# WebUI pro autonomní OCR a porovnávání průchodů

Stav: implementační specifikace odvozená z rozhodnutí Q19–Q35 a podmínek přijetí B1–B9, které zadavatel potvrdil v Q36 dne 14. 10. 2026. Navazuje na dokončenou první etapu nativního OCR; tato publikace sama nezahajuje implementaci.

## Problem Statement

Operátor potřebuje opakovaně zpracovávat zdrojová PDF Rychvaldského zpravodaje, ladit automatickou část OCR a posoudit, které kroky ovlivňují kvalitu, dobu zpracování a spotřebu AI. Současné nástroje poskytují místní OCR, registry, obnovu přípravy, cílené dotazy a opravy, export a kontroly, ale chybí jim GUI a řízení celého průchodu včetně AI.

Z příkazových výstupů a pracovních souborů nelze pohodlně sledovat jednotlivá vydání, rozlišovat místní výpočty od AI, dohledávat použitá zadání a porovnávat varianty stejného zpracování. Přerušení, nové průchody, převzatá místní cache a skutečná AI spotřeba potřebují společnou, trvalou a pravdivou evidenci. Úspěch příkazu nebo sestavení PDF přitom sám nepotvrzuje správnost přepisu.

Operátor chce spustitelnou Linux aplikaci připravenou pro pozdější začlenění do pdf-ocr-reviewer. V této etapě se soustředí na automatické zpracování; ruční doplňování textu a vložené zobrazení PDF zůstávají úlohou revieweru.

## Solution

Vytvořit nativní Linux aplikaci s WebUI, která řídí celý ověřený OCR postup od importu přes místní přípravu, skutečné vizuální čtení a rekonstrukci AI až po export, kontroly a omezené cílené opravy.

V levém sloupci budou projekty vydání. Každé vydání zastřeší pojmenované průchody OCR a jejich historii. Milníky a rozbalitelné kroky ukážou aktuální stav, místní/AI práci, dokončené jednotky, čas, dostupné tokeny a srovnávací odhad ceny. U AI bude dostupné zadání aplikace, použité podklady, odpověď a dostupná nástrojová činnost.

Aplikace umožní porovnat průchody stejného PDF i po restartu, vybírat externě spravované profily, řídit frontu a bezpečně pokračovat po přerušení. Přibalený a ověřený Codex app-server musí podporovat GPT-6.1 Sol high a funkční context-mode. Tato kombinace je povinnou podmínkou přijetí, doloženou skutečným během.

## User Stories

