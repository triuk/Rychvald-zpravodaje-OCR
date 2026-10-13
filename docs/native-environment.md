# Ověřené nativní OCR prostředí

`native/environment.json` je verzovaný profil **vývojového prostředí**, nikoli
hotový instalační balík. Profil `rychvald-ocr-linux-x86_64-v3-2026-10-13-dev1`
odpovídá ověřenému Linuxu CachyOS, x86_64 se základnou x86-64-v3 a glibc 2.44.
Systémové ELF programy potřebují své odpovídající dynamické knihovny: Python,
Tesseract/Leptonica, qpdf, Poppler a jejich tranzitivní vazby. Samotné zkopírování
programů na jinou distribuci není instalace. Distribuovatelný balík musí přibalit
ověřenou knihovní uzávěru nebo stanovit a ověřit odpovídající systémový základ.

Manifest připíná Python 3.14.7, všech sedm přímých a tranzitivních knihoven z
`requirements.txt`, Tesseract 5.5.3, modely ces/eng/osd 4.1.0, qpdf 12.4.2,
Poppler 26.08.0, oba pracovní fonty a konfigurace výstupů Tesseractu. Obsahuje
zdroje konkrétních vydání a ověřitelné SHA-256 skutečných instalovaných prostředků.
URL zdroje je provenance vydání; hash souboru není hash celého zdrojového archivu.
Vývojový profil neslibuje stažení shodných systémových binárek z upstream tarballu.
Neobsahuje neomezené vstupy `latest`.

## Spuštění a nastavení cest

Použij Python odpovídající manifestu a samostatné prostředí s přesnými knihovnami.
Z kořene repozitáře:

```bash
.venv/bin/python tools/ocr_workflow.py doctor
.venv/bin/python tools/ocr_workflow.py prepare --source /cesta/sken.pdf --work /cesta/novy-pruchod
```

Každý veřejný příkaz nejdříve ověří sadu bez zápisu do pracovních dat. Rozlišuje
chybějící prostředek, nesprávnou verzi a změněný obsah. `doctor --work` zapisuje
`checks/environment.json` pouze po úspěšném ověření. Příprava zapisuje identitu
prostředí do `input-manifest.json`; OCR příkazy zaznamenávají skutečné absolutní
cesty. Lokální OCR cache váže i manifest a identitu sestavení.

Jinou sadu vyber pomocí `--environment /cesta/environment.json` **před názvem
příkazu**, případně proměnnou `OCR_ENVIRONMENT`. Změna očekávané sady patří do
verzované revize manifestu s novým `build_id` a integračním ověřením.

```bash
.venv/bin/python tools/ocr_workflow.py --environment /cesta/balik/environment.json doctor
```

`root` může být absolutní cesta nebo cesta relativní k souboru manifestu.
Relativní `path` prostředku se vyhodnotí vůči `root`; absolutní zůstane absolutní.
V balíku lze proto přesunout Python, programy, fonty a datové soubory změnou
manifestu a spouštěče bez úprav OCR implementace. `tessdata` určuje adresář modelů
i podadresář `configs`. Volitelná mapa `libraries` obsahuje stejný záznam
`path`/`sha256`/`source`; `library_dirs` určuje adresáře pro `LD_LIBRARY_PATH`
podprocesů. Spouštěč musí nastavit knihovní prostředí také před startem Pythonu.

Podprocesy používají určené absolutní programy, `TESSDATA_PREFIX` a případně
`library_dirs`; náhodné programy v PATH ani uživatelská proměnná TESSDATA_PREFIX
sadu nenahradí. Výběr alternativního fontu přes existující `--font` je povolen
jen pro soubor se shodným očekávaným obsahem; výchozí cesty nahradí manifest.

## Schéma a veřejné rozhraní

Verze schématu 1: `build_id`, `platform`, `root`, `python`, `packages`, `programs`,
`tessdata`, `models`, `fonts`, `configs`, `library_dirs`, `libraries`.
Program má přesný první řádek `version`, cestu, SHA-256 a zdroj; Python má
verzi runtime a hash skutečné binárky. Knihovna má přesnou verzi a
`tree_sha256`: pro seřazené cesty instalovaných souborů z RECORD se spojí
UTF-8 cesta, nulový byte a 32 bytů SHA-256 souboru. Vynechají se `..`,
`__pycache__` a `.dist-info`; tím se nezahrnou lokální skripty venv a metadata
instalátoru. Hash chrání skutečný obsah knihoven i binárních rozšíření.
Kontrola také ověří, že import vybírá soubor ověřené distribuce; odlišná knihovna
vložená přes PYTHONPATH nemůže nahradit ověřenou instalaci.

`tools/ocr_environment.py::verify_environment(path=None, language='ces')`
vrací ověřený `NativeEnvironment`; při neshodě vyhodí `ValueError`/`OSError`.
Objekt má `identity`, `manifest`, `resolve(path)`, `command(argv)`, `run(argv)`
a `report()`. `command` přijímá logický název programu jako první položku,
`run` vrací `CompletedProcess` a zachovává návratový kód. Vrstva příkazů
`tools/ocr_workflow.py::configure_environment` nastaví stejný ověřený objekt
pro současné operace. Import modulu sám neprovádí OCR ani zápisy.

## Evidence verzí a ověření

Tento profil zachovává dříve připnuté Python knihovny a zdokumentovaný pracovní
postup. Systémové nástroje a Python jsou zaznamenány v přesných verzích skutečně
ověřené instalace; Tesseract je 5.5.3, nikoli dříve předpokládaná 5.5.2.
Změny fontů či modelů nikdy nejsou automaticky přijaty při běhu.

`tests/test_ocr_environment.py` ověřuje veřejné CLI: neshody před zápisem a malý
syntetický sken přes prepare, regions, targeted, draft, segment, export a check.
Programy, fonty, modely a konfigurace se v testu přesunou; PATH a TESSDATA_PREFIX
ukazují na záměrně chybné prostředky. Očekávání `OCR 11` pochází z vytvořeného
rastru, ne z automatického přepisu. Export kontroluje shodu obrazu, PDF/TXT,
qpdf a extrakci Poppler/MuPDF. Test neprohlašuje vizuální revizi běžných zpravodajů
ani schránku skutečné čtečky za provedenou.
