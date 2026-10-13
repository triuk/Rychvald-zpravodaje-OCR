# Datové smlouvy OCR běhu

Reference pro [workflow](ocr-workflow.md). Obsahové hodnoty vždy pocházejí z nového zdroje. Příklady ukazují schéma, nikoli přepis vydání. Cesty k obrazovým dokladům a kontrolám jsou relativní k aktuálnímu work; musí existovat uvnitř něj. Manifesty obsahují absolutní cesty a SHA-256.

## Přepis

`review.json`:

| Položka | Význam |
|---|---|
| `source_sha256` | Hash zdroje z nového `input-manifest.json`. |
| `lines` | Ponechané/doplněné řádky: `id`, `page`, `text`, `selection_region`, `source_crop`, `decision_basis`, `text_status`. |
| `text_status` | `visually_confirmed`, nebo `partially_unresolved` právě při výskytu `[NEČITELNÉ]`. Stav `candidate` není připraven k segmentaci. |
| `candidate_id` | Existující místní kandidát na téže stránce, nebo `null` pro vizuálně doplněný řádek. |
| `join_after` | Na každém vnitřním řádku jednotky: `space`, `typesetting_hyphen`, `literal_hyphen`, `none`. |
| `fields` | Tabulkové údaje s vlastním `text` a `bbox`; `line.text` je jejich souhrn s tabulátory. Bez `fields` se používá celý řádek. |
| `units` | Logické pořadí: `id`, `page`, `article`, `tag` (`H1/H2/P`), `line_ids`. Jednotka je stránková; každý řádek je použit právě jednou. |
| `table_fields` | Volitelný seznam hodnot jednotky pro TXT; tabulátory oddělují i prázdné buňky. |
| `dropped_candidates` | `id` a `reason` každého vyřazeného/nahraděného kandidáta. |
| `unresolved` | Jeden záznam na každý `[NEČITELNÉ]`: `id`, `line`, `page`, `bbox`, `source_crop`, `context`, `candidates`, `reason`, `status`. |
| `publisher_errors` | `line`, `printed`, `explanation`, `status` potvrzené chyby nebo podezření. Přepis zachovává tištěné znění. |
| `risk_register` | `id`, `line`, `page`, `value`, `bbox`, `source_crop`, `status` a doklad rozhodnutí o rizikovém údaji. |

Boxy jsou `[x0,y0,x1,y1]` v pixelech vlastního rastru, stránky od 1. Všechny odkazy musí být platné. `printed` se vyskytuje v příslušném řádku; `risk_register.value` odpovídá jeho údaji (mezery a tabulátory se zde pro porovnání sjednotí). Kontext nevyřešeného místa může zahrnovat sousední řádky. Validátor kontroluje ID, zařazení, pokrytí kandidátů, rozsahy, doklady a přiřazení nečitelných míst ke konkrétním řádkům; správnost čtení potvrzuje člověk/agent nad obrazem.

Příklad spojení: `kni-` / `hovna` má `typesetting_hyphen`; `česko-` / `anglický` má `literal_hyphen`. Spojovník musí být samostatnou poslední buňkou. `none` spojí části přímo, např. písmena vertikálního nápisu.

`update-line --id ID --patch FILE` přijímá objekt `line` s celým náhradním řádkem a volitelné seznamy `unresolved`, `publisher_errors`, `risk_register`. Má-li řádek související záznamy, patch musí výslovně obsahovat jejich náhrady; `[]` je vymaže. Každá náhrada se vztahuje jen k danému ID.

`update-review --patch FILE` přijímá dávku:

```json
{
  "lines": [{"line": {
    "id": "ID", "candidate_id": null, "page": 1, "text": "ZNENI ZE ZDROJE",
    "selection_region": [40, 60, 300, 90], "source_crop": "crops/NOVY_VYREZ.png",
    "decision_basis": "Skutecne cteni tohoto vyrezu", "text_status": "visually_confirmed"
  }}],
  "units": [{"id": "ODSTAVEC", "page": 1, "article": "CLANEK", "tag": "P", "line_ids": ["ID"]}]
}
```

`lines` je seznam patchů stejného tvaru jako pro `update-line`; nový řádek lze doplnit s `candidate_id: null` a skutečným vizuálním dokladem. `units` nahrazuje celé pořadí jednotek. Volitelný `drop_lines` je seznam ID k vyřazení a `dropped_candidates` nahrazuje registr vypořádání kandidátů. Před vyřazením řádku se související registry výslovně vyprázdní v jeho patchi; zbývající reference nebo nezdůvodněné vyřazení kandidáta validátor odmítne.

