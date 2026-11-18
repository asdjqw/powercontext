# PowerContext 作用证据（Scope、Memory、可复跑查询）

本文件对应赛题 3.1「技术结合有效」与 4.3「指定技术的作用及对应记录」。
PowerContext 在本作品中承担**跨会话记忆**：Dify 的 `sys.user_id` → 桥接 → PowerContext Scope → Memory。

## 1. Scope 映射

| 项 | 值 |
| --- | --- |
| 桥接服务 | `dify/bridge/app.py`，`127.0.0.1:8099` |
| 记忆 key | `dify-memory-{user_id}`（本次 `verify-2026-11-18`） |
| Scope ID | `scp_6a6abrkhqq49k3wk15ac16f35e` |
| 会话轮次 | 3 轮（第 2 轮为新会话） |
| Memory 条数 | 3 |
| 存储 | PowerContext 1.2.0，SQLite：`dify/bridge/.data/powercontext.db` |

Scope 的创建请求记录在 `pc_scope_creation_requests` 表（key → scope_id），说明同一个用户复用同一个 Scope，
不会每轮新建。

## 2. 每轮写入的 Memory

`pc_memory_entry_versions` 中该 Scope 的 3 条记录（`kind=progress`），与三轮对话一一对应；
完整内容见 [`bridge_memories.json`](bridge_memories.json)。

| # | 轮次 | 内容（节选） |
| --- | --- | --- |
| 1 | 埋入“戴面具的人” | `玩家：我推门走进酒馆，问老板昨晚那个戴面具的人是谁。` / `老板：门铃轻响……他没留名字，只留下一枚沾着银霜的黑色筹码` |
| 2 | 新会话召回 | `玩家：你还记得我昨晚问过什么吗？` / `老板：记得。你昨晚推门进来，问那个戴面具的人是谁……【记忆命中：是】` |
| 3 | 同会话追问 | `玩家：那枚铜扣你放在哪了？` / `老板：……若你见过另一枚铜扣，它现在不在这间酒馆里。【记忆命中：是】` |

> 桥接落库前会去掉模型输出里的 `<details>…</details>` 思考区块；下一轮 `/memory/load` 先返回该用户最近 5 条记忆，
> 再叠加 FTS 命中，因此新会话的召回不依赖问法与原文的关键词重合。

## 3. 可复跑查询

```bash
# 需要 sqlite3；桥接停止后执行，避免 WAL 锁
sqlite3 dify/bridge/.data/powercontext.db <<'SQL'
SELECT idempotency_key, scope_id FROM pc_scope_creation_requests;
SELECT scope_id, kind, substr(text, 1, 80) FROM pc_memory_entry_versions
WHERE scope_id='scp_6a6abrkhqq49k3wk15ac16f35e' ORDER BY rowid;
SQL
```

预期：第一条能看到 `dify-memory-verify-2026-11-18 → scp_6a6abrkhqq49k3wk15ac16f35e`，
第二条返回 3 行。

## 4. 桥接接口调用记录

Dify 的两个 HTTP 节点（`verify/workflow_nodes.json` 中 `node_type=http-request`，状态 `succeeded`）：

| 节点 | 请求 | 作用 |
| --- | --- | --- |
| 读取 PowerContext 记忆 | `POST /memory/load`（`user_id`, `query`） | 返回最近记忆 + FTS 命中，拼进 LLM 提示词 |
| 写入 PowerContext 记忆 | `POST /memory/save`（`user_id`, `text`） | 保存“玩家提问 + 老板回答”，供后续轮次/新会话召回 |

## 5. 没有 PowerContext 会怎样

第 2 轮使用**全新的 `conversation_id`**，Dify 自身没有第 1 轮的历史；如果没有 `/memory/load` 注入，
模型不可能知道“戴面具的人”，末行只能是 `【记忆命中：否】`。实测第 2 轮复述了第 1 轮的问题并输出 `是`，
说明记忆确实来自 PowerContext。
