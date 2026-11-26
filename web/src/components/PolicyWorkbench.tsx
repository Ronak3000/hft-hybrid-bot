'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useState } from 'react';
import { API_BASE } from '@/lib/api';

type Mode = 'training' | 'backtest' | 'live';
type Job = {status: string; message: string; result: Record<string, unknown> | null};
type Model = {id: string; steps: number; environment:string};
type Value = string | number | boolean | number[] | null;
type FieldSchema = {title: string; description: string; type?: string; enum?: string[]; minimum?: number; maximum?: number; exclusiveMinimum?: number; anyOf?: {type: string}[]};
type Settings = {ppo: Record<string, Value>; simulation: Record<string, Value>};
type Schema = {properties: Record<string, FieldSchema>};
type Options = {recordings: string[]; ppo: Schema; simulation: Schema; defaults: Settings};
const titles = {training: 'Train a policy', backtest: 'Historical test', live: 'Live paper test'};
const JOB_KEY = 'apex-candle-job-training';
const detail = {
  training: 'Choose a real Binance data source. Train verifies the market data, runs PPO and saves the weights.',
  backtest: 'Select frozen weights and a later UTC window. The model determines which exchange data and paper execution rules are used.',
  live: 'Test frozen weights on the matching public exchange feed. No exchange orders are sent.',
};

async function read(url: string, init?: RequestInit) {
  const response = await fetch(API_BASE + url, {cache: 'no-store', ...init});
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || response.status));
  return body;
}

