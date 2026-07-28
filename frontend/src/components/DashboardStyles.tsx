export function DashboardStyles() {
  return <style>{`
    .ai-dashboard .hero-card{background:linear-gradient(135deg,rgba(56,189,248,.10),rgba(99,102,241,.08),rgba(2,6,23,.96))}
    .ai-dashboard .ai-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
    .ai-dashboard .ai-status-line{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid rgba(148,163,184,.13)}
    .ai-dashboard .ai-status-line:last-child{border-bottom:0}.ai-dashboard .ai-status-line span{color:#94a3b8}
    .ai-dashboard .ai-meter{margin:14px 0}.ai-dashboard .ai-meter-head{display:flex;justify-content:space-between;margin-bottom:8px}
    .ai-dashboard .ai-meter-track{height:12px;border-radius:999px;overflow:hidden;background:rgba(148,163,184,.16)}
    .ai-dashboard .ai-meter-fill{height:100%;border-radius:999px;background:linear-gradient(90deg,#38bdf8,#818cf8)}
    .ai-dashboard .decision-card{min-height:240px}.ai-dashboard .decision-symbol{font-size:2.5rem;margin:4px 0}
    .ai-dashboard .reason-list{margin:14px 0 0;padding-left:20px}.ai-dashboard .reason-list li{margin:8px 0;color:#cbd5e1}
    .ai-dashboard .admin-section{margin-top:18px}.ai-dashboard .compact-table td,.ai-dashboard .compact-table th{white-space:nowrap}
    @media(max-width:800px){.ai-dashboard .ai-grid{grid-template-columns:1fr}}
  `}</style>;
}
