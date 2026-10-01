"""Internal seller-side costing dataset.

This is the *internal* half of the picture. The marketplace exports know what a
customer paid; only this data knows what the goods cost us.

Four files are produced
-----------------------
products_internal_cost.csv
    Internal master mirror: one row per SKU with **both** the standard and the
    currently-effective unit cost. `Cost Price` in `products_master.csv` is a
    display figure; only this file is authoritative for accounting.

cost_history.csv
    The dated cost basis. One row per SKU per cost change, plus a baseline row
    for every SKU. This is the answer to "what did this sku cost on date X",
    which is what a real costing engine needs and a single static column cannot
    express.

cogs_ledger.csv
    Month-by-month roll-forward per SKU: opening stock -> receipts -> shipped
    units -> COGS, at weighted average cost. Derives from the marketplace order
    files plus the cost basis, so COGS can be reconciled end to end.

product_margin.csv
    Per-channel margin view: net revenue, COGS, gross profit and margin %.

Design note on honesty
----------------------
COGS is computed **only from units that actually moved** (shipped, excluding
cancelled and returned). It is not estimated from order placement. Where a
period's shipped units exceed opening stock - which happens by construction for
lean SKUs - the shortfall is explicitly backfilled from the cost basis of the
month that supplied it, rather than being quietly dropped.
"""
from __future__ import annotations

import csv
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import config as cfg
from master_data import Product
from sales import Order, round_to

# --------------------------------------------------------------------------- #
# Month helpers
# --------------------------------------------------------------------------- #
def _month_start(day: date) -> date:
    return day.replace(day=1)


def _next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


MONTHS: List[str] = []
_cursor = _month_start(cfg.START_DATE)
_end_month = _month_start(cfg.END_DATE)
while _cursor <= _end_month:
    MONTHS.append(_cursor.strftime("%Y-%m"))
    _cursor = _next_month(_cursor)


# --------------------------------------------------------------------------- #
# Cost basis
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CostEntry:
    sku_id: str
    effective_from: date
    unit_cost: int
    supplier: str
    reason: str

    @property
    def effective_from_str(self) -> str:
        return self.effective_from.isoformat()


SUPPLIERS = [
    "PT Sumber Pangan Nusantara",
    "PT Aneka Konsumsi Jaya",
    "PT Mitra Distribusi Utama",
    "CV Berkah Sembako",
    "PT Global FMCG Supply",
    "PT Sentra Bahan Pokok",
]


def build_cost_basis(
    products: Sequence[Product],
    rng: random.Random,
) -> Dict[str, List[CostEntry]]:
    """Build the dated cost basis for every SKU.

    Each SKU gets a baseline entry well before the window, and ~22 % get a
    second entry partway through the window to represent a supplier price change.
    Costs are never allowed to change within a calendar month, so the monthly
    weighted average stays unambiguous.
    """
    basis: Dict[str, List[CostEntry]] = {}

    for product in products:
        baseline = CostEntry(
            sku_id=product.sku_id,
            effective_from=date(2025, 1, 1) - timedelta(days=rng.randint(30, 900)),
            unit_cost=product.cost_price,
            supplier=rng.choice(SUPPLIERS),
            reason="Opening cost basis",
        )
        entries = [baseline]

        if rng.random() < cfg.COST_CHANGE_SHARE:
            # Anchor to the 1st of August or September so the roll lands cleanly.
            change_month = rng.choice([date(2025, 8, 1), date(2025, 9, 1)])
            multiplier = rng.uniform(*cfg.COST_CHANGE_RANGE)
            new_cost = round_to(product.cost_price * multiplier, 50)
            if new_cost != baseline.unit_cost:
                entries.append(
                    CostEntry(
                        sku_id=product.sku_id,
                        effective_from=change_month,
                        unit_cost=new_cost,
                        supplier=baseline.supplier,
                        reason=(
                            "Supplier price increase"
                            if multiplier > 1
                            else "Supplier price decrease"
                        ),
                    )
                )

        basis[product.sku_id] = entries

    return basis


def cost_on(basis: Dict[str, List[CostEntry]], sku_id: str, day: date) -> int:
    """Unit cost in effect for `sku_id` on `day`."""
    effective = basis[sku_id][0].unit_cost
    for entry in basis[sku_id]:
        if entry.effective_from <= day:
            effective = entry.unit_cost
        else:
            break
    return effective


def current_cost(basis: Dict[str, List[CostEntry]], sku_id: str) -> int:
    """Latest known unit cost for `sku_id`."""
    return basis[sku_id][-1].unit_cost


