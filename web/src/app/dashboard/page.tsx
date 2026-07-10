'use client';

import { useState, useEffect, useRef } from 'react';
import { Activity, Database, Play, AlertTriangle, ShieldCheck, Server, RefreshCw } from 'lucide-react';
// NEW V5 IMPORTS: Added AreaSeries and createSeriesMarkers
import { createChart, ColorType, Time, AreaSeries, createSeriesMarkers } from 'lightweight-charts';

const SUPPORTED_ASSETS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT'];

interface TrainedModel {
  id: string;
  model_filename: string;
  start_date: string;
  end_date: string;
  created_at: string;
  hyperparameters?: {
    max_inventory?: number;
    base_trade_size?: number;
    kappa?: number;
    [key: string]: any;
  };
}

export default function LiveDashboardPage() {
  const [symbol, setSymbol] = useState<string>('BTC/USDT');
  const [availableModels, setAvailableModels] = useState<TrainedModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [isLoadingModels, setIsLoadingModels] = useState<boolean>(false);
  const [engineStatus, setEngineStatus] = useState<'OFFLINE' | 'BOOTING' | 'LIVE'>('OFFLINE');
  
  const [liveData, setLiveData] = useState({ price: 0, netWorth: 1000000, inventory: 0 });
  const [liveLogs, setLiveLogs] = useState<string[]>([]);
  
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fetchModels = async () => {
      setIsLoadingModels(true);
      try {
        const cleanSymbol = symbol.replace('/', '').replace('-', '').toUpperCase();
        const res = await fetch(`http://localhost:8000/api/models/${cleanSymbol}`);
        const data = await res.json();
        
        if (data.status === 'success') {
          setAvailableModels(data.models);
          if (data.models.length > 0) {
            const sorted = data.models.sort((a: TrainedModel, b: TrainedModel) => 
              new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
            );
            setSelectedModel(sorted[0].model_filename);
          } else {
            setSelectedModel('');
          }
        }
      } catch (error) {
        setAvailableModels([]);
        setSelectedModel('');
      } finally {
        setIsLoadingModels(false);
      }
    };
    fetchModels();
  }, [symbol]);

  // V5 Hardware-Accelerated Chart & WebSocket Engine
  useEffect(() => {
    if (engineStatus !== 'LIVE' || !chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0D1117' }, 
        textColor: '#A1A1AA',
      },
      grid: {
        vertLines: { color: '#1F2937' },
        horzLines: { color: '#1F2937' },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: true,
        borderColor: '#1F2937',
        rightOffset: 15,
      },
      rightPriceScale: {
        borderColor: '#1F2937',
        autoScale: true,
      }
    });

    // V5 SYNTAX FIX: Inject AreaSeries definition directly into addSeries
    const series = chart.addSeries(AreaSeries, {
      lineColor: '#3B82F6',
      topColor: 'rgba(59, 130, 246, 0.4)',
      bottomColor: 'rgba(59, 130, 246, 0.0)',
      lineWidth: 2,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });

    // V5 SYNTAX FIX: Initialize the Series Markers Plugin 
    const markersPlugin = createSeriesMarkers(series, []);
    let currentMarkers: any[] = [];

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth, height: chartContainerRef.current.clientHeight });
      }
    };
    window.addEventListener('resize', handleResize);

    const cleanSymbol = symbol.replace('/', '').replace('-', '').toLowerCase();
    const ws = new WebSocket(`ws://localhost:8000/ws/live/${cleanSymbol}`);

    ws.onopen = () => {
      setLiveLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] System: Connected to matching engine WS stream.`]);
      setLiveLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] Engine: Loaded Avellaneda-Stoikov parameters from ${selectedModel}`]);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      const timeInSeconds = Math.floor(data.timestamp / 1000) as Time;
      
      setLiveData({
        price: data.mid_price,
        netWorth: data.net_worth,
        inventory: data.inventory_btc
      });

      series.update({ time: timeInSeconds, value: data.mid_price });

      if (data.latest_executions && data.latest_executions.length > 0) {
        data.latest_executions.forEach((exec: any) => {
           setLiveLogs(prev => {
             const time = new Date().toLocaleTimeString();
             const newLogs = [...prev, `[${time}] Market: Executed ${exec.side} ${exec.size} @ ${exec.price} (PnL: $${exec.realized_pnl})`];
             return newLogs.slice(-30); 
           });

           currentMarkers.push({
             time: timeInSeconds,
             position: exec.side === 'BUY' ? 'belowBar' : 'aboveBar',
             color: exec.side === 'BUY' ? '#10B981' : '#EF4444',
             shape: exec.side === 'BUY' ? 'arrowUp' : 'arrowDown',
             text: exec.side,
           });
        });

        // Ensure markers are unique by time and strictly sorted (required by TradingView)
        const uniqueMarkers = Array.from(new Map(currentMarkers.map(m => [m.time, m])).values());
        uniqueMarkers.sort((a, b) => (a.time as number) - (b.time as number));
        
        // V5 SYNTAX FIX: Update markers using the new plugin API
        markersPlugin.setMarkers(uniqueMarkers);
      }
    };

    ws.onclose = () => {
      setLiveLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] System: Connection to engine closed.`]);
      setEngineStatus('OFFLINE');
    };

    return () => {
      window.removeEventListener('resize', handleResize);
      ws.close();
      chart.remove();
    };
  }, [engineStatus, selectedModel]);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [liveLogs]);

  const handleInitializeEngine = () => {
    if (!selectedModel) return;
    setEngineStatus('BOOTING');
    setLiveLogs([]); 
    setTimeout(() => {
      setEngineStatus('LIVE');
    }, 1000);
  };

  const activeModelDetails = availableModels.find(m => m.model_filename === selectedModel);
  const currentMaxInventory = activeModelDetails?.hyperparameters?.max_inventory || 6.0;
  const currentBaseTrade = activeModelDetails?.hyperparameters?.base_trade_size || 0.5;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 p-6 font-sans">
      <header className="mb-8 border-b border-zinc-800 pb-4 flex justify-between items-end">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Activity className="text-blue-500" />
            Live Execution Terminal
          </h1>
          <p className="text-sm text-zinc-400 mt-1">Deploy trained PPO agents against real-time market microstructure.</p>
        </div>
        
        <div className="flex items-center gap-3 bg-zinc-900 px-4 py-2 rounded-lg border border-zinc-800 shadow-[0_0_10px_rgba(0,0,0,0.5)]">
          <Server size={16} className={engineStatus === 'LIVE' ? 'text-blue-500' : 'text-zinc-500'} />
          <span className="text-sm font-mono font-medium">
            {engineStatus === 'OFFLINE' && <span className="text-zinc-400">ENGINE OFFLINE</span>}
            {engineStatus === 'BOOTING' && <span className="text-yellow-400 animate-pulse">ALLOCATING MEMORY...</span>}
            {engineStatus === 'LIVE' && <span className="text-blue-400">WEBSOCKET CONNECTED</span>}
          </span>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 shadow-lg">
            <h2 className="text-sm font-semibold text-zinc-400 mb-4 uppercase tracking-wider flex items-center gap-2">
              <Database size={16} /> Strategy Deployment
            </h2>
            
            <div className="space-y-5">
              <div>
                <label className="block text-xs text-zinc-500 mb-1">Target Asset</label>
                <select 
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  disabled={engineStatus !== 'OFFLINE'}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-blue-500 transition-colors disabled:opacity-50"
                >
                  {SUPPORTED_ASSETS.map(asset => (
                    <option key={asset} value={asset}>{asset}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1 flex justify-between">
                  <span>Compiled Brain (.zip)</span>
                  {isLoadingModels && <RefreshCw size={12} className="animate-spin text-zinc-500" />}
                </label>
                <select 
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  disabled={availableModels.length === 0 || engineStatus !== 'OFFLINE'}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-blue-500 transition-colors disabled:opacity-50 font-mono text-xs"
                >
                  {availableModels.length === 0 ? (
                    <option value="">No models found in database</option>
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
                {engineStatus === 'OFFLINE' ? (
                  <button 
                    onClick={handleInitializeEngine}
                    disabled={!selectedModel}
                    className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-white font-semibold py-3 rounded-md transition-colors flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(37,99,235,0.2)]"
                  >
                    <Play fill="currentColor" size={16} /> Deploy Strategy
                  </button>
                ) : (
                  <button 
                    onClick={() => setEngineStatus('OFFLINE')}
                    className="w-full bg-red-600/20 hover:bg-red-600/30 text-red-500 border border-red-900/50 font-semibold py-3 rounded-md transition-colors flex items-center justify-center gap-2"
                  >
                    Disconnect Engine
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 shadow-lg">
             <h2 className="text-sm font-semibold text-zinc-400 mb-3 flex items-center gap-2">
              <ShieldCheck size={16} /> Security Rules
            </h2>
            <div className="space-y-2 text-xs font-mono text-zinc-500">
              <div className="flex justify-between"><span>Max Drawdown:</span> <span className="text-zinc-300">-20.0%</span></div>
              <div className="flex justify-between"><span>Inventory Limit:</span> <span className="text-emerald-400">±{currentMaxInventory.toFixed(1)}</span></div>
              <div className="flex justify-between"><span>Base Order Size:</span> <span className="text-blue-400">{currentBaseTrade.toFixed(2)}</span></div>
            </div>
          </div>
        </div>

        <div className="lg:col-span-3">
          <div className="bg-[#0D1117] border border-zinc-800 rounded-xl h-[700px] flex flex-col relative overflow-hidden shadow-2xl">
            
            <div className="bg-zinc-900 px-4 py-3 border-b border-zinc-800 flex justify-between items-center z-10 shadow-sm">
              <div className="flex items-center gap-4">
                <span className="font-bold text-lg">{symbol}</span>
                <span className="text-sm px-2 py-1 bg-zinc-800 rounded text-zinc-200 font-mono">
                  {engineStatus === 'LIVE' ? `$${liveData.price.toLocaleString(undefined, {minimumFractionDigits: 2})}` : '---'}
                </span>
              </div>
              <div className="flex gap-6 text-xs font-mono">
                <div className="flex flex-col items-end">
                  <span className="text-zinc-500">Unrealized PnL</span>
                  <span className={engineStatus === 'LIVE' ? (liveData.netWorth >= 1000000 ? "text-emerald-400 text-sm" : "text-red-400 text-sm") : "text-zinc-600 text-sm"}>
                    {engineStatus === 'LIVE' ? `$${(liveData.netWorth - 1000000).toLocaleString(undefined, {minimumFractionDigits: 2})}` : "$0.00"}
                  </span>
                </div>
                <div className="flex flex-col items-end">
                  <span className="text-zinc-500">Net Inventory</span>
                  <span className={engineStatus === 'LIVE' ? "text-blue-400 text-sm font-bold" : "text-zinc-600 text-sm"}>
                    {engineStatus === 'LIVE' ? `${liveData.inventory > 0 ? '+' : ''}${liveData.inventory.toFixed(2)}` : "0.00"}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex-1 relative w-full h-full">
              {engineStatus === 'OFFLINE' && (
                <div className="absolute inset-0 z-10 flex flex-col items-center justify-center text-zinc-600 bg-[#0D1117]">
                  <Activity size={48} className="mx-auto mb-4 opacity-20" />
                  <p>Awaiting engine initialization...</p>
                  <p className="text-xs mt-2 font-mono">Select a trained model and click Deploy Strategy.</p>
                </div>
              )}
              <div ref={chartContainerRef} className="absolute inset-0 w-full h-full" />
            </div>
            
            <div className="h-56 bg-[#0a0a0a] border-t border-zinc-800 p-4 font-mono text-xs overflow-y-auto shadow-inner">
               {engineStatus === 'LIVE' ? (
                 <div className="space-y-1.5">
                   {liveLogs.map((log, index) => (
                     <p key={index} className={log.includes('Market: Executed BUY') ? 'text-emerald-400' : log.includes('Market: Executed SELL') ? 'text-red-400' : 'text-zinc-400'}>
                       {log}
                     </p>
                   ))}
                   <div ref={terminalEndRef} />
                 </div>
               ) : (
                 <p className="text-zinc-700 italic">Order routing engine disconnected...</p>
               )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}