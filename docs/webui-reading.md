# První úplné vizuální čtení

V pojmenovaném průchodu nejprve dokončete místní přípravu, obrazové ověření
požadovaného modelu a skutečné ověření context-mode. Tlačítko „Spustit vizuální
čtení“ vyžaduje stejný profil a přesné runtime prostředky jako oba dokončené
diagnostické kroky. Používá spravovaný účet ChatGPT, `gpt-6.1-sol` a `high`.

První tah přiloží všechny původní rastry a jejich identitu. AI přečte všechny
stránky bez OCR kandidátů a sama vytvoří potvrzené nebo částečně nevyřešené
řádky, logické jednotky a příslušnou evidenci. V této fázi adaptér povoluje
pouze původní obrazové podklady a statistiku context-mode. Spuštění shellu,
čtení textových souborů nebo nástroj kandidátů fázi nezpřístupní k publikaci.

Druhý tah používá existující stránkované místní dotazy `ocr_query`, původní
obrazy `ocr_image` a validaci `ocr_validate`. Každý místní kandidát musí mít
přiřazený přezkoumaný řádek nebo výslovný důvod vyřazení. Přidané a změněné
čtení vyžaduje nové skutečné zobrazení příslušného původního rastru. Úplný
návrh se validuje jako celek; neúplná struktura ani úspěšný návrat tahu samy
nevytvoří zveřejněný přepis. Potvrzení čtení vždy pochází z odpovědi modelu.

Adaptér před zveřejněním znovu odvodí důkaz z původního JSON-RPC: dva dokončené
tahy a jejich konečné odpovědi, skutečně přiložené obrazy, přesný model/úsilí,
úspěšné dotazy a validaci přesného návrhu, obrazové odpovědi, použitý
context-mode a příslušné důvěryhodné hooky. Výsledek se váže na zdroj,
inventář kandidátů, nezměněný profil a manifest průchodu. Nativní proces pak
pod zámkem ověří celý dokument a očekávaný hash předchozího přepisu před
jediným atomickým zápisem `review.json`.

GUI ukazuje skutečnou fázi, počty přečtených stránek/řádků/jednotek, použitý
profil, původní zadání, odpovědi a odkazy na důkazy. Zveřejněný text a evidence
nejistot/chyb vydavatele jsou pouze ke čtení. GUI neobsahuje formulář pro
ruční přepis nebo doplňování. Čitelné chyby vydavatele zůstanou ve znění;
nejasná část má `[NEČITELNÉ]` a samostatný záznam se zdrojovým obrazem a
stavem čekajícím na doplnění. Dokončené čtení ještě neznamená geometrii,
export PDF/TXT, závěrečnou validaci ani přijetí zadavatelem.

Veřejné operace `Application.dispatch` jsou `start_reading({run_id})` a
`reading_status({run_id})`. Nativní rozhraní přidává `reading-input RUN`,
`check-reading RUN --proposal FILE` a `publish-reading RUN --proposal FILE`.
`reading-input` vytváří pouze kandidátní `reading-draft.json`; `check-reading`
nemění zveřejněný přepis. Tyto operace zachovávají původní procesovou smlouvu.

Pokus má vlastní adresář `application/reading-attempts/ATTEMPT/` s manifestem,
původními protokoly a žádostmi, zdrojovou a závěrečnou odpovědí, jednotlivými
prozatímními návrhy a přesným publikovaným návrhem. Neúspěšné a přerušené
pokusy se nemažou a automaticky se neopakují. Spotřeba obou skutečných tahů
patří do stejného metrického přehledu s původními zdroji, spojeními a poli;
neznámé údaje zůstávají neznámé.

`tools/prepare_reading_cases.py` připraví nový dvoustránkový rastrový vstup,
nový obtížný výřez skutečné předlohy a zveřejní před AI závazek nezávislých
očekávání. Náhodná znění drží pouze vlastní hostitelský proces. Očekávání
odhalí až po výslovném kontrolním signálu navázaném na ověřenou atomickou
publikaci a po opětovném ověření původního závazku. Tento proces při přerušení
neukončujte naslepo. `tools/smoke_webui_reading.py` používá skutečná tlačítka
nativního GUI; očekávaný přepis nečte a potvrzení modelu nevyplňuje. Příznaky
`--run-preflights` a `--run-reading` výslovně spouštějí skutečné AI tahy.
Bez nich lze ověřit místní přípravu nebo obnovení již uloženého výsledku.
