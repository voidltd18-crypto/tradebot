import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_URL, readJson } from "../lib/api";
import { clamp } from "../lib/format";
import type { AnyObj, BuySizeMode, Currency } from "../lib/types";

export function useTradeBot() {
  const [data, setData] = useState<AnyObj>({});
  const [reports, setReports] = useState<AnyObj>({});
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
  const POLL_MS = 10000;
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

  const fetchData = useCallback(async (force = false) => {
    if (!authToken) return;
    const now = Date.now();
    if (!force && (fetchInFlight.current || now - lastFetchAt.current < POLL_MS)) return;
    fetchInFlight.current = true;
    lastFetchAt.current = now;
    const seq = ++fetchSeq.current;
    try {
      const fetchJson = async (path: string) => {
        const response = await fetch(`${API_URL}${path}`, { cache: "no-store", headers: secureHeaders });
        const json = await readJson(response);
        if (!response.ok) throw new Error(json?.detail || json?.message || `${path} failed (${response.status})`);
        return json || {};
      };
      const [statusResult, reportResult, bankingResult] = await Promise.allSettled([
        fetchJson("/status"),
        fetchJson("/reports"),
        fetchJson("/banking-status"),
      ]);
      if (seq !== fetchSeq.current) return;

      let liveConnected = false;
      if (statusResult.status === "fulfilled" && statusResult.value?.account) {
        setData((previous) => ({ ...previous, ...statusResult.value }));
        const mode = statusResult.value?.positionSettings?.buySizeMode;
        if (mode) setBuySizeMode(mode === "partial" ? "partial" : "full");
        liveConnected = true;
      }
      if (reportResult.status === "fulfilled") {
        setReports((previous) => ({ ...previous, ...reportResult.value }));
      }
      if (bankingResult.status === "fulfilled" && bankingResult.value?.ok !== false) {
        setBanking(bankingResult.value || {});
        // Banking is broker-backed and proves the live API is reachable even if
        // a non-critical report request is slow or temporarily unavailable.
        liveConnected = true;
      }

      setStatus(liveConnected ? "Connected" : "Connection failed");
      if (!liveConnected) {
        const reason = statusResult.status === "rejected" ? statusResult.reason : bankingResult.status === "rejected" ? bankingResult.reason : "Live status unavailable";
        console.error(reason);
      }
    } catch (error) {
      console.error(error);
      setStatus("Connection failed");
    } finally {
      fetchInFlight.current = false;
    }
  }, [authToken]);

  useEffect(() => { if (!authToken) return; fetchData(true); const timer = window.setInterval(() => fetchData(false), POLL_MS); return () => window.clearInterval(timer); }, [authToken, fetchData]);
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
    fetchSeq.current += 1; setAuthToken(""); setData({}); setReports({}); setBanking({}); setStatus("Logged out"); setMessage("Logged out.");
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

  return { data, reports, banking, status, message, authToken, secureUsername, securePassword, authError, setSecureUsername, setSecurePassword, secureLogin, secureLogout, rate, positions, trades, logs, closedTrades, dynamicScanner, dynamicRows, strategySettings, positionSettings, bestCandidate, aiConfidence, marketLabel, marketRegime, riskLabel, currentAction, botHealth, aiReasons, fetchData, action, chartCurrency, setChartCurrency, stockQuery, setStockQuery, stockResults, setStockResults, stockSearchLoading, searchStocks, tradingCapInput, setTradingCapInput, tradingCapSaving, saveTradingCap, manualBaselineInput, setManualBaselineInput, baselineSaving, setManualBaseline, strategyStrictness, setStrategyStrictness, strategySaving, saveStrategy, maxPositionsInput, setMaxPositionsInput, positionsSaving, saveMaxPositions, buySizeMode, saveBuySizeMode, replayCapInput, setReplayCapInput, replayLoading, replayResult, runBacktestReplay };
}
