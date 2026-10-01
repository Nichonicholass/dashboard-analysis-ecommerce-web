import Link from "next/link";
import { byCategory } from "@/lib/analysis";
import { number, rupiahCompact } from "@/lib/format";
import { Card, ChannelTag, Stat } from "@/components/ui";

export default function BrandsPage() {
  const categories = byCategory();

  // Roll up per category across both channels.
  const rollup = categories.map(({ category, rows }) => {
    const exposure = rows.reduce((sum, r) => sum + Math.max(0, r.under_cogs_total), 0);
    const critical = rows.filter((r) => r.severity === "CRITICAL").length;
    const belowCost = rows.filter((r) => r.under_cogs_total > 0).length;
    const atRisk = rows.filter(
      (r) => r.stockout_status === "AT_RISK" || r.stockout_status === "OUT_OF_STOCK"
    ).length;
    const revenue = rows.reduce((sum, r) => sum + r.revenue, 0);
    return { category, rows, exposure, critical, belowCost, atRisk, revenue };
  });

  rollup.sort((a, b) => b.exposure - a.exposure);

  const totalExposure = rollup.reduce((sum, r) => sum + r.exposure, 0);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Brand Overview</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Where the losses concentrate, by category — sorted by exposure.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Categories" value={number(rollup.length)} />
        <Stat
          label="Total exposure"
          value={rupiahCompact(totalExposure)}
          tone="bad"
          hint="Gross — losses only"
        />
        <Stat
          label="Categories in loss"
          value={number(rollup.filter((r) => r.exposure > 0).length)}
          hint={`of ${rollup.length}`}
        />
        <Stat
          label="Worst category"
          value={rollup[0]?.category ?? "—"}
          hint={rollup[0] ? rupiahCompact(rollup[0].exposure) : undefined}
          tone="bad"
        />
      </div>

      <Card
        title="Exposure by category"
        subtitle="Bar width is proportional to the largest exposure in the table"
      >
        <ul className="divide-y divide-slate-100">
          {rollup.map((item) => {
            const width = totalExposure > 0 ? (item.exposure / rollup[0].exposure) * 100 : 0;
            return (
              <li key={item.category} className="px-4 py-3">
                <div className="flex items-baseline justify-between gap-4">
                  <span className="text-sm font-medium text-slate-900">{item.category}</span>
                  <span className="text-sm font-semibold tabular-nums text-red-700">
                    {item.exposure > 0 ? rupiahCompact(item.exposure) : "—"}
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 overflow-hidden rounded bg-slate-100">
                  <div
                    className="h-full bg-red-500"
                    style={{ width: `${Math.min(width, 100)}%` }}
                  />
                </div>
                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                  <span>{item.rows.length} SKU/channel rows</span>
                  {item.critical > 0 && (
                    <span className="font-medium text-red-600">{item.critical} critical</span>
                  )}
                  {item.belowCost > 0 && <span>{item.belowCost} below cost</span>}
                  {item.atRisk > 0 && <span>{item.atRisk} stock risk</span>}
                  <span>revenue {rupiahCompact(item.revenue)}</span>
                </div>
              </li>
            );
          })}
        </ul>
      </Card>

      <Card title="Category detail" subtitle="Every SKU/channel row, grouped by category">
        <div className="divide-y divide-slate-100">
          {rollup.map(({ category, rows }) => (
            <details key={category} className="group">
              <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-slate-800 hover:bg-slate-50">
                <span className="mr-1 inline-block transition-transform group-open:rotate-90">
                  ▸
                </span>
                {category}
                <span className="ml-2 text-xs font-normal text-slate-400">
                  {rows.length} rows
                </span>
              </summary>
              <ul className="bg-slate-50/60 px-4 py-2">
                {rows
                  .slice()
                  .sort((a, b) => b.under_cogs_total - a.under_cogs_total)
                  .map((row) => (
                    <li
                      key={`${row.sku}-${row.channel}`}
                      className="flex flex-wrap items-center gap-2 border-b border-slate-100 py-1.5 last:border-0 text-sm"
                    >
                      <Link
                        href={`/sku/${row.sku}`}
                        className="text-slate-800 hover:underline"
                      >
                        {row.name}
                      </Link>
                      <ChannelTag value={row.channel} />
                      <span className="ml-auto tabular-nums text-xs text-slate-500">
                        {row.under_cogs_total > 0
                          ? `−${rupiahCompact(row.under_cogs_total)}`
                          : "profitable"}
                      </span>
                    </li>
                  ))}
              </ul>
            </details>
          ))}
        </div>
      </Card>
    </div>
  );
}