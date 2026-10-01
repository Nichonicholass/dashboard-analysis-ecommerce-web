# Product Requirements Document — Marketplace Allocation & Margin Advisor

**Status:** Draft for prototype
**Version:** 0.1
**Owner:** Nicholas
**Last updated:** 2026-09-30

**See also:** `tech_spec.md` — data model, formulas and thresholds for the three core
metrics (run rate, under COGS, budget safe).

---

## 1. One-liner

A dashboard that tells an Account Manager which SKUs are about to run out on which
marketplace, which SKUs are selling below cost, and what to do about it.

**Advisory only.** The system recommends; the AM decides and executes manually.

---

## 2. Problem

An Account Manager handles several brands across three marketplaces
(**Shopee, TikTok Shop, Tokopedia**). Two things routinely go wrong, and today
both are found by hand.

### Problem 1 — Stock sits in the wrong marketplace

Seller stock is **not mirrored** across channels. The same physical SKU is listed
in all three, but each marketplace is only given an *allocated quantity* it may
sell. That allocation is how the AM controls where stock actually moves.

Today the allocation drifts: one channel runs dry while another holds weeks of
cover. The AM only notices when a listing goes to zero — by which point sales are
already lost and the marketplace's ranking signal has taken a hit.

### Problem 2 — SKUs sell below cost

Marketplace discounts, vouchers and coin programmes stack up until the amount the
seller actually receives falls below the cost of the goods. Nothing in the
marketplace UI surfaces this. It is only visible by downloading an order export
and cross-referencing it against an internal cost list.

### Why it hurts

| Cost of today's process | Detail |
|---|---|
| Hours of manual work | Download per marketplace, per brand, then reconcile in spreadsheets |
| Catalogue blind spots | Only the biggest SKUs get reviewed; small ones leak margin unnoticed |
| Late detection | Problems are caught after the stock-out or after the discount period ends |
| No audit trail | Decisions are made in chat threads, not against a recorded recommendation |

---

## 3. Users

**Primary — Account Manager (AM).**
Owns the commercial relationship with one or more brands. Today: downloads
exports, builds pivot tables, decides allocations, updates each seller centre by
hand. Needs a single view and a concrete action list.

**Secondary — Brand / Category Lead.**
Needs to see margin health across the brands they are accountable for, and to
know whether the AM is acting on the flagged risks.

**Out of scope for now — Finance.**
Will eventually want the same COGS data for reporting. Not a driver for v1.

---

## 4. Goals & non-goals

### Goals

1. Show every at-risk SKU — stock-out risk and under-cost selling — **in one view**.
2. Produce a **concrete action list**, not just numbers: move *this many* units from
   channel A to channel B; raise *this* price to *that*.
3. Cut time-to-find-issues from **hours to minutes**.
4. Prove the data pipeline end to end: upload → parse → normalise → analyse → advise.

### Non-goals (v1)

- ❌ Writing back to any marketplace. No auto price changes, no auto stock updates.
- ❌ Live API integration. Input is manually uploaded exports.
- ❌ Warehouse-to-warehouse transfers. See §5.
- ❌ Demand forecasting beyond a simple trailing velocity.
- ❌ Ads spend or ROAS analysis.

---

## 5. Core concept — the allocation model

This is the heart of the product, and the thing to get right before building
anything else.

```
                    Physical stock on hand  (one pool, from internal data)
                                  │
                                  │  AM decides how to split it
                                  ▼
        ┌──────────────┬──────────────┬──────────────┐
        │   Shopee     │ TikTok Shop  │  Tokopedia   │
        │  allocated   │  allocated   │  allocated   │
        │   = 60       │   = 130      │   = 0        │
        └──────────────┴──────────────┴──────────────┘
```

- One physical pool per SKU.
- Each marketplace holds a **listing quantity** — the units it is allowed to sell.
- Allocations may sum to **less than** stock on hand (deliberate buffer), and a channel
  may be allocated **zero** on purpose.
- "Migrating stock" means **reallocating listing quantity**: reduce the donor channel,
  raise the recipient. No goods physically move.

**Constraint the system must respect:** `Σ allocations ≤ stock on hand`.

### Per-channel metrics that drive every recommendation

