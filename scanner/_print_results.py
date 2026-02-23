import pandas as pd
import numpy as np
import glob, os

# Find latest scan CSV
files = sorted(glob.glob("scanner/darvas_scan_*.csv"))
if not files:
    print("No scan CSV found.")
    exit()
path = files[-1]
print(f"\nReading: {path}\n")

df = pd.read_csv(path)
priority = {"FRESH BREAKOUT": 0, "APPROACHING": 1, "WATCHING": 2, "BOX FORMING": 3}
df["_p"] = df["status"].map(priority).fillna(9)
df = df.sort_values(["_p", "dist_to_ceil"], na_position="last").reset_index(drop=True)

SEP  = "=" * 78
SEP2 = "-" * 78

def r(v, pre="Rs", suf="", dec=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    if pre == "Rs":
        return f"Rs{v:,.{dec}f}{suf}"
    return f"{pre}{v:.{dec}f}{suf}"

# ── FRESH BREAKOUT ──────────────────────────────────────────────────
bo = df[df["status"] == "FRESH BREAKOUT"]
if len(bo):
    print(SEP)
    print(f"  FRESH BREAKOUT  ({len(bo)} stocks)")
    print(SEP)
    for _, row in bo.iterrows():
        rr = row.get("rr_ratio")
        flag = "  [LOW RR]" if (rr and rr < 1.0) else "  [OK RR] "
        days = int(row["days_in_box"]) if not pd.isna(row.get("days_in_box", float("nan"))) else "-"
        print(f"  {row['symbol']:<14} {flag}"
              f"  Close={r(row['close'])}  Ceil={r(row['box_ceiling'])}"
              f"  SL={r(row['sl_price'])}  Tgt={r(row['mm_target'])}"
              f"  Risk={r(row['risk_pct'],'','%',1)}  RR={r(rr,'','',2)}"
              f"  Vol={r(row['vol_ratio'],'','x',2)}  Days={days}")
    print()

# ── APPROACHING ─────────────────────────────────────────────────────
ap = df[df["status"] == "APPROACHING"]
if len(ap):
    print(SEP)
    print(f"  APPROACHING  ({len(ap)} stocks)  -- sorted by distance to ceiling")
    print(SEP)
    print(f"  {'Symbol':<14}  {'Close':>10}  {'Ceiling':>10}  {'Dist%':>6}  {'Width%':>7}  {'Vol':>6}  {'Days':>5}  SL            Target")
    print(SEP2)
    for _, row in ap.iterrows():
        days = int(row["days_in_box"]) if not pd.isna(row.get("days_in_box", float("nan"))) else "-"
        print(f"  {row['symbol']:<14}  {r(row['close']):>10}  {r(row['box_ceiling']):>10}"
              f"  {r(row['dist_to_ceil'],'','%',1):>6}  {r(row['box_width_pct'],'','%',1):>7}"
              f"  {r(row['vol_ratio'],'','x',2):>6}  {str(days):>5}"
              f"  {r(row['sl_price']):>12}  {r(row['mm_target'])}")
    print()

# ── SUMMARY ─────────────────────────────────────────────────────────
print(SEP2)
print("  SUMMARY")
print(SEP2)
vc = df["status"].value_counts()
for status, count in vc.items():
    print(f"  {status:<22}: {count}")
print(f"\n  Total analysed: {len(df)}")
print(SEP)
