# 一页技术说明

## 模块结构

```text
sdd_context/
  config.py     配置、路径、.env.local、DSN 解析
  db.py         seekdb 连接、sdd_documents/sdd_context_runs、SQL 查询与日志
  ingest.py     扫描 specs/code/tests/docs，按内容哈希增量导入
  retrieval.py  任务分词、SQL 候选召回、排序、来源定位、上下文渲染
  state.py      PowerContext Server + Client，Memory 保存/读取任务状态
  minimax_client.py  MiniMax OpenAI 兼容调用与开发记录
  cli.py        db-init/import/context/state-save/state-show/minimax-generate/verify/reset

project/
  specs/        政策规格与变更请求
  src/          SubLedger 业务代码
  tests/        目标测试与回归测试
  snapshots/    修改前/后快照
  VALIDATION.md 验证样例
```

## 上下文选择方式

1. 对任务做小写分词并扩展同义词（minimum→threshold/small，discount→percent/cap 等）。
2. 在 seekdb 的 `sdd_documents` 上执行关键词 SQL（`title/symbol/content LIKE`），只取 spec/code/test/doc 候选；SQL 与返回行数写入 `evidence/seekdb_queries.jsonl`。
3. 在应用层按标题、符号、正文词频、路径和 kind 权重排序，分别取 specs≤3、code≤2、tests≤2、docs≤1。
4. 每个来源输出数据库 id、仓库相对路径、行号、符号、SHA-256 和 `exists`，保证来源真实存在。
5. 规格文件更新后重新 `import` 会更新同一 path 的 content 与哈希，下一次 context 自动使用新内容，不做缓存或固定答案。

## 三项技术的分工

| 技术 | 实际作用 | 证据 |
| --- | --- | --- |
| seekdb | 保存 7 份工程资料与内容哈希；每次任务执行真实 SQL 取候选；记录 `sdd_context_runs` | `evidence/seekdb_queries.jsonl`、`evidence/database_usage.md` |
| MiniMax | 输入任务 + seekdb 检索出的规格/代码/测试 + 当前文件，输出完整 `pricing.py` 替换；`MiniMax-M3.1-Flash`，prompt 1342 tokens / completion 352 tokens | `evidence/minimax_requests.jsonl`、`evidence/minimax_prompt.txt`、`evidence/pricing_change.diff` |
| PowerContext | 启动本地 Server（SQLite），在同一 Scope 写入 `progress` Memory；独立 CLI 进程重启 Server 后 `search_memory` 读取状态 | `evidence/powercontext_usage.md`、`evidence/cli_state-*.log` |

## 验证结果

- 修改前：目标测试 2 failed（AssertionError），回归 4 passed
- 修改后：目标测试 3 passed，回归 4 passed
- PowerContext：状态保存后由独立进程恢复，`phase=validated`
- 规格更新：`10,000`→`12,000` 后重新导入，context 返回 12,000
- `scripts/run_acceptance.py`：22 项检查全部通过

## 限制

- 需要可用的 seekdb/ OceanBase；没有数据库时直接失败，不伪造数据库参与。
- MiniMax 需 `.env.local` 中的真实 Key；验收使用已记录的真实响应快照保证可重复。
- PowerContext 在 Windows 为 experimental，本机已在 Python 3.12 + PowerContext 1.2.0 验证。
