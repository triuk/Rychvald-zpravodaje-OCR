# Import a pojmenované průchody z externích profilů

Po otevření evidence zadejte cestu k jednomu PDF nebo složce PDF do pole
„Zdrojový sken nebo složka PDF“. Složka se prochází bez vnořených složek;
rozlišují se PDF podle přípony bez ohledu na velikost písmen a ostatní soubory
se ponechávají. Všechny vybrané vstupy se před importem ověří stejnou kontrolou
PDF hlavičky, kterou používá stávající registr. Úplnou místní přípravu a kontroly
obsahu provádí navazující operace OCR. Import sám OCR nespouští.

Identitu zdroje určuje SHA-256 obsahu. Opakovaný import existujícího obsahu
znovu použije dosavadní záznam; odlišný obsah stejného názvu založí samostatné
vydání. Zdrojové soubory se nepřepisují. Neplatný vstup v seznamu se hlásí před
zahájením importu složky. Původní importovaný průchod zůstává dohledatelný bez
profilu, nová pojmenovaná varianta vzniká vždy výslovnou akcí operátora.

Do pole „Externí profil průchodu“ zadejte cestu k JSON souboru a použijte
„Prohlédnout profil“. Aplikace zobrazí jméno, DPI, jazyk, požadovaný model,
úroveň uvažování a úplný obsah promptů. Použitelný příklad je
`profiles/faithful-reading.json`. Profil upravujte mimo GUI.

Poté vyberte projekt vydání, zadejte jméno nového průchodu a použijte
„Založit nový průchod“. Jméno musí být v daném vydání jedinečné bez ohledu
na velikost písmen. Každý průchod má vlastní identitu, pracovní adresář,
profil a historii. Stav nového průchodu je `registered`, validace `not_run`
a přijetí `not_recorded`; založení průchodu nezahajuje zpracování.

Pozdější úprava externího profilu nemění založené průchody. Změní-li se soubor
mezi prohlédnutím a založením, aplikace vyžádá jeho nové prohlédnutí. Upravený
profil lze použít v dalším výslovně pojmenovaném průchodu. V přehledu průchodu
jsou uložené prompty a parametry dostupné vedle samostatné historie i po restartu.

## Formát profilu verze 1

Profil je UTF-8 JSON do 1 MiB se čtyřmi povinnými položkami:

| Položka | Význam a pravidla |
| --- | --- |
| `schema_version` | Celé číslo `1` |
| `name` | Neprázdné jméno do 160 znaků bez krajních mezer a řídicích znaků |
| `parameters` | Přesně `dpi`, `language`, `model`, `reasoning_effort` |
| `prompts` | Přesně neprázdné texty `read`, `repair`, `final_check` |

`dpi` je kladné celé číslo; `language` a `model` jsou výslovně uvedené neprázdné
řetězce. `reasoning_effort` připouští `none`, `minimal`, `low`, `medium`, `high`,
`xhigh`, `max` a `ultra`. Syntaktická platnost neprokazuje dostupnost modelu
ani kombinace parametrů v místním runtime; tu ověřuje navazující předběžná
kontrola běhu. Nedoplňují se skryté výchozí hodnoty. Neznámé položky, duplicitní
JSON klíče, neúplné parametry a prázdné prompty jsou chyby.

## Veřejné operace a trvalá data

GUI používá `Application.dispatch` z [přehledu WebUI](webui-projects.md):

| Operace | Payload | Výsledek |
| --- | --- | --- |
| `import_sources` | `{"path":"/cesta/k/PDF-nebo-složce"}` | `root`, `editions`, `counts` (`sources`, `created`, `reused`) |
| `inspect_profile` | `{"path":"/cesta/k/profilu.json"}` | `path`, `sha256`, přesný `text`, rozebraný `profile` |
| `create_run` | `edition_id`, `name`, `profile_path`, `profile_sha256` | Stejný přehled jako `select_run` pro nový průchod |
| `select_run` | `{"run_id":"…"}` | U pojmenovaných průchodů navíc `run` s použitým profilem a `history` |

K novým událostem patří `sources_imported` a `run_created`. Prohlédnutí profilu
nezapisuje do evidence. Kódy `profile_invalid`, `profile_changed`,
`run_name_conflict` a `source_changed` rozlišují neopravitelné vstupy od
změněných podmínek, které je třeba znovu prohlédnout nebo vybrat.

Publikování pojmenovaného průchodu provádí samostatný OCR proces pod zámkem
registru. Doplňující přepínače existujícího příkazu `import` jsou:

```sh
python tools/ocr_projects.py --root /cesta/k/evidenci --json import /cesta/ke/skenu.pdf \
  --new-run --run-name 'První čtení' --profile /cesta/k/profilu.json \
  --profile-sha256 HASH_PROHLÉDNUTÉHO_PROFILU --source-sha256 HASH_VYDÁNÍ
```

Poslední dva přepínače kontrolují očekávané identity obsahu; GUI je předává vždy.
Existující volání bez těchto přepínačů se chovají jako dříve. Profil a jméno
se přijímají pouze pro jeden zdroj a výslovný nový průchod. Souhrnný protokol
zůstává verze 1 do 4 KiB. Dlouhé prompty se předávají souborem a nejsou v stdout.

Záznam projektu doplní `run_name` a cesty těchto artefaktů:

| Cesta v pracovním adresáři průchodu | Obsah |
| --- | --- |
| `application/profile.json` | Přesné původní UTF-8 byty profilu včetně formátování a konců řádků |
| `application/run.json` | Identita vydání a průchodu, jméno, čas založení, původní cesta a SHA-256 profilu |
| `application/history.jsonl` | Samostatná historie, počínaje událostí `run_created`; jeden JSON objekt na řádek |

Artefakty vzniknou před atomickým zveřejněním projektu v registru. Chyba při
vytváření nového pracovního adresáře vrátí nepublikované podklady; starší data
se nemažou ani nevracejí. Načtení ověřuje hash uloženého profilu a identitu
manifestu. U starších průchodů bez těchto artefaktů zůstává kompatibilní čtecí
pohled z ticketu #10.

## Ověření

`python -m unittest discover -s tests -p 'test_webui*.py' -v` ověřuje import,
kolize názvů, předběžné odmítnutí vadného vstupu, dvě pojmenované varianty,
přesné byty profilu, neměnnost starší historie, načtení po restartu, neplatné
profily a změnu zdroje nebo profilu před založením.

`python tools/smoke_webui_projects.py --browser Chromium --profiles` rozšíří
skutečný nativní scénář o import přes formulář, prohlédnutí profilu, založení
dvou pojmenovaných průchodů po externí úpravě profilu a opětovný výběr prvního
s jeho původními parametry a historií. Pro spuštění bez displeje lze použít
`xvfb-run -a`; volitelný `--screenshot` zachytí skutečné okno.
