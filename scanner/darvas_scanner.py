#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
"""
╔══════════════════════════════════════════════════════════════╗
║          DARVAS BOX SCANNER  —  NSE / Chartink              ║
║                                                              ║
║  Workflow:                                                   ║
║  1. Paste comma-separated symbols from Chartink             ║
║  2. Script fetches 400 days of daily OHLCV (yfinance)       ║
║  3. Resamples to weekly, runs Darvas box state machine       ║
║     (mirrors Pine Script logic exactly)                     ║
║  4. Classifies each stock:                                   ║
║       🚀 FRESH BREAKOUT  — buy signal today                 ║
║       ⚠️  APPROACHING    — within X% of ceiling             ║
║       👀 WATCHING        — box confirmed, wait              ║
║       📦 BOX FORMING     — ceiling/floor still pending      ║
║  5. Prints ranked table + saves CSV                         ║
╚══════════════════════════════════════════════════════════════╝

Usage:
    python darvas_scanner.py                        # uses built-in symbols
    python darvas_scanner.py --symbols "NTPC,CANBK"
    python darvas_scanner.py --file my_symbols.txt
"""

import argparse
import os
import sys
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf
from tabulate import tabulate

warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION  (mirrors Pine Script V2 defaults)
# ══════════════════════════════════════════════════════════════
CONFIG = {
    # Box detection (weekly bars)
    "ceil_bars":       3,      # consecutive weeks NOT making a new high
    "floor_bars":      3,      # consecutive weeks NOT making a new low

    # Breakout filter
    "atr_mult_bo":     0.1,    # close must exceed ceiling by this many daily ATRs
    "atr_period":      14,     # ATR period (daily bars)

    # Volume filter
    "vol_len":         20,     # volume SMA period (daily bars)
    "vol_mult":        1.5,    # volume surge multiplier
    "require_vol":     True,   # require volume surge for BREAKOUT classification

    # Stop loss
    "sl_buffer_pct":   0.5,    # stop placed this % below box floor

    # Quality filters
    "min_rr":          1.0,    # minimum R:R ratio to classify as quality breakout
    "max_box_width":   35.0,   # ignore boxes wider than this % (too wide = not Darvas)

    # Urgency tiers for APPROACHING stocks
    # HOT  = imminent breakout — set TradingView alert + consider starter position
    # WARM = closing in       — set TradingView alert today
    "hot_dist_pct":    2.0,    # HOT if within this % of ceiling
    "hot_vol_mult":    2.0,    # HOT requires this vol surge (elevated demand visible)
    "warm_dist_pct":   4.0,    # WARM if within this % of ceiling
    "warm_vol_mult":   1.3,    # WARM requires at least this vol (above average)

    # Scanner / watchlist settings
    "history_days":    420,    # days of history to download (>52 weeks)
    "proximity_pct":   7.0,    # flag APPROACHING when within this % of ceiling
    "watchlist_days":  45,     # auto-expire watchlist entries after N days without breakout
}

# ── NSE symbol overrides for yfinance (special characters, etc.) ──
SYMBOL_MAP = {
    "GMRP&UI": "GMRPUI",
}

# ── Watchlist persistent storage path ────────────────────────
WATCHLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.csv")
WATCHLIST_COLS = [
    "symbol", "date_added", "date_updated", "prev_status", "status",
    "box_ceiling", "box_floor", "box_width_pct", "sl_price",
    "mm_target", "days_in_box", "source",
    # Position tracking (set when an order is placed)
    "entry_price", "qty", "notes",
]

# ── Default universe (from Chartink paste) ───────────────────
DEFAULT_SYMBOLS = (
    "KRN,CENTUM,VESUVIUS,DOLPHIN,UEL,GLOBAL,BAJAJCON,HAPPYFORGE,SILVERTUC,"
    "GAEL,YATHARTH,WANBURY,ELDEHSG,HINDALCO,SIEMENS,CANBK,NETWEB,ADVENZYMES,"
    "NTPC,VTL,ABSLAMC,DATAPATTNS,GMRP&UI,CIEINDIA,NAVINFLUOR,TATACOMM,"
    "SBILIFE,COALINDIA,NITINSPIN,FORTIS,ONGC,AZAD,SCHAEFFLER,GMDCLTD,"
    "CHEVIOT,POLYCAB,SOBHA,BANDHANBNK,GAIL,RAMRAT,AADHARHFC,SUNTECK,TMB,"
    "PRIVISCL,ICICIPRULI,BIOCON"
)

STATUS_PRIORITY = {
    "FRESH BREAKOUT": 0,
    "APPROACHING":    1,
    "WATCHING":       2,
    "BOX FORMING":    3,
    "NO BOX":         4,
}

