"""Core metrics from tech_spec.md — run rate, under COGS, budget safe.

Pure functions only: no file I/O, no globals, no randomness. Every function takes its
inputs explicitly so the checkpoint suite can pin exact values.

Implemented to satisfy `checkpoint.json`. Bands and formulas follow tech_spec.md:

    §5   commission & fees        -> seller_received_per_unit, variable_rate
    §6   run rate & stock-out     -> run_rate_per_hour, hours_to_stockout,
                                     classify_stockout, recommend_reallocation
    §7   under COGS               -> under_cogs_per_unit, under_cogs_total,
                                     classify_severity, target_price,
                                     gross_exposure, net_position
    §8   budget safe              -> budget_safe, budget_status
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable, Optional

# --------------------------------------------------------------------------- #
# §6 — Run rate and stock-out projection
# --------------------------------------------------------------------------- #
class StockoutStatus(str, Enum):
    """Four-way classification from tech_spec §6.3."""
    DORMANT = "DORMANT"              # no sales — never alert, never divide by zero
    OUT_OF_STOCK = "OUT_OF_STOCK"    # allocation already zero
    AT_RISK = "AT_RISK"              # runs dry within the horizon
    HEALTHY = "HEALTHY"              # cover exceeds the horizon


def run_rate_per_hour(units_net: int, observation_hours: float) -> float:
    """Units per hour over the observation window (tech_spec §6.1).

    Raises ValueError on a zero-length window rather than dividing by zero — a
    zero-hour window is a caller bug, not a valid measurement.
    """
    if observation_hours <= 0:
        raise ValueError("observation_hours must be positive")
    return units_net / observation_hours


def hours_to_stockout(
    allocated_units: int,
    rate_per_hour: float,
) -> Optional[float]:
    """Hours of cover remaining (tech_spec §6.2).

    Returns None when the rate is zero, because a dormant SKU has no meaningful
    time-to-empty. Returning infinity would push the problem downstream into the
    UI; returning None forces the caller to handle the dormant case explicitly.
    """
    if rate_per_hour <= 0:
        return None
    return allocated_units / rate_per_hour


def classify_stockout(
    allocated_units: int,
    rate_per_hour: float = 0.0,
    horizon_hours: float = 1.0,
    *,
    rate: Optional[float] = None,
) -> StockoutStatus:
    """Classify a SKU/channel against the alert horizon (tech_spec §6.3).

    `rate` is accepted as an alias for `rate_per_hour` so callers can use the shorter
    name from tech_spec §6.3's pseudocode.

    Order matters: dormant is checked before out-of-stock, because a SKU with no
    sales and no allocation is a listing problem, not a demand problem.
    """
    effective_rate = rate_per_hour if rate is None else rate

    if effective_rate <= 0:
        return StockoutStatus.DORMANT
    if allocated_units <= 0:
        return StockoutStatus.OUT_OF_STOCK

    cover = hours_to_stockout(allocated_units, effective_rate)
    if cover is not None and cover <= horizon_hours:
        return StockoutStatus.AT_RISK
    return StockoutStatus.HEALTHY


def donor_surplus(allocated_units: int, rate_per_hour: float, target_cover_hours: float) -> float:
    """Units a channel can give away and still hold its target cover (§6.5)."""
    required = target_cover_hours * rate_per_hour
    return allocated_units - required


def recommend_reallocation(
    needed_units: float,
    donor_allocated: int,
    donor_rate: float,
    target_cover_hours: float,
) -> Optional[int]:
    """How many units to move from a donor channel (tech_spec §6.5).

    Returns None when the donor has no surplus, so the UI renders
    "no donor available" instead of a meaningless zero.

    The move is capped by the donor's surplus: the donor must remain above its own
    target cover. It is never capped by stock on hand here — that check belongs to
    the caller, which is the only place that knows the whole allocation picture.
    """
    surplus = donor_surplus(donor_allocated, donor_rate, target_cover_hours)
    if surplus <= 0:
        return None

    move = min(needed_units, surplus)
    if move <= 0:
        return None
    return int(move)


# --------------------------------------------------------------------------- #
# §5 — Commission and fees
# --------------------------------------------------------------------------- #
def variable_rate(
    commission: float,
    admin_fee: float = 0.0,
    payment: float = 0.0,
    affiliate: float = 0.0,
) -> float:
    """Sum of the percentage-based fees (tech_spec §5.1).

    `admin_fee` is accepted for signature symmetry but excluded by design: it is a
    fixed per-order charge, so it cannot be expressed as a rate. Test CP-17 pins the
    consequence — fixed fees hurt cheap orders more than expensive ones.
    """
    return commission + payment + affiliate


def seller_received_per_unit(
    net_item_value_per_unit: float,
    units: int,
    commission: float,
    admin_fee: float = 0.0,
    payment: float = 0.0,
    affiliate: float = 0.0,
    *,
    rate: Optional[float] = None,
) -> float:
    """What the seller actually receives per unit, after all fees (tech_spec §5.1).

    `net_item_value_per_unit` is what the *buyer* paid **for one unit**. The name is
    deliberately explicit: passing a line total here instead of a unit price silently
    produces a receipt roughly `units` times too small. An earlier draft of this
    module made exactly that mistake, and checkpoint CP-15 is what caught it.

    The fixed `admin_fee` is charged **once per order**, so it is spread across the
    order's units. Charging it against a single unit would overstate the fee on
    multi-unit orders.
    """
    if units <= 0:
        raise ValueError("units must be positive")

    effective_rate = (
        variable_rate(commission, admin_fee, payment, affiliate) if rate is None else rate
    )
    net_after_variable = net_item_value_per_unit * (1 - effective_rate)
    return net_after_variable - (admin_fee / units)


def seller_received_total(
    net_item_value_per_unit: float,
    units: int,
    commission: float,
    admin_fee: float = 0.0,
    payment: float = 0.0,
    affiliate: float = 0.0,
) -> float:
    """Total receipt across all units, after fees."""
    return seller_received_per_unit(
        net_item_value_per_unit, units, commission, admin_fee, payment, affiliate
    ) * units


# --------------------------------------------------------------------------- #
# §7 — Under COGS
# --------------------------------------------------------------------------- #
class Severity(str, Enum):
    """Severity bands from tech_spec §7.3, expressed against cost."""
    OK = "OK"                # profitable with a real margin
    WATCH = "WATCH"          # thin but still profitable
    AT_RISK = "AT_RISK"      # losing money, under 10 % of cost
    CRITICAL = "CRITICAL"    # losing money, 10 % of cost or worse


def under_cogs_per_unit(
    cost_per_unit: float,
    net_item_value_per_unit: float,
    units: int,
    **fees: float,
) -> float:
    """Loss per unit: cost less what the seller receives (tech_spec §7.2).

    Positive means selling below cost. Negative means profitable.
    """
    received = seller_received_per_unit(net_item_value_per_unit, units, **fees)
    return cost_per_unit - received


def under_cogs_total(
    cost_per_unit: float,
    net_item_value_per_unit: float,
    units: int,
    **fees: float,
) -> float:
    """Total loss across all units (tech_spec §7.1)."""
    return (
        under_cogs_per_unit(cost_per_unit, net_item_value_per_unit, units, **fees)
        * units
    )


def classify_severity(under_cogs_per_unit: float, cost_per_unit: float) -> Severity:
    """Band a loss against cost (tech_spec §7.3).

    Bands are relative to cost, not price, so a cheap staple and an expensive item
    are comparable.
    """
    if cost_per_unit <= 0:
        raise ValueError("cost_per_unit must be positive")

    loss_pct = under_cogs_per_unit / cost_per_unit

    if under_cogs_per_unit > 0:
        return Severity.CRITICAL if loss_pct > 0.10 else Severity.AT_RISK

    # Not losing money. WATCH covers a thin-but-positive margin, i.e. revenue within
    # 5 % below cost, which means loss_pct is between -5 % and 0 %.
    if loss_pct > -0.05:
        return Severity.WATCH
    return Severity.OK


def target_price(
    cost_per_unit: float,
    target_margin: float,
    units: int,
    commission: float,
    admin_fee: float,
    payment: float,
    affiliate: float,
) -> float:
    """Price that clears cost, the target margin and all fees (tech_spec §7.5).

        price = (cost x (1 + margin) + admin_fee/unit) / (1 - variable_rate)

    The split numerator is deliberate. The percentage fees scale with price, so they
    belong in the denominator as a gross-up. The admin fee does not scale with price,
    so it is added to the numerator per unit. Folding both into one percentage — the
    tempting simplification — under-prices cheap orders.
    """
    if units <= 0:
        raise ValueError("units must be positive")

    rate = variable_rate(commission, admin_fee, payment, affiliate)
    if rate >= 1.0:
        raise ValueError("variable fee rate must be below 100%")

    admin_fee_per_unit = admin_fee / units
    return (cost_per_unit * (1 + target_margin) + admin_fee_per_unit) / (1 - rate)


def gross_exposure(under_cogs_values: Iterable[float]) -> float:
    """Sum of losses only (tech_spec §7.4).

    Profitable SKUs are ignored, because a profit elsewhere does not restore a
    depleted campaign reserve. This is the default mode for Logic 3.
    """
    return sum(value for value in under_cogs_values if value > 0)


def net_position(under_cogs_values: Iterable[float]) -> float:
    """Losses netted against profits (tech_spec §7.4).

    The reporting view. May be negative, which means the catalogue as a whole is
    profitable despite individual loss-makers.
    """
    return sum(under_cogs_values)


# --------------------------------------------------------------------------- #
# §8 — Budget safe
# --------------------------------------------------------------------------- #
class BudgetStatus(str, Enum):
    """Reserve health (tech_spec §8.2)."""
    HEALTHY = "HEALTHY"      # more than half the reserve intact
    CAUTION = "CAUTION"      # over half consumed, not yet breached
    BREACHED = "BREACHED"    # reserve exhausted


def budget_safe(campaign_budget: float, total_under_cogs: float) -> float:
    """Campaign budget less gross exposure (tech_spec §8.1).

    This is a *reserve*, not money spent — see tech_spec §8.3. It answers "are the
    losses this campaign is absorbing still small enough to keep pushing volume?".
    """
    if campaign_budget <= 0:
        raise ValueError("campaign_budget must be positive")
    return campaign_budget - total_under_cogs


def budget_remaining_pct(campaign_budget: float, total_under_cogs: float) -> float:
    """Share of the reserve still intact (tech_spec §8.1)."""
    if campaign_budget <= 0:
        raise ValueError("campaign_budget must be positive")
    return budget_safe(campaign_budget, total_under_cogs) / campaign_budget


def budget_status(campaign_budget: float, total_under_cogs: float) -> BudgetStatus:
    """Band the reserve (tech_spec §8.2).

    HEALTHY is strictly more than half remaining, so exactly half is CAUTION.
    Test CP-34 pins that boundary.
    """
    remaining = budget_safe(campaign_budget, total_under_cogs)
    if remaining <= 0:
        return BudgetStatus.BREACHED
    if remaining > 0.5 * campaign_budget:
        return BudgetStatus.HEALTHY
    return BudgetStatus.CAUTION
