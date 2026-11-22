import type { Metadata } from 'next';
import { labData, type QuoteMetrics } from '../lab-data';
import s from '../lab.module.css';

export const metadata: Metadata = {
  title: 'Queue-aware market making | ApexHFT',
  description: 'Compare Avellaneda–Stoikov and signal-adjusted quoting on the same real L2 recording.',
};

const metrics: { name: string; read: (value: QuoteMetrics) => string | number }[] = [
  { name: 'Net P&L · USDT', read: (m) => Number(m.net_pnl).toFixed(6) },
  { name: 'Simulated fills', read: (m) => m.fills },
  { name: 'Quantity fill rate', read: (m) => `${(Number(m.quantity_fill_rate) * 100).toFixed(1)}%` },
  { name: 'Fees · USDT', read: (m) => Number(m.fees).toFixed(6) },
  { name: 'Peak absolute inventory · BTC', read: (m) => m.maximum_absolute_inventory },
  ...[[100, '100 ms'], [1000, '1 s']].map(([milliseconds, label]) => ({
    name: `Signed mid-price movement P&L · ${label}`,
    read: (m: QuoteMetrics) => {
      const markout = m.adverse_selection[String(Number(milliseconds) * 1e6)];
      return markout?.signed_mid_move_pnl == null ? 'Not observed' :
        `${Number(markout.signed_mid_move_pnl).toFixed(6)} (${markout.observed_fills} fills)`;
    },
  })),
];

export default function MarketMakingPage() {
  const { sessions, simulation_parameters: settings } = labData.quoteReport;
  return (
    <div className={s.shell}>
      <span className={s.kicker}>Project 02 · Strategy comparison</span>
      <h1 className={s.title}>Queue-aware market making</h1>
      <p className={s.intro}>Compare plain Avellaneda–Stoikov, fixed wider quotes without a prediction, and quotes adjusted by the signal. Each column runs on the same recording with the same order size, inventory constraints, latency, and fees.</p>
      <section className={s.panel}>
        <h2>Replay assumptions</h2>
        <p className={s.muted}>{labData.venue} · {labData.symbol} · {labData.snapshot ?? 'Recorded pilot'}. Assumed maker fee: {Number(settings.maker_fee_rate) * 10_000} bps. Order / cancel latency: {settings.order_latency_ns / 1e6} / {settings.cancel_latency_ns / 1e6} ms. Fills and queue positions are simulated estimates, not exchange executions.</p>
      </section>
      {sessions.map((session) => {
        const variants = [
          { name: 'Plain A–S', metrics: session.avellaneda_stoikov },
          { name: 'Fixed wider quotes', metrics: session.symmetric_widened },
          { name: 'Signal-adjusted A–S', metrics: session.alpha_widened },
        ];
        return (
          <section className={s.panel} key={session.test_capture}>
            <h2>{session.test_capture.replace('.jsonl', '')}</h2>
            <p className={s.note}>{session.matched_updates} signal updates · {session.horizon_updates}-update forecast · {session.widen_ticks}-tick adjustment</p>
            <div className={s.tableWrap}>
              <table className={s.table}>
                <thead><tr><th scope="col">Metric</th>{variants.map(({ name }) => <th scope="col" key={name}>{name}</th>)}</tr></thead>
                <tbody>{metrics.map((metric) => (
                  <tr key={metric.name}><th scope="row">{metric.name}</th>{variants.map((variant) => <td key={variant.name}>{metric.read(variant.metrics)}</td>)}</tr>
                ))}</tbody>
              </table>
            </div>
          </section>
        );
      })}
      <p className={s.muted}>Fixed widening moves both quotes outward by the same per-side distance used by the signal arm, which widens only one side. It is a width-only reference, not a matched-activity control. Negative signed movement means the mid-price moved against a simulated fill. These short recordings show the mechanics; they do not establish an edge.</p>
    </div>
  );
}
