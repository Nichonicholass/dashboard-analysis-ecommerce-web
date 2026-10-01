"""Order generation and channel-specific sales-export writers.

Design notes
------------
* Both channels describe the *same* economics but present them differently:

  Shopee : list price -> seller discount ("Deal Price") -> platform discount
  TikTok : subtotal before discount -> seller + platform discount -> after

  Net item value is identical on both channels, which makes cross-channel
  revenue reconciliation possible and gives the prototype something to validate.

* Row layout differs per channel. Shopee repeats order-level fields on every
  line item at the "No." level; TikTok emits order-level fields with line-level
  SKU fields, including `Warehouse` and `Seller SKU`.

* Edge-case SKUs (out of stock / low stock / no sales) are chosen *after* the
  orders exist. An out-of-stock SKU must not be sitting in a `Ready to Ship`
  order, so it is only picked from SKUs that hold no reserved stock.
"""
from __future__ import annotations

import csv
import random
import string
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import config as cfg
from master_data import Product

SNAPSHOT = datetime.combine(cfg.END_DATE, time(23, 59, 59))


# --------------------------------------------------------------------------- #
# Rounding helper
# --------------------------------------------------------------------------- #
def round_to(value: float, step: int) -> int:
    """Round to the nearest `step`, never below zero."""
    if value <= 0:
        return 0
    return max(0, int(round(value / step)) * step)


# --------------------------------------------------------------------------- #
# Delisted / orphan SKUs - orders referencing products missing from the catalogue
# --------------------------------------------------------------------------- #
ORPHAN_SKUS = [
    ("SS-ORPHAN-0001", "Mie Instan Goreng 85 gr - Goreng", "Goreng", 3_500),
    ("SS-ORPHAN-0002", "Air Mineral 600 ml", "600 ml", 4_000),
    ("SS-ORPHAN-0003", "Deterjen Bubuk 800 gr", "800 gr", 24_000),
]


# --------------------------------------------------------------------------- #
# Line model
# --------------------------------------------------------------------------- #
@dataclass
class OrderLine:
    product: Product
    quantity: int
    returned_quantity: int
    unit_list_price: int          # channel list price at time of order
    unit_seller_discount: int     # per-unit seller-funded discount
    unit_platform_discount: int   # per-unit marketplace-funded discount
    orphan: Optional[Tuple[str, str, str, int]] = None  # delisted SKU tuple

    @property
    def is_orphan(self) -> bool:
        return self.orphan is not None

    @property
    def seller_sku(self) -> str:
        return self.orphan[0] if self.orphan else self.product.seller_sku

    @property
    def display_name(self) -> str:
        return self.orphan[1] if self.orphan else self.product.display_name

    @property
    def variant(self) -> str:
        return self.orphan[2] if self.orphan else self.product.variant

    @property
    def unit_deal_price(self) -> int:
        """Shopee's 'Deal Price' - unit price after the seller discount."""
        return self.unit_list_price - self.unit_seller_discount

    # --- Shopee presentation ------------------------------------------------
    @property
    def product_subtotal(self) -> int:
        """Shopee 'Product Subtotal' (deal price x qty, platform discount excluded)."""
        return self.unit_deal_price * self.quantity

    @property
    def seller_discount_total(self) -> int:
        return self.unit_seller_discount * self.quantity

    @property
    def platform_discount_total(self) -> int:
        return self.unit_platform_discount * self.quantity

    # --- TikTok presentation ------------------------------------------------
    @property
    def subtotal_before_discount(self) -> int:
        return self.unit_list_price * self.quantity

    @property
    def subtotal_after_discount(self) -> int:
        return (
            self.subtotal_before_discount
            - self.seller_discount_total
            - self.platform_discount_total
        )

    @property
    def net_item_value(self) -> int:
        """Channel-independent net item value - identical on Shopee and TikTok."""
        return self.subtotal_after_discount


