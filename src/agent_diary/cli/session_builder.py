from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any


@dataclass
class TranscriptMessage:
    message_id: str
    created_at: str
    author_role: str
    speaker: str
    content: str
    metadata: dict[str, Any]

    @property
    def created_dt(self) -> datetime:
        return datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))


def _require_message_fields(payload: dict[str, Any], fields: list[str]) -> None:
    missing = [name for name in fields if name not in payload or payload[name] in (None, "")]
    if missing:
        raise ValueError(f"missing required message fields: {', '.join(missing)}")


def load_transcript_messages(path: Path) -> list[TranscriptMessage]:
    messages: list[TranscriptMessage] = []
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            _require_message_fields(obj, ["message_id", "created_at", "author_role", "speaker", "content"])
            metadata = obj.get("metadata", {})
            if metadata is None:
                metadata = {}
            if not isinstance(metadata, dict):
                raise ValueError(f"message metadata must be an object on line {idx}")
            messages.append(
                TranscriptMessage(
                    message_id=str(obj["message_id"]),
                    created_at=str(obj["created_at"]),
                    author_role=str(obj["author_role"]),
                    speaker=str(obj["speaker"]),
                    content=str(obj["content"]),
                    metadata=metadata,
                )
            )
    messages.sort(key=lambda item: (item.created_dt, item.message_id))
    return messages


def _chunk_fingerprint(message_ids: list[str]) -> str:
    joined = "|".join(message_ids)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def build_session_entries(
    messages: list[TranscriptMessage],
    *,
    source: str,
    gap_minutes: int = 30,
    max_chars: int = 4000,
) -> list[dict[str, Any]]:
    if gap_minutes < 1:
        raise ValueError("gap_minutes must be >= 1")
    if max_chars < 200:
        raise ValueError("max_chars must be >= 200")
    if not messages:
        return []

    chunks: list[list[TranscriptMessage]] = []
    current: list[TranscriptMessage] = []
    current_chars = 0
    gap_seconds = gap_minutes * 60

    for message in messages:
        rendered = f"{message.speaker}: {message.content}"
        start_new = False
        if current:
            prev = current[-1]
            delta = (message.created_dt - prev.created_dt).total_seconds()
            if delta > gap_seconds:
                start_new = True
            elif current_chars + len(rendered) + 1 > max_chars:
                start_new = True

        if start_new:
            chunks.append(current)
            current = []
            current_chars = 0

        current.append(message)
        current_chars += len(rendered) + 1

    if current:
        chunks.append(current)

    entries: list[dict[str, Any]] = []
    for chunk in chunks:
        message_ids = [m.message_id for m in chunk]
        author_roles = {m.author_role for m in chunk}
        author_role = next(iter(author_roles)) if len(author_roles) == 1 else "mixed"
        content = "\n".join(f"{m.speaker}: {m.content}" for m in chunk)
        created_at = chunk[0].created_at
        chunk_id = f"{source}:{chunk[0].message_id}:{chunk[-1].message_id}:{_chunk_fingerprint(message_ids)}"
        entries.append(
            {
                "entry_type": "chat_log",
                "source": source,
                "author_role": author_role,
                "created_at": created_at,
                "content": content,
                "metadata": {
                    "source_item_id": chunk_id,
                    "source_message_ids": message_ids,
                    "message_count": len(message_ids),
                    "chunk_start_message_id": chunk[0].message_id,
                    "chunk_end_message_id": chunk[-1].message_id,
                },
            }
        )
    return entries


def build_session_jsonl(
    *,
    input_path: Path,
    output_path: Path,
    source: str,
    gap_minutes: int = 30,
    max_chars: int = 4000,
) -> dict[str, Any]:
    messages = load_transcript_messages(input_path)
    entries = build_session_entries(messages, source=source, gap_minutes=gap_minutes, max_chars=max_chars)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False))
            handle.write("\n")
    return {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "message_count": len(messages),
        "entry_count": len(entries),
        "source": source,
        "gap_minutes": gap_minutes,
        "max_chars": max_chars,
    }
