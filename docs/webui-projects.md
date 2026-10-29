# WebUI: přehled projektů vydání

Pro vývojové spuštění z repozitáře slouží `./start.sh`. Používá místní
`.venv/bin/python` a předává všechny argumenty aplikaci:

```sh
./start.sh --root /cesta/k/testovaci-evidenci --browser Chromium
./start.sh --root /cesta/k/testovaci-evidenci --serve
./start.sh --help
```

Skript lze zavolat i absolutní cestou z jiného adresáře. Relativní uživatelské
cesty se vyhodnocují vůči adresáři, ze kterého jej spustíte. Bez `--root` platí
výchozí evidence aplikace (`$XDG_DATA_HOME/rychvald-ocr`, jinak
`~/.local/share/rychvald-ocr`).

Závislosti připravte jednorázově; pokud `.venv` již existuje, první příkaz vynechte:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-gui.txt
```

Start nic nestahuje ani neinstaluje. Skutečné AI zpracování navíc vyžaduje
[připravené připnuté prostředky Codexu a context-mode](webui-context.md).

Nativní aplikace se spouští příkazem `python main.py --root "/cesta/k/evidenci"`.
GUI potřebuje `pip install -r requirements-gui.txt`, dostupný prohlížeč a grafické
prostředí. Volitelný `--browser Chromium` vybere konkrétní prohlížeč. Pro samostatně
zabalený OCR proces lze předat `--ocr-executable /cesta/k/ocr-process`.
Bez tohoto přepínače se používá dosavadní `tools/ocr_projects.py` jako podproces.
Stávající OCR CLI, jeho prostředí a souhrnný JSON protokol zůstávají zachované.

Import PDF a složek, výběr externích profilů a vytváření pojmenovaných průchodů
popisuje [návod k profilům](webui-profiles.md).
Spouštění skutečné místní přípravy a její živé checkpointy popisuje
[návod k místní přípravě](webui-preparation.md).

Do pole „Adresář evidence“ patří pracovní kořen se souborem `registry.json`,
nikoli adresář zdrojových PDF. Po otevření se vlevo zobrazí projekty vydání a jejich
průchody. Rozdílné zdrojové skeny stejného názvu mají vlastní projekty vydání;
úplný hash zdroje lze zobrazit nad jeho zkrácenou podobou. Výběr průchodu načte
aktuální fázi, stav operace, validaci a přijetí zadavatelem. Tabulka rozlišuje
evidované cesty artefaktů a jejich skutečnou dostupnost. Obnovit načte čerstvý stav.

Projekty zůstávají v levém panelu. Jediný průchod lze vybrat přímo; dva a více
průchodů jsou v rozbalitelné skupině. Tlačítko Nastavení u projektu otevře jeho
nastavení a založení nového průchodu; globální nastavení evidence je vlevo dole.
Celý automatický průchod spouští hlavní tlačítko nahoře. Fronta a porovnání jsou
v rozbalitelné části pod pracovní plochou.

Vybraný průchod má vodorovné záložky Příprava, Přepis, Pořadí a geometrie,
Sestavení a kontroly, Ruční revize a Výstupy. Přepínání záložek samo nespouští
zpracování. Obnovení přehledu ponechá vybraný průchod i záložku. Ruční revize
a Výstupy jsou zatím označená místa pro budoucí práci; automatické PDF se
prohlíží v Sestavení a kontrolách. Původní profil, soubory a historie jsou
v rozbalitelných technických podkladech průchodu.

Přehled je kompatibilní čtecí pohled nad verzí 1 evidence: projekt vydání je určen
celým `source_sha256`, jeho průchody zachovávají původní `project_id` a `run_id`.
Neprobíhá migrace, kopírování ani přepisování starší práce. Načtení neprovádí
validaci a nemění stav přijetí.

## Společné veřejné rozhraní

`app.service.Application(root, process_command=None).dispatch(operation, payload)`
je společná hranice pro GUI a integrační scénáře. `process_command` je seznam
argumentů OCR procesu. Nepoužívá shell. Operace:

| Operace | Payload | Výsledek |
| --- | --- | --- |
| `projects` | `{}` | `root`, `editions` se všemi průchody; stránkování CLI se načte celé |
| `open_registry` | `{"root": "/cesta/k/evidenci"}` | Přehled jiné evidence; chyba zachová původní kořen |
| `select_run` | `{"run_id": "…"}` | `edition_id`, původní `project`, `counts`, dostupnost `artifacts` |
| `events` | `{"after": 0}` | Události `projects_changed` a `run_selected` od kurzoru |

Odpověď obsahuje `ok`, `data`, `error` a `event_cursor`. Chyby OCR zachovávají
veřejný kód procesu. Události mají rostoucí `sequence`; historie změn pohledu je
omezena na 1000 událostí a odpověď `reset` signalizuje potřebu nového dotazu.
Události pohledu jsou dočasné; trvalá historie průchodu zůstává v jeho artefaktech.
Nativní `requestB` předává JSON požadavek tomuto rozhraní. Živé události se
nezapisují do stdout OCR procesu.

## Výběr cest

Tlačítka vedle cest otevřou systémový dialog pro příslušný adresář nebo soubor.
Pro import je samostatná volba jednoho PDF a celé složky. Zrušení ponechá
dosavadní text; cestu lze stále napsat ručně. Zvolená cesta se pouze vyplní,
otevření evidence, import a načtení profilu nadále potvrzuje jejich vlastní akce.

Veřejný požadavek `choose_path` přijímá `kind` a volitelnou `current_path`.
Podporované typy jsou `registry_directory`, `source_directory`, `source_pdf`,
`profile`, `environment_manifest` a `image`. Vrací `kind`, `path`, `cancelled`.
Neexistující, nepřístupná nebo typově neodpovídající cesta vrací `path_invalid`.
Dialog nezamyká aplikační službu a neblokuje zpracování ani dotazy na jeho stav.

Desktopový adaptér používá dostupný `kdialog`, `zenity` nebo standardní Tk.
Při vývojovém spuštění tedy potřebuje vedle grafické relace jeden z těchto
prostředků (Tk je například součástí balíčku Python Tk distribuce Linuxu).
Pokud žádný není dostupný, zobrazí se chyba `path_picker_unavailable` a ruční
zadání zůstává použitelné. Distribuovaný Linux balík musí mít dostupný dialog
ověřený spolu se svým Python runtime.

Ověření adaptéru 29. 10. 2026 použilo skutečný Tk dialog v Linux relaci Xvfb
a vstup klávesnice přes xdotool. Ověřen byl výběr PDF s mezerami a diakritikou
v cestě s následným importem přes veřejnou operaci, výběr vstupního adresáře
a zrušení dialogu se zachováním předchozí hodnoty. Nešlo o náhradu dialogu
v testu; kontrola distribuovaného runtime a rozložení GUI je samostatná.

## Ověření

`python -m unittest discover -s tests -p 'test_webui_projects.py' -v` ověřuje
starší průchody stejného zdroje, kolize názvů, pravdivé stavy a artefakty,
opětovné načtení po restartu, zachování všech bytů dat, více stránek seznamu,
výběr jiné evidence a chyby poškozených metadat přes společné veřejné operace.

Skutečný nativní průchod lze spustit v grafickém prostředí:

```sh
python tools/smoke_webui_projects.py --browser Chromium
```

Přepínač `--headless` ověří skutečný Chromium bez viditelného okna (nativní
knihovna WebUI stále potřebuje dostupný displej, případně Xvfb). Scénář navíc
ověřuje šest záložek, vodorovné rozložení vedle seznamu projektů, rozbalitelné
průchody a zachování výběru po obnovení. `--profiles` přidá import a dva
pojmenované průchody s nezávisle uchovanými profily.

V prostředí bez displeje použijte `xvfb-run -a`. Přepínač `--screenshot /tmp/ocr.png`
volitelně zachytí okno pomocí ImageMagick. Scénář skutečně otevře produkční WebUI,
načte dvě vydání a tři průchody z dočasné evidence, klikne na průchod a ověří
vykreslené stavy. Nepoužívá náhradu nativní knihovny, prohlížeče ani procesu OCR.
