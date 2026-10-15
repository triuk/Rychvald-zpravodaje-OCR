# Tickety pro WebUI OCR

Parent: [specifikace #9](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/9). Rozdělení schválené zadavatelem; všech 14 ticketů bylo publikováno dne 15. 10. 2026 pomocí `to-tickets` se štítkem `ready-for-agent`.

Zpětně ověřeno všech 14 těl issues, jejich štítky a 16 blokujících hran. Parent #9 má nezměněné znění, název, stav a štítky. Blokující vazby jsou výslovně uvedené v sekcích `Blocked by`; připojené GitHub nástroje nativní dependency operace nevystavují.

Každý ticket dodává ověřitelný funkční celek přes společné veřejné operace, GUI, trvalá data a testy. Stávající procesové rozhraní OCR zůstává zachované; samostatný široký prefaktoring nebyl nutný. Pomocné lokální kopie ticketů nejsou verzované; úplné zadání je vždy v odkazovaném GitHub issue.

## Výchozí stav pro implementaci

Dokončený nativní kódový základ je [commit 8ebb859](https://github.com/triuk/Rychvald-zpravodaje-OCR/commit/8ebb85937f15e3a4792a2c87b19ac8103e2ce53d). Nové implementační větve vycházejí z `main` obsahujícího tuto první etapu a schválenou dokumentaci WebUI. Starší `main` před začleněním nativní etapy není vhodným základem pro tickety #10–#23.

## Publikované tickety

1. **[#10 — Přehled projektů vydání ve spustitelném WebUI](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/10)**
   Blokováno: nic; lze začít ihned.
   Dodá: Operátor spustí WebUI, otevře existující evidenci a v levém sloupci vybere vydání a jeho dosavadní průchod se skutečným stavem.
   Pokrytí: B9.

2. **[#11 — Import a nový pojmenovaný průchod z externího profilu](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/11)**
   Blokováno: [#10](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/10).
   Dodá: Operátor naimportuje PDF nebo složku, vybere externí profil a založí pojmenovaný průchod s neměnnou kopií použitých promptů a parametrů.
   Pokrytí: B5, B9.

3. **[#12 — Místní příprava s živými checkpointy v GUI](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/12)**
   Blokováno: [#11](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/11).
   Dodá: Operátor spustí místní přípravu nového průchodu a sleduje ověření prostředí, rastry a OCR kandidáty až k uloženému ověřenému checkpointu.
   Pokrytí: B6, B7, B9.

4. **[#13 — Přihlášení a skutečné obrazové ověření GPT-6.1 Sol high](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/13)**
   Blokováno: [#12](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/12).
   Dodá: Operátor z GUI ověří přístup účtu ChatGPT k přesnému modelu a úrovni high skutečným diagnostickým čtením připraveného obrazového podkladu.
   Pokrytí: B2, B7.

5. **[#14 — Funkční context-mode v AI kroku a izolace průchodů](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/14)**
   Blokováno: [#13](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/13).
   Dodá: Operátor ověří z GUI celou požadovanou AI kombinaci včetně context-mode, jeho skutečného směrování a vlastní znalostní evidence každého průchodu.
   Pokrytí: B2, B7.

6. **[#15 — Úplný vizuální přepis s rekonstrukcí a nejistotami](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/15)**
   Blokováno: [#14](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/14).
   Dodá: Operátor spustí skutečné AI čtení všech stránek malého vydání a získá zdrojově doložený přepis, logické jednotky a evidenci nevyřešených míst.
   Pokrytí: B3, B4, B9.

7. **[#16 — Geometrie a nezávislá očekávání jako checkpoint](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/16)**
   Blokováno: [#15](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/15).
   Dodá: Z přečteného vydání vznikne ověřený podklad pro export: pořadí článků, geometrie a kontrolní vzorky odvozené ze zdrojového skenu.
   Pokrytí: B3, B4, B8.

8. **[#17 — První OCR PDF/TXT a pravdivé kontroly v GUI](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/17)**
   Blokováno: [#16](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/16).
   Dodá: Operátor dokončí celý první automatický průchod od importu k PDF/TXT, výsledkům technických i obsahových kontrol a podkladům pro reviewer.
   Pokrytí: B3, B4, B8, B9.

9. **[#18 — Cílené opravné cykly se zachováním exportních iterací](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/18)**
   Blokováno: [#17](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/17).
   Dodá: Při konkrétním nálezu aplikace cíleně opraví data, znovu exportuje a ověří výsledek; operátor dohledá celý průběh i předchozí PDF.
   Pokrytí: B8.

10. **[#19 — Pozastavení, přerušení a pokračování průchodu z GUI](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/19)**
   Blokováno: [#17](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/17).
   Dodá: Operátor pozastaví nebo přeruší místní či AI práci, zavře aplikaci a po dalším spuštění naváže na poslední ověřený bod prvního úplného průchodu.
   Pokrytí: B6, B7.

11. **[#20 — Řaditelná fronta a obsluha výpadků AI](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/20)**
   Blokováno: [#19](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/19).
   Dodá: Operátor řídí dávku s jedním aktivním průchodem; chyba jednoho PDF neblokuje další a globální nedostupnost AI frontu bezpečně pozastaví.
   Pokrytí: B6.

12. **[#21 — Auditovatelné časy, tokeny a srovnávací ceny kroků](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/21)**
   Blokováno: [#13](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/13).
   Dodá: Operátor u místních a AI kroků uvidí trvalé časy a ověřenou spotřebu ve třech kategoriích, barevné odhady cen a dohledatelné vstupy měření.
   Pokrytí: B7.

13. **[#22 — Porovnávání průchodů a ověřené sdílení místní přípravy](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/22)**
   Blokováno: [#17](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/17), [#21](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/21).
   Dodá: Operátor porovná dva úplné průchody stejného PDF s různými profily, přičemž uvidí dopad změny a přesně pozná převzatou místní práci.
   Pokrytí: B5, B7.

14. **[#23 — Přenosný Linux balík a úplné přijetí B1–B9](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/23)**
   Blokováno: [#18](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/18), [#20](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/20), [#22](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/22).
   Dodá: Operátor převezme samostatnou Linux aplikaci s přibaleným OCR, Codexem a context-mode a doloženým celým dohodnutým pracovním postupem.
   Pokrytí: B1, B2, B3, B4, B5, B6, B7, B8, B9.

## Paralelní větve

- Začíná [#10](https://github.com/triuk/Rychvald-zpravodaje-OCR/issues/10); poté #11 → #12 → #13.
- Po #13 lze souběžně pracovat na context-mode #14 a metrikách #21.
- Hlavní OCR větev pokračuje #14 → #15 → #16 → #17.
- Z #17 se oddělí opravné cykly #18 a obnova #19 → fronta #20.
- Porovnávání #22 potřebuje #17 a #21.
- Závěrečný balík a společné přijetí #23 potřebují #18, #20 a #22.

Diagnostické ověření modelu #13 je samostatně ověřitelný přírůstek; plná požadovaná kombinace pro autonomní OCR zahrnuje také context-mode z #14. Přerušení během opravného cyklu a zachování jeho počítadla se společně ověří v #23, aby mezi #18 a #19 nevznikla umělá závislost.

## Pravidla práce

Pracovat na ticketu až po dokončení všech jeho blokujících issues. Parent #9 nebyl při rozdělení upravován ani zavírán. Publikace ticketů není provedením implementace ani důkazem splnění B1–B9.
