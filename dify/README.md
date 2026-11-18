# Dify 赛题：记忆酒馆（Memory Tavern）

一个会记住玩家选择的互动剧情小游戏。Dify 负责对话编排，PowerContext 负责**跨会话长期记忆**：
只要 Dify 的 `user` 不变，换一个新会话，酒馆老板仍记得你上次做了什么。

```text
开始 → PowerContext 记忆检索(HTTP) → 酒馆老板(LLM) → PowerContext 记忆写入(HTTP) → 直接回复
```

## 1. 玩法与体验

- 玩家在 Dify 应用聊天页输入一句话（推门、点酒、问人、放狠话），老板会以“记忆酒馆”NPC 的口吻回应；
- 老板会把每次互动写进 PowerContext；**新开一个对话**，用同一个 `user` 再问“你还记得我昨晚问过什么吗？”，
  它会复述你上一轮的提问——这是本作品的核心体验：跨会话记忆；
- 换一个 `user`，记忆立即隔离，老板不再认识你。

应用入口有两个，任选其一：

1. **Dify 应用聊天页**：导入并发布后，在 Dify 控制台「工作室 → 记忆酒馆 → 运行」进入，
   地址形如 `http://<dify-host>/app/<app_id>`；
2. **Service API**：`POST http://<dify-host>/v1/chat-messages`，`Authorization: Bearer app-xxx`，
   `response_mode=blocking`，`user=tavern-guest-001`。

## 2. 技术分工

| 角色 | 承担 | 落点 |
| --- | --- | --- |
| **Dify**（必选） | 全部流程编排：接收输入 → 读取记忆 HTTP → 调用模型 → 写入记忆 HTTP → 输出回答 | [`app.dsl.yml`](app.dsl.yml)（5 节点 Chatflow） |
| **PowerContext 1.2.0** | 跨会话记忆：按用户建立 Scope，保存每轮互动，下一轮（含新会话）检索并注入提示词 | [`bridge/app.py`](bridge/app.py) 暴露 `/search`、`/remember`，兼容旧版 `/memory/load`、`/memory/save` |
| 模型 | 生成 NPC 回应 | 经 `openai_api_compatible` 接入 MiniMax `MiniMax-M3.1-Flash` |

记忆 scope 由 `sys.user_id` 决定（`dify-memory-{user_id}`），绑用户而不是会话——绑会话就退化成 Dify 自带历史，跨会话立刻失效。

## 3. 提交文件与导入顺序（对应赛题 4.1）

| 顺序 | 文件 | 用途 | 适用 Dify |
| --- | --- | --- | --- |
| 1 | [`app.dsl.yml`](app.dsl.yml) | **主 DSL**：5 节点 Chatflow，已在真实 Dify 0.15.3 导入运行 | **0.15.3**（`version: 0.1.5`，内置 `openai_api_compatible`，无需插件） |
| 2 | [`app-1.x.dsl.yml`](app-1.x.dsl.yml) | 同一应用的 Dify 1.x 版本：`dependencies: []`，模型用内置 `openai`，记忆地址走环境变量 | 1.x（`version: 0.7.0`，**不依赖插件**） |
| — | [`bridge/app.py`](bridge/app.py) | PowerContext HTTP 桥接后端（自定义后端源码） | 任意 Python 3.11+ |
| — | [`bridge/requirements.txt`](bridge/requirements.txt) | 后端依赖清单 | — |
| — | [`VALIDATION.md`](VALIDATION.md) | 验证样例：初始状态、输入顺序、预期、实测结果、恢复方式（4.3） | — |
| — | [`scripts/init_scope.py`](scripts/init_scope.py) | 预置一条初始记忆（4.4 预置记忆初始化） | — |
| — | [`verify/`](verify/) | 运行证据：环境、会话 JSON、工作流节点、PowerContext 记忆 | — |

**导入顺序**：先起桥接（第 4.3 节）→ 配置模型 → 导入 `app.dsl.yml`（或 1.x 环境用 `app-1.x.dsl.yml`）→ 发布 → 打开应用聊天页。
两个 DSL 是同一应用的两种版本，按你的 Dify 版本二选一，不要同时导入。

## 4. 版本与依赖（对应赛题 4.2）

| 组件 | 版本 |
| --- | --- |
| Dify | **0.15.3**（推荐，主 DSL 已实测）；1.x（备选 DSL，无插件） |
| 模型供应商 | 0.15.3 用内置 `openai_api_compatible`；1.x 用内置 `openai`（`app-1.x.dsl.yml` 不声明任何插件依赖） |
| 模型 | `MiniMax-M3.1-Flash`（OpenAI 兼容端点；推理模型，`max_tokens` 需 ≥ 2048，本 DSL 用 8192） |
| PowerContext | `1.2.0`（`pip install "powercontext[server]==1.2.0"`） |
| Python | 3.11+（本次实测 3.11.18 / 3.12.16） |
| 数据库 | Dify 侧 PostgreSQL 15、Redis 6、Weaviate 1.19（可用 Docker）；桥接侧 SQLite（PowerContext 自带） |
| DSL 版本 | `version: 0.1.5`（0.15.3，`app.dsl.yml`）；`version: 0.7.0`（1.x，`app-1.x.dsl.yml`） |

