# Příprava kandidátů projektu

Po [importu](project-registry.md) vyber projekt a spusť přípravu:

```bash
.venv/bin/python tools/ocr_projects.py --root '/cesta/archiv vydání' --json prepare PROJECT_ID
.venv/bin/python tools/ocr_projects.py --root '/cesta/archiv vydání' --json prepare PROJECT_ID --environment /cesta/environment.json --language ces --dpi 300
```

Příkaz před každým zápisem ověří nativní prostředí, zamkne projekt a kontroluje
hash jeho zdroje. Zachovává původní rasterizaci bez obrazových změn, přehledy
1250 × 1800, PSM 3/11, hOCR/TSV/TXT/box a nejvýše dva OCR podprocesy. Přepis
`fresh-lines.json` tvoří kandidáty. Nevytváří potvrzení vizuálního čtení, přijetí
uživatelem ani `review.json`; stav je `phase: prepared`, `validation: not_run`.
Navazující čtení a geometrie se řídí [workflow](ocr-workflow.md).

Opakování **dokončené** přípravy ověří uložené jednotky. Nezměněný rastr i OCR
průchod jsou cache hit; chybějící či poškozený výstup se přepočítá. Projektový
souhrn vrací `pages`, `rasters_computed`, `rasters_reused`, `ocr_computed`,
`ocr_reused`, `lines`, identitu projektu a odkazy na podklady. Platí protokol
verze 1 s maximem 4096 bajtů UTF-8 na stdout; logy a plné podklady zůstávají
v pracovním prostoru. `review.json`, historie oprav a očekávání se nepřepisují.

Parametry a ověřená sada prostředků se po zahájení vážou k danému průchodu.
Změna DPI/jazyka nebo explicitně schválený jiný manifest vyžaduje import
`--new-run`. Nesouhlasí-li skutečné bajty modelu, fontu či programu s manifestem,
příprava se odmítne bez přepsání podkladů. Pouhé ponechání jména modelu není
důvodem k opětovnému použití jeho starých kandidátů.

## Cache a checkpointy

`preparation-checkpoint.json` obsahuje verzi, identitu celého průchodu a stav
`running`, `completed` nebo `failed`. Při dokončení odkazuje na vstupní manifest,
příkazy a kandidátní řádky a obsahuje počty.

Každý rastr má `raster/page-N-checkpoint.json`: hash zdroje, stránku, DPI,
verzi a obsahové SHA-256 rendereru, geometrii a hashe rastru/přehledu. Každý
kandidátní průchod má `ocr/page-N-psmS-cache.json`: skutečný příkaz, hash obrazu,
parametry, jazyk, Tesseract, **obsahové hashe použitých jazykových modelů**,
identitu prostředí a hashe všech výsledných formátů. Stejná pravidla platí pro
lokální OCR oblastí i cílené varianty původního/podpůrného obrazu.

Checkpoint se nejprve atomicky označí `running`, potom se spočítá jednotka a až
po ověření všech výsledných souborů se atomicky zapíše `completed`. Pouze
`completed` se shodnou identitou a všemi výstupními hashi je cache hit. Záznam
neúplné jednotky nebo poškozený cache soubor není dokladem dokončení.

Linux zámek jednoho projektu zůstává držen přes OCR podprocesy. Souběžný zápis
vrátí `project_busy`; jiný projekt lze připravovat dál. `status` ukazuje
`running` při živém vlastníkovi. Po náhlém ukončení zůstane checkpoint zachovaný
a stav ukazuje `preparation_interrupted` / `interrupted`. Běžné selhání uloží
`preparation_failed` / `failed`, diagnostiku `preparation-error.log` a stabilní
chybu `prepare_failed`.

Přerušený průchod se neobnovuje implicitním `prepare`: vrátí `resume_required`.
Explicitní obnova používá stejné identity a jednotkové checkpointy a je
samostatnou navazující operací.

## Pokračování přerušeného průchodu

```bash
.venv/bin/python tools/ocr_projects.py --root '/cesta/archiv vydání' --json resume PROJECT_ID
```

