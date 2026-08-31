import { useMemo, useRef, useState } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card } from "../components/Card";
import { TradeReplayModal, type ReplayTarget } from "../components/TradeReplayModal";
import { Stat } from "../components/Stat";
import { gbp, pct, tone, tradeDate, tradeTime, usd } from "../lib/format";
import type { AnyObj, Currency } from "../lib/types";

type RangeKey = "today" | "week" | "month" | "year";

function parseReportTimestamp(entry: AnyObj): number {
  const raw = entry?.timestamp || entry?.time || entry?.t || entry?.date || entry?.closedAt || entry?.exitTime || "";
  if (raw) {
    const direct = Date.parse(String(raw));
    if (Number.isFinite(direct)) return direct;
  }

  // Legacy report rows sometimes carry YYYY-MM-DD in day and HH:MM:SS in time/clock.
  const day = String(entry?.day || entry?.date || "").trim();
  const clock = String(entry?.clock || entry?.timeOfDay || "00:00:00").trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(day)) {
    const joined = Date.parse(`${day}T${clock || "00:00:00"}`);
    if (Number.isFinite(joined)) return joined;
  }

  // UK legacy dates (DD/MM/YYYY).
  const uk = day.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (uk) {
    const joined = Date.parse(`${uk[3]}-${uk[2]}-${uk[1]}T${clock || "00:00:00"}`);
    if (Number.isFinite(joined)) return joined;
  }
  return 0;
}

function tradeTimestamp(trade: AnyObj): number {
  return parseReportTimestamp(trade);
}

function rangeStart(range: RangeKey): number {
  const now = new Date();
  if (range === "today") { const d = new Date(now); d.setHours(0,0,0,0); return d.getTime(); }
  const days = range === "week" ? 7 : range === "month" ? 31 : 366;
  return now.getTime() - days * 86400000;
}

