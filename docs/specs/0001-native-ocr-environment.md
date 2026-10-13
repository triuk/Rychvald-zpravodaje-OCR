# Reprodukovatelné nativní OCR prostředí pro projekty vydání — první etapa

Stav: implementační specifikace odvozená ze společného návrhu potvrzeného v Q18 dne 13. 10. 2026. První cílová platforma je Linux x86_64; Windows a rozšíření revieweru následují později.

## Problem Statement

Zadavatel chce opakovaně zpracovávat více než sto zdrojových PDF Rychvaldského zpravodaje a průběžně přidávat další. Ověřený OCR postup už existuje, ale zatím spoléhá na systémové programy, modely a fonty konkrétního počítače. Přerušení úvodní přípravy nelze bezpečně obnovit a samostatné pracovní adresáře nemají společnou evidenci projektů vydání.

Velké přepisy a opakované čtení nezměněných podkladů zvyšují spotřebu tokenů. Cílem je připravit obnovitelné prostředí a rozhraní procesu, které používá ověřené OCR, uchovává práci na disku a později půjde ovládat z revieweru. Úspora tokenů má vzniknout z práce s uloženými podklady a stručnými výstupy, při zachování úplného prvního vizuálního čtení a povinných kontrol.

## Solution

Vznikne nativní OCR pracoviště pro deklarované a skutečně otestované Linux prostředí. Jeho instalace či sestavení z jednoznačně určených vstupů zajistí ověřené Python knihovny, OCR programy, český model a fonty. Manifest verzí a hashů a kontrola prostředí rozpoznají odchylku před výpočtem. Běžný běh nebude vyžadovat Docker ani ruční dohledávání OCR závislostí.

Každé PDF bude samostatným projektem vydání s identitou zdroje, pracovními podklady, přepisem, historií, kontrolami a PDF/TXT výstupem. Proces dovolí zahájit a obnovit práci, zjistit stav a provést strukturovanou opravu. Dlouhé podklady zůstanou v souborech; běžný výsledek příkazu bude malý a strojově čitelný. Připravený kandidát, vizuálně potvrzený přepis, úspěšné kontroly a přijetí uživatelem budou odlišné skutečnosti.

První etapa připraví OCR proces pro navazující aplikaci. Reviewer ani vestavěná komunikace s Codexem se v této etapě nerozšiřují.

## User Stories

