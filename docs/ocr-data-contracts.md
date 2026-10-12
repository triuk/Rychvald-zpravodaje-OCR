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

`update-line --id ID --patch FILE` přijímá objekt `line` s celým náhradním řádkem a volitelné seznamy `unresolved`, `publisher_errors`, `risk_register`. Má-li řádek související záznamy, patch musí výslovně obsahovat jejich náhrady; `[]` je vymaže. Každá náhrada se vztahuje jen k danému ID. Chybějící reference odmítne před zápisem, celý review zapíše atomicky a očekávání testů ponechá samostatná. Změny jednotek a pořadí proveď přímo v review a pak validuj celek.

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

`samples.json` je neprázdný seznam `id`, `page`, `bbox`, `expected`, `expected_origin`, vhodně i `source_crop`. Očekávání a oblast jsou odvozené z původního rastru před exportem. `checks/geometry-samples.json` obsahuje `inputs` s hashi PDF/očekávání/manifestu a `samples` s doslovnými výsledky obou extraktorů. Kontrola znaků odstraňuje whitespace; UI a doslovné odstavce mají samostatné testy.

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

## Schránka

Na začátku zaznamenej dostupné čtečky a způsob ovládání do `checks/readers.md`. Před exportem připrav očekávání z nového rastru. Pro finální PDF vytvoř `checks/manual-copy/status.json`:

```json
{
  "source_sha256": "HASH_ZDROJE",
  "pdf_sha256": "HASH_PDF",
  "reader": "Název skutečně testované čtečky",
  "version": "Její verze",
  "os": "Systém",
  "expected_origin": "Kdo přečetl které původní výřezy",
  "reason": "UI není dostupné; případy předány člověku",
  "required_cases": ["cross-column-paragraph"],
  "cases": [
    {"id": "first-page", "expected_file": "checks/manual-copy/first-page-expected.txt",
     "selection": "Celý text první strany", "actual_clipboard_file": null,
     "result": "not_tested"}
  ]
}
```

Doplň případy `multiline-paragraph`, `two-adjacent-paragraphs` a `cross-column-paragraph`, pokud se pokračování přes sloupec vyskytuje. U nepřítomného jevu může být `not_applicable` s důvodem; nezařazuj jej do `required_cases`. Podle dokumentu přidej pokračování přes stránku a obtížné výběry podle [kompatibility](pdf-copy-compatibility.md#návrh-kontrol-kopírování).

`pass`/`fail` vyžaduje skutečnou čtečku, verzi, OS, popis výběru a soubor doslovného výsledku. Validace srovná UTF-8 soubory po bytech včetně whitespace. `fail` vyžaduje také vlastní otevřený nález. `not_tested` má důvod a zůstává viditelný. Zaznamenej dostupný rozsah; jedna čtečka nedokládá kompatibilitu ostatních.

## Iterace a souhrn

`snapshot` uchovává PDF/TXT, zmrazený přepis, exportní očekávání, manifest, konstrukci a kontroly. Velké rastry/OCR/výřezy se nekopírují; jsou součástí předávaného work a snapshot eviduje jejich hashe. `snapshot.json` rozlišuje uložené a sdílené artefakty. Při změně kandidátních výřezů zachovej předchozí doklad pod novým ID.

`validate-run` požaduje reporty z nového schématu a odmítá zastaralé vstupy i chybějící reference. Vrací `failed`/1, `ready_with_open_items`/2 nebo `verified`/0 a ukládá `checks/run-validation.json`. Ověření se vztahuje pouze na zaznamenaný rozsah. Přijetí konkrétního OCR PDF zadavatelem je samostatné.
