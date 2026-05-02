import React, {useEffect, useState} from 'react';
import { createRoot } from 'react-dom/client';

const API = import.meta.env.VITE_API_URL || '';
const KEY = import.meta.env.VITE_DASHBOARD_API_KEY || '';

function App(){
  const [status,setStatus]=useState(null);
  const [msg,setMsg]=useState('');
  async function load(){
    const r=await fetch(`${API}/status`); setStatus(await r.json());
  }
  async function post(path){
    const r=await fetch(`${API}${path}`,{method:'POST',headers: KEY?{'x-api-key':KEY}:{}});
    const j=await r.json(); setMsg(j.message || JSON.stringify(j)); load();
  }
  useEffect(()=>{load(); const t=setInterval(load,5000); return()=>clearInterval(t)},[]);
  const engines=status?.engines||{};
  return <div style={{fontFamily:'Arial',padding:20,background:'#0b1020',color:'#eef',minHeight:'100vh'}}>
    <h1>Merged Tradebot Platform</h1>
    <p>Dry Run: <b>{String(status?.dryRun)}</b></p>
    <button onClick={()=>post('/start-all')}>Start All</button> <button onClick={()=>post('/pause-all')}>Pause All</button>
    <p>{msg}</p>
    <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(320px,1fr))',gap:16}}>
      {Object.entries(engines).map(([name,e])=><div key={name} style={{background:'#151b33',borderRadius:16,padding:16}}>
        <h2>{name.toUpperCase()}</h2>
        <p>Running: {String(e.running)} | Paused: {String(e.paused)} | Enabled: {String(e.enabled)}</p>
        <p>Last: {e.last_action}</p>
        <p style={{color:'#ff8'}}>{e.last_error}</p>
        <button onClick={()=>post(`/engines/${name}/start`)}>Start</button> <button onClick={()=>post(`/engines/${name}/pause`)}>Pause</button>
        <h3>Positions</h3>
        {(e.positions||[]).slice(0,8).map(p=><div key={p.symbol}>{p.symbol} | {Number(p.pnlPct||0).toFixed(2)}%</div>)}
        <h3>Logs</h3>
        <pre style={{whiteSpace:'pre-wrap',fontSize:12}}>{(e.logs||[]).slice(-8).join('\n')}</pre>
      </div>)}
    </div>
  </div>
}

createRoot(document.getElementById('root')).render(<App/>);
