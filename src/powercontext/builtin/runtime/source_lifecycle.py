# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Source-lifecycle propagation for Memory and Topic Memory availability."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from powercontext.artifacts import ArtifactRef
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime

_POLICIES = ("all", "any")
_PURPOSES = ("generation", "audit")
_TABLE = "pc_source_lifecycle_state"


class SourceLifecycleError(ValueError):
    """Raised when a lifecycle graph, event or reference violates its contract."""


class SourceLifecycleEvent(BaseModel):
    """One versioned availability event for an already registered Source."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    node_id: str
    reason: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool

    @field_validator("node_id", "reason")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-blank string")  # noqa: TRY003
        return value


def _require_node_id(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SourceLifecycleError("node id must be a non-empty trimmed string")
    return value


def _require_positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SourceLifecycleError(f"{field} must be a positive integer")
    return value


def _require_policy(value: object) -> str:
    if value not in _POLICIES:
        raise SourceLifecycleError("policy must be 'all' or 'any'")
    return str(value)


class LifecycleApplication:
    """Create scope-bound lifecycle services over one Runtime."""

    def __init__(self, runtime: "BuiltinRuntime") -> None:
        self._runtime = runtime
        self._services: dict[str, ScopedSourceLifecycle] = {}

    def for_scope(self, scope_id: str, /) -> "ScopedSourceLifecycle":
        service = self._services.get(scope_id)
        if service is None:
            service = ScopedSourceLifecycle(self._runtime, scope_id)
            self._services[scope_id] = service
        return service

    async def filter_topic_hits(self, scope_id: str, hits: tuple[Any, ...]) -> tuple[Any, ...]:
        """Drop Topic hits whose lifecycle node is currently unavailable."""

        service = self.for_scope(scope_id)
        unavailable = await service.unavailable_topic_refs()
        return tuple(hit for hit in hits if _ref_key(hit.artifact_ref) not in unavailable)


def _ref_key(ref: ArtifactRef) -> tuple[str, str, int]:
    return (ref.family, ref.artifact_id, ref.revision)


class ScopedSourceLifecycle:
    """Registered dependency graph and versioned availability for one Scope."""

    def __init__(self, runtime: "BuiltinRuntime", scope_id: str) -> None:
        self._runtime = runtime
        self.scope_id = scope_id
        self._state: dict[str, Any] | None = None

    # -- registration ----------------------------------------------------

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int) -> None:
        node_id = _require_node_id(node_id)
        revision = _require_positive_int("revision", revision)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source_ref must be a SourceRef")
        await self._runtime.records.for_scope(self.scope_id).get_source(source_ref.source_type, source_ref.source_id)
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            state = await self._load_locked()
            nodes = state["nodes"]
            existing = nodes.get(node_id)
            binding = {
                "kind": "source",
                "ref": source_ref.model_dump(mode="json"),
                "revision": revision,
                "sequence": 0,
                "available": True,
                "active": True,
            }
            if existing is not None:
                if {k: existing[k] for k in ("kind", "ref", "revision")} != {
                    k: binding[k] for k in ("kind", "ref", "revision")
                }:
                    raise SourceLifecycleError(f"node {node_id!r} is already registered differently")
                return
            nodes[node_id] = binding
            await self._save_locked(state)

    async def register_memory(
        self,
        node_id: str,
        citation: Any,
        *,
        parents: tuple[str, ...],
        policy: Literal["all", "any"],
    ) -> None:
        node_id = _require_node_id(node_id)
        policy = _require_policy(policy)
        await self._register_derived(
            node_id,
            kind="memory",
            ref=_citation_ref(citation),
            parents=parents,
            policy=policy,
        )

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        *,
        parents: tuple[str, ...],
        policy: Literal["all", "any"],
    ) -> None:
        node_id = _require_node_id(node_id)
        policy = _require_policy(policy)
        if not isinstance(artifact_ref, ArtifactRef):
            raise SourceLifecycleError("artifact_ref must be an ArtifactRef")
        await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
            artifact_ref.family, artifact_ref.artifact_id, artifact_ref.revision
        )
        await self._register_derived(
            node_id,
            kind="topic",
            ref={"family": artifact_ref.family, "artifact_id": artifact_ref.artifact_id, "revision": artifact_ref.revision},
            parents=parents,
            policy=policy,
        )

    async def _register_derived(
        self,
        node_id: str,
        *,
        kind: str,
        ref: dict[str, Any],
        parents: tuple[str, ...],
        policy: str,
    ) -> None:
        if not isinstance(parents, tuple) or not parents:
            raise SourceLifecycleError("a derived node needs at least one parent")
        if len(set(parents)) != len(parents):
            raise SourceLifecycleError("parent nodes must be unique")
        for parent in parents:
            _require_node_id(parent)
        if kind == "memory":
            await self._validate_citation(ref)
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            state = await self._load_locked()
            nodes = state["nodes"]
            for parent in parents:
                if parent not in nodes:
                    raise SourceLifecycleError(f"parent node {parent!r} is not registered")
                if parent == node_id:
                    raise SourceLifecycleError("a node cannot depend on itself")
            binding = {
                "kind": kind,
                "ref": ref,
                "parents": list(parents),
                "policy": policy,
                "active": _node_available(nodes, parents, policy),
            }
            existing = nodes.get(node_id)
            if existing is not None:
                comparable = ("kind", "ref", "parents", "policy")
                if any(existing.get(key) != binding.get(key) for key in comparable):
                    raise SourceLifecycleError(f"node {node_id!r} is already registered differently")
                return
            nodes[node_id] = binding
            if kind == "memory":
                await self._set_memory_active(node_id, binding, binding["active"])
            await self._save_locked(state)

    # -- events ----------------------------------------------------------

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event must be a SourceLifecycleEvent")
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            state = await self._load_locked()
            nodes = state["nodes"]
            node = nodes.get(event.node_id)
            if node is None or node["kind"] != "source":
                raise SourceLifecycleError(f"unknown Source node: {event.node_id!r}")
            if event.revision != node["revision"]:
                raise SourceLifecycleError(
                    f"revision {event.revision} does not match {node['revision']} for {event.node_id!r}"
                )
            current_sequence = int(node.get("sequence", 0))
            if event.sequence < current_sequence:
                raise SourceLifecycleError("event sequence must increase monotonically")
            if event.sequence == current_sequence:
                if event.available != node["available"] or event.reason != node.get("reason"):
                    raise SourceLifecycleError("replayed sequence carries different content")
                return sorted(_active_ids(nodes))
            node["available"] = event.available
            node["sequence"] = event.sequence
            node["reason"] = event.reason
            _recompute(nodes)
            for node_id, binding in nodes.items():
                if binding["kind"] == "memory" and binding["active"] != binding.get("applied_active", True):
                    await self._set_memory_active(node_id, binding, binding["active"])
            await self._save_locked(state)
            return sorted(_active_ids(nodes))

    async def resolve(self, node_id: str, /, *, purpose: str) -> Any:
        if purpose not in _PURPOSES:
            raise SourceLifecycleError(f"unknown resolve purpose: {purpose!r}")
        state = await self._load()
        node = state["nodes"].get(node_id)
        if node is None:
            raise SourceLifecycleError(f"unknown lifecycle node: {node_id!r}")
        if purpose == "generation" and not node["active"]:
            raise SourceLifecycleError(f"node {node_id!r} is not available for generation")
        return _node_reference(node)

    async def unavailable_topic_refs(self) -> set[tuple[str, str, int]]:
        state = await self._load()
        refs = set()
        for node in state["nodes"].values():
            if node["kind"] == "topic" and not node["active"]:
                refs.add(_ref_key(ArtifactRef(**node["ref"])))
        return refs

    # -- persistence -----------------------------------------------------

    async def _load(self) -> dict[str, Any]:
        if self._state is None:
            self._state = await self._read_state()
        return self._state

    async def _load_locked(self) -> dict[str, Any]:
        self._state = await self._read_state()
        return self._state

    async def _read_state(self) -> dict[str, Any]:
        from sqlalchemy import text

        database = getattr(self._runtime._provider, "database", None)
        if database is None or not hasattr(database, "transaction"):
            return {"nodes": {}}
        async with database.transaction() as connection:
            await connection.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                    "scope_id VARCHAR(255) PRIMARY KEY NOT NULL, state TEXT NOT NULL)"
                )
            )
            row = (
                await connection.execute(
                    text(f"SELECT state FROM {_TABLE} WHERE scope_id = :scope_id"),
                    {"scope_id": self.scope_id},
                )
            ).first()
        if row is None:
            return {"nodes": {}}
        return json.loads(str(row[0]))

    async def _save_locked(self, state: dict[str, Any]) -> None:
        from sqlalchemy import text

        database = getattr(self._runtime._provider, "database", None)
        if database is None or not hasattr(database, "transaction"):
            return
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True)
        async with database.transaction() as connection:
            await connection.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                    "scope_id VARCHAR(255) PRIMARY KEY NOT NULL, state TEXT NOT NULL)"
                )
            )
            result = await connection.execute(
                text(f"UPDATE {_TABLE} SET state = :state WHERE scope_id = :scope_id"),
                {"state": payload, "scope_id": self.scope_id},
            )
            if result.rowcount == 0:
                await connection.execute(
                    text(f"INSERT INTO {_TABLE} (scope_id, state) VALUES (:scope_id, :state)"),
                    {"scope_id": self.scope_id, "state": payload},
                )

    # -- native Memory state --------------------------------------------

    async def _validate_citation(self, ref: dict[str, Any]) -> None:
        from powercontext.builtin.artifacts.memory.models import MemoryCitation

        citation = MemoryCitation.model_validate(ref)
        async with self._runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            memory = await service.head(context.artifacts.memory_artifact_id)
            if memory is None:
                raise SourceLifecycleError("Memory is not available for this Scope")
            await service.validate_citation(citation)

    async def _set_memory_active(self, node_id: str, binding: dict[str, Any], active: bool) -> None:
        from powercontext.builtin.artifacts.memory.models import MemoryCitation

        citation = MemoryCitation.model_validate(binding["ref"])
        async with self._runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            memory = await service.head(context.artifacts.memory_artifact_id)
            if memory is None:
                raise SourceLifecycleError(f"Memory is not available for node {node_id!r}")
            entries = [item for item in memory.content.manifest.entries if item.entry_id == citation.entry_id]
            if not entries:
                raise SourceLifecycleError(f"Memory entry for node {node_id!r} was not found")
            entry = await service.validate_citation(citation)
            if (entries[0].state == "active") == active:
                binding["applied_active"] = active
                return
            if active:
                await service.reactivate(memory, entries=(entry,), reason="source lifecycle")
            else:
                await service.forget(memory, entries=(entry,), reason="source lifecycle")
            binding["applied_active"] = active


def _citation_ref(citation: Any) -> dict[str, Any]:
    from powercontext.builtin.artifacts.memory.models import MemoryCitation

    if not isinstance(citation, MemoryCitation):
        raise SourceLifecycleError("citation must be a MemoryCitation")
    return citation.model_dump(mode="json")


def _node_available(nodes: dict[str, Any], parents: tuple[str, ...], policy: str) -> bool:
    supports = [bool(nodes[parent]["active"]) for parent in parents]
    return all(supports) if policy == "all" else any(supports)


def _recompute(nodes: dict[str, Any]) -> None:
    """Recompute derived availability in dependency order."""

    for node in nodes.values():
        if node["kind"] == "source":
            node["active"] = node["available"]
    pending = {node_id for node_id, node in nodes.items() if node["kind"] != "source"}
    progress = True
    while pending and progress:
        progress = False
        for node_id in tuple(pending):
            node = nodes[node_id]
            parents = node["parents"]
            if all(parent not in pending for parent in parents):
                node["active"] = _node_available(nodes, parents, node["policy"])
                pending.remove(node_id)
                progress = True


def _active_ids(nodes: dict[str, Any]) -> list[str]:
    return [node_id for node_id, node in nodes.items() if node["active"]]


def _node_reference(node: dict[str, Any]) -> Any:
    if node["kind"] == "source":
        return SourceRef(**node["ref"])
    if node["kind"] == "memory":
        from powercontext.builtin.artifacts.memory.models import MemoryCitation

        return MemoryCitation.model_validate(node["ref"])
    return ArtifactRef(**node["ref"])


__all__ = ["LifecycleApplication", "ScopedSourceLifecycle", "SourceLifecycleError", "SourceLifecycleEvent"]
