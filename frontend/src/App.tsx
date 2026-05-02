import React, { useEffect, useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceDot,
} from "recharts";

const API_URL = "https://tradebot-0myo.onrender.com";

type Position = {
  symbol: string;
  qty: number;
  entry: number;
  price: number;
  marketValue: number;
  marketValueGbp?: number;
  pnl: number;
  pnlGbp?: number;
  pnlPct: number;
  trailStartPrice?: number;
  trailFloor?: number;
  trailingActive?: boolean;
  boughtToday?: boolean;
  minutesSinceBuy?: number;
  lockedToday?: boolean;
};

type Scan = {
  symbol: string;
  price: number;
  trigger?: number;
  spread?: number;
  pullback?: number;
  shortMomentum?: number;
  qualityScore?: number;
  readyToBuy?: boolean;
  confidence?: number;
  confidenceLabel?: string;
  sniperPass?: boolean;
  sniperReason?: string;
  aPlusPass?: boolean;
  aPlusReason?: string;
  priceCurve?: { t: string; value: number }[];
};

type Trade = {
  time?: string;
  side?: string;
  symbol?: string;
  amount?: number;
  amountGbp?: number;
  qty?: number;
  pnl?: number;
  pnlGbp?: number;
  pnlPct?: number;
  reason?: string;
};

const tabs = [
  ["overview", "Overview"],
  ["money", "Reports"],
  ["positions", "Positions"],
  ["scanner", "Scanner"],
  ["activity", "Activity"],
  ["admin", "Admin"],
] as const;

function usd(n: any) {
  return `$${Number(n || 0).toFixed(2)}`;
}
function gbp(n: any) {
  return `£${Number(n || 0).toFixed(2)}`;
}
function pct(n: any) {
  return `${Number(n || 0).toFixed(2)}%`;
}
function colour(n: any) {
  return Number(n || 0) >= 0 ? "#22c55e" : "#f87171";
}
function moneyPair(usdValue: any, gbpValue: any, rate: number) {
  const u = Number(usdValue || 0);
  const g = gbpValue !== undefined && gbpValue !== null ? Number(gbpValue || 0) : u * rate;
  return (
    <>
      <b>{usd(u)}</b>
      <small>{gbp(g)}</small>
    </>
  );
}

function Card({ title, children, tone }: { title: string; children: React.ReactNode; tone?: string }) {
  return (
    <div className="card" style={{ borderColor: tone || "rgba(255,255,255,.1)" }}>
      <span className="card-label">{title}</span>
      <div className="card-value">{children}</div>
    </div>
  );
}