1. Jako správce OCR chci obnovit prostředí z verzovaných vstupů, abych nemusel znovu odhadovat funkční kombinaci závislostí.
2. Jako správce OCR chci používat nativní Linux prostředí bez Dockeru za běhu, abych připravil základ budoucí distribuované aplikace.
3. Jako správce OCR chci znát podporované Linux prostředí a jeho omezení, abych nepovažoval neotestovanou platformu za kompatibilní.
4. Jako správce OCR chci před OCR ověřit programy, knihovny, modely a fonty, abych včas zjistil chybějící nebo změněnou závislost.
5. Jako správce OCR chci mít původ a hashe potřebných prostředků, abych uměl obnovit stejnou sadu a vysvětlit změnu výsledku.
6. Jako operátor chci načíst zdrojová PDF ze složky, abych připravil jednotlivé projekty vydání pro pozdější dávku.
7. Jako operátor chci zachovat zdrojové PDF beze změny, abych měl předlohu pro kontrolu každé iterace.
8. Jako operátor chci stabilní identitu projektu vydání, abych správně přiřadil přepis, kontroly a výsledky.
9. Jako operátor chci rozpoznat již evidovaný obsah, abych nezakládal neúmyslně další průchod stejného vstupu.
10. Jako operátor chci rozlišit různé vstupy se stejným názvem, aby se zdroje a výsledky nepřepsaly.
11. Jako operátor chci zachovat pracovní data každého vydání odděleně, abych nepomíchal články a opravy různých PDF.
12. Jako operátor chci bezpečně pokračovat po přerušení přípravy, abych neztratil již dokončené rastry a OCR průchody.
13. Jako operátor chci poznat, které kroky jsou hotové a které čekají, abych mohl pokračovat bez opakovaného průzkumu celého pracovního adresáře.
14. Jako operátor chci při nezměněných podkladech použít cache, abych šetřil výpočty a opakovanou komunikaci s agentem.
15. Jako operátor chci rozpoznat změnu modelu i pod stejným názvem, abych nepoužil kandidáty vytvořené jiným OCR prostředím.
16. Jako operátor chci zjistit poškození nebo chybějící výsledek kroku, abych pokračoval jen z ověřených podkladů.
17. Jako operátor chci znovu zpracovat pouze potřebné kroky, abych kvůli lokální opravě neopakoval OCR všech stránek.
18. Jako agent chci získat stručný stav projektu a odkazy na podklady, abych nemusel načítat úplný přepis a diagnostiku.
19. Jako agent chci vyžádat jen potřebné stránky, řádky nebo nálezy, abych omezil kontext na aktuální úlohu.
20. Jako agent chci dávkově předávat strukturované opravy, abych nepřenášel celý přepis jako velký textový patch.
21. Jako operátor chci zachovat předchozí přepis při opravě, abych uměl dohledat změnu nebo se vrátit.
22. Jako operátor chci odmítnout neplatnou opravu před zápisem, aby rozpracovaný přepis zůstal použitelný.
23. Jako operátor chci uchovat přesné znění nevyřešených míst a doklady rekonstrukcí, abych mohl doplnit obtížná místa bez ztráty jejich kontextu.
24. Jako operátor chci pokračovat dalšími vydáními, když jedno čeká na doplnění, abych neblokoval celou složku.
25. Jako operátor chci PDF a souvislý text článků ze stejného potvrzeného přepisu, abych mohl výsledek vyhledávat, označovat a dále používat.
26. Jako operátor chci verzovat exporty a jejich kontroly, abych nepovažoval starý report za ověření nové iterace.
27. Jako operátor chci rozlišit technické selhání, připravený výsledek s otevřenými nálezy a ověřený rozsah kontrol, abych věděl, co lze předat.
28. Jako operátor chci skutečnou vizuální kontrolu evidovanou odděleně od automatické přípravy, aby proces neprohlašoval neprovedené čtení za hotové.
29. Jako operátor chci neprovedenou volitelnou zkoušku schránky vykázat pravdivě, aby neblokovala OCR ani nepředstírala UI kompatibilitu.
30. Jako budoucí autor revieweru chci ovládat stejný OCR proces přes stabilní rozhraní, abych neimplementoval OCR algoritmy znovu v aplikaci.
31. Jako budoucí autor revieweru chci dostávat stavy a výsledky v malých zprávách, abych mohl zobrazit průběh bez čtení velkých pracovních souborů.
32. Jako správce OCR chci ověřit čistou instalaci a obnovu na syntetickém skenu, abych reprodukovatelnost doložil spustitelným případem.
33. Jako správce OCR chci zachovat současné uživatelské změny a prototypové podklady, aby příprava prostředí nezničila ověřenou práci.

## Implementation Decisions

### Rozsah a výchozí stav

- Převzít aktuální ověřený postup, generátor neviditelné vrstvy F a datové smlouvy přepisu, geometrie a kontrol. Nerozpoznávat znovu skutečný zpravodaj pouze kvůli přípravě prostředí.
- První podporovaná platforma je Linux x86_64. Sestavení musí deklarovat skutečně ověřený systém a případné požadavky na systémové knihovny; nelze prohlašovat všechny Linux distribuce za podporované bez testu.
- První etapa poskytne nativní instalovatelnou/verzovanou sadu a OCR proces. Vývojové virtuální prostředí není samo o sobě výsledným uživatelským balíkem. Jeden spouštěč může používat přibalené pomocné programy a data.
- Použít současné pracovní soubory jako základ. Uživatelské změny nejsou určené k vrácení; implementace je rozvíjí, nikoli přepisuje starší vzdálenou kopií.

### Prostředí

