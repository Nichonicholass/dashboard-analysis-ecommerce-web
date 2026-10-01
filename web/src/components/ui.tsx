import type { BudgetStatus, Severity, StockoutStatus } from "@/lib/types";

const badgeBase =
  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap";

const SEVERITY_STYLE: Record<Severity, string> = {
  CRITICAL: "bg-red-100 text-red-800 ring-1 ring-red-200",
  AT_RISK: "bg-orange-100 text-orange-800 ring-1 ring-orange-200",
  WATCH: "bg-amber-100 text-amber-800 ring-1 ring-amber-200",
  OK: "bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200",
};

const STOCKOUT_STYLE: Record<StockoutStatus, string> = {
  OUT_OF_STOCK: "bg-red-100 text-red-800 ring-1 ring-red-200",
  AT_RISK: "bg-orange-100 text-orange-800 ring-1 ring-orange-200",
  HEALTHY: "bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200",
  DORMANT: "bg-slate-100 text-slate-600 ring-1 ring-slate-200",
};

const STOCKOUT_LABEL: Record<StockoutStatus, string> = {
  OUT_OF_STOCK: "Out of stock",
  AT_RISK: "At risk",
  HEALTHY: "Healthy",
  DORMANT: "No sales",
};

export function SeverityBadge({ value }: { value: Severity }) {
  return <span className={`${badgeBase} ${SEVERITY_STYLE[value]}`}>{value}</span>;
}

export function StockoutBadge({ value }: { value: StockoutStatus }) {
  return <span className={`${badgeBase} ${STOCKOUT_STYLE[value]}`}>{STOCKOUT_LABEL[value]}</span>;
}

export function BudgetBadge({ value }: { value: BudgetStatus }) {
  const style =
    value === "HEALTHY"
      ? "bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200"
      : value === "CAUTION"
        ? "bg-amber-100 text-amber-800 ring-1 ring-amber-200"
        : "bg-red-100 text-red-800 ring-1 ring-red-200";
  return <span className={`${badgeBase} ${style}`}>{value}</span>;
}

export function ChannelTag({ value }: { value: string }) {
  const style =
    value === "Shopee"
      ? "bg-orange-50 text-orange-700 ring-1 ring-orange-200"
      : "bg-slate-900 text-white";
  return <span className={`${badgeBase} ${style}`}>{value}</span>;
}

export function Card({
  title,
  subtitle,
  action,
  children,
}: {
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div>{children}</div>
    </section>
  );
}

/** Headline figure. `tone` drives the accent so a breached reserve reads as bad. */
export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "good" | "warn" | "bad";
}) {
  const toneStyle = {
    neutral: "text-slate-900",
    good: "text-emerald-700",
    warn: "text-amber-700",
    bad: "text-red-700",
  }[tone];

  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${toneStyle}`}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

/** Small inline caveat used where the data cannot honestly support a claim. */
export function Caveat({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
      <span className="font-semibold">Caveat · </span>
      {children}
    </div>
  );
}