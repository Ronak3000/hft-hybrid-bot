'use client';

import { useState, useEffect } from 'react';
import { Activity, Database, Calendar, Play, AlertTriangle, ShieldCheck, Server, RefreshCw } from 'lucide-react';

// Common Binance HFT Pairs
const SUPPORTED_ASSETS = [
  'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 
  'BNB/USDT', 'XRP/USDT', 'ADA/USDT'
];

interface TrainedModel {
  id: string;
  model_filename: string;
  start_date: string;
  end_date: string;
  created_at: string;
}

export default function LiveDashboardPage() {
  // Configuration State
  const [symbol, setSymbol] = useState<string>('BTC/USDT');
  const [startDate, setStartDate] = useState<string>(new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]); // Default to 7 days ago
  const [endDate, setEndDate] = useState<string>(new Date().toISOString().split('T')[0]); // Default to today
  
  // Database State
  const [availableModels, setAvailableModels] = useState<TrainedModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [isLoadingModels, setIsLoadingModels] = useState<boolean>(false);
  
  // Engine State
  const [engineStatus, setEngineStatus] = useState<'OFFLINE' | 'BOOTING' | 'LIVE'>('OFFLINE');

  // Dynamic Model Fetching
  useEffect(() => {
    const fetchModels = async () => {
      setIsLoadingModels(true);
      try {
        const cleanSymbol = symbol.replace('/', '').replace('-', '').toUpperCase();
        const res = await fetch(`http://localhost:8000/api/models/${cleanSymbol}`);
        const data = await res.json();
        
        if (data.status === 'success') {
          setAvailableModels(data.models);
          // Auto-select the most recent model if available
          if (data.models.length > 0) {
            // Sort by created_at descending
            const sorted = data.models.sort((a: TrainedModel, b: TrainedModel) => 
              new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
            );
            setSelectedModel(sorted[0].model_filename);
          } else {
            setSelectedModel('');
          }
        }
      } catch (error) {
        console.error("Failed to fetch models from Supabase:", error);
        setAvailableModels([]);
        setSelectedModel('');
      } finally {
        setIsLoadingModels(false);
      }
    };

    fetchModels();
  }, [symbol]); // Re-runs every time the user changes the symbol

  const handleInitializeEngine = () => {
    if (!selectedModel) return;
    setEngineStatus('BOOTING');
    
    // Simulate connection to the WebSockets we stubbed out earlier
    setTimeout(() => {
      setEngineStatus('LIVE');
    }, 1500);
  };

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
        
        {/* Global Engine Status */}
        <div className="flex items-center gap-3 bg-zinc-900 px-4 py-2 rounded-lg border border-zinc-800">
          <Server size={16} className={engineStatus === 'LIVE' ? 'text-blue-500' : 'text-zinc-500'} />
          <span className="text-sm font-mono font-medium">
            {engineStatus === 'OFFLINE' && <span className="text-zinc-400">ENGINE OFFLINE</span>}
            {engineStatus === 'BOOTING' && <span className="text-yellow-400 animate-pulse">ALLOCATING MEMORY...</span>}
            {engineStatus === 'LIVE' && <span className="text-blue-400">WEBSOCKET CONNECTED</span>}
          </span>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        
        {/* Left Column: Command & Control */}
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-zinc-400 mb-4 uppercase tracking-wider flex items-center gap-2">
              <Database size={16} /> Strategy Deployment
            </h2>
            
            <div className="space-y-5">
              {/* Asset Selector */}
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

              {/* Model Selector (Filtered dynamically via Supabase) */}
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
                        {model.model_filename} (Trained: {new Date(model.created_at).toLocaleDateString()})
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

              {/* Data Range Selector (For initializing the Live Chart / Lookback) */}
              <div className="grid grid-cols-2 gap-3 pt-2 border-t border-zinc-800">
                <div className="col-span-2">
                  <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1">
                    <Calendar size={12} /> Chart Lookback Period
                  </label>
                </div>
                <div>
                  <label className="block text-[10px] text-zinc-600 mb-1">From</label>
                  <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} disabled={engineStatus !== 'OFFLINE'} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1.5 text-xs disabled:opacity-50" />
                </div>
                <div>
                  <label className="block text-[10px] text-zinc-600 mb-1">To</label>
                  <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} disabled={engineStatus !== 'OFFLINE'} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1.5 text-xs disabled:opacity-50" />
                </div>
              </div>

              {/* Action Button */}
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
          
          {/* Active Configuration Readout */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
             <h2 className="text-sm font-semibold text-zinc-400 mb-3 flex items-center gap-2">
              <ShieldCheck size={16} /> Security Rules
            </h2>
            <div className="space-y-2 text-xs font-mono text-zinc-500">
              <div className="flex justify-between"><span>Max Drawdown:</span> <span className="text-zinc-300">-20.0%</span></div>
              <div className="flex justify-between"><span>Inventory Limit:</span> <span className="text-zinc-300">±6.0 BTC</span></div>
              <div className="flex justify-between"><span>Order Type:</span> <span className="text-emerald-400">MAKER ONLY</span></div>
            </div>
          </div>
        </div>

        {/* Right Column: The Trading View */}
        <div className="lg:col-span-3">
          <div className="bg-[#0D1117] border border-zinc-800 rounded-xl h-[700px] flex flex-col relative overflow-hidden">
            
            {/* Chart Header */}
            <div className="bg-zinc-900 px-4 py-3 border-b border-zinc-800 flex justify-between items-center z-10">
              <div className="flex items-center gap-4">
                <span className="font-bold">{symbol}</span>
                <span className="text-xs px-2 py-1 bg-zinc-800 rounded text-zinc-300">100ms Tick</span>
              </div>
              <div className="flex gap-4 text-xs font-mono">
                <div className="flex flex-col items-end">
                  <span className="text-zinc-500">Unrealized PnL</span>
                  <span className={engineStatus === 'LIVE' ? "text-emerald-400" : "text-zinc-600"}>
                    {engineStatus === 'LIVE' ? "+$142.50" : "$0.00"}
                  </span>
                </div>
                <div className="flex flex-col items-end">
                  <span className="text-zinc-500">Inventory</span>
                  <span className={engineStatus === 'LIVE' ? "text-blue-400" : "text-zinc-600"}>
                    {engineStatus === 'LIVE' ? "+1.5 BTC" : "0.00 BTC"}
                  </span>
                </div>
              </div>
            </div>

            {/* Chart Body Placeholder */}
            <div className="flex-1 flex items-center justify-center relative">
              {engineStatus === 'OFFLINE' ? (
                <div className="text-center text-zinc-600">
                  <Activity size={48} className="mx-auto mb-4 opacity-20" />
                  <p>Awaiting engine initialization...</p>
                  <p className="text-xs mt-2 font-mono">Select a trained model and click Deploy Strategy.</p>
                </div>
              ) : (
                <div className="absolute inset-0 p-4">
                  {/* Grid background to simulate a chart area */}
                  <div className="w-full h-full border border-zinc-800/50 rounded flex flex-col justify-end p-4 relative"
                       style={{ backgroundImage: 'linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)', backgroundSize: '20px 20px' }}>
                    
                    {/* Simulated live chart line connecting */}
                    <div className="absolute left-0 bottom-[40%] w-[60%] h-0.5 bg-zinc-700"></div>
                    <div className="absolute left-[60%] bottom-[40%] w-[40%] h-0.5 bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.8)]"></div>
                    
                    {/* Pulsing indicator */}
                    <div className="absolute right-4 bottom-[calc(40%-3px)] w-2 h-2 rounded-full bg-blue-400 animate-ping"></div>
                    <div className="absolute right-4 bottom-[calc(40%-3px)] w-2 h-2 rounded-full bg-blue-500"></div>
                  </div>
                </div>
              )}
            </div>
            
            {/* Live Order Book Terminal Log */}
            <div className="h-48 bg-zinc-950 border-t border-zinc-800 p-3 font-mono text-xs overflow-y-auto">
               {engineStatus === 'LIVE' ? (
                 <div className="space-y-1">
                   <p className="text-zinc-500">[10:42:01.105] System: Connected to matching engine WS stream.</p>
                   <p className="text-zinc-500">[10:42:01.120] Engine: Loading Avellaneda-Stoikov parameters...</p>
                   <p className="text-zinc-500">[10:42:01.125] Engine: Loaded weights from {selectedModel}</p>
                   <p className="text-blue-400">[10:42:02.001] AI Action: Calculated spread 4.5. Placed Buy @ 62498.50, Sell @ 62503.00</p>
                   <p className="text-emerald-400">[10:42:03.450] Market: Executed BUY 0.5 BTC @ 62498.50 (Maker Fee: -$0.00)</p>
                   <p className="text-blue-400">[10:42:03.452] AI Action: Inventory shifted. Adjusting reservation price...</p>
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