- Připnout Python runtime, přímé i tranzitivní knihovny, Tesseract, český model, qpdf, Poppler a potřebné fonty. Zachovat ověřené verze, kde jsou dostupné; případnou nutnou změnu ověřit integračními kontrolami a zaznamenat.
- Uchovat jednoznačný manifest prostředí s verzí schématu, identitou sestavení, zdrojem jednotlivých prostředků a jejich ověřitelnými hashi. Instalace nebo sestavení nesmí používat neomezené „latest“ vstupy jako deklarovanou reprodukovatelnou sadu.
- Kontrola prostředí řeší chybějící prostředek, nesprávnou verzi a jiný obsah modelu či fontu. Odchylku od očekávané sady odmítne před OCR; změna očekávané sady musí být explicitní a dohledatelná.
- Běžný běh používá určené programy a prostředky nativního balíku, nikoli náhodnou shodu z uživatelova PATH. Cesty k programu a datům jsou konfigurovatelné bez editace OCR implementace.

### Projekt vydání a stav

- Evidenci celé složky tvoří registr projektů vydání; podrobné podklady zůstávají v pracovním prostoru konkrétního projektu. Registr neobsahuje celý přepis a nenahrazuje manifest ruční revize.
- Identita projektu váže nezměněný zdrojový obsah, jeho původní název a konkrétní průchod. Opakované načtení stejného vstupu vrací existující projekt; nový nezávislý průchod se zakládá explicitně. Jiný obsah se stejným názvem nesmí přepsat existující projekt nebo výstup.
- Zachovat členění na zdrojové vstupy, pracovní prostory a ploché PDF/TXT výstupy. Nové složky a registr přidat bez smazání prototypových podkladů. Existující práce se nepovýší na ověřenou jen jejím nalezením.
- Rozlišit fázi zpracování, stav právě běžící operace a výsledek obsahových/technických kontrol. Úspěšné vytvoření OCR kandidátů není potvrzený přepis ani přijetí vydání.
- Zachovat aktuální validační výsledky: `failed`/1, `ready_with_open_items`/2 a `verified`/0. Tyto kódy mají tento význam při validaci celého průchodu; úspěch jiného příkazu jej nesmí zaměnit za obsahové ověření.
- Zdrojová PDF se nemění. Starší výstupní iterace, potvrzené opravy a doklady nálezů se uchovají. Přijetí výsledku zadavatelem zůstává oddělené od stavu povinných kontrol.

### Pokračování a cache

- Zachovat rozlišení nového průchodu a explicitního pokračování. Přítomnost vstupního manifestu sama nesmí znemožnit bezpečné obnovení rozpracované úvodní přípravy.
- Ukládat průběžný stav po dokončených jednotkách práce: rastr stránky a jednotlivý kandidátní průchod. Po přerušení se ověří jejich identity a hashe a pokračuje jen nedokončenou nebo neplatnou prací.
- Identita OCR cache zahrnuje obraz/výřez, úplné parametry a jazyk, Tesseract, obsah použitých jazykových modelů a hashe kandidátních výstupů. Prostředky ovlivňující geometrii nebo export patří do identity příslušných následných kroků.
- Změna vstupu, konfigurace nebo schváleného prostředí nikdy nevede k tichému použití zastaralého výsledku. Neodsouhlasená změna prostředí se odmítne; při explicitně zvoleném novém průchodu se znovu provedou dotčené kroky.
- Nedokončený či poškozený artefakt se nepovažuje za úspěšný checkpoint. Zápis stavu je atomický; chyba nebo přerušení uchová poslední validní stav a vysvětlí další krok.
- Současné zapisování dvou operací do stejného projektu se odmítne nebo serializuje. Jednoznačně se rozliší živá operace od stavu po přerušení; obnova nevyžaduje smazání celého pracovního prostoru.

### Rozhraní OCR procesu

