# Marine Populations Policy Chatbot

A question-answering service for policymakers, CCAMLR delegates, and others who need FishCast results in plain language. Answers are supposed to come from a pinned xAI Collection (project docs, the limitations note, and benchmark files when a local run has produced them), with the file name cited.

This is Phase 1 and Phase 2 of the rollout:

- Phase 1: collection build, `POST /chat` (Server-Sent Events), audit log, Streamlit UI, disclaimer.
- Phase 2: `POST /brief` (one-page brief, human-review flag set by the server) and `GET /sources` (passages for the last answer), shown in the UI.
- Phase 3, not built: embed the chat in `viz/app/`, keep history somewhere other than the API process, and add richer filters in that app.
- Phase 4, not built: other languages.

## Why it is not `viz/api/`

`viz/README.md` reserves `viz/api/` for the data API that will serve predictions, time series, and benchmark tables to the map. The chatbot is a separate process with its own keys, collection, and UI, so it lives in `viz/chatbot/`. The map can call it later without mixing those routes into the data API.

## Layout

| Path | Role |
| --- | --- |
| `viz/chatbot/app.py` | FastAPI app: `/health`, `/chat`, `/brief`, `/sources` |
| `viz/chatbot/grok.py` | xAI SDK call (`collections_search`, optional `web_search`) |
| `viz/chatbot/prompt.py` | System prompt from the spec, disclaimer, brief instructions |
| `viz/chatbot/build_collection.py` | Create or fill the collection |
| `viz/chatbot/catalog.py` | Files and metadata (`doc_type`, `year`, `region`, `skill_status`, `preprocessing_version`) |
| `viz/chatbot/collection_pin.json` | Collection version label committed for reproducibility |
| `viz/chatbot/knowledge/limitations.md` | Skill and data caveats, taken from this repository |
| `viz/chatbot/knowledge/benchmark_schema.md` | Column names only. No scored table is committed |
| `viz/chatbot/knowledge/external/` | Placeholder for CCAMLR texts and open papers the team adds |
| `viz/chatbot/ui.py` | Streamlit UI |
| `tests/test_policy_chatbot.py` | Unit tests. The xAI client is mocked |

## SDK and model

Checked against PyPI and the xAI docs on 3 November 2026:

- Package: `xai-sdk==1.21.0` (requires Python 3.10+).
- Default model: `grok-4.7`, set with `XAI_MODEL`. The docs describe it as the flagship model with configurable reasoning, and the collections example uses it. `XAI_REASONING_EFFORT` defaults to `high`.
- Retrieval tool: `xai_sdk.tools.collections_search(collection_ids=..., limit=..., instructions=..., retrieval_mode="hybrid")`.
- Citations: `include=["inline_citations", "collections_search_call_output", "verbose_streaming"]`.

`collections_search` in 1.21.0 has no metadata `filter` argument. `Client.collections.search` does not expose one either, even though the REST documents-search page shows a `filter` string. This service writes an AIP-160 expression (`doc_type="limitations" AND region="Southern Ocean"`) into the tool's `instructions`, repeats it in a second system message, and returns it on the response as `filter_expression`. If a newer SDK declares a `filter` parameter, `make_collections_tool` passes the expression there as well. Treat filters as a retrieval instruction, not a guarantee that other documents cannot appear, until that parameter exists.

Web search is off unless `CHATBOT_ENABLE_WEB_SEARCH=true`. Leave it off for policy answers.

## Setup

From the repository root, with Python 3.10 or newer:

```bash
python -m venv .venv-chatbot
source .venv-chatbot/bin/activate
pip install -r viz/chatbot/requirements.txt
cp viz/chatbot/.env.example viz/chatbot/.env
```

`pip install -e ".[chatbot]"` installs the same extra. The FishCast training install (`requirements.txt` at the repo root) does not include these packages. CI installs only `viz/chatbot/requirements-test.txt` (FastAPI, httpx, python-dotenv) so the test run does not pull the SDK or Streamlit.

Keys stay in the environment or in `viz/chatbot/.env`. That file is gitignored.

## Build the collection

Dry run (no network, no keys). Prints every file, its metadata, and a SHA-256:

```bash
python -m viz.chatbot.build_collection --dry-run
```

Create a collection and upload. The management key needs `AddFileToCollection` and permission to create collections:

