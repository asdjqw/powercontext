# Dify 0.15.3 真实运行环境与证据

本目录的证据来自 **2026-11-17** 在本机（WSL2 Ubuntu 22.04）真实启动的 Dify **0.15.3**，
不是只验证桥接层。

## 1. 版本

| 组件 | 版本 / 说明 |
| --- | --- |
| Dify | **0.15.3**，源码运行（Gitee 镜像 `gitee.com/mirrors/dify`，tag `0.15.3`，commit `ca19bd31d42fb87c83b91541c473ebae85e9d14e`） |
| API | Python 3.11.18 虚拟环境 + Gunicorn 23.0.0，`127.0.0.1:5001` |
| 数据库 | PostgreSQL 15（`127.0.0.1:5433`，Docker） |
| 缓存 | Redis 6（`127.0.0.1:6380`，Docker） |
| 向量库 | Weaviate 1.19.0（`127.0.0.1:8081`，Docker） |
| PowerContext | 1.2.0，桥接服务 `dify/bridge/app.py`，`127.0.0.1:8099`，SQLite 持久化 |
| 模型 | `openai_api_compatible` 供应商，`https://api.minimax.cn/v1`，模型 `MiniMax-M3.1-Flash`（context 8192，max_tokens 8192） |

## 2. 关键配置（`api/.env`）

```text
DB_HOST=127.0.0.1  DB_PORT=5433  DB_DATABASE=dify
REDIS_HOST=127.0.0.1  REDIS_PORT=6380
VECTOR_STORE=weaviate  WEAVIATE_ENDPOINT=http://127.0.0.1:8081
STORAGE_TYPE=local
SSRF_PROXY_HTTP_URL=   SSRF_PROXY_HTTPS_URL=      # 源码直跑，不经过 squid 代理
MIGRATION_ENABLED=false
```

数据库迁移：`cd api && FLASK_APP=app.py flask db upgrade`。

## 3. 本次运行的步骤

1. 导入 `app.dsl.yml`（`version: 0.1.5`）→ 发布 → 创建应用 API Key；
2. 模型供应商按“自定义模型”方式接入：`POST /console/api/workspaces/current/model-providers/openai_api_compatible/models`
   （该供应商没有 provider 级凭据，凭据挂在模型上）；
3. 启动桥接服务，DSL 的两个 HTTP 节点指向 `http://127.0.0.1:8099/memory/load`、`/memory/save`；
4. 以 `user=tavern-guest-001` 连续跑 3 轮：

| 轮次 | 请求 | 会话 | HTTP | 耗时 |
| --- | --- | --- | --- | --- |
| embed | 我推门走进酒馆，问老板昨晚那个戴面具的人是谁。 | 新会话 | 200 | 167.7s |
| recall_new_session | 你还记得我昨晚问过什么吗？ | **另一个新会话** | 200 | 3.8s |
| follow_up_same_session | 那枚铜扣你放在哪了？ | 第一轮会话 | 200 | 5.3s |

第 2 轮在**全新会话**里回答：“记得——你昨晚问的是，昨晚那个戴面具的人是谁。”
说明记忆来自 PowerContext，而不是 Dify 的会话历史。

## 4. 证据文件

| 文件 | 内容 |
| --- | --- |
| `dify_session.json` | 三轮请求与 Dify 原始响应（含 conversation_id、用量） |
| `workflow_nodes.json` | 3 次 workflow run、15 个节点执行（开始 / 读记忆 HTTP / LLM / 写记忆 HTTP / 回答），状态全部 `succeeded` |
| `bridge_memories.json` | PowerContext 侧的 Scope 与 3 条 Memory 记录（`scp_6hv437fepj3wmskz6zj1zvq4my`） |
| `00_environment.md` | 本文件 |

## 5. 说明

- 源码运行时移除了 `nomic` 供应商模块：它间接依赖的 `pyarrow` 要求 NumPy 2.x，而 Dify 0.15.3 固定
  NumPy 1.26；该供应商与本作品无关，不影响导入与对话。
- MiniMax 推理模型的回答里带 `<details>Thinking…</details>` 区块，这是模型输出的一部分，正文在区块之后。
- 复现脚本与步骤见 [`../README.md`](../README.md) 第 4 节；0.15.3 版 DSL 为 [`../app.dsl.yml`](../app.dsl.yml)。
