# PowerContext 状态保存与复用记录

## 接入方式

- 版本：PowerContext 1.2.0（`powercontext[server]`）
- 方式：进程内启动真实 PowerContext Server（SQLite 后端），使用 `PowerContextClient` 调用 HTTP API
- Scope：`MiniMax SDD context demo`
- Scope id（本次运行）：`scp_0mbvs75x9c2k5q270kz1s826vk`
- 幂等键：`minimax-sdd-context-v1`

## 保存

CLI 进程 A：

```bash
python -m sdd_context.cli state-save \
  --payload-file evidence/state_payload_final.json \
  --task-id minimax-sdd-001
```

写入内容摘要：

```json
{
  "task_id": "minimax-sdd-001",
  "phase": "validated",
  "completed": [
    "indexed specs, code, tests and docs in seekdb",
    "selected development context for the pricing task",
    "generated the implementation with MiniMax",
    "applied the generated implementation",
    "target and regression tests passed"
  ],
  "pending": [],
  "validation": {
    "target_tests": "pass",
    "regression_tests": "pass",
    "before_target": "fail:AssertionError",
    "after_target": "pass"
  }
}
```

Memory citation：

```json
{
  "memory_ref": {"family": "memory", "artifact_id": "memory", "revision": 1},
  "entry_id": "mem_ent_1ffd8b57cb4f4aae93d264b5105156d0"
}
```

## 重启后读取

CLI 进程 B（新进程、新 Server）：

```bash
python -m sdd_context.cli state-show --task-id minimax-sdd-001
```

返回：

```json
{
  "found": true,
  "state": {
    "phase": "validated",
    "task_id": "minimax-sdd-001",
    "validation": {
      "after_target": "pass",
      "before_target": "fail:AssertionError",
      "regression_tests": "pass",
      "target_tests": "pass"
    },
    "_powercontext_revision": 1
  }
}
```

日志：`cli_state-save.log`、`cli_state-show.log`。`acceptance_report.json` 中的 `PowerContext state saved` 和 `PowerContext state restored after restart` 两项均通过。

## 说明

- 状态不是从本地 JSON 读取的：两个 CLI 命令分别启动/停止 PowerContext Server，状态存放在 `.state/powercontext.db`，读取通过 `search_memory`。
- 验收脚本开始时删除 `.state/`，确保“从空状态开始保存”，随后由独立进程恢复。
- `.state/` 已在 `.gitignore` 中排除，不提交数据库文件。
