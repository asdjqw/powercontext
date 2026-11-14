"""Minimal OpenAI-compatible MiniMax client used by the SDD workflow."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import EVIDENCE_DIR, ensure_dirs, minimax_settings


class MiniMaxError(RuntimeError):
    pass


def _request(payload: dict[str, Any], timeout: int = 240) -> dict[str, Any]:
    settings = minimax_settings()
    if not settings["api_key"]:
        raise MiniMaxError("MINIMAX_API_KEY is not configured (put it in minimax/.env.local)")
    url = settings["base_url"].rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise MiniMaxError(f"MiniMax HTTP {exc.code}: {detail[:1200]}") from exc


def _record(event: dict[str, Any]) -> None:
    ensure_dirs()
    record = {"at": datetime.now(timezone.utc).isoformat(), **event}
    with (EVIDENCE_DIR / "minimax_requests.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def generate_pricing_implementation(task: str, context_text: str, current_code: str) -> dict[str, Any]:
    settings = minimax_settings()
    system = (
        "You are a careful Python engineer. Produce one complete replacement for "
        "project/src/subledger/pricing.py. Do not change tests or specs. "
        "Output only valid JSON with keys file, content, summary. The content must "
        "be the full Python file, not a diff."
    )
    user = (
        f"TASK:\n{task}\n\n"
        f"ENGINEERING CONTEXT:\n{context_text}\n\n"
        f"CURRENT FILE:\n```python\n{current_code}\n```\n\n"
        "Requirements: minimum discountable order is 10000 cents; discount percent "
        "is capped at 50; keep half-up rounding, zero handling, and ValueError for "
        "negative inputs. Return JSON only."
    )
    payload = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_completion_tokens": 5000,
        "reasoning_effort": "low",
    }
    _record(
        {
            "event": "request",
            "model": settings["model"],
            "base_url": settings["base_url"],
            "task": task,
            "prompt_chars": len(system) + len(user),
            "current_code_sha": __import__("hashlib").sha256(current_code.encode()).hexdigest(),
        }
    )
    response = _request(payload)
    _record({"event": "response", "response": response})
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MiniMaxError(f"Unexpected MiniMax response: {response}") from exc
    try:
        parsed = _extract_json(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MiniMaxError(f"MiniMax did not return JSON: {content[:2000]}") from exc
    if not isinstance(parsed.get("content"), str) or "def apply_discount" not in parsed["content"]:
        raise MiniMaxError(f"MiniMax content is not a pricing implementation: {content[:2000]}")
    parsed.setdefault("file", "project/src/subledger/pricing.py")
    parsed["model"] = response.get("model", settings["model"])
    parsed["usage"] = response.get("usage")
    parsed["raw_response_id"] = response.get("id")
    (EVIDENCE_DIR / "minimax_last_response.json").write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return parsed


def apply_implementation(content: str, target: Path) -> str:
    """Write the model output to the target and return a unified diff."""
    import difflib

    before = target.read_text(encoding="utf-8")
    normalized = content
    if not normalized.endswith("\n"):
        normalized += "\n"
    target.write_text(normalized, encoding="utf-8")
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        normalized.splitlines(keepends=True),
        fromfile=f"a/{target.as_posix()}",
        tofile=f"b/{target.as_posix()}",
    )
    return "".join(diff)
