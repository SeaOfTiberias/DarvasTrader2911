#!/usr/bin/env python3
"""
Place a single Darvas order with fixed quantity override.
Usage: python scanner/place_order.py --symbol POLYCAB --qty 7 --live
"""
import argparse
import glob
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime

# Add scanner dir to path so breeze_orders is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from breeze_orders import (
    connect_breeze, build_order, print_basket_preview,
    _save_order_log, ORDER_CONFIG, get_breeze_code
)


def place_single(symbol: str, qty: int, dry_run: bool = True) -> dict:
    """Place a single Darvas order for a specific symbol with fixed quantity."""

    # ── Load latest scan data ────────────────────────────────────
    files = sorted(glob.glob(
        os.path.join(os.path.dirname(__file__), "darvas_scan_*.csv")
    ))
    if not files:
        print("ERROR: No scan CSV found. Run the scanner first.")
        sys.exit(1)

    df = pd.read_csv(files[-1])
    matches = df[df["symbol"].str.upper() == symbol.upper()]
    if matches.empty:
        print(f"ERROR: {symbol} not found in latest scan ({os.path.basename(files[-1])}).")
        print(f"Available symbols: {', '.join(df.symbol.tolist())}")
        sys.exit(1)

    row = matches.iloc[0]
    result = row.to_dict()

    # ── Build order (then override qty) ─────────────────────────
    cfg = ORDER_CONFIG.copy()
    order = build_order(result, cfg)
    order["quantity"] = qty  # user override

    # Recalculate financials with fixed qty
    order["capital_inr"]  = round(order["entry_price"] * qty, 2)
    order["risk_inr"]     = round((order["entry_price"] - order["sl_price"]) * qty, 2)
    order["reward_inr"]   = round((order["target_price"] - order["entry_price"]) * qty, 2)
    order["rr"]           = round(order["reward_inr"] / order["risk_inr"], 2) \
                            if order["risk_inr"] > 0 else 0

    # ── Preview ─────────────────────────────────────────────────
    print_basket_preview([order], live=not dry_run)
    breeze_code = get_breeze_code(symbol)
    print(f"  Breeze stock_code : {breeze_code}  (NSE: {symbol})")
    print()

    if dry_run:
        _save_order_log([order], tag="SINGLE_DRYRUN")
        return order

    # ── Live placement ───────────────────────────────────────────
    # NOTE: Breeze CNC limit orders do NOT accept a combined stoploss parameter.
    # We place a clean buy limit order. Set the SL as a GTT/SL order separately
    # in the ICICI Direct app once the position is open.
    # ── Tick-size rounding (NSE requires price in multiples of tick) ─
    # Most NSE stocks: tick = 0.05. Some large-caps: tick = 0.50.
    # We round UP to 0.50 to be safe and ensure the order is valid.
    def round_tick(price: float, tick: float = 0.50) -> float:
        import math
        return round(math.ceil(price / tick) * tick, 2)

    entry_rounded = round_tick(order["entry_price"])
    if entry_rounded != order["entry_price"]:
        print(f"  Tick adjustment: Rs{order['entry_price']} -> Rs{entry_rounded}  (tick=0.50)")
        order["entry_price"] = entry_rounded

    print(f"  Placing LIVE buy limit order: {symbol} ({breeze_code}) x {qty}...")
    breeze = connect_breeze()

    try:
        resp = breeze.place_order(
            stock_code    = breeze_code,
            exchange_code = order["exchange"],
            product       = order["product"],
            action        = order["action"],
            order_type    = order["order_type"],
            quantity      = str(qty),
            price         = str(order["entry_price"]),
            validity      = order["validity"],
            user_remark   = f"Darvas{datetime.now().strftime('%Y%m%d')}",
        )

        order["api_response"] = str(resp)
        print(f"\n  Full API response: {resp}")

        if resp.get("Error"):
            order["status"] = "ERROR"
            order["error"]  = str(resp["Error"])
            print(f"\n  ORDER FAILED: {resp['Error']}")
        else:
            success  = (resp.get("Success") or {})
            order_id = success.get("order_id", "")
            order["order_id"] = order_id
            order["status"]   = "PLACED"
            print(f"\n  ORDER PLACED SUCCESSFULLY")
            print(f"     Symbol      : {symbol}  (Breeze: {breeze_code})")
            print(f"     Order ID    : {order_id}")
            print(f"     Buy Limit   : Rs{order['entry_price']:,.2f}  x {qty} shares")
            print(f"     Capital     : Rs{order['capital_inr']:,.0f}")
            print()
            print(f"  !! ACTION REQUIRED -- Set Stop Loss in your broker app:")
            print(f"     SL Price    : Rs{order['sl_price']:,.2f}")
            print(f"     Target      : Rs{order['target_price']:,.2f}")
            print(f"     (Place a GTT SL-M order in ICICI Direct after position fills)")

    except Exception as exc:
        order["status"] = "ERROR"
        order["error"]  = str(exc)
        print(f"\n  ERROR placing order: {exc}")

    _save_order_log([order], tag="SINGLE_LIVE")
    return order


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Place a single Darvas breakout order with fixed quantity"
    )
    parser.add_argument("--symbol", required=True, help="NSE symbol (e.g. POLYCAB)")
    parser.add_argument("--qty",    required=True, type=int, help="Number of shares")
    parser.add_argument("--live",   action="store_true",
                        help="Place actual order (default: dry run preview)")
    args = parser.parse_args()

    place_single(
        symbol  = args.symbol.upper(),
        qty     = args.qty,
        dry_run = not args.live,
    )
