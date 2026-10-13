# OCR rychvaldských zpravodajů

Převod naskenovaných vydání Rychvaldského zpravodaje do podoby s věrným, vyhledatelným a kopírovatelným textem. Pojmy vycházejí z požadavků zadavatele; otevřená návrhová rozhodnutí jsou vedena samostatně.

## Jazyk projektu

**Zdrojový sken**:
Vstupní PDF zachycující stránky zpravodaje, které slouží jako předloha rozpoznání a porovnání výsledku.
_Nepoužívat_: raw jako název výsledku, originál bez rozlišení od papírového výtisku.

**Projekt vydání**:
Samostatný pracovní celek jednoho zdrojového PDF, jeho přepisu, nevyřešených míst, revizí a výsledných podob. Provází vydání od zahájení OCR po konečnou ruční revizi a opravu.
_Nepoužívat_: repozitář jako synonymum; jeden repozitář může zpracovávat mnoho projektů vydání.

**OCR PDF**:
Výsledné PDF s rozpoznaným textem, který lze vyhledávat, označovat na příslušném místě stránky a kopírovat.

**Pořadí čtení**:
Logická posloupnost textu uvnitř článku a mezi články, včetně návazností přes sloupce a stránky. Souvislý text dokončí článek před přechodem k dalšímu; samostatné články řadí podle místa jejich začátku.

**Rekonstrukce textu**:
Obnovení špatně čitelného znění z obrazu, jazykového kontextu nebo odpovídajícího externího dokladu.

**Chyba vydavatele**:
Chybné znění, které je již v tištěné předloze a které věrný přepis zachovává. Eviduje se odděleně s vysvětlením chyby.
_Nepoužívat_: chyba OCR; ta vzniká při rozpoznávání předlohy.

**Text článků**:
Samostatný textový výstup rozpoznaného vydání se souvislým zněním článků v jejich logickém pořadí.

**Nevyřešené místo**:
Úsek, jehož správné znění se nepodařilo dostatečně určit a který čeká na doplnění zadavatelem, případně z papírového výtisku.

**Vydání čekající na doplnění**:
Rozpoznané vydání s alespoň jedním nevyřešeným místem, u kterého se čeká na znění od zadavatele. Dokončení ostatních vydání se tím nezastavuje.

**Autonomní fáze OCR**:
Zpracování zpravodajů před následnou kontrolou všech výsledných PDF zadavatelem v revieweru; zahrnuje jeho doplnění nevyřešených míst.

**Manifest revize**:
Výstup z nástroje `pdf-ocr-reviewer` obsahující místa a poznámky, které zadavatel označil pro následnou opravu rozpoznaných PDF.
_Nepoužívat_: seznam nevyřešených míst jako synonymum; ten vzniká již při OCR.
