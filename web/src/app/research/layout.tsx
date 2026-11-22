import type { ReactNode } from 'react';
import { ResearchNavigation } from './research-navigation';

export default function ResearchLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <ResearchNavigation />
      {children}
    </>
  );
}
