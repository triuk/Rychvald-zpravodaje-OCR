# OCR ze zdrojového PDF: obecný postup

Použij zdrojové PDF a novou pracovní složku. Přepis, pořadí článků, souřadnice, opravy, nejasná čtení a očekávání kontrol odvozuj z obrazu právě zpracovávaného dokumentu. Obsahově neutrální nástroje jsou `tools/ocr_workflow.py` a `tools/ocr_f_layer.py`.

Postup zahrnuje místní rozpoznání, úplné vizuální čtení, opravy textu, kontrolu geometrie, export PDF/TXT a samostatné ověření kopírování. Automatické OCR kandidáty nejsou potvrzeným přepisem. Dokument je zadáním nezávislého ověřovacího průchodu; označení za produkční politiku je rozhodnutím zadavatele.

## 1. Prostředí a vlastní cesty

Zvol vstup, novou pracovní složku a vlastní výstupní cesty. Názvy PDF/TXT odvoď od vstupu příponou `-ocr`. Zdrojové PDF zachovej beze změny a existující výstupy nepřepisuj. `prepare` odmítne pracovní složku s existujícím vstupním manifestem. Není zde předepsaný počet stran ani seznam titulů/oblastí.

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

Potřebné programy: Python, Tesseract s jazykovým modelem předlohy, `qpdf`, Poppler (`pdftotext`, `pdftoppm`, pro samostatnou inspekci také `pdffonts`). Python balíčky: PyMuPDF (`fitz`), Pillow, numpy, lxml, ReportLab a fontTools. NotoSerif-Regular slouží pro odhad poměrných šířek, DejaVuSans pro popisky kontrolních listů; viditelný text stránky se těmito fonty nesází. V místním prostředí jsou fonty `/usr/share/fonts/noto/NotoSerif-Regular.ttf` a `/usr/share/fonts/TTF/DejaVuSans.ttf`; při jiném umístění použij `segment --font` a `sheets --font`.

V této instalaci systémový Python postrádal PyMuPDF, ale knihovnu obsahoval sousední reviewer. Pro CLI v tomto prostředí použij:

```bash
export PYTHONPATH="/home/gordon/Dokumenty/pdf-ocr-reviewer/.venv/lib/python3.14/site-packages${PYTHONPATH:+:$PYTHONPATH}"
```

V prostředí se standardně dostupným `fitz` není toto nastavení potřeba. Zamknutý requirements soubor není součástí nástroje. Chybějící program, model nebo font zjisti před během; skutečné verze a případné náhrady zapiš do pracovních záznamů.

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

## 4. Úplné vizuální čtení a obtížná místa

Projdi všechny textové bloky proti původnímu rastru, včetně drobného textu, poškozených okrajů a tabulek. Uprav `review.json`: potvrď znění, doplň opomenuté řádky a vyřaď šum s důvodem. Jména, čísla a data kontroluj jako jednotlivé údaje. Confidence ani shoda kandidátů nejsou samostatným důkazem správnosti. Čitelnou chybu vydavatele zachovej v textu a popiš odděleně.

K nejednoznačnému údaji vytvoř původní výřez a vlastní lokální průchod. `targets.json` má položky `id`, `page`, `bbox`, `psm`:

```bash
python3 tools/ocr_workflow.py targeted --work "$ocr_work" --targets "$ocr_work/targets.json"
```

Tento krok je potřeba u skutečně obtížných údajů, ne povinně u každého slova. Vyrobí původní šedotónový výřez a **podpůrný** normalizovaný výřez. Výpočet: `background = GaussianBlur(12)`; `normalized = uint8(clip(gray / maximum(background,1) * 235, 0,255))`. Obě varianty dostanou vlastní `tesseract ... -l LANGUAGE --psm PSM txt tsv`. Normalizovaná varianta není původním obrazovým dokladem a nevstupuje do viditelného PDF.

