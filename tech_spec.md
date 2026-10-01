# Technical Specification — Data & Logic

**Companion to:** `Product.md` (the PRD)
**Status:** Draft for prototype
**Version:** 0.1
**Last updated:** 2026-09-30

---

## 1. Purpose

Defines the **data inputs** and the **calculation logic** behind the three core
metrics the prototype must produce:

| # | Logic | Question it answers |
|---|---|---|
| 1 | Run rate → stock-out projection | Which SKU is about to run out on which marketplace? |
| 2 | Under COGS | Which SKU is selling below cost, and how much is it costing us? |
| 3 | Budget safe | How much campaign budget is left after absorbing those losses? |

Everything else in the product (screens, uploads, action lists) is presentation over
these three numbers.

---

## 2. Scope

**In scope:** three marketplaces (Shopee, TikTok Shop, Tokopedia), per-SKU-per-channel
grain, hourly run rate, commission-aware revenue, campaign budget guardrail.

**Out of scope:** demand forecasting beyond trailing velocity, write-back to
marketplaces, ads/ROAS, warehouse transfers.

---

## 3. Data sources

| Source | Provides | Grain | Origin |
|---|---|---|---|
| Marketplace order export | units sold, order date, price, discounts | line item | Shopee / TikTok / Tokopedia seller centre |
| Marketplace inventory export | listing quantity, warehouse split | SKU × warehouse | same |
| Internal stock on hand | physical units available | SKU | WMS or internal sheet |
| Internal cost basis | weighted-average unit cost | SKU × month | `data/internal/cogs_ledger.csv` |
| **Campaign budget** | budget per campaign | campaign × brand | **manual input by the AM** |

