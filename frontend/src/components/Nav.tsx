import { useState } from "react";
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
  { id: "crypto", label: "Crypto Lab", icon: "◇", badge: "SHADOW" },
  { id: "admin", label: "Settings", icon: "⚙" },
];

const mobilePrimary: Tab[] = ["overview", "positions", "explorer", "intelligence"];

export function Nav({ tab, setTab, isPhone = false }: { tab: Tab; setTab: (tab: Tab) => void; isPhone?: boolean }) {
  const [moreOpen, setMoreOpen] = useState(false);
  const choose = (next: Tab) => { setTab(next); setMoreOpen(false); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const primaryTabs = tabs.filter((item) => mobilePrimary.includes(item.id));
  const moreTabs = tabs.filter((item) => !mobilePrimary.includes(item.id));

  return <>
    {!isPhone && <aside className="sidebar desktop-sidebar">
      <div className="brand"><div className="brand-mark">◉</div><div><strong>TradeBot</strong><span>AI Trading System</span></div></div>
      <nav className="tabs sidebar-tabs">{tabs.map((item) => <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => choose(item.id)}><span className="nav-icon">{item.icon}</span><span>{item.label}</span>{item.badge && <em>{item.badge}</em>}</button>)}</nav>
      <div className="sidebar-status"><span className="status-dot" /> <b>SYSTEM ONLINE</b><small>Live dashboard connected</small></div>
    </aside>}

    {isPhone && <nav className="mobile-nav-dock" aria-label="Mobile navigation">
      {primaryTabs.map((item) => <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => choose(item.id)}><span>{item.icon}</span><small>{item.id === "intelligence" ? "AI" : item.label.replace("Market ", "")}</small></button>)}
      <button className={moreOpen || moreTabs.some((item) => item.id === tab) ? "active" : ""} onClick={() => setMoreOpen((value) => !value)}><span>☰</span><small>More</small></button>
    </nav>}

    {isPhone && moreOpen && <div className="mobile-more-backdrop" onClick={() => setMoreOpen(false)}>
      <section className="mobile-more-sheet" onClick={(event) => event.stopPropagation()}>
        <div className="mobile-sheet-handle" />
        <div className="mobile-sheet-head"><div><strong>TradeBot Menu</strong><small>More dashboards & controls</small></div><button onClick={() => setMoreOpen(false)} aria-label="Close menu">×</button></div>
        <div className="mobile-more-grid">
          {moreTabs.map((item) => <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => choose(item.id)}><span className="nav-icon">{item.icon}</span><span>{item.label}</span>{item.badge && <em>{item.badge}</em>}</button>)}
        </div>
      </section>
    </div>}
  </>;
}
