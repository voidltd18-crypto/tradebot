import { useEffect, useMemo, useRef, useState } from "react";
import { API_URL } from "../lib/api";
import type { AnyObj } from "../lib/types";

const money = (n: unknown) => `${Number(n || 0).toFixed(2)}`;
const BUY_ALERTS_STORAGE_KEY = "tradebot_evidence_buy_alerts_enabled";

export function CryptoScannerPopoutPage({ authToken }: { authToken: string }) {
  const [shadow, setShadow] = useState<AnyObj | null>(null);
  const [bridge, setBridge] = useState<AnyObj | null>(null);
  const [evidence, setEvidence] = useState<AnyObj | null>(null);
  const [error, setError] = useState("");
  const [buyBusySymbol, setBuyBusySymbol] = useState("");
  const [buyMessage, setBuyMessage] = useState("");
  const [buyPreflight, setBuyPreflight] = useState<AnyObj | null>(null);
  const [buyAlertsEnabled, setBuyAlertsEnabled] = useState(() => {
    try {
      return window.localStorage.getItem(BUY_ALERTS_STORAGE_KEY) === "true";
    } catch (_) {
      return false;
    }
  });
  const [buyAlertMessage, setBuyAlertMessage] = useState("");
  const previousActionableRef = useRef<Set<string>>(new Set());
  const alertBaselineReadyRef = useRef(false);

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
        const [shadowBody, bridgeBody, buyPreflightBody] = await Promise.all([
          fetchJson(`${API_URL}/v18/crypto-shadow`, { cache: "no-store", headers }),
          fetchJson(`${API_URL}/v18/crypto-bridge`, { cache: "no-store", headers }),
          fetchJson(`${API_URL}/v18/crypto-evidence/buy-preflight`, { cache: "no-store", headers }),
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
        setBuyPreflight(buyPreflightBody);
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


  const playBuyJingle = () => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;
      const master = ctx.createGain();
      master.gain.value = 0.95;
      master.connect(ctx.destination);

      const notes = [659.25, 783.99, 987.77];
      [0, 0.72].forEach((repeatOffset) => {
        notes.forEach((frequency, index) => {
          const start = now + repeatOffset + index * 0.18;
          const end = start + 0.16;

          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.frequency.value = frequency;
          osc.type = "square";
          gain.gain.setValueAtTime(0.0001, start);
          gain.gain.exponentialRampToValueAtTime(0.35, start + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.0001, end);
          osc.connect(gain);
          gain.connect(master);
          osc.start(start);
          osc.stop(end);

          const layer = ctx.createOscillator();
          const layerGain = ctx.createGain();
          layer.frequency.value = frequency * 2;
          layer.type = "sine";
          layerGain.gain.setValueAtTime(0.0001, start);
          layerGain.gain.exponentialRampToValueAtTime(0.14, start + 0.02);
          layerGain.gain.exponentialRampToValueAtTime(0.0001, end);
          layer.connect(layerGain);
          layerGain.connect(master);
          layer.start(start);
          layer.stop(end);
        });
      });

      window.setTimeout(() => { try { ctx.close(); } catch (_) {} }, 1900);
    } catch (_) {}
  };

  const toggleBuyAlerts = async () => {
    if (buyAlertsEnabled) {
      setBuyAlertsEnabled(false);
      try { window.localStorage.setItem(BUY_ALERTS_STORAGE_KEY, "false"); } catch (_) {}
      setBuyAlertMessage("BUY alerts muted. This setting will be remembered.");
      return;
    }

    if ("Notification" in window && Notification.permission === "default") {
      try { await Notification.requestPermission(); } catch (_) {}
    }

    previousActionableRef.current = new Set(
      (Array.isArray(evidence?.decisions) ? evidence.decisions : [])
        .filter((row: AnyObj) => String(row?.verdict || "").includes("WOULD_BUY"))
        .map((row: AnyObj) => String(row?.symbol || "").toUpperCase())
    );
    alertBaselineReadyRef.current = true;
    setBuyAlertsEnabled(true);
    try { window.localStorage.setItem(BUY_ALERTS_STORAGE_KEY, "true"); } catch (_) {}
    setBuyAlertMessage(
      "BUY alerts armed and remembered. New WOULD BUY / STRONG WOULD BUY signals will chime" +
      ("Notification" in window && Notification.permission === "granted" ? " and show a desktop notification." : ".")
    );
    playBuyJingle();
  };

  useEffect(() => {
    if (!buyAlertsEnabled || !evidence) return;

    if (!alertBaselineReadyRef.current) {
      previousActionableRef.current = new Set(
        (Array.isArray(evidence?.decisions) ? evidence.decisions : [])
          .filter((row: AnyObj) => String(row?.verdict || "").includes("WOULD_BUY"))
          .map((row: AnyObj) => String(row?.symbol || "").toUpperCase())
      );
      alertBaselineReadyRef.current = true;
      setBuyAlertMessage(
        "BUY alerts restored from your saved setting. Waiting for a new actionable signal."
      );
      return;
    }

    const actionable = (Array.isArray(evidence?.decisions) ? evidence.decisions : [])
      .filter((row: AnyObj) => String(row?.verdict || "").includes("WOULD_BUY"));

    const current = new Set(actionable.map((row: AnyObj) => String(row?.symbol || "").toUpperCase()));
    const newlyActionable = actionable.filter((row: AnyObj) => {
      const symbol = String(row?.symbol || "").toUpperCase();
      return symbol && !previousActionableRef.current.has(symbol);
    });

    for (const row of newlyActionable) {
      const symbol = String(row?.symbol || "").toUpperCase();
      const verdict = String(row?.verdict || "WOULD_BUY").replaceAll("_", " ");
      playBuyJingle();
      setBuyAlertMessage(`NEW BUY SIGNAL · ${symbol} · ${verdict}`);
      if ("Notification" in window && Notification.permission === "granted") {
        try {
          new Notification("TradeBot BUY signal", {
            body: `${symbol} · ${verdict} · Score ${Number(row?.score || 0).toFixed(3)}`,
            tag: `tradebot-buy-${symbol}`,
          });
        } catch (_) {}
      }
    }

    previousActionableRef.current = current;
  }, [evidence, buyAlertsEnabled]);

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

  const suggestedEvidenceBuyUsd = () => {
    const fxRate = Number(shadow?.fx?.usdToGbp || 0.7403);
    const allocatedGbp = Math.max(0, Number(bridge?.cryptoAllocatedGbp || 0));
    const buyingPowerUsd = Math.max(
      0,
      Number(
        buyPreflight?.usableCryptoBuyingPowerUsd ??
        bridge?.accountCrypto?.buyingPowerUsd ??
        bridge?.accountCrypto?.buyingPower ??
        bridge?.buyingPowerUsd ??
        0
      )
    );
    const allocatedUsd = fxRate > 0 ? allocatedGbp / fxRate : allocatedGbp;
    const usableUsd = buyingPowerUsd > 0
      ? Math.min(allocatedUsd > 0 ? allocatedUsd : buyingPowerUsd, buyingPowerUsd)
      : allocatedUsd;
    return usableUsd >= 1 ? Math.floor(usableUsd * 100) / 100 : 0;
  };

  const confirmEvidenceBuy = async (row: AnyObj) => {
    const symbol = String(row?.symbol || "").toUpperCase();
    if (!symbol || buyBusySymbol) return;

    const notionalUsd = suggestedEvidenceBuyUsd();
    if (notionalUsd < 1) {
      setBuyMessage("No usable Crypto Allocation is available for a live buy.");
      return;
    }

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
      setBuyMessage(body?.message || `Live crypto buy submitted for ${symbol} at ${money(notionalUsd)}.`);
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
        <div style={{display:"flex",gap:8,alignItems:"center",flexWrap:"wrap",justifyContent:"flex-end"}}>
          <button
            type="button"
            className="crypto-chip"
            onClick={toggleBuyAlerts}
            style={{cursor:"pointer"}}
          >
            {buyAlertsEnabled ? "🔔 BUY ALERTS ON" : "🔕 BUY ALERTS OFF"}
          </button>
          <span className="crypto-chip">{Number(evidence?.model?.outcomes || 0).toLocaleString("en-GB")} outcomes learned</span>
        </div>
      </div>
      {buyAlertMessage && <div className="crypto-notice">{buyAlertMessage}</div>}

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
                    <button className="crypto-sell-now" onClick={() => confirmEvidenceBuy(row)} disabled={Boolean(buyBusySymbol) || suggestedEvidenceBuyUsd() < 1}>
                      {buyBusySymbol === row.symbol ? "SUBMITTING…" : suggestedEvidenceBuyUsd() > 0 ? `CONFIRM LIVE BUY · ${money(suggestedEvidenceBuyUsd())}` : "NO CRYPTO ALLOCATION"}
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
      <small className="muted">This is the same Evidence Decision Engine as the main Crypto Lab. A real buy is submitted only when you click the clearly labelled CONFIRM LIVE BUY button for that specific row.</small>
    </section>
  </main>;
}
