# Cílené čtení a bezpečné opravy

Dotazy a opravy projektu používají standardní knihovnu a stejné datové smlouvy
jako dosavadní [OCR workflow](ocr-workflow.md). Nevyžadují načtení OCR runtime
ani přenos celého přepisu do odpovědi.

```bash
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json query PROJECT_ID transcript --page 2 --limit 10
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json query PROJECT_ID transcript --id LINE_ID --text-bytes 128
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json query PROJECT_ID units --article ARTICLE_ID
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json query PROJECT_ID candidates --offset 0 --limit 20
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json query PROJECT_ID findings
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json patch PROJECT_ID --patch '/cesta/dávka oprav.json'
python3 tools/ocr_projects.py --root '/cesta/archiv vydání' --json patch PROJECT_ID --id LINE_ID --patch '/cesta/oprava řádku.json'
```

## Dotazy

Pohledy jsou `transcript`, `candidates`, `findings`, `unresolved`,
`publisher-errors`, `reconstructions`, `units`. Kandidáti zahrnují celostránkové
řádky, jednotlivé PSM průchody, místní oblasti a cílené varianty; každá položka
rozlišuje `candidate_kind`. Tištěná chyba vydavatele, návrh rekonstrukce a
nevyřešené místo zůstávají samostatné záznamy s původním významem a stavem.

Filtry `--page`, opakované `--id` a `--article` vybírají příslušné řádky.
`--offset` se vztahuje k filtrovanému seznamu; `--limit` je horní mez položek.
Odpověď obsahuje `counts.total`, `counts.matched`, `counts.returned`, `rows`,
`next_offset` a explicitní `limits`. Pokračuj přes vrácený `next_offset`, dokud
není `null`; skutečný počet řádků může být menší kvůli limitu bajtů.

Protokol verze 1 vrací jeden platný JSON do **4096 bajtů UTF-8 včetně LF**.
`--text-bytes` omezuje náhled každého textového pole na 0–512 bajtů (výchozí 256).
`text_bytes` uvádí původní velikost, `text_truncated` a `truncated_fields`
odlišují zkrácené náhledy. Je-li celá položka příliš velká, `omitted_fields`
výslovně vyjmenuje vynechané detaily. JSON se nikdy neřeže jako řetězec.

Každý řádek obsahuje `artifact.path` relativní ke kořenu a JSON Pointer
`artifact.pointer` k úplnému záznamu. U doslovného TXT průchodu je pointer `null`
a celý text je v daném souboru. `source` odkazuje na zdrojový sken, případný
rastr, výřez a doklady. Výřezy/doklady musí zůstat uvnitř pracovního prostoru.
Samotný odkaz nepotvrzuje, že obraz někdo přečetl.

Předchozí odvozené doklady jsou po opravě dostupné pro porovnání, ale dotaz je
označí `stale_for_current_review`. Vazba nového segmentačního/exportního
manifestu na aktuální hash přepisu tuto zastaralost odstraní pro příslušnou
sadu artefaktů. Dotaz nemění přepis, nálezy ani vizuální report.

## Opravy

`patch --patch FILE` přijímá přesně dosavadní dávkový formát `update-review`:
`lines`, `drop_lines`, `units`, `dropped_candidates`. `--id LINE_ID` používá
formát `update-line`: celý náhradní `line` a související registry. Pravidla
explicitního nahrazení registrů, nečitelných míst, zařazení kandidátů, jednotek,
obrazových dokladů a polí jsou v [datové smlouvě](ocr-data-contracts.md#přepis).

Projektový Linux zámek chrání celý zápis. Nejdříve se sestaví a ověří **celá**
výsledná dávka, včetně vazby ke zdroji projektu. Teprve poté se původní doslovné
bajty přepisu uloží do `review-history/SHA256.json` a nový přepis zveřejní jedním
atomickým přejmenováním. Neplatný patch ponechá přepis, historii, metadata a
nezávislá očekávání beze změny. Souběžný zapisovač dostane `project_busy`;
dotazy mohou dál číst poslední kompletní přepis.

Platná změna nastaví `phase: review_updated`, `validation: not_run` a uloží
`review-invalidation.json`. Ten váže předchozí/aktuální hash přepisu, dotčené
řádky a stránky, změnu pořadí jednotek a seznam přítomných odvozených artefaktů
s jejich hashi. Odvozené soubory a staré reporty se zachovají pro porovnání;
jejich dosavadní hashové vazby odmítnou použití se změněným přepisem. Přepočti
segmentaci, export a příslušné kontroly podle workflow. OCR cache, vstupní
rastry, výřezy, historie, `samples.json`, očekávání schránky a nepříslušné
reporty se nepřepisují ani nezneplatňují.

Oprava sama nevytvoří vizuální potvrzení, obsahový úspěch ani přijetí uživatelem.
`text_status` a `decision_basis` musí pocházet z výslovně dodaného obrazového
čtení. Návrh se automaticky nepromění v potvrzený přepis.

Další stabilní chyby jsou `artifact_missing`, `artifact_invalid`,
`invalid_selection`, `patch_invalid` a `project_busy`; chyba má návratový kód 1
a běžnou verzovanou JSON obálku bez diagnostického textu na stdout.

## Rozhraní pro navazující operace

```python
query_project(registry, project_id, view, *, page=None, ids=None, article=None,
              offset=0, limit=10, text_bytes=256)  # úplná malá obálka protokolu
patch_project(registry, project_id, patch, *, line_id=None)  # aktuální record
stale_artifacts(work)  # zachované artefakty zastaralé pro aktuální přepis
```

Funkce jsou v `tools/ocr_project_review.py`. Validátory zůstávají v
`ocr_quality.py`; `patched_review(review, patch)` používá stejnou dávkovou
transformaci jako dosavadní `update_review`, `validate_review` ověřuje celý
výsledek a `save_review` uchovává přesné předchozí bajty.
