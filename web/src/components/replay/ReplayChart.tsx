import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReplayFrame } from './types';
import { elapsedText, numberText } from './types';

export function ReplayChart({ frames, cursor, mode }: { frames: ReplayFrame[]; cursor: number; mode: 'market' | 'pnl' }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(980);
  useEffect(() => {
    if (!svgRef.current) return;
    const observer = new ResizeObserver(entries => {
      const bounds = entries[0]?.contentRect;
      if (bounds) setWidth(Math.max(300, Math.round(bounds.width)));
    });
    observer.observe(svgRef.current);
    return () => observer.disconnect();
  }, []);
  const dimensions = useMemo(() => {
    const values = frames.flatMap(frame => mode === 'pnl' ? [Number(frame.pnl), 0] : [Number(frame.mid)]);
    const minimum = Math.min(...values);
    const maximum = Math.max(...values);
    const padding = Math.max((maximum - minimum) * 0.12, mode === 'pnl' ? 0.01 : 0.05);
    const low = minimum - padding;
    const high = maximum + padding;
    const duration = Math.max(1, frames[frames.length - 1].elapsed_ms);
    const plotWidth = width - 91;
    const x = (elapsed: number) => 73 + elapsed / duration * plotWidth;
    const y = (value: number) => 24 + (high - value) / (high - low) * 230;
    const path = (limit: number) => frames.slice(0, limit + 1).map((frame, index) => `${index ? 'L' : 'M'}${x(frame.elapsed_ms).toFixed(2)},${y(Number(mode === 'pnl' ? frame.pnl : frame.mid)).toFixed(2)}`).join(' ');
    return { low, high, duration, x, y, path, plotWidth };
  }, [frames, mode, width]);
  const frame = frames[cursor];
  const value = Number(mode === 'pnl' ? frame.pnl : frame.mid);
  const { low, high, duration, x, y, path, plotWidth } = dimensions;
  const color = mode === 'pnl' && value < 0 ? '#e8ad91' : '#b5ed85';

  return (
    <svg ref={svgRef} className="replay-chart" viewBox={`0 0 ${width} 294`} role="img" aria-label={mode === 'market' ? 'Recorded mid-price with current replay position' : 'Simulated fee-inclusive P and L with current replay position'}>
      {[0, 1, 2, 3, 4].map(index => {
        const level = low + (high - low) * index / 4;
        return <g key={index}><line x1="73" x2={width - 18} y1={y(level)} y2={y(level)} stroke="#29362a" strokeDasharray="3 5" /><text x="62" y={y(level) + 3} textAnchor="end">{numberText(level)}</text></g>;
      })}
      {[0, 1, 2, 3, 4].map(index => <text key={index} x={73 + plotWidth * index / 4} y="278" textAnchor="middle">{elapsedText(duration * index / 4)}</text>)}
      <path d={path(frames.length - 1)} fill="none" stroke="#53664e" strokeWidth="1.5" opacity="0.65" />
      <path d={path(cursor)} fill="none" stroke={color} strokeWidth="2" />
      <line x1={x(frame.elapsed_ms)} x2={x(frame.elapsed_ms)} y1="20" y2="254" stroke="#a7bf8e" strokeDasharray="3 5" opacity="0.6" />
      <circle cx={x(frame.elapsed_ms)} cy={y(value)} r="4" fill={color} stroke="#152013" strokeWidth="2" />
    </svg>
  );
}
