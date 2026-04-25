
import React, { useEffect, useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
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
  inUniverse: boolean;
  custom?: boolean;
  lockedToday?: boolean;
};

type Scan = {
  symbol: string;
  price: number;
  ref: number;
  trigger: number;
  spread: number;
  qty: number;
  score: number;
  pullback?: number;
  shortMomentum?: number;
  qualityScore?: number;
  readyToBuy?: boolean;
  lockedToday?: boolean;
  custom?: boolean;
  done: boolean;
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

function niceDate(s: string) {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString();
}

export default function App() {
  const [data, setData] = useState<any>(null);
  const [status, setStatus] = useState("Connecting...");
  const [message, setMessage] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [customTicker, setCustomTicker] = useState("");
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("dashboard_api_key") || "");

  const fetchData = async () => {
    try {
      const res = await fetch(`${API_URL}/status`);
      const json = await res.json();
      setData(json);
      setStatus("Connected");
      if (!selectedSymbol && json.scans?.length) {
        setSelectedSymbol(json.scans[0].symbol);
      }
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
        headers: {
          "x-api-key": apiKey.trim(),
        },
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

  const sellSymbol = async (symbol: string) => {
    const ok = confirm(`Sell ${symbol}? It will be locked from rebuying until tomorrow.`);
    if (!ok) return;
    await action(`/sell/${symbol}`);
  };

  const customBuy = async () => {
    const symbol = customTicker.trim().toUpperCase();
    if (!symbol) {
      setMessage("Enter a ticker first");
      return;
    }

    const ok = confirm(`Custom buy ${symbol}? It will be added to the managed universe.`);
    if (!ok) return;

    await action(`/custom-buy/${symbol}`);
    setCustomTicker("");
  };

  const selectedScan: Scan | undefined = useMemo(() => {
    return data?.scans?.find((s: Scan) => s.symbol === selectedSymbol);
  }, [data, selectedSymbol]);

  const bestCandidate: Scan | undefined = useMemo(() => {
    return [...(data?.scans || [])]
      .filter((s: Scan) => !s.lockedToday)
      .sort((a: Scan, b: Scan) => (b.qualityScore || 0) - (a.qualityScore || 0))[0];
  }, [data]);

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#020617",
        color: "white",
        padding: 14,
        fontFamily: "Arial, sans-serif",
      }}
    >
      <div style={{ maxWidth: 1350, margin: "0 auto" }}>
        <h1 style={{ textAlign: "center", fontSize: "clamp(28px, 6vw, 48px)" }}>
          🎯 Custom Buy Money Mode
        </h1>

        <div style={{ textAlign: "center", marginBottom: 10 }}>
          <span style={{ color: status === "Connected" ? "#22c55e" : "#f87171", fontWeight: 700 }}>
            {status}
          </span>
        </div>

        {data && (
          <div style={{ textAlign: "center", color: "#94a3b8", marginBottom: 12 }}>
            {data.name} · {data.paperMode ? "PAPER" : "LIVE"} · Bot {data.botEnabled ? "ON" : "OFF"} ·{" "}
            Market {data.market?.label || "UNKNOWN"} · {data.mode} · {data.allowedNewPositions} buy slots open · Emergency {data.emergencyStop ? "ON" : "OFF"}
          </div>
        )}

        <div style={{ ...panel, marginBottom: 12, borderColor: "rgba(250,204,21,0.35)" }}>
          <h3>Protection Rule</h3>
          <p style={{ color: "#facc15", fontWeight: 700 }}>
            BUY → HOLD → SELL → that symbol is locked until tomorrow.
          </p>
          <p style={{ color: "#94a3b8" }}>
            Custom buys are added to the managed universe, so trailing/stop protection applies after buying.
          </p>
          {data && (
            <p>
              Locked today:{" "}
              <b style={{ color: data.lockedSymbolsToday?.length ? "#f87171" : "#22c55e" }}>
                {data.lockedSymbolsToday?.length ? data.lockedSymbolsToday.join(", ") : "none"}
              </b>
              {" · "}
              Custom:{" "}
              <b style={{ color: data.customSymbols?.length ? "#38bdf8" : "#94a3b8" }}>
                {data.customSymbols?.length ? data.customSymbols.join(", ") : "none"}
              </b>
            </p>
          )}
        </div>

        {data && (
          <div
            style={{
              ...panel,
              marginBottom: 12,
              borderColor: data.market?.isOpen ? "rgba(34,197,94,0.45)" : "rgba(239,68,68,0.45)",
            }}
          >
            <h3>Market Status</h3>
            <p style={{ fontSize: 22, fontWeight: 800, color: data.market?.isOpen ? "#22c55e" : "#f87171" }}>
              {data.market?.isOpen ? "🟢 Market Open" : "🔴 Market Closed"}
            </p>
            <p style={{ color: "#94a3b8" }}>Current market time: {niceDate(data.market?.timestamp || "")}</p>
            <p style={{ color: "#94a3b8" }}>Next open: {niceDate(data.market?.nextOpen || "")}</p>
            <p style={{ color: "#94a3b8" }}>Next close: {niceDate(data.market?.nextClose || "")}</p>
          </div>
        )}

        <div style={{ ...panel, marginBottom: 12, borderColor: "rgba(56,189,248,0.45)" }}>
          <h3>Security</h3>
          <p style={{ color: "#94a3b8" }}>
            Enter your dashboard password to enable trading buttons on this device.
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Dashboard password"
              style={{
                padding: 11,
                borderRadius: 12,
                border: "1px solid rgba(255,255,255,0.18)",
                background: "#020617",
                color: "white",
                minWidth: 220,
              }}
            />
            <button style={btn("#2563eb")} onClick={saveApiKey}>Save Key</button>
            <button style={btn("#4b5563")} onClick={clearApiKey}>Clear</button>
          </div>
        </div>

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

          <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <input
              value={customTicker}
              onChange={(e) => setCustomTicker(e.target.value.toUpperCase())}
              placeholder="Ticker e.g. AMD"
              style={{
                padding: 11,
                borderRadius: 12,
                border: "1px solid rgba(255,255,255,0.18)",
                background: "#020617",
                color: "white",
                minWidth: 160,
              }}
            />
            <button style={btn("#22c55e")} onClick={customBuy}>Buy Custom</button>
          </div>

          {message && <div style={{ marginTop: 10, color: "#facc15" }}>{message}</div>}
        </div>

        {!data && <p>Loading...</p>}

        {data && (
          <>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                gap: 12,
                marginBottom: 12,
              }}
            >
              <div style={panel}>Equity<br /><b>{money(data.account.equity)}</b></div>
              <div style={panel}>Buying Power<br /><b>{money(data.account.buyingPower)}</b></div>
              <div style={panel}>Cash<br /><b>{money(data.account.cash)}</b></div>
              <div style={panel}>Day PnL<br /><b style={{ color: data.account.pnlDay >= 0 ? "#22c55e" : "#f87171" }}>{money(data.account.pnlDay)}</b></div>
              <div style={panel}>Positions<br /><b>{(data.positions || []).length}/{data.maxPositions}</b></div>
              <div style={panel}>Next Buy Size<br /><b>{money(data.newPositionNotional || 0)}</b></div>
              <div style={panel}>Risk<br /><b style={{ color: data.riskBlocked ? "#f87171" : "#22c55e" }}>{data.riskBlocked ? "BLOCKED" : "OK"}</b></div>
              <div style={panel}>Market<br /><b style={{ color: data.market?.isOpen ? "#22c55e" : "#f87171" }}>{data.market?.label || "UNKNOWN"}</b></div>
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>All Positions</h3>
              {(data.positions || []).length === 0 && <p>No open positions.</p>}
              {(data.positions || []).map((p: Position) => (
                <div
                  key={p.symbol}
                  style={{
                    background: "#020617",
                    borderRadius: 14,
                    padding: 12,
                    marginBottom: 8,
                    border: "1px solid rgba(255,255,255,0.08)",
                  }}
                >
                  <b>{p.symbol}</b>
                  {p.custom ? <span style={{ color: "#38bdf8" }}> · CUSTOM</span> : null}
                  {" · "}Qty {Number(p.qty).toFixed(4)} · Entry {money(p.entry)} · Price {money(p.price)} · Value {money(p.marketValue)}
                  {p.lockedToday ? <span style={{ color: "#f87171" }}> · LOCKED AFTER SELL</span> : null}
                  <br />
                  <span style={{ color: p.pnlPct >= 0 ? "#22c55e" : "#f87171" }}>
                    PnL {money(p.pnl)} / {pct(p.pnlPct)}
                  </span>
                  {" · "}
                  <span style={{ color: p.trailingActive ? "#22c55e" : "#facc15" }}>
                    {p.trailingActive ? `Trailing floor ${money(p.trailFloor)}` : `Trail starts ${money(p.trailStartPrice)}`}
                  </span>
                  {" · "}
                  <button style={btn("#dc2626")} onClick={() => sellSymbol(p.symbol)}>Sell {p.symbol}</button>
                </div>
              ))}
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Equity Chart</h3>
              <div style={{ height: 260 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.equityCurve || []}>
                    <CartesianGrid stroke="rgba(255,255,255,0.1)" />
                    <XAxis dataKey="t" />
                    <YAxis />
                    <Tooltip />
                    <Line type="monotone" dataKey="value" stroke="#22c55e" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div style={{ ...panel, marginBottom: 12 }}>
              <h3>Money Mode Scanner</h3>
              {bestCandidate && (
                <p style={{ color: "#facc15" }}>
                  Best unlocked: {bestCandidate.symbol} · quality {(bestCandidate.qualityScore || 0).toFixed(4)} ·{" "}
                  {bestCandidate.readyToBuy ? "READY" : "WATCHING"}
                </p>
              )}

              <select
                value={selectedSymbol}
                onChange={(e) => setSelectedSymbol(e.target.value)}
                style={{ padding: 10, borderRadius: 10, marginBottom: 10 }}
              >
                {(data.scans || []).map((s: Scan) => (
                  <option key={s.symbol} value={s.symbol}>{s.symbol}{s.custom ? " (CUSTOM)" : ""}</option>
                ))}
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

              {(data.scans || []).length === 0 && <p>No scan data yet</p>}
              {(data.scans || []).map((s: Scan) => (
                <div
                  key={s.symbol}
                  style={{
                    background: s.lockedToday
                      ? "rgba(239,68,68,0.18)"
                      : s.readyToBuy
                        ? "rgba(22,163,74,0.18)"
                        : "#020617",
                    borderRadius: 14,
                    padding: 12,
                    marginBottom: 8,
                    border: "1px solid rgba(255,255,255,0.08)",
                  }}
                >
                  <b>{s.symbol}</b>
                  {s.custom ? <span style={{ color: "#38bdf8" }}> · CUSTOM</span> : null}
                  {" | "}{money(s.price)} | trigger {money(s.trigger)} | spread {(s.spread * 100).toFixed(2)}%
                  <br />
                  pullback {pct((s.pullback || 0) * 100)} | momentum {pct((s.shortMomentum || 0) * 100)} | quality {(s.qualityScore || 0).toFixed(4)} |{" "}
                  {s.lockedToday ? "LOCKED UNTIL TOMORROW" : s.readyToBuy ? "READY" : "watching"}
                </div>
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

            <div style={{ ...panel, marginBottom: 12, borderColor: "rgba(251,191,36,0.45)" }}>
              <h3>Alpaca Sell Rejection / PDT Log</h3>
              <p style={{ color: "#94a3b8" }}>
                The bot still attempts sells. This panel only shows when Alpaca rejects a sell, including PDT blocks.
              </p>
              {(data.alpacaRejectionEvents || []).length === 0 && (
                <p style={{ color: "#94a3b8" }}>No Alpaca sell rejections yet.</p>
              )}
              {(data.alpacaRejectionEvents || []).map((e: any, i: number) => (
                <div key={i} style={{ color: e.type === "PDT BLOCK" ? "#facc15" : "#f87171", marginBottom: 8, fontWeight: 700 }}>
                  {e.time} | {e.message} | {e.reason}
                  <div style={{ color: "#94a3b8", fontWeight: 400, fontSize: 12 }}>
                    {e.error}
                  </div>
                </div>
              ))}
            </div>

            <div style={panel}>
              <h3>Logs</h3>
              {(data.logs || []).map((l: string, i: number) => (
                <div key={i} style={{ color: l.includes("PDT") || l.includes("REJECTION") ? "#facc15" : "#94a3b8", fontSize: 12 }}>
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
