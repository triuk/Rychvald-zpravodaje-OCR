# Ověření instalačního balíku

Povinný `tests/test_linux_bundle.py::InstalledBundleTests` spouští veřejný
`tools/verify_linux_bundle.py`; nikdy nevolá skip. Zdroj je nezávislý známý
raster `OCR 11`, nikoli přepis dřívějšího vydání. Běžné OCR regresní testy
zůstávají samostatnou povinnou kontrolou.

| Kritérium | Doklad v instalovaném čistém průchodu |
|---|---|
| A1 | Dvojí byte-identické sestavení, instalace/přesun/verify; prázdný bwrap root bez `/usr`, `/home`, `.venv`; vlastní executable/importy/nativní prostředky. |
| A2 | Skutečná změna modelu/fontu odmítnuta inventory i prepare; chybějící program/jiná verze a nesoulad tessdata prefixu s ověřenými modely/configs odmítnuty před změnou projektu. |
| A3 | Opakovaný import shodného obsahu stejné ID; jiné PDF se stejným názvem vlastní ID/výstupy; zdrojový hash zachován. |
| A4 | Skutečný SIGKILL procesní skupiny mezi dokončenými OCR průchody; explicitní resume ponechá hotové bytes/mtime. |
| A5 | Opakovaná příprava cache hit, korupce TXT opraví jediný průchod; jiné DPI odmítnuto v témže běhu; výslovně schválený validní model pod stejným názvem má nový hash/nový běh a žádný starý hit. |
| A6 | Projektový file patch zachová byte-exact historii a očekávání; neplatný bbox odmítnut bez změny přepisu/historie/očekávání. |
| A7 | Společné PDF/TXT `OCR 11\n`, přesný scan render/geometrie, qpdf, MuPDF/Poppler, pořadí/vzorky dle aktuálních technických reportů. |
| A8 | Nepotvrzený kandidát odmítnut, export `not_run`; validate template failed1, explicitní fixture evidence verified0, důvodný nález ready2, oprava stale failed1; schránka not_tested, souhlas samostatný. |
| A9 | Každá strojová odpověď validní protocol_version1 JSON <=4096B včetně LF; vybraný řádek/budget a úplné stránkování velkého Unicode přepisu. |
| A10 | Živý samostatný OS writer lock odmítne export/patch; opakování resume neztratí platné checkpointy/přepis; instalátor odmítne nesprávný archive hash bez změny existujícího cíle. |
| A11 | prepare/export nevytvoří potvrzené vizuální čtení; šablona reportu selže; pouze výslovný známý syntetický doklad dovolí confirmed testový průchod. |

`work/package-evidence.json` vznikne až po všech uvedených assertions; stav
kritérií neoznačuje skutečná vydání za přečtená. `verification.json` přidává
archiv/sha256/instalaci/reprodukovatelnost a cestu k uloženým dokladům.
Vizuální testové potvrzení je omezené na kontrolovanou syntetickou předlohu.
