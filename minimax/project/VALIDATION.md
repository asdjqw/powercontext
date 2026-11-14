# 验证样例：SubLedger 最低折扣订单与折扣上限

## 任务

修改业务工程 `project/src/subledger/pricing.py` 的 `apply_discount(subtotal_cents, percent)`：

1. 小计低于 **10,000 分** 时不打折，返回小计原值；
2. 小计达到 10,000 分时保留原有百分比折扣；
3. 折扣百分比最高为 **50%**；
4. 保留原有半进位（half-up）舍入、零值处理和负数输入的 `ValueError`。

## 有效规格

| 规格 | 来源 | 要求 |
| --- | --- | --- |
| PRICE-001 | `project/specs/pricing_policy.md` | 小计低于 10,000 分不打折 |
| PRICE-002 | `project/specs/pricing_policy.md` | 折扣比例上限 50% |
| PRICE-003 | `project/specs/pricing_policy.md` | half-up 舍入；零值有效；负数 `ValueError` |
| PRICE-AMS-001 | `project/specs/policy_amendment.md` | 当前发布的最低折扣订单金额 |
| 变更请求 | `project/specs/change_request.md` | 本任务的验收范围 |

## 必须保持的原有行为

- `apply_discount(20_000, 10) == 18_000`
- `apply_discount(12_345, 15) == 10_493`（1,851.75 分半进位为 1,852）
- `apply_discount(20_000, 0) == 20_000`，`apply_discount(0, 25) == 0`
- 负数小计或负数比例抛出 `ValueError`

## 初始数据

`project/snapshots/pricing_before.py` 是修改前实现；`project/src/subledger/pricing.py` 应被重置为该文件。

## 操作步骤

```bash
cd minimax

# 1. 初始化数据库并导入资料
python -m sdd_context.cli db-init --reset
python -m sdd_context.cli import --reset

# 2. 检索任务上下文
python -m sdd_context.cli context \
  --task "Add a minimum order threshold of 10000 cents, cap the discount at 50 percent, and preserve existing rounding and validation behavior"

# 3. 恢复修改前代码并运行测试
python scripts/reset_demo.py
python -m pytest -q project/tests/test_target_minimum_discount.py   # 预期失败
python -m pytest -q project/tests/test_regression_pricing.py        # 预期通过

# 4. 应用 MiniMax 生成的修改（已记录在 project/snapshots/pricing_after.py）
python - <<'PY'
import shutil
shutil.copyfile("project/snapshots/pricing_after.py", "project/src/subledger/pricing.py")
PY
python -m pytest -q project/tests/test_target_minimum_discount.py   # 预期 3 passed
python -m pytest -q project/tests/test_regression_pricing.py        # 预期 4 passed

# 5. 保存状态并用新进程读取
python -m sdd_context.cli state-save \
  --payload-file evidence/state_payload_final.json --task-id minimax-sdd-001
python -m sdd_context.cli state-show --task-id minimax-sdd-001
```

## 预期结果

修改前目标测试：

```text
2 failed, 1 passed
```

失败原因必须是 `AssertionError`（不是缺少依赖、导入错误等环境问题）。

修改后：

```text
project/tests/test_target_minimum_discount.py: 3 passed
project/tests/test_regression_pricing.py:      4 passed
```

PowerContext：

```json
{"found": true, "state": {"phase": "validated", "validation": {"target_tests": "pass", "regression_tests": "pass"}}}
```

规格更新验证：把 `project/specs/policy_amendment.md` 中的 `10,000 cents` 改为 `12,000 cents`，重新执行 `import` 和 `context`，输出应包含 `12,000 cents`；验收脚本随后会恢复原文。

## 重置方法

```bash
python scripts/reset_demo.py
rm -rf .state          # Windows: rmdir /s /q .state
python -m sdd_context.cli db-init --reset
python -m sdd_context.cli import --reset
```

`scripts/run_acceptance.py` 会自动完成上述重置和全部验证。
