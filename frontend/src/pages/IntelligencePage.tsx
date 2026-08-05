import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card } from "../components/Card";
import { Meter } from "../components/Meter";
import { API_URL, readJson } from "../lib/api";
import { clamp } from "../lib/format";
import type { AnyObj } from "../lib/types";

type IntelligenceSection = "ceo" | "board" | "brain" | "market" | "research" | "symbols" | "rules" | "evolution" | "memory" | "scientist" | "operations";

type EndpointState = {
  data: AnyObj;
  error: string;
  loading: boolean;
};

const EMPTY_ENDPOINT: EndpointState = { data: {}, error: "", loading: true };

function num(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function text(value: unknown, fallback = "Not available yet"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function pct(value: unknown): number {
  const parsed = num(value);
  return clamp(Math.abs(parsed) <= 1 ? parsed * 100 : parsed);
}

function firstArray(...values: unknown[]): AnyObj[] {
  for (const value of values) {
    if (Array.isArray(value)) return value.filter((item) => item && typeof item === "object") as AnyObj[];
  }
  return [];
}

function firstObject(...values: unknown[]): AnyObj {
  for (const value of values) {
    if (value && typeof value === "object" && !Array.isArray(value)) return value as AnyObj;
  }
  return {};
}

function keyLabel(value: string): string {
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatOperatorValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (key === "tradingCapUsd") return `$${num(value).toFixed(2)}`;
  if (key === "targetPositionValuePct" || key === "maxPositionValuePct") return `${pct(value).toFixed(0)}%`;
  if (["stopLossPct", "fastStopLossPct", "trailStartPct", "trailGivebackPct"].includes(key)) return `${num(value).toFixed(2)}%`;
  if (key === "symbolExclusions") return Array.isArray(value) ? (value.length ? value.join(", ") : "None") : text(value, "None");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return text(value, "—");
}

function StatTile({ label, value, sub, tone = "" }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className={`intelligence-stat ${tone}`.trim()}><span>{label}</span><strong>{value}</strong>{sub && <small>{sub}</small>}</div>;
}

function EmptyState({ endpoint, error }: { endpoint: string; error?: string }) {
  return <div className="intelligence-empty"><strong>No evidence returned yet</strong><span>{error || `The ${endpoint} endpoint is connected, but it has not produced displayable evidence yet.`}</span></div>;
}

function DataTable({ rows, columns }: { rows: AnyObj[]; columns: { key: string; label: string; render?: (row: AnyObj) => React.ReactNode }[] }) {
  if (!rows.length) return <EmptyState endpoint="selected intelligence" />;
  return <div className="table-wrap"><table className="compact-table"><thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={String(row.id ?? row.key ?? row.symbol ?? index)}>{columns.map((column) => <td key={column.key}>{column.render ? column.render(row) : text(row[column.key], "—")}</td>)}</tr>)}</tbody></table></div>;
}

