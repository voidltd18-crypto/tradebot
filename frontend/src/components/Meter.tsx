import { clamp } from "../lib/format";

export function Meter({ value, label }: { value: number; label: string }) {
  const safeValue = clamp(Number(value || 0));
  return <div className="ai-meter" aria-label={`${label}: ${safeValue.toFixed(0)}%`}><div className="ai-meter-head"><span>{label}</span><strong>{safeValue.toFixed(0)}%</strong></div><div className="ai-meter-track"><div className="ai-meter-fill" style={{ width: `${safeValue}%` }} /></div></div>;
}
