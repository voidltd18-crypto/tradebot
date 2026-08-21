import { useState } from "react";
import { Card } from "../components/Card";
import { TradeReplayModal, type ReplayTarget } from "../components/TradeReplayModal";
import { gbp, pct, tone, usd } from "../lib/format";
import type { ActionFn, AnyObj, PositionStyleFn } from "../lib/types";

export function PositionsPage({ positions, rate, action, positionGlowStyle, authToken }: { positions: AnyObj[]; rate: number; action: ActionFn; positionGlowStyle: PositionStyleFn; authToken: string }) {
  const [replay, setReplay] = useState<ReplayTarget | null>(null);
  return <>
    <Card title="Open Positions — Best to Worst"><p className="muted">Your live holdings, sorted by performance. Price movement is recorded automatically for Trade Replay.</p><div className="position-list">{positions.map((position) => <article className="position" key={position.symbol} style={positionGlowStyle(position)}><div><h3>{position.symbol}</h3><p>Qty {Number(position.qty || 0).toFixed(4)} · Entry {usd(position.entry)} · Price {usd(position.price)}</p><p>Value <b>{gbp(position.marketValueGbp ?? Number(position.marketValue || 0) * rate)}</b> / {usd(position.marketValue)}</p></div><div className="position-side"><b className={tone(position.pnl)}>PnL {gbp(position.pnlGbp ?? Number(position.pnl || 0) * rate)} / {usd(position.pnl)} / {pct(position.pnlPct)}</b><span>{position.runnerGraceActive
  ? `Runner grace ${Number(position.runnerGraceCheck || 1)}/${Number(position.runnerGraceRequired || 2)} · floor ${usd(position.trailFloor)}`
  : (position.peakExhaustionArmed
      ? `Peak exhaustion ARMED ${Number(position.peakExhaustionTouches || 0)}/${Number(position.peakExhaustionRequired || 4)} · peak ${usd(position.peakExhaustionPeak)}`
      : (Number(position.peakExhaustionTouches || 0) > 0
          ? `Peak tests ${Number(position.peakExhaustionTouches || 0)}/${Number(position.peakExhaustionRequired || 4)} · peak ${usd(position.peakExhaustionPeak)}`
          : (position.trailingActive ? `Trailing floor ${usd(position.trailFloor)}` : `Trail starts ${usd(position.trailStartPrice)}`)))}</span><div className="position-actions"><button onClick={() => setReplay({ mode: "live", symbol: String(position.symbol) })}>View Chart</button><button className="danger" onClick={() => action(`/sell/${position.symbol}`)}>Sell {position.symbol}</button></div></div></article>)}{!positions.length && <p className="muted">No open positions.</p>}</div></Card>
    <TradeReplayModal target={replay} authToken={authToken} onClose={() => setReplay(null)} />
  </>;
}