1. Jako operátor chci spustit Linux aplikaci, abych mohl řídit OCR bez ručního sestavování příkazů.
2. Jako operátor chci používat přibalené ověřené prostředky bez vývojového Python prostředí a Dockeru, abych nemusel rekonstruovat vývojářskou instalaci.
3. Jako správce chci znát skutečně podporovanou platformu, abych mohl rozlišit ověřené a neověřené prostředí.
4. Jako správce chci ověřitelné verze a hashe přibalených prostředků, abych mohl vysvětlit změnu prostředí nebo výsledku.
5. Jako operátor chci, aby spuštění nevyžadovalo dodatečné instalování závislostí, abych měl předvídatelné pracoviště.
6. Jako operátor chci použít účet ChatGPT, abych zachoval zvolený způsob přístupu k AI.
7. Jako operátor chci podporu modelu GPT-6.1 Sol s úrovní high a obrazovými vstupy, abych mohl používat požadovanou kombinaci pro vizuální OCR.
8. Jako operátor chci funkční context-mode včetně automatického směrování nástrojů, abych omezoval zbytečný přenos rozsáhlých výstupů.
9. Jako operátor chci jednoznačně poznat nedostupnost požadovaného modelu nebo context-mode, abych omylem neporovnával běh s jinými podmínkami.
10. Jako operátor chci importovat zdrojové PDF a složky přes existující evidenci, abych připravil jednotlivá vydání ke zpracování.
11. Jako operátor chci při opakovaném načtení stejného zdroje najít existující projekt vydání, abych nezakládal neúmyslné duplicity.
12. Jako operátor chci odlišit různá PDF stejného názvu, abych nepřepsal zdroj ani výsledky.
13. Jako operátor chci vlevo vidět jeden projekt vydání pro jedno zdrojové PDF, abych se orientoval podle zpravodajů.
14. Jako operátor chci uvnitř vydání pojmenované průchody OCR, abych rozlišil jednotlivé experimenty a jejich účel.
15. Jako operátor chci dohledat starší projektové záznamy i jejich výsledky, abych mohl navázat na dosavadní práci.
16. Jako operátor chci zachovat zdrojový sken beze změny, abych měl trvalou předlohu pro porovnání.
17. Jako operátor chci vybrat externě spravovaný profil průchodu OCR, abych mohl prompty připravovat konzultací s AI v jiném okně.
18. Jako operátor chci v GUI prohlédnout parametry a prompty vybraného profilu, abych před spuštěním znal podmínky zpracování.
19. Jako operátor chci v historii přesnou použitou podobu profilu, abych později vysvětlil rozdíl mezi průchody.
20. Jako operátor chci upravený profil použít pro nový průchod, abych nezměnil historii předchozího experimentu.
21. Jako operátor chci zařazovat průchody do fronty a měnit jejich pořadí, abych rozhodoval o pořadí zpracování.
22. Jako operátor chci jeden aktivní průchod, abych mohl přehledně sledovat jeho práci a porovnávat výkon.
23. Jako operátor chci pokračovat jinými vydáními, když jedno čeká na doplnění, abych nezablokoval celou dávku.
24. Jako operátor chci vidět hlavní logické milníky a aktuální práci u každého vydání, abych rychle poznal stav zpracování.
25. Jako operátor chci rozbalit milník na jednotlivé místní a AI kroky, abych našel konkrétní příčinu prodlevy nebo nákladů.
26. Jako operátor chci počty dokončených stránek a úloh tam, kde jsou známé, abych rozuměl průběhu bez zavádějících procent.
27. Jako operátor chci poznat ověřený checkpoint, abych věděl, odkud lze bezpečně pokračovat.
28. Jako operátor chci u kroku začátek, konec a dobu běhu, abych našel časově náročné části.
29. Jako operátor chci odlišit čekání od aktivní práce, abych správně vyhodnotil dobu zpracování.
30. Jako operátor chci dohledat zadání AI kroku a jeho podklady, abych mohl posoudit a upravit použitý prompt.
31. Jako operátor chci dostupné odpovědi AI a záznamy použitých nástrojů, abych vysvětlil dosažený výsledek.
32. Jako operátor chci vazbu vydání, průchodu, kroku a pokusu na konkrétní AI tah, abych správně přiřadil jeho stav a spotřebu.
33. Jako operátor chci tokeny oddělené na necacheovaný vstup, cacheovaný vstup a výstup, abych rozuměl skladbě spotřeby.
34. Jako operátor chci podrobnosti uvažování bez dvojího započtení, abych nepřeceňoval celkovou spotřebu.
35. Jako operátor chci chybějící nebo neúplné měření jasně označené, abych je nezaměnil za nulovou spotřebu.
36. Jako operátor chci odhad ceny podle doložených API sazeb, abych mohl srovnávat nákladovost průchodů.
37. Jako operátor chci odlišit srovnávací odhad od skutečného účtování předplatného, abych cenu správně interpretoval.
38. Jako operátor chci stálé barvy tokenových kategorií a společnou cenovou škálu porovnávaných průchodů, abych mohl údaje vizuálně porovnat.
39. Jako operátor chci cenu kroku, celého průchodu i přepočet na stránku, abych rozlišil drahý krok od většího vydání.
40. Jako operátor chci zaznamenané přesměrování na jiný model, abych poznal odchylku od požadované kombinace.
41. Jako operátor chci znovu využít platnou místní přípravu se shodnou identitou, abych při změně promptu neopakoval zbytečné výpočty.
42. Jako operátor chci rozlišit místní cache a cacheované vstupní tokeny AI, abych nezaměnil dva různé mechanismy úspory.
43. Jako operátor chci v novém srovnávacím průchodu samostatný AI kontext, abych měřil vliv profilu bez přebírání předchozích AI výsledků.
44. Jako operátor chci při pokračování stejného průchodu zachovat dokončené AI kroky, abych neopakoval již ověřenou práci.
45. Jako operátor chci úplné první vizuální čtení skenu, abych získal přepis založený na předloze.
46. Jako operátor chci rekonstrukci obtížných míst s doklady, abych mohl rozlišit podložené čtení a nejistotu.
47. Jako operátor chci nevyřešená místa uchovaná pro reviewer, abych je mohl později ručně doplnit s potřebným kontextem.
48. Jako operátor chci zachované čitelné chyby vydavatele s oddělenou evidencí, abych měl věrný historický přepis.
49. Jako operátor chci OCR PDF a text článků ze stejného přepisu, abych dostal vzájemně odpovídající výstupy.
50. Jako operátor chci zachovaný obraz stránky a logické pořadí článků, abych mohl výstup číst, vyhledávat a kopírovat.
51. Jako operátor chci kontroly skutečně exportovaného PDF, abych ověřil výstup používaný čtenářem.
52. Jako operátor chci cílené opravy konkrétních nálezů, abych zlepšil výsledek bez opakování celého čtení.
53. Jako operátor chci nejvýše tři následné opravné cykly a dřívější zastavení stejného neúspěchu, abych měl předvídatelnou hranici automatického opravování.
54. Jako operátor chci zachovat každou předchozí exportní iteraci s podklady a kontrolami, abych mohl dohledat dopad opravy.
55. Jako operátor chci oddělené stavy operace, validace a přijetí zadavatelem, abych si úspěch exportu nespletl s potvrzením kvality.
56. Jako operátor chci souhrny kontrol, nálezy a otevření souvisejících PDF nebo podkladů v externím nástroji, abych posoudil automatickou část.
57. Jako operátor chci pozastavit frontu po dokončení rozpracované jednotky, abych neukončil potřebnou práci uprostřed.
58. Jako operátor chci přerušit běžící práci a uchovat platné výsledky, abych mohl změnit plán zpracování.
59. Jako operátor chci při zavření aplikace uložený a přerušený stav, abych neměl nejasně běžící zpracování na pozadí.
60. Jako operátor chci po restartu pokračovat od posledního ověřeného bodu, abych nepřišel o hotové podklady.
61. Jako operátor chci v historii spotřebu přerušeného AI pokusu, abych nepodhodnotil skutečnou aktivitu.
62. Jako operátor chci při nedostupnosti AI pozastavenou frontu s vysvětlením, abych věděl, proč zpracování čeká.
63. Jako operátor chci před opakováním již odeslané úlohy zjistit její stav, abych nezadal tutéž práci znovu při pouhém výpadku spojení.
64. Jako operátor chci po obnovení dostupnosti AI nabídku pokračovat, abych mohl dokončit rozpracovaný průchod.
65. Jako operátor chci chybu jednoho PDF oddělenou od celé fronty, abych mohl zpracovat ostatní vydání.
66. Jako operátor chci bezpečné atomické zápisy a ochranu před souběžným zápisem do téhož průchodu, abych neztratil práci.
67. Jako operátor chci ověření zdrojů, prostředí a cache před pokračováním, abych nepoužil poškozené nebo zastaralé výsledky.
68. Jako operátor chci porovnat uložené průchody i po restartu aplikace, abych nemusel analýzu dokončit během jediného spuštění.
69. Jako správce chci oddělený kontext a znalostní evidenci různých průchodů, abych zabránil smísení jejich podkladů.
70. Jako správce chci zachované veřejné OCR rozhraní, abych mohl dál používat existující nástroje a později připojit reviewer.
71. Jako správce chci trvalá projektová data nezávislá na výměně programového balíku, abych mohl aktualizovat aplikaci bez ztráty historie.
72. Jako zadavatel chci důkaz skutečného autonomního běhu s požadovaným modelem a context-mode, abych nepřijal pouze simulované nebo deklarované propojení.

