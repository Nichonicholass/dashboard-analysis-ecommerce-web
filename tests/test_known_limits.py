"""Checkpoints CP-36 to CP-38 — known limitations, pinned as tests.

These are unusual checkpoints. They do **not** assert that the system does something
desirable. They assert that a measured limitation of the *data* is still true, so
that nobody later "fixes" the threshold and quietly loses the finding.

Background (tech_spec.md §6.4): a 1-hour alert horizon was specified. Measured
against the generated fixture, the fastest SKU/channel moves 0.0139 units per hour.
An AT_RISK alert requires `allocated_units <= run_rate x horizon_hours`, so at a
1-hour horizon that means `allocated <= 0.0139` — i.e. it can only fire once stock is
already gone.

If the fixture is ever rebuilt with ~100x more volume, CP-36 and CP-38 should be
**updated, not deleted**, because the limitation will genuinely have changed.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from metrics import StockoutStatus, classify_stockout  # noqa: E402

# Measured from the generated fixture — see tech_spec.md §6.4.
FIXTURE_FASTEST_RATE_PER_HOUR = 0.0139
FIXTURE_MEDIAN_RATE_PER_HOUR = 0.00417

# The threshold called out as insufficient for hourly alerting.
HOURLY_HORIZON = 1
WEEKLY_HORIZON = 168


class TestKnownLimits(unittest.TestCase):
    """CP-36 to CP-38."""

    # CP-36
    def test_one_hour_horizon_cannot_predict_at_fixture_rate(self) -> None:
        """One allocated unit is still ~72 hours of cover at fixture speed."""
        status = classify_stockout(
            allocated_units=1,
            rate=FIXTURE_FASTEST_RATE_PER_HOUR,
            horizon_hours=HOURLY_HORIZON,
        )
        self.assertIs(
            status,
            StockoutStatus.HEALTHY,
            "If this now returns AT_RISK, the fixture gained volume. "
            "Update tech_spec §6.4 and this checkpoint together.",
        )

    # CP-37
    def test_168h_horizon_does_predict_at_fixture_rate(self) -> None:
        """Same maths, only the threshold moved — this is the recommended default."""
        status = classify_stockout(
            allocated_units=1,
            rate=FIXTURE_FASTEST_RATE_PER_HOUR,
            horizon_hours=WEEKLY_HORIZON,
        )
        self.assertIs(status, StockoutStatus.AT_RISK)

    # CP-38
    def test_fixture_fastest_rate_is_below_hourly_velocity(self) -> None:
        """Pins the measurement itself, so the fixture's sparsity is on record."""
        self.assertLess(FIXTURE_FASTEST_RATE_PER_HOUR, 0.1)
        self.assertLess(FIXTURE_MEDIAN_RATE_PER_HOUR, FIXTURE_FASTEST_RATE_PER_HOUR)

        # An hourly horizon needs at least 1 unit/hour to be able to trigger at all
        # on a single unit of stock.
        self.assertLess(FIXTURE_FASTEST_RATE_PER_HOUR, 1.0)

    # CP-39
    def test_default_horizon_is_one_hour_per_spec(self) -> None:
        """Pin the default horizon itself.

        Found by mutation testing: changing the default from 1.0 to 168.0 broke
        nothing, because every other checkpoint passes the horizon explicitly. That
        default is precisely the value that silently bypasses §6.4 — with a 168-hour
        default, the specified 1-hour behaviour is never exercised and CP-36 stops
        describing the shipped system.

        If the team decides to adopt 168 hours as the default (the recommendation in
        §6.4, needing an explicit decision), this checkpoint and tech_spec §9's
        ALERT_HORIZON_HOURS must change together.
        """
        import inspect

        signature = inspect.signature(classify_stockout)
        default = signature.parameters["horizon_hours"].default
        self.assertEqual(
            default,
            1.0,
            "The default alert horizon no longer matches tech_spec §9 "
            "(ALERT_HORIZON_HOURS = 1). Update the spec and this checkpoint together.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)