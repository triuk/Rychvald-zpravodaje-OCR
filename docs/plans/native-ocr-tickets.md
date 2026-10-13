# Úkoly první etapy nativního OCR

Stav: sedm úkolů a jejich vazby schváleny zadavatelem a publikovány 13. 10. 2026 podle skillu to-tickets. Všechna issues mají štítek ready-for-agent; jejich obsah, štítky a blokující odkazy byly ověřeny. Rodičem je [specifikace #1](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/1); rodičovské issue zůstalo beze změny.

Každý úkol má ověřitelný výsledek přes veřejné OCR rozhraní. UI revieweru zůstává mimo tuto etapu. Samostatný rozsáhlý refaktor není potřeba; nezbytné úpravy vazby na prostředí patří do prvního úkolu a zachovají současný průchod.

## Přehled

1. **[#2](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/2): OCR průchod s pevně určeným prostředím** — blokují: nic. Agent spustí současné OCR příkazy s jednoznačně určenými nativními prostředky. Před výpočtem se dozví, zda sada odpovídá očekávanému prostředí; odchylka zastaví operaci bez změny projektových dat. Jde o zapojení ověřeného prostředí do skutečného průchodu, nikoli pouze o seznam verzí.

2. **[#3](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/3): Import zdrojových PDF a přehled projektů vydání** — blokují: nic. Agent načte PDF ze složky, získá stabilní projekt pro každé vydání a může vypsat projekty nebo zjistit stav vybraného projektu bez načtení celého přepisu. Import a přehled nevyžadují spuštění OCR.

3. **[#4](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/4): Příprava OCR kandidátů projektu se správnou cache** — blokují: [#2](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/2), [#3](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/3). Agent vybere registrované vydání a připraví rastry a OCR kandidáty ověřeným postupem. Stejné platné podklady se znovu využijí, zatímco změněný model nebo poškozený výstup starou cache nepoužije. Stav projektu ukazuje přípravu kandidátů bez předstírání potvrzeného přepisu.

4. **[#5](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/5): Pokračování přerušené přípravy bez ztráty práce** — blokují: [#4](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/4). Po přerušení agent explicitně obnoví přípravu konkrétního projektu. Proces zkontroluje již dokončené jednotky, dopočítá pouze chybějící nebo neplatné a zachová potvrzené opravy i doklady.

5. **[#6](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/6): Cílené čtení podkladů a bezpečné opravy přepisu** — blokují: [#4](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/4). Agent získá jen požadované řádky, okolí nebo nálezy vybraného projektu a provede dávku strukturovaných oprav. Platné opravy zůstanou v historii; neplatné zadání nezmění rozpracované vydání. Celý přepis a obrazové podklady se opakovaně neposílají do běžných odpovědí.

6. **[#7](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/7): Export a pravdivá validace výsledku projektu** — blokují: [#6](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/6). Agent z přepisu vybraného projektu vytvoří OCR PDF a souvislý text článků, spustí povinné kontroly a získá stručný výsledek s odkazy na doklady. Nová iterace zachová předchozí výsledky a jasně odliší ověřený průchod, otevřené nálezy a selhání.

7. **[#8](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/8): Instalovatelný Linux balík s ověřením celého průchodu** — blokují: [#5](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/5), [#7](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/7). Uživatel na deklarovaném čistém Linuxu nainstaluje nebo sestaví verzovanou nativní sadu z určených vstupů a stejným OCR rozhraním zpracuje syntetické vydání včetně obnovy a opravy. Za běhu nepotřebuje Docker, projektovou vývojovou venv ani ruční dohledávání OCR závislostí.

Issues [#2](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/2) a [#3](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/3) mohou začít nezávisle. Po [#4](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/4) se rozcházejí větve obnovy ([#5](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/5)) a oprav/exportu ([#6](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/6) → [#7](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/7)); balík ([#8](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/8)) je spojuje. Uvedené vazby jsou přímé; tranzitivní závislosti se neopakují.

## Publikované texty issues

### [#2](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/2): OCR průchod s pevně určeným prostředím

## Parent

https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/1

## What to build

Agent spustí současné OCR příkazy s jednoznačně určenými nativními prostředky. Před výpočtem se dozví, zda sada odpovídá očekávanému prostředí; odchylka zastaví operaci bez změny projektových dat. Jde o zapojení ověřeného prostředí do skutečného průchodu, nikoli pouze o seznam verzí.

## Acceptance criteria

- [ ] Verzovaný manifest určuje identitu sestavení, Python runtime, přímé i tranzitivní knihovny, Tesseract, český model, qpdf, Poppler a fonty včetně zdrojů a ověřitelných hashů; nepoužívá neomezené latest.
- [ ] Kontrola prostředí rozliší chybějící prostředek, nesprávnou verzi a změněný obsah modelu nebo fontu; při nesouladu OCR nezačne a existující pracovní data se nezmění.
- [ ] Současná příprava, cílené OCR a export používají určené prostředky, i když PATH nabízí jiné programy; cesty a data se nastavují bez úpravy OCR implementace.
- [ ] Malý syntetický průchod přes existující veřejné příkazy prokáže, že kontrolovaná sada je skutečně použita; změna potřebné verze má záznam a odpovídající integrační ověření.
- [ ] Dokumentace určuje podporovaný Linux x86_64 a požadavky na systémové knihovny. Vývojové prostředí se neprohlašuje za hotový instalační balík.
- [ ] Současné uživatelské úpravy a ověřené obsahové workflow zůstanou zachovány.

## Blocked by

None (can start immediately)

Pokrytí rodičovských kritérií: A2; podklad pro A1 a A7.

### [#3](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/3): Import zdrojových PDF a přehled projektů vydání

## Parent

https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/1

## What to build

Agent načte PDF ze složky, získá stabilní projekt pro každé vydání a může vypsat projekty nebo zjistit stav vybraného projektu bez načtení celého přepisu. Import a přehled nevyžadují spuštění OCR.

## Acceptance criteria

- [ ] Registrace váže zdrojový hash, původní název a průchod; opakovaný import stejného vstupu vrátí existující projekt a samostatný nový průchod vzniká pouze explicitně.
- [ ] Různá PDF se stejným názvem se oddělí bez přepsání zdroje, pracovního prostoru nebo výsledku; zdrojový obsah se nemění.
- [ ] Registry a pracovní prostory respektují oddělení vstupů, práce a výstupů, zachovají prototypové podklady a nalezenou starší práci neoznačí automaticky za ověřenou.
- [ ] Veřejné operace importu, seznamu a stavu mají verzovaný strojový režim: identita projektu/průchodu, operace, stav, počty, odkazy na artefakty a stabilní kódy chyb.
- [ ] Běžný souhrn je platný JSON do 4 KiB UTF-8; rozsáhlý seznam je stránkovaný nebo uložený. Diagnostika nezasahuje do strojového stdout.
- [ ] Testy zahrnou duplicitní obsah, kolizi názvů, přerušený zápis registru, velký seznam a cesty s mezerami; poslední platný registr zůstane použitelný.

## Blocked by

None (can start immediately)

Pokrytí rodičovských kritérií: A3, A9; registr z A10.

### [#4](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/4): Příprava OCR kandidátů projektu se správnou cache

## Parent

https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/1

## What to build

Agent vybere registrované vydání a připraví rastry a OCR kandidáty ověřeným postupem. Stejné platné podklady se znovu využijí, zatímco změněný model nebo poškozený výstup starou cache nepoužije. Stav projektu ukazuje přípravu kandidátů bez předstírání potvrzeného přepisu.

## Acceptance criteria

- [ ] Příprava vybraného projektu používá ověřené prostředí, stávající rastry a kandidátní průchody; úspěch přípravy není obsahové ověření ani přijetí uživatelem.
- [ ] Identita OCR cache zahrnuje obraz nebo výřez, parametry, jazyk, Tesseract, obsah použitých jazykových modelů a hashe výsledků; tato pravidla platí i pro cílené OCR.
- [ ] Nezměněný podklad je doložený cache hit. Změna parametrů či explicitně schválené sady v novém průchodu a poškozený výstup vyžadují nový výpočet. Neodsouhlasená změna prostředí se odmítne.
- [ ] Každý dokončený rastr a kandidátní průchod má atomicky uložený záznam identity a dokončení, který připraví obnovu; neúplný artefakt se nevydává za platný výsledek.
- [ ] Zápis do jednoho projektu je chráněn před souběžnými operacemi; stav a chyba jsou dostupné přes krátké verzované odpovědi. Ostatní projekty lze dále zpracovávat.
- [ ] Veřejný integrační test ověří přípravu, cache hit, obsahovou změnu modelu pod stejným názvem, poškozený kandidátní výstup a souběžný pokus o zápis.

## Blocked by

- [#2: OCR průchod s pevně určeným prostředím](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/2)
- [#3: Import zdrojových PDF a přehled projektů vydání](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/3)

Pokrytí rodičovských kritérií: A5, A8, A11; checkpointy a zámek pro A4/A10.

### [#5](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/5): Pokračování přerušené přípravy bez ztráty práce

## Parent

https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/1

## What to build

Po přerušení agent explicitně obnoví přípravu konkrétního projektu. Proces zkontroluje již dokončené jednotky, dopočítá pouze chybějící nebo neplatné a zachová potvrzené opravy i doklady.

## Acceptance criteria

- [ ] Nový průchod a pokračování existujícího průchodu jsou odlišné operace; samotná existence vstupního manifestu pokračování neblokuje.
- [ ] Obnova ověří identity a hashe dokončených rastrů a kandidátních průchodů; platné jednotky nepřepočítá a nedokončené nebo poškozené doplní.
- [ ] Nesoulad zdroje, konfigurace či prostředí se vysvětlí a nevede k tichému použití starých dat; další krok nevyžaduje smazání celého pracovního prostoru.
- [ ] Živá operace se odliší od opuštěného stavu po přerušení; obnova neobejde živý zámek a zůstane bezpečná při dalším přerušení.
- [ ] Vynucené přerušení mezi stránkami i kandidátními průchody, poškozený checkpoint a opakování neúspěšné operace mají veřejné integrační kontroly.
- [ ] Pokračování nezmění poslední validní přepis, historii oprav, doklady nálezů ani nezávislá očekávání; souhrn a stav dodržují limit a protokol.

## Blocked by

- [#4: Příprava OCR kandidátů projektu se správnou cache](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/4)

Pokrytí rodičovských kritérií: A4, A10.

### [#6](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/6): Cílené čtení podkladů a bezpečné opravy přepisu

## Parent

https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/1

## What to build

Agent získá jen požadované řádky, okolí nebo nálezy vybraného projektu a provede dávku strukturovaných oprav. Platné opravy zůstanou v historii; neplatné zadání nezmění rozpracované vydání. Celý přepis a obrazové podklady se opakovaně neposílají do běžných odpovědí.

## Acceptance criteria

- [ ] Výběrové nebo stránkované dotazy pokryjí přepis, kandidáty a nálezy s vazbou na zdrojové podklady; rozsáhlé údaje mají explicitní limity nebo odkazy na uložený artefakt.
- [ ] Strojové odpovědi dotazů a oprav jsou verzované, platné a do 4 KiB UTF-8; dlouhý text se neusekne do neplatného JSON a neplete se s diagnostikou.
- [ ] Opravy používají stávající strukturované patche a datové validátory. Celá dávka se ověří před atomickým zápisem a uchová předchozí přepis i historii.
- [ ] Neplatný patch ponechá přepis, historii a nezávislá očekávání beze změny; platná změna zneplatní pouze příslušné odvozené výsledky a reporty podle současných smluv.
- [ ] Nevyřešená místa, rekonstrukce a chyby vydavatele si zachovají doklady a odlišný význam; dotaz ani patch automaticky nepotvrdí první vizuální čtení.
- [ ] Testy přes veřejné rozhraní ověří malý dotaz nad velkým vydáním, opravu s historií, neplatnou dávku, souběžný zápis a zachování nepříslušných dat.

## Blocked by

- [#4: Příprava OCR kandidátů projektu se správnou cache](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/4)

Pokrytí rodičovských kritérií: A6, A9; zachování dat z A10/A11.

### [#7](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/7): Export a pravdivá validace výsledku projektu

## Parent

https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/1

## What to build

Agent z přepisu vybraného projektu vytvoří OCR PDF a souvislý text článků, spustí povinné kontroly a získá stručný výsledek s odkazy na doklady. Nová iterace zachová předchozí výsledky a jasně odliší ověřený průchod, otevřené nálezy a selhání.

## Acceptance criteria

- [ ] Export používá současnou konstrukci F a datové smlouvy; PDF a text článků vycházejí ze stejného přepisu a zachovají očekávaný obraz, geometrii, pořadí čtení a výběrové vzorky.
- [ ] Výstupy různých projektů se při kolizi původních názvů nepřepíší; nové iterace zachovají předchozí výsledky, historii a vazbu na zdrojový hash.
- [ ] Stav projektu odlišuje fázi, operaci a výsledek kontrol. Validace průchodu zachová failed/1, ready_with_open_items/2 a verified/0; úspěch jiného příkazu není verified.
- [ ] Nepřečtený kandidát ani šablona vizuálního reportu neprojdou jako potvrzený přepis. Úplné první čtení a povinné kontroly zůstanou podmínkou podle ověřeného workflow.
- [ ] Volitelná schránka not_tested sama neblokuje verified a nedokládá UI kompatibilitu; souhlas zadavatele zůstává samostatný.
- [ ] Syntetický koncový test a dosavadní regresní kontroly ověří export, zastaralé reporty po opravě, otevřené nálezy a selhání. Výsledky jsou dostupné krátkým protokolem, velké doklady v artefaktech.

## Blocked by

- [#6: Cílené čtení podkladů a bezpečné opravy přepisu](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/6)

Pokrytí rodičovských kritérií: A7, A8, A11; exportní část A3/A9.

### [#8](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/8): Instalovatelný Linux balík s ověřením celého průchodu

## Parent

https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/1

## What to build

Uživatel na deklarovaném čistém Linuxu nainstaluje nebo sestaví verzovanou nativní sadu z určených vstupů a stejným OCR rozhraním zpracuje syntetické vydání včetně obnovy a opravy. Za běhu nepotřebuje Docker, projektovou vývojovou venv ani ruční dohledávání OCR závislostí.

## Acceptance criteria

- [ ] Balík obsahuje spouštěč, runtime, potřebné programy, český model a fonty podle ověřeného manifestu; sestavení a instalace používají připnuté ověřitelné vstupy.
- [ ] Běh v čistém deklarovaném Linux x86_64 prostředí nepoužívá projektovou vývojovou venv ani náhodné OCR prostředky z PATH a nevyžaduje Docker.
- [ ] Dokumentovaný koncový průchod přes veřejné rozhraní pokryje import, přípravu, přerušení a pokračování, výběrový dotaz, dávkovou opravu, PDF/TXT export a validaci syntetického zdroje.
- [ ] Kontrola balíku odmítne změněný model nebo font a doloží správnou cache, kolize názvů, ochranu souběžných zápisů a limit strojových odpovědí.
- [ ] Povinný integrační test balíku se nepovažuje za splněný při přeskočení; výsledky dokládají všechna kritéria A1–A11 rodičovské specifikace.
- [ ] Instalační a provozní návod určí podporovaný systém, postup po selhání a hranice následné etapy. Nezavádí UI revieweru, Windows ani měření skutečných AI tokenů.

## Blocked by

- [#5: Pokračování přerušené přípravy bez ztráty práce](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/5)
- [#7: Export a pravdivá validace výsledku projektu](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/7)

Pokrytí rodičovských kritérií: A1 a závěrečné ověření A2–A11.


## Vazby v trackeru

Použité připojené GitHub rozhraní nenabízí zápis nativních issue dependencies ani sub-issues a gh CLI na stroji není dostupné. Blokující vazby jsou proto jednoznačné odkazy na skutečná issues v oddílu Blocked by. Rodičovská specifikace se nemění ani neuzavírá. Implementace může začít úkolem, jehož blokátory jsou dokončené; samotný štítek ready-for-agent neodstraňuje závislosti.
