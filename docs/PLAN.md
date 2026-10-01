# Marketplace Dummy Data Generator — Build Plan

**Goal:** produce realistic Shopee + TikTok Shop sales and inventory exports so we can
prototype ingestion, reconciliation and analytics without waiting on real seller accounts.

---

## 1. Scope

| In scope | Out of scope (for now) |
|---|---|
| 50 FMCG/grocery SKUs, listed on both marketplaces | Real API integration |
| 3 months of orders (Jul 1 – Sep 30, 2025), ~500 orders | Financial settlement / disbursement files |
| Sales export per marketplace, per month | Ads / live-commerce performance files |
| Inventory snapshot per marketplace, per warehouse | Returns-only exports |
| Reproducible, seeded, stdlib-only Python | Database loading |

Business context: **FMCG / grocery**, Indonesian market. Currency **IDR**, timezone **WIB (GMT+7)**.

---

## 2. Folder structure

```
SIRCLO_Protoyping_Workshop/
├── README.md
├── docs/
│   └── PLAN.md                     ← this file
├── data/                           ← generated output (safe to delete & regenerate)
│   ├── master/
│   │   └── products_master.csv
│   ├── shopee/
│   │   ├── shopee_orders_2025-07.csv
│   │   ├── shopee_orders_2025-08.csv
│   │   ├── shopee_orders_2025-09.csv
│   │   └── shopee_inventory_export.csv
│   ├── tiktok/
│   │   ├── tiktok_orders_2025-07.csv
│   │   ├── tiktok_orders_2025-08.csv
│   │   ├── tiktok_orders_2025-09.csv
│   │   └── tiktok_inventory_export.csv
│   └── internal/                   ← seller-side costing (no marketplace counterpart)
│       ├── products_internal_cost.csv
│       ├── cost_history.csv
│       ├── cogs_ledger.csv
│       └── product_margin.csv
└── src/
    ├── config.py        ← all knobs in one place
    ├── master_data.py   ← catalogue + per-channel listings
    ├── sales.py         ← order generation + channel-specific CSV writers
    ├── inventory.py     ← stock snapshot + CSV writers
    ├── internal_data.py ← cost basis + weighted-average COGS ledger + margins
    └── generate.py      ← entry point: `python src/generate.py`
```

---

## 3. Data model

### 3.1 Master catalogue (the join key)

`products_master.csv` is the **single source of truth**. Every marketplace row can be traced
back to it, which is exactly the problem SIRCLO solves for its clients.

| Column | Example | Notes |
|---|---|---|
| `SKU ID` | `SRC-0007` | Internal SKU, stable across channels |
| `Seller SKU` | `SS-SRC-0007` | What the seller uploads to both marketplaces |
| `Product Name` | `Susu UHT Cokelat 1 L` | |
| `Brand` | `Kelinci Putih` | Fictional brands, no trademark issues |
| `Category` | `Minuman` | 7 categories |
| `Variant` | `1 L` | |
| `UOM` | `pcs` / `box` / `pack` | |
| `Cost Price` | `14200` | ~62–80 % of base price → lets you compute margin/GMV-vs-profit |
| `Base Price` | `19000` | MSRP before channel pricing |
| `Weight (gr)` | `1050` | Drives shipping fee plausibility |
| `Shelf Life (days)` | `270` | |
| `Perishable` | `TRUE` / `FALSE` | |
| `Shopee Item ID` | `3847291056` | Marketplace ID space #1 |
| `Shopee Model ID` | `1827394056123` | |
| `Shopee Price` | `18800` | Channel-specific pricing |
| `TikTok Product ID` | `1729384756102938475` | ID space #2 (19 digits) |
| `TikTok SKU ID` | `1729384756102938476` | |
| `TikTok Price` | `19250` | |
| `Launch Date` | `2025-01-15` | |

**Why two ID spaces:** Shopee and TikTok use unrelated identifiers. Any realistic ingestion
prototype must map `Marketplace ID → internal SKU`, so we give it real work to do.

### 3.2 Catalogue composition (50 SKUs)

