import asset from '../../../public/research/l2-pilot.json';

export type Direction = -1 | 0 | 1;
// UTC milliseconds, snapshot segment, mid, OFI, microprice dev., imbalance,
// spread, then the three logistic forecasts in horizon order.
export type Frame = [number, number, number, number, number, number, number, ...Direction[]];
export type PredictionSession = {
  name: string; featureSha256: string; captureSha256: string; majority: Direction[]; frames: Frame[];
};
type Markout = { observed_fills: number; signed_mid_move_pnl: string | null };
export type QuoteMetrics = {
  fills: number; net_pnl: string; fees: string; quantity_fill_rate: string;
  maximum_absolute_inventory: string; adverse_selection: Record<string, Markout>;
};
type QuoteSession = {
  test_capture: string; matched_updates: number; matched_directions: Record<string, number>;
  horizon_updates: number; widen_ticks: number;
  avellaneda_stoikov: QuoteMetrics; alpha_widened: QuoteMetrics; symmetric_widened: QuoteMetrics;
};
type LabData = {
  schema: number; venue: string; symbol: string; snapshot: string | null; horizons: number[];
  sessions: PredictionSession[];
  quoteReport: { sessions: QuoteSession[]; simulation_parameters: {
    maker_fee_rate: string; order_latency_ns: number; cancel_latency_ns: number;
  } };
};
export const labData = asset as unknown as LabData;
