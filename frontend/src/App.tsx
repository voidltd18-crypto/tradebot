import React, { useEffect, useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceDot,
} from "recharts";

const API_URL = "https://tradebot-0myo.onrender.com";

type Trade = {
  time: string;
  side: "BUY" | "SELL";
  symbol: string;
  amount?: number;
  qty?: number;
  pnl?: number;
  pnlPct?: number;
  reason?: string;
};

type Position = {
  symbol: string;
  qty: number;
  entry: number;
  price: number;
  marketValue: number;
  pnl: number;
  pnlPct: number;
  trailStartPrice: number;
  trailFloor: number;
  trailingActive: boolean;
  custom?: boolean;
  lockedToday?: boolean;
  boughtToday?: boolean;
  minutesSinceBuy?: number;
};

type Scan = {
  symbol: string;
  price: number;
  trigger: number;
  spread: number;
  pullback?: number;
  shortMomentum?: number;
  qualityScore?: number;
  readyToBuy?: boolean;
  lockedToday?: boolean;
  confidence?: number;
  confidenceLabel?: string;
  sniperPass?: boolean;
  sniperReason?: string;
  aPlusPass?: boolean;
  aPlusReason?: string;
  priceCurve?: { t: string; value: number }[];
};

const panel: React.CSSProperties = {
  background: "#0f172a",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 18,
  padding: 16,
};

const btn = (color: string): React.CSSProperties => ({
  padding: "10px 14px",
  borderRadius: 999,
  background: color,
  color: "white",
  border: "none",
  cursor: "pointer",
  fontWeight: 700,
  margin: 4,
});

function money(n: number) {
  return `$${Number(n || 0).toFixed(2)}`;
}

function pct(n: number) {
  return `${Number(n || 0).toFixed(2)}%`;
}

function daysAgo(days: number) {
  return Date.now() - days * 24 * 60 * 60 * 1000;
}

function timelineFilterMs(filter: string) {
  if (filter === "day") return daysAgo(1);
  if (filter === "week") return daysAgo(7);
  if (filter === "month") return daysAgo(30);
  return 0;
}

