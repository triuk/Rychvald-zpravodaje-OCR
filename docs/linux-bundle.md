# Linux instalační balík OCR

První sestavení `rychvald-ocr-linux-x86_64-v3-2026-10-14-1` používá ověřené
CachyOS binárky pro **Linux x86_64-v3**, vlastní glibc 2.44 a Python 3.14.7.
Podporovaný host má Linux kernel 6.1 nebo novější a kompatibilní POSIX `/bin/sh`.
Balík obsahuje Python standardní knihovnu, sedm přesně určených Python knihoven,
Tesseract, český model, qpdf, Poppler, nativní knihovny a fonty. Za běhu nepotřebuje
Docker, bwrap, systémový Python ani projektovou `.venv`. Obecná přenositelnost na
starší CPU, Windows nebo jinou libc není ověřena.

## Uzamčené vstupy a sestavení

[`native/bundle-inputs.json`](../native/bundle-inputs.json) určuje hash každého
nativního vstupu a licenčního textu, celý Python package archiv, sedm přesných
wheel URL/hashů, verze/vlastníky/architekturu a původ balíčků. Identita Pythonu
odkazuje na skutečný CachyOS `python-3.14.7-2-x86_64_v3.pkg.tar.zst`, nikoli
na binárně odlišný Arch balíček. Jeho současná mirror URL může být nedostupná;
připravený offline cache je samostatným uchovávaným vstupem sestavení.

Na stroji s přesnými uzamčenými soubory vytvoř obsahově adresovaný cache.
Tato operace kontroluje každý původní hash; **nevytváří ani nepřepisuje lock**:
Sestavovací nástroje vyžadují Python 3.14 se standardní podporou `.tar.zst`;
potřebné nativní binárky se při sestavení neinstalují do hostitele.

```bash
python3 tools/ocr_bundle.py capture \
  --inputs /absolutni/cesta/ocr-inputs \
  --wheel-cache /absolutni/cesta/pinned-wheels
```

Volitelné `--download` dovolí získat chybějící wheels pouze z připnutých URL;
stažené tělo musí souhlasit s připnutým SHA256. Nativní prostředky a Python
archiv musí být dostupné v uvedených přesných cestách nebo již zachované v cache.
Po zachycení přenes celý cache spolu s repozitářem. Sestavení čte **jen cache**,
nikdy hledání OCR v PATH, importy z `.venv` nebo aktualizaci locku:

```bash
python3 tools/ocr_bundle.py build \
  --inputs /absolutni/cesta/ocr-inputs \
  --output /absolutni/cesta/rychvald-ocr.tar.gz
```

Změněný/chybějící vstup vrací `input_mismatch` před vytvořením výsledku.
Existující archiv sestavovač nepřepíše. Archiv má pevné časy, pořadí, vlastnictví
a gzip hlavičku; dvojí sestavení ze stejných vstupů musí dát stejný SHA256.
Vedle něj vznikne `.sha256`. `provenance/input-lock.json`, Python `.PKGINFO`/
`.BUILDINFO`, aplikační hashe a úplný `inventory.json` uchovávají původ výsledku.

Nové verze jsou výslovná změna locku/build_id a nové integrační ověření.
Samotné opětovné zachycení aktuálního stroje není schválením nové verze.

## Instalace bez vývojového Pythonu

Převezmi archiv a očekávaný SHA256 od sestavovatele. Systémový `sha256sum`
a `tar` jsou pouze pomůcky prvního rozbalení; následný instalátor už používá
vlastní Python z balíku. Nejprve ověř archiv, potom jej rozbal do prázdné
dočasné složky:

```bash
sha256sum -c rychvald-ocr.tar.gz.sha256
mkdir temporary-ocr
tar -xzf rychvald-ocr.tar.gz -C temporary-ocr
temporary-ocr/rychvald-ocr/bin/rychvald-ocr install \
  --archive /absolutni/cesta/rychvald-ocr.tar.gz \
  --sha256 OCEKAVANY_SHA256 \
  --destination /absolutni/cesta/rychvald-ocr
/absolutni/cesta/rychvald-ocr/bin/rychvald-ocr verify
```

Instalátor znovu ověří hash archivu **před extrakcí**, odmítne nebezpečné členy
archivu i existující cílovou instalaci, zkontroluje každý instalovaný soubor,
nativní prostředky a skutečné importy všech sedmi knihoven a teprve potom
zveřejní cílovou složku. Při selhání je stará instalace zachována. Samostatné
`verify` odmítne změněný model, font, knihovnu, spouštěč či standardní knihovnu.
Instalaci lze přesunout jako celek; znovu spusť `verify`. Spouštěj ji plnou
cestou, aby se vlastní prostředky našly bez náhodného PATH.

## Práce s projektem

```bash
/cesta/rychvald-ocr/bin/rychvald-ocr --root /cesta/projekty --json import zdroj.pdf
/cesta/rychvald-ocr/bin/rychvald-ocr --root /cesta/projekty --json prepare PROJECT_ID
/cesta/rychvald-ocr/bin/rychvald-ocr --root /cesta/projekty --json status PROJECT_ID
```

