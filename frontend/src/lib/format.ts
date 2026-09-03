export const usd = (value: any) => `$${Number(value || 0).toFixed(2)}`;
export const gbp = (value: any) => `£${Number(value || 0).toFixed(2)}`;
export const pct = (value: any) => `${Number(value || 0).toFixed(2)}%`;
export const tone = (value: any) => (Number(value || 0) >= 0 ? "gain" : "loss");
export const clamp = (value: number, min = 0, max = 100) => Math.max(min, Math.min(max, value));

export const UK_TIME_ZONE = "Europe/London";

function reportTradeDate(trade: Record<string, any>) {
  const stamped = trade?.timestamp || trade?.closedAt || trade?.exitTime || "";
  if (stamped) return new Date(String(stamped));
  const day = String(trade?.day || trade?.date || "").trim();
  const clock = String(trade?.time || trade?.clock || trade?.timeOfDay || "00:00:00").trim();
  // Legacy report day/time fields are stored by the backend in UTC. Mark them
  // explicitly as UTC before converting for display, otherwise a UK browser
  // can accidentally treat the raw clock as already-local time.
  if (/^\d{4}-\d{2}-\d{2}$/.test(day)) return new Date(`${day}T${clock || "00:00:00"}Z`);
  const uk = day.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (uk) return new Date(`${uk[3]}-${uk[2]}-${uk[1]}T${clock || "00:00:00"}Z`);
  return new Date(String(day));
}

export function tradeDate(trade: Record<string, any>) {
  const date = reportTradeDate(trade);
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString("en-GB", { timeZone: UK_TIME_ZONE }) : String(trade?.day || trade?.date || "—");
}

export function tradeTime(trade: Record<string, any>) {
  const date = reportTradeDate(trade);
  return Number.isFinite(date.getTime()) ? date.toLocaleTimeString("en-GB", { timeZone: UK_TIME_ZONE, hour12: false }) : "—";
}
