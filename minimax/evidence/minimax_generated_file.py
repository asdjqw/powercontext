"""Order pricing rules for the sample SubLedger business project."""

from decimal import Decimal, ROUND_HALF_UP


def apply_discount(subtotal_cents: int, percent: int) -> int:
    """Return the amount due after applying a percentage discount.

    Orders below 10,000 cents receive no discount, and the discount
    percentage is capped at 50 percent.
    """
    if subtotal_cents < 0:
        raise ValueError("subtotal_cents must be non-negative")
    if percent < 0:
        raise ValueError("percent must be non-negative")

    if subtotal_cents < 10_000:
        return subtotal_cents

    effective_percent = min(percent, 50)
    discount = int(
        (
            Decimal(subtotal_cents)
            * Decimal(effective_percent)
            / Decimal(100)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    return subtotal_cents - discount
