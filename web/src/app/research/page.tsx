import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowRight, ArrowUpRight, BookOpen, Check, FileText, FlaskConical, Layers3 } from 'lucide-react';
import { nextStudy, pilot, repositoryUrl } from '@/lib/research';
import replayCatalog from '../../../public/replays/catalog.json';

export const metadata: Metadata = {
  title: 'Research overview | ApexHFT',
  description: 'Documented BTCUSDT pilot results and research assumptions, available without a running backend.',
};

const capabilities = [
  ['Matching engine', 'Price-time priority, intrusive FIFO queues, preallocated storage, and hierarchical price discovery.'],
  ['Data integrity', 'Snapshot/delta sequencing, reconnect boundaries, immutable capture manifests, and SHA-256 verification.'],
  ['Execution model', 'Conservative queue-ahead approximation, configurable latency, maker fees, and decimal accounting.'],
  ['Evaluation', 'Frozen settings, chronological splits, multiple seeds, and comparisons on identical replay episodes.'],
];

export default function ResearchPage() {
  return (
    <div className="research-workspace">
      <header className="workspace-header">
        <span className="breadcrumb">Workspace <span>/</span> Research overview</span>
        <a href={pilot.source} target="_blank" rel="noopener noreferrer" className="quiet-link">Source notes <ArrowUpRight size={14} aria-hidden="true" /></a>
      </header>
      <div className="workspace-content">
        <div className="research-title">
          <div>
            <div className="eyebrow"><FlaskConical size={14} aria-hidden="true" /> RESEARCH OVERVIEW</div>
            <h1>The evidence, in one place.</h1>
            <p>Review the first real-data pilot and the assumptions behind it.</p>
          </div>
          <span className="snapshot-badge"><FileText size={13} aria-hidden="true" /> Historical snapshot · {pilot.date}</span>
        </div>
        <div className="research-metrics">
          <Metric label="Validated captures" value="05" detail="2 training · 1 validation · 2 test" />
          <Metric label="Applied L2 deltas" value="50,000" detail="Binance Spot · BTCUSDT" />
          <Metric label="PPO seeds" value="03" detail="7 / 19 / 43 · 102,400 steps each" />
          <Metric label="Final-test sessions" value="02" detail="Pilot sample · limited inference" />
        </div>
        <div className="research-main-grid">
          <section className="research-panel results-panel" aria-labelledby="results-title">
            <div className="research-panel-heading">
              <div><span className="eyebrow">SEALED PILOT / V1</span><h2 id="results-title">Policy comparison</h2></div>
              <span className="neutral-tag">Fee-inclusive</span>
            </div>
            <p className="panel-description">Mean net P&amp;L per test session in USDT. PPO is averaged across three seeds within each session.</p>
            <div className="loss-scale" aria-hidden="true"><span>−60 USDT</span><span>0</span></div>
            <div className="policy-rows">
              {pilot.policies.map((policy) => (
                <div key={policy.name} className={`policy-row ${policy.kind === 'Learned policy' ? 'policy-highlight' : ''}`}>
                  <div className="policy-label"><span>{policy.name}</span><small>{policy.kind}</small></div>
                  <div className="loss-track" aria-hidden="true"><span style={{ width: `${Math.abs(policy.pnl) / 60 * 100}%` }} /></div>
                  <span className="policy-value">{policy.pnl.toFixed(2)}</span>
                </div>
              ))}
            </div>
            <div className="result-note">
              <span className="note-marker" />
              <p><strong>All evaluated policies lost money after fees.</strong> Two test sessions are too few to establish a reliable performance advantage. Lower activity contributed to the inventory-skew policy&apos;s smaller loss.</p>
            </div>
            <a href={pilot.source} target="_blank" rel="noopener noreferrer" className="panel-source">Read setup, paired differences, and limitations <ArrowUpRight size={14} aria-hidden="true" /></a>
          </section>
          <section className="research-panel assumptions-panel" aria-labelledby="assumptions-title">
            <div className="research-panel-heading">
              <div><span className="eyebrow">EXPERIMENT SETTINGS</span><h2 id="assumptions-title">What was modeled</h2></div>
              <Layers3 size={19} className="text-zinc-500" aria-hidden="true" />
            </div>
            <dl className="assumption-list">
              {[
                ['Market data', 'L2 depth + public trades'],
                ['Maker fee per fill', pilot.makerFee],
                ['Order / cancel latency', pilot.orderLatency],
                ['Quote quantity', pilot.quoteSize],
                ['Absolute inventory cap', pilot.inventoryLimit],
                ['Queue position', 'Conservative estimate'],
              ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            </dl>
            <p className="assumption-footnote">These are frozen pilot inputs, not current exchange fees. Market-by-price data cannot reveal exact queue position.</p>
          </section>
        </div>
        <section className="research-panel status-panel" aria-labelledby="status-title">
          <div className="research-panel-heading">
            <div><span className="eyebrow">IMPLEMENTATION STATUS</span><h2 id="status-title">A working research foundation.</h2></div>
            <span className="neutral-tag">Under active validation</span>
          </div>
          <div className="capability-grid">
            {capabilities.map(([name, description]) => (
              <article key={name}><Check size={15} aria-hidden="true" /><div><h3>{name}</h3><p>{description}</p></div></article>
            ))}
          </div>
          <div className="next-experiment">
            <BookOpen size={18} aria-hidden="true" />
            <div><strong>Next: understand inactivity before expanding training.</strong><p>A small PPO v2 model is now connected to the replay. It produces zero fills on the displayed training recordings; no-quote and widest-grid controls also return zero. Trading improvements remain unproven.</p></div>
            <a href={`${repositoryUrl}/blob/main/docs/phase13-ppo-v2-controls.md`} target="_blank" rel="noopener noreferrer" className="quiet-link" aria-label="Read PPO activity-control protocol"><ArrowUpRight size={18} aria-hidden="true" /></a>
          </div>
        </section>
        <section className="research-panel collection-panel" aria-labelledby="collection-title">
          <div className="research-panel-heading">
            <div><span className="eyebrow">FRESH DATA / PPO V2</span><h2 id="collection-title">From capture to a visible policy.</h2></div>
            <span className="neutral-tag">Validated at replay export</span>
          </div>
          <p className="panel-description">{replayCatalog.training_sessions_validated} training sessions from {nextStudy.name} passed validation at the latest replay export. Watch the first and last recordings in the working player. Validation and test counts below are collection targets, not live progress.</p>
          <div className="collection-targets">
            <div><strong>{replayCatalog.training_sessions_validated}</strong><span>training captures validated</span></div>
            <div><strong>{nextStudy.validationSessions}</strong><span>validation session target</span></div>
            <div><strong>{nextStudy.testSessions}</strong><span>test session target</span></div>
          </div>
          <p className="assumption-footnote">10,000 applied L2 deltas per session · 250,000 planned total. Confirm fees and captured depth before freezing model settings.</p>
          <div className="hero-actions"><Link href="/replay" className="button-accent">Play the captured sessions <ArrowRight size={15} aria-hidden="true" /></Link></div>
          <a href={`${repositoryUrl}/blob/main/docs/phase14-quote-grid-and-study.md`} target="_blank" rel="noopener noreferrer" className="panel-source">Read the collection and preflight guide <ArrowUpRight size={14} aria-hidden="true" /></a>
        </section>
        <section className="provenance-panel">
          <div><FileText size={17} aria-hidden="true" /><strong>Source-linked, not live telemetry</strong></div>
          <p>This page summarizes checked-in pilot notes and works without the API. Raw captures, model weights, and the full evaluation report are not served here. The separate paper simulator still uses the legacy environment.</p>
          <details><summary>Recorded evaluation report SHA-256</summary><code>{pilot.reportSha256}</code></details>
        </section>
        <footer className="research-footer"><span>No profitability or generalization claim.</span><Link href="/replay">Play real-data replay <ArrowRight size={14} aria-hidden="true" /></Link></footer>
      </div>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <article className="research-metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}
