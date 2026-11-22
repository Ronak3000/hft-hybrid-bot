import type { Metadata } from 'next';
import { labData } from '../lab-data';
import { PredictionReplay } from '../prediction-replay';
import s from '../lab.module.css';

export const metadata: Metadata = {
  title: 'Order-book prediction replay | ApexHFT',
  description: 'Walk forward through real BTCUSDT order-book updates and score each forecast as its horizon arrives.',
};

export default function PredictionPage() {
  return (
    <div className={s.shell}>
      <span className={s.kicker}>Project 01 · Prediction lab</span>
      <h1 className={s.title}>Order-book prediction</h1>
      <p className={s.intro}>Play a real {labData.symbol} recording or select <strong>Run to end</strong> to score the full session immediately. The browser replays saved forecasts from a model trained on earlier sessions; it does not train a new model or place orders.</p>
      <p className={s.note}><span className={s.tag}>{labData.venue} · {labData.snapshot ?? 'Historical'} · Recorded test data</span></p>
      <PredictionReplay sessions={labData.sessions} horizons={labData.horizons} />
    </div>
  );
}
