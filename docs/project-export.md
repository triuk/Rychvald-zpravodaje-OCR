# Export projektu a pravdivá validace

Projekt nejprve importuj a [připrav](project-preparation.md). Z přehledů a
zdrojových rastrů odvoď místní oblasti, přepis, pořadí článků, geometrii a
nezávislé výběrové vzorky podle [workflow](ocr-workflow.md). Dosavadní veřejné
`regions` a `draft` vytvoří místní kandidáty a neověřený návrh `review.json`;
[projektový patch](project-review.md) používá stejné strukturované opravy.
Žádný z těchto kroků nezastupuje skutečné úplné první vizuální čtení.

```bash
.venv/bin/python tools/ocr_projects.py --root '/cesta/archiv vydání' --json export PROJECT_ID
.venv/bin/python tools/ocr_projects.py --root '/cesta/archiv vydání' --json validate PROJECT_ID
```

Oba příkazy přijímají `--environment MANIFEST`; sada musí odpovídat přípravě.
`export --reviewer-root PATH` přidá skutečně dostupný reviewer do technických
kontrol. Export odvodí vstup/work/výstupy z projektu, ověří prostředí a zdroj,
pod zámkem ověří celý potvrzený přepis a použije zachovanou konstrukci F:
segmentace → diagnostické překryvy → zdrojové výběrové náhledy → PDF/TXT →
technické kontroly → výběrové kontroly → neověřené reportové šablony.
Očekávání musí být předem dodaná v neprázdném `samples.json` ze zdroje.
Export je sám nevytváří ani nepřizpůsobuje extrakci výsledku.

## Výstupy, iterace a stav

Každý export vytvoří nová plochá PDF/TXT jména
`outputs/PROJECT_ID-ITERATION_ID-ocr.pdf` a `.txt`. Řiď se vrácenými
`artifacts.output_pdf/output_txt`, nikoli původním plánovaným názvem při importu.
Jiné vydání se stejným vstupním názvem ani nová iterace nepřepíší staré soubory.
Před regenerací podkladů se předchozí výstup, manifesty, frozen přepis/vstupy,
reporty, konstrukce a metadata projektu uloží do `work/iterations/`.
Doklady a historie oprav zůstanou zachované; velké OCR/rastry se evidují hashi.
Změněný starý PDF/TXT se nearchivuje jako platný: export se odmítne.

`output-manifest.json` váže zdroj, projekt/průchod/iteraci, potvrzený přepis,
výběrová očekávání, PDF i TXT. Projektová validace navíc ověří totožnost
projektu, průchodu, iterace a skutečných výstupních cest s registry.
Nový export má `phase: exported`, `operation_state: completed`,
`validation: not_run`, `acceptance: not_recorded`. Předchozí přijetí nebo
kontrolní pokrytí se nepřenáší jako potvrzení nové iterace.

Zámek chrání celý export i validaci; souběžný zapisovač vrací `project_busy`.
Atomicky uložené `exporting/running/not_run` předchází výpočtu. Pád procesu se
zobrazí jako `export_interrupted/interrupted`; běžné selhání jako
`export_failed/failed`, s `export-error.json` a `export-process.log`.
Předchozí ploché výstupy a archivované iterace zůstávají použitelné.

## První čtení a výsledky kontrol

Export nepotvrdí kandidátní přepis. Vizuální report začíná bez čtenáře,
zkontrolovaných stran a dokladů. Doplň skutečný rozsah prvního čtení, doklady
a jednotlivé důvody otevřených nálezů podle [datové smlouvy](ocr-data-contracts.md).
Šablona ani pouhý výpočet OCR/výřezu tento požadavek nesplní. Po opravě se staré
hashové vazby přepisu/reportů odmítnou; proveď novou segmentaci/export/kontroly
a zapiš nový aktuální vizuální report.

| Kód `validate` | `project.validation` | Význam |
|---|---|---|
| 1 | `failed` | Selhala povinná kontrola, vazba, úplnost nebo doklad. |
| 2 | `ready_with_open_items` | Povinné podmínky prošly; zůstávají konkrétní důvodem a doklady podložené otevřené nálezy. |
| 0 | `verified` | Povinné kontroly jsou doložené v zaznamenaném rozsahu. |

Příkaz validace může být `status: completed`, i když obsahový výsledek je
`failed` a návratový kód 1: operace proběhla a uložila neúspěšný report.
Návratový kód úspěšného exportu 0 není obsahové `verified`. Přijetí konkrétní
iterace zadavatelem je stále samostatné rozhodnutí.

## Volitelné pokrytí a doslovné extrakce

Schránka `not_tested` není otevřeným nálezem a nepotvrzuje UI kompatibilitu.
Neprovedená integrace revieweru je obdobně výslovné pokrytí `not_tested`, nikoli
automatická chyba OCR. Je-li reviewer skutečně zapojen, jeho přítomné kontroly
se ověří a skutečné selhání zůstane chybou; neúplná dvojice kontrol se odmítne.
Report uvádí otestované stránky a případné částečné pokrytí. Žádné chybějící
booleany se nedoplňují na `true`.

Připnutý Poppler 26.08.0 v kontrolovaném syntetickém průchodu vrací `OCR 11`
bez posledního LF, zatímco společný přepis/TXT má `OCR 11\n`. Tato jediná
konkrétní odlišnost rámování extraktoru je zaznamenaná samostatně jako
`single_terminal_lf_omitted`. Původní doslovné bajty i `poppler_literal_equal:
false` zůstávají zachované. Validátor znovu ověří soubory proti zmrazenému
exportnímu přepisu a povolí pouze **přesné vynechání jednoho koncového LF**.
Vnitřní mezery, vnitřní/dvojité newline, jiné znaky nebo jiná koncová odlišnost
se tím nenormalizují. Další doslovné rozdíly zůstávají chybami nebo samostatně
doloženými otevřenými nálezy. TXT, text znaků, pořadí jednotek, výběrové kontroly,
obraz a geometrie mají své nezměněné povinné kontroly.

Krátká odpověď protokolu 1 má do 4096 bajtů UTF-8, počty, odkazy a souhrn
`coverage`. Úplné chyby/nálezy, booleany, přesné extrakce a doklady jsou v
`checks/run-validation.json`, `checks/run-summary.md` a jednotlivých kontrolách.

## Rozhraní pro instalovaný proces

```python
export_project(registry, project_id, *, environment=None, reviewer_root=None)  # record
validate_project(registry, project_id, *, environment=None)  # (record, 0|1|2)
```

Funkce jsou v `tools/ocr_project_export.py`. Volají zachované veřejné příkazy
`ocr_workflow.py`; procesové argumenty jsou předané jako seznam, bez shellové
interpolace. Nový `export --previous-snapshot PATH` v původním CLI umožňuje
ověřený předem uložený archiv uvnitř daného work a zabrání dvojité archivaci.
Samostatné původní exporty bez tohoto argumentu archivují stejně jako dříve.