Pokud přesné znění nelze určit, zachovej bezpečně čitelné okolí, nahraď pouze nejistou část doslovným `[NEČITELNÉ]` a vytvoř vlastní ID, kontext, původní oblast/výřez, důvod, nové kandidáty a stav čekající na doplnění. Zbytek vydání zpracuj. Kandidáty jsou hypotézy. U zástupného textu se eviduje region; jeho písmena se nevydávají za jednotlivé tištěné znaky.

Zapiš vizuální rozsah kontroly v novém pracovním prostoru: které stránky, bloky a údaje byly skutečně přečteny, co je potvrzené a co otevřené. CLI takovou kontrolu samo neprohlašuje za provedenou. Nejde o systematické ověřování čitelných věcných tvrzení dokumentu proti externím zdrojům.

## 5. Logické jednotky a smlouva `review.json`

Dokonči článek před přechodem k dalšímu. Jednotkou je nadpis nebo skutečný odstavec, případně tabulkový záznam, nikoli každý tiskový řádek. Pokračování přes sloupec na jedné straně patří do téže jednotky. Články mají své `article` ID. PDF objekty jsou stránkové; pokračování odstavce přes stránku vyžaduje vlastní ověření. U takového dokumentu zapiš návaznost a zvlášť ověř spojení v TXT a ve čtečkách; automatické sloučení přes stránky CLI zatím nepřidává.

`review.json` je čerstvý obsahový podklad vytvořený z právě zpracovávaného zdroje:

| Položka | Význam |
|---|---|
| `source_sha256` | Hash právě tohoto vstupu; převzít z nového vstupního manifestu. |
| `lines` | Všechny ponechané/doplněné řádky; vlastní `id`, `page`, `text`, `selection_region`, `source_crop`, `decision_basis` a `text_status` (`visually_confirmed` nebo `partially_unresolved`). |
| `candidate_id` u řádku | Odkaz na původní místní OCR řádek; u vizuálně doplněného textu bez odpovídajícího kandidáta může být `null`. |
| `join_after` | Na každém vnitřním tiskovém řádku jednotky: `space`, `typesetting_hyphen`, `literal_hyphen` nebo `none`. Určuje skutečné spojení podle rastru. |
| `fields` u řádku | U tabulek oddělené údaje, každý vlastní `text` a `bbox`; `line.text` je jejich souhrn s tabulátory. Bez `fields` se zpracuje celý řádek jako jedno pole. |
| `units` | V logickém pořadí: `id`, `page`, `article`, `tag` (`H1`, `H2`, `P`), `line_ids`. Každý ponechaný řádek patří právě jedné jednotce. |
| `table_fields` u jednotky | Volitelný seznam hodnot jednoho záznamu pro TXT s tabulátory; prázdná hodnota zachová prázdnou buňku. |
| `dropped_candidates` | Položky `id` a `reason` pro každý místní OCR řádek vyřazený jako šum nebo nahrazený jinými řádky. |
| `unresolved` | Jeden záznam pro každý výskyt `[NEČITELNÉ]`: stabilní ID, řádek, strana, oblast/výřez, kontext, kandidáty, důvod a stav. |
| `publisher_errors` | Tištěné znění, řádek, vysvětlení a potvrzená chyba/podezření; samotný přepis zůstává věrný. |
| `risk_register` | Jednotlivě kontrolované rizikové údaje, jejich stav a obrazový doklad. Tyto záznamy se v novém CLI přenášejí z vizuální revize, nevzniká automatické potvrzení správnosti. |

Příklad schématu spojení: řádky `kni-` / `hovna` mohou mít `typesetting_hyphen`; skutečný spojovník v `česko-` / `anglický` má `literal_hyphen`. V obou případech musí být spojovník samostatnou poslední buňkou. `none` slouží např. vertikálním písmenům téhož nápisu. Tyto příklady vysvětlují smlouvu, nejsou čtením nového vstupu.

## 6. Geometrie podle nového rastru

