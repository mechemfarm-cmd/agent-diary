from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent_diary.config import Paths


LEDGER_VERSION = 1
LEDGER_PATH = "ledger.json"
BATCHES_DIR = "batches"


def ensure_import_dirs(paths: Paths) -> None:
    paths.imports_dir.mkdir(parents=True, exist_ok=True)
    (paths.imports_dir / BATCHES_DIR).mkdir(parents=True, exist_ok=True)


def _ledger_file(paths: Paths) -> Path:
    return paths.imports_dir / LEDGER_PATH


def load_import_ledger(paths: Paths) -> dict[str, Any]:
    ensure_import_dirs(paths)
    ledger_file = _ledger_file(paths)
    if not ledger_file.exists():
        return {"version": LEDGER_VERSION, "items": {}}
    body = json.loads(ledger_file.read_text(encoding="utf-8"))
    if not isinstance(body, dict):
        raise ValueError("import ledger is malformed")
    items = body.get("items", {})
    if not isinstance(items, dict):
        raise ValueError("import ledger items are malformed")
    return {
        "version": int(body.get("version", LEDGER_VERSION)),
        "items": items,
    }


def save_import_ledger(paths: Paths, ledger: dict[str, Any]) -> Path:
    ensure_import_dirs(paths)
    ledger_file = _ledger_file(paths)
    ledger_file.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")
    return ledger_file


def _canonicalize_source_payload(entry: dict[str, Any]) -> dict[str, Any]:
    metadata = entry.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "entry_type": entry.get("entry_type"),
        "source": entry.get("source"),
        "author_role": entry.get("author_role"),
        "created_at": entry.get("created_at"),
        "title": entry.get("title"),
        "content": entry.get("content"),
        "metadata": metadata,
    }


def build_source_item_key(entry: dict[str, Any]) -> str:
    metadata = entry.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    external_ref = (
        metadata.get("source_item_id")
        or metadata.get("source_message_id")
        or metadata.get("message_id")
        or metadata.get("conversation_item_id")
    )
    source = str(entry.get("source", "")).strip() or "unknown-source"
    if external_ref:
        return f"{source}::external::{external_ref}"

    canonical = json.dumps(_canonicalize_source_payload(entry), sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return f"{source}::fingerprint::{digest}"


def write_import_batch_manifest(
    paths: Paths,
    *,
    import_id: str,
    manifest: dict[str, Any],
) -> Path:
    ensure_import_dirs(paths)
    target = paths.imports_dir / BATCHES_DIR / f"{import_id}.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return target


def list_import_batch_manifests(paths: Paths, limit: int = 20) -> list[dict[str, Any]]:
    ensure_import_dirs(paths)
    manifests: list[dict[str, Any]] = []
    batch_dir = paths.imports_dir / BATCHES_DIR
    for path in sorted(batch_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(body, dict):
            continue
        body = dict(body)
        body["manifest_path"] = str(path)
        body["manifest_file"] = path.name
        manifests.append(body)
        if len(manifests) >= limit:
            break
    return manifests
