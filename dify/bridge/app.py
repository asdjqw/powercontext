"""Small HTTP bridge between Dify and a real PowerContext server.

Dify's HTTP Request node calls:
  POST /memory/load  (form: user_id, query) -> plain-text memories
  POST /memory/save  (form: user_id, text)  -> JSON

The bridge starts PowerContext in-process (SQLite) and keeps one Scope per
Dify user, so the same user's choices are remembered across Dify sessions.
"""

from __future__ import annotations

import asyncio
import json
import re
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
DATA = ROOT / ".data"
_THINKING = re.compile(r"<details.*?</details>", re.S | re.I)


def clean_memory(text: str) -> str:
    """Drop the model's thinking block so stored memory is the answer body only."""
    return _THINKING.sub("", text or "").strip()
DATA.mkdir(parents=True, exist_ok=True)
PORT = int(__import__("os").environ.get("BRIDGE_PORT", "8099"))


class Runtime:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.base_url = ""
        self.client: PowerContextClient | None = None
        self._server = None
        self._listener: socket.socket | None = None
        self._scopes: dict[str, str] = {}
        self._recent_path = DATA / "recent.json"
        try:
            self._recent: dict[str, list[str]] = json.loads(self._recent_path.read_text("utf-8"))
        except (OSError, ValueError):
            self._recent = {}
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

    async def _scope(self, user_id: str) -> str:
        if user_id in self._scopes:
            return self._scopes[user_id]
        assert self.client is not None
        scope = await self.client.create_scope(
            CreateScopeRequest(
                title=f"Dify player {user_id}",
                summary="Interactive story memory for the Dify Memory Tavern app",
                idempotency_key=f"dify-memory-{user_id}",
            )
        )
        self._scopes[user_id] = scope.scope_id
        return scope.scope_id

    def _remember(self, user_id: str, text: str) -> None:
        text = clean_memory(text)
        if not text:
            return
        items = self._recent.setdefault(user_id, [])
        items.append(text[:2000])
        del items[:-20]
        try:
            self._recent_path.write_text(json.dumps(self._recent, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    async def _load(self, user_id: str, query: str) -> str:
        assert self.client is not None
        scope_id = await self._scope(user_id)
        result = await self.client.search_memory(
            SearchMemoryRequest(scope_id=scope_id, query=query, mode="fts", limit=8)
        )
        seen: set[str] = set()
        lines: list[str] = []
        # Deterministic recency first: the next session must always see the last
        # few turns, even when the question shares no FTS token with them.
        for text in reversed(self._recent.get(user_id, [])[-5:]):
            if text not in seen:
                seen.add(text)
                lines.append(f"- {text}")
        for hit in result.hits:
            text = getattr(hit, "text", "")
            if text and text not in seen:
                seen.add(text)
                lines.append(f"- {text}")
        return "\n".join(lines[:8]) if lines else "（暂无历史记忆）"

    async def _save(self, user_id: str, text: str) -> dict[str, Any]:
        assert self.client is not None
        scope_id = await self._scope(user_id)
        text = clean_memory(text)
        saved = await self.client.remember_memory(
            RememberMemoryRequest(
                scope_id=scope_id,
                kind="progress",
                text=text,
                reason="Dify Memory Tavern player/NPC turn",
            )
        )
        self._remember(user_id, text)
        return {"scope_id": scope_id, "saved": True, "citation": str(getattr(saved, "citation", ""))}


RUNTIME = Runtime()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[bridge] {fmt % args}")

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

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        content_type = (self.headers.get("Content-Type") or "").lower()
        form = {}
        if "application/x-www-form-urlencoded" in content_type:
            form = {key: values[0] for key, values in parse_qs(raw, keep_blank_values=True).items()}
        user_id = (self.headers.get("X-User-Id") or form.get("user_id") or "demo-player").strip() or "demo-player"
        try:
            if self.path == "/memory/load":
                query = form.get("query", raw) if form else raw
                context = RUNTIME.call(RUNTIME._load(user_id, query.strip() or "玩家行动"))
                self._reply(200, context)
            elif self.path == "/memory/save":
                text = form.get("text", raw) if form else raw
                result = RUNTIME.call(RUNTIME._save(user_id, text.strip()))
                self._reply(200, result)
            else:
                self._reply(404, {"error": "not found"})
        except Exception as exc:
            self._reply(503, {"error": str(exc)[:500]})


if __name__ == "__main__":
    print(f"Dify/PowerContext bridge listening on http://0.0.0.0:{PORT} (PowerContext {RUNTIME.base_url})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
