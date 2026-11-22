import type { ReactNode } from 'react';
import { WorkspaceChrome } from '@/components/workspace-chrome/WorkspaceChrome';

export default function TrainingLayout({ children }: { children: ReactNode }) {
  return <WorkspaceChrome view="train">{children}</WorkspaceChrome>;
}
