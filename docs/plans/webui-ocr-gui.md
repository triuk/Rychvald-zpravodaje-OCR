# WebUI pro řízení a analýzu OCR — návrhový rozhovor

Stav k 14. 10. 2026: návrhový rozhovor je uzavřený. Zadavatel přijal Q36
a zadal syntézu a publikaci pomocí `to-spec`. Podpora GPT-6.1 Sol high
a context-mode z Q35 je závaznou podmínkou přijetí implementace.
Implementační zadání je v [potvrzené specifikaci 0002](../specs/0002-webui-ocr-orchestration.md).
Publikováno jako [GitHub issue #9](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/9)
se štítkem `ready-for-agent`; zveřejněné znění a štítek byly zpětně ověřeny.
Číslování pokračuje po Q18 předchozího návrhu.

## Zadání

Zadavatel požaduje Linux aplikaci s GUI pomocí WebUI podle projektu
`example-webui-python`. Nynější prioritou je vyladění automatického OCR;
později se má workflow začlenit do `pdf-ocr-reviewer`.

Vlevo mají být projekty jednotlivých PDF s postupem podle logických
checkpointů. Rozhraní má odlišovat místní výpočty a práci AI, zpřístupnit
AI prompt a přehledně ukazovat délku běhu, spotřebu tokenů ve třech částech
a barevné vyjádření ceny. Rozdělení tokenů a význam ceny určuje Q20/Q22;
podrobnosti zobrazení zůstávají otevřené.

## Ověřený výchozí stav

- Pojem **Projekt vydání** označuje životní cyklus jednoho zdrojového PDF
  včetně OCR a následné ruční revize (`GLOSSARY.md`). Implementace ale váže
  `project_id` na `run_id`; explicitní nový průchod vytváří další projektový
  záznam (`tools/ocr_projects.py`). Q21 potvrzuje zobrazení jednoho vydání
  s podřízenými průchody; konkrétní kompatibilní převod současných záznamů
  bude součástí další specifikace.
- Existují místní operace importu, seznamu, stavu, přípravy, dotazů, oprav,
  exportu, validace a pokračování. Nižší workflow poskytuje další pracovní
  kroky. Úplné vizuální čtení, rekonstrukce a další úsudky dosud provádí
  externí agent/čtenář podle `docs/ocr-workflow.md`.
- Není implementován klient Codex app-server ani ukládání promptů, skutečné
  spotřeby AI, cen nebo časů jednotlivých kroků. Předchozí návrh app-server
  doporučuje pro navazující etapu (`docs/reviewer-ocr-integration.md`).
- Obnova a ověřovaná cache pokrývají především přípravu: rastry stránek
  a jednotlivé kandidátní OCR průchody. Nejde zatím o obnovu celého AI cyklu.
- Stav rozlišuje fázi, běžící operaci, validaci a přijetí zadavatelem.
  Úspěšný příkaz nebo export nejsou potvrzení správnosti přepisu.
- Stávající CLI vydává po dokončení jeden strojový JSON do 4096 bajtů.
  Živé události potřebují kompatibilní rozšíření; nesmějí narušit stdout
  protokol (`docs/project-registry.md`).
- OCR má vlastní přenosný adresářový balík se spouštěčem, Pythonem a nativními
  prostředky. Deklarovaný základ je Linux x86_64-v3 s vlastním glibc 2.44,
  Pythonem 3.14.7 a kernelem nejméně 6.1; univerzální Linux kompatibilita
  není ověřená (`docs/linux-bundle.md`).
- `example-webui-python` ukazuje Python callbacky, malé odpovědi a průběžné
  aktualizace ze samostatného vlákna. Reviewer již používá WebUI i Linux
  sestavení PyInstaller do jednoho souboru; má oddělený backend a UI.
- Reviewerův manifest obsahuje ruční revizi, nikoli historii OCR operací.
  Jeho současné API nemá spouštění ani rušení OCR. Dlouhá OCR operace uvnitř
  synchronního callbacku by blokovala obsluhu UI.
- Doplňující průzkum: samotné připnutí `webui2==2.5.8` nepřipíná nativní
  knihovnu WebUI. Bootstrap při jejím chybění používá proměnlivé `nightly`.
  Dosavadní požadavek reprodukovatelného nativního prostředí proto vyžaduje
  přibalit konkrétní ověřenou knihovnu a evidovat její hash; běh GUI nic
  nestahuje. `show()` může použít prohlížeč nebo systémový WebView; podpora
  konkrétního režimu se dokládá integračním testem, nikoli přítomností metody.
- Doplňující průzkum Codex protokolu: lokálně instalovaný Codex
  `0.162.0-alpha.17.2` má veřejnou událost `thread/tokenUsage/updated`
  s identitou vlákna/tahu a poli `last` a `total`. Veřejná dokumentace
  neurčuje `last` jako součet celého tahu; nelze takto pole prezentovat
  ani opakovaně sčítat kumulativní snímky. Přiřazení spotřeby řízeným
  krokům vyžaduje integračně ověřit rozdíly kumulativních hodnot, obnovení,
  přerušení a opožděné události. Interní/experimentální raw response události
  nejsou podkladem pro slib přesných metrik každého interního volání modelu.
  Offline generování schémat neprovádělo přihlášení ani AI tah.

## Dosavadní rozhodnutí a možné střety

- ADR 0001 zachovává obraz skenu; ADR 0002 zachovává chyby vydavatele
  s oddělenou evidencí. GUI ani automatizace je samy o sobě nemění.
- ADR 0003 zachovává OCR jako oddělený nativní proces kvůli nezávislým runtime
  závislostem OCR a revieweru. WebUI může tento proces ovládat; sloučení obou
  do jednoho runtime by vyžadovalo znovu otevřít toto rozhodnutí.
- Specifikace `docs/specs/0001-native-ocr-environment.md` odkládá GUI, AI
  integraci a tokenové metriky do další etapy. Aktuální zadání tuto etapu
  otevírá; nejde o implicitní součást hotové první etapy.
- Úplné první vizuální čtení, samostatné povinné kontroly a oddělené přijetí
  zadavatelem zůstávají požadavkem. Automatické dokončení operace nesmí
  vytvářet neprovedené vizuální doklady nebo souhlas zadavatele.
- Q23 volí spustitelné GUI s přibaleným OCR adresářem; jediný fyzický
  soubor pro celé OCR pracoviště není podmínkou této etapy.
- Dosavadní směr nepočítá s novými placenými OCR službami; případný nový
  poskytovatel nebo API režim musí být výslovně vybrán.

## Strom nových rozhodnutí

### Potvrzené první kolo

Zadavatel přijal doporučení pro všech šest otázek:

- **Q19 — Rozsah automatizace:** GUI řídí celý průchod od importu přes
  místní OCR, vizuální čtení a rekonstrukci AI až po export a kontroly.
  Výsledek je připraven k následné ruční revizi; jeho přijetí zadavatelem
  zůstává samostatné.
- **Q20 — Přístup k AI:** místní Codex app-server s přihlášením účtem
  ChatGPT. Případná cena podle API sazeb je výslovně srovnávací odhad,
  nikoli částka skutečně účtovaná za tento běh v rámci předplatného.
- **Q21 — Vydání a průchody:** jeden projekt vydání v levém sloupci,
  uvnitř pojmenované průchody OCR a jejich historie. Různý obsah se stejným
  názvem zůstává rozlišený.
- **Q22 — Tři části tokenů:** necacheovaný vstup, cacheovaný vstup a výstup;
  dostupné podrobnosti uvažování mohou být navíc bez dvojího započtení.
- **Q23 — Distribuce:** spustitelné GUI s přibaleným ověřeným OCR adresářem;
  první ověření na současné podporované platformě Linux x86_64-v3.
- **Q24 — Analytický cíl:** živé sledování, trvalá historie a porovnání
  průchodů stejného vydání. Základní scénář přijetí: porovnat dva průchody
  stejného PDF; u kroků dohledat místní/AI práci, prompt, dobu, tokeny,
  srovnávací odhad ceny a výsledky kontrol kvality.

Q20 doplňuje ADR 0004. Rozlišení projektu vydání a průchodu OCR je zachycené
v `GLOSSARY.md`; nemění samo o sobě identifikátory stávajících dat.

### Potvrzená rozhodnutí druhého kola

- **Q25 — Checkpointy a podrobnost průběhu:** checkpoint je uložený,
  ověřený bod, odkud lze pokračovat. Hlavní milníky: příprava → vizuální
  přepis a rekonstrukce → pořadí článků a geometrie → export → kontroly
  a opravy → předání k revizi. Detail rozbalí místní a AI kroky; měřitelné
  jednotky ukážou počty dokončených stránek/úloh, AI také stav a čas.
  Dokončení checkpointu potvrzuje kontrola jeho podkladů.
- **Q26 — Fronta a souběh:** první verze má jeden aktivní průchod
  a ručně řaditelnou frontu. Vydání čekající na doplnění uvolní místo dalšímu.
- **Q27 — Životní cyklus:** pozastavení dokončí právě rozpracovanou jednotku
  a další nezačne. Přerušení ukončí běžící práci a zachová platné výsledky.
  Zavření aplikace přeruší zpracování a uloží stav; po novém spuštění se
  nabídne pokračování od posledního ověřeného bodu. Přerušený AI krok může
  vyžadovat nový pokus; jeho již spotřebované tokeny zůstávají v historii.
- **Q28 — Nevyřešená místa:** v této etapě žádný formulář pro ruční doplnění
  nebo opravu znění. Ruční práci řeší `pdf-ocr-reviewer`; zde zadavatel
  kontroluje kvalitu automatické části. Nevyřešená místa a jejich doklady
  se uchovají a předají k revizi; jejich přítomnost se nezamění za selhání
  dokončení ostatních vydání ani za potvrzení správného čtení.
- **Q30 — Cena a barvy:** stálé barvy tří tokenových kategorií a samostatná
  intenzita podle odhadované ceny kroku. Porovnávané průchody používají
  stejnou škálu. Číselně cena kroku, celého průchodu a přepočet na stránku;
  chybějící měření jsou nedostupná, nikoli nula.

### Potvrzená upřesnění druhého kola

- **Q29 — Prompty a nastavení:** externě spravované pojmenované profily
  obsahují prompty a parametry průchodu (například DPI rastru, jazyk místního
  OCR, model AI a míru uvažování). Zadavatel je může upravovat konzultací
  s AI v jiném okně. GUI umožní profil vybrat a prohlédnout jeho obsah;
  průchod uchová přesnou kopii použitých promptů a parametrů. Upravený
  profil se použije pro další průchod.
- **Q31 — Automatické opravné iterace:** rekonstrukce špatně čitelného textu
  patří do prvního čtení. Následné cílené cykly řeší nálezy nad přepisem,
  pořadím čtení či geometrií, znovu exportují a opakují dotčené kontroly.
  Po prvním kompletním výsledku proběhnou nejvýše tři takové cykly;
  opakování stejného neúspěchu je zastaví dříve. Nevyřešené čtení se předá
  revieweru. Technické závady nástrojů nebo prostředí se samostatně hlásí
  k vyřešení. Čitelné chyby vydavatele se zachovávají podle ADR 0002.
- **Q32 — Kontrola kvality automatické části:** zde souhrny kontrol,
  nálezy a tlačítka pro otevření PDF či příslušných podkladů v externím
  nástroji. Vložený náhled bude až po propojení s `pdf-ocr-reviewer`, kde
  se PDF již zobrazuje. Ruční úpravy jsou podle Q28 mimo tuto etapu.

### Upřesnění pořadí exportu a kontrol

První kompletní OCR PDF se sestaví po přípravě přepisu a geometrie celého
vydání, před závěrečnými kontrolami. Stávající `export_project` provádí
segmentaci, diagnostické obrázky, export plného PDF/TXT, technické kontroly,
výběrové geometrické kontroly a reporty (`tools/ocr_project_export.py`).
Kontroly otevírají skutečné PDF, extrahují jeho text a porovnávají rendery
a výběry (`tools/ocr_workflow.py`). Opravný cyklus vytváří další plnou
exportní iteraci; předchozí PDF/TXT, zmrazené podklady a kontroly se zachovají.
Průběžně ukládané rastry, výřezy a diagnostické listy jsou pracovní podklady.
Dokončení exportu a výsledek následných kontrol zůstávají rozdílné stavy.

### Třetí kolo

- **Q33 — Potvrzeno, podklady nového srovnávacího průchodu:** použít
  ověřenou místní přípravu se shodnými vstupy a parametry, AI spustit znovu
  s vlastním kontextem bez přebírání předchozích AI výsledků. Pokračování
  stejného přerušeného průchodu naopak zachová jeho dokončené AI kroky.
  Historie rozliší převzaté podklady a nově spočítanou práci.
- **Q34 — Potvrzeno, nedostupnost AI a chyby fronty:** vyčerpání limitu,
  ztráta přihlášení nebo nedostupnost AI pozastaví frontu, zachová stav
  a zobrazí důvod. Po obnovení dostupnosti se nabídne pokračování; u již
  odeslané úlohy se nejprve zjistí její skutečný stav. Chyba konkrétního PDF
  se zaznamená u vydání a fronta pokračuje dalším.
- **Q35 — Podmíněně potvrzeno, distribuce Codexu:** přibalit konkrétní
  ověřenou verzi app-serveru s přístupem přes účet ChatGPT, pokud podporuje
  přesně `gpt-6.1-sol`, úroveň uvažování `high` a `context-mode`.
  Tento požadavek zadavatel výslovně přidal; nesmí se potichu nahradit jiným
  modelem, úrovní nebo běžným během bez context-mode. Podpora modelu
  v protokolu, dostupnost pro přihlášený účet a funkčnost context-mode
  v distribuovaném prostředí jsou samostatné ověřovací podmínky.

### Výsledek průzkumu podmínky Q35

Oficiální dokumentace GPT-6.1 Sol uvádí `high`; lokální neautentizační katalog
obsahuje model `gpt-6.1-sol`, tuto úroveň i obrazové vstupy. Offline schéma
Codexu `0.162.0-alpha.17.2` má pro tah explicitní `model` a `effort`.
Žádný AI tah ani přihlášení během průzkumu neproběhly; oprávnění konkrétního
účtu a funkce finální přibalené sady proto zatím nebyly prokázány.

Instalovaný context-mode 1.0.169 obsahuje Codex MCP konfiguraci a šest
vlastních hooků. Potřebuje Node.js >=22.5.0, SQLite FTS5 a funkční požadované
runtime prostředky. Hooková detekce vyžaduje dostupný správný `codex` na
procesové cestě a verzi alespoň 0.141.0; nedůvěryhodné hooky se mohou
přeskočit. Registrace MCP sama o sobě nestačí. Balík musí předem obsahovat
funkční závislosti bez runtime instalací, ověřit důvěru/spuštění hooků,
směrování rozsáhlého výstupu, obnovu a izolaci kontextu jednotlivých průchodů.
Nebyla nalezena pevná překážka, která by tuto kombinaci vylučovala;
úplná podpora zůstává povinným integračním důkazem pro přijetí výsledku.

### Závěrečné potvrzení návrhu

- **Q36 — Podmínky přijetí a společné porozumění:** návrh je sjednocen
  v [implementační specifikaci 0002](../specs/0002-webui-ocr-orchestration.md).
  Potvrzená matice B1–B9 vyžaduje samostatný balík, skutečný GPT-6.1 Sol high
  s funkčním context-mode, úplný malý syntetický AI průchod, malou skutečnou
  obtížnou předlohu, porovnání průchodů, obnovu/frontu, pravdivé metriky,
  omezené opravné cykly a zachování starších dat/CLI i hranice revieweru.
  Zadavatel ji přijal a zadal publikaci specifikace. Dosavadní průzkum
  tyto implementační podmínky nevykazuje jako již splněné.

Detaily řízení běhu, oprávnění nad projektovými daty, kompatibility,
desktopových závislostí a ověření dostupných metrik jsou zahrnuté
v potvrzené specifikaci. Testovací hranice používá veřejné operace,
dotazy, události a artefakty aplikace používané také GUI, se zachováním
stávajícího procesového rozhraní OCR. Potvrzení a publikace specifikace
samy nejsou zadáním začít implementaci.

## Podklady

- `GLOSSARY.md`, `docs/adr/0001-zachovat-obraz-skenu.md`,
  `docs/adr/0002-verne-zneni-a-evidence-chyb.md`,
  `docs/adr/0003-native-ocr-process.md`.
- `docs/specs/0001-native-ocr-environment.md`, `docs/ocr-design.md`,
  `docs/reviewer-ocr-integration.md`, prováděcí a datové dokumenty OCR.
- Implementace a testy nástrojů `tools/ocr_projects.py`,
  `tools/ocr_project_prepare.py`, `tools/ocr_project_review.py`,
  `tools/ocr_project_export.py`, `tools/ocr_workflow.py`, `tools/ocr_bundle.py`.
- Sousední `example-webui-python` a `pdf-ocr-reviewer`, zejména WebUI backend,
  sestavení a smlouva manifestu revieweru.
- Aktuálně ověřená oficiální dokumentace:
  [Codex App Server](https://learn.chatgpt.com/docs/app-server),
  [Authentication](https://learn.chatgpt.com/docs/auth).
- Primární podklady WebUI:
  [Python wrapper a bootstrap](https://github.com/webui-dev/python-webui/tree/f62a965f8941b4875e0c53770a90bd7b76bf98a9/PyPI/Package/src/webui),
  [nativní implementace](https://github.com/webui-dev/webui/blob/efac0e24dd4e6199dd7308c485906c90fb8816a2/src/webui.c).

GitHub CLI `gh` není v dostupném prostředí nainstalované. Při publikaci byl
proto použit připojený GitHub konektor. Ověřeno uzavřené issue #1 i jeho
závěrečný komentář potvrzující dokončení první etapy a úkolů #2–#8;
vyhledání před publikací nevrátilo duplicitní WebUI issue.
