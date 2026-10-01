# Marketplace Dummy Data — Shopee & TikTok Shop

Synthetic but internally consistent **sales** and **inventory** exports for two
marketplaces, so we can prototype ingestion, SKU mapping, reconciliation and
analytics without waiting on real seller accounts.

Built for a **FMCG / grocery** seller, Indonesian market, **IDR**, **WIB (GMT+7)**.

---

## Quick start

```powershell
python src/generate.py
```

No third-party dependencies — standard library only (Python 3.9+).

---

## What gets produced

```
data/
├── master/
│   └── products_master.csv              50 SKUs — the join key for everything
├── shopee/
│   ├── shopee_orders_2025-07.csv        monthly sales exports
│   ├── shopee_orders_2025-08.csv
│   ├── shopee_orders_2025-09.csv
│   └── shopee_inventory_export.csv      stock snapshot
├── tiktok/
│   ├── tiktok_orders_2025-07.csv        monthly sales exports
│   ├── tiktok_orders_2025-08.csv
│   ├── tiktok_orders_2025-09.csv
│   └── tiktok_inventory_export.csv      stock snapshot (+ 14 SKUs across 2 warehouses)
└── internal/                            ← seller-side costing, NOT from any marketplace
    ├── products_internal_cost.csv       50 SKUs — standard vs current cost, supplier
    ├── cost_history.csv                 dated cost basis (61 rows), the authoritative one
    ├── cogs_ledger.csv                  150 rows — monthly weighted-average roll
    └── product_margin.csv               revenue, COGS, gross profit per SKU per channel
```

Straight out of the box: **500 orders**, **50 SKUs**, **~350 Shopee** and
**~300 TikTok** order *rows*, **3 months** of history, and **Rp 10.08 M** of COGS.

All files are UTF-8 with a BOM, which is what both marketplaces emit and what
Excel needs to open the Indonesian characters correctly.

---

## Why the two channels don't look alike

The point of this dataset is not volume — it is the *friction*. Both channels
describe the same underlying event, but report it differently:

| | Shopee | TikTok Shop |
|---|---|---|
| Order ID | 15 chars, `250901LE0BCT324` | 19 digits, `8410316513328443059` |
| Item identity | `SKU Reference No.` + `Product ID` | `Seller SKU` + `SKU ID` |
| Discounts | `Deal Price` (post-seller) + separate platform discount | `Before Discount` − seller − platform |
| Stock field | `Stock` / `Reserved Stock` | `Inventory` / `Committed Inventory` |
| Warehouses | one row per SKU | one row per SKU **per warehouse** |
| Statuses | `Ready to Ship`, `Shipped`, `Completed` | `To Ship`, `In Transit`, `Completed` |

Net item value is **identical** across channels for the same economics, so
cross-channel revenue can be reconciled — but only after you normalise the
schemas. That normalisation *is* the exercise.

---

## The internal COGS dataset

The marketplace files know what a **customer paid**. Only `data/internal/` knows
what the goods **cost us**. There is deliberately no cost column anywhere in the
Shopee or TikTok exports, because a marketplace has no idea what your supplier
charges.

### `products_master.csv` is not the cost authority

It carries a `Cost Price`, but that is a display figure. `products_internal_cost.csv`
holds both the **Standard Cost** and the **Current Cost**, and `cost_history.csv`
holds the dated basis. When the two disagree, internal wins.

### Cost changes over time

A single static cost column cannot answer "what did this SKU cost on 1 August".
`cost_history.csv` can — one row per cost change, with `Effective From` /
`Effective To`:

| SKU ID | Effective From | Effective To | Unit Cost | Change Reason | Is Current |
|---|---|---|---|---|---|
| SRC-0007 | 2024-06-23 | 2025-07-31 | 8,100 | Opening cost basis | FALSE |
| SRC-0007 | 2025-08-01 | | 8,350 | Supplier price increase | TRUE |

8 of 50 SKUs reprice mid-window. Costs never change mid-month, so the monthly
weighted average is unambiguous.

### The weighted-average roll

`cogs_ledger.csv` rolls each SKU forward one month at a time:

```
opening stock  →  + receipts  →  − shipped units  →  = closing stock
```

For SRC-0007, August is the month the cost changed:

| Month | Opening | Receipts | Shipped | Closing | Unit Cost (WA) | COGS |
|---|---|---|---|---|---|---|
| 2025-07 | 84 | 40 | 7 | 117 | 8,100 | 56,700 |
| 2025-08 | 51 | 22 | 10 | 63 | **8,138** | 81,380 |
| 2025-09 | 63 | 4 | 9 | 58 | 8,350 | 75,150 |

August's 8,138 is the blend: `(51 × 8,100 + 22 × 8,350) / 73`.

