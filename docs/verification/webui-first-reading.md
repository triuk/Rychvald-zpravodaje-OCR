# Ticket 15 — skutečné první vizuální čtení

Ověřeno 18. 10. 2026. Implementační větev `ticket/15-visual-reading` navazuje
na integrační `d3e9a4d`. Trvalé doklady v tomto pracovním prostoru jsou v
`/home/gordon/Dokumenty/Rychvald-zpravodaje-OCR/.scratch/ticket-15-proof/`;
nejde o data distribuovaná společně s aplikací.

## Veřejné rozhraní a ochrany

GUI používá `Application.dispatch(start_reading, reading_status)`. Start
vyžaduje platnou nativní přípravu včetně checkpointu a hashů, shodný zdroj,
DPI/jazyk profilu a dokončené obrazové i context-mode ověření stejného
profilu a připnutých prostředků. Přepnutí evidence nebo souběžný jiný krok
se během čtení odmítne.

První skutečný tah dostane všechny původní obrazy a jejich identitu, bez
OCR kandidátů. Potvrzené řádky a jejich stav pocházejí výhradně z původního
konečného JSON modelu. Druhý tah používá skutečné nativní dotazy, původní
obrazové odpovědi a úplnou validaci kandidátů, řádků, jednotek a registrů.
Průběžný návrh zůstává nezveřejněný. Před publikací se znovu čtou původní
protokoly a ověřují oba dokončené tahy, přesný model/úsilí, obrazy, použité
nástroje, příslušné důvěryhodné hooky a context-mode. Nativní proces pod
zámkem provede plnou validaci a compare-and-swap přepisu před atomickým
zápisem. Ruční editor přepisu v GUI není.

## Přesné prostředí

Skutečné tahy použily Codex `0.162.0-alpha.17.2`, `gpt-6.1-sol`, `high` a
spravované přihlášení účtem ChatGPT. Codex i jeho host byly obnoveny z
konkrétního dřívějšího balíku a odpovídají původním hashům v
`native/codex-runtime.json`; změněná instalace desktopu se nepoužila.

Historická agregovaná sada context-mode po restartu nebyla dostupná. Nová
výslovně připnutá sada `1.0.169` má zdrojový hash
`6207b687a1606af3fe46f63ce3e6a3ee0ae9315c1612a37b20633688026bf14b`
a připravený hash
`e6304ac4d20283362feda2d5287b8e008af48c9b7e3fb949414aa1f89fdd2c17`.
Skutečná offline rekonstrukce všech 4578 souborů z upstream Git objektů a
integritou ověřených npm archivů prošla, stejně jako následná příprava.
Per-file původ je v `native/context-source-inventory.json`; původní Codex
hooky a adaptér bez instalací zůstaly beze změny. Důvod rozdílu historické
agregované sady není znám, nový pin se za historické bajty nevydává.

Místní OCR použilo stabilně obnovený Python 3.14.7 a explicitní manifest
`native-recovered-runtime/environment.json` ve sdílených pracovních
dokladech. Tento místní manifest má dvě výslovně přezkoumané náhrady
nedostupných dřívějších sestavení jbig/zstd stejnými upstream verzemi z
oficiálních archivů Arch; původní manifest repozitáře se neměnil. Identitu
skutečného manifestu zachovávají přípravné checkpointy a
`final-saved-proof-integrity-before-reload.json`. Samostatná izolovaná
zkouška tohoto obnoveného OCR prostředí prošla všemi A1–A11. Tím se ještě
netvrdí dokončení distribučního GUI balíku podle ticketu 23.

## Nový syntetický sken

Doklady: `native-cases-20261018-1/`. Před AI byl zveřejněn
`source-disclosure.json`, SHA-256
`41a261c4af6f9648a396b8edc626ff65592f2c48542c5e32b7603b4d7d55fbe9`.
Zdroj obsahuje dvě nově vykreslené rastrové stránky 1400×1000 a 1400×900,
náhodné údaje a čitelnou tiskovou chybu. Použitý průchod je
`22d0903ed909-1283960bdfa0`.

Nezávislé hodnoty a původní výběrové obdélníky byly drženy pouze ve vlastním
hostitelském procesu. Před AI se zaznamenal jejich závazek
`a3f45daf93634eba13816e5ce54187af1f3e4ae2145e8c680ca7f604786e2886`.
Teprve po ověřené atomické publikaci poslal GUI harness výslovný kontrolní
signál. Původní proces ověřil nezměněný závazek, porovnal výsledek a odhalil
`independent-source-samples.json` a `independent-oracle-result.json`.
Žádný očekávaný přepis nebyl předán modelu ani vložen programem.

