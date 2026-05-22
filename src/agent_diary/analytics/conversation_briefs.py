from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_diary.config import Paths
from agent_diary.index.repository import get_entry_row, list_entry_rows


def _read_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _entry_row_to_body(row: dict[str, Any]) -> dict[str, Any]:
    return _read_json(Path(row["raw_file_path"]))


def _split_turns(content: str) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    current_speaker = ""
    current_lines: list[str] = []
    for line in content.replace("\r\n", "\n").split("\n"):
        match = re.match(r"^([^:\n]{1,48}):\s*(.*)$", line)
        if match:
            if current_speaker or current_lines:
                turns.append((current_speaker, "\n".join(current_lines).strip()))
            current_speaker = match.group(1).strip()
            current_lines = [match.group(2)]
            continue
        current_lines.append(line)
    if current_speaker or current_lines:
        turns.append((current_speaker, "\n".join(current_lines).strip()))
    return [(speaker, body) for speaker, body in turns if body]


def _clean_text(text: str) -> str:
    return " ".join(str(text).split()).strip()


def _sentenceish(text: str, limit: int = 220) -> str:
    compact = _clean_text(text)
    if len(compact) <= limit:
        return compact
    clipped = compact[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{clipped}…"


def _speaker_label(speaker: str) -> str:
    lowered = _clean_text(speaker).lower()
    if lowered in {"assistant", "agent", "tom", "codex", "bot"}:
        return "Tom"
    if lowered in {"user", "human", "bill", "willard", "willardmechem"}:
        return "Bill"
    return _clean_text(speaker) or "Speaker"


def build_conversation_brief_text(entry: dict[str, Any]) -> str:
    content = str(entry.get("content", ""))
    turns = _split_turns(content)
    if not turns:
        return _sentenceish(content, limit=260)

    first_turn = turns[0]
    last_turn = turns[-1]
    middle_turn = turns[1] if len(turns) >= 3 else None
    question_turn = next((turn for turn in turns if "?" in turn[1]), None)

    opener = _sentenceish(first_turn[1], limit=140)
    closer = _sentenceish(last_turn[1], limit=140)

    if question_turn and question_turn != first_turn:
        focus = _sentenceish(question_turn[1], limit=120)
        return (
            f"{_speaker_label(first_turn[0])} opens with {opener} "
            f"The main ask becomes {focus} "
            f"It closes with {_speaker_label(last_turn[0])}: {closer}"
        )

    if middle_turn:
        response = _sentenceish(middle_turn[1], limit=120)
        return (
            f"{_speaker_label(first_turn[0])} starts with {opener} "
            f"{_speaker_label(middle_turn[0])} responds: {response} "
            f"It closes with {_speaker_label(last_turn[0])}: {closer}"
        )

    if len(turns) == 1:
        return f"{_speaker_label(first_turn[0])}: {opener}"

    return (
        f"{_speaker_label(first_turn[0])} starts with {opener} "
        f"The exchange ends with {_speaker_label(last_turn[0])}: {closer}"
    )


def collect_source_rows(
    paths: Paths,
    *,
    limit: int,
    entry_ids: list[str] | None,
) -> list[dict[str, Any]]:
    if entry_ids:
        rows: list[dict[str, Any]] = []
        for entry_id in entry_ids:
            row = get_entry_row(paths.sqlite_path, entry_id)
            if row is not None:
                rows.append(row)
        rows.sort(key=lambda r: (r["created_at"], r["entry_id"]), reverse=True)
        return rows[:limit]
    return list_entry_rows(paths.sqlite_path, limit=limit, offset=0)


def entry_has_artifact_type(paths: Paths, *, entry_id: str, artifact_type: str) -> bool:
    artifact_dir = paths.artifacts_dir / entry_id
    if not artifact_dir.exists():
        return False
    for path in artifact_dir.glob("*.json"):
        body = _read_json(path)
        if str(body.get("artifact_type", "")).strip() == artifact_type:
            return True
    return False
