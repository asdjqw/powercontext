"""Target behavior for the SDD change request.

These tests intentionally fail against the before-state in
project/snapshots/pricing_before.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subledger.pricing import apply_discount  # noqa: E402


def test_small_order_below_minimum_gets_no_discount():
    assert apply_discount(9_999, 10) == 9_999
    assert apply_discount(5_000, 10) == 5_000


def test_minimum_order_gets_discount():
    assert apply_discount(10_000, 10) == 9_000


def test_discount_percent_is_capped_at_fifty():
    assert apply_discount(20_000, 80) == 10_000
    assert apply_discount(20_000, 50) == 10_000