Oba příkazy ověří celý výsledek před jediným atomickým zápisem, uchovají původní přepis v `review-history/` a očekávání testů ponechají samostatná. Neplatná dávka nezmění přepis ani historii. Stdout obsahuje jen cesty a stručnou validaci.

## Geometrie

Výjimky patří do příslušného pole řádku (`fields`; u běžného textu přidej jedno pole se stejným textem a boxem):

| Klíč | Význam |
|---|---|
| `token_boxes` | Index tokenu → box tokenu. Má přednost před dalším automatickým zúžením/výškovou úpravou. |
| `placeholder_surrogates` | Index tokenu → náhrada nejisté části pro poměrný odhad šířky, např. `00`; odpovídá obrazovému rozsahu. |
| `piece_boxes` | Index tokenu → index části kolem `[NEČITELNÉ]` → box části. |
| `character_boxes` | Klíč `token:část:znak` → box znaku nad původním tiskem. |

Indexy jsou od 0; JSON klíče jsou řetězce. Přítomnost výjimky nepředstavuje potvrzení geometrie. Placeholder má stav `region_only`; jeho písmena nejsou jednotlivými tištěnými znaky. Běžné mezery mají krátké explicitní buňky, které netvoří mosty přes sloupce.

`segment-manifest.json` váže segmentaci na přepis, kandidáty, rastry, font a kód. Po změně těchto vstupů spusť segmentaci znovu. `pages.json` neupravuj jako další zdroj pravdy; opravy geometrie patří do review.

## Kontroly

`samples.json` je neprázdný seznam `id`, `page`, `bbox`, `expected`, `expected_origin`, vhodně i `source_crop`. ID používají písmena ASCII, číslice, `_` a `-`. Očekávání a oblast jsou odvozené z původního rastru před exportem. `sample-sheets` uloží původní výřezy s okolím a vyznačeným obdélníkem i přehledy do verzovaného adresáře `checks/sample-source/HASH/`; `checks/sample-source.json` eviduje jejich vstupy. Čtenář potvrzuje, zda oblast zahrnuje správné znaky.

Export zmrazí celou sadu v `export-inputs.json` a její hash v `output-manifest.json.inputs.samples`. `checks/geometry-samples.json` obsahuje `inputs` s hashi PDF/očekávání/manifestu a `samples` s doslovnými výsledky obou extraktorů. Validace požaduje stejnou sadu jako při exportu; změnu očekávání nezlegalizuje opakované spuštění `samples`. Kontrola znaků odstraňuje whitespace; doslovné odstavce a volitelné UI mají samostatné testy.

Vizuální report `checks/visual-review.json` vyplňuje skutečný čtenář po exportu:

```json
{
  "source_sha256": "HASH_ZDROJE",
  "pdf_sha256": "HASH_PDF",
  "review_sha256": "HASH_AKTUALNIHO_REVIEW",
  "reviewer": "Kdo provedl čtení",
  "pages_reviewed": [1],
  "evidence": ["visual-review.md"],
  "geometry_status": "approximation_requires_character_review"
}
```

`pages_reviewed` pokrývá všechny stránky skutečného dokumentu. Evidence popisuje přečtené bloky, rizikové údaje, prohlédnuté překryvy a dotčené opravy. `geometry_status: visually_verified` použij jen při skutečně dokončené kontrole geometrie; jinak eviduj nález `geometry/approximation` i jednotlivá konkrétní rizika.

`checks/findings.json` obsahuje identitu aktuálního výstupu a jednotlivé otevřené nálezy:

```json
{
  "source_sha256": "HASH_ZDROJE",
  "pdf_sha256": "HASH_PDF",
  "items": [
    {"id": "sample/ID_VZORKU/mupdf", "status": "open",
     "reason": "Výběr přibral znak sousedního řádku",
     "evidence": ["checks/geometry-samples.json", "checks/ID_VZORKU-source.png"]}
  ]
}
```

ID z automatických kontrol: `sample/ID/mupdf`, `sample/ID/poppler`, `literal/STRANA/mupdf`, `literal/STRANA/poppler`, `geometry/approximation`, `clipboard/ID`. Každý neúspěch má vlastní důvod a existující doklad. Souhrnná výjimka „vše přijatelné“ nenahrazuje jednotlivé záznamy. Nevyřešená čtení se přebírají přímo z review.

Po změně PDF znovu proveď kontroly a přiřaď nálezy k novému hashi až po jejich opětovném posouzení. Staré reporty, stará schránka a starý vizuální závěr nejsou potvrzením nové iterace. Technické podmínky zachování zdroje/obrazu, integrity, textových znaků a struktury nemají výjimku přes findings.

