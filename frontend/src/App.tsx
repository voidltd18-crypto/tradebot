import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const API_URL = import.meta.env.VITE_API_BASE || "https://tradebot-0myo.onrender.com";
const BOT_VERSION = "ui-refresh-profit-banking-fix-2026-05-16";

type AnyObj = Record<string, any>;
type Tab = "overview" | "reports" | "positions" | "scanner" | "search" | "activity" | "admin";

const usd = (n: any) => `$${Number(n || 0).toFixed(2)}`;
const gbp = (n: any) => `£${Number(n || 0).toFixed(2)}`;
const pct = (n: any) => `${Number(n || 0).toFixed(2)}%`;
const tone = (n: any) => (Number(n || 0) >= 0 ? "gain" : "loss");

function Card({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <section className="card">
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
      {sub && <small>{sub}</small>}
    </div>
  );
}

async function readJson(res: Response) {
  const text = await res.text();
  try {
    return text ? JSON.parse(text) : {};
  } catch {
    return { message: text };
  }
}

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [data, setData] = useState<AnyObj>({});
  const [reports, setReports] = useState<AnyObj>({});
  const [banking, setBanking] = useState<AnyObj>({});
  const [weeklyUniverse, setWeeklyUniverse] = useState<AnyObj>({});
  const [status, setStatus] = useState("Connecting...");
  const [message, setMessage] = useState("Ready.");
  const [busyAction, setBusyAction] = useState("");
  const [lastRefresh, setLastRefresh] = useState("");
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("dashboard_api_key") || "");
  const [authToken, setAuthToken] = useState(() => localStorage.getItem("tradebot_auth_token") || "");
  const [secureUsername, setSecureUsername] = useState("");
  const [securePassword, setSecurePassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [stockQuery, setStockQuery] = useState("");
  const [stockResults, setStockResults] = useState<AnyObj[]>([]);
  const [stockSearchLoading, setStockSearchLoading] = useState(false);
  const fetchSeq = useRef(0);

  const token = authToken || apiKey.trim();
  const secureHeaders = token ? { "x-api-key": token } : {};
  const rate = Number(data?.fx?.usdToGbp || reports?.fx?.usdToGbp || 0.7403);
  const scans = Array.isArray(data?.scans) ? data.scans : [];
  const positions = Array.isArray(data?.positions) ? data.positions : [];
  const trades = Array.isArray(data?.trades) ? data.trades : [];
  const logs = Array.isArray(data?.logs) ? data.logs : [];
  const closedTrades = Array.isArray(reports?.closedTrades)
    ? reports.closedTrades
    : Array.isArray(data?.closedTrades)
      ? data.closedTrades
      : [];

  const autoUniverse = useMemo(() => {
    return weeklyUniverse?.autoUniverse || weeklyUniverse || data?.autoUniverse || {};
  }, [weeklyUniverse, data]);

  const bankingPayload = banking?.ok || banking?.enabled !== undefined ? banking : data?.banking || {};
  const bankingEnabled = Boolean(bankingPayload?.enabled);
  const bankingCap = Number(bankingPayload?.maxTradingCapital || 0);
  const bankingEquity = Number(bankingPayload?.accountEquity || data?.account?.equity || 0);
  const bankingEffective = Number(bankingPayload?.effectiveTradingEquity || 0);
  const bankingBuffer = Number(bankingPayload?.bankedProfitCashBuffer || Math.max(0, bankingEquity - bankingEffective));

  const mergeStatus = useCallback((json: AnyObj) => {
    if (!json || typeof json !== "object") return;
    setData(prev => ({ ...prev, ...json }));
    const nextScans = Array.isArray(json?.scans) ? json.scans : [];
    if (!selectedSymbol && nextScans.length) setSelectedSymbol(nextScans[0].symbol);
  }, [selectedSymbol]);

  const fetchData = useCallback(async (quiet = false) => {
    if (!token) return;
    const seq = ++fetchSeq.current;
    try {
      const [statusRes, reportRes, bankingRes, universeRes] = await Promise.allSettled([
        fetch(`${API_URL}/status`, { cache: "no-store" }).then(readJson),
        fetch(`${API_URL}/reports`, { cache: "no-store" }).then(readJson),
        fetch(`${API_URL}/banking-status`, { cache: "no-store" }).then(readJson),
        fetch(`${API_URL}/weekly-universe`, { cache: "no-store" }).then(readJson),
      ]);
      if (seq !== fetchSeq.current) return;
      if (statusRes.status === "fulfilled") mergeStatus(statusRes.value || {});
      if (reportRes.status === "fulfilled") setReports(reportRes.value || {});
      if (bankingRes.status === "fulfilled") setBanking(bankingRes.value || {});
      if (universeRes.status === "fulfilled") setWeeklyUniverse(universeRes.value || {});
      setStatus("Connected");
      setLastRefresh(new Date().toLocaleTimeString());
      if (!quiet) setMessage("Dashboard refreshed.");
    } catch (e: any) {
      console.error(e);
      setStatus("Connection failed");
      if (!quiet) setMessage(`Refresh failed: ${e?.message || "unknown error"}`);
    }
  }, [mergeStatus, token]);

  useEffect(() => {
    if (!token) return;
    fetchData(true);
    const fastPoll = setInterval(() => fetchData(true), 5000);
    return () => clearInterval(fastPoll);
  }, [fetchData, token]);

  async function secureLogin() {
    try {
      setAuthError("");
      const res = await fetch(`${API_URL}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: secureUsername.trim(), password: securePassword }),
      });
      const json = await readJson(res);
      if (!res.ok || !json?.token) throw new Error(json?.detail || "Login failed");
      localStorage.setItem("tradebot_auth_token", json.token);
      localStorage.setItem("dashboard_api_key", json.token);
      setAuthToken(json.token);
      setApiKey(json.token);
      setSecurePassword("");
      setMessage("Logged in.");
    } catch (e: any) {
      setAuthError(e?.message || "Login failed");
    }
  }

  function secureLogout() {
    localStorage.removeItem("tradebot_auth_token");
    localStorage.removeItem("dashboard_api_key");
    setAuthToken("");
    setApiKey("");
    setMessage("Logged out.");
  }

  async function action(endpoint: string, optimistic?: (prev: AnyObj) => AnyObj) {
    if (!token) {
      setMessage("Please login first.");
      return;
    }
    setBusyAction(endpoint);
    setMessage(`Sent ${endpoint}. Updating dashboard...`);
    if (optimistic) setData(optimistic);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    const pollWhileWaiting = setInterval(() => fetchData(true), 1500);

    try {
      const res = await fetch(`${API_URL}${endpoint}`, {
        method: "POST",
        headers: secureHeaders,
        signal: controller.signal,
      });
      const json = await readJson(res);
      if (json?.autoUniverse) setWeeklyUniverse(json);
      if (json?.botEnabled !== undefined || json?.market || json?.positions || json?.scans) mergeStatus(json);
      setMessage(json?.message || json?.detail || JSON.stringify(json) || `Done: ${endpoint}`);
    } catch (e: any) {
      setMessage(e?.name === "AbortError" ? `${endpoint} is still running on Render. Dashboard will keep polling.` : `Action failed: ${endpoint}`);
    } finally {
      clearTimeout(timeout);
      clearInterval(pollWhileWaiting);
      setBusyAction("");
      fetchData(true);
      setTimeout(() => fetchData(true), 1000);
      setTimeout(() => fetchData(true), 3000);
      setTimeout(() => fetchData(true), 7000);
    }
  }

  async function searchStocks(queryOverride?: string) {
    const query = (queryOverride ?? stockQuery).trim();
    if (!query) {
      setStockResults([]);
      return;
    }
    setStockSearchLoading(true);
    try {
      const res = await fetch(`${API_URL}/search-stocks?q=${encodeURIComponent(query)}`, { cache: "no-store" });
      const json = await readJson(res);
      setStockResults(Array.isArray(json.results) ? json.results : []);
    } catch {
      setMessage("Stock search failed.");
    } finally {
      setStockSearchLoading(false);
    }
  }

  const equityHistory = Array.isArray(reports?.equityHistory)
    ? reports.equityHistory
    : Array.isArray(data?.tradeTimeline)
      ? data.tradeTimeline
      : Array.isArray(data?.equityCurve)
        ? data.equityCurve
        : [];

  const chartData = equityHistory.slice(-100).map((e: AnyObj, i: number) => ({
    label: String(e.time || e.t || e.timestamp || i).slice(0, 16),
    equity: Number(e.equityGbp ?? e.valueGbp ?? Number(e.equity || e.value || 0) * rate),
  }));

  const selectedScan = scans.find((s: AnyObj) => s.symbol === selectedSymbol) || scans[0];
  const scannerChart = Array.isArray(selectedScan?.priceCurve) ? selectedScan.priceCurve : [];

  if (!authToken) {
    return (
      <main className="login-page">
        <section className="login-card">
          <p className="eyebrow">Protected Dashboard</p>
          <h1>TradeBot Secure Login</h1>
          <input value={secureUsername} onChange={e => setSecureUsername(e.target.value)} placeholder="Username" autoComplete="username" />
          <input value={securePassword} onChange={e => setSecurePassword(e.target.value)} placeholder="Password" type="password" autoComplete="current-password" onKeyDown={e => e.key === "Enter" && secureLogin()} />
          <button onClick={secureLogin}>Login</button>
          {authError && <p className="error">{authError}</p>}
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">{BOT_VERSION}</p>
          <h1>TradeBot</h1>
          <p>{status} · last refresh {lastRefresh || "—"}</p>
        </div>
        <div className="status-pills">
          <span>Market {data?.market?.label || "UNKNOWN"}</span>
          <span>Bot {data?.botEnabled ? "ON" : "OFF"}</span>
          <span>{data?.paperMode ? "PAPER" : "LIVE"}</span>
        </div>
      </header>

      <nav className="tabs">
        {(["overview", "reports", "positions", "scanner", "search", "activity", "admin"] as Tab[]).map(t => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t.toUpperCase()}</button>
        ))}
      </nav>

      {tab === "overview" && (
        <>
          <Card>
            <div className="actions">
              <button onClick={() => fetchData(false)}>Refresh Data</button>
              <button disabled={!!busyAction} onClick={() => action("/manual-buy")}>Money Buy</button>
              <button disabled={!!busyAction} onClick={() => action("/manual-sell")}>Sell Worst</button>
              <button disabled={!!busyAction} onClick={() => action("/refresh-universe")}>↻ Weekly Stock Refresh</button>
              <button disabled={!!busyAction} onClick={() => action("/pause", prev => ({ ...prev, botEnabled: false }))}>Pause</button>
              <button disabled={!!busyAction} onClick={() => action("/resume", prev => ({ ...prev, botEnabled: true, emergencyStop: false }))}>Resume</button>
            </div>
            <p className="message">{busyAction ? `Working on ${busyAction}... ` : ""}{message}</p>
          </Card>

          <section className="grid four">
            <Stat label="Equity" value={gbp(data?.account?.equityGbp ?? Number(data?.account?.equity || 0) * rate)} sub={usd(data?.account?.equity)} />
            <Stat label="Buying Power" value={gbp(data?.account?.buyingPowerGbp ?? Number(data?.account?.buyingPower || 0) * rate)} sub={usd(data?.account?.buyingPower)} />
            <Stat label="Positions" value={`${positions.length}/${data?.maxPositions || 0}`} />
            <Stat label="Win Rate" value={pct((data?.dbSummary?.winRate || 0) * 100)} />
          </section>

          <section className="grid two">
            <Card title="Profit Banking">
              <div className="grid two compact">
                <Stat label="Status" value={bankingEnabled ? "ON" : "OFF"} />
                <Stat label="Trading Cap" value={usd(bankingCap)} sub={gbp(bankingCap * rate)} />
                <Stat label="Account Equity" value={usd(bankingEquity)} sub={gbp(bankingEquity * rate)} />
                <Stat label="Used For Sizing" value={usd(bankingEffective)} sub={gbp(bankingEffective * rate)} />
                <Stat label="Banked Buffer" value={usd(bankingBuffer)} sub={gbp(bankingBuffer * rate)} />
              </div>
              <p className="muted">Profits above MAX_TRADING_CAPITAL stay as cash buffer instead of increasing future trade size.</p>
            </Card>

            <Card title="Weekly / Quality Universe">
              <div className="grid two compact">
                <Stat label="Total" value={autoUniverse?.rows?.length || 0} />
                <Stat label="Active" value={autoUniverse?.activeSymbols?.length || 0} />
              </div>
              <div className="chips">
                {(autoUniverse?.activeSymbols || []).slice(0, 24).map((s: string) => <span key={s}>{s}</span>)}
              </div>
            </Card>
          </section>
        </>
      )}

      {tab === "reports" && (
        <Card title="Reports">
          <button onClick={() => fetchData(false)}>Refresh Reports</button>
          {chartData.length ? (
            <div className="chart">
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" hide />
                  <YAxis tickFormatter={v => gbp(v)} />
                  <Tooltip formatter={(v: any) => gbp(v)} />
                  <Area type="monotone" dataKey="equity" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : <p>No equity history yet.</p>}
          <div className="table-wrap">
            <table><thead><tr><th>Time</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th><th>%</th></tr></thead><tbody>
              {closedTrades.slice(-80).reverse().map((t: AnyObj, i: number) => (
                <tr key={`${t.symbol}-${i}`}><td>{t.time || t.timestamp || "—"}</td><td>{t.symbol}</td><td>{usd(t.entryPrice)}</td><td>{usd(t.exitPrice)}</td><td>{Number(t.qty || 0).toFixed(4)}</td><td className={tone(t.pnl)}>{gbp(Number(t.pnlGbp ?? Number(t.pnl || 0) * rate))} / {usd(t.pnl)}</td><td>{pct(t.pnlPct)}</td></tr>
              ))}
            </tbody></table>
          </div>
        </Card>
      )}

      {tab === "positions" && (
        <section className="grid three">
          {positions.map((p: AnyObj) => (
            <Card key={p.symbol} title={p.symbol}>
              <p>Qty {Number(p.qty || 0).toFixed(4)} · Entry {usd(p.entry)} · Price {usd(p.price)}</p>
              <p>Value {gbp(p.marketValueGbp ?? Number(p.marketValue || 0) * rate)} / {usd(p.marketValue)}</p>
              <p className={tone(p.pnl)}>PnL {gbp(p.pnlGbp ?? Number(p.pnl || 0) * rate)} / {usd(p.pnl)} / {pct(p.pnlPct)}</p>
              <button disabled={!!busyAction} onClick={() => action(`/sell/${p.symbol}`)}>Sell {p.symbol}</button>
            </Card>
          ))}
          {!positions.length && <Card><p>No open positions.</p></Card>}
        </section>
      )}

      {tab === "scanner" && (
        <Card title="Scanner">
          {scans.length > 0 && <select value={selectedSymbol} onChange={e => setSelectedSymbol(e.target.value)}>{scans.map((s: AnyObj) => <option key={s.symbol}>{s.symbol}</option>)}</select>}
          <pre>{JSON.stringify(selectedScan || {}, null, 2)}</pre>
          {scannerChart.length ? <div className="chart"><ResponsiveContainer width="100%" height={220}><AreaChart data={scannerChart.map((v: any, i: number) => ({ i, price: Number(v) }))}><XAxis dataKey="i" hide /><YAxis domain={["auto", "auto"]} /><Tooltip /><Area dataKey="price" /></AreaChart></ResponsiveContainer></div> : <p>No scanner price history yet.</p>}
        </Card>
      )}

      {tab === "search" && (
        <Card title="Stock Search">
          <div className="search-row"><input value={stockQuery} onChange={e => { setStockQuery(e.target.value); if (e.target.value.trim().length >= 2) searchStocks(e.target.value); if (!e.target.value.trim()) setStockResults([]); }} onKeyDown={e => e.key === "Enter" && searchStocks()} placeholder="Search ticker or company, e.g. AMD" /><button onClick={() => searchStocks()}>{stockSearchLoading ? "Searching..." : "Search"}</button></div>
          <section className="grid two">
            {stockResults.map(s => <Card key={s.symbol} title={s.name || s.symbol}><p>{s.symbol} · {usd(s.price)} · {pct(s.changePct)}</p><p>{gbp(Number(s.price || 0) * rate)}</p><button disabled={!!busyAction} onClick={() => action(`/custom-buy/${s.symbol}`)}>Buy</button><button disabled={!!busyAction} onClick={() => action(`/add-to-universe/${s.symbol}`)}>Add to Universe</button></Card>)}
          </section>
        </Card>
      )}

      {tab === "activity" && (
        <section className="grid two">
          <Card title="Trades">{trades.slice(-50).reverse().map((t: AnyObj, i: number) => <p key={i}>{t.time || "—"} · {t.side} {t.symbol} · {t.reason || ""}</p>)}{!trades.length && <p>No trades yet.</p>}</Card>
          <Card title="Logs">{logs.map((l: string, i: number) => <p key={i} className="log-line">{l}</p>)}</Card>
        </section>
      )}

      {tab === "admin" && (
        <Card title="Admin">
          <label>Dashboard password/API key</label>
          <input value={apiKey} onChange={e => setApiKey(e.target.value)} />
          <button onClick={() => { localStorage.setItem("dashboard_api_key", apiKey); setMessage("Dashboard key saved."); }}>Save</button>
          <button onClick={secureLogout}>Logout</button>
          <pre>{JSON.stringify({ api: API_URL, botEnabled: data?.botEnabled, market: data?.market, banking: bankingPayload, autoUniverse }, null, 2)}</pre>
        </Card>
      )}
    </main>
  );
}
