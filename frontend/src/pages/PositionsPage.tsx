import { useEffect, useState } from "react";
import { Card } from "../components/Card";
import { TradeReplayModal, type ReplayTarget } from "../components/TradeReplayModal";
import { gbp, pct, tone, usd } from "../lib/format";
import { API_URL } from "../lib/api";
import type { ActionFn, AnyObj, PositionStyleFn } from "../lib/types";

export function PositionsPage({ positions, rate, action, positionGlowStyle, authToken }: { positions: AnyObj[]; rate: number; action: ActionFn; positionGlowStyle: PositionStyleFn; authToken: string }) {
  const [replay, setReplay] = useState<ReplayTarget | null>(null);
  const [aiExit, setAiExit] = useState<AnyObj | null>(null);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch(`${API_URL}/v18/ai-exit-manager?limit=30`, { headers: { "X-API-Key": authToken, "X-Auth-Token": authToken } });
        const body = await res.json();
        if (alive && res.ok) setAiExit(body);
      } catch {}
    };
    load();
    const id = window.setInterval(load, 10000);
    return () => { alive = false; window.clearInterval(id); };
  }, [authToken]);
  const aiDecisionFor = (symbol: string) => (Array.isArray(aiExit?.decisions) ? aiExit.decisions : []).find((d:AnyObj) => String(d.symbol || "").toUpperCase() === String(symbol || "").toUpperCase());
  return <>
    <Card title="AI Exit Manager · Shadow"><p className="muted">Autonomous HOLD / PROTECT / EXIT decisions are being recorded every 10 seconds. Shadow only — the AI cannot submit a sell order yet.</p><div className="summary"><div><span>Mode</span><b>{aiExit?.mode || "SHADOW"}</b></div><div><span>Live authority</span><b>{aiExit?.liveAuthority ? "ON" : "OFF"}</b></div><div><span>Cycles</span><b>{Number(aiExit?.cycles || 0).toLocaleString("en-GB")}</b></div><div><span>Positions watched</span><b>{Number(aiExit?.positionsSeen || 0)}</b></div></div></Card>
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
