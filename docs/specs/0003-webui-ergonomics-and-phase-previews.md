# Ergonomické GUI OCR, náhledy fází a automatický analytický záznam

Stav: implementační specifikace podle potvrzeného návrhu GUI1–GUI15. Zadavatel potvrdil společný návrh, výslovně odložil realizaci a následně zadal jeho převod do specifikace a publikaci. Testovací hranice níže samostatně potvrdil. Publikace sama nezahajuje implementaci.

Navazuje na [původní specifikaci WebUI a autonomního OCR, issue #9](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/9). Nové zadání rozvíjí existující aplikaci a její veřejné operace; nevytváří druhý nezávislý OCR systém.

## Problem Statement

Operátor považuje současné GUI za nepřehledné a neergonomické. Rozsáhlé panely nad pracovní plochou odsouvají projekty a výsledek práce; jednotlivé fáze jsou nahromaděné pod sebou. Cesty musí zadávat ručně. Model a reasoning jsou součástí profilu, ale nelze je pohodlně upravit v globálním ani projektovém nastavení.

Operátor potřebuje na konkrétní stránce zjistit, v jaké fázi vznikla chyba geometrie. Samotné konečné PDF neukazuje původní přepis a geometrii před automatickými opravami. Přepínání fází musí porovnávat skutečně zachované výsledky, nikoli různé pohledy na stejné nejnovější soubory.

Současně potřebuje rozumět tomu, co každá fáze provádí, co běží místně a co přes AI, jaké prompty se použily a jaká byla časová, výpočetní a tokenová náročnost. Celý proces chce trvale zaznamenat a na konci automaticky získat srozumitelné podklady pro analýzu a optimalizace pomocí Codexu.

Ruční opravy a konečná kontrola znění a plynutí textu mají později využít existující opravovací program. Tento redesign má připravit jejich místo v rozhraní, nikoli předčasně vytvořit náhradní editor.

## Solution

Přeuspořádat existující nativní WebUI podle layoutu ai-asr-sub-maker: ovládání aplikace vlevo nahoře, projekty vydání v levém panelu, vlastní nastavení u projektu a globální nastavení vlevo dole. Jedno zdrojové PDF se zobrazí jako jeden projekt vydání. Má-li dva a více průchodů OCR, objeví se jako rozbalitelné podřízené položky vybírané jedním kliknutím.

Hlavní plocha poskytne horizontální záložky: **Příprava → Přepis → Pořadí a geometrie → Sestavení a kontroly → Ruční revize → Výstupy**. Celá automatická část se spouští jedním hlavním tlačítkem. Záložky slouží především ke sledování a porozumění procesu.

Vpravo bude velký náhled zdrojového skenu nebo kontrolního PDF s geometrií a textem, jakmile je pro fázi dostupný. Vlevo od něj bude stručný popis činnosti, stav, průběh a rozbalitelné technické podrobnosti. Přepnutí fáze zachová stránku a přiblížení. Přepis a geometrie zobrazí své zachované původní výsledky; Sestavení a kontroly zobrazí aktuální nebo konečné PDF po automatických opravách.

Klikací výběr cest, globální a projektové předvolby modelu/reasoningu a úplná historie odstraní nutnost ručního hledání pracovních souborů. Na konci běhu automaticky vznikne přehled v Markdownu a úplné strukturované analytické podklady pro Codex. Ruční revize a Výstupy zatím zůstanou srozumitelnými placeholdery.

## User Stories

1. Jako operátor chci ovládání aplikace vlevo nahoře, abych je našel bez procházení pracovních panelů.
2. Jako operátor chci seznam projektů vydání trvale vlevo, abych mohl rychle přepínat mezi PDF.
3. Jako operátor chci každé zdrojové PDF v seznamu pouze jednou, abych si průchody nespletl s různými vydáními.
4. Jako operátor chci u PDF se dvěma a více průchody rozbalitelné podsekce, abych viděl související varianty pohromadě.
5. Jako operátor chci vybrat konkrétní průchod jedním kliknutím, abych se snadno dostal k jeho výsledkům.
6. Jako operátor chci jednoduché zobrazení PDF s jediným průchodem, abych nemusel zbytečně procházet další úroveň.
7. Jako operátor chci jasně poznat vybrané vydání a průchod, abych nezaměnil jejich data.
8. Jako operátor chci zachovat přístup ke starším průchodům, abych mohl porovnat výsledky a náročnost.
9. Jako operátor chci nastavení konkrétního PDF otevřít u jeho položky, abych věděl, kterého projektu se změna týká.
10. Jako operátor chci globální nastavení vlevo dole, abych jej odlišil od nastavení projektu.
11. Jako operátor chci vybrat složku evidence kliknutím, abych nemusel opisovat cestu.
12. Jako operátor chci vybrat vstupní PDF kliknutím, abych mohl pohodlně přidat jeden zdrojový sken.
13. Jako operátor chci vybrat vstupní složku kliknutím, abych mohl použít existující import více PDF.
14. Jako operátor chci vybrat soubor profilu odpovídajícím dialogem, abych se vyhnul chybám v cestě.
15. Jako operátor chci, aby zrušení výběrového dialogu ponechalo dosavadní hodnotu, abych nepoškodil rozpracované nastavení.
16. Jako operátor chci nadále zadat nebo upravit cestu ručně, abych mohl použít již známé umístění.
17. Jako operátor chci, aby cesty s mezerami a diakritikou fungovaly, abych nemusel přejmenovávat svoje složky.
18. Jako operátor chci nastavit globální model a reasoning, abych určil předvolby nových projektů vydání.
19. Jako operátor chci vlastní model a reasoning pro konkrétní PDF, abych přizpůsobil další zpracování jeho obtížnosti.
20. Jako operátor chci společnou výchozí dvojici model/reasoning, abych nemusel nastavovat každou AI činnost samostatně.
21. Jako operátor chci rozbalitelné výjimky pro jednotlivé AI kroky, abych mohl cíleně měnit jejich kvalitu a náročnost.
22. Jako operátor chci při založení projektu kopii globálních předvoleb, abych měl předvídatelný výchozí stav.
23. Jako operátor chci zachovat vlastní nastavení existujícího projektu při změně globálu, abych nepřekvapivě nezměnil jeho další běh.
24. Jako operátor chci výslovně převzít globální hodnoty do vybraného projektu, abych je mohl sjednotit záměrně.
25. Jako operátor chci přesné použité nastavení zmrazené u průchodu, abych mohl později vysvětlit jeho výsledek.
26. Jako operátor chci změněné projektové předvolby použít pro další průchod, abych nepřepsal nastavení již zahájené práce.
27. Jako operátor chci poznat nedostupnou kombinaci modelu a reasoningu, abych nespustil jinou variantu bez svého vědomí.
28. Jako operátor chci horizontální logické záložky, abych se orientoval podle postupu OCR.
29. Jako operátor chci automatickou část spustit jedním tlačítkem, abych nemusel ručně spouštět každou fázi.
30. Jako operátor chci přepínat záložky bez změny běžícího zpracování, abych mohl průběžně prohlížet výsledky.
31. Jako operátor chci u každé fáze stručné vysvětlení její činnosti, abych rozuměl tomu, co přidává nebo mění.
32. Jako operátor chci vidět stav a právě probíhající práci, abych rozlišil čekání, aktivitu a chybu.
33. Jako operátor chci rozlišit místní a AI kroky, abych správně posoudil jejich nároky.
34. Jako operátor chci hlavní prostor věnovat náhledu stránky, abych mohl pohodlně kontrolovat geometrii.
35. Jako operátor chci měnit poměr šířky náhledu a detailu, abych rozhraní přizpůsobil obrazovce.
36. Jako operátor chci náhled zvětšit, abych mohl prohlédnout malé nebo problematické oblasti.
37. Jako operátor chci při přepnutí fáze zachovat stránku a přiblížení, abych sledoval stejné místo.
38. Jako operátor chci v Přípravě vidět sken a dostupné pomocné oblasti místního OCR, abych posoudil jeho vstupní podklady.
39. Jako operátor chci v Přepisu vidět jeho původní text a oblasti, abych poznal stav před navazujícím zpracováním.
40. Jako operátor chci v Pořadí a geometrii vidět umístění a logické pořadí textu, abych rozpoznal chyby této fáze.
41. Jako operátor chci zobrazit text v překryvu automaticky, jakmile existuje, abych jej nemusel zvlášť zapínat.
42. Jako operátor chci v Sestavení a kontrolách vidět skutečné vytvořené PDF a textovou vrstvu, abych posoudil reálný výstup.
43. Jako operátor chci zachovat náhled prvního dokončení přepisu, abych jej mohl odlišit od pozdějších oprav.
44. Jako operátor chci zachovat geometrii před automatickými opravami, abych zjistil, co se následně změnilo.
45. Jako operátor chci aktuální nebo konečný výsledek oprav v Sestavení a kontrolách, abych viděl jejich dopad.
46. Jako operátor chci náhled vždy přiřazený k vybranému průchodu a fázi, abych nehodnotil cizí nebo pozdější podklady.
47. Jako operátor chci správně umístěné překryvy i na otočených a oříznutých stránkách, abych chybu zobrazení nezaměnil za chybu OCR.
48. Jako operátor chci srozumitelně označené dosud nevytvořené nebo chybějící podklady, abych neviděl falešný historický výsledek.
49. Jako operátor chci Ruční revizi jako připravené místo pro existující opravovací program, abych měl přehled o budoucím pokračování práce.
50. Jako operátor chci Výstupy zatím jako placeholder navazující na ruční část, abych automatický výsledek nezaměnil za ručně dokončené vydání.
51. Jako operátor chci automatické kontroly a opravy odlišit od ruční revize, abych chápal hranice automatizace.
52. Jako operátor chci vidět místní nástroje a jejich skutečné parametry, abych zjistil, co konkrétně se spouštělo.
53. Jako operátor chci čas a stav každého místního kroku, abych našel pomalé nebo selhávající operace.
54. Jako operátor chci místní spotřebu CPU a maximum RAM po krocích, abych vyhodnotil výpočetní nároky.
55. Jako operátor chci u AI kroku skutečně použité nastavení, abych ověřil respektování předvoleb a výjimek.
56. Jako operátor chci úplné odeslané prompty, abych mohl analyzovat a optimalizovat zadání.
57. Jako operátor chci dostupné odpovědi a činnost nástrojů, abych porozuměl výsledku AI kroku.
58. Jako operátor chci tokeny oddělené na necachovaný vstup, cachovaný vstup a výstup, abych rozuměl skladbě spotřeby.
59. Jako operátor chci spotřebu opakovaných a přerušených pokusů v historii, abych nepodhodnotil náročnost.
60. Jako operátor chci chybějící metriky odlišit od nul, abych nevyvozoval nesprávné závěry.
61. Jako operátor chci historii spojenou s projektem, průchodem, fází a pokusem, abych dohledal příčiny rozdílů.
62. Jako operátor chci průběžné ukládání záznamu celého procesu, abych neztratil podklady při chybě nebo ukončení.
63. Jako operátor chci zachovat historii po restartu aplikace, abych analýzu nemusel dokončit během běhu.
64. Jako operátor chci automatický analytický export na konci celého běhu, abych jej nemusel ručně vyvolávat.
65. Jako operátor chci srozumitelný Markdown přehled pro Codex, abych mohl snadno zadat následnou analýzu.
66. Jako operátor chci úplné strukturované události a metriky vedle přehledu, abych mohl provádět přesná porovnání.
67. Jako operátor chci odkazy z přehledu na prompty, odpovědi a podklady fází, abych načítal podrobnosti podle potřeby.
68. Jako operátor chci v exportu chyby, opravné cykly a neúplnost běhu, abych mohl analyzovat i neúspěšné zpracování.
69. Jako operátor chci vytvořit analytický přehled z uložených dat bez dalšího AI běhu, abych nepřidával spotřebu kvůli samotnému reportování.
70. Jako operátor chci po zavření okna ponechat práci na pozadí, abych nemusel mít rozhraní stále otevřené.
71. Jako operátor chci znovu otevřít pohled na běžící aplikaci, abych mohl pokračovat ve sledování.
72. Jako operátor chci při vypnutí volbu dokončit běžící krok a potom skončit, abych uchoval jeho ověřený výsledek.
73. Jako operátor chci možnost okamžitě zastavit práci, abych mohl zpracování ukončit bez čekání.
74. Jako operátor chci při zastavení informaci o bodu pokračování, abych věděl, která práce zůstává platná.
75. Jako operátor chci zachovat existující frontu, obnovu a porovnávání průchodů, abych redesignem nepřišel o hotové schopnosti aplikace.

## Implementation Decisions

### Aplikační hranice a kompatibilita

- Rozšířit současnou aplikační službu a veřejné požadavky, dotazy a události, které používá GUI. Tato hranice zůstává hlavní integrační hranicí také pro testy. Nezavádět vedle ní druhou nezávislou orchestraci.
- Rozšíření se týká prezentace workflow, projektových a globálních předvoleb, prohlížení podkladů fází, měření místních prostředků, životního cyklu okna a analytického exportu.
- Zachovat existující procesové OCR rozhraní, registry, jedno aktivní zpracování a frontu, pokračování, porovnávání průchodů, atomické zápisy, identity podkladů a ochranu před souběžným zápisem.
- Respektovat ADR 0001 (zachovaný obraz skenu), ADR 0002 (věrné znění a oddělené chyby vydavatele), ADR 0003 (samostatný nativní OCR proces) a ADR 0004 (Codex app-server). Nový layout tyto hranice nemění.
- Zachovat podporu dosud požadované a ověřované kombinace gpt-6.1-sol/high a context-mode. Výběr dalších skutečně dostupných modelů neruší dosavadní integrační podmínky.

### Layout, výběr a soubory

- Levý panel obsahuje ovládání aplikace nahoře, projekty vydání, nastavení jednotlivých projektů a globální nastavení dole. Hlavní plocha začíná hlavičkou vybraného průchodu a horizontálními záložkami.
- Identita projektu vydání vychází ze zdrojového PDF, nikoli jen z jeho názvu. Průchody jsou podřízené témuž vydání. Při dvou a více průchodech jsou rozbalitelné a přímo vybíratelné; jeden průchod nevynucuje zbytečnou další úroveň.
- Import, výběr průchodu a čtení historie zachovávají starší data. Samotné zobrazení nemění jejich validační stav ani přijetí zadavatelem.
- Výběrový dialog odpovídá účelu: složka evidence, jedno vstupní PDF, vstupní složka nebo soubor profilu; totéž platí pro další zobrazovaná pole pro soubory, například manifest prostředí. Ruční zadání cesty může zůstat.
- Desktopový adaptér zajišťuje klikací výběr cest. Zrušení nemění dosavadní hodnotu; neplatný typ nebo nedostupné umístění má srozumitelnou chybu. Zachovat cesty s mezerami a diakritikou.
- Dlouhé operace neblokují obsluhu UI. Náhled, výběr projektu ani změna záložky samy nespouštějí OCR nebo AI.

### Globální a projektové předvolby

- Globální předvolby a vlastní nastavení projektu vydání jsou trvalé a jednoznačně označené rozsahem. Při založení projektu se globální hodnoty zkopírují; nejde o živé dědění.
- Existující projekt nabízí výslovné převzetí současných globálních hodnot. Samotná změna globálu jeho nastavení nepřepíše.
- Na globální i projektové úrovni existuje společný model/reasoning a rozbalitelné výjimky pro jednotlivé AI činnosti. Výjimka má přednost před společnou dvojicí daného projektu.
- Při založení průchodu se uloží přesně vyhodnocené nastavení včetně výjimek, parametrů a skutečně použitých promptů. Další úpravy globálu, projektu nebo externího profilu již zahájený průchod nemění; pokračování používá jeho zmrazené podmínky.
- Zachovat výběr a prohlížení externích profilů. Model/reasoning jsou nově editovatelné z GUI, plný editor promptů zůstává mimo rozsah. Účinné parametry pro nový průchod musí být před spuštěním srozumitelné.
- Všechny AI cesty skutečně použijí účinné nastavení, včetně čtení, geometrie, kontroly a oprav. Odstranit současné vynucování pevného modelu/reasoningu v některých cestách; nestačí změnit pouze zobrazený profil.
- Nabídky vycházejí z dostupných schopností runtime a poskytovatele, ne z příkladu jiného programu. Nepodporovaná uložená hodnota musí zůstat vysvětlitelná; nedostupná kombinace se nesmí tiše nahradit jinou.

### Fáze a odpovědnost uživatele

- Záložky jsou přesně Příprava, Přepis, Pořadí a geometrie, Sestavení a kontroly, Ruční revize a Výstupy.
- Příprava zahrnuje místní podklady a potřebná ověření prostředí/modelu; Přepis vizuální čtení a rekonstrukci; Pořadí a geometrie návaznost článků a umístění textu; Sestavení a kontroly export, AI a místní kontroly a cílené automatické opravy.
- Automatický postup se nadále spouští jednou hlavní akcí. Záložky nezavádějí povinný ruční wizard a nepředstavují samostatné spuštění fáze při otevření.
- Detail fáze vysvětlí její účel, vstupy/výsledek, stav, průběh a místní/AI činnost. Technické podrobnosti jsou dostupné bez zahlcení hlavní plochy.
- Zachovat nejvýše tři následné cílené opravné cykly a dosavadní důvody jejich dřívějšího ukončení. Přítomnost nevyřešeného místa není totéž co technické selhání a dokončený export není potvrzení správnosti přepisu.
- Ruční revize i Výstupy jsou nyní placeholdery budoucí logiky existujícího opravovacího programu. Automatické kontrolní PDF je k dispozici přímo v Sestavení a kontrolách.

### Náhledy, překryvy a historické stavy

- Pravá část pracovní plochy zobrazuje náhled, levá stručný detail fáze. Uživatel může posouvat dělicí příčku a náhled zvětšit. Přepnutí fáze zachová aktuální stránku a přiblížení.
- Náhled používá zdrojový sken před sestavením PDF a skutečné vytvořené PDF v Sestavení a kontrolách. Podklad může být vykreslený raster, pokud pravdivě reprezentuje odpovídající stránku.
- Geometrie a dostupný text se zobrazují společně. Text se objeví automaticky, jakmile jej fáze má; jeho zobrazení se nepodmiňuje dalším přepínačem. V Přípravě musí být pomocné místní OCR odlišitelné od pozdějšího přepisu.
- Přepis zobrazuje zachovaný výsledek svého prvního dokončení. Pořadí a geometrie zobrazují výsledek před následnými automatickými opravami. Sestavení a kontroly zobrazují aktuální nebo konečný export včetně oprav.
- Zavést jednoznačnou vazbu náhledu na zdroj, průchod, fázi, stránku a zachovaný podklad. Pozdější oprava nesmí přepsat náhled původní fáze. Dosavadní bohaté exportní a opravné archivy využít a doplnit chybějící zachování mezivýsledků, zejména geometrie.
- U starších dat se chybějící historický stav výslovně označí; nepoužít za něj nejnovější soubory ani automaticky znovu spouštět AI. Nedokončená fáze ukazuje svůj stav a pouze skutečně dostupné podklady.
- Souřadnice místních OCR podkladů jsou pixely původního rastru, zatímco náhled PDF pracuje s rozměry zobrazené stránky. Převod musí zohlednit DPI, rozměry, ořez, rotaci, přiblížení a rozdílné číslování/indexování stránek.
- Rozlišovat pomocnou nebo aproximovanou geometrii od skutečné výsledné textové vrstvy. Vykreslený rámeček sám neprokazuje správnost přepisu nebo identity znaku.
- Nepřidávat samostatný inspektor, který po kliknutí na řádek otevírá přepis a nálezy. Hlavním účelem této části je vizuální geometrická diagnostika; podrobné posuzování znění a plynutí textu patří do ruční revize.
- Další samostatný prohlížeč historie všech opravných iterací není součástí tohoto redesignu. Zachování původních dokladů oprav tím není omezeno.

### Činnost, prostředky, prompty a tokeny

- Každý krok je trvale přiřazen k projektu vydání, průchodu, fázi a pokusu. U AI se zachovává dostupná identita vlákna/tahu a původní události potřebné k vysvětlení spotřeby.
- U místních kroků evidovat nástroj a jeho dostupnou verzi, skutečné parametry, vstupy/výstupy, stav, časy, chyby, spotřebu CPU a špičkovou paměť RAM. Pokrytí se týká celého místního procesu včetně exportů, segmentace a validací, nikoli jen přípravy.
- Měření místních prostředků má uvedené jednotky a rozsah, zejména započtení potomků procesu. U CPU odlišit procesový čas od doby běhu a čekání. U RAM nevydávat součet individuálních maxim za současnou špičku celého kroku.
- U AI zpřístupnit celý aplikací odeslaný prompt a podklady, použité nastavení, dostupnou odpověď, činnost nástrojů, trvání a spotřebu. Souhrn může být krátký, ale úplný uložený originál musí být dostupný.
- Zachovat původní prompty a účinný profil; netvrdit, že aplikace zná neveřejný interní kontext poskytovatele. Místní CPU/RAM neprezentovat jako výpočetní prostředky poskytovatele AI.
- Zachovat dosavadní auditovatelné tokenové účetnictví: necachovaný vstup, cachovaný vstup a výstup; reasoning nepřičítat k výstupu podruhé. Duplicitní/kumulativní události nesmějí navyšovat spotřebu a opožděné události zůstávají přiřazené původnímu pokusu.
- Zachovat přerušené a opakované pokusy. Místní cache není cache AI tokenů. Nedostupné nebo neúplné měření je výslovně označené, nikoli nula.
- Zachovat dohledatelné podklady dosavadního srovnávacího odhadu ceny a jeho odlišení od skutečného účtování předplatného.
- Historie se zapisuje průběžně a přežije restart. Protokoly nadále respektují stávající redakci přihlašovacích údajů.

### Automatický analytický export

- Na konci celého průchodu vznikne automaticky analytický balík bez exportního tlačítka a bez dodatečného AI běhu.
- Hlavním vstupem je srozumitelný Markdown přehled pro Codex. Popíše zdrojové vydání, identitu průchodu a prostředí, použité nastavení, účel a skutečnou činnost fází, výsledek, časy, místní prostředky, tokeny, chyby, opravné cykly a chybějící údaje.
- Vedle přehledu zachovat úplné strukturované metriky a události JSON/JSONL a manifest podkladů. Přehled obsahuje relativní odkazy na úplné prompty, dostupné odpovědi, výsledky a zachované náhledy fází.
- Vstupní přehled zůstane stručný a odkáže na podrobnosti podle potřeby; velké protokoly se nekopírují celé do jednoho Markdown dokumentu.
- Manifest jednoznačně sváže podklady s průchodem a stavem fází. Automatický balík nesmí odkazovat na později přepsaný výsledek jako na původní stav.
- Export vznikne při dokončení i při ukončení chybou nebo přerušením a pravdivě rozliší tyto stavy. Pozastavení pouze zachová průběžný záznam, protože průchod bude pokračovat.
- Při obnovení stejného průchodu lze analytický přehled obnovit z jeho trvalých událostí bez opakování dokončených OCR/AI kroků. Opakované sestavení přehledu nesmí duplikovat události nebo spotřebu.
- Vytvoření přehledu a jeho případná chyba se nesmějí zaměnit za kvalitu OCR výsledku. Výsledné PDF a původní události zůstávají zachované i při selhání reportování.

### Životní cyklus aplikace

- Rozlišit zavření okna a výslovné vypnutí aplikace. Zavření okna ponechá běžící práci na pozadí a uživatel může znovu otevřít její rozhraní.
- Nabídka ovládání aplikace vlevo nahoře zpřístupní odpovídající otevření rozhraní, restart a vypnutí. Restart respektuje pravidla zachování práce a historie.
- Při výslovném vypnutí během práce nabídnout dokončení rozpracované ověřitelné jednotky s následným vypnutím nebo okamžité přerušení se zachováním platných výsledků.
- Před pokračováním po přerušení se ověří uložený stav a uživatel dostane pravdivou informaci o bodu obnovy. Nepřislibovat pokračování uvnitř neověřeného AI kroku.
- Dosavadní pozastavení/přerušení/obnova autonomního průchodu a fronty zůstávají základem. Desktopový adaptér musí přestat automaticky rušit práci jen kvůli zavření pohledu.

## Testing Decisions

- Zadavatel potvrdil hlavní hranici: stávající veřejné operace, dotazy a události používané GUI. Přes ně ověřovat celé uživatelské scénáře a uložené výsledky; skutečné rozhraní, náhledy a desktopové výběrové dialogy doplnit integrační kontrolou.
- Testy hodnotí vnější chování, nikoli interní strukturu komponent, konkrétní selektory CSS, pořadí pomocných funkcí nebo kopii implementačního výpočtu. Nevytvářet nové samostatné testovací rozhraní pro každý modul.
- Navázat na existující integrační testy projektů vydání, seskupování průchodů, profilů, fronty, geometrie, autonomního exportu, cílených oprav, metrik a obnovy. Ty používají dočasnou evidenci, veřejné požadavky, řízené procesy a řízeného partnera app-serveru; část provádí skutečnou místní práci s PDF.
- Hlavní scénář zahrne dvě vydání a dva průchody jednoho PDF, rozdílné globální/projektové předvolby, výjimku AI fáze, opravu výsledku a restart aplikace. Ověří výběr správného průchodu, zmrazené nastavení, původní náhledy fází a aktuální opravené PDF.
- Testy nastavení ověří kopii globálu při založení, nezávislost existujícího projektu, výslovné převzetí globálu, trvalost po restartu a skutečné předání účinného modelu/reasoningu do všech AI cest. Nedostupný model nesmí vyvolat tichou náhradu.
- Testy cest ověří výběr odpovídajícího typu, zrušení bez změny hodnoty, neplatnou cestu a mezery/diakritiku. Klikací desktopový dialog se ověří na podporovaném Linux prostředí; samotná náhrada dialogu v testu není důkazem funkčního systémového výběru.
- Náhledy ověřovat na malém syntetickém PDF s nezávisle známými polohami, alespoň více stránkami, ořezem a rotací. Očekávané pozice odvodit z předlohy, nikoli převzít z testované geometrie.
- Integrační kontrola UI ověří rozložení, horizontální záložky, rozbalení průchodů, změnu poměru ploch, zvětšení náhledu a zachování stránky/přiblížení. Dostupný text musí být vidět bez dalšího zapnutí. Přepínání náhledu nesmí spustit práci.
- Test cílené opravy ověří, že původní Přepis a Pořadí a geometrie zůstávají beze změny, zatímco kontrolní PDF odráží opravu. Chybějící historický podklad se nesmí tiše nahradit novějším.
- Testy místních prostředků ověří přiřazení ke kroku, uvedený rozsah a jednotky, měření potomků a zachování neúplnosti při přerušení; nepoužívat přesné hodnoty výkonu závislé na stroji jako křehké očekávání.
- Testy AI metrik zachovají dosavadní deduplikaci, přiřazení opožděných událostí, přerušené pokusy, rozlišení neznámé/nulové hodnoty a reasoning bez dvojího započtení. Ověřit dostupnost celého dlouhého promptu, nejen zkráceného náhledu.
- Automatický analytický export ověřit po úspěchu, chybě a přerušení, bez stisknutí dalšího tlačítka. Odkazy a manifest musí vést k odpovídajícím uloženým podkladům, Markdown musí vysvětlit stav a strukturovaná data odpovídat trvalým událostem.
- Ověřit, že pozastavení nezavře pokračovatelný průchod jako dokončený, opakované sestavení přehledu neduplikuje spotřebu a reportování nevyvolá další AI požadavek.
- Životní cyklus ověřit přes veřejné řízení a skutečný desktopový adaptér: zavření okna ponechá práci běžet, opětovné otevření obnoví pohled a výslovné vypnutí respektuje volbu doběhnout/přerušit. Dosavadní obnova a fronta zůstávají funkční.
- Ruční revize a Výstupy musí být zřetelně placeholdery; nesmějí předstírat hotové ruční schválení nebo spouštět neexistující opravovací logiku.
- Řízený AI partner prokazuje kontrakt a účetnictví, nikoli skutečnou dostupnost modelu. Zachovat dosavadní povinné integrační doklady runtime/modelu/context-mode při přijetí měněných AI cest.

## Out of Scope

- Zahájení implementace v rámci převodu rozhovoru do specifikace nebo samotnou publikací issue.
- Integrace plné ruční opravovací logiky, editace znění, doplňování nevyřešených míst a konečného schvalování vydání.
- Implementace finálního workflow záložky Výstupy navazujícího na ruční revizi.
- Samostatný inspektor přepisu po kliknutí na řádek a nový prohlížeč všech historických opravných iterací.
- Kompletní editor promptů v GUI; zůstává jejich prohlížení a dosavadní externí správa.
- Nový poskytovatel AI nebo jiný způsob účtování pouze proto, že jej podporuje inspirační aplikace.
- Nahrazení ověřeného OCR postupu, změna požadavku věrného přepisu, přepisování zdrojového skenu nebo oslabení stávajících kontrol kvality.
- Nové multiplatformní distribuční závazky, změna jedné aktivní úlohy na paralelní OCR a přepis celé aplikace na jiný framework.
- Další AI běh vytvářející analytický report, ruční exportní tlačítko a automatická optimalizace promptů/modelů. Export je podkladem pro pozdější analýzu a rozhodnutí.
- Zjišťování neveřejného interního kontextu nebo hardwarové spotřeby poskytovatele AI.

## Further Notes

- Návrh byl potvrzen v GUI15. Následný pokyn zadavatele výslovně požaduje nerealizovat a čekat na další instrukce. Aktuální zadání autorizuje syntézu a publikaci této specifikace; samotný štítek ready-for-agent nenahrazuje pokyn zahájit implementaci.
- Testovací hranice popsané výše zadavatel samostatně potvrdil během přípravy specifikace.
- Tato specifikace mění tři dřívější volby původního zadání: odklad vloženého náhledu do revieweru se ruší pro diagnostické náhledy; omezení GUI na prohlížení profilů se rozšiřuje o model/reasoning; zavření okna se odděluje od vypnutí procesu.
- Ostatní pravidla původní specifikace zůstávají v platnosti. Jde zejména o samostatný nativní OCR proces, věrné znění, zachování zdroje, izolaci průchodů, auditovatelnou historii, omezené opravné cykly, frontu a pravdivé validační stavy.
- Již existují rastry a OCR podklady, přepis s oblastmi řádků, geometrie, archivy opravných/exportních stavů, prompty, původní události a tokenový ledger. Chybí jednotné historické náhledy fází, vložený prohlížeč, plné pokrytí místních metrik, CPU/RAM a automatický analytický balík. Tyto mezery jsou součástí realizace, nikoli důkazem hotové funkce.
- Při implementaci zachovat existující nesouvisející lokální změny a nevydávat samotný nový layout za splnění OCR integračních podmínek.