export function IntelligencePage({ authToken, marketRegime, botHealth, aiConfidence, fetchData }: {
  authToken: string;
  marketRegime: string;
  botHealth: number;
  aiConfidence: number;
  fetchData: (force?: boolean) => Promise<void>;
}) {
  const [section, setSection] = useState<IntelligenceSection>("ceo");
  const [lastUpdated, setLastUpdated] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [promotionBusy, setPromotionBusy] = useState(false);
  const [promotionMessage, setPromotionMessage] = useState("");
  const [sources, setSources] = useState<Record<string, EndpointState>>({
    advisor: EMPTY_ENDPOINT,
    shadow: EMPTY_ENDPOINT,
    decision: EMPTY_ENDPOINT,
    strategy: EMPTY_ENDPOINT,
    symbols: EMPTY_ENDPOINT,
    rules: EMPTY_ENDPOINT,
    weakness: EMPTY_ENDPOINT,
    marketDna: EMPTY_ENDPOINT,
    patterns: EMPTY_ENDPOINT,
    weekly: EMPTY_ENDPOINT,
    research: EMPTY_ENDPOINT,
    v7Status: EMPTY_ENDPOINT,
    v8Status: EMPTY_ENDPOINT,
    promotion: EMPTY_ENDPOINT,
    operator: EMPTY_ENDPOINT,
    status: EMPTY_ENDPOINT,
    reports: EMPTY_ENDPOINT,
    reputation: EMPTY_ENDPOINT,
    ceoStatus: EMPTY_ENDPOINT,
    ceoJournal: EMPTY_ENDPOINT,
    ceoReviews: EMPTY_ENDPOINT,
    ceoConstitution: EMPTY_ENDPOINT,
    boardStatus: EMPTY_ENDPOINT,
    boardHistory: EMPTY_ENDPOINT,
    boardConstitution: EMPTY_ENDPOINT,
    memoryStatus: EMPTY_ENDPOINT,
    memoryKnowledge: EMPTY_ENDPOINT,
    memoryEvents: EMPTY_ENDPOINT,
    memoryConstitution: EMPTY_ENDPOINT,
    scientistStatus: EMPTY_ENDPOINT,
    scientistHypotheses: EMPTY_ENDPOINT,
    scientistExperiments: EMPTY_ENDPOINT,
    scientistEvents: EMPTY_ENDPOINT,
    scientistConstitution: EMPTY_ENDPOINT,
    operationsStatus: EMPTY_ENDPOINT,
    operationsComponents: EMPTY_ENDPOINT,
    operationsAlerts: EMPTY_ENDPOINT,
    operationsHistory: EMPTY_ENDPOINT,
    operationsConstitution: EMPTY_ENDPOINT,
    operationsDependencies: EMPTY_ENDPOINT,
    operationsWatchdogs: EMPTY_ENDPOINT,
    operationsQueues: EMPTY_ENDPOINT,
    operationsDoctor: EMPTY_ENDPOINT,
    operationsEngineHealth: EMPTY_ENDPOINT,
  });

  const endpoints = useMemo(() => ({
    advisor: "/ai-advisor/summary",
    shadow: "/shadow-trading/summary",
    decision: "/decision-intelligence/summary",
    strategy: "/strategy-intelligence/summary",
    symbols: "/symbol-intelligence/summary",
    rules: "/rule-intelligence/summary",
    weakness: "/weakness-intelligence/summary",
    marketDna: "/v4/market-dna",
    patterns: "/v4/patterns",
    weekly: "/v4/weekly-intelligence",
    research: "/v7/research/insights",
    v7Status: "/v7/status",
    v8Status: "/v8/status",
    promotion: "/v10/promotion/status",
    operator: "/v10/operator/status",
    status: "/status",
    reports: "/reports",
    reputation: "/v10/symbol-reputation/summary",
    ceoStatus: "/v12/ceo/status?journal_limit=40",
    ceoJournal: "/v12/ceo/journal?limit=100",
    ceoReviews: "/v12/ceo/reviews?limit=30",
    ceoConstitution: "/v12/ceo/constitution",
    boardStatus: "/v12/board/status",
    boardHistory: "/v12/board/history?limit=30",
    boardConstitution: "/v12/board/constitution",
    memoryStatus: "/v13/memory/status",
    memoryKnowledge: "/v13/memory/knowledge?limit=200",
    memoryEvents: "/v13/memory/events?limit=100",
    memoryConstitution: "/v13/memory/constitution",
    scientistStatus: "/v14/scientist/status",
    scientistHypotheses: "/v14/scientist/hypotheses?limit=200",
    scientistExperiments: "/v14/scientist/experiments?limit=200",
    scientistEvents: "/v14/scientist/events?limit=100",
    scientistConstitution: "/v14/scientist/constitution",
    operationsStatus: "/v15/operations/status",
    operationsComponents: "/v15/operations/components",
    operationsAlerts: "/v15/operations/alerts?limit=100&status=ACTIVE",
    operationsHistory: "/v15/operations/history?limit=100",
    operationsConstitution: "/v15/operations/constitution",
    operationsDependencies: "/v15/operations/dependencies",
    operationsWatchdogs: "/v15/operations/watchdogs",
    operationsQueues: "/v15/operations/queues",
    operationsDoctor: "/v15/operations/doctor",
    operationsEngineHealth: "/v15/operations/engine-health",
  }), []);

  const load = useCallback(async () => {
    if (!authToken) return;
    setRefreshing(true);
    const headers = { "X-Auth-Token": authToken, "x-api-key": authToken };
    const entries = Object.entries(endpoints);
    const collected: Record<string, EndpointState> = {};

    const fetchEndpoint = async (key: string, endpoint: string): Promise<void> => {
      let lastError = "Endpoint unavailable";
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        const controller = new AbortController();
        // Reports and Operator are composite snapshots and can legitimately need a
        // little longer on the first request after a Render restart. Other endpoints
        // keep the tighter limit so real outages are still surfaced quickly.
        const timeoutSeconds = ["reports", "operator", "advisor", "evolution"].includes(key) ? 60 : 30;
        const timeout = window.setTimeout(() => controller.abort(), timeoutSeconds * 1000);
        try {
          const response = await fetch(`${API_URL}${endpoint}`, {
            cache: "no-store",
            headers,
            signal: controller.signal,
          });
          const json = await readJson(response);
          if (!response.ok) throw new Error(json?.detail || json?.message || `HTTP ${response.status}`);
          collected[key] = { data: json || {}, error: "", loading: false };
          return;
        } catch (error: any) {
          lastError = error?.name === "AbortError"
            ? `Request timed out after ${timeoutSeconds} seconds`
            : error?.message || "Endpoint unavailable";
          if (attempt < 2) await new Promise((resolve) => window.setTimeout(resolve, 500));
        } finally {
          window.clearTimeout(timeout);
        }
      }
      collected[key] = { data: {}, error: lastError, loading: false };
    };

    try {
      // Avoid hammering SQLite and Render with 43 simultaneous requests.
      // Four-at-a-time keeps the dashboard responsive without creating a health-check storm.
      const batchSize = 4;
      for (let index = 0; index < entries.length; index += batchSize) {
        const batch = entries.slice(index, index + batchSize);
        await Promise.all(batch.map(([key, endpoint]) => fetchEndpoint(key, endpoint)));
        if (index + batchSize < entries.length) {
          await new Promise((resolve) => window.setTimeout(resolve, 150));
        }
      }
      setSources(collected);
      setLastUpdated(new Date().toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }));
    } finally {
      setRefreshing(false);
    }
  }, [authToken, endpoints]);

  useEffect(() => { load(); }, [load]);

  const advisor = sources.advisor.data;
  const shadow = sources.shadow.data;
  const decision = sources.decision.data;
  const strategy = sources.strategy.data;
  const symbols = sources.symbols.data;
  const rules = sources.rules.data;
  const weakness = sources.weakness.data;
  const marketDna = sources.marketDna.data;
  const patterns = sources.patterns.data;
  const weekly = sources.weekly.data;
  const research = sources.research.data;
  const v7Status = sources.v7Status.data;
  const v8Status = sources.v8Status.data;
  const promotion = sources.promotion.data;
  const operator = sources.operator.data;
  const liveStatus = sources.status.data;
  const reportsData = sources.reports.data;
  const reputationData = sources.reputation.data;
  const ceoBackend = sources.ceoStatus.data;
  const ceoJournalData = sources.ceoJournal.data;
  const ceoReviewsData = sources.ceoReviews.data;
  const ceoConstitution = sources.ceoConstitution.data;
  const boardStatus = sources.boardStatus.data;
  const boardHistoryData = sources.boardHistory.data;
  const boardConstitution = sources.boardConstitution.data;
  const memoryStatus = sources.memoryStatus.data;
  const memoryKnowledgeData = sources.memoryKnowledge.data;
  const memoryEventsData = sources.memoryEvents.data;
  const memoryConstitution = sources.memoryConstitution.data;
  const memorySummary = firstObject(memoryStatus.summary);
  const memoryKnowledge = firstArray(memoryKnowledgeData.items, memoryStatus.latestKnowledge);
  const memoryEvents = firstArray(memoryEventsData.items);
  const scientistStatus = sources.scientistStatus.data;
  const scientistHypothesesData = sources.scientistHypotheses.data;
  const scientistExperimentsData = sources.scientistExperiments.data;
  const scientistEventsData = sources.scientistEvents.data;
  const scientistConstitution = sources.scientistConstitution.data;
  const scientistSummary = firstObject(scientistStatus.summary);
  const scientistHypotheses = firstArray(scientistHypothesesData.items, scientistStatus.topHypotheses);
  const scientistExperiments = firstArray(scientistExperimentsData.items, scientistStatus.topExperiments);
  const scientistEvents = firstArray(scientistEventsData.items);
  const operationsStatus = sources.operationsStatus.data;
  const operationsComponentsData = sources.operationsComponents.data;
  const operationsAlertsData = sources.operationsAlerts.data;
  const operationsHistoryData = sources.operationsHistory.data;
  const operationsConstitution = sources.operationsConstitution.data;
  const operationsDependencies = Array.isArray(sources.operationsDependencies.data?.items) ? sources.operationsDependencies.data.items : [];
  const operationsWatchdogs = Array.isArray(sources.operationsWatchdogs.data?.items) ? sources.operationsWatchdogs.data.items : [];
  const operationsQueues = sources.operationsQueues.data?.queues || {};
  const operationsDoctor = sources.operationsDoctor.data || {};
  const operationsEngineHealth = sources.operationsEngineHealth.data || {};
  const operationsComponents = firstArray(
    operationsComponentsData.items,
    operationsComponentsData.components,
    operationsStatus.components,
    operationsStatus.items,
    operationsEngineHealth.components,
  );
  const derivedPassed = operationsComponents.filter((row) => text(row.status, "").toUpperCase() === "PASS").length;
  const derivedWarnings = operationsComponents.filter((row) => text(row.status, "").toUpperCase() === "WARN").length;
  const derivedFailed = operationsComponents.filter((row) => ["FAIL", "CRITICAL"].includes(text(row.status, "").toUpperCase())).length;
  const derivedHealthScore = operationsComponents.length
    ? Math.round(((derivedPassed + (derivedWarnings * 0.5)) / operationsComponents.length) * 100)
    : 0;
  const operationsSummary = firstObject(
    operationsStatus.summary,
    operationsStatus.operationsSummary,
    operationsStatus.latestAudit?.summary,
    operationsStatus.latestAudit,
    operationsEngineHealth.operationsSummary,
    operationsDoctor.operationsSummary,
    {
      overallStatus: derivedFailed ? "CRITICAL" : derivedWarnings ? "WARNING" : operationsComponents.length ? "HEALTHY" : "STARTING",
      healthScore: derivedHealthScore,
      passed: derivedPassed,
      warnings: derivedWarnings,
      failed: derivedFailed,
      componentCount: operationsComponents.length,
      nextAuditInSeconds: 900,
    },
  );
  const holidayMode = firstObject(
    operationsDoctor.holidayMode,
    operationsStatus.holidayMode,
    operationsEngineHealth.holidayMode,
    {
      headline: derivedFailed ? "ATTENTION REQUIRED" : derivedWarnings ? "MONITORING WARNINGS" : operationsComponents.length ? "SYSTEM HEALTHY" : "WAITING FOR FIRST AUDIT",
      healthScore: num(operationsSummary.healthScore, derivedHealthScore),
      safeToLeaveRunning: derivedFailed === 0,
      criticalFailures: derivedFailed,
      warnings: derivedWarnings,
      automaticRecovery: "MONITORING",
    },
  );
  const operationsAlerts = firstArray(operationsAlertsData.items);
  const operationsHistory = firstArray(operationsHistoryData.items);
  const operatorCurrent = firstObject(operator.current);
  const operatorProposal = firstObject(operator.lastProposal);
  const operatorChanged = firstObject(operatorProposal.changed);
  const operatorReasons = Array.isArray(operatorProposal.reasons) ? operatorProposal.reasons.map((item) => text(item, "")).filter(Boolean) : [];
  const operatorStableRuns = num(operator.stableRuns);
  const operatorRequiredRuns = Math.max(1, num(operator.requiredStableRuns, 5));
  const operatorProgress = clamp((operatorStableRuns / operatorRequiredRuns) * 100);
  const operatorEligible = operatorProposal.eligible === true;
  const operatorChangeCount = Object.keys(operatorChanged).length;
  const operatorStatus = operatorChangeCount === 0
    ? "NO CHANGE NEEDED"
    : !operatorEligible
      ? "EVIDENCE NOT ELIGIBLE"
      : operatorStableRuns >= operatorRequiredRuns
        ? "READY FOR CLOSED-MARKET APPLY"
        : "COLLECTING STABLE EVIDENCE";
  const operatorLastRun = operator.lastRunAt ? new Date(String(operator.lastRunAt)).toLocaleString("en-GB") : "Not run yet";
  const operatorHistory = firstArray(operator.history);
  const evolutionActions = [...operatorHistory].reverse().map((row, index) => {
    const before = firstObject(row.before);
    const after = firstObject(row.after);
    const proposal = firstObject(row.proposal);
    const changed = firstObject(proposal.changed);
    const derivedChanged = Object.keys(changed).length ? changed : Object.fromEntries(
      Object.keys(after).filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key])).map((key) => [key, { before: before[key], after: after[key] }])
    );
    return {
      ...row,
      id: row.id,
      generation: index + 1,
      before,
      after,
      proposal,
      changed: derivedChanged,
      equity: num(row.account_equity ?? row.accountEquity),
      samples: num(row.evidence_samples ?? row.evidenceSamples),
      createdAt: text(row.created_at ?? row.createdAt, ""),
      actionType: text(row.action_type ?? row.actionType, "UNKNOWN"),
      status: text(row.status, "UNKNOWN"),
      reason: text(row.reason ?? row.note, "No reason recorded."),
    };
  });
  const promotionActions = evolutionActions.filter((row) => row.actionType.includes("PROMOTION"));
  const currentGeneration = Math.max(1, promotionActions.length + 1);
  const evolutionChartRows = evolutionActions.filter((row) => row.equity > 0).map((row) => ({
    name: `G${row.generation}`,
    equity: row.equity,
    samples: row.samples,
    action: keyLabel(row.actionType),
  }));
  const evolutionLessons = Array.from(new Set([
    ...operatorReasons,
    ...evolutionActions.slice(-8).flatMap((row) => String(row.reason || "").split(";").map((item) => item.trim()).filter(Boolean)),
  ])).slice(0, 10);
  const promotionLatest = firstObject(promotion.latest);
  const promotionCandidate = firstObject(promotionLatest.candidate, promotionLatest.payload?.candidate);
  const promotionOptimizer = firstObject(promotionLatest.optimizer, promotionLatest.payload?.optimizer);

  const learningProgress = pct(advisor.evidence?.richEvidenceProgressPct ?? advisor.learning?.richEvidenceProgressPct ?? 0);
  const shadowAccuracy = pct(shadow.accuracy ?? shadow.winRate ?? shadow.summary?.winRate ?? shadow.metrics?.winRate);
  const calibration = pct(advisor.confidenceCalibration ?? decision.confidenceCalibration ?? decision.calibration?.score ?? strategy.confidenceCalibration);
  const evidenceCount = num(advisor.evidence?.completedOutcomes ?? advisor.evidence?.observations ?? decision.total ?? shadow.summary?.samples ?? 0);
  const discoveryCount = num((advisor.evidence?.validatedPositive ?? 0)) + num((advisor.evidence?.validatedNegative ?? 0));
  const recommendation = firstObject(advisor.recommendation, advisor.latestRecommendation, strategy.recommendation, strategy.latestRecommendation);
  const recommendationMessage = text(advisor.message, "The advisor is still collecting evidence.");

  const symbolRows = firstArray(symbols.symbols, symbols.rows, symbols.rankings, symbols.summary, symbols.topSymbols, symbols.data);
  const ruleRows = firstArray(rules.rules, rules.rows, rules.rankings, rules.summary, rules.data);
  const weaknessRows = firstArray(weakness.issues, weakness.weaknesses, weakness.rows, weakness.findings, weakness.data);
  const strategyRows = firstArray(strategy.strategies, strategy.rows, strategy.rankings, strategy.summary, strategy.data);
  const patternRows = firstArray(patterns.bestPatterns, patterns.rows, patterns.discoveries, patterns.data, research.patterns, research.discoveries,
    ...(Object.values(patterns.patterns || {}).filter(Array.isArray) as AnyObj[][]));
  const researchRows = firstArray(research.leaderboard, research.brains, research.rows, research.insights, v7Status.brains, v8Status.brains);

  const chartSymbolRows = symbolRows.slice(0, 12).map((row) => ({
    name: text(row.symbol ?? row.name ?? row.key, "?"),
    expectancy: num(row.averageReturnPct ?? row.expectancyPct ?? row.expectancy ?? row.edgePct ?? row.edge),
    winRate: pct(row.winRate ?? row.accuracy ?? row.successRate),
    samples: num(row.trades ?? row.samples ?? row.observations),
  }));

  const confidenceRows = firstArray(decision.confidenceBuckets, decision.calibration?.buckets, strategy.confidenceBuckets, advisor.confidenceBuckets).map((row) => ({
    name: text(row.bucket ?? row.range ?? row.label, "?"),
    expected: pct(row.expected ?? row.confidence ?? row.predicted),
    actual: pct(row.actual ?? row.winRate ?? row.realised),
    samples: num(row.samples ?? row.trades ?? row.count),
  }));

  const marketRows = firstArray(marketDna.regimes, marketDna.marketRegimes, marketDna.rows, weekly.regimes, weekly.marketRegimes).map((row) => ({
    name: text(row.regime ?? row.name ?? row.label, "Unknown"),
    expectancy: num(row.expectancyPct ?? row.expectancy ?? row.edgePct ?? row.edge),
    winRate: pct(row.winRate ?? row.accuracy),
    samples: num(row.samples ?? row.trades ?? row.count),
  }));

  const monitoredSourceEntries = Object.entries(sources).filter(([key]) => key !== "operationsEngineHealth");
  const endpointHealth = monitoredSourceEntries.filter(([, source]) => !source.error && !source.loading).length;
  const endpointTotal = monitoredSourceEntries.length;
  const frontendOfflineEngines = monitoredSourceEntries
    .filter(([, source]) => Boolean(source.error) || source.loading)
    .map(([key, source]) => ({
      name: keyLabel(key),
      category: "Dashboard endpoint",
      status: source.loading ? "STARTING" : "FAIL",
      reason: source.loading ? "Waiting for endpoint response." : source.error,
      source: "FRONTEND",
    }));
  const intelligenceHealth = Math.round(((botHealth / 100) * 0.45 + (endpointHealth / Math.max(1, endpointTotal)) * 0.55) * 100);
  const backendEngineRows = firstArray(
    operationsEngineHealth.offline,
    operationsEngineHealth.failed,
    operationsEngineHealth.engines,
    operationsEngineHealth.items,
  );
  const backendOfflineEngines = backendEngineRows
    .filter((row) => {
      const status = text(row.status, row.online === false ? "FAIL" : "PASS").toUpperCase();
      return row.online === false || !["PASS", "ONLINE", "HEALTHY", "OK"].includes(status);
    })
    .map((row) => ({
      ...row,
      name: text(row.name ?? row.endpoint ?? row.key, "Unnamed backend engine"),
      category: text(row.category ?? row.area, "Backend component"),
      status: text(row.status, row.online === false ? "FAIL" : "WARN").toUpperCase(),
      critical: row.critical === true,
      source: "BACKEND",
      reason: text(row.reason ?? row.message ?? row.error, "No diagnostic reason returned."),
    }));
  const exactOfflineEngines = [...frontendOfflineEngines, ...backendOfflineEngines].filter((row, index, rows) =>
    rows.findIndex((candidate) => `${candidate.source}:${candidate.name}` === `${row.source}:${row.name}`) === index
  );


  const account = firstObject(liveStatus.account, liveStatus.data?.account);
  const reportSummary = firstObject(reportsData.summary, reportsData);
  const backendAccount = firstObject(ceoBackend.account);
  const backendPerformance = firstObject(ceoBackend.performance);
  const backendHealth = firstObject(ceoBackend.health);
  const backendLearning = firstObject(ceoBackend.learning);
  const backendEvolution = firstObject(ceoBackend.evolution);
  const backendSymbols = firstObject(ceoBackend.symbols);
  const ceoEquity = num(backendAccount.equity ?? account.equity);
  const ceoDayPnl = num(backendAccount.todayRealisedPnl ?? account.pnlDay ?? account.dayPnl ?? reportSummary.todayPnl ?? reportSummary.dailyPnl);
  const ceoTotalPnl = num(backendAccount.totalRealisedPnl ?? reportSummary.totalGainLoss ?? reportSummary.totalPnl ?? reportSummary.netPnl);
  const ceoTradesToday = num(backendPerformance.closedTrades ?? reportSummary.todayTrades ?? reportSummary.tradesToday ?? advisor.today?.trades);
  const ceoHealthScore = num(ceoBackend.grade, Math.round(clamp((intelligenceHealth * 0.35) + (calibration * 0.25) + (shadowAccuracy * 0.15) + (learningProgress * 0.1) + (botHealth * 0.15))));
  const ceoRiskLevel = text(ceoBackend.riskLevel, ceoDayPnl < -Math.max(10, ceoEquity * 0.015) ? "HIGH" : ceoDayPnl < 0 ? "MODERATE" : "LOW");
  const ceoStatus = text(ceoBackend.operatingStatus, ceoRiskLevel === "HIGH" ? "PROTECTING CAPITAL" : text(operator.mode, "OFF") === "AUTO" ? "AUTONOMOUS TRADING ACTIVE" : "SUPERVISED TRADING");
  const bestResearch = [...researchRows].sort((a, b) => num(b.expectancyPct ?? b.expectancy) - num(a.expectancyPct ?? a.expectancy))[0] || {};
  const bestSymbol = firstObject(backendSymbols.strongest, [...symbolRows].sort((a, b) => num(b.averageReturnPct ?? b.expectancyPct ?? b.expectancy) - num(a.averageReturnPct ?? a.expectancyPct ?? a.expectancy))[0]);
  const worstSymbol = firstObject(backendSymbols.weakest, [...symbolRows].sort((a, b) => num(a.averageReturnPct ?? a.expectancyPct ?? a.expectancy) - num(b.averageReturnPct ?? b.expectancyPct ?? b.expectancy))[0]);
  const hurtingRules = ruleRows.filter((row) => String(row.rating ?? row.verdict ?? row.status ?? "").toUpperCase().includes("HURT"));
  const blockedSymbols = firstArray(reputationData.blockedSymbols, reputationData.blocked, reputationData.cooldowns);
  const ceoRecommendation = text(ceoBackend.recommendation, recommendationMessage);
  const ceoPriorities = Array.isArray(ceoBackend.priorities) && ceoBackend.priorities.length
    ? ceoBackend.priorities.map(String).slice(0, 5)
    : [
      hurtingRules.length ? `Repair ${text(hurtingRules[0]?.rule ?? hurtingRules[0]?.name, "the weakest rule")}` : "Maintain rule stability",
      num(worstSymbol.averageReturnPct ?? worstSymbol.expectancyPct ?? worstSymbol.expectancy) < 0 ? `Avoid weak ${text(worstSymbol.symbol ?? worstSymbol.name, "symbol")} setups` : "Expand symbol evidence",
      calibration < 80 ? "Improve confidence calibration" : "Protect calibrated confidence",
      operatorStableRuns < operatorRequiredRuns ? `Validate next generation (${operatorStableRuns}/${operatorRequiredRuns})` : "Prepare next closed-market promotion",
    ];
  const rawCeoJournal = firstArray(ceoJournalData.items, ceoBackend.journal);
  const ceoJournal = rawCeoJournal.length ? rawCeoJournal.map((entry) => ({
    time: entry.created_at ? new Date(String(entry.created_at)).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "medium" }) : text(entry.day, "Recorded"),
    title: text(entry.title, keyLabel(text(entry.category, "CEO event"))),
    detail: text(entry.detail, "No detail recorded."),
    severity: text(entry.severity, "INFO"),
  })) : [
    { time: operatorLastRun, title: "Autonomous review", detail: operatorStatus, severity: "INFO" },
    { time: "Live", title: "Trading state", detail: `${ceoStatus}; daily P&L ${ceoDayPnl >= 0 ? "+" : ""}$${ceoDayPnl.toFixed(2)}`, severity: "INFO" },
  ];
  const ceoReviewRows = firstArray(ceoReviewsData.items);
  const ceoManualActionRequired = ceoBackend.manualActionRequired === true;
  const ceoGradeLetter = text(ceoBackend.gradeLetter, "—");
  const ceoCreatedAt = ceoBackend.createdAt ? new Date(String(ceoBackend.createdAt)).toLocaleString("en-GB") : "Not generated yet";

  const refreshAll = async () => {
    await Promise.all([load(), fetchData(true)]);
  };

  const promotionPost = async (endpoint: string, body: AnyObj) => {
    if (!authToken) return;
    setPromotionBusy(true);
    setPromotionMessage("");
    try {
      const response = await fetch(`${API_URL}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Auth-Token": authToken, "x-api-key": authToken },
        body: JSON.stringify(body),
      });
      const json = await readJson(response);
      if (!response.ok || json?.ok === false) throw new Error(json?.detail || json?.message || `${response.status}`);
      setPromotionMessage(text(json?.message, "Promotion workflow updated."));
      await refreshAll();
    } catch (error: any) {
      setPromotionMessage(error?.message || "Promotion action failed.");
    } finally {
      setPromotionBusy(false);
    }
  };

  const evaluatePromotion = () => promotionPost("/v10/promotion/evaluate", { horizonHours: 24, minimumSamples: 100 });
  const approvePromotion = () => {
    const key = text(promotionLatest.candidate_key ?? promotionLatest.candidateKey, "");
    if (!key) return setPromotionMessage("No promotion candidate is available.");
    const confirmation = window.prompt("Type PROMOTE to apply this staged strategy change.", "");
    if (confirmation !== null) promotionPost("/v10/promotion/approve", { candidateKey: key, confirmation });
  };
  const rejectPromotion = () => {
    const key = text(promotionLatest.candidate_key ?? promotionLatest.candidateKey, "");
    if (!key) return setPromotionMessage("No promotion candidate is available.");
    if (window.confirm("Reject this promotion candidate?")) promotionPost("/v10/promotion/reject", { candidateKey: key, note: "Rejected from Intelligence dashboard" });
  };
  const rollbackPromotion = () => {
    const confirmation = window.prompt("Type ROLLBACK to restore the previous promoted thresholds.", "");
    if (confirmation !== null) promotionPost("/v10/promotion/rollback", { confirmation });
  };
  const runOperator = () => promotionPost("/v10/operator/run", { force: true });
  const setOperatorMode = (mode: "OFF" | "SHADOW" | "AUTO") => promotionPost("/v10/operator/mode", { mode });
  const rollbackOperator = () => {
    const confirmation = window.prompt("Type ROLLBACK to restore the previous autonomous configuration.", "");
    if (confirmation !== null) promotionPost("/v10/operator/rollback", { confirmation });
  };

  return <div className="intelligence-page">
    <Card wide className="intelligence-hero">
      <div className="intelligence-hero-head">
        <div>
          <p className="eyebrow">TRADEBOT INTELLIGENCE CORE</p>
          <h2>Everything the bot knows, in one place</h2>
          <p className="muted">Live evidence from the advisor, decision memory, Market DNA, shadow trading and research engines.</p>
        </div>
        <div className="actions">
          <span className={`pill ${endpointHealth === endpointTotal ? "ok" : endpointHealth ? "warn" : "bad"}`}>{endpointHealth}/{endpointTotal} engines online</span>
          <button className="ghost" disabled={refreshing} onClick={refreshAll}>{refreshing ? "REFRESHING..." : "REFRESH INTELLIGENCE"}</button>
        </div>
      </div>
      <div className="intelligence-stat-grid">
        <StatTile label="Intelligence Health" value={`${intelligenceHealth}%`} sub={lastUpdated ? `Updated ${lastUpdated}` : "Connecting"} />
        <StatTile label="Market Regime" value={text(advisor.marketRegime ?? marketDna.currentRegime ?? weekly.currentRegime ?? marketRegime)} />
        <StatTile label="Evidence Collected" value={evidenceCount.toLocaleString("en-GB")} sub={`${discoveryCount.toLocaleString("en-GB")} discoveries`} />
        <StatTile label="Decision Confidence" value={`${Math.round(aiConfidence)}%`} />
      </div>
    </Card>

    <nav className="intelligence-tabs">
      {(["ceo", "board", "brain", "market", "research", "symbols", "rules", "evolution", "memory", "scientist", "operations"] as IntelligenceSection[]).map((item) => <button key={item} className={section === item ? "active" : ""} onClick={() => setSection(item)}>{item === "ceo" ? "AI CEO" : item === "board" ? "AI BOARD" : item === "brain" ? "AI BRAIN" : item === "memory" ? "AI MEMORY" : item === "scientist" ? "AI SCIENTIST" : item === "operations" ? "AI OPERATIONS" : item.toUpperCase()}</button>)}
    </nav>


    {section === "ceo" && <div className="grid two ceo-view">
      <Card title="AI Chief Executive" wide className="ceo-command-card">
        <div className="ceo-command-head">
          <div>
            <p className="eyebrow">V12 EXECUTIVE CONTROL ROOM</p>
            <h3>{ceoStatus}</h3>
            <p className="muted">{ceoBackend.ok ? `Live V12 CEO review generated ${ceoCreatedAt}.` : "Waiting for the V12 CEO backend."}</p>
          </div>
          <div className={`ceo-grade ${ceoHealthScore >= 80 ? "good" : ceoHealthScore >= 60 ? "medium" : "poor"}`}>
            <strong>{(ceoHealthScore / 10).toFixed(1)}</strong><span>/ 10</span><small>{ceoGradeLetter} CEO Grade</small>
          </div>
        </div>
        <div className="intelligence-stat-grid ceo-stat-grid">
          <StatTile label="Account Equity" value={`$${ceoEquity.toFixed(2)}`} sub={`Total realised ${ceoTotalPnl >= 0 ? "+" : ""}$${ceoTotalPnl.toFixed(2)}`} tone={ceoTotalPnl >= 0 ? "positive" : "negative"} />
          <StatTile label="Today Realised" value={`${ceoDayPnl >= 0 ? "+" : ""}$${ceoDayPnl.toFixed(2)}`} sub={`${ceoTradesToday} closed trades`} tone={ceoDayPnl >= 0 ? "positive" : "negative"} />
          <StatTile label="Risk" value={ceoRiskLevel} sub={`Market: ${text(ceoBackend.market?.status ?? ceoBackend.market?.session ?? marketRegime)}`} tone={ceoRiskLevel === "HIGH" ? "negative" : ceoRiskLevel === "LOW" ? "positive" : ""} />
          <StatTile label="Evolution" value={`${num(backendEvolution.stableRuns, operatorStableRuns)} / ${num(backendEvolution.requiredStableRuns, operatorRequiredRuns)}`} sub={text(backendEvolution.mode, operatorStatus)} />
        </div>
        <div className="operator-actions">
          <span className="pill ok">AUTOMATIC REVIEWS ACTIVE</span>
          <span className={`pill ${ceoBackend.advisoryOnly === false ? "bad" : "ok"}`}>{ceoBackend.advisoryOnly === false ? "LIVE CONTROL" : "ADVISORY ONLY"}</span>
        </div>
        {promotionMessage && <p className="muted">{promotionMessage}</p>}
      </Card>

      <Card title="CEO Decision" className="ceo-decision-card">
        <span className={`pill ${ceoManualActionRequired ? "bad" : "ok"}`}>{ceoManualActionRequired ? "ACTION REQUIRED" : "NO MANUAL ACTION REQUIRED"}</span>
        <h3>{ceoRecommendation}</h3>
        <div className="summary">
          <div><span>Autonomy</span><b>{text(backendEvolution.mode, operator.mode)}</b></div>
          <div><span>Calibration</span><b>{Math.round(pct(backendLearning.confidenceCalibration ?? calibration))}%</b></div>
          <div><span>Completed outcomes</span><b>{num(backendLearning.completedOutcomes, evidenceCount).toLocaleString("en-GB")}</b></div>
          <div><span>Ready outcomes</span><b>{num(backendLearning.readyOutcomes).toLocaleString("en-GB")}</b></div>
        </div>
      </Card>

      <Card title="Executive Priorities">
        <div className="ceo-priorities">{ceoPriorities.map((priority, index) => <div key={`${priority}-${index}`}><span>{index + 1}</span><p>{priority}</p></div>)}</div>
      </Card>

      <Card title="Company Health" wide>
        <div className="ceo-health-grid">
          <Meter label="Trading" value={num(backendHealth.trading, botHealth)} />
          <Meter label="Learning" value={num(backendHealth.learning, learningProgress)} />
          <Meter label="Research" value={num(backendHealth.research, intelligenceHealth)} />
          <Meter label="Stability" value={num(backendHealth.stability, 100)} />
          <Meter label="Autonomy" value={num(backendHealth.autonomy, 0)} />
        </div>
      </Card>

      <Card title="Research & Symbol Supervision">
        <div className="ceo-facts">
          <div><span>Best research brain</span><b>{text(bestResearch.name ?? bestResearch.brainName, "Learning")}</b><small>{num(bestResearch.expectancyPct ?? bestResearch.expectancy).toFixed(2)}% expectancy</small></div>
          <div><span>Strongest symbol</span><b>{text(bestSymbol.symbol ?? bestSymbol.name, "Learning")}</b><small>Reputation score {num(bestSymbol.score).toFixed(1)}</small></div>
          <div><span>Weakest symbol</span><b>{text(worstSymbol.symbol ?? worstSymbol.name, "Learning")}</b><small>Reputation score {num(worstSymbol.score).toFixed(1)}</small></div>
          <div><span>Mature symbols monitored</span><b>{num(backendSymbols.count)}</b><small>{blockedSymbols.length} currently blocked / cooling</small></div>
        </div>
      </Card>

      <Card title="CEO Review History">
        <DataTable rows={ceoReviewRows.slice(0, 10)} columns={[
          { key: "created_at", label: "Date", render: (row) => row.created_at ? new Date(String(row.created_at)).toLocaleString("en-GB") : "—" },
          { key: "review_type", label: "Type" },
          { key: "grade_letter", label: "Grade", render: (row) => `${text(row.grade_letter, "—")} (${num(row.grade).toFixed(1)})` },
          { key: "risk_level", label: "Risk" },
        ]} />
      </Card>

      <Card title="CEO Constitution">
        <span className={`pill ${ceoConstitution.advisoryOnly === false ? "bad" : "ok"}`}>{ceoConstitution.advisoryOnly === false ? "LIVE CONTROL" : "ADVISORY ONLY"}</span>
        <div className="ceo-priorities">{(Array.isArray(ceoConstitution.principles) ? ceoConstitution.principles : []).map((principle: string, index: number) => <div key={principle}><span>{index + 1}</span><p>{principle}</p></div>)}</div>
      </Card>

      <Card title="CEO Journal" wide>
        <div className="ceo-journal">{ceoJournal.map((entry, index) => <article key={`${entry.title}-${index}`}><time>{entry.time}</time><div><b>{entry.title}</b><p>{entry.detail}</p></div></article>)}</div>
      </Card>
    </div>}


    {section === "board" && <div className="grid two ceo-view">
      <Card title="AI Board of Directors" wide className="ceo-command-card">
        <div className="ceo-command-head">
          <div>
            <p className="eyebrow">V12.1 AUTOMATIC GOVERNANCE</p>
            <h3>{text(boardStatus.finalDecision, "WAITING FOR FIRST MEETING")}</h3>
            <p className="muted">{text(boardStatus.finalReason, "The board will meet automatically after the backend starts.")}</p>
          </div>
          <div className={`ceo-grade ${boardStatus.finalDecision === "VETO" ? "poor" : boardStatus.finalDecision === "DELAY" ? "medium" : "good"}`}>
            <strong>{Math.round(pct(boardStatus.confidence))}</strong><span>%</span><small>Board confidence</small>
          </div>
        </div>
        <div className="intelligence-stat-grid ceo-stat-grid">
          <StatTile label="Approvals" value={String(num(boardStatus.consensus?.approve))} sub={`${num(boardStatus.consensus?.total)} directors`} />
          <StatTile label="Wait / Caution" value={String(num(boardStatus.consensus?.wait) + num(boardStatus.consensus?.caution))} sub="More evidence required" />
          <StatTile label="Vetoes" value={String(num(boardStatus.consensus?.veto))} tone={num(boardStatus.consensus?.veto) > 0 ? "negative" : "positive"} />
          <StatTile label="CEO Grade" value={`${text(boardStatus.ceoGradeLetter, "—")} ${num(boardStatus.ceoGrade).toFixed(1)}`} sub={`Risk: ${text(boardStatus.riskLevel, "—")}`} />
        </div>
        <div className="operator-actions">
          <span className="pill ok">AUTOMATIC MEETINGS ACTIVE</span>
          <span className="pill ok">ADVISORY ONLY</span>
        </div>
      </Card>

      <Card title="Board Next Action" className="ceo-decision-card">
        <span className={`pill ${boardStatus.finalDecision === "VETO" ? "bad" : boardStatus.finalDecision === "DELAY" ? "warn" : "ok"}`}>{text(boardStatus.finalDecision, "PENDING")}</span>
        <h3>{text(boardStatus.nextAction, "Waiting for the first automatic board review.")}</h3>
        <p className="muted">Meeting type: {text(boardStatus.meetingType, "—")} · {boardStatus.createdAt ? new Date(String(boardStatus.createdAt)).toLocaleString("en-GB") : "—"}</p>
      </Card>

      <Card title="Director Votes" wide>
        <DataTable rows={firstArray(boardStatus.votes)} columns={[
          { key: "director", label: "Director" },
          { key: "vote", label: "Vote", render: (row) => <span className={`pill ${row.vote === "VETO" ? "bad" : row.vote === "APPROVE" ? "ok" : "warn"}`}>{text(row.vote, "WAIT")}</span> },
          { key: "confidence", label: "Confidence", render: (row) => `${Math.round(pct(row.confidence))}%` },
          { key: "reason", label: "Evidence-backed reason" },
        ]} />
      </Card>

      <Card title="Board Meeting History" wide>
        <DataTable rows={firstArray(boardHistoryData.items).slice(0, 15)} columns={[
          { key: "created_at", label: "Date", render: (row) => row.created_at ? new Date(String(row.created_at)).toLocaleString("en-GB") : "—" },
          { key: "meeting_type", label: "Meeting" },
          { key: "final_decision", label: "Decision" },
          { key: "ceo_grade", label: "CEO Grade", render: (row) => num(row.ceo_grade).toFixed(1) },
          { key: "risk_level", label: "Risk" },
        ]} />
      </Card>

      <Card title="Board Constitution" wide>
        <div className="operator-actions"><span className="pill ok">AUTOMATIC</span><span className="pill ok">NO MANUAL REVIEW</span></div>
        <div className="ceo-priorities">{(Array.isArray(boardConstitution.rules) ? boardConstitution.rules : []).map((rule: string, index: number) => <div key={rule}><span>{index + 1}</span><p>{rule}</p></div>)}</div>
      </Card>
    </div>}

    {section === "brain" && <div className="grid two">
      <Card title="AI Readiness">
        <Meter label="Learning progress" value={learningProgress} />
        <Meter label="Shadow accuracy" value={shadowAccuracy} />
        <Meter label="Confidence calibration" value={calibration} />
        <Meter label="Engine availability" value={(endpointHealth / endpointTotal) * 100} />
      </Card>
      <Card title="Latest Recommendation" className="recommendation-card">
        <strong className="recommendation-title">{text(recommendation.title ?? recommendation.action ?? recommendation.recommendation ?? advisor.message, "No new recommendation")}</strong>
        <p>{text(recommendation.reason ?? recommendation.summary ?? recommendation.explanation ?? advisor.note, "The AI remains advisory-only and has not produced a new evidence-backed recommendation.")}</p>
        <div className="summary">
          <div><span>Confidence</span><b>{Math.round(pct(recommendation.confidence ?? recommendation.score ?? advisor.confidence))}%</b></div>
          <div><span>Live changes</span><b>{advisor.automaticLiveChanges === true ? "Enabled" : "Human approval required"}</b></div>
          <div><span>Current regime</span><b>{text(advisor.marketRegime ?? marketRegime)}</b></div>
        </div>
      </Card>
      <Card title="Autonomous AI Operator" wide className="recommendation-card operator-card">
        <div className="operator-headline">
          <div>
            <span className={`pill ${text(operator.mode, "SHADOW") === "AUTO" ? "ok" : "warn"}`}>{text(operator.mode, "SHADOW")}</span>
            <h3>{operatorStatus}</h3>
            <p className="muted">{operatorChangeCount
              ? `${operatorChangeCount} bounded setting${operatorChangeCount === 1 ? "" : "s"} currently under review.`
              : "The current live configuration remains the best eligible configuration."}</p>
          </div>
          <div className="operator-window">
            <span>Apply window</span>
            <b>Market closed only</b>
            <small>Last review: {operatorLastRun}</small>
          </div>
        </div>

        <div className="operator-progress-block">
          <div className="operator-progress-label"><span>Stable evidence</span><b>{operatorStableRuns} / {operatorRequiredRuns}</b></div>
          <div className="operator-progress-track"><span style={{ width: `${operatorProgress}%` }} /></div>
          <small>{operatorStableRuns >= operatorRequiredRuns
            ? "Stability requirement met. An eligible proposal may apply while the market is closed, subject to cooldown and constitution checks."
            : `${operatorRequiredRuns - operatorStableRuns} matching review${operatorRequiredRuns - operatorStableRuns === 1 ? "" : "s"} still required.`}</small>
        </div>

        {operatorChangeCount > 0 ? <div className="operator-change-grid">
          {Object.entries(operatorChanged).map(([key, raw]) => {
            const change = firstObject(raw);
            return <div className="operator-change" key={key}>
              <span>{keyLabel(key)}</span>
              <div><b>{formatOperatorValue(key, change.before)}</b><strong>→</strong><b>{formatOperatorValue(key, change.after)}</b></div>
            </div>;
          })}
        </div> : <div className="operator-no-change">No parameter change is currently proposed.</div>}

        <div className="operator-evidence-grid">
          <div><span>Evidence samples</span><b>{num(operatorProposal.evidenceSamples).toLocaleString("en-GB")}</b></div>
          <div><span>Eligible</span><b>{operatorEligible ? "YES" : "NO"}</b></div>
          <div><span>Automatic changes</span><b>{text(operator.mode, "SHADOW") === "AUTO" ? "ENABLED" : "DISABLED"}</b></div>
          <div><span>Rollback protection</span><b>ACTIVE</b></div>
        </div>

        {operatorReasons.length > 0 && <div className="operator-reasons">
          <h4>Why the AI is proposing this</h4>
          {operatorReasons.map((reason, index) => <p key={`${reason}-${index}`}>✓ {reason}</p>)}
        </div>}

        <details className="operator-current">
          <summary>View current live settings</summary>
          <div className="summary">
            <div><span>Max positions</span><b>{num(operatorCurrent.maxPositions)}</b></div>
            <div><span>Trading cap</span><b>${num(operatorCurrent.tradingCapUsd).toFixed(2)}</b></div>
            <div><span>Position size</span><b>{pct(operatorCurrent.targetPositionValuePct).toFixed(0)}%</b></div>
            <div><span>Stop loss</span><b>{num(operatorCurrent.stopLossPct).toFixed(2)}%</b></div>
            <div><span>Trail start</span><b>{num(operatorCurrent.trailStartPct).toFixed(2)}%</b></div>
            <div><span>Trail giveback</span><b>{num(operatorCurrent.trailGivebackPct).toFixed(2)}%</b></div>
            <div><span>Excluded symbols</span><b>{Array.isArray(operatorCurrent.symbolExclusions) ? operatorCurrent.symbolExclusions.length : 0}</b></div>
            <div><span>Order execution</span><b>{text(operatorCurrent.orderExecution, "MARKET")}</b></div>
          </div>
        </details>

        <div className="actions admin-section">
          <button onClick={() => setOperatorMode("AUTO")} disabled={promotionBusy}>ENABLE AUTO</button>
          <button className="ghost" onClick={() => setOperatorMode("SHADOW")} disabled={promotionBusy}>SHADOW ONLY</button>
          <button className="ghost" onClick={() => setOperatorMode("OFF")} disabled={promotionBusy}>TURN OFF</button>
          <button onClick={runOperator} disabled={promotionBusy}>{promotionBusy ? "WORKING..." : "RUN REVIEW NOW"}</button>
          <button className="danger" onClick={rollbackOperator} disabled={promotionBusy || !operator.history?.length}>ROLL BACK</button>
        </div>
        <p className="muted">AUTO requires no recurring approval. It only applies constitution-bounded settings while the market is closed, after the same eligible proposal remains stable for all required reviews. Automatic rollback remains active.</p>
        {promotionMessage && <p><b>{promotionMessage}</b></p>}
      </Card>

      <Card title="Human-Gated Strategy Promotion" wide className="recommendation-card">
        <div className="summary">
          <div><span>Status</span><b>{text(promotionLatest.status ?? promotionOptimizer.recommendation, "No candidate evaluated")}</b></div>
          <div><span>Current confidence gate</span><b>{num(promotion.current?.confidence).toFixed(2)}</b></div>
          <div><span>Proposed confidence gate</span><b>{Object.keys(promotionCandidate).length ? num(promotionCandidate.confidence).toFixed(2) : "—"}</b></div>
          <div><span>Current quality gate</span><b>{num(promotion.current?.quality).toFixed(3)}</b></div>
          <div><span>Proposed quality gate</span><b>{Object.keys(promotionCandidate).length ? num(promotionCandidate.quality).toFixed(3) : "—"}</b></div>
          <div><span>Samples</span><b>{num(promotionCandidate.samples).toLocaleString("en-GB")}</b></div>
          <div><span>Candidate expectancy</span><b>{num(promotionCandidate.expectancyPct).toFixed(2)}%</b></div>
          <div><span>Profit factor</span><b>{num(promotionCandidate.profitFactor).toFixed(2)}</b></div>
          <div><span>Stability</span><b>{num(promotionLatest.matching_runs ?? promotionOptimizer.stability?.matchingRuns)} / {num(promotionLatest.required_runs ?? promotionOptimizer.stability?.requiredRuns)}</b></div>
          <div><span>Automatic live changes</span><b>No — approval required</b></div>
        </div>
        <div className="actions admin-section">
          <button onClick={evaluatePromotion} disabled={promotionBusy}>{promotionBusy ? "WORKING..." : "EVALUATE CANDIDATE"}</button>
          <button onClick={approvePromotion} disabled={promotionBusy || text(promotionLatest.status, "") !== "READY_FOR_APPROVAL"}>APPROVE & APPLY</button>
          <button className="ghost" onClick={rejectPromotion} disabled={promotionBusy || !Object.keys(promotionLatest).length}>REJECT</button>
          <button className="danger" onClick={rollbackPromotion} disabled={promotionBusy || !promotion.rollbackAvailable}>ROLL BACK LAST CHANGE</button>
        </div>
        <p className="muted">The bot never applies a candidate automatically. Approval re-runs the evidence checks, requires the same stable candidate, then changes only the staged A+ confidence and quality thresholds. Rollback restores the previous thresholds.</p>
        {promotionMessage && <p><b>{promotionMessage}</b></p>}
      </Card>
      <Card title="When this intelligence updates" wide>
        <div className="summary">
          <div><span>Outcome evaluation</span><b>After market close</b></div>
          <div><span>Default outcome horizon</span><b>24 hours</b></div>
          <div><span>Research check interval</span><b>Every 30 minutes while closed</b></div>
          <div><span>First reliable learning run</span><b>20 completed outcomes</b></div>
          <div><span>Rich evidence target</span><b>{num(advisor.evidence?.richEvidenceTarget || 100)}</b></div>
          <div><span>Completed / pending</span><b>{num(advisor.evidence?.completedOutcomes)} / {num(advisor.evidence?.pendingOutcomes)}</b></div>
        </div>
        <p className="muted">The live market worker deliberately pauses the research learner during market hours. Today’s decisions normally become eligible after their 24-hour checkpoint and are processed during a closed-market research cycle.</p>
      </Card>
      <Card title="Confidence Calibration" wide>
        {confidenceRows.length ? <div className="chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={confidenceRows}><CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.16)" /><XAxis dataKey="name" stroke="#94a3b8" /><YAxis domain={[0, 100]} stroke="#94a3b8" /><Tooltip contentStyle={{ background: "#020617", border: "1px solid #263450", borderRadius: 12 }} /><Line type="monotone" dataKey="expected" stroke="#38bdf8" strokeWidth={3} name="Expected %" /><Line type="monotone" dataKey="actual" stroke="#22c55e" strokeWidth={3} name="Actual %" /></LineChart></ResponsiveContainer></div> : <EmptyState endpoint="decision confidence buckets" error={sources.decision.error} />}
      </Card>
      <Card title="Strategy Intelligence" wide>
        <DataTable rows={strategyRows.slice(0, 12)} columns={[
          { key: "name", label: "Strategy", render: (row) => <b>{text(row.name ?? row.strategy ?? row.key)}</b> },
          { key: "trades", label: "Samples", render: (row) => num(row.trades ?? row.samples ?? row.observations).toLocaleString("en-GB") },
          { key: "winRate", label: "Win Rate", render: (row) => `${Math.round(pct(row.winRate ?? row.accuracy))}%` },
          { key: "expectancy", label: "Expectancy", render: (row) => `${num(row.averageReturnPct ?? row.expectancyPct ?? row.expectancy ?? row.edgePct).toFixed(2)}%` },
          { key: "status", label: "Status", render: (row) => <span className="pill">{text(row.status ?? row.verdict ?? row.readiness, "Learning")}</span> },
        ]} />
      </Card>
    </div>}

    {section === "market" && <div className="grid two">
      <Card title="Current Market DNA">
        <div className="summary">
          {Object.entries(firstObject(marketDna.current, marketDna.snapshot, marketDna.market, marketDna.dna)).slice(0, 10).map(([key, value]) => <div key={key}><span>{keyLabel(key)}</span><b>{typeof value === "number" ? value.toFixed(2) : text(value)}</b></div>)}
        </div>
        {!Object.keys(firstObject(marketDna.current, marketDna.snapshot, marketDna.market, marketDna.dna)).length && <EmptyState endpoint="Market DNA" error={sources.marketDna.error} />}
      </Card>
      <Card title="Weekly Intelligence">
        <strong className="recommendation-title">{text(weekly.title ?? weekly.headline ?? weekly.summary?.title, "Weekly evidence summary")}</strong>
        <p>{text(weekly.message ?? weekly.summary ?? weekly.note, sources.weekly.error || "No weekly intelligence narrative has been generated yet.")}</p>
        <pre>{JSON.stringify(firstObject(weekly.recommendation, weekly.outlook, weekly.highlights), null, 2)}</pre>
      </Card>
      <Card title="Regime Performance" wide>
        {marketRows.length ? <div className="chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={marketRows}><CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.16)" /><XAxis dataKey="name" stroke="#94a3b8" /><YAxis stroke="#94a3b8" /><Tooltip contentStyle={{ background: "#020617", border: "1px solid #263450", borderRadius: 12 }} /><Bar dataKey="expectancy" name="Expectancy %">{marketRows.map((row, index) => <Cell key={index} fill={row.expectancy >= 0 ? "#22c55e" : "#fb7185"} />)}</Bar></BarChart></ResponsiveContainer></div> : <EmptyState endpoint="Market DNA regime history" error={sources.marketDna.error} />}
      </Card>
      <Card title="Discovered Market Patterns" wide>
        <DataTable rows={patternRows.slice(0, 20)} columns={[
          { key: "pattern", label: "Pattern", render: (row) => <b>{text(row.pattern ?? row.name ?? row.title ?? row.description)}</b> },
          { key: "samples", label: "Samples", render: (row) => text(row.area ?? row.samples ?? row.trades ?? row.count, "—") },
          { key: "winRate", label: "Win Rate", render: (row) => `${Math.round(pct(row.winRate ?? row.accuracy))}%` },
          { key: "expectancy", label: "Expectancy", render: (row) => `${num(row.rejectedTradeAverageReturnPct ?? row.expectancyPct ?? row.expectancy ?? row.edgePct).toFixed(2)}%` },
          { key: "confidence", label: "Confidence", render: (row) => `${Math.round(pct(row.confidence ?? row.score))}%` },
        ]} />
      </Card>
    </div>}

    {section === "research" && <div className="grid two">
      <Card title="Research Lab Status">
        <div className="summary">
          <div><span>Version</span><b>{text(v8Status.version ?? v7Status.version ?? research.version)}</b></div>
          <div><span>Generation</span><b>{text(research.generation ?? v7Status.generation ?? v8Status.generation)}</b></div>
          <div><span>Active brains</span><b>{num(research.activeBrains ?? v7Status.activeBrains ?? researchRows.length)}</b></div>
          <div><span>Research-only</span><b>{research.automaticLiveChanges === true ? "No" : "Yes"}</b></div>
        </div>
      </Card>
      <Card title="Research Champion">
        {(() => { const champion = firstObject(research.champion, research.researchChampion, v7Status.champion, v7Status.researchChampion, v8Status.champion, v8Status.researchChampion); return Object.keys(champion).length ? <><strong className="recommendation-title">{text(champion.name ?? champion.key, "Current champion")}</strong><div className="summary"><div><span>Samples</span><b>{num(champion.trades ?? champion.samples)}</b></div><div><span>Win Rate</span><b>{Math.round(pct(champion.winRate ?? champion.accuracy))}%</b></div><div><span>Expectancy</span><b>{num(champion.expectancyPct ?? champion.expectancy).toFixed(2)}%</b></div><div><span>Research Score</span><b>{num(champion.researchScore ?? champion.score).toFixed(2)}</b></div></div></> : <EmptyState endpoint="V7 research champion" error={sources.research.error} />; })()}
      </Card>
      <Card title="Research Leaderboard" wide>
        <DataTable rows={researchRows.slice(0, 25)} columns={[
          { key: "name", label: "Brain", render: (row) => <b>{text(row.name ?? row.key ?? row.brainName)}</b> },
          { key: "generation", label: "Generation", render: (row) => text(row.generation ?? row.origin, "—") },
          { key: "trades", label: "Samples", render: (row) => num(row.trades ?? row.samples).toLocaleString("en-GB") },
          { key: "winRate", label: "Win Rate", render: (row) => `${Math.round(pct(row.winRate ?? row.accuracy))}%` },
          { key: "expectancy", label: "Expectancy", render: (row) => `${num(row.expectancyPct ?? row.expectancy).toFixed(2)}%` },
          { key: "score", label: "Score", render: (row) => num(row.researchScore ?? row.score).toFixed(2) },
          { key: "eligible", label: "Eligible", render: (row) => <span className={`pill ${row.eligible || row.recommendationEligible ? "ok" : "warn"}`}>{row.eligible || row.recommendationEligible ? "YES" : "LEARNING"}</span> },
        ]} />
      </Card>
    </div>}

    {section === "symbols" && <div className="grid two">
      <Card title="Symbol Expectancy" wide>
        {chartSymbolRows.length ? <div className="chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={chartSymbolRows}><CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.16)" /><XAxis dataKey="name" stroke="#94a3b8" /><YAxis stroke="#94a3b8" /><Tooltip contentStyle={{ background: "#020617", border: "1px solid #263450", borderRadius: 12 }} /><Bar dataKey="expectancy" name="Expectancy %">{chartSymbolRows.map((row, index) => <Cell key={index} fill={row.expectancy >= 0 ? "#22c55e" : "#fb7185"} />)}</Bar></BarChart></ResponsiveContainer></div> : <EmptyState endpoint="symbol intelligence" error={sources.symbols.error} />}
      </Card>
      <Card title="Symbol DNA Rankings" wide>
        <DataTable rows={symbolRows.slice(0, 30)} columns={[
          { key: "symbol", label: "Symbol", render: (row) => <b className="symbol-badge">{text(row.symbol ?? row.name ?? row.key)}</b> },
          { key: "samples", label: "Samples", render: (row) => num(row.trades ?? row.samples ?? row.observations).toLocaleString("en-GB") },
          { key: "winRate", label: "Win Rate", render: (row) => `${Math.round(pct(row.winRate ?? row.accuracy))}%` },
          { key: "expectancy", label: "Expectancy", render: (row) => `${num(row.averageReturnPct ?? row.expectancyPct ?? row.expectancy ?? row.edgePct).toFixed(2)}%` },
          { key: "bestRegime", label: "Best Regime", render: (row) => text(row.status, "Learning") },
          { key: "confidence", label: "Confidence", render: (row) => `${Math.round(num(row.samples) ? Math.min(99, Math.sqrt(num(row.samples) / 50) * 100) : 0)}%` },
        ]} />
      </Card>
    </div>}


    {section === "memory" && <div className="memory-view">
      <Card title="V13 Long-Term AI Memory">
        <div className="intelligence-hero-head"><div><span className="eyebrow">AUTONOMOUS KNOWLEDGE LAYER</span><h2>{memoryStatus.enabled === false ? "MEMORY DISABLED" : "MEMORY LEARNING ACTIVE"}</h2><p>Evidence-backed knowledge shared with the CEO, Board, Research and Evolution engines.</p></div><div className="score-ring"><strong>{num(memorySummary.highConfidence)}</strong><span>high-confidence claims</span></div></div>
        <div className="intelligence-stats four"><StatTile label="Active knowledge" value={num(memorySummary.activeKnowledge).toLocaleString("en-GB")} /><StatTile label="High confidence" value={num(memorySummary.highConfidence).toLocaleString("en-GB")} /><StatTile label="Positive claims" value={num(memorySummary.positiveClaims).toLocaleString("en-GB")} tone="positive" /><StatTile label="Negative claims" value={num(memorySummary.negativeClaims).toLocaleString("en-GB")} tone="negative" /></div>
        <div className="status-strip"><span>AUTOMATIC LEARNING ACTIVE</span><span>ADVISORY ONLY</span><span>STALE KNOWLEDGE AUTO-RETIRES</span></div>
      </Card>
      <Card title="What the AI currently knows">
        <DataTable rows={memoryKnowledge} columns={[
          { key: "knowledgeType", label: "Type", render: (row) => <span className="pill">{text(row.knowledgeType, "UNKNOWN")}</span> },
          { key: "subject", label: "Subject" },
          { key: "claim", label: "Evidence-backed knowledge" },
          { key: "confidence", label: "Confidence", render: (row) => `${num(row.confidence).toFixed(0)}%` },
          { key: "evidenceCount", label: "Evidence", render: (row) => num(row.evidenceCount).toLocaleString("en-GB") },
          { key: "status", label: "Status" },
        ]} />
      </Card>
      <div className="grid two">
        <Card title="Memory activity">{memoryEvents.length ? <div className="journal-list">{memoryEvents.slice(0, 20).map((row, index) => <article key={String(row.id ?? index)}><time>{row.created_at ? new Date(row.created_at).toLocaleString("en-GB") : ""}</time><div><b>{text(row.title, "Memory event")}</b><p>{text(row.detail, "")}</p></div></article>)}</div> : <EmptyState endpoint="V13 memory events" error={sources.memoryEvents.error} />}</Card>
        <Card title="Memory Constitution"><div className="constitution-list">{Array.isArray(memoryConstitution.rules) && memoryConstitution.rules.length ? memoryConstitution.rules.map((rule: unknown, index: number) => <div key={index}><span>{index + 1}</span><p>{text(rule)}</p></div>) : <EmptyState endpoint="V13 memory constitution" error={sources.memoryConstitution.error} />}</div></Card>
      </div>
    </div>}


    {section === "scientist" && <div className="memory-view scientist-view">
      <Card title="V14 Autonomous AI Scientist">
        <div className="intelligence-hero-head"><div><span className="eyebrow">AUTOMATIC RESEARCH ORGANISATION</span><h2>{scientistStatus.enabled === false ? "SCIENTIST DISABLED" : "SCIENTIST ACTIVE"}</h2><p>Generates evidence-backed hypotheses from AI Memory and designs controlled shadow experiments. It cannot alter live trading.</p></div><div className="score-ring"><strong>{num(scientistSummary.hypotheses)}</strong><span>active hypotheses</span></div></div>
        <div className="intelligence-stats four"><StatTile label="Hypotheses" value={num(scientistSummary.hypotheses).toLocaleString("en-GB")} /><StatTile label="Experiments" value={num(scientistSummary.experiments).toLocaleString("en-GB")} /><StatTile label="Shadow ready" value={num(scientistSummary.shadowReady).toLocaleString("en-GB")} /><StatTile label="Board eligible" value={num(scientistSummary.boardEligible).toLocaleString("en-GB")} tone={num(scientistSummary.boardEligible) ? "positive" : ""} /></div>
        <div className="status-strip"><span>AUTOMATIC HYPOTHESIS GENERATION</span><span>RESEARCH ONLY</span><span>NO MANUAL REVIEW REQUIRED</span></div>
        <p className="muted">{text(scientistStatus.nextAction, "Collecting evidence for the next research cycle.")}</p>
      </Card>
      <Card title="Current Scientific Hypotheses">
        <DataTable rows={scientistHypotheses} columns={[
          { key: "title", label: "Hypothesis", render: (row) => <b>{text(row.title)}</b> },
          { key: "hypothesisType", label: "Type", render: (row) => <span className="pill">{text(row.hypothesisType)}</span> },
          { key: "subject", label: "Subject" },
          { key: "statement", label: "Testable statement" },
          { key: "confidence", label: "Prior confidence", render: (row) => `${num(row.confidence).toFixed(0)}%` },
          { key: "evidenceCount", label: "Source evidence", render: (row) => num(row.evidenceCount).toLocaleString("en-GB") },
          { key: "status", label: "Status" },
        ]} />
      </Card>
      <Card title="Experiment Pipeline">
        <DataTable rows={scientistExperiments} columns={[
          { key: "name", label: "Experiment", render: (row) => <b>{text(row.name)}</b> },
          { key: "experimentType", label: "Design", render: (row) => <span className="pill">{text(row.experimentType)}</span> },
          { key: "status", label: "Status" },
          { key: "sampleSize", label: "Tagged samples", render: (row) => num(row.sampleSize).toLocaleString("en-GB") },
          { key: "winRate", label: "Win rate", render: (row) => row.winRate === null || row.winRate === undefined ? "—" : `${num(row.winRate).toFixed(0)}%` },
          { key: "expectancyPct", label: "Expectancy", render: (row) => row.expectancyPct === null || row.expectancyPct === undefined ? "—" : `${num(row.expectancyPct).toFixed(2)}%` },
          { key: "evaluationScore", label: "Research score", render: (row) => num(row.evaluationScore).toFixed(2) },
          { key: "boardEligible", label: "Board", render: (row) => <span className={`pill ${row.boardEligible ? "ok" : "warn"}`}>{row.boardEligible ? "ELIGIBLE" : "NOT YET"}</span> },
        ]} />
      </Card>
      <div className="grid two">
        <Card title="Scientist activity">{scientistEvents.length ? <div className="journal-list">{scientistEvents.slice(0, 20).map((row, index) => <article key={String(row.id ?? index)}><time>{row.created_at ? new Date(row.created_at).toLocaleString("en-GB") : ""}</time><div><b>{text(row.title, "Scientist event")}</b><p>{text(row.detail, "")}</p></div></article>)}</div> : <EmptyState endpoint="V14 scientist events" error={sources.scientistEvents.error} />}</Card>
        <Card title="Scientist Constitution"><div className="constitution-list">{Array.isArray(scientistConstitution.rules) && scientistConstitution.rules.length ? scientistConstitution.rules.map((rule: unknown, index: number) => <div key={index}><span>{index + 1}</span><p>{text(rule)}</p></div>) : <EmptyState endpoint="V14 scientist constitution" error={sources.scientistConstitution.error} />}</div></Card>
      </div>
    </div>}


    {section === "operations" && <div className="memory-view operations-view">
      <Card title="V15.1 AI Operations Centre Pro">
        <div className="intelligence-hero-head"><div><span className="eyebrow">AUTOMATIC FULL-SYSTEM MONITORING</span><h2>{text(operationsSummary.overallStatus, "STARTING")}</h2><p>Continuously checks the full dependency tree, registered APIs, database integrity, queues, workers, intelligence, governance and host resources.</p></div><div className="score-ring"><strong>{num(operationsSummary.healthScore).toFixed(0)}%</strong><span>system health</span></div></div>
        <div className="intelligence-stats four"><StatTile label="Passed" value={num(operationsSummary.passed).toLocaleString("en-GB")} tone="positive" /><StatTile label="Warnings" value={num(operationsSummary.warnings).toLocaleString("en-GB")} /><StatTile label="Failed" value={num(operationsSummary.failed).toLocaleString("en-GB")} tone={num(operationsSummary.failed) ? "negative" : ""} /><StatTile label="Active alerts" value={operationsAlerts.length.toLocaleString("en-GB")} tone={operationsAlerts.length ? "negative" : "positive"} /></div>
        <div className="status-strip"><span>AUTOMATIC AUDITS ACTIVE</span><span>EVERY {Math.max(1, Math.round(num(operationsSummary.nextAuditInSeconds, 900) / 60))} MINUTES</span><span>ENDPOINT DISCOVERY</span><span>WORKER WATCHDOG</span><span>NO MANUAL REVIEW</span></div>
        <p className="muted">Last audit: {operationsSummary.checkedAt ? new Date(String(operationsSummary.checkedAt)).toLocaleString("en-GB") : "Waiting for first automatic audit"}. {text(operationsStatus.nextAction, "No intervention required.")}</p>
      </Card>
      <Card title="Holiday Mode">
        <div className="intelligence-hero-head"><div><span className="eyebrow">AUTOMATIC HOLIDAY SUPERVISION</span><h2>{text(holidayMode.headline, "WAITING FOR FIRST AUDIT")}</h2><p>{holidayMode.safeToLeaveRunning === false ? "A critical condition needs human attention." : "The system is monitoring itself and will keep warnings visible until they clear."}</p></div><div className="score-ring"><strong>{num(holidayMode.healthScore).toFixed(0)}%</strong><span>holiday health</span></div></div>
        <div className="status-strip"><span>{holidayMode.safeToLeaveRunning === false ? "ATTENTION REQUIRED" : "SAFE TO LEAVE RUNNING"}</span><span>RECOVERY: {text(holidayMode.automaticRecovery, "MONITORING")}</span><span>CRITICAL: {num(holidayMode.criticalFailures)}</span><span>WARNINGS: {num(holidayMode.warnings)}</span></div>
      </Card>
      <Card title="Exact Engine Health">
        <div className="intelligence-hero-head"><div><span className="eyebrow">FAULT-ISOLATED DIAGNOSTICS</span><h2>{exactOfflineEngines.length ? `${exactOfflineEngines.length} ITEMS NEED ATTENTION` : "ALL MONITORED ENGINES HEALTHY"}</h2><p>The dashboard now identifies each unavailable endpoint or failed internal component instead of showing only a total.</p></div><div className="score-ring"><strong>{endpointHealth}/{endpointTotal}</strong><span>dashboard endpoints online</span></div></div>
        {exactOfflineEngines.length ? <DataTable rows={exactOfflineEngines} columns={[
          { key: "status", label: "Health", render: (row) => <span className={`pill ${row.status === "WARN" || row.status === "STARTING" ? "warn" : "bad"}`}>{text(row.status)}</span> },
          { key: "source", label: "Detected by", render: (row) => <span className="pill">{text(row.source)}</span> },
          { key: "category", label: "Area" },
          { key: "name", label: "Engine / endpoint", render: (row) => <b>{text(row.name)}</b> },
          { key: "reason", label: "Exact reason" },
          { key: "critical", label: "Critical", render: (row) => row.critical ? "YES" : "NO" },
        ]} /> : <div className="intelligence-empty"><strong>All clear</strong><span>Every monitored dashboard endpoint and backend Operations component is currently healthy.</span></div>}
      </Card>
      <Card title="Dependency Health">
        <DataTable rows={operationsDependencies} columns={[
          { key: "status", label: "Health", render: (row) => <span className={`pill ${row.status === "PASS" ? "ok" : "warn"}`}>{text(row.status)}</span> },
          { key: "name", label: "Department", render: (row) => <b>{text(row.name)}</b> },
          { key: "healthy", label: "Healthy", render: (row) => `${num(row.healthy)} / ${num(row.total)}` },
          { key: "components", label: "Dependencies", render: (row) => Array.isArray(row.components) ? row.components.map((x: any) => `${text(x.name)}: ${text(x.status)}`).join(" · ") : "—" },
        ]} />
      </Card>
      <div className="grid two">
        <Card title="Worker Watchdogs"><DataTable rows={operationsWatchdogs} columns={[
          { key: "status", label: "Health", render: (row) => <span className={`pill ${row.status === "PASS" ? "ok" : "warn"}`}>{text(row.status)}</span> },
          { key: "name", label: "Watchdog" }, { key: "message", label: "Latest result" },
          { key: "durationMs", label: "Check", render: (row) => `${num(row.durationMs).toFixed(0)} ms` },
        ]} /></Card>
        <Card title="Queue & Audit Stores"><div className="summary">{Object.entries(operationsQueues).length ? Object.entries(operationsQueues).map(([key,value]: any) => <div key={key}><span>{keyLabel(key)}</span><b>{typeof value === "object" ? text(value.total ?? value.status ?? value.table, "AVAILABLE") : num(value).toLocaleString("en-GB")}</b></div>) : <div><span>Status</span><b>Waiting for audit</b></div>}</div></Card>
      </div>
      <Card title="Subsystem Health">
        <DataTable rows={operationsComponents} columns={[
          { key: "status", label: "Health", render: (row) => <span className={`pill ${row.status === "PASS" ? "ok" : "warn"}`}>{text(row.status)}</span> },
          { key: "category", label: "Area" },
          { key: "name", label: "Subsystem", render: (row) => <b>{text(row.name)}</b> },
          { key: "message", label: "Latest check" },
          { key: "durationMs", label: "Response", render: (row) => `${num(row.durationMs).toFixed(0)} ms` },
          { key: "critical", label: "Critical", render: (row) => row.critical ? "YES" : "NO" },
        ]} />
      </Card>
      <div className="grid two">
        <Card title="Active Operations Alerts">{operationsAlerts.length ? <div className="journal-list">{operationsAlerts.slice(0, 30).map((row, index) => <article key={String(row.id ?? index)}><time>{row.last_seen ? new Date(String(row.last_seen)).toLocaleString("en-GB") : ""}</time><div><b>{text(row.severity)} · {text(row.title)}</b><p>{text(row.detail, "")}</p></div></article>)}</div> : <div className="intelligence-empty"><strong>All clear</strong><span>No active system alerts.</span></div>}</Card>
        <Card title="Health History"><DataTable rows={operationsHistory.slice(0, 30)} columns={[
          { key: "created_at", label: "Audit", render: (row) => row.created_at ? new Date(String(row.created_at)).toLocaleString("en-GB") : "—" },
          { key: "overallStatus", label: "Status" },
          { key: "healthScore", label: "Health", render: (row) => `${num(row.healthScore).toFixed(0)}%` },
          { key: "passed", label: "Pass" }, { key: "warnings", label: "Warn" }, { key: "failed", label: "Fail" },
        ]} /></Card>
      </div>
      <Card title="Operations Constitution"><div className="constitution-list">{Array.isArray(operationsConstitution.rules) && operationsConstitution.rules.length ? operationsConstitution.rules.map((rule: unknown, index: number) => <div key={index}><span>{index + 1}</span><p>{text(rule)}</p></div>) : <EmptyState endpoint="V15 operations constitution" error={sources.operationsConstitution.error} />}</div></Card>
    </div>}

    {section === "evolution" && <div className="grid two evolution-view">
      <Card title="Current Evolution State">
        <div className="evolution-current">
          <span className="pill ok">GENERATION {currentGeneration}</span>
          <strong>{text(operator.mode, "OFF") === "AUTO" ? "AUTONOMOUS EVOLUTION ACTIVE" : `${text(operator.mode, "OFF")} MODE`}</strong>
          <p className="muted">The next generation is created only when a stable, constitution-bounded proposal is applied while the market is closed.</p>
        </div>
        <div className="summary">
          <div><span>Promotions recorded</span><b>{promotionActions.length}</b></div>
          <div><span>Rollbacks recorded</span><b>{evolutionActions.filter((row) => row.actionType.includes("ROLLBACK")).length}</b></div>
          <div><span>Current stability</span><b>{operatorStableRuns} / {operatorRequiredRuns}</b></div>
          <div><span>Last applied</span><b>{operator.lastApplyAt ? new Date(String(operator.lastApplyAt)).toLocaleString("en-GB") : "No promotion yet"}</b></div>
          <div><span>Rollback protection</span><b>{operator.history?.length ? "ACTIVE" : "ARMED"}</b></div>
        </div>
      </Card>

      <Card title="Next Candidate">
        <div className="operator-progress-block">
          <div className="operator-progress-label"><b>{operatorStatus}</b><b>{operatorStableRuns} / {operatorRequiredRuns}</b></div>
          <div className="operator-progress-track"><span style={{ width: `${operatorProgress}%` }} /></div>
          <small>{operatorChangeCount ? `${Math.max(0, operatorRequiredRuns - operatorStableRuns)} matching reviews remain.` : "No evidence-backed change is currently required."}</small>
        </div>
        {operatorChangeCount ? <div className="evolution-candidate-list">{Object.entries(operatorChanged).map(([key, change]) => { const item = firstObject(change); return <div key={key}><span>{keyLabel(key)}</span><b>{formatOperatorValue(key, item.before)} → {formatOperatorValue(key, item.after)}</b></div>; })}</div> : <EmptyState endpoint="autonomous candidate" />}
        <p className="muted">Evidence: {num(operatorProposal.evidenceSamples).toLocaleString("en-GB")} completed observations. Apply window: market closed only.</p>
      </Card>

      <Card title="Evolution Equity Checkpoints" wide>
        {evolutionChartRows.length ? <div className="chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={evolutionChartRows}><CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.16)" /><XAxis dataKey="name" stroke="#94a3b8" /><YAxis stroke="#94a3b8" /><Tooltip contentStyle={{ background: "#020617", border: "1px solid #263450", borderRadius: 12 }} formatter={(value: any) => `$${num(value).toFixed(2)}`} /><Line type="monotone" dataKey="equity" stroke="#38bdf8" strokeWidth={3} name="Account equity at action" /></LineChart></ResponsiveContainer></div> : <EmptyState endpoint="operator promotion history" />}
        <p className="muted">This chart shows account equity captured when each operator action was recorded. It is an audit checkpoint, not proof that a parameter change caused the subsequent result.</p>
      </Card>

      <Card title="What the AI has learned" wide>
        {evolutionLessons.length ? <div className="evolution-lessons">{evolutionLessons.map((lesson, index) => <div key={`${lesson}-${index}`}><span>✓</span><p>{lesson}</p></div>)}</div> : <EmptyState endpoint="operator learning reasons" />}
      </Card>

      <Card title="Evolution Timeline" wide>
        {evolutionActions.length ? <div className="evolution-timeline">{[...evolutionActions].reverse().map((row) => <article key={String(row.id ?? `${row.createdAt}-${row.generation}`)} className={`evolution-entry ${row.actionType.includes("ROLLBACK") ? "rollback" : "promotion"}`}>
          <div className="evolution-node" />
          <div className="evolution-entry-head"><div><span className="pill">G{row.generation}</span><b>{keyLabel(row.actionType)}</b></div><time>{row.createdAt ? new Date(row.createdAt).toLocaleString("en-GB") : "Unknown time"}</time></div>
          <p>{row.reason}</p>
          <div className="evolution-meta"><span>Evidence <b>{row.samples.toLocaleString("en-GB")}</b></span><span>Status <b>{row.status}</b></span>{row.equity > 0 && <span>Equity <b>${row.equity.toFixed(2)}</b></span>}</div>
          {Object.keys(row.changed).length > 0 && <div className="evolution-change-list">{Object.entries(row.changed).map(([key, value]) => { const change = firstObject(value); return <div key={key}><span>{keyLabel(key)}</span><b>{formatOperatorValue(key, change.before)} → {formatOperatorValue(key, change.after)}</b></div>; })}</div>}
        </article>)}</div> : <EmptyState endpoint="autonomous promotion history" />}
      </Card>
    </div>}

    {section === "rules" && <div className="grid two">
      <Card title="Rule Intelligence" wide>
        <DataTable rows={ruleRows.slice(0, 30)} columns={[
          { key: "rule", label: "Rule", render: (row) => <b>{text(row.rule ?? row.name ?? row.key)}</b> },
          { key: "triggered", label: "Triggered", render: (row) => num(row.triggered ?? row.samples ?? row.count).toLocaleString("en-GB") },
          { key: "helped", label: "Helped", render: (row) => `${Math.round(pct(row.helpedRate ?? row.helpRate ?? row.successRate ?? row.winRate))}%` },
          { key: "expectancy", label: "Expectancy", render: (row) => `${num(row.rejectedTradeAverageReturnPct ?? row.expectancyPct ?? row.expectancy ?? row.edgePct).toFixed(2)}%` },
          { key: "verdict", label: "Verdict", render: (row) => <span className="pill">{text(row.rating ?? row.verdict ?? row.status ?? row.recommendation, "Learning")}</span> },
        ]} />
      </Card>
      <Card title="Weakness Intelligence" wide>
        <DataTable rows={weaknessRows.slice(0, 30)} columns={[
          { key: "weakness", label: "Weakness", render: (row) => <b>{text(row.finding ?? row.weakness ?? row.name ?? row.title ?? row.rule)}</b> },
          { key: "severity", label: "Severity", render: (row) => text(row.severity ?? row.risk ?? row.level, "Unknown") },
          { key: "samples", label: "Evidence", render: (row) => num(row.samples ?? row.trades ?? row.count).toLocaleString("en-GB") },
          { key: "impact", label: "Impact", render: (row) => text(row.severity ?? row.impactPct ?? row.expectancyPct ?? row.impact, "—") },
          { key: "recommendation", label: "Recommendation", render: (row) => text(row.recommendation ?? row.action ?? row.note, "Observe") },
        ]} />
      </Card>
    </div>}
  </div>;
}
