"""Seed one initial memory entry for a demo user through the PowerContext bridge.

Usage:
    python scripts/init_scope.py [bridge_url] [user_id] [text]

The bridge maps each user id to a PowerContext scope named dify-memory-{user_id},
so this is the same scope the Dify workflow uses for that user.
"""
import sys
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
USER = sys.argv[2] if len(sys.argv) > 2 else "tavern-guest-001"
TEXT = (
    sys.argv[3]
    if len(sys.argv) > 3
    else "你推门时带进一阵冷风。老板擦着杯子说：戴面具的人昨晚坐在角落，走前留下一枚铜扣。"
)


def main() -> int:
    data = urllib.parse.urlencode({"user_id": USER, "text": TEXT}).encode()
    request = urllib.request.Request(BASE + "/memory/save", data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request, timeout=30) as response:
        print(response.status, response.read().decode("utf-8", "replace")[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