- Preferovat existující příkazové rozhraní a jeho validátory. Přidat jen potřebné operace pro registraci/seznam projektů, stav a pokračování; pro opravy používat existující strukturované patche.
- Stejné rozhraní použije agent, integrační test i budoucí reviewer. Nezavádět další obecný server, alternativní OCR engine nebo abstraktní systém zásuvných modulů.
- Strojový režim má verzované odpovědi s identitou projektu/průchodu, operací, stavem, počty, odkazy na artefakty a stabilním kódem chyby. Úplný přepis, obrázky a rozsáhlé diagnostiky nepatří do běžné odpovědi.
- Běžný souhrn operace omezit na 4 KiB UTF-8 na stdout. Rozsáhlejší údaje vracet přes uložený soubor nebo výběrový/paginovaný dotaz; limity musí být explicitní a odpověď nesmí skončit neplatným uříznutým JSON.
- stdout strojového režimu obsahuje pouze deklarovaný protokol; diagnostické logy patří do stderr nebo souborů. Podporovat cesty s mezerami a předávat argumenty bez shellové interpolace uživatelských názvů.
- Dávkové zpracování v první etapě znamená evidenci jednotlivých vydání a možnost pokračovat vybraným projektem. Neznamená plně bezobslužné potvrzování OCR kandidátů nebo nahrazení vizuální práce agenta.

### Úspora tokenů a kvalita

- Velké přepisy, kandidáty, rastry, historie a reporty jsou trvalými pracovními soubory. Agent získává konkrétní řádky/stránky/nálezy a stručný souhrn, nikoli opakovaný dump celého vydání.
- Dávkové opravy se validují před atomickým zápisem a uchovávají historii. Neplatný patch nesmí změnit přepis, jeho historii nebo nezávislá očekávání kontrol.
- Úplné první vizuální čtení a povinné technické a geometrické kontroly se zachovají. Další obsahové opravy načítají dotčené řádky a okolí; automatické kontroly se opakují podle závislostí nové exportní iterace.
- Cache a krátké odpovědi jsou konkrétní mechanismy úspory. Neprohlašovat počty znaků, cache hity nebo krátký stdout za skutečně spotřebované AI tokeny. Jejich měření z Codexu patří k navazující integraci.
- Skutečná zkouška schránky zůstává volitelná. `not_tested` neblokuje OCR a neznamená ověřenou UI kompatibilitu. Automatické příkazy nevytvářejí vizuální potvrzení ani souhlas zadavatele.

## Testing Decisions

Hlavní testovací rozhraní je veřejné rozhraní OCR procesu. Test používá stejné vstupy, příkazy, návratové stavy a artefakty jako agent nebo budoucí aplikace. Výsledkem se ověřuje chování, nikoli pořadí interních volání nebo kopie implementačních heuristik.

Převzít dosavadní regresní kontroly validace, atomických oprav, vazby reportů a exportních očekávání. Dosavadní integrační případ se syntetickým skenem je vzor pro nový koncový průchod: potvrzený testový přepis se odvodí z tohoto syntetického zdroje a nezastupuje kontrolu skutečných zpravodajů.

