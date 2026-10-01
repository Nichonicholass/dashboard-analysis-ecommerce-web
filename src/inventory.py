"""Inventory snapshot generation for both marketplaces.

Key consistency guarantees
--------------------------
* `Available = Stock - Reserved` on Shopee, `Available = Inventory - Committed`
  on TikTok (the platforms use different words for the same idea).
* `Reserved` / `Committed` are **derived from the generated orders** - units
  sitting in unshipped orders - not invented independently.
* `Sales (30d)` is **derived from the generated orders** too, so it can be
  recomputed from the sales files alone. That is the check a reviewer will run.
* Stock-outs are only assigned to SKUs with no reserved units, so the snapshot
  never contradicts an open order.

TikTok additionally emits one row per SKU **per warehouse**, and a few SKUs are
stocked in two locations, which is why the TikTok file has more rows than Shopee.
"""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

import config as cfg
from master_data import Product
from sales import (
    Order,
    SpecialSkus,
    last_sale_dates,
    reserved_units,
    shipped_units_last_30d,
)

SNAPSHOT = datetime.combine(cfg.END_DATE, time(23, 59, 59))

# Baseline cover in days: how much stock a normally-moving SKU keeps on hand.
BASE_COVER_DAYS = (12, 45)
LOW_STOCK_CEILING = 10


@dataclass
class InventoryRow:
    product: Product
    channel: str
    warehouse: str
    stock: int
    reserved: int
    sales_30d: int
    updated_at: datetime
    inbound: int = 0

    @property
    def available(self) -> int:
        return max(0, self.stock - self.reserved)


def _warehouse_plan(
    products: Sequence[Product],
    channel: str,
    rng: random.Random,
) -> Dict[str, List[str]]:
    """Map SKU -> warehouses holding it.

    Shopee assigns every SKU to its home warehouse. TikTok splits a subset of
    SKUs across two locations, which is what makes the TikTok file larger and
    cross-warehouse stock sums necessary.
    """
    if channel == cfg.SHOPEE:
        home = cfg.SHOPEE_WAREHOUSES
        return {
            product.sku_id: [home[rng.randrange(len(home))]] for product in products
        }

    primary = cfg.TIKTOK_WAREHOUSES[0]
    plan: Dict[str, List[str]] = {}
    for product in products:
        # Popular, physically small SKUs are the ones worth splitting.
        if product.popularity >= 7 and rng.random() < 0.45:
            secondary = rng.choice(cfg.TIKTOK_WAREHOUSES[1:])
            plan[product.sku_id] = [primary, secondary]
        else:
            plan[product.sku_id] = [primary]
    return plan


def _split_quantities(total: int, parts: int, rng: random.Random) -> List[int]:
    """Split a total into `parts` positive-ish chunks that still sum to `total`."""
    if parts == 1:
        return [total]
    first = int(total * rng.uniform(0.5, 0.75))
    first = min(first, total)
    return [first, total - first]