# --------------------------------------------------------------------------- #
# Shipment aggregation
# --------------------------------------------------------------------------- #
@dataclass
class Shipment:
    """Units of one SKU shipped in one month, per channel."""
    shopee_units: int = 0
    tiktok_units: int = 0

    @property
    def total(self) -> int:
        return self.shopee_units + self.tiktok_units


def collect_shipments(orders: Sequence[Order]) -> Dict[Tuple[str, str], Shipment]:
    """(sku_id, month) -> shipped units, excluding cancelled and returned units.

    Returned units are subtracted here. A returned unit still incurred purchase
    cost, but it is sellable stock again, so it is not a COGS event.
    """
    shipments: Dict[Tuple[str, str], Shipment] = defaultdict(Shipment)

    for order in orders:
        if not order.counts_as_sale:
            continue
        month = order.created_at.strftime("%Y-%m")
        for line in order.lines:
            if line.is_orphan:
                continue
            moved = max(0, line.quantity - line.returned_quantity)
            if moved == 0:
                continue
            record = shipments[(line.product.sku_id, month)]
            if order.channel == cfg.SHOPEE:
                record.shopee_units += moved
            else:
                record.tiktok_units += moved

    return shipments


# --------------------------------------------------------------------------- #
# Internal master
# --------------------------------------------------------------------------- #
@dataclass
class InternalCost:
    product: Product
    standard_cost: int
    current_cost: int
    last_changed: date
    costing_method: str
    supplier: str

    @property
    def cost_delta(self) -> int:
        return self.current_cost - self.standard_cost