## Implementation Decisions

### Hranice aplikace a veřejné rozhraní

- GUI používá WebUI podle existujících projektů example-webui-python a pdf-ocr-reviewer. Dlouhé zpracování běží mimo synchronní GUI callbacky, aby sledování a ovládání zůstaly dostupné.
- Společné řízení průchodu a fronty poskytne veřejné operace, dotazy a události používané GUI i integračními testy. Je to hlavní nová aplikační hranice pro import/seznam/stav, profily, spuštění, pozastavení, přerušení, pokračování, frontu, historii a porovnávání.
- Místní OCR zůstane samostatným nativním procesem podle ADR 0003. Řízení použije existující procesové operace a validátory; budoucí reviewer využije stejné řízení bez nutnosti sjednotit Python runtime.
- Zachovat existující verzovaný strojový protokol, stabilní chybové kódy, stránkování a souhrn do 4 KiB. Rozsáhlé podklady zůstávají v artefaktech nebo výběrových dotazech; živé události nesmějí zneplatnit stdout protokol.
- Předávat procesové argumenty strukturovaně a zachovat podporu uživatelských cest s mezerami.

### Projekty vydání, průchody a profily

- Projekt vydání je pracovní celek jednoho zdrojového PDF, který zastřešuje více průchodů OCR. Průchod má vlastní identitu, podklady, profil, historii, pokusy, exportní iterace a výsledky.
- Opakovaný import stejného zdroje nevytváří neúmyslné vydání. Různý obsah se stejným názvem se oddělí. Zdrojový sken zůstává nezměněný.
- Současné záznamy, které vážou projekt na průchod, musí být kompatibilně seskupitelné. Zachovat jejich dohledatelnost, výsledky, opravy a validační význam; samotné načtení do GUI neprohlašuje starší práci za ověřenou.
- Profil průchodu OCR je externě spravovaná pojmenovaná sada promptů a parametrů, například DPI, jazyk místního OCR, model AI a míra uvažování. GUI umožní výběr a prohlédnutí profilu. Průchod uloží přesnou použitou podobu; pozdější změna profilu se uplatní v novém průchodu.
- Nový srovnávací průchod může převzít ověřenou místní přípravu jen při shodě úplné identity vstupů, parametrů a prostředků. AI začne znovu s vlastním kontextem bez přebírání předchozích AI výsledků.
- Pokračování stejného průchodu zachová jeho dokončené ověřené kroky. Historie rozliší převzaté podklady, nově spočítanou práci a další pokusy.
- Zachovat atomické zápisy, ochranu před souběžným zápisem, ověřování hashů a pravidla invalidace. Změna profilu či prostředí nesmí tiše předefinovat rozpracovaný průchod.

