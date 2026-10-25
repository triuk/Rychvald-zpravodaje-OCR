# Cílené opravné cykly

Po dokončení prvního PDF/TXT, skutečného prohlédnutí výstupu a nativní validace
pokračuje `start_autonomous` automaticky cílenými opravami konkrétních nálezů.
První vizuální čtení ani jeho rekonstrukce se neopakují. Volitelné
`defer_corrections: true` ukončí akci po prvním kompletním výsledku; samostatné
tlačítko oprav používá stejnou veřejnou operaci jako automatický průchod.

`start_corrections` přijímá `run_id`, `expected_iteration_id`,
`expected_validation_sha256` a volitelné `environment`. Aktuální identitu poskytuje
`output_results`. Před spuštěním se ověřuje původní run-local runtime, profil,
zdroj, skutečná publikace výstupní kontroly a původní nezávislé vzorky. Zastaralý
výběr ani souběžný další start nespotřebuje nový cyklus a nepošle AI požadavek.

## Trvalý rozpočet a původ oprav

`application/corrections/ledger.json` ukotvuje první kompletní iteraci, zdroj,
profil a hash zmrazených vzorků. Nejvýše tři rezervace mají vlastní `N-UUID`,
rodičovský cyklus a neměnný `plan.json`. Rezervace vzniká pod projektovým zámkem
před workerem a před modelovým tahem. Znovuotevření, druhá instance aplikace ani
nový export stejného průchodu rozpočet nevynulují.

Plán obsahuje konkrétní finding IDs, povolené řádky/logické jednotky, přesné CAS
vstupy, původní zdrojové výřezy s jejich souřadnicemi v rastru a kopie vybraných
diagnostických překryvů. Zadání používá zmrazené `prompts.repair`. Model sám
vrací skutečný nativní patch, zdůvodnění každého cíle a odkazy na přiložené obrazy.
Původní requesty, protokol, thread/turn/connection IDs, JSON, resource hashe a
spotřeba zůstávají v `application/correction-attempts/`; řadič odpověď neopravuje.

Nativní `check-correction` je nepublikující kontrola téhož návrhu.
`publish-correction` pod jedním zámkem znovu ověří původní dokončený modelový JSON,
obrazy, přesný model/high, context-mode doklady, runtime a CAS celého paketu.
Úplný výsledný review musí projít existujícím nativním validátorem. Teprve potom
vznikne patch a jeho historie. Neplatný nebo prázdný návrh nepřepíše review,
PDF/TXT, původní kontroly, historii review ani očekávání. Pokus se uchová a
automatika se zastaví; nejde o bezplatnou smyčku dalších požadavků.

Oprava může změnit přepis, geometrii a pořadí povolených jednotek. Zachovává
ostatní řádky, pozice nesouvisejících jednotek, kandidátní účetnictví a záznamy
čitelných chyb vydavatele včetně jejich znění. Příbuzné registry se předávají
uvnitř jednotlivých nativních line edits. Změna vyžadující jiný rozsah nebo
nedoložené nové čtení zůstává k rozhodnutí revieweru. Zdroj, profil, prostředí,
program, nezávislé vzorky ani přijetí nejsou obsahem modelového patche.

## Nová geometrie, export a historie

Ještě před platnou změnou review a před regenerováním odvozených obrazů se
archivuje původní kompletní iterace. Snapshot obsahuje původní PDF/TXT, reporty,
obrazy kontrol, vstupy, review, checkpointy, zmrazené pakety a původní modelové
doklady se SHA mapou. Velké nezměněné rastry zůstávají v průchodu s původním
hashem. Export používá právě tento `--previous-snapshot`; nevytváří směs starého
PDF s novými kontrolami.

Segmentace se znovu nativně vypočte a porovná po řádcích. Nový geometrický tah
prohlíží změněné řádky, jejich logický kontext, sousedy a dotčené zdrojové vzorky.
`correction_scope` odděluje nově prohlédnuté položky od skutečně nezměněných.
`historical_observations` uchovává původní modelové řádky, jejich checkpoint,
protokol a oddělené archivní pixelové aliasy. Nejde o doplnění původního JSON ani
o tvrzení, že nový model prohlédl staré položky. Nativní ověření kontroluje
nezměněné produkty a přesnou historii; GUI tyto dvě skupiny zobrazuje odděleně.
Nezměněné otevřené geometrické nálezy se přenášejí do výstupní kontroly.

