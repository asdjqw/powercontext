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

"""Incremental context transfer with prefix reuse.

A ``ContextPack`` is the complete context for one prepare call, split into
deterministic UTF-8-safe chunks.  A ``ContextPackDelta`` reuses a prefix of the
previous pack and carries only the new suffix, so the receiver can rebuild the
target pack from the base pack and the delta alone.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CHUNK_BYTES = 512
_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})


class ContextPackError(ValueError):
    """Raised when pack or delta data violates the wire protocol."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(value: Any, field: str) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError(f"{field} must be a list of base64 strings")
    decoded: list[bytes] = []
    for encoded in value:
        if not isinstance(encoded, str):
            raise ContextPackError(f"{field} must be a list of base64 strings")
        try:
            decoded.append(base64.b64decode(encoded, validate=True))
        except (binascii.Error, ValueError) as error:
            raise ContextPackError(f"{field} contains invalid base64 data") from error
    return tuple(decoded)


def _pack_digest(items: tuple[bytes, ...]) -> str:
    unsigned = {"schema": PACK_SCHEMA, "items": _encode_items(items)}
    return "sha256:" + hashlib.sha256(_canonical_json(unsigned)).hexdigest()


def _validate_items(items: object) -> tuple[bytes, ...]:
    if not isinstance(items, tuple):
        items = tuple(items)  # type: ignore[arg-type]
    for item in items:
        if not isinstance(item, bytes):
            raise ContextPackError("context pack items must be bytes")
    return tuple(items)


class ContextPack:
    """One complete context version split into deterministic chunks."""

    __slots__ = ("items", "digest")

    def __init__(self, items: tuple[bytes, ...], digest: str) -> None:
        self.items = items
        self.digest = digest

    @classmethod
    def build(cls, items: tuple[bytes, ...], /) -> "ContextPack":
        """Build a complete pack from already chunked bytes."""

        validated = _validate_items(items)
        return cls(validated, _pack_digest(validated))

    @classmethod
    def from_content(cls, content: bytes | str, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> "ContextPack":
        """Split text into deterministic, UTF-8-safe chunks bounded by byte budget."""

        if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes <= 0:
            raise ContextPackError("chunk_bytes must be a positive integer")
        if isinstance(content, bytes):
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ContextPackError("context content must be valid UTF-8") from error
        elif isinstance(content, str):
            text = content
        else:
            raise ContextPackError("context content must be bytes or str")

        chunks: list[bytes] = []
        current = bytearray()
        for character in text:
            encoded = character.encode("utf-8")
            if len(encoded) > chunk_bytes:
                raise ContextPackError("chunk_bytes is too small for one UTF-8 code point")
            if len(current) + len(encoded) > chunk_bytes:
                chunks.append(bytes(current))
                current.clear()
            current.extend(encoded)
        if current:
            chunks.append(bytes(current))
        return cls.build(tuple(chunks))

    @classmethod
    def from_bytes(cls, raw: bytes, /) -> "ContextPack":
        """Decode and validate one wire-format pack."""

        if not isinstance(raw, (bytes, bytearray)):
            raise ContextPackError("pack payload must be bytes")
        try:
            payload = json.loads(bytes(raw))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ContextPackError("pack payload must be valid UTF-8 JSON") from error
        if not isinstance(payload, dict) or set(payload) != _PACK_FIELDS:
            raise ContextPackError("pack payload must contain exactly schema, items, digest and byte_count")
        if payload["schema"] != PACK_SCHEMA:
            raise ContextPackError("pack schema is not supported")
        items = _decode_items(payload["items"], "items")
        expected_digest = _pack_digest(items)
        if payload["digest"] != expected_digest:
            raise ContextPackError("pack digest does not match its items")
        byte_count = payload["byte_count"]
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count != len(bytes(raw)):
            raise ContextPackError("pack byte_count does not match its encoding")
        return cls(items, expected_digest)

    def to_bytes(self) -> bytes:
        """Serialize the canonical wire form, including a self-consistent byte_count."""

        unsigned = {"schema": PACK_SCHEMA, "items": _encode_items(self.items)}
        payload = {**unsigned, "digest": self.digest, "byte_count": 0}
        while True:
            encoded = _canonical_json(payload)
            if payload["byte_count"] == len(encoded):
                return encoded
            payload["byte_count"] = len(encoded)

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ContextPack) and (self.items, self.digest) == (other.items, other.digest)

    def __hash__(self) -> int:
        return hash((self.items, self.digest))

    def __repr__(self) -> str:
        return f"ContextPack(items={len(self.items)}, digest={self.digest!r})"


