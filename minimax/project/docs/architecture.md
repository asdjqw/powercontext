# SubLedger Architecture Note

The sample service has one pricing entry point:

- `subledger.pricing.apply_discount(subtotal_cents, percent)` — computes the
  amount due after a percentage discount.
- `test_regression_pricing.py` protects the existing pricing contract.
- `test_target_minimum_discount.py` describes the requested policy change.

The SDD context module indexes these files by path, kind, and symbol so a task
can retrieve the applicable policy, implementation, and tests before asking a
coding model for a patch.
