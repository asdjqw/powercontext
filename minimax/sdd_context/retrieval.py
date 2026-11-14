"""Task-aware engineering context selection backed by seekdb queries."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .config import ROOT
from .db import SeekdbStore

STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "please",
    "implement", "update", "change", "add", "make", "this", "that", "must", "should",
    "task", "code", "file", "files", "test", "tests",
}
SYNONYMS = {
    "minimum": ["minimum", "min", "threshold", "small", "below", "10000", "10,000"],
    "discount": ["discount", "percent", "percentage", "rate", "cap", "pricing"],
    "pricing": ["pricing", "price", "subtotal", "order", "checkout"],
    "rounding": ["round", "rounding", "cent", "half"],
    "validation": ["validation", "negative", "valueerror", "zero"],
    "regression": ["regression", "compatibility", "existing"],
}


def task_tokens(task: str) -> list[str]:
    words = re.findall(r"[a-z0-9_]+", task.lower())
    tokens: list[str] = []
    for word in words:
        if len(word) < 2 or word in STOPWORDS:
            continue
        tokens.append(word)
        for key, values in SYNONYMS.items():
            if word == key or word in values:
                tokens.extend(values)
    seen: set[str] = set()
    return [token for token in tokens if not (token in seen or seen.add(token))]


def _score(row: dict[str, Any], tokens: list[str]) -> float:
    title = str(row["title"]).lower()
    symbol = str(row["symbol"]).lower()
    content = str(row["content"]).lower()
    kind = str(row["kind"])
    score = 0.0
    for token in tokens:
        if token in title:
            score += 5.0
        if token in symbol:
            score += 3.0
        score += min(content.count(token), 6) * 0.7
        if token in str(row["path"]).lower():
            score += 1.5
    if kind == "spec":
        score *= 1.25
    elif kind == "test":
        score *= 1.05
    elif kind == "doc":
        score *= 0.7
    return score


def _line_for(content: str, tokens: list[str]) -> int:
    lines = content.splitlines()
    for index, line in enumerate(lines, start=1):
        lowered = line.lower()
        if any(token in lowered for token in tokens[:8]):
            return index
    return 1


def _excerpt(content: str, tokens: list[str], limit: int = 520) -> str:
    lines = content.splitlines()
    if not lines:
        return ""
    chosen = _line_for(content, tokens) - 1
    start = max(0, chosen - 3)
    text = "\n".join(lines[start : start + 12]).strip()
    return text[:limit]


def _source(row: dict[str, Any], tokens: list[str], reason: str) -> dict[str, Any]:
    path = str(row["path"])
    content = str(row["content"])
    actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    exists = (ROOT / path).is_file()
    return {
        "source_id": int(row["id"]),
        "path": path,
        "kind": str(row["kind"]),
        "symbol": str(row["symbol"]),
        "title": str(row["title"]),
        "line": _line_for(content, tokens),
        "reason": reason,
        "sha256": actual_hash,
        "exists": exists,
        "excerpt": _excerpt(content, tokens),
    }


def build_context(store: SeekdbStore, task: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    tokens = task_tokens(task)
    rows = store.query_documents(tokens, ["spec", "code", "test", "doc"])
    ranked = sorted(rows, key=lambda row: _score(row, tokens), reverse=True)

    def pick(kind: str, limit: int) -> list[dict[str, Any]]:
        selected = [row for row in ranked if row["kind"] == kind][:limit]
        return [_source(row, tokens, f"task match in {kind}") for row in selected]

    specs = pick("spec", 3)
    code = pick("code", 2)
    tests = pick("test", 2)
    docs = pick("doc", 1)
    all_sources = specs + code + tests + docs
    store.record_context_run(task, [str(item["path"]) for item in all_sources])
    return {
        "task": task,
        "query_terms": tokens,
        "specs": specs,
        "code": code,
        "tests": tests,
        "docs": docs,
        "source_count": len(all_sources),
        "state": state,
    }


def render_prompt(context: dict[str, Any]) -> str:
    """Render selected context as a compact prompt for a coding model."""
    chunks = [
        "You are changing a small Python pricing project. Use only the sources below.",
        f"TASK: {context['task']}",
    ]
    for label, key in (("SPEC", "specs"), ("CODE", "code"), ("TEST", "tests"), ("DOC", "docs")):
        chunks.append(f"\n## {label} SOURCES")
        for source in context.get(key, []):
            chunks.append(
                f"\n### {source['path']}:{source['line']} ({source['symbol']})\n{source['excerpt']}"
            )
    if context.get("state"):
        chunks.append("\n## SAVED TASK STATE\n" + str(context["state"]))
    return "\n".join(chunks)
