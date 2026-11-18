#!/usr/bin/env bash
# 三段式冒烟：埋记忆 → 新会话召回 → 换用户隔离。
# 用法：APP_KEY=app-xxx DIFY_HOST=http://localhost ./05_smoke_test.sh
set -u

KEY="${APP_KEY:?请设置 APP_KEY（app- 开头的 Service API Key）}"
HOST="${DIFY_HOST:-http://localhost}"
USER_A="${USER_A:-tavern-guest-001}"
USER_B="${USER_B:-tavern-guest-002}"

ask() { # $1=query $2=conversation_id(可空) $3=user
  python3 - "$1" "$2" "$3" > /tmp/dify_chat_req.json <<'PY'
import json
import sys

body = {"inputs": {}, "query": sys.argv[1], "response_mode": "blocking", "user": sys.argv[3]}
if sys.argv[2]:
    body["conversation_id"] = sys.argv[2]
print(json.dumps(body, ensure_ascii=False))
PY
  curl -sS --max-time 240 -X POST "$HOST/v1/chat-messages" \
    -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
    --data @/tmp/dify_chat_req.json
}

show() {
  python3 -c "
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception:
    print('RAW:', raw[:400]); raise SystemExit
if data.get('code'):
    print('ERROR:', json.dumps(data, ensure_ascii=False)[:400]); raise SystemExit
print('ANSWER:', (data.get('answer') or '').strip()[:500])
print('CID   :', data.get('conversation_id'))
print('TOKENS:', ((data.get('metadata') or {}).get('usage') or {}).get('total_tokens'))
"
}

echo '########## 1) 新会话，埋入记忆 ##########'
R1=$(ask '我推门走进酒馆，问老板昨晚那个戴面具的人是谁。' '' "$USER_A")
printf '%s' "$R1" | show
CID=$(printf '%s' "$R1" | python3 -c "import sys,json;print(json.load(sys.stdin).get('conversation_id') or '')" 2>/dev/null || true)

echo
echo '########## 2) 全新会话召回（核心） ##########'
echo '期望：回答里出现「戴面具」相关内容，且末行是【记忆命中：是】；CID 与第一轮不同'
ask '你还记得我昨晚问过什么吗？' '' "$USER_A" | show

echo
echo '########## 3) 同一会话追问（对照） ##########'
ask '那枚铜扣你放在哪了？' "$CID" "$USER_A" | show

echo
echo '########## 4) 换用户，验证记忆隔离 ##########'
echo '期望：不该知道「戴面具的人」，末行是【记忆命中：否】'
ask '你还记得我昨晚问过什么吗？' '' "$USER_B" | show
