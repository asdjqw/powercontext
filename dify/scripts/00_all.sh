#!/usr/bin/env bash
# 一键跑完 Dify 侧配置：登录 → 装插件 → 配模型 → 导入发布。
# 前置：
#   - Dify 1.18 已启动，且已创建管理员
#   - 桥接服务已启动：python bridge/app.py（8099）
# 用法：
#   DIFY_BASE=http://localhost \
#   DIFY_ADMIN_EMAIL=admin@example.com DIFY_ADMIN_PASSWORD='<pwd>' \
#   MINIMAX_API_KEY=<key> ./scripts/00_all.sh
set -eu

DIR=$(cd "$(dirname "$0")" && pwd)

: "${DIFY_BASE:?请设置 DIFY_BASE，例如 http://localhost}"
: "${DIFY_ADMIN_EMAIL:?请设置 DIFY_ADMIN_EMAIL}"
: "${DIFY_ADMIN_PASSWORD:?请设置 DIFY_ADMIN_PASSWORD}"
: "${MINIMAX_API_KEY:?请设置 MINIMAX_API_KEY（或跳过 03 脚本，导入后手动改绑模型）}"

echo "== [1/4] 登录 =="
"$DIR/01_login.sh"

echo "== [2/4] 安装 openai_api_compatible 插件 =="
"$DIR/02_install_plugin.sh"

echo "== [3/4] 配置 MiniMax 供应商 =="
"$DIR/03_config_provider.sh"

echo "== [4/4] 导入 DSL 并发布 =="
"$DIR/04_import_app.sh"

cat <<'TIP'

下一步：
1) 打开 Dify 应用「记忆酒馆」→ 工作流 → 环境变量，
   把 POWERCONTEXT_BASE_URL 改成你的桥接地址（宿主默认 http://host.docker.internal:8099）；
2) 用 04 脚本输出的 app-xxx 作为 APP_KEY，运行：
   APP_KEY=app-xxx DIFY_HOST=$DIFY_BASE ./scripts/05_smoke_test.sh
   期望第 2 轮出现「戴面具」相关内容 +【记忆命中：是】。
TIP
