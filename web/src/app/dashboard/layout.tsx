import type { ReactNode } from 'react';
import { WorkspaceChrome } from '@/components/workspace-chrome/WorkspaceChrome';

export default function LiveLayout({ children }: { children: ReactNode }) {
  return <WorkspaceChrome view="dashboard">{children}</WorkspaceChrome>;
}
