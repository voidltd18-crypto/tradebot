
import React, { useEffect, useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis
} from "recharts";

const API_URL = import.meta.env.VITE_API_BASE || "https://tradebot-0myo.onrender.com";

type AnyObj = Record<string, any>;

const usd = (v: any) => `$${Number(v || 0).toFixed(2)}`;
const gbp = (v: any) => `£${Number(v || 0).toFixed(2)}`;
const pct = (v: any) => `${Number(v || 0).toFixed(2)}%`;
const tone = (v: any) => Number(v || 0) >= 0 ? "gain" : "loss";

function Card({ title, children, wide = false }: { title?: string; children: React.ReactNode; wide?: boolean }) {
  return <section className={`card ${wide ? "wide" : ""}`}>{title && <h2>{title}</h2>}{children}</section>;
}

function Stat({ label, value, sub, className = "" }: { label: string; value: React.ReactNode; sub?: React.ReactNode; className?: string }) {
  return <section className="card stat"><span>{label}</span><strong className={className}>{value}</strong>{sub && <small>{sub}</small>}</section>;
}

function formatLabel(raw: any, fallback: number) {
  if (!raw) return `#${fallback + 1}`;
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return String(raw).slice(0, 16);
  return d.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function formatDay(raw: any, fallback: number) {
  if (!raw) return `Session ${fallback + 1}`;
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return String(raw).slice(0, 10);
  return d.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
}

export default function App() {
  const [tab, setTab] = useState("overview");
  const [data, setData] = useState<AnyObj>({});
  const [reports, setReports] = useState<AnyObj>({});
  const [pro, setPro] = useState<AnyObj>({});
  const [status, setStatus] = useState("Connecting...");
  const [message, setMessage] = useState("Ready.");
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("dashboard_api_key") || "");
  const [customSymbol, setCustomSymbol] = useState("");
  const [customAmount, setCustomAmount] = useState("25");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [chartCurrency, setChartCurrency] = useState<"GBP" | "USD">("GBP");

  const rate = Number(data?.fx?.usdToGbp || 0.78);
  const account = data?.account || {};
  const market = data?.market || {};
  const scans = Array.isArray(data?.scans) ? data.scans : [];
  const positions = Array.isArray(data?.positions) ? data.positions : [];
  const logs = Array.isArray(data?.logs) ? data.logs : [];
  const trades = Array.isArray(data?.trades) ? data.trades : (Array.isArray(data?.tradeTimeline) ? data.tradeTimeline : []);
  const closedTrades = Array.isArray(reports?.closedTrades) ? reports.closedTrades : (Array.isArray(data?.closedTrades) ? data.closedTrades : []);
  const lockedToday = pro?.lockedToday || data?.lockedSymbolsToday || data?.soldTodayLocks || [];
  const pdtWarnings = pro?.pdtWarnings || data?.pdtWarningEvents || [];
  const alpacaRejections = pro?.alpacaRejections || data?.alpacaRejections || [];
  const autoUniverse = data?.autoUniverse || pro?.autoUniverse || {};
  const sinceUpgrade = pro?.sinceUpgrade || reports?.sinceUpgrade || data?.sinceUpgrade || {};
  const equityHistory = Array.isArray(reports?.equityHistory) ? reports.equityHistory : trades;

  async function fetchJson(path: string) {
    const r = await fetch(`${API_URL}${path}`);
    if (!r.ok) throw new Error(`${path} ${r.status}`);
    return r.json();
  }

  async function refresh() {
    try {
      const [s, r, p] = await Promise.allSettled([
        fetchJson("/status"),
        fetchJson("/reports"),
        fetchJson("/pro-dashboard"),
      ]);
      if (s.status === "fulfilled") {
        setData(s.value || {});
        const nextScans = Array.isArray(s.value?.scans) ? s.value.scans : [];
        if (!selectedSymbol && nextScans.length) setSelectedSymbol(nextScans[0].symbol);
      }
      if (r.status === "fulfilled") setReports(r.value || {});
      if (p.status === "fulfilled") setPro(p.value || {});
      setStatus("Connected");
    } catch (e) {
      console.error(e);
      setStatus("Connection failed");
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 8000);
    return () => clearInterval(id);
  }, []);

  async function post(endpoint: string, body?: AnyObj) {
    if (!apiKey.trim()) {
      setMessage("Enter your dashboard password in Admin first.");
      return;
    }
    try {
      const r = await fetch(`${API_URL}${endpoint}`, {
        method: "POST",
        headers: {
          "x-api-key": apiKey.trim(),
          "content-type": "application/json",
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      const j = await r.json();
      setMessage(j.message || j.detail || JSON.stringify(j));
      refresh();
    } catch (e: any) {
      setMessage(`Action failed: ${e.message || e}`);
    }
  }

  function saveKey() {
    localStorage.setItem("dashboard_api_key", apiKey);
    setMessage("Dashboard password saved.");
  }

  const totalDeposited = Number(reports.totalDeposited || 0);
  const earned = Number(reports.earnedSinceDeposit || 0);
  const totalGainLoss = Number(reports.totalGainLoss || 0);
  const lost = Number(reports.lostSinceDeposit || 0);

  const reportChart = useMemo(() => {
    return equityHistory.map((e: AnyObj, i: number) => {
      const raw = e.time || e.timestamp || e.t || e.label || "";
      const equityUsd = Number(e.equity ?? e.value ?? account.equity ?? 0);
      const pnlUsd = Number(e.pnl || 0);
      return {
        idx: i,
        label: formatLabel(raw, i),
        day: formatDay(raw, i),
        equity: chartCurrency === "GBP" ? Number(e.equityGbp ?? equityUsd * rate) : equityUsd,
        pnl: chartCurrency === "GBP" ? Number(e.pnlGbp ?? pnlUsd * rate) : pnlUsd,
        symbol: e.symbol || "",
      };
    }).filter((x: AnyObj) => Number.isFinite(x.equity));
  }, [equityHistory, chartCurrency, rate, account.equity]);

  const dailyPnlChart = useMemo(() => {
    const m: Record<string, number> = {};
    for (const p of reportChart) m[p.day] = (m[p.day] || 0) + Number(p.pnl || 0);
    return Object.entries(m).map(([day, pnl]) => ({ day, pnl }));
  }, [reportChart]);

  const selectedScan = scans.find((s: AnyObj) => s.symbol === selectedSymbol) || scans[0];
  const scannerChart = selectedScan?.priceCurve || selectedScan?.curve || [];

  const tabs = ["overview","reports","positions","scanner","risk","activity","admin"];

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">Rebuilt Sniper Profit Bot</p>
          <h1>TradeBot Pro</h1>
        </div>
        <div className="pills">
          <span className={`pill ${status === "Connected" ? "ok" : "bad"}`}>{status}</span>
          <span className={`pill ${market?.isOpen ? "ok" : "warn"}`}>Market {market?.label || "UNKNOWN"}</span>
          <span className={`pill ${data?.botEnabled ? "ok" : "bad"}`}>Bot {data?.botEnabled ? "ON" : "OFF"}</span>
          <span className="pill">{data?.paperMode ? "PAPER" : "LIVE"}</span>
        </div>
      </header>

      <section className="stats">
        <Stat label="Equity" value={gbp(Number(account.equity || 0) * rate)} sub={usd(account.equity)} />
        <Stat label="Buying Power" value={gbp(Number(account.buyingPower || 0) * rate)} sub={usd(account.buyingPower)} />
        <Stat label="Day PnL" value={gbp(Number(account.pnlDay || 0) * rate)} sub={usd(account.pnlDay)} className={tone(account.pnlDay)} />
        <Stat label="Total Gain/Loss" value={gbp(totalGainLoss * rate)} sub={`${usd(totalGainLoss)} · Deposited ${gbp(totalDeposited * rate)}`} className={tone(totalGainLoss)} />
        <Stat label="Since Upgrade" value={gbp(Number(sinceUpgrade.sinceUpgradePnl || 0) * rate)} sub={`${usd(sinceUpgrade.sinceUpgradePnl)} · ${pct(sinceUpgrade.sinceUpgradePnlPct)}`} className={tone(sinceUpgrade.sinceUpgradePnl)} />
      </section>

      <nav className="tabs">
        {tabs.map(t => <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t.toUpperCase()}</button>)}
      </nav>

      {tab === "overview" && (
        <main className="grid two">
          <Card title="Controls">
            <div className="actions">
              <button onClick={refresh}>Refresh Data</button>
              <button onClick={() => post("/manual-buy")}>Money Buy</button>
              <button className="danger" onClick={() => post("/manual-sell")}>Sell Worst</button>
              <button className="purple" onClick={() => post("/refresh-universe")}>🔄 Weekly Stock Refresh</button>
              <button className="ghost" onClick={() => post("/pause")}>Pause</button>
              <button onClick={() => post("/resume")}>Resume</button>
            </div>
            <p className="notice">{message}</p>
          </Card>

          <Card title="Custom Buy">
            <div className="buy-row">
              <input value={customSymbol} onChange={e => setCustomSymbol(e.target.value.toUpperCase())} placeholder="Ticker e.g. NVDA" />
              <input value={customAmount} onChange={e => setCustomAmount(e.target.value)} placeholder="USD amount" />
              <button onClick={() => post("/custom-buy-json", { symbol: customSymbol, amount: Number(customAmount || 0) })}>Buy</button>
            </div>
            <p className="muted">Uses dashboard password. Keep amount small while testing.</p>
          </Card>

          <Card title="Live Summary">
            <div className="summary">
              <div><span>Positions</span><b>{positions.length}/{data?.maxPositions ?? "—"}</b></div>
              <div><span>Next buy</span><b>{gbp(Number(data?.newPositionNotional || 0) * rate)} / {usd(data?.newPositionNotional)}</b></div>
              <div><span>Win rate</span><b>{Number((data?.dbSummary?.winRate || 0) * 100).toFixed(2)}%</b></div>
              <div><span>Universe active</span><b>{autoUniverse?.activeSymbols?.length || 0}/{autoUniverse?.size || 0}</b></div>
              <div><span>Locked today</span><b>{lockedToday.length}</b></div>
            </div>
          </Card>

          <Card title="Auto Universe Scores">
            <div className="scan-grid compact">
              {(autoUniverse?.rows || []).slice(0, 24).map((r: AnyObj) => (
                <article className="scan" key={r.symbol}>
                  <div><b>{r.symbol}</b><strong>Score {Number(r.score || 0).toFixed(2)}</strong></div>
                  <p>{r.reason || "weekly candidate"}</p>
                </article>
              ))}
              {!(autoUniverse?.rows || []).length && <p className="muted">No auto-universe rows yet. Press Weekly Stock Refresh.</p>}
            </div>
          </Card>
        </main>
      )}

      {tab === "reports" && (
        <main>
          <section className="stats">
            <Stat label="Deposited" value={gbp(totalDeposited * rate)} sub={`${usd(totalDeposited)} · ${reports.depositSource || ""}`} />
            <Stat label="Earned Since Deposit" value={gbp(earned * rate)} sub={usd(earned)} className={tone(earned)} />
            <Stat label="Lost Since Deposit" value={gbp(lost * rate)} sub={usd(lost)} className="loss" />
            <Stat label="Current Equity" value={gbp(Number((reports.currentEquity ?? account.equity) || 0) * rate)} sub={usd(reports.currentEquity ?? account.equity)} />
            <Stat label="Since Upgrade" value={gbp(Number(sinceUpgrade.sinceUpgradePnl || 0) * rate)} sub={`${usd(sinceUpgrade.sinceUpgradePnl)} · ${pct(sinceUpgrade.sinceUpgradePnlPct)}`} className={tone(sinceUpgrade.sinceUpgradePnl)} />
          </section>

          <Card title="Since Upgrade Tracker">
            <div className="summary">
              <div><span>Baseline set</span><b>{sinceUpgrade.baselineSet ? "Yes" : "Not yet"}</b></div>
              <div><span>Baseline date</span><b>{sinceUpgrade.baselineAt || "Press reset to start from now"}</b></div>
              <div><span>Baseline equity</span><b>{gbp(Number(sinceUpgrade.baselineEquity || 0) * rate)} / {usd(sinceUpgrade.baselineEquity)}</b></div>
              <div><span>Current equity</span><b>{gbp(Number(sinceUpgrade.currentEquity || account.equity || 0) * rate)} / {usd(sinceUpgrade.currentEquity || account.equity)}</b></div>
              <div><span>Since-upgrade PnL</span><b className={tone(sinceUpgrade.sinceUpgradePnl)}>{gbp(Number(sinceUpgrade.sinceUpgradePnl || 0) * rate)} / {usd(sinceUpgrade.sinceUpgradePnl)} / {pct(sinceUpgrade.sinceUpgradePnlPct)}</b></div>
            </div>
            <div className="actions tracker-actions">
              <button className="purple" onClick={() => post("/reset-upgrade-baseline")}>Reset Upgrade Baseline</button>
            </div>
            <p className="muted">Use this after a major bot update. It separates old historical losses from new bot performance.</p>
          </Card>

          <Card title="Price / Equity History">
            <div className="chart-controls">
              <button className={chartCurrency === "GBP" ? "active" : ""} onClick={() => setChartCurrency("GBP")}>GBP</button>
              <button className={chartCurrency === "USD" ? "active" : ""} onClick={() => setChartCurrency("USD")}>USD</button>
            </div>
            <div className="chart">
              {reportChart.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={reportChart}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#263450" />
                    <XAxis dataKey="label" stroke="#94a3b8" minTickGap={28} />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip formatter={(v: any) => chartCurrency === "GBP" ? gbp(v) : usd(v)} />
                    <Area type="monotone" dataKey="equity" stroke="#38bdf8" fill="#38bdf833" />
                  </AreaChart>
                </ResponsiveContainer>
              ) : <p className="muted">No history yet. It builds as trades/equity snapshots are recorded.</p>}
            </div>
          </Card>

          <Card title="Daily PnL">
            <div className="chart small-chart">
              {dailyPnlChart.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={dailyPnlChart}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#263450" />
                    <XAxis dataKey="day" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip formatter={(v: any) => chartCurrency === "GBP" ? gbp(v) : usd(v)} />
                    <Bar dataKey="pnl" fill="#38bdf8" />
                  </BarChart>
                </ResponsiveContainer>
              ) : <p className="muted">Daily PnL appears once trades close.</p>}
            </div>
          </Card>

          <Card title="Closed Trade History">
            <div className="table-wrap">
              <table>
                <thead><tr><th>Time</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th><th>%</th></tr></thead>
                <tbody>
                  {closedTrades.slice(-100).reverse().map((t: AnyObj, i: number) => (
                    <tr key={i}>
                      <td>{t.time || "—"}</td><td>{t.symbol}</td><td>{usd(t.entryPrice)}</td><td>{usd(t.exitPrice)}</td><td>{Number(t.qty || 0).toFixed(4)}</td>
                      <td className={tone(t.pnl)}>{gbp(Number(t.pnl || 0) * rate)} / {usd(t.pnl)}</td><td className={tone(t.pnl)}>{pct(t.pnlPct)}</td>
                    </tr>
                  ))}
                  {!closedTrades.length && <tr><td colSpan={7}>No closed trades yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </Card>
        </main>
      )}

      {tab === "positions" && (
        <Card title="All Positions">
          <div className="position-list">
            {positions.map((p: AnyObj) => (
              <article className="position" key={p.symbol}>
                <div><h3>{p.symbol}</h3><p>Qty {Number(p.qty || 0).toFixed(4)} · Entry {usd(p.entry)} · Price {usd(p.price)}</p><p>Value <b>{gbp(p.marketValueGbp ?? p.marketValue * rate)}</b> / {usd(p.marketValue)}</p></div>
                <div className="position-side"><b className={tone(p.pnl)}>PnL {gbp(p.pnlGbp ?? p.pnl * rate)} / {usd(p.pnl)} / {pct(p.pnlPct)}</b><span>{p.trailingActive ? `Trailing floor ${usd(p.trailFloor)}` : `Trail starts ${usd(p.trailStartPrice)}`}</span><button className="danger" onClick={() => post(`/sell/${p.symbol}`)}>Sell {p.symbol}</button></div>
              </article>
            ))}
            {!positions.length && <p className="muted">No open positions.</p>}
          </div>
        </Card>
      )}

      {tab === "scanner" && (
        <main>
          <Card title="Scanner Price History">
            {scans.length > 0 && <select value={selectedSymbol} onChange={(e) => setSelectedSymbol(e.target.value)}>{scans.map((s: AnyObj) => <option key={s.symbol}>{s.symbol}</option>)}</select>}
            <div className="chart">
              {scannerChart.length ? (
                <ResponsiveContainer width="100%" height="100%"><LineChart data={scannerChart}><CartesianGrid strokeDasharray="3 3" stroke="#263450" /><XAxis dataKey="t" stroke="#94a3b8" /><YAxis stroke="#94a3b8" /><Tooltip /><Line type="monotone" dataKey="value" stroke="#38bdf8" dot={false} /></LineChart></ResponsiveContainer>
              ) : <p className="muted">No scanner price history yet.</p>}
            </div>
          </Card>
          <Card title="Scanner Cards">
            <div className="scan-grid">{scans.map((s: AnyObj) => <article className="scan" key={s.symbol}><div><b>{s.symbol}</b><strong>{usd(s.price)}</strong></div><p>Confidence {Number(s.confidence || 0).toFixed(2)} · Quality {Number(s.qualityScore || 0).toFixed(4)}</p><span className={s.readyToBuy ? "ready" : ""}>{s.readyToBuy ? "Ready" : (s.aPlusReason || s.sniperReason || "Watching")}</span></article>)}</div>
          </Card>
        </main>
      )}

      {tab === "risk" && (
        <main className="grid two">
          <Card title="PDT Tracker">
            <div className="summary">
              <div><span>Today buys</span><b>{data?.todayBuyCount ?? "—"}</b></div>
              <div><span>Max new buys</span><b>{data?.maxNewBuysPerDayPdtAware ?? "—"}</b></div>
              <div><span>PDT warnings</span><b>{pdtWarnings.length}</b></div>
              <div><span>Alpaca rejections</span><b>{alpacaRejections.length}</b></div>
            </div>
          </Card>
          <Card title="Sold / Locked Today">
            <div className="tag-list">{lockedToday.length ? lockedToday.map((s: any, i: number) => <span key={i}>{typeof s === "string" ? s : (s.symbol || JSON.stringify(s))}</span>) : <p className="muted">No locked symbols today.</p>}</div>
          </Card>
          <Card title="PDT / Alpaca Warnings" wide>
            <div className="log-list">
              {[...pdtWarnings, ...alpacaRejections].slice(-80).reverse().map((x: any, i: number) => <div key={i}>{typeof x === "string" ? x : JSON.stringify(x)}</div>)}
              {![...pdtWarnings, ...alpacaRejections].length && <p className="muted">No warnings.</p>}
            </div>
          </Card>
        </main>
      )}

      {tab === "activity" && (
        <main className="grid two">
          <Card title="Recent Trades"><div className="log-list">{trades.slice(-60).reverse().map((t: AnyObj, i: number) => <div key={i}>{t.time || "—"} · <b>{t.side} {t.symbol}</b> · {t.reason || ""}</div>)}{!trades.length && <p className="muted">No trades yet.</p>}</div></Card>
          <Card title="Logs"><div className="log-list">{logs.map((l: string, i: number) => <div key={i}>{l}</div>)}{!logs.length && <p className="muted">No logs.</p>}</div></Card>
        </main>
      )}

      {tab === "admin" && (
        <Card title="Admin">
          <label className="field"><span>Dashboard password</span><input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} /></label>
          <div className="actions"><button onClick={saveKey}>Save</button><button className="ghost" onClick={() => { localStorage.removeItem("dashboard_api_key"); setApiKey(""); }}>Clear</button></div>
          <pre>{JSON.stringify({ api: API_URL, botEnabled: data?.botEnabled, market: data?.market, autoUniverse, lockedToday, sinceUpgrade, proKeys: Object.keys(pro || {}) }, null, 2)}</pre>
        </Card>
      )}
    </div>
  );
}
