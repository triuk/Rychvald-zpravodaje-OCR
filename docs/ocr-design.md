# Návrh zpracování zpravodajů

Stav k 13. 10. 2026: Q13–Q14 jsou uzavřené ověřeným workflow, Q15 určuje cílové rozšíření revieweru o OCR a Codex, Q16 nejprve Linux a Q17 nejprve OCR prostředí a proces. V Q18 zadavatel potvrdil společný návrh. První etapu vymezuje [implementační specifikace](specs/0001-native-ocr-environment.md); Windows a UI integrace následují později.

Pro nezávislé zpracování PDF čti [obecný OCR postup](ocr-workflow.md). Tento dokument uchovává požadavky a návrhy organizace projektu; prováděcí kroky jsou v obecném postupu.

## Potvrzené požadavky

- Vstupem je zdrojové PDF zadané pro konkrétní průchod.
- Později přibude více než sto PDF a následně další soubory.
- Hlavním cílem další práce je reprodukovatelné prostředí pro zpracování zpravodajů s přijatelným výsledkem a nízkou spotřebou tokenů. Vychází se z existujících nástrojů a vyzkoušeného workflow; nový technický prototyp není aktuálně požadován.
- Prioritou je kvalita OCR, návaznost článků a přirozené označování textu nad obrazem stránky a kopírování například do Wordu. Požadavek „archivní kvalita“ sám o sobě nevyžaduje konkrétní PDF standard.
- Špatně čitelné znění se má nejprve rekonstruovat z obrazu a kontextu. Zejména u jmen a čísel může následovat hledání odpovídajícího údaje na internetu. Při neúspěchu má vzniknout vhodný placeholder a místo pro doplnění zadavatelem.
- Výchozí neviditelná vrstva používá generované fonty se znakovými buňkami a Unicode mapováním konstrukce F podle `docs/ocr-f-construction.md`. Správnost znění, geometrie a chování nového PDF mají vlastní kontroly.
- Nový cíl podle upřesnění Q15 je rozšířit `pdf-ocr-reviewer` o OCR a komunikaci s Codexem. Každé PDF tvoří projekt vydání; po jeho OCR může rovnou následovat ruční revize a zapracování oprav v téže aplikaci.
- Setup skills již je hotový; jeho opakování není předmětem práce.
- Čitelné chyby vydavatele se zachovávají a současně evidují odděleně s vysvětlením, proč jde o chybu. Evidenci není dovoleno zaměnit za tichou opravu textu. Evidují se chyby nalezené při OCR a rekonstrukci, nikoli systematické ověření všech čitelných jmen, dat a tvrzení; věcné chyby potřebují doklad a neprokázaná podezření se odliší.
- Výstupy zahrnou OCR PDF, samostatný text článků a pracovní data pro opakovatelné opravy. DOCX nyní není požadován.
- Rozpoznávání začne místním OCR a kontrolou dostupnými nástroji, bez zapojení nových placených služeb. To není požadavek na výhradně místní zpracování všemi nástroji. Hledání údajů na internetu zůstává součástí rekonstrukce.
- Kopírovaný odstavec má být plynulý: bez pevných konců tiskových řádků, s logickými odstavci a spojením slov rozdělených sazbou, ale se zachováním skutečných spojovníků. Současně má být možné vybrat nad skenem jen část slova, a zkopírovat přesně vybrané znaky. Splnění se ověřuje na konkrétním výstupu.
- Rozsah přepisu zahrnuje veškerý čitelný tištěný text včetně inzerce, hlaviček, tiráže, popisků a tabulek. Články se dokončují přes navazující sloupce; ostatní bloky jsou oddělené a tabulky zachovají vztah záhlaví a řádků. Dekorace bez textu se nepřepisují.
- Běžná slova lze rekonstruovat při silné opoře v kontextu a zaznamenat důvod. Nejednoznačná jména, čísla a data bez odpovídajícího dokladu dostanou `[NEČITELNÉ]`; evidence váže místo na stránku, výřez a případné kandidáty. Každou takovou rekonstrukci není nutné předem potvrzovat.
- Při nevyřešených místech se pokračuje dalšími PDF. Zadavateli se předávají souhrny po vydáních; dotčená vydání čekají na doplnění a nejsou dokončená, dokud se odpovědi nezapracují. Podle pozdějšího upřesnění Q15 se ruční revize konkrétního vydání může spustit hned po jeho OCR.
- PDF jsou určena široké veřejnosti, nikoli jedné konkrétní čtečce zadavatele. Kopírování pokračování článku přes další stránky je relevantní, byť takové články jsou podle zadavatele vzácné.
- Zkouška skutečného výběru a schránky je podle aktuálního `ocr-workflow.md` volitelná a její neprovedení neblokuje dokončení OCR. Při zvolené zkoušce je počítačová kontrola podrobná a na Androidu/iOS základní; rozsah a konkrétní prostředí se evidují. Stav `not_tested` nepotvrzuje kompatibilitu čtečky. Automatické technické a geometrické kontroly zůstávají povinné.
- Samostatný text dokončí každý článek přes navazující sloupce a stránky. Články řadí podle místa začátku: stránky vzestupně, v běžné sloupcové sazbě zleva doprava. Nadpis přes více sloupců patří článku; inzeráty, popisky a tabulky jsou oddělené bloky. PDF zachovává původní stránkování.
- Celý postup byl podle zadavatele vyzkoušen v prototypu a je zachycen v `docs/ocr-workflow.md`. Z tohoto postupu vychází příprava opakovaného zpracování dalších PDF; prováděcí kroky se v tomto návrhu neduplikují.
- Zadavatel může ručně ověřit Acrobat. Word byl příklad následného využití kopírovaného textu, nikoli požadavek na otevírání PDF ve Wordu nebo povinné ověření tímto programem. Kontroly mají primárně porovnávat přesné znění schránky a výběr nad skenem.

