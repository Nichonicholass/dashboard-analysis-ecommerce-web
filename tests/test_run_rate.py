"""Checkpoints CP-01 to CP-14 — Logic 1: run rate, stock-out projection, reallocation.

Golden values are hand-computed from the worked example in tech_spec.md §10:

    SKU-0007 / Shopee : allocated = 12, units_net(7d) = 9
    run_rate_per_hour  = 9 / 168 = 0.0535714
    hours_to_stockout  = 12 / 0.0535714 = 224 hours

The real functions live in `src/metrics.py`. Until that module exists these tests
must fail on import — that is the point of writing them first.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from metrics import (  # noqa: E402  (fails loudly until implemented)
    StockoutStatus,
    classify_stockout,
    hours_to_stockout,
    recommend_reallocation,
    run_rate_per_hour,
)

# Worked-example constants, kept in one place so the tests read as arithmetic.
SHOPEE_ALLOCATED = 12
SHOPEE_UNITS_7D = 9
TIKTOK_ALLOCATED = 130
TIKTOK_UNITS_7D = 2
SEVEN_DAYS = 168
TARGET_COVER_HOURS = 336


class TestRunRate(unittest.TestCase):
    """CP-01 to CP-06 — the run rate itself and its guardrails."""

    # CP-01
    def test_exact_rate_shopee_worked_example(self) -> None:
        rate = run_rate_per_hour(SHOPEE_UNITS_7D, SEVEN_DAYS)
        self.assertAlmostEqual(rate, 0.05357142857142857, places=12)

    # CP-02
    def test_exact_rate_tiktok_worked_example(self) -> None:
        rate = run_rate_per_hour(TIKTOK_UNITS_7D, SEVEN_DAYS)
        self.assertAlmostEqual(rate, 0.011904761904761904, places=12)

    # CP-03
    def test_hours_to_stockout_shopee(self) -> None:
        rate = run_rate_per_hour(SHOPEE_UNITS_7D, SEVEN_DAYS)
        hours = hours_to_stockout(SHOPEE_ALLOCATED, rate)
        self.assertAlmostEqual(hours, 224.0, places=9)

    # CP-04
    def test_hours_to_stockout_tiktok(self) -> None:
        rate = run_rate_per_hour(TIKTOK_UNITS_7D, SEVEN_DAYS)
        hours = hours_to_stockout(TIKTOK_ALLOCATED, rate)
        self.assertAlmostEqual(hours, 10920.0, places=9)

    # CP-05
    def test_zero_observation_hours_raises(self) -> None:
        with self.assertRaises(ValueError):
            run_rate_per_hour(5, 0)

    # CP-06
    def test_zero_rate_returns_none_not_error(self) -> None:
        self.assertIsNone(hours_to_stockout(50, 0.0))


class TestStockoutStatus(unittest.TestCase):
    """CP-07 to CP-10 — the four-way alert classification."""

    # CP-07
    def test_zero_allocated_is_out_of_stock(self) -> None:
        status = classify_stockout(allocated_units=0, rate=0.05, horizon_hours=1)
        self.assertIs(status, StockoutStatus.OUT_OF_STOCK)

    # CP-08
    def test_at_risk_within_horizon(self) -> None:
        # 3 units at 1.0/hour clears in 3 hours; horizon 24 → at risk.
        status = classify_stockout(allocated_units=3, rate=1.0, horizon_hours=24)
        self.assertIs(status, StockoutStatus.AT_RISK)

    # CP-09
    def test_healthy_beyond_horizon(self) -> None:
        # 100 units at 1.0/hour clears in 100 hours; horizon 24 → healthy.
        status = classify_stockout(allocated_units=100, rate=1.0, horizon_hours=24)
        self.assertIs(status, StockoutStatus.HEALTHY)

    # CP-10
    def test_dormant_when_no_sales(self) -> None:
        status = classify_stockout(allocated_units=500, rate=0.0, horizon_hours=168)
        self.assertIs(status, StockoutStatus.DORMANT)


class TestReallocation(unittest.TestCase):
    """CP-11 to CP-14 — moving units between marketplaces."""

    def _worked_example_move(self) -> int:
        return recommend_reallocation(
            needed_units=6,
            donor_allocated=TIKTOK_ALLOCATED,
            donor_rate=run_rate_per_hour(TIKTOK_UNITS_7D, SEVEN_DAYS),
            target_cover_hours=TARGET_COVER_HOURS,
        )

    # CP-11
    def test_worked_example_move(self) -> None:
        self.assertEqual(self._worked_example_move(), 6)

    # CP-12
    def test_never_exceeds_donor_surplus(self) -> None:
        # Ask for far more than the donor can spare; must be capped.
        donor_rate = run_rate_per_hour(TIKTOK_UNITS_7D, SEVEN_DAYS)
        donor_surplus = TIKTOK_ALLOCATED - TARGET_COVER_HOURS * donor_rate

        move = recommend_reallocation(
            needed_units=10_000,
            donor_allocated=TIKTOK_ALLOCATED,
            donor_rate=donor_rate,
            target_cover_hours=TARGET_COVER_HOURS,
        )
        self.assertIsNotNone(move)
        self.assertLessEqual(move, donor_surplus)

    # CP-13
    def test_none_when_no_donor_surplus(self) -> None:
        # Donor is already below target cover, so it has nothing to give.
        move = recommend_reallocation(
            needed_units=10,
            donor_allocated=5,
            donor_rate=1.0,                  # 5 units at 1/hour = 5h cover
            target_cover_hours=TARGET_COVER_HOURS,
        )
        self.assertIsNone(move)

    # CP-14
    def test_total_allocation_unchanged(self) -> None:
        """A migration is a transfer, so the pool total is conserved."""
        move = self._worked_example_move()
        before = SHOPEE_ALLOCATED + TIKTOK_ALLOCATED
        after = (SHOPEE_ALLOCATED + move) + (TIKTOK_ALLOCATED - move)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)