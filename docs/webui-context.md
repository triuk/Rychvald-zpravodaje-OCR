# Context-mode, směrování a obnova v GUI

V pojmenovaném průchodu s profilem `gpt-6.1-sol` a úsilím `high` zvolte
„Ověřit context-mode“. Jde o skutečný řízený AI test přes přihlášený účet
ChatGPT: vytvoří syntetický místní výstup, použije context-mode pro jeho
uložení a dohledání a obnoví stejné vlákno po nativní kompaktaci a restartu
app-serveru. Nezpracovává zdrojové PDF ani nepřikládá obraz nebo přepis.
Místní příprava a modelový diagnostický krok zůstávají oddělené.

GUI rozlišuje `context_verified` od `model_verified` a od odvozeného
`autonomous_ocr_ready`. Celá kombinace je připravena pouze při dokončeném
platném context testu a platném obrazovém ověření tohoto průchodu.
Samotná registrace MCP, katalog modelů, úspěšný návrat procesu nebo pouhá
textová odpověď nestačí. Chybějící prostředky, nedůvěryhodný hook,
nesprávný model, přesměrování, nesprávné dohledání nebo nefunkční obnova
neumožní vykázat připravenost. Dokončený test není dokončený OCR přepis,
validace věrnosti ani přijetí zadavatelem.

Při změně výběru průchodu se staré akce ihned odstraní. Pozdní odpověď
staršího výběru nemůže znovu zobrazit ovládání jiného průchodu.

## Přesná sada prostředků bez instalace za běhu

`native/context-runtime.json` připíná context-mode **1.0.169**, Node.js
**24.21.0**, Python a shellové interpretery. Vybraná produkční sada má
4578 souborů, obsahuje původní hooky, session/security bundly, server bundle
a lokálně dostupnou produkční dependency closure bez nepoužívaného
`better-sqlite3`. Hashuje se celá sada včetně relativních jmen souborů.

- Původní sada: `6207b687a1606af3fe46f63ce3e6a3ee0ae9315c1612a37b20633688026bf14b`.
- Připravená sada: `e6304ac4d20283362feda2d5287b8e008af48c9b7e3fb949414aa1f89fdd2c17`.

Tato výslovně nově připnutá sada pochází z upstream commitu
`03e831573f8964e9330008d1b456d40838d86df8` a z integritou ověřených npm
archivů. `native/context-source-inventory.json` obsahuje hash, velikost a
Git/npm původ každého souboru. Historická agregovaná sada po restartu nebyla
dostupná; důvod rozdílu historického hashe není znám a není vydáván za
obnovení stejných bajtů. Původní Codex hooky i adaptér bez instalací zůstaly
beze změny. Záznam změny uchovává `native/context-runtime-provenance.json`.

Při sestavení se jediný instalační bootstrap `hooks/ensure-deps.mjs`
nahradí kontrolou vestavěného SQLite FTS5 z
`native/context-no-install.mjs`. Původní hook entrypointy a jejich směrování
či session logika se nemění. Server se spouští přímo přes
`server.bundle.mjs`; upstream `start.mjs` s automatickými opravami se
nespouští. Změna a licence jsou uvedeny v
`native/context-mode-NOTICE.txt`; připravená sada zachovává původní LICENSE
a licence produkčních závislostí.

Příprava používá pouze již dostupné zamčené zdroje:

```sh
python tools/reconstruct_context_runtime.py \
  --upstream /cesta/git-objekty/context-mode --npm-cache /cesta/npm/_cacache \
  --output /cesta/nove-zdroje/context-mode
python tools/prepare_context_runtime.py \
  --source /cesta/nove-zdroje/context-mode --output /cesta/pripravene/context-mode
```

Příkaz odmítne jinou zdrojovou sadu i existující výstup. Nestahuje balíky,
nespouští npm ani nepřepisuje instalovaný plugin. Před každým testem aplikace
znovu ověří SHA-256 Codexu, jeho hostu, Node/interpreterů, celé připravené
sady a skutečný FTS5 probe. Při chybě nevytváří modelové vlákno.

Vývojový start může určit již připravenou sadu proměnnou
`RYCHVALD_CONTEXT_RUNTIME`; výchozí distribuční cesta je
`runtime/context-mode`. Neprobíhá automatická příprava ani oprava při
startu GUI. Přenositelnost celého balíku včetně dynamických knihoven je
součástí distribučního přírůstku, nikoli tohoto testu.

Pro výslovně vybranou stabilní vývojovou kopii lze zadat
`RYCHVALD_CODEX_RUNTIME` s cestou ke Codexu a `RYCHVALD_CONTEXT_BIN` s adresářem
`node`, `python3`, `bash`, `sh`. Každý soubor stále musí odpovídat přesnému
připnutému SHA-256; nejde o náhradu modelu, verze ani povolení změněného
prostředku. Distribuční balík používá své přibalené cesty.

## Důvěra a efektivní konfigurace

Codex si ponechá své běžné spravované přihlášení. Aplikace nečte ani
nekopíruje přihlašovací tokeny a nepřepisuje uživatelův globální config.
Všechny aplikační MCP a hook definice se předávají jako procesové
konfigurační argumenty. Zděděné pluginy jsou vypnuté, aby nevznikly duplicitní
pluginové hooky. Povolené jsou pouze nástroje `ctx_execute`,
`ctx_execute_file`, `ctx_batch_execute`, `ctx_index`, `ctx_search`,
`ctx_stats`; každý má explicitní aplikační `approval_mode = "approve"`.
`ctx_upgrade`, instalace a opravné nástroje nejsou vystavené.

