'use client';

import { useId, useMemo, useState } from 'react';
import s from './home.module.css';

type Point = { time: number; mid: number };
const price = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const utc = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit', second: '2-digit' });

export function TapePreview({ points }: { points: Point[] }) {
  const [index, setIndex] = useState(points.length - 1);
  const fill = useId();
  const slider = useId();
  const { coords, path } = useMemo(() => {
    const prices = points.map((point) => point.mid);
    const lo = Math.min(...prices);
    const hi = Math.max(...prices);
    const coords = points.map(({ mid }, i) => ({
      x: 14 + i / Math.max(points.length - 1, 1) * 612,
      y: hi === lo ? 130 : 224 - (mid - lo) / (hi - lo) * 191,
    }));
    return { coords, path: coords.map(({ x, y }) => `${x},${y}`).join(' ') };
  }, [points]);
  const current = coords[index];
  const midPrice = price.format(points[index].mid);
  const time = utc.format(points[index].time);
  return (
    <article className={s.tape} aria-labelledby="tape-preview-title">
      <div className={s.tapeHeading}>
        <div><span className={s.eyebrow}>RECORDED TAPE / 01</span><h2 id="tape-preview-title">BTC / USDT</h2></div>
        <span className={s.badge}>Binance Spot</span>
      </div>
      <div className={s.plot}>
        <span className={s.plotGuide}>MID-PRICE · NOT LIVE</span>
        <svg viewBox="0 0 640 260" role="img" aria-label="Recorded Bitcoin mid-price. Use the chart slider to inspect earlier updates.">
          <defs><linearGradient id={fill} x1="0" x2="0" y1="0" y2="1"><stop stopColor="#52e6c4" stopOpacity=".36"/><stop offset="100%" stopColor="#52e6c4" stopOpacity="0"/></linearGradient></defs>
          {[32, 80, 128, 176, 224].map((y) => <line key={y} x1="0" y1={y} x2="640" y2={y} stroke="#26374c" />)}
          {[14, 167, 320, 473, 626].map((x) => <line key={x} x1={x} y1="12" x2={x} y2="244" stroke="#26374c" />)}
          <polygon points={`14,245 ${path} 626,245`} fill={`url(#${fill})`} />
          <polyline points={path} fill="none" stroke="#52e6c4" strokeWidth="2.4" strokeLinejoin="round" />
          <line x1={current.x} y1="12" x2={current.x} y2="245" stroke="#91efdc" strokeDasharray="5 5" />
          <circle cx={current.x} cy={current.y} r="7" fill="#102d35" stroke="#8cf4db" strokeWidth="2.5" />
        </svg>
      </div>
      <div className={s.readout}>
        <div><strong>{midPrice}</strong><span>{time} UTC · observed mid (USDT)</span></div>
        <label htmlFor={slider}>Inspect recording<input id={slider} type="range" min="0" max={points.length - 1} value={index} aria-valuetext={`${midPrice} USDT at ${time} UTC`} onChange={(event) => setIndex(Number(event.target.value))} /></label>
      </div>
    </article>
  );
}
