export interface QuoteState {
  price: string;
  quantity: string;
  queue_ahead: string;
  status: string;
  cancel_pending: boolean;
}

export interface ReplayFrame {
  decision?: { quote: boolean; half_spread_ticks: number; skew_ticks: number; side_mode?: 'off' | 'both' | 'buy' | 'sell' } | null;
  elapsed_ms: number;
  time_ms: number;
  received_time_ns: string;
  mid: string;
  pnl: string;
  cash: string;
  inventory: string;
  fees: string;
  turnover: string;
  fill_count: number;
  bids: [string, string][];
  asks: [string, string][];
  quotes: { buy: QuoteState | null; sell: QuoteState | null };
}

export interface ReplayFill {
  order_id: string;
  trade_id: string;
  time_ms: number;
  elapsed_ms: number;
  side: 'buy' | 'sell';
  price: string;
  quantity: string;
  fee: string;
}

export interface ReplaySummary {
  pnl: string;
  inventory: string;
  fees: string;
  turnover: string;
  fill_count: number;
  duration_ms: number;
  decision_steps: number;
  terminal_reason: string;
}

export interface ReplayRun {
  model?: ModelProvenance | null;
  schema_version: number;
  source: { capture_file: string; capture_sha256: string; segment_index: number; segment_count: number };
  policy: { id: string; label: string; kind: string };
  configuration: {
    tick_size: string; quantity: string; initial_cash: string;
    maker_fee_rate: string; order_latency_ns: number; cancel_latency_ns: number;
    max_abs_inventory: string; half_spread_ticks: number | null; max_skew_ticks: string;
    decision_interval_ns: number; sample_interval_ns: number;
    entry_fee_buffer_bps?: string | null;
  };
  summary: ReplaySummary;
  frames: ReplayFrame[];
  fills: ReplayFill[];
}

export interface CatalogRun {
  policy: string;
  label: string;
  file: string;
  sha256: string;
  frames: number;
  summary: ReplaySummary;
}

export interface ReplaySession {
  id: string;
  label: string;
  split: 'train';
  captured_at_utc: string;
  capture_sha256: string;
  runs: CatalogRun[];
}

export interface ReplayCatalog {
  model?: ModelProvenance | null;
  schema_version: number;
  generated_at_utc: string;
  study_name: string;
  training_sessions_validated: number;
  selection_rule: string;
  held_out_splits_used: string[];
  sessions: ReplaySession[];
}

export interface ModelProvenance {
  policy_overlay?: { entry_fee_buffer_bps: string; trained_with_overlay: boolean; scope: string } | null;
  model_file: string;
  model_sha256: string;
  metadata_file: string;
  metadata_sha256: string;
  seed: number;
  total_timesteps: number;
  training_capture_count: number;
  action_schema_version: number;
  observation_schema_version?: number;
  half_spread_tick_choices: number[] | null;
  claim_status: string;
}

export function numberText(value: string | number, digits = 2) {
  return Number(value).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function elapsedText(milliseconds: number) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
}
