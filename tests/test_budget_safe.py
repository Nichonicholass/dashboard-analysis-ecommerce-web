"""Checkpoints CP-29 to CP-35 — Logic 3: budget safe (tech_spec §8).

Golden values are hand-computed from the worked example in tech_spec.md §10:

    campaign_budget  = Rp 50,000,000
    total_under_cogs = Rp 18,400,000   (gross exposure)
    budget_safe      = Rp 31,600,000
    remaining        = 63.2%           -> HEALTHY

Reminder from §8.3: this is a *reserve*, not money spent. The tests below pin the
arithmetic and the band boundaries, not the interpretation.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from metrics import BudgetStatus, budget_safe, budget_status  # noqa: E402

CAMPAIGN_BUDGET = 50_000_000.0
TOTAL_UNDER_COGS = 18_400_000.0
EXPECTED_SAFE = 31_600_000.0


class TestBudgetSafe(unittest.TestCase):
    """CP-29 to CP-35."""

    # CP-29
    def test_worked_example(self) -> None:
        self.assertEqual(budget_safe(CAMPAIGN_BUDGET, TOTAL_UNDER_COGS), EXPECTED_SAFE)

    # CP-30
    def test_remaining_pct(self) -> None:
        safe = budget_safe(CAMPAIGN_BUDGET, TOTAL_UNDER_COGS)
        self.assertAlmostEqual(safe / CAMPAIGN_BUDGET, 0.632, places=6)

    # CP-31
    def test_status_healthy(self) -> None:
        # 63.2 % remaining — comfortably above half.
        self.assertIs(
            budget_status(CAMPAIGN_BUDGET, TOTAL_UNDER_COGS), BudgetStatus.HEALTHY
        )

    # CP-32
    def test_status_caution(self) -> None:
        # 25 % remaining — over half consumed, but not breached.
        self.assertIs(
            budget_status(CAMPAIGN_BUDGET, 37_500_000.0), BudgetStatus.CAUTION
        )

    # CP-33
    def test_status_breached(self) -> None:
        # Exposure equals the whole budget.
        self.assertIs(
            budget_status(CAMPAIGN_BUDGET, CAMPAIGN_BUDGET), BudgetStatus.BREACHED
        )

    # CP-34
    def test_boundary_exactly_half_is_caution(self) -> None:
        """HEALTHY is strictly more than half, so the boundary is CAUTION."""
        self.assertIs(
            budget_status(CAMPAIGN_BUDGET, CAMPAIGN_BUDGET / 2), BudgetStatus.CAUTION
        )

    # CP-35
    def test_zero_budget_raises(self) -> None:
        with self.assertRaises(ValueError):
            budget_safe(0.0, 1_000.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)