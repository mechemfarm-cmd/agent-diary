from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from agent_diary.analytics.conversation_briefs import (
    build_conversation_brief_text,
    collect_source_rows as collect_brief_source_rows,
    entry_has_artifact_type,
)
from agent_diary.analytics.compressed_memory import (
    build_compressed_memory_text,
    collect_source_rows as collect_memory_source_rows,
    entry_has_artifact_type as entry_has_memory_artifact_type,
)
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
from agent_diary.storage.imports import (
    build_source_item_key,
    load_import_batch_manifest,
    list_import_batch_manifests,
    load_import_ledger,
    save_import_ledger,
    write_import_batch_manifest,
)


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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_import_id() -> str:
    return f"import_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid4().hex[:8]}"


def import_session_jsonl(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    _require_fields(payload, ["path"])
    import_path = Path(str(payload["path"])).expanduser().resolve()
    if not import_path.exists():
        raise FileNotFoundError(f"import file not found: {import_path}")

    import_id = str(payload.get("import_id") or _make_import_id())
    imported_at = _utc_now_iso()
    source_session_id = str(payload.get("source_session_id", "")).strip() or None
    source_conversation_id = str(payload.get("source_conversation_id", "")).strip() or None
    dry_run = bool(payload.get("dry_run", False))

    parsed_rows: list[dict[str, Any]] = []
    with import_path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            _require_fields(obj, ["entry_type", "source", "author_role", "content", "created_at"])
            parsed_rows.append({"line": idx, "entry": obj})

    ledger = load_import_ledger(paths)
    ledger_items = ledger["items"]
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in parsed_rows:
        obj = dict(row["entry"])
        metadata = obj.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError(f"metadata must be an object on line {row['line']}")

        if source_session_id and "source_session_id" not in metadata:
            metadata["source_session_id"] = source_session_id
        if source_conversation_id and "source_conversation_id" not in metadata:
            metadata["source_conversation_id"] = source_conversation_id

        source_item_key = build_source_item_key({**obj, "metadata": metadata})
        if source_item_key in ledger_items:
            existing = ledger_items[source_item_key]
            skipped.append(
                {
                    "line": row["line"],
                    "reason": "duplicate_source_item",
                    "source_item_key": source_item_key,
                    "existing_entry_id": existing["entry_id"],
                }
            )
            continue

        ingestion_meta = {
            "truthful_source": True,
            "import_mode": "session_jsonl",
            "import_id": import_id,
            "imported_at": imported_at,
            "source_item_key": source_item_key,
        }
        if source_session_id:
            ingestion_meta["source_session_id"] = source_session_id
        if source_conversation_id:
            ingestion_meta["source_conversation_id"] = source_conversation_id
        metadata["ingestion"] = ingestion_meta

        entry_payload = {
            "entry_type": obj["entry_type"],
            "source": obj["source"],
            "author_role": obj["author_role"],
            "content": obj["content"],
            "created_at": obj["created_at"],
            "metadata": metadata,
        }
        if "title" in obj:
            entry_payload["title"] = obj["title"]

        if dry_run:
            imported.append({"line": row["line"], "source_item_key": source_item_key, "dry_run": True})
            continue

        result = append_entry(paths, entry_payload)
        imported.append(
            {
                "line": row["line"],
                "entry_id": result["entry_id"],
                "raw_file": result["raw_file"],
                "source_item_key": source_item_key,
            }
        )
        ledger_items[source_item_key] = {
            "entry_id": result["entry_id"],
            "import_id": import_id,
            "imported_at": imported_at,
            "source": obj["source"],
            "created_at": obj["created_at"],
            "line": row["line"],
        }

    manifest = {
        "import_id": import_id,
        "imported_at": imported_at,
        "import_mode": "session_jsonl",
        "input_path": str(import_path),
        "source_session_id": source_session_id,
        "source_conversation_id": source_conversation_id,
        "dry_run": dry_run,
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "imported": imported,
        "skipped": skipped,
    }

    if not dry_run:
        ledger_path = save_import_ledger(paths, ledger)
        manifest["ledger_path"] = str(ledger_path)
    manifest_path = write_import_batch_manifest(paths, import_id=import_id, manifest=manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def import_session_and_refresh_derived(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    import_result = import_session_jsonl(paths, payload)
    imported_entry_ids = [
        str(item.get("entry_id", "")).strip()
        for item in import_result.get("imported", [])
        if str(item.get("entry_id", "")).strip()
    ]
    dry_run = bool(payload.get("dry_run", False))
    derived: dict[str, Any] = {}
    if dry_run:
        derived = {
            "conversation_briefs": {"status": "skipped_dry_run", "produced_count": 0, "skipped_count": 0},
            "compressed_memory": {"status": "skipped_dry_run", "produced_count": 0, "skipped_count": 0},
            "open_loops": {"status": "skipped_dry_run", "loop_count": 0},
        }
    elif not imported_entry_ids:
        derived = {
            "conversation_briefs": {"status": "skipped_no_imports", "produced_count": 0, "skipped_count": 0},
            "compressed_memory": {"status": "skipped_no_imports", "produced_count": 0, "skipped_count": 0},
            "open_loops": {"status": "skipped_no_imports", "loop_count": 0},
        }
    else:
        brief_result = produce_conversation_briefs(paths, {"entry_ids": imported_entry_ids, "limit": len(imported_entry_ids)})
        memory_result = produce_compressed_memory(paths, {"entry_ids": imported_entry_ids, "limit": len(imported_entry_ids)})
        open_loops_result = produce_open_loops(paths, {"entry_ids": imported_entry_ids, "limit": len(imported_entry_ids)})
        derived = {
            "conversation_briefs": {
                "status": "ok",
                "produced_count": int(brief_result.get("produced_count", 0)),
                "skipped_count": int(brief_result.get("skipped_count", 0)),
            },
            "compressed_memory": {
                "status": "ok",
                "produced_count": int(memory_result.get("produced_count", 0)),
                "skipped_count": int(memory_result.get("skipped_count", 0)),
            },
            "open_loops": {
                "status": "ok",
                "loop_count": int(open_loops_result.get("loop_count", 0)),
                "artifact_id": open_loops_result.get("artifact_id"),
            },
        }

    return {
        "import_id": import_result.get("import_id"),
        "imported_count": int(import_result.get("imported_count", 0)),
        "skipped_count": int(import_result.get("skipped_count", 0)),
        "imported_entry_ids": imported_entry_ids,
        "import_result": import_result,
        "derived": derived,
    }


def refresh_derived_for_import(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    _require_fields(payload, ["import_id"])
    import_id = str(payload["import_id"]).strip()
    if not import_id:
        raise ValueError("import_id is required")
    dry_run = bool(payload.get("dry_run", False))
    force = bool(payload.get("force", True))

    manifest = load_import_batch_manifest(paths, import_id=import_id)
    imported_entry_ids = [
        str(item.get("entry_id", "")).strip()
        for item in manifest.get("imported", [])
        if isinstance(item, dict) and str(item.get("entry_id", "")).strip()
    ]

    if dry_run:
        derived = {
            "conversation_briefs": {"status": "skipped_dry_run", "produced_count": 0, "skipped_count": 0},
            "compressed_memory": {"status": "skipped_dry_run", "produced_count": 0, "skipped_count": 0},
            "open_loops": {"status": "skipped_dry_run", "loop_count": 0},
        }
    elif not imported_entry_ids:
        derived = {
            "conversation_briefs": {"status": "skipped_no_imported_entries", "produced_count": 0, "skipped_count": 0},
            "compressed_memory": {"status": "skipped_no_imported_entries", "produced_count": 0, "skipped_count": 0},
            "open_loops": {"status": "skipped_no_imported_entries", "loop_count": 0},
        }
    else:
        brief_result = produce_conversation_briefs(
            paths, {"entry_ids": imported_entry_ids, "limit": len(imported_entry_ids), "force": force}
        )
        memory_result = produce_compressed_memory(
            paths, {"entry_ids": imported_entry_ids, "limit": len(imported_entry_ids), "force": force}
        )
        open_loops_result = produce_open_loops(paths, {"entry_ids": imported_entry_ids, "limit": len(imported_entry_ids)})
        derived = {
            "conversation_briefs": {
                "status": "ok",
                "produced_count": int(brief_result.get("produced_count", 0)),
                "skipped_count": int(brief_result.get("skipped_count", 0)),
            },
            "compressed_memory": {
                "status": "ok",
                "produced_count": int(memory_result.get("produced_count", 0)),
                "skipped_count": int(memory_result.get("skipped_count", 0)),
            },
            "open_loops": {
                "status": "ok",
                "loop_count": int(open_loops_result.get("loop_count", 0)),
                "artifact_id": open_loops_result.get("artifact_id"),
            },
        }

    return {
        "import_id": import_id,
        "imported_entry_count": len(imported_entry_ids),
        "imported_entry_ids": imported_entry_ids,
        "manifest_path": str(paths.imports_dir / "batches" / f"{import_id}.json"),
        "force": force,
        "dry_run": dry_run,
        "derived": derived,
    }


def list_imports(paths: Paths, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    limit = int(payload.get("limit", 20))
    manifests = list_import_batch_manifests(paths, limit=limit)
    items: list[dict[str, Any]] = []
    for manifest in manifests:
        import_result = manifest.get("import_result", {})
        if not isinstance(import_result, dict):
            import_result = {}
        items.append(
            {
                "import_id": manifest.get("import_id"),
                "import_label": manifest.get("import_label"),
                "imported_at": manifest.get("imported_at"),
                "imported_count": manifest.get("imported_count"),
                "skipped_duplicate_count": manifest.get("skipped_count"),
                "source_session_id": manifest.get("source_session_id"),
                "source_conversation_id": manifest.get("source_conversation_id"),
                "batch_manifest_path": manifest.get("manifest_path"),
                "manifest_file": manifest.get("manifest_file"),
                "dry_run": manifest.get("dry_run"),
            }
        )
    return {"limit": limit, "count": len(items), "items": items}


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


def _build_open_loop_participation(paths: Paths) -> dict[str, dict[str, Any]]:
    participation: dict[str, dict[str, Any]] = {}
    for artifact_file in paths.artifacts_dir.glob("*/artifact_*.json"):
        try:
            artifact = json.loads(artifact_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(artifact.get("artifact_type", "")).strip() != "analysis:open-loop":
            continue
        metadata = artifact.get("metadata")
        source_entry_ids: list[str] = []
        if isinstance(metadata, dict):
            source_entry_ids = [str(e).strip() for e in metadata.get("source_entry_ids", []) if str(e).strip()]
        if not source_entry_ids:
            anchor_id = str(artifact.get("entry_id", "")).strip()
            if anchor_id:
                source_entry_ids = [anchor_id]
        loops: list[dict[str, Any]] = []
        try:
            raw_loops = json.loads(str(artifact.get("content", "{}"))).get("loops", [])
            if isinstance(raw_loops, list):
                loops = [loop for loop in raw_loops if isinstance(loop, dict)]
        except json.JSONDecodeError:
            loops = []
        representative_title = None
        if loops:
            candidate = str(loops[0].get("title", "")).strip()
            if candidate:
                representative_title = candidate
        created_at = str(artifact.get("created_at", "")).strip()
        artifact_id = str(artifact.get("artifact_id", "")).strip()
        key = (created_at, artifact_id)
        for entry_id in source_entry_ids:
            current = participation.get(entry_id)
            current_key = (
                str(current.get("latest_created_at", "")),
                str(current.get("latest_artifact_id", "")),
            ) if isinstance(current, dict) else ("", "")
            if current is None or key >= current_key:
                participation[entry_id] = {
                    "count": len(loops),
                    "latest_created_at": created_at,
                    "latest_artifact_id": artifact_id,
                    "representative_title": representative_title,
                    "last_seen_at": created_at or None,
                }
    return participation


def _search_raw_entries(paths: Paths, query: str, limit: int) -> list[dict[str, Any]]:
    terms = [t for t in re.findall(r"\w+", query.lower()) if t]
    if not terms:
        return []

    candidates = list_entry_rows(paths.sqlite_path, limit=max(limit * 10, 200), offset=0)
    scored: list[dict[str, Any]] = []
    for row in candidates:
        raw_file = Path(str(row["raw_file_path"]))
        if not raw_file.exists():
            continue
        body = json.loads(raw_file.read_text(encoding="utf-8"))
        content = str(body.get("content", ""))
        lowered = content.lower()
        if not any(term in lowered for term in terms):
            continue
        phrase_bonus = 100 if query.lower() in lowered else 0
        coverage = sum(1 for term in terms if term in lowered)
        frequency = sum(lowered.count(term) for term in terms)
        scored.append(
            {
                "entry_id": row["entry_id"],
                "artifact_id": None,
                "indexed_at": row["created_at"],
                "match_text": content,
                "match_layer": "raw_entry_fallback",
                "entry_type": body.get("entry_type", "unknown"),
                "source": row["source"],
                "author_role": row["author_role"],
                "_score": phrase_bonus + (coverage * 10) + frequency,
            }
        )

    scored.sort(key=lambda item: (item["_score"], item["indexed_at"]), reverse=True)
    return [{k: v for k, v in item.items() if k != "_score"} for item in scored[:limit]]


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
    compressed_matches = search_index(paths.sqlite_path, query=query, limit=limit)
    linked_matches = [
        {
            "entry_id": row["entry_id"],
            "artifact_id": row["artifact_id"],
            "indexed_at": row["indexed_at"],
            "match_text": _build_snippet(str(row["match_text"]), query),
            "match_layer": "compressed_memory",
            "fetch_raw_entry": {"entry_id": row["entry_id"]},
        }
        for row in compressed_matches
    ]
    fallback_matches: list[dict[str, Any]] = []
    if not linked_matches:
        fallback_matches = [
            {
                "entry_id": row["entry_id"],
                "artifact_id": row["artifact_id"],
                "indexed_at": row["indexed_at"],
                "match_text": _build_snippet(str(row["match_text"]), query),
                "match_layer": row["match_layer"],
                "entry_type": row["entry_type"],
                "source": row["source"],
                "author_role": row["author_role"],
                "fetch_raw_entry": {"entry_id": row["entry_id"]},
            }
            for row in _search_raw_entries(paths, query=query, limit=limit)
        ]
    return {
        "query": query,
        "limit": limit,
        "filters": filters,
        "matches": linked_matches or fallback_matches,
        "match_summary": {
            "compressed_memory_hits": len(linked_matches),
            "raw_entry_fallback_hits": len(fallback_matches),
            "using_fallback": not linked_matches and bool(fallback_matches),
        },
        "note": "Search prefers compressed-memory artifacts and falls back to raw-entry text when the compressed layer has no hits.",
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
    only_with_open_loops = bool(payload.get("only_with_open_loops", False))
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    row_offset = offset
    rows: list[dict[str, Any]]
    open_loop_participation = _build_open_loop_participation(paths)
    if only_with_open_loops:
        # In filtered mode, limit/offset apply to the filtered result set, ordered by
        # open-loop freshness (latest linked last_seen_at), then stable tiebreakers.
        all_rows = list_entry_rows(paths.sqlite_path, limit=1000000, offset=0)
        participating_rows = []
        for row in all_rows:
            loop_info = open_loop_participation.get(str(row["entry_id"]))
            if loop_info and int(loop_info.get("count", 0)) > 0:
                participating_rows.append(row)
        participating_rows.sort(
            key=lambda r: (
                str(open_loop_participation.get(str(r["entry_id"]), {}).get("last_seen_at", "")),
                str(r.get("created_at", "")),
                str(r.get("entry_id", "")),
            ),
            reverse=True,
        )
        rows = participating_rows[offset : offset + limit]
        row_offset = offset
    else:
        rows = list_entry_rows(paths.sqlite_path, limit=limit, offset=offset)
    items: list[dict[str, Any]] = []
    for row in rows:
        raw_file = Path(row["raw_file_path"])
        body = json.loads(raw_file.read_text(encoding="utf-8"))
        brief = None
        latest_brief_key: tuple[str, str] | None = None
        artifact_dir = paths.artifacts_dir / row["entry_id"]
        if artifact_dir.exists():
            for artifact_file in sorted(artifact_dir.glob("*.json")):
                artifact_body = json.loads(artifact_file.read_text(encoding="utf-8"))
                if artifact_body.get("artifact_type") == "conversation-brief":
                    key = (
                        str(artifact_body.get("created_at", "")).strip(),
                        str(artifact_body.get("artifact_id", "")).strip(),
                    )
                    if latest_brief_key is None or key > latest_brief_key:
                        latest_brief_key = key
                        brief = str(artifact_body.get("content", "")).strip() or None
        item = {
            "entry_id": row["entry_id"],
            "created_at": row["created_at"],
            "entry_type": body.get("entry_type", "unknown"),
            "source": row["source"],
            "author_role": row["author_role"],
            "brief": brief,
            "preview": _build_preview(str(body.get("content", ""))),
        }
        loop_info = open_loop_participation.get(str(row["entry_id"]))
        if loop_info and int(loop_info.get("count", 0)) > 0:
            item["open_loop"] = {
                "has_open_loops": True,
                "count": int(loop_info.get("count", 0)),
                "representative_title": str(loop_info.get("representative_title") or "").strip() or None,
                "last_seen_at": str(loop_info.get("last_seen_at") or "").strip() or None,
            }
        items.append(item)

    return {"limit": limit, "offset": row_offset, "items": items}


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
    seen_artifact_ids: set[str] = set()
    for a in fetched.get("artifacts", []):
        artifact_id = str(a.get("artifact_id", "")).strip()
        if artifact_id:
            seen_artifact_ids.add(artifact_id)
        artifact = {
            "artifact_id": artifact_id or a.get("artifact_id"),
            "artifact_type": a.get("artifact_type"),
            "producer": a.get("producer"),
            "created_at": a.get("created_at"),
        }
        if a.get("artifact_type") in {"memory", "compressed-memory", "conversation-brief"}:
            artifact["content"] = a.get("content", "")
        if a.get("artifact_type") == "analysis:open-loop":
            metadata = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
            artifact["lineage"] = {
                "link_mode": "direct",
                "anchor_entry_id": str(a.get("entry_id", entry["entry_id"])),
                "source_entry_ids": [str(e) for e in metadata.get("source_entry_ids", []) if str(e).strip()],
            }
            try:
                artifact["open_loops"] = json.loads(str(a.get("content", "{}"))).get("loops", [])
            except json.JSONDecodeError:
                artifact["open_loops"] = []
        artifacts.append(artifact)

    for linked in _find_linked_open_loop_artifacts(paths, entry_id=str(entry["entry_id"]), exclude_artifact_ids=seen_artifact_ids):
        artifacts.append(linked)

    artifacts.sort(key=lambda a: (str(a.get("created_at", "")), str(a.get("artifact_id", ""))), reverse=True)
    latest_by_type: dict[str, tuple[str, str]] = {}
    for artifact in artifacts:
        artifact_type = str(artifact.get("artifact_type", "")).strip()
        if not artifact_type:
            continue
        key = (str(artifact.get("created_at", "")), str(artifact.get("artifact_id", "")))
        current = latest_by_type.get(artifact_type)
        if current is None or key > current:
            latest_by_type[artifact_type] = key
    for artifact in artifacts:
        artifact_type = str(artifact.get("artifact_type", "")).strip()
        if not artifact_type:
            continue
        key = (str(artifact.get("created_at", "")), str(artifact.get("artifact_id", "")))
        artifact["is_current"] = key == latest_by_type.get(artifact_type)

    return {
        "entry_id": entry["entry_id"],
        "raw_entry": entry,
        "artifacts": artifacts,
        "truth_model": {
            "primary": "raw_entry",
            "secondary": "artifacts",
        },
    }


def _find_linked_open_loop_artifacts(paths: Paths, *, entry_id: str, exclude_artifact_ids: set[str]) -> list[dict[str, Any]]:
    linked: list[dict[str, Any]] = []
    for artifact_file in paths.artifacts_dir.glob("*/artifact_*.json"):
        try:
            body = json.loads(artifact_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(body.get("artifact_type", "")).strip() != "analysis:open-loop":
            continue
        artifact_id = str(body.get("artifact_id", "")).strip()
        if not artifact_id or artifact_id in exclude_artifact_ids:
            continue
        metadata = body.get("metadata")
        if not isinstance(metadata, dict):
            continue
        source_entry_ids = [str(e).strip() for e in metadata.get("source_entry_ids", []) if str(e).strip()]
        if entry_id not in source_entry_ids:
            continue
        try:
            open_loops = json.loads(str(body.get("content", "{}"))).get("loops", [])
        except json.JSONDecodeError:
            open_loops = []
        linked.append(
            {
                "artifact_id": artifact_id,
                "artifact_type": "analysis:open-loop",
                "producer": body.get("producer"),
                "created_at": body.get("created_at"),
                "open_loops": open_loops,
                "lineage": {
                    "link_mode": "lineage",
                    "anchor_entry_id": str(body.get("entry_id", "")),
                    "source_entry_ids": source_entry_ids,
                },
            }
        )
    linked.sort(key=lambda a: (str(a.get("created_at", "")), str(a.get("artifact_id", ""))), reverse=True)
    return linked


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


def produce_conversation_briefs(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    limit = int(payload.get("limit", 20))
    if limit < 1:
        raise ValueError("limit must be >= 1")
    entry_ids = payload.get("entry_ids")
    normalized_entry_ids: list[str] | None = None
    if entry_ids:
        if not isinstance(entry_ids, list):
            raise ValueError("entry_ids must be a list when provided")
        normalized_entry_ids = [str(e).strip() for e in entry_ids if str(e).strip()]
    force = bool(payload.get("force", False))

    source_rows = collect_brief_source_rows(paths, limit=limit, entry_ids=normalized_entry_ids)
    if not source_rows:
        raise FileNotFoundError("no source entries found for conversation-brief analysis")

    produced: list[dict[str, Any]] = []
    skipped: list[str] = []
    for row in source_rows:
        entry_id = str(row["entry_id"])
        if not force and entry_has_artifact_type(paths, entry_id=entry_id, artifact_type="conversation-brief"):
            skipped.append(entry_id)
            continue
        body = json.loads(Path(row["raw_file_path"]).read_text(encoding="utf-8"))
        brief = build_conversation_brief_text(body)
        attached = attach_artifact(
            paths,
            {
                "entry_id": entry_id,
                "artifact_type": "conversation-brief",
                "producer": "conversation-brief.v1",
                "content": brief,
                "metadata": {
                    "schema_version": "conversation-brief.v1",
                    "method": "deterministic-dialogue-brief-v1",
                    "source_entry_id": entry_id,
                },
            },
        )
        produced.append(
            {
                "entry_id": entry_id,
                "artifact_id": attached["artifact_id"],
                "artifact_file": attached["artifact_file"],
                "brief": brief,
            }
        )
    return {
        "produced_count": len(produced),
        "skipped_count": len(skipped),
        "produced": produced,
        "skipped": skipped,
    }


def produce_compressed_memory(paths: Paths, payload: dict[str, Any]) -> dict[str, Any]:
    limit = int(payload.get("limit", 20))
    if limit < 1:
        raise ValueError("limit must be >= 1")
    entry_ids = payload.get("entry_ids")
    normalized_entry_ids: list[str] | None = None
    if entry_ids:
        if not isinstance(entry_ids, list):
            raise ValueError("entry_ids must be a list when provided")
        normalized_entry_ids = [str(e).strip() for e in entry_ids if str(e).strip()]
    force = bool(payload.get("force", False))

    source_rows = collect_memory_source_rows(paths, limit=limit, entry_ids=normalized_entry_ids)
    if not source_rows:
        raise FileNotFoundError("no source entries found for compressed-memory analysis")

    produced: list[dict[str, Any]] = []
    skipped: list[str] = []
    for row in source_rows:
        entry_id = str(row["entry_id"])
        if not force and entry_has_memory_artifact_type(paths, entry_id=entry_id, artifact_type="compressed-memory"):
            skipped.append(entry_id)
            continue
        body = json.loads(Path(row["raw_file_path"]).read_text(encoding="utf-8"))
        memory_text = build_compressed_memory_text(body)
        attached = attach_artifact(
            paths,
            {
                "entry_id": entry_id,
                "artifact_type": "compressed-memory",
                "producer": "compressed-memory.v2",
                "content": memory_text,
                "metadata": {
                    "schema_version": "compressed-memory.v2",
                    "method": "deterministic-dialogue-compression-v2",
                    "source_entry_id": entry_id,
                },
            },
        )
        produced.append(
            {
                "entry_id": entry_id,
                "artifact_id": attached["artifact_id"],
                "artifact_file": attached["artifact_file"],
                "indexed_in_memory": attached["indexed_in_memory"],
            }
        )
    return {
        "produced_count": len(produced),
        "skipped_count": len(skipped),
        "produced": produced,
        "skipped": skipped,
    }


def status(paths: Paths) -> dict[str, Any]:
    return {
        "ok": True,
        "data_root": str(paths.data_root),
        "sqlite_path": str(paths.sqlite_path),
    }
