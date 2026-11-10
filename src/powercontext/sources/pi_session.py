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

"""Pi session history Sources: selected-branch parsing and incremental capture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.connectors import (
    Connector,
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
)
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PI_EVENT_SOURCE_TYPE = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
CHECKPOINT_SCHEMA = "powercontext.pi-session-history.v1"
_SOURCE_ID_PREFIX = "pi"


class PiSessionInput(BaseModel):
    """Complete offline Pi v3 session bytes and the selected leaf node."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected branch, retaining its original record."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """Captured Pi event Source retaining identity and the complete raw record."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Build the stable identity for one Pi event."""

    if not isinstance(session_id, str) or not session_id or session_id != session_id.strip():
        raise ValueError("session id must be a non-empty trimmed string")  # noqa: TRY003
    if not isinstance(event_id, str) or not event_id or event_id != event_id.strip():
        raise ValueError("event id must be a non-empty trimmed string")  # noqa: TRY003
    source_id = f"{_SOURCE_ID_PREFIX}:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"event identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse a Pi v3 session and return visible events from root to the selected leaf."""

    if not isinstance(value, PiSessionInput):
        raise ValueError("value must be a PiSessionInput")  # noqa: TRY003
    try:
        text = value.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be valid UTF-8") from error

    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("Pi session lines must be valid JSON") from error
        if not isinstance(record, dict):
            raise ValueError("Pi session lines must be JSON objects")  # noqa: TRY003
        records.append(record)
    if not records:
        raise ValueError("Pi session must start with a session header")  # noqa: TRY003

    header = records[0]
    if header.get("type") != "session" or header.get("version") != 3:
        raise ValueError("Pi session header must be type=session with version=3")  # noqa: TRY003
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Pi session header must carry a non-empty id")  # noqa: TRY003

    nodes: list[dict[str, Any]] = []
    known_ids: set[str] = set()
    for record in records[1:]:
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id or event_id != event_id.strip():
            raise ValueError("Pi session records must carry a trimmed non-empty id")  # noqa: TRY003
        if event_id in known_ids:
            raise ValueError(f"duplicate Pi session record id: {event_id!r}")  # noqa: TRY003
        parent_id = record.get("parentId")
        if parent_id is not None:
            if not isinstance(parent_id, str) or not parent_id:
                raise ValueError("Pi session parentId must be null or a record id")  # noqa: TRY003
            if parent_id not in known_ids:
                raise ValueError(f"Pi session parent does not precede its child: {parent_id!r}")  # noqa: TRY003
        known_ids.add(event_id)
        nodes.append(record)

    if not nodes:
        raise ValueError("Pi session must contain at least one event record")  # noqa: TRY003
    leaf_id = value.leaf_id if value.leaf_id is not None else nodes[-1].get("id")
    if not isinstance(leaf_id, str) or leaf_id not in known_ids:
        raise ValueError(f"Pi session leaf is not a record id: {leaf_id!r}")  # noqa: TRY003

    by_id = {record["id"]: record for record in nodes}
    path: list[dict[str, Any]] = []
    current: str | None = leaf_id
    while current is not None:
        record = by_id.get(current)
        if record is None:
            raise ValueError(f"Pi session parent chain is broken at {current!r}")  # noqa: TRY003
        path.append(record)
        current = record.get("parentId")
    path.reverse()

    events: list[PiEventInput] = []
    for record in path:
        event = _event_from_record(session_id, record)
        if event is not None:
            events.append(event)
    return tuple(events)


def _event_from_record(session_id: str, record: dict[str, Any]) -> PiEventInput | None:
    event_type = record.get("type")
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            raise ValueError("Pi message records must carry a message object")  # noqa: TRY003
        role = message.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError("Pi message records must carry a message role")  # noqa: TRY003
        if role == "toolResult":
            tool_name = _optional_text(message.get("toolName"))
            tool_call_id = _optional_text(message.get("toolCallId"))
            body = f"[tool_result {tool_name} {tool_call_id}] {_content_text(message.get('content'))}"
        elif role == "bashExecution":
            command = _optional_text(message.get("command"))
            output = _optional_text(message.get("output"))
            body = f"$ {command}\n{output}"
        else:
            body = _content_text(message.get("content"))
    elif event_type == "compaction" or event_type == "branch_summary":
        role = str(event_type)
        body = _optional_text(record.get("summary"))
    elif event_type == "custom_message":
        role = "custom"
        body = _content_text(record.get("content"))
    else:
        return None
    if not body.strip():
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=record["id"],
        parent_id=record.get("parentId"),
        event_type=str(event_type),
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        elif block_type == "toolCall":
            name = _optional_text(block.get("name"))
            call_id = _optional_text(block.get("id"))
            arguments = json.dumps(
                block.get("arguments"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            parts.append(f"[tool_call {name} {call_id}] {arguments}")
    return "\n".join(parts)


def _optional_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _record_digest(record: dict[str, JsonValue]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _PiEventTextEvidenceProjection:
    """Standard powercontext.text-evidence projection for one Pi event."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_TYPE,
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