export default function App() {
  const [data, setData] = useState<any>(null);
  const [status, setStatus] = useState("Connecting...");
  const [message, setMessage] = useState("");
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("dashboard_api_key") || "");
  const [customTicker, setCustomTicker] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [timelineRange, setTimelineRange] = useState("day");

  const fetchData = async () => {
    try {
      const res = await fetch(`${API_URL}/status`);
      const json = await res.json();
      setData(json);
      setStatus("Connected");
      if (!selectedSymbol && json.scans?.length) setSelectedSymbol(json.scans[0].symbol);
    } catch {
      setStatus("Connection failed");
    }
  };

  useEffect(() => {
    fetchData();
    const i = setInterval(fetchData, 5000);
    return () => clearInterval(i);
  }, []);

  const saveApiKey = () => {
    localStorage.setItem("dashboard_api_key", apiKey);
    setMessage("Dashboard key saved on this device");
  };

  const clearApiKey = () => {
    localStorage.removeItem("dashboard_api_key");
    setApiKey("");
    setMessage("Dashboard key cleared");
  };

  const action = async (endpoint: string) => {
    if (!apiKey.trim()) {
      setMessage("Enter your dashboard password first");
      return;
    }

    try {
      const res = await fetch(`${API_URL}${endpoint}`, {
        method: "POST",
        headers: { "x-api-key": apiKey.trim() },
      });
      const json = await res.json();

      if (!res.ok) {
        setMessage(json.detail || json.message || "Action blocked");
        return;
      }

      setMessage(json.message || "Action sent");
      fetchData();
    } catch {
      setMessage("Action failed");
    }
  };

  const customBuy = async () => {
    const symbol = customTicker.trim().toUpperCase();
    if (!symbol) return setMessage("Enter a ticker first");
    if (!confirm(`Custom buy ${symbol}?`)) return;
    await action(`/custom-buy/${symbol}`);
    setCustomTicker("");
  };

  const selectedScan: Scan | undefined = useMemo(
    () => data?.scans?.find((s: Scan) => s.symbol === selectedSymbol),
    [data, selectedSymbol]
  );

  const timeline = useMemo(() => {
    const start = timelineFilterMs(timelineRange);
    return (data?.tradeTimeline || [])
      .filter((e: any) => !start || new Date(e.timestamp).getTime() >= start)
      .map((e: any, i: number) => ({ ...e, idx: i }));
  }, [data, timelineRange]);

  const timelineChart = useMemo(() => {
    return timeline.map((e: any, i: number) => ({
      idx: i,
      equity: e.equity || 0,
      symbol: e.symbol,
      side: e.side,
      time: e.time,
      reason: e.reason,
      pnl: e.pnl,
      pnlPct: e.pnlPct,
    }));
  }, [timeline]);

  return (
    <div style={{ minHeight: "100vh", background: "#020617", color: "white", padding: 14, fontFamily: "Arial" }}>
      <div style={{ maxWidth: 1350, margin: "0 auto" }}>
        <h1 style={{ textAlign: "center", fontSize: "clamp(28px, 6vw, 48px)" }}>
          🎯 Rebuilt Sniper Profit Bot
        </h1>

        <div style={{ textAlign: "center", color: status === "Connected" ? "#22c55e" : "#f87171", fontWeight: 700 }}>
          {status}
        </div>

        {data && (
          <div style={{ textAlign: "center", color: "#94a3b8", marginBottom: 12 }}>
            {data.name} · {data.paperMode ? "PAPER" : "LIVE"} · Bot {data.botEnabled ? "ON" : "OFF"} · Market{" "}
            {data.market?.label || "UNKNOWN"} · {data.mode}
          </div>
        )}

        <div style={{ ...panel, marginBottom: 12, borderColor: "rgba(56,189,248,0.45)" }}>
          <h3>Security</h3>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Dashboard password"
            style={{ padding: 11, borderRadius: 12, background: "#020617", color: "white", border: "1px solid rgba(255,255,255,0.18)", minWidth: 220 }}
          />
          <button style={btn("#2563eb")} onClick={saveApiKey}>Save Key</button>
          <button style={btn("#4b5563")} onClick={clearApiKey}>Clear</button>
          {message && <span style={{ color: "#facc15", marginLeft: 8 }}>{message}</span>}
        </div>

        {data && (
          <div style={{ ...panel, marginBottom: 12, borderColor: "rgba(34,197,94,0.45)" }}>
            <h3>Strategy Modes</h3>
            <p style={{ color: "#22c55e", fontWeight: 700 }}>
              Sniper {data.sniperModeEnabled ? "ON" : "OFF"} · A+ Gate {data.aPlusGateEnabled ? "ON" : "OFF"} · Confidence Sizing {data.confidenceSizingEnabled ? "ON" : "OFF"} · Stock Memory {data.stockMemoryEnabled ? "ON" : "OFF"} · PDT-Aware {data.pdtAwareModeEnabled ? "ON" : "OFF"}
            </p>
            <p style={{ color: "#94a3b8" }}>
              A+ Gate only allows the highest quality trades. Sniper decides IF to buy. Confidence decides HOW MUCH. Memory learns which stocks work best.
            </p>
          </div>
        )}

        {data && (
          <div style={{ ...panel, marginBottom: 12, borderColor: "rgba(250,204,21,0.45)" }}>
            <h3>A+ Trade Quality Gate</h3>
            <p style={{ color: "#facc15", fontWeight: 700 }}>
              {data.aPlusGateEnabled ? "ACTIVE" : "OFF"} · Minimum confidence {data.aPlusMinConfidence} · Minimum quality {data.aPlusMinQuality}
            </p>
            <p style={{ color: "#94a3b8" }}>
              Money Buy is blocked unless an A+ candidate is available. Temporary blacklist: {Object.keys(data.tempBlacklist || {}).length} stocks.
            </p>
          </div>
        )}

        <div style={{ ...panel, marginBottom: 12 }}>
          <h3>Controls</h3>
          <button style={btn("#2563eb")} onClick={fetchData}>Refresh</button>
          <button style={btn("#16a34a")} onClick={() => action("/manual-buy")}>Money Buy</button>
          <button style={btn("#dc2626")} onClick={() => action("/manual-sell")}>Sell Worst</button>
          <button style={btn("#7f1d1d")} onClick={() => action("/emergency-sell")}>EMERGENCY SELL ALL</button>
          <button style={btn("#9333ea")} onClick={() => action("/pause")}>Pause</button>
          <button style={btn("#0891b2")} onClick={() => action("/resume")}>Resume</button>
          <button style={btn("#f59e0b")} onClick={() => action("/manual-override/on")}>Override ON</button>
          <button style={btn("#4b5563")} onClick={() => action("/manual-override/off")}>Override OFF</button>

          <div style={{ marginTop: 12 }}>
            <input
              value={customTicker}
              onChange={(e) => setCustomTicker(e.target.value.toUpperCase())}
              placeholder="Ticker e.g. AMD"
              style={{ padding: 11, borderRadius: 12, background: "#020617", color: "white", border: "1px solid rgba(255,255,255,0.18)", minWidth: 160 }}
            />
            <button style={btn("#22c55e")} onClick={customBuy}>Buy Custom</button>
          </div>
        </div>

        {!data && <p>Loading...</p>}

        {data && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 12 }}>
              <div style={panel}>Equity<br /><b>{money(data.account.equity)}</b></div>
              <div style={panel}>Buying Power<br /><b>{money(data.account.buyingPower)}</b></div>
              <div style={panel}>Day PnL<br /><b style={{ color: data.account.pnlDay >= 0 ? "#22c55e" : "#f87171" }}>{money(data.account.pnlDay)}</b></div>
              <div style={panel}>Positions<br /><b>{(data.positions || []).length}/{data.maxPositions}</b></div>
              <div style={panel}>Next Buy Size<br /><b>{money(data.newPositionNotional || 0)}</b></div>
              <div style={panel}>Risk<br /><b style={{ color: data.riskBlocked ? "#f87171" : "#22c55e" }}>{data.riskBlocked ? "BLOCKED" : "OK"}</b></div>
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Trade Timeline</h3>
              <div>
                {["day", "week", "month", "total"].map((r) => (
                  <button key={r} style={btn(timelineRange === r ? "#2563eb" : "#334155")} onClick={() => setTimelineRange(r)}>
                    {r.toUpperCase()}
                  </button>
                ))}
              </div>
              <div style={{ height: 320 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={timelineChart}>
                    <CartesianGrid stroke="rgba(255,255,255,0.1)" />
                    <XAxis dataKey="idx" />
                    <YAxis />
                    <Tooltip />
                    <Line type="monotone" dataKey="equity" stroke="#22c55e" strokeWidth={2} dot={false} />
                    {timelineChart.map((e: any) => (
                      <ReferenceDot
                        key={`${e.idx}-${e.symbol}-${e.side}`}
                        x={e.idx}
                        y={e.equity}
                        r={5}
                        fill={e.side === "BUY" ? "#22c55e" : "#ef4444"}
                        stroke="white"
                        label={{ value: e.symbol, position: "top", fill: "white", fontSize: 11 }}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {timeline.length === 0 && <p style={{ color: "#94a3b8" }}>No timeline trades yet.</p>}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>All Positions</h3>
              {(data.positions || []).length === 0 && <p>No open positions.</p>}
              {(data.positions || []).map((p: Position) => (
                <div key={p.symbol} style={{ background: "#020617", borderRadius: 14, padding: 12, marginBottom: 8 }}>
                  <b>{p.symbol}</b>
                  {p.boughtToday ? <span style={{ color: "#facc15" }}> · BOUGHT TODAY · {p.minutesSinceBuy}m held</span> : null}
                  {" · "}Qty {Number(p.qty).toFixed(4)} · Entry {money(p.entry)} · Price {money(p.price)} · Value {money(p.marketValue)}
                  <br />
                  <span style={{ color: p.pnlPct >= 0 ? "#22c55e" : "#f87171" }}>
                    PnL {money(p.pnl)} / {pct(p.pnlPct)}
                  </span>
                  {" · "}
                  <span style={{ color: p.trailingActive ? "#22c55e" : "#facc15" }}>
                    {p.trailingActive ? `Trailing floor ${money(p.trailFloor)}` : `Trail starts ${money(p.trailStartPrice)}`}
                  </span>
                  <button style={btn("#dc2626")} onClick={() => action(`/sell/${p.symbol}`)}>Sell {p.symbol}</button>
                </div>
              ))}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Scanner</h3>
              <select value={selectedSymbol} onChange={(e) => setSelectedSymbol(e.target.value)} style={{ padding: 10, borderRadius: 10, marginBottom: 10 }}>
                {(data.scans || []).map((s: Scan) => <option key={s.symbol} value={s.symbol}>{s.symbol}</option>)}
              </select>

              <div style={{ height: 220, marginBottom: 12 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={selectedScan?.priceCurve || []}>
                    <CartesianGrid stroke="rgba(255,255,255,0.1)" />
                    <XAxis dataKey="t" />
                    <YAxis />
                    <Tooltip />
                    <Line type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {(data.scans || []).map((s: Scan) => (
                <div key={s.symbol} style={{ background: s.sniperPass ? "rgba(22,163,74,0.18)" : "#020617", borderRadius: 14, padding: 12, marginBottom: 8 }}>
                  <b>{s.symbol}</b> | {money(s.price)} | trigger {money(s.trigger)} | spread {(s.spread * 100).toFixed(2)}%
                  <br />
                  quality {(s.qualityScore || 0).toFixed(4)} | confidence {(s.confidence || 0).toFixed(2)} {s.confidenceLabel} | {s.aPlusPass ? "A+ PASS" : `A+ WAIT: ${s.aPlusReason || s.sniperReason}`}
                </div>
              ))}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Stock Memory</h3>
              {(data.stockMemory || []).length === 0 && <p style={{ color: "#94a3b8" }}>No completed sell history yet.</p>}
              {(data.stockMemory || []).slice(0, 20).map((m: any) => (
                <div key={m.symbol} style={{ background: "#020617", borderRadius: 12, padding: 10, marginBottom: 6 }}>
                  <b>{m.symbol}</b> · Trust {m.trust} · Trades {m.trades} · Win rate {pct((m.winRate || 0) * 100)} · Avg PnL {money(m.avgPnl || 0)}
                </div>
              ))}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Alpaca Rejections / PDT Warnings</h3>
              {(data.alpacaRejectionEvents || []).length === 0 && (data.pdtWarningEvents || []).length === 0 && <p style={{ color: "#94a3b8" }}>No warnings yet.</p>}
              {(data.alpacaRejectionEvents || []).map((e: any, i: number) => (
                <div key={`a-${i}`} style={{ color: "#f87171", marginBottom: 6 }}>{e.time} | {e.message} | {e.error}</div>
              ))}
              {(data.pdtWarningEvents || []).map((e: any, i: number) => (
                <div key={`p-${i}`} style={{ color: "#facc15", marginBottom: 6 }}>{e.time} | {e.message}</div>
              ))}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Trades</h3>
              {(data.trades || []).length === 0 && <p>No trades yet</p>}
              {(data.trades || []).map((t: Trade, i: number) => (
                <div key={i} style={{ color: t.side === "BUY" ? "#22c55e" : "#f87171", marginBottom: 6 }}>
                  {t.time} | {t.side} | {t.symbol} {t.amount ? `| ${money(t.amount)}` : ""} {t.qty ? `| ${t.qty} shares` : ""} {t.reason ? `| ${t.reason}` : ""} {t.pnl !== undefined ? `| PnL ${money(t.pnl)} (${pct(t.pnlPct || 0)})` : ""}
                </div>
              ))}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Logs</h3>
              {(data.logs || []).map((l: string, i: number) => (
                <div key={i} style={{ color: l.includes("SNIPER") ? "#38bdf8" : l.includes("PDT") ? "#facc15" : l.includes("PROFIT") ? "#22c55e" : "#94a3b8", fontSize: 12 }}>
                  {l}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
