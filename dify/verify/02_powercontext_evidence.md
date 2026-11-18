# PowerContext 作用证据（Scope、Memory、可复跑查询）

本文件对应赛题 3.1「技术结合有效」与 4.3「指定技术的作用及对应记录」。
PowerContext 在本作品中承担**跨会话记忆**：Dify 的 `sys.user_id` → 桥接 → PowerContext Scope → Memory。

## 1. Scope 映射

| 项 | 值 |
| --- | --- |
| 桥接服务 | `dify/bridge/app.py`，`127.0.0.1:8099` |
| 记忆 key | `dify-memory-{user_id}`（本次 `tavern-guest-001`） |
| Scope ID | `scp_6hv437fepj3wmskz6zj1zvq4my` |
| 会话轮次 | 3 轮（第 2 轮为新会话） |
| Memory 条数 | 3 |
| 存储 | PowerContext 1.2.0，SQLite：`dify/bridge/.data/powercontext.db` |

Scope 的创建请求记录在 `pc_scope_creation_requests` 表（key → scope_id），说明同一个用户复用同一个 Scope，
不会每轮新建：

```sql
SELECT idempotency_key, scope_id FROM pc_scope_creation_requests WHERE scope_id='scp_6hv437fepj3wmskz6zj1zvq4my';
```

## 2. 每轮写入的 Memory

`pc_memory_entry_versions` 中该 Scope 的 3 条记录（`kind=progress`），与三轮对话一一对应；
完整内容见 [`bridge_memories.json`](bridge_memories.json)。

| # | 轮次 | 内容（节选） |
| --- | --- | --- |
| 1 | 埋入“戴面具的人” | 回答开头 `<details>…Thinking…</details>`，正文为老板对“戴面具的人”的回应 |
| 2 | 新会话召回 | 回答复述“你昨晚问的是，昨晚那个戴面具的人是谁” |
| 3 | 同会话追问 | 回答“铜扣在柜台后的木匣里” |

> Memory 的 text 是当轮 NPC 回答（含模型输出的 `<details>` 思考区块），由 DSL 的“写入 PowerContext 记忆”
> HTTP 节点在每轮结束时写入；下一轮“读取 PowerContext 记忆”节点把它注入 LLM 提示词。

## 3. 可复跑查询

```bash
# 需要 sqlite3；桥接停止后执行，避免 WAL 锁
sqlite3 dify/bridge/.data/powercontext.db <<'SQL'
SELECT idempotency_key, scope_id FROM pc_scope_creation_requests;
SELECT scope_id, kind, substr(text, 1, 80) FROM pc_memory_entry_versions
WHERE scope_id='scp_6hv437fepj3wmskz6zj1zvq4my' ORDER BY rowid;
SQL
```

预期：第一行查询能看到 `dify-memory-tavern-guest-001 → scp_6hv437fepj3wmskz6zj1zvq4my`，
第二条查询返回 3 行。

## 4. 桥接接口调用记录

Dify 的两个 HTTP 节点（`verify/workflow_nodes.json` 中 `node_type=http-request`，状态 `succeeded`）：

| 节点 | 请求 | 作用 |
| --- | --- | --- |
| 读取 PowerContext 记忆 | `POST /memory/load`（`user_id`, `query`） | 取回该用户最近记忆，拼进 LLM 提示词 |
| 写入 PowerContext 记忆 | `POST /memory/save`（`user_id`, `text`） | 把本轮回答落库，供后续轮次/新会话召回 |

桥接同时提供 JSON 接口 `/search`、`/remember`，便于其它客户端复用；旧版表单接口保持兼容。

## 5. 没有 PowerContext 会怎样

第 2 轮使用**全新的 `conversation_id`**，Dify 自身没有第 1 轮的历史；如果没有 `/memory/load` 注入，
模型不可能知道“戴面具的人”。实测第 2 轮回答复述了第 1 轮的问题，说明记忆确实来自 PowerContext。
