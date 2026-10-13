# Registr projektů vydání

`tools/ocr_projects.py` eviduje zdrojová PDF a nezávislé průchody. Import, seznam
a stav používají pouze standardní knihovnu Pythonu; nespouštějí OCR ani nevyžadují
jeho runtime. Pro vlastní rozpoznání nadále platí [OCR workflow](ocr-workflow.md).

```bash
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json import '/cesta/vstup.pdf'
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json import '/cesta/vstupní složka'
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json list --offset 0 --limit 10
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json status PROJECT_ID
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json import '/cesta/vstup.pdf' --new-run
```

Složka se načítá bez rekurze; importují se soubory s příponou `.pdf`, bez ohledu
na velikost písmen. Zdroj musí obsahovat PDF hlavičku. Úplné otevření a ověření
PDF patří přípravě OCR. Opakovaný obsah vrací první registrovaný projekt, i když
kopie má jiný název; `original_name` uchová jméno prvního importu. `--new-run`
vytvoří nový projekt/průchod se samostatnou prací a výstupy. Stejný název s jiným
obsahem vytvoří jinou identitu. PDF není upravováno; kontrolovaná kopie je uložena
pod SHA-256 obsahu.

Pod kořenem vzniká `registry.json`, `inputs/HASH.pdf`, `work/PROJECT_ID/project.json`
a plochá složka `outputs/`. Plánované PDF/TXT mají jméno `PROJECT_ID-ocr.pdf/txt`,
takže jiné vydání ani nový průchod nepřepíší předchozí výstup. Ostatní soubory,
včetně prototypových experimentů, zůstávají zachované a nejsou automaticky
považované za ověřené. Import začíná s `phase: registered`,
`operation_state: idle`, `validation: not_run`, `acceptance: not_recorded`.

## Procesový protokol verze 1

Každá běžná odpověď je jeden platný UTF-8 JSON včetně LF do **4096 bajtů**.
JSON je výchozí formát; `--json` jej výslovně deklaruje. Obsahuje
`protocol_version`, `operation`, `status`, `project`, `counts`, `artifacts`, `error`.
`project` váže `project_id`, `run_id`, `source_sha256`, `original_name` a oddělené
stavy fáze, operace, validace a přijetí. `status: completed` a návratový kód 0
říkají, že daný příkaz proběhl; nepotvrzují správnost přepisu.

Cesty v `artifacts` jsou relativní ke kořenu registru. Stav projektu vrací
`source`, `workspace`, `project`, `output_pdf`, `output_txt` a projektové počty.
Složkový import vrátí jen počty a odkaz na registr; identity získá následný seznam.
`list` obsahuje `projects`, `counts.total`, `counts.returned` a `next_offset`.
Požadovaný `--limit` je horní mez; počet skutečně vrácených položek může být menší
kvůli limitu bajtů. Pokračuj přes přesně vrácený `next_offset`, dokud není `null`.
Úplný přepis se do odpovědi nenačítá. Diagnostika nepatří do strojového stdout.

Chyba má `status: failed`, návratový kód 1 a objekt `error` s `code` a stručným
`message`. Stabilní kódy: `invalid_arguments`, `invalid_selection`,
`source_missing`, `invalid_source`, `source_changed`, `source_corrupt`,
`registry_invalid`, `project_not_found`, `project_invalid`, `project_busy`,
`identity_changed`, `response_too_large`, `io_error`. Neplatný registr není
přepsán novým prázdným registrem.

## Rozhraní pro navazující příkazy

```python
from ocr_projects import ProjectRegistry, ProjectError, atomic_json, response, emit_response

registry = ProjectRegistry(root)
record, created = registry.import_source(source, new_run=False)
record = registry.get(project_id)
page = registry.list_projects(offset=0, limit=10)

with registry.project_lock(project_id) as record:
    workspace = registry.root / record['artifacts']['workspace']
    # Zámek drž přes všechny OCR podprocesy a zápisy checkpointů.
    # Větší průběžné artefakty zapisuj samostatně pomocí atomic_json(path, value).
    record['project']['phase'] = 'prepared'
    record['project']['operation_state'] = 'completed'
    record['counts']['pages'] = page_count
```

`record` obsahuje `project`, `artifacts`, `counts`; kontext zámku atomicky uloží
upravený `project.json` jen po úspěšném dokončení. Identita projektu je neměnná.
Výjimka nechá původní metadata zachovaná. `get` a `status` označí skutečně držený
zámek jako `operation_state: running`; uložené `running` bez vlastníka označí jako
`interrupted`. Po pádu procesu se Linux zámku automaticky zbaví; soubor
`.operation.lock` může zůstat a není sám důkazem běžící operace.

Importy používají společný zámek registru. Registry a metadata se zapisují do
dočasného souboru ve stejné složce a zveřejní jedním přejmenováním po flush/fsync.
Přerušený zápis zachová poslední platný registr; neúplný dočasný soubor se nečte.
Při přerušeném složkovém importu lze stejný import opakovat: již dokončené projekty
se vrátí jako existující. Není potřeba mazat pracovní složky.
