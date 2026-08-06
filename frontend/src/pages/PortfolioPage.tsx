import { useCallback, useEffect, useMemo, useState } from "react";
import { Card } from "../components/Card";
import { API_URL, readJson } from "../lib/api";
import { gbp, pct, usd } from "../lib/format";
import type { AnyObj } from "../lib/types";

function decisionLabel(value: string) {
  if (value === "QUALIFIED") return "QUALIFIED";
  if (value === "QUALIFIED_WAITING") return "WAITING";
  return "REJECTED";
}

function decisionClass(value: string) {
  if (value === "QUALIFIED") return "profit";
  if (value === "QUALIFIED_WAITING") return "notice";
  return "loss";
}

function factorSummary(row: AnyObj) {
  const values = row?.factors?.values || {};
  const parts = [
    ["MOM", values.momentum],
    ["RS", values.relativeStrength],
    ["LIQ", values.liquidity],
    ["VOL", values.volatilityQuality],
    ["HIST", values.historicalEdge],
    ["REG", values.regimeFit],
  ];
  return <div style={{ minWidth: 250, lineHeight: 1.55 }}>
    {parts.map(([label, value]) => <span key={String(label)} style={{ display: "inline-block", marginRight: 10, whiteSpace: "nowrap" }}>
      <b>{label}</b> {Number(value || 0).toFixed(2)}
    </span>)}
  </div>;
}

