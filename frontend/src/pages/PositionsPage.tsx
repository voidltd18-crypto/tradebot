import { Card } from "../components/Card";
import { gbp, pct, tone, usd } from "../lib/format";
import type { ActionFn, AnyObj, PositionStyleFn } from "../lib/types";

function TradeExplanation({ position, rate }: { position: AnyObj; rate: number }) {
  const explanation = position?.tradeExplanation || {};
  const reasons = Array.isArray(explanation?.sizingReasons) ? explanation.sizingReasons : [];
  const approvals = Array.isArray(explanation?.approvals) ? explanation.approvals : [];
  return <details className="trade-explanation">
    <summary>Why did the AI choose this position size?</summary>
    <div className="explanation-grid">
      <div><span>Allocated</span><b>{gbp(explanation?.finalNotionalGbp ?? Number(explanation?.finalNotionalUsd || position.marketValue || 0) * rate)} / {usd(explanation?.finalNotionalUsd ?? position.marketValue)}</b></div>
      <div><span>Portfolio allocation</span><b>{pct(explanation?.allocationPctOfManagedCapital)}</b></div>
      {explanation?.confidence !== undefined && <div><span>Entry confidence</span><b>{pct(Number(explanation.confidence) * 100)} · {explanation.confidenceLabel || "—"}</b></div>}
      {explanation?.qualityScore !== undefined && <div><span>Quality score</span><b>{Number(explanation.qualityScore).toFixed(4)}</b></div>}
      {explanation?.riskMultiplier !== undefined && <div><span>Risk multiplier</span><b>{Number(explanation.riskMultiplier).toFixed(2)}×</b></div>}
      {explanation?.cashReservedAfterUsd !== undefined && <div><span>Cash kept available</span><b>{usd(explanation.cashReservedAfterUsd)}</b></div>}
    </div>
    <p className="notice">{explanation?.summary || "Detailed explanation was not recorded for this position."}</p>
    {reasons.length > 0 && <div><b>Sizing reasons</b><ul>{reasons.map((reason: string, index: number) => <li key={index}>{reason}</li>)}</ul></div>}
    {explanation?.riskRationale && <p><b>Risk engine:</b> {explanation.riskRationale}</p>}
    {approvals.length > 0 && <p><b>Approved by:</b> {approvals.join(" · ")}</p>}
    {explanation?.reconstructed && <small className="muted">This explanation was reconstructed because the position was opened before detailed tracking was enabled.</small>}
  </details>;
}

export function PositionsPage({ positions, rate, action, positionGlowStyle }: { positions: AnyObj[]; rate: number; action: ActionFn; positionGlowStyle: PositionStyleFn }) {
  return <Card title="Open Positions — Best to Worst"><p className="muted">Your live holdings, sorted by performance. Manual selling remains available for supervision.</p><div className="position-list">{positions.map((position) => <article className="position" key={position.symbol} style={positionGlowStyle(position)}><div className="position-main"><h3>{position.symbol}</h3><p>Qty {Number(position.qty || 0).toFixed(4)} · Entry {usd(position.entry)} · Price {usd(position.price)}</p><p>Value <b>{gbp(position.marketValueGbp ?? Number(position.marketValue || 0) * rate)}</b> / {usd(position.marketValue)}</p><TradeExplanation position={position} rate={rate} /></div><div className="position-side"><b className={tone(position.pnl)}>PnL {gbp(position.pnlGbp ?? Number(position.pnl || 0) * rate)} / {usd(position.pnl)} / {pct(position.pnlPct)}</b><span>{position.trailingActive ? `Trailing floor ${usd(position.trailFloor)}` : `Trail starts ${usd(position.trailStartPrice)}`}</span><button className="danger" onClick={() => action(`/sell/${position.symbol}`)}>Sell {position.symbol}</button></div></article>)}{!positions.length && <p className="muted">No open positions.</p>}</div></Card>;
}
