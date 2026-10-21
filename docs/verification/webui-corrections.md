# Ověření cílených oprav #18

Základ izolované větve: integration `1ced2b74efe549f9f70b4b02323941f09a3fabb2`.
Použitá hranice: veřejné operace `Application.dispatch`, události a artefakty GUI
a existující verze 1 nativního CLI. Testy používají skutečné nativní PDF/TXT,
segmentaci, kontrolní reporty, CAS a archivaci. Externí procesní protějšek je
výslovně řízený test; není důkazem skutečné AI kvality ani přijetí.

`tests/test_webui_corrections.py` ověřuje tyto veřejné scénáře:

- známý syntetický sken ABC/DEF, řízené chybné AXC, cílený původní modelový patch,
  nový PDF/TXT, původní očekávání a byte-identické původní reporty ve snapshotu;
- nové geometrické pozorování pouze dotčené položky, přesný původ zbývajících
  nezměněných položek, souřadnice zdrojového výřezu, diagnostické obrazy a spotřebu;
- stejný vzorkový neúspěch po změně PDF: stop po jednom pokusu, beze změny při
  znovuotevření a bez možnosti znovu vynulovat rozpočet;
- tři skutečně odlišné neúspěchy: přesně tři uložené cykly, tři nové iterace,
  odmítnutí dalšího startu druhou instancí a oddělené uživatelské přijetí;
- automatické navázání oprav na kompletní první export bez nového prvního čtení;
- neplatný celý patch, zastaralý start, prázdný původní návrh a nativně platný
  redakční zásah do testového registru chyb vydavatele: atomické odmítnutí a
  zachování původního skutečného validačního výsledku;
- neznámý cyklus vrací strukturovanou chybu CLI a nic nemění.

RED a GREEN logy a kontrolované artefakty jsou uchovány pod
`.scratch/ticket-18-proof/` v kořeni projektu. Samostatné původní protokoly a
pakety zůstávají beze změny; přesné kopie z dočasných testových cest mají mapu
původních cest a SHA manifest. Cesty uvnitř modelových paketů se nepřepisují.

Závěrečné výsledky po synchronizaci integration
`f9316c8e724cc7f5a85c4159c2206c26b7913023`:

- Původní zmrazený běh 89 testů skončil 88 PASS / 1 FAIL za 746,718 s.
  Všech 82 dosavadních regresních testů prošlo. Nový test tří cyklů odhalil
  chybějící archivaci zdrojového PNG z předchozí opravné iterace; zpracování
  bezpečně skončilo technickou chybou. Původní neúspěšný výsledek zůstává
  v `final-regressions.log`, původní zdroje v `before-final-fixes/` a přesné
  artefakty neúspěšného případu v `failed-89-cycle-case/`.
- Zpřísnění řízeného protějšku na skutečné schéma odpovědi #17 odhalilo další
  chybu převodu ID vzorku (`11-strict-schema-red.log`). Oprava používá cílové
  údaje z nativního reportu vzorků; nepřidává pole do původní modelové odpovědi.
- Čerstvý běh všech sedmi opravných scénářů na `cc39104e52292a4fea552b1435ecddea2e736705`
  prošel 7/7 za 322,419 s (`affected-final.log`, `affected-final-exit.json`).
  Obsahuje skutečné omezené schéma #17 a všechny tři archivované iterace.
  Celá původní sada 89 testů po opravě opakována nebyla; výsledky výše jsou
  odlišené a původní FAIL není přeznačen na úspěch.
- Závěrečná kontrola syntaxe `ui/export.js` a `ui/geometry.js` připnutým Node
  a `git diff --check` prošly (`js-syntax-final.log`).

`LATEST.json` v kanonickém adresáři důkazů ukazuje na přesnou konečnou kopii.
Její `SHA256SUMS.json` a `origin-map.json` umožňují ověřit obsah a původní
cesty také po odstranění izolovaného worktree.

Samostatný nativní GUI screenshot v #18 nevznikl. Veřejná historie, stránkování,
ochrana externího otevření a syntaxe JS se kontrolují v tomto ticketu; společná
vizuální kontrola finálního nativního GUI a pause/recovery/fronty následuje v #23.
Žádný skutečný AI tah #15–17 nebyl v tomto ověření opakován.