function Pill({ children, good }: { children: React.ReactNode; good?: boolean }) {
  return <span className={good ? "pill good" : "pill"}>{children}</span>;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number][0]>("overview");
  const [data, setData] = useState<any>(null);
  const [reports, setReports] = useState<any>(null);
  const [status, setStatus] = useState("Connecting…");
  const [message, setMessage] = useState("");
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("dashboard_api_key") || "");
  const [customTicker, setCustomTicker] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [chartCurrency, setChartCurrency] = useState<"USD" | "GBP">("GBP");

  const positions: Position[] = Array.isArray(data?.positions) ? data.positions : [];
  const scans: Scan[] = Array.isArray(data?.scans) ? data.scans : [];
  const trades: Trade[] = Array.isArray(data?.trades) ? data.trades : [];
  const closedTrades: any[] = Array.isArray(data?.closedTrades) ? data.closedTrades : [];
  const stockMemory: any[] = Array.isArray(data?.stockMemory) ? data.stockMemory : [];
  const logs: string[] = Array.isArray(data?.logs) ? data.logs : [];
  const warnings = [
    ...(Array.isArray(data?.alpacaRejectionEvents) ? data.alpacaRejectionEvents : []),
    ...(Array.isArray(data?.pdtWarningEvents) ? data.pdtWarningEvents : []),
  ];
  const rate = Number(data?.fx?.usdToGbp || 0.78);

  const fetchData = async () => {
    try {
      const [statusRes, reportsRes] = await Promise.allSettled([
        fetch(`${API_URL}/status`),
        fetch(`${API_URL}/reports`),
      ]);

      if (statusRes.status === "fulfilled") {
        const json = await statusRes.value.json();
        setData(json);
        const nextScans = Array.isArray(json?.scans) ? json.scans : [];
        if (!selectedSymbol && nextScans.length) setSelectedSymbol(nextScans[0].symbol);
      }

      if (reportsRes.status === "fulfilled" && reportsRes.value.ok) {
        setReports(await reportsRes.value.json());
      }

      setStatus("Connected");
    } catch (e) {
      console.error(e);
      setStatus("Connection failed");
    }
  };

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 5000);
    return () => clearInterval(id);
  }, []);

  const saveApiKey = () => {
    localStorage.setItem("dashboard_api_key", apiKey);
    setMessage("Dashboard key saved");
  };

  const action = async (endpoint: string) => {
    if (!apiKey.trim()) return setMessage("Enter dashboard password first");
    try {
      const res = await fetch(`${API_URL}${endpoint}`, {
        method: "POST",
        headers: { "x-api-key": apiKey.trim() },
      });
      const json = await res.json();
      setMessage(json.message || json.detail || "Action sent");
      fetchData();
    } catch (e) {
      console.error(e);
      setMessage("Action failed");
    }
  };

  const customBuy = async () => {
    const symbol = customTicker.trim().toUpperCase();
    if (!symbol) return setMessage("Enter a ticker first");
    if (!confirm(`Buy ${symbol}?`)) return;
    await action(`/custom-buy/${symbol}`);
    setCustomTicker("");
  };

  const selectedScan = useMemo(() => {
    if (!scans.length) return undefined;
    return scans.find((s) => s.symbol === selectedSymbol) || scans[0];
  }, [scans, selectedSymbol]);

  const equityChart = useMemo(() => {
    const rows = Array.isArray(data?.tradeTimeline) ? data.tradeTimeline : [];
    return rows.slice(-80).map((e: any, idx: number) => ({
      idx,
      equity: chartCurrency === "GBP" ? Number(e.equityGbp || e.equity * rate || 0) : Number(e.equity || 0),
      symbol: e.symbol || "",
      side: e.side || "",
    }));
  }, [data, chartCurrency, rate]);

  const report = reports || {};
  const totalGainLoss = Number(report.totalGainLoss ?? (data?.dbSummary?.totalPnl || 0));
  const marketOpen = data?.market?.label === "OPEN";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo">£</div>
          <div>
            <h1>TradeBot</h1>
            <p>{status}</p>
          </div>
        </div>

        <div className="status-box">
          <Pill good={!!data?.botEnabled}>Bot {data?.botEnabled ? "ON" : "OFF"}</Pill>
          <Pill good={marketOpen}>Market {data?.market?.label || "UNKNOWN"}</Pill>
          <Pill>{data?.paperMode ? "PAPER" : "LIVE"}</Pill>
        </div>

        <nav>
          {tabs.map(([id, label]) => (
            <button key={id} className={activeTab === id ? "nav active" : "nav"} onClick={() => setActiveTab(id)}>
              {label}
            </button>
          ))}
        </nav>

        <div className="key-box">
          <label>Dashboard password</label>
          <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="x-api-key" />
          <div className="mini-row">
            <button onClick={saveApiKey}>Save</button>
            <button className="secondary" onClick={() => { localStorage.removeItem("dashboard_api_key"); setApiKey(""); }}>Clear</button>
          </div>
          {message && <p className="message">{message}</p>}
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h2>{tabs.find(([id]) => id === activeTab)?.[1]}</h2>
            <p>{data?.name || "GBP Profit Trading Bot"} · USD/GBP {Number(rate).toFixed(4)}</p>
          </div>
          <div className="actions compact-actions">
            <button onClick={fetchData}>Refresh</button>
            <button className="buy" onClick={() => action("/manual-buy")}>Money Buy</button>
            <button className="danger" onClick={() => action("/manual-sell")}>Sell Worst</button>
          </div>
        </header>

        {!data && <div className="empty">Loading bot status…</div>}

        {data && activeTab === "overview" && (
          <>
            <section className="cards compact-grid">
              <Card title="Equity">{moneyPair(data.account?.equity, data.account?.equityGbp, rate)}</Card>
              <Card title="Buying Power">{moneyPair(data.account?.buyingPower, data.account?.buyingPowerGbp, rate)}</Card>
              <Card title="Day PnL" tone={colour(data.account?.pnlDay)}><b style={{ color: colour(data.account?.pnlDay) }}>{usd(data.account?.pnlDay)}</b><small style={{ color: colour(data.account?.pnlDay) }}>{gbp(data.account?.pnlDayGbp ?? data.account?.pnlDay * rate)}</small></Card>
              <Card title="Total Gain/Loss" tone={colour(totalGainLoss)}><b style={{ color: colour(totalGainLoss) }}>{usd(totalGainLoss)}</b><small style={{ color: colour(totalGainLoss) }}>{gbp(report.totalGainLossGbp ?? totalGainLoss * rate)} · {pct(report.returnPct)}</small></Card>
              <Card title="Positions"><b>{positions.length}/{data.maxPositions || 0}</b><small>Next buy {usd(data.newPositionNotional)}</small></Card>
              <Card title="PDT / Buys"><b>{data.todayBuyCount || 0}/{data.maxNewBuysPerDayPdtAware || "—"}</b><small>{(data.lockedSymbolsToday || []).length} locked today</small></Card>
            </section>

            <section className="split">
              <div className="panel grow">
                <div className="panel-head">
                  <h3>Equity Timeline</h3>
                  <div className="toggle">
                    <button className={chartCurrency === "USD" ? "active" : ""} onClick={() => setChartCurrency("USD")}>USD</button>
                    <button className={chartCurrency === "GBP" ? "active" : ""} onClick={() => setChartCurrency("GBP")}>GBP</button>
                  </div>
                </div>
                <div className="chart-box">
                  {equityChart.length ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={equityChart}>
                        <CartesianGrid stroke="rgba(255,255,255,.08)" />
                        <XAxis dataKey="idx" />
                        <YAxis />
                        <Tooltip formatter={(v: any) => chartCurrency === "GBP" ? gbp(v) : usd(v)} />
                        <Line dataKey="equity" stroke="#22c55e" strokeWidth={2} dot={false} />
                        {equityChart.map((e: any) => (
                          <ReferenceDot key={`${e.idx}-${e.side}-${e.symbol}`} x={e.idx} y={e.equity} r={4} fill={e.side === "BUY" ? "#22c55e" : "#ef4444"} />
                        ))}
                      </LineChart>
                    </ResponsiveContainer>
                  ) : <div className="empty small">Timeline appears after trades/backfill.</div>}
                </div>
              </div>

              <div className="panel side-panel">
                <h3>Live Summary</h3>
                <div className="mini-list">
                  <span>Sniper</span><b>{data.sniperModeEnabled ? "ON" : "OFF"}</b>
                  <span>A+ Gate</span><b>{data.aPlusGateEnabled ? "ON" : "OFF"}</b>
                  <span>Auto Universe</span><b>{data.autoUniverseEnabled ? "ON" : "OFF"}</b>
                  <span>PDT-aware</span><b>{data.pdtAwareModeEnabled ? "ON" : "OFF"}</b>
                  <span>Closed trades</span><b>{data.dbSummary?.closedTrades || 0}</b>
                  <span>Win rate</span><b>{pct((data.dbSummary?.winRate || 0) * 100)}</b>
                </div>
              </div>
            </section>
          </>
        )}

        {data && activeTab === "money" && (
          <>
            <section className="cards compact-grid">
              <Card title="Total Deposited">{moneyPair(report.totalDeposited, report.totalDepositedGbp, rate)}</Card>
              <Card title="Current Value">{moneyPair(report.currentEquity ?? data.account?.equity, report.currentEquityGbp ?? data.account?.equityGbp, rate)}</Card>
              <Card title="Total Gain/Loss" tone={colour(totalGainLoss)}><b style={{ color: colour(totalGainLoss) }}>{usd(totalGainLoss)}</b><small style={{ color: colour(totalGainLoss) }}>{gbp(report.totalGainLossGbp ?? totalGainLoss * rate)} · {pct(report.returnPct)}</small></Card>
              <Card title="Earned Since Deposit" tone="#22c55e">{moneyPair(report.earnedSinceDeposit, report.earnedSinceDepositGbp, rate)}</Card>
              <Card title="Lost Since Deposit" tone="#f87171">{moneyPair(report.lostSinceDeposit, report.lostSinceDepositGbp, rate)}</Card>
              <Card title="Open PnL" tone={colour(report.openPnl)}><b style={{ color: colour(report.openPnl) }}>{usd(report.openPnl)}</b><small>{gbp(report.openPnlGbp)}</small></Card>
            </section>
            <section className="panel">
              <div className="panel-head"><h3>Report Details</h3><Pill>{report.depositSource || "status/db fallback"}</Pill></div>
              <div className="report-grid">
                <div><span>Withdrawn</span><b>{usd(report.totalWithdrawn)} / {gbp(report.totalWithdrawnGbp)}</b></div>
                <div><span>Net deposited</span><b>{usd(report.netDeposited)} / {gbp(report.netDepositedGbp)}</b></div>
                <div><span>Realised net</span><b style={{ color: colour(report.realisedNet) }}>{usd(report.realisedNet)} / {gbp(report.realisedNetGbp)}</b></div>
                <div><span>Gross wins</span><b style={{ color: "#22c55e" }}>{usd(report.realisedGains)} / {gbp(report.realisedGainsGbp)}</b></div>
                <div><span>Gross losses</span><b style={{ color: "#f87171" }}>{usd(report.realisedLosses)} / {gbp(report.realisedLossesGbp)}</b></div>
                <div><span>Activity count</span><b>{report.depositActivityCount ?? 0}</b></div>
              </div>
              {report.depositErrors?.length ? <p className="warning">Deposit activity warning: {report.depositErrors.join(" | ")}</p> : null}
            </section>
          </>
        )}

        {data && activeTab === "positions" && (
          <section className="panel">
            <div className="panel-head"><h3>Open Positions</h3><span>{positions.length} open</span></div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Symbol</th><th>Value</th><th>Entry</th><th>Price</th><th>PnL</th><th>Trail</th><th></th></tr></thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={p.symbol}>
                      <td><b>{p.symbol}</b>{p.boughtToday ? <small className="yellow"> bought today</small> : null}</td>
                      <td>{usd(p.marketValue)}<small>{gbp(p.marketValueGbp ?? p.marketValue * rate)}</small></td>
                      <td>{usd(p.entry)}</td>
                      <td>{usd(p.price)}</td>
                      <td style={{ color: colour(p.pnlPct) }}>{usd(p.pnl)}<small>{pct(p.pnlPct)}</small></td>
                      <td>{p.trailingActive ? <span className="green">Floor {usd(p.trailFloor)}</span> : <span className="yellow">Starts {usd(p.trailStartPrice)}</span>}</td>
                      <td><button className="danger" onClick={() => action(`/sell/${p.symbol}`)}>Sell</button></td>
                    </tr>
                  ))}
                  {!positions.length && <tr><td colSpan={7}>No open positions.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {data && activeTab === "scanner" && (
          <section className="split">
            <div className="panel grow">
              <div className="panel-head"><h3>Scanner Chart</h3><select value={selectedScan?.symbol || ""} onChange={(e) => setSelectedSymbol(e.target.value)}>{scans.map((s) => <option key={s.symbol}>{s.symbol}</option>)}</select></div>
              <div className="chart-box scanner">
                {selectedScan?.priceCurve?.length ? (
                  <ResponsiveContainer width="100%" height="100%"><LineChart data={selectedScan.priceCurve}><CartesianGrid stroke="rgba(255,255,255,.08)" /><XAxis dataKey="t" /><YAxis /><Tooltip /><Line dataKey="value" stroke="#38bdf8" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer>
                ) : <div className="empty small">No chart data yet.</div>}
              </div>
            </div>
            <div className="panel grow">
              <div className="panel-head"><h3>Scan List</h3><span>{scans.length} symbols</span></div>
              <div className="scan-grid">
                {scans.map((s) => <div key={s.symbol} className={(s.aPlusPass || s.sniperPass) ? "scan pass" : "scan"} onClick={() => setSelectedSymbol(s.symbol)}><b>{s.symbol}</b><span>{usd(s.price)} · conf {(s.confidence || 0).toFixed(2)}</span><small>{s.aPlusPass || s.sniperPass ? "PASS" : s.aPlusReason || s.sniperReason || "waiting"}</small></div>)}
                {!scans.length && <div className="empty small">No scan data yet. Normal while market is closed.</div>}
              </div>
            </div>
          </section>
        )}

        {data && activeTab === "activity" && (
          <section className="split">
            <div className="panel grow">
              <h3>Recent Trades</h3>
              <div className="activity-list">{trades.slice().reverse().map((t, i) => <div key={i} className={t.side === "BUY" ? "activity buy" : "activity sell"}><b>{t.side || "—"} {t.symbol || "—"}</b><span>{t.time || "—"} · {t.amount ? `${usd(t.amount)} / ${gbp(t.amountGbp ?? t.amount * rate)}` : ""} {t.pnl !== undefined ? ` · PnL ${usd(t.pnl)} (${pct(t.pnlPct)})` : ""}</span><small>{t.reason}</small></div>)}{!trades.length && <p>No trades yet.</p>}</div>
            </div>
            <div className="panel grow">
              <h3>Closed Trades / Memory</h3>
              <div className="activity-list">{closedTrades.slice(-30).reverse().map((t, i) => <div key={i} className={Number(t.pnl || 0) >= 0 ? "activity buy" : "activity sell"}><b>{t.symbol} {pct(t.pnlPct)}</b><span>{usd(t.pnl)} / {gbp(t.pnlGbp)}</span><small>Entry {usd(t.entryPrice)} → Exit {usd(t.exitPrice)}</small></div>)}{!closedTrades.length && <p>No matched closed trades yet.</p>}</div>
            </div>
          </section>
        )}

        {data && activeTab === "admin" && (
          <section className="split">
            <div className="panel grow">
              <h3>Controls</h3>
              <div className="actions">
                <button onClick={() => action("/resume")}>Resume</button>
                <button className="warn" onClick={() => action("/pause")}>Pause</button>
                <button onClick={() => action("/manual-override/on")}>Override ON</button>
                <button className="secondary" onClick={() => action("/manual-override/off")}>Override OFF</button>
                <button className="danger" onClick={() => action("/emergency-sell")}>Emergency Sell All</button>
              </div>
              <div className="custom-buy"><input value={customTicker} onChange={(e) => setCustomTicker(e.target.value.toUpperCase())} placeholder="Ticker e.g. AMD" /><button className="buy" onClick={customBuy}>Buy Custom</button></div>
              <h3>Maintenance</h3>
              <div className="actions"><button onClick={() => action("/backfill-trades")}>Backfill Orders</button><button onClick={() => action("/rebuild-closed-trades")}>Rebuild PnL</button><button onClick={() => action("/refresh-universe")}>Refresh Universe</button></div>
            </div>
            <div className="panel grow">
              <h3>Warnings & Logs</h3>
              <div className="log-box">
                {warnings.map((w: any, i: number) => <div key={`w-${i}`} className="log warning-line">{w.time || "—"} | {w.message || w.reason || w.error}</div>)}
                {logs.map((l, i) => <div key={`l-${i}`} className="log">{l}</div>)}
                {!warnings.length && !logs.length && <p>No logs yet.</p>}
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
