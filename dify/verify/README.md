# Dify 侧运行证据（评审请先看这里）

**2026-11-18 已在真实 Dify 0.15.3 实例上跑通完整链路**，证据如下（均为本次运行生成）：

| 文件 | 内容 |
| --- | --- |
| [`00_environment.md`](00_environment.md) | 运行环境、版本、部署步骤、模型配置 |
| [`ui/01_first_reply.png`](ui/01_first_reply.png) | Dify 聊天页：第 1 轮，末行 `【记忆命中：否】` |
| [`ui/02_new_session_recall.png`](ui/02_new_session_recall.png) | **新会话**问“你还记得我昨晚问过什么吗？”，回答复述第 1 轮，末行 `【记忆命中：是】` |
| [`ui/03_workflow.png`](ui/03_workflow.png) | Dify Studio 的 5 节点工作流编排 |
| [`dify_session.json`](dify_session.json) | 3 轮请求与 Dify 原始响应（含 `conversation_id`、耗时、标记） |
| [`workflow_nodes.json`](workflow_nodes.json) | 3 次 workflow run、15 个节点执行结果 |
| [`bridge_memories.json`](bridge_memories.json) | PowerContext 侧同一 Scope 的 3 条 Memory |
| [`01_sample_session.md`](01_sample_session.md) | 按步骤执行时应看到什么、实际看到了什么 |
| [`02_powercontext_evidence.md`](02_powercontext_evidence.md) | Scope 映射、Memory 表、可复跑查询 |

## 结果

| 轮次 | 会话 | HTTP | 标记 | 关键内容 |
| --- | --- | --- | --- | --- |
| 1 埋入 | 新会话 | 200 | `【记忆命中：否】` | “他没留名字，只留下一枚沾着银霜的黑色筹码” |
| 2 召回 | **另一个新会话** | 200 | `【记忆命中：是】` | “记得。你昨晚推门进来，问那个戴面具的人是谁” |
| 3 追问 | 第 1 轮会话 | 200 | `【记忆命中：是】` | 延续“铜扣/黑色筹码”的场景 |

第 2 轮换了 `conversation_id` 仍输出 `是`，说明记忆来自 PowerContext，而不是 Dify 的会话历史。

## 截图环境

- 浏览器：Microsoft Edge（Playwright 驱动，1600×1000）；
- 应用：记忆酒馆（Chatflow，`ca6c53fe-db8b-4033-804f-ce9006cde775`）；
- 第 1 张是第一轮聊天页；第 2 张点“New chat”后在**新会话**输入召回问题；第 3 张是 Studio → 编排页。

## 判定口径

- 第 1 轮（新会话）末行 `【记忆命中：否】`；
- 第 2 轮（**新会话、同 user**）复述第 1 轮内容，末行 `【记忆命中：是】`，`conversation_id` 与第 1 轮不同；
- 第 3 轮（同会话）末行 `【记忆命中：是】`；
- 换 `user` 后（scope 隔离）不再知道之前的互动，末行 `【记忆命中：否】`。
