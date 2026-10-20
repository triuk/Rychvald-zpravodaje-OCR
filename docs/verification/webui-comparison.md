# Ověření porovnání a místního importu

Testy používají dohodnuté veřejné hranice `Application.dispatch`, původní
nativní CLI a jejich trvalé události/artefakty. Původní workflow, F konstrukce,
fonty, kvalita ani očekávání zdrojů se nemění.

`tests/test_webui_comparison.py` má osm scénářů. Skutečné místní renderování
a Tesseract ověřují import pouze celých stránek, nezávislé inody, nezměněného
dárce, chybějící AI/context sentinel soubory v novém průchodu, audit původního
a přepsaného argv, opravu vadné jednotky, odmítnutí různých prostředků,
argumentů, symlinků, nedokončených checkpointů, různých DPI/zdrojů i pokusu
předefinovat neměnný profil přes nativní CLI. Samostatná historie odlišuje
`computed`, `same_run_cache` a `imported_local`.

RED→GREEN zachyceno pro chybějící import, veřejné porovnání, vadný seznam
místo checkpointu, symlink v cíli a odlišné DPI cílového profilu. Celá sada
po těchto změnách prošla8/8 za88.981s. Obsahuje také dva úplné průchody přes
veřejné `start_autonomous` se skutečnými nativními PDF/TXT a kontrolami,
s externím řízeným procesovým peerem. Porovnání zachová nálezy, ceník, kroky,
historii a výsledek po restartu. Peer záměrně vrací stejné doslovné thread ID;
aplikace tuto shodu pravdivě označí. Tento test není skutečný AI důkaz.

Regresní metriky prošly13/13 za16.258s. Syntaxe změněných JavaScriptů byla
ověřena `node --check`. U řízené context SQLite fixture se vyskytují původní
ResourceWarning pro neuzavřené spojení; testy dokončily úspěšně.
Dosavadní nativní příprava prošla9/9 za40.848s, včetně opravy poškozených
jednotek, parametrů, modelů a zachování ruční práce.

Logy RED/GREEN jsou v `.scratch/worktrees/ticket-22/.scratch/proof/`.
Příprava konkrétního skutečného B5 se dvěma novými profily je odděleně
v `.scratch/ticket-22-proof/prepared-b5/`. Před spuštěním je nutný přesný
zmrazený commit/disclosure, běžný přezkum skutečného spuštění a koordinace
sdílené plochy. Žádný výsledek15–17 se nepřeposílá jako nový průchod.
Finální instalovaný balík23 vyžaduje vlastní finální ověření.
