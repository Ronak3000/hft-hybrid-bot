import type { ReactNode } from 'react';
import Link from 'next/link';
import { Activity, ArrowUpRight, BrainCircuit, Database, History } from 'lucide-react';
import styles from './workspace-chrome.module.css';

const workspaces = {
  train: {
    label: 'Model training',
    title: 'Start with a question.',
    description: 'Choose a market and a period, then configure a research training job. Keep the run settings so you can compare the outcome later.',
    next: 'Explore order-book research',
    href: '/research/lob-prediction',
    icon: BrainCircuit,
  },
  backtest: {
    label: 'Historical workspace',
    title: 'Revisit a market session.',
    description: 'Choose a market and load an earlier period. Use the chart to see how prices moved and keep historical results separate from live activity.',
    next: 'Play the recorded L2 demo',
    href: '/market-replay',
    icon: History,
  },
  dashboard: {
    label: 'Live workspace',
    title: 'Observe the policy in paper mode.',
    description: 'Choose a saved policy and follow its simulated decisions as the feed comes in. No orders are routed to the exchange.',
    next: 'Go to model training',
    href: '/train',
    icon: Activity,
  },
} as const;

export function WorkspaceChrome({ view, children }: {
  view: keyof typeof workspaces;
  children: ReactNode;
}) {
  const { label, title, description, next, href, icon: Icon } = workspaces[view];

  return (
    <div className={styles.workspace} data-view={view}>
      <header className={styles.intro}>
        <div className={styles.introCopy}>
          <p className={styles.eyebrow}><Icon size={15} aria-hidden="true" /> {label}</p>
          <p className={styles.headline}>{title}</p>
          <p className={styles.description}>{description}</p>
        </div>
        <div className={styles.context}>
          <span className={styles.mode}><Database size={13} aria-hidden="true" /> Backend required</span>
          <Link className={styles.jump} href={href}>
            {next} <ArrowUpRight size={16} aria-hidden="true" />
          </Link>
        </div>
      </header>
      <div className={styles.operational}>{children}</div>
    </div>
  );
}
