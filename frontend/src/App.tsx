import { lazy, Suspense, useEffect, useState } from "react";
import { DashboardStyles } from "./components/DashboardStyles";
import { Header } from "./components/Header";
import { Login } from "./components/Login";
import { Nav } from "./components/Nav";
import { Stat } from "./components/Stat";
import { useTradeBot } from "./hooks/useTradeBot";
import { gbp, tone, usd } from "./lib/format";
import type { AnyObj, Tab } from "./lib/types";
import { OverviewPage } from "./pages/OverviewPage";
import { PositionsPage } from "./pages/PositionsPage";

const AdminPage = lazy(() => import("./pages/AdminPage").then((module) => ({ default: module.AdminPage })));
const IntelligencePage = lazy(() => import("./pages/IntelligencePage").then((module) => ({ default: module.IntelligencePage })));
const ExplorerPage = lazy(() => import("./pages/ExplorerPage").then((module) => ({ default: module.ExplorerPage })));
const PortfolioPage = lazy(() => import("./pages/PortfolioPage").then((module) => ({ default: module.PortfolioPage })));
const ObservatoryPage = lazy(() => import("./pages/ObservatoryPage").then((module) => ({ default: module.ObservatoryPage })));
const WeeklyReviewPage = lazy(() => import("./pages/WeeklyReviewPage").then((module) => ({ default: module.WeeklyReviewPage })));
const AuditPage = lazy(() => import("./pages/AuditPage").then((module) => ({ default: module.AuditPage })));
const CryptoLabPage = lazy(() => import("./pages/CryptoLabPage").then((module) => ({ default: module.CryptoLabPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((module) => ({ default: module.ReportsPage })));


function usePhoneLayout() {
  const detect = () => {
    if (typeof window === "undefined") return false;
    const vv = window.visualViewport?.width ?? Number.POSITIVE_INFINITY;
    const screenWidth = Math.min(window.screen?.width || Number.POSITIVE_INFINITY, window.screen?.height || Number.POSITIVE_INFINITY);
    const coarse = window.matchMedia?.("(pointer: coarse)")?.matches ?? false;
    return window.innerWidth <= 760 || vv <= 760 || screenWidth <= 760 || (coarse && window.innerWidth <= 1100);
  };
  const [isPhone, setIsPhone] = useState(detect);
  useEffect(() => {
    const refresh = () => setIsPhone(detect());
    refresh();
    window.addEventListener("resize", refresh);
    window.addEventListener("orientationchange", refresh);
    window.visualViewport?.addEventListener("resize", refresh);
    return () => {
      window.removeEventListener("resize", refresh);
      window.removeEventListener("orientationchange", refresh);
      window.visualViewport?.removeEventListener("resize", refresh);
    };
  }, []);
  return isPhone;
}

function PageLoading() {
  return <div className="card"><strong>Loading this page…</strong><div className="muted">Live balances and trading remain connected.</div></div>;
}

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [exportRequested, setExportRequested] = useState(false);
  const isPhone = usePhoneLayout();
  const bot = useTradeBot(tab);

  function positionGlowStyle(position: AnyObj): React.CSSProperties {
    const pnlPct = Number(position?.pnlPct || 0);
    if (pnlPct >= 5) return { borderColor: "rgba(34,197,94,.95)", boxShadow: "0 0 26px rgba(34,197,94,.42)", background: "linear-gradient(135deg,rgba(34,197,94,.13),rgba(2,6,23,.96) 55%)" };
    if (pnlPct >= 1) return { borderColor: "rgba(34,197,94,.65)", boxShadow: "0 0 18px rgba(34,197,94,.25)" };
    if (pnlPct > -1) return { borderColor: "rgba(56,189,248,.35)", boxShadow: "0 0 12px rgba(56,189,248,.10)" };
    if (pnlPct > -4) return { borderColor: "rgba(251,146,60,.75)", boxShadow: "0 0 20px rgba(251,146,60,.28)" };
    return { borderColor: "rgba(248,113,113,.9)", boxShadow: "0 0 28px rgba(248,113,113,.38)", background: "linear-gradient(135deg,rgba(248,113,113,.13),rgba(2,6,23,.96) 55%)" };
  }

  if (!bot.authToken) {
    return <Login username={bot.secureUsername} password={bot.securePassword} error={bot.authError} setUsername={bot.setSecureUsername} setPassword={bot.setSecurePassword} onLogin={bot.secureLogin} />;
  }

  const totalDeposited = Number(bot.reports?.totalDeposited || 0);
  const totalGainLoss = Number(bot.reports?.totalGainLoss || 0);
  const profitVault = bot.banking?.profitVault || bot.data?.banking?.profitVault || {};
  const bankedProfitGbp = Number(profitVault?.bankedProfitGbp || 0);
  const accountEquityGbp = Number(bot.data?.account?.equity || 0) * bot.rate;
  const tradingCapitalGbp = Math.max(0, Number(profitVault?.accountEquityGbp || accountEquityGbp) - bankedProfitGbp);
  const maxPositions = Number(bot.data?.maxPositions || bot.positionSettings?.maxPositions || 0);

  return <div className={`app ai-dashboard command-dashboard${isPhone ? " phone-layout" : ""}`}>
    <DashboardStyles />
    <div className="dashboard-shell">
      <Nav tab={tab} setTab={setTab} isPhone={isPhone} />
      <div className="dashboard-content">
        <Header status={bot.status} data={bot.data} marketLabel={bot.marketLabel} onLogout={bot.secureLogout} />

        <section className="stats command-stats">
          <Stat label="Equity" value={gbp(accountEquityGbp)} sub={usd(bot.data?.account?.equity)} />
          <Stat label="Trading Capital" value={gbp(tradingCapitalGbp)} sub="Invested + free cash · vault excluded" />
          <Stat label="Today P&L" value={gbp(Number(bot.data?.account?.pnlDay || 0) * bot.rate)} sub="Since midnight" className={tone(bot.data?.account?.pnlDay)} />
          <Stat label="Total Gain/Loss" value={gbp(totalGainLoss)} sub={`Deposited ${gbp(totalDeposited)}`} className={tone(totalGainLoss)} />
          <Stat label="Profit Vault" value={gbp(bankedProfitGbp)} sub="Protected realised profit" className={bankedProfitGbp > 0 ? "gain" : ""} />
          <Stat label="Positions" value={`${bot.positions.length} / ${maxPositions || "—"}`} sub="Open / Max" />
        </section>

        {tab === "overview" && <OverviewPage {...bot} positionGlowStyle={positionGlowStyle} onExportFullBot={() => setExportRequested(true)} exportBusy={exportRequested} />}
        {tab === "positions" && <PositionsPage positions={bot.positions} rate={bot.rate} action={bot.action} positionGlowStyle={positionGlowStyle} authToken={bot.authToken} />}
        <Suspense fallback={<PageLoading />}>
          {tab === "portfolio" && <PortfolioPage authToken={bot.authToken} />}
          {tab === "reports" && <ReportsPage reports={bot.reports} data={bot.data} rate={bot.rate} closedTrades={bot.closedTrades} chartCurrency={bot.chartCurrency} setChartCurrency={bot.setChartCurrency} reportsLoading={bot.reportsLoading} reportsError={bot.reportsError} reportsUpdatedAt={bot.reportsUpdatedAt} loadReports={bot.loadReports} authToken={bot.authToken} />}
          {tab === "intelligence" && <IntelligencePage authToken={bot.authToken} marketRegime={bot.marketRegime} botHealth={bot.botHealth} aiConfidence={bot.aiConfidence} fetchData={bot.fetchData} />}
          {tab === "explorer" && <ExplorerPage data={bot.data} stockQuery={bot.stockQuery} setStockQuery={bot.setStockQuery} stockResults={bot.stockResults} setStockResults={bot.setStockResults} stockSearchLoading={bot.stockSearchLoading} searchStocks={bot.searchStocks} action={bot.action} />}
          {tab === "audit" && <AuditPage authToken={bot.authToken} />}
          {tab === "weekly" && <WeeklyReviewPage authToken={bot.authToken} />}
          {tab === "observatory" && <ObservatoryPage authToken={bot.authToken} />}
          {tab === "crypto" && <CryptoLabPage authToken={bot.authToken} />}
          {tab === "admin" && <AdminPage {...bot} />}
          {exportRequested && tab !== "intelligence" && <div className="home-export-host" aria-hidden="true"><IntelligencePage authToken={bot.authToken} marketRegime={bot.marketRegime} botHealth={bot.botHealth} aiConfidence={bot.aiConfidence} fetchData={bot.fetchData} autoExport onExportComplete={() => setExportRequested(false)} /></div>}
        </Suspense>
      </div>
    </div>
  </div>;
}