### Milníky, workflow a opravné cykly

- Levý sloupec zobrazuje vydání a milníky: příprava → vizuální přepis a rekonstrukce → pořadí článků a geometrie → export → kontroly a opravy → předání k revizi.
- Detail rozbalí milníky na místní a AI kroky. Měřitelné jednotky ukazují počty dokončených stránek/úloh; AI krok ukazuje stav a čas. Checkpoint je uložený a ověřený bod pro pokračování.
- Převzít dosavadní ověřený OCR postup, datové smlouvy a konstrukci neviditelné vrstvy F. Zachovat obraz skenu podle ADR 0001 a čitelné chyby vydavatele s oddělenou evidencí podle ADR 0002.
- Úplné první vizuální čtení zůstává povinné. context-mode omezuje zbytečný přenos rozsáhlých textových podkladů; nesmí toto čtení nahradit souhrnem kandidátního OCR.
- Rekonstrukce obtížného čtení patří do základního průchodu a má vlastní doklady. Nevyřešená místa se zachovají s podklady pro reviewer; neblokují další vydání.
- První kompletní OCR PDF a TXT vzniknou po přípravě přepisu a geometrie celého vydání, před závěrečnými kontrolami. Kontroly pracují se skutečně exportovaným PDF.
- Po prvním kompletním výsledku jsou nejvýše tři následné cílené opravné cykly nad konkrétními nálezy v přepisu, pořadí čtení nebo geometrii. Opakování stejného neúspěchu je zastaví dříve.
- Nový potřebný export vytvoří další iteraci a zopakuje dotčené kontroly. Předchozí PDF/TXT, zmrazené vstupy, historie a doklady kontrol se zachovají. Očekávání odvozená nezávisle ze zdroje se nemění jen proto, aby kontrola prošla.
- Technické závady nástrojů či prostředí se samostatně zaznamenají k vyřešení. Autonomní zpracování mění projektová data přes validované operace; nepřepisuje implementaci programu při chybě.
- Fáze, stav běžící operace, výsledek validace a přijetí zadavatelem jsou oddělené. Zachovat význam failed, ready_with_open_items a verified; dokončení AI tahu ani exportu není dokladem přijetí nebo správného přepisu.

