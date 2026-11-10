"""Compare the single-statement hybrid candidates with the dual-query baseline.

Runs only where the embedded seekdb binding is available (Linux/macOS). The
comparison is identity based, so it does not need relevance labels: equal fused
identities mean any Recall@10 / MRR@10 computed over these results is equal.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import tempfile
from pathlib import Path

from powercontext.builtin.artifacts.memory import EmbeddingProfile, MemoryEntryInput
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex
from powercontext.builtin.persistence.seekdb import SeekDBConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts

PROFILE = EmbeddingProfile(
    profile_id="hybrid-probe-v1",
    model="deterministic",
    dimension=384,
    distance="l2",
    normalization="unit",
)

_TERMS = ("alpha", "beta", "gamma", "delta")


def _vector(text: str) -> tuple[float, ...]:
    lowered = text.casefold()
    values = [0.0] * PROFILE.dimension
    for index, term in enumerate(_TERMS):
        if term in lowered:
            values[index] = 1.0
            return tuple(values)
    values[3] = 1.0
    return tuple(values)


class _Embedding:
    profile = PROFILE

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        return EmbeddingResult(vectors=tuple(_vector(text) for text in texts))


def _documents() -> tuple[str, ...]:
    documents = []
    for index in range(180):
        term = _TERMS[index % len(_TERMS)]
        documents.append(f"{term} observation number {index} with shared vocabulary record")
    return tuple(documents)


_QUERIES = tuple(
    f"{_TERMS[index % len(_TERMS)]} observation" for index in range(20)
)


def _identity(result) -> tuple:
    return tuple(
        (
            hit.entry_id,
            hit.entry_version_id,
            hit.memory_ref.artifact_id,
            hit.memory_ref.revision,
            hit.matched_by,
        )
        for hit in result.hits
    )


async def main() -> None:
    database_path = Path(tempfile.mkdtemp(prefix="hybrid-probe-")) / "db"
    async with open_builtin_contexts(
        BuiltinConfig(database=SeekDBConfig(path=database_path)), embedding_model=_Embedding()
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=tuple(MemoryEntryInput(kind="fact", text=text) for text in _documents()),
            mode="append",
        )
        assert head is not None
        backend = memory._backend  # noqa: SLF001 - probe-only comparison
        hybrid = backend._index  # noqa: SLF001
        baseline = CompositeMemoryIndex(hybrid._fts, hybrid._vector)  # noqa: SLF001

        mismatches = 0
        latencies: list[float] = []
        for query in _QUERIES:
            backend._index = baseline  # noqa: SLF001
            expected = await memory.search(query, memories=(head,), mode="hybrid", limit=10)
            backend._index = hybrid  # noqa: SLF001
            started = asyncio.get_running_loop().time()
            actual = await memory.search(query, memories=(head,), mode="hybrid", limit=10)
            latencies.append((asyncio.get_running_loop().time() - started) * 1000)
            if _identity(actual) != _identity(expected):
                mismatches += 1
                if mismatches <= 3:
                    print(f"MISMATCH {query!r}")
                    print("  baseline:", _identity(expected)[:5])
                    print("  hybrid:  ", _identity(actual)[:5])
            else:
                print(f"ok {query!r} hits={len(actual.hits)}")

        p50 = statistics.median(latencies)
        print(f"queries={len(_QUERIES)} mismatches={mismatches} p50_ms={p50:.1f}")
        print(f"seekdb_pid_dir={os.path.dirname(database_path)}")
        assert mismatches == 0, "hybrid identities diverged from the dual-query baseline"
        assert p50 <= 500, f"p50 latency {p50:.1f} ms exceeds 500 ms"


if __name__ == "__main__":
    asyncio.run(main())
