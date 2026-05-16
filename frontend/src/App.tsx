
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const API_URL = import.meta.env.VITE_API_BASE || "https://tradebot-0myo.onrender.com";
const BOT_VERSION = "v1.1-strict-profit-mode";
type AnyObj = Record<string, any>;
type Tab = "overview" | "reports" | "positions" | "scanner" | "search" | "activity" | "admin";

const usd = (n:any) => `$${Number(n || 0).toFixed(2)}`;
const gbp = (n:any) => `£${Number(n || 0).toFixed(2)}`;
const pct = (n:any) => `${Number(n || 0).toFixed(2)}%`;
const tone = (n:any) => Number(n || 0) >= 0 ? "gain" : "loss";

function Card({ title, children, wide=false }: {title?: string; children: React.ReactNode; wide?: boolean}) {
  return <section className={`card ${wide ? "wide" : ""}`}>{title && <h2>{title}</h2>}{children}</section>;
}
function Stat({ label, value, sub, className="" }: {label:string; value:React.ReactNode; sub?:React.ReactNode; className?:string}) {
  return <section className="card stat"><span>{label}</span><strong className={className}>{value}</strong>{sub && <small>{sub}</small>}</section>;
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
  
  const [authToken, setAuthToken] = useState<string>(() => localStorage.getItem("tradebot_auth_token") || "");
  const [secureUsername, setSecureUsername] = useState<string>("");
  const [securePassword, setSecurePassword] = useState<string>("");
  const [authError, setAuthError] = useState<string>("");
const [banking, setBanking] = useState<AnyObj>({});
  const [status, setStatus] = useState("Connecting...");
  const [message, setMessage] = useState("Ready.");
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("dashboard_api_key") || "");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [chartCurrency, setChartCurrency] = useState<"GBP"|"USD">("GBP");
  const [stockQuery, setStockQuery] = useState("");
  const [stockResults, setStockResults] = useState<any[]>([]);
  const [stockSearchLoading, setStockSearchLoading] = useState(false);
  const [tradingCapInput, setTradingCapInput] = useState<string>("");
  const [tradingCapSaving, setTradingCapSaving] = useState(false);
  const fetchSeq = useRef(0);
  const fetchInFlight = useRef(false);
  const lastFetchAt = useRef(0);
  const POLL_MS = 10000;

  const rate = Number(data?.fx?.usdToGbp || 0.7403);
  const scans = Array.isArray(data?.scans) ? data.scans : [];
  const positions = Array.isArray(data?.positions) ? data.positions : [];
  const trades = Array.isArray(data?.trades) ? data.trades : [];
  const logs = Array.isArray(data?.logs) ? data.logs : [];
  const closedTrades = Array.isArray(reports?.closedTrades) ? reports.closedTrades : [];
  const equityHistory = Array.isArray(reports?.equityHistory) ? reports.equityHistory : (Array.isArray(data?.tradeTimeline) ? data.tradeTimeline : []);
  const bankingEnabled = Boolean(banking?.enabled || data?.banking?.enabled);
  const bankingCap = Number(banking?.maxTradingCapital ?? data?.banking?.maxTradingCapital ?? 0);
  const bankingCapGbp = Number(banking?.maxTradingCapitalGbp ?? data?.banking?.maxTradingCapitalGbp ?? bankingCap * rate);
  const bankingCapCurrency = String(banking?.tradingCapCurrency ?? data?.banking?.tradingCapCurrency ?? "USD");
  const bankingCapSource = String(banking?.tradingCapSource ?? data?.banking?.tradingCapSource ?? "env");
  const bankingEquity = Number(banking?.accountEquity ?? data?.banking?.accountEquity ?? data?.account?.equity ?? 0);
  const bankingEffective = Number(banking?.effectiveTradingEquity ?? data?.banking?.effectiveTradingEquity ?? 0);
  const bankingEffectiveGbp = Number(banking?.effectiveTradingEquityGbp ?? data?.banking?.effectiveTradingEquityGbp ?? bankingEffective * rate);
  const bankingBuffer = Number(banking?.bankedProfitCashBuffer ?? data?.banking?.bankedProfitCashBuffer ?? 0);
  const bankingBufferGbp = Number(banking?.bankedProfitCashBufferGbp ?? data?.banking?.bankedProfitCashBufferGbp ?? bankingBuffer * rate);
  const dynamicScanner = data?.dynamicMarketScanner || data?.autoUniverse?.dynamicScanner || {};
  const dynamicRows = Array.isArray(dynamicScanner?.rows) ? dynamicScanner.rows : [];
  const dynamicPickCount = Number(data?.autoUniverse?.dynamicPickCount || dynamicRows.length || 0);

  useEffect(() => {
    const gbpCap = Number(banking?.maxTradingCapitalGbp ?? data?.banking?.maxTradingCapitalGbp ?? 0);
    if (gbpCap > 0 && !tradingCapInput) setTradingCapInput(String(Math.round(gbpCap)));
  }, [banking?.maxTradingCapitalGbp, data?.banking?.maxTradingCapitalGbp]);

  
  const token = authToken || apiKey.trim();
  const secureHeaders = token ? { "X-Auth-Token": token, "x-api-key": token } : {};

  async function triggerDynamicMarketUniverseRefresh(loginToken: string, reason = "login") {
    if (!loginToken) return;
    try {
      setMessage(reason === "login" ? "Login successful. Refreshing dynamic market universe..." : "Refreshing dynamic market universe...");
      const res = await fetch(`${API_URL}/refresh-universe`, {
        method: "POST",
        headers: { "X-Auth-Token": loginToken, "x-api-key": loginToken },
        cache: "no-store",
      });
      const json = await readJson(res);
      if (!res.ok || json?.ok === false) throw new Error(json?.detail || json?.message || "Dynamic market refresh failed");

      const autoUniverse = json?.autoUniverse || json;
      const dynamicScanner = json?.dynamicMarketScanner || autoUniverse?.dynamicScanner;
      setData(prev => ({
        ...prev,
        autoUniverse: autoUniverse?.activeSymbols || autoUniverse?.rows ? autoUniverse : prev.autoUniverse,
        universe: autoUniverse?.activeSymbols || json?.activeSymbols || prev.universe,
        dynamicMarketScanner: dynamicScanner || prev.dynamicMarketScanner,
        lastAction: json?.message || "Dynamic market universe refreshed",
        lastActionAt: new Date().toISOString(),
      }));
      setMessage(json?.message || "Dynamic market universe refreshed.");
    } catch (e:any) {
      setMessage(e?.message || "Dynamic market refresh failed. Dashboard will still load normally.");
    }
  }

  function softReloadApp() {
    // Prevent the blank-screen state that can happen when auth changes while
    // async dashboard requests are still resolving. This reloads automatically,
    // so the user no longer has to manually refresh the page after login/logout.
    window.location.replace(window.location.pathname + window.location.search);
  }

  async function secureLogin() {
    try {
      setAuthError("");
      setMessage("Logging in...");
      const res = await fetch(`${API_URL}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: secureUsername.trim(), password: securePassword }),
      });
      const json = await readJson(res);
      if (!res.ok || !json?.token) throw new Error(json?.detail || "Login failed");

      localStorage.setItem("tradebot_auth_token", json.token);
      localStorage.setItem("dashboard_api_key", json.token);
      sessionStorage.setItem("tradebot_pending_dynamic_refresh", "1");

      setAuthToken(json.token);
      setApiKey(json.token);
      setSecurePassword("");
      setMessage("Login successful. Loading dashboard...");

      setTimeout(softReloadApp, 80);
    } catch (e: any) {
      setAuthError(e?.message || "Login failed");
      setMessage("Login failed.");
    }
  }

  function secureLogout() {
    localStorage.removeItem("tradebot_auth_token");
    localStorage.removeItem("dashboard_api_key");
    sessionStorage.removeItem("tradebot_pending_dynamic_refresh");
    fetchSeq.current += 1;
    fetchInFlight.current = false;
    setAuthToken("");
    setApiKey("");
    setData({});
    setReports({});
    setBanking({});
    setSelectedSymbol("");
    setStockResults([]);
    setMessage("Logged out.");
    setTimeout(softReloadApp, 50);
  }

const fetchData = useCallback(async (force = false) => {
    if (!authToken) return;

    const now = Date.now();
    if (!force && (fetchInFlight.current || now - lastFetchAt.current < POLL_MS)) return;

    fetchInFlight.current = true;
    lastFetchAt.current = now;
    const seq = ++fetchSeq.current;
    try {
      const [statusRes, reportRes, bankingRes] = await Promise.allSettled([
        fetch(`${API_URL}/status`, { cache: "no-store", headers: secureHeaders }).then(readJson),
        fetch(`${API_URL}/reports`, { cache: "no-store", headers: secureHeaders }).then(readJson),
        fetch(`${API_URL}/banking-status`, { cache: "no-store", headers: secureHeaders }).then(readJson),
      ]);

      if (seq !== fetchSeq.current) return;

      if (statusRes.status === "fulfilled") {
        const json = statusRes.value;
        if (json && typeof json === "object") {
          setData(prev => ({ ...prev, ...json }));
        }
        const nextScans = Array.isArray(json?.scans) ? json.scans : [];
        if (!selectedSymbol && nextScans.length) setSelectedSymbol(nextScans[0].symbol);
      }

      if (reportRes.status === "fulfilled" && reportRes.value) {
        setReports(prev => ({ ...prev, ...reportRes.value }));
      }

      if (bankingRes.status === "fulfilled" && bankingRes.value) {
        setBanking(bankingRes.value || {});
      }

      setStatus("Connected");
    } catch (e) {
      console.error(e);
      setStatus("Connection failed");
    } finally {
      fetchInFlight.current = false;
    }
  }, [authToken, selectedSymbol]);

  useEffect(() => {
    if (!authToken) return;

    fetchData(true);

    if (sessionStorage.getItem("tradebot_pending_dynamic_refresh") === "1") {
      sessionStorage.removeItem("tradebot_pending_dynamic_refresh");
      setTimeout(() => triggerDynamicMarketUniverseRefresh(authToken, "login"), 350);
    }

    const i = setInterval(() => fetchData(false), POLL_MS);
    return () => clearInterval(i);
  }, [authToken, fetchData]);

  if (!authToken) {
    return (
      <div className="app">
        <h1>TradeBot Secure Login</h1>
        <div className="card" style={{ maxWidth: 520, margin: "40px auto" }}>
          <h2>Login</h2>
          <p className="muted">Enter your admin username and password.</p>
          <input
            value={secureUsername}
            onChange={(e) => setSecureUsername(e.target.value)}
            placeholder="Username"
            style={{ width: "100%", padding: "14px", borderRadius: "12px", marginBottom: "12px" }}
          />
          <input
            type="password"
            value={securePassword}
            onChange={(e) => setSecurePassword(e.target.value)}
            placeholder="Password"
            style={{ width: "100%", padding: "14px", borderRadius: "12px", marginBottom: "12px" }}
            onKeyDown={(e) => { if (e.key === "Enter") secureLogin(); }}
          />
          <button onClick={secureLogin}>Login</button>
          {authError && <p className="loss">{authError}</p>}
        </div>
      </div>
    );
  }

  function saveApiKey() {
    localStorage.setItem("dashboard_api_key", apiKey);
    setMessage("Dashboard password saved.");
  }

  async function refreshWeeklyUniverseView() {
    try {
      const res = await fetch(`${API_URL}/weekly-universe`, {
        cache: "no-store",
        headers: secureHeaders,
      });
      const json = await readJson(res);
      const autoUniverse = json?.autoUniverse || json;
      if (autoUniverse?.activeSymbols || autoUniverse?.rows) {
        setData(prev => ({
          ...prev,
          autoUniverse,
          universe: autoUniverse.activeSymbols || prev.universe,
          lastAction: json?.message || "Dynamic universe refreshed",
          lastActionAt: new Date().toISOString(),
        }));
      }
    } catch (e) {
      console.error("Weekly universe follow-up failed", e);
    }
  }

  async function action(endpoint:string) {
    if (!token) {
      setMessage("Please login first.");
      return;
    }

    const optimistic = endpoint === "/pause"
      ? (prev: AnyObj) => ({ ...prev, botEnabled: false })
      : endpoint === "/resume"
        ? (prev: AnyObj) => ({ ...prev, botEnabled: true })
        : null;

    if (optimistic) setData(optimistic);

    const isWeeklyRefresh = endpoint === "/refresh-universe";
    setMessage(isWeeklyRefresh ? "Dynamic market refresh sent. Updating universe..." : `Sent ${endpoint}. Updating dashboard...`);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), isWeeklyRefresh ? 12000 : 30000);

    try {
      const res = await fetch(`${API_URL}${endpoint}`, {
        method:"POST",
        headers: secureHeaders,
        cache: "no-store",
        signal: controller.signal,
      });
      const json = await readJson(res);
      if (!res.ok) throw new Error(json?.detail || json?.message || `Action failed (${res.status})`);

      if (isWeeklyRefresh) {
        const autoUniverse = json?.autoUniverse;
        if (autoUniverse?.activeSymbols || autoUniverse?.rows) {
          setData(prev => ({
            ...prev,
            autoUniverse,
            universe: autoUniverse.activeSymbols || prev.universe,
            lastAction: json?.message || "Dynamic universe refreshed",
            lastActionAt: new Date().toISOString(),
          }));
        }
        setMessage(json?.message || "Dynamic universe refreshed.");
        await refreshWeeklyUniverseView();
      } else {
        setMessage(json.message || json.detail || JSON.stringify(json));
      }
    } catch (e:any) {
      if (isWeeklyRefresh && e?.name === "AbortError") {
        setMessage("Dynamic refresh was sent. Checking saved universe now...");
        await refreshWeeklyUniverseView();
      } else {
        setMessage(e?.name === "AbortError" ? "Action is still processing on Render. Dashboard will refresh normally." : (e?.message || "Action failed."));
      }
    } finally {
      clearTimeout(timeout);
      await fetchData(true);
      if (isWeeklyRefresh) setTimeout(() => refreshWeeklyUniverseView(), 2500);
    }
  }

  async function searchStocks(queryOverride?: string) {
    const query = (queryOverride ?? stockQuery).trim();
    if (!query) { setStockResults([]); return; }
    setStockSearchLoading(true);
    try {
      const res = await fetch(`${API_URL}/search-stocks?q=${encodeURIComponent(query)}`, { cache: "no-store", headers: secureHeaders });
      const json = await readJson(res);
      setStockResults(Array.isArray(json.results) ? json.results : []);
    } catch {
      setMessage("Stock search failed.");
    } finally {
      setStockSearchLoading(false);
    }
  }

  async function saveTradingCap(capOverride?: number) {
    if (!token) {
      setMessage("Please login first.");
      return;
    }

    const capGbp = Number(capOverride ?? tradingCapInput);
    if (!Number.isFinite(capGbp) || capGbp <= 0) {
      setMessage("Enter a valid trading cap in GBP.");
      return;
    }

    setTradingCapSaving(true);
    setMessage(`Saving trading cap at £${capGbp.toFixed(2)}...`);

    try {
      const res = await fetch(`${API_URL}/trading-cap`, {
        method: "POST",
        headers: { ...secureHeaders, "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ capGbp, currency: "GBP" }),
      });
      const json = await readJson(res);
      if (!res.ok || json?.ok === false) throw new Error(json?.detail || json?.message || "Could not save trading cap");
      setBanking(json || {});
      setData(prev => ({ ...prev, banking: json, newPositionNotional: json?.newPositionNotional ?? prev.newPositionNotional }));
      setTradingCapInput(String(Math.round(Number(json?.maxTradingCapitalGbp || capGbp))));
      setMessage(json?.message || "Trading cap saved.");
      await fetchData(true);
    } catch (e:any) {
      setMessage(e?.message || "Could not save trading cap.");
    } finally {
      setTradingCapSaving(false);
    }
  }

  async function refreshDynamicScanner() {
    if (!token) {
      setMessage("Please login first.");
      return;
    }
    setMessage("Refreshing dynamic market universe...");
    try {
      const res = await fetch(`${API_URL}/refresh-universe`, {
        method: "POST",
        headers: secureHeaders,
        cache: "no-store",
      });
      const json = await readJson(res);
      if (!res.ok || json?.ok === false) throw new Error(json?.detail || json?.message || "Dynamic market refresh failed");
      const autoUniverse = json?.autoUniverse || json;
      const dynamicScanner = json?.dynamicMarketScanner || autoUniverse?.dynamicScanner;
      setData(prev => ({
        ...prev,
        autoUniverse: autoUniverse?.activeSymbols || autoUniverse?.rows ? autoUniverse : prev.autoUniverse,
        universe: autoUniverse?.activeSymbols || json?.activeSymbols || prev.universe,
        dynamicMarketScanner: dynamicScanner || prev.dynamicMarketScanner,
        lastAction: json?.message || "Dynamic market universe refreshed",
        lastActionAt: new Date().toISOString(),
      }));
      setMessage(json?.message || "Dynamic market universe refreshed.");
      await refreshWeeklyUniverseView();
      await fetchData(true);
    } catch (e:any) {
      setMessage(e?.message || "Dynamic market refresh failed.");
    }
  }

  async function resetBaseline() {
    if (!confirm("Reset PnL baseline to current equity? This only resets reporting.")) return;
    await action("/reset-baseline");
  }

  function chartLabel(raw:any, i:number) {
    const d = new Date(raw || "");
    if (Number.isNaN(d.getTime())) return raw ? String(raw).slice(0,16) : `#${i+1}`;
    return d.toLocaleString(undefined, { month:"short", day:"2-digit", hour:"2-digit", minute:"2-digit" });
  }
  function chartDay(raw:any, i:number) {
    const d = new Date(raw || "");
    if (Number.isNaN(d.getTime())) return raw ? String(raw).slice(0,10) : `Session ${i+1}`;
    return d.toLocaleDateString(undefined, { month:"short", day:"2-digit" });
  }

  const reportChart = useMemo(() => equityHistory.map((e:AnyObj, i:number) => {
    const raw = e.time || e.timestamp || e.t || e.label || "";
    return {
      idx:i,
      label:chartLabel(raw,i),
      day:chartDay(raw,i),
      equity: chartCurrency === "GBP" ? Number(e.equityGbp ?? e.valueGbp ?? Number(e.equity || e.value || 0) * rate) : Number(e.equity ?? e.value ?? 0),
      pnl: chartCurrency === "GBP" ? Number(e.pnlGbp ?? Number(e.pnl || 0) * rate) : Number(e.pnl || 0)
    };
  }), [equityHistory, chartCurrency, rate]);

  const dailyPnlChart = useMemo(() => {
    const grouped: Record<string, number> = {};
    for (const p of reportChart) grouped[p.day] = (grouped[p.day] || 0) + Number(p.pnl || 0);
    return Object.entries(grouped).map(([day,pnl]) => ({ day, pnl }));
  }, [reportChart]);

  const selectedScan = scans.find((s:AnyObj) => s.symbol === selectedSymbol) || scans[0];
  const scannerChart = selectedScan?.priceCurve || [];
  const totalDeposited = Number(reports.totalDeposited ?? 0);
  const earned = Number(reports.earnedSinceDeposit ?? 0);
  const totalGainLoss = Number(reports.totalGainLoss ?? 0);
  const lost = Number(reports.lostSinceDeposit ?? 0);
  const tabs: Tab[] = ["overview","reports","positions","scanner","search","activity","admin"];

  return <div className="app">
    <header className="topbar">
      <div><p className="eyebrow">Rebuilt Sniper Profit Bot</p><h1>TradeBot</h1></div>
      <div className="pills">
        <span className="pill ok">{status}</span>
        <span className={`pill ${data?.market?.isOpen ? "ok" : "warn"}`}>Market {data?.market?.label || "UNKNOWN"}</span>
        <span className={`pill ${data?.botEnabled ? "ok" : "bad"}`}>Bot {data?.botEnabled ? "ON" : "OFF"}</span>
        <span className="pill">{data?.paperMode ? "PAPER" : "LIVE"}</span>
      </div>
    </header>

    <section className="stats">
      <Stat label="Equity" value={gbp(Number(data?.account?.equity || 0) * rate)} sub={usd(data?.account?.equity)} />
      <Stat label="Buying Power" value={gbp(Number(data?.account?.buyingPower || 0) * rate)} sub={usd(data?.account?.buyingPower)} />
      <Stat label="Day PnL" value={gbp(Number(data?.account?.pnlDay || 0) * rate)} sub={usd(data?.account?.pnlDay)} className={tone(data?.account?.pnlDay)} />
      <Stat label="Total Gain/Loss" value={gbp(totalGainLoss * rate)} sub={`Deposited ${gbp(totalDeposited * rate)} / ${usd(totalDeposited)}`} className={tone(totalGainLoss)} />
    </section>

    <nav className="tabs">{tabs.map(t => <button key={t} className={tab===t ? "active":""} onClick={() => setTab(t)}>{t.toUpperCase()}</button>)}</nav>

    {tab==="overview" && <main className="grid two">
      <Card title="Controls"><div className="actions">
        <button onClick={() => fetchData(true)}>Refresh Data</button>
        <button onClick={secureLogout}>Logout</button>
        <button onClick={() => action("/manual-buy")}>Money Buy</button>
        <button className="danger" onClick={() => action("/manual-sell")}>Sell Worst</button>
        <button className="purple" onClick={() => action("/refresh-universe")}>↻ Dynamic Market Refresh</button>
        <button className="ghost" onClick={() => action("/pause")}>Pause</button>
        <button onClick={() => action("/resume")}>Resume</button>
      </div><p className="notice">{message}</p></Card>
      <Card title="Live Summary"><div className="summary">
        <div><span>Positions</span><b>{positions.length}/{data?.maxPositions || 0}</b></div>
        <div><span>Next buy</span><b>{usd(data?.newPositionNotional)}</b></div>
        <div><span>Win rate</span><b>{pct((data?.dbSummary?.winRate || 0) * 100)}</b></div>
        <div><span>Dynamic universe</span><b>{data?.autoUniverse?.activeSymbols?.length || 0}/{data?.autoUniverse?.size || 0}</b></div>
        <div><span>Manual picks</span><b>{data?.autoUniverse?.manualPickCount || data?.manualUniversePicks?.length || 0}</b></div>
      </div></Card>

      <Card title="Dynamic Market Scanner" wide>
        <div className="summary">
          <div><span>Status</span><b className={dynamicScanner?.enabled === false ? "loss" : "gain"}>{dynamicScanner?.enabled === false ? "OFF" : "ON"}</b></div>
          <div><span>Discovered picks</span><b>{dynamicPickCount}</b></div>
          <div><span>Source</span><b>{dynamicScanner?.source || "market movers"}</b></div>
          <div><span>Refresh</span><b>{dynamicScanner?.updatedAt ? new Date(dynamicScanner.updatedAt).toLocaleTimeString() : "Waiting"}</b></div>
        </div>
        <div className="actions"><button className="purple" onClick={refreshDynamicScanner}>Refresh Dynamic Market</button></div>
        <p className="muted">This searches market movers/active stocks first, applies price/volume/spread filters, then merges the best candidates with your manual pinned stocks and core safety list.</p>
        {dynamicScanner?.error && <p className="notice danger-text">Scanner warning: {dynamicScanner.error}</p>}
        <div className="scan-grid">{dynamicRows.slice(0,12).map((r:AnyObj) => <article className="scan" key={r.symbol}><div><b>{r.symbol}</b><strong>Score {Number(r.score || 0).toFixed(2)}</strong></div><p>{r.reason || "dynamic candidate"}</p><small>{r.price ? `Price ${usd(r.price)} · ` : ""}{r.changePct !== undefined ? `Change ${pct(r.changePct)} · ` : ""}{r.volume ? `Volume ${Number(r.volume).toLocaleString()}` : ""}</small></article>)}</div>
      </Card>

      <Card title="Profit Banking / Trading Cap">
        <div className="summary">
          <div><span>Status</span><b className={bankingEnabled ? "gain" : ""}>{bankingEnabled ? "ON" : "OFF"}</b></div>
          <div><span>Trading cap</span><b>{gbp(bankingCapGbp)} · {usd(bankingCap)}</b></div>
          <div><span>Used for sizing</span><b>{gbp(bankingEffectiveGbp)} · {usd(bankingEffective)}</b></div>
          <div><span>Banked buffer</span><b className="gain">{gbp(bankingBufferGbp)} · {usd(bankingBuffer)}</b></div>
        </div>
        <label className="field"><span>Change trading cap (£)</span><input value={tradingCapInput} onChange={e=>setTradingCapInput(e.target.value)} placeholder="200" inputMode="decimal" /></label>
        <div className="actions">
          <button className="ghost" onClick={()=>{setTradingCapInput("100"); saveTradingCap(100)}} disabled={tradingCapSaving}>£100</button>
          <button className="ghost" onClick={()=>{setTradingCapInput("200"); saveTradingCap(200)}} disabled={tradingCapSaving}>£200</button>
          <button className="ghost" onClick={()=>{setTradingCapInput("260"); saveTradingCap(260)}} disabled={tradingCapSaving}>£260</button>
          <button onClick={()=>saveTradingCap()} disabled={tradingCapSaving}>{tradingCapSaving ? "Saving..." : "Save Cap"}</button>
        </div>
        <p className="muted">Saved cap source: {bankingCapSource}. Profits above the cap stay as cash buffer instead of increasing future trade size.</p>
      </Card>
      <Card title="Dynamic Auto Universe" wide>
        <p className="muted">The bot discovers strong market movers, filters out weak/junk tickers, and keeps manual picks pinned.</p>
        <div className="universe-counts">
          <div><span>Total in universe</span><b>{data?.autoUniverse?.rows?.length || 0}</b></div>
          <div><span>Active symbols</span><b>{data?.autoUniverse?.activeSymbols?.length || 0}</b></div>
          <div><span>Manual picks</span><b>{data?.autoUniverse?.manualPickCount || data?.manualUniversePicks?.length || 0}</b></div>
          <div><span>Dynamic picks</span><b>{data?.autoUniverse?.dynamicPickCount || dynamicPickCount}</b></div>
        </div>
        <div className="scan-grid">{(data?.autoUniverse?.rows || []).slice(0,40).map((r:AnyObj) => <article className="scan" key={r.symbol}><div><b>{r.symbol}</b><strong>{r.manualPick ? "Manual ⭐" : r.dynamicPick ? "Dynamic ⚡" : `Score ${Number(r.score || 0).toFixed(2)}`}</strong></div><p>{r.reason || "dynamic candidate"}</p></article>)}</div>
      </Card>
    </main>}

    {tab==="reports" && <main>
      <div className="actions report-actions"><button onClick={() => fetchData(true)}>Refresh Reports</button><button className="danger" onClick={resetBaseline}>Reset PnL Baseline</button></div>
      <section className="stats">
        <Stat label="Deposited" value={gbp(totalDeposited * rate)} sub={`${usd(totalDeposited)} · ${reports.depositSource ? `Source: ${reports.depositSource}` : ""}`} />
        <Stat label="Earned Since Deposit" value={gbp(earned * rate)} sub={usd(earned)} className={tone(earned)} />
        <Stat label="Lost Since Deposit" value={gbp(lost * rate)} sub={usd(lost)} className="loss" />
        <Stat label="Current Equity" value={gbp(Number((reports.currentEquity ?? data?.account?.equity) || 0) * rate)} sub={usd(reports.currentEquity ?? data?.account?.equity)} />
      </section>
      <Card title="Price / Equity History"><div className="chart-controls"><button className={chartCurrency==="GBP" ? "active":""} onClick={() => setChartCurrency("GBP")}>GBP</button><button className={chartCurrency==="USD" ? "active":""} onClick={() => setChartCurrency("USD")}>USD</button></div><div className="chart">{reportChart.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={reportChart}><CartesianGrid strokeDasharray="3 3" stroke="#263450"/><XAxis dataKey="label" stroke="#94a3b8" minTickGap={28}/><YAxis stroke="#94a3b8"/><Tooltip formatter={(v:any) => chartCurrency==="GBP" ? gbp(v) : usd(v)}/><Area type="monotone" dataKey="equity" stroke="#38bdf8" fill="#38bdf833"/></AreaChart></ResponsiveContainer> : <p className="muted">No price/equity history yet.</p>}</div></Card>
      <Card title="Daily PnL"><div className="chart small-chart">{dailyPnlChart.length ? <ResponsiveContainer width="100%" height="100%"><BarChart data={dailyPnlChart}><CartesianGrid strokeDasharray="3 3" stroke="#263450"/><XAxis dataKey="day" stroke="#94a3b8"/><YAxis stroke="#94a3b8"/><Tooltip formatter={(v:any) => chartCurrency==="GBP" ? gbp(v) : usd(v)}/><Bar dataKey="pnl" fill="#38bdf8"/></BarChart></ResponsiveContainer> : <p className="muted">Daily PnL bars will appear as trades are recorded.</p>}</div></Card>
      <Card title="Closed Trade History"><div className="table-wrap"><table><thead><tr><th>Time</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th><th>%</th></tr></thead><tbody>{closedTrades.slice(-80).reverse().map((t:AnyObj,i:number)=><tr key={i}><td>{t.time || "—"}</td><td>{t.symbol}</td><td>{usd(t.entryPrice)}</td><td>{usd(t.exitPrice)}</td><td>{Number(t.qty || 0).toFixed(4)}</td><td className={tone(t.pnl)}>{gbp(Number(t.pnl || 0) * rate)} / {usd(t.pnl)}</td><td className={tone(t.pnl)}>{pct(t.pnlPct)}</td></tr>)}{!closedTrades.length && <tr><td colSpan={7}>No matched closed trades yet.</td></tr>}</tbody></table></div></Card>
    </main>}

    {tab==="positions" && <Card title="All Positions"><div className="position-list">{positions.map((p:AnyObj)=><article className="position" key={p.symbol}><div><h3>{p.symbol}</h3><p>Qty {Number(p.qty || 0).toFixed(4)} · Entry {usd(p.entry)} · Price {usd(p.price)}</p><p>Value <b>{gbp(p.marketValueGbp ?? p.marketValue * rate)}</b> / {usd(p.marketValue)}</p></div><div className="position-side"><b className={tone(p.pnl)}>PnL {gbp(p.pnlGbp ?? p.pnl * rate)} / {usd(p.pnl)} / {pct(p.pnlPct)}</b><span>{p.trailingActive ? `Trailing floor ${usd(p.trailFloor)}` : `Trail starts ${usd(p.trailStartPrice)}`}</span><button className="danger" onClick={() => action(`/sell/${p.symbol}`)}>Sell {p.symbol}</button></div></article>)}{!positions.length && <p className="muted">No open positions.</p>}</div></Card>}

    {tab==="scanner" && <main><Card title="Scanner Price History">{scans.length>0 && <select value={selectedSymbol} onChange={e=>setSelectedSymbol(e.target.value)}>{scans.map((s:AnyObj)=><option key={s.symbol}>{s.symbol}</option>)}</select>}<div className="chart">{scannerChart.length ? <ResponsiveContainer width="100%" height="100%"><LineChart data={scannerChart}><CartesianGrid strokeDasharray="3 3" stroke="#263450"/><XAxis dataKey="t" stroke="#94a3b8"/><YAxis stroke="#94a3b8"/><Tooltip/><Line type="monotone" dataKey="value" stroke="#38bdf8" dot={false}/></LineChart></ResponsiveContainer> : <p className="muted">No scanner price history yet.</p>}</div></Card></main>}

    {tab==="search" && <main><Card title="Stock Search / Preview"><div className="search-row"><input value={stockQuery} onChange={e=>{setStockQuery(e.target.value); if(e.target.value.trim().length>=2) searchStocks(e.target.value); if(!e.target.value.trim()) setStockResults([])}} onKeyDown={e=>{if(e.key==="Enter") searchStocks()}} placeholder="Search ticker or company, e.g. AMD"/><button onClick={()=>searchStocks()}>{stockSearchLoading ? "Searching..." : "Search"}</button></div><div className="search-results">{stockResults.map((s:AnyObj)=><article className="search-card" key={s.symbol}><div className="search-main"><div className="logo-circle">{s.symbol.slice(0,2)}</div><div><h3>{s.name}</h3><p>{s.symbol} · NASDAQ/NYSE</p></div></div><div className="search-price"><strong>{usd(s.price)}</strong><span className={tone(s.changePct)}>{Number(s.changePct || 0)>=0 ? "↗":"↘"} {pct(s.changePct)}</span><small>{gbp(s.priceGbp)}</small></div><div className="mini-chart">{Array.isArray(s.history) && s.history.length>1 ? <ResponsiveContainer width="100%" height="100%"><LineChart data={s.history.map((p:AnyObj,i:number)=>({...p,i}))}><Line type="monotone" dataKey="value" stroke="#38bdf8" dot={false} strokeWidth={2}/><Tooltip formatter={(v:any)=>usd(v)}/></LineChart></ResponsiveContainer> : <p className="muted">Preview builds while you search.</p>}</div><div className="search-actions"><button onClick={()=>action(`/custom-buy/${s.symbol}`)}>Buy</button><button className="ghost" onClick={()=>action(`/add-to-universe/${s.symbol}`)}>Add to Universe</button></div></article>)}{!stockResults.length && <p className="muted">Type a symbol to preview price, daily movement and mini chart.</p>}</div></Card></main>}

    {tab==="activity" && <main className="grid two"><Card title="Recent Trades"><div className="log-list">{trades.slice(-50).reverse().map((t:AnyObj,i:number)=><div key={i}>{t.time || "—"} · <b>{t.side} {t.symbol}</b> · {t.reason || ""}</div>)}{!trades.length && <p className="muted">No trades yet.</p>}</div></Card><Card title="Logs"><div className="log-list">{logs.map((l:string,i:number)=><div key={i}>{l}</div>)}</div></Card></main>}

    {tab==="admin" && <Card title="Admin"><label className="field"><span>Dashboard password</span><input type="password" value={apiKey} onChange={e=>setApiKey(e.target.value)}/></label><div className="actions"><button onClick={saveApiKey}>Save</button><button className="ghost" onClick={()=>{localStorage.removeItem("dashboard_api_key"); setApiKey("")}}>Clear</button></div><pre>{JSON.stringify({ api:API_URL, botEnabled:data?.botEnabled, market:data?.market, manualPicks:data?.manualUniversePicks, tradingCapGbp:bankingCapGbp, tradingCapSource:bankingCapSource }, null, 2)}</pre></Card>}
  </div>;
}
