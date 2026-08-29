import type { AnyObj } from "../lib/types";
import { BOT_VERSION } from "../lib/api";

export function Header({ status, data, marketLabel, onLogout }: { status: string; data: AnyObj; marketLabel: string; onLogout: () => void }) {
  return <header className="topbar command-topbar">
    <div>
      <p className="eyebrow">TRADEBOT · {BOT_VERSION}</p>
      <h1>Welcome back <span className="wave">👋</span></h1>
      <p className="topbar-subtitle">AI-powered trading, research and autonomous governance</p>
    </div>
    <div className="pills command-pills">
      <span className={`pill ${status === "Connected" ? "ok" : "warn"}`}>{status}</span>
      <span className={`pill ${data?.market?.isOpen ? "ok" : "warn"}`}>US Market {marketLabel}</span>
      <span className={`pill ${data?.botEnabled ? "ok" : "bad"}`}>Bot {data?.botEnabled ? "ON" : "OFF"}</span>
      <span className="pill">{data?.paperMode ? "PAPER" : "LIVE"}</span>
      <button className="ghost logout-button" onClick={onLogout}>Logout</button>
    </div>
  </header>;
}
