#!/usr/bin/env bash
# 登录 Dify 控制台，保存 cookie 与 CSRF token，供后续脚本复用。
# 用法：
#   DIFY_BASE=http://localhost DIFY_ADMIN_EMAIL=admin@example.com \
#   DIFY_ADMIN_PASSWORD='<password>' ./01_login.sh
set -eu

BASE="${DIFY_BASE:-http://localhost}"
API="$BASE/console/api"
EMAIL="${DIFY_ADMIN_EMAIL:?请设置 DIFY_ADMIN_EMAIL}"
PASSWORD="${DIFY_ADMIN_PASSWORD:?请设置 DIFY_ADMIN_PASSWORD}"
COOKIE="${DIFY_COOKIE_JAR:-/tmp/dify_cookie.txt}"
CSRF_FILE="${DIFY_CSRF_FILE:-/tmp/dify_csrf.txt}"

command -v python3 >/dev/null 2>&1 || { echo "需要 python3（用于 JSON 处理）"; exit 1; }

# Dify 1.x 的登录接口要求 password 字段为 base64。
PASSWORD_B64=$(printf '%s' "$PASSWORD" | base64 | tr -d '\n')

rm -f "$COOKIE"
HTTP=$(curl -sS -c "$COOKIE" -o /tmp/dify_login.json -w '%{http_code}' \
  -X POST "$API/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD_B64\",\"language\":\"zh-Hans\",\"remember_me\":true}")

CSRF=$(awk '/csrf_token/ {print $7}' "$COOKIE" 2>/dev/null | tail -n1)
printf '%s' "$CSRF" > "$CSRF_FILE"

echo "login HTTP=$HTTP csrf_len=${#CSRF}"
if [ "$HTTP" != "200" ]; then
  echo "登录失败，响应："; cat /tmp/dify_login.json; exit 1
fi
echo "cookie=$COOKIE csrf=$CSRF_FILE"
