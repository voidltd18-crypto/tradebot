import React, { useEffect, useState } from 'react';
import { Activity, RefreshCw, Server, Clock, Zap } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://tradebot-0myo.onrender.com';

type AnyObj = Record<string, any>;

async function getJson(path: string, options?: RequestInit): Promise<AnyObj> {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

export default function App() {
  const [status, setStatus] = useState<AnyObj | null>(null);
  const [market, setMarket] = useState<AnyObj | null>(null);
  const [realtime, setRealtime] = useState<AnyObj | null>(null);
  const [scan, setScan] = useState<AnyObj | null>(null);
  const [universe, setUniverse] = useState<AnyObj | null>(null);
  const [error, setError] = useState<string>('');
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    setError('');
    try {
      const [s, m, r, u] = await Promise.all([
        getJson('/status'),
        getJson('/market-status'),
        getJson('/realtime-status'),
        getJson('/weekly-universe'),
      ]);
      setStatus(s);
      setMarket(m);
      setRealtime(r);
      setUniverse(u);
      if (r?.last_result) setScan(r.last_result);
    } catch (e: any) {
      setError(e?.message || 'Could not connect to backend');
    } finally {
      setLoading(false);
    }
  }

  async function runScan() {
    setLoading(true);
    setError('');
    try {
      const result = await getJson('/scan', { method: 'POST' });
      setScan(result);
      await refresh();
    } catch (e: any) {
      setError(e?.message || 'Scan failed');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, []);

  const top = scan?.top || realtime?.last_result?.top || [];

  return (
    <main className="page">
      <section className="hero">
        <div>
          <h1>Tradebot Dashboard</h1>
          <p>Clean rebuild package • Backend: {API_BASE}</p>
        </div>
        <button onClick={refresh} disabled={loading}><RefreshCw size={18}/> Refresh</button>
      </section>

      {error && <div className="error">{error}</div>}

      <section className="grid">
        <Card icon={<Server/>} title="Backend">
          <b>{status?.backend || 'checking...'}</b>
          <span>Uptime: {status?.uptime_seconds ?? '-'}s</span>
          <span>Alpaca configured: {status?.alpaca_configured ? 'YES' : 'NO'}</span>
        </Card>

        <Card icon={<Activity/>} title="Market Status">
          <b className={market?.is_open ? 'open' : 'closed'}>{market?.status || 'checking...'}</b>
          <span>Source: {market?.source || '-'}</span>
          <span>{market?.error || market?.timestamp || ''}</span>
        </Card>

        <Card icon={<Zap/>} title="Real-Time Mode">
          <b>{realtime?.running ? 'ON • Background running' : 'OFF'}</b>
          <span>Scan age: {realtime?.last_scan_age_seconds ?? '-'}s</span>
          <span>Scans: {realtime?.scan_count ?? 0}</span>
        </Card>

        <Card icon={<Clock/>} title="Weekly Universe">
          <b>{universe?.universe?.length || 0} symbols</b>
          <span>{(universe?.universe || []).join(', ')}</span>
        </Card>
      </section>

      <section className="panel">
        <div className="panelHead">
          <h2>Live Scan</h2>
          <button onClick={runScan} disabled={loading}><Zap size={18}/> Run Scan</button>
        </div>
        <p>{scan?.message || 'Waiting for first scan...'}</p>
        <div className="table">
          <div className="row head"><span>Symbol</span><span>Price</span><span>Quality</span><span>Confidence</span><span>Action</span></div>
          {top.map((x: AnyObj) => (
            <div className="row" key={x.symbol}>
              <span>{x.symbol}</span><span>{x.price ?? '-'}</span><span>{x.quality}</span><span>{x.confidence}</span><span>{x.action}</span>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

function Card({icon, title, children}: {icon: React.ReactNode; title: string; children: React.ReactNode}) {
  return <section className="card"><div className="cardTitle">{icon}<span>{title}</span></div><div className="cardBody">{children}</div></section>
}
