# External CCAMLR and literature documents

This folder is a placeholder. Phase 1 does not ship CCAMLR reports or scientific papers.

The repository gitignore ignores every `external/` directory, so a PDF dropped here is not committed. That is intentional. The build script can still upload a local file after you add a row to `catalog.py`. Force-add a file only when the team has decided it belongs in git.

Add a file here only when the team has the right to upload it (for example an open CCAMLR decision summary the delegation already holds, or an open-access paper). Then add a row to `viz/chatbot/catalog.py` with `doc_type` of `policy` or `literature`, plus `year`, `region`, `skill_status`, and `preprocessing_version`.

Do not scrape publisher sites. Do not commit copyrighted papers. Do not ask the chatbot to summarise a paper that is not in the collection.

Until a file is added, the chatbot should say the collection does not contain that report or paper. `viz/chatbot/knowledge/limitations.md` is the statement of model skill.
