import type { Metadata } from 'next';
import './globals.css';
import { MarketFooter, MarketHeader } from '@/components/market-shell/MarketShell';
import s from '@/components/market-shell/shell.module.css';

export const metadata: Metadata = {
  title: 'ApexHFT',
  description: 'Experimental market-microstructure research platform',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className={s.body}>
        <a href="#main-content" className="skip-link">Skip to content</a>
        <MarketHeader />
        <main className={s.main} id="main-content">
          {children}
        </main>
        <MarketFooter />
      </body>
    </html>
  );
}
