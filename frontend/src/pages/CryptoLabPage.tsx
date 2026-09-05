import { useEffect, useMemo, useState } from "react";
import { API_URL } from "../lib/api";
import type { AnyObj } from "../lib/types";

const money = (n: unknown) => `$${Number(n || 0).toFixed(2)}`;
const pct = (n: unknown) => `${Number(n || 0).toFixed(2)}%`;
const gbp = (n: unknown) => `£${Number(n || 0).toFixed(2)}`;

function coinGlyph(symbol: string) {
  const s = String(symbol || "").split("/")[0].toUpperCase();
  if (s === "BTC") return "₿";
  if (s === "ETH") return "◆";
  if (s === "LTC") return "Ł";
  if (s === "SOL") return "≋";
  if (s === "XRP") return "✕";
  if (s === "DOGE") return "Ð";
  if (s === "LINK") return "⬡";
  if (s === "AVAX") return "▲";
  return "◈";
}

function scoreState(score: number, threshold: number) {
  if (score >= threshold) return { label: "QUALIFIED", cls: "qualified" };
  if (score >= Math.max(0.60, threshold - 0.08)) return { label: "NEAR ENTRY", cls: "near" };
  if (score >= 0.50) return { label: "BUILDING", cls: "building" };
  return { label: "WATCHING", cls: "watching" };
}

