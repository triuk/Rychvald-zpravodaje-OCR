# Náhledy fází průchodu OCR

Příprava zobrazuje zdrojový sken a automaticky přidává dostupné oblasti a text
pomocného místního OCR. Žlutý překryv je kandidát, nikoli potvrzený přepis.
Náhled sám nespouští přípravu, nevytváří podklady pro AI a nemění validační stav.

V pracovní ploše je vlevo detail fáze a vpravo náhled. Dělicí příčku lze přesouvat
myší i šipkami klávesnice. Stránka a přiblížení se uchovávají pro vybraný průchod
také při přepnutí fáze nebo obnovení detailu. Tlačítko „Zvětšit náhled“ poskytne
větší pracovní plochu; Escape vrátí běžné zobrazení. Text je viditelný přímo
v překryvu, bez dalšího přepínače nebo inspektoru řádku.

## Veřejný dotaz

`Application.dispatch('phase_preview', payload)` přijímá:

```json
{"run_id":"…","edition_id":"úplný SHA-256 zdroje","phase":"preparation","page":1}
```

`edition_id` je volitelná kontrola shody s průchodem. Stránky se číslují od 1.
Fáze jsou `preparation`, `reading`, `geometry` a `assembly`; používají stejný
prohlížeč a společný rozšiřovací bod `app.phase_preview.phase_content`.
Ruční revize a Výstupy zůstávají placeholdery.

Výsledek obsahuje `state`, srozumitelné `message`, `identity` projektu, průchodu,
fáze, stránky a hashe konkrétního podkladu, počet stránek, vykreslený `image`
s datovou URL a pole `overlays`. Každý překryv má text, druh a `normalized_bbox`
v souřadnicích 0–1 zobrazené stránky. `artifacts` eviduje skutečně čtené podklady
a jejich SHA-256; jejich cesty jsou relativní k pracovní složce průchodu.

Základní stavy jsou `available`, `source_only`, `historical_missing`,
`page_missing`, `source_missing`, `artifact_invalid` a `artifact_changed`.
Chybějící historický stav se nikdy nenahrazuje současným přepisem či geometrií.
Podklad z jiného průchodu nebo zdroje se nepoužije. Kontrola hashů po čtení
odmítne smíšený pohled, pokud pracovní proces právě podklady přepsal.

Přípravný rastr již zahrnuje CropBox a rotaci PDF. Jeho pixelové oblasti se
normalizují podle skutečných rozměrů rastru, takže se rotace neuplatní podruhé.
Ověřuje se i shoda rozměrů, ořezu a rotace se zdrojovou stránkou. Náhled má
omezené rozlišení a odpovídající poměr stran; přiblížení mění jeho zobrazení.

Výběr a kořen evidence se zachytí pod aplikačním zámkem, samotné čtení a
vykreslování probíhá mimo něj. GUI pro náhled používá nezávislý veřejný požadavek,
aby neblokovalo frontu ovládacích akcí. Opožděná odpověď nepřepíše novější výběr.

## Ověření

`tests/test_webui_phase_preview.py` používá veřejné dotazy nad skutečným nativním
importem. Syntetická dvoustránková předloha má nezávisle dané obdélníky,
jiný rozměr, ořez a rotaci druhé strany. Test porovnává oblasti i barvu podkladu,
izolaci průchodů, chybějící historický stav, změněné doklady a neměnnost dat.
Další scénář provádí skutečnou místní přípravu a čte její výsledek bez nové práce.

```sh
OCR_ENVIRONMENT=/cesta/k/overenemu/environment.json \
  python -m unittest discover -s tests -p test_webui_phase_preview.py -v
DISPLAY=:91 OCR_ENVIRONMENT=/cesta/k/overenemu/environment.json \
  python tools/smoke_webui_phase_preview.py --screenshot /tmp/nahled.png
```

Nativní scénář používá skutečné WebUI a Chromium. Ověřuje viditelný text místního
OCR, přepnutí otočené/oříznuté stránky, zachování stránky a zoomu mezi fázemi,
dělicí příčku, zvětšení a neměnnost uloženého průchodu. Neodesílá AI požadavky.

Při vývoji 29. 10. 2026 prošlo pět veřejných testů a nativní scénář na izolovaném
Xvfb displeji. Použito bylo výslovně vybrané a ověřené místní testovací prostředí
`/tmp/rychvald-native-recovery/environment.json`; nejde o doklad původního
přenosného runtime ani o přijetí celého Linux balíku.

## První dokončený Přepis

Nativní `publish-reading` při prvním zveřejnění uloží samostatný archiv
`phase-previews/reading/`. Obsahuje původní přepis, návrh, doklad zveřejnění,
vstupní packet a manifest stránek. Manifest archivu váže jejich přesné hashe na
zdroj, průchod a zmrazený profil. Adresář vzniká jedním přejmenováním hotového
celku a pozdější oprava ani další zveřejnění jej nepřepisují.

