# 提交说明：记忆酒馆（Dify × PowerContext）

## 一、提交信息

| 项 | 内容 |
| --- | --- |
| 仓库 | `https://github.com/asdjqw/powercontext-minimax` |
| 分支 | `2026-competition-ecosystem` |
| 提交 | 平台提交时填写分支当前的完整 `git rev-parse HEAD` |
| 目录 | `dify/` |
| 赛题 | Dify × OceanBase「Just for Fun」 |
| 技术方案 | **Dify + PowerContext**：Dify 编排对话，PowerContext 提供跨会话记忆（未使用 seekdb 运行时） |

## 二、建议的阅读顺序

1. **[`README.md`](README.md) 第 1 节**：记忆酒馆是什么、玩家怎么参与、应用入口在哪；
2. **[`README.md`](README.md) 第 5 节**：从零部署。推荐 Dify 0.15.3 导入 `app.dsl.yml`；
   1.x 环境导入无插件依赖的 `app-1.x.dsl.yml`；
3. **[`verify/00_environment.md`](verify/00_environment.md)**：本次真实运行的版本、配置、启动命令与踩坑记录；
4. **[`VALIDATION.md`](VALIDATION.md)**：验证样例——初始记忆状态、三轮输入、预期表现、实测结果、如何恢复初始状态；
5. **运行证据**：
   - 聊天与工作流截图：[`verify/ui/01_first_reply.png`](verify/ui/01_first_reply.png)、
     [`verify/ui/02_new_session_recall.png`](verify/ui/02_new_session_recall.png)、
     [`verify/ui/03_workflow.png`](verify/ui/03_workflow.png)；
   - 会话原始响应：[`verify/dify_session.json`](verify/dify_session.json)；
   - 节点级执行记录：[`verify/workflow_nodes.json`](verify/workflow_nodes.json)；
   - PowerContext 记忆记录：[`verify/bridge_memories.json`](verify/bridge_memories.json)；
6. **初始化与一键配置**：[`scripts/init_scope.py`](scripts/init_scope.py) 预置一条初始记忆；
   [`scripts/setup_0.15.3.py`](scripts/setup_0.15.3.py) 一键完成建管理员、配模型、导入 DSL、发布、创建 API Key。

## 三、Dify 与 PowerContext 的分工

- **Dify**：Chatflow 的 5 个节点承担全部流程——接收玩家输入、调用桥接读取记忆、调用模型生成 NPC 回应、
  调用桥接写入记忆、把回答返回给玩家；
- **PowerContext**：按 `sys.user_id` 建立 Scope，把每轮互动写成 Memory 并持久化；下一轮（包括**新会话**）
  读取同一 Scope 的记忆，拼进模型提示词。

换句话说：Dify 决定“这轮怎么回”，PowerContext 决定“这轮还记得什么”。把 PowerContext 拿掉，
第 2 轮开新会话时老板就不可能记得第 1 轮——这正是本作品要演示的体验。

## 四、这个作品自己的东西

- 玩法：雾里的酒馆、记性很好的老板、一枚来路不明的铜扣；玩家用一句话推动剧情，老板会提起你上次说过的话；
- 提示词、DSL、桥接代码、验证样例、截图均为本作品自行编写与实测，未复用其他参赛作品的代码或文本；
- 模型使用 MiniMax `MiniMax-M3.1-Flash`（OpenAI 兼容端点），也可替换为任意 OpenAI 兼容服务。

## 五、证据说明

- `verify/dify_session.json`：本次真实 Dify 0.15.3 服务的三轮会话原始响应（`conversation_id`、耗时、token 用量）；
- `verify/workflow_nodes.json`：三次会话对应的 3 次 workflow run、15 个节点执行结果，全部 `succeeded`；
- `verify/bridge_memories.json`：PowerContext 同一 Scope 下的 Memory 记录；
- 仓库内所有 Key、密码均为占位或本地配置，**未提交真实凭据**。
