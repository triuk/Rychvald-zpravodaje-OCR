# Redesign GUI OCR podle ai-asr-sub-maker

Stav: sjednocený návrh potvrzen v GUI15. Zadavatel výslovně odložil realizaci; následně zadal syntézu a publikaci specifikace. Program dosud nebyl změněn.
Datum: 28. 10. 2026.

## Zadání

Rozhraní vychází z layoutu místního programu ai-asr-sub-maker: ovládání aplikace vlevo nahoře, seznam projektů vydání vlevo, nastavení každého projektu přes jeho ovládací prvek, globální nastavení vlevo dole a horizontální logické záložky hlavní pracovní plochy.

Cesty mají klikací výběr. Podle účelu se vybírá složka evidence, vstupní PDF či složka PDF nebo soubor profilu. Ruční zadání cesty může zůstat jako další způsob.

Globální i projektové nastavení má editovatelné volby modelu a míry uvažování (reasoning).

## Potvrzená rozhodnutí

Čísla GUI1–GUI5 odpovídají prvnímu kolu tohoto rozhovoru; nejsou totožná s Q1–Q36 staršího návrhu.

### GUI2 — Globální předvolby

Nový projekt vydání dostane kopii globálních předvoleb. Existující projekt je nepřebírá průběžně. Projekt nabídne výslovné převzetí aktuálních globálních předvoleb.

Potvrzeno odpovědí „dle doporučení“. GUI6 následně uzavřelo původní GUI1: nový průchod přebírá předvolby projektu a uloží jejich přesnou účinnou podobu.

### GUI3 — Model a reasoning

Globální i projektové nastavení obsahují společnou výchozí dvojici model/reasoning a rozbalitelné výjimky pro jednotlivé AI kroky. Výsledná podoba použitá při spuštění patří k danému průchodu.

Potvrzeno odpovědí „dle doporučení“. Konkrétní členění kroků a jejich pojmenování bude navazovat na potvrzené záložky a skutečné fáze OCR.

### GUI4 — Členění workflow a hranice ruční revize

Rozpoznávání se člení do samostatných logických fází podle později potvrzeného GUI7.

Ruční kontrola a opravy budou zatím placeholder pro logiku existující aplikace na opravu OCR. Automatické kontroly a opravné cykly zůstávají součástí automatického OCR. Umístění automatických a budoucích ručních výstupů upřesňuje GUI8.

Potvrzeno vlastní odpovědí zadavatele k GUI4.

### GUI5 — Životní cyklus aplikace

Při vypnutí během práce nabídnout dokončení právě běžícího kroku s následným vypnutím, nebo okamžité zastavení s informací, odkud bude možné pokračovat. Zavření samotného okna může ponechat aplikaci pracovat na pozadí, jako v inspirační aplikaci.

Potvrzeno odpovědí „dle doporučení“. Skutečná hranice bezpečného dokončení a možnosti obnovy musí odpovídat dostupnému řízení běhu; neukládat příslib pokračování z neověřeného mezistavu.

Tato volba mění starší Q27, podle kterého zavření aplikace přerušovalo práci. Návrh bude muset výslovně rozlišit zavření okna a vypnutí aplikace.

### GUI6 — Projekty vydání a podřízené průchody

V levém panelu je každé zdrojové PDF jednou. Pokud má dva nebo více průchodů OCR, pod jeho rozbalitelnou položkou se zobrazí podřízené průchody. Každý lze vybrat jedním kliknutím. Ozubené kolečko projektu vydání upravuje předvolby dalších průchodů; již zahájené průchody uchovávají své skutečně použité nastavení.

Zadavatel potvrdil GUI6 a výslovně požádal o rozbalovací podsekce. Tím se uzavírá původní GUI1. Běžná práce s jediným průchodem nevyžaduje rozbalovat další úroveň.

### GUI7 — Záložky a vizuální diagnostika

Potvrzené hlavní záložky: Příprava → Přepis → Pořadí a geometrie → Sestavení a kontroly → Ruční revize → Výstupy.

