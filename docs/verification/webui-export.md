# První autonomní export — ověření #17

Implementace vychází z integration `669c283`. Veřejná `start_autonomous` akce
prochází importem, přípravou, přesným model/context preflightem, nezávislým čtením,
geometrií, nativním exportem, skutečnou výstupní kontrolou a validací. Provozní
kontrakt a přesné pokračování již připraveného exportu popisuje
[webui-export.md](../webui-export.md).

## Kontrolované veřejné testy

`tests/test_webui_export.py` pracuje přes dispatch a nativní CLI se skutečným
dvoustránkovým rastrovým PDF. Procesní protějšek je výslovně řízená fixture,
nikoli doklad skutečné modelové kontroly. Ověřuje celou autonomní akci, rezervaci
průchodu mezi etapami, PDF/TXT ze společného přepisu, neměnný zdroj, původ metrik,
explicitní CAS pokračování bez nového exportu/čtení a přesné původní modelové JSON.

Záporné případy odmítají zahození nálezů, nepodložené povýšení aproximace i při
prázdném seznamu jednotlivých otevřených problémů, šablonu, cizí existující PDF
jako doklad, změněné přiložené pixely a změněnou geometrii. Kladný případ zachová
absolutní aliasy původních obrazů a neměnných vstupních snapshotů bez přepsání
původního JSON. Neplatný checkpoint se odmítá před vytvořením výstupu;
podvržený starý finalrender se před odesláním regeneruje z aktuálního PDF.

Durable logy jsou v `PROJECTROOT/.scratch/ticket-17-proof/`:

- `frozen-evidence-alias-green.log`: celý řetězec, CAS pokračování, absolutní
  aliasy a záporné případy, 53,687 s, OK. Předchozí odpovídající RED zachován.
- `approximation-waiver-red.log` / `approximation-waiver-green.log`: konkrétní
  neplatné povýšení geometrie reprodukováno bez uměle vloženého otevřeného řádku,
  následně odmítnuto; kladný výsledek zůstává `ready_with_open_items`.
- `native-export-final.log`: 13 nativních exportních testů, 220,624 s, OK.
- `geometry-regressions.log`: 8 testů navazující geometrie, 74,394 s, OK.
- `reading-metrics-regressions.log`: 21 testů čtení a metrik, 23,718 s, OK.

Ověření nepřepisuje nativní sémantiku odstavců/článků ani source-derived očekávání.
Dva samostatné články v řízené fixture mají dokumentovaný oddělovač tří LF.

## Skutečné modelové důkazy

Byly znovu použity dokončené skutečné běhy #15/#16 a původních 13 syntetických
a 3 reálných source-only vzorků. První čtení ani geometrické tahy se neopakovaly.
Nativní export použil přesný zkoumaný checkpoint pod projektovým zámkem.
Následovaly právě dva chybějící postexport tahy nad skutečnými hotovými PDF:

| Předloha | Průchod | Output-review attempt | Původní thread / turn |
| --- | --- | --- | --- |
| Nová fiktivní dvoustránková předloha | `22d0903ed909-1283960bdfa0` | `51c796d4e52a4ddc9332cac02cfd86e5` | `01a1583a-c2ef-79d3-8243-f218f154bbee` / `01a1583a-c440-7322-bce6-c9738e02d4ee` |
| Reálný výřez 05/2000 | `06c775631212-6875223ed720` | `7df1ec8ad7b74123976fe3f63de5ec9d` | `01a15a38-d533-77d1-8a58-aac7a7ea9879` / `01a15a38-d925-7bc3-b709-39714a0ef456` |

Konkrétní disclosure `prepared-postexport-disclosure.json` má SHA-256
`805241e5ab6e12960ad6f556892d7f525e1bc6256df336bc198b7c9bdc028317`.
Obsahuje přesné prompty, schéma, instrukce, běhové identity a všech 26 + 10
přiložených obrazů. Root nezávisle ověřil jejich hashe i source/final pixely.
Po dvou zachovaných automatických odmítnutích uživatel výslovně povolil odeslání
fiktivních testů, reálného výřezu a odvozených kontrolních obrazů do ChatGPT.
Následující standardní přezkum oba přesné požadavky přijal. Odmítnuté požadavky
nevytvořily žádný proces, attempt ani modelový tah.

