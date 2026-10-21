# Ověření porovnání a místního importu

Testy používají dohodnuté veřejné hranice `Application.dispatch`, původní
nativní CLI a jejich trvalé události/artefakty. Původní workflow, F konstrukce,
fonty, kvalita ani očekávání zdrojů se nemění.

`tests/test_webui_comparison.py` má devět scénářů. Skutečné místní renderování
a Tesseract ověřují import pouze celých stránek, nezávislé inody, nezměněného
dárce, chybějící AI/context sentinel soubory v novém průchodu, audit původního
a přepsaného argv, opravu vadné jednotky, odmítnutí různých prostředků,
argumentů, symlinků, nedokončených checkpointů, různých DPI/zdrojů i pokusu
předefinovat neměnný profil přes nativní CLI. Veřejný nativní negativní test
také odmítá `../` cestu k manifestu i profilu mimo evidenci a ověřuje, že
externí soubory zůstaly nezměněné. Samostatná historie odlišuje
`computed`, `same_run_cache` a `imported_local`.

RED→GREEN zachyceno pro chybějící import, veřejné porovnání, vadný seznam
místo checkpointu, symlink v cíli a odlišné DPI cílového profilu. Celá sada
po základních změnách prošla8/8 za88.981s; po opravě confinement cesty prošla
celá rozšířená sada9/9 za135.626s. Obsahuje také dva úplné průchody přes
veřejné `start_autonomous` se skutečnými nativními PDF/TXT a kontrolami,
s externím řízeným procesovým peerem. Porovnání zachová nálezy, ceník, kroky,
historii a výsledek po restartu. Peer záměrně vrací stejné doslovné thread ID;
aplikace tuto shodu pravdivě označí. Tento test není skutečný AI důkaz.

Regresní metriky prošly13/13 za16.258s. Syntaxe změněných JavaScriptů byla
ověřena `node --check`. U řízené context SQLite fixture se vyskytují původní
ResourceWarning pro neuzavřené spojení; testy dokončily úspěšně.
Dosavadní nativní příprava prošla9/9 za40.848s, včetně opravy poškozených
jednotek, parametrů, modelů a zachování ruční práce.

## Skutečné B5: dva nové malé průchody

Oba skutečné průchody proběhly nad zmrazeným commitem
`3763ff3343b25302d8bffd894ab6f5e44aaec9e9`, s přesným GPT6.1 Sol high a
ověřeným context-mode. Běžný přezkum spuštění povolil každou novou akci
samostatně. Žádný dokončený tah15–17, A ani B se neopakoval.

- Zdroj: jedna stránka, zdrojový výřez620×210 pixelů ze schváleného fiktivního
  testu. SHA256 PDF
  `75bc8f6644e82ad9de6bc9ad9fafba3b985bc456cfd179054e581590f007d138`.
- A: `75bc8f6644e8-f82ac2ef08aa`, tři nově spočítané místní jednotky.
- B: `75bc8f6644e8-041a33375555`, tři převzaté místní jednotky a žádný nový
  rastr ani kandidátní průchod Tesseractu. Nativní závěrečná validace prošla.
- Profily mění jméno a prompt čtení; lokální parametry300DPI/ces jsou shodné.
  Pět pozorovaných AI vláken každého průchodu je mezi A/B disjunktních,
  včetně oddělených úložišť context-mode. Zdrojový požadavek neobsahuje vlastní
  očekávání ani dárcovy přepisy či posudky. Nezávislá očekávání byla zmrazena
  před oběma průchody a použita pouze v pozdější smlouvě geometrie.
- A i B mají dokončené nativní a původním tahem doložené kontroly,
  `errors=[]`, `ready_with_open_items`, `acceptance=not_recorded`. Každý
  zachovává tři otevřené nálezy: dva rozdíly mezer/řádkových konců úplné
  extrakce a aproximaci geometrie. Očekávání ani konstrukce F se neopravovaly
  jen kvůli výsledku kontroly.
- Všech173 běžných souborů A bylo shodných před, během i po B. Porovnání je
  přesně shodné po restartu aplikace. Celková AI spotřeba a cena jsou kvůli
  neúplnému pokrytí obnovených epoch označeny jako neúplné/neznámé, nikoli nula;
  původní měření jednotlivých kroků jsou zachována.
- Další skutečný místní průchod `75bc8f6644e8-283c6c3cac91` při150DPI odmítl
  import a skutečně spočítal rastr i oba kandidáty. Neodeslal žádný AI tah.

Kanonický důkaz je `.scratch/ticket-22-proof/`: `prepared-b5/` obsahuje
původní zadání/disclosure, `actual-A/` a `actual-B/` původní stavy, audity a
porovnání, `actual-DPI/` skutečný DPI miss. Přesných66 zmrazených souborů je
nezávisle zkopírováno a přehashováno do `exact-code-archive/` s mapou původních
absolutních cest. Původní modelové požadavky se nepřepisují kvůli pozdější
opravě validátoru cest nebo úklidu worktree.

Nativní uložené porovnání v `native-comparison-v5/` prošlo na vlastněném
Xvfb:119: skutečně mapované okno1880×1320, čitelné profily/prompty, společná
škála, původy místních jednotek, jedenáct kroků každého průchodu, nezměněný
aktivní výběr a žádný nový AI tah. Screenshot má normalizovaný průměr0.89476.
Předchozí chyby evidence zůstávají přiznané: příliš velký JSON odpovědi GUI,
černý screenshot nesprávné plochy, chybějící pomocný `xwininfo` a nesprávný
požadavek na legacy WM_NAME místo mapované geometrie. Tyto pokusy nejsou
označené jako úspěšné screenshoty.

Logy RED/GREEN a regresí jsou trvale v
`.scratch/ticket-22-proof/controlled-tests/`. Finální instalovaný balík23
vyžaduje vlastní finální ověření; toto je ověření současných zdrojů aplikace.
