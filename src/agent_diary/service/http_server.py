from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from agent_diary.config import Paths
from agent_diary.service import handlers

RouteFn = Callable[[Paths, dict[str, Any]], dict[str, Any]]


class AgentDiaryHandler(BaseHTTPRequestHandler):
    routes: dict[str, RouteFn] = {
        "/append_entry": handlers.append_entry,
        "/append_work_trace": handlers.append_work_trace_event,
        "/append_overlay": handlers.append_overlay,
        "/attach_artifact": handlers.attach_artifact,
        "/produce_open_loops": handlers.produce_open_loops,
        "/produce_conversation_briefs": handlers.produce_conversation_briefs,
        "/produce_compressed_memory": handlers.produce_compressed_memory,
        "/search_memory": handlers.search_memory,
        "/search_all": handlers.search_all,
        "/search_work_trace": handlers.search_work_trace,
        "/list_imports": handlers.list_imports,
        "/fetch_work_trace": handlers.fetch_work_trace_event,
        "/fetch_raw_entry": handlers.fetch_raw_entry,
        "/list_work_trace": handlers.list_work_trace,
        "/list_entries": handlers.list_entries,
        "/fetch_entry_detail": handlers.fetch_entry_detail,
    }

    def _send_json(self, code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/status":
            self._send_json(HTTPStatus.OK, handlers.status(self.server.paths))
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        route = self.routes.get(self.path)
        if route is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        body_len = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(body_len) if body_len else b"{}"
        payload = json.loads(raw.decode("utf-8"))
        try:
            result = route(self.server.paths, payload)
            self._send_json(HTTPStatus.OK, {"ok": True, "result": result})
        except FileNotFoundError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": str(exc)})
        except Exception as exc:  # scaffold-friendly fallback
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})


class AgentDiaryHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], paths: Paths):
        super().__init__(server_address, AgentDiaryHandler)
        self.paths = paths


def run_server(paths: Paths, host: str = "127.0.0.1", port: int = 8041) -> None:
    server = AgentDiaryHTTPServer((host, port), paths)
    print(f"agent-diary service listening on http://{host}:{port}")
    server.serve_forever()
