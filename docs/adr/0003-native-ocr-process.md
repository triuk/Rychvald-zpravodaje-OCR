# Nativní OCR proces připravený pro reviewer

První etapa připraví nativní OCR prostředí a samostatný proces pro Linux, který zachová ověřené závislosti a bude později ovládán z revieweru. Volíme jej místo kontejneru požadovaného za běhu, protože cílem je aplikace spouštějící OCR, komunikaci s Codexem a ruční revizi; verzované nativní prostředky zajistí obnovitelnost prostředí bez Dockeru u uživatele. Oddělený proces dovolí rozvíjet OCR a reviewer bez vynucení stejného Python runtime; Windows a rozšíření UI následují po první etapě podle rozhodnutí Q16–Q18.