Celé automatické zpracování lze spustit jedním hlavním tlačítkem; záložky zpřístupňují jednotlivé fáze. U každé relevantní fáze má být náhled PDF nebo zdrojového skenu s překryvnými vrstvami, který umožní vizuálně určit, ve které fázi vznikla chyba. Jde o diagnostické zobrazení; ruční opravovací logika zůstává odložená podle GUI4/GUI8.

Náhled musí odlišit podklady konkrétního průchodu a fáze od pozdějšího výsledku. Konkrétní vrstvy, ovládání a míru historického uchování dále upřesňují potvrzené GUI9–GUI12 níže.

### GUI8 — Kontrolní PDF a odložené výstupy

Automaticky sestavené kontrolní PDF se zobrazí přímo v záložce Sestavení a kontroly. Samostatná záložka Výstupy bude zatím placeholder pro budoucí logiku navazující na ruční revizi, stejně jako samotná Ruční revize. Tato odpověď nahrazuje návrh zobrazovat nynější PDF/TXT v samostatné záložce Výstupy.

### GUI9 — Uspořádání pracovní plochy

Náhled bude vpravo, se změnitelnou šířkou a možností zvětšení. Vlevo od něj bude stručný detail aktuální fáze. Přepnutí fáze zachová stránku a přiblížení. Zadavatel potvrdil návrh a upozornil, že fáze běží automaticky: detail proto znamená stav, průběh a případné chyby, nikoli nutnost ručně spouštět každý krok.

### GUI10 — Geometrie jako hlavní předmět diagnostiky

Překryvné vrstvy zobrazují geometrii a text přímo v ní automaticky, jakmile je pro danou fázi dostupný. Text není volitelná vrstva; zadavatel výslovně opravil původní výklad. Přepis již text obsahuje, navazující geometrie řeší jeho umístění a pořadí. Smyslem náhledu je především kontrola umístění textu. Podrobná kontrola samotného znění a jeho plynutí patří do závěrečné ruční revize. Zamítnut je návrh stavět rozhraní na klikání do řádků a otevírání přepisu/nálezů v samostatném detailu. Takový inspektor se nyní nepřidává.

### GUI11 — Stav fáze místo samostatného procházení verzí

Zadavatel chce stav před a po změně sledovat prostřednictvím jednotlivých fází; samostatný prohlížeč historie opravných iterací nebyl odsouhlasen. Každá fáze proto potřebuje odpovídající zachovaný podklad pro náhled. Upřesnění GUI12 bylo potvrzeno odpovědí „dle doporučení“: Přepis ukazuje výsledek prvního dokončení přepisu; Pořadí a geometrie ukazuje geometrii před následnými automatickými opravami; Sestavení a kontroly ukazuje aktuální/konečné PDF včetně automatických oprav. Pozdější opravný cyklus nesmí zpětně změnit náhled původních fází.

### Průběh, nároky a trvalý analytický záznam

Zadavatel požaduje přehled toho, co přesně každá fáze provádí, včetně rozlišení místních a AI kroků. U místního kroku bude vidět, co běží; u AI skutečně aplikací sestavené zadání a dostupná spotřeba tokenů. Celý proces se trvale loguje pro pozdější analýzu a optimalizace. Historie musí zůstat dostupná i po dokončení průchodu a restartu aplikace a být přiřaditelná k projektu, průchodu, fázi a pokusu.

Tento požadavek potvrzuje dosavadní Q22/Q24/Q30 a specifikaci 0002: místní/AI práce, prompty, doby, odpovědi a nástroje, návaznosti vstupů/výstupů, tři kategorie tokenů a srovnávací odhad ceny s původem sazeb. Neznámé či neúplné hodnoty se nesmějí zobrazovat jako nuly. Výstupní tokeny již obsahují reasoning; nepřičítat jej znovu. Přesný interní kontext poskytovatele není totéž jako aplikací sestavené zadání a nelze jej slibovat.