All three marketplaces arrive in **incompatible schemas** (see `Product.md` §"why the
two channels don't look alike"). Everything below operates on the canonical model in §4.

---

## 4. Canonical schema

Marketplace exports are parsed into one normalised shape. Field names are fixed here
and referenced by every formula in this document.

### 4.1 `fact_order_line` — one row per order line

| Field | Type | Notes |
|---|---|---|
| `marketplace` | enum | `SHOPEE`, `TIKTOK`, `TOKOPEDIA` |
| `order_id` | string | marketplace-native ID |
| `sku_id` | string | **internal SKU** — resolved from marketplace ID |
| `order_created_at` | datetime | local time, WIB |
| `units` | int | quantity ordered |
| `units_returned` | int | 0 unless returned |
| `units_net` | int | `units - units_returned` |
| `gross_item_value` | decimal | before any discount |
| `seller_discount` | decimal | seller-funded |
| `platform_discount` | decimal | marketplace-funded |
| `buyer_paid_shipping` | decimal | shipping borne by buyer |
| **`net_item_value`** | decimal | **what the buyer paid for the goods** |
| `order_status` | enum | normalised across marketplaces |

`net_item_value = gross_item_value - seller_discount - platform_discount`

**Only orders that count as a sale** are loaded. Cancelled and returned units are
excluded from revenue, run rate and COGS — a returned unit is sellable stock again.

### 4.2 `fact_listing` — one row per SKU per marketplace

| Field | Type | Notes |
|---|---|---|
| `marketplace` | enum | |
| `sku_id` | string | |
| **`allocated_units`** | int | listing quantity — what this channel may sell |
| `stock_on_hand` | int | physical units, SKU-level, shared across channels |
| `unit_cost` | decimal | weighted-average cost for the period |
| `snapshot_at` | datetime | when the export was taken |

**Allocation constraint (from PRD §5):**
`Σ allocated_units across marketplaces ≤ stock_on_hand`

---

## 5. Commission & fees model

This is **new** and it is load-bearing. Without it, "sold value" is what the *buyer*
paid, not what the seller *receives* — which under-reports every loss by the fee
amount.

### 5.1 Formula

```
seller_received = net_item_value
                - (net_item_value × commission_rate)
                - admin_fee_per_order
                - (net_item_value × payment_fee_rate)
                - (net_item_value × affiliate_rate)

seller_received_per_unit = seller_received / units_net
```

### 5.2 Default rates (placeholders — must be confirmed per seller contract)

| Marketplace | `commission_rate` | `admin_fee_per_order` | `payment_fee_rate` | `affiliate_rate` |
|---|---|---|---|---|
| Shopee | 8.0 % | Rp 1,250 | 2.0 % | 0 % |
| TikTok Shop | 6.5 % | Rp 1,000 | 2.0 % | 5.0 % |
| Tokopedia | 6.5 % | Rp 1,250 | 2.0 % | 0 % |

> **TikTok's affiliate rate is the danger.** Affiliate commission on TikTok Shop can
> reach 20 % when a creator drives the sale. At 20 %, a SKU that looks healthy on a
> 12 % margin becomes loss-making. The affiliate rate should ultimately be driven by
> the actual per-order affiliate attribution in the export, not a flat assumption.

**Effective take rate** (Shopee example): `8% + 2% + (1250 / net_item_value)`.
On a Rp 40,000 order that is `10% + 3.1% = 13.1%` — the fixed fee is proportionally
brutal on cheap orders, which is exactly where FMCG staples live.

---

## 6. Logic 1 — Run rate & stock-out projection

### 6.1 Run rate per SKU per marketplace

Measured **per hour**, as specified.

```
observation_hours = (snapshot_at - window_start) / 3600

run_rate_per_hour(sku, marketplace) = Σ units_net over window / observation_hours
```

**Window choice:** trailing **7 days** (`168 hours`) is the recommended default.
It is the shortest window that still carries enough volume to be non-zero for most
SKUs. Trailing 24 hours is available but noisy — one order in a slow hour produces a
rate that is an order of magnitude too high.

Fallback for zero-sale SKUs, in priority order:

1. If `units_net = 0` in the window → fall back to **trailing 30 days**.
2. If still zero → `run_rate_per_hour = 0`, and mark the SKU **dormant**. Never
   divide by it, and never report "stockout in 0 hours".

### 6.2 Stock-out projection

```
hours_to_stockout(sku, marketplace) = allocated_units / run_rate_per_hour
projected_stockout_at               = snapshot_at + hours_to_stockout
```

### 6.3 Alert condition

```
if run_rate_per_hour = 0        → status = DORMANT      (no alert)
else if allocated_units = 0     → status = OUT_OF_STOCK (already gone)
else if hours_to_stockout
        <= alert_horizon_hours  → status = AT_RISK
else                            → status = HEALTHY
```

`alert_horizon_hours` defaults to **1**, per specification.

### 6.4 ⚠️ The 1-hour horizon does not work on this data

This is measured, not estimated. Across the generated dataset:

| Measurement | Value |
|---|---|
| SKU/channel pairs with any sale | 98 |
| **Median run rate per hour** | **0.00417** |
| Fastest observed run rate per hour | **0.0139** |
| Pairs reaching 0.1/hour | **0** |
| Pairs reaching 0.5/hour | **0** |

**Consequence.** `AT_RISK` requires `allocated_units ≤ run_rate_per_hour × 1`. With
the fastest rate at 0.0139/hour, that means `allocated_units ≤ 0` — i.e. the alert can
only fire when stock is **already zero**. The metric degenerates into an
after-the-fact `OUT_OF_STOCK` detector and predicts nothing.

This is not a formula problem. A 1-hour horizon fundamentally requires velocity on the
order of tens of units per hour; this catalogue moves single units per *day*.

**Options** (a decision is needed — see §12 Q1):

| Option | Effect |
|---|---|
| `alert_horizon_hours = 168` (7 days) | Flags a SKU a working week ahead — actionable |
| `alert_horizon_hours = 720` (30 days) | Flags everything; noisy but nothing is missed |
| Adaptive per SKU | `horizon = max(24, cover_days × 0.25)` — reacts in proportion to velocity |
| Raise order volume ~100× | Makes literal hourly meaningful; changes the fixture, not the logic |

The formula is unchanged in every case; only the threshold moves. **Recommendation:**
ship `alert_horizon_hours` as config and default it to `168`, keeping the hourly run
rate exactly as specified.

### 6.5 Reallocation recommendation

Once a channel is `AT_RISK`, the donor search (from PRD §8):

```
target_units  = target_cover_hours × run_rate_per_hour
needed        = max(0, target_units - allocated_units)

donor_surplus = donor.allocated_units
              - (target_cover_hours × donor.run_rate_per_hour)

move = min(needed, donor_surplus)      # only if donor_surplus > 0
```

If `Σ allocations + move > stock_on_hand`, the move is capped — the listing cannot
promise units that do not physically exist.

---

## 7. Logic 2 — Under COGS

### 7.1 Definition

```
total_cogs(sku, marketplace)  = Σ (units_net × unit_cost)
sold_value(sku, marketplace)  = Σ seller_received          # §5, after fees
under_cogs(sku, marketplace)  = total_cogs - sold_value
```

Positive → selling **below** cost. Negative → profitable.

### 7.2 Per unit

```
cogs_per_unit        = total_cogs / Σ units_net
sold_value_per_unit  = sold_value / Σ units_net
under_cogs_per_unit  = cogs_per_unit - sold_value_per_unit
```

### 7.3 Severity bands

Expressed against cost, so a cheap and an expensive SKU are comparable.

| Band | Condition |
|---|---|
| `WATCH` | `-5% < margin_pct ≤ 0%` (thin, not yet losing) |
| `AT_RISK` | `under_cogs_per_unit > 0` and `≤ 10%` of `cogs_per_unit` |
| `CRITICAL` | `under_cogs_per_unit > 10%` of `cogs_per_unit` |

where `margin_pct = (sold_value - total_cogs) / total_cogs`

### 7.4 ⚠️ Gross vs net — an unresolved choice

The formula `under_cogs = total_cogs - sold_value` yields **negative** values for
profitable SKUs. Two readings, and they give very different numbers:

| Mode | Definition | Use when |
|---|---|---|
| **Gross exposure** | `Σ max(0, under_cogs)` — count losses only | Guardrail. A profitable SKU does not refund the budget |
| **Net position** | `Σ under_cogs` — let profits offset losses | Reporting. Honest P&L view of the catalogue |

**Default: gross exposure**, because Logic 3 uses this figure as a budget guardrail
and a profit elsewhere does not restore a depleted budget. Both must be surfaced, and
the choice must be explicit in the UI — a user who assumes net while the system
reports gross will think losses are smaller than they are.

### 7.5 Recommended action

```
target_price = (unit_cost × (1 + target_margin) + admin_fee_per_unit)
               ---------------------------------------------------------
               (1 - commission_rate - payment_fee_rate - affiliate_rate)
```

The denominator grosses the price up for the fees that will be deducted, so the
seller lands on the target margin **after** commission. The numerator adds the
**fixed** admin fee, because a flat per-order charge does not scale with price and
cannot be recovered by a percentage uplift alone. Combining the two into a single
percentage — a tempting simplification — under-prices the target by roughly 10 % on
cheap orders.

Action selection:

| Condition | Action |
|---|---|
| `under_cogs_per_unit > 0`, gap recoverable by pricing | **Raise price to `target_price`** |
| List price is fine but discounts caused it | **Reduce discount depth** |
| `margin_pct ≤ -20%`, or SKU structurally unprofitable on that channel | **Pause the listing** |
| Flagged, loss quantified, brand accepts it | **Keep selling — deliberate loss leader** |

All output is **recommendation only**. The AM decides and executes manually.

---

## 8. Logic 3 — Budget safe

### 8.1 Definition

```
budget_safe      = campaign_budget - total_under_cogs
budget_used_pct  = total_under_cogs / campaign_budget
budget_remaining_pct = 1 - budget_used_pct
```

- `campaign_budget` — **entered manually by the AM**, per campaign.
- `total_under_cogs` — **gross exposure** from §7.4, summed across all SKUs in scope.
- Cumulative across the campaign.

### 8.2 Reading the result

| Condition | Status | Meaning |
|---|---|---|
| `budget_safe > 0.5 × campaign_budget` | `HEALTHY` | Losses are well within the reserve |
| `0 < budget_safe ≤ 0.5 × campaign_budget` | `CAUTION` | Over half the reserve already consumed |
| `budget_safe ≤ 0` | `BREACHED` | Losses have exhausted the campaign reserve |

### 8.3 What the number actually means

Recorded explicitly, because it is easy to misread: **under-COGS loss is not money the
AM spends.** It is margin already forgone on sales that happened. `budget_safe` is
therefore a **reserve / guardrail** — it answers *"are the losses this campaign is
absorbing still small enough that we can keep pushing volume, or do we need to stop
and fix pricing?"*

It is **not** an accounting balance, and it must never be presented as "remaining
spend". Label it *"Campaign reserve"* in the UI, not *"Budget left"*.

---

## 9. Configuration

All thresholds live in config, not code.

```python
# Run rate
RUN_RATE_WINDOW_HOURS   = 168     # trailing 7 days; 24 = noisier, 720 = smoother
RUN_RATE_FALLBACK_HOURS = 720     # for SKUs with no recent sales
ALERT_HORIZON_HOURS     = 1       # per spec; see §6.4 — 168 recommended
TARGET_COVER_HOURS      = 336     # 14 days of cover to reallocate toward

# Under COGS
TARGET_MARGIN           = 0.15
UNDER_COGS_MODE         = "gross" # "gross" | "net"  — see §7.4
CRITICAL_LOSS_PCT       = 0.10

# Commission (per contract — placeholders only)
COMMISSION_RATES = {
    "SHOPEE":    dict(commission=0.080, admin_fee=1_250, payment=0.020, affiliate=0.00),
    "TIKTOK":    dict(commission=0.065, admin_fee=1_000, payment=0.020, affiliate=0.05),
    "TOKOPEDIA": dict(commission=0.065, admin_fee=1_250, payment=0.020, affiliate=0.00),
}
```

---

## 10. Worked examples

> **Illustrative.** Figures below demonstrate the arithmetic. They are **not** drawn
> from the current dataset — see §11 for why.

### Run rate & stock-out

```
SKU-0007 / Shopee  : allocated = 12,  units_net(7d) = 9
observation_hours  = 168
run_rate_per_hour  = 9 / 168              = 0.0536 / hour
hours_to_stockout  = 12 / 0.0536          = 224 hours ≈ 9.3 days
target_units       = 336 × 0.0536         = 18
needed             = 18 - 12              = 6 units

SKU-0007 / TikTok  : allocated = 130, units_net(7d) = 2 → 0.0119/hour
donor_surplus      = 130 - (336 × 0.0119) = 126 units

move               = min(6, 126)          = 6 units  TikTok → Shopee
```

Note the asymmetry: TikTok's cover is 10,920 hours (~455 days), so it can easily
spare 6 units. A channel with low velocity is almost always the donor.

### Under COGS

```
SKU-0022 / Shopee
  units_net              = 34
  net_item_value         = Rp 12,240 / unit   (what the buyer paid)
  commission  8%         = Rp   979
  admin fee              = Rp 1,250 / 34 = Rp 37
  payment fee 2%         = Rp   245
  affiliate  0%          = Rp     0
  ─────────────────────────────────────────
  seller_received/unit   = Rp 10,979
  cogs_per_unit          = Rp 12,050

under_cogs_per_unit = 12,050 - 10,979 = Rp 1,071   → AT_RISK (8.9% of cost)
total_under_cogs    = 1,071 × 34      = Rp 36,414

target_price = (12,050 × 1.15 + 37) / (1 - 0.08 - 0.02 - 0.00)
             = 13,895 / 0.90
             = Rp 15,438
```

*That target price is ~26 % above the current price — a real-world reminder that once
commission is included, recovering a sub-cost SKU often means a price the market will
not accept, which is why "pause the listing" exists.*

### Budget safe

```
campaign_budget        = Rp 50,000,000
total_under_cogs       = Rp 18,400,000   (gross exposure, all SKUs in campaign)
budget_safe            = 50,000,000 - 18,400,000 = Rp 31,600,000
budget_remaining_pct   = 63.2%           → HEALTHY
```

---

## 11. Data gaps & risks

### 11.1 The current dataset cannot exercise Logics 1 or 2

| Gap | Evidence | Impact |
|---|---|---|
| **Run rate too low for hourly alerts** | Fastest SKU = 0.0139 units/hour; 0 pairs ≥ 0.1/hour | Alert can only fire at zero stock (§6.4) |
| **Almost no below-cost SKUs** | 3 of 96 margin rows below cost, total loss **Rp 2,000** | Cannot validate the under-COGS detector |
| **Commission not modelled** | `product_margin.csv` uses `net_item_value` only | Losses under-reported by ~10–13 % of revenue |
| **Tokopedia absent** | Generator emits Shopee + TikTok only | Cannot test 3-way allocation |

**Root cause of the below-cost gap:** cost is 62–80 % of base price while marketplace
discounts rarely exceed 35 %, so margin almost never turns negative. Adding commission
(§5) will push the 10 `WATCH` rows over the line, but the dataset still needs
deliberate below-cost cases to be a real test.

### 11.2 Risks

| Risk | Mitigation |
|---|---|
| Commission rates wrong per contract → wrong loss figures | Make rates per-seller config, never global constants |
| Trailing velocity misreads a campaign spike as permanent | Window config; note that a 9.9 spike inflates 7-day rates |
| `gross` vs `net` misunderstanding changes the story | Surface both, label the mode in the UI |
| Hourly rate on sparse data produces infinite/zero division | Dormant status; never divide by zero (§6.1) |
| Budget figure is manual → typo scales the whole guardrail | Validate input range; show budget prominently alongside the result |

---

## 12. Open questions

1. **Alert horizon** — accept `168` hours as the default (recommendation), or keep the
   literal `1` hour knowing it only fires at zero stock? *This is the first decision
   needed; it determines whether Logic 1 predicts or merely reports.*
2. **Gross vs net under-COGS** — confirm gross exposure as the default for Logic 3.
3. **Affiliate attribution** — flat 5 % for TikTok, or read actual per-order affiliate
   commission from the export? Flat materially misstates creator-driven sales.
4. **Run rate window** — is 7 days right, or should it differ for fast vs slow movers?
5. **Zero-sale SKUs** — should a dormant SKU be flagged at all, or hidden by default?
6. **Campaign budget scope** — per campaign, per brand, or both? Does one campaign
   spanning several brands share one reserve?
7. **Cost freshness** — when the supplier reprices, how quickly does that update the
   cost basis used in Logic 2?

---

## 13. Relationship to existing code

| Spec element | Current implementation | Status |
|---|---|---|
| `fact_order_line` | `data/{shopee,tiktok}/*_orders_*.csv` | ✅ exists (2 of 3 channels) |
| `fact_listing` | `*_inventory_export.csv` | ✅ exists |
| `unit_cost` | `data/internal/cogs_ledger.csv` | ✅ exists |
| Commission model | `src/metrics.py` §5 functions | ✅ implemented, CP-15–19 |
| Logic 1 — run rate | `src/metrics.py` §6 functions | ✅ implemented, CP-01–14 |
| Logic 2 — under COGS | `src/metrics.py` §7 functions | ✅ implemented, CP-20–28 |
| Logic 3 — budget safe | `src/metrics.py` §8 functions | ✅ implemented, CP-29–35 |
| Tokopedia | — | ❌ not implemented |

`src/generate.py` remains the fixture generator. Adding the commission model to it is
the single change that makes Logics 2 and 3 produce truthful numbers against real
marketplace exports.

---

## 14. Verification

Every formula in this document is pinned by a checkpoint in `checkpoint.json`, with a
runnable implementation in `src/metrics.py` and a test per clause.

```powershell
python tests/run_checkpoints.py                    # all 39
python tests/run_checkpoints.py --category under_cogs
python tests/run_checkpoints.py --id CP-15 CP-36
python tests/run_checkpoints.py --no-write         # don't update the manifest
```

The runner exits non-zero on failure and writes `status`, `duration_ms` and `message`
back into each checkpoint entry.

### What the checkpoints cover

| Category | Count | Guards |
|---|---|---|
| `run_rate` | 14 | §6 — rate, projection, four-way status, reallocation |
| `commission` | 5 | §5 — receipt, variable rate, fixed-fee behaviour |
| `under_cogs` | 9 | §7 — per unit, total, severity bands, target price, gross vs net |
| `budget_safe` | 7 | §8 — reserve arithmetic and band boundaries |
| `known_limits` | 4 | §6.4 — the measured 1-hour limitation, pinned |
| **Total** | **39** | |

### Mutation testing

A test that cannot fail proves nothing, so the suite was validated by deliberately
breaking `src/metrics.py` and confirming the checkpoints noticed:

| Mutation | Detected by |
|---|---|
| CRITICAL band 10 % → 50 % | CP-23 |
| Admin fee not spread across units | CP-15, CP-20, CP-21 |
| Budget boundary `>` → `>=` | CP-34 |
| Donor surplus cap removed | CP-12 |
| WATCH band removed | CP-24 |
| DORMANT check removed | CP-10 |
| **Default horizon 1 h → 168 h** | **CP-39** (added *because* it initially escaped) |

The last one is the instructive case. Every other checkpoint passed the horizon
explicitly, so changing the *default* broke nothing — meaning the shipped default could
drift away from §9 without warning. CP-39 exists to pin it.

### Two bugs the checkpoints caught during implementation

1. **Receipt grain error.** `seller_received_per_unit` treated `net_item_value` as an
   order total rather than a **per-unit** price, producing Rp 287 instead of
   Rp 10,979. The parameter is now named `net_item_value_per_unit` so the mistake
   cannot recur silently; CP-15 is the guard.

2. **Target price arithmetic.** The first draft of this spec stated the worked example
   as Rp 15,438.889. The correct value is **Rp 15,438.0719** — the fixed admin fee had
   been folded in as if it scaled with price. Corrected in §10.