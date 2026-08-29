import type { Tab } from "../lib/types";

const tabs: { id: Tab; label: string; icon: string; badge?: string }[] = [
  { id: "overview", label: "Home", icon: "⌂" },
  { id: "positions", label: "Positions", icon: "◫" },
  { id: "portfolio", label: "AI Portfolio", icon: "◈" },
  { id: "reports", label: "Reports", icon: "▤" },
  { id: "explorer", label: "Market Explorer", icon: "◎" },
  { id: "audit", label: "Decision Audit", icon: "✓", badge: "V17.9" },
  { id: "intelligence", label: "AI Intelligence", icon: "✣" },
  { id: "weekly", label: "Weekly Review", icon: "▣", badge: "V18" },
  { id: "observatory", label: "Observatory", icon: "◉", badge: "V18.1" },
  { id: "admin", label: "Settings", icon: "⚙" },
];

export function Nav({ tab, setTab }: { tab: Tab; setTab: (tab: Tab) => void }) {
  return <aside className="sidebar">
    <div className="brand"><div className="brand-mark">◉</div><div><strong>TradeBot</strong><span>AI Trading System</span></div></div>
    <nav className="tabs sidebar-tabs">{tabs.map((item) => <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}><span className="nav-icon">{item.icon}</span><span>{item.label}</span>{item.badge && <em>{item.badge}</em>}</button>)}</nav>
    <div className="sidebar-status"><span className="status-dot" /> <b>SYSTEM ONLINE</b><small>Live dashboard connected</small></div>
  </aside>;
}
