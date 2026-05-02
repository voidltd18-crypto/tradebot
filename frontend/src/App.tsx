
import React, { useEffect, useMemo, useState } from "react";
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis
} from "recharts";

const API_URL = import.meta.env.VITE_API_BASE || "https://tradebot-0myo.onrender.com";

type AnyObj = Record<string, any>;

function usd(n: any) {
  return `$${Number(n || 0).toFixed(2)}`;
}
function gbp(n: any) {
  return `£${Number(n || 0).toFixed(2)}`;
}
function pct(n: any) {
  return `${Number(n || 0).toFixed(2)}%`;
}
function tone(n: any) {
  return Number(n || 0) >= 0 ? "gain" : "loss";
}

function Card({ title, children, wide = false }: { title?: string; children: React.ReactNode; wide?: boolean }) {
  return <section className={`card ${wide ? "wide" : ""}`}>{title && <h2>{title}</h2>}{children}</section>;
}

function Stat({ label, value, sub, className = "" }: { label: string; value: React.ReactNode; sub?: React.ReactNode; className?: string }) {
  return <section className="card stat"><span>{label}</span><strong className={className}>{value}</strong>{sub && <small>{sub}</small>}</section>;
}

export default function App() {
  const [tab, setTab] = useState("overview");
  const [data, setData] = useState<AnyObj>({});
  const [reports, setReports] = useState<AnyObj>({});
  const [status, setStatus] = useState("Connecting...");
  const [message, setMessage] = useState("");
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("dashboard_api_key") || "");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [chartCurrency, setChartCurrency] = useState<"USD" | "GBP">("USD");

  const rate = Number(data?.fx?.usdToGbp || 0.78);
  const scans = Array.isArray(data?.scans) ? data.scans : [];
  const positions = Array.isArray(data?.positions) ? data.positions : [];
  const trades = Array.isArray(data?.trades) ? data.trades : [];
  const logs = Array.isArray(data?.logs) ? data.logs : [];
  const closedTrades = Array.isArray(reports?.closedTrades) ? reports.closedTrades : (Array.isArray(data?.closedTrades) ? data.closedTrades : []);
  const equityHistory = Array.isArray(reports?.equityHistory) ? reports.equityHistory : (Array.isArray(data?.tradeTimeline) ? data.tradeTimeline : []);

  async function fetchData() {
    try {
      const [statusRes, reportRes] = await Promise.allSettled([
        fetch(`${API_URL}/status`).then(r => r.json()),
        fetch(`${API_URL}/reports`).then(r => r.json()),
      ]);
      if (statusRes.status === "fulfilled") {
        setData(statusRes.value);
        const nextScans = Array.isArray(statusRes.value?.scans) ? statusRes.value.scans : [];
        if (!selectedSymbol && nextScans.length) setSelectedSymbol(nextScans[0].symbol);
      }
      if (reportRes.status === "fulfilled") setReports(reportRes.value || {});
      setStatus("Connected");
    } catch (e) {
      console.error(e);
      setStatus("Connection failed");
    }
  }

  useEffect(() => {
    fetchData();
    const i = setInterval(fetchData, 8000);
    return () => clearInterval(i);
  }, []);

  function saveApiKey() {
    localStorage.setItem("dashboard_api_key", apiKey);
    setMessage("Dashboard password saved.");
  }

  async function action(endpoint: string) {
    if (!apiKey.trim()) {
      setMessage("Enter your dashboard password first.");
      return;
    }
    try {
      const res = await fetch(`${API_URL}${endpoint}`, {
        method: "POST",
        headers: { "x-api-key": apiKey.trim() },
      });
      const json = await res.json();
      setMessage(json.message || json.detail || JSON.stringify(json));
      fetchData();
    } catch (e) {
      setMessage("Action failed.");
    }
  }

  async function refreshUniverse() {
    await action("/refresh-universe");
  }

  const selectedScan = useMemo(() => {
    if (!scans.length) return undefined;
    return scans.find((s: AnyObj) => s.symbol === selectedSymbol) || scans[0];
  }, [scans, selectedSymbol]);

  const reportChart = useMemo(() => {
    return equityHistory.map((e: AnyObj, i: number) => ({
      idx: i,
      equity: chartCurrency === "GBP"
        ? Number(e.equityGbp ?? e.valueGbp ?? Number(e.equity || e.value || 0) * rate)
        : Number(e.equity ?? e.value ?? 0),
      pnl: chartCurrency === "GBP"
        ? Number(e.pnlGbp ?? Number(e.pnl || 0) * rate)
        : Number(e.pnl || 0),
      label: e.time || e.timestamp || e.t || String(i),
      symbol: e.symbol || "",
      side: e.side || "",
    }));
  }, [equityHistory, chartCurrency, rate]);

  const scannerChart = selectedScan?.priceCurve || [];

  const totalDeposited = reports.totalDeposited ?? 0;
  const earned = reports.earnedSinceDeposit ?? 0;
  const totalGainLoss = reports.totalGainLoss ?? 0;
  const lost = reports.lostSinceDeposit ?? 0;

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">Rebuilt Sniper Profit Bot</p>
          <h1>TradeBot</h1>
        </div>
        <div className="pills">
          <span className="pill ok">{status}</span>
          <span className={`pill ${data?.market?.isOpen ? "ok" : "warn"}`}>Market {data?.market?.label || "UNKNOWN"}</span>
          <span className={`pill ${data?.botEnabled ? "ok" : "bad"}`}>Bot {data?.botEnabled ? "ON" : "OFF"}</span>
          <span className="pill">{data?.paperMode ? "PAPER" : "LIVE"}</span>
        </div>
      </header>

      <section className="stats">
        <Stat label="Equity" value={usd(data?.account?.equity)} sub={gbp(Number(data?.account?.equity || 0) * rate)} />
        <Stat label="Buying Power" value={usd(data?.account?.buyingPower)} sub={gbp(Number(data?.account?.buyingPower || 0) * rate)} />
        <Stat label="Day PnL" value={usd(data?.account?.pnlDay)} sub={gbp(Number(data?.account?.pnlDay || 0) * rate)} className={tone(data?.account?.pnlDay)} />
        <Stat label="Total Gain/Loss" value={usd(totalGainLoss)} sub={`Deposited ${usd(totalDeposited)}`} className={tone(totalGainLoss)} />
      </section>

      <nav className="tabs">
        {["overview","reports","positions","scanner","activity","admin"].map(t => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t.toUpperCase()}</button>
        ))}
      </nav>

      {tab === "overview" && (
        <main className="grid two">
          <Card title="Controls">
            <div className="actions">
              <button onClick={fetchData}>Refresh Data</button>
              <button onClick={() => action("/manual-buy")}>Money Buy</button>
              <button className="danger" onClick={() => action("/manual-sell")}>Sell Worst</button>
              <button className="purple" onClick={refreshUniverse}>🔄 Weekly Stock Refresh</button>
              <button className="ghost" onClick={() => action("/pause")}>Pause</button>
              <button onClick={() => action("/resume")}>Resume</button>
            </div>
            <p className="notice">{message || "Ready."}</p>
          </Card>

          <Card title="Live Summary">
            <div className="summary">
              <div><span>Positions</span><b>{positions.length}/{data?.maxPositions || 0}</b></div>
              <div><span>Next buy</span><b>{usd(data?.newPositionNotional)}</b></div>
              <div><span>Win rate</span><b>{pct((data?.dbSummary?.winRate || 0) * 100)}</b></div>
              <div><span>Weekly universe</span><b>{data?.autoUniverse?.activeSymbols?.length || 0}/{data?.autoUniverse?.size || 0}</b></div>
              <div><span>Week start</span><b>{data?.autoUniverse?.weekStart || "—"}</b></div>
            </div>
          </Card>

          <Card title="Weekly Auto Universe" wide>
            <p className="muted">Use the button to rebuild the stock list immediately. The backend also supports automatic weekly refresh.</p>
            <div className="scan-grid">
              {(data?.autoUniverse?.rows || []).slice(0, 16).map((r: AnyObj) => (
                <article className="scan" key={r.symbol}>
                  <div><b>{r.symbol}</b><strong>Score {Number(r.score || 0).toFixed(2)}</strong></div>
                  <p>{r.reason || "weekly candidate"}</p>
                </article>
              ))}
              {!(data?.autoUniverse?.rows || []).length && <p className="muted">No weekly universe yet. Press Weekly Stock Refresh.</p>}
            </div>
          </Card>
        </main>
      )}

      {tab === "reports" && (
        <main>
          <section className="stats">
            <Stat label="Deposited" value={usd(totalDeposited)} sub={reports.depositSource ? `Source: ${reports.depositSource}` : ""} />
            <Stat label="Earned Since Deposit" value={usd(earned)} className={tone(earned)} />
            <Stat label="Lost Since Deposit" value={usd(lost)} className="loss" />
            <Stat label="Current Equity" value={usd(reports.currentEquity ?? data?.account?.equity)} />
          </section>

          <Card title="Price / Equity History">
            <div className="chart-controls">
              <button className={chartCurrency === "USD" ? "active" : ""} onClick={() => setChartCurrency("USD")}>USD</button>
              <button className={chartCurrency === "GBP" ? "active" : ""} onClick={() => setChartCurrency("GBP")}>GBP</button>
            </div>
            <div className="chart">
              {reportChart.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={reportChart}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#263450" />
                    <XAxis dataKey="idx" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip formatter={(v: any) => chartCurrency === "GBP" ? gbp(v) : usd(v)} />
                    <Area type="monotone" dataKey="equity" stroke="#38bdf8" fill="#38bdf833" />
                  </AreaChart>
                </ResponsiveContainer>
              ) : <p className="muted">No price/equity history yet. It will build as trades are recorded.</p>}
            </div>
          </Card>

          <Card title="Closed Trade History">
            <div className="table-wrap">
              <table>
                <thead><tr><th>Time</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th><th>%</th></tr></thead>
                <tbody>
                  {closedTrades.slice(-80).reverse().map((t: AnyObj, i: number) => (
                    <tr key={i}>
                      <td>{t.time || "—"}</td>
                      <td>{t.symbol}</td>
                      <td>{usd(t.entryPrice)}</td>
                      <td>{usd(t.exitPrice)}</td>
                      <td>{Number(t.qty || 0).toFixed(4)}</td>
                      <td className={tone(t.pnl)}>{usd(t.pnl)}</td>
                      <td className={tone(t.pnl)}>{pct(t.pnlPct)}</td>
                    </tr>
                  ))}
                  {!closedTrades.length && <tr><td colSpan={7}>No matched closed trades yet.</td></tr>}
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
                <div>
                  <h3>{p.symbol}</h3>
                  <p>Qty {Number(p.qty || 0).toFixed(4)} · Entry {usd(p.entry)} · Price {usd(p.price)}</p>
                  <p>Value <b>{usd(p.marketValue)}</b> / {gbp(p.marketValueGbp ?? p.marketValue * rate)}</p>
                </div>
                <div className="position-side">
                  <b className={tone(p.pnl)}>PnL {usd(p.pnl)} / {gbp(p.pnlGbp ?? p.pnl * rate)} / {pct(p.pnlPct)}</b>
                  <span>{p.trailingActive ? `Trailing floor ${usd(p.trailFloor)}` : `Trail starts ${usd(p.trailStartPrice)}`}</span>
                  <button className="danger" onClick={() => action(`/sell/${p.symbol}`)}>Sell {p.symbol}</button>
                </div>
              </article>
            ))}
            {!positions.length && <p className="muted">No open positions.</p>}
          </div>
        </Card>
      )}

      {tab === "scanner" && (
        <main>
          <Card title="Scanner Price History">
            {scans.length > 0 && (
              <select value={selectedSymbol} onChange={(e) => setSelectedSymbol(e.target.value)}>
                {scans.map((s: AnyObj) => <option key={s.symbol}>{s.symbol}</option>)}
              </select>
            )}
            <div className="chart">
              {scannerChart.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={scannerChart}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#263450" />
                    <XAxis dataKey="t" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip />
                    <Line type="monotone" dataKey="value" stroke="#38bdf8" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              ) : <p className="muted">No scanner price history yet.</p>}
            </div>
          </Card>
          <Card title="Scan Cards">
            <div className="scan-grid">
              {scans.map((s: AnyObj) => (
                <article className="scan" key={s.symbol}>
                  <div><b>{s.symbol}</b><strong>{usd(s.price)}</strong></div>
                  <p>Confidence {Number(s.confidence || 0).toFixed(2)} · Quality {Number(s.qualityScore || 0).toFixed(4)}</p>
                  <span className={s.readyToBuy ? "ready" : ""}>{s.readyToBuy ? "Ready" : (s.aPlusReason || s.sniperReason || "Watching")}</span>
                </article>
              ))}
            </div>
          </Card>
        </main>
      )}

      {tab === "activity" && (
        <main className="grid two">
          <Card title="Recent Trades">
            <div className="log-list">
              {trades.slice(-50).reverse().map((t: AnyObj, i: number) => (
                <div key={i}>{t.time || "—"} · <b>{t.side} {t.symbol}</b> · {t.reason || ""}</div>
              ))}
              {!trades.length && <p className="muted">No trades yet.</p>}
            </div>
          </Card>
          <Card title="Logs">
            <div className="log-list">{logs.map((l: string, i: number) => <div key={i}>{l}</div>)}</div>
          </Card>
        </main>
      )}

      {tab === "admin" && (
        <Card title="Admin">
          <label className="field"><span>Dashboard password</span><input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></label>
          <div className="actions">
            <button onClick={saveApiKey}>Save</button>
            <button className="ghost" onClick={() => { localStorage.removeItem("dashboard_api_key"); setApiKey(""); }}>Clear</button>
          </div>
          <pre>{JSON.stringify({ api: API_URL, botEnabled: data?.botEnabled, market: data?.market, autoUniverse: data?.autoUniverse }, null, 2)}</pre>
        </Card>
      )}
    </div>
  );
}
