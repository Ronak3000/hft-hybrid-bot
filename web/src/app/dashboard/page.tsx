'use client';

import { useState, useEffect, useRef } from 'react';
import { Activity, Database, Play, AlertTriangle, ShieldCheck, Server, RefreshCw, Pause, PlayCircle } from 'lucide-react';
import { createChart, ColorType, Time, AreaSeries, createSeriesMarkers } from 'lightweight-charts';
import { API_BASE, WS_BASE } from '@/lib/api';

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
  const [symbol, setSymbol] = useState<string>('ETH/USDT');
  const [availableModels, setAvailableModels] = useState<TrainedModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [isLoadingModels, setIsLoadingModels] = useState<boolean>(false);
  
  const [engineStatus, setEngineStatus] = useState<'OFFLINE' | 'BOOTING' | 'LIVE'>('OFFLINE');
  const [isQuoting, setIsQuoting] = useState<boolean>(true);
  // Params reported by the live engine API. null = not yet received, falls through to model params.
  const [engineMaxInv, setEngineMaxInv] = useState<number | null>(null);
  const [engineBaseTrade, setEngineBaseTrade] = useState<number | null>(null);
  const engineStatusRef = useRef(engineStatus);
  
  const [liveData, setLiveData] = useState({ price: 0, netWorth: 1000000, inventory: 0 });
  const [liveLogs, setLiveLogs] = useState<string[]>([]);
  
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);

  // Auto-reconnect to running background daemon on mount/tab switch
  useEffect(() => {
    const checkDaemonStatus = async () => {
      try {
        const cleanSym = symbol.replace('/', '').replace('-', '').toUpperCase();
        const res = await fetch(`${API_BASE}/api/engine/status/${cleanSym}`);
        const data = await res.json();
        if (data.status === 'LIVE') {
          setEngineStatus('LIVE');
          engineStatusRef.current = 'LIVE';
          setIsQuoting(data.is_quoting ?? true);
          if (data.max_inventory !== undefined) setEngineMaxInv(Number(data.max_inventory));
          if (data.base_trade_size !== undefined) setEngineBaseTrade(Number(data.base_trade_size));
          setSelectedModel(data.model_filename);
        } else {
          setEngineStatus('OFFLINE');
          engineStatusRef.current = 'OFFLINE';
        }
      } catch (error) {
        setEngineStatus('OFFLINE');
      }
    };
    checkDaemonStatus();
  }, [symbol]);

  useEffect(() => {
    const fetchModels = async () => {
      setIsLoadingModels(true);
      try {
        const cleanSymbol = symbol.replace('/', '').replace('-', '').toUpperCase();
        const res = await fetch(`${API_BASE}/api/models/${cleanSymbol}`);
        const data = await res.json();
        
        if (data.status === 'success') {
          setAvailableModels(data.models);
          // Only auto-select latest model when engine is offline (use ref to avoid stale closure)
          if (data.models.length > 0 && engineStatusRef.current === 'OFFLINE') {
            const sorted = data.models.sort((a: TrainedModel, b: TrainedModel) => 
              new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
            );
            setSelectedModel(sorted[0].model_filename);
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

  // V5 Hardware-Accelerated Chart & Telemetry Socket
  useEffect(() => {
    if (engineStatus !== 'LIVE' || !chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#0D1117' }, textColor: '#A1A1AA' },
      grid: { vertLines: { color: '#1F2937' }, horzLines: { color: '#1F2937' } },
      timeScale: { timeVisible: true, secondsVisible: true, borderColor: '#1F2937', rightOffset: 15 },
      rightPriceScale: { borderColor: '#1F2937', autoScale: true }
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor: '#3B82F6', topColor: 'rgba(59, 130, 246, 0.4)', bottomColor: 'rgba(59, 130, 246, 0.0)',
      lineWidth: 2, priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });

    const markersPlugin = createSeriesMarkers(series, []);
    let currentMarkers: any[] = [];

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth, height: chartContainerRef.current.clientHeight });
      }
    };
    window.addEventListener('resize', handleResize);

    const cleanSymbol = symbol.replace('/', '').replace('-', '').toLowerCase();
    const ws = new WebSocket(`${WS_BASE}/ws/live/${cleanSymbol}`);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.error) {
        setLiveLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] SERVER ERROR: ${data.error}`]);
        return;
      }

      // Handle instant chart and execution marker recovery when returning to tab
      if (data.type === 'RECOVERY_BUFFER') {
        setLiveLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] System: Synchronized with background quant daemon.`]);
        if (data.max_inventory !== undefined) setEngineMaxInv(Number(data.max_inventory));
        if (data.base_trade_size !== undefined) setEngineBaseTrade(Number(data.base_trade_size));
        if (data.is_quoting !== undefined) setIsQuoting(data.is_quoting);
        
        // 1. Restore chart price line
        if (data.chart_buffer && data.chart_buffer.length > 0) {
          const cleanHistory = Array.from(
            new Map(
              data.chart_buffer.map((point: any) => {
                const sec = Math.floor(point.timestamp / 1000) as Time;
                return [sec, { time: sec, value: point.mid_price }];
              })
            ).values()
          ).sort((a: any, b: any) => (a.time as number) - (b.time as number));

          series.setData(cleanHistory);
        }

        // 2. Restore execution logs and chart markers from before tab switch!
        if (data.recent_executions && data.recent_executions.length > 0) {
          const restoredLogs: string[] = [];
          const restoredMarkers: any[] = [];

          data.recent_executions.forEach((exec: any) => {
            const execTimeMs = exec.time || Date.now();
            const dateStr = new Date(execTimeMs).toLocaleTimeString();
            restoredLogs.push(`[${dateStr}] Market: Executed ${exec.side} ${exec.size} @ ${exec.price} (PnL: $${exec.realized_pnl})`);
            
            const timeInSeconds = Math.floor(execTimeMs / 1000) as Time;
            restoredMarkers.push({
              time: timeInSeconds,
              position: exec.side === 'BUY' ? 'belowBar' : 'aboveBar',
              color: exec.side === 'BUY' ? '#10B981' : '#EF4444',
              shape: exec.side === 'BUY' ? 'arrowUp' : 'arrowDown',
              text: exec.side,
            });
          });

          setLiveLogs(prev => [...prev, ...restoredLogs].slice(-50));
          
          currentMarkers.length = 0;
          currentMarkers.push(...restoredMarkers);
          
          const uniqueMap = new Map();
          currentMarkers.forEach(m => {
            const key = `${m.time}-${m.text}-${m.position}`;
            uniqueMap.set(key, m);
          });
          const sortedMarkers = Array.from(uniqueMap.values()).sort((a: any, b: any) => (a.time as number) - (b.time as number));
          markersPlugin.setMarkers(sortedMarkers);
        }

        return;
      }

      if (data.mid_price === undefined || data.timestamp === undefined) return;

      const timeInSeconds = Math.floor(data.timestamp / 1000) as Time;
      if (data.is_quoting !== undefined) setIsQuoting(data.is_quoting);
      
      setLiveData({
        price: data.mid_price ?? 0,
        netWorth: data.net_worth ?? 1000000,
        inventory: data.inventory_btc ?? 0
      });

      series.update({ time: timeInSeconds, value: data.mid_price });

      if (data.latest_executions && data.latest_executions.length > 0) {
        data.latest_executions.forEach((exec: any) => {
           setLiveLogs(prev => {
             const time = new Date().toLocaleTimeString();
             const newLogs = [...prev, `[${time}] Market: Executed ${exec.side} ${exec.size} @ ${exec.price} (PnL: $${exec.realized_pnl})`];
             return newLogs.slice(-50); 
           });

           currentMarkers.push({
             time: timeInSeconds,
             position: exec.side === 'BUY' ? 'belowBar' : 'aboveBar',
             color: exec.side === 'BUY' ? '#10B981' : '#EF4444',
             shape: exec.side === 'BUY' ? 'arrowUp' : 'arrowDown',
             text: exec.side,
           });
        });

        const uniqueMap = new Map();
        currentMarkers.forEach(m => {
          const key = `${m.time}-${m.text}-${m.position}`;
          uniqueMap.set(key, m);
        });
        const sortedMarkers = Array.from(uniqueMap.values()).sort((a, b) => (a.time as number) - (b.time as number));
        markersPlugin.setMarkers(sortedMarkers);
      }
    };

    ws.onclose = () => {
      setLiveLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] Telemetry: Subscriber socket closed.`]);
    };

    return () => {
      window.removeEventListener('resize', handleResize);
      ws.close();
      chart.remove();
    };
  }, [engineStatus, symbol]);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [liveLogs]);

  const handleDeployEngine = async () => {
    if (!selectedModel) return;
    setEngineStatus('BOOTING');
    setLiveLogs([]); 
    try {
      const res = await fetch(`${API_BASE}/api/engine/deploy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, model_filename: selectedModel })
      });
      const data = await res.json();
      if (data.status === 'success') {
        if (data.max_inventory !== undefined) setEngineMaxInv(Number(data.max_inventory));
        if (data.base_trade_size !== undefined) setEngineBaseTrade(Number(data.base_trade_size));
        setIsQuoting(true);
        setTimeout(() => {
          setEngineStatus('LIVE');
          engineStatusRef.current = 'LIVE';
        }, 800);
      } else {
        setEngineStatus('OFFLINE');
      }
    } catch (error) {
      setEngineStatus('OFFLINE');
    }
  };

  const handleStopEngine = async () => {
    try {
      await fetch(`${API_BASE}/api/engine/stop?symbol=${symbol}`, { method: 'POST' });
      setEngineMaxInv(null);
      setEngineBaseTrade(null);
      setEngineStatus('OFFLINE');
      engineStatusRef.current = 'OFFLINE';
    } catch (error) {
      console.error(error);
    }
  };

  const handleToggleQuoting = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/engine/toggle_quoting?symbol=${symbol}`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        setIsQuoting(data.is_quoting);
        setLiveLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] Control: ${data.message}`]);
      }
    } catch (error) {
      console.error(error);
    }
  };

  // Derive display values: engine API state → model hyperparameters → hardcoded default.
  const activeModelDetails = availableModels.find(m => m.model_filename === selectedModel);
  let modelMaxInv: number | undefined;
  let modelBaseTrade: number | undefined;
  if (activeModelDetails?.hyperparameters) {
    let raw: any = activeModelDetails.hyperparameters;
    if (typeof raw === 'string') { try { raw = JSON.parse(raw); } catch (e) { raw = null; } }
    if (raw && typeof raw === 'object') {
      if (raw.max_inventory !== undefined) modelMaxInv = Number(raw.max_inventory);
      if (raw.base_trade_size !== undefined) modelBaseTrade = Number(raw.base_trade_size);
    }
  }
  const displayMaxInv: number = engineMaxInv ?? modelMaxInv ?? 10.0;
  const displayBaseTrade: number = engineBaseTrade ?? modelBaseTrade ?? 0.50;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 p-6 font-sans">
      <header className="mb-8 border-b border-zinc-800 pb-4 flex justify-between items-end">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Activity className="text-blue-500" /> Live Execution Terminal
          </h1>
          <p className="text-sm text-zinc-400 mt-1">Deploy trained PPO agents against real-time market microstructure.</p>
        </div>
        
        <div className="flex items-center gap-3 bg-zinc-900 px-4 py-2 rounded-lg border border-zinc-800 shadow-[0_0_10px_rgba(0,0,0,0.5)]">
          <Server size={16} className={engineStatus === 'LIVE' ? (isQuoting ? 'text-blue-500' : 'text-yellow-500 animate-pulse') : 'text-zinc-500'} />
          <span className="text-sm font-mono font-medium">
            {engineStatus === 'OFFLINE' && <span className="text-zinc-400">ENGINE OFFLINE</span>}
            {engineStatus === 'BOOTING' && <span className="text-yellow-400 animate-pulse">BOOTING DAEMON...</span>}
            {engineStatus === 'LIVE' && (
              isQuoting ? <span className="text-blue-400">DAEMON ACTIVE (QUOTING)</span> : <span className="text-yellow-400">MARKET LEFT (PAUSED)</span>
            )}
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
                  value={symbol} onChange={(e) => setSymbol(e.target.value)} disabled={engineStatus !== 'OFFLINE'}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-blue-500 transition-colors disabled:opacity-50"
                >
                  {SUPPORTED_ASSETS.map(asset => (<option key={asset} value={asset}>{asset}</option>))}
                </select>
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1 flex justify-between">
                  <span>Compiled Brain (.zip)</span>
                  {isLoadingModels && <RefreshCw size={12} className="animate-spin text-zinc-500" />}
                </label>
                <select 
                  value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} disabled={availableModels.length === 0 || engineStatus !== 'OFFLINE'}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-blue-500 transition-colors disabled:opacity-50 font-mono text-xs"
                >
                  {availableModels.length === 0 ? (
                    <option value="">No models found in database</option>
                  ) : (
                    availableModels.map(model => (<option key={model.id} value={model.model_filename}>{model.model_filename}</option>))
                  )}
                </select>
                {availableModels.length === 0 && !isLoadingModels && (
                  <p className="text-[10px] text-red-400 mt-1 flex items-center gap-1"><AlertTriangle size={10} /> Train an agent for {symbol} first.</p>
                )}
              </div>

              <div className="pt-4 space-y-2">
                {engineStatus === 'OFFLINE' ? (
                  <button 
                    onClick={handleDeployEngine} disabled={!selectedModel}
                    className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-white font-semibold py-3 rounded-md transition-colors flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(37,99,235,0.2)]"
                  >
                    <Play fill="currentColor" size={16} /> Deploy Strategy
                  </button>
                ) : (
                  <>
                    <button 
                      onClick={handleToggleQuoting}
                      className={`w-full font-semibold py-2.5 rounded-md transition-colors flex items-center justify-center gap-2 border ${
                        isQuoting ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/50 hover:bg-yellow-500/30' : 'bg-emerald-500/20 text-emerald-400 border-emerald-500/50 hover:bg-emerald-500/30'
                      }`}
                    >
                      {isQuoting ? <><Pause size={16} /> Leave Market (Pause)</> : <><PlayCircle size={16} /> Enter Market (Resume)</>}
                    </button>

                    <button 
                      onClick={handleStopEngine}
                      className="w-full bg-red-600/20 hover:bg-red-600/30 text-red-500 border border-red-900/50 font-semibold py-2 rounded-md transition-colors flex items-center justify-center gap-2 text-xs"
                    >
                      Terminate Daemon
                    </button>
                  </>
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
              <div className="flex justify-between"><span>Inventory Limit:</span> <span className="text-emerald-400">±{displayMaxInv.toFixed(1)}</span></div>
              <div className="flex justify-between"><span>Base Order Size:</span> <span className="text-blue-400">{displayBaseTrade.toFixed(2)}</span></div>
            </div>
          </div>
        </div>

        <div className="lg:col-span-3">
          <div className="bg-[#0D1117] border border-zinc-800 rounded-xl h-[700px] flex flex-col relative overflow-hidden shadow-2xl">
            <div className="bg-zinc-900 px-4 py-3 border-b border-zinc-800 flex justify-between items-center z-10 shadow-sm">
              <div className="flex items-center gap-4">
                <span className="font-bold text-lg">{symbol}</span>
                <span className="text-sm px-2 py-1 bg-zinc-800 rounded text-zinc-200 font-mono">
                  {engineStatus === 'LIVE' ? `$${(liveData.price ?? 0).toLocaleString(undefined, {minimumFractionDigits: 2})}` : '---'}
                </span>
              </div>
              <div className="flex gap-6 text-xs font-mono">
                <div className="flex flex-col items-end">
                  <span className="text-zinc-500">Unrealized PnL</span>
                  <span className={engineStatus === 'LIVE' ? ((liveData.netWorth ?? 1000000) >= 1000000 ? "text-emerald-400 text-sm" : "text-red-400 text-sm") : "text-zinc-600 text-sm"}>
                    {engineStatus === 'LIVE' ? `$${((liveData.netWorth ?? 1000000) - 1000000).toLocaleString(undefined, {minimumFractionDigits: 2})}` : "$0.00"}
                  </span>
                </div>
                <div className="flex flex-col items-end">
                  <span className="text-zinc-500">Net Inventory</span>
                  <span className={engineStatus === 'LIVE' ? "text-blue-400 text-sm font-bold" : "text-zinc-600 text-sm"}>
                    {engineStatus === 'LIVE' ? `${(liveData.inventory ?? 0) > 0 ? '+' : ''}${(liveData.inventory ?? 0).toFixed(2)}` : "0.00"}
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
                     <p key={index} className={log.includes('Market: Executed BUY') ? 'text-emerald-400' : log.includes('Market: Executed SELL') ? 'text-red-400' : log.includes('SERVER ERROR') ? 'text-red-500 font-bold' : log.includes('Control:') ? 'text-yellow-400 font-bold' : 'text-zinc-400'}>
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