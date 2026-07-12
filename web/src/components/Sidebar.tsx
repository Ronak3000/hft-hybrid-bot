'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Activity, BarChart2, BrainCircuit, Settings, TerminalSquare } from 'lucide-react'; // Add BrainCircuit
export function Sidebar() {
  const pathname = usePathname();

  // Do not render the sidebar on the landing page
  if (pathname === '/') return null;

    const navItems = [
    { name: 'Live HFT Terminal', href: '/dashboard', icon: Activity },
    { name: 'Historical Backtest', href: '/backtest', icon: BarChart2 },
    { name: 'Model Training', href: '/train', icon: BrainCircuit }, // NEW ROUTE
    ];

  return (
    <div className="w-20 lg:w-64 border-r border-zinc-800 bg-zinc-950 flex flex-col h-screen sticky top-0 shrink-0 z-50">
      {/* Brand Header */}
      <Link href="/" className="h-20 flex items-center justify-center lg:justify-start lg:px-6 border-b border-zinc-800">
        <TerminalSquare className="text-emerald-500 w-8 h-8 shrink-0" />
        <span className="ml-3 font-bold text-lg text-zinc-50 hidden lg:block tracking-tight">
          ApexHFT
        </span>
      </Link>

      {/* Navigation Links */}
      <div className="flex-1 py-6 flex flex-col gap-2 px-3 lg:px-4">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          
          return (
            <Link 
              key={item.name} 
              href={item.href}
              className={`flex items-center gap-3 px-3 py-3 rounded-lg transition-all group ${
                isActive 
                  ? 'bg-emerald-500/10 text-emerald-400' 
                  : 'text-zinc-400 hover:bg-zinc-900 hover:text-zinc-50'
              }`}
            >
              <Icon size={20} className={isActive ? 'text-emerald-400' : 'text-zinc-500 group-hover:text-zinc-300'} />
              <span className={`font-medium hidden lg:block ${isActive ? 'text-emerald-400' : ''}`}>
                {item.name}
              </span>
            </Link>
          );
        })}
      </div>

      {/* Bottom Settings Link */}
      <div className="p-4 border-t border-zinc-800">
        <button className="flex items-center justify-center lg:justify-start gap-3 w-full px-3 py-3 rounded-lg text-zinc-400 hover:bg-zinc-900 hover:text-zinc-50 transition-all">
          <Settings size={20} />
          <span className="font-medium hidden lg:block">Settings</span>
        </button>
      </div>
    </div>
  );
}