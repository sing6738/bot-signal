"""XAUUSD SMC Signal Bot — Main entry point.

Polls MT5 every POLL_INTERVAL_SEC seconds. When a new M15 candle closes,
runs the full SMC analysis and sends a Telegram alert if a signal is found.
"""

import time
import sys
from datetime import datetime

# Prevent UnicodeEncodeError on Windows terminals (cp874 etc.) and flush immediately
sys.stdout.reconfigure(line_buffering=True, errors="replace")

import config
import mt5_data
import signal_engine
import telegram_bot


def main():
    print("=" * 50)
    print("  XAUUSD SMC Signal Bot")
    print(f"  H1 trend -> M15 entry | RR 1:{config.RR_RATIO}")
    print(f"  Min confluence: {config.MIN_CONFLUENCE}/4")
    print("=" * 50)

    # --- Connect MT5 ---
    for attempt in range(1, 4):
        if mt5_data.connect():
            break
        print(f"[Main] MT5 connect retry {attempt}/3 ...")
        time.sleep(5)
    else:
        msg = "❌ ไม่สามารถเชื่อมต่อ MT5 ได้ — บอทหยุดทำงาน"
        print(msg)
        telegram_bot.send_message(msg)
        sys.exit(1)

    last_m15_time = None
    print(f"[Main] Polling every {config.POLL_INTERVAL_SEC}s for new M15 candle ...")

    try:
        while True:
            # Fetch latest M15 candle to check if a new bar closed
            m15_check = mt5_data.get_candles(config.SYMBOL, config.LTF, 2)
            if m15_check is None:
                print("[Main] Failed to fetch M15 candles — retrying next cycle")
                time.sleep(config.POLL_INTERVAL_SEC)
                continue

            current_m15_time = m15_check["time"].iloc[-2]  # last *closed* bar

            if last_m15_time is not None and current_m15_time <= last_m15_time:
                # No new bar yet
                time.sleep(config.POLL_INTERVAL_SEC)
                continue

            last_m15_time = current_m15_time
            now = datetime.now().strftime("%H:%M:%S")
            print(f"\n[{now}] New M15 candle closed — analyzing ...")

            # --- Fetch full data ---
            h1_candles = mt5_data.get_candles(config.SYMBOL, config.HTF, config.CANDLE_COUNT)
            m15_candles = mt5_data.get_candles(config.SYMBOL, config.LTF, config.CANDLE_COUNT)

            if h1_candles is None or m15_candles is None:
                print("[Main] Failed to fetch candles — skipping")
                time.sleep(config.POLL_INTERVAL_SEC)
                continue

            # --- Analyze ---
            sig = signal_engine.analyze(h1_candles, m15_candles)

            if sig is None:
                print("[Main] No signal this bar")
            else:
                print(f"[Main] >>> SIGNAL: {sig.direction} | Entry={sig.entry} SL={sig.sl} TP={sig.tp}")
                msg = telegram_bot.format_signal(sig)
                print(msg)
                telegram_bot.send_message(msg)

            time.sleep(config.POLL_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n[Main] Shutting down ...")
    finally:
        mt5_data.disconnect()
        print("[Main] Done.")


if __name__ == "__main__":
    main()