### Fronta, přerušení a obnova

- Fronta je ručně řaditelná a má jeden aktivní průchod. Vydání čekající na doplnění uvolní místo dalšímu.
- Pozastavení dokončí právě rozpracovanou jednotku a další nezačne. Přerušení ukončí běžící práci a zachová platné výsledky.
- Zavření aplikace přeruší zpracování a uloží stav. Po dalším spuštění se nabídne pokračování od posledního ověřeného bodu.
- Přerušený AI krok může vyžadovat nový pokus; předchozí pokus i jeho spotřeba zůstávají v historii.
- Nedostupnost AI, vyčerpaný limit nebo ztráta přihlášení pozastaví frontu a zobrazí důvod. Po obnovení dostupnosti se nabídne pokračování.
- Před opakováním již odeslané AI úlohy se zjistí její skutečný stav, aby výpadek spojení nezpůsobil duplicitní zadání. Obnova konverzačního vlákna a ověření OCR checkpointu jsou dvě samostatné operace.
- Chyba konkrétního PDF se zaznamená u vydání a fronta pokračuje dalším.

### Codex a context-mode

- Přibalit konkrétní ověřenou verzi Codex app-serveru. Přístup k AI je přes účet ChatGPT podle ADR 0004.
- Povinně podporovat přesně gpt-6.1-sol s explicitní úrovní high, obrazovými vstupy a funkčním context-mode. Při zvoleném požadavku nepoužít tiše jiný model, úroveň ani běh bez context-mode.
- Před OCR ověřit dostupné schopnosti klienta a modelu. Katalog či schéma nejsou dokladem oprávnění přihlášeného účtu; skutečný přístup se ověří integračním tahem.
- Evidovat požadovaný model a dostupné údaje o skutečně použitém modelu, včetně událostí přesměrování. Přesměrovaný tah se nepovažuje za důkaz splnění podmínky GPT-6.1 Sol high.
- Podpora context-mode zahrnuje funkční MCP nástroje, příslušné instrukce i skutečně spuštěné důvěryhodné hooky pro používané směrování a obnovu kontextu. Registrace MCP samotná nestačí.
- Připnout ověřené verze Codexu, context-mode a potřebných runtime prostředků. Průzkum context-mode 1.0.169 doložil Node.js nejméně 22.5.0, SQLite FTS5 a detekci Codexu alespoň 0.141.0 pro směrování; finální kombinace se vybere a ověří jako celek.
- Procesové cesty MCP i hooků musí najít přibalený Codex a runtime. Potřebné JavaScript/Python/shell nástroje a databázové závislosti se připraví při sestavení, bez runtime instalací či oprav závislostí.
- Pracovní kořen, znalostní databáze, session evidence a kontext context-mode se přiřadí konkrétnímu průchodu. Ověřit potřebný přístup k jeho podkladům a izolaci od jiného průchodu.
- Efektivní profil, instrukce, konfigurace a verze ovlivňující běh se zaznamenají tak, aby šel rozdíl průchodů vysvětlit.

