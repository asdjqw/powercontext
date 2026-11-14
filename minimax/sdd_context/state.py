"""PowerContext-backed task state store.

The module starts a real in-process PowerContext Server (SQLite backend),
creates one Scope, writes task progress as Memory, and reads it back from a
fresh client.  A separate CLI process therefore exercises the same
stop/restart path as a real host restart.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import socket
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import (
    DEFAULT_MEMORY_IDEMPOTENCY_KEY,
    DEFAULT_MEMORY_SCOPE_SUMMARY,
    DEFAULT_MEMORY_SCOPE_TITLE,
    STATE_DIR,
    ensure_dirs,
)


class PowerContextUnavailable(RuntimeError):
    pass


def _imports():
    try:
        import uvicorn
        from powercontext.builtin.persistence.sqlite import SQLiteConfig
        from powercontext.builtin.runtime.config import (
            ExternalSkillsConfig,
            InferenceConfig,
            RuntimeConfig,
        )
        from powercontext.client import PowerContextClient
        from powercontext.http import (
            CreateScopeRequest,
            RememberMemoryRequest,
            SearchMemoryRequest,
        )
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
    except ImportError as exc:  # pragma: no cover - environment guard
        raise PowerContextUnavailable(
            "PowerContext is not installed. Run: "
            'python -m pip install "powercontext[server]==1.2.0"'
        ) from exc
    return {
        "uvicorn": uvicorn,
        "SQLiteConfig": SQLiteConfig,
        "ExternalSkillsConfig": ExternalSkillsConfig,
        "InferenceConfig": InferenceConfig,
        "RuntimeConfig": RuntimeConfig,
        "PowerContextClient": PowerContextClient,
        "CreateScopeRequest": CreateScopeRequest,
        "RememberMemoryRequest": RememberMemoryRequest,
        "SearchMemoryRequest": SearchMemoryRequest,
        "create_server_app": create_server_app,
        "AccessControlConfig": AccessControlConfig,
        "BearerAuthConfig": BearerAuthConfig,
        "HttpConfig": HttpConfig,
        "McpConfig": McpConfig,
        "MetricsConfig": MetricsConfig,
        "ServerSettings": ServerSettings,
        "TracingConfig": TracingConfig,
    }


class PowerContextState:
    def __init__(self, state_dir: Path | None = None) -> None:
        ensure_dirs()
        self.state_dir = state_dir or STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.database_path = self.state_dir / "powercontext.db"
        self.scheduler_path = self.state_dir / "powercontext-scheduler.db"
        self.base_url = ""
        self.client = None
        self._server = None
        self._thread: threading.Thread | None = None
        self._listener: socket.socket | None = None
        self._mods = _imports()

    async def __aenter__(self) -> "PowerContextState":
        await asyncio.to_thread(self._start_server)
        mods = self._mods
        self.client = mods["PowerContextClient"](self.base_url, timeout=180)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    def _start_server(self) -> None:
        mods = self._mods
        database = mods["SQLiteConfig"](url=f"sqlite+aiosqlite:///{self.database_path}")
        settings = mods["ServerSettings"](
            workspace=self.state_dir,
            database=database,
            http=mods["HttpConfig"](host="127.0.0.1"),
            auth=mods["BearerAuthConfig"](enabled=False),
            access=mods["AccessControlConfig"](mode="disabled"),
            inference=mods["InferenceConfig"](),
            runtime=mods["RuntimeConfig"](schedule_seconds=None, experience_schedule_seconds=None),
            external_skills=mods["ExternalSkillsConfig"](),
            mcp=mods["McpConfig"](enabled=False),
            metrics=mods["MetricsConfig"](enabled=False),
            tracing=mods["TracingConfig"](enabled=False),
        )
        app = mods["create_server_app"](
            settings=settings, scheduler_path=self.scheduler_path
        )
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        self._listener = listener
        self.base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = mods["uvicorn"].Server(
            mods["uvicorn"].Config(app, log_level="critical", access_log=False, lifespan="on")
        )
        self._server = server
        self._thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        self._thread.start()
        atexit.register(self._stop_server)
        deadline = time.monotonic() + 45
        while self._thread.is_alive() and not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            self._stop_server()
            raise RuntimeError("PowerContext local server failed to start")

    def _stop_server(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=15)
        if self._listener is not None:
            self._listener.close()
        self._server = None
        self._thread = None
        self._listener = None
        try:
            atexit.unregister(self._stop_server)
        except Exception:
            pass

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None
        await asyncio.to_thread(self._stop_server)

    async def _scope(self):
        mods = self._mods
        request = mods["CreateScopeRequest"](
            title=DEFAULT_MEMORY_SCOPE_TITLE,
            summary=DEFAULT_MEMORY_SCOPE_SUMMARY,
            idempotency_key=DEFAULT_MEMORY_IDEMPOTENCY_KEY,
        )
        return await self.client.create_scope(request)

    async def save_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("state client is not started")
        scope = await self._scope()
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        mods = self._mods
        saved = await self.client.remember_memory(
            mods["RememberMemoryRequest"](
                scope_id=scope.scope_id,
                kind="progress",
                text=text,
                reason="SDD task progress and validation state",
            )
        )
        citation = getattr(getattr(saved, "entry", None), "citation", None)
        return {
            "scope_id": scope.scope_id,
            "text": text,
            "citation": citation.model_dump(mode="json") if citation is not None else None,
        }

    async def load_state(self, task_id: str) -> dict[str, Any] | None:
        if self.client is None:
            raise RuntimeError("state client is not started")
        scope = await self._scope()
        mods = self._mods
        response = await self.client.search_memory(
            mods["SearchMemoryRequest"](
                scope_id=scope.scope_id,
                query=task_id,
                mode="fts",
                limit=20,
            )
        )
        candidates: list[tuple[int, dict[str, Any]]] = []
        for hit in response.hits:
            try:
                payload = json.loads(hit.text)
            except (TypeError, json.JSONDecodeError):
                continue
            if payload.get("task_id") != task_id:
                continue
            revision = int(hit.citation.memory_ref.revision)
            candidates.append((revision, payload))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        payload = candidates[0][1]
        payload["_powercontext_revision"] = candidates[0][0]
        return payload


async def save_task_state(payload: dict[str, Any]) -> dict[str, Any]:
    async with PowerContextState() as state:
        return await state.save_state(payload)


async def load_task_state(task_id: str) -> dict[str, Any] | None:
    async with PowerContextState() as state:
        return await state.load_state(task_id)
