"""Compatibility tests that must keep passing before and after the change."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subledger.pricing import apply_discount  # noqa: E402


def test_regular_discount_is_unchanged():
    assert apply_discount(20_000, 10) == 18_000


def test_rounding_is_half_up_to_the_cent():
    # 12_345 * 15% = 1_851.75 -> 1_852 cents discount.
    assert apply_discount(12_345, 15) == 10_493


def test_zero_percent_and_zero_subtotal():
    assert apply_discount(20_000, 0) == 20_000
    assert apply_discount(0, 25) == 0


def test_negative_inputs_raise_value_error():
    import pytest

    with pytest.raises(ValueError):
        apply_discount(-1, 10)
    with pytest.raises(ValueError):
        apply_discount(100, -1)
