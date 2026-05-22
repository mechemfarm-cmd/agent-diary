from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
import re
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


_THREAD_ID_KEYS = (
    "source_thread_id",
    "thread_id",
    "source_block_id",
    "block_id",
    "source_thread_block_id",
)
_NEW_THREAD_KEYS = (
    "is_new_thread",
    "new_thread",
    "thread_start",
    "is_new_block",
    "new_block",
    "block_start",
)
_LINKAGE_KEYS = (
    "reply_to_message_id",
    "in_reply_to_message_id",
    "source_parent_id",
    "parent_message_id",
    "parent_id",
)
_CONTINUATION_OPENINGS = (
    "yes",
    "no",
    "ok",
    "okay",
    "here",
    "here it is",
    "i found",
    "done",
)
_EPISODE_TOKENS = (
    "codex",
    "app",
    "build",
    "deploy",
    "release",
    "test",
    "bug",
    "fix",
    "android",
    "ios",
    "telegram",
    "session",
    "import",
)
_RESTART_CUES = (
    "different topic",
    "new topic",
    "unrelated",
    "anyway",
    "separately",
    "on another note",
)


def _metadata_str(message: TranscriptMessage, key: str) -> str | None:
    value = message.metadata.get(key)
    if value in (None, ""):
        return None
    return str(value)


def _metadata_bool(message: TranscriptMessage, key: str) -> bool:
    value = message.metadata.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _has_hard_source_boundary(prev: TranscriptMessage, current: TranscriptMessage) -> bool:
    for key in ("source_session_id", "source_conversation_id"):
        prev_id = _metadata_str(prev, key)
        current_id = _metadata_str(current, key)
        if prev_id and current_id and prev_id != current_id:
            return True

    for key in _THREAD_ID_KEYS:
        prev_id = _metadata_str(prev, key)
        current_id = _metadata_str(current, key)
        if prev_id and current_id and prev_id != current_id:
            return True

    return any(_metadata_bool(current, key) for key in _NEW_THREAD_KEYS)


def _looks_like_unresolved_request(content: str) -> bool:
    text = content.strip().lower()
    if not text:
        return False
    if "?" in text:
        return True
    return bool(re.search(r"\b(can you|could you|please|need you to|check|find|send|share|look up|do this)\b", text))


def _has_obvious_continuation_signal(
    prev: TranscriptMessage,
    current: TranscriptMessage,
    current_chunk: list[TranscriptMessage],
) -> bool:
    current_text = current.content.strip().lower()
    if not current_text:
        return False

    for key in _LINKAGE_KEYS:
        linked = _metadata_str(current, key)
        if linked and linked in {m.message_id for m in current_chunk}:
            return True

    opener_match = False
    for opener in _CONTINUATION_OPENINGS:
        if re.match(rf"^{re.escape(opener)}(\b|[\s,.:;!])", current_text):
            opener_match = True
            break
    if not opener_match:
        return False

    candidate_messages = [prev]
    for item in reversed(current_chunk[:-1]):
        if re.search(r"[a-zA-Z0-9]", item.content):
            candidate_messages.append(item)
            break

    return any(_looks_like_unresolved_request(item.content) for item in candidate_messages)


def _tokenize_for_overlap(content: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]{3,}", content.lower()))
    return tokens


def _looks_like_same_episode(prev: TranscriptMessage, current: TranscriptMessage, current_chunk: list[TranscriptMessage]) -> bool:
    prev_tokens = _tokenize_for_overlap(prev.content)
    current_tokens = _tokenize_for_overlap(current.content)
    overlap = len(prev_tokens & current_tokens)
    if overlap >= 2:
        return True

    if any(token in current_tokens for token in _EPISODE_TOKENS) and any(
        token in prev_tokens for token in _EPISODE_TOKENS
    ):
        return True

    return False


def _looks_like_restart(content: str) -> bool:
    text = content.strip().lower()
    return any(cue in text for cue in _RESTART_CUES)


def build_session_entries(
    messages: list[TranscriptMessage],
    *,
    source: str,
    gap_minutes: int = 60,
    max_chars: int = 6000,
    max_messages: int = 80,
    min_messages_before_gap_split: int = 4,
    min_chars_before_gap_split: int = 400,
) -> list[dict[str, Any]]:
    if gap_minutes < 1:
        raise ValueError("gap_minutes must be >= 1")
    if max_chars < 200:
        raise ValueError("max_chars must be >= 200")
    if max_messages < 1:
        raise ValueError("max_messages must be >= 1")
    if min_messages_before_gap_split < 1:
        raise ValueError("min_messages_before_gap_split must be >= 1")
    if min_chars_before_gap_split < 1:
        raise ValueError("min_chars_before_gap_split must be >= 1")
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

            # 1) Hard source boundary.
            if _has_hard_source_boundary(prev, message):
                start_new = True
            # 2) Hard size boundary.
            elif len(current) >= max_messages:
                start_new = True
            elif current_chars + len(rendered) + 1 > max_chars:
                start_new = True
            # 3) Soft time boundary, with 4) continuation override.
            elif delta > gap_seconds:
                if _looks_like_restart(message.content):
                    start_new = True
                else:
                    continued = _has_obvious_continuation_signal(prev, message, current) or _looks_like_same_episode(prev, message, current)
                    if continued:
                        start_new = False
                    elif len(current) < min_messages_before_gap_split or current_chars < min_chars_before_gap_split:
                        # Still split on very long unrelated silence.
                        if delta >= gap_seconds * 3:
                            start_new = True
                        else:
                            start_new = False
                    else:
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
        source_session_id = _metadata_str(chunk[0], "source_session_id")
        source_conversation_id = _metadata_str(chunk[0], "source_conversation_id")
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
                    **({"source_session_id": source_session_id} if source_session_id else {}),
                    **({"source_conversation_id": source_conversation_id} if source_conversation_id else {}),
                },
            }
        )
    return entries


def build_session_jsonl(
    *,
    input_path: Path,
    output_path: Path,
    source: str,
    gap_minutes: int = 60,
    max_chars: int = 6000,
    max_messages: int = 80,
    min_messages_before_gap_split: int = 4,
    min_chars_before_gap_split: int = 400,
) -> dict[str, Any]:
    messages = load_transcript_messages(input_path)
    entries = build_session_entries(
        messages,
        source=source,
        gap_minutes=gap_minutes,
        max_chars=max_chars,
        max_messages=max_messages,
        min_messages_before_gap_split=min_messages_before_gap_split,
        min_chars_before_gap_split=min_chars_before_gap_split,
    )
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
        "max_messages": max_messages,
        "min_messages_before_gap_split": min_messages_before_gap_split,
        "min_chars_before_gap_split": min_chars_before_gap_split,
    }