Oba dokončené návrhy prošly původním protokolem, kontrolou skutečných příloh,
modelem `gpt-6.1-sol/high`, nativním publikačním CAS a nativní validací. Výsledek
obou je `ready_with_open_items`, bez validačních chyb; uživatelské přijetí je
samostatné `not_recorded`. Syntetický report ponechává čtyři doslovné rozdíly
stránkového formátování v extraktorech a aproximaci geometrie. Reálný report
ponechává dva doslovné rozdíly extraktorů, aproximaci, oba původní otevřené řádky
`p1-l002`/`p1-l004` a nevyřešené zdrojové místo. Zdrojový registr nejistot i tři
původní rizikové záznamy zůstávají beze změny. UI clipboard není automaticky
považován za otestovaný a předmětem reportu není uživatelské přijetí.

`final-audit-handoff.json` a `audit-final.log` dokládají znovuodvození obou
původních dokončených tahů, nativní `verify-output-review` s návratovým kódem 0,
shodu reportů s původním modelovým JSON, neměnný PDF UUID, source/preparation
CAS, obrazové hashe i 50 syntetických a 33 reálných původních artefaktů. Množiny
reading/geometry attempts jsou identické s předexportním stavem. Původní
protokoly/proposals jsou pod kanonickým registry běhu #15 v
`application/output-review-attempts/<attempt>/output_examination/`.

Reálný tah se dokončil `2026-10-20T16:51:44.696336Z` po dlouhé lokální pauze
od spuštění `07:36:54Z`. Tento téměř devítihodinový klientský wall-time není
měřením výpočtu poskytovatele. Audit uvádí největší mezeru původních událostí,
ponechává provider compute jako neznámý a nemění původní usage či nulami
nenahrazuje chybějící části. GUI metrik už výslovně rozlišuje čas aplikace od
výpočtu poskytovatele.

## GUI a přenositelnost důkazů

Nativní WebUI používá přesnou místní kopii 21 souborů WebUI2 2.5.8, původní
clang-x64 knihovnu s SHA `59b7230ee0a6608ea6fa5bd38cf327851c0a0cc980976b13793723d25dacf768`
a obnovený Python 3.14.7 s `-B`. Preimport guard ověřuje knihovnu dříve, než by
její standardní loader mohl zkusit stažení. Nic se neinstalovalo ani neměnilo
globálně. Actual GUI summary/metrics a původní snímky jsou v
`native-synthetic/` a `native-difficult/`. Dokončené doplňkové read-only captures
jsou v `native-synthetic-completed-gui-v3/` a
`native-difficult-completed-gui-v2/`: oba `summary.json` potvrzují dokončení bez
nového modelového požadavku. Root skutečně prohlédl jejich `native-gui.png` a
`native-open-items.png` (visual PASS): čitelných 5/6 otevřených nálezů, bez
vodorovného přetečení, oddělené `ready_with_open_items` a `not_recorded`; u
reálného výřezu zůstávají blur/clip a source unknown. Snímky vznikly sekvenčně
po vykreslení výsledků i terminálního stavu. Žádný modelový tah se kvůli nim
neopakoval. Dřívější neúplné captures zůstávají označené jako neúplné.

Původní generující `ocr_workflow.py`, `ocr_quality.py` a F zůstaly byte-identical
s checkpointem #16. Přesné kopie zdrojových cest #15/#16/#17 jsou navíc uložené
v `exact-code-archive/` s hashi. Archiv sám není aktivním přesměrováním cesty:
vydání #23 musí zachovat původní cesty nebo zavést auditované rozlišení přes
exact SHA. Původní pakety/protokoly nelze kvůli úklidu worktree tiše přepsat.
Fresh actual full-bundle průchod je samostatný finální důkaz #22/#23; tento
výstupní důkaz již správně neopakuje hotová čtení při každém mezistupni.
