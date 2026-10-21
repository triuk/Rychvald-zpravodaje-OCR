# Porovnání průchodů a převzatá místní příprava

V horním panelu vyberte dva pojmenované průchody stejného vydání. Druhý
výběr nabídne jen průchody se shodným úplným SHA256 zdrojového PDF. Porovnání
ukáže přesné uložené profily a prompty, jejich hashe, fázi, validaci, přijetí,
časy, tokeny, cenu, původ místních jednotek, historii a nálezy. Podklady
jednotlivého kroku obsahují původní zadání, odpověď a události. Čtení porovnání
nespouští AI ani nemění vybraný pracovní průchod. Data zůstávají v evidenci
a lze je načíst po restartu.

Oba sloupce mají společné barvy tokenových kategorií a cenovou škálu. Každý
průchod zachovává svůj zmrazený ceník; různé ceníky se výslovně označí.
Srovnávací ceny API nejsou účtováním předplatného ChatGPT. Neznámá nebo
neúplná spotřeba se nevydává za nulu. Místní časy měří skutečnou práci
aktuálního pokusu včetně ověření a kopírování; původní výpočet dárce se
nepřičítá. Původy jednotek v přehledu jsou počty ukončených místních operací
napříč pokusy; opakované použití má vlastní historickou událost.

Při místní přípravě nebo spuštění celého nového průchodu lze vybrat jiný
pojmenovaný průchod stejného vydání jako dárce. Přenášejí se pouze plně
ověřené celostránkové rastry/přehledy a kandidáti OCR PSM3/11. Celá identita
zdroje, DPI, jazyka, parametrů, rendereru a skutečně ověřených nativních
prostředků musí souhlasit. Rozdílné prompty AI nebrání místnímu sdílení.
Chybějící, poškozená, nedokončená nebo neshodná jednotka se nově spočítá.
Existující jednotky cílového průchodu import nepřepisuje.

Import vytváří nezávislé běžné soubory přes dočasné kopie, fsync a ověření
hashů; dokončený checkpoint zveřejní až po výstupech. Nepoužívá hardlinky
ani symlinky. Původní příkaz OCR se ověří proti nezávisle sestavenému argv;
v nové identitě se přepíší pouze umístění rastru a prefixu výstupu. Původní
příkaz, nový příkaz, pozice argumentů a původní hash checkpointu zůstávají
v `local-imports.json`, jednotkovém checkpointu a historii. Dárce je pod
čtecím zámkem, cíl pod zápisovým; zámky jsou neblokující. Nové souhrnné
manifesty a kandidátní inventář vznikají vždy v cíli a běžná nativní závěrečná
validace se nevynechává.

AI přepisy, návrhy, posudky, očekávání, výběry oblastí, exporty, historie,
profily ani context-mode pracovní prostor či databáze se z dárce nepřenášejí.
Nový průchod má své pokusy, vlákna a úložiště. Pokračování stejného průchodu
zachovává jeho vlastní dokončenou práci. Shodná pozorovaná AI vlákna mezi
průchody se v porovnání označí; nepřítomnost měření sama nezávislost nedokládá.

## Veřejné operace a artefakty

`start_preparation` a `start_autonomous` přijímají volitelné
`reuse_from_run_id`. Stávající nativní `prepare` má kompatibilní volitelný
přepínač `--reuse-from-run-id RUN`; bez něj se chová jako dosud. Identifikátor
musí patřit registrovanému jinému pojmenovanému průchodu stejného zdroje,
nikoli libovolnému adresáři na disku.

`compare_runs` přijímá `left_run_id`, `right_run_id`, `offset` pro kroky,
`history_offset` pro historii a `limit` v rozsahu1–200 (výchozí100). Vrací
oba profily, výsledky, metriky a samostatné kurzory `step_next_offset` a
`history_next_offset`; GUI načítá všechny stránky. Existující `step_detail`
stránkuje úplné původní události a měření. Původní historie a price cards
zůstávají nedotčené; ledger metrik je odvozený z původních artefaktů.

Místní události `unit_completed`/`unit_cached` nesou `origin`:
`computed`, `same_run_cache` nebo `imported_local`. Import navíc nese
`donor_run_id` a `import_provenance`; odmítnutí má událost
`local_import_rejected` s důvodem. Tyto původy jsou oddělené od
poskytovatelem skutečně vykázaných cacheovaných vstupních tokenů AI.
