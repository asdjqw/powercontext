"""Order pricing rules for the sample SubLedger business project."""

from decimal import Decimal, ROUND_HALF_UP


def apply_discount(subtotal_cents: int, percent: int) -> int:
    """Return the amount due after applying a percentage discount.

    The function deliberately keeps the business project small: it is the
    before-state for the SDD validation scenario.
    """
    if subtotal_cents < 0:
        raise ValueError("subtotal_cents must be non-negative")
    if percent < 0:
        raise ValueError("percent must be non-negative")

    discount = int(
        (Decimal(subtotal_cents) * Decimal(percent) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return subtotal_cents - discount
