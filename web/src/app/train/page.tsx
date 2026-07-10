'use client';

import { useEffect, useState } from 'react';
import { BrainCircuit, Play, CheckCircle2, AlertCircle, Loader2, ChevronDown, ChevronUp, Settings2 } from 'lucide-react';
import { useTrainingStore } from '@/store/useTrainingStore';

export default function TrainingPage() {
  const { 
    params, setParams, 
    jobId, setJobId, 
    status, setStatus, 
    progress, setProgress, 
    logs, addLog, resetJob 
  } = useTrainingStore();
  
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleStartTraining = async () => {
    resetJob();
    setStatus('PENDING');
    addLog('Dispatching job to cluster...');

    try {
      const res = await fetch('http://localhost:8000/api/training/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
      });
      
      const data = await res.json();
      setJobId(data.job_id);
      addLog(`Job accepted by Redis. Task ID: ${data.job_id}`);
    } catch (error) {
      setStatus('FAILURE');
      addLog('API Connection failed. Is FastAPI running?');
    }
  };

  useEffect(() => {
    if (!jobId || status === 'SUCCESS' || status === 'FAILURE') return;

    const pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/training/status/${jobId}`);
        const data = await res.json();

        if (data.state === 'PROGRESS') {
          setStatus('PROGRESS');
          
          // DEFENSIVE CHECK: Only update if the payload actually contains the percentage
          if (data.progress?.progress_percent !== undefined) {
            setProgress(data.progress.progress_percent);
          }
        } 
        else if (data.state === 'SUCCESS') {
          setStatus('SUCCESS');
          setProgress(100);
          addLog(`Training complete. Model saved as: ${data.result?.model_file || 'unknown.zip'}`);
        } 
        else if (data.state === 'FAILURE') {
          setStatus('FAILURE');
          addLog(`Job failed: ${data.error}`);
        }
      } catch (error) {
        // Suppress transient network fetch errors so they don't crash the UI
        console.debug("Polling transient error:", error);
      }
    }, 1500);

    return () => clearInterval(pollInterval);
  }, [jobId, status, setStatus, setProgress, addLog]);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 p-6 font-sans">
      <header className="mb-8 border-b border-zinc-800 pb-4">
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <BrainCircuit className="text-emerald-500" />
          Model Training Cluster
        </h1>
        <p className="text-sm text-zinc-400 mt-1">Configure parameters and dispatch PPO reinforcement learning jobs to background workers.</p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Configuration Panel */}
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-zinc-400 mb-4 uppercase tracking-wider">Hyperparameters</h2>
            
            <div className="space-y-4">
              <div>
                <label className="block text-xs text-zinc-500 mb-1">Asset Symbol</label>
                <input 
                  type="text" 
                  value={params.symbol}
                  onChange={e => setParams({ symbol: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                />
              </div>
              
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-zinc-500 mb-1">Start Date</label>
                  <input type="date" value={params.start_date} onChange={e => setParams({ start_date: e.target.value })} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-xs text-zinc-500 mb-1">End Date</label>
                  <input type="date" value={params.end_date} onChange={e => setParams({ end_date: e.target.value })} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm" />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs text-zinc-500 mb-1">Epochs</label>
                  <input type="number" value={params.epochs} onChange={e => setParams({ epochs: Number(e.target.value) })} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm font-mono" />
                </div>
                <div>
                  <label className="block text-xs text-zinc-500 mb-1">LR</label>
                  <input type="number" step="0.0001" value={params.learning_rate} onChange={e => setParams({ learning_rate: Number(e.target.value) })} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm font-mono" />
                </div>
                <div>
                  <label className="block text-xs text-zinc-500 mb-1">Entropy</label>
                  <input type="number" step="0.01" value={params.entropy_coef} onChange={e => setParams({ entropy_coef: Number(e.target.value) })} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm font-mono" />
                </div>
              </div>

              {/* Advanced Settings Accordion */}
              <div className="pt-2 border-t border-zinc-800">
                <button 
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="flex items-center justify-between w-full text-xs text-zinc-400 hover:text-zinc-200 transition-colors"
                >
                  <span className="flex items-center gap-2"><Settings2 size={14} /> Advanced Market Dynamics</span>
                  {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>
                
                {showAdvanced && (
                  <div className="mt-4 space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs text-zinc-500 mb-1">Starting Cash</label>
                        <input type="number" value={params.starting_cash} onChange={e => setParams({ starting_cash: Number(e.target.value) })} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm font-mono" />
                      </div>
                      <div>
                        <label className="block text-xs text-zinc-500 mb-1">Maker Fee</label>
                        <input type="number" step="0.00001" value={params.maker_fee} onChange={e => setParams({ maker_fee: Number(e.target.value) })} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm font-mono" />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs text-zinc-500 mb-1">Base Trade Size</label>
                        <input type="number" step="0.1" value={params.base_trade_size} onChange={e => setParams({ base_trade_size: Number(e.target.value) })} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm font-mono" />
                      </div>
                      <div>
                        <label className="block text-xs text-zinc-500 mb-1">Max Inventory</label>
                        <input type="number" step="0.1" value={params.max_inventory} onChange={e => setParams({ max_inventory: Number(e.target.value) })} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm font-mono" />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs text-zinc-500 mb-1">Penalty Factor</label>
                        <input type="number" step="0.01" value={params.penalty_factor} onChange={e => setParams({ penalty_factor: Number(e.target.value) })} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm font-mono" />
                      </div>
                      <div>
                        <label className="block text-xs text-zinc-500 mb-1">AS Kappa (Risk)</label>
                        <input type="number" step="0.1" value={params.kappa} onChange={e => setParams({ kappa: Number(e.target.value) })} className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm font-mono" />
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <button 
                onClick={handleStartTraining}
                disabled={status === 'PENDING' || status === 'PROGRESS'}
                className="w-full mt-4 bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-white font-semibold py-3 rounded-md transition-colors flex items-center justify-center gap-2"
              >
                {status === 'PENDING' || status === 'PROGRESS' ? (
                  <><Loader2 size={18} className="animate-spin" /> Training...</>
                ) : (
                  <><Play fill="currentColor" size={16} /> Start Training Node</>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Telemetry and Progress Area */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
            <div className="flex justify-between items-end mb-4">
              <div>
                <h2 className="text-sm font-semibold text-zinc-400">Cluster Status</h2>
                <div className="text-2xl font-bold mt-1 flex items-center gap-2">
                  {status === 'IDLE' && <span className="text-zinc-500">Awaiting Job</span>}
                  {status === 'PENDING' && <span className="text-yellow-500 flex items-center gap-2"><Loader2 className="animate-spin" /> Allocating Resources</span>}
                  {status === 'PROGRESS' && <span className="text-emerald-400 font-mono">{progress}%</span>}
                  {status === 'SUCCESS' && <span className="text-emerald-500 flex items-center gap-2"><CheckCircle2 /> Training Complete</span>}
                  {status === 'FAILURE' && <span className="text-red-500 flex items-center gap-2"><AlertCircle /> Job Failed</span>}
                </div>
              </div>
              {status === 'PROGRESS' && (
                <div className="text-xs text-emerald-500 animate-pulse font-mono flex items-center gap-1">
                  <div className="w-2 h-2 rounded-full bg-emerald-500"></div> LIVE
                </div>
              )}
            </div>

            <div className="w-full bg-zinc-950 rounded-full h-4 border border-zinc-800 overflow-hidden relative">
              <div 
                className="bg-emerald-500 h-4 rounded-full transition-all duration-500 ease-out relative overflow-hidden"
                style={{ width: `${progress}%` }}
              >
                {(status === 'PENDING' || status === 'PROGRESS') && (
                  <div className="absolute top-0 left-0 right-0 bottom-0 bg-gradient-to-r from-transparent via-white/20 to-transparent -translate-x-full animate-[shimmer_2s_infinite]"></div>
                )}
              </div>
            </div>
          </div>

          <div className="bg-[#0D1117] border border-zinc-800 rounded-xl overflow-hidden h-[300px] flex flex-col">
            <div className="bg-zinc-900 px-4 py-2 border-b border-zinc-800 flex items-center gap-2">
              <span className="text-xs text-zinc-500 font-mono">worker_stdout.log</span>
            </div>
            <div className="p-4 font-mono text-sm text-zinc-400 overflow-y-auto flex-1 space-y-1">
              {logs.length === 0 ? (
                <p className="text-zinc-600 italic">No active logs...</p>
              ) : (
                logs.map((log, i) => (
                  <p key={i} className={log.includes('Failed') ? 'text-red-400' : 'text-emerald-400/80'}>{log}</p>
                ))
              )}
              {status === 'PROGRESS' && (
                <p className="text-emerald-500 animate-pulse">_</p>
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}