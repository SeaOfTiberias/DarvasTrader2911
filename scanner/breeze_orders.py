#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Darvas Box Scanner -- Automated Order Placement via ICICI Breeze API
=====================================================================

WORKFLOW
--------
  1. Darvas scanner identifies HOT tier APPROACHING stocks.
  2. For each HOT stock, place a BUY LIMIT order at ceiling + buffer.
     - Order sits dormant -- does NOT execute until price reaches the level.
     - Auto-cancels end of day (3:15 PM IST) if never triggered.
  3. When triggered (stock breaks ceiling), position is opened automatically.
     - Separately place an SL-M sell order to protect the position.

ORDER TYPES (NSE Equity)
------------------------
  Main order : Limit buy  @ ceiling + buffer  -- "buy-stop" via limit
  SL order   : SL-M sell  @ box_floor - buffer -- placed after main fills
  Validity   : DAY (auto-expires at 3:15 PM NSE)

POSITION SIZING
---------------
  Risk-based: qty = max_risk_inr / (entry_price - sl_price)
  Ensures FIXED rupee risk regardless of stock price.

SAFETY DEFAULTS
---------------
  - dry_run=True by default -- NEVER places live orders unless --live passed
  - max_orders_daily cap to prevent runaway basket
  - Full audit trail saved to CSV

DAILY SETUP (required each morning)
------------------------------------
  1. Login to ICICI markets.com / Breeze portal
  2. Generate a fresh session token
  3. Update BREEZE_SESSION_TOKEN in .env

USAGE
-----
  # Preview only (safe, no orders placed):
  python scanner/darvas_scanner.py --file scanner/symbols.txt --auto-order

  # Place live orders (confirm in broker app):
  python scanner/darvas_scanner.py --file scanner/symbols.txt --auto-order --live

  # Adjust risk per trade:
  python scanner/darvas_scanner.py --file scanner/symbols.txt --auto-order --live --risk 10000
