"""Build the dashboard payload from the generated CSVs.

Runs after `src/generate.py`, reads the marketplace exports and the internal costing
layer, and writes `web/public/analysis.json` for the Next.js UI to render.

**All arithmetic goes through `src/metrics.py`** — the module protected by the 39
checkpoints in `checkpoint.json`. Nothing in this file reimplements a formula; it only
feeds the tested functions real rows. That is the whole point of pre-computing here
rather than reimplementing the logic in TypeScript.

Usage
-----
    python src/build_analysis.py
"""
from __future__ import annotations

import csv
import glob
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
import metrics as M  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = datetime.combine(cfg.END_DATE, time(23, 59, 59))

# --------------------------------------------------------------------------- #
# Tunables (mirrors tech_spec.md §9)
# --------------------------------------------------------------------------- #
RUN_RATE_WINDOW_HOURS = 168        # trailing 7 days
RUN_RATE_FALLBACK_HOURS = 720      # 30 days, for SKUs with no recent sales
ALERT_HORIZON_HOURS = 168          # tech_spec §9 recommends 168 over the literal 1;
                                   # see §6.4 and checkpoints CP-36..CP-39
TARGET_COVER_HOURS = 336           # 14 days of cover to reallocate toward
TARGET_MARGIN = 0.15
CAMPAIGN_BUDGET = 50_000_000.0     # manual AM input — placeholder for the prototype

# The fixture carries far more stock than demand (median cover is ~537 days), so a
# short horizon finds nothing. Classifying at several horizons lets the UI show
# *why*, rather than displaying a misleadingly empty list. See tech_spec §6.4 and
# the pinned limitation CP-36..CP-39.
HORIZONS = [24, 168, 336, 720, 2160, 8760]

# Commission per marketplace. Placeholders pending real seller contracts
# (tech_spec §5.2) — deliberately not presented as authoritative.
COMMISSION = {
    cfg.SHOPEE: dict(commission=0.080, admin_fee=1_250, payment=0.020, affiliate=0.00),
    cfg.TIKTOK: dict(commission=0.065, admin_fee=1_000, payment=0.020, affiliate=0.05),
}

SEVERITY_RANK = {"CRITICAL": 3, "AT_RISK": 2, "WATCH": 1, "OK": 0}
STOCKOUT_RANK = {"OUT_OF_STOCK": 3, "AT_RISK": 2, "HEALTHY": 1, "DORMANT": 0}


# --------------------------------------------------------------------------- #
# Raw load
# --------------------------------------------------------------------------- #
@dataclass
class SaleLine:
    channel: str
    sku: str
    sold_units: int
    net_item_value_per_unit: float
    occurred_at: datetime


@dataclass
class SkuChannel:
    sku: str
    seller_sku: str
    name: str
    category: str
    channel: str
    allocated: int
    stock_on_hand: int
    unit_cost: float
    sold_units_window: int
    sold_units_fallback: int
    sold_units_period: int
    net_item_value_per_unit: float
    revenue: float
    # filled in during analysis
    run_rate_per_hour: float = 0.0
    hours_to_stockout: Optional[float] = None
    stockout_status: str = ""
    status_by_horizon: Dict[str, str] = field(default_factory=dict)
    cover_days: Optional[float] = None
    under_cogs_per_unit: float = 0.0
    under_cogs_total: float = 0.0
    severity: str = "OK"
    seller_received_per_unit: float = 0.0
    recommended_price: float = 0.0


