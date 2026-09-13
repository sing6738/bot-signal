"""Signal engine — combines H1 trend with M15 entry zones."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

import config
from smc_core import (
    Zone, StructureResult,
    find_swing_points, detect_structure,
    find_order_blocks, find_fvg, find_supply_demand_zones,
    update_zones, detect_liquidity_sweep,
)


@dataclass
class Signal:
    direction: str        # "BUY" or "SELL"
    entry: float
    sl: float
    tp: float
    rr_ratio: float
    h1_trend: str         # "BULLISH" or "BEARISH"
    h1_event: str         # "CHoCH" or "BOS"
    confluence: list[str] # e.g. ["OB", "FVG"]
    timestamp: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _check_rsi_confirmation(m15_candles: pd.DataFrame, direction: str) -> bool:
    """Check RSI for oversold/overbought confirmation.

    BUY: RSI should be in oversold territory (<40) or showing bullish divergence.
    SELL: RSI should be in overbought territory (>60) or showing bearish divergence.
    """
    rsi = _rsi(m15_candles["close"])
    if rsi.isna().all():
        return True  # no data → don't block

    current_rsi = float(rsi.iloc[-1])
    recent_rsi = rsi.iloc[-10:]

    if direction == "BUY":
        # RSI oversold or recently was oversold (momentum shifting up)
        if current_rsi < 45 or recent_rsi.min() < 35:
            return True
        return False
    else:
        # RSI overbought or recently was overbought (momentum shifting down)
        if current_rsi > 55 or recent_rsi.max() > 65:
            return True
        return False


def _in_session(timestamp) -> bool:
    """Check if timestamp falls in configured trading sessions (UTC)."""
    if isinstance(timestamp, pd.Timestamp):
        hour = timestamp.hour
    elif isinstance(timestamp, datetime):
        hour = timestamp.hour
    else:
        return True

    for start_h, end_h in config.SESSION_HOURS_UTC:
        if start_h <= hour < end_h:
            return True
    return False


def _premium_discount_ok(direction: str, current_price: float,
                          m15_candles: pd.DataFrame, lookback: int = 50) -> bool:
    """Check price isn't in the extreme wrong zone.

    BUY: reject only if price is in the top 20% of recent range (extreme premium).
    SELL: reject only if price is in the bottom 20% of recent range (extreme discount).
    """
    recent = m15_candles.iloc[-lookback:]
    range_high = float(recent["high"].max())
    range_low = float(recent["low"].min())
    range_size = range_high - range_low

    if range_size < 0.1:
        return True  # no significant range

    pct = (current_price - range_low) / range_size  # 0.0=bottom, 1.0=top
    threshold = getattr(config, "PREMIUM_DISCOUNT_THRESHOLD", 0.50)

    if direction == "BUY":
        return pct <= threshold  # BUY in discount zone
    else:
        return pct >= (1.0 - threshold)  # SELL in premium zone


def _find_confluence(zones: list[Zone], direction: str,
                     current_price: float) -> list[Zone]:
    """Filter zones matching direction and near current price, then group
    overlapping / proximate zones as confluence."""
    matching = [
        z for z in zones
        if z.direction == direction and z.is_valid
    ]
    if not matching:
        return []

    # Keep zones that current price is approaching (within proximity)
    proximity = config.CONFLUENCE_PROXIMITY
    near: list[Zone] = []

    for z in matching:
        if direction == "BULLISH":
            # Price approaching from above — zone should be below current price
            if current_price - z.high < proximity and current_price >= z.low:
                near.append(z)
            elif z.low <= current_price <= z.high:
                near.append(z)
        else:
            # Price approaching from below — zone should be above current price
            if z.low - current_price < proximity and current_price <= z.high:
                near.append(z)
            elif z.low <= current_price <= z.high:
                near.append(z)

    return near


def _cluster_zones(zones: list[Zone]) -> list[list[Zone]]:
    """Group zones that overlap or are within CONFLUENCE_PROXIMITY of each other."""
    if not zones:
        return []

    proximity = config.CONFLUENCE_PROXIMITY
    sorted_zones = sorted(zones, key=lambda z: z.low)
    clusters: list[list[Zone]] = [[sorted_zones[0]]]

    for z in sorted_zones[1:]:
        last_cluster = clusters[-1]
        cluster_high = max(cz.high for cz in last_cluster)
        if z.low - cluster_high <= proximity:
            last_cluster.append(z)
        else:
            clusters.append([z])

    return clusters


def _calc_sl_tp(direction: str, zones: list[Zone],
                m15_candles: pd.DataFrame) -> tuple[float, float, float]:
    """Calculate entry, SL, TP from a cluster of zones.

    Uses swing structure for SL placement when available.
    """
    buf = config.SL_BUFFER
    rr = config.RR_RATIO

    # Find recent swing lows/highs from M15 for better SL placement
    recent = m15_candles.iloc[-30:]
    recent_swing_lows = []
    recent_swing_highs = []
    highs = recent["high"].values
    lows = recent["low"].values
    for i in range(2, len(recent) - 2):
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            recent_swing_lows.append(lows[i])
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            recent_swing_highs.append(highs[i])

    entry_mode = getattr(config, "ENTRY_MODE", "equilibrium")
    ob_zones = [z for z in zones if z.zone_type == "OB"]

    if direction == "BUY":
        lowest = min(zones, key=lambda z: z.low)
        target_ob = min(ob_zones, key=lambda z: z.low) if ob_zones else lowest
        if entry_mode == "equilibrium":
            entry = (target_ob.high + target_ob.low) / 2.0
        else:
            entry = lowest.high  # proximal edge

        # SL: use the lower of zone bottom or recent swing low
        sl_zone = lowest.low - buf
        if recent_swing_lows:
            # Find the swing low closest to (but below) the zone
            below_zone = [s for s in recent_swing_lows if s < lowest.low]
            if below_zone:
                sl_swing = max(below_zone) - buf  # closest swing low below zone
                sl = min(sl_zone, sl_swing)  # use the tighter one
            else:
                sl = sl_zone
        else:
            sl = sl_zone

        tp = entry + (entry - sl) * rr
    else:
        highest = max(zones, key=lambda z: z.high)
        target_ob = max(ob_zones, key=lambda z: z.high) if ob_zones else highest
        if entry_mode == "equilibrium":
            entry = (target_ob.high + target_ob.low) / 2.0
        else:
            entry = highest.low  # proximal edge

        # SL: use the higher of zone top or recent swing high
        sl_zone = highest.high + buf
        if recent_swing_highs:
            above_zone = [s for s in recent_swing_highs if s > highest.high]
            if above_zone:
                sl_swing = min(above_zone) + buf
                sl = max(sl_zone, sl_swing)
            else:
                sl = sl_zone
        else:
            sl = sl_zone

        tp = entry - (sl - entry) * rr

    return round(entry, 2), round(sl, 2), round(tp, 2)


def analyze(h1_candles: pd.DataFrame,
            m15_candles: pd.DataFrame) -> Signal | None:
    """Run full analysis pipeline.

    1. H1 → swing points → structure (CHoCH/BOS) → trend direction
    2. EMA50 + EMA slope filters
    3. Session filter (London/NY only)
    4. Premium/Discount zone check
    5. M15 → find OB, FVG, Supply/Demand zones → update zones
    6. Check confluence ≥ MIN_CONFLUENCE (must include OB)
    7. RSI confirmation
    8. Calculate entry / SL / TP with swing-aware placement
    """
    # --- Step 1: H1 trend ---
    h1_swings = find_swing_points(h1_candles)
    structure = detect_structure(h1_swings, h1_candles)

    print(f"  [DBG] H1 swings: {len(h1_swings)} | trend={structure.trend} event={structure.event_type}")

    if structure.trend == "NEUTRAL":
        print("  [DBG] [X] H1 trend NEUTRAL -- skip")
        return None

    # EMA50 trend filter — don't trade against the major trend
    ema50_series = h1_candles["close"].ewm(span=50, min_periods=20).mean()
    ema50 = float(ema50_series.iloc[-1])
    ema50_prev = float(ema50_series.iloc[-10]) if len(ema50_series) >= 10 else ema50
    h1_close = float(h1_candles["close"].iloc[-1])
    ema_slope_up = ema50 > ema50_prev
    print(f"  [DBG] H1 close={h1_close:.2f} EMA50={ema50:.2f} slope={'UP' if ema_slope_up else 'DOWN'}")

    # Two independent checks that the swing-based trend can disagree with:
    #   1) price position relative to EMA50
    #   2) EMA50 slope direction
    # STRICT_TREND_ALIGNMENT=True (original behavior): BOTH must agree with
    # the swing trend, or skip. This is the tightest filter and can create
    # long "dead zones" during trend transitions (price crosses EMA50 before
    # swing structure catches up, or vice versa).
    # STRICT_TREND_ALIGNMENT=False (looser): skip only if BOTH disagree —
    # i.e. trade as long as at least one of the two still agrees with the
    # swing trend. Trades more often, at the cost of occasionally entering
    # during a live trend transition instead of waiting for full agreement.
    price_disagrees = (
        (structure.trend == "BEARISH" and h1_close > ema50) or
        (structure.trend == "BULLISH" and h1_close < ema50)
    )
    slope_disagrees = (
        (structure.trend == "BULLISH" and not ema_slope_up) or
        (structure.trend == "BEARISH" and ema_slope_up)
    )
    strict_alignment = getattr(config, "STRICT_TREND_ALIGNMENT", True)

    if strict_alignment:
        if price_disagrees:
            print("  [DBG] [X] Swing trend vs price-vs-EMA50 disagree -- skip (STRICT_TREND_ALIGNMENT=True)")
            return None
        if slope_disagrees:
            print("  [DBG] [X] Swing trend vs EMA50 slope disagree -- skip (STRICT_TREND_ALIGNMENT=True)")
            return None
    else:
        if price_disagrees and slope_disagrees:
            print("  [DBG] [X] Swing trend disagrees with BOTH price-vs-EMA50 AND slope -- skip")
            return None
        if price_disagrees or slope_disagrees:
            print("  [DBG] (!) Partial EMA disagreement allowed (STRICT_TREND_ALIGNMENT=False) -- continuing")

    direction = "BUY" if structure.trend == "BULLISH" else "SELL"
    zone_direction = structure.trend  # "BULLISH" or "BEARISH"
    h1_event = structure.event_type or "TREND"

    # --- Step 2: Session filter ---
    current_time = m15_candles["time"].iloc[-1]
    if not _in_session(current_time):
        print(f"  [DBG] [X] Outside trading session (hour={current_time.hour}) -- skip")
        return None

    # --- Step 3: Premium/Discount filter ---
    current_price = float(m15_candles["close"].iloc[-1])
    if not _premium_discount_ok(direction, current_price, m15_candles):
        print(f"  [DBG] [X] {direction} but price not in {'discount' if direction == 'BUY' else 'premium'} zone -- skip")
        return None

    # --- Step 4: M15 zones ---
    n_bars = len(m15_candles)
    obs = find_order_blocks(m15_candles)
    fvgs = find_fvg(m15_candles)
    sd_zones = find_supply_demand_zones(m15_candles)

    print(f"  [DBG] M15 zones raw: OB={len(obs)} FVG={len(fvgs)} SD={len(sd_zones)} | price={current_price:.2f}")

    # Update (remove filled/expired/old)
    all_zones = update_zones(obs + fvgs + sd_zones, current_price,
                             current_bar_index=n_bars - 1)

    print(f"  [DBG] M15 zones valid: {len(all_zones)}")

    # --- Step 5: Confluence ---
    near_zones = _find_confluence(all_zones, zone_direction, current_price)

    print(f"  [DBG] Near zones ({zone_direction}): {len(near_zones)} (need >={config.MIN_CONFLUENCE})")
    for z in near_zones[:5]:
        print(f"        {z.zone_type} {z.direction} [{z.low:.2f} - {z.high:.2f}]")

    if len(near_zones) < config.MIN_CONFLUENCE:
        print("  [DBG] [X] Not enough confluence -- skip")
        return None

    # Cluster and pick the best cluster (most zones)
    clusters = _cluster_zones(near_zones)
    best_cluster = max(clusters, key=len)

    print(f"  [DBG] Best cluster: {len(best_cluster)} zones")

    if len(best_cluster) < config.MIN_CONFLUENCE:
        print("  [DBG] [X] Best cluster too small -- skip")
        return None

    # Unique zone types in cluster
    confluence_types = list({z.zone_type for z in best_cluster})

    # --- Require OB in confluence ---
    has_ob = any(z.zone_type == "OB" for z in best_cluster)
    if not has_ob:
        print("  [DBG] [X] No OB in confluence cluster -- skip")
        return None

    # --- Step 6: Liquidity Sweep Check ---
    bull_sw, bear_sw = detect_liquidity_sweep(m15_candles)
    has_sweep = (direction == "BUY" and bull_sw) or (direction == "SELL" and bear_sw)
    if has_sweep:
        confluence_types.append("SWEEP")
        print(f"  [DBG] Liquidity Sweep confirmed for {direction}")
    elif getattr(config, "REQUIRE_LIQUIDITY_SWEEP", False):
        print(f"  [DBG] [X] No recent Liquidity Sweep for {direction} -- skip")
        return None

    # --- Step 7: RSI confirmation ---
    if not _check_rsi_confirmation(m15_candles, direction):
        print(f"  [DBG] [X] RSI not confirming {direction} -- skip")
        return None

    # --- Step 8: Entry / SL / TP ---
    entry, sl, tp = _calc_sl_tp(direction, best_cluster, m15_candles)

    # SL range check
    sl_pips = abs(entry - sl) / 0.1
    if sl_pips > config.MAX_SL_PIPS:
        print(f"  [DBG] [X] SL too wide: {sl_pips:.0f} pips > {config.MAX_SL_PIPS} -- skip")
        return None
    if sl_pips < config.MIN_SL_PIPS:
        print(f"  [DBG] [X] SL too tight: {sl_pips:.0f} pips < {config.MIN_SL_PIPS} -- skip")
        return None

    # Sanity: TP must be in the right direction
    if direction == "BUY" and tp <= entry:
        print(f"  [DBG] [X] BUY but TP <= entry -- skip")
        return None
    if direction == "SELL" and tp >= entry:
        print(f"  [DBG] [X] SELL but TP >= entry -- skip")
        return None

    print(f"  [DBG] >>> SIGNAL {direction} entry={entry} sl={sl} tp={tp} SL={sl_pips:.0f}pips conf={confluence_types}")

    return Signal(
        direction=direction,
        entry=entry,
        sl=sl,
        tp=tp,
        rr_ratio=config.RR_RATIO,
        h1_trend=structure.trend,
        h1_event=h1_event,
        confluence=confluence_types,
        timestamp=m15_candles["time"].iloc[-1].to_pydatetime(),
    )
