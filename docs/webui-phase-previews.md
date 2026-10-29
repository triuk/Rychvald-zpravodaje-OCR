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
Fáze jsou `preparation`, `reading`, `geometry` a `assembly`; poslední tři používají
stejný prohlížeč a společný rozšiřovací bod `app.phase_preview.phase_content`.
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