def build_internal_costs(
    products: Sequence[Product],
    basis: Dict[str, List[CostEntry]],
) -> List[InternalCost]:
    rows: List[InternalCost] = []
    for product in products:
        entries = basis[product.sku_id]
        rows.append(
            InternalCost(
                product=product,
                standard_cost=product.cost_price,
                current_cost=entries[-1].unit_cost,
                last_changed=entries[-1].effective_from,
                costing_method=cfg.COSTING_METHOD,
                supplier=entries[-1].supplier,
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Opening / closing stock
# --------------------------------------------------------------------------- #
@dataclass
class StockState:
    opening: int
    closing: int


def build_stock_states(
    products: Sequence[Product],
    shipments: Dict[Tuple[str, str], Shipment],
    rng: random.Random,
) -> Dict[Tuple[str, str], StockState]:
    """Opening and closing units per (sku, month).

    Closing stock carries into the next month's opening **exactly**. Any other
    behaviour would leave an unexplained gap between months that no ledger could
    justify, so the chain is strictly:

        opening[0] -> closing[0] == opening[1] -> closing[1] == opening[2] ...

    Within a month, `receipts` replenish stock. Lean SKUs deliberately
    under-replenish, so they drift along at low cover and occasionally ship more
    than they hold - which is what forces the mid-month cost backfill.
    """
    states: Dict[Tuple[str, str], StockState] = {}

    for product in products:
        lean = rng.random() < cfg.LEAN_STOCK_SHARE
        opening: Optional[int] = None

        for index, month in enumerate(MONTHS):
            shipped = shipments.get((product.sku_id, month), Shipment()).total

            if opening is None:
                # First month: no carryover, so stock must at least cover shipments.
                base = product.popularity * rng.randint(8, 22)
                if lean:
                    opening = max(1, int(shipped * rng.uniform(0.45, 0.9)))
                else:
                    opening = max(shipped + 10, base)

            shortfall = max(0, shipped - opening)
            if lean:
                # Under-replenish deliberately: receipts cover the shortfall but
                # little more, so cover stays thin and the SKU keeps shipping more
                # than it holds - which is what exercises the mid-month backfill.
                replenish = rng.randint(0, max(1, shipped))
            else:
                # Replace what was sold, plus a little, so stock drifts rather
                # than compounding. Unbounded replenishment would grow the
                # warehouse without limit and make closing inventory meaningless.
                replenish = shipped + rng.randint(0, max(1, int(opening * 0.12)))

            receipts = shortfall + replenish
            closing = max(0, opening - shipped + receipts)

            states[(product.sku_id, month)] = StockState(opening=opening, closing=closing)
            opening = closing  # carries forward exactly

    return states


# --------------------------------------------------------------------------- #
# COGS ledger
# --------------------------------------------------------------------------- #
@dataclass
class LedgerRow:
    product: Product
    month: str
    opening_units: int
    receipts_units: int
    shipped_units: int
    closing_units: int
    unit_cost: int
    opening_value: int
    receipts_value: int
    cogs: int
    closing_value: int

    @property
    def is_consistent(self) -> bool:
        return self.opening_value + self.receipts_value - self.cogs == self.closing_value


def build_ledger(
    products: Sequence[Product],
    basis: Dict[str, List[CostEntry]],
    states: Dict[Tuple[str, str], StockState],
    shipments: Dict[Tuple[str, str], Shipment],
) -> List[LedgerRow]:
    """Roll every SKU forward month by month at weighted average cost.

    Two cases, and only two:

    * **No cost change in the month** - one unit cost applies to everything, so
      the roll is trivial.
    * **Cost changed in the month** - opening stock is valued at the *old* cost
      and receipts at the *new* cost. The weighted average is then

          WA = (opening x old + receipts x new) / (closing + shipped)

      Dividing by `closing + shipped` rather than `opening + receipts` is the
      same number but makes the identity obvious: it is the pool of units that
      were either still here or had already departed.

    `cogs` is then taken **directly** as `shipped x unit_cost` rather than as a
    residual. That matters: the margin view has to cost each shipment at the same
    authoritative figure, so total COGS in the ledger and total COGS in the margin
    view agree exactly. Any rounding residue stays in `closing_value`, which is
    where it belongs.
    """
    ledger: List[LedgerRow] = []

    for product in products:
        for month in MONTHS:
            key = (product.sku_id, month)
            state = states[key]
            shipped = shipments.get(key, Shipment()).total
            receipts = state.closing - state.opening + shipped  # >= 0 by construction

            month_start = date.fromisoformat(f"{month}-01")
            prior_day = month_start - timedelta(days=1)

            changed = [
                entry
                for entry in basis[product.sku_id]
                if entry.effective_from.strftime("%Y-%m") == month
            ]

            if changed:
                old_cost = cost_on(basis, product.sku_id, prior_day)
                new_cost = changed[-1].unit_cost
                opening_value = state.opening * old_cost
                receipts_value = receipts * new_cost
                pool_units = state.closing + shipped
                unit_cost = (
                    round_to((opening_value + receipts_value) / pool_units, 1)
                    if pool_units > 0
                    else new_cost
                )
            else:
                unit_cost = cost_on(basis, product.sku_id, month_start)
                opening_value = state.opening * unit_cost
                receipts_value = receipts * unit_cost

            closing_value = state.closing * unit_cost

            # COGS is settled cost x units actually moved. Closing value is the
            # residual, so `opening + receipts - cogs == closing` holds exactly.
            cogs = shipped * unit_cost
            closing_value = opening_value + receipts_value - cogs

            ledger.append(
                LedgerRow(
                    product=product,
                    month=month,
                    opening_units=state.opening,
                    receipts_units=receipts,
                    shipped_units=shipped,
                    closing_units=state.closing,
                    unit_cost=unit_cost,
                    opening_value=opening_value,
                    receipts_value=receipts_value,
                    cogs=cogs,
                    closing_value=closing_value,
                )
            )

    return ledger


# --------------------------------------------------------------------------- #
# Margin view
# --------------------------------------------------------------------------- #
@dataclass
class MarginRow:
    product: Product
    channel: str
    units_sold: int
    net_revenue: int
    cogs: int

    @property
    def gross_profit(self) -> int:
        return self.net_revenue - self.cogs

    @property
    def margin_pct(self) -> float:
        return (self.gross_profit / self.net_revenue * 100) if self.net_revenue else 0.0


def build_margins(
    orders: Sequence[Order],
    unit_costs: Dict[Tuple[str, str], int],
) -> List[MarginRow]:
    """Net revenue and COGS per SKU per channel, across the whole window.

    Only units that actually moved are counted, so a returned unit contributes
    neither revenue nor COGS. COGS uses the **same weighted-average unit cost as
    the ledger** for that SKU and month, so the two views reconcile exactly.
    """
    revenue: Dict[Tuple[str, str], int] = defaultdict(int)
    units: Dict[Tuple[str, str], int] = defaultdict(int)
    cogs: Dict[Tuple[str, str], int] = defaultdict(int)
    seen: Dict[str, Product] = {}

    for order in orders:
        if not order.counts_as_sale:
            continue
        month = order.created_at.strftime("%Y-%m")
        for line in order.lines:
            if line.is_orphan:
                continue
            moved = max(0, line.quantity - line.returned_quantity)
            if moved == 0:
                continue

            key = (line.product.sku_id, order.channel)
            seen[line.product.sku_id] = line.product
            unit_cost = unit_costs.get((line.product.sku_id, month), 0)

            # Net revenue per unit is what the buyer actually bore, so scale the
            # line's after-discount subtotal by the share of units that moved.
            unit_net_value = line.subtotal_after_discount / line.quantity
            units[key] += moved
            revenue[key] += round(moved * unit_net_value)
            cogs[key] += moved * unit_cost

    rows = [
        MarginRow(
            product=seen[sku_id],
            channel=channel,
            units_sold=unit_count,
            net_revenue=revenue[(sku_id, channel)],
            cogs=cogs[(sku_id, channel)],
        )
        for (sku_id, channel), unit_count in units.items()
    ]
    rows.sort(key=lambda r: (r.product.sku_id, r.channel))
    return rows


# --------------------------------------------------------------------------- #
# CSV writers
# --------------------------------------------------------------------------- #
INTERNAL_COST_COLUMNS = [
    "SKU ID", "Seller SKU", "Product Name", "Category", "Brand", "UOM",
    "Standard Cost", "Current Cost", "Cost Delta", "Cost Change %",
    "Last Cost Change", "Costing Method", "Supplier",
]

COST_HISTORY_COLUMNS = [
    "SKU ID", "Seller SKU", "Product Name", "Effective From", "Effective To",
    "Unit Cost", "Supplier", "Change Reason", "Is Current",
]

LEDGER_COLUMNS = [
    "Month", "SKU ID", "Seller SKU", "Product Name", "Category",
    "Opening Units", "Receipts Units", "Shipped Units", "Closing Units",
    "Unit Cost (WA)", "Opening Value", "Receipts Value", "COGS", "Closing Value",
    "COGS per Unit", "Stock Turns",
]

MARGIN_COLUMNS = [
    "SKU ID", "Seller SKU", "Product Name", "Category", "Channel",
    "Units Sold", "Net Revenue", "COGS", "Gross Profit", "Gross Margin %",
]


def write_internal_costs(rows: Sequence[InternalCost], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "products_internal_cost.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(INTERNAL_COST_COLUMNS)
        for row in rows:
            delta = row.cost_delta
            pct = (delta / row.standard_cost * 100) if row.standard_cost else 0.0
            writer.writerow([
                row.product.sku_id,
                row.product.seller_sku,
                row.product.name,
                row.product.category,
                row.product.brand,
                row.product.uom,
                row.standard_cost,
                row.current_cost,
                delta,
                f"{pct:.2f}",
                row.last_changed.isoformat(),
                row.costing_method,
                row.supplier,
            ])
    return path


def write_cost_history(
    products: Sequence[Product],
    basis: Dict[str, List[CostEntry]],
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "cost_history.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(COST_HISTORY_COLUMNS)
        for product in products:
            entries = basis[product.sku_id]
            for index, entry in enumerate(entries):
                is_last = index == len(entries) - 1
                effective_to = (
                    "" if is_last else (entries[index + 1].effective_from - timedelta(days=1)).isoformat()
                )
                writer.writerow([
                    product.sku_id,
                    product.seller_sku,
                    product.name,
                    entry.effective_from_str,
                    effective_to,
                    entry.unit_cost,
                    entry.supplier,
                    entry.reason,
                    "TRUE" if is_last else "FALSE",
                ])
    return path


def write_ledger(rows: Sequence[LedgerRow], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "cogs_ledger.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(LEDGER_COLUMNS)
        for row in sorted(rows, key=lambda r: (r.month, r.product.sku_id)):
            cogs_per_unit = (
                round(row.cogs / row.shipped_units, 1) if row.shipped_units else 0
            )
            # Stock turns: annualised COGS / average inventory value.
            average_value = (row.opening_value + row.closing_value) / 2
            turns = (
                round(row.cogs * 4 / average_value, 2)
                if average_value > 0 and row.shipped_units
                else 0.0
            )
            writer.writerow([
                row.month,
                row.product.sku_id,
                row.product.seller_sku,
                row.product.name,
                row.product.category,
                row.opening_units,
                row.receipts_units,
                row.shipped_units,
                row.closing_units,
                row.unit_cost,
                row.opening_value,
                row.receipts_value,
                row.cogs,
                row.closing_value,
                cogs_per_unit,
                turns,
            ])
    return path


def write_margins(rows: Sequence[MarginRow], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "product_margin.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(MARGIN_COLUMNS)
        for row in rows:
            writer.writerow([
                row.product.sku_id,
                row.product.seller_sku,
                row.product.name,
                row.product.category,
                row.channel,
                row.units_sold,
                row.net_revenue,
                row.cogs,
                row.gross_profit,
                f"{row.margin_pct:.2f}",
            ])
    return path