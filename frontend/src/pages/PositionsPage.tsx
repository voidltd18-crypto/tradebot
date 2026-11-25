import { useState } from "react";
import { Card } from "../components/Card";
import { TradeReplayModal, type ReplayTarget } from "../components/TradeReplayModal";
import { gbp, pct, tone, usd, positionQuantity, isSmallCryptoResidual } from "../lib/format";
import type { AnyObj, PositionStyleFn } from "../lib/types";

export function PositionsPage({ positions, rate, positionGlowStyle, authToken }: { positions: AnyObj[]; rate: number; positionGlowStyle: PositionStyleFn; authToken: string }) {
  const [replay, setReplay] = useState<ReplayTarget | null>(null);
  const cryptoPositions = positions.filter(position => position.assetClass === "crypto");
  const otherPositions = positions.filter(position => position.assetClass !== "crypto");
  return <>
    <Card title="Open Positions — Best to Worst"><p className="muted">Your live holdings, sorted by performance. Price movement is recorded automatically for Trade Replay.</p><div className="position-list">{otherPositions.map((position) => <article className="position" key={position.symbol} style={positionGlowStyle(position)}><div><h3>{position.symbol}</h3><p>Qty {positionQuantity(position)} · Entry {usd(position.entry)} · Price {usd(position.price)}{isSmallCryptoResidual(position) ? " · Small residual holding (still at Alpaca)" : ""}</p><p>Value <b>{gbp(position.marketValueGbp ?? Number(position.marketValue || 0) * rate)}</b> / {usd(position.marketValue)}</p></div><div className="position-side"><b className={tone(position.pnl)}>PnL {gbp(position.pnlGbp ?? Number(position.pnl || 0) * rate)} / {usd(position.pnl)} / {pct(position.pnlPct)}</b><span>{position.runnerGraceActive
  ? `Runner grace ${Number(position.runnerGraceCheck || 1)}/${Number(position.runnerGraceRequired || 2)} · floor ${usd(position.trailFloor)}`
  : (position.peakExhaustionArmed
      ? `Peak exhaustion ARMED ${Number(position.peakExhaustionTouches || 0)}/${Number(position.peakExhaustionRequired || 4)} · peak ${usd(position.peakExhaustionPeak)}`
      : (Number(position.peakExhaustionTouches || 0) > 0
          ? `Peak tests ${Number(position.peakExhaustionTouches || 0)}/${Number(position.peakExhaustionRequired || 4)} · peak ${usd(position.peakExhaustionPeak)}`
          : (position.trailingActive ? `Trailing floor ${usd(position.trailFloor)}` : `Trail starts ${usd(position.trailStartPrice)}`)))}</span>
      {position.sellPreview && <div>
        <b>Sell preview · {position.sellPreview.action}</b>
        <p>{position.sellPreview.reason}</p>
        {position.sellPreview.thresholdSignal && <p>Price level reached · {position.sellPreview.thresholdSignal}</p>}
        {position.sellPreview.estimatedNetPnl != null && (
          <p>Estimated P&L after {position.sellPreview.costAllowancePct}% assumed costs · {gbp(Number(position.sellPreview.estimatedNetPnl) * rate)}</p>
        )}
      </div>}
      <div className="position-actions"><button onClick={() => setReplay({ mode: "live", symbol: String(position.symbol) })}>View Chart</button></div></div></article>)}{!otherPositions.length && <p className="muted">No open positions.</p>}</div></Card>
    {cryptoPositions.length > 0 && <Card title="Crypto Holdings">
      <p className="muted">Read-only Alpaca holdings.</p>
      <div className="position-list">{cryptoPositions.map(position => (
        <article className="position" key={position.symbol} style={positionGlowStyle(position)}>
          <div><h3>{position.symbol}</h3><p>Qty {positionQuantity(position)}</p></div>
          <b>{gbp(position.marketValueGbp ?? Number(position.marketValue || 0) * rate)}</b>
        </article>
      ))}</div>
    </Card>}
    <TradeReplayModal target={replay} authToken={authToken} onClose={() => setReplay(null)} />
  </>;
}
