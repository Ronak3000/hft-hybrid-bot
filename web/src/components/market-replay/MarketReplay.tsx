'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight, ChartCandlestick, ChartNoAxesCombined, ChevronDown, CircleHelp,
  Expand, History, Pause, Play, RotateCcw, ShieldCheck, SkipBack, SkipForward,
} from 'lucide-react';
import { MarketChart, type ChartMode } from './MarketChart';
import {
  DEFAULT_POLICY, findFrame, formatClock, formatElapsed, formatPrice, formatSize,
  loadRecording, sessions, type Recording,
} from './recording';
import styles from './market-replay.module.css';

const chartModes = [
  { id: 'mid', label: 'Mid-price', Icon: ChartNoAxesCombined },
  { id: 'candles', label: 'Candles', Icon: ChartCandlestick },
  { id: 'pnl', label: 'Simulated P&L', Icon: ChartNoAxesCombined },
] as const;

type LoadResult = { file: string; recording: Recording; error?: never } | { file: string; error: string; recording?: never };

export function MarketReplay() {
  const [sessionId, setSession] = useState(sessions[0].id);
  const [policyId, setPolicy] = useState(DEFAULT_POLICY);
  const [loadResult, setLoadResult] = useState<LoadResult | null>(null);
  const [request, setRequest] = useState(0);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);
  const [mode, setMode] = useState<ChartMode>('mid');
  const [fit, setFit] = useState(0);
  const [showFills, setShowFills] = useState(true);
  const position = useRef(0);
  const session = sessions.find((item) => item.id === sessionId) ?? sessions[0];
  const entry = session.runs.find((item) => item.policy === policyId) ?? session.runs[0];
  const result = loadResult?.file === entry.file ? loadResult : null;
  const recording = result?.recording;
  const frame = recording?.frames[cursor];
  const last = (recording?.frames.length ?? 1) - 1;
  const duration = recording?.frames[last].elapsed_ms ?? 0;

  useEffect(() => {
    const cancellation = new AbortController();
    loadRecording(entry, session.capture_sha256, cancellation.signal).then(
      (recording) => {
        if (!cancellation.signal.aborted) {
          const duration = recording.frames.at(-1)?.elapsed_ms ?? 0;
          const preview = findFrame(recording.frames, Math.min(15_000, duration / 4));
          position.current = preview;
          setCursor(preview);
          setLoadResult({ file: entry.file, recording });
        }
      },
      (error: unknown) => {
        if (!cancellation.signal.aborted) setLoadResult({
          file: entry.file,
          error: error instanceof Error ? error.message : 'Could not open this recorded session.',
        });
      },
    );
    return () => cancellation.abort();
  }, [entry, session.capture_sha256, request]);

  useEffect(() => {
    if (!playing || !recording) return;
    const { frames } = recording;
    const start = performance.now();
    const initialTime = frames[position.current].elapsed_ms;
    let timer = requestAnimationFrame(advance);
    function advance(now: number) {
      const next = findFrame(frames, initialTime + Math.max(0, now - start) * speed);
      if (next !== position.current) {
        position.current = next;
        setCursor(next);
      }
      if (next === last) setPlaying(false);
      else timer = requestAnimationFrame(advance);
    }
    return () => cancelAnimationFrame(timer);
  }, [last, playing, recording, speed]);

  function seek(next: number) {
    setPlaying(false);
    position.current = Math.min(last, Math.max(0, next));
    setCursor(position.current);
  }

  function togglePlayback() {
    if (!recording) return;
    if (playing) setPlaying(false);
    else {
      if (cursor === last) seek(0);
      setPlaying(true);
    }
  }

  function resetSession() {
    seek(0);
    setLoadResult(null);
  }

  return (
    <div className={styles.studio}>
      <header className={styles.hero}>
        <div>
          <p className={styles.eyebrow}><History size={15} aria-hidden="true" /> Playback studio</p>
          <h1>Rewind the market<span>.</span></h1>
          <p>Step through a real Binance order book and see where a paper strategy would have filled.</p>
        </div>
        <span className={styles.recorded}><i aria-hidden="true" /> Recorded · not live</span>
      </header>

      <div className={styles.workspace}>
        <section className={styles.chartPanel} aria-label="Replay workspace">
          <div className={styles.instrument}>
            <div className={styles.assetIcon} aria-hidden="true">₿</div>
            <div><h2>BTC / USDT</h2><p>Binance Spot <span>·</span> recorded L2</p></div>
            {frame && <div className={styles.reading}>
              <small>{mode === 'pnl' ? 'Simulated P&L' : 'Observed mid-price'}</small>
              <strong>{formatPrice.format(Number(mode === 'pnl' ? frame.pnl : frame.mid))} <span>USDT</span></strong>
            </div>}
          </div>
          <div className={styles.chartToolbar}>
            <div className={styles.chartModes} role="group" aria-label="Chart view">
              {chartModes.map(({ id, label, Icon }) => <button
                type="button" key={id} aria-pressed={mode === id} onClick={() => setMode(id)}
              ><Icon size={15} aria-hidden="true" />{label}</button>)}
            </div>
            <div className={styles.viewActions}>
              {mode !== 'pnl' && <label className={styles.fillToggle}><input type="checkbox" checked={showFills} onChange={event => setShowFills(event.target.checked)} /> Fill markers</label>}
              <button type="button" className={styles.iconButton} aria-label="Fit chart to played range" title="Fit chart to played range" onClick={() => setFit(fit + 1)} disabled={!recording}><Expand size={16} aria-hidden="true" /></button>
            </div>
          </div>
          {recording && frame ? (
            <MarketChart frames={recording.frames} fills={recording.fills} cursor={cursor} mode={mode} fit={fit} showFills={showFills} />
          ) : (
            <div className={styles.placeholder} role={result?.error ? 'alert' : 'status'}>
              {result?.error ? (
                <><p>{result.error}</p><button className={styles.secondary} type="button" onClick={() => { resetSession(); setRequest(request + 1); }}>Try again</button></>
              ) : <p>Checking the recording…</p>}
            </div>
          )}
          <div className={styles.chartHint}>
            {mode === 'candles' ? '5-second candles from recorded mid-price samples, not exchange OHLC.' :
              mode === 'pnl' ? 'Simulated performance after the recorded replay’s fee assumptions.' :
              'Mid-price from the recorded bid and ask. The chart stops at your cursor; Restart begins at the first frame.'}
          </div>
          <div className={styles.transport}>
            <div className={styles.transportButtons} role="group" aria-label="Playback controls">
              <button type="button" className={styles.iconButton} onClick={() => seek(0)} disabled={!frame} aria-label="Restart replay" title="Restart replay"><RotateCcw size={17} aria-hidden="true" /></button>
              <button type="button" className={styles.iconButton} onClick={() => seek(cursor - 1)} disabled={!frame || cursor === 0} aria-label="Previous frame" title="Previous frame"><SkipBack size={17} aria-hidden="true" /></button>
              <button type="button" className={styles.play} onClick={togglePlayback} disabled={!frame}>{playing ? <Pause size={17} aria-hidden="true" /> : <Play size={17} aria-hidden="true" />}{playing ? 'Pause' : cursor === last && last > 0 ? 'Replay' : 'Play'}</button>
              <button type="button" className={styles.iconButton} onClick={() => seek(cursor + 1)} disabled={!frame || cursor === last} aria-label="Next frame" title="Next frame"><SkipForward size={17} aria-hidden="true" /></button>
            </div>
            <label className={styles.speed}><span>Speed</span><select value={speed} onChange={event => setSpeed(Number(event.target.value))}><option value={1}>1×</option><option value={4}>4×</option><option value={16}>16×</option><option value={64}>64×</option></select></label>
          </div>
          <div className={styles.timeline}>
            <input
              type="range" min={0} max={Math.max(1, last)} value={cursor} onChange={event => seek(Number(event.target.value))}
              disabled={!frame || last === 0} aria-label="Seek recording"
              aria-valuetext={frame ? `${formatElapsed(frame.elapsed_ms)} of ${formatElapsed(duration)}` : 'Recording not loaded'}
            />
            <div><span>{formatElapsed(frame?.elapsed_ms ?? 0)} / {formatElapsed(duration)}</span><span>{frame ? `${formatClock.format(frame.time_ms)} UTC` : 'Recorded timeline'}</span></div>
          </div>
        </section>

        <aside className={styles.sidePanel} aria-label="Recording settings and fills">
          <div className={styles.sideSection}>
            <p className={styles.eyebrow}>Set the scene</p>
            <h2>Choose a recording</h2>
            <label className={styles.field}>Capture <select value={session.id} onChange={event => { resetSession(); setSession(event.target.value); }}>
              {sessions.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.captured_at_utc.slice(0, 10)}</option>)}
            </select></label>
            <label className={styles.field}>Paper strategy <select value={entry.policy} onChange={event => { resetSession(); setPolicy(event.target.value); }}>
              {session.runs.map((item) => <option key={item.policy} value={item.policy}>{item.label}</option>)}
            </select></label>
          </div>
          <div className={styles.sideSection}>
            <p className={styles.eyebrow}>Paper orders</p>
            <h2>Simulated fills {frame && <span className={styles.count}>{frame.fill_count}</span>}</h2>
            {recording && frame && frame.fill_count > 0 ? (
              <ol className={styles.activity}>{recording.fills.slice(Math.max(0, frame.fill_count - 4), frame.fill_count).reverse().map((fill) => (
                <li key={fill.order_id + ':' + fill.trade_id}>
                  <span className={fill.side === 'buy' ? styles.buy : styles.sell}>{fill.side === 'buy' ? 'Buy' : 'Sell'}</span>
                  <div><strong>{formatPrice.format(Number(fill.price))}</strong><small>{formatSize.format(Number(fill.quantity))} BTC</small></div>
                  <time dateTime={new Date(fill.time_ms).toISOString()}>{formatClock.format(fill.time_ms)}</time>
                </li>
              ))}</ol>
            ) : <p className={styles.noFills}>{recording ? cursor === last ? 'No fills in this replay. Try another paper strategy.' : 'No fills yet. Press Play or move the timeline to see what happens.' : 'Waiting for the recording.'}</p>}
          </div>
          <p className={styles.notice}><CircleHelp size={17} aria-hidden="true" /> Market prices are recorded. Orders, fills and P&L are simulated, not exchange executions.</p>
        </aside>
      </div>

      {recording && frame && <details className={styles.details}>
        <summary><ShieldCheck size={18} aria-hidden="true" /><span>Recording details and assumptions</span><ChevronDown size={17} aria-hidden="true" /></summary>
        <dl>
          <div><dt>Source capture</dt><dd>{recording.source.capture_file}</dd></div>
          <div><dt>Maker fee</dt><dd>{Number(recording.configuration.maker_fee_rate) * 100} %</dd></div>
          <div><dt>Order / cancel latency (modeled)</dt><dd>{recording.configuration.order_latency_ns / 1e6} / {recording.configuration.cancel_latency_ns / 1e6} ms</dd></div>
          <div><dt>Inventory at cursor</dt><dd>{formatSize.format(Number(frame.inventory))} BTC</dd></div>
          <div><dt>Fees at cursor</dt><dd>{formatPrice.format(Number(frame.fees))} USDT</dd></div>
          <div><dt>Replay file SHA-256 (verified)</dt><dd className={styles.hash}>{entry.sha256}</dd></div>
        </dl>
        <p>Markers appear on chart buckets containing recorded samples. Exact recent fill times are listed beside the chart.</p>
        <a href={`/replays/${entry.file}`} download>Download recording <ArrowUpRight size={15} aria-hidden="true" /></a>
      </details>}
      <Link className={styles.prior} href="/replay">Open earlier replay experiments <ArrowUpRight size={14} aria-hidden="true" /></Link>
    </div>
  );
}
