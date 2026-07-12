'use client';

import Link from 'next/link';
import { ArrowRight, BrainCircuit, Cpu, LineChart, Play, Shield, TerminalSquare, Zap } from 'lucide-react';

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 font-sans selection:bg-emerald-500/30">
      {/* Navigation Bar */}
      <nav className="border-b border-zinc-900 bg-zinc-950/50 backdrop-blur-md fixed top-0 w-full z-50">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <TerminalSquare className="text-emerald-500 w-6 h-6" />
            <span className="font-bold text-lg tracking-tight">ApexHFT</span>
          </Link>
          <div className="flex items-center gap-6 text-sm font-medium">
            <Link href="#features" className="text-zinc-400 hover:text-zinc-50 transition-colors hidden md:block">Features</Link>
            <Link href="#architecture" className="text-zinc-400 hover:text-zinc-50 transition-colors hidden md:block">Architecture</Link>
            <Link 
              href="/dashboard" 
              className="bg-zinc-50 text-zinc-950 hover:bg-zinc-200 px-4 py-2 rounded-md font-semibold transition-colors"
            >
              Launch Terminal
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="pt-32 pb-20 px-6 relative overflow-hidden">
        {/* Abstract Background Glow */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[400px] bg-emerald-500/20 blur-[120px] rounded-full pointer-events-none" />
        
        <div className="max-w-4xl mx-auto text-center relative z-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 text-xs font-semibold uppercase tracking-wider mb-8 border border-emerald-500/20">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            C++ Microstructure Engine Live
          </div>
          
          <h1 className="text-5xl md:text-7xl font-bold tracking-tighter mb-6 bg-gradient-to-br from-zinc-50 to-zinc-400 bg-clip-text text-transparent">
            Build Your Own Alpha.<br />
            <span className="text-emerald-500">Zero Code Required.</span>
          </h1>
          
          <p className="text-lg md:text-xl text-zinc-400 mb-10 max-w-2xl mx-auto leading-relaxed">
            The first retail HFT platform bridging a bare-metal C++ limit order book with multi-core Reinforcement Learning. Train custom PPO agents overnight. Deploy live tomorrow.
          </p>
          
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link 
              href="/dashboard"
              className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white px-8 py-4 rounded-lg font-semibold transition-all w-full sm:w-auto justify-center shadow-[0_0_40px_-10px_rgba(16,185,129,0.4)]"
            >
              <Play fill="currentColor" size={18} />
              Start Training a Model
            </Link>
            <Link 
              href="/backtest"
              className="flex items-center gap-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-50 px-8 py-4 rounded-lg font-semibold transition-all w-full sm:w-auto justify-center"
            >
              <LineChart size={18} />
              View Historical Backtests
            </Link>
          </div>
        </div>
      </section>

      {/* The "Train Tonight, Trade Tomorrow" Workflow */}
      <section id="features" className="py-24 px-6 bg-zinc-900/50 border-y border-zinc-900">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold tracking-tight mb-4">Train Tonight. Trade Tomorrow.</h2>
            <p className="text-zinc-400 max-w-2xl mx-auto">Stop relying on black-box strategies. Take control of the machine learning pipeline and parameterize your own risk aversion.</p>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            <FeatureCard 
              icon={<LineChart />}
              title="1. Select Historical Data"
              description="Choose your asset pair and slice exact historical timeframes. Target specific market regimes, from high-volatility flash crashes to sideways chop."
            />
            <FeatureCard 
              icon={<BrainCircuit />}
              title="2. Tweak RL Parameters"
              description="Adjust PPO hyperparameters like entropy, learning rate, and batch size. Or, let our optimized institutional defaults handle the heavy lifting while you sleep."
            />
            <FeatureCard 
              icon={<Zap />}
              title="3. Deploy to C++ Engine"
              description="Wake up to a fully trained policy network. Inject the weights directly into our sub-millisecond C++ matching engine for live execution."
            />
          </div>
        </div>
      </section>

      {/* Technical Specs Footer-style section */}
      <section id="architecture" className="py-24 px-6">
        <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-16 items-center">
          <div>
            <h2 className="text-3xl font-bold tracking-tight mb-6">Institutional Grade Infrastructure</h2>
            <ul className="space-y-6">
              <SpecItem 
                icon={<Cpu />}
                title="Bare-Metal Execution"
                description="O(1) limit order book execution utilizing L1 cache-aligned memory slabs to bypass dynamic allocation overhead."
              />
              <SpecItem 
                icon={<Shield />}
                title="Mathematical Safety Rails"
                description="Hard-coded Avellaneda-Stoikov reservation price skewing overrides the AI to prevent toxic adverse selection."
              />
              <SpecItem 
                icon={<TerminalSquare />}
                title="Zero-Copy Telemetry"
                description="Real-time Pybind11 memory bridges stream live execution data to your browser at 60 FPS without DOM lag."
              />
            </ul>
          </div>
          
          {/* Decorative Terminal Window */}
          <div className="bg-[#0D1117] border border-zinc-800 rounded-xl overflow-hidden shadow-2xl">
            <div className="bg-zinc-900 px-4 py-2 border-b border-zinc-800 flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-red-500"></div>
              <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
              <div className="w-3 h-3 rounded-full bg-green-500"></div>
              <span className="text-xs text-zinc-500 ml-2 font-mono">hft_engine_worker.py</span>
            </div>
            <div className="p-6 font-mono text-sm text-zinc-400 space-y-2">
              <p><span className="text-emerald-400">root@ApexHFT</span>:~$ ./start_training --symbol BTC/USDT --epochs 500</p>
              <p className="text-zinc-500">[INFO] Initializing Gymnasium environment...</p>
              <p className="text-zinc-500">[INFO] Loading 30 days of LOB data (34.2 GB)...</p>
              <p className="text-zinc-300">Epoch 1/500 | Loss: 0.842 | Reward: -12.4</p>
              <p className="text-zinc-300">Epoch 2/500 | Loss: 0.612 | Reward: 4.1</p>
              <p className="animate-pulse text-emerald-400">Training in progress... ETA: 04:12:33</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function FeatureCard({ icon, title, description }: { icon: React.ReactNode, title: string, description: string }) {
  return (
    <div className="bg-zinc-950 border border-zinc-800 p-8 rounded-xl hover:border-emerald-500/50 transition-colors group">
      <div className="w-12 h-12 bg-zinc-900 text-emerald-400 rounded-lg flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
        {icon}
      </div>
      <h3 className="text-xl font-bold mb-3">{title}</h3>
      <p className="text-zinc-400 leading-relaxed">{description}</p>
    </div>
  );
}

function SpecItem({ icon, title, description }: { icon: React.ReactNode, title: string, description: string }) {
  return (
    <li className="flex gap-4">
      <div className="text-zinc-500 mt-1">{icon}</div>
      <div>
        <h4 className="text-lg font-bold text-zinc-200">{title}</h4>
        <p className="text-zinc-400 mt-1">{description}</p>
      </div>
    </li>
  );
}