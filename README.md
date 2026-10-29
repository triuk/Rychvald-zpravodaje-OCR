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

Redesign je navržený a rozdělený do úkolů; jeho realizace dosud nezačala. Zadavatel ji výslovně odložil. Publikace issues a štítek ready-for-agent samy nejsou pokynem začít implementovat.

Po samostatném pokynu k realizaci nemají věcné blokace úkoly [#25](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/25) a [#26](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/26). Další úkoly se zpřístupňují podle jejich části Blocked by. Každý obsahuje vlastní kritéria přijetí.

## Příprava a spuštění

[Spuštění WebUI z repozitáře](docs/webui-projects.md) popisuje místní Python prostředí, závislosti a spouštěcí skript. [Připravené prostředky Codexu a context-mode](docs/webui-context.md) jsou potřeba pro skutečné AI zpracování. [Linux balík](docs/linux-bundle.md) a [ověření vydání](docs/linux-release.md) popisují distribuovanou variantu.

Git přenáší verzované soubory. Místní prostředí .venv a ignorované experimenty se do klonu nepřenášejí; připravují se na cílovém počítači. Případnou vlastní evidenci běhů uloženou mimo repozitář je nutné přenést zvlášť, má-li na ni druhý počítač navázat.

## Synchronizace další práce

Změny ukládejte do commitů a odesílejte na GitHub. Před zahájením práce na druhém počítači načtěte aktuální větev.
