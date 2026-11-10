import type { AnyObj } from "../lib/types";
import { BOT_VERSION } from "../lib/api";

export function Header({ status, data, marketLabel, onLogout }: { status: string; data: AnyObj; marketLabel: string; onLogout: () => void }) {
  return <header className="topbar"><div><p className="eyebrow">AI Trading Supervisor · {BOT_VERSION}</p><h1>TradeBot</h1></div><div className="pills"><span className={`pill ${status === "Connected" ? "ok" : "warn"}`}>{status}</span><span className={`pill ${data?.market?.isOpen ? "ok" : "warn"}`}>Market {marketLabel}</span><span className={`pill ${data?.botEnabled ? "ok" : "bad"}`}>Bot {data?.botEnabled ? "ON" : "OFF"}</span><span className="pill">{data?.paperMode ? "PAPER" : "LIVE"}</span><button className="ghost" onClick={onLogout}>Logout</button></div></header>;
}