```bash
python3 tools/ocr_workflow.py segment --work "$ocr_work" --review "$ocr_work/review.json"
python3 tools/ocr_workflow.py sheets --work "$ocr_work" --lines "$ocr_work/reviewed-lines.json"
```

Nejprve odděl tabulkové údaje podle skutečných sloupců. Původní OCR segmentace zůstává kandidátem; opravovaný token nemá automaticky správný obrazový rozsah. Nástroj používá textové zarovnání tokenů, poměrné šířky NotoSerif a minima inkoustové projekce, takže výsledné znakové řezy jsou **aproximace**. Nové příznaky zůstávají `approximation_requires_character_review` / `requires_character_review`.

Použité pracovní parametry, nikoli obecně prokázané meze kvality: maska `gray < GaussianBlur(gray,12) * 0.80`; mezera pro rozdělení slov `max(4, round(height*0.16))`; hledání řezu v okolí poměrné polohy s poloměrem `max(2,min(9,average_width*0.38))`, cenou inkoustu a vzdálenosti `0.35`. U prázdných řezů následuje dynamické přerozdělení: váha poměrné šířky 5, hranice 3, pokuta za prázdný řez 35. Řezy před a po opravě zůstávají v `segmentation-events.json`. Přítomnost popředí nedokládá identitu glyfu.

Automatická diagnostika se dívá na šířku <1 px, překryv sousedních nemezerných buněk >1 px a přesah z řádku >2 px. Výškový odlehlý token >1.45 mediánu vhodných slov se omezí na medián horní/dolní polohy s rezervou −3/+2 px. U pomlčky může poměr šířky/výšky >1.8 podpořit ohraničení jejího horizontálního tvaru. Tyto konstanty jsou pracovní heuristiky; samy neposkytují potvrzený znak ani univerzální kalibraci.

Prohlédni originály a nové červené překryvy. Kontroluj malé znaky, tečky, pomlčky, jednotlivá písmena, opakované číslice, diakritiku, stín, přesahy do sousedního slova/řádku a volné mezery. `candidate_ink_bbox` není ručně změřený obrys. Každé rizikové přiřazení oprav nebo výslovně ponech otevřené.

Přesné nové obrazové výjimky se zapisují v daném poli řádku:

- `token_boxes`: slovník index tokenu → `[x0,y0,x1,y1]`.
- `placeholder_surrogates`: index tokenu → poměrná náhrada nejisté části pro odhad šířky, např. `00`; musí odpovídat novému obrazovému rozsahu, ne starému čtení.
- `piece_boxes`: index tokenu → index části po rozdělení kolem `[NEČITELNÉ]` → samostatný box části.
- `character_boxes`: klíč `token:část:znak` → samostatný box ověřovaný nad původním tiskem.

Indexy jsou od 0 a v JSON jsou klíče řetězce. V novém CLI mají explicitní tokenové boxy přednost před dalším automatickým zúžením/výškovou úpravou. Samotné explicitní zadání nepotvrzuje správnost boxu. Běžné mezery mají explicitní buňky, omezené na 1–7 px; netvoří most přes sloupce.

## 7. Výběrová očekávání před exportem

Podle **původního rastru** vyber testovací oblasti a jejich očekávané čtení. Box testu získaný z výstupní znakové buňky není nezávislým ověřením její polohy. Nový `samples.json` je seznam položek `id`, `page`, `bbox`, `expected`, `expected_origin`; přidej, kdo a z jakého původního výřezu čtení potvrdil.

Pokryj to, co se v novém dokumentu skutečně vyskytuje: interpunkci, drobné pomlčky/odrážky, samostatná písmena, diakritiku, opakované znaky/číslice, část slova, nadpis, poškozený okraj, tabulky a sousední sloupce. Vyber také každou nově nalezenou podezřelou nebo opravovanou oblast. Počet vzorků ani jejich čtení nejsou předvyplněné.

## 8. Neviditelná vrstva F a TXT