| Category | SKUs | Examples |
|---|---|---|
| Minuman | 10 | Air mineral 600 ml, teh kotak, jus, susu UHT, SKM |
| Makanan Instan | 8 | Mie instan (3 variants), bubur instan, sarden, kornet |
| Snack | 8 | Keripik kentang, biskuit, wafer, cokelat, permen |
| Bumbu & Rempah | 8 | Kecap, saus sambal, garam, gula, kaldu |
| Perawatan Tubuh | 6 | Sabun cair, shampoo, pasta gigi, deodoran |
| Perawatan Rumah | 6 | Deterjen, pembersih lantai, sabun cuci piring |
| Kopi & Teh | 4 | Kopi bubuk, kopi instan, teh celup, kopi susu sachet |

Each SKU carries a **popularity weight (1–10)** used when sampling order lines, so staples
(air mineral, mie instan, gula) dominate volume the way they do in reality.

---

## 4. Export schemas

### 4.1 Shopee — Sales / Order export

Order-level fields repeated on every line item (this is how Shopee actually ships it).

```
No., Order ID, Order Status, Product Name, SKU Reference No., Variation,
Original Price, Deal Price, Quantity, Returned Quantity, Product Subtotal,
Seller Discount, Shopee Discount, Shopee Coin Discount, Buyer Paid Shipping Fee,
Shopee Shipping Discount, Seller Voucher, Shopee Voucher, Total Amount,
Buyer Username, Receiver Name, Phone Number, Delivery Address, City, Province,
Payment Method, Buyer Payment Method, Courier, Return/Refund Status,
Create Time, Paid Time, Ready to Ship Time, Ship Time, Delivered Time,
Complete Time, Cancel Time, Note
```

- `Order ID` → 15-char alphanumeric, e.g. `2507140KJ8H2M9P`
- `Total Amount` = `Product Subtotal − Shopee Discount + Buyer Paid Shipping Fee`

### 4.2 TikTok Shop — Order export

```
Order ID, Order Status, Order Substatus, Cancel/Return Type, Seller SKU,
Product Name, Variation, SKU ID, Quantity, Sku Unit Original Price,
Sku Subtotal Before Discount, Sku Platform Discount, Sku Seller Discount,
Sku Subtotal After Discount, Shipping Fee After Discount, Original Shipping Fee,
Buyer Username, Receiver Name, Phone Number, Delivery Address, City, Province,
Payment Method, Courier, Warehouse, Order Channel,
Created Time, Paid Time, RTS Time, Shipped Time, Delivered Time, Cancelled Time,
Order Amount, Order Refund Amount
```

- `Order ID` → 19-digit numeric, e.g. `5769821234567890123`
- `Order Amount` = `Σ Sku Subtotal After Discount + Shipping Fee After Discount`

> **Intentional asymmetry:** Shopee reports "Deal Price" plus a separate platform discount;
> TikTok reports "Before Discount" and subtracts seller + platform discounts explicitly.
> Same underlying economics, different presentation — a genuine day-one integration headache.

### 4.3 Shopee — Inventory export

```
Product ID, Product Name, Parent SKU, Variation Name, Category, Price,
Stock, Reserved Stock, Available Stock, Sales (30d), Weight (gr),
Warehouse, Last Updated
```

### 4.4 TikTok Shop — Inventory export

```
Product ID, Product Name, Seller SKU, SKU ID, Variation, Category, Price,
Inventory, Available Inventory, Committed Inventory, Inbound Inventory,
Sales (30d), Weight (gr), Warehouse, Last Updated
```

TikTok emits **one row per SKU per warehouse** (some SKUs are stocked in two locations),
Shopee emits one row per SKU with a home warehouse.

### 4.5 Internal costing exports (seller-side, not from any marketplace)

The marketplace exports deliberately contain **no cost column** — a marketplace has no
idea what the seller pays its supplier. Costing lives in `data/internal/`.

**`products_internal_cost.csv`** — internal mirror of the catalogue.

```
SKU ID, Seller SKU, Product Name, Category, Brand, UOM, Standard Cost, Current Cost,
Cost Delta, Cost Change %, Last Cost Change, Costing Method, Supplier
```

`products_master.csv` keeps a `Cost Price` for convenience, but it is a display figure.
This file is authoritative.

**`cost_history.csv`** — the dated cost basis.

```
SKU ID, Seller SKU, Product Name, Effective From, Effective To, Unit Cost,
Supplier, Change Reason, Is Current
```