| Kritérium | Ověření připravenosti první etapy |
|---|---|
| A1 — Čisté prostředí | Dokumentovaný instalační/sestavovací postup funguje v deklarovaném Linux prostředí bez projektové vývojové venv a bez Dockeru za běhu. Sada obsahuje potřebné runtime prostředky a manifest. |
| A2 — Odchylka prostředí | Chybějící program, jiná verze, změněný model a změněný font vedou před OCR k jednoznačné chybě; existující projektová data zůstávají zachována. |
| A3 — Identita projektu | Opakovaný import zdroje nerozmnoží neúmyslně projekt. Různé obsahy se stejným názvem jsou oddělené a nepřepisují výsledky. Hash zdroje před a po průchodu je shodný. |
| A4 — Přerušená příprava | Vynucené přerušení mezi stránkami či kandidátními průchody dovolí explicitní pokračování. Již platné výsledky se znovu nevytvářejí; chybějící nebo poškozené se doplní. |
| A5 — Správná cache | Nezměněný podklad je cache hit. Změna obrazu, parametrů, výstupu nebo explicitně schváleného obsahu modelu pod stejným názvem zabrání použití starého výsledku. |
| A6 — Zachování oprav | Po platné dávkové opravě existuje předchozí přepis a aktuální validní přepis. Neplatná oprava ponechá původní stav beze změny. Očekávání testů se nezmění jako vedlejší efekt opravy. |
| A7 — Export a kontroly | Malý syntetický průchod vytvoří PDF/TXT ze stejného přepisu, zachová obraz a geometrické vlastnosti zdroje a projde povinnými kontrolami obrazu, textu, pořadí a výběrových vzorků. |
| A8 — Pravdivé stavy | Kandidátní či nepřečtený přepis se nestane potvrzeným automaticky. Selhání a otevřené nálezy zůstávají odlišeny. Volitelná schránka `not_tested` nepotvrzuje kompatibilitu a sama neblokuje `verified`. |
| A9 — Malé rozhraní | Souhrn nepřekročí 4 KiB a je platný podle verze protokolu; velká testová data zůstanou v souborech. Dotazy respektují výběr/stránkování a strojový stdout neobsahuje diagnostický text. |
| A10 — Bezpečná obnova | Neúplný stav a souběžný zápis nepoškodí poslední platný přepis ani checkpoint. Opakování neúspěšné operace zůstává možné a má vysvětlený postup. |
| A11 — Úplný první průchod | Příprava a export samy nevytvoří záznam o vizuálním čtení. Validace rozlišuje skutečně doplněné vizuální doklady od šablony reportu. |

Každé kritérium má mít spustitelnou kontrolu nebo doložený instalační výsledek. Integrační test vyžadující nativní prostředky se v ověření výsledného balíku nesmí považovat za splněný pouze proto, že byl přeskočen. Stávající lehké CI kontroly mohou zůstat samostatnou rychlou vrstvou.

Při změně pouze návrhu a této specifikace se OCR ani regresní testy nemusí spouštět; implementace první etapy je spustí podle dotčeného chování a kritérií výše.

## Out of Scope

- Windows, macOS, ARM a univerzální podpora všech Linux distribucí v první verzi.
- Změny UI revieweru, vestavěný chat s Codexem, přihlašovací integrace a automatické zapracování skutečného manifestu ruční revize.
- Nový OCR postup, změna konstrukce F, nové modely AI nebo poskytovatelé, placené OCR služby a nový obecný OCR produkt.
- Plně bezobslužné potvrzování kandidátů, omezení povinného prvního vizuálního čtení nebo automatické prohlášení přijetí zadavatelem.
- Nové řešení deskew, odstraňování existující textové vrstvy, odemykání PDF nebo automatického spojování odstavců přes stránky; tyto případy zůstávají v mezích současného workflow.
- Povinné testování skutečné schránky všech čteček, povinné otevírání PDF ve Wordu, DOCX výstup a zavádění nového archivního PDF standardu.
- Opakování celého obsahového prototypu, hromadné zpracování skutečných zpravodajů a úklid či vrácení existujících uživatelských změn.

## Further Notes

Schválený návrh a etapizace jsou v `docs/reviewer-ocr-integration.md` a `docs/ocr-design.md`. Prováděcím zdrojem je `docs/ocr-workflow.md`, datové smlouvy jsou v `docs/ocr-data-contracts.md` a konstrukce vrstvy v `docs/ocr-f-construction.md`. Pojmy určuje `GLOSSARY.md`; zachování obrazu a chyb vydavatele vymezují ADR 0001 a 0002.

V okamžiku přípravy specifikace má aktuální pracovní strom již uživatelské změny OCR nástrojů, testů a prováděcích dokumentů. Vzdálený checkout nemusí obsahovat stejný výchozí stav; před implementací je třeba pracovat s odpovídající aktuální základnou a zachovat její změny.

Nízká spotřeba tokenů je cílem způsobu práce; bez měření konkrétního AI běhu se neuvádí procentní úspora nebo pevný počet tokenů na vydání. První etapa především umožní obnovu, opakované využití podkladů a malé rozhraní. Následná etapa přidá ovládání z revieweru a měření dostupné přes Codex app-server.
