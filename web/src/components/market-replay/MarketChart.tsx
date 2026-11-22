'use client';

import { useEffect, useRef } from 'react';
import {
  AreaSeries, CandlestickSeries, ColorType, CrosshairMode, createChart, createSeriesMarkers,
  type AreaData, type CandlestickData, type IChartApi, type ISeriesApi,
  type ISeriesMarkersPluginApi, type SeriesMarker, type Time, type UTCTimestamp,
} from 'lightweight-charts';
import { formatClock, type RecordedFill, type RecordedFrame } from './recording';
import styles from './market-replay.module.css';

export type ChartMode = 'mid' | 'candles' | 'pnl';

const MINT = '#52e6c4';
const VIOLET = '#a594ff';
const SELL = '#f8a1a6';
const CANDLE_SECONDS = 5;

const bucket = (ms: number, seconds: number) => (Math.floor(ms / (1000 * seconds)) * seconds) as UTCTimestamp;

function addAreaPoint(points: AreaData<UTCTimestamp>[], frame: RecordedFrame, pnl: boolean) {
  const point = { time: bucket(frame.time_ms, 1), value: Number(pnl ? frame.pnl : frame.mid) };
  if (points.at(-1)?.time === point.time) points[points.length - 1] = point;
  else points.push(point);
  return point;
}

function addCandle(points: CandlestickData<UTCTimestamp>[], frame: RecordedFrame) {
  const time = bucket(frame.time_ms, CANDLE_SECONDS);
  const price = Number(frame.mid);
  const last = points.at(-1);
  if (last?.time === time) {
    const point = { ...last, high: Math.max(last.high, price), low: Math.min(last.low, price), close: price };
    points[points.length - 1] = point;
    return point;
  }
  const point = { time, open: price, high: price, low: price, close: price };
  points.push(point);
  return point;
}

function fillMarkers(points: { time: UTCTimestamp }[], fills: RecordedFill[], fillCount: number, isCandles: boolean) {
  const plotted = new Set(points.map((point) => point.time));
  const edges = new Map<UTCTimestamp, Set<'buy' | 'sell'>>();
  for (let i = 0; i < fillCount && i < fills.length; i++) {
    const fill = fills[i];
    const time = bucket(fill.time_ms, isCandles ? CANDLE_SECONDS : 1);
    if (!plotted.has(time)) continue;
    const sides = edges.get(time) ?? new Set();
    sides.add(fill.side);
    edges.set(time, sides);
  }
  return [...edges].sort(([a], [b]) => a - b).flatMap(([time, sides]): SeriesMarker<Time>[] =>
    [...sides].map(side => ({
      time, position: side === 'buy' ? 'belowBar' : 'aboveBar',
      color: side === 'buy' ? MINT : SELL, shape: side === 'buy' ? 'arrowUp' : 'arrowDown',
      size: 1,
    })),
  );
}

type ChartState = {
  chart: IChartApi;
  markers: ISeriesMarkersPluginApi<Time>;
  frames?: RecordedFrame[];
  cursor: number;
  appliedFills: number;
} & (
  { mode: 'candles'; series: ISeriesApi<'Candlestick'>; points: CandlestickData<UTCTimestamp>[] } |
  { mode: 'mid' | 'pnl'; series: ISeriesApi<'Area'>; points: AreaData<UTCTimestamp>[] }
);

const axisTime = (time: Time) => typeof time === 'number' ? formatClock.format(time * 1000) : String(time);

export function MarketChart({ frames, fills, cursor, mode, fit, showFills }: {
  frames: RecordedFrame[];
  fills: RecordedFill[];
  cursor: number;
  mode: ChartMode;
  fit: number;
  showFills: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chartState = useRef<ChartState | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#0a1421' },
        textColor: '#a5b5c9', attributionLogo: true,
      },
      grid: { vertLines: { color: '#13243a' }, horzLines: { color: '#13243a' } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#59728f', labelBackgroundColor: '#263c54' },
        horzLine: { color: '#59728f', labelBackgroundColor: '#263c54' },
      },
      localization: { timeFormatter: axisTime },
      rightPriceScale: { borderColor: '#24354a', scaleMargins: { top: 0.14, bottom: 0.17 } },
      timeScale: {
        borderColor: '#24354a', timeVisible: true, secondsVisible: true,
        tickMarkFormatter: axisTime, rightOffset: 7, barSpacing: mode === 'candles' ? 12 : 5,
      },
    });
    if (mode === 'candles') {
      const series = chart.addSeries(CandlestickSeries, {
        upColor: MINT, downColor: '#ea8092', wickUpColor: MINT, wickDownColor: '#ea8092',
        borderVisible: false,
        priceFormat: { type: 'price', precision: 3, minMove: 0.005 },
      });
      chartState.current = { chart, mode, series, markers: createSeriesMarkers(series), points: [], cursor: -1, appliedFills: -1 };
    } else {
      const isPnl = mode === 'pnl';
      const series = chart.addSeries(AreaSeries, {
        lineWidth: 2, lineColor: isPnl ? VIOLET : MINT,
        topColor: isPnl ? '#a594ff40' : '#52e6c43d',
        bottomColor: isPnl ? '#a594ff02' : '#52e6c402',
        priceFormat: { type: 'price', precision: 3, minMove: isPnl ? 0.001 : 0.005 },
        crosshairMarkerBorderColor: '#0a1421', crosshairMarkerRadius: 4,
      });
      chartState.current = { chart, mode, series, markers: createSeriesMarkers(series), points: [], cursor: -1, appliedFills: -1 };
    }
    return () => {
      chartState.current = null;
      chart.remove();
    };
  }, [mode]);

  useEffect(() => {
    const state = chartState.current;
    if (!state) return;
    const replace = state.frames !== frames || cursor < state.cursor || cursor - state.cursor > 32;
    const start = replace ? 0 : state.cursor + 1;
    if (state.mode === 'candles') {
      if (replace) state.points = [];
      for (let i = start; i <= cursor; i++) {
        const point = addCandle(state.points, frames[i]);
        if (!replace) state.series.update(point);
      }
      if (replace) state.series.setData(state.points);
    } else {
      if (replace) state.points = [];
      for (let i = start; i <= cursor; i++) {
        const point = addAreaPoint(state.points, frames[i], state.mode === 'pnl');
        if (!replace) state.series.update(point);
      }
      if (replace) state.series.setData(state.points);
    }
    const revealedFills = showFills && state.mode !== 'pnl' ? frames[cursor].fill_count : 0;
    if (replace || revealedFills !== state.appliedFills) {
      state.markers.setMarkers(fillMarkers(state.points, fills, revealedFills, state.mode === 'candles'));
    }
    if (replace) state.chart.timeScale().scrollToRealTime();
    state.frames = frames;
    state.cursor = cursor;
    state.appliedFills = revealedFills;
  }, [frames, fills, cursor, mode, showFills]);

  useEffect(() => {
    if (fit > 0) chartState.current?.chart.timeScale().fitContent();
  }, [fit]);

  return (
    <div
      className={styles.chartCanvas}
      ref={host}
      role="img"
      aria-label={mode === 'pnl' ? 'Simulated profit and loss to the current replay point' : 'Recorded BTC/USDT mid-price to the current replay point'}
    />
  );
}
