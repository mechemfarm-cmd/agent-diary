from __future__ import annotations

import argparse
import json

from agent_diary.config import default_paths
from agent_diary.index.sqlite_index import bootstrap_sqlite
from agent_diary.service.handlers import (
    append_entry,
    attach_artifact,
    fetch_entry_detail,
    fetch_raw_entry,
    list_entries,
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
    parser = argparse.ArgumentParser(prog="agent-diary")
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")

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

    if args.command == "serve":
        run_server(paths, host=args.host, port=args.port)
        return


if __name__ == "__main__":
    main()
