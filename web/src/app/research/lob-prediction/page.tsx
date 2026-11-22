import type { Metadata } from 'next';
import { DepthModelResults } from '../advanced-results';
import { labData } from '../lab-data';
import { PredictionReplay } from '../prediction-replay';
import { ProjectMasthead } from '../project-masthead';
import s from '../lab.module.css';

export const metadata: Metadata = {
  title: 'Order-book prediction replay | ApexHFT',
  description: 'Walk forward through real BTCUSDT order-book updates and score each forecast as its horizon arrives.',
};

export default function PredictionPage() {
  return (
    <div className={s.shell}>
      <ProjectMasthead index="01" label="Prediction" title="Order-book prediction" description="Watch how the market unfolds, then compare what a simple forecast saw with what the deeper models learned.">
        <span className={s.tag}>{labData.symbol}</span>
        <span className={s.tag}>{labData.venue} · Recorded depth</span>
      </ProjectMasthead>
      <PredictionReplay sessions={labData.sessions} horizons={labData.horizons} />
      <DepthModelResults />
    </div>
  );
}
