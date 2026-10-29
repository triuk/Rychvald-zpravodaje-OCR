# Schválené úkoly redesignu GUI OCR

Rodičovská specifikace: [#24](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/24).

Všech 14 schválených úkolů je publikováno a ověřeno se štítkem **ready-for-agent**. Každý obsahuje vlastní kritéria přijetí a skutečné odkazy na blokující úkoly. Rodičovské issue nebylo změněno ani uzavřeno. Realizace zůstává odložená do dalšího pokynu zadavatele.

| Původní číslo | GitHub issue | Úkol | Blokováno |
|---|---|---|---|
| 1 | [#25](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/25) | Přehledné rozhraní s projekty, průchody a záložkami | Žádné |
| 2 | [#26](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/26) | Klikací výběr složek, vstupních PDF a profilů | Žádné |
| 3 | [#27](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/27) | Trvalé globální a projektové předvolby modelu a reasoningu | [#25](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/25) |
| 4 | [#28](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/28) | Výjimky modelu a reasoningu pro jednotlivé AI činnosti | [#27](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/27) |
| 5 | [#29](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/29) | Příprava s vloženým náhledem skenu a překryvem OCR | [#25](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/25) |
| 6 | [#30](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/30) | Zachovaný náhled prvního dokončení Přepisu | [#29](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/29) |
| 7 | [#31](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/31) | Zachovaný náhled Pořadí a geometrie před opravami | [#29](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/29) |
| 8 | [#32](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/32) | Skutečné kontrolní PDF v Sestavení a kontrolách | [#29](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/29) |
| 9 | [#33](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/33) | Úplné AI prompty a spotřeba v přehledu fází | [#25](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/25) |
| 10 | [#34](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/34) | Trvalá historie všech místních kroků ve fázích | [#25](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/25) |
| 11 | [#35](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/35) | CPU a špičková RAM místních kroků | [#34](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/34) |
| 12 | [#36](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/36) | Automatický analytický balík pro Codex po celém běhu | [#28](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/28), [#30](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/30), [#31](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/31), [#32](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/32), [#33](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/33), [#35](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/35) |
| 13 | [#37](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/37) | Práce na pozadí a bezpečné ovládání aplikace | [#25](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/25) |
| 14 | [#38](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/38) | Přijetí redesignu ve spustitelném Linux balíku | [#26](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/26), [#36](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/36), [#37](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/37) |

Závislosti jsou výslovné odkazy v části **Blocked by**. Připojený GitHub konektor neposkytuje operace pro nativní blokující vazby, proto nebyly tyto odkazy vydávány za nativní vztahy.

Po samostatném pokynu zahájit realizaci nemají věcné blokace úkoly #25 a #26. Další úkoly se otevírají podle dokončení předchůdců; značka ready-for-agent sama neodvolává odklad realizace.

Po publikaci byly z GitHubu znovu načteny všechny úkoly a ověřena shoda názvů, úplných popisů a štítku. Ověřeno také nezměněné tělo, název, stav a štítky rodičovské specifikace.


Místní zadání: [implementační specifikace 0003](../specs/0003-webui-ergonomics-and-phase-previews.md) a [návrhová rozhodnutí](webui-ocr-gui-redesign.md).
