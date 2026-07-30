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

type IntelligenceSection = "brain" | "market" | "research" | "symbols" | "rules";

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

  const learningProgress = pct(advisor.learningProgress ?? advisor.readiness?.progress ?? advisor.readiness ?? decision.learningProgress ?? decision.readiness);
  const shadowAccuracy = pct(shadow.accuracy ?? shadow.winRate ?? shadow.summary?.winRate ?? shadow.metrics?.winRate);
  const calibration = pct(advisor.confidenceCalibration ?? decision.confidenceCalibration ?? decision.calibration?.score ?? strategy.confidenceCalibration);
  const evidenceCount = num(advisor.observations ?? advisor.evidenceCount ?? decision.totalDecisions ?? decision.observations ?? shadow.total ?? shadow.trades);
  const discoveryCount = num(advisor.discoveries ?? advisor.validatedPatterns ?? patterns.total ?? patterns.count ?? research.patternsFound ?? research.patternCount);
  const recommendation = firstObject(advisor.recommendation, advisor.latestRecommendation, strategy.recommendation, strategy.latestRecommendation);

  const symbolRows = firstArray(symbols.symbols, symbols.rows, symbols.rankings, symbols.summary, symbols.topSymbols, symbols.data);
  const ruleRows = firstArray(rules.rules, rules.rows, rules.rankings, rules.summary, rules.data);
  const weaknessRows = firstArray(weakness.weaknesses, weakness.rows, weakness.findings, weakness.summary, weakness.data);
  const strategyRows = firstArray(strategy.strategies, strategy.rows, strategy.rankings, strategy.summary, strategy.data);
  const patternRows = firstArray(patterns.patterns, patterns.rows, patterns.discoveries, patterns.data, research.patterns, research.discoveries);
  const researchRows = firstArray(research.brains, research.rows, research.leaderboard, research.insights, v7Status.brains, v8Status.brains);

  const chartSymbolRows = symbolRows.slice(0, 12).map((row) => ({
    name: text(row.symbol ?? row.name ?? row.key, "?"),
    expectancy: num(row.expectancyPct ?? row.expectancy ?? row.edgePct ?? row.edge),
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
      {(["brain", "market", "research", "symbols", "rules"] as IntelligenceSection[]).map((item) => <button key={item} className={section === item ? "active" : ""} onClick={() => setSection(item)}>{item === "brain" ? "AI BRAIN" : item.toUpperCase()}</button>)}
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
      <Card title="Confidence Calibration" wide>
        {confidenceRows.length ? <div className="chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={confidenceRows}><CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.16)" /><XAxis dataKey="name" stroke="#94a3b8" /><YAxis domain={[0, 100]} stroke="#94a3b8" /><Tooltip contentStyle={{ background: "#020617", border: "1px solid #263450", borderRadius: 12 }} /><Line type="monotone" dataKey="expected" stroke="#38bdf8" strokeWidth={3} name="Expected %" /><Line type="monotone" dataKey="actual" stroke="#22c55e" strokeWidth={3} name="Actual %" /></LineChart></ResponsiveContainer></div> : <EmptyState endpoint="decision confidence buckets" error={sources.decision.error} />}
      </Card>
      <Card title="Strategy Intelligence" wide>
        <DataTable rows={strategyRows.slice(0, 12)} columns={[
          { key: "name", label: "Strategy", render: (row) => <b>{text(row.name ?? row.strategy ?? row.key)}</b> },
          { key: "trades", label: "Samples", render: (row) => num(row.trades ?? row.samples ?? row.observations).toLocaleString("en-GB") },
          { key: "winRate", label: "Win Rate", render: (row) => `${Math.round(pct(row.winRate ?? row.accuracy))}%` },
          { key: "expectancy", label: "Expectancy", render: (row) => `${num(row.expectancyPct ?? row.expectancy ?? row.edgePct).toFixed(2)}%` },
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
          { key: "samples", label: "Samples", render: (row) => num(row.samples ?? row.trades ?? row.count).toLocaleString("en-GB") },
          { key: "winRate", label: "Win Rate", render: (row) => `${Math.round(pct(row.winRate ?? row.accuracy))}%` },
          { key: "expectancy", label: "Expectancy", render: (row) => `${num(row.expectancyPct ?? row.expectancy ?? row.edgePct).toFixed(2)}%` },
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
          { key: "expectancy", label: "Expectancy", render: (row) => `${num(row.expectancyPct ?? row.expectancy ?? row.edgePct).toFixed(2)}%` },
          { key: "bestRegime", label: "Best Regime", render: (row) => text(row.bestRegime ?? row.regime ?? row.marketRegime, "Learning") },
          { key: "confidence", label: "Confidence", render: (row) => `${Math.round(pct(row.confidence ?? row.reliability ?? row.score))}%` },
        ]} />
      </Card>
    </div>}

    {section === "rules" && <div className="grid two">
      <Card title="Rule Intelligence" wide>
        <DataTable rows={ruleRows.slice(0, 30)} columns={[
          { key: "rule", label: "Rule", render: (row) => <b>{text(row.rule ?? row.name ?? row.key)}</b> },
          { key: "triggered", label: "Triggered", render: (row) => num(row.triggered ?? row.samples ?? row.count).toLocaleString("en-GB") },
          { key: "helped", label: "Helped", render: (row) => `${Math.round(pct(row.helpRate ?? row.successRate ?? row.winRate))}%` },
          { key: "expectancy", label: "Expectancy", render: (row) => `${num(row.expectancyPct ?? row.expectancy ?? row.edgePct).toFixed(2)}%` },
          { key: "verdict", label: "Verdict", render: (row) => <span className="pill">{text(row.verdict ?? row.status ?? row.recommendation, "Learning")}</span> },
        ]} />
      </Card>
      <Card title="Weakness Intelligence" wide>
        <DataTable rows={weaknessRows.slice(0, 30)} columns={[
          { key: "weakness", label: "Weakness", render: (row) => <b>{text(row.weakness ?? row.name ?? row.title ?? row.rule)}</b> },
          { key: "severity", label: "Severity", render: (row) => text(row.severity ?? row.risk ?? row.level, "Unknown") },
          { key: "samples", label: "Evidence", render: (row) => num(row.samples ?? row.trades ?? row.count).toLocaleString("en-GB") },
          { key: "impact", label: "Impact", render: (row) => `${num(row.impactPct ?? row.expectancyPct ?? row.impact).toFixed(2)}%` },
          { key: "recommendation", label: "Recommendation", render: (row) => text(row.recommendation ?? row.action ?? row.note, "Observe") },
        ]} />
      </Card>
    </div>}
  </div>;
}
