#!/usr/bin/env python3
"""跑一轮完整的 Dify 会话并把原始响应保存成 verify/dify_session.json。

用法：
    python verify/run_dify_session.py \
        --host http://localhost \
        --app-key app-xxxxxxxx \
        --user tavern-guest-001

脚本会：
  1. 新会话发第 1 轮（埋记忆）；
  2. 换新会话发第 2 轮（跨会话召回，核心证据）；
  3. 同一会话追问第 3 轮（对照）；
  4. 换 user 发第 4 轮（隔离）。
每一步的请求、HTTP 状态、响应原文、耗时都写进 dify_session.json，
可直接作为评审材料；不需要额外的 JSON 工具。
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

TURNS = [
    ("embed", "我推门走进酒馆，问老板昨晚那个戴面具的人是谁。"),
    ("recall_new_session", "你还记得我昨晚问过什么吗？"),
    ("follow_up_same_session", "那枚铜扣你放在哪了？"),
    ("isolation_other_user", "你还记得我昨晚问过什么吗？"),
]


def post(host: str, app_key: str, payload: dict) -> tuple[int, str, float]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{host.rstrip('/')}/v1/chat-messages",
        data=body,
        headers={"Authorization": f"Bearer {app_key}", "Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            return response.status, response.read().decode("utf-8", "replace"), time.monotonic() - started
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace"), time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://localhost")
    parser.add_argument("--app-key", required=True)
    parser.add_argument("--user", default="tavern-guest-001")
    parser.add_argument("--other-user", default="tavern-guest-002")
    parser.add_argument("--out", default=str(Path(__file__).with_name("dify_session.json")))
    args = parser.parse_args()

    records = []
    conversation_id = ""
    for name, query in TURNS:
        user = args.other_user if name == "isolation_other_user" else args.user
        payload = {"inputs": {}, "query": query, "response_mode": "blocking", "user": user}
        if name == "follow_up_same_session" and conversation_id:
            payload["conversation_id"] = conversation_id
        status, raw, elapsed = post(args.host, args.app_key, payload)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"raw": raw[:1000]}
        if name == "embed" and isinstance(data, dict):
            conversation_id = data.get("conversation_id") or ""
        answer = (data.get("answer") or "").strip() if isinstance(data, dict) else ""
        print(f"[{name}] HTTP {status} {elapsed:.2f}s -> {answer[:120]!r}")
        records.append(
            {
                "turn": name,
                "request": payload,
                "http_status": status,
                "elapsed_seconds": round(elapsed, 3),
                "response": data,
                "answer": answer,
                "memory_hit_marker": "【记忆命中：是】" if "【记忆命中：是】" in answer else ("【记忆命中：否】" if "【记忆命中：否】" in answer else ""),
            }
        )

    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host": args.host,
        "user": args.user,
        "other_user": args.other_user,
        "turns": records,
    }
    Path(args.out).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