`reports` připraví vizuální šablonu s `reviewer: null`, prázdným `pages_reviewed` a jednotlivé nálezy s `reason: null`. Doplnění vypíše do `checks/report-todo.json`. Důvody i skutečné vizuální závěry doplní čtenář. Při stejném exportu se již doplněné záznamy zachovají; pro jiný export příkaz požaduje `--reset`, který staré reporty uchová v `checks/report-history/`. Automaticky připravené ID ani doklad z kontrol nejsou potvrzením správnosti nebo přijetím nálezu.

## Schránka

Zkouška skutečného výběru a schránky je volitelná. Při běžném OCR průchodu nejsou čtečka, inventář prostředí, ruční případy ani `checks/manual-copy/status.json` povinné. Chybějící report nebo `not_tested` se v souhrnu eviduje jako neprovedený volitelný rozsah a nevytváří otevřenou položku.

Pokud zkoušku plánuješ, zaznamenej čtečku/způsob ovládání podle dostupnosti a před exportem vytvoř nový `clipboard-cases.json` z původního rastru:

```json
{
  "expected_origin": "Kdo přečetl které původní výřezy",
  "required_cases": [],
  "cases": [
    {"id": "single-letter", "selection": "Jedno samostatné písmeno podle zdroje", "expected": "F"},
    {"id": "cross-page-paragraph", "result": "not_applicable", "reason": "Žádný odstavec nepokračuje přes stránku"}
  ]
}
```

Příklad ukazuje schéma, nikoli očekávání k přenosu. `clipboard-expectations --cases FILE` zapíše přesné bajty `expected.encode('utf-8')`, bez přidaného posledního LF. Novou verzi uloží do `checks/manual-copy/expectations/HASH/` a vytvoří `clipboard-expectations.json` s identitou zdroje, popisem původu a `expected_file`/`expected_sha256` každého proveditelného případu. Původní verze se nepřepisují. Export zmrazí manifest v `export-inputs.json.clipboard_expectations` a váže hashe všech očekávaných souborů. Změna očekávání podle nového čtení předlohy vyžaduje novou verzi a exportní iteraci.

`reports` připraví `checks/manual-copy/status.json` z této zmrazené verze, doplní hash PDF a nechá případy `not_tested`. Při skutečné zkoušce doplň `reader`, `version`, `os`, `actual_clipboard_file` a `result`. Zachovej původní `expected_origin`, popis `selection`, cestu i hash očekávání; validátor je srovná se zmrazenými údaji.

Zvol relevantní případy podle [metodiky kopírování](pdf-copy-compatibility.md#návrh-kontrol-kopírování), například celou první stranu, víceřádkový odstavec, dvě sousední odstavcové jednotky a pokračování přes sloupec. `required_cases` určuje pokrytí zvolené sady, ne povinnost provést UI při OCR. Nepřítomný jev může mít `not_applicable` s důvodem; nezařazuj jej do `required_cases`.

Validace se řídí stavem případu:

- `not_applicable`: nepovinný případ a důvod; soubor očekávání ani výběr se nevyžaduje.
- `not_tested`: neprovedená volitelná zkouška; nevytváří otevřenou položku.
- `pass`/`fail`: zmrazené očekávání, skutečná čtečka, verze, OS a soubor doslovného výsledku. Srovnání probíhá po bytech včetně whitespace. `fail` vyžaduje vlastní otevřený nález `clipboard/ID`; volitelnost zkoušky nezakrývá nalezené selhání.

Zaznamenej skutečný rozsah; jedna čtečka nedokládá kompatibilitu ostatních.

## Iterace a souhrn

`snapshot` uchovává PDF/TXT, zmrazený přepis, exportní očekávání, manifest, konstrukci a kontroly. Velké rastry/OCR/výřezy se nekopírují; jsou součástí předávaného work a snapshot eviduje jejich hashe. `snapshot.json` rozlišuje uložené a sdílené artefakty. Při změně kandidátních výřezů zachovej předchozí doklad pod novým ID.

`validate-run` požaduje povinné technické, výběrové a vizuální reporty a odmítá zastaralé vstupy i chybějící reference. Report schránky je volitelný. Vrací `failed`/1, `ready_with_open_items`/2 nebo `verified`/0 a ukládá `checks/run-validation.json` i stručný `checks/run-summary.md`. Pole `ui_clipboard` obsahuje `optional: true`, stav `not_tested`/`tested` a skutečně provedená `tested_cases`. Neprovedená schránka je slučitelná s `verified`/0; ten dokládá pouze zaznamenaný rozsah. Přijetí konkrétního OCR PDF zadavatelem je samostatné.