Záložka Přepis čte tento archiv; nepoužívá aktuální `review.json`. Zobrazuje
původní oblasti i text automaticky nad stejným zdrojovým skenem. Průchod v
archivu musí odpovídat vybranému průchodu. Poškozený archiv se označí jako
neplatný, místo aby byl tiše nahrazen aktuálním stavem.

Starší projekt bez nového archivu může využít svůj nejdřívější dokončený
originální návrh z `application/reading-attempts`. Ověřují se hashe, původní
dokončené odpovědi a protokol, zdroj a zmrazený profil. U pokračovaného čtení
se ověřuje i zachovaný původní zdrojový tah. Chybí-li takové doklady, vrací
se `historical_missing`; dotaz nevytváří nové soubory ani AI požadavky.

`tests/test_webui_reading_preview.py` ověřuje celý veřejný průchod se skutečným
místním exportem a výslovně řízeným AI partnerem. První přepis obsahuje `AXC`,
řízená cílená oprava změní pracovní přepis na `ABC`, ale identita a obsah
původního náhledu zůstanou stejné i po restartu. Test následně ověří starší
originální doklady a jejich skutečnou nedostupnost bez fallbacku.

```sh
OCR_ENVIRONMENT=/cesta/k/overenemu/environment.json \
  python -m unittest discover -s tests -p test_webui_reading_preview.py -v
DISPLAY=:91 OCR_ENVIRONMENT=/cesta/k/overenemu/environment.json \
  python tools/smoke_webui_reading_preview.py --screenshot /tmp/prvni-prepis.png
```

Tento nativní scénář prokazuje skutečně viditelný původní text `AXC` po opravě
pracovního přepisu na `ABC`. AI partner je řízená testovací náhrada; test není
dokladem dostupnosti skutečného modelu. Ověření poškozeného staršího PDF navíc
zaručuje veřejnou chybu `preview_invalid` bez výjimky unikající do nativního
WebUI callbacku.

## První dokončené Pořadí a geometrie

Nativní `publish-geometry` uchová celý první dokončený stav v
`phase-previews/geometry/`. Stejným místem prochází běžné dokončení i obnovení
původního dokončeného pozorování po chybě místního zveřejnění. Archiv obsahuje
checkpoint, přípravu, manifest zdrojových stránek, přepis, skutečné znakové
oblasti, logické jednotky a segmentační manifest. Souborové hashe se ověřují
proti archivnímu manifestu i původně prohlédnuté geometrii.

Záložka zobrazuje původní text a čísla jeho logického pořadí. Obrys řádku vychází
ze skutečných znakových oblastí segmentace, vnitřní čárkované hranice ukazují
jednotlivé znakové buňky. U regionu bez znakových buněk je v datech výslovně
uvedeno `source_region_only`. Dostupný text ani hranice nevyžadují další přepínač
a nevytvářejí řádkový inspektor. Jde stále o aproximace: umístění oblasti není
potvrzením správného přečtení nebo identity znaku.

Opravný cyklus může změnit aktuální `reviewed-lines.json`, `pages.json` a
`geometry.json`; tento první archiv zůstává beze změny. Starší průchod bez
zachovaného prvního stavu ukazuje `historical_missing`, i když současná pracovní
geometrie existuje.

`tests/test_webui_geometry_preview.py` ověřuje nezávisle dané polohy buněk,
ořez a rotaci, rozdílné vizuální a logické pořadí, skutečný cílený opravný cyklus,
restart a obnovení původního dokončeného AI pozorování bez nového tahu.
Samostatný scénář vytvoří výsledek přes přesné uchované bajty předchozího
generujícího adaptéru a ověří jej nynějším validátorem. Změna původních
archivovaných bajtů se odmítne.

Tabulka `native/geometry-adapter-compatibility.json` obsahuje pouze výslovné
hashové páry pro tuto změnu ukládání náhledů. Nepovoluje obecnou shodu verzí
ani neoslabuje vazby na zdroj, přepis, profil, prostředí, generující kód,
očekávání nebo původní modelové doklady. Předchozí bajty adaptéru musí být
nadále zachovány v pracovním archivu průchodu.

```sh
OCR_ENVIRONMENT=/cesta/k/overenemu/environment.json \
  python -m unittest discover -s tests -p test_webui_geometry_preview.py -v
DISPLAY=:91 OCR_ENVIRONMENT=/cesta/k/overenemu/environment.json \
  python tools/smoke_webui_geometry_preview.py --screenshot /tmp/prvni-geometrie.png
```

Nativní scénář kontroluje skutečně viditelné původní `1. AXC`, pořadí a znakové
hranice po opravě pracovního přepisu na `ABC`, včetně vysvětlení aproximací.
Řízený AI partner zde opět dokládá aplikační kontrakt, nikoli dostupnost modelu.
