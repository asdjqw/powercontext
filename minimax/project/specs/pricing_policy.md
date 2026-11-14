# SubLedger Pricing Policy

## PRICE-001 — Minimum discountable order

An order with a subtotal below **10,000 cents** must not receive any discount.
The amount due is the subtotal unchanged.

## PRICE-002 — Maximum discount rate

A percentage discount is capped at **50%**. Any input above 50 is treated as 50
for the purpose of calculating the amount due.

## PRICE-003 — Rounding and input validation

Discounts are rounded **half up to the nearest cent**. Zero subtotal and zero
percent are valid. Negative subtotal or negative percent must raise
`ValueError`.

## PRICE-004 — Scope

This policy applies to the `subledger.pricing.apply_discount` function used by
the checkout service.
