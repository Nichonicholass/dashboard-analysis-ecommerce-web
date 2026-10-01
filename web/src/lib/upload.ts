/**
 * Client-side ingestion + analysis for manually uploaded seller-centre exports.
 *
 * WHY THIS EXISTS
 * ---------------
 * `analysis.json` is pre-computed by `python src/build_analysis.py`. That works for
 * the bundled fixture, but it cannot work for a file the Python build never saw — an
 * AM dropping today's export expects a result now, and there is no server in this
 * prototype. So the Upload page recomputes in the browser.
 *
 * WHAT IT MIRRORS
 * ---------------
 * Every formula here is a port of `src/metrics.py` (the module protected by the 39
 * checkpoints) and of the ingestion rules in `src/build_analysis.py`. The same port
 * already exists for the server-less page in `simple/_skrip.js`. Keep all three in
 * step: same bands, same fee split, same window/fallback rule.
 *
 * Deliberate scope limit: this computes on the AM's uploaded snapshot only. It does
 * not merge uploads into the dashboard dataset, and it writes nothing back.
 */

export type Channel = "Shopee" | "TikTok Shop";
export type StockoutStatus = "AT_RISK" | "OUT_OF_STOCK" | "HEALTHY" | "DORMANT";
export type Severity = "CRITICAL" | "AT_RISK" | "WATCH" | "OK";
export type BudgetStatus = "HEALTHY" | "CAUTION" | "BREACHED";

/** Which of the two upload zones a file belongs to. */
export type UploadZone = "internal" | "sales";

export interface Fees {
  commission: number;
  admin_fee: number;
  payment: number;
  affiliate: number;
}

export interface SeedProduct {
  key: string; // seller SKU — the only key marketplace exports carry
  name: string;
  cost: number;
  category: string;
}

export interface SeedListing {
  s: string; // seller SKU
  c: Channel;
  a: number; // allocated listing quantity
}

export interface Seed {
  as_of: string;
  config: {
    run_rate_window_hours: number;
    run_rate_fallback_hours: number;
    alert_horizon_hours: number;
    target_cover_hours: number;
    target_margin: number;
    campaign_budget: number;
  };
  fees: Record<string, Fees>;
  products: SeedProduct[];
  listings: SeedListing[];
}

/** A file that has already been read into memory by the page. */
export interface UploadedText {
  name: string;
  text: string;
}

/** One row of the upload's result table — shaped like the dashboard's SkuChannelRow. */
export interface UploadRow {
  sku: string; // seller SKU (what the AM sees in the export)
  name: string;
  category: string;
  channel: Channel;
  allocated: number;
  unit_cost: number;
  sold_units_window: number;
  sold_units_fallback: number;
  sold_units_period: number;
  net_item_value_per_unit: number;
  revenue: number;
  run_rate_per_hour: number;
  hours_to_stockout: number | null;
  stockout_status: StockoutStatus;
  cover_days: number | null;
  under_cogs_per_unit: number;
  under_cogs_total: number;
  severity: Severity;
  seller_received_per_unit: number;
  recommended_price: number;
}

export interface UploadFileReport {
  name: string;
  zone: UploadZone;
  kind: "internal" | "sales" | "inventory" | "unknown";
  marketplace: Channel | null;
  ok: boolean;
  message: string;
  rows: number; // rows that survived into the analysis
}

export interface UploadSummary {
  rows: number;
  below_cost: number;
  critical: number;
  out_of_stock: number;
  at_risk: number;
  gross_exposure: number;
  net_position: number;
  campaign_budget: number;
  budget_safe: number;
  budget_remaining_pct: number;
  budget_status: BudgetStatus;
  reallocation_count: number;
}

export interface UploadResult {
  files: UploadFileReport[];
  catalogue_size: number;
  used_seed_catalogue: boolean;
  sales_lines: number;
  listing_pairs: number;
  orphan_skus: string[];
  rows: UploadRow[];
  summary: UploadSummary;
}

/* -------------------------------------------------------------------------- */
/* Indonesian labels — the Upload page is Bahasa Indonesia.                    */
/* -------------------------------------------------------------------------- */
export const LABEL_STOKOUT: Record<StockoutStatus, string> = {
  OUT_OF_STOCK: "Habis",
  AT_RISK: "Hampir habis",
  HEALTHY: "Aman",
  DORMANT: "Tidak terjual",
};

