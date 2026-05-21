from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_diary.cli.session_builder import build_session_jsonl
from agent_diary.cli.openclaw_session_import import import_openclaw_session
from agent_diary.cli.transcript_adapter import SUPPORTED_ADAPTER_FORMATS, adapt_session_export
from agent_diary.config import default_paths
from agent_diary.index.sqlite_index import bootstrap_sqlite
from agent_diary.service.handlers import (
    append_entry,
    attach_artifact,
    fetch_entry_detail,
    fetch_raw_entry,
    import_session_jsonl,
    list_entries,
    list_imports,
    produce_open_loops,
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
    p_openclaw_import.add_argument("--gap-minutes", type=int, default=30, help="group transcript messages into a chunk when gaps exceed this many minutes")
    p_openclaw_import.add_argument("--max-chars", type=int, default=4000, help="split session chunks when rendered text exceeds this many characters")

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
    p_build_session.add_argument("--gap-minutes", type=int, default=30, help="start a new chunk when message gaps exceed this many minutes")
    p_build_session.add_argument("--max-chars", type=int, default=4000, help="start a new chunk when rendered text exceeds this many characters")

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

    if args.command == "build-session-jsonl":
        out = build_session_jsonl(
            input_path=Path(args.input_path).expanduser().resolve(),
            output_path=Path(args.output_path).expanduser().resolve(),
            source=args.source,
            gap_minutes=args.gap_minutes,
            max_chars=args.max_chars,
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
