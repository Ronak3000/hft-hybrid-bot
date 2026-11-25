'use client';
import {useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {createChart, AreaSeries,CandlestickSeries,LineSeries,ColorType,createSeriesMarkers,type Time} from 'lightweight-charts';
import {Activity,Database,History,Server,ShieldCheck,Terminal} from 'lucide-react';
import './classic-terminal.css';
import {API_BASE} from '@/lib/api';

type Point={gap_before?:boolean;time:number;open:number;high:number;low:number;close:number;pnl:number|null;inventory:number;fills:number;buys?:number;sells?:number;wins?:number;closed?:number;drawdown_usdt?:number};
type Model={id:string;environment:string;steps:number;training?:{end?:string}|string};
type Recording={id:string;family:string;label:string};
type Result={chart?:Point[];chart_source?:string;bucket_seconds?:number};
type Job={status:string;message:string;paused?:boolean;result?:Result;request?:{model_id:string}};
const SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT'];
async function api(path:string,init?:RequestInit){
  const res=await fetch(API_BASE+path,{cache:'no-store',...init});const value=await res.json();
  if(!res.ok)throw Error(typeof value.detail==='string'?value.detail:JSON.stringify(value.detail));return value;
}
function plot(el:HTMLDivElement,area:boolean){
  const chart=createChart(el,{autoSize:true,layout:{background:{type:ColorType.Solid,color:'#0D1117'},textColor:'#A1A1AA'},
    grid:{vertLines:{color:'#202c37'},horzLines:{color:'#202c37'}},timeScale:{timeVisible:true,secondsVisible:true}});
  const price=area?chart.addSeries(AreaSeries,{lineColor:'#3B82F6',topColor:'rgba(59,130,246,.4)',bottomColor:'rgba(59,130,246,0)',lineWidth:2}):chart.addSeries(CandlestickSeries,{upColor:'#10b981',downColor:'#ef4444',borderVisible:false,wickUpColor:'#10b981',wickDownColor:'#ef4444'});
  const pnl=chart.addSeries(LineSeries,{title:'Paper P&L · USDT',color:'#c5ef89',priceFormat:{type:'price',precision:5,minMove:.00001}},1);
  const markers=createSeriesMarkers(price,[]);
  return {chart,price,pnl,markers};
}
function Plot({points,area,lookback}:{points:Point[];area:boolean;lookback:number}){
  const host=useRef<HTMLDivElement>(null), instance=useRef<ReturnType<typeof plot>|null>(null), fitted=useRef(false);
  useEffect(()=>{if(!host.current)return;const p=plot(host.current,area);instance.current=p;return()=>{p.chart.remove();instance.current=null;fitted.current=false;};},[area]);
  useEffect(()=>{const p=instance.current;if(!p)return;
    p.price.setData(points.map(b=>({...b,value:b.close,time:b.time as Time})));
    p.pnl.setData(points.filter(b=>b.pnl!==null).map(b=>({time:b.time as Time,value:b.pnl!})));
    p.markers.setMarkers(points.flatMap<import('lightweight-charts').SeriesMarker<Time>>((b,i)=>{
      const prev=points[i-1];
      if(b.buys!==undefined&&b.sells!==undefined){
        const gap=b.gap_before?[{time:b.time as Time,position:'aboveBar' as const,color:'#fbbf24',shape:'circle' as const,text:'Data gap · reset'}]:[];
        const buy=b.buys-(prev?.buys??0),sell=b.sells-(prev?.sells??0);
        return [...gap,...(buy?[{time:b.time as Time,position:'belowBar' as const,color:'#10B981',shape:'arrowUp' as const,text:'B ×'+buy}]:[]),
                ...(sell?[{time:b.time as Time,position:'aboveBar' as const,color:'#EF4444',shape:'arrowDown' as const,text:'S ×'+sell}]:[])];
      }
      const n=b.fills-(points[i-1]?.fills??0);return n>0?[{time:b.time as Time,position:'aboveBar' as const,color:'#d3ec93',shape:'circle' as const,text:n+' fill'+(n>1?'s':'')}]:[];}));
    if(points.length&&!fitted.current){p.chart.timeScale().fitContent();fitted.current=true;}
  },[points,area]);
  const lastTime=points.at(-1)?.time;
  useEffect(()=>{const scale=instance.current?.chart.timeScale();if(lookback<0||!scale||lastTime===undefined)return;if(lookback)scale.setVisibleRange({from:(lastTime-lookback) as Time,to:lastTime as Time});else scale.fitContent();},[lookback,lastTime,area]);
  return <div ref={host} style={{height:420,width:'100%'}} aria-label="Market candlesticks and paper profit and loss chart"/>;
}
export function TraderDesk({live}:{live:boolean}){
  const mode=live?'live':'backtest',key='apex-candle-job-'+mode;
  const [symbol,setSymbol]=useState('BTCUSDT'),[restored,setRestored]=useState(false),[ready,setReady]=useState(false);
  const [area,setArea]=useState(false);
  const [lookback,setLookback]=useState(0);
  const [models,setModels]=useState<Model[]>([]),[model,setModel]=useState(''),[files,setFiles]=useState<Recording[]>([]),[file,setFile]=useState('');
  const [start,setStart]=useState('2024-01-01T01:00'),[end,setEnd]=useState('2024-01-01T02:00'),[seconds,setSeconds]=useState(180),[token,setToken]=useState('');
  const [id,setId]=useState(''),[job,setJob]=useState<Job|null>(null),[err,setErr]=useState(''),[sending,send]=useState(false);
  const [cursor,seek]=useState<number|null>(null),[playing,play]=useState(false);
  useEffect(()=>{
    const timer=setTimeout(()=>{
      const params=new URLSearchParams(location.search), saved=sessionStorage.getItem(key+'-symbol');
      const asset=params.get('symbol')||saved;
      if(asset&&SYMBOLS.includes(asset))setSymbol(asset);
      if(!params.has('model')&&(!asset||asset===saved))setId(sessionStorage.getItem(key)||'');
      setRestored(true);
    },0);
    return ()=>clearTimeout(timer);
  },[key]);
  function chooseModel(checkpoint:Model|undefined){
    setModel(checkpoint?.id||'');setFile('');
    const trained=checkpoint?.training;
    if(typeof trained!=='object'||!trained?.end)return;
    const after=Date.parse(trained.end), latest=Math.floor(Date.now()/60000)*60000;
    if(!Number.isFinite(after))return;
    setStart(new Date(after).toISOString().slice(0,16));
    setEnd(new Date(Math.max(after+120000,Math.min(latest,after+3600000))).toISOString().slice(0,16));
  }
  useEffect(()=>{if(!restored)return;let ok=true;Promise.all([api('/api/models/'+symbol),live?Promise.resolve([]):api('/api/backtest/recordings?symbol='+symbol)]).then(([m,f])=>{if(!ok)return;setReady(true);setModels(m.models);setFiles(f);const chosen=new URLSearchParams(location.search).get('model');chooseModel(m.models.find((x:Model)=>x.id===chosen)||m.models[0]);}).catch(e=>{if(ok){setReady(false);setErr(String(e));}});return()=>{ok=false;};},[live,symbol,restored]);
  useEffect(()=>{if(!id)return;let ok=true,t:ReturnType<typeof setTimeout>;
    async function poll(){try{const j=await api('/api/'+mode+'/status/'+id);if(!ok)return;setJob(j);if(j.status==='running')t=setTimeout(poll,900);}
      catch(e){if(ok){setErr(String(e));t=setTimeout(poll,4000);}}}void poll();return()=>{ok=false;clearTimeout(t);};},[id,mode]);
  const active=job?.status==='running',bars=job?.result?.chart, length=bars?.length||0;
  useEffect(()=>{if(!playing)return;const t=setInterval(()=>seek(i=>Math.min((i??0)+1,length-1)),180);return()=>clearInterval(t);},[playing,length]);
  const shown=bars?.slice(0,(cursor??length-1)+1)||[],last=shown.at(-1);
  const family=models.find(m=>m.id===model)?.environment==='ApexBinanceUSMinute-v1'?'candles':'l2';
  const choices=files.filter(f=>f.family===family);
  const selected=choices.find(f=>f.id===file)?.id||'range';
  async function command(path:string,body?:object){return api(path,{method:'POST',headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},...(body?{body:JSON.stringify(body)}:{})});}
  async function startJob(){send(true);setErr('');try{const r=await command('/api/'+mode+'/start',{model_id:model,symbol,...(live?{seconds}:selected==='range'?{start:start+'Z',end:end+'Z'}:{recording_id:selected})});sessionStorage.setItem(key,r.job_id);sessionStorage.setItem(key+'-symbol',symbol);setId(r.job_id);seek(null);play(false);setJob({status:'running',message:'Loading verified model and market data…'});}catch(e){setErr(String(e));}finally{send(false);}}
  async function control(stop:boolean){send(true);try{await command(stop?'/api/training/cancel/'+id:'/api/live/pause/'+id+'?paused='+!job?.paused);setJob(await api('/api/'+mode+'/status/'+id));}catch(e){setErr(String(e));}finally{send(false);}}
  return <div className={live?"classic-terminal":"classic-terminal historical-engine"}><header className="classic-head"><div><h1>{live?<Activity size={24}/>:<History size={24}/>}{live?'Live Execution Terminal':'Historical Backtest Engine'}</h1><p>{live?'Run a saved PPO policy on the live Binance market feed.':'Replay a saved PPO policy against recorded market data.'} Paper execution only.</p></div><strong className="classic-status"><Server size={16}/>{job?.paused?'TRADING PAUSED':active?'SESSION RUNNING':job?.status?.toUpperCase()||(ready?'READY':err?'BACKEND UNAVAILABLE':'CONNECTING')}</strong></header>
    <div className="classic-grid"><section className="classic-screen">
      {!live&&<div className="historical-stats">{[
        ['Net Profit',last?.pnl==null?'—':last.pnl.toFixed(5)+' USDT','Marked-to-market paper P&L'],
        ['Win Rate',last?.closed&&last.wins!==undefined?(100*last.wins/last.closed).toFixed(1)+'%':'—',last?.closed===0?'No closing fills':'Profitable FIFO closing fills / all closing fills, after fees'],
        ['Total Trades',last?.fills??'—','Simulated fills from this replay'],
        ['Max Drawdown',last?.drawdown_usdt==null?'—':last.drawdown_usdt.toFixed(5)+' USDT','Largest peak-to-trough loss at replay decisions']
      ].map(([label,value,hint])=><div key={label} title={String(hint)}><small>{label}</small><strong>{value}</strong>{label==='Win Rate'&&last?.closed===0&&<small>No closing fills</small>}</div>)}</div>}
      <div className="classic-ticker"><h2>{symbol.replace('USDT','/USDT')}</h2><small>{job?.result?.chart_source||'Market price'}</small><div className="classic-toggle"><button aria-pressed={area} onClick={()=>setArea(true)}>Area</button><button aria-pressed={!area} onClick={()=>setArea(false)}>Candles</button></div></div>
      {live&&<div className="trader-metrics">{[['Price · USDT',last?.close],['Paper P&L · USDT',last?.pnl],['Inventory · '+symbol.replace('USDT',''),last?.inventory],['Paper fills',last?.fills]].map(([k,v])=><div key={k}><small>{k}</small><strong>{typeof v==='number'?v.toLocaleString('en-US',{maximumFractionDigits:6}):'—'}</strong></div>)}</div>}
      {shown.length?<Plot points={shown} area={area} lookback={live?-1:lookback}/>:<div className="classic-empty"><Activity size={48}/><p>{active?'Waiting for market data…':'Awaiting simulator initialization…'}</p><small>Select a saved policy to start the {live?'live paper session':'historical replay'}.</small></div>}
      <div className="classic-log" role="region" aria-label="Execution terminal"><b><Terminal size={15}/> Execution terminal · UTC</b><p>{job?.message||'Simulator disconnected.'}</p>
        {shown.slice(-20).reverse().map((b,i)=>{
          const previous=shown[shown.length-i-2];
          const buys=(b.buys??0)-(previous?.buys??0), sells=(b.sells??0)-(previous?.sells??0);
          return <p key={b.time}>[{new Date(b.time*1000).toISOString().slice(11,19)}] {symbol} {b.close.toFixed(2)} · {buys>0?`BUY ×${buys} · `:''}{sells>0?`SELL ×${sells} · `:''}{b.pnl===null?'Market history':`P&L ${b.pnl.toFixed(5)} · Inventory ${b.inventory} · Fills ${b.fills}`}</p>;
        })}</div>
      {!live&&length>1&&<div className="policy-fields"><button onClick={()=>{if(!playing||cursor===length-1){if(cursor===null||cursor===length-1)seek(0);play(true);}else play(false);}}>{playing&&cursor!==length-1?'Pause playback':'▶ Play replay'}</button><input aria-label="Replay position" type="range" min={0} max={length-1} value={cursor??length-1} onChange={e=>{play(false);seek(+e.target.value);}}/></div>}
    </section><aside className="classic-rail"><section className="classic-card policy-form"><h2><Database size={16}/>{live?'Strategy Deployment':'Strategy Parameters'}</h2><label>Target asset<select disabled={active} value={symbol} onChange={e=>{setSymbol(e.target.value);setModels([]);setModel('');setFiles([]);setFile('');setJob(null);setId('');sessionStorage.removeItem(key);}}>{['BTCUSDT','ETHUSDT','SOLUSDT'].map(s=><option key={s}>{s}</option>)}</select></label>
      {!live&&<label>Chart lookback<select value={lookback} onChange={e=>setLookback(+e.target.value)}><option value={0}>Full recording</option><option value={1800}>30 Minutes (30m)</option><option value={7200}>2 Hours (2h)</option><option value={14400}>4 Hours (4h)</option></select></label>}
      <label>Saved PPO model<select value={model} disabled={active} onChange={e=>chooseModel(models.find(m=>m.id===e.target.value))}>{!models.length&&<option value="">No verified checkpoints</option>}{models.map(m=><option key={m.id} value={m.id}>{m.environment==='ApexBinanceUSMinute-v1'?'Candles':'L2'} · {m.id} · {m.steps} steps</option>)}</select></label>
      {!live?<><label>Market recording<select disabled={active} value={selected} onChange={e=>setFile(e.target.value)}>{choices.map(f=><option value={f.id} key={f.id}>{f.label}</option>)}<option value="range">Download date range</option></select></label>{selected==='range'&&<><label>Start UTC<input type="datetime-local" value={start} onChange={e=>setStart(e.target.value)}/></label><label>End UTC (exclusive)<input type="datetime-local" value={end} onChange={e=>setEnd(e.target.value)}/></label></>}<small>Choose real Binance.US candles later than training. Missing minutes start a new paper episode.</small></>:<><label>Session seconds<input type="number" min={10} max={300} value={seconds} onChange={e=>setSeconds(+e.target.value)}/></label><small>Pause stops new paper trades at the next decision; the feed and inventory valuation continue. The session timer keeps running.</small></>}
      <details><summary>Hosted operator access</summary><label>Operator token<input type="password" value={token} onChange={e=>setToken(e.target.value)}/></label></details>
      <button className="button-accent" disabled={!model||sending||active} onClick={startJob}>{live?'▶ Start live trader':active?'Simulating…':'▶ Run Simulation'}</button>
      {active&&live&&<button className="button-outline" disabled={sending} onClick={()=>control(false)}>{job?.paused?'▶ Resume trading':'Ⅱ Pause trading'}</button>}
      {active&&<button disabled={sending} onClick={()=>control(true)}>Stop session</button>}{!models.length&&<small>No saved model for {symbol}. <Link href="/train">Train one first ↗</Link></small>}{err&&<p role="alert">{err}</p>}
    </section>{live&&<section className="classic-card"><h2><ShieldCheck size={16}/> Simulation rules</h2><p>Execution: <strong>Paper only</strong></p><p>Exchange orders: <strong>Disabled</strong></p><Link href="/train">Train a new policy ↗</Link></section>}</aside></div></div>;
}
