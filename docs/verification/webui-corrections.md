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

Samostatný nativní GUI screenshot v #18 nevznikl. Veřejná historie, stránkování,
ochrana externího otevření a syntaxe JS se kontrolují v tomto ticketu; společná
vizuální kontrola finálního nativního GUI a pause/recovery/fronty následuje v #23.
Žádný skutečný AI tah #15–17 nebyl v tomto ověření opakován.
