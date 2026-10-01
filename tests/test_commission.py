"""Checkpoints CP-15 to CP-19 — the commission and fees model (tech_spec §5).

Golden values are hand-computed from the worked example in tech_spec.md §10:

    net_item_value = Rp 12,240 / unit, units = 34
    commission 8%  = Rp   979.20
    admin fee      = Rp 1,250 / 34 = Rp 36.7647
    payment fee 2% = Rp   244.80
    ─────────────────────────────────────
    seller_received = Rp 10,979.2353 / unit
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from metrics import seller_received_per_unit, variable_rate  # noqa: E402

SHOPEE = dict(commission=0.080, admin_fee=1_250, payment=0.020, affiliate=0.00)
TIKTOK = dict(commission=0.065, admin_fee=1_000, payment=0.020, affiliate=0.05)

NET_ITEM_VALUE_PER_UNIT = 12_240.0
UNITS = 34


class TestCommission(unittest.TestCase):
    """CP-15 to CP-19."""

    # CP-15
    def test_shopee_seller_received_per_unit(self) -> None:
        received = seller_received_per_unit(
            NET_ITEM_VALUE_PER_UNIT, UNITS, **SHOPEE
        )
        self.assertAlmostEqual(received, 10_979.235294117647, places=9)

    # CP-16
    def test_variable_rate_is_sum_of_percentage_fees(self) -> None:
        self.assertAlmostEqual(variable_rate(**SHOPEE), 0.10, places=12)
        self.assertAlmostEqual(variable_rate(**TIKTOK), 0.135, places=12)

    # CP-17
    def test_admin_fee_does_not_scale_with_price(self) -> None:
        """A fixed fee is proportionally worse on cheaper orders."""
        cheap = seller_received_per_unit(2_000.0, 1, **SHOPEE)
        expensive = seller_received_per_unit(200_000.0, 1, **SHOPEE)

        cheap_effective_rate = 1 - cheap / 2_000.0
        expensive_effective_rate = 1 - expensive / 200_000.0
        self.assertGreater(cheap_effective_rate, expensive_effective_rate)

    # CP-18
    def test_tiktok_affiliate_reduces_receipt(self) -> None:
        """Same money, same commission, but TikTok's affiliate cut bites."""
        tiktok = seller_received_per_unit(NET_ITEM_VALUE_PER_UNIT, UNITS, **TIKTOK)
        no_affiliate = seller_received_per_unit(
            NET_ITEM_VALUE_PER_UNIT, UNITS, **{**TIKTOK, "affiliate": 0.0}
        )
        self.assertLess(tiktok, no_affiliate)

    # CP-19
    def test_zero_units_raises(self) -> None:
        with self.assertRaises(ValueError):
            seller_received_per_unit(NET_ITEM_VALUE_PER_UNIT, 0, **SHOPEE)


if __name__ == "__main__":
    unittest.main(verbosity=2)