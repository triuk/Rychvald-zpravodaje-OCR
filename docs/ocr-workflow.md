# OCR ze zdrojového PDF: obecný postup

Použij zdrojové PDF a novou pracovní složku. Přepis, pořadí článků, souřadnice, opravy, nejasná čtení a očekávání kontrol odvozuj z obrazu právě zpracovávaného dokumentu. Obsahově neutrální nástroje jsou `tools/ocr_workflow.py` a `tools/ocr_f_layer.py`.

Postup zahrnuje místní rozpoznání, úplné vizuální čtení, opravy textu, kontrolu geometrie, export PDF/TXT a samostatné ověření kopírování. Automatické OCR kandidáty nejsou potvrzeným přepisem. Optimalizace šetří opakované výpočty a ruční evidenci; rozsah čtení a požadavky na kvalitu zůstávají zachované.

## 1. Prostředí a vlastní cesty

Zvol vstup, novou pracovní složku a vlastní výstupní cesty. Názvy PDF/TXT odvoď od vstupu příponou `-ocr`. Zdrojové PDF zachovej beze změny. `prepare` odmítne pracovní složku s existujícím vstupním manifestem; další export téhož běhu automaticky archivuje předchozí iteraci. Cizí existující výstup se odmítne. Není zde předepsaný počet stran ani seznam titulů/oblastí.

Příklady zadej v kořeni repozitáře a nahraď vstup, jazyk a identifikátor běhu:

```bash
cd /home/gordon/Dokumenty/Rychvald-zpravodaje-OCR
source_pdf='/absolutni/cesta/ke/zdrojovemu.pdf'
ocr_work='experiments/novy-nezavisly-pruchod'
ocr_language='ces'
ocr_stem="$(basename -- "$source_pdf" .pdf)"
ocr_pdf="$ocr_work/output/pdf/${ocr_stem}-ocr.pdf"
ocr_txt="$ocr_work/output/text/${ocr_stem}-ocr.txt"
```

Jednorázově zřiď vlastní prostředí s Pythonem 3.14. [requirements.txt](../requirements.txt) připíná přímé i tranzitivní runtime závislosti nástrojů:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
source .venv/bin/activate
python tools/ocr_workflow.py doctor --work "$ocr_work" --language "$ocr_language"
```

Při dalších bězích stačí aktivace a `doctor`. Příkaz ověří importy, Tesseract a požadované modely, qpdf, Poppler a oba fonty; chybějící závislost vrátí kód 1 před OCR. Verze a hashe fontů uloží do `checks/environment.json`. Python prostředí je samostatné; systémové programy a fonty nejsou requirements souborem uzamčené. Při jiném umístění fontů předej stejné cesty do `doctor --font/--sheet-font`, `segment --font` a `sheets --font`.

Hned zjisti dostupnost skutečné cílové čtečky a jejího výběru/schránky. Pokud UI není dostupné, připrav ruční případy pro člověka podle [smlouvy kontrol](ocr-data-contracts.md#schránka); jejich stav zůstane `not_tested`. OCR může pokračovat, ale souhrn nebude tvrdit ověřenou kompatibilitu. Rozsah čteček a obtížné výběry řeší [pdf-copy-compatibility.md](pdf-copy-compatibility.md).

**Hotovo:** `doctor` prošel a je známý způsob provedení nebo předání zkoušek schránky.

## 2. Identita, rastr a první rozpoznání

```bash
python3 tools/ocr_workflow.py prepare \
  --source "$source_pdf" --work "$ocr_work" --dpi 300 --language "$ocr_language"
