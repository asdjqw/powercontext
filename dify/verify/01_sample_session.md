# 验证样例：一轮完整会话（含新会话召回）

本文件是 [`../VALIDATION.md`](../VALIDATION.md) 的运行记录版：按步骤执行时应看到什么、实际看到了什么。

## 0. 前置

- Dify **0.15.3** 已启动（`verify/00_environment.md`），应用由 `app.dsl.yml` 导入并发布；
- 桥接 8099 已启动，`/health` 返回 `{"ok": true}`；
- 记忆为空：删除 `dify/bridge/.data/` 后重启桥接；
- `user = tavern-guest-001`（Dify 终端用户 ID，映射为 `sys.user_id`）。

## 1. 第 1 轮：新会话，埋入“戴面具的人”

请求（Dify 聊天页输入，或 `POST /v1/chat-messages`）：

```json
{"inputs": {}, "query": "我推门走进酒馆，问老板昨晚那个戴面具的人是谁。",
 "response_mode": "blocking", "user": "tavern-guest-001"}
```

**预期**：老板给氛围与线索，不编造玩家没做过的选择。
**实测**（HTTP 200，167.7s）：

> “戴面具的人……我只能确认他昨晚来过，名字并未留下，连说话声都像笼在雾里。”
> “若你愿意，我可以陪你查查账本，或守在门边等他再出现。”

`conversation_id = f9fa1f92-9147-4d4c-a23c-42dee222c361`。

## 2. 第 2 轮：**新会话**，验证跨会话记忆

点“新对话”（`conversation_id` 置空），同一 `user`：

```json
{"query": "你还记得我昨晚问过什么吗？", "user": "tavern-guest-001"}
```

**预期**：复述第 1 轮的问题，且 `conversation_id` 与第 1 轮不同。
**实测**（HTTP 200，3.8s）：

> “记得——你昨晚问的是，昨晚那个戴面具的人是谁。”
> “至于他是谁，我还没能确认；旧账簿里或许藏着线索，你要我找找看吗？”

`conversation_id = 0c521aea-3516-43dd-bc70-fdc8d9f7c258`（与第 1 轮不同）。

这一步是本作品的关键证据：记忆来自 PowerContext（`/memory/load` 返回的旧记忆进入提示词），
而不是 Dify 自带的会话历史。

## 3. 第 3 轮：回到第 1 轮会话，延续上下文

```json
{"query": "那枚铜扣你放在哪了？", "conversation_id": "f9fa1f92-...", "user": "tavern-guest-001"}
```

**实测**（HTTP 200，5.3s）：

> “铜扣在柜台后的木匣里，和昨晚留下的物件搁在一处。”
> “匣子还没上锁——你要亲手打开看看吗？”

## 4. 对账

| 检查 | 命令/文件 | 结果 |
| --- | --- | --- |
| 三次 workflow run | `verify/workflow_nodes.json` | 3 runs / 15 nodes，全部 `succeeded` |
| 两个 HTTP 节点真实调用 | 同上，节点“读取/写入 PowerContext 记忆” | `http-request`，`succeeded` |
| PowerContext 写入 | `verify/bridge_memories.json` | 同一 Scope 3 条 Memory |
| 会话原始响应 | `verify/dify_session.json` | 三轮 HTTP 200 |
| 聊天界面截图 | `verify/ui/01_first_reply.png` | 第 1 轮回答 |
| 新会话召回截图 | `verify/ui/02_new_session_recall.png` | 新会话复述第 1 轮问题 |
| 工作流编排截图 | `verify/ui/03_workflow.png` | 5 个节点 |

## 5. 恢复初始状态

```bash
rm -rf dify/bridge/.data && python dify/bridge/app.py
```

Dify 侧新建对话即可；无需重置应用。
