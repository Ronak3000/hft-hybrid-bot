import type { ReactNode } from 'react';
import { WorkspaceChrome } from '@/components/workspace-chrome/WorkspaceChrome';

export default function HistoricalLayout({ children }: { children: ReactNode }) {
  return <WorkspaceChrome view="backtest">{children}</WorkspaceChrome>;
}