```

Pro český dokument nastav `ces`; pro jiný jazyk zvol skutečně dostupný model předlohy. Počet stran se načte z PDF. `input-manifest.json` obsahuje SHA-256 vstupu, vlastní rect/MediaBox/CropBox/rotaci každé strany, rozměry a hashe rastrů, DPI a verze. Zkontroluj `existing_text_characters`. Existující textová vrstva je samostatná situace, jejíž odstranění nástroj neimplementuje; export ji ve výchozím stavu odmítne. `--allow-existing-text` ji ponechá a může způsobit duplicitní extrakci, proto samo tuto situaci neřeší. PDF vyžadující heslo nástroj rozpozná, ale odemykání není implementováno.

Renderuj 300 DPI bez narovnání, změny kontrastu zdroje nebo společné šablony rozměrů. Vznikají `raster/page-N.png` a přehledy do 1250 × 1800 px. Na každé straně se provedou dva kandidátní průchody:

```bash
tesseract PAGE.png PREFIX -l LANGUAGE --psm 3 -c hocr_char_boxes=1 hocr tsv txt makebox
tesseract PAGE.png PREFIX -l LANGUAGE --psm 11 -c hocr_char_boxes=1 hocr tsv txt makebox
```

CLI dosadí `PAGE`, `PREFIX` a jazyk z parametrů a uloží skutečné příkazy do `ocr-commands.json`; pracují nejvýše dvě souběžné úlohy. PSM 3 tvoří základ inventáře, PSM 11 další kandidáty. Výsledek této fáze není potvrzený přepis.

**Hotovo:** manifest odpovídá vstupu, všechny stránky mají rastr a oba kandidátní průchody. Tyto podklady se při opravách přepisu znovu nevytvářejí.

## 3. Nové oblasti a místní OCR

Prohlédni všechny přehledy a původní rastry. Rozděl stránku podle skutečných článků, sloupců, hlaviček, inzerce, tabulek a dalších textů. Založ nový `regions.json`; obdélníky jsou `[x0,y0,x1,y1]` v pixelech vlastního rastru, od levého horního rohu, stránky číslované od 1. ID volíš nově. Příklad **schématu**, nikoli souřadnice k přenosu:

```json
[
  {"id":"nova-oblast", "page":1, "bbox":[40,100,1300,900], "psm":6}
]
```

Použij PSM 6 pro bloky textu, 7 pro jednotlivé řádky a 11 pro rozptýlené texty podle skutečné oblasti. Počet ani volba režimu pro konkrétní oblast nejsou pevně dané pro další PDF.

```bash
python3 tools/ocr_workflow.py regions --work "$ocr_work" --regions "$ocr_work/regions.json"
python3 tools/ocr_workflow.py draft --work "$ocr_work" --review "$ocr_work/review.json"
```

Místní příkaz má přesný tvar:

```bash
tesseract CROP.png PREFIX -l LANGUAGE --psm PSM -c hocr_char_boxes=1 hocr tsv txt
```

`local-candidates.json` uchovává kandidátní text, řádky, slova, znakové hOCR boxy i příkazy. Boxy výřezu se převádějí do souřadnic stránky přičtením počátku výřezu. `draft` pouze vytvoří návrh `review.json` s `text_status: candidate` a jednou jednotkou na tiskový řádek. Odstavce, nadpisy, pořadí a potvrzení čtení musí následovat podle obrazu.

`regions` a `targeted` znovu použijí OCR pouze při shodě hashe výřezu, příkazu, verze Tesseractu a hashů všech kandidátních výstupů. Poškozený nebo změněný podklad se rozpozná znovu. `targeted` zachovává i výsledky předchozích cílů; další průchod zadávej jen pro obtížná nebo změněná místa. `draft` vytvoř jednou, pak upravuj potvrzený přepis.

**Hotovo:** inventář oblastí pokrývá všechny texty stránky; každý kandidát bude v přepisu ponechán nebo vyřazen s důvodem.

## 4. Úplné vizuální čtení a obtížná místa

Projdi všechny textové bloky proti původnímu rastru, včetně drobného textu, poškozených okrajů a tabulek. Uprav `review.json`: potvrď znění, doplň opomenuté řádky a vyřaď šum s důvodem. Jména, čísla a data kontroluj jako jednotlivé údaje. Confidence ani shoda kandidátů nejsou samostatným důkazem správnosti. Čitelnou chybu vydavatele zachovej v textu a popiš odděleně.

K nejednoznačnému údaji vytvoř původní výřez a vlastní lokální průchod. `targets.json` má položky `id`, `page`, `bbox`, `psm`:

```bash
python3 tools/ocr_workflow.py targeted --work "$ocr_work" --targets "$ocr_work/targets.json"
```

Tento krok je potřeba u skutečně obtížných údajů, ne povinně u každého slova. Vyrobí původní šedotónový výřez a **podpůrný** normalizovaný výřez. Výpočet: `background = GaussianBlur(12)`; `normalized = uint8(clip(gray / maximum(background,1) * 235, 0,255))`. Obě varianty dostanou vlastní `tesseract ... -l LANGUAGE --psm PSM txt tsv`. Normalizovaná varianta není původním obrazovým dokladem a nevstupuje do viditelného PDF.

Pokud přesné znění nelze určit, zachovej bezpečně čitelné okolí, nahraď pouze nejistou část doslovným `[NEČITELNÉ]` a vytvoř vlastní ID, kontext, původní oblast/výřez, důvod, nové kandidáty a stav čekající na doplnění. Zbytek vydání zpracuj. Kandidáty jsou hypotézy. U zástupného textu se eviduje region; jeho písmena se nevydávají za jednotlivé tištěné znaky.

Zapiš vizuální rozsah kontroly v novém pracovním prostoru: které stránky, bloky a údaje byly skutečně přečteny, co je potvrzené a co otevřené. CLI takovou kontrolu samo neprohlašuje za provedenou. Nejde o systematické ověřování čitelných věcných tvrzení dokumentu proti externím zdrojům.

**Hotovo:** všechny textové bloky byly přečteny, rizikové údaje zkontrolovány a každý výskyt `[NEČITELNÉ]` má vlastní záznam. Nejistota neblokuje zpracování zbytku vydání.

## 5. Logické jednotky a smlouva `review.json`

Dokonči článek před přechodem k dalšímu. Jednotkou je nadpis nebo skutečný odstavec, případně tabulkový záznam, nikoli každý tiskový řádek. Pokračování přes sloupec na jedné straně patří do téže jednotky. Články mají své `article` ID. PDF objekty jsou stránkové; pokračování odstavce přes stránku vyžaduje vlastní ověření. U takového dokumentu zapiš návaznost a zvlášť ověř spojení v TXT a ve čtečkách; automatické sloučení přes stránky CLI zatím nepřidává.

Před úpravami čti [smlouvu přepisu a geometrie](ocr-data-contracts.md#přepis). Pracuj se strukturovanými soubory přímo na disku; do kontextu vracej potřebné řádky a stručnou validaci. JSON získávej ze souboru, nikoli parsováním zobrazovací obálky nástroje.

```bash
python tools/ocr_workflow.py validate-review --work "$ocr_work" --review "$ocr_work/review.json"
python tools/ocr_workflow.py update-line --work "$ocr_work" \
  --review "$ocr_work/review.json" --id ID --patch "$ocr_work/line-patch.json"
