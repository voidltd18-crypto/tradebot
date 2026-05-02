from __future__ import annotations
from datetime import datetime, UTC
from typing import Dict

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend import config
from backend.state.bot_state import EngineState, registry
from backend.strategies.sniper_strategy import SniperStrategy
from backend.engines.stock_engine import StockEngine
from backend.engines.crypto_engine import CryptoEngine
from backend.services.alpaca_service import AlpacaService
from backend.services.binance_service import BinanceService

app = FastAPI(title='Merged Tradebot Platform')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

engines: Dict[str, object] = {}

def verify_api_key(request: Request):
    if not config.DASHBOARD_API_KEY:
        return
    key = request.headers.get('x-api-key')
    if key != config.DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail='Unauthorized')

def setup_engines():
    strategy = SniperStrategy(config.FAST_STOP_LOSS_PCT, config.TRAIL_START_PCT, config.TRAIL_GIVEBACK_PCT)

    stock_state = EngineState('stocks', enabled=config.STOCK_ENABLED, dry_run=config.DRY_RUN)
    registry.add('stocks', stock_state)
    if config.STOCK_ENABLED:
        try:
            stock_service = AlpacaService(config.ALPACA_API_KEY, config.ALPACA_API_SECRET, config.ALPACA_PAPER)
            engines['stocks'] = StockEngine(stock_state, stock_service, strategy, config.CHECK_INTERVAL, config.DRY_RUN)
            stock_state.log('stock engine ready')
        except Exception as e:
            stock_state.last_error = str(e)
            stock_state.log(f'stock engine disabled: {e}')

    crypto_state = EngineState('crypto', enabled=config.CRYPTO_ENABLED, dry_run=config.DRY_RUN)
    registry.add('crypto', crypto_state)
    if config.CRYPTO_ENABLED:
        try:
            crypto_service = BinanceService(config.BINANCE_API_KEY, config.BINANCE_SECRET_KEY, config.BINANCE_TESTNET)
            engines['crypto'] = CryptoEngine(crypto_state, crypto_service, strategy, config.CHECK_INTERVAL, config.DRY_RUN)
            crypto_state.log('crypto engine ready')
        except Exception as e:
            crypto_state.last_error = str(e)
            crypto_state.log(f'crypto engine disabled: {e}')

@app.on_event('startup')
def startup():
    setup_engines()

@app.get('/')
def root():
    return {'ok': True, 'name': 'Merged Tradebot Platform', 'status': '/status', 'docs': '/docs'}

@app.get('/health')
def health():
    return {'ok': True, 'time': datetime.now(UTC).isoformat(), 'engines': list(registry.engines.keys())}

@app.get('/status')
def status():
    return {
        'ok': True,
        'time': datetime.now(UTC).isoformat(),
        'dryRun': config.DRY_RUN,
        'engines': registry.payload(),
        'safety': {
            'stockNoSameDaySells': config.STOCK_NO_SAME_DAY_SELLS,
            'binanceTestnet': config.BINANCE_TESTNET,
            'fastStopLossPct': config.FAST_STOP_LOSS_PCT,
            'trailStartPct': config.TRAIL_START_PCT,
            'trailGivebackPct': config.TRAIL_GIVEBACK_PCT,
        }
    }

@app.post('/engines/{engine_name}/start')
def start_engine(engine_name: str, request: Request):
    verify_api_key(request)
    engine = engines.get(engine_name)
    if not engine:
        raise HTTPException(status_code=404, detail=f'Engine not available: {engine_name}')
    engine.start()
    return {'ok': True, 'message': f'{engine_name} started'}

@app.post('/engines/{engine_name}/pause')
def pause_engine(engine_name: str, request: Request):
    verify_api_key(request)
    engine = engines.get(engine_name)
    if not engine:
        raise HTTPException(status_code=404, detail=f'Engine not available: {engine_name}')
    engine.pause()
    return {'ok': True, 'message': f'{engine_name} paused'}

@app.post('/engines/{engine_name}/stop')
def stop_engine(engine_name: str, request: Request):
    verify_api_key(request)
    engine = engines.get(engine_name)
    if not engine:
        raise HTTPException(status_code=404, detail=f'Engine not available: {engine_name}')
    engine.stop()
    return {'ok': True, 'message': f'{engine_name} stopped'}

@app.post('/start-all')
def start_all(request: Request):
    verify_api_key(request)
    started = []
    for name, engine in engines.items():
        engine.start()
        started.append(name)
    return {'ok': True, 'started': started}

@app.post('/pause-all')
def pause_all(request: Request):
    verify_api_key(request)
    paused = []
    for name, engine in engines.items():
        engine.pause()
        paused.append(name)
    return {'ok': True, 'paused': paused}
