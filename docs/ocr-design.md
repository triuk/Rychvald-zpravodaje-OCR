# Návrh zpracování zpravodajů

Stav: návrhový rozhovor podle `grill-with-docs`, rozhodnutí Q1–Q14 zaznamenána. Technickou nejistotu kopírování má vyřešit další vlákno; toto vlákno nyní slouží k dokumentaci a předání. Tento dokument neznačí schválení implementace celé dávky; po výsledku experimentu zbývá potvrdit společný návrh.

## Potvrzené požadavky

- Vstupem pilotu je zdrojový sken `zpravodaj-2000-05-c03.pdf`.
- Později přibude více než sto PDF a následně další soubory.
- Prioritou je kvalita OCR, návaznost článků a přirozené označování textu nad obrazem stránky a kopírování například do Wordu. Požadavek „archivní kvalita“ sám o sobě nevyžaduje konkrétní PDF standard.
- Špatně čitelné znění se má nejprve rekonstruovat z obrazu a kontextu. Zejména u jmen a čísel může následovat hledání odpovídajícího údaje na internetu. Při neúspěchu má vzniknout vhodný placeholder a místo pro doplnění zadavatelem.
- Font má být pokud možno univerzální. Konkrétní volba a způsob vložení jsou otevřené.
- Po autonomní fázi všech PDF následuje kontrola v samostatném projektu `pdf-ocr-reviewer` a export manifestu revize.
- Setup skills již je hotový; jeho opakování není předmětem práce.
- Čitelné chyby vydavatele se zachovávají a současně evidují odděleně s vysvětlením, proč jde o chybu. Evidenci není dovoleno zaměnit za tichou opravu textu. Evidují se chyby nalezené při OCR a rekonstrukci, nikoli systematické ověření všech čitelných jmen, dat a tvrzení; věcné chyby potřebují doklad a neprokázaná podezření se odliší.
- Výstupy zahrnou OCR PDF, samostatný text článků a pracovní data pro opakovatelné opravy. DOCX nyní není požadován.
- Rozpoznávání začne místním OCR a kontrolou dostupnými nástroji, bez zapojení nových placených služeb. To není požadavek na výhradně místní zpracování všemi nástroji. Hledání údajů na internetu zůstává součástí rekonstrukce.
- Kopírovaný odstavec má být plynulý: bez pevných konců tiskových řádků, s logickými odstavci a spojením slov rozdělených sazbou, ale se zachováním skutečných spojovníků. Současně má být možné vybrat nad skenem jen část slova, například `využ` ze slova `využíván`, a zkopírovat přesně vybrané znaky. Toto je požadavek na pilot, nikoli dosud prokázaná vlastnost výsledného PDF.
- Rozsah přepisu zahrnuje veškerý čitelný tištěný text včetně inzerce, hlaviček, tiráže, popisků a tabulek. Články se dokončují přes navazující sloupce; ostatní bloky jsou oddělené a tabulky zachovají vztah záhlaví a řádků. Dekorace bez textu se nepřepisují.
- Běžná slova lze rekonstruovat při silné opoře v kontextu a zaznamenat důvod. Nejednoznačná jména, čísla a data bez odpovídajícího dokladu dostanou `[NEČITELNÉ]`; evidence váže místo na stránku, výřez a případné kandidáty. Každou takovou rekonstrukci není nutné předem potvrzovat.
- Při nevyřešených místech se pokračuje dalšími PDF. Zadavateli se předávají souhrny po vydáních; dotčená vydání čekají na doplnění a nejsou dokončená, dokud se odpovědi nezapracují. Reviewer následuje až po uzavření celé dávky.
- PDF jsou určena široké veřejnosti, nikoli jedné konkrétní čtečce zadavatele. Kopírování pokračování článku přes další stránky je relevantní, byť takové články jsou podle zadavatele vzácné.
- Hlavní kompatibilita se ověřuje důkladně na počítačích. Na Androidu a iOS stačí základní kontrola zobrazení, vyhledávání a kopírování; přesný výběr několika znaků dotykem není podmínkou dokončení.
- Samostatný text dokončí každý článek přes navazující sloupce a stránky. Články řadí podle místa začátku: stránky vzestupně, v běžné sloupcové sazbě zleva doprava. Nadpis přes více sloupců patří článku; inzeráty, popisky a tabulky jsou oddělené bloky. PDF zachovává původní stránkování.
- Nejprve má vzniknout pilot; případný kompromis v kopírování se rozhodne nad skutečnými výsledky před dávkou. Zadavatel výslovně požaduje experiment a pilot řešit v jiném vlákně.
- Zadavatel může ručně ověřit Acrobat. Word byl příklad následného využití kopírovaného textu, nikoli požadavek na otevírání PDF ve Wordu nebo povinné ověření tímto programem. Kontroly mají primárně porovnávat přesné znění schránky a výběr nad skenem.

