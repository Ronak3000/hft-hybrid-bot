'use client';

import { useState, useEffect } from 'react';
import { HistoricalChart, OHLCData } from '@/components/charts/HistoricalChart';
import { BarChart2, TrendingUp } from 'lucide-react'; // Make sure lucide-react is installed

export default function BacktestPage() {
  const [data, setData] = useState<OHLCData[]>([]);
  const [timeframe, setTimeframe] = useState<'30m' | '2h' | '5h'>('30m');
  const [chartType, setChartType] = useState<'candlestick' | 'line'>('candlestick');
  const [isLoading, setIsLoading] = useState(true);

  // Fetch historical data from the FastAPI Backend
  useEffect(() => {
    const fetchHistoricalData = async () => {
      setIsLoading(true);
      try {
        const response = await fetch(`http://localhost:8000/api/backtest/ohlcv?symbol=BTC/USDT&timeframe=${timeframe}`);
        const result = await response.json();
        
        const sortedData = result.data.sort((a: OHLCData, b: OHLCData) => a.time - b.time);
        setData(sortedData);
      } catch (error) {
        console.error("Failed to fetch backtest data:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchHistoricalData();
  }, [timeframe]);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 p-6 font-sans">
      <header className="flex justify-between items-center mb-6 border-b border-zinc-800 pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Historical Backtest Sandbox</h1>
          <p className="text-sm text-zinc-400 mt-1">Simulate strategy performance on past LOB data.</p>
        </div>
        
        <div className="flex items-center gap-4">
          {/* Chart Type Toggle */}
          <div className="flex bg-zinc-900 border border-zinc-800 rounded-lg p-1">
            <button
              onClick={() => setChartType('candlestick')}
              className={`flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
                chartType === 'candlestick' ? 'bg-zinc-800 text-zinc-50 shadow-sm' : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              <BarChart2 size={16} />
              Candles
            </button>
            <button
              onClick={() => setChartType('line')}
              className={`flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
                chartType === 'line' ? 'bg-zinc-800 text-zinc-50 shadow-sm' : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              <TrendingUp size={16} />
              Line
            </button>
          </div>

          <div className="w-px h-6 bg-zinc-800"></div> {/* Divider */}

          {/* Timeframe Selector Panel */}
          <div className="flex bg-zinc-900 border border-zinc-800 rounded-lg p-1">
            {(['30m', '2h', '5h'] as const).map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                  timeframe === tf 
                    ? 'bg-zinc-800 text-emerald-400 shadow-sm' 
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Configuration Sidebar */}
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
            <h2 className="text-sm font-semibold text-zinc-400 mb-4">Simulation Parameters</h2>
            
            <div className="space-y-4">
              <div>
                <label className="block text-xs text-zinc-500 mb-1">Asset Pair</label>
                <div className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-300">
                  BTC / USDT
                </div>
              </div>
              
              <div>
                <label className="block text-xs text-zinc-500 mb-1">Initial Capital</label>
                <div className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-300 font-mono">
                  $1,000,000.00
                </div>
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1">RL Model Weights</label>
                <div className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-emerald-400">
                  ppo_hft_v2.zip
                </div>
              </div>
              
              <button className="w-full mt-4 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-2 rounded transition-colors shadow-sm">
                Run Simulation
              </button>
            </div>
          </div>
        </div>

        {/* Main Chart Area */}
        <div className="lg:col-span-3 bg-zinc-900 border border-zinc-800 rounded-xl p-4 min-h-[550px] relative">
          <h2 className="text-sm font-semibold text-zinc-400 mb-4">Asset Price Action</h2>
          
          {isLoading ? (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-emerald-500"></div>
            </div>
          ) : (
            <HistoricalChart data={data} type={chartType} />
          )}
        </div>
      </div>
    </div>
  );
}