import { useEffect, useMemo, useState } from "react";
import { API_URL } from "../lib/api";
import type { AnyObj } from "../lib/types";

const money = (n: unknown) => `$${Number(n || 0).toFixed(2)}`;

export function CryptoV2Page({ authToken }: { authToken: string }) {
  const [data, setData] = useState<AnyObj | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async (force = false) => {
    try {
      if (force) setBusy(true);
      const url = `${API_URL}/v19/crypto-v2${force ? "/refresh" : ""}`;
      const res = await fetch(url, {
        method: force ? "POST" : "GET",
        cache: "no-store",
        headers: { "X-API-Key": authToken },
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail || body?.message || `HTTP ${res.status}`);
      setData(body);
      setError("");
    } catch (e: any) {
      setError(e?.message || "Crypto V2 unavailable");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      await load(false);
    };
    tick();
    const id = window.setInterval(tick, 15000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [authToken]);

  const scans = useMemo(() => Array.isArray(data?.scans) ? data.scans : [], [data]);
  const positions = useMemo(() => Array.isArray(data?.shadow?.positions) ? data.shadow.positions : [], [data]);
  const trades = useMemo(() => Array.isArray(data?.shadow?.trades) ? [...data.shadow.trades].reverse() : [], [data]);

  return <main className="crypto-lab-page">
    <section className="crypto-panel">
      <div className="crypto-panel-head">
        <div>
          <h3>◈ Crypto V2 · Clean Rebuild</h3>
          <p>Fresh Alpaca crypto engine using the same basic shape as stocks: discover → validate → rank → manage positions.</p>
        </div>
        <div style={{display:"flex",gap:8,alignItems:"center",flexWrap:"wrap"}}>
          <span className="crypto-chip">SHADOW ONLY</span>
          <button className="crypto-chip" type="button" onClick={() => load(true)} disabled={busy}>
            {busy ? "SCANNING…" : "REFRESH NOW"}
          </button>
        </div>
      </div>

      {error && <div className="crypto-warning">{error}</div>}

      <div className="crypto-metric-grid">
        <div className="crypto-metric"><span>Discovered</span><strong>{Number(data?.discovered || 0)}</strong></div>
        <div className="crypto-metric"><span>Scanned</span><strong>{Number(data?.scanned || 0)}</strong></div>
        <div className="crypto-metric"><span>Qualified</span><strong>{Number(data?.qualified || 0)}</strong></div>
        <div className="crypto-metric"><span>Cycles</span><strong>{Number(data?.cycles || 0)}</strong></div>
        <div className="crypto-metric"><span>Shadow cash</span><strong>{money(data?.shadow?.cashUsd)}</strong></div>
        <div className="crypto-metric"><span>Realised P&L</span><strong>{money(data?.shadow?.realisedPnlUsd)}</strong></div>
        <div className="crypto-metric"><span>Unrealised P&L</span><strong>{money(data?.shadow?.unrealisedPnlUsd)}</strong></div>
        <div className="crypto-metric"><span>Positions</span><strong>{positions.length} / {Number(data?.shadow?.maxPositions || 0)}</strong></div>
      </div>
    </section>

    <section className="crypto-panel">
      <div className="crypto-panel-head">
        <div>
          <h3>Market Scanner</h3>
          <p>Ranks every Alpaca-tradable USD crypto market with price movement, spread and activity checks.</p>
        </div>
      </div>
      <div className="crypto-table-wrap">
        <table className="crypto-scanner-table">
          <thead>
            <tr><th>Rank</th><th>Symbol</th><th>Status</th><th>Price</th><th>24h</th><th>Spread</th><th>24h activity</th><th>Score</th></tr>
          </thead>
          <tbody>
            {scans.slice(0, 40).map((row: AnyObj, index: number) => (
              <tr key={String(row.symbol)}>
                <td>{index + 1}</td>
                <td><b>{row.symbol}</b></td>
                <td><span className={`crypto-chip ${row.qualified ? "qualified" : "watching"}`}>{row.qualified ? "QUALIFIED" : "WATCH"}</span></td>
                <td>{Number(row.price || 0).toLocaleString("en-GB", {maximumFractionDigits: 8})}</td>
                <td className={Number(row.change24hPct || 0) >= 0 ? "gain" : "loss"}>{Number(row.change24hPct || 0).toFixed(2)}%</td>
                <td>{Number(row.spreadPct || 0).toFixed(2)}%</td>
                <td>{money(row.notional24hUsd)}</td>
                <td>{Number(row.score || 0).toFixed(2)}</td>
              </tr>
            ))}
            {!scans.length && <tr><td colSpan={8}>Waiting for the first Crypto V2 scan.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>

    <section className="crypto-panel">
      <div className="crypto-panel-head">
        <div>
          <h3>Shadow Positions</h3>
          <p>V2 automatically paper-trades the highest-ranked qualified candidates so we can judge the new engine before adding live execution.</p>
        </div>
      </div>
      <div className="crypto-table-wrap">
        <table className="crypto-scanner-table">
          <thead><tr><th>Symbol</th><th>Entry</th><th>Price</th><th>P&L</th><th>Entry score</th><th>Opened</th></tr></thead>
          <tbody>
            {positions.map((row: AnyObj) => (
              <tr key={String(row.symbol)}>
                <td><b>{row.symbol}</b></td>
                <td>{Number(row.entry || 0).toLocaleString("en-GB", {maximumFractionDigits: 8})}</td>
                <td>{Number(row.price || 0).toLocaleString("en-GB", {maximumFractionDigits: 8})}</td>
                <td className={Number(row.pnlPct || 0) >= 0 ? "gain" : "loss"}>{Number(row.pnlPct || 0).toFixed(2)}%</td>
                <td>{Number(row.entryScore || 0).toFixed(2)}</td>
                <td>{String(row.openedAt || "—")}</td>
              </tr>
            ))}
            {!positions.length && <tr><td colSpan={6}>No V2 shadow positions open.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>

    <section className="crypto-panel">
      <div className="crypto-panel-head"><div><h3>V2 Trade Log</h3></div></div>
      <div className="crypto-table-wrap">
        <table className="crypto-scanner-table">
          <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Price</th><th>P&L</th><th>Reason</th></tr></thead>
          <tbody>
            {trades.slice(0, 30).map((row: AnyObj, index: number) => (
              <tr key={`${row.timestamp}-${row.symbol}-${index}`}>
                <td>{String(row.timestamp || "—")}</td>
                <td>{row.symbol}</td>
                <td>{row.side}</td>
                <td>{Number(row.price || 0).toLocaleString("en-GB", {maximumFractionDigits: 8})}</td>
                <td className={Number(row.pnlUsd || 0) >= 0 ? "gain" : "loss"}>{row.pnlUsd == null ? "—" : money(row.pnlUsd)}</td>
                <td>{row.reason || "—"}</td>
              </tr>
            ))}
            {!trades.length && <tr><td colSpan={6}>No V2 shadow trades yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  </main>;
}
