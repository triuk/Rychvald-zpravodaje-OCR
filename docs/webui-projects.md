# WebUI: přehled projektů vydání

Nativní aplikace se spouští příkazem `python main.py --root "/cesta/k/evidenci"`.
GUI potřebuje `pip install -r requirements-gui.txt`, dostupný prohlížeč a grafické
prostředí. Volitelný `--browser Chromium` vybere konkrétní prohlížeč. Pro samostatně
zabalený OCR proces lze předat `--ocr-executable /cesta/k/ocr-process`.
Bez tohoto přepínače se používá dosavadní `tools/ocr_projects.py` jako podproces.
Stávající OCR CLI, jeho prostředí a souhrnný JSON protokol zůstávají zachované.

Import PDF a složek, výběr externích profilů a vytváření pojmenovaných průchodů
popisuje [návod k profilům](webui-profiles.md).

Do pole „Adresář evidence“ patří pracovní kořen se souborem `registry.json`,
nikoli adresář zdrojových PDF. Po otevření se vlevo zobrazí projekty vydání a jejich
průchody. Rozdílné zdrojové skeny stejného názvu mají vlastní projekty vydání;
úplný hash zdroje lze zobrazit nad jeho zkrácenou podobou. Výběr průchodu načte
aktuální fázi, stav operace, validaci a přijetí zadavatelem. Tabulka rozlišuje
evidované cesty artefaktů a jejich skutečnou dostupnost. Obnovit načte čerstvý stav.

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

## Ověření

`python -m unittest discover -s tests -p 'test_webui_projects.py' -v` ověřuje
starší průchody stejného zdroje, kolize názvů, pravdivé stavy a artefakty,
opětovné načtení po restartu, zachování všech bytů dat, více stránek seznamu,
výběr jiné evidence a chyby poškozených metadat přes společné veřejné operace.

Skutečný nativní průchod lze spustit v grafickém prostředí:

```sh
python tools/smoke_webui_projects.py --browser Chromium
```

V prostředí bez displeje použijte `xvfb-run -a`. Přepínač `--screenshot /tmp/ocr.png`
volitelně zachytí okno pomocí ImageMagick. Scénář skutečně otevře produkční WebUI,
načte dvě vydání a tři průchody z dočasné evidence, klikne na průchod a ověří
vykreslené stavy. Nepoužívá náhradu nativní knihovny, prohlížeče ani procesu OCR.
