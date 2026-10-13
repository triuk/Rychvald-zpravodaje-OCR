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

Další stabilní kódy přípravy jsou `invalid_parameters` (neplatné DPI),
`environment_invalid` (odmítnutý preflight), `configuration_changed` (změna
identity již zahájeného průchodu), `source_corrupt`, `invalid_source` a
`prepare_failed`. Odmítnutí preflightu nebo změny identity nenahrazuje dřívější
platný checkpoint ani schválený model.

## Rozhraní pro explicitní obnovu

`tools/ocr_project_prepare.py` vystavuje:

```python
prepare_project(registry, project_id, *, dpi=300, language='ces', environment=None)
prepare_artifacts(source, work, *, dpi, language, native)
```

První funkce provádí preflight, zámek, kontrolu zdroje a aktualizaci malých
projektových metadat. Druhá používá ověřený `NativeEnvironment` a jednotkové
checkpointy; nyní přijímá nový nebo již dokončený průchod. Obnova může rozšířit
její explicitní vstup pro přerušený průchod bez změny rasterizace, cache identity
nebo ochrany ručních podkladů. Zdroj/parametry se odvozují z uložené identity,
jednotky se ověřují pomocí checkpointů a poškozené/chybějící se dopočítávají.