export const LABEL_SEVERITY: Record<Severity, string> = {
  CRITICAL: "KRITIS",
  AT_RISK: "BERISIKO",
  WATCH: "PANTAU",
  OK: "PROFIT",
};

export const LABEL_BUDGET: Record<BudgetStatus, string> = {
  HEALTHY: "AMAN",
  CAUTION: "PERHATIAN",
  BREACHED: "TERLAMPAUI",
};

/* -------------------------------------------------------------------------- */
/* §5-§8 — formula ports of src/metrics.py                                     */
/* -------------------------------------------------------------------------- */

/** Percentage-only fees. The admin fee is fixed per order, never a rate (§5.1). */
function variableRate(f: Fees): number {
  return f.commission + f.payment + f.affiliate;
}

/** What the seller keeps per unit, after fees. `price` is per unit, not a line total. */
export function sellerReceivedPerUnit(price: number, units: number, f: Fees): number {
  if (units <= 0) return 0;
  return price * (1 - variableRate(f)) - f.admin_fee / units;
}

/** Units per hour over the observation window (§6.1). */
export function runRatePerHour(units: number, hours: number): number {
  if (hours <= 0) return 0;
  return units / hours;
}

/** Hours of cover left. Null for a dormant SKU — "time to empty" is meaningless. */
export function hoursToStockout(allocated: number, rate: number): number | null {
  if (rate <= 0) return null;
  return allocated / rate;
}

/** Order matters: dormant is checked before out-of-stock (§6.3). */
export function classifyStockout(
  allocated: number,
  rate: number,
  horizonHours: number,
): StockoutStatus {
  if (rate <= 0) return "DORMANT";
  if (allocated <= 0) return "OUT_OF_STOCK";
  const cover = hoursToStockout(allocated, rate);
  return cover !== null && cover <= horizonHours ? "AT_RISK" : "HEALTHY";
}

export function donorSurplus(allocated: number, rate: number, targetCoverHours: number): number {
  return allocated - targetCoverHours * rate;
}

/** How many units a donor can give up and still hold its own target cover (§6.5). */
export function recommendReallocation(
  needed: number,
  donorAllocated: number,
  donorRate: number,
  targetCoverHours: number,
): number | null {
  const surplus = donorSurplus(donorAllocated, donorRate, targetCoverHours);
  if (surplus <= 0) return null;
  const move = Math.min(needed, surplus);
  return move <= 0 ? null : Math.floor(move);
}

/** Loss per unit. Positive means selling below cost (§7.2). */
export function underCogsPerUnit(cost: number, price: number, units: number, f: Fees): number {
  return cost - sellerReceivedPerUnit(price, units, f);
}

/** Severity bands are relative to cost, not price, so cheap and dear items compare (§7.3). */
export function classifySeverity(lossPerUnit: number, cost: number): Severity {
  if (cost <= 0) return "OK";
  const pct = lossPerUnit / cost;
  if (lossPerUnit > 0) return pct > 0.1 ? "CRITICAL" : "AT_RISK";
  return pct > -0.05 ? "WATCH" : "OK";
}

/**
 * Price that clears cost, target margin and every fee (§7.5).
 *
 * The numerator is split on purpose: percentage fees scale with price so they are a
 * gross-up in the denominator, while the admin fee does not scale with price so it is
 * added per unit in the numerator.
 */
export function targetPrice(
  cost: number,
  margin: number,
  units: number,
  f: Fees,
): number {
  const rate = variableRate(f);
  if (rate >= 1 || units <= 0) return 0;
  return (cost * (1 + margin) + f.admin_fee / units) / (1 - rate);
}

/** Losses only — a profit elsewhere does not restore a depleted reserve (§7.4). */
export function grossExposure(values: number[]): number {
  return values.reduce((total, v) => total + (v > 0 ? v : 0), 0);
}

/** Reserve health (§8.2). Half remaining exactly is CAUTION, not HEALTHY. */
export function budgetStatus(budget: number, exposure: number): BudgetStatus {
  const remaining = budget - exposure;
  if (remaining <= 0) return "BREACHED";
  return remaining > 0.5 * budget ? "HEALTHY" : "CAUTION";
}

