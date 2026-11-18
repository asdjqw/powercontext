#!/usr/bin/env bash
# 导入 DSL（默认 app-1.18.dsl.yml，仅用于 Dify 1.18），发布应用并创建 Service API Key。
# Dify 0.15.3 请用同目录的 setup_0.15.3.py。
# 用法：./04_import_app.sh [要覆盖的 app_id]
# 前置：01_login.sh；模型已在 03_config_provider.sh 配好
set -eu

BASE="${DIFY_BASE:-http://localhost}/console/api"
COOKIE="${DIFY_COOKIE_JAR:-/tmp/dify_cookie.txt}"
CSRF=$(cat "${DIFY_CSRF_FILE:-/tmp/dify_csrf.txt}")
DSL="${DSL_PATH:-$(cd "$(dirname "$0")/.." && pwd)/app-1.18.dsl.yml}"
TARGET_APP="${1:-}"

[ -f "$DSL" ] || { echo "找不到 DSL：$DSL"; exit 1; }

python3 - "$DSL" "$TARGET_APP" > /tmp/dify_import.json <<'PY'
import json
import sys

dsl_path, app_id = sys.argv[1], sys.argv[2]
payload = {
    "mode": "yaml-content",
    "yaml_content": open(dsl_path, encoding="utf-8").read(),
    "name": "记忆酒馆",
}
if app_id:
    payload["app_id"] = app_id
print(json.dumps(payload, ensure_ascii=False))
PY

echo "== 导入 DSL =="
RESP=$(curl -sS -b "$COOKIE" -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -X POST "$BASE/apps/imports" --data @/tmp/dify_import.json)
echo "$RESP"
APP_ID=$(printf '%s' "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('app_id') or '')")
[ -n "$APP_ID" ] || { echo "导入失败，请看上面的响应"; exit 1; }

echo "== 发布应用 =="
curl -sS -b "$COOKIE" -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -X POST "$BASE/apps/$APP_ID/workflows/publish" -d '{}' -w ' HTTP:%{http_code}\n'

echo "== 创建 Service API Key =="
curl -sS -b "$COOKIE" -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -X POST "$BASE/apps/$APP_ID/api-keys" -d '{"type":"app","name":"memory-tavern"}' -w ' HTTP:%{http_code}\n'

echo
echo "APP_ID=$APP_ID"
echo "把上面返回的 token 存到 APP_KEY，然后运行 05_smoke_test.sh"