```bash
python3 tools/ocr_workflow.py export \
  --source "$source_pdf" --work "$ocr_work" --pages "$ocr_work/pages.json" \
  --pdf "$ocr_pdf" --txt "$ocr_txt"
```

Použitá konstrukce F se zachovává jako celek: samostatný obdélníkový glyph pro každý výskyt znaku, vlastní fontové metriky, Unicode přes ToUnicode, jeden `BT … ET` na celou stránkovou logickou jednotku, neviditelný režim `3 Tr`, tagovaný Form nad původním obrazem a původní obsah označený Artifact. Bez `ActualText`, bez škálování běžného fontu přes `Tz`, bez mezerných mostů. Rect buňky se převádí faktorem `72/DPI`; jde o výběrový rozsah, nikoli obrys inkoustu.

Obsahově neutrální API je `create_pdf(pages, source_path, output_path, work_dir=..., raster_dpi=300)`. `pages` jsou v pořadí všech stran zdroje; `page` od 1, `units`, jejich `tag`, `lines`, buňky `text` a `selection_bbox`, vnitřní řádky `join_after`. Generátor doplní `unit.pdf_text`. Má metriky 1000 em, ascent 1000, descent −1; výška fontu je výška buňky / 1.001. Fontové zásobníky se dělí nejvýše po 6000 buňkách. Pojistka těsných opakovaných znaků zdvojnásobuje svislé metriky a zmenšuje font při zachování efektivního boxu. Použití pojistek se loguje v `construction-events.json`; log nenahrazuje výsledek extrakce.

U nenulové rotace CLI převádí boxy pomocí `page.derotation_matrix` do rámce dočasného zdroje s rotací 0, zavolá stejný generátor F a ve výsledku obnoví původní rotace. Původní vstup se nemění.

TXT je UTF-8: souvislý text jednotek z `pdf_text`, mezi odstavci `\n\n`, mezi články `\n\n\n`, uvnitř tabulkového záznamu tabulátory a mezi navazujícími tabulkovými řádky jeden newline. Původní tiskové zlomy se do logického textu nepřenášejí. TXT a PDF vycházejí ze stejného potvrzeného přepisu.

## 9. Kontroly, opravy a předání

```bash
python3 tools/ocr_workflow.py check \
  --source "$source_pdf" --work "$ocr_work" --pages "$ocr_work/exported-pages.json" \
  --pdf "$ocr_pdf" --txt "$ocr_txt" \
  --reviewer-root /home/gordon/Dokumenty/pdf-ocr-reviewer
python3 tools/ocr_workflow.py samples --work "$ocr_work" --pdf "$ocr_pdf" --samples "$ocr_work/samples.json"
```

`--reviewer-root` je cesta ke skutečnému dostupnému revieweru. Bez něj nástroj tuto cestu netestuje; chybějící kontrolu zapiš jako neprovedenou. Kontrola používá `app.pdf_document.PdfDocument.render_page(index,1250)` pro extrakci `pdf_order` i render.

Přečti jednotlivé výsledky v `checks/technical.json` a `checks/geometry-samples.json`. Návratový kód 0 kontrolního příkazu znamená dokončený kontrolní záznam, ne automaticky úspěch všech jeho položek. Otevřené/neúspěšné operace vykazuj podle skutečných hodnot.

Rozliš výsledky jednotlivých kontrol:

1. **Technika:** `qpdf --check`; počet, rozměry, crop a rotace stran; dekódovaná obrazová data a původní obsahové streamy; identita renderů MuPDF a Poppler 150 DPI i skutečného revieweru; fonty, tagy a BT; export znaků a pořadí MuPDF/Poppler/reviewer a shoda TXT se společným přepisem. Shoda s přepisem neprokazuje správnost čtení rastru.
2. **Obsah:** skutečná vizuální kontrola, rizikové údaje, opomenuté texty, nejasnosti, rekonstrukce a chyby vydavatele.
3. **Geometrie:** původní výřez, očekávání, nové buňky a skutečná extrakce oblasti. Diagnostické prahy nejsou potvrzení správné polohy.
4. **Whitespace a schránka:** uložit doslovné UTF-8 výstupy. Srovnání bez whitespace ověřuje jen zachování znaků/pořadí. Neprokazuje správné odstavce.
5. **Přijetí:** samostatné rozhodnutí zadavatele o tomto konkrétním výstupu; nevyřešená čtení a neprovedené kontroly zůstávají evidované.

