# Auditovatelné metriky průchodů

Panel „Časy, tokeny a srovnávací cena“ čte původní procesové artefakty;
nevolá model. Veřejné operace `Application.dispatch('run_metrics', {run_id})`
a `step_detail` používá GUI i integrační ověření. Samostatné OCR CLI a jeho
verzovaný JSON protokol se nemění. Staré nepojmenované průchody zůstávají
v původním čtecím pohledu.

## Co je měření

- Každý místní krok/jednotka má stabilní `local:ATTEMPT:STEP` a původní
  `event_id`. AI operace má `ai:ATTEMPT`, původní vlákno a seznam skutečně
  odeslaných tahů. Podklady jsou v `codex-attempts` nebo `context-attempts`.
- Časy místních jednotek pocházejí z jejich nativních start/terminal událostí.
  Čas obsazeného AI workeru pochází z hranic pokusu, samostatně je uvedena
  příprava/spuštění a pozorovaný běh od odeslání tahu do ukončení pokusu.
  Tyto časy nejsou měřením výpočtu poskytovatele.
- Čekání pochází pouze z explicitních `waiting_intervals` pokusu (dvojice
  ISO začátek/konec; například producent fronty nebo schvalování). Pokud
  takový podklad není dostupný, `waiting_seconds` je `null`, nikoli nula.
  Preflight s kontrolou prostředí, účtu a modelu se nevydává za čekání.
- Současné/vnořené intervaly se sjednocují. Místní parent kroky a jednotky
  ani nástroje uvnitř AI tahu se nepřičítají podruhé; překryv čekání s jinou
  doloženou prací se do čekání celého průchodu nezapočítá.
  Rozpětí prvního až posledního doloženého kroku se uvádí samostatně;
  nezařazené mezery nejsou automaticky čekáním ani potvrzením dokončení OCR.

## Tokeny a neúplné údaje

Účetní politika `fresh-thread-cumulative-observations-v1` používá pouze
původní `thread/tokenUsage/updated.tokenUsage.total`. Nikdy nesčítá `last`.
Necacheovaný vstup je `inputTokens - cachedInputTokens`; výstup již zahrnuje
`reasoningOutputTokens`. Tři barvy kategorií jsou stálé napříč průchody.
Místní OCR, místní cache ani délka textové odpovědi nejsou usage AI.

Platný výchozí stav musí doložit skutečný `thread/start` požadavek a odpověď
v příslušné procesové epoše, následovaný mapováním skutečného `turn/start`.
`connection_id` odděluje procesy; starý protokol #13 bez tohoto pole má
jednu explicitně označenou legacy connection a její `initialize` epochy.
Metadata-only bootstrap nevytváří spotřebu. Každá usage událost uchovává
původní pole, jejich přítomnost, thread/turn/connection, pořadí, časy,
offset/řádek a SHA-256. Neváže se na právě aktivní tah.

Duplicitní kumulativní snímek přispěje jednou; zcela shodná původní usage
stejného thread/turn v opakovaném pokusu se označí `duplicate_of`. Rozdílné
překryvné vlastnictví zůstává neúplné. Starší doručený snímek lze rozpoznat
jen podle jeho původního `emittedAtMs`; jinak pokles čítačů není pokládán
za ověřený reset. Obnova bez doloženého základu, kompaktace, neznámý tah,
neplatné čítače a neúplný JSONL konec ponechávají součet neúplný. Původní
řádky se neopravují ani nemažou. Přerušený pokus si uchová známou spotřebu,
ale její úplnost se netvrdí. Pole přítomné s `null` není naměřená nula.

`observed` znamená pozorování podle uvedené politiky, nikoli univerzální
garanci fakturačních nebo resetovacích pravidel app-serveru. Známý dokončený
krok může mít číselné údaje, zatímco celý průchod má `partial` a `null`,
například kvůli předchozímu přerušenému pokusu bez usage.

