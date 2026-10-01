import Link from "next/link";
import { data } from "@/lib/analysis";
import { number, percent, rupiah, rupiahCompact } from "@/lib/format";
import type { SkuChannelRow } from "@/lib/types";
import { Caveat, Card, ChannelTag, SeverityBadge, Stat, StockoutBadge } from "@/components/ui";
import { HorizonChart } from "@/components/horizon-chart";

function Row({ row }: { row: SkuChannelRow }) {
  return (
    <tr className="border-t border-slate-100 align-top hover:bg-slate-50">
      <td className="px-3 py-2">
        <Link href={`/sku/${row.sku}`} className="font-medium text-slate-900 hover:underline">
          {row.name}
        </Link>
        <div className="mt-0.5 font-mono text-xs text-slate-400">{row.sku}</div>
      </td>
      <td className="px-3 py-2">
        <ChannelTag value={row.channel} />
      </td>
      <td className="px-3 py-2">
        <StockoutBadge value={row.stockout_status} />
      </td>
      <td className="px-3 py-2">
        <SeverityBadge value={row.severity} />
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-slate-700">{row.allocated}</td>
      <td className="px-3 py-2 text-right tabular-nums text-slate-700">
        {row.sold_units_window > 0 ? row.sold_units_window : "—"}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-slate-700">
        {row.under_cogs_per_unit > 0 ? rupiah(row.under_cogs_per_unit) : "—"}
      </td>
      <td className="px-3 py-2 text-right font-medium tabular-nums text-red-700">
        {row.under_cogs_total > 0 ? rupiah(row.under_cogs_total) : "—"}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-slate-700">
        {row.under_cogs_per_unit > 0 && row.recommended_price > 0
          ? rupiah(row.recommended_price)
          : "—"}
      </td>
      <td className="px-3 py-2 text-right">
        <Link
          href={`/sku/${row.sku}`}
          className="text-xs font-medium text-slate-500 hover:text-slate-900 hover:underline"
        >
          Detail →
        </Link>
      </td>
    </tr>
  );
}

export default function ActionListPage() {
  const { summary, action_list, recommendations, horizon_sensitivity, config } = data;

  const budgetTone =
    summary.budget_status === "HEALTHY"
      ? "good"
      : summary.budget_status === "CAUTION"
        ? "warn"
        : "bad";

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Action List</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Every SKU needing attention, worst money at stake first. Data as of{" "}
          {data.data_as_of.replace("T", " ")} · generated {data.generated_at.replace("T", " ")}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Critical"
          value={number(summary.critical_count)}
          hint="Losing ≥10% of cost"
          tone={summary.critical_count > 0 ? "bad" : "good"}
        />
        <Stat
          label="At risk"
          value={number(summary.at_risk_count)}
          hint={`Cover ≤ ${config.alert_horizon_hours}h`}
          tone="neutral"
        />
        <Stat
          label="Gross exposure"
          value={rupiahCompact(summary.gross_exposure)}
          hint="Losses only, profits excluded"
          tone="bad"
        />
        <Stat
          label="Campaign reserve"
          value={rupiahCompact(summary.budget_safe)}
          hint={`${percent(summary.budget_remaining_pct)} left · ${summary.budget_status}`}
          tone={budgetTone}
        />
      </div>

      <Caveat>
        <strong>This fixture cannot demonstrate stock-out prediction.</strong> Median cover is
        537 days, so a 7-day horizon flags nothing. The {summary.out_of_stock_count} SKUs shown
        are already empty. This is the measured limitation in <code>tech_spec.md</code> §6.4,
        pinned by checkpoints CP-36–39. The chart below shows the arithmetic is sound and the
        data is simply slow-moving — not that the logic is wrong.
      </Caveat>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card
            title="Recommended reallocations"
            subtitle="Listing quantity moved between channels — no goods physically move"
          >
            {recommendations.length === 0 ? (
              <p className="px-4 py-6 text-sm text-slate-500">Nothing to reallocate.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {recommendations.map((rec) => (
                  <li key={`${rec.sku}-${rec.to_channel}`} className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`/sku/${rec.sku}`}
                        className="text-sm font-medium hover:underline"
                      >
                        {rec.name}
                      </Link>
                      <span className="font-mono text-xs text-slate-400">{rec.sku}</span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm">
                      {rec.blocked ? (
                        <>
                          <ChannelTag value={rec.to_channel} />
                          <span className="text-slate-600">needs stock —</span>
                          <span className="font-semibold text-amber-700">
                            no donor available
                          </span>
                        </>
                      ) : (
                        <>
                          <span className="rounded bg-slate-900 px-2 py-0.5 text-xs font-semibold text-white tabular-nums">
                            {rec.move_units} units
                          </span>
                          {rec.from_channel && <ChannelTag value={rec.from_channel} />}
                          <span className="text-slate-400">→</span>
                          <ChannelTag value={rec.to_channel} />
                        </>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-slate-500">{rec.reason}</p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <Card
          title="Would a wider horizon help?"
          subtitle="AT_RISK count by alert horizon (tech_spec §6.4)"
        >
          <HorizonChart series={horizon_sensitivity} />
        </Card>
      </div>

      <Card
        title={`Action list · ${action_list.length} rows`}
        subtitle="Sorted by severity, then stock-out risk. Amounts in IDR."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                <th className="px-3 py-2">Product</th>
                <th className="px-3 py-2">Channel</th>
                <th className="px-3 py-2">Stock</th>
                <th className="px-3 py-2">Margin</th>
                <th className="px-3 py-2 text-right">Allocated</th>
                <th className="px-3 py-2 text-right">Sold (7d)</th>
                <th className="px-3 py-2 text-right">Loss / unit</th>
                <th className="px-3 py-2 text-right">Total loss</th>
                <th className="px-3 py-2 text-right">Target price</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {action_list.map((row) => (
                <Row key={`${row.sku}-${row.channel}`} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="text-xs text-slate-400">
        Commission rates are placeholders pending real seller contracts — see{" "}
        <code>tech_spec.md</code> §5.2. Every figure on this page is computed in{" "}
        <code>src/metrics.py</code>; none is recalculated in the browser.
      </p>
    </div>
  );
}