One row per SKU baseline, plus a second row for the ~22 % of SKUs that reprice
mid-window. This exists because a single static cost column cannot answer
"what did this SKU cost on 1 August". Costs never change mid-month, so the
monthly weighted average stays unambiguous.

**`cogs_ledger.csv`** — the monthly roll-forward, one row per SKU per month.

```
Month, SKU ID, Seller SKU, Product Name, Category, Opening Units, Receipts Units,
Shipped Units, Closing Units, Unit Cost (WA), Opening Value, Receipts Value,
COGS, Closing Value, COGS per Unit, Stock Turns
```

Weighted average, applied as:

```
WA = (opening x old cost + receipts x new cost) / (closing units + shipped units)
COGS = shipped units x WA
closing value = opening value + receipts value - COGS
```

When the cost does **not** change in a month, the roll collapses to a single unit
cost and `COGS = shipped x cost`.

**`product_margin.csv`** — per SKU per channel.

```
SKU ID, Seller SKU, Product Name, Category, Channel, Units Sold, Net Revenue,
COGS, Gross Profit, Gross Margin %
```

COGS here reuses the ledger's weighted-average unit costs rather than recosting
independently, so the two files reconcile to the rupiah.

**What counts as COGS.** Only units that actually moved: shipped, excluding
cancelled and returned. A returned unit still incurred purchase cost, but it is
sellable stock again, so it is not a COGS event. Nothing is estimated from order
placement.

**Stock continuity.** Each month's closing stock becomes the next month's opening
stock **exactly**. Any other behaviour would leave an unexplained gap that no
ledger could justify. ~15 % of SKUs are deliberately *lean* — they replenish less
than they sell, so they occasionally ship more than they hold. When that happens
the shortfall is costed at the **new** price rather than being silently dropped,
which is the honest answer and exercises the mid-month cost roll.

---

## 5. Generation logic

### 5.1 Channels
- Shopee **55 %**, TikTok Shop **45 %** of orders.
- TikTok is newer, so its growth curve trends slightly upward over the window.

### 5.2 Date selection (seasonality)

| Factor | Multiplier |
|---|---|
| Saturday | ×1.25 |
| Sunday | ×1.15 |
| Payday window (day ≥ 25 or day ≤ 5) | ×1.30 |
| **7.7** campaign | ×1.8 |
| **8.8** campaign | ×2.1 |
| **9.9** campaign | ×2.6 |

Hour-of-day weights peak at **12:00–13:00** and **19:00–21:00**.

### 5.3 Order shape
- 1–3 line items; ~62 % single-line.
- Quantity 1–5, weighted toward 1 (staples skew higher).
- Seller discount 0–15 %, platform voucher 0–20 %.
- Shipping fee ₫/Rp 0–25 000, ~40 % free-shipping.
- Couriers, payment methods and warehouses drawn per channel.

### 5.4 Status lifecycle (age-aware — this is important)

Status is **not** drawn at random; it depends on how old the order is relative to 30 Sep 2025.

| Order age | Allowed statuses (Shopee) |
|---|---|
| ≤ 1 day | `Ready to Ship`, `Shipped`, `Cancelled` |
| 2–4 days | `Shipped`, `Completed`, `Cancelled`, `Returned/Refunded` |
| ≥ 5 days | Full mix: Completed 70 %, Shipped 10 %, Ready to Ship 8 %, Cancelled 8 %, Returned 4 % |

Timestamps are only emitted once the milestone has actually passed — so recent orders
legitimately have empty `Delivered Time` / `Complete Time`. Without this rule the dataset
looks obviously fake.

---

## 6. Consistency rules (the things that make data survive scrutiny)

1. `Total Amount` / `Order Amount` recomputed from line items — always internally consistent.
2. `Available Stock = Stock − Reserved Stock`.
3. **`Reserved Stock`** = units sitting in orders that are `Ready to Ship` / `To Ship` — derived
   from the generated orders, not invented.
4. **`Sales (30d)`** = units actually shipped (non-cancelled, non-returned) between
   1–30 Sep 2025, per SKU per channel.
