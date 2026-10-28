import Link from 'next/link';
import { ArrowDown, ArrowRight, ArrowUpRight, BookOpen, Check, Cpu, GitBranch, Layers3, TerminalSquare } from 'lucide-react';
import { pilot, repositoryUrl } from '@/lib/research';

const stages = [
  { number: '01', title: 'Capture the market', description: 'Binance Spot depth and public trades, checked for sequence gaps and sealed with source hashes.', icon: Layers3 },
  { number: '02', title: 'Replay with assumptions', description: 'Deterministic replay with queue-ahead volume, order latency, fees, and explicit inventory limits.', icon: GitBranch },
  { number: '03', title: 'Compare the evidence', description: 'Chronological splits, multiple PPO seeds, and rule-based controls on identical replay episodes.', icon: BookOpen },
];
const asks = [
  { price: '60,004.00', size: '0.842', total: '2.184', width: 81 },
  { price: '60,003.00', size: '0.615', total: '1.342', width: 58 },
  { price: '60,002.00', size: '0.727', total: '0.727', width: 34 },
];
const bids = [
  { price: '60,000.00', size: '0.938', total: '0.938', width: 42 },
  { price: '59,999.00', size: '0.524', total: '1.462', width: 65 },
  { price: '59,998.00', size: '0.816', total: '2.278', width: 89 },
];

export default function LandingPage() {
  return (
    <div className="research-home">
      <nav aria-label="Main navigation" className="home-nav">
        <Link href="/" className="brand-lockup"><TerminalSquare size={24} aria-hidden="true" /><span>Apex<span className="accent-text">HFT</span></span></Link>
        <div className="home-nav-links">
          <Link href="/research" className="quiet-link">Research</Link>
          <a href="#architecture" className="quiet-link architecture-link">Architecture</a>
          <a href={repositoryUrl} target="_blank" rel="noopener noreferrer" className="quiet-link" aria-label="View ApexHFT on GitHub">GitHub <ArrowUpRight size={14} aria-hidden="true" /></a>
          <Link href="/replay" className="button-light">Open replay <ArrowRight size={15} aria-hidden="true" /></Link>
        </div>
      </nav>
      <section className="home-hero">
        <div className="hero-copy">
          <div className="eyebrow"><span className="status-dot" /> Market microstructure research</div>
          <h1>Understand the book.<br /><span className="muted-heading">Question the edge.</span></h1>
          <p className="hero-description">A C++ matching engine and Python research workbench for studying market making—from the order queue to the final experiment.</p>
          <div className="hero-actions">
            <Link href="/replay" className="button-accent">Play real-data replay <ArrowRight size={17} aria-hidden="true" /></Link>
            <Link href="/research" className="button-outline">Explore the research <ArrowUpRight size={16} aria-hidden="true" /></Link>
          </div>
          <p className="hero-footnote"><Check size={14} aria-hidden="true" /> Real market captures. Explicit simulation assumptions. Open results.</p>
        </div>
        <div className="book-preview" aria-label="Illustrative order book, not live market data">
          <div className="panel-topline"><span><span className="status-dot" /> ORDER BOOK</span><span className="mono text-zinc-400">BTC / USDT</span></div>
          <div className="book-caption">Illustrative depth · not live data</div>
          <div className="book-columns"><span>Price (USDT)</span><span>Size (BTC)</span><span>Total</span></div>
          {asks.map((row) => <BookRow key={row.price} row={row} side="ask" />)}
          <div className="book-mid"><strong>60,001.00</strong><span>Spread <b>2.00</b></span></div>
          {bids.map((row) => <BookRow key={row.price} row={row} side="bid" />)}
          <div className="book-footer"><Cpu size={14} aria-hidden="true" /> Price-time priority <span>FIFO / C++20</span></div>
        </div>
      </section>
      <section className="evidence-strip" aria-label="Project measurements">
        <div><span className="eyebrow">Engine microbenchmark</span><strong>11.9M <small>actions/s</small></strong><p>Attempted synthetic actions · single thread · in-process</p></div>
        <div><span className="eyebrow">Captured L2 events</span><strong>{pilot.depthDeltas.toLocaleString('en-US')} <small>deltas</small></strong><p>Five validated BTCUSDT pilot sessions</p></div>
        <div><span className="eyebrow">Reproducible evaluation</span><strong>{pilot.seeds.length} <small>PPO seeds</small></strong><p>Chronological train / validation / test</p></div>
      </section>
      <section id="architecture" className="workflow-section">
        <div className="section-heading"><div><span className="eyebrow">THE WORKFLOW</span><h2>From market events to evidence.</h2></div><ArrowDown size={24} className="text-zinc-500" aria-hidden="true" /></div>
        <div className="workflow-grid">
          {stages.map(({ number, title, description, icon: Icon }) => (
            <article key={number} className="workflow-card">
              <div className="workflow-card-top"><Icon size={22} aria-hidden="true" /><span>{number}</span></div>
              <h3>{title}</h3><p>{description}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="pilot-callout">
        <div><span className="eyebrow">FIRST SEALED PILOT · {pilot.date}</span><h2>A useful result, including the losses.</h2><p>PPO beat fixed-spread and random controls on two test sessions, but lost to stronger inventory-aware baselines. Every policy lost money after fees.</p></div>
        <Link href="/research" className="button-outline">Read the pilot results <ArrowRight size={17} aria-hidden="true" /></Link>
      </section>
      <footer className="home-footer"><span>ApexHFT / Independent research</span><span>Paper simulation only · No exchange orders routed</span></footer>
    </div>
  );
}

function BookRow({ row, side }: { row: typeof asks[number]; side: 'ask' | 'bid' }) {
  return (
    <div className={`book-row ${side}-row`}>
      <span className="depth-fill" style={{ width: `${row.width}%` }} />
      <span>{row.price}</span><span>{row.size}</span><span>{row.total}</span>
    </div>
  );
}
