import { SmartRebuyPanel } from "../components/SmartRebuyPanel";
import { Card } from "../components/Card";
import { useState } from "react";

type ScanDecision = {
  symbol: string;
  decision?: string;
  stage?: string;
  reason?: string;
  confidence?: number;
  quality?: number;
};

type StockScan = {
  startedAt: string;
  completedAt: string;
  attemptedCount: number;
  scannedCount: number;
  evaluationComplete: boolean;
  rows: ScanDecision[];
};

function EntryGateDiagnostics({ symbols, scan, marketOpen }: {
  symbols: string[]; scan?: StockScan | null; marketOpen: boolean;
}) {
  const [showAll, setShowAll] = useState(false);
  const age = scan ? Date.now() - Date.parse(scan.startedAt) : Infinity;
  const current = marketOpen && scan?.evaluationComplete === true && age >= 0 && age <= 5 * 60 * 1000;
  const opportunity = (row: ScanDecision) => {
    if (!current) return "RED";
    if (row.decision === "APPROVED" && row.stage === "final_gate") return "GREEN";
    if (row.decision === "REJECTED" && row.stage === "trigger_gate") return "AMBER";
    return "RED";
  };
  const priority = { GREEN: 0, AMBER: 1, RED: 2 };
  const colors = { GREEN: "#22c55e", AMBER: "#f59e0b", RED: "#f87171" };
  const watchlist = symbols.map<ScanDecision>(symbol => scan?.rows.find(row => row.symbol === symbol) || { symbol });
  watchlist.sort((a, b) => priority[opportunity(a)] - priority[opportunity(b)] ||
    (b.confidence ?? 0) - (a.confidence ?? 0) || (b.quality ?? 0) - (a.quality ?? 0));
  const visible = showAll ? watchlist : watchlist.filter(row => opportunity(row) !== "RED");
  return <Card title="Stock Opportunities" wide className="decision-card">
    <p className="muted">Green passed the latest scan’s entry gates. Amber is waiting for an entry trigger. Orders are disabled.</p>
    {!marketOpen && <p className="muted">Waiting for an open market confirmed by Alpaca.</p>}
    {marketOpen && !scan && <p className="muted">Waiting for the first scan of this session.</p>}
    {scan && <p className="muted">
      Last scan {new Date(scan.completedAt).toLocaleTimeString("en-GB", { timeZone: "Europe/London" })}
      {" (UK) · "}{scan.scannedCount}/{scan.attemptedCount} stocks scanned
      {!scan.evaluationComplete ? " · Entry evaluation incomplete" : !current ? " · Inactive" : ""}
    </p>}
    <button className="ghost" onClick={() => setShowAll(value => !value)}>{showAll ? "Hide red" : "Show all"}</button>
    {current && !visible.length && <p className="muted">No current green or amber candidates.</p>}
    {visible.length > 0 && <div className="table-wrap">
      <table className="compact-table">
        <thead><tr><th>Stock</th><th>Result</th><th>Confidence</th><th>Quality</th><th>Reason</th></tr></thead>
        <tbody>{visible.map(row => {
          const result = opportunity(row);
          const reason = current ? row.reason || "No evaluation available"
            : !marketOpen ? "Market closed or unconfirmed"
            : scan?.evaluationComplete === false ? "Entry evaluation incomplete"
            : scan ? "Scan expired" : "Waiting for scan";
          return <tr key={row.symbol}>
            <td><b>{row.symbol}</b></td>
            <td><b style={{ color: colors[result] }}>{result}</b></td>
            <td>{row.confidence?.toFixed(2) ?? "—"}</td>
            <td>{row.quality?.toFixed(4) ?? "—"}</td>
            <td>{reason}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>}
  </Card>;
}

import { Meter } from "../components/Meter";
import { gbp, pct, tone, usd, positionQuantity, isSmallCryptoResidual } from "../lib/format";
import type { ActionFn, AnyObj, PositionStyleFn } from "../lib/types";

export function OverviewPage({ data, banking, message, positions, trades, rate, bestCandidate, aiConfidence, marketRegime, riskLabel, currentAction, botHealth, aiReasons, positionSettings, fetchData, positionGlowStyle, onExportFullBot, exportBusy, authToken }: { data: AnyObj; banking: AnyObj; message: string; positions: AnyObj[]; trades: AnyObj[]; rate: number; bestCandidate?: AnyObj; aiConfidence: number; marketRegime: string; riskLabel: string; currentAction: string; botHealth: number; aiReasons: string[]; positionSettings: AnyObj; fetchData: (force?: boolean) => Promise<void>; action: ActionFn; positionGlowStyle: PositionStyleFn; onExportFullBot: () => void; exportBusy: boolean; authToken: string }) {
  const stockPositions = positions.filter(position => position.assetClass === "us_equity");
  const maxPositions = Number(data?.maxPositions || positionSettings?.maxPositions || 0);
  const vault = banking?.profitVault || data?.banking?.profitVault || {};
  const market = data?.market || {};
  const finalGate = data?.finalGateMonitor || {};
  const shadow = data?.shadow || data?.shadowTrading || {};
  const outcomes = Number(data?.ai?.outcomes || data?.learning?.outcomes || data?.outcomes || 0);
  const cycleMonitor = data?.cycleMonitor || {};
  const cycleRows = cycleMonitor?.cycles || {};

  const systems = [
    ["V6 Outcome Engine", "OPERATIONAL"],
    ["V17.9 Decision Audit", "ACTIVE"],
    ["V18 Weekly Review", "ACTIVE"],
    ["V18.1 Observatory", "ACTIVE"],
    ["V12 CEO Advisor", "ACTIVE"],
    ["V12.1 Board Director", "ACTIVE"],
    ["V13 Memory Engine", "ACTIVE"],
    ["V14 Market Scientist", "ACTIVE"],
    ["V15 AIOPS Monitor", "ACTIVE"],
  ];

  const formatClock = (value: unknown) => {
    if (!value) return "—";
    const d = new Date(String(value));
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString("en-GB", { timeZone: "Europe/London", weekday: "short", hour: "2-digit", minute: "2-digit" });
  };

  return <main className="home-command-center">
    <section className="system-banner" aria-label="Trading mode">
      <b>Stock monitoring · Read-only</b>
      <span>Automatic buying and selling are disabled. Cryptocurrency trading is temporarily unavailable through Alpaca.</span>
    </section>
    {data?.cryptoMonitoringEnabled === true && <SmartRebuyPanel authToken={authToken} />}
    <section className="home-hero-row">
      <div className="system-banner"><span className={`status-dot ${botHealth >= 75 ? "healthy" : "warning"}`} /><b>{botHealth >= 75 ? "SYSTEM OPERATIONAL" : "SYSTEM CHECK"}</b><span>{message || currentAction}</span></div>
      <button className="full-report-button" onClick={onExportFullBot} disabled={exportBusy}>
        <span className="report-icon">▤</span>
        <span><strong>{exportBusy ? "BUILDING FULL BOT REPORT..." : "EXPORT FULL BOT REPORT PDF"}</strong><small>Everything included · V17.9 · V18 · V18.1 · all AI systems</small></span>
      </button>
    </section>

    <Card title="Quick Actions" wide className="quick-actions-card">
      <div className="command-actions">
        <button className="ghost" onClick={() => fetchData(true)}>↻  Refresh Dashboard</button>
      </div>
    </Card>

    <section className="command-grid">
      <Card title="Market Status" className="command-panel market-panel">
        <div className={`market-state ${market?.isOpen ? "open" : "closed"}`}><strong>{market?.isOpen ? "US Market Open" : "US Market Closed"}</strong><span>{market?.isOpen ? `Next close: ${formatClock(market?.nextClose)}` : `Next open: ${formatClock(market?.nextOpen)}`}</span></div>
        <div className="summary compact-summary">
          <div><span>Clock source</span><b>{String(market?.source || "Alpaca")}</b></div>
          <div><span>Fallback</span><b>{market?.fallbackActive ? "ACTIVE" : "Not needed"}</b></div>
          <div><span>Market regime</span><b>{marketRegime}</b></div>
          <div><span>Risk mode</span><b>{riskLabel}</b></div>
        </div>
      </Card>

      <Card title="Open Stock Positions" className="command-panel positions-panel">
        <div className="panel-count">{stockPositions.length}</div>
        {stockPositions.length ? <div className="position-list compact-positions">{stockPositions.slice(0, 3).map((p) => <article className="position" key={p.symbol} style={positionGlowStyle(p)}><div><h3>{p.symbol}</h3><p>Price {gbp(Number(p.price || 0) * rate)} · Qty {positionQuantity(p)}{isSmallCryptoResidual(p) ? " · Small residual holding" : ""}</p><p>Position value <b>{gbp(p.marketValueGbp ?? Number(p.marketValue || 0) * rate)}</b></p></div><div className="position-side"><b className={tone(p.pnl)}>PnL {gbp(p.pnlGbp ?? Number(p.pnl || 0) * rate)}<br />{pct(p.pnlPct)}</b></div></article>)}</div> : <div className="empty-position"><span>▣</span><b>No open stock positions</b></div>}
      </Card>

      <Card title="AI System Overview" className="command-panel systems-panel">
        <div className="system-list">{systems.map(([name, state]) => <div key={name}><span className="system-check">✓</span><span>{name}</span><b>{state}</b></div>)}</div>
      </Card>


      <Card title="Cycle Monitor" className="command-panel cycle-monitor-panel">
        <div className="research-badge">LIVE</div>
        <div className="summary compact-summary">
          {[["Bot", "bot"], ["Scientist", "scientist"], ["Research", "research"], ["Advisor", "advisor"], ["Scanner", "scanner"]].map(([label, key]) => { const row = cycleRows?.[key] || {}; return <div key={key}><span>{label}</span><b>{Number(row.thisRunCompleted || 0)} run · {Number(row.thisRunFailed || 0)} failed</b><small>Lifetime {Number(row.lifetimeCompleted || 0).toLocaleString("en-GB", { timeZone: "Europe/London" })} · {row.lastCompletedAt ? formatClock(row.lastCompletedAt) : "waiting"}</small></div>; })}
          <div><span>Current uptime</span><b>{Math.floor(Number(cycleMonitor?.uptimeSeconds || 0) / 3600)}h {Math.floor((Number(cycleMonitor?.uptimeSeconds || 0) % 3600) / 60)}m</b></div>
        </div>
      </Card>
      <Card title="AI Research & Learning" className="command-panel research-panel">
        <div className="research-badge">ACTIVE</div>
        <div className="summary compact-summary">
          <div><span>Outcome evidence</span><b>{outcomes ? outcomes.toLocaleString("en-GB", { timeZone: "Europe/London" }) : "LIVE"}</b></div>
          <div><span>AI confidence</span><b>{Math.round(aiConfidence)}%</b></div>
          <div><span>System health</span><b>{botHealth}%</b></div>
          <div><span>Shadow pending</span><b>{Number(shadow?.pending || 0).toLocaleString("en-GB", { timeZone: "Europe/London" })}</b></div>
          <div><span>Current action</span><b className="research-action">{currentAction}</b></div>
        </div>
      </Card>
    </section>

    <EntryGateDiagnostics symbols={data?.approvedStockSymbols || []} scan={data?.stockScan} marketOpen={market?.isOpen === true && !market?.fallbackActive} />
    <section className="grid two dashboard-detail-grid">
      <Card title="AI Brain" className="decision-card"><div className="ai-grid"><div><div className="ai-status-line"><span>Market view</span><b>{marketRegime}</b></div><div className="ai-status-line"><span>Risk</span><b>{riskLabel}</b></div><div className="ai-status-line"><span>Current action</span><b>{currentAction}</b></div><div className="ai-status-line"><span>Open positions</span><b>{stockPositions.length}/{maxPositions}</b></div></div><div><Meter value={aiConfidence} label="AI confidence"/><Meter value={botHealth} label="System health"/></div></div></Card>
      <Card title="Best Current Opportunity" className="decision-card">{bestCandidate?.symbol ? <><p className="eyebrow">Top-ranked candidate</p><h3 className="decision-symbol">{bestCandidate.symbol}</h3><div className="summary"><div><span>Confidence</span><b>{aiConfidence.toFixed(0)}%</b></div><div><span>Price</span><b>{bestCandidate?.price ? usd(bestCandidate.price) : "—"}</b></div><div><span>Movement</span><b className={tone(bestCandidate?.changePct || bestCandidate?.gap_pct)}>{pct(bestCandidate?.changePct ?? bestCandidate?.gap_pct ?? 0)}</b></div></div><ul className="reason-list">{aiReasons.length ? aiReasons.map((reason) => <li key={reason}>{reason}</li>) : <li>Waiting for the live scanner to provide detailed evidence.</li>}</ul></> : <p className="muted">No ranked opportunity is available yet. The card will populate when the scanner produces candidates.</p>}</Card>
      <Card title="Final Gate Monitor" className="decision-card final-gate-card"><div className="final-gate-head"><span className={`gate-pill ${finalGate?.state === "FINAL_GATE_READY" ? "ready" : finalGate?.state === "FINAL_GATE_WAITING" ? "waiting" : "idle"}`}>{finalGate?.state === "FINAL_GATE_READY" ? "FINAL GATE READY" : finalGate?.state === "FINAL_GATE_WAITING" ? "FINAL GATE · WAITING" : "SCANNING"}</span></div>{finalGate?.topCandidate?.symbol ? <><h3 className="decision-symbol">{finalGate.topCandidate.symbol}</h3><div className="summary"><div><span>Portfolio score</span><b>{Number(finalGate.topCandidate.portfolioScore || 0).toFixed(3)}</b></div><div><span>Minimum</span><b>{Number(finalGate.topCandidate.minimumScore || finalGate.minimumPortfolioScore || 0).toFixed(3)}</b></div></div><p className="muted">{finalGate.detail}</p></> : <p className="muted">No stock has reached the final portfolio gate yet.</p>}</Card>
      <Card title="Profit Vault" className="decision-card"><div className="final-gate-head"><span className={`gate-pill ${vault?.enabled ? "ready" : "idle"}`}>{vault?.enabled ? "PROFIT VAULT ACTIVE" : "VAULT OFF"}</span><span className="muted">100% realised-profit banking</span></div><div className="summary"><div><span>Trading capital</span><b>{gbp(Math.max(0, Number(vault?.accountEquityGbp || 0) - Number(vault?.bankedProfitGbp || 0)))}</b></div><div><span>Free cash</span><b>{gbp(Number(vault?.workingCapitalGbp || 0))}</b></div><div><span>Banked profit</span><b className={Number(vault?.bankedProfitGbp || 0) > 0 ? "positive" : ""}>{gbp(Number(vault?.bankedProfitGbp || 0))}</b></div><div><span>Protected baseline</span><b>{gbp(Number(vault?.baselineGbp || 0))}</b></div><div><span>Lifetime banked</span><b>{gbp(Number(vault?.lifetimeBankedGbp || 0))}</b></div></div><p className="muted" style={{marginTop:10}}>Trading capital includes money currently invested in the open position plus free cash. Banked profit is protected and excluded from new buys.</p></Card>
      <Card title="Recent AI Activity" wide><div className="log-list">{trades.slice(-8).reverse().map((trade, index) => <div key={index}>{trade.time || "—"} · <b>{trade.side} {trade.symbol}</b> · {trade.reason || "Decision recorded"}</div>)}{!trades.length && <p className="muted">No recent trading activity.</p>}</div></Card>
    </section>
  </main>;
}
