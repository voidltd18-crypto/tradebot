export const usd = (value: any) => `$${Number(value || 0).toFixed(2)}`;
export const gbp = (value: any) => `£${Number(value || 0).toFixed(2)}`;
export const pct = (value: any) => `${Number(value || 0).toFixed(2)}%`;
export const tone = (value: any) => (Number(value || 0) >= 0 ? "gain" : "loss");
export const clamp = (value: number, min = 0, max = 100) => Math.max(min, Math.min(max, value));

export function tradeDate(trade: Record<string, any>) {
  const raw = trade?.timestamp || (trade?.day && trade?.time ? `${trade.day}T${trade.time}` : trade?.day || trade?.date || "");
  const date = new Date(String(raw));
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString("en-GB") : String(trade?.day || trade?.date || "—");
}

export function tradeTime(trade: Record<string, any>) {
  if (trade?.time) return String(trade.time).slice(0, 8);
  const date = new Date(String(trade?.timestamp || ""));
  return Number.isFinite(date.getTime()) ? date.toLocaleTimeString("en-GB", { hour12: false }) : "—";
}
