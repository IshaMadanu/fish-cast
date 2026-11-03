"""Create an xAI Collection and upload the FishCast policy documents.

Usage, from the repository root:

    python -m viz.chatbot.build_collection --dry-run
    python -m viz.chatbot.build_collection --create

--dry-run prints the file list and metadata and does not contact xAI.
--create uses XAI_API_KEY and XAI_MANAGEMENT_API_KEY to make a collection
with the metadata fields, uploads every catalog file, and writes the new id
to viz/chatbot/.collection_state.json (gitignored). Copy that id into
XAI_COLLECTION_ID. Bump collection_pin.json when the document set changes.

The management key needs AddFileToCollection, plus permission to create
collections when you pass --create. Nothing in this script downloads papers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from viz.chatbot.catalog import (
    CATALOG,
    FIELD_DEFINITIONS,
    CollectionDocument,
    optional_benchmark_documents,
    repo_root,
)
from viz.chatbot.settings import Settings, load_local_dotenv, load_pin


STATE_PATH = Path(__file__).resolve().parent / ".collection_state.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def describe(root: Path, document: CollectionDocument) -> dict[str, Any]:
    path = root / document.path
    info: dict[str, Any] = {"name": document.name, "path": document.path, "fields": document.fields()}
    if path.is_file():
        info["sha256"] = file_sha256(path)
        info["bytes"] = path.stat().st_size
        info["missing"] = False
    else:
        info["missing"] = True
    return info


def plan(root: Path | None = None) -> dict[str, Any]:
    root = (root or repo_root()).resolve()
    pin = load_pin()
    required = [describe(root, document) for document in CATALOG]
    optional = [describe(root, document) for document in optional_benchmark_documents(root)]
    return {
        "collection_version": pin.get("collection_version"),
        "sdk": pin.get("sdk"),
        "default_model": pin.get("default_model"),
        "field_definitions": FIELD_DEFINITIONS,
        "documents": required,
        "optional_documents": optional,
        "missing": [item["path"] for item in required if item["missing"]],
    }


def _file_id(document: Any) -> str:
    meta = getattr(document, "file_metadata", None)
    if meta is not None and getattr(meta, "file_id", None):
        return str(meta.file_id)
    file_id = getattr(document, "file_id", None)
    return "" if file_id is None else str(file_id)


def _upload(client: Any, collection_id: str, root: Path, item: dict[str, Any]) -> str:
    path = root / item["path"]
    uploaded = client.collections.upload_document(
        collection_id=collection_id,
        name=item["name"],
        data=path.read_bytes(),
        fields=item["fields"],
        wait_for_indexing=True,
    )
    return _file_id(uploaded)


def build(root: Path, collection_id: str | None, create: bool) -> dict[str, Any]:
    load_local_dotenv()
    settings = Settings.from_env()
    if not settings.xai_api_key:
        raise SystemExit("XAI_API_KEY is not set.")
    if not settings.xai_management_api_key:
        raise SystemExit("XAI_MANAGEMENT_API_KEY is not set. Collection uploads need a management key.")
    snapshot = plan(root)
    if snapshot["missing"]:
        raise SystemExit("Missing knowledge-base files: " + ", ".join(snapshot["missing"]))

    from xai_sdk import Client

    client = Client(
        api_key=settings.xai_api_key,
        management_api_key=settings.xai_management_api_key,
        timeout=3600,
    )
    created = False
    if create:
        collection = client.collections.create(
            name=f"fishcast-policy-{snapshot['collection_version']}",
            field_definitions=FIELD_DEFINITIONS,
            description=(
                "FishCast policy knowledge base "
                f"{snapshot['collection_version']}. Pin this id for reproducibility."
            ),
        )
        collection_id = str(getattr(collection, "collection_id", "") or "")
        created = True
    if not collection_id:
        raise SystemExit("Pass --create or set XAI_COLLECTION_ID.")

    uploaded = []
    for item in snapshot["documents"] + snapshot["optional_documents"]:
        file_id = _upload(client, collection_id, root, item)
        uploaded.append({"name": item["name"], "sha256": item["sha256"], "file_id": file_id, "fields": item["fields"]})
        print(f"uploaded {item['name']}", file=sys.stderr)

    state = {
        "collection_id": collection_id,
        "collection_version": snapshot["collection_version"],
        "created": created,
        "documents": uploaded,
    }
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"collection_id={collection_id}")
    print(f"collection_version={snapshot['collection_version']}")
    print(f"wrote {STATE_PATH}")
    print("Set XAI_COLLECTION_ID to this collection_id. Do not commit the state file.")
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="List documents and metadata; do not call xAI.")
    parser.add_argument("--create", action="store_true", help="Create a new collection instead of reusing XAI_COLLECTION_ID.")
    parser.add_argument("--collection-id", default="", help="Collection to upload into. Overrides XAI_COLLECTION_ID.")
    parser.add_argument("--root", default="", help="Repository root. Defaults to this repo.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else repo_root()
    snapshot = plan(root)
    if args.dry_run:
        print(json.dumps(snapshot, indent=2))
        return 1 if snapshot["missing"] else 0
    collection_id = args.collection_id.strip() or None
    if collection_id is None:
        load_local_dotenv()
        collection_id = Settings.from_env().collection_id or None
    build(root, collection_id, create=args.create)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
