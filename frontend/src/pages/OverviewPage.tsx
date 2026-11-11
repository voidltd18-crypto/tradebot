import { Card } from "../components/Card";
import { useEffect, useState } from "react";
import { API_URL } from "../lib/api";

const APPROVED_TECH = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ORCL", "AMD", "TSLA"];

function EntryGateDiagnostics({ authToken }: { authToken: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState("");
  useEffect(() => {
    if (!authToken) return;
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch(`${API_URL}/v2/recent-decisions?limit=300`, {
          cache: "no-store", headers: { "X-Auth-Token": authToken, "x-api-key": authToken }
        });
        if (!response.ok) throw new Error(`Decision history unavailable (HTTP ${response.status})`);
        const result = await response.json();
        if (!active) return;
        const latest = new Map<string, any>();
        for (const item of (Array.isArray(result?.decisions) ? result.decisions : [])) {
          const symbol = String(item?.symbol || "").toUpperCase();
          if (APPROVED_TECH.includes(symbol) && !latest.has(symbol)) latest.set(symbol, item);
        }
        setRows(APPROVED_TECH.map(symbol => latest.get(symbol) || { symbol }));
        setUpdated(new Date().toISOString());
        setError("");
      } catch (e: any) { if (active) setError(e?.message || "Decision history unavailable"); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, [authToken]);
  // A pre-expectancy rejection records zero-valued placeholders for historical
  // metrics. Do not present those as evidence of zero wins or zero samples.
  const hasExpectancyEvidence = (row: any) =>
    ["expectancy_gate", "v17_cold_start_gate", "final_gate"].includes(String(row.stage || "")) ||
    Number(row.historical_samples || 0) > 0;
  // Session-aware freshness: the previous close is expected outside regular
  // US equity hours. This schedule is indicative; exchange holidays and halts
  // are not inferred from the clock.
  const nyParts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", weekday: "short", hour: "2-digit",
    minute: "2-digit", hourCycle: "h23"
  }).formatToParts(new Date());
  const nyValue = (type: string) => nyParts.find(part => part.type === type)?.value || "";
  const nyMinute = Number(nyValue("hour")) * 60 + Number(nyValue("minute"));
  const regularHours = !["Sat", "Sun"].includes(nyValue("weekday")) && nyMinute >= 570 && nyMinute < 960;
  const sessionStartedLongEnough = nyMinute >= 600;
  const decisionStatus = (row: any) => {
    if (!row.timestamp) return "NO RECORD";
    const age = Date.now() - new Date(row.timestamp).getTime();
    if (!regularHours) return "LAST SESSION";
    if (age <= 30 * 60 * 1000) return "RECENT";
    return sessionStartedLongEnough ? "SCAN OVERDUE" : "AWAITING OPEN SCAN";
  };
  const memoryAudit = (row: any) => {
    try { const payload = JSON.parse(String(row.payload_json || "{}")); return payload?.confidenceMemoryAudit || null; }
    catch { return null; }
  };
  const numeric = (value: unknown, digits: number) => value == null || value === "" ? "—" : Number(value).toFixed(digits);
  const friendlyReason = (row: any) => {
    const reason = String(row.reason || "");
    if (!row.decision) return "No recorded decision";
    if (row.stage === "sniper_gate" && reason.includes("confidence too low")) return "Confidence below sniper minimum";
    if (row.stage === "account_gate" && reason.includes("locked until tomorrow")) return "Daily trading lock";
    if (row.stage === "symbol_reputation_gate" && reason.includes("cooldown")) return "Historical reputation cooldown";
    if (row.stage === "expectancy_gate") return "Historical expectancy check";
    if (row.stage === "account_gate") return "Account or order restriction";
    return reason || String(row.stage || "Not approved").replace(/_/g, " ");
  };
  const recordedAt = (row: any) => row.timestamp
    ? new Date(row.timestamp).toLocaleString("en-GB", {
        timeZone: "Europe/London", day: "2-digit", month: "short",
        hour: "2-digit", minute: "2-digit"
      }) : "—";
  return <Card title="Why No Buy? · Entry Gate Diagnostics" wide className="decision-card">
    <p className="muted">Latest recorded decision for each approved stock. Confidence shows the score used for trading; raw confidence and memory show how historical performance affected it. Read-only.</p>
    {error && <p className="muted">{error}</p>}
    {updated && <p className="muted">Checked {new Date(updated).toLocaleTimeString("en-GB")} · US session labels are clock-based (holidays and halts not detected)</p>}
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "0.85rem" }}>
        <thead><tr>{["Stock", "Result", "Session", "Final conf.", "Raw conf.", "Memory ×", "Why?", "Recorded"].map(label =>
          <th key={label} style={{ padding: "9px 7px", borderBottom: "1px solid #64748b", whiteSpace: "nowrap" }}>{label}</th>
        )}</tr></thead>
        <tbody>{rows.map(row => <tr key={row.symbol}>
          <td style={{ padding: "9px 7px" }}><b>{row.symbol}</b></td>
          <td style={{ padding: "9px 7px" }}>{row.decision || "No record"}</td>
          <td style={{ padding: "9px 7px", whiteSpace: "nowrap" }}>{decisionStatus(row)}</td>
          <td style={{ padding: "9px 7px" }}><b>{numeric(row.confidence, 2)}</b></td>
          <td style={{ padding: "9px 7px" }}>{numeric(memoryAudit(row)?.rawConfidence, 2)}</td>
          <td style={{ padding: "9px 7px" }}>{memoryAudit(row)?.multiplier == null ? "—" : `${Number(memoryAudit(row).multiplier).toFixed(2)}×`}</td>
          <td style={{ padding: "9px 7px", minWidth: "190px" }}>
            <details>
              <summary style={{ cursor: "pointer" }}>{friendlyReason(row)}</summary>
              <div className="muted" style={{ paddingTop: "6px", fontSize: "0.8rem" }}>
                <div>Gate: {row.stage || "—"}</div>
                <div>Exact reason: {row.reason || "—"}</div>
                <div>Quality: {numeric(row.quality, 4)}</div>
                <div>Historical samples: {hasExpectancyEvidence(row) ? row.historical_samples ?? "—" : "Not evaluated"}</div>
                <div>Win rate: {hasExpectancyEvidence(row) && row.historical_win_rate != null ? `${(Number(row.historical_win_rate) * 100).toFixed(0)}%` : "Not evaluated"}</div>
                <div>Profit factor: {hasExpectancyEvidence(row) ? numeric(row.historical_profit_factor, 2) : "Not evaluated"}</div>
              </div>
            </details>
          </td>
          <td style={{ padding: "9px 7px", whiteSpace: "nowrap" }}>{recordedAt(row)}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <p className="muted" style={{ fontSize: "0.78rem" }}>LAST SESSION = previous regular session; RECENT = within 30 minutes; SCAN OVERDUE = no recent decision after 10:00 New York time. Dashes mean older decisions lack the new memory audit. Click a reason for the full evidence.</p>
  </Card>;
}


import { Meter } from "../components/Meter";
import { gbp, pct, tone, usd, positionQuantity, isSmallCryptoResidual } from "../lib/format";
import type { ActionFn, AnyObj, PositionStyleFn } from "../lib/types";

export function OverviewPage({ data, banking, message, positions, trades, rate, bestCandidate, aiConfidence, marketRegime, riskLabel, currentAction, botHealth, aiReasons, positionSettings, fetchData, action, positionGlowStyle, onExportFullBot, exportBusy, authToken }: { data: AnyObj; banking: AnyObj; message: string; positions: AnyObj[]; trades: AnyObj[]; rate: number; bestCandidate?: AnyObj; aiConfidence: number; marketRegime: string; riskLabel: string; currentAction: string; botHealth: number; aiReasons: string[]; positionSettings: AnyObj; fetchData: (force?: boolean) => Promise<void>; action: ActionFn; positionGlowStyle: PositionStyleFn; onExportFullBot: () => void; exportBusy: boolean; authToken: string }) {
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
    <section className="home-hero-row">
      <div className="system-banner"><span className={`status-dot ${botHealth >= 75 ? "healthy" : "warning"}`} /><b>{botHealth >= 75 ? "SYSTEM OPERATIONAL" : "SYSTEM CHECK"}</b><span>{message || currentAction}</span></div>
      <button className="full-report-button" onClick={onExportFullBot} disabled={exportBusy}>
        <span className="report-icon">▤</span>
        <span><strong>{exportBusy ? "BUILDING FULL BOT REPORT..." : "EXPORT FULL BOT REPORT PDF"}</strong><small>Everything included · V17.9 · V18 · V18.1 · all AI systems</small></span>
      </button>
    </section>

    <Card title="Quick Actions" wide className="quick-actions-card">
      <div className="command-actions">
        <button className="ghost" onClick={() => action(data?.botEnabled ? "/pause" : "/resume")}>{data?.botEnabled ? "⏸  Pause Trading" : "▶  Resume Trading"}</button>
        <button className="ghost" onClick={() => action("/manual-buy")}>🛒  Manual Buy</button>
        <button className="ghost" onClick={() => action("/manual-sell")}>⇩  Manual Sell (Worst)</button>
        <button className="ghost" onClick={() => fetchData(true)}>↻  Refresh Dashboard</button>
        <button className="danger" onClick={() => confirm("Emergency sell all open positions?") && action("/emergency-sell")}>⚡  Emergency Sell</button>
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

      <Card title="Open Positions" className="command-panel positions-panel">
        <div className="panel-count">{positions.length}</div>
        {positions.length ? <div className="position-list compact-positions">{positions.slice(0, 3).map((p) => <article className="position" key={p.symbol} style={positionGlowStyle(p)}><div><h3>{p.symbol}</h3><p>Price {gbp(Number(p.price || 0) * rate)} · Qty {positionQuantity(p)}{isSmallCryptoResidual(p) ? " · Small residual holding" : ""}</p><p>Position value <b>{gbp(p.marketValueGbp ?? Number(p.marketValue || 0) * rate)}</b></p></div><div className="position-side"><b className={tone(p.pnl)}>PnL {gbp(p.pnlGbp ?? Number(p.pnl || 0) * rate)}<br />{pct(p.pnlPct)}</b></div></article>)}</div> : <div className="empty-position"><span>▣</span><b>No Open Positions</b><small>The bot is ready to find opportunities</small></div>}
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

    <EntryGateDiagnostics authToken={authToken} />
    <section className="grid two dashboard-detail-grid">
      <Card title="AI Brain" className="decision-card"><div className="ai-grid"><div><div className="ai-status-line"><span>Market view</span><b>{marketRegime}</b></div><div className="ai-status-line"><span>Risk</span><b>{riskLabel}</b></div><div className="ai-status-line"><span>Current action</span><b>{currentAction}</b></div><div className="ai-status-line"><span>Open positions</span><b>{positions.length}/{maxPositions}</b></div></div><div><Meter value={aiConfidence} label="AI confidence"/><Meter value={botHealth} label="System health"/></div></div></Card>
      <Card title="Best Current Opportunity" className="decision-card">{bestCandidate?.symbol ? <><p className="eyebrow">Top-ranked candidate</p><h3 className="decision-symbol">{bestCandidate.symbol}</h3><div className="summary"><div><span>Confidence</span><b>{aiConfidence.toFixed(0)}%</b></div><div><span>Price</span><b>{bestCandidate?.price ? usd(bestCandidate.price) : "—"}</b></div><div><span>Movement</span><b className={tone(bestCandidate?.changePct || bestCandidate?.gap_pct)}>{pct(bestCandidate?.changePct ?? bestCandidate?.gap_pct ?? 0)}</b></div></div><ul className="reason-list">{aiReasons.length ? aiReasons.map((reason) => <li key={reason}>{reason}</li>) : <li>Waiting for the live scanner to provide detailed evidence.</li>}</ul></> : <p className="muted">No ranked opportunity is available yet. The card will populate when the scanner produces candidates.</p>}</Card>
      <Card title="Final Gate Monitor" className="decision-card final-gate-card"><div className="final-gate-head"><span className={`gate-pill ${finalGate?.state === "FINAL_GATE_READY" ? "ready" : finalGate?.state === "FINAL_GATE_WAITING" ? "waiting" : "idle"}`}>{finalGate?.state === "FINAL_GATE_READY" ? "FINAL GATE READY" : finalGate?.state === "FINAL_GATE_WAITING" ? "FINAL GATE · WAITING" : "SCANNING"}</span></div>{finalGate?.topCandidate?.symbol ? <><h3 className="decision-symbol">{finalGate.topCandidate.symbol}</h3><div className="summary"><div><span>Portfolio score</span><b>{Number(finalGate.topCandidate.portfolioScore || 0).toFixed(3)}</b></div><div><span>Minimum</span><b>{Number(finalGate.topCandidate.minimumScore || finalGate.minimumPortfolioScore || 0).toFixed(3)}</b></div></div><p className="muted">{finalGate.detail}</p></> : <p className="muted">No stock has reached the final portfolio gate yet.</p>}</Card>
      <Card title="Profit Vault" className="decision-card"><div className="final-gate-head"><span className={`gate-pill ${vault?.enabled ? "ready" : "idle"}`}>{vault?.enabled ? "PROFIT VAULT ACTIVE" : "VAULT OFF"}</span><span className="muted">100% realised-profit banking</span></div><div className="summary"><div><span>Trading capital</span><b>{gbp(Math.max(0, Number(vault?.accountEquityGbp || 0) - Number(vault?.bankedProfitGbp || 0)))}</b></div><div><span>Free cash</span><b>{gbp(Number(vault?.workingCapitalGbp || 0))}</b></div><div><span>Banked profit</span><b className={Number(vault?.bankedProfitGbp || 0) > 0 ? "positive" : ""}>{gbp(Number(vault?.bankedProfitGbp || 0))}</b></div><div><span>Protected baseline</span><b>{gbp(Number(vault?.baselineGbp || 0))}</b></div><div><span>Lifetime banked</span><b>{gbp(Number(vault?.lifetimeBankedGbp || 0))}</b></div></div><p className="muted" style={{marginTop:10}}>Trading capital includes money currently invested in the open position plus free cash. Banked profit is protected and excluded from new buys.</p></Card>
      <Card title="Recent AI Activity" wide><div className="log-list">{trades.slice(-8).reverse().map((trade, index) => <div key={index}>{trade.time || "—"} · <b>{trade.side} {trade.symbol}</b> · {trade.reason || "Decision recorded"}</div>)}{!trades.length && <p className="muted">No recent trading activity.</p>}</div></Card>
    </section>
  </main>;
}