Rozsah měření místních prostředků a automatický analytický export byly následně potvrzeny v GUI13/GUI14 níže.

Ověřený výchozí stav logování: existují původní požadavky/události app-serveru v protocol.jsonl, úplná zadání v request.json, kopie profilů a strojově čitelný ledger s cenovými podklady. Současný detail GUI zkracuje dlouhé prompty/odpovědi; návrh musí zpřístupnit úplné originály. Místní metriky nyní pokrývají především přípravu, takže je nutné doplnit přiřazení místních exportů, validací, segmentace a kontrol k jejich fázím a dobu jednotlivých kroků. Dosud není odběr CPU/RAM ani hotový přenosný export z GUI. Všechny fáze musí také skutečně respektovat zvolený model/reasoning; některé současné vizuální AI cesty je mají pevně určené, což bude nutné upravit v souladu s GUI3.

### GUI13 — Místní CPU a RAM

Zadavatel potvrdil měření místního procesoru a maximální obsazené RAM po jednotlivých místních krocích nad rámec již zaznamenávaného času, nástrojů a parametrů. Měření má umožnit hledat úzká místa a porovnávat optimalizace. Údaje se vážou na konkrétní krok a průchod; nedostupná měření zůstávají výslovně nedostupná.

### GUI14 — Automatický analytický export pro Codex

Export vznikne automaticky na konci celého běhu, nikoli na vyžádání tlačítkem. Zadavatel výslovně žádá formát snadno čitelný a srozumitelný pro Codex.

Konkrétní podoba potvrzená ve sjednoceném návrhu GUI15: adresář analysis u průchodu s hlavním vstupním souborem README.md, úplnými strukturovanými metrikami a událostmi JSON/JSONL, manifestem podkladů a relativními odkazy na úplné prompty, odpovědi a výsledky fází. Markdown stručně vysvětlí vstupní PDF, použité nastavení, výsledek běhu, účel a činnost jednotlivých fází, místní nástroje, AI model/reasoning, časy, CPU/RAM, tokeny a chybějící údaje. Zahrne chyby, opravné cykly a odkazy na zachované náhledy. Velké protokoly se nebudou kopírovat celé do vstupního přehledu.

Živý log se ukládá průběžně; závěrečný export jej shrne při dokončení i při ukončení chybou nebo přerušením a pravdivě označí stav a neúplnost. Pozastavení pouze zachová průběžný záznam, protože běh bude moci pokračovat. Přehled se sestaví z uložených dat bez dalšího AI běhu.

## Závěrečné potvrzení

Věcné návrhové otázky jsou uzavřené. V GUI15 zadavatel potvrdil společné porozumění celému návrhu včetně konkrétní podoby automatického analytického exportu a výslovně zadal nerealizovat a čekat na další instrukce.

