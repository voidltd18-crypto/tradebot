import type { Tab } from "../lib/types";

const tabs: Tab[] = ["overview", "positions", "portfolio", "reports", "intelligence", "explorer", "audit", "weekly", "observatory", "admin"];
export function Nav({ tab, setTab }: { tab: Tab; setTab: (tab: Tab) => void }) {
  return <nav className="tabs">{tabs.map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item === "explorer" ? "MARKET EXPLORER" : item === "intelligence" ? "AI INTELLIGENCE" : item === "portfolio" ? "AI PORTFOLIO" : item === "audit" ? "DECISION AUDIT" : item === "weekly" ? "WEEKLY REVIEW" : item === "observatory" ? "OBSERVATORY" : item.toUpperCase()}</button>)}</nav>;
}