export function CryptoLabPage({ authToken }: { authToken: string }) {
  const [data, setData] = useState<AnyObj | null>(null);
  const [error, setError] = useState("");
  const [bridge, setBridge] = useState<AnyObj | null>(null);
  const [releaseAmount, setReleaseAmount] = useState("25");
  const [bridgeMessage, setBridgeMessage] = useState("");
  const [bridgeBusy, setBridgeBusy] = useState(false);
  const [sellBusySymbol, setSellBusySymbol] = useState("");
  const [sellMessage, setSellMessage] = useState("");

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch(`${API_URL}/v18/crypto-shadow`, { headers: { "X-API-Key": authToken } });
        const body = await res.json();
        if (!res.ok) throw new Error(body?.detail || body?.message || `HTTP ${res.status}`);
        const bridgeRes = await fetch(`${API_URL}/v18/crypto-bridge`, { headers: { "X-API-Key": authToken } });
        const bridgeBody = await bridgeRes.json();
        if (alive) {
          setData(body);
          setBridge(bridgeRes.ok ? bridgeBody : null);
          setError("");
        }
      } catch (e: any) {
        if (alive) setError(e?.message || "Crypto Lab unavailable");
      }
    };
    load();
    const id = window.setInterval(load, 30000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [authToken]);

  const releaseVault = async () => {
    if (!bridge || bridge.locked || bridge.livePilotEnabled) return;
    const amount = Number(releaseAmount || 0);
    if (!Number.isFinite(amount) || amount <= 0) {
      setBridgeMessage("Enter a valid amount.");
      return;
    }
    if (!window.confirm(`Release £${amount.toFixed(2)} from the protected Profit Vault to Crypto?\n\nThis is a manual capital decision and cannot be performed by the AI.`)) return;
    setBridgeBusy(true);
    setBridgeMessage("");
    try {
      const res = await fetch(`${API_URL}/v18/crypto-bridge/release`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Auth-Token": authToken, "x-api-key": authToken },
        body: JSON.stringify({ amountGbp: amount, confirmation: "UNLOCK CRYPTO" }),
      });
      const body = await res.json();
      if (!res.ok || body?.ok === false) throw new Error(body?.message || body?.detail || `HTTP ${res.status}`);
      setBridge(body.bridge || bridge);
      setBridgeMessage(body.message || "Vault allocation updated.");
    } catch (e: any) {
      setBridgeMessage(e?.message || "Vault release failed.");
    } finally {
      setBridgeBusy(false);
    }
  };

  const manualSellCrypto = async (position: AnyObj) => {
    const symbol = String(position?.symbol || "").toUpperCase();
    if (!symbol || sellBusySymbol) return;
    const managed = Boolean(position?.managedByPilot);
    const ownershipText = managed ? "TradeBot live-pilot" : "manual/external Alpaca";
    if (!window.confirm(`SELL 100% of ${symbol} now?\n\nThis will submit a real market sell for the ${ownershipText} position.`)) return;
    setSellBusySymbol(symbol);
    setSellMessage("");
    try {
      const res = await fetch(`${API_URL}/v18/crypto-bridge/manual-sell`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Auth-Token": authToken, "x-api-key": authToken },
        body: JSON.stringify({ symbol, confirmation: "SELL CRYPTO NOW" }),
      });
      const body = await res.json();
      if (!res.ok || body?.ok === false) throw new Error(body?.message || body?.detail || `HTTP ${res.status}`);
      if (body?.bridge) setBridge(body.bridge);
      setSellMessage(body?.message || `Manual sell submitted for ${symbol}.`);
    } catch (e: any) {
      setSellMessage(e?.message || `Manual sell failed for ${symbol}.`);
    } finally {
      setSellBusySymbol("");
    }
  };

  const scans = useMemo(() => {
    const rows = Array.isArray(data?.scans) ? [...data.scans] : [];
    return rows.sort((a: AnyObj, b: AnyObj) => Number(b?.score || 0) - Number(a?.score || 0));
  }, [data]);

  if (!data) {
    return <div className="card crypto-loading"><strong>Crypto Lab</strong><div className="muted">{error || "Loading 24/7 Alpaca crypto evidence…"}</div></div>;
  }

  const positions = Array.isArray(data.positions) ? data.positions : [];
  const livePositions = Array.isArray(bridge?.livePositions) ? bridge.livePositions : [];
  const entryScore = Number(data.config?.entryScore || 0.68);
  const armed = Boolean(bridge?.livePilotEnabled);
  const accountActive = Boolean(bridge?.accountCrypto?.active);

  return <div className="crypto-lab-page">
    <section className="crypto-hero">
      <div className="crypto-hero-main">
        <div className="crypto-hero-icon">₿</div>
        <div>
          <div className="eyebrow">V18.2.37 · MANUAL CRYPTO SELL</div>
          <h2>Crypto Lab</h2>
          <p>Live crypto trading pilot — real capital, real trades, real results.</p>
        </div>
      </div>
      <div className={`crypto-live-badge ${armed ? "armed" : "idle"}`}><span>●</span>{armed ? "LIVE PILOT ARMED" : "LIVE PILOT OFF"}</div>
    </section>

    <section className="crypto-summary-grid">
      <div className="crypto-summary-card"><div className="crypto-summary-icon vault">▣</div><div><span>Vault Available</span><strong>{gbp(bridge?.vaultAvailableGbp)}</strong><small>Protected capital</small></div></div>
      <div className="crypto-summary-card"><div className="crypto-summary-icon allocation">●</div><div><span>Crypto Allocation</span><strong>{gbp(bridge?.cryptoAllocatedGbp)}</strong><small>Live pilot cap</small></div></div>
      <div className="crypto-summary-card"><div className="crypto-summary-icon pnl">↗</div><div><span>Crypto P&amp;L</span><strong className={Number(bridge?.cryptoRealisedPnlGbp || 0) >= 0 ? "gain" : "loss"}>{gbp(bridge?.cryptoRealisedPnlGbp)}</strong><small>Realised live pilot</small></div></div>
      <div className="crypto-summary-card"><div className="crypto-summary-icon returned">↻</div><div><span>Profit Returned</span><strong>{gbp(bridge?.cryptoLifetimeProfitBankedGbp)}</strong><small>Swept back to Vault</small></div></div>
    </section>

    {livePositions.length > 0 && <section className="crypto-panel crypto-live-positions">
      <div className="crypto-panel-head">
        <div><h3>Live Crypto Position</h3><p>Real Alpaca crypto position currently managed by the pilot.</p></div>
        <span className="crypto-chip live">LIVE</span>
      </div>
      <div className="crypto-position-grid">
        {livePositions.map((p: AnyObj) => {
          const pnl = Number(p.pnlGbp ?? p.pnlUsd ?? 0);
          const pnlPct = Number(p.pnlPct || 0);
          const managed = Boolean(p.managedByPilot);
          return <div className="crypto-position-card" key={p.symbol}>
            <div className="crypto-position-symbol"><span className="coin-icon">{coinGlyph(p.symbol)}</span><div><strong>{p.symbol}</strong><small>Entry {money(p.entry)} · {managed ? "BOT MANAGED" : "MANUAL / EXTERNAL"}</small></div></div>
            <div className="crypto-position-metric"><span>Market Value</span><strong>{money(p.marketValueUsd)}</strong><small>Qty {Number(p.qty || 0).toFixed(8)}</small></div>
            <div className={`crypto-position-metric ${pnl >= 0 ? "gain" : "loss"}`}><span>P&amp;L</span><strong>{gbp(pnl)}</strong><small>{pct(pnlPct)}</small></div>
            <div className="crypto-position-actions"><button className="crypto-sell-now" onClick={() => manualSellCrypto(p)} disabled={Boolean(sellBusySymbol)}>{sellBusySymbol === p.symbol ? "SELLING…" : "SELL CRYPTO NOW"}</button><small>100% market sell · confirmation required</small></div>
          </div>;
        })}
      </div>
      {sellMessage && <div className="crypto-notice crypto-sell-notice">{sellMessage}</div>}
    </section>}

    <section className="crypto-panel crypto-scanner-panel">
      <div className="crypto-panel-head">
        <div>
          <h3><span className="panel-icon">◈</span> Crypto Scanner</h3>
          <p>AI scans the market and ranks opportunities. Trades only when score ≥ {entryScore.toFixed(2)}.</p>
        </div>
        <div className="scanner-state"><span className="crypto-chip">{scans.length} assets</span><span className="scanning-dot">●</span><span>Scanning</span></div>
      </div>
      <div className="crypto-table-wrap">
        <table className="crypto-scanner-table">
          <thead><tr><th>Symbol</th><th>Price</th><th>Score</th><th>15m</th><th>60m</th><th>60m Range</th><th>Status</th></tr></thead>
          <tbody>{scans.map((s: AnyObj) => {
            const score = Number(s.score || 0);
            const state = scoreState(score, entryScore);
            const progress = Math.max(4, Math.min(100, (score / entryScore) * 100));
            return <tr key={s.symbol} className={s.qualified ? "qualified-row" : ""}>
              <td><div className="crypto-symbol"><span className="coin-icon small">{coinGlyph(s.symbol)}</span><strong>{s.symbol}</strong></div></td>
              <td>{money(s.price)}</td>
              <td><span className={`score-badge ${state.cls}`}>{score.toFixed(3)}</span></td>
              <td className={Number(s.return15mPct || 0) >= 0 ? "gain" : "loss"}>{pct(s.return15mPct)}</td>
              <td className={Number(s.return60mPct || 0) >= 0 ? "gain" : "loss"}>{pct(s.return60mPct)}</td>
              <td>{pct(s.range60mPct)}</td>
              <td><div className="crypto-status-cell"><span className={`crypto-chip ${state.cls}`}>{state.label}</span><span className="score-track"><span style={{ width: `${progress}%` }} /></span></div></td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      {error && <div className="crypto-warning">Last refresh warning: {error}</div>}
      {data.lastError && <div className="crypto-warning">Engine warning: {data.lastError}</div>}
    </section>

    <section className="crypto-panel crypto-bridge-panel">
      <div className="crypto-panel-head">
        <div>
          <h3><span className="panel-icon">⌒</span> Crypto Bridge</h3>
          <p>Manually release funds to the live crypto pilot. Maximum {gbp(bridge?.pilotMaxGbp || 25)}.</p>
        </div>
        <span className={`crypto-chip ${armed ? "live" : accountActive ? "building" : ""}`}>{armed ? "LIVE PILOT ARMED" : accountActive ? "READY TO ARM" : "CRYPTO NOT ACTIVE"}</span>
      </div>

      <div className="crypto-bridge-grid">
        <div className="bridge-metric"><span className="crypto-summary-icon vault">▣</span><div><small>Vault Available</small><strong>{gbp(bridge?.vaultAvailableGbp)}</strong></div></div>
        <div className="bridge-metric"><span className="crypto-summary-icon allocation">●</span><div><small>Crypto Allocation</small><strong>{gbp(bridge?.cryptoAllocatedGbp)}</strong></div></div>
        <div className="bridge-metric"><span className="crypto-summary-icon pnl">◇</span><div><small>Live Pilot Cap</small><strong>{gbp(bridge?.pilotMaxGbp || 25)}</strong></div></div>
        <div className="bridge-metric"><span className="crypto-summary-icon returned">◎</span><div><small>Status</small><strong className={armed ? "gain" : ""}>{armed ? "● Armed" : "Off"}</strong></div></div>
        <div className={`bridge-action ${armed ? "allocated" : ""}`}>
          {armed ? <><strong>🔒 {gbp(bridge?.cryptoAllocatedGbp)} ALLOCATED</strong><small>Live pilot armed — waiting for signal</small></> : <>
            <div className="bridge-release-controls"><input aria-label="Crypto release amount in pounds" type="number" min="1" max={Number(bridge?.pilotMaxGbp || 25)} step="1" value={releaseAmount} onChange={e => setReleaseAmount(e.target.value)} /><button onClick={releaseVault} disabled={bridgeBusy || !bridge || bridge.locked}>{bridgeBusy ? "ARMING…" : `UNLOCK ${gbp(releaseAmount)} & START`}</button></div>
            <small>Manual approval only · no auto-refill</small>
          </>}
        </div>
      </div>
      {bridgeMessage && <div className="crypto-notice">{bridgeMessage}</div>}
    </section>

    <section className="crypto-footer-strip">
      <span><b>Shadow:</b> {Number(bridge?.shadowEvidence?.closedTests || data.closedTrades || 0)} tests · {money(bridge?.shadowEvidence?.totalPnlUsd ?? data.totalPnlUsd)} · win {pct(bridge?.shadowEvidence?.winRate ?? data.winRate)}</span>
      <span><b>Safety:</b> Stop {pct(data.config?.stopPct)} · Trail {pct(data.config?.trailStartPct)} / {pct(data.config?.trailGivebackPct)}</span>
      <span><b>Stock engine:</b> £900 baseline and MARA rules untouched</span>
    </section>
  </div>;
}
