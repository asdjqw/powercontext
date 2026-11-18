# Dify 侧运行证据（评审请先看这里）

**2026-11-17 已在真实 Dify 0.15.3 实例上跑通完整链路**，证据如下（均为本次运行生成，不是示意）：

| 文件 | 内容 |
| --- | --- |
| [`00_environment.md`](00_environment.md) | 运行环境、版本、部署步骤、模型配置 |
| [`ui/01_first_reply.png`](ui/01_first_reply.png) | Dify 应用聊天页：第 1 轮“戴面具的人”的回答 |
| [`ui/02_new_session_recall.png`](ui/02_new_session_recall.png) | **新会话**里问“你还记得我昨晚问过什么吗？”，老板复述“戴面具的人” |
| [`ui/03_workflow.png`](ui/03_workflow.png) | Dify Studio 的 5 节点工作流编排（含两个 PowerContext HTTP 节点） |
| [`dify_session.json`](dify_session.json) | 3 轮请求与 Dify 原始响应（含 `conversation_id`、耗时、token 用量） |
| [`workflow_nodes.json`](workflow_nodes.json) | 3 次 workflow run、15 个节点执行结果（开始 / 读记忆 HTTP / LLM / 写记忆 HTTP / 回答） |
| [`bridge_memories.json`](bridge_memories.json) | PowerContext 侧同一 Scope 的 3 条 Memory 记录 |
| [`01_sample_session.md`](01_sample_session.md) | 按步骤执行时应看到什么、实际看到了什么 |
| [`02_powercontext_evidence.md`](02_powercontext_evidence.md) | Scope 映射、Memory 表、可复跑查询 |

## 结果

| 轮次 | 会话 | HTTP | 关键内容 |
| --- | --- | --- | --- |
| 1 埋入 | 新会话 | 200 | “戴面具的人……名字并未留下” |
| 2 召回 | **另一个新会话** | 200 | “记得——你昨晚问的是，昨晚那个戴面具的人是谁” |
| 3 追问 | 第 1 轮会话 | 200 | “铜扣在柜台后的木匣里，和昨晚留下的物件搁在一处” |

第 2 轮换了 `conversation_id` 仍能召回，说明记忆来自 PowerContext，而不是 Dify 的会话历史。

## 截图环境

截图取自本次真实运行的 Dify Web（0.15.3，源码构建）：

- 浏览器：Microsoft Edge（Playwright 驱动，1600×1000）；
- 应用：记忆酒馆（Chatflow，`10bd0b8b-0d44-4c86-982a-193a982aa3a0`）；
- 第 1 张是普通聊天页；第 2 张点“New chat”后在**新会话**输入召回问题；第 3 张是 Studio → 编排页。

## 判定口径

- 第 1 轮（新会话）不应知道「戴面具的人」；
- 第 2 轮（**新会话、同 user**）应回答出第 1 轮的问题，且 `conversation_id` 与第 1 轮不同；
- 第 3 轮（同会话）延续上下文；
- 换 `user` 后（scope 隔离）不再知道「戴面具的人」。