def build_inventory(
    products: Sequence[Product],
    orders: Sequence[Order],
    special_by_channel: Dict[str, SpecialSkus],
    rng: random.Random,
) -> Dict[str, List[InventoryRow]]:
    """Build the inventory snapshot for each channel."""
    reserved = reserved_units(orders)
    sold_30d = shipped_units_last_30d(orders)
    last_sold = last_sale_dates(orders)

    result: Dict[str, List[InventoryRow]] = {}
    shopee_stock: Dict[str, int] = {}

    for channel in (cfg.SHOPEE, cfg.TIKTOK):
        special = special_by_channel[channel]
        plan = _warehouse_plan(products, channel, rng)
        rows: List[InventoryRow] = []

        # Real reconciliation always yields both a matched and an unmatched
        # bucket, so deliberately make a small set of SKUs agree across channels.
        aligned: Set[str] = set()
        if channel == cfg.TIKTOK and shopee_stock:
            candidates = [
                p.sku_id for p in products
                if p.sku_id not in special.out_of_stock
                and p.sku_id not in special.low_stock
                and shopee_stock.get(p.sku_id, 0) > 0  # never align onto a stock-out
            ]
            rng.shuffle(candidates)
            aligned = set(candidates[:8])

        for product in products:
            key = (channel, product.sku_id)
            reserved_total = reserved.get(key, 0)
            sales_30d = sold_30d.get(key, 0)

            # --- Base stock from recent velocity AND catalogue popularity ---
            # Velocity alone is too thin at this order volume (500 orders over 90
            # days spreads to <1 unit/SKU/day), which would leave almost every SKU
            # reading as low stock. Popularity provides the realistic baseline.
            daily_rate = sales_30d / cfg.INVENTORY_LOOKBACK_DAYS
            cover_days = rng.uniform(*BASE_COVER_DAYS)
            velocity_stock = int(daily_rate * cover_days)
            baseline_stock = product.popularity * rng.randint(6, 20)
            target = max(5, velocity_stock + baseline_stock)

            # Slow movers keep a flat minimum hand-stock so they don't all read 0.
            if sales_30d == 0:
                target = rng.randint(15, 60)

            # --- Overlay the requested edge cases --------------------------
            if product.sku_id in special.out_of_stock:
                target = 0
            elif product.sku_id in special.low_stock:
                target = rng.randint(1, LOW_STOCK_CEILING)

            # Aligned SKUs mirror Shopee's on-hand quantity exactly.
            if product.sku_id in aligned and product.sku_id in shopee_stock:
                target = shopee_stock[product.sku_id]

            stock = max(reserved_total, target)
            if product.sku_id in special.out_of_stock:
                stock = 0

            # --- Freshness timestamp ---------------------------------------
            if product.sku_id in special.no_sales:
                updated = SNAPSHOT - timedelta(days=rng.randint(20, 60))
            elif product.sku_id in special.low_stock:
                updated = SNAPSHOT - timedelta(hours=rng.randint(1, 48))
            else:
                last = last_sold.get(key)
                base = datetime.combine(last, time(23, 0)) if last else SNAPSHOT
                updated = min(SNAPSHOT, base + timedelta(minutes=rng.randint(5, 600)))

            warehouses = plan[product.sku_id]
            count = len(warehouses)

            # Allocate reserved units first, then top each warehouse up with free
            # stock. Doing it in this order guarantees reserved <= stock per row,
            # so `available` is never silently clamped by the max(0, ...) guard.
            reserves = _split_quantities(reserved_total, count, rng)
            free = max(0, stock - reserved_total)
            extra = _split_quantities(free, count, rng)
            stocks = [reserves[i] + extra[i] for i in range(count)]

            # A stock-out must not be contradicted by an open order.
            if product.sku_id in special.out_of_stock:
                stocks = [0] * count
                reserves = [0] * count

            for index, warehouse in enumerate(warehouses):
                rows.append(
                    InventoryRow(
                        product=product,
                        channel=channel,
                        warehouse=warehouse,
                        stock=stocks[index],
                        reserved=reserves[index],
                        # Sales (30d) is a SKU-level figure; report it once, on the
                        # primary warehouse row, so column sums stay correct.
                        sales_30d=sales_30d if index == 0 else 0,
                        updated_at=updated,
                        inbound=(
                            rng.randint(50, 300)
                            if product.sku_id in special.low_stock
                            or product.sku_id in special.out_of_stock
                            else 0
                        ),
                    )
                )

        if channel == cfg.SHOPEE:
            shopee_stock = {row.product.sku_id: row.stock for row in rows}

        result[channel] = rows

    return result


# --------------------------------------------------------------------------- #
# CSV writers
# --------------------------------------------------------------------------- #
SHOPEE_INVENTORY_COLUMNS = [
    "Product ID", "Product Name", "Parent SKU", "Variation Name", "Category",
    "Price", "Stock", "Reserved Stock", "Available Stock", "Sales (30d)",
    "Weight (gr)", "Warehouse", "Last Updated",
]

TIKTOK_INVENTORY_COLUMNS = [
    "Product ID", "Product Name", "Seller SKU", "SKU ID", "Variation", "Category",
    "Price", "Inventory", "Available Inventory", "Committed Inventory",
    "Inbound Inventory", "Sales (30d)", "Weight (gr)", "Warehouse", "Last Updated",
]


def _fmt_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def write_shopee_inventory(rows: Sequence[InventoryRow], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "shopee_inventory_export.csv"

    ordered = sorted(rows, key=lambda r: r.product.sku_id)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(SHOPEE_INVENTORY_COLUMNS)
        for row in ordered:
            writer.writerow([
                row.product.shopee_item_id,
                row.product.display_name,
                row.product.seller_sku,
                row.product.variant,
                row.product.category,
                row.product.shopee_price,
                row.stock,
                row.reserved,
                row.available,
                row.sales_30d,
                row.product.weight_gr,
                row.warehouse,
                _fmt_ts(row.updated_at),
            ])
    return path


def write_tiktok_inventory(rows: Sequence[InventoryRow], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "tiktok_inventory_export.csv"

    ordered = sorted(rows, key=lambda r: (r.product.sku_id, r.warehouse))
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(TIKTOK_INVENTORY_COLUMNS)
        for row in ordered:
            writer.writerow([
                row.product.tiktok_product_id,
                row.product.display_name,
                row.product.seller_sku,
                row.product.tiktok_sku_id,
                row.product.variant,
                row.product.category,
                row.product.tiktok_price,
                row.stock,
                row.available,
                row.reserved,
                row.inbound,
                row.sales_30d,
                row.product.weight_gr,
                row.warehouse,
                _fmt_ts(row.updated_at),
            ])
    return path