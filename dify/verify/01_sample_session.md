# 验证样例：一轮完整会话（含新会话召回）

本文件是 [`../VALIDATION.md`](../VALIDATION.md) 的运行记录版：按步骤执行时应看到什么、实际看到了什么。

## 0. 前置

- Dify **0.15.3** 已启动（见 [`00_environment.md`](00_environment.md)），应用由 `app.dsl.yml` 导入并发布；
- 桥接 8099 已启动，`/health` 返回 `{"ok": true}`；
- 记忆为空：删除 `dify/bridge/.data/` 后重启桥接；
- `user = verify-2026-11-18`（Dify 终端用户 ID，映射为 `sys.user_id`）。

## 1. 第 1 轮：新会话，埋入“戴面具的人”

```json
{"inputs": {}, "query": "我推门走进酒馆，问老板昨晚那个戴面具的人是谁。",
 "response_mode": "blocking", "user": "verify-2026-11-18"}
```

**预期**：初次见面/想不起来，给氛围与线索，不编造玩家做过的选择；末行 `【记忆命中：否】`。
**实测**（HTTP 200，4.5s）：

> “……他没留名字，只留下一枚沾着银霜的黑色筹码——想知道他是谁，得看你拿什么来换。”
>
> `【记忆命中：否】`

## 2. 第 2 轮：**新会话**，验证跨会话记忆

点“新对话”（`conversation_id` 置空），同一 `user`：

```json
{"query": "你还记得我昨晚问过什么吗？", "user": "verify-2026-11-18"}
```

**预期**：复述第 1 轮的问题，且 `conversation_id` 与第 1 轮不同；末行 `【记忆命中：是】`。
**实测**（HTTP 200，3.1s）：

> “记得。你昨晚推门进来，问那个戴面具的人是谁，只留下一枚沾着银霜的黑色筹码作为线索……”
>
> `【记忆命中：是】`

这一步证明记忆来自 PowerContext：第 2 轮是全新会话，Dify 自身没有第 1 轮历史。

## 3. 第 3 轮：回到第 1 轮会话，延续上下文

```json
{"query": "那枚铜扣你放在哪了？", "conversation_id": "第 1 轮的 id", "user": "verify-2026-11-18"}
```

**实测**（HTTP 200，3.6s）：

> “……铜扣？我可没把它收起来——昨晚他留在这里的，是那枚沾着银霜的黑色筹码……”
>
> `【记忆命中：是】`

## 4. 对账

| 检查 | 文件 | 结果 |
| --- | --- | --- |
| 三轮请求与响应 | [`dify_session.json`](dify_session.json) | 三轮 HTTP 200，标记依次为 否 / 是 / 是 |
| 三次 workflow run | [`workflow_nodes.json`](workflow_nodes.json) | 3 runs / 15 nodes，全部 `succeeded` |
| 两个 HTTP 节点真实调用 | 同上 | 读取/写入 PowerContext 记忆均 `http-request` + `succeeded` |
| PowerContext 记忆 | [`bridge_memories.json`](bridge_memories.json) | 同一 Scope 3 条，内容为“玩家提问 + 老板回答” |
| 聊天界面截图 | [`ui/01_first_reply.png`](ui/01_first_reply.png) | 第 1 轮，末行 `【记忆命中：否】` |
| 新会话召回截图 | [`ui/02_new_session_recall.png`](ui/02_new_session_recall.png) | 新会话，末行 `【记忆命中：是】` |
| 工作流编排截图 | [`ui/03_workflow.png`](ui/03_workflow.png) | 5 个节点 |

## 5. 恢复初始状态

```bash
rm -rf dify/bridge/.data && python dify/bridge/app.py
```

Dify 侧新建对话即可。
