'use client';

import { useState } from 'react';
import results from '../../../public/research/advanced-development.json';
import s from './lab.module.css';

const fixed = (n: number | null, digits: number) => n === null ? '—' : n.toFixed(digits);
const models = [
  ['majority', 'Majority'], ['microprice_sign', 'Microprice'], ['deeplob', 'DeepLOB-style'],
  ['cnn-lstm', 'CNN–LSTM'], ['transformer', 'Transformer'],
] as const;
const fillNames: Record<string, string> = {
  train_fill_rate: 'Training fill rate',
  logistic: 'Logistic',
  validation_calibrated: 'Validation-calibrated',
};

function SourceReports() {
  return (
    <details>
      <summary className={s.detailSummary}>Report provenance</summary>
      {Object.entries(results.sourceReportSha256).map(([name, hash]) => (
        <p key={name} className={s.hash}>{name}: <code>{hash}</code></p>
      ))}
    </details>
  );
}

export function DepthModelResults() {
  const [index, setIndex] = useState(0);
  const selected = results.depth[index];
  const control = Math.max(selected.macroF1.majority, selected.macroF1.microprice_sign);
  const neural = Math.max(selected.macroF1.deeplob, selected.macroF1['cnn-lstm'], selected.macroF1.transformer);
  const finding = neural > control ? 'A neural model led on this recording split.' : neural === control
    ? 'The best neural model tied the strongest simple control.'
    : 'A simple control led the neural models at this horizon.';
  return (
    <section className={s.panel} aria-labelledby="depth-results-title">
      <div className={s.sectionHeading}><div><span className={s.kicker}>02 / Model comparison</span><h2 id="depth-results-title">How did the deeper models do?</h2></div><span className={s.tag}>Development</span></div>
      <div className={s.sectionHeading}>
        <p className={s.note}>{finding}</p>
        <div className={s.choices} role="group" aria-label="Forecast benchmark horizon">
          {results.depth.map(({ horizon }, i) => <button type="button" key={horizon} aria-pressed={index === i} onClick={() => setIndex(i)}>{horizon} updates</button>)}
        </div>
      </div>
      <figure className={s.benchmarkChart}>
        <figcaption>Macro-F1 · higher is better</figcaption>
        <ul className={s.bars}>
          {models.map(([key, label], i) => (
            <li key={key}><span>{label}</span><div aria-hidden="true" className={s.barTrack}><div className={i < 2 ? s.controlBar : s.neuralBar} style={{ width: `${selected.macroF1[key] * 100}%` }} /></div><strong>{fixed(selected.macroF1[key], 3)}</strong></li>
          ))}
        </ul>
      </figure>
      <p className={s.note}>This short engineering run does not establish a predictive or trading edge.</p>
      <details className={s.replayDetail}>
      <summary className={s.detailSummary}>Full benchmark results</summary>
      <p className={s.note}>{results.levels} levels per side · {results.lookback}-update inputs · {results.depthEpochs} training epoch · {results.captures.length} reused test recordings.</p>
      <div className={s.tableWrap}>
        <table className={s.table}>
          <caption>Test macro-F1 on common prediction windows (higher is better)</caption>
          <thead><tr><th scope="col">Horizon</th><th scope="col">Windows</th>{models.map(([key, label]) => <th scope="col" key={key}>{label}</th>)}</tr></thead>
          <tbody>{results.depth.map(({ horizon, rows, macroF1 }) => (
            <tr key={horizon}><th scope="row">{horizon} updates</th><td>{rows}</td>{models.map(([key]) => <td key={key}>{fixed(macroF1[key], 3)}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
      <SourceReports />
      </details>
    </section>
  );
}

export function QueueModelResults() {
  const [capture, setCapture] = useState(results.captures[0].file);
  const shown = results.paired.filter((item) => item.capture === capture);
  const values = results.paired.flatMap(({ off, on }) => [off.pnl, on.pnl, on.matchedPnl]).filter((p): p is number => p !== null);
  const scale = Math.max(...values.map(Math.abs), 0.001);
  const arms = [
    { name: 'Without fill signal', read: ({ off }: (typeof shown)[number]) => off.pnl },
    { name: 'With fill signal', read: ({ on }: (typeof shown)[number]) => on.pnl },
    { name: 'Size-matched rule', read: ({ on }: (typeof shown)[number]) => on.matchedPnl },
  ];
  return (
    <>
      <section className={s.panel} aria-labelledby="rl-results-title">
        <div className={s.sectionHeading}><div><span className={s.kicker}>01 / Strategy comparison</span><h2 id="rl-results-title">Did the fill signal help?</h2></div><span className={s.tag}>Development</span></div>
        <div className={s.sectionHeading}>
          <p className={s.note}>Compare the same market and fee assumptions, with and without the extra input.</p>
          <div className={s.choices} role="group" aria-label="Market making recorded session">
            {results.captures.map(({ file }, i) => <button type="button" key={file} aria-pressed={capture === file} onClick={() => setCapture(file)}>Session {i + 1}</button>)}
          </div>
        </div>
        <div className={s.strategyCharts}>
          {shown.map((row) => (
            <figure className={s.benchmarkChart} key={row.algorithm}>
              <figcaption><strong>{row.algorithm}</strong> · Simulated net P&amp;L · USDT</figcaption>
              <ul className={s.bars}>
                {arms.map(({ name, read }, i) => {
                  const value = read(row);
                  return (
                    <li key={name}><span>{name}</span><div aria-hidden="true" className={`${s.barTrack} ${s.divergingTrack}`}>
                      {value !== null && <div className={i === 2 ? s.controlBar : s.neuralBar} style={{ width: `${Math.abs(value) / scale * 50}%`, left: value < 0 ? `${50 + value / scale * 50}%` : '50%' }} />}
                    </div><strong>{fixed(value, 4)}</strong></li>
                  );
                })}
              </ul>
            </figure>
          ))}
        </div>
        <p className={s.note}>Zero is the center line. The plotted results already include fees. Seeds are averaged within each recording, not counted as independent markets.</p>
        <details className={s.replayDetail}>
          <summary className={s.detailSummary}>Full strategy results and settings</summary>
          <p className={s.note}>{results.rlSteps} training steps per run · seeds {results.seeds.join(', ')}. Both arms observe Hawkes arrival rates; the second arm also observes simulated fill probabilities.</p>
        <div className={s.tableWrap}>
          <table className={s.table}>
            <caption>Mean fee-inclusive simulated P&amp;L per recording · USDT</caption>
            <thead><tr><th scope="col">Session / agent</th><th scope="col">Fill inputs off</th><th scope="col">Fill inputs on</th><th scope="col">Size-matched control (on)</th></tr></thead>
            <tbody>{results.paired.map(({ capture, algorithm, off, on }) => (
              <tr key={capture + algorithm}><th scope="row">{capture.replace('.jsonl', '')} · {algorithm}</th><td>{fixed(off.pnl, 4)}</td><td>{fixed(on.pnl, 4)}</td><td>{fixed(on.matchedPnl, 4)}</td></tr>
            ))}</tbody>
          </table>
        </div>
        <p className={s.note}>The control size was chosen on validation data, before this comparison.</p>
        </details>
      </section>
      <div className={s.grid}>
        <details className={s.panel}>
          <summary className={s.detailSummary}>Trade arrival model</summary>
          <div className={s.tableWrap}>
            <table className={s.table}>
              <caption>Test log-likelihood per trade (higher is better)</caption>
              <thead><tr><th scope="col">Session</th><th scope="col">Hawkes</th><th scope="col">Poisson</th></tr></thead>
              <tbody>{results.arrival.map((arrival) => <tr key={arrival.capture}><th scope="row">{arrival.capture.replace('.jsonl', '')}</th><td>{fixed(arrival.hawkes, 3)}</td><td>{fixed(arrival.poisson, 3)}</td></tr>)}</tbody>
            </table>
          </div>
        </details>
        <details className={s.panel}>
          <summary className={s.detailSummary}>Simulated fill probabilities</summary>
          <div className={s.tableWrap}>
            <table className={s.table}>
              <caption>One-second test probes (lower errors are better)</caption>
              <thead><tr><th scope="col">Model</th><th scope="col">Brier score</th><th scope="col">Log loss</th></tr></thead>
              <tbody>{results.fill.map((fill) => <tr key={fill.name}><th scope="row">{fillNames[fill.name] ?? fill.name}</th><td>{fixed(fill.brier, 5)}</td><td>{fixed(fill.logLoss, 5)}</td></tr>)}</tbody>
            </table>
          </div>
          <p className={s.note}>{results.fill[0].fills} of {results.fill[0].rows.toLocaleString('en-US')} hypothetical quotes filled in replay, not at an exchange.</p>
        </details>
      </div>
      <div className={s.panel}><SourceReports /></div>
    </>
  );
}
