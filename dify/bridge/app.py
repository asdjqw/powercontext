"""Small HTTP bridge between Dify and a real PowerContext server.

The Dify 1.x Chatflow (see ``dify/app.dsl.yml``) calls two JSON endpoints:

  POST /search   {"scope": "dify-<user>", "query": "...", "limit": 5}
                 -> {"scope": ..., "hits": [{"text": "..."}]}
  POST /remember {"scope": "dify-<user>", "text": "..."}
                 -> {"ok": true, "scope": ..., "citation": "..."}

The older form/text endpoints (``/memory/load``、``/memory/save``) are kept for
backward compatibility with the 0.15.3 DSL.

The bridge starts PowerContext in-process (SQLite backend) and keeps one Scope
per Dify user, so the same ``sys.user_id`` keeps its memory across sessions.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from urllib.parse import parse_qs
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime.config import ExternalSkillsConfig, InferenceConfig, RuntimeConfig
from powercontext.client import PowerContextClient
from powercontext.http import CreateScopeRequest, RememberMemoryRequest, SearchMemoryRequest
from powercontext.server.factory import create_server_app
from powercontext.server.settings import (
    AccessControlConfig,
    BearerAuthConfig,
    HttpConfig,
    McpConfig,
    MetricsConfig,
    ServerSettings,
    TracingConfig,
)
import uvicorn

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("BRIDGE_DATA", ROOT / ".data"))
DATA.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("BRIDGE_PORT", "8099"))


class Runtime:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.base_url = ""
        self.client: PowerContextClient | None = None
        self._server = None
        self._listener: socket.socket | None = None
        self._scopes: dict[str, str] = {}
        self.ready = threading.Event()
        self.error = ""
        self.thread.start()
        self.ready.wait(60)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._start())
            self.loop.run_forever()
        except Exception as exc:  # pragma: no cover - startup guard
            self.error = str(exc)
            self.ready.set()

    async def _start(self) -> None:
        database = SQLiteConfig(url=f"sqlite+aiosqlite:///{DATA / 'powercontext.db'}")
        settings = ServerSettings(
            workspace=DATA,
            database=database,
            http=HttpConfig(host="127.0.0.1"),
            auth=BearerAuthConfig(enabled=False),
            access=AccessControlConfig(mode="disabled"),
            inference=InferenceConfig(),
            runtime=RuntimeConfig(schedule_seconds=None, experience_schedule_seconds=None),
            external_skills=ExternalSkillsConfig(),
            mcp=McpConfig(enabled=False),
            metrics=MetricsConfig(enabled=False),
            tracing=TracingConfig(enabled=False),
        )
        app = create_server_app(settings=settings, scheduler_path=DATA / "scheduler.db")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        self._listener = listener
        self.base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        self._server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on"))
        threading.Thread(target=self._server.run, kwargs={"sockets": [listener]}, daemon=True).start()
        deadline = time.monotonic() + 45
        while not self._server.started and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if not self._server.started:
            raise RuntimeError("PowerContext server failed to start")
        self.client = PowerContextClient(self.base_url, timeout=120)
        self.ready.set()

    def call(self, coro: Any) -> Any:
        if self.error:
            raise RuntimeError(self.error)
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(60)

    async def _scope(self, scope_key: str) -> str:
        key = (scope_key or "demo-player").strip()[:120]
        if key in self._scopes:
            return self._scopes[key]
        assert self.client is not None
        scope = await self.client.create_scope(
            CreateScopeRequest(
                title=f"Dify memory {key}"[:120],
                summary="Interactive story memory for the Dify Memory Tavern app",
                idempotency_key=f"dify-memory-{key}",
            )
        )
        self._scopes[key] = scope.scope_id
        return scope.scope_id

    async def _search(self, scope_key: str, query: str, limit: int) -> dict[str, Any]:
        assert self.client is not None
        scope_id = await self._scope(scope_key)
        result = await self.client.search_memory(
            SearchMemoryRequest(
                scope_id=scope_id,
                query=query or "玩家行动",
                mode="fts",
                limit=max(1, min(int(limit or 5), 20)),
            )
        )
        hits = []
        for hit in result.hits:
            text = getattr(hit, "text", "") or ""
            if text:
                hits.append({"text": text, "citation": str(getattr(hit, "citation", "") or "")})
        return {"scope": scope_key, "scope_id": scope_id, "query": query, "hits": hits}

    async def _remember(self, scope_key: str, text: str) -> dict[str, Any]:
        assert self.client is not None
        scope_id = await self._scope(scope_key)
        saved = await self.client.remember_memory(
            RememberMemoryRequest(
                scope_id=scope_id,
                kind="progress",
                text=text,
                reason="Dify Memory Tavern player/NPC turn",
            )
        )
        return {"ok": True, "scope": scope_key, "scope_id": scope_id, "citation": str(getattr(saved, "citation", "") or "")}


RUNTIME = Runtime()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[bridge] {fmt % args}", flush=True)

    def _reply(self, status: int, body: Any) -> None:
        payload = body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8" if isinstance(body, str) else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._reply(200, {"ok": not bool(RUNTIME.error), "error": RUNTIME.error, "base_url": RUNTIME.base_url})
        else:
            self._reply(404, {"error": "not found"})

    def _parse(self, raw: str, content_type: str) -> tuple[dict[str, Any], dict[str, str], str]:
        payload: dict[str, Any] = {}
        form: dict[str, str] = {}
        if "application/json" in content_type:
            try:
                parsed = json.loads(raw) if raw.strip() else {}
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                payload = {}
        elif "application/x-www-form-urlencoded" in content_type:
            form = {key: values[0] for key, values in parse_qs(raw, keep_blank_values=True).items()}
        return payload, form, raw

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        content_type = (self.headers.get("Content-Type") or "").lower()
        payload, form, raw_text = self._parse(raw, content_type)
        scope_key = str(
            payload.get("scope")
            or payload.get("user_id")
            or self.headers.get("X-User-Id")
            or form.get("user_id")
            or "demo-player"
        ).strip() or "demo-player"
        try:
            if self.path in ("/search", "/memory/load"):
                query = str(payload.get("query") or form.get("query") or (raw_text if not payload and not form else ""))
                limit = int(payload.get("limit") or 5)
                result = RUNTIME.call(RUNTIME._search(scope_key, query.strip(), limit))
                if self.path == "/search":
                    self._reply(200, result)
                else:
                    lines = [f"- {hit['text']}" for hit in result["hits"]]
                    self._reply(200, "\n".join(lines) if lines else "（暂无历史记忆）")
            elif self.path in ("/remember", "/memory/save"):
                text = str(payload.get("text") or form.get("text") or (raw_text if not payload and not form else "")).strip()
                if not text:
                    self._reply(400, {"ok": False, "error": "text is empty"})
                    return
                self._reply(200, RUNTIME.call(RUNTIME._remember(scope_key, text)))
            else:
                self._reply(404, {"error": "not found"})
        except Exception as exc:
            self._reply(503, {"ok": False, "error": str(exc)[:500]})


if __name__ == "__main__":
    print(f"Dify/PowerContext bridge listening on http://0.0.0.0:{PORT} (PowerContext {RUNTIME.base_url})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
