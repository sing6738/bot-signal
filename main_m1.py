"""XAUUSD SMC Signal Bot — [M1 Scalper] Entry Point.

Polls MT5 every POLL_INTERVAL_SEC seconds. When a new M1 candle closes,
runs the full SMC analysis (H1 trend -> M1 entry) and sends a Telegram alert if a signal is found.

NOTE ON M1:
M1 candles are 15x noisier per unit time than M15. To keep the same
*real-world* lookback/freshness windows the M15 system was tuned for,
several config values are scaled up here (in bar-count, not price) before
the bot starts. This does NOT change price-based settings (SL_BUFFER,
MIN/MAX_SL_PIPS, RR_RATIO) — those still need your own validation on M1,
ideally via backtest.py --tf m1 first.

ONE TRADE AT A TIME:
The bot tracks the last signal it sent and will NOT send a new signal until
that one has been resolved — either the entry never got hit within
ORDER_EXPIRY_BARS candles (expired), or price hit SL, or price hit TP.
This mirrors how backtest.py simulates a single open position per signal.
"""

import time
import sys
from dataclasses import dataclass
from datetime import datetime

# Prevent UnicodeEncodeError on Windows terminals (cp874 etc.) and flush immediately
sys.stdout.reconfigure(line_buffering=True, errors="replace")

import config
import mt5_data
import signal_engine
import telegram_bot

TIMEFRAME_M1 = 1  # mt5.TIMEFRAME_M1
PIP = 0.1         # XAUUSD: 1 pip = 0.1

# --- M1-specific bar-count scaling (M15 -> M1 is a 15x factor) ---
# H1 fetch count stays untouched (H1 lookback doesn't depend on entry timeframe).
# Only the M1 entry-side bar counts are scaled up, plus config.ZONE_MAX_AGE_BARS
# and config.SWEEP_WINDOW_BARS (read via getattr by smc_core/signal_engine at
# call time, so overriding the module attribute here is picked up automatically).
M1_SCALE = 15
H1_CANDLE_COUNT = config.CANDLE_COUNT  # unscaled, e.g. 200 H1 bars
M1_CANDLE_COUNT = getattr(config, "M1_CANDLE_COUNT", config.CANDLE_COUNT * M1_SCALE)
config.ZONE_MAX_AGE_BARS = getattr(config, "M1_ZONE_MAX_AGE_BARS", config.ZONE_MAX_AGE_BARS * M1_SCALE)
config.SWEEP_WINDOW_BARS = getattr(config, "M1_SWEEP_WINDOW_BARS",
                                    getattr(config, "SWEEP_WINDOW_BARS", 20) * M1_SCALE)

# How many M1 candles to wait for price to reach Entry before giving up on
# a signal (so the bot doesn't stay locked forever if price never comes back).
# How many M1 candles to wait for price to reach Entry before giving up on
# a signal (so the bot doesn't stay locked forever if price never comes back).
# Scaled ×15 by default so the real-world wait time matches M15's tuning
# (20 M15 bars = 5 hours) — 20 unscaled M1 bars would only be 20 minutes,
# nowhere near enough time for price to pull back to an OB/FVG zone.
ORDER_EXPIRY_BARS = getattr(config, "M1_ORDER_EXPIRY_BARS",
                             getattr(config, "ORDER_EXPIRY_BARS", 20) * M1_SCALE)


@dataclass
class OpenSignal:
    direction: str
    entry: float
    sl: float
    tp: float
    signal_time: datetime
    bars_waited: int = 0
    entered: bool = False


def _pips(direction: str, entry: float, exit_price: float) -> float:
    if direction == "BUY":
        return round((exit_price - entry) / PIP, 1)
    return round((entry - exit_price) / PIP, 1)


def _check_open_signal(open_sig: OpenSignal, bar_high: float, bar_low: float) -> str | None:
    """Advance an OpenSignal by one candle. Returns 'TP', 'SL', 'EXPIRED', or None (still open)."""
    if not open_sig.entered:
        triggered = (
            (open_sig.direction == "BUY" and bar_low <= open_sig.entry) or
            (open_sig.direction == "SELL" and bar_high >= open_sig.entry)
        )
        if triggered:
            open_sig.entered = True
            print(f"[M1 Main] Entry filled @ {open_sig.entry}")
        else:
            open_sig.bars_waited += 1
            if open_sig.bars_waited > ORDER_EXPIRY_BARS:
                return "EXPIRED"
            return None

    if open_sig.entered:
        if open_sig.direction == "BUY":
            if bar_high >= open_sig.tp:
                return "TP"
            if bar_low <= open_sig.sl:
                return "SL"
        else:
            if bar_low <= open_sig.tp:
                return "TP"
            if bar_high >= open_sig.sl:
                return "SL"
    return None


