import type { Metadata } from 'next';
import { MarketReplay } from '@/components/market-replay/MarketReplay';

export const metadata: Metadata = {
  title: 'Market replay | ApexHFT',
  description: 'Explore recorded Binance BTC/USDT order-book updates and simulated fills.',
};

export default function MarketReplayPage() {
  return <MarketReplay />;
}