### Historie, časy, tokeny a ceny

- Trvale přiřazovat projekt vydání, průchod, krok a pokus ke konverzačnímu vláknu a tahu Codexu. Uchovat původní události potřebné k ověření přiřazení a deduplikaci.
- Detail AI zpřístupní zadání sestavené aplikací, identity použitého profilu a podkladů, dostupné odpovědi a nástrojové události. Neslibovat úplný interní kontext modelu ani přesné metriky každého interního modelového požadavku.
- Evidovat začátek, konec, stav a trvání kroků. Rozlišit dobu celého průchodu, aktivní práci a čekání; čas vnořených nástrojů nepřičítat podruhé k celkovému času.
- Zobrazit dostupné tokeny ve třech částech: necacheovaný vstup, cacheovaný vstup a výstup. Podrobnosti uvažování se nepřičítají podruhé k výstupu.
- Integračně ověřit význam a přírůstky usage událostí. Pole last nepovažovat bez ověření za součet celého kroku; opakované kumulativní snímky total se nesčítají. Ošetřit obnovení, přerušení, kompaktaci a opožděné události.
- Chybějící, neúplná nebo neověřitelná metrika se zobrazuje jako nedostupná či neúplná, nikoli nula. Délka textu, krátká odpověď ani místní cache nejsou skutečná AI spotřeba.
- Cena je výslovně srovnávací odhad podle doložených API sazeb s uchovaným zdrojem/verzí ceníku. Nejde o skutečně účtovanou cenu běhu v předplatném ChatGPT. Chybějící sazba modelu se nenahradí sazbou jiného modelu.
- Tři tokenové kategorie mají stálé barvy; cena kroku samostatnou intenzitu. Porovnávané průchody používají společnou škálu a legendu. Číselně zobrazit cenu kroku, průchodu a přepočet na stránku.
- Historie a porovnávání dvou průchodů musí fungovat i po restartu, včetně jejich profilů, místní cache, spotřeby, otevřených nálezů a výsledků kontrol.

### Distribuce a hranice revieweru

- První podporovaný cíl je dosud ověřený Linux x86_64-v3. Spustitelné GUI doprovází přibalený OCR adresář a ověřené AI/runtime prostředky; jediný fyzický soubor není podmínkou.
- Běh nevyžaduje vývojové Python prostředí ani Docker. Deklarovat a otestovat potřebné desktopové prostředí WebUI; neslibovat všechny Linux distribuce bez ověření.
- Přibalit konkrétní ověřenou nativní knihovnu WebUI a její hash. Samotná verze Python wrapperu nepřipíná nativní nightly artefakt; spuštění nic nedostahuje.
- Projektová data a historie musí zůstat trvalé při restartu, relokaci nebo výměně programového balíku.
- Tato etapa poskytne souhrny kontrol, nálezy a otevření PDF či podkladů v externím nástroji. Vložený náhled a ruční doplňování budou až po propojení s pdf-ocr-reviewer; jeho manifest se nezaměňuje za historii provádění OCR.

## Testing Decisions

### Hlavní testovací hranice

