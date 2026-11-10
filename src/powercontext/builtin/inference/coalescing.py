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

"""Cross-call request coalescing and bounded LRU caching for Embedding calls."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage

DEFAULT_MAX_BATCH_SIZE = 64
DEFAULT_COALESCE_MS = 5.0
DEFAULT_CACHE_SIZE = 1024


class CoalescingEmbeddingModel:
    """Share in-flight Embedding work and cache successful vectors.

    Concurrent calls (and late arrivals while a request is still running)
    share one provider request per unique text.  A short coalescing window lets
    near-simultaneous calls join the same batch.  Successful vectors are kept in
    a bounded LRU cache; failures are never cached and never cancel independent
    batches.  Cancelling one caller never cancels shared provider work.
    """

    def __init__(
        self,
        model: Any,
        *,
        max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
        coalesce_ms: float = DEFAULT_COALESCE_MS,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        if isinstance(max_batch_size, bool) or not isinstance(max_batch_size, int) or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if isinstance(coalesce_ms, bool) or not isinstance(coalesce_ms, (int, float)) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be a non-negative number")  # noqa: TRY003
        if isinstance(cache_size, bool) or not isinstance(cache_size, int) or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003

        self._model = model
        self.profile = model.profile
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = float(coalesce_ms) / 1000.0
        self._cache_size = cache_size

        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[str, asyncio.Future[tuple[EmbeddingVector, InferenceUsage, object]]] = {}
        self._queue: list[str] = []
        self._flush_task: asyncio.Task[None] | None = None

    async def embed(self, texts: Sequence[str], /) -> EmbeddingResult:
        """Embed texts, sharing duplicate and concurrent work, preserving input order."""

        ordered = tuple(texts)
        if not ordered:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))
        self._ensure_loop()

        unique = list(dict.fromkeys(ordered))
        cached: dict[str, EmbeddingVector] = {}
        waits: list[tuple[str, asyncio.Future[tuple[EmbeddingVector, InferenceUsage, object]]]] = []
        for text in unique:
            vector = self._cache_get(text)
            if vector is not None:
                cached[text] = vector
                continue
            future = self._pending.get(text)
            if future is None:
                future = self._loop.create_future()  # type: ignore[union-attr]
                future.add_done_callback(_consume_exception)
                self._pending[text] = future
                self._queue.append(text)
            waits.append((text, future))
        if waits:
            self._schedule_flush()

        results: dict[str, EmbeddingVector] = {}
        batches: list[object] = []
        usage = InferenceUsage(requests=0)
        for text, future in waits:
            vector, batch_usage, token = await asyncio.shield(future)
            results[text] = vector
            if all(token is not seen for seen in batches):
                batches.append(token)
                usage = InferenceUsage(
                    requests=usage.requests + batch_usage.requests,
                    input_tokens=_add_optional(usage.input_tokens, batch_usage.input_tokens),
                    output_tokens=_add_optional(usage.output_tokens, batch_usage.output_tokens),
                )

        vectors = tuple(results[text] if text in results else cached[text] for text in ordered)
        return EmbeddingResult(vectors=vectors, usage=usage)

    # -- coalescing -----------------------------------------------------

    def _ensure_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self._loop = loop
            self._pending.clear()
            self._queue.clear()
            self._flush_task = None

    def _schedule_flush(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = self._loop.create_task(self._flush())  # type: ignore[union-attr]

    async def _flush(self) -> None:
        try:
            if self._coalesce_seconds > 0:
                await asyncio.sleep(self._coalesce_seconds)
            while self._queue:
                batch = tuple(self._queue[: self._max_batch_size])
                del self._queue[: self._max_batch_size]
                if batch:
                    self._loop.create_task(self._run_batch(batch))  # type: ignore[union-attr]
        finally:
            self._flush_task = None
        if self._queue:
            self._schedule_flush()

    async def _run_batch(self, batch: tuple[str, ...]) -> None:
        token = object()
        try:
            result = await self._model.embed(batch)
            vectors = tuple(result.vectors)
            if len(vectors) != len(batch):
                raise ValueError("embedding provider returned a wrong number of vectors")  # noqa: TRY003
            usage = result.usage
        except BaseException as error:  # noqa: BLE001 - errors must reach every waiter
            for text in batch:
                future = self._pending.pop(text, None)
                if future is not None and not future.done():
                    future.set_exception(error)
            return
        for text, vector in zip(batch, vectors, strict=True):
            self._cache_put(text, vector)
            future = self._pending.pop(text, None)
            if future is not None and not future.done():
                future.set_result((vector, usage, token))

    # -- cache and usage -------------------------------------------------

    def _cache_get(self, text: str) -> EmbeddingVector | None:
        if self._cache_size <= 0:
            return None
        vector = self._cache.get(text)
        if vector is not None:
            self._cache.move_to_end(text)
        return vector

    def _cache_put(self, text: str, vector: EmbeddingVector) -> None:
        if self._cache_size <= 0:
            return
        self._cache[text] = vector
        self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

def _add_optional(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def _consume_exception(future: asyncio.Future[Any]) -> None:
    """Retrieve exceptions of shared futures so cancelled waiters cannot leak warnings."""

    if not future.cancelled():
        future.exception()


__all__ = ["CoalescingEmbeddingModel"]
