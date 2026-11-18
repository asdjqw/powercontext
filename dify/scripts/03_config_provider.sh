#!/usr/bin/env bash
# 为 openai_api_compatible 插件配置 MiniMax 供应商，并做一次真实调用校验。
# 用法：MINIMAX_API_KEY=<key> ./03_config_provider.sh
# 前置：01_login.sh、02_install_plugin.sh
set -eu

BASE="${DIFY_BASE:-http://localhost}/console/api"
COOKIE="${DIFY_COOKIE_JAR:-/tmp/dify_cookie.txt}"
CSRF=$(cat "${DIFY_CSRF_FILE:-/tmp/dify_csrf.txt}")
PROVIDER='langgenius/openai_api_compatible/openai_api_compatible'
KEY="${MINIMAX_API_KEY:?请设置 MINIMAX_API_KEY}"
MODEL="${MINIMAX_MODEL:-MiniMax-M3.1-Flash}"
ENDPOINT="${MINIMAX_BASE_URL:-https://api.minimax.chat/v1}"

python3 - "$KEY" "$MODEL" "$ENDPOINT" > /tmp/dify_model_cred.json <<'PY'
import json
import sys

key, model, endpoint = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({
    "model": model,
    "model_type": "llm",
    "name": model.lower().replace(".", "-"),
    "credentials": {
        "api_key": key,
        "endpoint_url": endpoint,
        "mode": "chat",
        "context_size": "128000",
        "max_tokens_to_sample": "8192",
        "agent_thought_support": "not_supported",
        "compatibility_mode": "strict",
        "api_type": "chat_completions",
        "token_param_name": "auto",
        "stream_include_usage": "disabled",
        "user_identity_support": "no_support",
        "function_calling_type": "no_call",
        "stream_function_calling": "not_supported",
        "vision_support": "no_support",
        "web_search_support": "not_supported",
        "structured_output_support": "not_supported",
        "stream_mode_auth": "not_use",
    },
}, ensure_ascii=False))
PY

echo "== 写入模型凭据 =="
curl -sS -b "$COOKIE" -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -X POST "$BASE/workspaces/current/model-providers/$PROVIDER/models/credentials" \
  --data @/tmp/dify_model_cred.json -w ' HTTP:%{http_code}\n'

echo "== 真实调用校验（会打到 $ENDPOINT）=="
curl -sS -b "$COOKIE" -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -X POST "$BASE/workspaces/current/model-providers/$PROVIDER/models/credentials/validate" \
  --data @/tmp/dify_model_cred.json -w ' HTTP:%{http_code}\n'

echo "== 可用模型 =="
curl -sS -b "$COOKIE" -H "X-CSRF-Token: $CSRF" \
  "$BASE/workspaces/current/model-providers/$PROVIDER/models?model_type=llm" | head -c 600
echo
