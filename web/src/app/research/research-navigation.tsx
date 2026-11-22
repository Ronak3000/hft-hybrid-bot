'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import s from './lab.module.css';

const tabs = [
  { href: '/research/lob-prediction', label: 'Order-book prediction' },
  { href: '/research/queue-market-making', label: 'Queue-aware market making' },
];

export function ResearchNavigation() {
  const pathname = usePathname();
  return (
    <div className={s.researchNav}>
      <nav className={s.tabs} aria-label="Research projects">
        {tabs.map(({ href, label }) => (
          <Link key={href} href={href} aria-current={pathname === href ? 'page' : undefined}>{label}</Link>
        ))}
      </nav>
      <Link className={s.archiveLink} href="/research/archive" aria-current={pathname === '/research/archive' ? 'page' : undefined}>Earlier PPO pilot</Link>
    </div>
  );
}
