from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_diary.cli.session_builder import build_session_jsonl
from agent_diary.cli.openclaw_session_import import backfill_openclaw_session_key, import_openclaw_session
from agent_diary.cli.transcript_adapter import SUPPORTED_ADAPTER_FORMATS, adapt_session_export, build_openclaw_telegram_direct_transcript
from agent_diary.config import default_paths
from agent_diary.index.sqlite_index import bootstrap_sqlite
from agent_diary.service.handlers import (
    append_entry,
    attach_artifact,
    fetch_entry_detail,
    fetch_raw_entry,
    import_session_and_refresh_derived,
    import_session_jsonl,
    list_entries,
    list_imports,
    produce_conversation_briefs,
    produce_compressed_memory,
    produce_open_loops,
    refresh_derived_for_import,
    search_memory,
)
from agent_diary.service.http_server import run_server
from agent_diary.storage.files import ensure_data_dirs


def _print(output: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(output, indent=2))
    else:
        print(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-diary",
        description="Local-first Agent Diary CLI for raw entries, memory artifacts, and truthful recurring imports.",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON output")

    sub = parser.add_subparsers(dest="command", required=True)

    p_append = sub.add_parser("append-entry")
    p_append.add_argument("--entry-type", required=True)
    p_append.add_argument("--source", required=True)
    p_append.add_argument("--author-role", required=True)
    p_append.add_argument("--content", required=True)
    p_append.add_argument("--created-at", required=True)
    p_append.add_argument("--title")
    p_append.add_argument("--metadata", default="{}")

    p_artifact = sub.add_parser("attach-artifact")
    p_artifact.add_argument("--entry-id", required=True)
    p_artifact.add_argument("--artifact-type", required=True)
    p_artifact.add_argument("--producer", required=True)
    p_artifact.add_argument("--content", required=True)
    p_artifact.add_argument("--created-at")
    p_artifact.add_argument("--metadata", default="{}")

    p_search = sub.add_parser("search-memory")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=20)
    p_search.add_argument("--filters", default="{}")

    p_fetch = sub.add_parser("fetch-raw-entry")
    p_fetch.add_argument("--entry-id", required=True)
    p_fetch.add_argument("--include-overlays", action="store_true")
    p_fetch.add_argument("--include-artifacts", action="store_true")

    p_list = sub.add_parser("list-entries")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--offset", type=int, default=0)

    p_detail = sub.add_parser("fetch-entry-detail")
    p_detail.add_argument("--entry-id", required=True)

    p_open_loops = sub.add_parser("produce-open-loops")
    p_open_loops.add_argument("--limit", type=int, default=20)
    p_open_loops.add_argument("--entry-ids", nargs="*", default=None)

    p_briefs = sub.add_parser("produce-conversation-briefs")
    p_briefs.add_argument("--limit", type=int, default=20)
    p_briefs.add_argument("--entry-ids", nargs="*", default=None)
    p_briefs.add_argument("--force", action="store_true")

    p_memory = sub.add_parser("produce-compressed-memory")
    p_memory.add_argument("--limit", type=int, default=20)
    p_memory.add_argument("--entry-ids", nargs="*", default=None)
    p_memory.add_argument("--force", action="store_true")

    p_import = sub.add_parser("import-entries-jsonl")
    p_import.add_argument("--path", required=True)

    p_session_import = sub.add_parser(
        "import-session-jsonl",
        help="import session-import JSONL after transcript adaptation and session chunking",
        description="Import canonical session-import JSONL. Raw entries remain authoritative; duplicate source items are skipped through the import ledger.",
    )
    p_session_import.add_argument("--path", required=True, help="path to session-import JSONL")
    p_session_import.add_argument("--import-id", help="optional batch id; defaults to a readable id when omitted")
    p_session_import.add_argument("--source-session-id", help="override or supply the source session id")
    p_session_import.add_argument("--source-conversation-id", help="override or supply the source conversation id")
    p_session_import.add_argument("--dry-run", action="store_true", help="plan the import without writing raw entries")

    p_session_import_and_analyze = sub.add_parser(
        "import-session-and-analyze",
        help="import session-import JSONL and refresh core derived artifacts in one step",
        description="Import canonical session-import JSONL, then produce conversation briefs, compressed memory, and open-loop analysis for imported entries.",
    )
    p_session_import_and_analyze.add_argument("--path", required=True, help="path to session-import JSONL")
    p_session_import_and_analyze.add_argument("--import-id", help="optional batch id; defaults to a readable id when omitted")
    p_session_import_and_analyze.add_argument("--source-session-id", help="override or supply the source session id")
    p_session_import_and_analyze.add_argument("--source-conversation-id", help="override or supply the source conversation id")
    p_session_import_and_analyze.add_argument("--dry-run", action="store_true", help="plan the import without writing raw entries")

    p_refresh_import = sub.add_parser(
        "refresh-derived-for-import",
        help="recompute derived artifacts for a previously imported batch",
        description="Refresh conversation briefs, compressed memory, and open-loop analysis for entries already imported under one import_id.",
    )
    p_refresh_import.add_argument("--import-id", required=True, help="existing import batch id to refresh")
    p_refresh_import.add_argument("--dry-run", action="store_true", help="show what would refresh without writing new artifacts")
    p_refresh_import.add_argument("--no-force", action="store_true", help="do not force brief/memory regeneration when artifacts already exist")

    p_openclaw_import = sub.add_parser(
        "import-openclaw-session",
        help="one-step truthful import for OpenClaw session exports",
        description="Adapt an OpenClaw session export, build session-import JSONL, and import it through the truthful recurring-ingestion path.",
    )
    p_openclaw_import.add_argument("--input-path", required=True, help="raw OpenClaw session export path")
    p_openclaw_import.add_argument("--format", default="openclaw-session-jsonl", choices=SUPPORTED_ADAPTER_FORMATS, help="source export format to adapt")
    p_openclaw_import.add_argument("--source", default="openclaw-session-import", help="source label stored on imported raw entries")
    p_openclaw_import.add_argument("--source-session-id", help="override or supply the source session id")
    p_openclaw_import.add_argument("--source-conversation-id", help="override or supply the source conversation id")
    p_openclaw_import.add_argument("--import-id", help="override the generated import batch id")
    p_openclaw_import.add_argument("--dry-run", action="store_true", help="show what would import without writing raw entries")
    p_openclaw_import.add_argument("--gap-minutes", type=int, default=60, help="group transcript messages into a chunk when gaps exceed this many minutes")
    p_openclaw_import.add_argument("--max-chars", type=int, default=6000, help="split session chunks when rendered text exceeds this many characters")
    p_openclaw_import.add_argument("--max-messages", type=int, default=80, help="split session chunks when they exceed this many messages")
    p_openclaw_import.add_argument("--min-messages-before-gap-split", type=int, default=4, help="avoid splitting on a time gap when the current chunk is still smaller than this many messages")
    p_openclaw_import.add_argument("--min-chars-before-gap-split", type=int, default=400, help="avoid splitting on a time gap when the current chunk is still smaller than this many rendered characters")

    p_backfill = sub.add_parser(
        "backfill-openclaw-session-key",
        help="import many OpenClaw session files discovered from trajectory metadata for one session key",
        description="Find session files for a specific OpenClaw session key under the trajectory store, then import them through the truthful recurring-ingestion path as a controlled backfill.",
    )
    p_backfill.add_argument("--session-key", required=True, help="OpenClaw session key to backfill, for example agent:main:telegram:default:direct:713733361")
    p_backfill.add_argument("--trajectories-root", default="~/.openclaw/agents/main/sessions", help="directory containing *.trajectory.jsonl files")
    p_backfill.add_argument("--source", default="openclaw-session-backfill", help="source label stored on imported raw entries")
    p_backfill.add_argument("--since", help="inclusive lower bound for trajectory start time; accepts YYYY-MM-DD or ISO timestamp")
    p_backfill.add_argument("--until", help="exclusive upper bound for trajectory start time; accepts YYYY-MM-DD or ISO timestamp")
    p_backfill.add_argument("--days-back", type=int, help="convenience window counting backward from now when --since is omitted")
    p_backfill.add_argument("--dry-run", action="store_true", help="discover and plan the backfill without writing raw entries")
    p_backfill.add_argument("--gap-minutes", type=int, default=60, help="group transcript messages into a chunk when gaps exceed this many minutes")
    p_backfill.add_argument("--max-chars", type=int, default=6000, help="split session chunks when rendered text exceeds this many characters")
    p_backfill.add_argument("--max-messages", type=int, default=80, help="split session chunks when they exceed this many messages")
    p_backfill.add_argument("--min-messages-before-gap-split", type=int, default=4, help="avoid splitting on a time gap when the current chunk is still smaller than this many messages")
    p_backfill.add_argument("--min-chars-before-gap-split", type=int, default=400, help="avoid splitting on a time gap when the current chunk is still smaller than this many rendered characters")

    p_list_imports = sub.add_parser(
        "list-imports",
        help="show recent truthful recurring-import batches",
        description="List recent import batch manifests in newest-first order so operators can review repeat imports and skipped duplicates.",
    )
    p_list_imports.add_argument("--limit", type=int, default=20, help="maximum number of import batches to show")

    p_build_session = sub.add_parser(
        "build-session-jsonl",
        help="convert canonical transcript messages into session-import JSONL",
        description="Chunk canonical transcript messages into session-import JSONL for truthful recurring ingestion.",
    )
    p_build_session.add_argument("--input-path", required=True, help="canonical transcript-message JSONL input")
    p_build_session.add_argument("--output-path", required=True, help="output path for session-import JSONL")
    p_build_session.add_argument("--source", required=True, help="source label stored on imported raw entries")
    p_build_session.add_argument("--gap-minutes", type=int, default=60, help="start a new chunk when message gaps exceed this many minutes")
    p_build_session.add_argument("--max-chars", type=int, default=6000, help="start a new chunk when rendered text exceeds this many characters")
    p_build_session.add_argument("--max-messages", type=int, default=80, help="start a new chunk when it exceeds this many messages")
    p_build_session.add_argument("--min-messages-before-gap-split", type=int, default=4, help="avoid splitting on a time gap when the current chunk is still smaller than this many messages")
    p_build_session.add_argument("--min-chars-before-gap-split", type=int, default=400, help="avoid splitting on a time gap when the current chunk is still smaller than this many rendered characters")

    p_build_transcript = sub.add_parser(
        "build-transcript-jsonl",
        help="adapt raw OpenClaw or generic exports into canonical transcript messages",
        description="Convert raw exports into canonical transcript-message JSONL for session building.",
    )
    p_build_transcript.add_argument("--input-path", required=True, help="raw export input path")
    p_build_transcript.add_argument("--output-path", required=True, help="output path for transcript JSONL")
    p_build_transcript.add_argument("--format", required=True, choices=SUPPORTED_ADAPTER_FORMATS, help="input format to adapt")
    p_build_transcript.add_argument("--source-session-id", help="override or supply the source session id")
    p_build_transcript.add_argument("--source-conversation-id", help="override or supply the source conversation id")

    p_build_telegram_direct = sub.add_parser(
        "build-telegram-direct-transcript",
        help="reconstruct a two-sided Telegram direct-chat transcript from Telegram-side logs and session-file sent messages",
        description="Build canonical transcript JSONL for one Telegram direct chat by combining inbound Telegram logs with assistant message sends recovered from OpenClaw session files.",
    )
    p_build_telegram_direct.add_argument("--inbound-path", required=True, help="path to sessions.json.telegram-messages.json")
    p_build_telegram_direct.add_argument("--sessions-root", required=True, help="directory containing OpenClaw session *.jsonl files")
    p_build_telegram_direct.add_argument("--chat-id", required=True, help="Telegram chat id to reconstruct")
    p_build_telegram_direct.add_argument("--output-path", required=True, help="output path for canonical transcript JSONL")
    p_build_telegram_direct.add_argument("--source-session-id", help="override the canonical source session id")
    p_build_telegram_direct.add_argument("--source-conversation-id", help="override the canonical source conversation id")

    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8041)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    paths = default_paths()
    ensure_data_dirs(paths)
    bootstrap_sqlite(paths.sqlite_path)

    if args.command == "append-entry":
        payload = {
            "entry_type": args.entry_type,
            "source": args.source,
            "author_role": args.author_role,
            "content": args.content,
            "created_at": args.created_at,
            "metadata": json.loads(args.metadata),
        }
        if args.title:
            payload["title"] = args.title
        out = append_entry(paths, payload)
        _print(out, args.json)
        return

    if args.command == "attach-artifact":
        payload = {
            "entry_id": args.entry_id,
            "artifact_type": args.artifact_type,
            "producer": args.producer,
            "content": args.content,
            "metadata": json.loads(args.metadata),
        }
        if args.created_at:
            payload["created_at"] = args.created_at
        out = attach_artifact(paths, payload)
        _print(out, args.json)
        return

    if args.command == "search-memory":
        payload = {
            "query": args.query,
            "limit": args.limit,
            "filters": json.loads(args.filters),
        }
        out = search_memory(paths, payload)
        _print(out, args.json)
        return

    if args.command == "fetch-raw-entry":
        payload = {
            "entry_id": args.entry_id,
            "include_overlays": args.include_overlays,
            "include_artifacts": args.include_artifacts,
        }
        out = fetch_raw_entry(paths, payload)
        _print(out, args.json)
        return

    if args.command == "list-entries":
        out = list_entries(paths, {"limit": args.limit, "offset": args.offset})
        _print(out, args.json)
        return

    if args.command == "fetch-entry-detail":
        out = fetch_entry_detail(paths, {"entry_id": args.entry_id})
        _print(out, args.json)
        return

    if args.command == "produce-open-loops":
        out = produce_open_loops(paths, {"limit": args.limit, "entry_ids": args.entry_ids})
        _print(out, args.json)
        return

    if args.command == "produce-conversation-briefs":
        out = produce_conversation_briefs(
            paths,
            {"limit": args.limit, "entry_ids": args.entry_ids, "force": args.force},
        )
        _print(out, args.json)
        return

    if args.command == "produce-compressed-memory":
        out = produce_compressed_memory(
            paths,
            {"limit": args.limit, "entry_ids": args.entry_ids, "force": args.force},
        )
        _print(out, args.json)
        return

    if args.command == "import-entries-jsonl":
        imported: list[dict[str, str]] = []
        with open(args.path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                raw = line.strip()
                if not raw:
                    continue
                obj = json.loads(raw)
                payload = {
                    "entry_type": obj["entry_type"],
                    "source": obj["source"],
                    "author_role": obj["author_role"],
                    "content": obj["content"],
                    "created_at": obj["created_at"],
                    "metadata": obj.get("metadata", {}),
                }
                if "title" in obj:
                    payload["title"] = obj["title"]
                result = append_entry(paths, payload)
                imported.append({"line": str(idx), "entry_id": result["entry_id"]})
        _print({"imported_count": len(imported), "entries": imported}, args.json)
        return

    if args.command == "import-session-jsonl":
        out = import_session_jsonl(
            paths,
            {
                "path": args.path,
                "import_id": args.import_id,
                "source_session_id": args.source_session_id,
                "source_conversation_id": args.source_conversation_id,
                "dry_run": args.dry_run,
            },
        )
        _print(out, args.json)
        return

    if args.command == "import-session-and-analyze":
        out = import_session_and_refresh_derived(
            paths,
            {
                "path": args.path,
                "import_id": args.import_id,
                "source_session_id": args.source_session_id,
                "source_conversation_id": args.source_conversation_id,
                "dry_run": args.dry_run,
            },
        )
        _print(out, args.json)
        return

    if args.command == "refresh-derived-for-import":
        out = refresh_derived_for_import(
            paths,
            {
                "import_id": args.import_id,
                "dry_run": args.dry_run,
                "force": not args.no_force,
            },
        )
        _print(out, args.json)
        return

    if args.command == "build-session-jsonl":
        out = build_session_jsonl(
            input_path=Path(args.input_path).expanduser().resolve(),
            output_path=Path(args.output_path).expanduser().resolve(),
            source=args.source,
            gap_minutes=args.gap_minutes,
            max_chars=args.max_chars,
            max_messages=args.max_messages,
            min_messages_before_gap_split=args.min_messages_before_gap_split,
            min_chars_before_gap_split=args.min_chars_before_gap_split,
        )
        _print(out, args.json)
        return

    if args.command == "build-transcript-jsonl":
        out = adapt_session_export(
            input_path=Path(args.input_path).expanduser().resolve(),
            output_path=Path(args.output_path).expanduser().resolve(),
            format_name=args.format,
            source_session_id=args.source_session_id,
            source_conversation_id=args.source_conversation_id,
        )
        _print(out, args.json)
        return

    if args.command == "build-telegram-direct-transcript":
        out = build_openclaw_telegram_direct_transcript(
            inbound_path=Path(args.inbound_path).expanduser().resolve(),
            sessions_root=Path(args.sessions_root).expanduser().resolve(),
            output_path=Path(args.output_path).expanduser().resolve(),
            chat_id=str(args.chat_id),
            source_session_id=args.source_session_id,
            source_conversation_id=args.source_conversation_id,
        )
        _print(out, args.json)
        return

    if args.command == "import-openclaw-session":
        out = import_openclaw_session(
            paths,
            input_path=Path(args.input_path).expanduser().resolve(),
            format_name=args.format,
            source=args.source,
            import_id=args.import_id,
            source_session_id=args.source_session_id,
            source_conversation_id=args.source_conversation_id,
            dry_run=args.dry_run,
            gap_minutes=args.gap_minutes,
            max_chars=args.max_chars,
            max_messages=args.max_messages,
            min_messages_before_gap_split=args.min_messages_before_gap_split,
            min_chars_before_gap_split=args.min_chars_before_gap_split,
        )
        _print(out, args.json)
        return

    if args.command == "backfill-openclaw-session-key":
        out = backfill_openclaw_session_key(
            paths,
            trajectories_root=Path(args.trajectories_root).expanduser().resolve(),
            session_key=args.session_key,
            source=args.source,
            since=args.since,
            until=args.until,
            days_back=args.days_back,
            dry_run=args.dry_run,
            gap_minutes=args.gap_minutes,
            max_chars=args.max_chars,
            max_messages=args.max_messages,
            min_messages_before_gap_split=args.min_messages_before_gap_split,
            min_chars_before_gap_split=args.min_chars_before_gap_split,
        )
        _print(out, args.json)
        return

    if args.command == "list-imports":
        out = list_imports(paths, {"limit": args.limit})
        _print(out, args.json)
        return

    if args.command == "serve":
        run_server(paths, host=args.host, port=args.port)
        return


if __name__ == "__main__":
    main()
