# Fronta průchodů OCR

Panel **Fronta průchodů OCR** ukládá ručně zvolené pořadí. Lze zařadit jedno
zdrojové PDF s prohlédnutým profilem nebo již existující pojmenovaný průchod.
Zařazení nespouští AI. Tlačítko **Spustit / pokračovat ve frontě** výslovně
povolí zpracování. Čekající položky lze posunout výše a níže; běžící položka
se nepřeskupuje. Výběr detailu jiného průchodu nemění aktivní položku fronty.
Evidence se nepřepíná, dokud tato aplikace vlastní běžící frontu, ani když fronta
právě čeká na cizí vykonávanou práci. Nejdříve ji výslovně pozastavte.

V jedné evidenci se zpracovává jeden průchod, i přes více procesů aplikace.
Stejný zámek chrání samostatné ruční kroky a opravné cykly. Autonomní rodič
jej drží také mezi svými kroky a opravami. Po pádu vlastníka se ověřuje trvalý
záznam původní práce: samotný volný systémový zámek nepovoluje nové spuštění.

Chyba konkrétního vstupu nebo dokončený výstup čekající na doplnění uvolní místo
dalšímu vydání. Výsledek, nálezy, validace a samostatné přijetí zadavatelem se
zachovají. Ztráta přihlášení, limit AI, nedostupný požadovaný model či spojení
zastaví celou frontu. U položky je důvod a rozbalitelný odkaz na původní
protokol s hashem, identitou pokusu, vlákna a tahu a původní strukturovanou chybou.
Klasifikace vychází z typovaných kódů a původních odpovědí, nikoliv z hledání
slov v přeložené zprávě. Neznámá chyba poskytovatele frontu bezpečně zastaví.

**Pozastavit po jednotce** uzavře přijímání dalších místních jednotek a AI tahů.
**Přerušit nyní** použije původní řízení přerušení; poskytovatel nemusí potvrdit
ukončení. Zavření a opětovné otevření aplikace frontu samo nespouští. Důvod
globálního zastavení i ruční pořadí zůstanou uložené.

Také samostatný ruční krok má trvale uložený záměr a přesnou vazbu na svůj
podřízený pokus před spuštěním procesu. Konec místního workeru není důkazem
odmítnutí AI. Nejasné původní zadání zachová stav `reconciliation_required`,
vlákno/tah a hash protokolu v `application/manual-execution.json`; nová práce
se nepřijme. `queue_status.manual_execution` a rozbalitelná evidence fronty
ukazují původní stav i bez autonomního rodiče. Původní protokol se nepřepisuje.

Před pokračováním aktivní položky použijte **Ověřit původní pokus**. Kontrola
`reconcile_autonomous` ověří přesný původní tah odděleným podporovaným čtením
vlákna a nezávisle ověří místní checkpoint. Teprve následné výslovné spuštění
fronty předá přesné `item_id`, `run_id`, `attempt_id` a `reconciliation_id`.
Obnovené připojení samo není důkaz, že předchozí zadání nebylo přijato.
Neznámé potvrzení ani dokončený tah bez obnovitelného místního výsledku se
neodesílají znovu. Stejně se chrání i ruční spuštění jiného průchodu.
Rozpracovaný kombinovaný opravný cyklus respektuje stávající bezpečné zastavení
`correction_reconciliation_required`; fronta neobchází jeho kontrolu ani rozpočet.

## Veřejné operace a evidence

Všechny operace používají `Application.dispatch`, stejnou návratovou obálku a
události jako GUI. `queue_changed` nese revizi a stav; `queue_status` umožní úplné
obnovení pohledu i po resetu kurzoru událostí.

| Operace | Vstup a účinek |
| --- | --- |
| `enqueue_run` | Stabilní `request_id` a buď `run_id`, nebo jedno `source_path` + `name` + `profile_path` + `profile_sha256`. Volitelně prostředí a místní donor. Opakování vrátí tutéž položku. |
| `queue_status` | Pořadí, položky, stav, důvod čekání, původní pokus a historie. Neprovádí inference ani opakování práce. |
| `reorder_queue` | Úplná permutace čekajících `item_ids` a `expected_revision`. Zastaralé pořadí vrátí `queue_conflict`. |
| `pause_queue`, `interrupt_queue` | Nejprve uloží úmysl, potom ovládají přesného aktivního rodiče. |
| `resume_queue` | Bez aktivní položky výslovně spustí čekající dávku. S aktivní položkou vyžaduje její přesnou identitu a původní důkaz usmíření. |

Schéma1 v `application/queue.json` obsahuje revizi, identitu evidence, požadovaný
stav, aktivní položku, pořadí a historii. Položka váže vydání, průchod, původní
požadavek, volby, pokus a intervaly čekání. Zámek `.queue.lock` chrání změny mezi
procesy; `.application-execution.lock` vlastní vykonávanou práci. Identita položky
a předem rezervovaného rodiče se zapíše před jeho spuštěním. Chybějící nebo
pozměněná původní vazba zastaví pokračování.

Záměr vytvoření pojmenovaného průchodu se uloží před nativním zveřejněním.
Při ztracené odpovědi na vytvoření se tentýž požadavek znovu nevytváří a vrátí
`enqueue_recovery_required`. Prohlédněte již existující průchody a zařaďte
přesný existující průchod novým požadavkem. Zařazení průchodu s původním pokusem
vyžaduje kontrolované pokračování, nikdy nové automatické čtení.

Metriky čtou zaznamenané intervaly fronty a důvody. Práce probíhající při žádosti
o pozastavení se nezapočítá zároveň jako čekání. Otevřené intervaly zůstávají
neukončené; nepozorované mezery nejsou automaticky čekáním. Původní protokoly,
spotřeba, částečné/neznámé údaje a pravidla deduplikace tahů se zachovají.

## Ověření

`tests/test_webui_queue.py` používá společné veřejné operace, skutečný oddělený
nativní proces a výslovně syntetické app-server peers. Zahrnuje více vydání,
změnu pořadí, poškozené PDF, otevřené nálezy, globální výpadek a výslovné
pokračování, restart, dva procesy aplikace, neznámé potvrzení, dokončený původní
tah bez místního výsledku, přeživší nativní proces a ztracenou odpověď zařazení.
Tyto testy nejsou dokladem skutečné práce vzdáleného modelu ani kontroly GUI.
