import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_URL, readJson } from "../lib/api";
import { clamp } from "../lib/format";
import type { AnyObj, BuySizeMode, Currency, Tab } from "../lib/types";

export function useTradeBot(activeTab: Tab = "overview") {
  const [data, setData] = useState<AnyObj>({});
  const [reports, setReports] = useState<AnyObj>({});
  const [reportsLoading, setReportsLoading] = useState(false);
  const [reportsError, setReportsError] = useState("");
  const [reportsUpdatedAt, setReportsUpdatedAt] = useState("");
  const [banking, setBanking] = useState<AnyObj>({});
  const [status, setStatus] = useState("Connecting...");
  const [message, setMessage] = useState("Ready.");
  const [authToken, setAuthToken] = useState(() => localStorage.getItem("tradebot_auth_token") || "");
  const [secureUsername, setSecureUsername] = useState("");
  const [securePassword, setSecurePassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [chartCurrency, setChartCurrency] = useState<Currency>("GBP");
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
  const [buySizeMode, setBuySizeMode] = useState<BuySizeMode>("full");
  const [replayCapInput, setReplayCapInput] = useState("");
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayResult, setReplayResult] = useState<AnyObj | null>(null);

  const fetchSeq = useRef(0);
  const fetchInFlight = useRef(false);
  const lastFetchAt = useRef(0);
  const reportsInFlight = useRef(false);
  const reportsLastFetchAt = useRef(0);
  const POLL_MS = 10000;
  const REPORTS_REFRESH_MS = 60000;
  const token = authToken;
  const secureHeaders = token ? { "X-Auth-Token": token, "x-api-key": token } : {};
  const rate = Number(data?.fx?.usdToGbp || 0.7403);

  const scans = Array.isArray(data?.scans) ? data.scans : [];
  const positions = useMemo(() => [...(Array.isArray(data?.positions) ? data.positions : [])].sort((a: AnyObj, b: AnyObj) => Number(b?.pnlPct || 0) - Number(a?.pnlPct || 0)), [data?.positions]);
  const trades = Array.isArray(data?.trades) ? data.trades : [];
  const logs = Array.isArray(data?.logs) ? data.logs : [];
  const closedTrades = Array.isArray(reports?.closedTrades) ? reports.closedTrades : [];
  const dynamicScanner = data?.dynamicMarketScanner || data?.autoUniverse?.dynamicScanner || {};
  const dynamicRows = Array.isArray(dynamicScanner?.rows) ? dynamicScanner.rows : [];
  const strategySettings = data?.strategySettings || {};
  const positionSettings = data?.positionSettings || {};

  const bestCandidate = useMemo(() => [...scans, ...dynamicRows].filter((item: AnyObj) => item?.symbol).sort((a: AnyObj, b: AnyObj) => Number(b?.confidence ?? b?.score ?? b?.quality ?? 0) - Number(a?.confidence ?? a?.score ?? a?.quality ?? 0))[0], [scans, dynamicRows]);
  const candidateScore = Number(bestCandidate?.confidence ?? bestCandidate?.score ?? bestCandidate?.quality ?? 0);
  const aiConfidenceRaw = Number(data?.ai?.confidence ?? data?.aiConfidence ?? (candidateScore <= 1 ? candidateScore * 100 : candidateScore) ?? 0);
  const aiConfidence = clamp(aiConfidenceRaw <= 1 ? aiConfidenceRaw * 100 : aiConfidenceRaw);
  const marketLabel = String(data?.market?.label || (data?.market?.isOpen ? "OPEN" : "CLOSED"));
  const marketRegime = String(data?.ai?.marketRegime || data?.marketRegime || data?.regime || marketLabel);
  const riskLabel = String(data?.ai?.risk || data?.riskLevel || (Number(data?.account?.pnlDay || 0) < 0 ? "CAUTIOUS" : "NORMAL"));
  const currentAction = String(data?.ai?.action || data?.lastAction || (data?.botEnabled ? (data?.market?.isOpen ? "Scanning for qualified opportunities" : "Waiting for market open") : "Bot paused"));
  const botHealth = Math.round(([status === "Connected", Object.keys(data).length > 0, Object.keys(reports).length > 0, data?.botEnabled !== undefined].filter(Boolean).length / 4) * 100);
  const aiReasons = useMemo(() => {
    const supplied = bestCandidate?.reasons || bestCandidate?.reasoning || bestCandidate?.why;
    if (Array.isArray(supplied)) return supplied.slice(0, 4).map(String);
    if (typeof supplied === "string") return supplied.split(/[|•,]/).map((s: string) => s.trim()).filter(Boolean).slice(0, 4);
    const result: string[] = [];
    if (Number(bestCandidate?.relative_volume || bestCandidate?.relativeVolume || 0) > 1.5) result.push("Strong relative volume");
    if (Number(bestCandidate?.distance_vwap_pct || bestCandidate?.distanceVwapPct || 0) > 0) result.push("Trading above VWAP");
    if (Number(bestCandidate?.gap_pct || bestCandidate?.changePct || 0) > 0) result.push("Positive price momentum");
    if (bestCandidate?.symbol) result.push("Highest-ranked current candidate");
    return result;
  }, [bestCandidate]);

  const fetchJsonWithTimeout = useCallback(async (path: string, timeoutMs = 30000) => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${API_URL}${path}`, {
        cache: "no-store",
        headers: secureHeaders,
        signal: controller.signal,
      });
      const json = await readJson(response);
      if (!response.ok) throw new Error(json?.detail || json?.message || `${path} failed (${response.status})`);
      return json || {};
    } finally {
      window.clearTimeout(timer);
    }
  }, [authToken]);

  const loadReports = useCallback(async (force = false) => {
    if (!authToken) return;
    const now = Date.now();
    if (!force && (reportsInFlight.current || now - reportsLastFetchAt.current < REPORTS_REFRESH_MS)) return;

    reportsInFlight.current = true;
    reportsLastFetchAt.current = now;
    setReportsLoading(true);
    setReportsError("");

    try {
      const json = await fetchJsonWithTimeout("/reports", 90000);
      setReports((previous) => ({ ...previous, ...json }));
      setReportsUpdatedAt(new Date().toISOString());
    } catch (error: any) {
      if (error?.name === "AbortError") {
        setReportsError("Reports are taking longer than expected. Live trading, balances, positions and AI remain connected.");
      } else {
        setReportsError(error?.message || "Reports unavailable.");
        console.error("Reports load failed", error);
      }
    } finally {
      reportsInFlight.current = false;
      setReportsLoading(false);
    }
  }, [authToken, fetchJsonWithTimeout]);

  const fetchData = useCallback(async (force = false) => {
    if (!authToken) return;
    const now = Date.now();
    if (!force && (fetchInFlight.current || now - lastFetchAt.current < POLL_MS)) return;

    fetchInFlight.current = true;
    lastFetchAt.current = now;
    const seq = ++fetchSeq.current;
    let liveConnected = false;

    // V18.2.8: hydrate independently. Previously Promise.allSettled meant a fast
    // /banking-status response was held hostage by a slow /status request for up
    // to 30 seconds. Each panel now paints as soon as its own endpoint returns.
    const bankingPromise = fetchJsonWithTimeout("/banking-status", 10000)
      .then((value) => {
        if (seq !== fetchSeq.current || value?.ok === false) return;
        setBanking(value || {});
        liveConnected = true;
        setStatus("Connected");

        // Give the header a useful equity value immediately while the richer
        // status snapshot is still arriving. /status will replace this with the
        // authoritative live account/positions payload a moment later.
        const eq = Number(value?.accountEquity || 0);
        if (eq > 0) {
          setData((previous) => ({
            ...previous,
            account: {
              ...(previous?.account || {}),
              equity: previous?.account?.equity || eq,
              equityGbp: previous?.account?.equityGbp || eq * Number(previous?.fx?.usdToGbp || 0.7403),
            },
            banking: { ...(previous?.banking || {}), ...(value || {}) },
          }));
        }
      })
      .catch((error: any) => {
        if (error?.name !== "AbortError") console.error("Banking status load failed", error);
      });

    const statusPromise = fetchJsonWithTimeout("/status", 12000)
      .then((value) => {
        if (seq !== fetchSeq.current) return;
        if (value && Object.keys(value).length > 0) {
          setData((previous) => ({ ...previous, ...value }));
          const mode = value?.positionSettings?.buySizeMode;
          if (mode) setBuySizeMode(mode === "partial" ? "partial" : "full");
          liveConnected = true;
          setStatus("Connected");
        }
      })
      .catch((error: any) => {
        if (error?.name !== "AbortError") console.error("Live status load failed", error);
      });

    try {
      await Promise.allSettled([bankingPromise, statusPromise]);
      if (seq !== fetchSeq.current) return;
      if (!liveConnected) setStatus("Connection failed");
    } finally {
      fetchInFlight.current = false;
    }
  }, [authToken, fetchJsonWithTimeout]);


  useEffect(() => {
    if (!authToken) return;
    fetchData(true);
    const timer = window.setInterval(() => fetchData(false), POLL_MS);
    return () => window.clearInterval(timer);
  }, [authToken, fetchData]);

  useEffect(() => {
    if (!authToken || activeTab !== "reports") return;
    loadReports(false);
  }, [authToken, activeTab, loadReports]);
  useEffect(() => { const cap = Number(banking?.maxTradingCapitalGbp ?? data?.banking?.maxTradingCapitalGbp ?? 0); if (cap > 0 && !tradingCapInput) setTradingCapInput(String(Math.round(cap))); if (cap > 0 && !replayCapInput) setReplayCapInput(String(Math.round(cap))); }, [banking?.maxTradingCapitalGbp, data?.banking?.maxTradingCapitalGbp]);
  useEffect(() => { const level = Number(data?.strategySettings?.level); if (Number.isFinite(level)) setStrategyStrictness(Math.max(0, Math.min(2, level))); }, [data?.strategySettings?.level]);
  useEffect(() => { const max = Number(data?.positionSettings?.maxPositions ?? data?.maxPositions ?? data?.config?.maxPositions); if (Number.isFinite(max) && max > 0) setMaxPositionsInput(Math.max(1, Math.min(10, max))); }, [data?.positionSettings?.maxPositions, data?.maxPositions, data?.config?.maxPositions]);

  async function secureLogin() {
    try {
      setAuthError("");
      const response = await fetch(`${API_URL}/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: secureUsername.trim(), password: securePassword }) });
      const json = await readJson(response);
      if (!response.ok || !json?.token) throw new Error(json?.detail || "Login failed");
      localStorage.setItem("tradebot_auth_token", json.token);
      localStorage.setItem("dashboard_api_key", json.token);
      setAuthToken(json.token);
      setSecurePassword("");
    } catch (error: any) { setAuthError(error?.message || "Login failed"); }
  }

  function secureLogout() {
    localStorage.removeItem("tradebot_auth_token"); localStorage.removeItem("dashboard_api_key");
    fetchSeq.current += 1; fetchInFlight.current = false; reportsInFlight.current = false; setAuthToken(""); setData({}); setReports({}); setReportsLoading(false); setReportsError(""); setReportsUpdatedAt(""); setBanking({}); setStatus("Logged out"); setMessage("Logged out.");
  }

  async function action(endpoint: string) {
    if (!token) return setMessage("Please login first.");
    setMessage(`Sending ${endpoint}...`);
    try {
      const response = await fetch(`${API_URL}${endpoint}`, { method: "POST", headers: secureHeaders, cache: "no-store" });
      const json = await readJson(response);
      if (!response.ok || json?.ok === false) throw new Error(json?.detail || json?.message || `Action failed (${response.status})`);
      setMessage(json?.message || json?.detail || "Action completed.");
    } catch (error: any) { setMessage(error?.message || "Action failed."); }
    await fetchData(true);
  }

  async function searchStocks(queryOverride?: string) {
    const query = (queryOverride ?? stockQuery).trim();
    if (!query) return setStockResults([]);
    setStockSearchLoading(true);
    try {
      const response = await fetch(`${API_URL}/search-stocks?q=${encodeURIComponent(query)}`, { cache: "no-store", headers: secureHeaders });
      const json = await readJson(response);
      setStockResults(Array.isArray(json?.results) ? json.results : []);
    } catch { setMessage("Stock search failed."); } finally { setStockSearchLoading(false); }
  }

  async function postSetting(endpoint: string, payload: AnyObj, success: string) {
    const response = await fetch(`${API_URL}${endpoint}`, { method: "POST", headers: { ...secureHeaders, "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify(payload) });
    const json = await readJson(response);
    if (!response.ok || json?.ok === false) throw new Error(json?.detail || json?.message || "Could not save setting");
    setMessage(json?.message || success);
    await fetchData(true);
    return json;
  }

  async function saveTradingCap() { const capGbp = Number(tradingCapInput); if (!(capGbp > 0)) return setMessage("Enter a valid trading cap in GBP."); setTradingCapSaving(true); try { await postSetting("/trading-cap", { capGbp, currency: "GBP" }, "Trading cap saved."); } catch (e: any) { setMessage(e.message); } finally { setTradingCapSaving(false); } }
  async function saveStrategy() { setStrategySaving(true); try { const level = Math.max(0, Math.min(2, strategyStrictness)); await postSetting("/strategy-settings", { level, preset: ["safe", "balanced", "aggressive"][level] }, "Risk profile saved."); } catch (e: any) { setMessage(e.message); } finally { setStrategySaving(false); } }
  async function saveMaxPositions() { setPositionsSaving(true); try { await postSetting("/position-settings", { maxPositions: Math.max(1, Math.min(10, maxPositionsInput)) }, "Position limit saved."); } catch (e: any) { setMessage(e.message); } finally { setPositionsSaving(false); } }
  async function saveBuySizeMode(mode: BuySizeMode) { try { await postSetting("/buy-size-mode", { mode }, "Buy size mode saved."); setBuySizeMode(mode); } catch (e: any) { setMessage(e.message); } }
  async function setManualBaseline() { const gbpValue = Number(manualBaselineInput); if (!(gbpValue > 0)) return setMessage("Enter a valid GBP baseline."); setBaselineSaving(true); try { await postSetting("/set-baseline", { baseline: rate > 0 ? gbpValue / rate : gbpValue }, "Baseline saved."); } catch (e: any) { setMessage(e.message); } finally { setBaselineSaving(false); } }
  async function runBacktestReplay() { const capGbp = Number(replayCapInput || tradingCapInput); if (!(capGbp > 0)) return setMessage("Enter a valid replay cap."); setReplayLoading(true); try { const result = await postSetting("/backtest-replay", { capGbp }, "Replay complete."); setReplayResult(result); } catch (e: any) { setMessage(e.message); } finally { setReplayLoading(false); } }

  return { data, reports, reportsLoading, reportsError, reportsUpdatedAt, loadReports, banking, status, message, authToken, secureUsername, securePassword, authError, setSecureUsername, setSecurePassword, secureLogin, secureLogout, rate, positions, trades, logs, closedTrades, dynamicScanner, dynamicRows, strategySettings, positionSettings, bestCandidate, aiConfidence, marketLabel, marketRegime, riskLabel, currentAction, botHealth, aiReasons, fetchData, action, chartCurrency, setChartCurrency, stockQuery, setStockQuery, stockResults, setStockResults, stockSearchLoading, searchStocks, tradingCapInput, setTradingCapInput, tradingCapSaving, saveTradingCap, manualBaselineInput, setManualBaselineInput, baselineSaving, setManualBaseline, strategyStrictness, setStrategyStrictness, strategySaving, saveStrategy, maxPositionsInput, setMaxPositionsInput, positionsSaving, saveMaxPositions, buySizeMode, saveBuySizeMode, replayCapInput, setReplayCapInput, replayLoading, replayResult, runBacktestReplay };
}
