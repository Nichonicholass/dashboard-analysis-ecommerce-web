"""Entry point: generate the full Shopee + TikTok Shop dummy dataset.

Usage
-----
    python src/generate.py

Output
------
    data/master/products_master.csv
    data/shopee/shopee_orders_YYYY-MM.csv
    data/shopee/shopee_inventory_export.csv
    data/tiktok/tiktok_orders_YYYY-MM.csv
    data/tiktok/tiktok_inventory_export.csv

Re-running with the same `cfg.RANDOM_SEED` produces byte-identical files.
"""
from __future__ import annotations

import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, time
from pathlib import Path

# Allow `python src/generate.py` as well as `python -m src.generate`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
import internal_data as internal  # noqa: E402
import inventory as inv  # noqa: E402
import sales as sl  # noqa: E402
from master_data import build_products, write_master_csv  # noqa: E402

SNAPSHOT = datetime.combine(cfg.END_DATE, time(23, 59, 59))
RULE = "-" * 74


def _rupiah(value: float) -> str:
    return f"Rp {value:,.0f}".replace(",", ".")


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def main() -> int:
    rng = random.Random(cfg.RANDOM_SEED)

    for directory in (cfg.MASTER_DIR, cfg.SHOPEE_DIR, cfg.TIKTOK_DIR, cfg.INTERNAL_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    print(f"Generating dataset  |  seed={cfg.RANDOM_SEED}  |  "
          f"{cfg.START_DATE} -> {cfg.END_DATE}\n{RULE}")

    # ---- 1. Catalogue ------------------------------------------------------
    products = build_products(rng)
    master_path = cfg.MASTER_DIR / "products_master.csv"
    write_master_csv(products, master_path)

    # ---- 2. Orders ---------------------------------------------------------
    orders = sl.generate_orders(products, rng)
    orphans = sl.inject_orphan_lines(orders, products, rng)

    # Edge-case SKUs are decided after the orders exist so that a stock-out
    # can never contradict an open (unshipped) order.
    special_by_channel = {
        channel: sl.select_special_skus(products, orders, channel)
        for channel in (cfg.SHOPEE, cfg.TIKTOK)
    }

    # ---- 3. Inventory ------------------------------------------------------
    inventory = inv.build_inventory(products, orders, special_by_channel, rng)

    # ---- 4. Internal costing ----------------------------------------------
    basis = internal.build_cost_basis(products, rng)
    internal_costs = internal.build_internal_costs(products, basis)
    shipments = internal.collect_shipments(orders)
    stock_states = internal.build_stock_states(products, shipments, rng)
    ledger = internal.build_ledger(products, basis, stock_states, shipments)
    # The ledger is authoritative for cost, so the margin view reuses the very
    # same weighted-average unit costs rather than recosting independently.
    unit_costs = {(row.product.sku_id, row.month): row.unit_cost for row in ledger}
    margins = internal.build_margins(orders, unit_costs)

    # ---- 5. Write ----------------------------------------------------------
    shopee_files = sl.write_shopee_orders(orders, cfg.SHOPEE_DIR)
    tiktok_files = sl.write_tiktok_orders(orders, cfg.TIKTOK_DIR)
    shopee_inventory_path = inv.write_shopee_inventory(inventory[cfg.SHOPEE], cfg.SHOPEE_DIR)
    tiktok_inventory_path = inv.write_tiktok_inventory(inventory[cfg.TIKTOK], cfg.TIKTOK_DIR)

    internal_paths = [
        internal.write_internal_costs(internal_costs, cfg.INTERNAL_DIR),
        internal.write_cost_history(products, basis, cfg.INTERNAL_DIR),
        internal.write_ledger(ledger, cfg.INTERNAL_DIR),
        internal.write_margins(margins, cfg.INTERNAL_DIR),
    ]

    # ---- 6. Report ---------------------------------------------------------
    _print_summary(
        products, orders, inventory, orphans,
        shopee_files, tiktok_files,
        shopee_inventory_path, tiktok_inventory_path, master_path,
        ledger, margins, internal_paths,
    )

    failures = _validate(products, orders, inventory, basis, ledger, margins)
    if failures:
        print("\nVALIDATION FAILED")
        for failure in failures:
            print(f"  ! {failure}")
        return 1

    print("\nAll consistency checks passed.")
    return 0


def _print_summary(
    products, orders, inventory, orphans,
    shopee_files, tiktok_files,
    shopee_inventory_path, tiktok_inventory_path, master_path,
    ledger, margins, internal_paths,
) -> None:
    shopee_orders = [o for o in orders if o.channel == cfg.SHOPEE]
    tiktok_orders = [o for o in orders if o.channel == cfg.TIKTOK]

    print(f"\nCatalogue          : {len(products)} SKUs -> {master_path.name}")
    print(f"Orders             : {len(orders)} total "
          f"({len(shopee_orders)} Shopee / {len(tiktok_orders)} TikTok)")
    print(f"  of which orphan SKU lines : {orphans}")

    for label, subset in (("Shopee", shopee_orders), ("TikTok Shop", tiktok_orders)):
        statuses = Counter(o.status for o in subset)
        breakdown = ", ".join(
            f"{status} {count}" for status, count in statuses.most_common()
        )
        revenue = sum(
            o.shopee_total_amount() if o.channel == cfg.SHOPEE else o.tiktok_order_amount()
            for o in subset
            if o.counts_as_sale
        )
        print(f"\n{label} status mix   : {breakdown}")
        print(f"{label} realised GMV  : {_rupiah(revenue)}")

    monthly = defaultdict(int)
    for order in orders:
        monthly[order.created_at.strftime("%Y-%m")] += 1
    print("\nOrders per month   : " + ", ".join(
        f"{month} {count}" for month, count in sorted(monthly.items())
    ))

    for label, channel in (("Shopee", cfg.SHOPEE), ("TikTok Shop", cfg.TIKTOK)):
        rows = inventory[channel]
        per_sku_stock = defaultdict(int)
        per_sku_sales = defaultdict(int)
        for row in rows:
            per_sku_stock[row.product.sku_id] += row.stock
            per_sku_sales[row.product.sku_id] += row.sales_30d
        # Count at SKU level, not row level - TikTok emits multiple rows per SKU.
        out_of_stock = sum(1 for value in per_sku_stock.values() if value == 0)
        low = sum(1 for value in per_sku_stock.values() if 0 < value <= inv.LOW_STOCK_CEILING)
        no_sales = sum(1 for value in per_sku_sales.values() if value == 0)
        print(f"\n{label} inventory   : {len(rows)} rows / {len(per_sku_stock)} SKUs, "
              f"{out_of_stock} SKUs out of stock, {low} SKUs low stock, "
              f"{no_sales} SKUs with no 30-day sales")

    print("\nFiles written")
    print(f"  {master_path.relative_to(cfg.ROOT_DIR)}")
    for path in shopee_files + [shopee_inventory_path] + tiktok_files + [tiktok_inventory_path]:
        print(f"  {path.relative_to(cfg.ROOT_DIR)}")

    # ---- Internal costing --------------------------------------------------
    total_cogs = sum(row.cogs for row in ledger)
    total_value = sum(row.closing_value for row in ledger if row.month == internal.MONTHS[-1])
    print(f"\nInternal costing   : {len(ledger)} ledger rows across {len(internal.MONTHS)} months")
    for month in internal.MONTHS:
        month_rows = [row for row in ledger if row.month == month]
        print(f"  {month} COGS        : {_rupiah(sum(r.cogs for r in month_rows))}"
              f"  ({sum(r.shipped_units for r in month_rows)} units moved)")
    print(f"  Total COGS        : {_rupiah(total_cogs)}")
    print(f"  Closing inventory : {_rupiah(total_value)}"
          f" at weighted average cost")

    shopee_margin = [m for m in margins if m.channel == cfg.SHOPEE]
    tiktok_margin = [m for m in margins if m.channel == cfg.TIKTOK]
    for label, subset in (("Shopee", shopee_margin), ("TikTok Shop", tiktok_margin)):
        rev = sum(m.net_revenue for m in subset)
        cost = sum(m.cogs for m in subset)
        profit = rev - cost
        pct = (profit / rev * 100) if rev else 0.0
        print(f"  {label:<12} margin  : {_rupiah(profit)} on {_rupiah(rev)}"
              f"  ({pct:.1f}%)")

    print("\nFiles written")
    print(f"  {master_path.relative_to(cfg.ROOT_DIR)}")
    for path in shopee_files + [shopee_inventory_path] + tiktok_files + [tiktok_inventory_path]:
        print(f"  {path.relative_to(cfg.ROOT_DIR)}")
    for path in internal_paths:
        print(f"  {path.relative_to(cfg.ROOT_DIR)}")


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _validate(products, orders, inventory, basis, ledger, margins) -> list:
    failures = []
    sku_ids = {p.sku_id for p in products}
    seller_skus = {p.seller_sku for p in products}

    # 1. Catalogue uniqueness.
    if len(products) != 50:
        failures.append(f"expected 50 SKUs, found {len(products)}")
    if len(sku_ids) != len(products):
        failures.append("duplicate SKU IDs in catalogue")

    # 2. No known-SKU order refers to something outside the catalogue.
    for order in orders:
        for line in order.lines:
            if line.is_orphan:
                continue
            if line.product.sku_id not in sku_ids:
                failures.append(f"{order.order_id}: unknown SKU {line.product.sku_id}")
            if line.seller_sku not in seller_skus:
                failures.append(f"{order.order_id}: unknown seller SKU {line.seller_sku}")

    # 3. Order totals recompute from their own line items.
    for order in orders:
        line_sum = sum(line.subtotal_after_discount for line in order.lines)
        if order.channel == cfg.SHOPEE:
            expected = max(
                0,
                line_sum
                - order.seller_voucher
                - order.platform_voucher
                - order.coin_discount,
            ) + order.buyer_paid_shipping_fee
            actual = order.shopee_total_amount()
        else:
            expected = max(
                0,
                line_sum
                - order.seller_voucher
                - order.platform_voucher
                - order.coin_discount,
            ) + order.buyer_paid_shipping_fee
            actual = order.tiktok_order_amount()
        if expected != actual:
            failures.append(f"{order.order_id}: total mismatch {actual} != {expected}")
        if actual < 0:
            failures.append(f"{order.order_id}: negative order total")

    # 4. Timestamps are monotonic where they exist.
    sequence = ["created_at", "paid_at", "rts_at", "shipped_at", "delivered_at", "completed_at"]
    for order in orders:
        previous = None
        for attribute in sequence:
            value = getattr(order, attribute)
            if value is None:
                continue
            if previous is not None and value < previous:
                failures.append(f"{order.order_id}: {attribute} precedes earlier step")
            previous = value
            if value > SNAPSHOT:
                failures.append(f"{order.order_id}: {attribute} is in the future")

    # 5. Cancelled orders carry no downstream timestamps.
    for order in orders:
        if order.is_cancelled and order.shipped_at is not None:
            failures.append(f"{order.order_id}: cancelled but shipped")

    # 6. Sold units never exceed ordered units.
    for order in orders:
        for line in order.lines:
            if line.returned_quantity > line.quantity:
                failures.append(f"{order.order_id}: returned more units than ordered")

    # 7. Inventory arithmetic.
    for channel, rows in inventory.items():
        for row in rows:
            if row.available != max(0, row.stock - row.reserved):
                failures.append(
                    f"{channel} {row.product.sku_id}: available != stock - reserved"
                )
            if row.stock < 0 or row.reserved < 0:
                failures.append(f"{channel} {row.product.sku_id}: negative stock value")

    # 8. Stock-outs never contradict an open order.
    reserved = sl.reserved_units(orders)
    for channel, rows in inventory.items():
        totals = defaultdict(int)
        for row in rows:
            totals[row.product.sku_id] += row.stock
        for sku_id, stock in totals.items():
            if stock == 0 and reserved.get((channel, sku_id), 0) > 0:
                failures.append(
                    f"{channel} {sku_id}: zero stock but {reserved[(channel, sku_id)]} reserved"
                )

    # 9. Sales (30d) in inventory matches the recomputed figure from the orders.
    recomputed = sl.shipped_units_last_30d(orders)
    for channel, rows in inventory.items():
        reported = defaultdict(int)
        for row in rows:
            reported[row.product.sku_id] += row.sales_30d
        for sku_id, value in reported.items():
            expected = recomputed.get((channel, sku_id), 0)
            if value != expected:
                failures.append(
                    f"{channel} {sku_id}: Sales (30d) {value} != recomputed {expected}"
                )

    # 10. Reserved in inventory matches unshipped order units.
    for channel, rows in inventory.items():
        reported = defaultdict(int)
        for row in rows:
            reported[row.product.sku_id] += row.reserved
        for sku_id, value in reported.items():
            expected = reserved.get((channel, sku_id), 0)
            if value != expected:
                failures.append(
                    f"{channel} {sku_id}: reserved {value} != open-order units {expected}"
                )

    # 11. Cost basis covers every SKU, starting before the window opens.
    for product in products:
        entries = basis.get(product.sku_id)
        if not entries:
            failures.append(f"{product.sku_id}: no cost basis")
            continue
        if entries[0].effective_from > cfg.START_DATE:
            failures.append(f"{product.sku_id}: cost basis starts after the window opens")
        if any(entry.unit_cost <= 0 for entry in entries):
            failures.append(f"{product.sku_id}: non-positive unit cost in cost basis")
        for entry in entries:
            # Only in-window cost changes need to land on a month boundary; the
            # historical baseline legitimately sits on an arbitrary date.
            if entry.effective_from >= cfg.START_DATE and entry.effective_from.day != 1:
                failures.append(
                    f"{product.sku_id}: in-window cost change on {entry.effective_from} "
                    f"is not the 1st of a month"
                )
        dates = [entry.effective_from for entry in entries]
        if dates != sorted(set(dates)):
            failures.append(f"{product.sku_id}: cost history is not strictly ordered")

    # 12. Every ledger row satisfies the roll-forward identity.
    for row in ledger:
        if row.opening_value + row.receipts_value - row.cogs != row.closing_value:
            failures.append(
                f"{row.product.sku_id} {row.month}: ledger does not roll forward"
            )
        if row.closing_units < 0:
            failures.append(f"{row.product.sku_id} {row.month}: negative closing stock")
        if row.cogs < 0:
            failures.append(f"{row.product.sku_id} {row.month}: negative COGS")
        if row.opening_units + row.receipts_units - row.shipped_units != row.closing_units:
            failures.append(
                f"{row.product.sku_id} {row.month}: unit flow does not balance"
            )
        if row.receipts_units < 0:
            failures.append(f"{row.product.sku_id} {row.month}: negative receipts")

    # 12b. Each month's closing stock is exactly the next month's opening stock.
    by_key = {(row.product.sku_id, row.month): row for row in ledger}
    for product in products:
        for earlier, later in zip(internal.MONTHS, internal.MONTHS[1:]):
            previous = by_key.get((product.sku_id, earlier))
            following = by_key.get((product.sku_id, later))
            if previous and following and previous.closing_units != following.opening_units:
                failures.append(
                    f"{product.sku_id}: {earlier} closed at {previous.closing_units} "
                    f"but {later} opened at {following.opening_units}"
                )

    # 13. Ledger shipment units reconcile with the marketplace order data.
    recomputed = internal.collect_shipments(orders)
    for row in ledger:
        expected = recomputed.get((row.product.sku_id, row.month), internal.Shipment()).total
        if row.shipped_units != expected:
            failures.append(
                f"{row.product.sku_id} {row.month}: ledger units {row.shipped_units} "
                f"!= order data {expected}"
            )

    # 14. Total COGS across the ledger equals COGS derived from the orders.
    ledger_cogs = sum(row.cogs for row in ledger)
    derived_cogs = sum(row.cogs for row in margins)
    if ledger_cogs != derived_cogs:
        failures.append(
            f"total COGS mismatch: ledger {ledger_cogs} != margin view {derived_cogs}"
        )

    # 15. Margin rows are internally coherent and gross profit is not absurd.
    for row in margins:
        if row.net_revenue < 0 or row.cogs < 0:
            failures.append(f"{row.product.sku_id} {row.channel}: negative margin input")
        if row.units_sold <= 0:
            failures.append(f"{row.product.sku_id} {row.channel}: margin row with no units")
        if row.net_revenue and row.cogs > row.net_revenue * 3:
            failures.append(
                f"{row.product.sku_id} {row.channel}: COGS exceeds 3x net revenue"
            )

    # 16. Margin COGS is order units x the ledger's weighted-average unit cost.
    unit_costs = {(row.product.sku_id, row.month): row.unit_cost for row in ledger}
    expected_cogs = defaultdict(int)
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
            expected_cogs[(line.product.sku_id, order.channel)] += (
                moved * unit_costs.get((line.product.sku_id, month), 0)
            )
    for row in margins:
        expected = expected_cogs.get((row.product.sku_id, row.channel), 0)
        if row.cogs != expected:
            failures.append(
                f"{row.product.sku_id} {row.channel}: margin COGS {row.cogs} "
                f"!= per-order cost {expected}"
            )

    return failures


if __name__ == "__main__":
    raise SystemExit(main())