> 模型端点本仓库实测用 `https://api.minimax.cn/v1`；如你的 Key 属于其它区域，配置时换成对应端点即可。

## 5. 从零部署

### 5.1 启动 Dify 0.15.3（推荐，本次实测路径）

```bash
# 源码（国内可用 Gitee 镜像）
git clone --depth 1 --branch 0.15.3 https://gitee.com/mirrors/dify.git
cd dify/api
python -m venv .venv && . .venv/bin/activate    # Python 3.11
pip install -r requirements.txt                 # 若仓库无该文件，按 pyproject.toml 安装

# 依赖服务（Docker）：PostgreSQL / Redis / Weaviate
docker run -d --name dify-pg      -e POSTGRES_PASSWORD=difyai123456 -e POSTGRES_DB=dify -p 5433:5432 postgres:15-alpine
docker run -d --name dify-redis   -p 6380:6379 redis:6-alpine
docker run -d --name dify-weaviate -p 8081:8080 -e AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true \
  -e PERSISTENCE_DATA_PATH=/var/lib/weaviate -e DEFAULT_VECTORIZER_MODULE=none semitechnologies/weaviate:1.19.0

# api/.env 关键项
# DB_HOST=127.0.0.1 DB_PORT=5433 DB_DATABASE=dify DB_USERNAME=postgres DB_PASSWORD=difyai123456
# REDIS_HOST=127.0.0.1 REDIS_PORT=6380 VECTOR_STORE=weaviate WEAVIATE_ENDPOINT=http://127.0.0.1:8081
# STORAGE_TYPE=local  MIGRATION_ENABLED=false  SSRF_PROXY_HTTP_URL=  SSRF_PROXY_HTTPS_URL=

FLASK_APP=app.py flask db upgrade
FLASK_APP=app.py gunicorn --bind 127.0.0.1:5001 --workers 1 --worker-class sync --timeout 600 app:app
```

完整环境与踩坑记录见 [`verify/00_environment.md`](verify/00_environment.md)。

### 5.2 或启动 Dify 1.x（备选）

```bash
git clone --depth 1 --branch 1.18.0 https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env
# 按 deploy/.env.example 增补：VECTOR_STORE、SSRF_PROXY_ALLOW_PRIVATE_IPS 等
docker compose -f docker-compose.yaml -f compose.override.yaml up -d
```

控制台 `http://localhost`，首次访问 `/setup` 创建管理员。1.x 路线请导入无插件的 `app-1.x.dsl.yml`；
如果坚持用 `openai_api_compatible`，需要先装好对应插件，或改用 5.1 的 0.15.3。

### 5.3 启动 PowerContext 桥接后端

```bash
cd dify/bridge
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                                    # 监听 0.0.0.0:8099
curl -s http://127.0.0.1:8099/health             # {"ok": true, ...}
```

Dify 与桥接不在同一台机器/容器时，把 DSL 里的 `127.0.0.1:8099` 改成 Dify 能访问的地址：

- Dify 在 Docker（Linux）：给 api/worker 加 `extra_hosts: ["host.docker.internal:host-gateway"]`，
  地址写 `http://host.docker.internal:8099`；
- Dify 源码运行（5.1）：保持 `http://127.0.0.1:8099` 即可。

### 5.4 配置模型

Dify 0.15.3（内置供应商，自定义模型）：

```http
POST /console/api/workspaces/current/model-providers/openai_api_compatible/models
{"model": "MiniMax-M3.1-Flash", "model_type": "llm",
 "credentials": {"api_key": "<你的 Key>", "endpoint_url": "https://api.minimax.cn/v1",
                 "mode": "chat", "context_size": "8192", "max_tokens_to_sample": "8192",
                 "function_calling_type": "no_call", "stream_function_calling": "not_supported",
                 "vision_support": "no_support", "stream_mode_delimiter": "\n\n"}}
```

Dify 1.x：用内置 `openai` 供应商（填入你的 OpenAI 兼容 Key/模型），`app-1.x.dsl.yml` 不声明插件依赖；也可安装 `openai_api_compatible` 插件后按同样字段填写。

### 5.5 导入 DSL、发布、进入应用

一键方式（Dify 0.15.3，源码或容器均可）：

```bash
export DIFY_BASE=http://127.0.0.1:5001
export MINIMAX_API_KEY=<你的 Key>
python scripts/setup_0.15.3.py app.dsl.yml dify-setup.json
# 输出 app_id 与 app-xxx 的 Service API Key
```