class _PiEventAdapter:
    name = PI_EVENT_SOURCE_TYPE
    input_class = PiEventInput
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    adapter=_PiEventAdapter(),
    version="1",
    projections=(_PiEventTextEvidenceProjection(),),
)


class PiSessionConnector(Connector):
    """Import visible events of one Pi branch, persisting progress through the lifecycle."""

    name = PI_SESSION_CONNECTOR_NAME
    version = "1"
    source_definitions = frozenset({PI_EVENT_SOURCE_TYPE})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        content = self.path.read_bytes()
        events = parse_pi_session(PiSessionInput(content=content, leaf_id=self.leaf_id))
        checkpoint = session.checkpoint
        known = _known_events(checkpoint)

        # Detect rewritten history anywhere in the archive, including events that are no longer
        # on the selected branch: an imported event's raw record is immutable evidence.
        archive = _archive_records(content)
        for event_id, previous_digest in known.items():
            record = archive.get(event_id)
            if record is not None and _record_digest(record) != previous_digest:
                raise ValueError(f"imported Pi event changed: {event_id!r}")  # noqa: TRY003

        digests: list[tuple[PiEventInput, str]] = [
            (event, _record_digest(event.record)) for event in events
        ]
        for event, digest in digests:
            previous = known.get(event.event_id)
            if previous is not None and previous != digest:
                raise ValueError(f"imported Pi event changed: {event.event_id!r}")  # noqa: TRY003

        for event, digest in digests:
            if event.event_id in known:
                continue
            await session.submit(event.event_id, PI_EVENT_SOURCE_TYPE, event)
            known[event.event_id] = digest

        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"schema": CHECKPOINT_SCHEMA, "events": known},
        )


def _archive_records(content: bytes) -> dict[str, dict[str, JsonValue]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be valid UTF-8") from error
    records: dict[str, dict[str, JsonValue]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("Pi session lines must be valid JSON") from error
        if isinstance(record, dict) and isinstance(record.get("id"), str):
            records[record["id"]] = record
    return records


def _known_events(checkpoint: JsonValue | None) -> dict[str, str]:
    if checkpoint is None:
        return {}
    if not isinstance(checkpoint, dict):
        raise ValueError("Pi session checkpoint must be an object")  # noqa: TRY003
    events = checkpoint.get("events", {})
    if not isinstance(events, dict):
        raise ValueError("Pi session checkpoint events must be an object")  # noqa: TRY003
    known: dict[str, str] = {}
    for event_id, digest in events.items():
        if not isinstance(event_id, str) or not isinstance(digest, str):
            raise ValueError("Pi session checkpoint entries must map ids to digests")  # noqa: TRY003
        known[event_id] = digest
    return known


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_TYPE",
    "PI_SESSION_CONNECTOR_NAME",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