# --------------------------------------------------------------------------- #
# Order model
# --------------------------------------------------------------------------- #
@dataclass
class Order:
    channel: str
    order_id: str
    status: str
    order_substatus: str
    lines: List[OrderLine]
    buyer_username: str
    receiver_name: str
    phone: str
    address: str
    city: str
    province: str
    postal_code: str
    payment_method: str
    courier: str
    warehouse: str
    order_channel: str
    note: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    rts_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: str = ""
    return_reason: str = ""

    # --- Buyer-paid amounts (order level, not line level) -------------------
    seller_voucher: int = 0
    platform_voucher: int = 0
    coin_discount: int = 0
    buyer_paid_shipping_fee: int = 0
    shipping_discount: int = 0
    original_shipping_fee: int = 0

    # --- Convenience --------------------------------------------------------
    @property
    def items_gross(self) -> int:
        return sum(line.subtotal_before_discount for line in self.lines)

    @property
    def seller_discount_total(self) -> int:
        return sum(line.seller_discount_total for line in self.lines)

    @property
    def platform_discount_total(self) -> int:
        return sum(line.platform_discount_total for line in self.lines)

    @property
    def units(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def is_cancelled(self) -> bool:
        return self.status in cfg.CANCELLED_STATUSES[self.channel]

    @property
    def is_returned(self) -> bool:
        return self.status in cfg.RETURNED_STATUSES[self.channel]

    @property
    def counts_as_sale(self) -> bool:
        return self.status in cfg.SOLD_STATUSES[self.channel]

    @property
    def holds_stock(self) -> bool:
        return self.status in cfg.RESERVED_STATUSES[self.channel]

    # --- Channel totals -----------------------------------------------------
    def shopee_total_amount(self) -> int:
        """Shopee 'Total Amount' = net item value + shipping actually paid."""
        net_items = (
            self.items_gross
            - self.seller_discount_total
            - self.platform_discount_total
            - self.seller_voucher
            - self.platform_voucher
            - self.coin_discount
        )
        return max(0, net_items) + self.buyer_paid_shipping_fee

    def tiktok_order_amount(self) -> int:
        """TikTok 'Order Amount' = sum of after-discount subtotals + shipping paid."""
        net_items = sum(line.subtotal_after_discount for line in self.lines)
        net_items -= self.seller_voucher + self.platform_voucher + self.coin_discount
        return max(0, net_items) + self.buyer_paid_shipping_fee

    def refund_amount(self) -> int:
        """Value of returned units, at the deal price actually paid."""
        if not self.is_returned:
            return 0
        return sum(line.unit_deal_price * line.returned_quantity for line in self.lines)


# --------------------------------------------------------------------------- #
# Special-SKU selection (drives availability edge cases)
# --------------------------------------------------------------------------- #
@dataclass
class SpecialSkus:
    """Per-channel SKU sets used to create realistic availability problems."""
    out_of_stock: Set[str] = field(default_factory=set)
    low_stock: Set[str] = field(default_factory=set)
    no_sales: Set[str] = field(default_factory=set)


# --------------------------------------------------------------------------- #
# Timestamp helpers
# --------------------------------------------------------------------------- #
def _date_weights() -> List[Tuple[date, float]]:
    """Seasonal weight for every day in the window (weekend, payday, campaigns)."""
    span = (cfg.END_DATE - cfg.START_DATE).days + 1
    weighted: List[Tuple[date, float]] = []
    for offset in range(span):
        day = cfg.START_DATE + timedelta(days=offset)
        weight = 1.0
        weight *= cfg.WEEKEND_MULTIPLIER.get(day.weekday(), 1.0)
        if day.day >= 25 or day.day <= 5:
            weight *= cfg.PAYDAY_MULTIPLIER
        weight *= cfg.CAMPAIGN_DATES.get(day, 1.0)
        weighted.append((day, weight))
    return weighted


_DATE_WEIGHTS = _date_weights()


def _random_timestamp(rng: random.Random) -> datetime:
    days = [day for day, _ in _DATE_WEIGHTS]
    weights = [weight for _, weight in _DATE_WEIGHTS]
    day = rng.choices(days, weights=weights, k=1)[0]
    hour = rng.choices(range(24), weights=cfg.HOUR_WEIGHTS, k=1)[0]
    return datetime.combine(day, time(hour, rng.randint(0, 59), rng.randint(0, 59)))


def _fmt(value: Optional[datetime]) -> str:
    """Marketplaces export 'YYYY-MM-DD HH:MM:SS'; blank when the step hasn't happened."""
    return "" if value is None else value.strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# Buyer identity
# --------------------------------------------------------------------------- #
def _buyer(rng: random.Random) -> Tuple[str, str, str, str, str, str, str]:
    first = rng.choice(cfg.FIRST_NAMES)
    last = rng.choice(cfg.LAST_NAMES)
    receiver = f"{first} {last}"

    style = rng.random()
    if style < 0.55:
        username = f"{first.lower()}{rng.randint(1, 999):03d}"
    elif style < 0.85:
        username = f"{first.lower()}.{last.lower()}"
    else:
        username = f"user{rng.randint(10_000_000, 99_999_999)}"

    phone = f"08{rng.randint(10_000_000, 99_999_999)}"
    city, province, prefix = rng.choice(cfg.CITIES)
    street = rng.choice(cfg.STREET_NAMES)
    address = (
        f"{street} No. {rng.randint(1, 200)}, RT {rng.randint(1, 12):02d}/"
        f"RW {rng.randint(1, 12):02d}, {rng.choice(cfg.KELURAHAN_NAMES)}"
    )
    postal = f"{prefix}{rng.randint(100, 999)}"
    return username, receiver, phone, address, city, province, postal


# --------------------------------------------------------------------------- #
# Order ID generation
# --------------------------------------------------------------------------- #
_SHOPEE_ALPHABET = string.ascii_uppercase + string.digits


def _shopee_order_id(rng: random.Random, created: datetime) -> str:
    """15-character Shopee-style ID: YYMMDD + 9 alphanumerics."""
    suffix = "".join(rng.choices(_SHOPEE_ALPHABET, k=9))
    return f"{created:%y%m%d}{suffix}"


def _tiktok_order_id(rng: random.Random) -> str:
    """19-digit numeric TikTok Shop ID."""
    return str(rng.randint(1_000_000_000_000_000_000, 9_999_999_999_999_999_999))


# --------------------------------------------------------------------------- #
# Status selection
# --------------------------------------------------------------------------- #
_STATUS_REQUIREMENT = {
    "Completed": "completed_at",
    "Returned/Refunded": "delivered_at",
    "Refund/Return": "delivered_at",
    "Shipped": "shipped_at",
    "In Transit": "shipped_at",
    "Ready to Ship": "rts_at",
    "To Ship": "rts_at",
    "Cancelled": "created_at",
}


def _allowed_statuses(order: Order, mix: Dict[str, float]) -> Dict[str, float]:
    """Restrict a status mix to statuses whose required timestamp already occurred.

    This is what stops a 2025-09-29 order from being `Completed`; without it the
    dataset looks obviously synthetic.
    """
    allowed: Dict[str, float] = {}
    for status, weight in mix.items():
        attribute = _STATUS_REQUIREMENT.get(status)
        required = getattr(order, attribute, None) if attribute else None
        if required is not None and required <= SNAPSHOT:
            allowed[status] = weight
    if not allowed:
        fallback = "Ready to Ship" if order.channel == cfg.SHOPEE else "To Ship"
        allowed = {fallback: 1.0}
    return allowed


# --------------------------------------------------------------------------- #
# Order assembly
# --------------------------------------------------------------------------- #
def _weighted_product_choice(
    rng: random.Random,
    products: Sequence[Product],
    already_chosen: Set[str],
) -> Product:
    pool = [p for p in products if p.sku_id not in already_chosen]
    weights = [p.popularity ** 1.6 for p in pool]
    return rng.choices(pool, weights=weights, k=1)[0]


def _line_from_product(
    rng: random.Random,
    product: Product,
    channel: str,
    orphan: Optional[Tuple[str, str, str, int]] = None,
) -> OrderLine:
    list_price = orphan[3] if orphan else (
        product.shopee_price if channel == cfg.SHOPEE else product.tiktok_price
    )

    quantity = rng.choices(
        range(1, len(cfg.QUANTITY_WEIGHTS) + 1), weights=cfg.QUANTITY_WEIGHTS, k=1
    )[0]

    seller_pct = rng.uniform(*cfg.SELLER_DISCOUNT_RANGE)
    platform_pct = rng.uniform(*cfg.PLATFORM_DISCOUNT_RANGE)

    return OrderLine(
        product=product,
        quantity=quantity,
        returned_quantity=0,
        unit_list_price=list_price,
        unit_seller_discount=round_to(list_price * seller_pct, 50),
        unit_platform_discount=round_to(list_price * platform_pct, 50),
        orphan=orphan,
    )


def _build_order(rng: random.Random, products: Sequence[Product], channel: str) -> Order:
    created = _random_timestamp(rng)

    line_count = rng.choices(
        range(1, cfg.MAX_LINES_PER_ORDER + 1), weights=cfg.LINE_COUNT_WEIGHTS, k=1
    )[0]

    chosen: List[Product] = []
    while len(chosen) < line_count:
        chosen.append(
            _weighted_product_choice(rng, products, {p.sku_id for p in chosen})
        )

    username, receiver, phone, address, city, province, postal = _buyer(rng)

    order = Order(
        channel=channel,
        order_id=(
            _shopee_order_id(rng, created) if channel == cfg.SHOPEE else _tiktok_order_id(rng)
        ),
        status="",
        order_substatus="",
        lines=[_line_from_product(rng, product, channel) for product in chosen],
        buyer_username=username,
        receiver_name=receiver,
        phone=phone,
        address=address,
        city=city,
        province=province,
        postal_code=postal,
        payment_method=rng.choice(
            cfg.SHOPEE_PAYMENT_METHODS if channel == cfg.SHOPEE else cfg.TIKTOK_PAYMENT_METHODS
        ),
        courier=rng.choice(
            cfg.SHOPEE_COURIERS if channel == cfg.SHOPEE else cfg.TIKTOK_COURIERS
        ),
        warehouse=rng.choice(
            cfg.SHOPEE_WAREHOUSES if channel == cfg.SHOPEE else cfg.TIKTOK_WAREHOUSES
        ),
        order_channel="Shopee" if channel == cfg.SHOPEE else "TikTok Shop",
        note=rng.choice(cfg.BUYER_NOTES) if rng.random() < cfg.LAST_ORDER_NOTE_FRACTION else "",
        created_at=created,
    )

    # ---- Lifecycle timestamps ---------------------------------------------
    order.paid_at = created + timedelta(minutes=rng.randint(1, 120))
    order.rts_at = order.paid_at + timedelta(hours=rng.randint(2, 36))
    order.shipped_at = order.rts_at + timedelta(hours=rng.randint(1, 24))
    order.delivered_at = order.shipped_at + timedelta(days=rng.randint(1, 7))
    order.completed_at = order.delivered_at + timedelta(days=rng.randint(0, 3))
    order.cancelled_at = created + timedelta(hours=rng.randint(1, 48))

    # ---- Status ------------------------------------------------------------
    mix = cfg.SHOPEE_STATUS_MIX if channel == cfg.SHOPEE else cfg.TIKTOK_STATUS_MIX
    allowed = _allowed_statuses(order, mix)
    order.status = rng.choices(list(allowed), weights=list(allowed.values()), k=1)[0]

    _apply_status_details(order, rng)
    _clamp_timeline(order)
    _apply_order_money(order, rng)

    return order


def _clamp_timeline(order: Order) -> None:
    """Guarantee no timestamp describes an event that hasn't happened yet.

    The status mix is already filtered by `_allowed_statuses`, but a returned
    order can still carry a projected `completed_at`, and a cancellation raised
    late on 30 Sep can spill into 1 Oct. Both are trimmed here.
    """
    # A returned order never reached "completed" - it came back.
    if order.is_returned:
        order.completed_at = None

    if order.cancelled_at is not None:
        if order.cancelled_at > SNAPSHOT:
            order.cancelled_at = SNAPSHOT
        if order.created_at > order.cancelled_at:
            order.cancelled_at = None

    # Safety net for any other projected milestone beyond the snapshot.
    for attribute in ("paid_at", "rts_at", "shipped_at", "delivered_at", "completed_at"):
        value = getattr(order, attribute)
        if value is not None and value > SNAPSHOT:
            setattr(order, attribute, None)


def _apply_status_details(order: Order, rng: random.Random) -> None:
    """Clear timestamps that logically cannot exist for the chosen status."""
    if order.is_cancelled:
        order.cancel_reason = rng.choice(cfg.CANCEL_REASONS)
        if rng.random() < 0.35:
            order.paid_at = None  # buyer never paid before cancelling
        order.rts_at = order.shipped_at = order.delivered_at = order.completed_at = None
        order.order_substatus = (
            "Canceled by buyer" if rng.random() < 0.6 else "Canceled by seller"
        )
        return

    if order.is_returned:
        order.return_reason = rng.choice(cfg.RETURN_REASONS)
        order.order_substatus = "Returned"
        order.cancelled_at = None
        target = order.lines[0]
        target.returned_quantity = target.quantity if rng.random() < 0.7 else 1
        return

    order.cancelled_at = None

    if order.status == "Completed":
        order.order_substatus = "Delivered"
        return

    if order.status in {"Shipped", "In Transit"}:
        order.order_substatus = "In transit"
        order.delivered_at = None      # still moving
        order.completed_at = None
        return

    # Awaiting shipment.
    order.order_substatus = "Awaiting shipment"
    order.shipped_at = None
    order.delivered_at = None
    order.completed_at = None


def _apply_order_money(order: Order, rng: random.Random) -> None:
    gross = order.items_gross

    if rng.random() < 0.25:
        order.seller_voucher = round_to(gross * rng.uniform(0.02, 0.10), 500)
    if rng.random() < 0.30:
        order.platform_voucher = round_to(gross * rng.uniform(0.02, 0.12), 500)
    if rng.random() < 0.20:
        order.coin_discount = round_to(rng.uniform(500, 5_000), 500)

    order.original_shipping_fee = round_to(rng.uniform(8_000, 25_000), 500)
    if rng.random() < cfg.FREE_SHIPPING_PROBABILITY:
        order.shipping_discount = order.original_shipping_fee
    elif rng.random() < 0.35:
        order.shipping_discount = round_to(
            order.original_shipping_fee * rng.uniform(0.2, 0.7), 500
        )
    order.buyer_paid_shipping_fee = order.original_shipping_fee - order.shipping_discount

    # Order-level vouchers must never exceed the item value, or totals go negative.
    ceiling = max(0, gross - order.seller_discount_total - order.platform_discount_total)
    spent = order.seller_voucher + order.platform_voucher + order.coin_discount
    if spent > ceiling and spent:
        scale = ceiling / spent
        order.seller_voucher = int(order.seller_voucher * scale)
        order.platform_voucher = int(order.platform_voucher * scale)
        order.coin_discount = int(order.coin_discount * scale)


# --------------------------------------------------------------------------- #
# Public generation entry point
# --------------------------------------------------------------------------- #
def generate_orders(
    products: Sequence[Product],
    rng: random.Random,
    channels: Optional[Iterable[str]] = None,
) -> List[Order]:
    """Generate `cfg.NUM_ORDERS` orders spread across the channels.

    TikTok Shop's share ramps upward over the window because it is the newer
    channel; Shopee is the established volume driver.
    """
    active = list(channels) if channels else [cfg.SHOPEE, cfg.TIKTOK]
    orders: List[Order] = []
    seen_ids: Set[str] = set()

    while len(orders) < cfg.NUM_ORDERS:
        ramp = len(orders) / max(1, cfg.NUM_ORDERS - 1)
        weights = {}
        for channel in active:
            base = cfg.CHANNEL_SPLIT[channel]
            if channel == cfg.TIKTOK:
                base *= 1 + cfg.TIKTOK_GROWTH_RAMP * ramp
            weights[channel] = base

        channel = rng.choices(list(weights), weights=list(weights.values()), k=1)[0]
        order = _build_order(rng, products, channel)

        if order.order_id in seen_ids:  # collisions are rare, but must not ship
            continue
        seen_ids.add(order.order_id)
        orders.append(order)

    orders.sort(key=lambda o: (o.created_at, o.order_id))
    return orders


# --------------------------------------------------------------------------- #
# Aggregates consumed by the inventory module
# --------------------------------------------------------------------------- #
def shipped_units_last_30d(orders: Sequence[Order]) -> Dict[Tuple[str, str], int]:
    """(channel, sku_id) -> units from sale-realised orders in the last 30 days."""
    cutoff = SNAPSHOT - timedelta(days=cfg.INVENTORY_LOOKBACK_DAYS)
    totals: Dict[Tuple[str, str], int] = {}
    for order in orders:
        if not order.counts_as_sale or order.created_at < cutoff:
            continue
        for line in order.lines:
            if line.is_orphan:
                continue
            sold = max(0, line.quantity - line.returned_quantity)
            key = (order.channel, line.product.sku_id)
            totals[key] = totals.get(key, 0) + sold
    return totals


def reserved_units(orders: Sequence[Order]) -> Dict[Tuple[str, str], int]:
    """(channel, sku_id) -> units still held in unshipped orders."""
    totals: Dict[Tuple[str, str], int] = {}
    for order in orders:
        if not order.holds_stock:
            continue
        for line in order.lines:
            if line.is_orphan:
                continue
            key = (order.channel, line.product.sku_id)
            totals[key] = totals.get(key, 0) + line.quantity
    return totals


def last_sale_dates(orders: Sequence[Order]) -> Dict[Tuple[str, str], date]:
    """(channel, sku_id) -> date of the most recent sale, for inventory freshness."""
    latest: Dict[Tuple[str, str], date] = {}
    for order in orders:
        if not order.counts_as_sale:
            continue
        for line in order.lines:
            if line.is_orphan:
                continue
            key = (order.channel, line.product.sku_id)
            current = latest.get(key)
            if current is None or order.created_at.date() > current:
                latest[key] = order.created_at.date()
    return latest


def select_special_skus(
    products: Sequence[Product],
    orders: Sequence[Order],
    channel: str,
) -> SpecialSkus:
    """Choose the availability edge cases for one channel.

    `out_of_stock` SKUs are drawn only from SKUs holding **zero** reserved units,
    so a stock-out never contradicts an open `Ready to Ship` order. Slow movers
    are preferred, because that is what actually runs dry in practice.
    """
    reserved = reserved_units(orders)
    recent = shipped_units_last_30d(orders)

    by_popularity = sorted(products, key=lambda p: (p.popularity, p.sku_id))

    # A per-channel offset keeps the two channels' stock-outs from being
    # identical, which is what produces the cross-channel stock mismatch.
    offset = 0 if channel == cfg.SHOPEE else 9
    rotating = by_popularity[offset:] + by_popularity[:offset]

    out_of_stock: Set[str] = set()
    for product in rotating:
        if len(out_of_stock) >= 4:
            break
        if reserved.get((channel, product.sku_id), 0) == 0:
            out_of_stock.add(product.sku_id)

    low_stock: Set[str] = set()
    for product in rotating:
        if len(low_stock) >= 5:
            break
        if product.sku_id not in out_of_stock:
            low_stock.add(product.sku_id)

    # SKUs with no sales in the lookback window, slow movers first.
    no_sales = {
        p.sku_id for p in by_popularity if recent.get((channel, p.sku_id), 0) == 0
    }
    if len(no_sales) > 3:
        trimmed = [p.sku_id for p in by_popularity if p.sku_id in no_sales][:3]
        no_sales = set(trimmed)

    return SpecialSkus(out_of_stock, low_stock, no_sales)


def inject_orphan_lines(
    orders: Sequence[Order],
    products: Sequence[Product],
    rng: random.Random,
    count: int = 4,
) -> int:
    """Sprinkle in orders referencing SKUs no longer present in the catalogue.

    Real exports routinely contain delisted SKUs. A prototype that assumes every
    order row maps to a known product will break here - which is the point.
    """
    injected = 0
    eligible = [o for o in orders if len(o.lines) < cfg.MAX_LINES_PER_ORDER]
    rng.shuffle(eligible)

    for order in eligible:
        if injected >= count:
            break
        orphan = ORPHAN_SKUS[injected % len(ORPHAN_SKUS)]
        order.lines.append(_line_from_product(rng, products[0], order.channel, orphan=orphan))
        injected += 1

    return injected


# --------------------------------------------------------------------------- #
# CSV writers
# --------------------------------------------------------------------------- #
SHOPEE_ORDER_COLUMNS = [
    "No.", "Order ID", "Order Status", "Product Name", "SKU Reference No.",
    "Variation", "Original Price", "Deal Price", "Quantity", "Returned Quantity",
    "Product Subtotal", "Seller Discount", "Shopee Discount", "Shopee Coin Discount",
    "Buyer Paid Shipping Fee", "Shopee Shipping Discount", "Seller Voucher",
    "Shopee Voucher", "Total Amount", "Buyer Username", "Receiver Name",
    "Phone Number", "Delivery Address", "City", "Province", "Postal Code",
    "Payment Method", "Courier", "Warehouse", "Cancel Reason",
    "Return/Refund Status", "Create Time", "Paid Time", "Ready to Ship Time",
    "Ship Time", "Delivered Time", "Complete Time", "Cancel Time", "Note",
]

TIKTOK_ORDER_COLUMNS = [
    "Order ID", "Order Status", "Order Substatus", "Cancel/Return Type",
    "Seller SKU", "Product Name", "Variation", "SKU ID", "Quantity",
    "Sku Unit Original Price", "Sku Subtotal Before Discount",
    "Sku Platform Discount", "Sku Seller Discount", "Sku Subtotal After Discount",
    "Shipping Fee After Discount", "Original Shipping Fee", "Buyer Username",
    "Receiver Name", "Phone Number", "Delivery Address", "City", "Province",
    "Postal Code", "Payment Method", "Courier", "Warehouse", "Order Channel",
    "Created Time", "Paid Time", "RTS Time", "Shipped Time", "Delivered Time",
    "Cancelled Time", "Order Amount", "Order Refund Amount", "Buyer Note",
]


def _order_month(order: Order) -> str:
    return order.created_at.strftime("%Y-%m")


def _group_by_month(orders: Sequence[Order], channel: str) -> Dict[str, List[Order]]:
    grouped: Dict[str, List[Order]] = {}
    for order in orders:
        if order.channel == channel:
            grouped.setdefault(_order_month(order), []).append(order)
    return grouped


def write_shopee_orders(orders: Sequence[Order], out_dir: Path) -> List[Path]:
    """Write one CSV per calendar month for Shopee orders."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []

    for month, month_orders in sorted(_group_by_month(orders, cfg.SHOPEE).items()):
        path = out_dir / f"shopee_orders_{month}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(SHOPEE_ORDER_COLUMNS)

            row_no = 0
            for order in month_orders:
                total_amount = order.shopee_total_amount()
                for index, line in enumerate(order.lines):
                    row_no += 1
                    is_head = index == 0
                    writer.writerow([
                        row_no,
                        order.order_id,
                        order.status,
                        line.display_name,
                        line.seller_sku,
                        line.variant,
                        line.unit_list_price,
                        line.unit_deal_price,
                        line.quantity,
                        line.returned_quantity,
                        line.product_subtotal,
                        line.seller_discount_total,
                        line.platform_discount_total,
                        order.coin_discount if is_head else 0,
                        order.buyer_paid_shipping_fee if is_head else 0,
                        order.shipping_discount if is_head else 0,
                        order.seller_voucher if is_head else 0,
                        order.platform_voucher if is_head else 0,
                        total_amount if is_head else "",
                        order.buyer_username,
                        order.receiver_name,
                        order.phone,
                        order.address,
                        order.city,
                        order.province,
                        order.postal_code,
                        order.payment_method,
                        order.courier,
                        order.warehouse,
                        order.cancel_reason,
                        "Refunded" if order.is_returned and line.returned_quantity else "",
                        _fmt(order.created_at),
                        _fmt(order.paid_at),
                        _fmt(order.rts_at),
                        _fmt(order.shipped_at),
                        _fmt(order.delivered_at),
                        _fmt(order.completed_at),
                        _fmt(order.cancelled_at),
                        order.note,
                    ])
        written.append(path)
    return written


def write_tiktok_orders(orders: Sequence[Order], out_dir: Path) -> List[Path]:
    """Write one CSV per calendar month for TikTok Shop orders."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []

    for month, month_orders in sorted(_group_by_month(orders, cfg.TIKTOK).items()):
        path = out_dir / f"tiktok_orders_{month}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(TIKTOK_ORDER_COLUMNS)

            for order in month_orders:
                order_amount = order.tiktok_order_amount()
                refund_amount = order.refund_amount()
                for index, line in enumerate(order.lines):
                    is_head = index == 0
                    writer.writerow([
                        order.order_id,
                        order.status,
                        order.order_substatus,
                        order.return_reason or order.cancel_reason,
                        line.seller_sku,
                        line.display_name,
                        line.variant,
                        line.product.tiktok_sku_id,
                        line.quantity,
                        line.unit_list_price,
                        line.subtotal_before_discount,
                        line.platform_discount_total,
                        line.seller_discount_total,
                        line.subtotal_after_discount,
                        order.buyer_paid_shipping_fee if is_head else "",
                        order.original_shipping_fee if is_head else "",
                        order.buyer_username,
                        order.receiver_name,
                        order.phone,
                        order.address,
                        order.city,
                        order.province,
                        order.postal_code,
                        order.payment_method,
                        order.courier,
                        order.warehouse,
                        order.order_channel,
                        _fmt(order.created_at),
                        _fmt(order.paid_at),
                        _fmt(order.rts_at),
                        _fmt(order.shipped_at),
                        _fmt(order.delivered_at),
                        _fmt(order.cancelled_at),
                        order_amount if is_head else "",
                        refund_amount if is_head else "",
                        order.note if is_head else "",
                    ])
        written.append(path)
    return written