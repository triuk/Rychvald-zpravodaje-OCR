# Řídit AI kroky OCR přes Codex app-server

Autonomní průchod OCR bude řídit AI kroky přes místní Codex app-server s přihlášením účtem ChatGPT, zatímco místní OCR zůstane odděleným procesem podle ADR 0003. Volíme toto propojení místo ručního zadávání AI úloh mimo aplikaci nebo nového přístupu přes API klíč, aby GUI mohlo řídit celý průchod, sledovat dostupné události a spotřebu a uchovat historii pro porovnávání. Cena odvozená z API sazeb bude výslovně srovnávací odhad, nikoli vykázaná skutečná útrata za průchod v rámci předplatného; rozhodnutí potvrdil zadavatel v Q19–Q20 dne 14. 10. 2026.

V Q35 zadavatel podmínil přibalení konkrétní ověřené verze Codexu podporou `gpt-6.1-sol` s úrovní `high` a funkčním context-mode. Součástí přijetí balíku proto bude skutečný integrační tah a ověření nástrojů i hookového směrování context-mode; samotný katalog modelů nebo registrace MCP nejsou dokladem splnění této podmínky.