class ContextPackDelta:
    """A reusable base prefix plus the target suffix of one context update."""

    __slots__ = ("base_digest", "target_digest", "prefix_items", "appended")

    def __init__(
        self,
        base_digest: str,
        target_digest: str,
        prefix_items: int,
        appended: tuple[bytes, ...],
    ) -> None:
        self.base_digest = base_digest
        self.target_digest = target_digest
        self.prefix_items = prefix_items
        self.appended = appended

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack, /) -> "ContextPackDelta":
        """Build a delta that reuses the longest common prefix of two packs."""

        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("delta endpoints must be ContextPack values")
        prefix = 0
        limit = min(len(base.items), len(target.items))
        while prefix < limit and base.items[prefix] == target.items[prefix]:
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    @classmethod
    def from_bytes(cls, raw: bytes, /) -> "ContextPackDelta":
        """Decode and validate one wire-format delta."""

        if not isinstance(raw, (bytes, bytearray)):
            raise ContextPackError("delta payload must be bytes")
        try:
            payload = json.loads(bytes(raw))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ContextPackError("delta payload must be valid UTF-8 JSON") from error
        if not isinstance(payload, dict) or set(payload) != _DELTA_FIELDS:
            raise ContextPackError(
                "delta payload must contain exactly schema, base_digest, target_digest, prefix_items and appended"
            )
        if payload["schema"] != DELTA_SCHEMA:
            raise ContextPackError("delta schema is not supported")
        base_digest = payload["base_digest"]
        target_digest = payload["target_digest"]
        if not isinstance(base_digest, str) or not isinstance(target_digest, str):
            raise ContextPackError("delta digests must be strings")
        prefix_items = payload["prefix_items"]
        if isinstance(prefix_items, bool) or not isinstance(prefix_items, int) or prefix_items < 0:
            raise ContextPackError("delta prefix_items must be a non-negative integer")
        appended = _decode_items(payload["appended"], "appended")
        return cls(base_digest, target_digest, prefix_items, appended)

    def to_bytes(self) -> bytes:
        """Serialize the canonical wire form of this delta."""

        payload = {
            "schema": DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode_items(self.appended),
        }
        return _canonical_json(payload)

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ContextPackDelta) and (
            self.base_digest,
            self.target_digest,
            self.prefix_items,
            self.appended,
        ) == (other.base_digest, other.target_digest, other.prefix_items, other.appended)

    def __hash__(self) -> int:
        return hash((self.base_digest, self.target_digest, self.prefix_items, self.appended))

    def __repr__(self) -> str:
        return (
            f"ContextPackDelta(prefix_items={self.prefix_items}, appended={len(self.appended)}, "
            f"base_digest={self.base_digest!r})"
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta, /) -> ContextPack:
    """Validate a delta against its base pack and rebuild the target pack."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("delta application requires a base pack and a delta")
    if base.digest != delta.base_digest:
        raise ContextPackError("delta base digest does not match the provided base pack")
    if isinstance(delta.prefix_items, bool) or not isinstance(delta.prefix_items, int):
        raise ContextPackError("delta prefix_items must be an integer")
    if delta.prefix_items < 0 or delta.prefix_items > len(base.items):
        raise ContextPackError("delta prefix_items exceeds the base pack")
    rebuilt = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if rebuilt.digest != delta.target_digest:
        raise ContextPackError("delta target digest does not match the rebuilt pack")
    return rebuilt


__all__ = [
    "DEFAULT_CHUNK_BYTES",
    "DELTA_SCHEMA",
    "PACK_SCHEMA",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
