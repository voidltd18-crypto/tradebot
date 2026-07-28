import type { Tab } from "../lib/types";

const tabs: Tab[] = ["overview", "positions", "reports", "explorer", "admin"];
export function Nav({ tab, setTab }: { tab: Tab; setTab: (tab: Tab) => void }) {
  return <nav className="tabs">{tabs.map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item === "explorer" ? "MARKET EXPLORER" : item.toUpperCase()}</button>)}</nav>;
}
