import { useCallback, useEffect, useState } from "react";
import { API_URL, readJson } from "../lib/api";
import type { AnyObj } from "../lib/types";

type ReviewRow = {
  symbol: string;
  status?: string;
  holdingTradingDay?: number | null;
  maxTradingDays?: number;
  reviewDue?: boolean;
  entrySession?: string | null;
  action?: string;
  verificationSource?: string;
  reason?: string;
  sidewaysAssessment?: { status?: string; action?: string };
};

export function SwingReviewPanel({ authToken, symbols }: { authToken: string; symbols: string[] }) {
  const [rows, setRows] = useState<ReviewRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState("");
  const load = useCallback(async (signal?: AbortSignal) => {
    if (!authToken) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/swing-review`, {
        cache: "no-store",
        headers: { "X-Auth-Token": authToken, "x-api-key": authToken },
        signal,
      });
      const json: AnyObj = await readJson(response);
      if (!response.ok) throw new Error(String(json?.detail || `Review unavailable (${response.status})`));
      if (!Array.isArray(json?.positions)) throw new Error("Review response missing positions");
      if (signal?.aborted) return;
      setRows(json.positions);
      setUpdated(new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }));
      if (json.status !== "ok") setError(String(json.reason || "Some holdings could not be verified"));
    } catch (e) {
      if (!signal?.aborted) setError(e instanceof Error ? e.message : "Review unavailable");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [authToken]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const visible = rows.filter((row) => symbols.includes(String(row.symbol || "")));
  return <section className="card swing-review-panel" aria-label="Five-session holding review">
    <div className="swing-review-head">
      <div><h2>Five-Session Holding Review</h2><p className="muted">Read-only · Day 5 is a review, not a forced sell</p></div>
      <button className="ghost" type="button" disabled={loading} onClick={() => void load()}>{loading ? "Checking…" : "↻ Refresh"}</button>
    </div>
    {error && <p className="muted" role="status">Review status: {error}</p>}
    {!loading && !visible.length && <p className="muted">{symbols.length ? "No matching review data available yet." : "No open positions to review."}</p>}
    {visible.length > 0 && <div className="swing-review-grid">
      {visible.map((row) => {
        const verified = row.status === "verified" && Number.isFinite(Number(row.holdingTradingDay));
        const sideways = verified && row.reviewDue && row.sidewaysAssessment?.status === "sideways";
        const label = !verified ? "Unverified" : sideways ? "Sideways Candidate" : row.reviewDue ? "Review Due" : "Hold Window";
        const day = verified ? Math.max(0, Number(row.holdingTradingDay)) : null;
        const progress = day === null ? 0 : Math.min(100, (day / Math.max(1, Number(row.maxTradingDays || 5))) * 100);
        return <div className="swing-review-item" key={row.symbol}>
          <div className="swing-review-title"><strong>{row.symbol}</strong><span className={sideways ? "swing-flag sideways" : row.reviewDue ? "swing-flag due" : "swing-flag"}>{label}</span></div>
          <strong>{day === null ? "Holding day unknown" : `Day ${day} / ${row.maxTradingDays || 5}`}</strong>
          <div className="swing-review-track"><div style={{ width: `${progress}%` }} /></div>
          <small className="muted">{verified ? `Entered ${row.entrySession || "unknown"} · ${row.reviewDue ? "Review only" : "Holding window"}` : "Broker fill verification incomplete — no review decision"}</small>
        </div>;
      })}
    </div>}
    <small className="muted">Diagnostic only. Stops and other live trading rules remain separate.{updated ? ` · Updated ${updated} UK` : ""}</small>
  </section>;
}