export function PolicyWorkbench({mode}: {mode: Mode}) {
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState('');
  const [start, setStart] = useState(mode === 'training' ? '2024-01-01T00:00' : '2024-01-01T01:00');
  const [end, setEnd] = useState(mode === 'training' ? '2024-01-01T01:00' : '2024-01-01T02:00');
  const [size, setSize] = useState(mode === 'live' ? 60 : 2048);
  const [token, setToken] = useState('');
  const [jobId, setJobId] = useState('');
  const [job, setJob] = useState<Job | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [preset, setPreset] = useState('custom');
  const [days, setDays] = useState(7);
  const [budget, setBudget] = useState(100);
  const [symbol,setSymbol]=useState('BTCUSDT');
  const candle = mode === 'training' ? true : models.find(m => m.id === model)?.environment === 'ApexBinanceUSMinute-v1';
  const keyless = false;
  const [options, setOptions] = useState<Options | null>(null);
  const [settings, setSettings] = useState<Settings>({ppo:{}, simulation:{}});
  const [estimate, setEstimate] = useState<Record<string, unknown> | null>(null);
  const [inspecting, setInspecting] = useState(false);
  useEffect(() => {
    let active = true;
    if (mode === 'training') read('/api/training/settings').then((value: Options) => {
      if (active) {
        setOptions(value); setSettings(value.defaults);
        setJobId(sessionStorage.getItem(JOB_KEY) || sessionStorage.getItem('apex-job-training') || '');
      }
    }).catch(e => {if (active) setError(String(e));});
    return () => {active = false;};
  }, [mode]);
  function selectRange(value: string) {
    setPreset(value); setEstimate(null);
    if (value === 'custom') return;
    const now = new Date(), finish = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), value === 'days' ? now.getUTCDate() : 1));
    if (value === 'demo') finish.setTime(Math.floor(now.getTime()/60000)*60000-15*60000);
    const begin = new Date(finish);
    if (value === 'demo') begin.setTime(finish.getTime()-3600000);
    else if (value === 'days') begin.setUTCDate(begin.getUTCDate() - days);
    else begin.setUTCMonth(begin.getUTCMonth() - Number(value));
    setStart(begin.toISOString().slice(0,16)); setEnd(finish.toISOString().slice(0,16));
    if (mode === 'training') {
      const rollout = Number(settings.ppo.n_steps || 2048), interval = candle ? 60e9 : Number(settings.simulation.decision_interval_ns || 1e9);
      setSize(Math.ceil((finish.getTime() - begin.getTime()) * 1e6 / interval / rollout) * rollout);
    }
  }
  function requestBody() {
    const simulation = {...settings.simulation};
    if (typeof simulation.half_spread_tick_choices === 'string') simulation.half_spread_tick_choices = simulation.half_spread_tick_choices.split(',').map(v => Number(v.trim()));
    return {symbol, ...(mode === 'live' ? {seconds: size} : {start: start + 'Z', end: end + 'Z', max_dataset_gb: budget}),
            ...(mode === 'training' ? {steps: size, ppo: settings.ppo, ...(candle ? {source:'candles'} : {simulation})} : {model_id: model})};
  }
  async function inspect() {
    setInspecting(true); setError('');
    try {setEstimate(await read('/api/training/estimate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(requestBody())}));}
    catch (e) {setError(String(e));} finally {setInspecting(false);}
  }
  useEffect(() => {
    if (mode === 'training') return;
    let active = true;
    read('/api/models/BTCUSDT').then(v => {
      if (active) {
        const requested = new URLSearchParams(window.location.search).get('model');
        setModels(v.models);
        setModel(v.models.find((m: Model) => m.id === requested)?.id || v.models[0]?.id || '');
      }
    }).catch(e => {if (active) setError(String(e));});
    return () => {active = false;};
  }, [mode]);
  useEffect(() => {
    if (!jobId) return;
    let active = true, timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await read('/api/' + mode + '/status/' + jobId);
        if (!active) return;
        setJob(value); setError('');
        if (value.status === 'running') timer = setTimeout(poll, 1200);
      } catch (e) {
        if (active) { setError(String(e)); timer = setTimeout(poll, 4000); }
      }
    }
    void poll();
    return () => {active = false; clearTimeout(timer);};
  }, [jobId, mode]);
  async function submit(e: FormEvent) {
    e.preventDefault(); setSending(true); setError('');
    try {
      const value = await read('/api/' + mode + '/start', {method: 'POST',
        headers: {'Content-Type':'application/json', ...(token ? {Authorization: 'Bearer ' + token} : {})},
        body: JSON.stringify(requestBody())});
      sessionStorage.setItem(JOB_KEY, value.job_id); setJob({status:'running',message:'Submitted',result:null}); setJobId(value.job_id);
    } catch (e) { setError(String(e)); } finally { setSending(false); }
  }
  const busy = sending || job?.status === 'running';
  return <div className="research-workspace"><header className="workspace-header"><span className="breadcrumb">Research desk / {symbol}</span></header>
    <div className="workspace-content"><div className="research-title"><div><div className="eyebrow">BINANCE SPOT · PAPER EXECUTION</div>
      <h1>{titles[mode]}</h1><p>{detail[mode]}</p></div></div>
    <form className="research-panel policy-form" onSubmit={submit}>
      {mode === 'training' && !options && <p role="status">Loading supported PPO settings from the backend…</p>}
      {mode !== 'training' && <label>Saved PPO checkpoint<select value={model} onChange={e => setModel(e.target.value)} required>
        {!models.length && <option value="">No verified weights available</option>}
        {models.map(m => <option key={m.id} value={m.id}>{m.environment === 'ApexBinanceUSMinute-v1' ? 'Binance.US candles' : 'Binance L2'} · {m.id} · {m.steps.toLocaleString()} steps</option>)}</select></label>}
      <label>Crypto market<select value={symbol} onChange={e=>setSymbol(e.target.value)}>{['BTCUSDT','ETHUSDT','SOLUSDT'].map(s=><option key={s}>{s}</option>)}</select></label>
      {mode !== 'live' && !keyless && <>
        <label>Historical period<select value={preset} onChange={e => selectRange(e.target.value)}>
          <option value="demo">Recent demo hour (leaves 15 minutes for testing)</option>
          <option value="1">Previous month</option><option value="3">Previous 3 months</option><option value="6">Previous 6 months</option>
          <option value="days">Custom number of days</option><option value="custom">Custom UTC start / end</option></select></label>
        {preset === 'days' && <div className="policy-fields"><label>Completed days<input type="number" min="1" max="3650" value={days} onChange={e => setDays(Number(e.target.value))} /></label><button type="button" className="button-outline" onClick={() => selectRange('days')}>Apply days</button></div>}
        <div className="policy-fields"><label>Start (UTC)<input type="datetime-local" value={start} onChange={e => {setStart(e.target.value); setPreset('custom'); setEstimate(null);}} required /></label>
        <label>End (UTC, exclusive)<input type="datetime-local" value={end} onChange={e => {setEnd(e.target.value); setPreset('custom'); setEstimate(null);}} required /></label></div>
        <label>Dataset disk budget (GiB)<input type="number" min="0.1" max="10000" step="any" value={budget} onChange={e => setBudget(Number(e.target.value))} /></label>
        {candle ? <p className="panel-description">Download available closed 1-minute Binance.US candles for the selected dates, without a key. Missing minutes are not invented: historical replay starts a new flat episode after each gap. This PPO chooses flat or long 0.001 units; paper position changes use the following minute’s close, with zero fees and slippage. The C++ order book is not used.</p> : <><p className="panel-description">Binance L2 history comes through Tardis; most dates require archive access. Verified chunks are reused on retry.</p>
        <p className="panel-description">L2 archive episodes reset the portfolio every ten minutes.</p></>}</>}
      {mode === 'live' && candle && <p>Binance.US closed minute candles · allow 120 seconds to observe a new bar. No fabricated interim ticks.</p>}
      {mode !== 'backtest' && <label>{mode === 'live' ? 'Session duration (seconds)' : 'Total training steps'}<input type="number" min={mode === 'live' ? 10 : 2} max={mode === 'live' ? 300 : 100000000} step="1" value={size} onChange={e => {setSize(Number(e.target.value)); setEstimate(null);}} required /></label>}
      {mode === 'training' && options && (['ppo','simulation'] as const).filter(g => !candle || g === 'ppo').map(group => <details key={group}><summary>{group === 'ppo' ? 'PPO learning and network settings' : 'Quote, risk and execution assumptions'}</summary>
        <div className="policy-settings">{Object.entries(options[group].properties).map(([key, schema]) => <SettingField key={key} schema={schema} value={settings[group][key]} onChange={value => {
          setSettings(s => ({...s, [group]: {...s[group], [key]: value}})); setEstimate(null);
        }} />)}</div></details>)}
      {mode === 'training' && candle && <button type="button" className="button-outline" onClick={() => {const n=Number(settings.ppo.n_steps || 2048);setSize(Math.max(n,Math.ceil(((Date.parse(end+'Z')-Date.parse(start+'Z'))/60000-1)/n)*n));}}>Set steps to cover selected dates</button>}
      {mode === 'training' && !keyless && !candle && <><button type="button" className="button-outline" disabled={!options || inspecting} onClick={inspect}>{inspecting ? 'Checking…' : 'Estimate download and training budget'}</button>
        {estimate && <div className="policy-estimate"><p>{String(estimate.selected_minutes)} selected minutes · {String(estimate.chunks)} chunks · up to {String(estimate.maximum_minute_requests)} archive requests</p>
          <p>{estimate.requires_archive_key && !estimate.archive_key_configured ? 'Archive access missing: configure TARDIS_API_KEY on the server.' : 'Archive access configuration is present or this range uses free sample dates; availability is verified during download.'}</p>
          <p>Minimum steps to cover this range: {Number(estimate.minimum_training_steps).toLocaleString()}.</p>
          {!estimate.training_budget_covers_range && <button type="button" onClick={() => {setSize(Number(estimate.minimum_training_steps)); setEstimate(null);}}>Use this training budget</button>}
        </div>}</>}
      <details><summary>Hosted operator access</summary><label>Operator token<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} /></label></details>
      <p className="panel-description">Paper orders and fills are simulated on genuine market inputs. New training defaults to zero fees as requested; this is not a fee-inclusive profitability claim. Test and live sessions keep the model&apos;s saved configuration.</p>
      <button className="button-accent" disabled={busy || (mode !== 'training' && !model) || (mode === 'training' && !options)}>{busy ? 'Job in progress' : titles[mode]}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {job && <section className="research-panel policy-output" aria-live="polite"><div className="eyebrow">{job.status}</div><h2>{job.message}</h2>
      {job.status === 'running' && <button className="button-outline" onClick={async () => {
        try {await read('/api/training/cancel/' + jobId, {method:'POST',headers:token ? {Authorization:'Bearer ' + token} : {}});}
        catch (e) {setError(String(e));}
      }}>Cancel job</button>}
      {job.result && <><dl>{Object.entries(job.result).filter(([k]) => ['model_id','training_steps','bars','missing_minutes','continuous_episodes','fills','net_pnl','turnover','total_fills','inventory','net_worth','episode_steps'].includes(k)).map(([k,v]) => <div key={k}><dt>{k.replaceAll('_',' ')}</dt><dd>{String(v)}</dd></div>)}</dl>
      <details><summary>Run details and provenance</summary><pre>{JSON.stringify(job.result, null, 2)}</pre></details></>}
      {mode === 'training' && job.status === 'completed' && <div className="hero-actions"><Link href={'/backtest?model='+encodeURIComponent(String(job.result?.model_id))+'&symbol='+encodeURIComponent(String(job.result?.symbol||symbol))}>Test on history →</Link><Link href={'/dashboard?model='+encodeURIComponent(String(job.result?.model_id))+'&symbol='+encodeURIComponent(String(job.result?.symbol||symbol))}>Test live →</Link></div>}
    </section>}</div></div>;
}

function SettingField({schema, value, onChange}: {schema: FieldSchema; value: Value; onChange: (v: Value) => void}) {
  const type = schema.type || schema.anyOf?.find(t => t.type !== 'null')?.type;
  const nullable = schema.anyOf?.some(t => t.type === 'null');
  return <label>{schema.title}
    {schema.enum ? <select value={String(value)} onChange={e => onChange(e.target.value)}>{schema.enum.map(v => <option key={v}>{v}</option>)}</select> :
     type === 'boolean' ? <select value={String(value)} onChange={e => onChange(e.target.value === 'true')}><option value="true">Enabled</option><option value="false">Disabled</option></select> :
     <input type={type === 'array' ? 'text' : 'number'} step={type === 'integer' ? 1 : 'any'} min={schema.minimum} max={schema.maximum}
       required={!nullable} value={Array.isArray(value) ? value.join(',') : value == null ? '' : String(value)}
       onChange={e => onChange(type === 'array' ? e.target.value : e.target.value === '' && nullable ? null : Number(e.target.value))} />}
    <small>{schema.description}</small>
  </label>;
}
