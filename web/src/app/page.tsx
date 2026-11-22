import Link from 'next/link';
import { ArrowDown, ArrowRight, ArrowUpRight, AudioLines, CandlestickChart, ChartNoAxesCombined, FlaskConical, Layers3, Play } from 'lucide-react';
import { labData } from './research/lab-data';
import { TapePreview } from '@/components/market-shell/TapePreview';
import s from '@/components/market-shell/home.module.css';

const studios = [
  { title: 'Order-book prediction', label: 'PROJECT 01', icon: AudioLines,
    description: 'See what the book looked like at the decision, what the model expected, and what happened next.',
    href: '/research/lob-prediction', action: 'Explore prediction replay' },
  { title: 'Queue-aware market making', label: 'PROJECT 02', icon: Layers3,
    description: 'Compare quoting decisions against the same recording, with fees, latency, and estimated fills in view.',
    href: '/research/queue-market-making', action: 'Compare quoting policies' },
];

const work = [
  { href: '/train', icon: FlaskConical, title: 'Train a model', text: 'Configure a training run and follow its progress.' },
  { href: '/backtest', icon: ChartNoAxesCombined, title: 'Test a strategy', text: 'Review a historical run without risking capital.' },
  { href: '/dashboard', icon: CandlestickChart, title: 'Open the live desk', text: 'Follow a paper session when the backend is connected.' },
];

export default function LandingPage() {
  const frames = labData.sessions[0]?.frames ?? [];
  const stride = Math.max(1, Math.ceil(frames.length / 160));
  const tape = frames.filter((_, index) => index % stride === 0 || index === frames.length - 1)
    .map((frame) => ({ time: frame[0], mid: frame[2] }));
  return (
    <div className={s.home}>
      <section className={s.hero}>
        <div className={s.heroCopy}>
          <span className={s.eyebrow}><span className={s.signal} /> THE MARKET MICROSTRUCTURE WORKSPACE</span>
          <h1>Read the market.<br/><em>Test the idea.</em></h1>
          <p>Replay real order-book data, explore how models make decisions, and see what survives a simulation with costs.</p>
          <div className={s.actions}>
            <Link href="/market-replay" className={s.primary}><Play size={16} aria-hidden="true" /> Open market replay</Link>
            <Link href="/research" className={s.secondary}>Explore research <ArrowUpRight size={15} aria-hidden="true" /></Link>
          </div>
          <a href="#research-studios" className={s.jump}><ArrowDown size={15} aria-hidden="true" /> Find your next experiment</a>
        </div>
        {tape.length > 0 && <TapePreview points={tape} />}
      </section>
      <section className={s.studio} id="research-studios" aria-labelledby="research-studio-title">
        <div className={s.sectionHeading}>
          <div><span className={s.eyebrow}>THE RESEARCH STUDIO</span><h2 id="research-studio-title">Two ways to study the book.</h2></div>
          <p>Start with a question, then open the evidence behind the result.</p>
        </div>
        <div className={s.studioGrid}>
          {studios.map(({ title, label, icon: Icon, description, href, action }) => (
            <article key={title} className={s.studioCard}>
              <div className={s.cardTop}><Icon size={24} aria-hidden="true" /><span>{label}</span></div>
              <h3>{title}</h3><p>{description}</p>
              <Link href={href}>{action} <ArrowRight size={15} aria-hidden="true" /></Link>
            </article>
          ))}
        </div>
      </section>
      <section className={s.work} aria-labelledby="workbench-title">
        <div><span className={s.eyebrow}>WORKBENCH</span><h2 id="workbench-title">Go from training to paper trading.</h2></div>
        <div className={s.workGrid}>
          {work.map(({ href, icon: Icon, title, text }) => (
            <Link key={href} href={href} className={s.workItem}><Icon aria-hidden="true" size={22} /><span><strong>{title}</strong><small>{text}</small></span><ArrowUpRight size={15} aria-hidden="true" /></Link>
          ))}
        </div>
      </section>
    </div>
  );
}