Každý nový export má novou identitu PDF/TXT a znovu provede všechny povinné
technické kontroly a kompletní původní sadu vzorků. Následuje skutečné prohlédnutí
aktuálních exportovaných stran a nativní validace. Očekávání, terminální LF
výjimka extraktoru a význam původních validačních návratových kódů se nemění.

`correction_status` pouze čte uložené výsledky a aktuální skutečný validační stav.
`correction_history` stránkuje artefakty pomocí `offset` a `limit` (1–200).
`open_correction_artifact` vyžaduje zaznamenanou cestu a přesný hash, ověří archiv
a požádá o externí otevření. Otevření neznamená prohlédnutí nebo přijetí.

## Dřívější zastavení a skutečný stav

Verzovaná identita neúspěchu obsahuje stabilní finding ID, stránku/oblast a
skutečný literální výsledek extraktoru s původním očekáváním. Nezahrnuje nové PDF
UUID, čas, výstupní cestu ani modelové zdůvodnění. Nezměněný neúspěch některého
vybraného cíle zastaví další tah jako `repeated_failure`. Jiné zbylé neúspěchy
mohou využít nejvýše tři cykly; pak nastane `limit_reached`. Samotná obecná
aproximace geometrie není důvodem k dalšímu celému čtení; zbývá `awaiting_input`.

Každý dokončený pokus má samostatný neměnný `outcome.json`. Rozpočet, důvod
zastavení automatiky, stav workeru, nativní validace a přijetí jsou oddělené.
Neplatný návrh nebo limit nemění `ready_with_open_items` na úspěch. Povinná
technická chyba zůstává neúspěchem kontrol; automatika nemění implementaci.
Nový export obnovuje `acceptance: not_recorded`.

Neuzavřená rezervace odmítá nový start. Výslovné `reconcile_autonomous` a
`resume_autonomous` pokračují se stejným rodičem, opravným pokusem a cyklem.
Ověřují původní archivované předky, současné vstupy a přesnou podřízenou kontrolu
výsledku. Restart ani další pozastavení nepřiděluje nový rozpočet.

Nativní zápisy mají před změnou trvalý záměr: patch se seznamem původních a
nových hashů, export s předem rezervovaným UUID a neměnný výsledek cyklu.
Po přerušení se dokončí jen doložené chybějící zápisy téhož záměru. Již vytvořené
PDF/TXT, výsledky validace a rozhodnutí o zastavení se převezmou beze změny.
Záměr patche uložený těsně před jeho propojením do knihy cyklů se vyhledá pouze
v původním rezervovaném cyklu. Před doplněním propojení se znovu ověří původní
návrh modelu, archiv vstupů a úplný nativní výsledek transakce; samotná shoda
identifikátorů ani hash uvedený tímto nepřipojeným záměrem nestačí.
Částečně zapsaná vazba nebo již uložená fáze rezervace patche vyžaduje ověření
i při chybějícím souboru záměru; prázdná hodnota nesmí povolit nové publikování.
Dokončený původní modelový protokol lze místně znovu ověřit a zveřejnit bez nového
tahu; chybějící nebo neověřitelný výsledek zůstává zablokovaný.

Nejisté doručení se neopakuje. Prokazatelně odmítnutý, neúspěšný nebo přerušený
původní tah smí po výslovné obnově pokračovat pouze se samostatným neměnným
záznamem původního požadavku, ověření a navazujícího požadavku. Původní fyzický
protokol se nepřepisuje. Globální výpadek AI i místně nedokončený potomek drží
rezervovaný cyklus a přijetí další práce; pravdivý stav doručení zůstává oddělený
od tohoto zákazu. Historické čtení podle cesty a SHA nikdy nenahrazuje kontrolu
aktuálních vstupů před publikací.
