import {useEffect,useMemo,useRef,useState} from "react";
import {Card} from "./Card";
import {API_URL,readJson} from "../lib/api";
import type {AnyObj} from "../lib/types";
const SMART_REBUY_PAIRS = ["UNIUSD","BTCUSD","XRPUSD","SOLUSD","HYPEUSD","LDOUSD","AVAXUSD","FILUSD","LTCUSD","ARBUSD","ADAUSD","ONDOUSD","SKYUSD","SHIBUSD","LINKUSD","SUSHIUSD","BATUSD","ETHUSD","XTZUSD","AAVEUSD","DOTUSD","CRVUSD","BCHUSD","GRTUSD","PAXGUSD","DOGEUSD","BONKUSD","YFIUSD","POLUSD"] as const;
const normaliseCryptoPair = (value: unknown) => String(value || "").toUpperCase().replace(/[^A-Z0-9]/g, "");

export function SmartRebuyPanel({authToken}:{authToken:string}) {
  const [signalSymbol, setSignalSymbol] = useState("UNIUSD");
  const [showAllRebuyCoins, setShowAllRebuyCoins] = useState(false);
  const [bulkSignals, setBulkSignals] = useState<AnyObj[]>([]);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkError, setBulkError] = useState("");
  const [bulkScannedAt, setBulkScannedAt] = useState("");
  const bulkBusyRef = useRef(false);
  useEffect(() => {
    if (!authToken) return;
    let active = true;
    async function scan() {
      if (bulkBusyRef.current) return;
      bulkBusyRef.current = true;
      if (active) setBulkLoading(true);
      try {
        const response = await fetch(`${API_URL}/v19/manual-crypto-rebuy-scan`, {
          cache:"no-store", headers: {"X-Auth-Token":authToken,"x-api-key":authToken},
        });
        if (!response.ok) throw new Error("Automatic broker scan unavailable");
        const payload = await readJson(response);
        if (!Array.isArray(payload?.rows) || payload.rows.length !== SMART_REBUY_PAIRS.length) throw new Error("Incomplete scan");
        if (active) {setBulkSignals(payload.rows);setBulkScannedAt(String(payload.scannedAt||""));setBulkError("");}
      } catch {
        if (active) setBulkError("Automatic scan unavailable — no unverified buy signals shown");
      } finally {
        bulkBusyRef.current = false;
        if (active) setBulkLoading(false);
      }
    }
    void scan();
    const interval = window.setInterval(()=>void scan(), 120000);
    return ()=>{active=false;window.clearInterval(interval);};
  }, [authToken]);
  const [signal, setSignal] = useState<AnyObj | null>(null);
  const [signalLoading, setSignalLoading] = useState(false);
  async function checkManualRebuySignal() {
    setSignalLoading(true);
    setSignal(null);
    try {
      const response = await fetch(`${API_URL}/v19/manual-crypto-rebuy-preview/${encodeURIComponent(signalSymbol)}`, {
        cache: "no-store", headers: {"X-Auth-Token": authToken, "x-api-key": authToken},
      });
      const result = await readJson(response);
      if (!response.ok) throw new Error("Broker preview unavailable");
      setSignal(result);
    } catch {
      setSignal({status:"WAIT",reason:"Could not verify broker data; do not buy"});
    } finally { setSignalLoading(false); }
  }
  const [rebuySymbol, setRebuySymbol] = useState("");
  const [rebuyRequestId, setRebuyRequestId] = useState("");
  const [rebuyAmount, setRebuyAmount] = useState("25");
  const [rebuyPotChoice, setRebuyPotChoice] = useState<"FULL" | "HALF" | null>(null);
  const [rebuySignalWarning, setRebuySignalWarning] = useState("");
  const [rebuyAvailable, setRebuyAvailable] = useState<number | null>(null);
  const [rebuyCashLoading, setRebuyCashLoading] = useState(false);
  const [rebuyCashError, setRebuyCashError] = useState("");
  async function fetchRebuyCash() {
    setRebuyCashLoading(true);
    setRebuyAvailable(null);
    setRebuyCashError("");
    try {
      const response = await fetch(`${API_URL}/v19/reports/crypto-buy-again/available`, {
        cache: "no-store",
        headers: {"X-Auth-Token":authToken, "x-api-key":authToken},
      });
      const payload = await readJson(response);
      const amount = Number(payload?.availableUsd);
      if (!response.ok || !payload?.ok || payload?.availableUsd == null || !Number.isFinite(amount) || amount < 0) {
        throw new Error(String(payload?.message || "Available cash could not be verified"));
      }
      setRebuyAvailable(amount);
      setRebuyAmount(rebuyPotChoice === "HALF" ? (Math.floor(amount * 50) / 100).toFixed(2) : (Math.floor(amount * 100) / 100).toFixed(2));
    } catch (error: any) {
      setRebuyCashError(String(error?.message || "Available cash could not be verified"));
    } finally { setRebuyCashLoading(false); }
  }
  function openSmartRebuyBuy(row: AnyObj) {
    const symbol = String(row?.symbol || "").toUpperCase();
    if (!cryptoPair(symbol) || rebuyPending) return;
    setRebuySymbol(symbol);
    setRebuyRequestId(crypto.randomUUID());
    setRebuyPotChoice(null);
    setRebuyAvailable(null);
    setRebuyAmount("");
    setRebuyMessage("");
    setRebuySignalWarning(row.status === "BUY_CANDIDATE"
      ? "Green signal is informational, not a guarantee. Broker conditions may have changed."
      : "AMBER WATCH: Recovery is NOT verified. Buying now is outside the green rebuy signal.");
    void fetchRebuyCash();
  }
  const [rebuyPending, setRebuyPending] = useState(false);
  const [rebuyMessage, setRebuyMessage] = useState("");
  const cryptoPair = (symbol: string) => /^[A-Z0-9]{2,20}\/USD$/.test(symbol.toUpperCase());
  async function submitRebuy() {
    if (!rebuySymbol || !rebuyRequestId || rebuyPending || rebuyCashLoading || rebuyAvailable === null || Number(rebuyAmount) < 1 || Number(rebuyAmount) > rebuyAvailable || !rebuyPotChoice) return;
    setRebuyPending(true);
    setRebuyMessage("");
    try {
      const response = await fetch(`${API_URL}/v19/reports/crypto-buy-again`, {
        method: "POST",
        headers: {"Content-Type":"application/json", "X-Auth-Token": authToken, "x-api-key":authToken},
        body: JSON.stringify({symbol:rebuySymbol, amountUsd:rebuyAmount, confirmation:`BUY ${rebuySymbol}`, requestId:rebuyRequestId}),
      });
      const result = await readJson(response);
      setRebuyMessage(String(result?.message || (response.ok ? "Broker request submitted; verify your orders." : "Order not placed.")));
      if (result?.orderSubmitted) { setRebuySymbol(""); }
    } catch {
      setRebuyMessage("Request status unknown. Check Alpaca orders before trying again.");
    } finally {setRebuyPending(false);}
  }
  const highlightedRebuyCoins = useMemo(() => bulkSignals.filter(row =>
    row?.status === "BUY_CANDIDATE" && row?.readOnly === true && row?.orderSubmitted === false ||
    row?.status === "WATCH" && row?.readOnly === true && row?.orderSubmitted === false
  ).sort((a,b) => (a.status === "BUY_CANDIDATE" ? 0 : 1) - (b.status === "BUY_CANDIDATE" ? 0 : 1)), [bulkSignals]);
  const relevantRebuyCoins = highlightedRebuyCoins.map(row => normaliseCryptoPair(row.symbol));
  const visibleRebuyCoins = showAllRebuyCoins ? SMART_REBUY_PAIRS : SMART_REBUY_PAIRS.filter(pair => relevantRebuyCoins.includes(pair));