## Strom rozhodnutí

První kolo je uzavřeno:

1. **Rozhodnuto:** zachovat obraz skenu a opravovat neviditelnou textovou vrstvu; narovnání je přípustné. Rozsah dalších obrazových zásahů tím schválen nebyl. Viz ADR 0001.
2. **Rozhodnuto:** zachovat chyby vydavatele a odděleně je evidovat s vysvětlením. Viz ADR 0002.
3. **Rozhodnuto:** OCR PDF, text článků a pracovní data; bez DOCX.
4. **Rozhodnuto:** místní OCR a dostupné nástroje, bez nových placených služeb.

Druhé kolo — rozhodnutí a otevřená technická otázka:

5. **Požadavek rozhodnut:** přirozené odstavce i výběr části slova. **Otevřeno:** doložit současnou splnitelnost v běžných veřejných čtečkách; nesnižovat bez domluvy jeden požadavek kvůli druhému. Cílený průzkum je v `docs/pdf-copy-compatibility.md`: cíle se významově nevylučují, ale čtečky mohou odvozovat konce řádků z geometrie; univerzální splnění nebylo prokázáno.
6. **Rozhodnuto:** všechny čitelné tištěné texty, včetně tabulek a inzerce.
7. **Rozhodnuto:** silně podložená rekonstrukce s evidencí; jinak `[NEČITELNÉ]` a záznam místa.
8. **Rozhodnuto:** pokračovat dávkou, souhrny po vydáních; čekající vydání dokončit až po zapracování doplnění.
9. **Rozhodnuto:** veřejné použití; sadu čteček má navrhnout agent. Rozsah mobilního ověření je rozhodnutý v Q11.
10. **Rozhodnuto:** evidence chyb nalezených při OCR a rekonstrukci, nikoli úplné ověření věcných tvrzení.

Třetí kolo je uzavřeno:

11. **Rozhodnuto:** důkladná hlavní počítačová sada a základní kontrola Android/iOS; přesnost dotykového výběru znaků neblokuje dokončení.
12. **Rozhodnuto:** samostatný text po souvislých článcích, včetně pokračování přes stránky. Články se řadí podle místa začátku. PDF zachovává původní stránkování.

Čtvrté kolo je uzavřeno:

13. **Rozhodnuto:** pilot nejprve, případný kompromis rozhodnout nad výsledky před dávkou. Experiment a pilot se mají odehrát mimo toto vlákno.
14. **Rozhodnuto:** zadavatel může ručně ověřit Acrobat. Word není povinné testovací prostředí; účelem je kopírovat text do libovolného vhodného cíle. Dostupnost dalších mimohostitelských čteček nebyla potvrzena a nesmí se uvádět jako ověřená.

Zbývá technický experiment v novém vlákně a následné společné potvrzení konkrétního návrhu, včetně skutečně prokázané kompatibility, adresářů, evidence a hranice integrace revieweru. Rutinní implementační volby lze pak řešit podle doložených výsledků.

## Dosud ověřené skutečnosti

- Zdrojový sken je v rootu projektu. Nový prototyp vznikne v samostatném vlákně.
- Před zahájením rozhovoru neexistoval `GLOSSARY.md` ani rozhodnutí v `docs/adr/`.
- Návrhový průzkum neposkytuje schválený OCR přepis. Kvalita nového zpracování se ověřuje vůči zdrojovému rastru.

### Zdrojové PDF

- Zdroj představuje šestistránkové číslo 3/2000 (květen–červen) a nemá textovou vrstvu.
- Skeny jsou ve stupních šedi, přibližně 200 dpi. Šířky stránek se liší; nelze používat jednotnou předpokládanou geometrii A4.
- Rozvržení zahrnuje dva až tři sloupce, pokračování článků, inzerci, fotografie a tabulky jmen a dat. Na stranách 2 a 4 jsou poškozené nebo oříznuté pravé konce některých řádků.
- Správnost přepisu a chování označování a clipboardu je třeba doložit novým zpracováním.

