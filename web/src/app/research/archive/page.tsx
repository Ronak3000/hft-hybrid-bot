import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowRight, ArrowUpRight, FileText, FlaskConical, Layers3 } from 'lucide-react';
import { pilot } from '@/lib/research';

export const metadata: Metadata = {
  title: 'Archived PPO pilot | ApexHFT',
  description: 'Documented BTCUSDT pilot results and research assumptions, available without a running backend.',
};

export default function ArchivePage() {
  return (
    <div className="research-workspace">
      <header className="workspace-header">
        <span className="breadcrumb">Research <span>/</span> Archived PPO pilot</span>
        <a href={pilot.source} target="_blank" rel="noopener noreferrer" className="quiet-link">Source notes <ArrowUpRight size={14} aria-hidden="true" /></a>
      </header>
      <div className="workspace-content">
        <div className="research-title">
          <div>
            <div className="eyebrow"><FlaskConical size={14} aria-hidden="true" /> RESEARCH ARCHIVE</div>
            <h1>Earlier PPO pilot</h1>
            <p>Historical results and assumptions from the separate PPO study.</p>
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
        <section className="provenance-panel">
          <div><FileText size={17} aria-hidden="true" /><strong>Source-linked, not live telemetry</strong></div>
          <p>This page summarizes checked-in pilot notes and works without the API. Raw captures, model weights, and the full evaluation report are not served here.</p>
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