"""

import os
import sys
import logging
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ======================================================================
#  ORDER CONFIGURATION
# ======================================================================

ORDER_CONFIG = {
    # Entry
    "entry_buffer_pct":  0.3,    # buy at ceiling + X% (clears ceiling on breakout)

    # Risk / sizing
    "risk_per_trade":    5000,   # max INR to risk per trade (position sizing base)

    # Safety
    "max_orders_daily":  5,      # hard cap on number of orders per scan run

    # Broker
    "product":           "cash", # "cash" = CNC delivery equity
    "exchange":          "NSE",
    "validity":          "day",  # auto-cancel at session end
}


# ======================================================================
#  BREEZE CONNECTION
# ======================================================================

def connect_breeze():
    """
    Authenticate with ICICI Breeze API.
    Returns a connected BreezeConnect instance.

    Requires in .env:
        BREEZE_API_KEY
        BREEZE_API_SECRET
        BREEZE_SESSION_TOKEN   <-- refresh this EACH morning from the Breeze portal
    """
    try:
        from breeze_connect import BreezeConnect
    except ImportError:
        print("  ERROR: breeze_connect not installed.")
        print("         Run: pip install breeze-connect")
        sys.exit(1)

    api_key       = os.getenv("BREEZE_API_KEY")
    api_secret    = os.getenv("BREEZE_API_SECRET")
    session_token = os.getenv("BREEZE_SESSION_TOKEN")

    missing = [k for k, v in {
        "BREEZE_API_KEY":       api_key,
        "BREEZE_API_SECRET":    api_secret,
        "BREEZE_SESSION_TOKEN": session_token,
    }.items() if not v]

    if missing:
        raise EnvironmentError(
            f"Missing .env variables: {', '.join(missing)}\n"
            "Update your .env file with fresh Breeze credentials."
        )

    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret, session_token=session_token)
    print("  >> Breeze API: connected successfully")
    return breeze


# ======================================================================
#  POSITION SIZING
# ======================================================================

def qty_by_risk(entry: float, sl: float, max_risk_inr: float) -> int:
    """
    Risk-based position sizing.
    qty = max_risk_inr / (entry - sl)
    Guarantees a fixed rupee risk regardless of stock price.
    """
    risk_per_share = entry - sl
    if risk_per_share <= 0:
        return 1
    return max(1, int(max_risk_inr / risk_per_share))


# ======================================================================
#  ORDER BUILDING
# ======================================================================

def build_order(result: dict, cfg: dict) -> dict:
    """
    Build a complete order dict from a HOT scanner result.

    Entry logic:
      - Buy limit at ceiling + entry_buffer_pct
        (A limit order ABOVE current price acts as a buy-stop on NSE.
         It will execute automatically when the market price rises to that level.)
    """
    symbol    = result["symbol"]
    ceiling   = result["box_ceiling"]
    sl_price  = result["sl_price"]
    mm_target = result["mm_target"]

    # Entry: ceiling + buffer
    entry = round(ceiling * (1 + cfg["entry_buffer_pct"] / 100.0), 2)

    # Quantity by risk
    qty    = qty_by_risk(entry, sl_price, cfg["risk_per_trade"])

    # Financials
    capital     = round(entry * qty, 2)
    risk_inr    = round((entry - sl_price) * qty, 2)
    reward_inr  = round((mm_target - entry) * qty, 2)
    rr          = round(reward_inr / risk_inr, 2) if risk_inr > 0 else 0.0

    return {
        # Identity
        "symbol":        symbol,
        "alert_tier":    result.get("alert_tier", "HOT"),
        "days_in_box":   result.get("days_in_box"),
        "vol_ratio":     result.get("vol_ratio", 0),

        # Order params
        "action":        "buy",
        "order_type":    "limit",
        "product":       cfg["product"],
        "exchange":      cfg["exchange"],
        "validity":      cfg["validity"],

        # Prices & sizing
        "ceiling":       ceiling,
        "entry_price":   entry,
        "sl_price":      sl_price,
        "target_price":  mm_target,
        "quantity":      qty,

        # Financials (for preview / log)
        "capital_inr":   capital,
        "risk_inr":      risk_inr,
        "reward_inr":    reward_inr,
        "rr":            rr,

        # Outcome (filled after placement)
        "order_id":      "",
        "status":        "pending",
        "error":         "",
        "created_at":    datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ======================================================================
#  PREVIEW DISPLAY
# ======================================================================

def print_basket_preview(orders: list[dict], live: bool) -> None:
    """Print a formatted preview of the basket before placement."""
    SEP  = "=" * 72
    SEP2 = "-" * 72
    mode = "LIVE" if live else "DRY RUN (preview only)"

    print(f"\n{SEP}")
    print(f"  DARVAS BREAKOUT BASKET  --  {mode}")
    print(f"  {len(orders)} order(s)  |  Risk per trade: Rs{orders[0]['risk_inr']:,.0f}")
    print(SEP)

    total_capital = sum(o["capital_inr"] for o in orders)
    total_risk    = sum(o["risk_inr"]    for o in orders)
    total_reward  = sum(o["reward_inr"]  for o in orders)

    for o in orders:
        tier_flag = "**" if o["alert_tier"] == "HOT" else "*"
        print(f"\n  {tier_flag} [{o['alert_tier']}] {o['symbol']}")
        print(f"    Ceiling (box)   : Rs{o['ceiling']:>10,.2f}")
        print(f"    BUY LIMIT at    : Rs{o['entry_price']:>10,.2f}  x {o['quantity']} shares")
        print(f"    Stop Loss       : Rs{o['sl_price']:>10,.2f}  (risk Rs{o['risk_inr']:,.0f})")
        print(f"    Target          : Rs{o['target_price']:>10,.2f}  (reward Rs{o['reward_inr']:,.0f})")
        print(f"    R:R             : {o['rr']:.2f}  |  Capital: Rs{o['capital_inr']:,.0f}")
        print(f"    Box days        : {o.get('days_in_box') or '-'}  |  Vol: {o.get('vol_ratio', 0):.2f}x")
        print(f"    Validity        : {o['validity'].upper()} -- auto-cancels at 3:15 PM if not triggered")

    print(f"\n{SEP2}")
    print(f"  Total capital reserved : Rs{total_capital:>12,.0f}  (only deployed if breakout occurs)")
    print(f"  Total max risk         : Rs{total_risk:>12,.0f}")
    print(f"  Total potential reward : Rs{total_reward:>12,.0f}")
    print(f"  Portfolio R:R          : {total_reward / total_risk:.2f}")
    if not live:
        print(f"\n  >> To place these orders LIVE, add the --live flag.")
    print(f"{SEP}\n")


# ======================================================================
#  ORDER PLACEMENT
# ======================================================================

def place_basket(
    hot_results: list[dict],
    order_cfg:   dict  = None,
    dry_run:     bool  = True,
) -> list[dict]:
    """
    Build and optionally place breakout-capture orders for HOT tier stocks.

    Parameters
    ----------
    hot_results : list[dict]
        HOT tier stocks from the Darvas scanner (alert_tier == "HOT").
    order_cfg : dict, optional
        Override ORDER_CONFIG defaults.
    dry_run : bool
        True  = preview only; safe, no API calls.
        False = LIVE mode; places actual orders via Breeze API.

    Returns
    -------
    list[dict]
        Order details with status / order_id populated.
    """
    if order_cfg is None:
        order_cfg = ORDER_CONFIG.copy()

    if not hot_results:
        print("\n  No HOT tier stocks to place orders for.")
        return []

    # Safety cap
    max_n = order_cfg.get("max_orders_daily", 5)
    if len(hot_results) > max_n:
        print(f"\n  WARNING: {len(hot_results)} HOT stocks -- capped at {max_n} (closest to ceiling).")
        hot_results = sorted(hot_results, key=lambda r: r.get("dist_to_ceil", 99))[:max_n]

    # Build all orders
    orders = [build_order(r, order_cfg) for r in hot_results]

    # Always show preview
    print_basket_preview(orders, live=not dry_run)

    if dry_run:
        _save_order_log(orders, tag="DRYRUN")
        return orders

    # ── LIVE PLACEMENT ────────────────────────────────────────────────
    print(f"  Placing {len(orders)} LIVE order(s) via Breeze API...\n")
    breeze = connect_breeze()

    for o in orders:
        try:
            resp = breeze.place_order(
                stock_code    = o["symbol"],
                exchange_code = o["exchange"],
                product       = o["product"],
                action        = o["action"],
                order_type    = o["order_type"],
                quantity      = str(o["quantity"]),
                price         = str(o["entry_price"]),
                stoploss      = str(o["sl_price"]),
                validity      = o["validity"],
                user_remark   = f"DarvasHOT_{datetime.now().strftime('%Y%m%d')}",
            )
            success  = (resp.get("Success") or {})
            order_id = success.get("order_id", "")
            o["order_id"] = order_id
            o["status"]   = "PLACED"
            print(f"  PLACED  : {o['symbol']:<14}  order_id={order_id}"
                  f"  entry=Rs{o['entry_price']:.2f}  qty={o['quantity']}")

        except Exception as exc:
            o["status"] = "ERROR"
            o["error"]  = str(exc)
            print(f"  ERROR   : {o['symbol']:<14}  {exc}")

    _save_order_log(orders, tag="LIVE")
    placed = sum(1 for o in orders if o["status"] == "PLACED")
    errors = sum(1 for o in orders if o["status"] == "ERROR")
    print(f"\n  Done: {placed} placed  |  {errors} failed")
    return orders


# ======================================================================
#  AUDIT TRAIL
# ======================================================================

def _save_order_log(orders: list[dict], tag: str = "LOG") -> None:
    """Save order details to a CSV for full audit trail."""
    if not orders:
        return
    log_dir = os.path.dirname(os.path.abspath(__file__))
    fname   = os.path.join(
        log_dir,
        f"darvas_orders_{tag}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    )
    pd.DataFrame(orders).to_csv(fname, index=False)
    print(f"  >> Order log: {fname}")


# ======================================================================
#  STANDALONE TEST
# ======================================================================

if __name__ == "__main__":
    # Quick test with mock HOT data
    mock_hot = [
        {
            "symbol":      "POLYCAB",
            "alert_tier":  "HOT",
            "box_ceiling": 7948.00,
            "box_floor":   6620.00,
            "sl_price":    6586.90,
            "mm_target":   9276.00,
            "dist_to_ceil": 0.3,
            "vol_ratio":   2.4,
            "days_in_box": 129,
        },
        {
            "symbol":      "BAJFINANCE",
            "alert_tier":  "HOT",
            "box_ceiling": 1061.00,
            "box_floor":   976.39,
            "sl_price":    971.29,
            "mm_target":   1145.61,
            "dist_to_ceil": 2.3,
            "vol_ratio":   2.1,
            "days_in_box": 52,
        },
    ]
    print("Running DRY RUN with mock HOT data...\n")
    place_basket(mock_hot, dry_run=True)