```

První sestavení odstavců a hromadné úpravy dokonči validací. Pro následnou opravu řádku používej `update-line`: patch obsahuje celý řádek a výslovné náhrady jeho souvisejících registrů. Příkaz ověří celý přepis před atomickým zápisem a uloží předchozí přepis do `review-history/`. Očekávání testů nemění.

**Hotovo:** validace prošla, všechny řádky patří právě jedné jednotce, kandidáti jsou vypořádaní a vnitřní řádky mají správný `join_after`.

## 6. Geometrie podle nového rastru

```bash
python3 tools/ocr_workflow.py segment --work "$ocr_work" --review "$ocr_work/review.json"
python3 tools/ocr_workflow.py sheets --work "$ocr_work" --lines "$ocr_work/reviewed-lines.json"
```

Nejprve odděl tabulkové údaje podle skutečných sloupců. Původní OCR segmentace zůstává kandidátem; opravovaný token nemá automaticky správný obrazový rozsah. Nástroj používá textové zarovnání tokenů, poměrné šířky NotoSerif a minima inkoustové projekce, takže výsledné znakové řezy jsou **aproximace**. Nové příznaky zůstávají `approximation_requires_character_review` / `requires_character_review`.

Pracovní heuristiky a jejich prahy jsou v `tools/ocr_workflow.py`; nejsou obecně prokázanými mezemi kvality. Řezy před a po přerozdělení zůstávají v `segmentation-events.json`, podezřelé buňky v `checks/unsupported-cells.json` a `checks/geometry-anomalies.json`. Přítomnost popředí nedokládá identitu glyfu.

Prohlédni originály a nové červené překryvy. Kontroluj malé znaky, tečky, pomlčky, jednotlivá písmena, opakované číslice, diakritiku, stín, přesahy do sousedního slova/řádku a volné mezery. `candidate_ink_bbox` není ručně změřený obrys. Každé rizikové přiřazení oprav nebo výslovně ponech otevřené.

Přesné obrazové výjimky zapisuj do polí řádku podle [smlouvy geometrie](ocr-data-contracts.md#geometrie). Explicitní box sám nepotvrzuje správnost.

**Hotovo:** původní výřezy a překryvy byly prohlédnuty; riziková přiřazení jsou opravena nebo jednotlivě evidována jako otevřená. Po opravách stačí znovu prohlédnout dotčené řádky a návaznosti; úplné první čtení se tím nenahrazuje.

## 7. Výběrová očekávání před exportem

Podle **původního rastru** vyber testovací oblasti a jejich očekávané čtení. Box testu získaný z výstupní znakové buňky není nezávislým ověřením její polohy. Nový `samples.json` je seznam položek `id`, `page`, `bbox`, `expected`, `expected_origin`; přidej, kdo a z jakého původního výřezu čtení potvrdil.

Pokryj to, co se v novém dokumentu skutečně vyskytuje: interpunkci, drobné pomlčky/odrážky, samostatná písmena, diakritiku, opakované znaky/číslice, část slova, nadpis, poškozený okraj, tabulky a sousední sloupce. Vyber také každou nově nalezenou podezřelou nebo opravovanou oblast. Počet vzorků ani jejich čtení nejsou předvyplněné.

Připrav také doslovná očekávání ručních výběrů. Původní neúspěšné očekávání zachovej; jeho změna vyžaduje nový obrazový důkaz. **Hotovo:** očekávání i výběrové boxy jsou odvozené ze zdroje před exportem.

## 8. Neviditelná vrstva F a TXT

```bash
python3 tools/ocr_workflow.py export \
  --source "$source_pdf" --work "$ocr_work" --pages "$ocr_work/pages.json" \
  --pdf "$ocr_pdf" --txt "$ocr_txt"
