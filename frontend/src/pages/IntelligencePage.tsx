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

type IntelligenceSection = "brain" | "market" | "research" | "symbols" | "rules" | "evolution";

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
  const [section, setSection] = useState<IntelligenceSection>("brain");
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
  }), []);

  const load = useCallback(async () => {
    if (!authToken) return;
    setRefreshing(true);
    const headers = { "X-Auth-Token": authToken, "x-api-key": authToken };
    const entries = Object.entries(endpoints);
    const results = await Promise.all(entries.map(async ([key, endpoint]) => {
      try {
        const response = await fetch(`${API_URL}${endpoint}`, { cache: "no-store", headers });
        const json = await readJson(response);
        if (!response.ok || json?.ok === false) throw new Error(json?.detail || json?.message || `${response.status}`);
        return [key, { data: json || {}, error: "", loading: false }] as const;
      } catch (error: any) {
        return [key, { data: {}, error: error?.message || "Endpoint unavailable", loading: false }] as const;
      }
    }));
    setSources(Object.fromEntries(results));
    setLastUpdated(new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    setRefreshing(false);
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

  const endpointHealth = Object.values(sources).filter((source) => !source.error && !source.loading).length;
  const endpointTotal = Object.keys(sources).length;
  const intelligenceHealth = Math.round(((botHealth / 100) * 0.45 + (endpointHealth / endpointTotal) * 0.55) * 100);

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
      {(["brain", "market", "research", "symbols", "rules", "evolution"] as IntelligenceSection[]).map((item) => <button key={item} className={section === item ? "active" : ""} onClick={() => setSection(item)}>{item === "brain" ? "AI BRAIN" : item.toUpperCase()}</button>)}
    </nav>

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
