import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import { Sidebar } from '@/components/Sidebar';

// Standard UI Font
const inter = Inter({ subsets: ['latin'], variable: '--font-geist-sans' });
// Monospaced Font for financial data
const jetbrainsMono = JetBrains_Mono({ subsets: ['latin'], variable: '--font-geist-mono' });

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
      <body className={`${inter.variable} ${jetbrainsMono.variable} font-sans bg-zinc-950 text-zinc-50 flex min-h-screen`}>
        <a href="#main-content" className="skip-link">Skip to content</a>
        {/* Persistent Global Navigation */}
        <Sidebar />
        
        {/* Main Application Area */}
        <main className="flex-1 flex flex-col min-w-0" id="main-content">
          {children}
        </main>
      </body>
    </html>
  );
}
