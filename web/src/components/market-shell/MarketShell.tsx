'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { MoveUpRight } from 'lucide-react';
import s from './shell.module.css';

const links = [
  { href: '/market-replay', label: 'Market replay', aliases: ['/replay'] },
  { href: '/research', label: 'Research', aliases: [] },
  { href: '/train', label: 'Train', aliases: [] },
  { href: '/backtest', label: 'Backtest', aliases: [] },
  { href: '/dashboard', label: 'Live desk', aliases: [] },
];

export function MarketHeader() {
  const pathname = usePathname();
  return (
    <header className={s.header}>
      <div className={s.bar}>
        <Link className={s.wordmark} href="/" aria-label="ApexHFT home">
          <span className={s.brandIcon} aria-hidden="true">
            <svg width="23" height="23" viewBox="0 0 24 24" fill="none">
              <path d="M3 17 9.4 6.5l3.2 5.1L16 6l5 8.4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="m3 17 5.3-3.2 4.2 2.3 6.7-4.1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </span>
          <span>Apex<span className={s.accent}>HFT</span><small>MARKET LAB</small></span>
        </Link>
        <nav className={s.navigation} aria-label="Workspace">
          {links.map(({ href, label, aliases }) => {
            const active = [href, ...aliases].some((route) => pathname === route || pathname.startsWith(`${route}/`));
            return <Link href={href} key={href} aria-current={active ? 'page' : undefined}>{label}</Link>;
          })}
        </nav>
        <span className={s.scope}><i aria-hidden="true" />Paper only</span>
      </div>
    </header>
  );
}

export function MarketFooter() {
  return (
    <footer className={s.footer}>
      <div><strong>ApexHFT</strong><span>Market microstructure research · No exchange orders routed</span></div>
      <a href="https://github.com/Ronak3000/hft-hybrid-bot" target="_blank" rel="noopener noreferrer">Source code <MoveUpRight size={13} aria-hidden="true" /></a>
    </footer>
  );
}