### What actually counts as COGS

COGS recognises **only units that moved** — shipped, excluding cancelled and
returned. A returned unit still incurred purchase cost, but it is sellable stock
again, so it is not a COGS event. Nothing is estimated from order placement.

### Ledger = margin, to the rupiah

`product_margin.csv` reuses the ledger's weighted-average unit costs rather than
recosting independently. Ledger COGS and margin COGS are therefore **identical**
(Rp 10,084,569), which is what makes the two files safe to join.

| Channel | Net Revenue | COGS | Gross Profit | Margin |
|---|---|---|---|---|
| Shopee | Rp 5,465,200 | Rp 4,828,916 | Rp 636,284 | 11.6% |
| TikTok Shop | Rp 6,116,600 | Rp 5,255,653 | Rp 860,947 | 14.1% |

---

## Consistency guarantees

The generator self-validates and exits non-zero if any of these break:

1. Order totals recompute exactly from their own line items.
2. `Available = Stock − Reserved` (Shopee) / `Inventory − Committed` (TikTok).
3. `Reserved` is derived from units sitting in **unshipped orders** — not invented.
4. `Sales (30d)` is derived from **shipped, non-cancelled, non-returned** orders
   in the last 30 days, and can be recomputed from the sales CSVs alone.
5. Timestamps are monotonic: `Create ≤ Paid ≤ RTS ≤ Ship ≤ Delivered ≤ Complete`.
6. No timestamp describes an event after the snapshot date.
7. A stock-out is never contradicted by an open order.
8. Cancelled orders carry no downstream timestamps.
9. Ledger roll-forward holds: `opening + receipts − COGS == closing`, per row.
10. `opening + receipts − shipped == closing` units, per row.
11. Each month's closing stock is **exactly** the next month's opening stock.
12. Ledger shipped units reconcile with the marketplace order files.
13. Ledger COGS equals margin COGS, and margin COGS equals
    `units × weighted-average unit cost` recomputed from the orders.
14. Every SKU has a cost basis starting before the window opens.
15. In-window cost changes land on the 1st of a month.

Same seed → byte-identical output. Verified with MD5 hashes.

---

## Edge cases deliberately included

| Case | Where to look |
|---|---|
| Cancelled orders | ~8 % of orders, with a cancel reason |
| Returned / refunded orders | ~4–5 %, with `Returned Quantity` and a refund amount |
| Out-of-stock SKUs | 4 per channel — but **different SKUs per channel** |
| Low-stock SKUs | 5 per channel, with non-zero `Inbound` stock |
| SKUs with no 30-day sales | ~10 per channel → divide-by-zero hunting |
| **Orphan SKUs** | 4 order lines reference delisted SKUs absent from master |
| Cross-channel stock mismatch | 42 of 50 SKUs disagree; **8 agree** |
| SKUs split across warehouses | 14 TikTok SKUs stocked in 2 locations |
| Undelivered orders | ~34 % of rows still lack `Delivered Time` |
| **Supplier cost change mid-window** | 8 SKUs in `cost_history.csv` |
| **Shipped more than opening stock** | lean SKUs → cost backfilled from the new price |
| **Thin-cover SKUs** | 15 % of SKUs replenish less than they sell |

---

## Tuning

Everything lives in `src/config.py`:

```python
NUM_ORDERS      = 500          # raise to 10_000 for a load test
START_DATE      = date(2025, 7, 1)
END_DATE        = date(2025, 9, 30)
RANDOM_SEED     = 42           # change for a different but equally consistent dataset
CHANNEL_SPLIT   = {"Shopee": 0.55, "TikTok Shop": 0.45}
```

Seasonality is applied when picking order dates: weekend uplift, a payday window
(25th–5th), and campaign spikes on **7.7 / 8.8 / 9.9**. TikTok's channel share
also ramps upward across the window, since it is the newer channel.

---

## A five-minute exercise

```python
import csv, glob
from collections import defaultdict

# Reconcile 30-day unit sales against the inventory snapshot.
sold = defaultdict(int)
for path in glob.glob("data/shopee/shopee_orders_*.csv"):
    for row in csv.DictReader(open(path, encoding="utf-8-sig")):
        if row["Order Status"] in {"Completed", "Shipped"} \
           and row["Create Time"].startswith("2025-09"):
            sold[row["SKU Reference No."]] += (
                int(row["Quantity"]) - int(row["Returned Quantity"])
            )

stock = {
    row["Parent SKU"]: int(row["Sales (30d)"])
    for row in csv.DictReader(
        open("data/shopee/shopee_inventory_export.csv", encoding="utf-8-sig")
    )
}
print({sku: (stock.get(sku), units) for sku, units in sold.items() if stock.get(sku) != units})
# -> {} — every SKU reconciles.
```

