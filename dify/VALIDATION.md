# 验证样例：记忆酒馆（Dify × PowerContext）

本文件对应赛题 4.3（验证样例与运行证据）与 4.4（预置记忆初始化）。

## 0. 交付物与导入顺序

| 顺序 | 文件 | 用途 | 适用 Dify |
| --- | --- | --- | --- |
| 1 | [`app.dsl.yml`](app.dsl.yml) | **主 DSL**，5 节点 Chatflow（开始 → 读取记忆 HTTP → LLM → 写入记忆 HTTP → 回答） | **0.15.3**（`version: 0.1.5`，内置 `openai_api_compatible`，无需插件） |
| 2 | [`app-1.x.dsl.yml`](app-1.x.dsl.yml) | 同一应用的 Dify 1.x 版本：`dependencies: []`，模型用内置 `openai`，地址走环境变量 | 1.x（`version: 0.7.0`，无插件） |
| — | [`bridge/app.py`](bridge/app.py) | PowerContext HTTP 桥接后端（`/search`、`/remember`，兼容旧版 `/memory/load`、`/memory/save`） | 任意 |

只导入其中一个 DSL；两个 DSL 是同一应用的两种版本，不要同时导入。

## 1. 初始状态

- **记忆**：清空状态 = 删除 `dify/bridge/.data/` 后重启桥接服务；
- **用户标识**：`user = tavern-guest-001`（DSL 用 `{{#sys.user_id#}}` 作为记忆 key）；
- **Scope 映射**：桥接按 `dify-memory-{user_id}` 建立并复用 PowerContext Scope，
  所以同一 `user` 换会话仍共享记忆，换 `user` 即隔离；
- **预置记忆（可选）**：`python scripts/init_scope.py http://127.0.0.1:8099 tavern-guest-001`
  会写入一条“戴面具的人留下铜扣”的初始记忆，便于直接演示召回。

## 2. 输入与操作顺序

在 Dify 应用聊天页（或 `POST /v1/chat-messages`）按顺序发送：

| 轮次 | 会话 | 输入 | 预期 |
| --- | --- | --- | --- |
| 1 | 新会话 | 我推门走进酒馆，问老板昨晚那个戴面具的人是谁。 | 回答围绕“戴面具的人”，不知道具体身份（此时记忆为空则只能编氛围，不能编玩家选择） |
| 2 | **点“新对话”** | 你还记得我昨晚问过什么吗？ | 回答应复述第 1 轮的问题（“戴面具的人”），且 `conversation_id` 与第 1 轮不同 |
| 3 | 回到第 1 轮会话 | 那枚铜扣你放在哪了？ | 回答延续同一场景（铜扣/木匣），体现同会话上下文 |

## 3. 实际运行结果（2026-11-17，Dify 0.15.3）

环境与部署见 [`verify/00_environment.md`](verify/00_environment.md)。

| 轮次 | HTTP | 耗时 | 实际回答（节选） |
| --- | --- | --- | --- |
| 1 | 200 | 167.7s | “戴面具的人……我只能确认他昨晚来过，名字并未留下……” |
| 2 | 200 | 3.8s | “记得——你昨晚问的是，昨晚那个戴面具的人是谁。” |
| 3 | 200 | 5.3s | “铜扣在柜台后的木匣里，和昨晚留下的物件搁在一处。” |

- 第 2 轮的 `conversation_id` 与第 1 轮不同，仍能召回 → 记忆来自 PowerContext；
- `verify/workflow_nodes.json`：3 次 workflow run、15 个节点全部 `succeeded`，
  其中“读取 PowerContext 记忆”“写入 PowerContext 记忆”两个 HTTP 节点为真实调用；
- `verify/bridge_memories.json`：同一 Scope 下 3 条 Memory 记录；
- `verify/dify_session.json`：三轮原始请求与响应。

## 4. 恢复初始状态

```bash
# 停桥接后删除本地记忆库，再启动即为空状态
rm -rf dify/bridge/.data
python dify/bridge/app.py
```

Dify 侧无需重置：新建对话即可。

## 5. 技术作用说明

| 技术 | 在作品中的作用 | 证据 |
| --- | --- | --- |
| Dify | 承担全部流程编排：接收输入、调用记忆 HTTP 节点、调用模型、写回记忆、输出回答 | `app.dsl.yml` 的 5 个节点；`verify/workflow_nodes.json` 的节点执行记录 |
| PowerContext | 跨会话记忆：按用户建立 Scope，保存每轮互动，下一轮（含新会话）检索并注入提示词 | `verify/bridge_memories.json`、`verify/dify_session.json` 第 2 轮 |

## 6. 已知限制

- 记忆检索是 PowerContext 的关键词/FTS，不是语义向量检索；问法与原文完全不重叠时可能漏召回；
- MiniMax 推理模型的回答包含 `<details>Thinking…</details>` 区块，正文在区块之后；
- 桥接默认无鉴权，仅用于本地/内网演示。
