#!/usr/bin/env bash
# 从 Dify Marketplace 安装 OpenAI 兼容模型插件（用于接入 MiniMax 等 OpenAI 兼容端点）。
# 前置：01_login.sh
set -eu

BASE="${DIFY_BASE:-http://localhost}/console/api"
COOKIE="${DIFY_COOKIE_JAR:-/tmp/dify_cookie.txt}"
CSRF=$(cat "${DIFY_CSRF_FILE:-/tmp/dify_csrf.txt}")
PLUGIN="${PLUGIN_PKG:-langgenius/openai_api_compatible:0.0.73@4cf123ffaa4556f079bed6c47f3a462cc825504b859b183239e74eb19136a4b5}"

echo "== 安装插件 $PLUGIN =="
RESP=$(curl -sS -b "$COOKIE" -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -X POST "$BASE/workspaces/current/plugin/install/marketplace" \
  -d "{\"plugin_unique_identifiers\":[\"$PLUGIN\"]}")
echo "$RESP"
TASK=$(printf '%s' "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('task_id') or '')")
if [ -z "$TASK" ]; then
  echo "没有拿到 task_id：插件可能已安装，或 Marketplace 不可用（可改为离线安装 .difypkg）"
  exit 1
fi

echo "== 轮询安装任务 $TASK =="
for i in $(seq 1 30); do
  OUT=$(curl -sS -b "$COOKIE" -H "X-CSRF-Token: $CSRF" "$BASE/workspaces/current/plugin/tasks?page=1&page_size=5")
  STATUS=$(printf '%s' "$OUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for task in data.get('tasks') or []:
    if task.get('id') == '$TASK':
        print(task.get('status') or '')
")
  echo "poll $i: $STATUS"
  case "$STATUS" in success|failed) break;; esac
  sleep 8
done

echo "== 已安装插件 =="
curl -sS -b "$COOKIE" -H "X-CSRF-Token: $CSRF" "$BASE/workspaces/current/plugin/list" | head -c 800
echo
