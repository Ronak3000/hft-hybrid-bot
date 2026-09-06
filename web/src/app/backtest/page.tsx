'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  BarChart2,
  CandlestickChart,
  CheckCircle2,
  Database,
  History,
  Loader2,
  Play,
  TrendingUp,
} from 'lucide-react';
import {
  CandlestickSeries,
  ColorType,
  createChart,
  IChartApi,
  LineSeries,
  Time,
} from 'lightweight-charts';
import { API_BASE } from '@/lib/api';

const SUPPORTED_ASSETS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT'];
const TIMEFRAMES = [
  { label: '30 Minutes (30m)', value: '30m' },
  { label: '2 Hours (2h)', value: '2h' },
  { label: '4 Hours (4h)', value: '4h' },
];

interface CandleData {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface HistoricalResponse {
  data?: Array<{
    time: number;
    open: number;
    high: number;
    low: number;
    close: number;
  }>;
  detail?: string;
}

export default function BacktestPage() {
  const [symbol, setSymbol] = useState('BTC/USDT');
  const [timeframe, setTimeframe] = useState('30m');
  const [status, setStatus] = useState<'IDLE' | 'FETCHING' | 'COMPLETE'>('IDLE');
  const [logs, setLogs] = useState<string[]>([]);
  const [chartType, setChartType] = useState<'candlestick' | 'line'>('candlestick');

  const historicalData = useRef<CandleData[] | null>(null);
  const chartTypeRef = useRef(chartType);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chartTypeRef.current = chartType;
  }, [chartType]);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => () => chartRef.current?.remove(), []);

  const renderChart = useCallback((candles: CandleData[]) => {
    if (!chartContainerRef.current) return;

    chartRef.current?.remove();
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
      layout: { background: { type: ColorType.Solid, color: '#0D1117' }, textColor: '#A1A1AA' },
      grid: { vertLines: { color: '#1F2937' }, horzLines: { color: '#1F2937' } },
      timeScale: { timeVisible: true, borderColor: '#1F2937' },
      rightPriceScale: { borderColor: '#1F2937', autoScale: true },
    });
    chartRef.current = chart;

    if (chartTypeRef.current === 'candlestick') {
      const series = chart.addSeries(CandlestickSeries, {
        upColor: '#10B981',
        downColor: '#EF4444',
        borderVisible: false,
        wickUpColor: '#10B981',
        wickDownColor: '#EF4444',
      });
      series.setData(candles);
    } else {
      const series = chart.addSeries(LineSeries, {
        color: '#a855f7',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      series.setData(candles.map((candle) => ({ time: candle.time, value: candle.close })));
    }

    chart.timeScale().fitContent();
  }, []);

  useEffect(() => {
    if (historicalData.current) renderChart(historicalData.current);
  }, [chartType, renderChart]);

  const handleLoadData = async () => {
    setStatus('FETCHING');
    setLogs([`[${new Date().toLocaleTimeString()}] Requesting historical OHLCV data for ${symbol} (${timeframe})...`]);
    historicalData.current = null;

    try {
      const response = await fetch(
        `${API_BASE}/api/backtest/ohlcv?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`,
      );
      const payload = (await response.json()) as HistoricalResponse;

      if (!response.ok) throw new Error(payload.detail || 'Historical data request failed.');
      if (!payload.data?.length) throw new Error('No data returned by the exchange-data endpoint.');

      const candles: CandleData[] = payload.data.map((candle) => ({
        ...candle,
        time: candle.time as Time,
      }));

      historicalData.current = candles;
      renderChart(candles);
      setLogs((previous) => [
        ...previous,
        `[${new Date().toLocaleTimeString()}] Loaded ${candles.length} OHLCV candles for visualization.`,
        `[${new Date().toLocaleTimeString()}] No policy was executed and no performance metrics were calculated.`,
      ]);
      setStatus('COMPLETE');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown historical data error.';
      setLogs((previous) => [...previous, `[${new Date().toLocaleTimeString()}] Error: ${message}`]);
      setStatus('IDLE');
    }
  };

  return (
    <div className="min-h-screen bg-zinc-950 p-6 font-sans text-zinc-50">
      <header className="mb-8 border-b border-zinc-800 pb-4">
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <History className="text-purple-500" /> Historical Data Preview
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          Visualize exchange OHLCV candles. Strategy evaluation is not implemented yet.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <div className="space-y-6 lg:col-span-1">
          <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 shadow-lg">
            <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
              <Database size={16} /> Data Parameters
            </h2>

            <div className="space-y-5">
              <div>
                <label className="mb-1 block text-xs text-zinc-500">Target Asset</label>
                <select
                  value={symbol}
                  onChange={(event) => setSymbol(event.target.value)}
                  disabled={status === 'FETCHING'}
                  className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm transition-colors focus:border-purple-500 focus:outline-none disabled:opacity-50"
                >
                  {SUPPORTED_ASSETS.map((asset) => <option key={asset} value={asset}>{asset}</option>)}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs text-zinc-500">Candle Timeframe</label>
                <select
                  value={timeframe}
                  onChange={(event) => setTimeframe(event.target.value)}
                  disabled={status === 'FETCHING'}
                  className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm transition-colors focus:border-purple-500 focus:outline-none disabled:opacity-50"
                >
                  {TIMEFRAMES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </div>

              <button
                onClick={handleLoadData}
                disabled={status === 'FETCHING'}
                className="flex w-full items-center justify-center gap-2 rounded-md bg-purple-600 py-3 font-semibold text-white transition-colors hover:bg-purple-500 disabled:bg-zinc-800 disabled:text-zinc-500"
              >
                {status === 'FETCHING' ? (
                  <><Loader2 size={16} className="animate-spin" /> Loading...</>
                ) : (
                  <><Play fill="currentColor" size={16} /> Load Data Preview</>
                )}
              </button>
            </div>
          </div>
        </div>

        <div className="space-y-6 lg:col-span-3">
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">
            This page does not execute a strategy. P&amp;L, fills, win rate, and drawdown remain unavailable until the deterministic evaluation pipeline is implemented.
          </div>

          <div className="relative flex h-[500px] flex-col overflow-hidden rounded-xl border border-zinc-800 bg-[#0D1117] shadow-2xl">
            <div className="z-10 flex items-center justify-between border-b border-zinc-800 bg-zinc-900 px-4 py-3 shadow-sm">
              <div className="flex items-center gap-4">
                <BarChart2 size={16} className="text-purple-500" />
                <span className="text-sm font-bold">{symbol}</span>
                <span className="rounded bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-200">Candles: {timeframe}</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-0.5 rounded-lg border border-zinc-700 bg-zinc-950 p-0.5">
                  <button
                    onClick={() => setChartType('candlestick')}
                    title="Candlestick Chart"
                    className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all ${chartType === 'candlestick' ? 'bg-purple-600 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}
                  >
                    <CandlestickChart size={13} /> Candles
                  </button>
                  <button
                    onClick={() => setChartType('line')}
                    title="Line Chart"
                    className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all ${chartType === 'line' ? 'bg-purple-600 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}
                  >
                    <TrendingUp size={13} /> Line
                  </button>
                </div>
                {status === 'COMPLETE' && (
                  <span className="flex items-center gap-2 text-xs text-emerald-500">
                    <CheckCircle2 size={14} /> Data Loaded
                  </span>
                )}
              </div>
            </div>

            <div className="relative h-full w-full flex-1">
              {status === 'IDLE' && (
                <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-[#0D1117] text-zinc-600">
                  <History size={48} className="mb-4 opacity-20" />
                  <p>Choose a symbol and load historical candles.</p>
                </div>
              )}
              <div ref={chartContainerRef} className="absolute inset-0 h-full w-full" />
            </div>
          </div>

          <div className="h-48 overflow-y-auto rounded-xl border border-zinc-800 bg-[#0a0a0a] p-4 font-mono text-xs shadow-inner">
            <div className="space-y-1.5">
              {logs.length === 0 ? (
                <p className="italic text-zinc-700">Data preview idle. No strategy evaluation is running.</p>
              ) : (
                logs.map((log, index) => (
                  <p key={`${index}-${log}`} className={log.includes('Error') ? 'text-red-400' : 'text-zinc-400'}>{log}</p>
                ))
              )}
              <div ref={terminalEndRef} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
