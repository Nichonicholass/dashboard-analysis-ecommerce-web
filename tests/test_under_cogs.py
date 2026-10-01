"""Checkpoints CP-20 to CP-28 — Logic 2: under COGS (tech_spec §7).

Golden values are hand-computed from the worked example in tech_spec.md §10:

    cogs_per_unit    = Rp 12,050
    received/unit    = Rp 10,979.2353
    under_cogs/unit  = Rp  1,070.7647       -> 8.9 % of cost -> AT_RISK
    total (34 units) = Rp 36,406.0
    target_price     = Rp 15,438
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from metrics import (  # noqa: E402
    Severity,
    classify_severity,
    gross_exposure,
    net_position,
    target_price,
    under_cogs_per_unit,
    under_cogs_total,
)

SHOPEE = dict(commission=0.080, admin_fee=1_250, payment=0.020, affiliate=0.00)

NET_ITEM_VALUE_PER_UNIT = 12_240.0
UNITS = 34
COST_PER_UNIT = 12_050.0
TARGET_MARGIN = 0.15

# Rp 12,050 − Rp 10,979.2353
EXPECTED_PER_UNIT = 1_070.764705882353
EXPECTED_TOTAL = EXPECTED_PER_UNIT * UNITS


class TestUnderCogs(unittest.TestCase):
    """CP-20 to CP-26."""

    # CP-20
    def test_worked_example_per_unit(self) -> None:
        result = under_cogs_per_unit(
            cost_per_unit=COST_PER_UNIT,
            net_item_value_per_unit=NET_ITEM_VALUE_PER_UNIT,
            units=UNITS,
            **SHOPEE,
        )
        self.assertAlmostEqual(result, EXPECTED_PER_UNIT, places=6)

    # CP-21
    def test_worked_example_total(self) -> None:
        result = under_cogs_total(
            cost_per_unit=COST_PER_UNIT,
            net_item_value_per_unit=NET_ITEM_VALUE_PER_UNIT,
            units=UNITS,
            **SHOPEE,
        )
        self.assertAlmostEqual(result, EXPECTED_TOTAL, places=6)

    # CP-22
    def test_severity_at_risk(self) -> None:
        # 8.9 % of cost — below the 10 % critical line.
        self.assertIs(
            classify_severity(under_cogs_per_unit=1_070.7647, cost_per_unit=12_050.0),
            Severity.AT_RISK,
        )

    # CP-23
    def test_severity_critical(self) -> None:
        # 20 % of cost — well past the critical line.
        self.assertIs(
            classify_severity(under_cogs_per_unit=2_410.0, cost_per_unit=12_050.0),
            Severity.CRITICAL,
        )

    # CP-24
    def test_severity_watch(self) -> None:
        """Thin but profitable: margin between -5 % and 0 %."""
        # Cost 100, revenue 98 → margin -2 %, i.e. not yet losing money.
        self.assertIs(
            classify_severity(under_cogs_per_unit=-2.0, cost_per_unit=100.0),
            Severity.WATCH,
        )

    # CP-25
    def test_target_price_worked_example(self) -> None:
        price = target_price(
            cost_per_unit=COST_PER_UNIT,
            target_margin=TARGET_MARGIN,
            units=UNITS,
            **SHOPEE,
        )
        # (12,050 x 1.15 + 1,250/34) / (1 - 0.08 - 0.02)
        # = (13,857.5 + 36.76470588235294) / 0.90
        self.assertAlmostEqual(price, 15_438.071895424835, places=6)

    # CP-26
    def test_target_price_above_cost(self) -> None:
        """Property: the corrected price must actually clear cost."""
        for cost in (500.0, 3_000.0, 12_050.0, 150_000.0):
            with self.subTest(cost=cost):
                price = target_price(
                    cost_per_unit=cost, target_margin=0.15, units=10, **SHOPEE
                )
                self.assertGreater(price, cost)


class TestUnderCogsAggregation(unittest.TestCase):
    """CP-27 to CP-28 — the gross vs net decision from §7.4."""

    LOSS = 36_406.0
    PROFIT = -50_000.0  # negative under_cogs means profitable

    # CP-27
    def test_gross_exposure_ignores_profits(self) -> None:
        self.assertEqual(gross_exposure([self.LOSS, self.PROFIT]), self.LOSS)

    # CP-28
    def test_net_position_offsets(self) -> None:
        self.assertEqual(net_position([self.LOSS, self.PROFIT]), self.LOSS + self.PROFIT)
        self.assertNotEqual(
            net_position([self.LOSS, self.PROFIT]),
            gross_exposure([self.LOSS, self.PROFIT]),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)