export function PortfolioPage({ authToken }: { authToken: string }) {
  const [plan, setPlan] = useState<AnyObj>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("ALL");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/v16/portfolio/status`, {
        cache: "no-store",
        headers: { "X-Auth-Token": authToken, "x-api-key": authToken },
      });
      const json = await readJson(response);
      if (!response.ok) throw new Error(json?.detail || json?.message || `HTTP ${response.status}`);
      setPlan(json || {});
    } catch (e: any) {
      setError(e?.message || "Portfolio plan unavailable");
    } finally {
      setLoading(false);
    }
  }, [authToken]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 30000);
    return () => window.clearInterval(id);
  }, [load]);

  const rows = Array.isArray(plan?.allocations) ? plan.allocations : [];
  const decisions = Array.isArray(plan?.decisions) ? plan.decisions : [];
  const filteredDecisions = useMemo(() => {
    if (filter === "ALL") return decisions;
    if (filter === "QUALIFIED") return decisions.filter((row: AnyObj) => row.decision === "QUALIFIED");
    if (filter === "WAITING") return decisions.filter((row: AnyObj) => row.decision === "QUALIFIED_WAITING");
    return decisions.filter((row: AnyObj) => row.decision === "REJECTED");
  }, [decisions, filter]);

  return <main className="grid two">
    <Card title="AI Portfolio Brain" wide>
      <div className="actions">
        <button onClick={load} disabled={loading}>{loading ? "Loading..." : "Refresh Plan"}</button>
      </div>
      {error && <p className="notice loss">{error}</p>}
      <div className="summary">
        <div><span>Status</span><b>{plan?.status || "WAITING"}</b></div>
        <div><span>Scanned</span><b>{Number(plan?.candidateCount || 0)}</b></div>
        <div><span>Qualified</span><b>{Number(plan?.qualifiedCount || 0)}</b></div>
        <div><span>Rejected</span><b>{Number(plan?.rejectedCount || 0)}</b></div>
        <div><span>Actionable</span><b>{Number(plan?.actionableCount || 0)} / {Number(plan?.orderLimit || 0)}</b></div>
        <div><span>Effective minimum</span><b>{Number(plan?.minimumPortfolioScore || 0).toFixed(3)}</b></div>
        <div><span>Base minimum</span><b>{Number(plan?.baseMinimumPortfolioScore || plan?.minimumPortfolioScore || 0).toFixed(3)}</b></div>
        <div><span>Threshold mode</span><b>{String(plan?.thresholdMode || "BASE").replaceAll("_", " ")}</b></div>
        <div><span>Deploy</span><b>{gbp(plan?.deployableGbp)} / {usd(plan?.deployableUsd)}</b></div>
        <div><span>Cash reserve</span><b>{pct(plan?.cashReservePct)} · {gbp(plan?.cashReserveGbp)}</b></div>
        <div><span>Managed capital</span><b>{gbp(plan?.managedCapitalGbp)} / {usd(plan?.managedCapitalUsd)}</b></div>
      </div>
      <p className="notice">{plan?.explanation || "The AI will publish its next score-weighted portfolio plan when qualified candidates are available."}</p>
      <p className="muted">{plan?.allocationMethod}</p>
    </Card>

    <Card title="Planned Allocations" wide>
      <div className="table-wrap"><table><thead><tr><th>Rank</th><th>Symbol</th><th>Portfolio score</th><th>Confidence</th><th>Quality</th><th>Allocation</th><th>Share deployed</th><th>Why</th></tr></thead>
      <tbody>{rows.map((row: AnyObj) => <tr key={`${row.rank}-${row.symbol}`}><td>#{row.rank}</td><td><b>{row.symbol}</b></td><td>{Number(row.portfolioScore || 0).toFixed(3)}</td><td>{pct(Number(row.confidence || 0) * 100)}</td><td>{Number(row.quality || 0).toFixed(4)}</td><td>{gbp(row.notionalGbp)} / {usd(row.notionalUsd)}</td><td>{pct(row.shareOfDeployedPct)}</td><td>{row.reason}</td></tr>)}{!rows.length && <tr><td colSpan={8}>No allocation has passed all requirements yet. See the Decision Inspector below.</td></tr>}</tbody></table></div>
    </Card>

    <Card title="AI Decision Inspector" wide>
      <div className="actions">
        {(["ALL", "QUALIFIED", "WAITING", "REJECTED"] as const).map((value) =>
          <button key={value} onClick={() => setFilter(value)} disabled={filter === value}>{value}</button>
        )}
      </div>
      <p className="muted">Every candidate now shows its six-factor V16.4 score: momentum, relative strength, liquidity, volatility quality, historical edge and market-regime fit.</p>
      <div className="table-wrap"><table><thead><tr><th>Rank</th><th>Symbol</th><th>Decision</th><th>Calibrated</th><th>Raw</th><th>Minimum</th><th>Confidence</th><th>Quality</th><th>Spread</th><th>Factor breakdown</th><th>Exact reason</th></tr></thead>
      <tbody>{filteredDecisions.map((row: AnyObj, index: number) => <tr key={`${row.symbol}-${row.scanIndex}-${index}`}>
        <td>{row.rank ? `#${row.rank}` : "—"}</td>
        <td><b>{row.symbol || "UNKNOWN"}</b></td>
        <td><b className={decisionClass(String(row.decision || "REJECTED"))}>{decisionLabel(String(row.decision || "REJECTED"))}</b></td>
        <td>{Number(row.portfolioScore || 0).toFixed(3)}</td>
        <td>{Number(row.rawPortfolioScore ?? row.portfolioScore ?? 0).toFixed(3)}</td>
        <td>{Number(row.minimumScore || plan?.minimumPortfolioScore || 0).toFixed(3)}</td>
        <td>{pct(Number(row.confidence || 0) * 100)}</td>
        <td>{Number(row.quality || 0).toFixed(4)}</td>
        <td>{Number(row.spread || 0).toFixed(5)}</td>
        <td>{factorSummary(row)}</td>
        <td>{row.reason || row.reasonCode || "No reason supplied"}</td>
      </tr>)}{!filteredDecisions.length && <tr><td colSpan={11}>{loading ? "Loading scanner decisions..." : "No scanner decisions are available yet."}</td></tr>}</tbody></table></div>
    </Card>
  </main>;
}