STATUS_EMOJI = {
    "FRESH BREAKOUT": "[BREAKOUT]",
    "APPROACHING":    "[APPROACH]",
    "WATCHING":       "[WATCH]   ",
    "BOX FORMING":    "[FORMING] ",
    "NO BOX":         "[NO BOX]  ",
}


# ══════════════════════════════════════════════════════════════
#  DATA FETCHING
# ══════════════════════════════════════════════════════════════

def fetch_daily(symbol: str, days: int = 420) -> pd.DataFrame | None:
    """
    Download daily OHLCV for an NSE symbol via yfinance.
    Handles MultiIndex columns from newer yfinance versions.
    Returns None if data is insufficient.
    """
    yf_sym = SYMBOL_MAP.get(symbol, symbol) + ".NS"
    end    = datetime.today()
    start  = end - timedelta(days=days)

    try:
        df = yf.download(yf_sym, start=start, end=end,
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None

        # ── Flatten MultiIndex columns (yfinance ≥ 0.2.x) ──────
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # ── Normalise column names to Title Case ────────────────
        df.columns = [c.strip().title() for c in df.columns]

        # Must have the basics
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(set(df.columns)):
            return None

        df = df[list(required)].copy()
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        # Need at least 60 trading days (≈3 months) of data
        if len(df) < 60:
            return None

        return df

    except Exception:
        return None


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """
    Resample daily OHLCV to weekly (week ending Friday).
    Mirrors TradingView's weekly bar construction.
    """
    weekly = daily.resample("W-FRI").agg(
        Open=("Open",   "first"),
        High=("High",   "max"),
        Low=("Low",     "min"),
        Close=("Close", "last"),
        Volume=("Volume","sum"),
    ).dropna(subset=["Close"])
    return weekly


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's Average True Range on a daily DataFrame."""
    h  = df["High"]
    lo = df["Low"]
    c  = df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, min_periods=period, adjust=False).mean()


# ══════════════════════════════════════════════════════════════
#  DARVAS BOX DETECTOR  (exact mirror of Pine Script V2 logic)
# ══════════════════════════════════════════════════════════════

def detect_box(weekly: pd.DataFrame, cfg: dict) -> dict:
    """
    Run the Darvas box state machine on weekly bars.

    Logic (identical to Pine Script):
      - pendingCeiling = highest weekly high seen
      - Each new week: if prev week's high <= pendingCeiling → ceilConfCount++
                       else → reset pendingCeiling to prev week's high
      - Same for floor (tracking lows)
      - When BOTH ceilConfCount >= ceil_bars AND floorConfCount >= floor_bars
        → box is CONFIRMED
      - After confirmation, reset counts and start tracking next box

    Returns dict with last confirmed box + current pending state.
    """
    ceil_bars  = cfg["ceil_bars"]
    floor_bars = cfg["floor_bars"]

    pending_ceil   = None
    pending_floor  = None
    ceil_conf      = 0
    floor_conf     = 0

    box_ceiling    = None
    box_floor      = None
    box_conf_date  = None

    rows = weekly.reset_index()

    for i in range(1, len(rows)):
        prev_high = float(rows.loc[i - 1, "High"])
        prev_low  = float(rows.loc[i - 1, "Low"])
        curr_high = float(rows.loc[i,     "High"])
        curr_low  = float(rows.loc[i,     "Low"])

        # ── Ceiling tracking ──────────────────────────────────
        if pending_ceil is None:
            pending_ceil = prev_high
            ceil_conf    = 0
        elif prev_high <= pending_ceil:
            ceil_conf += 1
        else:
            pending_ceil = prev_high
            ceil_conf    = 0

        # ── Floor tracking ────────────────────────────────────
        if pending_floor is None:
            pending_floor = prev_low
            floor_conf    = 0
        elif prev_low >= pending_floor:
            floor_conf += 1
        else:
            pending_floor = prev_low
            floor_conf    = 0

        # ── Box confirmed when both counts reach threshold ────
        if ceil_conf >= ceil_bars and floor_conf >= floor_bars:
            box_ceiling   = pending_ceil
            box_floor     = pending_floor
            box_conf_date = rows.loc[i, "Date"] if "Date" in rows.columns else rows.index[i]

            # Reset — start hunting for next box
            ceil_conf     = 0
            floor_conf    = 0
            pending_ceil  = curr_high
            pending_floor = curr_low

    return {
        "box_ceiling":   box_ceiling,
        "box_floor":     box_floor,
        "box_conf_date": box_conf_date,
        "pending_ceil":  pending_ceil,
        "pending_floor": pending_floor,
        "ceil_conf":     ceil_conf,
        "floor_conf":    floor_conf,
    }


# ══════════════════════════════════════════════════════════════
#  FULL SYMBOL ANALYSIS
# ══════════════════════════════════════════════════════════════

