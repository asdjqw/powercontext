# MiniMax × OceanBase：规有所依 — SDD 上下文模块

本目录是一个可运行的 **规格驱动开发（SDD）上下文模块** 示例。它把规格、实现代码和测试导入 **seekdb**，按开发任务检索出真实来源，交给 **MiniMax** 生成代码修改，用 **PowerContext** 保存/恢复任务状态，并通过同一组测试验证修改前后行为。

题目要求的六项必做内容全部有可复现证据：

| 必做项 | 实现 |
| --- | --- |
| 能够运行 | `scripts/start_seekdb.py` + `scripts/run_acceptance.py`，从空状态可完整重跑 |
| MiniMax 实际参与 | `evidence/minimax_requests.jsonl`、`evidence/minimax_last_response.json`、`evidence/minimax_patch.diff` |
| 上下文正确 | `sdd_context` 从 seekdb 检索规格/代码/测试；`evidence/context_initial.json` 和规格更新后的 `context_after_spec_update.json` |
| 数据库实际参与 | `sdd_documents` / `sdd_context_runs` 表；`evidence/seekdb_queries.jsonl` 记录实际 SQL 与返回行数 |
| 状态能够复用 | PowerContext Scope + Memory；`evidence/cli_state-save.log`、`evidence/cli_state-show.log`（两个独立进程） |
| 代码修改有效 | 修改前目标测试 `2 failed`，修改后 `3 passed`；回归测试前后均 `4 passed`；见 `evidence/tests_*.log` |

## 1. 运行环境

- Python 3.11+（本项目在 3.12 上验证）
- seekdb 1.4（本机使用 `seekdb.exe`；也可连接已有 seekdb/OceanBase MySQL 端点）
- PowerContext 1.2.0
- MiniMax OpenAI 兼容接口（`https://api.minimax.cn/v1`，模型 `MiniMax-M3.1-Flash`）

安装：

```bash
cd minimax
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env.local
# 在 .env.local 填写 MINIMAX_API_KEY
```

`.env.local` 不提交到仓库；`.env.example` 只保留占位值。

## 2. 初始化数据库

### 方式 A：启动本地 seekdb

```bash
python scripts/start_seekdb.py
```

脚本会查找 `SEEKDB_BIN`、`PATH` 中的 `seekdb`，或 `pylibseekdb` 包内自带的 seekdb 可执行文件，在 `.seekdb/` 下启动并等待 2881 端口可用。也可以手动启动：

```bash
seekdb --base-dir .seekdb --port 2881 --nodaemon \
  --parameter datafile_size=5G --parameter datafile_maxsize=10G \
  --parameter log_disk_size=2G
```

### 方式 B：连接已有 seekdb / OceanBase

```bash
export SEEKDB_DSN='mysql://user:password@host:2881/sdd_context'
```

数据库名会自动创建。连接参数见 `sdd_context/config.py`。

## 3. 一键验收

```bash
python scripts/run_acceptance.py
```

它会：

1. 创建/重置 `sdd_context` 数据库，导入 7 份工程资料；
2. 对任务检索上下文，校验规格、代码、测试来源真实存在；
3. 恢复修改前代码，运行目标测试（预期失败，且失败原因是 `AssertionError`，不是环境错误）和回归测试（预期通过）；
4. 应用 MiniMax 生成的实现，运行目标测试和回归测试（预期全部通过）；
5. 通过 CLI 的独立进程保存 PowerContext 状态，再启动另一个独立进程读取并比对；
6. 修改 `policy_amendment.md` 的最低金额并重新导入，确认上下文返回新值，而不是固定答案；
7. 写出 `evidence/acceptance_report.json`（本次运行 22 项检查全部通过）。

验收成功输出：

```json
{"passed": true, "checks": 22}
```

## 4. 上下文模块入口

模块入口为 CLI：

```bash
python -m sdd_context.cli --help
```

主要命令：