`resume` použije původní DPI, jazyk a cestu manifestu prostředí. Nepřejde
automaticky na výchozí300 DPI/ces nebo jiné prostředí. Volitelné `--dpi`,
`--language` musí původním hodnotám odpovídat; `--environment` může změnit
umístění shodného manifestu. Rozdílná sada vyžaduje import `--new-run`.
Projekt dosud bez zahájené přípravy vrátí `resume_unavailable`; začni `prepare`.

Kontrola zdroje, prostředí a uložené identity předchází přepisu podkladů.
`configuration_changed`, `environment_changed`, `environment_invalid` nebo
`source_corrupt` vysvětlí nesoulad v malé odpovědi. Nový běh zachová původní
pracovní prostor; není potřeba ho mazat. Původní manifest z nedostupného
umístění lze zadat novou cestou, jeho obsah a identita ale musí zůstat shodné.

`preparation-identity.json` se atomicky zapíše před prvním průběžným checkpointem
a odděleně zachová identitu přípravy i cestu ověřené sady. Při poškozeném nebo
chybějícím hlavním checkpointu obnova použije tento záznam; starší projekty lze
obnovit z platné identity hlavního checkpointu nebo vlastního vstupního
manifestu. Pokud není žádný důvěryhodný záznam identity, vrátí `checkpoint_invalid`
a nabídne nový explicitní běh. Rozpor dvou platných identit vrátí
`checkpoint_conflict`; nepřijme jednu z nich potichu.

Každý dokončený rastr musí mít shodnou identitu, geometrii zdroje, rozměry obrazu
a hashe rastru/přehledu. Každý kandidátní průchod musí mít shodnou úplnou identitu
a hashe všech formátů. Obnova nepřepisuje platné jednotky; dopočítá neúplné,
chybějící nebo poškozené. Stejný vstupní manifest zachová i jeho původní bajty.
Po neúspěchu lze příčinu odstranit a `resume` opakovat. Další SIGKILL zanechá
nový checkpoint, který se opět ověří při následující obnově.

Živý Linux zámek vrátí `project_busy`. Soubor zámku bez vlastníka pokračování
neblokuje; stav odliší `running` od `interrupted`. Obnova chrání poslední
`review.json`, historii oprav/iterace, doklady nálezů, očekávání i předchozí
PDF/TXT. Zaznamenanou pozdější fázi revize a její stav zachová také při selhání
a dalším pokračování; nejde o nově provedenou obsahovou validaci. První
úspěšná příprava stále vrací `prepared`/`not_run`.

Integrační testy obnovy opravdu ukončují procesovou skupinu SIGKILL mezi
stránkami a kandidátními průchody, přerušují i další pokračování a ověřují
znovupoužití dokončených souborů, živý zámek a zachování ruční práce. Nejde
o simulaci změnou návratové hodnoty workeru.

Další stabilní kódy přípravy jsou `invalid_parameters` (neplatné DPI),
`environment_invalid` (odmítnutý preflight), `configuration_changed` (změna
identity již zahájeného průchodu), `source_corrupt`, `invalid_source` a
`prepare_failed`. Odmítnutí preflightu nebo změny identity nenahrazuje dřívější
platný checkpoint ani schválený model.

## Rozhraní pro explicitní obnovu

`tools/ocr_project_prepare.py` vystavuje:

```python
prepare_project(registry, project_id, *, dpi=300, language='ces', environment=None)
resume_project(registry, project_id, *, dpi=None, language=None, environment=None)
prepare_artifacts(source, work, *, dpi, language, native, resume=False, retained_state=None)
```

`prepare_project` provádí preflight, zámek, kontrolu zdroje a aktualizaci malých
projektových metadat. `resume_project` odvodí původní konfiguraci, odmítne živou
operaci a použije stejnou transakci s explicitní obnovou. `prepare_artifacts`
používá ověřený `NativeEnvironment` a jednotkové checkpointy bez změny
rasterizace nebo OCR algoritmu. `retained_state` přenese zaznamenanou pozdější
fázi projektu přes další přerušení, nový průchod ji nevytváří.
