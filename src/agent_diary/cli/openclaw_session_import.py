from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from agent_diary.cli.session_builder import build_session_jsonl
from agent_diary.cli.transcript_adapter import adapt_session_export
from agent_diary.config import Paths
from agent_diary.service.handlers import import_session_jsonl
from agent_diary.storage.imports import ensure_import_dirs


def _slugify_identifier(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    slug = slug.strip("-")
    return slug or "unknown"


def _make_readable_import_id(source: str, resolved_session_id: str | None, input_path: Path) -> str:
    session_hint = resolved_session_id or input_path.stem
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"import-{_slugify_identifier(source)}-{_slugify_identifier(session_hint)}-{stamp}"


def import_openclaw_session(
    paths: Paths,
    *,
    input_path: Path,
    format_name: str = "openclaw-session-jsonl",
    source: str = "openclaw-session-import",
    import_id: str | None = None,
    source_session_id: str | None = None,
    source_conversation_id: str | None = None,
    dry_run: bool = False,
    gap_minutes: int = 30,
    max_chars: int = 4000,
) -> dict[str, Any]:
    ensure_import_dirs(paths)
    input_path = Path(input_path).expanduser().resolve()

    with tempfile.TemporaryDirectory(prefix="openclaw-import-", dir=str(paths.imports_dir)) as temp_dir:
        temp_root = Path(temp_dir)
        transcript_path = temp_root / "transcript.jsonl"
        session_path = temp_root / "session.jsonl"

        adapter_result = adapt_session_export(
            input_path=input_path,
            output_path=transcript_path,
            format_name=format_name,
            source_session_id=source_session_id,
            source_conversation_id=source_conversation_id,
        )
        effective_session_id = source_session_id or adapter_result.get("source_session_id")
        effective_conversation_id = source_conversation_id or adapter_result.get("source_conversation_id")
        effective_import_id = import_id or _make_readable_import_id(source, effective_session_id, input_path)
        import_label = (
            f"{source} | session={effective_session_id or 'unknown'} | "
            f"conversation={effective_conversation_id or 'unknown'} | import={effective_import_id}"
        )

        session_result = build_session_jsonl(
            input_path=transcript_path,
            output_path=session_path,
            source=source,
            gap_minutes=gap_minutes,
            max_chars=max_chars,
        )
        import_result = import_session_jsonl(
            paths,
            {
                "path": str(session_path),
                "import_id": effective_import_id,
                "source_session_id": effective_session_id,
                "source_conversation_id": effective_conversation_id,
                "dry_run": dry_run,
            },
        )

    batch_manifest_path = import_result.get("manifest_path")
    summary = {
        "input_path": str(input_path),
        "format": format_name,
        "source": source,
        "resolved_source_session_id": effective_session_id,
        "resolved_source_conversation_id": effective_conversation_id,
        "source_session_id": effective_session_id,
        "source_conversation_id": effective_conversation_id,
        "dry_run": dry_run,
        "import_id": import_result.get("import_id"),
        "import_label": import_label,
        "transcript_message_count": adapter_result["message_count"],
        "session_chunk_count": session_result["entry_count"],
        "imported_count": import_result.get("imported_count", 0),
        "skipped_duplicate_count": import_result.get("skipped_count", 0),
        "batch_manifest_path": batch_manifest_path,
        "adapter": {
            "format": adapter_result["format"],
            "message_count": adapter_result["message_count"],
            "schema_fields": adapter_result["schema_fields"],
        },
        "session_builder": {
            "message_count": session_result["message_count"],
            "entry_count": session_result["entry_count"],
            "source": session_result["source"],
            "gap_minutes": session_result["gap_minutes"],
            "max_chars": session_result["max_chars"],
        },
        "import_result": import_result,
    }
    return summary
