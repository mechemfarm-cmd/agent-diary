from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


Metadata = dict[str, Any]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RawEntry:
    entry_type: str
    source: str
    author_role: str
    content: str
    created_at: str = field(default_factory=now_iso)
    metadata: Metadata = field(default_factory=dict)
    title: str | None = None
    entry_id: str = field(default_factory=lambda: f"entry_{uuid4().hex}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Artifact:
    """Secondary interpreted data linked to authoritative raw entries.

    For future derived analysis artifacts, keep lineage/method hints in `metadata`
    (for example: `source_entry_ids`, `schema_version`, `method`, `generated_at`).
    """
    entry_id: str
    artifact_type: str
    producer: str
    content: str
    created_at: str = field(default_factory=now_iso)
    metadata: Metadata = field(default_factory=dict)
    artifact_id: str = field(default_factory=lambda: f"artifact_{uuid4().hex}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Overlay:
    entry_id: str
    overlay_type: str
    author: str
    content: str
    created_at: str = field(default_factory=now_iso)
    metadata: Metadata = field(default_factory=dict)
    overlay_id: str = field(default_factory=lambda: f"overlay_{uuid4().hex}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
