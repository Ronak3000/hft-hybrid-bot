import sourceCatalog from '../../../public/replays/catalog.json';

export interface RecordedFrame {
  time_ms: number;
  elapsed_ms: number;
  mid: string;
  pnl: string;
  fees: string;
  inventory: string;
  fill_count: number;
}

export interface RecordedFill {
  trade_id: string;
  order_id: string;
  time_ms: number;
  side: 'buy' | 'sell';
  price: string;
  quantity: string;
}

export interface Recording {
  source: { capture_sha256: string; capture_file: string };
  configuration: { maker_fee_rate: string; order_latency_ns: number; cancel_latency_ns: number };
  frames: RecordedFrame[];
  fills: RecordedFill[];
}

export const sessions = sourceCatalog.sessions;
export const DEFAULT_POLICY = 'inventory_skew';

export type RecordingEntry = typeof sessions[number]['runs'][number];

export async function loadRecording(entry: RecordingEntry, captureSha: string, signal: AbortSignal) {
  const response = await fetch('/replays/' + entry.file, { signal });
  if (!response.ok) throw new Error('Could not open this recorded session.');
  const bytes = await response.arrayBuffer();
  if (!globalThis.crypto?.subtle) throw new Error('Recording verification requires HTTPS or localhost.');
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  const actual = Array.from(new Uint8Array(hash), (value) => value.toString(16).padStart(2, '0')).join('');
  if (actual !== entry.sha256) throw new Error('The recording did not match its catalog checksum.');
  const recording = JSON.parse(new TextDecoder().decode(bytes)) as Recording;
  if (recording.source.capture_sha256 !== captureSha || recording.frames.length !== entry.frames || !recording.frames.length) {
    throw new Error('This recording does not match the selected session.');
  }
  return recording;
}

export const formatPrice = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 });
export const formatSize = new Intl.NumberFormat('en-US', { maximumFractionDigits: 8, minimumFractionDigits: 3 });
export const formatClock = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'UTC', hour: '2-digit', minute: '2-digit', second: '2-digit',
});

export function formatElapsed(ms: number) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const seconds = totalSeconds % 60;
  return [hours ? String(hours) : '', String(minutes).padStart(2, '0'), String(seconds).padStart(2, '0')].filter(Boolean).join(':');
}

export function findFrame(frames: RecordedFrame[], elapsed: number) {
  let low = 0;
  let high = frames.length - 1;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (frames[mid].elapsed_ms <= elapsed) low = mid;
    else high = mid - 1;
  }
  return low;
}
