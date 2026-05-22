from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_diary.config import Paths
from agent_diary.index.repository import get_entry_row, list_entry_rows


STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "have", "from", "your", "just", "into", "then", "they",
    "them", "what", "when", "where", "will", "would", "could", "should", "about", "there", "here", "their",
    "were", "been", "being", "also", "than", "them", "our", "you", "are", "but", "not", "too", "can", "let",
    "know", "looks", "look", "said", "just", "still", "more", "like", "need",
}

DECISION_CUES = ("let's", "lets", "we should", "we will", "plan", "the plan", "decision", "agreed")
COMMITMENT_CUES = ("i'll", "i will", "i can", "i'm going to", "ill ", "i am going to", "next i")


def _read_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


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


def _clean_text(text: str) -> str:
    return " ".join(str(text).split()).strip()


def _sentenceish(text: str, limit: int = 220) -> str:
    compact = _clean_text(text)
    if len(compact) <= limit:
        return compact
    clipped = compact[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{clipped}…"


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


def _speaker_label(speaker: str) -> str:
    lowered = _clean_text(speaker).lower()
    if lowered in {"assistant", "agent", "tom", "codex", "bot"}:
        return "Tom"
    if lowered in {"user", "human", "bill", "willard", "willardmechem"}:
        return "Bill"
    return _clean_text(speaker) or "Speaker"


def _extract_keywords(text: str, limit: int = 8) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"[a-z0-9]{4,}", text)]
    counts: dict[str, int] = {}
    for token in tokens:
        if token in STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _ in ranked[:limit]]


def _first_matching(turns: list[str], cues: tuple[str, ...], *, limit: int = 140) -> list[str]:
    matched: list[str] = []
    for body in turns:
        lowered = body.lower()
        if any(cue in lowered for cue in cues):
            matched.append(_sentenceish(body, limit=limit))
    return matched[:2]


def build_compressed_memory_text(entry: dict[str, Any]) -> str:
    created_at = str(entry.get("created_at", "")).strip()
    entry_type = _clean_text(str(entry.get("entry_type", "")))
    source = _clean_text(str(entry.get("source", "")))
    content = str(entry.get("content", ""))
    turns = _split_turns(content)
    keywords = _extract_keywords(content)
    lines: list[str] = []
    if created_at:
        lines.append(f"Date: {created_at}")
    if entry_type or source:
        lines.append(f"Source context: type={entry_type or 'unknown'} source={source or 'unknown'}")

    if not turns:
        lines.append(f"Retrieval summary: {_sentenceish(content, limit=220)}")
        if keywords:
            lines.append(f"Retrieval anchors: {', '.join(keywords)}")
        return "\n".join(lines)

    bill_turns = [body for speaker, body in turns if _speaker_label(speaker) == "Bill"]
    tom_turns = [body for speaker, body in turns if _speaker_label(speaker) == "Tom"]
    question_turns = [body for speaker, body in turns if _speaker_label(speaker) == "Bill" and "?" in body]
    decisions = _first_matching(bill_turns + tom_turns, DECISION_CUES, limit=130)
    commitments = _first_matching(tom_turns, COMMITMENT_CUES, limit=130)
    open_loops = [body for body in bill_turns if "?" in body and body not in commitments]

    opener = _sentenceish(turns[0][1], limit=140)
    closer = _sentenceish(turns[-1][1], limit=120)
    lines.append(f"Retrieval summary: {_speaker_label(turns[0][0])} opens with {opener}")
    if question_turns:
        lines.append(f"Bill asks: {' | '.join(_sentenceish(text, limit=130) for text in question_turns[:2])}")
    if bill_turns:
        lines.append(f"Bill context: {' | '.join(_sentenceish(text, limit=130) for text in bill_turns[:2])}")
    if commitments:
        lines.append(f"Tom commitments: {' | '.join(commitments)}")
    elif tom_turns:
        lines.append(f"Tom response: {' | '.join(_sentenceish(text, limit=130) for text in tom_turns[:2])}")
    if decisions:
        lines.append(f"Decisions / direction: {' | '.join(decisions)}")
    if open_loops:
        lines.append(f"Open loops: {' | '.join(_sentenceish(text, limit=130) for text in open_loops[:2])}")
    lines.append(f"Closing state: {_speaker_label(turns[-1][0])} ends with {closer}")
    if keywords:
        lines.append(f"Retrieval anchors: {', '.join(keywords)}")
    return "\n".join(lines)