def _read(path: Path) -> List[dict]:
    with path.open(encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def load_sales(products_by_sku: Dict[str, dict]) -> List[SaleLine]:
    """Read sale-realised order lines from both marketplace exports."""
    lines: List[SaleLine] = []

    # Shopee — order-level fields repeat per line, so total is only on the first row.
    for path in glob.glob(str(cfg.SHOPEE_DIR / "shopee_orders_*.csv")):
        for row in _read(Path(path)):
            sku = row["SKU Reference No."]
            if sku not in products_by_sku:
                continue  # orphan SKU, not in the catalogue
            if row["Order Status"] not in cfg.SOLD_STATUSES[cfg.SHOPEE]:
                continue
            units = int(row["Quantity"]) - int(row["Returned Quantity"])
            if units <= 0:
                continue
            lines.append(SaleLine(
                channel=cfg.SHOPEE,
                sku=products_by_sku[sku]["SKU ID"],
                sold_units=units,
                net_item_value_per_unit=float(row["Deal Price"]) - float(row["Shopee Discount"]) / int(row["Quantity"]),
                occurred_at=datetime.strptime(row["Create Time"], "%Y-%m-%d %H:%M:%S"),
            ))

    # TikTok Shop — Seller SKU is the join key, prices are per unit already.
    for path in glob.glob(str(cfg.TIKTOK_DIR / "tiktok_orders_*.csv")):
        for row in _read(Path(path)):
            sku = row["Seller SKU"]
            if sku not in products_by_sku:
                continue
            if row["Order Status"] not in cfg.SOLD_STATUSES[cfg.TIKTOK]:
                continue
            units = int(row["Quantity"])
            if units <= 0:
                continue
            lines.append(SaleLine(
                channel=cfg.TIKTOK,
                sku=products_by_sku[sku]["SKU ID"],
                sold_units=units,
                net_item_value_per_unit=float(row["Sku Unit Original Price"])
                - float(row["Sku Platform Discount"]) / int(row["Quantity"])
                - float(row["Sku Seller Discount"]) / int(row["Quantity"]),
                occurred_at=datetime.strptime(row["Created Time"], "%Y-%m-%d %H:%M:%S"),
            ))

    return lines


def load_listings(products: Sequence[dict]) -> Dict[Tuple[str, str], Tuple[int, str]]:
    """(channel, sku) -> (allocated units, warehouse) from the inventory exports."""
    listings: Dict[Tuple[str, str], Tuple[int, str]] = {}

    for row in _read(cfg.SHOPEE_DIR / "shopee_inventory_export.csv"):
        seller_sku = row["Parent SKU"]
        product = next((p for p in products if p["Seller SKU"] == seller_sku), None)
        if product:
            listings[(cfg.SHOPEE, product["SKU ID"])] = (
                int(row["Stock"]) - int(row["Reserved Stock"]),
                row["Warehouse"],
            )

    # TikTok may hold one SKU across several warehouses; sum them.
    tiktok_rows = _read(cfg.TIKTOK_DIR / "tiktok_inventory_export.csv")
    aggregated: Dict[str, int] = defaultdict(int)
    warehouse: Dict[str, str] = {}
    for row in tiktok_rows:
        aggregated[row["Seller SKU"]] += int(row["Available Inventory"])
        warehouse.setdefault(row["Seller SKU"], row["Warehouse"])

    for seller_sku, units in aggregated.items():
        product = next((p for p in products if p["Seller SKU"] == seller_sku), None)
        if product:
            listings[(cfg.TIKTOK, product["SKU ID"])] = (
                units, warehouse[seller_sku]
            )

    return listings


def load_costs() -> Dict[str, float]:
    """Latest weighted-average unit cost per SKU, from the COGS ledger."""
    latest: Dict[str, Tuple[str, float]] = {}
    for row in _read(cfg.INTERNAL_DIR / "cogs_ledger.csv"):
        sku, month, cost = row["SKU ID"], row["Month"], float(row["Unit Cost (WA)"])
        if sku not in latest or month > latest[sku][0]:
            latest[sku] = (month, cost)
    return {sku: cost for sku, (_, cost) in latest.items()}


# --------------------------------------------------------------------------- #
# Analysis — every number below comes from src/metrics.py
# --------------------------------------------------------------------------- #
def analyse() -> dict:
    products = _read(cfg.MASTER_DIR / "products_master.csv")
    products_by_sku = {p["Seller SKU"]: p for p in products}
    costs = load_costs()
    listings = load_listings(products)
    sales = load_sales(products_by_sku)

    window_start = SNAPSHOT - timedelta(hours=RUN_RATE_WINDOW_HOURS)
    fallback_start = SNAPSHOT - timedelta(hours=RUN_RATE_FALLBACK_HOURS)

    # Aggregate sales per (channel, sku) over both windows.
    window_units: Dict[Tuple[str, str], int] = defaultdict(int)
    fallback_units: Dict[Tuple[str, str], int] = defaultdict(int)
    revenue: Dict[Tuple[str, str], float] = defaultdict(float)
    revenue_units: Dict[Tuple[str, str], int] = defaultdict(int)

    for line in sales:
        key = (line.channel, line.sku)
        if line.occurred_at >= window_start:
            window_units[key] += line.sold_units
        if line.occurred_at >= fallback_start:
            fallback_units[key] += line.sold_units
        revenue[key] += line.net_item_value_per_unit * line.sold_units
        revenue_units[key] += line.sold_units

    rows: List[SkuChannel] = []

    for (channel, sku), (allocated, _warehouse) in listings.items():
        product = next(p for p in products if p["SKU ID"] == sku)
        fees = COMMISSION[channel]
        cost = costs.get(sku, 0.0)

        key = (channel, sku)
        units_window = window_units.get(key, 0)
        units_fallback = fallback_units.get(key, 0)

        # §6.1 — run rate, with the documented fallback for slow movers.
        if units_window > 0:
            rate = M.run_rate_per_hour(units_window, RUN_RATE_WINDOW_HOURS)
        elif units_fallback > 0:
            rate = M.run_rate_per_hour(units_fallback, RUN_RATE_FALLBACK_HOURS)
        else:
            rate = 0.0

        # §6.2/§6.3 — projection and classification.
        hours = M.hours_to_stockout(allocated, rate)
        status = M.classify_stockout(
            allocated_units=allocated, rate_per_hour=rate, horizon_hours=ALERT_HORIZON_HOURS
        )
        status_by_horizon = {
            str(horizon): M.classify_stockout(
                allocated_units=allocated, rate_per_hour=rate, horizon_hours=horizon
            ).value
            for horizon in HORIZONS
        }

        # §7 — margin, only where the SKU actually sold.
        n_units = revenue_units.get(key, 0)
        if n_units > 0:
            net_per_unit = revenue[key] / n_units
            received = M.seller_received_per_unit(net_per_unit, n_units, **fees)
            loss_unit = M.under_cogs_per_unit(cost, net_per_unit, n_units, **fees)
            loss_total = M.under_cogs_total(cost, net_per_unit, n_units, **fees)
            severity = M.classify_severity(loss_unit, cost) if cost > 0 else M.Severity.OK
            suggested = M.target_price(cost, TARGET_MARGIN, n_units, **fees) if cost > 0 else 0.0
        else:
            net_per_unit = received = loss_unit = loss_total = 0.0
            severity = M.Severity.OK
            suggested = 0.0

        rows.append(SkuChannel(
            sku=sku,
            seller_sku=product["Seller SKU"],
            name=product["Product Name"],
            category=product["Category"],
            channel=channel,
            allocated=allocated,
            stock_on_hand=0,  # filled after the loop, aggregated across channels
            unit_cost=cost,
            sold_units_window=units_window,
            sold_units_fallback=units_fallback,
            sold_units_period=n_units,
            net_item_value_per_unit=round(net_per_unit, 2),
            revenue=round(revenue.get(key, 0.0), 2),
            run_rate_per_hour=round(rate, 6),
            hours_to_stockout=round(hours, 1) if hours is not None else None,
            stockout_status=status.value,
            status_by_horizon=status_by_horizon,
            cover_days=round(hours / 24, 1) if hours is not None else None,
            seller_received_per_unit=round(received, 2),
            under_cogs_per_unit=round(loss_unit, 2),
            under_cogs_total=round(loss_total, 2),
            severity=severity.value,
            recommended_price=round(suggested, 2),
        ))

    # Total stock on hand per SKU, so the allocation constraint is visible.
    stock_by_sku: Dict[str, int] = defaultdict(int)
    for row in _read(cfg.TIKTOK_DIR / "tiktok_inventory_export.csv"):
        for product in products:
            if product["Seller SKU"] == row["Seller SKU"]:
                stock_by_sku[product["SKU ID"]] += int(row["Inventory"])
    for row in _read(cfg.SHOPEE_DIR / "shopee_inventory_export.csv"):
        for product in products:
            if product["Seller SKU"] == row["Parent SKU"]:
                stock_by_sku[product["SKU ID"]] = max(
                    stock_by_sku[product["SKU ID"]], int(row["Stock"])
                )

    for row in rows:
        row.stock_on_hand = stock_by_sku.get(row.sku, 0)

    return {"rows": rows, "products": products, "costs": costs}


# --------------------------------------------------------------------------- #
# Reallocation recommendations (§6.5)
# --------------------------------------------------------------------------- #
def build_recommendations(rows: Sequence[SkuChannel]) -> List[dict]:
    """For every at-risk SKU, find the best donor channel."""
    by_sku: Dict[str, List[SkuChannel]] = defaultdict(list)
    for row in rows:
        by_sku[row.sku].append(row)

    recommendations: List[dict] = []

    for sku, channels in by_sku.items():
        troubled = [
            c for c in channels
            if c.stockout_status in {"AT_RISK", "OUT_OF_STOCK"} and c.run_rate_per_hour > 0
        ]
        if not troubled:
            continue

        troubled.sort(key=lambda c: STOCKOUT_RANK[c.stockout_status], reverse=True)
        target = troubled[0]

        # Donor candidates: not at risk, and with surplus above their own target cover.
        donors = [
            c for c in channels
            if c is not target and c.stockout_status not in {"AT_RISK", "OUT_OF_STOCK"}
        ]
        best: Optional[Tuple[SkuChannel, int]] = None
        for donor in donors:
            needed = max(0.0, TARGET_COVER_HOURS * target.run_rate_per_hour - target.allocated)
            move = M.recommend_reallocation(
                needed_units=needed,
                donor_allocated=donor.allocated,
                donor_rate=donor.run_rate_per_hour,
                target_cover_hours=TARGET_COVER_HOURS,
            )
            if move and (best is None or move > best[1]):
                best = (donor, move)

        recommendations.append({
            "sku": sku,
            "name": target.name,
            "from_channel": best[0].channel if best else None,
            "to_channel": target.channel,
            "move_units": best[1] if best else None,
            "reason": (
                f"{target.cover_days}d cover on {target.channel}"
                if target.cover_days is not None else "already out of stock"
            ),
            "blocked": best is None,
        })

    return recommendations


# --------------------------------------------------------------------------- #
# Emit
# --------------------------------------------------------------------------- #
def main() -> int:
    analysed = analyse()
    rows: List[SkuChannel] = analysed["rows"]
    recommendations = build_recommendations(rows)

    # Action list: only rows with something to act on, worst money first.
    actionable = [
        r for r in rows
        if r.stockout_status in {"AT_RISK", "OUT_OF_STOCK"} or r.severity in {"AT_RISK", "CRITICAL", "WATCH"}
    ]
    actionable.sort(
        key=lambda r: (SEVERITY_RANK[r.severity] * 2 + STOCKOUT_RANK[r.stockout_status]),
        reverse=True,
    )

    # Aggregate with the tested helpers rather than summing by hand.
    total_exposure = M.gross_exposure(r.under_cogs_total for r in rows)
    net = M.net_position(r.under_cogs_total for r in rows)
    reserve = M.budget_safe(CAMPAIGN_BUDGET, total_exposure)
    reserve_status = M.budget_status(CAMPAIGN_BUDGET, total_exposure)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_as_of": SNAPSHOT.isoformat(timespec="seconds"),
        "config": {
            "run_rate_window_hours": RUN_RATE_WINDOW_HOURS,
            "alert_horizon_hours": ALERT_HORIZON_HOURS,
            "target_cover_hours": TARGET_COVER_HOURS,
            "target_margin": TARGET_MARGIN,
            "campaign_budget": CAMPAIGN_BUDGET,
        },
        "summary": {
            "total_rows": len(rows),
            "at_risk_count": sum(1 for r in rows if r.stockout_status == "AT_RISK"),
            "out_of_stock_count": sum(1 for r in rows if r.stockout_status == "OUT_OF_STOCK"),
            "critical_count": sum(1 for r in rows if r.severity == "CRITICAL"),
            "below_cost_count": sum(1 for r in rows if r.under_cogs_total > 0),
            "gross_exposure": round(total_exposure, 2),
            "net_position": round(net, 2),
            "campaign_budget": CAMPAIGN_BUDGET,
            "budget_safe": round(reserve, 2),
            "budget_remaining_pct": round(M.budget_remaining_pct(CAMPAIGN_BUDGET, total_exposure) * 100, 1),
            "budget_status": reserve_status.value,
            "reallocation_count": len(recommendations),
        },
        "action_list": [asdict(r) for r in actionable],
        "recommendations": recommendations,
        "all_rows": [asdict(r) for r in rows],
        "horizon_sensitivity": [
            {
                "horizon_hours": horizon,
                "horizon_days": horizon / 24,
                "at_risk": sum(
                    1 for r in rows if r.status_by_horizon.get(str(horizon)) == "AT_RISK"
                ),
                "out_of_stock": sum(
                    1 for r in rows if r.status_by_horizon.get(str(horizon)) == "OUT_OF_STOCK"
                ),
            }
            for horizon in HORIZONS
        ],
    }

    out = ROOT / "web" / "public" / "analysis.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ seed
    # A compact "current data" seed so the Upload page can price and rank an
    # uploaded file in the browser without shipping the full analysis payload
    # (~165 KB) to the client. It carries only the catalogue cost/name, the
    # per-channel allocation and the tunables. The Upload page recomputes the
    # *uploaded* snapshot client-side (see web/src/lib/upload.ts) because a file
    # the Dashboard never saw cannot have been pre-computed here.
    products_seed: Dict[str, dict] = {}
    for row in rows:
        products_seed.setdefault(row.seller_sku, {
            "key": row.seller_sku,
            "name": row.name,
            "cost": row.unit_cost,
            "category": row.category,
        })

    listings_seed: Dict[Tuple[str, str], int] = {}
    for row in rows:
        listings_seed[(row.seller_sku, row.channel)] = row.allocated

    seed = {
        "as_of": SNAPSHOT.strftime("%Y-%m-%d"),
        "config": {
            "run_rate_window_hours": RUN_RATE_WINDOW_HOURS,
            "run_rate_fallback_hours": RUN_RATE_FALLBACK_HOURS,
            "alert_horizon_hours": ALERT_HORIZON_HOURS,
            "target_cover_hours": TARGET_COVER_HOURS,
            "target_margin": TARGET_MARGIN,
            "campaign_budget": CAMPAIGN_BUDGET,
        },
        "fees": COMMISSION,
        "products": list(products_seed.values()),
        "listings": [
            {"s": seller_sku, "c": channel, "a": allocated}
            for (seller_sku, channel), allocated in listings_seed.items()
        ],
    }
    seed_out = ROOT / "web" / "public" / "seed.json"
    seed_out.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")

    summary = payload["summary"]
    print(f"Analysis written -> {out.relative_to(ROOT)}")
    print(f"  rows analysed      : {summary['total_rows']}")
    print(f"  at risk            : {summary['at_risk_count']}"
          f"  (out of stock {summary['out_of_stock_count']})")
    print(f"  below cost         : {summary['below_cost_count']}  (critical {summary['critical_count']})")
    print(f"  gross exposure     : Rp {summary['gross_exposure']:,.0f}".replace(",", "."))
    print(f"  campaign reserve   : Rp {summary['budget_safe']:,.0f}".replace(",", ".")
          + f"  ({summary['budget_remaining_pct']}% left, {summary['budget_status']})")
    print(f"  reallocations      : {summary['reallocation_count']}")
    print(f"  seed               -> {seed_out.relative_to(ROOT)}"
          f"  ({seed_out.stat().st_size:,} bytes, {len(products_seed)} products)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())