# Marketplace Allocation & Margin Advisor — Web App

Next.js dashboard for Account Managers (AMs) who run a brand across **Shopee,
TikTok Shop and Tokopedia** in the Indonesian market. It surfaces two problems in one
view:

1. **Stock-out risk** — an allocated listing quantity that will run dry soon.
2. **Below-cost selling** — SKUs whose receipt (after commission and fees) is under HPP.

Everything here is **advisory only**. No marketplace is ever written to; the AM
decides and executes in the seller centre.

---

## Quick start

```bash
# From the repository root
python src/generate.py           # 1. build the fixture CSVs in data/
python src/build_analysis.py     # 2. build web/public/analysis.json + seed.json
npm --prefix web run dev         # 3. http://localhost:3000
```

> On Windows, `npm --prefix <abs path> run dev` is the reliable form. A plain
> `cd web; npm run dev` loses the working directory in some terminal integrations.

---

## Pages

| Route | Purpose |
|---|---|
| `/` | **Action list.** At-risk SKUs ranked worst-first, with a horizon-sensitivity chart and reallocation suggestions. |
| `/sku/[sku]` | **SKU detail.** Pre-rendered for every SKU (`generateStaticParams`). |
| `/brands` | Brand / category roll-up. |
| `/upload` | **Manual upload.** Drop seller-centre CSVs and get an analysis right away. |

---

## Upload page (`/upload`)

The AM's real trigger is a manual export drop — there is no scheduler and no API. The
page presents **two clearly separated drop zones**:

| Step | Zone | What goes in | Required? |
|---|---|---|---|
| **1** | **Data internal** | Cost / HPP per SKU. Accepts `products_internal_cost.csv`, `cogs_ledger.csv`, `products_master.csv` (any file with `Seller SKU` **and** a recognised cost column) | Optional |
| **2** | **Data penjualan & inventori** | Seller-centre exports from Shopee / TikTok Shop — order files and inventory files, any number of them | Practically required to get rows |

### How a file is recognised

Files are identified **from their columns, never their filename**. Inventory columns
are checked before order columns — an inventory export that is mistaken for an order
export silently zeroes every allocation, which is exactly the bug that was hit and
fixed in the server-less `simple/` page.

| Marketplace | Order-file columns | Inventory-file columns |
|---|---|---|
| Shopee | `SKU Reference No.`, `Deal Price`, `Parent SKU` | `Parent SKU`, `Stock`, `Reserved Stock`, `Available Stock` |
| TikTok Shop | `Order Substatus`, `SKU ID`, `Seller SKU` | `Seller SKU`, `Inventory`, `Available Inventory` |

An unknown file is listed in the report with a red **"kolom tidak dikenali"** badge
rather than being silently dropped.

### What the page shows

- **Zone 1 / Zone 2** drop areas with per-file chips you can remove.
- **File report** — every file with its detected type (internal / orders / inventory)
  and row count, or the reason it was rejected.
- **Summary tiles** — rows analysed, below-cost count, gross exposure, campaign
  reserve.
- **Action list** — the uploaded rows ranked by money lost, then stock risk.
- Caveats for orphan SKUs (in an export but absent from the cost table) and for the
  bundled-cost fallback.

All UI copy on this page is **Bahasa Indonesia**; the rest of the app is being
localised as it is touched.

---

## Architecture: why the upload page computes in the browser

`src/build_analysis.py` **pre-computes** `web/public/analysis.json`, and the dashboard
pages only render that payload. Every number in it was produced by `src/metrics.py` —
the module protected by the **39 checkpoints** in `checkpoint.json`. That is deliberate:
there must be only one copy of the maths wherever it can be avoided.

A file the AM drops **now**, however, cannot have been pre-computed by a Python build
that ran earlier, and this prototype has no server. So the upload page recomputes in
the browser, in `web/src/lib/upload.ts`. The same port already exists for the
server-less page in `simple/_skrip.js`.