5. Order `Create Time` always ≤ `Paid Time` ≤ `RTS Time` ≤ `Ship Time` ≤ `Delivered Time` ≤ `Complete Time`.
6. Cancelled/returned orders are excluded from `Sales (30d)` and `Reserved`.
7. Every marketplace `SKU Reference No.` / `SKU ID` exists in `products_master.csv`.
8. Ledger roll-forward holds per row: `opening value + receipts value − COGS == closing value`.
9. Unit flow balances per row: `opening + receipts − shipped == closing`.
10. Each month's closing stock equals the next month's opening stock, exactly.
11. Ledger shipped units equal the units recomputed from the marketplace orders.
12. Ledger COGS equals margin COGS, and margin COGS equals
    `units × weighted-average unit cost` recomputed from the orders.
13. Every SKU has a cost basis starting before the window opens; in-window cost
    changes land on the 1st of a month.
14. Weighted-average unit cost always sits within that SKU's own historical cost range.

---

## 7. Deliberately included edge cases

These exist so the prototype has something to actually triage:

| Case | Approx. volume | Why |
|---|---|---|
| Cancelled orders | ~8 % | Tests exclusion logic |
| Returned / refunded orders (with `Refund Amount`) | ~4–5 % | Tests net-revenue logic |
| Orders with `Returned Quantity` > 0 | a few | Tests unit reconciliation |
| SKUs out of stock (`Stock = 0`) | ~4 SKUs per channel | Tests availability logic |
| SKUs low stock (`Stock ≤ 10`) | ~5 SKUs per channel | Tests reorder-alert logic |
| SKUs with zero sales in the window | ~3 SKUs | Tests divide-by-zero / "no data" |
| Stock mismatch between Shopee and TikTok for same SKU | by design | Tests cross-channel reconciliation |
| Orders still undelivered at snapshot date | ~15 % | Tests partial-timeline handling |
| Supplier cost change mid-window | 8 SKUs | Tests dated cost lookup / WA roll |
| SKU ships more than opening stock | lean SKUs | Tests backfill from the new cost |
| SKU with zero opening stock but units shipped | 1+ rows | Tests divide-by-zero in cost-per-unit |

---

## 8. QA / acceptance checks

`generate.py` prints a summary and self-validates:

- [ ] 50 rows in `products_master.csv`, unique SKU IDs
- [ ] ~500 orders total, split ≈ 55/45 across channels
- [ ] No order references an unknown SKU
- [ ] Every order total equals recomputed line-item total
- [ ] All timestamps monotonically ordered per order
- [ ] `Available Stock ≥ 0` and `Available = Stock − Reserved` everywhere
- [ ] `Sales (30d)` reproducible from the order files alone
- [ ] Ledger rolled forward and reconciled against the margin view, rupiah-exact
- [ ] Stock chain continuous month to month
- [ ] Re-running with the same seed produces byte-identical CSV files

---

## 9. How to run

```powershell
python src/generate.py
```

Optional overrides (edit `src/config.py`):

```python
NUM_ORDERS      = 500          # raise to 10_000 for a heavier load test
START_DATE      = date(2025, 7, 1)
END_DATE        = date(2025, 9, 30)
RANDOM_SEED     = 42           # change to get a different but equally consistent dataset
CHANNEL_SPLIT   = {SHOPEE: 0.55, TIKTOK: 0.45}
```

Costing knobs, also in `src/config.py`:

```python
COSTING_METHOD      = "Weighted Average"
COST_CHANGE_SHARE   = 0.22     # share of SKUs that reprice mid-window
COST_CHANGE_RANGE   = (0.92, 1.10)
LEAN_STOCK_SHARE    = 0.15     # SKUs that replenish less than they sell
```

---

## 10. Future extensions

1. **Settlement / disbursement exports** — marketplace fees, commission, net payout.
2. **Returns export** — separate file per channel with return reasons.
3. **Ads export** — spend per SKU to enable true ROAS prototyping.
4. **Stock-movement file** — goods-receipt and stock-adjustment events, so the
   COGS ledger can roll from event detail instead of monthly aggregates.
5. **Landed cost** — inbound freight and duty on top of supplier cost.
6. **Purchase orders** — supplier POs and goods-receipt notes behind each receipt.
7. **FIFO costing** — a second ledger under FIFO to compare against weighted average.
8. **Advertiser/live-commerce sessions** — TikTok Shop live stream attribution.
9. **Larger catalogue** — 500–2 000 SKUs, seasonal SKUs, discontinued SKUs.
10. **Multi-seller mode** — several shops per channel to test tenant isolation.