| Metric | Meaning |
|---|---|
| `allocated` | Units the channel may currently sell |
| `velocity` | Units sold per day on that channel, trailing window |
| `cover_days` | `allocated ÷ velocity` — how long until that channel runs dry |
| `donor_surplus` | Units a channel can give up and still clear its own target cover |

---

## 6. Feature scope

### 6.1 Upload & ingest

The AM uploads the CSV exports straight from each marketplace's seller centre.

- Drag-and-drop, one or more files, any marketplace.
- Upload is the trigger — no scheduler, no cron.
- The system identifies marketplace and report type from the file itself.
- Every upload is recorded with a timestamp so the dashboard can state
  *"data as of …"* and flag stale input.
- Parse failures must be shown per-file and per-row, never silently swallowed.

### 6.2 Problem 1 — Stock allocation & stock-out risk

**Detects:** channels whose `cover_days` is below threshold, and SKUs already at zero
on a channel with stock available elsewhere.

**Recommends:** a concrete reallocation.

> *Illustrative example*
> SKU-0007 (Susu UHT Cokelat 1 L) — Shopee has 2.1 days cover, TikTok has 24 days.
> Move **40 units** from TikTok Shop → Shopee. Leaves both at ~12 days cover.

**Actions offered per SKU:**

| Action | When |
|---|---|
| Reallocate units A → B | At-risk channel, and a donor with spare surplus exists |
| Increase allocation | At-risk channel, and total stock on hand is sufficient |
| No change — leave it | At-risk, but no donor and no spare stock. Say so explicitly |
| Zero out a channel | Channel is unprofitable and its stock is better used elsewhere |

### 6.3 Problem 2 — Selling below COGS

**Detects:** line items where the amount the seller receives per unit is below the
weighted-average cost of that unit.

**Recommends:**

| Action | When |
|---|---|
| Raise price to hit target margin | Gap is recoverable through pricing |
| Reduce discount depth | The list price is fine; the discounts are the problem |
| Pause the listing | Gap is severe, or the SKU is structurally unprofitable on that channel |
| Keep selling — deliberate loss leader | Flagged, with the loss quantified, so the decision is explicit |

**Example:**

> *Illustrative example*
> SKU-0022 (Cokelat Batang 65 gr) on Shopee — receives Rp 11,300/unit, cost Rp 12,050.
> **Loss of Rp 750 per unit** across 34 units = **Rp 25,500 lost**.
> Raise price to Rp 13,900 to reach a 15 % margin, or pause the listing.

Severity bands: **Watch** (margin 0–5 %), **At risk** (margin negative by <10 %),
**Critical** (margin negative by ≥10 %).

### 6.4 The unified action list

The single most important screen. One row per SKU per channel, both problem types
merged, sorted by money at stake. Each row carries: the problem, the recommended
action, the exact number, and the estimated value protected or recovered.

---

## 7. Screens

| # | Screen | Purpose |
|---|---|---|
| 1 | **Upload** | Drop marketplace exports, see parse status and data freshness |
| 2 | **Action List** | Every at-risk SKU, one row each, with the recommended action |
| 3 | **SKU Detail** | One SKU: allocation per channel, cover days, margin, cost history, decision log |
| 4 | **Brand Overview** | Rollup across the AM's brands — how much is at risk, where |

Deliberately four screens. Resist adding more until the action list proves itself.

---

## 8. Recommendation logic

Simple, explainable rules. Every recommendation must show its arithmetic — an AM
will not act on a number they cannot audit.

### Stock-out risk

```
cover_days         = allocated ÷ velocity
at_risk            = cover_days ≤ 7
target_units       = target_cover_days × velocity
needed             = target_units − allocated
donor_surplus      = donor.allocated − (target_cover_days × donor.velocity)
move               = min(needed, donor_surplus)
```

Only recommend a move when `donor_surplus > 0`. Otherwise say *"no donor available"*.

### Under-COGS

```
unit_received      = net amount the seller receives per unit, after discounts
under_cost         = unit_received < unit_cost
target_price       = unit_cost × (1 + target_margin)
loss               = (unit_cost − unit_received) × units_sold
```

Thresholds (`target_cover_days`, `target_margin`, velocity window) must live in a
config file, not hard-coded.

---

## 9. Success metrics

