import { useEffect, useMemo, useState } from "react";
import { API_URL } from "../lib/api";
import type { AnyObj } from "../lib/types";

const money = (n: unknown) => `$${Number(n || 0).toFixed(2)}`;
const pct = (n: unknown) => `${Number(n || 0).toFixed(2)}%`;

function scoreState(score: number, threshold: number) {
  if (score >= Math.max(0.60, threshold - 0.08)) return { label: "NEAR ENTRY", cls: "near" };
  if (score >= 0.50) return { label: "BUILDING", cls: "building" };
  return { label: "WATCHING", cls: "watching" };
}

function fmtCountdown(seconds: number) {
  const total = Math.max(0, Math.floor(seconds));
  const mm = Math.floor(total / 60);
  const ss = total % 60;
  return `${mm}:${String(ss).padStart(2, "0")}`;
}

export function CryptoScannerPopoutPage({ authToken }: { authToken: string }) {
  const [data, setData] = useState<AnyObj | null>(null);
  const [bridge, setBridge] = useState<AnyObj | null>(null);
  const [error, setError] = useState("");
  const [clockTick, setClockTick] = useState(0);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const headers = { "X-API-Key": authToken, "X-Auth-Token": authToken, "x-api-key": authToken };
        const [shadowRes, bridgeRes] = await Promise.all([
          fetch(`${API_URL}/v18/crypto-shadow`, { cache: "no-store", headers }),
          fetch(`${API_URL}/v18/crypto-bridge`, { cache: "no-store", headers }),
        ]);
        const shadowBody = await shadowRes.json();
        const bridgeBody = await bridgeRes.json();
        if (!shadowRes.ok) throw new Error(shadowBody?.detail || `Scanner HTTP ${shadowRes.status}`);
        if (!bridgeRes.ok) throw new Error(bridgeBody?.detail || `Bridge HTTP ${bridgeRes.status}`);
        if (!alive) return;
        setData(shadowBody);
        setBridge({ ...bridgeBody, __fetchedAt: Date.now() });
        setError("");
      } catch (e: any) {
        if (alive) setError(e?.message || "Scanner unavailable");
      }
    };
    load();
    const refreshId = window.setInterval(load, 15000);
    const tickId = window.setInterval(() => setClockTick(v => v + 1), 1000);
    return () => {
      alive = false;
      window.clearInterval(refreshId);
      window.clearInterval(tickId);
    };
  }, [authToken]);

  const scans = useMemo(() => {
    const rows = Array.isArray(data?.scans) ? [...data.scans] : [];
    return rows.sort((a: AnyObj, b: AnyObj) =>
      Number(Boolean(b?.qualified)) - Number(Boolean(a?.qualified)) ||
      Number(b?.score || 0) - Number(a?.score || 0)
    );
  }, [data]);

  if (!data) {
    return <main className="crypto-lab-page crypto-scanner-popout"><section className="crypto-panel"><strong>Crypto Scanner</strong><p className="muted">{error || "Loading scanner…"}</p></section></main>;
  }

  const entryScore = Number(data?.config?.entryScore || 0.34);
  const fetchedAt = Number(bridge?.__fetchedAt || 0);
  const elapsed = fetchedAt ? Math.max(0, Math.floor((Date.now() - fetchedAt) / 1000)) : 0;
  void clockTick;
  const nextDecisionSeconds = Math.max(0, Number(bridge?.nextNormalDecisionInSeconds || 0) - elapsed);

  return <main className="crypto-lab-page crypto-scanner-popout">
    <section className="crypto-panel crypto-scanner-panel">
      <div className="crypto-panel-head">
        <div>
          <h3><span className="panel-icon">◈</span> Crypto Scanner · Pop-out</h3>
          <p>Live scanner-only view. Refreshes every 15 seconds so this window can stay open beside the main TradeBot dashboard.</p>
        </div>
        <div className="scanner-state">
          <span className="crypto-chip">{Number(data?.marketDiscovery?.discovered || scans.length)} discovered</span>
          <span className="crypto-chip">{Number(data?.marketDiscovery?.eligible || scans.filter((s: AnyObj) => s.liquid !== false).length)} liquid</span>
          <span className="crypto-chip">{scans.filter((s: AnyObj) => Boolean(s.qualified)).length} qualified</span>
          <span className="crypto-chip crypto-countdown-chip">NEXT DECISION {fmtCountdown(nextDecisionSeconds)}</span>
          <span className="crypto-chip crypto-cycle-chip">CYCLES {Number(bridge?.normalDecisionCycleCount || 0)}</span>
          <span className="scanning-dot">●</span><span>Dynamic</span>
        </div>
      </div>

      <div className="crypto-table-wrap">
        <table className="crypto-scanner-table">
          <thead><tr><th>Symbol</th><th>Price</th><th>Score</th><th>15m</th><th>60m</th><th>60m Range</th><th>Liquidity</th><th>Status</th></tr></thead>
          <tbody>{scans.map((s: AnyObj) => {
            const score = Number(s.score || 0);
            const min15 = Number(bridge?.min15mMomentumPct ?? -0.10);
            const min60 = Number(bridge?.min60mMomentumPct ?? 0.00);
            const ret15 = Number(s.return15mPct || 0);
            const ret60 = Number(s.return60mPct || 0);
            const backendQualified = Boolean(s.qualified);
            let state = scoreState(score, entryScore);
            if (s.liquid === false) state = { label: "BLOCKED · THIN LIQUIDITY", cls: "watching" };
            else if (score < entryScore) state = { label: `BLOCKED · SCORE ${score.toFixed(3)} < ${entryScore.toFixed(2)}`, cls: "watching" };
            else if (ret15 < min15) state = { label: `BLOCKED · 15m ${ret15.toFixed(2)}% < ${min15.toFixed(2)}%`, cls: "watching" };
            else if (ret60 < min60) state = { label: `BLOCKED · 60m ${ret60.toFixed(2)}% < ${min60.toFixed(2)}%`, cls: "watching" };
            else if (backendQualified) state = { label: nextDecisionSeconds > 0 ? `QUALIFIED · ${fmtCountdown(nextDecisionSeconds)}` : "QUALIFIED · DUE", cls: "qualified" };
            else state = { label: "BLOCKED · BACKEND GATE", cls: "watching" };

            const progress = Math.max(4, Math.min(100, (score / entryScore) * 100));
            return <tr key={s.symbol} className={backendQualified ? "qualified-row" : ""}>
              <td><strong>{s.symbol}</strong></td>
              <td>{money(s.price)}</td>
              <td><span className={`score-badge ${state.cls}`}>{score.toFixed(3)}</span></td>
              <td className={ret15 >= 0 ? "gain" : "loss"}>{pct(ret15)}</td>
              <td className={ret60 >= 0 ? "gain" : "loss"}>{pct(ret60)}</td>
              <td>{pct(s.range60mPct)}</td>
              <td><span className={s.liquid === false ? "loss" : "gain"}>{money(s.liquidity60mUsd)}</span><small style={{display:"block",opacity:.7}}>{s.liquid === false ? "THIN" : "LIQUID"}</small></td>
              <td><div className="crypto-status-cell"><span className={`crypto-chip ${state.cls}`}>{state.label}</span><span className="score-track"><span style={{ width: `${progress}%` }} /></span></div></td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      {error && <div className="crypto-warning">Last refresh warning: {error}</div>}
      {data?.lastError && <div className="crypto-warning">Engine warning: {data.lastError}</div>}
    </section>
  </main>;
}
