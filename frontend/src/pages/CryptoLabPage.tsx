import { useEffect, useState } from "react";
import { API_URL } from "../lib/api";
import type { AnyObj } from "../lib/types";

const money = (n: unknown) => `$${Number(n || 0).toFixed(2)}`;
const pct = (n: unknown) => `${Number(n || 0).toFixed(2)}%`;

export function CryptoLabPage({ authToken }: { authToken: string }) {
  const [data, setData] = useState<AnyObj | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch(`${API_URL}/v18/crypto-shadow`, { headers: { "X-API-Key": authToken } });
        const body = await res.json();
        if (!res.ok) throw new Error(body?.detail || body?.message || `HTTP ${res.status}`);
        if (alive) { setData(body); setError(""); }
      } catch (e: any) { if (alive) setError(e?.message || "Crypto Shadow unavailable"); }
    };
    load(); const id = window.setInterval(load, 30000);
    return () => { alive = false; window.clearInterval(id); };
  }, [authToken]);
  if (!data) return <div className="card"><strong>Crypto Shadow Lab</strong><div className="muted">{error || "Loading 24/7 Alpaca crypto evidence…"}</div></div>;
  const scans = Array.isArray(data.scans) ? data.scans : [];
  const positions = Array.isArray(data.positions) ? data.positions : [];
  return <div className="page-stack">
    <section className="card hero-card">
      <div className="eyebrow">V18.2.32 · ALPACA CRYPTO SHADOW LAB</div>
      <h2>24/7 Crypto Research Engine</h2>
      <p className="muted">Completely isolated from live stock capital. It uses Alpaca crypto market data and virtual money only — no crypto broker orders can be submitted by this engine.</p>
      <div className="pill-row"><span className="pill good">SHADOW ONLY</span><span className="pill">24/7 MARKET</span><span className="pill">LIVE ORDERS OFF</span><span className="pill">{data.running ? "ENGINE RUNNING" : "ENGINE IDLE"}</span></div>
    </section>
    <section className="stats">
      <div className="stat"><span>Virtual Equity</span><strong>{money(data.equityUsd)}</strong><small>Started {money(data.virtualCapitalUsd)}</small></div>
      <div className="stat"><span>Total P&L</span><strong>{money(data.totalPnlUsd)}</strong><small>Realised {money(data.realisedPnlUsd)}</small></div>
      <div className="stat"><span>Shadow Positions</span><strong>{positions.length} / {data.config?.maxPositions}</strong><small>No real capital</small></div>
      <div className="stat"><span>Closed Tests</span><strong>{data.closedTrades || 0}</strong><small>Win rate {pct(data.winRate)}</small></div>
    </section>
    {positions.length > 0 && <section className="card"><h3>Open Shadow Position</h3>{positions.map((p: AnyObj) => <div className="list-row" key={p.symbol}><div><strong>{p.symbol}</strong><div className="muted">Entry {money(p.entry)} · Current {money(p.price)}</div></div><div><strong>{money(p.pnlUsd)}</strong><div className="muted">{pct(p.pnlPct)}</div></div></div>)}</section>}
    <section className="card"><div className="section-head"><div><h3>Crypto Scanner</h3><div className="muted">Independent crypto score — it does not reuse or alter stock entry gates.</div></div><span className="pill">Entry ≥ {Number(data.config?.entryScore || 0).toFixed(2)}</span></div>
      <div className="table-wrap"><table><thead><tr><th>Symbol</th><th>Price</th><th>Score</th><th>15m</th><th>60m</th><th>60m Range</th><th>Status</th></tr></thead><tbody>{scans.map((s: AnyObj) => <tr key={s.symbol}><td><strong>{s.symbol}</strong></td><td>{money(s.price)}</td><td>{Number(s.score || 0).toFixed(3)}</td><td>{pct(s.return15mPct)}</td><td>{pct(s.return60mPct)}</td><td>{pct(s.range60mPct)}</td><td>{s.qualified ? <span className="pill good">QUALIFIED</span> : <span className="pill">WATCHING</span>}</td></tr>)}</tbody></table></div>
      {error && <div className="muted">Last refresh warning: {error}</div>}
      {data.lastError && <div className="muted">Engine warning: {data.lastError}</div>}
    </section>
    <section className="card"><h3>Safety Boundary</h3><p className="muted">Virtual capital: {money(data.virtualCapitalUsd)} · Position size: {pct(Number(data.config?.positionPct || 0) * 100)} · Stop: {pct(data.config?.stopPct)} · Trail arms: {pct(data.config?.trailStartPct)} · Giveback: {pct(data.config?.trailGivebackPct)}. Profit Vault, £900 stock baseline, MARA rules and all live stock execution remain untouched.</p></section>
  </div>;
}
