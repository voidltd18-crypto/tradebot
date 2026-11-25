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
  // Sound is opt-in: mobile browsers require a user gesture to enable audio.
  const [soundEnabled, setSoundEnabled] = useState(false);
  const audioRef = useRef<AudioContext | null>(null);
  const lastGreenRef = useRef<Set<string> | null>(null);
  const soundEnabledRef = useRef(false);
  const playGreenAlert = () => {
    const ctx = audioRef.current;
    if (!ctx || ctx.state !== "running") return;
    const start = ctx.currentTime;
    // A louder, longer three-note chime with a soft attack to avoid clicks.
    // Peak gain remains below unity; device volume is still controlled by iOS.
    [0, 0.24, 0.48].forEach((offset, i) => {
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      oscillator.type = "triangle";
      oscillator.frequency.value = [660, 880, 1046][i];
      gain.gain.setValueAtTime(0.0001, start + offset);
      gain.gain.exponentialRampToValueAtTime(0.42, start + offset + 0.025);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + offset + 0.22);
      oscillator.connect(gain); gain.connect(ctx.destination);
      oscillator.start(start + offset); oscillator.stop(start + offset + 0.23);
    });
  };
  const enableSound = async () => {
    if (soundEnabledRef.current) {
      soundEnabledRef.current = false; setSoundEnabled(false);
      return;
    }
    try {
      const ctx = audioRef.current || new AudioContext();
      audioRef.current = ctx;
      await ctx.resume();
      if (ctx.state !== "running") return;
      soundEnabledRef.current = true; setSoundEnabled(true);
      playGreenAlert(); // confirmation that sound was enabled
    } catch { soundEnabledRef.current = false; setSoundEnabled(false); }
  };
  useEffect(() => () => { soundEnabledRef.current = false; void audioRef.current?.close(); }, []);

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
        if (active) {
          const greenNow = new Set<string>(payload.rows.filter((row: AnyObj) => row?.status === "BUY_CANDIDATE" && row?.readOnly === true && row?.orderSubmitted === false).map((row: AnyObj) => normaliseCryptoPair(row.symbol)));
          const previous = lastGreenRef.current;
          if (previous !== null && soundEnabledRef.current && [...greenNow].some(symbol => !previous.has(symbol))) playGreenAlert();
          lastGreenRef.current = greenNow;
          setBulkSignals(payload.rows);setBulkScannedAt(String(payload.scannedAt||""));setBulkError("");
        }
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
  const highlightedRebuyCoins = useMemo(() => bulkSignals.filter(row =>
    row?.status === "BUY_CANDIDATE" && row?.readOnly === true && row?.orderSubmitted === false ||
    row?.status === "WATCH" && row?.readOnly === true && row?.orderSubmitted === false
  ).sort((a,b) => {
    const statusOrder = (row: AnyObj) => row.status === "BUY_CANDIDATE" ? 0 : 1;
    if (statusOrder(a) !== statusOrder(b)) return statusOrder(a) - statusOrder(b);
    const strength = (row: AnyObj) => row.status === "BUY_CANDIDATE" && typeof row.recoveryStrengthPct === "number" && Number.isFinite(row.recoveryStrengthPct) ? row.recoveryStrengthPct : -Infinity;
    return strength(b) - strength(a);
  }), [bulkSignals]);
  const relevantRebuyCoins = highlightedRebuyCoins.map(row => normaliseCryptoPair(row.symbol));
  const visibleRebuyCoins = showAllRebuyCoins ? SMART_REBUY_PAIRS : SMART_REBUY_PAIRS.filter(pair => relevantRebuyCoins.includes(pair));

return <>
    <Card title="Smart Rebuy — Crypto Signals" wide>
      <div style={{padding:18,border:"1px solid #334155",borderRadius:14,background:"#1e293b"}}>
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",gap:12,flexWrap:"wrap"}}>
          <div><strong style={{fontSize:18}}>Smart Rebuy</strong><p style={{margin:"5px 0",color:"#cbd5e1"}}>Live Alpaca · Read-only · No automatic buys · Automatically scans 29 coins every 2 minutes · Manual decisions only</p><button type="button" className="ghost" aria-pressed={soundEnabled} onClick={()=>void enableSound()}>{soundEnabled ? "🔔 Green alerts ON" : "🔕 Enable green alert sound"}</button><small style={{display:"block",marginTop:5,color:"#cbd5e1"}}>Chimes when a coin turns green after the first scan. Keep this page open; iPhone may silence background tabs.</small></div>
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
          <p style={{color:"#cbd5e1",fontSize:12,margin:"0 0 8px"}}>Green coins ranked by verified recovery strength (highest first). Confidence describes how consistent the recent rise is; it is NOT a probability of profit or a buy instruction.</p>
          <div style={{display:"flex",flexWrap:"wrap",gap:8}}>
            {highlightedRebuyCoins.map((row,index) => <div key={row.symbol} style={{display:"flex",alignItems:"center",gap:6,padding:"4px 5px 4px 10px",borderRadius:9,border:"1px solid #475569",background:"#0f172a"}}>
              <button type="button" onClick={()=>{setSignalSymbol(normaliseCryptoPair(row.symbol));setSignal(row);}} style={{padding:"6px 2px",border:0,background:"transparent",color:"#f8fafc",cursor:"pointer"}}>
                <span style={{color:row.status==="BUY_CANDIDATE"?"#22c55e":"#f59e0b"}}>●</span> {row.symbol} · {row.status==="BUY_CANDIDATE"?"BUY candidate":"WATCH"}{row.dipPct!=null?` · ${row.dipPct}% dip`:""}{row.status==="BUY_CANDIDATE" && typeof row.recoveryStrengthPct==="number" ? ` · #${highlightedRebuyCoins.slice(0,index+1).filter(r=>r.status==="BUY_CANDIDATE" && typeof r.recoveryStrengthPct==="number").length} recovery +${row.recoveryStrengthPct.toFixed(2)}%` : ""}{row.status==="BUY_CANDIDATE" && row.recoveryConfidence?.label ? ` · ${row.recoveryConfidence.label} confidence (${row.recoveryConfidence.score}/100)` : ""}
              </button>
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

</>;
}
