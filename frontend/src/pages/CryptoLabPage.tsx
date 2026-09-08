import { useEffect, useMemo, useState } from "react";
import { API_URL } from "../lib/api";
import type { AnyObj } from "../lib/types";

const money = (n: unknown) => `$${Number(n || 0).toFixed(2)}`;
const pct = (n: unknown) => `${Number(n || 0).toFixed(2)}%`;
const gbp = (n: unknown) => `£${Number(n || 0).toFixed(2)}`;


function fmtHeldDuration(openedAt: unknown, clockTick = 0) {
  void clockTick; // forces a fresh calculation on the page's 1-second clock
  if (!openedAt) return "HELD --:--:--";
  const started = new Date(String(openedAt)).getTime();
  if (!Number.isFinite(started)) return "HELD --:--:--";
  const total = Math.max(0, Math.floor((Date.now() - started) / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return `HELD ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

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
  if (score >= Math.max(0.60, threshold - 0.08)) return { label: "NEAR ENTRY", cls: "near" };
  if (score >= 0.50) return { label: "BUILDING", cls: "building" };
  return { label: "WATCHING", cls: "watching" };
}

function CryptoRecordTracker({ points }: { points: AnyObj[] }) {
  const rows = Array.isArray(points) ? points : [];
  if (!rows.length) return <div className="crypto-chart-empty">Recording starts with V18.2.52. The first movement point will appear after the live worker runs.</div>;
  const values = rows.map(r => Number(r.totalPnlGbp || 0));
  let min = Math.min(...values, 0), max = Math.max(...values, 0);
  if (Math.abs(max - min) < 0.01) { max += 0.5; min -= 0.5; }
  const width = 1000, height = 280, padX = 18, padY = 18;
  const x = (i: number) => padX + (rows.length <= 1 ? 0 : i * (width - padX * 2) / (rows.length - 1));
  const y = (v: number) => padY + (max - v) * (height - padY * 2) / (max - min);
  const path = rows.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(Number(r.totalPnlGbp || 0)).toFixed(1)}`).join(" ");
  const zeroY = y(0);
  const latest = rows[rows.length - 1];
  const first = rows[0];
  const fmtTime = (v: unknown) => { try { return new Date(String(v)).toLocaleString("en-GB", { day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit" }); } catch { return ""; } };
  return <>
    <div className="crypto-chart-stats">
      <span><small>Current movement</small><strong className={Number(latest.totalPnlGbp || 0) >= 0 ? "gain" : "loss"}>{gbp(latest.totalPnlGbp)}</strong></span>
      <span><small>High</small><strong className="gain">{gbp(max)}</strong></span>
      <span><small>Low</small><strong className={min < 0 ? "loss" : ""}>{gbp(min)}</strong></span>
      <span><small>Points recorded</small><strong>{rows.length.toLocaleString("en-GB")}</strong></span>
    </div>
    <div className="crypto-record-chart" title={`Latest ${gbp(latest.totalPnlGbp)} · ${fmtTime(latest.timestamp)}`}>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Crypto profit and loss movement history">
        <line className="crypto-chart-zero" x1={padX} y1={zeroY} x2={width-padX} y2={zeroY}/>
        <path className="crypto-chart-line" d={path}/>
      </svg>
    </div>
    <div className="crypto-chart-axis"><span>{fmtTime(first.timestamp)}</span><span>{fmtTime(latest.timestamp)}</span></div>
    <div className="crypto-chart-legend"><span>● Total crypto P&amp;L movement (realised + live unrealised)</span><span>Snapshots every 15 seconds · persistent across refresh/restart</span></div>
  </>;
}

export function CryptoLabPage({ authToken }: { authToken: string }) {
  const [data, setData] = useState<AnyObj | null>(null);
  const [decisionAudit, setDecisionAudit] = useState<any>(null);
  const [decisionAuditError, setDecisionAuditError] = useState<string>("");
  const [engineHealth, setEngineHealth] = useState<any>(null);
  const [engineHealthError, setEngineHealthError] = useState<string>("");
  const [ledgerHealth, setLedgerHealth] = useState<any>(null);


  const [error, setError] = useState("");
  const [bridge, setBridge] = useState<AnyObj | null>(null);
  const [sellBusySymbol, setSellBusySymbol] = useState("");
  const [sellMessage, setSellMessage] = useState("");
  const [history, setHistory] = useState<AnyObj[]>([]);
  const [clockTick, setClockTick] = useState(0);

    const loadDecisionAudit = async () => {
    try {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 8000);
      const res = await fetch(`${API_URL}/v18/crypto-decision-audit?limit=5000`, {
        headers: { "X-API-Key": authToken },
        signal: controller.signal,
      });
      window.clearTimeout(timer);
      if (!res.ok) throw new Error(`Audit HTTP ${res.status}`);
      const body = await res.json();
      setDecisionAudit(body);
      setDecisionAuditError("");
    } catch (err: any) {
      setDecisionAuditError(err?.message || "Decision audit unavailable");
    }
  };

  const loadEngineHealth = async () => {
    try {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 5000);
      const res = await fetch(`${API_URL}/v18/engine-health`, {
        headers: { "X-API-Key": authToken },
        signal: controller.signal,
      });
      window.clearTimeout(timer);
      if (!res.ok) throw new Error(`Health HTTP ${res.status}`);
      setEngineHealth(await res.json());
      setEngineHealthError("");
    } catch (err: any) {
      setEngineHealthError(err?.message || "Engine health unavailable");
    }
  };

  const loadLedgerHealth = async () => {
    try {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 5000);
      const res = await fetch(`${API_URL}/v18/crypto-ledger-health`, {
        headers: { "X-API-Key": authToken },
        signal: controller.signal,
      });
      window.clearTimeout(timer);
      if (res.ok) setLedgerHealth(await res.json());
    } catch (_) {}
  };

useEffect(() => {
    loadLedgerHealth();
    loadEngineHealth();
    loadDecisionAudit();
    const id = window.setInterval(() => setClockTick(v => v + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    let alive = true;

    const fetchJson = async (url: string, timeoutMs: number) => {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), timeoutMs);
      try {
        const res = await fetch(url, {
          headers: { "X-API-Key": authToken },
          signal: controller.signal,
        });
        const body = await res.json();
        if (!res.ok) throw new Error(body?.detail || body?.message || `HTTP ${res.status}`);
        return body;
      } finally {
        window.clearTimeout(timer);
      }
    };

    const load = async () => {
      // V18.2.67: requests are independent. A slow history/bridge endpoint must
      // never leave the entire 24/7 Crypto Lab stuck on the loading card.
      const [shadowResult, bridgeResult, historyResult] = await Promise.allSettled([
        fetchJson(`${API_URL}/v18/crypto-shadow`, 8000),
        fetchJson(`${API_URL}/v18/crypto-bridge`, 8000),
        fetchJson(`${API_URL}/v18/crypto-history?limit=5000`, 8000),
      ]);
      if (!alive) return;

      const warnings: string[] = [];
      if (shadowResult.status === "fulfilled") {
        setData(shadowResult.value);
      } else {
        warnings.push(`scanner: ${shadowResult.reason?.name === "AbortError" ? "timeout" : shadowResult.reason?.message || "unavailable"}`);
      }
      if (bridgeResult.status === "fulfilled") {
        setBridge({ ...bridgeResult.value, __fetchedAt: Date.now() });
      } else {
        warnings.push(`bridge: ${bridgeResult.reason?.name === "AbortError" ? "timeout" : bridgeResult.reason?.message || "unavailable"}`);
      }
      if (historyResult.status === "fulfilled" && Array.isArray(historyResult.value?.points)) {
        setHistory(historyResult.value.points);
      } else if (historyResult.status === "rejected") {
        warnings.push(`history: ${historyResult.reason?.name === "AbortError" ? "timeout" : historyResult.reason?.message || "unavailable"}`);
      }
      setError(warnings.length ? `Partial refresh · ${warnings.join(" · ")}` : "");
    };

    load();
    const id = window.setInterval(load, 30000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [authToken]);

  const manualSellCrypto = async (position: AnyObj) => {
    const symbol = String(position?.symbol || "").toUpperCase();
    if (!symbol || sellBusySymbol) return;
    const managed = Boolean(position?.managedByPilot);
    const ownershipText = managed ? "TradeBot live-pilot" : "manual/external Alpaca";
    if (!window.confirm(`SELL 100% of ${symbol} now?\n\nThis will submit a real market sell for the ${ownershipText} position.`)) return;
    setSellBusySymbol(symbol);
    setSellMessage("");
    try {
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), 8000);
      let res: Response;
      try {
        res = await fetch(`${API_URL}/v18/crypto-bridge/manual-sell`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Auth-Token": authToken, "x-api-key": authToken },
          body: JSON.stringify({ symbol, confirmation: "SELL CRYPTO NOW" }),
          signal: controller.signal,
        });
      } finally {
        window.clearTimeout(timeoutId);
      }
      const body = await res.json();
      if (!res.ok || body?.ok === false) throw new Error(body?.message || body?.detail || `HTTP ${res.status}`);
      setSellMessage(body?.message || `Manual sell accepted for ${symbol}.`);
      // V18.2.68: endpoint acknowledgement is immediate; the durable broker
      // execution completes independently. Refresh the bridge shortly after so
      // the position disappears as soon as Alpaca confirms the sell.
      window.setTimeout(async () => {
        try {
          const refresh = await fetch(`${API_URL}/v18/crypto-bridge`, {
            headers: { "X-Auth-Token": authToken, "x-api-key": authToken },
          });
          const freshBody = await refresh.json();
          if (refresh.ok) setBridge({ ...freshBody, __fetchedAt: Date.now() });
        } catch (_) {}
      }, 1500);
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
  const entryScore = Number(data.config?.entryScore || 0.34);
  const armed = Boolean(bridge?.livePilotEnabled);
  const accountActive = Boolean(bridge?.accountCrypto?.active);
  const entriesPaused = Boolean(bridge?.newEntriesPaused);
  const bridgeFetchedAt = Number(bridge?.__fetchedAt || 0);
  const elapsedSinceBridge = bridgeFetchedAt ? Math.max(0, Math.floor((Date.now() - bridgeFetchedAt) / 1000)) : 0;
  const nextDecisionSeconds = Math.max(0, Number(bridge?.nextNormalDecisionInSeconds || 0) - elapsedSinceBridge);
  const fmtCountdown = (seconds: number) => {
    const total = Math.max(0, Math.floor(seconds));
    const mm = Math.floor(total / 60);
    const ss = total % 60;
    return `${mm}:${String(ss).padStart(2, "0")}`;
  };
  void clockTick;
  const liveKeys = new Set(livePositions.map((p: AnyObj) => String(p?.symbol || "").replace("/", "").toUpperCase()));
  const cooldowns = bridge?.activeReentryCooldowns && typeof bridge.activeReentryCooldowns === "object" ? bridge.activeReentryCooldowns : {};
  const cooldownRemaining = (symbol: unknown) => {
    const key = String(symbol || "").replace("/", "").toUpperCase();
    const raw = cooldowns?.[key];
    if (!raw) return 0;
    const until = new Date(String(raw)).getTime();
    return Number.isFinite(until) ? Math.max(0, Math.floor((until - Date.now()) / 1000)) : 0;
  };

  return <div className="crypto-lab-page">
    <section className="crypto-hero">
      <div className="crypto-hero-main">
        <div className="crypto-hero-icon">₿</div>
        <div>
          <div className="eyebrow">V18.2.77.1 · DASHBOARD API HOTFIX</div>
          <h2>Crypto Lab</h2>
          <p>Live crypto trading pilot — real capital, real trades, real results.</p>
        </div>
      </div>
      <div className={`crypto-live-badge ${armed ? "armed" : "idle"}`}><span>●</span>{armed ? (entriesPaused ? "PAUSED · EXITS ARMED" : "LIVE PILOT ARMED") : "LIVE PILOT OFF"}</div>
    </section>

    {entriesPaused && <div className="crypto-notice">New crypto entries are paused with the main bot. Existing bot-managed crypto positions keep stop-loss and trailing protection active.</div>}

    <section className="crypto-summary-grid">
      <div className="crypto-summary-card"><div className="crypto-summary-icon vault">▣</div><div><span>Piggy Bank</span><strong>{gbp(bridge?.piggyBankGbp ?? bridge?.vaultAvailableGbp)}</strong><small>Banked · never reused</small></div></div>
      <div className="crypto-summary-card"><div className="crypto-summary-icon allocation">●</div><div><span>Crypto Allocation</span><strong>{gbp(bridge?.cryptoAllocatedGbp)}</strong><small>Automatic surplus above £900 stock reserve</small></div></div>
      <div className="crypto-summary-card"><div className="crypto-summary-icon pnl">↗</div><div><span>Crypto P&amp;L</span><strong className={Number(bridge?.cryptoRealisedPnlGbp || 0) >= 0 ? "gain" : "loss"}>{gbp(bridge?.cryptoRealisedPnlGbp)}</strong><small>Realised live pilot</small></div></div>
    </section>

    <section className="crypto-panel crypto-record-panel">
      <div className="crypto-panel-head">
        <div><h3><span className="panel-icon">⌁</span> Crypto Record Tracker</h3><p>Permanent movement history for the live crypto pilot — records realised and unrealised P&amp;L while positions move.</p></div>
        <span className="crypto-chip live">RECORDING</span>
      </div>
      <CryptoRecordTracker points={history} />
    </section>

    {livePositions.length > 0 && <section className="crypto-panel crypto-live-positions">
      <div className="crypto-panel-head">
        <div><h3>Live Crypto Positions</h3><p>Up to 10 real Alpaca crypto positions. Bot-managed positions have independent exit protection and can free stalled slots after 45 minutes.</p></div>
        <span className="crypto-chip live">LIVE</span>
      </div>
      <div className="crypto-position-grid">
        {livePositions.map((p: AnyObj) => {
          const pnl = Number(p.pnlGbp ?? p.pnlUsd ?? 0);
          const pnlPct = Number(p.pnlPct || 0);
          const managed = Boolean(p.managedByPilot);
          return <div className="crypto-position-card" key={p.symbol}>
            <div className="crypto-position-symbol"><span className="coin-icon">{coinGlyph(p.symbol)}</span><div><strong>{p.symbol}</strong><small>Entry {money(p.entry)} · {managed ? "BOT MANAGED" : "MANUAL / EXTERNAL"}</small>{managed && <small className="crypto-held-timer">{fmtHeldDuration(p.openedAt, clockTick)}</small>}{managed && p.protection && <small className="crypto-protection-line">{p.protection.trailArmed ? `TRAIL ARMED · HIGH ${money(p.protection.highPrice)} · SELL BELOW ~${money(p.protection.activeFloor)}` : `STOP ARMED · ~${money(p.protection.stopPrice)} · TRAIL AT +${Number(p.protection.trailStartPct || 0).toFixed(1)}%`}</small>}</div></div>
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
          <p>Automatically discovers Alpaca's active USD crypto market and uses a market-relative liquidity floor with a $250 minimum, so active mid-liquidity pairs are not blocked just because BTC clears the old $5k gate. Trades only when score ≥ {entryScore.toFixed(2)}.</p>
        </div>
        <div className="scanner-state"><span className="crypto-chip">{Number(data?.marketDiscovery?.discovered || scans.length)} discovered</span><span className="crypto-chip">{Number(data?.marketDiscovery?.eligible || scans.filter((s: AnyObj) => s.liquid !== false).length)} liquid</span><span className="crypto-chip">{scans.filter((s: AnyObj) => Boolean(s.qualified)).length} qualified</span><span className="crypto-chip crypto-countdown-chip">NEXT DECISION {fmtCountdown(nextDecisionSeconds)}</span><span className="crypto-chip crypto-cycle-chip">CYCLES {Number(bridge?.normalDecisionCycleCount || 0)}</span><span className="crypto-chip">{String(data?.marketDiscovery?.liquidityMode || "fixed").toUpperCase()} ≥ {money(data?.marketDiscovery?.effectiveLiquidity60mUsd || data?.config?.minLiquidity60mUsd || 0)}</span><span className="scanning-dot">●</span><span>Dynamic</span></div>
      </div>
      <div className="crypto-table-wrap">
        <table className="crypto-scanner-table">
          <thead><tr><th>Symbol</th><th>Price</th><th>Score</th><th>15m</th><th>60m</th><th>60m Range</th><th>Liquidity</th><th>Status</th></tr></thead>
          <tbody>{scans.map((s: AnyObj) => {
            const score = Number(s.score || 0);
            const key = String(s.symbol || "").replace("/", "").toUpperCase();
            const held = liveKeys.has(key);
            const cooldownSecs = cooldownRemaining(s.symbol);
            const min15 = Number(bridge?.min15mMomentumPct ?? -0.10);
            const min60 = Number(bridge?.min60mMomentumPct ?? 0.00);
            const ret15 = Number(s.return15mPct || 0);
            const ret60 = Number(s.return60mPct || 0);
            const backendQualified = Boolean(s.qualified);
            let blockedState = scoreState(score, entryScore);
            if (s.liquid === false) {
              blockedState = { label: "BLOCKED · THIN LIQUIDITY", cls: "watching" };
            } else if (score < entryScore) {
              blockedState = { label: `BLOCKED · SCORE ${score.toFixed(3)} < ${entryScore.toFixed(2)}`, cls: "watching" };
            } else if (ret15 < min15) {
              blockedState = { label: `BLOCKED · 15m ${ret15.toFixed(2)}% < ${min15.toFixed(2)}%`, cls: "watching" };
            } else if (ret60 < min60) {
              blockedState = { label: `BLOCKED · 60m ${ret60.toFixed(2)}% < ${min60.toFixed(2)}%`, cls: "watching" };
            } else if (!backendQualified) {
              blockedState = { label: "BLOCKED · BACKEND GATE", cls: "watching" };
            }
            const state = held
              ? { label: "HELD · EXIT ARMED", cls: "held" }
              : cooldownSecs > 0
                ? { label: `COOLDOWN ${fmtCountdown(cooldownSecs)}`, cls: "cooldown" }
                : backendQualified
                  ? { label: nextDecisionSeconds > 0 ? `QUALIFIED · ${fmtCountdown(nextDecisionSeconds)}` : "QUALIFIED · DUE", cls: "qualified" }
                  : blockedState;
            const progress = Math.max(4, Math.min(100, (score / entryScore) * 100));
            return <tr key={s.symbol} className={held ? "held-row" : cooldownSecs > 0 ? "cooldown-row" : backendQualified ? "qualified-row" : ""}>
              <td><div className="crypto-symbol"><span className="coin-icon small">{coinGlyph(s.symbol)}</span><strong>{s.symbol}</strong></div></td>
              <td>{money(s.price)}</td>
              <td><span className={`score-badge ${state.cls}`}>{score.toFixed(3)}</span></td>
              <td className={Number(s.return15mPct || 0) >= 0 ? "gain" : "loss"}>{pct(s.return15mPct)}</td>
              <td className={Number(s.return60mPct || 0) >= 0 ? "gain" : "loss"}>{pct(s.return60mPct)}</td>
              <td>{pct(s.range60mPct)}</td>
              <td><span className={s.liquid === false ? "loss" : "gain"}>{money(s.liquidity60mUsd)}</span><small style={{display:"block",opacity:.7}}>{s.liquid === false ? "THIN" : "LIQUID"}</small></td>
              <td><div className="crypto-status-cell"><span className={`crypto-chip ${state.cls}`}>{state.label}</span><span className="score-track"><span style={{ width: `${progress}%` }} /></span></div></td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      {error && <div className="crypto-warning">Last refresh warning: {error}</div>}
      {data.lastError && <div className="crypto-warning">Engine warning: {data.lastError}</div>}
    </section>

    
      
      <section className="crypto-card">
        <div className="crypto-section-heading">
          <div>
            <div className="crypto-kicker">♥ Engine Health</div>
            <h2>{engineHealth?.status === "GOOD" ? "GOOD 🟢" : "DEGRADED 🟠"}</h2>
            <p>Mechanical health only — this does not alter entries, exits or risk rules.</p>
          </div>
          <button type="button" className="crypto-secondary-button" onClick={loadEngineHealth}>Refresh Health</button>
        </div>

        {engineHealthError && <div className="crypto-warning">Health warning: {engineHealthError}</div>}

        <div className="crypto-metric-grid">
          <div className="crypto-metric"><span>Safety loop age</span><strong>{engineHealth?.safetyAgeSeconds ?? "—"}s</strong></div>
          <div className="crypto-metric"><span>Last safety duration</span><strong>{engineHealth?.lastSafetyDurationMs ?? "—"} ms</strong></div>
          <div className="crypto-metric"><span>Decision age</span><strong>{engineHealth?.decisionAgeSeconds ?? "—"}s</strong></div>
          <div className="crypto-metric"><span>Decision duration</span><strong>{engineHealth?.lastDecisionDurationMs ?? "—"} ms</strong></div>
          <div className="crypto-metric"><span>Scanner age</span><strong>{engineHealth?.scannerAgeSeconds ?? "—"}s</strong></div>
          <div className="crypto-metric"><span>Scanner duration</span><strong>{engineHealth?.lastScannerDurationMs ?? "—"} ms</strong></div>
          <div className="crypto-metric"><span>Last buy latency</span><strong>{engineHealth?.lastOrderLatencyMs ?? "—"} ms</strong></div>
          <div className="crypto-metric"><span>Last sell latency</span><strong>{engineHealth?.lastSellLatencyMs ?? "—"} ms</strong></div>
          <div className="crypto-metric"><span>Exit pending</span><strong>{engineHealth?.exitPendingCount ?? 0}</strong></div>
          <div className="crypto-metric"><span>Audit errors</span><strong>{engineHealth?.auditWriteErrors ?? 0}</strong></div>
        </div>

        {Array.isArray(engineHealth?.reasons) && engineHealth.reasons.length > 0 && (
          <div className="crypto-warning">Attention: {engineHealth.reasons.join(" · ")}</div>
        )}
      </section>

<section className="crypto-card">
        <div className="crypto-section-heading">
          <div>
            <div className="crypto-kicker">◎ Crypto Engine Analytics</div>
            <h2>Decision Audit</h2>
            <p>Live evidence from V18.2.74+ trades. Analytics only — this panel does not change trading rules.</p>
          </div>
          <button type="button" className="crypto-secondary-button" onClick={loadDecisionAudit}>Refresh Analytics</button>
        </div>

        {decisionAuditError && (
          <div className="crypto-warning">Analytics warning: {decisionAuditError}</div>
        )}

        <div className="crypto-metric-grid">
          <div className="crypto-metric"><span>Audited trades</span><strong>{decisionAudit?.closedTrades ?? 0}</strong></div>
          <div className="crypto-metric"><span>Win rate</span><strong>{Number(decisionAudit?.winRatePct ?? 0).toFixed(1)}%</strong></div>
          <div className="crypto-metric"><span>Expectancy / trade</span><strong>${Number(decisionAudit?.expectancyUsd ?? 0).toFixed(2)}</strong></div>
          <div className="crypto-metric"><span>Audit P&amp;L</span><strong>${Number(decisionAudit?.pnlUsd ?? 0).toFixed(2)}</strong></div>
          <div className="crypto-metric"><span>Average winner</span><strong>${Number(decisionAudit?.avgWinUsd ?? 0).toFixed(2)}</strong></div>
          <div className="crypto-metric"><span>Average loser</span><strong>${Number(decisionAudit?.avgLossUsd ?? 0).toFixed(2)}</strong></div>
        </div>

        
        <div className="crypto-metric-grid">
          <div className="crypto-metric"><span>Ledger health</span><strong>{ledgerHealth?.ledgerHealthy === false ? "CHECK 🟠" : "CLEAN 🟢"}</strong></div>
          <div className="crypto-metric"><span>Logical entries</span><strong>{ledgerHealth?.logicalEntries ?? 0}</strong></div>
          <div className="crypto-metric"><span>Completed trades</span><strong>{ledgerHealth?.completedTrades ?? 0}</strong></div>
          <div className="crypto-metric"><span>Open logical trades</span><strong>{ledgerHealth?.openLogicalTrades ?? 0}</strong></div>
          <div className="crypto-metric"><span>Duplicate trade IDs</span><strong>{ledgerHealth?.duplicateCompletedTradeIds ?? 0}</strong></div>
        </div>

<div className="crypto-audit-progress">
          <div className="crypto-audit-progress-head">
            <span>Evidence sample</span>
            <strong>{decisionAudit?.closedTrades ?? 0} / {decisionAudit?.sampleTarget ?? 30}</strong>
          </div>
          <div className="crypto-audit-progress-track">
            <div className="crypto-audit-progress-fill" style={{ width: `${Math.min(100, Number(decisionAudit?.sampleProgressPct ?? 0))}%` }} />
          </div>
          <small>{decisionAudit?.sampleReady ? "Enough data to start comparing patterns cautiously." : "Collecting fresh closed trades before tuning the engine again."}</small>
        </div>

        <div className="crypto-audit-columns">
          <div className="crypto-audit-table-wrap">
            <h3>By market regime</h3>
            <table className="crypto-table">
              <thead><tr><th>Regime</th><th>Trades</th><th>Win %</th><th>P&amp;L</th><th>Avg W</th><th>Avg L</th></tr></thead>
              <tbody>
                {Object.entries(decisionAudit?.byRegime || {}).map(([name, raw]: any) => {
                  const v:any = raw;
                  return <tr key={name}><td>{String(name).toUpperCase()}</td><td>{v.trades}</td><td>{Number(v.winRatePct||0).toFixed(1)}%</td><td>${Number(v.pnlUsd||0).toFixed(2)}</td><td>${Number(v.avgWinUsd||0).toFixed(2)}</td><td>${Number(v.avgLossUsd||0).toFixed(2)}</td></tr>;
                })}
                {Object.keys(decisionAudit?.byRegime || {}).length === 0 && <tr><td colSpan={6}>No audited exits yet.</td></tr>}
              </tbody>
            </table>
          </div>

          <div className="crypto-audit-table-wrap">
            <h3>By exit reason</h3>
            <table className="crypto-table">
              <thead><tr><th>Reason</th><th>Trades</th><th>Win %</th><th>P&amp;L</th></tr></thead>
              <tbody>
                {Object.entries(decisionAudit?.byExitReason || {}).map(([name, raw]: any) => {
                  const v:any = raw;
                  return <tr key={name}><td>{name}</td><td>{v.trades}</td><td>{Number(v.winRatePct||0).toFixed(1)}%</td><td>${Number(v.pnlUsd||0).toFixed(2)}</td></tr>;
                })}
                {Object.keys(decisionAudit?.byExitReason || {}).length === 0 && <tr><td colSpan={4}>No audited exits yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>

        <div className="crypto-audit-table-wrap">
          <h3>By coin</h3>
          <table className="crypto-table">
            <thead><tr><th>Coin</th><th>Trades</th><th>Wins</th><th>Losses</th><th>Win %</th><th>P&amp;L</th><th>Avg W</th><th>Avg L</th></tr></thead>
            <tbody>
              {Object.entries(decisionAudit?.bySymbol || {})
                .sort((a:any,b:any)=>Number((b[1] as any)?.trades||0)-Number((a[1] as any)?.trades||0))
                .slice(0,20)
                .map(([name, raw]: any) => {
                  const v:any = raw;
                  return <tr key={name}><td>{name}</td><td>{v.trades}</td><td>{v.wins}</td><td>{v.losses}</td><td>{Number(v.winRatePct||0).toFixed(1)}%</td><td>${Number(v.pnlUsd||0).toFixed(2)}</td><td>${Number(v.avgWinUsd||0).toFixed(2)}</td><td>${Number(v.avgLossUsd||0).toFixed(2)}</td></tr>;
                })}
              {Object.keys(decisionAudit?.bySymbol || {}).length === 0 && <tr><td colSpan={8}>No audited exits yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

<section className="crypto-panel crypto-bridge-panel">
      <div className="crypto-panel-head">
        <div>
          <h3><span className="panel-icon">⌒</span> Crypto Bridge</h3>
          <p>Capital split is automatic: £900 is reserved for stocks, everything else outside the Piggy Bank is crypto. Crypto profits are banked one-way. Safety exits check every 5 seconds; normal decisions run every 5 minutes.</p>
        </div>
        <span className={`crypto-chip ${armed ? "live" : accountActive ? "building" : ""}`}>{armed ? "LIVE PILOT ARMED" : accountActive ? "READY TO ARM" : "CRYPTO NOT ACTIVE"}</span>
      </div>

      <div className="crypto-bridge-grid">
        <div className="bridge-metric"><span className="crypto-summary-icon vault">▣</span><div><small>Piggy Bank</small><strong>{gbp(bridge?.piggyBankGbp ?? bridge?.vaultAvailableGbp)}</strong></div></div>
        <div className="bridge-metric"><span className="crypto-summary-icon allocation">●</span><div><small>Crypto Allocation</small><strong>{gbp(bridge?.cryptoAllocatedGbp)}</strong></div></div>
        <div className="bridge-metric"><span className="crypto-summary-icon pnl">◇</span><div><small>Protected Pool</small><strong>{gbp(bridge?.cryptoPoolGbp)}</strong></div></div>
        <div className="bridge-metric"><span className="crypto-summary-icon returned">◎</span><div><small>Status</small><strong className={armed ? "gain" : ""}>{armed ? "● Armed" : "Off"}</strong></div></div>
        <div className={`bridge-action ${armed ? "allocated" : ""}`}>
          <div className="crypto-allocation-editor">
            <strong>AUTOMATIC CAPITAL SPLIT</strong>
            <small>{`${gbp(bridge?.stockCapitalReservedGbp ?? 900)} reserved for stocks · ${gbp(bridge?.cryptoAllocatedGbp)} assigned to crypto · ${gbp(bridge?.piggyBankGbp)} locked in Piggy Bank`}</small>
          </div>
        </div>
      </div>
    </section>

    <section className="crypto-footer-strip">
      <span><b>Shadow:</b> {Number(bridge?.shadowEvidence?.closedTests || data.closedTrades || 0)} tests · {money(bridge?.shadowEvidence?.totalPnlUsd ?? data.totalPnlUsd)} · win {pct(bridge?.shadowEvidence?.winRate ?? data.winRate)}</span>
      <span><b>Safety:</b> Stop {pct(data.config?.stopPct)} · Trail {pct(data.config?.trailStartPct)} / {pct(data.config?.trailGivebackPct)}</span>
      <span><b>Next live decision:</b> {fmtCountdown(nextDecisionSeconds)} · safety still checks every {Number(bridge?.safetyCheckIntervalSeconds || 5)}s</span>
      <span><b>Re-entry:</b> {Number(bridge?.reentryCooldownMinutes || 30)} min after wins · {Number(bridge?.lossCooldownMinutes || 120)} min after losses</span>
      <span><b>Loss brake:</b> {Number(bridge?.consecutiveCryptoLosses || 0)}/{Number(bridge?.lossBrakeStreak || 2)} consecutive · daily {gbp(bridge?.dailyCryptoPnlGbp)} / -{gbp(bridge?.dailyLossLimitGbp)}</span>
      <span><b>Stock engine:</b> £900 baseline and MARA rules untouched</span>
    </section>
  </div>;
}