Následně vyvolal to-spec. Sjednocený návrh byl převeden do [implementační specifikace 0003](../specs/0003-webui-ergonomics-and-phase-previews.md) a publikován jako [issue #24](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/24) se štítkem ready-for-agent. Testovací hranice stávajících veřejných operací používaných GUI s doplňující integrační kontrolou skutečného rozhraní zadavatel samostatně potvrdil. Publikace ani štítek nejsou pokynem zahájit implementaci.

Po schválení rozpadu to-tickets bylo publikováno 14 úkolů #25–#38; jejich skutečná čísla, názvy a blokující vazby uvádí [přehled úkolů](webui-ocr-gui-tickets.md). Rodičovské issue #24 se při jejich publikaci neměnilo. [Předání na další počítač](../../README.md) popisuje větev a podklady pro pokračování přes GitHub.

## Ověřené souvislosti

Slovník již rozlišuje Projekt vydání (jedno zdrojové PDF a jeho životní cyklus) a Průchod OCR (jedno konkrétní zpracování s vlastními parametry a historií). Nové termíny zatím nevznikly.

Dosavadní Q29 ve webui-ocr-gui.md a specifikace 0002 předpokládaly externí správu profilů a jejich výběr/prohlížení v GUI. Nově požadované editory modelu/reasoning tento rozsah mění. Po závěrečném potvrzení se odpovídající části specifikace sjednotí; plný editor promptů zatím nebyl požadován.

Požadavek GUI7 také mění starší Q32, které odkládalo vložený PDF náhled do integrace s reviewerem. Nově bude diagnostický náhled součástí této úpravy; odklad ručních oprav nadále platí.

Starší Q25 pojmenovává milníky: příprava → vizuální přepis a rekonstrukce → pořadí článků a geometrie → export → kontroly a opravy → předání k revizi. Q28/Q32 již ponechávají ruční opravy revieweru.

Zmrazený profil zahájeného průchodu a zachování jeho historie jsou dosavadní pravidla programu. Rozpracovaná možnost úpravy modelu/reasoning je nesmí zpětně přepsat.

Ověření skutečných fází: příprava → diagnostika modelu a context-mode → čtení → pořadí/geometrie → export → AI kontrola výstupu → místní validace → cílené automatické opravy. Opravné cykly obnovují geometrii, export a kontroly; výsledky stejného průchodu se tedy vyvíjejí v archivovaných exportních iteracích. Zmrazené je použité nastavení, nikoli celý rozpracovaný výsledek. Ruční revize je samostatná navazující činnost. Příprava, čtení, geometrie, kontrola i opravy mají vlastní veřejné operace; současná operace prvního exportu navazuje také kontrolami.

Současný profil má jednu společnou dvojici model/reasoning. Výjimky pro jednotlivé AI kroky podle GUI3 budou vyžadovat rozšíření profilu a jeho vyhodnocování. Pozastavení a pokračování existují pro autonomní průchod/frontu; stejné ovládání jednotlivě spuštěných fází a běh po zavření okna vyžadují doplnění řízení aplikace.

Pro náhledy už existují vstupní PDF a stránkové rastry, pomocné hOCR/TSV místního OCR, rozpoznané řádky se stabilními ID, čísly stránek a oblastmi v souřadnicích původního rastru, vazby článků na řádky, geometrie řádků/znaků, nálezy a kontrolní obrázky. UI zatím nabízí otevření zaznamenaných podkladů externě, nikoli vložený prohlížeč. Návrh vrstev musí rozlišit pomocné místní OCR, přepis a skutečnou výslednou textovou vrstvu.

Historie již uchovává předchozí review, první publikovaný přepis a bohaté snímky exportů a opravných cyklů. Neexistuje však univerzální katalog neměnných stavů všech fází; samostatná příprava geometrie může přegenerovat soubory se stejnými názvy. Historický náhled bude vyžadovat výslovnou vazbu na uložený stav a zobrazení nedostupných historických dat. Náhled minulé fáze nesmí použít aktuální vrstvy bez upozornění.

Souřadnice fází OCR jsou pixely původního rastru s číslováním stránek od 1. Reviewer používá body zobrazené stránky po zohlednění ořezu a otočení a index od 0. Přenos vrstev vyžaduje převod podle manifestu (DPI, rozměry rastru, rect/mediabox/cropbox/rotation). Geometrické buňky znaků jsou aproximace, nikoli samy o sobě potvrzení správné identity znaku.

Zjištěné původní lokální změny docs/webui-projects.md a neversionovaný start.sh se tímto návrhem neupravují.

## Podklady

- ../agents/domain.md
- ../../GLOSSARY.md
- webui-ocr-gui.md (zejména Q21, Q24–Q29, Q31–Q32)
- ../specs/0002-webui-ocr-orchestration.md
- ../adr/0003-native-ocr-process.md
- ../adr/0004-codex-app-server-pro-autonomni-ocr.md
- ../../ui/index.html a ../../ui/app.js
- ../../app/service.py
- Referenční projekt /home/gordon/Dokumenty/ai-asr-sub-maker a jeho ADR 0005.
