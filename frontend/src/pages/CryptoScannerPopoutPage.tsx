import { useEffect, useMemo, useState } from "react";
import { API_URL } from "../lib/api";
import type { AnyObj } from "../lib/types";

const money = (n: unknown) => `$${Number(n || 0).toFixed(2)}`;

export function CryptoScannerPopoutPage({ authToken }: { authToken: string }) {
  const [shadow, setShadow] = useState<AnyObj | null>(null);
  const [bridge, setBridge] = useState<AnyObj | null>(null);
  const [evidence, setEvidence] = useState<AnyObj | null>(null);
  const [error, setError] = useState("");
  const [buyBusySymbol, setBuyBusySymbol] = useState("");
  const [buyMessage, setBuyMessage] = useState("");

  useEffect(() => {
    let alive = true;

    const fetchJson = async (url: string, options: RequestInit = {}, timeoutMs = 8000) => {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), timeoutMs);
      try {
        const res = await fetch(url, { ...options, signal: controller.signal });
        const body = await res.json();
        if (!res.ok) throw new Error(body?.detail || body?.message || `HTTP ${res.status}`);
        return body;
      } finally {
        window.clearTimeout(timer);
      }
    };

    const load = async () => {
      try {
        const headers = { "X-API-Key": authToken };
        const [shadowBody, bridgeBody] = await Promise.all([
          fetchJson(`${API_URL}/v18/crypto-shadow`, { cache: "no-store", headers }),
          fetchJson(`${API_URL}/v18/crypto-bridge`, { cache: "no-store", headers }),
        ]);

        const decisionBody = await fetchJson(
          `${API_URL}/v18/crypto-evidence-decisions`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-API-Key": authToken },
            body: JSON.stringify({ scans: Array.isArray(shadowBody?.scans) ? shadowBody.scans : [] }),
          }
        );

        if (!alive) return;
        setShadow(shadowBody);
        setBridge(bridgeBody);
        setEvidence(decisionBody);
        setError("");
      } catch (e: any) {
        if (alive) setError(e?.name === "AbortError" ? "Refresh timed out." : e?.message || "Evidence engine unavailable");
      }
    };

    load();
    const id = window.setInterval(load, 15000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [authToken]);

  const rows = useMemo(() => {
    const list = Array.isArray(evidence?.decisions) ? [...evidence.decisions] : [];
    const priority = (v: unknown) =>
      String(v || "") === "STRONG_WOULD_BUY" ? 0 :
      String(v || "") === "WOULD_BUY" ? 1 :
      String(v || "") === "WAIT" ? 2 : 3;
    return list
      .sort((a: AnyObj, b: AnyObj) =>
        priority(a?.verdict) - priority(b?.verdict) ||
        Number(b?.evidenceRank || 0) - Number(a?.evidenceRank || 0)
      )
      .slice(0, 20);
  }, [evidence]);

  const confirmEvidenceBuy = async (row: AnyObj) => {
    const symbol = String(row?.symbol || "").toUpperCase();
    if (!symbol || buyBusySymbol) return;

    const fxRate = Number(shadow?.fx?.usdToGbp || 0.7403);
    const allocatedGbp = Math.max(0, Number(bridge?.cryptoAllocatedGbp || 0));
    const buyingPowerUsd = Math.max(
      0,
      Number(
        bridge?.accountCrypto?.buyingPowerUsd ??
        bridge?.accountCrypto?.buyingPower ??
        bridge?.buyingPowerUsd ??
        0
      )
    );
    const allocatedUsd = fxRate > 0 ? allocatedGbp / fxRate : allocatedGbp;
    const suggestedUsd = Math.max(
      1,
      Math.floor(
        buyingPowerUsd > 0
          ? Math.min(allocatedUsd > 0 ? allocatedUsd : buyingPowerUsd, buyingPowerUsd)
          : allocatedUsd > 0
            ? allocatedUsd
            : 25
      )
    );

    const rawAmount = window.prompt(
      `How much USD do you want to buy of ${symbol}?\n\nSuggested from current Crypto Allocation: $${suggestedUsd.toFixed(2)}`,
      suggestedUsd.toFixed(2)
    );
    if (rawAmount === null) return;

    const notionalUsd = Number(rawAmount);
    if (!Number.isFinite(notionalUsd) || notionalUsd < 1) {
      setBuyMessage("Enter a valid amount of at least $1.00.");
      return;
    }

    const evidenceText = [
      `Decision: ${String(row?.verdict || "").replaceAll("_", " ")}`,
      `Historical expectancy: ${money(row?.historicalExpectancyUsd)}`,
      `Evidence: ${Number(row?.evidenceTrades || 0)} outcomes`,
    ].join("\n");

    if (!window.confirm(
      `BUY ${money(notionalUsd)} of ${symbol} now?\n\n${evidenceText}\n\nThis submits a real Alpaca crypto market order.`
    )) return;

    setBuyBusySymbol(symbol);
    setBuyMessage("");
    try {
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), 10000);
      let res: Response;
      try {
        res = await fetch(`${API_URL}/v18/crypto-evidence/confirm-buy`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Auth-Token": authToken, "x-api-key": authToken },
          body: JSON.stringify({
            confirmation: "CONFIRM CRYPTO BUY",
            notionalUsd,
            scan: row,
          }),
          signal: controller.signal,
        });
      } finally {
        window.clearTimeout(timeoutId);
      }

      const body = await res.json();
      if (!res.ok || body?.ok === false) throw new Error(body?.detail || body?.message || `HTTP ${res.status}`);
      setBuyMessage(body?.message || `Crypto buy submitted for ${symbol}.`);
    } catch (e: any) {
      setBuyMessage(e?.name === "AbortError" ? "Buy request timed out." : e?.message || `Buy failed for ${symbol}.`);
    } finally {
      setBuyBusySymbol("");
    }
  };

  return <main className="crypto-lab-page crypto-scanner-popout">
    <section className="crypto-panel">
      <div className="crypto-panel-head">
        <div>
          <h3><span className="panel-icon">◎</span> V18.3.78 Evidence Decision Engine · Pop-out</h3>
          <p>Dedicated evidence view. Refreshes every 15 seconds and keeps actionable BUY decisions at the top.</p>
        </div>
        <span className="crypto-chip">{Number(evidence?.model?.outcomes || 0).toLocaleString("en-GB")} outcomes learned</span>
      </div>

      {error && <div className="crypto-warning">Evidence engine: {error}</div>}

      <div className="crypto-metric-grid">
        <div className="crypto-metric"><span>Positive symbols</span><strong>{Number(evidence?.model?.positiveSymbols?.length || 0)}</strong></div>
        <div className="crypto-metric"><span>Positive score bands</span><strong>{Number(evidence?.model?.positiveScoreBins?.length || 0)}</strong></div>
        <div className="crypto-metric"><span>Blocked negative symbols</span><strong>{Number(evidence?.model?.negativeSymbols?.length || 0)}</strong></div>
        <div className="crypto-metric"><span>Would select now</span><strong>{Number(evidence?.wouldSelect?.length || 0)}</strong></div>
      </div>

      <div className="crypto-table-wrap">
        <table className="crypto-scanner-table">
          <thead><tr><th>Rank</th><th>Symbol</th><th>Decision</th><th>Score</th><th>Historical expectancy</th><th>Evidence</th><th>Why</th><th>Action</th></tr></thead>
          <tbody>
            {rows.map((row: AnyObj, index: number) => (
              <tr key={`evidence-${row.symbol}`}>
                <td>{index + 1}</td>
                <td><b>{row.symbol}</b></td>
                <td><span className={`crypto-chip ${String(row.verdict || "").includes("BUY") ? "qualified" : row.verdict === "BLOCK" ? "loss" : "watching"}`}>{String(row.verdict || "WAIT").replaceAll("_", " ")}</span></td>
                <td>{Number(row.score || 0).toFixed(3)}</td>
                <td className={Number(row.historicalExpectancyUsd || 0) >= 0 ? "gain" : "loss"}>{money(row.historicalExpectancyUsd)}</td>
                <td>{Number(row.evidenceTrades || 0)} outcomes</td>
                <td>{String(row.reason || "—").replaceAll("_", " ")}</td>
                <td>
                  {String(row.verdict || "").includes("WOULD_BUY") ? (
                    <button className="crypto-sell-now" onClick={() => confirmEvidenceBuy(row)} disabled={Boolean(buyBusySymbol)}>
                      {buyBusySymbol === row.symbol ? "SUBMITTING…" : "CONFIRM BUY"}
                    </button>
                  ) : <span className="muted">—</span>}
                </td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={8}>Waiting for current scanner evidence.</td></tr>}
          </tbody>
        </table>
      </div>

      {buyMessage && <div className="crypto-notice crypto-sell-notice">{buyMessage}</div>}
      <small className="muted">This is the same Evidence Decision Engine as the main Crypto Lab. Real buys still require your CONFIRM BUY click and final confirmation.</small>
    </section>
  </main>;
}
