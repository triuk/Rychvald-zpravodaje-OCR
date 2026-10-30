# OCR Rychvaldského zpravodaje

Aplikace pro převod naskenovaných vydání do OCR PDF a souvislého textu článků, s trvalou historií jednotlivých průchodů.

## Pokračování na jiném počítači

Aktuální vývojová větev je **integration/webui-ocr**. Obsahuje dosavadní WebUI aplikaci i podklady potvrzeného redesignu. Výchozí větev main zatím obsahuje starší etapu projektu.

Nový pracovní adresář vytvořte:

```sh
git clone --branch integration/webui-ocr https://github.com/triuk/Rychvald-zpravodaje-OCR.git
cd Rychvald-zpravodaje-OCR
```

V již existujícím klonu po uložení vlastní rozpracované práce:

```sh
git fetch origin
git switch integration/webui-ocr
git pull --ff-only
```

## Zadání redesignu a stav práce

- [Potvrzená implementační specifikace](docs/specs/0003-webui-ergonomics-and-phase-previews.md), také [GitHub issue #24](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/24).
- [Schválený rozpad na úkoly a jejich závislosti](docs/plans/webui-ocr-gui-tickets.md), publikované jako issues #25–#38.
- [Rozhodnutí návrhového rozhovoru](docs/plans/webui-ocr-gui-redesign.md).
- [Slovník projektu](GLOSSARY.md) a [instrukce pro práci v repozitáři](AGENTS.md).

Realizace byla výslovně zahájena zadavatelem a pokračuje na větvi **integration/webui-ocr**. Sloučené a dílčími testy ověřené jsou úkoly #25–#31 a #34: rozložení GUI, výběr cest, předvolby a výjimky modelů, společný náhled a zachované původní stavy přepisu a geometrie i historie místních kroků.

Rozpracované jsou náhled exportovaného PDF (#32), úplná AI historie (#33) a měření CPU/RAM (#35). Navážou analytický balík (#36), životní cyklus aplikace (#37) a společné přijetí Linux balíku (#38). Celá specifikace zatím není dokončená. Zadavatel schválil přípravu nově připnutého runtime; jeho skutečné obrazové a context-mode diagnostiky prošly v oddělené zkušební sadě, finální distribuční ověření ještě zbývá.

Úkoly se realizují podle jejich části **Blocked by** a vlastních kritérií přijetí. Historické odložení implementace ve specifikaci a původních popisech úkolů již bylo nahrazeno výslovným pokynem k realizaci.

## Příprava a spuštění

[Spuštění WebUI z repozitáře](docs/webui-projects.md) popisuje místní Python prostředí, závislosti a spouštěcí skript. [Připravené prostředky Codexu a context-mode](docs/webui-context.md) jsou potřeba pro skutečné AI zpracování. [Linux balík](docs/linux-bundle.md) a [ověření vydání](docs/linux-release.md) popisují distribuovanou variantu.

Git přenáší verzované soubory. Místní prostředí .venv a ignorované experimenty se do klonu nepřenášejí; připravují se na cílovém počítači. Případnou vlastní evidenci běhů uloženou mimo repozitář je nutné přenést zvlášť, má-li na ni druhý počítač navázat.

## Synchronizace další práce

Změny ukládejte do commitů a odesílejte na GitHub. Před zahájením práce na druhém počítači načtěte aktuální větev.
