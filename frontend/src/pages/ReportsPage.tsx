import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card } from "../components/Card";
import { API_URL, readJson } from "../lib/api";
import { TradeReplayModal, type ReplayTarget } from "../components/TradeReplayModal";
import { Stat } from "../components/Stat";
import { gbp, pct, tone, tradeDate, tradeTime, usd } from "../lib/format";
import type { AnyObj, Currency } from "../lib/types";

type RangeKey = "today" | "week" | "month" | "year";
type AssetFilter = "ALL" | "CRYPTO" | "STOCKS";
const SMART_REBUY_PAIRS = ["UNIUSD","BTCUSD","XRPUSD","SOLUSD","HYPEUSD","LDOUSD","AVAXUSD","FILUSD","LTCUSD","ARBUSD","ADAUSD","ONDOUSD","SKYUSD","SHIBUSD","LINKUSD","SUSHIUSD","BATUSD","ETHUSD","XTZUSD","AAVEUSD","DOTUSD","CRVUSD","BCHUSD","GRTUSD","PAXGUSD","DOGEUSD","BONKUSD","YFIUSD","POLUSD"] as const;
const normaliseCryptoPair = (value: unknown) => String(value || "").toUpperCase().replace(/[^A-Z0-9]/g, "");

function isCryptoTrade(trade: AnyObj): boolean {
  const assetClass = String(trade?.asset_class ?? trade?.assetClass ?? trade?.asset_type ?? trade?.assetType ?? "").toLowerCase();
  if (assetClass.includes("crypto")) return true;
  if (assetClass.includes("equity") || assetClass.includes("stock")) return false;
  const symbol = String(trade?.symbol || "").toUpperCase().replace(/\s/g, "");
  return /^[A-Z0-9]{2,20}\/USD$/.test(symbol) || /^(BTC|ETH|SOL|DOGE|LTC|BCH|AVAX|LINK|UNI|AAVE|DOT|SHIB|PEPE|XRP|ADA|MATIC|USDT|USDC)USD$/.test(symbol);
}


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
    const joined = Date.parse(`${day}T${clock || "00:00:00"}Z`);
    if (Number.isFinite(joined)) return joined;
  }

  // UK legacy dates (DD/MM/YYYY).
  const uk = day.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (uk) {
    const joined = Date.parse(`${uk[3]}-${uk[2]}-${uk[1]}T${clock || "00:00:00"}Z`);
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
  const [signalSymbol, setSignalSymbol] = useState("UNIUSD");
  const [showAllRebuyCoins, setShowAllRebuyCoins] = useState(false);
  const [bulkSignals, setBulkSignals] = useState<AnyObj[]>([]);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkError, setBulkError] = useState("");
  const [bulkScannedAt, setBulkScannedAt] = useState("");
  const bulkBusyRef = useRef(false);
  useEffect(() => {
    if (!authToken) return;
    let active = true;
    async function scan() {
      if (bulkBusyRef.current) return;
      bulkBusyRef.current = true;
      if (active) setBulkLoading(true);
      try {
        const response = await fetch(`${API_URL}/v19/manual-crypto-rebuy-scan`, {
          cache:"no-store", headers: {"X-Auth-Token":authToken,"x-api-key":authToken},
        });
        if (!response.ok) throw new Error("Automatic broker scan unavailable");
        const payload = await readJson(response);
        if (!Array.isArray(payload?.rows) || payload.rows.length !== SMART_REBUY_PAIRS.length) throw new Error("Incomplete scan");
        if (active) {setBulkSignals(payload.rows);setBulkScannedAt(String(payload.scannedAt||""));setBulkError("");}
      } catch {
        if (active) setBulkError("Automatic scan unavailable — no unverified buy signals shown");
      } finally {
        bulkBusyRef.current = false;
        if (active) setBulkLoading(false);
      }
    }
    void scan();
    const interval = window.setInterval(()=>void scan(), 120000);
    return ()=>{active=false;window.clearInterval(interval);};
  }, [authToken]);
  const [signal, setSignal] = useState<AnyObj | null>(null);
  const [signalLoading, setSignalLoading] = useState(false);
  async function checkManualRebuySignal() {
    setSignalLoading(true);
    setSignal(null);
    try {
      const response = await fetch(`${API_URL}/v19/manual-crypto-rebuy-preview/${encodeURIComponent(signalSymbol)}`, {
        cache: "no-store", headers: {"X-Auth-Token": authToken, "x-api-key": authToken},
      });
      const result = await readJson(response);
      if (!response.ok) throw new Error("Broker preview unavailable");
      setSignal(result);
    } catch {
      setSignal({status:"WAIT",reason:"Could not verify broker data; do not buy"});
    } finally { setSignalLoading(false); }
  }
  const [rebuySymbol, setRebuySymbol] = useState("");
  const [rebuyRequestId, setRebuyRequestId] = useState("");
  const [rebuyAmount, setRebuyAmount] = useState("25");
  const [rebuyPotChoice, setRebuyPotChoice] = useState<"FULL" | "HALF" | null>(null);
  const [rebuySignalWarning, setRebuySignalWarning] = useState("");
  const [rebuyAvailable, setRebuyAvailable] = useState<number | null>(null);
  const [rebuyCashLoading, setRebuyCashLoading] = useState(false);
  const [rebuyCashError, setRebuyCashError] = useState("");
  async function fetchRebuyCash() {
    setRebuyCashLoading(true);
    setRebuyAvailable(null);
    setRebuyCashError("");
    try {
      const response = await fetch(`${API_URL}/v19/reports/crypto-buy-again/available`, {
        cache: "no-store",
        headers: {"X-Auth-Token":authToken, "x-api-key":authToken},
      });
      const payload = await readJson(response);
      const amount = Number(payload?.availableUsd);
      if (!response.ok || !payload?.ok || payload?.availableUsd == null || !Number.isFinite(amount) || amount < 0) {
        throw new Error(String(payload?.message || "Available cash could not be verified"));
      }
      setRebuyAvailable(amount);
      setRebuyAmount(rebuyPotChoice === "HALF" ? (Math.floor(amount * 50) / 100).toFixed(2) : (Math.floor(amount * 100) / 100).toFixed(2));
    } catch (error: any) {
      setRebuyCashError(String(error?.message || "Available cash could not be verified"));
    } finally { setRebuyCashLoading(false); }
  }
  function openSmartRebuyBuy(row: AnyObj) {
    const symbol = String(row?.symbol || "").toUpperCase();
    if (!cryptoPair(symbol) || rebuyPending) return;
    setRebuySymbol(symbol);
    setRebuyRequestId(crypto.randomUUID());
    setRebuyPotChoice(null);
    setRebuyAvailable(null);
    setRebuyAmount("");
    setRebuyConfirmation("");
    setRebuyMessage("");
    setRebuySignalWarning(row.status === "BUY_CANDIDATE"
      ? "Green signal is informational, not a guarantee. Broker conditions may have changed."
      : "AMBER WATCH: Recovery is NOT verified. Buying now is outside the green rebuy signal.");
    void fetchRebuyCash();
  }
  const [rebuyConfirmation, setRebuyConfirmation] = useState("");
  const [rebuyPending, setRebuyPending] = useState(false);
  const [rebuyMessage, setRebuyMessage] = useState("");
  const cryptoPair = (symbol: string) => /^[A-Z0-9]{2,20}\/USD$/.test(symbol.toUpperCase());
  async function submitRebuy() {
    if (!rebuySymbol || !rebuyRequestId || rebuyPending || rebuyCashLoading || rebuyAvailable === null || Number(rebuyAmount) < 1 || Number(rebuyAmount) > rebuyAvailable || rebuyConfirmation !== `BUY ${rebuySymbol}`) return;
    setRebuyPending(true);
    setRebuyMessage("");
    try {
      const response = await fetch(`${API_URL}/v19/reports/crypto-buy-again`, {
        method: "POST",
        headers: {"Content-Type":"application/json", "X-Auth-Token": authToken, "x-api-key":authToken},
        body: JSON.stringify({symbol:rebuySymbol, amountUsd:rebuyAmount, confirmation:rebuyConfirmation, requestId:rebuyRequestId}),
      });
      const result = await readJson(response);
      setRebuyMessage(String(result?.message || (response.ok ? "Broker request submitted; verify your orders." : "Order not placed.")));
      if (result?.orderSubmitted) { setRebuySymbol(""); await loadReports(true); }
    } catch {
      setRebuyMessage("Request status unknown. Check Alpaca orders before trying again.");
    } finally {setRebuyPending(false);}
  }
  const [range, setRange] = useState<RangeKey>("month");
  const [symbolFilter, setSymbolFilter] = useState("ALL");
  const [assetFilter, setAssetFilter] = useState<AssetFilter>("ALL");
  const [symbolSearch, setSymbolSearch] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [chartSelection, setChartSelection] = useState<{ts:number; equity:number} | null>(null);
  const chartHoverRef = useRef<{ts:number; equity:number} | null>(null);
  const chartShellRef = useRef<HTMLDivElement | null>(null);
  const [momentFilter, setMomentFilter] = useState<{from:number; to:number; label:string} | null>(null);
  const totalDeposited = Number(reports?.totalDeposited || 0);
  const totalGainLoss = Number(reports?.totalGainLoss || 0);
  const expectancy = reports?.recentTradeExpectancy || {};

  const earned = Number(reports?.earnedSinceDeposit || 0);
  const lost = Number(reports?.lostSinceDeposit || 0);
  const equityHistory = Array.isArray(reports?.equityHistory) ? reports.equityHistory : Array.isArray(data?.tradeTimeline) ? data.tradeTimeline : [];

  const reportChart = useMemo(() => {
    const start = rangeStart(range);
    return equityHistory.map((entry: AnyObj, index: number) => {
      const ts = parseReportTimestamp(entry);
      const date = ts ? new Date(ts) : null;
      const equity = chartCurrency === "GBP" ? Number(entry.equityGbp ?? entry.valueGbp ?? Number(entry.equity || entry.value || 0) * rate) : Number(entry.equity ?? entry.value ?? 0);
      return { ts, equity, label: date ? date.toLocaleString("en-GB", { timeZone: "Europe/London", day:"2-digit", month:"short", hour:"2-digit", minute:"2-digit", hour12:false }) : `#${index + 1}` };
    }).filter((p) => p.ts >= start && p.equity > 0).sort((a,b) => a.ts-b.ts);
  }, [equityHistory, chartCurrency, rate, range]);

  // Never display non-executed or zero-quantity closed-trade artefacts.
  // Keep the broker/database records untouched and leave account totals unchanged.
  const displayedTrades = useMemo(() => closedTrades.filter((trade) => {
    const qty = Number(trade?.qty);
    return Number.isFinite(qty) && qty > 0;
  }), [closedTrades]);
  const highlightedRebuyCoins = useMemo(() => bulkSignals.filter(row =>
    row?.status === "BUY_CANDIDATE" && row?.readOnly === true && row?.orderSubmitted === false ||
    row?.status === "WATCH" && row?.readOnly === true && row?.orderSubmitted === false
  ).sort((a,b) => (a.status === "BUY_CANDIDATE" ? 0 : 1) - (b.status === "BUY_CANDIDATE" ? 0 : 1)), [bulkSignals]);
  const relevantRebuyCoins = highlightedRebuyCoins.map(row => normaliseCryptoPair(row.symbol));
  const visibleRebuyCoins = showAllRebuyCoins ? SMART_REBUY_PAIRS : SMART_REBUY_PAIRS.filter(pair => relevantRebuyCoins.includes(pair));
  const assetTrades = useMemo(() => displayedTrades.filter(t => assetFilter === "ALL" || (isCryptoTrade(t) ? "CRYPTO" : "STOCKS") === assetFilter), [displayedTrades, assetFilter]);
  const symbols = useMemo(() => Array.from(new Set(assetTrades.map(t => String(t?.symbol || "").toUpperCase()).filter(Boolean))).sort(), [assetTrades]);
  const filteredClosedTrades = useMemo(() => {
    const from = fromDate ? new Date(`${fromDate}T00:00:00`).getTime() : 0;
    const to = toDate ? new Date(`${toDate}T23:59:59.999`).getTime() : Number.MAX_SAFE_INTEGER;
    return [...assetTrades].filter((trade) => {
      const symbol = String(trade?.symbol || "").toUpperCase();
      const ts = tradeTimestamp(trade);
      const dateMatch = (!from || ts >= from) && (!toDate || ts <= to);
      const momentMatch = !momentFilter || (ts >= momentFilter.from && ts <= momentFilter.to);
      return (symbolFilter === "ALL" || symbol === symbolFilter) && symbol.includes(symbolSearch.trim().toUpperCase()) && dateMatch && momentMatch;
    }).sort((a,b) => tradeTimestamp(b)-tradeTimestamp(a));
  }, [assetTrades, symbolFilter, symbolSearch, fromDate, toDate, momentFilter]);

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

  // V18.2.23: Recharts v3 can render the tooltip while omitting activePayload
  // from chart-level click callbacks. Use the actual pointer X coordinate as the
  // source of truth and select the nearest plotted report point. This makes the
  // interaction independent of Recharts' event payload shape.
  const selectNearestPointFromPointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!reportChart.length || !chartShellRef.current) return;
    const rect = chartShellRef.current.getBoundingClientRect();
    if (!rect.width) return;

    // Approximate the actual drawable X axis. The chart has a small right margin
    // and Recharts reserves space on the left for the Y axis/ticks. Clamping
    // keeps clicks in either gutter pinned to the first/last real observation.
    const plotLeft = rect.left + 56;
    const plotRight = rect.right - 20;
    const x = Math.max(plotLeft, Math.min(plotRight, event.clientX));
    const ratio = plotRight > plotLeft ? (x - plotLeft) / (plotRight - plotLeft) : 0;
    const firstTs = reportChart[0].ts;
    const lastTs = reportChart[reportChart.length - 1].ts;
    const targetTs = firstTs + (lastTs - firstTs) * ratio;

    let nearest = reportChart[0];
    let nearestDistance = Math.abs(nearest.ts - targetTs);
    for (const point of reportChart) {
      const distance = Math.abs(point.ts - targetTs);
      if (distance < nearestDistance) {
        nearest = point;
        nearestDistance = distance;
      }
    }

    const selected = { ts: Number(nearest.ts), equity: Number(nearest.equity || 0) };
    chartHoverRef.current = selected;
    setChartSelection(selected);
  };

  const selectionTrades = useMemo(() => {
    if (!chartSelection) return [] as AnyObj[];
    const selected = new Date(chartSelection.ts);
    let from = 0;
    let to = 0;
    if (range === "today") {
      from = chartSelection.ts - 30 * 60 * 1000;
      to = chartSelection.ts + 30 * 60 * 1000;
    } else {
      const start = new Date(selected); start.setHours(0,0,0,0);
      const end = new Date(selected); end.setHours(23,59,59,999);
      from = start.getTime();
      to = end.getTime();
    }
    return assetTrades.filter((trade) => {
      const ts = tradeTimestamp(trade);
      return ts >= from && ts <= to;
    }).sort((a,b) => tradeTimestamp(a)-tradeTimestamp(b));
  }, [chartSelection, assetTrades, range]);

  const viewTradesAtSelection = () => {
    if (!chartSelection) return;
    const selected = new Date(chartSelection.ts);
    let from = 0;
    let to = 0;
    let label = "";
    if (range === "today") {
      from = chartSelection.ts - 30 * 60 * 1000;
      to = chartSelection.ts + 30 * 60 * 1000;
      label = `Within 30 minutes of ${selected.toLocaleString("en-GB", { timeZone: "Europe/London", dateStyle:"medium", timeStyle:"short" })}`;
    } else {
      const start = new Date(selected); start.setHours(0,0,0,0);
      const end = new Date(selected); end.setHours(23,59,59,999);
      from = start.getTime(); to = end.getTime();
      label = selected.toLocaleDateString("en-GB", { timeZone: "Europe/London", dateStyle:"full" });
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
      {!reportsLoading && !reportsError && reportsUpdatedAt && <p className="muted">Updated {new Date(reportsUpdatedAt).toLocaleTimeString("en-GB", { timeZone: "Europe/London", hour12: false })}</p>}
    </Card>

    <Card title="Smart Rebuy — Crypto Signals" wide>
      <div style={{padding:18,border:"1px solid #334155",borderRadius:14,background:"#1e293b"}}>
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",gap:12,flexWrap:"wrap"}}>
          <div><strong style={{fontSize:18}}>Smart Rebuy</strong><p style={{margin:"5px 0",color:"#cbd5e1"}}>Live Alpaca · Read-only · No automatic buys · Automatically scans 29 coins every 2 minutes · Manual decisions only</p></div>
          <div style={{display:"flex",alignItems:"center",gap:8}}>
            <select aria-label="Smart Rebuy pair" value={signalSymbol} onChange={e=>{setSignalSymbol(e.target.value);setSignal(null);}}>
              {!visibleRebuyCoins.includes(signalSymbol as typeof SMART_REBUY_PAIRS[number]) && <option value={signalSymbol}>{signalSymbol.replace(/USD$/, "/USD")} · Selected</option>}
              {visibleRebuyCoins.map(pair => <option key={pair} value={pair}>{pair.replace(/USD$/, "/USD")}</option>)}
            </select>
            <button className="ghost" onClick={()=>setShowAllRebuyCoins(v=>!v)}>{showAllRebuyCoins ? "Show relevant only" : `Show all 29 coins`}</button>
            <button className="table-action" disabled={signalLoading} onClick={()=>void checkManualRebuySignal()}>{signalLoading?"Checking…":"Refresh Signal"}</button>
          </div>
        </div>
        <div style={{marginTop:12}}>
          <p style={{color:"#cbd5e1",margin:"0 0 8px"}}>{bulkLoading ? "Scanning 29 coins…" : bulkScannedAt ? `Auto-scanned 29 coins · ${new Date(bulkScannedAt).toLocaleTimeString("en-GB")}` : "Awaiting first automatic scan"}</p>
          {bulkError && <p role="status" style={{color:"#fbbf24"}}>{bulkError}</p>}
          {!bulkLoading && !bulkError && highlightedRebuyCoins.length===0 && <p style={{color:"#94a3b8"}}>No verified WATCH or BUY candidates right now. All other coins are hidden.</p>}
          <div style={{display:"flex",flexWrap:"wrap",gap:8}}>
            {highlightedRebuyCoins.map(row => <div key={row.symbol} style={{display:"flex",alignItems:"center",gap:6,padding:"4px 5px 4px 10px",borderRadius:9,border:"1px solid #475569",background:"#0f172a"}}>
              <button type="button" onClick={()=>{setSignalSymbol(normaliseCryptoPair(row.symbol));setSignal(row);}} style={{padding:"6px 2px",border:0,background:"transparent",color:"#f8fafc",cursor:"pointer"}}>
                <span style={{color:row.status==="BUY_CANDIDATE"?"#22c55e":"#f59e0b"}}>●</span> {row.symbol} · {row.status==="BUY_CANDIDATE"?"BUY candidate":"WATCH"}{row.dipPct!=null?` · ${row.dipPct}% dip`:""}
              </button>
              <button type="button" className="table-action" onClick={()=>openSmartRebuyBuy(row)}>Buy</button>
            </div>)}
          </div>
        </div>
        {showAllRebuyCoins && <div style={{marginTop:14,padding:12,borderRadius:10,background:"#0f172a"}}>
          <p style={{margin:"0 0 10px",color:"#cbd5e1"}}>All 29 coins — select one to check its broker signal:</p>
          <div style={{display:"flex",flexWrap:"wrap",gap:8}}>
            {SMART_REBUY_PAIRS.map(pair => <button key={pair} type="button"
              aria-pressed={signalSymbol===pair}
              onClick={()=>{setSignalSymbol(pair);setSignal(null);}}
              style={{padding:"7px 11px",borderRadius:8,cursor:"pointer",border:signalSymbol===pair?"1px solid #38bdf8":"1px solid #475569",background:signalSymbol===pair?"#164e63":"#1e293b",color:"#f8fafc"}}>
              {pair.replace(/USD$/, "/USD")}
            </button>)}
          </div>
        </div>}
        {signal && (() => {
          const reason=String(signal.reason||"No verified signal");
          const blocked=signal.positionOpen===true||signal.orderPending===true||/position|order pending|broker data unavailable|unverified|verified sale|credentials|invalid|could not verify/i.test(reason);
          const green=signal.status==="BUY_CANDIDATE"&&signal.readOnly===true&&signal.orderSubmitted===false;
          const colour=green?"#22c55e":blocked?"#ef4444":"#f59e0b";
          const label=green?"YES — Buy candidate":blocked?"NO — Blocked":"WAIT — Not ready";
          return <div role="status" style={{marginTop:16,padding:14,borderRadius:10,background:"#0f172a"}}>
            <div style={{display:"flex",alignItems:"center",gap:12}}>
              <span aria-hidden="true" style={{display:"inline-block",width:24,height:24,borderRadius:"50%",background:colour,boxShadow:`0 0 0 5px ${colour}22`,flexShrink:0}}/>
              <strong style={{fontSize:20}}>{label}</strong>
            </div>
            <p style={{margin:"12px 0 4px",color:"#cbd5e1"}}>{reason}</p>
            {signal.dipPct!=null&&<small>Dip from last sale: {String(signal.dipPct)}%</small>}
            {signal.quoteFresh===false&&<p style={{color:"#fbbf24"}}>Quote not fresh — no buy signal</p>}
          </div>;
        })()}
      </div>
    </Card>\n\n    <Card title="Performance Summary" wide><p className="muted">Account-wide balances (stocks and crypto combined). Use the asset selector in Closed Trade History for filtered realised P&amp;L.</p><section className="stats"><Stat label="Deposited" value={gbp(totalDeposited * rate)} sub={usd(totalDeposited)}/><Stat label="Earned" value={gbp(earned * rate)} sub={usd(earned)} className={tone(earned)}/><Stat label="Lost" value={gbp(lost * rate)} sub={usd(lost)} className="loss"/><Stat label="Current Equity" value={gbp(Number(reports?.currentEquity ?? data?.account?.equity ?? 0) * rate)} sub={usd(reports?.currentEquity ?? data?.account?.equity ?? 0)}/></section><p className={tone(totalGainLoss)}>Total gain/loss: {gbp(totalGainLoss * rate)}</p></Card>

    <Card title="Recent Trade Reward vs Risk" wide>
      <p className="muted">Read-only · Latest {Number(expectancy?.sampleTrades || 0)} closed trades · Not lifetime performance</p>
      <section className="stats">
        <Stat label="Average Win" value={expectancy?.averageWinnerGbp == null ? "—" : gbp(expectancy.averageWinnerGbp)} />
        <Stat label="Average Loss" value={expectancy?.averageLoserGbp == null ? "—" : gbp(expectancy.averageLoserGbp)} />
        <Stat label="Win Rate" value={expectancy?.winRatePct == null ? "—" : `${Number(expectancy.winRatePct).toFixed(1)}%`} />
        <Stat label="Break-even Win Rate" value={expectancy?.breakEvenWinRatePct == null ? "—" : `${Number(expectancy.breakEvenWinRatePct).toFixed(1)}%`} />
        <Stat label="Net Realised" value={expectancy?.sampleTrades ? gbp(expectancy.netRealisedGbp) : "—"} className={tone(expectancy?.netRealisedGbp || 0)} />
      </section>
      <p className="muted">Historical results only. No changes to live entries or exits.</p>
    </Card>

    <Card title="Account Value" wide>
      <div className="report-toolbar">
        <div className="range-tabs">{(["today","week","month","year"] as RangeKey[]).map(r => <button key={r} className={range===r?"active":""} onClick={() => setRange(r)}>{r[0].toUpperCase()+r.slice(1)}</button>)}</div>
        <div className="chart-controls"><button className={chartCurrency === "GBP" ? "active" : ""} onClick={() => setChartCurrency("GBP")}>GBP</button><button className={chartCurrency === "USD" ? "active" : ""} onClick={() => setChartCurrency("USD")}>USD</button></div>
      </div>
      <div ref={chartShellRef} className="equity-chart-clean interactive-equity-chart" onPointerUp={selectNearestPointFromPointer}>{reportChart.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={reportChart} margin={{top:12,right:18,left:8,bottom:8}} onMouseMove={rememberChartPoint} onClick={selectChartPoint}><defs><linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#38bdf8" stopOpacity={0.28}/><stop offset="100%" stopColor="#38bdf8" stopOpacity={0.02}/></linearGradient></defs><CartesianGrid strokeDasharray="3 3" stroke="#1e2b43" vertical={false}/><XAxis dataKey="ts" type="number" domain={["dataMin","dataMax"]} stroke="#94a3b8" tickFormatter={(v) => new Date(v).toLocaleDateString("en-GB", range==="today"?{timeZone:"Europe/London",hour:"2-digit",minute:"2-digit"}:{timeZone:"Europe/London",day:"2-digit",month:"short"})} minTickGap={44}/><YAxis stroke="#94a3b8" domain={["auto","auto"]} tickFormatter={(v) => `${chartCurrency==="GBP"?"£":"$"}${Number(v).toFixed(0)}`}/><Tooltip labelFormatter={(v) => new Date(Number(v)).toLocaleString("en-GB", { timeZone: "Europe/London",dateStyle:"medium",timeStyle:"short"})} formatter={(value:any) => [chartCurrency === "GBP" ? gbp(value) : usd(value), "Account value"]}/>{chartSelection && <ReferenceLine x={chartSelection.ts} strokeDasharray="4 4" label={{ value: "Selected", position: "insideTopRight" }} />}<Area type="monotone" dataKey="equity" stroke="#38bdf8" strokeWidth={2.5} fill="url(#equityFill)" dot={reportChart.length === 1 ? { r: 4 } : false} activeDot={{r:5, onClick: selectAreaPoint, style: { cursor: "pointer" }}} onClick={selectAreaPoint}/></AreaChart></ResponsiveContainer> : <div className="chart-empty"><b>No account-value points in this period</b><span>Choose a wider range or wait for more recorded history.</span></div>}</div>
      {chartSelection && <div className="chart-trade-selection">
        <div><span>Selected point</span><b>{new Date(chartSelection.ts).toLocaleString("en-GB", { timeZone: "Europe/London", dateStyle:"medium", timeStyle:"short" })}</b></div>
        <div><span>Account value</span><b>{chartCurrency === "GBP" ? gbp(chartSelection.equity) : usd(chartSelection.equity)}</b></div>
        <div><span>Closed trades in this {range === "today" ? "±30 min window" : "day"}</span><b>{selectionTrades.length}</b>{selectionTrades.length > 0 && <small>{Array.from(new Set(selectionTrades.map(t => String(t?.symbol || "").toUpperCase()).filter(Boolean))).slice(0,6).join(", ")}</small>}</div>
        <button onClick={viewTradesAtSelection}>View trades around this point</button>
        <button className="ghost" onClick={()=>{setChartSelection(null);setMomentFilter(null);}}>Clear selection</button>
      </div>}
    </Card>

    <div id="closed-trade-history" className="report-anchor"><Card title="Closed Trade History" wide>
      <div className="trade-filter-panel">
        <label><span>Asset type</span><select aria-label="Filter reports by asset type" value={assetFilter} onChange={e => { setAssetFilter(e.target.value as AssetFilter); setSymbolFilter("ALL"); setChartSelection(null); setMomentFilter(null); }}><option value="ALL">All trades</option><option value="CRYPTO">Crypto only</option><option value="STOCKS">Stocks only</option></select></label>
        <label><span>Search ticker</span><input type="search" aria-label="Search trade symbols" placeholder="e.g. USD, SOL, MARA" value={symbolSearch} onChange={e=>setSymbolSearch(e.target.value)}/></label>
        <label><span>Symbol</span><select value={symbolFilter} onChange={e=>setSymbolFilter(e.target.value)}><option value="ALL">All symbols</option>{symbols.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
        <label><span>From</span><input type="date" value={fromDate} onChange={e=>setFromDate(e.target.value)}/></label>
        <label><span>To</span><input type="date" value={toDate} onChange={e=>setToDate(e.target.value)}/></label>
        <button className="ghost" onClick={()=>{setAssetFilter("ALL");setSymbolFilter("ALL");setSymbolSearch("");setFromDate("");setToDate("");setMomentFilter(null);setChartSelection(null);}}>Clear filters</button>
      </div>
      {momentFilter && <div className="moment-filter-banner"><b>Chart selection:</b> {momentFilter.label}<button className="ghost" onClick={()=>setMomentFilter(null)}>Show all dates</button></div>}
      <div className="filter-summary"><b>{filteredClosedTrades.length}</b> {assetFilter === "CRYPTO" ? "crypto" : assetFilter === "STOCKS" ? "stock" : ""} matching rows <span>•</span> PnL <strong className={tone(filteredPnl)}>{gbp(filteredPnl * rate)}</strong> <span>•</span> Winning rows {filteredWins}</div>
      <div className="table-wrap"><table className="compact-table"><thead><tr><th>Date</th><th>Time</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th><th>%</th><th>Replay</th><th>Rebuy</th></tr></thead><tbody>{filteredClosedTrades.map((trade,index)=><tr key={`${trade.id||index}-${index}`}><td>{tradeDate(trade)}</td><td>{tradeTime(trade)}</td><td><b>{trade.symbol}</b></td><td>{usd(trade.entryPrice)}</td><td>{usd(trade.exitPrice)}</td><td>{Number(trade.qty||0).toFixed(4)}</td><td className={tone(trade.pnl)}>{gbp(trade.pnlGbp ?? Number(trade.pnl||0)*rate)} / {usd(trade.pnl)}</td><td className={tone(trade.pnl)}>{pct(trade.pnlPct)}</td><td><button className="table-action" disabled={!trade.id} onClick={()=>trade.id&&setReplay({mode:"closed",symbol:String(trade.symbol),tradeId:Number(trade.id)})}>View Chart</button></td><td>{cryptoPair(String(trade.symbol || "")) ? <button className="table-action" onClick={()=>{setRebuySymbol(String(trade.symbol).toUpperCase());setRebuyRequestId(crypto.randomUUID());setRebuyAvailable(null);setRebuyAmount("");void fetchRebuyCash();setRebuyConfirmation("");setRebuyMessage("");setRebuySignalWarning("");setRebuyPotChoice(null);}}>Buy Again</button> : "—"}</td></tr>)}{!filteredClosedTrades.length&&<tr><td colSpan={10}>No trades match these filters.</td></tr>}</tbody></table></div>
    </Card></div>
    {rebuySymbol && <div role="dialog" aria-modal="true" aria-label="Buy crypto again" className="report-rebuy-dialog" style={{position:"fixed",inset:0,zIndex:9000,background:"rgba(0,0,0,.75)",display:"flex",alignItems:"center",justifyContent:"center",padding:16}}>
      <div style={{width:"min(450px,100%)",background:"#161b27",border:"1px solid #475569",borderRadius:12,padding:20,color:"#f8fafc"}}>
        <h3>Buy Crypto — {rebuySymbol}</h3>
        {rebuySignalWarning && <p role="alert" style={{color:"#fbbf24"}}>{rebuySignalWarning}</p>}
        <p>This requests a <strong>new Alpaca market buy</strong> at the current market price, not the historical sale price. It may use real money if the broker account is live and the feature is enabled.</p>
        <div style={{display:"flex",gap:8,marginBottom:12}}>
          <button type="button" disabled={rebuyAvailable===null || rebuyPending} onClick={()=>{setRebuyPotChoice("FULL");setRebuyAmount((Math.floor((rebuyAvailable||0)*100)/100).toFixed(2));}}>Full pot (100%)</button>
          <button type="button" disabled={rebuyAvailable===null || rebuyPending} onClick={()=>{setRebuyPotChoice("HALF");setRebuyAmount((Math.floor((rebuyAvailable||0)*50)/100).toFixed(2));}}>Half pot (50%)</button>
        </div>
        <p style={{color:"#cbd5e1"}}>Pot = verified available Alpaca cash, not total portfolio value. Choose a pot size, then confirm the live market order.</p>
        <label style={{display:"block",marginBottom:12}}>Amount to spend (USD)
          <input type="number" min="1" max={rebuyAvailable ?? undefined} step="0.01" value={rebuyAmount} disabled={rebuyCashLoading || rebuyAvailable === null} onChange={e=>{setRebuyPotChoice(null);setRebuyAmount(e.target.value);}} style={{display:"block",width:"100%",marginTop:5}}/>
        </label>
        <p role="status" style={{marginTop:-4}}>{rebuyCashLoading ? "Checking Alpaca cash…" : rebuyAvailable !== null ? `Available to buy: ${rebuyAvailable.toFixed(2)} USD` : (rebuyCashError || "No verified buying power available")}</p>
        <button className="ghost" disabled={rebuyCashLoading || rebuyPending} onClick={()=>{void fetchRebuyCash();}}>Refresh buying power</button>
        <label style={{display:"block",marginBottom:12}}>Type <strong>BUY {rebuySymbol}</strong> to confirm
          <input value={rebuyConfirmation} autoComplete="off" onChange={e=>setRebuyConfirmation(e.target.value)} style={{display:"block",width:"100%",marginTop:5}}/>
        </label>
        <p>The available amount comes from Alpaca cash and non-marginable buying power, not your invested positions or vault. Alpaca rechecks cash when you confirm.</p>
        {rebuyMessage && <p role="status">{rebuyMessage}</p>}
        <div style={{display:"flex",gap:8,justifyContent:"flex-end"}}>
          <button className="ghost" disabled={rebuyPending} onClick={()=>{setRebuySymbol("");setRebuyRequestId("");setRebuyMessage("");}}>Close</button>
          <button disabled={rebuyPending || rebuyCashLoading || rebuyAvailable === null || rebuyConfirmation !== `BUY ${rebuySymbol}` || !(Number(rebuyAmount)>=1 && Number(rebuyAmount)<=rebuyAvailable)} onClick={submitRebuy}>{rebuyPending?"Submitting…":"Confirm Buy"}</button>
        </div>
      </div>
    </div>}
    <TradeReplayModal target={replay} authToken={authToken} onClose={() => setReplay(null)} />
  </main>;
}