## Srovnávací cenový scénář

Při prvním čtení se s průchodem uloží konkrétní `price-card.json` se zdroji,
datem, verzí, sazbami, předpoklady a SHA-256. Další čtení používá tuto uloženou
kartu. Nejde o účtování předplatného ChatGPT ani o odhad počtu zbývajících
subscription tokenů. Chybějící sazba přesného modelu se nenahrazuje jiným
modelem; chybějící cache-write údaj cenu znemožní.

Karta `gpt-6.1-sol-standard-short-2026-10-16` zachycuje Standard API scénář
do 272 000 vstupních tokenů na každý požadavek bez regionální přirážky.
USD / milion tokenů: běžný vstup 2, cache read 0,10, cache write 2,50,
výstup 10. Dlouhé požadavky mají jiné sazby (4 / 0,20 / 5 / 15); hranice
se týká celého jednotlivého požadavku. Kumulativní thread součet nedokládá
mix délek jednotlivých požadavků ani tier; `high` tier neurčuje.
Zdroje ověřené 16. 10. 2026: [přesný model](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
a [pravidla prompt cache](https://developers.openai.com/api/docs/guides/prompt-caching).

Pro uvedený referenční scénář platí
`((I-C-W)*2 + C*0.10 + W*2.50 + O*10) / 1_000_000`.
Zápisy cache patří do zobrazeného necacheovaného vstupu, pro cenu však
nahrazují běžnou vstupní sazbu. Reasoning se znovu nepřičítá.
GUI ukazuje cenu kroku, průchodu a přepočet podle nativního počtu stran;
bez dostupného počtu je přepočet neznámý. Společná intenzita má pevné
prahy 0 / 0,001 / 0,01 / 0,1 / 1 / 10 USD a šedou pro neznámou cenu.

## Trvalé podklady a velikost odpovědí

### Místní práce ve všech automatických fázích

Každá automatická záložka má vlastní přehled místní práce a rozbalitelnou
historii. Zobrazuje běžící práci, stav, začátek/konec, dostupnou verzi nástroje,
skutečné argumenty a původ vstupů/výstupů. Starší kroky jsou stránkované;
výběr záložky ani načtení historie nespouští OCR. Místní cache a převzaté
místní podklady se rozlišují od nového výpočtu i od cache tokenů AI.

Nativní příkazy ukládají vlastní přijetí práce do
`application/local-attempts/ATTEMPT.json` a průběžný deník `.jsonl` ve workspace.
Záznamy se připojují pod zámkem a synchronizují na disk. Pokrývají přípravu,
práci s přepisem, místní přípravu geometrie, segmentaci, sestavení PDF,
ověření PDF/textu i místní části opravných cyklů. Vnořené procesy připojují
své skutečné příkazy do stejného deníku. Rutinní čtecí dotazy (`status`,
`list`, `query` a ověření při zobrazení uloženého stavu) nepřidávají další
výpočetní pokusy. Krátké dotazy na verzi nejsou vykazovány jako samostatná
výpočetní práce; dostupná verze je u nástroje.

Krok má identitu `native:ATTEMPT:STEP`, plný hash zdrojového vydání,
průchod, fázi a případnou vazbu na rodičovský krok/pokus. `scope` rozlišuje
nativní operaci, dílčí workflow příkaz, jednotku a podřízený nástroj.
Čas rodiče zahrnuje jeho potomky a souhrn používá sjednocení časových
intervalů. Nelze sčítat dobu rodiče a jeho vnořených nástrojů. Čekání bez
samostatného dokladu zůstává neznámé. CPU a RAM mají samostatné měření
popsané níže; nejsou dopočítány z délky běhu.

Deník zůstává čitelný po restartu, chybě i ukončení procesu. Pokud vlastník
se stejnou kernelovou identitou již neběží a chybí koncová událost, čtecí
pohled označí krok jako přerušený s neznámým koncem; nezapisuje vymyšlené
dokončení. Již publikované koncové události zůstávají zachované. Chyby
čitelnosti místních dokladů jsou v `local_warnings` a neznehodnocují samy
o sobě původní tokenové doklady AI. Starší přípravné události jsou nadále
čitelné přes původní identitu `local:ATTEMPT:STEP`, bez falešného doplnění
nezaznamenané verze nebo příkazu.

`run_metrics` navíc přijímá volitelné `kind` (`local`/`ai`), `phase`
(`preparation`/`reading`/`geometry`/`assembly`) a boolean `newest_first`.
Stránkování se potom vztahuje k vybraným krokům; celkové metriky průchodu
zůstávají celkové. Bez filtrů se chování dosavadního přehledu nemění.

### CPU a vzorkovaná RAM místních kroků

`resources` u místního kroku obsahuje jednotky, rozsah, dostupnost měření,
počet vzorků a způsob ukončení. GUI ukazuje CPU v sekundách a vzorkovanou
špičku RSS v MiB vedle názvu nástroje a doby běhu. Procesový čas CPU není
čas běhu ani čekání; tato čísla mohou být různá. Nejde o prostředky vzdáleného
poskytovatele AI. Starší nezměřené kroky mají neznámé hodnoty, nikoli nuly.

- Externí nástroj/workflow má vlastní PID. CPU se čte pomocí `wait4` právě
  pro tento PID, včetně potomků, které jeho procesový řetězec skutečně
  vyčkal. Nepoužívá se rozdíl globálního `RUSAGE_CHILDREN` mezi souběžnými
  vlákny. Nevyčkaní nebo přeživší pozorovaní potomci označí pokrytí jako
  neúplné. Linuxové hranice popisují [wait4](https://www.man7.org/linux/man-pages/man2/wait4.2.html)
  a [getrusage](https://www.man7.org/linux/man-pages/man2/getrusage.2.html).
- Rodičovská nativní operace měří svůj proces včetně všech jeho vláken
  a vyčkaných potomků z jeho vlastních `/proc/PID/stat` čítačů. Pozorované
  vlastní CPU potomků se nepřičítá znovu k CPU již započtenému do rodiče;
  alternativní pozorování tvoří pouze dolní mez. Vnořená CPU měření se
  nesčítají a nevytváří se z nich vymyšlený celkový součet.
- U jednotek uvnitř jednoho procesu se měří CPU volajícího vlákna. Jejich
  vlastní RAM se nedá spolehlivě oddělit od sdíleného procesu, proto je
  výslovně nepřiřaditelná. Rodičovská operace poskytuje společné RSS.
- RAM se vzorkuje po 50 ms: v jednom skenu se sečtou aktuální RSS kořene
  a pozorovaných potomků a uchová se maximum těchto součtů. Nejde o součet
  jejich individuálních maxim. Sdílené stránky se mohou v RSS různých
  procesů započítat vícekrát, tedy nejde o unikátní fyzickou paměť. Špička
  mezi vzorky může uniknout; `ram_status: sampled_lower_bound` to uvádí.
  Velmi krátký proces může mít CPU doložené, ale RAM nepozorovanou.

Měření zahrnuje režii vlastního pozorování. Vzorky zůstávají v paměti;
do trvalého deníku se ukládá počáteční stav, nejvýše přibližně jednou za
sekundu průběžný stav a při řádném konci poslední měření. Neúspěšný nástroj
si uchová naměřené prostředky. Při násilném ukončení přežije poslední
uložený vzorek označený `partial`/`interrupted`, bez smyšleného konečného
CPU nebo RSS. `scope` i `cpu_status` odlišují úplně odečtené konkrétní
procesy od neúplných průběžných pozorování. Samotné selhání OCR a úplnost
měření jsou odlišné skutečnosti.

Odvozený `application/metrics/ledger.json` obsahuje původní vazby,
naměřené vstupy a hashe zdrojů, účetní politiku, kartu i předpoklady.
Originální request, attempt a protocol soubory zůstávají nedotčené.
`run_metrics` vrací přehled; `offset` a `limit` (1–200, výchozí 100)
stránkují kroky přes `step_next_offset`. Přehled obsahuje maximálně posledních
pět odkazů na usage události kroku a jejich celkový počet.
`step_detail({run_id,step_id,offset,limit})` stránkuje původní usage události
a místní historii pomocí `usage_next_offset` / `event_next_offset`.
Příliš dlouhé zadání/odpověď mají v detailu limit 32 768 znaků, příznak
zkrácení a celkový počet; celý originál je v dohledatelném artefaktu.

## Ověření

`tests/test_webui_metrics.py` testuje veřejné operace proti skutečnému
kontrolovanému subprocess peeru a procesu produkujícímu recovery artefakty.
Pokryje duplicity, více tahů, kumulativní/opožděné snímky, procesové epochy,
obnovu, kompaktaci, přerušení, chybějící pole, vnořené časové intervaly,
stránkování, restart a cenu za stránku po skutečné nativní přípravě rastrů.
Kontrolované procesy nejsou vydávány za nativní modelovou evidenci.

Tři scénáře `local_history` v `tests/test_ocr_project_export.py` používají
skutečnou místní přípravu, segmentaci, export, qpdf/extrakci a validaci
malého syntetického skenu přes nativní CLI a veřejné dotazy aplikace.
Ověřují dostupné příkazy/vstupy/výstupy, výsledek validace, stránkování
fáze, cache bez opakování OCR, rozpracovanou práci ukončenou signálem a
stálé identity po restartu. Nativní `smoke_webui_projects.py --preparation`
ověřuje také zobrazení místní historie a cache v reálném WebUI/Chromiu.

Scénář `local_resources_include_descendants_failure_interruption_and_restart`
navíc vybírá explicitní hashovaný nástrojový fixture, který při skutečném
PDF exportu spouští potomka a vnuka. Ověřuje zahrnutí obou, CPU bez závislosti
na rychlosti stroje, neúspěšný proces, uložený vzorek po SIGKILL a restart.
Dvě postupné 128MiB alokace u různých potomků oddělené jejich uvolněním
ověřují, že se individuální maxima nevydávají za současnou špičku. Fixture
není distribuovaný qpdf; běžné exportní scénáře dál používají skutečné
místní nástroje. Nativní GUI smoke ověřuje zobrazení CPU/RSS i označení
nepřiřaditelné RAM jednotek.

Místní ověření #34 používá výslovně vybraný, hashi ověřený profil
`OCR_ENVIRONMENT=/tmp/rychvald-native-recovery/environment.json`
(Python 3.14.8, Tesseract 5.5.4, Poppler 26.10.0, qpdf 12.4.2 a připnuté
Python knihovny). Není vydáváno za původní distribuovaný runtime ani
za ověření skutečné dostupnosti modelu/context-mode.

`tools/smoke_webui_metrics.py` otevře skutečné WebUI/Chromium, vybere již
uložený pokus, zkontroluje zobrazené tokeny/cenu a otevře audit detailu.
Nevysílá nový tah. Ve vlastním displeji lze použít
`xvfb-run -a -s '-screen 0 1920x1400x24' ...`; Chromium má v harnessu
`--ozone-platform=x11`. Screenshot skutečného displeje pořizuje `ffmpeg`
(`x11grab`); černý výstup se odmítá. Původní modelové soubory mají před/po
shodné hashe.

Uložený skutečný diagnostický tah #13 poskytuje 14 596 necacheovaných
vstupních tokenů, 0 cache read, 82 výstupních tokenů (včetně 53 reasoning).
Referenční scénář dává 0,030012 USD pro tento krok. Starší přerušený pokus
bez usage záměrně ponechá cenu a spotřebu celého průchodu neznámou.
