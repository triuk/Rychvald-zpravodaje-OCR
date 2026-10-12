# Výběr části slova a kopírování plynulých odstavců

Pro nezávislé zpracování použij [obecný OCR postup](ocr-workflow.md) a [technický mechanismus F](ocr-f-construction.md). Tento dokument uchovává metodiku kompatibility; výsledek konkrétního PDF musí mít vlastní kontroly.

## Odpověď na požadavek

Požadavky na přesný výběr části slova nad skenem a na plynulý kopírovaný odstavec se významově nevylučují. Zatím však není prokázáno, že je jeden výsledný PDF soubor splní současně ve všech běžných čtečkách. Výběr znaků lze podpořit jejich správným textovým kódováním a geometrií; sestavení schránkového textu z tiskových řádků zároveň ovlivňuje čtečka. Není správné slíbit veřejnou kompatibilitu jen na základě správného přepisu nebo přítomnosti tagů.

Samostatný schválený textový výstup může mít plynulé odstavce bez závislosti na PDF čtečce. Je to doprovodný výstup; sám o sobě nesplňuje požadavek na výběr a kopírování přímo nad skenem.

## Ověření konkrétního výstupu

Očekávané znění a hranice výběru se určují ze zdrojového rastru. Správnost jednotlivých znaků, jejich geometrie a kopírovaných odstavců se musí doložit vlastním experimentem; samotná přítomnost textové vrstvy nestačí.

## Co mohou a nemohou zajistit PDF mechanismy

Pro skenované stránky doporučuje PDF Association neviditelné textové objekty odpovídající skutečné poloze textu. To podporuje návrh s přesnou znakovou geometrií; nevyžaduje to automaticky samostatný objekt pro každé písmeno. Viz [Tagged PDF Best Practice Guide, §5.5.3](https://pdfa.org/wp-content/uploads/2023/07/Tagged-PDF-Best-Practice-Guide.pdf).

Tagování umí popsat logické odstavce a jejich návaznost přes sloupce a stránky. Adobe dokumentuje použití této struktury při reflow. Reflow je však odlišná operace od běžného výběru myší a Ctrl+C; nelze z něj odvodit zaručené odstranění tiskových konců řádků ve schránce. Viz [Adobe: reflow](https://helpx.adobe.com/acrobat/using/reading-pdfs-reflow-accessibility-features.html) a [Reader: kopírování](https://helpx.adobe.com/reader/desktop/copy-content-pdfs.html).

`ActualText` je náhradní znění úseku, nikoli úplná mapa náhradních znaků na původní obraz. Aktuální PDFium při zpracování tohoto znění umí odvozovat náhradní znakové boxy rovnoměrným rozdělením šířky textového objektu. Z toho vyvozujeme, že náhrada celého odstavce není spolehlivý způsob, jak zároveň zajistit výběr přesně odpovídající konkrétním písmenům více tiskových řádků. PDF.js navíc eviduje problém podpory `ActualText`. Viz [PDFium: ProcessMarkedContent](https://pdfium.googlesource.com/pdfium/+/refs/heads/main/core/fpdftext/cpdf_textpage.cpp#997) a [PDF.js #12237](https://github.com/mozilla/pdf.js/issues/12237).

V aktuálním PDF.js textová vrstva při `hasEOL` vytváří HTML zalomení `<br>`. Obsluha Copy zapisuje normalizované `selection.toString()` a neobsahuje krok, který by automaticky spojoval tiskové řádky do odstavců; konce řádků může extraktor odvodit také z geometrie. Samotné vynechání znaků nového řádku v přepisu proto není zárukou plynulého clipboardu ve Firefoxu. Jde o závěr ze zdrojového kódu, nikoli již provedený test našeho budoucího PDF. Viz [text layer](https://github.com/mozilla/pdf.js/blob/master/src/display/text_layer.js), [copy handler](https://github.com/mozilla/pdf.js/blob/master/web/text_layer_builder.js) a [evaluator](https://github.com/mozilla/pdf.js/blob/master/src/core/evaluator.js).

## Navržené čtečky pro veřejné použití

Toto je sada k ověření, nikoli seznam již potvrzené kompatibility:

| Rozsah | Čtečky | Co ověřit |
|---|---|---|
| Hlavní počítačová sada | Adobe Acrobat Reader, vestavěné čtečky Chrome, Edge a Firefox | Přesný výběr znaků, slova, odstavce, článku a obsah schránky |
| Doplňkově macOS | Preview a Safari | Stejné vzorky podle dostupnosti zařízení |
| Doplňkově Linux | Okular | Stejné vzorky; Firefox již patří do hlavní sady |
| Android | Chrome a Acrobat Reader | Obraz, vyhledávání a základní kopírování; přesnost dotykového výběru několika znaků není podmínkou dokončení podle Q11 |
| iPhone/iPad | Safari a Acrobat Reader | Obraz, vyhledávání a základní kopírování; přesnost dotykového výběru několika znaků není podmínkou dokončení podle Q11 |

Výběr každé čtečky bude zaznamenán s verzí, systémem a konkrétní operací. Na mobilech je přesnost dotykových úchytů také vlastností uživatelského rozhraní. Dokumentace potvrzuje kopírování a dotykový výběr, nikoli záruku libovolné hranice písmena: [Chrome Android](https://support.google.com/chrome/answer/16215622?co=GENIE.Platform%3DAndroid&hl=en), [Preview na Macu](https://support.apple.com/en-ie/guide/preview/prvw1020/mac), [Okular](https://docs.kde.org/stable_kf6/en/okular/okular/menutools.html).

Dostupnost čteček zjisti pro konkrétní průchod. Test Chromia nelze uvádět jako test Chrome nebo Edge. Zadavatel podle Q14 může ručně ověřit Acrobat. Word je příklad následného použití textu, nikoli povinná čtečka nebo povinné testovací prostředí.

## Návrh kontrol kopírování

1. Vybrat vnitřní úsek nerozděleného slova podle právě zpracovávaného zdroje. Výběr i schránka musí obsahovat pouze požadované znaky; nesmí být vynucen výběr celého slova nebo odstavce.
2. Samostatně vybrat část slova rozděleného přes tiskový řádek a celé takové slovo. Ověřit vynechání sazbového spojovníku i zachování skutečných spojovníků.
3. Zkopírovat odstavec přes alespoň tři tiskové řádky a porovnat přesný prostý text schránky. Uvnitř odstavce nesmí zůstat pevné zlomy řádků; skutečné hranice odstavců se zachovají. Vložení do vhodného editoru pak umožní zalomení podle jeho šířky; Word je pouze možný příklad.
4. Zkopírovat vícesloupcový článek bez přimíchání sousedního článku a pokračování přes stránku. Rozlišit logické pořadí kompletní extrakce od schopnosti čtečky vybrat rozsah jedním tahem.
5. Ověřit českou diakritiku, nadpis, číslo, jméno, tabulkový řádek a dvě sousední odstavcové jednotky.
6. Pro každý vzorek zaznamenat přesný text schránky a výsledek v konkrétní čtečce. Automatická extrakce není náhradou této kontroly.

Než se spustí celá dávka, musí být dohodnuto, které výsledky jsou závazné a jak se postupuje při selhání některé čtečky. Zachování přesného výběru části slova nelze bez dohody obětovat trikům pro kopírování celého odstavce; stejně tak nelze doprovodný textový soubor vydávat za splnění všech požadavků na samotné PDF.