export function ReportsPage({ reports, data, rate, closedTrades, chartCurrency, setChartCurrency, reportsLoading, reportsError, reportsUpdatedAt, loadReports, authToken }: { reports: AnyObj; data: AnyObj; rate: number; closedTrades: AnyObj[]; chartCurrency: Currency; setChartCurrency: (currency: Currency) => void; reportsLoading: boolean; reportsError: string; reportsUpdatedAt: string; loadReports: (force?: boolean) => Promise<void>; authToken: string }) {
  const [replay, setReplay] = useState<ReplayTarget | null>(null);
  const [range, setRange] = useState<RangeKey>("month");
  const [symbolFilter, setSymbolFilter] = useState("ALL");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [chartSelection, setChartSelection] = useState<{ts:number; equity:number} | null>(null);
  const chartHoverRef = useRef<{ts:number; equity:number} | null>(null);
  const [momentFilter, setMomentFilter] = useState<{from:number; to:number; label:string} | null>(null);
  const totalDeposited = Number(reports?.totalDeposited || 0);
  const totalGainLoss = Number(reports?.totalGainLoss || 0);
  const earned = Number(reports?.earnedSinceDeposit || 0);
  const lost = Number(reports?.lostSinceDeposit || 0);
  const equityHistory = Array.isArray(reports?.equityHistory) ? reports.equityHistory : Array.isArray(data?.tradeTimeline) ? data.tradeTimeline : [];

  const reportChart = useMemo(() => {
    const start = rangeStart(range);
    return equityHistory.map((entry: AnyObj, index: number) => {
      const ts = parseReportTimestamp(entry);
      const date = ts ? new Date(ts) : null;
      const equity = chartCurrency === "GBP" ? Number(entry.equityGbp ?? entry.valueGbp ?? Number(entry.equity || entry.value || 0) * rate) : Number(entry.equity ?? entry.value ?? 0);
      return { ts, equity, label: date ? date.toLocaleString("en-GB", { day:"2-digit", month:"short", hour:"2-digit", minute:"2-digit", hour12:false }) : `#${index + 1}` };
    }).filter((p) => p.ts >= start && p.equity > 0).sort((a,b) => a.ts-b.ts);
  }, [equityHistory, chartCurrency, rate, range]);

  const symbols = useMemo(() => Array.from(new Set(closedTrades.map(t => String(t?.symbol || "").toUpperCase()).filter(Boolean))).sort(), [closedTrades]);
  const filteredClosedTrades = useMemo(() => {
    const from = fromDate ? new Date(`${fromDate}T00:00:00`).getTime() : 0;
    const to = toDate ? new Date(`${toDate}T23:59:59.999`).getTime() : Number.MAX_SAFE_INTEGER;
    return [...closedTrades].filter((trade) => {
      const symbol = String(trade?.symbol || "").toUpperCase();
      const ts = tradeTimestamp(trade);
      const dateMatch = (!from || ts >= from) && (!toDate || ts <= to);
      const momentMatch = !momentFilter || (ts >= momentFilter.from && ts <= momentFilter.to);
      return (symbolFilter === "ALL" || symbol === symbolFilter) && dateMatch && momentMatch;
    }).sort((a,b) => tradeTimestamp(b)-tradeTimestamp(a));
  }, [closedTrades, symbolFilter, fromDate, toDate, momentFilter]);

  const filteredPnl = filteredClosedTrades.reduce((sum, t) => sum + Number(t?.pnl || 0), 0);
  const filteredWins = filteredClosedTrades.filter(t => Number(t?.pnl || 0) > 0).length;

  const chartPointFromState = (state: any) => {
    const payload = state?.activePayload?.[0]?.payload;
    if (!payload?.ts) return null;
    return { ts: Number(payload.ts), equity: Number(payload.equity || 0) };
  };

  // Recharts reliably exposes activePayload during pointer movement (the same
  // payload used by the working tooltip), but some versions do not include it
  // on the chart-level click event. Capture the live hovered point and make
  // the click consume that point instead. This keeps click selection aligned
  // exactly with the tooltip the operator can see.
  const rememberChartPoint = (state: any) => {
    const point = chartPointFromState(state);
    if (point) chartHoverRef.current = point;
  };

  const selectChartPoint = (state?: any) => {
    const point = chartPointFromState(state) || chartHoverRef.current;
    if (!point?.ts) return;
    setChartSelection(point);
  };

  const selectAreaPoint = (entry: any) => {
    const payload = entry?.payload || entry;
    if (!payload?.ts) return;
    const point = { ts: Number(payload.ts), equity: Number(payload.equity || 0) };
    chartHoverRef.current = point;
    setChartSelection(point);
  };

  const viewTradesAtSelection = () => {
    if (!chartSelection) return;
    const selected = new Date(chartSelection.ts);
    let from = 0;
    let to = 0;
    let label = "";
    if (range === "today") {
      from = chartSelection.ts - 30 * 60 * 1000;
      to = chartSelection.ts + 30 * 60 * 1000;
      label = `Within 30 minutes of ${selected.toLocaleString("en-GB", { dateStyle:"medium", timeStyle:"short" })}`;
    } else {
      const start = new Date(selected); start.setHours(0,0,0,0);
      const end = new Date(selected); end.setHours(23,59,59,999);
      from = start.getTime(); to = end.getTime();
      label = selected.toLocaleDateString("en-GB", { dateStyle:"full" });
    }
    setSymbolFilter("ALL");
    setFromDate("");
    setToDate("");
    setMomentFilter({from,to,label});
    window.setTimeout(() => document.getElementById("closed-trade-history")?.scrollIntoView({ behavior:"smooth", block:"start" }), 50);
  };

  return <main className="grid two reports-page">
    <Card title="Reports Status" wide>
      <div className="actions"><button onClick={() => loadReports(true)} disabled={reportsLoading}>{reportsLoading ? "Loading Reports..." : "Refresh Reports"}</button></div>
      {reportsLoading && <p className="notice">Reports are loading separately. Live trading, positions and AI remain available.</p>}
      {reportsError && <p className="notice loss">{reportsError}</p>}
      {!reportsLoading && !reportsError && reportsUpdatedAt && <p className="muted">Updated {new Date(reportsUpdatedAt).toLocaleTimeString("en-GB", { hour12: false })}</p>}
    </Card>

    <Card title="Performance Summary" wide><section className="stats"><Stat label="Deposited" value={gbp(totalDeposited * rate)} sub={usd(totalDeposited)}/><Stat label="Earned" value={gbp(earned * rate)} sub={usd(earned)} className={tone(earned)}/><Stat label="Lost" value={gbp(lost * rate)} sub={usd(lost)} className="loss"/><Stat label="Current Equity" value={gbp(Number(reports?.currentEquity ?? data?.account?.equity ?? 0) * rate)} sub={usd(reports?.currentEquity ?? data?.account?.equity ?? 0)}/></section><p className={tone(totalGainLoss)}>Total gain/loss: {gbp(totalGainLoss * rate)}</p></Card>

    <Card title="Account Value" wide>
      <div className="report-toolbar">
        <div className="range-tabs">{(["today","week","month","year"] as RangeKey[]).map(r => <button key={r} className={range===r?"active":""} onClick={() => setRange(r)}>{r[0].toUpperCase()+r.slice(1)}</button>)}</div>
        <div className="chart-controls"><button className={chartCurrency === "GBP" ? "active" : ""} onClick={() => setChartCurrency("GBP")}>GBP</button><button className={chartCurrency === "USD" ? "active" : ""} onClick={() => setChartCurrency("USD")}>USD</button></div>
      </div>
      <div className="equity-chart-clean interactive-equity-chart">{reportChart.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={reportChart} margin={{top:12,right:18,left:8,bottom:8}} onMouseMove={rememberChartPoint} onClick={selectChartPoint}><defs><linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#38bdf8" stopOpacity={0.28}/><stop offset="100%" stopColor="#38bdf8" stopOpacity={0.02}/></linearGradient></defs><CartesianGrid strokeDasharray="3 3" stroke="#1e2b43" vertical={false}/><XAxis dataKey="ts" type="number" domain={["dataMin","dataMax"]} stroke="#94a3b8" tickFormatter={(v) => new Date(v).toLocaleDateString("en-GB", range==="today"?{hour:"2-digit",minute:"2-digit"}:{day:"2-digit",month:"short"})} minTickGap={44}/><YAxis stroke="#94a3b8" domain={["auto","auto"]} tickFormatter={(v) => `${chartCurrency==="GBP"?"£":"$"}${Number(v).toFixed(0)}`}/><Tooltip labelFormatter={(v) => new Date(Number(v)).toLocaleString("en-GB", {dateStyle:"medium",timeStyle:"short"})} formatter={(value:any) => [chartCurrency === "GBP" ? gbp(value) : usd(value), "Account value"]}/>{chartSelection && <ReferenceLine x={chartSelection.ts} strokeDasharray="4 4" label={{ value: "Selected", position: "insideTopRight" }} />}<Area type="monotone" dataKey="equity" stroke="#38bdf8" strokeWidth={2.5} fill="url(#equityFill)" dot={reportChart.length === 1 ? { r: 4 } : false} activeDot={{r:5, onClick: selectAreaPoint, style: { cursor: "pointer" }}} onClick={selectAreaPoint}/></AreaChart></ResponsiveContainer> : <div className="chart-empty"><b>No account-value points in this period</b><span>Choose a wider range or wait for more recorded history.</span></div>}</div>
      {chartSelection && <div className="chart-trade-selection">
        <div><span>Selected point</span><b>{new Date(chartSelection.ts).toLocaleString("en-GB", { dateStyle:"medium", timeStyle:"short" })}</b></div>
        <div><span>Account value</span><b>{chartCurrency === "GBP" ? gbp(chartSelection.equity) : usd(chartSelection.equity)}</b></div>
        <button onClick={viewTradesAtSelection}>View trades around this point</button>
        <button className="ghost" onClick={()=>{setChartSelection(null);setMomentFilter(null);}}>Clear selection</button>
      </div>}
    </Card>

    <div id="closed-trade-history" className="report-anchor"><Card title="Closed Trade History" wide>
      <div className="trade-filter-panel">
        <label><span>Stock</span><select value={symbolFilter} onChange={e=>setSymbolFilter(e.target.value)}><option value="ALL">All stocks</option>{symbols.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
        <label><span>From</span><input type="date" value={fromDate} onChange={e=>setFromDate(e.target.value)}/></label>
        <label><span>To</span><input type="date" value={toDate} onChange={e=>setToDate(e.target.value)}/></label>
        <button className="ghost" onClick={()=>{setSymbolFilter("ALL");setFromDate("");setToDate("");setMomentFilter(null);setChartSelection(null);}}>Clear filters</button>
      </div>
      {momentFilter && <div className="moment-filter-banner"><b>Chart selection:</b> {momentFilter.label}<button className="ghost" onClick={()=>setMomentFilter(null)}>Show all dates</button></div>}
      <div className="filter-summary"><b>{filteredClosedTrades.length}</b> matching rows <span>•</span> PnL <strong className={tone(filteredPnl)}>{gbp(filteredPnl * rate)}</strong> <span>•</span> Winning rows {filteredWins}</div>
      <div className="table-wrap"><table className="compact-table"><thead><tr><th>Date</th><th>Time</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th><th>%</th><th>Replay</th></tr></thead><tbody>{filteredClosedTrades.map((trade,index)=><tr key={`${trade.id||index}-${index}`}><td>{tradeDate(trade)}</td><td>{tradeTime(trade)}</td><td><b>{trade.symbol}</b></td><td>{usd(trade.entryPrice)}</td><td>{usd(trade.exitPrice)}</td><td>{Number(trade.qty||0).toFixed(4)}</td><td className={tone(trade.pnl)}>{gbp(trade.pnlGbp ?? Number(trade.pnl||0)*rate)} / {usd(trade.pnl)}</td><td className={tone(trade.pnl)}>{pct(trade.pnlPct)}</td><td><button className="table-action" disabled={!trade.id} onClick={()=>trade.id&&setReplay({mode:"closed",symbol:String(trade.symbol),tradeId:Number(trade.id)})}>View Chart</button></td></tr>)}{!filteredClosedTrades.length&&<tr><td colSpan={9}>No trades match these filters.</td></tr>}</tbody></table></div>
    </Card></div>
    <TradeReplayModal target={replay} authToken={authToken} onClose={() => setReplay(null)} />
  </main>;
}