## Strom rozhodnutí

První kolo je uzavřeno:

1. **Rozhodnuto:** zachovat obraz skenu a opravovat neviditelnou textovou vrstvu; narovnání je přípustné. Rozsah dalších obrazových zásahů tím schválen nebyl. Viz ADR 0001.
2. **Rozhodnuto:** zachovat chyby vydavatele a odděleně je evidovat s vysvětlením. Viz ADR 0002.
3. **Rozhodnuto:** OCR PDF, text článků a pracovní data; bez DOCX.
4. **Rozhodnuto:** místní OCR a dostupné nástroje, bez nových placených služeb.

Druhé kolo — rozhodnutí a otevřená technická otázka:

5. **Požadavek rozhodnut:** přirozené odstavce i výběr části slova. Aktuální konstrukci a povinné kontroly vymezuje vyzkoušený `docs/ocr-workflow.md`; skutečná schránka čteček je volitelná podle aktualizace Q13–Q14. Univerzální kompatibilita se neslibuje bez doložených testů.
6. **Rozhodnuto:** všechny čitelné tištěné texty, včetně tabulek a inzerce.
7. **Rozhodnuto:** silně podložená rekonstrukce s evidencí; jinak `[NEČITELNÉ]` a záznam místa.
8. **Rozhodnuto:** pokračovat dávkou, souhrny po vydáních; čekající vydání dokončit až po zapracování doplnění.
9. **Rozhodnuto:** veřejné použití; sadu čteček má navrhnout agent. Rozsah mobilního ověření je rozhodnutý v Q11.
10. **Rozhodnuto:** evidence chyb nalezených při OCR a rekonstrukci, nikoli úplné ověření věcných tvrzení.

Třetí kolo je uzavřeno:

11. **Rozhodnuto:** při zvolené UI zkoušce podrobná počítačová kontrola a základní Android/iOS; přesnost dotykového výběru neblokuje dokončení. Samotná UI zkouška je podle pozdějšího rozhodnutí Q14 volitelná.
12. **Rozhodnuto:** samostatný text po souvislých článcích, včetně pokračování přes stránky. Články se řadí podle místa začátku. PDF zachovává původní stránkování.

Čtvrté kolo je uzavřeno:

13. **Uzavřeno zadavatelem:** celé workflow bylo vyzkoušeno v prototypu; postup je v `docs/ocr-workflow.md`. Následuje příprava reprodukovatelného zpracování, nikoli nový návrhový experiment.
14. **Uzavřeno zadavatelem:** odpověď vyplývá z workflow Q13. Skutečná zkouška schránky je volitelná, neprovedení neblokuje OCR a nedokládá UI kompatibilitu. Zadavatel může případně ověřit Acrobat; Word není povinné prostředí.

Společný návrh produkčního prostředí, adresářů, evidence a hranice integrace revieweru byl potvrzen v Q18. Rozsah první etapy určuje implementační specifikace. Povinné kontroly a význam stavů výstupu určuje aktuální `docs/ocr-workflow.md` a `docs/ocr-data-contracts.md`.

## Rozhraní revieweru

Ověřeno čtením aktuálního kódu a dokumentace, bez spuštění integračního testu:

- Soubor `pdf-ocr-reviewer.manifest.json` se ukládá průběžně ve vybrané složce. Při aktuálním průzkumu 13. 10. 2026 má manifest `schema_version=2`, instrukce oprav `repair_instructions.version=7` a externího vykonavatele oprav. Před implementací oprav znovu ověřit aktuální smlouvu.
- Reviewer prochází PDF přímo ve zvolené složce, nerekurzivně, a nerozlišuje zdroje od výsledků. Záznamy dokumentů klíčuje přesným názvem PDF.
- `ocr_sha256` kotví konkrétní obsah výsledného PDF. `source_sha256` připomínky je při jejím vytvoření také hash otevřeného OCR PDF, nikoli hash zdrojového skenu.
- `page_index` začíná nulou. `bbox` používá PDF body od levého horního rohu zobrazené stránky po ořezu a rotaci (`displayed_page_points_top_left`). Zachytí se rozměry stránky i její rotace.
- Zadání opravy je v `note`; aktuální reviewer navíc přijímá `replacement_text` pro doplnění `[NEČITELNÉ]`. `text` a `targets` popisují vybraný současný OCR text. Přesnou aktuální strukturu připomínky ověřit při implementaci oprav.
- Změna geometrie naruší vazbu připomínek. Změna textové vrstvy mění hash; pozdější opravný průchod musí bezpečně aktualizovat kotvy a historii, nikoli jen přepsat PDF a JSON.
- Automatické nalezení zdrojového PDF a souborů `-qa2.md` a `-qa3.md` očekává sousední soubory. Oddělené zdroje vyžadují řešení relativních `resources`; jeho úplnou funkčnost ověří pozdější integrační test.

Podklady: `../pdf-ocr-reviewer/app/manifest.py`, `app/review.py`, `app/api.py`, `app/folder_scanner.py`, `app/pdf_document.py`, `docs/region-review.md` (cesty po první jsou relativní ke kořeni projektu revieweru).

### Pořadí čtení a kopírování — podklady pro ověření

