'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ArrowRight, Check, Download, History, Loader2, Pause, Play, RotateCcw, ShieldCheck } from 'lucide-react';
import { ReplayChart } from './ReplayChart';
import { causalCandidate, entryGuardStudy } from '@/lib/research';
import { elapsedText, numberText } from './types';
import type { CatalogRun, QuoteState, ReplayCatalog, ReplayFrame, ReplayRun } from './types';

async function fetchVerifiedRun(entry: CatalogRun, signal: AbortSignal, assetBase: string): Promise<ReplayRun> {
  if (!/^[a-z0-9_-]+-[0-9a-f]{16}\.json$/.test(entry.file)) throw new Error('Invalid replay asset path.');
  const response = await fetch(`${assetBase}/${entry.file}`, { signal });
  if (!response.ok) throw new Error('Replay asset could not be loaded. Regenerate the demo export.');
  const bytes = await response.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  if (hash !== entry.sha256) throw new Error('Replay integrity check failed. Refresh or regenerate the export.');
  const run = JSON.parse(new TextDecoder().decode(bytes)) as ReplayRun;
  if (run.schema_version !== 1 || !run.frames?.length || !Array.isArray(run.fills)) throw new Error('Unsupported replay data.');
  if (run.frames.some(frame => !Number.isFinite(Number(frame.mid)) || !Number.isFinite(Number(frame.pnl)))) throw new Error('Invalid numeric replay data.');
  return run;
}

function frameAt(frames: ReplayFrame[], elapsed: number) {
  let low = 0;
  let high = frames.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (frames[middle].elapsed_ms <= elapsed) low = middle;
    else high = middle - 1;
  }
  return low;
}