První krátký proces provede pouze `hooks/list`. Aplikace vyžaduje přesně
šest známých příkazů a událostí, správný zdroj `sessionFlags` a zapnuté
handlery. Potom předá jejich skutečné `currentHash` jako procesové
`hooks.state.KEY.trusted_hash` a v novém procesu vyžaduje `trustStatus:
trusted` i shodu hashů. Neužívá přepínač pro obcházení hook trust.
Neočekávaný další hook znamená chybu před modelem.

Pro kompatibilní změnu shellového příkazu původním context-mode hookem
se v tomto testu používá nativní shell s vypnutým `unified_exec`.
Protokol musí doložit nejen spuštění PreToolUse, ale i skutečný přepsaný
příkaz `echo` s pokynem context-mode. Potom skutečný MCP `ctx_execute`
spustí přesný lokální generátor s výstupem 636061 bytů a `ctx_search`
dohledá unikátní hodnotu. Kontrola vyžaduje i reálný obsah FTS5 databáze.
Průběžné zprávy modelu se zachovávají v protokolu; očekávání se porovnává
s odpovědí označenou `final_answer`.

Pokud první tah prokazatelně skončil, správně dohledal hodnotu a doložil
ostatní hooky, ale úplně vynechal nativní příkaz, aplikace ve stejném vlákně
jednou vyžádá jen tento chybějící test přesměrování. Velký výstup ani hledání
neopakuje. Požadavek i nový tah zůstanou ve stejném vlastněném pokusu a jeho
historii; bez skutečného přepsaného příkazu diagnostika dál neprojde.
Nedokončený či chybový tah, chybná odpověď a chybějící další důkazy tento
doplňující požadavek nespustí. Načtení stavu ani obnova nepřidá další požadavek
na tuto opravu.

## Izolace a podporovaná obnova

Každý průchod má vlastní `work/RUN/context/workspace` a
`work/RUN/context/store`. MCP i hooky dostávají explicitní
`CONTEXT_MODE_PROJECT_DIR`, `CONTEXT_MODE_DIR`, vlastní dočasný adresář a
stejný určený PATH. Hooky a MCP navíc mají vlastní prázdný `CODEX_HOME`
pro session/config pomocné soubory; nepřebírají přihlašovací údaje.
App-server pro přihlášení dál používá svůj běžný spravovaný domov.
PATH zpřístupňuje konkrétní ověřený Codex, Node, Python a shelly.

Test provede `thread/compact/start`, ověří skutečný PreCompact a dokončenou
kompaktaci, ukončí svůj app-server a použije `thread/resume` se stejnou
identitou, modelem a úsilím. Obnovený SessionStart musí předat
`session_knowledge`; model skutečně prohledá `source: "session-events"`
a potom vrátí dříve uloženou znalost. Reálná session DB musí obsahovat toto
vlákno, správný pracovní kořen, události, `compact_count >= 1` a neprázdný
kompaktační snapshot.

Zvolená verze Codexu v doloženém scénáři spustila SessionStart při startupu
a resume, nikoli při kompaktaci. Snapshot proto zůstal `consumed: false`.
Ověřená obnova používá původní resume větev se session událostmi po skutečné
kompaktaci. Nedeklaruje spotřebování snapshotu nepoužitou compact větví.

## Veřejné operace a doklady

| Operace | Payload | Výsledek |
| --- | --- | --- |
| `prepare_context_diagnostic` | `run_id` | Přesná syntetická data, hash a oba pevné prompty bez modelu |
| `start_context_diagnostic` | `run_id` | Asynchronní skutečný test; použije nezměněná připravená data |
| `context_status` | `run_id` | Poslední pokus, živý/konečný stav, důkazy a odvozená připravenost |

Není-li vstup předem připraven, test vytvoří stejným místním postupem nový.
Změněná data, generátor, pevné prompty nebo AGENTS instrukce se odmítnou
před spuštěním Codexu. Syntetická očekávaná hodnota není součástí promptu;
vstupní soubor ji obsahuje jako znalost určenou k indexaci a dohledání.
Nejde o tvrzení, že je soubor před modelem technicky tajný.

Doklady jsou v `work/RUN/application/context-attempts/ATTEMPT/`:
`attempt.json`, `request.json`, `protocol.jsonl`, `stderr.log`. Události
průchodu mají `step_id: context_diagnostic`; aplikace publikuje průběžné
události a `context_finished`. Původní rámce mají čas, uplynulý čas, směr
a původní `message`; přibývá `connection_id` pro životní cyklus spojení.
Zachovávají se původní hook události, usage hodnoty i chybějící pole.
Usage se nepřiřazuje podle posledního aktivního tahu, ale podle původního
`threadId`/`turnId`. Kompaktace může mít vlastní serverový tah; jeho účtování
se nedoplňuje odhadem. `connections`, `turns` a `terminal_turns` uchovávají
procesy, fáze a skutečné identity; surový protokol zůstává rozhodující.

`tools/smoke_webui_context.py` používá skutečná nativní GUI tlačítka a
ověřuje správné načtení cílového průchodu. Bez `--run-diagnostics` pouze
obnovuje hotové výsledky. Se dvěma `--run-id` nezávisle ověří oddělené
pracovní kořeny/databáze/vlákna, přítomnost vlastní hodnoty a nepřítomnost
cizí hodnoty i cizího vlákna po dokončení obou testů. Screenshoty a původní
protokoly držte mimo repozitář. Řízené procesové fixtures v
`test_webui_context.py` ověřují chybové větve; nejsou dokladem skutečného AI.

Použité oficiální podklady:
[Codex hooks](https://learn.chatgpt.com/docs/hooks),
[konfigurace MCP a tool policy](https://learn.chatgpt.com/docs/config-file/config-reference).
Konkrétní protokol a trust route byly ověřeny na připnutém lokálním runtime.