return <>
    <Card title="Smart Rebuy — Crypto Signals" wide>
      <div style={{padding:18,border:"1px solid #334155",borderRadius:14,background:"#1e293b"}}>
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",gap:12,flexWrap:"wrap"}}>
          <div><strong style={{fontSize:18}}>Smart Rebuy</strong><p style={{margin:"5px 0",color:"#cbd5e1"}}>Live Alpaca · Read-only · No automatic buys · Automatically scans 29 coins every 2 minutes · Manual decisions only</p></div>
          <div style={{display:"flex",alignItems:"center",gap:8}}>
            <select aria-label="Smart Rebuy pair" value={signalSymbol} onChange={e=>{setSignalSymbol(e.target.value);setSignal(null);}}>
              {!visibleRebuyCoins.includes(signalSymbol as typeof SMART_REBUY_PAIRS[number]) && <option value={signalSymbol}>{signalSymbol.replace(/USD$/, "/USD")} · Selected</option>}
              {visibleRebuyCoins.map(pair => <option key={pair} value={pair}>{pair.replace(/USD$/, "/USD")}</option>)}
            </select>
            <button className="ghost" onClick={()=>setShowAllRebuyCoins(v=>!v)}>{showAllRebuyCoins ? "Show relevant only" : `Show all 29 coins`}</button>
            <button className="table-action" disabled={signalLoading} onClick={()=>void checkManualRebuySignal()}>{signalLoading?"Checking…":"Refresh Signal"}</button>
          </div>
        </div>
        <div style={{marginTop:12}}>
          <p style={{color:"#cbd5e1",margin:"0 0 8px"}}>{bulkLoading ? "Scanning 29 coins…" : bulkScannedAt ? `Auto-scanned 29 coins · ${new Date(bulkScannedAt).toLocaleTimeString("en-GB")}` : "Awaiting first automatic scan"}</p>
          {bulkError && <p role="status" style={{color:"#fbbf24"}}>{bulkError}</p>}
          {!bulkLoading && !bulkError && highlightedRebuyCoins.length===0 && <p style={{color:"#94a3b8"}}>No verified WATCH or BUY candidates right now. All other coins are hidden.</p>}
          <div style={{display:"flex",flexWrap:"wrap",gap:8}}>
            {highlightedRebuyCoins.map(row => <div key={row.symbol} style={{display:"flex",alignItems:"center",gap:6,padding:"4px 5px 4px 10px",borderRadius:9,border:"1px solid #475569",background:"#0f172a"}}>
              <button type="button" onClick={()=>{setSignalSymbol(normaliseCryptoPair(row.symbol));setSignal(row);}} style={{padding:"6px 2px",border:0,background:"transparent",color:"#f8fafc",cursor:"pointer"}}>
                <span style={{color:row.status==="BUY_CANDIDATE"?"#22c55e":"#f59e0b"}}>●</span> {row.symbol} · {row.status==="BUY_CANDIDATE"?"BUY candidate":"WATCH"}{row.dipPct!=null?` · ${row.dipPct}% dip`:""}
              </button>
              <button type="button" className="table-action" onClick={()=>openSmartRebuyBuy(row)}>Buy</button>
            </div>)}
          </div>
        </div>
        {showAllRebuyCoins && <div style={{marginTop:14,padding:12,borderRadius:10,background:"#0f172a"}}>
          <p style={{margin:"0 0 10px",color:"#cbd5e1"}}>All 29 coins — select one to check its broker signal:</p>
          <div style={{display:"flex",flexWrap:"wrap",gap:8}}>
            {SMART_REBUY_PAIRS.map(pair => <button key={pair} type="button"
              aria-pressed={signalSymbol===pair}
              onClick={()=>{setSignalSymbol(pair);setSignal(null);}}
              style={{padding:"7px 11px",borderRadius:8,cursor:"pointer",border:signalSymbol===pair?"1px solid #38bdf8":"1px solid #475569",background:signalSymbol===pair?"#164e63":"#1e293b",color:"#f8fafc"}}>
              {pair.replace(/USD$/, "/USD")}
            </button>)}
          </div>
        </div>}
        {signal && (() => {
          const reason=String(signal.reason||"No verified signal");
          const blocked=signal.positionOpen===true||signal.orderPending===true||/position|order pending|broker data unavailable|unverified|verified sale|credentials|invalid|could not verify/i.test(reason);
          const green=signal.status==="BUY_CANDIDATE"&&signal.readOnly===true&&signal.orderSubmitted===false;
          const colour=green?"#22c55e":blocked?"#ef4444":"#f59e0b";
          const label=green?"YES — Buy candidate":blocked?"NO — Blocked":"WAIT — Not ready";
          return <div role="status" style={{marginTop:16,padding:14,borderRadius:10,background:"#0f172a"}}>
            <div style={{display:"flex",alignItems:"center",gap:12}}>
              <span aria-hidden="true" style={{display:"inline-block",width:24,height:24,borderRadius:"50%",background:colour,boxShadow:`0 0 0 5px ${colour}22`,flexShrink:0}}/>
              <strong style={{fontSize:20}}>{label}</strong>
            </div>
            <p style={{margin:"12px 0 4px",color:"#cbd5e1"}}>{reason}</p>
            {signal.dipPct!=null&&<small>Dip from last sale: {String(signal.dipPct)}%</small>}
            {signal.quoteFresh===false&&<p style={{color:"#fbbf24"}}>Quote not fresh — no buy signal</p>}
          </div>;
        })()}
      </div>
    </Card>

    {rebuySymbol && <div role="dialog" aria-modal="true" aria-label="Buy crypto again" className="report-rebuy-dialog" style={{position:"fixed",inset:0,zIndex:9000,background:"rgba(0,0,0,.75)",display:"flex",alignItems:"center",justifyContent:"center",padding:16}}>
      <div style={{width:"min(450px,100%)",background:"#161b27",border:"1px solid #475569",borderRadius:12,padding:20,color:"#f8fafc"}}>
        <h3>Buy Crypto — {rebuySymbol}</h3>
        {rebuySignalWarning && <p role="alert" style={{color:"#fbbf24"}}>{rebuySignalWarning}</p>}
        <p>This requests a <strong>new Alpaca market buy</strong> at the current market price, not the historical sale price. It may use real money if the broker account is live and the feature is enabled.</p>
        <div style={{display:"flex",gap:8,marginBottom:12}}>
          <button type="button" disabled={rebuyAvailable===null || rebuyPending} onClick={()=>{setRebuyPotChoice("FULL");setRebuyAmount((Math.floor((rebuyAvailable||0)*100)/100).toFixed(2));}}>Full pot (100%)</button>
          <button type="button" disabled={rebuyAvailable===null || rebuyPending} onClick={()=>{setRebuyPotChoice("HALF");setRebuyAmount((Math.floor((rebuyAvailable||0)*50)/100).toFixed(2));}}>Half pot (50%)</button>
        </div>
        <p style={{color:"#cbd5e1"}}>Pot = verified available Alpaca cash, not total portfolio value. Choose a pot size, then confirm the live market order.</p>
        <label style={{display:"block",marginBottom:12}}>Amount to spend (USD) — choose Full or Half pot
          <input type="number" min="1" max={rebuyAvailable ?? undefined} step="0.01" value={rebuyAmount} disabled={rebuyCashLoading || rebuyAvailable === null} onChange={e=>{setRebuyPotChoice(null);setRebuyAmount(e.target.value);}} style={{display:"block",width:"100%",marginTop:5}}/>
        </label>
        <p role="status" style={{marginTop:-4}}>{rebuyCashLoading ? "Checking Alpaca cash…" : rebuyAvailable !== null ? `Available to buy: ${rebuyAvailable.toFixed(2)} USD` : (rebuyCashError || "No verified buying power available")}</p>
        <button className="ghost" disabled={rebuyCashLoading || rebuyPending} onClick={()=>{void fetchRebuyCash();}}>Refresh buying power</button>
        <p style={{color:"#fbbf24"}}>Review your coin and amount before pressing Confirm Buy. This button places a real-money market order when live trading is enabled.</p>
        <p>The available amount comes from Alpaca cash and non-marginable buying power, not your invested positions or vault. Alpaca rechecks cash when you confirm.</p>
        {rebuyMessage && <p role="status">{rebuyMessage}</p>}
        <div style={{display:"flex",gap:8,justifyContent:"flex-end"}}>
          <button className="ghost" disabled={rebuyPending} onClick={()=>{setRebuySymbol("");setRebuyRequestId("");setRebuyMessage("");}}>Close</button>
          <button disabled={rebuyPending || rebuyCashLoading || rebuyAvailable === null || !rebuyPotChoice || !(Number(rebuyAmount)>=1 && Number(rebuyAmount)<=rebuyAvailable)} onClick={submitRebuy}>{rebuyPending?"Submitting…":"Confirm Buy"}</button>
        </div>
      </div>
    </div>}
</>;
}