### Existující reviewer

Ověřeno čtením aktuálního kódu a dokumentace, bez spuštění integračního testu:

- Soubor `pdf-ocr-reviewer.manifest.json` se ukládá průběžně ve vybrané složce. Manifest má `schema_version=2`, instrukce oprav `repair_instructions.version=3`.
- Reviewer prochází PDF přímo ve zvolené složce, nerekurzivně, a nerozlišuje zdroje od výsledků. Záznamy dokumentů klíčuje přesným názvem PDF.
- `ocr_sha256` kotví konkrétní obsah výsledného PDF. `source_sha256` připomínky je při jejím vytvoření také hash otevřeného OCR PDF, nikoli hash zdrojového skenu.
- `page_index` začíná nulou. `bbox` používá PDF body od levého horního rohu zobrazené stránky po ořezu a rotaci (`displayed_page_points_top_left`). Zachytí se rozměry stránky i její rotace.
- Text zadání opravy je v `note`; `text` a `targets` popisují vybraný současný OCR text. Samostatné `corrected_text` manifest nemá.
- Změna geometrie naruší vazbu připomínek. Změna textové vrstvy mění hash; pozdější opravný průchod musí bezpečně aktualizovat kotvy a historii, nikoli jen přepsat PDF a JSON.
- Automatické nalezení zdrojového PDF a souborů `-qa2.md` a `-qa3.md` očekává sousední soubory. Oddělené zdroje vyžadují řešení relativních `resources`; jeho úplnou funkčnost ověří pozdější integrační test.

Podklady: `../pdf-ocr-reviewer/app/manifest.py`, `app/review.py`, `app/api.py`, `app/folder_scanner.py`, `app/pdf_document.py`, `docs/region-review.md` (cesty po první jsou relativní ke kořeni projektu revieweru).

### Místní nástroje a font

- Dostupný je Tesseract 5.5.3 s českým modelem `ces` a výstupy hOCR, TSV, ALTO, PDF a TXT. Konkrétní varianta českého modelu nebyla určena.
- Dostupné jsou Poppler, qpdf, Ghostscript, ImageMagick, Pillow, NumPy a ReportLab 5.0.1. PyMuPDF 1.26.7 je v prostředí sousedního revieweru; samostatné prostředí tohoto projektu zatím neexistuje.
- Font `/usr/share/fonts/noto/NotoSans-Regular.ttf` obsahuje ověřené české znaky včetně velkých písmen s diakritikou. Noto Sans je kandidát pro jednotný font, nikoli dosud přijatá implementační volba.
- Dostupnost nástrojů dokládá možnost místního pilotu. Neprokazuje dostatečnou kvalitu OCR, rekonstrukce, geometrie ani kopírování výsledku.

### Pořadí čtení a kopírování — podklady pro pilot

