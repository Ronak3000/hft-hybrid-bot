import type { Metadata } from 'next';
import Link from 'next/link';
import { pilot } from '@/lib/research';
import { ProjectMasthead } from '../project-masthead';
import s from '../lab.module.css';

export const metadata: Metadata = {
  title: 'Archived PPO pilot | ApexHFT',
  description: 'Documented BTCUSDT pilot results and historical research assumptions.',
};

export default function ArchivePage() {
  const largest = Math.max(...pilot.policies.map(({ pnl }) => Math.abs(pnl)));
  const settings = [
    ['Validated captures', String(pilot.sessions)],
    ['Applied L2 deltas', pilot.depthDeltas.toLocaleString('en-US')],
    ['Training seeds', pilot.seeds.join(' / ')],
    ['Steps per seed', pilot.trainingStepsPerSeed.toLocaleString('en-US')],
    ['Final-test sessions', String(pilot.testSessions)],
    ['Maker fee per fill', pilot.makerFee],
    ['Order / cancel latency', pilot.orderLatency],
    ['Quote quantity', pilot.quoteSize],
    ['Absolute inventory cap', pilot.inventoryLimit],
    ['Queue position', 'Conservative estimate'],
  ];
  return (
    <div className={s.shell}>
      <ProjectMasthead index="A" label="Archive" title="Earlier PPO pilot" description="Historical results from the first sealed policy comparison, preserved separately from the current research projects.">
        <span className={s.tag}>BTCUSDT</span><span className={s.tag}>{pilot.date} · Historical record</span>
      </ProjectMasthead>
      <section className={s.panel} aria-labelledby="pilot-policy-title">
        <div className={s.sectionHeading}><div><span className={s.kicker}>Sealed pilot / V1</span><h2 id="pilot-policy-title">Every policy lost money after fees</h2></div><span className={s.tag}>Archived results</span></div>
        <figure className={s.benchmarkChart}>
          <figcaption>Mean net P&amp;L per test session · USDT. Bars show loss magnitude.</figcaption>
          <ul className={s.bars}>
            {pilot.policies.map(({ name, pnl, kind }) => (
              <li key={name}><span>{name}</span><div className={s.barTrack} aria-hidden="true"><div className={kind === 'Learned policy' ? s.neuralBar : s.controlBar} style={{ width: `${Math.abs(pnl) / largest * 100}%` }} /></div><strong>{pnl.toFixed(2)}</strong></li>
            ))}
          </ul>
        </figure>
        <p className={s.note}>PPO was averaged over seeds within each recording. Lower activity contributed to inventory skew’s smaller loss, and two test sessions are too few to establish an advantage.</p>
        <details className={s.replayDetail}>
          <summary className={s.detailSummary}>Experiment settings and provenance</summary>
          <dl className={s.tiles}>{settings.map(([label, value]) => (
            <div className={s.tile} key={label}><dt>{label}</dt><dd>{value}</dd></div>
          ))}</dl>
          <p className={s.note}>Recorded fees are the pilot assumptions, not current exchange fees. Market-by-price data does not reveal exact queue position.</p>
          <p className={s.hash}>Report SHA-256: <code>{pilot.reportSha256}</code></p>
        </details>
        <div className={s.linkRow}>
          <a href={pilot.source} target="_blank" rel="noopener noreferrer">Read the source notes <span aria-hidden="true">↗</span></a>
          <Link href="/replay">Open the market replay <span aria-hidden="true">→</span></Link>
        </div>
      </section>
    </div>
  );
}
