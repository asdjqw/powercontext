# MiniMax 开发记录

## 任务

> Add a minimum order threshold of 10000 cents, cap the discount at 50 percent, and preserve existing rounding and validation behavior

## 实际调用

- 时间：2026-11-14T09:22:00Z
- 服务：`https://api.minimax.cn/v1/chat/completions`
- 模型：`MiniMax-M3.1-Flash`
- 请求 id：`07475b3961e7b67ad32d2836c1fc0f27`
- 用量：prompt 1342 tokens，completion 352 tokens，total 1694 tokens
- 原始请求/响应元数据：`minimax_requests.jsonl`
- 实际提示词：`minimax_prompt.txt`
- 模型返回的完整文件：`minimax_generated_file.py`
- 模型 summary：Added the 10,000-cent minimum discountable order threshold and capped the effective discount percentage at 50%, while preserving negative-input validation, zero handling, and half-up rounding.

## 提供给 MiniMax 的上下文

`sdd_context` 从 seekdb 检索出以下真实来源，并渲染进提示词：

| 类型 | 来源 |
| --- | --- |
| spec | `project/specs/change_request.md` |
| spec | `project/specs/pricing_policy.md`（PRICE-001/002/003） |
| spec | `project/specs/policy_amendment.md`（PRICE-AMS-001） |
| code | `project/src/subledger/pricing.py`（`apply_discount`） |
| test | `project/tests/test_target_minimum_discount.py` |
| test | `project/tests/test_regression_pricing.py` |
| doc | `project/docs/architecture.md` |

完整提示词见 `minimax_prompt.txt`；检索结果见 `context_initial.json`。

## 模型输出与代码差异

模型返回一个 JSON，`content` 为完整替换文件。应用后得到的差异：

```diff
--- a/project/src/subledger/pricing.py
+++ b/project/src/subledger/pricing.py
@@ -6,17 +6,23 @@
 def apply_discount(subtotal_cents: int, percent: int) -> int:
     """Return the amount due after applying a percentage discount.
 
-    The function deliberately keeps the business project small: it is the
-    before-state for the SDD validation scenario.
+    Orders below 10,000 cents receive no discount, and the discount
+    percentage is capped at 50 percent.
     """
     if subtotal_cents < 0:
         raise ValueError("subtotal_cents must be non-negative")
     if percent < 0:
         raise ValueError("percent must be non-negative")
 
+    if subtotal_cents < 10_000:
+        return subtotal_cents
+
+    effective_percent = min(percent, 50)
     discount = int(
-        (Decimal(subtotal_cents) * Decimal(percent) / Decimal(100)).quantize(
-            Decimal("1"), rounding=ROUND_HALF_UP
-        )
+        (
+            Decimal(subtotal_cents)
+            * Decimal(effective_percent)
+            / Decimal(100)
+        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
     )
     return subtotal_cents - discount

```

完整 diff 文件：`pricing_change.diff`。修改前/后完整快照：`../project/snapshots/pricing_before.py`、`pricing_after.py`。

## 验证

- 修改前目标测试：`2 failed, 1 passed`，失败原因是 `AssertionError`（见 `tests_before_target.log`）
- 修改前回归：`4 passed`（见 `tests_before_regression.log`）
- 修改后目标：`3 passed`（见 `tests_after_target.log`）
- 修改后回归：`4 passed`（见 `tests_after_regression.log`）

## 复现

```bash
cd minimax
python -m sdd_context.cli minimax-generate \
  --task "Add a minimum order threshold of 10000 cents, cap the discount at 50 percent, and preserve existing rounding and validation behavior"
```

该命令会重新调用 MiniMax、写入 `minimax_requests.jsonl`、生成 `pricing_change.diff` 并覆盖 `project/src/subledger/pricing.py`。需要 `.env.local` 中有效的 `MINIMAX_API_KEY`。

> 未保存模型私有思维链；`minimax_requests.jsonl` 中的 `reasoning_content` 已移除。