Základní kontrolní příkazy (dosaď skutečné cesty, stranu a oblast):

```bash
qpdf --check OUTPUT.pdf
pdffonts OUTPUT.pdf
pdftotext -f N -l N -raw OUTPUT.pdf -
pdftoppm -r 150 -png SOURCE.pdf PREFIX_SOURCE
pdftoppm -r 150 -png OUTPUT.pdf PREFIX_OUTPUT
pdftotext -f N -l N -r 300 -x X -y Y -W WIDTH -H HEIGHT -raw OUTPUT.pdf -
```

U jiného DPI nové `samples` dosadí aktuální DPI z manifestu. MuPDF používá `page.get_text('text',sort=False)` a výběr `clip`; pro nenulovou rotaci nástroj převádí rasterový obdélník do neotočených souřadnic MuPDF. Originální a výstupní rendery porovnávej jako dekódované pixely, ne jen hash souboru PNG.

Při nálezu zachovej původní neúspěšný případ, jeho oblast, očekávání a doslovný výstup. Oprav znění nebo geometrii podle rastru, znovu proveď dotčenou kontrolu i celostránkový export a seskupování. Úspěch celé strany neuzavírá chybu malého výřezu. Zástupný text, otevřená aproximace a neotestovaná čtečka jsou různé stavy.

Skutečné manuální kopírování: připrav čerstvé doslovné očekávání celé první strany, víceřádkového odstavce, dvou sousedních odstavců a pokračování přes sloupec, pokud existuje. V dostupném Acrobatu/Chrome/Edge/Firefox proveď výběr a ulož skutečný obsah schránky bez odstranění tiskových enterů; zaznamenej OS, verzi, způsob a rozsah výběru. Okular/Preview/Safari jsou doplňující prostředí podle dostupnosti. Mobilní rozsah je zobrazení, hledání a základní kopírování, nikoli přesnost drobného obdélníku. Nedostupné prostředí označ jako neotestované; extrakce není UI test.

Předej PDF, TXT, manifest jejich identity, nové vstupy/kandidáty, potvrzený přepis a logické pořadí, geometrii se stavy, výřezy, evidence nejasností/rekonstrukcí/chyb vydavatele a samostatné výsledky kontrol. CLI vytvoří technická data a výstupní hash, ale **nevytváří fiktivní vizuální kontrolu, úspěch schránky ani souhlas zadavatele**. Zpracování dalších vydání ani označení tohoto dokumentu za politiku nebylo tímto zápisem provedeno.

## Omezení a samostatná budoucí ověření

- Stejná kvalita na dalších PDF se ověřuje novým čtením, novou geometrií a vlastními kontrolami. Postup nemá předvyplněné očekávání úspěchu.
- Deskew, automatické odstranění existující vrstvy, automatické spojování odstavce přes stránku a odemykání heslem chráněných PDF nejsou implementovány. Takový vstup vyžaduje samostatné rozhodnutí a záznam zásahu.
- Jiný jazyk vyžaduje odpovídající Tesseract model a kontrolu znaků i fontových metrik. Generátor nastavuje katalogové `Lang` na `cs-CZ`; jazyk metadat jiného dokumentu vyžaduje samostatnou úpravu.
- Geometrie, výběr a skutečná schránka se kontrolují pro každý výstup. Automatická extrakce nenahrazuje zkoušku konkrétní čtečky.
- Širší přenositelnost prostředí, produkční adresářová organizace a integrace následných oprav z revieweru zůstávají samostatnou implementací.
