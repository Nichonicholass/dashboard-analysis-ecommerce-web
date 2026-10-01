import Link from "next/link";
import { notFound } from "next/navigation";
import { data, rowsForSku, skuList } from "@/lib/analysis";
import { coverDays, number, percent, rupiah } from "@/lib/format";
import { Card, ChannelTag, SeverityBadge, Stat, StockoutBadge } from "@/components/ui";

export function generateStaticParams() {
  return skuList().map(({ sku }) => ({ sku }));
}

const HORIZONS = [24, 168, 336, 720, 2160, 8760];

export default async function SkuDetailPage({
  params,
}: {
  params: Promise<{ sku: string }>;
}) {
  const { sku } = await params;
  const rows = rowsForSku(sku);

  if (rows.length === 0) notFound();

  const first = rows[0];
  const totalLoss = rows.reduce((sum, row) => sum + Math.max(0, row.under_cogs_total), 0);
  const totalAllocated = rows.reduce((sum, row) => sum + row.allocated, 0);
  const stockOnHand = first.stock_on_hand;

  // The PRD's allocation constraint: you cannot promise units that don't exist.
  const oversubscribed = totalAllocated > stockOnHand;

  return (
    <div className="space-y-5">
      <div>
        <Link href="/" className="text-xs font-medium text-slate-500 hover:text-slate-900">
          ← Action List
        </Link>
        <h1 className="mt-1 text-lg font-semibold tracking-tight">{first.name}</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          <span className="font-mono">{first.sku}</span> · {first.category} · cost{" "}
          {rupiah(first.unit_cost)} per unit
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Stock on hand" value={number(stockOnHand)} hint="One physical pool" />
        <Stat
          label="Allocated across channels"
          value={number(totalAllocated)}
          hint={oversubscribed ? "Exceeds stock on hand" : "Within stock on hand"}
          tone={oversubscribed ? "bad" : "good"}
        />
        <Stat
          label="Total loss"
          value={totalLoss > 0 ? rupiah(totalLoss) : "—"}
          hint={totalLoss > 0 ? "Across both channels" : "Profitable everywhere"}
          tone={totalLoss > 0 ? "bad" : "good"}
        />
        <Stat
          label="Channels selling"
          value={`${rows.filter((r) => r.sold_units_period > 0).length} of ${rows.length}`}
          hint={`${number(rows.reduce((s, r) => s + r.sold_units_period, 0))} units sold in period`}
        />
      </div>

      <Card
        title="Allocation across marketplaces"
        subtitle="Seller stock is one pool; each marketplace holds a listing quantity it may sell"
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                <th className="px-3 py-2">Channel</th>
                <th className="px-3 py-2 text-right">Allocated</th>
                <th className="px-3 py-2 text-right">Sold (7d)</th>
                <th className="px-3 py-2 text-right">Run rate</th>
                <th className="px-3 py-2 text-right">Cover</th>
                <th className="px-3 py-2">Stock status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.channel} className="border-t border-slate-100">
                  <td className="px-3 py-2">
                    <ChannelTag value={row.channel} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.allocated}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {row.sold_units_window > 0 ? row.sold_units_window : "—"}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs tabular-nums text-slate-500">
                    {number(row.run_rate_per_hour, 5)}/h
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {coverDays(row.cover_days)}
                  </td>
                  <td className="px-3 py-2">
                    <StockoutBadge value={row.stockout_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="Margin by channel"
        subtitle="Over the whole 90-day window. Seller receipt is net of commission, payment fee and affiliate — what the buyer paid is not what we keep"
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                <th className="px-3 py-2">Channel</th>
                <th className="px-3 py-2 text-right">Units</th>
                <th className="px-3 py-2 text-right">Buyer paid / unit</th>
                <th className="px-3 py-2 text-right">Seller receives / unit</th>
                <th className="px-3 py-2 text-right">Cost / unit</th>
                <th className="px-3 py-2 text-right">Loss / unit</th>
                <th className="px-3 py-2 text-right">Total loss</th>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2 text-right">Target price</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                /* Margin figures cover the full period, so the price columns must
                   use the same basis — gating them on the 7-day window produced
                   rows showing a loss with no price behind it. */
                const sold = row.sold_units_period > 0;
                return (
                <tr key={row.channel} className="border-t border-slate-100">
                  <td className="px-3 py-2">
                    <ChannelTag value={row.channel} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                    {sold ? row.sold_units_period : "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                    {sold ? rupiah(row.net_item_value_per_unit) : "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {sold ? rupiah(row.seller_received_per_unit) : "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{rupiah(row.unit_cost)}</td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums ${
                      row.under_cogs_per_unit > 0 ? "font-medium text-red-700" : "text-slate-500"
                    }`}
                  >
                    {row.under_cogs_per_unit > 0 ? rupiah(row.under_cogs_per_unit) : "—"}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums ${
                      row.under_cogs_total > 0 ? "font-medium text-red-700" : "text-slate-500"
                    }`}
                  >
                    {row.under_cogs_total > 0 ? rupiah(row.under_cogs_total) : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <SeverityBadge value={row.severity} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {row.under_cogs_per_unit > 0 ? (
                      <>
                        <div>{rupiah(row.recommended_price)}</div>
                        <div className="text-xs text-slate-400">
                          {percent(
                            (row.recommended_price / row.net_item_value_per_unit - 1) * 100, 0
                          )}{" "}
                          above current
                        </div>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="Would a wider horizon flag this SKU?"
        subtitle="Same formula, different threshold — the §6.4 sensitivity for this item"
      >
        <ul className="divide-y divide-slate-100">
          {HORIZONS.map((hours) => {
            const status = first.status_by_horizon?.[String(hours)] ?? "HEALTHY";
            return (
              <li key={hours} className="flex items-center justify-between px-4 py-2 text-sm">
                <span className="text-slate-600">
                  {hours / 24} day{hours === 24 ? "" : "s"}
                </span>
                <StockoutBadge value={status} />
              </li>
            );
          })}
        </ul>
      </Card>

      <p className="text-xs text-slate-400">
        Cost basis: weighted average from <code>data/internal/cogs_ledger.csv</code>. Figures
        computed in <code>src/metrics.py</code>.
      </p>
    </div>
  );
}