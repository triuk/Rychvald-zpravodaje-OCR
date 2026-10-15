# Živá místní příprava v GUI

Vyberte pojmenovaný průchod s uloženým profilem a použijte „Spustit místní
přípravu“. DPI a jazyk se převezmou z neměnné kopie profilu. Pro jiné parametry
založte nový průchod. Volitelné pole prostředí vybírá konkrétní manifest;
prázdné pole použije určené prostředí samostatného OCR procesu. Zvolená cesta
se při obnově přehledu zachová a opakovaný pokus ji svévolně nemění.

Příprava používá stávající nativní příkaz `prepare`. Ověří přesný runtime,
programy, knihovny, modely, konfigurace a fonty před rastrováním nebo OCR.
Pracuje v samostatném pracovním adresáři vybraného průchodu. Úspěšné kandidátní
OCR není potvrzený přepis: validace obsahu zůstává `not_run` a přijetí
zadavatelem `not_recorded`.

GUI průběžně ukazuje skutečně aktivní kroky, čas od zahájení pokusu, dokončené
ověřené rastry stránek a úlohy OCR. Započítá jednotku až po ověření jejího
checkpointu a hashů výstupů. Platná převzatá cache má samostatný stav a počty;
zahájená nebo neúspěšná práce se nepovažuje za dokončenou.

Dlouhé zpracování běží ve vlastněném procesu mimo GUI callback. Během něj
lze obnovovat přehled a vybírat průchody. Otevření jiné evidence nebo spuštění
další přípravy vrátí srozumitelný stav `operation_active`. Kořen evidence je
uložen s pokusem; pracovní proces nepřebírá pozdější změny výběru v GUI.
Zavření aplikace ukončí její aktivní skupinu procesů a uchová nedokončené
checkpointy. Ovládání pozastavení/pokračování není součástí tohoto přírůstku;
stávající samostatný příkaz `resume` zůstává zachován.

## Veřejné operace

Nové operace používají stejný `Application.dispatch` jako ostatní GUI:

| Operace | Payload | Výsledek |
| --- | --- | --- |
| `start_preparation` | `run_id`, volitelně `environment` | Okamžitě vrací novou identitu pokusu a stav `starting`/`running` |
| `preparation_status` | `run_id` | Aktuální či poslední uložený pokus, kroky, čas, počty, události a platnost checkpointu |

Parametry `dpi` a `language` v požadavku nelze použít ke změně uloženého
profilu. Odlišné hodnoty vrátí `configuration_changed` před spuštěním a zápisy.
Starší průchod bez profilu vrátí `run_profile_required`.

Stavy jsou `not_started`, `starting`, `running`, `completed`, `failed`,
`interrupted` a `invalidated`. `completed` znamená ověřenou místní přípravu
tohoto pokusu. Neúspěšný další pokus nemaže dříve platné podklady; fáze
průchodu a stav posledního pokusu jsou samostatné údaje. Změní-li se artefakt
uloženého úspěšného pokusu, dotaz vrátí `invalidated` a `checkpoint_invalid`.
Pouhá přítomnost souboru se stavem `completed` nestačí.

`counts` rozlišuje `pages_total`, `pages_completed`, `ocr_total`,
`ocr_completed`, `rasters_cached` a `ocr_cached`. `active_steps` obsahuje
identifikátory skutečně zahájených a dosud neukončených kroků. `events`
vrací posledních nejvýše 200 událostí pokusu; úplná evidence zůstává na disku.
`elapsed_seconds` měří skutečně uplynulý čas. GUI navíc může odebírat události
`preparation_progress` a `preparation_finished` přes dosavadní kurzor událostí.
`totals_known` rozliší zatím nezjištěný počet stránek od známých počtů;
neznámý počet se v GUI nezobrazuje jako dokončených nula stran z nuly.

## Trvalá evidence a procesové rozhraní

Pokus se uloží před spuštěním procesu do
`work/RUN/application/attempts/ATTEMPT.json`. Obsahuje vlastní `attempt_id`,
identitu průchodu, zachycený kořen evidence, původní argumenty, časy, PID,
skupinu procesů, očekávané vstupy, návratový kód a případnou chybu. Vedle jsou
`ATTEMPT.stdout.json` a `ATTEMPT.stderr.log`. Výstup procesu zůstává jediným
souhrnným JSON protokolem verze 1 do 4096 bytů. Návratový kód 0 sám úspěch
přípravy neprokazuje.

