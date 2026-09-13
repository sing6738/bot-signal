"""XAUUSD SMC Signal Bot — [M5 Scalper] Entry Point.

Polls MT5 every POLL_INTERVAL_SEC seconds. When a new M5 candle closes,
runs the full SMC analysis (H1 trend -> M5 entry) and sends a Telegram alert if a signal is found.
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

TIMEFRAME_M5 = 5  # mt5.TIMEFRAME_M5


def main():
    print("=" * 50)
    print("  XAUUSD SMC Signal Bot — [M5 Scalper]")
    print(f"  H1 trend -> M5 entry | RR 1:{config.RR_RATIO}")
    print(f"  Min confluence: {config.MIN_CONFLUENCE}/4")
    print("=" * 50)

    # --- Connect MT5 ---
    for attempt in range(1, 4):
        if mt5_data.connect():
            break
        print(f"[M5 Main] MT5 connect retry {attempt}/3 ...")
        time.sleep(5)
    else:
        msg = "❌ ไม่สามารถเชื่อมต่อ MT5 ได้ — บอท M5 หยุดทำงาน"
        print(msg)
        telegram_bot.send_message(msg)
        sys.exit(1)

    last_m5_time = None
    print(f"[M5 Main] Polling every {config.POLL_INTERVAL_SEC}s for new M5 candle ...")

    try:
        while True:
            # Fetch latest M5 candle to check if a new bar closed
            m5_check = mt5_data.get_candles(config.SYMBOL, TIMEFRAME_M5, 2)
            if m5_check is None:
                print("[M5 Main] Failed to fetch M5 candles — retrying next cycle")
                time.sleep(config.POLL_INTERVAL_SEC)
                continue

            current_m5_time = m5_check["time"].iloc[-2]  # last *closed* bar

            if last_m5_time is not None and current_m5_time <= last_m5_time:
                # No new bar yet
                time.sleep(config.POLL_INTERVAL_SEC)
                continue

            last_m5_time = current_m5_time
            now = datetime.now().strftime("%H:%M:%S")
            print(f"\n[{now}] New M5 candle closed ({current_m5_time}) — analyzing ...")

            # --- Fetch full data: H1 for trend, M5 for entry ---
            h1_candles = mt5_data.get_candles(config.SYMBOL, config.HTF, config.CANDLE_COUNT)
            m5_candles = mt5_data.get_candles(config.SYMBOL, TIMEFRAME_M5, config.CANDLE_COUNT)

            if h1_candles is None or m5_candles is None:
                print("[M5 Main] Failed to fetch candles — skipping")
                time.sleep(config.POLL_INTERVAL_SEC)
                continue

            # --- Analyze ---
            sig = signal_engine.analyze(h1_candles, m5_candles)

            if sig is None:
                print("[M5 Main] No signal this bar")
            else:
                print(f"[M5 Main] >>> SIGNAL: {sig.direction} | Entry={sig.entry} SL={sig.sl} TP={sig.tp}")
                
                # Dynamic Lot Sizing: 0.01 per confluence (min 4 signals required by config)
                lot_size = len(sig.confluence) * 0.01
                
                # --- Execute Trade ---
                order_res = mt5_data.place_order(
                    symbol=config.SYMBOL,
                    direction=sig.direction,
                    lot=lot_size,
                    entry=sig.entry,
                    sl=sig.sl,
                    tp=sig.tp,
                    comment=f"SMC M5 {'+'.join(sig.confluence)}"
                )

                exec_status = "✅ Trade Executed" if order_res else "❌ Execution Failed"
                msg = telegram_bot.format_signal(sig, timeframe="M5")
                msg = f"{exec_status}\nLot Size: {lot_size}\n\n{msg}"
                
                print(msg)
                telegram_bot.send_message(msg)

            time.sleep(config.POLL_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n[M5 Main] Shutting down ...")
    finally:
        mt5_data.disconnect()
        print("[Main] Done.")


if __name__ == "__main__":
    main()
