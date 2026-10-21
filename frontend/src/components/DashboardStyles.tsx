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
    .swing-review-panel{margin:16px 0}.swing-review-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:14px}.swing-review-head h2{margin:0 0 4px;font-size:1.15rem}.swing-review-head p{margin:0}
    .swing-review-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin:14px 0}
    .swing-review-item{padding:14px;border:1px solid rgba(148,163,184,.24);border-radius:12px;background:rgba(15,23,42,.5);display:flex;flex-direction:column;gap:9px;min-width:0}
    .swing-review-title{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}.swing-flag{font-size:.76rem;padding:4px 8px;border-radius:999px;background:rgba(56,189,248,.13);color:#7dd3fc}.swing-flag.due{background:rgba(250,204,21,.15);color:#fde047}.swing-flag.sideways{background:rgba(251,146,60,.17);color:#fdba74}
    .swing-review-track{height:7px;border-radius:999px;background:rgba(148,163,184,.2);overflow:hidden}.swing-review-track div{height:100%;border-radius:999px;background:linear-gradient(90deg,#38bdf8,#818cf8)}.swing-review-item small{overflow-wrap:anywhere}
    @media(max-width:800px){.ai-dashboard .ai-grid{grid-template-columns:1fr}}
  `}</style>;
}
