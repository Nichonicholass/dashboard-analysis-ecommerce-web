import type { HorizonSensitivity } from "@/lib/types";
import { number } from "@/lib/format";

/**
 * Makes the tech_spec §6.4 finding visible instead of leaving an empty list.
 *
 * The fixture carries far more stock than demand (median cover ~537 days), so a
 * 1-day or 7-day horizon classifies nothing as AT_RISK. Widening the horizon shows
 * that the formula works and the data is simply slow-moving.
 */
export function HorizonChart({ series }: { series: HorizonSensitivity[] }) {
  const max = Math.max(...series.map((s) => s.at_risk), 1);

  return (
    <div className="px-4 py-4">
      <ul className="space-y-2">
        {series.map((point) => {
          const width = (point.at_risk / max) * 100;
          const isActive = point.horizon_days === 7;
          return (
            <li key={point.horizon_hours} className="flex items-center gap-3 text-xs">
              <span
                className={`w-16 shrink-0 tabular-nums ${
                  isActive ? "font-semibold text-slate-900" : "text-slate-500"
                }`}
              >
                {number(point.horizon_days)}d
                {isActive && " ●"}
              </span>
              <span className="h-4 flex-1 overflow-hidden rounded bg-slate-100">
                <span
                  className={isActive ? "block h-full bg-slate-900" : "block h-full bg-slate-300"}
                  style={{ width: `${Math.max(width, point.at_risk > 0 ? 2 : 0)}%` }}
                />
              </span>
              <span className="w-24 shrink-0 text-right tabular-nums text-slate-600">
                {point.at_risk} at risk
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-slate-500">
        ● marks the configured default of 7 days. Widening the horizon raises the count
        because the catalogue moves slowly — median cover is 537 days.
      </p>
    </div>
  );
}