Hlavní nová testovací hranice jsou veřejné operace, dotazy, události a artefakty řízení aplikace, které používá i GUI. Integrační test má spouštět stejné akce jako operátor a posuzovat uložený průběh, návratové stavy a výstupy. Existující veřejné rozhraní samostatného OCR procesu a jeho regresní kontroly se zachovají jako podklad této hranice.

Testy mají ověřovat vnější chování a invarianty dat, nikoli pořadí interních volání nebo kopie implementačních heuristik. Nové testovací body uvnitř jednotlivých pomocných funkcí nejsou cílem. Tenké GUI scénáře navíc ověří dostupnost ovládání během dlouhé práce, zobrazení stavu a zavření/znovuspuštění aplikace.

Pro řízené chyby, duplicity, opožděné události a přerušení lze použít testovací protějšek na procesové hranici Codexu. Taková simulace nenahrazuje skutečný modelový běh ani důkaz autonomie.

### Moduly a předchozí testovací základ

- Ověřit společně registr projektů vydání, řízení průchodů/fronty, adaptéry procesů OCR a Codexu, trvalou historii/metriky a veřejné GUI operace.
- Převzít dosavadní veřejné regresní scénáře registru, cílených dotazů, validovaných oprav, checkpointů, cache, obnovy, exportních iterací a pravdivých stavů.
- Zachovat instalační kritéria první etapy A1–A11, včetně čistého prostředí, relokace, změn modelů/fontů, cest s mezerami, atomických zápisů, zámků a nenarušeného strojového protokolu.
- Využít existující syntetický generátor skenu se známým zněním a nezávislými očekáváními. Jeho dosavadní programové vložení potvrzení přepisu není důkazem skutečného AI čtení.
- Dosavadní šestistránkový prototyp skutečného zpravodaje má otevřená nevyřešená místa a stav ready_with_open_items. Poskytuje podklady a srovnání, nikoli bezchybný schválený etalon.
- Nové kontroly přepisu, geometrie a výběrů odvozovat ze zdrojového skenu; nepřizpůsobovat nezávislá očekávání chybné implementaci.

### Potvrzené podmínky přijetí B1–B9

| Kritérium | Požadovaný důkaz |
|---|---|
| B1 — Samostatný balík | GUI a místní OCR se spustí na deklarovaném desktopu bez vývojové venv/Dockeru; přibalené runtime prostředky jsou ověřené a původní A1–A11 zůstávají splněné. |
| B2 — Požadovaná AI kombinace | Skutečný tah s přihlášeným účtem používá GPT-6.1 Sol high a obrazový vstup. Context-mode doloží zdravý MCP, skutečné spuštění důvěryhodných hooků, směrování velkého výstupu, záznam/vyhledání znalosti, obnovu kontextu a izolaci dvou průchodů. Nedostupnost nezpůsobí tichou náhradu; běh neinstaluje závislosti. |
| B3 — Autonomní malý průchod | Nový malý syntetický sken projde přes skutečné AI čtení k PDF/TXT a kontrolám. Očekávání jsou nezávisle odvozená ze skenu; fixture nevkládá potvrzený přepis místo AI. |
| B4 — Reálná obtížná předloha | Nově odvozená malá stránka/oblast dosavadního skutečného skenu doloží čtení, nálezy a předání nevyřešených míst. Starý prototyp je podklad k porovnání, nikoli bezchybný schválený etalon. |
| B5 — Srovnání průchodů | Dva průchody stejného PDF s odlišným profilem zachovají samostatné AI kontexty, pravdivě označenou místní cache, úplnou historii a porovnání metrik/kvality i po restartu GUI. |
| B6 — Obnova a fronta | Přerušení místní i AI práce, zavření/znovuspuštění, pokračování z ověřeného bodu, řazení fronty, chyba jednoho PDF a globální nedostupnost AI mají dohodnuté chování bez ztráty dat. |
| B7 — Pravdivé metriky | Opakované/opožděné události, obnovení, kompaktace a přerušený tah nezdvojí tokeny ani časy. Měření, odhad, převzatá práce a nedostupné údaje se rozlišují. |
| B8 — Opravy a výsledné stavy | Nejvýše tři cílené opravné cykly, dřívější zastavení stejného neúspěchu, zachování exportních iterací a oddělení dokončení/validace/přijetí. Chyby vydavatele a nevyřešená místa se vykazují pravdivě. |
| B9 — Kompatibilita a hranice GUI | Starší data a veřejné CLI zůstanou použitelné. GUI ukazuje vydání, milníky, profily, nálezy a odkazy na podklady; ruční opravy a vložený náhled zůstávají v revieweru. |

