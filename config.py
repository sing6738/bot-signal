"""Configuration for XAUUSD SMC Signal Bot."""

import os
from dotenv import load_dotenv

load_dotenv()

# --- MetaTrader 5 ---
SYMBOL = "GOLD"
HTF = 16385       # mt5.TIMEFRAME_H1
LTF = 15          # mt5.TIMEFRAME_M15
CANDLE_COUNT = 200

# --- Swing Detection ---
SWING_LOOKBACK = 3

# --- H1 Trend Alignment ---
STRICT_TREND_ALIGNMENT = True

# --- ATR / Impulse / Consolidation ---
ATR_PERIOD = 14
IMPULSE_THRESHOLD = 1.5   # × ATR
CONSOL_THRESHOLD = 0.5    # × ATR
CONSOL_MIN_BARS = 5

# --- Zone Management ---
ZONE_MAX_TESTS = 2         # allow 1 retest, invalid after 2nd test
ZONE_MAX_WIDTH_ATR = 1.5   # reject zones wider than this × ATR

# --- Confluence ---
# XAUUSD 1 pip = 0.1 price unit → 50 pips = 5.0
CONFLUENCE_PROXIMITY = 5.0  # tighter proximity (50 pips)
MIN_CONFLUENCE = 4

# --- Entry Mode & Premium/Discount ---
ENTRY_MODE = "equilibrium"  # "equilibrium" (50% of OB) or "proximal" (edge)
PREMIUM_DISCOUNT_THRESHOLD = 0.50  # strictly BUY in discount (<0.50), SELL in premium (>0.50)
REQUIRE_LIQUIDITY_SWEEP = True     # require BSL/SSL sweep for high-probability entry
SWEEP_WINDOW_BARS = 20             # lookback bars to detect recent liquidity sweep

# --- SL / TP & Break-Even ---
RR_RATIO = 1.0     # 1:1.0 Risk:Reward target
SL_BUFFER = 0.3    # 3 pips buffer
MAX_SL_PIPS = 120  # reject signals with SL > 120 pips
MIN_SL_PIPS = 10   # reject signals with SL < 10 pips (too tight)
BE_TRIGGER_R = 0.5 # move SL to Breakeven when trade reaches 0.5R
BE_OFFSET_PIPS = 2.0 # lock in +2 pips at Breakeven

# --- Zone Freshness ---
ZONE_MAX_AGE_BARS = 50  # ignore zones older than this (in M15 bars)

# --- Session Filter (UTC hours) ---
# Narrow to most liquid window: 08:00-17:00 UTC
SESSION_HOURS_UTC = [(8, 17)]

# --- Main Loop ---
POLL_INTERVAL_SEC = 15

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
