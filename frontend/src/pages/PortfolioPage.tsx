import { useCallback, useEffect, useState } from "react";
import { Card } from "../components/Card";
import { API_URL, readJson } from "../lib/api";
import { gbp, pct, usd } from "../lib/format";
import type { AnyObj } from "../lib/types";

export function PortfolioPage({ authToken }: { authToken: string }) {
  const [plan, setPlan] = useState<AnyObj>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API_URL}/v16/portfolio/status`, { cache: "no-store", headers: { "X-Auth-Token": authToken, "x-api-key": authToken } });
      const json = await readJson(response);
      if (!response.ok) throw new Error(json?.detail || json?.message || `HTTP ${response.status}`);
      setPlan(json || {});
    } catch (e:any) { setError(e?.message || "Portfolio plan unavailable"); }
    finally { setLoading(false); }
  }, [authToken]);
  useEffect(() => { load(); const id = window.setInterval(load, 30000); return () => window.clearInterval(id); }, [load]);
  const rows = Array.isArray(plan?.allocations) ? plan.allocations : [];
  return <main className="grid two">
    <Card title="AI Portfolio Brain" wide>
      <div className="actions"><button onClick={load} disabled={loading}>{loading ? "Loading..." : "Refresh Plan"}</button></div>
      {error && <p className="notice loss">{error}</p>}
      <div className="summary">
        <div><span>Status</span><b>{plan?.status || "WAITING"}</b></div>
        <div><span>Qualified</span><b>{Number(plan?.qualifiedCount || 0)}</b></div>
        <div><span>Deploy</span><b>{gbp(plan?.deployableGbp)} / {usd(plan?.deployableUsd)}</b></div>
        <div><span>Cash reserve</span><b>{pct(plan?.cashReservePct)} · {gbp(plan?.cashReserveGbp)}</b></div>
        <div><span>Managed capital</span><b>{gbp(plan?.managedCapitalGbp)} / {usd(plan?.managedCapitalUsd)}</b></div>
      </div>
      <p className="notice">{plan?.explanation || "The AI will publish its next score-weighted portfolio plan when qualified candidates are available."}</p>
      <p className="muted">{plan?.allocationMethod}</p>
    </Card>
    <Card title="Planned Allocations" wide>
      <div className="table-wrap"><table><thead><tr><th>Rank</th><th>Symbol</th><th>Portfolio score</th><th>Confidence</th><th>Quality</th><th>Allocation</th><th>Share deployed</th><th>Why</th></tr></thead>
      <tbody>{rows.map((row:AnyObj) => <tr key={`${row.rank}-${row.symbol}`}><td>#{row.rank}</td><td><b>{row.symbol}</b></td><td>{Number(row.portfolioScore || 0).toFixed(3)}</td><td>{pct(Number(row.confidence || 0) * 100)}</td><td>{Number(row.quality || 0).toFixed(4)}</td><td>{gbp(row.notionalGbp)} / {usd(row.notionalUsd)}</td><td>{pct(row.shareOfDeployedPct)}</td><td>{row.reason}</td></tr>)}{!rows.length && <tr><td colSpan={8}>No active portfolio plan yet.</td></tr>}</tbody></table></div>
    </Card>
  </main>;
}
