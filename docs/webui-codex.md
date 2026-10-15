# Přihlášení a obrazová diagnostika Codex

V pojmenovaném průchodu s profilem `gpt-6.1-sol` a úsilím `high` otevřete
„Codex · obrazové ověření“. „Ověřit přihlášení“ čte stav účtu podporovaným
protokolem Codex. „Přihlásit účet ChatGPT“ v případě potřeby nabídne odkaz
vrácený `account/login/start`; dokončení sleduje `account/login/completed`.
Aplikace nečte ani nekopíruje přihlašovací tokeny a nevyžaduje API klíč.
Používá běžné spravované přihlášení Codex, jehož stav musí být pro Codex
zapisovatelný. Přihlašovací odkaz existuje pouze během aktivního pokusu;
do trvalého protokolu se uloží s odstraněnými citlivými údaji.

Zadejte připravený PNG/JPEG do 20 MiB a stiskněte „Přečíst diagnostický
obrázek“. Prázdné pole použije `raster/page-1.png` tohoto průchodu. Aplikace
zkopíruje obraz do samostatného adresáře pokusu a uloží SHA-256. Před
inferenčním tahem vyžaduje deklarovanou podporu obrazů i úsilí `high`,
potvrzení přesné konfigurace v `thread/start` a explicitně nastaví stejný
model i úsilí v `turn/start`. Katalog sám oprávnění účtu neprokazuje.

GUI ukazuje konečný stav, odpověď, požadovanou a potvrzenou konfiguraci,
identity pokusu/vlákna/tahu i dostupné původní usage údaje. Odlišná
konfigurace, přesměrování, použití nástroje, chybějící odpověď nebo
neúspěšný tah nemohou vytvořit `combination_verified: true`. Potvrzení
konfigurace vychází z dostupných údajů protokolu, nikoli z nezávislé
atestace backendu. Změněný uchovaný obraz zneplatní uložený doklad.

Dokončená obrazová diagnostika není přepis vydání, kontrola věrnosti,
přijetí zadavatelem ani připravenost autonomního OCR. Vždy zachovává
`autonomous_ocr_ready: false`; skutečné nástroje a hooky context-mode ověří
navazující přírůstek. Diagnostika nepřebírá kandidátní OCR a vyžaduje
čtení přiloženého obrazu bez nástrojů. Pro tento účel vypíná zděděné
pluginy, hooky a shell. Případné nástroje stále hlídá v událostech.

## Veřejné operace a proces

Operace používají stejný `Application.dispatch` jako nativní WebUI:

| Operace | Payload | Výsledek |
| --- | --- | --- |
| `check_codex_account` | `run_id` | Asynchronní ověření přihlášení bez inference |
| `start_codex_login` | `run_id` | Podporované přihlášení bez inference |
| `start_model_diagnostic` | `run_id`, volitelně `image_path` | Nový obrazový pokus |
| `model_diagnostic_status` | `run_id` | Poslední uložený pokus a jeho evidence |

Události `codex_progress` a `codex_finished` jsou dostupné běžným kurzorem
aplikace. Stavy jsou `not_started`, `starting`, `running`, `awaiting_login`,
`completed`, `failed`, `interrupted` a `invalidated`. Úspěšná kontrola účtu
nemá obrazový tah a nezískává `combination_verified`. Aplikace současně
nespouští přípravu a Codex; změna kořene evidence za běhu je odmítnuta.

`native/codex-runtime.json` připíná Codex `0.162.0-alpha.17.2` a jeho
společníka `codex-code-mode-host` přesnými SHA-256. Adaptér před spuštěním
ověří oba soubory. Použije přibalenou cestu `runtime/codex/codex`, při vývoji
určený instalovaný soubor `/usr/lib/chatgpt/resources/codex`. Přibalení a
přenositelnost celého distribučního balíku zůstávají samostatnou prací.
Codex běží jako vlastněná skupina procesů s JSON-RPC na stdio, mimo GUI
callback. OCR dále používá vlastní určený interpreter/proces; GUI Python
nemusí mít OCR knihovny. Manifest zachovává PID, skupinu, startovní čas
procesu v `/proc`, vlastníka i návratový kód pro pozdější obnovu.

## Trvalé doklady

Doklady jsou oddělené od místní přípravy:

```text
work/RUN/application/codex-attempts/ATTEMPT/
  attempt.json
  request.json
  protocol.jsonl
  stderr.log
  workspace/image.png nebo image.jpg
```

Manifest váže pokus ke kořeni evidence, průchodu, profilu, obrazu a
vláknu/tahu. `request.json` zachovává skutečné zadání aplikace i požadavek
na tah. `protocol.jsonl` zachovává pořadí příchozích i odchozích rámců,
čas a původní hodnoty/přítomnost usage polí; pouze autentizační údaje
odstraňuje. Žádný chybějící usage údaj se nedoplňuje nulou, nepočítají se
ceny ani se nesčítají `last` a `total`. Přesměrovaný nebo přerušený pokus
si své dostupné usage ponechá. Historie průchodu obsahuje stabilní
identity událostí. Obnova po pádu vlastníka je předmětem navazující práce;
uložený nedokončený pokus se automaticky neposílá znovu.

## Ověření

`tests/test_webui_codex.py` používá na schválené procesové hranici skutečné
řízené potomky. Ověřuje veřejné operace, přihlášení, původní usage,
perzistenci, nesprávný model/úsilí, chybějící obrazové schopnosti,
odmítnutí, přesměrování, nástroj, přerušení, poškozená data a ukončený
proces. Tyto řízené odpovědi nejsou důkazem skutečného přístupu k modelu.

`tools/smoke_webui_codex.py` ověří skutečné formuláře nativního WebUI.
Vyžaduje existující pojmenovaný průchod a malou nezávislou rastrovou
předlohu. Očekávání ve formátu `{"expected":"přesný text"}` držte mimo
adresář předávaný modelu; čte je pouze ověřovací proces. Model obdrží jen
obraz a pevné diagnostické zadání. Novou inferenci spustí pouze přepínač
`--run-diagnostic`; bez něj ověřuje obnovení již uloženého výsledku.

```sh
xvfb-run -a -s '-screen 0 1920x1400x24' /cesta/gui/python \
  tools/smoke_webui_codex.py --root /evidence --run-id RUN \
  --image /predloha/image.png --expectation /nezavisle/oracle.json \
  --ocr-python /cesta/ocr/python --browser Chromium \
  --browser-parameters=--ozone-platform=x11 \
  --evidence-directory /tmp/codex-proof --run-diagnostic
```

Pro screenshot je potřebný ImageMagick `import`. Při Wayland prostředí
vyžaduje snímání kořene Xvfb skutečné spuštění prohlížeče přes X11, jak
ukazuje přepínač výše. Ověření bez `--run-diagnostic` nesmí vytvořit nový
tah. Původní protokol zůstává v evidenci vybraného průchodu.
