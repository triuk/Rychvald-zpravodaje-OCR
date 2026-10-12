# Technická konstrukce F pro OCR

Tento dokument popisuje obecný mechanismus neviditelné textové vrstvy. Obsah, geometrie a testová očekávání se získávají ze zdrojového PDF konkrétního průchodu. Implementace je [tools/ocr_f_layer.py](../tools/ocr_f_layer.py); před použitím přečti její vstupní smlouvu.

## Font a znakové buňky

Pro každý výskyt znaku vytvoř samostatný obdélníkový glyph. Font má 1000 jednotek na em, ascent 1000 a descent -1; cap height a x-height 1000. Šířka glyphu vychází z příslušné nové výběrové buňky. Buňku v rasterových souřadnicích převeď podle zaznamenaného DPI na PDF body. Obdélník je neviditelný díky režimu `3 Tr`; jeho tvar představuje výběrovou buňku, nikoli měřený obrys inkoustu.

Pomocné fontové kódy jednotlivých výskytů mapuj přes `ToUnicode` na skutečné UTF-16BE znění. Zachovej českou diakritiku, ostatní tištěné znaky a skutečné mezery. ReportLab font dělí na subsety; mapování zkontroluj v každém subsetu. Generátor rozděluje zásobníky po nejvýše 6000 buňkách a ověřuje počet přemapovaných záznamů.

Referenční výška fontu je výška buňky dělená `1.001`; dolní posun je `0.001` velikosti fontu. Pro těsně sousedící stejný znak generátor při stanovené blízkosti koncových poloh zdvojnásobí svislé fontové metriky a úměrně zmenší velikost fontu. Efektivní výška, šířka buňky a Unicode zůstávají zachovány. Vhodnost této pojistky se ověřuje vlastní extrakcí opakovaných znaků.

## Textové objekty a spojení řádků

Celou logickou jednotku zapiš jedním `BT … ET`, i při pokračování do dalšího sloupce na téže stránce. Znaky uvnitř zapisuj v logickém pořadí a polohu každého určuj nad tiskem. Nevkládej konce tiskových řádků do Unicode. Pro pokračování přes stránku zachovej návaznost v pracovních datech a TXT; PDF objekty jsou stránkové a chování konkrétní čtečky má vlastní test.

Každá hranice fyzických řádků má vlastní ověřený druh spojení: běžná mezera, odstranění sazbového spojovníku, zachování skutečného spojovníku bez mezery nebo přímé spojení částí téže jednotky. Poslední možnost pokrývá například samostatná písmena vertikálního nápisu. Rozhodnutí neváž na pevné ID řádku či konkrétní slovo. Mezerná buňka představuje skutečnou logickou mezeru; není mostem nataženým přes stránku.

ReportLab před každou stranou nastavuje preambuli `1 0 0 1 0 0 cm`, aby nepřidal další prázdný textový objekt. Ověř počet `BT`, tagů a logických jednotek v samotném textovém Formu.

## Vrstva, obraz a tagy

Importuj textovou stranu jako Form XObject nad původní obraz. Původní obsahové streamy zůstávají zachované a jsou obaleny `Artifact BMC … EMC`. Logické jednotky mají H1/H2/P a MCID. Strukturální prvek odkazuje přes `/MCR` na `/Pg`, `/Stm` textového Formu a `/MCID`. `StructParents` patří Formu, ParentTree přiřazuje MCID ke strukturálním prvkům. Strany mají `/Tabs /S`; katalog `StructTreeRoot`, `MarkInfo` a `Lang (cs-CZ)`.

Vrstva nepoužívá `ActualText`, změnu šířky běžného fontu přes `Tz` ani mezerné mosty. Ověření jedné z těchto vlastností nenahrazuje kontrolu celého mechanismu.

## Použití generátoru

`create_pdf(pages, source_path, output_path, work_dir=..., raster_dpi=300)` přijímá pouze nově vytvořená data. `pages` je seznam v pořadí stran zdroje; každá položka má `page` (od 1) a `units`. Jednotka má `tag` (H1/H2/P) a `lines`; řádek má `cells`. Buňka má `text` a `selection_bbox` jako `[x0, y0, x1, y1]` od levého horního rohu rastru při `raster_dpi`. Všechny strany daného volání používají toto DPI.

Každý řádek kromě posledního v jednotce musí uvést `join_after`: `space`, `typesetting_hyphen`, `literal_hyphen` nebo `none`. Sazbový spojovník je v poslední buňce řádku a generátor jej odstraní; skutečný spojovník ponechá a spojí bez mezery. `none` spojuje přímo. Generátor doplní `unit.pdf_text`; PDF i TXT mají použít tento společný logický text. Pomocné tabulkové oddělovače TXT nepatří mezi tištěné buňky PDF.

`work_dir` určuje pracovní složku aktuálního běhu. Zde vznikají pomocné fonty a vrstva. V buňkách s minimální šířkou, u úpravy opakovaných znaků a na hranicích spojení ukládá generátor diagnostiku do `construction-events.json`. Knihovny: PyMuPDF, ReportLab a fontTools. Použij dostupné prostředí, zaznamenej verze a ověř výsledek; kód není OCR ani kontrola správnosti vstupu.

Dokončeno, když nový výstup prošel kontrolou znaků dvěma extraktory, zachováním obrazu a struktury, cílenými výběry podle nového rastru a vlastním testem schránky v dostupných čtečkách. Nedostupné UI operace a neúspěšné malé výřezy zůstávají v reportu samostatně viditelné.
