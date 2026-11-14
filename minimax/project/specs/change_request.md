# Change Request: minimum order threshold and discount cap

Implement the pricing policy update in `subledger.pricing.apply_discount`:

1. Orders with a subtotal below 10,000 cents receive no discount.
2. Orders at or above 10,000 cents keep the existing percentage behavior.
3. The discount percentage is capped at 50.
4. Existing rounding, zero-value, and validation behavior must not regress.

Acceptance evidence:

- `test_target_minimum_discount.py` must pass after the change.
- `test_regression_pricing.py` must continue to pass.
- The implementation must remain in `project/src/subledger/pricing.py`.
