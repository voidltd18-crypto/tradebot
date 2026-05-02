
import React, { useEffect, useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

type AnyObj = Record<string, any>;
type Tab = 'overview' | 'reports' | 'positions' | 'scanner' | 'activity' | 'admin';

const API_BASE = import.meta.env.VITE_API_BASE || '';

function money(value: any, symbol = '$') {
  const n = Number(value || 0);
  return `${symbol}${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(value: any) {
  const n = Number(value || 0);
  return `${n.toFixed(2)}%`;
}

function tone(value: any) {
  return Number(value || 0) >= 0 ? 'gain' : 'loss';
}

async function getJson(path: string) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
}

async function postJson(path: string, key: string) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'x-api-key': key || '' },
  });
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    return { ok: res.ok, message: text };
  }
}

function Card({ title, children, className = '' }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}

function Stat({ label, value, sub, className = '' }: { label: string; value: React.ReactNode; sub?: React.ReactNode; className?: string }) {
  return (
    <Card className="stat">
      <span>{label}</span>
      <strong className={className}>{value}</strong>
      {sub && <small>{sub}</small>}
    </Card>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>('overview');
  const [status, setStatus] = useState<AnyObj>({});
  const [reports, setReports] = useState<AnyObj>({});
  const [error, setError] = useState('');
  const [lastAction, setLastAction] = useState('No action yet.');
  const [apiKey, setApiKey] = useState(localStorage.getItem('dashboardApiKey') || '');
  const [currency, setCurrency] = useState<'USD' | 'GBP'>('USD');

  async function refresh() {
    try {
      const data = await getJson('/status');
      setStatus(data || {});
      setError('');
    } catch (e: any) {
      setError(e.message || 'Status failed');
    }

    try {
      const r = await getJson('/reports');
      setReports(r || {});
    } catch {
      setReports({});
    }
  }

  async function action(path: string) {
    try {
      const data = await postJson(path, apiKey);
      setLastAction(data.message || data.detail || JSON.stringify(data));
      await refresh();
    } catch (e: any) {
      setLastAction(`Action failed: ${e.message}`);
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, []);

  const account = status.account || {};
  const market = status.market || {};
  const positions = status.positions || [];
  const scans = status.scans || [];
  const logs = status.logs || [];
  const trades = status.trades || status.tradeTimeline || [];
  const dbSummary = status.dbSummary || {};
  const equityCurve = status.equityCurve || [];

  const chartData = useMemo(() => {
    return equityCurve.map((p: AnyObj) => ({
      t: p.t,
      value: currency === 'GBP' ? Number(p.valueGbp || 0) : Number(p.value || 0),
    }));
  }, [equityCurve, currency]);

  const deposited = reports.totalDeposited ?? reports.deposited ?? reports.totalDepositedUsd ?? 0;
  const earned = reports.earnedSinceDeposit ?? reports.earned ?? reports.totalProfit ?? reports.totalGainLoss ?? 0;
  const gainLoss = reports.totalGainLoss ?? reports.gainLoss ?? reports.netGainLoss ?? earned;
  const lost = reports.lostSinceDeposit ?? reports.grossLosses ?? reports.realisedLosses ?? 0;

  const tabs: { key: Tab; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'reports', label: 'Reports' },
    { key: 'positions', label: 'Positions' },
    { key: 'scanner', label: 'Scanner' },
    { key: 'activity', label: 'Activity' },
    { key: 'admin', label: 'Admin' },
  ];

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Live trading dashboard</p>
          <h1>TradeBot</h1>
        </div>
        <div className="top-actions">
          <span className={`pill ${error ? 'bad' : 'ok'}`}>{error ? 'Disconnected' : 'Connected'}</span>
          <span className={`pill ${market?.isOpen ? 'ok' : 'warn'}`}>Market {market?.label || 'UNKNOWN'}</span>
          <span className={`pill ${status.botEnabled ? 'ok' : 'bad'}`}>Bot {status.botEnabled ? 'ON' : 'OFF'}</span>
        </div>
      </header>

      <section className="stats-grid">
        <Stat
          label="Equity"
          value={money(account.equity)}
          sub={money(account.equityGbp, '£')}
        />
        <Stat
          label="Buying Power"
          value={money(account.buyingPower)}
          sub={money(account.buyingPowerGbp, '£')}
        />
        <Stat
          label="Day PnL"
          value={money(account.pnlDay)}
          sub={money(account.pnlDayGbp, '£')}
          className={tone(account.pnlDay)}
        />
        <Stat
          label="Total Gain/Loss"
          value={money(gainLoss)}
          sub={`${pct(dbSummary.winRate ? dbSummary.winRate * 100 : 0)} win rate`}
          className={tone(gainLoss)}
        />
      </section>

      <nav className="tabs">
        {tabs.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)} className={tab === t.key ? 'active' : ''}>
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'overview' && (
        <main className="grid two">
          <Card title="Quick Actions">
            <div className="actions">
              <button onClick={() => refresh()}>Refresh</button>
              <button onClick={() => action('/manual-buy')}>Money Buy</button>
              <button className="danger" onClick={() => action('/manual-sell')}>Sell Worst</button>
              <button className="ghost" onClick={() => action('/pause')}>Pause</button>
              <button onClick={() => action('/resume')}>Resume</button>
            </div>
            <p className="notice">{lastAction}</p>
          </Card>

          <Card title="Live Summary">
            <div className="summary">
              <div><span>Positions</span><b>{positions.length}/{status.maxPositions ?? '—'}</b></div>
              <div><span>Next buy</span><b>{money(status.newPositionNotional)}</b></div>
              <div><span>PDT / buys</span><b>{status.todayBuyCount ?? 0}/{status.maxNewBuysPerDayPdtAware ?? '—'}</b></div>
              <div><span>Locked today</span><b>{(status.lockedSymbolsToday || []).length}</b></div>
              <div><span>FX</span><b>USD/GBP {Number(status.fx?.usdToGbp || 0).toFixed(4)}</b></div>
            </div>
          </Card>

          <Card title="Equity Timeline" className="wide">
            <div className="currency-switch">
              <button className={currency === 'USD' ? 'active' : ''} onClick={() => setCurrency('USD')}>USD</button>
              <button className={currency === 'GBP' ? 'active' : ''} onClick={() => setCurrency('GBP')}>GBP</button>
            </div>
            <div className="chart">
              {chartData.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#243047" />
                    <XAxis dataKey="t" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip />
                    <Area type="monotone" dataKey="value" stroke="#38bdf8" fill="#38bdf833" />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <p className="muted">Equity timeline will appear after the bot records points.</p>
              )}
            </div>
          </Card>
        </main>
      )}

      {tab === 'reports' && (
        <main>
          <section className="stats-grid">
            <Stat label="Deposited" value={money(deposited)} />
            <Stat label="Earned" value={money(earned)} className={tone(earned)} />
            <Stat label="Current Gain/Loss" value={money(gainLoss)} className={tone(gainLoss)} />
            <Stat label="Lost Since Deposit" value={money(lost)} className="loss" />
          </section>
          <Card title="Report Details">
            <table>
              <tbody>
                {Object.entries(reports).filter(([,v]) => typeof v !== 'object').map(([k, v]) => (
                  <tr key={k}><td>{k}</td><td>{typeof v === 'number' ? v.toFixed(4) : String(v)}</td></tr>
                ))}
                {!Object.keys(reports).length && <tr><td colSpan={2}>No report data yet.</td></tr>}
              </tbody>
            </table>
          </Card>
        </main>
      )}

      {tab === 'positions' && (
        <main>
          <Card title="Open Positions">
            <div className="position-list">
              {positions.length ? positions.map((p: AnyObj) => (
                <article className="position" key={p.symbol}>
                  <div>
                    <h3>{p.symbol}</h3>
                    <p>Qty {Number(p.qty || 0).toFixed(4)} · Entry {money(p.entry)} · Price {money(p.price)}</p>
                    <p>Value <b>{money(p.marketValue)}</b> / {money(p.marketValueGbp, '£')}</p>
                  </div>
                  <div className="position-side">
                    <b className={tone(p.pnl)}>{money(p.pnl)} / {money(p.pnlGbp, '£')} / {pct(p.pnlPct)}</b>
                    <span>{p.trailingActive ? `Trailing floor ${money(p.trailFloor)}` : `Trail starts ${money(p.trailStartPrice)}`}</span>
                    <button className="danger" onClick={() => action(`/sell/${p.symbol}`)}>Sell {p.symbol}</button>
                  </div>
                </article>
              )) : <p className="muted">No open positions.</p>}
            </div>
          </Card>
        </main>
      )}

      {tab === 'scanner' && (
        <main>
          <Card title="Scanner">
            <div className="scan-grid">
              {scans.length ? scans.map((s: AnyObj) => (
                <article className="scan" key={s.symbol}>
                  <div><b>{s.symbol}</b><strong>{money(s.price)}</strong></div>
                  <p>Confidence {pct((s.confidence || 0) * 100)} · Quality {Number(s.qualityScore || 0).toFixed(4)}</p>
                  <span className={s.readyToBuy ? 'ready' : ''}>{s.readyToBuy ? 'Ready to buy' : (s.aPlusReason || s.sniperReason || 'Watching')}</span>
                </article>
              )) : <p className="muted">No scans yet.</p>}
            </div>
          </Card>
        </main>
      )}

      {tab === 'activity' && (
        <main className="grid two">
          <Card title="Recent Trades">
            <div className="log-list">
              {(trades || []).slice(-50).reverse().map((t: AnyObj, i: number) => (
                <div key={i}><b>{t.side || 'TRADE'} {t.symbol || ''}</b> · {t.reason || ''} · <span className={tone(t.pnl)}>{money(t.pnl || 0)}</span></div>
              ))}
              {!trades.length && <p className="muted">No trades yet.</p>}
            </div>
          </Card>
          <Card title="Logs">
            <div className="log-list">
              {logs.map((l: string, i: number) => <div key={i}>{l}</div>)}
              {!logs.length && <p className="muted">No logs.</p>}
            </div>
          </Card>
        </main>
      )}

      {tab === 'admin' && (
        <main>
          <Card title="Admin">
            <label className="field">
              <span>Dashboard password</span>
              <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
            </label>
            <div className="actions">
              <button onClick={() => { localStorage.setItem('dashboardApiKey', apiKey); setLastAction('Dashboard password saved.'); }}>Save</button>
              <button className="ghost" onClick={() => { setApiKey(''); localStorage.removeItem('dashboardApiKey'); }}>Clear</button>
            </div>
            <pre>{JSON.stringify({
              botEnabled: status.botEnabled,
              market: market.label,
              positions: positions.length,
              locked: status.lockedSymbolsToday || [],
              pdtWarnings: status.pdtWarningEvents?.length || 0,
            }, null, 2)}</pre>
          </Card>
        </main>
      )}
    </div>
  );
}