| Metric | Baseline (today) | Target |
|---|---|---|
| Time to identify at-risk SKUs | Hours of manual spreadsheet work | Under 5 minutes |
| At-risk SKUs surfaced | Only the largest, ad hoc | 100 % of catalogue |
| Action list quality | None — analysis only | Concrete, quantified, per SKU |
| Auditability | Chat threads | Every recommendation traceable to source rows |
| Stock-out events | Detected after the fact | Detected ≥ 7 days ahead |

---

## 10. Data requirements

| Input | Source | Have it? |
|---|---|---|
| Orders per marketplace | Seller-centre export | ✅ Shopee, TikTok in generator |
| Listing quantity per channel | Seller-centre export | ✅ Shopee, TikTok |
| Product / SKU mapping | Internal master | ✅ |
| Stock on hand | Internal WMS or spreadsheet | ✅ modelled in `data/internal/` |
| Weighted-average unit cost | Internal costing | ✅ `cogs_ledger.csv` |
| **Tokopedia orders + inventory** | Seller-centre export | ❌ **not generated yet** |
| **Platform commission / fees** | Marketplace settlement report | ❌ **not modelled** |

### Three gaps to close before the prototype is honest

1. **Tokopedia is not in the data generator.** It currently emits Shopee and TikTok
   only. A three-marketplace allocation tool needs the third channel's data, or the
   first build will quietly be a two-channel tool.

2. **Platform commission is not modelled.** Today's `product_margin.csv` uses *net
   item value* — what the buyer paid. What the seller actually receives is that
   figure **minus marketplace commission and admin fees**, which typically run
   several percent. Without it, "selling below COGS" **under-reports the problem**:
   some SKUs that look marginally profitable are already loss-making. This is the
   single highest-value missing input, because it changes the answer to Problem 2.

3. **The current test bed barely contains Problem 2.** Measured against the generated
   data: of 96 SKU/channel margin rows, only **3** sit below cost, for a combined
   loss of **Rp 2,000**. That is far too small to validate a below-cost detector
   against. The cause is structural — cost is set at 62–80 % of list price while
   marketplace discounts rarely cut deeper than 35 %, so the margin almost never
   goes negative.

   **Consequence:** Phase 2 of the rollout cannot be honestly demoed on the current
   fixture. Either commission must be added (gap 2, which shrinks margins toward
   reality) or the generator must be tuned to produce deliberate, meaningful
   below-cost cases. Otherwise Problem 2 will appear solved when it has simply
   never been tested.

---

## 11. Open questions

1. **Oversell tolerance.** Should `Σ allocations` be allowed to exceed stock on hand
   to chase demand, accepting occasional cancellations? Or strictly ≤?
2. **Velocity window.** Trailing 7 days reacts fast but is noisy; 30 days is stable
   but slow. Different windows for fast vs slow movers?
3. **Who owns the target margin?** Set by brand, by category, or per SKU by the AM?
4. **Multi-brand isolation.** Should an AM see only their assigned brands, or all?
5. **Does "pause a listing" need brand sign-off?** If yes, the action list needs an
   approval state, which is a bigger build than v1 assumes.
6. **Cost freshness.** If the supplier reprices, who updates the cost basis, and how
   quickly does that flow through to under-COGS detection?

---

## 12. Rollout

| Phase | Deliverable | Proves |
|---|---|---|
| **1** | Upload + parse + normalise all 3 marketplaces | The pipeline works end to end |
| **2** | Action list with both problem types | The analysis is genuinely useful |
| **3** | Reallocation recommendations with quantities | The hard problem is solved |
| **4** | Decision log + outcome tracking | We can prove it saved money |

Phase 1 is infrastructure and is not demoable. Phase 2 is the first thing worth
showing a stakeholder.

---

## 13. Appendix — relationship to the existing data generator

`src/generate.py` already produces the marketplace order and inventory exports plus
the internal costing layer. That dataset is the **fixture** for this prototype:

| Generator output | Used for |
|---|---|
| `data/{shopee,tiktok}/*_orders_*.csv` | Velocity, units sold, under-COGS detection |
| `data/{shopee,tiktok}/*_inventory_export.csv` | Current listing quantity per channel |
| `data/internal/cogs_ledger.csv` | Weighted-average unit cost |
| `data/internal/product_margin.csv` | Starting point for the margin view |

It already contains the failure modes this product is meant to catch: channels
holding stock while others go dry, SKUs priced near or below cost, and supplier cost
changes. That makes it a usable test bed for **Problem 1** — but not yet for
Problem 2, for the reasons in §10.