export function CaptureReplay() {
  const [catalog, setCatalog] = useState<ReplayCatalog | null>(null);
  const [catalogError, setCatalogError] = useState('');
  const [assetBase, setAssetBase] = useState('/replays');
  const [selection, setSelection] = useState({ session: '', policy: 'ppo' });
  const [loaded, setLoaded] = useState<{ file: string; run: ReplayRun } | null>(null);
  const [loadError, setLoadError] = useState<{ file: string; message: string } | null>(null);
  const [cursor, setCursor] = useState(0);
  const cursorRef = useRef(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(30);
  const [chartMode, setChartMode] = useState<'market' | 'pnl'>('market');

  useEffect(() => {
    const controller = new AbortController();
    const variant = new URLSearchParams(window.location.search).get('variant');
    const base = variant === 'fee' ? '/replays/fee-guard' : variant === 'causal' ? '/replays/causal-candidate' : '/replays';
    fetch(`${base}/catalog.json`, { signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        if (!response.ok) throw new Error('No replay export found. Run the demo exporter first.');
        const value = await response.json() as ReplayCatalog;
        if (value.schema_version !== 1 || !value.sessions?.length || value.held_out_splits_used?.length !== 0 || value.sessions.some(session => session.split !== 'train' || !session.runs.length)) throw new Error('Invalid training-replay catalog.');
        setAssetBase(base);
        setCatalog(value);
      })
      .catch(error => { if (!controller.signal.aborted) setCatalogError(error instanceof Error ? error.message : 'Unable to load replay.'); });
    return () => controller.abort();
  }, []);

  const session = catalog?.sessions.find(item => item.id === selection.session) ?? catalog?.sessions[0];
  const entry = session?.runs.find(item => item.policy === selection.policy) ?? session?.runs[0];
  const run = loaded?.file === entry?.file ? loaded?.run : null;
  const error = loadError?.file === entry?.file ? loadError?.message : '';
  const frame = run?.frames[cursor] ?? run?.frames[0];
  const entryGuard = run?.configuration.entry_fee_buffer_bps != null;
  const decisionLabel = !frame?.decision ? 'Not started' : !frame.decision.quote ? 'Stay out'
    : frame.decision.side_mode === 'buy' ? 'Quote buy side' : frame.decision.side_mode === 'sell' ? 'Quote sell side' : 'Quote both sides';
  const emptyFillMessage = run?.summary.fill_count === 0
    ? 'No simulated fills for this policy in this recording.'
    : 'No simulated fills yet at this point. Play or scrub forward to inspect the execution.';

  useEffect(() => {
    if (!entry) return;
    const controller = new AbortController();
    fetchVerifiedRun(entry, controller.signal, assetBase).then(value => {
      if (controller.signal.aborted) return;
      cursorRef.current = 0;
      setCursor(0);
      setPlaying(false);
      setLoaded({ file: entry.file, run: value });
    }).catch(error => {
      if (!controller.signal.aborted) setLoadError({ file: entry.file, message: error instanceof Error ? error.message : 'Unable to load recording.' });
    });
    return () => controller.abort();
  }, [entry, assetBase]);

  useEffect(() => {
    if (!playing || !run) return;
    const origin = performance.now();
    const start = run.frames[cursorRef.current].elapsed_ms;
    const duration = run.frames[run.frames.length - 1].elapsed_ms;
    const timer = window.setInterval(() => {
      const elapsed = Math.min(duration, start + (performance.now() - origin) * speed);
      const next = frameAt(run.frames, elapsed);
      cursorRef.current = next;
      setCursor(next);
      if (elapsed >= duration) setPlaying(false);
    }, 100);
    return () => window.clearInterval(timer);
  }, [playing, run, speed]);

  function seek(index: number) {
    cursorRef.current = index;
    setCursor(index);
    setPlaying(false);
  }

  function togglePlayback() {
    if (run && cursor >= run.frames.length - 1) seek(0);
    setPlaying(value => !value);
  }

  return (
    <div className="research-workspace replay-workspace">
      <header className="workspace-header"><span className="breadcrumb">Workspace <span>/</span> Real-data replay</span><span className="replay-recorded"><History size={13} aria-hidden="true" /> Recorded market · simulated execution</span></header>
      <div className="workspace-content">
        <div className="research-title">
          <div><div className="eyebrow"><span className="status-dot" /> REAL CAPTURES. VISIBLE EXECUTION.</div><h1>Watch the market. Inspect the fills.</h1><p>Play your captured order book through the queue-aware simulator. Every number comes from the recording and its execution model.</p></div>
          <span className="snapshot-badge"><ShieldCheck size={13} aria-hidden="true" /> Training data only</span>
        </div>
        {!catalog ? (
          <div className="replay-loading" role="status">{catalogError || <><Loader2 size={20} className="animate-spin" /> Loading verified recordings…</>}</div>
        ) : (
          <>
            <nav className="replay-experiments" aria-label="PPO experiment"><a href="/replay" aria-current={assetBase === '/replays' ? 'page' : undefined}>Reference · 16k steps</a><a href="/replay?variant=causal" aria-current={assetBase === '/replays/causal-candidate' ? 'page' : undefined}>Causal + one-sided · experimental</a><a href="/replay?variant=fee" aria-current={assetBase === '/replays/fee-guard' ? 'page' : undefined}>Entry-cost guard · overlay</a><span>Training diagnostics, not held-out results</span></nav>
            <div className="replay-controls research-panel">
              <label>Recording<select aria-label="Recording" value={session?.id ?? ''} onChange={event => { setPlaying(false); seek(0); setSelection(previous => ({ ...previous, session: event.target.value })); }}>{catalog.sessions.map(item => <option key={item.id} value={item.id}>{item.label} · {new Date(item.captured_at_utc).toLocaleDateString('en-GB', { timeZone: 'UTC' })}</option>)}</select></label>
              <label>Policy<select aria-label="Policy" value={entry?.policy ?? ''} onChange={event => { seek(0); setSelection(previous => ({ ...previous, policy: event.target.value })); }}>{session?.runs.map(item => <option key={item.policy} value={item.policy}>{item.label}</option>)}</select></label>
              <div className="replay-data-status"><Check size={15} aria-hidden="true" /><span>{catalog.training_sessions_validated} training captures validated<small>{catalog.model ? 'Saved PPO + baselines · training replay' : 'Rule-based demonstrations · training replay'}</small></span></div>
              {entry && <a className="button-outline replay-download" href={`${assetBase}/${entry.file}`} download><Download size={15} aria-hidden="true" /> Replay JSON</a>}
            </div>
            {!run || !frame ? <div className="replay-loading" role="status">{error || <><Loader2 size={20} className="animate-spin" /> Verifying capture-derived replay…</>}</div> : (
              <>
                {run.model && <section className="research-panel replay-model" aria-label="PPO model information">
                  <div><span className="eyebrow">PPO · TRAINING DEMONSTRATION</span><h2>A saved policy. Visible decisions.</h2><p>Seed {run.model.seed} · {numberText(run.model.total_timesteps, 0)} training steps · {run.model.training_capture_count} training captures. Offline inference from this saved model—not live learning.</p><p>{run.model.observation_schema_version === 2 ? '26 causal features · off / both / buy-only / sell-only actions' : '14-feature reference · both-sides / stay-out actions'}</p><p className="replay-model-caution">{run.summary.fill_count === 0 ? 'No fills in this recording. Zero P&L is inactivity, not a demonstrated trading edge.' : 'Hypothetical execution on data used for training. This does not establish out-of-sample performance.'}</p></div>
                  <div className="replay-decision" data-testid="ppo-decision"><span>Last PPO decision</span><strong>{decisionLabel}</strong><small>{frame.decision?.quote ? `${numberText(frame.decision.half_spread_ticks, 0)}-tick half width · ${frame.decision.skew_ticks > 0 ? '+' : ''}${frame.decision.skew_ticks}-tick skew` : 'No quote requested'}</small><small>Decision at or before this frame; simulated quote state below.</small></div>
                </section>}
                {entryGuard && <aside className="research-panel replay-candidate-result" aria-label="Entry-cost overlay"><strong>Entry-cost rule outside PPO · experimental</strong><p>The saved model is unchanged. Its requested exposure additions can be vetoed when the current-mid edge does not cover the maker fee plus {run.configuration.entry_fee_buffer_bps} bps extra buffer. Zero extra buffer does not mean zero fees. Inventory reductions may pass with capped requested size; pending cancellations still have latency. This rule applies to all displayed controls, is not a forecast, and cannot guarantee a profitable fill.</p><small>The last PPO decision is a request, not a promise that the order was accepted. Inspect the actual simulated quotes below.</small></aside>}
                {entryGuard && run.model?.model_sha256 === causalCandidate.modelSha256 && run.configuration.entry_fee_buffer_bps === '0' && <aside className="research-panel replay-candidate-result" aria-label="All-training guard result"><strong>Loss avoided through inactivity—not a trading edge</strong><p>Same checkpoint, all {entryGuardStudy.trainingCaptures} training captures: unguarded {entryGuardStudy.unguardedFills} fills / {numberText(entryGuardStudy.unguardedNetPnl)} USDT net; guarded {entryGuardStudy.guardedFills} fills / {numberText(entryGuardStudy.guardedNetPnl)} USDT net. Every unguarded fill had instantaneous spread capture below its fee. The guarded result matches doing nothing, not a profitable market maker.</p><small>Training-only rule comparison; no model retraining or held-out validation. Report SHA-256: {entryGuardStudy.reportSha256}</small></aside>}
                {!entryGuard && run.model?.model_sha256 === causalCandidate.modelSha256 && <aside className="research-panel replay-candidate-result" aria-label="All-training candidate result"><strong>Experimental · not promoted</strong><p>Across all {causalCandidate.trainingCaptures} training captures: {causalCandidate.fills} simulated fills · gross marked-to-market P&amp;L +{numberText(causalCandidate.grossPnl)} · fees {numberText(causalCandidate.fees)} · net P&amp;L {numberText(causalCandidate.netPnl)} USDT. The reference made no fills and returned zero. More activity did not improve net performance; the individual recording below is not the full result.</p><small>Single seed, different training budgets, no held-out data. Comparison SHA-256: {causalCandidate.reportSha256}</small></aside>}
                <div className="replay-stats">
                  <Stat label="Market mid · USDT" value={numberText(frame.mid)} />
                  <Stat label="Simulated net P&L · USDT" value={numberText(frame.pnl)} tone={Number(frame.pnl) < 0 ? 'loss' : 'neutral'} />
                  <Stat label="Inventory · BTC" value={numberText(frame.inventory, 4)} />
                  <Stat label="Maker fees · USDT" value={numberText(frame.fees, 4)} />
                  <Stat label="Simulated fills" value={String(frame.fill_count)} />
                </div>
                <div className="replay-grid">
                  <section className="research-panel replay-market" aria-label="Market replay and playback controls">
                    <div className="research-panel-heading"><div><span className="eyebrow">BTC / USDT · {playing ? 'PLAYING RECORDING' : 'PAUSED RECORDING'}</span><h2>{chartMode === 'market' ? 'Recorded mid-price' : 'Simulated account P&L'}</h2></div><div className="replay-tabs"><button type="button" aria-pressed={chartMode === 'market'} onClick={() => setChartMode('market')}>Market</button><button type="button" aria-pressed={chartMode === 'pnl'} onClick={() => setChartMode('pnl')}>P&amp;L</button></div></div>
                    <ReplayChart frames={run.frames} cursor={cursor} mode={chartMode} />
                    <div className="replay-chart-caption"><span>Full recording shown faintly; cursor marks the current state.</span><span>{new Date(frame.time_ms).toISOString().slice(11, 19)} UTC</span></div>
                    <div className="replay-transport">
                      <button className="replay-play" type="button" aria-label={playing ? 'Pause replay' : 'Play replay'} onClick={togglePlayback}>{playing ? <Pause size={17} aria-hidden="true" /> : <Play size={17} aria-hidden="true" />}</button>
                      <button className="replay-reset" type="button" aria-label="Restart replay" onClick={() => seek(0)}><RotateCcw size={16} aria-hidden="true" /></button>
                      <span className="replay-elapsed">{elapsedText(frame.elapsed_ms)}</span>
                      <input type="range" aria-label="Replay position" min={0} max={run.frames.length - 1} value={cursor} onChange={event => seek(Number(event.target.value))} />
                      <span className="replay-elapsed">{elapsedText(run.summary.duration_ms)}</span>
                      <select aria-label="Playback speed" value={speed} onChange={event => setSpeed(Number(event.target.value))}>{[1, 10, 30, 60].map(value => <option key={value} value={value}>{value}×</option>)}</select>
                    </div>
                    <div className="replay-quotes"><Quote label="Our simulated bid" quote={frame.quotes.buy} side="buy" /><Quote label="Our simulated ask" quote={frame.quotes.sell} side="sell" /></div>
                  </section>
                  <OrderBook frame={frame} />
                </div>
                <section className="research-panel replay-fills" aria-labelledby="fills-title">
                  <div className="research-panel-heading"><div><span className="eyebrow">EXECUTION LEDGER</span><h2 id="fills-title">Simulated fills</h2></div><span className="neutral-tag">Most recent 20 at this position</span></div>
                  <div className="replay-table-wrap"><table><thead><tr><th>UTC time</th><th>Side</th><th>Price · USDT</th><th>Quantity · BTC</th><th>Fee · USDT</th><th>Public trade ID</th></tr></thead><tbody>{run.fills.slice(0, frame.fill_count).slice(-20).reverse().map((fill, index) => <tr key={`${fill.order_id}-${fill.trade_id}-${index}`}><td>{new Date(fill.time_ms).toISOString().slice(11, 19)}</td><td className={fill.side === 'buy' ? 'replay-buy' : 'replay-sell'}>{fill.side.toUpperCase()}</td><td>{numberText(fill.price)}</td><td>{numberText(fill.quantity, 4)}</td><td>{numberText(fill.fee, 5)}</td><td>{fill.trade_id}</td></tr>)}</tbody></table>{frame.fill_count === 0 && <div className="replay-empty">{emptyFillMessage}</div>}</div>
                </section>
                <div className="replay-comparison"><span>Full-recording net P&amp;L · training illustration</span><div>{session?.runs.map(item => <button key={item.policy} type="button" aria-pressed={entry?.policy === item.policy} onClick={() => { seek(0); setSelection(previous => ({ ...previous, policy: item.policy })); }}><span>{item.label}</span><strong className={Number(item.summary.pnl) < 0 ? 'replay-loss' : ''}>{numberText(item.summary.pnl)} <small>USDT</small></strong></button>)}</div></div>
                <details className="research-panel replay-provenance"><summary>Execution assumptions &amp; source provenance</summary><p>Market prices and displayed depth are captured Binance Spot L2 data. Orders, queues and fills are simulated with a conservative market-by-price queue approximation. {run.model ? 'Saved PPO decisions were computed offline from the current causal observation.' : 'This is a rule-based policy, not a learned model.'} All results here use training captures—not held-out evaluation, live trading, or proof of profitability. Controls share execution costs and latency; the widest-grid and no-quote controls expose inactivity.</p><dl><div><dt>Maker fee assumption</dt><dd>{numberText(Number(run.configuration.maker_fee_rate) * 100, 2)}% per fill</dd></div><div><dt>Order / cancel latency</dt><dd>{run.configuration.order_latency_ns / 1e6} / {run.configuration.cancel_latency_ns / 1e6} ms</dd></div><div><dt>Quote size / inventory cap</dt><dd>{run.configuration.quantity} / ±{run.configuration.max_abs_inventory} BTC</dd></div><div><dt>Decision / displayed sample interval</dt><dd>{run.configuration.decision_interval_ns / 1e6} / {run.configuration.sample_interval_ns / 1e6} ms</dd></div><div><dt>Capture</dt><dd>{run.source.capture_file}</dd></div><div><dt>Capture SHA-256</dt><dd>{run.source.capture_sha256}</dd></div>{run.model && <><div><dt>Model / metadata</dt><dd>{run.model.model_file} / {run.model.metadata_file}</dd></div><div><dt>Model SHA-256</dt><dd>{run.model.model_sha256}</dd></div><div><dt>Metadata SHA-256</dt><dd>{run.model.metadata_sha256}</dd></div><div><dt>Action schema / width grid</dt><dd>v{run.model.action_schema_version} / {run.model.half_spread_tick_choices?.join(', ') ?? 'Dense integer grid'} ticks</dd></div></>}<div><dt>Replay integrity</dt><dd>Replay asset SHA-256 verified against catalog</dd></div></dl><p>All intervening market events were processed by the simulator. Only displayed frames are sampled. Raw captures and model weights are not bundled. This app needs no Python API, Redis, or exchange connection to play these exported recordings.</p></details>
              </>
            )}
          </>
        )}
        <footer className="research-footer"><span>Real recorded market data. Hypothetical strategy execution. No exchange orders.</span><Link href="/research">Research notes <ArrowRight size={14} aria-hidden="true" /></Link></footer>
      </div>
    </div>
  );
}

function Stat({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: 'loss' | 'neutral' }) {
  return <article><span>{label}</span><strong className={tone === 'loss' ? 'replay-loss' : ''} data-testid={label.startsWith('Simulated net') ? 'net-pnl' : undefined}>{value}</strong></article>;
}

function Quote({ label, quote, side }: { label: string; quote: QuoteState | null; side: 'buy' | 'sell' }) {
  return <div><span>{label}</span><strong className={side === 'buy' ? 'replay-buy' : 'replay-sell'}>{quote ? numberText(quote.price) : '—'}</strong><small>{quote ? `${quote.status}${quote.cancel_pending ? ' · cancel pending' : ''} · ${numberText(quote.queue_ahead, 4)} BTC ahead` : 'No open quote'}</small></div>;
}

function OrderBook({ frame }: { frame: ReplayFrame }) {
  const maximum = Math.max(0.000001, ...frame.bids.map(row => Number(row[1])), ...frame.asks.map(row => Number(row[1])));
  function rows(levels: [string, string][], side: 'buy' | 'sell') {
    return levels.map(([price, quantity]) => <div className={`replay-depth-row replay-${side}`} key={price}><span className="replay-depth-fill" style={{ width: `${Number(quantity) / maximum * 100}%` }} /><span>{numberText(price)}</span><span>{numberText(quantity, 4)}</span></div>);
  }
  return <section className="research-panel replay-book" aria-label="Recorded top five book levels"><div className="research-panel-heading"><div><span className="eyebrow">RECORDED DEPTH</span><h2>Order book</h2></div><span className="neutral-tag">L2 · top 5</span></div><div className="replay-book-columns"><span>Price · USDT</span><span>Size · BTC</span></div>{rows([...frame.asks].reverse(), 'sell')}<div className="replay-book-mid"><strong>{numberText(frame.mid)}</strong><span>Mid-price</span></div>{rows(frame.bids, 'buy')}<p className="replay-book-note">Exchange depth is real. Our hypothetical orders are shown separately.</p></section>;
}
