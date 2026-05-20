from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from agent_diary.analytics.open_loops import build_open_loops_payload, collect_source_rows
from agent_diary.config import Paths
from agent_diary.index.repository import (
    get_entry_row,
    insert_artifact,
    insert_entry,
    insert_memory_index_row,
    list_entry_rows,
    search_memory as search_index,
)
from agent_diary.models.types import Artifact, RawEntry
from agent_diary.storage.entry_reader import fetch_raw_entry as fetch_entry_from_files
from agent_diary.storage.files import append_artifact, append_raw_entry


def _require_fields(payload: dict[str, Any], fields: list[str]) -> None:
    missing = [name for name in fields if name not in payload or payload[name] in (None, "")]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")


def append_entry(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    _require_fields(
        payload,
        ["entry_type", "source", "author_role", "content", "created_at"],
    )
    entry = RawEntry(**payload)
    raw_path = append_raw_entry(paths, entry)
    insert_entry(paths.sqlite_path, entry, str(raw_path))
    return {"entry_id": entry.entry_id, "raw_file": str(raw_path)}


def _is_compressed_memory_artifact(artifact_type: str) -> bool:
    normalized = artifact_type.strip().lower().replace("_", "-")
    return normalized in {"memory", "compressed-memory"}


def _build_snippet(text: str, query: str, size: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= size:
        return compact
    terms = [t for t in re.findall(r"\w+", query.lower()) if t]
    lowered = compact.lower()
    pivot = -1
    for term in terms:
        idx = lowered.find(term)
        if idx != -1 and (pivot == -1 or idx < pivot):
            pivot = idx
    if pivot == -1:
        return compact[: size - 3] + "..."
    start = max(0, pivot - (size // 3))
    end = min(len(compact), start + size)
    snippet = compact[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(compact):
        snippet = snippet + "..."
    return snippet


def _build_preview(text: str, size: int = 140) -> str:
    compact = " ".join(text.split())
    if len(compact) <= size:
        return compact
    return compact[: size - 3] + "..."


def attach_artifact(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    _require_fields(
        payload,
        ["entry_id", "artifact_type", "producer", "content"],
    )
    if get_entry_row(paths.sqlite_path, str(payload["entry_id"])) is None:
        raise FileNotFoundError(f"entry not found: {payload['entry_id']}")

    artifact = Artifact(**payload)
    artifact_path = append_artifact(paths, artifact)
    insert_artifact(paths.sqlite_path, artifact)
    indexed = False
    if _is_compressed_memory_artifact(artifact.artifact_type):
        insert_memory_index_row(
            paths.sqlite_path,
            entry_id=artifact.entry_id,
            artifact_id=artifact.artifact_id,
            created_at=artifact.created_at,
            memory_text=artifact.content,
        )
        indexed = True
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_file": str(artifact_path),
        "indexed_in_memory": indexed,
    }


def search_memory(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query", "")).strip()
    limit = int(payload.get("limit", 20))
    filters = payload.get("filters", {})
    matches = search_index(paths.sqlite_path, query=query, limit=limit)
    linked_matches = [
        {
            "entry_id": row["entry_id"],
            "artifact_id": row["artifact_id"],
            "indexed_at": row["indexed_at"],
            "match_text": _build_snippet(str(row["match_text"]), query),
            "fetch_raw_entry": {"entry_id": row["entry_id"]},
        }
        for row in matches
    ]
    return {
        "query": query,
        "limit": limit,
        "filters": filters,
        "matches": linked_matches,
        "note": "compressed-memory index results; fetch_raw_entry for authoritative truth",
    }


def fetch_raw_entry(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    entry_id = str(payload["entry_id"])
    include_overlays = bool(payload.get("include_overlays", False))
    include_artifacts = bool(payload.get("include_artifacts", False))
    return fetch_entry_from_files(
        paths,
        entry_id=entry_id,
        include_overlays=include_overlays,
        include_artifacts=include_artifacts,
    )


def list_entries(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    limit = int(payload.get("limit", 20))
    offset = int(payload.get("offset", 0))
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    rows = list_entry_rows(paths.sqlite_path, limit=limit, offset=offset)
    items: list[dict[str, Any]] = []
    for row in rows:
        raw_file = Path(row["raw_file_path"])
        body = json.loads(raw_file.read_text(encoding="utf-8"))
        items.append(
            {
                "entry_id": row["entry_id"],
                "created_at": row["created_at"],
                "entry_type": body.get("entry_type", "unknown"),
                "source": row["source"],
                "author_role": row["author_role"],
                "preview": _build_preview(str(body.get("content", ""))),
            }
        )

    return {"limit": limit, "offset": offset, "items": items}


def fetch_entry_detail(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    _require_fields(payload, ["entry_id"])
    fetched = fetch_entry_from_files(
        paths,
        entry_id=str(payload["entry_id"]),
        include_overlays=False,
        include_artifacts=True,
    )
    entry = fetched["entry"]
    artifacts = []
    for a in fetched.get("artifacts", []):
        artifact = {
            "artifact_id": a.get("artifact_id"),
            "artifact_type": a.get("artifact_type"),
            "producer": a.get("producer"),
            "created_at": a.get("created_at"),
        }
        if a.get("artifact_type") == "analysis:open-loop":
            try:
                artifact["open_loops"] = json.loads(str(a.get("content", "{}"))).get("loops", [])
            except json.JSONDecodeError:
                artifact["open_loops"] = []
        artifacts.append(artifact)
    return {
        "entry_id": entry["entry_id"],
        "raw_entry": entry,
        "artifacts": artifacts,
        "truth_model": {
            "primary": "raw_entry",
            "secondary": "artifacts",
        },
    }


def produce_open_loops(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    limit = int(payload.get("limit", 20))
    if limit < 1:
        raise ValueError("limit must be >= 1")
    entry_ids = payload.get("entry_ids")
    normalized_entry_ids: list[str] | None = None
    if entry_ids:
        if not isinstance(entry_ids, list):
            raise ValueError("entry_ids must be a list when provided")
        normalized_entry_ids = [str(e).strip() for e in entry_ids if str(e).strip()]

    source_rows = collect_source_rows(paths, limit=limit, entry_ids=normalized_entry_ids)
    if not source_rows:
        raise FileNotFoundError("no source entries found for open-loop analysis")

    source_entry_ids = [str(r["entry_id"]) for r in source_rows]
    payload_content = build_open_loops_payload(source_entries=source_rows)
    newest_row = max(source_rows, key=lambda r: (r["created_at"], r["entry_id"]))
    generated_at = datetime.now(timezone.utc).isoformat()

    artifact_payload = {
        "entry_id": str(newest_row["entry_id"]),
        "artifact_type": "analysis:open-loop",
        "producer": "open-loop.v1",
        "content": json.dumps(payload_content, sort_keys=True),
        "created_at": generated_at,
        "metadata": {
            "schema_version": "open-loop.v1",
            "source_entry_ids": source_entry_ids,
            "analysis_window": {
                "start": min(r["created_at"] for r in source_rows),
                "end": max(r["created_at"] for r in source_rows),
            },
            "method": "keyword-window-v1",
            "method_version": "1",
            "generated_at": generated_at,
        },
    }
    attached = attach_artifact(paths, artifact_payload)
    return {
        "artifact_id": attached["artifact_id"],
        "artifact_file": attached["artifact_file"],
        "loop_count": len(payload_content["loops"]),
        "source_entry_ids": source_entry_ids,
    }


def status(paths: Paths) -> dict[str, Any]:
    return {
        "ok": True,
        "data_root": str(paths.data_root),
        "sqlite_path": str(paths.sqlite_path),
    }