PDF může ukládat text v jiném pořadí, než naznačuje jeho poloha. Pouhé řazení všech řádků podle souřadnic neřeší vícesloupcové články; jejich hranice je potřeba určit samostatně. Viz [PyMuPDF: Text](https://pymupdf.readthedocs.io/en/latest/recipes-text.html) a [PyMuPDF: FAQ](https://pymupdf.readthedocs.io/en/latest/faq/index.html).

Tagovaná struktura může vyjádřit pořadí i návaznosti odstavců; Adobe popisuje její použití pro reflow. Z toho pro projekt vyvozujeme, že tagování může pomoci, ale jeho přítomnost sama nedokládá správný výběr myší a obsah schránky. Viz [PDF Association: přístupnost a strojově čitelný text](https://pdfa.org/understanding-pdf-accessibility-techniques/) a [Adobe: reflow](https://helpx.adobe.com/acrobat/using/reading-pdfs-reflow-accessibility-features.html).

`ActualText` umí vyjádřit náhradní znění úseku, ale není vhodné spoléhat na něj jako na jediný nosič českého textu a spojení dělených slov. Pro skeny se doporučují neviditelné textové objekty odpovídající skutečným textům; podporu konkrétními prohlížeči musí ověřit pilot. Viz [Tagged PDF Best Practice Guide, §5.5.3](https://pdfa.org/wp-content/uploads/2023/07/Tagged-PDF-Best-Practice-Guide.pdf) a [PDF.js: issue podpory ActualText](https://github.com/mozilla/pdf.js/issues/12237).

Jednotný font v neviditelné vrstvě je reálný: Tesseract/PyMuPDF používá `GlyphLessFont`. Kvalita geometrie výběru je samostatná vlastnost, kterou font automaticky nezaručuje. Viz [PyMuPDF: OCR](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html).

Návrh ověření pilotu: porovnat přesný kopírovaný text s potvrzenými vzorky pro diakritiku, jména, čísla, nadpis, část slova, odstavec, dělené slovo a vícesloupcový článek. Pro veřejné použití doporučujeme hlavní sadu Acrobat Reader, Chrome, Edge a Firefox, doplňkově Preview/Safari a Okular podle dostupnosti zařízení; mobilní kontrola je základní podle Q11. Plynulost odstavce ověřit v textu schránky a vložením do běžného textového cíle, bez pevných tiskových konců řádků. Word je pouze možný příklad cíle. Celé články přes více stránek ověřit v samostatném textovém exportu i v PDF podle skutečné čtečky. Automatická extrakce není náhradou kontroly výběru a schránky. Podrobnosti a zdroje: `docs/pdf-copy-compatibility.md`.

## Doporučená adresářová struktura — dosud neschválená

```text
Rychvald-zpravodaje-OCR/
├── AGENTS.md
├── GLOSSARY.md
├── docs/                    # návrh, pokyny a přijatá ADR
├── input/                   # zdrojová PDF, později sem přibudou další
├── work/
│   └── <identifikátor>/      # přepis, geometrie, rekonstrukce, nevyřešená místa
└── output/
    ├── pdf/                 # plochá složka hotových -ocr.pdf pro reviewer
    │   └── pdf-ocr-reviewer.manifest.json  # vytvoří reviewer při kontrole
    └── text/                # schválený samostatný text článků
```

Návrh odděluje zdrojové vstupy od výsledků tak, aby reviewer nenabízel původní skeny jako dokumenty k opravě. Podoba identifikátorů, evidence verzí a pracovních souborů ještě není rozhodnutá. Produkční adresářová struktura zatím nebyla provedena; zdrojový sken zůstává v rootu.

## Doporučení k pozdější revizi

Minimální smlouvu s reviewerem je účelné promyslet před dávkou: stabilní názvy výsledků, plochou výstupní složku, vlastní evidenci hashů zdrojů i výsledků, opravitelné pracovní přepisy a geometrii. Narovnání je třeba dokončit před ruční kontrolou. Podrobné provádění oprav a aktualizaci manifestu lze probrat po autonomní fázi. Jde zatím o doporučení k rozhodnutí zadavatelem; manifest revieweru nemá nahrazovat interní evidenci OCR ani seznam nevyřešených míst.

## Konkrétní návrh workflow pro společné potvrzení

Následující návrh rozvádí přijaté požadavky. Neznamená ještě spuštění OCR nebo schválení všech organizačních voleb.

1. Zdrojová PDF uložit do `input/` a zachovat bez změny obsahu; názvy dosavadních souborů není třeba měnit. Další PDF bude zadavatel přidávat do `input/`.
2. Každé vydání evidovat podle stabilního názvu a hashe zdroje. Stejný obsah znovu nezpracovávat bez důvodu; jiný obsah se stejným názvem nesmí potichu přepsat dosavadní zdroj nebo výsledek. Nové nebo změněné vstupy odlišit od již dokončených vydání.
3. Pracovní data v `work/<identifikátor>/` uchovají zdrojovou a výslednou verzi, strukturu článků a odstavců, rozpoznaný text, polohy slov a znaků, vazbu spojených slov na tiskové řádky a případný převod geometrie po narovnání. Konkrétní datové schéma určí a ověří pilot; data musí umožnit lokální opravu bez ztráty ostatních potvrzených oprav.
4. Místní OCR vytvoří první přepis a geometrii. Následuje kontrola všech stránek a textových bloků agentem, oprava pořadí článků, rekonstrukce obtížných pasáží a cílené dohledání údajů. Číselná jistota OCR sama o sobě nerozhoduje o správnosti. Poškozené okraje nelze „opravit“ pouhým zvýšením renderovacího DPI.
5. Pro nevyřešená místa, doložené rekonstrukce a chyby vydavatele vést odlišné záznamy s místem ve zdroji. Rekonstrukce má důvod a případný externí doklad; vydavatelská chyba původní znění a vysvětlení; nevyřešené místo výřez, kontext a kandidáty. Předávání souhrnů po vydáních umožní zapracování odpovědí bez přerušení ostatních dokumentů.
6. Narovnání provádět jen podle potřeby, bez ztráty obsahu stránky, a dokončit před ruční kontrolou. Viditelný obraz nepřestavovat. Jednotný font navrhnout z ověřeného Noto Sans; pokud by pilot ukázal nevhodnou geometrii, vybrat jiný Unicode font a změnu zdůvodnit. Font sám nesmí být považován za řešení výběru znaků.
7. Vytvořit `output/pdf/<původní-název>-ocr.pdf` a `output/text/<původní-název>.txt` v UTF-8. Text obsahuje souvislé články a skutečné odstavce; tabulkový text zachová členění na řádky a sloupce. PDF a textový export vycházejí ze stejného potvrzeného přepisu. Vlastní evidence a reporty zůstávají oddělené od manifestu revieweru.
8. Pilot je celé dodané šestistránkové vydání. Zahrne úplný přepis, kontroly jmen a čísel, složité sloupce a tabulky, reprezentativní výběr znaků, schránku a textový export. Výsledky veřejné kompatibility se zapíší jako otestované nebo neotestované pro konkrétní čtečku; přesná brána do dávky je Q13–Q14.
9. Po přijetí pilotu zpracovávat další vydání po obnovitelných krocích. Přerušení nesmí ztratit potvrzené opravy. Hotová vydání mají zkontrolované pořadí a text, odpovídající výstup a žádná nevyřešená místa. Stav čekající na doplnění, technická chyba a dokončení se odliší. Agent v rámci autonomie kontroluje každou stránku; nejde o požadavek, aby zadavatel ručně porovnával všechny stránky už před reviewerem.
10. Po uzavření celé nahrané dávky zadavatel otevře `output/pdf/` v revieweru. Nyní se připraví stabilní názvy, verze a geometrická vazba; následné provádění oprav z manifestu, aktualizace kotev a jejich historie se navrhne podrobně až po autonomní fázi. Reviewer manifest nevytvářet předem jako náhradu ručních připomínek.

Bez nových placených služeb a bez požadavku na konkrétní PDF archivní standard. Výkonnostní optimalizace a výběr knihoven se podřizují kvalitě prokázané pilotem; nevytváří se obecný OCR produkt ani nový reviewer.

## Doporučený další krok podle ask-matt — v novém vlákně

`ask-matt` směruje nevyřešitelnou technickou otázku do prototypu s předáním výsledků zpět. Konkrétní místní skill `prototype` ale nabízí HTML ukázku logiky nebo varianty UI. Pro tento problém je vhodnější princip malého prototypu provést jako skutečný PDF experiment podle skillu `pdf`; HTML ukázka by neprokázala chování veřejných PDF čteček.

1. Převzít dokumentaci prostřednictvím `handoff`; setup skills se neopakuje.
2. V izolované pracovní složce připravit krátký experiment na jedné stránce nebo několika skutečných úsecích zdrojového skenu, s předem ručně ověřeným textem. Ověřuje se konstrukce textové vrstvy, nikoli dosud kvalita OCR celého vydání.
3. Použít skutečná testovací PDF. Prověřit část nerozděleného slova, část slova rozděleného sazbou, odstavec přes tiskové řádky, českou diakritiku a sousední sloupce. Zkoušet pouze malé varianty vrstvy potřebné pro rozhodnutí; nebudovat vlastní PDF prohlížeč.
4. Zaznamenat přesný clipboard a geometrii výběru ve skutečně dostupných čtečkách. Připravit krátké instrukce k ručnímu ověření Acrobatem zadavatelem. Jasně rozlišit funkční, nefunkční, neotestované a případně omezené operace.
5. Experiment uzavřít reprodukovatelným příkazem, zachovanými zdrojovými variantami a reportem odkazujícím na testovací PDF. Report má odpovědět, zda alespoň některá varianta současně splnila znakový výběr a plynulý odstavec, a kde zůstává omezení čtečky. Výsledek předat zpět; širší kompatibilitu nelze vyvozovat z jednoho extraktoru.
6. Podle výsledku upřesnit návrh a uzavřít společné porozumění. Teprve poté připravit udržitelné workflow a celý šestistránkový OCR pilot. Celá dávka následuje až po přijetí pilotu podle Q13.

Tento experiment nemění zdrojové PDF ani reviewer. Navržený přesun zdrojů do `input/` zůstává součástí následného společného potvrzení, nikoli předpokladem experimentu.