```

Používá se zachovaná konstrukce F v `tools/ocr_f_layer.py`. [ocr-f-construction.md](ocr-f-construction.md) je technická reference pro změny generátoru, fontů, Unicode, tagů a spojování řádků; při běžném průchodu postačí tento workflow a datová smlouva. Diagnostika konstrukce je v `construction-events.json` a nenahrazuje extrakční kontroly.

U nenulové rotace CLI převádí boxy pomocí `page.derotation_matrix` do rámce dočasného zdroje s rotací 0, zavolá stejný generátor F a ve výsledku obnoví původní rotace. Původní vstup se nemění.

TXT je UTF-8: souvislý text jednotek z `pdf_text`, mezi odstavci `\n\n`, mezi články `\n\n\n`, uvnitř tabulkového záznamu tabulátory a mezi navazujícími tabulkovými řádky jeden newline. Původní tiskové zlomy se do logického textu nepřenášejí. TXT a PDF vycházejí ze stejného potvrzeného přepisu.

Export odmítne zastaralý přepis, kandidáty, rastry nebo segmentaci. Uloží jejich hashe, zmrazený přepis `exported-review.json` a očekávání do `export-inputs.json`. Další export automaticky uloží předchozí PDF/TXT, zmrazené vstupy, konstrukci a kontroly do `iterations/`; rozsáhlé OCR a obrazové podklady zůstávají ve work s evidovanými hashi. **Hotovo:** výstupní manifest váže PDF/TXT na aktuální segmentaci.

## 9. Kontroly, opravy a předání

```bash
python3 tools/ocr_workflow.py check \
  --source "$source_pdf" --work "$ocr_work" --pages "$ocr_work/exported-pages.json" \
  --pdf "$ocr_pdf" --txt "$ocr_txt" \
  --reviewer-root /home/gordon/Dokumenty/pdf-ocr-reviewer
