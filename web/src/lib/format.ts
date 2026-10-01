/** Presentation helpers. Currency is IDR throughout. */

const idr = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  maximumFractionDigits: 0,
});

/**
 * Indonesian locale abbreviates as "rb" (ribu / thousand) and "jt" (juta / million).
 * That is correct locally but easy to misread, so scale explicitly instead and keep
 * the rupiah prefix.
 */
export function rupiahCompact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `Rp ${number(value / 1_000_000_000, 1)}bn`;
  if (abs >= 1_000_000) return `Rp ${number(value / 1_000_000, 1)}M`;
  if (abs >= 1_000) return `Rp ${number(value / 1_000, 0)}k`;
  return rupiah(value);
}

export function rupiah(value: number): string {
  return idr.format(value);
}

export function number(value: number, digits = 0): string {
  return new Intl.NumberFormat("id-ID", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** Cover in days, with the awkward extremes handled honestly. */
export function coverDays(days: number | null): string {
  if (days === null) return "—";
  if (days === 0) return "0 (empty)";
  if (days < 1) return `${number(days * 24, 1)}h`;
  if (days > 365) return `${number(days / 365, 1)}y`;
  return `${number(days, 1)}d`;
}

export function percent(value: number, digits = 1): string {
  return `${number(value, digits)}%`;
}

/** Margin as a share of cost, which is how severity bands are defined. */
export function marginVsCost(row: { unit_cost: number; under_cogs_per_unit: number }): number {
  if (row.unit_cost <= 0) return 0;
  return ((row.unit_cost - row.under_cogs_per_unit) / row.unit_cost) * 100 - 100;
}