> **This is a second copy of the logic.** If you change a band, a fee split or the
> window/fallback rule, update **all three** copies — `src/metrics.py`,
> `simple/_skrip.js` and `web/src/lib/upload.ts` — together.

### Formula parity (ported from `src/metrics.py`)

| Concern | Rule | Spec |
|---|---|---|
| Variable fees | `commission + payment + affiliate`; the **admin fee is fixed per order**, never a rate | §5.1 |
| Seller receipt | `price × (1 − variable) − admin_fee / units` | §5.1 |
| Run rate | `units / observation_hours`; recent 7-day window first, then a 30-day fallback | §6.1 |
| Stock-out | dormant → out-of-stock → at-risk (`cover ≤ horizon`) → healthy. Order matters | §6.3 |
| Loss per unit | `cost − seller_received_per_unit` (positive = below cost) | §7.2 |
| Severity | Against **cost**, not price: `CRITICAL` > 10 %, `AT_RISK` ≤ 10 %, `WATCH` −5 %…0 %, else `OK` | §7.3 |
| Target price | `(cost × (1 + margin) + admin_fee/unit) / (1 − variable_rate)` — split numerator on purpose | §7.5 |
| Gross exposure | `Σ max(0, loss)` — a profit elsewhere does not restore the reserve | §7.4 |
| Reserve status | `HEALTHY` > half left, `CAUTION` otherwise (exactly half is CAUTION), `BREACHED` at zero | §8.2 |

### `seed.json` vs `analysis.json`

| File | Size | Used by |
|---|---|---|
| `analysis.json` | ~165 KB | Dashboard pages (full pre-computed payload) |
| `seed.json` | ~10 KB | Upload page only |

`seed.json` carries just what the upload needs to price and rank a new file: the
catalogue (seller SKU → name, cost, category), the per-channel allocations, the
tunables and the fee tables. Shipping the full payload to the upload route would push
the whole dataset over the wire for no reason.

---

## Known limits (inherited, not introduced here)

- **Commission and fees are placeholders.** Real seller contract values are still
  pending; the numbers are not authoritative.
- **Donor surplus is not capped by stock on hand** — the caller owns that check.
- **Tokopedia exists in the data model but not in the fixture.** The upload parser is
  ready for it once a real export shape is known.
- **The fixture is ~100× too sparse for an hourly horizon.** The default is 168 h
  (7 days); see `tech_spec.md` §6.4 and checkpoints CP-36…CP-39.
- Cost source matters. `products_internal_cost.csv` (dated `Current Cost`) and
  `cogs_ledger.csv` (weighted average) disagree on a handful of SKUs, so totals differ
  slightly depending on which file you upload. Both are accepted; the page says which
  one it used.

---

## Project layout

```
web/
├── public/
│   ├── analysis.json          # generated by src/build_analysis.py
│   └── seed.json              # generated by src/build_analysis.py
├── src/
│   ├── app/
│   │   ├── page.tsx           # action list
│   │   ├── brands/page.tsx
│   │   ├── sku/[sku]/page.tsx
│   │   └── upload/page.tsx    # Upload — client component
│   ├── components/
│   │   ├── ui.tsx             # Card, Stat, Caveat, badges
│   │   ├── nav.tsx
│   │   └── horizon-chart.tsx
│   └── lib/
│       ├── analysis.ts        # reads the pre-computed payload
│       ├── seed.ts            # reads the upload seed
│       ├── upload.ts          # metric ports + CSV ingestion (client-side)
│       ├── format.ts          # IDR / number formatting
│       └── types.ts
└── package.json
```

---

## Stack

Next.js 16 (App Router, Turbopack) · React 19 · TypeScript · Tailwind v4.

## Scripts

| Command | Effect |
|---|---|
| `npm --prefix web run dev` | Dev server on :3000 |
| `npm --prefix web run build` | Production build + type check |
| `npm --prefix web run lint` | ESLint |

Regenerate the data after changing any Python source:

```bash
python src/generate.py && python src/build_analysis.py
```
