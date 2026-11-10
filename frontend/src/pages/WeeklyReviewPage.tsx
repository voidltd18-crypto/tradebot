import { useCallback, useEffect, useState } from "react";
import { Card } from "../components/Card";
import { API_URL, readJson } from "../lib/api";
import type { AnyObj } from "../lib/types";

export function WeeklyReviewPage({ authToken }:{authToken:string}) {
  const [data,setData]=useState<AnyObj>({}); const [loading,setLoading]=useState(true); const [error,setError]=useState("");
  const load=useCallback(async()=>{setLoading(true);setError("");try{const r=await fetch(`${API_URL}/v18/weekly-review?days=7`,{cache:"no-store",headers:{"X-Auth-Token":authToken,"x-api-key":authToken}});const j=await readJson(r);if(!r.ok||j?.ok===false)throw new Error(j?.detail||j?.error||`HTTP ${r.status}`);setData(j||{});}catch(e:any){setError(e?.message||"Weekly review unavailable");}finally{setLoading(false);}},[authToken]);
  useEffect(()=>{load();},[load]);
  const gates=Array.isArray(data?.gates)?data.gates:[]; const p=data?.proposal||{}; const e=data?.evidence||{};
  return <main className="grid two">
    <Card title="V18 Autonomous Weekly Review" wide><div className="actions"><button onClick={load} disabled={loading}>{loading?"Reviewing...":"Refresh Weekly Review"}</button></div>{error&&<p className="notice loss">{error}</p>}<div className="summary"><div><span>Verdict</span><b>{data?.verdict||"—"}</b></div><div><span>Evidence</span><b>{data?.evidenceStrength||"—"}</b></div><div><span>Audited decisions</span><b>{Number(e?.auditedDecisions||0)} / {Number(e?.minimumAuditedDecisions||20)}</b></div><div><span>Pending checkpoints</span><b>{Number(e?.pendingCheckpoints||0)}</b></div></div><p className="notice">Governance only. V18 can identify evidence-backed candidates, but it cannot directly change live trading rules or remove constitutional safety protections.</p></Card>
    <Card title="Weekly Gate Review" wide><div className="table-wrap"><table><thead><tr><th>Gate</th><th>Evidence</th><th>Good blocks</th><th>Missed winners</th><th>Neutral</th><th>Effectiveness</th><th>Action</th></tr></thead><tbody>{gates.map((g:AnyObj)=><tr key={g.stage}><td><b>{String(g.stage||"unknown").toUpperCase()}</b></td><td>{g.classified}</td><td>{g.good_blocks}</td><td>{g.missed_winners}</td><td>{g.neutral}</td><td>{Number(g.effectivenessPct||0).toFixed(1)}%</td><td><b>{g.action}</b></td></tr>)}{!gates.length&&<tr><td colSpan={7}>V17.9 is still collecting enough live rejection evidence for the first review.</td></tr>}</tbody></table></div></Card>
    <Card title="Governance Proposal"><div className="summary"><div><span>Action</span><b>{p?.action||"OBSERVE"}</b></div><div><span>Stability</span><b>{Number(p?.stabilityCount||0)} / {Number(p?.stabilityRequired||5)}</b></div><div><span>Board eligible</span><b>{p?.promotionEligible?"YES":"NO"}</b></div></div><p>{p?.text||"Waiting for sufficient evidence."}</p></Card>
    <Card title="Constitutional Locks"><div className="tags">{(Array.isArray(data?.constitutionalLocks)?data.constitutionalLocks:[]).map((x:string)=><span className="tag" key={x}>{x.replaceAll("_"," ")}</span>)}</div><p className="muted">These protections are outside V18's autonomous optimisation authority.</p></Card>
  </main>;
}
