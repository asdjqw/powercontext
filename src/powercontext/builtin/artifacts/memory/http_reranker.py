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

"""HTTP cross-encoder reranking for Memory search candidates."""

from __future__ import annotations

import math
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

HTTP_RERANK_POLICY_ID = "http-cross-encoder-v1"


class HTTPMemoryReranker:
    """Score Memory hits through a batching HTTP scoring service.

    The service accepts at most ``batch_size`` candidates per request, so the
    candidate pool is split into bounded batches while preserving the original
    global rank of every candidate. Selection always happens over the complete
    pool: scores from all batches are merged and ordered by descending score,
    with ties broken by ascending original rank.
    """

    policy_id: str

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = HTTP_RERANK_POLICY_ID,
    ) -> None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("rerank endpoint must be a non-empty string")  # noqa: TRY003
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise ValueError("policy_id must be a non-empty string")  # noqa: TRY003
        self.endpoint = endpoint
        self._client = client
        self.batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Request scores in bounded batches and select the global top ``limit``."""

        candidate_count = len(candidates)
        if candidate_count < 1:
            raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > candidate_count:
            raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003

        scores: dict[int, float] = {}
        request_count = 0
        for offset in range(0, candidate_count, self.batch_size):
            batch = candidates[offset : offset + self.batch_size]
            expected_ranks = tuple(range(offset + 1, offset + len(batch) + 1))
            payload = {
                "query": query,
                "candidates": [
                    {"rank": rank, "text": candidate.text}
                    for rank, candidate in zip(expected_ranks, batch, strict=True)
                ],
            }
            response = await self._client.post(self.endpoint, json=payload)
            response.raise_for_status()
            request_count += 1
            batch_scores = _parse_scores(response, expected_ranks)
            scores.update(batch_scores)

        ordered_ranks = sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit]
        return MemoryRerankDecision(
            selected_ranks=tuple(ordered_ranks),
            usage=InferenceUsage(requests=request_count),
        )


def _parse_scores(response: httpx.Response, expected_ranks: tuple[int, ...]) -> dict[int, float]:
    """Validate one scoring response and return rank -> score for the batch."""

    try:
        body: Any = response.json()
    except ValueError as error:
        raise ValueError("rerank response must be valid JSON") from error
    if not isinstance(body, dict) or set(body) != {"scores"}:
        raise ValueError("rerank response must contain exactly the scores field")  # noqa: TRY003
    raw_scores = body["scores"]
    if not isinstance(raw_scores, list):
        raise ValueError("rerank scores must be a list")  # noqa: TRY003

    expected = set(expected_ranks)
    parsed: dict[int, float] = {}
    for item in raw_scores:
        if not isinstance(item, dict) or set(item) != {"rank", "score"}:
            raise ValueError("each rerank score must contain exactly rank and score")  # noqa: TRY003
        rank = item["rank"]
        score = item["score"]
        if type(rank) is not int or rank not in expected:
            raise ValueError("rerank score ranks must cover exactly the requested batch")  # noqa: TRY003
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError("rerank scores must be finite numbers")  # noqa: TRY003
        numeric_score = float(score)
        if not math.isfinite(numeric_score):
            raise ValueError("rerank scores must be finite numbers")  # noqa: TRY003
        if rank in parsed:
            raise ValueError("rerank score ranks must be unique within one batch")  # noqa: TRY003
        parsed[rank] = numeric_score

    if set(parsed) != expected:
        raise ValueError("rerank scores must cover exactly the requested batch")  # noqa: TRY003
    return parsed


__all__ = ["HTTPMemoryReranker", "HTTP_RERANK_POLICY_ID"]