python3 tools/ocr_workflow.py samples --work "$ocr_work" --pdf "$ocr_pdf" --samples "$ocr_work/samples.json"
```

`--reviewer-root` je cesta ke skutečnému dostupnému revieweru. Bez něj nástroj tuto cestu netestuje; chybějící kontrolu zapiš jako neprovedenou. Kontrola používá `app.pdf_document.PdfDocument.render_page(index,1250)` pro extrakci `pdf_order` i render.

`check` vrátí kód 1 při selhání povinné technické podmínky; doslovné whitespace rozdíly vykáže samostatně. `samples` vrátí kód 1 při neúspěšném vzorku nebo prázdné sadě. Oba uloží report i při zjištěném neúspěchu. `geometry-samples.json` má nyní objekt `inputs` a seznam `samples`; staré experimentální reporty se nemění.

Rozliš výsledky jednotlivých kontrol:

1. **Technika:** `qpdf --check`; počet, rozměry, crop a rotace stran; dekódovaná obrazová data a původní obsahové streamy; identita renderů MuPDF a Poppler 150 DPI i skutečného revieweru; fonty, tagy a BT; export znaků a pořadí MuPDF/Poppler/reviewer a shoda TXT se společným přepisem. Shoda s přepisem neprokazuje správnost čtení rastru.
2. **Obsah:** skutečná vizuální kontrola, rizikové údaje, opomenuté texty, nejasnosti, rekonstrukce a chyby vydavatele.
3. **Geometrie:** původní výřez, očekávání, nové buňky a skutečná extrakce oblasti. Diagnostické prahy nejsou potvrzení správné polohy.
4. **Whitespace a schránka:** uložit doslovné UTF-8 výstupy. Srovnání bez whitespace ověřuje jen zachování znaků/pořadí. Neprokazuje správné odstavce.
5. **Přijetí:** samostatné rozhodnutí zadavatele o tomto konkrétním výstupu; nevyřešená čtení a neprovedené kontroly zůstávají evidované.

Příkazy a doslovné výsledky uchovává CLI v reportech. `samples` používá aktuální DPI manifestu a převádí rasterový box pro rotaci MuPDF. Originální a výstupní rendery se porovnávají jako dekódované pixely.

Při nálezu zachovej původní neúspěšný případ, jeho oblast, očekávání a doslovný výstup. Oprav přepis nebo geometrii podle rastru a opakuj `validate-review → segment → sheets → export → check → samples`. Při kontrole sheets čti změněné řádky a jejich okolí; techniku a úplnou sadu výběrových vzorků ověř po každém exportu. Původní OCR opakuj jen při změně výřezu nebo potřebě nového kandidáta. Úspěch celé strany neuzavírá chybu malého výřezu.

Proveď připravené ruční případy v dostupné cílové čtečce; ulož doslovné UTF-8 schránky včetně mezer a newline, OS, verzi, způsob a rozsah výběru. Člověku předej stejná očekávání i konkrétní PDF s hashem, pokud UI nemůže ovládat agent. Nedostupná prostředí zůstávají neotestovaná. Podrobný rozsah je v [pdf-copy-compatibility.md](pdf-copy-compatibility.md); extrakce není UI test.

Dokonči `checks/visual-review.json`, `checks/manual-copy/status.json` a jednotlivé otevřené nálezy v `checks/findings.json` podle [smlouvy kontrol](ocr-data-contracts.md#kontroly). Vizuální závěry zůstávají skutečným záznamem čtenáře. Poté spusť:

```bash
python tools/ocr_workflow.py validate-run --work "$ocr_work"
python tools/ocr_workflow.py snapshot --work "$ocr_work"
```

| Kód `validate-run` | Význam a další krok |
|---|---|
| `0` | Kontroly jsou ověřené v zaznamenaném rozsahu; předej výsledek k přijetí. |
| `1` | Technické selhání, zastaralý/chybějící podklad nebo neevidovaný neúspěch; oprav a opakuj kontrolu. |
| `2` | Povinné podmínky prošly, zůstávají jednotlivě doložené otevřené nálezy nebo neprovedené UI zkoušky; předej výsledek s omezeními. |

Souhrn `checks/run-validation.json` kontroluje identitu zdroje/výstupů, vazby reportů, shodu logických jednotek s přepisem a existenci dokladů. Kód 2 neznamená plné ověření geometrie nebo schránky. Přijetí zadavatelem je samostatné rozhodnutí.

**Hotovo:** předej PDF/TXT, jejich manifest, souhrn kontrol a celý work se vstupy, výřezy, přepisem, geometrií, evidencí nejasností/rekonstrukcí/chyb vydavatele a iteracemi. CLI nevytváří vizuální potvrzení, úspěch schránky ani souhlas zadavatele.

## Omezení a samostatná budoucí ověření

- Stejná kvalita na dalších PDF se ověřuje novým čtením, novou geometrií a vlastními kontrolami. Postup nemá předvyplněné očekávání úspěchu.
- Deskew, automatické odstranění existující vrstvy, automatické spojování odstavce přes stránku a odemykání heslem chráněných PDF nejsou implementovány. Takový vstup vyžaduje samostatné rozhodnutí a záznam zásahu.
- Jiný jazyk vyžaduje odpovídající Tesseract model a kontrolu znaků i fontových metrik. Generátor nastavuje katalogové `Lang` na `cs-CZ`; jazyk metadat jiného dokumentu vyžaduje samostatnou úpravu.
- Geometrie, výběr a skutečná schránka se kontrolují pro každý výstup. Automatická extrakce nenahrazuje zkoušku konkrétní čtečky.
- Produkční adresářová organizace a integrace následných oprav z revieweru zůstávají samostatnou implementací. Python závislosti jsou připnuté; změny systému a čteček vyžadují nový `doctor` a příslušné kontroly.

## Dokumentace a ověření nástrojů

Workflow popisuje provádění OCR a kvalitu výsledku. `ocr-f-construction.md` popisuje API a invarianty generátoru a čte se při úpravách konstrukce. Datové smlouvy přepisu, geometrie a kontrol jsou v `ocr-data-contracts.md`.

Při změně nástrojů spusť v prostředí z kroku 1:

```bash
python -m unittest discover -s tests -v
```

Regresní případy používají syntetická data; integrační test vytvoří malý sken a ověří export, obraz, extrakci, cache a archivaci. Vyžaduje závislosti, systémové programy a výchozí fonty tohoto prostředí. CI provádí kontrolu syntaxe a testy podmínek validace se standardní knihovnou; integrační export se bez runtime závislostí výslovně přeskočí.