手工方式：

1. Dify 控制台 → 工作室 → 创建空白应用（Chatflow/高级对话）→ 导入 DSL → 选 `app.dsl.yml`（0.15.3）
   或 `app-1.x.dsl.yml`（1.x）；
2. 打开应用 → 发布；
3. 进入「运行」/聊天页（入口 `http://<dify-host>/app/<app_id>`），或用 Service API：
   先在应用「API 访问」里创建 Key，再 `POST /v1/chat-messages`。

1.x 版本还需要在应用「环境变量」里把 `POWERCONTEXT_BASE_URL` 改成桥接地址后重新发布。
`scripts/01..05` 是 Dify 1.x 的控制台脚本；0.15.3 直接用 `setup_0.15.3.py`。

### 5.6 初始化数据与恢复初始状态（对应赛题 4.4）

- **初始状态**：删除 `dify/bridge/.data/` 后重启桥接即为空记忆；
- **用户与 Scope**：DSL 用 `{{#sys.user_id#}}`；桥接按 `dify-memory-{user_id}` 建/复用 Scope；
- **预置记忆（可选）**：

```bash
python scripts/init_scope.py http://127.0.0.1:8099 tavern-guest-001
```

## 6. 验证样例与实测结果（对应赛题 4.3）

完整样例见 [`VALIDATION.md`](VALIDATION.md)。摘要：

| 轮次 | 会话 | 输入 | 实测结果 |
| --- | --- | --- | --- |
| 1 | 新会话 | 我推门走进酒馆，问老板昨晚那个戴面具的人是谁。 | “戴面具的人……名字并未留下” |
| 2 | **新会话** | 你还记得我昨晚问过什么吗？ | “记得——你昨晚问的是，昨晚那个戴面具的人是谁。” |
| 3 | 第 1 轮会话 | 那枚铜扣你放在哪了？ | “铜扣在柜台后的木匣里，和昨晚留下的物件搁在一处。” |

第 2 轮换了 `conversation_id` 仍能召回，说明记忆来自 PowerContext，而不是 Dify 会话历史。

## 7. 实测证据（2026-11-17，Dify 0.15.3）

| 文件 | 内容 |
| --- | --- |
| [`verify/00_environment.md`](verify/00_environment.md) | 环境、版本、部署与踩坑 |
| [`verify/ui/01_first_reply.png`](verify/ui/01_first_reply.png) | Dify 聊天页：第 1 轮“戴面具的人” |
| [`verify/ui/02_new_session_recall.png`](verify/ui/02_new_session_recall.png) | **新会话**召回第 1 轮的问题 |
| [`verify/ui/03_workflow.png`](verify/ui/03_workflow.png) | Dify Studio 的 5 节点编排 |
| [`verify/dify_session.json`](verify/dify_session.json) | 3 轮请求与 Dify 原始响应 |
| [`verify/workflow_nodes.json`](verify/workflow_nodes.json) | 3 次 workflow run、15 个节点执行，全部 `succeeded` |
| [`verify/bridge_memories.json`](verify/bridge_memories.json) | 同一 Scope 的 3 条 Memory 记录 |

## 8. 设计要点

- **地址可改**：0.15.3 DSL 的两个 HTTP 节点写 `127.0.0.1:8099`，换环境时按 5.3 修改；1.x DSL 用环境变量。
- **记忆失败不阻断对话**：1.x DSL 的两个 HTTP 节点设 `error_strategy: default-value`；0.15.3 可用节点的
  失败重试/默认值配置，桥接不可用时对话仍能继续。
- **scope 绑定 `sys.user_id`**，换会话共享，换用户隔离。
- **写入是 append**，保留每次互动。

## 9. 已知限制

1. 记忆检索是 PowerContext 的关键词/FTS，不是语义向量检索，问法与原文完全不重叠时可能漏召回；
2. 桥接默认无鉴权，仅用于本地/内网演示，不要直接暴露公网；
3. 模型为推理模型，`max_tokens` 给小会返回空 content；回答里会带 `<details>Thinking…</details>` 区块，正文在区块之后；
4. Dify 1.x 路线请用无插件的 `app-1.x.dsl.yml`；离线环境推荐走 0.15.3；
5. 0.15.3 的 HTTP 节点没有 `error_strategy` 时，桥接不可用会让本轮失败——演示前先确认 `/health`。

## 10. 参考与许可

- Dify 0.15.3 / 1.x 的 DSL 结构与导入方式参考 Dify 官方导出格式；DSL 内容（提示词、节点、判定）为本作品自行编写；
- 控制台 API（登录、模型、导入、发布、API Key）为 Dify 公开接口；
- PowerContext：https://github.com/oceanbase/powercontext （Apache-2.0）。