Then try the same against TikTok. The schema will fight you first.

---

## Project layout

```
├── README.md
├── Product.md            PRD — what the product is and why
├── tech_spec.md          data model, formulas, thresholds
├── checkpoint.json       test manifest — 39 checkpoints
├── docs/PLAN.md          design spec for the data generator
├── data/                 generated output (delete safely, regenerate anytime)
├── src/
│   ├── config.py         all tunable knobs and reference lists
│   ├── master_data.py    catalogue, marketplace IDs, pricing
│   ├── sales.py          order lifecycle, money, channel CSV writers
│   ├── inventory.py      stock snapshot, warehouse allocation, CSV writers
│   ├── internal_data.py  cost basis, weighted-average COGS ledger, margins
│   ├── metrics.py        run rate, under COGS, budget safe — THE logic
│   ├── build_analysis.py analysis -> web/public/analysis.json
│   └── generate.py       entry point + self-validation
├── tests/
│   ├── run_checkpoints.py  reads checkpoint.json and runs each test
│   └── test_*.py           39 checkpoints
└── web/                  Next.js dashboard
```

---

## The dashboard

A Next.js app in `web/` renders the analysis. It does **not** recompute anything —
every figure comes from `src/metrics.py`, so the 39 checkpoints keep protecting the
numbers the UI shows.

```powershell
python src/generate.py            # 1. build the CSV fixture
python src/build_analysis.py      # 2. analyse -> web/public/analysis.json
cd web; npm install; npm run dev  # 3. open http://localhost:3000
```

Four screens, matching `Product.md` §7:

| Route | Purpose |
|---|---|
| `/` | **Action List** — every at-risk SKU, worst money first |
| `/sku/[sku]` | **SKU Detail** — allocation, margin, horizon sensitivity per SKU |
| `/brands` | **Brand Overview** — exposure rolled up by category |
| `/upload` | **Upload** — interface stub, not yet wired to a parser |

### Why the analysis is pre-computed

The alternative was reimplementing the formulas in TypeScript. That would have meant
two copies of logic that must agree, with the checkpoints protecting only one. Instead
`src/build_analysis.py` runs the tested functions over the CSVs and emits JSON; the
browser only formats.

### Two things the dashboard says honestly

1. **It cannot demonstrate stock-out prediction.** Median cover in the fixture is 537
   days, so a 7-day horizon flags nothing. The page states this, and the horizon chart
   shows the count rising as the threshold widens — proving the arithmetic works and
   the data is simply slow-moving (tech_spec §6.4, checkpoints CP-36–39).

2. **Commission rates are placeholders.** They are not presented as authoritative,
   because getting them wrong changes every loss figure (tech_spec §5.2).

---

## The one-page version (`simple/index.html`)

A single self-contained HTML file — no server, no build step, no dependencies. Open it
by double-clicking. Entirely in Indonesian.

```powershell
python src/generate.py            # 1. fixture
python src/build_analysis.py      # 2. analysis
python src/build_simple_data.py   # 3. demo data for the page
python src/build_simple.py        # 4. -> simple/index.html
python tests/verify_js_port.py    # 5. prove the JS matches the Python
```

**What it does.** The AM drops in marketplace exports; the page parses them, computes
the analysis in the browser, and shows a summary, stock-move suggestions, and an action
list. It opens with sample data so it is never empty.

**How it differs from the Next.js app.**

| | `web/` (Next.js) | `simple/index.html` |
|---|---|---|
| Setup | `npm install`, dev server | double-click the file |
| Computation | Python, at build time | JavaScript, in the browser |
| Upload | interface stub | **actually parses CSVs** |
| Logic copies | one (`metrics.py`) | **two** — see below |

### The tradeoff, stated plainly

A server-less page must compute in the browser, so the formulas were **ported to
JavaScript**. That means the logic now exists in two places, and the 39 checkpoints
only protect the Python.

To stop the two drifting, `tests/verify_js_port.py` feeds 19 identical cases through
both implementations and compares **55 values** — receipt per unit, loss per unit,
severity bands, target price, run rate, stock status, and budget arithmetic. It
currently reports no differences. Run it after touching either copy.

### Files

```
simple/
├── index.html      the deliverable — one file, ~41 KB, self-contained
├── _template.html  markup + styles, with __PLACEHOLDER__ slots
├── _skrip.js       the logic and CSV parsing (edited here, not in index.html)
├── _demo.json      generated demo rows + cost/name tables
└── _uji/           small CSV fixtures for exercising the upload path
```

`index.html` is **generated**. Edit `_template.html` or `_skrip.js` and rebuild.