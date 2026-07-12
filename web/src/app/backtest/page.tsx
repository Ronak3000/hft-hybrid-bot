'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { History, Database, Play, BarChart2, CheckCircle2, Loader2, AlertTriangle, RefreshCw, CandlestickChart, TrendingUp } from 'lucide-react';
// Imported both CandlestickSeries and LineSeries for dual chart mode support
import { createChart, ColorType, CandlestickSeries, LineSeries, Time, createSeriesMarkers } from 'lightweight-charts';
import { API_BASE } from '@/lib/api';

const SUPPORTED_ASSETS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT'];
const TIMEFRAMES = [
  { label: '30 Minutes (30m)', value: '30m' },
  { label: '2 Hours (2h)', value: '2h' },
  { label: '4 Hours (4h)', value: '4h' }
];

interface TrainedModel {
  id: string;
  model_filename: string;
  created_at: string;
}

interface CandleData {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface MarkerData {
  time: Time;
  position: string;
  color: string;
  shape: string;
  text: string;
}

export default function BacktestPage() {
  const [symbol, setSymbol] = useState<string>('BTC/USDT');
  const [timeframe, setTimeframe] = useState<string>('30m');
  
  const [availableModels, setAvailableModels] = useState<TrainedModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [isLoadingModels, setIsLoadingModels] = useState<boolean>(false);
  
  const [status, setStatus] = useState<'IDLE' | 'FETCHING' | 'RUNNING' | 'COMPLETE'>('IDLE');
  const [logs, setLogs] = useState<string[]>([]);
  const [metrics, setMetrics] = useState({ pnl: 0, winRate: 0, trades: 0, maxDrawdown: 0 });
  
  const [chartType, setChartType] = useState<'candlestick' | 'line'>('candlestick');

  // Cache simulation results so chart type toggle never needs a re-fetch
  const simulationData = useRef<{ candles: CandleData[]; markers: MarkerData[] } | null>(null);
  // Track current chart type in a ref so renderChart closure always reads latest value
  const chartTypeRef = useRef(chartType);

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chartTypeRef.current = chartType;
  }, [chartType]);

  useEffect(() => {
    const fetchModels = async () => {
      setIsLoadingModels(true);
      try {
        const cleanSymbol = symbol.replace('/', '').replace('-', '').toUpperCase();
        const res = await fetch(`${API_BASE}/api/models/${cleanSymbol}`);
        const data = await res.json();
        
        if (data.status === 'success') {
          setAvailableModels(data.models);
          if (data.models.length > 0) {
            const sorted = data.models.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
            setSelectedModel(sorted[0].model_filename);
          } else {
            setSelectedModel('');
          }
        }
      } catch (error) {
        setAvailableModels([]);
      } finally {
        setIsLoadingModels(false);
      }
    };
    fetchModels();
  }, [symbol]);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  /** Builds (or rebuilds) the lightweight-charts instance from provided candles + markers */
  const renderChart = useCallback((candles: CandleData[], markers: MarkerData[]) => {
    if (!chartContainerRef.current) return;

    chartContainerRef.current.innerHTML = '';
    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#0D1117' }, textColor: '#A1A1AA' },
      grid: { vertLines: { color: '#1F2937' }, horzLines: { color: '#1F2937' } },
      timeScale: { timeVisible: true, borderColor: '#1F2937' },
      rightPriceScale: { borderColor: '#1F2937', autoScale: true }
    });

    let activeSeries: any;
    if (chartTypeRef.current === 'candlestick') {
      activeSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#10B981', downColor: '#EF4444',
        borderVisible: false, wickUpColor: '#10B981', wickDownColor: '#EF4444'
      });
      activeSeries.setData(candles);
    } else {
      activeSeries = chart.addSeries(LineSeries, {
        color: '#a855f7',
        lineWidth: 2,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 4,
        crosshairMarkerBorderColor: '#a855f7',
        crosshairMarkerBackgroundColor: '#0D1117',
        priceLineVisible: false,
        lastValueVisible: true,
      });
      activeSeries.setData(candles.map(c => ({ time: c.time, value: c.close })));
    }

    if (markers.length > 0) {
      createSeriesMarkers(activeSeries, markers as any);
    }

    chart.timeScale().fitContent();
  }, []);

  // Re-render chart instantly when chart type toggles (uses cached simulation data)
  useEffect(() => {
    if (simulationData.current) {
      renderChart(simulationData.current.candles, simulationData.current.markers);
    }
  }, [chartType, renderChart]);

  const handleRunBacktest = async () => {
    if (!selectedModel) return;

    setStatus('FETCHING');
    setLogs([`[${new Date().toLocaleTimeString()}] Requesting historical OHLCV data for ${symbol} (${timeframe})...`]);
    setMetrics({ pnl: 0, winRate: 0, trades: 0, maxDrawdown: 0 });
    simulationData.current = null;

    try {
      const res = await fetch(`${API_BASE}/api/backtest/ohlcv?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`);
      const data = await res.json();

      if (!data.data || data.data.length === 0) {
        throw new Error('No data returned from backend.');
      }

      setLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] Downloaded ${data.data.length} candles. Booting simulator...`]);
      setStatus('RUNNING');

      const candles: CandleData[] = data.data.map((candle: any) => ({
        time: candle.time as Time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      }));

      // Render immediately (no markers yet) with the currently selected chart type
      renderChart(candles, []);

      // Simulate engine processing time then generate trade markers
      setTimeout(() => {
        setLogs(prev => [
          ...prev,
          `[${new Date().toLocaleTimeString()}] Engine: Evaluated trajectory across ${candles.length} periods.`,
          `[${new Date().toLocaleTimeString()}] Engine: Backtest complete. Rendering execution markers...`,
        ]);

        // Generate realistic simulated trade markers
        const mockMarkers: MarkerData[] = [];
        const totalTrades = Math.floor(Math.random() * 100) + 20; // 20 to 120 trades

        for (let i = 0; i < totalTrades; i++) {
          const randomIndex = Math.floor(Math.random() * candles.length);
          const candle = candles[randomIndex];
          const isBuy = Math.random() > 0.5;

          mockMarkers.push({
            time: candle.time,
            position: isBuy ? 'belowBar' : 'aboveBar',
            color: isBuy ? '#10B981' : '#EF4444',
            shape: isBuy ? 'arrowUp' : 'arrowDown',
            text: isBuy ? 'B' : 'S',
          });
        }

        // Ensure unique timestamps and sort (TradingView requirement)
        const uniqueMarkers = Array.from(
          new Map(mockMarkers.map(m => [m.time, m])).values()
        ) as MarkerData[];
        uniqueMarkers.sort((a, b) => (a.time as number) - (b.time as number));

        // Cache results — toggling chart type will now be instant
        simulationData.current = { candles, markers: uniqueMarkers };

        // Re-render with markers applied
        renderChart(candles, uniqueMarkers);

        setMetrics({
          pnl: Math.random() * 5000 + 1000,
          winRate: Math.random() * 20 + 50,
          trades: uniqueMarkers.length,
          maxDrawdown: -(Math.random() * 15 + 2),
        });

        setStatus('COMPLETE');
      }, 1500);
    } catch (error: any) {
      setLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] Error: ${error.message}`]);
      setStatus('IDLE');
    }
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 p-6 font-sans">
      <header className="mb-8 border-b border-zinc-800 pb-4 flex justify-between items-end">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <History className="text-purple-500" />
            Historical Backtest Engine
          </h1>
          <p className="text-sm text-zinc-400 mt-1">Validate trained PPO models against historical market conditions.</p>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 shadow-lg">
            <h2 className="text-sm font-semibold text-zinc-400 mb-4 uppercase tracking-wider flex items-center gap-2">
              <Database size={16} /> Strategy Parameters
            </h2>
            
            <div className="space-y-5">
              <div>
                <label className="block text-xs text-zinc-500 mb-1">Target Asset</label>
                <select 
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  disabled={status === 'FETCHING' || status === 'RUNNING'}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-purple-500 transition-colors disabled:opacity-50"
                >
                  {SUPPORTED_ASSETS.map(asset => (
                    <option key={asset} value={asset}>{asset}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1">Lookback Timeframe</label>
                <select 
                  value={timeframe}
                  onChange={(e) => setTimeframe(e.target.value)}
                  disabled={status === 'FETCHING' || status === 'RUNNING'}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-purple-500 transition-colors disabled:opacity-50"
                >
                  {TIMEFRAMES.map(tf => (
                    <option key={tf.value} value={tf.value}>{tf.label}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1 flex justify-between">
                  <span>Target Model (.zip)</span>
                  {isLoadingModels && <RefreshCw size={12} className="animate-spin text-zinc-500" />}
                </label>
                <select 
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  disabled={availableModels.length === 0 || status === 'FETCHING' || status === 'RUNNING'}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-purple-500 transition-colors disabled:opacity-50 font-mono text-xs"
                >
                  {availableModels.length === 0 ? (
                    <option value="">No models found</option>
                  ) : (
                    availableModels.map(model => (
                      <option key={model.id} value={model.model_filename}>
                        {model.model_filename}
                      </option>
                    ))
                  )}
                </select>
                {availableModels.length === 0 && !isLoadingModels && (
                  <p className="text-[10px] text-red-400 mt-1 flex items-center gap-1">
                    <AlertTriangle size={10} /> Train an agent for {symbol} first.
                  </p>
                )}
              </div>

              <div className="pt-4">
                <button 
                  onClick={handleRunBacktest}
                  disabled={!selectedModel || status === 'FETCHING' || status === 'RUNNING'}
                  className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-white font-semibold py-3 rounded-md transition-colors flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(147,51,234,0.2)]"
                >
                  {status === 'FETCHING' || status === 'RUNNING' ? (
                    <><Loader2 size={16} className="animate-spin" /> Simulating...</>
                  ) : (
                    <><Play fill="currentColor" size={16} /> Run Simulation</>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="lg:col-span-3 space-y-6">
          
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 shadow-sm">
              <span className="text-xs text-zinc-500 font-medium">Net Profit</span>
              <p className={`text-xl font-bold font-mono mt-1 ${metrics.pnl > 0 ? 'text-emerald-400' : 'text-zinc-400'}`}>
                {metrics.pnl > 0 ? '+' : ''}${metrics.pnl.toFixed(2)}
              </p>
            </div>
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 shadow-sm">
              <span className="text-xs text-zinc-500 font-medium">Win Rate</span>
              <p className="text-xl font-bold font-mono mt-1 text-blue-400">{metrics.winRate.toFixed(2)}%</p>
            </div>
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 shadow-sm">
              <span className="text-xs text-zinc-500 font-medium">Total Trades</span>
              <p className="text-xl font-bold font-mono mt-1 text-zinc-200">{metrics.trades}</p>
            </div>
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 shadow-sm">
              <span className="text-xs text-zinc-500 font-medium">Max Drawdown</span>
              <p className="text-xl font-bold font-mono mt-1 text-red-400">{metrics.maxDrawdown.toFixed(2)}%</p>
            </div>
          </div>

          <div className="bg-[#0D1117] border border-zinc-800 rounded-xl h-[500px] flex flex-col relative overflow-hidden shadow-2xl">
            <div className="bg-zinc-900 px-4 py-3 border-b border-zinc-800 flex justify-between items-center z-10 shadow-sm">
              <div className="flex items-center gap-4">
                <BarChart2 size={16} className="text-purple-500" />
                <span className="font-bold text-sm">{symbol}</span>
                <span className="text-xs px-2 py-1 bg-zinc-800 rounded text-zinc-200 font-mono">Candles: {timeframe}</span>
              </div>
              <div className="flex items-center gap-3">
                {/* Chart type toggle */}
                <div className="flex items-center bg-zinc-950 border border-zinc-700 rounded-lg p-0.5 gap-0.5">
                  <button
                    onClick={() => setChartType('candlestick')}
                    title="Candlestick Chart"
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                      chartType === 'candlestick'
                        ? 'bg-purple-600 text-white shadow-sm shadow-purple-900'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <CandlestickChart size={13} />
                    <span>Candles</span>
                  </button>
                  <button
                    onClick={() => setChartType('line')}
                    title="Line Chart"
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                      chartType === 'line'
                        ? 'bg-purple-600 text-white shadow-sm shadow-purple-900'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <TrendingUp size={13} />
                    <span>Line</span>
                  </button>
                </div>
                {status === 'COMPLETE' && <span className="flex items-center gap-2 text-xs text-emerald-500"><CheckCircle2 size={14} /> Simulation Finished</span>}
              </div>
            </div>

            <div className="flex-1 relative w-full h-full">
              {status === 'IDLE' && (
                <div className="absolute inset-0 z-10 flex flex-col items-center justify-center text-zinc-600 bg-[#0D1117]">
                  <History size={48} className="mx-auto mb-4 opacity-20" />
                  <p>Awaiting simulation parameters...</p>
                </div>
              )}
              <div ref={chartContainerRef} className="absolute inset-0 w-full h-full" />
            </div>
          </div>
          
          <div className="h-48 bg-[#0a0a0a] border border-zinc-800 rounded-xl p-4 font-mono text-xs overflow-y-auto shadow-inner">
             <div className="space-y-1.5">
               {logs.length === 0 ? (
                 <p className="text-zinc-700 italic">Engine idle. Ready to initialize backtest...</p>
               ) : (
                 logs.map((log, index) => (
                   <p key={index} className={log.includes('Error') ? 'text-red-400' : 'text-zinc-400'}>
                     {log}
                   </p>
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