def analyse(symbol: str, cfg: dict) -> dict | None:
    """
    Complete Darvas analysis for one symbol.
    Returns a result dict or None if data unavailable.
    """
    daily = fetch_daily(symbol, cfg["history_days"])
    if daily is None:
        return None

    weekly = to_weekly(daily)
    if len(weekly) < cfg["ceil_bars"] + cfg["floor_bars"] + 2:
        return None

    box   = detect_box(weekly, cfg)
    atr_s = calc_atr(daily, cfg["atr_period"])

    # ── Latest daily values ───────────────────────────────────
    latest    = daily.iloc[-1]
    prev_bar  = daily.iloc[-2] if len(daily) > 1 else latest
    close     = float(latest["Close"])
    prev_close= float(prev_bar["Close"])
    vol_today = float(latest["Volume"])
    atr_val   = float(atr_s.iloc[-1]) if not pd.isna(atr_s.iloc[-1]) else 0.0
    vol_sma   = float(daily["Volume"].rolling(cfg["vol_len"]).mean().iloc[-1])
    vol_ratio = vol_today / vol_sma if vol_sma > 0 else 0.0

    box_ceil  = box["box_ceiling"]
    box_floor = box["box_floor"]

    # ── Case: No confirmed box yet ────────────────────────────
    if box_ceil is None:
        # Report box-forming progress
        weeks_needed = max(cfg["ceil_bars"] - box["ceil_conf"],
                           cfg["floor_bars"] - box["floor_conf"])
        return {
            "symbol":       symbol,
            "status":       "BOX FORMING",
            "close":        round(close, 2),
            "box_ceiling":  round(box["pending_ceil"],  2) if box["pending_ceil"]  else None,
            "box_floor":    round(box["pending_floor"], 2) if box["pending_floor"] else None,
            "box_width_pct":None,
            "dist_to_ceil": None,
            "sl_price":     None,
            "mm_target":    None,
            "risk_pct":     None,
            "rr_ratio":     None,
            "vol_ratio":    round(vol_ratio, 2),
            "days_in_box":  None,
            "weeks_to_confirm": weeks_needed,
            "ceil_conf":    box["ceil_conf"],
            "floor_conf":   box["floor_conf"],
        }

    # ── Box metrics ───────────────────────────────────────────
    box_width_pct = (box_ceil - box_floor) / box_floor * 100

    # Skip boxes that are way too wide (not Darvas-style)
    if box_width_pct > cfg["max_box_width"]:
        return None

    sl_price  = box_floor * (1.0 - cfg["sl_buffer_pct"] / 100.0)
    mm_target = box_ceil  + (box_ceil - box_floor)     # measured move

    dist_to_ceil = (box_ceil - close) / close * 100   # +ve = below ceiling

    # Days since box was confirmed
    days_in_box = None
    if box["box_conf_date"] is not None:
        try:
            conf = pd.Timestamp(box["box_conf_date"])
            days_in_box = (pd.Timestamp.today() - conf).days
        except Exception:
            pass

    # ── Classify status ───────────────────────────────────────
    breakout_raw   = close > (box_ceil + atr_val * cfg["atr_mult_bo"])
    vol_ok         = (vol_ratio >= cfg["vol_mult"]) if cfg["require_vol"] else True
    fresh_breakout = breakout_raw and vol_ok and (prev_close <= box_ceil)

    if fresh_breakout:
        status = "FRESH BREAKOUT"
    elif breakout_raw and vol_ok:
        status = "WATCHING"          # already above ceiling (prior breakout)
    elif 0 <= dist_to_ceil <= cfg["proximity_pct"]:
        status = "APPROACHING"
    elif dist_to_ceil > 0:
        status = "WATCHING"
    else:
        status = "WATCHING"          # above ceiling but no volume — still watching

    # ── Risk / reward ─────────────────────────────────────────
    risk_pct   = (close - sl_price)  / close * 100 if close > 0 else None
    reward_pct = (mm_target - close) / close * 100 if close > 0 else None
    rr_ratio   = reward_pct / risk_pct if (risk_pct and risk_pct > 0) else None

    # ── Urgency tier (for APPROACHING stocks) ────────────────
    alert_tier = ""
    if status == "APPROACHING":
        if (dist_to_ceil <= cfg["hot_dist_pct"]
                and vol_ratio >= cfg["hot_vol_mult"]):
            alert_tier = "HOT"
        elif (dist_to_ceil <= cfg["warm_dist_pct"]
                and vol_ratio >= cfg["warm_vol_mult"]):
            alert_tier = "WARM"
        else:
            alert_tier = "WATCH"
    elif status == "WATCHING" and vol_ratio >= cfg["hot_vol_mult"] * 1.5:
        # High-volume WATCHING stock — elevated demand even far from ceiling
        alert_tier = "VOL-SURGE"

    return {
        "symbol":        symbol,
        "status":        status,
        "alert_tier":    alert_tier,
        "close":         round(close, 2),
        "box_ceiling":   round(box_ceil, 2),
        "box_floor":     round(box_floor, 2),
        "box_width_pct": round(box_width_pct, 1),
        "dist_to_ceil":  round(dist_to_ceil, 1),
        "sl_price":      round(sl_price, 2),
        "mm_target":     round(mm_target, 2),
        "risk_pct":      round(risk_pct, 1)  if risk_pct  else None,
        "rr_ratio":      round(rr_ratio, 2)  if rr_ratio  else None,
        "vol_ratio":     round(vol_ratio, 2),
        "days_in_box":   days_in_box,
        "ceil_conf":     box["ceil_conf"],
        "floor_conf":    box["floor_conf"],
    }