/* -------------------------------------------------------------------------- */
/* CSV reading                                                                 */
/* -------------------------------------------------------------------------- */

/** RFC-4180-ish reader: handles BOM, quoted fields and doubled quotes. */
export function parseCsv(text: string): Record<string, string>[] {
  const clean = text.replace(/^\uFEFF/, "");
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;

  for (let i = 0; i < clean.length; i++) {
    const c = clean[i];
    if (inQuotes) {
      if (c === '"') {
        if (clean[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cell += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(cell);
      cell = "";
    } else if (c === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (c !== "\r") {
      cell += c;
    }
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  if (!rows.length) return [];

  const header = rows[0].map((h) => h.trim());
  return rows
    .slice(1)
    .filter((r) => r.length > 1 || (r[0] && r[0].trim() !== ""))
    .map((r) => {
      const record: Record<string, string> = {};
      header.forEach((h, i) => {
        record[h] = (r[i] || "").trim();
      });
      return record;
    });
}

function num(value: string | undefined): number {
  if (!value) return 0;
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

/** Marketplace timestamps are WIB ("YYYY-MM-DD HH:MM:SS"); Safari wants ISO. */
function parseStamp(value: string | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(`${value.replace(" ", "T")}+07:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function has(headers: string[], key: string): boolean {
  return headers.indexOf(key) !== -1;
}

/**
 * Identify a file from its columns, never its filename.
 *
 * Inventory columns are checked first: an inventory export shares no column names
 * with an order export, and confusing the two silently zeroes every allocation.
 */
export function recognise(headers: string[]): {
  marketplace: Channel | null;
  kind: "sales" | "inventory";
} {
  const inventory = has(headers, "Available Inventory") || has(headers, "Reserved Stock") || has(headers, "Stock") || has(headers, "Inventory");
  let marketplace: Channel | null = null;
  if (has(headers, "Order Substatus") || has(headers, "SKU ID") || has(headers, "Available Inventory") || has(headers, "Inventory")) {
    marketplace = "TikTok Shop";
  } else if (has(headers, "SKU Reference No.") || has(headers, "Deal Price") || has(headers, "Parent SKU")) {
    marketplace = "Shopee";
  }
  return { marketplace, kind: inventory ? "inventory" : "sales" };
}

/** The internal costing exports carry a cost column and none of the order columns. */
function isInternal(headers: string[]): boolean {
  if (!has(headers, "Seller SKU") && !has(headers, "SKU ID")) return false;
  if (has(headers, "Deal Price") || has(headers, "Available Inventory") || has(headers, "Inventory")) return false;
  return (
    has(headers, "Current Cost") ||
    has(headers, "Unit Cost (WA)") ||
    has(headers, "Standard Cost") ||
    has(headers, "Cost Price")
  );
}

/** Cost column priority: the ledger's weighted average beats the display-only price. */
function costOf(record: Record<string, string>): number {
  for (const key of ["Current Cost", "Unit Cost (WA)", "Standard Cost", "Cost Price"]) {
    if (record[key] !== undefined && record[key] !== "") return num(record[key]);
  }
  return NaN;
}

/* -------------------------------------------------------------------------- */
/* Ingestion                                                                   */
/* -------------------------------------------------------------------------- */

interface CatalogueEntry {
  key: string;
  name: string;
  category: string;
  cost: number;
}

interface SaleLine {
  channel: Channel;
  sku: string; // seller SKU
  units: number;
  pricePerUnit: number;
  at: Date | null;
}

const SOLD_STATUS: Record<Channel, string[]> = {
  Shopee: ["Completed", "Shipped"],
  "TikTok Shop": ["Completed", "In Transit"],
};

function readInternal(files: UploadedText[]): {
  catalogue: Map<string, CatalogueEntry>;
  reports: UploadFileReport[];
} {
  const catalogue = new Map<string, CatalogueEntry>();
  const latestMonth = new Map<string, string>();
  const reports: UploadFileReport[] = [];

  for (const file of files) {
    const records = parseCsv(file.text);
    const headers = records.length ? Object.keys(records[0]) : [];
    if (!records.length || !isInternal(headers)) {
      reports.push({
        name: file.name,
        zone: "internal",
        kind: "unknown",
        marketplace: null,
        ok: false,
        message: "Kolom HPP tidak dikenali",
        rows: 0,
      });
      continue;
    }

    let count = 0;
    const seenInFile = new Set<string>();
    for (const record of records) {
      const sellerSku = (record["Seller SKU"] || "").trim();
      if (!sellerSku) continue;
      const cost = costOf(record);
      if (!Number.isFinite(cost)) continue;

      // The COGS ledger has one row per month; keep the most recent.
      const month = record["Month"];
      if (month) {
        const seen = latestMonth.get(sellerSku);
        if (seen && seen >= month) continue;
        latestMonth.set(sellerSku, month);
      }

      catalogue.set(sellerSku, {
        key: sellerSku,
        name: record["Product Name"] || sellerSku,
        category: record["Category"] || "—",
        cost,
      });
      seenInFile.add(sellerSku);
      count = seenInFile.size;
    }

    reports.push({
      name: file.name,
      zone: "internal",
      kind: "internal",
      marketplace: null,
      ok: true,
      message: `${count} SKU berkode HPP`,
      rows: count,
    });
  }

  return { catalogue, reports };
}

function readMarketplace(files: UploadedText[]): {
  sales: SaleLine[];
  listings: Map<string, number>; // "channel|sellerSku" -> allocated units
  reports: UploadFileReport[];
} {
  const sales: SaleLine[] = [];
  const listings = new Map<string, number>();
  const reports: UploadFileReport[] = [];

  for (const file of files) {
    const records = parseCsv(file.text);
    const headers = records.length ? Object.keys(records[0]) : [];
    const { marketplace, kind } = recognise(headers);

    if (!records.length || !marketplace) {
      reports.push({
        name: file.name,
        zone: "sales",
        kind: "unknown",
        marketplace: null,
        ok: false,
        message: "Kolom marketplace tidak dikenali",
        rows: 0,
      });
      continue;
    }

    let rows = 0;

    if (kind === "inventory") {
      for (const record of records) {
        // Shopee keys inventory on "Parent SKU"; TikTok on "Seller SKU".
        const sellerSku = (record["Parent SKU"] || record["Seller SKU"] || "").trim();
        if (!sellerSku) continue;
        const allocated =
          record["Available Inventory"] !== undefined && record["Available Inventory"] !== ""
            ? num(record["Available Inventory"])
            : (record["Inventory"] !== undefined && record["Inventory"] !== ""
                ? num(record["Inventory"])
                : num(record["Stock"])) - num(record["Reserved Stock"]);
        if (allocated < 0) continue;
        // TikTok spreads one listing across warehouses, so sum the rows.
        const key = `${marketplace}|${sellerSku}`;
        listings.set(key, (listings.get(key) || 0) + allocated);
        rows++;
      }
    } else {
      const allowed = SOLD_STATUS[marketplace];
      for (const record of records) {
        const sellerSku = (record["SKU Reference No."] || record["Seller SKU"] || "").trim();
        if (!sellerSku) continue;
        const status = record["Order Status"] || "";
        if (allowed.indexOf(status) === -1) continue;

        const quantity = num(record["Quantity"]);
        const returned = num(record["Returned Quantity"]);
        const units = Math.max(0, quantity - returned);
        if (units <= 0) continue;

        let pricePerUnit: number;
        if (marketplace === "Shopee") {
          // Deal Price is post-seller-discount, pre-platform-discount.
          pricePerUnit = num(record["Deal Price"]) - (quantity ? num(record["Shopee Discount"]) / quantity : 0);
        } else {
          pricePerUnit =
            num(record["Sku Unit Original Price"]) -
            (quantity ? num(record["Sku Platform Discount"]) / quantity : 0) -
            (quantity ? num(record["Sku Seller Discount"]) / quantity : 0);
        }

        sales.push({
          channel: marketplace,
          sku: sellerSku,
          units,
          pricePerUnit,
          at: parseStamp(record["Create Time"] || record["Created Time"]),
        });
        rows++;
      }
    }

    reports.push({
      name: file.name,
      zone: "sales",
      kind,
      marketplace,
      ok: true,
      message:
        kind === "inventory"
          ? `${rows} baris inventori`
          : `${rows} baris terjual`,
      rows,
    });
  }

  return { sales, listings, reports };
}

/* -------------------------------------------------------------------------- */
/* Analysis                                                                    */
/* -------------------------------------------------------------------------- */

export function analyseUpload(
  internalFiles: UploadedText[],
  salesFiles: UploadedText[],
  seed: Seed,
): UploadResult {
  const { catalogue, reports: internalReports } = readInternal(internalFiles);
  const usedSeedCatalogue = internalFiles.length === 0 || catalogue.size === 0;

  // With no internal file, fall back to the bundled cost table so a sales-only
  // upload can still be priced rather than producing rows with zero cost.
  if (usedSeedCatalogue) {
    for (const p of seed.products) {
      if (!catalogue.has(p.key)) {
        catalogue.set(p.key, { key: p.key, name: p.name, category: p.category, cost: p.cost });
      }
    }
  }

  const { sales, listings, reports: salesReports } = readMarketplace(salesFiles);

  const asOf = parseStamp(`${seed.as_of} 23:59:59`) ?? new Date();
  const windowStart = new Date(asOf.getTime() - seed.config.run_rate_window_hours * 3_600_000);
  const fallbackStart = new Date(asOf.getTime() - seed.config.run_rate_fallback_hours * 3_600_000);

  const windowUnits = new Map<string, number>();
  const fallbackUnits = new Map<string, number>();
  const revenue = new Map<string, number>();
  const revenueUnits = new Map<string, number>();

  for (const line of sales) {
    const key = `${line.channel}|${line.sku}`;
    if (line.at && line.at >= windowStart) {
      windowUnits.set(key, (windowUnits.get(key) || 0) + line.units);
    }
    if (line.at && line.at >= fallbackStart) {
      fallbackUnits.set(key, (fallbackUnits.get(key) || 0) + line.units);
    }
    revenue.set(key, (revenue.get(key) || 0) + line.pricePerUnit * line.units);
    revenueUnits.set(key, (revenueUnits.get(key) || 0) + line.units);
  }

  // A row exists for every (channel, SKU) that has either an allocation or a sale —
  // a sales-only upload still surfaces margin problems.
  const pairs = new Set<string>([...listings.keys(), ...revenue.keys()]);

  const orphanSet = new Set<string>();
  const rows: UploadRow[] = [];

  for (const pair of pairs) {
    const [channel, sellerSku] = pair.split("|") as [Channel, string];
    const entry = catalogue.get(sellerSku);
    if (!entry) {
      orphanSet.add(sellerSku);
      continue;
    }
    const fees = seed.fees[channel] ?? seed.fees.Shopee;
    const allocated = listings.get(pair) || 0;
    const unitsWindow = windowUnits.get(pair) || 0;
    const unitsFallback = fallbackUnits.get(pair) || 0;

    // §6.1 — recent window first, then the documented 30-day fallback for slow movers.
    const rate =
      unitsWindow > 0
        ? runRatePerHour(unitsWindow, seed.config.run_rate_window_hours)
        : unitsFallback > 0
          ? runRatePerHour(unitsFallback, seed.config.run_rate_fallback_hours)
          : 0;

    const hours = hoursToStockout(allocated, rate);
    const status = classifyStockout(allocated, rate, seed.config.alert_horizon_hours);

    // §7 — margin, only where the SKU actually sold.
    const nUnits = revenueUnits.get(pair) || 0;
    let pricePerUnit = 0;
    let received = 0;
    let lossUnit = 0;
    let lossTotal = 0;
    let severity: Severity = "OK";
    let suggested = 0;

    if (nUnits > 0 && entry.cost > 0) {
      pricePerUnit = (revenue.get(pair) || 0) / nUnits;
      received = sellerReceivedPerUnit(pricePerUnit, nUnits, fees);
      lossUnit = underCogsPerUnit(entry.cost, pricePerUnit, nUnits, fees);
      lossTotal = lossUnit * nUnits;
      severity = classifySeverity(lossUnit, entry.cost);
      suggested = targetPrice(entry.cost, seed.config.target_margin, nUnits, fees);
    } else if (nUnits > 0) {
      pricePerUnit = (revenue.get(pair) || 0) / nUnits;
    }

    rows.push({
      sku: sellerSku,
      name: entry.name,
      category: entry.category,
      channel,
      allocated,
      unit_cost: entry.cost,
      sold_units_window: unitsWindow,
      sold_units_fallback: unitsFallback,
      sold_units_period: nUnits,
      net_item_value_per_unit: Math.round(pricePerUnit * 100) / 100,
      revenue: Math.round((revenue.get(pair) || 0) * 100) / 100,
      run_rate_per_hour: Math.round(rate * 1_000_000) / 1_000_000,
      hours_to_stockout: hours === null ? null : Math.round(hours * 10) / 10,
      stockout_status: status,
      cover_days: hours === null ? null : Math.round((hours / 24) * 10) / 10,
      under_cogs_per_unit: Math.round(lossUnit * 100) / 100,
      under_cogs_total: Math.round(lossTotal * 100) / 100,
      severity,
      seller_received_per_unit: Math.round(received * 100) / 100,
      recommended_price: Math.round(suggested * 100) / 100,
    });
  }

  const reallocationCount = countReallocations(rows, seed.config.target_cover_hours);
  const exposure = grossExposure(rows.map((r) => r.under_cogs_total));
  const net = rows.reduce((total, r) => total + r.under_cogs_total, 0);
  const budget = seed.config.campaign_budget;

  return {
    files: [...internalReports, ...salesReports],
    catalogue_size: catalogue.size,
    used_seed_catalogue: usedSeedCatalogue,
    sales_lines: sales.length,
    listing_pairs: listings.size,
    orphan_skus: [...orphanSet].sort(),
    rows,
    summary: {
      rows: rows.length,
      below_cost: rows.filter((r) => r.under_cogs_total > 0).length,
      critical: rows.filter((r) => r.severity === "CRITICAL").length,
      out_of_stock: rows.filter((r) => r.stockout_status === "OUT_OF_STOCK").length,
      at_risk: rows.filter((r) => r.stockout_status === "AT_RISK").length,
      gross_exposure: Math.round(exposure * 100) / 100,
      net_position: Math.round(net * 100) / 100,
      campaign_budget: budget,
      budget_safe: Math.round((budget - exposure) * 100) / 100,
      budget_remaining_pct: budget > 0 ? Math.round(((budget - exposure) / budget) * 1000) / 10 : 0,
      budget_status: budgetStatus(budget, exposure),
      reallocation_count: reallocationCount,
    },
  };
}

/** Mirrors build_analysis.build_recommendations — how many SKUs have a donor. */
function countReallocations(rows: UploadRow[], targetCoverHours: number): number {
  const bySku = new Map<string, UploadRow[]>();
  for (const row of rows) {
    const list = bySku.get(row.sku) ?? [];
    list.push(row);
    bySku.set(row.sku, list);
  }

  let count = 0;
  for (const channels of bySku.values()) {
    const troubled = channels
      .filter((c) => (c.stockout_status === "AT_RISK" || c.stockout_status === "OUT_OF_STOCK") && c.run_rate_per_hour > 0)
      .sort((a, b) => rankStockout(b.stockout_status) - rankStockout(a.stockout_status));
    if (!troubled.length) continue;

    // One advisory per troubled SKU, matching build_analysis.build_recommendations —
    // a donor is offered when one exists, but the SKU still needs a decision either way.
    void targetCoverHours;
    count++;
  }
  return count;
}

function rankStockout(status: StockoutStatus): number {
  return { OUT_OF_STOCK: 3, AT_RISK: 2, HEALTHY: 1, DORMANT: 0 }[status];
}

/** Actionable rows first: money lost, then stock risk. Mirrors the dashboard's ranking. */
export function rankRows(rows: UploadRow[]): UploadRow[] {
  const severityRank: Record<Severity, number> = { CRITICAL: 3, AT_RISK: 2, WATCH: 1, OK: 0 };
  return [...rows]
    .filter(
      (r) =>
        r.stockout_status === "AT_RISK" ||
        r.stockout_status === "OUT_OF_STOCK" ||
        r.severity === "CRITICAL" ||
        r.severity === "AT_RISK" ||
        r.severity === "WATCH",
    )
    .sort(
      (a, b) =>
        severityRank[b.severity] * 2 + rankStockout(b.stockout_status) -
        (severityRank[a.severity] * 2 + rankStockout(a.stockout_status)),
    );
}