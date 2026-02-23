import pandas as pd
import numpy as np
import glob

files = sorted(glob.glob("scanner/darvas_scan_*.csv"))
df = pd.read_csv(files[-1])

# APPROACHING with tiers
ap = df[df["status"] == "APPROACHING"].copy()
tier_order = {"HOT": 0, "WARM": 1, "WATCH": 2, "": 3}
ap["_t"] = ap["alert_tier"].map(tier_order).fillna(3)
ap = ap.sort_values(["_t", "dist_to_ceil"])

print("\n=== APPROACHING (tiered) ===")
for _, r in ap.iterrows():
    tier = str(r.get("alert_tier", ""))
    flag = "**" if tier == "HOT" else ("*" if tier == "WARM" else " ")
    try:
        days = int(r["days_in_box"])
    except Exception:
        days = "-"
    print(f"{flag} [{tier:<9}] {r['symbol']:<14} dist={r['dist_to_ceil']:.1f}%  "
          f"vol={r['vol_ratio']:.2f}x  days={days}  "
          f"ceil={r['box_ceiling']:.2f}  w={r['box_width_pct']:.1f}%")

# FRESH BREAKOUTs
bo = df[df["status"] == "FRESH BREAKOUT"]
print("\n=== FRESH BREAKOUT ===")
for _, r in bo.iterrows():
    rr = r.get("rr_ratio")
    flag = "[LOW RR]" if (rr and rr < 1.0) else "[OK RR] "
    print(f"  {flag} {r['symbol']:<14} close={r['close']}  "
          f"ceil={r['box_ceiling']}  rr={rr}  vol={r['vol_ratio']}x  "
          f"days={r.get('days_in_box')}")

print("\n=== COUNTS ===")
print(df["status"].value_counts().to_string())