def main():
    print("=" * 50)
    print("  XAUUSD SMC Signal Bot — [M1 Scalper]")
    print(f"  H1 trend -> M1 entry | RR 1:{config.RR_RATIO}")
    print(f"  Min confluence: {config.MIN_CONFLUENCE}/4")
    print(f"  H1_CANDLES={H1_CANDLE_COUNT}  M1_CANDLES={M1_CANDLE_COUNT}  ZONE_MAX_AGE_BARS={config.ZONE_MAX_AGE_BARS}  SWEEP_WINDOW_BARS={config.SWEEP_WINDOW_BARS}  ORDER_EXPIRY_BARS={ORDER_EXPIRY_BARS}")
    print("  One trade at a time: new signals are held until the open one hits TP/SL/expires")
    print("=" * 50)

    # --- Connect MT5 ---
    for attempt in range(1, 4):
        if mt5_data.connect():
            break
        print(f"[M1 Main] MT5 connect retry {attempt}/3 ...")
        time.sleep(5)
    else:
        msg = "❌ ไม่สามารถเชื่อมต่อ MT5 ได้ — บอท M1 หยุดทำงาน"
        print(msg)
        telegram_bot.send_message(msg)
        sys.exit(1)

    last_m1_time = None
    open_sig: OpenSignal | None = None
    print(f"[M1 Main] Polling every {config.POLL_INTERVAL_SEC}s for new M1 candle ...")

    try:
        while True:
            # Fetch latest M1 candle to check if a new bar closed
            m1_check = mt5_data.get_candles(config.SYMBOL, TIMEFRAME_M1, 2)
            if m1_check is None:
                print("[M1 Main] Failed to fetch M1 candles — retrying next cycle")
                time.sleep(config.POLL_INTERVAL_SEC)
                continue

            current_m1_time = m1_check["time"].iloc[-2]  # last *closed* bar

            if last_m1_time is not None and current_m1_time <= last_m1_time:
                # No new bar yet
                time.sleep(config.POLL_INTERVAL_SEC)
                continue

            last_m1_time = current_m1_time
            bar_high = float(m1_check["high"].iloc[-2])
            bar_low = float(m1_check["low"].iloc[-2])
            now = datetime.now().strftime("%H:%M:%S")
            print(f"\n[{now}] New M1 candle closed ({current_m1_time}) — analyzing ...")

            # --- If a signal is already open, advance it first and skip analysis ---
            if open_sig is not None:
                outcome = _check_open_signal(open_sig, bar_high, bar_low)
                if outcome == "TP":
                    pnl = _pips(open_sig.direction, open_sig.entry, open_sig.tp)
                    msg = f"✅ TP HIT [M1] — {config.SYMBOL}\n{open_sig.direction} @ {open_sig.entry:,.2f} → TP {open_sig.tp:,.2f}  ({pnl:+.1f} pips)"
                    print(f"[M1 Main] >>> {msg}")
                    telegram_bot.send_message(msg)
                    open_sig = None
                elif outcome == "SL":
                    pnl = _pips(open_sig.direction, open_sig.entry, open_sig.sl)
                    msg = f"❌ SL HIT [M1] — {config.SYMBOL}\n{open_sig.direction} @ {open_sig.entry:,.2f} → SL {open_sig.sl:,.2f}  ({pnl:+.1f} pips)"
                    print(f"[M1 Main] >>> {msg}")
                    telegram_bot.send_message(msg)
                    open_sig = None
                elif outcome == "EXPIRED":
                    print(f"[M1 Main] Signal expired (never filled) — {open_sig.direction} @ {open_sig.entry}")
                    open_sig = None
                else:
                    print(f"[M1 Main] Trade still open ({open_sig.direction} @ {open_sig.entry}, "
                          f"{'in position' if open_sig.entered else 'waiting for fill'}) — skipping new analysis")

                time.sleep(config.POLL_INTERVAL_SEC)
                continue  # don't look for a new signal this bar

            # --- Fetch full data: H1 for trend, M1 for entry ---
            h1_candles = mt5_data.get_candles(config.SYMBOL, config.HTF, H1_CANDLE_COUNT)
            m1_candles = mt5_data.get_candles(config.SYMBOL, TIMEFRAME_M1, M1_CANDLE_COUNT)

            if h1_candles is None or m1_candles is None:
                print("[M1 Main] Failed to fetch candles — skipping")
                time.sleep(config.POLL_INTERVAL_SEC)
                continue

            # --- Analyze ---
            sig = signal_engine.analyze(h1_candles, m1_candles)

            if sig is None:
                print("[M1 Main] No signal this bar")
            else:
                print(f"[M1 Main] >>> SIGNAL: {sig.direction} | Entry={sig.entry} SL={sig.sl} TP={sig.tp}")
                msg = telegram_bot.format_signal(sig, timeframe="M1")
                print(msg)
                telegram_bot.send_message(msg)
                open_sig = OpenSignal(
                    direction=sig.direction, entry=sig.entry, sl=sig.sl, tp=sig.tp,
                    signal_time=sig.timestamp,
                )

            time.sleep(config.POLL_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n[M1 Main] Shutting down ...")
    finally:
        mt5_data.disconnect()
        print("[Main] Done.")


if __name__ == "__main__":
    main()