```bash
# 初始化/重置 seekdb
python -m sdd_context.cli db-init --reset

# 导入规格、代码、测试、文档
python -m sdd_context.cli import --reset

# 按任务检索开发上下文（输出 JSON，包含 specs/code/tests/docs 与真实来源）
python -m sdd_context.cli context \
  --task "Add a minimum order threshold of 10000 cents and cap the discount at 50 percent"

# 检索并渲染为可直接交给模型的文本
python -m sdd_context.cli context --task "..." --prompt

# 保存任务状态到 PowerContext
python -m sdd_context.cli state-save \
  --payload-file evidence/state_payload_final.json --task-id minimax-sdd-001

# 新进程读取状态
python -m sdd_context.cli state-show --task-id minimax-sdd-001

# 用 MiniMax 重新生成实现（需要 .env.local 中的 Key）
python -m sdd_context.cli minimax-generate --task "..."

# 单独跑修改前/后测试
python -m sdd_context.cli verify --phase before
python -m sdd_context.cli verify --phase after

# 恢复修改前代码、清空 PowerContext 状态、重建索引
python scripts/reset_demo.py
```

`context` 的输出字段：

- `specs`：适用的规格条目（路径、行号、来源 id、摘要）
- `code`：需要修改的代码文件/符号
- `tests`：功能测试与回归测试
- `docs`：架构说明
- `state`：可选的 PowerContext 任务状态

所有来源都带 `path`、`line`、`sha256`、`exists`，可在仓库中直接核对。

## 5. 验证样例

见 [`project/VALIDATION.md`](project/VALIDATION.md)。摘要：

- 业务工程：`project/src/subledger/pricing.py`
- 任务：订单小计低于 10,000 分不打折；折扣比例上限 50%；保持四舍五入、零值和负数校验
- 修改前：`test_target_minimum_discount.py` 2 个用例失败（AssertionError），回归测试通过
- 修改后：目标测试 3 个通过，回归测试 4 个通过
- 重置：`python scripts/reset_demo.py`

## 6. 三项技术的实际分工

- **seekdb**：`sdd_documents` 保存规格/代码/测试/文档和内容哈希；`sdd_context_runs` 记录每次上下文任务。检索使用真实 SQL（`LIKE` 关键词过滤 + 应用层排序），结果进入上下文；见 `evidence/seekdb_queries.jsonl`。
- **MiniMax**：`MiniMax-M3.1-Flash` 接收任务、检索到的上下文和当前文件，返回完整替换文件；实际响应、用量和生成的 diff 保存在 `evidence/`。开发记录见 `evidence/minimax_development.md`。
- **PowerContext**：每个 CLI 进程启动一个本地 PowerContext Server（SQLite 后端），在同一个 Scope 中写入 `progress` Memory；独立进程重新启动 Server 后通过 `search_memory` 读取同一任务状态。见 `evidence/powercontext_usage.md`。

## 7. 材料索引

| 材料 | 路径 |
| --- | --- |
| 上下文模块源码 | `sdd_context/` |
| 业务工程与测试 | `project/src/`、`project/tests/` |
| 规格与文档 | `project/specs/`、`project/docs/` |
| 修改前/后快照 | `project/snapshots/` |
| 代码差异 | `evidence/pricing_change.diff` |
| MiniMax 开发记录 | `evidence/minimax_development.md` |
| 数据库查询记录 | `evidence/seekdb_queries.jsonl`、`evidence/database_usage.md` |
| PowerContext 记录 | `evidence/powercontext_usage.md`、`evidence/cli_state-*.log` |
| 测试日志 | `evidence/tests_*.log` |
| 验收报告 | `evidence/acceptance_report.json` |
| 一页技术说明 | `TECHNICAL_NOTE.md` |

## 8. 已知限制

- PowerContext 官方将 Windows 标为 experimental；本机在 Python 3.12 + PowerContext 1.2.0 上已验证。Linux 评测机按同样命令运行即可。
- `scripts/run_acceptance.py` 使用已经记录的真实 MiniMax 响应快照来保证可重复；重新调用 MiniMax 使用 `minimax-generate`，需要有效 Key。
- seekdb 必须真实可用；没有数据库时验收会失败并给出启动说明，不会用 SQLite 冒充数据库。
- 本目录不包含任何密钥；`.env.local` 被 `.gitignore` 排除。