- Obrazový preflight `a6156b3df60346ae9851d2e6aded19c9`: dokončen.
- Context preflight `6bbc1bbef442440281ccd857d1b02da0`: skutečné směrování,
  dohledání, kompaktace, restart a obnova dokončeny.
- Čtení `729cc4940c4949b58ae26a7b6571f54b`: původní zdrojový tah
  `01a14f82-3a6c-7371-8def-a51a4672dceb` a vypořádání
  `01a14f83-a956-7932-918b-04c3108e7dc2` jsou dokončené.
- 13 řádků a 13 logických jednotek. Úplný text odpovídá původním hodnotám
  po NFC a normalizaci whitespace. Tisková chyba „chibu“ zůstala ve znění
  a má vlastní vysvětlení v evidenci chyb vydavatele.
- `logical-order-source-check.json` porovnává také pořadí logických
  jednotek proti stejnému původnímu závazku; pokračování přes stránku má
  stejné article ID. Nejde o byte-for-byte ani geometrické ověření.

První skutečná obrazová žádost skončila `usageLimitExceeded`.
Podporované `thread/read` nezávisle potvrdilo její terminální selhání.
Další pokus přerušila chyba čekání GUI harnessu ještě před `turn/start`;
originální protokol obsahuje nula odeslaných tahů. Oba záznamy zůstaly
zachované. Nová žádost byla výslovná až po tomto ověření a po dostupném
stavu účtu. Žádný přijatý aktivní tah se nepodal duplicitně.

## Nový obtížný výřez

Průchod `06c775631212-6875223ed720` zpracoval nově odvozenou malou oblast
strany 2 původního `zpravodaj-2000-05-c03.pdf`, 300 DPI, původní bbox
`[1070,290,2600,540]`. Je to pouze tento výřez, nikoli celá původní stránka.
Má skutečně rozmazaný pravý okraj a řádek dole přerušený hranicí výřezu;
tato omezení se nezamlčují. Původní hash a přesný obraz jsou ve disclosure.

Skutečný obrazový preflight `4eb00f8ded7b45cfae7e671cc597b1d0` i context
preflight `aa52978aef2e40998b42796af35a56ce` byly dokončeny. Čtení
`85014f6a3db044adab5100993beaf198` má původní dokončené tahy
`01a14f8b-e167-7232-962b-174a182eb3cf` a
`01a14f8c-f7d6-75a2-9841-1f808da08c68`.

Výsledkem jsou čtyři řádky ve třech logických jednotkách. Neurčitelné slovo
na pravém okraji zůstává `[NEČITELNÉ]`, s původním bbox/cropem, kontextem,
odůvodněním, kandidátní hypotézou a stavem `waiting_for_input`. Hypotéza se
nevydává za potvrzené čtení. U dolního řádku zůstala výslovná poznámka o
oříznutí a zdrojový rizikový záznam. Nic z toho nevložil opravný skript.
První prozatímní validace byla v obou případech odmítnuta a opravený návrh
modelu pak prošel; neúspěšné návrhy se zachovaly. Dokončený přepis nevznikl
pouhým návratem tahu.

## Kontroly a meze

`actual-two-run-context-isolation.json` ověřuje na skutečných SQLite
databázích dvou nových dokončených průchodů vlastní záznamy a události,
nulový cizí záznam/vlákno a rozdílné workspace i úložiště. Počty tokenů
čtení jsou v původních protokolech a stávajícím metrickém přehledu;
neznámé údaje zůstávají neznámé, včetně neúspěšných předchozích pokusů.

46 veřejných WebUI regresí prošlo na stabilním obnoveném prostředí
(48,634 s). Následně nový negativní test nativního checkpointu nejprve
selhal, po doplnění brány prošlo všech osm testů čtení. Nativních 12 testů
review transakcí prošlo. JavaScript syntaxe a `git diff --check` prošly.
Řízené protokolové peers v automatických testech nejsou dokladem skutečného
modelu; skutečné modelové důkazy výše mají vlastní původní protokoly.

Skutečné nativní GUI zachycuje `read-difficult/native-gui.png` a
`readonly-synthetic-reload-fixed/native-gui.png`, vizuálně prohlédnuté.
Obnovení uloženého výsledku nevyžadovalo novou inferenci. Zveřejnění prvního
přepisu je dokončené; geometrie, PDF/TXT, závěrečné kontroly a přijetí
zadavatelem jsou samostatné následující fáze.
