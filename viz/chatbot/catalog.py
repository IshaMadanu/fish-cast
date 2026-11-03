"""Documents that go into the FishCast policy collection, with required metadata.

Paths are relative to the repository root. Optional benchmark files are added
at build time only when they exist on disk. This module does not download or
embed papers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Metadata values are strings because xAI collection fields are strings.
# skill_status:
#   no_skill          the document says the relevant models do not beat a no-skill baseline
#   partial           some nowcast skill is reported; climate-only skill is not
#   not_applicable    the document is not a skill claim
#   unknown           skill is not stated, or this build does not interpret the file


@dataclass(frozen=True)
class CollectionDocument:
    path: str
    doc_type: str
    year: str
    region: str
    skill_status: str
    preprocessing_version: str

    @property
    def name(self) -> str:
        """Upload name. The relative path is what answers should cite."""
        return self.path

    def fields(self) -> dict[str, str]:
        return {
            "doc_type": self.doc_type,
            "year": self.year,
            "region": self.region,
            "skill_status": self.skill_status,
            "preprocessing_version": self.preprocessing_version,
        }


FIELD_DEFINITIONS = [
    {
        "key": "doc_type",
        "required": True,
        "unique": False,
        "inject_into_chunk": True,
        "description": "model_output, project_doc, policy, literature, or limitations",
    },
    {
        "key": "year",
        "required": True,
        "unique": False,
        "inject_into_chunk": True,
        "description": "Document year, or unknown",
    },
    {
        "key": "region",
        "required": True,
        "unique": False,
        "inject_into_chunk": True,
        "description": "Geographic scope, usually Southern Ocean or CCAMLR",
    },
    {
        "key": "skill_status",
        "required": True,
        "unique": False,
        "inject_into_chunk": True,
        "description": "no_skill, partial, not_applicable, or unknown",
    },
    {
        "key": "preprocessing_version",
        "required": True,
        "unique": False,
        "inject_into_chunk": True,
        "description": "FishCast preprocessing version the document refers to",
    },
]


CATALOG: tuple[CollectionDocument, ...] = (
    CollectionDocument("README.md", "project_doc", "2026", "Southern Ocean", "partial", "2"),
    CollectionDocument("docs/FishCastMethodology.md", "project_doc", "unknown", "Southern Ocean", "unknown", "unspecified"),
    CollectionDocument("docs/MODEL_VARIANTS.md", "project_doc", "unknown", "Southern Ocean", "not_applicable", "2"),
    CollectionDocument("docs/CHANGES_preprocessing_v2.md", "project_doc", "2026", "Southern Ocean", "no_skill", "2"),
    CollectionDocument("docs/week1_issues.md", "project_doc", "2026", "Southern Ocean", "no_skill", "2"),
    CollectionDocument("data/README.md", "project_doc", "2026", "Southern Ocean", "not_applicable", "1"),
    CollectionDocument("scripts/data/README.md", "project_doc", "2026", "Southern Ocean", "not_applicable", "2"),
    CollectionDocument(
        "viz/chatbot/knowledge/limitations.md", "limitations", "2026", "Southern Ocean", "no_skill", "2"
    ),
    CollectionDocument(
        "viz/chatbot/knowledge/benchmark_schema.md", "model_output", "2026", "Southern Ocean", "not_applicable", "2"
    ),
    CollectionDocument(
        "viz/chatbot/knowledge/external/README.md", "policy", "2026", "CCAMLR", "not_applicable", "unspecified"
    ),
)


# Benchmark products are not in git. Upload them when a local run has written them.
OPTIONAL_PATTERNS = (
    "artifacts/benchmark/benchmark_table.csv",
    "artifacts/benchmark/benchmark_summary.json",
    "artifacts/**/metrics.json",
    "benchmark_table.csv",
    "metrics.json",
)

MAX_OPTIONAL_BYTES = 5 * 1024 * 1024


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def optional_benchmark_documents(root: Path | None = None) -> list[CollectionDocument]:
    """Benchmark tables and metrics files present on disk, skipping anything over 5 MB."""
    root = (root or repo_root()).resolve()
    found: list[CollectionDocument] = []
    seen: set[Path] = set()
    for pattern in OPTIONAL_PATTERNS:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if root not in resolved.parents and resolved != root:
                continue
            if resolved in seen:
                continue
            if resolved.stat().st_size > MAX_OPTIONAL_BYTES:
                continue
            seen.add(resolved)
            relative = resolved.relative_to(root).as_posix()
            found.append(
                CollectionDocument(relative, "model_output", "unknown", "Southern Ocean", "unknown", "2")
            )
    return found
