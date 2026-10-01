/** Shapes emitted by src/build_analysis.py — keep in step with that file. */

export type StockoutStatus = "AT_RISK" | "OUT_OF_STOCK" | "HEALTHY" | "DORMANT";
export type Severity = "CRITICAL" | "AT_RISK" | "WATCH" | "OK";
export type BudgetStatus = "HEALTHY" | "CAUTION" | "BREACHED";
export type Channel = "Shopee" | "TikTok Shop";

export interface SkuChannelRow {
  sku: string;
  seller_sku: string;
  name: string;
  category: string;
  channel: Channel;
  allocated: number;
  stock_on_hand: number;
  unit_cost: number;
  sold_units_window: number;
  sold_units_fallback: number;
  /** All sold units across the whole analysis window — the basis for margin figures. */
  sold_units_period: number;
  net_item_value_per_unit: number;
  revenue: number;
  run_rate_per_hour: number;
  hours_to_stockout: number | null;
  stockout_status: StockoutStatus;
  status_by_horizon: Record<string, StockoutStatus>;
  cover_days: number | null;
  under_cogs_per_unit: number;
  under_cogs_total: number;
  severity: Severity;
  seller_received_per_unit: number;
  recommended_price: number;
}

export interface Recommendation {
  sku: string;
  name: string;
  from_channel: Channel | null;
  to_channel: Channel;
  move_units: number | null;
  reason: string;
  blocked: boolean;
}

export interface HorizonSensitivity {
  horizon_hours: number;
  horizon_days: number;
  at_risk: number;
  out_of_stock: number;
}

export interface AnalysisSummary {
  total_rows: number;
  at_risk_count: number;
  out_of_stock_count: number;
  critical_count: number;
  below_cost_count: number;
  gross_exposure: number;
  net_position: number;
  campaign_budget: number;
  budget_safe: number;
  budget_remaining_pct: number;
  budget_status: BudgetStatus;
  reallocation_count: number;
}

export interface Analysis {
  generated_at: string;
  data_as_of: string;
  config: {
    run_rate_window_hours: number;
    alert_horizon_hours: number;
    target_cover_hours: number;
    target_margin: number;
    campaign_budget: number;
  };
  summary: AnalysisSummary;
  action_list: SkuChannelRow[];
  recommendations: Recommendation[];
  all_rows: SkuChannelRow[];
  horizon_sensitivity: HorizonSensitivity[];
}