PDF může ukládat text v jiném pořadí, než naznačuje jeho poloha. Pouhé řazení všech řádků podle souřadnic neřeší vícesloupcové články; jejich hranice je potřeba určit samostatně. Viz [PyMuPDF: Text](https://pymupdf.readthedocs.io/en/latest/recipes-text.html) a [PyMuPDF: FAQ](https://pymupdf.readthedocs.io/en/latest/faq/index.html).

Tagovaná struktura může vyjádřit pořadí i návaznosti odstavců; Adobe popisuje její použití pro reflow. Z toho pro projekt vyvozujeme, že tagování může pomoci, ale jeho přítomnost sama nedokládá správný výběr myší a obsah schránky. Viz [PDF Association: přístupnost a strojově čitelný text](https://pdfa.org/understanding-pdf-accessibility-techniques/) a [Adobe: reflow](https://helpx.adobe.com/acrobat/using/reading-pdfs-reflow-accessibility-features.html).

`ActualText` umí vyjádřit náhradní znění úseku, ale není vhodné spoléhat na něj jako na jediný nosič českého textu a spojení dělených slov. Pro skeny se doporučují neviditelné textové objekty odpovídající skutečným textům; podporu konkrétními prohlížeči musí ověřit samostatný průchod. Viz [Tagged PDF Best Practice Guide, §5.5.3](https://pdfa.org/wp-content/uploads/2023/07/Tagged-PDF-Best-Practice-Guide.pdf) a [PDF.js: issue podpory ActualText](https://github.com/mozilla/pdf.js/issues/12237).

Jednotný font v neviditelné vrstvě je reálný: Tesseract/PyMuPDF používá `GlyphLessFont`. Kvalita geometrie výběru je samostatná vlastnost, kterou font automaticky nezaručuje. Viz [PyMuPDF: OCR](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html).

Návrh ověření ověřovacího průchodu: porovnat přesný kopírovaný text s potvrzenými vzorky pro diakritiku, jména, čísla, nadpis, část slova, odstavec, dělené slovo a vícesloupcový článek. Pro veřejné použití doporučujeme hlavní sadu Acrobat Reader, Chrome, Edge a Firefox, doplňkově Preview/Safari a Okular podle dostupnosti zařízení; mobilní kontrola je základní podle Q11. Plynulost odstavce ověřit v textu schránky a vložením do běžného textového cíle, bez pevných tiskových konců řádků. Word je pouze možný příklad cíle. Celé články přes více stránek ověřit v samostatném textovém exportu i v PDF podle skutečné čtečky. Automatická extrakce není náhradou kontroly výběru a schránky. Podrobnosti a zdroje: `docs/pdf-copy-compatibility.md`.

## Potvrzená cílová adresářová struktura

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

Struktura odděluje zdrojové vstupy od výsledků tak, aby reviewer nenabízel původní skeny jako dokumenty k opravě. Pravidla identity a verzí určuje specifikace; konkrétní zápis identifikátorů se stanoví při implementaci. Produkční adresářová struktura zatím nebyla provedena; současné prototypové podklady se zachovají.

## Doporučení k pozdější revizi

Smlouva s reviewerem zahrnuje stabilní názvy výsledků, vlastní evidenci hashů zdrojů i výsledků, opravitelné pracovní přepisy a geometrii. Narovnání je třeba dokončit před ruční kontrolou. Nový cílový rozsah Q15 zahrnuje také spouštění OCR z aplikace a následné zapracování revizí; podrobný návrh je v [propojení revieweru a OCR](reviewer-ocr-integration.md). Manifest revieweru nenahrazuje interní stav OCR ani seznam nevyřešených míst.

## Potvrzený směr workflow

Následující přehled rozvádí přijaté požadavky včetně pozdější integrace aplikace. První etapu vymezuje specifikace; provádění OCR a existující datová schémata určuje ověřené `docs/ocr-workflow.md`.

1. Zdrojová PDF uložit do `input/` a zachovat bez změny obsahu; názvy dosavadních souborů není třeba měnit. Další PDF bude zadavatel přidávat do `input/`.
2. Každé vydání evidovat podle stabilního názvu a hashe zdroje. Stejný obsah znovu nezpracovávat bez důvodu; jiný obsah se stejným názvem nesmí potichu přepsat dosavadní zdroj nebo výsledek. Nové nebo změněné vstupy odlišit od již dokončených vydání.
3. Pracovní data v `work/<identifikátor>/` uchovají zdrojovou a výslednou verzi, strukturu článků a odstavců, rozpoznaný text, polohy slov a znaků, vazbu spojených slov na tiskové řádky a případný převod geometrie po narovnání. Konkrétní datové schéma určí a ověří ověřovací průchod; data musí umožnit lokální opravu bez ztráty ostatních potvrzených oprav.
4. Místní OCR vytvoří první přepis a geometrii. Následuje kontrola všech stránek a textových bloků agentem, oprava pořadí článků, rekonstrukce obtížných pasáží a cílené dohledání údajů. Číselná jistota OCR sama o sobě nerozhoduje o správnosti. Poškozené okraje nelze „opravit“ pouhým zvýšením renderovacího DPI.
5. Pro nevyřešená místa, doložené rekonstrukce a chyby vydavatele vést odlišné záznamy s místem ve zdroji. Rekonstrukce má důvod a případný externí doklad; vydavatelská chyba původní znění a vysvětlení; nevyřešené místo výřez, kontext a kandidáty. Předávání souhrnů po vydáních umožní zapracování odpovědí bez přerušení ostatních dokumentů.
6. Narovnání provádět jen podle potřeby, bez ztráty obsahu stránky, a dokončit před ruční kontrolou. Viditelný obraz nepřestavovat. Použít konkrétní konstrukci F podle `docs/ocr-f-construction.md`; změna fontu, metrik nebo umístění vrstvy vyžaduje nové ověření malých výběrů i kopírování odstavců. Font sám není důkazem správnosti výběru znaků.
7. Vytvořit `output/pdf/<původní-název>-ocr.pdf` a `output/text/<původní-název>.txt` v UTF-8. Text obsahuje souvislé články a skutečné odstavce; tabulkový text zachová členění na řádky a sloupce. PDF a textový export vycházejí ze stejného potvrzeného přepisu. Vlastní evidence a reporty zůstávají oddělené od manifestu revieweru.
8. Pro každé PDF provést kontroly podle vyzkoušeného workflow: úplné první vizuální čtení, techniku, geometrii, automatické výběrové vzorky a textový export. Skutečná schránka je volitelná a její výsledek se eviduje odděleně.
9. Další vydání zpracovávat po obnovitelných krocích. Přerušení nesmí ztratit potvrzené opravy. Stav čekající na doplnění, technická chyba, ověřené povinné kontroly a přijetí zadavatelem se odliší podle workflow. Agent v rámci autonomie kontroluje každou stránku; nejde o požadavek, aby zadavatel ručně porovnával všechny stránky už před reviewerem.
10. Aplikace nabídne ruční revizi po OCR jednotlivého projektu vydání. Opravy se předají stejnému OCR modulu, vznikne nová ověřená iterace a bezpečně se aktualizují revizní kotvy. Stabilní názvy, verze a historie propojují oba kroky. Podrobnou implementaci upravuje návrh `docs/reviewer-ocr-integration.md`; manifest nevytvářet předem jako náhradu skutečných ručních připomínek.

Bez nových placených služeb a bez požadavku na konkrétní PDF archivní standard. Výkonnostní optimalizace a výběr knihoven se podřizují kvalitě prokázané ověřovacím průchodem; nevytváří se obecný OCR produkt ani nový reviewer.

## Reprodukovatelné prostředí a úspora tokenů — potvrzený směr

### Ověřený současný stav

- Existuje projektové `.venv` s Pythonem 3.14.7; instalované verze odpovídají sedmi přesným pinům v `requirements.txt`.
- `doctor` ověřuje dostupnost a zaznamenává prostředí. Systémové nástroje nejsou uzamčené; zaznamenané verze se neporovnávají se závaznou očekávanou sadou. Český model nemá kontrolovaný hash.
- Místní OCR má cache navázanou na obraz, příkaz, verzi Tesseractu a výstupy. Hash jazykového modelu v klíči chybí.
- `prepare` zatím nelze explicitně obnovit po přerušení: manifest vzniká před OCR a opakovaný příkaz s manifestem se odmítne.
- CLI pracuje s jedním zdrojem a jedním pracovním adresářem. Dávkový seznam a plán pokračování pro složku vydání zatím nejsou implementované.
- Docker klient a daemon jsou na tomto stroji dostupné. Kontejnerové prostředí projektu zatím neexistuje.

Zjištěno čtením aktuální implementace a kontrolou lokálních verzí; tento návrhový průchod nespouštěl OCR ani testy. Existující uživatelské změny `tools/`, `tests/` a prováděcích dokumentů se zachovávají.

### Navržený rozsah další implementace

1. Zafixovat výpočetní prostředí: Python, knihovny, Tesseract, český model, qpdf, Poppler a oba použité fonty. Volba obalu prostředí je Q15. Nestačí uzamknout pouze Python knihovny; prostředí má evidovat i hashe modelů a fontů a odmítnout neodsouhlasenou změnu verze.
2. Doplnit bezpečné pokračování přerušeného `prepare` a zahrnout model do identity OCR cache. Každý dokončený krok se ověřuje z jeho vstupů a výstupů; nezměněné podklady se znovu nevytvářejí.
3. Připravit jednoduchou evidenci dávky pro `input/`, pracovní adresáře v `work/` a ploché výsledky v `output/pdf/` a `output/text/`. Evidovat hash zdroje, krok, stav kontroly a otevřená místa. Nové soubory lze přidávat a pokračovat od konkrétního vydání.
4. Agent pracuje vždy s konkrétním vydáním a omezeným výřezem strukturovaných dat. Strojové kroky, validaci, zápis JSON a souhrny zajišťuje CLI. Potvrzený přepis, historie a vizuální záznam jsou na disku; nepřenášejí se opakovaně celé do kontextu.
5. Úplné první čtení všech textových bloků zůstává podle ověřeného workflow. U dalších oprav se načítají dotčené řádky a jejich okolí; technické kontroly se opakují podle závislostí exportu. Úsporu nesmí tvořit nepravdivé označení kandidátů za přečtené a potvrzené.
6. Předat stručný souhrn stavu a pouze otevřené problémy s odkazy na výřezy. Rozsáhlé rastry, OCR kandidáty, přepis, diagnostika a doslovné výsledky zůstávají soubory. Skutečné tokeny se měří jen tam, kde je prostředí poskytuje; délka souhrnu ani počet nálezů nejsou měřením tokenů.
7. Ověřit instalaci a běh z čistého prostředí na malých syntetických datech, přerušený/obnovený běh, invalidaci cache po změně modelu a zachování oprav. Návrh nevyžaduje další obsahový prototyp nebo opakování celého již zpracovaného zpravodaje.

Strojové prostředí zajišťuje opakovatelné výpočty; vizuální čtení a rekonstrukce agentem jsou samostatnou částí pracovního postupu. Způsob propojení s Codexem a ručními opravami vymezuje [návrh společné aplikace](reviewer-ocr-integration.md); přihlašovací režim a konkrétní verze se ověří před implementací.

### Q15: nativní OCR v rozšířeném revieweru

Zadavatel upřesnil cíl: aplikace načte složku PDF, každé PDF vede jako samostatný projekt vydání, spouští OCR včetně komunikace s Codexem a dovoluje bezprostřední ruční revizi i finální opravu. Původní návrh samostatného kontejnerového OCR pracoviště tedy není doporučenou cílovou architekturou.

Pro tento cíl doporučujeme nativní běh bez Dockeru, samostatný OCR proces v aplikačním balíku a verzovanou sadu nástrojů, modelů a fontů. `.venv` slouží vývoji; uživatelský balík musí obsahovat potřebné nativní závislosti. Návrh UI, rozhraní OCR, integrace Codex app-server a obnovy jednotlivých projektů je v [reviewer-ocr-integration.md](reviewer-ocr-integration.md).

Aktuální reviewer se balí PyInstallerem pro Linux x86_64 a Windows x86_64; dnes vlastní OCR ani opravy PDF neprovádí. Jeho CLI dovoluje kontrolovaný zápis manifestu. Současné `check --reviewer-root` v OCR navíc importuje zdrojový Python modul revieweru, nikoli jeho binárku; test skutečné distribuované aplikace musí být samostatně doložen.

**Q16 rozhodnuto:** nejprve Linux, následně Windows.

**Q17 rozhodnuto:** nejprve OCR prostředí, obnovení běhu a rozhraní procesu; rozšíření revieweru v navazující etapě.

**Q18 rozhodnuto:** společný návrh potvrzen, zadána příprava implementační specifikace.

Konkrétní souhrn první etapy je v [návrhu propojení](reviewer-ocr-integration.md#potvrzený-souhrn-první-etapy) a její kritéria ve [specifikaci](specs/0001-native-ocr-environment.md). Ověřené obsahové workflow se přebírá z `ocr-workflow.md`.