B2–B4 vyžadují doloženou skutečnou AI práci. Test vyžadující nativní prostředky nebo účet není pro přijetí splněný tím, že byl přeskočen. Rychlé regresní testy a úplné instalační/AI ověření mohou být samostatné vrstvy. Výsledky mají obsahovat identitu prostředí, modelu, profilu a výstupů a odkazy na zachované důkazy.

## Out of Scope

- Windows, macOS, ARM a obecná kompatibilita všech Linux distribucí.
- Vložený PDF náhled, ruční doplňování či úpravy přepisu v tomto GUI, plná integrace pdf-ocr-reviewer a automatické zapracování jeho manifestu.
- Vestavěný editor promptů; profily se připravují mimo GUI a aplikace je vybírá a prohlíží.
- Souběžné zpracování více průchodů v první verzi a pokračování OCR na pozadí po zavření aplikace.
- Nový OCR engine, změna konstrukce F, nové placené OCR služby nebo redakční opravy čitelných chyb vydavatele.
- Nahrazení úplného prvního vizuálního čtení pouhým souhrnem kandidátů nebo automatické prohlášení přijetí zadavatelem.
- Garance úplného interního kontextu modelu, přesných metrik každého interního modelového volání nebo skutečné peněžní ceny odvozené z předplatného.
- Opakování celého archivu nebo kompletního obsahového prototypu bez potřeby; pro přijetí stačí dohodnuté malé a doložené scénáře.
- Úklid, vrácení nebo přepsání existujících uživatelských pracovních dat a změn.

## Further Notes

- Navazuje na dokončenou [první etapu nativního OCR, issue #1](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/1) a její úkoly #2–#8. Nové GUI a skutečné řízení AI byly z první etapy výslovně odložené; tato specifikace otevírá navazující etapu.
- Výchozím stavem je současná implementace, její doménový slovník a ADR 0001–0004. Věrný obraz, zachování chyb vydavatele a samostatný OCR proces zůstávají v platnosti.
- Projekt vydání, průchod OCR, profil průchodu OCR, historie průchodu a opravný cyklus jsou odlišné pojmy; použít je konzistentně v modelu i GUI.
- Průzkum ověřil veřejnou podporu GPT-6.1 Sol high, schopnosti lokálního katalogu/protokolu a existenci integrace context-mode pro Codex. Žádný účetní přístup, inference ani finální distribuovaná sada se během návrhu netestovaly. Povinné integrační důkazy zůstávají prací implementace.
- Konkrétní verze finální distribuované sady se připnou až po integračním ověření; nezáviset na libovolné aktualizaci Codexu, nativním nightly WebUI ani runtime instalaci závislostí.
- Při změně pouze dokumentace se OCR ani AI průchody nespouštějí. Vytvoření této specifikace a issue není provedení ani ověření implementace.

Ověřené primární podklady:

- [GPT-6.1 Sol a úrovně uvažování](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
- [Možnosti a runtime požadavky pluginů](https://developers.openai.com/plugins/concepts/plugins)
- [context-mode: integrace Codexu](https://github.com/mksglu/context-mode/blob/main/README.md)
- [context-mode: podpora platforem](https://github.com/mksglu/context-mode/blob/main/docs/platform-support.md)