```bash
python -m viz.chatbot.build_collection --create
```

The script writes `viz/chatbot/.collection_state.json` (gitignored) and prints `collection_id`. Put that id in `XAI_COLLECTION_ID`.

To upload again into an existing collection that already has the same field definitions:

```bash
python -m viz.chatbot.build_collection --collection-id "$XAI_COLLECTION_ID"
```

Bump `collection_version` in `collection_pin.json` when the document set changes, then rebuild. The API reports that version on every response. The live collection id is not committed.

Optional files, uploaded only when they exist and are under 5 MB:

- `artifacts/benchmark/benchmark_table.csv`
- `artifacts/benchmark/benchmark_summary.json`
- `artifacts/**/metrics.json`
- `benchmark_table.csv` or `metrics.json` at the repo root

Nothing scored is in git today. Do not paste numbers from memory into the collection. CCAMLR PDFs and papers are not downloaded. Add a file under `knowledge/external/` and a row in `catalog.py` when the team has the right to upload it. That folder is gitignored, so the PDF stays on disk unless someone force-adds it.

## Run the API and the UI

```bash
uvicorn viz.chatbot.app:app --host 0.0.0.0 --port 8000
streamlit run viz/chatbot/ui.py
```

Docker, from the repository root, after copying `.env.example` to `.env`:

```bash
docker compose --env-file viz/chatbot/.env -f viz/chatbot/docker-compose.yml up --build
```

The image is Python 3.10 and the chatbot requirements only. It does not install PyTorch. The API is on port 8000 and Streamlit on port 8501.

`/health` is open so a probe can reach it. It returns the disclaimer and the collection version. `/chat`, `/brief`, and `/sources` use basic auth when `CHATBOT_BASIC_AUTH_PASSWORD` is set. The default rate limit is 30 requests a minute per client, in memory, in a single process.

### `POST /chat`

```json
{
  "message": "What are the limitations of the climate-only models?",
  "conversation_id": "optional-session-id",
  "filters": {"doc_type": ["limitations", "project_doc"]},
  "stream": true
}
```

`stream` defaults to true: Server-Sent Events named `meta`, `token`, and `done`. `"stream": false` returns one JSON object. Every payload includes `disclaimer` and `human_review_required`.

### `POST /brief`

```json
{"topic": "What should a delegate keep in mind about climate-only skill?"}
```

The JSON includes `markdown`, `human_review_required: true`, and `human_review_note`. The flag is set by the server. The model cannot turn it off. The markdown starts with the disclaimer.

### `GET /sources?conversation_id=...`

Passages and citation URIs stored for the last answer in that conversation. History is kept in the API process only (last 20 messages) and is lost on restart.

## Governance

- The disclaimer is always: "Decision-support tool based on FishCast model outputs and cited literature. Not official advice." It is on `/health`, every chat and brief payload, the brief markdown, and the Streamlit banner.
- The system prompt in `prompt.py` is the spec text. Brief instructions and filter instructions are extra system messages, not edits to that prompt.
- Do not claim climate-only skill. `knowledge/limitations.md` is the statement to retrieve, and it only repeats what this repository already says: climate-only models show no skill yet; the climate-only GP's test ROC-AUC is about 0.35 (hotspots ranked backwards); the longitude bug in the current `krillcast_merged.csv` is fixed in `scripts/data/build_dataset.py`, and the file has not been rebuilt.
- `docs/FishCastMethodology.md` is a draft. The limitations note tells the model to prefer the limitations note when they conflict.
- Any text used in a formal submission needs a person to review it. The brief says so in a field the server sets.
- The audit log is JSONL (`CHATBOT_AUDIT_LOG`): query, filters, collection id and version, model, passages, citations, answer, disclaimer. API keys and the basic-auth password are redacted. The log directory is gitignored.
- The collection version in `collection_pin.json` is the reproducibility pin. The collection id stays in the environment.

## Tests

```bash
pip install -r viz/chatbot/requirements-test.txt
pytest tests/test_policy_chatbot.py -q
ruff check viz/chatbot tests/test_policy_chatbot.py
```

The tests do not call xAI and do not need a key. They mock `load_sdk`. If `xai-sdk` happens to be installed, one test checks that `collections_search` still has no `filter` parameter.
