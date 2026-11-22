'use client';

import { useEffect, useId, useState } from 'react';
import type { Direction, Frame, PredictionSession } from './lab-data';
import s from './lab.module.css';

const dirs = [-1, 0, 1] as const;
const name = { [-1]: 'Down', 0: 'Flat', 1: 'Up' };
const prices = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 });
const utc = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3, timeZone: 'UTC' });
const directionStyle = { [-1]: s.directionDown, 0: s.directionFlat, 1: s.directionUp };
const glyph = { [-1]: '↘', 0: '→', 1: '↗' };
type Model = 'logistic' | 'microprice' | 'majority';

function sign(x: number): Direction { return x > 0 ? 1 : x < 0 ? -1 : 0; }

function Chart({ frames, cursor }: { frames: Frame[]; cursor: number }) {
  const fill = useId();
  const points = frames.slice(Math.max(0, cursor - 159), cursor + 1).filter((f) => f[1] === frames[cursor][1]);
  const mid = points.map((f) => f[2]);
  const lo = Math.min(...mid), hi = Math.max(...mid), range = hi - lo;
  const draw = mid.map((p, i) => [10 + i * 580 / Math.max(mid.length - 1, 1), range ? 171 - ((p - lo) / range) * 146 : 98]);
  const line = draw.map((point) => point.join(',')).join(' ');
  const last = draw.at(-1)!;
  return (
    <figure className={s.chart}>
      <div className={s.chartPlot}>
        <svg viewBox="0 0 600 200" preserveAspectRatio="none" role="img" aria-label="Observed mid-price through the current update; future prices are not shown">
          <defs>
            <linearGradient id={fill} x1="0" x2="0" y1="0" y2="1" gradientUnits="objectBoundingBox">
              <stop stopColor="#52e6c4" stopOpacity=".25" />
              <stop offset="1" stopColor="#52e6c4" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[25, 74, 122, 171].map((y) => <line key={y} x1="0" x2="600" y1={y} y2={y} className={s.chartGridLine} />)}
          {[10, 126, 242, 358, 474, 590].map((x) => <line key={x} x1={x} x2={x} y1="0" y2="200" className={s.chartGridLine} />)}
          <polygon points={`${draw[0][0]},197 ${line} ${last[0]},197`} fill={`url(#${fill})`} />
          <line x1="0" x2="600" y1={last[1]} y2={last[1]} stroke="#52e6c4" opacity=".4" strokeDasharray="4 5" />
          <polyline points={line} fill="none" stroke="#52e6c4" strokeWidth="2" vectorEffect="non-scaling-stroke" />
          <circle cx={last[0]} cy={last[1]} r="3.5" fill="#52e6c4" />
        </svg>
        <div className={s.chartPrices} aria-hidden="true"><span>{prices.format(hi)}</span><span>{prices.format(lo)}</span></div>
      </div>
      <figcaption className={s.chartCaption}><span>{points.length === 1 ? 'First update of this view' : `Last ${points.length} observed updates`}</span><span>Mid-price · USDT</span></figcaption>
    </figure>
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
  const prediction = forecast(current);
  const macroF1 = counts.reduce((total, row, i) => {
    const denom = row.reduce((sum, n) => sum + n, 0) + counts.reduce((sum, other) => sum + other[i], 0);
    return total + (denom ? 2 * row[i] / denom : 0);
  }, 0) / 3;
  const fmt = (value: number, digits: number) => value.toFixed(digits);

  return (
    <>
      <section className={s.panel} aria-labelledby="prediction-replay-title">
        <div className={s.sectionHeading}><div><span className={s.kicker}>01 / Replay desk</span><h2 id="prediction-replay-title">Follow the next move</h2></div><span className={s.tag}>Baseline replay</span></div>
        <p className={s.note}>Watch a recorded session or jump to the verdict. Forecasts are scored only when the selected horizon has elapsed.</p>
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
        </div>
        <div className={s.replayGrid}>
          <article className={s.chartCard}>
            <div className={s.priceHeading}><span className={s.kicker}>Observed mid-price</span><strong>{prices.format(current[2])}</strong><span>USDT</span></div>
            <Chart frames={frames} cursor={cursor} />
          </article>
          <article className={s.forecastCard}>
            <h3 className={s.kicker}>Forecast at this update</h3>
            <div className={`${s.forecastDirection} ${directionStyle[prediction]}`}><span aria-hidden="true">{glyph[prediction]}</span> {name[prediction]}</div>
            <div className={s.settlement}>
              <span>Latest settled forecast</span>
              <strong>{settled ? `${name[settled.predicted]} → ${name[settled.actual]}` : 'Not settled'}</strong>
              <small>{!settled ? `Requires ${horizon} updates in the same segment.` : settled.actual === settled.predicted ? 'Prediction matched the outcome.' : 'Prediction missed the outcome.'}</small>
            </div>
          </article>
        </div>
        <div className={s.transport}>
          <div className={s.buttons}>
            <button type="button" className={`${s.button} ${s.primary}`} onClick={() => { if (cursor === last) setCursor(0); setPlaying(!playing); }}>{playing ? 'Pause' : 'Play replay'}</button>
            <button type="button" className={s.button} disabled={cursor === last} onClick={() => { setPlaying(false); setCursor(cursor + 1); }}>Step +1</button>
            <button type="button" className={s.button} onClick={() => { setPlaying(false); setCursor(last); }}>Run to end</button>
            <button type="button" className={s.button} onClick={() => { setPlaying(false); setCursor(0); }}>Reset</button>
          </div>
          <label className={s.progress}><span>Update {cursor + 1} of {frames.length} <time dateTime={new Date(current[0]).toISOString()}>{utc.format(current[0])} UTC</time></span>
            <input type="range" min={0} max={last} value={cursor} onChange={(e) => { setPlaying(false); setCursor(Number(e.target.value)); }} />
          </label>
        </div>
        <details className={s.replayDetail}>
          <summary className={s.detailSummary}>Replay statistics and capture provenance</summary>
          <dl className={s.tiles}>
            <div className={s.tile}><dt>Forecasts scored</dt><dd>{scored}</dd></div>
            <div className={s.tile}><dt>Accuracy so far</dt><dd>{scored ? `${fmt(100 * correct / scored, 1)}%` : '—'}</dd></div>
            <div className={s.tile}><dt>Macro-F1 so far</dt><dd>{scored ? fmt(macroF1, 3) : '—'}</dd></div>
            <div className={s.tile}><dt>Order-flow imbalance</dt><dd>{fmt(current[3], 4)}</dd></div>
            <div className={s.tile}><dt>Microprice deviation · bps</dt><dd>{fmt(current[4], 5)}</dd></div>
            <div className={s.tile}><dt>Depth imbalance</dt><dd>{fmt(current[5], 4)}</dd></div>
          </dl>
          <p className={s.note}>Forecasts in the final tail are not scored. Playback uses saved baseline forecasts; it does not train a model or submit orders.</p>
          <div className={s.tableWrap}>
            <table className={s.table}>
              <caption>Confusion matrix: actual rows × predicted columns</caption>
              <thead><tr><th scope="col">Actual</th>{dirs.map((d) => <th key={d} scope="col">{name[d]}</th>)}</tr></thead>
              <tbody>{dirs.map((d) => <tr key={d}><th scope="row">{name[d]}</th>{counts[d + 1].map((count, i) => <td key={i}>{count}</td>)}</tr>)}</tbody>
            </table>
          </div>
          <p className={s.hash}>Capture SHA-256: <code>{session.captureSha256}</code></p>
          <p className={s.hash}>Features SHA-256: <code>{session.featureSha256}</code></p>
        </details>
      </section>
    </>
  );
}
