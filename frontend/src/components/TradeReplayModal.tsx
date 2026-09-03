import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { API_URL, readJson } from "../lib/api";
import { pct, usd } from "../lib/format";
import type { AnyObj } from "../lib/types";

type ReplayTarget = { mode: "live"; symbol: string } | { mode: "closed"; symbol: string; tradeId: number };

export function TradeReplayModal({ target, authToken, onClose }: { target: ReplayTarget | null; authToken: string; onClose: () => void }) {
  const [payload, setPayload] = useState<AnyObj>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!target) return;
    let cancelled = false;
    let timer: number | undefined;

    async function load() {
      setLoading(true);
      try {
        const path = target.mode === "live" ? `/trade-replay/live/${encodeURIComponent(target.symbol)}?limit=5000` : `/trade-replay/closed/${target.tradeId}?limit=5000`;
        const res = await fetch(`${API_URL}${path}`, { cache: "no-store", headers: authToken ? { "X-Auth-Token": authToken, "x-api-key": authToken } : {} });
        const json = await readJson(res);
        if (!res.ok || json?.ok === false) throw new Error(json?.message || json?.detail || "Replay unavailable");
        if (!cancelled) { setPayload(json); setError(""); }
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Replay unavailable");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    if (target.mode === "live") timer = window.setInterval(load, 5000);
    return () => { cancelled = true; if (timer) window.clearInterval(timer); };
  }, [target, authToken]);

  const chart = useMemo(() => (Array.isArray(payload?.points) ? payload.points : []).map((p: AnyObj) => {
    const dt = new Date(String(p.time || ""));
    return {
      ...p,
      label: Number.isFinite(dt.getTime()) ? dt.toLocaleTimeString("en-GB", { timeZone: "Europe/London", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : String(p.time || ""),
      price: Number(p.price || 0),
    };
  }), [payload?.points]);

  if (!target) return null;
  const stats = payload?.stats || {};
  const session = payload?.session || {};
  const trade = payload?.trade || {};
  const first = chart[0] || {};
  const last = chart[chart.length - 1] || {};
  const entry = Number(session.entryPrice || trade.entryPrice || first.entry || 0);
  const current = Number(target.mode === "closed" ? (trade.exitPrice || session.exitPrice || last.price || 0) : (last.price || 0));
  const pnlPct = entry > 0 && current > 0 ? ((current / entry) - 1) * 100 : Number(trade.pnlPct || last.pnlPct || 0);
  const trailStart = Number(last.trailStart || first.trailStart || 0);
  const trailFloor = Number(last.trailFloor || 0);
  const stop = Number(last.stop || first.stop || 0);
  const trailingActive = Boolean(last.trailingActive);
  const runnerGrace = Boolean(last.runnerGrace || last.source === "runner-grace");
  const peakExhaustion = Boolean(last.peakExhaustion || last.source === "peak-exhaustion");

  // V17.1.1: auto-zoom to the movement that matters while still keeping the
  // trade's entry/risk/profit reference levels visible. This avoids a tiny
  // $0.02 move being flattened inside an arbitrary multi-dollar axis.
  const yValues: number[] = chart.map((p: AnyObj) => Number(p.price || 0)).filter((v: number) => Number.isFinite(v) && v > 0);
  [entry, stop, trailStart, trailingActive ? trailFloor : 0].forEach((v) => { if (Number.isFinite(v) && v > 0) yValues.push(v); });
  let yDomain: [number, number] | [string, string] = ["auto", "auto"];
  if (yValues.length) {
    const low = Math.min(...yValues);
    const high = Math.max(...yValues);
    const spread = Math.max(high - low, Math.max(0.02, entry * 0.0025));
    const pad = Math.max(spread * 0.12, Math.max(0.01, entry * 0.001));
    yDomain = [Math.max(0, low - pad), high + pad];
  }

  return <div className="replay-backdrop" onMouseDown={onClose}>
    <section className="replay-modal" onMouseDown={(e) => e.stopPropagation()}>
      <div className="replay-header">
        <div><span className="replay-kicker">{target.mode === "live" ? "LIVE TRADE" : "SAVED TRADE REPLAY"}</span><h2>{target.symbol} Price Movement</h2></div>
        <button className="replay-close" onClick={onClose}>×</button>
      </div>

      <div className="replay-stats">
        <div><span>Entry</span><b>{usd(entry)}</b></div>
        <div><span>{target.mode === "live" ? "Current" : "Exit"}</span><b>{usd(current)}</b></div>
        <div><span>Peak recorded</span><b>{usd(stats.peak)}</b></div>
        <div><span>PnL</span><b className={pnlPct >= 0 ? "profit" : "loss"}>{pct(pnlPct)}</b></div>
        <div><span>Exit state</span><b>{runnerGrace ? `RUNNER GRACE ${usd(trailFloor)}` : (peakExhaustion ? `PEAK EXHAUSTION ARMED` : (trailingActive ? `TRAIL ACTIVE ${usd(trailFloor)}` : `Trail starts ${usd(trailStart)}`))}</b></div>
      </div>

      {loading && !chart.length && <p className="muted">Loading recorded movement…</p>}
      {error && <p className="notice loss">{error}</p>}
      {!loading && !error && !chart.length && <p className="notice">{payload?.message || "No recorded price points yet. Recording begins automatically while positions are open."}</p>}

      {chart.length > 0 && <>
        <div className="replay-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chart} margin={{ top: 12, right: 24, bottom: 8, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#263450" />
              <XAxis dataKey="label" stroke="#94a3b8" minTickGap={28} />
              <YAxis stroke="#94a3b8" domain={yDomain as any} allowDataOverflow={false} tickFormatter={(v) => `$${Number(v).toFixed(2)}`} />
              <Tooltip labelFormatter={(label) => `Time ${label}`} formatter={(value: any, name: any) => [usd(value), name === "price" ? "Price" : name]} />
              {entry > 0 && <ReferenceLine y={entry} stroke="#38bdf8" strokeDasharray="6 5" label={{ value: `Entry ${usd(entry)}`, fill: "#7dd3fc", position: "insideTopLeft" }} />}
              {trailStart > 0 && <ReferenceLine y={trailStart} stroke="#facc15" strokeDasharray="6 5" label={{ value: `Trail start ${usd(trailStart)}`, fill: "#fde047", position: "insideTopRight" }} />}
              {stop > 0 && <ReferenceLine y={stop} stroke="#fb7185" strokeDasharray="5 5" label={{ value: `Stop ${usd(stop)}`, fill: "#fda4af", position: "insideBottomLeft" }} />}
              {trailingActive && trailFloor > 0 && <ReferenceLine y={trailFloor} stroke="#22c55e" strokeDasharray="4 4" label={{ value: `Trail floor ${usd(trailFloor)}`, fill: "#4ade80", position: "insideBottomRight" }} />}
              <Line type="monotone" dataKey="price" stroke="#22c55e" strokeWidth={3} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="replay-footer">
          <span>{chart.length} saved points · recording every ~{Number(payload?.sampleSeconds || 10)} seconds · live refresh 5 seconds</span>
          <span>{session.startedAt ? `Recording since ${new Date(session.startedAt).toLocaleString("en-GB", { timeZone: "Europe/London" })}` : ""}</span>
        </div>
      </>}
    </section>
  </div>;
}

export type { ReplayTarget };