# ══════════════════════════════════════════════════════════════
#  OUTPUT FORMATTING
# ══════════════════════════════════════════════════════════════

def fmt(val, prefix="₹", suffix="", decimals=2, na="-"):
    """Format a numeric value for table display."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return na
    if prefix == "₹":
        return f"₹{val:,.{decimals}f}{suffix}"
    return f"{val:.{decimals}f}{suffix}"


def print_category(results: list[dict], status: str) -> None:
    """Print a formatted table for one status category."""
    cat = [r for r in results if r["status"] == status]
    if not cat:
        return

    emoji = STATUS_EMOJI.get(status, "")
    print(f"\n{'-' * 72}")
    print(f"  {emoji}  {status}  ({len(cat)} stock{'s' if len(cat) != 1 else ''})")
    print(f"{'-' * 72}")

    if status == "FRESH BREAKOUT":
        headers = ["Symbol", "Close", "Ceiling", "Floor", "Width%",
                   "SL", "Target", "Risk%", "R:R", "Vol×", "Days"]
        rows = [[
            r["symbol"],
            fmt(r["close"]),
            fmt(r["box_ceiling"]),
            fmt(r["box_floor"]),
            fmt(r["box_width_pct"], prefix="", suffix="%", decimals=1),
            fmt(r["sl_price"]),
            fmt(r["mm_target"]),
            fmt(r["risk_pct"], prefix="", suffix="%", decimals=1),
            fmt(r["rr_ratio"], prefix="", decimals=2),
            fmt(r["vol_ratio"], prefix="", suffix="×", decimals=2),
            r["days_in_box"] or "-",
        ] for r in cat]

    elif status == "APPROACHING":
        # Sort HOT first, then WARM, then WATCH, then by distance
        tier_order = {"HOT": 0, "WARM": 1, "WATCH": 2, "": 3}
        cat = sorted(cat, key=lambda r: (
            tier_order.get(r.get("alert_tier", ""), 3),
            r.get("dist_to_ceil", 999)
        ))
        headers = ["Tier", "Symbol", "Close", "Ceiling", "Dist%",
                   "Width%", "Vol x", "Days", "Action"]
        rows = []
        for r in cat:
            tier = r.get("alert_tier", "")
            if tier == "HOT":
                action = "!! SET ALERT + consider starter pos"
            elif tier == "WARM":
                action = "Set TradingView alert today"
            else:
                action = "Monitor"
            rows.append([
                tier,
                r["symbol"],
                fmt(r["close"]),
                fmt(r["box_ceiling"]),
                fmt(r.get("dist_to_ceil"), prefix="", suffix="%", decimals=1),
                fmt(r["box_width_pct"], prefix="", suffix="%", decimals=1),
                fmt(r["vol_ratio"], prefix="", suffix="x", decimals=2),
                r["days_in_box"] or "-",
                action,
            ])

    elif status == "BOX FORMING":
        headers = ["Symbol", "Close", "Pend.Ceil", "Pend.Floor",
                   "Ceil✓", "Floor✓", "Weeks Left"]
        rows = [[
            r["symbol"],
            fmt(r["close"]),
            fmt(r["box_ceiling"]),
            fmt(r["box_floor"]),
            r.get("ceil_conf", "-"),
            r.get("floor_conf", "-"),
            r.get("weeks_to_confirm", "-"),
        ] for r in cat]

    else:  # WATCHING
        headers = ["Symbol", "Close", "Ceiling", "Dist%", "Floor",
                   "Width%", "Vol x", "Days", "Note"]
        rows = [[
            r["symbol"],
            fmt(r["close"]),
            fmt(r["box_ceiling"]),
            fmt(r.get("dist_to_ceil"), prefix="", suffix="%", decimals=1),
            fmt(r["box_floor"]),
            fmt(r["box_width_pct"], prefix="", suffix="%", decimals=1),
            fmt(r["vol_ratio"], prefix="", suffix="x", decimals=2),
            r["days_in_box"] or "-",
            r.get("_note", ""),
        ] for r in cat]

    print(tabulate(rows, headers=headers, tablefmt="simple"))


# ══════════════════════════════════════════════════════════════
#  WATCHLIST  —  persistent APPROACHING / WATCHING tracker
# ══════════════════════════════════════════════════════════════

def load_watchlist() -> pd.DataFrame:
    """Load the persistent watchlist CSV, or return an empty frame."""
    if os.path.exists(WATCHLIST_PATH):
        try:
            return pd.read_csv(WATCHLIST_PATH)
        except Exception:
            pass
    return pd.DataFrame(columns=WATCHLIST_COLS)


def save_watchlist(df: pd.DataFrame) -> None:
    """Persist the watchlist to disk."""
    df.to_csv(WATCHLIST_PATH, index=False)
    print(f"  >> Watchlist saved  : {WATCHLIST_PATH}  ({len(df)} stocks)")


def check_add_candidates(
    results: list[dict],
    wl: pd.DataFrame,
) -> list[dict]:
    """
    Cross-reference today's scan results against open positions in the watchlist.

    An ADD candidate is a stock where:
      1. The watchlist has a POSITION OPEN entry with a known entry_price.
      2. Today's scan found a *new* Darvas box whose ceiling is ABOVE the
         original entry price  (i.e. the stock has formed a higher box).
      3. The stock is now FRESH BREAKOUT or APPROACHING that higher ceiling
         (i.e. it's on the cusp of the next leg up).

    Returns a list of dicts, each containing the scan result enriched with
    the original position details for display.
    """
    if wl is None or len(wl) == 0:
        return []

    # Find open positions in the watchlist
    open_pos = wl[wl["status"] == "POSITION OPEN"] if "status" in wl.columns else wl.iloc[0:0]
    if len(open_pos) == 0:
        return []

    add_candidates = []
    result_map = {r["symbol"]: r for r in results}

    for _, pos in open_pos.iterrows():
        sym = pos["symbol"]
        if sym not in result_map:
            continue  # Not in today's scan — skip

        scan = result_map[sym]
        orig_entry = float(pos.get("entry_price") or 0)
        new_ceiling = scan.get("box_ceiling") or 0
        scan_status = scan.get("status", "")

        # A new, higher box must exist above original entry
        if orig_entry <= 0 or new_ceiling <= orig_entry:
            continue

        # Only flag if breakout imminent or happening
        if scan_status not in ("FRESH BREAKOUT", "APPROACHING"):
            continue

        tier = scan.get("alert_tier", "")
        candidate = scan.copy()
        candidate["_add_orig_entry"] = orig_entry
        candidate["_add_orig_qty"]   = int(pos.get("qty") or 0)
        candidate["_add_tier"]       = tier
        candidate["_add_gain_pct"]   = round((new_ceiling - orig_entry) / orig_entry * 100, 1)
        add_candidates.append(candidate)

    return add_candidates


def merge_into_watchlist(wl: pd.DataFrame, results: list[dict],
                         cfg: dict) -> pd.DataFrame:
    """
    Update the persistent watchlist with today's scan results.

    Rules:
      FRESH BREAKOUT  -> graduate (remove) from watchlist
      APPROACHING     -> add if new, update if existing
      WATCHING        -> add if new, update if existing
      BOX FORMING     -> update only if already in list
      Box failed      -> remove if price < floor (handled at scan time)
      Expired         -> remove if on list > watchlist_days without breakout
    """
    today     = datetime.now().strftime("%Y-%m-%d")
    max_days  = cfg.get("watchlist_days", 45)
    wl        = wl.copy()

    # Statuses managed externally -- scanner must never overwrite these
    PROTECTED_STATUSES = {"POSITION OPEN", "POSITION CLOSED", "MANUAL"}

    for r in results:
        sym    = r["symbol"]
        status = r["status"]
        exists = sym in wl["symbol"].values if len(wl) > 0 else False

        # Never touch rows the user has manually set (open positions etc.)
        if exists:
            current_status = wl.loc[wl["symbol"] == sym, "status"].iloc[0]
            if current_status in PROTECTED_STATUSES:
                continue

        if status == "FRESH BREAKOUT":
            # Graduate — remove from watchlist (mission accomplished)
            if exists:
                wl = wl[wl["symbol"] != sym]
            continue

        if status in ("APPROACHING", "WATCHING"):
            if exists:
                idx = wl.index[wl["symbol"] == sym][0]
                wl.at[idx, "prev_status"]  = wl.at[idx, "status"]
                wl.at[idx, "status"]       = status
                wl.at[idx, "date_updated"] = today
                wl.at[idx, "box_ceiling"]  = r.get("box_ceiling")
                wl.at[idx, "box_floor"]    = r.get("box_floor")
                wl.at[idx, "sl_price"]     = r.get("sl_price")
                wl.at[idx, "mm_target"]    = r.get("mm_target")
                wl.at[idx, "days_in_box"]  = r.get("days_in_box")
            else:
                new_row = {
                    "symbol":       sym,
                    "date_added":   today,
                    "date_updated": today,
                    "prev_status":  status,
                    "status":       status,
                    "box_ceiling":  r.get("box_ceiling"),
                    "box_floor":    r.get("box_floor"),
                    "box_width_pct":r.get("box_width_pct"),
                    "sl_price":     r.get("sl_price"),
                    "mm_target":    r.get("mm_target"),
                    "days_in_box":  r.get("days_in_box"),
                    "source":       r.get("_source", "chartink"),
                }
                wl = pd.concat([wl, pd.DataFrame([new_row])], ignore_index=True)

        elif status == "BOX FORMING" and exists:
            idx = wl.index[wl["symbol"] == sym][0]
            wl.at[idx, "date_updated"] = today
            wl.at[idx, "status"]       = status

    # ── Auto-expire entries older than watchlist_days ────────
    # Protected statuses (open positions etc.) are NEVER expired automatically
    if "date_added" in wl.columns and len(wl) > 0:
        wl["date_added"] = pd.to_datetime(wl["date_added"], errors="coerce")
        age = (pd.Timestamp.today() - wl["date_added"]).dt.days
        if "status" in wl.columns:
            protected_mask = wl["status"].isin(PROTECTED_STATUSES)
        else:
            protected_mask = pd.Series(False, index=wl.index)
        expired_mask = (age > max_days) & ~protected_mask
        expired = wl[expired_mask]["symbol"].tolist()
        if expired:
            print(f"  >> Expired from watchlist ({max_days}d): {', '.join(expired)}")
        wl = wl[~expired_mask]

    return wl


def annotate_status_changes(results: list[dict], wl: pd.DataFrame) -> list[dict]:
    """
    Add _note and _upgraded flag to results based on watchlist prev_status.
    Highlights when a stock has UPGRADED (WATCHING -> APPROACHING etc.)
    """
    if len(wl) == 0:
        return results

    upgrade_map = {"WATCHING": 2, "BOX FORMING": 3, "APPROACHING": 1, "FRESH BREAKOUT": 0}

    for r in results:
        sym = r["symbol"]
        match = wl[wl["symbol"] == sym]
        if len(match) == 0:
            r["_note"] = "NEW"
            r["_upgraded"] = False
            continue
        prev = match.iloc[0].get("prev_status", r["status"])
        curr = r["status"]
        prev_pri = upgrade_map.get(str(prev), 9)
        curr_pri = upgrade_map.get(curr, 9)
        if curr_pri < prev_pri:
            r["_note"]     = f"** UPGRADED from {prev} **"
            r["_upgraded"] = True
        else:
            r["_note"]     = ""
            r["_upgraded"] = False
    return results


# ══════════════════════════════════════════════════════════════
#  MAIN SCANNER
# ══════════════════════════════════════════════════════════════

def parse_symbols(raw: str) -> list[str]:
    """Parse a comma-separated symbol string."""
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def run_scan(chartink_symbols: list[str], cfg: dict) -> list[dict]:
    """
    Run the full Darvas scan.
    Merges today's Chartink symbols with the persistent watchlist,
    analyses all unique symbols, updates the watchlist, prints results.
    """
    SEP  = "=" * 72
    SEP2 = "-" * 72
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Load existing watchlist ──────────────────────────────
    wl = load_watchlist()
    wl_symbols = list(wl["symbol"].unique()) if len(wl) > 0 else []

    # ── Merge: Chartink + watchlist (deduplicated) ───────────
    all_symbols = list(dict.fromkeys(chartink_symbols + wl_symbols))
    chartink_set = set(chartink_symbols)

    print(f"\n{SEP}")
    print(f"  DARVAS BOX SCANNER  --  {timestamp}")
    print(f"  Chartink today : {len(chartink_symbols)} stocks")
    print(f"  Watchlist      : {len(wl_symbols)} stocks  ({WATCHLIST_PATH})")
    print(f"  Total to scan  : {len(all_symbols)} unique symbols")
    print(f"  RR filter      : >= {cfg['min_rr']}  |  Proximity: {cfg['proximity_pct']}%")
    print(SEP)

    results = []
    errors  = []

    for i, sym in enumerate(all_symbols, 1):
        src = "chartink" if sym in chartink_set else "watchlist"
        print(f"  [{i:2d}/{len(all_symbols)}] [{src:<9}] {sym:<15}", end="\r")
        sys.stdout.flush()

        res = analyse(sym, cfg)
        if res:
            res["_source"] = src
            res["_note"]   = ""
            res["_upgraded"] = False
            results.append(res)
        else:
            errors.append(sym)

    print(f"\n  OK: {len(results)} analysed   SKIP: {len(errors)} skipped\n")

    # ── Annotate upgrades from watchlist history ─────────────
    results = annotate_status_changes(results, wl)

    # ── Sort: priority first, then distance to ceiling ───────
    results.sort(key=lambda r: (
        0 if r.get("_upgraded") else 1,          # upgrades float to top
        STATUS_PRIORITY.get(r["status"], 9),
        r.get("dist_to_ceil") if r.get("dist_to_ceil") is not None else 999,
    ))

    # ── R:R quality split for FRESH BREAKOUT ─────────────────
    min_rr = cfg.get("min_rr", 1.0)
    bo_quality = [r for r in results
                  if r["status"] == "FRESH BREAKOUT"
                  and r.get("rr_ratio") is not None
                  and r["rr_ratio"] >= min_rr]
    bo_weak    = [r for r in results
                  if r["status"] == "FRESH BREAKOUT"
                  and (r.get("rr_ratio") is None or r["rr_ratio"] < min_rr)]

    # ── Print results ─────────────────────────────────────────
    if bo_quality:
        print(f"\n{SEP2}")
        print(f"  [BREAKOUT] FRESH BREAKOUT  -- R:R >= {min_rr}  ({len(bo_quality)} stocks)")
        print(SEP2)
        _print_breakout_table(bo_quality)

    if bo_weak:
        print(f"\n{SEP2}")
        print(f"  [BREAKOUT] FRESH BREAKOUT  -- R:R < {min_rr}  LOW R:R -- review carefully")
        print(SEP2)
        _print_breakout_table(bo_weak)

    for cat in ["APPROACHING", "WATCHING", "BOX FORMING"]:
        print_category(results, cat)

    # ── Summary ───────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  SUMMARY")
    print(SEP2)
    if bo_quality:
        print(f"  [BREAKOUT]  FRESH BREAKOUT (R:R OK)   : {len(bo_quality)}")
    if bo_weak:
        print(f"  [LOW RR]    FRESH BREAKOUT (Low R:R)  : {len(bo_weak)}")
    for cat in ["APPROACHING", "WATCHING", "BOX FORMING"]:
        count = sum(1 for r in results if r["status"] == cat)
        if count:
            lbl = STATUS_EMOJI.get(cat, "")
            print(f"  {lbl}  {cat:<22}: {count}")
    upgrades = [r for r in results if r.get("_upgraded")]
    if upgrades:
        print(f"\n  ** STATUS UPGRADES today : {', '.join(r['symbol'] for r in upgrades)}")

    # ── Open Positions: ADD? check ────────────────────────────
    add_candidates = check_add_candidates(results, wl)
    if add_candidates:
        print(f"\n{SEP}")
        print(f"  [ADD?] OPEN POSITIONS -- ADD CANDIDATES  ({len(add_candidates)} stocks)")
        print(f"  (New Darvas box formed ABOVE your entry -- breakout approaching)")
        print(SEP)
        for c in add_candidates:
            tier_label = f"  [{c.get('_add_tier','?')}] " if c.get('_add_tier') else "  "
            print(f"\n{tier_label}{c['symbol']}")
            print(f"    Original entry      : Rs{c['_add_orig_entry']:,.2f}  "
                  f"x {c['_add_orig_qty']} shares")
            print(f"    New box ceiling     : Rs{c.get('box_ceiling',0):,.2f}  "
                  f"(+{c['_add_gain_pct']}% above entry)")
            print(f"    New box floor       : Rs{c.get('box_floor',0):,.2f}")
            print(f"    New SL              : Rs{c.get('sl_price',0):,.2f}")
            print(f"    New target          : Rs{c.get('mm_target',0):,.2f}")
            print(f"    R:R                 : {c.get('rr_ratio',0):.2f}")
            print(f"    Status              : {c['status']}  "
                  f"| Dist to ceiling: {c.get('dist_to_ceil',0):.1f}%")
            print(f"    Vol                 : {c.get('vol_ratio',0):.2f}x avg")
            print(f"    >> Run: python scanner/place_order.py "
                  f"--symbol {c['symbol']} --qty <N> --live")
        print()

    # ── Final summary lines ────────────────────────────────────
    if add_candidates:
        print(f"  [ADD?]  Open pos add candidates : "
              f"{', '.join(c['symbol'] for c in add_candidates)}")
    if errors:
        print(f"  Skipped (fetch error)    : {', '.join(errors)}")

    # ── Update + save watchlist ────────────────────────────────
    wl = merge_into_watchlist(wl, results, cfg)
    save_watchlist(wl)

    # ── Save today's full scan to CSV ─────────────────────────
    if results:
        df_out = pd.DataFrame(results)
        # Drop internal keys before saving
        df_out = df_out.drop(columns=[c for c in ["_source","_note","_upgraded"] if c in df_out.columns])
        fname  = f"darvas_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        fpath  = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
        df_out.to_csv(fpath, index=False)
        print(f"  >> Scan results saved   : {fpath}")

    print(f"\n{'=' * 72}\n")
    return results


def _print_breakout_table(rows: list[dict]) -> None:
    """Helper: print a FRESH BREAKOUT table."""
    headers = ["Symbol", "Close", "Ceiling", "Floor", "Width%",
               "SL", "Target", "Risk%", "R:R", "Volx", "Days", "Note"]
    table = [[
        r["symbol"],
        fmt(r["close"]),
        fmt(r["box_ceiling"]),
        fmt(r["box_floor"]),
        fmt(r["box_width_pct"], prefix="", suffix="%", decimals=1),
        fmt(r["sl_price"]),
        fmt(r["mm_target"]),
        fmt(r["risk_pct"], prefix="", suffix="%", decimals=1),
        fmt(r["rr_ratio"], prefix="", decimals=2),
        fmt(r["vol_ratio"], prefix="", suffix="x", decimals=2),
        r["days_in_box"] or "-",
        r.get("_note", ""),
    ] for r in rows]
    print(tabulate(table, headers=headers, tablefmt="simple"))


# ══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Darvas Box Scanner -- NSE stocks from Chartink + watchlist",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Daily scan only:\n"
            "  python scanner/darvas_scanner.py --file scanner/symbols.txt\n\n"
            "  # Scan + preview basket orders (safe, no orders placed):\n"
            "  python scanner/darvas_scanner.py --file scanner/symbols.txt --auto-order\n\n"
            "  # Scan + PLACE LIVE orders for HOT stocks:\n"
            "  python scanner/darvas_scanner.py --file scanner/symbols.txt --auto-order --live\n\n"
            "  # LIVE orders with custom risk per trade (default Rs5000):\n"
            "  python scanner/darvas_scanner.py --file scanner/symbols.txt --auto-order --live --risk 10000\n"
        ),
    )
    parser.add_argument(
        "--symbols", type=str, default=DEFAULT_SYMBOLS,
        help="Comma-separated NSE symbols (paste from Chartink)"
    )
    parser.add_argument(
        "--file", type=str, default=None,
        help="Path to a .txt file containing comma-separated symbols"
    )
    parser.add_argument(
        "--show-watchlist", action="store_true",
        help="Print the current watchlist and exit"
    )
    parser.add_argument(
        "--auto-order", action="store_true",
        help="After scan, build basket orders for HOT tier stocks (dry-run by default)"
    )
    parser.add_argument(
        "--live", action="store_true",
        help="PLACE ACTUAL ORDERS via Breeze API (requires --auto-order). Default is dry-run."
    )
    parser.add_argument(
        "--risk", type=float, default=5000.0,
        help="Max INR risk per trade for position sizing (default: 5000)"
    )
    args = parser.parse_args()

    if args.show_watchlist:
        wl = load_watchlist()
        if len(wl) == 0:
            print("Watchlist is empty.")
        else:
            print(f"\nWatchlist ({WATCHLIST_PATH}):\n")
            print(tabulate(wl.to_dict("records"), headers="keys", tablefmt="simple"))
        return

    if args.file:
        with open(args.file, "r") as fh:
            raw = fh.read()
    else:
        raw = args.symbols

    symbols = parse_symbols(raw)
    if not symbols:
        print("No symbols provided. Exiting.")
        sys.exit(1)

    results = run_scan(symbols, CONFIG)

    # ── Auto-order: build basket for HOT tier stocks ───────────────
    if args.auto_order:
        hot_stocks = [r for r in results if r.get("alert_tier") == "HOT"]

        if not hot_stocks:
            print("\n  No HOT tier stocks found -- no basket orders to place.")
            print("  (HOT = within 2% of ceiling AND volume >= 2x average)\n")
        else:
            print(f"\n  {len(hot_stocks)} HOT stock(s) identified for basket orders.")
            if args.live:
                print("  MODE: LIVE -- placing actual orders via Breeze API")
            else:
                print("  MODE: DRY RUN -- add --live flag to place actual orders")

            from breeze_orders import place_basket, ORDER_CONFIG
            order_cfg = ORDER_CONFIG.copy()
            order_cfg["risk_per_trade"] = args.risk

            place_basket(
                hot_results=hot_stocks,
                order_cfg=order_cfg,
                dry_run=not args.live,
            )


if __name__ == "__main__":
    main()
