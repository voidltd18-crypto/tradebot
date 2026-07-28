import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const API_URL = import.meta.env.VITE_API_BASE || "https://tradebot-0myo.onrender.com";
const BOT_VERSION = "v2-ai-dashboard";

type AnyObj = Record<string, any>;
type Tab = "overview" | "positions" | "reports" | "explorer" | "admin";

const usd = (n: any) => `$${Number(n || 0).toFixed(2)}`;
const gbp = (n: any) => `£${Number(n || 0).toFixed(2)}`;
const pct = (n: any) => `${Number(n || 0).toFixed(2)}%`;
const tone = (n: any) => (Number(n || 0) >= 0 ? "gain" : "loss");
const clamp = (n: number, min = 0, max = 100) => Math.max(min, Math.min(max, n));

function Card({
  title,
  children,
  wide = false,
  className = "",
}: {
  title?: string;
  children: React.ReactNode;
  wide?: boolean;
  className?: string;
}) {
  return (
    <section className={`card ${wide ? "wide" : ""} ${className}`.trim()}>
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}

function Stat({
  label,
  value,
  sub,
  className = "",
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  className?: string;
}) {
  return (
    <section className="card stat">
      <span>{label}</span>
      <strong className={className}>{value}</strong>
      {sub && <small>{sub}</small>}
    </section>
  );
}

function Meter({ value, label }: { value: number; label: string }) {
  const safeValue = clamp(Number(value || 0));
  return (
    <div className="ai-meter" aria-label={`${label}: ${safeValue.toFixed(0)}%`}>
      <div className="ai-meter-head">
        <span>{label}</span>
        <strong>{safeValue.toFixed(0)}%</strong>
      </div>
      <div className="ai-meter-track">
        <div className="ai-meter-fill" style={{ width: `${safeValue}%` }} />
      </div>
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
  const [status, setStatus] = useState("Connecting...");
  const [message, setMessage] = useState("Ready.");

  const [authToken, setAuthToken] = useState(() => localStorage.getItem("tradebot_auth_token") || "");
  const [secureUsername, setSecureUsername] = useState("");
  const [securePassword, setSecurePassword] = useState("");
  const [authError, setAuthError] = useState("");

  const [chartCurrency, setChartCurrency] = useState<"GBP" | "USD">("GBP");
  const [stockQuery, setStockQuery] = useState("");
  const [stockResults, setStockResults] = useState<any[]>([]);
  const [stockSearchLoading, setStockSearchLoading] = useState(false);

  const [tradingCapInput, setTradingCapInput] = useState("");
  const [tradingCapSaving, setTradingCapSaving] = useState(false);
  const [manualBaselineInput, setManualBaselineInput] = useState("");
  const [baselineSaving, setBaselineSaving] = useState(false);
  const [strategyStrictness, setStrategyStrictness] = useState(1);
  const [strategySaving, setStrategySaving] = useState(false);
  const [maxPositionsInput, setMaxPositionsInput] = useState(6);
  const [positionsSaving, setPositionsSaving] = useState(false);
  const [buySizeMode, setBuySizeMode] = useState<"full" | "partial">("full");
  const [replayCapInput, setReplayCapInput] = useState("");
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayResult, setReplayResult] = useState<AnyObj | null>(null);

  const fetchSeq = useRef(0);
  const fetchInFlight = useRef(false);
  const lastFetchAt = useRef(0);
  const POLL_MS = 10000;

  const token = authToken;
  const secureHeaders = token ? { "X-Auth-Token": token, "x-api-key": token } : {};
  const rate = Number(data?.fx?.usdToGbp || 0.7403);

  const scans = Array.isArray(data?.scans) ? data.scans : [];
  const rawPositions = Array.isArray(data?.positions) ? data.positions : [];
  const positions = [...rawPositions].sort((a: AnyObj, b: AnyObj) => Number(b?.pnlPct || 0) - Number(a?.pnlPct || 0));
  const trades = Array.isArray(data?.trades) ? data.trades : [];
  const logs = Array.isArray(data?.logs) ? data.logs : [];
  const closedTrades = Array.isArray(reports?.closedTrades) ? reports.closedTrades : [];

  const closedTradeTime = (t: AnyObj) => {
    const raw = t?.timestamp || (t?.day && t?.time ? `${t.day}T${t.time}` : t?.day || t?.date || t?.time || "");
    const ms = Date.parse(String(raw));
    return Number.isFinite(ms) ? ms : 0;
  };

  const displayClosedTrades = [...closedTrades]
    .sort((a: AnyObj, b: AnyObj) => closedTradeTime(b) - closedTradeTime(a))
    .slice(0, 80);

  const tradeDate = (t: AnyObj) => {
    const raw = t?.timestamp || (t?.day && t?.time ? `${t.day}T${t.time}` : t?.day || t?.date || "");
    const d = new Date(String(raw));
    return Number.isFinite(d.getTime()) ? d.toLocaleDateString("en-GB") : String(t?.day || t?.date || "—");
  };

  const tradeTime = (t: AnyObj) => {
    if (t?.time) return String(t.time).slice(0, 8);
    const d = new Date(String(t?.timestamp || ""));
    return Number.isFinite(d.getTime()) ? d.toLocaleTimeString("en-GB", { hour12: false }) : "—";
  };

  const totalDeposited = Number(reports?.totalDeposited || 0);
  const totalGainLoss = Number(reports?.totalGainLoss || 0);
  const earned = Number(reports?.earnedSinceDeposit || 0);
  const lost = Number(reports?.lostSinceDeposit || 0);
  const equityHistory = Array.isArray(reports?.equityHistory)
    ? reports.equityHistory
    : Array.isArray(data?.tradeTimeline)
      ? data.tradeTimeline
      : [];

  const dynamicScanner = data?.dynamicMarketScanner || data?.autoUniverse?.dynamicScanner || {};
  const dynamicRows = Array.isArray(dynamicScanner?.rows) ? dynamicScanner.rows : [];
  const strategySettings = data?.strategySettings || {};
  const positionSettings = data?.positionSettings || {};

  const bestCandidate = useMemo(() => {
    const combined = [...scans, ...dynamicRows].filter((item: AnyObj) => item?.symbol);
    return combined.sort((a: AnyObj, b: AnyObj) => {
      const aScore = Number(a?.confidence ?? a?.score ?? a?.quality ?? 0);
      const bScore = Number(b?.confidence ?? b?.score ?? b?.quality ?? 0);
      return bScore - aScore;
    })[0];
  }, [scans, dynamicRows]);

  const aiConfidenceRaw = Number(
    data?.ai?.confidence ??
      data?.aiConfidence ??
      bestCandidate?.confidence ??
      (Number(bestCandidate?.score || 0) <= 1 ? Number(bestCandidate?.score || 0) * 100 : bestCandidate?.score) ??
      0,
  );
  const aiConfidence = clamp(aiConfidenceRaw <= 1 ? aiConfidenceRaw * 100 : aiConfidenceRaw);

  const marketLabel = String(data?.market?.label || (data?.market?.isOpen ? "OPEN" : "CLOSED"));
  const marketRegime = String(data?.ai?.marketRegime || data?.marketRegime || data?.regime || marketLabel);
  const riskLabel = String(data?.ai?.risk || data?.riskLevel || (Number(data?.account?.pnlDay || 0) < 0 ? "CAUTIOUS" : "NORMAL"));
  const currentAction = String(
    data?.ai?.action ||
      data?.lastAction ||
      (data?.botEnabled ? (data?.market?.isOpen ? "Scanning for qualified opportunities" : "Waiting for market open") : "Bot paused"),
  );

  const healthSignals = [
    status === "Connected",
    Boolean(data && Object.keys(data).length),
    Boolean(reports && Object.keys(reports).length),
    data?.botEnabled !== undefined,
  ];
  const botHealth = Math.round((healthSignals.filter(Boolean).length / healthSignals.length) * 100);

  const aiReasons = useMemo(() => {
    const supplied = bestCandidate?.reasons || bestCandidate?.reasoning || bestCandidate?.why;
    if (Array.isArray(supplied)) return supplied.slice(0, 4).map(String);
    if (typeof supplied === "string") return supplied.split(/[|•,]/).map((s) => s.trim()).filter(Boolean).slice(0, 4);

    const result: string[] = [];
    if (Number(bestCandidate?.relative_volume || bestCandidate?.relativeVolume || 0) > 1.5) result.push("Strong relative volume");
    if (Number(bestCandidate?.distance_vwap_pct || bestCandidate?.distanceVwapPct || 0) > 0) result.push("Trading above VWAP");
    if (Number(bestCandidate?.gap_pct || bestCandidate?.changePct || 0) > 0) result.push("Positive price momentum");
    if (bestCandidate?.symbol) result.push("Highest-ranked current candidate");
    return result.slice(0, 4);
  }, [bestCandidate]);

  useEffect(() => {
    const cap = Number(banking?.maxTradingCapitalGbp ?? data?.banking?.maxTradingCapitalGbp ?? 0);
    if (cap > 0 && !tradingCapInput) setTradingCapInput(String(Math.round(cap)));
    if (cap > 0 && !replayCapInput) setReplayCapInput(String(Math.round(cap)));
  }, [banking?.maxTradingCapitalGbp, data?.banking?.maxTradingCapitalGbp]);

  useEffect(() => {
    const level = Number(data?.strategySettings?.level);
    if (Number.isFinite(level)) setStrategyStrictness(Math.max(0, Math.min(2, level)));
  }, [data?.strategySettings?.level]);

  useEffect(() => {
    const maxPos = Number(data?.positionSettings?.maxPositions ?? data?.maxPositions ?? data?.config?.maxPositions);
    if (Number.isFinite(maxPos) && maxPos > 0) setMaxPositionsInput(Math.max(1, Math.min(10, maxPos)));
  }, [data?.positionSettings?.maxPositions, data?.maxPositions, data?.config?.maxPositions]);

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
      setSecurePassword("");
    } catch (e: any) {
      setAuthError(e?.message || "Login failed");
    }
  }

  function secureLogout() {
    localStorage.removeItem("tradebot_auth_token");
    localStorage.removeItem("dashboard_api_key");
    fetchSeq.current += 1;
    fetchInFlight.current = false;
    lastFetchAt.current = 0;
    setAuthToken("");
    setData({});
    setReports({});
    setBanking({});
    setStatus("Logged out");
    setMessage("Logged out.");
    setTab("overview");
  }

  const fetchData = useCallback(
    async (force = false) => {
      if (!authToken) return;
      const now = Date.now();
      if (!force && (fetchInFlight.current || now - lastFetchAt.current < POLL_MS)) return;

      fetchInFlight.current = true;
      lastFetchAt.current = now;
      const seq = ++fetchSeq.current;

      try {
        const headers = { "X-Auth-Token": authToken, "x-api-key": authToken };
        const [statusRes, reportRes, bankingRes] = await Promise.allSettled([
          fetch(`${API_URL}/status`, { cache: "no-store", headers }).then(readJson),
          fetch(`${API_URL}/reports`, { cache: "no-store", headers }).then(readJson),
          fetch(`${API_URL}/banking-status`, { cache: "no-store", headers }).then(readJson),
        ]);

        if (seq !== fetchSeq.current) return;

        if (statusRes.status === "fulfilled") {
          const json = statusRes.value;
          if (json && typeof json === "object") {
            setData((prev) => ({ ...prev, ...json }));
            if (json?.positionSettings?.buySizeMode) {
              setBuySizeMode(json.positionSettings.buySizeMode === "partial" ? "partial" : "full");
            }
          }
        }

        if (reportRes.status === "fulfilled" && reportRes.value) {
          setReports((prev) => ({ ...prev, ...reportRes.value }));
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
    },
    [authToken],
  );

  useEffect(() => {
    if (!authToken) return;
    fetchData(true);
    const timer = window.setInterval(() => fetchData(false), POLL_MS);
    return () => window.clearInterval(timer);
  }, [authToken, fetchData]);

  useEffect(() => {
    if (!authToken) return;
    const now = new Date();
    const nextMidnight = new Date(now);
    nextMidnight.setHours(24, 0, 0, 0);
    const timeout = window.setTimeout(secureLogout, Math.max(1000, nextMidnight.getTime() - now.getTime() + 500));
    return () => window.clearTimeout(timeout);
  }, [authToken]);

  async function action(endpoint: string) {
    if (!token) return setMessage("Please login first.");

    if (endpoint === "/pause") setData((prev) => ({ ...prev, botEnabled: false }));
    if (endpoint === "/resume") setData((prev) => ({ ...prev, botEnabled: true }));
    setMessage(`Sending ${endpoint.replaceAll("/", " ").trim()}...`);

    try {
      const res = await fetch(`${API_URL}${endpoint}`, { method: "POST", headers: secureHeaders, cache: "no-store" });
      const json = await readJson(res);
      if (!res.ok || json?.ok === false) throw new Error(json?.detail || json?.message || `Action failed (${res.status})`);
      setMessage(json?.message || json?.detail || "Action completed.");
    } catch (e: any) {
      setMessage(e?.message || "Action failed.");
    } finally {
      await fetchData(true);
    }
  }

  async function searchStocks(queryOverride?: string) {
    const query = (queryOverride ?? stockQuery).trim();
    if (!query) return setStockResults([]);
    setStockSearchLoading(true);
    try {
      const res = await fetch(`${API_URL}/search-stocks?q=${encodeURIComponent(query)}`, { cache: "no-store", headers: secureHeaders });
      const json = await readJson(res);
      setStockResults(Array.isArray(json?.results) ? json.results : []);
    } catch {
      setMessage("Stock search failed.");
    } finally {
      setStockSearchLoading(false);
    }
  }

  async function postSetting(endpoint: string, payload: AnyObj, successText: string) {
    if (!token) throw new Error("Please login first.");
    const res = await fetch(`${API_URL}${endpoint}`, {
      method: "POST",
      headers: { ...secureHeaders, "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(payload),
    });
    const json = await readJson(res);
    if (!res.ok || json?.ok === false) throw new Error(json?.detail || json?.message || successText);
    setMessage(json?.message || successText);
    await fetchData(true);
    return json;
  }

  async function saveTradingCap() {
    const capGbp = Number(tradingCapInput);
    if (!Number.isFinite(capGbp) || capGbp <= 0) return setMessage("Enter a valid trading cap in GBP.");
    setTradingCapSaving(true);
    try {
      const json = await postSetting("/trading-cap", { capGbp, currency: "GBP" }, "Trading cap saved.");
      setBanking(json || {});
    } catch (e: any) {
      setMessage(e?.message || "Could not save trading cap.");
    } finally {
      setTradingCapSaving(false);
    }
  }

  async function saveStrategy() {
    const level = Math.max(0, Math.min(2, Number(strategyStrictness)));
    const preset = level === 0 ? "safe" : level === 2 ? "aggressive" : "balanced";
    setStrategySaving(true);
    try {
      await postSetting("/strategy-settings", { level, preset }, "AI risk profile saved.");
    } catch (e: any) {
      setMessage(e?.message || "Could not save AI risk profile.");
    } finally {
      setStrategySaving(false);
    }
  }

  async function saveMaxPositions() {
    const maxPositions = Math.max(1, Math.min(10, Number(maxPositionsInput)));
    setPositionsSaving(true);
    try {
      await postSetting("/position-settings", { maxPositions }, "Maximum positions saved.");
    } catch (e: any) {
      setMessage(e?.message || "Could not save maximum positions.");
    } finally {
      setPositionsSaving(false);
    }
  }

  async function saveBuySizeMode(mode: "full" | "partial") {
    try {
      const json = await postSetting("/buy-size-mode", { mode }, "Position size mode saved.");
      setBuySizeMode(json?.buySizeMode === "partial" ? "partial" : mode);
    } catch (e: any) {
      setMessage(e?.message || "Could not save position size mode.");
    }
  }

  async function setManualBaseline() {
    const gbpValue = Number(manualBaselineInput);
    if (!Number.isFinite(gbpValue) || gbpValue <= 0) return setMessage("Enter a valid GBP baseline.");
    const usdValue = rate > 0 ? gbpValue / rate : gbpValue;
    setBaselineSaving(true);
    try {
      await postSetting("/set-baseline", { baseline: usdValue }, "Reporting baseline saved.");
    } catch (e: any) {
      setMessage(e?.message || "Could not save baseline.");
    } finally {
      setBaselineSaving(false);
    }
  }

  async function runBacktestReplay() {
    const capGbp = Number(replayCapInput || tradingCapInput || 0);
    if (!Number.isFinite(capGbp) || capGbp <= 0) return setMessage("Enter a valid replay cap in GBP.");
    setReplayLoading(true);
    try {
      const json = await postSetting("/backtest-replay", { capGbp }, "Replay completed.");
      setReplayResult(json);
    } catch (e: any) {
      setMessage(e?.message || "Replay failed.");
    } finally {
      setReplayLoading(false);
    }
  }

  const reportChart = useMemo(
    () =>
      equityHistory.map((e: AnyObj, i: number) => {
        const raw = e?.time || e?.timestamp || e?.t || e?.label || "";
        const date = new Date(raw);
        const label = Number.isFinite(date.getTime())
          ? date.toLocaleString("en-GB", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })
          : raw || `#${i + 1}`;
        const day = Number.isFinite(date.getTime()) ? date.toLocaleDateString("en-GB", { month: "short", day: "2-digit" }) : `Session ${i + 1}`;
        return {
          label,
          day,
          equity:
            chartCurrency === "GBP"
              ? Number(e?.equityGbp ?? e?.valueGbp ?? Number(e?.equity || e?.value || 0) * rate)
              : Number(e?.equity ?? e?.value ?? 0),
          pnl: chartCurrency === "GBP" ? Number(e?.pnlGbp ?? Number(e?.pnl || 0) * rate) : Number(e?.pnl || 0),
        };
      }),
    [equityHistory, chartCurrency, rate],
  );

  const dailyPnlChart = useMemo(() => {
    const grouped: Record<string, number> = {};
    for (const point of reportChart) grouped[point.day] = (grouped[point.day] || 0) + Number(point.pnl || 0);
    return Object.entries(grouped).map(([day, pnl]) => ({ day, pnl }));
  }, [reportChart]);

  function positionGlowStyle(position: AnyObj): React.CSSProperties {
    const pnlPct = Number(position?.pnlPct || 0);
    if (pnlPct >= 5) return { borderColor: "rgba(34,197,94,.95)", boxShadow: "0 0 26px rgba(34,197,94,.35)" };
    if (pnlPct >= 1) return { borderColor: "rgba(34,197,94,.65)", boxShadow: "0 0 18px rgba(34,197,94,.22)" };
    if (pnlPct > -1) return { borderColor: "rgba(56,189,248,.35)" };
    if (pnlPct > -4) return { borderColor: "rgba(251,146,60,.75)", boxShadow: "0 0 20px rgba(251,146,60,.22)" };
    return { borderColor: "rgba(248,113,113,.9)", boxShadow: "0 0 26px rgba(248,113,113,.3)" };
  }

  if (!authToken) {
    return (
      <div className="app">
        <h1>TradeBot Secure Login</h1>
        <div className="card" style={{ maxWidth: 520, margin: "40px auto" }}>
          <h2>Login</h2>
          <p className="muted">Enter your admin username and password.</p>
          <input value={secureUsername} onChange={(e) => setSecureUsername(e.target.value)} placeholder="Username" style={{ width: "100%", padding: 14, borderRadius: 12, marginBottom: 12 }} />
          <input type="password" value={securePassword} onChange={(e) => setSecurePassword(e.target.value)} placeholder="Password" style={{ width: "100%", padding: 14, borderRadius: 12, marginBottom: 12 }} onKeyDown={(e) => e.key === "Enter" && secureLogin()} />
          <button onClick={secureLogin}>Login</button>
          {authError && <p className="loss">{authError}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="app ai-dashboard">
      <style>{`
        .ai-dashboard .hero-card { background: linear-gradient(135deg, rgba(56,189,248,.10), rgba(99,102,241,.08), rgba(2,6,23,.96)); }
        .ai-dashboard .ai-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
        .ai-dashboard .ai-status-line { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:11px 0; border-bottom:1px solid rgba(148,163,184,.13); }
        .ai-dashboard .ai-status-line:last-child { border-bottom:0; }
        .ai-dashboard .ai-status-line span { color:#94a3b8; }
        .ai-dashboard .ai-meter { margin:14px 0; }
        .ai-dashboard .ai-meter-head { display:flex; justify-content:space-between; margin-bottom:8px; }
        .ai-dashboard .ai-meter-track { height:12px; border-radius:999px; overflow:hidden; background:rgba(148,163,184,.16); }
        .ai-dashboard .ai-meter-fill { height:100%; border-radius:999px; background:linear-gradient(90deg,#38bdf8,#818cf8); }
        .ai-dashboard .decision-card { min-height:240px; }
        .ai-dashboard .decision-symbol { font-size:2.5rem; margin:4px 0; }
        .ai-dashboard .reason-list { margin:14px 0 0; padding-left:20px; }
        .ai-dashboard .reason-list li { margin:8px 0; color:#cbd5e1; }
        .ai-dashboard .health-row { display:flex; justify-content:space-between; gap:10px; padding:8px 0; }
        .ai-dashboard .admin-section { margin-top:18px; }
        .ai-dashboard .admin-section h3 { margin-bottom:8px; }
        .ai-dashboard .compact-table td, .ai-dashboard .compact-table th { white-space:nowrap; }
        @media (max-width:800px){ .ai-dashboard .ai-grid{grid-template-columns:1fr;} }
      `}</style>

      <header className="topbar">
        <div>
          <p className="eyebrow">AI Trading Supervisor · {BOT_VERSION}</p>
          <h1>TradeBot</h1>
        </div>
        <div className="pills">
          <span className={`pill ${status === "Connected" ? "ok" : "warn"}`}>{status}</span>
          <span className={`pill ${data?.market?.isOpen ? "ok" : "warn"}`}>Market {marketLabel}</span>
          <span className={`pill ${data?.botEnabled ? "ok" : "bad"}`}>Bot {data?.botEnabled ? "ON" : "OFF"}</span>
          <span className="pill">{data?.paperMode ? "PAPER" : "LIVE"}</span>
          <button className="ghost" onClick={secureLogout}>Logout</button>
        </div>
      </header>

      <section className="stats">
        <Stat label="Equity" value={gbp(Number(data?.account?.equity || 0) * rate)} sub={usd(data?.account?.equity)} />
        <Stat label="Buying Power" value={gbp(Number(data?.account?.buyingPower || 0) * rate)} sub={usd(data?.account?.buyingPower)} />
        <Stat label="Today" value={gbp(Number(data?.account?.pnlDay || 0) * rate)} sub={usd(data?.account?.pnlDay)} className={tone(data?.account?.pnlDay)} />
        <Stat label="Total Gain/Loss" value={gbp(totalGainLoss * rate)} sub={`Deposited ${gbp(totalDeposited * rate)}`} className={tone(totalGainLoss)} />
      </section>

      <nav className="tabs">
        {(["overview", "positions", "reports", "explorer", "admin"] as Tab[]).map((item) => (
          <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>
            {item === "explorer" ? "MARKET EXPLORER" : item.toUpperCase()}
          </button>
        ))}
      </nav>

      {tab === "overview" && (
        <main className="grid two">
          <Card title="AI Brain" className="hero-card decision-card">
            <div className="ai-grid">
              <div>
                <div className="ai-status-line"><span>Market view</span><b>{marketRegime}</b></div>
                <div className="ai-status-line"><span>Risk</span><b>{riskLabel}</b></div>
                <div className="ai-status-line"><span>Current action</span><b>{currentAction}</b></div>
                <div className="ai-status-line"><span>Open positions</span><b>{positions.length}/{Number(data?.maxPositions || positionSettings?.maxPositions || 0)}</b></div>
              </div>
              <div>
                <Meter value={aiConfidence} label="AI confidence" />
                <Meter value={botHealth} label="System health" />
                <p className="notice">{message}</p>
              </div>
            </div>
          </Card>

          <Card title="Best Current Opportunity" className="decision-card">
            {bestCandidate?.symbol ? (
              <>
                <p className="eyebrow">Top-ranked candidate</p>
                <h3 className="decision-symbol">{bestCandidate.symbol}</h3>
                <div className="summary">
                  <div><span>Confidence</span><b>{aiConfidence.toFixed(0)}%</b></div>
                  <div><span>Price</span><b>{bestCandidate?.price ? usd(bestCandidate.price) : "—"}</b></div>
                  <div><span>Movement</span><b className={tone(bestCandidate?.changePct || bestCandidate?.gap_pct)}>{pct(bestCandidate?.changePct ?? bestCandidate?.gap_pct ?? 0)}</b></div>
                </div>
                <ul className="reason-list">
                  {aiReasons.length ? aiReasons.map((reason) => <li key={reason}>{reason}</li>) : <li>Waiting for the live scanner to provide detailed evidence.</li>}
                </ul>
              </>
            ) : (
              <p className="muted">No ranked opportunity is available yet. The card will populate when the scanner produces candidates.</p>
            )}
          </Card>

          <Card title="Bot Controls">
            <div className="actions">
              <button onClick={() => fetchData(true)}>Refresh</button>
              <button onClick={() => action("/manual-buy")}>Money Buy</button>
              <button className="danger" onClick={() => action("/manual-sell")}>Sell Worst</button>
              <button className="ghost" onClick={() => action("/pause")}>Pause</button>
              <button onClick={() => action("/resume")}>Resume</button>
              <button className="danger" onClick={() => confirm("Emergency sell all open positions?") && action("/emergency-sell")}>Emergency Sell All</button>
            </div>
            <p className="muted">Routine scanner and universe management now stay automatic. Technical controls are in Admin.</p>
          </Card>

          <Card title="Live Portfolio">
            <div className="summary">
              <div><span>Positions</span><b>{positions.length}</b></div>
              <div><span>Next buy</span><b>{gbp(Number(data?.newPositionNotional || 0) * rate)}</b></div>
              <div><span>Win rate</span><b>{pct(Number(data?.dbSummary?.winRate || 0) * 100)}</b></div>
              <div><span>Available slots</span><b>{Math.max(0, Number(data?.maxPositions || positionSettings?.maxPositions || 0) - positions.length)}</b></div>
            </div>
            <div className="position-list">
              {positions.slice(0, 3).map((p: AnyObj) => (
                <article className="position" key={p.symbol} style={positionGlowStyle(p)}>
                  <div><h3>{p.symbol}</h3><p>{usd(p.price)} · Qty {Number(p.qty || 0).toFixed(4)}</p></div>
                  <div className="position-side"><b className={tone(p.pnl)}>{gbp(p.pnlGbp ?? Number(p.pnl || 0) * rate)} · {pct(p.pnlPct)}</b></div>
                </article>
              ))}
              {!positions.length && <p className="muted">No open positions.</p>}
            </div>
          </Card>

          <Card title="Recent AI Activity" wide>
            <div className="log-list">
              {trades.slice(-8).reverse().map((t: AnyObj, i: number) => (
                <div key={i}>{t.time || "—"} · <b>{t.side} {t.symbol}</b> · {t.reason || "Decision recorded"}</div>
              ))}
              {!trades.length && <p className="muted">No recent trading activity.</p>}
            </div>
          </Card>
        </main>
      )}

      {tab === "positions" && (
        <Card title="Open Positions — Best to Worst">
          <p className="muted">Your live holdings, sorted by performance. Manual selling remains available for supervision.</p>
          <div className="position-list">
            {positions.map((p: AnyObj) => (
              <article className="position" key={p.symbol} style={positionGlowStyle(p)}>
                <div>
                  <h3>{p.symbol}</h3>
                  <p>Qty {Number(p.qty || 0).toFixed(4)} · Entry {usd(p.entry)} · Price {usd(p.price)}</p>
                  <p>Value <b>{gbp(p.marketValueGbp ?? Number(p.marketValue || 0) * rate)}</b> / {usd(p.marketValue)}</p>
                </div>
                <div className="position-side">
                  <b className={tone(p.pnl)}>PnL {gbp(p.pnlGbp ?? Number(p.pnl || 0) * rate)} / {usd(p.pnl)} / {pct(p.pnlPct)}</b>
                  <span>{p.trailingActive ? `Trailing floor ${usd(p.trailFloor)}` : `Trail starts ${usd(p.trailStartPrice)}`}</span>
                  <button className="danger" onClick={() => action(`/sell/${p.symbol}`)}>Sell {p.symbol}</button>
                </div>
              </article>
            ))}
            {!positions.length && <p className="muted">No open positions.</p>}
          </div>
        </Card>
      )}

      {tab === "reports" && (
        <main className="grid two reports-page">
          <Card title="Performance Summary" wide>
            <section className="stats">
              <Stat label="Deposited" value={gbp(totalDeposited * rate)} sub={usd(totalDeposited)} />
              <Stat label="Earned" value={gbp(earned * rate)} sub={usd(earned)} className={tone(earned)} />
              <Stat label="Lost" value={gbp(lost * rate)} sub={usd(lost)} className="loss" />
              <Stat label="Current Equity" value={gbp(Number(reports?.currentEquity ?? data?.account?.equity || 0) * rate)} sub={usd(reports?.currentEquity ?? data?.account?.equity)} />
            </section>
          </Card>

          <Card title="Equity History" wide>
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
                    <Tooltip formatter={(v: any) => (chartCurrency === "GBP" ? gbp(v) : usd(v))} />
                    <Area type="monotone" dataKey="equity" stroke="#38bdf8" fill="#38bdf833" />
                  </AreaChart>
                </ResponsiveContainer>
              ) : <p className="muted">No equity history yet.</p>}
            </div>
          </Card>

          <Card title="Daily PnL" wide>
            <div className="chart small-chart">
              {dailyPnlChart.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={dailyPnlChart}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#263450" />
                    <XAxis dataKey="day" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip formatter={(v: any) => (chartCurrency === "GBP" ? gbp(v) : usd(v))} />
                    <Bar dataKey="pnl" fill="#38bdf8" />
                  </BarChart>
                </ResponsiveContainer>
              ) : <p className="muted">Daily PnL will appear as trades are recorded.</p>}
            </div>
          </Card>

          <Card title="Closed Trade History" wide>
            <div className="table-wrap">
              <table className="compact-table">
                <thead><tr><th>Date</th><th>Time</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th><th>%</th></tr></thead>
                <tbody>
                  {displayClosedTrades.map((t: AnyObj, i: number) => (
                    <tr key={i}>
                      <td>{tradeDate(t)}</td><td>{tradeTime(t)}</td><td>{t.symbol}</td><td>{usd(t.entryPrice)}</td><td>{usd(t.exitPrice)}</td><td>{Number(t.qty || 0).toFixed(4)}</td>
                      <td className={tone(t.pnl)}>{gbp(t.pnlGbp ?? Number(t.pnl || 0) * rate)} / {usd(t.pnl)}</td><td className={tone(t.pnl)}>{pct(t.pnlPct)}</td>
                    </tr>
                  ))}
                  {!displayClosedTrades.length && <tr><td colSpan={8}>No matched closed trades yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </Card>
        </main>
      )}

      {tab === "explorer" && (
        <main>
          <Card title="Market Explorer">
            <div className="search-row">
              <input value={stockQuery} onChange={(e) => { setStockQuery(e.target.value); if (e.target.value.trim().length >= 2) searchStocks(e.target.value); if (!e.target.value.trim()) setStockResults([]); }} onKeyDown={(e) => e.key === "Enter" && searchStocks()} placeholder="Search ticker or company, e.g. AMD" />
              <button onClick={() => searchStocks()}>{stockSearchLoading ? "Searching..." : "Search"}</button>
            </div>
            <div className="search-results">
              {stockResults.map((s: AnyObj) => (
                <article className="search-card" key={s.symbol}>
                  <div className="search-main"><div className="logo-circle">{s.symbol.slice(0, 2)}</div><div><h3>{s.name}</h3><p>{s.symbol} · NASDAQ/NYSE</p></div></div>
                  <div className="search-price"><strong>{usd(s.price)}</strong><span className={tone(s.changePct)}>{pct(s.changePct)}</span><small>{gbp(s.priceGbp)}</small></div>
                  <div className="mini-chart">
                    {Array.isArray(s.history) && s.history.length > 1 ? (
                      <ResponsiveContainer width="100%" height="100%"><LineChart data={s.history.map((p: AnyObj, i: number) => ({ ...p, i }))}><Line type="monotone" dataKey="value" stroke="#38bdf8" dot={false} strokeWidth={2} /><Tooltip formatter={(v: any) => usd(v)} /></LineChart></ResponsiveContainer>
                    ) : <p className="muted">Preview builds while you search.</p>}
                  </div>
                  <div className="search-actions"><button onClick={() => action(`/custom-buy/${s.symbol}`)}>Buy</button><button className="ghost" onClick={() => action(`/add-to-universe/${s.symbol}`)}>Pin</button><button className="danger" onClick={() => action(`/remove-from-universe/${s.symbol}`)}>Remove</button></div>
                </article>
              ))}
              {!stockResults.length && <p className="muted">Search a symbol to preview price, movement and chart.</p>}
            </div>
          </Card>
        </main>
      )}

      {tab === "admin" && (
        <main className="grid two">
          <Card title="AI Risk Profile">
            <label className="field"><span>Conservative ← Balanced → Aggressive</span><input type="range" min="0" max="2" step="1" value={strategyStrictness} onChange={(e) => setStrategyStrictness(Number(e.target.value))} /></label>
            <div className="summary"><div><span>Current</span><b>{["Conservative", "Balanced", "Aggressive"][strategyStrictness]}</b></div><div><span>A+ gate</span><b>{Number(strategySettings?.aPlusMinConfidence ?? data?.aPlusMinConfidence ?? 0).toFixed(2)}</b></div></div>
            <button onClick={saveStrategy} disabled={strategySaving}>{strategySaving ? "Saving..." : "Save Risk Profile"}</button>
          </Card>

          <Card title="Capital & Position Limits">
            <label className="field"><span>Trading cap (£)</span><input value={tradingCapInput} onChange={(e) => setTradingCapInput(e.target.value)} inputMode="decimal" /></label>
            <button onClick={saveTradingCap} disabled={tradingCapSaving}>{tradingCapSaving ? "Saving..." : "Save Trading Cap"}</button>
            <label className="field"><span>Maximum open positions: {maxPositionsInput}</span><input type="range" min="1" max="10" value={maxPositionsInput} onChange={(e) => setMaxPositionsInput(Number(e.target.value))} /></label>
            <button onClick={saveMaxPositions} disabled={positionsSaving}>{positionsSaving ? "Saving..." : "Save Position Limit"}</button>
            <div className="actions admin-section"><button className={buySizeMode === "partial" ? "active" : "ghost"} onClick={() => saveBuySizeMode("partial")}>Partial Buy</button><button className={buySizeMode === "full" ? "active" : "ghost"} onClick={() => saveBuySizeMode("full")}>Full Buy</button></div>
          </Card>

          <Card title="Scanner & Universe Tools">
            <div className="actions"><button className="purple" onClick={() => action("/refresh-universe")}>Refresh Universe</button></div>
            <div className="summary"><div><span>Dynamic picks</span><b>{Number(data?.autoUniverse?.dynamicPickCount || dynamicRows.length || 0)}</b></div><div><span>Active symbols</span><b>{Number(data?.autoUniverse?.activeSymbols?.length || 0)}</b></div><div><span>Source</span><b>{dynamicScanner?.source || "market movers"}</b></div></div>
          </Card>

          <Card title="Reports Maintenance">
            <div className="actions"><button onClick={() => action("/backfill-trades")}>Backfill Past Trades</button><button onClick={() => action("/backfill-trades-limited")}>Quick Backfill</button><button onClick={() => action("/rebuild-closed-trades")}>Rebuild Closed Trades</button><button className="danger" onClick={() => confirm("Reset reporting baseline to current equity?") && action("/reset-baseline")}>Reset Baseline</button></div>
            <label className="field"><span>Manual baseline (£)</span><input value={manualBaselineInput} onChange={(e) => setManualBaselineInput(e.target.value)} /></label>
            <button onClick={setManualBaseline} disabled={baselineSaving}>{baselineSaving ? "Saving..." : "Set Manual Baseline"}</button>
          </Card>

          <Card title="Backtest / Paper Replay">
            <label className="field"><span>Replay cap (£)</span><input value={replayCapInput} onChange={(e) => setReplayCapInput(e.target.value)} /></label>
            <button onClick={runBacktestReplay} disabled={replayLoading}>{replayLoading ? "Running..." : "Run Replay"}</button>
            {replayResult && <div className="summary admin-section"><div><span>Trades</span><b>{replayResult?.tradesTested || 0}</b></div><div><span>Win rate</span><b>{pct(Number(replayResult?.winRate || 0) * 100)}</b></div><div><span>PnL</span><b className={tone(replayResult?.replayPnlGbp)}>{gbp(replayResult?.replayPnlGbp)}</b></div></div>}
          </Card>

          <Card title="Developer Diagnostics" wide>
            <div className="ai-grid">
              <div><h3>Recent Logs</h3><div className="log-list">{logs.slice(-80).reverse().map((line: string, i: number) => <div key={i}>{line}</div>)}{!logs.length && <p className="muted">No logs returned.</p>}</div></div>
              <div><h3>Runtime Snapshot</h3><pre>{JSON.stringify({ api: API_URL, version: BOT_VERSION, botEnabled: data?.botEnabled, market: data?.market, strategySettings, positionSettings, banking, autoUniverse: data?.autoUniverse }, null, 2)}</pre></div>
            </div>
          </Card>
        </main>
      )}
    </div>
  );
}
