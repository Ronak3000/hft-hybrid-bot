'use client';

import { useEffect, useState } from 'react';
import type { Direction, Frame, PredictionSession } from './lab-data';
import s from './lab.module.css';

const dirs = [-1, 0, 1] as const;
const name = { [-1]: 'Down', 0: 'Flat', 1: 'Up' };
const prices = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 });
const utc = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3, timeZone: 'UTC' });
type Model = 'logistic' | 'microprice' | 'majority';

function sign(x: number): Direction { return x > 0 ? 1 : x < 0 ? -1 : 0; }

function Chart({ frames, cursor }: { frames: Frame[]; cursor: number }) {
  const points = frames.slice(0, cursor + 1).filter((f) => f[1] === frames[cursor][1]).slice(-160);
  const mid = points.map((f) => f[2]);
  const lo = Math.min(...mid), range = Math.max(...mid) - lo;
  const draw = mid.map((p, i) => [5 + i * 590 / Math.max(mid.length - 1, 1), range ? 188 - ((p - lo) / range) * 176 : 100]);
  const last = draw.at(-1)!;
  return (
    <svg viewBox="0 0 600 200" className={s.chart} role="img" aria-label="Observed mid-price through the current update; future prices are not shown">
      {[50, 100, 150].map((y) => <line key={y} x1="0" x2="600" y1={y} y2={y} stroke="#28354a" />)}
      <polyline points={draw.map((point) => point.join(',')).join(' ')} fill="none" stroke="#93e5cf" strokeWidth="2" />
      <circle cx={last[0]} cy={last[1]} r="3.5" fill="#93e5cf" />
    </svg>
  );
}

export function PredictionReplay({ sessions, horizons }: { sessions: PredictionSession[]; horizons: number[] }) {
  const [sessionIndex, setSession] = useState(0);
  const [horizonIndex, setHorizon] = useState(0);
  const [model, setModel] = useState<Model>('logistic');
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const session = sessions[sessionIndex];
  const frames = session.frames;
  const last = frames.length - 1;
  const horizon = horizons[horizonIndex];
  const current = frames[cursor];

  useEffect(() => {
    if (!playing || cursor >= last) return;
    const timer = window.setTimeout(() => {
      if (cursor + 1 === last) setPlaying(false);
      setCursor(cursor + 1);
    }, 80);
    return () => window.clearTimeout(timer);
  }, [playing, cursor, last]);

  function forecast(frame: Frame): Direction {
    if (model === 'microprice') return sign(frame[4]);
    if (model === 'majority') return session.majority[horizonIndex];
    return frame[7 + horizonIndex] as Direction;
  }
  const counts = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  let scored = 0, correct = 0;
  for (let i = horizon; i <= cursor; i++) {
    const start = frames[i - horizon], end = frames[i];
    if (start[1] !== end[1]) continue;
    const actual = sign(end[2] - start[2]), prediction = forecast(start);
    counts[actual + 1][prediction + 1]++;
    scored++;
    if (actual === prediction) correct++;
  }
  const origin = frames[cursor - horizon];
  const settled = origin && origin[1] === current[1] ? { actual: sign(current[2] - origin[2]), predicted: forecast(origin) } : null;
  const macroF1 = counts.reduce((total, row, i) => {
    const denom = row.reduce((sum, n) => sum + n, 0) + counts.reduce((sum, other) => sum + other[i], 0);
    return total + (denom ? 2 * row[i] / denom : 0);
  }, 0) / 3;
  const fmt = (value: number, digits: number) => value.toFixed(digits);

  return (
    <>
      <section className={s.panel} aria-label="Prediction replay controls">
        <div className={s.controls}>
          <label>Recorded session
            <select value={sessionIndex} onChange={(e) => { setPlaying(false); setCursor(0); setSession(Number(e.target.value)); }}>
              {sessions.map((item, i) => <option value={i} key={item.name}>{item.name.replace('.csv', '')}</option>)}
            </select>
          </label>
          <label>Prediction horizon
            <select value={horizonIndex} onChange={(e) => setHorizon(Number(e.target.value))}>
              {horizons.map((item, i) => <option value={i} key={item}>{item} updates</option>)}
            </select>
          </label>
          <label>Model
            <select value={model} onChange={(e) => setModel(e.target.value as Model)}>
              <option value="logistic">Logistic regression</option><option value="microprice">Microprice rule</option><option value="majority">Training majority</option>
            </select>
          </label>
          <button className={`${s.button} ${s.primary}`} onClick={() => { if (cursor === last) setCursor(0); setPlaying(!playing); }}>{playing ? 'Pause' : 'Play replay'}</button>
          <button className={s.button} disabled={cursor === last} onClick={() => { setPlaying(false); setCursor(cursor + 1); }}>Step +1</button>
          <button className={s.button} onClick={() => { setPlaying(false); setCursor(last); }}>Run to end</button>
          <button className={s.button} onClick={() => { setPlaying(false); setCursor(0); }}>Reset</button>
        </div>
        <label className={s.progress}>Update {cursor + 1} of {frames.length} · {utc.format(current[0])} UTC
          <input type="range" min={0} max={last} value={cursor} onChange={(e) => { setPlaying(false); setCursor(Number(e.target.value)); }} />
        </label>
      </section>
      <div className={s.grid}>
        <article className={s.panel}>
          <h2>Market as observed</h2>
          <div className={s.tiles}>
            <div className={s.tile}><span>Mid-price · USDT</span><strong>{prices.format(current[2])}</strong></div>
            <div className={s.tile}><span>Order-flow imbalance</span><strong>{fmt(current[3], 4)}</strong></div>
            <div className={s.tile}><span>Microprice deviation · bps</span><strong>{fmt(current[4], 5)}</strong></div>
            <div className={s.tile}><span>Depth imbalance</span><strong>{fmt(current[5], 4)}</strong></div>
          </div>
          <Chart frames={frames} cursor={cursor} />
        </article>
        <article className={s.panel}>
          <h2>Prediction vs. outcome</h2>
          <div className={s.tiles}>
            <div className={s.tile}><span>Forecast at this update</span><strong>{name[forecast(current)]}</strong></div>
            <div className={s.tile}><span>Latest settled forecast</span><strong>{settled ? `${name[settled.predicted]} → ${name[settled.actual]}` : 'Not settled'}</strong></div>
            <div className={s.tile}><span>Scored forecasts</span><strong>{scored}</strong></div>
            <div className={s.tile}><span>Accuracy so far</span><strong>{scored ? `${fmt(100 * correct / scored, 1)}%` : '—'}</strong></div>
            <div className={s.tile}><span>Macro-F1 so far</span><strong>{scored ? fmt(macroF1, 3) : '—'}</strong></div>
          </div>
          <p className={s.muted}>An outcome is revealed only after {horizon} updates in the same snapshot segment. Forecasts in the final tail are not scored.</p>
          <div className={s.tableWrap}>
            <table className={s.table}>
              <caption>Confusion matrix: actual rows × predicted columns</caption>
              <thead><tr><th scope="col">Actual</th>{dirs.map((d) => <th key={d} scope="col">{name[d]}</th>)}</tr></thead>
              <tbody>{dirs.map((d) => <tr key={d}><th scope="row">{name[d]}</th>{counts[d + 1].map((count, i) => <td key={i}>{count}</td>)}</tr>)}</tbody>
            </table>
          </div>
        </article>
      </div>
      <details className={s.panel}><summary>Capture provenance</summary><p className={s.hash}>Capture SHA-256: {session.captureSha256}</p><p className={s.hash}>Features SHA-256: {session.featureSha256}</p></details>
    </>
  );
}
