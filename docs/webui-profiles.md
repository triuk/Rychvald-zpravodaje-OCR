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

## Globální a projektové předvolby modelu

Globální nastavení vlevo dole určuje model a reasoning nových projektů vydání
v otevřené evidenci. Při importu se hodnoty zkopírují k identitě zdrojového PDF.
Další změna globálních hodnot neovlivní existující projekty. Jejich vlastní
nastavení je u tlačítka **Nastavení**; **Převzít globální předvolby** provede
výslovnou kopii. U starších projektů bez záznamu předvoleb zůstává původní
výchozí kombinace. Změna předvoleb nepřepisuje žádný existující průchod.

Modely a jejich úrovně reasoningu se načítají tlačítkem **Obnovit nabídku modelů
Codexu** ze skutečného `model/list` připojeného připnutého runtime. Dotaz běží
na pozadí a nevytváří AI tah. Uložená hodnota zůstane viditelná i při změně
nebo nedostupnosti runtime; aplikace ji tiše nenahrazuje. Známá nedostupná
kombinace zabrání založení nového průchodu. Samotná nabídka nezaručuje přístup
účtu: každý skutečný AI krok ověří přesnou zvolenou kombinaci a odmítne jinou
odpověď poskytovatele i přesměrování modelu.

Při založení průchodu se předvolby projektu vyhodnotí nad prohlédnutým externím
profilem. Jeho původní soubor se nemění; pokud se model nebo reasoning liší,
vytvoří se přesná vyhodnocená kopie pro nativní import. Prompty, DPI a jazyk
zůstávají z externího profilu. Zmrazená kopie průchodu je pak zdrojem nastavení
čtení, geometrie, kontrol, oprav i jejich obnovení. Formulář nového průchodu
před spuštěním zobrazuje účinnou dvojici model/reasoning.

Veřejné operace jsou `global_preferences`, `set_global_preferences`,
`project_preferences`, `set_project_preferences`, `adopt_global_preferences`,
`model_capabilities` a `start_model_capabilities`. Projektové operace používají
`edition_id`; zápis dvojice používá `model` a `reasoning_effort`. Záznam je
v `application/preferences.json`, aktualizuje se atomicky pod procesovým zámkem.

Ověření: `tests/test_webui_preferences.py` používá veřejné požadavky a skutečné
nativní PDF zpracování s výslovně řízeným app-server partnerem. Kontroluje
nezávislost kopií, převzetí globálu, restart, zmrazení průchodu a předání jiné
dvojice všem AI činnostem včetně cílené opravy. Skutečné WebUI a Chromium
ověřuje `tools/smoke_webui_projects.py --headless --profiles --preferences`;
spuštění stále vyžaduje dostupný Linux displej pro nativní adaptér.

### Výjimky jednotlivých AI činností

Globální i projektové nastavení mají rozbalitelnou část **Výjimky pro AI
činnosti**. Čtení, pořadí a geometrie, kontroly výsledku a cílené opravy mohou
mít vlastní dvojici. Vypnutí výjimky a uložení obnoví společnou dvojici. Uložený
přehled pod formulářem ukazuje skutečně účinné hodnoty pro další průchod;
rozpracované změny formuláře je nejdříve třeba uložit.

Obrazová diagnostika i ověření context-mode používají dvojici čtení, aby jejich
preflight dokazoval přesně kombinaci potřebnou k přepisu. Geometrické ověření
po cílené opravě používá výjimku geometrie, vlastní opravný tah výjimku oprav
a následná kontrola PDF výjimku kontrol výsledku.

Veřejné zápisy předvoleb přijímají volitelnou mapu `overrides` s klíči
`reading`, `geometry`, `final_check`, `repair`; každá hodnota obsahuje `model`
a `reasoning_effort`. Prázdná mapa výjimky odstraní. Odpověď poskytuje také
`effective` a `activity_availability` pro všechny čtyři činnosti. Při založení
průchodu se mapa zmrazí v `parameters.activity_overrides` profilu. Původní
profily bez tohoto volitelného pole zůstávají podporované.

Každý původní tah a jeho obnova se ověřují proti příslušné aktivitě zmrazeného
profilu. Zachované protokoly dokládají skutečný model a reasoning. Pokud pokus
obsahuje více modelů a nelze jim spolehlivě přiřadit souhrnné tokeny, metriky
vracejí `model_attribution: mixed_models`, seznam `model_settings` a nedostupný
cenový odhad; nepoužijí cenu posledního modelu na celý pokus.

`tests/test_webui_activity_preferences.py` ověřuje kopírování, rušení výjimek,
restart, odmítnutí nedostupné kombinace a nativní průchod se čtyřmi různými
dvojicemi včetně následné opravy po změně projektových předvoleb. Skutečný
GUI scénář `tools/smoke_webui_projects.py --headless --profiles --preferences`
ověřuje i rozbalení výjimek, převzetí globálu, jejich zrušení a zachování
zmrazeného průchodu.
