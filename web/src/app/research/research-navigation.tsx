'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import s from './lab.module.css';

const tabs = [
  { href: '/research/lob-prediction', label: 'Order-book prediction', index: '01' },
  { href: '/research/queue-market-making', label: 'Queue-aware market making', index: '02' },
];

export function ResearchNavigation() {
  const pathname = usePathname();
  return (
    <div className={s.researchNav}>
      <nav className={s.tabs} aria-label="Research projects">
        {tabs.map(({ href, label, index }) => (
          <Link key={href} href={href} aria-current={pathname === href ? 'page' : undefined}>
            <span className={s.tabIndex} aria-hidden="true">{index}</span><span>{label}</span>
          </Link>
        ))}
      </nav>
      <Link className={s.archiveLink} href="/research/archive" aria-current={pathname === '/research/archive' ? 'page' : undefined}>Research archive <span aria-hidden="true">↗</span></Link>
    </div>
  );
}
