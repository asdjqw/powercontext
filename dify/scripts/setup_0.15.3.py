"""One-command setup for the Dify 0.15.3 route.

Waits for the API, creates the admin, logs in, registers MiniMax as a custom
model of the built-in `openai_api_compatible` provider, imports app.dsl.yml,
publishes the app and prints a Service API key.

Usage:
    DIFY_BASE=http://127.0.0.1:5001 MINIMAX_API_KEY=<key> \
        python scripts/setup_0.15.3.py [dsl_path] [output_json]

Dependencies: Python 3.9+ standard library only.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("DIFY_BASE", "http://127.0.0.1:5001")
EMAIL = os.environ.get("DIFY_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("DIFY_PASSWORD", "MvdbDemo12345")
NAME = os.environ.get("DIFY_NAME", "mvdb")
KEY = os.environ.get("MINIMAX_API_KEY", "")
ENDPOINT = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.cn/v1")
MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M3.1-Flash")
PROVIDER = "openai_api_compatible"


def call(method, path, body=None, token=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
            return response.status, (json.loads(text) if text else {})
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(text)
        except json.JSONDecodeError:
            return error.code, {"raw": text[:300]}


def wait_ready(limit=180):
    for _ in range(limit):
        try:
            status, _body = call("GET", "/console/api/setup", timeout=5)
            if status in (200, 403):
                return
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit("Dify API did not become ready: " + BASE)


def main():
    dsl_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "app.dsl.yml")
    out_path = sys.argv[2] if len(sys.argv) > 2 else "dify-setup.json"
    if not KEY:
        raise SystemExit("MINIMAX_API_KEY is required")

    wait_ready()
    status, body = call("POST", "/console/api/setup", {"email": EMAIL, "name": NAME, "password": PASSWORD})
    print("setup", status, body.get("result", body))

    status, body = call("POST", "/console/api/login", {"email": EMAIL, "password": PASSWORD, "remember_me": True})
    token = (body.get("data") or {}).get("access_token", "")
    print("login", status, bool(token))
    if not token:
        raise SystemExit(f"login failed: {body}")

    credentials = {
        "api_key": KEY,
        "endpoint_url": ENDPOINT,
        "mode": "chat",
        "context_size": "8192",
        "max_tokens_to_sample": "8192",
        "function_calling_type": "no_call",
        "stream_function_calling": "not_supported",
        "vision_support": "no_support",
        "stream_mode_delimiter": "\\n\\n",
    }
    status, body = call("POST", f"/console/api/workspaces/current/model-providers/{PROVIDER}/models",
                        {"model": MODEL, "model_type": "llm", "credentials": credentials}, token)
    print("add model", status, body)

    status, body = call("POST", "/console/api/workspaces/current/default-model",
                        {"model_settings": [{"model_type": "llm", "provider": PROVIDER, "model": MODEL}]}, token)
    print("default model", status, body)

    dsl = open(dsl_path, encoding="utf-8").read()
    status, body = call("POST", "/console/api/apps/imports",
                        {"mode": "yaml-content", "yaml_content": dsl}, token, timeout=300)
    print("import", status, json.dumps(body, ensure_ascii=False)[:300])
    app_id = body.get("app_id") or body.get("id")
    if not app_id:
        raise SystemExit(f"import failed: {body}")

    status, body = call("POST", f"/console/api/apps/{app_id}/workflows/publish", {}, token)
    print("publish", status, body)

    status, body = call("POST", f"/console/api/apps/{app_id}/api-keys",
                        {"type": "app", "name": "memory-tavern"}, token)
    print("api key", status, json.dumps(body, ensure_ascii=False)[:200])
    app_key = body.get("token") or (body.get("data") or {}).get("token")

    result = {"app_id": app_id, "app_key": app_key, "model": MODEL, "base": BASE}
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print("saved", out_path)
    print("入口: " + BASE.rsplit(":5001", 1)[0] + ":3000/app/" + app_id if BASE.endswith(":5001") else "")


if __name__ == "__main__":
    main()
