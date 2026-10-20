# Autonomní první export

`Application.dispatch('start_autonomous', payload)` je jediná asynchronní akce pro
jeden zdrojový PDF, jméno průchodu a již prohlédnutý profil (`profile_path`,
`profile_sha256`). Volitelné `environment` vybírá konkrétní nativní manifest.
GUI používá stejnou akci tlačítkem **Spustit celý průchod ze zdrojového PDF**.
Příprava, obrazová diagnostika, context-mode, nezávislé čtení, vyúčtování OCR
kandidátů, geometrie, export, skutečné prohlédnutí výstupu a validace proběhnou
v jednom vlastněném průchodu. Průběh, jednotlivé child attempt ID a chyby jsou
uložené v `application/autonomous-attempts/*/attempt.json`; sleduje je
`autonomous_status`. Jiná mutující GUI akce nesmí mezi etapami převzít evidenci.

První export z již dokončené geometrie používá `start_first_export(run_id)`.
Nativní `export --geometry-checkpoint` pod projektovým zámkem znovu ověří přesný
checkpoint, jeho původní dokončený modelový JSON, aktuální review, všechny
geometrické produkty a nezávislé vzorky. Tyto produkty již negeneruje znovu.
Původní legacy `export` bez tohoto přepínače zachovává své dosavadní chování.
Nativní generování F ani sémantika společného PDF/TXT přepisu se nemění.

## Skutečné reporty

`prepare-output-review` ověří nativní prostředí, aktuální source/PDF/TXT a
technické i vzorkové kontroly. Z aktuálních souborů znovu vyrenderuje všechny
strany MuPDF i Popplerem. Existující obrázek pouze nalezený na disku není důkazem
aktuálního PDF. Do paketu patří přesný seznam aktuálních stran a geometrických
obrazů z manifestu; staré přebytečné listy se neodesílají. Původní očekávání,
zdrojový sken a dokončené modelové návrhy zůstávají beze změny.

Každý paket a původní šablony jsou uloženy také v neměnném adresáři
`output-review-inputs/<id>/`. `output-review-preparation.json` je aktuální výběr,
nikoli jediná kopie historického důkazu. `publish-output-review --proposal`
ověří původní protokol, skutečně přiložené obrazy, model/effort, dokončený tah,
context-mode statistiky, původní JSON a CAS všech vstupů. Všechny strany i
dosavadní nálezy musejí být pokryty konkrétním závěrem a doklady. Nezměněné
geometrické otevřené nálezy a nevyřešená místa zdroje se nedají uzavřít obecným
dojmem z celé strany. Historické slovní `remaining_risks` se uchovávají s původním
významem; dokončení nové fáze nepřepisuje starý JSON.

Teprve platný návrh publikuje `checks/visual-review.json`, `checks/findings.json`
a `output-review-publication.json`. Při odmítnutí zůstávají dosavadní reporty
zachované. `verify-output-review` znovu odvozuje závěry z původního dokončeného
tahu a odmítne později změněný obsah. Pro export s examined checkpointem je
platná publikace povinnou součástí nativní validace.

## Pokračování připraveného exportu

Pro konkrétní předem zkontrolovaný export může `start_first_export` převzít
`existing_export_sha256` a `prepared_review_sha256`. Oba hashe se musejí shodovat
s aktuálním exportem a jeho nezměněným paketem; veřejná nativní operace
`verify-output-preparation --sha256 --output-manifest-sha256` kontroluje CAS.
Akce potom dokončí pouze výstupní AI kontrolu a validaci. Nevytváří nový export,
neopakuje čtení ani geometrii a sama neopakuje již existující AI pokusy.
GUI tuto větev nabízí jako **Dokončit kontrolu tohoto připraveného exportu**.

`output_results` vrací výsledky a jejich původ, nálezy a aktuální dostupné
artefakty. `open_output_artifact` přijímá pouze zaznamenanou cestu v evidenci
společně s jejím aktuálním hashem a požádá o otevření v externí aplikaci.
Nevytváří potvrzení prohlédnutí ani uživatelského přijetí. GUI nemá PDF preview.

Dokončená operace se odlišuje od validace (`failed`, `ready_with_open_items`,
`verified`) a od samostatného přijetí zadavatelem. Aproximace znakových řezů,
nejistá místa a neprovedené testy clipboardu se nepřevádějí na záruku bez chyb.
Neúspěšná validace může být řádně dokončenou operací s výsledkem `failed`.

## Ověření

`test_webui_export.py` používá veřejné dispatch/native CLI a skutečně generovaný
PDF s řízeným procesním protějškem. Ověřuje celý řetězec, rezervaci průchodu,
explicitní CAS pokračování a odmítnutí zahozených nálezů, jejich nepodloženého
uzavření, šablony a změněných přiložených pixelů. Řízený protějšek není důkaz
skutečné AI akceptace. `smoke_webui_export.py` odděleně prokazuje skutečný nativní
GUI průchod nad konkrétním zveřejněným paketem; implicitně jen prohlíží a bez
výslovného přepínače neposílá nový modelový požadavek.

Historické geometrické a exportní vstupy obsahují přesné cesty ke kódu. Úklid
worktree ani přemístění balíku je nesmějí tiše zneplatnit. Vydání musí zachovat
přesné archivní kopie a auditovanou mapu řešení původních cest; přepsání cesty v
původním paketu by změnilo hash obsažený v původním modelovém JSON.
