import type { Metadata } from 'next';
import { CaptureReplay } from '@/components/replay/CaptureReplay';
import './replay.css';

export const metadata: Metadata = {
  title: 'Real-data replay | ApexHFT',
  description: 'Play real Binance order-book captures with simulated quotes, fills, inventory, and fee-inclusive accounting. No running Python backend required.',
};

export default function ReplayPage() {
  return <CaptureReplay />;
}
