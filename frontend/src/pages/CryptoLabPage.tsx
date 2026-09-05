import { useEffect, useState } from "react";
import { API_URL } from "../lib/api";
import type { AnyObj } from "../lib/types";

const money = (n: unknown) => `$${Number(n || 0).toFixed(2)}`;
const pct = (n: unknown) => `${Number(n || 0).toFixed(2)}%`;

export function CryptoLabPage({ authToken }: { authToken: string }) {
  const [data, setData] = useState<AnyObj | null>(null);
  const [error, setError] = useState("");
  const [bridge, setBridge] = useState<AnyObj | null>(null);
  const [releaseAmount, setReleaseAmount] = useState("25");
  const [bridgeMessage, setBridgeMessage] = useState("");
  const [bridgeBusy, setBridgeBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch(`${API_URL}/v18/crypto-shadow`, { headers: { "X-API-Key": authToken } });
        const body = await res.json();
        if (!res.ok) throw new Error(body?.detail || body?.message || `HTTP ${res.status}`);
        const bridgeRes = await fetch(`${API_URL}/v18/crypto-bridge`, { headers: { "X-API-Key": authToken } });
        const bridgeBody = await bridgeRes.json();
        if (alive) { setData(body); setBridge(bridgeRes.ok ? bridgeBody : null); setError(""); }
      } catch (e: any) { if (alive) setError(e?.message || "Crypto Shadow unavailable"); }
    };
    load(); const id = window.setInterval(load, 30000);
    return () => { alive = false; window.clearInterval(id); };
  }, [authToken]);

  const releaseVault = async () => {
    if (!bridge || bridge.locked) return;
    const amount = Number(releaseAmount || 0);
    if (!Number.isFinite(amount) || amount <= 0) { setBridgeMessage("Enter a valid amount."); return; }
    if (!window.confirm(`Release £${amount.toFixed(2)} from the protected Profit Vault to Crypto?\n\nThis is a manual capital decision and cannot be performed by the AI.`)) return;
    setBridgeBusy(true); setBridgeMessage("");
    try {
      const res = await fetch(`${API_URL}/v18/crypto-bridge/release`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": authToken, "x-api-key": authToken },
        body: JSON.stringify({ amountGbp: amount, confirmation: "UNLOCK CRYPTO" }),
      });
      const body = await res.json();
      if (!res.ok || body?.ok === false) throw new Error(body?.message || body?.detail || `HTTP ${res.status}`);
      setBridge(body.bridge || bridge); setBridgeMessage(body.message || "Vault allocation updated.");
    } catch (e: any) { setBridgeMessage(e?.message || "Vault release failed."); }
    finally { setBridgeBusy(false); }
  };

  if (!data) return <div className="card"><strong>Crypto Shadow Lab</strong><div className="muted">{error || "Loading 24/7 Alpaca crypto evidence…"}</div></div>;
  const scans = Array.isArray(data.scans) ? data.scans : [];
  const positions = Array.isArray(data.positions) ? data.positions : [];
  return <div className="page-stack">
    <section className="card hero-card">
      <div className="eyebrow">V18.2.34 · VAULT-FUNDED LIVE CRYPTO PILOT</div>
      <h2>24/7 Crypto Research Engine</h2>
      <p className="muted">Shadow research stays active 24/7. Live crypto is a separate, manually funded pilot using only the amount you release from the Profit Vault.</p>
      <div className="pill-row"><span className="pill good">SHADOW RESEARCH ON</span><span className="pill">24/7 MARKET</span><span className="pill">LIVE PILOT AVAILABLE</span><span className="pill">{data.running ? "ENGINE RUNNING" : "ENGINE IDLE"}</span></div>
    </section>
    <section className="stats">
      <div className="stat"><span>Virtual Equity</span><strong>{money(data.equityUsd)}</strong><small>Started {money(data.virtualCapitalUsd)}</small></div>
      <div className="stat"><span>Total P&L</span><strong>{money(data.totalPnlUsd)}</strong><small>Realised {money(data.realisedPnlUsd)}</small></div>
      <div className="stat"><span>Shadow Positions</span><strong>{positions.length} / {data.config?.maxPositions}</strong><small>No real capital</small></div>
      <div className="stat"><span>Closed Tests</span><strong>{data.closedTrades || 0}</strong><small>Win rate {pct(data.winRate)}</small></div>
    </section>
    {bridge && <section className="card"><div className="section-head"><div><div className="eyebrow">REAL MONEY PILOT</div><h3>Live Crypto Status</h3></div><span className={`pill ${bridge.accountCrypto?.active ? "good" : ""}`}>{bridge.accountCrypto?.status || "UNKNOWN"}</span></div><div className="stats" style={{marginTop:14}}><div className="stat"><span>Pilot</span><strong>{bridge.livePilotEnabled ? "ARMED" : "OFF"}</strong><small>Manual Vault permission</small></div><div className="stat"><span>Allocated</span><strong>£{Number(bridge.cryptoAllocatedGbp || 0).toFixed(2)}</strong><small>Max £{Number(bridge.pilotMaxGbp || 25).toFixed(2)}</small></div><div className="stat"><span>Crypto P&L</span><strong>£{Number(bridge.cryptoRealisedPnlGbp || 0).toFixed(2)}</strong><small>Realised live pilot</small></div><div className="stat"><span>Profit Returned</span><strong>£{Number(bridge.cryptoLifetimeProfitBankedGbp || 0).toFixed(2)}</strong><small>Swept back to Vault</small></div></div>{Array.isArray(bridge.livePositions) && bridge.livePositions.length>0 && bridge.livePositions.map((p:AnyObj)=><div className="list-row" key={p.symbol}><div><strong>{p.symbol}</strong><div className="muted">LIVE · Entry {money(p.entry)}</div></div><div><strong>{money(p.marketValueUsd)}</strong><div className="muted">Qty {Number(p.qty||0).toFixed(8)}</div></div></div>)}</section>}
    {positions.length > 0 && <section className="card"><h3>Open Shadow Position</h3>{positions.map((p: AnyObj) => <div className="list-row" key={p.symbol}><div><strong>{p.symbol}</strong><div className="muted">Entry {money(p.entry)} · Current {money(p.price)}</div></div><div><strong>{money(p.pnlUsd)}</strong><div className="muted">{pct(p.pnlPct)}</div></div></div>)}</section>}
    <section className="card"><div className="section-head"><div><h3>Crypto Scanner</h3><div className="muted">Independent crypto score — it does not reuse or alter stock entry gates.</div></div><span className="pill">Entry ≥ {Number(data.config?.entryScore || 0).toFixed(2)}</span></div>
      <div className="table-wrap"><table><thead><tr><th>Symbol</th><th>Price</th><th>Score</th><th>15m</th><th>60m</th><th>60m Range</th><th>Status</th></tr></thead><tbody>{scans.map((s: AnyObj) => <tr key={s.symbol}><td><strong>{s.symbol}</strong></td><td>{money(s.price)}</td><td>{Number(s.score || 0).toFixed(3)}</td><td>{pct(s.return15mPct)}</td><td>{pct(s.return60mPct)}</td><td>{pct(s.range60mPct)}</td><td>{s.qualified ? <span className="pill good">QUALIFIED</span> : <span className="pill">WATCHING</span>}</td></tr>)}</tbody></table></div>
      {error && <div className="muted">Last refresh warning: {error}</div>}
      {data.lastError && <div className="muted">Engine warning: {data.lastError}</div>}
    </section>
    <section className="card">
      <div className="section-head"><div><div className="eyebrow">MANUAL CAPITAL BRIDGE</div><h3>Profit Vault → Crypto</h3><div className="muted">Stocks earn the profit. The Vault protects it. Only you can release a chosen amount to Crypto.</div></div><span className={`pill ${bridge?.locked ? "" : "good"}`}>{bridge?.locked ? "ALPACA CRYPTO NOT ACTIVE" : bridge?.livePilotEnabled ? "LIVE PILOT ARMED" : "READY TO ARM"}</span></div>
      <div className="stats" style={{marginTop: 14}}>
        <div className="stat"><span>Vault Available</span><strong>£{Number(bridge?.vaultAvailableGbp || 0).toFixed(2)}</strong><small>Still protected</small></div>
        <div className="stat"><span>Crypto Allocation</span><strong>£{Number(bridge?.cryptoAllocatedGbp || 0).toFixed(2)}</strong><small>Reserved from stock engine</small></div>
        <div className="stat"><span>Live Pilot Cap</span><strong>£{Number(bridge?.pilotMaxGbp || 25).toFixed(2)}</strong><small>Hard maximum · no auto-refill</small></div>
        <div className="stat"><span>Shadow Evidence</span><strong>{Number(bridge?.shadowEvidence?.closedTests || 0)} tests</strong><small>{money(bridge?.shadowEvidence?.totalPnlUsd)} · win rate {pct(bridge?.shadowEvidence?.winRate)}</small></div>
      </div>
      <div className="actions" style={{alignItems: "center"}}>
        <input aria-label="Crypto release amount in pounds" type="number" min="1" step="1" value={releaseAmount} onChange={e => setReleaseAmount(e.target.value)} style={{width: 130}} />
        <button onClick={releaseVault} disabled={bridgeBusy || !bridge || bridge.locked}>{bridgeBusy ? "ARMING…" : `UNLOCK £${Number(releaseAmount || 0).toFixed(2)} & START LIVE PILOT`}</button>
      </div>
      <div className="muted" style={{marginTop: 10}}>{bridge?.message || "Manual approval only. Live crypto cannot draw from stock capital or auto-refill from the Vault."}</div>
      {bridgeMessage && <div className="notice" style={{marginTop: 10}}>{bridgeMessage}</div>}
    </section>
    <section className="card"><h3>Safety Boundary</h3><p className="muted">Virtual capital: {money(data.virtualCapitalUsd)} · Position size: {pct(Number(data.config?.positionPct || 0) * 100)} · Stop: {pct(data.config?.stopPct)} · Trail arms: {pct(data.config?.trailStartPct)} · Giveback: {pct(data.config?.trailGivebackPct)}. Profit Vault, £900 stock baseline, MARA rules and all live stock execution remain untouched.</p></section>
  </div>;
}
