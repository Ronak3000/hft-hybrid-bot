'use client';

import Link from 'next/link';
import { Fragment } from 'react';
import { usePathname } from 'next/navigation';
import { Activity, ArrowUpRight, BarChart2, BookOpen, BrainCircuit, GitBranch, History, TerminalSquare } from 'lucide-react';
import { repositoryUrl } from '@/lib/research';

const navItems = [
  { name: 'Real-data replay', href: '/replay', icon: History },
  { name: 'Research overview', href: '/research', icon: BookOpen },
  { name: 'Legacy simulator', href: '/dashboard', icon: Activity },
  { name: 'Historical data', href: '/backtest', icon: BarChart2 },
  { name: 'Legacy training', href: '/train', icon: BrainCircuit },
];

export function Sidebar() {
  const pathname = usePathname();
  if (pathname === '/') return null;
  return (
    <aside className="workspace-sidebar">
      <Link href="/" className="sidebar-brand" aria-label="ApexHFT home"><TerminalSquare size={27} aria-hidden="true" /><span>Apex<span className="accent-text">HFT</span></span></Link>
      <div className="sidebar-section-label">WORKSPACE</div>
      <nav aria-label="Workspace navigation" className="workspace-navigation">
        {navItems.map(({ name, href, icon: Icon }, index) => (
          <Fragment key={href}>
          {index === 2 && <div className="sidebar-section-label">BACKEND REQUIRED</div>}
          <Link href={href} title={name} aria-label={name} aria-current={pathname === href ? 'page' : undefined} className={`workspace-nav-item ${pathname === href ? 'is-active' : ''}`}>
            <Icon size={18} aria-hidden="true" /><span>{name}</span>
          </Link>
          </Fragment>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-scope"><span className="status-dot" /><div>Research prototype<small>Paper simulation only</small></div></div>
        <a href={repositoryUrl} target="_blank" rel="noopener noreferrer" className="workspace-nav-item" aria-label="View source on GitHub" title="View source on GitHub">
          <GitBranch size={18} aria-hidden="true" /><span>View source</span><ArrowUpRight size={13} className="sidebar-external" aria-hidden="true" />
        </a>
      </div>
    </aside>
  );
}
