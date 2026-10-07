import { useEffect, useState } from "react";
import { Card } from "../components/Card";
import { TradeReplayModal, type ReplayTarget } from "../components/TradeReplayModal";
import { gbp, pct, tone, usd } from "../lib/format";
import { API_URL } from "../lib/api";
import type { ActionFn, AnyObj, PositionStyleFn } from "../lib/types";

export function PositionsPage({ positions, rate, action, positionGlowStyle, authToken }: { positions: AnyObj[]; rate: number; action: ActionFn; positionGlowStyle: PositionStyleFn; authToken: string }) {
  const [replay, setReplay] = useState<ReplayTarget | null>(null);
  const [aiExit, setAiExit] = useState<AnyObj | null>(null);
  const [aiOutcome, setAiOutcome] = useState<AnyObj | null>(null);
  const [aiLearning, setAiLearning] = useState<AnyObj | null>(null);
  const [aiPilot, setAiPilot] = useState<AnyObj | null>(null);
  const [aiGuardian, setAiGuardian] = useState<AnyObj | null>(null);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [res, outcomeRes, learningRes, pilotRes, guardianRes] = await Promise.all([
          fetch(`${API_URL}/v18/ai-exit-manager?limit=30`, { headers: { "X-API-Key": authToken, "X-Auth-Token": authToken } }),
          fetch(`${API_URL}/v18/ai-exit-outcomes`, { headers: { "X-API-Key": authToken, "X-Auth-Token": authToken } }),
          fetch(`${API_URL}/v18/ai-exit-learning`, { headers: { "X-API-Key": authToken, "X-Auth-Token": authToken } }),
          fetch(`${API_URL}/v18/ai-exit-pilot`, { headers: { "X-API-Key": authToken, "X-Auth-Token": authToken } }),
          fetch(`${API_URL}/v18/ai-exit-pilot-guardian`, { headers: { "X-API-Key": authToken, "X-Auth-Token": authToken } }),
        ]);
        const [body, outcomeBody, learningBody, pilotBody, guardianBody] = await Promise.all([res.json(), outcomeRes.json(), learningRes.json(), pilotRes.json(), guardianRes.json()]);
        if (alive && res.ok) setAiExit(body);
        if (alive && outcomeRes.ok) setAiOutcome(outcomeBody);
        if (alive && learningRes.ok) setAiLearning(learningBody);
        if (alive && pilotRes.ok) setAiPilot(pilotBody);
        if (alive && guardianRes.ok) setAiGuardian(guardianBody);
      } catch {}
    };
    load();
    const id = window.setInterval(load, 10000);
    return () => { alive = false; window.clearInterval(id); };
  }, [authToken]);
  const aiDecisionFor = (symbol: string) => (Array.isArray(aiExit?.decisions) ? aiExit.decisions : []).find((d:AnyObj) => String(d.symbol || "").toUpperCase() === String(symbol || "").toUpperCase());
  return <>
    <Card title="AI Exit Manager · Shadow"><p className="muted">Autonomous HOLD / PROTECT / EXIT decisions are being recorded every 10 seconds. Shadow only — the AI cannot submit a sell order yet.</p><div className="summary"><div><span>Mode</span><b>{aiExit?.mode || "SHADOW"}</b></div><div><span>Live authority</span><b>{aiExit?.liveAuthority ? "ON" : "OFF"}</b></div><div><span>Cycles</span><b>{Number(aiExit?.cycles || 0).toLocaleString("en-GB")}</b></div><div><span>Positions watched</span><b>{Number(aiExit?.positionsSeen || 0)}</b></div></div></Card>
    <Card title="AI Exit Outcome Scorer"><p className="muted">Scores each sampled Shadow decision against what actually happens 5, 15, 30 and 60 trading minutes later. Research only.</p><div className="summary"><div><span>Anchors</span><b>{Number(aiOutcome?.anchors || 0)}</b></div><div><span>Outcomes scored</span><b>{Number(aiOutcome?.outcomes || 0)}</b></div><div><span>30m accuracy</span><b>{Number((Array.isArray(aiOutcome?.byHorizon) ? aiOutcome.byHorizon : []).find((x:AnyObj) => Number(x.horizonMin) === 30)?.decisionAccuracyPct || 0).toFixed(1)}%</b></div><div><span>30m edge</span><b>{Number((Array.isArray(aiOutcome?.byHorizon) ? aiOutcome.byHorizon : []).find((x:AnyObj) => Number(x.horizonMin) === 30)?.avgDecisionEdgePct || 0).toFixed(2)}%</b></div><div><span>Pilot gate</span><b>{aiOutcome?.pilotEligible ? "QUALIFIED" : "COLLECTING"}</b></div><div><span>Live authority</span><b>OFF</b></div></div></Card>
    <Card title="AI Exit Learner"><p className="muted">Learns small bounded HOLD / PROTECT / EXIT calibration biases from scored 30-minute outcomes. Shadow only.</p><div className="summary"><div><span>Learning mode</span><b>{aiLearning?.mode || "SHADOW_LEARNING"}</b></div><div><span>Qualified buckets</span><b>{Number(aiLearning?.qualifiedBuckets || 0)}</b></div><div><span>Max adjustment</span><b>±8 points</b></div><div><span>Minimum per bucket</span><b>12 samples</b></div><div><span>Live authority</span><b>OFF</b></div></div></Card>
    <Card title="AI Exit Live Pilot"><p className="muted">The bridge to live AI-controlled selling. It stays OFF until both the evidence gate qualifies and the pilot is explicitly enabled.</p><div className="summary"><div><span>Pilot enabled</span><b>{aiPilot?.pilotEnabled ? "YES" : "NO"}</b></div><div><span>Evidence qualified</span><b>{aiPilot?.pilotEligible ? "YES" : "NO"}</b></div><div><span>Live authority</span><b>{aiPilot?.liveAuthority ? "ON" : "OFF"}</b></div><div><span>Min confidence</span><b>{Number(aiPilot?.minDecisionConfidencePct || 75).toFixed(0)}%</b></div><div><span>Confirmations</span><b>{Number(aiPilot?.requiredConsecutiveExit || 2)}</b></div><div><span>AI exits today</span><b>{Number(aiPilot?.aiExitsToday || 0)} / {Number(aiPilot?.maxAiExitsPerDay || 1)}</b></div></div></Card>
    <Card title="AI Exit Pilot Guardian"><p className="muted">Every future live AI exit is quarantined for a 30-open-minute review before another AI exit can happen.</p><div className="summary"><div><span>Guardian state</span><b>{aiGuardian?.state || "READY"}</b></div><div><span>Pending review</span><b>{aiGuardian?.pendingReview ? "YES" : "NO"}</b></div><div><span>Suspended</span><b>{aiGuardian?.suspended ? "YES" : "NO"}</b></div><div><span>Review window</span><b>{Number(aiGuardian?.reviewOpenMinutes || 30)}m</b></div><div><span>Bad-exit trigger</span><b>+{Number(aiGuardian?.badExitThresholdPct || 0.3).toFixed(2)}%</b></div><div><span>Last verdict</span><b>{aiGuardian?.lastReview?.verdict || "—"}</b></div></div>{aiGuardian?.suspensionReason && <p className="notice">{String(aiGuardian.suspensionReason)}</p>}</Card>
    <Card title="Open Positions — Best to Worst"><p className="muted">Your live holdings, sorted by performance. Price movement is recorded automatically for Trade Replay.</p><div className="position-list">{positions.map((position) => { const ai = aiDecisionFor(String(position.symbol)); return <article className="position" key={position.symbol} style={positionGlowStyle(position)}><div><h3>{position.symbol}</h3><p>Qty {Number(position.qty || 0).toFixed(4)} · Entry {usd(position.entry)} · Price {usd(position.price)}</p><p>Value <b>{gbp(position.marketValueGbp ?? Number(position.marketValue || 0) * rate)}</b> / {usd(position.marketValue)}</p></div><div className="position-side"><b className={tone(position.pnl)}>PnL {gbp(position.pnlGbp ?? Number(position.pnl || 0) * rate)} / {usd(position.pnl)} / {pct(position.pnlPct)}</b><span>{position.runnerGraceActive
  ? `Runner grace ${Number(position.runnerGraceCheck || 1)}/${Number(position.runnerGraceRequired || 2)} · floor ${usd(position.trailFloor)}`
  : (position.peakExhaustionArmed
      ? `Peak exhaustion ARMED ${Number(position.peakExhaustionTouches || 0)}/${Number(position.peakExhaustionRequired || 4)} · peak ${usd(position.peakExhaustionPeak)}`
      : (Number(position.peakExhaustionTouches || 0) > 0
          ? `Peak tests ${Number(position.peakExhaustionTouches || 0)}/${Number(position.peakExhaustionRequired || 4)} · peak ${usd(position.peakExhaustionPeak)}`
          : (position.trailingActive ? `Trailing floor ${usd(position.trailFloor)}` : `Trail starts ${usd(position.trailStartPrice)}`)))}</span><div className="position-actions"><button onClick={() => setReplay({ mode: "live", symbol: String(position.symbol) })}>View Chart</button><button className="danger" onClick={() => action(`/sell/${position.symbol}`)}>Sell {position.symbol}</button></div>{ai && <p className="muted"><b>AI Shadow: {String(ai.action || "HOLD")}</b> · {Number(ai.decisionConfidencePct || 0).toFixed(0)}% decision confidence · {Array.isArray(ai.reasons) ? ai.reasons.slice(0,2).join(" · ") : ""}</p>}</div></article>; })}{!positions.length && <p className="muted">No open positions.</p>}</div></Card>
    <TradeReplayModal target={replay} authToken={authToken} onClose={() => setReplay(null)} />
  </>;
}
