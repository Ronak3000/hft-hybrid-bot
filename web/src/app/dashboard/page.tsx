'use client';

import { useEffect } from 'react';
import { useTradingStore } from '@/store/useTradingStore';
import { LiveChart } from '@/components/charts/LiveChart';

// --- MICRO-COMPONENTS ---
// These only re-render when their specific piece of data changes.

function ConnectionStatus() {
  const isConnected = useTradingStore((state) => state.isConnected);
  return (
    <div className="flex items-center gap-2">
      <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`} />
      <span className="text-sm text-zinc-400 font-mono">
        {isConnected ? 'ENGINE_SYNCED' : 'DISCONNECTED'}
      </span>
    </div>
  );
}

function KPIGrid() {
  const netWorth = useTradingStore((state) => state.netWorth);
  const midPrice = useTradingStore((state) => state.midPrice);
  const inventory = useTradingStore((state) => state.inventory);

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <MetricCard title="Net Worth" value={`$${netWorth.toFixed(2)}`} />
      <MetricCard title="Mid Price" value={`$${midPrice.toFixed(2)}`} />
      <MetricCard 
        title="Physical Inventory" 
        value={`${inventory.toFixed(2)} BTC`} 
        alert={Math.abs(inventory) > 4} 
      />
    </div>
  );
}

function ExecutionFeed() {
  const executions = useTradingStore((state) => state.executions);
  
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col h-[460px]">
      <h2 className="text-sm font-semibold text-zinc-400 mb-4">Execution Feed</h2>
      <div className="overflow-y-auto flex-1 pr-2">
        <table className="w-full text-sm font-mono text-right">
          <thead>
            <tr className="text-zinc-500 pb-2 border-b border-zinc-800">
              <th className="font-normal text-left py-2">Side</th>
              <th className="font-normal py-2">Price</th>
              <th className="font-normal py-2">PnL</th>
            </tr>
          </thead>
          <tbody>
            {executions.map((exe, i) => (
              <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/20 transition-colors">
                <td className={`text-left py-2 ${exe.side === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>
                  {exe.side} {exe.size}
                </td>
                <td className="py-2 text-zinc-300">${exe.price.toFixed(2)}</td>
                <td className={`py-2 ${exe.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {exe.realized_pnl >= 0 ? '+' : ''}{exe.realized_pnl.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MetricCard({ title, value, alert = false }: { title: string, value: string, alert?: boolean }) {
  return (
    <div className={`p-4 rounded-xl border transition-colors duration-300 ${alert ? 'bg-red-950/20 border-red-900' : 'bg-zinc-900 border-zinc-800'}`}>
      <div className="text-sm text-zinc-400 mb-1">{title}</div>
      <div className={`text-2xl font-mono ${alert ? 'text-red-400' : 'text-zinc-50'}`}>{value}</div>
    </div>
  );
}

// --- MAIN LAYOUT ---
export default function DashboardPage() {
  const connect = useTradingStore((state) => state.connect);
  const disconnect = useTradingStore((state) => state.disconnect);

  // The main layout mounts once, connects the WebSocket, and NEVER re-renders.
  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 p-6 font-sans">
      <header className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold tracking-tight">HFT Live Terminal</h1>
        <ConnectionStatus />
      </header>

      <KPIGrid />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-zinc-900 border border-zinc-800 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-zinc-400 mb-4">Live Equity Curve (USD)</h2>
          <LiveChart />
        </div>
        <ExecutionFeed />
      </div>
    </div>
  );
}