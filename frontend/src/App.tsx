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
  time?: string;
  side?: "BUY" | "SELL";
  symbol?: string;
  amount?: number;
  amountGbp?: number;
  qty?: number;
  pnl?: number;
  pnlGbp?: number;
  pnlPct?: number;
  reason?: string;
};

type Position = {
  symbol: string;
  qty: number;
  entry: number;
  price: number;
  marketValue: number;
  marketValueGbp?: number;
  pnl: number;
  pnlGbp?: number;
  pnlPct: number;
  trailStartPrice: number;
  trailFloor: number;
  trailingActive: boolean;
  custom?: boolean;
  lockedToday?: boolean;
  boughtToday?: boolean;
  minutesSinceBuy?: number;
  partialProfitTaken?: boolean;
  partialProfitTriggerPct?: number;
  fastStopLossPct?: number;
  stallExitAfterMinutes?: number;
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

function usd(n: number | undefined | null) {
  return `$${Number(n || 0).toFixed(2)}`;
}

function gbpFromUsd(n: number | undefined | null, rate: number) {
  return `£${(Number(n || 0) * Number(rate || 0.78)).toFixed(2)}`;
}

function gbpValue(n: number | undefined | null) {
  return `£${Number(n || 0).toFixed(2)}`;
}

function pct(n: number | undefined | null) {
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

function DualMoney({
  usdValue,
  gbpValue: gbpDirect,
  rate,
}: {
  usdValue: number;
  gbpValue?: number;
  rate: number;
}) {
  return (
    <>
      <b>{usd(usdValue)}</b>
      <br />
      <span style={{ color: "#94a3b8" }}>
        {gbpDirect !== undefined ? gbpValue(gbpDirect) : gbpFromUsd(usdValue, rate)}
      </span>
    </>
  );
}

export default function App() {
  const [data, setData] = useState<any>(null);
  const [status, setStatus] = useState("Connecting...");
  const [message, setMessage] = useState("");
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("dashboard_api_key") || "");
  const [customTicker, setCustomTicker] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [timelineRange, setTimelineRange] = useState("day");
  const [chartCurrency, setChartCurrency] = useState<"USD" | "GBP">("GBP");

  const scans: Scan[] = Array.isArray(data?.scans) ? data.scans : [];
  const positions: Position[] = Array.isArray(data?.positions) ? data.positions : [];
  const trades: Trade[] = Array.isArray(data?.trades) ? data.trades : [];
  const tradeTimeline: any[] = Array.isArray(data?.tradeTimeline) ? data.tradeTimeline : [];
  const stockMemory: any[] = Array.isArray(data?.stockMemory) ? data.stockMemory : [];
  const logs: string[] = Array.isArray(data?.logs) ? data.logs : [];
  const alpacaRejectionEvents: any[] = Array.isArray(data?.alpacaRejectionEvents) ? data.alpacaRejectionEvents : [];
  const pdtWarningEvents: any[] = Array.isArray(data?.pdtWarningEvents) ? data.pdtWarningEvents : [];
  const rate = Number(data?.fx?.usdToGbp || 0.78);

  const fetchData = async () => {
    try {
      const res = await fetch(`${API_URL}/status`);
      const json = await res.json();
      setData(json);
      setStatus("Connected");

      const nextScans = Array.isArray(json?.scans) ? json.scans : [];
      if (!selectedSymbol && nextScans.length) {
        setSelectedSymbol(nextScans[0].symbol);
      }
    } catch (err) {
      console.error("Fetch failed:", err);
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
    } catch (err) {
      console.error("Action failed:", err);
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

  const selectedScan: Scan | undefined = useMemo(() => {
    if (!scans.length) return undefined;
    return scans.find((s) => s.symbol === selectedSymbol) || scans[0];
  }, [scans, selectedSymbol]);

  const timeline = useMemo(() => {
    const start = timelineFilterMs(timelineRange);
    return tradeTimeline
      .filter((e: any) => {
        if (!start) return true;
        const t = new Date(e?.timestamp || 0).getTime();
        return Number.isFinite(t) && t >= start;
      })
      .map((e: any, i: number) => ({ ...e, idx: i }));
  }, [tradeTimeline, timelineRange]);

  const timelineChart = useMemo(() => {
    return timeline.map((e: any, i: number) => ({
      idx: i,
      equity: chartCurrency === "GBP" ? (e.equityGbp ?? Number(e.equity || 0) * rate) : Number(e.equity || 0),
      symbol: e.symbol || "",
      side: e.side || "",
      time: e.time || "",
      reason: e.reason || "",
      pnl: chartCurrency === "GBP" ? (e.pnlGbp ?? Number(e.pnl || 0) * rate) : Number(e.pnl || 0),
      pnlPct: e.pnlPct || 0,
    }));
  }, [timeline, chartCurrency, rate]);

  const scannerChartData = selectedScan?.priceCurve || [];

  return (
    <div style={{ minHeight: "100vh", background: "#020617", color: "white", padding: 14, fontFamily: "Arial" }}>
      <div style={{ maxWidth: 1350, margin: "0 auto" }}>
        <h1 style={{ textAlign: "center", fontSize: "clamp(28px, 6vw, 48px)" }}>
          🇬🇧 GBP Profit Trading Bot
        </h1>

        <div style={{ textAlign: "center", color: status === "Connected" ? "#22c55e" : "#f87171", fontWeight: 700 }}>
          {status}
        </div>

        {data && (
          <div style={{ textAlign: "center", color: "#94a3b8", marginBottom: 12 }}>
            {data.name || "Trading Bot"} · {data.paperMode ? "PAPER" : "LIVE"} · Bot {data.botEnabled ? "ON" : "OFF"} · Market{" "}
            {data.market?.label || "UNKNOWN"} · USD/GBP {Number(rate).toFixed(4)}
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
          <>
            <div style={{ ...panel, marginBottom: 12, borderColor: "rgba(34,197,94,0.45)" }}>
              <h3>GBP Conversion</h3>
              <p style={{ color: "#22c55e", fontWeight: 700 }}>
                1 USD = £{Number(rate).toFixed(4)} GBP
              </p>
              <p style={{ color: "#94a3b8" }}>
                Equity, PnL, position value and trade history show both USD and GBP.
              </p>
            </div>

            
            <div style={{ ...panel, marginBottom: 12, borderColor: "rgba(20,184,166,0.45)" }}>
              <h3>Persistent Trade Database</h3>
              <p style={{ color: "#2dd4bf", fontWeight: 700 }}>
                SQLite {data.dbSummary?.enabled ? "ON" : "OFF"} · Raw Orders {data.dbSummary?.totalTrades || 0} · Closed Trades {data.dbSummary?.closedTrades || 0} · Win rate {pct((data.dbSummary?.winRate || 0) * 100)}
              </p>
              <p style={{ color: Number(data.dbSummary?.totalPnl || 0) >= 0 ? "#22c55e" : "#f87171" }}>
                Total Realised PnL: {usd(data.dbSummary?.totalPnl || 0)} / {gbpValue(data.dbSummary?.totalPnlGbp || 0)}
              </p>
              <p style={{ color: "#94a3b8" }}>
                Use “Full Backfill Alpaca Trades” to import old orders, then “Rebuild PnL Matching” to pair BUY → SELL and calculate realised PnL.
              </p>
            </div>

<div style={{ ...panel, marginBottom: 12, borderColor: "rgba(250,204,21,0.45)" }}>
              <h3>Strategy Modes</h3>
              <p style={{ color: "#facc15", fontWeight: 700 }}>
                Sniper {data.sniperModeEnabled ? "ON" : "OFF"} · A+ Gate {data.aPlusGateEnabled ? "ON" : "OFF"} · Confidence Sizing {data.confidenceSizingEnabled ? "ON" : "OFF"} · Stock Memory {data.stockMemoryEnabled ? "ON" : "OFF"} · PDT-Aware {data.pdtAwareModeEnabled ? "ON" : "OFF"}
              </p>
            </div>
          </>
        )}

        <div style={{ ...panel, marginBottom: 12 }}>
          <h3>Controls</h3>
          <button style={btn("#2563eb")} onClick={fetchData}>Refresh</button>
          <button style={btn("#0f766e")} onClick={() => action("/backfill-trades")}>Full Backfill Alpaca Trades</button>
          <button style={btn("#0d9488")} onClick={() => action("/rebuild-closed-trades")}>Rebuild PnL Matching</button>
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
              <div style={panel}>Equity<br /><DualMoney usdValue={data.account?.equity || 0} gbpValue={data.account?.equityGbp} rate={rate} /></div>
              <div style={panel}>Buying Power<br /><DualMoney usdValue={data.account?.buyingPower || 0} gbpValue={data.account?.buyingPowerGbp} rate={rate} /></div>
              <div style={panel}>Cash<br /><DualMoney usdValue={data.account?.cash || 0} gbpValue={data.account?.cashGbp} rate={rate} /></div>
              <div style={panel}>Day PnL<br /><b style={{ color: Number(data.account?.pnlDay || 0) >= 0 ? "#22c55e" : "#f87171" }}>{usd(data.account?.pnlDay)}</b><br /><span style={{ color: Number(data.account?.pnlDay || 0) >= 0 ? "#22c55e" : "#f87171" }}>{gbpValue(data.account?.pnlDayGbp ?? Number(data.account?.pnlDay || 0) * rate)}</span></div>
              <div style={panel}>Positions<br /><b>{positions.length}/{data.maxPositions || 0}</b></div>
              <div style={panel}>Next Buy Size<br /><DualMoney usdValue={data.newPositionNotional || 0} rate={rate} /></div>
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Trade Timeline</h3>
              <div>
                {["day", "week", "month", "total"].map((r) => (
                  <button key={r} style={btn(timelineRange === r ? "#2563eb" : "#334155")} onClick={() => setTimelineRange(r)}>
                    {r.toUpperCase()}
                  </button>
                ))}
                <button style={btn(chartCurrency === "USD" ? "#16a34a" : "#334155")} onClick={() => setChartCurrency("USD")}>USD Chart</button>
                <button style={btn(chartCurrency === "GBP" ? "#16a34a" : "#334155")} onClick={() => setChartCurrency("GBP")}>GBP Chart</button>
              </div>

              {timelineChart.length > 0 ? (
                <div style={{ height: 320 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={timelineChart}>
                      <CartesianGrid stroke="rgba(255,255,255,0.1)" />
                      <XAxis dataKey="idx" />
                      <YAxis />
                      <Tooltip formatter={(value: any) => chartCurrency === "GBP" ? gbpValue(Number(value)) : usd(Number(value))} />
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
              ) : (
                <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center", color: "#94a3b8", border: "1px dashed rgba(255,255,255,0.15)", borderRadius: 14, marginTop: 12 }}>
                  No trades yet — timeline will appear after first buy/sell.
                </div>
              )}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>All Positions</h3>
              {positions.length === 0 && <p>No open positions.</p>}
              {positions.map((p: Position) => (
                <div key={p.symbol} style={{ background: "#020617", borderRadius: 14, padding: 12, marginBottom: 8 }}>
                  <b>{p.symbol}</b>
                  {p.boughtToday ? <span style={{ color: "#facc15" }}> · BOUGHT TODAY · {p.minutesSinceBuy}m held</span> : null}
                  {p.partialProfitTaken ? <span style={{ color: "#22c55e" }}> · PARTIAL PROFIT TAKEN</span> : null}
                  {" · "}Qty {Number(p.qty).toFixed(4)} · Entry {usd(p.entry)} · Price {usd(p.price)}
                  <br />
                  Value: <b>{usd(p.marketValue)}</b> / <span style={{ color: "#94a3b8" }}>{gbpValue(p.marketValueGbp ?? p.marketValue * rate)}</span>
                  <br />
                  <span style={{ color: p.pnlPct >= 0 ? "#22c55e" : "#f87171" }}>
                    PnL {usd(p.pnl)} / {gbpValue(p.pnlGbp ?? p.pnl * rate)} / {pct(p.pnlPct)}
                  </span>
                  {" · "}
                  <span style={{ color: p.trailingActive ? "#22c55e" : "#facc15" }}>
                    {p.trailingActive ? `Trailing floor ${usd(p.trailFloor)}` : `Trail starts ${usd(p.trailStartPrice)}`}
                  </span>
                  <button style={btn("#dc2626")} onClick={() => action(`/sell/${p.symbol}`)}>Sell {p.symbol}</button>
                </div>
              ))}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Scanner</h3>

              {scans.length > 0 ? (
                <>
                  <select value={selectedScan?.symbol || ""} onChange={(e) => setSelectedSymbol(e.target.value)} style={{ padding: 10, borderRadius: 10, marginBottom: 10 }}>
                    {scans.map((s: Scan) => <option key={s.symbol} value={s.symbol}>{s.symbol}</option>)}
                  </select>

                  {scannerChartData.length > 0 ? (
                    <div style={{ height: 220, marginBottom: 12 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={scannerChartData}>
                          <CartesianGrid stroke="rgba(255,255,255,0.1)" />
                          <XAxis dataKey="t" />
                          <YAxis />
                          <Tooltip />
                          <Line type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={2} dot={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <p style={{ color: "#94a3b8" }}>No scanner chart data yet.</p>
                  )}

                  {scans.map((s: Scan) => (
                    <div key={s.symbol} style={{ background: s.aPlusPass || s.sniperPass ? "rgba(22,163,74,0.18)" : "#020617", borderRadius: 14, padding: 12, marginBottom: 8 }}>
                      <b>{s.symbol}</b> | {usd(s.price)} / {gbpFromUsd(s.price, rate)} | trigger {usd(s.trigger)} | spread {(Number(s.spread || 0) * 100).toFixed(2)}%
                      <br />
                      quality {(s.qualityScore || 0).toFixed(4)} | confidence {(s.confidence || 0).toFixed(2)} {s.confidenceLabel} | {(s.aPlusPass || s.sniperPass) ? "PASS" : `WAIT: ${s.aPlusReason || s.sniperReason || "not ready"}`}
                    </div>
                  ))}
                </>
              ) : (
                <div style={{ color: "#94a3b8", padding: 20, border: "1px dashed rgba(255,255,255,0.15)", borderRadius: 14 }}>
                  No scan data yet. This is normal while the market is closed.
                </div>
              )}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Trades</h3>
              {trades.length === 0 && <p>No trades yet.</p>}
              {trades.map((t: Trade, i: number) => (
                <div key={i} style={{ color: t.side === "BUY" ? "#22c55e" : "#f87171", marginBottom: 6 }}>
                  {t.time || "—"} | {t.side || "—"} | {t.symbol || "—"}
                  {t.amount ? ` | ${usd(t.amount)} / ${gbpValue(t.amountGbp ?? t.amount * rate)}` : ""}
                  {t.qty ? ` | ${t.qty} shares` : ""}
                  {t.reason ? ` | ${t.reason}` : ""}
                  {t.pnl !== undefined ? ` | PnL ${usd(t.pnl)} / ${gbpValue(t.pnlGbp ?? t.pnl * rate)} (${pct(t.pnlPct || 0)})` : ""}
                </div>
              ))}
            </div>


            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Matched Closed Trades</h3>
              {(!Array.isArray(data.closedTrades) || data.closedTrades.length === 0) && (
                <p style={{ color: "#94a3b8" }}>No matched closed trades yet. Click Backfill, then Rebuild PnL Matching.</p>
              )}
              {(Array.isArray(data.closedTrades) ? data.closedTrades : []).slice(-50).reverse().map((t: any, i: number) => (
                <div key={i} style={{ color: Number(t.pnl || 0) >= 0 ? "#22c55e" : "#f87171", marginBottom: 6 }}>
                  {t.time || "—"} | {t.symbol} | Qty {Number(t.qty || 0).toFixed(4)}
                  {" | "}Entry {usd(t.entryPrice || 0)} → Exit {usd(t.exitPrice || 0)}
                  {" | "}PnL {usd(t.pnl || 0)} / {gbpValue(t.pnlGbp || 0)} ({pct(t.pnlPct || 0)})
                </div>
              ))}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Stock Memory</h3>
              {stockMemory.length === 0 && <p style={{ color: "#94a3b8" }}>No completed sell history yet.</p>}
              {stockMemory.slice(0, 20).map((m: any) => (
                <div key={m.symbol} style={{ background: "#020617", borderRadius: 12, padding: 10, marginBottom: 6 }}>
                  <b>{m.symbol}</b> · Trust {m.trust} · Trades {m.trades} · Win rate {pct((m.winRate || 0) * 100)} · Avg PnL {usd(m.avgPnl || 0)} / {gbpFromUsd(m.avgPnl || 0, rate)}
                </div>
              ))}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Alpaca Rejections / PDT Warnings</h3>
              {alpacaRejectionEvents.length === 0 && pdtWarningEvents.length === 0 && <p style={{ color: "#94a3b8" }}>No warnings yet.</p>}
              {alpacaRejectionEvents.map((e: any, i: number) => (
                <div key={`a-${i}`} style={{ color: "#f87171", marginBottom: 6 }}>{e.time} | {e.message} | {e.error}</div>
              ))}
              {pdtWarningEvents.map((e: any, i: number) => (
                <div key={`p-${i}`} style={{ color: "#facc15", marginBottom: 6 }}>{e.time} | {e.message}</div>
              ))}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Logs</h3>
              {logs.map((l: string, i: number) => (
                <div key={i} style={{ color: l.includes("FX") ? "#22c55e" : l.includes("SNIPER") ? "#38bdf8" : l.includes("PDT") ? "#facc15" : l.includes("PROFIT") ? "#22c55e" : "#94a3b8", fontSize: 12 }}>
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
