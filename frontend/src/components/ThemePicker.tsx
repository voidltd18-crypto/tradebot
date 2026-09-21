export type ThemeId = "midnight-ocean" | "classic-dark" | "arctic-glass" | "aurora" | "trading-floor" | "mission-control";

export const THEMES: { id: ThemeId; label: string; icon: string }[] = [
  { id: "midnight-ocean", label: "Midnight Ocean", icon: "🌊" },
  { id: "classic-dark", label: "Classic Dark", icon: "🌑" },
  { id: "arctic-glass", label: "Arctic Glass", icon: "🧊" },
  { id: "aurora", label: "Aurora", icon: "🌌" },
  { id: "trading-floor", label: "Trading Floor", icon: "🏦" },
  { id: "mission-control", label: "Mission Control", icon: "🛰️" },
];

export function ThemePicker({ theme, setTheme }: { theme: ThemeId; setTheme: (theme: ThemeId) => void }) {
  return <label className="theme-picker" title="Change dashboard theme">
    <span className="theme-picker-icon">🎨</span>
    <select aria-label="Dashboard theme" value={theme} onChange={(event) => setTheme(event.target.value as ThemeId)}>
      {THEMES.map((item) => <option key={item.id} value={item.id}>{item.icon} {item.label}</option>)}
    </select>
  </label>;
}