Přerušená příprava vyžaduje výslovné `resume PROJECT_ID`. Platné checkpointy
zůstávají cache hit; poškozené části se obnoví. Nové parametry či prostředí
patří do nového `import --new-run`, existující běh se automaticky nepředefinuje.

Původní příkazy pro místní OCR a návrh přepisu zůstávají dostupné přes
`rychvald-ocr workflow regions ...` a `rychvald-ocr workflow draft ...`.
Podrobnosti [přípravy](project-preparation.md), [čtení a oprav](project-review.md)
a [exportu a validace](project-export.md) platí i pro instalovaný spouštěč.
`query`, `patch`, `export` a `validate` mají stejné projektové rozhraní.
Přebírej skutečné cesty PDF/TXT z odpovědi exportu; každá iterace má vlastní
název a předchozí výsledky se zachovají.

Výsledky validace jsou `failed/1`, `ready_with_open_items/2` a `verified/0`.
Příprava ani export nepotvrzují vizuální čtení a šablona reportu neprojde jako
hotový první průchod. Schránka `not_tested` je volitelná neprovedená kontrola,
ne potvrzená kompatibilita UI. Souhlas zadavatele zůstává samostatný.

Při `environment_invalid` nepřepisuj pracovní projekt: ověř instalaci pomocí
`verify`, obnov přesné soubory reinstalací do nové cílové složky nebo proveď
výslovně verzovanou změnu prostředí. `project_busy` znamená jiného živého
zapisujícího procesu; jeho ukončení uvolní OS zámek. Přerušený proces bezpečně
obnovíš podle [dokumentace přípravy](project-preparation.md).

## Povinné ověření a předání

```bash
python3 tools/verify_linux_bundle.py \
  --inputs /absolutni/cesta/ocr-inputs \
  --artifacts /absolutni/cesta/doklady
```

Test sestaví archiv dvakrát, instaluje a přesune jej, pak spustí skutečný celý
syntetický průchod v prázdném bwrap rootu bez hostitelského `/usr`, `/home`,
repozitáře a `.venv`, se záměrně chybnými PATH/model/Python proměnnými.
Jediný explicitní testovací základ je uzamčený shell, `/proc`, `/dev` a `/tmp`.
Instalace je v testu zapisovatelná pouze kvůli skutečné zkoušce změny modelu/fontu;
každá změna se obnoví a konečné `verify` musí projít. bwrap není závislost běhu.
Chybějící cache, harness nebo oprávnění jsou **selhání**, nikoli přeskočený test.
V Codex sandboxu může namespace vyžadovat schválené spuštění mimo sandbox.

Velké doklady a balík zůstávají v předané složce `--artifacts`, mimo pracovní
worktree. `verification.json` a `work/package-evidence.json` odkazují na čistý
průchod; testové stdout/stderr, projekty a předchozí iterace jsou zachované.
[`linux-bundle-verification.md`](linux-bundle-verification.md) mapuje A1–A11.

## Licence a původ

Balík ponechává licence/notices všech wheel distribucí v jejich `.dist-info`,
89 uzamčených nativních/společných licenčních souborů v `licenses/` a přesné
Apache LICENSE tělo Tesseractu a tessdata. `provenance/input-lock.json` obsahuje
vlastníky, verze, licenční identifikátory, upstream odkazy, známé exact package
archivy/signatury a PKGBUILD hashe. Přibalené sdílené knihovny nejsou upravené;
pro vlastní změnu/relinkování uprav výslovný input lock a sestav novou identitu.
Zachovej obsahově adresovaný vstupní cache a přesné package archivy, jsou-li
dostupné. Upstream odkazy samy nejsou tvrzením, že se binárky znovu sestaví
identicky z aktuálního zdrojového stromu.

## CI vrstvy

Hosted push/PR workflow provádí pouze syntax a výslovně vybrané standard-library
quality/registry/query testy. Jeho zelený stav není ověřením nativního balíku.
Samostatný `Native OCR package (explicit trusted run)` se spouští ručně přes
`workflow_dispatch` pro důvěryhodný checkout. Vyžaduje self-hosted runner se
štítky `self-hosted`, `Linux`, `X64`, `rychvald-ocr-v3`, uzamčený CachyOS profil,
Python 3.14, funkční bwrap/user namespaces a cache `/opt/rychvald-ocr-inputs`.
Z cache sestaví vlastní runtime a tím spustí celou regresní sadu včetně
povinného čistého instalačního průchodu. Runner ani infrastruktura se tímto
commitem nezřizují. Bez konfigurace je nativní workflow `not_run` nebo pending;
chybějící vstup či selhaný test je failure a nikdy se nemění na přeskočený pass.
Lokální doložený průchod z výše uvedeného příkazu je samostatný doklad.

Následná etapa řeší reviewer UI, Windows a případné širší CPU/distribuční
podmínky. Tento balík nezavádí UI ani měření skutečných AI tokenů.
