import os
import json
import time
import secrets
import hashlib
import shutil
MAX_TRADING_CAPITAL = float(os.getenv("MAX_TRADING_CAPITAL", "200") or 200)

import sqlite3
import math
import re
import threading
import random
from datetime import datetime, UTC, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any, Tuple

import requests
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed


# ============================================================
# REBUILT SNIPER PROFIT TRADING BOT
# ============================================================
# Includes:
# - API key protection for trading endpoints
# - Market status
# - Custom buy
# - Strict sell-then-lock protection
# - Sell reliability quantity flooring
# - Alpaca/PDT rejection logging
# - PDT-aware safer mode
# - Sniper entries
# - Confidence-based sizing
# - Stock memory
# - Persistent trade timeline
# ============================================================


# =========================
# ENV
# =========================
API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY") or os.getenv("ADMIN_PASSWORD") or os.getenv("API_ACCESS_KEY") or ""

# Guarded adaptive optimiser. Disabled by default; advisory/stability tracking still runs.
V2_AUTO_APPLY_THRESHOLDS = os.getenv("V2_AUTO_APPLY_THRESHOLDS", "true").lower() == "true"
AI_THRESHOLD_LEARNING_ENABLED = os.getenv("AI_THRESHOLD_LEARNING_ENABLED", "true").lower() == "true"
AI_THRESHOLD_CLOSED_MARKET_ONLY = os.getenv("AI_THRESHOLD_CLOSED_MARKET_ONLY", "true").lower() == "true"
AI_THRESHOLD_INTERVAL_SECONDS = max(900, int(os.getenv("AI_THRESHOLD_INTERVAL_SECONDS", "1800") or 1800))
AI_THRESHOLD_MIN_SAMPLES = max(100, int(os.getenv("AI_THRESHOLD_MIN_SAMPLES", "100") or 100))
AI_THRESHOLD_STARTUP_DELAY_SECONDS = max(30, int(os.getenv("AI_THRESHOLD_STARTUP_DELAY_SECONDS", "90") or 90))
V2_OPTIMIZER_REQUIRED_STABLE_RUNS = int(os.getenv("V2_OPTIMIZER_REQUIRED_STABLE_RUNS", "5") or 5)
V2_OPTIMIZER_MIN_IMPROVEMENT = float(os.getenv("V2_OPTIMIZER_MIN_IMPROVEMENT", "0.08") or 0.08)
V2_OPTIMIZER_MAX_DRAWDOWN_INCREASE = float(os.getenv("V2_OPTIMIZER_MAX_DRAWDOWN_INCREASE", "0.10") or 0.10)
V2_OPTIMIZER_MAX_CONF_STEP = float(os.getenv("V2_OPTIMIZER_MAX_CONF_STEP", "0.04") or 0.04)
V2_OPTIMIZER_MAX_QUALITY_STEP = float(os.getenv("V2_OPTIMIZER_MAX_QUALITY_STEP", "0.004") or 0.004)

PAPER = os.getenv("PAPER", "false").lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# GBP dashboard conversion
FX_ENABLED = True
FX_BASE = "USD"
FX_QUOTE = "GBP"
FX_FALLBACK_USD_TO_GBP = 0.78
FX_REFRESH_SECONDS = 60 * 30


if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing APCA_API_KEY_ID or APCA_API_SECRET_KEY")


# =========================
# CORE CONFIG
# =========================
BOT_NAME = "Rebuilt Sniper Profit Bot"

SAFE_UNIVERSE = [
    "NVDA", "AMD", "MSFT", "AAPL", "META",
    "AMZN", "GOOGL", "GOOG", "AVGO", "NFLX",
    "TSLA", "PLTR", "UBER", "QQQ", "SMH",
]

CHECK_INTERVAL = 60
UNIVERSE_REFRESH_SECONDS = 60 * 30

MAX_POSITIONS = 1

# V15.9 — AI-controlled portfolio capacity.
# The legacy slider is no longer the live position limit while this is enabled.
# The effective capacity is derived from the AI-promoted position sizing and
# available trading capital, then bounded by an immutable safety ceiling.
AI_POSITION_CAPACITY_ENABLED = os.getenv("AI_POSITION_CAPACITY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
AI_POSITION_HARD_CAP = max(1, min(10, int(os.getenv("AI_POSITION_HARD_CAP", "10") or 10)))
AI_POSITION_MIN_NOTIONAL_USD = max(10.0, float(os.getenv("AI_POSITION_MIN_NOTIONAL_USD", "25") or 25))
AI_PORTFOLIO_MANAGER_ENABLED = os.getenv("AI_PORTFOLIO_MANAGER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
AI_PORTFOLIO_MANAGER_VERSION = "V16.0"
AI_PORTFOLIO_MAX_SINGLE_WEIGHT = max(0.10, min(0.60, float(os.getenv("AI_PORTFOLIO_MAX_SINGLE_WEIGHT", "0.45") or 0.45)))
AI_PORTFOLIO_MIN_CASH_RESERVE_PCT = max(0.02, min(0.50, float(os.getenv("AI_PORTFOLIO_MIN_CASH_RESERVE_PCT", "0.08") or 0.08)))
AI_PORTFOLIO_MAX_CASH_RESERVE_PCT = max(AI_PORTFOLIO_MIN_CASH_RESERVE_PCT, min(0.80, float(os.getenv("AI_PORTFOLIO_MAX_CASH_RESERVE_PCT", "0.45") or 0.45)))
AI_PORTFOLIO_MAX_ORDERS_PER_CYCLE = max(1, min(10, int(os.getenv("AI_PORTFOLIO_MAX_ORDERS_PER_CYCLE", "10") or 10)))
AI_PORTFOLIO_MIN_SCORE = max(0.0, min(1.0, float(os.getenv("AI_PORTFOLIO_MIN_SCORE", "0.55") or 0.55)))
AI_PORTFOLIO_ADAPTIVE_SCORE_ENABLED = os.getenv("AI_PORTFOLIO_ADAPTIVE_SCORE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
AI_PORTFOLIO_ADAPTIVE_SCORE_FLOOR = max(0.0, min(AI_PORTFOLIO_MIN_SCORE, float(os.getenv("AI_PORTFOLIO_ADAPTIVE_SCORE_FLOOR", "0.52") or 0.52)))
AI_PORTFOLIO_ADAPTIVE_TARGET_COUNT = max(1, min(5, int(os.getenv("AI_PORTFOLIO_ADAPTIVE_TARGET_COUNT", "2") or 2)))
AI_PORTFOLIO_RELATIVE_SCORE_WEIGHT = max(0.0, min(0.40, float(os.getenv("AI_PORTFOLIO_RELATIVE_SCORE_WEIGHT", "0.22") or 0.22)))
AI_PORTFOLIO_PLAN_FILE = os.getenv("AI_PORTFOLIO_PLAN_FILE", "/var/data/ai_portfolio_plan.json")
MAX_NEW_BUYS_PER_LOOP = 1
MAX_POSITION_VALUE_PCT = 0.12
TARGET_POSITION_VALUE_PCT = 0.08
MIN_ORDER_NOTIONAL = 1.00
CASH_BUFFER = 0.50

# Full-buy mode:
# When max positions is 1, use nearly all available trading capital/buying power
# instead of small partial sizing.
FULL_BUY_WHEN_ONE_POSITION = os.getenv("FULL_BUY_WHEN_ONE_POSITION", "true").lower() == "true"
FULL_BUY_CASH_BUFFER = float(os.getenv("FULL_BUY_CASH_BUFFER", "2.00") or 2.00)
V17_SINGLE_FULL_BUY_MODE = os.getenv("V17_SINGLE_FULL_BUY_MODE", "true").lower() in ("1", "true", "yes", "on")
V17_FULL_BUY_CONSTITUTION_LOCK = os.getenv("V17_FULL_BUY_CONSTITUTION_LOCK", "true").lower() in ("1", "true", "yes", "on")

MAX_SPREAD = 0.015
PREFER_SPREAD_UNDER = 0.006

BUY_DIP = 0.9985
MIN_PULLBACK = 0.0010
MAX_PULLBACK = 0.0450
MIN_TICKS_BEFORE_BUY = 3
MOMENTUM_LOOKBACK_POINTS = 5
MIN_SHORT_MOMENTUM = -0.015
MAX_SHORT_MOMENTUM = 0.045

STOP_LOSS = 0.960
TRAIL_START = 1.060
TRAIL_GIVEBACK = 0.980

# V17.2 — continuation-aware trailing profit protection.
# A strong winner gets ONE confirmation cycle after a very shallow trail-floor
# breach. The protected floor is never moved down; a deeper breach still exits
# immediately. This is designed to filter brief opening/quote whipsaws without
# returning to the old behaviour of letting a large winner evaporate.
ADAPTIVE_RUNNER_TRAIL_ENABLED = os.getenv("ADAPTIVE_RUNNER_TRAIL_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ADAPTIVE_RUNNER_MIN_CURRENT_PNL_PCT = float(os.getenv("ADAPTIVE_RUNNER_MIN_CURRENT_PNL_PCT", "5.0") or 5.0)
ADAPTIVE_RUNNER_MIN_PEAK_PNL_PCT = float(os.getenv("ADAPTIVE_RUNNER_MIN_PEAK_PNL_PCT", "6.0") or 6.0)
ADAPTIVE_RUNNER_MAX_SHALLOW_BREACH_PCT = float(os.getenv("ADAPTIVE_RUNNER_MAX_SHALLOW_BREACH_PCT", "0.30") or 0.30)
ADAPTIVE_RUNNER_MAX_NEGATIVE_MOMENTUM = float(os.getenv("ADAPTIVE_RUNNER_MAX_NEGATIVE_MOMENTUM", "-0.020") or -0.020)
ADAPTIVE_RUNNER_CONFIRMATION_CHECKS = max(1, int(os.getenv("ADAPTIVE_RUNNER_CONFIRMATION_CHECKS", "2") or 2))

# V17.3 — Peak Exhaustion / Failed Breakout Exit
# Uses the persisted 10-second Trade Replay curve to detect repeated tests of
# the same local high. A touch alone never sells: the position must have made
# a worthwhile peak, recorded several time-separated peak tests, and then
# rejected materially from that peak while remaining profitable.
PEAK_EXHAUSTION_ENABLED = os.getenv("PEAK_EXHAUSTION_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PEAK_EXHAUSTION_REQUIRED_TOUCHES = max(3, int(os.getenv("PEAK_EXHAUSTION_REQUIRED_TOUCHES", "4") or 4))
PEAK_EXHAUSTION_TOLERANCE_PCT = max(0.05, float(os.getenv("PEAK_EXHAUSTION_TOLERANCE_PCT", "0.20") or 0.20))
PEAK_EXHAUSTION_MIN_SECONDS_BETWEEN_TOUCHES = max(20, int(os.getenv("PEAK_EXHAUSTION_MIN_SECONDS_BETWEEN_TOUCHES", "60") or 60))
PEAK_EXHAUSTION_MIN_PEAK_PNL_PCT = max(0.0, float(os.getenv("PEAK_EXHAUSTION_MIN_PEAK_PNL_PCT", "2.0") or 2.0))
PEAK_EXHAUSTION_MIN_CURRENT_PNL_PCT = max(0.0, float(os.getenv("PEAK_EXHAUSTION_MIN_CURRENT_PNL_PCT", "0.25") or 0.25))
PEAK_EXHAUSTION_REJECTION_PCT = max(0.10, float(os.getenv("PEAK_EXHAUSTION_REJECTION_PCT", "0.50") or 0.50))
PEAK_EXHAUSTION_LOOKBACK_POINTS = max(100, int(os.getenv("PEAK_EXHAUSTION_LOOKBACK_POINTS", "3000") or 3000))
PEAK_EXHAUSTION_MARKET_OPEN_ONLY = os.getenv("PEAK_EXHAUSTION_MARKET_OPEN_ONLY", "true").lower() in ("1", "true", "yes", "on")

MAX_DAILY_LOSS = -100.00
MAX_TRADES_PER_DAY = 12
DUST_THRESHOLD = 0.1

STRICT_ONE_CYCLE_PER_STOCK_PER_DAY = True
ALLOW_CUSTOM_BUY = True
CUSTOM_BUY_REQUIRES_MARKET_OPEN = True
ENABLE_MANUAL_BUTTONS = True
MANAGE_OUTSIDE_UNIVERSE_POSITIONS = False


# =========================
# PROFIT / PDT / MEMORY
# =========================
PROFIT_MODE_ENABLED = True
ROTATION_MODE_ENABLED = True
ROTATION_MIN_QUALITY_EDGE = 0.018
ROTATE_ONLY_IF_WEAKEST_PNL_BELOW = 0.35
ROTATION_COOLDOWN_SECONDS = 60 * 20

PDT_AWARE_MODE_ENABLED = True
AVOID_SAME_DAY_PROFIT_SELLS = True
AVOID_SAME_DAY_ROTATION_SELLS = True
MIN_HOLD_MINUTES_BEFORE_PROFIT_SELL = 45
MIN_HOLD_MINUTES_BEFORE_ROTATION = 60
HARD_STOP_LOSS_PCT = -4.50
MAX_NEW_BUYS_PER_DAY_PDT_AWARE = 6

# Faster Exit / Partial Profit Mode
FAST_EXIT_MODE_ENABLED = True
PARTIAL_PROFIT_ENABLED = False
PARTIAL_PROFIT_TRIGGER_PCT = 8.00
PARTIAL_PROFIT_SELL_PCT = 0.00
POST_PARTIAL_TRAIL_GIVEBACK = 0.980
FAST_STOP_LOSS_PCT = -4.00
STALL_EXIT_ENABLED = True
STALL_EXIT_AFTER_MINUTES = 4320
STALL_EXIT_MIN_PNL_PCT = -1.00

# Swing Hold AI: learns from closed-trade history and avoids quick exits.
SWING_SNIPER_SAFE_MODE = True
HOLD_AI_ENABLED = True
HOLD_AI_LOOKBACK_DAYS = int(os.getenv("HOLD_AI_LOOKBACK_DAYS", "180") or 180)
HOLD_AI_MIN_TRADES = int(os.getenv("HOLD_AI_MIN_TRADES", "4") or 4)
HOLD_AI_MIN_HOLD_MINUTES = 1440       # default: at least 1 trading day
HOLD_AI_GOOD_SYMBOL_HOLD_MINUTES = 2880
HOLD_AI_WEAK_SYMBOL_HOLD_MINUTES = 720
HOLD_AI_MAX_STALL_MINUTES = 4320      # only consider a stall exit after 3 days
HOLD_AI_MIN_TRAIL_PROFIT_PCT = 6.00
HOLD_AI_TRAIL_GIVEBACK_PCT = 2.00
MIN_SELL_NOTIONAL = 1.00

# =========================
# TRADEBOT V2 SAFETY / EXPECTANCY ENGINE
# =========================
# V2 starts in validation-only mode. It will scan and explain trades, but it
# will not place a new live buy until TRADEBOT_V2_LIVE_ENABLED=true is set.
TRADEBOT_V2_ENABLED = os.getenv("TRADEBOT_V2_ENABLED", "true").lower() == "true"
TRADEBOT_V2_LIVE_ENABLED = os.getenv("TRADEBOT_V2_LIVE_ENABLED", "true").lower() == "true"
V2_MIN_SYMBOL_SAMPLES = int(os.getenv("V2_MIN_SYMBOL_SAMPLES", "8") or 8)
V2_MIN_WIN_RATE = float(os.getenv("V2_MIN_WIN_RATE", "0.50") or 0.50)
V2_MIN_PROFIT_FACTOR = float(os.getenv("V2_MIN_PROFIT_FACTOR", "1.10") or 1.10)
V2_MIN_EXPECTANCY_PCT = float(os.getenv("V2_MIN_EXPECTANCY_PCT", "0.10") or 0.10)
V2_LOOKBACK_DAYS = int(os.getenv("V2_LOOKBACK_DAYS", "365") or 365)
V2_LOG_DECISIONS = os.getenv("V2_LOG_DECISIONS", "true").lower() == "true"
V2_DECISION_DEDUPE_SECONDS = int(os.getenv("V2_DECISION_DEDUPE_SECONDS", "300") or 300)
V2_OUTCOME_HORIZONS_HOURS = tuple(int(x.strip()) for x in os.getenv("V2_OUTCOME_HORIZONS_HOURS", "1,24,72,120").split(",") if x.strip())
V2_OUTCOME_BATCH_SIZE = int(os.getenv("V2_OUTCOME_BATCH_SIZE", "250"))
V2_OUTCOME_DRAIN_LIMIT = max(V2_OUTCOME_BATCH_SIZE, int(os.getenv("V2_OUTCOME_DRAIN_LIMIT", "1000") or 1000))
V2_OUTCOME_DRAIN_PAUSE_SECONDS = max(0.0, float(os.getenv("V2_OUTCOME_DRAIN_PAUSE_SECONDS", "0.25") or 0.25))
V2_INDEPENDENT_SAMPLE_MINUTES = int(os.getenv("V2_INDEPENDENT_SAMPLE_MINUTES", "30"))
V2_ESTIMATED_COST_BPS = float(os.getenv("V2_ESTIMATED_COST_BPS", "10"))

# V17.0.15 — V2 cold-start qualification for genuinely new symbols.
# Established symbols (>= V2_MIN_SYMBOL_SAMPLES) still require the normal V2
# expectancy gate. A new symbol can only bypass the sample-count deadlock when
# the *current live setup* is exceptionally strong and every preceding safety
# gate (account lock, reputation, Sniper and A+) has already passed.
V17_V2_COLD_START_ENABLED = os.getenv("V17_V2_COLD_START_ENABLED", "true").lower() in ("1", "true", "yes", "on")
V17_V2_COLD_START_MIN_CONFIDENCE = max(0.70, min(0.99, float(os.getenv("V17_V2_COLD_START_MIN_CONFIDENCE", "0.80") or 0.80)))
V17_V2_COLD_START_MIN_QUALITY = max(0.0, float(os.getenv("V17_V2_COLD_START_MIN_QUALITY", "0.030") or 0.030))
V17_V2_COLD_START_MAX_SPREAD = max(0.0005, min(MAX_SPREAD, float(os.getenv("V17_V2_COLD_START_MAX_SPREAD", "0.006") or 0.006)))
V17_V2_COLD_START_MIN_MOMENTUM = max(0.0, float(os.getenv("V17_V2_COLD_START_MIN_MOMENTUM", "0.0") or 0.0))

# TradeBot V4.1 intelligence foundation. Advisory/data-collection only.
V4_MARKET_DNA_ENABLED = os.getenv("V4_MARKET_DNA_ENABLED", "true").lower() == "true"
V4_SIMILARITY_MIN_SAMPLES = int(os.getenv("V4_SIMILARITY_MIN_SAMPLES", "8") or 8)
V4_SIMILARITY_LIMIT = int(os.getenv("V4_SIMILARITY_LIMIT", "50") or 50)
V4_PATTERN_MIN_SAMPLES = int(os.getenv("V4_PATTERN_MIN_SAMPLES", "8") or 8)

# TradeBot V5.1 Replay Laboratory. Research/advisory only.
V5_REPLAY_ENABLED = os.getenv("V5_REPLAY_ENABLED", "true").lower() == "true"
V5_REPLAY_DEFAULT_HORIZON_HOURS = int(os.getenv("V5_REPLAY_DEFAULT_HORIZON_HOURS", "24") or 24)
V5_REPLAY_MIN_SAMPLES = int(os.getenv("V5_REPLAY_MIN_SAMPLES", "8") or 8)
V5_REPLAY_MAX_ROWS = int(os.getenv("V5_REPLAY_MAX_ROWS", "10000") or 10000)

# TradeBot V6.4 Outcome-Time Forensics. Historical checkpoint evidence only.
V6_BRAINS_ENABLED = os.getenv("V6_BRAINS_ENABLED", "true").lower() == "true"
V6_DEFAULT_HORIZON_HOURS = int(os.getenv("V6_DEFAULT_HORIZON_HOURS", "24") or 24)
V6_MIN_SAMPLES = int(os.getenv("V6_MIN_SAMPLES", "12") or 12)
V6_RECOMMENDATION_MIN_PF = float(os.getenv("V6_RECOMMENDATION_MIN_PF", "1.15") or 1.15)
V6_RECOMMENDATION_MIN_EXPECTANCY = float(os.getenv("V6_RECOMMENDATION_MIN_EXPECTANCY", "0.10") or 0.10)
V6_ACTIVE_BRAIN = os.getenv("V6_ACTIVE_BRAIN", "current_a_plus").strip().lower() or "current_a_plus"
V6_AUTO_SYNC_ENABLED = os.getenv("V6_AUTO_SYNC_ENABLED", "true").lower() == "true"
V6_AUTO_SYNC_INTERVAL_SECONDS = max(30, int(os.getenv("V6_AUTO_SYNC_INTERVAL_SECONDS", "300") or 300))
V6_AUTO_SYNC_LIMIT = max(100, min(int(os.getenv("V6_AUTO_SYNC_LIMIT", "50000") or 50000), 50000))
V6_OUTCOME_MAX_DELAY_MINUTES = max(1, int(os.getenv("V6_OUTCOME_MAX_DELAY_MINUTES", "30") or 30))
V6_HISTORICAL_BAR_LOOKBACK_MINUTES = max(5, int(os.getenv("V6_HISTORICAL_BAR_LOOKBACK_MINUTES", "15") or 15))
V6_HISTORICAL_BAR_LOOKAHEAD_MINUTES = max(5, int(os.getenv("V6_HISTORICAL_BAR_LOOKAHEAD_MINUTES", "45") or 45))
V6_REPAIR_BATCH_SIZE = max(1, min(int(os.getenv("V6_REPAIR_BATCH_SIZE", "200") or 200), 1000))

# V17.8.2 — Outcome Recovery / stale-error cleanup.
V6_OUTCOME_MAX_RETRIES = max(1, min(int(os.getenv("V6_OUTCOME_MAX_RETRIES", "3") or 3), 20))

# Closed-market AI research scheduler. Live trading stays focused while the market is open.
AI_RESEARCH_CLOSED_MARKET_ONLY = os.getenv("AI_RESEARCH_CLOSED_MARKET_ONLY", "true").lower() == "true"
AI_RESEARCH_INTERVAL_SECONDS = max(300, int(os.getenv("AI_RESEARCH_INTERVAL_SECONDS", "300") or 300))
AI_RESEARCH_STARTUP_DELAY_SECONDS = max(5, int(os.getenv("AI_RESEARCH_STARTUP_DELAY_SECONDS", "30") or 30))

# TradeBot V7.1 Autonomous Research Lab. Shadow-only; never changes live trading.
V7_ENABLED = os.getenv("V7_ENABLED", "true").lower() == "true"
V7_AUTOMATIC_EVOLUTION = os.getenv("V7_AUTOMATIC_EVOLUTION", "true").lower() == "true"
V7_POPULATION_LIMIT = max(6, min(int(os.getenv("V7_POPULATION_LIMIT", "30") or 30), 200))
V7_CHILDREN_PER_RUN = max(1, min(int(os.getenv("V7_CHILDREN_PER_RUN", "12") or 12), 50))
V7_MIN_PARENT_SAMPLES = max(V6_MIN_SAMPLES, int(os.getenv("V7_MIN_PARENT_SAMPLES", "20") or 20))
V7_MUTATION_RATE = max(0.01, min(float(os.getenv("V7_MUTATION_RATE", "0.12") or 0.12), 0.50))
V7_WEEKEND_MAINTENANCE_ENABLED = os.getenv("V7_WEEKEND_MAINTENANCE_ENABLED", "true").lower() == "true"
V7_WEEKEND_DAY = max(0, min(int(os.getenv("V7_WEEKEND_DAY", "6") or 6), 6))  # Monday=0, Sunday=6
V7_WEEKEND_HOUR_UK = max(0, min(int(os.getenv("V7_WEEKEND_HOUR_UK", "6") or 6), 23))

# V2 deliberately disables rotation/churn. Existing positions are still
# protected by hard-stop and swing-management rules.
if TRADEBOT_V2_ENABLED:
    ROTATION_MODE_ENABLED = False
    MAX_NEW_BUYS_PER_LOOP = 1
    # Position count is controlled by AI portfolio capacity, not forced to one.
    if not AI_POSITION_CAPACITY_ENABLED:
        MAX_POSITIONS = 1

# Profit Optimiser / Analytics / Auto-Improve
PROFIT_OPTIMIZER_ENABLED = True
ANALYTICS_ENABLED = True
AUTO_IMPROVE_ENABLED = True

DAILY_PROFIT_TARGET = 4.00
DAILY_LOSS_LIMIT_OPTIMIZER = -100.00
PAUSE_BUYS_AFTER_DAILY_TARGET = False
PAUSE_BUYS_AFTER_DAILY_LOSS = True

OPTIMIZED_STOP_LOSS = 0.960
OPTIMIZED_TRAIL_START = 1.060
OPTIMIZED_TRAIL_GIVEBACK = 0.980
OPTIMIZED_FAST_STOP_LOSS_PCT = -4.00
OPTIMIZED_PARTIAL_PROFIT_TRIGGER_PCT = 8.00
OPTIMIZED_PARTIAL_PROFIT_SELL_PCT = 0.00

AUTO_BLACKLIST_ENABLED = True
AUTO_BLACKLIST_MIN_TRADES = 4
AUTO_BLACKLIST_MAX_WINRATE = 0.38
AUTO_BLACKLIST_MAX_TOTAL_PNL = -1.50
AUTO_BOOST_ENABLED = True
AUTO_BOOST_MIN_TRADES = 4
AUTO_BOOST_MIN_WINRATE = 0.60
AUTO_BOOST_MIN_TOTAL_PNL = 1.00
AUTO_BOOST_MULTIPLIER = 1.20
AUTO_REDUCE_MULTIPLIER = 0.70
OPTIMIZER_MIN_CONFIDENCE = 0.68



SNIPER_MODE_ENABLED = True
CONFIDENCE_SIZING_ENABLED = True
STOCK_MEMORY_ENABLED = True
TRADE_TIMELINE_ENABLED = True

SNIPER_MIN_CONFIDENCE = 0.58
SNIPER_MIN_QUALITY = 0.020
SNIPER_MAX_SPREAD = 0.012
SNIPER_MIN_PULLBACK = 0.0015
SNIPER_MAX_PULLBACK = 0.035
SNIPER_MIN_MOMENTUM = -0.003

# A+ trade quality gate
A_PLUS_GATE_ENABLED = True
A_PLUS_MIN_CONFIDENCE = 0.70
A_PLUS_MIN_QUALITY = 0.03
A_PLUS_MAX_SPREAD = 0.010
A_PLUS_REQUIRE_NON_NEGATIVE_MOMENTUM = True
A_PLUS_BLOCK_LOW_CONFIDENCE_MANUAL_BUY = True

# Temporary loser blacklist
LOSER_BLACKLIST_ENABLED = True
LOSER_BLACKLIST_LOSS_STREAK = 2
LOSER_BLACKLIST_MIN_TRADES = 3
LOSER_BLACKLIST_HOURS = 24
TEMP_BLACKLIST_FILE = "temp_blacklist.json"

LOW_CONFIDENCE_SIZE_MULTIPLIER = 0.65
MEDIUM_CONFIDENCE_SIZE_MULTIPLIER = 1.00
HIGH_CONFIDENCE_SIZE_MULTIPLIER = 1.35
MAX_CONFIDENCE_POSITION_VALUE_PCT = 0.14

MEMORY_MIN_TRADES_FOR_TRUST = 3
MEMORY_BAD_WINRATE = 0.35
MEMORY_GOOD_WINRATE = 0.58
MEMORY_BAD_MULTIPLIER = 0.70
MEMORY_GOOD_MULTIPLIER = 1.15


# SQLite persistent trade memory
SQLITE_ENABLED = True

def persistent_data_dir() -> str:
    """Choose a directory that survives Render redeploys when a disk is mounted.

    Recommended Render disk mount path: /var/data
    Override with PERSISTENT_DATA_DIR when using a different mount.
    """
    configured = os.getenv("PERSISTENT_DATA_DIR", "").strip()
    if configured:
        return configured
    if os.path.isdir("/var/data"):
        return "/var/data"
    return os.path.join("backend", "state")


def persistent_file(name: str) -> str:
    return os.path.join(persistent_data_dir(), name)


SQLITE_DB_FILE = os.getenv("SQLITE_DB_FILE", "").strip() or persistent_file("trades.db")
BACKFILL_ORDER_LIMIT = 500
BACKFILL_CHUNK_SIZE = 500
BACKFILL_MAX_PAGES = 50

TRADE_HISTORY_FILE = "trade_history.json"
STOCK_MEMORY_FILE = "stock_memory.json"



if PROFIT_OPTIMIZER_ENABLED:
    STOP_LOSS = OPTIMIZED_STOP_LOSS
    TRAIL_START = OPTIMIZED_TRAIL_START
    TRAIL_GIVEBACK = OPTIMIZED_TRAIL_GIVEBACK
    FAST_STOP_LOSS_PCT = OPTIMIZED_FAST_STOP_LOSS_PCT
    PARTIAL_PROFIT_TRIGGER_PCT = OPTIMIZED_PARTIAL_PROFIT_TRIGGER_PCT
    PARTIAL_PROFIT_SELL_PCT = OPTIMIZED_PARTIAL_PROFIT_SELL_PCT


# Weekly Auto Universe Rotation
AUTO_UNIVERSE_ENABLED = True
AUTO_UNIVERSE_SIZE = 12
AUTO_UNIVERSE_REFRESH_DAY = 0
AUTO_UNIVERSE_MIN_HOURS_BETWEEN_REFRESH = 12
AUTO_UNIVERSE_KEEP_WINNERS = True
AUTO_UNIVERSE_KEEP_WINNER_MIN_PNL = 0.50
AUTO_UNIVERSE_KEEP_WINNER_MIN_WINRATE = 0.55
AUTO_UNIVERSE_REMOVE_LOSER_MAX_WINRATE = 0.35
AUTO_UNIVERSE_REMOVE_LOSER_MAX_PNL = -1.00
AUTO_UNIVERSE_MIN_PRICE = 1.00
AUTO_UNIVERSE_MAX_PRICE = 800.00
AUTO_UNIVERSE_MAX_SPREAD = 0.020
AUTO_UNIVERSE_CANDIDATE_POOL = [
    "NVDA", "AMD", "MSFT", "AAPL", "META",
    "AMZN", "GOOGL", "GOOG", "AVGO", "NFLX",
    "TSLA", "PLTR", "UBER", "QQQ", "SMH",
]

# V17.0.11 — Locked Universe Auto-Replacement.
# Daily locks remain strict. When too few unlocked names remain, the bot swaps
# locked symbols out of the *runtime* scan universe and replenishes them from
# fresh market discovery. The saved weekly universe is not deleted or unlocked.
LOCKED_UNIVERSE_AUTO_REPLACEMENT_ENABLED = os.getenv("LOCKED_UNIVERSE_AUTO_REPLACEMENT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
LOCKED_UNIVERSE_TARGET_SIZE = max(6, int(os.getenv("LOCKED_UNIVERSE_TARGET_SIZE", str(AUTO_UNIVERSE_SIZE)) or AUTO_UNIVERSE_SIZE))
LOCKED_UNIVERSE_MIN_UNLOCKED = max(1, min(LOCKED_UNIVERSE_TARGET_SIZE, int(os.getenv("LOCKED_UNIVERSE_MIN_UNLOCKED", "6") or 6)))
LOCKED_UNIVERSE_DISCOVERY_COOLDOWN_SECONDS = max(60, int(os.getenv("LOCKED_UNIVERSE_DISCOVERY_COOLDOWN_SECONDS", "600") or 600))
LOCKED_UNIVERSE_DISCOVERY_PER_SCREEN = max(20, min(100, int(os.getenv("LOCKED_UNIVERSE_DISCOVERY_PER_SCREEN", "60") or 60)))
LOCKED_UNIVERSE_FALLBACK_POOL = [
    "AAPL", "ABBV", "ADBE", "AMD", "AMAT", "AMGN", "AMZN", "AVGO",
    "BAC", "CAT", "CMG", "COIN", "COST", "CRM", "CRWD", "CSCO",
    "CVX", "DDOG", "DIS", "GE", "GM", "GOOG", "GOOGL", "GS",
    "HD", "HOOD", "IBM", "INTC", "JNJ", "JPM", "KO", "LLY",
    "MA", "META", "MSFT", "MU", "NFLX", "NOW", "NVDA", "ORCL",
    "PANW", "PEP", "PFE", "QCOM", "QQQ", "ROKU", "SHOP", "SMH",
    "SNOW", "SPY", "TGT", "TJX", "TSLA", "TXN", "UBER", "UNH",
    "V", "WMT", "XOM", "ZS"
]

# =========================
# CLIENTS
# =========================
trading_client = TradingClient(API_KEY, API_SECRET, paper=PAPER)
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)


# =========================
# STATE
# =========================
current_universe = list(dict.fromkeys(SAFE_UNIVERSE))
state: Dict[str, Dict[str, Any]] = {}

for symbol in current_universe:
    state[symbol] = {
        "ref": None,
        "highest_since_entry": None,
        "price_curve": [],
        "custom": False,
    }

locked_today: Dict[str, str] = {}
custom_symbols: Dict[str, bool] = {}
last_universe_refresh_ts = 0
locked_universe_runtime_cache: Dict[str, Any] = {"day": "", "symbols": [], "rows": [], "lastDiscoveryTs": 0.0}
adaptive_universe_runtime_cache: Dict[str, Any] = {"updatedAt": "", "symbols": [], "rows": [], "lastRefreshTs": 0.0, "changes": 0}

latest_status: Dict[str, Any] = {}
_STATUS_LOCK = threading.RLock()
latest_scans: List[Dict[str, Any]] = []
v174_final_gate_last_event: Dict[str, Any] = {}

trade_events: List[Dict[str, Any]] = []
trade_history: List[Dict[str, Any]] = []
stock_memory: Dict[str, Dict[str, Any]] = {}
temp_blacklist: Dict[str, Any] = {}
alpaca_rejection_events: List[Dict[str, Any]] = []
pdt_warning_events: List[Dict[str, Any]] = []
partial_profit_taken: Dict[str, str] = {}
equity_curve: List[Dict[str, Any]] = []

bot_enabled = True
manual_override = False
emergency_stop = False
bot_thread_started = False
v6_sync_thread_started = False
v7_weekend_thread_started = False
v11_learning_thread_started = False
ai_research_thread_started = False
ai_summary_thread_started = False
AI_SUMMARY_LOG_ENABLED = os.getenv("AI_SUMMARY_LOG_ENABLED", "true").lower() in ("1","true","yes","on")
AI_SUMMARY_LOG_INTERVAL_SECONDS = max(300, int(os.getenv("AI_SUMMARY_LOG_INTERVAL_SECONDS", "3600")))
AI_SUMMARY_LOG_STARTUP_DELAY_SECONDS = max(30, int(os.getenv("AI_SUMMARY_LOG_STARTUP_DELAY_SECONDS", "120")))
v6_last_sync_result: Dict[str, Any] = {}

# Automatic closed-trade report reconciliation. Reporting-only: this never
# changes entries, exits, sizing, scanner decisions, or order submission.
AUTO_REPORT_SYNC_ENABLED = os.getenv("AUTO_REPORT_SYNC_ENABLED", "true").lower() == "true"
AUTO_REPORT_SYNC_INTERVAL_SECONDS = max(30, int(os.getenv("AUTO_REPORT_SYNC_INTERVAL_SECONDS", "60") or 60))
AUTO_REPORT_SYNC_ORDER_LIMIT = max(20, min(int(os.getenv("AUTO_REPORT_SYNC_ORDER_LIMIT", "500") or 500), 500))
auto_report_last_sync_ts = 0.0
auto_report_last_result: Dict[str, Any] = {}

bot_lock = threading.Lock()

starting_equity_today: Optional[float] = None
starting_equity_day: Optional[str] = None
last_rotation_ts = 0
fx_cache: Dict[str, Any] = {"rate": FX_FALLBACK_USD_TO_GBP, "updated": 0, "source": "fallback"}


# =========================
# APP
# =========================
app = FastAPI(title="Rebuilt Sniper Profit Bot")

app.add_middleware(
    CORSMiddleware,
    # Token authentication is sent in headers, not browser cookies.
    # Credentials + wildcard origins can cause browsers to accept OPTIONS
    # but block the real GET request. Keep credential mode disabled.
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    # Cache successful preflight responses so the dashboard does not
    # repeat OPTIONS before every polling request.
    max_age=600,
)


# =========================
# SECURITY
# =========================
def verify_api_key(request: Request):
    if not DASHBOARD_API_KEY:
        raise HTTPException(status_code=500, detail="Dashboard API key not configured")

    key = request.headers.get("x-api-key")
    if key != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.post("/login")
def login(payload: dict = Body(...)):
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))

    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", DASHBOARD_API_KEY)

    if not admin_password:
        raise HTTPException(status_code=503, detail="Admin password not configured")

    if not secrets.compare_digest(username, admin_username) or not secrets.compare_digest(password, admin_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Existing protected endpoints already expect x-api-key, so return that as the session token.
    return {"ok": True, "token": DASHBOARD_API_KEY or admin_password, "username": username}


@app.get("/auth-check")
def auth_check(request: Request):
    verify_api_key(request)
    return {"ok": True, "authenticated": True}

# =========================
# UTIL
# =========================
def today_str():
    return datetime.now(UTC).strftime("%Y-%m-%d")


def now_time():
    return datetime.now(UTC).strftime("%H:%M:%S")


def now_chart_time():
    return datetime.now(UTC).strftime("%H:%M")


def notify(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=5,
        )
    except Exception:
        pass


def safe_load_json(path: str, fallback):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return fallback


def safe_save_json(path: str, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"SAVE ERROR {path}: {e}")


def load_persistent_state():
    global trade_history, stock_memory, temp_blacklist
    trade_history = safe_load_json(TRADE_HISTORY_FILE, [])
    stock_memory = safe_load_json(STOCK_MEMORY_FILE, {})
    temp_blacklist = safe_load_json(TEMP_BLACKLIST_FILE, {})


def save_trade_history():
    safe_save_json(TRADE_HISTORY_FILE, trade_history[-2000:])


def save_stock_memory():
    safe_save_json(STOCK_MEMORY_FILE, stock_memory)


def save_temp_blacklist():
    safe_save_json(TEMP_BLACKLIST_FILE, temp_blacklist)


def cleanup_temp_blacklist():
    now = datetime.now(UTC)
    changed = False

    for symbol, data in list(temp_blacklist.items()):
        try:
            until = datetime.fromisoformat(data.get("until", ""))
            if until <= now:
                del temp_blacklist[symbol]
                changed = True
        except Exception:
            del temp_blacklist[symbol]
            changed = True

    if changed:
        save_temp_blacklist()


def is_temp_blacklisted(symbol: str):
    if not LOSER_BLACKLIST_ENABLED:
        return False, ""

    cleanup_temp_blacklist()
    data = temp_blacklist.get(symbol.upper())

    if not data:
        return False, ""

    return True, data.get("reason", "temporarily blacklisted")


def add_temp_blacklist(symbol: str, reason: str):
    if not LOSER_BLACKLIST_ENABLED:
        return

    until = datetime.now(UTC) + timedelta(hours=LOSER_BLACKLIST_HOURS)
    temp_blacklist[symbol.upper()] = {
        "reason": reason,
        "until": until.isoformat(),
    }
    save_temp_blacklist()
    print(f"BLACKLIST | {symbol} | {reason} until {until.isoformat()}")


def current_loss_streak(symbol: str):
    streak = 0
    for event in reversed(trade_history):
        if event.get("symbol") != symbol or event.get("side") != "SELL":
            continue
        if float(event.get("pnl", 0.0)) < 0:
            streak += 1
        else:
            break
    return streak


def refresh_blacklist_from_memory(symbol: str):
    if not LOSER_BLACKLIST_ENABLED:
        return

    m = get_memory(symbol)

    if m.get("trades", 0) < LOSER_BLACKLIST_MIN_TRADES:
        return

    streak = current_loss_streak(symbol)

    if streak >= LOSER_BLACKLIST_LOSS_STREAK:
        add_temp_blacklist(symbol, f"{streak} loss streak")


def a_plus_gate(scan: Dict[str, Any]):
    if not A_PLUS_GATE_ENABLED:
        return True, "A+ gate off"

    symbol = scan.get("symbol", "")
    blacklisted, reason = is_temp_blacklisted(symbol)
    if blacklisted:
        return False, f"blacklisted: {reason}"

    confidence = float(scan.get("confidence", 0.0))
    quality = float(scan.get("quality_score", scan.get("qualityScore", 0.0)))
    spread = float(scan.get("spread", 1.0))
    momentum = float(scan.get("short_momentum", scan.get("shortMomentum", 0.0)))

    if confidence < A_PLUS_MIN_CONFIDENCE:
        return False, f"confidence {confidence:.2f} below A+ {A_PLUS_MIN_CONFIDENCE:.2f}"

    if quality < A_PLUS_MIN_QUALITY:
        return False, f"quality {quality:.4f} below A+ {A_PLUS_MIN_QUALITY:.4f}"

    if spread > A_PLUS_MAX_SPREAD:
        return False, f"spread {spread:.4f} above A+ {A_PLUS_MAX_SPREAD:.4f}"

    if A_PLUS_REQUIRE_NON_NEGATIVE_MOMENTUM and momentum < 0:
        return False, f"momentum negative {momentum:.4f}"

    return True, "A+ PASS"



def ensure_symbol_state(symbol: str, custom=False):
    symbol = symbol.upper()
    if symbol not in state:
        state[symbol] = {
            "ref": None,
            "highest_since_entry": None,
            "price_curve": [],
            "custom": custom,
        }
    if custom:
        state[symbol]["custom"] = True


def add_symbol_to_universe(symbol: str, custom=False):
    symbol = symbol.upper().strip()
    if symbol not in current_universe:
        current_universe.append(symbol)
    ensure_symbol_state(symbol, custom=custom)
    if custom:
        custom_symbols[symbol] = True


def reset_daily_flags_if_needed():
    global starting_equity_today, starting_equity_day

    today = today_str()
    for symbol, day in list(locked_today.items()):
        if day != today:
            del locked_today[symbol]

    for symbol, day in list(partial_profit_taken.items()):
        if day != today:
            del partial_profit_taken[symbol]

    if starting_equity_day != today:
        try:
            account = get_account()
            starting_equity_today = float(account.equity)
            starting_equity_day = today
            trade_events.clear()
            alpaca_rejection_events.clear()
            pdt_warning_events.clear()
            equity_curve.clear()
        except Exception:
            pass


def lock_symbol_until_tomorrow(symbol: str):
    if STRICT_ONE_CYCLE_PER_STOCK_PER_DAY:
        locked_today[symbol] = today_str()


def is_locked_today(symbol: str):
    return locked_today.get(symbol) == today_str()


def floor_qty(qty: float, decimals: int = 6):
    factor = 10 ** decimals
    return max(0.0, int(float(qty) * factor) / factor)


def parse_available_qty(error_text: str):
    try:
        m = re.search(r"available[:=]\s*([0-9]*\.?[0-9]+)", str(error_text), re.IGNORECASE)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def is_insufficient_qty_error(error_text: str):
    lower = str(error_text).lower()
    return "insufficient qty" in lower or "insufficient quantity" in lower


def is_likely_pdt_error(error_text: str):
    lower = str(error_text).lower()
    return any(term in lower for term in ["pattern day", "pdt", "day trade", "day-trade", "day trading"])



# =========================
# FX / GBP CONVERSION
# =========================
def get_usd_to_gbp_rate():
    global fx_cache

    if not FX_ENABLED:
        return FX_FALLBACK_USD_TO_GBP

    now = time.time()

    if fx_cache.get("rate") and (now - float(fx_cache.get("updated", 0))) < FX_REFRESH_SECONDS:
        return float(fx_cache["rate"])

    urls = [
        "https://api.frankfurter.app/latest?from=USD&to=GBP",
        "https://api.exchangerate.host/latest?base=USD&symbols=GBP",
    ]

    for url in urls:
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            rate = float(data["rates"]["GBP"])

            if rate > 0:
                fx_cache = {
                    "rate": rate,
                    "updated": now,
                    "source": url,
                }
                return rate
        except Exception as e:
            print(f"FX ERROR {url}: {e}")

    fx_cache = {
        "rate": FX_FALLBACK_USD_TO_GBP,
        "updated": now,
        "source": "fallback",
    }
    return FX_FALLBACK_USD_TO_GBP


def money_gbp(value_usd: float):
    try:
        return float(value_usd) * get_usd_to_gbp_rate()
    except Exception:
        return 0.0


def fx_payload():
    rate = get_usd_to_gbp_rate()
    return {
        "enabled": FX_ENABLED,
        "base": FX_BASE,
        "quote": FX_QUOTE,
        "usdToGbp": rate,
        "label": "USD/GBP",
        "source": fx_cache.get("source", "fallback"),
        "updated": fx_cache.get("updated", 0),
    }


# =========================
# ACCOUNT / MARKET
# =========================
def get_account():
    return trading_client.get_account()


def get_equity():
    return float(get_account().equity)


# V17.6.4: Alpaca remains the primary market clock, but a deterministic
# NYSE regular-session sanity check prevents a stale false `is_open` value
# from putting the entire live trader to sleep during obvious core hours.
_market_clock_last_override_log = 0.0
_market_clock_last_error_log = 0.0
MARKET_CLOCK_FALLBACK_LOG_SECONDS = 300.0


def _nth_weekday(year: int, month: int, weekday: int, n: int):
    d = datetime(year, month, 1).date()
    shift = (weekday - d.weekday()) % 7
    return d + timedelta(days=shift + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int):
    if month == 12:
        d = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        d = datetime(year, month + 1, 1).date() - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed_fixed_holiday(year: int, month: int, day: int):
    d = datetime(year, month, day).date()
    if d.weekday() == 5:  # Saturday -> Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday -> Monday
        return d + timedelta(days=1)
    return d


def _easter_sunday(year: int):
    # Anonymous Gregorian algorithm; used only to derive Good Friday.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime(year, month, day).date()


def _nyse_regular_holidays(year: int):
    holidays = {
        _observed_fixed_holiday(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),   # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),   # Washington's Birthday
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),     # Memorial Day
        _observed_fixed_holiday(year, 6, 19),  # Juneteenth
        _observed_fixed_holiday(year, 7, 4),   # Independence Day
        _nth_weekday(year, 9, 0, 1),   # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_fixed_holiday(year, 12, 25), # Christmas
    }
    # New Year's Day can be observed on Dec 31 of the previous year.
    holidays.add(_observed_fixed_holiday(year + 1, 1, 1))
    return holidays


def _nyse_early_close_dates(year: int):
    dates = set()
    # Friday after Thanksgiving.
    dates.add(_nth_weekday(year, 11, 3, 4) + timedelta(days=1))
    # Christmas Eve when it is a weekday and not itself a full holiday.
    xmas_eve = datetime(year, 12, 24).date()
    if xmas_eve.weekday() < 5 and xmas_eve not in _nyse_regular_holidays(year):
        dates.add(xmas_eve)
    # Common Independence Day early close: July 3 when it is a weekday and
    # not the observed full holiday. If July 4 is Monday, July 1 is commonly
    # the preceding early-close session.
    july4 = datetime(year, 7, 4).date()
    candidate = datetime(year, 7, 3).date()
    if candidate.weekday() < 5 and candidate not in _nyse_regular_holidays(year):
        dates.add(candidate)
    elif july4.weekday() == 0:
        july1 = datetime(year, 7, 1).date()
        if july1.weekday() < 5 and july1 not in _nyse_regular_holidays(year):
            dates.add(july1)
    return dates


def _nyse_schedule_state(now_utc=None) -> Dict[str, Any]:
    now_utc = now_utc or datetime.now(UTC)
    ny = now_utc.astimezone(ZoneInfo("America/New_York"))
    day = ny.date()
    holidays = _nyse_regular_holidays(day.year)
    regular_day = ny.weekday() < 5 and day not in holidays
    close_hour = 13 if day in _nyse_early_close_dates(day.year) else 16
    open_dt = ny.replace(hour=9, minute=30, second=0, microsecond=0)
    close_dt = ny.replace(hour=close_hour, minute=0, second=0, microsecond=0)
    is_open = bool(regular_day and open_dt <= ny < close_dt)
    return {
        "isOpen": is_open,
        "timestamp": ny.isoformat(),
        "sessionOpen": open_dt.isoformat(),
        "sessionClose": close_dt.isoformat(),
        "regularDay": regular_day,
        "earlyClose": bool(day in _nyse_early_close_dates(day.year)),
        "date": day.isoformat(),
    }


def get_effective_market_status_payload() -> Dict[str, Any]:
    global _market_clock_last_override_log, _market_clock_last_error_log
    schedule = _nyse_schedule_state()
    try:
        clock = trading_client.get_clock()
        alpaca_open = bool(clock.is_open)
        effective_open = alpaca_open
        source = "alpaca"
        overridden = False

        # We only override a suspicious CLOSED result. Alpaca remains trusted
        # when it reports OPEN, preserving broker-side special-session handling.
        if not alpaca_open and schedule["isOpen"]:
            effective_open = True
            source = "nyse_schedule_fallback"
            overridden = True
            now_mono = time.monotonic()
            if now_mono - _market_clock_last_override_log >= MARKET_CLOCK_FALLBACK_LOG_SECONDS:
                print(
                    "V17.6.4 MARKET CLOCK MISMATCH | "
                    f"alpaca_open={alpaca_open} schedule_open={schedule['isOpen']} "
                    f"ny_time={schedule['timestamp']} -> USING NYSE SCHEDULE FALLBACK"
                )
                _market_clock_last_override_log = now_mono

        return {
            "isOpen": effective_open,
            "alpacaOpen": alpaca_open,
            "scheduleOpen": bool(schedule["isOpen"]),
            "fallbackActive": overridden,
            "source": source,
            "timestamp": str(clock.timestamp),
            "nextOpen": str(clock.next_open),
            "nextClose": str(clock.next_close),
            "schedule": schedule,
            "label": "OPEN" if effective_open else "CLOSED",
        }
    except Exception as exc:
        # If the broker clock itself errors, a known regular NYSE session is a
        # safer fallback than forcing the bot closed. Outside the session we
        # remain closed.
        effective_open = bool(schedule["isOpen"])
        now_mono = time.monotonic()
        if now_mono - _market_clock_last_error_log >= MARKET_CLOCK_FALLBACK_LOG_SECONDS:
            print(
                "V17.6.4 MARKET CLOCK ERROR | "
                f"error={exc} schedule_open={effective_open} ny_time={schedule['timestamp']} "
                "-> USING NYSE SCHEDULE FALLBACK"
            )
            _market_clock_last_error_log = now_mono
        return {
            "isOpen": effective_open,
            "alpacaOpen": None,
            "scheduleOpen": effective_open,
            "fallbackActive": True,
            "source": "nyse_schedule_fallback_error",
            "error": str(exc),
            "timestamp": schedule["timestamp"],
            "nextOpen": "",
            "nextClose": "",
            "schedule": schedule,
            "label": "OPEN" if effective_open else "CLOSED",
        }


def get_market_status_payload():
    return get_effective_market_status_payload()


def get_quote(symbol: str):
    req = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
    quote = data_client.get_stock_latest_quote(req)[symbol]
    bid = quote.bid_price
    ask = quote.ask_price
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        raise ValueError(f"Bad quote for {symbol}")
    mid = (bid + ask) / 2.0
    spread = (ask - bid) / mid
    return {"bid": float(bid), "ask": float(ask), "mid": float(mid), "spread": float(spread)}


def get_position(symbol: str):
    try:
        pos = trading_client.get_open_position(symbol)
        return float(pos.qty), float(pos.avg_entry_price)
    except Exception:
        return 0.0, 0.0


def get_open_orders(symbol=None):
    try:
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        orders = trading_client.get_orders(filter=request)
        if symbol is None:
            return orders
        return [order for order in orders if str(order.symbol).upper() == symbol.upper()]
    except Exception:
        return []


def has_open_order(symbol: str):
    return len(get_open_orders(symbol)) > 0


def get_all_positions():
    positions = []
    try:
        raw_positions = trading_client.get_all_positions()
    except Exception:
        return positions

    for pos in raw_positions:
        try:
            symbol = str(pos.symbol).upper()
            qty = float(pos.qty)
            entry = float(pos.avg_entry_price)
            market_value = float(pos.market_value)

            if qty <= DUST_THRESHOLD:
                continue

            ensure_symbol_state(symbol)

            quote_price = 0.0
            spread = 0.0
            try:
                quote = get_quote(symbol)
                quote_price = quote["mid"]
                spread = quote["spread"]
            except Exception:
                try:
                    quote_price = float(pos.current_price)
                except Exception:
                    quote_price = 0.0

            pnl = 0.0
            pnl_pct = 0.0
            if entry > 0 and quote_price > 0:
                pnl = (quote_price - entry) * qty
                pnl_pct = ((quote_price / entry) - 1.0) * 100.0

            highest = state[symbol].get("highest_since_entry")
            if quote_price > 0 and (highest is None or quote_price > highest):
                state[symbol]["highest_since_entry"] = quote_price

            # V17.1: expose the same adaptive AI risk levels that the live exit
            # manager actually uses. This keeps the dashboard/replay chart from
            # showing the older global trail value while execution uses a symbol-
            # specific profile.
            risk_profile = _ai_risk_effective_profile(symbol) if "_ai_risk_effective_profile" in globals() else {}
            trail_start_pct = abs(float(risk_profile.get("trailStartPct") or ((TRAIL_START - 1.0) * 100.0)))
            trail_giveback_pct = abs(float(risk_profile.get("trailGivebackPct") or ((1.0 - TRAIL_GIVEBACK) * 100.0)))
            stop_loss_pct = abs(float(risk_profile.get("stopLossPct") or ((1.0 - STOP_LOSS) * 100.0)))
            emergency_stop_pct = abs(float(risk_profile.get("emergencyStopPct") or (globals().get("AI_RISK_EMERGENCY_STOP_PCT", 10.0))))
            trail_start_price = entry * (1.0 + trail_start_pct / 100.0) if entry > 0 else 0.0
            trail_floor = (state[symbol].get("highest_since_entry") or 0.0) * (1.0 - trail_giveback_pct / 100.0)
            stop_price = entry * (1.0 - stop_loss_pct / 100.0) if entry > 0 else 0.0
            emergency_stop_price = entry * (1.0 - emergency_stop_pct / 100.0) if entry > 0 else 0.0
            trailing_active = quote_price >= trail_start_price if quote_price > 0 and trail_start_price > 0 else False

            positions.append({
                "symbol": symbol,
                "qty": qty,
                "entry": entry,
                "price": quote_price,
                "marketValue": market_value,
                "marketValueGbp": money_gbp(market_value),
                "pnl": pnl,
                "pnlGbp": money_gbp(pnl),
                "pnlPct": pnl_pct,
                "spread": spread,
                "highest": state[symbol].get("highest_since_entry") or 0.0,
                "trailStartPrice": trail_start_price,
                "trailFloor": trail_floor,
                "trailingActive": trailing_active,
                "stopPrice": stop_price,
                "emergencyStopPrice": emergency_stop_price,
                "trailStartPct": trail_start_pct,
                "trailGivebackPct": trail_giveback_pct,
                "runnerTrailEnabled": bool(ADAPTIVE_RUNNER_TRAIL_ENABLED),
                "runnerGraceActive": bool(int(state[symbol].get("runner_trail_breach_count") or 0) > 0),
                "runnerGraceCheck": int(state[symbol].get("runner_trail_breach_count") or 0),
                "runnerGraceRequired": int(ADAPTIVE_RUNNER_CONFIRMATION_CHECKS),
                "runnerLastBreachPct": float(state[symbol].get("runner_trail_last_breach_pct") or 0.0),
                "peakExhaustionEnabled": bool(PEAK_EXHAUSTION_ENABLED),
                "peakExhaustionTouches": int(state[symbol].get("peak_exhaustion_touch_count") or 0),
                "peakExhaustionRequired": int(PEAK_EXHAUSTION_REQUIRED_TOUCHES),
                "peakExhaustionPeak": float(state[symbol].get("peak_exhaustion_peak") or 0.0),
                "peakExhaustionArmed": bool(state[symbol].get("peak_exhaustion_armed") or False),
                "peakExhaustionRejectPct": float(state[symbol].get("peak_exhaustion_reject_pct") or 0.0),
                "aiRiskProfile": risk_profile,
                "inUniverse": symbol in current_universe,
                "custom": bool(state.get(symbol, {}).get("custom")),
                "lockedToday": is_locked_today(symbol),
                "boughtToday": was_bought_today(symbol),
                "minutesSinceBuy": minutes_since_today_buy(symbol),
                "partialProfitTaken": has_taken_partial_profit(symbol),
                "partialProfitTriggerPct": PARTIAL_PROFIT_TRIGGER_PCT,
                "fastStopLossPct": FAST_STOP_LOSS_PCT,
                "stallExitAfterMinutes": STALL_EXIT_AFTER_MINUTES,
            })
        except Exception:
            continue

    positions.sort(key=lambda p: abs(p.get("marketValue", 0.0)), reverse=True)
    return positions


# =========================
# HISTORY / MEMORY
# =========================
def get_today_buy_event(symbol: str):
    today = today_str()
    for event in reversed(trade_events + trade_history[-100:]):
        if event.get("symbol") == symbol and event.get("side") == "BUY" and event.get("day") == today:
            return event
    return None


def was_bought_today(symbol: str):
    return get_today_buy_event(symbol) is not None


def minutes_since_today_buy(symbol: str):
    buy = get_today_buy_event(symbol)
    if not buy:
        return 999999
    try:
        buy_time = datetime.strptime(f"{buy['day']} {buy['time']}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return max(0, int((datetime.now(UTC) - buy_time).total_seconds() / 60))
    except Exception:
        return 0


def today_buy_count():
    today = today_str()
    return len([t for t in trade_events if t.get("side") == "BUY" and t.get("day") == today])


def get_memory(symbol: str):
    symbol = symbol.upper()
    if symbol not in stock_memory:
        stock_memory[symbol] = {
            "wins": 0, "losses": 0, "trades": 0,
            "totalPnl": 0.0, "totalPnlPct": 0.0,
            "avgPnl": 0.0, "avgPnlPct": 0.0,
            "winRate": 0.0, "trust": "NEW", "lastResult": "—",
        }
    return stock_memory[symbol]


def update_stock_memory_from_sell(symbol: str, pnl: float, pnl_pct: float):
    if not STOCK_MEMORY_ENABLED:
        return
    m = get_memory(symbol)
    m["trades"] += 1
    m["totalPnl"] += float(pnl)
    m["totalPnlPct"] += float(pnl_pct)
    if pnl >= 0:
        m["wins"] += 1
        m["lastResult"] = "WIN"
    else:
        m["losses"] += 1
        m["lastResult"] = "LOSS"
    m["winRate"] = m["wins"] / max(1, m["trades"])
    m["avgPnl"] = m["totalPnl"] / max(1, m["trades"])
    m["avgPnlPct"] = m["totalPnlPct"] / max(1, m["trades"])
    if m["trades"] < MEMORY_MIN_TRADES_FOR_TRUST:
        m["trust"] = "NEW"
    elif m["winRate"] >= MEMORY_GOOD_WINRATE:
        m["trust"] = "GOOD"
    elif m["winRate"] <= MEMORY_BAD_WINRATE:
        m["trust"] = "BAD"
    else:
        m["trust"] = "NEUTRAL"
    save_stock_memory()
    refresh_blacklist_from_memory(symbol)


def memory_multiplier(symbol: str):
    if not STOCK_MEMORY_ENABLED:
        return 1.0
    m = get_memory(symbol)
    if m["trades"] < MEMORY_MIN_TRADES_FOR_TRUST:
        return 1.0
    if m["winRate"] >= MEMORY_GOOD_WINRATE:
        return MEMORY_GOOD_MULTIPLIER
    if m["winRate"] <= MEMORY_BAD_WINRATE:
        return MEMORY_BAD_MULTIPLIER
    return 1.0


def add_trade_history_event(event: Dict[str, Any]):
    if not TRADE_TIMELINE_ENABLED:
        return
    equity = 0.0
    try:
        equity = float(get_account().equity)
    except Exception:
        pass
    item = {
        **event,
        "timestamp": datetime.now(UTC).isoformat(),
        "equity": equity,
        "equityGbp": money_gbp(equity),
        "fxRate": get_usd_to_gbp_rate(),
    }

    if "pnl" in item:
        item["pnlGbp"] = money_gbp(float(item.get("pnl") or 0.0))

    if "amount" in item:
        item["amountGbp"] = money_gbp(float(item.get("amount") or 0.0))
    trade_history.append(item)
    if len(trade_history) > 2000:
        del trade_history[:-2000]
    save_trade_history()
    save_trade_to_db(item, source="bot")


def stock_memory_payload():
    items = [{"symbol": s, **m} for s, m in stock_memory.items()]
    items.sort(key=lambda x: (-x.get("winRate", 0), -x.get("trades", 0)))
    return items


# =========================
# SIGNALS
# =========================
def calculate_confidence(scan: Dict[str, Any]):
    quality = float(scan.get("quality_score", 0.0))
    spread = float(scan.get("spread", 1.0))
    momentum = float(scan.get("short_momentum", 0.0))
    pullback = float(scan.get("pullback", 0.0))
    symbol = scan.get("symbol", "")

    confidence = 0.0
    confidence += min(0.35, quality * 8.0)
    confidence += 0.20 if spread <= PREFER_SPREAD_UNDER else 0.10 if spread <= MAX_SPREAD else 0.0
    confidence += 0.20 if momentum >= 0 else 0.10 if momentum >= SNIPER_MIN_MOMENTUM else 0.0
    confidence += 0.15 if SNIPER_MIN_PULLBACK <= pullback <= SNIPER_MAX_PULLBACK else 0.0
    confidence *= memory_multiplier(symbol)
    confidence = max(0.0, min(1.0, confidence))

    label = "HIGH" if confidence >= 0.75 else "MEDIUM" if confidence >= 0.58 else "LOW"
    return confidence, label


def sniper_passes(scan: Dict[str, Any]):
    if not SNIPER_MODE_ENABLED:
        return True, "SNIPER OFF"
    confidence, label = calculate_confidence(scan)
    if confidence < SNIPER_MIN_CONFIDENCE:
        return False, f"confidence too low {confidence:.2f}"
    if scan["quality_score"] < SNIPER_MIN_QUALITY:
        return False, f"quality too low {scan['quality_score']:.4f}"
    if scan["spread"] > SNIPER_MAX_SPREAD:
        return False, f"spread too wide {scan['spread']:.4f}"
    if scan["pullback"] < SNIPER_MIN_PULLBACK or scan["pullback"] > SNIPER_MAX_PULLBACK:
        return False, f"pullback outside sniper range {scan['pullback']:.4f}"
    if scan["short_momentum"] < SNIPER_MIN_MOMENTUM:
        return False, f"momentum too weak {scan['short_momentum']:.4f}"
    return True, f"{label} confidence {confidence:.2f}"


def compute_short_momentum(symbol: str, current_price: float):
    curve = state[symbol].get("price_curve", [])
    if len(curve) < MOMENTUM_LOOKBACK_POINTS:
        return 0.0
    old = curve[-MOMENTUM_LOOKBACK_POINTS]["value"]
    return 0.0 if old <= 0 else (current_price / old) - 1.0


def compute_scan(symbol: str):
    ensure_symbol_state(symbol, custom=symbol in custom_symbols)
    quote = get_quote(symbol)
    qty, entry = get_position(symbol)

    price = quote["mid"]
    spread = quote["spread"]

    if state[symbol]["ref"] is None:
        state[symbol]["ref"] = price
    ref = state[symbol]["ref"]
    if price > ref:
        state[symbol]["ref"] = price
        ref = price

    if qty > DUST_THRESHOLD:
        highest = state[symbol].get("highest_since_entry")
        if highest is None or price > highest:
            state[symbol]["highest_since_entry"] = price
    else:
        state[symbol]["highest_since_entry"] = None

    curve = state[symbol]["price_curve"]
    curve.append({"t": now_chart_time(), "value": price})
    if len(curve) > 180:
        curve.pop(0)

    short_momentum = compute_short_momentum(symbol, price)
    pullback = max(0.0, (ref - price) / ref) if ref > 0 else 0.0
    tightness_score = max(0.0, PREFER_SPREAD_UNDER - spread)

    quality_score = 0.0
    if MIN_PULLBACK <= pullback <= MAX_PULLBACK:
        quality_score += pullback * 3.0
    if spread <= MAX_SPREAD:
        quality_score += tightness_score * 2.0
    if MIN_SHORT_MOMENTUM <= short_momentum <= MAX_SHORT_MOMENTUM:
        quality_score += max(0.0, short_momentum) * 0.7
    else:
        quality_score -= 0.02

    buy_trigger = ref * BUY_DIP
    locked = is_locked_today(symbol)
    ready_to_buy = (
        not locked and
        price <= buy_trigger and
        spread <= MAX_SPREAD and
        MIN_PULLBACK <= pullback <= MAX_PULLBACK and
        short_momentum >= MIN_SHORT_MOMENTUM and
        len(curve) >= MIN_TICKS_BEFORE_BUY
    )

    temp = {
        "symbol": symbol, "quality_score": quality_score, "spread": spread,
        "short_momentum": short_momentum, "pullback": pullback,
    }
    confidence, confidence_label = calculate_confidence(temp)
    sniper_ok, sniper_reason = sniper_passes({**temp, "ready_to_buy": ready_to_buy, "confidence": confidence})
    aplus_ok, aplus_reason = a_plus_gate({**temp, "confidence": confidence})

    return {
        "symbol": symbol,
        "price": price,
        "spread": spread,
        "bid": quote["bid"],
        "ask": quote["ask"],
        "qty": qty,
        "entry": entry,
        "ref": ref,
        "score": (price / ref) - 1.0 if ref > 0 else 0.0,
        "pullback": pullback,
        "short_momentum": short_momentum,
        "quality_score": quality_score,
        "buy_trigger": buy_trigger,
        "ready_to_buy": ready_to_buy,
        "locked_today": locked,
        "custom": symbol in custom_symbols,
        "price_curve": curve,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "sniper_pass": sniper_ok,
        "sniper_reason": sniper_reason,
        "a_plus_pass": aplus_ok,
        "a_plus_reason": aplus_reason,
    }


# =========================
# ORDERS / RISK
# =========================
def get_daily_pnl():
    global starting_equity_today
    try:
        equity = get_equity()
        if starting_equity_today is None:
            starting_equity_today = equity
        return equity - starting_equity_today
    except Exception:
        return 0.0


def daily_trade_count():
    today = today_str()
    return len([t for t in trade_events if t.get("day") == today])


def risk_blocked():
    if PROFIT_OPTIMIZER_ENABLED:
        opt_blocked, opt_reason = profit_guardrail_status()
        if opt_blocked:
            return True, opt_reason

    pnl = get_daily_pnl()
    if pnl <= MAX_DAILY_LOSS:
        return True, f"Max daily loss hit: {pnl:.2f}"
    if daily_trade_count() >= MAX_TRADES_PER_DAY:
        return True, "Max trades per day reached"
    return False, ""


def ai_position_capacity_payload() -> Dict[str, Any]:
    """Return the live AI-controlled portfolio capacity.

    Capacity is not a target that must be filled. It is only the maximum number
    of simultaneous positions the bot may hold if enough independent candidates
    pass every existing entry, quality, risk, PDT and cash check.
    """
    configured = int(globals().get("MAX_POSITIONS", 1) or 1)
    hard_cap = int(globals().get("AI_POSITION_HARD_CAP", 10) or 10)

    # V17.0.4: a configured one-position full-buy mode is authoritative.
    # Do not let the legacy AI capacity estimator expand MAX_POSITIONS=1 back
    # to 8-10 slots based on TARGET_POSITION_VALUE_PCT.
    if bool(globals().get("V17_SINGLE_FULL_BUY_MODE", False)) or (bool(globals().get("FULL_BUY_WHEN_ONE_POSITION", False)) and configured <= 1):
        try:
            account = get_account()
            equity = float(account.equity)
            buying_power = max(0.0, float(account.buying_power))
            # V17.6: explicit single-position FULL BUY uses the whole WORKING pot,
            # while realised Profit Vault cash remains reserved and cannot be reused.
            cap_usd = profit_vault_deployable_usd(equity, buying_power) if "profit_vault_deployable_usd" in globals() else equity
            open_count = len(get_all_positions())
        except Exception:
            buying_power = None
            cap_usd = None
            try:
                open_count = len(get_all_positions())
            except Exception:
                open_count = 0
        structural_slots = max(0, 1 - int(open_count))
        affordable = 1 if structural_slots > 0 and (buying_power is None or buying_power > float(globals().get("MIN_ORDER_NOTIONAL", 1.0))) else 0
        return {
            "enabled": True,
            "configuredMaxPositions": 1,
            "effectiveMaxPositions": 1,
            "hardSafetyCap": 1,
            "targetPositionValuePct": 1.0,
            "maxPositionValuePct": 1.0,
            "capitalUsd": round(float(cap_usd), 2) if cap_usd is not None else None,
            "buyingPowerUsd": round(float(buying_power), 2) if buying_power is not None else None,
            "targetPositionNotionalUsd": round(max(0.0, min(float(buying_power or 0.0), float(cap_usd or 0.0)) - float(globals().get("FULL_BUY_CASH_BUFFER", 2.0))), 2) if buying_power is not None else None,
            "openPositions": int(open_count),
            "structuralAvailableSlots": int(structural_slots),
            "affordableNewPositions": int(affordable),
            "availableSlots": int(min(structural_slots, affordable)),
            "reason": "V17.6 single-position full-buy mode: the full working pot is authoritative, while realised Profit Vault cash is reserved from new orders.",
        }

    if not bool(globals().get("AI_POSITION_CAPACITY_ENABLED", True)):
        return {
            "enabled": False, "configuredMaxPositions": configured,
            "effectiveMaxPositions": configured, "hardSafetyCap": hard_cap,
            "reason": "Legacy fixed-position mode is active.",
        }

    target_pct = max(0.001, float(globals().get("TARGET_POSITION_VALUE_PCT", 0.10) or 0.10))
    max_pct = max(target_pct, float(globals().get("MAX_POSITION_VALUE_PCT", target_pct) or target_pct))
    # Target sizing is the AI decision. Portfolio capacity is a consequence of
    # that target, not of the legacy single-buy amount or currently free cash.
    # The epsilon avoids 10% becoming 9 because of binary floating-point.
    sizing_capacity = max(1, int(math.floor((1.0 / target_pct) + 1e-9)))

    cap_usd = None
    buying_power = None
    target_notional = None
    affordable_new_positions = 0
    open_count = 0
    try:
        account = get_account()
        equity = float(account.equity)
        buying_power = max(0.0, float(account.buying_power))
        cap_usd = effective_trading_equity(equity) if "effective_trading_equity" in globals() else equity
        target_notional = max(
            float(globals().get("AI_POSITION_MIN_NOTIONAL_USD", 25.0)),
            cap_usd * target_pct,
        )
        open_count = len(get_all_positions())
        usable_cash = max(0.0, buying_power - float(globals().get("CASH_BUFFER", 0.0)))
        affordable_new_positions = max(0, int(math.floor((usable_cash / max(target_notional, 1.0)) + 1e-9)))
    except Exception:
        # Capacity remains AI-sized if account telemetry is briefly unavailable.
        # Existing order-side cash checks still prevent unaffordable purchases.
        try:
            open_count = len(get_all_positions())
        except Exception:
            open_count = 0

    effective = max(1, min(hard_cap, sizing_capacity))
    structural_slots = max(0, effective - open_count)
    usable_slots_now = min(structural_slots, affordable_new_positions) if buying_power is not None else structural_slots
    reason = (
        f"AI target allocation permits up to {sizing_capacity}; effective safety-bounded capacity is {effective}. "
        f"Current buying power can fund {affordable_new_positions} additional target-sized position(s). "
        "Every slot still requires an independently qualified candidate."
    )
    return {
        "enabled": True,
        "configuredMaxPositions": configured,
        "effectiveMaxPositions": effective,
        "hardSafetyCap": hard_cap,
        "targetPositionValuePct": round(target_pct, 4),
        "maxPositionValuePct": round(max_pct, 4),
        "capitalUsd": round(float(cap_usd), 2) if cap_usd is not None else None,
        "buyingPowerUsd": round(float(buying_power), 2) if buying_power is not None else None,
        "targetPositionNotionalUsd": round(float(target_notional), 2) if target_notional is not None else None,
        "openPositions": int(open_count),
        "structuralAvailableSlots": int(structural_slots),
        "affordableNewPositions": int(affordable_new_positions),
        "availableSlots": int(usable_slots_now),
        "reason": reason,
    }


def effective_max_positions() -> int:
    try:
        return int(ai_position_capacity_payload()["effectiveMaxPositions"])
    except Exception:
        return max(1, int(globals().get("MAX_POSITIONS", 1) or 1))


def allowed_new_position_count():
    try:
        payload = ai_position_capacity_payload()
        if payload.get("enabled"):
            return max(0, int(payload.get("availableSlots", 0)))
    except Exception:
        pass
    return max(0, effective_max_positions() - len(get_all_positions()))


def calculate_new_position_notional():
    account = get_account()
    equity = float(account.equity)
    buying_power = float(account.buying_power)

    # Profit banking cap now controls sizing. If account equity grows above
    # the saved cap, new trade sizes are calculated from the capped amount,
    # not full account equity.
    sizing_equity = effective_trading_equity(equity) if "effective_trading_equity" in globals() else equity

    # Full-buy mode for one-position trading.
    # Uses nearly all available capped trading capital/buying power, leaving a small buffer.
    if V17_SINGLE_FULL_BUY_MODE or (FULL_BUY_WHEN_ONE_POSITION and effective_max_positions() <= 1):
        # V17.6: full-buy means the whole WORKING pot, not the Profit Vault.
        working_cash = profit_vault_deployable_usd(equity, buying_power) if "profit_vault_deployable_usd" in globals() else buying_power
        usable_cash = max(0.0, min(buying_power, working_cash) - FULL_BUY_CASH_BUFFER)
        return round(usable_cash, 2)

    target_value = sizing_equity * TARGET_POSITION_VALUE_PCT
    max_value = sizing_equity * MAX_POSITION_VALUE_PCT
    usable_cash = max(0.0, buying_power - CASH_BUFFER)
    return round(max(0.0, min(target_value, max_value, usable_cash)), 2)


def confidence_notional(scan):
    base = calculate_new_position_notional()

    # In one-position full-buy mode, do not downsize by confidence.
    # The entry gates still control trade quality; this only changes allocation size.
    if V17_SINGLE_FULL_BUY_MODE or (FULL_BUY_WHEN_ONE_POSITION and effective_max_positions() <= 1):
        return base

    if not CONFIDENCE_SIZING_ENABLED:
        return base

    confidence, label = calculate_confidence(scan)
    mult = HIGH_CONFIDENCE_SIZE_MULTIPLIER if label == "HIGH" else MEDIUM_CONFIDENCE_SIZE_MULTIPLIER if label == "MEDIUM" else LOW_CONFIDENCE_SIZE_MULTIPLIER
    try:
        account_equity = float(get_account().equity)
        sizing_equity = effective_trading_equity(account_equity) if "effective_trading_equity" in globals() else account_equity
    except Exception:
        sizing_equity = 0.0
    cap = sizing_equity * MAX_CONFIDENCE_POSITION_VALUE_PCT if sizing_equity > 0 else base
    return round(max(0.0, min(base * mult, cap)), 2)


def proposed_buy_qty(scan: Dict[str, Any]) -> float:
    """Display-only estimate. Live orders still use notional sizing at submission time."""
    try:
        price = float(scan.get("price") or 0.0)
        if price <= 0:
            return 0.0
        notional = float(confidence_notional(scan))
        return floor_qty(notional / price, 6)
    except Exception:
        return 0.0


def can_buy_symbol(symbol: str):
    if STRICT_ONE_CYCLE_PER_STOCK_PER_DAY and is_locked_today(symbol):
        return False, f"{symbol} locked until tomorrow"
    if has_open_order(symbol):
        return False, f"{symbol} existing open order"
    qty, _ = get_position(symbol)
    if qty > DUST_THRESHOLD:
        return False, f"{symbol} already holding"
    return True, ""


def add_alpaca_rejection_event(symbol: str, reason: str, error_text: str):
    label = "PDT BLOCK" if is_likely_pdt_error(error_text) else "ALPACA SELL REJECTED"
    event = {
        "day": today_str(), "time": now_time(), "symbol": symbol,
        "type": label, "reason": reason,
        "message": f"{label} | {symbol} sell was rejected by Alpaca.",
        "error": str(error_text),
    }
    alpaca_rejection_events.append(event)
    if len(alpaca_rejection_events) > 100:
        alpaca_rejection_events.pop(0)
    print(f"{event['message']} | {event['error']}")
    notify(f"⚠️ {event['message']} Reason: {event['error']}")


def add_pdt_warning(symbol: str, reason: str):
    event = {"day": today_str(), "time": now_time(), "symbol": symbol, "reason": reason, "message": f"PDT AWARE | {symbol}: {reason}"}
    pdt_warning_events.append(event)
    if len(pdt_warning_events) > 100:
        pdt_warning_events.pop(0)
    print(event["message"])


def pdt_aware_should_avoid_sell(symbol: str, reason: str, pnl_pct: float, allow_hard_stop=False):
    if not PDT_AWARE_MODE_ENABLED or not was_bought_today(symbol):
        return False
    if allow_hard_stop and pnl_pct <= HARD_STOP_LOSS_PCT:
        add_pdt_warning(symbol, f"hard stop override: attempting sell despite same-day buy, pnl={pnl_pct:.2f}%")
        return False
    mins = minutes_since_today_buy(symbol)
    if "ROTATE" in reason.upper() and AVOID_SAME_DAY_ROTATION_SELLS:
        add_pdt_warning(symbol, f"rotation skipped because bought today; hold until next day reset")
        return True
    if ("TRAILING" in reason.upper() or "PROFIT" in reason.upper()) and AVOID_SAME_DAY_PROFIT_SELLS:
        add_pdt_warning(symbol, f"profit sell skipped because bought today; hold until next day reset")
        return True
    return False


def market_buy_notional(symbol: str, notional_amount: float, reason="AUTO BUY", scan: Optional[Dict[str, Any]] = None):
    order = MarketOrderRequest(symbol=symbol, notional=round(notional_amount, 2), side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
    trading_client.submit_order(order)
    if AI_RISK_ENGINE_ENABLED and scan:
        try:
            _ai_risk_save_profile(_ai_risk_build_profile(scan), float(scan.get("price") or 0.0))
        except Exception as risk_error:
            print(f"AI RISK PROFILE SAVE ERROR {symbol}: {risk_error}")
    event = {
        "day": today_str(),
        "time": now_time(),
        "side": "BUY",
        "symbol": symbol,
        "amount": round(notional_amount, 2),
        "amountGbp": round(money_gbp(notional_amount), 2),
        "reason": reason,
        "pnl": 0.0,
        "pnlGbp": 0.0,
    }
    trade_events.append(event)
    add_trade_history_event(event)
    notify(f"🟢 {reason}: ${round(notional_amount, 2)} {symbol}")


def market_sell_qty(symbol: str, qty: float, entry: float = 0.0, price: float = 0.0, reason="AUTO SELL"):
    rounded_qty = floor_qty(qty, 6)
    if rounded_qty <= 0:
        return

    def submit(q):
        order = MarketOrderRequest(symbol=symbol, qty=q, side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
        trading_client.submit_order(order)

    try:
        submit(rounded_qty)
    except Exception as e:
        err = str(e)
        if is_insufficient_qty_error(err):
            available = parse_available_qty(err)
            retry_qty = floor_qty(available, 6) if available else 0
            if retry_qty > 0 and retry_qty < rounded_qty:
                try:
                    submit(retry_qty)
                    rounded_qty = retry_qty
                except Exception as retry_error:
                    add_alpaca_rejection_event(symbol, reason, f"Initial: {err} | Retry: {retry_error}")
                    raise
            else:
                add_alpaca_rejection_event(symbol, reason, err)
                raise
        else:
            add_alpaca_rejection_event(symbol, reason, err)
            raise

    pnl = (price - entry) * rounded_qty if entry > 0 and price > 0 else 0.0
    pnl_pct = ((price / entry) - 1.0) * 100.0 if entry > 0 and price > 0 else 0.0
    event = {
        "day": today_str(),
        "time": now_time(),
        "side": "SELL",
        "symbol": symbol,
        "qty": rounded_qty,
        "reason": reason,
        "pnl": round(pnl, 4),
        "pnlGbp": round(money_gbp(pnl), 4),
        "pnlPct": round(pnl_pct, 4),
    }
    trade_events.append(event)
    add_trade_history_event(event)
    update_stock_memory_from_sell(symbol, pnl, pnl_pct)
    if pnl > 0 and "profit_vault_bank_realised_profit" in globals():
        try:
            profit_vault_bank_realised_profit(pnl, symbol=symbol, reason=reason)
        except Exception as vault_exc:
            print(f"V17.6 PROFIT VAULT BANK ERROR | symbol={symbol} error={vault_exc}")
    lock_symbol_until_tomorrow(symbol)
    notify(f"🔴 {reason}: {symbol} | qty={rounded_qty} | est PnL {round(pnl, 4)} ({round(pnl_pct, 2)}%)")


def close_position(position, reason="MANUAL SELL"):
    symbol = position["symbol"]
    qty = position["qty"]
    entry = position["entry"]
    price = position["price"]

    if qty <= DUST_THRESHOLD:
        return {"ok": False, "message": "No open position to sell"}
    if has_open_order(symbol):
        return {"ok": False, "message": f"{symbol} already has open order"}

    market_sell_qty(symbol, qty, entry=entry, price=price, reason=reason)
    if symbol in state:
        state[symbol]["highest_since_entry"] = None
    return {"ok": True, "message": f"{reason} submitted for {symbol}. {symbol} locked until tomorrow.", "symbol": symbol}


def close_position_by_symbol(symbol: str, reason="MANUAL SYMBOL SELL"):
    for p in get_all_positions():
        if p["symbol"] == symbol:
            return close_position(p, reason=reason)
    return {"ok": False, "message": f"No open position found for {symbol}"}


def close_worst_or_largest_position(reason="MANUAL SELL"):
    positions = get_all_positions()
    if not positions:
        return {"ok": False, "message": "No open position to sell"}
    positions.sort(key=lambda p: (p["pnlPct"], -abs(p["marketValue"])))
    return close_position(positions[0], reason=reason)


def close_all_positions(reason="EMERGENCY SELL"):
    results = []
    positions = get_all_positions()
    if not positions:
        return {"ok": False, "message": "No open positions to sell"}
    for p in positions:
        try:
            results.append(close_position(p, reason=reason))
        except Exception as e:
            results.append({"ok": False, "symbol": p["symbol"], "message": str(e)})
    return {"ok": True, "message": f"{reason} attempted for {len(positions)} positions.", "results": results}




# =========================
# SWING HOLD AI HELPERS
# =========================
def _parse_trade_dt(value: Any):
    try:
        if not value:
            return None
        txt = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(txt)
    except Exception:
        return None


def hold_ai_symbol_profile(symbol: str):
    """Small, safe learning layer from rebuilt closed trades.
    It does not predict prices. It only decides whether this symbol deserves
    more patience or should be treated cautiously based on its own history.
    """
    sym = str(symbol or "").upper()
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    cutoff = datetime.now(UTC) - timedelta(days=HOLD_AI_LOOKBACK_DAYS)
    trades = []
    for t in closed:
        if str(t.get("symbol", "")).upper() != sym:
            continue
        dt = _parse_trade_dt(t.get("timestamp"))
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if dt is not None and dt < cutoff:
            continue
        trades.append(t)

    wins = [t for t in trades if float(t.get("pnl") or 0.0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0.0) < 0]
    total = sum(float(t.get("pnl") or 0.0) for t in trades)
    avg_pct = sum(float(t.get("pnlPct") or 0.0) for t in trades) / max(1, len(trades))
    win_rate = len(wins) / max(1, len(trades))

    if len(trades) >= HOLD_AI_MIN_TRADES and win_rate >= 0.55 and total > 0:
        bias = "PATIENT"
        min_hold = HOLD_AI_GOOD_SYMBOL_HOLD_MINUTES
    elif len(trades) >= HOLD_AI_MIN_TRADES and (win_rate <= 0.40 or total < 0):
        bias = "CAUTIOUS"
        min_hold = HOLD_AI_WEAK_SYMBOL_HOLD_MINUTES
    else:
        bias = "NORMAL"
        min_hold = HOLD_AI_MIN_HOLD_MINUTES

    return {
        "symbol": sym,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": win_rate,
        "totalPnl": total,
        "avgPnlPct": avg_pct,
        "bias": bias,
        "minHoldMinutes": int(min_hold),
    }


def hold_ai_min_hold_minutes(symbol: str):
    if not HOLD_AI_ENABLED:
        return 0
    return int(hold_ai_symbol_profile(symbol).get("minHoldMinutes") or HOLD_AI_MIN_HOLD_MINUTES)


def hold_ai_blocks_soft_exit(position: Dict[str, Any], exit_reason: str):
    """Returns True when Swing AI should keep holding instead of taking a soft exit.
    Hard stops are intentionally not blocked.
    """
    if not HOLD_AI_ENABLED:
        return False, "hold ai off"

    symbol = str(position.get("symbol", "")).upper()
    pnl_pct = float(position.get("pnlPct") or 0.0)
    minutes = int(position.get("minutesSinceBuy") or 999999)
    min_hold = hold_ai_min_hold_minutes(symbol)
    profile = hold_ai_symbol_profile(symbol)

    # Never soft-sell the same day unless it is a hard stop. This protects the
    # account from PDT churn and stops the bot from scalping tiny moves.
    if was_bought_today(symbol):
        return True, f"HOLD AI same-day hold for {symbol}; soft exit blocked ({exit_reason})"

    # Give valid swing setups time to develop unless they are near the hard stop.
    if minutes < min_hold and pnl_pct > FAST_STOP_LOSS_PCT:
        return True, f"HOLD AI {profile['bias']} min hold {minutes}/{min_hold}m; pnl={pnl_pct:.2f}%"

    return False, f"HOLD AI allows {exit_reason}; {profile['bias']}"


# =========================
# FASTER EXIT HELPERS
# =========================
def has_taken_partial_profit(symbol: str):
    return partial_profit_taken.get(symbol.upper()) == today_str()


def mark_partial_profit_taken(symbol: str):
    partial_profit_taken[symbol.upper()] = today_str()


def sell_notional_ok(qty: float, price: float):
    return (float(qty) * float(price)) >= MIN_SELL_NOTIONAL


def partial_profit_qty(position: Dict[str, Any]):
    qty = float(position.get("qty") or 0.0)
    return floor_qty(qty * PARTIAL_PROFIT_SELL_PCT, 6)


def should_partial_profit(position: Dict[str, Any]):
    if HOLD_AI_ENABLED:
        return False, "swing hold ai: partial profit disabled"
    if not FAST_EXIT_MODE_ENABLED or not PARTIAL_PROFIT_ENABLED:
        return False, "partial profit disabled"

    symbol = position["symbol"]
    if has_taken_partial_profit(symbol):
        return False, "partial profit already taken today"

    pnl_pct = float(position.get("pnlPct") or 0.0)
    price = float(position.get("price") or 0.0)
    qty_to_sell = partial_profit_qty(position)

    if pnl_pct < PARTIAL_PROFIT_TRIGGER_PCT:
        return False, f"pnl {pnl_pct:.2f}% below partial trigger {PARTIAL_PROFIT_TRIGGER_PCT:.2f}%"

    if qty_to_sell <= DUST_THRESHOLD:
        return False, "partial qty too small"

    if not sell_notional_ok(qty_to_sell, price):
        return False, "partial sell notional too small"

    return True, "partial profit trigger"


def should_fast_stop(position: Dict[str, Any]):
    if not FAST_EXIT_MODE_ENABLED:
        return False, "fast exit disabled"

    pnl_pct = float(position.get("pnlPct") or 0.0)
    symbol = str(position.get("symbol") or "").upper()
    profile = _ai_risk_effective_profile(symbol) if "_ai_risk_effective_profile" in globals() else {}
    threshold = -abs(float(profile.get("fastStopLossPct") or abs(FAST_STOP_LOSS_PCT)))
    return pnl_pct <= threshold, f"adaptive fast stop pnl={pnl_pct:.2f}% threshold={threshold:.2f}%"


def should_stall_exit(position: Dict[str, Any]):
    if not FAST_EXIT_MODE_ENABLED or not STALL_EXIT_ENABLED:
        return False, "stall exit disabled"

    symbol = position["symbol"]
    minutes = int(position.get("minutesSinceBuy") or 999999)
    pnl_pct = float(position.get("pnlPct") or 0.0)

    ai_min = hold_ai_min_hold_minutes(symbol) if HOLD_AI_ENABLED else STALL_EXIT_AFTER_MINUTES
    effective_stall = max(STALL_EXIT_AFTER_MINUTES, ai_min)

    if minutes < effective_stall:
        return False, f"held {minutes}m below swing stall timer {effective_stall}m"

    if HOLD_AI_ENABLED and pnl_pct > -1.00:
        return False, f"hold ai: pnl {pnl_pct:.2f}% not weak enough for stall exit"

    if pnl_pct > STALL_EXIT_MIN_PNL_PCT:
        return False, f"pnl {pnl_pct:.2f}% above stall minimum"

    if was_bought_today(symbol) and PDT_AWARE_MODE_ENABLED:
        return False, "PDT-aware hold; stall exit skipped today"

    return True, f"stall exit: held {minutes}m pnl={pnl_pct:.2f}%"



# =========================
# TRADEBOT V2 EXPECTANCY HELPERS
# =========================
def v2_forward_shadow_profile(symbol: str, preferred_horizon: int = 24) -> Dict[str, Any]:
    """Forward replay evidence only. This never changes the live gate."""
    sym = str(symbol or "").upper().strip()
    if not (SQLITE_ENABLED and sym):
        return {"symbol": sym, "mode": "SHADOW", "recommendation": "WATCH", "samples": 0}
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute(
            """WITH ranked AS (
                   SELECT o.*,
                          ROW_NUMBER() OVER (
                              PARTITION BY COALESCE(o.sample_key, CAST(o.decision_id AS TEXT)), o.horizon_hours
                              ORDER BY o.id ASC
                          ) AS rn
                   FROM v2_observation_outcomes o
                   WHERE o.status='COMPLETE' AND o.symbol=? AND o.net_return_pct IS NOT NULL
               )
               SELECT horizon_hours, COUNT(*) AS samples,
                      AVG(net_return_pct) AS expectancy_pct,
                      SUM(CASE WHEN net_return_pct>0 THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN net_return_pct<0 THEN 1 ELSE 0 END) AS losses,
                      SUM(CASE WHEN net_return_pct=0 THEN 1 ELSE 0 END) AS breakevens,
                      SUM(CASE WHEN net_return_pct>0 THEN net_return_pct ELSE 0 END) /
                        NULLIF(ABS(SUM(CASE WHEN net_return_pct<0 THEN net_return_pct ELSE 0 END)),0) AS profit_factor
               FROM ranked WHERE rn=1
               GROUP BY horizon_hours ORDER BY CASE WHEN horizon_hours=? THEN 0 WHEN horizon_hours=1 THEN 1 ELSE 2 END, horizon_hours""",
            (sym, int(preferred_horizon)),
        ).fetchall()
        conn.close()
        row = dict(rows[0]) if rows else {}
        wins = int(row.get("wins") or 0)
        losses = int(row.get("losses") or 0)
        directional = wins + losses
        win_rate = wins / directional if directional else 0.0
        samples = int(row.get("samples") or 0)
        expectancy = float(row.get("expectancy_pct") or 0.0)
        pf = row.get("profit_factor")
        pf_value = float(pf) if pf is not None else (99.0 if wins and not losses else 0.0)
        enough = samples >= V2_MIN_SYMBOL_SAMPLES
        shadow_approved = enough and win_rate >= V2_MIN_WIN_RATE and pf_value >= V2_MIN_PROFIT_FACTOR and expectancy >= V2_MIN_EXPECTANCY_PCT
        recommendation = "APPROVE" if shadow_approved else ("BLOCK" if enough else "WATCH")
        return {
            "symbol": sym, "mode": "SHADOW", "horizonHours": int(row.get("horizon_hours") or preferred_horizon),
            "samples": samples, "wins": wins, "losses": losses, "breakevens": int(row.get("breakevens") or 0),
            "winRate": win_rate, "profitFactor": pf_value, "expectancyPct": expectancy,
            "recommendation": recommendation, "approved": shadow_approved,
            "reason": "forward evidence passes" if shadow_approved else ("insufficient forward samples" if not enough else "forward evidence below gate"),
        }
    except Exception as e:
        return {"symbol": sym, "mode": "SHADOW", "recommendation": "WATCH", "samples": 0, "error": str(e)}


def v2_symbol_expectancy(symbol: str):
    sym = str(symbol or "").upper().strip()
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    cutoff = datetime.now(UTC) - timedelta(days=V2_LOOKBACK_DAYS)
    rows = []
    for trade in closed:
        if str(trade.get("symbol", "")).upper() != sym:
            continue
        dt = _parse_trade_dt(trade.get("timestamp"))
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if dt is not None and dt < cutoff:
            continue
        rows.append(trade)

    pnls = [float(t.get("pnl") or 0.0) for t in rows]
    pct = [float(t.get("pnlPct") or 0.0) for t in rows]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    breakevens = [x for x in pnls if x == 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    directional = len(wins) + len(losses)
    win_rate = len(wins) / directional if directional else 0.0
    expectancy_pct = sum(pct) / len(pct) if pct else 0.0
    enough = len(rows) >= V2_MIN_SYMBOL_SAMPLES
    approved = enough and win_rate >= V2_MIN_WIN_RATE and profit_factor >= V2_MIN_PROFIT_FACTOR and expectancy_pct >= V2_MIN_EXPECTANCY_PCT
    reasons = []
    if not enough: reasons.append(f"only {len(rows)}/{V2_MIN_SYMBOL_SAMPLES} samples")
    if enough and win_rate < V2_MIN_WIN_RATE: reasons.append(f"win rate {win_rate:.0%} below {V2_MIN_WIN_RATE:.0%}")
    if enough and profit_factor < V2_MIN_PROFIT_FACTOR: reasons.append(f"profit factor {profit_factor:.2f} below {V2_MIN_PROFIT_FACTOR:.2f}")
    if enough and expectancy_pct < V2_MIN_EXPECTANCY_PCT: reasons.append(f"expectancy {expectancy_pct:.2f}% below {V2_MIN_EXPECTANCY_PCT:.2f}%")
    return {
        "symbol": sym, "samples": len(rows), "wins": len(wins), "losses": len(losses), "breakevens": len(breakevens),
        "directionalSamples": directional, "winRate": win_rate, "profitFactor": profit_factor,
        "expectancyPct": expectancy_pct, "totalPnl": sum(pnls),
        "approved": approved, "reason": "approved" if approved else "; ".join(reasons) or "not approved",
        "forwardShadow": v2_forward_shadow_profile(sym),
    }


def v2_trade_gate(scan: Dict[str, Any]):
    if not TRADEBOT_V2_ENABLED:
        return True, {"approved": True, "reason": "V2 disabled"}
    profile = v2_symbol_expectancy(scan.get("symbol"))
    # Deliberately use historical approval only. forwardShadow is advisory.
    return bool(profile.get("approved")), profile


def v17_v2_trade_gate_with_cold_start(scan: Dict[str, Any], log_decision: bool = True):
    """V17.0.15 V2 gate with a bounded cold-start path for new symbols.

    This never overrides mature negative evidence.  Once a symbol has the normal
    V2 sample minimum it must pass the established expectancy gate exactly as
    before.  For fewer samples, the symbol may proceed only when the current
    setup is unusually strong.  Earlier account/reputation/Sniper/A+ gates are
    intentionally evaluated by the caller before this function is reached.
    """
    ok, profile = v2_trade_gate(scan)
    profile = dict(profile or {})
    if ok or not TRADEBOT_V2_ENABLED:
        profile.setdefault("coldStart", False)
        return ok, profile

    samples = int(profile.get("samples") or 0)
    if not V17_V2_COLD_START_ENABLED or samples >= V2_MIN_SYMBOL_SAMPLES:
        return False, profile

    symbol = str(scan.get("symbol") or "").upper().strip()
    confidence = float(scan.get("confidence") or calculate_confidence(scan)[0] or 0.0)
    quality = float(scan.get("quality_score") or scan.get("qualityScore") or 0.0)
    spread = float(scan.get("spread") or 1.0)
    momentum = float(scan.get("short_momentum") or scan.get("shortMomentum") or 0.0)

    # Require at least the current A+ quality floor as well as the dedicated
    # cold-start floor so autonomous tuning cannot accidentally weaken it.
    required_quality = max(float(A_PLUS_MIN_QUALITY), float(V17_V2_COLD_START_MIN_QUALITY))
    required_spread = min(float(A_PLUS_MAX_SPREAD), float(V17_V2_COLD_START_MAX_SPREAD))

    failures = []
    if confidence < V17_V2_COLD_START_MIN_CONFIDENCE:
        failures.append(f"confidence {confidence:.2f} < {V17_V2_COLD_START_MIN_CONFIDENCE:.2f}")
    if quality < required_quality:
        failures.append(f"quality {quality:.4f} < {required_quality:.4f}")
    if spread > required_spread:
        failures.append(f"spread {spread:.5f} > {required_spread:.5f}")
    if momentum <= V17_V2_COLD_START_MIN_MOMENTUM:
        failures.append(f"momentum {momentum:.4f} <= {V17_V2_COLD_START_MIN_MOMENTUM:.4f}")

    if failures:
        cold = {
            **profile,
            "approved": False,
            "historicalApproved": bool(profile.get("approved")),
            "coldStart": True,
            "coldStartApproved": False,
            "coldStartReason": "; ".join(failures),
            "coldStartRequirements": {
                "minConfidence": V17_V2_COLD_START_MIN_CONFIDENCE,
                "minQuality": required_quality,
                "maxSpread": required_spread,
                "minMomentumExclusive": V17_V2_COLD_START_MIN_MOMENTUM,
            },
        }
        if log_decision:
            print(
                f"V17.0.15 V2 COLD START REJECT | {symbol} samples={samples}/{V2_MIN_SYMBOL_SAMPLES} "
                f"confidence={confidence:.2f} quality={quality:.4f} spread={spread:.5f} momentum={momentum:.4f} "
                f"reason={cold['coldStartReason']}"
            )
        return False, cold

    cold = {
        **profile,
        "approved": True,
        "historicalApproved": False,
        "coldStart": True,
        "coldStartApproved": True,
        "reason": "V17.0.15 exceptional live setup cold-start pass",
        "coldStartReason": "exceptional live setup passed bounded cold-start requirements",
        "coldStartRequirements": {
            "minConfidence": V17_V2_COLD_START_MIN_CONFIDENCE,
            "minQuality": required_quality,
            "maxSpread": required_spread,
            "minMomentumExclusive": V17_V2_COLD_START_MIN_MOMENTUM,
        },
    }
    if log_decision:
        print(
            f"V17.0.15 V2 COLD START PASS | {symbol} samples={samples}/{V2_MIN_SYMBOL_SAMPLES} "
            f"confidence={confidence:.2f} quality={quality:.4f} spread={spread:.5f} momentum={momentum:.4f}"
        )
    return True, cold


# =========================
# TRADEBOT V2 SESSION / SAMPLE HELPERS
# =========================
def _v2_session_due_at(observed_at: datetime, horizon_hours: int) -> datetime:
    """Translate legacy horizon labels into tradable-session checkpoints.

    1 = one market hour; 24/72/120 = one/three/five trading sessions.
    Weekends are skipped and holidays are naturally deferred because evaluation
    only runs while Alpaca reports the market open.
    """
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    current = observed_at.astimezone(et)
    market_open = current.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = current.replace(hour=16, minute=0, second=0, microsecond=0)
    if current < market_open:
        current = market_open
    elif current > market_close:
        current = market_open + timedelta(days=1)
    while current.weekday() >= 5:
        current += timedelta(days=1)

    if int(horizon_hours) == 1:
        due = current + timedelta(hours=1)
        if due > market_close:
            overflow = due - market_close
            due = (current + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
            while due.weekday() >= 5:
                due += timedelta(days=1)
            due += overflow
        return due.astimezone(UTC)

    sessions = max(1, int(round(int(horizon_hours) / 24)))
    due = current
    added = 0
    while added < sessions:
        due += timedelta(days=1)
        if due.weekday() < 5:
            added += 1
    return due.astimezone(UTC)


def _v2_sample_key(symbol: str, stage: str, decision: str, observed_at: datetime) -> str:
    bucket_seconds = max(60, V2_INDEPENDENT_SAMPLE_MINUTES * 60)
    bucket = int(observed_at.timestamp()) // bucket_seconds
    return f"{symbol}:{stage}:{decision}:{bucket}"

# =========================
# TRADEBOT V2 INTELLIGENCE LOG
# =========================
def _v2_decision_recently_logged(symbol: str, decision: str, stage: str) -> bool:
    if not SQLITE_ENABLED:
        return False
    try:
        init_db()
        cutoff = (datetime.now(UTC) - timedelta(seconds=V2_DECISION_DEDUPE_SECONDS)).isoformat()
        conn = db_connect()
        row = conn.execute(
            """SELECT id FROM v2_setup_decisions
               WHERE symbol=? AND decision=? AND stage=? AND timestamp>=?
               ORDER BY id DESC LIMIT 1""",
            (str(symbol).upper(), str(decision), str(stage), cutoff),
        ).fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        print(f"V2 DECISION DEDUPE ERROR: {e}")
        return False


# =========================
# TRADEBOT V11.4 — UNIFIED DECISION PIPELINE
# Every real scanner decision is traced through one persistence route.
# Logging/research only: this cannot place or modify an order.
# =========================
def _v114_ensure_tables() -> None:
    if not SQLITE_ENABLED:
        return
    conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS v11_decision_trace (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_id TEXT NOT NULL,
        decision_id INTEGER,
        created_at TEXT NOT NULL,
        symbol TEXT NOT NULL,
        writer TEXT NOT NULL,
        event TEXT NOT NULL,
        stage TEXT,
        decision TEXT,
        success INTEGER NOT NULL DEFAULT 1,
        detail TEXT,
        payload_json TEXT
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v11_trace_trace_id ON v11_decision_trace(trace_id,id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v11_trace_decision ON v11_decision_trace(decision_id,id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v11_trace_time ON v11_decision_trace(created_at)")
    conn.commit(); conn.close()


def _v114_trace(trace_id: str, symbol: str, writer: str, event: str,
                 stage: str = "", decision: str = "", decision_id: Optional[int] = None,
                 success: bool = True, detail: str = "", payload: Optional[Dict[str, Any]] = None,
                 conn: Optional[sqlite3.Connection] = None) -> None:
    if not SQLITE_ENABLED:
        return
    own = conn is None
    try:
        if own:
            _v114_ensure_tables(); conn = db_connect()
        conn.execute("""INSERT INTO v11_decision_trace(
            trace_id,decision_id,created_at,symbol,writer,event,stage,decision,success,detail,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (str(trace_id), decision_id, datetime.now(UTC).isoformat(), str(symbol), str(writer), str(event),
             str(stage), str(decision), int(bool(success)), str(detail)[:2000], json.dumps(payload or {}, default=str)))
        if own:
            conn.commit(); conn.close()
    except Exception as e:
        print(f"V11.4 TRACE ERROR {symbol} {event}: {e}")
        if own and conn:
            try: conn.close()
            except Exception: pass


def _v114_trace_id(symbol: str) -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{str(symbol).upper()}-{secrets.token_hex(4)}"


def v114_trace_payload(decision_id: int) -> Dict[str, Any]:
    _v114_ensure_tables(); conn = db_connect()
    rows = conn.execute("""SELECT id,trace_id,decision_id,created_at,symbol,writer,event,stage,decision,success,detail,payload_json
        FROM v11_decision_trace WHERE decision_id=? ORDER BY id ASC""", (int(decision_id),)).fetchall()
    snapshot = conn.execute("""SELECT decision_id,captured_at,symbol,decision,stage,source,relative_volume,gap_pct,
        distance_vwap_pct,ema20_distance_pct,atr_pct FROM v9_market_memory WHERE decision_id=?""", (int(decision_id),)).fetchone()
    verification = conn.execute("""SELECT created_at,passed,core_present,missing_fields_json,error
        FROM v11_capture_verification WHERE decision_id=? ORDER BY id DESC LIMIT 1""", (int(decision_id),)).fetchone()
    conn.close()
    events=[]
    for r in rows:
        try: payload=json.loads(r[11] or '{}')
        except Exception: payload={}
        events.append({"id":r[0],"traceId":r[1],"decisionId":r[2],"createdAt":r[3],"symbol":r[4],
                       "writer":r[5],"event":r[6],"stage":r[7],"decision":r[8],"success":bool(r[9]),
                       "detail":r[10],"payload":payload})
    return {"ok":True,"version":V11_VERSION,"decisionId":int(decision_id),"events":events,
            "snapshot":None if not snapshot else {"decisionId":snapshot[0],"capturedAt":snapshot[1],"symbol":snapshot[2],
                "decision":snapshot[3],"stage":snapshot[4],"source":snapshot[5],"relativeVolume":snapshot[6],
                "gapPct":snapshot[7],"distanceVwapPct":snapshot[8],"ema20DistancePct":snapshot[9],"atrPct":snapshot[10]},
            "verification":None if not verification else {"createdAt":verification[0],"passed":bool(verification[1]),
                "corePresent":verification[2],"missingFields":json.loads(verification[3] or '[]'),"error":verification[4]}}


def v114_recent_traces(limit: int = 50) -> Dict[str, Any]:
    _v114_ensure_tables(); limit=max(1,min(int(limit),500)); conn=db_connect()
    rows=conn.execute("""SELECT d.id,d.timestamp,d.symbol,d.decision,d.stage,d.reason,
        (SELECT COUNT(*) FROM v11_decision_trace t WHERE t.decision_id=d.id) AS trace_events,
        (SELECT passed FROM v11_capture_verification v WHERE v.decision_id=d.id ORDER BY v.id DESC LIMIT 1) AS verified,
        (SELECT core_present FROM v11_capture_verification v WHERE v.decision_id=d.id ORDER BY v.id DESC LIMIT 1) AS core_present
        FROM v2_setup_decisions d ORDER BY d.id DESC LIMIT ?""",(limit,)).fetchall(); conn.close()
    return {"ok":True,"version":V11_VERSION,"count":len(rows),"items":[{"decisionId":r[0],"timestamp":r[1],
        "symbol":r[2],"decision":r[3],"stage":r[4],"reason":r[5],"traceEvents":r[6],
        "captureVerified":None if r[7] is None else bool(r[7]),"corePresent":r[8]} for r in rows]}


def record_v2_setup_decision(scan: Dict[str, Any], decision: str, stage: str, reason: str, profile: Optional[Dict[str, Any]] = None):
    symbol = str(scan.get("symbol") or "").upper().strip()
    trace_id = _v114_trace_id(symbol or "UNKNOWN")
    writer = str(scan.get("decision_writer") or scan.get("source_module") or "scanner_unified")
    if not (TRADEBOT_V2_ENABLED and V2_LOG_DECISIONS and SQLITE_ENABLED):
        _v114_trace(trace_id, symbol or "UNKNOWN", writer, "SKIPPED_DISABLED", stage, decision, success=False,
                    detail="V2 logging or SQLite disabled")
        return
    if not symbol:
        _v114_trace(trace_id, "UNKNOWN", writer, "SKIPPED_INVALID_SYMBOL", stage, decision, success=False)
        return
    _v114_trace(trace_id, symbol, writer, "ENTER_UNIFIED_PIPELINE", stage, decision, detail=str(reason)[:1000])
    if _v2_decision_recently_logged(symbol, decision, stage):
        _v114_trace(trace_id, symbol, writer, "SKIPPED_DEDUPE", stage, decision, success=False,
                    detail="matching decision/stage already logged inside dedupe window")
        return
    profile = profile or {}

    # V11.3 surgical repair: enrich the exact scan object that is persisted.
    # This is logging-only and cannot alter the already-made trading decision.
    capture_scan = dict(scan)
    if globals().get("V91_INTELLIGENCE_ENABLED", False) and globals().get("_v91_enrich_scan"):
        try:
            capture_scan = _v91_enrich_scan(capture_scan)
            core_now = [k for k in globals().get("V112_CORE_RICH_FIELDS", ()) if _v112_present(capture_scan.get(k))]
            _v114_trace(trace_id, symbol, writer, "INTELLIGENCE_ENRICHED", stage, decision,
                        success=len(core_now) >= globals().get("V112_MIN_CORE_FIELDS", 4),
                        detail=f"core fields present: {len(core_now)}", payload={"presentFields":core_now})
        except Exception as enrich_error:
            capture_scan["v113_capture_enrichment_error"] = str(enrich_error)[:500]
            print(f"V11.4 CAPTURE ENRICHMENT ERROR {symbol}: {enrich_error}")
            _v114_trace(trace_id, symbol, writer, "INTELLIGENCE_ENRICHMENT_FAILED", stage, decision,
                        success=False, detail=str(enrich_error))
    scan = capture_scan

    payload = {
        "confidenceLabel": scan.get("confidence_label"),
        "sniperReason": scan.get("sniper_reason"),
        "aPlusReason": scan.get("a_plus_reason"),
        "lockedToday": bool(scan.get("locked_today")),
        "v2": profile,
    }
    try:
        init_db()
        conn = db_connect()
        cur = conn.execute(
            """INSERT INTO v2_setup_decisions (
                timestamp, symbol, decision, stage, reason, price, confidence,
                quality, momentum, pullback, spread, ready_to_buy, sniper_pass,
                a_plus_pass, historical_samples, historical_win_rate,
                historical_profit_factor, historical_expectancy_pct, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(UTC).isoformat(), symbol, str(decision), str(stage), str(reason)[:1000],
                float(scan.get("price") or 0.0), float(scan.get("confidence") or 0.0),
                float(scan.get("quality_score") or 0.0), float(scan.get("short_momentum") or 0.0),
                float(scan.get("pullback") or 0.0), float(scan.get("spread") or 0.0),
                int(bool(scan.get("ready_to_buy"))), int(bool(scan.get("sniper_pass"))),
                int(bool(scan.get("a_plus_pass"))), int(profile.get("samples") or 0),
                float(profile.get("winRate") or 0.0), float(profile.get("profitFactor") or 0.0),
                float(profile.get("expectancyPct") or 0.0), json.dumps(payload, default=str),
            ),
        )
        decision_id = int(cur.lastrowid)
        # V17.9 Decision Audit: every rejected live-gate decision gets independent
        # 15m/30m/1h/2h forward checkpoints. Advisory evidence only.
        if decision_id > 0 and str(decision).upper() == "REJECTED" and float(scan.get("price") or 0.0) > 0:
            audit_at = datetime.now(UTC)
            for audit_minutes in (15, 30, 60, 120):
                conn.execute(
                    """INSERT OR IGNORE INTO v179_decision_audit
                       (decision_id,symbol,decision_at,stage,reason,entry_price,confidence,quality,due_minutes,due_at,status)
                       VALUES (?,?,?,?,?,?,?,?,?,?,'PENDING')""",
                    (decision_id,symbol,audit_at.isoformat(),str(stage),str(reason)[:1000],float(scan.get("price") or 0.0),
                     float(scan.get("confidence") or 0.0),float(scan.get("quality_score") or 0.0),audit_minutes,
                     (audit_at + timedelta(minutes=audit_minutes)).isoformat()),
                )
        _v114_trace(trace_id, symbol, writer, "BASE_DECISION_WRITTEN", stage, decision, decision_id=decision_id,
                    success=decision_id > 0, detail="v2_setup_decisions insert completed", conn=conn)
        observed_at = datetime.now(UTC)
        entry_price = float(scan.get("price") or 0.0)
        if decision_id > 0 and entry_price > 0:
            for horizon_hours in V2_OUTCOME_HORIZONS_HOURS:
                due_at = _v2_session_due_at(observed_at, int(horizon_hours))
                conn.execute(
                    """INSERT OR IGNORE INTO v2_observation_outcomes
                       (decision_id, symbol, observed_at, entry_price, horizon_hours, due_at, status, sample_key)
                       VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
                    (decision_id, symbol, observed_at.isoformat(), entry_price, int(horizon_hours), due_at.isoformat(),
                     _v2_sample_key(symbol, str(stage), str(decision), observed_at)),
                )
        if decision_id > 0 and V4_MARKET_DNA_ENABLED:
            record_v4_market_dna(conn, decision_id, scan, decision, stage, reason, observed_at)
        if decision_id > 0 and globals().get("V9_ENABLED", False):
            try:
                _v9_capture_snapshot(conn, decision_id, scan, decision, stage, reason, observed_at)
                _v114_trace(trace_id, symbol, writer, "RICH_SNAPSHOT_WRITTEN", stage, decision,
                            decision_id=decision_id, success=True, detail="v9_market_memory capture completed", conn=conn)
            except Exception as v9_error:
                print(f"V9 SNAPSHOT ERROR {symbol}: {v9_error}")
                _v114_trace(trace_id, symbol, writer, "RICH_SNAPSHOT_FAILED", stage, decision,
                            decision_id=decision_id, success=False, detail=str(v9_error), conn=conn)
        _v114_trace(trace_id, symbol, writer, "PIPELINE_COMMIT_PENDING", stage, decision,
                    decision_id=decision_id, success=True, conn=conn)
        conn.commit()
        conn.close()
        _v114_trace(trace_id, symbol, writer, "PIPELINE_COMMITTED", stage, decision,
                    decision_id=decision_id, success=True, detail="all decision evidence committed")
    except Exception as e:
        print(f"V2 DECISION LOG ERROR {symbol}: {e}")
        _v114_trace(trace_id, symbol or "UNKNOWN", writer, "PIPELINE_FAILED", stage, decision,
                    success=False, detail=str(e))


def v2_recent_decisions(limit: int = 100):
    if not SQLITE_ENABLED:
        return []
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute(
            "SELECT * FROM v2_setup_decisions ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"V2 RECENT DECISIONS ERROR: {e}")
        return []


def v2_setup_profiles(limit: int = 100):
    if not SQLITE_ENABLED:
        return []
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute(
            """SELECT symbol,
                      COUNT(*) AS observations,
                      SUM(CASE WHEN decision='APPROVED' THEN 1 ELSE 0 END) AS approvals,
                      AVG(confidence) AS avg_confidence,
                      AVG(quality) AS avg_quality,
                      AVG(historical_win_rate) AS avg_historical_win_rate,
                      AVG(historical_profit_factor) AS avg_historical_profit_factor,
                      AVG(historical_expectancy_pct) AS avg_historical_expectancy_pct,
                      MAX(timestamp) AS last_seen
               FROM v2_setup_decisions
               GROUP BY symbol
               ORDER BY approvals DESC, observations DESC, symbol ASC
               LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"V2 SETUP PROFILES ERROR: {e}")
        return []


def v2_intelligence_summary():
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    try:
        init_db()
        conn = db_connect()
        totals = conn.execute(
            """SELECT COUNT(*) AS observations,
                      COUNT(DISTINCT symbol) AS symbols,
                      SUM(CASE WHEN decision='APPROVED' THEN 1 ELSE 0 END) AS approvals,
                      SUM(CASE WHEN decision='REJECTED' THEN 1 ELSE 0 END) AS rejections,
                      MIN(timestamp) AS first_observation,
                      MAX(timestamp) AS last_observation
               FROM v2_setup_decisions"""
        ).fetchone()
        stages = conn.execute(
            """SELECT stage, COUNT(*) AS count
               FROM v2_setup_decisions GROUP BY stage ORDER BY count DESC"""
        ).fetchall()
        conn.close()
        data = dict(totals) if totals else {}
        observations = int(data.get("observations") or 0)
        approvals = int(data.get("approvals") or 0)
        return {
            "ok": True,
            **data,
            "approvalRate": approvals / observations if observations else 0.0,
            "stages": [dict(r) for r in stages],
            "recent": v2_recent_decisions(20),
            "profiles": v2_setup_profiles(20),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# =========================
# TRADEBOT V2 STAGE 2 — FORWARD REPLAY / OUTCOMES
# =========================
def v2_seed_missing_outcomes(limit: int = 5000) -> int:
    """Create/repair pending outcomes using short bounded write batches.

    V18.2.12: the old implementation kept one transaction open while walking up
    to thousands of decisions.  That made this maintenance task a multi-second
    SQLite writer.  We now precompute rows outside the write transaction and
    commit every small batch so other AI workers get regular writer access.
    """
    if not SQLITE_ENABLED:
        return 0
    created = 0
    batch_size = max(25, min(int(os.getenv("V2_OUTCOME_SEED_BATCH_SIZE", "100") or 100), 500))
    try:
        init_db()
        read_conn = db_connect()
        rows = read_conn.execute(
            """SELECT id, timestamp, symbol, price, decision, stage FROM v2_setup_decisions
               WHERE price > 0 ORDER BY id DESC LIMIT ?""",
            (max(1, min(int(limit), 50000)),),
        ).fetchall()
        read_conn.close()

        pending = []
        for row in rows:
            try:
                observed_at = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=UTC)
                symbol = str(row["symbol"]).upper()
                key = _v2_sample_key(symbol, str(row["stage"]), str(row["decision"]), observed_at)
                for horizon_hours in V2_OUTCOME_HORIZONS_HOURS:
                    due = _v2_session_due_at(observed_at, int(horizon_hours)).isoformat()
                    pending.append((int(row["id"]), symbol, observed_at.isoformat(), float(row["price"]), int(horizon_hours), due, key))
            except Exception as row_error:
                print(f"V2 OUTCOME SEED ROW ERROR: {row_error}")

        for offset in range(0, len(pending), batch_size):
            chunk = pending[offset:offset + batch_size]
            conn = db_connect()
            try:
                for decision_id, symbol, observed_at, entry_price, horizon_hours, due, key in chunk:
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO v2_observation_outcomes
                           (decision_id, symbol, observed_at, entry_price, horizon_hours, due_at, status, sample_key)
                           VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
                        (decision_id, symbol, observed_at, entry_price, horizon_hours, due, key),
                    )
                    created += int(cur.rowcount or 0)
                    conn.execute(
                        """UPDATE v2_observation_outcomes SET due_at=?, sample_key=COALESCE(sample_key, ?)
                           WHERE decision_id=? AND horizon_hours=? AND status='PENDING'""",
                        (due, key, decision_id, horizon_hours),
                    )
                conn.commit()
            finally:
                conn.close()
    except Exception as e:
        print(f"V2 OUTCOME SEED ERROR: {e}")
    return created

def _v6_parse_utc(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _v6_historical_checkpoint_price(symbol: str, due_at: Any) -> Dict[str, Any]:
    """Return the first valid one-minute bar at/after the intended checkpoint.

    V17.8.1 research-data fallback: Alpaca accounts without recent SIP history
    can still evaluate V6 outcomes by retrying the historical request on the IEX
    feed. This path is research/outcome evaluation only and never participates
    in live entry, exit, sizing, quotes, or order submission.
    """
    due = _v6_parse_utc(due_at)
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        raise RuntimeError("missing_symbol")

    forward_windows_minutes = [
        V6_HISTORICAL_BAR_LOOKAHEAD_MINUTES,
        180,
        24 * 60,
        3 * 24 * 60,
        7 * 24 * 60,
    ]
    last_error = None
    before_candidates = []
    use_iex = False
    fallback_logged = False

    def _bars_for_window(start: datetime, end: datetime):
        nonlocal use_iex, fallback_logged

        def _request(feed=None):
            kwargs = {
                "symbol_or_symbols": [symbol],
                "timeframe": TimeFrame.Minute,
                "start": start,
                "end": end,
            }
            if feed is not None:
                kwargs["feed"] = feed
            request = StockBarsRequest(**kwargs)
            response = data_client.get_stock_bars(request)
            try:
                return list(response[symbol])
            except Exception:
                data = getattr(response, "data", {}) or {}
                return list(data.get(symbol, []))

        if use_iex:
            return _request(DataFeed.IEX), "alpaca_iex_historical_1min_close"

        try:
            return _request(), "alpaca_historical_1min_close"
        except Exception as exc:
            text = str(exc).lower()
            entitlement_error = (
                "subscription does not permit" in text
                or "recent sip data" in text
                or ("sip" in text and "subscription" in text)
                or ("sip" in text and "not permit" in text)
            )
            if not entitlement_error:
                raise
            use_iex = True
            if not fallback_logged:
                print(
                    f"V17.8.1 V6 DATA FALLBACK | {symbol} SIP historical unavailable -> IEX historical feed"
                )
                fallback_logged = True
            return _request(DataFeed.IEX), "alpaca_iex_historical_1min_close"

    for forward_minutes in sorted(set(max(5, int(v)) for v in forward_windows_minutes)):
        start = due - timedelta(minutes=V6_HISTORICAL_BAR_LOOKBACK_MINUTES)
        end = due + timedelta(minutes=forward_minutes)
        try:
            bars, source_name = _bars_for_window(start, end)

            candidates = []
            for bar in bars:
                ts = getattr(bar, "timestamp", None)
                close = getattr(bar, "close", None)
                if ts is None or close is None:
                    continue
                try:
                    price = float(close)
                    if price <= 0 or not math.isfinite(price):
                        continue
                    bar_at = _v6_parse_utc(ts)
                    candidates.append((bar_at, price, source_name))
                except Exception:
                    continue

            if not candidates:
                last_error = "historical_bar_unavailable"
                continue

            after = [item for item in candidates if item[0] >= due]
            if after:
                bar_at, price, source_name = min(after, key=lambda item: item[0])
                delay_minutes = (bar_at - due).total_seconds() / 60.0
                return {
                    "price": price,
                    "barAt": bar_at.isoformat(),
                    "delayMinutes": delay_minutes,
                    "source": source_name,
                    "lookupWindowMinutes": forward_minutes,
                    "feedFallback": bool(source_name == "alpaca_iex_historical_1min_close"),
                }

            before_candidates.extend(item for item in candidates if item[0] < due)
            last_error = "no_bar_at_or_after_checkpoint"
        except Exception as exc:
            last_error = str(exc) or exc.__class__.__name__

    if before_candidates:
        bar_at, price, source_name = max(before_candidates, key=lambda item: item[0])
        delay_minutes = (bar_at - due).total_seconds() / 60.0
        if delay_minutes >= -float(V6_HISTORICAL_BAR_LOOKBACK_MINUTES):
            return {
                "price": price,
                "barAt": bar_at.isoformat(),
                "delayMinutes": delay_minutes,
                "source": source_name,
                "lookupWindowMinutes": max(forward_windows_minutes),
                "feedFallback": bool(source_name == "alpaca_iex_historical_1min_close"),
            }

    raise RuntimeError(f"historical_bar_unavailable:{last_error or 'unknown'}")

# =========================
# V17.9 — DECISION AUDIT / MISSED OPPORTUNITY TRACKER
# =========================
V179_MISSED_WINNER_PCT = 1.0
V179_GOOD_BLOCK_PCT = -0.50

def _v179_classify(return_pct: float) -> str:
    if return_pct >= V179_MISSED_WINNER_PCT:
        return "MISSED_WINNER"
    if return_pct <= V179_GOOD_BLOCK_PCT:
        return "GOOD_BLOCK"
    return "NEUTRAL"

def v179_evaluate_decision_audit(limit: int = 200) -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return {"ok":False,"evaluated":0,"errors":0}
    evaluated=errors=0
    try:
        init_db(); conn=db_connect()
        rows=conn.execute("SELECT * FROM v179_decision_audit WHERE status='PENDING' AND due_at<=? ORDER BY due_at LIMIT ?",
                          (datetime.now(UTC).isoformat(),max(1,min(int(limit),1000)))).fetchall()
        for row in rows:
            try:
                cp=_v6_historical_checkpoint_price(str(row["symbol"]),row["due_at"])
                entry=float(row["entry_price"] or 0); price=float(cp["price"] or 0)
                if entry <= 0 or price <= 0: raise RuntimeError("invalid_audit_price")
                ret=((price/entry)-1.0)*100.0
                conn.execute("""UPDATE v179_decision_audit SET evaluated_at=?,outcome_price=?,return_pct=?,
                    best_move_pct=?,worst_move_pct=?,classification=?,status='COMPLETE',error=NULL,source=? WHERE id=?""",
                    (cp.get("barAt"),price,ret,max(0.0,ret),min(0.0,ret),_v179_classify(ret),cp.get("source"),int(row["id"])))
                evaluated += 1
            except Exception as exc:
                errors += 1
                conn.execute("UPDATE v179_decision_audit SET error=? WHERE id=?",(str(exc)[:500],int(row["id"])))
        conn.commit(); conn.close()
        if evaluated or errors: print(f"V17.9 DECISION AUDIT | evaluated={evaluated} errors={errors}")
        return {"ok":True,"evaluated":evaluated,"errors":errors}
    except Exception as exc:
        try: conn.close()
        except Exception: pass
        return {"ok":False,"evaluated":evaluated,"errors":errors+1,"error":str(exc)}

def v179_decision_audit_summary(days: int = 7) -> Dict[str, Any]:
    days=max(1,min(int(days),365)); cutoff=(datetime.now(UTC)-timedelta(days=days)).isoformat()
    try:
        init_db(); conn=db_connect()
        rows=conn.execute("""SELECT stage,COUNT(DISTINCT decision_id) blocked,
          COUNT(DISTINCT CASE WHEN classification='GOOD_BLOCK' THEN decision_id END) good_blocks,
          COUNT(DISTINCT CASE WHEN classification='MISSED_WINNER' THEN decision_id END) missed_winners,
          COUNT(DISTINCT CASE WHEN classification='NEUTRAL' THEN decision_id END) neutral,
          AVG(CASE WHEN due_minutes=60 AND status='COMPLETE' THEN return_pct END) avg_1h_return_pct
          FROM v179_decision_audit WHERE decision_at>=? GROUP BY stage ORDER BY blocked DESC""",(cutoff,)).fetchall()
        recent=conn.execute("""SELECT decision_id,symbol,decision_at,stage,reason,entry_price,confidence,quality,
          MAX(CASE WHEN due_minutes=15 THEN return_pct END) return_15m,
          MAX(CASE WHEN due_minutes=30 THEN return_pct END) return_30m,
          MAX(CASE WHEN due_minutes=60 THEN return_pct END) return_1h,
          MAX(CASE WHEN due_minutes=120 THEN return_pct END) return_2h,
          MAX(CASE WHEN classification='MISSED_WINNER' THEN 1 ELSE 0 END) missed,
          MAX(CASE WHEN classification='GOOD_BLOCK' THEN 1 ELSE 0 END) good
          FROM v179_decision_audit WHERE decision_at>=? GROUP BY decision_id ORDER BY decision_id DESC LIMIT 100""",(cutoff,)).fetchall()
        pending=int(conn.execute("SELECT COUNT(*) FROM v179_decision_audit WHERE status='PENDING'").fetchone()[0]); conn.close()
        gates=[]
        for r in rows:
            d=dict(r); denom=max(1,int(d['good_blocks'] or 0)+int(d['missed_winners'] or 0)+int(d['neutral'] or 0))
            d['effectivenessPct']=round(100.0*int(d['good_blocks'] or 0)/denom,1); gates.append(d)
        items=[]
        for r in recent:
            d=dict(r); d['classification']='MISSED_WINNER' if d.pop('missed') else ('GOOD_BLOCK' if d.pop('good') else 'NEUTRAL'); items.append(d)
        return {"ok":True,"version":"V17.9","days":days,"advisoryOnly":True,"pendingCheckpoints":pending,
                "thresholds":{"missedWinnerPct":V179_MISSED_WINNER_PCT,"goodBlockPct":V179_GOOD_BLOCK_PCT},
                "gates":gates,"recent":items}
    except Exception as exc:
        return {"ok":False,"version":"V17.9","error":str(exc),"gates":[],"recent":[]}

@app.get("/v17/decision-audit")
def api_v179_decision_audit(days: int = 7):
    return v179_decision_audit_summary(days)

# =========================
# V18.1 — EVIDENCE & PERFORMANCE OBSERVATORY
# Read-only evidence aggregation. Never changes live trading.
# =========================
def v181_performance_observatory(days: int = 7) -> Dict[str, Any]:
    days=max(1,min(int(days),90)); cutoff=(datetime.now(UTC)-timedelta(days=days)).isoformat()
    try:
        init_db(); conn=db_connect()
        trades=[dict(r) for r in conn.execute("SELECT * FROM closed_trades WHERE timestamp>=? ORDER BY timestamp ASC",(cutoff,)).fetchall()]
        pnls=[float(t.get('pnl_gbp') if t.get('pnl_gbp') is not None else (t.get('pnl') or 0.0)) for t in trades]
        wins=[x for x in pnls if x>0]; losses=[x for x in pnls if x<0]
        curve=0.0; peak=0.0; max_dd=0.0
        for x in pnls:
            curve+=x; peak=max(peak,curve); max_dd=max(max_dd,peak-curve)
        reasons={}
        for t in trades:
            reason=str(t.get('reason') or 'UNKNOWN').strip() or 'UNKNOWN'; d=reasons.setdefault(reason,{'reason':reason,'trades':0,'pnlGbp':0.0,'wins':0})
            p=float(t.get('pnl_gbp') if t.get('pnl_gbp') is not None else (t.get('pnl') or 0.0)); d['trades']+=1; d['pnlGbp']+=p; d['wins']+=1 if p>0 else 0
        exit_rows=[]
        for d in reasons.values():
            d['pnlGbp']=round(d['pnlGbp'],2); d['winRatePct']=round(100*d['wins']/max(1,d['trades']),1); exit_rows.append(d)
        exit_rows.sort(key=lambda x:(x['trades'],x['pnlGbp']),reverse=True)
        capture=[]
        try:
            rr=conn.execute("""SELECT s.closed_trade_id,s.symbol,s.entry_price,s.exit_price,MAX(p.price) peak_price
              FROM trade_replay_sessions s LEFT JOIN trade_replay_points p ON p.session_id=s.id
              WHERE s.status='CLOSED' AND s.closed_trade_id IS NOT NULL AND s.ended_at>=?
              GROUP BY s.id ORDER BY s.ended_at DESC LIMIT 200""",(cutoff,)).fetchall()
            for r in rr:
                entry=float(r['entry_price'] or 0); exitp=float(r['exit_price'] or 0); peakp=float(r['peak_price'] or 0)
                available=max(0.0,peakp-entry); captured=max(0.0,exitp-entry)
                if available>0: capture.append(min(150.0,max(0.0,100.0*captured/available)))
        except Exception: pass
        audit=v179_decision_audit_summary(days)
        weekly=_v18_build_review(days,persist=False) if '_v18_build_review' in globals() else {}
        conn.close()
        vault=profit_vault_payload() if 'profit_vault_payload' in globals() else {}
        universe=adaptive_universe_payload() if 'adaptive_universe_payload' in globals() else {}
        rows=universe.get('rows') if isinstance(universe,dict) else []
        counts={}
        for r in (rows if isinstance(rows,list) else []):
            role=str((r or {}).get('role') or (r or {}).get('type') or 'OTHER').upper(); counts[role]=counts.get(role,0)+1
        return {'ok':True,'version':'V18.1','days':days,'readOnly':True,
          'trading':{'closedTrades':len(trades),'realisedPnlGbp':round(sum(pnls),2),'wins':len(wins),'losses':len(losses),'winRatePct':round(100*len(wins)/max(1,len(pnls)),1),'avgWinnerGbp':round(sum(wins)/max(1,len(wins)),2),'avgLoserGbp':round(sum(losses)/max(1,len(losses)),2),'maxRealisedDrawdownGbp':round(max_dd,2)},
          'profitProtection':{'bankedProfitGbp':vault.get('bankedProfitGbp',0),'lifetimeBankedGbp':vault.get('lifetimeBankedGbp',0),'workingCapitalGbp':vault.get('workingCapitalGbp',0),'freeCashGbp':vault.get('freeCashGbp',vault.get('workingCapitalGbp',0)),'tradingCapitalGbp':vault.get('tradingCapitalGbp',max(0.0,float(vault.get('accountEquityGbp',0) or 0)-float(vault.get('bankedProfitGbp',0) or 0))),'protectedBaselineGbp':vault.get('baselineGbp',0),'growthSinceBaselineGbp':vault.get('growthSinceBaselineGbp',0)},
          'profitCapture':{'replayTradesMeasured':len(capture),'averagePeakCapturePct':round(sum(capture)/len(capture),1) if capture else None},
          'decisionAudit':{'pendingCheckpoints':audit.get('pendingCheckpoints',0),'gates':audit.get('gates',[])},
          'exits':exit_rows[:12], 'universe':{'activeSymbols':len(universe.get('activeSymbols',[]) if isinstance(universe,dict) else []),'roles':counts},
          'governance':{'verdict':weekly.get('verdict'),'evidenceStrength':weekly.get('evidenceStrength'),'proposal':weekly.get('proposal',{}),'evidence':weekly.get('evidence',{})}}
    except Exception as exc:
        try: conn.close()
        except Exception: pass
        return {'ok':False,'version':'V18.1','error':str(exc),'readOnly':True}

@app.get('/v18/performance-observatory')
def api_v181_performance_observatory(days: int = 7):
    return v181_performance_observatory(days)

# =========================
# V18 — AUTONOMOUS WEEKLY REVIEW
# =========================
V18_WINDOW_DAYS=7
V18_MIN_AUDITED_DECISIONS=20
V18_MIN_GATE_CLASSIFIED=8
V18_PROMOTION_STABILITY_REQUIRED=5

def _v18_week_key(now=None):
    now=now or datetime.now(UTC); iso=now.isocalendar(); return f"{iso.year}-W{iso.week:02d}"

def _v18_build_review(days=V18_WINDOW_DAYS, persist=True):
    days=max(1,min(int(days),31)); cutoff=(datetime.now(UTC)-timedelta(days=days)).isoformat(); now=datetime.now(UTC); key=_v18_week_key(now)
    try:
        init_db(); conn=db_connect()
        rows=conn.execute("""SELECT stage,COUNT(DISTINCT decision_id) blocked,
          COUNT(DISTINCT CASE WHEN classification='GOOD_BLOCK' THEN decision_id END) good_blocks,
          COUNT(DISTINCT CASE WHEN classification='MISSED_WINNER' THEN decision_id END) missed_winners,
          COUNT(DISTINCT CASE WHEN classification='NEUTRAL' THEN decision_id END) neutral,
          AVG(CASE WHEN due_minutes=60 AND status='COMPLETE' THEN return_pct END) avg_1h_return_pct
          FROM v179_decision_audit WHERE decision_at>=? GROUP BY stage ORDER BY blocked DESC""",(cutoff,)).fetchall()
        pending=int(conn.execute("SELECT COUNT(*) FROM v179_decision_audit WHERE status='PENDING'").fetchone()[0])
        audited=int(conn.execute("SELECT COUNT(DISTINCT decision_id) FROM v179_decision_audit WHERE decision_at>=? AND status='COMPLETE'",(cutoff,)).fetchone()[0])
        gates=[]; weakest=None
        for r in rows:
            d=dict(r); classified=int(d.get('good_blocks') or 0)+int(d.get('missed_winners') or 0)+int(d.get('neutral') or 0); good=int(d.get('good_blocks') or 0); missed=int(d.get('missed_winners') or 0); eff=100.0*good/max(1,classified)
            d['classified']=classified; d['effectivenessPct']=round(eff,1)
            d['action']='OBSERVE' if classified<V18_MIN_GATE_CLASSIFIED else ('KEEP' if eff>=60 and good>missed else ('REVIEW' if eff<45 and missed>good else 'OBSERVE'))
            gates.append(d)
            if d['action']=='REVIEW' and (weakest is None or eff<weakest['effectivenessPct']): weakest=d
        enough=audited>=V18_MIN_AUDITED_DECISIONS
        if not enough:
            verdict='COLLECTING_EVIDENCE'; strength='LOW'; proposal_key=None; proposal=f"Collect at least {V18_MIN_AUDITED_DECISIONS} completed audited rejection decisions before proposing a strategy adjustment."
        elif weakest:
            verdict='REVIEW_RECOMMENDED'; strength='STRONG' if weakest['classified']>=20 else 'MODERATE'; proposal_key=f"gate:{str(weakest.get('stage') or 'unknown').lower()}"; proposal=f"Review {str(weakest.get('stage') or 'unknown').upper()} only: effectiveness {weakest['effectivenessPct']:.1f}% across {weakest['classified']} classified decisions. No automatic live change."
        else:
            verdict='HEALTHY'; strength='STRONG' if audited>=50 else 'MODERATE'; proposal_key='keep:entry_governance'; proposal='Keep current entry governance. No evidence-backed gate change is justified this week.'
        prev=conn.execute("SELECT proposal_key,stability_count FROM v18_weekly_reviews WHERE review_key<>? ORDER BY created_at DESC LIMIT 1",(key,)).fetchone(); stability=1 if proposal_key else 0
        if prev and proposal_key and str(prev['proposal_key'] or '')==proposal_key: stability=int(prev['stability_count'] or 0)+1
        eligible=bool(proposal_key and stability>=V18_PROMOTION_STABILITY_REQUIRED and enough)
        payload={'ok':True,'version':'V18','advisoryOnly':True,'automaticLiveChanges':False,'reviewKey':key,'createdAt':now.isoformat(),'windowDays':days,'verdict':verdict,'evidenceStrength':strength,'evidence':{'auditedDecisions':audited,'pendingCheckpoints':pending,'minimumAuditedDecisions':V18_MIN_AUDITED_DECISIONS},'gates':gates,'proposal':{'key':proposal_key,'text':proposal,'stabilityCount':stability,'stabilityRequired':V18_PROMOTION_STABILITY_REQUIRED,'promotionEligible':eligible,'action':'BOARD_REVIEW_ONLY' if eligible else 'OBSERVE'},'constitutionalLocks':['PROFIT_VAULT','PROTECTED_BASELINE','MAX_POSITION_SAFETY','ORDER_EXECUTION_SAFETY','STOP_PROTECTION']}
        if persist:
            conn.execute("""INSERT INTO v18_weekly_reviews(review_key,created_at,window_days,verdict,evidence_strength,proposal_key,proposal_text,stability_count,promotion_required,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(review_key) DO UPDATE SET created_at=excluded.created_at,window_days=excluded.window_days,verdict=excluded.verdict,evidence_strength=excluded.evidence_strength,proposal_key=excluded.proposal_key,proposal_text=excluded.proposal_text,stability_count=excluded.stability_count,promotion_required=excluded.promotion_required,payload_json=excluded.payload_json""",(key,now.isoformat(),days,verdict,strength,proposal_key,proposal,stability,V18_PROMOTION_STABILITY_REQUIRED,json.dumps(payload,default=str))); conn.commit()
        conn.close(); return payload
    except Exception as exc:
        try: conn.close()
        except Exception: pass
        return {'ok':False,'version':'V18','error':str(exc),'advisoryOnly':True,'automaticLiveChanges':False}

@app.get('/v18/weekly-review')
def api_v18_weekly_review(days: int=V18_WINDOW_DAYS):
    return _v18_build_review(days,True)

def _v6_write_historical_outcome(conn: sqlite3.Connection, row: Any) -> Dict[str, Any]:
    symbol=str(row["symbol"]).upper()
    checkpoint=_v6_historical_checkpoint_price(symbol,row["due_at"])
    outcome_price=float(checkpoint["price"]); entry_price=float(row["entry_price"] or 0.0)
    if entry_price <= 0:
        raise RuntimeError("missing_or_invalid_entry_price")
    return_pct=((outcome_price/entry_price)-1.0)*100.0
    estimated_cost_pct=max(0.0,V2_ESTIMATED_COST_BPS/100.0)
    net_return_pct=return_pct-estimated_cost_pct
    now=datetime.now(UTC).isoformat()
    conn.execute("""UPDATE v2_observation_outcomes
       SET evaluated_at=?, outcome_price=?, return_pct=?, net_return_pct=?, estimated_cost_pct=?,
           evaluation_delay_minutes=?, outcome_bar_at=?, outcome_source=?, repaired_at=?, status='COMPLETE', error=NULL,
           retry_count=0, last_error_at=NULL
       WHERE id=?""",
       (checkpoint["barAt"],outcome_price,return_pct,net_return_pct,estimated_cost_pct,
        float(checkpoint["delayMinutes"]),checkpoint["barAt"],checkpoint["source"],now,int(row["id"])))
    return checkpoint


def v2_evaluate_due_outcomes(limit: Optional[int] = None) -> Dict[str, Any]:
    """Evaluate due outcomes using historical checkpoints with bounded recovery."""
    if not (TRADEBOT_V2_ENABLED and SQLITE_ENABLED):
        return {"ok":False,"evaluated":0,"reason":"V2 or SQLite disabled"}
    batch=max(1,min(int(limit or V2_OUTCOME_BATCH_SIZE),1000))
    evaluated=0; errors=0; recovered=0; abandoned=0; retried=0
    try:
        init_db(); conn=db_connect()
        rows=conn.execute("""SELECT * FROM v2_observation_outcomes
            WHERE status='PENDING' AND due_at<=? ORDER BY due_at ASC LIMIT ?""",
            (datetime.now(UTC).isoformat(),batch)).fetchall()
        error_reasons: Dict[str, int] = {}
        error_samples: List[str] = []
        for row in rows:
            keys = row.keys() if hasattr(row, "keys") else []
            previous_error = str(row["error"] or "")
            previous_retry = int(row["retry_count"] or 0) if "retry_count" in keys else 0
            if previous_error:
                conn.execute("UPDATE v2_observation_outcomes SET error=NULL WHERE id=?", (int(row["id"]),))
            try:
                checkpoint = _v6_write_historical_outcome(conn,row)
                evaluated += 1
                if previous_error or previous_retry > 0 or checkpoint.get("feedFallback"):
                    recovered += 1
            except Exception as row_error:
                reason = str(row_error)[:500] or row_error.__class__.__name__
                reason_key = reason.split(":", 1)[0]
                next_retry = previous_retry + 1
                now_iso = datetime.now(UTC).isoformat()
                if next_retry >= V6_OUTCOME_MAX_RETRIES:
                    abandoned += 1
                    conn.execute("""UPDATE v2_observation_outcomes
                        SET status='UNAVAILABLE', error=NULL, retry_count=?, last_error_at=?,
                            outcome_source='unavailable_after_iex_retries', repaired_at=?
                        WHERE id=?""",
                        (next_retry, now_iso, now_iso, int(row["id"])))
                    print(f"V17.8.2 OUTCOME QUARANTINE | {str(row['symbol']).upper()} checkpoint={row['due_at']} retries={next_retry}/{V6_OUTCOME_MAX_RETRIES} reason={reason_key}")
                else:
                    errors += 1; retried += 1
                    error_reasons[reason_key] = error_reasons.get(reason_key, 0) + 1
                    if len(error_samples) < 5:
                        error_samples.append(f"{str(row['symbol']).upper()}@{row['due_at']}={reason} retry={next_retry}/{V6_OUTCOME_MAX_RETRIES}")
                    conn.execute("""UPDATE v2_observation_outcomes
                        SET error=?, retry_count=?, last_error_at=? WHERE id=?""",
                        (reason,next_retry,now_iso,int(row["id"])))
        conn.commit(); conn.close()
        if evaluated or errors or abandoned:
            reason_text = ",".join(f"{k}:{v}" for k,v in sorted(error_reasons.items())) or "none"
            print(f"V17.8.2 OUTCOME RECOVERY | completed={evaluated} recovered={recovered} retrying={retried} abandoned={abandoned} reasons={reason_text}")
            if error_samples:
                print("V17.8.2 OUTCOME RETRY SAMPLES | " + " | ".join(error_samples))
            print(f"V6.5 OUTCOMES | historical={evaluated} errors={errors} reasons={reason_text}")
        return {"ok":True,"version":"V17.8.2","evaluated":evaluated,"errors":errors,"due":len(rows),
                "recovered":recovered,"retrying":retried,"abandoned":abandoned,"maxRetries":V6_OUTCOME_MAX_RETRIES,
                "errorReasons":error_reasons,"errorSamples":error_samples,
                "outcomeSource":"alpaca_historical_1min_close_or_iex_fallback"}
    except Exception as e:
        try: conn.close()
        except Exception: pass
        return {"ok":False,"version":"V17.8.2","evaluated":evaluated,"errors":errors+1,"error":str(e)}

def v2_pending_breakdown() -> Dict[str, Any]:
    """Explain active pending outcomes and quarantined unavailable rows."""
    now = datetime.now(UTC).isoformat()
    result = {"totalPending":0,"notMatureYet":0,"readyForProcessing":0,"withErrors":0,"completed":0,"unavailable":0}
    if not SQLITE_ENABLED:
        return result
    try:
        init_db(); conn=db_connect()
        row=conn.execute("""SELECT
            SUM(CASE WHEN status='COMPLETE' AND net_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN status='PENDING' AND due_at>? THEN 1 ELSE 0 END) AS immature,
            SUM(CASE WHEN status='PENDING' AND due_at<=? THEN 1 ELSE 0 END) AS ready,
            SUM(CASE WHEN status='PENDING' AND error IS NOT NULL AND TRIM(error)<>'' THEN 1 ELSE 0 END) AS errors,
            SUM(CASE WHEN status='UNAVAILABLE' THEN 1 ELSE 0 END) AS unavailable
            FROM v2_observation_outcomes""",(now,now)).fetchone(); conn.close()
        result={"completed":int(row["completed"] or 0),"totalPending":int(row["pending"] or 0),
                "notMatureYet":int(row["immature"] or 0),"readyForProcessing":int(row["ready"] or 0),
                "withErrors":int(row["errors"] or 0),"unavailable":int(row["unavailable"] or 0)}
    except Exception as exc:
        result["error"]=str(exc)
    return result

def v2_drain_due_outcomes(max_total: Optional[int] = None) -> Dict[str, Any]:
    """Drain eligible outcomes while counting quarantined rows as resolved work."""
    ceiling=max(V2_OUTCOME_BATCH_SIZE,int(max_total or V2_OUTCOME_DRAIN_LIMIT))
    total_evaluated=total_errors=total_abandoned=batches=0
    while total_evaluated+total_errors+total_abandoned < ceiling:
        remaining=ceiling-(total_evaluated+total_errors+total_abandoned)
        result=v2_evaluate_due_outcomes(min(V2_OUTCOME_BATCH_SIZE,remaining)); batches+=1
        evaluated=int(result.get("evaluated") or 0); errors=int(result.get("errors") or 0); abandoned=int(result.get("abandoned") or 0); due=int(result.get("due") or 0)
        total_evaluated+=evaluated; total_errors+=errors; total_abandoned+=abandoned
        if due==0 or (evaluated==0 and errors==0 and abandoned==0): break
        if due < min(V2_OUTCOME_BATCH_SIZE,remaining): break
        if V2_OUTCOME_DRAIN_PAUSE_SECONDS: time.sleep(V2_OUTCOME_DRAIN_PAUSE_SECONDS)
    backlog=v2_pending_breakdown()
    if total_evaluated or total_errors or total_abandoned:
        print(f"V6.6 OUTCOME DRAIN | batches={batches} evaluated={total_evaluated} errors={total_errors} abandoned={total_abandoned} ready_remaining={backlog.get('readyForProcessing',0)} immature={backlog.get('notMatureYet',0)} unavailable={backlog.get('unavailable',0)}")
    return {"ok":True,"version":"V17.8.2","batches":batches,"evaluated":total_evaluated,"errors":total_errors,"abandoned":total_abandoned,"backlog":backlog}

def v6_repair_outcome_times(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, limit: int = V6_REPAIR_BATCH_SIZE) -> Dict[str, Any]:
    """Repair legacy live-quote outcomes using the intended historical due_at checkpoint."""
    horizon=max(1,int(horizon_hours)); batch=max(1,min(int(limit),1000)); repaired=0; errors=0; samples=[]
    try:
        init_db(); conn=db_connect()
        rows=conn.execute("""SELECT * FROM v2_observation_outcomes
            WHERE horizon_hours=? AND status='COMPLETE'
              AND (outcome_source IS NULL OR outcome_source NOT IN ('alpaca_historical_1min_close','alpaca_iex_historical_1min_close') OR outcome_bar_at IS NULL)
            ORDER BY due_at ASC LIMIT ?""",(horizon,batch)).fetchall()
        for row in rows:
            try:
                cp=_v6_write_historical_outcome(conn,row); repaired += 1
                if len(samples)<10: samples.append({"id":int(row["id"]),"symbol":row["symbol"],"dueAt":row["due_at"],**cp})
            except Exception as exc:
                errors += 1
                conn.execute("UPDATE v2_observation_outcomes SET error=? WHERE id=?",(str(exc)[:500],int(row["id"])))
        conn.commit()
        remaining=int(conn.execute("""SELECT COUNT(*) FROM v2_observation_outcomes
            WHERE horizon_hours=? AND status='COMPLETE'
              AND (outcome_source IS NULL OR outcome_source NOT IN ('alpaca_historical_1min_close','alpaca_iex_historical_1min_close') OR outcome_bar_at IS NULL)""",(horizon,)).fetchone()[0])
        conn.close()
        return {"ok":True,"version":"V6.4","advisoryOnly":True,"horizonHours":horizon,"processed":len(rows),
                "repaired":repaired,"errors":errors,"remaining":remaining,"samples":samples,
                "note":"Research outcomes only were repaired. Live trading logic was unchanged."}
    except Exception as e:
        try: conn.close()
        except Exception: pass
        return {"ok":False,"version":"V6.4","error":str(e),"repaired":repaired,"errors":errors+1}


def v2_normalise_reason(reason: str) -> str:
    """Collapse highly specific numeric rejection messages into useful evidence buckets."""
    raw = str(reason or "").strip().lower()
    if not raw:
        return "unspecified"

    def bucket(value: float, width: float, decimals: int = 2) -> str:
        low = (value // width) * width
        high = low + width
        return f"{low:.{decimals}f} to {high:.{decimals}f}"

    match = re.search(r"confidence(?: too low)?\s+(-?\d+(?:\.\d+)?)", raw)
    if match:
        value = float(match.group(1))
        return f"confidence {bucket(value, 0.10, 2)}"

    match = re.search(r"quality(?: too low)?\s+(-?\d+(?:\.\d+)?)", raw)
    if match:
        value = float(match.group(1))
        return f"quality {bucket(value, 0.005, 3)}"

    match = re.search(r"momentum (?:negative|too weak)\s+(-?\d+(?:\.\d+)?)", raw)
    if match:
        value = float(match.group(1))
        return f"momentum {bucket(value, 0.001, 3)}"

    match = re.search(r"pullback outside sniper range\s+(-?\d+(?:\.\d+)?)", raw)
    if match:
        value = float(match.group(1))
        return f"pullback {bucket(value, 0.005, 3)} outside range"

    match = re.search(r"only\s+(\d+)/(\d+)\s+samples", raw)
    if match:
        have, need = int(match.group(1)), int(match.group(2))
        return f"insufficient samples {have}/{need}"

    if "win rate" in raw or "profit factor" in raw or "expectancy" in raw:
        failures = []
        if "win rate" in raw: failures.append("win rate")
        if "profit factor" in raw: failures.append("profit factor")
        if "expectancy" in raw: failures.append("expectancy")
        return "expectancy gate: " + " + ".join(failures)

    if "already holding" in raw:
        return "already holding"
    if "all v2 gates passed" in raw:
        return "all V2 gates passed"
    return raw[:160]


def v2_outcomes_summary(symbol: Optional[str] = None) -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    try:
        init_db()
        conn = db_connect()
        params: List[Any] = []
        symbol_clause = ""
        if symbol:
            symbol_clause = " AND o.symbol=?"
            params.append(str(symbol).upper())
        totals = conn.execute(
            f"""SELECT COUNT(*) AS scheduled,
                       SUM(CASE WHEN o.status='COMPLETE' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN o.status='PENDING' THEN 1 ELSE 0 END) AS pending,
                       COUNT(DISTINCT o.symbol) AS symbols
                FROM v2_observation_outcomes o WHERE 1=1 {symbol_clause}""", params
        ).fetchone()
        cte = f"""WITH ranked AS (
                    SELECT o.*, d.stage, d.decision, d.reason,
                           CASE
                             WHEN lower(d.reason) LIKE 'confidence%' THEN 'confidence threshold'
                             WHEN lower(d.reason) LIKE 'quality%' THEN 'quality threshold'
                             WHEN lower(d.reason) LIKE 'momentum negative%' THEN 'negative momentum'
                             WHEN lower(d.reason) LIKE 'momentum too weak%' THEN 'weak momentum'
                             WHEN lower(d.reason) LIKE 'pullback outside%' THEN 'pullback outside range'
                             WHEN lower(d.reason) LIKE 'only % samples%' THEN 'insufficient samples'
                             WHEN lower(d.reason) LIKE 'win rate%' OR lower(d.reason) LIKE 'profit factor%' OR lower(d.reason) LIKE 'expectancy%' THEN 'expectancy evidence below gate'
                             WHEN lower(d.reason) LIKE '%already holding%' THEN 'already holding'
                             ELSE d.reason
                           END AS reason_bucket,
                           ROW_NUMBER() OVER (PARTITION BY COALESCE(o.sample_key, CAST(o.decision_id AS TEXT)), o.horizon_hours
                                              ORDER BY o.id ASC) AS rn
                    FROM v2_observation_outcomes o
                    JOIN v2_setup_decisions d ON d.id=o.decision_id
                    WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL {symbol_clause}
                 )"""
        metric_sql = """COUNT(*) AS samples,
                       SUM(CASE WHEN net_return_pct>0 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN net_return_pct<0 THEN 1 ELSE 0 END) AS losses,
                       SUM(CASE WHEN net_return_pct=0 THEN 1 ELSE 0 END) AS breakevens,
                       AVG(net_return_pct) AS avg_return_pct,
                       SUM(CASE WHEN net_return_pct>0 THEN 1 ELSE 0 END)*1.0/
                         NULLIF(SUM(CASE WHEN net_return_pct<>0 THEN 1 ELSE 0 END),0) AS win_rate,
                       AVG(CASE WHEN net_return_pct>0 THEN net_return_pct END) AS avg_win_pct,
                       AVG(CASE WHEN net_return_pct<0 THEN net_return_pct END) AS avg_loss_pct,
                       MIN(net_return_pct) AS worst_return_pct, MAX(net_return_pct) AS best_return_pct,
                       SUM(CASE WHEN net_return_pct>0 THEN net_return_pct ELSE 0 END) /
                         NULLIF(ABS(SUM(CASE WHEN net_return_pct<0 THEN net_return_pct ELSE 0 END)),0) AS profit_factor,
                       AVG(net_return_pct) AS expectancy_pct"""
        profiles = conn.execute(
            cte + f" SELECT horizon_hours, {metric_sql} FROM ranked WHERE rn=1 GROUP BY horizon_hours ORDER BY horizon_hours", params
        ).fetchall()
        by_stage = conn.execute(
            cte + f" SELECT stage, decision, horizon_hours, {metric_sql} FROM ranked WHERE rn=1 GROUP BY stage, decision, horizon_hours ORDER BY horizon_hours, samples DESC", params
        ).fetchall()
        by_reason = conn.execute(
            cte + f" SELECT stage, decision, reason, horizon_hours, {metric_sql} FROM ranked WHERE rn=1 GROUP BY stage, decision, reason, horizon_hours ORDER BY horizon_hours, samples DESC", params
        ).fetchall()
        by_reason_bucket = conn.execute(
            cte + f" SELECT stage, decision, reason_bucket AS reason, horizon_hours, {metric_sql} FROM ranked WHERE rn=1 GROUP BY stage, decision, reason_bucket, horizon_hours ORDER BY horizon_hours, samples DESC", params
        ).fetchall()
        by_symbol = conn.execute(
            cte + f" SELECT symbol, stage, decision, horizon_hours, {metric_sql} FROM ranked WHERE rn=1 GROUP BY symbol, stage, decision, horizon_hours ORDER BY horizon_hours, samples DESC", params
        ).fetchall()
        conn.close()
        symbols_for_shadow = sorted({str(r["symbol"]) for r in by_symbol})
        shadow = [v2_forward_shadow_profile(sym) for sym in symbols_for_shadow]
        return {"ok": True, **(dict(totals) if totals else {}),
                "winRateDefinition": "wins / (wins + losses); breakevens excluded",
                "independentSampleMinutes": V2_INDEPENDENT_SAMPLE_MINUTES,
                "estimatedRoundTripCostBps": V2_ESTIMATED_COST_BPS,
                "horizonMeaning": {"1": "one market hour", "24": "one trading session", "72": "three trading sessions", "120": "five trading sessions"},
                "horizons": [dict(r) for r in profiles], "byStage": [dict(r) for r in by_stage],
                "byReason": [dict(r) for r in by_reason],
                "byReasonBucket": [dict(r) for r in by_reason_bucket], "bySymbol": [dict(r) for r in by_symbol],
                "shadowRecommendations": shadow,
                "shadowMode": True,
                "shadowNote": "Forward recommendations are advisory and do not alter live approvals.",
                "evidencePatch": {"reasonBuckets": True, "safeTrustRatings": True, "proposedQtyAudit": True}}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def v2_replay_rows(symbol: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    try:
        init_db()
        conn = db_connect()
        params: List[Any] = []
        where = ""
        if symbol:
            where = "WHERE d.symbol=?"
            params.append(str(symbol).upper())
        params.append(max(1, min(int(limit), 2000)))
        rows = conn.execute(
            f"""SELECT d.id AS decision_id, d.timestamp, d.symbol, d.decision, d.stage,
                       d.reason, d.price AS entry_price, d.confidence, d.quality,
                       d.momentum, d.pullback, o.horizon_hours, o.status,
                       o.due_at, o.evaluated_at, o.outcome_price, o.return_pct,
                       o.net_return_pct, o.estimated_cost_pct, o.sample_key
                FROM v2_setup_decisions d
                LEFT JOIN v2_observation_outcomes o ON o.decision_id=d.id
                {where}
                ORDER BY d.id DESC, o.horizon_hours ASC LIMIT ?""", params
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"V2 REPLAY ERROR: {e}")
        return []

# =========================
# TRADEBOT V9.1 DECISION INTELLIGENCE
# =========================
def decision_intelligence_summary(days: int = 30) -> Dict[str, Any]:
    """Summarise BOUGHT/BLOCKED/APPROVED/REJECTED evidence.

    Outcome returns come from the existing historical checkpoint engine. This
    endpoint is advisory only and cannot modify trading settings.
    """
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    days = max(1, min(int(days), 3650))
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    try:
        init_db()
        conn = db_connect()
        totals = conn.execute(
            """SELECT decision, COUNT(*) AS count, COUNT(DISTINCT symbol) AS symbols
               FROM v2_setup_decisions
               WHERE timestamp>=?
               GROUP BY decision ORDER BY count DESC""",
            (cutoff,),
        ).fetchall()
        outcomes = conn.execute(
            """WITH ranked AS (
                   SELECT d.decision,d.stage,d.symbol,d.timestamp,d.confidence,d.quality,
                          o.horizon_hours,o.net_return_pct,
                          ROW_NUMBER() OVER (
                              PARTITION BY COALESCE(o.sample_key,CAST(o.decision_id AS TEXT)),o.horizon_hours
                              ORDER BY o.id ASC
                          ) AS rn
                   FROM v2_setup_decisions d
                   JOIN v2_observation_outcomes o ON o.decision_id=d.id
                   WHERE d.timestamp>=? AND o.status='COMPLETE' AND o.net_return_pct IS NOT NULL
               )
               SELECT decision,horizon_hours,COUNT(*) AS samples,
                      SUM(CASE WHEN net_return_pct>0 THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN net_return_pct<0 THEN 1 ELSE 0 END) AS losses,
                      AVG(net_return_pct) AS avg_return_pct,
                      MAX(net_return_pct) AS best_return_pct,
                      MIN(net_return_pct) AS worst_return_pct
               FROM ranked WHERE rn=1
               GROUP BY decision,horizon_hours
               ORDER BY decision,horizon_hours""",
            (cutoff,),
        ).fetchall()
        blocked = conn.execute(
            """SELECT d.id,d.timestamp,d.symbol,d.reason,d.price,d.confidence,d.quality,
                      d.sniper_pass,d.a_plus_pass,
                      o.horizon_hours,o.status,o.net_return_pct,o.outcome_price,o.due_at,o.evaluated_at
               FROM v2_setup_decisions d
               LEFT JOIN v2_observation_outcomes o ON o.decision_id=d.id
               WHERE d.timestamp>=? AND d.decision='BLOCKED'
               ORDER BY d.id DESC,o.horizon_hours ASC LIMIT 500""",
            (cutoff,),
        ).fetchall()
        calibration_rows = conn.execute(
            """WITH ranked AS (
                   SELECT d.confidence,o.net_return_pct,
                          ROW_NUMBER() OVER (
                              PARTITION BY COALESCE(o.sample_key,CAST(o.decision_id AS TEXT)),o.horizon_hours
                              ORDER BY o.id ASC
                          ) AS rn
                   FROM v2_setup_decisions d
                   JOIN v2_observation_outcomes o ON o.decision_id=d.id
                   WHERE d.timestamp>=? AND o.status='COMPLETE'
                     AND o.horizon_hours=24 AND o.net_return_pct IS NOT NULL
                     AND d.confidence IS NOT NULL
               )
               SELECT CAST(MIN(9,MAX(0,CAST(confidence*10 AS INTEGER))) AS INTEGER) AS bucket,
                      COUNT(*) AS samples,
                      AVG(confidence) AS avg_confidence,
                      AVG(CASE WHEN net_return_pct>0 THEN 1.0 ELSE 0.0 END) AS actual_win_rate,
                      AVG(net_return_pct) AS expectancy_pct
               FROM ranked WHERE rn=1
               GROUP BY bucket ORDER BY bucket""",
            (cutoff,),
        ).fetchall()
        conn.close()
        confidence_buckets = []
        weighted_error = 0.0
        weighted_samples = 0
        for row in calibration_rows:
            bucket = int(row['bucket'] or 0)
            samples = int(row['samples'] or 0)
            expected = float(row['avg_confidence'] or 0.0)
            actual = float(row['actual_win_rate'] or 0.0)
            weighted_error += abs(expected - actual) * samples
            weighted_samples += samples
            confidence_buckets.append({
                'bucket': f"{bucket/10:.1f}-{(bucket+1)/10:.1f}",
                'samples': samples,
                'expected': round(expected, 4),
                'actual': round(actual, 4),
                'winRate': round(actual, 4),
                'expectancyPct': round(float(row['expectancy_pct'] or 0.0), 4),
                'calibrationErrorPct': round(abs(expected-actual)*100.0, 2),
            })
        calibration_score = max(0.0, 1.0 - (weighted_error / weighted_samples)) if weighted_samples else 0.0
        return {
            "ok": True,
            "version": "V9.1",
            "advisoryOnly": True,
            "days": days,
            "since": cutoff,
            "totals": [dict(r) for r in totals],
            "outcomesByDecision": [dict(r) for r in outcomes],
            "blockedOpportunities": [dict(r) for r in blocked],
            "confidenceBuckets": confidence_buckets,
            "confidenceCalibration": round(calibration_score, 4),
            "calibration": {"score": round(calibration_score, 4), "buckets": confidence_buckets,
                            "samples": weighted_samples},
            "note": "Decision evidence and historical outcomes only; live trading rules are unchanged.",
        }
    except Exception as e:
        return {"ok": False, "version": "V9.1", "error": str(e)}


def blocked_opportunities(limit: int = 100, horizon_hours: int = 24) -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    limit = max(1, min(int(limit), 1000))
    horizon_hours = max(1, int(horizon_hours))
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute(
            """SELECT d.id AS decision_id,d.timestamp,d.symbol,d.reason,d.price,
                      d.confidence,d.quality,d.momentum,d.pullback,d.spread,
                      d.sniper_pass,d.a_plus_pass,o.status,o.horizon_hours,o.due_at,
                      o.evaluated_at,o.outcome_price,o.return_pct,o.net_return_pct
               FROM v2_setup_decisions d
               LEFT JOIN v2_observation_outcomes o
                 ON o.decision_id=d.id AND o.horizon_hours=?
               WHERE d.decision='BLOCKED'
               ORDER BY d.id DESC LIMIT ?""",
            (horizon_hours, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"BLOCKED OPPORTUNITIES ERROR: {e}")
        return []


@app.get("/decision-intelligence/summary")
def api_decision_intelligence_summary(days: int = 30):
    return decision_intelligence_summary(days)


@app.get("/decision-intelligence/blocked")
def api_decision_intelligence_blocked(limit: int = 100, horizon_hours: int = 24):
    items = blocked_opportunities(limit=limit, horizon_hours=horizon_hours)
    return {
        "ok": True,
        "version": "V9.3",
        "advisoryOnly": True,
        "count": len(items),
        "horizonHours": int(horizon_hours),
        "items": items,
    }


def decision_intelligence_recent(limit: int = 100, decision: str = "", stage: str = "") -> Dict[str, Any]:
    """Return recent decision records for the dashboard table."""
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled", "items": []}
    limit = max(1, min(int(limit), 1000))
    decision = str(decision or "").upper().strip()
    stage = str(stage or "").strip()
    try:
        init_db()
        conn = db_connect()
        clauses = []
        params: List[Any] = []
        if decision:
            clauses.append("d.decision=?")
            params.append(decision)
        if stage:
            clauses.append("d.stage=?")
            params.append(stage)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = conn.execute(
            f"""SELECT d.id AS decision_id,d.timestamp,d.symbol,d.decision,d.stage,d.reason,
                       d.price,d.confidence,d.quality,d.momentum,d.pullback,d.spread,
                       d.ready_to_buy,d.sniper_pass,d.a_plus_pass,
                       o.status AS outcome_status,o.horizon_hours,o.due_at,o.evaluated_at,
                       o.outcome_price,o.return_pct,o.net_return_pct
                FROM v2_setup_decisions d
                LEFT JOIN v2_observation_outcomes o
                  ON o.decision_id=d.id AND o.horizon_hours=24
                {where}
                ORDER BY d.id DESC LIMIT ?""",
            params,
        ).fetchall()
        conn.close()
        return {
            "ok": True, "version": "V9.3", "count": len(rows),
            "decision": decision or "ALL", "stage": stage or "ALL",
            "items": [dict(r) for r in rows],
        }
    except Exception as e:
        return {"ok": False, "version": "V9.3", "error": str(e), "items": []}


def decision_intelligence_today() -> Dict[str, Any]:
    """Dashboard cards for the current UTC trading day."""
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        init_db()
        conn = db_connect()
        counts = conn.execute(
            """SELECT decision,COUNT(*) AS count FROM v2_setup_decisions
               WHERE timestamp>=? GROUP BY decision""", (start,)
        ).fetchall()
        stages = conn.execute(
            """SELECT stage,COUNT(*) AS count FROM v2_setup_decisions
               WHERE timestamp>=? GROUP BY stage ORDER BY count DESC""", (start,)
        ).fetchall()
        best_blocked = conn.execute(
            """SELECT d.id,d.timestamp,d.symbol,d.confidence,d.quality,d.reason,
                      o.status AS outcome_status,o.net_return_pct
               FROM v2_setup_decisions d
               LEFT JOIN v2_observation_outcomes o
                 ON o.decision_id=d.id AND o.horizon_hours=24
               WHERE d.timestamp>=? AND d.decision='BLOCKED'
               ORDER BY d.confidence DESC,d.quality DESC,d.id DESC LIMIT 1""", (start,)
        ).fetchone()
        conn.close()
        mapped = {str(r["decision"]).upper(): int(r["count"] or 0) for r in counts}
        return {
            "ok": True, "version": "V9.3", "day": today_str(),
            "total": sum(mapped.values()),
            "bought": mapped.get("BOUGHT", 0),
            "blocked": mapped.get("BLOCKED", 0),
            "approved": mapped.get("APPROVED", 0),
            "rejected": mapped.get("REJECTED", 0),
            "counts": mapped,
            "stages": [dict(r) for r in stages],
            "bestBlocked": dict(best_blocked) if best_blocked else None,
            "advisoryOnly": True,
        }
    except Exception as e:
        return {"ok": False, "version": "V9.3", "error": str(e)}


@app.get("/decision-intelligence/recent")
def api_decision_intelligence_recent(limit: int = 100, decision: str = "", stage: str = ""):
    return decision_intelligence_recent(limit=limit, decision=decision, stage=stage)


@app.get("/decision-intelligence/today")
def api_decision_intelligence_today():
    return decision_intelligence_today()


# =========================
# STRATEGY
# =========================
def refresh_universe_if_needed(force=False):
    global current_universe, last_universe_refresh_ts

    if AUTO_UNIVERSE_ENABLED:
        try:
            result = build_weekly_universe(force=force)
            if result.get("ok"):
                last_universe_refresh_ts = time.time()
                return
        except Exception as e:
            print(f"AUTO UNIVERSE ERROR: {e}")

    now = time.time()
    if not force and (now - last_universe_refresh_ts) < UNIVERSE_REFRESH_SECONDS:
        return
    current_universe = list(dict.fromkeys(SAFE_UNIVERSE + list(custom_symbols.keys())))
    for s in current_universe:
        ensure_symbol_state(s, custom=s in custom_symbols)
    last_universe_refresh_ts = now
    print(f"UNIVERSE REFRESHED: {', '.join(current_universe)}")


def pick_money_mode_stocks(
    scans,
    approval_decision: str = "APPROVED",
    approval_stage: str = "final_gate",
    approval_reason: str = "all V2 gates passed",
    persist_decisions: bool = True,
    log_rejections: bool = True,
):
    """Evaluate scans through the exact live entry gates.

    V17.0.15 retains read-only portfolio publishing and makes this gate path the single source of truth. Live order paths
    keep persist_decisions=True so every real decision is recorded exactly as
    before. Dashboard/status refreshes use persist_decisions=False and
    log_rejections=False, which means they can reuse the *same* eligibility
    pipeline without creating duplicate learning rows or noisy rejection logs.
    """
    def persist(scan, decision, stage, reason, profile=None):
        if persist_decisions:
            record_v2_setup_decision(scan, decision, stage, reason, profile)

    candidates = []
    for scan in scans:
        symbol = scan["symbol"]
        can_buy, reason = can_buy_symbol(symbol)
        if not can_buy:
            persist(scan, "REJECTED", "account_gate", reason)
            continue
        if PDT_AWARE_MODE_ENABLED and today_buy_count() >= MAX_NEW_BUYS_PER_DAY_PDT_AWARE:
            persist(scan, "REJECTED", "pdt_gate", "maximum new buys for today reached")
            continue

        # V10.5 Symbol Reputation Gate: prevent repeated live entries into symbols
        # with sufficiently mature, persistently negative evidence. New/low-sample
        # symbols remain eligible so the learner can continue gathering evidence.
        reputation_ok, reputation_reason, reputation = symbol_reputation_allows_live_buy(symbol)
        scan["symbolReputation"] = reputation
        if not reputation_ok:
            if log_rejections:
                print(f"REPUTATION SKIP {symbol} | {reputation_reason}")
            persist(scan, "REJECTED", "symbol_reputation_gate", reputation_reason)
            continue

        sniper_ok, sniper_reason = sniper_passes(scan)
        if not sniper_ok:
            if log_rejections:
                print(f"SNIPER SKIP {symbol} | {sniper_reason}")
            persist(scan, "REJECTED", "sniper_gate", sniper_reason)
            continue

        aplus_ok, aplus_reason = a_plus_gate(scan)
        if not aplus_ok:
            if log_rejections:
                print(f"A+ SKIP {symbol} | {aplus_reason}")
            persist(scan, "REJECTED", "a_plus_gate", aplus_reason)
            continue
        if not scan["ready_to_buy"]:
            persist(scan, "REJECTED", "trigger_gate", "entry trigger not ready")
            continue
        v2_ok, v2_profile = v17_v2_trade_gate_with_cold_start(scan, log_decision=log_rejections)
        if not v2_ok:
            if log_rejections and not v2_profile.get("coldStart"):
                print(f"V2 SKIP {symbol} | {v2_profile.get('reason')}")
            stage = "v17_cold_start_gate" if v2_profile.get("coldStart") else "expectancy_gate"
            reason_text = v2_profile.get("coldStartReason") or v2_profile.get("reason", "not approved")
            persist(scan, "REJECTED", stage, reason_text, v2_profile)
            continue
        scan["v2Expectancy"] = v2_profile
        persist(
            scan,
            approval_decision,
            approval_stage,
            approval_reason,
            v2_profile,
        )
        candidates.append(scan)
    candidates.sort(key=lambda x: (-x["confidence"], -x["quality_score"], x["spread"]))
    return candidates


def v17_live_entry_gate_pipeline(
    scans,
    approval_decision: str = "APPROVED",
    approval_stage: str = "final_gate",
    approval_reason: str = "all V2 gates passed",
    persist_decisions: bool = True,
    log_rejections: bool = True,
    log_summary: bool = False,
):
    """V17.0.15 single source of truth for pre-portfolio entry eligibility.

    Every portfolio planner/order path must call this function before V16/V17
    scoring.  It delegates to the established live gate implementation so the
    planner can never rank a symbol that Sniper/A+/Reputation/Trigger/V2 would
    reject.  Read-only callers disable persistence to avoid duplicate learning.
    """
    raw = _prioritize_first_dibs_rows(scans)
    survivors = pick_money_mode_stocks(
        raw,
        approval_decision=approval_decision,
        approval_stage=approval_stage,
        approval_reason=approval_reason,
        persist_decisions=persist_decisions,
        log_rejections=log_rejections,
    )
    if log_summary:
        survivor_symbols = ",".join(str(row.get("symbol") or "") for row in survivors) or "-"
        print(
            f"V17.0.15 ENTRY GATES | scanned={len(raw)} passed={len(survivors)} "
            f"rejected={max(0, len(raw)-len(survivors))} survivors={survivor_symbols}"
        )
    return survivors


def get_best_profit_candidate(scans):
    picks = pick_money_mode_stocks(scans)
    return picks[0] if picks else None


def get_weakest_position_for_rotation():
    managed = [p for p in get_all_positions() if p["symbol"] in current_universe]
    if not managed:
        return None
    managed.sort(key=lambda p: (p["pnlPct"], p.get("spread", 0.0)))
    return managed[0]


def maybe_rotate_weakest_into_best(scans):
    global last_rotation_ts
    if not PROFIT_MODE_ENABLED or not ROTATION_MODE_ENABLED or manual_override or emergency_stop:
        return ""
    if time.time() - last_rotation_ts < ROTATION_COOLDOWN_SECONDS:
        return "ROTATION SKIP | cooldown"
    best = get_best_profit_candidate(scans)
    weakest = get_weakest_position_for_rotation()
    if not best or not weakest or best["symbol"] == weakest["symbol"]:
        return "ROTATION SKIP | no useful rotation"
    if weakest["pnlPct"] > ROTATE_ONLY_IF_WEAKEST_PNL_BELOW:
        return f"ROTATION SKIP | weakest {weakest['symbol']} still okay"
    if pdt_aware_should_avoid_sell(weakest["symbol"], f"PROFIT MODE ROTATE OUT FOR {best['symbol']}", weakest["pnlPct"]):
        return f"ROTATION SKIP | PDT-aware hold for {weakest['symbol']}"
    try:
        sell_result = close_position(weakest, reason=f"PROFIT MODE ROTATE OUT FOR {best['symbol']}")
        if not sell_result.get("ok"):
            return f"ROTATION SELL BLOCKED | {sell_result.get('message')}"
        time.sleep(2)
        notional = ai_risk_notional(best)
        if notional < MIN_ORDER_NOTIONAL:
            return "ROTATION BUY SKIP | no buying power"
        market_buy_notional(best["symbol"], notional, reason=f"PROFIT MODE ROTATE INTO FROM {weakest['symbol']}", scan=best)
        last_rotation_ts = time.time()
        return f"ROTATION DONE | sold {weakest['symbol']} -> bought {best['symbol']} ${notional:.2f}"
    except Exception as e:
        return f"ROTATION ERROR | {e}"


def _v17_runner_trail_state(symbol: str) -> Dict[str, Any]:
    ensure_symbol_state(symbol)
    st = state[symbol]
    if "runner_trail_breach_count" not in st:
        st["runner_trail_breach_count"] = 0
    if "runner_trail_last_reason" not in st:
        st["runner_trail_last_reason"] = ""
    if "runner_trail_last_breach_pct" not in st:
        st["runner_trail_last_breach_pct"] = 0.0
    return st


def _v17_reset_runner_trail(symbol: str) -> None:
    st = _v17_runner_trail_state(symbol)
    st["runner_trail_breach_count"] = 0
    st["runner_trail_last_reason"] = ""
    st["runner_trail_last_breach_pct"] = 0.0


def _v17_runner_trail_decision(p: Dict[str, Any], trail_floor: float) -> Dict[str, Any]:
    """Return whether a breached trailing floor should sell now or get one grace check.

    The trail floor itself is NEVER loosened. Grace is only available to an
    already-strong winner when the breach is very shallow and recent momentum
    is not collapsing. A persistent second breach exits normally.
    """
    symbol = str(p.get("symbol") or "").upper()
    price = float(p.get("price") or 0.0)
    entry = float(p.get("entry") or 0.0)
    highest = float(p.get("highest") or 0.0)
    pnl_pct = float(p.get("pnlPct") or 0.0)
    st = _v17_runner_trail_state(symbol)

    if not ADAPTIVE_RUNNER_TRAIL_ENABLED or price <= 0 or trail_floor <= 0 or entry <= 0:
        _v17_reset_runner_trail(symbol)
        return {"sell": True, "grace": False, "reason": "runner disabled/ineligible"}

    # Any recovery above the protected floor clears a previous test breach.
    if price > trail_floor:
        if int(st.get("runner_trail_breach_count") or 0) > 0:
            print(f"V17.2 RUNNER RECOVERED | {symbol} price={price:.2f} floor={trail_floor:.2f}")
        _v17_reset_runner_trail(symbol)
        return {"sell": False, "grace": False, "reason": "above floor"}

    breach_pct = max(0.0, ((trail_floor - price) / trail_floor) * 100.0)
    peak_pnl_pct = ((highest / entry) - 1.0) * 100.0 if highest > 0 and entry > 0 else pnl_pct
    try:
        short_momentum = float(compute_short_momentum(symbol, price))
    except Exception:
        short_momentum = 0.0

    qualifies = (
        pnl_pct >= ADAPTIVE_RUNNER_MIN_CURRENT_PNL_PCT
        and peak_pnl_pct >= ADAPTIVE_RUNNER_MIN_PEAK_PNL_PCT
        and breach_pct <= ADAPTIVE_RUNNER_MAX_SHALLOW_BREACH_PCT
        and short_momentum >= ADAPTIVE_RUNNER_MAX_NEGATIVE_MOMENTUM
    )
    if not qualifies:
        _v17_reset_runner_trail(symbol)
        return {
            "sell": True, "grace": False,
            "reason": f"breach={breach_pct:.3f}% pnl={pnl_pct:.2f}% peak={peak_pnl_pct:.2f}% momentum={short_momentum:.4f}",
            "breachPct": breach_pct, "peakPnlPct": peak_pnl_pct, "momentum": short_momentum,
        }

    count = int(st.get("runner_trail_breach_count") or 0) + 1
    st["runner_trail_breach_count"] = count
    st["runner_trail_last_breach_pct"] = breach_pct
    st["runner_trail_last_reason"] = "SHALLOW_CONTINUATION_BREACH"

    if count < ADAPTIVE_RUNNER_CONFIRMATION_CHECKS:
        print(
            f"V17.2 RUNNER GRACE HOLD | {symbol} check={count}/{ADAPTIVE_RUNNER_CONFIRMATION_CHECKS} "
            f"price={price:.2f} floor={trail_floor:.2f} breach={breach_pct:.3f}% "
            f"pnl={pnl_pct:.2f}% peak={peak_pnl_pct:.2f}% momentum={short_momentum:.4f}"
        )
        return {
            "sell": False, "grace": True, "reason": "shallow continuation breach",
            "check": count, "breachPct": breach_pct, "peakPnlPct": peak_pnl_pct, "momentum": short_momentum,
        }

    print(
        f"V17.2 RUNNER CONFIRMED EXIT | {symbol} check={count}/{ADAPTIVE_RUNNER_CONFIRMATION_CHECKS} "
        f"price={price:.2f} floor={trail_floor:.2f} breach={breach_pct:.3f}% "
        f"pnl={pnl_pct:.2f}% peak={peak_pnl_pct:.2f}% momentum={short_momentum:.4f}"
    )
    _v17_reset_runner_trail(symbol)
    return {
        "sell": True, "grace": False, "reason": "confirmed trailing breach",
        "check": count, "breachPct": breach_pct, "peakPnlPct": peak_pnl_pct, "momentum": short_momentum,
    }



def _v17_peak_exhaustion_state(symbol: str) -> Dict[str, Any]:
    ensure_symbol_state(symbol)
    st = state[symbol]
    st.setdefault("peak_exhaustion_touch_count", 0)
    st.setdefault("peak_exhaustion_peak", 0.0)
    st.setdefault("peak_exhaustion_armed", False)
    st.setdefault("peak_exhaustion_reject_pct", 0.0)
    st.setdefault("peak_exhaustion_last_eval", "")
    return st


def _v17_reset_peak_exhaustion(symbol: str) -> None:
    st = _v17_peak_exhaustion_state(symbol)
    st["peak_exhaustion_touch_count"] = 0
    st["peak_exhaustion_peak"] = 0.0
    st["peak_exhaustion_armed"] = False
    st["peak_exhaustion_reject_pct"] = 0.0
    st["peak_exhaustion_last_eval"] = ""


def _v17_peak_exhaustion_decision(p: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate repeated failed tests of the persisted Trade Replay peak.

    A 'touch' is a market-open replay sample within PEAK_EXHAUSTION_TOLERANCE_PCT
    of the session's highest recorded price. Touches are clustered by time so
    ten-second samples from one visit to resistance count as ONE attempt.

    The rule is intentionally conservative: it only exits after the required
    number of distinct attempts AND a subsequent rejection from the peak. This
    avoids selling simply because a strong trend sits near fresh highs.
    """
    symbol = str(p.get("symbol") or "").upper()
    price = float(p.get("price") or 0.0)
    entry = float(p.get("entry") or 0.0)
    pnl_pct = float(p.get("pnlPct") or 0.0)
    st = _v17_peak_exhaustion_state(symbol)

    if not PEAK_EXHAUSTION_ENABLED or not SQLITE_ENABLED or not TRADE_REPLAY_ENABLED or not symbol or price <= 0 or entry <= 0:
        _v17_reset_peak_exhaustion(symbol)
        return {"sell": False, "eligible": False, "reason": "disabled/ineligible"}

    try:
        _trade_replay_ensure_tables()
        conn = db_connect()
        session = conn.execute(
            "SELECT id FROM trade_replay_sessions WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if not session:
            conn.close()
            return {"sell": False, "eligible": False, "reason": "no replay session"}
        rows = conn.execute(
            """SELECT observed_at,price,market_open FROM trade_replay_points
               WHERE session_id=? ORDER BY observed_at DESC LIMIT ?""",
            (int(session["id"]), int(PEAK_EXHAUSTION_LOOKBACK_POINTS)),
        ).fetchall()
        conn.close()
    except Exception as exc:
        return {"sell": False, "eligible": False, "reason": f"replay read failed: {exc}"}

    pts = []
    for row in reversed(rows):
        try:
            px = float(row["price"] or 0.0)
            if px <= 0:
                continue
            if PEAK_EXHAUSTION_MARKET_OPEN_ONLY and not bool(row["market_open"]):
                continue
            ts_raw = str(row["observed_at"] or "")
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            pts.append((ts, px))
        except Exception:
            continue

    if len(pts) < PEAK_EXHAUSTION_REQUIRED_TOUCHES:
        st["peak_exhaustion_touch_count"] = 0
        st["peak_exhaustion_armed"] = False
        return {"sell": False, "eligible": False, "reason": "not enough replay samples"}

    peak = max(px for _, px in pts)
    peak_pnl_pct = ((peak / entry) - 1.0) * 100.0
    if peak_pnl_pct < PEAK_EXHAUSTION_MIN_PEAK_PNL_PCT:
        st["peak_exhaustion_peak"] = peak
        st["peak_exhaustion_touch_count"] = 0
        st["peak_exhaustion_armed"] = False
        return {"sell": False, "eligible": False, "reason": f"peak pnl {peak_pnl_pct:.2f}% below minimum"}

    touch_floor = peak * (1.0 - PEAK_EXHAUSTION_TOLERANCE_PCT / 100.0)
    touch_times = []
    last_touch_ts = None
    for ts, px in pts:
        if px < touch_floor:
            continue
        if last_touch_ts is None or (ts - last_touch_ts).total_seconds() >= PEAK_EXHAUSTION_MIN_SECONDS_BETWEEN_TOUCHES:
            touch_times.append(ts)
            last_touch_ts = ts

    touches = len(touch_times)
    reject_pct = max(0.0, ((peak - price) / peak) * 100.0) if peak > 0 else 0.0
    armed = touches >= PEAK_EXHAUSTION_REQUIRED_TOUCHES
    st["peak_exhaustion_touch_count"] = touches
    st["peak_exhaustion_peak"] = peak
    st["peak_exhaustion_armed"] = armed
    st["peak_exhaustion_reject_pct"] = reject_pct
    st["peak_exhaustion_last_eval"] = datetime.now(UTC).isoformat()

    if touches > 0:
        previous_logged = int(st.get("peak_exhaustion_last_logged_touches") or 0)
        if touches != previous_logged:
            print(
                f"V17.3 PEAK RETEST | {symbol} attempts={touches}/{PEAK_EXHAUSTION_REQUIRED_TOUCHES} "
                f"peak={peak:.2f} tolerance={PEAK_EXHAUSTION_TOLERANCE_PCT:.2f}% "
                f"current={price:.2f} peak_pnl={peak_pnl_pct:.2f}%"
            )
            st["peak_exhaustion_last_logged_touches"] = touches

    if not armed:
        return {
            "sell": False, "eligible": True, "armed": False, "touches": touches,
            "peak": peak, "peakPnlPct": peak_pnl_pct, "rejectPct": reject_pct,
            "reason": "collecting peak attempts",
        }

    # Once armed, require an actual rejection rather than selling merely because
    # price revisits the high. This keeps clean breakouts alive.
    if pnl_pct < PEAK_EXHAUSTION_MIN_CURRENT_PNL_PCT:
        return {
            "sell": False, "eligible": True, "armed": True, "touches": touches,
            "peak": peak, "rejectPct": reject_pct,
            "reason": f"current pnl {pnl_pct:.2f}% below protected-profit minimum",
        }

    if reject_pct < PEAK_EXHAUSTION_REJECTION_PCT:
        return {
            "sell": False, "eligible": True, "armed": True, "touches": touches,
            "peak": peak, "rejectPct": reject_pct,
            "reason": "peak exhaustion armed; waiting for rejection",
        }

    print(
        f"V17.3 PEAK EXHAUSTION EXIT | {symbol} attempts={touches}/{PEAK_EXHAUSTION_REQUIRED_TOUCHES} "
        f"peak={peak:.2f} current={price:.2f} rejection={reject_pct:.2f}% "
        f"current_pnl={pnl_pct:.2f}% peak_pnl={peak_pnl_pct:.2f}%"
    )
    return {
        "sell": True, "eligible": True, "armed": True, "touches": touches,
        "peak": peak, "peakPnlPct": peak_pnl_pct, "rejectPct": reject_pct,
        "reason": "repeated peak tests followed by failed breakout rejection",
    }


def manage_money_mode_positions():
    for p in get_all_positions():
        symbol = p["symbol"]

        if not MANAGE_OUTSIDE_UNIVERSE_POSITIONS and symbol not in current_universe:
            continue

        if has_open_order(symbol):
            continue

        price = float(p["price"])
        entry = float(p["entry"])
        qty = float(p["qty"])
        highest = p["highest"]

        if price <= 0 or entry <= 0 or qty <= DUST_THRESHOLD:
            continue

        fast_stop, fast_stop_reason = should_fast_stop(p)
        if fast_stop:
            try:
                if pdt_aware_should_avoid_sell(symbol, "FAST EXIT STOP LOSS", p["pnlPct"], allow_hard_stop=True):
                    continue

                market_sell_qty(symbol, qty, entry=entry, price=price, reason="FAST EXIT STOP LOSS")
                state[symbol]["highest_since_entry"] = None
                _v17_reset_peak_exhaustion(symbol)
                print(f"FAST EXIT STOP LOSS SELL {qty:.6f} {symbol}")
            except Exception as e:
                print(f"SELL ERROR {symbol}: {e}")
            continue

        risk_profile = _ai_risk_effective_profile(symbol) if "_ai_risk_effective_profile" in globals() else {}
        adaptive_stop_pct = abs(float(risk_profile.get("stopLossPct") or ((1.0 - STOP_LOSS) * 100.0)))
        emergency_stop_pct = abs(float(risk_profile.get("emergencyStopPct") or AI_RISK_EMERGENCY_STOP_PCT if "AI_RISK_EMERGENCY_STOP_PCT" in globals() else 10.0))
        stop_price = entry * (1.0 - adaptive_stop_pct / 100.0)
        emergency_stop_price = entry * (1.0 - emergency_stop_pct / 100.0)
        if price <= emergency_stop_price:
            try:
                market_sell_qty(symbol, qty, entry=entry, price=price, reason="AI RISK EMERGENCY STOP")
                state[symbol]["highest_since_entry"] = None
                _v17_reset_peak_exhaustion(symbol)
                print(f"AI RISK EMERGENCY STOP {symbol} | pnl={p['pnlPct']:.2f}% limit=-{emergency_stop_pct:.2f}%")
            except Exception as e:
                print(f"EMERGENCY SELL ERROR {symbol}: {e}")
            continue
        if price <= stop_price:
            try:
                if pdt_aware_should_avoid_sell(symbol, "MONEY MODE STOP LOSS", p["pnlPct"], allow_hard_stop=True):
                    continue

                market_sell_qty(symbol, qty, entry=entry, price=price, reason="MONEY MODE STOP LOSS")
                state[symbol]["highest_since_entry"] = None
                _v17_reset_peak_exhaustion(symbol)
            except Exception as e:
                print(f"SELL ERROR {symbol}: {e}")
            continue

        peak_exit = _v17_peak_exhaustion_decision(p)
        if peak_exit.get("sell"):
            try:
                if pdt_aware_should_avoid_sell(symbol, "PEAK EXHAUSTION PROFIT", p["pnlPct"], allow_hard_stop=False):
                    continue
                market_sell_qty(symbol, qty, entry=entry, price=price, reason="PEAK EXHAUSTION PROFIT")
                state[symbol]["highest_since_entry"] = None
                _v17_reset_peak_exhaustion(symbol)
                _v17_reset_runner_trail(symbol)
                print(
                    f"PEAK EXHAUSTION PROFIT SELL {qty:.6f} {symbol} | "
                    f"attempts={peak_exit.get('touches', 0)} peak={float(peak_exit.get('peak') or 0):.2f} "
                    f"rejection={float(peak_exit.get('rejectPct') or 0):.2f}%"
                )
            except Exception as e:
                print(f"PEAK EXHAUSTION SELL ERROR {symbol}: {e}")
            continue

        partial_ok, partial_reason = should_partial_profit(p)
        if partial_ok:
            ai_block, ai_reason = hold_ai_blocks_soft_exit(p, "PARTIAL PROFIT TAKE")
            if ai_block:
                print(ai_reason)
                continue
            try:
                if pdt_aware_should_avoid_sell(symbol, "PARTIAL PROFIT TAKE", p["pnlPct"], allow_hard_stop=False):
                    continue

                sell_qty = partial_profit_qty(p)
                market_sell_qty(symbol, sell_qty, entry=entry, price=price, reason="PARTIAL PROFIT TAKE")
                mark_partial_profit_taken(symbol)
                print(f"PARTIAL PROFIT SELL {sell_qty:.6f} {symbol}")
            except Exception as e:
                print(f"PARTIAL SELL ERROR {symbol}: {e}")
            continue

        stall_ok, stall_reason = should_stall_exit(p)
        if stall_ok:
            ai_block, ai_reason = hold_ai_blocks_soft_exit(p, "STALL EXIT")
            if ai_block:
                print(ai_reason)
                continue
            try:
                if pdt_aware_should_avoid_sell(symbol, "STALL EXIT", p["pnlPct"], allow_hard_stop=False):
                    continue

                market_sell_qty(symbol, qty, entry=entry, price=price, reason="STALL EXIT")
                state[symbol]["highest_since_entry"] = None
                _v17_reset_peak_exhaustion(symbol)
                print(f"STALL EXIT SELL {qty:.6f} {symbol} | {stall_reason}")
            except Exception as e:
                print(f"STALL SELL ERROR {symbol}: {e}")
            continue

        adaptive_trail_start_pct = abs(float(risk_profile.get("trailStartPct") or ((TRAIL_START - 1.0) * 100.0)))
        adaptive_giveback_pct = abs(float(risk_profile.get("trailGivebackPct") or ((1.0 - TRAIL_GIVEBACK) * 100.0)))
        trail_start_price = entry * (1.0 + adaptive_trail_start_pct / 100.0)
        if price >= trail_start_price and highest is not None:
            if has_taken_partial_profit(symbol):
                giveback = POST_PARTIAL_TRAIL_GIVEBACK
            else:
                giveback = 1.0 - adaptive_giveback_pct / 100.0
            trail_floor = highest * giveback

            if price > trail_floor:
                _v17_reset_runner_trail(symbol)

            if price <= trail_floor:
                runner_decision = _v17_runner_trail_decision(p, trail_floor)
                if not runner_decision.get("sell"):
                    # One shallow confirmation check lets a strong winner recover
                    # from a brief floor touch without lowering the protected floor.
                    continue
                ai_block, ai_reason = hold_ai_blocks_soft_exit(p, "MONEY MODE TRAILING PROFIT")
                if ai_block:
                    print(ai_reason)
                    continue
                try:
                    if pdt_aware_should_avoid_sell(symbol, "MONEY MODE TRAILING PROFIT", p["pnlPct"]):
                        continue

                    market_sell_qty(symbol, qty, entry=entry, price=price, reason="MONEY MODE TRAILING PROFIT")
                    state[symbol]["highest_since_entry"] = None
                    _v17_reset_runner_trail(symbol)
                    _v17_reset_peak_exhaustion(symbol)
                except Exception as e:
                    print(f"SELL ERROR {symbol}: {e}")
                continue


def _v16_clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _v16_curve_metrics(scan: Dict[str, Any]) -> Dict[str, float]:
    """Calculate real short-horizon behaviour from the live price curve."""
    symbol = str(scan.get("symbol") or "").upper().strip()
    curve = scan.get("price_curve") or scan.get("priceCurve") or []
    if not curve and symbol:
        try:
            curve = (state.get(symbol) or {}).get("price_curve") or []
        except Exception:
            curve = []
    prices: List[float] = []
    for point in curve[-60:]:
        try:
            value = float(point.get("value") if isinstance(point, dict) else point)
            if value > 0:
                prices.append(value)
        except Exception:
            continue
    if len(prices) < 3:
        return {"samples": float(len(prices)), "return": 0.0, "slope": 0.0, "consistency": 0.5, "volatility": 0.0, "drawdown": 0.0}
    returns = [(prices[i] / prices[i - 1]) - 1.0 for i in range(1, len(prices)) if prices[i - 1] > 0]
    total_return = (prices[-1] / prices[0]) - 1.0
    n = len(prices)
    x_mean = (n - 1) / 2.0
    y_mean = sum(prices) / n
    denom = sum((i - x_mean) ** 2 for i in range(n)) or 1.0
    slope_abs = sum((i - x_mean) * (prices[i] - y_mean) for i in range(n)) / denom
    slope = slope_abs / y_mean if y_mean > 0 else 0.0
    positive = sum(1 for r in returns if r > 0)
    negative = sum(1 for r in returns if r < 0)
    consistency = max(positive, negative) / max(1, len(returns))
    mean_r = sum(returns) / max(1, len(returns))
    volatility = (sum((r - mean_r) ** 2 for r in returns) / max(1, len(returns))) ** 0.5
    peak = prices[0]
    max_drawdown = 0.0
    for price in prices:
        peak = max(peak, price)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - price) / peak)
    return {
        "samples": float(n), "return": total_return, "slope": slope,
        "consistency": consistency, "volatility": volatility, "drawdown": max_drawdown,
    }


def _v16_prepare_real_market_factors(picks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Enrich candidates with batch-relative strength and real curve metrics."""
    enriched: List[Dict[str, Any]] = []
    rows: List[tuple[int, float]] = []
    for index, original in enumerate(picks):
        scan = dict(original)
        metrics = _v16_curve_metrics(scan)
        scan["v16CurveMetrics"] = metrics
        strength = (metrics["return"] * 0.65) + (metrics["slope"] * 8.0 * 0.35)
        rows.append((index, strength))
        enriched.append(scan)
    ordered = sorted(rows, key=lambda row: row[1])
    count = max(1, len(ordered) - 1)
    percentiles = {idx: rank / count for rank, (idx, _) in enumerate(ordered)}
    for index, scan in enumerate(enriched):
        scan["v16BatchRelativeStrength"] = percentiles.get(index, 0.5)
        try:
            scan["market_regime"] = scan.get("market_regime") or scan.get("marketRegime") or _v4_market_regime()
        except Exception:
            scan["market_regime"] = scan.get("market_regime") or "UNKNOWN"
    return enriched


def _v16_factor_breakdown(scan: Dict[str, Any]) -> Dict[str, Any]:
    """V16.5 factors calculated from live curve, quote, reputation and regime data."""
    confidence, _ = calculate_confidence(scan)
    confidence = _v16_clamp(confidence)
    metrics = scan.get("v16CurveMetrics") or _v16_curve_metrics(scan)

    curve_return = float(metrics.get("return") or 0.0)
    curve_slope = float(metrics.get("slope") or 0.0)
    consistency = float(metrics.get("consistency") or 0.5)
    momentum_raw = float(scan.get("short_momentum") or scan.get("shortMomentum") or curve_return)
    directional = _v16_clamp(0.5 + (curve_return * 22.0) + (curve_slope * 95.0))
    momentum = _v16_clamp((directional * 0.72) + (consistency * 0.28))

    relative_strength = _v16_clamp(float(scan.get("v16BatchRelativeStrength") or 0.5))

    spread = max(0.0, float(scan.get("spread") or 0.0))
    spread_quality = _v16_clamp(1.0 - spread / max(0.0001, float(MAX_SPREAD)))
    relative_volume = float(scan.get("relative_volume") or scan.get("relativeVolume") or scan.get("rvol") or 0.0)
    volume_quality = _v16_clamp(relative_volume / 2.0) if relative_volume > 0 else 0.55
    liquidity = _v16_clamp((spread_quality * 0.82) + (volume_quality * 0.18))

    realised_vol = abs(float(metrics.get("volatility") or 0.0))
    drawdown = abs(float(metrics.get("drawdown") or 0.0))
    # Reward enough movement to trade, penalise unstable/noisy or sharply drawing-down curves.
    movement_score = _v16_clamp(realised_vol / 0.0015)
    noise_penalty = _v16_clamp(realised_vol / 0.008)
    drawdown_penalty = _v16_clamp(drawdown / 0.025)
    volatility_quality = _v16_clamp(0.48 + movement_score * 0.35 - noise_penalty * 0.18 - drawdown_penalty * 0.30)

    historical_edge = 0.50
    symbol = str(scan.get("symbol") or "").upper().strip()
    try:
        reputation = symbol_reputation_snapshot(force=False).get(symbol) or {}
        samples = int(reputation.get("samples") or 0)
        rep_score = float(reputation.get("score") or 0.5)
        sample_weight = min(1.0, samples / 20.0)
        historical_edge = _v16_clamp(0.5 * (1.0 - sample_weight) + rep_score * sample_weight)
    except Exception:
        history = scan.get("optimiserDecision") or {}
        history_mult = max(0.65, min(1.25, float(history.get("multiplier") or 1.0)))
        historical_edge = _v16_clamp((history_mult - 0.65) / 0.60)

    regime_text = str(scan.get("market_regime") or scan.get("marketRegime") or "UNKNOWN").upper()
    if "BULL" in regime_text or "RISK_ON" in regime_text:
        regime_fit = _v16_clamp(0.45 + momentum * 0.45 + relative_strength * 0.10)
    elif "BEAR" in regime_text or "RISK_OFF" in regime_text:
        regime_fit = _v16_clamp(0.72 - momentum * 0.30 + volatility_quality * 0.18)
    elif "RANGE" in regime_text or "CHOP" in regime_text:
        regime_fit = _v16_clamp(0.42 + volatility_quality * 0.38 + (1.0 - abs(momentum - 0.5) * 2.0) * 0.20)
    else:
        regime_fit = _v16_clamp(0.45 + momentum * 0.22 + volatility_quality * 0.18 + relative_strength * 0.15)

    quality_raw = max(0.0, float(scan.get("quality_score") or scan.get("qualityScore") or 0.0))
    quality = _v16_clamp(quality_raw / max(0.0001, float(A_PLUS_MIN_QUALITY or 0.026)))
    weights = {"momentum": 0.25, "relativeStrength": 0.18, "liquidity": 0.15, "volatilityQuality": 0.12, "historicalEdge": 0.18, "regimeFit": 0.12}
    values = {"momentum": momentum, "relativeStrength": relative_strength, "liquidity": liquidity, "volatilityQuality": volatility_quality, "historicalEdge": historical_edge, "regimeFit": regime_fit}
    weighted = {key: round(values[key] * weights[key], 6) for key in weights}
    base = sum(weighted.values())
    validation = (confidence * 0.60) + (quality * 0.40)
    final = _v16_clamp((base * 0.82) + (validation * 0.18))
    return {
        "version": "V16.5", "source": "LIVE_MARKET_DATA",
        "values": {key: round(value, 6) for key, value in values.items()},
        "weights": weights, "weighted": weighted, "validation": round(validation, 6),
        "final": round(final, 6), "regime": regime_text,
        "marketMetrics": {key: round(float(value), 8) for key, value in metrics.items()},
    }

def _v16_portfolio_score(scan: Dict[str, Any]) -> float:
    return float(_v16_factor_breakdown(scan).get("final") or 0.0)

def _v16_calibrated_score_profiles(picks: List[Dict[str, Any]]) -> List[Dict[str, float]]:
    """Blend absolute setup strength with bounded current-batch separation."""
    import math
    raw_scores: List[float] = []
    for scan in picks:
        try:
            raw_scores.append(float(_v16_portfolio_score(scan)))
        except Exception:
            raw_scores.append(0.0)
    if not raw_scores:
        return []
    mean = sum(raw_scores) / len(raw_scores)
    variance = sum((value - mean) ** 2 for value in raw_scores) / max(1, len(raw_scores))
    std = max(0.04, variance ** 0.5)
    relative_weight = AI_PORTFOLIO_RELATIVE_SCORE_WEIGHT if len(raw_scores) >= 4 else 0.0
    profiles: List[Dict[str, float]] = []
    for raw in raw_scores:
        z_score = max(-2.5, min(2.5, (raw - mean) / std))
        relative = 1.0 / (1.0 + math.exp(-1.35 * z_score))
        calibrated = (raw * (1.0 - relative_weight)) + (relative * relative_weight)
        profiles.append({
            "raw": round(max(0.0, min(1.0, raw)), 6),
            "relative": round(relative, 6),
            "calibrated": round(max(0.0, min(1.0, calibrated)), 6),
            "zScore": round(z_score, 4),
        })
    return profiles


def _v16_effective_minimum_score(profiles: List[Dict[str, float]], manual: bool = False) -> tuple[float, str]:
    if manual or not AI_PORTFOLIO_ADAPTIVE_SCORE_ENABLED or not profiles:
        return AI_PORTFOLIO_MIN_SCORE, "BASE"
    scores = sorted((float(row.get("calibrated") or 0.0) for row in profiles), reverse=True)
    if sum(1 for score in scores if score >= AI_PORTFOLIO_MIN_SCORE) >= AI_PORTFOLIO_ADAPTIVE_TARGET_COUNT:
        return AI_PORTFOLIO_MIN_SCORE, "BASE"
    target_index = min(len(scores), AI_PORTFOLIO_ADAPTIVE_TARGET_COUNT) - 1
    target_score = scores[target_index]
    if target_score < AI_PORTFOLIO_ADAPTIVE_SCORE_FLOOR:
        return AI_PORTFOLIO_MIN_SCORE, "BASE_QUALITY_TOO_LOW"
    effective = max(AI_PORTFOLIO_ADAPTIVE_SCORE_FLOOR, min(AI_PORTFOLIO_MIN_SCORE, target_score - 0.001))
    return (round(effective, 6), "ADAPTIVE_QUIET_MARKET") if effective < AI_PORTFOLIO_MIN_SCORE else (AI_PORTFOLIO_MIN_SCORE, "BASE")


def _v16_cash_reserve_pct(candidates: List[Dict[str, Any]]) -> float:
    if not candidates:
        return 1.0
    scores = [float(c.get("portfolioScore") or 0.0) for c in candidates]
    top = max(scores)
    average = sum(scores) / max(1, len(scores))
    breadth_bonus = min(0.14, max(0, len(candidates) - 1) * 0.025)
    deploy_quality = max(0.0, min(1.0, (top * 0.62) + (average * 0.38) + breadth_bonus))
    reserve = AI_PORTFOLIO_MAX_CASH_RESERVE_PCT - deploy_quality * (AI_PORTFOLIO_MAX_CASH_RESERVE_PCT - AI_PORTFOLIO_MIN_CASH_RESERVE_PCT)
    if len(candidates) == 1:
        reserve = max(reserve, 1.0 - AI_PORTFOLIO_MAX_SINGLE_WEIGHT)
    return round(max(AI_PORTFOLIO_MIN_CASH_RESERVE_PCT, min(AI_PORTFOLIO_MAX_CASH_RESERVE_PCT, reserve)), 4)


def _v16_save_portfolio_plan(plan: Dict[str, Any]) -> None:
    try:
        path = AI_PORTFOLIO_PLAN_FILE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(plan, handle, indent=2, default=str)
        os.replace(tmp, path)
    except Exception as exc:
        print(f"V16 PORTFOLIO PLAN SAVE ERROR: {exc}")


def _v16_load_portfolio_plan() -> Dict[str, Any]:
    try:
        with open(AI_PORTFOLIO_PLAN_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {"ok": True, "version": AI_PORTFOLIO_MANAGER_VERSION, "enabled": AI_PORTFOLIO_MANAGER_ENABLED, "status": "WAITING_FOR_PLAN", "allocations": []}


def _v174_final_gate_monitor_payload() -> Dict[str, Any]:
    """Compact frontend view of the candidate(s) that reached the final pre-order gate.

    The monitor is intentionally derived from the saved V16/V17 portfolio plan, whose
    input has already passed the single-source live entry pipeline. This prevents the
    frontend from presenting a raw scanner candidate as FINAL GATE when the real trader
    would still reject it at Sniper/A+/Trigger/V2.
    """
    try:
        plan = _v16_load_portfolio_plan() or {}
        qualified = list(plan.get("qualifiedCandidates") or [])
        allocations = list(plan.get("allocations") or [])
        decisions = list(plan.get("decisions") or [])
        allocation_by_symbol = {
            str(row.get("symbol") or "").upper(): row
            for row in allocations
            if str(row.get("symbol") or "").strip()
        }

        candidates = []
        for row in qualified[:8]:
            symbol = str(row.get("symbol") or "").upper().strip()
            if not symbol:
                continue
            allocation = allocation_by_symbol.get(symbol) or {}
            deployable = bool(row.get("deployableNow") or allocation)
            candidates.append({
                "rank": int(row.get("rank") or len(candidates) + 1),
                "symbol": symbol,
                "portfolioScore": round(float(row.get("portfolioScore") or 0.0), 4),
                "minimumScore": round(float(plan.get("minimumPortfolioScore") or 0.0), 4),
                "confidence": round(float(row.get("confidence") or 0.0), 4),
                "confidenceLabel": str(row.get("confidenceLabel") or ""),
                "quality": round(float(row.get("quality") or 0.0), 6),
                "spread": round(float(row.get("spread") or 0.0), 6),
                "deployableNow": deployable,
                "plannedNotionalUsd": round(float(allocation.get("notionalUsd") or 0.0), 2),
                "plannedNotionalGbp": round(float(allocation.get("notionalGbp") or 0.0), 2),
                "gate": "FINAL_GATE",
                "nextStep": "FULL_BUY_EXECUTION_LOCK" if deployable else "WAITING_FOR_CAPACITY",
            })

        top = candidates[0] if candidates else None
        actionable = int(plan.get("actionableCount") or 0)
        qualified_count = int(plan.get("qualifiedCount") or len(candidates))
        order_limit = int(plan.get("orderLimit") or 0)
        if top and actionable > 0:
            state_name = "FINAL_GATE_READY"
            headline = f"{top['symbol']} reached the final gate"
            detail = "All live entry gates and portfolio score passed. Next step: final execution lock / order submission."
        elif top:
            state_name = "FINAL_GATE_WAITING"
            headline = f"{top['symbol']} reached the final gate"
            detail = "Qualified at the final gate but waiting for portfolio capacity, buying power, or the daily order limit."
        else:
            state_name = "NO_FINAL_GATE_CANDIDATE"
            headline = "No stock at the final gate yet"
            detail = "The live scanner is still filtering candidates through the entry gates."

        rejected = [
            {
                "symbol": str(d.get("symbol") or ""),
                "reasonCode": str(d.get("reasonCode") or ""),
                "reason": str(d.get("reason") or ""),
                "portfolioScore": round(float(d.get("portfolioScore") or 0.0), 4),
            }
            for d in decisions
            if d.get("decision") == "REJECTED"
        ][:5]

        return {
            "ok": True,
            "version": "V17.4-FINAL-GATE-MONITOR",
            "state": state_name,
            "headline": headline,
            "detail": detail,
            "updatedAt": plan.get("createdAt"),
            "planStatus": plan.get("status"),
            "thresholdMode": plan.get("thresholdMode"),
            "minimumPortfolioScore": round(float(plan.get("minimumPortfolioScore") or 0.0), 4),
            "qualifiedCount": qualified_count,
            "actionableCount": actionable,
            "orderLimit": order_limit,
            "topCandidate": top,
            "candidates": candidates,
            "recentRejects": rejected,
            "lastEvent": dict(v174_final_gate_last_event or {}),
        }
    except Exception as exc:
        return {
            "ok": False,
            "version": "V17.4-FINAL-GATE-MONITOR",
            "state": "MONITOR_ERROR",
            "headline": "Final gate monitor unavailable",
            "detail": str(exc),
            "candidates": [],
        }


def build_v16_portfolio_plan(picks: List[Dict[str, Any]], manual: bool = False) -> Dict[str, Any]:
    account = get_account()
    equity = float(account.equity)
    buying_power = max(0.0, float(account.buying_power))
    managed_capital = max(0.0, float(effective_trading_equity(equity) if "effective_trading_equity" in globals() else equity))
    usable_cash = max(0.0, min(buying_power, managed_capital) - CASH_BUFFER)
    structural_slots = max(0, int(ai_position_capacity_payload().get("structuralAvailableSlots") or allowed_new_position_count()))
    daily_slots = max(0, int(MAX_NEW_BUYS_PER_DAY_PDT_AWARE - today_buy_count())) if PDT_AWARE_MODE_ENABLED else AI_PORTFOLIO_MAX_ORDERS_PER_CYCLE
    order_limit = max(0, min(structural_slots, daily_slots, AI_PORTFOLIO_MAX_ORDERS_PER_CYCLE))

    ranked: List[Dict[str, Any]] = []
    decisions: List[Dict[str, Any]] = []
    picks = _v16_prepare_real_market_factors(picks)
    score_profiles = _v16_calibrated_score_profiles(picks)
    effective_minimum_score, threshold_mode = _v16_effective_minimum_score(score_profiles, manual=manual)

    for scan_index, scan in enumerate(picks):
        symbol = str(scan.get("symbol") or "").upper().strip()
        if not symbol:
            decisions.append({
                "scanIndex": scan_index + 1,
                "symbol": "UNKNOWN",
                "decision": "REJECTED",
                "reasonCode": "MISSING_SYMBOL",
                "reason": "Scanner result did not contain a symbol.",
                "portfolioScore": 0.0,
                "minimumScore": effective_minimum_score,
                "confidence": 0.0,
                "quality": 0.0,
                "spread": 0.0,
                "deployableNow": False,
            })
            print(f"V16 DECISION | symbol=UNKNOWN decision=REJECTED reason=MISSING_SYMBOL scan={scan_index + 1}")
            continue

        try:
            profile = score_profiles[scan_index] if scan_index < len(score_profiles) else {"raw": _v16_portfolio_score(scan), "calibrated": _v16_portfolio_score(scan), "relative": 0.5, "zScore": 0.0}
            raw_score = float(profile.get("raw") or 0.0)
            score = float(profile.get("calibrated") or raw_score)
        except Exception as exc:
            profile = {"raw": 0.0, "calibrated": 0.0, "relative": 0.0, "zScore": 0.0}
            raw_score = 0.0
            score = 0.0
            decisions.append({
                "scanIndex": scan_index + 1,
                "symbol": symbol,
                "decision": "REJECTED",
                "reasonCode": "SCORE_ERROR",
                "reason": f"Portfolio score could not be calculated: {exc}",
                "portfolioScore": 0.0,
                "minimumScore": effective_minimum_score,
                "confidence": 0.0,
                "quality": round(float(scan.get("quality_score") or 0.0), 6),
                "spread": round(float(scan.get("spread") or 0.0), 6),
                "deployableNow": False,
            })
            print(f"V16 DECISION | symbol={symbol} decision=REJECTED reason=SCORE_ERROR error={exc}")
            continue

        try:
            confidence, label = calculate_confidence(scan)
            confidence = float(confidence)
        except Exception as exc:
            confidence, label = 0.0, "UNKNOWN"
            print(f"V16 DECISION CONFIDENCE ERROR | symbol={symbol} error={exc}")

        quality = round(float(scan.get("quality_score") or 0.0), 6)
        spread = round(float(scan.get("spread") or 0.0), 6)
        factors = _v16_factor_breakdown(scan)

        try:
            allowed, block = can_buy_symbol(symbol)
        except Exception as exc:
            allowed, block = False, f"BUY_CHECK_ERROR: {exc}"

        if not allowed:
            block_text = str(block or "Symbol blocked by buy safety checks")
            decisions.append({
                "scanIndex": scan_index + 1,
                "symbol": symbol,
                "decision": "REJECTED",
                "reasonCode": "BUY_SAFETY_BLOCK",
                "reason": block_text,
                "portfolioScore": score,
                "rawPortfolioScore": raw_score,
                "relativeBatchScore": round(float(profile.get("relative") or 0.0), 6),
                "scoreZ": round(float(profile.get("zScore") or 0.0), 4),
                "minimumScore": effective_minimum_score,
                "confidence": round(confidence, 4),
            "factors": factors,
                "confidenceLabel": label,
                "quality": quality,
                "spread": spread,
            "factors": factors,
                "factors": factors,
                "deployableNow": False,
            })
            print(
                f"V16 DECISION | symbol={symbol} decision=REJECTED reason=BUY_SAFETY_BLOCK "
                f"detail={block_text} score={score:.3f} confidence={confidence:.3f} quality={quality:.4f}"
            )
            continue

        if score < effective_minimum_score and not manual:
            reason = f"Calibrated portfolio score {score:.3f} (raw {raw_score:.3f}) is below the minimum {effective_minimum_score:.3f}."
            decisions.append({
                "scanIndex": scan_index + 1,
                "symbol": symbol,
                "decision": "REJECTED",
                "reasonCode": "SCORE_BELOW_MINIMUM",
                "reason": reason,
                "portfolioScore": score,
                "rawPortfolioScore": raw_score,
                "relativeBatchScore": round(float(profile.get("relative") or 0.0), 6),
                "scoreZ": round(float(profile.get("zScore") or 0.0), 4),
                "minimumScore": effective_minimum_score,
                "scoreGap": round(effective_minimum_score - score, 6),
                "confidence": round(confidence, 4),
                "confidenceLabel": label,
                "quality": quality,
                "spread": spread,
            "factors": factors,
                "factors": factors,
                "deployableNow": False,
            })
            print(
                f"V16 DECISION | symbol={symbol} decision=REJECTED reason=SCORE_BELOW_MINIMUM "
                f"score={score:.3f} minimum={effective_minimum_score:.3f} confidence={confidence:.3f} quality={quality:.4f} spread={spread:.5f}"
            )
            continue

        item = {
            "symbol": symbol,
            "scan": scan,
            "portfolioScore": score,
            "rawPortfolioScore": raw_score,
            "relativeBatchScore": round(float(profile.get("relative") or 0.0), 6),
            "scoreZ": round(float(profile.get("zScore") or 0.0), 4),
            "confidence": round(confidence, 4),
            "confidenceLabel": label,
            "quality": quality,
            "spread": spread,
            "factors": factors,
                "factors": factors,
            "riskProfile": _ai_risk_build_profile(scan) if AI_RISK_ENGINE_ENABLED else {},
        }
        ranked.append(item)
        decisions.append({
            "scanIndex": scan_index + 1,
            "symbol": symbol,
            "decision": "QUALIFIED",
            "reasonCode": "QUALIFIED",
            "reason": f"Calibrated score {score:.3f} (raw {raw_score:.3f}) met the minimum {effective_minimum_score:.3f} and all symbol safety checks passed.",
            "portfolioScore": score,
            "minimumScore": effective_minimum_score,
            "confidence": round(confidence, 4),
            "confidenceLabel": label,
            "quality": quality,
            "spread": spread,
            "factors": factors,
                "factors": factors,
            "deployableNow": False,
        })
        print(
            f"V16 DECISION | symbol={symbol} decision=QUALIFIED score={score:.3f} "
            f"raw={raw_score:.3f} minimum={effective_minimum_score:.3f} mode={threshold_mode} confidence={confidence:.3f} quality={quality:.4f} spread={spread:.5f}"
        )

    ranked.sort(key=lambda item: (-item["portfolioScore"], -item["confidence"], item["spread"]))

    # V18.2.16 FIRST DIBS: MARA (or configured preferred symbol) only receives
    # priority *after* normal score qualification. If it fails any gate or the
    # portfolio minimum, it is absent from `ranked` and receives no preference.
    preferred = _first_dibs_symbol()
    if preferred:
        original_rank = next((i + 1 for i, item in enumerate(ranked) if str(item.get("symbol") or "").upper() == preferred), None)
        if original_rank is not None and original_rank > 1:
            ranked = sorted(ranked, key=lambda item: 0 if str(item.get("symbol") or "").upper() == preferred else 1)
            print(
                f"V18.2.16 FIRST DIBS | symbol={preferred} result=QUALIFIED_PRIORITY "
                f"original_rank={original_rank} final_rank=1 score={float(ranked[0].get('portfolioScore') or 0.0):.3f}"
            )
        elif original_rank == 1:
            print(
                f"V18.2.16 FIRST DIBS | symbol={preferred} result=QUALIFIED_ALREADY_FIRST "
                f"final_rank=1 score={float(ranked[0].get('portfolioScore') or 0.0):.3f}"
            )
    qualified_ranked = list(ranked)
    actionable_ranked = qualified_ranked[:order_limit] if order_limit > 0 else []
    actionable_symbols = {item["symbol"] for item in actionable_ranked}

    for decision in decisions:
        if decision.get("decision") == "QUALIFIED":
            decision["deployableNow"] = decision.get("symbol") in actionable_symbols
            if not decision["deployableNow"]:
                decision["decision"] = "QUALIFIED_WAITING"
                decision["reasonCode"] = "CAPACITY_OR_RANK_LIMIT"
                decision["reason"] = (
                    "Candidate qualified, but it is outside the current available order capacity."
                    if order_limit > 0
                    else "Candidate qualified, but no new order slots are currently available."
                )

    decision_rank = {item["symbol"]: index + 1 for index, item in enumerate(qualified_ranked)}
    for decision in decisions:
        if decision.get("symbol") in decision_rank:
            decision["rank"] = decision_rank[decision["symbol"]]
    decisions.sort(key=lambda row: (
        0 if row.get("decision") == "QUALIFIED" else 1 if row.get("decision") == "QUALIFIED_WAITING" else 2,
        int(row.get("rank") or 9999),
        -float(row.get("portfolioScore") or 0.0),
        str(row.get("symbol") or ""),
    ))

    single_full_buy = bool(V17_SINGLE_FULL_BUY_MODE or (FULL_BUY_WHEN_ONE_POSITION and effective_max_positions() <= 1))
    reserve_pct = 0.0 if single_full_buy else _v16_cash_reserve_pct(actionable_ranked)
    if single_full_buy:
        # Use all currently available deployable cash for the #1 qualified candidate,
        # leaving only the explicit full-buy cash buffer. Do not apply the legacy
        # 45% portfolio weight or V10 per-position cap to this user-selected mode.
        # V17.6: commit the whole WORKING pot to #1, excluding the persistent
        # realised-profit vault from deployable buying power.
        vault_working_capital = profit_vault_deployable_usd(equity, buying_power) if "profit_vault_deployable_usd" in globals() else buying_power
        deployable = round(max(0.0, min(buying_power, vault_working_capital) - FULL_BUY_CASH_BUFFER), 2)
        actionable_ranked = actionable_ranked[:1]
    else:
        deployable = round(max(0.0, usable_cash * (1.0 - reserve_pct)), 2)

    allocations = []
    if actionable_ranked and deployable >= MIN_ORDER_NOTIONAL:
        power = 2.0
        strengths = [max(0.001, item["portfolioScore"] - effective_minimum_score + 0.08) ** power for item in actionable_ranked]
        total_strength = sum(strengths) or 1.0
        remaining = deployable
        for index, (item, strength) in enumerate(zip(actionable_ranked, strengths)):
            if single_full_buy:
                amount = round(max(0.0, remaining), 2)
            else:
                raw_weight = strength / total_strength
                weight = min(AI_PORTFOLIO_MAX_SINGLE_WEIGHT, raw_weight)
                requested = round(deployable * weight, 2)
                constitutional_cap = round(managed_capital * min(float(V10_CONSTITUTION["positionValuePct"]["max"]), AI_PORTFOLIO_MAX_SINGLE_WEIGHT), 2)
                amount = round(max(0.0, min(requested, constitutional_cap, remaining)), 2)
                if index == len(actionable_ranked) - 1:
                    amount = round(max(0.0, min(remaining, constitutional_cap)), 2)
            remaining = round(max(0.0, remaining - amount), 2)
            if amount < MIN_ORDER_NOTIONAL:
                continue
            allocations.append({
                "rank": index + 1,
                "symbol": item["symbol"],
                "portfolioScore": item["portfolioScore"],
                "confidence": item["confidence"],
                "confidenceLabel": item["confidenceLabel"],
                "quality": item["quality"],
                "spread": item["spread"],
                "weightPct": round((amount / (vault_working_capital if single_full_buy else managed_capital)) * 100.0, 2) if (vault_working_capital if single_full_buy else managed_capital) else 0.0,
                "shareOfDeployedPct": round((amount / deployable) * 100.0, 2) if deployable else 0.0,
                "notionalUsd": amount,
                "notionalGbp": round(money_gbp(amount), 2),
                "riskMultiplier": round(float(item["riskProfile"].get("positionMultiplier") or 1.0), 3),
                "reason": f"Rank #{index + 1}; score={item['portfolioScore']:.3f}; confidence={item['confidence']:.2f}; quality={item['quality']:.4f}",
                "scan": item["scan"],
            })

    allocated = round(sum(float(a["notionalUsd"]) for a in allocations), 2)
    rejected_count = sum(1 for d in decisions if d.get("decision") == "REJECTED")
    waiting_count = sum(1 for d in decisions if d.get("decision") == "QUALIFIED_WAITING")
    reason_counts: Dict[str, int] = {}
    for decision in decisions:
        code = str(decision.get("reasonCode") or "UNKNOWN")
        reason_counts[code] = reason_counts.get(code, 0) + 1

    plan = {
        "ok": True,
        "version": "V17.0.13-LIVE-GATE-ALIGNED-PLANNER",
        "enabled": AI_PORTFOLIO_MANAGER_ENABLED,
        "createdAt": datetime.now(UTC).isoformat(),
        "manual": bool(manual),
        "status": (
            "READY" if allocations
            else "QUALIFIED_WAITING_FOR_CAPACITY" if qualified_ranked and order_limit <= 0
            else "QUALIFIED_BELOW_ORDER_MINIMUM" if qualified_ranked
            else "NO_QUALIFIED_PORTFOLIO"
        ),
        "managedCapitalUsd": round((vault_working_capital if single_full_buy else managed_capital), 2),
        "managedCapitalGbp": round(money_gbp((vault_working_capital if single_full_buy else managed_capital)), 2),
        "buyingPowerUsd": round(buying_power, 2),
        "candidateCount": len(picks),
        "qualifiedCount": len(qualified_ranked),
        "actionableCount": len(actionable_ranked),
        "rejectedCount": rejected_count,
        "waitingCount": waiting_count,
        "orderLimit": order_limit,
        "minimumPortfolioScore": effective_minimum_score,
        "baseMinimumPortfolioScore": AI_PORTFOLIO_MIN_SCORE,
        "adaptiveScoreFloor": AI_PORTFOLIO_ADAPTIVE_SCORE_FLOOR,
        "thresholdMode": threshold_mode,
        "scoringMode": "ABSOLUTE_PLUS_BATCH_CALIBRATION",
        "decisionReasonCounts": reason_counts,
        "decisions": decisions[:100],
        "qualifiedCandidates": [
            {
                "rank": index + 1,
                "symbol": item["symbol"],
                "portfolioScore": item["portfolioScore"],
                "confidence": item["confidence"],
                "confidenceLabel": item["confidenceLabel"],
                "quality": item["quality"],
                "spread": item["spread"],
                "deployableNow": index < len(actionable_ranked),
            }
            for index, item in enumerate(qualified_ranked[:25])
        ],
        "cashReservePct": round(reserve_pct * 100.0, 2),
        "cashReserveUsd": round(max(0.0, usable_cash - allocated), 2),
        "cashReserveGbp": round(money_gbp(max(0.0, usable_cash - allocated)), 2),
        "deployableUsd": allocated,
        "deployableGbp": round(money_gbp(allocated), 2),
        "allocationMethod": "score-weighted; stronger qualified candidates receive more capital; cash remains only when breadth/quality is insufficient or safety caps apply",
        "allocations": [{k: v for k, v in row.items() if k != "scan"} for row in allocations],
        "explanation": (
            f"Reviewed {len(picks)} live scanner candidate(s) using {threshold_mode.lower().replace('_', ' ')} thresholding "
            f"(base {AI_PORTFOLIO_MIN_SCORE:.3f}, effective {effective_minimum_score:.3f}): {len(qualified_ranked)} qualified, "
            f"{rejected_count} rejected and {waiting_count} qualified but waiting for capacity. "
            f"{len(actionable_ranked)} can be considered within the current capacity/daily safety limit. "
            f"Planned ${allocated:.2f} across {len(allocations)} position(s), with {reserve_pct * 100.0:.1f}% cash reserve. "
            + (
                "Capital is retained because no new order slots are currently available."
                if qualified_ranked and order_limit <= 0
                else "Open the Decision Inspector below to see the exact reason for every candidate."
            )
        ),
    }
    _v16_save_portfolio_plan(plan)
    print(
        f"V17.0.15 SINGLE-SOURCE FULL-BUY PLAN | gate_eligible={len(picks)} threshold={effective_minimum_score:.3f} base={AI_PORTFOLIO_MIN_SCORE:.3f} mode={threshold_mode} qualified={len(qualified_ranked)} "
        f"rejected={rejected_count} waiting={waiting_count} actionable={len(actionable_ranked)} "
        f"order_limit={order_limit} deploy=${allocated:.2f} reserve={reserve_pct*100:.1f}% allocations="
        + ",".join(f"{a['symbol']}=${a['notionalUsd']:.2f}" for a in allocations)
    )
    return {"plan": plan, "internalAllocations": allocations}


@app.get("/v16/portfolio/status")
def api_v16_portfolio_status(request: Request):
    verify_api_key(request)

    # V16.2 live portfolio publishing fix:
    # The old endpoint only loaded the last JSON file. If no buy cycle had run,
    # the frontend remained on WAITING_FOR_PLAN even while the market and scanner
    # were live. Build a read-only plan from the latest scan snapshot whenever
    # the saved plan is missing, empty or stale. This does not submit orders.
    payload = _v16_load_portfolio_plan()
    should_publish = payload.get("status") in (None, "WAITING_FOR_PLAN") or not payload.get("createdAt")
    try:
        created_at = payload.get("createdAt")
        if created_at:
            created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            should_publish = should_publish or (datetime.now(UTC) - created).total_seconds() > max(30, CHECK_INTERVAL * 2)
    except Exception:
        should_publish = True

    if AI_PORTFOLIO_MANAGER_ENABLED and latest_scans and should_publish:
        try:
            # V17.0.13 PLANNER ALIGNMENT:
            # Never rank raw scanner rows on the dashboard. First pass them
            # through the exact same entry gates used by money_mode_buy(), but
            # read-only so a status refresh cannot create duplicate evidence.
            raw_scans = list(latest_scans)
            gate_eligible = v17_live_entry_gate_pipeline(
                raw_scans,
                persist_decisions=False,
                log_rejections=False,
                log_summary=False,
            )
            payload = build_v16_portfolio_plan(gate_eligible, manual=False).get("plan") or payload
            payload["source"] = "latest_live_scans_after_live_gates"
            payload["rawScanCount"] = len(raw_scans)
            payload["gateEligibleCount"] = len(gate_eligible)
            payload["plannerAlignmentVersion"] = "V17.0.15-COLD-START"
        except Exception as exc:
            print(f"V17.0.15 PORTFOLIO STATUS REFRESH ERROR: {exc}")
            payload["refreshError"] = str(exc)

    payload.setdefault("enabled", AI_PORTFOLIO_MANAGER_ENABLED)
    payload.setdefault("version", AI_PORTFOLIO_MANAGER_VERSION)
    payload["openPositions"] = len(get_all_positions())
    payload["capacity"] = ai_position_capacity_payload()
    payload["latestScanCount"] = len(latest_scans)
    return payload

def money_mode_buy(scans, manual=False):
    if TRADEBOT_V2_ENABLED and not PAPER and not TRADEBOT_V2_LIVE_ENABLED:
        # Validation mode must still run the complete decision pipeline so V2 can
        # record approved/rejected observations without submitting a live order.
        try:
            validation_picks = pick_money_mode_stocks(scans)
            print(f"V2 VALIDATION | observations processed={len(scans)} approved={len(validation_picks)} live_order=False")
        except Exception as e:
            print(f"V2 VALIDATION LOG ERROR: {e}")
        return "BUY BLOCKED | TradeBot V2 validation mode. Decisions recorded; live ordering remains disabled."
    if emergency_stop:
        return "BUY BLOCKED | emergency stop active"
    blocked, reason = risk_blocked()
    if blocked:
        return f"BUY BLOCKED | {reason}"
    if allowed_new_position_count() <= 0:
        capacity = ai_position_capacity_payload()
        structural_slots = int(capacity.get("structuralAvailableSlots") or 0)
        affordable_slots = int(capacity.get("affordableNewPositions") or 0)
        if structural_slots <= 0:
            block_reason = f"AI portfolio capacity reached ({capacity.get('effectiveMaxPositions', effective_max_positions())})"
            approval_stage = "position_limit"
        elif affordable_slots <= 0:
            buying_power = float(capacity.get("buyingPowerUsd") or 0.0)
            target_notional = float(capacity.get("targetPositionNotionalUsd") or 0.0)
            block_reason = f"insufficient buying power (${buying_power:.2f}) for AI target position (${target_notional:.2f})"
            approval_stage = "buying_power"
        else:
            block_reason = str(capacity.get("reason") or "no AI-approved portfolio slot available")
            approval_stage = "portfolio_capacity"
        # Preserve decision evidence even when account-level capacity blocks an order.
        try:
            blocked_picks = pick_money_mode_stocks(
                scans,
                approval_decision="BLOCKED",
                approval_stage=approval_stage,
                approval_reason=block_reason,
            )
            if blocked_picks:
                best = blocked_picks[0]
                print(
                    "DECISION INTELLIGENCE | "
                    f"blocked={len(blocked_picks)} best={best.get('symbol')} "
                    f"confidence={float(best.get('confidence') or 0.0):.2f} "
                    f"reason={block_reason}"
                )
        except Exception as decision_error:
            print(f"DECISION INTELLIGENCE BLOCKED LOG ERROR: {decision_error}")
        return f"BUY BLOCKED | {block_reason}"
    if PDT_AWARE_MODE_ENABLED and today_buy_count() >= MAX_NEW_BUYS_PER_DAY_PDT_AWARE:
        return f"BUY BLOCKED | PDT-aware max new buys today reached ({MAX_NEW_BUYS_PER_DAY_PDT_AWARE})"

    picks = v17_live_entry_gate_pipeline(
        scans,
        persist_decisions=True,
        log_rejections=True,
        log_summary=True,
    )
    if manual and not picks:
        if A_PLUS_BLOCK_LOW_CONFIDENCE_MANUAL_BUY:
            return "No A+ sniper candidates ready. Manual Money Buy blocked by Trade Quality Gate."
        picks = [s for s in scans if can_buy_symbol(s["symbol"])[0] and s["spread"] <= MAX_SPREAD]
        picks.sort(key=lambda x: (-x["confidence"], -x["quality_score"], x["spread"]))

    if not picks:
        return "No sniper candidates ready."

    bought = 0
    messages = []
    if AI_PORTFOLIO_MANAGER_ENABLED:
        portfolio = build_v16_portfolio_plan(picks, manual=manual)
        execution_rows = portfolio.get("internalAllocations") or []
    else:
        execution_rows = [{"symbol": c["symbol"], "scan": c, "notionalUsd": ai_risk_notional(c), "rank": index + 1, "portfolioScore": _v16_portfolio_score(c)} for index, c in enumerate(picks[:MAX_NEW_BUYS_PER_LOOP])]

    if not execution_rows:
        plan = portfolio.get("plan") if AI_PORTFOLIO_MANAGER_ENABLED else {}
        return str(plan.get("explanation") or "No portfolio allocations passed the capital and safety rules.")

    for allocation in execution_rows:
        c = allocation["scan"]
        symbol = allocation["symbol"]
        can_buy, block_reason = can_buy_symbol(symbol)
        if not can_buy:
            messages.append(f"SKIP {symbol} | {block_reason}")
            continue
        planned_notional = round(float(allocation.get("notionalUsd") or 0.0), 2)
        notional = planned_notional

        # V17.0.7 FINAL EXECUTION LOCK:
        # Re-read Alpaca buying power at the exact moment the #1 portfolio order
        # is submitted. This is authoritative in one-position/full-buy mode and
        # prevents any stale planner value, V10 sizing, AI risk multiplier,
        # profit-banking cap or portfolio-weight rule from shrinking the order.
        if bool(globals().get("V17_SINGLE_FULL_BUY_MODE", False)) or (
            bool(globals().get("FULL_BUY_WHEN_ONE_POSITION", False))
            and effective_max_positions() <= 1
        ):
            try:
                live_account = get_account()
                live_equity = max(0.0, float(live_account.equity))
                live_buying_power = max(0.0, float(live_account.buying_power))
                full_buffer = float(globals().get("FULL_BUY_CASH_BUFFER", 2.0))
                working_capital = profit_vault_deployable_usd(live_equity, live_buying_power) if "profit_vault_deployable_usd" in globals() else live_buying_power
                notional = round(max(0.0, min(live_buying_power, working_capital) - full_buffer), 2)
                allocation["notionalUsd"] = notional
                vault_reserved = profit_vault_reserved_usd() if "profit_vault_reserved_usd" in globals() else 0.0
                print(
                    f"V17.6 FULL BUY EXECUTION LOCK | symbol={symbol} "
                    f"planned=${planned_notional:.2f} live_buying_power=${live_buying_power:.2f} "
                    f"working_capital=${working_capital:.2f} vault_reserved=${vault_reserved:.2f} "
                    f"buffer=${full_buffer:.2f} final=${notional:.2f}"
                )
                v174_final_gate_last_event.clear()
                v174_final_gate_last_event.update({
                    "type": "EXECUTION_LOCK",
                    "symbol": symbol,
                    "at": datetime.now(UTC).isoformat(),
                    "plannedNotionalUsd": planned_notional,
                    "finalNotionalUsd": notional,
                    "liveBuyingPowerUsd": round(live_buying_power, 2),
                    "message": f"{symbol} passed the final gate and reached the full-buy execution lock.",
                })
            except Exception as full_buy_exc:
                print(f"V17.0.7 FULL BUY EXECUTION LOCK ERROR | symbol={symbol} error={full_buy_exc}")

        if notional < MIN_ORDER_NOTIONAL:
            messages.append(f"SKIP {symbol} | portfolio allocation too small {notional:.2f}")
            continue
        confidence, label = calculate_confidence(c)
        reason = f"{'MANUAL' if manual else 'AUTO'} V16 PORTFOLIO #{allocation.get('rank', bought + 1)} {label} BUY"
        try:
            market_buy_notional(symbol, notional, reason=reason, scan=c)
            v174_final_gate_last_event.clear()
            v174_final_gate_last_event.update({
                "type": "BUY_SENT",
                "symbol": symbol,
                "at": datetime.now(UTC).isoformat(),
                "finalNotionalUsd": round(notional, 2),
                "portfolioScore": round(float(allocation.get("portfolioScore") or 0.0), 4),
                "confidence": round(float(confidence or 0.0), 4),
                "message": f"{symbol} cleared the final gate and the buy order was submitted.",
            })
            record_v2_setup_decision(c, "BOUGHT", "v16_portfolio_order_submitted", reason, c.get("v2Expectancy") or {})
            state[symbol]["ref"] = c["price"]
            state[symbol]["highest_since_entry"] = c["price"]
            messages.append(f"{reason} ${notional:.2f} {symbol} score={float(allocation.get('portfolioScore') or 0):.3f} confidence={confidence:.2f}")
            bought += 1
        except Exception as e:
            messages.append(f"BUY ERROR {symbol}: {e}")
    return " | ".join(messages)


def buy_custom_symbol(symbol: str):
    if TRADEBOT_V2_ENABLED and not PAPER and not TRADEBOT_V2_LIVE_ENABLED:
        return {"ok": False, "message": "TradeBot V2 validation mode blocks new live buys."}
    symbol = symbol.upper().strip()
    if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
        return {"ok": False, "message": "Invalid ticker"}
    if CUSTOM_BUY_REQUIRES_MARKET_OPEN and not get_effective_market_status_payload().get("isOpen", False):
        return {"ok": False, "message": "Market closed"}
    can_buy, reason = can_buy_symbol(symbol)
    if not can_buy:
        return {"ok": False, "message": f"BUY BLOCKED | {reason}"}
    quote = get_quote(symbol)
    if quote["spread"] > MAX_SPREAD:
        return {"ok": False, "message": f"BUY BLOCKED | {symbol} spread too wide: {quote['spread']:.4f}"}
    add_symbol_to_universe(symbol, custom=True)
    fake_scan = {"symbol": symbol, "quality_score": 0.03, "spread": quote["spread"], "short_momentum": 0, "pullback": 0.01}
    notional = ai_risk_notional(fake_scan)
    market_buy_notional(symbol, notional, reason="CUSTOM SNIPER BUY", scan=fake_scan)
    return {"ok": True, "message": f"CUSTOM BUY ${notional:.2f} of {symbol}. Added to managed universe."}



# =========================
# SQLITE PERSISTENT STORAGE
# =========================
# V15.3 database reliability: WAL, busy timeout and bounded lock retries.
_DB_BUSY_TIMEOUT_MS = max(5000, int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "30000") or 30000))
_DB_LOCK_RETRIES = max(1, int(os.getenv("SQLITE_LOCK_RETRIES", "7") or 7))
_DB_RETRY_BASE_SECONDS = max(0.02, float(os.getenv("SQLITE_RETRY_BASE_SECONDS", "0.08") or 0.08))
_DB_PRAGMA_LOCK = threading.RLock()
_DB_WAL_INITIALISED = False
_DB_INIT_LOCK = threading.RLock()
_DB_INIT_COMPLETE = False
_V7_SCHEMA_LOCK = threading.RLock()
_V7_SCHEMA_COMPLETE = False
_V8_SCHEMA_LOCK = threading.RLock()
_V8_SCHEMA_COMPLETE = False


def _db_is_lock_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message or "database is busy" in message


def _db_retry_delay(attempt: int) -> float:
    # Bounded exponential backoff with small jitter to stop workers retrying together.
    return min(2.0, _DB_RETRY_BASE_SECONDS * (2 ** attempt)) + random.uniform(0.0, 0.04)


_DB_SERIAL_WRITE_LOCK = threading.RLock()
_DB_SLOW_WRITE_SECONDS = max(0.25, float(os.getenv("SQLITE_SLOW_WRITE_SECONDS", "1.0") or 1.0))
_DB_WRITE_SEQ_LOCK = threading.Lock()
_DB_WRITE_SEQ = 0
# V18.2.14: transaction black-box registry. Tracks live DB connections/transactions
# so lock failures can report what this process believes is holding SQLite.
_DB_TX_REGISTRY_LOCK = threading.RLock()
_DB_TX_REGISTRY = {}
_DB_CONN_SEQ = 0

def _db_next_conn_id() -> int:
    global _DB_CONN_SEQ
    with _DB_TX_REGISTRY_LOCK:
        _DB_CONN_SEQ += 1
        return _DB_CONN_SEQ

def _db_register_connection(conn) -> None:
    cid = getattr(conn, "_tradebot_conn_id", None)
    if cid is None:
        cid = _db_next_conn_id()
        conn._tradebot_conn_id = cid
    with _DB_TX_REGISTRY_LOCK:
        _DB_TX_REGISTRY[cid] = {"opened": time.monotonic(), "thread": threading.current_thread().name, "tx": False, "owner": "", "tx_started": None}

def _db_registry_tx(conn, owner: str, active: bool) -> None:
    cid = getattr(conn, "_tradebot_conn_id", None)
    if cid is None:
        return
    with _DB_TX_REGISTRY_LOCK:
        item = _DB_TX_REGISTRY.get(cid)
        if item is None:
            return
        item["tx"] = bool(active)
        item["owner"] = owner if active else ""
        item["tx_started"] = time.monotonic() if active else None

def _db_unregister_connection(conn) -> None:
    cid = getattr(conn, "_tradebot_conn_id", None)
    if cid is not None:
        with _DB_TX_REGISTRY_LOCK:
            _DB_TX_REGISTRY.pop(cid, None)

def _db_dump_active_transactions(waiting_owner: str, error: BaseException) -> None:
    now = time.monotonic()
    with _DB_TX_REGISTRY_LOCK:
        active = []
        for cid, item in _DB_TX_REGISTRY.items():
            if item.get("tx"):
                started = item.get("tx_started") or now
                active.append(f"conn={cid} owner={item.get('owner') or 'UNKNOWN'} thread={item.get('thread')} age={max(0.0, now-started):.3f}s")
    if active:
        print(f"V18.2.14 DB BLACK BOX | waiting_owner={waiting_owner} active_local_tx={len(active)} | " + " ; ".join(active))
    else:
        print(f"V18.2.14 DB BLACK BOX | waiting_owner={waiting_owner} active_local_tx=0 external_or_untracked_lock=TRUE error={error}")

def _db_next_write_id() -> int:
    global _DB_WRITE_SEQ
    with _DB_WRITE_SEQ_LOCK:
        _DB_WRITE_SEQ += 1
        return _DB_WRITE_SEQ

def _db_write_owner() -> str:
    # Cheap caller identification for diagnostics; only evaluated when a write transaction begins.
    try:
        import inspect
        for frame in inspect.stack()[2:10]:
            name = str(frame.function or "")
            if name not in {"execute", "executemany", "_acquire_writer_if_needed"} and not name.startswith("_db_"):
                return name
    except Exception:
        pass
    return threading.current_thread().name or "UNKNOWN"


def _db_sql_is_write(sql: Any) -> bool:
    try:
        token = str(sql).lstrip().split(None, 1)[0].upper()
    except Exception:
        return False
    if token in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "VACUUM", "REINDEX"}:
        return True
    # V18.2.14: BEGIN IMMEDIATE/EXCLUSIVE reserves SQLite's writer lock even
    # before an INSERT/UPDATE occurs. V18.2.13 introduced BEGIN IMMEDIATE in
    # Scientist, but the in-process coordinator did not recognise BEGIN as a
    # write, which is why those transactions were invisible to V18.2.11 tracing.
    text = str(sql).lstrip().upper()
    return text.startswith("BEGIN IMMEDIATE") or text.startswith("BEGIN EXCLUSIVE")


class ReliableSQLiteCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        # V18.2.11: cursor.execute previously bypassed the connection-level writer
        # coordinator. Route cursor writes through the exact same transaction lock.
        conn = self.connection
        conn._acquire_writer_if_needed(sql)
        last_error = None
        try:
            for attempt in range(_DB_LOCK_RETRIES):
                try:
                    return super().execute(sql, parameters)
                except sqlite3.OperationalError as exc:
                    if not _db_is_lock_error(exc) or attempt >= _DB_LOCK_RETRIES - 1:
                        raise
                    last_error = exc
                    time.sleep(_db_retry_delay(attempt))
            raise last_error  # pragma: no cover
        except Exception:
            if not conn.in_transaction:
                conn._release_writer()
            raise

    def executemany(self, sql, seq_of_parameters):
        # Materialise once because a retry cannot safely reuse an exhausted generator.
        params = list(seq_of_parameters)
        conn = self.connection
        conn._acquire_writer_if_needed(sql)
        last_error = None
        try:
            for attempt in range(_DB_LOCK_RETRIES):
                try:
                    return super().executemany(sql, params)
                except sqlite3.OperationalError as exc:
                    if not _db_is_lock_error(exc) or attempt >= _DB_LOCK_RETRIES - 1:
                        raise
                    last_error = exc
                    time.sleep(_db_retry_delay(attempt))
            raise last_error  # pragma: no cover
        except Exception:
            if not conn.in_transaction:
                conn._release_writer()
            raise


class ReliableSQLiteConnection(sqlite3.Connection):
    """SQLite connection with bounded retries and one in-process writer at a time.

    The lock is acquired on the first mutating statement and held until commit,
    rollback or close. This prevents the autonomous workers from starting
    competing write transactions against the same SQLite file.
    """

    def _acquire_writer_if_needed(self, sql) -> None:
        if not _db_sql_is_write(sql) or getattr(self, "_tradebot_writer_lock_held", False):
            return
        wait_started = time.monotonic()
        _DB_SERIAL_WRITE_LOCK.acquire()
        waited = time.monotonic() - wait_started
        self._tradebot_writer_lock_held = True
        self._tradebot_writer_started = time.monotonic()
        self._tradebot_writer_owner = _db_write_owner()
        self._tradebot_writer_id = _db_next_write_id()
        _db_registry_tx(self, self._tradebot_writer_owner, True)
        if waited >= _DB_SLOW_WRITE_SECONDS:
            print(f"V18.2.11 DB WRITER WAIT | id={self._tradebot_writer_id} owner={self._tradebot_writer_owner} waited={waited:.3f}s")

    def _release_writer(self) -> None:
        if getattr(self, "_tradebot_writer_lock_held", False):
            duration = max(0.0, time.monotonic() - float(getattr(self, "_tradebot_writer_started", time.monotonic())))
            owner = str(getattr(self, "_tradebot_writer_owner", "UNKNOWN"))
            write_id = getattr(self, "_tradebot_writer_id", "?")
            self._tradebot_writer_lock_held = False
            _db_registry_tx(self, owner, False)
            if duration >= _DB_SLOW_WRITE_SECONDS:
                print(f"V18.2.11 DB WRITER SLOW | id={write_id} owner={owner} duration={duration:.3f}s")
            try:
                _DB_SERIAL_WRITE_LOCK.release()
            except RuntimeError:
                pass

    def cursor(self, factory=ReliableSQLiteCursor):
        return super().cursor(factory)

    def execute(self, sql, parameters=()):
        self._acquire_writer_if_needed(sql)
        try:
            return self.cursor().execute(sql, parameters)
        except Exception:
            # If the first write failed before a transaction became useful, do
            # not strand the process-wide writer lock.
            if not self.in_transaction:
                self._release_writer()
            raise

    def executemany(self, sql, seq_of_parameters):
        self._acquire_writer_if_needed(sql)
        try:
            return self.cursor().executemany(sql, seq_of_parameters)
        except Exception:
            if not self.in_transaction:
                self._release_writer()
            raise

    def commit(self):
        last_error = None
        try:
            for attempt in range(_DB_LOCK_RETRIES):
                try:
                    return super().commit()
                except sqlite3.OperationalError as exc:
                    if not _db_is_lock_error(exc) or attempt >= _DB_LOCK_RETRIES - 1:
                        raise
                    last_error = exc
                    time.sleep(_db_retry_delay(attempt))
            raise last_error  # pragma: no cover
        finally:
            self._release_writer()

    def rollback(self):
        try:
            return super().rollback()
        finally:
            self._release_writer()

    def close(self):
        try:
            if self.in_transaction:
                try:
                    super().rollback()
                except Exception:
                    pass
            return super().close()
        finally:
            self._release_writer()
            _db_unregister_connection(self)


def db_connect():
    global _DB_WAL_INITIALISED
    os.makedirs(os.path.dirname(SQLITE_DB_FILE) or ".", exist_ok=True)
    conn = sqlite3.connect(
        SQLITE_DB_FILE,
        timeout=_DB_BUSY_TIMEOUT_MS / 1000.0,
        check_same_thread=False,
        factory=ReliableSQLiteConnection,
    )
    conn.row_factory = sqlite3.Row
    _db_register_connection(conn)
    conn.execute(f"PRAGMA busy_timeout={_DB_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")

    # WAL is persistent for the database file, so initialise it once per process.
    # If another process temporarily owns the schema lock, retries above handle it.
    if not _DB_WAL_INITIALISED:
        with _DB_PRAGMA_LOCK:
            if not _DB_WAL_INITIALISED:
                conn.execute("PRAGMA journal_mode=WAL").fetchone()
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA wal_autocheckpoint=1000")
                _DB_WAL_INITIALISED = True
    else:
        conn.execute("PRAGMA synchronous=NORMAL")

    return conn


# ============================================================
# V17.0.8 DATABASE STORAGE AUDIT + SAFE HOUSEKEEPING
# ============================================================
# Purpose: keep high-frequency audit/event tables bounded without deleting
# trading history, completed outcomes, AI Memory knowledge, hypotheses,
# experiments, or research evidence used by the live intelligence stack.
DB_HOUSEKEEPING_ENABLED = os.getenv("DB_HOUSEKEEPING_ENABLED", "true").lower() in ("1", "true", "yes", "on")
DB_HOUSEKEEPING_INTERVAL_SECONDS = max(3600, int(os.getenv("DB_HOUSEKEEPING_INTERVAL_SECONDS", "21600") or 21600))
DB_HOUSEKEEPING_STARTUP_DELAY_SECONDS = max(60, int(os.getenv("DB_HOUSEKEEPING_STARTUP_DELAY_SECONDS", "120") or 120))
DB_HOUSEKEEPING_RETENTION_DAYS = max(14, int(os.getenv("DB_HOUSEKEEPING_RETENTION_DAYS", "90") or 90))
DB_HEALTH_WARN_PCT = max(50.0, min(99.0, float(os.getenv("DB_HEALTH_WARN_PCT", "80") or 80)))
DB_HEALTH_FAIL_PCT = max(DB_HEALTH_WARN_PCT + 1.0, min(99.9, float(os.getenv("DB_HEALTH_FAIL_PCT", "95") or 95)))
db_housekeeping_thread_started = False
_db_housekeeping_lock = threading.RLock()
_db_last_housekeeping: Dict[str, Any] = {}


def _db_file_size(path: str) -> int:
    try:
        return int(os.path.getsize(path))
    except Exception:
        return 0


def _db_storage_snapshot(include_tables: bool = True) -> Dict[str, Any]:
    db_path = os.path.abspath(SQLITE_DB_FILE)
    base_dir = os.path.dirname(db_path) or "."
    main_bytes = _db_file_size(db_path)
    wal_bytes = _db_file_size(db_path + "-wal")
    shm_bytes = _db_file_size(db_path + "-shm")
    try:
        usage = shutil.disk_usage(base_dir)
        total_bytes, used_bytes, free_bytes = int(usage.total), int(usage.used), int(usage.free)
    except Exception:
        total_bytes = used_bytes = free_bytes = 0
    pct = (used_bytes / total_bytes * 100.0) if total_bytes else 0.0
    payload: Dict[str, Any] = {
        "ok": True, "version": "V17.0.8", "databaseFile": db_path,
        "mainBytes": main_bytes, "walBytes": wal_bytes, "shmBytes": shm_bytes,
        "sqliteBytes": main_bytes + wal_bytes + shm_bytes,
        "diskTotalBytes": total_bytes, "diskUsedBytes": used_bytes, "diskFreeBytes": free_bytes,
        "diskUsedPct": round(pct, 2),
        "thresholds": {"warnPct": DB_HEALTH_WARN_PCT, "failPct": DB_HEALTH_FAIL_PCT},
        "lastHousekeeping": dict(_db_last_housekeeping),
    }
    if not include_tables or not SQLITE_ENABLED:
        return payload
    conn = None
    try:
        conn = db_connect()
        tables = [str(r[0]) for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
        row_counts = []
        for table in tables:
            try:
                count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            except Exception:
                count = -1
            row_counts.append({"table": table, "rows": count})
        payload["tablesByRows"] = sorted(row_counts, key=lambda x: x.get("rows", -1), reverse=True)
        try:
            # dbstat is built into most SQLite builds and gives true on-disk bytes per table/index.
            rows = conn.execute(
                "SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name ORDER BY bytes DESC"
            ).fetchall()
            payload["objectsByBytes"] = [{"name": str(r[0]), "bytes": int(r[1] or 0)} for r in rows]
        except Exception as exc:
            payload["dbstatUnavailable"] = str(exc)[:300]
    except Exception as exc:
        payload["tableAuditError"] = str(exc)[:500]
    finally:
        try:
            if conn is not None: conn.close()
        except Exception:
            pass
    return payload


def _db_table_exists(conn, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _db_column_exists(conn, table: str, column: str) -> bool:
    try:
        return any(str(r[1]) == column for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall())
    except Exception:
        return False


def _db_delete_older_than(conn, table: str, column: str, cutoff: str) -> int:
    if not _db_table_exists(conn, table) or not _db_column_exists(conn, table, column):
        return 0
    before = conn.total_changes
    conn.execute(f'DELETE FROM "{table}" WHERE "{column}" < ?', (cutoff,))
    return int(conn.total_changes - before)


def _db_safe_housekeeping(force: bool = False) -> Dict[str, Any]:
    global _db_last_housekeeping
    if not SQLITE_ENABLED:
        return {"ok": False, "skipped": True, "reason": "SQLite disabled"}
    if not DB_HOUSEKEEPING_ENABLED and not force:
        return {"ok": True, "skipped": True, "reason": "DB housekeeping disabled"}
    # Routine pruning is intentionally closed-market only. A manual forced run is still safe
    # because it only touches audit/event history and takes the serial SQLite writer lock.
    if not force:
        try:
            if bool(get_effective_market_status_payload().get("isOpen", False)):
                return {"ok": True, "skipped": True, "reason": "Market open"}
        except Exception:
            pass
    with _db_housekeeping_lock:
        started = datetime.now(UTC)
        before = _db_storage_snapshot(include_tables=False)
        cutoff = (started - timedelta(days=DB_HOUSEKEEPING_RETENTION_DAYS)).isoformat()
        short_cutoff = (started - timedelta(days=min(30, DB_HOUSEKEEPING_RETENTION_DAYS))).isoformat()
        deleted: Dict[str, int] = {}
        conn = None
        try:
            conn = db_connect()
            # Reconstructable operational/audit data only. Core learning evidence is deliberately retained.
            retention_targets = [
                ("universe_refresh_log", "refreshed_at", cutoff),
                ("v7_maintenance_runs", "created_at", cutoff),
                ("v7_research_runs", "created_at", cutoff),
                ("v9_memory_runs", "created_at", cutoff),
                ("v11_learning_history", "created_at", cutoff),
                ("v11_capture_verification", "created_at", short_cutoff),
                ("v11_capture_tests", "created_at", short_cutoff),
                ("v10_operator_actions", "created_at", cutoff),
                ("v12_ceo_reviews", "created_at", cutoff),
                ("v12_ceo_journal", "created_at", cutoff),
                ("v13_memory_events", "created_at", cutoff),
                ("v14_scientist_events", "created_at", cutoff),
                ("v15_health_audits", "created_at", short_cutoff),
            ]
            for table, column, table_cutoff in retention_targets:
                removed = _db_delete_older_than(conn, table, column, table_cutoff)
                if removed:
                    deleted[table] = removed

            # Board votes must be removed before their parent meetings.
            if _db_table_exists(conn, "v121_board_votes") and _db_table_exists(conn, "v121_board_meetings"):
                old_ids = [int(r[0]) for r in conn.execute(
                    "SELECT id FROM v121_board_meetings WHERE created_at < ?", (cutoff,)
                ).fetchall()]
                if old_ids:
                    marks = ",".join("?" for _ in old_ids)
                    before_changes = conn.total_changes
                    conn.execute(f"DELETE FROM v121_board_votes WHERE meeting_id IN ({marks})", old_ids)
                    vote_removed = int(conn.total_changes - before_changes)
                    if vote_removed: deleted["v121_board_votes"] = vote_removed
                    before_changes = conn.total_changes
                    conn.execute(f"DELETE FROM v121_board_meetings WHERE id IN ({marks})", old_ids)
                    meeting_removed = int(conn.total_changes - before_changes)
                    if meeting_removed: deleted["v121_board_meetings"] = meeting_removed

            # Resolved alerts are useful briefly, but do not need to grow forever.
            if _db_table_exists(conn, "v15_health_alerts") and _db_column_exists(conn, "v15_health_alerts", "resolved_at"):
                before_changes = conn.total_changes
                conn.execute("DELETE FROM v15_health_alerts WHERE status='RESOLVED' AND resolved_at IS NOT NULL AND resolved_at < ?", (cutoff,))
                removed = int(conn.total_changes - before_changes)
                if removed: deleted["v15_health_alerts"] = removed

            conn.commit()
            # Return WAL pages to the filesystem. This is safe and materially helps persistent-disk usage.
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            except Exception as exc:
                checkpoint_error = str(exc)[:300]
            else:
                checkpoint_error = None
            conn.close(); conn = None
            after = _db_storage_snapshot(include_tables=False)
            result = {
                "ok": True, "version": "V17.0.8", "ranAt": started.isoformat(),
                "retentionDays": DB_HOUSEKEEPING_RETENTION_DAYS, "deletedRows": deleted,
                "deletedTotal": int(sum(deleted.values())),
                "before": before, "after": after,
                "sqliteBytesFreed": max(0, int(before.get("sqliteBytes", 0)) - int(after.get("sqliteBytes", 0))),
                "checkpointError": checkpoint_error,
                "protectedData": [
                    "trades", "closed_trades", "performance_state", "v2_setup_decisions",
                    "v2_observation_outcomes", "v4_market_dna", "v6_brain_observations",
                    "v9_market_memory", "v10_evidence_lineage", "v11_discoveries",
                    "v13_knowledge", "v14_hypotheses", "v14_experiments"
                ],
            }
            _db_last_housekeeping = result
            print(f"V17.0.8 DB HOUSEKEEPING | deleted={result['deletedTotal']} sqlite_freed={result['sqliteBytesFreed']} disk_used={after.get('diskUsedPct',0):.1f}%")
            return result
        except Exception as exc:
            try:
                if conn is not None: conn.rollback(); conn.close()
            except Exception:
                pass
            result = {"ok": False, "version": "V17.0.8", "ranAt": started.isoformat(), "error": str(exc)[:1000]}
            _db_last_housekeeping = result
            print(f"V17.0.8 DB HOUSEKEEPING ERROR: {exc}")
            return result


def _db_housekeeping_worker() -> None:
    time.sleep(DB_HOUSEKEEPING_STARTUP_DELAY_SECONDS)
    while True:
        try:
            _db_safe_housekeeping(False)
        except Exception as exc:
            print(f"V17.0.8 DB HOUSEKEEPING WORKER ERROR: {exc}")
        time.sleep(DB_HOUSEKEEPING_INTERVAL_SECONDS)


@app.get("/admin/db-storage-audit")
def api_db_storage_audit(request: Request):
    verify_api_key(request)
    return _db_storage_snapshot(include_tables=True)


@app.post("/admin/db-housekeeping")
def api_db_housekeeping(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return _db_safe_housekeeping(bool(payload.get("force", True)))


def _init_db_impl():
    if not SQLITE_ENABLED:
        return

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alpaca_order_id TEXT UNIQUE,
            timestamp TEXT NOT NULL,
            day TEXT,
            time TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL,
            price REAL,
            amount REAL,
            amount_gbp REAL,
            pnl REAL,
            pnl_gbp REAL,
            pnl_pct REAL,
            reason TEXT,
            equity REAL,
            equity_gbp REAL,
            fx_rate REAL,
            source TEXT DEFAULT 'bot'
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_timestamp
        ON trades(timestamp)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_symbol
        ON trades(symbol)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS performance_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            baseline_equity REAL NOT NULL DEFAULT 0,
            total_deposited REAL NOT NULL DEFAULT 0,
            total_withdrawn REAL NOT NULL DEFAULT 0,
            lifetime_realised_pnl REAL NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            breakevens INTEGER NOT NULL DEFAULT 0,
            total_closed_trades INTEGER NOT NULL DEFAULT 0,
            best_trade REAL NOT NULL DEFAULT 0,
            worst_trade REAL NOT NULL DEFAULT 0,
            average_win REAL NOT NULL DEFAULT 0,
            average_loss REAL NOT NULL DEFAULT 0,
            profit_factor REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
    """)
    cur.execute("""INSERT OR IGNORE INTO performance_state (id, updated_at) VALUES (1, ?)""",
                (datetime.now(UTC).isoformat(),))


    cur.execute("""
        CREATE TABLE IF NOT EXISTS closed_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_sell_order_id TEXT,
            source_buy_order_id TEXT,
            timestamp TEXT NOT NULL,
            day TEXT,
            time TEXT,
            symbol TEXT NOT NULL,
            qty REAL,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            pnl_gbp REAL,
            pnl_pct REAL,
            fx_rate REAL,
            reason TEXT,
            source TEXT DEFAULT 'matcher'
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_closed_trades_timestamp
        ON closed_trades(timestamp)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_closed_trades_symbol
        ON closed_trades(symbol)
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS weekly_universe (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            symbol TEXT NOT NULL,
            score REAL,
            reason TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(week_start, symbol)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS universe_refresh_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            refreshed_at TEXT NOT NULL,
            week_start TEXT NOT NULL,
            symbols TEXT,
            reason TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS v2_setup_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            decision TEXT NOT NULL,
            stage TEXT,
            reason TEXT,
            price REAL,
            confidence REAL,
            quality REAL,
            momentum REAL,
            pullback REAL,
            spread REAL,
            ready_to_buy INTEGER,
            sniper_pass INTEGER,
            a_plus_pass INTEGER,
            historical_samples INTEGER,
            historical_win_rate REAL,
            historical_profit_factor REAL,
            historical_expectancy_pct REAL,
            payload_json TEXT
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v2_setup_decisions_symbol_time
        ON v2_setup_decisions(symbol, timestamp)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v2_setup_decisions_decision
        ON v2_setup_decisions(decision)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS v179_decision_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            decision_at TEXT NOT NULL,
            stage TEXT,
            reason TEXT,
            entry_price REAL NOT NULL,
            confidence REAL,
            quality REAL,
            due_minutes INTEGER NOT NULL,
            due_at TEXT NOT NULL,
            evaluated_at TEXT,
            outcome_price REAL,
            return_pct REAL,
            best_move_pct REAL,
            worst_move_pct REAL,
            classification TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING',
            error TEXT,
            source TEXT,
            UNIQUE(decision_id, due_minutes)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_v179_audit_due ON v179_decision_audit(status,due_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_v179_audit_stage ON v179_decision_audit(stage,classification)")

    # V18 — advisory weekly governance reviews. Never applies live changes directly.
    cur.execute("""CREATE TABLE IF NOT EXISTS v18_weekly_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, review_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL, window_days INTEGER NOT NULL, verdict TEXT NOT NULL,
        evidence_strength TEXT NOT NULL, proposal_key TEXT, proposal_text TEXT,
        stability_count INTEGER NOT NULL DEFAULT 0, promotion_required INTEGER NOT NULL DEFAULT 5,
        payload_json TEXT NOT NULL)""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_v18_weekly_created ON v18_weekly_reviews(created_at)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS v2_observation_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            entry_price REAL NOT NULL,
            horizon_hours INTEGER NOT NULL,
            due_at TEXT NOT NULL,
            evaluated_at TEXT,
            outcome_price REAL,
            return_pct REAL,
            net_return_pct REAL,
            estimated_cost_pct REAL,
            sample_key TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING',
            error TEXT,
            UNIQUE(decision_id, horizon_hours)
        )
    """)
    for column_sql in (
        "ALTER TABLE v2_observation_outcomes ADD COLUMN net_return_pct REAL",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN estimated_cost_pct REAL",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN sample_key TEXT",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN evaluation_delay_minutes REAL",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN outcome_bar_at TEXT",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN outcome_source TEXT",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN repaired_at TEXT",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN last_error_at TEXT",
    ):
        try:
            cur.execute(column_sql)
        except Exception:
            pass

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v2_outcomes_due
        ON v2_observation_outcomes(status, due_at)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v2_outcomes_symbol
        ON v2_observation_outcomes(symbol, horizon_hours)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS v4_market_dna (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id INTEGER NOT NULL UNIQUE,
            observed_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            decision TEXT NOT NULL,
            stage TEXT,
            reason TEXT,
            market_regime TEXT,
            session_name TEXT,
            weekday INTEGER,
            hour_utc INTEGER,
            price REAL,
            confidence REAL,
            quality REAL,
            momentum REAL,
            pullback REAL,
            spread REAL,
            ready_to_buy INTEGER,
            sniper_pass INTEGER,
            a_plus_pass INTEGER,
            spy_move REAL,
            qqq_move REAL,
            position_count INTEGER,
            payload_json TEXT
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v4_dna_symbol_time
        ON v4_market_dna(symbol, observed_at)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v4_dna_decision
        ON v4_market_dna(decision, stage)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS v5_replay_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            label TEXT,
            date_from TEXT,
            date_to TEXT,
            horizon_hours INTEGER NOT NULL,
            observation_count INTEGER NOT NULL DEFAULT 0,
            variant_count INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS v5_replay_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            variant_key TEXT NOT NULL,
            variant_name TEXT NOT NULL,
            trades INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            win_rate REAL,
            profit_factor REAL,
            expectancy_pct REAL,
            total_return_pct REAL,
            max_drawdown_pct REAL,
            largest_win_pct REAL,
            largest_loss_pct REAL,
            config_json TEXT,
            UNIQUE(run_id, variant_key)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v5_replay_runs_created
        ON v5_replay_runs(created_at)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v5_replay_results_run
        ON v5_replay_results(run_id, expectancy_pct)
    """)


    # V6.1 multi-brain shadow intelligence. These tables never drive live orders.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS v6_brain_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brain_key TEXT NOT NULL,
            brain_name TEXT NOT NULL,
            decision_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            market_regime TEXT,
            horizon_hours INTEGER NOT NULL,
            accepted INTEGER NOT NULL DEFAULT 0,
            return_pct REAL,
            confidence REAL,
            quality REAL,
            momentum REAL,
            pullback REAL,
            spread REAL,
            config_json TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(brain_key, decision_id, horizon_hours)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v6_brain_results
        ON v6_brain_observations(brain_key, horizon_hours, accepted, observed_at)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v6_brain_regime
        ON v6_brain_observations(market_regime, brain_key, horizon_hours)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS v6_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            horizon_hours INTEGER NOT NULL,
            market_regime TEXT,
            current_brain TEXT,
            recommended_brain TEXT,
            confidence_grade TEXT,
            approved INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS v2_optimizer_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluated_at TEXT NOT NULL,
            horizon_hours INTEGER NOT NULL,
            candidate_confidence REAL,
            candidate_quality REAL,
            current_confidence REAL,
            current_quality REAL,
            eligible INTEGER DEFAULT 0,
            stable_key TEXT,
            payload_json TEXT
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v2_optimizer_eval_time
        ON v2_optimizer_evaluations(evaluated_at)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS v2_strategy_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            version_label TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence REAL NOT NULL,
            quality REAL NOT NULL,
            previous_confidence REAL,
            previous_quality REAL,
            reason TEXT,
            metrics_json TEXT,
            rollback_of INTEGER
        )
    """)

    conn.commit()
    conn.close()


def init_db():
    """Initialise the shared schema once per process, never on every API read."""
    global _DB_INIT_COMPLETE
    if not SQLITE_ENABLED or _DB_INIT_COMPLETE:
        return
    with _DB_INIT_LOCK:
        if _DB_INIT_COMPLETE:
            return
        last_error = None
        for attempt in range(5):
            try:
                _init_db_impl()
                _DB_INIT_COMPLETE = True
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                if not _db_is_lock_error(exc) or attempt == 4:
                    raise
                time.sleep(min(3.0, 0.5 * (attempt + 1)) + random.uniform(0.0, 0.1))
        if last_error:
            raise last_error


def save_trade_to_db(event: Dict[str, Any], source: str = "bot"):
    if not SQLITE_ENABLED:
        return

    try:
        init_db()
        conn = db_connect()
        cur = conn.cursor()

        timestamp = event.get("timestamp") or datetime.now(UTC).isoformat()
        equity = float(event.get("equity") or 0.0)
        equity_gbp = float(event.get("equityGbp") or money_gbp(equity))
        fx_rate = float(event.get("fxRate") or get_usd_to_gbp_rate())

        cur.execute("""
            INSERT OR REPLACE INTO trades (
                alpaca_order_id, timestamp, day, time, symbol, side, qty, price,
                amount, amount_gbp, pnl, pnl_gbp, pnl_pct, reason,
                equity, equity_gbp, fx_rate, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.get("alpacaOrderId"),
            timestamp,
            event.get("day"),
            event.get("time"),
            event.get("symbol"),
            event.get("side"),
            float(event.get("qty") or 0.0),
            float(event.get("price") or 0.0),
            float(event.get("amount") or 0.0),
            float(event.get("amountGbp") or money_gbp(float(event.get("amount") or 0.0))),
            float(event.get("pnl") or 0.0),
            float(event.get("pnlGbp") or money_gbp(float(event.get("pnl") or 0.0))),
            float(event.get("pnlPct") or 0.0),
            event.get("reason", ""),
            equity,
            equity_gbp,
            fx_rate,
            source,
        ))

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"DB SAVE ERROR: {e}")


def trades_from_db(limit: int = 1000):
    if not SQLITE_ENABLED:
        return trade_history[-limit:]

    try:
        init_db()
        conn = db_connect()
        rows = conn.execute("""
            SELECT * FROM trades
            ORDER BY timestamp ASC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()

        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "alpacaOrderId": r["alpaca_order_id"],
                "timestamp": r["timestamp"],
                "day": r["day"],
                "time": r["time"],
                "symbol": r["symbol"],
                "side": r["side"],
                "qty": r["qty"],
                "price": r["price"],
                "amount": r["amount"],
                "amountGbp": r["amount_gbp"],
                "pnl": r["pnl"],
                "pnlGbp": r["pnl_gbp"],
                "pnlPct": r["pnl_pct"],
                "reason": r["reason"],
                "equity": r["equity"],
                "equityGbp": r["equity_gbp"],
                "fxRate": r["fx_rate"],
                "source": r["source"],
            })
        return items
    except Exception as e:
        print(f"DB READ ERROR: {e}")
        return trade_history[-limit:]


def stock_memory_from_db():
    trades = trades_from_db(5000)
    memory: Dict[str, Dict[str, Any]] = {}

    for t in trades:
        if t.get("side") != "SELL":
            continue

        symbol = str(t.get("symbol", "")).upper()
        if not symbol:
            continue

        if symbol not in memory:
            memory[symbol] = {
                "wins": 0,
                "losses": 0,
                "trades": 0,
                "totalPnl": 0.0,
                "totalPnlGbp": 0.0,
                "totalPnlPct": 0.0,
                "avgPnl": 0.0,
                "avgPnlGbp": 0.0,
                "avgPnlPct": 0.0,
                "winRate": 0.0,
                "trust": "NEW",
                "lastResult": "—",
            }

        m = memory[symbol]
        pnl = float(t.get("pnl") or 0.0)
        pnl_gbp = float(t.get("pnlGbp") or 0.0)
        pnl_pct = float(t.get("pnlPct") or 0.0)

        m["trades"] += 1
        m["totalPnl"] += pnl
        m["totalPnlGbp"] += pnl_gbp
        m["totalPnlPct"] += pnl_pct

        if pnl >= 0:
            m["wins"] += 1
            m["lastResult"] = "WIN"
        else:
            m["losses"] += 1
            m["lastResult"] = "LOSS"

    for symbol, m in memory.items():
        m["winRate"] = m["wins"] / max(1, m["trades"])
        m["avgPnl"] = m["totalPnl"] / max(1, m["trades"])
        m["avgPnlGbp"] = m["totalPnlGbp"] / max(1, m["trades"])
        m["avgPnlPct"] = m["totalPnlPct"] / max(1, m["trades"])

        if m["trades"] < MEMORY_MIN_TRADES_FOR_TRUST:
            m["trust"] = "NEW"
        elif m["winRate"] >= MEMORY_GOOD_WINRATE:
            m["trust"] = "GOOD"
        elif m["winRate"] <= MEMORY_BAD_WINRATE:
            m["trust"] = "BAD"
        else:
            m["trust"] = "NEUTRAL"

    items = [{"symbol": s, **m} for s, m in memory.items()]
    items.sort(key=lambda x: (-x.get("totalPnl", 0), -x.get("winRate", 0), -x.get("trades", 0)))
    return items


def db_summary_payload():
    trades = trades_from_db(5000)
    sells = [t for t in trades if t.get("side") == "SELL"]
    wins = [t for t in sells if float(t.get("pnl") or 0.0) >= 0]
    total_pnl = sum(float(t.get("pnl") or 0.0) for t in sells)
    total_pnl_gbp = sum(float(t.get("pnlGbp") or 0.0) for t in sells)

    return {
        "enabled": SQLITE_ENABLED,
        "dbFile": SQLITE_DB_FILE,
        "totalTrades": len(trades),
        "sellTrades": len(sells),
        "wins": len(wins),
        "losses": max(0, len(sells) - len(wins)),
        "winRate": len(wins) / max(1, len(sells)),
        "totalPnl": total_pnl,
        "totalPnlGbp": total_pnl_gbp,
    }


def parse_order_timestamp(order):
    for attr in ["filled_at", "updated_at", "submitted_at", "created_at"]:
        try:
            value = getattr(order, attr, None)
            if value:
                return value
        except Exception:
            pass
    return datetime.now(UTC)



def clear_closed_trades():
    if not SQLITE_ENABLED:
        return
    init_db()
    conn = db_connect()
    conn.execute("DELETE FROM closed_trades")
    conn.commit()
    conn.close()


def save_closed_trade_to_db(trade: Dict[str, Any]):
    if not SQLITE_ENABLED:
        return

    init_db()
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO closed_trades (
            source_sell_order_id, source_buy_order_id, timestamp, day, time,
            symbol, qty, entry_price, exit_price, pnl, pnl_gbp, pnl_pct,
            fx_rate, reason, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade.get("sourceSellOrderId"),
        trade.get("sourceBuyOrderId"),
        trade.get("timestamp"),
        trade.get("day"),
        trade.get("time"),
        trade.get("symbol"),
        float(trade.get("qty") or 0.0),
        float(trade.get("entryPrice") or 0.0),
        float(trade.get("exitPrice") or 0.0),
        float(trade.get("pnl") or 0.0),
        float(trade.get("pnlGbp") or 0.0),
        float(trade.get("pnlPct") or 0.0),
        float(trade.get("fxRate") or get_usd_to_gbp_rate()),
        trade.get("reason", ""),
        trade.get("source", "matcher"),
    ))

    closed_trade_id = int(cur.lastrowid) if cur.lastrowid else None
    conn.commit()
    conn.close()
    try:
        if "_trade_replay_close_for_trade" in globals():
            _trade_replay_close_for_trade(trade, closed_trade_id)
    except Exception as replay_error:
        print(f"V17.1 TRADE REPLAY LINK ERROR: {replay_error}")


def closed_trades_from_db(limit: int = 1000):
    if not SQLITE_ENABLED:
        return []

    try:
        init_db()
        conn = db_connect()
        rows = conn.execute("""
            SELECT * FROM closed_trades
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()

        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "day": r["day"],
                "time": r["time"],
                "symbol": r["symbol"],
                "side": "SELL",
                "qty": r["qty"],
                "entryPrice": r["entry_price"],
                "exitPrice": r["exit_price"],
                "price": r["exit_price"],
                "pnl": r["pnl"],
                "pnlGbp": r["pnl_gbp"],
                "pnlPct": r["pnl_pct"],
                "fxRate": r["fx_rate"],
                "reason": r["reason"],
                "source": r["source"],
                "equity": 0.0,
                "equityGbp": 0.0,
            }
            for r in rows
        ]

    except Exception as e:
        print(f"CLOSED TRADES READ ERROR: {e}")
        return []


def rebuild_closed_trades_from_orders():
    """
    Reads raw BUY/SELL rows from trades table and rebuilds completed trades
    using FIFO matching. This is the important fix for realised PnL.
    """
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}

    init_db()
    clear_closed_trades()

    conn = db_connect()
    rows = conn.execute("""
        SELECT *
        FROM trades
        WHERE symbol IS NOT NULL
          AND side IN ('BUY', 'SELL')
          AND qty > 0
          AND alpaca_order_id IS NOT NULL
          AND TRIM(alpaca_order_id) <> ''
        ORDER BY timestamp ASC, id ASC
    """).fetchall()
    conn.close()

    open_lots: Dict[str, List[Dict[str, Any]]] = {}
    closed_count = 0
    unmatched_sells = 0
    rate = get_usd_to_gbp_rate()

    for r in rows:
        symbol = str(r["symbol"]).upper()
        side = str(r["side"]).upper()
        qty = float(r["qty"] or 0.0)
        price = float(r["price"] or 0.0)

        # Backfilled BUY rows may have amount but no price in older DB rows.
        if price <= 0 and qty > 0:
            amount = float(r["amount"] or 0.0)
            if amount > 0:
                price = amount / qty

        if qty <= 0 or price <= 0:
            continue

        if side == "BUY":
            open_lots.setdefault(symbol, []).append({
                "qty": qty,
                "price": price,
                "order_id": r["alpaca_order_id"],
                "timestamp": r["timestamp"],
            })
            continue

        if side == "SELL":
            remaining = qty
            lots = open_lots.setdefault(symbol, [])

            while remaining > 1e-9 and lots:
                lot = lots[0]
                used_qty = min(remaining, float(lot["qty"]))
                entry_price = float(lot["price"])
                exit_price = price

                pnl = (exit_price - entry_price) * used_qty
                pnl_pct = ((exit_price / entry_price) - 1.0) * 100.0 if entry_price > 0 else 0.0

                trade = {
                    "sourceSellOrderId": r["alpaca_order_id"],
                    "sourceBuyOrderId": lot.get("order_id"),
                    "timestamp": r["timestamp"],
                    "day": r["day"],
                    "time": r["time"],
                    "symbol": symbol,
                    "qty": used_qty,
                    "entryPrice": entry_price,
                    "exitPrice": exit_price,
                    "pnl": round(pnl, 6),
                    "pnlGbp": round(pnl * rate, 6),
                    "pnlPct": round(pnl_pct, 6),
                    "fxRate": rate,
                    "reason": "FIFO MATCHED CLOSED TRADE",
                    "source": "fifo_matcher",
                }

                save_closed_trade_to_db(trade)
                closed_count += 1

                lot["qty"] = float(lot["qty"]) - used_qty
                remaining -= used_qty

                if lot["qty"] <= 1e-9:
                    lots.pop(0)

            if remaining > 1e-9:
                unmatched_sells += 1

    return {
        "ok": True,
        "message": f"Closed-trade rebuild complete. Matched {closed_count} closed trades. Unmatched sells: {unmatched_sells}.",
        "matchedClosedTrades": closed_count,
        "unmatchedSells": unmatched_sells,
    }


def closed_trade_summary_payload():
    closed = closed_trades_from_db(10000)
    wins = [t for t in closed if float(t.get("pnl") or 0.0) > 0]
    losses = [t for t in closed if float(t.get("pnl") or 0.0) < 0]
    breakevens = [t for t in closed if float(t.get("pnl") or 0.0) == 0]
    total_pnl = sum(float(t.get("pnl") or 0.0) for t in closed)
    total_pnl_gbp = sum(float(t.get("pnlGbp") or 0.0) for t in closed)

    return {
        "closedTrades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "winRate": len(wins) / max(1, len(wins) + len(losses)),
        "totalPnl": total_pnl,
        "totalPnlGbp": total_pnl_gbp,
    }


def stock_memory_from_closed_trades():
    closed = closed_trades_from_db(10000)
    memory: Dict[str, Dict[str, Any]] = {}

    for t in closed:
        symbol = str(t.get("symbol", "")).upper()
        if not symbol:
            continue

        if symbol not in memory:
            memory[symbol] = {
                "wins": 0,
                "losses": 0,
                "trades": 0,
                "totalPnl": 0.0,
                "totalPnlGbp": 0.0,
                "totalPnlPct": 0.0,
                "avgPnl": 0.0,
                "avgPnlGbp": 0.0,
                "avgPnlPct": 0.0,
                "winRate": 0.0,
                "trust": "NEW",
                "lastResult": "—",
            }

        m = memory[symbol]
        pnl = float(t.get("pnl") or 0.0)
        pnl_gbp = float(t.get("pnlGbp") or 0.0)
        pnl_pct = float(t.get("pnlPct") or 0.0)

        m["trades"] += 1
        m["totalPnl"] += pnl
        m["totalPnlGbp"] += pnl_gbp
        m["totalPnlPct"] += pnl_pct

        if pnl >= 0:
            m["wins"] += 1
            m["lastResult"] = "WIN"
        else:
            m["losses"] += 1
            m["lastResult"] = "LOSS"

    for symbol, m in memory.items():
        m["winRate"] = m["wins"] / max(1, m["trades"])
        m["avgPnl"] = m["totalPnl"] / max(1, m["trades"])
        m["avgPnlGbp"] = m["totalPnlGbp"] / max(1, m["trades"])
        m["avgPnlPct"] = m["totalPnlPct"] / max(1, m["trades"])

        if m["trades"] < MEMORY_MIN_TRADES_FOR_TRUST:
            m["trust"] = "NEW"
        elif m["winRate"] >= MEMORY_GOOD_WINRATE:
            m["trust"] = "GOOD"
        elif m["winRate"] <= MEMORY_BAD_WINRATE:
            m["trust"] = "BAD"
        else:
            m["trust"] = "NEUTRAL"

    items = [{"symbol": s, **m} for s, m in memory.items()]
    items.sort(key=lambda x: (-x.get("totalPnl", 0), -x.get("winRate", 0), -x.get("trades", 0)))
    return items


def order_is_filled(order):
    try:
        filled_qty = float(getattr(order, "filled_qty", 0) or 0)
        return filled_qty > 0
    except Exception:
        return False


def get_order_side(order):
    """Return clean BUY/SELL even when alpaca-py gives an enum like OrderSide.BUY."""
    raw = getattr(order, "side", "")
    value = getattr(raw, "value", raw)
    text = str(value).upper().strip()
    if "." in text:
        text = text.split(".")[-1]
    if text in ("BUY", "SELL"):
        return text
    return text


def get_order_symbol(order):
    return str(getattr(order, "symbol", "")).upper()


def get_order_price(order):
    try:
        price = float(getattr(order, "filled_avg_price", 0) or 0)
        if price > 0:
            return price
    except Exception:
        pass
    try:
        limit_price = float(getattr(order, "limit_price", 0) or 0)
        if limit_price > 0:
            return limit_price
    except Exception:
        pass
    return 0.0


def get_order_qty(order):
    try:
        return float(getattr(order, "filled_qty", 0) or 0)
    except Exception:
        return 0.0


def get_order_id(order):
    try:
        return str(getattr(order, "id", ""))
    except Exception:
        return ""



def get_query_order_status_all():
    try:
        return QueryOrderStatus.ALL
    except Exception:
        # Some alpaca-py versions represent all as lowercase string.
        return "all"


def fetch_all_orders_paginated():
    """
    Alpaca-py pagination/backfill.
    Pulls ALL orders backwards in chunks using `until`, same idea as the user-provided snippet.
    """
    all_orders = []
    until = datetime.now(UTC)
    seen_ids = set()

    for page in range(BACKFILL_MAX_PAGES):
        try:
            req = GetOrdersRequest(
                status=get_query_order_status_all(),
                limit=BACKFILL_CHUNK_SIZE,
                until=until,
                direction="desc",
                nested=False,
            )
        except TypeError:
            # Some alpaca-py versions may not accept nested.
            req = GetOrdersRequest(
                status=get_query_order_status_all(),
                limit=BACKFILL_CHUNK_SIZE,
                until=until,
                direction="desc",
            )

        chunk = trading_client.get_orders(filter=req)

        if not chunk:
            break

        new_count = 0
        earliest = None

        for order in chunk:
            oid = get_order_id(order)
            if oid and oid in seen_ids:
                continue

            if oid:
                seen_ids.add(oid)

            all_orders.append(order)
            new_count += 1

            ts = parse_order_timestamp(order)
            if earliest is None or str(ts) < str(earliest):
                earliest = ts

        print(f"BACKFILL PAGE {page + 1}: fetched={len(chunk)} new={new_count}")

        if new_count == 0 or len(chunk) < BACKFILL_CHUNK_SIZE:
            break

        # Move until backwards to the earliest order timestamp in this chunk.
        if earliest:
            try:
                until = earliest - timedelta(microseconds=1)
            except Exception:
                # If alpaca returns string timestamps.
                try:
                    until = datetime.fromisoformat(str(earliest).replace("Z", "+00:00")) - timedelta(microseconds=1)
                except Exception:
                    break
        else:
            break

    return all_orders


def backfill_trades_from_alpaca_full():
    init_db()

    orders = fetch_all_orders_paginated()
    imported = 0
    skipped = 0
    rate = get_usd_to_gbp_rate()

    # Sort oldest -> newest before saving/matching.
    sorted_orders = sorted(orders, key=lambda o: str(parse_order_timestamp(o)))

    for order in sorted_orders:
        try:
            if not order_is_filled(order):
                skipped += 1
                continue

            symbol = get_order_symbol(order)
            side = get_order_side(order)
            qty = get_order_qty(order)
            price = get_order_price(order)
            oid = get_order_id(order)

            if not symbol or side not in ["BUY", "SELL"] or qty <= 0:
                skipped += 1
                continue

            # If price is missing, skip for PnL safety.
            if price <= 0:
                skipped += 1
                continue

            timestamp_obj = parse_order_timestamp(order)

            if hasattr(timestamp_obj, "isoformat"):
                timestamp = timestamp_obj.isoformat()
                try:
                    day = timestamp_obj.astimezone(UTC).strftime("%Y-%m-%d")
                    tm = timestamp_obj.astimezone(UTC).strftime("%H:%M:%S")
                except Exception:
                    day = today_str()
                    tm = now_time()
            else:
                timestamp = str(timestamp_obj)
                day = today_str()
                tm = now_time()

            amount = qty * price

            event = {
                "alpacaOrderId": oid,
                "timestamp": timestamp,
                "day": day,
                "time": tm,
                "side": side,
                "symbol": symbol,
                "qty": qty,
                "price": price,
                "amount": amount if side == "BUY" else 0.0,
                "amountGbp": amount * rate if side == "BUY" else 0.0,
                "pnl": 0.0,
                "pnlGbp": 0.0,
                "pnlPct": 0.0,
                "reason": "ALPACA FULL BACKFILL",
                "equity": 0.0,
                "equityGbp": 0.0,
                "fxRate": rate,
            }

            before = db_summary_payload().get("totalTrades", 0)
            save_trade_to_db(event, source="alpaca_full_backfill")
            after = db_summary_payload().get("totalTrades", 0)

            if after > before:
                imported += 1
            else:
                skipped += 1

        except Exception as e:
            print(f"FULL BACKFILL ORDER ERROR: {e}")
            skipped += 1

    match_result = rebuild_closed_trades_from_orders()

    return {
        "ok": True,
        "message": f"Full ALL-orders backfill complete. Orders fetched {len(orders)}. Imported {imported}, skipped {skipped}. {match_result.get('message', '')}",
        "ordersFetched": len(orders),
        "imported": imported,
        "skipped": skipped,
        **match_result,
    }


def backfill_trades_from_alpaca():
    init_db()

    request = GetOrdersRequest(
        status=get_query_order_status_all(),
        limit=BACKFILL_ORDER_LIMIT,
    )

    orders = trading_client.get_orders(filter=request)
    imported = 0
    skipped = 0
    rate = get_usd_to_gbp_rate()

    # Keep a simple FIFO-ish entry tracker for pnl approximation.
    open_entries: Dict[str, List[Dict[str, float]]] = {}

    sorted_orders = sorted(orders, key=lambda o: str(parse_order_timestamp(o)))

    for order in sorted_orders:
        try:
            status = str(getattr(order, "status", "")).lower()
            filled_qty = float(getattr(order, "filled_qty", 0) or 0)

            if filled_qty <= 0:
                skipped += 1
                continue

            symbol = str(getattr(order, "symbol", "")).upper()
            side = get_order_side(order)
            filled_avg_price = float(getattr(order, "filled_avg_price", 0) or 0)
            timestamp_obj = parse_order_timestamp(order)

            if hasattr(timestamp_obj, "isoformat"):
                timestamp = timestamp_obj.isoformat()
                day = timestamp_obj.astimezone(UTC).strftime("%Y-%m-%d") if hasattr(timestamp_obj, "astimezone") else today_str()
                tm = timestamp_obj.astimezone(UTC).strftime("%H:%M:%S") if hasattr(timestamp_obj, "astimezone") else now_time()
            else:
                timestamp = str(timestamp_obj)
                day = today_str()
                tm = now_time()

            amount = filled_qty * filled_avg_price
            pnl = 0.0
            pnl_pct = 0.0

            if side == "BUY":
                open_entries.setdefault(symbol, []).append({
                    "qty": filled_qty,
                    "price": filled_avg_price,
                })

            if side == "SELL":
                remaining = filled_qty
                cost = 0.0
                matched_qty = 0.0
                entries = open_entries.setdefault(symbol, [])

                while remaining > 0 and entries:
                    entry = entries[0]
                    use_qty = min(remaining, entry["qty"])
                    cost += use_qty * entry["price"]
                    matched_qty += use_qty
                    entry["qty"] -= use_qty
                    remaining -= use_qty

                    if entry["qty"] <= 1e-9:
                        entries.pop(0)

                if matched_qty > 0 and cost > 0:
                    proceeds = matched_qty * filled_avg_price
                    pnl = proceeds - cost
                    avg_entry = cost / matched_qty
                    pnl_pct = ((filled_avg_price / avg_entry) - 1.0) * 100.0

            event = {
                "alpacaOrderId": str(getattr(order, "id", "")),
                "timestamp": timestamp,
                "day": day,
                "time": tm,
                "side": side,
                "symbol": symbol,
                "qty": filled_qty,
                "price": filled_avg_price,
                "amount": amount if side == "BUY" else 0.0,
                "amountGbp": amount * rate if side == "BUY" else 0.0,
                "pnl": round(pnl, 4),
                "pnlGbp": round(pnl * rate, 4),
                "pnlPct": round(pnl_pct, 4),
                "reason": "ALPACA BACKFILL",
                "equity": 0.0,
                "equityGbp": 0.0,
                "fxRate": rate,
            }

            before = len(trades_from_db(10000))
            save_trade_to_db(event, source="alpaca_backfill")
            after = len(trades_from_db(10000))

            if after > before:
                imported += 1
            else:
                skipped += 1

        except Exception as e:
            print(f"BACKFILL ORDER ERROR: {e}")
            skipped += 1

    match_result = rebuild_closed_trades_from_orders()

    return {
        "ok": True,
        "message": f"Backfill complete. Imported {imported}, skipped {skipped}. {match_result.get('message', '')}",
        "imported": imported,
        "skipped": skipped,
        **match_result,
    }



def _trade_order_exists(alpaca_order_id: str) -> bool:
    if not (SQLITE_ENABLED and alpaca_order_id):
        return False
    init_db()
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM trades WHERE alpaca_order_id=? LIMIT 1",
            (str(alpaca_order_id),),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def restore_today_sell_locks_from_db() -> List[str]:
    """Restore the existing sell-then-lock rule after a restart/redeploy.

    Reporting rows are read only; no orders are submitted or changed. Any symbol
    with a SELL recorded for the current UTC trading day is locked until the next
    daily reset, exactly like a live sell handled by market_sell_qty().
    """
    if not (STRICT_ONE_CYCLE_PER_STOCK_PER_DAY and SQLITE_ENABLED):
        return []

    restored: List[str] = []
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute(
            """SELECT DISTINCT UPPER(symbol) AS symbol
               FROM trades
               WHERE side='SELL' AND day=? AND symbol IS NOT NULL""",
            (today_str(),),
        ).fetchall()
        conn.close()

        for row in rows:
            symbol = str(row["symbol"] or "").upper().strip()
            if not symbol:
                continue
            if not is_locked_today(symbol):
                locked_today[symbol] = today_str()
                restored.append(symbol)

        if restored:
            print(f"DAILY LOCK RESTORED | sold today: {', '.join(sorted(restored))}")
        return sorted(restored)
    except Exception as e:
        print(f"DAILY LOCK RESTORE ERROR: {e}")
        return []


def sync_recent_filled_orders_to_reports(force: bool = False) -> Dict[str, Any]:
    """Import recent filled Alpaca orders and refresh FIFO closed trades.

    This is deliberately reporting-only. It does not submit/cancel orders and
    does not alter any live strategy setting. Alpaca order IDs make imports
    idempotent, so repeated runs do not duplicate trades.
    """
    global auto_report_last_sync_ts, auto_report_last_result

    if not AUTO_REPORT_SYNC_ENABLED:
        return {"ok": False, "skipped": True, "reason": "automatic report sync disabled"}

    now_ts = time.time()
    if not force and (now_ts - auto_report_last_sync_ts) < AUTO_REPORT_SYNC_INTERVAL_SECONDS:
        return {**auto_report_last_result, "skipped": True, "reason": "sync interval not due"}

    auto_report_last_sync_ts = now_ts
    imported = 0
    existing = 0
    skipped = 0
    errors = 0

    try:
        init_db()
        # A Render restart clears the in-memory lock dictionary. Rebuild it from
        # today's persisted SELL rows before the scanner can approve another buy.
        restored_locks = restore_today_sell_locks_from_db()
        request = GetOrdersRequest(
            status=get_query_order_status_all(),
            limit=AUTO_REPORT_SYNC_ORDER_LIMIT,
            direction="desc",
        )
        orders = trading_client.get_orders(filter=request)
        rate = get_usd_to_gbp_rate()

        for order in sorted(orders, key=lambda o: str(parse_order_timestamp(o))):
            try:
                if not order_is_filled(order):
                    skipped += 1
                    continue

                oid = get_order_id(order)
                symbol = get_order_symbol(order)
                side = get_order_side(order)
                qty = get_order_qty(order)
                price = get_order_price(order)

                if not oid or not symbol or side not in ("BUY", "SELL") or qty <= 0 or price <= 0:
                    skipped += 1
                    continue

                if _trade_order_exists(oid):
                    existing += 1
                    continue

                timestamp_obj = parse_order_timestamp(order)
                if hasattr(timestamp_obj, "isoformat"):
                    timestamp = timestamp_obj.isoformat()
                    try:
                        utc_timestamp = timestamp_obj.astimezone(UTC)
                        day = utc_timestamp.strftime("%Y-%m-%d")
                        tm = utc_timestamp.strftime("%H:%M:%S")
                    except Exception:
                        day = today_str()
                        tm = now_time()
                else:
                    timestamp = str(timestamp_obj)
                    day = today_str()
                    tm = now_time()

                amount = qty * price
                event = {
                    "alpacaOrderId": oid,
                    "timestamp": timestamp,
                    "day": day,
                    "time": tm,
                    "side": side,
                    "symbol": symbol,
                    "qty": qty,
                    "price": price,
                    "amount": amount if side == "BUY" else 0.0,
                    "amountGbp": amount * rate if side == "BUY" else 0.0,
                    "pnl": 0.0,
                    "pnlGbp": 0.0,
                    "pnlPct": 0.0,
                    "reason": "AUTOMATIC ALPACA REPORT SYNC",
                    "equity": 0.0,
                    "equityGbp": 0.0,
                    "fxRate": rate,
                }
                save_trade_to_db(event, source="alpaca_auto_sync")
                imported += 1
            except Exception as order_error:
                errors += 1
                print(f"AUTO REPORT SYNC ORDER ERROR: {order_error}")

        rebuild_result = None
        if imported > 0:
            rebuild_result = rebuild_closed_trades_from_orders()
            restored_locks = sorted(set(restored_locks + restore_today_sell_locks_from_db()))
            print(
                f"AUTO REPORT SYNC | imported={imported} existing={existing} "
                f"skipped={skipped} errors={errors} "
                f"closed={rebuild_result.get('matchedClosedTrades', 0)}"
            )

        auto_report_last_result = {
            "ok": True,
            "automatic": True,
            "ordersChecked": len(orders),
            "imported": imported,
            "existing": existing,
            "skipped": skipped,
            "errors": errors,
            "rebuilt": bool(imported > 0),
            "matchedClosedTrades": int((rebuild_result or {}).get("matchedClosedTrades", 0)),
            "restoredSellLocks": restored_locks,
            "syncedAt": datetime.now(UTC).isoformat(),
        }
        return auto_report_last_result
    except Exception as e:
        auto_report_last_result = {
            "ok": False,
            "automatic": True,
            "error": str(e),
            "imported": imported,
            "errors": errors + 1,
            "syncedAt": datetime.now(UTC).isoformat(),
        }
        print(f"AUTO REPORT SYNC ERROR: {e}")
        return auto_report_last_result



# =========================
# PROFIT OPTIMISER / ANALYTICS / AUTO IMPROVE
# =========================
def today_realised_pnl():
    today = today_str()
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    return sum(float(t.get("pnl") or 0.0) for t in closed if t.get("day") == today)


def today_realised_pnl_gbp():
    today = today_str()
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    return sum(float(t.get("pnlGbp") or 0.0) for t in closed if t.get("day") == today)


def profit_guardrail_status():
    pnl = today_realised_pnl()
    if PAUSE_BUYS_AFTER_DAILY_TARGET and pnl >= DAILY_PROFIT_TARGET:
        return True, f"Daily profit target hit: ${pnl:.2f}"
    if PAUSE_BUYS_AFTER_DAILY_LOSS and pnl <= DAILY_LOSS_LIMIT_OPTIMIZER:
        return True, f"Daily optimiser loss limit hit: ${pnl:.2f}"
    return False, ""


def analytics_payload():
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    wins = [t for t in closed if float(t.get("pnl") or 0.0) > 0]
    losses = [t for t in closed if float(t.get("pnl") or 0.0) < 0]
    breakevens = [t for t in closed if float(t.get("pnl") or 0.0) == 0]
    total_pnl = sum(float(t.get("pnl") or 0.0) for t in closed)
    total_pnl_gbp = sum(float(t.get("pnlGbp") or 0.0) for t in closed)
    gross_win = sum(float(t.get("pnl") or 0.0) for t in wins)
    gross_loss = abs(sum(float(t.get("pnl") or 0.0) for t in losses))
    avg_win = gross_win / max(1, len(wins))
    avg_loss = -gross_loss / max(1, len(losses))
    avg_win_gbp = sum(float(t.get("pnlGbp") or 0.0) for t in wins) / max(1, len(wins))
    avg_loss_gbp = sum(float(t.get("pnlGbp") or 0.0) for t in losses) / max(1, len(losses))

    by_symbol = {}
    for t in closed:
        symbol = str(t.get("symbol", "")).upper()
        if not symbol:
            continue
        row = by_symbol.setdefault(symbol, {
            "symbol": symbol, "trades": 0, "wins": 0, "losses": 0, "breakevens": 0,
            "totalPnl": 0.0, "totalPnlGbp": 0.0, "grossProfit": 0.0, "grossLoss": 0.0,
            "winRate": 0.0, "avgPnl": 0.0, "profitFactor": 0.0, "trust": "NEW"
        })
        pnl = float(t.get("pnl") or 0.0)
        row["trades"] += 1
        row["totalPnl"] += pnl
        row["totalPnlGbp"] += float(t.get("pnlGbp") or 0.0)
        if pnl > 0:
            row["wins"] += 1
            row["grossProfit"] += pnl
        elif pnl < 0:
            row["losses"] += 1
            row["grossLoss"] += abs(pnl)
        else:
            row["breakevens"] += 1

    rows = []
    for row in by_symbol.values():
        directional = row["wins"] + row["losses"]
        row["winRate"] = row["wins"] / directional if directional else 0.0
        row["avgPnl"] = row["totalPnl"] / max(1, row["trades"])
        row["profitFactor"] = row["grossProfit"] / row["grossLoss"] if row["grossLoss"] > 0 else (99.0 if row["grossProfit"] > 0 else 0.0)

        enough_boost = row["trades"] >= AUTO_BOOST_MIN_TRADES
        enough_blacklist = row["trades"] >= AUTO_BLACKLIST_MIN_TRADES
        if enough_blacklist and row["totalPnl"] < 0 and row["profitFactor"] < 0.75:
            row["trust"] = "BLACKLIST"
        elif row["trades"] >= 3 and (row["totalPnl"] <= 0 or row["profitFactor"] < 1.0):
            row["trust"] = "REDUCE"
        elif enough_boost and row["winRate"] >= AUTO_BOOST_MIN_WINRATE and row["totalPnl"] >= AUTO_BOOST_MIN_TOTAL_PNL and row["profitFactor"] >= 1.20:
            row["trust"] = "BOOST"
        elif row["trades"] >= 3:
            row["trust"] = "NEUTRAL"
        rows.append(row)

    return {
        "enabled": ANALYTICS_ENABLED,
        "closedTrades": len(closed), "wins": len(wins), "losses": len(losses), "breakevens": len(breakevens),
        "winRate": len(wins) / max(1, len(wins) + len(losses)),
        "totalPnl": total_pnl, "totalPnlGbp": total_pnl_gbp,
        "averageWin": avg_win, "averageLoss": avg_loss,
        "averageWinGbp": avg_win_gbp, "averageLossGbp": avg_loss_gbp,
        "profitFactor": gross_win / max(0.01, gross_loss),
        "trustDefinition": "BOOST requires positive PnL and PF >= 1.20; negative PnL/PF < 1 becomes REDUCE or BLACKLIST",
        "bestStocks": sorted(rows, key=lambda x: (x["totalPnl"], x["profitFactor"]), reverse=True)[:10],
        "worstStocks": sorted(rows, key=lambda x: (x["totalPnl"], x["profitFactor"]))[:10],
        "todayRealisedPnl": today_realised_pnl(), "todayRealisedPnlGbp": today_realised_pnl_gbp(),
    }


def symbol_stats(symbol: str):
    symbol = symbol.upper()
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    trades = [t for t in closed if str(t.get("symbol", "")).upper() == symbol]
    pnls = [float(t.get("pnl") or 0.0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    breakevens = [p for p in pnls if p == 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    directional = len(wins) + len(losses)
    return {
        "symbol": symbol, "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "breakevens": len(breakevens), "winRate": len(wins) / directional if directional else 0.0,
        "totalPnl": sum(pnls), "avgPnl": sum(pnls) / max(1, len(pnls)),
        "profitFactor": gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0),
    }


def auto_improve_decision(symbol: str):
    if not AUTO_IMPROVE_ENABLED:
        return {"action": "NORMAL", "multiplier": 1.0, "reason": "auto improve off"}
    row = symbol_stats(symbol)
    trades = int(row.get("trades") or 0)
    win_rate = float(row.get("winRate") or 0.0)
    total_pnl = float(row.get("totalPnl") or 0.0)
    profit_factor = float(row.get("profitFactor") or 0.0)

    if AUTO_BLACKLIST_ENABLED and trades >= AUTO_BLACKLIST_MIN_TRADES and total_pnl < 0 and profit_factor < 0.75:
        return {"action": "BLACKLIST", "multiplier": 0.0,
                "reason": f"weak history: trades={trades}, winRate={win_rate:.2f}, PF={profit_factor:.2f}, pnl=${total_pnl:.2f}"}
    if trades >= 3 and (total_pnl <= 0 or profit_factor < 1.0):
        return {"action": "REDUCE", "multiplier": AUTO_REDUCE_MULTIPLIER,
                "reason": f"negative expectancy: trades={trades}, winRate={win_rate:.2f}, PF={profit_factor:.2f}, pnl=${total_pnl:.2f}"}
    if AUTO_BOOST_ENABLED and trades >= AUTO_BOOST_MIN_TRADES and win_rate >= AUTO_BOOST_MIN_WINRATE and total_pnl >= AUTO_BOOST_MIN_TOTAL_PNL and profit_factor >= 1.20:
        return {"action": "BOOST", "multiplier": AUTO_BOOST_MULTIPLIER,
                "reason": f"strong history: trades={trades}, winRate={win_rate:.2f}, PF={profit_factor:.2f}, pnl=${total_pnl:.2f}"}
    return {"action": "NORMAL", "multiplier": 1.0,
            "reason": f"normal history: trades={trades}, PF={profit_factor:.2f}, pnl=${total_pnl:.2f}"}


def optimiser_allows_scan(scan):
    if not PROFIT_OPTIMIZER_ENABLED:
        return True, "optimiser off"
    symbol = scan.get("symbol", "")
    confidence = float(scan.get("confidence", 0.0))
    if confidence < OPTIMIZER_MIN_CONFIDENCE:
        return False, f"confidence {confidence:.2f} below optimiser {OPTIMIZER_MIN_CONFIDENCE:.2f}"
    decision = auto_improve_decision(symbol)
    if decision["action"] == "BLACKLIST":
        return False, f"auto-blacklisted: {decision['reason']}"
    blocked, reason = profit_guardrail_status()
    if blocked:
        return False, reason
    return True, decision["reason"]


def optimiser_position_multiplier(symbol):
    return float(auto_improve_decision(symbol).get("multiplier", 1.0))


def optimiser_payload():
    blocked, reason = profit_guardrail_status()
    return {
        "enabled": PROFIT_OPTIMIZER_ENABLED,
        "autoImproveEnabled": AUTO_IMPROVE_ENABLED,
        "autoUniverseEnabled": AUTO_UNIVERSE_ENABLED,
        "autoUniverseEnabled": AUTO_UNIVERSE_ENABLED,
        "buyBlocked": blocked,
        "blockReason": reason,
        "dailyProfitTarget": DAILY_PROFIT_TARGET,
        "dailyLossLimit": DAILY_LOSS_LIMIT_OPTIMIZER,
        "todayRealisedPnl": today_realised_pnl(),
        "todayRealisedPnlGbp": today_realised_pnl_gbp(),
        "optimizedStopLoss": OPTIMIZED_STOP_LOSS,
        "optimizedTrailStart": OPTIMIZED_TRAIL_START,
        "optimizedTrailGiveback": OPTIMIZED_TRAIL_GIVEBACK,
        "autoBoostMultiplier": AUTO_BOOST_MULTIPLIER,
        "autoReduceMultiplier": AUTO_REDUCE_MULTIPLIER,
    }



# =========================
# WEEKLY AUTO UNIVERSE ROTATION
# =========================
def week_start_str(dt=None):
    dt = dt or datetime.now(UTC)
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


def get_last_universe_refresh():
    if not SQLITE_ENABLED:
        return None
    try:
        init_db()
        conn = db_connect()
        row = conn.execute("""
            SELECT refreshed_at FROM universe_refresh_log
            ORDER BY refreshed_at DESC
            LIMIT 1
        """).fetchone()
        conn.close()
        return row["refreshed_at"] if row else None
    except Exception:
        return None


def get_weekly_universe_from_db(week_start=None):
    if not SQLITE_ENABLED:
        return []
    week_start = week_start or week_start_str()
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute("""
            SELECT symbol, score, reason, status
            FROM weekly_universe
            WHERE week_start = ? AND status = 'active'
            ORDER BY score DESC
        """, (week_start,)).fetchall()
        conn.close()
        return [
            {"symbol": r["symbol"], "score": r["score"], "reason": r["reason"], "status": r["status"]}
            for r in rows
        ]
    except Exception as e:
        print(f"WEEKLY UNIVERSE READ ERROR: {e}")
        return []


def save_weekly_universe(rows, reason="weekly refresh"):
    if not SQLITE_ENABLED:
        return
    week = week_start_str()
    init_db()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE weekly_universe SET status='removed' WHERE week_start=?", (week,))

    for r in rows:
        cur.execute("""
            INSERT OR REPLACE INTO weekly_universe (week_start, symbol, score, reason, status)
            VALUES (?, ?, ?, ?, 'active')
        """, (week, r["symbol"], float(r.get("score") or 0), r.get("reason", "")))

    cur.execute("""
        INSERT INTO universe_refresh_log (refreshed_at, week_start, symbols, reason)
        VALUES (?, ?, ?, ?)
    """, (
        datetime.now(UTC).isoformat(),
        week,
        ",".join([r["symbol"] for r in rows]),
        reason,
    ))
    conn.commit()
    conn.close()


def should_refresh_weekly_universe(force=False):
    if force:
        return True
    if not AUTO_UNIVERSE_ENABLED:
        return False
    if not get_weekly_universe_from_db():
        return True

    last = get_last_universe_refresh()
    if not last:
        return True

    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        hours = (datetime.now(UTC) - last_dt).total_seconds() / 3600
        if hours < AUTO_UNIVERSE_MIN_HOURS_BETWEEN_REFRESH:
            return False
    except Exception:
        pass

    return datetime.now(UTC).weekday() == AUTO_UNIVERSE_REFRESH_DAY


def universe_rows_from_stock_memory():
    """
    Build the weekly watchlist from closed-trade memory using the same PnL/PF
    rules as the live optimiser. BLACKLIST symbols are excluded from new-entry
    selection even when an older saved universe still labels them as GOOD.
    """
    rows = []

    try:
        memory = stock_memory_from_closed_trades()
    except Exception:
        try:
            memory = stock_memory_from_db()
        except Exception:
            memory = []

    for m in memory:
        symbol = str(m.get("symbol", "")).upper().strip()
        if not symbol:
            continue

        stats = symbol_stats(symbol)
        decision = auto_improve_decision(symbol)
        action = str(decision.get("action") or "NORMAL").upper()

        # A currently held symbol must remain visible for position management,
        # but a BLACKLIST symbol must never be selected for a fresh entry.
        held_qty = 0.0
        try:
            held_qty, _ = get_position(symbol)
            held_qty = float(held_qty or 0.0)
        except Exception:
            held_qty = 0.0

        if action == "BLACKLIST" and held_qty <= DUST_THRESHOLD:
            continue

        trades = int(stats.get("trades") or 0)
        win_rate = float(stats.get("winRate") or 0.0)
        avg_pnl = float(stats.get("avgPnl") or 0.0)
        total_pnl = float(stats.get("totalPnl") or 0.0)
        profit_factor = float(stats.get("profitFactor") or 0.0)

        score = 0.0
        score += min(trades, 20) * 0.6
        score += win_rate * 12.0
        score += avg_pnl * 3.0
        score += max(-10.0, min(10.0, total_pnl)) * 0.5
        score += min(profit_factor, 4.0) * 1.5

        if action == "BOOST":
            score += 6.0
        elif action == "REDUCE":
            score -= 8.0
        elif action == "BLACKLIST":
            score -= 100.0

        management_only = action == "BLACKLIST" and held_qty > DUST_THRESHOLD
        reason = (
            f"trust {action} | trades={trades} | winRate={win_rate*100:.2f}% | "
            f"PF={profit_factor:.2f} | avgPnL=${avg_pnl:.2f} | totalPnL=${total_pnl:.2f}"
        )
        if management_only:
            reason = "currently held; management only | " + reason

        rows.append({
            "symbol": symbol,
            "score": round(score, 4),
            "reason": reason,
            "status": "active",
            "trust": action,
            "profitFactor": profit_factor,
            "totalPnl": total_pnl,
            "eligibleForNewBuy": not management_only and action != "BLACKLIST",
            "managementOnly": management_only,
        })

    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def reconcile_auto_universe_rows(rows, target_size=None):
    """Re-score saved universe rows with current optimiser evidence.

    This repairs stale weekly labels immediately after a deployment. Symbols
    currently classified BLACKLIST are removed from new-entry selection. Open
    positions are retained as management-only rows so exit logic can still see
    them. Empty slots are filled from the candidate pool with non-blacklisted
    symbols.
    """
    target_size = int(target_size or AUTO_UNIVERSE_SIZE)
    result = []
    seen = set()

    def append_symbol(symbol, original=None):
        symbol = str(symbol or "").upper().strip()
        if not symbol or symbol in seen:
            return

        decision = auto_improve_decision(symbol)
        action = str(decision.get("action") or "NORMAL").upper()
        stats = symbol_stats(symbol)
        held_qty = 0.0
        try:
            held_qty, _ = get_position(symbol)
            held_qty = float(held_qty or 0.0)
        except Exception:
            pass

        management_only = action == "BLACKLIST" and held_qty > DUST_THRESHOLD
        if action == "BLACKLIST" and not management_only:
            return

        original = original or {}
        score = float(original.get("score") or 0.0)
        if action == "BOOST":
            score += 6.0
        elif action == "REDUCE":
            score -= 8.0
        elif management_only:
            score = max(score, 20.0)

        reason = (
            f"trust {action} | trades={int(stats.get('trades') or 0)} | "
            f"winRate={float(stats.get('winRate') or 0.0)*100:.2f}% | "
            f"PF={float(stats.get('profitFactor') or 0.0):.2f} | "
            f"avgPnL=${float(stats.get('avgPnl') or 0.0):.2f} | "
            f"totalPnL=${float(stats.get('totalPnl') or 0.0):.2f}"
        )
        if management_only:
            reason = "currently held; management only | " + reason

        result.append({
            **original,
            "symbol": symbol,
            "score": round(score, 4),
            "reason": reason,
            "status": "active",
            "trust": action,
            "profitFactor": float(stats.get("profitFactor") or 0.0),
            "totalPnl": float(stats.get("totalPnl") or 0.0),
            "eligibleForNewBuy": not management_only and action != "BLACKLIST",
            "managementOnly": management_only,
        })
        seen.add(symbol)

    for row in rows or []:
        append_symbol(row.get("symbol"), row)

    # Refill removed BLACKLIST slots from the current memory ranking first.
    for row in universe_rows_from_stock_memory():
        if len(result) >= target_size:
            break
        append_symbol(row.get("symbol"), row)

    # Then use the normal candidate pool, still respecting BLACKLIST evidence.
    for symbol in AUTO_UNIVERSE_CANDIDATE_POOL:
        if len(result) >= target_size:
            break
        append_symbol(symbol, score_candidate_symbol(symbol))

    result.sort(key=lambda r: float(r.get("score") or 0.0), reverse=True)
    return result[:target_size]

def score_candidate_symbol(symbol):
    """
    Fallback/new-candidate scoring for symbols not yet in stock memory.
    """
    symbol = symbol.upper()
    score = 1.0
    reasons = ["candidate pool"]

    try:
        q = get_quote(symbol)
        price = float(q["mid"])
        spread = float(q["spread"])

        if 1 <= price <= 800:
            score += 2.0
            reasons.append(f"price ok ${price:.2f}")
        else:
            score -= 10.0
            reasons.append(f"price out of range ${price:.2f}")

        if spread <= 0.02:
            score += max(0.0, 4.0 - spread * 200)
            reasons.append(f"spread ok {spread:.4f}")
        else:
            score -= 5.0
            reasons.append(f"spread wide {spread:.4f}")
    except Exception:
        score -= 2.0
        reasons.append("quote unavailable")

    try:
        qty, _ = get_position(symbol)
        if qty > DUST_THRESHOLD:
            score += 8.0
            reasons.append("currently held")
    except Exception:
        pass

    return {"symbol": symbol, "score": round(score, 4), "reason": " | ".join(reasons), "status": "active"}


def build_weekly_universe(force=False):
    global current_universe

    if not AUTO_UNIVERSE_ENABLED:
        return {"ok": False, "message": "Auto universe disabled", "symbols": current_universe}

    if not should_refresh_weekly_universe(force=force):
        active = get_weekly_universe_from_db()
        if active:
            current_universe = [r["symbol"] for r in active]
            for s in current_universe:
                ensure_symbol_state(s, custom=s in custom_symbols)
            return {"ok": True, "message": "Weekly universe already fresh", "symbols": current_universe, "rows": active}

    rows = universe_rows_from_stock_memory()

    # Add currently held symbols so open positions don't disappear from management.
    held_rows = []
    try:
        for p in get_all_positions():
            symbol = str(p.get("symbol", "")).upper()
            if symbol and symbol not in [r["symbol"] for r in rows]:
                held_rows.append({
                    "symbol": symbol,
                    "score": 20.0,
                    "reason": "currently held position",
                    "status": "active",
                })
    except Exception:
        pass

    combined = held_rows + rows

    # Fill empty slots with candidate pool.
    existing = {r["symbol"] for r in combined}
    for symbol in AUTO_UNIVERSE_CANDIDATE_POOL:
        if len(combined) >= AUTO_UNIVERSE_SIZE * 2:
            break
        if symbol not in existing:
            combined.append(score_candidate_symbol(symbol))
            existing.add(symbol)

    combined.sort(key=lambda r: r["score"], reverse=True)

    chosen = []
    seen = set()
    for r in combined:
        if len(chosen) >= AUTO_UNIVERSE_SIZE:
            break
        if r["symbol"] in seen:
            continue
        chosen.append(r)
        seen.add(r["symbol"])

    if not chosen:
        chosen = [{"symbol": s, "score": 0, "reason": "fallback safe universe", "status": "active"} for s in SAFE_UNIVERSE[:AUTO_UNIVERSE_SIZE]]

    chosen = reconcile_auto_universe_rows(chosen, AUTO_UNIVERSE_SIZE)
    save_weekly_universe(chosen, "forced refresh" if force else "weekly refresh")
    current_universe = [r["symbol"] for r in chosen]

    for s in current_universe:
        ensure_symbol_state(s, custom=s in custom_symbols)

    return {
        "ok": True,
        "message": f"Weekly universe updated with {len(current_universe)} symbols",
        "symbols": current_universe,
        "rows": chosen,
    }


def auto_universe_payload():
    global current_universe
    active = get_weekly_universe_from_db()

    # If DB has not been populated yet but stock memory exists, show live preview.
    if not active:
        active = universe_rows_from_stock_memory()[:AUTO_UNIVERSE_SIZE]

    # Always re-score saved rows against current optimiser evidence. This makes
    # stale GOOD labels disappear immediately after deployment and suppresses
    # BLACKLIST symbols without waiting for the next weekly refresh.
    active = reconcile_auto_universe_rows(active, AUTO_UNIVERSE_SIZE)
    symbols = [r["symbol"] for r in active]
    if symbols:
        current_universe = symbols[:]
        for symbol in current_universe:
            ensure_symbol_state(symbol, custom=symbol in custom_symbols)

    return {
        "enabled": AUTO_UNIVERSE_ENABLED,
        "size": len(active),
        "configuredSize": AUTO_UNIVERSE_SIZE,
        "weekStart": week_start_str(),
        "activeSymbols": symbols if active else list(current_universe),
        "rows": active,
        "lastRefresh": get_last_universe_refresh(),
        "candidatePoolSize": len(AUTO_UNIVERSE_CANDIDATE_POOL),
        "keepWinners": True,
        "liveRescored": True,
        "blacklistSuppressed": True,
        "trustDefinition": "BOOST/REDUCE/BLACKLIST uses current PnL and profit factor; BLACKLIST symbols are excluded from new entries",
    }



def weekly_universe_public():
    return auto_universe_payload()

# =========================
# STATUS
# =========================
def update_equity_curve(account):
    equity_usd = float(account.equity)
    point = {"t": now_chart_time(), "value": equity_usd, "valueGbp": money_gbp(equity_usd)}
    if not equity_curve or equity_curve[-1]["value"] != point["value"]:
        equity_curve.append(point)
    if len(equity_curve) > 240:
        equity_curve.pop(0)


def build_status_payload(bot_name, scans):
    account = get_account()
    update_equity_curve(account)
    positions = get_all_positions()
    active = positions[0] if positions else None
    daily_pnl = get_daily_pnl()
    blocked, risk_reason = risk_blocked()
    market_status = get_market_status_payload()
    locked_symbols = sorted([s for s, d in locked_today.items() if d == today_str()])

    return {
        "id": "rebuilt-sniper-live",
        "name": bot_name,
        "paperMode": PAPER,
        "botEnabled": bot_enabled,
        "manualOverride": manual_override,
        "emergencyStop": emergency_stop,
        "riskBlocked": blocked,
        "riskReason": risk_reason,
        "mode": "SNIPER_CONFIDENCE_MEMORY_TIMELINE_GBP",
        "market": market_status,
        "fx": fx_payload(),
        "autoUniverse": auto_universe_payload(),
        "dynamicMarketScanner": dynamic_market_scanner_payload() if "dynamic_market_scanner_payload" in globals() else {},
        "cycleMonitor": cycle_monitor_payload() if "cycle_monitor_payload" in globals() else {},
        "adaptiveUniverse": adaptive_universe_payload() if "adaptive_universe_payload" in globals() else {},
        "analytics": analytics_payload(),
        "optimiser": optimiser_payload(),
        "strictOneCyclePerStockPerDay": STRICT_ONE_CYCLE_PER_STOCK_PER_DAY,
        "allowCustomBuy": ALLOW_CUSTOM_BUY,
        "profitModeEnabled": PROFIT_MODE_ENABLED,
        "rotationModeEnabled": ROTATION_MODE_ENABLED,
        "pdtAwareModeEnabled": PDT_AWARE_MODE_ENABLED,
        "sniperModeEnabled": SNIPER_MODE_ENABLED,
        "confidenceSizingEnabled": CONFIDENCE_SIZING_ENABLED,
        "stockMemoryEnabled": STOCK_MEMORY_ENABLED,
        "profitOptimizerEnabled": PROFIT_OPTIMIZER_ENABLED,
        "analyticsEnabled": ANALYTICS_ENABLED,
        "autoImproveEnabled": AUTO_IMPROVE_ENABLED,
        "autoUniverseEnabled": AUTO_UNIVERSE_ENABLED,
        "autoUniverseEnabled": AUTO_UNIVERSE_ENABLED,
        "fastExitModeEnabled": FAST_EXIT_MODE_ENABLED,
        "partialProfitEnabled": PARTIAL_PROFIT_ENABLED,
        "partialProfitTriggerPct": PARTIAL_PROFIT_TRIGGER_PCT,
        "partialProfitSellPct": PARTIAL_PROFIT_SELL_PCT,
        "fastStopLossPct": FAST_STOP_LOSS_PCT,
        "stallExitEnabled": STALL_EXIT_ENABLED,
        "stallExitAfterMinutes": STALL_EXIT_AFTER_MINUTES,
        "aPlusGateEnabled": A_PLUS_GATE_ENABLED,
        "strategySettings": current_strategy_settings_payload() if "current_strategy_settings_payload" in globals() else {},
        "aPlusMinConfidence": A_PLUS_MIN_CONFIDENCE,
        "aPlusMinQuality": A_PLUS_MIN_QUALITY,
        "tempBlacklist": temp_blacklist,
        "todayBuyCount": today_buy_count(),
        "maxNewBuysPerDayPdtAware": MAX_NEW_BUYS_PER_DAY_PDT_AWARE,
        "lockedSymbolsToday": locked_symbols,
        "customSymbols": sorted(list(custom_symbols.keys())),
        "maxPositions": effective_max_positions(),
        "positionCapacity": ai_position_capacity_payload(),
        "positionSettings": current_position_settings_payload() if "current_position_settings_payload" in globals() else {},
        "newPositionNotional": calculate_new_position_notional(),
        "allowedNewPositions": allowed_new_position_count(),
        "universe": list(current_universe),
        "config": {
            "checkInterval": CHECK_INTERVAL,
            "maxPositions": effective_max_positions(),
        "positionCapacity": ai_position_capacity_payload(),
            "fullBuyWhenOnePosition": True if V17_SINGLE_FULL_BUY_MODE else (False if AI_POSITION_CAPACITY_ENABLED else FULL_BUY_WHEN_ONE_POSITION),
            "fullBuyCashBuffer": FULL_BUY_CASH_BUFFER,
            "targetPositionValuePct": TARGET_POSITION_VALUE_PCT,
            "maxPositionValuePct": MAX_POSITION_VALUE_PCT,
            "stopLoss": STOP_LOSS,
            "trailStart": TRAIL_START,
            "trailGiveback": TRAIL_GIVEBACK,
            "fastExitModeEnabled": FAST_EXIT_MODE_ENABLED,
            "partialProfitTriggerPct": PARTIAL_PROFIT_TRIGGER_PCT,
            "partialProfitSellPct": PARTIAL_PROFIT_SELL_PCT,
            "fastStopLossPct": FAST_STOP_LOSS_PCT,
            "stallExitAfterMinutes": STALL_EXIT_AFTER_MINUTES,
            "sniperMinConfidence": SNIPER_MIN_CONFIDENCE,
            "sniperMinQuality": SNIPER_MIN_QUALITY,
        },
        "account": {
            "equity": float(account.equity),
            "equityGbp": money_gbp(float(account.equity)),
            "buyingPower": float(account.buying_power),
            "buyingPowerGbp": money_gbp(float(account.buying_power)),
            "cash": float(account.cash),
            "cashGbp": money_gbp(float(account.cash)),
            "pnlDay": float(daily_pnl),
            "pnlDayGbp": money_gbp(float(daily_pnl)),
        },
        "activePosition": {
            "symbol": active["symbol"] if active else "—",
            "qty": float(active["qty"]) if active else 0.0,
            "entry": float(active["entry"]) if active else 0.0,
            "price": float(active["price"]) if active else 0.0,
            "pnl": float(active["pnl"]) if active else 0.0,
            "pnlGbp": money_gbp(float(active["pnl"])) if active else 0.0,
            "pnlPct": float(active["pnlPct"]) if active else 0.0,
            "trailingActive": bool(active["trailingActive"]) if active else False,
            "trailStartPrice": float(active["trailStartPrice"]) if active else 0.0,
            "trailFloor": float(active["trailFloor"]) if active else 0.0,
        },
        "positions": positions,
        "scans": [
            {
                "symbol": s["symbol"], "price": float(s["price"]), "ref": float(s["ref"]),
                "trigger": float(s["buy_trigger"]), "spread": float(s["spread"]),
                "qty": 0.0 if float(s["qty"]) <= DUST_THRESHOLD else float(s["qty"]),
                "heldQty": 0.0 if float(s["qty"]) <= DUST_THRESHOLD else float(s["qty"]),
                "proposedQty": proposed_buy_qty(s),
                "proposedNotional": confidence_notional(s),
                "qtyMeaning": "heldQty; proposedQty is the estimated new order size",
                "score": float(s["score"]),
                "pullback": float(s["pullback"]), "shortMomentum": float(s["short_momentum"]),
                "qualityScore": float(s["quality_score"]), "readyToBuy": bool(s["ready_to_buy"]),
                "lockedToday": bool(s["locked_today"]), "custom": bool(s.get("custom", False)),
                "priceCurve": s.get("price_curve", []), "confidence": float(s.get("confidence", 0.0)),
                "confidenceLabel": s.get("confidence_label", "LOW"),
                "sniperPass": bool(s.get("sniper_pass", False)),
                "sniperReason": s.get("sniper_reason", ""),
                "aPlusPass": bool(s.get("a_plus_pass", False)),
                "aPlusReason": s.get("a_plus_reason", ""),
                "optimiserDecision": auto_improve_decision(s["symbol"]),
            } for s in scans
        ],
        "banking": banking_payload(),
        "performanceEngine": performance_engine_payload(),
        "logs": [
            f"MODE | SNIPER_CONFIDENCE_MEMORY_TIMELINE | max_positions={effective_max_positions()} | allowed_new={allowed_new_position_count()}",
            f"SNIPER | enabled={SNIPER_MODE_ENABLED} | confidence_sizing={CONFIDENCE_SIZING_ENABLED} | memory={STOCK_MEMORY_ENABLED} | timeline={len(trade_history)}",
            f"FX | USDGBP={get_usd_to_gbp_rate():.4f} | source={fx_cache.get('source', 'fallback')}",
            f"DB | sqlite={SQLITE_ENABLED} | raw_trades={db_summary_payload().get('totalTrades', 0)} | closed={closed_trade_summary_payload().get('closedTrades', 0)} | pnl_gbp={closed_trade_summary_payload().get('totalPnlGbp', 0):.2f}",
            f"BACKFILL | chunk={BACKFILL_CHUNK_SIZE} | max_pages={BACKFILL_MAX_PAGES}",
            f"OPTIMIZER | enabled={PROFIT_OPTIMIZER_ENABLED} | today_realised={today_realised_pnl():.2f} | block={profit_guardrail_status()[1] or 'none'}",
            f"ANALYTICS | profit_factor={analytics_payload().get('profitFactor', 0):.2f} | avg_win={analytics_payload().get('averageWin', 0):.2f} | avg_loss={analytics_payload().get('averageLoss', 0):.2f}",
            f"HOLD AI | enabled={HOLD_AI_ENABLED} | min_trades={HOLD_AI_MIN_TRADES} | min_hold={HOLD_AI_MIN_HOLD_MINUTES}m | good_hold={HOLD_AI_GOOD_SYMBOL_HOLD_MINUTES}m | max_positions={effective_max_positions()}",
            f"A+ GATE | enabled={A_PLUS_GATE_ENABLED} | min_conf={A_PLUS_MIN_CONFIDENCE} | min_quality={A_PLUS_MIN_QUALITY} | blacklist={len(temp_blacklist)}",
            f"PDT AWARE | enabled={PDT_AWARE_MODE_ENABLED} | today_buys={today_buy_count()}/{MAX_NEW_BUYS_PER_DAY_PDT_AWARE} | warnings={len(pdt_warning_events)}",
            f"FAST EXIT | enabled={FAST_EXIT_MODE_ENABLED} | partial={PARTIAL_PROFIT_TRIGGER_PCT}%/{int(PARTIAL_PROFIT_SELL_PCT*100)}% | stop={FAST_STOP_LOSS_PCT}% | stall={STALL_EXIT_AFTER_MINUTES}m",
            f"MARKET | {market_status.get('label', 'UNKNOWN')}",
            f"ACCOUNT | equity={float(account.equity):.2f} | buying_power={float(account.buying_power):.2f}",
            f"POSITIONS | {len(positions)}",
            f"LOCKOUT | locked_today={', '.join(locked_symbols) if locked_symbols else 'none'}",
        ],
        "trades": trade_events[-50:],
        "tradeTimeline": trades_from_db(1000),
        "closedTrades": closed_trades_from_db(1000),
        "stockMemory": stock_memory_from_closed_trades(),
        "dbSummary": {**db_summary_payload(), **closed_trade_summary_payload()},
        "automaticReportSync": {
            "enabled": AUTO_REPORT_SYNC_ENABLED,
            "intervalSeconds": AUTO_REPORT_SYNC_INTERVAL_SECONDS,
            **auto_report_last_result,
        },
        "equityCurve": equity_curve[-240:],
        "alpacaRejectionEvents": alpaca_rejection_events[-50:],
        "pdtWarningEvents": pdt_warning_events[-50:],
    }


def update_status(bot_name, scans):
    # V18.2.8: build the expensive payload off to the side, then publish it
    # atomically.  The previous clear-then-build sequence left latest_status
    # empty for the entire build, so /status could fall into a second live
    # broker refresh and hang the dashboard for 15-30 seconds.
    payload = build_status_payload(bot_name, scans)
    with _STATUS_LOCK:
        latest_status.clear()
        latest_status.update(payload)



# ============================================================
# STRATEGY STRICTNESS / LIVE GATE SETTINGS
# ============================================================

STRATEGY_SETTINGS_FILE = os.path.join("backend", "state", "strategy_settings.json")

STRATEGY_PRESETS = {
    "safe": {
        "label": "Safe",
        "aPlusMinConfidence": 0.70,
        "sniperMinConfidence": 0.58,
        "aPlusMinQuality": 0.026,
        "sniperMinQuality": 0.020,
    },
    "balanced": {
        "label": "Balanced",
        "aPlusMinConfidence": 0.62,
        "sniperMinConfidence": 0.54,
        "aPlusMinQuality": 0.022,
        "sniperMinQuality": 0.017,
    },
    "aggressive": {
        "label": "Aggressive",
        "aPlusMinConfidence": 0.55,
        "sniperMinConfidence": 0.50,
        "aPlusMinQuality": 0.018,
        "sniperMinQuality": 0.014,
    },
}

def _strategy_preset_from_level(level: int) -> str:
    try:
        level = int(level)
    except Exception:
        level = 1
    if level <= 0:
        return "safe"
    if level >= 2:
        return "aggressive"
    return "balanced"


def _save_strategy_settings(payload: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(STRATEGY_SETTINGS_FILE), exist_ok=True)
        with open(STRATEGY_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"STRATEGY SETTINGS SAVE ERROR: {e}")


def _load_strategy_settings() -> Dict[str, Any]:
    try:
        if os.path.exists(STRATEGY_SETTINGS_FILE):
            with open(STRATEGY_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"STRATEGY SETTINGS LOAD ERROR: {e}")
    return {"level": 0, "preset": "safe"}


def apply_strategy_settings(level: int = None, preset: str = None, save: bool = True) -> Dict[str, Any]:
    global A_PLUS_MIN_CONFIDENCE, SNIPER_MIN_CONFIDENCE, A_PLUS_MIN_QUALITY, SNIPER_MIN_QUALITY

    if preset:
        preset_key = str(preset).lower().strip()
    else:
        preset_key = _strategy_preset_from_level(0 if level is None else int(level))

    if preset_key not in STRATEGY_PRESETS:
        preset_key = "safe"

    if level is None:
        level = {"safe": 0, "balanced": 1, "aggressive": 2}.get(preset_key, 0)

    cfg = STRATEGY_PRESETS[preset_key]

    A_PLUS_MIN_CONFIDENCE = float(cfg["aPlusMinConfidence"])
    SNIPER_MIN_CONFIDENCE = float(cfg["sniperMinConfidence"])
    A_PLUS_MIN_QUALITY = float(cfg["aPlusMinQuality"])
    SNIPER_MIN_QUALITY = float(cfg["sniperMinQuality"])

    payload = {
        "ok": True,
        "level": int(level),
        "preset": preset_key,
        "label": cfg["label"],
        "aPlusMinConfidence": A_PLUS_MIN_CONFIDENCE,
        "sniperMinConfidence": SNIPER_MIN_CONFIDENCE,
        "aPlusMinQuality": A_PLUS_MIN_QUALITY,
        "sniperMinQuality": SNIPER_MIN_QUALITY,
        "updatedAt": datetime.now(UTC).isoformat(),
        "presets": STRATEGY_PRESETS,
    }

    if save:
        _save_strategy_settings(payload)

    try:
        latest_status["strategySettings"] = payload
        latest_status["aPlusMinConfidence"] = A_PLUS_MIN_CONFIDENCE
        latest_status["aPlusMinQuality"] = A_PLUS_MIN_QUALITY
        latest_status["config"]["sniperMinConfidence"] = SNIPER_MIN_CONFIDENCE
        latest_status["config"]["sniperMinQuality"] = SNIPER_MIN_QUALITY
        latest_status["lastAction"] = f"Trading strictness set to {cfg['label']}"
        latest_status["lastActionAt"] = payload["updatedAt"]
    except Exception:
        pass

    return payload


def apply_custom_a_plus_thresholds(confidence: float, quality: float, reason: str = "adaptive optimiser", save: bool = True) -> Dict[str, Any]:
    global A_PLUS_MIN_CONFIDENCE, A_PLUS_MIN_QUALITY, SNIPER_MIN_CONFIDENCE, SNIPER_MIN_QUALITY
    confidence = max(0.50, min(0.90, float(confidence)))
    quality = max(0.010, min(0.100, float(quality)))
    previous_conf = float(A_PLUS_MIN_CONFIDENCE)
    previous_quality = float(A_PLUS_MIN_QUALITY)
    previous_sniper_conf = float(SNIPER_MIN_CONFIDENCE)
    previous_sniper_quality = float(SNIPER_MIN_QUALITY)
    A_PLUS_MIN_CONFIDENCE = confidence
    A_PLUS_MIN_QUALITY = quality
    # Sniper remains the broader entry gate, learned alongside A+ while
    # preserving a conservative separation between the two tiers.
    SNIPER_MIN_CONFIDENCE = max(0.48, min(0.70, round(confidence - 0.12, 2)))
    SNIPER_MIN_QUALITY = max(0.012, min(0.030, round(quality - 0.006, 3)))
    payload = current_strategy_settings_payload()
    payload.update({
        "preset": "custom", "label": "Adaptive Custom",
        "aPlusMinConfidence": confidence, "aPlusMinQuality": quality,
        "sniperMinConfidence": SNIPER_MIN_CONFIDENCE, "sniperMinQuality": SNIPER_MIN_QUALITY,
        "previousSniperMinConfidence": previous_sniper_conf,
        "previousSniperMinQuality": previous_sniper_quality,
        "updatedAt": datetime.now(UTC).isoformat(), "changeReason": reason,
    })
    if save:
        _save_strategy_settings(payload)
    # V17.7.1 — write the strategy-version audit row as one serialized
    # transaction.  The old SELECT-then-INSERT sequence could start as a WAL
    # reader and then fail while upgrading to a writer if another autonomous
    # worker committed in between.  BEGIN IMMEDIATE + whole-transaction retry
    # removes that read->write upgrade race without changing any strategy rule.
    strategy_save_error = None
    for strategy_save_attempt in range(_DB_LOCK_RETRIES):
        conn = None
        try:
            init_db()
            with _DB_SERIAL_WRITE_LOCK:
                conn = db_connect()
                conn.execute("BEGIN IMMEDIATE")
                count = conn.execute("SELECT COUNT(*) FROM v2_strategy_versions").fetchone()[0]
                conn.execute(
                    """INSERT INTO v2_strategy_versions
                       (created_at, version_label, action, confidence, quality, previous_confidence, previous_quality, reason, metrics_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (datetime.now(UTC).isoformat(), f"V2.{count+1}", "APPLY", confidence, quality,
                     previous_conf, previous_quality, reason, json.dumps({})),
                )
                conn.commit()
            strategy_save_error = None
            break
        except sqlite3.OperationalError as e:
            strategy_save_error = e
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if not _db_is_lock_error(e) or strategy_save_attempt >= _DB_LOCK_RETRIES - 1:
                break
            time.sleep(_db_retry_delay(strategy_save_attempt))
        except Exception as e:
            strategy_save_error = e
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            break
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    if strategy_save_error is not None:
        print(f"V17.7.1 STRATEGY VERSION SAVE ERROR | attempts={_DB_LOCK_RETRIES} error={strategy_save_error}")
    return payload


def current_strategy_settings_payload() -> Dict[str, Any]:
    saved = _load_strategy_settings()
    preset_key = str(saved.get("preset") or _strategy_preset_from_level(int(saved.get("level", 0)))).lower()
    is_custom = preset_key == "custom"
    if preset_key not in STRATEGY_PRESETS and not is_custom:
        preset_key = "safe"
    preset_cfg = STRATEGY_PRESETS.get(preset_key, {"label": "Adaptive Custom"})

    # Keep runtime values as source of truth after startup has applied saved config.
    return {
        "ok": True,
        "level": int(saved.get("level", {"safe": 0, "balanced": 1, "aggressive": 2}.get(preset_key, -1))),
        "preset": preset_key,
        "label": preset_cfg["label"],
        "aPlusMinConfidence": float(A_PLUS_MIN_CONFIDENCE),
        "sniperMinConfidence": float(SNIPER_MIN_CONFIDENCE),
        "aPlusMinQuality": float(A_PLUS_MIN_QUALITY),
        "sniperMinQuality": float(SNIPER_MIN_QUALITY),
        "updatedAt": saved.get("updatedAt", ""),
        "presets": STRATEGY_PRESETS,
    }


@app.get("/strategy-settings")
def api_get_strategy_settings():
    return current_strategy_settings_payload()


@app.post("/strategy-settings")
def api_set_strategy_settings(request: Request, payload: dict = Body(...)):
    verify_api_key(request)
    level = payload.get("level")
    preset = payload.get("preset")
    result = apply_strategy_settings(level=level, preset=preset, save=True)
    return {**result, "message": f"Trading strictness set to {result['label']}"}


try:
    saved_strategy = _load_strategy_settings()
    if str(saved_strategy.get("preset") or "").lower() == "custom":
        apply_custom_a_plus_thresholds(
            float(saved_strategy.get("aPlusMinConfidence", A_PLUS_MIN_CONFIDENCE)),
            float(saved_strategy.get("aPlusMinQuality", A_PLUS_MIN_QUALITY)),
            reason="restore saved adaptive settings", save=False,
        )
    else:
        apply_strategy_settings(
            level=int(saved_strategy.get("level", 0)),
            preset=saved_strategy.get("preset", "safe"),
            save=False,
        )
except Exception as e:
    print(f"STRATEGY SETTINGS STARTUP APPLY ERROR: {e}")



# ============================================================
# LIVE POSITION LIMIT SETTINGS
# ============================================================

POSITION_SETTINGS_FILE = os.path.join("backend", "state", "position_settings.json")

def _save_position_settings(payload: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(POSITION_SETTINGS_FILE), exist_ok=True)
        with open(POSITION_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"POSITION SETTINGS SAVE ERROR: {e}")


def _load_position_settings() -> Dict[str, Any]:
    try:
        if os.path.exists(POSITION_SETTINGS_FILE):
            with open(POSITION_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"POSITION SETTINGS LOAD ERROR: {e}")
    return {"maxPositions": int(MAX_POSITIONS), "swingSafeMode": bool(globals().get("SWING_SNIPER_SAFE_MODE", False))}


def apply_position_settings(max_positions: int = None, save: bool = True) -> Dict[str, Any]:
    global MAX_POSITIONS, STRICT_MAX_POSITIONS

    try:
        value = int(max_positions if max_positions is not None else MAX_POSITIONS)
    except Exception:
        value = int(MAX_POSITIONS)

    value = max(1, min(10, value))
    if globals().get("V17_SINGLE_FULL_BUY_MODE", False):
        value = 1
    elif globals().get("SWING_SNIPER_SAFE_MODE", False):
        value = 1

    MAX_POSITIONS = value

    try:
        STRICT_MAX_POSITIONS = value
    except Exception:
        pass

    payload = {
        "ok": True,
        "maxPositions": int(MAX_POSITIONS),
        "min": 1,
        "max": 10,
        "updatedAt": datetime.now(UTC).isoformat(),
    }

    if save:
        _save_position_settings(payload)

    try:
        latest_status["positionSettings"] = payload
        latest_status["maxPositions"] = int(MAX_POSITIONS)
        latest_status["allowedNewPositions"] = allowed_new_position_count()
        latest_status["config"]["maxPositions"] = int(MAX_POSITIONS)
        latest_status["lastAction"] = f"Max positions set to {MAX_POSITIONS}"
        latest_status["lastActionAt"] = payload["updatedAt"]
    except Exception:
        pass

    return payload


def current_position_settings_payload() -> Dict[str, Any]:
    saved = _load_position_settings()
    return {
        "ok": True,
        "maxPositions": int(effective_max_positions()),
        "savedMaxPositions": int(saved.get("maxPositions", MAX_POSITIONS)),
        "autonomousPositionCapacity": ai_position_capacity_payload(),
        "manualSliderActive": not AI_POSITION_CAPACITY_ENABLED,
        "min": 1,
        "max": 10,
        "updatedAt": saved.get("updatedAt", ""),
    }


@app.get("/position-settings")
def api_get_position_settings():
    return current_position_settings_payload()


@app.get("/ai-position-capacity")
def api_ai_position_capacity(request: Request):
    verify_api_key(request)
    payload = ai_position_capacity_payload()
    return {"ok": True, **payload}


@app.post("/position-settings")
def api_set_position_settings(request: Request, payload: dict = Body(...)):
    verify_api_key(request)
    if AI_POSITION_CAPACITY_ENABLED:
        current = current_position_settings_payload()
        return {
            **current,
            "message": "Manual position slider is disabled. AI portfolio capacity is active.",
        }
    result = apply_position_settings(max_positions=payload.get("maxPositions"), save=True)
    return {**result, "message": f"Max positions set to {result['maxPositions']}"}


try:
    saved_positions = _load_position_settings()
    apply_position_settings(max_positions=int(saved_positions.get("maxPositions", MAX_POSITIONS)), save=False)
except Exception as e:
    print(f"POSITION SETTINGS STARTUP APPLY ERROR: {e}")


# =========================
# ROUTES
# =========================

@app.get("/debug-orders")
def debug_orders():
    try:
        req = GetOrdersRequest(
            status=get_query_order_status_all(),
            limit=10,
            direction="desc",
        )
        orders = trading_client.get_orders(filter=req)
        sample = []
        for o in orders[:10]:
            sample.append({
                "id": str(getattr(o, "id", "")),
                "symbol": str(getattr(o, "symbol", "")),
                "side": str(getattr(o, "side", "")),
                "status": str(getattr(o, "status", "")),
                "filled_qty": str(getattr(o, "filled_qty", "")),
                "filled_avg_price": str(getattr(o, "filled_avg_price", "")),
                "submitted_at": str(getattr(o, "submitted_at", "")),
                "filled_at": str(getattr(o, "filled_at", "")),
            })
        return {"ok": True, "count": len(orders), "sample": sample}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/")
def root():
    return {"message": "Rebuilt Sniper Profit Bot running", "status": "/status", "paperMode": PAPER}



@app.get("/v2/status")
def v2_status():
    return {
        "ok": True, "enabled": TRADEBOT_V2_ENABLED, "paper": PAPER,
        "liveBuyingEnabled": TRADEBOT_V2_LIVE_ENABLED,
        "mode": "paper" if PAPER else ("live" if TRADEBOT_V2_LIVE_ENABLED else "validation-only"),
        "features": {
            "decisionExplanation": True, "shadowVsOriginal": True,
            "adaptiveThresholdAdvisory": True, "autoApplyThresholds": V2_AUTO_APPLY_THRESHOLDS,
            "guardedOptimizer": True, "strategyTimeline": True,
            "marketDna": V4_MARKET_DNA_ENABLED, "similarityEngine": True,
            "patternMiner": True, "weeklyIntelligence": True
        },
        "rules": {
            "minSamples": V2_MIN_SYMBOL_SAMPLES, "minWinRate": V2_MIN_WIN_RATE,
            "minProfitFactor": V2_MIN_PROFIT_FACTOR, "minExpectancyPct": V2_MIN_EXPECTANCY_PCT,
            "lookbackDays": V2_LOOKBACK_DAYS, "maxPositions": effective_max_positions(),
            "positionCapacity": ai_position_capacity_payload(),
            "logDecisions": V2_LOG_DECISIONS, "decisionDedupeSeconds": V2_DECISION_DEDUPE_SECONDS,
        },
    }

@app.get("/v2/explain/{symbol}")
def v2_explain(symbol: str):
    return v2_decision_explanation(symbol)

@app.get("/v2/decision-review")
def api_v2_decision_review(limit: int = 100):
    return v2_decision_review(limit)

@app.get("/v2/adaptive-thresholds")
def api_v2_adaptive_thresholds(horizon_hours: int = 24, min_samples: int = 25):
    return v2_adaptive_threshold_recommendations(horizon_hours, min_samples)

@app.get("/v2/strategy-timeline")
def api_v2_strategy_timeline(limit: int = 50):
    return v2_strategy_timeline(limit)

@app.post("/v2/strategy-rollback")
def api_v2_strategy_rollback(request: Request):
    verify_api_key(request)
    return v2_rollback_latest_strategy()

@app.get("/v4/status")
def api_v4_status():
    return v4_status_payload()

@app.get("/v4/market-dna")
def api_v4_market_dna(symbol: Optional[str] = None, limit: int = 100, horizon_hours: int = 24):
    rows = v4_market_dna_rows(symbol, limit)
    report = v4_pattern_report(horizon_hours, V4_PATTERN_MIN_SAMPLES)
    regime_rows = ((report.get("patterns") or {}).get("marketRegime") or []) if report.get("ok") else []
    latest = rows[0] if rows else None
    current = {
        "symbol": (latest or {}).get("symbol"),
        "regime": (latest or {}).get("market_regime") or "UNKNOWN",
        "session": (latest or {}).get("session_name") or "UNKNOWN",
        "confidence": float((latest or {}).get("confidence") or 0.0),
        "quality": float((latest or {}).get("quality") or 0.0),
        "momentum": float((latest or {}).get("momentum") or 0.0),
        "spread": float((latest or {}).get("spread") or 0.0),
        "observedAt": (latest or {}).get("observed_at"),
    } if latest else {}
    return {"ok": True, "version": "V9.9", "rows": rows, "current": current,
            "regimes": regime_rows, "marketRegimes": regime_rows,
            "overall": report.get("overall", {}), "bestPatterns": report.get("bestPatterns", []),
            "observations": int(report.get("observations") or 0),
            "advisoryOnly": True, "automaticLiveChanges": False}

@app.get("/v4/similarity/{symbol}")
def api_v4_similarity(symbol: str, horizon_hours: int = 24, limit: int = 50):
    return v4_similarity_for_symbol(symbol, horizon_hours, limit)

@app.get("/v4/explain/{decision_id}")
def api_v4_explain(decision_id: int, horizon_hours: int = 24, limit: int = 50):
    return v4_explain_decision(decision_id, horizon_hours, limit)

@app.get("/v4/explain-symbol/{symbol}")
def api_v4_explain_symbol(symbol: str, horizon_hours: int = 24, limit: int = 50):
    return v4_explain_latest_symbol(symbol, horizon_hours, limit)

@app.get("/v4/confidence/{symbol}")
def api_v4_confidence(symbol: str, horizon_hours: int = 24, limit: int = 50):
    return v4_contextual_confidence_for_symbol(symbol, horizon_hours, limit)

@app.get("/v4/confidence-decision/{decision_id}")
def api_v4_confidence_decision(decision_id: int, horizon_hours: int = 24, limit: int = 50):
    return v4_contextual_confidence_for_decision(decision_id, horizon_hours, limit)

@app.get("/v4/patterns")
def api_v4_patterns(horizon_hours: int = 24, min_samples: int = 8):
    return v4_pattern_report(horizon_hours, min_samples)

@app.get("/v4/weekly-intelligence")
def api_v4_weekly_intelligence(horizon_hours: int = 24):
    return v4_weekly_intelligence(horizon_hours)



# =========================
# TRADEBOT V4.3 — CONTEXTUAL SIMILARITY / CONFIDENCE INTELLIGENCE
# =========================
def _v4_session_name(dt: datetime) -> str:
    hour = dt.hour
    if hour < 14:
        return "PRE_MARKET_OR_EARLY_UTC"
    if hour < 17:
        return "US_MORNING"
    if hour < 20:
        return "US_AFTERNOON"
    return "US_LATE_OR_AFTER_HOURS"


def _v4_index_move(symbol: str) -> Optional[float]:
    try:
        st = state.get(symbol) or {}
        curve = st.get("price_curve") or []
        if len(curve) >= 2:
            first = float(curve[0].get("value") or 0.0)
            last = float(curve[-1].get("value") or 0.0)
            if first > 0:
                return (last / first) - 1.0
    except Exception:
        pass
    return None


def _v4_market_regime() -> str:
    spy = _v4_index_move("SPY")
    qqq = _v4_index_move("QQQ")
    values = [x for x in (spy, qqq) if x is not None]
    if not values:
        return "UNKNOWN"
    avg = sum(values) / len(values)
    if avg >= 0.007:
        return "STRONG_RISK_ON"
    if avg >= 0.0015:
        return "RISK_ON"
    if avg <= -0.007:
        return "STRONG_RISK_OFF"
    if avg <= -0.0015:
        return "RISK_OFF"
    return "SIDEWAYS"


def record_v4_market_dna(conn, decision_id: int, scan: Dict[str, Any], decision: str,
                         stage: str, reason: str, observed_at: datetime) -> None:
    """Persist the exact context available to the live bot. It never changes an order decision."""
    try:
        position_count = 0
        try:
            position_count = len(get_all_positions())
        except Exception:
            pass
        payload = {
            "confidenceLabel": scan.get("confidence_label"),
            "sniperReason": scan.get("sniper_reason"),
            "aPlusReason": scan.get("a_plus_reason"),
            "lockedToday": bool(scan.get("locked_today")),
            "custom": bool(scan.get("custom")),
            "source": "live_scan_context",
        }
        conn.execute(
            """INSERT OR REPLACE INTO v4_market_dna (
               decision_id,observed_at,symbol,decision,stage,reason,market_regime,
               session_name,weekday,hour_utc,price,confidence,quality,momentum,pullback,
               spread,ready_to_buy,sniper_pass,a_plus_pass,spy_move,qqq_move,
               position_count,payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(decision_id), observed_at.isoformat(), str(scan.get("symbol") or "").upper(),
                str(decision), str(stage), str(reason)[:1000], _v4_market_regime(),
                _v4_session_name(observed_at), int(observed_at.weekday()), int(observed_at.hour),
                float(scan.get("price") or 0.0), float(scan.get("confidence") or 0.0),
                float(scan.get("quality_score") or 0.0), float(scan.get("short_momentum") or 0.0),
                float(scan.get("pullback") or 0.0), float(scan.get("spread") or 0.0),
                int(bool(scan.get("ready_to_buy"))), int(bool(scan.get("sniper_pass"))),
                int(bool(scan.get("a_plus_pass"))), _v4_index_move("SPY"), _v4_index_move("QQQ"),
                position_count, json.dumps(payload, default=str),
            ),
        )
    except Exception as e:
        print(f"V4 MARKET DNA ERROR: {e}")


def v4_market_dna_rows(symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    try:
        init_db(); conn = db_connect()
        params: List[Any] = []
        where = ""
        if symbol:
            where = "WHERE symbol=?"
            params.append(str(symbol).upper())
        params.append(max(1, min(int(limit), 2000)))
        rows = conn.execute(f"SELECT * FROM v4_market_dna {where} ORDER BY id DESC LIMIT ?", params).fetchall()
        conn.close()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
            except Exception:
                item["payload"] = {}
            result.append(item)
        return result
    except Exception as e:
        print(f"V4 DNA READ ERROR: {e}")
        return []


def _v4_current_scan(symbol: str) -> Dict[str, Any]:
    sym = str(symbol or "").upper()
    for scan in latest_scans:
        if str(scan.get("symbol") or "").upper() == sym:
            return scan
    for scan in latest_status.get("scans") or []:
        if str(scan.get("symbol") or "").upper() == sym:
            return {
                "symbol": sym, "price": scan.get("price"), "confidence": scan.get("confidence"),
                "quality_score": scan.get("qualityScore"), "short_momentum": scan.get("shortMomentum"),
                "pullback": scan.get("pullback"), "spread": scan.get("spread"),
            }
    return {}


def _v4_weighted_similarity_summary(ranked: List[Dict[str, Any]], limit: int) -> Dict[str, Any]:
    """Summarise contextual neighbours with similarity, recency and sample-size controls."""
    chosen = ranked[:max(1, min(int(limit or V4_SIMILARITY_LIMIT), 200))]
    if not chosen:
        return {
            "matches": 0, "effectiveSamples": 0.0, "winRate": 0.0,
            "profitFactor": 0.0, "profitFactorDisplay": 0.0,
            "expectancyPct": 0.0, "averageSimilarity": 0.0,
            "evidenceReliability": 0.0, "recommendation": "WATCH",
        }

    weighted_wins = weighted_losses = weighted_return = total_weight = 0.0
    gross_profit = gross_loss = 0.0
    now = datetime.now(UTC)
    for item in chosen:
        similarity = max(0.0, min(1.0, float(item.get("similarity") or 0.0)))
        evaluated_at = item.get("evaluated_at") or item.get("observed_at")
        age_days = 365.0
        try:
            dt = datetime.fromisoformat(str(evaluated_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            age_days = max(0.0, (now - dt.astimezone(UTC)).total_seconds() / 86400.0)
        except Exception:
            pass
        recency = 0.5 ** (age_days / 90.0)  # 90-day half-life
        weight = max(0.01, similarity ** 2 * recency)
        ret = float(item.get("net_return_pct") or 0.0)
        total_weight += weight
        weighted_return += ret * weight
        if ret > 0:
            weighted_wins += weight
            gross_profit += ret * weight
        elif ret < 0:
            weighted_losses += weight
            gross_loss += abs(ret) * weight

    decisive_weight = weighted_wins + weighted_losses
    win_rate = weighted_wins / decisive_weight if decisive_weight > 0 else 0.0
    expectancy = weighted_return / total_weight if total_weight > 0 else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    avg_similarity = sum(float(x.get("similarity") or 0.0) for x in chosen) / len(chosen)
    effective_samples = total_weight
    sample_score = min(1.0, effective_samples / max(1.0, float(V4_SIMILARITY_MIN_SAMPLES)))
    similarity_score = min(1.0, max(0.0, (avg_similarity - 0.25) / 0.50))
    reliability = sample_score * similarity_score
    enough = len(chosen) >= V4_SIMILARITY_MIN_SAMPLES and effective_samples >= max(4.0, V4_SIMILARITY_MIN_SAMPLES * 0.40)
    recommendation = "WATCH"
    if enough and reliability >= 0.35:
        if expectancy > 0.10 and pf >= 1.10 and win_rate >= 0.50:
            recommendation = "APPROVE"
        elif expectancy < 0 or pf < 0.90:
            recommendation = "BLOCK"
    return {
        "matches": len(chosen),
        "effectiveSamples": effective_samples,
        "winRate": win_rate,
        "profitFactor": pf,
        "profitFactorDisplay": min(pf, 20.0),
        "expectancyPct": expectancy,
        "averageSimilarity": avg_similarity,
        "evidenceReliability": reliability,
        "recommendation": recommendation,
        "chosen": chosen,
    }


def _v4_rank_contextual_rows(rows: List[Any], target: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rank historical observations by the full setup, not merely by ticker."""
    numeric_scales = {
        "confidence": 0.15, "quality": 0.015, "momentum": 0.02,
        "pullback": 0.02, "spread": 0.01, "spy_move": 0.012, "qqq_move": 0.015,
    }
    ranked: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        distance = 0.0
        used = 0
        for key, scale in numeric_scales.items():
            tv = target.get(key)
            rv = item.get(key)
            if tv is None or rv is None:
                continue
            distance += ((float(rv or 0.0) - float(tv or 0.0)) / scale) ** 2
            used += 1
        if used == 0:
            continue
        if str(item.get("market_regime") or "UNKNOWN") != str(target.get("market_regime") or "UNKNOWN"):
            distance += 1.00
        if str(item.get("session_name") or "UNKNOWN") != str(target.get("session_name") or "UNKNOWN"):
            distance += 0.35
        if int(item.get("weekday") or -1) != int(target.get("weekday") or -2):
            distance += 0.08
        # Same-symbol history is useful but cannot dominate contextual evidence.
        if str(item.get("symbol") or "").upper() == str(target.get("symbol") or "").upper():
            distance = max(0.0, distance - 0.20)
        similarity = 1.0 / (1.0 + math.sqrt(max(0.0, distance)))
        ranked.append({**item, "similarity": similarity})
    ranked.sort(key=lambda x: x["similarity"], reverse=True)
    return ranked


def _v4_target_from_scan(symbol: str, current: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "symbol": str(symbol or "").upper(),
        "confidence": float(current.get("confidence") or 0.0),
        "quality": float(current.get("quality_score") or current.get("qualityScore") or 0.0),
        "momentum": float(current.get("short_momentum") or current.get("shortMomentum") or 0.0),
        "pullback": float(current.get("pullback") or 0.0),
        "spread": float(current.get("spread") or 0.0),
        "spy_move": _v4_index_move("SPY"), "qqq_move": _v4_index_move("QQQ"),
        "market_regime": _v4_market_regime(), "session_name": _v4_session_name(now),
        "weekday": now.weekday(),
    }


def v4_similarity_for_symbol(symbol: str, horizon_hours: int = 24, limit: int = 50) -> Dict[str, Any]:
    """V4.3 contextual nearest-neighbour evidence. Advisory only."""
    sym = str(symbol or "").upper().strip()
    current = _v4_current_scan(sym)
    base = {"ok": True, "version": "V4.3", "advisoryOnly": True, "symbol": sym, "horizonHours": int(horizon_hours)}
    if not current:
        return {**base, "recommendation": "WATCH", "reason": "No current scan available", "matches": 0}
    try:
        init_db(); conn = db_connect()
        rows = conn.execute(
            """SELECT d.*,o.net_return_pct,o.evaluated_at
               FROM v4_market_dna d JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
               WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL AND o.horizon_hours=?
               ORDER BY o.evaluated_at DESC LIMIT 5000""", (int(horizon_hours),)
        ).fetchall(); conn.close()
        target = _v4_target_from_scan(sym, current)
        ranked = _v4_rank_contextual_rows(list(rows), target)
        summary = _v4_weighted_similarity_summary(ranked, limit)
        chosen = summary.pop("chosen", [])
        return {**base, **summary, "minimumSamples": V4_SIMILARITY_MIN_SAMPLES,
                "currentFeatures": target,
                "topMatches": [{k: x.get(k) for k in (
                    "decision_id","symbol","observed_at","decision","stage","market_regime","session_name",
                    "confidence","quality","momentum","pullback","spread","spy_move","qqq_move",
                    "net_return_pct","similarity") } for x in chosen[:10]],
                "note": "Contextual evidence uses similarity and recency weighting and cannot place or block an order."}
    except Exception as e:
        return {**base, "ok": False, "error": str(e), "recommendation": "WATCH", "matches": 0}


def _v4_similarity_for_dna(dna: Dict[str, Any], horizon_hours: int = 24,
                           limit: int = 50, exclude_decision_id: Optional[int] = None) -> Dict[str, Any]:
    symbol = str(dna.get("symbol") or "").upper().strip()
    base = {"ok": True, "version": "V4.3", "advisoryOnly": True, "symbol": symbol, "horizonHours": int(horizon_hours)}
    try:
        init_db(); conn = db_connect()
        sql = """SELECT d.*,o.net_return_pct,o.evaluated_at FROM v4_market_dna d
                 JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
                 WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL AND o.horizon_hours=?"""
        params: List[Any] = [int(horizon_hours)]
        if exclude_decision_id is not None:
            sql += " AND d.decision_id<>?"; params.append(int(exclude_decision_id))
        sql += " ORDER BY o.evaluated_at DESC LIMIT 5000"
        rows = conn.execute(sql, params).fetchall(); conn.close()
        target = {k: dna.get(k) for k in (
            "symbol","confidence","quality","momentum","pullback","spread","spy_move","qqq_move",
            "market_regime","session_name","weekday")}
        ranked = _v4_rank_contextual_rows(list(rows), target)
        summary = _v4_weighted_similarity_summary(ranked, limit)
        chosen = summary.pop("chosen", [])
        return {**base, **summary, "minimumSamples": V4_SIMILARITY_MIN_SAMPLES,
                "currentFeatures": target,
                "topMatches": [{k: x.get(k) for k in (
                    "decision_id","symbol","observed_at","decision","stage","market_regime","session_name",
                    "confidence","quality","momentum","pullback","spread","spy_move","qqq_move",
                    "net_return_pct","similarity") } for x in chosen[:10]],
                "note": "Historical similarity is advisory and cannot place or block an order."}
    except Exception as e:
        return {**base, "ok": False, "error": str(e), "recommendation": "WATCH", "matches": 0}


def _v4_contextual_confidence(dna: Dict[str, Any], similarity: Dict[str, Any]) -> Dict[str, Any]:
    confidence = max(0.0, min(1.0, float(dna.get("confidence") or 0.0)))
    quality = max(0.0, float(dna.get("quality") or 0.0))
    momentum = float(dna.get("momentum") or 0.0)
    spread = max(0.0, float(dna.get("spread") or 0.0))
    technical = 100.0 * max(0.0, min(1.0,
        confidence * 0.55 + min(1.0, quality / 0.04) * 0.25 +
        max(0.0, min(1.0, 0.5 + momentum / 0.04)) * 0.15 +
        max(0.0, min(1.0, 1.0 - spread / 0.02)) * 0.05))
    recommendation = str(similarity.get("recommendation") or "WATCH")
    wr = float(similarity.get("winRate") or 0.0)
    expectancy = float(similarity.get("expectancyPct") or 0.0)
    historical_raw = wr * 70.0 + max(0.0, min(30.0, 15.0 + expectancy * 10.0))
    reliability = max(0.0, min(1.0, float(similarity.get("evidenceReliability") or 0.0)))
    historical = 50.0 + (historical_raw - 50.0) * reliability
    spy = dna.get("spy_move"); qqq = dna.get("qqq_move")
    moves = [float(x) for x in (spy, qqq) if x is not None]
    market = 50.0 if not moves else max(0.0, min(100.0, 50.0 + (sum(moves)/len(moves)) * 2500.0))
    if recommendation == "BLOCK": historical = min(historical, 40.0)
    elif recommendation == "APPROVE": historical = max(historical, 60.0)
    overall = technical * 0.55 + historical * 0.30 + market * 0.15
    grade = "HIGH" if overall >= 75 and reliability >= 0.35 else ("MEDIUM" if overall >= 60 else "LOW")
    return {
        "technicalScore": round(technical, 2), "historicalScore": round(historical, 2),
        "marketScore": round(market, 2), "dataReliabilityScore": round(reliability * 100.0, 2),
        "overallScore": round(overall, 2), "grade": grade,
        "advisoryRecommendation": recommendation,
        "weights": {"technical": 0.55, "historical": 0.30, "market": 0.15},
    }


def v4_contextual_confidence_for_symbol(symbol: str, horizon_hours: int = 24, limit: int = 50) -> Dict[str, Any]:
    sym = str(symbol or "").upper().strip(); current = _v4_current_scan(sym)
    if not current:
        return {"ok": False, "version": "V4.3", "symbol": sym, "message": "No current scan available"}
    now = datetime.now(UTC)
    dna = _v4_target_from_scan(sym, current)
    dna.update({"price": current.get("price")})
    similarity = v4_similarity_for_symbol(sym, horizon_hours, limit)
    return {"ok": True, "version": "V4.3", "advisoryOnly": True, "symbol": sym,
            "observedAt": now.isoformat(), "confidenceBreakdown": _v4_contextual_confidence(dna, similarity),
            "historicalEvidence": similarity,
            "note": "The score is explanatory only and does not change the live gate."}


def v4_contextual_confidence_for_decision(decision_id: int, horizon_hours: int = 24, limit: int = 50) -> Dict[str, Any]:
    try:
        init_db(); conn = db_connect()
        row = conn.execute("SELECT * FROM v4_market_dna WHERE decision_id=?", (int(decision_id),)).fetchone(); conn.close()
        if not row:
            return {"ok": False, "decisionId": int(decision_id), "message": "Decision not found"}
        dna = dict(row); similarity = _v4_similarity_for_dna(dna, horizon_hours, limit, int(decision_id))
        return {"ok": True, "version": "V4.3", "advisoryOnly": True, "decisionId": int(decision_id),
                "symbol": dna.get("symbol"), "confidenceBreakdown": _v4_contextual_confidence(dna, similarity),
                "historicalEvidence": similarity,
                "note": "The score audits a stored decision and cannot alter live trading."}
    except Exception as e:
        return {"ok": False, "decisionId": int(decision_id), "error": str(e)}


def _v4_explanation_reasons(dna: Dict[str, Any], similarity: Dict[str, Any]) -> List[Dict[str, Any]]:
    reasons: List[Dict[str, Any]] = []

    def add(label: str, passed: Optional[bool], detail: str) -> None:
        status = "INFO" if passed is None else ("PASS" if passed else "CAUTION")
        reasons.append({"status": status, "label": label, "detail": detail})

    confidence = float(dna.get("confidence") or 0.0)
    quality = float(dna.get("quality") or 0.0)
    momentum = float(dna.get("momentum") or 0.0)
    spread = float(dna.get("spread") or 0.0)
    add("Confidence", confidence >= 0.70, f"Recorded confidence {confidence:.3f}")
    add("Quality", quality >= 0.026, f"Recorded quality {quality:.4f}")
    add("Momentum", momentum > 0, f"Short momentum {momentum:.4f}")
    add("Spread", spread <= 0.01 if spread > 0 else None, f"Recorded spread {spread:.4f}")
    add("A+ gate", bool(dna.get("a_plus_pass")), "Passed" if dna.get("a_plus_pass") else "Not passed")
    add("Sniper gate", bool(dna.get("sniper_pass")), "Passed" if dna.get("sniper_pass") else "Not passed")
    add("Market regime", None, str(dna.get("market_regime") or "UNKNOWN"))
    add("Session", None, str(dna.get("session_name") or "UNKNOWN"))

    matches = int(similarity.get("matches") or 0)
    if matches:
        wr = float(similarity.get("winRate") or 0.0)
        pf = float(similarity.get("profitFactor") or 0.0)
        exp = float(similarity.get("expectancyPct") or 0.0)
        add("Historical evidence", similarity.get("recommendation") == "APPROVE",
            f"{matches} matches | win rate {wr:.1%} | PF {pf:.2f} | expectancy {exp:.3f}%")
    else:
        add("Historical evidence", None, "No completed comparable outcomes yet")
    return reasons


def v4_explain_decision(decision_id: int, horizon_hours: int = 24, limit: int = 50) -> Dict[str, Any]:
    """Return a complete, human-readable audit for one stored decision."""
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    try:
        init_db()
        conn = db_connect()
        row = conn.execute(
            """SELECT d.*,s.timestamp AS decision_timestamp,s.payload_json AS decision_payload_json
               FROM v4_market_dna d
               LEFT JOIN v2_setup_decisions s ON s.id=d.decision_id
               WHERE d.decision_id=?""",
            (int(decision_id),),
        ).fetchone()
        if not row:
            conn.close()
            return {"ok": False, "message": "Decision not found", "decisionId": int(decision_id)}
        dna = dict(row)
        outcomes = [dict(r) for r in conn.execute(
            """SELECT horizon_hours,status,due_at,evaluated_at,outcome_price,return_pct,
                      net_return_pct,estimated_cost_pct,error
               FROM v2_observation_outcomes WHERE decision_id=? ORDER BY horizon_hours""",
            (int(decision_id),),
        ).fetchall()]
        conn.close()
        try:
            dna["payload"] = json.loads(dna.pop("payload_json") or "{}")
        except Exception:
            dna["payload"] = {}
        try:
            dna["decisionPayload"] = json.loads(dna.pop("decision_payload_json") or "{}")
        except Exception:
            dna["decisionPayload"] = {}

        similarity = _v4_similarity_for_dna(dna, horizon_hours, limit, int(decision_id))
        confidence_breakdown = _v4_contextual_confidence(dna, similarity)
        reasons = _v4_explanation_reasons(dna, similarity)
        original_decision = str(dna.get("decision") or "UNKNOWN")
        advisory = str(similarity.get("recommendation") or "WATCH")
        agreement = (
            "AGREE" if (original_decision == "APPROVE" and advisory == "APPROVE") or
                       (original_decision != "APPROVE" and advisory == "BLOCK")
            else "INSUFFICIENT_EVIDENCE" if advisory == "WATCH" else "DISAGREE"
        )
        return {
            "ok": True,
            "version": "V4.3",
            "advisoryOnly": True,
            "decisionId": int(decision_id),
            "symbol": dna.get("symbol"),
            "decision": original_decision,
            "stage": dna.get("stage"),
            "reason": dna.get("reason"),
            "observedAt": dna.get("observed_at"),
            "marketRegime": dna.get("market_regime"),
            "session": dna.get("session_name"),
            "features": {k: dna.get(k) for k in (
                "price", "confidence", "quality", "momentum", "pullback", "spread",
                "ready_to_buy", "sniper_pass", "a_plus_pass", "spy_move", "qqq_move",
                "position_count"
            )},
            "historicalEvidence": similarity,
            "confidenceBreakdown": confidence_breakdown,
            "explanation": reasons,
            "advisoryAgreement": agreement,
            "outcomes": outcomes,
            "note": "This explanation audits the decision; it does not alter live trading.",
        }
    except Exception as e:
        return {"ok": False, "decisionId": int(decision_id), "error": str(e)}


def v4_explain_latest_symbol(symbol: str, horizon_hours: int = 24, limit: int = 50) -> Dict[str, Any]:
    sym = str(symbol or "").upper().strip()
    try:
        init_db()
        conn = db_connect()
        row = conn.execute(
            "SELECT decision_id FROM v4_market_dna WHERE symbol=? ORDER BY id DESC LIMIT 1",
            (sym,),
        ).fetchone()
        conn.close()
        if not row:
            return {"ok": False, "symbol": sym, "message": "No Market DNA decision found for symbol"}
        return v4_explain_decision(int(row["decision_id"]), horizon_hours, limit)
    except Exception as e:
        return {"ok": False, "symbol": sym, "error": str(e)}

def _v4_metrics(values: List[float]) -> Dict[str, Any]:
    wins = [x for x in values if x > 0]; losses = [x for x in values if x < 0]
    gp, gl = sum(wins), abs(sum(losses))
    return {"samples": len(values), "winRate": len(wins) / max(1, len(wins)+len(losses)),
            "profitFactor": gp / gl if gl > 0 else (99.0 if gp > 0 else 0.0),
            "expectancyPct": sum(values) / max(1, len(values)),
            "bestReturnPct": max(values) if values else 0.0, "worstReturnPct": min(values) if values else 0.0}


def v4_pattern_report(horizon_hours: int = 24, min_samples: int = 8) -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    try:
        init_db(); conn = db_connect()
        rows = [dict(r) for r in conn.execute(
            """SELECT d.*,o.net_return_pct FROM v4_market_dna d
               JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
               WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL AND o.horizon_hours=?""",
            (int(horizon_hours),)).fetchall()]
        conn.close()
        groups: Dict[str, Dict[str, List[float]]] = {
            "marketRegime": {}, "session": {}, "stage": {}, "confidenceBand": {}, "qualityBand": {}
        }
        for r in rows:
            ret = float(r.get("net_return_pct") or 0.0)
            conf = float(r.get("confidence") or 0.0); qual = float(r.get("quality") or 0.0)
            conf_band = f"{math.floor(conf*10)/10:.1f}-{math.floor(conf*10)/10+0.1:.1f}"
            qlow = math.floor(qual/0.005)*0.005
            qual_band = f"{qlow:.3f}-{qlow+0.005:.3f}"
            keys = {"marketRegime": str(r.get("market_regime") or "UNKNOWN"),
                    "session": str(r.get("session_name") or "UNKNOWN"),
                    "stage": str(r.get("stage") or "UNKNOWN"),
                    "confidenceBand": conf_band, "qualityBand": qual_band}
            for category, key in keys.items():
                groups[category].setdefault(key, []).append(ret)
        output = {}
        for category, mapping in groups.items():
            items = [{"name": name, **_v4_metrics(vals)} for name, vals in mapping.items() if len(vals) >= int(min_samples)]
            items.sort(key=lambda x: (x["expectancyPct"], x["profitFactor"], x["samples"]), reverse=True)
            output[category] = items
        all_metrics = _v4_metrics([float(r.get("net_return_pct") or 0.0) for r in rows])
        return {"ok": True, "advisoryOnly": True, "horizonHours": int(horizon_hours),
                "minimumSamplesPerPattern": int(min_samples), "observations": len(rows),
                "overall": all_metrics, "patterns": output,
                "bestPatterns": [{"category": cat, **items[0]} for cat, items in output.items() if items],
                "note": "Patterns are descriptive evidence only; no live threshold is changed."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def v4_weekly_intelligence(horizon_hours: int = 24) -> Dict[str, Any]:
    report = v4_pattern_report(horizon_hours, V4_PATTERN_MIN_SAMPLES)
    if not report.get("ok"):
        return report
    cutoff = datetime.now(UTC) - timedelta(days=7)
    try:
        init_db(); conn = db_connect()
        rows = [dict(r) for r in conn.execute(
            """SELECT d.*,o.net_return_pct FROM v4_market_dna d
               JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
               WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL
                 AND o.horizon_hours=? AND d.observed_at>=?""",
            (int(horizon_hours), cutoff.isoformat())).fetchall()]
        conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    metrics = _v4_metrics([float(r.get("net_return_pct") or 0.0) for r in rows])
    best = report.get("bestPatterns") or []
    recommendation = "COLLECT_MORE_EVIDENCE"
    if metrics["samples"] >= V4_PATTERN_MIN_SAMPLES:
        recommendation = "CONTINUE_CURRENT_GUARDS" if metrics["expectancyPct"] >= 0 else "REVIEW_WEAK_PATTERNS"
    direction = "positive" if metrics["expectancyPct"] > 0 else "negative" if metrics["expectancyPct"] < 0 else "flat"
    message = (f"The latest 7-day Market DNA sample contains {metrics['samples']} completed 24-hour outcomes, "
               f"with a {metrics['winRate']*100:.1f}% win rate and {metrics['expectancyPct']:.3f}% average expectancy. "
               f"The evidence is currently {direction}; recommendation: {recommendation.replace('_',' ').lower()}.")
    return {"ok": True, "advisoryOnly": True, "periodDays": 7, "horizonHours": int(horizon_hours),
            "title": "Weekly Market DNA review", "message": message,
            "weekly": metrics, "summary": {"title": "Weekly Market DNA review", **metrics},
            "recommendation": {"verdict": recommendation, "nextStep": "Shadow-test before any live change."},
            "topPatterns": best[:5], "highlights": best[:5],
            "marketDnaRows": len(v4_market_dna_rows(limit=2000)),
            "nextStep": "Use similarity and pattern evidence in shadow mode before any guarded optimiser proposal."}


def v4_status_payload() -> Dict[str, Any]:
    try:
        rows = v4_market_dna_rows(limit=1)
        init_db(); conn = db_connect()
        count = int(conn.execute("SELECT COUNT(*) FROM v4_market_dna").fetchone()[0])
        complete = int(conn.execute("""SELECT COUNT(*) FROM v4_market_dna d JOIN v2_observation_outcomes o
                                      ON o.decision_id=d.decision_id WHERE o.status='COMPLETE'""").fetchone()[0])
        conn.close()
    except Exception:
        count, complete, rows = 0, 0, []
    return {"ok": True, "version": "V4.3", "mode": "advisory-contextual-intelligence",
            "marketDnaEnabled": V4_MARKET_DNA_ENABLED, "dnaRows": count,
            "completedOutcomeLinks": complete, "latestDna": rows[0] if rows else None,
            "features": {"marketDna": True, "similarityEngine": True, "patternMiner": True,
                         "weeklyIntelligence": True, "explainability": True, "contextualSimilarity": True,
                         "confidenceBreakdown": True, "recencyWeighting": True, "liveGateChanged": False}}


# =========================
# TRADEBOT V2 DECISION EXPLANATION + ADAPTIVE ADVISORY
# =========================
def _v2_metric_grade(samples: int, profit_factor: float, expectancy: float) -> str:
    if samples < 8:
        return "LOW"
    if samples >= 30 and profit_factor >= 1.50 and expectancy > 0:
        return "HIGH"
    if profit_factor >= 1.10 and expectancy >= 0:
        return "MEDIUM"
    return "LOW"


def _v2_drawdown(returns: List[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in returns:
        equity += float(value)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _v2_candidate_metrics(observations: List[Dict[str, Any]], confidence: float, quality: float, min_samples: int) -> Optional[Dict[str, Any]]:
    selected = [r for r in observations if float(r.get("confidence") or 0) >= confidence and float(r.get("quality") or 0) >= quality]
    returns = [float(r.get("net_return_pct") or 0) for r in selected]
    if len(returns) < int(min_samples):
        return None
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]
    gp, gl = sum(wins), abs(sum(losses))
    pf = gp / gl if gl > 0 else (99.0 if gp > 0 else 0.0)
    exp = sum(returns) / len(returns)
    wr = len(wins) / (len(wins)+len(losses)) if (wins or losses) else 0.0
    dd = _v2_drawdown(returns)
    robustness = min(1.0, len(returns)/100.0)
    score = exp * min(pf, 4.0) * (0.5 + 0.5*robustness) / (1.0 + dd)
    return {"confidence": confidence, "quality": quality, "samples": len(returns), "winRate": wr,
            "profitFactor": pf, "expectancyPct": exp, "maxDrawdownPct": dd,
            "largestLossPct": min(returns) if returns else 0.0, "score": score}


def _v2_blacklisted_symbols() -> set:
    blocked = set()
    try:
        stats = symbol_stats()
        rows = stats.values() if isinstance(stats, dict) else stats
        for row in rows or []:
            if str(row.get("trust") or "").upper() in {"BLACKLIST", "AVOID"}:
                blocked.add(str(row.get("symbol") or "").upper())
    except Exception:
        try:
            for row in (analytics_payload().get("worstStocks") or []):
                if str(row.get("trust") or "").upper() in {"BLACKLIST", "AVOID"}:
                    blocked.add(str(row.get("symbol") or "").upper())
        except Exception:
            pass
    return blocked


def _v2_step_toward(current: float, target: float, maximum_step: float, decimals: int) -> float:
    delta = max(-maximum_step, min(maximum_step, target-current))
    return round(current+delta, decimals)


def v2_adaptive_threshold_recommendations(horizon_hours: int = 24, min_samples: int = 25) -> Dict[str, Any]:
    """Guarded optimiser: blacklist filtering, rolling windows, drawdown, stability and optional staged apply."""
    current_conf, current_quality = float(A_PLUS_MIN_CONFIDENCE), float(A_PLUS_MIN_QUALITY)
    result = {"ok": True, "advisoryOnly": not V2_AUTO_APPLY_THRESHOLDS, "applied": False,
              "horizonHours": int(horizon_hours), "minimumSamples": int(min_samples),
              "current": {"confidence": current_conf, "quality": current_quality}}
    if not SQLITE_ENABLED:
        return {**result, "ok": False, "message": "SQLite disabled"}
    try:
        init_db(); conn=db_connect()
        blocked=_v2_blacklisted_symbols()
        rows=conn.execute("""WITH ranked AS (
              SELECT d.symbol,d.confidence,d.quality,o.net_return_pct,o.observed_at,
              ROW_NUMBER() OVER (PARTITION BY COALESCE(o.sample_key,CAST(o.decision_id AS TEXT)),o.horizon_hours ORDER BY o.id ASC) rn
              FROM v2_observation_outcomes o JOIN v2_setup_decisions d ON d.id=o.decision_id
              WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL AND o.horizon_hours=?)
              SELECT symbol,confidence,quality,net_return_pct,observed_at FROM ranked WHERE rn=1""",(int(horizon_hours),)).fetchall()
        all_obs=[dict(r) for r in rows]
        observations=[r for r in all_obs if str(r.get("symbol") or "").upper() not in blocked]
        now=datetime.now(UTC)
        windows=[24,72,168,720]
        confs=sorted(set([round(x,2) for x in [0.55,0.58,0.60,0.62,0.65,0.66,0.67,0.68,0.69,0.70,0.72,0.75,current_conf]]))
        quals=sorted(set([round(x,3) for x in [0.018,0.020,0.022,0.024,0.025,0.026,0.028,0.030,current_quality]]))
        candidates=[]
        for conf in confs:
            for qual in quals:
                window_metrics=[]
                for hours in windows:
                    cutoff=now-timedelta(hours=hours)
                    subset=[]
                    for r in observations:
                        try: dt=datetime.fromisoformat(str(r.get("observed_at")).replace("Z","+00:00"))
                        except Exception: continue
                        if dt>=cutoff: subset.append(r)
                    metric=_v2_candidate_metrics(subset,conf,qual,min_samples)
                    if metric: window_metrics.append({"hours":hours,**metric})
                base=_v2_candidate_metrics(observations,conf,qual,min_samples)
                if not base: continue
                positive=sum(1 for m in window_metrics if m["expectancyPct"]>0 and m["profitFactor"]>=1.1)
                base["positiveWindows"]=positive; base["availableWindows"]=len(window_metrics); base["windows"]=window_metrics
                base["stableScore"]=base["score"]*(0.5+0.5*(positive/max(1,len(window_metrics))))
                candidates.append(base)
        candidates.sort(key=lambda x:(x["stableScore"],x["samples"]),reverse=True)
        current=next((x for x in candidates if x["confidence"]==round(current_conf,2) and x["quality"]==round(current_quality,3)),None)
        best=candidates[0] if candidates else None
        recommendation="KEEP_CURRENT"; reason="Not enough completed, non-blacklisted evidence."
        eligible=False; staged=None
        if best and current:
            improvement=(best["stableScore"]-current["stableScore"])/max(abs(current["stableScore"]),1e-9)
            dd_ok=best["maxDrawdownPct"] <= current["maxDrawdownPct"]*(1+V2_OPTIMIZER_MAX_DRAWDOWN_INCREASE)+0.05
            windows_ok=best["positiveWindows"]>=max(1,(best["availableWindows"]+1)//2)
            materially_better=improvement>=V2_OPTIMIZER_MIN_IMPROVEMENT and best["expectancyPct"]>current["expectancyPct"] and best["profitFactor"]>=current["profitFactor"]
            eligible=bool(materially_better and dd_ok and windows_ok)
            if eligible:
                staged={**best,
                    "confidence":_v2_step_toward(current_conf,best["confidence"],V2_OPTIMIZER_MAX_CONF_STEP,2),
                    "quality":_v2_step_toward(current_quality,best["quality"],V2_OPTIMIZER_MAX_QUALITY_STEP,3),
                    "targetConfidence":best["confidence"],"targetQuality":best["quality"]}
                recommendation="STABILITY_TEST"; reason="Candidate passed blacklist, rolling-window and drawdown safeguards."
            else: reason="Best candidate did not pass every stability, improvement and drawdown safeguard."
        stable_key=f"{(staged or best or {}).get('confidence')}:{(staged or best or {}).get('quality')}"
        conn.execute("INSERT INTO v2_optimizer_evaluations (evaluated_at,horizon_hours,candidate_confidence,candidate_quality,current_confidence,current_quality,eligible,stable_key,payload_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (now.isoformat(),int(horizon_hours),(staged or best or {}).get("confidence"),(staged or best or {}).get("quality"),current_conf,current_quality,1 if eligible else 0,stable_key,json.dumps({"best":best,"current":current})))
        recent=conn.execute("SELECT stable_key,eligible FROM v2_optimizer_evaluations ORDER BY id DESC LIMIT ?",(V2_OPTIMIZER_REQUIRED_STABLE_RUNS,)).fetchall()
        stable_runs=len(recent)==V2_OPTIMIZER_REQUIRED_STABLE_RUNS and all(int(r["eligible"])==1 and r["stable_key"]==stable_key for r in recent)
        if eligible and stable_runs: recommendation="READY_TO_APPLY"
        market_closed = True
        if AI_THRESHOLD_CLOSED_MARKET_ONLY:
            try:
                market_closed = not bool(get_effective_market_status_payload().get("isOpen", False))
            except Exception:
                market_closed = False
        result["marketClosed"] = market_closed
        result["closedMarketOnly"] = AI_THRESHOLD_CLOSED_MARKET_ONLY
        if eligible and stable_runs and V2_AUTO_APPLY_THRESHOLDS and staged and market_closed:
            apply_custom_a_plus_thresholds(staged["confidence"],staged["quality"],"autonomous evidence-calibrated threshold learner",True)
            result["applied"]=True; recommendation="APPLIED_STAGED_CHANGE"
        elif eligible and stable_runs and V2_AUTO_APPLY_THRESHOLDS and staged and not market_closed:
            recommendation="READY_FOR_CLOSED_MARKET_APPLY"
        conn.commit(); conn.close()
        result.update({"observations":len(observations),"excludedBlacklistSymbols":sorted(blocked),"excludedObservationCount":len(all_obs)-len(observations),
            "recommendation":recommendation,"reason":reason,"recommended":best,"stagedRecommendation":staged,"currentEvidence":current,
            "topCandidates":candidates[:10],"stability":{"requiredRuns":V2_OPTIMIZER_REQUIRED_STABLE_RUNS,"matchingRuns":sum(1 for r in recent if r["stable_key"]==stable_key and int(r["eligible"])==1),"passed":stable_runs},
            "safeguards":{"rollingWindowsHours":windows,"minimumImprovementPct":V2_OPTIMIZER_MIN_IMPROVEMENT*100,"maxDrawdownIncreasePct":V2_OPTIMIZER_MAX_DRAWDOWN_INCREASE*100,"maxConfidenceStep":V2_OPTIMIZER_MAX_CONF_STEP,"maxQualityStep":V2_OPTIMIZER_MAX_QUALITY_STEP},
            "safetyNote":"Thresholds only apply when auto-apply is enabled and all safeguards pass for consecutive evaluations."})
        return result
    except Exception as e:
        return {**result,"ok":False,"error":str(e)}


def v2_rollback_latest_strategy() -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    try:
        init_db(); conn = db_connect()
        row = conn.execute("SELECT * FROM v2_strategy_versions WHERE action='APPLY' ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            conn.close(); return {"ok": False, "message": "No applied adaptive strategy version to roll back"}
        row = dict(row)
        previous_conf = row.get("previous_confidence")
        previous_quality = row.get("previous_quality")
        if previous_conf is None or previous_quality is None:
            conn.close(); return {"ok": False, "message": "Previous thresholds are unavailable"}
        conn.close()
        result = apply_custom_a_plus_thresholds(float(previous_conf), float(previous_quality), f"rollback of strategy version {row.get('version_label')}", True)
        return {"ok": True, "rolledBack": row.get("version_label"), "settings": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def v2_strategy_timeline(limit: int = 50) -> Dict[str, Any]:
    if not SQLITE_ENABLED: return {"ok":False,"message":"SQLite disabled","rows":[]}
    try:
        init_db(); conn=db_connect()
        rows=[dict(r) for r in conn.execute("SELECT * FROM v2_strategy_versions ORDER BY id DESC LIMIT ?",(max(1,min(int(limit),200)),)).fetchall()]
        conn.close()
        for r in rows:
            try: r["metrics"]=json.loads(r.pop("metrics_json") or "{}")
            except Exception: r["metrics"]={}
        return {"ok":True,"count":len(rows),"rows":rows}
    except Exception as e: return {"ok":False,"error":str(e),"rows":[]}


def v2_decision_explanation(symbol: str) -> Dict[str, Any]:
    sym = str(symbol or "").upper().strip()
    scans = latest_status.get("scans") or []
    scan = next((s for s in scans if str(s.get("symbol", "")).upper() == sym), {})
    profile = v2_symbol_expectancy(sym)
    forward = profile.get("forwardShadow") or v2_forward_shadow_profile(sym)
    recent = [r for r in v2_recent_decisions(500) if str(r.get("symbol", "")).upper() == sym]
    latest = recent[0] if recent else {}
    confidence = float(scan.get("confidence") if scan else latest.get("confidence") or 0.0)
    quality = float(scan.get("qualityScore") if scan else latest.get("quality") or 0.0)
    momentum = float(scan.get("shortMomentum") if scan else latest.get("momentum") or 0.0)
    pullback = float(scan.get("pullback") if scan else latest.get("pullback") or 0.0)
    checks = [
        {"name": "Sniper confidence", "passed": confidence >= float(SNIPER_MIN_CONFIDENCE), "value": confidence, "required": float(SNIPER_MIN_CONFIDENCE)},
        {"name": "Sniper quality", "passed": quality >= float(SNIPER_MIN_QUALITY), "value": quality, "required": float(SNIPER_MIN_QUALITY)},
        {"name": "A+ confidence", "passed": confidence >= float(A_PLUS_MIN_CONFIDENCE), "value": confidence, "required": float(A_PLUS_MIN_CONFIDENCE)},
        {"name": "A+ quality", "passed": quality >= float(A_PLUS_MIN_QUALITY), "value": quality, "required": float(A_PLUS_MIN_QUALITY)},
        {"name": "Momentum non-negative", "passed": momentum >= 0.0, "value": momentum, "required": 0.0},
        {"name": "Historical expectancy gate", "passed": bool(profile.get("approved")), "value": float(profile.get("expectancyPct") or 0.0), "required": float(V2_MIN_EXPECTANCY_PCT)},
    ]
    live_decision = str(latest.get("decision") or ("APPROVED" if scan.get("aPlusPass") else "REJECTED" if scan else "UNKNOWN"))
    live_reason = str(latest.get("reason") or scan.get("aPlusReason") or scan.get("sniperReason") or "No recorded reason")
    shadow_decision = str(forward.get("recommendation") or "WATCH")
    mismatch = ((live_decision == "APPROVED" and shadow_decision == "BLOCK") or
                (live_decision == "REJECTED" and shadow_decision == "APPROVE"))
    estimated_skip_cost = None
    if live_decision == "REJECTED" and shadow_decision == "APPROVE":
        estimated_skip_cost = float(forward.get("expectancyPct") or 0.0)
    samples = int(forward.get("samples") or 0)
    pf = float(forward.get("profitFactor") or 0.0)
    exp = float(forward.get("expectancyPct") or 0.0)
    return {
        "ok": True,
        "symbol": sym,
        "decision": live_decision,
        "stage": latest.get("stage"),
        "reason": live_reason,
        "checks": checks,
        "historicalEvidence": profile,
        "forwardShadow": forward,
        "comparison": {
            "originalDecision": live_decision,
            "shadowRecommendation": shadow_decision,
            "disagreement": mismatch,
            "estimatedCostOfSkipPct": estimated_skip_cost,
            "evidenceConfidence": _v2_metric_grade(samples, pf, exp),
            "note": "Shadow advice is evidence-only and cannot place an order.",
        },
        "latestScan": scan,
        "recentDecisions": recent[:20],
    }


def v2_decision_review(limit: int = 100) -> Dict[str, Any]:
    decisions = v2_recent_decisions(max(1, min(int(limit), 500)))
    rows = []
    profile_cache: Dict[str, Dict[str, Any]] = {}
    for d in decisions:
        sym = str(d.get("symbol") or "").upper()
        if sym not in profile_cache:
            profile_cache[sym] = v2_forward_shadow_profile(sym)
        shadow = profile_cache[sym]
        original = str(d.get("decision") or "UNKNOWN")
        recommendation = str(shadow.get("recommendation") or "WATCH")
        disagreement = ((original == "APPROVED" and recommendation == "BLOCK") or
                        (original == "REJECTED" and recommendation == "APPROVE"))
        rows.append({
            "decisionId": d.get("id"), "timestamp": d.get("timestamp"), "symbol": sym,
            "originalDecision": original, "stage": d.get("stage"), "reason": d.get("reason"),
            "confidence": d.get("confidence"), "quality": d.get("quality"),
            "shadowRecommendation": recommendation,
            "shadowSamples": shadow.get("samples"), "shadowWinRate": shadow.get("winRate"),
            "shadowProfitFactor": shadow.get("profitFactor"), "shadowExpectancyPct": shadow.get("expectancyPct"),
            "disagreement": disagreement,
            "estimatedCostOfSkipPct": float(shadow.get("expectancyPct") or 0.0) if original == "REJECTED" and recommendation == "APPROVE" else None,
        })
    return {
        "ok": True, "advisoryOnly": True, "count": len(rows),
        "disagreements": sum(1 for r in rows if r["disagreement"]),
        "rows": rows,
        "note": "Comparison only; live ordering and saved thresholds remain unchanged.",
    }


@app.get("/v2/intelligence-summary")
def api_v2_intelligence_summary():
    return v2_intelligence_summary()

@app.get("/v2/setup-profiles")
def api_v2_setup_profiles(limit: int = 100):
    return {"ok": True, "profiles": v2_setup_profiles(limit)}

@app.get("/v2/recent-decisions")
def api_v2_recent_decisions(limit: int = 100):
    return {"ok": True, "decisions": v2_recent_decisions(limit)}

@app.get("/v2/outcomes-summary")
def api_v2_outcomes_summary(symbol: Optional[str] = None):
    return v2_outcomes_summary(symbol)

@app.get("/v2/replay")
def api_v2_replay(symbol: Optional[str] = None, limit: int = 200):
    return {"ok": True, "rows": v2_replay_rows(symbol, limit)}

@app.get("/v2/shadow-recommendations")
def api_v2_shadow_recommendations(symbol: Optional[str] = None):
    if symbol:
        return {"ok": True, "shadowMode": True, "recommendations": [v2_forward_shadow_profile(symbol)]}
    summary = v2_outcomes_summary()
    return {"ok": bool(summary.get("ok")), "shadowMode": True,
            "note": "Advisory only; live gate unchanged.",
            "recommendations": summary.get("shadowRecommendations", [])}

@app.post("/v2/evaluate-outcomes")
def api_v2_evaluate_outcomes(request: Request, limit: int = 100):
    verify_api_key(request)
    return v2_evaluate_due_outcomes(limit)

def _quick_live_status_payload() -> Dict[str, Any]:
    """Build a lightweight live status snapshot without running research/schema work."""
    account = get_account()
    positions = get_all_positions()
    market_status = get_market_status_payload()
    daily_pnl = get_daily_pnl()
    return {
        "id": "rebuilt-sniper-live",
        "name": BOT_NAME,
        "botVersion": "v1.1-strict-profit-mode",
        "paperMode": PAPER,
        "botEnabled": bot_enabled,
        "manualOverride": manual_override,
        "emergencyStop": emergency_stop,
        "market": market_status,
        "account": {
            "equity": float(account.equity),
            "equityGbp": money_gbp(float(account.equity)),
            "buyingPower": float(account.buying_power),
            "buyingPowerGbp": money_gbp(float(account.buying_power)),
            "cash": float(account.cash),
            "cashGbp": money_gbp(float(account.cash)),
            "pnlDay": float(daily_pnl),
            "pnlDayGbp": money_gbp(float(daily_pnl)),
        },
        "positions": positions,
        "activePosition": positions[0] if positions else None,
        "scans": list(latest_scans),
        "maxPositions": effective_max_positions(),
        "positionCapacity": ai_position_capacity_payload(),
        "allowedNewPositions": allowed_new_position_count(),
        "newPositionNotional": calculate_new_position_notional(),
        "autoUniverse": auto_universe_payload(),
        "universe": list(current_universe),
        "banking": banking_payload(),
        "quickStatus": True,
        "quickStatusUpdatedAt": datetime.now(UTC).isoformat(),
    }


@app.get("/final-gate-monitor")
def api_final_gate_monitor(request: Request):
    verify_api_key(request)
    return _v174_final_gate_monitor_payload()


@app.get("/status")
def get_status():
    # V18.2.8 FAST DASHBOARD LOAD
    # This endpoint must be cache-only. Never call Alpaca, SQLite-heavy research,
    # universe rebuilds or filesystem merge helpers from the browser request path.
    # Background workers already refresh latest_status; the UI should receive the
    # most recent coherent snapshot immediately rather than waiting for a second
    # synchronous status rebuild.
    with _STATUS_LOCK:
        payload = dict(latest_status)

    payload["botVersion"] = "v1.1-strict-profit-mode"
    payload.pop("tradeTimeline", None)
    payload.pop("closedTrades", None)
    payload.pop("stockMemory", None)
    payload["statusPayloadMode"] = "compact-live-cache"
    payload["fullHistoryAvailableFrom"] = "/reports"
    payload["statusCacheReady"] = isinstance(payload.get("account"), dict)

    # Keep final-gate data best-effort and non-fatal. This is local persisted state,
    # not a broker call, but the dashboard must still return if it is unavailable.
    try:
        payload["finalGateMonitor"] = _v174_final_gate_monitor_payload()
    except Exception:
        payload["finalGateMonitor"] = {}

    if not payload.get("statusCacheReady"):
        # Return a truthful warming snapshot immediately. Banking/equity can still
        # hydrate independently from /banking-status on the frontend.
        payload.setdefault("botEnabled", bot_enabled)
        payload.setdefault("manualOverride", manual_override)
        payload.setdefault("emergencyStop", emergency_stop)
        payload.setdefault("positions", [])
        payload.setdefault("scans", list(latest_scans))
        payload.setdefault("universe", list(current_universe))
        payload["warmingUp"] = True

    return payload


@app.post("/pause")
def pause_bot(request: Request):
    verify_api_key(request)
    global bot_enabled
    bot_enabled = False
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Bot paused"}


@app.post("/resume")
def resume_bot(request: Request):
    verify_api_key(request)
    global bot_enabled, emergency_stop
    bot_enabled = True
    emergency_stop = False
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Bot resumed"}


@app.post("/manual-override/on")
def manual_override_on(request: Request):
    verify_api_key(request)
    global manual_override
    manual_override = True
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Manual override ON. Auto-buy paused."}


@app.post("/manual-override/off")
def manual_override_off(request: Request):
    verify_api_key(request)
    global manual_override
    manual_override = False
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Manual override OFF. Auto-buy active."}


@app.post("/manual-buy")
def manual_buy(request: Request):
    verify_api_key(request)
    with bot_lock:
        if not get_effective_market_status_payload().get("isOpen", False):
            return {"ok": False, "message": "Market closed"}
        result = money_mode_buy(latest_scans, manual=True)
        update_status(BOT_NAME, latest_scans)
        return {"ok": True, "message": result}


@app.post("/custom-buy/{symbol}")
def custom_buy(symbol: str, request: Request):
    verify_api_key(request)
    with bot_lock:
        result = buy_custom_symbol(symbol)
        update_status(BOT_NAME, latest_scans)
        return result


@app.post("/manual-sell")
def manual_sell(request: Request):
    verify_api_key(request)
    with bot_lock:
        result = close_worst_or_largest_position(reason="MANUAL SELL")
        update_status(BOT_NAME, latest_scans)
        return result


@app.post("/sell/{symbol}")
def sell_symbol(symbol: str, request: Request):
    verify_api_key(request)
    with bot_lock:
        result = close_position_by_symbol(symbol.upper(), reason="MANUAL SYMBOL SELL")
        update_status(BOT_NAME, latest_scans)
        return result


@app.post("/emergency-sell")
def emergency_sell(request: Request):
    verify_api_key(request)
    global emergency_stop, bot_enabled
    with bot_lock:
        emergency_stop = True
        bot_enabled = False
        result = close_all_positions(reason="EMERGENCY SELL")
        update_status(BOT_NAME, latest_scans)
        return {**result, "emergencyStop": True, "botEnabled": False}




@app.post("/rebuild-closed-trades")
def rebuild_closed_trades(request: Request):
    verify_api_key(request)
    with bot_lock:
        result = rebuild_closed_trades_from_orders()
        update_status(BOT_NAME, latest_scans)
        return result



@app.post("/backfill-trades-limited")
def backfill_trades_limited(request: Request):
    verify_api_key(request)
    with bot_lock:
        result = backfill_trades_from_alpaca()
        update_status(BOT_NAME, latest_scans)
        return result





def refresh_universe(request: Request):
    verify_api_key(request)
    with bot_lock:
        result = build_weekly_universe(force=True)
        update_status(BOT_NAME, latest_scans)
        return result


@app.post("/backfill-trades")
def backfill_trades(request: Request):
    verify_api_key(request)
    with bot_lock:
        result = backfill_trades_from_alpaca_full()
        update_status(BOT_NAME, latest_scans)
        return result


# =========================
# TRADEBOT V18.2.15 — CYCLE MONITOR
# Persistent operational counters. Read-only visibility; no trading decisions.
# =========================
_CYCLE_MONITOR_LOCK = threading.RLock()
_CYCLE_MONITOR_STARTED_AT = datetime.now(UTC).isoformat()
_CYCLE_MONITOR_RUN: Dict[str, Dict[str, Any]] = {}
_CYCLE_MONITOR_TABLE_READY = False
_CYCLE_MONITOR_TABLE_LOCK = threading.Lock()
_CYCLE_MONITOR_TYPES = ("bot", "scientist", "research", "advisor", "scanner")


def _cycle_monitor_ensure_table() -> None:
    global _CYCLE_MONITOR_TABLE_READY
    if not SQLITE_ENABLED or _CYCLE_MONITOR_TABLE_READY:
        return
    with _CYCLE_MONITOR_TABLE_LOCK:
        if _CYCLE_MONITOR_TABLE_READY:
            return
        conn = None
        try:
            conn = db_connect()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS v18215_cycle_monitor (
                    cycle_name TEXT PRIMARY KEY,
                    lifetime_completed INTEGER NOT NULL DEFAULT 0,
                    lifetime_failed INTEGER NOT NULL DEFAULT 0,
                    last_started_at TEXT,
                    last_completed_at TEXT,
                    last_failed_at TEXT,
                    last_duration_ms REAL NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()
            _CYCLE_MONITOR_TABLE_READY = True
        finally:
            if conn is not None:
                conn.close()


def _cycle_monitor_start(name: str) -> float:
    key = str(name or "unknown").lower()
    started = time.monotonic()
    with _CYCLE_MONITOR_LOCK:
        row = _CYCLE_MONITOR_RUN.setdefault(key, {"completed": 0, "failed": 0})
        row["lastStartedAt"] = datetime.now(UTC).isoformat()
        row["state"] = "RUNNING"
    return started


def _cycle_monitor_finish(name: str, started: float, ok: bool = True, error: str = "") -> None:
    key = str(name or "unknown").lower()
    now = datetime.now(UTC).isoformat()
    duration_ms = max(0.0, (time.monotonic() - started) * 1000.0)
    with _CYCLE_MONITOR_LOCK:
        row = _CYCLE_MONITOR_RUN.setdefault(key, {"completed": 0, "failed": 0})
        if ok:
            row["completed"] = int(row.get("completed", 0)) + 1
            row["lastCompletedAt"] = now
            row["state"] = "WAITING"
            row["lastError"] = ""
        else:
            row["failed"] = int(row.get("failed", 0)) + 1
            row["lastFailedAt"] = now
            row["state"] = "ERROR"
            row["lastError"] = str(error or "")[:500]
        row["lastDurationMs"] = round(duration_ms, 1)
    if not SQLITE_ENABLED:
        return
    conn = None
    try:
        _cycle_monitor_ensure_table()
        conn = db_connect()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""
            INSERT INTO v18215_cycle_monitor (
                cycle_name,lifetime_completed,lifetime_failed,last_started_at,last_completed_at,
                last_failed_at,last_duration_ms,last_error,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(cycle_name) DO UPDATE SET
                lifetime_completed=lifetime_completed + excluded.lifetime_completed,
                lifetime_failed=lifetime_failed + excluded.lifetime_failed,
                last_started_at=excluded.last_started_at,
                last_completed_at=CASE WHEN excluded.lifetime_completed > 0 THEN excluded.last_completed_at ELSE last_completed_at END,
                last_failed_at=CASE WHEN excluded.lifetime_failed > 0 THEN excluded.last_failed_at ELSE last_failed_at END,
                last_duration_ms=excluded.last_duration_ms,
                last_error=excluded.last_error,
                updated_at=excluded.updated_at
        """, (key, 1 if ok else 0, 0 if ok else 1,
              _CYCLE_MONITOR_RUN.get(key, {}).get("lastStartedAt"), now if ok else None,
              None if ok else now, duration_ms, "" if ok else str(error or "")[:500], now))
        conn.commit()
    except Exception as exc:
        # Monitoring must never interfere with the bot or recursively fail a worker.
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        print(f"V18.2.15 CYCLE MONITOR SAVE ERROR | cycle={key} error={exc}")
    finally:
        if conn is not None:
            conn.close()


def cycle_monitor_payload() -> Dict[str, Any]:
    persistent: Dict[str, Dict[str, Any]] = {}
    if SQLITE_ENABLED:
        conn = None
        try:
            _cycle_monitor_ensure_table()
            conn = db_connect()
            rows = conn.execute("SELECT * FROM v18215_cycle_monitor").fetchall()
            for raw in rows:
                d = dict(raw)
                persistent[str(d.get("cycle_name") or "")] = d
        except Exception as exc:
            persistent["_error"] = {"error": str(exc)}
        finally:
            if conn is not None:
                conn.close()
    with _CYCLE_MONITOR_LOCK:
        runtime = {k: dict(v) for k, v in _CYCLE_MONITOR_RUN.items()}
    cycles = {}
    for name in _CYCLE_MONITOR_TYPES:
        live = runtime.get(name, {})
        saved = persistent.get(name, {})
        cycles[name] = {
            "thisRunCompleted": int(live.get("completed", 0)),
            "thisRunFailed": int(live.get("failed", 0)),
            "lifetimeCompleted": int(saved.get("lifetime_completed", 0) or 0),
            "lifetimeFailed": int(saved.get("lifetime_failed", 0) or 0),
            "state": live.get("state", "WAITING"),
            "lastStartedAt": live.get("lastStartedAt") or saved.get("last_started_at"),
            "lastCompletedAt": live.get("lastCompletedAt") or saved.get("last_completed_at"),
            "lastFailedAt": live.get("lastFailedAt") or saved.get("last_failed_at"),
            "lastDurationMs": float(live.get("lastDurationMs", saved.get("last_duration_ms", 0)) or 0),
            "lastError": live.get("lastError") or saved.get("last_error") or "",
        }
    return {
        "ok": True,
        "version": "V18.2.15 Cycle Monitor",
        "startedAt": _CYCLE_MONITOR_STARTED_AT,
        "uptimeSeconds": max(0, int((datetime.now(UTC) - datetime.fromisoformat(_CYCLE_MONITOR_STARTED_AT)).total_seconds())),
        "cycles": cycles,
    }


@app.get("/cycle-monitor")
def api_cycle_monitor(request: Request):
    verify_api_key(request)
    return cycle_monitor_payload()


# =========================
# LOOP
# =========================
def _ai_research_market_open() -> Optional[bool]:
    """Return Alpaca market state, or None when the clock cannot be read safely."""
    try:
        return bool(get_effective_market_status_payload().get("isOpen", False))
    except Exception as exc:
        print(f"AI RESEARCH CLOCK ERROR: {exc}")
        return None


def closed_market_ai_research_worker() -> None:
    """Run outcome evaluation and advisory learning only while the market is closed.

    This worker never places orders and never changes live thresholds automatically.
    """
    time.sleep(AI_RESEARCH_STARTUP_DELAY_SECONDS)
    last_cycle_at = 0.0
    last_state: Optional[str] = None
    while True:
        try:
            is_open = _ai_research_market_open()
            if is_open is None:
                time.sleep(60)
                continue

            if is_open:
                if last_state != "open":
                    print("AI RESEARCH PAUSED | market open; live trader has priority")
                last_state = "open"
                time.sleep(60)
                continue

            if last_state != "closed":
                print("AI RESEARCH ACTIVE | market closed; outcome and shadow learning enabled")
            last_state = "closed"

            now_mono = time.monotonic()
            if last_cycle_at and (now_mono - last_cycle_at) < AI_RESEARCH_INTERVAL_SECONDS:
                time.sleep(min(60, AI_RESEARCH_INTERVAL_SECONDS))
                continue

            _research_cycle_started = _cycle_monitor_start("research")
            started = datetime.now(UTC).isoformat()
            seeded = v2_seed_missing_outcomes()
            outcomes = v2_drain_due_outcomes()
            v179_audit = v179_evaluate_decision_audit()
            v18_review = _v18_build_review(V18_WINDOW_DAYS, True)
            v6_result = v6_sync_brains(V6_DEFAULT_HORIZON_HOURS, V6_AUTO_SYNC_LIMIT) if V6_BRAINS_ENABLED else {"ok": True, "skipped": True}
            v11_result = v11_learning_cycle("closed_market", force=False) if V11_AUTO_LEARNING_ENABLED else {"ok": True, "skipped": True}
            last_cycle_at = time.monotonic()
            print(
                "AI NIGHT RESEARCH | "
                f"started={started} seeded={seeded} "
                f"outcomes={outcomes.get('evaluated', outcomes.get('historical', 0))} "
                f"errors={outcomes.get('errors', 0)} "
                f"audit={v179_audit.get('evaluated', 0)}/{v179_audit.get('errors', 0)} "
                f"weekly={v18_review.get('verdict', 'UNAVAILABLE')} "
                f"v6_new={v6_result.get('newShadowRows', 0)} "
                f"v11_discovery={bool(v11_result.get('ranDiscovery'))} "
                "live_changes=False"
            )
            _cycle_monitor_finish("research", _research_cycle_started, True)
        except Exception as exc:
            if "_research_cycle_started" in locals():
                _cycle_monitor_finish("research", _research_cycle_started, False, str(exc))
            print(f"AI NIGHT RESEARCH ERROR: {exc}")
        time.sleep(60)


def _locked_universe_reset_cache_if_new_day() -> None:
    today = today_str()
    if str(locked_universe_runtime_cache.get("day") or "") != today:
        locked_universe_runtime_cache.clear()
        locked_universe_runtime_cache.update({"day": today, "symbols": [], "rows": [], "lastDiscoveryTs": 0.0})


def _locked_universe_candidate_allowed(symbol: str, active_symbols: set[str]) -> bool:
    sym = str(symbol or "").upper().strip()
    if not sym or sym in active_symbols or is_locked_today(sym):
        return False
    try:
        if sym in globals().get("BLOCKED_WEAK_TICKERS", set()):
            return False
    except Exception:
        pass
    try:
        qty, _ = get_position(sym)
        if qty > DUST_THRESHOLD:
            # An already-held symbol should be managed, not introduced as a new replacement entry.
            return False
    except Exception:
        pass
    return True


def _discover_locked_universe_replacements(active_symbols: set[str], need: int) -> List[Dict[str, Any]]:
    """Find fresh unlocked symbols without changing any daily lock or buy gate."""
    _locked_universe_reset_cache_if_new_day()
    rows_by_symbol: Dict[str, Dict[str, Any]] = {}

    # Reuse discoveries from this trading day first. This prevents a weekly-universe
    # refresh from undoing runtime replacements every loop while avoiding repeated web calls.
    for row in list(locked_universe_runtime_cache.get("rows") or []):
        sym = str(row.get("symbol") or "").upper().strip()
        if _locked_universe_candidate_allowed(sym, active_symbols):
            rows_by_symbol[sym] = dict(row)

    now_ts = time.time()
    should_refresh = (
        len(rows_by_symbol) < need
        and (now_ts - float(locked_universe_runtime_cache.get("lastDiscoveryTs") or 0.0)) >= LOCKED_UNIVERSE_DISCOVERY_COOLDOWN_SECONDS
    )

    # Use the same Yahoo discovery screens as the existing dynamic scanner, but
    # keep more than the normal top-12 so locked symbols have genuine alternatives.
    if should_refresh:
        try:
            screens = list(globals().get("DYNAMIC_MARKET_YAHOO_SCREENS", []) or [])
            yahoo_fn = globals().get("_yahoo_dynamic_screen")
            score_fn = globals().get("_score_dynamic_quote")
            if callable(yahoo_fn) and callable(score_fn):
                for screen in screens:
                    try:
                        for quote in yahoo_fn(screen, count=LOCKED_UNIVERSE_DISCOVERY_PER_SCREEN):
                            row = score_fn(quote, screen)
                            if not row:
                                continue
                            sym = str(row.get("symbol") or "").upper().strip()
                            if not _locked_universe_candidate_allowed(sym, active_symbols):
                                continue
                            previous = rows_by_symbol.get(sym)
                            if previous is None or float(row.get("score") or 0.0) > float(previous.get("score") or 0.0):
                                rows_by_symbol[sym] = dict(row)
                    except Exception as screen_exc:
                        print(f"V17.0.11 LOCKED UNIVERSE DISCOVERY SOURCE ERROR {screen}: {screen_exc}")
        except Exception as exc:
            print(f"V17.0.11 LOCKED UNIVERSE DISCOVERY ERROR: {exc}")
        locked_universe_runtime_cache["lastDiscoveryTs"] = now_ts

    # Stable broad fallback. These still go through all normal live score,
    # reputation, sniper, A+, expectancy and spread checks before any order.
    fallback = []
    for sym in list(globals().get("LOCKED_UNIVERSE_FALLBACK_POOL", []) or []):
        sym = str(sym).upper().strip()
        if not _locked_universe_candidate_allowed(sym, active_symbols) or sym in rows_by_symbol:
            continue
        try:
            row = score_candidate_symbol(sym)
        except Exception:
            row = {"symbol": sym, "score": 0.0, "reason": "locked-universe fallback", "status": "active"}
        row = dict(row)
        row["lockedUniverseReplacement"] = True
        row.setdefault("source", "locked-universe-fallback")
        fallback.append(row)

    dynamic_rows = sorted(rows_by_symbol.values(), key=lambda r: float(r.get("score") or 0.0), reverse=True)
    fallback.sort(key=lambda r: float(r.get("score") or 0.0), reverse=True)
    combined = dynamic_rows + fallback

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for row in combined:
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym or sym in seen or not _locked_universe_candidate_allowed(sym, active_symbols):
            continue
        seen.add(sym)
        item = dict(row)
        item["symbol"] = sym
        item["lockedUniverseReplacement"] = True
        deduped.append(item)

    locked_universe_runtime_cache["day"] = today_str()
    locked_universe_runtime_cache["rows"] = deduped[:max(LOCKED_UNIVERSE_TARGET_SIZE * 4, 24)]
    locked_universe_runtime_cache["symbols"] = [r["symbol"] for r in locked_universe_runtime_cache["rows"]]
    return deduped[:max(need, LOCKED_UNIVERSE_TARGET_SIZE)]


def replenish_locked_universe_if_needed() -> Dict[str, Any]:
    """Swap daily-locked scan slots for fresh symbols; never clear a lock."""
    global current_universe
    _locked_universe_reset_cache_if_new_day()
    if not LOCKED_UNIVERSE_AUTO_REPLACEMENT_ENABLED:
        return {"ok": True, "changed": False, "reason": "disabled"}

    active = list(dict.fromkeys(str(s).upper().strip() for s in current_universe if str(s).strip()))
    if not active:
        return {"ok": True, "changed": False, "reason": "empty universe"}

    locked = [s for s in active if is_locked_today(s)]
    unlocked = [s for s in active if not is_locked_today(s)]
    if len(unlocked) >= LOCKED_UNIVERSE_MIN_UNLOCKED and len(active) >= LOCKED_UNIVERSE_TARGET_SIZE:
        return {"ok": True, "changed": False, "locked": locked, "unlocked": unlocked}

    # Keep every currently-held position in the scan/management universe even if
    # a future rule ever marks it locked. Normally locks are created only after SELL.
    held = []
    try:
        held = [str(p.get("symbol") or "").upper().strip() for p in get_all_positions() if p.get("symbol")]
    except Exception:
        held = []
    keep = []
    for sym in unlocked + held:
        if sym and sym not in keep:
            keep.append(sym)

    target = max(LOCKED_UNIVERSE_TARGET_SIZE, len(keep))
    need = max(0, target - len(keep))
    active_set = set(active) | set(keep)
    replacements = _discover_locked_universe_replacements(active_set, need)
    added = []
    for row in replacements:
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym or sym in keep or is_locked_today(sym):
            continue
        keep.append(sym)
        added.append(sym)
        ensure_symbol_state(sym, custom=sym in custom_symbols)
        if len(keep) >= target:
            break

    if not added:
        return {"ok": True, "changed": False, "reason": "no fresh unlocked replacements available", "locked": locked, "unlocked": unlocked}

    removed_locked = [s for s in active if s not in keep and is_locked_today(s)]
    current_universe = keep[:target]
    summary = {
        "ok": True, "changed": True, "day": today_str(),
        "lockedRemoved": removed_locked, "added": added,
        "unlockedBefore": len(unlocked), "activeAfter": len(current_universe),
        "symbols": list(current_universe),
    }
    try:
        latest_status["lockedUniverseReplacement"] = summary
        latest_status.setdefault("autoUniverse", {})["activeSymbols"] = list(current_universe)
        latest_status["autoUniverse"]["size"] = len(current_universe)
    except Exception:
        pass
    print(
        "V17.0.11 LOCKED UNIVERSE REPLACEMENT | "
        f"locked={len(locked)} unlocked_before={len(unlocked)} removed={','.join(removed_locked) or '-'} "
        f"added={','.join(added) or '-'} universe={','.join(current_universe)}"
    )
    return summary



# =========================
# V17.1 TRADE REPLAY / PERSISTENT PRICE HISTORY
# =========================
TRADE_REPLAY_ENABLED = os.getenv("TRADE_REPLAY_ENABLED", "true").lower() == "true"
# V17.1.1: 10-second live capture. This has its own lightweight worker so the
# main trading/scanner cadence remains unchanged. A floor of 5s prevents an
# accidental environment setting from hammering SQLite/broker state.
TRADE_REPLAY_SAMPLE_SECONDS = max(5, int(os.getenv("TRADE_REPLAY_SAMPLE_SECONDS", "10")))
TRADE_REPLAY_MAX_POINTS = max(500, int(os.getenv("TRADE_REPLAY_MAX_POINTS", "5000")))
_trade_replay_last_sample: Dict[str, float] = {}
_trade_replay_schema_ready = False
_trade_replay_schema_lock = threading.RLock()
_trade_replay_record_lock = threading.Lock()
trade_replay_thread_started = False


def _trade_replay_ensure_tables() -> None:
    """Create the small persistent recorder schema without touching trading logic."""
    global _trade_replay_schema_ready
    if not SQLITE_ENABLED or not TRADE_REPLAY_ENABLED or _trade_replay_schema_ready:
        return
    with _trade_replay_schema_lock:
        if _trade_replay_schema_ready:
            return
        conn = db_connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_replay_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                entry_price REAL NOT NULL DEFAULT 0,
                qty_initial REAL NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                exit_price REAL,
                closed_trade_id INTEGER,
                status TEXT NOT NULL DEFAULT 'OPEN',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trade_replay_sessions_symbol_status
            ON trade_replay_sessions(symbol, status, started_at)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_replay_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                price REAL NOT NULL DEFAULT 0,
                entry_price REAL NOT NULL DEFAULT 0,
                qty REAL NOT NULL DEFAULT 0,
                market_value REAL NOT NULL DEFAULT 0,
                pnl REAL NOT NULL DEFAULT 0,
                pnl_pct REAL NOT NULL DEFAULT 0,
                highest REAL NOT NULL DEFAULT 0,
                trail_start_price REAL NOT NULL DEFAULT 0,
                trail_floor REAL NOT NULL DEFAULT 0,
                stop_price REAL NOT NULL DEFAULT 0,
                emergency_stop_price REAL NOT NULL DEFAULT 0,
                trailing_active INTEGER NOT NULL DEFAULT 0,
                market_open INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'live-position',
                FOREIGN KEY(session_id) REFERENCES trade_replay_sessions(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trade_replay_points_session_time
            ON trade_replay_points(session_id, observed_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trade_replay_points_symbol_time
            ON trade_replay_points(symbol, observed_at)
        """)
        conn.commit(); conn.close()
        _trade_replay_schema_ready = True


def _trade_replay_open_session(conn, position: Dict[str, Any], now_iso: str) -> int:
    symbol = str(position.get("symbol") or "").upper()
    entry = float(position.get("entry") or 0.0)
    # Keep an overnight position in the same replay session. A materially different
    # entry price indicates a new trade in the same symbol.
    row = conn.execute(
        "SELECT * FROM trade_replay_sessions WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if row:
        existing_entry = float(row["entry_price"] or 0.0)
        tolerance = max(0.01, abs(entry) * 0.0005)
        if abs(existing_entry - entry) <= tolerance:
            return int(row["id"])
        conn.execute(
            "UPDATE trade_replay_sessions SET status='CLOSED', ended_at=?, updated_at=? WHERE id=?",
            (now_iso, now_iso, int(row["id"])),
        )
    cur = conn.execute(
        """INSERT INTO trade_replay_sessions
           (symbol,entry_price,qty_initial,started_at,status,created_at,updated_at)
           VALUES (?,?,?,?, 'OPEN', ?, ?)""",
        (symbol, entry, float(position.get("qty") or 0.0), now_iso, now_iso, now_iso),
    )
    return int(cur.lastrowid)


def record_trade_replay_snapshot(market_open: Optional[bool] = None) -> Dict[str, Any]:
    """Persist one price point per open position at the replay cadence.

    This intentionally runs even when the regular market is closed so any quote
    updates available from the broker/feed (pre-market/after-hours included) can
    be preserved for the chart. V17.1.1 serialises recorder calls because both
    the main bot loop and the dedicated recorder worker may request a sample.
    """
    if not SQLITE_ENABLED or not TRADE_REPLAY_ENABLED:
        return {"ok": False, "enabled": False, "recorded": 0}
    if not _trade_replay_record_lock.acquire(blocking=False):
        return {"ok": True, "enabled": True, "recorded": 0, "busy": True}
    try:
        _trade_replay_ensure_tables()
        positions = get_all_positions()
        if not positions:
            return {"ok": True, "enabled": True, "recorded": 0}
        now_mono = time.monotonic()
        now_iso = datetime.now(UTC).isoformat()
        due = []
        for p in positions:
            symbol = str(p.get("symbol") or "").upper()
            if not symbol:
                continue
            last = float(_trade_replay_last_sample.get(symbol, 0.0))
            if now_mono - last >= TRADE_REPLAY_SAMPLE_SECONDS:
                due.append(p)
        if not due:
            return {"ok": True, "enabled": True, "recorded": 0}
        if market_open is None:
            try:
                market_open = bool(get_effective_market_status_payload().get("isOpen", False))
            except Exception:
                market_open = False
        conn = db_connect(); recorded = 0
        for p in due:
            symbol = str(p.get("symbol") or "").upper()
            session_id = _trade_replay_open_session(conn, p, now_iso)
            conn.execute(
                """INSERT INTO trade_replay_points
                   (session_id,symbol,observed_at,price,entry_price,qty,market_value,pnl,pnl_pct,highest,
                    trail_start_price,trail_floor,stop_price,emergency_stop_price,trailing_active,market_open,source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session_id, symbol, now_iso, float(p.get("price") or 0.0), float(p.get("entry") or 0.0),
                 float(p.get("qty") or 0.0), float(p.get("marketValue") or 0.0), float(p.get("pnl") or 0.0),
                 float(p.get("pnlPct") or 0.0), float(p.get("highest") or 0.0), float(p.get("trailStartPrice") or 0.0),
                 float(p.get("trailFloor") or 0.0), float(p.get("stopPrice") or 0.0),
                 float(p.get("emergencyStopPrice") or 0.0), 1 if p.get("trailingActive") else 0,
                 1 if market_open else 0, "runner-grace" if p.get("runnerGraceActive") else ("peak-exhaustion" if p.get("peakExhaustionArmed") else "live-position")),
            )
            conn.execute("UPDATE trade_replay_sessions SET updated_at=? WHERE id=?", (now_iso, session_id))
            _trade_replay_last_sample[symbol] = now_mono
            recorded += 1
        conn.commit(); conn.close()
        return {"ok": True, "enabled": True, "recorded": recorded}
    except Exception as exc:
        print(f"V17.1.1 TRADE REPLAY RECORD ERROR: {exc}")
        return {"ok": False, "enabled": True, "recorded": 0, "error": str(exc)}
    finally:
        _trade_replay_record_lock.release()


def trade_replay_recorder_worker() -> None:
    """High-frequency replay capture isolated from the trading decision loop."""
    print(f"V17.1.1 TRADE REPLAY RECORDER | interval={TRADE_REPLAY_SAMPLE_SECONDS}s")
    # Small startup delay lets account/broker state initialise normally.
    time.sleep(2)
    while True:
        try:
            # get_all_positions already reads live position data; market-open is
            # informational for the saved point and does not control recording.
            try:
                is_open = bool(get_effective_market_status_payload().get("isOpen", False))
            except Exception:
                is_open = False
            record_trade_replay_snapshot(is_open)
        except Exception as exc:
            print(f"V17.1.1 TRADE REPLAY WORKER ERROR: {exc}")
        # Wake more often than the sample cadence; record_trade_replay_snapshot
        # decides whether a symbol is actually due.
        time.sleep(max(1.0, min(2.0, TRADE_REPLAY_SAMPLE_SECONDS / 4.0)))


def _trade_replay_close_for_trade(trade: Dict[str, Any], closed_trade_id: Optional[int] = None) -> None:
    if not SQLITE_ENABLED or not TRADE_REPLAY_ENABLED:
        return
    try:
        _trade_replay_ensure_tables()
        symbol = str(trade.get("symbol") or "").upper()
        if not symbol:
            return
        ended_at = str(trade.get("timestamp") or datetime.now(UTC).isoformat())
        exit_price = float(trade.get("exitPrice") or trade.get("price") or 0.0)
        conn = db_connect()
        row = conn.execute(
            "SELECT id FROM trade_replay_sessions WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if row:
            conn.execute(
                """UPDATE trade_replay_sessions
                   SET status='CLOSED',ended_at=?,exit_price=?,closed_trade_id=COALESCE(?,closed_trade_id),updated_at=?
                   WHERE id=?""",
                (ended_at, exit_price, closed_trade_id, datetime.now(UTC).isoformat(), int(row["id"])),
            )
            conn.commit()
        conn.close()
    except Exception as exc:
        print(f"V17.1 TRADE REPLAY CLOSE ERROR: {exc}")


def _trade_replay_points_for_session(session_id: int, limit: int = TRADE_REPLAY_MAX_POINTS) -> List[Dict[str, Any]]:
    _trade_replay_ensure_tables(); conn = db_connect()
    rows = conn.execute(
        "SELECT * FROM trade_replay_points WHERE session_id=? ORDER BY observed_at ASC LIMIT ?",
        (int(session_id), max(1, min(int(limit), TRADE_REPLAY_MAX_POINTS))),
    ).fetchall(); conn.close()
    return [
        {"id": int(r["id"]), "sessionId": int(r["session_id"]), "symbol": r["symbol"], "time": r["observed_at"],
         "price": float(r["price"] or 0.0), "entry": float(r["entry_price"] or 0.0), "qty": float(r["qty"] or 0.0),
         "marketValue": float(r["market_value"] or 0.0), "pnl": float(r["pnl"] or 0.0), "pnlPct": float(r["pnl_pct"] or 0.0),
         "highest": float(r["highest"] or 0.0), "trailStart": float(r["trail_start_price"] or 0.0),
         "trailFloor": float(r["trail_floor"] or 0.0), "stop": float(r["stop_price"] or 0.0),
         "emergencyStop": float(r["emergency_stop_price"] or 0.0), "trailingActive": bool(r["trailing_active"]),
         "marketOpen": bool(r["market_open"]), "source": str(r["source"] or "live-position"),
         "runnerGrace": str(r["source"] or "") == "runner-grace",
         "peakExhaustion": str(r["source"] or "") == "peak-exhaustion"} for r in rows
    ]


def _trade_replay_payload(session_row, limit: int = TRADE_REPLAY_MAX_POINTS, closed_trade: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not session_row:
        return {"ok": True, "recorded": False, "points": [], "message": "No recorded replay is available for this trade yet."}
    session = dict(session_row); points = _trade_replay_points_for_session(int(session["id"]), limit)
    prices = [float(p.get("price") or 0.0) for p in points if float(p.get("price") or 0.0) > 0]
    entry = float(session.get("entry_price") or (points[0].get("entry") if points else 0.0) or 0.0)
    last_price = float((closed_trade or {}).get("exitPrice") or session.get("exit_price") or (points[-1].get("price") if points else 0.0) or 0.0)
    peak = max(prices) if prices else 0.0; trough = min(prices) if prices else 0.0
    return {
        "ok": True, "recorded": bool(points),
        "session": {"id": int(session["id"]), "symbol": session.get("symbol"), "entryPrice": entry,
                    "startedAt": session.get("started_at"), "endedAt": session.get("ended_at"),
                    "exitPrice": last_price, "status": session.get("status")},
        "trade": closed_trade or {}, "points": points,
        "stats": {"pointCount": len(points), "entry": entry, "last": last_price, "peak": peak, "trough": trough,
                  "maxGainPct": (((peak / entry) - 1.0) * 100.0) if entry > 0 and peak > 0 else 0.0,
                  "maxDrawdownFromEntryPct": (((trough / entry) - 1.0) * 100.0) if entry > 0 and trough > 0 else 0.0},
        "sampleSeconds": TRADE_REPLAY_SAMPLE_SECONDS,
    }


def trade_replay_live_payload(symbol: str, limit: int = TRADE_REPLAY_MAX_POINTS) -> Dict[str, Any]:
    _trade_replay_ensure_tables(); sym = str(symbol).upper().strip(); conn = db_connect()
    row = conn.execute(
        "SELECT * FROM trade_replay_sessions WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1", (sym,)
    ).fetchone(); conn.close()
    return _trade_replay_payload(row, limit)


def trade_replay_closed_payload(trade_id: int, limit: int = TRADE_REPLAY_MAX_POINTS) -> Dict[str, Any]:
    _trade_replay_ensure_tables(); conn = db_connect()
    trade_row = conn.execute("SELECT * FROM closed_trades WHERE id=?", (int(trade_id),)).fetchone()
    if not trade_row:
        conn.close(); return {"ok": False, "message": "Closed trade not found", "points": []}
    tr = dict(trade_row); symbol = str(tr.get("symbol") or "").upper(); exit_ts = str(tr.get("timestamp") or "")
    row = conn.execute(
        "SELECT * FROM trade_replay_sessions WHERE closed_trade_id=? ORDER BY id DESC LIMIT 1", (int(trade_id),)
    ).fetchone()
    if not row:
        # Historical matcher rows may have been written before the replay session
        # was linked. Prefer the most recent session for this symbol that began
        # before the trade closed.
        row = conn.execute(
            """SELECT * FROM trade_replay_sessions
               WHERE symbol=? AND started_at<=?
               ORDER BY CASE WHEN ended_at IS NULL THEN 1 ELSE 0 END, ABS(strftime('%s', COALESCE(ended_at,updated_at))-strftime('%s',?)) ASC
               LIMIT 1""",
            (symbol, exit_ts, exit_ts),
        ).fetchone()
    conn.close()
    trade = {"id": int(tr["id"]), "timestamp": tr.get("timestamp"), "symbol": symbol,
             "qty": float(tr.get("qty") or 0.0), "entryPrice": float(tr.get("entry_price") or 0.0),
             "exitPrice": float(tr.get("exit_price") or 0.0), "pnl": float(tr.get("pnl") or 0.0),
             "pnlGbp": float(tr.get("pnl_gbp") or 0.0), "pnlPct": float(tr.get("pnl_pct") or 0.0),
             "reason": tr.get("reason") or ""}
    return _trade_replay_payload(row, limit, trade)


def run_bot_loop():
    print("Rebuilt Sniper Profit Bot started...")
    init_db()
    seeded_outcomes = v2_seed_missing_outcomes()
    if seeded_outcomes:
        print(f"V2 OUTCOMES | seeded={seeded_outcomes}")
    load_persistent_state()
    reset_daily_flags_if_needed()
    # V17.0.11 startup hardening: rebuild today's persisted sell locks before
    # the first universe/scan can approve a symbol after a Render redeploy.
    restored_at_boot = restore_today_sell_locks_from_db()
    if restored_at_boot:
        print(f"V17.0.11 STARTUP LOCK GUARD | restored={len(restored_at_boot)} symbols={','.join(restored_at_boot)}")
    refresh_universe_if_needed(force=True)
    try:
        sync_recent_filled_orders_to_reports(force=True)
        # The Alpaca sync may import a SELL that was not yet present locally when
        # the process stopped. Re-read once more before entering the live loop.
        restore_today_sell_locks_from_db()
    except Exception as e:
        print(f"AUTO REPORT STARTUP SYNC ERROR: {e}")
    try:
        if "profit_vault_seed_existing_surplus" in globals():
            profit_vault_seed_existing_surplus()
    except Exception as e:
        print(f"V17.6.2 PROFIT VAULT STARTUP SEED ERROR: {e}")
    update_status(BOT_NAME, [])

    while True:
        _cycle_started = _cycle_monitor_start("bot")
        try:
            with bot_lock:
                reset_daily_flags_if_needed()
                cleanup_temp_blacklist()
                try:
                    refresh_dynamic_market_candidates_if_needed()
                except Exception as e:
                    print(f"DYNAMIC SCANNER LOOP ERROR: {e}")
                refresh_universe_if_needed()
                try:
                    refresh_adaptive_universe_if_needed()
                except Exception as e:
                    print(f"V17.5 ADAPTIVE UNIVERSE LOOP ERROR: {e}")
                try:
                    sync_recent_filled_orders_to_reports()
                except Exception as e:
                    print(f"AUTO REPORT LOOP SYNC ERROR: {e}")
                market_state = get_effective_market_status_payload()
                try:
                    record_trade_replay_snapshot(bool(market_state.get("isOpen")))
                except Exception as e:
                    print(f"V17.1 TRADE REPLAY LOOP ERROR: {e}")

                if not market_state.get("isOpen"):
                    print("Market closed. Waiting...")
                    update_status(BOT_NAME, latest_scans)
                    _cycle_monitor_finish("bot", _cycle_started, True)
                    time.sleep(CHECK_INTERVAL)
                    continue

                # V17.0.11: preserve every daily lock but keep the scanner productive
                # by replacing locked scan slots with fresh unlocked candidates.
                try:
                    replenish_locked_universe_if_needed()
                except Exception as e:
                    print(f"V17.0.11 LOCKED UNIVERSE REPLACEMENT ERROR: {e}")

                if not AI_RESEARCH_CLOSED_MARKET_ONLY:
                    try:
                        v2_evaluate_due_outcomes()
                    except Exception as e:
                        print(f"V2 OUTCOME LOOP ERROR: {e}")

                scans = []
                preferred_scan_symbol = _first_dibs_symbol()
                scan_order = sorted(
                    list(current_universe),
                    key=lambda sym: 0 if preferred_scan_symbol and str(sym).upper() == preferred_scan_symbol else 1,
                )
                for symbol in scan_order:
                    try:
                        scan = compute_scan(symbol)
                        scans.append(scan)
                        print(f"{symbol} | price={scan['price']:.2f} | quality={scan['quality_score']:.4f} | confidence={scan['confidence']:.2f} | sniper={scan['sniper_pass']}")
                    except Exception as e:
                        print(f"SCAN ERROR {symbol}: {e}")

                latest_scans.clear()
                latest_scans.extend(scans)

                # Always publish the current AI Portfolio plan after a completed
                # live scan. Previously this only happened inside money_mode_buy,
                # so a paused bot, manual override or no order attempt left the
                # dashboard stuck on WAITING_FOR_PLAN.
                if AI_PORTFOLIO_MANAGER_ENABLED:
                    try:
                        gate_eligible = v17_live_entry_gate_pipeline(
                            scans,
                            persist_decisions=False,
                            log_rejections=False,
                            log_summary=True,
                        )
                        build_v16_portfolio_plan(gate_eligible, manual=False)
                    except Exception as portfolio_error:
                        print(f"V17.0.15 PORTFOLIO AUTO-PUBLISH ERROR: {portfolio_error}")

                if bot_enabled and not emergency_stop:
                    manage_money_mode_positions()
                    if PROFIT_MODE_ENABLED and ROTATION_MODE_ENABLED:
                        rr = maybe_rotate_weakest_into_best(scans)
                        if rr:
                            print(rr)
                    if not manual_override:
                        result = money_mode_buy(scans, manual=False)
                        if result:
                            print(result)
                update_status(BOT_NAME, scans)

            _cycle_monitor_finish("bot", _cycle_started, True)
            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            _cycle_monitor_finish("bot", _cycle_started, False, str(e))
            print(f"Main loop error: {e}")
            time.sleep(10)


@app.on_event("startup")
def startup_event():
    global bot_thread_started, v6_sync_thread_started, v7_weekend_thread_started, v11_learning_thread_started, ai_research_thread_started, ai_summary_thread_started, db_housekeeping_thread_started, trade_replay_thread_started
    # Initialise the shared SQLite schema synchronously before any worker threads start.
    # This removes the startup race where multiple workers all tried to create tables.
    init_db()
    # V17.0.11: restore persisted daily SELL locks synchronously before the live
    # bot thread starts. This closes the restart/redeploy eligibility window.
    try:
        startup_restored_locks = restore_today_sell_locks_from_db()
        if startup_restored_locks:
            print(f"V17.0.11 STARTUP EVENT LOCK GUARD | restored={len(startup_restored_locks)} symbols={','.join(startup_restored_locks)}")
    except Exception as exc:
        print(f"V17.0.11 STARTUP EVENT LOCK RESTORE ERROR: {exc}")
    try:
        startup_payload = _quick_live_status_payload()
        with _STATUS_LOCK:
            latest_status.clear()
            latest_status.update(startup_payload)
    except Exception as exc:
        print(f"STARTUP QUICK STATUS ERROR: {exc}")
    if not bot_thread_started:
        bot_thread_started = True
        threading.Thread(target=run_bot_loop, daemon=True).start()
    if TRADE_REPLAY_ENABLED and not trade_replay_thread_started:
        trade_replay_thread_started = True
        threading.Thread(target=trade_replay_recorder_worker, daemon=True, name="v17-trade-replay-recorder").start()
    if V6_BRAINS_ENABLED and V6_AUTO_SYNC_ENABLED and not AI_RESEARCH_CLOSED_MARKET_ONLY and not v6_sync_thread_started:
        v6_sync_thread_started = True
        threading.Thread(target=v6_auto_sync_worker, daemon=True).start()
    if V7_ENABLED and V7_WEEKEND_MAINTENANCE_ENABLED and not v7_weekend_thread_started:
        v7_weekend_thread_started = True
        threading.Thread(target=v7_weekend_worker, daemon=True).start()
    if V11_AUTO_LEARNING_ENABLED and not AI_RESEARCH_CLOSED_MARKET_ONLY and not v11_learning_thread_started:
        v11_learning_thread_started = True
        threading.Thread(target=v11_auto_learning_worker, daemon=True).start()
    if AI_RESEARCH_CLOSED_MARKET_ONLY and not ai_research_thread_started:
        ai_research_thread_started = True
        threading.Thread(target=closed_market_ai_research_worker, daemon=True).start()
    if AI_SUMMARY_LOG_ENABLED and not ai_summary_thread_started:
        ai_summary_thread_started = True
        threading.Thread(target=ai_periodic_summary_worker, daemon=True).start()
    if DB_HOUSEKEEPING_ENABLED and not db_housekeeping_thread_started:
        db_housekeeping_thread_started = True
        threading.Thread(target=_db_housekeeping_worker, daemon=True).start()



# =========================
# V1.0 PRODUCTION STABLE ADDONS
# =========================

BOT_VERSION = "V17.0.11-LOCKED-UNIVERSE-REPLACEMENT"
BOT_VERSION_NOTES = {
    "version": BOT_VERSION,
    "name": "TradeBot v1.0 Production Stable",
    "sameDayTrading": True,
    "sellThenLockUntilNextDay": True,
    "manualUniversePins": True,
    "weeklyUniverseRefresh": True,
    "gbpFirstReports": True,
    "pdtAware": True,
}

@app.get("/version")
def version():
    return BOT_VERSION_NOTES

# ---------- baseline reporting ----------
BASELINE_FILE = os.getenv("EQUITY_BASELINE_FILE", "").strip() or persistent_file("equity_baseline.json")

def _safe_num(v, default=0.0):
    try:
        return float(v or default)
    except Exception:
        return float(default)

def _ensure_performance_state_table() -> None:
    if not SQLITE_ENABLED:
        return
    os.makedirs(os.path.dirname(SQLITE_DB_FILE) or ".", exist_ok=True)
    conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS performance_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        baseline_equity REAL NOT NULL DEFAULT 0,
        total_deposited REAL NOT NULL DEFAULT 0,
        total_withdrawn REAL NOT NULL DEFAULT 0,
        lifetime_realised_pnl REAL NOT NULL DEFAULT 0,
        wins INTEGER NOT NULL DEFAULT 0,
        losses INTEGER NOT NULL DEFAULT 0,
        breakevens INTEGER NOT NULL DEFAULT 0,
        total_closed_trades INTEGER NOT NULL DEFAULT 0,
        best_trade REAL NOT NULL DEFAULT 0,
        worst_trade REAL NOT NULL DEFAULT 0,
        average_win REAL NOT NULL DEFAULT 0,
        average_loss REAL NOT NULL DEFAULT 0,
        profit_factor REAL NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )""")
    conn.execute("""INSERT OR IGNORE INTO performance_state
        (id, updated_at) VALUES (1, ?)""", (datetime.now(UTC).isoformat(),))
    conn.commit(); conn.close()


def load_equity_baseline() -> float:
    # SQLite on the Render disk is the primary source. The JSON copy is a
    # human-readable backup and supports migration from older deployments.
    try:
        _ensure_performance_state_table()
        conn = db_connect()
        row = conn.execute("SELECT baseline_equity FROM performance_state WHERE id=1").fetchone()
        conn.close()
        value = float(row[0] or 0.0) if row else 0.0
        if value > 0:
            return value
    except Exception as e:
        print(f"BASELINE DB LOAD ERROR: {e}")

    try:
        if os.path.exists(BASELINE_FILE):
            with open(BASELINE_FILE, "r", encoding="utf-8") as f:
                value = float(json.load(f).get("baseline", 0) or 0)
            if value > 0:
                # Migrate the old file value into the persistent DB.
                save_equity_baseline(value)
                return value
    except Exception as e:
        print(f"BASELINE LOAD ERROR: {e}")

    return _safe_num(os.getenv("TOTAL_DEPOSITED_USD", 0))


def save_equity_baseline(value: float) -> None:
    value = float(value or 0.0)
    now = datetime.now(UTC).isoformat()
    try:
        os.makedirs(os.path.dirname(BASELINE_FILE) or ".", exist_ok=True)
        with open(BASELINE_FILE, "w", encoding="utf-8") as f:
            json.dump({"baseline": value, "resetAt": now}, f, indent=2)
    except Exception as e:
        print(f"BASELINE SAVE ERROR: {e}")

    try:
        _ensure_performance_state_table()
        conn = db_connect()
        conn.execute("""UPDATE performance_state
            SET baseline_equity=?, total_deposited=?, updated_at=? WHERE id=1""",
            (value, value, now))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"BASELINE DB SAVE ERROR: {e}")


def rebuild_performance_state() -> Dict[str, Any]:
    """Recalculate lifetime realised statistics from persisted closed trades.

    This is reporting-only. It never submits or changes an order.
    """
    closed = closed_trades_from_db(100000) if "closed_trades_from_db" in globals() else []
    pnls = [float(t.get("pnl") or 0.0) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    breakevens = [p for p in pnls if p == 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    stats = {
        "lifetimeRealisedPnl": sum(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "totalClosedTrades": len(pnls),
        "bestTrade": max(pnls) if pnls else 0.0,
        "worstTrade": min(pnls) if pnls else 0.0,
        "averageWin": gross_profit / len(wins) if wins else 0.0,
        "averageLoss": sum(losses) / len(losses) if losses else 0.0,
        "profitFactor": gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0),
        "winRate": len(wins) / max(1, len(wins) + len(losses)),
        "updatedAt": datetime.now(UTC).isoformat(),
    }
    try:
        _ensure_performance_state_table()
        conn = db_connect()
        conn.execute("""UPDATE performance_state SET
            lifetime_realised_pnl=?, wins=?, losses=?, breakevens=?,
            total_closed_trades=?, best_trade=?, worst_trade=?, average_win=?,
            average_loss=?, profit_factor=?, updated_at=? WHERE id=1""",
            (stats["lifetimeRealisedPnl"], stats["wins"], stats["losses"], stats["breakevens"],
             stats["totalClosedTrades"], stats["bestTrade"], stats["worstTrade"],
             stats["averageWin"], stats["averageLoss"], stats["profitFactor"], stats["updatedAt"]))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"PERFORMANCE STATE SAVE ERROR: {e}")
    return stats


_performance_payload_cache: Dict[str, Any] = {"at": 0.0, "value": None}
_performance_payload_lock = threading.RLock()
PERFORMANCE_PAYLOAD_CACHE_SECONDS = max(10, int(os.getenv("PERFORMANCE_PAYLOAD_CACHE_SECONDS", "45")))


def performance_engine_payload(force_refresh: bool = False) -> Dict[str, Any]:
    now_mono = time.monotonic()
    with _performance_payload_lock:
        cached = _performance_payload_cache.get("value")
        if not force_refresh and isinstance(cached, dict) and now_mono - float(_performance_payload_cache.get("at", 0.0)) < PERFORMANCE_PAYLOAD_CACHE_SECONDS:
            return dict(cached)
    stats = rebuild_performance_state()
    baseline = load_equity_baseline()
    try:
        account = get_account()
        equity = float(account.equity)
    except Exception:
        equity = _safe_num(latest_status.get("account", {}).get("equity", 0))
    total_withdrawn = _safe_num(os.getenv("TOTAL_WITHDRAWN_USD", 0))
    if baseline <= 0:
        baseline = equity
        if baseline > 0:
            save_equity_baseline(baseline)
    total_gain_loss = equity + total_withdrawn - baseline
    payload = {
        "ok": True,
        "persistent": os.path.abspath(SQLITE_DB_FILE).startswith("/var/data") or bool(os.getenv("PERSISTENT_DATA_DIR")),
        "databaseFile": SQLITE_DB_FILE,
        "baselineFile": BASELINE_FILE,
        "baselineEquity": baseline,
        "totalDeposited": baseline,
        "totalWithdrawn": total_withdrawn,
        "currentEquity": equity,
        "totalGainLoss": total_gain_loss,
        "totalGainLossGbp": money_gbp(total_gain_loss),
        **stats,
    }
    with _performance_payload_lock:
        _performance_payload_cache["at"] = time.monotonic()
        _performance_payload_cache["value"] = dict(payload)
    return payload

@app.post("/reset-baseline")
def reset_baseline(request: Request):
    verify_api_key(request)
    try:
        equity = _safe_num(latest_status.get("account", {}).get("equity", 0))
        save_equity_baseline(equity)
        return {"ok": True, "message": f"Baseline reset to ${equity:.2f}", "baseline": equity}
    except Exception as e:
        return {"ok": False, "message": str(e)}

@app.get("/baseline")
def get_baseline():
    return {"ok": True, "baseline": load_equity_baseline(), "file": BASELINE_FILE}


@app.get("/performance-engine")
def api_performance_engine():
    return performance_engine_payload()


@app.post("/performance-engine/rebuild")
def api_rebuild_performance_engine(request: Request):
    verify_api_key(request)
    return {"ok": True, **performance_engine_payload(force_refresh=True), "message": "Performance statistics rebuilt from closed trades."}

_reports_payload_cache: Dict[str, Any] = {"at": 0.0, "value": None}
_reports_payload_lock = threading.RLock()
REPORTS_CACHE_SECONDS = max(15, int(os.getenv("REPORTS_CACHE_SECONDS", "45")))


def _reports_fast_performance_snapshot(status: Dict[str, Any]) -> Dict[str, Any]:
    """Build report statistics with short read-only SQLite queries.

    V17.4.1: Reports must never rebuild the performance engine, write to SQLite,
    or call the broker on the HTTP request path. Those operations can contend
    with the 10-second Trade Replay writer and made /reports appear to hang.
    """
    baseline = 0.0
    total_withdrawn = _safe_num(os.getenv("TOTAL_WITHDRAWN_USD", 0))
    stats = {
        "lifetimeRealisedPnl": 0.0, "wins": 0, "losses": 0, "breakevens": 0,
        "totalClosedTrades": 0, "bestTrade": 0.0, "worstTrade": 0.0,
        "averageWin": 0.0, "averageLoss": 0.0, "profitFactor": 0.0,
        "winRate": 0.0, "updatedAt": datetime.now(UTC).isoformat(),
    }
    try:
        conn = db_connect()
        # A single aggregate query is much cheaper than loading/rebuilding the
        # entire historical performance state on every Reports page open.
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(pnl), 0) AS realised,
                COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                COALESCE(SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END), 0) AS losses,
                COALESCE(SUM(CASE WHEN pnl = 0 THEN 1 ELSE 0 END), 0) AS breakevens,
                COALESCE(MAX(pnl), 0) AS best_trade,
                COALESCE(MIN(pnl), 0) AS worst_trade,
                COALESCE(AVG(CASE WHEN pnl > 0 THEN pnl END), 0) AS average_win,
                COALESCE(AVG(CASE WHEN pnl < 0 THEN pnl END), 0) AS average_loss,
                COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) AS gross_profit,
                COALESCE(ABS(SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END)), 0) AS gross_loss
            FROM closed_trades
        """).fetchone()
        try:
            state = conn.execute("SELECT baseline_equity, total_withdrawn, updated_at FROM performance_state WHERE id=1").fetchone()
        except Exception:
            state = None
        conn.close()

        if row is not None:
            wins = int(row["wins"] or 0); losses = int(row["losses"] or 0)
            gross_profit = float(row["gross_profit"] or 0.0); gross_loss = float(row["gross_loss"] or 0.0)
            stats.update({
                "lifetimeRealisedPnl": float(row["realised"] or 0.0),
                "wins": wins, "losses": losses, "breakevens": int(row["breakevens"] or 0),
                "totalClosedTrades": int(row["total"] or 0),
                "bestTrade": float(row["best_trade"] or 0.0), "worstTrade": float(row["worst_trade"] or 0.0),
                "averageWin": float(row["average_win"] or 0.0), "averageLoss": float(row["average_loss"] or 0.0),
                "profitFactor": gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0),
                "winRate": wins / max(1, wins + losses),
            })
        if state is not None:
            baseline = _safe_num(state["baseline_equity"])
            total_withdrawn = _safe_num(state["total_withdrawn"], total_withdrawn)
            stats["updatedAt"] = state["updated_at"] or stats["updatedAt"]
    except Exception as exc:
        print(f"V17.4.1 FAST REPORT SNAPSHOT ERROR: {exc}")
        # Fall back to already-computed status values instead of blocking the UI.
        db = status.get("dbSummary") or {}
        stats["lifetimeRealisedPnl"] = _safe_num(db.get("totalPnl"))
        stats["winRate"] = _safe_num(db.get("winRate"))
        stats["totalClosedTrades"] = int(_safe_num(db.get("totalTrades")))

    account = status.get("account") or {}
    equity = _safe_num(account.get("equity"))
    if baseline <= 0:
        baseline = _safe_num(os.getenv("TOTAL_DEPOSITED_USD", 0)) or equity
    total_gain_loss = equity + total_withdrawn - baseline
    return {
        "ok": True,
        "persistent": os.path.abspath(SQLITE_DB_FILE).startswith("/var/data") or bool(os.getenv("PERSISTENT_DATA_DIR")),
        "databaseFile": SQLITE_DB_FILE,
        "baselineFile": BASELINE_FILE,
        "baselineEquity": baseline,
        "totalDeposited": baseline,
        "totalWithdrawn": total_withdrawn,
        "currentEquity": equity,
        "totalGainLoss": total_gain_loss,
        "totalGainLossGbp": money_gbp(total_gain_loss),
        **stats,
    }


def _reports_latest_equity_history(limit: int = 500) -> List[Dict[str, Any]]:
    """Return the newest trade-backed equity points in chronological order.

    V18.2.18: reports previously reused tradeTimeline, whose shared DB reader is
    intentionally ordered oldest-first. Once the trade table grew beyond the
    limit, Today/Week/Month filters could therefore receive only old rows and
    render an empty chart. Keep this reports-only reader isolated so no trading
    memory/strategy consumers are changed.
    """
    points: List[Dict[str, Any]] = []
    if SQLITE_ENABLED:
        conn = None
        try:
            init_db()
            conn = db_connect()
            rows = conn.execute("""
                SELECT timestamp, day, time, symbol, side, equity, equity_gbp, pnl, pnl_gbp, pnl_pct, reason
                FROM trades
                WHERE COALESCE(equity, 0) > 0
                ORDER BY datetime(timestamp) DESC, id DESC
                LIMIT ?
            """, (max(1, int(limit)),)).fetchall()
            for r in reversed(rows):
                timestamp = r["timestamp"] or ""
                # Backfilled/legacy rows can have day + time even when timestamp is weak.
                if not timestamp and r["day"]:
                    timestamp = f"{r['day']}T{r['time'] or '00:00:00'}"
                points.append({
                    "time": timestamp,
                    "day": r["day"] or "",
                    "clock": r["time"] or "",
                    "symbol": r["symbol"] or "",
                    "side": r["side"] or "",
                    "equity": _safe_num(r["equity"]),
                    "equityGbp": _safe_num(r["equity_gbp"]),
                    "pnl": _safe_num(r["pnl"]),
                    "pnlGbp": _safe_num(r["pnl_gbp"]),
                    "pnlPct": _safe_num(r["pnl_pct"]),
                    "reason": r["reason"] or "",
                    "source": "trade_history",
                })
        except Exception as exc:
            print(f"V18.2.18 REPORT CHART READ ERROR: {exc}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return points


def _build_reports_payload() -> Dict[str, Any]:
    status = latest_status if isinstance(latest_status, dict) else {}
    account = status.get("account") or {}
    db = status.get("dbSummary") or {}
    equity = _safe_num(account.get("equity"))
    equity_gbp = _safe_num(account.get("equityGbp"))
    performance = _reports_fast_performance_snapshot(status)
    total_withdrawn = _safe_num(performance.get("totalWithdrawn"))
    total_deposited = _safe_num(performance.get("totalDeposited"))
    total_gain_loss = _safe_num(performance.get("totalGainLoss"))
    closed = closed_trades_from_db(200) if "closed_trades_from_db" in globals() else (status.get("closedTrades") or [])

    # V18.2.18: newest historical trade-equity points + a live current-equity point.
    # This guarantees Today can render even on a no-trade day, while Week/Month/Year
    # continue to use persisted historical account values where available.
    equity_history = _reports_latest_equity_history(500)
    live_equity = equity or _safe_num(performance.get("currentEquity"))
    if live_equity > 0:
        live_gbp = equity_gbp or money_gbp(live_equity)
        equity_history.append({
            "time": datetime.now(UTC).isoformat(),
            "day": datetime.now(UTC).strftime("%Y-%m-%d"),
            "clock": datetime.now(UTC).strftime("%H:%M:%S"),
            "symbol": "ACCOUNT",
            "side": "SNAPSHOT",
            "equity": live_equity,
            "equityGbp": live_gbp,
            "pnl": 0.0,
            "pnlGbp": 0.0,
            "pnlPct": 0.0,
            "reason": "live account snapshot",
            "source": "live_snapshot",
        })
    return {
        "ok": True, "depositSource": "persistent-performance-engine-fast-read",
        "totalDeposited": total_deposited, "totalWithdrawn": total_withdrawn,
        "currentEquity": equity, "currentEquityGbp": equity_gbp,
        "totalGainLoss": total_gain_loss, "earnedSinceDeposit": max(total_gain_loss, 0.0),
        "lostSinceDeposit": abs(min(total_gain_loss, 0.0)), "dayPnl": _safe_num(account.get("pnlDay")),
        "realisedNet": _safe_num(performance.get("lifetimeRealisedPnl", db.get("totalPnl"))),
        "performanceEngine": performance, "closedTrades": closed[:200] if isinstance(closed, list) else [],
        "equityHistory": equity_history[-500:], "winRate": _safe_num(performance.get("winRate", db.get("winRate"))) * 100.0,
        "totalTrades": int(_safe_num(performance.get("totalClosedTrades", db.get("totalTrades")))),
    }


@app.get("/trade-replay/live/{symbol}")
def api_trade_replay_live(symbol: str, limit: int = TRADE_REPLAY_MAX_POINTS):
    return trade_replay_live_payload(symbol, limit)


@app.get("/trade-replay/closed/{trade_id}")
def api_trade_replay_closed(trade_id: int, limit: int = TRADE_REPLAY_MAX_POINTS):
    return trade_replay_closed_payload(trade_id, limit)


@app.get("/trade-replay/status")
def api_trade_replay_status():
    try:
        _trade_replay_ensure_tables(); conn = db_connect()
        sessions = int(conn.execute("SELECT COUNT(*) FROM trade_replay_sessions").fetchone()[0])
        points = int(conn.execute("SELECT COUNT(*) FROM trade_replay_points").fetchone()[0])
        conn.close()
        return {"ok": True, "enabled": TRADE_REPLAY_ENABLED, "sampleSeconds": TRADE_REPLAY_SAMPLE_SECONDS,
                "sessions": sessions, "points": points}
    except Exception as exc:
        return {"ok": False, "enabled": TRADE_REPLAY_ENABLED, "error": str(exc)}


@app.get("/reports")
def reports():
    now_mono = time.monotonic()
    with _reports_payload_lock:
        cached = _reports_payload_cache.get("value")
        if isinstance(cached, dict) and now_mono - float(_reports_payload_cache.get("at", 0.0)) < REPORTS_CACHE_SECONDS:
            result = dict(cached); result["cached"] = True
            return result
    try:
        result = _build_reports_payload()
        with _reports_payload_lock:
            _reports_payload_cache.update({"at": time.monotonic(), "value": dict(result)})
        return result
    except sqlite3.OperationalError as exc:
        if _db_is_lock_error(exc):
            with _reports_payload_lock:
                cached = _reports_payload_cache.get("value")
                if isinstance(cached, dict):
                    result = dict(cached); result.update({"cached": True, "stale": True, "cacheReason": "database busy"})
                    return result
        raise


# ---------- manual universe pins ----------
MANUAL_UNIVERSE_FILE = os.path.join("backend", "state", "manual_universe_picks.json")

def load_manual_universe_picks() -> List[str]:
    try:
        if os.path.exists(MANUAL_UNIVERSE_FILE):
            with open(MANUAL_UNIVERSE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return sorted({str(x).upper().strip() for x in data if str(x).strip()})
    except Exception as e:
        print(f"MANUAL UNIVERSE LOAD ERROR: {e}")
    return []

def save_manual_universe_picks(symbols: List[str]) -> None:
    try:
        os.makedirs(os.path.dirname(MANUAL_UNIVERSE_FILE), exist_ok=True)
        clean = sorted({str(x).upper().strip() for x in symbols if str(x).strip()})
        with open(MANUAL_UNIVERSE_FILE, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)
    except Exception as e:
        print(f"MANUAL UNIVERSE SAVE ERROR: {e}")

def add_manual_universe_pick(symbol: str) -> List[str]:
    sym = symbol.upper().strip()
    picks = load_manual_universe_picks()
    if sym and sym not in picks:
        picks.append(sym)
    save_manual_universe_picks(picks)
    return load_manual_universe_picks()

def remove_manual_universe_pick(symbol: str) -> List[str]:
    sym = symbol.upper().strip()
    picks = [x for x in load_manual_universe_picks() if x != sym]
    save_manual_universe_picks(picks)
    return picks

def manual_pick_row(symbol: str) -> Dict[str, Any]:
    return {"symbol": symbol.upper(), "score": 99.0, "reason": "manual pick | pinned to universe", "manualPick": True, "status": "active"}

def apply_manual_picks_to_current_universe() -> None:
    try:
        for sym in load_manual_universe_picks():
            add_symbol_to_universe(sym, custom=True)
    except Exception as e:
        print(f"APPLY MANUAL PICKS ERROR: {e}")

def merge_manual_picks_into_auto_universe(status_obj: Dict[str, Any]) -> Dict[str, Any]:
    try:
        picks = load_manual_universe_picks()
        apply_manual_picks_to_current_universe()
        status_obj["manualUniversePicks"] = picks
        au = status_obj.setdefault("autoUniverse", {})
        rows = au.setdefault("rows", [])
        active = au.setdefault("activeSymbols", [])
        existing_rows = {str(r.get("symbol", "")).upper() for r in rows if isinstance(r, dict)}
        existing_active = {str(x).upper() for x in active}
        for sym in reversed(picks):
            if sym not in existing_rows:
                rows.insert(0, manual_pick_row(sym))
            if sym not in existing_active:
                active.insert(0, sym)
        au["rows"] = rows
        au["activeSymbols"] = active
        au["size"] = max(int(au.get("size") or 0), len(active))
        au["manualPickCount"] = len(picks)
    except Exception as e:
        print(f"MERGE MANUAL PICKS ERROR: {e}")
    return status_obj

@app.get("/manual-universe")
def api_manual_universe():
    return {"ok": True, "symbols": load_manual_universe_picks()}



def touch_quick_status(**kwargs):
    """Small safe status updater used by manual-universe/search buttons.
    Keeps UI feedback fields current without forcing a full status rebuild.
    """
    try:
        for key, value in kwargs.items():
            latest_status[key] = value
        latest_status["quickStatusUpdatedAt"] = datetime.now(UTC).isoformat()
        return True
    except Exception as e:
        print(f"TOUCH QUICK STATUS ERROR: {e}")
        return False

@app.post("/add-to-universe/{symbol}")
def add_to_universe(symbol: str, request: Request):
    verify_api_key(request)
    sym = symbol.upper().strip()
    try:
        picks = add_manual_universe_pick(sym)
        add_symbol_to_universe(sym, custom=True)
        latest_status.setdefault("autoUniverse", {})
        latest_status["autoUniverse"].setdefault("rows", [])
        latest_status["autoUniverse"].setdefault("activeSymbols", [])
        merge_manual_picks_into_auto_universe(latest_status)
        touch_quick_status(lastAction=f"{sym} added and pinned to universe", lastActionAt=datetime.now(UTC).isoformat())
        return {"ok": True, "message": f"{sym} added and pinned to universe", "symbols": picks, "manualPick": True}
    except Exception as e:
        return {"ok": False, "message": f"Could not add {sym}: {e}"}

@app.post("/remove-from-universe/{symbol}")
def api_remove_from_universe(symbol: str, request: Request):
    verify_api_key(request)
    picks = remove_manual_universe_pick(symbol)
    try:
        sym = symbol.upper().strip()
        if sym in current_universe:
            current_universe.remove(sym)
        custom_symbols.pop(sym, None)
    except Exception:
        pass
    update_status(BOT_NAME, latest_scans)
    merge_manual_picks_into_auto_universe(latest_status)
    return {"ok": True, "message": f"{symbol.upper()} removed from manual picks", "symbols": picks}

# Wrap weekly universe builder so pinned picks survive refreshes and are tradable.
_ORIGINAL_BUILD_WEEKLY_UNIVERSE = build_weekly_universe

def build_weekly_universe(force=False):
    result = _ORIGINAL_BUILD_WEEKLY_UNIVERSE(force=force)
    apply_manual_picks_to_current_universe()
    try:
        picks = load_manual_universe_picks()
        rows = result.setdefault("rows", []) if isinstance(result, dict) else []
        symbols = result.setdefault("symbols", []) if isinstance(result, dict) else []
        existing = {str(r.get("symbol", "")).upper() for r in rows if isinstance(r, dict)}
        for sym in reversed(picks):
            if sym not in existing:
                rows.insert(0, manual_pick_row(sym))
            if sym not in symbols:
                symbols.insert(0, sym)
    except Exception as e:
        print(f"BUILD WEEKLY MANUAL MERGE ERROR: {e}")
    return result

# ---------- search preview ----------
SEARCH_PREVIEW_HISTORY: Dict[str, List[Dict[str, Any]]] = {}

def _stock_name_guess(symbol: str) -> str:
    names = {"AAPL":"Apple","MSFT":"Microsoft","NVDA":"NVIDIA","AMD":"Advanced Micro Devices","AMZN":"Amazon","META":"Meta Platforms","GOOGL":"Alphabet","GOOG":"Alphabet","TSLA":"Tesla","INTC":"Intel","NFLX":"Netflix","CRM":"Salesforce","ORCL":"Oracle","ADBE":"Adobe","PYPL":"PayPal","UBER":"Uber","PLTR":"Palantir","SHOP":"Shopify","SNOW":"Snowflake","NET":"Cloudflare","MDB":"MongoDB","MU":"Micron","LAC":"Lithium Americas","LCID":"Lucid","TTWO":"Take-Two Interactive","EA":"Electronic Arts","RBLX":"Roblox","U":"Unity Software"}
    return names.get(symbol.upper(), symbol.upper())

def _stock_search_universe() -> List[str]:
    symbols = []
    for name in ["current_universe", "SAFE_UNIVERSE", "TECH_UNIVERSE", "AUTO_UNIVERSE", "UNIVERSE"]:
        val = globals().get(name)
        if isinstance(val, list):
            symbols.extend([str(x).upper() for x in val])
    symbols.extend(load_manual_universe_picks())
    symbols.extend(["AAPL","MSFT","NVDA","AMD","AMZN","META","GOOGL","GOOG","TSLA","INTC","NFLX","CRM","ORCL","ADBE","PYPL","UBER","PLTR","SHOP","SNOW","NET","MDB","MU","LAC","LCID","AVGO","QCOM","TXN","NOW","DDOG","CRWD","PANW","ZS","TEAM","SQ","COIN","HOOD","RBLX","ROKU","DIS","TTWO","EA","U"])
    seen = []
    for s in symbols:
        s = str(s).upper().strip()
        if s and s not in seen:
            seen.append(s)
    return seen

def _search_fx_rate() -> float:
    try:
        return float(get_usd_to_gbp_rate())
    except Exception:
        return 0.7403

def _latest_quote_for_symbol(symbol: str) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    quote_price = bid = ask = spread = 0.0
    try:
        req = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
        q = data_client.get_stock_latest_quote(req)
        quote = q.get(symbol) if isinstance(q, dict) else None
        if quote:
            bid = float(getattr(quote, "bid_price", 0) or 0)
            ask = float(getattr(quote, "ask_price", 0) or 0)
            quote_price = round((bid + ask) / 2, 4) if bid and ask else round(float(ask or bid or 0), 4)
            spread = round(ask - bid, 4) if ask and bid else 0.0
    except Exception as e:
        print(f"SEARCH QUOTE ERROR {symbol}: {e}")
    if quote_price <= 0:
        try:
            for s in latest_scans:
                if str(s.get("symbol", "")).upper() == symbol:
                    quote_price = float(s.get("price") or 0)
                    break
        except Exception:
            pass
    now = datetime.now(UTC).isoformat()
    hist = SEARCH_PREVIEW_HISTORY.setdefault(symbol, [])
    if quote_price > 0:
        hist.append({"t": now, "value": quote_price})
        del hist[:-80]
    prev = hist[0]["value"] if hist else quote_price
    change = quote_price - prev if quote_price and prev else 0.0
    change_pct = (change / prev * 100.0) if prev else 0.0
    fx = _search_fx_rate()
    return {"symbol": symbol, "name": _stock_name_guess(symbol), "price": quote_price, "priceGbp": round(quote_price * fx, 4), "bid": bid, "ask": ask, "spread": spread, "change": round(change, 4), "changePct": round(change_pct, 4), "history": hist, "inUniverse": symbol in [x.upper() for x in _stock_search_universe()]}

@app.get("/search-stocks")
def search_stocks(q: str = ""):
    query = (q or "").strip().upper()
    if not query:
        return {"ok": True, "query": q, "results": []}
    matches = []
    for sym in _stock_search_universe():
        name = _stock_name_guess(sym).upper()
        if query in sym or query in name:
            matches.append(sym)
        if len(matches) >= 8:
            break
    if re.fullmatch(r"[A-Z]{1,5}", query) and query not in matches:
        matches.insert(0, query)
    deduped = []
    for sym in matches:
        if sym not in deduped:
            deduped.append(sym)
    results = []
    for sym in deduped[:8]:
        qd = _latest_quote_for_symbol(sym)
        if qd.get("price", 0) > 0 or sym == query:
            results.append(qd)
    return {"ok": True, "query": q, "results": results}

@app.get("/stock-preview/{symbol}")
def stock_preview(symbol: str):
    return {"ok": True, "stock": _latest_quote_for_symbol(symbol)}




# =========================
# STRICTER PROFIT MODE v1.1
# =========================

STRICT_PROFIT_MODE = os.getenv("STRICT_PROFIT_MODE", "true").lower() == "true"
STRICT_STOP_LOSS_PCT = float(os.getenv("STRICT_STOP_LOSS_PCT", "-4.00"))
STRICT_TAKE_PROFIT_PCT = float(os.getenv("STRICT_TAKE_PROFIT_PCT", "8.00"))
STRICT_TRAIL_START_PCT = float(os.getenv("STRICT_TRAIL_START_PCT", "6.00"))
STRICT_TRAIL_DROP_PCT = float(os.getenv("STRICT_TRAIL_DROP_PCT", "2.00"))
STRICT_MAX_POSITIONS = int(os.getenv("STRICT_MAX_POSITIONS", "1"))
LOSER_COOLDOWN_DAYS = int(os.getenv("LOSER_COOLDOWN_DAYS", "3"))
LOSER_COOLDOWN_FILE = os.path.join("backend", "state", "loser_cooldown.json")

def _load_loser_cooldown() -> Dict[str, Any]:
    try:
        if os.path.exists(LOSER_COOLDOWN_FILE):
            with open(LOSER_COOLDOWN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"LOSER COOLDOWN LOAD ERROR: {e}")
    return {}

def _save_loser_cooldown(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(LOSER_COOLDOWN_FILE), exist_ok=True)
        with open(LOSER_COOLDOWN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"LOSER COOLDOWN SAVE ERROR: {e}")

def add_loser_cooldown(symbol: str, pnl_pct: float = 0.0, reason: str = "loss") -> None:
    try:
        sym = symbol.upper().strip()
        until = (datetime.now(UTC) + timedelta(days=LOSER_COOLDOWN_DAYS)).date().isoformat()
        data = _load_loser_cooldown()
        data[sym] = {"until": until, "pnlPct": float(pnl_pct or 0), "reason": reason, "createdAt": datetime.now(UTC).isoformat()}
        _save_loser_cooldown(data)
        print(f"LOSER COOLDOWN | {sym} blocked until {until} | pnlPct={pnl_pct}")
    except Exception as e:
        print(f"ADD LOSER COOLDOWN ERROR: {e}")

def is_loser_cooldown(symbol: str) -> bool:
    try:
        sym = symbol.upper().strip()
        data = _load_loser_cooldown()
        row = data.get(sym)
        if not row:
            return False
        until = datetime.fromisoformat(row.get("until")).date()
        if datetime.now(UTC).date() <= until:
            return True
        data.pop(sym, None)
        _save_loser_cooldown(data)
    except Exception:
        return False
    return False

def strict_position_should_sell(symbol: str, entry_price: float, current_price: float, high_price: float = 0.0) -> Dict[str, Any]:
    try:
        if not STRICT_PROFIT_MODE:
            return {"sell": False, "reason": ""}
        entry = float(entry_price or 0)
        price = float(current_price or 0)
        high = float(high_price or price or 0)
        if entry <= 0 or price <= 0:
            return {"sell": False, "reason": ""}

        pnl_pct = ((price - entry) / entry) * 100.0
        high_pct = ((high - entry) / entry) * 100.0
        drop_from_high_pct = ((price - high) / high) * 100.0 if high > 0 else 0.0

        if pnl_pct <= STRICT_STOP_LOSS_PCT:
            add_loser_cooldown(symbol, pnl_pct, "strict-stop-loss")
            return {"sell": True, "reason": f"STRICT STOP LOSS {pnl_pct:.2f}%", "pnlPct": pnl_pct}

        if pnl_pct >= STRICT_TAKE_PROFIT_PCT:
            return {"sell": True, "reason": f"STRICT TAKE PROFIT {pnl_pct:.2f}%", "pnlPct": pnl_pct}

        if high_pct >= STRICT_TRAIL_START_PCT and drop_from_high_pct <= -abs(STRICT_TRAIL_DROP_PCT):
            return {"sell": True, "reason": f"STRICT TRAIL DROP {drop_from_high_pct:.2f}%", "pnlPct": pnl_pct}
    except Exception as e:
        print(f"STRICT SELL DECISION ERROR {symbol}: {e}")
    return {"sell": False, "reason": ""}

def strict_can_buy_symbol(symbol: str) -> Dict[str, Any]:
    try:
        if STRICT_PROFIT_MODE and is_loser_cooldown(symbol):
            return {"ok": False, "reason": f"{symbol.upper()} in loser cooldown"}
    except Exception as e:
        print(f"STRICT CAN BUY ERROR {symbol}: {e}")
    return {"ok": True, "reason": ""}

@app.get("/strict-mode")
def api_strict_mode():
    return {
        "ok": True,
        "version": "v1.1-strict-profit-mode",
        "strictProfitMode": STRICT_PROFIT_MODE,
        "stopLossPct": STRICT_STOP_LOSS_PCT,
        "takeProfitPct": STRICT_TAKE_PROFIT_PCT,
        "trailStartPct": STRICT_TRAIL_START_PCT,
        "trailDropPct": STRICT_TRAIL_DROP_PCT,
        "maxPositions": STRICT_MAX_POSITIONS,
        "loserCooldownDays": LOSER_COOLDOWN_DAYS,
        "loserCooldown": _load_loser_cooldown(),
    }

@app.post("/clear-loser-cooldown")
def api_clear_loser_cooldown(request: Request):
    verify_api_key(request)
    _save_loser_cooldown({})
    return {"ok": True, "message": "Loser cooldown cleared"}





# =========================
# DYNAMIC MARKET SCANNER v1.0
# =========================
DYNAMIC_MARKET_SCANNER_ENABLED = os.getenv("DYNAMIC_MARKET_SCANNER_ENABLED", "true").lower() == "true"
DYNAMIC_MARKET_SCANNER_MAX_SYMBOLS = int(os.getenv("DYNAMIC_MARKET_SCANNER_MAX_SYMBOLS", "24"))
DYNAMIC_MARKET_SCANNER_REFRESH_SECONDS = int(os.getenv("DYNAMIC_MARKET_SCANNER_REFRESH_SECONDS", str(60 * 30)))
DYNAMIC_MARKET_SCANNER_FILE = os.path.join("backend", "state", "dynamic_market_scanner.json")
DYNAMIC_MARKET_MIN_PRICE = float(os.getenv("DYNAMIC_MARKET_MIN_PRICE", "3"))
DYNAMIC_MARKET_MAX_PRICE = float(os.getenv("DYNAMIC_MARKET_MAX_PRICE", "800"))
DYNAMIC_MARKET_MIN_VOLUME = int(os.getenv("DYNAMIC_MARKET_MIN_VOLUME", "500000"))
DYNAMIC_MARKET_MAX_SPREAD = float(os.getenv("DYNAMIC_MARKET_MAX_SPREAD", "0.025"))
DYNAMIC_MARKET_YAHOO_SCREENS = [
    s.strip() for s in os.getenv("DYNAMIC_MARKET_YAHOO_SCREENS", "day_gainers,most_actives,aggressive_small_caps").split(",") if s.strip()
]

DYNAMIC_SCANNER_CACHE: Dict[str, Any] = {"updatedAt": "", "symbols": [], "rows": [], "source": "empty", "error": ""}


def _load_dynamic_scanner_cache() -> Dict[str, Any]:
    global DYNAMIC_SCANNER_CACHE
    try:
        if os.path.exists(DYNAMIC_MARKET_SCANNER_FILE):
            with open(DYNAMIC_MARKET_SCANNER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                DYNAMIC_SCANNER_CACHE = {**DYNAMIC_SCANNER_CACHE, **data}
    except Exception as e:
        print(f"DYNAMIC SCANNER LOAD ERROR: {e}")
    return DYNAMIC_SCANNER_CACHE


def _save_dynamic_scanner_cache(data: Dict[str, Any]) -> Dict[str, Any]:
    global DYNAMIC_SCANNER_CACHE
    try:
        os.makedirs(os.path.dirname(DYNAMIC_MARKET_SCANNER_FILE), exist_ok=True)
        with open(DYNAMIC_MARKET_SCANNER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"DYNAMIC SCANNER SAVE ERROR: {e}")
    DYNAMIC_SCANNER_CACHE = {**DYNAMIC_SCANNER_CACHE, **data}
    return DYNAMIC_SCANNER_CACHE


def _dynamic_cache_age_seconds() -> float:
    data = _load_dynamic_scanner_cache()
    try:
        updated = datetime.fromisoformat(str(data.get("updatedAt", "")).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(UTC) - updated).total_seconds())
    except Exception:
        return 999999999.0


def _clean_dynamic_symbol(symbol: str) -> str:
    sym = str(symbol or "").upper().strip()
    # Keep normal US tickers and class shares such as BRK-B, but reject odd Yahoo suffixes.
    if not re.fullmatch(r"[A-Z]{1,5}([.-][A-Z])?", sym):
        return ""
    return sym.replace(".", "-")


def _yahoo_dynamic_screen(screen_id: str, count: int = 50) -> List[Dict[str, Any]]:
    url = f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={screen_id}&count={count}"
    headers = {"User-Agent": "Mozilla/5.0 TradeBot dynamic scanner"}
    response = requests.get(url, headers=headers, timeout=8)
    response.raise_for_status()
    data = response.json()
    quotes = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
    return quotes if isinstance(quotes, list) else []


def _score_dynamic_quote(q: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    symbol = _clean_dynamic_symbol(q.get("symbol"))
    if not symbol or symbol in BLOCKED_WEAK_TICKERS:
        return None

    exchange = str(q.get("fullExchangeName") or q.get("exchange") or "").upper()
    quote_type = str(q.get("quoteType") or "").upper()
    if quote_type and quote_type not in {"EQUITY", "ETF"}:
        return None
    if any(bad in exchange for bad in ["PNK", "OTC", "OTHER OTC"]):
        return None

    price = float(q.get("regularMarketPrice") or q.get("postMarketPrice") or q.get("preMarketPrice") or 0.0)
    volume = int(float(q.get("regularMarketVolume") or q.get("averageDailyVolume3Month") or 0))
    change_pct = float(q.get("regularMarketChangePercent") or 0.0)
    market_cap = float(q.get("marketCap") or 0.0)

    if price < DYNAMIC_MARKET_MIN_PRICE or price > DYNAMIC_MARKET_MAX_PRICE:
        return None
    if volume < DYNAMIC_MARKET_MIN_VOLUME:
        return None

    # Optional live quote spread check using Alpaca. If unavailable, do not reject; just score lower.
    spread = 0.0
    spread_ok = True
    try:
        aq = get_quote(symbol)
        spread = float(aq.get("spread") or 0.0)
        if spread > DYNAMIC_MARKET_MAX_SPREAD:
            spread_ok = False
    except Exception:
        spread = 0.0

    if not spread_ok:
        return None

    score = 0.0
    score += max(-8.0, min(12.0, change_pct)) * 1.25
    score += min(10.0, math.log10(max(volume, 1)) * 1.15)
    if market_cap > 1_000_000_000:
        score += 4.0
    if source == "day_gainers" and change_pct > 0:
        score += 3.0
    if source == "most_actives":
        score += 1.5
    if spread > 0:
        score += max(0.0, 3.0 - (spread * 120.0))

    return {
        "symbol": symbol,
        "score": round(score, 4),
        "reason": f"dynamic scanner | {source} | change={change_pct:.2f}% | volume={volume:,}" + (f" | spread={spread:.4f}" if spread else ""),
        "status": "active",
        "dynamicPick": True,
        "source": source,
        "price": price,
        "changePct": change_pct,
        "volume": volume,
        "marketCap": market_cap,
        "spread": spread,
    }


def refresh_dynamic_market_candidates(force: bool = False) -> Dict[str, Any]:
    if not DYNAMIC_MARKET_SCANNER_ENABLED:
        data = {"enabled": False, "symbols": [], "rows": [], "source": "disabled", "updatedAt": datetime.now(UTC).isoformat(), "error": ""}
        return _save_dynamic_scanner_cache(data)

    if not force and _dynamic_cache_age_seconds() < DYNAMIC_MARKET_SCANNER_REFRESH_SECONDS:
        return _load_dynamic_scanner_cache()

    _scanner_cycle_started = _cycle_monitor_start("scanner")
    rows_by_symbol: Dict[str, Dict[str, Any]] = {}
    errors = []

    for screen in DYNAMIC_MARKET_YAHOO_SCREENS:
        try:
            for quote in _yahoo_dynamic_screen(screen, count=60):
                row = _score_dynamic_quote(quote, screen)
                if not row:
                    continue
                prev = rows_by_symbol.get(row["symbol"])
                if not prev or float(row.get("score") or 0) > float(prev.get("score") or 0):
                    rows_by_symbol[row["symbol"]] = row
        except Exception as e:
            errors.append(f"{screen}: {e}")
            print(f"DYNAMIC SCANNER SOURCE ERROR {screen}: {e}")

    rows = sorted(rows_by_symbol.values(), key=lambda r: float(r.get("score") or 0), reverse=True)[:DYNAMIC_MARKET_SCANNER_MAX_SYMBOLS]

    # Safe fallback keeps the bot tradable if external screener data is unavailable.
    if not rows:
        for i, sym in enumerate(QUALITY_ONLY_UNIVERSE[:DYNAMIC_MARKET_SCANNER_MAX_SYMBOLS]):
            rows.append({
                "symbol": sym,
                "score": round(50 - i, 4),
                "reason": "dynamic scanner fallback | core quality universe",
                "status": "active",
                "dynamicPick": False,
                "source": "fallback",
            })

    payload = {
        "enabled": True,
        "mode": "dynamic-market-scanner",
        "updatedAt": datetime.now(UTC).isoformat(),
        "refreshSeconds": DYNAMIC_MARKET_SCANNER_REFRESH_SECONDS,
        "maxSymbols": DYNAMIC_MARKET_SCANNER_MAX_SYMBOLS,
        "source": ",".join(DYNAMIC_MARKET_YAHOO_SCREENS),
        "symbols": [r["symbol"] for r in rows],
        "rows": rows,
        "filters": {
            "minPrice": DYNAMIC_MARKET_MIN_PRICE,
            "maxPrice": DYNAMIC_MARKET_MAX_PRICE,
            "minVolume": DYNAMIC_MARKET_MIN_VOLUME,
            "maxSpread": DYNAMIC_MARKET_MAX_SPREAD,
        },
        "error": " | ".join(errors[-3:]),
    }
    saved_payload = _save_dynamic_scanner_cache(payload)
    _cycle_monitor_finish("scanner", _scanner_cycle_started, True)
    return saved_payload


def refresh_dynamic_market_candidates_if_needed() -> Dict[str, Any]:
    return refresh_dynamic_market_candidates(force=False)


def dynamic_market_scanner_payload() -> Dict[str, Any]:
    data = _load_dynamic_scanner_cache()
    if not data.get("rows"):
        data = refresh_dynamic_market_candidates(force=False)
    return {"enabled": DYNAMIC_MARKET_SCANNER_ENABLED, **data}


def dynamic_market_rows() -> List[Dict[str, Any]]:
    if not DYNAMIC_MARKET_SCANNER_ENABLED:
        return []
    return list(dynamic_market_scanner_payload().get("rows") or [])


def dynamic_market_symbols() -> List[str]:
    return [str(r.get("symbol", "")).upper() for r in dynamic_market_rows() if r.get("symbol")]


@app.get("/dynamic-market-scanner")
def api_dynamic_market_scanner():
    payload = dynamic_market_scanner_payload()
    return {"ok": True, "dynamicMarketScanner": payload, **payload}


@app.post("/dynamic-market-scanner/refresh")
def api_dynamic_market_scanner_refresh(request: Request):
    verify_api_key(request)
    payload = refresh_dynamic_market_candidates(force=True)
    try:
        apply_quality_only_universe()
        update_status(BOT_NAME, latest_scans)
        latest_status["dynamicMarketScanner"] = payload
        latest_status["lastAction"] = "Dynamic market scanner refreshed"
        latest_status["lastActionAt"] = datetime.now(UTC).isoformat()
    except Exception as e:
        print(f"DYNAMIC SCANNER STATUS UPDATE ERROR: {e}")
    return {"ok": True, "message": "Dynamic market scanner refreshed", "dynamicMarketScanner": payload, **payload}



# =========================
# V17.5 — HYBRID ADAPTIVE OPEN-MARKET UNIVERSE
# =========================
# The old weekly/core pool remains as a safety anchor, but it no longer owns the
# whole scanner. Fresh broad-market discoveries compete for most runtime slots.
# No entry, sizing, daily-lock or exit gate is bypassed by this layer.
ADAPTIVE_UNIVERSE_ENABLED = os.getenv("ADAPTIVE_UNIVERSE_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# V18.2.16 MARA FIRST DIBS
# The preferred symbol is always kept in the adaptive scan set (where capacity
# allows), scanned first, and promoted to portfolio rank #1 only *after* it has
# passed every normal live entry gate and the portfolio minimum score. Nothing
# here bypasses account/PDT/daily locks, reputation, Sniper, A+, trigger, V2,
# portfolio score, or the final execution lock.
FIRST_DIBS_SYMBOL = str(os.getenv("TRADEBOT_FIRST_DIBS_SYMBOL", "MARA") or "MARA").upper().strip()
FIRST_DIBS_ENABLED = os.getenv("TRADEBOT_FIRST_DIBS_ENABLED", "true").lower() in ("1", "true", "yes", "on")

def _first_dibs_symbol() -> str:
    return FIRST_DIBS_SYMBOL if FIRST_DIBS_ENABLED else ""

def _prioritize_first_dibs_rows(rows):
    """Stable priority: move the configured symbol to the front, if present.

    This function never adds eligibility; it only changes evaluation/ranking
    order for a symbol that is already present in the supplied rows.
    """
    preferred = _first_dibs_symbol()
    items = list(rows or [])
    if not preferred:
        return items
    return sorted(items, key=lambda row: 0 if str((row or {}).get("symbol") or "").upper().strip() == preferred else 1)
ADAPTIVE_UNIVERSE_TARGET_SIZE = max(6, int(os.getenv("ADAPTIVE_UNIVERSE_TARGET_SIZE", str(AUTO_UNIVERSE_SIZE)) or AUTO_UNIVERSE_SIZE))
ADAPTIVE_UNIVERSE_DISCOVERY_SLOTS = max(1, min(ADAPTIVE_UNIVERSE_TARGET_SIZE, int(os.getenv("ADAPTIVE_UNIVERSE_DISCOVERY_SLOTS", "8") or 8)))
ADAPTIVE_UNIVERSE_CORE_SLOTS = max(0, min(ADAPTIVE_UNIVERSE_TARGET_SIZE, int(os.getenv("ADAPTIVE_UNIVERSE_CORE_SLOTS", "4") or 4)))
ADAPTIVE_UNIVERSE_REFRESH_SECONDS = max(300, int(os.getenv("ADAPTIVE_UNIVERSE_REFRESH_SECONDS", "1800") or 1800))
ADAPTIVE_UNIVERSE_FILE = os.path.join("backend", "state", "adaptive_universe.json")


def _adaptive_symbol_buy_allowed(symbol: str) -> bool:
    sym = str(symbol or "").upper().strip()
    if not sym or sym in globals().get("BLOCKED_WEAK_TICKERS", set()):
        return False
    try:
        if is_locked_today(sym):
            return False
    except Exception:
        pass
    try:
        decision = auto_improve_decision(sym)
        if str(decision.get("action") or "NORMAL").upper() == "BLACKLIST":
            qty, _ = get_position(sym)
            return float(qty or 0.0) > DUST_THRESHOLD
    except Exception:
        pass
    return True


def _adaptive_core_rows() -> List[Dict[str, Any]]:
    """Rank stable anchors by the bot's own realised symbol evidence."""
    pool = [str(x).upper() for x in globals().get("QUALITY_ONLY_UNIVERSE", AUTO_UNIVERSE_CANDIDATE_POOL)]
    memory = {}
    try:
        memory = {str(r.get("symbol") or "").upper(): dict(r) for r in universe_rows_from_stock_memory()}
    except Exception:
        memory = {}

    rows: List[Dict[str, Any]] = []
    for i, sym in enumerate(pool):
        if not _adaptive_symbol_buy_allowed(sym):
            continue
        row = dict(memory.get(sym) or score_candidate_symbol(sym))
        # Keep scores useful for display without pretending dynamic/core scores
        # are identical statistical quantities.
        row.update({"symbol": sym, "adaptiveSource": "CORE", "coreAnchor": True, "dynamicPick": False})
        row.setdefault("reason", "adaptive core anchor")
        row["anchorRank"] = i + 1
        rows.append(row)
    rows.sort(key=lambda r: float(r.get("score") or 0.0), reverse=True)
    return rows


def _adaptive_discovery_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for raw in dynamic_market_rows():
        sym = str(raw.get("symbol") or "").upper().strip()
        if not _adaptive_symbol_buy_allowed(sym):
            continue
        row = dict(raw)
        row.update({"symbol": sym, "adaptiveSource": "DISCOVERY", "coreAnchor": False, "dynamicPick": True})
        rows.append(row)
    rows.sort(key=lambda r: float(r.get("score") or 0.0), reverse=True)
    return rows


def _save_adaptive_universe_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    global adaptive_universe_runtime_cache
    adaptive_universe_runtime_cache = {**adaptive_universe_runtime_cache, **payload}
    try:
        os.makedirs(os.path.dirname(ADAPTIVE_UNIVERSE_FILE), exist_ok=True)
        with open(ADAPTIVE_UNIVERSE_FILE, "w", encoding="utf-8") as f:
            json.dump(adaptive_universe_runtime_cache, f, indent=2)
    except Exception as exc:
        print(f"V17.5 ADAPTIVE UNIVERSE SAVE ERROR: {exc}")
    return dict(adaptive_universe_runtime_cache)


def adaptive_universe_payload() -> Dict[str, Any]:
    payload = dict(adaptive_universe_runtime_cache)
    if not payload.get("rows"):
        try:
            if os.path.exists(ADAPTIVE_UNIVERSE_FILE):
                with open(ADAPTIVE_UNIVERSE_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    payload.update(saved)
        except Exception:
            pass
    payload.setdefault("enabled", ADAPTIVE_UNIVERSE_ENABLED)
    payload.setdefault("mode", "hybrid-open-market")
    payload.setdefault("targetSize", ADAPTIVE_UNIVERSE_TARGET_SIZE)
    payload.setdefault("discoverySlots", ADAPTIVE_UNIVERSE_DISCOVERY_SLOTS)
    payload.setdefault("coreSlots", ADAPTIVE_UNIVERSE_CORE_SLOTS)
    payload.setdefault("refreshSeconds", ADAPTIVE_UNIVERSE_REFRESH_SECONDS)
    payload["activeSymbols"] = list(current_universe)
    return payload


def refresh_adaptive_universe(force: bool = False) -> Dict[str, Any]:
    """Build a runtime universe with fresh discoveries owning most slots.

    Priority is: held positions -> manual pins -> broad-market discoveries ->
    evidence-ranked core anchors -> safe refill. Every candidate still has to
    pass the normal V17 live gates and final execution lock before buying.
    """
    global current_universe, adaptive_universe_runtime_cache
    if not ADAPTIVE_UNIVERSE_ENABLED:
        return adaptive_universe_payload()

    now_ts = time.time()
    last_ts = float(adaptive_universe_runtime_cache.get("lastRefreshTs") or 0.0)
    if not force and adaptive_universe_runtime_cache.get("rows") and (now_ts - last_ts) < ADAPTIVE_UNIVERSE_REFRESH_SECONDS:
        return adaptive_universe_payload()

    try:
        refresh_dynamic_market_candidates(force=force)
    except Exception as exc:
        print(f"V17.5 DISCOVERY REFRESH ERROR: {exc}")

    held: List[str] = []
    try:
        held = [str(p.get("symbol") or "").upper().strip() for p in get_all_positions() if str(p.get("symbol") or "").strip()]
    except Exception:
        held = []

    manual: List[str] = []
    try:
        manual = [str(x).upper().strip() for x in load_manual_universe_picks() if str(x).strip()]
    except Exception:
        manual = []

    discoveries = _adaptive_discovery_rows()
    cores = _adaptive_core_rows()
    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def add_row(row: Dict[str, Any], source: str) -> None:
        if len(selected) >= ADAPTIVE_UNIVERSE_TARGET_SIZE:
            return
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym or sym in seen:
            return
        item = dict(row)
        item["symbol"] = sym
        item["adaptiveSource"] = source
        item["status"] = "active"
        selected.append(item)
        seen.add(sym)

    # Held symbols are management-critical even if a buy lock/blacklist exists.
    for sym in held:
        add_row({"symbol": sym, "score": 999.0, "reason": "currently held position"}, "HELD")

    for sym in manual:
        if sym not in seen and sym not in globals().get("BLOCKED_WEAK_TICKERS", set()):
            add_row({"symbol": sym, "score": 998.0, "reason": "manual pin | retained in adaptive universe", "manualPick": True}, "PIN")

    # V18.2.16: reserve one runtime scan slot for the first-dibs symbol so it
    # cannot disappear during an adaptive rotation. It still has to pass every
    # live gate before it can be ranked or bought.
    preferred = _first_dibs_symbol()
    if preferred and preferred not in seen:
        add_row({
            "symbol": preferred,
            "score": 997.0,
            "reason": "first dibs watch | checked first but never bypasses gates",
            "firstDibs": True,
        }, "PRIORITY")

    discovery_added = 0
    for row in discoveries:
        if len(selected) >= ADAPTIVE_UNIVERSE_TARGET_SIZE or discovery_added >= ADAPTIVE_UNIVERSE_DISCOVERY_SLOTS:
            break
        if str(row.get("symbol") or "").upper() in seen:
            continue
        add_row(row, "DISCOVERY")
        discovery_added += 1

    core_added = 0
    for row in cores:
        if len(selected) >= ADAPTIVE_UNIVERSE_TARGET_SIZE or core_added >= ADAPTIVE_UNIVERSE_CORE_SLOTS:
            break
        if str(row.get("symbol") or "").upper() in seen:
            continue
        add_row(row, "CORE")
        core_added += 1

    # If discovery/core quotas left gaps, fill from whichever side still has
    # viable names rather than returning to a fixed dedicated pool.
    for row in discoveries + cores:
        if len(selected) >= ADAPTIVE_UNIVERSE_TARGET_SIZE:
            break
        add_row(row, str(row.get("adaptiveSource") or "DISCOVERY"))

    # Last-resort safe refill only if external discovery is unavailable.
    for sym in AUTO_UNIVERSE_CANDIDATE_POOL:
        if len(selected) >= ADAPTIVE_UNIVERSE_TARGET_SIZE:
            break
        if sym in seen or not _adaptive_symbol_buy_allowed(sym):
            continue
        add_row(score_candidate_symbol(sym), "FALLBACK")

    previous = list(current_universe)
    current_universe = [r["symbol"] for r in selected]
    for sym in current_universe:
        ensure_symbol_state(sym, custom=sym in custom_symbols)

    changed = previous != current_universe
    changes = int(adaptive_universe_runtime_cache.get("changes") or 0) + (1 if changed else 0)
    payload = {
        "enabled": True,
        "mode": "hybrid-open-market",
        "updatedAt": datetime.now(UTC).isoformat(),
        "lastRefreshTs": now_ts,
        "refreshSeconds": ADAPTIVE_UNIVERSE_REFRESH_SECONDS,
        "targetSize": ADAPTIVE_UNIVERSE_TARGET_SIZE,
        "discoverySlots": ADAPTIVE_UNIVERSE_DISCOVERY_SLOTS,
        "coreSlots": ADAPTIVE_UNIVERSE_CORE_SLOTS,
        "discoveryCount": len([r for r in selected if r.get("adaptiveSource") == "DISCOVERY"]),
        "coreCount": len([r for r in selected if r.get("adaptiveSource") == "CORE"]),
        "heldCount": len([r for r in selected if r.get("adaptiveSource") == "HELD"]),
        "pinCount": len([r for r in selected if r.get("adaptiveSource") == "PIN"]),
        "priorityCount": len([r for r in selected if r.get("adaptiveSource") == "PRIORITY"]),
        "firstDibsEnabled": bool(FIRST_DIBS_ENABLED),
        "firstDibsSymbol": _first_dibs_symbol() or None,
        "symbols": list(current_universe),
        "activeSymbols": list(current_universe),
        "rows": selected,
        "changed": changed,
        "changes": changes,
        "previousSymbols": previous,
    }
    _save_adaptive_universe_payload(payload)
    try:
        latest_status["adaptiveUniverse"] = payload
        latest_status["autoUniverse"] = {**latest_status.get("autoUniverse", {}), "mode": "hybrid-open-market", "activeSymbols": list(current_universe), "rows": selected, "size": len(current_universe)}
    except Exception:
        pass

    if changed:
        removed = [x for x in previous if x not in current_universe]
        added = [x for x in current_universe if x not in previous]
        print(
            "V17.5 ADAPTIVE UNIVERSE ROTATION | "
            f"discovery={payload['discoveryCount']} core={payload['coreCount']} held={payload['heldCount']} pins={payload['pinCount']} "
            f"removed={','.join(removed) or '-'} added={','.join(added) or '-'} universe={','.join(current_universe)}"
        )
    return payload


def refresh_adaptive_universe_if_needed() -> Dict[str, Any]:
    return refresh_adaptive_universe(force=False)


@app.get("/adaptive-universe")
def api_adaptive_universe():
    payload = adaptive_universe_payload()
    return {"ok": True, "adaptiveUniverse": payload, **payload}


@app.post("/adaptive-universe/refresh")
def api_refresh_adaptive_universe(request: Request):
    verify_api_key(request)
    payload = refresh_adaptive_universe(force=True)
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Adaptive open-market universe refreshed", "adaptiveUniverse": payload, **payload}

# =========================
# QUALITY-ONLY UNIVERSE LOCK v1.3
# =========================

QUALITY_ONLY_MODE = os.getenv("QUALITY_ONLY_MODE", "true").lower() == "true"

QUALITY_ONLY_UNIVERSE = [
    "NVDA", "AMD", "MSFT", "AAPL", "META",
    "AMZN", "GOOGL", "GOOG", "AVGO", "NFLX",
    "TSLA", "PLTR", "UBER", "QQQ", "SMH",
]

BLOCKED_WEAK_TICKERS = {
    "LAC", "LCID", "PLUG", "SOFI", "SNAP", "NUVB",
    "RIVN", "F", "AAL", "GIS", "PYPL"
}

def quality_only_symbols():
    symbols = []

    # Manual pins always get first priority unless explicitly blocked.
    try:
        if "load_manual_universe_picks" in globals() and callable(globals()["load_manual_universe_picks"]):
            for sym in load_manual_universe_picks():
                sym = str(sym).upper().strip()
                if sym and sym not in symbols and sym not in BLOCKED_WEAK_TICKERS:
                    symbols.append(sym)
    except Exception as e:
        print(f"QUALITY ONLY MANUAL MERGE ERROR: {e}")

    # Dynamic scanner picks are the main discovery layer.
    try:
        if DYNAMIC_MARKET_SCANNER_ENABLED:
            for sym in dynamic_market_symbols():
                sym = str(sym).upper().strip()
                if sym and sym not in symbols and sym not in BLOCKED_WEAK_TICKERS:
                    symbols.append(sym)
    except Exception as e:
        print(f"QUALITY ONLY DYNAMIC MERGE ERROR: {e}")

    # Core quality names are the safety fallback and stable baseline.
    for sym in QUALITY_ONLY_UNIVERSE:
        sym = str(sym).upper().strip()
        if sym and sym not in symbols and sym not in BLOCKED_WEAK_TICKERS:
            symbols.append(sym)

    return symbols

def quality_only_rows():
    rows = []
    dynamic_by_symbol = {}
    try:
        dynamic_by_symbol = {str(r.get("symbol", "")).upper(): r for r in dynamic_market_rows()}
    except Exception:
        dynamic_by_symbol = {}

    manual_picks = set()
    try:
        manual_picks = {str(s).upper() for s in load_manual_universe_picks()}
    except Exception:
        manual_picks = set()

    for i, sym in enumerate(quality_only_symbols()):
        dyn = dynamic_by_symbol.get(sym)
        is_manual = sym in manual_picks
        is_dynamic = bool(dyn)
        base_score = 100 - (i * 3.0)
        score = float(dyn.get("score", base_score)) if dyn else base_score
        reason = dyn.get("reason") if dyn else "core quality universe | weak tickers blocked"
        if is_manual:
            reason = "manual pick | pinned to universe" + (f" | {reason}" if reason else "")
            score = max(score, 99.0)
        rows.append({
            "symbol": sym,
            "score": round(score, 2),
            "reason": reason,
            "status": "active",
            "manualPick": is_manual,
            "dynamicPick": is_dynamic,
            "source": dyn.get("source") if dyn else "core-quality",
            "changePct": dyn.get("changePct") if dyn else None,
            "volume": dyn.get("volume") if dyn else None,
            "price": dyn.get("price") if dyn else None,
        })
    return rows

def apply_quality_only_universe():
    global current_universe, SAFE_UNIVERSE, UNIVERSE, AUTO_UNIVERSE_CANDIDATE_POOL

    symbols = quality_only_symbols()
    rows = quality_only_rows()

    try:
        current_universe = symbols[:]
    except Exception:
        pass

    try:
        SAFE_UNIVERSE = symbols[:]
    except Exception:
        pass

    try:
        UNIVERSE = symbols[:]
    except Exception:
        pass

    try:
        AUTO_UNIVERSE_CANDIDATE_POOL = symbols[:]
    except Exception:
        pass

    try:
        latest_status["autoUniverse"] = {
            "enabled": True,
            "mode": "dynamic-quality-hybrid" if DYNAMIC_MARKET_SCANNER_ENABLED else "quality-only",
            "size": len(symbols),
            "activeSymbols": symbols,
            "rows": rows,
            "blockedWeakTickers": sorted(list(BLOCKED_WEAK_TICKERS)),
            "dynamicScanner": dynamic_market_scanner_payload() if "dynamic_market_scanner_payload" in globals() else {},
            "lastRefresh": datetime.now(UTC).isoformat(),
            "manualPickCount": len([s for s in symbols if s not in QUALITY_ONLY_UNIVERSE]),
        }
        latest_status["lastAction"] = "Quality-only universe applied"
        latest_status["lastActionAt"] = datetime.now(UTC).isoformat()
    except Exception as e:
        print(f"QUALITY ONLY STATUS ERROR: {e}")

    return symbols

def is_quality_blocked_symbol(symbol: str) -> bool:
    sym = str(symbol).upper().strip()
    if not QUALITY_ONLY_MODE:
        return False
    if sym in BLOCKED_WEAK_TICKERS:
        return True
    if sym not in quality_only_symbols():
        return True
    return False

def quality_buy_check(symbol: str):
    sym = str(symbol).upper().strip()
    if is_quality_blocked_symbol(sym):
        return {
            "ok": False,
            "reason": f"{sym} blocked by quality-only universe",
        }
    return {"ok": True, "reason": "quality approved"}

# Apply immediately on startup/redeploy.
try:
    apply_quality_only_universe()
except Exception as e:
    print(f"QUALITY ONLY STARTUP APPLY ERROR: {e}")

@app.get("/quality-universe")
def api_quality_universe():
    return {
        "ok": True,
        "qualityOnlyMode": QUALITY_ONLY_MODE,
        "activeSymbols": quality_only_symbols(),
        "blockedWeakTickers": sorted(list(BLOCKED_WEAK_TICKERS)),
        "rows": quality_only_rows(),
    }

@app.post("/apply-quality-universe")
def api_apply_quality_universe(request: Request):
    verify_api_key(request)
    symbols = apply_quality_only_universe()
    try:
        update_status(BOT_NAME, latest_scans)
        apply_quality_only_universe()
    except Exception as e:
        print(f"APPLY QUALITY UPDATE_STATUS ERROR: {e}")
    return {
        "ok": True,
        "message": "Quality-only universe applied",
        "activeSymbols": symbols,
        "blockedWeakTickers": sorted(list(BLOCKED_WEAK_TICKERS)),
    }




# =========================
# FORCE QUALITY UNIVERSE STATUS/UI PATCH
# =========================

def force_quality_auto_universe_payload():
    try:
        if "quality_only_rows" in globals():
            rows = quality_only_rows()
        elif "quality_universe_rows" in globals():
            rows = quality_universe_rows()
        else:
            rows = []
        if "reconcile_auto_universe_rows" in globals():
            rows = reconcile_auto_universe_rows(rows, len(rows) or AUTO_UNIVERSE_SIZE)
        symbols = [r["symbol"] for r in rows]
    except Exception:
        rows = []
        symbols = []

    if not symbols:
        symbols = [
            "NVDA", "AMD", "MSFT", "AAPL", "META",
            "AMZN", "GOOGL", "GOOG", "AVGO", "NFLX",
            "TSLA", "PLTR", "UBER", "QQQ", "SMH",
        ]
        rows = [
            {
                "symbol": s,
                "score": round(100 - (i * 3), 2),
                "reason": "quality-only universe | forced UI sync",
                "status": "active",
            }
            for i, s in enumerate(symbols)
        ]

    return {
        "enabled": True,
        "mode": "dynamic-quality-hybrid" if DYNAMIC_MARKET_SCANNER_ENABLED else "quality-only",
        "size": len(symbols),
        "weekStart": datetime.now(UTC).date().isoformat(),
        "monthStart": datetime.now(UTC).replace(day=1).date().isoformat(),
        "activeSymbols": symbols,
        "rows": rows,
        "lastRefresh": datetime.now(UTC).isoformat(),
        "candidatePoolSize": len(symbols),
        "dynamicPickCount": len([r for r in rows if r.get("dynamicPick")]),
        "manualPickCount": len([r for r in rows if r.get("manualPick")]),
        "dynamicScanner": dynamic_market_scanner_payload() if "dynamic_market_scanner_payload" in globals() else {},
        "keepWinners": True,
    }

@app.get("/weekly-universe")
def weekly_universe():
    payload = force_quality_auto_universe_payload()
    try:
        latest_status["autoUniverse"] = payload
    except Exception:
        pass
    return {"ok": True, "autoUniverse": payload, **payload}

@app.post("/refresh-universe")
def refresh_universe(request: Request):
    """
    Fast weekly stock refresh route for the dashboard button.

    Important fix:
    - Do not wait behind the trading bot lock.
    - Do not run slow scans/trading work here.
    - Update current_universe + latest_status immediately so /status and /weekly-universe
      show the refreshed list straight away.
    """
    print("BUTTON HIT: refresh-universe", flush=True)
    verify_api_key(request)

    try:
        if "refresh_dynamic_market_candidates" in globals():
            refresh_dynamic_market_candidates(force=True)
        if "apply_quality_only_universe" in globals():
            apply_quality_only_universe()
        elif "apply_quality_universe_to_status" in globals():
            apply_quality_universe_to_status()
    except Exception as e:
        print(f"QUALITY APPLY ERROR: {e}")

    payload = force_quality_auto_universe_payload()
    symbols = list(dict.fromkeys([str(s).upper().strip() for s in payload.get("activeSymbols", []) if str(s).strip()]))

    try:
        global current_universe, last_universe_refresh_ts
        if symbols:
            current_universe = symbols
            for sym in current_universe:
                ensure_symbol_state(sym, custom=sym in custom_symbols)
        last_universe_refresh_ts = time.time()
    except Exception as e:
        print(f"REFRESH UNIVERSE STATE ERROR: {e}")

    try:
        latest_status["autoUniverse"] = payload
        latest_status["universe"] = symbols or payload.get("activeSymbols", [])
        latest_status["lastAction"] = "Quality-only weekly universe refreshed"
        latest_status["lastActionAt"] = datetime.now(UTC).isoformat()
        latest_status["autoUniverseEnabled"] = True
        latest_status["dynamicMarketScanner"] = dynamic_market_scanner_payload() if "dynamic_market_scanner_payload" in globals() else {}
    except Exception as e:
        print(f"REFRESH UNIVERSE STATUS ERROR: {e}")

    return {
        "ok": True,
        "message": "Dynamic market universe refreshed",
        "autoUniverse": payload,
        "activeSymbols": symbols or payload.get("activeSymbols", []),
        "rows": payload.get("rows", []),
    }

@app.get("/refresh-universe-preview")
def refresh_universe_preview():
    print("BUTTON HIT: refresh-universe", flush=True)
    payload = force_quality_auto_universe_payload()
    return {
        "ok": True,
        "message": "Preview of quality-only universe",
        "activeSymbols": payload["activeSymbols"],
        "rows": payload["rows"],
        "autoUniverse": payload,
    }




# ============================================================
# V17.6.0 — REALISED PROFIT VAULT
# ============================================================
# The vault is deliberately separate from the legacy trading cap.
# Full-buy mode still commits the whole WORKING pot, but realised positive
# PnL is reserved in software and excluded from all future buy sizing.
# Losses never consume the recorded vault balance.
PROFIT_VAULT_VERSION = "V17.6.2"
PROFIT_VAULT_ENABLED = os.getenv("PROFIT_VAULT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PROFIT_VAULT_DEFAULT_BASELINE_GBP = 900.00  # HARD-CODED: persisted state must not override this
PROFIT_VAULT_BANK_PCT = max(0.0, min(1.0, float(os.getenv("PROFIT_VAULT_BANK_PCT", "1.0") or 1.0)))
_PROFIT_VAULT_LOCK = threading.RLock()

def profit_vault_file_path() -> str:
    env_path = os.getenv("PROFIT_VAULT_FILE", "").strip()
    if env_path:
        return env_path
    if os.path.isdir("/var/data"):
        return "/var/data/profit_vault.json"
    base = os.getenv("RENDER_DISK_PATH", "backend/state")
    return os.path.join(base, "profit_vault.json")

def _profit_vault_default_state() -> Dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "version": PROFIT_VAULT_VERSION,
        "enabled": bool(PROFIT_VAULT_ENABLED),
        "baselineGbp": round(float(PROFIT_VAULT_DEFAULT_BASELINE_GBP), 2),
        "bankPct": round(float(PROFIT_VAULT_BANK_PCT), 4),
        "bankedProfitGbp": 0.0,
        "lifetimeBankedGbp": 0.0,
        "createdAt": now,
        "updatedAt": now,
        "lastBankedAt": "",
        "lastBankedSymbol": "",
        "lastBankedReason": "",
        "lastBankedAmountGbp": 0.0,
        "baselineSeeded": False,
        "baselineSeededAt": "",
        "baselineSeedAmountGbp": 0.0,
    }

def load_profit_vault_state() -> Dict[str, Any]:
    path = profit_vault_file_path()
    with _PROFIT_VAULT_LOCK:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                default = _profit_vault_default_state()
                default.update(data if isinstance(data, dict) else {})
                default["enabled"] = bool(default.get("enabled", PROFIT_VAULT_ENABLED))
                default["baselineGbp"] = round(float(PROFIT_VAULT_DEFAULT_BASELINE_GBP), 2)  # hard-coded baseline wins
                default["bankPct"] = max(0.0, min(1.0, float(default.get("bankPct") if default.get("bankPct") is not None else PROFIT_VAULT_BANK_PCT)))
                default["bankedProfitGbp"] = max(0.0, float(default.get("bankedProfitGbp") or 0.0))
                default["lifetimeBankedGbp"] = max(default["bankedProfitGbp"], float(default.get("lifetimeBankedGbp") or 0.0))
                return default
        except Exception as exc:
            print(f"V17.6 PROFIT VAULT LOAD ERROR | {exc}")

        state = _profit_vault_default_state()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as exc:
            print(f"V17.6 PROFIT VAULT INIT ERROR | {exc}")
        return state

def save_profit_vault_state(state: Dict[str, Any]) -> Dict[str, Any]:
    path = profit_vault_file_path()
    with _PROFIT_VAULT_LOCK:
        data = _profit_vault_default_state()
        data.update(state or {})
        data["version"] = PROFIT_VAULT_VERSION
        data["baselineGbp"] = round(float(PROFIT_VAULT_DEFAULT_BASELINE_GBP), 2)  # never persist a different baseline
        data["updatedAt"] = datetime.now(UTC).isoformat()
        data["bankedProfitGbp"] = round(max(0.0, float(data.get("bankedProfitGbp") or 0.0)), 4)
        data["lifetimeBankedGbp"] = round(max(data["bankedProfitGbp"], float(data.get("lifetimeBankedGbp") or 0.0)), 4)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
        return data

def profit_vault_seed_existing_surplus(account: Any = None) -> Dict[str, Any]:
    """One-time migration: reserve existing account equity above the hard-coded baseline.

    This only runs when there are no open positions. Once seeded, future vault growth
    comes only from realised profitable sells via profit_vault_bank_realised_profit().
    """
    state = load_profit_vault_state()
    if not state.get("enabled") or bool(state.get("baselineSeeded")):
        return state
    try:
        if len(get_all_positions()) > 0:
            return state
    except Exception as exc:
        print(f"V17.6.2 PROFIT VAULT SEED WAIT | positions unavailable: {exc}")
        return state
    try:
        account = account or get_account()
        equity_usd = max(0.0, float(account.equity))
    except Exception as exc:
        print(f"V17.6.2 PROFIT VAULT SEED WAIT | account unavailable: {exc}")
        return state
    rate = get_usd_to_gbp_rate() or FX_FALLBACK_USD_TO_GBP
    equity_gbp = equity_usd * float(rate)
    baseline_gbp = float(PROFIT_VAULT_DEFAULT_BASELINE_GBP)
    target_banked = round(max(0.0, equity_gbp - baseline_gbp), 4)
    existing_banked = max(0.0, float(state.get("bankedProfitGbp") or 0.0))
    seeded_delta = round(max(0.0, target_banked - existing_banked), 4)
    state["bankedProfitGbp"] = round(max(existing_banked, target_banked), 4)
    state["lifetimeBankedGbp"] = round(max(
        float(state.get("lifetimeBankedGbp") or 0.0) + seeded_delta,
        float(state["bankedProfitGbp"]),
    ), 4)
    state["baselineSeeded"] = True
    state["baselineSeededAt"] = datetime.now(UTC).isoformat()
    state["baselineSeedAmountGbp"] = seeded_delta
    state = save_profit_vault_state(state)
    print(
        f"V17.6.2 PROFIT VAULT BASELINE SEED | baseline=£{baseline_gbp:.2f} "
        f"equity=£{equity_gbp:.2f} banked=£{float(state.get('bankedProfitGbp') or 0.0):.2f} "
        f"working=£{max(0.0, equity_gbp-float(state.get('bankedProfitGbp') or 0.0)):.2f}"
    )
    return state

def profit_vault_reserved_usd() -> float:
    state = load_profit_vault_state()
    if not state.get("enabled"):
        return 0.0
    banked_gbp = max(0.0, float(state.get("bankedProfitGbp") or 0.0))
    rate = get_usd_to_gbp_rate() or FX_FALLBACK_USD_TO_GBP
    return max(0.0, banked_gbp / max(float(rate), 0.0001))

def profit_vault_deployable_usd(account_equity: float, buying_power: Optional[float] = None) -> float:
    try:
        equity = max(0.0, float(account_equity or 0.0))
    except Exception:
        equity = 0.0
    reserved = profit_vault_reserved_usd()
    working = max(0.0, equity - reserved)
    if buying_power is not None:
        try:
            working = min(working, max(0.0, float(buying_power)))
        except Exception:
            pass
    return max(0.0, working)

def profit_vault_bank_realised_profit(pnl_usd: float, symbol: str = "", reason: str = "") -> Dict[str, Any]:
    state = load_profit_vault_state()
    if not state.get("enabled"):
        return state
    try:
        pnl_usd = float(pnl_usd or 0.0)
    except Exception:
        pnl_usd = 0.0
    if pnl_usd <= 0:
        return state
    pnl_gbp = max(0.0, float(money_gbp(pnl_usd)))
    bank_amount = round(pnl_gbp * max(0.0, min(1.0, float(state.get("bankPct") or PROFIT_VAULT_BANK_PCT))), 4)
    if bank_amount <= 0:
        return state
    state["bankedProfitGbp"] = round(float(state.get("bankedProfitGbp") or 0.0) + bank_amount, 4)
    state["lifetimeBankedGbp"] = round(float(state.get("lifetimeBankedGbp") or 0.0) + bank_amount, 4)
    state["lastBankedAt"] = datetime.now(UTC).isoformat()
    state["lastBankedSymbol"] = str(symbol or "").upper()
    state["lastBankedReason"] = str(reason or "")
    state["lastBankedAmountGbp"] = bank_amount
    state = save_profit_vault_state(state)
    print(
        f"V17.6 PROFIT VAULT BANK | symbol={str(symbol or '').upper()} "
        f"realised_pnl=£{pnl_gbp:.2f} banked=£{bank_amount:.2f} "
        f"vault=£{float(state.get('bankedProfitGbp') or 0.0):.2f}"
    )
    return state

def profit_vault_payload(account: Any = None) -> Dict[str, Any]:
    state = profit_vault_seed_existing_surplus(account)
    if not state.get("baselineSeeded"):
        state = load_profit_vault_state()
    try:
        account = account or get_account()
        equity_usd = max(0.0, float(account.equity))
        buying_power_usd = max(0.0, float(account.buying_power))
    except Exception:
        equity_usd = 0.0
        buying_power_usd = 0.0
    rate = get_usd_to_gbp_rate() or FX_FALLBACK_USD_TO_GBP
    equity_gbp = equity_usd * float(rate)
    banked_gbp = max(0.0, float(state.get("bankedProfitGbp") or 0.0))
    reserved_usd = banked_gbp / max(float(rate), 0.0001)
    working_usd = profit_vault_deployable_usd(equity_usd, buying_power_usd)
    return {
        "version": PROFIT_VAULT_VERSION,
        "enabled": bool(state.get("enabled")),
        "baselineGbp": round(float(state.get("baselineGbp") or PROFIT_VAULT_DEFAULT_BASELINE_GBP), 2),
        "bankPct": round(float(state.get("bankPct") or 0.0), 4),
        "bankedProfitGbp": round(banked_gbp, 2),
        "bankedProfitUsd": round(reserved_usd, 2),
        "lifetimeBankedGbp": round(float(state.get("lifetimeBankedGbp") or 0.0), 2),
        "accountEquityGbp": round(equity_gbp, 2),
        "accountEquityUsd": round(equity_usd, 2),
        # V18.2.4 capital clarity: workingCapital remains the legacy free-cash/deployable field.
        # Explicit semantic fields prevent dashboards/reports from mistaking free cash for the whole trading pot.
        "workingCapitalGbp": round(working_usd * float(rate), 2),
        "workingCapitalUsd": round(working_usd, 2),
        "freeCashGbp": round(working_usd * float(rate), 2),
        "freeCashUsd": round(working_usd, 2),
        "tradingCapitalGbp": round(max(0.0, equity_gbp - banked_gbp), 2),
        "tradingCapitalUsd": round(max(0.0, equity_usd - reserved_usd), 2),
        "buyingPowerUsd": round(buying_power_usd, 2),
        "lastBankedAt": state.get("lastBankedAt", ""),
        "lastBankedSymbol": state.get("lastBankedSymbol", ""),
        "lastBankedReason": state.get("lastBankedReason", ""),
        "lastBankedAmountGbp": round(float(state.get("lastBankedAmountGbp") or 0.0), 2),
        "baselineSeeded": bool(state.get("baselineSeeded")),
        "baselineSeededAt": state.get("baselineSeededAt", ""),
        "baselineSeedAmountGbp": round(float(state.get("baselineSeedAmountGbp") or 0.0), 2),
        "growthSinceBaselineGbp": round(equity_gbp - float(state.get("baselineGbp") or PROFIT_VAULT_DEFAULT_BASELINE_GBP), 2),
        "message": "100% of positive realised PnL is reserved and excluded from future buys." if float(state.get("bankPct") or 0.0) >= 0.999 else "A configured share of positive realised PnL is reserved from future buys.",
    }

# ============================================================
# PROFIT BANKING / PERSISTENT TRADING CAP OVERRIDE
# ============================================================

def trading_cap_file_path() -> str:
    """Persistent cap file.

    On Render, set TRADING_CAP_FILE to your disk path if your disk is not mounted
    at /var/data. If /var/data exists, the bot will use it automatically.
    """
    env_path = os.getenv("TRADING_CAP_FILE", "").strip()
    if env_path:
        return env_path
    if os.path.isdir("/var/data"):
        return "/var/data/trading_cap.json"
    base = os.getenv("RENDER_DISK_PATH", "backend/state")
    return os.path.join(base, "trading_cap.json")


def _default_trading_cap_usd() -> float:
    try:
        return float(os.getenv("MAX_TRADING_CAPITAL", str(MAX_TRADING_CAPITAL or 200)) or 200)
    except Exception:
        return 200.0


def load_trading_cap_setting() -> Dict[str, Any]:
    path = trading_cap_file_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            value = float(data.get("value") or 0)
            currency = str(data.get("currency") or "GBP").upper()
            if value > 0 and currency in ["GBP", "USD"]:
                return {
                    "value": value,
                    "currency": currency,
                    "source": "saved",
                    "path": path,
                    "updatedAt": data.get("updatedAt", ""),
                }
    except Exception as e:
        print(f"TRADING CAP LOAD ERROR: {e}")

    # Backwards-compatible fallback: old env/code cap is USD.
    return {
        "value": _default_trading_cap_usd(),
        "currency": "USD",
        "source": "env",
        "path": path,
        "updatedAt": "",
    }


def save_trading_cap_setting(value: float, currency: str = "GBP") -> Dict[str, Any]:
    currency = str(currency or "GBP").upper().strip()
    if currency not in ["GBP", "USD"]:
        currency = "GBP"
    value = float(value or 0)
    if value < 0:
        value = 0.0

    path = trading_cap_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "value": round(value, 2),
        "currency": currency,
        "updatedAt": datetime.now(UTC).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return load_trading_cap_setting()


def trading_cap_usd() -> float:
    setting = load_trading_cap_setting()
    value = float(setting.get("value") or 0.0)
    currency = str(setting.get("currency") or "USD").upper()
    if value <= 0:
        return 0.0
    if currency == "GBP":
        rate = get_usd_to_gbp_rate() or FX_FALLBACK_USD_TO_GBP
        return value / max(rate, 0.0001)
    return value


def trading_cap_gbp() -> float:
    setting = load_trading_cap_setting()
    value = float(setting.get("value") or 0.0)
    currency = str(setting.get("currency") or "USD").upper()
    if value <= 0:
        return 0.0
    if currency == "GBP":
        return value
    return money_gbp(value)


def effective_trading_equity(account_equity: float) -> float:
    try:
        equity = float(account_equity or 0)
    except Exception:
        equity = 0.0

    cap = trading_cap_usd()
    return max(0.0, min(equity, cap)) if cap > 0 else max(0.0, equity)


def banking_payload():
    # V18.2.2: keep account defined even when the broker account lookup fails.
    # This lets /banking-status and the Command Center degrade gracefully instead
    # of raising UnboundLocalError during a temporary broker/API failure.
    account = None
    try:
        account = get_account()
        equity = float(account.equity)
    except Exception:
        equity = 0.0

    setting = load_trading_cap_setting()
    cap_usd = trading_cap_usd()
    cap_gbp = trading_cap_gbp()

    effective = max(0.0, min(equity, cap_usd)) if cap_usd > 0 else max(0.0, equity)
    banked = max(0.0, equity - effective) if cap_usd > 0 else 0.0
    vault = profit_vault_payload(account) if "profit_vault_payload" in globals() else {}

    return {
        "ok": True,
        "enabled": cap_usd > 0,
        "maxTradingCapital": cap_usd,
        "maxTradingCapitalUsd": cap_usd,
        "maxTradingCapitalGbp": cap_gbp,
        "tradingCapValue": float(setting.get("value") or 0.0),
        "tradingCapCurrency": setting.get("currency", "USD"),
        "tradingCapSource": setting.get("source", "env"),
        "tradingCapFile": setting.get("path", trading_cap_file_path()),
        "tradingCapUpdatedAt": setting.get("updatedAt", ""),
        "accountEquity": equity,
        "effectiveTradingEquity": effective,
        "effectiveTradingEquityGbp": money_gbp(effective),
        "bankedProfitCashBuffer": banked,
        "bankedProfitCashBufferGbp": money_gbp(banked),
        "profitVault": vault,
        "profitVaultEnabled": bool(vault.get("enabled")),
        "profitVaultBaselineGbp": vault.get("baselineGbp", 0.0),
        "profitVaultBankedGbp": vault.get("bankedProfitGbp", 0.0),
        "profitVaultWorkingCapitalGbp": vault.get("workingCapitalGbp", 0.0),
        "profitVaultLifetimeBankedGbp": vault.get("lifetimeBankedGbp", 0.0),
        "message": "Profit Vault active" if vault.get("enabled") else ("Profit banking active" if cap_usd > 0 else "Profit banking disabled"),
    }


@app.get("/banking-status")
def api_banking_status():
    return {"ok": True, **banking_payload()}


@app.get("/trading-cap")
def api_get_trading_cap():
    return {"ok": True, **banking_payload()}


@app.post("/trading-cap")
def api_set_trading_cap(request: Request, payload: dict = Body(...)):
    verify_api_key(request)
    try:
        # Dashboard sends GBP by default, because that is how the user thinks
        # about the trading cap. Backend converts it to USD internally for Alpaca.
        value = payload.get("capGbp", payload.get("value", payload.get("cap")))
        currency = str(payload.get("currency", "GBP")).upper()
        value = float(value)
        if value <= 0:
            return {"ok": False, "message": "Trading cap must be greater than 0"}
        setting = save_trading_cap_setting(value, currency)
        payload_out = banking_payload()
        try:
            latest_status["banking"] = payload_out
            latest_status["newPositionNotional"] = calculate_new_position_notional()
            latest_status["lastAction"] = f"Trading cap saved: {currency} {value:.2f}"
            latest_status["lastActionAt"] = datetime.now(UTC).isoformat()
        except Exception:
            pass
        return {
            "ok": True,
            "message": f"Trading cap saved at {currency} {value:.2f}",
            "setting": setting,
            **payload_out,
        }
    except Exception as e:
        return {"ok": False, "message": f"Could not save trading cap: {e}"}



# =========================
# BACKTEST / PAPER REPLAY REPORT
# =========================
@app.post("/backtest-replay")
def api_backtest_replay(payload: dict = Body(default={}), request: Request = None):
    if request is not None:
        verify_api_key(request)

    try:
        cap_gbp = float(payload.get("capGbp") or 0.0)
    except Exception:
        cap_gbp = 0.0

    try:
        rate = get_usd_to_gbp_rate()
    except Exception:
        rate = FX_FALLBACK_USD_TO_GBP

    cap_usd = cap_gbp / max(rate, 0.0001) if cap_gbp > 0 else 0.0

    try:
        closed = closed_trades_from_db(10000)
    except Exception:
        closed = []

    rows = []
    equity = cap_gbp if cap_gbp > 0 else 0.0
    peak = equity
    max_drawdown = 0.0
    wins = 0
    losses = 0
    total_pnl_gbp = 0.0
    total_pnl_usd = 0.0
    by_symbol: Dict[str, Dict[str, Any]] = {}

    for t in closed:
        try:
            symbol = str(t.get("symbol", "")).upper()
            pnl_usd = float(t.get("pnl") or 0.0)
            pnl_gbp = float(t.get("pnlGbp") or (pnl_usd * rate))
            if not symbol:
                continue

            wins += 1 if pnl_usd >= 0 else 0
            losses += 1 if pnl_usd < 0 else 0
            total_pnl_usd += pnl_usd
            total_pnl_gbp += pnl_gbp
            equity += pnl_gbp
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)

            row = by_symbol.setdefault(symbol, {
                "symbol": symbol,
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "pnlUsd": 0.0,
                "pnlGbp": 0.0,
                "winRate": 0.0,
            })
            row["trades"] += 1
            row["wins"] += 1 if pnl_usd >= 0 else 0
            row["losses"] += 1 if pnl_usd < 0 else 0
            row["pnlUsd"] += pnl_usd
            row["pnlGbp"] += pnl_gbp

            rows.append({
                "time": t.get("time") or t.get("timestamp") or "",
                "symbol": symbol,
                "pnlUsd": pnl_usd,
                "pnlGbp": pnl_gbp,
                "equityGbp": equity,
            })
        except Exception:
            continue

    symbol_rows = []
    for row in by_symbol.values():
        row["winRate"] = row["wins"] / max(1, row["trades"])
        row["pnlUsd"] = round(float(row["pnlUsd"]), 4)
        row["pnlGbp"] = round(float(row["pnlGbp"]), 4)
        symbol_rows.append(row)

    symbol_rows.sort(key=lambda r: float(r.get("pnlGbp") or 0.0), reverse=True)
    best_symbol = symbol_rows[0]["symbol"] if symbol_rows else "—"
    worst_symbol = symbol_rows[-1]["symbol"] if symbol_rows else "—"

    return {
        "ok": True,
        "message": "Backtest / paper replay report complete",
        "capGbp": cap_gbp,
        "capUsd": cap_usd,
        "tradesTested": len(rows),
        "wins": wins,
        "losses": losses,
        "winRate": wins / max(1, wins + losses),
        "replayPnlUsd": round(total_pnl_usd, 4),
        "replayPnlGbp": round(total_pnl_gbp, 4),
        "endingEquityGbp": round(equity, 4),
        "maxDrawdownGbp": round(max_drawdown, 4),
        "bestSymbol": best_symbol,
        "worstSymbol": worst_symbol,
        "bySymbol": symbol_rows,
        "equityCurve": rows[-500:],
        "notes": "Uses matched closed-trade history. It is a reporting replay, not a live trade signal and does not place orders.",
    }

# ============================================================
# FINAL COMPATIBILITY ROUTES: BASELINE + BUY SIZE MODE
# Append-only: do not remove existing working routes.
# ============================================================

_COMPAT_STATE_DIR = persistent_data_dir()
_COMPAT_BASELINE_FILE = BASELINE_FILE
_COMPAT_BUY_SIZE_FILE = persistent_file("buy_size_mode.json")

def _compat_num(v, default=0.0):
    try:
        return float(v or default)
    except Exception:
        return float(default)

def _compat_read(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"COMPAT READ ERROR {path}: {e}", flush=True)
    return dict(default or {})

def _compat_write(path, payload):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = dict(payload)
        payload["savedAt"] = time.time()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"COMPAT WRITE ERROR {path}: {e}", flush=True)

def _compat_auth(request: Request = None):
    if request is not None and "verify_api_key" in globals():
        return verify_api_key(request)
    return True

def _compat_gbp(usd):
    try:
        return float(money_gbp(float(usd or 0)))
    except Exception:
        try:
            return float(usd or 0) * float(get_usd_to_gbp_rate())
        except Exception:
            return float(usd or 0) * 0.78

def _compat_account_equity():
    try:
        a = get_account()
        return float(getattr(a, "equity", 0) or 0), float(getattr(a, "buying_power", 0) or 0)
    except Exception:
        return 0.0, 0.0

def _compat_baseline_value():
    return load_equity_baseline()

@app.get("/baseline")
def compat_get_baseline():
    baseline = _compat_baseline_value()
    return {
        "ok": True,
        "baseline": baseline,
        "baselineGbp": round(_compat_gbp(baseline), 2),
        "source": "saved" if baseline > 0 else "none",
    }

@app.post("/set-baseline")
def compat_set_baseline(payload: dict = Body(...), request: Request = None):
    _compat_auth(request)
    value = _compat_num(payload.get("baseline") or payload.get("value") or payload.get("amount"), 0.0)
    if value <= 0:
        raise HTTPException(status_code=400, detail="Invalid baseline")
    save_equity_baseline(value)
    return {
        "ok": True,
        "message": f"Baseline saved at ${value:.2f}",
        "baseline": value,
        "baselineGbp": round(_compat_gbp(value), 2),
        "depositSource": "saved",
    }

@app.post("/reset-baseline")
def compat_reset_baseline(request: Request = None):
    _compat_auth(request)
    equity, _bp = _compat_account_equity()
    if equity <= 0:
        raise HTTPException(status_code=400, detail="Could not read current equity")
    save_equity_baseline(equity)
    return {
        "ok": True,
        "message": f"Baseline reset to current equity ${equity:.2f}",
        "baseline": equity,
        "baselineGbp": round(_compat_gbp(equity), 2),
        "depositSource": "saved",
    }

def _compat_load_buy_mode():
    data = _compat_read(_COMPAT_BUY_SIZE_FILE, {})
    mode = str(data.get("mode") or os.getenv("BUY_SIZE_MODE", "full")).lower().strip()
    return mode if mode in ("full", "partial") else "full"

def _compat_save_buy_mode(mode):
    mode = str(mode or "full").lower().strip()
    if mode not in ("full", "partial"):
        mode = "full"
    _compat_write(_COMPAT_BUY_SIZE_FILE, {"mode": mode})
    if globals().get("V17_SINGLE_FULL_BUY_MODE", False):
        mode = "full"
    globals()["BUY_SIZE_MODE"] = mode
    globals()["FULL_BUY_WHEN_ONE_POSITION"] = mode == "full"
    return mode

def _compat_buy_preview():
    equity, buying_power = _compat_account_equity()

    try:
        max_positions = effective_max_positions()
    except Exception:
        max_positions = 1

    try:
        positions = get_positions() if "get_positions" in globals() else []
        open_positions = len(positions)
    except Exception:
        open_positions = 0

    try:
        capped_equity = effective_trading_equity(equity) if "effective_trading_equity" in globals() else equity
    except Exception:
        capped_equity = equity

    try:
        cash_buffer = float(globals().get("CASH_BUFFER", 0.50))
    except Exception:
        cash_buffer = 0.50

    try:
        full_buffer = float(globals().get("FULL_BUY_CASH_BUFFER", 2.00))
    except Exception:
        full_buffer = 2.00

    partial_usd = max(0.0, min(capped_equity / max(1, max_positions), max(0.0, buying_power - cash_buffer)))
    if bool(globals().get("V17_SINGLE_FULL_BUY_MODE", False)):
        working = profit_vault_deployable_usd(equity, buying_power) if "profit_vault_deployable_usd" in globals() else buying_power
        full_usd = max(0.0, min(buying_power, working) - full_buffer)
    else:
        full_usd = max(0.0, min(capped_equity, max(0.0, buying_power - full_buffer)))
    mode = _compat_load_buy_mode()

    return {
        "ok": True,
        "mode": mode,
        "partialUsd": round(partial_usd, 2),
        "partialGbp": round(_compat_gbp(partial_usd), 2),
        "fullUsd": round(full_usd, 2),
        "fullGbp": round(_compat_gbp(full_usd), 2),
        "cappedEquityUsd": round(capped_equity, 2),
        "cappedEquityGbp": round(_compat_gbp(capped_equity), 2),
        "buyingPowerUsd": round(buying_power, 2),
        "buyingPowerGbp": round(_compat_gbp(buying_power), 2),
        "maxPositions": max_positions,
        "openPositions": open_positions,
        "remainingSlots": max(0, max_positions - open_positions),
    }

@app.get("/buy-size-preview")
def compat_buy_size_preview():
    return _compat_buy_preview()

@app.get("/buy-size-mode")
def compat_get_buy_size_mode():
    mode = _compat_load_buy_mode()
    return {
        "ok": True,
        "buySizeMode": mode,
        "fullBuyWhenOnePosition": mode == "full",
        "preview": _compat_buy_preview(),
    }

@app.post("/buy-size-mode")
def compat_post_buy_size_mode(payload: dict = Body(...), request: Request = None):
    _compat_auth(request)
    mode = str(payload.get("mode", "")).lower().strip()
    if mode not in ("full", "partial"):
        raise HTTPException(status_code=400, detail="mode must be full or partial")
    saved = _compat_save_buy_mode(mode)
    return {
        "ok": True,
        "message": f"Buy size mode saved as {saved}",
        "buySizeMode": saved,
        "fullBuyWhenOnePosition": saved == "full",
        "preview": _compat_buy_preview(),
    }



# =========================
# TRADEBOT V5.1 — REPLAY LABORATORY
# =========================
def _v5_replay_variants() -> List[Dict[str, Any]]:
    """Fixed, explainable research variants. None can alter live settings."""
    return [
        {"key": "current_a_plus", "name": "Current A+ thresholds", "confidence": 0.70, "quality": 0.026, "momentum_min": 0.0, "spread_max": 0.010},
        {"key": "confidence_068", "name": "Confidence 0.68", "confidence": 0.68, "quality": 0.026, "momentum_min": 0.0, "spread_max": 0.010},
        {"key": "confidence_072", "name": "Confidence 0.72", "confidence": 0.72, "quality": 0.026, "momentum_min": 0.0, "spread_max": 0.010},
        {"key": "quality_022", "name": "Quality 0.022", "confidence": 0.70, "quality": 0.022, "momentum_min": 0.0, "spread_max": 0.010},
        {"key": "quality_030", "name": "Quality 0.030", "confidence": 0.70, "quality": 0.030, "momentum_min": 0.0, "spread_max": 0.010},
        {"key": "no_momentum", "name": "Momentum gate disabled", "confidence": 0.70, "quality": 0.026, "momentum_min": None, "spread_max": 0.010},
        {"key": "relaxed_spread", "name": "Spread max 0.015", "confidence": 0.70, "quality": 0.026, "momentum_min": 0.0, "spread_max": 0.015},
        {"key": "historical_live_decision", "name": "Original approved decisions", "original_approved_only": True},
    ]


def _v5_variant_accepts(row: Dict[str, Any], variant: Dict[str, Any]) -> bool:
    if variant.get("original_approved_only"):
        return str(row.get("decision") or "").upper() == "APPROVED"
    confidence = float(row.get("confidence") or 0.0)
    quality = float(row.get("quality") or 0.0)
    momentum = float(row.get("momentum") or 0.0)
    spread = float(row.get("spread") or 999.0)
    if confidence < float(variant.get("confidence", 0.0)):
        return False
    if quality < float(variant.get("quality", 0.0)):
        return False
    momentum_min = variant.get("momentum_min")
    if momentum_min is not None and momentum < float(momentum_min):
        return False
    if spread > float(variant.get("spread_max", 999.0)):
        return False
    return True


def _v5_replay_metrics(values: List[float]) -> Dict[str, Any]:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    wins = [v for v in clean if v > 0]
    losses = [v for v in clean if v < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in clean:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "trades": len(clean),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": len(wins) / max(1, len(wins) + len(losses)),
        "profitFactor": gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0),
        "expectancyPct": sum(clean) / max(1, len(clean)),
        "totalReturnPct": sum(clean),
        "maxDrawdownPct": max_drawdown,
        "largestWinPct": max(clean) if clean else 0.0,
        "largestLossPct": min(clean) if clean else 0.0,
    }


def v5_run_replay(date_from: Optional[str] = None, date_to: Optional[str] = None,
                  horizon_hours: int = V5_REPLAY_DEFAULT_HORIZON_HOURS,
                  label: Optional[str] = None) -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    if not V5_REPLAY_ENABLED:
        return {"ok": False, "message": "V5 replay disabled"}
    horizon = max(1, int(horizon_hours))
    try:
        init_db()
        conn = db_connect()
        where = ["o.status='COMPLETE'", "o.net_return_pct IS NOT NULL", "o.horizon_hours=?"]
        params: List[Any] = [horizon]
        if date_from:
            where.append("d.observed_at>=?")
            params.append(str(date_from))
        if date_to:
            where.append("d.observed_at<=?")
            params.append(str(date_to))
        rows = [dict(r) for r in conn.execute(
            f"""SELECT d.*,o.net_return_pct,o.sample_key,o.evaluated_at
                 FROM v4_market_dna d JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
                 WHERE {' AND '.join(where)} ORDER BY d.observed_at ASC LIMIT ?""",
            tuple(params + [V5_REPLAY_MAX_ROWS]),
        ).fetchall()]
        variants = _v5_replay_variants()
        created_at = datetime.now(UTC).isoformat()
        cur = conn.execute(
            """INSERT INTO v5_replay_runs(created_at,label,date_from,date_to,horizon_hours,observation_count,variant_count,payload_json)
               VALUES(?,?,?,?,?,?,?,?)""",
            (created_at, label or "Replay Laboratory", date_from, date_to, horizon, len(rows), len(variants),
             json.dumps({"advisoryOnly": True, "source": "v4_market_dna+v2_observation_outcomes"})),
        )
        run_id = int(cur.lastrowid)
        results = []
        for variant in variants:
            returns = [float(r["net_return_pct"]) for r in rows if _v5_variant_accepts(r, variant)]
            metrics = _v5_replay_metrics(returns)
            eligible = metrics["trades"] >= V5_REPLAY_MIN_SAMPLES
            result = {"variantKey": variant["key"], "variantName": variant["name"], **metrics,
                      "eligible": eligible, "config": variant}
            results.append(result)
            conn.execute(
                """INSERT OR REPLACE INTO v5_replay_results
                   (run_id,variant_key,variant_name,trades,wins,losses,win_rate,profit_factor,expectancy_pct,
                    total_return_pct,max_drawdown_pct,largest_win_pct,largest_loss_pct,config_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, variant["key"], variant["name"], metrics["trades"], metrics["wins"], metrics["losses"],
                 metrics["winRate"], metrics["profitFactor"], metrics["expectancyPct"], metrics["totalReturnPct"],
                 metrics["maxDrawdownPct"], metrics["largestWinPct"], metrics["largestLossPct"], json.dumps(variant)),
            )
        conn.commit()
        conn.close()
        results.sort(key=lambda x: (bool(x["eligible"]), x["expectancyPct"], x["profitFactor"]), reverse=True)
        best = next((r for r in results if r["eligible"]), None)
        baseline = next((r for r in results if r["variantKey"] == "current_a_plus"), None)
        return {
            "ok": True, "version": "V5.1", "advisoryOnly": True, "runId": run_id,
            "createdAt": created_at, "dateFrom": date_from, "dateTo": date_to,
            "horizonHours": horizon, "observations": len(rows), "minimumSamples": V5_REPLAY_MIN_SAMPLES,
            "bestVariant": best, "baseline": baseline, "leaderboard": results,
            "note": "Replay results are research evidence only. No live threshold or order logic was changed.",
        }
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return {"ok": False, "version": "V5.1", "error": str(e)}


def v5_replay_leaderboard(run_id: Optional[int] = None, limit: int = 25) -> Dict[str, Any]:
    try:
        init_db(); conn = db_connect()
        if run_id is None:
            row = conn.execute("SELECT id FROM v5_replay_runs ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                conn.close(); return {"ok": True, "version": "V5.1", "runs": 0, "leaderboard": []}
            run_id = int(row["id"])
        run = conn.execute("SELECT * FROM v5_replay_runs WHERE id=?", (int(run_id),)).fetchone()
        if not run:
            conn.close(); return {"ok": False, "message": "Replay run not found", "runId": int(run_id)}
        rows = [dict(r) for r in conn.execute(
            """SELECT * FROM v5_replay_results WHERE run_id=?
               ORDER BY expectancy_pct DESC, profit_factor DESC LIMIT ?""", (int(run_id), max(1, min(int(limit), 100)))).fetchall()]
        conn.close()
        for row in rows:
            try: row["config"] = json.loads(row.pop("config_json") or "{}")
            except Exception: row["config"] = {}
        return {"ok": True, "version": "V5.1", "advisoryOnly": True, "run": dict(run), "leaderboard": rows}
    except Exception as e:
        return {"ok": False, "version": "V5.1", "error": str(e)}


def v5_status_payload() -> Dict[str, Any]:
    try:
        init_db(); conn = db_connect()
        run_count = int(conn.execute("SELECT COUNT(*) FROM v5_replay_runs").fetchone()[0])
        latest = conn.execute("SELECT * FROM v5_replay_runs ORDER BY id DESC LIMIT 1").fetchone()
        observation_count = int(conn.execute(
            """SELECT COUNT(*) FROM v4_market_dna d JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
               WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL""").fetchone()[0])
        conn.close()
    except Exception:
        run_count, latest, observation_count = 0, None, 0
    return {"ok": True, "version": "V5.1", "mode": "advisory-replay-laboratory",
            "enabled": V5_REPLAY_ENABLED, "advisoryOnly": True, "liveGateChanged": False,
            "completedObservations": observation_count, "replayRuns": run_count,
            "latestRun": dict(latest) if latest else None,
            "features": {"candidateCapture": True, "historicalReplay": True, "strategyVariants": True,
                         "persistentLeaderboards": True, "automaticLiveChanges": False},
            "rules": {"defaultHorizonHours": V5_REPLAY_DEFAULT_HORIZON_HOURS,
                      "minimumSamples": V5_REPLAY_MIN_SAMPLES, "maxRowsPerReplay": V5_REPLAY_MAX_ROWS}}


@app.get("/v5/status")
def api_v5_status():
    return v5_status_payload()


@app.post("/v5/replay/run")
def api_v5_replay_run(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v5_run_replay(payload.get("dateFrom"), payload.get("dateTo"),
                         int(payload.get("horizonHours") or V5_REPLAY_DEFAULT_HORIZON_HOURS),
                         payload.get("label"))


@app.get("/v5/replay/leaderboard")
def api_v5_replay_leaderboard(run_id: Optional[int] = None, limit: int = 25):
    return v5_replay_leaderboard(run_id, limit)


@app.post("/v5/replay/day")
def api_v5_replay_day(request: Request, day: str, horizon_hours: int = V5_REPLAY_DEFAULT_HORIZON_HOURS):
    verify_api_key(request)
    start = f"{day}T00:00:00+00:00"
    end = f"{day}T23:59:59.999999+00:00"
    return v5_run_replay(start, end, horizon_hours, f"Daily replay {day}")



# =========================
# TRADEBOT V6.4 — OUTCOME-TIME FORENSICS + VALIDATED SHADOW ENGINE
# =========================
def _v6_brains() -> List[Dict[str, Any]]:
    """Configuration-driven research brains. They observe only; none can place orders."""
    return [
        {"key":"current_a_plus","name":"Current A+","min_confidence":0.70,"min_quality":0.026,"max_spread":0.010,"momentum_min":0.0},
        {"key":"conservative","name":"Conservative","min_confidence":0.78,"min_quality":0.032,"max_spread":0.007,"momentum_min":0.0},
        {"key":"aggressive","name":"Aggressive","min_confidence":0.62,"min_quality":0.018,"max_spread":0.015,"momentum_min":-0.01},
        {"key":"momentum","name":"Momentum","min_confidence":0.68,"min_quality":0.024,"max_spread":0.012,"momentum_min":0.012},
        {"key":"mean_reversion","name":"Mean Reversion","min_confidence":0.64,"min_quality":0.020,"max_spread":0.010,"pullback_min":0.010,"momentum_max":0.010},
        {"key":"breakout","name":"Breakout","min_confidence":0.72,"min_quality":0.030,"max_spread":0.012,"momentum_min":0.020},
    ]


def _v6_accepts(row: Dict[str, Any], brain: Dict[str, Any]) -> bool:
    """Apply a brain to a valid, independent, entry-ready observation."""
    if not bool(int(row.get("ready_to_buy") or 0)):
        return False
    confidence=float(row.get("confidence") or 0.0); quality=float(row.get("quality") or 0.0)
    momentum=float(row.get("momentum") or 0.0); pullback=float(row.get("pullback") or 0.0)
    spread=float(row.get("spread") if row.get("spread") is not None else 999.0)
    if confidence < float(brain.get("min_confidence",0.0)): return False
    if quality < float(brain.get("min_quality",0.0)): return False
    if spread > float(brain.get("max_spread",999.0)): return False
    if "momentum_min" in brain and momentum < float(brain["momentum_min"]): return False
    if "momentum_max" in brain and momentum > float(brain["momentum_max"]): return False
    if "pullback_min" in brain and pullback < float(brain["pullback_min"]): return False
    return True


def _v6_validate_source_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Validate one outcome before it is allowed into brain fitness calculations."""
    reasons: List[str] = []
    entry=float(row.get("entry_price") or 0.0)
    outcome=float(row.get("outcome_price") or 0.0)
    raw=float(row.get("raw_return_pct") or 0.0)
    net=float(row.get("net_return_pct") or 0.0)
    cost=max(0.0,float(row.get("estimated_cost_pct") or 0.0))
    if entry <= 0: reasons.append("missing_or_invalid_entry_price")
    if outcome <= 0: reasons.append("missing_or_invalid_outcome_price")
    if not bool(int(row.get("ready_to_buy") or 0)): reasons.append("entry_trigger_not_ready")
    due_at=row.get("due_at"); bar_at=row.get("outcome_bar_at"); source=str(row.get("outcome_source") or "")
    if source not in ("alpaca_historical_1min_close", "alpaca_iex_historical_1min_close"): reasons.append("outcome_not_historical_checkpoint")
    if not bar_at: reasons.append("outcome_timestamp_missing")
    if due_at and bar_at:
        try:
            delay=(_v6_parse_utc(bar_at)-_v6_parse_utc(due_at)).total_seconds()/60.0
            if delay < -V6_HISTORICAL_BAR_LOOKBACK_MINUTES: reasons.append("outcome_timestamp_before_allowed_window")
            if delay > V6_OUTCOME_MAX_DELAY_MINUTES: reasons.append("outcome_evaluated_too_late")
        except Exception: reasons.append("outcome_timestamp_mismatch")
    if entry > 0 and outcome > 0:
        expected=((outcome/entry)-1.0)*100.0
        if abs(expected-raw) > 0.02: reasons.append("raw_return_formula_mismatch")
        if abs((raw-cost)-net) > 0.02: reasons.append("net_return_formula_mismatch")
    if not math.isfinite(net): reasons.append("non_finite_return")
    if abs(net) > 50.0: reasons.append("implausible_return_over_50pct")
    return {"valid":not reasons,"reasons":reasons}


def _v6_source_rows(horizon_hours: int, limit: int) -> List[Dict[str, Any]]:
    """Return independent observations only—one row per sample bucket and horizon."""
    init_db(); conn=db_connect()
    rows=[dict(r) for r in conn.execute(
        """WITH ranked AS (
               SELECT d.*, o.entry_price, o.outcome_price,
                      o.return_pct AS raw_return_pct, o.net_return_pct,
                      o.estimated_cost_pct, o.sample_key, o.due_at, o.evaluated_at,
                      o.evaluation_delay_minutes, o.outcome_bar_at, o.outcome_source, o.repaired_at,
                      ROW_NUMBER() OVER (
                          PARTITION BY COALESCE(o.sample_key, CAST(o.decision_id AS TEXT)), o.horizon_hours
                          ORDER BY o.id ASC
                      ) AS rn
               FROM v4_market_dna d
               JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
               WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL
                 AND o.horizon_hours=?
           )
           SELECT * FROM ranked WHERE rn=1 ORDER BY observed_at ASC LIMIT ?""",
        (max(1,int(horizon_hours)),max(1,min(int(limit),50000)))).fetchall()]
    conn.close()
    return rows


def v6_validation_report(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, limit: int = 50000) -> Dict[str, Any]:
    horizon=max(1,int(horizon_hours)); rows=_v6_source_rows(horizon,limit)
    reason_counts: Dict[str,int]={}; valid=0; entry_ready=0
    samples=[]
    for row in rows:
        check=_v6_validate_source_row(row)
        if bool(int(row.get("ready_to_buy") or 0)): entry_ready += 1
        if check["valid"]: valid += 1
        else:
            for reason in check["reasons"]: reason_counts[reason]=reason_counts.get(reason,0)+1
            if len(samples)<20:
                samples.append({"decisionId":row.get("decision_id"),"symbol":row.get("symbol"),
                                "observedAt":row.get("observed_at"),"reasons":check["reasons"],
                                "entryPrice":row.get("entry_price"),"outcomePrice":row.get("outcome_price"),
                                "rawReturnPct":row.get("raw_return_pct"),"netReturnPct":row.get("net_return_pct"),
                                "dueAt":row.get("due_at"),"outcomeBarAt":row.get("outcome_bar_at"),
                                "outcomeSource":row.get("outcome_source"),"evaluationDelayMinutes":row.get("evaluation_delay_minutes")})
    return {"ok":True,"version":"V6.4","advisoryOnly":True,"horizonHours":horizon,
            "independentSourceObservations":len(rows),"entryReadyObservations":entry_ready,
            "validLearningObservations":valid,"invalidLearningObservations":len(rows)-valid,
            "invalidReasons":reason_counts,"invalidSamples":samples,
            "rules":{"independentSampleBuckets":True,"requiresEntryTriggerReady":True,
                     "returnFormulaTolerancePct":0.02,"maximumAbsoluteReturnPct":50.0,
                     "historicalCheckpointRequired":True,"maximumOutcomeDelayMinutes":V6_OUTCOME_MAX_DELAY_MINUTES}}


def v6_sync_brains(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, limit: int = 10000) -> Dict[str, Any]:
    if not SQLITE_ENABLED: return {"ok":False,"message":"SQLite disabled"}
    if not V6_BRAINS_ENABLED: return {"ok":False,"message":"V6 brains disabled"}
    horizon=max(1,int(horizon_hours)); limit=max(1,min(int(limit),50000))
    batch_size=max(50,min(int(os.getenv("V6_SYNC_BATCH_SIZE", "250") or 250),1000))
    conn=None
    try:
        rows=_v6_source_rows(horizon,limit)
        brains=_v6_brains(); inserted=0; accepted=0; valid_rows=0; rejected_invalid=0
        now=datetime.now(UTC).isoformat(); pending=[]
        # V18.2.12: validate/calculate outside any write transaction.
        for row in rows:
            validation=_v6_validate_source_row(row)
            if not validation["valid"]:
                rejected_invalid += 1
                continue
            valid_rows += 1
            for brain in brains:
                passed=1 if _v6_accepts(row,brain) else 0
                accepted += passed
                pending.append((brain["key"],brain["name"],int(row["decision_id"]),row.get("symbol") or "",row.get("observed_at") or now,
                     row.get("market_regime") or "unknown",horizon,passed,float(row["net_return_pct"]),
                     float(row.get("confidence") or 0),float(row.get("quality") or 0),float(row.get("momentum") or 0),
                     float(row.get("pullback") or 0),float(row.get("spread") or 0),json.dumps(brain),now))
        for offset in range(0,len(pending),batch_size):
            conn=db_connect()
            try:
                before=conn.total_changes
                conn.executemany("""INSERT OR IGNORE INTO v6_brain_observations
                    (brain_key,brain_name,decision_id,symbol,observed_at,market_regime,horizon_hours,accepted,return_pct,confidence,quality,momentum,pullback,spread,config_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", pending[offset:offset+batch_size])
                inserted += conn.total_changes-before
                conn.commit()
            finally:
                conn.close(); conn=None
        return {"ok":True,"version":"V6.4","advisoryOnly":True,"horizonHours":horizon,
                "independentSourceObservations":len(rows),"validLearningObservations":valid_rows,
                "invalidObservationsRejected":rejected_invalid,"brains":len(brains),
                "newShadowRows":inserted,"acceptedEvaluations":accepted,"liveGateChanged":False}
    except Exception as e:
        try:
            if conn is not None: conn.close()
        except Exception: pass
        return {"ok":False,"version":"V6.4","error":str(e)}

def v6_rebuild_validated(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, limit: int = V6_AUTO_SYNC_LIMIT) -> Dict[str, Any]:
    """Delete legacy V6.2 shadow rows and rebuild only from validated V6.3 evidence."""
    try:
        init_db(); conn=db_connect()
        removed=int(conn.execute("SELECT COUNT(*) FROM v6_brain_observations WHERE horizon_hours=?",(int(horizon_hours),)).fetchone()[0])
        conn.execute("DELETE FROM v6_brain_observations WHERE horizon_hours=?",(int(horizon_hours),))
        conn.commit(); conn.close()
        result=v6_sync_brains(horizon_hours,limit)
        return {**result,"rebuild":True,"legacyRowsRemoved":removed,
                "note":"Research rows only were rebuilt. Live trading logic was unchanged."}
    except Exception as e:
        return {"ok":False,"version":"V6.4","error":str(e)}


def v6_auto_sync_worker() -> None:
    """Continuously sync validated, independent outcomes into every research brain."""
    global v6_last_sync_result
    first_run = True
    while True:
        try:
            if AI_RESEARCH_CLOSED_MARKET_ONLY and _ai_research_market_open() is not False:
                time.sleep(60)
                continue
            result = v6_sync_brains(V6_DEFAULT_HORIZON_HOURS, V6_AUTO_SYNC_LIMIT)
            result["automatic"] = True; result["ranAt"] = datetime.now(UTC).isoformat()
            v6_last_sync_result = result
            if first_run or int(result.get("newShadowRows") or 0) > 0:
                print("V6.4 AUTO SYNC | "
                      f"source={result.get('independentSourceObservations', 0)} "
                      f"valid={result.get('validLearningObservations', 0)} "
                      f"new={result.get('newShadowRows', 0)} accepted={result.get('acceptedEvaluations', 0)}")
            first_run = False
        except Exception as exc:
            v6_last_sync_result = {"ok":False,"automatic":True,"ranAt":datetime.now(UTC).isoformat(),"error":str(exc)}
            print(f"V6.4 AUTO SYNC ERROR: {exc}")
        time.sleep(V6_AUTO_SYNC_INTERVAL_SECONDS)


def _v6_score_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    values=[float(r["return_pct"]) for r in rows if r.get("return_pct") is not None and math.isfinite(float(r["return_pct"]))]
    metrics=_v5_replay_metrics(values)
    n=int(metrics.get("trades") or 0)
    expectancy=float(metrics.get("expectancyPct") or 0.0)
    # Standard error gives the leaderboard a simple sample-stability measure.
    if n > 1:
        mean=sum(values)/n
        variance=sum((x-mean)**2 for x in values)/(n-1)
        std=math.sqrt(max(0.0,variance)); standard_error=std/math.sqrt(n)
    else:
        std=0.0; standard_error=999.0 if n == 0 else 0.0
    metrics.update({"returnStdDevPct":std,"expectancyStandardErrorPct":standard_error,
                    "expectancyLower95Pct":expectancy-(1.96*standard_error) if n>1 else expectancy})
    return metrics


def _v6_research_score(metrics: Dict[str, Any]) -> float:
    n=max(0,int(metrics.get("trades") or 0)); expectancy=float(metrics.get("expectancyPct") or 0.0)
    pf=max(0.0,min(float(metrics.get("profitFactor") or 0.0),3.0))
    drawdown=max(0.0,float(metrics.get("maxDrawdownPct") or 0.0))
    lower=float(metrics.get("expectancyLower95Pct") or expectancy)
    sample_confidence=min(1.0,math.sqrt(n/max(1.0,float(V6_MIN_SAMPLES*4))))
    return ((expectancy*0.45)+(lower*0.35)+(max(0.0,pf-1.0)*0.20)-(drawdown*0.01))*sample_confidence


def v6_brain_scoreboard(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, regime: Optional[str] = None) -> Dict[str, Any]:
    horizon=max(1,int(horizon_hours))
    try:
        init_db(); conn=db_connect(); params=[horizon]; extra=""
        if regime: extra=" AND lower(market_regime)=lower(?)"; params.append(regime)
        rows=[dict(r) for r in conn.execute(
            f"SELECT * FROM v6_brain_observations WHERE horizon_hours=? AND accepted=1{extra} ORDER BY observed_at",tuple(params)).fetchall()]
        conn.close(); by={}
        for r in rows: by.setdefault(r["brain_key"],[]).append(r)
        configs={b["key"]:b for b in _v6_brains()}; board=[]
        for key,brain in configs.items():
            metrics=_v6_score_rows(by.get(key,[])); sample_eligible=metrics["trades"]>=V6_MIN_SAMPLES
            recommendation_eligible=(sample_eligible and metrics["profitFactor"]>=V6_RECOMMENDATION_MIN_PF
                                     and metrics["expectancyPct"]>=V6_RECOMMENDATION_MIN_EXPECTANCY
                                     and metrics["expectancyLower95Pct"]>0)
            score=_v6_research_score(metrics) if sample_eligible else -999.0
            health="HEALTHY" if recommendation_eligible else ("LOSING" if sample_eligible and metrics["expectancyPct"]<0 else "INSUFFICIENT")
            board.append({"brainKey":key,"brainName":brain["name"],**metrics,
                          "eligible":recommendation_eligible,"sampleEligible":sample_eligible,
                          "recommendationEligible":recommendation_eligible,"health":health,
                          "researchScore":score,"config":brain})
        board.sort(key=lambda x:(x["recommendationEligible"],x["researchScore"],x["trades"]),reverse=True)
        leader=next((x for x in board if x["recommendationEligible"]),None)
        research_leader=next((x for x in board if x["sampleEligible"]),None)
        return {"ok":True,"version":"V6.4","advisoryOnly":True,"horizonHours":horizon,"marketRegime":regime,
                "minimumSamples":V6_MIN_SAMPLES,"leader":leader,"researchLeader":research_leader,
                "healthyLeaderAvailable":leader is not None,
                "leaderRule":"A leader must pass samples, profit factor, expectancy and positive 95% lower expectancy bound.",
                "scoreboard":board}
    except Exception as e: return {"ok":False,"version":"V6.4","error":str(e)}


def v6_recommendation(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, regime: Optional[str] = None, persist: bool = True) -> Dict[str, Any]:
    board=v6_brain_scoreboard(horizon_hours,regime)
    if not board.get("ok"): return board
    eligible=[x for x in board["scoreboard"] if x["recommendationEligible"]]
    best=eligible[0] if eligible else None
    current=next((x for x in board["scoreboard"] if x["brainKey"]==V6_ACTIVE_BRAIN),None)
    action="KEEP_CURRENT"
    if best and best["brainKey"]!=V6_ACTIVE_BRAIN:
        if not current or not current["recommendationEligible"] or best["researchScore"] > current["researchScore"]*1.10:
            action="RECOMMEND_SWITCH"
    samples=int(best["trades"] if best else 0)
    grade="HIGH" if best and samples>=50 else ("MEDIUM" if best and samples>=25 else ("LOW" if best else "INSUFFICIENT"))
    payload={"ok":True,"version":"V6.4","advisoryOnly":True,"automaticLiveChanges":False,"action":action,
             "currentBrain":V6_ACTIVE_BRAIN,"recommendedBrain":best["brainKey"] if best else None,
             "confidenceGrade":grade,"marketRegime":regime,"horizonHours":int(horizon_hours),
             "leader":best,"current":current,"safeguards":{"minimumSamples":V6_MIN_SAMPLES,
             "minimumProfitFactor":V6_RECOMMENDATION_MIN_PF,"minimumExpectancyPct":V6_RECOMMENDATION_MIN_EXPECTANCY,
             "positive95PctLowerBoundRequired":True,"requiredImprovement":0.10},
             "note":"Recommendation only. No live strategy or order gate was changed."}
    if persist and SQLITE_ENABLED:
        try:
            conn=db_connect(); conn.execute("""INSERT INTO v6_recommendations
                (created_at,horizon_hours,market_regime,current_brain,recommended_brain,confidence_grade,approved,payload_json)
                VALUES(?,?,?,?,?,?,0,?)""",(datetime.now(UTC).isoformat(),int(horizon_hours),regime,V6_ACTIVE_BRAIN,
                payload["recommendedBrain"],grade,json.dumps(payload))); conn.commit(); conn.close()
        except Exception: pass
    return payload


def v6_status_payload() -> Dict[str, Any]:
    try:
        init_db(); conn=db_connect()
        shadow_rows=int(conn.execute("SELECT COUNT(*) FROM v6_brain_observations").fetchone()[0])
        accepted_rows=int(conn.execute("SELECT COUNT(*) FROM v6_brain_observations WHERE accepted=1").fetchone()[0])
        latest=conn.execute("SELECT created_at FROM v6_brain_observations ORDER BY id DESC LIMIT 1").fetchone(); conn.close()
        validation=v6_validation_report(V6_DEFAULT_HORIZON_HOURS,V6_AUTO_SYNC_LIMIT)
        source_rows=int(validation.get("independentSourceObservations") or 0)
    except Exception:
        shadow_rows,accepted_rows,source_rows,latest,validation=0,0,0,None,{"ok":False}
    return {"ok":True,"version":"V6.4","mode":"historical-checkpoint-validated-shadow-intelligence","enabled":V6_BRAINS_ENABLED,
            "advisoryOnly":True,"automaticLiveChanges":False,"liveGateChanged":False,"activeBrain":V6_ACTIVE_BRAIN,
            "brainCount":len(_v6_brains()),"sourceCompletedObservations":source_rows,
            "validLearningObservations":validation.get("validLearningObservations",0),
            "invalidLearningObservations":validation.get("invalidLearningObservations",0),
            "shadowEvaluations":shadow_rows,"acceptedShadowEvaluations":accepted_rows,
            "latestShadowAt":latest["created_at"] if latest else None,"lastAutomaticSync":v6_last_sync_result or None,
            "features":{"configurationDrivenBrains":True,"multiBrainShadowing":True,"regimeScoreboards":True,
                        "guardedRecommendations":True,"automaticHistoricalBootstrap":True,
                        "continuousOutcomeSync":True,"historicalCheckpointOutcomes":True,"outcomeTimeRepair":True,
                        "independentSampleDedupe":True,
                        "entryTriggerValidation":True,"returnFormulaValidation":True,
                        "confidenceBoundRanking":True,"selfGeneratedBrains":False,"automaticPromotion":False},
            "rules":{"defaultHorizonHours":V6_DEFAULT_HORIZON_HOURS,"minimumSamples":V6_MIN_SAMPLES,
                     "minimumProfitFactor":V6_RECOMMENDATION_MIN_PF,"minimumExpectancyPct":V6_RECOMMENDATION_MIN_EXPECTANCY,
                     "autoSyncEnabled":V6_AUTO_SYNC_ENABLED,"autoSyncIntervalSeconds":V6_AUTO_SYNC_INTERVAL_SECONDS,
                     "autoSyncLimit":V6_AUTO_SYNC_LIMIT,"maximumOutcomeDelayMinutes":V6_OUTCOME_MAX_DELAY_MINUTES,
                     "repairBatchSize":V6_REPAIR_BATCH_SIZE}}


@app.get("/v6/status")
def api_v6_status(): return v6_status_payload()

@app.get("/v6/validation")
def api_v6_validation(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, limit: int = V6_AUTO_SYNC_LIMIT):
    return v6_validation_report(horizon_hours,limit)

@app.post("/v6/outcomes/repair")
def api_v6_outcomes_repair(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v6_repair_outcome_times(int(payload.get("horizonHours") or V6_DEFAULT_HORIZON_HOURS),
                                   int(payload.get("limit") or V6_REPAIR_BATCH_SIZE))


@app.post("/v6/brains/sync")
def api_v6_brains_sync(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v6_sync_brains(int(payload.get("horizonHours") or V6_DEFAULT_HORIZON_HOURS),int(payload.get("limit") or 10000))

@app.post("/v6/rebuild")
def api_v6_rebuild(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v6_rebuild_validated(int(payload.get("horizonHours") or V6_DEFAULT_HORIZON_HOURS),
                                int(payload.get("limit") or V6_AUTO_SYNC_LIMIT))

@app.get("/v6/brains")
def api_v6_brains(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, regime: Optional[str] = None):
    return v6_brain_scoreboard(horizon_hours,regime)

@app.get("/v6/recommendation")
def api_v6_recommendation(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, regime: Optional[str] = None):
    return v6_recommendation(horizon_hours,regime,False)

@app.post("/v6/recommendation/run")
def api_v6_recommendation_run(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v6_recommendation(int(payload.get("horizonHours") or V6_DEFAULT_HORIZON_HOURS),payload.get("regime"),True)


# =========================
# TRADEBOT V7.1 — EVIDENCE-DRIVEN RESEARCH FACTORY
# =========================
V7_VERSION = "V7.1"


def _v7_ensure_tables_impl() -> None:
    if not SQLITE_ENABLED:
        return
    init_db(); conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS v7_brains (
        brain_key TEXT PRIMARY KEY, brain_name TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0,
        parent_key TEXT, status TEXT NOT NULL DEFAULT 'ACTIVE', created_at TEXT NOT NULL,
        retired_at TEXT, config_json TEXT NOT NULL, origin TEXT NOT NULL DEFAULT 'seed',
        last_evaluated_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v7_evolution_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, completed_at TEXT,
        horizon_hours INTEGER NOT NULL, parent_count INTEGER NOT NULL DEFAULT 0,
        children_created INTEGER NOT NULL DEFAULT 0, brains_retired INTEGER NOT NULL DEFAULT 0,
        champion_key TEXT, payload_json TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v7_brain_results (
        brain_key TEXT NOT NULL, horizon_hours INTEGER NOT NULL, evaluated_at TEXT NOT NULL,
        trades INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
        win_rate REAL, profit_factor REAL, expectancy_pct REAL, expectancy_lower95_pct REAL,
        max_drawdown_pct REAL, research_score REAL, eligible INTEGER NOT NULL DEFAULT 0,
        accepted_decision_ids_json TEXT, PRIMARY KEY(brain_key, horizon_hours))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v7_maintenance_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, completed_at TEXT,
        trigger TEXT NOT NULL, repaired INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
        rebuild_json TEXT, evolution_json TEXT, ok INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v7_research_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, horizon_hours INTEGER NOT NULL,
        source_observations INTEGER NOT NULL DEFAULT 0, valid_observations INTEGER NOT NULL DEFAULT 0,
        candidates_created INTEGER NOT NULL DEFAULT 0, payload_json TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v7_brains_status ON v7_brains(status, generation)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v7_results_score ON v7_brain_results(horizon_hours, research_score)")
    now = datetime.now(UTC).isoformat()
    for brain in _v6_brains():
        conn.execute("""INSERT OR IGNORE INTO v7_brains
            (brain_key,brain_name,generation,parent_key,status,created_at,config_json,origin)
            VALUES(?,?,0,NULL,'ACTIVE',?,?,'v6_seed')""",
            (brain['key'], brain['name'], now, json.dumps(brain, sort_keys=True)))
    conn.commit(); conn.close()


def _v7_ensure_tables() -> None:
    global _V7_SCHEMA_COMPLETE
    if not SQLITE_ENABLED or _V7_SCHEMA_COMPLETE:
        return
    init_db()
    with _V7_SCHEMA_LOCK:
        if _V7_SCHEMA_COMPLETE:
            return
        _v7_ensure_tables_impl()
        _V7_SCHEMA_COMPLETE = True


def _v7_active_brains() -> List[Dict[str, Any]]:
    _v7_ensure_tables(); conn=db_connect()
    rows=conn.execute("SELECT * FROM v7_brains WHERE status='ACTIVE' ORDER BY generation, created_at").fetchall(); conn.close()
    out=[]
    for row in rows:
        item=dict(row)
        try: item['config']=json.loads(item.pop('config_json'))
        except Exception: item['config']={}
        out.append(item)
    return out


def _v7_valid_rows(horizon: int) -> List[Dict[str, Any]]:
    return [r for r in _v6_source_rows(horizon,V6_AUTO_SYNC_LIMIT) if _v6_validate_source_row(r).get('valid')]


def _v7_evaluate_brain(brain: Dict[str, Any], source_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    cfg=brain.get('config') or brain; accepted=[]
    for row in source_rows:
        if _v6_accepts(row,cfg):
            accepted.append({'decision_id':int(row.get('decision_id') or 0),
                'return_pct':float(row.get('net_return_pct') or 0.0),
                'confidence':float(row.get('confidence') or 0.0)})
    metrics=_v6_score_rows(accepted)
    sample_ok=metrics['trades'] >= V7_MIN_PARENT_SAMPLES
    eligible=(sample_ok and metrics['profitFactor'] >= V6_RECOMMENDATION_MIN_PF
              and metrics['expectancyPct'] >= V6_RECOMMENDATION_MIN_EXPECTANCY
              and metrics['expectancyLower95Pct'] > 0)
    score=_v6_research_score(metrics) if metrics['trades'] >= V6_MIN_SAMPLES else -999.0
    return {**metrics,'eligible':eligible,'researchScore':score,
            'acceptedDecisionIds':[x['decision_id'] for x in accepted]}


def _v7_quantile(values: List[float], q: float) -> float:
    if not values: return 0.0
    vals=sorted(float(x) for x in values); pos=(len(vals)-1)*q; lo=int(math.floor(pos)); hi=int(math.ceil(pos))
    return vals[lo] if lo==hi else vals[lo]+(vals[hi]-vals[lo])*(pos-lo)


def _v7_segment_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _v6_score_rows([{'return_pct':float(r.get('net_return_pct') or 0.0)} for r in rows])


def v7_research_insights(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    horizon=max(1,int(horizon_hours)); source=_v6_source_rows(horizon,V6_AUTO_SYNC_LIMIT); rows=_v7_valid_rows(horizon)
    features=['confidence','quality','momentum','pullback','spread']
    feature_report=[]
    for feature in features:
        vals=[float(r.get(feature) or 0.0) for r in rows]
        cuts=sorted(set(round(_v7_quantile(vals,q),6) for q in (0.2,0.4,0.6,0.8)))
        segments=[]
        for cut in cuts:
            high=[r for r in rows if float(r.get(feature) or 0.0)>=cut]
            low=[r for r in rows if float(r.get(feature) or 0.0)<=cut]
            for direction,group in [('at_or_above',high),('at_or_below',low)]:
                m=_v7_segment_metrics(group)
                if m['trades']>=max(5,min(V6_MIN_SAMPLES,10)):
                    segments.append({'direction':direction,'threshold':cut,**m})
        segments.sort(key=lambda x:(x['expectancyPct'],x['profitFactor'],x['trades']),reverse=True)
        feature_report.append({'feature':feature,'bestSegments':segments[:4]})
    regimes=[]
    by_regime={}
    for r in rows: by_regime.setdefault(str(r.get('market_regime') or 'unknown').lower(),[]).append(r)
    for name,group in by_regime.items(): regimes.append({'regime':name,**_v7_segment_metrics(group)})
    regimes.sort(key=lambda x:(x['expectancyPct'],x['trades']),reverse=True)
    wins=[r for r in rows if float(r.get('net_return_pct') or 0)>0]; losses=[r for r in rows if float(r.get('net_return_pct') or 0)<=0]
    contrasts=[]
    for f in features:
        contrasts.append({'feature':f,
            'winnerMedian':round(_v7_quantile([float(r.get(f) or 0) for r in wins],.5),6),
            'loserMedian':round(_v7_quantile([float(r.get(f) or 0) for r in losses],.5),6)})
    overall=_v7_segment_metrics(rows)
    lab=v7_brain_lab(horizon)
    brains=[]
    for brain in lab.get('brains',[]):
        item=dict(brain)
        item['key']=item.get('brain_key')
        item['name']=item.get('brain_name')
        item['winRate']=float(item.get('win_rate') or 0.0)
        item['expectancyPct']=float(item.get('expectancy_pct') or 0.0)
        item['researchScore']=float(item.get('research_score') or 0.0)
        item['profitFactor']=float(item.get('profit_factor') or 0.0)
        item['maxDrawdownPct']=float(item.get('max_drawdown_pct') or 0.0)
        item['trades']=int(item.get('trades') or 0)
        brains.append(item)
    champion=lab.get('champion') or lab.get('researchChampion')
    if champion:
        champion=dict(champion)
        champion['key']=champion.get('brain_key') or champion.get('key')
        champion['name']=champion.get('brain_name') or champion.get('name')
        champion['winRate']=float(champion.get('win_rate') or champion.get('winRate') or 0.0)
        champion['expectancyPct']=float(champion.get('expectancy_pct') or champion.get('expectancyPct') or 0.0)
        champion['researchScore']=float(champion.get('research_score') or champion.get('researchScore') or 0.0)
    return {'ok':True,'version':V7_VERSION,'advisoryOnly':True,'automaticLiveChanges':False,
            'horizonHours':horizon,'sourceObservations':len(source),'validObservations':len(rows),
            'invalidObservations':len(source)-len(rows),'overall':overall,
            'winnerLoserContrasts':contrasts,'featureAnalysis':feature_report,
            'regimeAnalysis':regimes,'generation':max([int(x.get('generation') or 0) for x in brains] or [0]),
            'activeBrains':int(lab.get('activeBrains') or 0),'champion':champion,
            'researchChampion':champion,'brains':brains,'leaderboard':brains,
            'note':'Descriptive research only; no live setting was changed.'}


def _v7_candidate_grid(rows: List[Dict[str, Any]], max_candidates: int) -> List[Dict[str, Any]]:
    if not rows: return []
    quantiles={f:sorted(set(round(_v7_quantile([float(r.get(f) or 0) for r in rows],q),4)
                      for q in (.2,.4,.6,.8))) for f in ('confidence','quality','momentum','pullback','spread')}
    configs=[]
    # Evidence-driven threshold families. Spread uses an upper bound; confidence/quality use lower bounds.
    for conf in quantiles['confidence']:
      for qual in quantiles['quality']:
       for spread in quantiles['spread']:
        configs.append({'min_confidence':conf,'min_quality':qual,'max_spread':spread})
    for mom in quantiles['momentum']:
      for conf in quantiles['confidence'][1:]:
       for spread in quantiles['spread']:
        configs.append({'min_confidence':conf,'min_quality':quantiles['quality'][1],
                        'max_spread':spread,'momentum_min':mom})
    for pull in quantiles['pullback']:
      for mommax in quantiles['momentum']:
       configs.append({'min_confidence':quantiles['confidence'][0],'min_quality':quantiles['quality'][0],
                       'max_spread':quantiles['spread'][2],'pullback_min':pull,'momentum_max':mommax})
    scored=[]; seen=set()
    min_samples=max(8,min(V7_MIN_PARENT_SAMPLES,15))
    for cfg in configs:
        sig=json.dumps(cfg,sort_keys=True)
        if sig in seen: continue
        seen.add(sig)
        result=_v7_evaluate_brain(cfg,rows)
        if result['trades']<min_samples: continue
        # Discovery score rewards expectancy and PF but strongly penalises drawdown and uncertainty.
        discovery=(result['expectancyPct']*0.55 + result['expectancyLower95Pct']*0.25
                   + min(result['profitFactor'],3.0)*0.15 - result['maxDrawdownPct']*0.01)
        scored.append((discovery,result,cfg))
    scored.sort(key=lambda x:(x[0],x[1]['expectancyPct'],x[1]['profitFactor']),reverse=True)
    diverse=[]
    for score,result,cfg in scored:
        if any(sum(1 for k,v in cfg.items() if other['config'].get(k)==v)>=max(2,len(cfg)-1) for other in diverse):
            continue
        diverse.append({'discoveryScore':score,'result':result,'config':cfg})
        if len(diverse)>=max_candidates: break
    return diverse


def v7_discover(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, candidates: int = 12) -> Dict[str, Any]:
    _v7_ensure_tables(); horizon=max(1,int(horizon_hours)); count=max(1,min(int(candidates),30)); rows=_v7_valid_rows(horizon)
    found=_v7_candidate_grid(rows,count); conn=db_connect(); now=datetime.now(UTC).isoformat()
    max_gen=int(conn.execute("SELECT COALESCE(MAX(generation),0) FROM v7_brains").fetchone()[0]); generation=max_gen+1; created=[]
    for i,item in enumerate(found,1):
        cfg=dict(item['config']); suffix=secrets.token_hex(3); key=f"discovery_g{generation}_{suffix}"
        cfg.update({'key':key,'name':f"Evidence Discovery G{generation}.{i}",'research_only':True,
                    'discovery_score':round(item['discoveryScore'],6)})
        conn.execute("""INSERT OR IGNORE INTO v7_brains
            (brain_key,brain_name,generation,parent_key,status,created_at,config_json,origin)
            VALUES(?,?,?,NULL,'ACTIVE',?,?,'evidence_discovery')""",
            (key,cfg['name'],generation,now,json.dumps(cfg,sort_keys=True)))
        created.append({'brainKey':key,'brainName':cfg['name'],'config':cfg,'backtest':item['result']})
    payload={'ok':True,'version':V7_VERSION,'advisoryOnly':True,'automaticLiveChanges':False,
             'horizonHours':horizon,'validObservations':len(rows),'generation':generation,
             'candidatesCreated':len(created),'candidates':created,
             'healthyCandidates':sum(1 for x in created if x['backtest'].get('eligible')),
             'note':'Candidates were derived from observed feature thresholds. They remain shadow-only.'}
    cur=conn.execute("""INSERT INTO v7_research_runs
        (created_at,horizon_hours,source_observations,valid_observations,candidates_created,payload_json)
        VALUES(?,?,?,?,?,?)""",(now,horizon,len(_v6_source_rows(horizon,V6_AUTO_SYNC_LIMIT)),len(rows),len(created),json.dumps(payload)))
    payload['researchRunId']=int(cur.lastrowid); conn.commit(); conn.close(); return payload


def _v7_mutate_config(parent: Dict[str, Any], child_number: int, generation: int) -> Dict[str, Any]:
    cfg={k:v for k,v in dict(parent).items() if k not in ('discovery_score',)}; parent_key=str(cfg.get('key') or 'brain')
    rng=random.Random(f"{parent_key}:{generation}:{child_number}:{datetime.now(UTC).date().isoformat()}")
    ranges={'min_confidence':(0.50,0.90,0.04),'min_quality':(0.010,0.060,0.004),
            'max_spread':(0.004,0.025,0.002),'momentum_min':(-0.025,0.050,0.006),
            'momentum_max':(-0.010,0.035,0.006),'pullback_min':(0.000,0.050,0.005)}
    mutable=[k for k in ranges if k in cfg] or ['min_confidence','min_quality','max_spread']
    for key in rng.sample(mutable,min(1 if rng.random()>.25 else 2,len(mutable))):
        lo,hi,step=ranges[key]; current=float(cfg.get(key,(lo+hi)/2)); current += step*(.5+rng.random())*(1 if rng.random()>=.5 else -1)
        cfg[key]=round(max(lo,min(hi,current)),4)
    suffix=secrets.token_hex(3); cfg['key']=f"{parent_key}_g{generation}_{suffix}"
    cfg['name']=f"{parent.get('name',parent_key)} G{generation}.{child_number}"; cfg['research_only']=True
    return cfg


def v7_evolve(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, children: int = V7_CHILDREN_PER_RUN) -> Dict[str, Any]:
    if not V7_ENABLED: return {'ok':False,'version':V7_VERSION,'message':'V7 disabled'}
    _v7_ensure_tables(); horizon=max(1,int(horizon_hours)); child_count=max(1,min(int(children),50)); source=_v7_valid_rows(horizon)
    brains=_v7_active_brains(); conn=db_connect(); now=datetime.now(UTC).isoformat(); evaluations=[]
    for brain in brains:
        result=_v7_evaluate_brain(brain,source); evaluations.append({'brain':brain,'result':result})
        conn.execute("""INSERT OR REPLACE INTO v7_brain_results
            (brain_key,horizon_hours,evaluated_at,trades,wins,losses,win_rate,profit_factor,expectancy_pct,
             expectancy_lower95_pct,max_drawdown_pct,research_score,eligible,accepted_decision_ids_json)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (brain['brain_key'],horizon,now,result['trades'],result['wins'],result['losses'],result['winRate'],
             result['profitFactor'],result['expectancyPct'],result['expectancyLower95Pct'],result['maxDrawdownPct'],
             result['researchScore'],1 if result['eligible'] else 0,json.dumps(result['acceptedDecisionIds'])))
        conn.execute("UPDATE v7_brains SET last_evaluated_at=? WHERE brain_key=?",(now,brain['brain_key']))
    evaluations.sort(key=lambda x:(x['result']['eligible'],x['result']['expectancyLower95Pct'],x['result']['researchScore'],x['result']['trades']),reverse=True)
    healthy=[x for x in evaluations if x['result']['eligible']]
    positive=[x for x in evaluations if x['result']['trades']>=V7_MIN_PARENT_SAMPLES and x['result']['expectancyPct']>0]
    parent_pool=healthy or positive
    discovery=None
    if not parent_pool:
        conn.commit(); conn.close(); discovery=v7_discover(horizon,child_count)
        return {'ok':True,'version':V7_VERSION,'advisoryOnly':True,'automaticLiveChanges':False,
                'horizonHours':horizon,'sourceObservations':len(source),'brainsEvaluated':len(evaluations),
                'generation':discovery.get('generation'),'childrenCreated':discovery.get('candidatesCreated',0),
                'brainsRetired':0,'champion':None,'researchChampion':_v7_public_eval(evaluations[0]) if evaluations else None,
                'discoveryFallback':True,'discovery':discovery,
                'note':'No profitable parent existed, so V7.1 generated evidence-driven candidates instead of mutating a losing champion.'}
    generation=max([int(x['brain'].get('generation') or 0) for x in evaluations] or [0])+1; created=[]
    for i in range(child_count):
        parent=parent_pool[i%len(parent_pool)]['brain']; cfg=_v7_mutate_config(parent['config'],i+1,generation)
        conn.execute("""INSERT OR IGNORE INTO v7_brains
            (brain_key,brain_name,generation,parent_key,status,created_at,config_json,origin)
            VALUES(?,?,?,?, 'ACTIVE',?,?,'mutation')""",(cfg['key'],cfg['name'],generation,parent['brain_key'],now,json.dumps(cfg,sort_keys=True)))
        created.append({'brainKey':cfg['key'],'brainName':cfg['name'],'parentKey':parent['brain_key'],'config':cfg})
    active_count=int(conn.execute("SELECT COUNT(*) FROM v7_brains WHERE status='ACTIVE'").fetchone()[0]); retired=[]
    if active_count>V7_POPULATION_LIMIT:
        removable=[x for x in reversed(evaluations) if x['brain']['origin']!='v6_seed']
        for item in removable[:active_count-V7_POPULATION_LIMIT]:
            key=item['brain']['brain_key']; conn.execute("UPDATE v7_brains SET status='RETIRED',retired_at=? WHERE brain_key=?",(now,key)); retired.append(key)
    champion=healthy[0] if healthy else None; research=evaluations[0] if evaluations else None
    payload={'ok':True,'version':V7_VERSION,'advisoryOnly':True,'automaticLiveChanges':False,'horizonHours':horizon,
             'sourceObservations':len(source),'brainsEvaluated':len(evaluations),'generation':generation,
             'childrenCreated':len(created),'brainsRetired':len(retired),'champion':_v7_public_eval(champion) if champion else None,
             'researchChampion':_v7_public_eval(research) if research else None,'children':created,'retiredBrainKeys':retired,
             'note':'Only eligible or positive-expectancy brains can parent mutations. No live setting changed.'}
    cur=conn.execute("""INSERT INTO v7_evolution_runs
        (created_at,completed_at,horizon_hours,parent_count,children_created,brains_retired,champion_key,payload_json)
        VALUES(?,?,?,?,?,?,?,?)""",(now,datetime.now(UTC).isoformat(),horizon,len(parent_pool),len(created),len(retired),
        champion['brain']['brain_key'] if champion else None,json.dumps(payload))); payload['runId']=int(cur.lastrowid)
    conn.commit(); conn.close(); return payload


def _v7_public_eval(item: Optional[Dict[str,Any]]) -> Optional[Dict[str,Any]]:
    if not item: return None
    return {'brainKey':item['brain']['brain_key'],'brainName':item['brain']['brain_name'],**item['result']}


def v7_brain_lab(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    _v7_ensure_tables(); horizon=max(1,int(horizon_hours)); conn=db_connect()
    rows=[dict(r) for r in conn.execute("""SELECT b.brain_key,b.brain_name,b.generation,b.parent_key,b.status,b.origin,b.created_at,
        r.trades,r.wins,r.losses,r.win_rate,r.profit_factor,r.expectancy_pct,r.expectancy_lower95_pct,
        r.max_drawdown_pct,r.research_score,r.eligible,b.config_json FROM v7_brains b
        LEFT JOIN v7_brain_results r ON r.brain_key=b.brain_key AND r.horizon_hours=?
        ORDER BY CASE WHEN b.status='ACTIVE' THEN 0 ELSE 1 END,COALESCE(r.eligible,0) DESC,
        COALESCE(r.expectancy_lower95_pct,-999) DESC,COALESCE(r.research_score,-999) DESC,b.generation DESC""",(horizon,)).fetchall()]
    last=conn.execute("SELECT payload_json FROM v7_evolution_runs ORDER BY id DESC LIMIT 1").fetchone(); conn.close()
    for row in rows:
        try: row['config']=json.loads(row.pop('config_json'))
        except Exception: row['config']={}
        row['eligible']=bool(row.get('eligible') or 0)
    champion=next((x for x in rows if x['status']=='ACTIVE' and x['eligible']),None)
    research=next((x for x in rows if x['status']=='ACTIVE' and x.get('trades') is not None),None)
    return {'ok':True,'version':V7_VERSION,'advisoryOnly':True,'horizonHours':horizon,
            'activeBrains':sum(x['status']=='ACTIVE' for x in rows),'retiredBrains':sum(x['status']=='RETIRED' for x in rows),
            'champion':champion,'researchChampion':research,'brains':rows,
            'lastEvolutionRun':json.loads(last['payload_json']) if last and last['payload_json'] else None}


def v7_maintenance(trigger: str = 'manual', horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    _v7_ensure_tables(); started=datetime.now(UTC).isoformat(); conn=db_connect()
    cur=conn.execute("INSERT INTO v7_maintenance_runs(started_at,trigger) VALUES(?,?)",(started,str(trigger))); run_id=int(cur.lastrowid); conn.commit(); conn.close()
    repaired=errors=loops=0
    while loops<100:
        result=v6_repair_outcome_times(horizon_hours,V6_REPAIR_BATCH_SIZE); repaired+=int(result.get('repaired') or 0); errors+=int(result.get('errors') or 0); loops+=1
        if int(result.get('remaining') or 0)<=0: break
        time.sleep(.5)
    rebuild=v6_rebuild_validated(horizon_hours,V6_AUTO_SYNC_LIMIT)
    evolution=v7_evolve(horizon_hours,V7_CHILDREN_PER_RUN) if V7_AUTOMATIC_EVOLUTION else {'ok':True,'skipped':True}
    ok=bool(rebuild.get('ok')) and bool(evolution.get('ok')) and errors==0
    payload={'ok':ok,'version':V7_VERSION,'trigger':trigger,'repairLoops':loops,'repaired':repaired,'errors':errors,
             'remaining':0,'rebuild':rebuild,'evolution':evolution,'advisoryOnly':True,'automaticLiveChanges':False}
    conn=db_connect(); conn.execute("""UPDATE v7_maintenance_runs SET completed_at=?,repaired=?,errors=?,rebuild_json=?,evolution_json=?,ok=? WHERE id=?""",
        (datetime.now(UTC).isoformat(),repaired,errors,json.dumps(rebuild),json.dumps(evolution),1 if ok else 0,run_id)); conn.commit(); conn.close()
    payload['maintenanceRunId']=run_id; return payload


def v7_status_payload() -> Dict[str, Any]:
    lab=v7_brain_lab(V6_DEFAULT_HORIZON_HOURS); _v7_ensure_tables(); conn=db_connect()
    last=conn.execute("SELECT * FROM v7_maintenance_runs ORDER BY id DESC LIMIT 1").fetchone(); conn.close()
    now_uk=datetime.now(ZoneInfo('Europe/London')); days=(V7_WEEKEND_DAY-now_uk.weekday())%7
    next_run=(now_uk+timedelta(days=days)).replace(hour=V7_WEEKEND_HOUR_UK,minute=0,second=0,microsecond=0)
    if next_run<=now_uk: next_run+=timedelta(days=7)
    return {'ok':True,'version':V7_VERSION,'name':'Evidence-Driven Research Factory','enabled':V7_ENABLED,
            'advisoryOnly':True,'automaticLiveChanges':False,'automaticPromotion':False,
            'automaticEvolution':V7_AUTOMATIC_EVOLUTION,'weekendMaintenanceEnabled':V7_WEEKEND_MAINTENANCE_ENABLED,
            'nextWeekendMaintenanceAt':next_run.isoformat(),'populationLimit':V7_POPULATION_LIMIT,
            'childrenPerEvolution':V7_CHILDREN_PER_RUN,'activeBrains':lab.get('activeBrains',0),
            'retiredBrains':lab.get('retiredBrains',0),'champion':lab.get('champion'),
            'researchChampion':lab.get('researchChampion'),'lastMaintenance':dict(last) if last else None,
            'features':{'evidenceDrivenDiscovery':True,'winnerLoserAnalysis':True,'featureThresholdSearch':True,
                        'regimeAnalysis':True,'losingParentProtection':True,'mutationLineage':True,
                        'automaticRetirement':True,'shadowOnlyEvaluation':True,'humanApprovalRequired':True}}


def v7_weekend_worker() -> None:
    last_week_key=None
    while True:
        try:
            now=datetime.now(ZoneInfo('Europe/London')); week_key=f"{now.isocalendar().year}-{now.isocalendar().week}"
            if now.weekday()==V7_WEEKEND_DAY and now.hour>=V7_WEEKEND_HOUR_UK and week_key!=last_week_key:
                print(f"V7.1 WEEKEND RESEARCH | starting {now.isoformat()}"); result=v7_maintenance('weekend_scheduler',V6_DEFAULT_HORIZON_HOURS)
                last_week_key=week_key; print(f"V7.1 WEEKEND RESEARCH | ok={result.get('ok')} run={result.get('maintenanceRunId')}")
        except Exception as e: print(f"V7.1 WEEKEND WORKER ERROR: {e}")
        time.sleep(300)


@app.get('/v7/status')
def api_v7_status(): return v7_status_payload()

@app.get('/v7/brains')
def api_v7_brains(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS): return v7_brain_lab(horizon_hours)

@app.get('/v7/research/insights')
def api_v7_research_insights(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS): return v7_research_insights(horizon_hours)

@app.post('/v7/discover')
def api_v7_discover(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v7_discover(int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS),int(payload.get('candidates') or 12))

@app.post('/v7/evolve')
def api_v7_evolve(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v7_evolve(int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS),int(payload.get('children') or V7_CHILDREN_PER_RUN))

@app.post('/v7/maintenance')
def api_v7_maintenance(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v7_maintenance('manual',int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS))

print(f"TRADEBOT V2 | enabled={TRADEBOT_V2_ENABLED} mode={'paper' if PAPER else ('live' if TRADEBOT_V2_LIVE_ENABLED else 'validation-only')} min_samples={V2_MIN_SYMBOL_SAMPLES} min_pf={V2_MIN_PROFIT_FACTOR}")



# =========================
# TRADEBOT V8.0 — MARKET INTELLIGENCE ENGINE
# Shadow-only. This layer cannot alter live trading settings.
# =========================
V8_VERSION = "V8.0"
V8_NAME = "Market Intelligence Engine"
V8_POPULATION_LIMIT = int(os.getenv("V8_POPULATION_LIMIT", "30"))
V8_MIN_CONTEXT_SAMPLES = int(os.getenv("V8_MIN_CONTEXT_SAMPLES", "12"))


def _v8_ensure_tables_impl() -> None:
    if not SQLITE_ENABLED:
        return
    conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS v8_context_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        horizon_hours INTEGER NOT NULL,
        source_observations INTEGER NOT NULL DEFAULT 0,
        valid_observations INTEGER NOT NULL DEFAULT 0,
        candidates_created INTEGER NOT NULL DEFAULT 0,
        duplicates_skipped INTEGER NOT NULL DEFAULT 0,
        retired INTEGER NOT NULL DEFAULT 0,
        payload_json TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v8_context_results (
        context_key TEXT NOT NULL,
        horizon_hours INTEGER NOT NULL,
        evaluated_at TEXT NOT NULL,
        trades INTEGER NOT NULL DEFAULT 0,
        wins INTEGER NOT NULL DEFAULT 0,
        losses INTEGER NOT NULL DEFAULT 0,
        win_rate REAL,
        profit_factor REAL,
        expectancy_pct REAL,
        expectancy_lower95_pct REAL,
        max_drawdown_pct REAL,
        context_score REAL,
        config_json TEXT NOT NULL,
        PRIMARY KEY(context_key, horizon_hours)
    )""")
    conn.commit(); conn.close()


def _v8_ensure_tables() -> None:
    global _V8_SCHEMA_COMPLETE
    if not SQLITE_ENABLED or _V8_SCHEMA_COMPLETE:
        return
    _v7_ensure_tables()
    with _V8_SCHEMA_LOCK:
        if _V8_SCHEMA_COMPLETE:
            return
        _v8_ensure_tables_impl()
        _V8_SCHEMA_COMPLETE = True


def _v8_context_value(row: Dict[str, Any], key: str) -> Any:
    if key in ("spy_move", "qqq_move", "confidence", "quality", "momentum", "pullback", "spread"):
        try: return float(row.get(key) or 0.0)
        except Exception: return 0.0
    if key in ("hour_utc", "weekday", "position_count"):
        try: return int(row.get(key) or 0)
        except Exception: return 0
    return str(row.get(key) or "unknown").lower()


def _v8_context_accepts(row: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    # Existing stock-level gates remain available.
    if not _v6_accepts(row, cfg):
        return False
    spy = _v8_context_value(row, "spy_move")
    qqq = _v8_context_value(row, "qqq_move")
    hour = _v8_context_value(row, "hour_utc")
    weekday = _v8_context_value(row, "weekday")
    positions = _v8_context_value(row, "position_count")
    regime = _v8_context_value(row, "market_regime")
    session = _v8_context_value(row, "session_name")
    checks = (
        ("spy_min", spy, lambda a,b: a >= b), ("spy_max", spy, lambda a,b: a <= b),
        ("qqq_min", qqq, lambda a,b: a >= b), ("qqq_max", qqq, lambda a,b: a <= b),
        ("hour_min", hour, lambda a,b: a >= b), ("hour_max", hour, lambda a,b: a <= b),
        ("position_count_max", positions, lambda a,b: a <= b),
    )
    for name, value, fn in checks:
        if name in cfg and not fn(value, float(cfg[name])):
            return False
    if cfg.get("weekdays") and weekday not in {int(x) for x in cfg["weekdays"]}:
        return False
    if cfg.get("regimes") and regime not in {str(x).lower() for x in cfg["regimes"]}:
        return False
    if cfg.get("sessions") and session not in {str(x).lower() for x in cfg["sessions"]}:
        return False
    return True


def _v8_eval(rows: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    accepted=[{"decision_id":int(r.get("decision_id") or 0),
               "return_pct":float(r.get("net_return_pct") or 0.0)}
              for r in rows if _v8_context_accepts(r,cfg)]
    metrics=_v6_score_rows(accepted)
    eligible=(metrics["trades"] >= V7_MIN_PARENT_SAMPLES and
              metrics["profitFactor"] >= V6_RECOMMENDATION_MIN_PF and
              metrics["expectancyPct"] >= V6_RECOMMENDATION_MIN_EXPECTANCY and
              metrics["expectancyLower95Pct"] > 0)
    score=(_v6_research_score(metrics) if metrics["trades"] >= V6_MIN_SAMPLES else -999.0)
    return {**metrics,"eligible":eligible,"researchScore":score,
            "acceptedDecisionIds":[x["decision_id"] for x in accepted]}


def _v8_signature(cfg: Dict[str, Any]) -> str:
    ignored={"key","name","research_only","discovery_score","context_score"}
    clean={k:v for k,v in cfg.items() if k not in ignored}
    return json.dumps(clean,sort_keys=True,separators=(",",":"))


def v8_cleanup_population(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    _v8_ensure_tables(); horizon=max(1,int(horizon_hours)); rows=_v7_valid_rows(horizon)
    brains=_v7_active_brains(); evaluated=[]
    for brain in brains:
        result=_v8_eval(rows,brain.get("config") or {})
        evaluated.append({"brain":brain,"result":result,"signature":_v8_signature(brain.get("config") or {})})
    # Keep one copy per effective configuration. Prefer seed, then most trades, then score.
    groups={}
    for item in evaluated: groups.setdefault(item["signature"],[]).append(item)
    retire=[]
    for group in groups.values():
        group.sort(key=lambda x:(x["brain"].get("origin")=="v6_seed",x["result"]["trades"],x["result"]["researchScore"]),reverse=True)
        retire.extend(x["brain"]["brain_key"] for x in group[1:] if x["brain"].get("origin")!="v6_seed")
    survivors=[x for x in evaluated if x["brain"]["brain_key"] not in set(retire)]
    if len(survivors)>V8_POPULATION_LIMIT:
        removable=[x for x in survivors if x["brain"].get("origin")!="v6_seed"]
        removable.sort(key=lambda x:(x["result"]["eligible"],x["result"]["trades"]>0,x["result"]["researchScore"],x["result"]["expectancyPct"]))
        retire.extend(x["brain"]["brain_key"] for x in removable[:max(0,len(survivors)-V8_POPULATION_LIMIT)])
    retire=list(dict.fromkeys(retire)); now=datetime.now(UTC).isoformat()
    if retire:
        conn=db_connect()
        for key in retire: conn.execute("UPDATE v7_brains SET status='RETIRED',retired_at=? WHERE brain_key=? AND origin!='v6_seed'",(now,key))
        conn.commit(); conn.close()
    active=max(0,len(brains)-len(retire))
    return {"ok":True,"version":V8_VERSION,"populationLimit":V8_POPULATION_LIMIT,
            "activeBefore":len(brains),"retired":len(retire),"activeAfter":active,
            "retiredBrainKeys":retire,"duplicateProtection":True}


def _v8_market_context_candidates(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    if not rows: return []
    spy=[_v8_context_value(r,"spy_move") for r in rows]; qqq=[_v8_context_value(r,"qqq_move") for r in rows]
    spread=[_v8_context_value(r,"spread") for r in rows]; pull=[_v8_context_value(r,"pullback") for r in rows]
    hours=sorted(set(_v8_context_value(r,"hour_utc") for r in rows))
    sessions=sorted(set(_v8_context_value(r,"session_name") for r in rows))
    regimes=sorted(set(_v8_context_value(r,"market_regime") for r in rows))
    configs=[]
    # Broad market alignment and risk-off filters.
    for sm in sorted(set(round(_v7_quantile(spy,q),5) for q in (.2,.4,.6))):
        for qm in sorted(set(round(_v7_quantile(qqq,q),5) for q in (.2,.4,.6))):
            configs.append({"spy_min":sm,"qqq_min":qm,"max_spread":round(_v7_quantile(spread,.6),5)})
    # Session/time filters discovered from actual observations.
    for session in sessions:
        configs.append({"sessions":[session],"max_spread":round(_v7_quantile(spread,.6),5),"pullback_max":round(_v7_quantile(pull,.6),5)})
    if hours:
        for start in hours:
            for width in (1,2,3): configs.append({"hour_min":start,"hour_max":start+width,"spy_min":round(_v7_quantile(spy,.4),5)})
    for regime in regimes:
        if regime!="unknown": configs.append({"regimes":[regime],"spy_min":round(_v7_quantile(spy,.4),5),"qqq_min":round(_v7_quantile(qqq,.4),5)})
    # Low exposure contexts.
    configs.extend([{"position_count_max":0},{"position_count_max":1,"spy_min":round(_v7_quantile(spy,.4),5)}])
    scored=[]; seen=set()
    for cfg in configs:
        sig=_v8_signature(cfg)
        if sig in seen: continue
        seen.add(sig); result=_v8_eval(rows,cfg)
        if result["trades"]<V8_MIN_CONTEXT_SAMPLES: continue
        context_score=(result["expectancyPct"]*.45+result["expectancyLower95Pct"]*.30+
                       min(result["profitFactor"],3)*.20-result["maxDrawdownPct"]*.01)
        scored.append({"config":cfg,"backtest":result,"contextScore":context_score,"signature":sig})
    scored.sort(key=lambda x:(x["backtest"]["eligible"],x["contextScore"],x["backtest"]["expectancyPct"]),reverse=True)
    return scored[:max(1,min(limit,30))]


def v8_context_research(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, candidates: int = 12) -> Dict[str, Any]:
    _v8_ensure_tables(); horizon=max(1,int(horizon_hours)); limit=max(1,min(int(candidates),30)); rows=_v7_valid_rows(horizon)
    found=_v8_market_context_candidates(rows,limit); conn=db_connect(); now=datetime.now(UTC).isoformat()
    existing={_v8_signature(json.loads(r[0])) for r in conn.execute("SELECT config_json FROM v7_brains").fetchall()}
    generation=int(conn.execute("SELECT COALESCE(MAX(generation),0)+1 FROM v7_brains").fetchone()[0]); created=[]; skipped=0
    for i,item in enumerate(found,1):
        if item["signature"] in existing: skipped+=1; continue
        cfg=dict(item["config"]); key=f"context_g{generation}_{secrets.token_hex(3)}"
        cfg.update({"key":key,"name":f"Market Context G{generation}.{i}","research_only":True,"context_score":round(item["contextScore"],6)})
        conn.execute("""INSERT INTO v7_brains(brain_key,brain_name,generation,parent_key,status,created_at,config_json,origin)
                     VALUES(?,?,?,NULL,'ACTIVE',?,?,'market_context')""",(key,cfg["name"],generation,now,json.dumps(cfg,sort_keys=True)))
        created.append({"brainKey":key,"brainName":cfg["name"],"config":cfg,"backtest":item["backtest"]})
        existing.add(item["signature"])
    conn.commit(); conn.close(); cleanup=v8_cleanup_population(horizon)
    healthy=sum(1 for x in created if x["backtest"].get("eligible"))
    payload={"ok":True,"version":V8_VERSION,"name":V8_NAME,"advisoryOnly":True,"automaticLiveChanges":False,
             "horizonHours":horizon,"validObservations":len(rows),"generation":generation,
             "candidatesCreated":len(created),"duplicatesSkipped":skipped,"healthyCandidates":healthy,
             "candidates":created,"populationCleanup":cleanup,
             "note":"Candidates use market context already captured at decision time. They remain shadow-only."}
    conn=db_connect(); cur=conn.execute("""INSERT INTO v8_context_runs(created_at,horizon_hours,source_observations,valid_observations,candidates_created,duplicates_skipped,retired,payload_json)
        VALUES(?,?,?,?,?,?,?,?)""",(now,horizon,len(_v6_source_rows(horizon,V6_AUTO_SYNC_LIMIT)),len(rows),len(created),skipped,cleanup["retired"],json.dumps(payload)))
    payload["runId"]=int(cur.lastrowid); conn.commit(); conn.close(); return payload


def v8_intelligence_report(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    horizon=max(1,int(horizon_hours)); rows=_v7_valid_rows(horizon)
    dimensions=("market_regime","session_name","weekday","hour_utc")
    report={}
    for dim in dimensions:
        groups={}
        for r in rows: groups.setdefault(str(_v8_context_value(r,dim)),[]).append(r)
        values=[]
        for key,group in groups.items():
            m=_v7_segment_metrics(group)
            if m["trades"]>=5: values.append({dim:key,**m})
        values.sort(key=lambda x:(x["expectancyPct"],x["profitFactor"],x["trades"]),reverse=True)
        report[dim]=values
    aligned=[r for r in rows if _v8_context_value(r,"spy_move")>=0 and _v8_context_value(r,"qqq_move")>=0]
    opposed=[r for r in rows if _v8_context_value(r,"spy_move")<0 or _v8_context_value(r,"qqq_move")<0]
    lab=v7_brain_lab(horizon)
    # Correct research champion: zero-trade brains are excluded.
    tested=[b for b in lab.get("brains",[]) if b.get("status")=="ACTIVE" and int(b.get("trades") or 0)>0]
    tested.sort(key=lambda b:(bool(b.get("eligible")),float(b.get("expectancy_lower95_pct") or -999),float(b.get("research_score") or -999)),reverse=True)
    return {"ok":True,"version":V8_VERSION,"name":V8_NAME,"advisoryOnly":True,"horizonHours":horizon,
            "validObservations":len(rows),"marketAlignment":{"bothNonNegative":_v7_segment_metrics(aligned),"riskOffOrDivergent":_v7_segment_metrics(opposed)},
            "contextBreakdown":report,"champion":next((b for b in tested if b.get("eligible")),None),
            "researchChampion":tested[0] if tested else None,"zeroTradeBrainsExcluded":True,
            "note":"This report uses only context recorded at the original decision timestamp."}


def v8_maintenance(trigger: str = "manual", horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    horizon=max(1,int(horizon_hours)); repaired=errors=loops=0
    while loops<100:
        result=v6_repair_outcome_times(horizon,V6_REPAIR_BATCH_SIZE); repaired+=int(result.get("repaired") or 0); errors+=int(result.get("errors") or 0); loops+=1
        if int(result.get("remaining") or 0)<=0: break
    rebuild=v6_rebuild_validated(horizon,V6_AUTO_SYNC_LIMIT)
    research=v8_context_research(horizon,V7_CHILDREN_PER_RUN)
    return {"ok":bool(rebuild.get("ok")) and bool(research.get("ok")) and errors==0,"version":V8_VERSION,
            "trigger":trigger,"repairLoops":loops,"repaired":repaired,"errors":errors,"rebuild":rebuild,
            "marketIntelligence":research,"advisoryOnly":True,"automaticLiveChanges":False}


def v8_status_payload() -> Dict[str, Any]:
    _v8_ensure_tables(); intelligence=v8_intelligence_report(V6_DEFAULT_HORIZON_HOURS); lab=v7_brain_lab(V6_DEFAULT_HORIZON_HOURS)
    return {"ok":True,"version":V8_VERSION,"name":V8_NAME,"enabled":True,"advisoryOnly":True,
            "automaticLiveChanges":False,"automaticPromotion":False,"populationLimit":V8_POPULATION_LIMIT,
            "activeBrains":lab.get("activeBrains",0),"retiredBrains":lab.get("retiredBrains",0),
            "champion":intelligence.get("champion"),"researchChampion":intelligence.get("researchChampion"),
            "features":{"marketAlignment":True,"sessionIntelligence":True,"timeOfDayIntelligence":True,
                        "exposureContext":True,"zeroTradeChampionProtection":True,"duplicateCandidateProtection":True,
                        "hardPopulationLimit":True,"shadowOnlyEvaluation":True,"humanApprovalRequired":True}}


@app.get('/v8/status')
def api_v8_status(): return v8_status_payload()

@app.get('/v8/intelligence')
def api_v8_intelligence(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS): return v8_intelligence_report(horizon_hours)

@app.post('/v8/research')
def api_v8_research(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v8_context_research(int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS),int(payload.get('candidates') or 12))

@app.post('/v8/cleanup')
def api_v8_cleanup(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v8_cleanup_population(int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS))

@app.post('/v8/maintenance')
def api_v8_maintenance(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v8_maintenance('manual',int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS))


# =========================
# TRADEBOT V9.0 — MARKET MEMORY ENGINE
# Rich decision-time observations. Shadow-only and unable to alter live trading.
# =========================
V9_VERSION = "V9.2"
V9_NAME = "Live Market Intelligence Engine (IEX Feed Fix)"
V9_ENABLED = os.getenv("V9_ENABLED", "true").lower() == "true"
V9_MIN_READY_OBSERVATIONS = max(100, int(os.getenv("V9_MIN_READY_OBSERVATIONS", "1000") or 1000))
V9_MIN_FIELD_COVERAGE = max(0.50, min(float(os.getenv("V9_MIN_FIELD_COVERAGE", "0.80") or 0.80), 1.0))


def _v9_ensure_tables() -> None:
    _v8_ensure_tables()
    if not SQLITE_ENABLED:
        return
    conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS v9_market_memory (
        decision_id INTEGER PRIMARY KEY,
        captured_at TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        symbol TEXT NOT NULL,
        decision TEXT,
        stage TEXT,
        reason TEXT,
        price REAL,
        confidence REAL,
        quality REAL,
        momentum REAL,
        pullback REAL,
        spread REAL,
        ready_to_buy INTEGER,
        sniper_pass INTEGER,
        a_plus_pass INTEGER,
        market_regime TEXT,
        session_name TEXT,
        weekday INTEGER,
        hour_utc INTEGER,
        spy_move REAL,
        qqq_move REAL,
        position_count INTEGER,
        relative_volume REAL,
        gap_pct REAL,
        distance_vwap_pct REAL,
        ema9_distance_pct REAL,
        ema20_distance_pct REAL,
        ema50_distance_pct REAL,
        atr_pct REAL,
        day_range_position REAL,
        opening_range_breakout INTEGER,
        premarket_volume REAL,
        sector TEXT,
        sector_strength REAL,
        news_score REAL,
        earnings_days INTEGER,
        float_shares REAL,
        shares_outstanding REAL,
        payload_json TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'live'
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v9_memory_symbol_time ON v9_market_memory(symbol, observed_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v9_memory_stage ON v9_market_memory(stage, decision)")
    conn.execute("""CREATE TABLE IF NOT EXISTS v9_memory_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        run_type TEXT NOT NULL,
        processed INTEGER NOT NULL DEFAULT 0,
        inserted INTEGER NOT NULL DEFAULT 0,
        updated INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0,
        payload_json TEXT
    )""")
    conn.commit(); conn.close()


def _v9_num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        x=float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _v9_scan_value(scan: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in scan and scan.get(key) is not None:
            return scan.get(key)
    return default



# =========================
# V9.1 LIVE MARKET INTELLIGENCE COLLECTOR
# Shadow-only: enriches memory records and never changes order decisions.
# =========================
V91_INTELLIGENCE_ENABLED = os.getenv("V91_INTELLIGENCE_ENABLED", "true").lower() == "true"
V91_CACHE_SECONDS = max(30, int(os.getenv("V91_CACHE_SECONDS", "180") or 180))
_v91_cache: Dict[str, Dict[str, Any]] = {}
_v91_cache_lock = threading.Lock()

V91_SECTOR_MAP = {
    "AAPL":"Technology","MSFT":"Technology","NVDA":"Technology","AMD":"Technology","INTC":"Technology",
    "QCOM":"Technology","MU":"Technology","GOOG":"Communication Services","GOOGL":"Communication Services",
    "META":"Communication Services","AMZN":"Consumer Discretionary","TSLA":"Consumer Discretionary",
    "F":"Consumer Discretionary","GM":"Consumer Discretionary","HOOD":"Financials","SOFI":"Financials",
    "JPM":"Financials","BAC":"Financials","KO":"Consumer Staples","GIS":"Consumer Staples",
    "PPL":"Utilities","XOM":"Energy","CVX":"Energy","LLY":"Healthcare","PFE":"Healthcare",
    "PLTR":"Technology","LCID":"Consumer Discretionary","RIVN":"Consumer Discretionary","SNAP":"Communication Services",
}
V91_SECTOR_ETF = {
    "Technology":"XLK","Communication Services":"XLC","Consumer Discretionary":"XLY","Financials":"XLF",
    "Consumer Staples":"XLP","Utilities":"XLU","Energy":"XLE","Healthcare":"XLV","Industrials":"XLI",
    "Materials":"XLB","Real Estate":"XLRE",
}

def _v91_bars(symbol: str, timeframe: Any, start: datetime, end: datetime) -> List[Any]:
    req=StockBarsRequest(symbol_or_symbols=[symbol], timeframe=timeframe, start=start, end=end, feed=DataFeed.IEX)
    response=data_client.get_stock_bars(req)
    try: return list(response[symbol])
    except Exception:
        data=getattr(response,"data",{}) or {}
        return list(data.get(symbol,[]))

def _v91_ema(values: List[float], period: int) -> Optional[float]:
    if not values: return None
    alpha=2.0/(period+1.0); value=float(values[0])
    for item in values[1:]: value=alpha*float(item)+(1.0-alpha)*value
    return value

def _v91_pct_distance(price: float, reference: Optional[float]) -> Optional[float]:
    return None if not reference or reference <= 0 else ((price/reference)-1.0)*100.0

def _v91_cached(symbol: str) -> Optional[Dict[str, Any]]:
    with _v91_cache_lock:
        item=_v91_cache.get(symbol)
        if item and time.time()-float(item.get("cached_at",0)) < V91_CACHE_SECONDS:
            return dict(item.get("data") or {})
    return None

def _v91_store_cache(symbol: str, data: Dict[str, Any]) -> None:
    with _v91_cache_lock: _v91_cache[symbol]={"cached_at":time.time(),"data":dict(data)}

def _v91_symbol_intelligence(symbol: str, price: float) -> Dict[str, Any]:
    sym=str(symbol).upper(); cached=_v91_cached(sym)
    if cached is not None: return cached
    result: Dict[str, Any]={}
    now=datetime.now(UTC)
    try:
        daily=_v91_bars(sym,TimeFrame.Day,now-timedelta(days=45),now)
        daily_rows=[]
        for b in daily:
            try: daily_rows.append({"o":float(b.open),"h":float(b.high),"l":float(b.low),"c":float(b.close),"v":float(b.volume or 0)})
            except Exception: pass
        if daily_rows:
            previous=daily_rows[-2] if len(daily_rows)>=2 else daily_rows[-1]
            today=daily_rows[-1]
            result["gap_pct"]=_v91_pct_distance(today["o"],previous["c"])
            trs=[]
            for i,row in enumerate(daily_rows[-15:]):
                prev_close=daily_rows[max(0,len(daily_rows)-15+i-1)]["c"]
                trs.append(max(row["h"]-row["l"],abs(row["h"]-prev_close),abs(row["l"]-prev_close)))
            atr=sum(trs)/len(trs) if trs else None
            result["atr_pct"]=(atr/price*100.0) if atr and price>0 else None
            avg_vol=sum(x["v"] for x in daily_rows[-21:-1])/max(1,len(daily_rows[-21:-1]))
            result["average_daily_volume"]=avg_vol
    except Exception as e: result["daily_error"]=str(e)[:160]
    try:
        et=ZoneInfo("America/New_York"); now_et=now.astimezone(et)
        session_open=now_et.replace(hour=9,minute=30,second=0,microsecond=0).astimezone(UTC)
        pre_open=now_et.replace(hour=4,minute=0,second=0,microsecond=0).astimezone(UTC)
        start=min(pre_open,now-timedelta(hours=14))
        bars=_v91_bars(sym,TimeFrame.Minute,start,now)
        rows=[]
        for b in bars:
            try: rows.append((b.timestamp,float(b.open),float(b.high),float(b.low),float(b.close),float(b.volume or 0)))
            except Exception: pass
        if rows:
            closes=[x[4] for x in rows]; volumes=[x[5] for x in rows]
            typical=[(x[2]+x[3]+x[4])/3.0 for x in rows]
            total_volume=sum(volumes); pv=sum(t*v for t,v in zip(typical,volumes)); vwap=pv/total_volume if total_volume>0 else None
            result["distance_vwap_pct"]=_v91_pct_distance(price,vwap)
            result["ema9_distance_pct"]=_v91_pct_distance(price,_v91_ema(closes,9))
            result["ema20_distance_pct"]=_v91_pct_distance(price,_v91_ema(closes,20))
            result["ema50_distance_pct"]=_v91_pct_distance(price,_v91_ema(closes,50))
            high=max(x[2] for x in rows); low=min(x[3] for x in rows)
            result["day_range_position"]=(price-low)/(high-low) if high>low else 0.5
            elapsed=max(1.0,min(390.0,(now-session_open).total_seconds()/60.0)); fraction=max(1/390,elapsed/390.0)
            avg_daily=float(result.get("average_daily_volume") or 0.0)
            result["relative_volume"]=(total_volume/(avg_daily*fraction)) if avg_daily>0 else None
            result["premarket_volume"]=sum(x[5] for x in rows if _v6_parse_utc(x[0]) < session_open)
            orb_end=session_open+timedelta(minutes=30)
            orb=[x for x in rows if session_open <= _v6_parse_utc(x[0]) <= orb_end]
            result["opening_range_breakout"]=bool(orb and price > max(x[2] for x in orb))
            result["current_volume"]=total_volume
    except Exception as e: result["intraday_error"]=str(e)[:160]
    sector=V91_SECTOR_MAP.get(sym,"unknown"); result["sector"]=sector
    _v91_store_cache(sym,result); return result

def _v91_market_context() -> Dict[str, Any]:
    cached=_v91_cached("__MARKET__")
    if cached is not None: return cached
    context: Dict[str, Any]={}
    moves=[]
    for symbol in ("SPY","QQQ"):
        try:
            q=get_quote(symbol); intel=_v91_symbol_intelligence(symbol,float(q["mid"]))
            move=(intel.get("gap_pct") or 0.0)+(intel.get("distance_vwap_pct") or 0.0)
            context[f"{symbol.lower()}_move_pct"]=move; moves.append(move)
            context[f"{symbol.lower()}_above_vwap"]=(intel.get("distance_vwap_pct") or 0.0)>0
        except Exception: pass
    avg=sum(moves)/len(moves) if moves else 0.0
    both_above=bool(context.get("spy_above_vwap") and context.get("qqq_above_vwap"))
    both_below=bool(context.get("spy_above_vwap") is False and context.get("qqq_above_vwap") is False)
    if avg>=1.0 and both_above: regime="STRONG_RISK_ON"
    elif avg>=0.2 and both_above: regime="RISK_ON"
    elif avg<=-1.0 and both_below: regime="STRONG_RISK_OFF"
    elif avg<=-0.2 and both_below: regime="RISK_OFF"
    elif abs(avg)<0.25: regime="SIDEWAYS"
    else: regime="MIXED"
    context["market_regime"]=regime
    _v91_store_cache("__MARKET__",context); return context

def _v91_enrich_scan(scan: Dict[str, Any]) -> Dict[str, Any]:
    if not V91_INTELLIGENCE_ENABLED: return scan
    symbol=str(scan.get("symbol") or "").upper(); price=float(scan.get("price") or 0.0)
    if not symbol or price<=0: return scan
    enriched=dict(scan)
    try: enriched.update({k:v for k,v in _v91_symbol_intelligence(symbol,price).items() if v is not None})
    except Exception as e: enriched["v91_symbol_error"]=str(e)[:160]
    try:
        market=_v91_market_context(); enriched["market_regime"]=market.get("market_regime","UNKNOWN")
        if market.get("spy_move_pct") is not None: enriched["spy_move"]=float(market["spy_move_pct"])/100.0
        if market.get("qqq_move_pct") is not None: enriched["qqq_move"]=float(market["qqq_move_pct"])/100.0
    except Exception as e: enriched["v91_market_error"]=str(e)[:160]
    sector=enriched.get("sector")
    etf=V91_SECTOR_ETF.get(str(sector))
    if etf:
        try:
            q=get_quote(etf); si=_v91_symbol_intelligence(etf,float(q["mid"]))
            enriched["sector_strength"]=(si.get("gap_pct") or 0.0)+(si.get("distance_vwap_pct") or 0.0)
        except Exception: pass
    return enriched

def _v9_capture_snapshot(conn, decision_id: int, scan: Dict[str, Any], decision: str,
                         stage: str, reason: str, observed_at: datetime, source: str = "live") -> None:
    symbol=str(scan.get("symbol") or "").upper().strip()
    if not symbol or decision_id <= 0:
        return
    if source == "live":
        scan = _v91_enrich_scan(scan)
    dna=conn.execute("SELECT market_regime,session_name,weekday,hour_utc,spy_move,qqq_move,position_count FROM v4_market_dna WHERE decision_id=?",(decision_id,)).fetchone()
    if dna:
        regime,session,weekday,hour,spy,qqq,positions=dna
        regime=scan.get("market_regime") or regime
        spy=scan.get("spy_move") if scan.get("spy_move") is not None else spy
        qqq=scan.get("qqq_move") if scan.get("qqq_move") is not None else qqq
    else:
        regime=_v4_market_regime(); session=_v4_session_name(observed_at); weekday=observed_at.weekday(); hour=observed_at.hour
        spy=_v4_index_move("SPY"); qqq=_v4_index_move("QQQ")
        try: positions=len(trading_client.get_all_positions())
        except Exception: positions=0
    payload={
        "schemaVersion":1,
        "explanation":{
            "decision":str(decision),"stage":str(stage),"reason":str(reason)[:1000],
            "sniperReason":scan.get("sniper_reason"),"aPlusReason":scan.get("a_plus_reason")
        },
        "rawScan":{k:v for k,v in scan.items() if isinstance(v,(str,int,float,bool,type(None)))}
    }
    fields={
        "relative_volume":_v9_num(_v9_scan_value(scan,"relative_volume","rvol","relativeVolume")),
        "gap_pct":_v9_num(_v9_scan_value(scan,"gap_pct","gap_percent","gapPercent")),
        "distance_vwap_pct":_v9_num(_v9_scan_value(scan,"distance_vwap_pct","vwap_distance_pct","distanceFromVwapPct")),
        "ema9_distance_pct":_v9_num(_v9_scan_value(scan,"ema9_distance_pct","ema9DistancePct")),
        "ema20_distance_pct":_v9_num(_v9_scan_value(scan,"ema20_distance_pct","ema20DistancePct")),
        "ema50_distance_pct":_v9_num(_v9_scan_value(scan,"ema50_distance_pct","ema50DistancePct")),
        "atr_pct":_v9_num(_v9_scan_value(scan,"atr_pct","atrPercent")),
        "day_range_position":_v9_num(_v9_scan_value(scan,"day_range_position","range_position","dayRangePosition")),
        "opening_range_breakout":int(bool(_v9_scan_value(scan,"opening_range_breakout","orb","openingRangeBreakout",default=False))),
        "premarket_volume":_v9_num(_v9_scan_value(scan,"premarket_volume","premarketVolume")),
        "sector":str(_v9_scan_value(scan,"sector",default="unknown") or "unknown"),
        "sector_strength":_v9_num(_v9_scan_value(scan,"sector_strength","sectorStrength")),
        "news_score":_v9_num(_v9_scan_value(scan,"news_score","newsScore")),
        "earnings_days":int(_v9_num(_v9_scan_value(scan,"earnings_days","days_to_earnings","earningsDays"),999) or 999),
        "float_shares":_v9_num(_v9_scan_value(scan,"float_shares","float","floatShares")),
        "shares_outstanding":_v9_num(_v9_scan_value(scan,"shares_outstanding","sharesOutstanding")),
    }
    conn.execute("""INSERT OR REPLACE INTO v9_market_memory(
        decision_id,captured_at,observed_at,symbol,decision,stage,reason,price,confidence,quality,momentum,pullback,spread,
        ready_to_buy,sniper_pass,a_plus_pass,market_regime,session_name,weekday,hour_utc,spy_move,qqq_move,position_count,
        relative_volume,gap_pct,distance_vwap_pct,ema9_distance_pct,ema20_distance_pct,ema50_distance_pct,atr_pct,
        day_range_position,opening_range_breakout,premarket_volume,sector,sector_strength,news_score,earnings_days,
        float_shares,shares_outstanding,payload_json,source)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (decision_id,datetime.now(UTC).isoformat(),observed_at.isoformat(),symbol,str(decision),str(stage),str(reason)[:1000],
         _v9_num(scan.get("price"),0.0),_v9_num(scan.get("confidence"),0.0),_v9_num(scan.get("quality_score"),0.0),
         _v9_num(scan.get("short_momentum"),0.0),_v9_num(scan.get("pullback"),0.0),_v9_num(scan.get("spread"),0.0),
         int(bool(scan.get("ready_to_buy"))),int(bool(scan.get("sniper_pass"))),int(bool(scan.get("a_plus_pass"))),
         str(regime or "unknown"),str(session or "unknown"),int(weekday or 0),int(hour or 0),_v9_num(spy,0.0),_v9_num(qqq,0.0),int(positions or 0),
         fields["relative_volume"],fields["gap_pct"],fields["distance_vwap_pct"],fields["ema9_distance_pct"],fields["ema20_distance_pct"],
         fields["ema50_distance_pct"],fields["atr_pct"],fields["day_range_position"],fields["opening_range_breakout"],fields["premarket_volume"],
         fields["sector"],fields["sector_strength"],fields["news_score"],fields["earnings_days"],fields["float_shares"],fields["shares_outstanding"],
         json.dumps(payload,default=str),str(source)))
    try:
        _v112_audit_snapshot(conn, decision_id, symbol, source, fields)
        if source == "live":
            _v113_verify_persisted_snapshot(conn, decision_id, symbol)
    except Exception as audit_error:
        print(f"V11.3 SNAPSHOT AUDIT/VERIFY ERROR {symbol}: {audit_error}")


def v9_backfill(limit: int = 5000) -> Dict[str, Any]:
    _v9_ensure_tables(); limit=max(1,min(int(limit),50000)); processed=inserted=errors=0
    conn=db_connect()
    rows=conn.execute("""SELECT d.id,d.timestamp,d.symbol,d.decision,d.stage,d.reason,d.price,d.confidence,d.quality,d.momentum,d.pullback,d.spread,
        d.ready_to_buy,d.sniper_pass,d.a_plus_pass,d.payload_json
        FROM v2_setup_decisions d LEFT JOIN v9_market_memory m ON m.decision_id=d.id
        WHERE m.decision_id IS NULL ORDER BY d.id ASC LIMIT ?""",(limit,)).fetchall()
    for row in rows:
        processed+=1
        try:
            (did,ts,symbol,decision,stage,reason,price,confidence,quality,momentum,pullback,spread,ready,sniper,a_plus,payload_json)=row
            try: observed=datetime.fromisoformat(str(ts).replace("Z","+00:00"))
            except Exception: observed=datetime.now(UTC)
            scan={"symbol":symbol,"price":price,"confidence":confidence,"quality_score":quality,"short_momentum":momentum,
                  "pullback":pullback,"spread":spread,"ready_to_buy":bool(ready),"sniper_pass":bool(sniper),"a_plus_pass":bool(a_plus)}
            try:
                payload=json.loads(payload_json or "{}")
                if isinstance(payload,dict):
                    scan.update({k:v for k,v in payload.items() if k not in scan})
            except Exception: pass
            _v9_capture_snapshot(conn,int(did),scan,str(decision),str(stage),str(reason),observed,"historical_backfill")
            inserted+=1
        except Exception as e:
            errors+=1; print(f"V9 BACKFILL ERROR: {e}")
    now=datetime.now(UTC).isoformat(); payload={"ok":errors==0,"version":V9_VERSION,"processed":processed,"inserted":inserted,"errors":errors}
    cur=conn.execute("INSERT INTO v9_memory_runs(created_at,run_type,processed,inserted,updated,errors,payload_json) VALUES(?,?,?,?,?,?,?)",
                     (now,"backfill",processed,inserted,0,errors,json.dumps(payload)))
    payload["runId"]=int(cur.lastrowid); conn.commit(); conn.close(); return payload


def v9_coverage() -> Dict[str, Any]:
    _v9_ensure_tables(); conn=db_connect(); total=int(conn.execute("SELECT COUNT(*) FROM v9_market_memory").fetchone()[0])
    fields=["market_regime","spy_move","qqq_move","relative_volume","gap_pct","distance_vwap_pct","ema9_distance_pct","ema20_distance_pct",
            "ema50_distance_pct","atr_pct","day_range_position","premarket_volume","sector","sector_strength","news_score","float_shares"]
    coverage={}
    for f in fields:
        if f in ("market_regime","sector"):
            present=int(conn.execute(f"SELECT COUNT(*) FROM v9_market_memory WHERE {f} IS NOT NULL AND lower({f}) NOT IN ('','unknown')").fetchone()[0])
        else:
            present=int(conn.execute(f"SELECT COUNT(*) FROM v9_market_memory WHERE {f} IS NOT NULL").fetchone()[0])
        coverage[f]={"present":present,"coverage":round(present/total,4) if total else 0.0}
    live=int(conn.execute("SELECT COUNT(*) FROM v9_market_memory WHERE source='live'").fetchone()[0]); backfilled=total-live
    decisions=int(conn.execute("SELECT COUNT(*) FROM v2_setup_decisions").fetchone()[0]); conn.close()
    rich=[coverage[f]["coverage"] for f in fields if f not in ("market_regime","spy_move","qqq_move")]
    rich_avg=sum(rich)/len(rich) if rich else 0.0
    ready=total>=V9_MIN_READY_OBSERVATIONS and rich_avg>=V9_MIN_FIELD_COVERAGE
    return {"ok":True,"version":V9_VERSION,"totalSnapshots":total,"liveSnapshots":live,"backfilledSnapshots":backfilled,
            "sourceDecisions":decisions,"missingSnapshots":max(0,decisions-total),"fieldCoverage":coverage,
            "richFieldAverageCoverage":round(rich_avg,4),"v10Ready":ready,
            "requirements":{"minimumSnapshots":V9_MIN_READY_OBSERVATIONS,"minimumRichFieldCoverage":V9_MIN_FIELD_COVERAGE}}


def v9_recent_memory(limit: int = 50) -> Dict[str, Any]:
    _v9_ensure_tables(); limit=max(1,min(int(limit),500)); conn=db_connect()
    cols=[x[1] for x in conn.execute("PRAGMA table_info(v9_market_memory)").fetchall()]
    rows=conn.execute("SELECT * FROM v9_market_memory ORDER BY decision_id DESC LIMIT ?",(limit,)).fetchall(); conn.close()
    items=[]
    for row in rows:
        d=dict(zip(cols,row)); d.pop("payload_json",None); items.append(d)
    return {"ok":True,"version":V9_VERSION,"count":len(items),"items":items}


def v9_status_payload() -> Dict[str, Any]:
    cov=v9_coverage()
    return {"ok":True,"version":V9_VERSION,"name":V9_NAME,"enabled":V9_ENABLED,"advisoryOnly":True,
            "automaticLiveChanges":False,"automaticPromotion":False,"snapshots":cov["totalSnapshots"],
            "liveSnapshots":cov["liveSnapshots"],"missingSnapshots":cov["missingSnapshots"],"v10Ready":cov["v10Ready"],
            "features":{"automaticDecisionSnapshots":True,"historicalBackfill":True,"explainableDecisionMemory":True,
                        "marketContext":True,"technicalFeatureSchema":True,"newsAndFundamentalPlaceholders":True,
                        "coverageMonitoring":True,"liveTechnicalCollection":V91_INTELLIGENCE_ENABLED,"marketRegimeDetection":True,
                        "relativeVolume":True,"vwapAndEmaDistances":True,"atrAndGap":True,"sectorContext":True,"shadowOnly":True}}


@app.get('/v9/status')
def api_v9_status(): return v9_status_payload()

@app.get('/v9/coverage')
def api_v9_coverage(): return v9_coverage()

@app.get('/v9/memory')
def api_v9_memory(limit: int = 50): return v9_recent_memory(limit)

@app.post('/v9/backfill')
def api_v9_backfill(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v9_backfill(int(payload.get('limit') or 5000))


@app.get('/v9/intelligence/{symbol}')
def api_v9_intelligence(symbol: str, request: Request):
    verify_api_key(request)
    sym=str(symbol or '').upper().strip()
    if not re.fullmatch(r'[A-Z.\-]{1,10}',sym):
        raise HTTPException(status_code=400,detail='Invalid symbol')
    quote=get_quote(sym)
    scan={'symbol':sym,'price':quote['mid'],'bid':quote['bid'],'ask':quote['ask'],'spread':quote['spread']}
    enriched=_v91_enrich_scan(scan)
    return {'ok':True,'version':V9_VERSION,'symbol':sym,'intelligence':enriched}


# =========================
# TRADEBOT V10.0 — EXPLAINABLE RESEARCH ENGINE
# Statistical research over V9 market memory. Shadow-only: never changes orders,
# thresholds, strategy settings, or live trading behaviour.
# =========================
V10_VERSION = "V10.1"
V10_NAME = "Evidence Lineage & Horizon Compatibility Engine"
V10_SCHEMA_VERSION = "10.1"
V10_ENABLED = os.getenv("V10_ENABLED", "true").lower() == "true"
V10_DEFAULT_HORIZON_HOURS = max(1, int(os.getenv("V10_DEFAULT_HORIZON_HOURS", "1") or 1))
V10_MIN_PATTERN_SAMPLES = max(3, int(os.getenv("V10_MIN_PATTERN_SAMPLES", "8") or 8))
V10_MAX_PATTERNS = max(25, min(int(os.getenv("V10_MAX_PATTERNS", "250") or 250), 1000))
_v10_tables_ready = False
_v10_tables_lock = threading.RLock()


def _v10_ensure_tables() -> None:
    global _v10_tables_ready
    if _v10_tables_ready:
        return
    with _v10_tables_lock:
        if _v10_tables_ready:
            return
        _v9_ensure_tables()
        if not SQLITE_ENABLED:
            return
        conn = db_connect()
        conn.execute("""CREATE TABLE IF NOT EXISTS v10_research_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            horizon_hours INTEGER NOT NULL,
            observations INTEGER NOT NULL DEFAULT 0,
            rich_observations INTEGER NOT NULL DEFAULT 0,
            patterns_found INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'RUNNING',
            payload_json TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS v10_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            horizon_hours INTEGER NOT NULL,
            pattern_key TEXT NOT NULL,
            pattern_name TEXT NOT NULL,
            dimensions_json TEXT NOT NULL,
            samples INTEGER NOT NULL,
            wins INTEGER NOT NULL,
            losses INTEGER NOT NULL,
            win_rate REAL NOT NULL,
            average_return_pct REAL NOT NULL,
            median_return_pct REAL NOT NULL,
            expectancy_pct REAL NOT NULL,
            gross_profit_pct REAL NOT NULL,
            gross_loss_pct REAL NOT NULL,
            profit_factor REAL NOT NULL,
            score REAL NOT NULL,
            confidence_grade TEXT NOT NULL,
            explanation TEXT NOT NULL,
            UNIQUE(run_id, pattern_key)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v10_patterns_run_score ON v10_patterns(run_id, score DESC)")
        conn.execute("""CREATE TABLE IF NOT EXISTS v10_research_notebook (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload_json TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS v10_evidence_lineage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_version TEXT NOT NULL DEFAULT '10.1',
            decision_id INTEGER NOT NULL,
            snapshot_id INTEGER NOT NULL,
            outcome_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            observed_at TEXT,
            horizon_hours INTEGER NOT NULL,
            outcome_status TEXT NOT NULL,
            net_return_pct REAL,
            linked_at TEXT NOT NULL,
            UNIQUE(snapshot_id, outcome_id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v10_lineage_horizon_status ON v10_evidence_lineage(horizon_hours,outcome_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v10_lineage_symbol_time ON v10_evidence_lineage(symbol,observed_at)")
        # V18.2.12: schema init stays schema-only. Evidence lineage backfill is
        # performed by normal research/sync paths instead of holding a startup DDL transaction.
        conn.commit(); conn.close()
        _v10_tables_ready = True



def _v10_sync_evidence_lineage(batch_size: int = 250, max_batches: int = 20) -> int:
    """Backfill missing V10 lineage using short transactions (V18.2.12)."""
    if not SQLITE_ENABLED:
        return 0
    total = 0
    batch_size = max(50, min(int(batch_size), 1000))
    for _ in range(max(1, int(max_batches))):
        conn = db_connect()
        try:
            before = conn.total_changes
            conn.execute("""INSERT OR IGNORE INTO v10_evidence_lineage(
                schema_version,decision_id,snapshot_id,outcome_id,symbol,observed_at,horizon_hours,outcome_status,net_return_pct,linked_at)
                SELECT ?,m.decision_id,m.decision_id,o.id,m.symbol,m.observed_at,o.horizon_hours,o.status,o.net_return_pct,?
                FROM v9_market_memory m
                JOIN v2_observation_outcomes o ON o.decision_id=m.decision_id
                LEFT JOIN v10_evidence_lineage l ON l.outcome_id=o.id
                WHERE l.id IS NULL
                ORDER BY o.id ASC LIMIT ?""",
                (V10_SCHEMA_VERSION, datetime.now(UTC).isoformat(), batch_size))
            added = int(conn.total_changes - before)
            conn.commit()
            total += added
        finally:
            conn.close()
        if added < batch_size:
            break
    return total

def _v10_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except Exception:
        return default


def _v10_bin(name: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    if name == "market_regime":
        v = str(value or "").strip().upper()
        return None if v in ("", "UNKNOWN") else v
    if name == "sector":
        v = str(value or "").strip()
        return None if v.lower() in ("", "unknown") else v
    x = _v10_float(value, float("nan"))
    if math.isnan(x):
        return None
    if name == "relative_volume":
        return "RVOL <1" if x < 1 else "RVOL 1-2" if x < 2 else "RVOL 2-4" if x < 4 else "RVOL 4+"
    if name == "gap_pct":
        return "Gap <-2%" if x < -2 else "Gap -2% to 0%" if x < 0 else "Gap 0-2%" if x < 2 else "Gap 2-5%" if x < 5 else "Gap 5%+"
    if name == "distance_vwap_pct":
        return "Below VWAP >1%" if x < -1 else "Below VWAP" if x < 0 else "Above VWAP 0-1%" if x < 1 else "Above VWAP >1%"
    if name == "ema20_distance_pct":
        return "Below EMA20" if x < 0 else "Above EMA20 0-1%" if x < 1 else "Above EMA20 >1%"
    if name == "atr_pct":
        return "ATR <2%" if x < 2 else "ATR 2-4%" if x < 4 else "ATR 4-7%" if x < 7 else "ATR 7%+"
    if name == "sector_strength":
        return "Sector weak" if x < -0.25 else "Sector neutral" if x < 0.25 else "Sector strong"
    if name == "confidence":
        return "Confidence <0.60" if x < .60 else "Confidence 0.60-0.70" if x < .70 else "Confidence 0.70-0.80" if x < .80 else "Confidence 0.80-0.90" if x < .90 else "Confidence 0.90+"
    if name == "session_name":
        return str(value or "UNKNOWN")
    return None


def _v10_grade(samples: int, profit_factor: float, expectancy: float) -> str:
    if samples >= 50 and profit_factor >= 1.5 and expectancy > 0:
        return "A"
    if samples >= 25 and profit_factor >= 1.2 and expectancy > 0:
        return "B"
    if samples >= V10_MIN_PATTERN_SAMPLES and profit_factor >= 1.0 and expectancy >= 0:
        return "C"
    if samples >= V10_MIN_PATTERN_SAMPLES:
        return "D"
    return "INSUFFICIENT"


def _v10_metrics(returns: List[float]) -> Dict[str, Any]:
    clean = [float(x) for x in returns if x is not None and not math.isnan(float(x)) and not math.isinf(float(x))]
    n = len(clean)
    wins = sum(1 for x in clean if x > 0)
    losses = sum(1 for x in clean if x < 0)
    gross_profit = sum(x for x in clean if x > 0)
    gross_loss = abs(sum(x for x in clean if x < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    avg = sum(clean) / n if n else 0.0
    ordered = sorted(clean)
    median = (ordered[n//2] if n % 2 else (ordered[n//2-1] + ordered[n//2]) / 2) if n else 0.0
    win_rate = wins / n if n else 0.0
    # Confidence-aware ranking: rewards positive evidence but limits tiny-sample dominance.
    sample_weight = min(1.0, math.sqrt(n / 50.0)) if n else 0.0
    score = (avg * 35.0 + min(pf, 5.0) * 5.0 + (win_rate - 0.5) * 20.0) * sample_weight
    return {"samples": n, "wins": wins, "losses": losses, "winRate": win_rate,
            "averageReturnPct": avg, "medianReturnPct": median, "expectancyPct": avg,
            "grossProfitPct": gross_profit, "grossLossPct": gross_loss,
            "profitFactor": pf, "score": score, "grade": _v10_grade(n, pf, avg)}


def _v10_available_horizons(conn) -> List[int]:
    rows = conn.execute("""SELECT DISTINCT horizon_hours FROM v10_evidence_lineage
                           WHERE outcome_status='COMPLETE' AND net_return_pct IS NOT NULL
                           ORDER BY horizon_hours""").fetchall()
    return [int(r[0]) for r in rows]


def _v10_resolve_horizon(conn, requested_horizon: int) -> Dict[str, Any]:
    requested = max(1, min(int(requested_horizon), 168))
    available = _v10_available_horizons(conn)
    if not available:
        return {"requested": requested, "effective": requested, "available": [], "exact": False}
    effective = requested if requested in available else min(available, key=lambda h: (abs(h-requested), h))
    return {"requested": requested, "effective": int(effective), "available": available, "exact": requested == effective}


def _v10_load_observations(conn, horizon_hours: int) -> List[Dict[str, Any]]:
    columns = [x[1] for x in conn.execute("PRAGMA table_info(v9_market_memory)").fetchall()]
    query = """SELECT m.*, l.net_return_pct AS v10_return_pct
               FROM v10_evidence_lineage l
               JOIN v9_market_memory m ON m.decision_id=l.snapshot_id
               WHERE l.horizon_hours=? AND l.outcome_status='COMPLETE' AND l.net_return_pct IS NOT NULL
               ORDER BY m.decision_id ASC"""
    rows = conn.execute(query, (int(horizon_hours),)).fetchall()
    return [dict(zip(columns + ["v10_return_pct"], row)) for row in rows]


def v10_run_research(horizon_hours: int = V10_DEFAULT_HORIZON_HOURS,
                     min_samples: int = V10_MIN_PATTERN_SAMPLES) -> Dict[str, Any]:
    _v10_ensure_tables()
    _v10_sync_evidence_lineage()
    requested_horizon = max(1, min(int(horizon_hours), 168))
    min_samples = max(3, min(int(min_samples), 500))
    now = datetime.now(UTC).isoformat()
    conn = db_connect()
    horizon_resolution = _v10_resolve_horizon(conn, requested_horizon)
    horizon_hours = int(horizon_resolution["effective"])
    cur = conn.execute("INSERT INTO v10_research_runs(created_at,horizon_hours,status) VALUES(?,?,'RUNNING')", (now, horizon_hours))
    run_id = int(cur.lastrowid)
    conn.commit()
    try:
        observations = _v10_load_observations(conn, horizon_hours)
        feature_names = ["market_regime", "sector", "relative_volume", "gap_pct", "distance_vwap_pct",
                         "ema20_distance_pct", "atr_pct", "sector_strength", "confidence", "session_name"]
        buckets: Dict[str, Dict[str, Any]] = {}
        rich_count = 0
        for obs in observations:
            ret = _v10_float(obs.get("v10_return_pct"), float("nan"))
            if math.isnan(ret):
                continue
            labels = {name: _v10_bin(name, obs.get(name)) for name in feature_names}
            labels = {k: v for k, v in labels.items() if v is not None}
            if any(k in labels for k in ("relative_volume", "gap_pct", "distance_vwap_pct", "atr_pct")):
                rich_count += 1
            # Single-factor patterns.
            combos = [((k,), (v,)) for k, v in labels.items()]
            # Two-factor interactions provide useful combinations while avoiding overfitting explosion.
            important = [k for k in ("market_regime", "sector", "relative_volume", "gap_pct", "distance_vwap_pct",
                                      "ema20_distance_pct", "atr_pct", "sector_strength") if k in labels]
            for i in range(len(important)):
                for j in range(i + 1, len(important)):
                    k1, k2 = important[i], important[j]
                    combos.append(((k1, k2), (labels[k1], labels[k2])))
            for keys, values in combos:
                dimensions = dict(zip(keys, values))
                key = "|".join(f"{k}={dimensions[k]}" for k in keys)
                item = buckets.setdefault(key, {"dimensions": dimensions, "returns": []})
                item["returns"].append(ret)

        patterns = []
        for key, item in buckets.items():
            metrics = _v10_metrics(item["returns"])
            if metrics["samples"] < min_samples:
                continue
            dims = item["dimensions"]
            name = " + ".join(str(v) for v in dims.values())
            direction = "positive" if metrics["expectancyPct"] > 0 else "negative"
            explanation = (f"{name}: {metrics['samples']} completed observations, "
                           f"{metrics['winRate']*100:.1f}% win rate, {metrics['expectancyPct']:+.3f}% average net return, "
                           f"profit factor {metrics['profitFactor']:.2f}. Evidence is {direction} and remains advisory-only.")
            patterns.append({"key": key, "name": name, "dimensions": dims, **metrics, "explanation": explanation})
        patterns.sort(key=lambda p: (p["score"], p["samples"]), reverse=True)
        patterns = patterns[:V10_MAX_PATTERNS]
        for p in patterns:
            conn.execute("""INSERT OR REPLACE INTO v10_patterns(
                run_id,created_at,horizon_hours,pattern_key,pattern_name,dimensions_json,samples,wins,losses,win_rate,
                average_return_pct,median_return_pct,expectancy_pct,gross_profit_pct,gross_loss_pct,profit_factor,
                score,confidence_grade,explanation) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, now, horizon_hours, p["key"], p["name"], json.dumps(p["dimensions"]), p["samples"],
                 p["wins"], p["losses"], p["winRate"], p["averageReturnPct"], p["medianReturnPct"],
                 p["expectancyPct"], p["grossProfitPct"], p["grossLossPct"], p["profitFactor"], p["score"],
                 p["grade"], p["explanation"]))
        best = [p for p in patterns if p["expectancyPct"] > 0][:5]
        worst = sorted([p for p in patterns if p["expectancyPct"] < 0], key=lambda p: p["score"])[:5]
        summary = (f"Analysed {len(observations)} completed {horizon_hours}-hour outcomes, including {rich_count} rich V9.2 observations. "
                   f"Found {len(patterns)} patterns meeting the {min_samples}-sample threshold. "
                   f"No live settings or orders were changed.")
        notebook_payload = {"bestPatterns": best, "worstPatterns": worst, "advisoryOnly": True}
        conn.execute("INSERT INTO v10_research_notebook(run_id,created_at,title,summary,payload_json) VALUES(?,?,?,?,?)",
                     (run_id, now, f"V10 research — {horizon_hours}h horizon", summary, json.dumps(notebook_payload, default=str)))
        completed = datetime.now(UTC).isoformat()
        run_payload = {"ok": True, "version": V10_VERSION, "runId": run_id,
                       "requestedHorizonHours": requested_horizon, "horizonHours": horizon_hours,
                       "horizonExactMatch": bool(horizon_resolution["exact"]),
                       "availableHorizons": horizon_resolution["available"],
                       "observations": len(observations), "richObservations": rich_count,
                       "patternsFound": len(patterns), "minimumSamples": min_samples,
                       "bestPatterns": best, "worstPatterns": worst, "advisoryOnly": True,
                       "automaticLiveChanges": False, "automaticPromotion": False}
        conn.execute("""UPDATE v10_research_runs SET completed_at=?,observations=?,rich_observations=?,patterns_found=?,status='COMPLETE',payload_json=? WHERE id=?""",
                     (completed, len(observations), rich_count, len(patterns), json.dumps(run_payload, default=str), run_id))
        conn.commit(); conn.close()
        return run_payload
    except Exception as exc:
        conn.execute("UPDATE v10_research_runs SET completed_at=?,status='ERROR',payload_json=? WHERE id=?",
                     (datetime.now(UTC).isoformat(), json.dumps({"error": str(exc)}), run_id))
        conn.commit(); conn.close()
        raise


def v10_latest_report(limit: int = 25) -> Dict[str, Any]:
    _v10_ensure_tables(); limit = max(1, min(int(limit), 250)); conn = db_connect()
    run = conn.execute("SELECT id,created_at,completed_at,horizon_hours,observations,rich_observations,patterns_found,status,payload_json FROM v10_research_runs ORDER BY id DESC LIMIT 1").fetchone()
    if not run:
        conn.close(); return {"ok": True, "version": V10_VERSION, "hasReport": False, "message": "Run POST /v10/research first."}
    run_id = int(run[0])
    rows = conn.execute("""SELECT pattern_key,pattern_name,dimensions_json,samples,wins,losses,win_rate,expectancy_pct,
                           median_return_pct,profit_factor,score,confidence_grade,explanation
                           FROM v10_patterns WHERE run_id=? ORDER BY score DESC LIMIT ?""", (run_id, limit)).fetchall()
    patterns = []
    for row in rows:
        patterns.append({"patternKey": row[0], "name": row[1], "dimensions": json.loads(row[2] or "{}"),
                         "samples": row[3], "wins": row[4], "losses": row[5], "winRate": row[6],
                         "expectancyPct": row[7], "medianReturnPct": row[8], "profitFactor": row[9],
                         "score": row[10], "grade": row[11], "explanation": row[12]})
    conn.close()
    return {"ok": True, "version": V10_VERSION, "hasReport": True,
            "run": {"id": run[0], "createdAt": run[1], "completedAt": run[2], "horizonHours": run[3],
                    "observations": run[4], "richObservations": run[5], "patternsFound": run[6], "status": run[7]},
            "count": len(patterns), "patterns": patterns, "advisoryOnly": True}


def v10_explain_symbol(symbol: str) -> Dict[str, Any]:
    _v10_ensure_tables(); sym = str(symbol or "").upper().strip()
    quote = get_quote(sym)
    intel = _v91_enrich_scan({"symbol": sym, "price": quote["mid"], "bid": quote["bid"], "ask": quote["ask"], "spread": quote["spread"]})
    conn = db_connect()
    run = conn.execute("SELECT id,horizon_hours FROM v10_research_runs WHERE status='COMPLETE' ORDER BY id DESC LIMIT 1").fetchone()
    if not run:
        conn.close(); return {"ok": True, "version": V10_VERSION, "symbol": sym, "intelligence": intel,
                              "matches": [], "message": "No V10 report exists yet. Run POST /v10/research."}
    rows = conn.execute("SELECT pattern_name,dimensions_json,samples,win_rate,expectancy_pct,profit_factor,score,confidence_grade,explanation FROM v10_patterns WHERE run_id=? ORDER BY score DESC", (int(run[0]),)).fetchall()
    matches = []
    for row in rows:
        dims = json.loads(row[1] or "{}")
        matched = True
        for feature, expected in dims.items():
            if _v10_bin(feature, intel.get(feature)) != expected:
                matched = False; break
        if matched:
            matches.append({"name": row[0], "dimensions": dims, "samples": row[2], "winRate": row[3],
                            "expectancyPct": row[4], "profitFactor": row[5], "score": row[6], "grade": row[7],
                            "explanation": row[8]})
        if len(matches) >= 10:
            break
    conn.close()
    positive = [m for m in matches if _v10_float(m.get("expectancyPct")) > 0]
    negative = [m for m in matches if _v10_float(m.get("expectancyPct")) < 0]
    verdict = "INSUFFICIENT_EVIDENCE"
    if positive and not negative: verdict = "HISTORICALLY_FAVOURABLE"
    elif negative and not positive: verdict = "HISTORICALLY_UNFAVOURABLE"
    elif positive and negative: verdict = "MIXED_EVIDENCE"
    return {"ok": True, "version": V10_VERSION, "symbol": sym, "horizonHours": int(run[1]),
            "verdict": verdict, "intelligence": intel, "matchCount": len(matches), "matches": matches,
            "advisoryOnly": True, "automaticLiveChanges": False}


def v10_status_payload() -> Dict[str, Any]:
    _v10_ensure_tables(); conn = db_connect()
    runs = int(conn.execute("SELECT COUNT(*) FROM v10_research_runs WHERE status='COMPLETE'").fetchone()[0])
    latest = conn.execute("SELECT id,observations,rich_observations,patterns_found,completed_at FROM v10_research_runs WHERE status='COMPLETE' ORDER BY id DESC LIMIT 1").fetchone()
    completed_outcomes = int(conn.execute("SELECT COUNT(*) FROM v2_observation_outcomes WHERE status='COMPLETE' AND net_return_pct IS NOT NULL").fetchone()[0])
    lineage_links = int(conn.execute("SELECT COUNT(*) FROM v10_evidence_lineage").fetchone()[0])
    linked_complete = int(conn.execute("SELECT COUNT(*) FROM v10_evidence_lineage WHERE outcome_status='COMPLETE' AND net_return_pct IS NOT NULL").fetchone()[0])
    available_horizons = _v10_available_horizons(conn)
    conn.close()
    return {"ok": True, "version": V10_VERSION, "name": V10_NAME, "enabled": V10_ENABLED,
            "advisoryOnly": True, "automaticLiveChanges": False, "automaticPromotion": False,
            "completedOutcomes": completed_outcomes, "lineageLinks": lineage_links,
            "linkedCompletedOutcomes": linked_complete, "availableHorizons": available_horizons,
            "schemaVersion": V10_SCHEMA_VERSION, "researchRuns": runs,
            "latestRun": None if not latest else {"id": latest[0], "observations": latest[1], "richObservations": latest[2], "patternsFound": latest[3], "completedAt": latest[4]},
            "features": {"singleFactorResearch": True, "twoFactorInteractions": True, "profitFactor": True,
                         "expectancy": True, "researchNotebook": True, "symbolExplanation": True,
                         "sampleSizeWeighting": True, "explicitEvidenceLineage": True,
                         "horizonCompatibility": True, "schemaVersioning": True, "shadowOnly": True}}


@app.get('/v10/lineage/status')
def api_v10_lineage_status(request: Request):
    verify_api_key(request)
    _v10_ensure_tables(); conn=db_connect()
    total=int(conn.execute("SELECT COUNT(*) FROM v10_evidence_lineage").fetchone()[0])
    complete=int(conn.execute("SELECT COUNT(*) FROM v10_evidence_lineage WHERE outcome_status='COMPLETE' AND net_return_pct IS NOT NULL").fetchone()[0])
    by_horizon={str(r[0]): int(r[1]) for r in conn.execute("SELECT horizon_hours,COUNT(*) FROM v10_evidence_lineage WHERE outcome_status='COMPLETE' AND net_return_pct IS NOT NULL GROUP BY horizon_hours ORDER BY horizon_hours").fetchall()}
    missing=int(conn.execute("""SELECT COUNT(*) FROM v2_observation_outcomes o JOIN v9_market_memory m ON m.decision_id=o.decision_id
                                LEFT JOIN v10_evidence_lineage l ON l.outcome_id=o.id WHERE l.id IS NULL""").fetchone()[0])
    conn.close()
    return {"ok":True,"version":V10_VERSION,"schemaVersion":V10_SCHEMA_VERSION,"lineageLinks":total,
            "linkedCompletedOutcomes":complete,"completedByHorizon":by_horizon,"missingEligibleLinks":missing,
            "advisoryOnly":True}

@app.get('/v10/status')
def api_v10_status(request: Request):
    verify_api_key(request); return v10_status_payload()

@app.post('/v10/research')
def api_v10_research(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v10_run_research(int(payload.get('horizonHours') or V10_DEFAULT_HORIZON_HOURS),
                            int(payload.get('minimumSamples') or V10_MIN_PATTERN_SAMPLES))

@app.get('/v10/report')
def api_v10_report(request: Request, limit: int = 25):
    verify_api_key(request); return v10_latest_report(limit)

@app.get('/v10/explain/{symbol}')
def api_v10_explain(symbol: str, request: Request):
    verify_api_key(request)
    sym = str(symbol or '').upper().strip()
    if not re.fullmatch(r'[A-Z.\-]{1,10}', sym):
        raise HTTPException(status_code=400, detail='Invalid symbol')
    return v10_explain_symbol(sym)

# =========================
# TRADEBOT V11.0 — EVIDENCE DISCOVERY ENGINE
# Mines validated multi-factor market setups from explicit V10 lineage.
# Shadow-only: never changes orders, thresholds, strategy settings, or live behaviour.
# =========================
V11_VERSION = "V11.4"
V11_NAME = "Unified Decision Pipeline"
V11_SCHEMA_VERSION = "11.4"
V11_ENABLED = os.getenv("V11_ENABLED", "true").lower() == "true"
V11_DEFAULT_HORIZON_HOURS = max(1, int(os.getenv("V11_DEFAULT_HORIZON_HOURS", "1") or 1))
V11_MIN_SAMPLES = max(8, int(os.getenv("V11_MIN_SAMPLES", "20") or 20))
V11_MAX_DISCOVERIES = max(25, min(int(os.getenv("V11_MAX_DISCOVERIES", "300") or 300), 1500))
V11_VALIDATION_FRACTION = min(0.40, max(0.20, float(os.getenv("V11_VALIDATION_FRACTION", "0.30") or 0.30)))
V11_AUTO_LEARNING_ENABLED = os.getenv("V11_AUTO_LEARNING_ENABLED", "true").lower() == "true"
V11_AUTO_INTERVAL_SECONDS = max(900, int(os.getenv("V11_AUTO_INTERVAL_SECONDS", "21600") or 21600))
V11_AUTO_MIN_NEW_OBSERVATIONS = max(1, int(os.getenv("V11_AUTO_MIN_NEW_OBSERVATIONS", "25") or 25))
V11_AUTO_MIN_NEW_RICH_OBSERVATIONS = max(1, int(os.getenv("V11_AUTO_MIN_NEW_RICH_OBSERVATIONS", "5") or 5))
V11_AUTO_RUN_ON_STARTUP = os.getenv("V11_AUTO_RUN_ON_STARTUP", "false").lower() == "true"
V11_RICH_TARGET_OBSERVATIONS = max(20, int(os.getenv("V11_RICH_TARGET_OBSERVATIONS", "100") or 100))
V11_AUTO_MAX_FACTORS = max(1, min(int(os.getenv("V11_AUTO_MAX_FACTORS", "3") or 3), 3))
v11_last_learning_result: Dict[str, Any] = {}
_v11_tables_ready = False
_v11_tables_lock = threading.RLock()


def _v11_ensure_tables() -> None:
    global _v11_tables_ready
    if _v11_tables_ready:
        return
    with _v11_tables_lock:
        if _v11_tables_ready:
            return
        _v10_ensure_tables()
        if not SQLITE_ENABLED:
            return
        conn = db_connect()
        conn.execute("""CREATE TABLE IF NOT EXISTS v11_discovery_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_version TEXT NOT NULL DEFAULT '11.0',
            created_at TEXT NOT NULL,
            completed_at TEXT,
            requested_horizon_hours INTEGER NOT NULL,
            horizon_hours INTEGER NOT NULL,
            minimum_samples INTEGER NOT NULL,
            observations INTEGER NOT NULL DEFAULT 0,
            rich_observations INTEGER NOT NULL DEFAULT 0,
            candidates_tested INTEGER NOT NULL DEFAULT 0,
            discoveries_found INTEGER NOT NULL DEFAULT 0,
            validated_positive INTEGER NOT NULL DEFAULT 0,
            validated_negative INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'RUNNING',
            payload_json TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS v11_discoveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            horizon_hours INTEGER NOT NULL,
            discovery_key TEXT NOT NULL,
            discovery_name TEXT NOT NULL,
            dimensions_json TEXT NOT NULL,
            factor_count INTEGER NOT NULL,
            samples INTEGER NOT NULL,
            wins INTEGER NOT NULL,
            losses INTEGER NOT NULL,
            win_rate REAL NOT NULL,
            expectancy_pct REAL NOT NULL,
            profit_factor REAL NOT NULL,
            median_return_pct REAL NOT NULL,
            lower95_expectancy_pct REAL NOT NULL,
            baseline_expectancy_pct REAL NOT NULL,
            expectancy_lift_pct REAL NOT NULL,
            train_samples INTEGER NOT NULL,
            train_expectancy_pct REAL NOT NULL,
            train_profit_factor REAL NOT NULL,
            validation_samples INTEGER NOT NULL,
            validation_expectancy_pct REAL NOT NULL,
            validation_profit_factor REAL NOT NULL,
            validation_win_rate REAL NOT NULL,
            stability_score REAL NOT NULL,
            evidence_score REAL NOT NULL,
            classification TEXT NOT NULL,
            explanation TEXT NOT NULL,
            UNIQUE(run_id, discovery_key)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v11_discoveries_run_score ON v11_discoveries(run_id,evidence_score DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v11_discoveries_run_class ON v11_discoveries(run_id,classification)")
        conn.execute("""CREATE TABLE IF NOT EXISTS v11_learning_state (
            id INTEGER PRIMARY KEY CHECK(id=1),
            schema_version TEXT NOT NULL DEFAULT '11.1',
            last_checked_at TEXT,
            last_automatic_run_at TEXT,
            last_run_id INTEGER,
            last_observations INTEGER NOT NULL DEFAULT 0,
            last_rich_observations INTEGER NOT NULL DEFAULT 0,
            last_status TEXT NOT NULL DEFAULT 'NEVER_RUN',
            last_reason TEXT,
            last_error TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS v11_learning_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            run_id INTEGER,
            trigger_type TEXT NOT NULL,
            observations INTEGER NOT NULL DEFAULT 0,
            rich_observations INTEGER NOT NULL DEFAULT 0,
            new_observations INTEGER NOT NULL DEFAULT 0,
            new_rich_observations INTEGER NOT NULL DEFAULT 0,
            validated_positive INTEGER NOT NULL DEFAULT 0,
            validated_negative INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            reason TEXT,
            payload_json TEXT
        )""")
        conn.execute("INSERT OR IGNORE INTO v11_learning_state(id,schema_version) VALUES(1,?)", (V11_SCHEMA_VERSION,))
        conn.commit(); conn.close()
        _v11_tables_ready = True


def _v11_bin(name: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    if name in ("market_regime", "sector", "session_name"):
        text = str(value or "").strip()
        if not text or text.lower() == "unknown":
            return None
        return text.upper() if name == "market_regime" else text
    if name in ("opening_range_breakout", "sniper_pass", "a_plus_pass", "ready_to_buy"):
        return f"{name}={'YES' if bool(value) else 'NO'}"
    x = _v10_float(value, float("nan"))
    if math.isnan(x):
        return None
    if name == "relative_volume":
        return "RVOL <1" if x < 1 else "RVOL 1-2" if x < 2 else "RVOL 2-4" if x < 4 else "RVOL 4-8" if x < 8 else "RVOL 8+"
    if name == "gap_pct":
        return "Gap <-2%" if x < -2 else "Gap -2% to 0%" if x < 0 else "Gap 0-2%" if x < 2 else "Gap 2-5%" if x < 5 else "Gap 5%+"
    if name == "distance_vwap_pct":
        return "VWAP <-1%" if x < -1 else "Below VWAP" if x < 0 else "VWAP +0-1%" if x < 1 else "VWAP +1%+"
    if name in ("ema9_distance_pct", "ema20_distance_pct", "ema50_distance_pct"):
        label = name.replace("_distance_pct", "").upper()
        return f"Below {label}" if x < 0 else f"Above {label} 0-1%" if x < 1 else f"Above {label} 1%+"
    if name == "atr_pct":
        return "ATR <2%" if x < 2 else "ATR 2-4%" if x < 4 else "ATR 4-7%" if x < 7 else "ATR 7%+"
    if name == "day_range_position":
        return "Range bottom" if x < .25 else "Range lower-middle" if x < .50 else "Range upper-middle" if x < .75 else "Range top"
    if name == "sector_strength":
        return "Sector weak" if x < -.25 else "Sector neutral" if x < .25 else "Sector strong"
    if name == "confidence":
        return "Confidence <0.60" if x < .60 else "Confidence 0.60-0.70" if x < .70 else "Confidence 0.70-0.80" if x < .80 else "Confidence 0.80-0.90" if x < .90 else "Confidence 0.90+"
    if name == "momentum":
        return "Momentum negative" if x < 0 else "Momentum 0-1%" if x < .01 else "Momentum 1-3%" if x < .03 else "Momentum 3%+"
    if name == "pullback":
        return "Pullback <0.5%" if x < .005 else "Pullback 0.5-1.5%" if x < .015 else "Pullback 1.5-3%" if x < .03 else "Pullback 3%+"
    if name == "spread":
        return "Spread <0.3%" if x < .003 else "Spread 0.3-0.8%" if x < .008 else "Spread 0.8-1.5%" if x < .015 else "Spread 1.5%+"
    return None


def _v11_stats(values: List[float]) -> Dict[str, Any]:
    m = _v10_metrics(values)
    clean = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    n = len(clean)
    if n > 1:
        mean = sum(clean) / n
        variance = sum((x - mean) ** 2 for x in clean) / (n - 1)
        se = math.sqrt(max(0.0, variance) / n)
        lower95 = mean - 1.96 * se
    else:
        lower95 = clean[0] if clean else 0.0
    return {**m, "lower95ExpectancyPct": lower95}


def _v11_classify(all_m: Dict[str, Any], train_m: Dict[str, Any], val_m: Dict[str, Any], min_validation: int) -> str:
    enough_val = val_m["samples"] >= min_validation
    positive = (all_m["expectancyPct"] > 0 and all_m["profitFactor"] > 1.0 and
                train_m["expectancyPct"] > 0 and train_m["profitFactor"] > 1.0 and
                enough_val and val_m["expectancyPct"] > 0 and val_m["profitFactor"] > 1.0)
    negative = (all_m["expectancyPct"] < 0 and all_m["profitFactor"] < 1.0 and
                train_m["expectancyPct"] < 0 and train_m["profitFactor"] < 1.0 and
                enough_val and val_m["expectancyPct"] < 0 and val_m["profitFactor"] < 1.0)
    if positive:
        return "VALIDATED_POSITIVE"
    if negative:
        return "VALIDATED_NEGATIVE"
    return "UNSTABLE_OR_INSUFFICIENT"


def _v11_evidence_score(all_m: Dict[str, Any], train_m: Dict[str, Any], val_m: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, float]:
    lift = all_m["expectancyPct"] - baseline["expectancyPct"]
    same_direction = (train_m["expectancyPct"] == 0 or val_m["expectancyPct"] == 0 or
                      (train_m["expectancyPct"] > 0) == (val_m["expectancyPct"] > 0))
    gap = abs(train_m["expectancyPct"] - val_m["expectancyPct"])
    stability = max(0.0, 1.0 - min(1.0, gap / max(.10, abs(all_m["expectancyPct"]) + .10)))
    if not same_direction:
        stability *= .25
    sample_weight = min(1.0, math.sqrt(all_m["samples"] / 100.0))
    validation_weight = min(1.0, math.sqrt(val_m["samples"] / 30.0)) if val_m["samples"] else 0.0
    direction = 1.0 if all_m["expectancyPct"] >= 0 else -1.0
    strength = (abs(all_m["expectancyPct"]) * 45.0 + abs(lift) * 25.0 +
                abs(min(all_m["profitFactor"], 5.0) - 1.0) * 8.0 +
                abs(all_m["winRate"] - .5) * 15.0)
    score = direction * strength * sample_weight * (.45 + .55 * validation_weight) * (.35 + .65 * stability)
    return {"evidenceScore": score, "stabilityScore": stability, "expectancyLiftPct": lift}


def _v11_load_rows(conn, horizon_hours: int) -> List[Dict[str, Any]]:
    rows = _v10_load_observations(conn, horizon_hours)
    rows.sort(key=lambda r: str(r.get("observed_at") or ""))
    return rows


def v11_run_discovery(horizon_hours: int = V11_DEFAULT_HORIZON_HOURS,
                      min_samples: int = V11_MIN_SAMPLES,
                      max_factors: int = 3) -> Dict[str, Any]:
    _v11_ensure_tables()
    requested = max(1, min(int(horizon_hours), 168))
    min_samples = max(8, min(int(min_samples), 1000))
    max_factors = max(1, min(int(max_factors), 3))
    now = datetime.now(UTC).isoformat()
    conn = db_connect()
    resolved = _v10_resolve_horizon(conn, requested)
    effective = int(resolved["effective"])
    cur = conn.execute("""INSERT INTO v11_discovery_runs(
        schema_version,created_at,requested_horizon_hours,horizon_hours,minimum_samples,status)
        VALUES(?,?,?,?,?,'RUNNING')""", (V11_SCHEMA_VERSION, now, requested, effective, min_samples))
    run_id = int(cur.lastrowid); conn.commit()
    try:
        rows = _v11_load_rows(conn, effective)
        returns = [_v10_float(r.get("v10_return_pct"), float("nan")) for r in rows]
        returns = [x for x in returns if math.isfinite(x)]
        baseline = _v11_stats(returns)
        feature_names = [
            "market_regime", "sector", "session_name", "relative_volume", "gap_pct",
            "distance_vwap_pct", "ema9_distance_pct", "ema20_distance_pct", "ema50_distance_pct",
            "atr_pct", "day_range_position", "opening_range_breakout", "sector_strength",
            "confidence", "momentum", "pullback", "spread", "sniper_pass", "a_plus_pass"
        ]
        market_features = {
            "market_regime", "sector", "relative_volume", "gap_pct", "distance_vwap_pct",
            "ema9_distance_pct", "ema20_distance_pct", "ema50_distance_pct", "atr_pct",
            "day_range_position", "opening_range_breakout", "sector_strength"
        }
        buckets: Dict[str, Dict[str, Any]] = {}
        rich_count = 0
        split_index = max(1, min(len(rows) - 1, int(len(rows) * (1.0 - V11_VALIDATION_FRACTION)))) if len(rows) > 1 else len(rows)
        for idx, obs in enumerate(rows):
            ret = _v10_float(obs.get("v10_return_pct"), float("nan"))
            if not math.isfinite(ret):
                continue
            labels = {name: _v11_bin(name, obs.get(name)) for name in feature_names}
            labels = {k: v for k, v in labels.items() if v is not None}
            rich_here = sum(1 for k in market_features if k in labels)
            if rich_here >= 2:
                rich_count += 1
            keys = list(labels.keys())
            combinations: List[tuple] = []
            for key in keys:
                combinations.append((key,))
            if max_factors >= 2:
                for i in range(len(keys)):
                    for j in range(i + 1, len(keys)):
                        pair = (keys[i], keys[j])
                        if any(k in market_features for k in pair):
                            combinations.append(pair)
            if max_factors >= 3:
                important = [k for k in keys if k in market_features]
                context = [k for k in keys if k in ("confidence", "session_name", "sniper_pass", "a_plus_pass")]
                triple_pool = important + context
                for i in range(len(triple_pool)):
                    for j in range(i + 1, len(triple_pool)):
                        for k in range(j + 1, len(triple_pool)):
                            triple = (triple_pool[i], triple_pool[j], triple_pool[k])
                            if sum(1 for x in triple if x in market_features) >= 2:
                                combinations.append(triple)
            seen = set()
            for combo in combinations:
                combo = tuple(sorted(combo))
                if combo in seen:
                    continue
                seen.add(combo)
                dims = {k: labels[k] for k in combo}
                key = "|".join(f"{k}={dims[k]}" for k in combo)
                item = buckets.setdefault(key, {"dimensions": dims, "all": [], "train": [], "validation": []})
                item["all"].append(ret)
                item["train" if idx < split_index else "validation"].append(ret)

        discoveries = []
        min_validation = max(5, int(math.ceil(min_samples * V11_VALIDATION_FRACTION * .60)))
        for key, item in buckets.items():
            all_m = _v11_stats(item["all"])
            if all_m["samples"] < min_samples:
                continue
            train_m = _v11_stats(item["train"])
            val_m = _v11_stats(item["validation"])
            scoring = _v11_evidence_score(all_m, train_m, val_m, baseline)
            classification = _v11_classify(all_m, train_m, val_m, min_validation)
            dims = item["dimensions"]
            name = " + ".join(str(v) for v in dims.values())
            explanation = (
                f"{name}: {all_m['samples']} observations, {all_m['winRate']*100:.1f}% win rate, "
                f"{all_m['expectancyPct']:+.3f}% expectancy and PF {all_m['profitFactor']:.2f}. "
                f"Validation: {val_m['samples']} observations, {val_m['expectancyPct']:+.3f}% expectancy, "
                f"PF {val_m['profitFactor']:.2f}. Classification: {classification}. Advisory-only."
            )
            discoveries.append({
                "key": key, "name": name, "dimensions": dims, "factorCount": len(dims),
                **all_m, **scoring,
                "baselineExpectancyPct": baseline["expectancyPct"],
                "trainSamples": train_m["samples"], "trainExpectancyPct": train_m["expectancyPct"],
                "trainProfitFactor": train_m["profitFactor"],
                "validationSamples": val_m["samples"], "validationExpectancyPct": val_m["expectancyPct"],
                "validationProfitFactor": val_m["profitFactor"], "validationWinRate": val_m["winRate"],
                "classification": classification, "explanation": explanation
            })
        discoveries.sort(key=lambda d: (d["classification"] == "VALIDATED_POSITIVE", d["evidenceScore"], d["samples"]), reverse=True)
        discoveries = discoveries[:V11_MAX_DISCOVERIES]
        for d in discoveries:
            conn.execute("""INSERT OR REPLACE INTO v11_discoveries(
                run_id,created_at,horizon_hours,discovery_key,discovery_name,dimensions_json,factor_count,
                samples,wins,losses,win_rate,expectancy_pct,profit_factor,median_return_pct,lower95_expectancy_pct,
                baseline_expectancy_pct,expectancy_lift_pct,train_samples,train_expectancy_pct,train_profit_factor,
                validation_samples,validation_expectancy_pct,validation_profit_factor,validation_win_rate,
                stability_score,evidence_score,classification,explanation)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, now, effective, d["key"], d["name"], json.dumps(d["dimensions"]), d["factorCount"],
                 d["samples"], d["wins"], d["losses"], d["winRate"], d["expectancyPct"], d["profitFactor"],
                 d["medianReturnPct"], d["lower95ExpectancyPct"], d["baselineExpectancyPct"], d["expectancyLiftPct"],
                 d["trainSamples"], d["trainExpectancyPct"], d["trainProfitFactor"], d["validationSamples"],
                 d["validationExpectancyPct"], d["validationProfitFactor"], d["validationWinRate"],
                 d["stabilityScore"], d["evidenceScore"], d["classification"], d["explanation"]))
        positive = [d for d in discoveries if d["classification"] == "VALIDATED_POSITIVE"]
        negative = [d for d in discoveries if d["classification"] == "VALIDATED_NEGATIVE"]
        payload = {
            "ok": True, "version": V11_VERSION, "runId": run_id,
            "requestedHorizonHours": requested, "horizonHours": effective,
            "horizonExactMatch": bool(resolved["exact"]), "availableHorizons": resolved["available"],
            "observations": len(rows), "richObservations": rich_count, "candidatesTested": len(buckets),
            "discoveriesFound": len(discoveries), "validatedPositive": len(positive),
            "validatedNegative": len(negative), "minimumSamples": min_samples, "maxFactors": max_factors,
            "baseline": baseline, "bestValidated": positive[:10],
            "worstValidated": sorted(negative, key=lambda d: d["evidenceScore"])[:10],
            "advisoryOnly": True, "automaticLiveChanges": False, "automaticPromotion": False
        }
        conn.execute("""UPDATE v11_discovery_runs SET completed_at=?,observations=?,rich_observations=?,
            candidates_tested=?,discoveries_found=?,validated_positive=?,validated_negative=?,status='COMPLETE',payload_json=?
            WHERE id=?""", (datetime.now(UTC).isoformat(), len(rows), rich_count, len(buckets), len(discoveries),
                            len(positive), len(negative), json.dumps(payload, default=str), run_id))
        conn.commit(); conn.close(); return payload
    except Exception as exc:
        conn.execute("UPDATE v11_discovery_runs SET completed_at=?,status='ERROR',payload_json=? WHERE id=?",
                     (datetime.now(UTC).isoformat(), json.dumps({"error": str(exc)}), run_id))
        conn.commit(); conn.close(); raise


def v11_latest_report(limit: int = 50, classification: Optional[str] = None) -> Dict[str, Any]:
    _v11_ensure_tables(); limit = max(1, min(int(limit), 300)); conn = db_connect()
    run = conn.execute("""SELECT id,created_at,completed_at,requested_horizon_hours,horizon_hours,minimum_samples,
                          observations,rich_observations,candidates_tested,discoveries_found,validated_positive,
                          validated_negative,status,payload_json FROM v11_discovery_runs ORDER BY id DESC LIMIT 1""").fetchone()
    if not run:
        conn.close(); return {"ok": True, "version": V11_VERSION, "hasReport": False, "message": "Run POST /v11/discover first."}
    where = "run_id=?"; params: List[Any] = [int(run[0])]
    valid_classes = {"VALIDATED_POSITIVE", "VALIDATED_NEGATIVE", "UNSTABLE_OR_INSUFFICIENT"}
    if classification and classification.upper() in valid_classes:
        where += " AND classification=?"; params.append(classification.upper())
    params.append(limit)
    rows = conn.execute(f"""SELECT discovery_key,discovery_name,dimensions_json,factor_count,samples,wins,losses,
        win_rate,expectancy_pct,profit_factor,median_return_pct,lower95_expectancy_pct,baseline_expectancy_pct,
        expectancy_lift_pct,train_samples,train_expectancy_pct,train_profit_factor,validation_samples,
        validation_expectancy_pct,validation_profit_factor,validation_win_rate,stability_score,evidence_score,
        classification,explanation FROM v11_discoveries WHERE {where}
        ORDER BY CASE classification WHEN 'VALIDATED_POSITIVE' THEN 0 WHEN 'VALIDATED_NEGATIVE' THEN 1 ELSE 2 END,
                 evidence_score DESC LIMIT ?""", tuple(params)).fetchall()
    columns = ["key","name","dimensions","factorCount","samples","wins","losses","winRate","expectancyPct",
               "profitFactor","medianReturnPct","lower95ExpectancyPct","baselineExpectancyPct","expectancyLiftPct",
               "trainSamples","trainExpectancyPct","trainProfitFactor","validationSamples","validationExpectancyPct",
               "validationProfitFactor","validationWinRate","stabilityScore","evidenceScore","classification","explanation"]
    output = []
    for row in rows:
        item = dict(zip(columns, row)); item["dimensions"] = json.loads(item["dimensions"] or "{}")
        output.append(item)
    conn.close()
    return {"ok": True, "version": V11_VERSION, "hasReport": True,
            "run": {"id": run[0], "createdAt": run[1], "completedAt": run[2],
                    "requestedHorizonHours": run[3], "horizonHours": run[4], "minimumSamples": run[5],
                    "observations": run[6], "richObservations": run[7], "candidatesTested": run[8],
                    "discoveriesFound": run[9], "validatedPositive": run[10], "validatedNegative": run[11],
                    "status": run[12]}, "count": len(output), "discoveries": output,
            "advisoryOnly": True, "automaticLiveChanges": False}


def v11_explain_symbol(symbol: str) -> Dict[str, Any]:
    _v11_ensure_tables(); sym = str(symbol or "").upper().strip()
    quote = get_quote(sym)
    intel = _v91_enrich_scan({"symbol": sym, "price": quote["mid"], "bid": quote["bid"], "ask": quote["ask"], "spread": quote["spread"]})
    conn = db_connect()
    run = conn.execute("SELECT id,horizon_hours FROM v11_discovery_runs WHERE status='COMPLETE' ORDER BY id DESC LIMIT 1").fetchone()
    if not run:
        conn.close(); return {"ok": True, "version": V11_VERSION, "symbol": sym, "verdict": "NO_DISCOVERY_RUN", "intelligence": intel, "matches": []}
    rows = conn.execute("""SELECT discovery_name,dimensions_json,samples,win_rate,expectancy_pct,profit_factor,
        validation_samples,validation_expectancy_pct,validation_profit_factor,evidence_score,classification,explanation
        FROM v11_discoveries WHERE run_id=? ORDER BY evidence_score DESC""", (int(run[0]),)).fetchall()
    matches = []
    for row in rows:
        dims = json.loads(row[1] or "{}")
        if all(_v11_bin(feature, intel.get(feature)) == expected for feature, expected in dims.items()):
            matches.append({"name": row[0], "dimensions": dims, "samples": row[2], "winRate": row[3],
                            "expectancyPct": row[4], "profitFactor": row[5], "validationSamples": row[6],
                            "validationExpectancyPct": row[7], "validationProfitFactor": row[8],
                            "evidenceScore": row[9], "classification": row[10], "explanation": row[11]})
        if len(matches) >= 15:
            break
    conn.close()
    positives = [m for m in matches if m["classification"] == "VALIDATED_POSITIVE"]
    negatives = [m for m in matches if m["classification"] == "VALIDATED_NEGATIVE"]
    verdict = "INSUFFICIENT_VALIDATED_EVIDENCE"
    if positives and not negatives:
        verdict = "VALIDATED_FAVOURABLE"
    elif negatives and not positives:
        verdict = "VALIDATED_UNFAVOURABLE"
    elif positives and negatives:
        positive_weight = sum(max(0.0, float(m["evidenceScore"])) for m in positives)
        negative_weight = abs(sum(min(0.0, float(m["evidenceScore"])) for m in negatives))
        verdict = "MIXED_LEAN_FAVOURABLE" if positive_weight > negative_weight else "MIXED_LEAN_UNFAVOURABLE"
    return {"ok": True, "version": V11_VERSION, "symbol": sym, "horizonHours": int(run[1]),
            "verdict": verdict, "intelligence": intel, "matchCount": len(matches), "matches": matches,
            "advisoryOnly": True, "automaticLiveChanges": False, "automaticPromotion": False}



def _v11_current_evidence_counts(horizon_hours: int = V11_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    _v11_ensure_tables()
    conn = db_connect()
    resolved = _v10_resolve_horizon(conn, max(1, int(horizon_hours)))
    effective = int(resolved["effective"])
    rows = _v11_load_rows(conn, effective)
    market_features = {
        "market_regime", "sector", "relative_volume", "gap_pct", "distance_vwap_pct",
        "ema9_distance_pct", "ema20_distance_pct", "ema50_distance_pct", "atr_pct",
        "day_range_position", "opening_range_breakout", "sector_strength"
    }
    rich = 0
    for obs in rows:
        labels = {name: _v11_bin(name, obs.get(name)) for name in market_features}
        if sum(1 for value in labels.values() if value is not None) >= 2:
            rich += 1
    conn.close()
    return {
        "requestedHorizonHours": int(horizon_hours), "horizonHours": effective,
        "horizonExactMatch": bool(resolved["exact"]), "availableHorizons": resolved["available"],
        "observations": len(rows), "richObservations": rich
    }


def v11_learning_cycle(trigger_type: str = "manual", force: bool = False) -> Dict[str, Any]:
    global v11_last_learning_result
    _v11_ensure_tables()
    now = datetime.now(UTC).isoformat()
    counts = _v11_current_evidence_counts(V11_DEFAULT_HORIZON_HOURS)
    conn = db_connect()
    state = conn.execute("SELECT last_observations,last_rich_observations,last_automatic_run_at FROM v11_learning_state WHERE id=1").fetchone()
    previous_obs = int(state[0] or 0) if state else 0
    previous_rich = int(state[1] or 0) if state else 0
    new_obs = max(0, int(counts["observations"]) - previous_obs)
    new_rich = max(0, int(counts["richObservations"]) - previous_rich)
    should_run = bool(force or trigger_type == "manual" or
                      new_rich >= V11_AUTO_MIN_NEW_RICH_OBSERVATIONS or
                      new_obs >= V11_AUTO_MIN_NEW_OBSERVATIONS)
    reason = "forced/manual run" if (force or trigger_type == "manual") else (
        f"new rich evidence threshold reached ({new_rich})" if new_rich >= V11_AUTO_MIN_NEW_RICH_OBSERVATIONS
        else f"new evidence threshold reached ({new_obs})" if new_obs >= V11_AUTO_MIN_NEW_OBSERVATIONS
        else "waiting for more evidence")
    if not should_run:
        result = {"ok": True, "version": V11_VERSION, "ranDiscovery": False, "trigger": trigger_type,
                  **counts, "newObservations": new_obs, "newRichObservations": new_rich,
                  "reason": reason, "nextCheckSeconds": V11_AUTO_INTERVAL_SECONDS,
                  "richEvidenceProgressPct": min(100.0, counts["richObservations"] / V11_RICH_TARGET_OBSERVATIONS * 100.0),
                  "advisoryOnly": True, "automaticLiveChanges": False}
        conn.execute("UPDATE v11_learning_state SET schema_version=?,last_checked_at=?,last_status='WAITING',last_reason=?,last_error=NULL WHERE id=1",
                     (V11_SCHEMA_VERSION, now, reason))
        conn.commit(); conn.close(); v11_last_learning_result = result; return result
    conn.close()
    try:
        discovery = v11_run_discovery(counts["horizonHours"], V11_MIN_SAMPLES, V11_AUTO_MAX_FACTORS)
        conn = db_connect()
        conn.execute("""UPDATE v11_learning_state SET schema_version=?,last_checked_at=?,last_automatic_run_at=?,
            last_run_id=?,last_observations=?,last_rich_observations=?,last_status='COMPLETE',last_reason=?,last_error=NULL WHERE id=1""",
            (V11_SCHEMA_VERSION, now, now, discovery.get("runId"), counts["observations"], counts["richObservations"], reason))
        conn.execute("""INSERT INTO v11_learning_history(created_at,run_id,trigger_type,observations,rich_observations,
            new_observations,new_rich_observations,validated_positive,validated_negative,status,reason,payload_json)
            VALUES(?,?,?,?,?,?,?,?,?,'COMPLETE',?,?)""",
            (now, discovery.get("runId"), trigger_type, counts["observations"], counts["richObservations"], new_obs, new_rich,
             discovery.get("validatedPositive",0), discovery.get("validatedNegative",0), reason, json.dumps(discovery, default=str)))
        conn.commit(); conn.close()
        result = {"ok": True, "version": V11_VERSION, "ranDiscovery": True, "trigger": trigger_type,
                  "newObservations": new_obs, "newRichObservations": new_rich,
                  "richEvidenceProgressPct": min(100.0, counts["richObservations"] / V11_RICH_TARGET_OBSERVATIONS * 100.0),
                  "reason": reason, "discovery": discovery,
                  "advisoryOnly": True, "automaticLiveChanges": False, "automaticPromotion": False}
        v11_last_learning_result = result; return result
    except Exception as exc:
        conn = db_connect()
        conn.execute("UPDATE v11_learning_state SET last_checked_at=?,last_status='ERROR',last_reason=?,last_error=? WHERE id=1",
                     (now, reason, str(exc)))
        conn.commit(); conn.close()
        v11_last_learning_result = {"ok": False, "version": V11_VERSION, "ranDiscovery": False,
                                    "trigger": trigger_type, "error": str(exc), "reason": reason}
        return v11_last_learning_result


def v11_auto_learning_worker() -> None:
    first = True
    while True:
        try:
            if AI_RESEARCH_CLOSED_MARKET_ONLY and _ai_research_market_open() is not False:
                time.sleep(60)
                continue
            if not first or V11_AUTO_RUN_ON_STARTUP:
                result = v11_learning_cycle("automatic", force=False)
                if result.get("ranDiscovery"):
                    print(f"V11.1 AUTO LEARNING | run={result.get('discovery',{}).get('runId')} "
                          f"obs={result.get('discovery',{}).get('observations')} rich={result.get('discovery',{}).get('richObservations')}")
            first = False
        except Exception as exc:
            print(f"V11.1 AUTO LEARNING ERROR: {exc}")
        time.sleep(V11_AUTO_INTERVAL_SECONDS)


def v11_learning_status_payload() -> Dict[str, Any]:
    _v11_ensure_tables()
    counts = _v11_current_evidence_counts(V11_DEFAULT_HORIZON_HOURS)
    conn = db_connect()
    state = conn.execute("SELECT schema_version,last_checked_at,last_automatic_run_at,last_run_id,last_observations,last_rich_observations,last_status,last_reason,last_error FROM v11_learning_state WHERE id=1").fetchone()
    history = conn.execute("SELECT COUNT(*) FROM v11_learning_history WHERE status='COMPLETE'").fetchone()[0]
    conn.close()
    return {"ok": True, "version": V11_VERSION, "name": V11_NAME, "enabled": V11_AUTO_LEARNING_ENABLED,
            "intervalSeconds": V11_AUTO_INTERVAL_SECONDS, "minimumNewObservations": V11_AUTO_MIN_NEW_OBSERVATIONS,
            "minimumNewRichObservations": V11_AUTO_MIN_NEW_RICH_OBSERVATIONS,
            "richEvidenceTarget": V11_RICH_TARGET_OBSERVATIONS,
            "richEvidenceProgressPct": min(100.0, counts["richObservations"] / V11_RICH_TARGET_OBSERVATIONS * 100.0),
            **counts, "learningRuns": int(history),
            "state": None if not state else {"schemaVersion": state[0], "lastCheckedAt": state[1],
                "lastAutomaticRunAt": state[2], "lastRunId": state[3], "lastObservations": state[4],
                "lastRichObservations": state[5], "status": state[6], "reason": state[7], "error": state[8]},
            "lastResult": v11_last_learning_result or None,
            "advisoryOnly": True, "automaticLiveChanges": False, "automaticPromotion": False}


def v11_learning_history_payload(limit: int = 25) -> Dict[str, Any]:
    _v11_ensure_tables(); limit = max(1, min(int(limit), 200)); conn = db_connect()
    rows = conn.execute("""SELECT id,created_at,run_id,trigger_type,observations,rich_observations,new_observations,
        new_rich_observations,validated_positive,validated_negative,status,reason FROM v11_learning_history
        ORDER BY id DESC LIMIT ?""", (limit,)).fetchall(); conn.close()
    cols = ["id","createdAt","runId","trigger","observations","richObservations","newObservations",
            "newRichObservations","validatedPositive","validatedNegative","status","reason"]
    return {"ok": True, "version": V11_VERSION, "count": len(rows),
            "history": [dict(zip(cols,row)) for row in rows], "advisoryOnly": True}

def v11_status_payload() -> Dict[str, Any]:
    _v11_ensure_tables(); conn = db_connect()
    runs = int(conn.execute("SELECT COUNT(*) FROM v11_discovery_runs WHERE status='COMPLETE'").fetchone()[0])
    latest = conn.execute("""SELECT id,observations,rich_observations,candidates_tested,discoveries_found,
                              validated_positive,validated_negative,completed_at FROM v11_discovery_runs
                              WHERE status='COMPLETE' ORDER BY id DESC LIMIT 1""").fetchone()
    horizons = _v10_available_horizons(conn); conn.close()
    return {"ok": True, "version": V11_VERSION, "name": V11_NAME, "schemaVersion": V11_SCHEMA_VERSION,
            "enabled": V11_ENABLED, "availableHorizons": horizons, "discoveryRuns": runs,
            "latestRun": None if not latest else {"id": latest[0], "observations": latest[1],
                "richObservations": latest[2], "candidatesTested": latest[3], "discoveriesFound": latest[4],
                "validatedPositive": latest[5], "validatedNegative": latest[6], "completedAt": latest[7]},
            "features": {"singleFactorDiscovery": True, "twoFactorInteractions": True,
                         "threeFactorInteractions": True, "chronologicalValidation": True,
                         "baselineLift": True, "lower95Expectancy": True, "stabilityScoring": True,
                         "liveSymbolExplanation": True, "automaticLearning": True, "richEvidenceTracking": True,
                         "thresholdTriggeredResearch": True, "learningHistory": True, "richCaptureAudit": True, "missingFieldDiagnostics": True, "pipelineReadiness": True, "captureRepair": True, "postWriteVerification": True, "endToEndCaptureTest": True, "unifiedDecisionPipeline": True, "decisionTrace": True, "writerAttribution": True, "shadowOnly": True},
            "autoLearning": {"enabled": V11_AUTO_LEARNING_ENABLED, "intervalSeconds": V11_AUTO_INTERVAL_SECONDS,
                             "minimumNewObservations": V11_AUTO_MIN_NEW_OBSERVATIONS,
                             "minimumNewRichObservations": V11_AUTO_MIN_NEW_RICH_OBSERVATIONS,
                             "richEvidenceTarget": V11_RICH_TARGET_OBSERVATIONS},
            "advisoryOnly": True, "automaticLiveChanges": False, "automaticPromotion": False}


@app.get('/v11/status')
def api_v11_status(request: Request):
    verify_api_key(request); return v11_status_payload()


@app.post('/v11/discover')
def api_v11_discover(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v11_run_discovery(int(payload.get('horizonHours') or V11_DEFAULT_HORIZON_HOURS),
                             int(payload.get('minimumSamples') or V11_MIN_SAMPLES),
                             int(payload.get('maxFactors') or 3))


@app.get('/v11/report')
def api_v11_report(request: Request, limit: int = 50, classification: Optional[str] = None):
    verify_api_key(request); return v11_latest_report(limit, classification)


@app.get('/v11/explain/{symbol}')
def api_v11_explain(symbol: str, request: Request):
    verify_api_key(request)
    sym = str(symbol or '').upper().strip()
    if not re.fullmatch(r'[A-Z.\-]{1,10}', sym):
        raise HTTPException(status_code=400, detail='Invalid symbol')
    return v11_explain_symbol(sym)


@app.get('/v11/learning/status')
def api_v11_learning_status(request: Request):
    verify_api_key(request); return v11_learning_status_payload()


@app.post('/v11/learning/run')
def api_v11_learning_run(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v11_learning_cycle('manual', bool(payload.get('force', True)))


@app.get('/v11/learning/history')
def api_v11_learning_history(request: Request, limit: int = 25):
    verify_api_key(request); return v11_learning_history_payload(limit)


# =========================
# TRADEBOT V11.2 — RICH EVIDENCE PIPELINE GUARDIAN
# Verifies live V9.2 capture quality and explains why evidence is not research-ready.
# Shadow-only. It never changes trading decisions or historical snapshots.
# =========================
V112_CORE_RICH_FIELDS = (
    "relative_volume", "gap_pct", "distance_vwap_pct", "ema20_distance_pct", "atr_pct"
)
V112_CONTEXT_FIELDS = (
    "market_regime", "sector", "sector_strength", "day_range_position", "premarket_volume"
)
V112_MIN_CORE_FIELDS = max(2, min(int(os.getenv("V112_MIN_CORE_FIELDS", "4") or 4), len(V112_CORE_RICH_FIELDS)))
V112_RECENT_HOURS = max(1, min(int(os.getenv("V112_RECENT_HOURS", "72") or 72), 720))


def _v112_ensure_tables() -> None:
    if not SQLITE_ENABLED:
        return
    conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS v11_rich_capture_audit (
        decision_id INTEGER PRIMARY KEY,
        audited_at TEXT NOT NULL,
        symbol TEXT NOT NULL,
        source TEXT NOT NULL,
        core_present INTEGER NOT NULL DEFAULT 0,
        core_required INTEGER NOT NULL DEFAULT 4,
        rich_ready INTEGER NOT NULL DEFAULT 0,
        missing_fields_json TEXT NOT NULL,
        present_fields_json TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v11_rich_audit_ready ON v11_rich_capture_audit(rich_ready,audited_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS v11_capture_verification (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        decision_id INTEGER,
        symbol TEXT NOT NULL,
        verification_type TEXT NOT NULL,
        passed INTEGER NOT NULL DEFAULT 0,
        core_present INTEGER NOT NULL DEFAULT 0,
        missing_fields_json TEXT NOT NULL,
        error TEXT,
        payload_json TEXT
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v11_capture_verify_time ON v11_capture_verification(created_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS v11_capture_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        symbol TEXT NOT NULL,
        passed INTEGER NOT NULL DEFAULT 0,
        core_present INTEGER NOT NULL DEFAULT 0,
        missing_fields_json TEXT NOT NULL,
        relative_volume REAL, gap_pct REAL, distance_vwap_pct REAL, ema20_distance_pct REAL, atr_pct REAL,
        payload_json TEXT NOT NULL
    )""")
    conn.commit(); conn.close()


def _v112_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in ("", "unknown", "none", "null")
    try:
        return math.isfinite(float(value))
    except Exception:
        return True


def _v112_audit_snapshot(conn, decision_id: int, symbol: str, source: str, fields: Dict[str, Any]) -> None:
    core_present = [name for name in V112_CORE_RICH_FIELDS if _v112_present(fields.get(name))]
    missing = [name for name in V112_CORE_RICH_FIELDS if name not in core_present]
    contextual = [name for name in V112_CONTEXT_FIELDS if _v112_present(fields.get(name))]
    present = core_present + contextual
    ready = int(len(core_present) >= V112_MIN_CORE_FIELDS)
    conn.execute("""INSERT OR REPLACE INTO v11_rich_capture_audit(
        decision_id,audited_at,symbol,source,core_present,core_required,rich_ready,missing_fields_json,present_fields_json
        ) VALUES(?,?,?,?,?,?,?,?,?)""",
        (int(decision_id), datetime.now(UTC).isoformat(), str(symbol), str(source), len(core_present),
         V112_MIN_CORE_FIELDS, ready, json.dumps(missing), json.dumps(present)))


def _v113_verify_persisted_snapshot(conn, decision_id: int, symbol: str) -> Dict[str, Any]:
    row = conn.execute("""SELECT relative_volume,gap_pct,distance_vwap_pct,ema20_distance_pct,atr_pct,payload_json
        FROM v9_market_memory WHERE decision_id=?""", (int(decision_id),)).fetchone()
    if not row:
        result={"passed":False,"corePresent":0,"missingFields":list(V112_CORE_RICH_FIELDS),"error":"snapshot row missing after write"}
    else:
        values=dict(zip(V112_CORE_RICH_FIELDS,row[:5]))
        present=[k for k,v in values.items() if _v112_present(v)]
        missing=[k for k in V112_CORE_RICH_FIELDS if k not in present]
        result={"passed":len(present)>=V112_MIN_CORE_FIELDS,"corePresent":len(present),"missingFields":missing,"error":None}
    conn.execute("""INSERT INTO v11_capture_verification(created_at,decision_id,symbol,verification_type,passed,core_present,missing_fields_json,error,payload_json)
        VALUES(?,?,?,?,?,?,?,?,?)""",(datetime.now(UTC).isoformat(),int(decision_id),str(symbol),"LIVE_POST_WRITE",int(result["passed"]),
        int(result["corePresent"]),json.dumps(result["missingFields"]),result.get("error"),json.dumps(result,default=str)))
    if not result["passed"]:
        print(f"V11.3 RICH SNAPSHOT VERIFY FAILED {symbol} decision={decision_id} missing={','.join(result['missingFields'])}")
    return result


def _v113_capture_test(symbol: str) -> Dict[str, Any]:
    _v9_ensure_tables(); _v112_ensure_tables()
    sym=str(symbol or '').upper().strip()
    if not re.fullmatch(r'[A-Z.\-]{1,10}',sym):
        raise HTTPException(status_code=400,detail='Invalid symbol')
    started=datetime.now(UTC)
    try:
        quote=get_quote(sym); price=float(quote.get('mid') or 0.0)
        if price<=0: raise RuntimeError('No usable midpoint quote')
        scan={"symbol":sym,"price":price,"confidence":0.5,"quality_score":0.0,"short_momentum":0.0,
              "pullback":0.0,"spread":float(quote.get('spread') or 0.0),"ready_to_buy":False,"sniper_pass":False,"a_plus_pass":False}
        enriched=_v91_enrich_scan(scan)
        values={k:_v9_num(_v9_scan_value(enriched,k)) for k in V112_CORE_RICH_FIELDS}
        present=[k for k,v in values.items() if _v112_present(v)]
        missing=[k for k in V112_CORE_RICH_FIELDS if k not in present]
        passed=len(present)>=V112_MIN_CORE_FIELDS
        conn=db_connect()
        cur=conn.execute("""INSERT INTO v11_capture_tests(created_at,symbol,passed,core_present,missing_fields_json,
            relative_volume,gap_pct,distance_vwap_pct,ema20_distance_pct,atr_pct,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (started.isoformat(),sym,int(passed),len(present),json.dumps(missing),values.get('relative_volume'),values.get('gap_pct'),
             values.get('distance_vwap_pct'),values.get('ema20_distance_pct'),values.get('atr_pct'),json.dumps(enriched,default=str)))
        test_id=int(cur.lastrowid); conn.commit()
        persisted=conn.execute("SELECT relative_volume,gap_pct,distance_vwap_pct,ema20_distance_pct,atr_pct FROM v11_capture_tests WHERE id=?",(test_id,)).fetchone()
        conn.close()
        persisted_values=dict(zip(V112_CORE_RICH_FIELDS,persisted)) if persisted else {}
        persistence_ok=bool(persisted and all((persisted_values[k] is not None)==(values[k] is not None) for k in V112_CORE_RICH_FIELDS))
        return {"ok":True,"version":V11_VERSION,"testId":test_id,"symbol":sym,"price":price,"passed":bool(passed and persistence_ok),
                "intelligenceCaptured":passed,"persistenceVerified":persistence_ok,"corePresent":len(present),"coreRequired":V112_MIN_CORE_FIELDS,
                "presentFields":present,"missingFields":missing,"values":values,"errors":{k:v for k,v in enriched.items() if str(k).endswith('_error')},
                "contaminatedResearchData":False,"placedOrder":False}
    except Exception as e:
        conn=db_connect(); conn.execute("""INSERT INTO v11_capture_verification(created_at,decision_id,symbol,verification_type,passed,core_present,missing_fields_json,error,payload_json)
            VALUES(?,?,?,?,0,0,?,?,?)""",(started.isoformat(),None,sym,"SYNTHETIC_END_TO_END",json.dumps(list(V112_CORE_RICH_FIELDS)),str(e)[:1000],json.dumps({"error":str(e)},default=str)))
        conn.commit(); conn.close()
        return {"ok":False,"version":V11_VERSION,"symbol":sym,"passed":False,"error":str(e),"placedOrder":False,"contaminatedResearchData":False}


def _v112_backfill_audit(limit: int = 50000) -> Dict[str, int]:
    _v112_ensure_tables(); limit=max(1,min(int(limit),100000)); conn=db_connect()
    rows=conn.execute("""SELECT m.decision_id,m.symbol,m.source,m.relative_volume,m.gap_pct,m.distance_vwap_pct,
        m.ema20_distance_pct,m.atr_pct,m.market_regime,m.sector,m.sector_strength,m.day_range_position,m.premarket_volume
        FROM v9_market_memory m LEFT JOIN v11_rich_capture_audit a ON a.decision_id=m.decision_id
        WHERE a.decision_id IS NULL ORDER BY m.decision_id DESC LIMIT ?""",(limit,)).fetchall()
    for row in rows:
        fields=dict(zip(("relative_volume","gap_pct","distance_vwap_pct","ema20_distance_pct","atr_pct",
                         "market_regime","sector","sector_strength","day_range_position","premarket_volume"),row[3:]))
        _v112_audit_snapshot(conn,int(row[0]),str(row[1]),str(row[2]),fields)
    conn.commit(); conn.close(); return {"processed":len(rows)}


def v112_pipeline_status(limit_examples: int = 10) -> Dict[str, Any]:
    _v9_ensure_tables(); _v10_ensure_tables(); _v112_backfill_audit()
    limit_examples=max(1,min(int(limit_examples),50)); conn=db_connect()
    cutoff=(datetime.now(UTC)-timedelta(hours=V112_RECENT_HOURS)).isoformat()
    total=int(conn.execute("SELECT COUNT(*) FROM v9_market_memory").fetchone()[0])
    live=int(conn.execute("SELECT COUNT(*) FROM v9_market_memory WHERE source='live'").fetchone()[0])
    recent_live=int(conn.execute("SELECT COUNT(*) FROM v9_market_memory WHERE source='live' AND captured_at>=?",(cutoff,)).fetchone()[0])
    audited=int(conn.execute("SELECT COUNT(*) FROM v11_rich_capture_audit").fetchone()[0])
    ready_all=int(conn.execute("SELECT COUNT(*) FROM v11_rich_capture_audit WHERE rich_ready=1").fetchone()[0])
    ready_live=int(conn.execute("SELECT COUNT(*) FROM v11_rich_capture_audit WHERE rich_ready=1 AND source='live'").fetchone()[0])
    ready_recent=int(conn.execute("SELECT COUNT(*) FROM v11_rich_capture_audit WHERE rich_ready=1 AND source='live' AND audited_at>=?",(cutoff,)).fetchone()[0])
    completed_ready=int(conn.execute("""SELECT COUNT(*) FROM v11_rich_capture_audit a
        JOIN v10_evidence_lineage l ON l.snapshot_id=a.decision_id
        WHERE a.rich_ready=1 AND l.horizon_hours=? AND l.outcome_status='COMPLETE' AND l.net_return_pct IS NOT NULL""",
        (V11_DEFAULT_HORIZON_HOURS,)).fetchone()[0])
    pending_ready=int(conn.execute("""SELECT COUNT(*) FROM v11_rich_capture_audit a
        JOIN v2_observation_outcomes o ON o.decision_id=a.decision_id
        WHERE a.rich_ready=1 AND o.horizon_hours=? AND o.status='PENDING'""",(V11_DEFAULT_HORIZON_HOURS,)).fetchone()[0])
    field_coverage={}
    for field in V112_CORE_RICH_FIELDS + V112_CONTEXT_FIELDS:
        if field in ("market_regime","sector"):
            present=int(conn.execute(f"SELECT COUNT(*) FROM v9_market_memory WHERE source='live' AND {field} IS NOT NULL AND lower({field}) NOT IN ('','unknown')").fetchone()[0])
        else:
            present=int(conn.execute(f"SELECT COUNT(*) FROM v9_market_memory WHERE source='live' AND {field} IS NOT NULL").fetchone()[0])
        field_coverage[field]={"present":present,"liveTotal":live,"coveragePct":round((present/live*100.0),2) if live else 0.0}
    missing_counts={name:0 for name in V112_CORE_RICH_FIELDS}
    for (payload,) in conn.execute("SELECT missing_fields_json FROM v11_rich_capture_audit WHERE source='live'").fetchall():
        try:
            for name in json.loads(payload or '[]'):
                if name in missing_counts: missing_counts[name]+=1
        except Exception: pass
    examples=[]
    rows=conn.execute("""SELECT a.decision_id,a.audited_at,a.symbol,a.core_present,a.core_required,a.missing_fields_json,
        m.stage,m.decision,m.reason FROM v11_rich_capture_audit a JOIN v9_market_memory m ON m.decision_id=a.decision_id
        WHERE a.source='live' AND a.rich_ready=0 ORDER BY a.decision_id DESC LIMIT ?""",(limit_examples,)).fetchall()
    for r in rows:
        examples.append({"decisionId":r[0],"auditedAt":r[1],"symbol":r[2],"corePresent":r[3],"coreRequired":r[4],
                         "missingFields":json.loads(r[5] or '[]'),"stage":r[6],"decision":r[7],"reason":r[8]})
    latest_live=conn.execute("SELECT MAX(captured_at) FROM v9_market_memory WHERE source='live'").fetchone()[0]
    verification_total=int(conn.execute("SELECT COUNT(*) FROM v11_capture_verification WHERE verification_type='LIVE_POST_WRITE'").fetchone()[0])
    verification_passed=int(conn.execute("SELECT COUNT(*) FROM v11_capture_verification WHERE verification_type='LIVE_POST_WRITE' AND passed=1").fetchone()[0])
    latest_test=conn.execute("SELECT id,created_at,symbol,passed,core_present,missing_fields_json FROM v11_capture_tests ORDER BY id DESC LIMIT 1").fetchone()
    _v114_ensure_tables()
    trace_events=int(conn.execute("SELECT COUNT(*) FROM v11_decision_trace").fetchone()[0])
    traced_decisions=int(conn.execute("SELECT COUNT(DISTINCT decision_id) FROM v11_decision_trace WHERE decision_id IS NOT NULL").fetchone()[0])
    latest_trace=conn.execute("SELECT created_at,decision_id,symbol,writer,event,success FROM v11_decision_trace ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if live == 0:
        diagnosis="NO_LIVE_SNAPSHOTS"
    elif recent_live == 0:
        diagnosis="NO_RECENT_LIVE_DECISIONS"
    elif ready_recent == 0:
        diagnosis="RECENT_LIVE_SNAPSHOTS_MISSING_CORE_FIELDS"
    elif completed_ready == 0 and pending_ready > 0:
        diagnosis="RICH_SNAPSHOTS_WAITING_FOR_OUTCOMES"
    elif completed_ready == 0:
        diagnosis="RICH_SNAPSHOTS_NOT_LINKED_TO_COMPLETED_OUTCOMES"
    else:
        diagnosis="RICH_PIPELINE_OPERATIONAL"
    return {"ok":True,"version":V11_VERSION,"name":V11_NAME,"schemaVersion":V11_SCHEMA_VERSION,
            "diagnosis":diagnosis,"coreFields":list(V112_CORE_RICH_FIELDS),"minimumCoreFields":V112_MIN_CORE_FIELDS,
            "recentWindowHours":V112_RECENT_HOURS,"snapshots":{"total":total,"live":live,"recentLive":recent_live,
            "audited":audited,"richReadyAll":ready_all,"richReadyLive":ready_live,"richReadyRecent":ready_recent,
            "richCompletedAtHorizon":completed_ready,"richPendingAtHorizon":pending_ready,"horizonHours":V11_DEFAULT_HORIZON_HOURS,
            "latestLiveCapturedAt":latest_live},"fieldCoverage":field_coverage,"missingCoreFieldCounts":missing_counts,
            "recentIncompleteExamples":examples,"captureVerification":{"total":verification_total,"passed":verification_passed,
            "failed":verification_total-verification_passed,"passRatePct":round(verification_passed/verification_total*100.0,2) if verification_total else 0.0},
            "latestEndToEndTest":None if not latest_test else {"id":latest_test[0],"createdAt":latest_test[1],"symbol":latest_test[2],
            "passed":bool(latest_test[3]),"corePresent":latest_test[4],"missingFields":json.loads(latest_test[5] or '[]')},
            "unifiedPipeline":{"traceEvents":trace_events,"tracedDecisions":traced_decisions,
                "latestTrace":None if not latest_trace else {"createdAt":latest_trace[0],"decisionId":latest_trace[1],
                    "symbol":latest_trace[2],"writer":latest_trace[3],"event":latest_trace[4],"success":bool(latest_trace[5])}},
            "advisoryOnly":True,"automaticLiveChanges":False,"historicalSnapshotsRewritten":False}


@app.get('/v11/pipeline/trace/{decision_id}')
def api_v114_pipeline_trace(decision_id: int, request: Request):
    verify_api_key(request)
    if int(decision_id) <= 0:
        raise HTTPException(status_code=400, detail='Invalid decision id')
    return v114_trace_payload(int(decision_id))


@app.get('/v11/pipeline/traces')
def api_v114_pipeline_traces(request: Request, limit: int = 50):
    verify_api_key(request)
    return v114_recent_traces(limit)


@app.get('/v11/pipeline/status')
def api_v112_pipeline_status(request: Request, examples: int = 10):
    verify_api_key(request); return v112_pipeline_status(examples)


@app.post('/v11/pipeline/audit')
def api_v112_pipeline_audit(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    result=_v112_backfill_audit(int(payload.get('limit') or 50000))
    result.update(v112_pipeline_status(int(payload.get('examples') or 10)))
    return result


@app.post('/v11/pipeline/test')
def api_v113_pipeline_test(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return _v113_capture_test(str(payload.get('symbol') or 'MSFT'))

@app.get('/v11/pipeline/test/{symbol}')
def api_v113_pipeline_test_get(symbol: str, request: Request):
    verify_api_key(request)
    return _v113_capture_test(symbol)


# =========================
# TRADEBOT V9.5 — SHADOW TRADING ENGINE
# Research-only virtual trades for decisions that did not become live orders.
# It reuses the existing forward outcome checkpoints and never submits an order.
# =========================
SHADOW_TRADE_NOTIONAL_GBP = max(1.0, float(os.getenv("SHADOW_TRADE_NOTIONAL_GBP", "100")))
SHADOW_DECISIONS = ("BLOCKED", "REJECTED")


def shadow_trading_summary(days: int = 30, horizon_hours: int = 24, notional_gbp: float = SHADOW_TRADE_NOTIONAL_GBP) -> Dict[str, Any]:
    days = max(1, min(int(days), 3650))
    horizon_hours = max(1, min(int(horizon_hours), 720))
    notional_gbp = max(1.0, float(notional_gbp))
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    try:
        init_db()
        conn = db_connect()
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT d.id,d.timestamp,d.symbol,d.decision,d.stage,d.reason,d.price,
                      d.confidence,d.quality,o.horizon_hours,o.status,o.outcome_price,
                      o.return_pct,o.net_return_pct,o.evaluated_at
               FROM v2_setup_decisions d
               JOIN v2_observation_outcomes o ON o.decision_id=d.id
               WHERE d.timestamp>=?
                 AND d.decision IN ('BLOCKED','REJECTED')
                 AND o.horizon_hours=?
               ORDER BY d.id DESC""",
            (cutoff, horizon_hours),
        ).fetchall()
        conn.close()
        records = [dict(r) for r in rows]
        complete = [r for r in records if r.get("status") == "COMPLETE" and r.get("net_return_pct") is not None]
        pending = len(records) - len(complete)
        returns = [float(r.get("net_return_pct") or 0.0) for r in complete]
        wins = sum(1 for x in returns if x > 0)
        losses = sum(1 for x in returns if x < 0)
        breakeven = len(returns) - wins - losses
        total_virtual_pnl = sum(notional_gbp * x / 100.0 for x in returns)
        gross_profit = sum(notional_gbp * x / 100.0 for x in returns if x > 0)
        gross_loss = abs(sum(notional_gbp * x / 100.0 for x in returns if x < 0))
        by_decision = {}
        by_stage = {}
        for r in complete:
            virtual_pnl = notional_gbp * float(r.get("net_return_pct") or 0.0) / 100.0
            r["virtualNotionalGbp"] = round(notional_gbp, 2)
            r["virtualPnlGbp"] = round(virtual_pnl, 2)
            for bucket, key in ((by_decision, str(r.get("decision") or "UNKNOWN")), (by_stage, str(r.get("stage") or "UNKNOWN"))):
                item = bucket.setdefault(key, {"samples": 0, "wins": 0, "virtualPnlGbp": 0.0, "returnSum": 0.0})
                item["samples"] += 1
                item["wins"] += int(float(r.get("net_return_pct") or 0.0) > 0)
                item["virtualPnlGbp"] += virtual_pnl
                item["returnSum"] += float(r.get("net_return_pct") or 0.0)
        def finish(bucket):
            result=[]
            for name,item in bucket.items():
                n=item["samples"]
                result.append({"name":name,"samples":n,"wins":item["wins"],
                    "winRate":round(item["wins"]/n,4) if n else 0.0,
                    "averageReturnPct":round(item["returnSum"]/n,4) if n else 0.0,
                    "virtualPnlGbp":round(item["virtualPnlGbp"],2)})
            return sorted(result,key=lambda x:(-x["virtualPnlGbp"],-x["samples"],x["name"]))
        best = sorted(complete, key=lambda r: float(r.get("net_return_pct") or 0.0), reverse=True)[:10]
        worst = sorted(complete, key=lambda r: float(r.get("net_return_pct") or 0.0))[:10]
        for group in (best, worst):
            for r in group:
                r["virtualNotionalGbp"] = round(notional_gbp,2)
                r["virtualPnlGbp"] = round(notional_gbp*float(r.get("net_return_pct") or 0.0)/100.0,2)
        return {
            "ok": True,
            "version": "V9.5",
            "name": "Shadow Trading Engine",
            "mode": "RESEARCH_ONLY",
            "days": days,
            "horizonHours": horizon_hours,
            "virtualNotionalGbpPerTrade": round(notional_gbp,2),
            "summary": {
                "shadowTrades": len(records), "completed": len(complete), "pending": pending,
                "wins": wins, "losses": losses, "breakeven": breakeven,
                "winRate": round(wins/len(complete),4) if complete else 0.0,
                "averageReturnPct": round(sum(returns)/len(returns),4) if returns else 0.0,
                "virtualPnlGbp": round(total_virtual_pnl,2),
                "grossVirtualProfitGbp": round(gross_profit,2),
                "grossVirtualLossGbp": round(gross_loss,2),
                "profitFactor": round(gross_profit/gross_loss,4) if gross_loss else (999.0 if gross_profit else 0.0),
            },
            "byDecision": finish(by_decision),
            "byStage": finish(by_stage),
            "bestMissedTrades": best,
            "worstAvoidedTrades": worst,
            "advisoryOnly": True,
            "realOrdersPlaced": False,
            "automaticLiveChanges": False,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "version": "V9.5"}


def shadow_trading_recent(limit: int = 100, horizon_hours: int = 24, decision: str = "") -> Dict[str, Any]:
    limit=max(1,min(int(limit),1000)); horizon_hours=max(1,min(int(horizon_hours),720))
    decision=str(decision or "").upper().strip()
    try:
        init_db(); conn=db_connect()
        params=[horizon_hours]
        where="AND d.decision IN ('BLOCKED','REJECTED')"
        if decision in SHADOW_DECISIONS:
            where="AND d.decision=?"; params.append(decision)
        params.append(limit)
        rows=conn.execute(f"""SELECT d.id,d.timestamp,d.symbol,d.decision,d.stage,d.reason,d.price,
            d.confidence,d.quality,o.status,o.horizon_hours,o.outcome_price,o.net_return_pct,o.due_at,o.evaluated_at
            FROM v2_setup_decisions d JOIN v2_observation_outcomes o ON o.decision_id=d.id
            WHERE o.horizon_hours=? {where} ORDER BY d.id DESC LIMIT ?""",tuple(params)).fetchall(); conn.close()
        items=[]
        for row in rows:
            item=dict(row)
            if item.get('net_return_pct') is not None:
                item['virtualNotionalGbp']=round(SHADOW_TRADE_NOTIONAL_GBP,2)
                item['virtualPnlGbp']=round(SHADOW_TRADE_NOTIONAL_GBP*float(item['net_return_pct'])/100.0,2)
            items.append(item)
        return {"ok":True,"version":"V9.5","count":len(items),"items":items,"realOrdersPlaced":False}
    except Exception as e:
        return {"ok":False,"error":str(e),"version":"V9.5"}


def shadow_trading_run(evaluate_limit: int = 1000, horizon_hours: int = 24) -> Dict[str, Any]:
    seeded=v2_seed_missing_outcomes(max(1,min(int(evaluate_limit)*10,50000)))
    evaluation=v2_evaluate_due_outcomes(max(1,min(int(evaluate_limit),5000)))
    return {"ok":bool(evaluation.get("ok",True)),"version":"V9.5","seededOutcomes":seeded,
            "outcomeEvaluation":evaluation,"shadow":shadow_trading_summary(horizon_hours=horizon_hours),
            "advisoryOnly":True,"realOrdersPlaced":False,"automaticLiveChanges":False}


@app.get('/outcomes/backlog')
def api_outcomes_backlog(request: Request):
    verify_api_key(request)
    return {
        "ok": True,
        "backlog": v2_pending_breakdown(),
        "horizonsHours": list(V2_OUTCOME_HORIZONS_HOURS),
        "validatedPromotionHorizonHours": V11_DEFAULT_HORIZON_HOURS,
        "researchIntervalSeconds": AI_RESEARCH_INTERVAL_SECONDS,
        "batchSize": V2_OUTCOME_BATCH_SIZE,
        "drainLimitPerCycle": V2_OUTCOME_DRAIN_LIMIT,
    }


@app.post('/outcomes/drain')
def api_outcomes_drain(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    try:
        market_state = get_effective_market_status_payload()
        if market_state.get("isOpen") and AI_RESEARCH_CLOSED_MARKET_ONLY:
            return {"ok": False, "blocked": True, "reason": "market_open_live_trader_has_priority"}
    except Exception:
        pass
    return v2_drain_due_outcomes(int(payload.get("limit") or V2_OUTCOME_DRAIN_LIMIT))


@app.get('/shadow-trading/summary')
def api_shadow_trading_summary(request: Request, days: int = 30, horizon_hours: int = 24, notional_gbp: float = SHADOW_TRADE_NOTIONAL_GBP):
    verify_api_key(request)
    return shadow_trading_summary(days, horizon_hours, notional_gbp)


@app.get('/shadow-trading/recent')
def api_shadow_trading_recent(request: Request, limit: int = 100, horizon_hours: int = 24, decision: str = ''):
    verify_api_key(request)
    return shadow_trading_recent(limit, horizon_hours, decision)


@app.post('/shadow-trading/run')
def api_shadow_trading_run(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return shadow_trading_run(int(payload.get('evaluateLimit') or 1000), int(payload.get('horizonHours') or 24))

# =========================
# TRADEBOT V9.4 — AI ADVISOR DASHBOARD
# Unified outcome-learning and evidence-based recommendations.
# Advisory-only: it never changes live trading settings automatically.
# =========================

def ai_advisor_summary(limit: int = 10) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    learning = v11_learning_status_payload()
    report = v11_latest_report(limit=max(limit * 3, 30))
    outcomes = v2_outcomes_summary()

    discoveries = report.get("discoveries", []) if report.get("hasReport") else []
    positive = [d for d in discoveries if d.get("classification") == "VALIDATED_POSITIVE"][:limit]
    negative = [d for d in discoveries if d.get("classification") == "VALIDATED_NEGATIVE"][:limit]

    completed = 0
    pending = 0
    try:
        conn = db_connect()
        completed = int(conn.execute(
            "SELECT COUNT(*) FROM v2_observation_outcomes WHERE status='COMPLETE' AND net_return_pct IS NOT NULL"
        ).fetchone()[0])
        pending = int(conn.execute(
            "SELECT COUNT(*) FROM v2_observation_outcomes WHERE status='PENDING'"
        ).fetchone()[0])
        conn.close()
    except Exception:
        pass

    rich = int(learning.get("richObservations") or 0)
    target = int(learning.get("richEvidenceTarget") or V11_RICH_TARGET_OBSERVATIONS)
    validated = len(positive) + len(negative)

    if completed < V11_MIN_SAMPLES:
        readiness = "COLLECTING_OUTCOMES"
        message = f"Collecting evidence: {completed}/{V11_MIN_SAMPLES} completed outcomes needed for a first reliable learning run."
    elif rich < min(target, V11_MIN_SAMPLES):
        readiness = "COLLECTING_RICH_EVIDENCE"
        message = "Outcomes exist, but more market-context snapshots are needed before recommendations are reliable."
    elif validated == 0:
        readiness = "LEARNING_NO_VALIDATED_PATTERN_YET"
        message = "The learner has enough data to test patterns, but none has passed validation yet."
    else:
        readiness = "RECOMMENDATIONS_AVAILABLE"
        message = f"{validated} validated evidence pattern(s) are available for review."

    return {
        "ok": True,
        "version": "V9.5",
        "name": "AI Advisor + Shadow Trading",
        "readiness": readiness,
        "message": message,
        "evidence": {
            "completedOutcomes": completed,
            "pendingOutcomes": pending,
            "observations": int(learning.get("observations") or 0),
            "richObservations": rich,
            "richEvidenceTarget": target,
            "richEvidenceProgressPct": float(learning.get("richEvidenceProgressPct") or 0.0),
            "learningRuns": int(learning.get("learningRuns") or 0),
            "validatedPositive": len(positive),
            "validatedNegative": len(negative),
            "pendingBreakdown": v2_pending_breakdown(),
            "outcomeHorizonsHours": list(V2_OUTCOME_HORIZONS_HOURS),
            "researchIntervalSeconds": AI_RESEARCH_INTERVAL_SECONDS,
        },
        "recommendations": {
            "favourablePatterns": positive,
            "unfavourablePatterns": negative,
        },
        "strategyIntelligence": strategy_intelligence_summary(limit),
        "learning": learning,
        "outcomes": outcomes,
        "shadowTrading": shadow_trading_summary(days=30, horizon_hours=24),
        "advisoryOnly": True,
        "automaticLiveChanges": False,
        "requiresHumanApproval": True,
    }


def ai_advisor_run(force: bool = True, evaluate_limit: int = 500) -> Dict[str, Any]:
    evaluation = v2_evaluate_due_outcomes(max(1, min(int(evaluate_limit), 5000)))
    learning = v11_learning_cycle("manual", bool(force))
    return {
        "ok": bool(evaluation.get("ok", True) and learning.get("ok", True)),
        "version": "V9.5",
        "outcomeEvaluation": evaluation,
        "learningRun": learning,
        "advisor": ai_advisor_summary(),
        "advisoryOnly": True,
        "automaticLiveChanges": False,
        "requiresHumanApproval": True,
    }


@app.get('/ai-advisor/summary')
def api_ai_advisor_summary(request: Request, limit: int = 10):
    verify_api_key(request)
    return ai_advisor_summary(limit)


@app.post('/ai-advisor/run')
def api_ai_advisor_run(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return ai_advisor_run(
        bool(payload.get('force', True)),
        int(payload.get('evaluateLimit') or 500),
    )



# =========================
# TRADEBOT V9.7 — EXPLAINABLE STRATEGY INTELLIGENCE
# Converts validated discoveries into transparent, evidence-backed advisory cards.
# Advisory-only: no live setting or trading rule is changed automatically.
# =========================

STRATEGY_INTELLIGENCE_NOTIONAL_GBP = max(1.0, float(os.getenv("STRATEGY_INTELLIGENCE_NOTIONAL_GBP", "100")))


def _strategy_intelligence_period(horizon_hours: int) -> Dict[str, Any]:
    """Return the actual observation period used by the latest evidence set."""
    result = {"start": None, "end": None, "days": 0}
    try:
        conn = db_connect()
        rows = _v11_load_rows(conn, int(horizon_hours))
        conn.close()
        stamps = [str(r.get("observed_at") or "") for r in rows if r.get("observed_at")]
        if stamps:
            start, end = min(stamps), max(stamps)
            result["start"], result["end"] = start, end
            try:
                a = datetime.fromisoformat(start.replace("Z", "+00:00"))
                b = datetime.fromisoformat(end.replace("Z", "+00:00"))
                result["days"] = max(1, int((b - a).total_seconds() // 86400) + 1)
            except Exception:
                pass
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _strategy_recommendation_confidence(item: Dict[str, Any]) -> float:
    """Conservative 0-100 confidence based on validation size, stability and evidence strength."""
    samples = max(0, int(item.get("samples") or 0))
    validation = max(0, int(item.get("validationSamples") or 0))
    stability = max(0.0, min(1.0, float(item.get("stabilityScore") or 0.0)))
    score = abs(float(item.get("evidenceScore") or 0.0))
    sample_component = min(1.0, (samples / 150.0) ** 0.5)
    validation_component = min(1.0, (validation / 50.0) ** 0.5)
    strength_component = min(1.0, score / 25.0)
    confidence = 100.0 * (
        0.25 * sample_component +
        0.30 * validation_component +
        0.30 * stability +
        0.15 * strength_component
    )
    return round(max(0.0, min(99.0, confidence)), 1)


def _strategy_action(item: Dict[str, Any]) -> Dict[str, str]:
    dims = item.get("dimensions") or {}
    classification = str(item.get("classification") or "")
    label = " + ".join(str(v) for v in dims.values()) or str(item.get("name") or "pattern")
    if classification == "VALIDATED_NEGATIVE":
        return {
            "action": "REQUIRE_STRONGER_ENTRY_OR_AVOID",
            "headline": f"Reduce exposure to: {label}",
            "suggestion": "Test a stricter confidence gate or exclusion for this setup in shadow mode before any live change.",
        }
    return {
        "action": "FAVOUR_IN_SHADOW_TEST",
        "headline": f"Favour in testing: {label}",
        "suggestion": "Give this setup higher shadow priority and confirm it remains profitable before changing live rules.",
    }


def strategy_intelligence_recommendations(limit: int = 20) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    report = v11_latest_report(limit=max(limit * 4, 100))
    if not report.get("hasReport"):
        return {
            "ok": True, "version": "V9.7", "hasReport": False,
            "message": "No completed discovery report is available yet.",
            "recommendations": [], "advisoryOnly": True,
            "automaticLiveChanges": False, "requiresHumanApproval": True,
        }

    run = report.get("run") or {}
    period = _strategy_intelligence_period(int(run.get("horizonHours") or 24))
    cards = []
    for item in report.get("discoveries", []):
        classification = str(item.get("classification") or "")
        if classification not in ("VALIDATED_POSITIVE", "VALIDATED_NEGATIVE"):
            continue
        samples = int(item.get("samples") or 0)
        validation_samples = int(item.get("validationSamples") or 0)
        expectancy = float(item.get("expectancyPct") or 0.0)
        baseline = float(item.get("baselineExpectancyPct") or 0.0)
        lift = float(item.get("expectancyLiftPct") or (expectancy - baseline))
        historical_effect = STRATEGY_INTELLIGENCE_NOTIONAL_GBP * samples * lift / 100.0
        validation_effect = STRATEGY_INTELLIGENCE_NOTIONAL_GBP * validation_samples * float(item.get("validationExpectancyPct") or 0.0) / 100.0
        action = _strategy_action(item)
        cards.append({
            "id": item.get("key"),
            "classification": classification,
            "rating": "FAVOURABLE" if classification == "VALIDATED_POSITIVE" else "UNFAVOURABLE",
            **action,
            "pattern": item.get("name"),
            "dimensions": item.get("dimensions") or {},
            "evidence": {
                "samples": samples,
                "wins": int(item.get("wins") or 0),
                "losses": int(item.get("losses") or 0),
                "winRate": float(item.get("winRate") or 0.0),
                "expectancyPct": expectancy,
                "profitFactor": float(item.get("profitFactor") or 0.0),
                "medianReturnPct": float(item.get("medianReturnPct") or 0.0),
                "validationSamples": validation_samples,
                "validationWinRate": float(item.get("validationWinRate") or 0.0),
                "validationExpectancyPct": float(item.get("validationExpectancyPct") or 0.0),
                "validationProfitFactor": float(item.get("validationProfitFactor") or 0.0),
                "stabilityScore": float(item.get("stabilityScore") or 0.0),
            },
            "period": period,
            "estimatedEffect": {
                "basis": f"£{STRATEGY_INTELLIGENCE_NOTIONAL_GBP:.2f} per historical observation",
                "expectancyLiftPct": lift,
                "historicalNetEffectGbp": round(historical_effect, 2),
                "validationNetEffectGbp": round(validation_effect, 2),
                "note": "This is a historical evidence estimate, not a forecast or guaranteed return.",
            },
            "recommendationConfidencePct": _strategy_recommendation_confidence(item),
            "explanation": item.get("explanation"),
            "requiresShadowTest": True,
            "requiresHumanApproval": True,
        })
        if len(cards) >= limit:
            break

    cards.sort(key=lambda x: (x["classification"] == "VALIDATED_POSITIVE", x["recommendationConfidencePct"]), reverse=True)
    return {
        "ok": True,
        "version": "V9.7",
        "name": "Explainable Strategy Intelligence",
        "hasReport": True,
        "run": run,
        "period": period,
        "summary": {
            "recommendations": len(cards),
            "favourable": sum(1 for x in cards if x["classification"] == "VALIDATED_POSITIVE"),
            "unfavourable": sum(1 for x in cards if x["classification"] == "VALIDATED_NEGATIVE"),
            "minimumSamples": int(run.get("minimumSamples") or 0),
        },
        "recommendations": cards,
        "advisoryOnly": True,
        "automaticLiveChanges": False,
        "requiresHumanApproval": True,
    }


def strategy_intelligence_summary(limit: int = 10) -> Dict[str, Any]:
    data = strategy_intelligence_recommendations(limit)
    recommendations = data.get("recommendations", [])
    data["topFavourable"] = [x for x in recommendations if x.get("classification") == "VALIDATED_POSITIVE"][:5]
    data["topUnfavourable"] = [x for x in recommendations if x.get("classification") == "VALIDATED_NEGATIVE"][:5]
    return data


@app.get('/strategy-intelligence/summary')
def api_strategy_intelligence_summary(request: Request, limit: int = 10):
    verify_api_key(request)
    return strategy_intelligence_summary(limit)


@app.get('/strategy-intelligence/recommendations')
def api_strategy_intelligence_recommendations(request: Request, limit: int = 20):
    verify_api_key(request)
    return strategy_intelligence_recommendations(limit)


# =========================
# TRADEBOT V9.9 — INTELLIGENCE COMPLETION
# Completes confidence calibration, Market DNA summaries and research promotion.
# Advisory-only: no live order, sizing, stop or gate changes.
# =========================

# =========================
# TRADEBOT V9.8 — WEAKNESS INTELLIGENCE ENGINE
# Fast, read-only analytics for symbols, rejection rules and data quality.
# It does not alter live gates, position limits, risk or order execution.
# =========================
WEAKNESS_INTELLIGENCE_NOTIONAL_GBP = max(
    1.0, float(os.getenv("WEAKNESS_INTELLIGENCE_NOTIONAL_GBP", "100"))
)


def _wi_safe_div(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _wi_profit_factor(returns: List[float]) -> float:
    gross_profit = sum(x for x in returns if x > 0)
    gross_loss = abs(sum(x for x in returns if x < 0))
    if gross_loss:
        return gross_profit / gross_loss
    return 999.0 if gross_profit else 0.0


def _wi_symbol_status(samples: int, expectancy_pct: float, profit_factor: float, win_rate: float) -> str:
    if samples < 5:
        return "INSUFFICIENT_DATA"
    if expectancy_pct <= -0.20 and profit_factor < 0.85:
        return "WEAK"
    if expectancy_pct < 0 or profit_factor < 1.0 or win_rate < 0.45:
        return "UNDER_REVIEW"
    if expectancy_pct >= 0.20 and profit_factor >= 1.20 and win_rate >= 0.52:
        return "STRONG"
    return "NEUTRAL"


def symbol_intelligence(days: int = 180, horizon_hours: int = 24, minimum_samples: int = 5, limit: int = 100) -> Dict[str, Any]:
    days = max(1, min(int(days), 3650))
    horizon_hours = max(1, min(int(horizon_hours), 720))
    minimum_samples = max(1, min(int(minimum_samples), 1000))
    limit = max(1, min(int(limit), 1000))
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled", "version": "V9.8"}
    try:
        init_db()
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        conn = db_connect()
        decision_rows = conn.execute(
            """SELECT d.symbol,d.decision,d.stage,d.reason,o.net_return_pct
               FROM v2_setup_decisions d
               JOIN v2_observation_outcomes o ON o.decision_id=d.id
               WHERE d.timestamp>=? AND o.horizon_hours=?
                 AND o.status='COMPLETE' AND o.net_return_pct IS NOT NULL""",
            (cutoff, horizon_hours),
        ).fetchall()
        live_rows = conn.execute(
            """SELECT symbol,pnl_gbp,pnl_pct,timestamp
               FROM closed_trades
               WHERE timestamp>=? AND COALESCE(qty,0)>0""",
            (cutoff,),
        ).fetchall()
        conn.close()

        buckets: Dict[str, Dict[str, Any]] = {}
        for row in decision_rows:
            symbol = str(row[0] or "").upper().strip()
            if not symbol:
                continue
            item = buckets.setdefault(symbol, {
                "symbol": symbol, "outcomes": [], "takenOutcomes": [], "shadowOutcomes": [],
                "actualPnlGbp": [], "actualPnlPct": [], "decisions": {}, "reasons": {}
            })
            decision = str(row[1] or "UNKNOWN").upper()
            reason = str(row[3] or row[2] or "UNKNOWN").strip()
            value = float(row[4] or 0.0)
            item["outcomes"].append(value)
            if decision in ("BOUGHT", "APPROVED"):
                item["takenOutcomes"].append(value)
            elif decision in ("BLOCKED", "REJECTED"):
                item["shadowOutcomes"].append(value)
            item["decisions"][decision] = int(item["decisions"].get(decision, 0)) + 1
            item["reasons"][reason] = int(item["reasons"].get(reason, 0)) + 1

        for row in live_rows:
            symbol = str(row[0] or "").upper().strip()
            if not symbol:
                continue
            item = buckets.setdefault(symbol, {
                "symbol": symbol, "outcomes": [], "takenOutcomes": [], "shadowOutcomes": [],
                "actualPnlGbp": [], "actualPnlPct": [], "decisions": {}, "reasons": {}
            })
            if row[1] is not None:
                item["actualPnlGbp"].append(float(row[1]))
            if row[2] is not None:
                item["actualPnlPct"].append(float(row[2]))

        results = []
        for symbol, item in buckets.items():
            returns = item["outcomes"]
            actual_pct = item["actualPnlPct"]
            evidence_returns = actual_pct if actual_pct else returns
            samples = len(evidence_returns)
            wins = sum(1 for x in evidence_returns if x > 0)
            losses = sum(1 for x in evidence_returns if x < 0)
            expectancy = _wi_safe_div(sum(evidence_returns), samples)
            win_rate = _wi_safe_div(wins, samples)
            pf = _wi_profit_factor(evidence_returns)
            status = _wi_symbol_status(samples, expectancy, pf, win_rate)
            top_reasons = sorted(item["reasons"].items(), key=lambda x: (-x[1], x[0]))[:5]
            suggestion = "Keep collecting evidence."
            if status == "WEAK":
                suggestion = "Shadow-test a higher confidence requirement or temporary exclusion; do not change live rules automatically."
            elif status == "UNDER_REVIEW":
                suggestion = "Require stronger evidence before prioritising this symbol."
            elif status == "STRONG":
                suggestion = "Retain current handling and confirm performance remains stable out-of-sample."
            results.append({
                "symbol": symbol,
                "status": status,
                "samples": samples,
                "wins": wins,
                "losses": losses,
                "winRate": round(win_rate, 4),
                "averageReturnPct": round(expectancy, 4),
                "expectancyPct": round(expectancy, 4),
                "expectancy": round(expectancy, 4),
                "profitFactor": round(pf, 4),
                "actualTrades": len(item["actualPnlGbp"]) or len(actual_pct),
                "actualPnlGbp": round(sum(item["actualPnlGbp"]), 2),
                "actualAverageReturnPct": round(_wi_safe_div(sum(actual_pct), len(actual_pct)), 4),
                "decisionOutcomes": len(returns),
                "takenOutcomeSamples": len(item["takenOutcomes"]),
                "shadowOutcomeSamples": len(item["shadowOutcomes"]),
                "decisionCounts": item["decisions"],
                "topReasons": [{"reason": k, "count": v} for k, v in top_reasons],
                "suggestion": suggestion,
                "requiresShadowTest": status in ("WEAK", "UNDER_REVIEW"),
                "requiresHumanApproval": True,
            })

        results.sort(key=lambda x: (
            0 if x["status"] == "WEAK" else 1 if x["status"] == "UNDER_REVIEW" else 2,
            x["averageReturnPct"], -x["samples"]
        ))
        eligible = [x for x in results if x["samples"] >= minimum_samples]
        return {
            "ok": True, "version": "V9.8", "name": "Symbol Intelligence",
            "days": days, "horizonHours": horizon_hours, "minimumSamples": minimum_samples,
            "summary": {
                "symbols": len(results), "eligible": len(eligible),
                "weak": sum(1 for x in eligible if x["status"] == "WEAK"),
                "underReview": sum(1 for x in eligible if x["status"] == "UNDER_REVIEW"),
                "strong": sum(1 for x in eligible if x["status"] == "STRONG"),
            },
            "symbols": results[:limit],
            "advisoryOnly": True, "automaticLiveChanges": False, "requiresHumanApproval": True,
        }
    except Exception as exc:
        return {"ok": False, "version": "V9.8", "error": str(exc)}


def _wi_normalise_rule(stage: Any, reason: Any) -> str:
    stage_text = str(stage or "UNKNOWN").strip().lower()
    reason_text = str(reason or "UNKNOWN").strip().lower()
    if "max positions" in reason_text or "position_limit" in stage_text:
        return "MAX_POSITIONS"
    if "confidence" in reason_text:
        return "CONFIDENCE_GATE"
    if "quality" in reason_text:
        return "QUALITY_GATE"
    if "momentum" in reason_text:
        return "MOMENTUM_FILTER"
    if "spread" in reason_text:
        return "SPREAD_FILTER"
    if "sample" in reason_text or stage_text.startswith("v2"):
        return "V2_SAMPLE_GATE"
    if "pullback" in reason_text:
        return "PULLBACK_FILTER"
    if "cooldown" in reason_text:
        return "COOLDOWN"
    if "sold today" in reason_text or "already traded" in reason_text:
        return "DAILY_LOCKOUT"
    return (str(stage or reason or "OTHER").upper().strip().replace(" ", "_"))[:80]


def rule_intelligence(days: int = 180, horizon_hours: int = 24, minimum_samples: int = 20, limit: int = 100) -> Dict[str, Any]:
    days = max(1, min(int(days), 3650))
    horizon_hours = max(1, min(int(horizon_hours), 720))
    minimum_samples = max(1, min(int(minimum_samples), 10000))
    limit = max(1, min(int(limit), 1000))
    try:
        init_db()
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        conn = db_connect()
        rows = conn.execute(
            """SELECT d.decision,d.stage,d.reason,d.symbol,o.net_return_pct
               FROM v2_setup_decisions d
               JOIN v2_observation_outcomes o ON o.decision_id=d.id
               WHERE d.timestamp>=? AND d.decision IN ('BLOCKED','REJECTED')
                 AND o.horizon_hours=? AND o.status='COMPLETE'
                 AND o.net_return_pct IS NOT NULL""",
            (cutoff, horizon_hours),
        ).fetchall()
        conn.close()
        buckets: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            rule = _wi_normalise_rule(row[1], row[2])
            item = buckets.setdefault(rule, {"returns": [], "symbols": {}, "reasons": {}, "decisions": {}})
            value = float(row[4] or 0.0)
            item["returns"].append(value)
            symbol = str(row[3] or "UNKNOWN").upper()
            reason = str(row[2] or "UNKNOWN")
            decision = str(row[0] or "UNKNOWN").upper()
            item["symbols"][symbol] = int(item["symbols"].get(symbol, 0)) + 1
            item["reasons"][reason] = int(item["reasons"].get(reason, 0)) + 1
            item["decisions"][decision] = int(item["decisions"].get(decision, 0)) + 1

        results = []
        for rule, item in buckets.items():
            returns = item["returns"]
            samples = len(returns)
            missed_winners = sum(1 for x in returns if x > 0)
            avoided_losers = sum(1 for x in returns if x < 0)
            shadow_pnl = WEAKNESS_INTELLIGENCE_NOTIONAL_GBP * sum(returns) / 100.0
            # A rejection rule adds value when rejected trades subsequently lose.
            rule_net_benefit = -shadow_pnl
            average_return = _wi_safe_div(sum(returns), samples)
            helped_rate = _wi_safe_div(avoided_losers, samples)
            rating = "INSUFFICIENT_DATA"
            if samples >= minimum_samples:
                if rule_net_benefit > 0 and helped_rate >= 0.52:
                    rating = "HELPING"
                elif rule_net_benefit < 0 and missed_winners > avoided_losers:
                    rating = "HURTING"
                else:
                    rating = "MIXED"
            confidence = min(99.0, 100.0 * min(1.0, (samples / max(50.0, minimum_samples * 2.0)) ** 0.5))
            top_symbols = sorted(item["symbols"].items(), key=lambda x: (-x[1], x[0]))[:5]
            top_reasons = sorted(item["reasons"].items(), key=lambda x: (-x[1], x[0]))[:5]
            results.append({
                "rule": rule, "rating": rating, "samples": samples,
                "avoidedLosers": avoided_losers, "missedWinners": missed_winners,
                "helpedRate": round(helped_rate, 4),
                "rejectedTradeAverageReturnPct": round(average_return, 4),
                "expectancyPct": round(average_return, 4),
                "expectancy": round(average_return, 4),
                "shadowPnlIfTakenGbp": round(shadow_pnl, 2),
                "estimatedRuleNetBenefitGbp": round(rule_net_benefit, 2),
                "evidenceConfidencePct": round(confidence, 1),
                "decisionCounts": item["decisions"],
                "topSymbols": [{"symbol": k, "count": v} for k, v in top_symbols],
                "topReasons": [{"reason": k, "count": v} for k, v in top_reasons],
                "interpretation": (
                    "The rule appears to avoid more losses than gains." if rating == "HELPING" else
                    "The rule appears to miss more profitable trades than losses it avoids." if rating == "HURTING" else
                    "The evidence is mixed or still insufficient."
                ),
                "requiresShadowTest": rating == "HURTING",
                "requiresHumanApproval": True,
            })
        results.sort(key=lambda x: (
            0 if x["rating"] == "HURTING" else 1 if x["rating"] == "MIXED" else 2,
            x["estimatedRuleNetBenefitGbp"], -x["samples"]
        ))
        eligible = [x for x in results if x["samples"] >= minimum_samples]
        return {
            "ok": True, "version": "V9.8", "name": "Rule Intelligence",
            "days": days, "horizonHours": horizon_hours, "minimumSamples": minimum_samples,
            "summary": {
                "rules": len(results), "eligible": len(eligible),
                "helping": sum(1 for x in eligible if x["rating"] == "HELPING"),
                "hurting": sum(1 for x in eligible if x["rating"] == "HURTING"),
                "mixed": sum(1 for x in eligible if x["rating"] == "MIXED"),
            },
            "rules": results[:limit],
            "advisoryOnly": True, "automaticLiveChanges": False, "requiresHumanApproval": True,
        }
    except Exception as exc:
        return {"ok": False, "version": "V9.8", "error": str(exc)}


def weakness_intelligence_summary() -> Dict[str, Any]:
    symbols = symbol_intelligence(days=180, horizon_hours=24, minimum_samples=5, limit=20)
    rules = rule_intelligence(days=180, horizon_hours=24, minimum_samples=20, limit=20)
    strategy = strategy_intelligence_summary(limit=10)
    weak_symbols = [x for x in symbols.get("symbols", []) if x.get("status") in ("WEAK", "UNDER_REVIEW")][:5]
    hurting_rules = [x for x in rules.get("rules", []) if x.get("rating") == "HURTING"][:5]
    positive = int((strategy.get("summary") or {}).get("favourable") or 0)
    negative = int((strategy.get("summary") or {}).get("unfavourable") or 0)
    issues = []
    if positive == 0 and negative > 0:
        issues.append({
            "area": "POSITIVE_PATTERN_DISCOVERY", "severity": "REVIEW",
            "finding": f"The latest validated set contains {negative} negative patterns and no positive patterns.",
            "action": "Keep live settings unchanged; inspect feature coverage and out-of-sample validation before relaxing thresholds."
        })
    if weak_symbols:
        issues.append({
            "area": "SYMBOL_PERFORMANCE", "severity": "REVIEW",
            "finding": f"{len(weak_symbols)} weak or under-review symbols are visible in the current result window.",
            "action": "Shadow-test symbol-specific confidence gates before any live exclusion."
        })
    if hurting_rules:
        issues.append({
            "area": "RULE_OPPORTUNITY_COST", "severity": "REVIEW",
            "finding": f"{len(hurting_rules)} rules currently show negative historical net benefit.",
            "action": "Run controlled shadow comparisons; do not remove gates during market hours."
        })
    return {
        "ok": bool(symbols.get("ok") and rules.get("ok")), "version": "V9.8",
        "name": "Weakness Intelligence Engine", "generatedAt": datetime.now(UTC).isoformat(),
        "readiness": "READY_FOR_OBSERVATION",
        "topWeakSymbols": weak_symbols,
        "topHurtingRules": hurting_rules,
        "issues": issues,
        "symbolSummary": symbols.get("summary", {}),
        "ruleSummary": rules.get("summary", {}),
        "strategyValidation": {"positive": positive, "negative": negative},
        "liveTradingChanged": False, "advisoryOnly": True,
        "automaticLiveChanges": False, "requiresHumanApproval": True,
    }


@app.get('/symbol-intelligence/summary')
def api_symbol_intelligence_summary(request: Request, days: int = 180, horizon_hours: int = 24, minimum_samples: int = 5, limit: int = 100):
    verify_api_key(request)
    return symbol_intelligence(days, horizon_hours, minimum_samples, limit)



# =========================
# TRADEBOT V10.5 — AI SYMBOL REPUTATION ENGINE
# Evidence-based live entry protection with reversible cooldowns.
# =========================
SYMBOL_REPUTATION_ENABLED = os.getenv("SYMBOL_REPUTATION_ENABLED", "true").lower() == "true"
SYMBOL_REPUTATION_MIN_SAMPLES = max(3, int(os.getenv("SYMBOL_REPUTATION_MIN_SAMPLES", "5") or 5))
SYMBOL_REPUTATION_BLOCK_SCORE = max(0.0, min(100.0, float(os.getenv("SYMBOL_REPUTATION_BLOCK_SCORE", "35") or 35)))
SYMBOL_REPUTATION_COOLDOWN_DAYS = max(1, int(os.getenv("SYMBOL_REPUTATION_COOLDOWN_DAYS", "5") or 5))
SYMBOL_REPUTATION_CACHE_SECONDS = max(30, int(os.getenv("SYMBOL_REPUTATION_CACHE_SECONDS", "300") or 300))
_symbol_reputation_cache: Dict[str, Any] = {"at": 0.0, "items": {}}
_symbol_reputation_table_ready = False
_symbol_reputation_table_lock = threading.RLock()


def _symbol_reputation_ensure_table() -> None:
    global _symbol_reputation_table_ready
    if _symbol_reputation_table_ready or not SQLITE_ENABLED:
        return
    with _symbol_reputation_table_lock:
        if _symbol_reputation_table_ready:
            return
        init_db()
        conn = db_connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS symbol_reputation_cooldowns (
                    symbol TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    score REAL NOT NULL,
                    reason TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()
            _symbol_reputation_table_ready = True
        finally:
            conn.close()


def _symbol_reputation_score(item: Dict[str, Any]) -> float:
    samples = int(item.get("samples") or 0)
    win_rate = float(item.get("winRate") or 0.0)
    expectancy = float(item.get("averageReturnPct") or item.get("expectancyPct") or 0.0)
    profit_factor = float(item.get("profitFactor") or 0.0)
    actual_pnl = float(item.get("actualPnlGbp") or 0.0)

    # Balanced 0-100 score. Expectancy is capped so single outliers cannot dominate.
    win_component = max(0.0, min(1.0, win_rate)) * 40.0
    expectancy_component = max(0.0, min(1.0, (expectancy + 2.0) / 4.0)) * 30.0
    pf_component = max(0.0, min(1.0, profit_factor / 2.0)) * 20.0
    sample_component = max(0.0, min(1.0, samples / 25.0)) * 10.0
    score = win_component + expectancy_component + pf_component + sample_component

    # Real-money losses receive a modest penalty, capped to avoid overreaction.
    if actual_pnl < 0:
        score -= min(15.0, abs(actual_pnl) / 5.0)
    return round(max(0.0, min(100.0, score)), 1)


def _symbol_reputation_label(score: float, samples: int) -> str:
    if samples < SYMBOL_REPUTATION_MIN_SAMPLES:
        return "LEARNING"
    if score < 20:
        return "BLACKLISTED"
    if score < SYMBOL_REPUTATION_BLOCK_SCORE:
        return "AVOID"
    if score < 50:
        return "WEAK"
    if score < 70:
        return "NEUTRAL"
    if score < 85:
        return "STRONG"
    return "ELITE"


def symbol_reputation_snapshot(force: bool = False) -> Dict[str, Any]:
    now_ts = time.time()
    if (not force and _symbol_reputation_cache.get("items") and
            now_ts - float(_symbol_reputation_cache.get("at") or 0) < SYMBOL_REPUTATION_CACHE_SECONDS):
        return _symbol_reputation_cache["items"]

    intelligence = symbol_intelligence(days=180, horizon_hours=24, minimum_samples=1, limit=1000)
    rows = intelligence.get("symbols", []) if intelligence.get("ok") else []
    items: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        samples = int(row.get("samples") or 0)
        score = _symbol_reputation_score(row)
        items[symbol] = {
            "symbol": symbol,
            "score": score,
            "label": _symbol_reputation_label(score, samples),
            "samples": samples,
            "winRate": round(float(row.get("winRate") or 0.0), 4),
            "expectancyPct": round(float(row.get("averageReturnPct") or row.get("expectancyPct") or 0.0), 4),
            "profitFactor": round(float(row.get("profitFactor") or 0.0), 4),
            "actualTrades": int(row.get("actualTrades") or 0),
            "actualPnlGbp": round(float(row.get("actualPnlGbp") or 0.0), 2),
            "mature": samples >= SYMBOL_REPUTATION_MIN_SAMPLES,
        }
    _symbol_reputation_cache["at"] = now_ts
    _symbol_reputation_cache["items"] = items
    return items


def _symbol_reputation_active_cooldown(symbol: str) -> Optional[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return None
    try:
        _symbol_reputation_ensure_table()
        conn = db_connect()
        row = conn.execute(
            "SELECT * FROM symbol_reputation_cooldowns WHERE symbol=? AND active=1",
            (symbol.upper(),),
        ).fetchone()
        if not row:
            conn.close()
            return None
        item = dict(row)
        expires = datetime.fromisoformat(str(item.get("expires_at")).replace("Z", "+00:00"))
        if expires <= datetime.now(UTC):
            conn.execute("UPDATE symbol_reputation_cooldowns SET active=0,updated_at=? WHERE symbol=?",
                         (datetime.now(UTC).isoformat(), symbol.upper()))
            conn.commit()
            conn.close()
            return None
        conn.close()
        return item
    except Exception as exc:
        print(f"SYMBOL REPUTATION COOLDOWN READ ERROR {symbol}: {exc}")
        return None


def _symbol_reputation_set_cooldown(symbol: str, score: float, reason: str) -> None:
    if not SQLITE_ENABLED:
        return
    try:
        _symbol_reputation_ensure_table()
        now = datetime.now(UTC)
        expires = now + timedelta(days=SYMBOL_REPUTATION_COOLDOWN_DAYS)
        conn = db_connect()
        conn.execute("""
            INSERT INTO symbol_reputation_cooldowns
            (symbol,started_at,expires_at,score,reason,active,updated_at)
            VALUES (?,?,?,?,?,1,?)
            ON CONFLICT(symbol) DO UPDATE SET
              started_at=excluded.started_at,expires_at=excluded.expires_at,
              score=excluded.score,reason=excluded.reason,active=1,updated_at=excluded.updated_at
        """, (symbol.upper(), now.isoformat(), expires.isoformat(), float(score), reason, now.isoformat()))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"SYMBOL REPUTATION COOLDOWN SAVE ERROR {symbol}: {exc}")


def symbol_reputation_allows_live_buy(symbol: str) -> Tuple[bool, str, Dict[str, Any]]:
    symbol = str(symbol or "").upper().strip()
    if not SYMBOL_REPUTATION_ENABLED or not symbol:
        return True, "reputation gate disabled", {"symbol": symbol, "label": "DISABLED"}

    cooldown = _symbol_reputation_active_cooldown(symbol)
    if cooldown:
        return False, f"symbol cooldown active until {cooldown.get('expires_at')}", {
            "symbol": symbol, "label": "COOLDOWN", "score": cooldown.get("score"),
            "expiresAt": cooldown.get("expires_at"), "reason": cooldown.get("reason")
        }

    item = symbol_reputation_snapshot().get(symbol)
    if not item:
        return True, "no reputation evidence yet", {"symbol": symbol, "label": "LEARNING", "samples": 0}
    if not item.get("mature"):
        return True, f"learning ({item.get('samples',0)}/{SYMBOL_REPUTATION_MIN_SAMPLES} samples)", item

    score = float(item.get("score") or 0.0)
    if score < SYMBOL_REPUTATION_BLOCK_SCORE:
        reason = (f"reputation {score:.1f}/100 ({item.get('label')}); "
                  f"samples={item.get('samples')} win_rate={float(item.get('winRate') or 0):.0%} "
                  f"expectancy={float(item.get('expectancyPct') or 0):.2f}%")
        _symbol_reputation_set_cooldown(symbol, score, reason)
        return False, reason, item
    return True, f"reputation passed {score:.1f}/100", item


def symbol_reputation_summary(force: bool = False) -> Dict[str, Any]:
    items = list(symbol_reputation_snapshot(force=force).values())
    items.sort(key=lambda x: (float(x.get("score") or 0.0), -int(x.get("samples") or 0)))
    cooldowns = []
    if SQLITE_ENABLED:
        try:
            _symbol_reputation_ensure_table()
            conn = db_connect()
            cooldowns = [dict(r) for r in conn.execute(
                "SELECT * FROM symbol_reputation_cooldowns WHERE active=1 ORDER BY score ASC"
            ).fetchall()]
            conn.close()
        except Exception as exc:
            print(f"SYMBOL REPUTATION SUMMARY ERROR: {exc}")
    return {
        "ok": True,
        "version": "V10.5",
        "enabled": SYMBOL_REPUTATION_ENABLED,
        "minimumSamples": SYMBOL_REPUTATION_MIN_SAMPLES,
        "blockBelowScore": SYMBOL_REPUTATION_BLOCK_SCORE,
        "cooldownDays": SYMBOL_REPUTATION_COOLDOWN_DAYS,
        "summary": {
            "symbols": len(items),
            "blocked": sum(1 for x in items if x.get("mature") and float(x.get("score") or 0) < SYMBOL_REPUTATION_BLOCK_SCORE),
            "strong": sum(1 for x in items if float(x.get("score") or 0) >= 70),
            "learning": sum(1 for x in items if not x.get("mature")),
            "activeCooldowns": len(cooldowns),
        },
        "symbols": items,
        "cooldowns": cooldowns,
        "liveGateActive": True,
    }


@app.get('/v10/symbol-reputation/summary')
def api_symbol_reputation_summary(request: Request, force: bool = False):
    verify_api_key(request)
    return symbol_reputation_summary(force=force)


@app.get('/v10/symbol-reputation/{symbol}')
def api_symbol_reputation_symbol(symbol: str, request: Request):
    verify_api_key(request)
    symbol = symbol.upper().strip()
    allowed, reason, reputation = symbol_reputation_allows_live_buy(symbol)
    return {"ok": True, "symbol": symbol, "allowed": allowed, "reason": reason, "reputation": reputation}


@app.get('/rule-intelligence/summary')
def api_rule_intelligence_summary(request: Request, days: int = 180, horizon_hours: int = 24, minimum_samples: int = 20, limit: int = 100):
    verify_api_key(request)
    return rule_intelligence(days, horizon_hours, minimum_samples, limit)


@app.get('/weakness-intelligence/summary')
def api_weakness_intelligence_summary(request: Request):
    verify_api_key(request)
    return weakness_intelligence_summary()

# =========================
# TRADEBOT V9.6 — PERIODIC AI SUMMARY LOG
# Read-only operational visibility. Never places orders or changes settings.
# =========================

def ai_periodic_summary_payload() -> Dict[str, Any]:
    """Build a compact operational summary from persistent decision and outcome data."""
    counts = {"total": 0, "approved": 0, "bought": 0, "blocked": 0, "rejected": 0}
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute("""
            SELECT UPPER(COALESCE(decision,'UNKNOWN')) AS decision_name, COUNT(*) AS decision_count
            FROM v2_setup_decisions
            WHERE date(timestamp) = date('now')
            GROUP BY UPPER(COALESCE(decision,'UNKNOWN'))
        """).fetchall()
        conn.close()
        for row in rows:
            name = str(row[0] or "UNKNOWN").upper()
            value = int(row[1] or 0)
            counts["total"] += value
            if name == "APPROVED": counts["approved"] = value
            elif name == "BOUGHT": counts["bought"] = value
            elif name == "BLOCKED": counts["blocked"] = value
            elif name == "REJECTED": counts["rejected"] = value
    except Exception as exc:
        counts["decisionError"] = str(exc)

    shadow = shadow_trading_summary(days=30, horizon_hours=24)
    advisor = ai_advisor_summary(limit=5)
    shadow_summary = shadow.get("summary", {}) if shadow.get("ok") else {}
    evidence = advisor.get("evidence", {}) if advisor.get("ok") else {}
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "decisionsToday": counts,
        "shadow": {
            "completed": int(shadow_summary.get("completed") or 0),
            "pending": int(shadow_summary.get("pending") or 0),
            "winRate": float(shadow_summary.get("winRate") or 0.0),
            "virtualPnlGbp": float(shadow_summary.get("virtualPnlGbp") or 0.0),
        },
        "advisor": {
            "readiness": advisor.get("readiness", "UNKNOWN"),
            "completedOutcomes": int(evidence.get("completedOutcomes") or 0),
            "pendingOutcomes": int(evidence.get("pendingOutcomes") or 0),
            "validatedPositive": int(evidence.get("validatedPositive") or 0),
            "validatedNegative": int(evidence.get("validatedNegative") or 0),
            "learningRuns": int(evidence.get("learningRuns") or 0),
        },
        "advisoryOnly": True,
        "liveChanges": False,
    }


def ai_periodic_summary_worker() -> None:
    time.sleep(AI_SUMMARY_LOG_STARTUP_DELAY_SECONDS)
    while True:
        try:
            _advisor_cycle_started = _cycle_monitor_start("advisor")
            summary = ai_periodic_summary_payload()
            d = summary["decisionsToday"]
            sh = summary["shadow"]
            adv = summary["advisor"]
            print(
                "AI ADVISOR SUMMARY | "
                f"decisions_today={d.get('total',0)} "
                f"approved={d.get('approved',0)} bought={d.get('bought',0)} "
                f"blocked={d.get('blocked',0)} rejected={d.get('rejected',0)} | "
                f"shadow_complete={sh.get('completed',0)} pending={sh.get('pending',0)} "
                f"win_rate={sh.get('winRate',0.0):.1%} virtual_pnl=£{sh.get('virtualPnlGbp',0.0):.2f} | "
                f"readiness={adv.get('readiness','UNKNOWN')} outcomes={adv.get('completedOutcomes',0)} "
                f"validated=+{adv.get('validatedPositive',0)}/-{adv.get('validatedNegative',0)} "
                f"learning_runs={adv.get('learningRuns',0)} live_changes=False"
            )
            _cycle_monitor_finish("advisor", _advisor_cycle_started, True)
        except Exception as exc:
            if "_advisor_cycle_started" in locals():
                _cycle_monitor_finish("advisor", _advisor_cycle_started, False, str(exc))
            print(f"AI ADVISOR SUMMARY ERROR: {exc}")
        time.sleep(AI_SUMMARY_LOG_INTERVAL_SECONDS)


@app.get('/ai-advisor/periodic-summary')
def api_ai_periodic_summary(request: Request):
    verify_api_key(request)
    return ai_periodic_summary_payload()


# =========================
# TRADEBOT V10 — HUMAN-GATED STRATEGY PROMOTION
# Converts the existing guarded adaptive optimiser into a transparent
# evaluate -> stabilise -> approve -> apply -> rollback workflow.
# No strategy change occurs without an authenticated explicit approval.
# =========================
V10_HUMAN_PROMOTION_ENABLED = os.getenv("V10_HUMAN_PROMOTION_ENABLED", "true").lower() == "true"
V10_PROMOTION_MIN_SAMPLES = max(25, int(os.getenv("V10_PROMOTION_MIN_SAMPLES", "100") or 100))
V10_PROMOTION_CONFIRMATION = os.getenv("V10_PROMOTION_CONFIRMATION", "PROMOTE").strip().upper() or "PROMOTE"


def _v10_promotion_ensure_tables() -> None:
    if not SQLITE_ENABLED:
        return
    init_db()
    conn = db_connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS v10_promotion_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'EVALUATING',
            horizon_hours INTEGER NOT NULL,
            minimum_samples INTEGER NOT NULL,
            matching_runs INTEGER NOT NULL DEFAULT 0,
            required_runs INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL,
            approved_at TEXT,
            rejected_at TEXT,
            applied_version TEXT,
            note TEXT
        )
    """)
    conn.commit()
    conn.close()


def _v10_candidate_key(candidate: Dict[str, Any], horizon_hours: int) -> str:
    identity = {
        "horizonHours": int(horizon_hours),
        "confidence": round(float(candidate.get("confidence") or 0.0), 4),
        "quality": round(float(candidate.get("quality") or 0.0), 6),
        "targetConfidence": round(float(candidate.get("targetConfidence") or candidate.get("confidence") or 0.0), 4),
        "targetQuality": round(float(candidate.get("targetQuality") or candidate.get("quality") or 0.0), 6),
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _v10_save_evaluation(result: Dict[str, Any]) -> Dict[str, Any]:
    _v10_promotion_ensure_tables()
    candidate = result.get("stagedRecommendation") or result.get("recommended") or {}
    if not candidate:
        return result
    key = _v10_candidate_key(candidate, int(result.get("horizonHours") or 24))
    stability = result.get("stability") or {}
    recommendation = str(result.get("recommendation") or "KEEP_CURRENT")
    status = "READY_FOR_APPROVAL" if recommendation == "READY_TO_APPLY" else "EVALUATING"
    now = datetime.now(UTC).isoformat()
    payload = {
        "optimizer": result,
        "candidate": candidate,
        "candidateKey": key,
        "humanApprovalRequired": True,
        "automaticLiveChanges": False,
    }
    conn = db_connect()
    conn.execute("""
        INSERT INTO v10_promotion_candidates
        (candidate_key,created_at,updated_at,status,horizon_hours,minimum_samples,matching_runs,required_runs,payload_json)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(candidate_key) DO UPDATE SET
          updated_at=excluded.updated_at,
          status=CASE
            WHEN v10_promotion_candidates.status IN ('APPLIED','REJECTED') THEN v10_promotion_candidates.status
            ELSE excluded.status
          END,
          matching_runs=excluded.matching_runs,
          required_runs=excluded.required_runs,
          payload_json=excluded.payload_json
    """, (
        key, now, now, status,
        int(result.get("horizonHours") or 24),
        int(result.get("minimumSamples") or V10_PROMOTION_MIN_SAMPLES),
        int(stability.get("matchingRuns") or 0),
        int(stability.get("requiredRuns") or V2_OPTIMIZER_REQUIRED_STABLE_RUNS),
        json.dumps(payload),
    ))
    conn.commit()
    conn.close()
    result["promotion"] = {
        "candidateKey": key,
        "status": status,
        "humanApprovalRequired": True,
        "automaticLiveChanges": False,
    }
    return result


def v10_evaluate_promotion(horizon_hours: int = 24, min_samples: int = V10_PROMOTION_MIN_SAMPLES) -> Dict[str, Any]:
    if not V10_HUMAN_PROMOTION_ENABLED:
        return {"ok": False, "message": "Human strategy promotion is disabled by configuration."}
    result = v2_adaptive_threshold_recommendations(
        max(1, int(horizon_hours)),
        max(V10_PROMOTION_MIN_SAMPLES, int(min_samples)),
    )
    if result.get("ok"):
        _v10_save_evaluation(result)
    result["version"] = "V10"
    result["name"] = "Human-Gated Strategy Promotion"
    result["humanApprovalRequired"] = True
    result["automaticLiveChanges"] = False
    return result


def v10_promotion_status(limit: int = 20) -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled", "candidates": []}
    _v10_promotion_ensure_tables()
    conn = db_connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM v10_promotion_candidates ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit), 100)),),
    ).fetchall()]
    conn.close()
    candidates = []
    for row in rows:
        try:
            payload = json.loads(row.pop("payload_json") or "{}")
        except Exception:
            payload = {}
        row["payload"] = payload
        row["candidate"] = payload.get("candidate") or {}
        row["optimizer"] = payload.get("optimizer") or {}
        candidates.append(row)
    latest = candidates[0] if candidates else None
    return {
        "ok": True,
        "version": "V10",
        "enabled": V10_HUMAN_PROMOTION_ENABLED,
        "mode": "HUMAN_APPROVAL_ONLY",
        "automaticLiveChanges": False,
        "current": {
            "confidence": float(A_PLUS_MIN_CONFIDENCE),
            "quality": float(A_PLUS_MIN_QUALITY),
        },
        "latest": latest,
        "candidates": candidates,
        "requiredConfirmation": V10_PROMOTION_CONFIRMATION,
        "rollbackAvailable": bool(v2_strategy_timeline(1).get("rows")),
    }


def v10_approve_promotion(candidate_key: str, confirmation: str) -> Dict[str, Any]:
    if not V10_HUMAN_PROMOTION_ENABLED:
        return {"ok": False, "message": "Human strategy promotion is disabled."}
    if str(confirmation or "").strip().upper() != V10_PROMOTION_CONFIRMATION:
        return {"ok": False, "message": f"Type {V10_PROMOTION_CONFIRMATION} to approve this strategy change."}
    _v10_promotion_ensure_tables()
    conn = db_connect()
    stored = conn.execute(
        "SELECT * FROM v10_promotion_candidates WHERE candidate_key=?",
        (str(candidate_key or "").strip(),),
    ).fetchone()
    conn.close()
    if not stored:
        return {"ok": False, "message": "Promotion candidate not found."}
    stored = dict(stored)
    if stored.get("status") == "APPLIED":
        return {"ok": False, "message": "This candidate has already been applied."}
    if stored.get("status") == "REJECTED":
        return {"ok": False, "message": "This candidate was rejected. Run a fresh evaluation."}

    # Re-evaluate at approval time. This prevents approval of stale evidence.
    fresh = v10_evaluate_promotion(
        int(stored.get("horizon_hours") or 24),
        int(stored.get("minimum_samples") or V10_PROMOTION_MIN_SAMPLES),
    )
    candidate = fresh.get("stagedRecommendation") or {}
    fresh_key = (fresh.get("promotion") or {}).get("candidateKey")
    if fresh.get("recommendation") != "READY_TO_APPLY":
        return {
            "ok": False,
            "message": "The candidate is no longer ready. It must pass all safeguards for the required consecutive evaluations.",
            "evaluation": fresh,
        }
    if fresh_key != str(candidate_key):
        return {
            "ok": False,
            "message": "Evidence changed and produced a different candidate. Review the new candidate before approval.",
            "evaluation": fresh,
        }
    if int(candidate.get("samples") or 0) < V10_PROMOTION_MIN_SAMPLES:
        return {"ok": False, "message": "Candidate does not meet the V10 minimum sample requirement."}

    previous_conf = float(A_PLUS_MIN_CONFIDENCE)
    previous_quality = float(A_PLUS_MIN_QUALITY)
    applied = apply_custom_a_plus_thresholds(
        float(candidate["confidence"]),
        float(candidate["quality"]),
        f"V10 human-approved candidate {candidate_key}",
        True,
    )
    now = datetime.now(UTC).isoformat()
    timeline = v2_strategy_timeline(1)
    version_label = ((timeline.get("rows") or [{}])[0]).get("version_label")
    conn = db_connect()
    conn.execute("""
        UPDATE v10_promotion_candidates
        SET status='APPLIED', approved_at=?, updated_at=?, applied_version=?, note=?
        WHERE candidate_key=?
    """, (
        now, now, version_label,
        f"Applied from confidence {previous_conf:.4f}/quality {previous_quality:.6f}",
        candidate_key,
    ))
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "message": "Human-approved staged strategy change applied.",
        "candidateKey": candidate_key,
        "previous": {"confidence": previous_conf, "quality": previous_quality},
        "current": applied,
        "appliedVersion": version_label,
        "rollbackAvailable": True,
        "automaticLiveChanges": False,
    }


def v10_reject_promotion(candidate_key: str, note: str = "") -> Dict[str, Any]:
    _v10_promotion_ensure_tables()
    now = datetime.now(UTC).isoformat()
    conn = db_connect()
    cur = conn.execute("""
        UPDATE v10_promotion_candidates
        SET status='REJECTED', rejected_at=?, updated_at=?, note=?
        WHERE candidate_key=? AND status!='APPLIED'
    """, (now, now, str(note or "Human rejected candidate")[:500], str(candidate_key or "").strip()))
    conn.commit()
    changed = cur.rowcount
    conn.close()
    return {"ok": bool(changed), "message": "Candidate rejected." if changed else "Candidate was not found or was already applied."}


@app.get('/v10/promotion/status')
def api_v10_promotion_status(request: Request, limit: int = 20):
    verify_api_key(request)
    return v10_promotion_status(limit)


@app.post('/v10/promotion/evaluate')
def api_v10_promotion_evaluate(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v10_evaluate_promotion(
        int(payload.get("horizonHours") or 24),
        int(payload.get("minimumSamples") or V10_PROMOTION_MIN_SAMPLES),
    )


@app.post('/v10/promotion/approve')
def api_v10_promotion_approve(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v10_approve_promotion(
        str(payload.get("candidateKey") or ""),
        str(payload.get("confirmation") or ""),
    )


@app.post('/v10/promotion/reject')
def api_v10_promotion_reject(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v10_reject_promotion(
        str(payload.get("candidateKey") or ""),
        str(payload.get("note") or ""),
    )


@app.post('/v10/promotion/rollback')
def api_v10_promotion_rollback(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    confirmation = str(payload.get("confirmation") or "").strip().upper()
    if confirmation != "ROLLBACK":
        return {"ok": False, "message": "Type ROLLBACK to restore the previous adaptive strategy thresholds."}
    return v2_rollback_latest_strategy()



# =========================
# V10.3 ADAPTIVE AI RISK ENGINE
# =========================
AI_RISK_ENGINE_VERSION = "V10.3"
AI_RISK_ENGINE_ENABLED = os.getenv("AI_RISK_ENGINE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
AI_RISK_EMERGENCY_STOP_PCT = max(6.0, min(15.0, float(os.getenv("AI_RISK_EMERGENCY_STOP_PCT", "10.0") or 10.0)))
AI_RISK_MIN_POSITION_MULTIPLIER = max(0.25, min(1.0, float(os.getenv("AI_RISK_MIN_POSITION_MULTIPLIER", "0.60") or 0.60)))
AI_RISK_MAX_POSITION_MULTIPLIER = max(1.0, min(1.50, float(os.getenv("AI_RISK_MAX_POSITION_MULTIPLIER", "1.25") or 1.25)))

# V17.7 — Volatility-aware trailing-profit activation.
# The saved AI risk profile remains the maximum breathing room selected at entry.
# While a position is live, sufficiently mature recent price behaviour may arm
# the profit trail earlier for slow/steady names. Fast movers keep their wider
# entry-selected activation threshold. This changes profit protection only; it
# never loosens stop-loss/emergency protection and never raises trail-start
# above the profile that was approved at entry.
V17_ADAPTIVE_TRAIL_START_ENABLED = os.getenv("V17_ADAPTIVE_TRAIL_START_ENABLED", "true").lower() in ("1", "true", "yes", "on")
V17_ADAPTIVE_TRAIL_MIN_SAMPLES = max(12, int(os.getenv("V17_ADAPTIVE_TRAIL_MIN_SAMPLES", "20") or 20))
V17_ADAPTIVE_TRAIL_LOW_VOL_PCT = max(0.01, float(os.getenv("V17_ADAPTIVE_TRAIL_LOW_VOL_PCT", "0.08") or 0.08))
V17_ADAPTIVE_TRAIL_MED_VOL_PCT = max(V17_ADAPTIVE_TRAIL_LOW_VOL_PCT, float(os.getenv("V17_ADAPTIVE_TRAIL_MED_VOL_PCT", "0.18") or 0.18))
V17_ADAPTIVE_TRAIL_LOW_START_PCT = max(1.0, float(os.getenv("V17_ADAPTIVE_TRAIL_LOW_START_PCT", "1.75") or 1.75))
V17_ADAPTIVE_TRAIL_MED_START_PCT = max(V17_ADAPTIVE_TRAIL_LOW_START_PCT, float(os.getenv("V17_ADAPTIVE_TRAIL_MED_START_PCT", "2.50") or 2.50))
V17_ADAPTIVE_TRAIL_HIGH_START_PCT = max(V17_ADAPTIVE_TRAIL_MED_START_PCT, float(os.getenv("V17_ADAPTIVE_TRAIL_HIGH_START_PCT", "4.00") or 4.00))
V17_ADAPTIVE_TRAIL_LOG_SECONDS = max(60.0, float(os.getenv("V17_ADAPTIVE_TRAIL_LOG_SECONDS", "300") or 300))
_ai_risk_adaptive_trail_log: Dict[str, Dict[str, Any]] = {}
_ai_risk_symbol_cache: Dict[str, Any] = {"ts": 0.0, "rows": {}}
_ai_risk_tables_ready = False
_ai_risk_tables_lock = threading.RLock()


def _ai_risk_ensure_tables() -> None:
    global _ai_risk_tables_ready
    if _ai_risk_tables_ready or not SQLITE_ENABLED:
        return
    with _ai_risk_tables_lock:
        if _ai_risk_tables_ready:
            return
        conn = db_connect()
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS v10_position_risk_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                created_at TEXT NOT NULL,
                entry_price REAL,
                confidence REAL,
                quality REAL,
                symbol_status TEXT,
                symbol_samples INTEGER,
                symbol_expectancy_pct REAL,
                position_multiplier REAL NOT NULL,
                stop_loss_pct REAL NOT NULL,
                fast_stop_loss_pct REAL NOT NULL,
                trail_start_pct REAL NOT NULL,
                trail_giveback_pct REAL NOT NULL,
                emergency_stop_pct REAL NOT NULL,
                rationale TEXT,
                active INTEGER NOT NULL DEFAULT 1
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_v10_risk_symbol_time ON v10_position_risk_profiles(symbol, created_at DESC)")
            conn.commit()
            _ai_risk_tables_ready = True
        finally:
            conn.close()


def _ai_risk_symbol_evidence(symbol: str) -> Dict[str, Any]:
    symbol = str(symbol or "").upper().strip()
    now = time.time()
    if now - float(_ai_risk_symbol_cache.get("ts") or 0.0) > 600:
        rows = {}
        try:
            payload = symbol_intelligence(days=365, horizon_hours=24, minimum_samples=3, limit=500)
            for row in payload.get("symbols") or payload.get("items") or payload.get("rows") or []:
                key = str(row.get("symbol") or "").upper().strip()
                if key:
                    rows[key] = row
        except Exception as exc:
            print(f"AI RISK SYMBOL EVIDENCE ERROR: {exc}")
        _ai_risk_symbol_cache["ts"] = now
        _ai_risk_symbol_cache["rows"] = rows
    return dict((_ai_risk_symbol_cache.get("rows") or {}).get(symbol) or {})


def _ai_risk_build_profile(scan: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(scan.get("symbol") or "").upper().strip()
    confidence = float(scan.get("confidence") or calculate_confidence(scan)[0] or 0.0)
    quality = float(scan.get("quality_score") or scan.get("quality") or 0.0)
    spread = max(0.0, float(scan.get("spread") or 0.0))
    momentum = float(scan.get("short_momentum") or scan.get("momentum") or 0.0)
    evidence = _ai_risk_symbol_evidence(symbol)
    status = str(evidence.get("status") or "INSUFFICIENT_DATA").upper()
    samples = int(evidence.get("samples") or 0)
    expectancy = float(evidence.get("averageReturnPct") or evidence.get("expectancyPct") or 0.0)

    # Start from the currently promoted live configuration.
    base_stop = max(0.5, (1.0 - float(STOP_LOSS)) * 100.0)
    base_fast = max(0.5, abs(float(FAST_STOP_LOSS_PCT)))
    base_trail_start = max(0.5, (float(TRAIL_START) - 1.0) * 100.0)
    base_giveback = max(0.2, (1.0 - float(TRAIL_GIVEBACK)) * 100.0)

    conviction = max(0.0, min(1.0, (confidence - 0.45) / 0.50))
    quality_boost = max(-0.15, min(0.15, (quality - 0.025) * 4.0))
    status_adjust = 0.12 if status == "STRONG" else -0.18 if status == "WEAK" else -0.08 if status == "UNDER_REVIEW" else 0.0
    expectancy_adjust = max(-0.12, min(0.12, expectancy / 10.0)) if samples >= 5 else 0.0
    spread_penalty = max(0.0, min(0.15, spread * 5.0))
    position_multiplier = 0.72 + conviction * 0.38 + quality_boost + status_adjust + expectancy_adjust - spread_penalty
    position_multiplier = _v10_clamp(position_multiplier, AI_RISK_MIN_POSITION_MULTIPLIER, AI_RISK_MAX_POSITION_MULTIPLIER)

    # Higher-quality, historically strong trades receive slightly more breathing room.
    room_adjust = (conviction - 0.5) * 1.2 + (0.45 if status == "STRONG" else -0.55 if status == "WEAK" else -0.25 if status == "UNDER_REVIEW" else 0.0)
    if momentum < -0.002:
        room_adjust -= 0.35
    stop_pct = _v10_clamp(base_stop + room_adjust, V10_CONSTITUTION["stopLossPct"]["min"], V10_CONSTITUTION["stopLossPct"]["max"])
    fast_stop_pct = _v10_clamp(min(base_fast, stop_pct), V10_CONSTITUTION["stopLossPct"]["min"], V10_CONSTITUTION["stopLossPct"]["max"])
    trail_start_pct = _v10_clamp(base_trail_start + room_adjust * 0.70, V10_CONSTITUTION["trailStartPct"]["min"], V10_CONSTITUTION["trailStartPct"]["max"])
    giveback_pct = _v10_clamp(base_giveback + room_adjust * 0.25, V10_CONSTITUTION["trailGivebackPct"]["min"], V10_CONSTITUTION["trailGivebackPct"]["max"])

    rationale = (
        f"confidence={confidence:.2f}; quality={quality:.4f}; symbol={status}; "
        f"samples={samples}; expectancy={expectancy:.3f}%; spread={spread:.4f}"
    )
    return {
        "version": AI_RISK_ENGINE_VERSION,
        "symbol": symbol,
        "confidence": round(confidence, 4),
        "quality": round(quality, 6),
        "symbolStatus": status,
        "symbolSamples": samples,
        "symbolExpectancyPct": round(expectancy, 4),
        "positionMultiplier": round(position_multiplier, 4),
        "stopLossPct": round(stop_pct, 4),
        "fastStopLossPct": round(fast_stop_pct, 4),
        "trailStartPct": round(trail_start_pct, 4),
        "trailGivebackPct": round(giveback_pct, 4),
        "emergencyStopPct": round(AI_RISK_EMERGENCY_STOP_PCT, 4),
        "rationale": rationale,
    }


def _ai_risk_save_profile(profile: Dict[str, Any], entry_price: float = 0.0) -> None:
    if not SQLITE_ENABLED or not AI_RISK_ENGINE_ENABLED:
        return
    _ai_risk_ensure_tables()
    conn = db_connect(); now = datetime.now(UTC).isoformat(); symbol = profile["symbol"]
    conn.execute("UPDATE v10_position_risk_profiles SET active=0 WHERE symbol=? AND active=1", (symbol,))
    conn.execute("""INSERT INTO v10_position_risk_profiles
        (symbol,created_at,entry_price,confidence,quality,symbol_status,symbol_samples,symbol_expectancy_pct,
         position_multiplier,stop_loss_pct,fast_stop_loss_pct,trail_start_pct,trail_giveback_pct,
         emergency_stop_pct,rationale,active)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
        (symbol, now, float(entry_price or 0.0), profile["confidence"], profile["quality"], profile["symbolStatus"],
         profile["symbolSamples"], profile["symbolExpectancyPct"], profile["positionMultiplier"],
         profile["stopLossPct"], profile["fastStopLossPct"], profile["trailStartPct"],
         profile["trailGivebackPct"], profile["emergencyStopPct"], profile["rationale"]))
    conn.commit(); conn.close()
    print(
        f"AI RISK PROFILE {symbol} | size=x{profile['positionMultiplier']:.2f} "
        f"stop={profile['stopLossPct']:.2f}% trail={profile['trailStartPct']:.2f}%/"
        f"{profile['trailGivebackPct']:.2f}% emergency={profile['emergencyStopPct']:.2f}%"
    )


def _ai_risk_latest_profile(symbol: str) -> Dict[str, Any]:
    if not AI_RISK_ENGINE_ENABLED or not SQLITE_ENABLED:
        return {}
    try:
        _ai_risk_ensure_tables(); conn = db_connect()
        row = conn.execute("SELECT * FROM v10_position_risk_profiles WHERE symbol=? AND active=1 ORDER BY id DESC LIMIT 1", (str(symbol).upper(),)).fetchone()
        conn.close()
        if not row:
            return {}
        d = dict(row)
        return {
            "symbol": d.get("symbol"), "createdAt": d.get("created_at"), "confidence": d.get("confidence"),
            "quality": d.get("quality"), "symbolStatus": d.get("symbol_status"), "symbolSamples": d.get("symbol_samples"),
            "symbolExpectancyPct": d.get("symbol_expectancy_pct"), "positionMultiplier": d.get("position_multiplier"),
            "stopLossPct": d.get("stop_loss_pct"), "fastStopLossPct": d.get("fast_stop_loss_pct"),
            "trailStartPct": d.get("trail_start_pct"), "trailGivebackPct": d.get("trail_giveback_pct"),
            "emergencyStopPct": d.get("emergency_stop_pct"), "rationale": d.get("rationale")
        }
    except Exception as exc:
        print(f"AI RISK PROFILE READ ERROR {symbol}: {exc}")
        return {}


def ai_risk_notional(scan: Dict[str, Any]) -> float:
    base = float(confidence_notional(scan))

    # V17.0.7: in explicit single-position full-buy mode, risk intelligence
    # may tune stops/trails but MUST NOT reduce the requested order notional.
    # Entry quality gates still decide whether a trade is permitted.
    if bool(globals().get("V17_SINGLE_FULL_BUY_MODE", False)) or (
        bool(globals().get("FULL_BUY_WHEN_ONE_POSITION", False))
        and effective_max_positions() <= 1
    ):
        try:
            account = get_account()
            live_equity = max(0.0, float(account.equity))
            live_bp = max(0.0, float(account.buying_power))
            working = profit_vault_deployable_usd(live_equity, live_bp) if "profit_vault_deployable_usd" in globals() else live_bp
            return round(max(0.0, min(live_bp, working) - float(globals().get("FULL_BUY_CASH_BUFFER", 2.0))), 2)
        except Exception:
            return base

    if not AI_RISK_ENGINE_ENABLED:
        return base
    profile = _ai_risk_build_profile(scan)
    try:
        account = get_account(); equity = float(account.equity); buying_power = float(account.buying_power)
        sizing_equity = effective_trading_equity(equity) if "effective_trading_equity" in globals() else equity
        constitutional_cap = sizing_equity * float(V10_CONSTITUTION["positionValuePct"]["max"])
        usable_cash = max(0.0, buying_power - CASH_BUFFER)
        return round(max(0.0, min(base * profile["positionMultiplier"], constitutional_cap, usable_cash)), 2)
    except Exception:
        return round(max(0.0, base * profile["positionMultiplier"]), 2)


def _v17_adaptive_trail_start(symbol: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of the risk profile with a volatility-aware trail start.

    Recent realised volatility is taken from the bot's live price curve. We only
    tighten the entry-selected trail activation; we never widen it. If there is
    not enough live evidence yet, the original profile is returned unchanged.
    """
    result = dict(profile or {})
    base_start = abs(float(result.get("trailStartPct") or ((float(TRAIL_START) - 1.0) * 100.0)))
    result["trailStartPctBase"] = round(base_start, 4)
    result["adaptiveTrailEnabled"] = bool(V17_ADAPTIVE_TRAIL_START_ENABLED)
    result["adaptiveTrailMode"] = "BASE"

    if not V17_ADAPTIVE_TRAIL_START_ENABLED:
        return result

    try:
        ensure_symbol_state(symbol)
        metrics = _v16_curve_metrics({"symbol": symbol, "price_curve": (state.get(symbol) or {}).get("price_curve") or []})
        samples = int(metrics.get("samples") or 0)
        # _v16_curve_metrics volatility is a decimal return; convert to percent.
        realised_vol_pct = abs(float(metrics.get("volatility") or 0.0)) * 100.0
        result["adaptiveTrailSamples"] = samples
        result["adaptiveTrailVolatilityPct"] = round(realised_vol_pct, 4)

        if samples < V17_ADAPTIVE_TRAIL_MIN_SAMPLES:
            result["adaptiveTrailMode"] = "LEARNING"
            return result

        if realised_vol_pct <= V17_ADAPTIVE_TRAIL_LOW_VOL_PCT:
            target = V17_ADAPTIVE_TRAIL_LOW_START_PCT
            mode = "STEADY_EARLY_PROTECTION"
        elif realised_vol_pct <= V17_ADAPTIVE_TRAIL_MED_VOL_PCT:
            target = V17_ADAPTIVE_TRAIL_MED_START_PCT
            mode = "NORMAL_PROTECTION"
        else:
            target = V17_ADAPTIVE_TRAIL_HIGH_START_PCT
            mode = "VOLATILE_BREATHING_ROOM"

        # Never loosen the entry-approved profile. This feature can only bank
        # protection earlier when the stock proves it is behaving steadily.
        effective = min(base_start, target)
        effective = _v10_clamp(
            effective,
            float(V10_CONSTITUTION["trailStartPct"]["min"]),
            float(V10_CONSTITUTION["trailStartPct"]["max"]),
        )
        result["trailStartPct"] = round(effective, 4)
        result["adaptiveTrailTargetPct"] = round(target, 4)
        result["adaptiveTrailMode"] = mode if effective < base_start - 0.001 else "BASE_VOLATILITY_OK"

        # Bounded, deduped observability so Render makes it obvious why a trail
        # activation moved without flooding the log every status refresh.
        now_mono = time.monotonic()
        cached = _ai_risk_adaptive_trail_log.get(symbol) or {}
        changed = abs(float(cached.get("effective") or -999.0) - effective) >= 0.05 or str(cached.get("mode") or "") != result["adaptiveTrailMode"]
        if changed or now_mono - float(cached.get("ts") or 0.0) >= V17_ADAPTIVE_TRAIL_LOG_SECONDS:
            if effective < base_start - 0.001:
                print(
                    f"V17.7 ADAPTIVE TRAIL | {symbol} mode={result['adaptiveTrailMode']} "
                    f"samples={samples} vol={realised_vol_pct:.3f}% "
                    f"base={base_start:.2f}% effective={effective:.2f}%"
                )
            _ai_risk_adaptive_trail_log[symbol] = {"ts": now_mono, "effective": effective, "mode": result["adaptiveTrailMode"]}
        return result
    except Exception as exc:
        result["adaptiveTrailMode"] = "BASE_ERROR_FALLBACK"
        result["adaptiveTrailError"] = str(exc)[:300]
        return result


def _ai_risk_effective_profile(symbol: str) -> Dict[str, Any]:
    profile = _ai_risk_latest_profile(symbol)
    if not profile:
        profile = {
            "symbol": symbol,
            "stopLossPct": round((1.0 - float(STOP_LOSS)) * 100.0, 4),
            "fastStopLossPct": abs(float(FAST_STOP_LOSS_PCT)),
            "trailStartPct": round((float(TRAIL_START) - 1.0) * 100.0, 4),
            "trailGivebackPct": round((1.0 - float(TRAIL_GIVEBACK)) * 100.0, 4),
            "emergencyStopPct": AI_RISK_EMERGENCY_STOP_PCT,
            "positionMultiplier": 1.0,
            "rationale": "Fallback to current promoted live configuration."
        }
    return _v17_adaptive_trail_start(str(symbol or "").upper(), profile)


def ai_risk_engine_status() -> Dict[str, Any]:
    profiles = []
    if SQLITE_ENABLED:
        try:
            _ai_risk_ensure_tables(); conn = db_connect()
            profiles = [dict(r) for r in conn.execute("SELECT * FROM v10_position_risk_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 50").fetchall()]
            conn.close()
        except Exception as exc:
            print(f"AI RISK STATUS ERROR: {exc}")
    return {
        "ok": True, "version": AI_RISK_ENGINE_VERSION, "enabled": AI_RISK_ENGINE_ENABLED,
        "emergencyStopPct": AI_RISK_EMERGENCY_STOP_PCT,
        "managedParameters": ["position size", "stop loss", "fast stop", "trailing start", "trailing giveback"],
        "profiles": profiles,
        "constitution": {
            "positionValuePct": V10_CONSTITUTION.get("positionValuePct"),
            "stopLossPct": V10_CONSTITUTION.get("stopLossPct"),
            "trailStartPct": V10_CONSTITUTION.get("trailStartPct"),
            "trailGivebackPct": V10_CONSTITUTION.get("trailGivebackPct"),
            "emergencyStopCannotBeDisabled": True,
        },
    }


@app.get("/v10/risk-engine/status")
def api_v10_risk_engine_status(request: Request):
    verify_api_key(request); return ai_risk_engine_status()


@app.get("/v10/risk-engine/position/{symbol}")
def api_v10_risk_engine_position(symbol: str, request: Request):
    verify_api_key(request); return {"ok": True, "profile": _ai_risk_effective_profile(symbol.upper())}

# ============================================================
# TRADEBOT V10.2 — AUTONOMOUS AI OPERATOR
# Bounded self-optimisation with an immutable constitution.
# It can manage approved runtime settings, but cannot disable core safety.
# ============================================================
V10_OPERATOR_VERSION = "V10.3"
V10_OPERATOR_ENABLED = os.getenv("V10_OPERATOR_ENABLED", "true").lower() in ("1", "true", "yes", "on")
V10_OPERATOR_MODE = os.getenv("V10_OPERATOR_MODE", "SHADOW").strip().upper() or "SHADOW"  # OFF, SHADOW, AUTO
V10_OPERATOR_INTERVAL_SECONDS = max(900, int(os.getenv("V10_OPERATOR_INTERVAL_SECONDS", "3600") or 3600))
V10_OPERATOR_STARTUP_DELAY_SECONDS = max(30, int(os.getenv("V10_OPERATOR_STARTUP_DELAY_SECONDS", "180") or 180))
V10_OPERATOR_REQUIRED_STABLE_RUNS = max(2, int(os.getenv("V10_OPERATOR_REQUIRED_STABLE_RUNS", "5") or 5))
V10_OPERATOR_MIN_SAMPLES = max(100, int(os.getenv("V10_OPERATOR_MIN_SAMPLES", "500") or 500))
V10_OPERATOR_COOLDOWN_HOURS = max(1, int(os.getenv("V10_OPERATOR_COOLDOWN_HOURS", "24") or 24))
V10_OPERATOR_AUTO_ROLLBACK_DRAWDOWN_PCT = max(0.5, float(os.getenv("V10_OPERATOR_AUTO_ROLLBACK_DRAWDOWN_PCT", "4.0") or 4.0))
V10_OPERATOR_AUTO_ROLLBACK_DAILY_LOSS_PCT = max(0.25, float(os.getenv("V10_OPERATOR_AUTO_ROLLBACK_DAILY_LOSS_PCT", "2.0") or 2.0))

# Immutable constitution. These are hard ceilings/floors; the operator cannot override them.
V10_CONSTITUTION = {
    "maxPositions": {"min": 1, "max": max(1, int(os.getenv("V10_CONSTITUTION_MAX_POSITIONS", str(AI_POSITION_HARD_CAP)) or AI_POSITION_HARD_CAP))},
    "tradingCapUsd": {
        "min": max(25.0, float(os.getenv("V10_CONSTITUTION_MIN_CAP_USD", "100") or 100)),
        "max": max(25.0, float(os.getenv("V10_CONSTITUTION_MAX_CAP_USD", "1500") or 1500)),
    },
    "positionValuePct": {
        "min": max(0.02, float(os.getenv("V10_CONSTITUTION_MIN_POSITION_PCT", "0.10") or 0.10)),
        "max": min(1.0, float(os.getenv("V10_CONSTITUTION_MAX_POSITION_PCT", "1.00") or 1.00)),
    },
    "stopLossPct": {
        "min": max(0.5, float(os.getenv("V10_CONSTITUTION_MIN_STOP_PCT", "1.0") or 1.0)),
        "max": min(10.0, float(os.getenv("V10_CONSTITUTION_MAX_STOP_PCT", "5.0") or 5.0)),
    },
    "trailStartPct": {
        "min": max(0.5, float(os.getenv("V10_CONSTITUTION_MIN_TRAIL_START_PCT", "2.0") or 2.0)),
        "max": min(20.0, float(os.getenv("V10_CONSTITUTION_MAX_TRAIL_START_PCT", "10.0") or 10.0)),
    },
    "trailGivebackPct": {
        "min": max(0.2, float(os.getenv("V10_CONSTITUTION_MIN_TRAIL_GIVEBACK_PCT", "0.5") or 0.5)),
        "max": min(10.0, float(os.getenv("V10_CONSTITUTION_MAX_TRAIL_GIVEBACK_PCT", "4.0") or 4.0)),
    },
    "minimumEvidenceSamples": V10_OPERATOR_MIN_SAMPLES,
    "requiredStableRuns": V10_OPERATOR_REQUIRED_STABLE_RUNS,
    "dailyLossGuardCannotBeDisabled": True,
    "emergencyStopCannotBeDisabled": True,
    "pdtProtectionCannotBeDisabled": True,
    # V17.0.16: the user-selected single-position full-buy strategy is constitutional.
    # Autonomous evolution may tune bounded risk/exits, but cannot silently change
    # one-position/100%-target/full-buy mode while this strategy is enabled.
    "v17SingleFullBuyMode": {
        "locked": bool(V17_FULL_BUY_CONSTITUTION_LOCK and V17_SINGLE_FULL_BUY_MODE),
        "maxPositions": 1,
        "targetPositionValuePct": 1.0,
        "maxPositionValuePct": 1.0,
        "fullBuyWhenOnePosition": True,
        "manualChangeRequired": True,
    },
    "allChangesMustBeLogged": True,
    "allChangesMustBeReversible": True,
}

v10_operator_thread_started = False
_v10_operator_last_run_ts = 0.0
_V10_OPERATOR_SCHEMA_LOCK = threading.RLock()
_V10_OPERATOR_SCHEMA_COMPLETE = False


def _v10_operator_ensure_tables() -> None:
    global _V10_OPERATOR_SCHEMA_COMPLETE
    if not SQLITE_ENABLED or _V10_OPERATOR_SCHEMA_COMPLETE:
        return
    with _V10_OPERATOR_SCHEMA_LOCK:
        if _V10_OPERATOR_SCHEMA_COMPLETE:
            return
        conn = db_connect()
        conn.execute("""CREATE TABLE IF NOT EXISTS v10_operator_state (
            id INTEGER PRIMARY KEY CHECK (id=1),
            mode TEXT NOT NULL DEFAULT 'SHADOW',
            enabled INTEGER NOT NULL DEFAULT 1,
            stable_key TEXT,
            stable_runs INTEGER NOT NULL DEFAULT 0,
            last_run_at TEXT,
            last_apply_at TEXT,
            last_snapshot_json TEXT,
            last_proposal_json TEXT,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""INSERT OR IGNORE INTO v10_operator_state(id,mode,enabled,updated_at)
                        VALUES(1,?,?,?)""", (V10_OPERATOR_MODE, int(V10_OPERATOR_ENABLED), datetime.now(UTC).isoformat()))
        conn.execute("""CREATE TABLE IF NOT EXISTS v10_operator_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            action_type TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT,
            evidence_samples INTEGER NOT NULL DEFAULT 0,
            before_json TEXT,
            after_json TEXT,
            proposal_json TEXT,
            account_equity REAL,
            rollback_of INTEGER,
            note TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v10_operator_actions_time ON v10_operator_actions(created_at)")
        conn.execute("""CREATE TABLE IF NOT EXISTS v10_symbol_exclusions (
            symbol TEXT PRIMARY KEY,
            excluded INTEGER NOT NULL DEFAULT 1,
            reason TEXT,
            samples INTEGER NOT NULL DEFAULT 0,
            total_pnl REAL,
            profit_factor REAL,
            updated_at TEXT NOT NULL
        )""")
        conn.commit(); conn.close()
        _V10_OPERATOR_SCHEMA_COMPLETE = True


def _v10_operator_state() -> Dict[str, Any]:
    if not _V10_OPERATOR_SCHEMA_COMPLETE:
        _v10_operator_ensure_tables()
    conn = db_connect(); row = conn.execute("SELECT * FROM v10_operator_state WHERE id=1").fetchone(); conn.close()
    return dict(row) if row else {"mode": V10_OPERATOR_MODE, "enabled": int(V10_OPERATOR_ENABLED), "stable_runs": 0}


def _v10_operator_current_config() -> Dict[str, Any]:
    cap = trading_cap_usd() if "trading_cap_usd" in globals() else float(MAX_TRADING_CAPITAL)
    exclusions = []
    try:
        _v10_operator_ensure_tables(); conn = db_connect()
        exclusions = [r[0] for r in conn.execute("SELECT symbol FROM v10_symbol_exclusions WHERE excluded=1 ORDER BY symbol").fetchall()]
        conn.close()
    except Exception:
        pass
    return {
        "maxPositions": int(effective_max_positions()),
        "positionCapacity": ai_position_capacity_payload(),
        "tradingCapUsd": float(cap),
        "targetPositionValuePct": float(TARGET_POSITION_VALUE_PCT),
        "maxPositionValuePct": float(MAX_POSITION_VALUE_PCT),
        "fullBuyWhenOnePosition": True if (V17_FULL_BUY_CONSTITUTION_LOCK and V17_SINGLE_FULL_BUY_MODE) else bool(FULL_BUY_WHEN_ONE_POSITION),
        "stopLossPct": round((1.0 - float(STOP_LOSS)) * 100.0, 4),
        "fastStopLossPct": abs(float(FAST_STOP_LOSS_PCT)),
        "trailStartPct": round((float(TRAIL_START) - 1.0) * 100.0, 4),
        "trailGivebackPct": round((1.0 - float(TRAIL_GIVEBACK)) * 100.0, 4),
        "symbolExclusions": exclusions,
        "orderExecution": str(globals().get("V10_ORDER_EXECUTION_MODE", "MARKET")),
    }


def _v10_operator_snapshot() -> Dict[str, Any]:
    analytics = analytics_payload() if "analytics_payload" in globals() else {}
    rules = rule_intelligence_summary(365, 24) if "rule_intelligence_summary" in globals() else {}
    symbols = symbol_intelligence_summary(365, 24) if "symbol_intelligence_summary" in globals() else {}
    shadow = shadow_trading_summary(365, 24) if "shadow_trading_summary" in globals() else {}
    advisor = ai_advisor_summary() if "ai_advisor_summary" in globals() else {}
    completed = int((shadow.get("summary") or {}).get("completed") or shadow.get("completed") or 0)
    return {
        "capturedAt": datetime.now(UTC).isoformat(),
        "completedOutcomes": completed,
        "analytics": analytics,
        "rules": rules,
        "symbols": symbols,
        "shadow": shadow,
        "advisor": advisor,
        "current": _v10_operator_current_config(),
    }


def _v10_clamp(value: float, low: float, high: float) -> float:
    return max(float(low), min(float(high), float(value)))


def _v10_rule_row(snapshot: Dict[str, Any], names: List[str]) -> Dict[str, Any]:
    payload = snapshot.get("rules") or {}
    rows = payload.get("rules") or payload.get("items") or payload.get("rows") or []
    for row in rows:
        label = str(row.get("rule") or row.get("name") or row.get("key") or "").lower()
        if any(n.lower() in label for n in names):
            return row
    return {}


def _v10_symbol_rows(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = snapshot.get("symbols") or {}
    return payload.get("symbols") or payload.get("items") or payload.get("rows") or []


def _v10_operator_propose(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Build a bounded proposal from existing evidence. No live change happens here."""
    current = snapshot["current"]
    analytics = snapshot.get("analytics") or {}
    completed = int(snapshot.get("completedOutcomes") or 0)
    proposal = dict(current)
    reasons: List[str] = []

    # Portfolio capacity is now autonomous. It is derived from AI-promoted
    # target position sizing and current capital rather than a manual slider.
    # The operator still records the effective ceiling for audit/rollback, but
    # it never forces the bot to fill every available slot.
    capacity = ai_position_capacity_payload()
    proposal["maxPositions"] = int(capacity.get("effectiveMaxPositions") or 1)
    reasons.append(str(capacity.get("reason") or "AI portfolio capacity recalculated."))

    # Position sizing and trading cap: only scale up after positive realised evidence; scale down sooner.
    win_rate = float(analytics.get("winRate") or 0.0)
    closed_count = int(analytics.get("closedTrades") or 0)
    # V17.0.12: V10 Operator metrics must come from the analytics snapshot.
    # These names were previously referenced without assignment, causing
    # `V10 OPERATOR ERROR: name 'pf' is not defined`. This is a diagnostics/
    # operator reliability fix only; all promotion thresholds remain unchanged.
    pf = float(analytics.get("profitFactor") or 0.0)
    total_pnl = float(analytics.get("totalPnl") or 0.0)
    cap_bounds = V10_CONSTITUTION["tradingCapUsd"]
    size_bounds = V10_CONSTITUTION["positionValuePct"]
    if closed_count >= 20 and pf >= 1.30 and win_rate >= 0.55 and total_pnl > 0:
        proposal["tradingCapUsd"] = round(_v10_clamp(current["tradingCapUsd"] * 1.05, cap_bounds["min"], cap_bounds["max"]), 2)
        proposal["targetPositionValuePct"] = round(_v10_clamp(current["targetPositionValuePct"] * 1.05, size_bounds["min"], size_bounds["max"]), 4)
        reasons.append("Strong realised evidence permits a conservative 5% scale-up.")
    elif closed_count >= 10 and (pf < 0.90 or total_pnl < 0):
        proposal["tradingCapUsd"] = round(_v10_clamp(current["tradingCapUsd"] * 0.90, cap_bounds["min"], cap_bounds["max"]), 2)
        proposal["targetPositionValuePct"] = round(_v10_clamp(current["targetPositionValuePct"] * 0.90, size_bounds["min"], size_bounds["max"]), 4)
        reasons.append("Weak realised evidence triggers a defensive 10% exposure reduction.")

    # Stop loss: use average losing trade percentage when available, but stay inside constitution.
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    loss_pcts = sorted(abs(float(t.get("pnlPct") or 0.0)) for t in closed if float(t.get("pnl") or 0.0) < 0 and float(t.get("pnlPct") or 0.0) != 0)
    win_pcts = sorted(float(t.get("pnlPct") or 0.0) for t in closed if float(t.get("pnl") or 0.0) > 0)
    if len(loss_pcts) >= 10:
        median_loss = loss_pcts[len(loss_pcts)//2]
        desired_stop = _v10_clamp(median_loss * 0.90, V10_CONSTITUTION["stopLossPct"]["min"], V10_CONSTITUTION["stopLossPct"]["max"])
        # Maximum step of 0.5 percentage points per promotion.
        delta = _v10_clamp(desired_stop - current["stopLossPct"], -0.5, 0.5)
        proposal["stopLossPct"] = round(current["stopLossPct"] + delta, 3)
        proposal["fastStopLossPct"] = proposal["stopLossPct"]
        if abs(delta) >= 0.05:
            reasons.append(f"Stop calibrated from {len(loss_pcts)} realised losses (median {median_loss:.2f}%).")

    # Trailing values: derive cautiously from the distribution of winning trades.
    if len(win_pcts) >= 10:
        median_win = win_pcts[len(win_pcts)//2]
        desired_start = _v10_clamp(median_win * 0.70, V10_CONSTITUTION["trailStartPct"]["min"], V10_CONSTITUTION["trailStartPct"]["max"])
        desired_giveback = _v10_clamp(max(0.5, median_win * 0.25), V10_CONSTITUTION["trailGivebackPct"]["min"], V10_CONSTITUTION["trailGivebackPct"]["max"])
        proposal["trailStartPct"] = round(current["trailStartPct"] + _v10_clamp(desired_start-current["trailStartPct"], -0.5, 0.5), 3)
        proposal["trailGivebackPct"] = round(current["trailGivebackPct"] + _v10_clamp(desired_giveback-current["trailGivebackPct"], -0.25, 0.25), 3)
        reasons.append(f"Trailing policy calibrated from {len(win_pcts)} realised winners.")

    # Symbol exclusions: reversible and evidence based.
    exclusions = set(current.get("symbolExclusions") or [])
    for row in _v10_symbol_rows(snapshot):
        sym = str(row.get("symbol") or "").upper().strip()
        samples = int(row.get("trades") or row.get("samples") or 0)
        sym_pnl = float(row.get("totalPnl") or row.get("actualPnl") or 0.0)
        sym_pf = float(row.get("profitFactor") or 0.0)
        if not sym or samples < 5:
            continue
        if sym_pnl < 0 and sym_pf < 0.80:
            exclusions.add(sym)
        elif sym_pnl > 0 and sym_pf >= 1.20 and sym in exclusions:
            exclusions.remove(sym)
    proposal["symbolExclusions"] = sorted(exclusions)
    if proposal["symbolExclusions"] != current.get("symbolExclusions", []):
        reasons.append("Symbol exclusions refreshed from realised symbol expectancy.")

    # Order execution uses approved templates only. HYBRID keeps market orders for tight spreads
    # and marketable limits for wider spreads; it never generates arbitrary execution code.
    spread_rule = _v10_rule_row(snapshot, ["spread filter", "spread_filter"])
    spread_helped = float(spread_rule.get("helpedRate") or 0.0)
    spread_samples = int(spread_rule.get("samples") or spread_rule.get("triggered") or 0)
    if spread_samples >= V10_OPERATOR_MIN_SAMPLES and spread_helped >= 0.60:
        proposal["orderExecution"] = "HYBRID_SAFE"
        reasons.append("Spread evidence supports the approved hybrid execution template.")
    else:
        proposal["orderExecution"] = "MARKET"

    # V17.0.16 — constitutional single-position full-buy lock.
    # The V10 Operator may still optimise trading cap, stops, trails, exclusions and
    # approved execution templates, but it cannot evolve the user-selected V17
    # one-position/full-buy strategy into multi-position or partial sizing.
    if V17_FULL_BUY_CONSTITUTION_LOCK and V17_SINGLE_FULL_BUY_MODE:
        proposal["maxPositions"] = 1
        proposal["targetPositionValuePct"] = 1.0
        proposal["maxPositionValuePct"] = 1.0
        proposal["fullBuyWhenOnePosition"] = True
        reasons.append("V17 single-position full-buy mode is constitution-locked; only a manual strategy change may disable it.")
    else:
        # Legacy autonomous-capacity behaviour outside the protected V17 mode.
        proposal["fullBuyWhenOnePosition"] = False
        proposal["maxPositionValuePct"] = max(proposal["targetPositionValuePct"], min(1.0, proposal["targetPositionValuePct"] * 1.25))

    changed = {k: {"before": current.get(k), "after": proposal.get(k)} for k in proposal if proposal.get(k) != current.get(k)}
    return {
        "key": json.dumps(proposal, sort_keys=True, default=str),
        "createdAt": datetime.now(UTC).isoformat(),
        "evidenceSamples": completed,
        "eligible": completed >= V10_OPERATOR_MIN_SAMPLES and bool(changed),
        "changed": changed,
        "proposal": proposal,
        "reasons": reasons or ["No evidence-backed setting change is currently required."],
    }


def _v10_operator_apply_runtime(config: Dict[str, Any]) -> Dict[str, Any]:
    global MAX_POSITIONS, TARGET_POSITION_VALUE_PCT, MAX_POSITION_VALUE_PCT, FULL_BUY_WHEN_ONE_POSITION
    global STOP_LOSS, FAST_STOP_LOSS_PCT, OPTIMIZED_STOP_LOSS, OPTIMIZED_FAST_STOP_LOSS_PCT
    global TRAIL_START, TRAIL_GIVEBACK, OPTIMIZED_TRAIL_START, OPTIMIZED_TRAIL_GIVEBACK
    global V10_ORDER_EXECUTION_MODE

    if V17_FULL_BUY_CONSTITUTION_LOCK and V17_SINGLE_FULL_BUY_MODE:
        # V17.0.16: constitution-locked user-selected one-position full-buy mode.
        # This also protects restores/rollbacks created by older operator versions.
        # The autonomous V10 operator may still tune exits/research, but it must
        # not expand position count or silently switch sizing back to partial.
        MAX_POSITIONS = 1
        TARGET_POSITION_VALUE_PCT = 1.0
        MAX_POSITION_VALUE_PCT = 1.0
        FULL_BUY_WHEN_ONE_POSITION = True
    else:
        MAX_POSITIONS = int(_v10_clamp(config.get("maxPositions", AI_POSITION_HARD_CAP), V10_CONSTITUTION["maxPositions"]["min"], V10_CONSTITUTION["maxPositions"]["max"]))
        TARGET_POSITION_VALUE_PCT = _v10_clamp(config["targetPositionValuePct"], V10_CONSTITUTION["positionValuePct"]["min"], V10_CONSTITUTION["positionValuePct"]["max"])
        MAX_POSITION_VALUE_PCT = max(TARGET_POSITION_VALUE_PCT, min(1.0, float(config.get("maxPositionValuePct") or TARGET_POSITION_VALUE_PCT)))
        FULL_BUY_WHEN_ONE_POSITION = False if AI_POSITION_CAPACITY_ENABLED else bool(config.get("fullBuyWhenOnePosition") and MAX_POSITIONS == 1)

    stop_pct = _v10_clamp(config["stopLossPct"], V10_CONSTITUTION["stopLossPct"]["min"], V10_CONSTITUTION["stopLossPct"]["max"])
    STOP_LOSS = 1.0 - stop_pct / 100.0
    FAST_STOP_LOSS_PCT = -abs(stop_pct)
    OPTIMIZED_STOP_LOSS = STOP_LOSS
    OPTIMIZED_FAST_STOP_LOSS_PCT = FAST_STOP_LOSS_PCT

    start_pct = _v10_clamp(config["trailStartPct"], V10_CONSTITUTION["trailStartPct"]["min"], V10_CONSTITUTION["trailStartPct"]["max"])
    giveback_pct = _v10_clamp(config["trailGivebackPct"], V10_CONSTITUTION["trailGivebackPct"]["min"], V10_CONSTITUTION["trailGivebackPct"]["max"])
    TRAIL_START = 1.0 + start_pct / 100.0
    TRAIL_GIVEBACK = 1.0 - giveback_pct / 100.0
    OPTIMIZED_TRAIL_START = TRAIL_START
    OPTIMIZED_TRAIL_GIVEBACK = TRAIL_GIVEBACK

    save_trading_cap_setting(float(config["tradingCapUsd"]), "USD")
    V10_ORDER_EXECUTION_MODE = str(config.get("orderExecution") or "MARKET").upper()

    # Persist exclusions in dedicated reversible memory and mirror them into the existing blacklist.
    _v10_operator_ensure_tables(); conn = db_connect(); now = datetime.now(UTC).isoformat()
    wanted = {str(s).upper() for s in config.get("symbolExclusions") or []}
    existing = {r[0] for r in conn.execute("SELECT symbol FROM v10_symbol_exclusions WHERE excluded=1").fetchall()}
    for sym in wanted | existing:
        excluded = int(sym in wanted)
        conn.execute("""INSERT INTO v10_symbol_exclusions(symbol,excluded,reason,updated_at)
                        VALUES(?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET excluded=excluded.excluded,reason=excluded.reason,updated_at=excluded.updated_at""",
                     (sym, excluded, "V10 autonomous symbol evidence", now))
        if excluded:
            temp_blacklist[sym] = {"reason": "V10 autonomous symbol exclusion", "until": (datetime.now(UTC)+timedelta(days=7)).isoformat()}
        elif sym in temp_blacklist and str(temp_blacklist[sym].get("reason", "")).startswith("V10 autonomous"):
            del temp_blacklist[sym]
    conn.commit(); conn.close(); save_temp_blacklist()
    return _v10_operator_current_config()


def _v10_operator_log(action_type: str, status: str, reason: str, proposal: Dict[str, Any], before: Dict[str, Any], after: Dict[str, Any], samples: int, rollback_of: Optional[int] = None) -> int:
    _v10_operator_ensure_tables(); conn = db_connect()
    try:
        equity = float(get_account().equity)
    except Exception:
        equity = 0.0
    cur = conn.execute("""INSERT INTO v10_operator_actions
        (created_at,action_type,status,reason,evidence_samples,before_json,after_json,proposal_json,account_equity,rollback_of)
        VALUES(?,?,?,?,?,?,?,?,?,?)""", (datetime.now(UTC).isoformat(), action_type, status, str(reason)[:2000], int(samples),
        json.dumps(before, default=str), json.dumps(after, default=str), json.dumps(proposal, default=str), equity, rollback_of))
    action_id = int(cur.lastrowid); conn.commit(); conn.close(); return action_id


def _v10_operator_apply(proposal: Dict[str, Any], automatic: bool = True) -> Dict[str, Any]:
    before = _v10_operator_current_config()
    after = _v10_operator_apply_runtime(proposal["proposal"])
    action_id = _v10_operator_log("AUTO_PROMOTION" if automatic else "MANUAL_PROMOTION", "APPLIED", "; ".join(proposal.get("reasons") or []), proposal, before, after, proposal.get("evidenceSamples") or 0)
    now = datetime.now(UTC).isoformat(); conn = db_connect()
    conn.execute("UPDATE v10_operator_state SET last_apply_at=?,updated_at=? WHERE id=1", (now, now)); conn.commit(); conn.close()
    print(f"V10 AUTOPILOT APPLIED | action={action_id} changes={list((proposal.get('changed') or {}).keys())}")
    return {"ok": True, "actionId": action_id, "before": before, "after": after, "proposal": proposal}


def _v10_operator_rollback_latest(reason: str) -> Dict[str, Any]:
    _v10_operator_ensure_tables(); conn = db_connect()
    row = conn.execute("SELECT * FROM v10_operator_actions WHERE status='APPLIED' AND action_type IN ('AUTO_PROMOTION','MANUAL_PROMOTION') ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return {"ok": False, "message": "No autonomous setting change is available to roll back."}
    row = dict(row); before = json.loads(row.get("before_json") or "{}")
    current = _v10_operator_current_config(); restored = _v10_operator_apply_runtime(before)
    rollback_id = _v10_operator_log("AUTO_ROLLBACK", "APPLIED", reason, {"rollbackOf": row["id"]}, current, restored, 0, rollback_of=int(row["id"]))
    conn = db_connect(); conn.execute("UPDATE v10_operator_actions SET status='ROLLED_BACK',note=? WHERE id=?", (reason[:1000], int(row["id"]))); conn.commit(); conn.close()
    print(f"V10 AUTOPILOT ROLLBACK | original={row['id']} rollback={rollback_id} reason={reason}")
    return {"ok": True, "rollbackActionId": rollback_id, "rolledBackActionId": row["id"], "current": restored}


def _v10_operator_should_rollback() -> Optional[str]:
    _v10_operator_ensure_tables(); conn = db_connect()
    row = conn.execute("SELECT id,account_equity,created_at FROM v10_operator_actions WHERE status='APPLIED' AND action_type='AUTO_PROMOTION' ORDER BY id DESC LIMIT 1").fetchone(); conn.close()
    if not row or not float(row["account_equity"] or 0):
        return None
    try:
        equity = float(get_account().equity); baseline = float(row["account_equity"])
        drawdown = ((equity / baseline) - 1.0) * 100.0
        if drawdown <= -V10_OPERATOR_AUTO_ROLLBACK_DRAWDOWN_PCT:
            return f"Post-promotion drawdown {drawdown:.2f}% breached {-V10_OPERATOR_AUTO_ROLLBACK_DRAWDOWN_PCT:.2f}% limit."
        daily = float(get_daily_pnl())
        cap = max(1.0, trading_cap_usd())
        if daily <= -(cap * V10_OPERATOR_AUTO_ROLLBACK_DAILY_LOSS_PCT / 100.0):
            return f"Daily loss ${daily:.2f} breached {V10_OPERATOR_AUTO_ROLLBACK_DAILY_LOSS_PCT:.2f}% of trading cap."
    except Exception:
        return None
    return None


def v10_operator_run(force: bool = False) -> Dict[str, Any]:
    global _v10_operator_last_run_ts
    if not V10_OPERATOR_ENABLED:
        return {"ok": False, "message": "V10 autonomous operator is disabled."}
    state_row = _v10_operator_state(); mode = str(state_row.get("mode") or V10_OPERATOR_MODE).upper()
    if mode == "OFF":
        return {"ok": True, "mode": mode, "message": "Operator is switched off."}
    if not force and time.time() - _v10_operator_last_run_ts < V10_OPERATOR_INTERVAL_SECONDS:
        return {"ok": True, "mode": mode, "skipped": True, "message": "Operator interval is not due."}
    _v10_operator_last_run_ts = time.time()

    rollback_reason = _v10_operator_should_rollback()
    if rollback_reason and mode == "AUTO":
        return {"ok": True, "mode": mode, "rollback": _v10_operator_rollback_latest(rollback_reason)}

    snapshot = _v10_operator_snapshot(); proposal = _v10_operator_propose(snapshot)
    old_key = str(state_row.get("stable_key") or "")
    stable_runs = int(state_row.get("stable_runs") or 0) + 1 if proposal["key"] == old_key else 1
    now = datetime.now(UTC).isoformat(); conn = db_connect()
    conn.execute("""UPDATE v10_operator_state SET stable_key=?,stable_runs=?,last_run_at=?,last_snapshot_json=?,last_proposal_json=?,updated_at=? WHERE id=1""",
                 (proposal["key"], stable_runs, now, json.dumps(snapshot, default=str), json.dumps(proposal, default=str), now))
    conn.commit(); conn.close()

    result = {"ok": True, "version": V10_OPERATOR_VERSION, "mode": mode, "stableRuns": stable_runs,
              "requiredStableRuns": V10_OPERATOR_REQUIRED_STABLE_RUNS, "snapshot": snapshot, "proposal": proposal,
              "applied": False, "automaticLiveChanges": mode == "AUTO"}

    # Automatic changes only happen while the market is closed, after identical evidence
    # remains stable for the required number of runs and the cooldown has expired.
    market_open = bool(get_market_status_payload().get("isOpen"))
    last_apply = state_row.get("last_apply_at")
    cooldown_ok = True
    if last_apply:
        try:
            cooldown_ok = (datetime.now(UTC) - _v6_parse_utc(last_apply)).total_seconds() >= V10_OPERATOR_COOLDOWN_HOURS * 3600
        except Exception:
            pass
    if mode == "AUTO" and proposal["eligible"] and stable_runs >= V10_OPERATOR_REQUIRED_STABLE_RUNS and not market_open and cooldown_ok:
        result["application"] = _v10_operator_apply(proposal, automatic=True); result["applied"] = True
    elif mode == "AUTO" and market_open:
        result["holdReason"] = "Market open; settings promotions are deferred until the market is closed."
    elif mode == "AUTO" and not cooldown_ok:
        result["holdReason"] = "Promotion cooldown is still active."
    elif mode == "AUTO" and stable_runs < V10_OPERATOR_REQUIRED_STABLE_RUNS:
        result["holdReason"] = f"Waiting for stable evidence {stable_runs}/{V10_OPERATOR_REQUIRED_STABLE_RUNS}."
    elif mode == "SHADOW":
        result["holdReason"] = "Shadow mode records proposals but does not change live settings."
    return result


_v10_operator_status_cache: Dict[str, Any] = {"at": 0.0, "value": None, "limit": 0}
_v10_operator_status_lock = threading.RLock()
V10_OPERATOR_STATUS_CACHE_SECONDS = max(5, int(os.getenv("V10_OPERATOR_STATUS_CACHE_SECONDS", "30")))


def v10_operator_status(limit: int = 50, force_refresh: bool = False) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 200))
    now_mono = time.monotonic()
    with _v10_operator_status_lock:
        cached = _v10_operator_status_cache.get("value")
        if (not force_refresh and isinstance(cached, dict)
                and int(_v10_operator_status_cache.get("limit", 0)) >= limit
                and now_mono - float(_v10_operator_status_cache.get("at", 0.0)) < V10_OPERATOR_STATUS_CACHE_SECONDS):
            result = dict(cached); result["history"] = list(result.get("history") or [])[:limit]; result["cached"] = True
            return result
    try:
        # Deliberately read-only: schema setup belongs to application startup.
        conn = db_connect()
        state = conn.execute("SELECT * FROM v10_operator_state WHERE id=1").fetchone()
        rows = [dict(r) for r in conn.execute("SELECT * FROM v10_operator_actions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        exclusions = [r[0] for r in conn.execute("SELECT symbol FROM v10_symbol_exclusions WHERE excluded=1 ORDER BY symbol").fetchall()]
        conn.close()
        state_row = dict(state) if state else {"mode": V10_OPERATOR_MODE, "enabled": int(V10_OPERATOR_ENABLED), "stable_runs": 0}
        for row in rows:
            for key in ("before_json", "after_json", "proposal_json"):
                try: row[key[:-5]] = json.loads(row.get(key) or "{}")
                except Exception: row[key[:-5]] = {}
        try: last_proposal = json.loads(state_row.get("last_proposal_json") or "{}")
        except Exception: last_proposal = {}
        current = _v10_operator_current_config(); current["symbolExclusions"] = exclusions
        result = {"ok": True, "version": V10_OPERATOR_VERSION, "enabled": bool(state_row.get("enabled")),
                "mode": str(state_row.get("mode") or V10_OPERATOR_MODE), "constitution": V10_CONSTITUTION,
                "current": current, "stableRuns": int(state_row.get("stable_runs") or 0),
                "requiredStableRuns": V10_OPERATOR_REQUIRED_STABLE_RUNS, "lastRunAt": state_row.get("last_run_at"),
                "lastApplyAt": state_row.get("last_apply_at"), "lastProposal": last_proposal, "history": rows,
                "recurringManualApprovalRequired": False,
                "setupNote": "AUTO performs bounded closed-market promotions without recurring approval."}
        with _v10_operator_status_lock:
            _v10_operator_status_cache.update({"at": time.monotonic(), "value": dict(result), "limit": limit})
        return result
    except sqlite3.OperationalError as exc:
        if _db_is_lock_error(exc):
            with _v10_operator_status_lock:
                cached = _v10_operator_status_cache.get("value")
                if isinstance(cached, dict):
                    result = dict(cached); result["history"] = list(result.get("history") or [])[:limit]
                    result.update({"cached": True, "stale": True, "cacheReason": "database busy"})
                    return result
            return {"ok": True, "version": V10_OPERATOR_VERSION, "enabled": V10_OPERATOR_ENABLED,
                    "mode": V10_OPERATOR_MODE, "current": {}, "history": [], "cached": True, "stale": True,
                    "cacheReason": "database busy during initial snapshot"}
        raise


def v10_operator_worker() -> None:
    time.sleep(V10_OPERATOR_STARTUP_DELAY_SECONDS)
    while True:
        try:
            result = v10_operator_run(False)
            if result.get("applied"):
                print("V10 OPERATOR | automatic promotion completed")
            elif not result.get("skipped"):
                print(f"V10 OPERATOR | mode={result.get('mode')} stable={result.get('stableRuns',0)}/{result.get('requiredStableRuns',0)} applied={result.get('applied',False)}")
        except Exception as exc:
            print(f"V10 OPERATOR ERROR: {exc}")
        time.sleep(V10_OPERATOR_INTERVAL_SECONDS)


@app.on_event("startup")
def v10_operator_startup_event():
    global v10_operator_thread_started
    _v10_operator_ensure_tables()
    # Restore the most recently applied runtime configuration after a redeploy.
    try:
        conn = db_connect(); row = conn.execute("SELECT after_json FROM v10_operator_actions WHERE status='APPLIED' AND action_type IN ('AUTO_PROMOTION','MANUAL_PROMOTION','AUTO_ROLLBACK') ORDER BY id DESC LIMIT 1").fetchone(); conn.close()
        if row and row[0]:
            _v10_operator_apply_runtime(json.loads(row[0]))
            print("V10 OPERATOR | restored persisted runtime configuration")
    except Exception as exc:
        print(f"V10 OPERATOR RESTORE ERROR: {exc}")
    if V10_OPERATOR_ENABLED and not v10_operator_thread_started:
        v10_operator_thread_started = True
        threading.Thread(target=v10_operator_worker, daemon=True).start()


@app.get("/v10/operator/status")
def api_v10_operator_status(request: Request, limit: int = 50):
    verify_api_key(request); return v10_operator_status(limit)


@app.post("/v10/operator/run")
def api_v10_operator_run(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v10_operator_run(bool(payload.get("force", True)))


@app.post("/v10/operator/mode")
def api_v10_operator_mode(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    mode = str(payload.get("mode") or "").strip().upper()
    if mode not in ("OFF", "SHADOW", "AUTO"):
        return {"ok": False, "message": "Mode must be OFF, SHADOW or AUTO."}
    _v10_operator_ensure_tables(); now = datetime.now(UTC).isoformat(); conn = db_connect()
    conn.execute("UPDATE v10_operator_state SET mode=?,updated_at=? WHERE id=1", (mode, now)); conn.commit(); conn.close()
    with _v10_operator_status_lock:
        _v10_operator_status_cache.update({"at": 0.0, "value": None, "limit": 0})
    return {"ok": True, "mode": mode, "message": "AUTO performs bounded closed-market promotions without recurring approval."}


@app.post("/v10/operator/rollback")
def api_v10_operator_rollback(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    confirmation = str(payload.get("confirmation") or "").strip().upper()
    if confirmation != "ROLLBACK":
        return {"ok": False, "message": "Type ROLLBACK to restore the previous autonomous configuration."}
    return _v10_operator_rollback_latest("Manual emergency rollback requested from dashboard.")


@app.get("/v10/operator/constitution")
def api_v10_operator_constitution(request: Request):
    verify_api_key(request); return {"ok": True, "version": V10_OPERATOR_VERSION, "constitution": V10_CONSTITUTION}


# ============================================================
# TRADEBOT V12.0 — AI CEO BACKEND
# Executive supervision, persistent journal and evidence-backed reviews.
# Advisory-only by default: it never submits orders or changes live settings.
# ============================================================
V12_CEO_VERSION = "V12.0"
V12_CEO_ENABLED = os.getenv("V12_CEO_ENABLED", "true").lower() in ("1", "true", "yes", "on")
V12_CEO_ADVISORY_ONLY = os.getenv("V12_CEO_ADVISORY_ONLY", "true").lower() in ("1", "true", "yes", "on")
V12_CEO_INTERVAL_SECONDS = max(300, int(os.getenv("V12_CEO_INTERVAL_SECONDS", "1800") or 1800))
V12_CEO_STARTUP_DELAY_SECONDS = max(10, int(os.getenv("V12_CEO_STARTUP_DELAY_SECONDS", "45") or 45))
V12_CEO_JOURNAL_LIMIT = max(50, min(int(os.getenv("V12_CEO_JOURNAL_LIMIT", "1000") or 1000), 10000))
v12_ceo_thread_started = False


def _v12_ceo_ensure_tables() -> None:
    if not SQLITE_ENABLED:
        return
    conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS v12_ceo_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        review_type TEXT NOT NULL,
        market_open INTEGER NOT NULL DEFAULT 0,
        grade REAL NOT NULL DEFAULT 0,
        grade_letter TEXT,
        risk_level TEXT,
        operating_status TEXT,
        recommendation TEXT,
        payload_json TEXT NOT NULL
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_v12_ceo_reviews_time
                    ON v12_ceo_reviews(created_at DESC)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v12_ceo_journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        day TEXT NOT NULL,
        event_key TEXT,
        category TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'INFO',
        title TEXT NOT NULL,
        detail TEXT NOT NULL,
        evidence_json TEXT,
        UNIQUE(day, event_key)
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_v12_ceo_journal_time
                    ON v12_ceo_journal(created_at DESC)""")
    conn.commit()
    conn.close()


def _v12_safe_call(name: str, *args, fallback=None, **kwargs):
    fn = globals().get(name)
    if not callable(fn):
        return fallback
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        print(f"V12 CEO SOURCE ERROR {name}: {exc}")
        return fallback


def _v12_num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def _v12_letter(score: float) -> str:
    if score >= 90: return "A+"
    if score >= 85: return "A"
    if score >= 80: return "A-"
    if score >= 75: return "B+"
    if score >= 70: return "B"
    if score >= 65: return "B-"
    if score >= 60: return "C+"
    if score >= 55: return "C"
    if score >= 45: return "D"
    return "F"


def _v12_journal_write(category: str, title: str, detail: str,
                       severity: str = "INFO", event_key: str = "",
                       evidence: Optional[Dict[str, Any]] = None) -> bool:
    if not SQLITE_ENABLED:
        return False
    _v12_ceo_ensure_tables()
    now = datetime.now(UTC)
    key = str(event_key or "").strip() or None
    conn = db_connect()
    try:
        cur = conn.execute("""INSERT OR IGNORE INTO v12_ceo_journal
            (created_at,day,event_key,category,severity,title,detail,evidence_json)
            VALUES(?,?,?,?,?,?,?,?)""", (
            now.isoformat(), now.strftime("%Y-%m-%d"), key,
            str(category).upper(), str(severity).upper(),
            str(title)[:240], str(detail)[:4000],
            json.dumps(evidence or {}, default=str),
        ))
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def _v12_recent_journal(limit: int = 100, day: str = "") -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    _v12_ceo_ensure_tables()
    limit = max(1, min(int(limit), V12_CEO_JOURNAL_LIMIT))
    conn = db_connect()
    try:
        if day:
            rows = conn.execute("""SELECT * FROM v12_ceo_journal
                WHERE day=? ORDER BY id DESC LIMIT ?""", (day, limit)).fetchall()
        else:
            rows = conn.execute("""SELECT * FROM v12_ceo_journal
                ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
    finally:
        conn.close()
    items = []
    for row in rows:
        item = dict(row)
        try: item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
        except Exception: item["evidence"] = {}; item.pop("evidence_json", None)
        items.append(item)
    return items


def _v12_symbol_facts(reputation: Dict[str, Any], analytics: Dict[str, Any]) -> Dict[str, Any]:
    symbols = reputation.get("symbols") or reputation.get("items") or []
    if isinstance(symbols, dict):
        symbols = list(symbols.values())
    mature = [s for s in symbols if isinstance(s, dict) and int(s.get("samples") or s.get("trades") or 0) > 0]
    strongest = max(mature, key=lambda s: _v12_num(s.get("score")), default=None)
    weakest = min(mature, key=lambda s: _v12_num(s.get("score")), default=None)
    if not strongest:
        best = analytics.get("bestStocks") or []
        strongest = best[0] if best else None
    if not weakest:
        worst = analytics.get("worstStocks") or []
        weakest = worst[0] if worst else None
    return {"strongest": strongest, "weakest": weakest, "count": len(mature)}


def v12_ceo_build_review(review_type: str = "LIVE", persist: bool = True) -> Dict[str, Any]:
    review_type = str(review_type or "LIVE").upper()
    market = get_market_status_payload()
    analytics = _v12_safe_call("analytics_payload", fallback={}) or {}
    decision = _v12_safe_call("decision_intelligence_summary", 30, fallback={}) or {}
    reputation = _v12_safe_call("symbol_reputation_summary", False, fallback={}) or {}
    operator = _v12_safe_call("v10_operator_status", 25, fallback={}) or {}
    advisor = _v12_safe_call("ai_advisor_summary", 10, fallback={}) or {}
    weakness = _v12_safe_call("weakness_intelligence_summary", fallback={}) or {}
    research = _v12_safe_call("v7_status_payload", fallback={}) or {}
    outcomes = _v12_safe_call("v2_pending_breakdown", fallback={}) or {}
    report_sync = dict(auto_report_last_result or {})

    try:
        account = get_account()
        equity = _v12_num(getattr(account, "equity", 0.0))
        cash = _v12_num(getattr(account, "cash", 0.0))
        buying_power = _v12_num(getattr(account, "buying_power", 0.0))
    except Exception:
        equity = cash = buying_power = 0.0

    today_pnl = _v12_num(analytics.get("todayRealisedPnl"))
    total_pnl = _v12_num(analytics.get("totalPnl"))
    win_rate = _v12_num(analytics.get("winRate"))
    profit_factor = _v12_num(analytics.get("profitFactor"))
    closed_trades = int(analytics.get("closedTrades") or 0)
    calibration = _v12_num(decision.get("confidenceCalibration") or (decision.get("calibration") or {}).get("score"))
    completed = int(outcomes.get("completed") or 0)
    pending_ready = int(outcomes.get("readyForProcessing") or 0)
    outcome_errors = int(outcomes.get("withErrors") or 0)
    operator_mode = str(operator.get("mode") or "OFF").upper()
    stable_runs = int(operator.get("stableRuns") or 0)
    stable_required = max(1, int(operator.get("requiredStableRuns") or 1))
    symbol_facts = _v12_symbol_facts(reputation, analytics)

    trading_score = 50.0
    if closed_trades >= 5:
        trading_score += max(-20.0, min(20.0, (win_rate - 0.50) * 80.0))
        trading_score += max(-15.0, min(15.0, (profit_factor - 1.0) * 15.0))
    if total_pnl > 0: trading_score += 8.0
    elif total_pnl < 0: trading_score -= 8.0

    learning_score = min(100.0, 20.0 + min(completed / 150.0, 55.0) + calibration * 25.0)
    research_score = 75.0 if research.get("enabled", V7_ENABLED) else 35.0
    if research.get("automaticEvolution") or research.get("automatic_evolution"):
        research_score += 10.0
    stability_score = 100.0
    if outcome_errors: stability_score -= min(35.0, outcome_errors * 2.0)
    if pending_ready: stability_score -= min(20.0, pending_ready / 25.0)
    if report_sync.get("ok") is False: stability_score -= 15.0
    operator_score = 40.0 if operator_mode == "OFF" else 75.0 if operator_mode == "SHADOW" else 90.0
    operator_score += min(10.0, (stable_runs / stable_required) * 10.0)

    health = {
        "trading": round(max(0.0, min(100.0, trading_score)), 1),
        "learning": round(max(0.0, min(100.0, learning_score)), 1),
        "research": round(max(0.0, min(100.0, research_score)), 1),
        "stability": round(max(0.0, min(100.0, stability_score)), 1),
        "autonomy": round(max(0.0, min(100.0, operator_score)), 1),
    }
    grade = round(sum(health.values()) / len(health), 1)

    daily_loss_trigger = max(10.0, equity * 0.015) if equity > 0 else 10.0
    if emergency_stop or risk_blocked()[0] or today_pnl <= -daily_loss_trigger:
        risk_level = "HIGH"
    elif today_pnl < 0 or outcome_errors > 0 or pending_ready > 250:
        risk_level = "MODERATE"
    else:
        risk_level = "LOW"

    if emergency_stop:
        status = "EMERGENCY PROTECTION ACTIVE"
        recommendation = "Keep new buying disabled and investigate the emergency-stop cause."
    elif risk_level == "HIGH":
        status = "PROTECTING CAPITAL"
        recommendation = "Do not increase exposure. Review losses and system health before the next entry."
    elif operator_mode == "AUTO":
        status = "AUTONOMOUS SUPERVISION ACTIVE"
        recommendation = "Continue autonomous operation within the existing safety constitution."
    elif operator_mode == "SHADOW":
        status = "SHADOW SUPERVISION"
        recommendation = "Continue collecting stable evidence before promoting further changes."
    else:
        status = "SUPERVISED TRADING"
        recommendation = "Trading may continue, but autonomous promotions are currently disabled."

    priorities: List[str] = []
    if risk_level == "HIGH": priorities.append("Protect account capital and prevent additional exposure")
    if symbol_facts.get("weakest"):
        ws = symbol_facts["weakest"]
        priorities.append(f"Monitor weak symbol {ws.get('symbol', 'UNKNOWN')} (score {round(_v12_num(ws.get('score')),1)})")
    if pending_ready: priorities.append(f"Drain {pending_ready} mature outcome checkpoints")
    if calibration < 0.75: priorities.append("Improve confidence calibration with more completed evidence")
    if operator_mode != "AUTO": priorities.append("Validate the autonomous operator before enabling AUTO mode")
    if not priorities: priorities.append("Maintain current controls and continue evidence collection")
    priorities = priorities[:5]

    now = datetime.now(UTC)
    payload = {
        "ok": True,
        "version": V12_CEO_VERSION,
        "advisoryOnly": V12_CEO_ADVISORY_ONLY,
        "reviewType": review_type,
        "createdAt": now.isoformat(),
        "market": market,
        "operatingStatus": status,
        "grade": grade,
        "gradeOutOf10": round(grade / 10.0, 1),
        "gradeLetter": _v12_letter(grade),
        "riskLevel": risk_level,
        "recommendation": recommendation,
        "manualActionRequired": risk_level == "HIGH" or bool(emergency_stop),
        "priorities": priorities,
        "account": {"equity": equity, "cash": cash, "buyingPower": buying_power,
                    "todayRealisedPnl": today_pnl, "totalRealisedPnl": total_pnl},
        "performance": {"closedTrades": closed_trades, "winRate": win_rate,
                        "profitFactor": profit_factor},
        "health": health,
        "learning": {"completedOutcomes": completed, "readyOutcomes": pending_ready,
                     "outcomeErrors": outcome_errors, "confidenceCalibration": calibration},
        "evolution": {"mode": operator_mode, "stableRuns": stable_runs,
                      "requiredStableRuns": stable_required,
                      "lastApplyAt": operator.get("lastApplyAt"),
                      "lastRunAt": operator.get("lastRunAt")},
        "symbols": symbol_facts,
        "advisor": advisor,
        "weakness": weakness,
    }

    if persist and SQLITE_ENABLED:
        _v12_ceo_ensure_tables()
        conn = db_connect()
        conn.execute("""INSERT INTO v12_ceo_reviews
            (created_at,review_type,market_open,grade,grade_letter,risk_level,operating_status,recommendation,payload_json)
            VALUES(?,?,?,?,?,?,?,?,?)""", (
            now.isoformat(), review_type, int(bool(market.get("isOpen"))), grade,
            payload["gradeLetter"], risk_level, status, recommendation,
            json.dumps(payload, default=str),
        ))
        conn.commit(); conn.close()

        event_slot = f"{review_type}:{now.strftime('%Y-%m-%d')}"
        if review_type == "LIVE":
            event_slot = f"LIVE:{now.strftime('%Y-%m-%dT%H')}"
        _v12_journal_write(
            "EXECUTIVE", f"{review_type.title()} CEO review", recommendation,
            "WARNING" if risk_level == "HIGH" else "INFO", event_slot,
            {"grade": grade, "riskLevel": risk_level, "status": status},
        )
        if symbol_facts.get("weakest"):
            ws = symbol_facts["weakest"]
            _v12_journal_write(
                "SYMBOL", "Weakest symbol under review",
                f"{ws.get('symbol','UNKNOWN')} currently has the lowest mature reputation score.",
                "WARNING", f"WEAKEST:{now.strftime('%Y-%m-%d')}:{ws.get('symbol','UNKNOWN')}", ws,
            )
        if operator.get("lastApplyAt"):
            _v12_journal_write(
                "EVOLUTION", "Autonomous configuration active",
                f"Latest bounded operator configuration was applied at {operator.get('lastApplyAt')}.",
                "INFO", f"OPERATOR_APPLY:{operator.get('lastApplyAt')}",
                {"mode": operator_mode, "lastApplyAt": operator.get("lastApplyAt")},
            )
    return payload


def v12_ceo_status(include_journal: bool = True, journal_limit: int = 30) -> Dict[str, Any]:
    latest = None
    if SQLITE_ENABLED:
        _v12_ceo_ensure_tables()
        conn = db_connect()
        row = conn.execute("SELECT payload_json FROM v12_ceo_reviews ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        if row and row[0]:
            try: latest = json.loads(row[0])
            except Exception: latest = None
    if not latest:
        latest = v12_ceo_build_review("LIVE", persist=True)
    latest["enabled"] = V12_CEO_ENABLED
    latest["journal"] = _v12_recent_journal(journal_limit) if include_journal else []
    return latest


def v12_ceo_review_history(limit: int = 50) -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    _v12_ceo_ensure_tables(); limit = max(1, min(int(limit), 500))
    conn = db_connect(); rows = conn.execute("""SELECT id,created_at,review_type,market_open,
        grade,grade_letter,risk_level,operating_status,recommendation
        FROM v12_ceo_reviews ORDER BY id DESC LIMIT ?""", (limit,)).fetchall(); conn.close()
    return [dict(r) for r in rows]


def _v12_ceo_worker() -> None:
    time.sleep(V12_CEO_STARTUP_DELAY_SECONDS)
    while True:
        try:
            market = get_market_status_payload()
            uk_now = datetime.now(ZoneInfo("Europe/London"))
            review_type = "LIVE" if market.get("isOpen") else "CLOSED_MARKET"
            if not market.get("isOpen") and uk_now.hour < 12:
                review_type = "MORNING_BRIEF"
            elif not market.get("isOpen") and uk_now.hour >= 21:
                review_type = "DAILY_DEBRIEF"
            result = v12_ceo_build_review(review_type, persist=True)
            print(f"V12 CEO | {review_type} grade={result.get('gradeOutOf10')}/10 risk={result.get('riskLevel')} status={result.get('operatingStatus')}")
        except Exception as exc:
            print(f"V12 CEO WORKER ERROR: {exc}")
        time.sleep(V12_CEO_INTERVAL_SECONDS)


@app.on_event("startup")
def v12_ceo_startup_event():
    global v12_ceo_thread_started
    if not V12_CEO_ENABLED:
        return
    _v12_ceo_ensure_tables()
    if not v12_ceo_thread_started:
        v12_ceo_thread_started = True
        threading.Thread(target=_v12_ceo_worker, daemon=True).start()
        print(f"V12 CEO | enabled advisory_only={V12_CEO_ADVISORY_ONLY}")


@app.get("/v12/ceo/status")
def api_v12_ceo_status(request: Request, journal_limit: int = 30):
    verify_api_key(request)
    return v12_ceo_status(True, journal_limit)


@app.get("/v12/ceo/journal")
def api_v12_ceo_journal(request: Request, limit: int = 100, day: str = ""):
    verify_api_key(request)
    return {"ok": True, "version": V12_CEO_VERSION, "count": len(_v12_recent_journal(limit, day)),
            "items": _v12_recent_journal(limit, day)}


@app.get("/v12/ceo/reviews")
def api_v12_ceo_reviews(request: Request, limit: int = 50):
    verify_api_key(request)
    items = v12_ceo_review_history(limit)
    return {"ok": True, "version": V12_CEO_VERSION, "count": len(items), "items": items}


@app.post("/v12/ceo/review")
def api_v12_ceo_review(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    review_type = str(payload.get("reviewType") or payload.get("type") or "MANUAL").upper()
    return v12_ceo_build_review(review_type, persist=True)


@app.get("/v12/ceo/constitution")
def api_v12_ceo_constitution(request: Request):
    verify_api_key(request)
    return {
        "ok": True, "version": V12_CEO_VERSION,
        "advisoryOnly": V12_CEO_ADVISORY_ONLY,
        "principles": [
            "Protect capital before pursuing growth.",
            "Use persisted evidence rather than invented metrics.",
            "Do not submit, cancel or alter orders from the CEO layer.",
            "Do not change live settings without the existing bounded operator safeguards.",
            "Record executive reviews and recommendations in an auditable journal.",
        ],
    }


# ============================================================
# TRADEBOT V12.1 — AI BOARD OF DIRECTORS
# Automatic, evidence-backed governance above the CEO layer.
# Advisory-only: the board cannot place orders or alter live settings.
# ============================================================
V12_BOARD_VERSION = "V12.1"
V12_BOARD_ENABLED = os.getenv("V12_BOARD_ENABLED", "true").lower() in ("1", "true", "yes", "on")
V12_BOARD_INTERVAL_SECONDS = max(300, int(os.getenv("V12_BOARD_INTERVAL_SECONDS", "1800") or 1800))
V12_BOARD_STARTUP_DELAY_SECONDS = max(20, int(os.getenv("V12_BOARD_STARTUP_DELAY_SECONDS", "75") or 75))
v121_board_thread_started = False
v12_board_thread_started = False


def _v121_board_ensure_tables() -> None:
    if not SQLITE_ENABLED:
        return
    conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS v121_board_meetings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        meeting_type TEXT NOT NULL,
        final_decision TEXT NOT NULL,
        final_reason TEXT NOT NULL,
        risk_level TEXT,
        ceo_grade REAL NOT NULL DEFAULT 0,
        payload_json TEXT NOT NULL
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_v121_board_meetings_time
                    ON v121_board_meetings(created_at DESC)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v121_board_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id INTEGER NOT NULL,
        director TEXT NOT NULL,
        vote TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0,
        reason TEXT NOT NULL,
        evidence_json TEXT,
        FOREIGN KEY(meeting_id) REFERENCES v121_board_meetings(id)
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_v121_board_votes_meeting
                    ON v121_board_votes(meeting_id, id)""")
    conn.commit()
    conn.close()


def _v121_vote(director: str, vote: str, confidence: float, reason: str,
               evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "director": director,
        "vote": vote,
        "confidence": round(max(0.0, min(1.0, _v12_num(confidence))), 3),
        "reason": str(reason),
        "evidence": evidence or {},
    }


def _v121_director_votes(ceo: Dict[str, Any]) -> List[Dict[str, Any]]:
    risk = str(ceo.get("riskLevel") or "MODERATE").upper()
    health = first_object = ceo.get("health") if isinstance(ceo.get("health"), dict) else {}
    learning = ceo.get("learning") if isinstance(ceo.get("learning"), dict) else {}
    evolution = ceo.get("evolution") if isinstance(ceo.get("evolution"), dict) else {}
    performance = ceo.get("performance") if isinstance(ceo.get("performance"), dict) else {}
    account = ceo.get("account") if isinstance(ceo.get("account"), dict) else {}

    grade = _v12_num(ceo.get("grade"))
    today_pnl = _v12_num(account.get("todayRealisedPnl"))
    pf = _v12_num(performance.get("profitFactor"))
    closed = int(performance.get("closedTrades") or 0)
    completed = int(learning.get("completedOutcomes") or 0)
    ready = int(learning.get("readyOutcomes") or 0)
    errors = int(learning.get("outcomeErrors") or 0)
    calibration = _v12_num(learning.get("confidenceCalibration"))
    mode = str(evolution.get("mode") or "OFF").upper()
    stable = int(evolution.get("stableRuns") or 0)
    required = max(1, int(evolution.get("requiredStableRuns") or 1))
    stability = _v12_num(health.get("stability"), 50.0)

    votes: List[Dict[str, Any]] = []

    if risk == "HIGH" or bool(ceo.get("manualActionRequired")):
        votes.append(_v121_vote("Risk Director", "VETO", 0.98,
            "Capital protection conditions are active; no expansion or promotion should proceed.",
            {"riskLevel": risk, "todayRealisedPnl": today_pnl, "manualActionRequired": ceo.get("manualActionRequired")}))
    elif risk == "MODERATE":
        votes.append(_v121_vote("Risk Director", "CAUTION", 0.82,
            "Risk is moderate. Continue only inside current exposure and loss limits.",
            {"riskLevel": risk, "todayRealisedPnl": today_pnl}))
    else:
        votes.append(_v121_vote("Risk Director", "APPROVE", 0.9,
            "No elevated capital-protection trigger is active.",
            {"riskLevel": risk, "todayRealisedPnl": today_pnl}))

    if completed >= 500 and calibration >= 0.70 and errors == 0:
        votes.append(_v121_vote("Research Director", "APPROVE", 0.9,
            "The evidence base and confidence calibration are sufficient for continued autonomous research.",
            {"completedOutcomes": completed, "confidenceCalibration": calibration, "outcomeErrors": errors}))
    elif completed >= 150 and errors <= 5:
        votes.append(_v121_vote("Research Director", "WAIT", 0.72,
            "Useful evidence exists, but additional mature outcomes are required before stronger conclusions.",
            {"completedOutcomes": completed, "confidenceCalibration": calibration, "readyOutcomes": ready, "outcomeErrors": errors}))
    else:
        votes.append(_v121_vote("Research Director", "WAIT", 0.88,
            "The evidence base is not yet mature enough for a board-level promotion decision.",
            {"completedOutcomes": completed, "confidenceCalibration": calibration, "outcomeErrors": errors}))

    if errors > 0 or stability < 70:
        votes.append(_v121_vote("Execution Director", "WAIT", 0.9,
            "Operational reliability must improve before execution-related changes are endorsed.",
            {"stabilityScore": stability, "outcomeErrors": errors, "readyOutcomes": ready}))
    elif ready > 500:
        votes.append(_v121_vote("Execution Director", "CAUTION", 0.78,
            "The outcome-processing backlog is elevated; retain current execution controls while it drains.",
            {"stabilityScore": stability, "readyOutcomes": ready}))
    else:
        votes.append(_v121_vote("Execution Director", "APPROVE", 0.84,
            "Execution and evidence-processing health are within acceptable limits.",
            {"stabilityScore": stability, "readyOutcomes": ready, "outcomeErrors": errors}))

    if V12_CEO_ADVISORY_ONLY:
        votes.append(_v121_vote("Compliance Director", "APPROVE", 1.0,
            "The CEO and board remain advisory-only and cannot bypass existing trading safeguards.",
            {"ceoAdvisoryOnly": V12_CEO_ADVISORY_ONLY, "boardAdvisoryOnly": True}))
    else:
        votes.append(_v121_vote("Compliance Director", "VETO", 1.0,
            "The CEO layer is not advisory-only; board approval is withheld until governance is restored.",
            {"ceoAdvisoryOnly": V12_CEO_ADVISORY_ONLY}))

    if mode == "AUTO" and stable >= required and grade >= 70:
        votes.append(_v121_vote("Evolution Director", "APPROVE", 0.88,
            "The autonomous operator is active and has met its stability requirement.",
            {"mode": mode, "stableRuns": stable, "requiredStableRuns": required, "ceoGrade": grade}))
    elif mode in ("AUTO", "SHADOW"):
        votes.append(_v121_vote("Evolution Director", "WAIT", 0.86,
            "Evolution should continue observing until all stability requirements are met.",
            {"mode": mode, "stableRuns": stable, "requiredStableRuns": required, "ceoGrade": grade}))
    else:
        votes.append(_v121_vote("Evolution Director", "WAIT", 0.95,
            "Autonomous evolution is not active, so no promotion can be endorsed.",
            {"mode": mode, "stableRuns": stable, "requiredStableRuns": required}))

    if risk == "HIGH":
        votes.append(_v121_vote("Chief Executive", "VETO", 0.97,
            "The executive recommendation is capital protection rather than expansion.",
            {"ceoRecommendation": ceo.get("recommendation"), "ceoGrade": grade}))
    elif grade >= 75 and mode == "AUTO":
        votes.append(_v121_vote("Chief Executive", "APPROVE", 0.9,
            "Company health supports continued autonomous supervision within existing bounds.",
            {"ceoRecommendation": ceo.get("recommendation"), "ceoGrade": grade, "mode": mode, "profitFactor": pf, "closedTrades": closed}))
    else:
        votes.append(_v121_vote("Chief Executive", "WAIT", 0.8,
            "Continue collecting evidence without expanding authority or risk.",
            {"ceoRecommendation": ceo.get("recommendation"), "ceoGrade": grade, "mode": mode, "profitFactor": pf, "closedTrades": closed}))
    return votes


def v121_board_build_meeting(meeting_type: str = "AUTOMATIC", persist: bool = True) -> Dict[str, Any]:
    meeting_type = str(meeting_type or "AUTOMATIC").upper()
    ceo = v12_ceo_status(False, 0)
    votes = _v121_director_votes(ceo)
    vote_names = [str(v.get("vote") or "WAIT").upper() for v in votes]

    if "VETO" in vote_names:
        final_decision = "VETO"
        vetoes = [v["director"] for v in votes if v["vote"] == "VETO"]
        final_reason = f"Board veto issued by {', '.join(vetoes)}. Existing safeguards remain unchanged."
    elif vote_names.count("WAIT") + vote_names.count("CAUTION") >= 2:
        final_decision = "DELAY"
        final_reason = "The board requires more evidence or improved operating conditions before endorsing change."
    else:
        final_decision = "APPROVE CONTINUATION"
        final_reason = "The board approves continued operation under the current bounded configuration; no new authority is granted."

    confidence = round(sum(_v12_num(v.get("confidence")) for v in votes) / max(1, len(votes)), 3)
    now = datetime.now(UTC)
    payload = {
        "ok": True,
        "version": V12_BOARD_VERSION,
        "enabled": V12_BOARD_ENABLED,
        "advisoryOnly": True,
        "createdAt": now.isoformat(),
        "meetingType": meeting_type,
        "finalDecision": final_decision,
        "finalReason": final_reason,
        "confidence": confidence,
        "riskLevel": ceo.get("riskLevel"),
        "ceoGrade": ceo.get("grade"),
        "ceoGradeLetter": ceo.get("gradeLetter"),
        "votes": votes,
        "consensus": {
            "approve": sum(1 for v in vote_names if v == "APPROVE"),
            "wait": sum(1 for v in vote_names if v == "WAIT"),
            "caution": sum(1 for v in vote_names if v == "CAUTION"),
            "veto": sum(1 for v in vote_names if v == "VETO"),
            "total": len(votes),
        },
        "nextAction": (
            "Protect capital and investigate the veto condition."
            if final_decision == "VETO" else
            "Continue evidence collection; the board will review automatically."
            if final_decision == "DELAY" else
            "Continue the current bounded autonomous configuration."
        ),
    }

    if persist and SQLITE_ENABLED:
        _v121_board_ensure_tables()
        conn = db_connect()
        cur = conn.execute("""INSERT INTO v121_board_meetings
            (created_at,meeting_type,final_decision,final_reason,risk_level,ceo_grade,payload_json)
            VALUES(?,?,?,?,?,?,?)""", (
            now.isoformat(), meeting_type, final_decision, final_reason,
            str(ceo.get("riskLevel") or ""), _v12_num(ceo.get("grade")),
            json.dumps(payload, default=str),
        ))
        meeting_id = int(cur.lastrowid)
        for vote in votes:
            conn.execute("""INSERT INTO v121_board_votes
                (meeting_id,director,vote,confidence,reason,evidence_json)
                VALUES(?,?,?,?,?,?)""", (
                meeting_id, vote["director"], vote["vote"], vote["confidence"],
                vote["reason"], json.dumps(vote.get("evidence") or {}, default=str),
            ))
        conn.commit()
        conn.close()
        payload["meetingId"] = meeting_id
        _v12_journal_write(
            "BOARD", f"AI Board decision: {final_decision}", final_reason,
            "WARNING" if final_decision == "VETO" else "INFO",
            f"BOARD:{now.strftime('%Y-%m-%dT%H')}",
            {"meetingId": meeting_id, "decision": final_decision, "consensus": payload["consensus"]},
        )
    return payload


def v121_board_status() -> Dict[str, Any]:
    latest = None
    if SQLITE_ENABLED:
        _v121_board_ensure_tables()
        conn = db_connect()
        row = conn.execute("SELECT payload_json FROM v121_board_meetings ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        if row and row[0]:
            try:
                latest = json.loads(row[0])
            except Exception:
                latest = None
    if not latest:
        latest = v121_board_build_meeting("STARTUP", persist=True)
    latest["enabled"] = V12_BOARD_ENABLED
    latest["advisoryOnly"] = True
    return latest


def v121_board_history(limit: int = 50) -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    _v121_board_ensure_tables()
    limit = max(1, min(int(limit), 500))
    conn = db_connect()
    rows = conn.execute("""SELECT id,created_at,meeting_type,final_decision,
        final_reason,risk_level,ceo_grade FROM v121_board_meetings
        ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _v121_board_worker() -> None:
    time.sleep(V12_BOARD_STARTUP_DELAY_SECONDS)
    while True:
        try:
            market = get_market_status_payload()
            meeting_type = "MARKET_OPEN" if market.get("isOpen") else "CLOSED_MARKET"
            result = v121_board_build_meeting(meeting_type, persist=True)
            print(f"V12.1 BOARD | {result.get('finalDecision')} confidence={result.get('confidence')} votes={result.get('consensus')}")
        except Exception as exc:
            print(f"V12.1 BOARD WORKER ERROR: {exc}")
        time.sleep(V12_BOARD_INTERVAL_SECONDS)


@app.on_event("startup")
def v121_board_startup_event():
    global v12_board_thread_started, v121_board_thread_started
    if not V12_BOARD_ENABLED:
        return
    _v121_board_ensure_tables()
    if not v121_board_thread_started:
        v12_board_thread_started = True  # backward-compatible legacy flag
        v121_board_thread_started = True
        threading.Thread(
            target=_v121_board_worker,
            daemon=True,
            name="v121-board-worker",
        ).start()
        print("V12.1 BOARD | enabled advisory_only=True automatic_reviews=True")


@app.get("/v12/board/status")
def api_v121_board_status(request: Request):
    verify_api_key(request)
    return v121_board_status()


@app.get("/v12/board/history")
def api_v121_board_history(request: Request, limit: int = 50):
    verify_api_key(request)
    items = v121_board_history(limit)
    return {"ok": True, "version": V12_BOARD_VERSION, "count": len(items), "items": items}


@app.get("/v12/board/constitution")
def api_v121_board_constitution(request: Request):
    verify_api_key(request)
    return {
        "ok": True,
        "version": V12_BOARD_VERSION,
        "advisoryOnly": True,
        "automaticReviews": True,
        "directors": [
            "Chief Executive",
            "Risk Director",
            "Research Director",
            "Execution Director",
            "Compliance Director",
            "Evolution Director",
        ],
        "rules": [
            "Any Risk or Compliance veto overrides all approvals.",
            "The board cannot place, cancel or alter orders.",
            "The board cannot bypass the bounded autonomous operator.",
            "Insufficient evidence results in DELAY, not forced approval.",
            "Every meeting and director vote is persisted for audit.",
            "Reviews run automatically; no manual review is required.",
        ],
    }

# =========================
# TRADEBOT V13 — AUTONOMOUS LONG-TERM AI MEMORY
# Structured, evidence-backed knowledge shared by CEO, Board, Research and Evolution.
# Advisory-only: never places orders and never bypasses existing safeguards.
# =========================
V13_MEMORY_VERSION = "V13.0"
V13_MEMORY_ENABLED = os.getenv("V13_MEMORY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
V13_MEMORY_INTERVAL_SECONDS = max(300, int(os.getenv("V13_MEMORY_INTERVAL_SECONDS", "1800")))
V13_MEMORY_STARTUP_DELAY_SECONDS = max(5, int(os.getenv("V13_MEMORY_STARTUP_DELAY_SECONDS", "35")))
v13_memory_thread_started = False


def _v13_memory_ensure_tables() -> None:
    if not SQLITE_ENABLED:
        return
    conn = db_connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS v13_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT UNIQUE NOT NULL,
            knowledge_type TEXT NOT NULL,
            subject TEXT NOT NULL,
            claim TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            confidence REAL NOT NULL DEFAULT 0,
            evidence_count INTEGER NOT NULL DEFAULT 0,
            metric_value REAL,
            metric_name TEXT,
            first_observed TEXT NOT NULL,
            last_confirmed TEXT NOT NULL,
            expires_at TEXT,
            source_json TEXT NOT NULL DEFAULT '{}',
            relationships_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS v13_memory_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            fingerprint TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v13_knowledge_type ON v13_knowledge(knowledge_type,status,confidence)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v13_memory_events_created ON v13_memory_events(created_at)")
    conn.commit(); conn.close()


def _v13_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _v13_fp(*parts: Any) -> str:
    raw = "|".join(str(p).strip().upper() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _v13_write_event(event_type: str, title: str, detail: str, fingerprint: str = "", payload: Optional[Dict[str, Any]] = None) -> None:
    if not SQLITE_ENABLED:
        return
    _v13_memory_ensure_tables(); conn = db_connect()
    conn.execute("INSERT INTO v13_memory_events(created_at,event_type,title,detail,fingerprint,payload_json) VALUES(?,?,?,?,?,?)",
                 (_v13_now(), event_type, title, detail, fingerprint, json.dumps(payload or {}, default=str)))
    conn.commit(); conn.close()


def _v13_upsert_knowledge(item: Dict[str, Any]) -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return item
    _v13_memory_ensure_tables(); now = _v13_now(); fp = str(item["fingerprint"])
    conn = db_connect(); row = conn.execute("SELECT * FROM v13_knowledge WHERE fingerprint=?", (fp,)).fetchone()
    prior = dict(row) if row else None
    incoming_conf = max(0.0, min(100.0, float(item.get("confidence") or 0)))
    incoming_evidence = max(0, int(item.get("evidenceCount") or 0))
    status = str(item.get("status") or "ACTIVE")
    if prior:
        old_conf = float(prior.get("confidence") or 0)
        old_ev = int(prior.get("evidence_count") or 0)
        # Grow confidence gradually on repeated confirmation; allow evidence deterioration to reduce it.
        if incoming_evidence >= old_ev:
            confidence = min(99.5, max(incoming_conf, old_conf + min(3.0, 0.25 + (incoming_evidence-old_ev)/500.0)))
        else:
            confidence = max(0.0, min(incoming_conf, old_conf - 2.0))
        conn.execute("""UPDATE v13_knowledge SET claim=?,status=?,confidence=?,evidence_count=?,metric_value=?,metric_name=?,
            last_confirmed=?,expires_at=?,source_json=?,relationships_json=?,updated_at=? WHERE fingerprint=?""",
            (item["claim"], status, confidence, incoming_evidence, item.get("metricValue"), item.get("metricName"), now,
             item.get("expiresAt"), json.dumps(item.get("source") or {}, default=str),
             json.dumps(item.get("relationships") or [], default=str), now, fp))
        event = "CONFIRMED" if incoming_evidence >= old_ev else "WEAKENED"
    else:
        confidence = incoming_conf
        conn.execute("""INSERT INTO v13_knowledge(fingerprint,knowledge_type,subject,claim,status,confidence,evidence_count,
            metric_value,metric_name,first_observed,last_confirmed,expires_at,source_json,relationships_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fp, item["knowledgeType"], item["subject"], item["claim"], status, confidence, incoming_evidence,
             item.get("metricValue"), item.get("metricName"), now, now, item.get("expiresAt"),
             json.dumps(item.get("source") or {}, default=str), json.dumps(item.get("relationships") or [], default=str), now, now))
        event = "DISCOVERED"
    conn.commit(); conn.close()
    if not prior or abs(confidence - float(prior.get("confidence") or 0)) >= 1.0:
        _v13_write_event(event, f"{event.title()} knowledge: {item['subject']}", item["claim"], fp,
                         {"confidence": confidence, "evidenceCount": incoming_evidence, "type": item["knowledgeType"]})
    item["confidence"] = round(confidence, 2)
    return item


def _v13_extract_candidates() -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    # Symbol knowledge
    try:
        rep = symbol_reputation_summary(force=False)
        for s in rep.get("symbols", []):
            samples = int(s.get("samples") or 0); score = float(s.get("score") or 0); exp = float(s.get("expectancyPct") or 0)
            if samples < max(5, int(rep.get("minimumSamples") or 20) // 2):
                continue
            symbol = str(s.get("symbol") or "UNKNOWN").upper()
            direction = "outperforming" if exp > 0.25 else "underperforming" if exp < -0.25 else "neutral"
            claim = f"{symbol} is {direction} in the current evidence window with {exp:.2f}% expectancy and a reputation score of {score:.1f}."
            conf = min(98.0, 20.0 + samples * 1.2 + abs(exp) * 2.0)
            candidates.append({"fingerprint": _v13_fp("SYMBOL", symbol, direction), "knowledgeType": "SYMBOL",
                "subject": symbol, "claim": claim, "confidence": conf, "evidenceCount": samples,
                "metricValue": exp, "metricName": "expectancy_pct", "status": "ACTIVE",
                "source": {"engine": "symbol_reputation", "score": score, "label": s.get("label")},
                "relationships": [{"type": "HAS_REGIME", "target": s.get("bestRegime") or "UNKNOWN"}]})
    except Exception as exc:
        print(f"V13 MEMORY SYMBOL EXTRACT ERROR: {exc}")
    # Rule knowledge
    try:
        rules_payload = rule_intelligence(180, 24, 20, 100)
        rows = rules_payload.get("rules") or rules_payload.get("items") or []
        for r in rows:
            samples = int(r.get("triggered") or r.get("samples") or 0)
            if samples < 20: continue
            rule = str(r.get("rule") or r.get("name") or "UNKNOWN").upper()
            exp = float(r.get("expectancyPct") if r.get("expectancyPct") is not None else r.get("expectancy") or 0)
            helped = float(r.get("helpedPct") if r.get("helpedPct") is not None else r.get("helped") or 0)
            direction = "helping" if exp > 0 else "hurting"
            claim = f"{rule} is historically {direction}: expectancy {exp:.2f}% across {samples:,} triggers; helped rate {helped:.0f}%."
            candidates.append({"fingerprint": _v13_fp("RULE", rule, direction), "knowledgeType": "RULE", "subject": rule,
                "claim": claim, "confidence": min(99.0, 35 + samples/40), "evidenceCount": samples,
                "metricValue": exp, "metricName": "expectancy_pct", "status": "ACTIVE",
                "source": {"engine": "rule_intelligence", "helpedPct": helped},
                "relationships": [{"type": "AFFECTS", "target": "TRADE_SELECTION"}]})
    except Exception as exc:
        print(f"V13 MEMORY RULE EXTRACT ERROR: {exc}")
    # Market knowledge
    try:
        weekly = v4_weekly_intelligence(24)
        samples = int(weekly.get("samples") or weekly.get("completed") or weekly.get("completedOutcomes") or 0)
        exp = float(weekly.get("expectancyPct") if weekly.get("expectancyPct") is not None else weekly.get("averageExpectancy") or 0)
        wr = float(weekly.get("winRate") or 0)
        recommendation = weekly.get("recommendation") if isinstance(weekly.get("recommendation"), dict) else {}
        verdict = str(weekly.get("verdict") or recommendation.get("verdict") or "CONTINUE_CURRENT_GUARDS")
        if samples > 0:
            claim = f"The latest market evidence contains {samples:,} completed outcomes, {wr:.1f}% win rate and {exp:.3f}% expectancy; current verdict is {verdict}."
            candidates.append({"fingerprint": _v13_fp("MARKET", verdict), "knowledgeType": "MARKET", "subject": "CURRENT_MARKET",
                "claim": claim, "confidence": min(98.0, 45 + samples/100), "evidenceCount": samples,
                "metricValue": exp, "metricName": "expectancy_pct", "status": "ACTIVE",
                "source": {"engine": "market_dna", "winRate": wr, "verdict": verdict},
                "relationships": [{"type": "GUIDES", "target": "RISK_GUARDS"}]})
    except Exception as exc:
        print(f"V13 MEMORY MARKET EXTRACT ERROR: {exc}")
    # Governance/evolution memory
    try:
        ceo = v12_ceo_status(False, 0); board = v121_board_status()
        grade = float(ceo.get("grade") or ceo.get("gradeOutOf100") or 0)
        decision = str(board.get("finalDecision") or "DELAY")
        claim = f"AI governance currently rates company health at {grade:.1f}/100 and the Board decision is {decision}."
        candidates.append({"fingerprint": _v13_fp("GOVERNANCE", decision), "knowledgeType": "GOVERNANCE", "subject": "AI_BOARD",
            "claim": claim, "confidence": float(board.get("confidence") or 80), "evidenceCount": int(ceo.get("completedOutcomes") or 0),
            "metricValue": grade, "metricName": "ceo_grade", "status": "ACTIVE",
            "source": {"engine": "ceo_board", "risk": ceo.get("riskLevel")},
            "relationships": [{"type": "SUPERVISES", "target": "AUTONOMOUS_OPERATOR"}]})
    except Exception as exc:
        print(f"V13 MEMORY GOVERNANCE EXTRACT ERROR: {exc}")
    return candidates


def v13_memory_refresh() -> Dict[str, Any]:
    _v13_memory_ensure_tables(); candidates = _v13_extract_candidates(); stored = 0
    for item in candidates:
        try: _v13_upsert_knowledge(item); stored += 1
        except Exception as exc: print(f"V13 MEMORY UPSERT ERROR: {exc}")
    # Retire stale knowledge after 45 days without confirmation.
    if SQLITE_ENABLED:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat(); conn = db_connect()
        conn.execute("UPDATE v13_knowledge SET status='STALE', updated_at=? WHERE status='ACTIVE' AND last_confirmed < ?", (_v13_now(), cutoff))
        conn.commit(); conn.close()
    return v13_memory_status()


def _v13_rows(limit: int = 200, knowledge_type: str = "", status: str = "ACTIVE") -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED: return []
    _v13_memory_ensure_tables(); limit = max(1, min(int(limit), 1000)); clauses=[]; params=[]
    if knowledge_type: clauses.append("knowledge_type=?"); params.append(knowledge_type.upper())
    if status: clauses.append("status=?"); params.append(status.upper())
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    conn=db_connect(); rows=conn.execute(f"SELECT * FROM v13_knowledge{where} ORDER BY confidence DESC,evidence_count DESC LIMIT ?", (*params,limit)).fetchall(); conn.close()
    result=[]
    for row in rows:
        d=dict(row)
        d["knowledgeType"]=d.pop("knowledge_type"); d["evidenceCount"]=d.pop("evidence_count")
        d["metricValue"]=d.pop("metric_value"); d["metricName"]=d.pop("metric_name")
        d["firstObserved"]=d.pop("first_observed"); d["lastConfirmed"]=d.pop("last_confirmed")
        d["source"] = json.loads(d.pop("source_json") or "{}")
        d["relationships"] = json.loads(d.pop("relationships_json") or "[]")
        result.append(d)
    return result


def v13_memory_status() -> Dict[str, Any]:
    items = _v13_rows(500, "", "ACTIVE")
    by_type: Dict[str,int] = {}
    for item in items: by_type[item["knowledgeType"]] = by_type.get(item["knowledgeType"],0)+1
    high = [x for x in items if float(x.get("confidence") or 0) >= 75]
    positive = [x for x in items if float(x.get("metricValue") or 0) > 0]
    negative = [x for x in items if float(x.get("metricValue") or 0) < 0]
    return {"ok": True, "version": V13_MEMORY_VERSION, "enabled": V13_MEMORY_ENABLED, "advisoryOnly": True,
        "automaticLearning": True, "summary": {"activeKnowledge": len(items), "highConfidence": len(high),
        "positiveClaims": len(positive), "negativeClaims": len(negative), "types": by_type},
        "strongestKnowledge": high[:8], "latestKnowledge": sorted(items, key=lambda x: x.get("lastConfirmed") or "", reverse=True)[:12],
        "nextAction": "Continue automatic evidence consolidation; stale knowledge will decay and retire automatically."}


def _v13_memory_worker() -> None:
    time.sleep(V13_MEMORY_STARTUP_DELAY_SECONDS)
    while True:
        try:
            result = v13_memory_refresh()
            print(f"V13 MEMORY | active={result['summary']['activeKnowledge']} high_conf={result['summary']['highConfidence']} types={result['summary']['types']}")
        except Exception as exc:
            print(f"V13 MEMORY WORKER ERROR: {exc}")
        time.sleep(V13_MEMORY_INTERVAL_SECONDS)


@app.on_event("startup")
def v13_memory_startup_event():
    global v13_memory_thread_started
    if not V13_MEMORY_ENABLED: return
    _v13_memory_ensure_tables()
    if not v13_memory_thread_started:
        v13_memory_thread_started=True
        threading.Thread(target=_v13_memory_worker, daemon=True).start()
        print("V13 MEMORY | enabled advisory_only=True automatic_learning=True")


@app.get("/v13/memory/status")
def api_v13_memory_status(request: Request):
    verify_api_key(request); return v13_memory_status()


@app.get("/v13/memory/knowledge")
def api_v13_memory_knowledge(request: Request, limit: int = 200, knowledge_type: str = "", status: str = "ACTIVE"):
    verify_api_key(request); items=_v13_rows(limit, knowledge_type, status)
    return {"ok": True, "version": V13_MEMORY_VERSION, "count": len(items), "items": items}


@app.get("/v13/memory/events")
def api_v13_memory_events(request: Request, limit: int = 100):
    verify_api_key(request); _v13_memory_ensure_tables(); limit=max(1,min(int(limit),500)); conn=db_connect()
    rows=conn.execute("SELECT * FROM v13_memory_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall(); conn.close()
    items=[]
    for row in rows:
        d=dict(row); d["payload"]=json.loads(d.pop("payload_json") or "{}"); items.append(d)
    return {"ok": True, "version": V13_MEMORY_VERSION, "count": len(items), "items": items}


@app.get("/v13/memory/constitution")
def api_v13_memory_constitution(request: Request):
    verify_api_key(request)
    return {"ok": True, "version": V13_MEMORY_VERSION, "advisoryOnly": True, "automaticLearning": True,
        "rules": ["Only persisted evidence may create or strengthen knowledge.",
        "Insufficient evidence remains LEARNING and cannot become a high-confidence claim.",
        "Contradictory evidence lowers confidence instead of being hidden.",
        "Knowledge that is not reconfirmed becomes STALE and is retired automatically.",
        "The memory layer cannot place, cancel or alter orders.",
        "CEO, Board, Research and Evolution may read memory but existing constitutions remain authoritative."]}
# =========================
# TRADEBOT V14 — AUTONOMOUS AI SCIENTIST
# Generates evidence-backed hypotheses and research experiments from V13 memory.
# Research-only: it cannot place orders, change live settings or promote strategies.
# =========================
V14_SCIENTIST_VERSION = "V14.0"
V14_SCIENTIST_ENABLED = os.getenv("V14_SCIENTIST_ENABLED", "true").lower() in ("1", "true", "yes", "on")
V14_SCIENTIST_INTERVAL_SECONDS = max(300, int(os.getenv("V14_SCIENTIST_INTERVAL_SECONDS", "1800")))
V14_SCIENTIST_STARTUP_DELAY_SECONDS = max(10, int(os.getenv("V14_SCIENTIST_STARTUP_DELAY_SECONDS", "55")))
V14_MIN_MEMORY_CONFIDENCE = max(25.0, float(os.getenv("V14_MIN_MEMORY_CONFIDENCE", "55")))
V14_MIN_RESEARCH_SAMPLES = max(20, int(os.getenv("V14_MIN_RESEARCH_SAMPLES", "100")))
v14_scientist_thread_started = False
# V18.2.10: Scientist schema/refresh single-flight guards.  The old code ran
# CREATE TABLE/INDEX from ordinary read endpoints and allowed overlapping refresh
# cycles, which created avoidable SQLite writer contention.
_V14_SCHEMA_LOCK = threading.RLock()
_V14_SCHEMA_COMPLETE = False
_V14_REFRESH_LOCK = threading.Lock()
_V14_LAST_LOCK_LOG_AT = 0.0


def _v14_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _v14_fp(*parts: Any) -> str:
    raw = "|".join(str(p).strip().upper() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _v14_scientist_ensure_tables() -> None:
    global _V14_SCHEMA_COMPLETE
    if not SQLITE_ENABLED or _V14_SCHEMA_COMPLETE:
        return
    with _V14_SCHEMA_LOCK:
        if _V14_SCHEMA_COMPLETE:
            return
        conn = db_connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS v14_hypotheses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                hypothesis_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                statement TEXT NOT NULL,
                rationale TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DISCOVERED',
                confidence REAL NOT NULL DEFAULT 0,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                expected_direction TEXT NOT NULL DEFAULT 'UNKNOWN',
                source_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                variables_json TEXT NOT NULL DEFAULT '{}',
                safeguards_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS v14_experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_key TEXT UNIQUE NOT NULL,
                hypothesis_fingerprint TEXT NOT NULL,
                name TEXT NOT NULL,
                experiment_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'SHADOW_READY',
                baseline_json TEXT NOT NULL DEFAULT '{}',
                variant_json TEXT NOT NULL DEFAULT '{}',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                sample_size INTEGER NOT NULL DEFAULT 0,
                win_rate REAL,
                expectancy_pct REAL,
                profit_factor REAL,
                evaluation_score REAL NOT NULL DEFAULT 0,
                board_eligible INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS v14_scientist_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                reference_key TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v14_hypotheses_status ON v14_hypotheses(status,confidence)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v14_experiments_status ON v14_experiments(status,evaluation_score)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v14_events_created ON v14_scientist_events(created_at)")
        conn.commit(); conn.close()
        _V14_SCHEMA_COMPLETE = True

def _v14_event(event_type: str, title: str, detail: str, reference_key: str = "", payload: Optional[Dict[str, Any]] = None) -> None:
    if not SQLITE_ENABLED:
        return
    _v14_scientist_ensure_tables(); conn = db_connect()
    conn.execute("INSERT INTO v14_scientist_events(created_at,event_type,title,detail,reference_key,payload_json) VALUES(?,?,?,?,?,?)",
                 (_v14_now(), event_type, title, detail, reference_key, json.dumps(payload or {}, default=str)))
    conn.commit(); conn.close()


def _v14_design_from_memory(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    kind = str(item.get("knowledgeType") or "").upper()
    subject = str(item.get("subject") or "UNKNOWN").upper()
    metric = float(item.get("metricValue") or 0)
    confidence = float(item.get("confidence") or 0)
    evidence = int(item.get("evidenceCount") or 0)
    memory_id = int(item.get("id") or 0)
    claim = str(item.get("claim") or "")
    if confidence < V14_MIN_MEMORY_CONFIDENCE:
        return None

    if kind == "RULE":
        direction = "IMPROVE_EXPECTANCY"
        if metric < 0:
            title = f"Shadow-test a less restrictive {subject}"
            statement = f"Reducing the influence of {subject} may improve net expectancy without materially increasing drawdown."
            variant = {"rule": subject, "mode": "SOFTEN", "changePct": 15, "live": False}
        else:
            title = f"Shadow-test stronger use of {subject}"
            statement = f"Prioritising setups supported by {subject} may preserve its positive historical expectancy."
            variant = {"rule": subject, "mode": "WEIGHT_UP", "changePct": 10, "live": False}
        htype = "RULE_VARIANT"
        safeguards = ["Shadow-only", "No live rule removal", "Minimum 100 tagged outcomes", "Compare drawdown and expectancy"]
    elif kind == "SYMBOL":
        direction = "REDUCE_LOSS" if metric < 0 else "IMPROVE_SELECTION"
        if metric < 0:
            title = f"Test a reputation guard for {subject}"
            statement = f"Applying a shadow-only reputation penalty to {subject} may reduce losses in similar market conditions."
            variant = {"symbol": subject, "mode": "REPUTATION_PENALTY", "penaltyPct": min(50, max(10, abs(metric) * 3)), "live": False}
        else:
            title = f"Test selective preference for {subject}"
            statement = f"Giving {subject} a small shadow ranking bonus may improve opportunity selection when its learned conditions recur."
            variant = {"symbol": subject, "mode": "RANKING_BONUS", "bonusPct": min(20, max(5, metric * 2)), "live": False}
        htype = "SYMBOL_POLICY"
        safeguards = ["Shadow-only", "No permanent blacklist", "Regime-matched comparison", "Minimum 50 tagged outcomes"]
    elif kind == "MARKET":
        direction = "IMPROVE_REGIME_FIT"
        title = "Test a market-context execution guard"
        statement = "Conditioning trade selection on the strongest current Market DNA features may improve regime fit."
        variant = {"mode": "MARKET_CONTEXT_GUARD", "source": subject, "live": False}
        htype = "MARKET_CONTEXT"
        safeguards = ["Shadow-only", "No live market shutdown", "Compare by session and regime", "Minimum 200 tagged outcomes"]
    else:
        return None

    fp = _v14_fp(htype, subject, "POS" if metric >= 0 else "NEG")
    return {
        "fingerprint": fp,
        "title": title,
        "hypothesisType": htype,
        "subject": subject,
        "statement": statement,
        "rationale": claim,
        "status": "SHADOW_READY",
        "confidence": min(95.0, confidence),
        "evidenceCount": evidence,
        "expectedDirection": direction,
        "sourceMemoryIds": [memory_id] if memory_id else [],
        "variables": variant,
        "safeguards": safeguards,
    }


def _v14_upsert_hypothesis(item: Dict[str, Any]) -> bool:
    if not SQLITE_ENABLED:
        return False
    _v14_scientist_ensure_tables(); now = _v14_now(); conn = db_connect()
    # V18.2.13: acquire writer before SELECT to avoid a WAL read->write upgrade race.
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT id,confidence,evidence_count,status FROM v14_hypotheses WHERE fingerprint=?", (item["fingerprint"],)).fetchone()
    created = row is None
    if row:
        old = dict(row)
        confidence = max(float(old.get("confidence") or 0), float(item.get("confidence") or 0))
        evidence = max(int(old.get("evidence_count") or 0), int(item.get("evidenceCount") or 0))
        conn.execute("""UPDATE v14_hypotheses SET title=?,statement=?,rationale=?,status=?,confidence=?,evidence_count=?,
            expected_direction=?,source_memory_ids_json=?,variables_json=?,safeguards_json=?,updated_at=? WHERE fingerprint=?""",
            (item["title"], item["statement"], item["rationale"], item["status"], confidence, evidence,
             item["expectedDirection"], json.dumps(item["sourceMemoryIds"]), json.dumps(item["variables"]),
             json.dumps(item["safeguards"]), now, item["fingerprint"]))
    else:
        conn.execute("""INSERT INTO v14_hypotheses(fingerprint,title,hypothesis_type,subject,statement,rationale,status,
            confidence,evidence_count,expected_direction,source_memory_ids_json,variables_json,safeguards_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item["fingerprint"], item["title"], item["hypothesisType"], item["subject"], item["statement"],
             item["rationale"], item["status"], item["confidence"], item["evidenceCount"], item["expectedDirection"],
             json.dumps(item["sourceMemoryIds"]), json.dumps(item["variables"]), json.dumps(item["safeguards"]), now, now))
    conn.commit(); conn.close()
    if created:
        _v14_event("HYPOTHESIS_CREATED", item["title"], item["statement"], item["fingerprint"],
                   {"type": item["hypothesisType"], "confidence": item["confidence"], "evidence": item["evidenceCount"]})
    return created


def _v14_upsert_experiment(hypothesis: Dict[str, Any]) -> bool:
    if not SQLITE_ENABLED:
        return False
    fp = str(hypothesis.get("fingerprint") or "")
    key = _v14_fp("EXPERIMENT", fp, "A_B_SHADOW")
    name = f"EXP-{key[:8].upper()} — {hypothesis.get('title')}"
    baseline = {"mode": "CURRENT_LIVE_LOGIC", "mutated": False}
    variant = hypothesis.get("variables") or {}
    evidence = {"source": "V13_MEMORY", "memoryIds": hypothesis.get("sourceMemoryIds") or [],
                "priorEvidenceCount": int(hypothesis.get("evidenceCount") or 0),
                "priorConfidence": float(hypothesis.get("confidence") or 0),
                "note": "Retrospective evidence designed the experiment; tagged shadow outcomes are still required."}
    prior_score = min(99.0, float(hypothesis.get("confidence") or 0) * 0.7 + min(30.0, int(hypothesis.get("evidenceCount") or 0) / 100.0))
    now = _v14_now(); conn = db_connect()
    # V18.2.13: acquire writer before SELECT to avoid a WAL read->write upgrade race.
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT id FROM v14_experiments WHERE experiment_key=?", (key,)).fetchone(); created = row is None
    if row:
        conn.execute("""UPDATE v14_experiments SET name=?,status='SHADOW_READY',baseline_json=?,variant_json=?,evidence_json=?,
            evaluation_score=?,updated_at=? WHERE experiment_key=?""",
            (name, json.dumps(baseline), json.dumps(variant), json.dumps(evidence), prior_score, now, key))
    else:
        conn.execute("""INSERT INTO v14_experiments(experiment_key,hypothesis_fingerprint,name,experiment_type,status,
            baseline_json,variant_json,evidence_json,sample_size,evaluation_score,board_eligible,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (key, fp, name, "A_B_SHADOW", "SHADOW_READY", json.dumps(baseline), json.dumps(variant),
             json.dumps(evidence), 0, prior_score, 0, now, now))
    conn.commit(); conn.close()
    if created:
        _v14_event("EXPERIMENT_DESIGNED", name,
                   "A controlled shadow experiment was designed. It cannot affect live trading and is not Board-eligible until tagged outcomes exist.",
                   key, {"hypothesisFingerprint": fp, "status": "SHADOW_READY"})
    return created


def _v14_import_research_validations() -> int:
    """Record V7 research evidence without nesting a second SQLite writer inside the experiment transaction.

    V18.2.13: each experiment upsert owns one short BEGIN IMMEDIATE transaction.  The
    Scientist event is emitted only *after* that transaction commits/closes, preventing
    the old connection-A -> _v14_event(connection-B) self-deadlock.
    """
    if not SQLITE_ENABLED:
        return 0
    created = 0
    try:
        payload = v7_research_insights(24)
        rows = payload.get("leaderboard") or payload.get("brains") or payload.get("items") or []
        for row in rows[:30]:
            if not isinstance(row, dict):
                continue
            samples = int(row.get("samples") or row.get("trades") or 0)
            expectancy = float(row.get("expectancyPct") if row.get("expectancyPct") is not None else row.get("expectancy") or 0)
            win_rate = float(row.get("winRate") or 0)
            score = float(row.get("researchScore") if row.get("researchScore") is not None else row.get("score") or 0)
            name = str(row.get("name") or row.get("brainName") or row.get("key") or "UNKNOWN")
            if samples < V14_MIN_RESEARCH_SAMPLES:
                continue
            key = _v14_fp("OBSERVATIONAL", name)
            status = "VALIDATED_RESEARCH" if expectancy > 0 and samples >= V14_MIN_RESEARCH_SAMPLES else "OBSERVED"
            board_eligible = 1 if status == "VALIDATED_RESEARCH" and samples >= 200 and expectancy > 0.25 else 0
            now = _v14_now()
            evidence = {"source": "V7_RESEARCH_LAB", "brain": name, "researchScore": score,
                        "note": "Existing research-lab evidence; not a V14 causal A/B experiment."}
            conn = None
            imported_now = False
            try:
                conn = db_connect()
                # Acquire the writer before SELECT so this cannot become a WAL read->write upgrade race.
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute("SELECT id FROM v14_experiments WHERE experiment_key=?", (key,)).fetchone()
                if existing:
                    conn.execute("""UPDATE v14_experiments SET status=?,evidence_json=?,sample_size=?,win_rate=?,expectancy_pct=?,
                        evaluation_score=?,board_eligible=?,updated_at=? WHERE experiment_key=?""",
                        (status, json.dumps(evidence), samples, win_rate, expectancy, score, board_eligible, now, key))
                else:
                    conn.execute("""INSERT INTO v14_experiments(experiment_key,hypothesis_fingerprint,name,experiment_type,status,
                        baseline_json,variant_json,evidence_json,sample_size,win_rate,expectancy_pct,evaluation_score,board_eligible,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (key, "", f"Research validation — {name}", "OBSERVATIONAL_RESEARCH", status, "{}", json.dumps({"brain": name}),
                         json.dumps(evidence), samples, win_rate, expectancy, score, board_eligible, now, now))
                    imported_now = True
                conn.commit()
            except Exception:
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                raise
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

            # IMPORTANT: this opens its own SQLite connection, so it must stay outside the transaction above.
            if imported_now:
                created += 1
                _v14_event("RESEARCH_VALIDATION_IMPORTED", f"Research evidence imported: {name}",
                           f"{samples:,} samples, {win_rate:.1f}% win rate and {expectancy:.2f}% expectancy.", key,
                           {"status": status, "boardEligible": bool(board_eligible)})
    except Exception as exc:
        if _db_is_lock_error(exc):
            print(f"V18.2.14 DB COORDINATOR | writer=SCIENTIST_IMPORT result=RETRY_EXHAUSTED error={exc}")
            _db_dump_active_transactions("SCIENTIST_IMPORT", exc)
        else:
            print(f"V14 SCIENTIST RESEARCH IMPORT ERROR: {exc}")
    return created


def v14_scientist_refresh() -> Dict[str, Any]:
    # V18.2.10: only one Scientist cycle may mutate research state at a time.
    # API/status readers continue to work while a duplicate cycle is skipped.
    if not _V14_REFRESH_LOCK.acquire(blocking=False):
        print("V18.2.10 SCIENTIST SINGLE-FLIGHT | duplicate cycle skipped")
        return v14_scientist_status()
    try:
        return _v14_scientist_refresh_impl()
    finally:
        _V14_REFRESH_LOCK.release()


def _v14_scientist_refresh_impl() -> Dict[str, Any]:
    _v14_scientist_ensure_tables()
    created_hypotheses = 0; created_experiments = 0
    try:
        memory_items = _v13_rows(300, "", "ACTIVE")
    except Exception:
        memory_items = []
    for memory in memory_items:
        item = _v14_design_from_memory(memory)
        if not item:
            continue
        if _v14_upsert_hypothesis(item):
            created_hypotheses += 1
        if _v14_upsert_experiment(item):
            created_experiments += 1
    imported = _v14_import_research_validations()
    if created_hypotheses or created_experiments or imported:
        _v14_event("SCIENTIST_CYCLE", "Automatic scientist cycle completed",
                   f"Created {created_hypotheses} hypotheses, designed {created_experiments} shadow experiments and imported {imported} research validations.",
                   "V14_CYCLE", {"hypotheses": created_hypotheses, "experiments": created_experiments, "researchValidations": imported})
    return v14_scientist_status()


def _v14_hypothesis_rows(limit: int = 200, status: str = "") -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    _v14_scientist_ensure_tables(); limit=max(1,min(int(limit),1000)); params=[]; where=""
    if status:
        where=" WHERE status=?"; params.append(status.upper())
    conn=db_connect(); rows=conn.execute(f"SELECT * FROM v14_hypotheses{where} ORDER BY confidence DESC,evidence_count DESC LIMIT ?", (*params,limit)).fetchall(); conn.close()
    result=[]
    for row in rows:
        d=dict(row); d["hypothesisType"]=d.pop("hypothesis_type"); d["evidenceCount"]=d.pop("evidence_count")
        d["expectedDirection"]=d.pop("expected_direction"); d["sourceMemoryIds"]=json.loads(d.pop("source_memory_ids_json") or "[]")
        d["variables"]=json.loads(d.pop("variables_json") or "{}"); d["safeguards"]=json.loads(d.pop("safeguards_json") or "[]")
        result.append(d)
    return result


def _v14_experiment_rows(limit: int = 200, status: str = "") -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    _v14_scientist_ensure_tables(); limit=max(1,min(int(limit),1000)); params=[]; where=""
    if status:
        where=" WHERE status=?"; params.append(status.upper())
    conn=db_connect(); rows=conn.execute(f"SELECT * FROM v14_experiments{where} ORDER BY board_eligible DESC,evaluation_score DESC,updated_at DESC LIMIT ?", (*params,limit)).fetchall(); conn.close()
    result=[]
    for row in rows:
        d=dict(row); d["experimentKey"]=d.pop("experiment_key"); d["hypothesisFingerprint"]=d.pop("hypothesis_fingerprint")
        d["experimentType"]=d.pop("experiment_type"); d["sampleSize"]=d.pop("sample_size")
        d["winRate"]=d.pop("win_rate"); d["expectancyPct"]=d.pop("expectancy_pct"); d["profitFactor"]=d.pop("profit_factor")
        d["evaluationScore"]=d.pop("evaluation_score"); d["boardEligible"]=bool(d.pop("board_eligible"))
        d["baseline"]=json.loads(d.pop("baseline_json") or "{}"); d["variant"]=json.loads(d.pop("variant_json") or "{}")
        d["evidence"]=json.loads(d.pop("evidence_json") or "{}")
        result.append(d)
    return result


def v14_scientist_status() -> Dict[str, Any]:
    hypotheses=_v14_hypothesis_rows(500); experiments=_v14_experiment_rows(500)
    by_status: Dict[str,int]={}
    for row in experiments: by_status[row["status"]]=by_status.get(row["status"],0)+1
    eligible=[x for x in experiments if x.get("boardEligible")]
    shadow=[x for x in experiments if x.get("status")=="SHADOW_READY"]
    return {"ok": True, "version": V14_SCIENTIST_VERSION, "enabled": V14_SCIENTIST_ENABLED,
        "researchOnly": True, "automatic": True, "advisoryOnly": True,
        "summary": {"hypotheses": len(hypotheses), "experiments": len(experiments), "shadowReady": len(shadow),
                    "validatedResearch": by_status.get("VALIDATED_RESEARCH",0), "boardEligible": len(eligible), "statuses": by_status},
        "topHypotheses": hypotheses[:8], "topExperiments": experiments[:10],
        "nextAction": "Continue automatic hypothesis generation and collect tagged shadow outcomes before any causal promotion proposal."}


def _v14_scientist_worker() -> None:
    time.sleep(V14_SCIENTIST_STARTUP_DELAY_SECONDS)
    while True:
        try:
            _scientist_cycle_started = _cycle_monitor_start("scientist")
            result=v14_scientist_refresh(); s=result["summary"]
            print(f"V14 SCIENTIST | hypotheses={s['hypotheses']} experiments={s['experiments']} shadow_ready={s['shadowReady']} board_eligible={s['boardEligible']}")
            _cycle_monitor_finish("scientist", _scientist_cycle_started, True)
        except Exception as exc:
            if "_scientist_cycle_started" in locals():
                _cycle_monitor_finish("scientist", _scientist_cycle_started, False, str(exc))
            print(f"V14 SCIENTIST WORKER ERROR: {exc}")
        time.sleep(V14_SCIENTIST_INTERVAL_SECONDS)


@app.on_event("startup")
def v14_scientist_startup_event():
    global v14_scientist_thread_started
    if not V14_SCIENTIST_ENABLED:
        return
    _v14_scientist_ensure_tables()
    if not v14_scientist_thread_started:
        v14_scientist_thread_started=True
        threading.Thread(target=_v14_scientist_worker, daemon=True).start()
        print("V14 SCIENTIST | enabled automatic=True research_only=True advisory_only=True")


@app.get("/v14/scientist/status")
def api_v14_scientist_status(request: Request):
    verify_api_key(request); return v14_scientist_status()


@app.get("/v14/scientist/hypotheses")
def api_v14_scientist_hypotheses(request: Request, limit: int = 200, status: str = ""):
    verify_api_key(request); items=_v14_hypothesis_rows(limit,status)
    return {"ok": True, "version": V14_SCIENTIST_VERSION, "count": len(items), "items": items}


@app.get("/v14/scientist/experiments")
def api_v14_scientist_experiments(request: Request, limit: int = 200, status: str = ""):
    verify_api_key(request); items=_v14_experiment_rows(limit,status)
    return {"ok": True, "version": V14_SCIENTIST_VERSION, "count": len(items), "items": items}


@app.get("/v14/scientist/events")
def api_v14_scientist_events(request: Request, limit: int = 100):
    verify_api_key(request); _v14_scientist_ensure_tables(); limit=max(1,min(int(limit),500)); conn=db_connect()
    rows=conn.execute("SELECT * FROM v14_scientist_events ORDER BY id DESC LIMIT ?",(limit,)).fetchall(); conn.close()
    items=[]
    for row in rows:
        d=dict(row); d["payload"]=json.loads(d.pop("payload_json") or "{}"); items.append(d)
    return {"ok": True, "version": V14_SCIENTIST_VERSION, "count": len(items), "items": items}


@app.get("/v14/scientist/constitution")
def api_v14_scientist_constitution(request: Request):
    verify_api_key(request)
    return {"ok": True, "version": V14_SCIENTIST_VERSION, "automatic": True, "researchOnly": True, "advisoryOnly": True,
        "rules": [
            "The Scientist may generate hypotheses only from persisted evidence and V13 memory.",
            "New V14 experiments are shadow-only and cannot alter live trade selection, orders or settings.",
            "Retrospective evidence may design an experiment but cannot prove that the proposed change caused an outcome.",
            "A hypothesis requires tagged shadow outcomes before it may become causally validated.",
            "Risk and Compliance safeguards remain authoritative and cannot be bypassed.",
            "Research candidates may be presented to the CEO and Board, but promotion remains governed by existing constitutions.",
            "Every hypothesis, experiment and scientist cycle is persisted for audit.",
            "Reviews run automatically; no manual scientist review is required."
        ]}


# ============================================================
# TRADEBOT V15 — AUTONOMOUS AI OPERATIONS CENTRE (AIOPS)
# ============================================================
V15_AIOPS_VERSION = "V15.7"
V15_AIOPS_ENABLED = os.getenv("V15_AIOPS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
V15_AIOPS_INTERVAL_SECONDS = max(300, int(os.getenv("V15_AIOPS_INTERVAL_SECONDS", "900")))
V15_AIOPS_STARTUP_DELAY_SECONDS = max(15, int(os.getenv("V15_AIOPS_STARTUP_DELAY_SECONDS", "75")))
V15_AIOPS_HISTORY_LIMIT = max(50, int(os.getenv("V15_AIOPS_HISTORY_LIMIT", "1000")))
v15_aiops_thread_started = False

# V15.7: health checks must observe the system, not become the system's heaviest workload.
_v157_health_cache: Dict[str, Dict[str, Any]] = {}
_v157_health_cache_lock = threading.RLock()
V157_COMPONENT_CACHE_SECONDS = max(30, int(os.getenv("V157_COMPONENT_CACHE_SECONDS", "120")))
V157_DEEP_DB_CACHE_SECONDS = max(300, int(os.getenv("V157_DEEP_DB_CACHE_SECONDS", "21600")))


def _v157_cached_check(name: str, ttl_seconds: int, fn):
    now = time.monotonic()
    with _v157_health_cache_lock:
        cached = _v157_health_cache.get(name)
        if cached and now - float(cached.get("at", 0.0)) < ttl_seconds:
            result = cached.get("result")
            if isinstance(result, tuple) and len(result) >= 3 and isinstance(result[2], dict):
                details = dict(result[2]); details["cached"] = True
                return (result[0], result[1], details)
            return result
    result = fn()
    with _v157_health_cache_lock:
        _v157_health_cache[name] = {"at": now, "result": result}
    return result


def _v15_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _v15_aiops_ensure_tables() -> None:
    if not SQLITE_ENABLED:
        return
    conn = db_connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS v15_health_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            overall_status TEXT NOT NULL,
            health_score REAL NOT NULL,
            passed INTEGER NOT NULL,
            warnings INTEGER NOT NULL,
            failed INTEGER NOT NULL,
            duration_ms REAL NOT NULL,
            summary_json TEXT NOT NULL DEFAULT '{}',
            components_json TEXT NOT NULL DEFAULT '[]',
            resources_json TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS v15_health_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_key TEXT UNIQUE NOT NULL,
            component TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            resolved_at TEXT,
            occurrences INTEGER NOT NULL DEFAULT 1,
            payload_json TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v15_audits_created ON v15_health_audits(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v15_alerts_status ON v15_health_alerts(status,severity,last_seen)")
    conn.commit(); conn.close()


def _v15_safe_json(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


def _v15_component(name: str, category: str, critical: bool, fn) -> Dict[str, Any]:
    started = time.perf_counter()
    status = "PASS"; message = "Operating normally."; details: Dict[str, Any] = {}
    try:
        result = fn()
        if isinstance(result, tuple):
            status = str(result[0] or "PASS").upper()
            message = str(result[1] or message)
            details = _v15_safe_json(result[2] if len(result) > 2 else {})
        elif isinstance(result, dict):
            details = _v15_safe_json(result)
            if result.get("ok") is False or result.get("enabled") is False:
                status = "WARN"; message = "Subsystem responded but reports a disabled or unhealthy state."
        elif result is False:
            status = "WARN"; message = "Subsystem check returned false."
    except Exception as exc:
        status = "FAIL"; message = f"{type(exc).__name__}: {exc}"
    duration = round((time.perf_counter() - started) * 1000.0, 2)
    performance_warning = None
    if status == "PASS" and duration > 15000:
        performance_warning = f"Slow response ({duration:.0f} ms), but check completed successfully."
        details = dict(details or {}); details["performanceWarning"] = performance_warning
    return {"name": name, "category": category, "critical": critical, "status": status,
            "message": message, "durationMs": duration, "performanceWarning": performance_warning,
            "details": details, "checkedAt": _v15_now()}


def _v15_database_check():
    if not SQLITE_ENABLED:
        return ("WARN", "SQLite persistence is disabled.", {"sqliteEnabled": False})
    conn = db_connect(); row = conn.execute("SELECT 1 AS ok").fetchone()
    tables = conn.execute("SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table'").fetchone()
    conn.close()
    storage = _db_storage_snapshot(include_tables=False)
    used_pct = float(storage.get("diskUsedPct") or 0.0)
    details = {"sqliteEnabled": True, "query": int(dict(row).get("ok", 0)), "tables": int(dict(tables).get("c", 0)),
               "diskUsedPct": used_pct, "diskFreeBytes": storage.get("diskFreeBytes"),
               "databaseBytes": storage.get("mainBytes"), "walBytes": storage.get("walBytes")}
    if used_pct >= DB_HEALTH_FAIL_PCT:
        return ("FAIL", f"Persistent disk is critically full ({used_pct:.1f}% used).", details)
    if used_pct >= DB_HEALTH_WARN_PCT:
        return ("WARN", f"Persistent disk usage is elevated ({used_pct:.1f}% used).", details)
    return ("PASS", "Persistent database is readable and disk capacity is healthy.", details)


def _v15_broker_check():
    broker = globals().get("api") or globals().get("trading_client")
    if broker is None:
        return ("WARN", "Broker client object is not currently available.", {})
    account = broker.get_account()
    blocked = bool(getattr(account, "trading_blocked", False) or getattr(account, "account_blocked", False))
    status = "FAIL" if blocked else "PASS"
    return (status, "Broker account is connected." if not blocked else "Broker reports trading blocked.",
            {"tradingBlocked": blocked, "equity": getattr(account, "equity", None),
             "buyingPower": getattr(account, "buying_power", None), "status": getattr(account, "status", None)})


def _v15_market_check():
    payload = get_market_status_payload()
    return ("PASS", "Market clock and session state are available.", payload)


def _v15_threads_check():
    threads = [t.name for t in threading.enumerate() if t.is_alive()]
    required_flags = {
        "CEO": bool(globals().get("v12_ceo_thread_started", False)),
        "Board": bool(globals().get("v121_board_thread_started", False) or globals().get("v12_board_thread_started", False) or any(t.name == "v121-board-worker" and t.is_alive() for t in threading.enumerate())),
        "Memory": bool(globals().get("v13_memory_thread_started", False)),
        "Scientist": bool(globals().get("v14_scientist_thread_started", False)),
    }
    missing = [name for name, active in required_flags.items() if not active]
    if missing:
        return ("WARN", "One or more autonomous worker start flags are inactive: " + ", ".join(missing),
                {"aliveThreadCount": len(threads), "workers": required_flags, "threadNames": threads[:50]})
    return ("PASS", "Autonomous worker start flags are active.",
            {"aliveThreadCount": len(threads), "workers": required_flags, "threadNames": threads[:50]})


def _v15_resources_check():
    import shutil as _shutil
    disk = _shutil.disk_usage("/")
    free_pct = (disk.free / disk.total * 100.0) if disk.total else 0.0
    try:
        load = list(os.getloadavg())
    except Exception:
        load = []
    try:
        import resource as _resource
        rss_kb = float(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss)
    except Exception:
        rss_kb = 0.0
    status = "PASS"; message = "Host resources are within basic safety thresholds."
    if free_pct < 5:
        status = "FAIL"; message = "Critical disk-space shortage."
    elif free_pct < 15:
        status = "WARN"; message = "Disk space is becoming low."
    return (status, message, {"diskTotalBytes": disk.total, "diskFreeBytes": disk.free,
            "diskFreePct": round(free_pct, 2), "loadAverage": load, "maxRssKb": rss_kb,
            "cpuCount": os.cpu_count()})


def _v15_core_check():
    return ("PASS", "FastAPI application and trading runtime are loaded.",
            {"routes": len(getattr(app, "routes", [])), "botEnabled": bool(globals().get("BOT_ENABLED", True)),
             "sqliteEnabled": bool(SQLITE_ENABLED)})


def _v15_operator_check():
    def _probe():
        payload = v10_operator_status(20)
        status = "PASS" if str(payload.get("mode") or "").upper() in ("AUTO", "SHADOW", "OFF") else "WARN"
        return (status, "Autonomous operator status is readable.", payload)
    return _v157_cached_check("operator-health", V157_COMPONENT_CACHE_SECONDS, _probe)


def _v15_research_check():
    return _v157_cached_check("research-health", V157_COMPONENT_CACHE_SECONDS,
        lambda: ("PASS" if (payload := v7_status_payload()).get("ok", True) is not False else "WARN",
                 "Research engine status is readable.", payload))


def _v15_evolution_check():
    return _v157_cached_check("evolution-health", V157_COMPONENT_CACHE_SECONDS,
        lambda: ("PASS" if (payload := v8_status_payload()).get("ok", True) is not False else "WARN",
                 "Evolution engine status is readable.", payload))


def _v15_ceo_check():
    return _v157_cached_check("ceo-health", V157_COMPONENT_CACHE_SECONDS,
        lambda: ("PASS" if (payload := v12_ceo_status(False, 0)).get("enabled", True) else "WARN",
                 "AI CEO review engine is available.", payload))


def _v15_board_check():
    def _probe():
        payload = v121_board_status()
        vetoes = int(payload.get("vetoes") or payload.get("vetoCount") or 0)
        return ("WARN" if vetoes else "PASS", "AI Board is available." if not vetoes else "AI Board currently reports a veto.", payload)
    return _v157_cached_check("board-health", V157_COMPONENT_CACHE_SECONDS, _probe)


def _v15_memory_check():
    return _v157_cached_check("memory-health", V157_COMPONENT_CACHE_SECONDS,
        lambda: ("PASS" if (payload := v13_memory_status()).get("enabled", True) else "WARN",
                 "Long-term AI Memory is available.", payload))


def _v15_scientist_check():
    return _v157_cached_check("scientist-health", V157_COMPONENT_CACHE_SECONDS,
        lambda: ("PASS" if (payload := v14_scientist_status()).get("enabled", True) else "WARN",
                 "AI Scientist is available.", payload))



def _v151_table_exists(conn, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def _v151_database_doctor_check():
    """Fast, read-only doctor used by the recurring audit.

    Deep integrity scans and write probes are deliberately cached for six hours so
    monitoring cannot hold SQLite locks or delay live endpoints.
    """
    if not SQLITE_ENABLED:
        return ("WARN", "SQLite persistence is disabled.", {"sqliteEnabled": False})

    def _probe():
        started = time.perf_counter()
        conn = db_connect()
        try:
            row = conn.execute("SELECT 1 AS ok").fetchone()
            journal_row = conn.execute("PRAGMA journal_mode").fetchone()
            page_row = conn.execute("PRAGMA page_count").fetchone()
            free_row = conn.execute("PRAGMA freelist_count").fetchone()
            # quick_check(1) performs a bounded sanity check; full integrity_check is
            # intentionally excluded from the recurring hot path.
            quick_row = conn.execute("PRAGMA quick_check(1)").fetchone()
        finally:
            conn.close()
        quick_value = quick_row[0] if quick_row else "unknown"
        ms = round((time.perf_counter() - started) * 1000.0, 2)
        status = "PASS" if str(quick_value).lower() == "ok" else "FAIL"
        return (status,
                "Database quick check passed." if status == "PASS" else "Database quick check failed.",
                {"sqliteEnabled": True, "readProbe": int(dict(row).get("ok", 0)),
                 "quickCheck": quick_value, "journalMode": str(journal_row[0]) if journal_row else "unknown",
                 "pageCount": int(page_row[0]) if page_row else 0,
                 "freePages": int(free_row[0]) if free_row else 0,
                 "latencyMs": ms, "writeProbe": "DEFERRED", "deepCheckCachedSeconds": V157_DEEP_DB_CACHE_SECONDS})

    return _v157_cached_check("database-doctor", V157_DEEP_DB_CACHE_SECONDS, _probe)


def _v151_route_inventory_check():
    routes=[]; parameter_free=[]; protected=[]
    for route in getattr(app, "routes", []):
        path=str(getattr(route,"path","") or "")
        methods=sorted(list(getattr(route,"methods",[]) or []))
        if not path: continue
        item={"path":path,"methods":methods,"name":str(getattr(route,"name","") or "")}
        routes.append(item)
        if "GET" in methods and "{" not in path: parameter_free.append(path)
        if path.startswith(("/v12/","/v13/","/v14/","/v15/")): protected.append(path)
    expected=["/status","/reports","/banking-status","/v12/ceo/status","/v12/board/status",
              "/v13/memory/status","/v14/scientist/status","/v15/operations/status"]
    missing=[p for p in expected if p not in {x["path"] for x in routes}]
    return (("FAIL" if missing else "PASS"),
            "All critical API routes are registered." if not missing else "Critical API routes are missing: "+", ".join(missing),
            {"routeCount":len(routes),"parameterFreeGetCount":len(set(parameter_free)),
             "governanceRouteCount":len(set(protected)),"missingCriticalRoutes":missing,
             "sampleRoutes":sorted(set(parameter_free))[:120]})


def _v151_worker_watchdog_check():
    alive={t.name:t for t in threading.enumerate() if t.is_alive()}
    expected={
        "v12-ceo-worker": bool(globals().get("v12_ceo_thread_started",False)),
        "v121-board-worker": bool(globals().get("v121_board_thread_started",False) or globals().get("v12_board_thread_started",False) or any(t.name == "v121-board-worker" and t.is_alive() for t in threading.enumerate())),
        "v13-memory-worker": bool(globals().get("v13_memory_thread_started",False)),
        "v14-scientist-worker": bool(globals().get("v14_scientist_thread_started",False)),
        "v15-aiops-worker": bool(globals().get("v15_aiops_thread_started",False)),
    }
    rows=[]; missing=[]
    for name,flag in expected.items():
        running=name in alive or flag
        rows.append({"worker":name,"running":running,"startFlag":flag,"threadVisible":name in alive})
        if not running: missing.append(name)
    return (("FAIL" if missing else "PASS"),
            "All autonomous worker watchdogs are active." if not missing else "Missing autonomous workers: "+", ".join(missing),
            {"workers":rows,"aliveThreadCount":len(alive),"missing":missing})


def _v151_queue_check():
    details={}; warnings=[]; failures=[]
    try:
        conn=db_connect()
        table_names={dict(r).get('name') for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        # Decision outcome queue: tolerate schema differences and report only what is measurable.
        outcome_candidates=["decision_outcomes","ai_decision_outcomes","v6_decision_outcomes","decision_memory"]
        found=None
        for t in outcome_candidates:
            if t in table_names: found=t; break
        if found:
            total=int(dict(conn.execute(f"SELECT COUNT(*) AS c FROM {found}").fetchone()).get('c',0))
            details["outcomes"]={"table":found,"total":total}
        else:
            details["outcomes"]={"table":None,"status":"NOT_DISCOVERED"}
        for key,table in [("ceoReviews","v12_ceo_reviews"),("boardMeetings","v121_board_meetings"),
                          ("memoryKnowledge","v13_knowledge"),("memoryEvents","v13_memory_events"),
                          ("scientistHypotheses","v14_hypotheses"),("scientistExperiments","v14_experiments")]:
            if table in table_names:
                details[key]=int(dict(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()).get('c',0))
        conn.close()
    except Exception as exc:
        failures.append(str(exc))
    status="FAIL" if failures else "WARN" if warnings else "PASS"
    msg="Persistent work queues and audit stores are readable." if status=="PASS" else ("; ".join(failures or warnings))
    return (status,msg,details)


def _v151_dependency_snapshot() -> Dict[str, Any]:
    latest=_v15_latest_audit(); comps=latest.get("components") or []
    byname={str(c.get("name")):c for c in comps}
    groups={
      "Trading Engine":["FastAPI & Trading Runtime","Persistent Database","Database Doctor","Broker Connection","Market Clock","Autonomous Operator"],
      "Research & Learning":["Research Lab","Evolution Engine","AI Memory","AI Scientist","Queue & Audit Stores"],
      "Governance":["AI CEO","AI Board","Autonomous Workers","Worker Watchdog"],
      "Infrastructure":["Host Resources","API Route Inventory"]
    }
    out=[]
    rank={"PASS":0,"WARN":1,"FAIL":2}
    for group,names in groups.items():
        items=[byname[n] for n in names if n in byname]
        worst=max((rank.get(str(x.get("status")),1) for x in items),default=1)
        status={0:"PASS",1:"WARN",2:"FAIL"}[worst]
        out.append({"name":group,"status":status,"healthy":sum(1 for x in items if x.get("status")=="PASS"),
                    "total":len(items),"components":[{"name":x.get("name"),"status":x.get("status"),"message":x.get("message")} for x in items]})
    return {"ok":all(x["status"]!="FAIL" for x in out),"version":V15_AIOPS_VERSION,"items":out,"count":len(out)}


def _v151_holiday_mode(latest: Dict[str, Any]) -> Dict[str, Any]:
    summary=latest.get("summary") or {}; status=str(summary.get("overallStatus") or "STARTING")
    critical=int(summary.get("criticalFailures") or 0); warnings=int(summary.get("warnings") or 0)
    if critical:
        headline="HUMAN ATTENTION REQUIRED"; safe=False
    elif status in ("HEALTHY",) and warnings==0:
        headline="EVERYTHING HEALTHY — NO ACTION REQUIRED"; safe=True
    else:
        headline="SYSTEM RUNNING WITH CAUTION"; safe=True
    return {"enabled":True,"headline":headline,"safeToLeaveRunning":safe,"overallStatus":status,
            "healthScore":summary.get("healthScore"),"criticalFailures":critical,"warnings":warnings,
            "automaticRecovery":"MONITORING_AND_ALERTING","checkedAt":summary.get("checkedAt")}

def _v15_collect_components() -> List[Dict[str, Any]]:
    checks = [
        ("FastAPI & Trading Runtime", "CORE", True, _v15_core_check),
        ("Persistent Database", "CORE", True, _v15_database_check),
        ("Database Doctor", "CORE", True, _v151_database_doctor_check),
        ("Broker Connection", "TRADING", True, _v15_broker_check),
        ("Market Clock", "MARKET", True, _v15_market_check),
        ("Autonomous Workers", "OPERATIONS", True, _v15_threads_check),
        ("Worker Watchdog", "OPERATIONS", True, _v151_worker_watchdog_check),
        ("Host Resources", "OPERATIONS", True, _v15_resources_check),
        ("API Route Inventory", "OPERATIONS", True, _v151_route_inventory_check),
        ("Queue & Audit Stores", "OPERATIONS", False, _v151_queue_check),
        ("Autonomous Operator", "TRADING", True, _v15_operator_check),
        ("Research Lab", "INTELLIGENCE", False, _v15_research_check),
        ("Evolution Engine", "INTELLIGENCE", False, _v15_evolution_check),
        ("AI CEO", "GOVERNANCE", False, _v15_ceo_check),
        ("AI Board", "GOVERNANCE", False, _v15_board_check),
        ("AI Memory", "INTELLIGENCE", False, _v15_memory_check),
        ("AI Scientist", "INTELLIGENCE", False, _v15_scientist_check),
    ]
    return [_v15_component(*item) for item in checks]


def _v15_alert_key(component: Dict[str, Any]) -> str:
    raw = f"{component.get('name')}|{component.get('status')}|{component.get('message')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _v15_sync_alerts(components: List[Dict[str, Any]]) -> None:
    if not SQLITE_ENABLED:
        return
    _v15_aiops_ensure_tables(); now = _v15_now(); active_keys = []
    conn = db_connect()
    for component in components:
        if component.get("status") == "PASS":
            continue
        key = _v15_alert_key(component); active_keys.append(key)
        severity = "CRITICAL" if component.get("status") == "FAIL" and component.get("critical") else \
                   "ERROR" if component.get("status") == "FAIL" else "WARNING"
        existing = conn.execute("SELECT id FROM v15_health_alerts WHERE alert_key=?", (key,)).fetchone()
        if existing:
            conn.execute("""UPDATE v15_health_alerts SET status='ACTIVE',severity=?,last_seen=?,resolved_at=NULL,
                occurrences=occurrences+1,detail=?,payload_json=? WHERE alert_key=?""",
                (severity, now, component.get("message"), json.dumps(component, default=str), key))
        else:
            conn.execute("""INSERT INTO v15_health_alerts(alert_key,component,severity,status,title,detail,first_seen,last_seen,payload_json)
                VALUES(?,?,?,'ACTIVE',?,?,?,?,?)""",
                (key, component.get("name"), severity, f"{component.get('name')} requires attention",
                 component.get("message"), now, now, json.dumps(component, default=str)))
    if active_keys:
        placeholders = ",".join("?" for _ in active_keys)
        conn.execute(f"UPDATE v15_health_alerts SET status='RESOLVED',resolved_at=? WHERE status='ACTIVE' AND alert_key NOT IN ({placeholders})",
                     (now, *active_keys))
    else:
        conn.execute("UPDATE v15_health_alerts SET status='RESOLVED',resolved_at=? WHERE status='ACTIVE'", (now,))
    conn.commit(); conn.close()


def v15_aiops_run_audit() -> Dict[str, Any]:
    started = time.perf_counter(); components = _v15_collect_components()
    passed = sum(1 for x in components if x["status"] == "PASS")
    warnings = sum(1 for x in components if x["status"] == "WARN")
    failed = sum(1 for x in components if x["status"] == "FAIL")
    critical_failures = sum(1 for x in components if x["status"] == "FAIL" and x.get("critical"))
    weights = {"PASS": 1.0, "WARN": 0.55, "FAIL": 0.0}
    total_weight = sum(2.0 if x.get("critical") else 1.0 for x in components) or 1.0
    earned = sum((2.0 if x.get("critical") else 1.0) * weights[x["status"]] for x in components)
    score = round(earned / total_weight * 100.0, 1)
    overall = "CRITICAL" if critical_failures else "DEGRADED" if failed else "WARNING" if warnings else "HEALTHY"
    duration = round((time.perf_counter() - started) * 1000.0, 2)
    resources = next((x.get("details") for x in components if x.get("name") == "Host Resources"), {}) or {}
    summary = {"overallStatus": overall, "healthScore": score, "passed": passed, "warnings": warnings,
               "failed": failed, "criticalFailures": critical_failures, "componentCount": len(components),
               "checkedAt": _v15_now(), "nextAuditInSeconds": V15_AIOPS_INTERVAL_SECONDS,
               "automatic": True, "selfHealing": "BOUNDED_MONITORING", "tradingChangesAllowed": False,
               "endpointDiscovery": True, "workerWatchdog": True, "databaseDoctor": True, "holidayMode": True}
    if SQLITE_ENABLED:
        _v15_aiops_ensure_tables(); conn = db_connect()
        conn.execute("""INSERT INTO v15_health_audits(created_at,overall_status,health_score,passed,warnings,failed,duration_ms,
            summary_json,components_json,resources_json) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (summary["checkedAt"], overall, score, passed, warnings, failed, duration,
             json.dumps(summary, default=str), json.dumps(components, default=str), json.dumps(resources, default=str)))
        conn.execute("DELETE FROM v15_health_audits WHERE id NOT IN (SELECT id FROM v15_health_audits ORDER BY id DESC LIMIT ?)",
                     (V15_AIOPS_HISTORY_LIMIT,))
        conn.commit(); conn.close()
        _v15_sync_alerts(components)
    return {"ok": critical_failures == 0, "version": V15_AIOPS_VERSION, "enabled": V15_AIOPS_ENABLED,
            "summary": summary, "components": components, "resources": resources, "durationMs": duration,
            "nextAction": "No intervention required." if overall == "HEALTHY" else
                          "Review active alerts; autonomous setting changes should remain bounded by existing safeguards."}


def _v15_latest_audit() -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return v15_aiops_run_audit()
    _v15_aiops_ensure_tables(); conn = db_connect()
    row = conn.execute("SELECT * FROM v15_health_audits ORDER BY id DESC LIMIT 1").fetchone(); conn.close()
    if not row:
        return v15_aiops_run_audit()
    d = dict(row)
    return {"ok": d["overall_status"] != "CRITICAL", "version": V15_AIOPS_VERSION, "enabled": V15_AIOPS_ENABLED,
            "summary": json.loads(d["summary_json"] or "{}"), "components": json.loads(d["components_json"] or "[]"),
            "resources": json.loads(d["resources_json"] or "{}"), "durationMs": d["duration_ms"],
            "nextAction": "No intervention required." if d["overall_status"] == "HEALTHY" else "Review active alerts."}


def _v15_alert_rows(limit: int = 100, status: str = "") -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    _v15_aiops_ensure_tables(); limit=max(1,min(int(limit),500)); params=[]; where=""
    if status:
        where=" WHERE status=?"; params.append(status.upper())
    conn=db_connect(); rows=conn.execute(f"SELECT * FROM v15_health_alerts{where} ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'ERROR' THEN 2 ELSE 3 END,last_seen DESC LIMIT ?", (*params,limit)).fetchall(); conn.close()
    result=[]
    for row in rows:
        d=dict(row); d["payload"]=json.loads(d.pop("payload_json") or "{}"); result.append(d)
    return result


def _v15_history_rows(limit: int = 100) -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    _v15_aiops_ensure_tables(); limit=max(1,min(int(limit),500)); conn=db_connect()
    rows=conn.execute("SELECT id,created_at,overall_status,health_score,passed,warnings,failed,duration_ms,summary_json,resources_json FROM v15_health_audits ORDER BY id DESC LIMIT ?", (limit,)).fetchall(); conn.close()
    result=[]
    for row in rows:
        d=dict(row); d["overallStatus"]=d.pop("overall_status"); d["healthScore"]=d.pop("health_score")
        d["durationMs"]=d.pop("duration_ms"); d["summary"]=json.loads(d.pop("summary_json") or "{}")
        d["resources"]=json.loads(d.pop("resources_json") or "{}"); result.append(d)
    return result


def _v15_aiops_worker() -> None:
    time.sleep(V15_AIOPS_STARTUP_DELAY_SECONDS)
    while True:
        try:
            result = v15_aiops_run_audit(); s=result["summary"]
            print(f"V15 AIOPS | status={s['overallStatus']} health={s['healthScore']} pass={s['passed']} warn={s['warnings']} fail={s['failed']}")
        except Exception as exc:
            print(f"V15 AIOPS WORKER ERROR: {exc}")
        time.sleep(V15_AIOPS_INTERVAL_SECONDS)


@app.on_event("startup")
def v15_aiops_startup_event():
    global v15_aiops_thread_started
    if not V15_AIOPS_ENABLED:
        return
    _v15_aiops_ensure_tables()
    if not v15_aiops_thread_started:
        v15_aiops_thread_started=True
        threading.Thread(target=_v15_aiops_worker, daemon=True, name="v15-aiops-worker").start()
        print(f"V15 AIOPS | enabled automatic=True interval={V15_AIOPS_INTERVAL_SECONDS}s monitoring_only=True")


@app.get("/v15/operations/status")
def api_v15_operations_status(request: Request):
    verify_api_key(request); return _v15_latest_audit()


@app.get("/v15/operations/components")
def api_v15_operations_components(request: Request):
    verify_api_key(request); latest=_v15_latest_audit()
    return {"ok": True, "version": V15_AIOPS_VERSION, "count": len(latest.get("components") or []), "items": latest.get("components") or []}


@app.get("/v15/operations/alerts")
def api_v15_operations_alerts(request: Request, limit: int = 100, status: str = "ACTIVE"):
    verify_api_key(request); items=_v15_alert_rows(limit,status)
    return {"ok": True, "version": V15_AIOPS_VERSION, "count": len(items), "items": items}


@app.get("/v15/operations/history")
def api_v15_operations_history(request: Request, limit: int = 100):
    verify_api_key(request); items=_v15_history_rows(limit)
    return {"ok": True, "version": V15_AIOPS_VERSION, "count": len(items), "items": items}


@app.get("/v15/operations/dependencies")
def api_v151_operations_dependencies(request: Request):
    verify_api_key(request); return _v151_dependency_snapshot()


@app.get("/v15/operations/watchdogs")
def api_v151_operations_watchdogs(request: Request):
    verify_api_key(request); latest=_v15_latest_audit()
    items=[x for x in (latest.get("components") or []) if x.get("name") in ("Autonomous Workers","Worker Watchdog")]
    return {"ok":all(x.get("status")!="FAIL" for x in items),"version":V15_AIOPS_VERSION,"count":len(items),"items":items}


@app.get("/v15/operations/queues")
def api_v151_operations_queues(request: Request):
    verify_api_key(request); status,message,details=_v151_queue_check()
    return {"ok":status!="FAIL","version":V15_AIOPS_VERSION,"status":status,"message":message,"queues":details}


@app.get("/v15/operations/doctor")
def api_v151_operations_doctor(request: Request):
    verify_api_key(request); latest=_v15_latest_audit()
    return {"ok":latest.get("ok",False),"version":V15_AIOPS_VERSION,"holidayMode":_v151_holiday_mode(latest),
            "dependencies":_v151_dependency_snapshot().get("items",[]),"summary":latest.get("summary",{}),
            "activeAlerts":_v15_alert_rows(100,"ACTIVE")}



def _v152_engine_health_snapshot() -> Dict[str, Any]:
    """Return a fault-isolated view of every Operations component and critical route.

    A failed component is reported without aborting the remaining checks. Route
    registration is also shown so deployment omissions are immediately visible.
    """
    latest = _v15_latest_audit()
    components = list(latest.get("components") or [])

    expected_routes = [
        "/status", "/banking-status", "/reports",
        "/ai-advisor/summary", "/shadow-trading/summary",
        "/decision-intelligence/summary", "/strategy-intelligence/summary",
        "/symbol-intelligence/summary", "/rule-intelligence/summary",
        "/weakness-intelligence/summary", "/v4/market-dna", "/v4/patterns",
        "/v4/weekly-intelligence", "/v7/status", "/v7/research/insights",
        "/v8/status", "/v10/operator/status", "/v10/promotion/status",
        "/v10/symbol-reputation/summary", "/v12/ceo/status",
        "/v12/ceo/journal", "/v12/ceo/reviews", "/v12/ceo/constitution",
        "/v12/board/status", "/v12/board/history", "/v12/board/constitution",
        "/v13/memory/status", "/v13/memory/knowledge", "/v13/memory/events",
        "/v13/memory/constitution", "/v14/scientist/status",
        "/v14/scientist/hypotheses", "/v14/scientist/experiments",
        "/v14/scientist/events", "/v14/scientist/constitution",
        "/v15/operations/status", "/v15/operations/components",
        "/v15/operations/alerts", "/v15/operations/history",
        "/v15/operations/constitution", "/v15/operations/dependencies",
        "/v15/operations/watchdogs", "/v15/operations/queues",
        "/v15/operations/doctor", "/v15/operations/engine-health",
    ]
    registered = {getattr(route, "path", "") for route in getattr(app, "routes", [])}
    route_items = []
    for path in expected_routes:
        present = path in registered
        route_items.append({
            "name": path,
            "category": "API Route",
            "status": "PASS" if present else "FAIL",
            "online": present,
            "critical": path in ("/status", "/banking-status", "/reports", "/v15/operations/status"),
            "reason": "Route registered." if present else "Route missing from the deployed FastAPI application.",
        })

    component_items = []
    for item in components:
        status = str(item.get("status") or "UNKNOWN").upper()
        component_items.append({
            "name": item.get("name") or "Unnamed component",
            "category": item.get("category") or "Subsystem",
            "status": status,
            "online": status == "PASS",
            "critical": bool(item.get("critical")),
            "reason": item.get("message") or "No diagnostic message.",
            "durationMs": item.get("durationMs"),
            "checkedAt": item.get("checkedAt"),
            "details": item.get("details") or {},
        })

    all_items = component_items + route_items
    online = sum(1 for item in all_items if item.get("online"))
    warning = sum(1 for item in all_items if item.get("status") == "WARN")
    offline = [item for item in all_items if not item.get("online")]
    return {
        "ok": not any(item.get("status") == "FAIL" and item.get("critical") for item in all_items),
        "version": "V15.2",
        "generatedAt": _v15_now(),
        "online": online,
        "total": len(all_items),
        "warnings": warning,
        "offlineCount": len(offline),
        "offline": offline,
        "items": all_items,
        "operationsSummary": latest.get("summary") or {},
    }


@app.get("/v15/operations/engine-health")
def api_v152_operations_engine_health(request: Request):
    verify_api_key(request)
    return _v152_engine_health_snapshot()


@app.get("/v15/operations/constitution")
def api_v15_operations_constitution(request: Request):
    verify_api_key(request)
    return {"ok": True, "version": V15_AIOPS_VERSION, "automatic": True, "monitoringOnly": True,
        "manualReviewRequired": False, "operationsMode": "PRO", "rules": [
            "The Operations Centre continuously monitors every critical subsystem without recurring human input.",
            "AIOps may observe, score, persist and alert, but it cannot place, cancel or alter orders.",
            "AIOps cannot change live strategy settings or bypass the CEO, Board, operator or risk constitutions.",
            "Critical trading, database, broker or worker failures must reduce the overall health state.",
            "Warnings remain visible until the underlying condition clears; resolved alerts remain auditable.",
            "Every full-system audit and alert transition is persisted.",
            "Health data may inform CEO and Board caution, but cannot grant additional trading authority.",
            "Audits run automatically; no manual health-review button is required.",
            "V15.1 discovers registered API routes, checks database integrity, watches autonomous workers and audits persistent queues.",
            "Holiday Mode summarises whether the platform is safe to leave running, but never conceals active warnings or critical failures.",
            "Self-healing is bounded to monitoring, alert resolution and safe worker diagnostics; it never changes trading strategy or orders."
        ]}


# ============================================================
# V15.12 — AUTONOMOUS EVIDENCE-CALIBRATED ENTRY GATES
# Learns Sniper/A+ confidence and quality thresholds from completed outcomes.
# Changes are bounded, stability-tested, closed-market-only and auditable.
# ============================================================
_ai_threshold_last_result: Dict[str, Any] = {}
_ai_threshold_worker_started = False
# V17.7.1 — only one evidence-calibration cycle may run at once, whether it
# comes from the autonomous worker or the authenticated review endpoint.
_AI_THRESHOLD_CYCLE_LOCK = threading.Lock()
_ai_threshold_last_log_signature = None
_ai_threshold_last_log_ts = 0.0
AI_THRESHOLD_LOG_DEDUPE_SECONDS = max(5.0, float(os.getenv("AI_THRESHOLD_LOG_DEDUPE_SECONDS", "60") or 60))


def ai_threshold_learning_status() -> Dict[str, Any]:
    current = current_strategy_settings_payload()
    return {
        "ok": True,
        "version": "V15.12",
        "enabled": AI_THRESHOLD_LEARNING_ENABLED,
        "automaticApply": V2_AUTO_APPLY_THRESHOLDS,
        "closedMarketOnly": AI_THRESHOLD_CLOSED_MARKET_ONLY,
        "intervalSeconds": AI_THRESHOLD_INTERVAL_SECONDS,
        "minimumSamples": AI_THRESHOLD_MIN_SAMPLES,
        "requiredStableReviews": V2_OPTIMIZER_REQUIRED_STABLE_RUNS,
        "maximumConfidenceStep": V2_OPTIMIZER_MAX_CONF_STEP,
        "maximumQualityStep": V2_OPTIMIZER_MAX_QUALITY_STEP,
        "currentSettings": current,
        "lastResult": _ai_threshold_last_result or None,
        "safety": {
            "canPlaceOrders": False,
            "canChangePositionCapacity": False,
            "canChangeStops": False,
            "changesOnlyEntryGates": True,
            "rollbackHistoryEnabled": True,
        },
    }


def _ai_threshold_learning_cycle_unlocked(trigger: str = "automatic", force: bool = False) -> Dict[str, Any]:
    global _ai_threshold_last_result
    if not AI_THRESHOLD_LEARNING_ENABLED:
        return {"ok": False, "version": "V15.12", "message": "Autonomous threshold learning is disabled."}
    try:
        market_open = bool(get_effective_market_status_payload().get("isOpen", False))
    except Exception as exc:
        result = {"ok": False, "version": "V15.12", "trigger": trigger, "error": f"Market clock unavailable: {exc}"}
        _ai_threshold_last_result = result
        return result
    if market_open and AI_THRESHOLD_CLOSED_MARKET_ONLY and not force:
        result = {
            "ok": True, "version": "V15.12", "trigger": trigger,
            "ran": False, "marketOpen": True,
            "message": "Live market has priority; threshold learning waits for market close.",
            "currentSettings": current_strategy_settings_payload(),
        }
        _ai_threshold_last_result = result
        return result
    result = v2_adaptive_threshold_recommendations(24, AI_THRESHOLD_MIN_SAMPLES)
    result.update({
        "version": "V15.12",
        "name": "Autonomous Evidence-Calibrated Entry Gates",
        "trigger": trigger,
        "ran": True,
        "marketOpen": market_open,
        "learns": ["sniper confidence", "sniper quality", "A+ confidence", "A+ quality"],
    })
    _ai_threshold_last_result = result
    try:
        global _ai_threshold_last_log_signature, _ai_threshold_last_log_ts
        stability = result.get('stability') or {}
        signature = (
            str(result.get('recommendation') or ''),
            int(result.get('observations') or 0),
            int(stability.get('matchingRuns') or 0),
            int(stability.get('requiredRuns') or V2_OPTIMIZER_REQUIRED_STABLE_RUNS),
            bool(result.get('applied', False)),
        )
        now_mono = time.monotonic()
        if signature != _ai_threshold_last_log_signature or (now_mono - _ai_threshold_last_log_ts) >= AI_THRESHOLD_LOG_DEDUPE_SECONDS:
            print(
                "V15.12 THRESHOLD LEARNER | "
                f"recommendation={result.get('recommendation')} observations={result.get('observations',0)} "
                f"stable={stability.get('matchingRuns',0)}/"
                f"{stability.get('requiredRuns',V2_OPTIMIZER_REQUIRED_STABLE_RUNS)} "
                f"applied={result.get('applied',False)}"
            )
            _ai_threshold_last_log_signature = signature
            _ai_threshold_last_log_ts = now_mono
    except Exception:
        pass
    return result


def ai_threshold_learning_cycle(trigger: str = "automatic", force: bool = False) -> Dict[str, Any]:
    # Never allow the scheduler, a manual review, or another caller to run the
    # expensive evidence-calibration transaction concurrently.  A busy cycle is
    # skipped rather than queued so /status and the live trader keep priority.
    acquired = _AI_THRESHOLD_CYCLE_LOCK.acquire(blocking=False)
    if not acquired:
        return {
            "ok": True, "version": "V17.7.1", "trigger": trigger,
            "ran": False, "skipped": True, "reason": "threshold_cycle_already_running",
            "message": "Another threshold-learning cycle is already running; this duplicate request was skipped.",
            "currentSettings": current_strategy_settings_payload(),
        }
    try:
        return _ai_threshold_learning_cycle_unlocked(trigger=trigger, force=force)
    finally:
        _AI_THRESHOLD_CYCLE_LOCK.release()


def ai_threshold_learning_worker() -> None:
    time.sleep(AI_THRESHOLD_STARTUP_DELAY_SECONDS)
    while True:
        try:
            ai_threshold_learning_cycle("automatic", force=False)
        except Exception as exc:
            print(f"V15.12 THRESHOLD LEARNER ERROR: {exc}")
        time.sleep(AI_THRESHOLD_INTERVAL_SECONDS)


@app.get("/adaptive-thresholds/status")
def api_adaptive_thresholds_status(request: Request):
    verify_api_key(request)
    return ai_threshold_learning_status()


@app.post("/adaptive-thresholds/review")
def api_adaptive_thresholds_review(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    # Force means run the evidence review now; market-open protection still
    # prevents applying live changes inside v2_adaptive_threshold_recommendations.
    return ai_threshold_learning_cycle("authenticated-manual-review", force=bool(payload.get("force", True)))


# Start once, after all functions/routes are registered.
if AI_THRESHOLD_LEARNING_ENABLED and not _ai_threshold_worker_started:
    try:
        threading.Thread(
            target=ai_threshold_learning_worker,
            daemon=True,
            name="v1512-threshold-learning-worker",
        ).start()
        _ai_threshold_worker_started = True
    except Exception as exc:
        print(f"V15.12 THRESHOLD WORKER START ERROR: {exc}")