Kompatibilní volitelné přepínače příkazů `prepare` a `resume` jsou:

```text
--progress-events /evidence/work/RUN/application/history.jsonl
--attempt-id 32_HEXADECIMÁLNÍCH_ZNAKŮ
```

Cesta událostí musí být ve vybraném pracovním adresáři. Události se atomicky
připojují pod zámkem souboru a synchronizují na disk. Nemísí se do stdout.
Bez přepínače nevzniká nový proud událostí a původní volání zůstávají platná.

Události obsahují `event_id`, `attempt_id`, `run_id`, `step_id`, UTC čas a
uplynulý čas. Identita události se při dotazu ani restartu negeneruje znovu.
Jednotky mají stabilní jména `raster:page:N` a `ocr:page:N:psm:P`. Typy
`unit_started`, `unit_completed` a `unit_cached` rozlišují zahájení, novou
ověřenou práci a ověřenou cache. Události ukončených kroků mají skutečné
`duration_seconds`. Ověření prostředí zaznamená jeho manifest a identitu.
Selhání má kód, vysvětlení a dostupnou příčinu; nepředstírá dokončení jednotky.
Ukončení procesu signálem doplní vlastník procesu trvalou událostí chyby.

Před zveřejněním dokončeného checkpointu nativní proces znovu ověří:

- identitu a neměnnost zdrojového skenu a manifestu;
- checkpointy a hashe každého rastru a přehledu;
- identitu prostředí a vstupního obrazu každého kandidátního průchodu OCR;
- hashe hOCR, TSV, TXT a BOX vůči dokončeným jednotkovým checkpointům;
- dostupnost souhrnných podkladů a jejich hashe.

Dokončený `preparation-checkpoint.json` nově obsahuje index `outputs`.
Následná událost `checkpoint_completed` uloží jeho SHA-256. Vlastník procesu
nezávisle ověří, že tento pokus má ověřené prostředí, odpovídající checkpoint
a všechny povinné artefakty s očekávanými hashi. Poškozená jednotka se při
dalším platném příkazu znovu spočítá podle dosavadních pravidel cache.

## Vývoj a ověření

GUI a OCR mohou používat odlišné Python runtime. Pro vývoj lze spustit:

```sh
python main.py --root /cesta/k/evidenci --ocr-python /cesta/k/ocr/.venv/bin/python
```

Přibalený samostatný OCR proces se nadále vybírá pomocí `--ocr-executable`.
Do argumentů se předávají seznamy bez shellu. Krátké dotazy používají omezený
čas čekání; dlouhý pracovní proces tento limit nemá.

`test_webui_preparation.py` používá skutečný rastrový sken s předem známým
nápisem, ověřené prostředí a skutečný Tesseract přes veřejné GUI operace.
Ověří živé dotazy, identifikátory a časy, cache, jiná DPI v novém průchodu,
chybné prostředí, poškozený artefakt, ukončený proces, restart a zachování
zdroje i předchozí práce. Regrese přípravy a obnovy zůstávají v
`test_ocr_project_prepare.py` a `test_ocr_project_resume.py`.

Skutečný nativní scénář lze spustit takto:

```sh
python tools/smoke_webui_projects.py --browser Chromium --preparation \
  --ocr-python /cesta/k/ocr/.venv/bin/python \
  --screenshot /tmp/native-preparation.png --evidence-directory /tmp/ocr-proof
```

Vytvoří osmistránkový rastrový sken se známým obsahem, použije skutečné
formuláře GUI, během místního OCR klikne na Obnovit a ověří odezvu za běhu.
Poté ověří dokončení, platnou cache a chybu chybějícího prostředí. Lze přidat
`xvfb-run -a` pro prostředí bez displeje. Screenshoty a volitelná kopie
skutečných podkladů zachovají důkazy mimo pracovní strom. Scénář nepoužívá AI
a nepotvrzuje přepis ani přijetí zadavatelem.
