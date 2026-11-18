# 验证样例：记忆酒馆（Dify × PowerContext）

本文件对应赛题 4.3（验证样例与运行证据）与 4.4（预置记忆初始化）。

## 0. 交付物与导入顺序

| 顺序 | 文件 | 用途 | 适用 Dify |
| --- | --- | --- | --- |
| 1 | [`app.dsl.yml`](app.dsl.yml) | **主 DSL**，5 节点 Chatflow（开始 → 读取记忆 HTTP → LLM → 写入记忆 HTTP → 回答） | **0.15.3**（`version: 0.1.5`，内置 `openai_api_compatible`，无需插件） |
| 2 | [`app-1.x.dsl.yml`](app-1.x.dsl.yml) | 同一应用的 Dify 1.x 版本，地址走环境变量 `POWERCONTEXT_BASE_URL` | 1.x（`version: 0.7.0`，`dependencies: []`） |
| — | [`bridge/app.py`](bridge/app.py) | PowerContext HTTP 桥接后端（`/search`、`/remember`，兼容 `/memory/load`、`/memory/save`） | 任意 |

只导入其中一个 DSL；两个 DSL 是同一应用的两种版本，不要同时导入。

## 1. 核心规则（应用必须遵守）

每一轮回答的最后一行必须是下面两个标记之一，模型不得省略：

- 记忆为空（或没有可用的历史记录）→ 最后一行输出 **`【记忆命中：否】`**，正文把这次当作初次见面或想不起来；
- 记忆非空（记录了玩家之前的提问或行动）→ 正文自然呼应记忆内容，最后一行输出 **`【记忆命中：是】`**。

记忆的存取方式：

- 每轮由“写入 PowerContext 记忆”节点保存 **`玩家：<本轮提问>\n老板：<回答正文>`**；
- 桥接会去掉模型输出里的 `<details>…</details>` 思考区块，只保留回答正文；
- 下一轮“读取 PowerContext 记忆”节点先返回该用户最近几条记忆（确定性召回），再叠加 FTS 命中，
  因此**新会话**也能看到上一轮内容，不依赖问法与原文的关键词重合。

## 2. 初始状态

- 记忆为空 = 删除 `dify/bridge/.data/` 后重启桥接；
- 用户标识：`user = verify-2026-11-18`（DSL 用 `{{#sys.user_id#}}` 作为记忆 key）；
- Scope 映射：桥接按 `dify-memory-{user_id}` 建立并复用 PowerContext Scope；
- 预置记忆（可选）：`python scripts/init_scope.py http://127.0.0.1:8099 <user_id>`。

## 3. 输入与预期

| 轮次 | 会话 | 输入 | 预期标记 | 预期内容 |
| --- | --- | --- | --- | --- |
| 1 | 新会话 | 我推门走进酒馆，问老板昨晚那个戴面具的人是谁。 | `【记忆命中：否】` | 初次见面/想不起来，给氛围和线索，不编造玩家做过的选择 |
| 2 | **点“新对话”** | 你还记得我昨晚问过什么吗？ | `【记忆命中：是】` | 复述第 1 轮的问题（戴面具的人），`conversation_id` 与第 1 轮不同 |
| 3 | 回到第 1 轮会话 | 那枚铜扣你放在哪了？ | `【记忆命中：是】` | 延续同一场景，呼应记忆里的内容 |

## 4. 实测结果（2026-11-18，Dify 0.15.3 + 本仓库桥接）

| 轮次 | HTTP | 耗时 | 实际回答（末尾） | 标记 |
| --- | --- | --- | --- | --- |
| 1 | 200 | 4.5 s | “他没留名字，只留下一枚沾着银霜的黑色筹码……” | `【记忆命中：否】` |
| 2 | 200 | 3.1 s | “……你究竟是来寻答案，还是来换答案的？”（复述第 1 轮的戴面具的人） | `【记忆命中：是】` |
| 3 | 200 | 3.6 s | “……若你见过另一枚铜扣，它现在不在这间酒馆里。” | `【记忆命中：是】` |

- 第 2 轮是**新会话**（`conversation_id` 与第 1 轮不同），仍输出 `是` → 记忆来自 PowerContext；
- 原始响应见 [`verify/dify_session.json`](verify/dify_session.json)；
- 界面截图：[`verify/ui/01_first_reply.png`](verify/ui/01_first_reply.png)、
  [`verify/ui/02_new_session_recall.png`](verify/ui/02_new_session_recall.png)、
  [`verify/ui/03_workflow.png`](verify/ui/03_workflow.png)；
- 节点级执行见 [`verify/workflow_nodes.json`](verify/workflow_nodes.json)，两个 HTTP 节点与 LLM 节点均 `succeeded`。

## 5. 恢复初始状态

```bash
# 停桥接后删除本地记忆库，再启动即为空状态
rm -rf dify/bridge/.data
python dify/bridge/app.py
```

Dify 侧新建对话即可。

## 6. 技术作用说明

| 技术 | 在作品中的作用 | 证据 |
| --- | --- | --- |
| Dify | 全部流程编排：输入、读取记忆、调用模型、写回记忆、输出 | `app.dsl.yml` 5 个节点；`verify/workflow_nodes.json` |
| PowerContext | 按用户保存每轮“玩家提问 + 老板回答”，下一轮（含新会话）检索并注入提示词 | `verify/bridge_memories.json`、`verify/dify_session.json` 第 2 轮 |

## 7. 已知限制

- 记忆召回优先返回该用户最近 5 条 + FTS 命中（最多 8 条），对话很长时会截断更早的内容；
- 模型是推理模型，回答会带 `<details>Thinking…</details>` 区块，正文在区块之后；桥接落库前已去掉该区块；
- 桥接默认无鉴权，仅用于本地/内网演示。
