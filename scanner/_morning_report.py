"""
_morning_report.py  –  DarvasTrader Daily Morning Briefing
============================================================
Generates a rich HTML report and opens it in your default browser.

Covers:
  (C) Signal movement alerts  – tier upgrades, status upgrades,
      significant dist_to_ceil improvement vs prior scan
  (B) Full visual HTML briefing  – KPI cards, tables, Chart.js charts,
      order tracker.

Usage:
    python scanner/_morning_report.py
    python scanner/_morning_report.py --no-open   # generate only, don't open
"""

import glob
import os
import sys
import json
import webbrowser
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
SCANNER_DIR     = Path(__file__).parent          # scanner/
REPORT_DIR      = SCANNER_DIR / "reports"
REPORT_DIR.mkdir(exist_ok=True)

DIST_IMPROVEMENT_THRESHOLD = 1.5   # % dist_to_ceil improvement triggers alert
VOL_SURGE_THRESHOLD        = 2.0   # vol_ratio to flag as surge
RR_GOOD                    = 1.5   # RR above this = green
RR_WARN                    = 1.0   # RR above this = yellow

TIER_RANK = {"HOT": 0, "WARM": 1, "WATCH": 2, "VOL-SURGE": 1, "": 3}
STATUS_RANK = {"FRESH BREAKOUT": 0, "APPROACHING": 1, "BOX FORMING": 2, "WATCHING": 3}

# ── Helper ───────────────────────────────────────────────────────────────────
def fmt_inr(v):
    try:
        v = float(v)
        if np.isnan(v): return "–"
        return f"₹{v:,.2f}"
    except: return "–"

def fmt_pct(v, dec=1):
    try:
        v = float(v)
        if np.isnan(v): return "–"
        return f"{v:.{dec}f}%"
    except: return "–"

def fmt_x(v, dec=2):
    try:
        v = float(v)
        if np.isnan(v): return "–"
        return f"{v:.{dec}f}x"
    except: return "–"

def fmt_num(v, dec=2):
    try:
        v = float(v)
        if np.isnan(v): return "–"
        return f"{v:.{dec}f}"
    except: return "–"

def safe_float(v):
    try:
        f = float(v)
        return f if not np.isnan(f) else None
    except:
        return None

# ── Data Loading ─────────────────────────────────────────────────────────────
def load_scan_files():
    """Return (latest_df, prev_df, latest_path, prev_path)."""
    files = sorted(glob.glob(str(SCANNER_DIR / "darvas_scan_*.csv")))
    if not files:
        print("ERROR: No darvas_scan_*.csv found in scanner/")
        sys.exit(1)
    latest_path = files[-1]
    prev_path   = files[-2] if len(files) >= 2 else None

    latest_df = pd.read_csv(latest_path)
    prev_df   = pd.read_csv(prev_path) if prev_path else None
    return latest_df, prev_df, latest_path, prev_path


def load_today_orders():
    """Load all order CSVs from today."""
    today_str = datetime.now().strftime("%Y%m%d")
    pattern   = str(SCANNER_DIR / f"darvas_orders_*{today_str}*.csv")
    files     = sorted(glob.glob(pattern))
    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f)
            if not df.empty:
                df["_source_file"] = Path(f).name
                dfs.append(df)
        except: pass
    if dfs:
        combined = pd.concat(dfs, ignore_index=True)
        # Deduplicate by order_id if present
        if "order_id" in combined.columns:
            combined = combined.drop_duplicates(subset=["order_id"])
        return combined
    return pd.DataFrame()


# ── (C) Signal Movement Detection ────────────────────────────────────────────
def compute_deltas(latest_df, prev_df):
    """Compare latest vs previous scan. Returns list of alert dicts."""
    if prev_df is None:
        return []

    alerts = []
    prev_map = prev_df.set_index("symbol").to_dict("index")

    for _, row in latest_df.iterrows():
        sym = row["symbol"]
        if sym not in prev_map:
            # Brand new stock entering scan
            if row.get("status") in ("APPROACHING", "FRESH BREAKOUT"):
                alerts.append({
                    "symbol": sym,
                    "type":   "NEW_ENTRY",
                    "emoji":  "🆕",
                    "badge":  "NEW",
                    "badge_class": "badge-new",
                    "msg":    f"New entry directly into <strong>{row['status']}</strong>",
                    "detail": f"Dist={fmt_pct(row.get('dist_to_ceil'))}  Vol={fmt_x(row.get('vol_ratio'))}  RR={fmt_num(row.get('rr_ratio'))}",
                })
            continue

        prev = prev_map[sym]
        curr_status = str(row.get("status", ""))
        prev_status = str(prev.get("status", ""))
        curr_tier   = str(row.get("alert_tier", ""))
        prev_tier   = str(prev.get("alert_tier", ""))

        # Status upgrade
        curr_sr = STATUS_RANK.get(curr_status, 9)
        prev_sr = STATUS_RANK.get(prev_status, 9)
        if curr_sr < prev_sr:
            alerts.append({
                "symbol": sym,
                "type":   "STATUS_UP",
                "emoji":  "⚡",
                "badge":  "STATUS↑",
                "badge_class": "badge-status",
                "msg":    f"<strong>{prev_status}</strong> → <strong>{curr_status}</strong>",
                "detail": f"Dist={fmt_pct(row.get('dist_to_ceil'))}  Vol={fmt_x(row.get('vol_ratio'))}  RR={fmt_num(row.get('rr_ratio'))}",
            })
            continue  # Don't double-alert; status is the biggest move

        # Tier upgrade (within APPROACHING)
        if curr_status == "APPROACHING" and prev_status == "APPROACHING":
            curr_tr = TIER_RANK.get(curr_tier, 9)
            prev_tr = TIER_RANK.get(prev_tier, 9)
            if curr_tr < prev_tr:
                alerts.append({
                    "symbol": sym,
                    "type":   "TIER_UP",
                    "emoji":  "🔥",
                    "badge":  "TIER↑",
                    "badge_class": "badge-tier",
                    "msg":    f"Tier <strong>{prev_tier or 'WATCH'}</strong> → <strong>{curr_tier}</strong>",
                    "detail": f"Dist={fmt_pct(row.get('dist_to_ceil'))}  Vol={fmt_x(row.get('vol_ratio'))}  RR={fmt_num(row.get('rr_ratio'))}",
                })

        # Significant dist improvement (moved closer to ceiling)
        if curr_status == "APPROACHING" and prev_status == "APPROACHING":
            curr_dist = safe_float(row.get("dist_to_ceil"))
            prev_dist = safe_float(prev.get("dist_to_ceil"))
            if curr_dist is not None and prev_dist is not None:
                improvement = prev_dist - curr_dist
                if improvement >= DIST_IMPROVEMENT_THRESHOLD:
                    alerts.append({
                        "symbol": sym,
                        "type":   "CLOSER",
                        "emoji":  "📐",
                        "badge":  f"−{improvement:.1f}%",
                        "badge_class": "badge-closer",
                        "msg":    f"Moved <strong>{improvement:.1f}% closer</strong> to ceiling",
                        "detail": f"Was {fmt_pct(prev_dist)} → Now {fmt_pct(curr_dist)}  Vol={fmt_x(row.get('vol_ratio'))}",
                    })

        # Volume surge
        curr_vol = safe_float(row.get("vol_ratio"))
        prev_vol = safe_float(prev.get("vol_ratio"))
        if (curr_vol is not None and curr_vol >= VOL_SURGE_THRESHOLD
                and (prev_vol is None or curr_vol > prev_vol * 1.5)):
            if curr_status == "APPROACHING":
                alerts.append({
                    "symbol": sym,
                    "type":   "VOL_SURGE",
                    "emoji":  "📢",
                    "badge":  f"VOL {curr_vol:.1f}x",
                    "badge_class": "badge-vol",
                    "msg":    f"Volume surge: <strong>{fmt_x(curr_vol)}</strong>",
                    "detail": f"Prev vol={fmt_x(prev_vol)}  Dist={fmt_pct(row.get('dist_to_ceil'))}  Tier={curr_tier}",
                })

    # Sort by priority: STATUS_UP > TIER_UP > CLOSER > VOL_SURGE > NEW_ENTRY
    type_order = {"STATUS_UP": 0, "TIER_UP": 1, "CLOSER": 2, "VOL_SURGE": 3, "NEW_ENTRY": 4}
    alerts.sort(key=lambda a: type_order.get(a["type"], 9))
    return alerts


# ── HTML Builder ─────────────────────────────────────────────────────────────
def tier_badge(t):
    t = str(t) if t else ""
    cls = {"HOT": "tier-hot", "WARM": "tier-warm", "WATCH": "tier-watch",
           "VOL-SURGE": "tier-vol"}.get(t.upper(), "tier-none")
    return f'<span class="tier-badge {cls}">{t or "–"}</span>' if t else "<span class='tier-badge tier-none'>–</span>"

def rr_cell(rr_val):
    v = safe_float(rr_val)
    if v is None: return "<td>–</td>"
    cls = "rr-good" if v >= RR_GOOD else ("rr-warn" if v >= RR_WARN else "rr-bad")
    return f'<td class="{cls}">{v:.2f}</td>'

def dist_bar(dist_val, max_dist=20):
    v = safe_float(dist_val)
    if v is None: return "<td>–</td>"
    pct = min(abs(v) / max_dist * 100, 100) if max_dist else 0
    color = "#22C55E" if v <= 2 else ("#F59E0B" if v <= 5 else "#64748B")
    return (f'<td class="dist-cell">'
            f'<div class="dist-bar-wrap"><div class="dist-bar" style="width:{pct:.0f}%;background:{color}"></div></div>'
            f'<span>{v:.1f}%</span></td>')

def vol_cell(vol_val):
    v = safe_float(vol_val)
    if v is None: return "<td>–</td>"
    cls = "vol-surge" if v >= 2.0 else ("vol-ok" if v >= 1.0 else "vol-low")
    return f'<td class="{cls}">{v:.2f}x</td>'

def status_dot(status):
    dots = {
        "FRESH BREAKOUT": "🔴",
        "APPROACHING": "🟡",
        "BOX FORMING": "🔵",
        "WATCHING": "⚫",
    }
    return dots.get(status, "⚫")


# ── Report Sections ───────────────────────────────────────────────────────────
def build_kpi_cards(df, orders_df):
    breakouts  = len(df[df["status"] == "FRESH BREAKOUT"])
    hot        = len(df[(df["status"] == "APPROACHING") & (df["alert_tier"] == "HOT")])
    warm       = len(df[(df["status"] == "APPROACHING") & (df["alert_tier"] == "WARM")])
    approaching= len(df[df["status"] == "APPROACHING"])
    watching   = len(df[df["status"] == "WATCHING"])
    total      = len(df)

    cap_deploy = orders_df["capital_inr"].sum() if not orders_df.empty and "capital_inr" in orders_df else 0
    risk_total = orders_df["risk_inr"].sum()    if not orders_df.empty and "risk_inr"    in orders_df else 0
    orders_n   = len(orders_df)

    bo_class   = "kpi-card kpi-breakout" if breakouts > 0 else "kpi-card kpi-neutral"
    hot_class  = "kpi-card kpi-hot"      if hot > 0       else "kpi-card kpi-neutral"

    return f"""
    <div class="kpi-row">
      <div class="{bo_class}">
        <div class="kpi-value">{breakouts}</div>
        <div class="kpi-label">🔴 Fresh Breakouts</div>
      </div>
      <div class="{hot_class}">
        <div class="kpi-value">{hot}</div>
        <div class="kpi-label">🔥 HOT Approaching</div>
      </div>
      <div class="kpi-card kpi-warm">
        <div class="kpi-value">{warm}</div>
        <div class="kpi-label">⚡ WARM Approaching</div>
      </div>
      <div class="kpi-card kpi-blue">
        <div class="kpi-value">{approaching}</div>
        <div class="kpi-label">📐 Total Approaching</div>
      </div>
      <div class="kpi-card kpi-neutral">
        <div class="kpi-value">{watching}</div>
        <div class="kpi-label">👁 Watching</div>
      </div>
      <div class="kpi-card kpi-neutral">
        <div class="kpi-value">{total}</div>
        <div class="kpi-label">📋 Universe Size</div>
      </div>
      <div class="kpi-card kpi-orders">
        <div class="kpi-value">{orders_n}</div>
        <div class="kpi-label">✅ Orders Today</div>
      </div>
      <div class="kpi-card kpi-cap">
        <div class="kpi-value">₹{cap_deploy:,.0f}</div>
        <div class="kpi-label">💰 Capital Deployed</div>
      </div>
      <div class="kpi-card kpi-risk">
        <div class="kpi-value">₹{risk_total:,.0f}</div>
        <div class="kpi-label">📉 Risk at Stake</div>
      </div>
    </div>"""


def build_alerts_section(alerts):
    if not alerts:
        return """<div class="section">
          <div class="section-header">📡 Signal Movement Alerts</div>
          <div class="no-alerts">✅ No significant signal movements since previous scan.</div>
        </div>"""

    rows = ""
    for a in alerts:
        rows += f"""
        <div class="alert-row">
          <div class="alert-symbol">{a['emoji']} {a['symbol']}</div>
          <span class="alert-badge {a['badge_class']}">{a['badge']}</span>
          <div class="alert-msg">{a['msg']}</div>
          <div class="alert-detail">{a['detail']}</div>
        </div>"""

    return f"""<div class="section">
      <div class="section-header">📡 Signal Movement Alerts <span class="count-badge">{len(alerts)}</span></div>
      <div class="alerts-grid">{rows}</div>
    </div>"""


def build_breakouts_table(df):
    bo = df[df["status"] == "FRESH BREAKOUT"].copy()
    if bo.empty:
        return """<div class="section">
          <div class="section-header">🔴 Fresh Breakouts</div>
          <div class="empty-msg">No fresh breakouts in this scan.</div>
        </div>"""

    rows = ""
    for _, r in bo.iterrows():
        rr   = safe_float(r.get("rr_ratio"))
        flag = "🔴 LOW RR" if (rr is not None and rr < 1.0) else "✅ OK RR"
        flag_cls = "flag-bad" if (rr is not None and rr < 1.0) else "flag-good"
        rows += f"""<tr>
          <td class="sym-cell">{r['symbol']}</td>
          <td><span class="{flag_cls}">{flag}</span></td>
          <td>{fmt_inr(r.get('close'))}</td>
          <td>{fmt_inr(r.get('box_ceiling'))}</td>
          <td>{fmt_inr(r.get('sl_price'))}</td>
          <td>{fmt_inr(r.get('mm_target'))}</td>
          {rr_cell(r.get('rr_ratio'))}
          {vol_cell(r.get('vol_ratio'))}
          <td>{int(r['days_in_box']) if safe_float(r.get('days_in_box')) and r['days_in_box'] >= 0 else '–'}</td>
          <td>{fmt_pct(r.get('box_width_pct'))}</td>
        </tr>"""

    return f"""<div class="section">
      <div class="section-header">🔴 Fresh Breakouts <span class="count-badge">{len(bo)}</span></div>
      <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Symbol</th><th>Signal</th><th>Close</th><th>Ceiling</th>
          <th>Stop Loss</th><th>Target</th><th>R:R</th><th>Volume</th>
          <th>Days in Box</th><th>Box Width</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
    </div>"""


def build_approaching_table(df):
    ap = df[df["status"] == "APPROACHING"].copy()
    if ap.empty:
        return """<div class="section">
          <div class="section-header">⚡ Approaching — Sorted by Distance to Ceiling</div>
          <div class="empty-msg">No approaching setups found.</div>
        </div>"""

    tier_order = {"HOT": 0, "WARM": 1, "VOL-SURGE": 1, "WATCH": 2, "": 3}
    ap["_tr"] = ap["alert_tier"].map(tier_order).fillna(3)
    ap = ap.sort_values(["_tr", "dist_to_ceil"])

    rows = ""
    for _, r in ap.iterrows():
        days = int(r["days_in_box"]) if safe_float(r.get("days_in_box")) and r["days_in_box"] >= 0 else "–"
        rows += f"""<tr>
          <td class="sym-cell">{r['symbol']}</td>
          <td>{tier_badge(r.get('alert_tier'))}</td>
          <td>{fmt_inr(r.get('close'))}</td>
          <td>{fmt_inr(r.get('box_ceiling'))}</td>
          {dist_bar(r.get('dist_to_ceil'))}
          {vol_cell(r.get('vol_ratio'))}
          <td>{days}</td>
          {rr_cell(r.get('rr_ratio'))}
          <td>{fmt_inr(r.get('sl_price'))}</td>
          <td>{fmt_inr(r.get('mm_target'))}</td>
          <td>{fmt_pct(r.get('box_width_pct'))}</td>
        </tr>"""

    return f"""<div class="section">
      <div class="section-header">⚡ Approaching Pipeline <span class="count-badge">{len(ap)}</span></div>
      <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Symbol</th><th>Tier</th><th>Close</th><th>Ceiling</th>
          <th>Dist to Ceil</th><th>Volume</th><th>Days</th>
          <th>R:R</th><th>Stop Loss</th><th>Target</th><th>Width</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
    </div>"""


def build_watching_table(df):
    wa = df[df["status"] == "WATCHING"].copy()
    wa = wa.sort_values("dist_to_ceil", ascending=True)
    # Show top 20 closest to ceiling (most likely to upgrade soon)
    wa_show = wa[wa["dist_to_ceil"] >= 0].head(20)

    if wa_show.empty:
        return ""

    rows = ""
    for _, r in wa_show.iterrows():
        days = int(r["days_in_box"]) if safe_float(r.get("days_in_box")) and r["days_in_box"] >= 0 else "–"
        rows += f"""<tr>
          <td class="sym-cell">{r['symbol']}</td>
          <td>{fmt_inr(r.get('close'))}</td>
          <td>{fmt_inr(r.get('box_ceiling'))}</td>
          {dist_bar(r.get('dist_to_ceil'), max_dist=40)}
          {vol_cell(r.get('vol_ratio'))}
          <td>{days}</td>
          {rr_cell(r.get('rr_ratio'))}
          <td>{fmt_pct(r.get('box_width_pct'))}</td>
        </tr>"""

    return f"""<div class="section section-collapsed">
      <div class="section-header collapsible" onclick="toggleSection(this)">
        👁 Watching — Next in Line (Top 20 by Proximity)
        <span class="count-badge">{len(wa)} total</span>
        <span class="collapse-icon">▼</span>
      </div>
      <div class="collapsible-body">
      <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Symbol</th><th>Close</th><th>Ceiling</th>
          <th>Dist to Ceil</th><th>Volume</th><th>Days</th>
          <th>R:R</th><th>Width</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table></div></div>
    </div>"""


def build_orders_section(orders_df):
    if orders_df.empty:
        return """<div class="section">
          <div class="section-header">✅ Today's Orders</div>
          <div class="empty-msg">No orders placed today. Run breeze_orders.py to place orders.</div>
        </div>"""

    cap_total  = orders_df["capital_inr"].sum()  if "capital_inr"  in orders_df else 0
    risk_total = orders_df["risk_inr"].sum()     if "risk_inr"     in orders_df else 0
    rew_total  = orders_df["reward_inr"].sum()   if "reward_inr"   in orders_df else 0
    avg_rr     = orders_df["rr"].mean()          if "rr"           in orders_df else None

    summary = f"""<div class="order-summary">
      <div class="os-card"><span class="os-val">₹{cap_total:,.0f}</span><span class="os-lbl">Capital</span></div>
      <div class="os-card os-risk"><span class="os-val">₹{risk_total:,.0f}</span><span class="os-lbl">Risk</span></div>
      <div class="os-card os-rew"><span class="os-val">₹{rew_total:,.0f}</span><span class="os-lbl">Reward</span></div>
      <div class="os-card os-rr"><span class="os-val">{avg_rr:.2f}</span><span class="os-lbl">Avg R:R</span></div>
    </div>""" if avg_rr is not None else ""

    rows = ""
    for _, r in orders_df.iterrows():
        status     = str(r.get("status", ""))
        status_cls = ("ord-placed" if "PLACED" in status.upper()
                      else "ord-pending" if "PENDING" in status.upper()
                      else "ord-failed" if "FAIL" in status.upper()
                      else "")
        time_str   = str(r.get("created_at", ""))[:16]
        rows += f"""<tr>
          <td class="sym-cell">{r.get('symbol','')}</td>
          <td>{tier_badge(r.get('alert_tier'))}</td>
          <td>{time_str}</td>
          <td>{fmt_inr(r.get('entry_price'))}</td>
          <td>{fmt_inr(r.get('sl_price'))}</td>
          <td>{fmt_inr(r.get('target_price'))}</td>
          <td>{r.get('quantity','–')}</td>
          <td>{fmt_inr(r.get('capital_inr'))}</td>
          <td>{fmt_inr(r.get('risk_inr'))}</td>
          {rr_cell(r.get('rr'))}
          <td><span class="status-badge {status_cls}">{status}</span></td>
          <td class="order-id">{str(r.get('order_id',''))}</td>
        </tr>"""

    return f"""<div class="section">
      <div class="section-header">✅ Today's Orders <span class="count-badge">{len(orders_df)}</span></div>
      {summary}
      <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Symbol</th><th>Tier</th><th>Time</th><th>Entry</th>
          <th>Stop Loss</th><th>Target</th><th>Qty</th>
          <th>Capital</th><th>Risk</th><th>R:R</th>
          <th>Status</th><th>Order ID</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
    </div>"""


def build_charts_data(df):
    """Return JSON-serializable data for Chart.js charts."""
    vc = df["status"].value_counts().to_dict()
    status_labels = list(vc.keys())
    status_values = list(vc.values())
    status_colors = []
    for s in status_labels:
        status_colors.append({
            "FRESH BREAKOUT": "#EF4444",
            "APPROACHING":    "#F59E0B",
            "BOX FORMING":    "#3B82F6",
            "WATCHING":       "#475569",
        }.get(s, "#64748B"))

    # Scatter: approaching stocks – dist vs rr, sized by vol
    ap = df[df["status"] == "APPROACHING"].copy()
    scatter_data = []
    for _, r in ap.iterrows():
        dist = safe_float(r.get("dist_to_ceil"))
        rr   = safe_float(r.get("rr_ratio"))
        vol  = safe_float(r.get("vol_ratio"))
        if dist is not None and rr is not None:
            tier = str(r.get("alert_tier", ""))
            scatter_data.append({
                "x":      round(dist, 2),
                "y":      round(rr, 2),
                "r":      max(4, min(20, int((vol or 1) * 5))),
                "label":  r["symbol"],
                "tier":   tier,
                "color":  {"HOT": "#F59E0B", "WARM": "#22C55E"}.get(tier, "#64748B"),
            })

    # Days in box histogram buckets
    ap2 = df[df["status"].isin(["APPROACHING", "FRESH BREAKOUT"])].copy()
    ap2["days_in_box"] = pd.to_numeric(ap2["days_in_box"], errors="coerce").fillna(0)
    bins   = [0, 10, 20, 30, 45, 60, 90, 120, 200]
    labels = ["0-10", "10-20", "20-30", "30-45", "45-60", "60-90", "90-120", "120+"]
    hist_vals = []
    for i in range(len(bins) - 1):
        count = int(((ap2["days_in_box"] >= bins[i]) & (ap2["days_in_box"] < bins[i+1])).sum())
        hist_vals.append(count)

    return {
        "status_labels": status_labels,
        "status_values": status_values,
        "status_colors": status_colors,
        "scatter_data":  scatter_data,
        "hist_labels":   labels,
        "hist_values":   hist_vals,
    }


# ── DAR-CARDS ────────────────────────────────────────────────────────────────
def _gauge_html(close, floor, ceiling, status):
    """Renders a horizontal gauge showing where price sits in the Darvas box."""
    f  = safe_float(floor)
    c  = safe_float(ceiling)
    cl = safe_float(close)
    if None in (f, c, cl) or c == f:
        return ""

    # Position as % across [floor → ceiling]
    raw_pct = (cl - f) / (c - f) * 100
    marker_pct = max(0, min(105, raw_pct))   # allow slight overshoot for breakout

    if status == "FRESH BREAKOUT":
        fill_color  = "linear-gradient(90deg, #22C55E, #EF4444)"
        fill_width  = 100
        pct_label   = f"🔴 Broke out {abs(raw_pct - 100):.1f}% above ceiling"
    elif raw_pct >= 95:
        fill_color  = "#F59E0B"
        fill_width  = min(raw_pct, 100)
        pct_label   = f"⚡ {100-raw_pct:.1f}% to ceiling"
    elif raw_pct >= 80:
        fill_color  = "#FBBF24"
        fill_width  = raw_pct
        pct_label   = f"🟡 {100-raw_pct:.1f}% to ceiling"
    else:
        fill_color  = "#3B82F6"
        fill_width  = raw_pct
        pct_label   = f"  {100-raw_pct:.1f}% distance remaining"

    return f"""<div class="darcard-gauge-wrap">
      <div class="darcard-gauge-label">
        <span title="Box Floor">Floor {fmt_inr(floor)}</span>
        <span title="Current Close">Close {fmt_inr(close)}</span>
        <span title="Box Ceiling">Ceil {fmt_inr(ceiling)}</span>
      </div>
      <div class="darcard-gauge-track">
        <div class="darcard-gauge-fill"
             style="width:{fill_width:.1f}%;background:{fill_color}"></div>
        <div class="darcard-gauge-marker"
             style="left:{marker_pct:.1f}%"></div>
      </div>
      <div class="darcard-gauge-pct">{pct_label}</div>
    </div>"""


def _rr_display(rr_val):
    v = safe_float(rr_val)
    if v is None: return ("–", "")
    cls = "rr-good" if v >= RR_GOOD else ("rr-warn" if v >= RR_WARN else "rr-bad")
    icon = " ✅" if v >= RR_GOOD else (" ⚠️" if v >= RR_WARN else " ❌")
    return (f"{v:.2f}{icon}", cls)


def build_darcards_section(df, notes_map=None):
    """
    Render one DAR-CARD per actionable stock:
      - All FRESH BREAKOUTs
      - All APPROACHING stocks (HOT first, then WARM, then WATCH)
    notes_map: dict {symbol: notes_str} from watchlist.csv
    """
    notes_map = notes_map or {}

    # Select and order candidates
    bo  = df[df["status"] == "FRESH BREAKOUT"].copy()
    ap  = df[df["status"] == "APPROACHING"].copy()
    tier_order = {"HOT": 0, "WARM": 1, "VOL-SURGE": 1, "WATCH": 2, "": 3}
    ap["_tr"] = ap["alert_tier"].map(tier_order).fillna(3)
    ap = ap.sort_values(["_tr", "dist_to_ceil"])

    candidates = pd.concat([bo, ap], ignore_index=True)
    if candidates.empty:
        return ""

    cards_html = ""
    for _, r in candidates.iterrows():
        sym    = r["symbol"]
        status = str(r.get("status", ""))
        tier   = str(r.get("alert_tier", ""))

        # Card accent class
        if status == "FRESH BREAKOUT":
            card_cls   = "darcard darcard-bo"
            status_cls = "darcard-status dcs-bo"
            status_lbl = "🔴 FRESH BREAKOUT"
        elif tier == "HOT":
            card_cls   = "darcard darcard-hot"
            status_cls = "darcard-status dcs-ap"
            status_lbl = "🔥 HOT"
        elif tier == "WARM":
            card_cls   = "darcard darcard-warm"
            status_cls = "darcard-status dcs-ap"
            status_lbl = "⚡ WARM"
        else:
            card_cls   = "darcard darcard-watch"
            status_cls = "darcard-status dcs-ap"
            status_lbl = "👁 APPROACHING"

        # Stats values
        days_raw = safe_float(r.get("days_in_box"))
        days     = str(int(days_raw)) if days_raw is not None and days_raw >= 0 else "–"
        width    = fmt_pct(r.get("box_width_pct"))
        dist     = fmt_pct(r.get("dist_to_ceil"))
        vol_v    = safe_float(r.get("vol_ratio"))
        vol_str  = fmt_x(vol_v)
        vol_cls  = ("darcard-metric-value vol-surge" if vol_v and vol_v >= 2.0
                    else "darcard-metric-value vol-ok" if vol_v and vol_v >= 1.0
                    else "darcard-metric-value vol-low")

        rr_str, rr_cls = _rr_display(r.get("rr_ratio"))

        # Confidence indicators (ceil_conf, floor_conf if present)
        ceil_c  = safe_float(r.get("ceil_conf"))
        floor_c = safe_float(r.get("floor_conf"))
        conf_html = ""
        if ceil_c is not None and floor_c is not None:
            dots_ceil  = "●" * min(int(ceil_c),  5) + "○" * max(0, 5 - min(int(ceil_c),  5))
            dots_floor = "●" * min(int(floor_c), 5) + "○" * max(0, 5 - min(int(floor_c), 5))
            conf_html  = (f'<div class="darcard-stat">'
                          f'<div class="darcard-stat-label">Ceil Conf</div>'
                          f'<div class="darcard-stat-value" style="letter-spacing:2px;color:var(--hot)">{dots_ceil}</div></div>'
                          f'<div class="darcard-stat">'
                          f'<div class="darcard-stat-label">Floor Conf</div>'
                          f'<div class="darcard-stat-value" style="letter-spacing:2px;color:var(--accent)">{dots_floor}</div></div>')

        # Notes from watchlist (or placeholder)
        note_text = notes_map.get(sym, "")
        if note_text and str(note_text).strip() and str(note_text).strip() != "nan":
            note_html = f'<strong>📝</strong> {note_text}'
        else:
            note_html = '<span style="opacity:0.4">📝 No notes — add to watchlist.csv</span>'

        # Gauge
        gauge = _gauge_html(r.get("close"), r.get("box_floor"), r.get("box_ceiling"), status)

        cards_html += f"""
        <div class="{card_cls}">

          <!-- Header -->
          <div class="darcard-header">
            <div class="darcard-sym">{sym}
              <small>NSE · Days in Box: {days}</small>
            </div>
            <div class="darcard-badges">
              <span class="{status_cls}">{status_lbl}</span>
              {tier_badge(tier) if status != 'FRESH BREAKOUT' else ''}
            </div>
          </div>

          <!-- Box Gauge -->
          {gauge}

          <!-- Stats grid -->
          <div class="darcard-stats">
            <div class="darcard-stat">
              <div class="darcard-stat-label">Box Ceiling</div>
              <div class="darcard-stat-value">{fmt_inr(r.get('box_ceiling'))}</div>
            </div>
            <div class="darcard-stat">
              <div class="darcard-stat-label">Box Floor</div>
              <div class="darcard-stat-value">{fmt_inr(r.get('box_floor'))}</div>
            </div>
            <div class="darcard-stat">
              <div class="darcard-stat-label">Box Width</div>
              <div class="darcard-stat-value">{width}</div>
            </div>
            <div class="darcard-stat">
              <div class="darcard-stat-label">Dist to Ceil</div>
              <div class="darcard-stat-value">{dist}</div>
            </div>
            {conf_html}
          </div>

          <!-- Trade parameters -->
          <div class="darcard-trade">
            <div class="darcard-trade-item">
              <div class="darcard-trade-label">Entry (Ceiling)</div>
              <div class="darcard-trade-val dtv-entry">{fmt_inr(r.get('box_ceiling'))}</div>
            </div>
            <div class="darcard-trade-item">
              <div class="darcard-trade-label">Stop Loss</div>
              <div class="darcard-trade-val dtv-sl">{fmt_inr(r.get('sl_price'))}</div>
            </div>
            <div class="darcard-trade-item">
              <div class="darcard-trade-label">Target</div>
              <div class="darcard-trade-val dtv-target">{fmt_inr(r.get('mm_target'))}</div>
            </div>
          </div>

          <!-- Metrics row -->
          <div class="darcard-metrics">
            <div class="darcard-metric">
              <span class="darcard-metric-label">R:R</span>
              <span class="darcard-metric-value {rr_cls}">{rr_str}</span>
            </div>
            <div class="darcard-metric">
              <span class="darcard-metric-label">Volume</span>
              <span class="{vol_cls}">{vol_str}</span>
            </div>
            <div class="darcard-metric">
              <span class="darcard-metric-label">Risk %</span>
              <span class="darcard-metric-value">{fmt_pct(r.get('risk_pct'))}</span>
            </div>
          </div>

          <!-- Notes -->
          <div class="darcard-notes">{note_html}</div>

        </div>"""

    total = len(candidates)
    return f"""<div class="section">
      <div class="section-header">
        🃏 DAR-CARDS — Individual Stock Dossiers
        <span class="count-badge">{total} cards</span>
        <span style="margin-left:auto;font-size:11px;color:var(--muted);font-weight:400">
          Fresh Breakouts + All Approaching · Gauge shows price position inside Darvas box
        </span>
      </div>
      <div class="darcards-grid">{cards_html}</div>
    </div>"""


# ── Full HTML ─────────────────────────────────────────────────────────────────

CSS = """
:root {
  --bg:        #0D1117;
  --bg2:       #161B22;
  --bg3:       #1E2530;
  --border:    #2D3748;
  --text:      #E2E8F0;
  --muted:     #94A3B8;
  --accent:    #3B82F6;
  --hot:       #F59E0B;
  --warm:      #10B981;
  --watch:     #64748B;
  --breakout:  #EF4444;
  --good:      #22C55E;
  --warn:      #FBBF24;
  --bad:       #EF4444;
  --radius:    10px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Inter', -apple-system, sans-serif;
  font-size: 13px;
  line-height: 1.5;
}
a { color: var(--accent); }

/* Header */
.report-header {
  background: linear-gradient(135deg, #1a1f2e 0%, #0d1117 100%);
  border-bottom: 1px solid var(--border);
  padding: 24px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.report-title { font-size: 24px; font-weight: 700; letter-spacing: -0.5px; }
.report-title span { color: var(--accent); }
.scan-meta { color: var(--muted); font-size: 12px; text-align: right; line-height: 1.8; }
.scan-meta strong { color: var(--text); }
.market-status { display: inline-block; padding: 3px 10px; border-radius: 20px;
  background: rgba(34,197,94,0.15); color: var(--good); font-size: 11px; font-weight: 600; }

/* Layout */
.container { max-width: 1400px; margin: 0 auto; padding: 24px 32px; }

/* KPI Cards */
.kpi-row { display: grid; grid-template-columns: repeat(9, 1fr); gap: 12px; margin-bottom: 28px; }
.kpi-card {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 12px;
  text-align: center;
  transition: transform 0.15s;
}
.kpi-card:hover { transform: translateY(-2px); }
.kpi-value { font-size: 26px; font-weight: 700; }
.kpi-label { font-size: 11px; color: var(--muted); margin-top: 4px; }
.kpi-breakout { border-color: var(--breakout); background: rgba(239,68,68,0.08); }
.kpi-breakout .kpi-value { color: var(--breakout); }
.kpi-hot { border-color: var(--hot); background: rgba(245,158,11,0.08); }
.kpi-hot .kpi-value { color: var(--hot); }
.kpi-warm { border-color: var(--warm); background: rgba(16,185,129,0.08); }
.kpi-warm .kpi-value { color: var(--warm); }
.kpi-blue { border-color: var(--accent); background: rgba(59,130,246,0.08); }
.kpi-blue .kpi-value { color: var(--accent); }
.kpi-neutral .kpi-value { color: var(--text); }
.kpi-orders { border-color: var(--good); background: rgba(34,197,94,0.08); }
.kpi-orders .kpi-value { color: var(--good); }
.kpi-cap .kpi-value { color: var(--accent); font-size: 18px; }
.kpi-risk .kpi-value { color: var(--warn); font-size: 18px; }

/* Sections */
.section {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 20px;
  overflow: hidden;
}
.section-header {
  padding: 14px 20px;
  font-size: 14px;
  font-weight: 600;
  background: var(--bg3);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 10px;
}
.collapsible { cursor: pointer; user-select: none; }
.collapsible:hover { background: #242b38; }
.collapse-icon { margin-left: auto; font-size: 11px; color: var(--muted); }
.section-collapsed .collapsible-body { display: none; }
.count-badge {
  background: rgba(59,130,246,0.2);
  color: var(--accent);
  border-radius: 20px;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 700;
}
.empty-msg, .no-alerts {
  padding: 24px;
  color: var(--muted);
  text-align: center;
  font-style: italic;
}

/* Tables */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
thead { background: #1a2035; }
th {
  padding: 10px 14px;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
  border-bottom: 1px solid var(--border);
}
td {
  padding: 9px 14px;
  border-bottom: 1px solid rgba(45,55,72,0.5);
  white-space: nowrap;
}
tbody tr:hover { background: rgba(59,130,246,0.04); }
tbody tr:last-child td { border-bottom: none; }
.sym-cell { font-weight: 700; color: var(--text); font-size: 13px; }

/* RR colours */
.rr-good { color: var(--good); font-weight: 700; }
.rr-warn { color: var(--warn); font-weight: 600; }
.rr-bad  { color: var(--bad);  font-weight: 600; }

/* Volume colours */
.vol-surge { color: var(--hot); font-weight: 700; }
.vol-ok    { color: var(--text); }
.vol-low   { color: var(--muted); }

/* Tier badges */
.tier-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.tier-hot  { background: rgba(245,158,11,0.2); color: var(--hot);  border: 1px solid rgba(245,158,11,0.3); }
.tier-warm { background: rgba(16,185,129,0.2); color: var(--warm); border: 1px solid rgba(16,185,129,0.3); }
.tier-watch{ background: rgba(100,116,139,0.2); color: var(--watch); border: 1px solid rgba(100,116,139,0.3); }
.tier-vol  { background: rgba(239,68,68,0.15); color: #FC8181; border: 1px solid rgba(239,68,68,0.3); }
.tier-none { background: transparent; color: var(--muted); border: none; }

/* Dist bars */
.dist-cell { min-width: 120px; }
.dist-bar-wrap { background: rgba(255,255,255,0.06); border-radius: 3px; height: 4px; margin-bottom: 3px; }
.dist-bar { height: 4px; border-radius: 3px; }

/* Flags */
.flag-good { color: var(--good); font-size: 11px; font-weight: 600; }
.flag-bad  { color: var(--bad);  font-size: 11px; font-weight: 600; }

/* Alerts */
.alerts-grid { padding: 16px 20px; display: flex; flex-direction: column; gap: 10px; }
.alert-row {
  display: grid;
  grid-template-columns: 160px 90px 1fr auto;
  align-items: center;
  gap: 14px;
  background: var(--bg3);
  border-radius: 8px;
  padding: 12px 16px;
  border-left: 3px solid var(--accent);
  transition: background 0.15s;
}
.alert-row:hover { background: #242b38; }
.alert-symbol { font-weight: 700; font-size: 14px; }
.alert-badge {
  display: inline-block;
  padding: 3px 9px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  text-align: center;
}
.badge-new    { background: rgba(16,185,129,0.2); color: var(--warm); }
.badge-status { background: rgba(239,68,68,0.2);  color: #FC8181; }
.badge-tier   { background: rgba(245,158,11,0.2); color: var(--hot); }
.badge-closer { background: rgba(59,130,246,0.2); color: #93C5FD; }
.badge-vol    { background: rgba(168,85,247,0.2); color: #C084FC; }
.alert-msg { font-size: 13px; }
.alert-detail { font-size: 11px; color: var(--muted); text-align: right; }

/* Order Summary */
.order-summary {
  display: flex;
  gap: 16px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.os-card {
  background: var(--bg3);
  border-radius: 8px;
  padding: 10px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.os-val { font-size: 18px; font-weight: 700; color: var(--accent); }
.os-lbl { font-size: 11px; color: var(--muted); }
.os-risk .os-val { color: var(--bad); }
.os-rew  .os-val { color: var(--good); }
.os-rr   .os-val { color: var(--warn); }

/* Order status badges */
.status-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.ord-placed  { background: rgba(34,197,94,0.15);  color: var(--good); }
.ord-pending { background: rgba(251,191,36,0.15); color: var(--warn); }
.ord-failed  { background: rgba(239,68,68,0.15);  color: var(--bad); }
.order-id { font-family: monospace; font-size: 11px; color: var(--muted); }

/* Charts */
.charts-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 20px; }
.chart-card {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}
.chart-title { font-size: 13px; font-weight: 600; color: var(--muted); margin-bottom: 16px; text-transform: uppercase; letter-spacing: 0.5px; }
.chart-wrap { position: relative; height: 220px; }

/* Divider */
.divider { height: 1px; background: var(--border); margin: 28px 0; }

/* Footer */
.report-footer {
  text-align: center;
  padding: 24px;
  color: var(--muted);
  font-size: 11px;
  border-top: 1px solid var(--border);
  margin-top: 40px;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

@media (max-width: 900px) {
  .kpi-row { grid-template-columns: repeat(3, 1fr); }
  .charts-row { grid-template-columns: 1fr; }
  .alert-row { grid-template-columns: 1fr 1fr; }
}

/* ── DAR-CARDS ─────────────────────────────────────────────────────────── */
.darcards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  padding: 20px;
}
.darcard {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  transition: transform 0.15s, box-shadow 0.15s;
  position: relative;
}
.darcard:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 30px rgba(0,0,0,0.4);
}
/* Left accent stripe by tier/status */
.darcard-hot    { border-left: 4px solid var(--hot); }
.darcard-warm   { border-left: 4px solid var(--warm); }
.darcard-watch  { border-left: 4px solid var(--watch); }
.darcard-bo     { border-left: 4px solid var(--breakout); }

.darcard-header {
  padding: 14px 16px 10px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
}
.darcard-sym {
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.5px;
  line-height: 1;
}
.darcard-sym small {
  display: block;
  font-size: 10px;
  font-weight: 500;
  color: var(--muted);
  margin-top: 3px;
  letter-spacing: 0.3px;
}
.darcard-badges { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.darcard-status {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.6px;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 4px;
}
.dcs-bo    { background: rgba(239,68,68,0.2);  color: var(--breakout); }
.dcs-ap    { background: rgba(245,158,11,0.15); color: var(--hot); }

/* Box gauge — shows where price sits inside the Darvas box */
.darcard-gauge-wrap {
  padding: 12px 16px 8px;
  border-bottom: 1px solid var(--border);
}
.darcard-gauge-label {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--muted);
  margin-bottom: 5px;
}
.darcard-gauge-label span { font-weight: 600; color: var(--text); }
.darcard-gauge-track {
  position: relative;
  height: 10px;
  background: rgba(255,255,255,0.06);
  border-radius: 6px;
  overflow: visible;
}
.darcard-gauge-fill {
  height: 100%;
  border-radius: 6px;
  transition: width 0.3s;
}
.darcard-gauge-marker {
  position: absolute;
  top: -3px;
  width: 4px;
  height: 16px;
  background: #fff;
  border-radius: 2px;
  box-shadow: 0 0 6px rgba(255,255,255,0.5);
  transform: translateX(-50%);
}
.darcard-gauge-pct {
  font-size: 10px;
  color: var(--muted);
  margin-top: 5px;
  text-align: center;
}

/* Grid of stats */
.darcard-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  border-bottom: 1px solid var(--border);
}
.darcard-stat {
  padding: 9px 14px;
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}
.darcard-stat:nth-child(even) { border-right: none; }
.darcard-stat:nth-last-child(-n+2) { border-bottom: none; }
.darcard-stat-label {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--muted);
  margin-bottom: 2px;
}
.darcard-stat-value {
  font-size: 13px;
  font-weight: 700;
}

/* Trade parameters band */
.darcard-trade {
  padding: 10px 16px;
  background: rgba(59,130,246,0.04);
  border-bottom: 1px solid var(--border);
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 6px;
  text-align: center;
}
.darcard-trade-item { }
.darcard-trade-label {
  font-size: 9px;
  text-transform: uppercase;
  color: var(--muted);
  letter-spacing: 0.4px;
}
.darcard-trade-val { font-size: 12px; font-weight: 700; }
.dtv-entry  { color: var(--accent); }
.dtv-sl     { color: var(--bad); }
.dtv-target { color: var(--good); }

/* Metrics row */
.darcard-metrics {
  display: flex;
  padding: 9px 16px;
  gap: 16px;
  border-bottom: 1px solid var(--border);
  align-items: center;
}
.darcard-metric { display: flex; flex-direction: column; align-items: center; flex: 1; }
.darcard-metric-label { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px; }
.darcard-metric-value { font-size: 13px; font-weight: 700; }

/* Notes */
.darcard-notes {
  padding: 10px 14px;
  font-size: 11px;
  color: var(--muted);
  background: rgba(255,255,255,0.02);
  min-height: 36px;
  font-style: italic;
  border-radius: 0 0 12px 12px;
}
.darcard-notes strong { color: var(--text); font-style: normal; }
"""


JS = """
function toggleSection(el) {
  const section = el.closest('.section');
  const body    = section.querySelector('.collapsible-body');
  const icon    = el.querySelector('.collapse-icon');
  if (body.style.display === 'none' || !body.style.display) {
    body.style.display = 'block';
    icon.textContent   = '▲';
  } else {
    body.style.display = 'none';
    icon.textContent   = '▼';
  }
}

// ── Charts ────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const chartData = window.__CHART_DATA__;

  // 1. Status doughnut
  new Chart(document.getElementById('statusChart'), {
    type: 'doughnut',
    data: {
      labels: chartData.status_labels,
      datasets: [{
        data:            chartData.status_values,
        backgroundColor: chartData.status_colors,
        borderColor:     '#1E2530',
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { color: '#94A3B8', boxWidth: 12, font: { size: 11 } } }
      }
    }
  });

  // 2. Scatter – dist vs RR
  const scatterPoints = chartData.scatter_data.map(d => ({
    x: d.x, y: d.y, r: d.r,
    label: d.label, color: d.color
  }));
  new Chart(document.getElementById('scatterChart'), {
    type: 'bubble',
    data: {
      datasets: [{
        label: 'Approaching Stocks',
        data: scatterPoints,
        backgroundColor: scatterPoints.map(p => p.color + '99'),
        borderColor:     scatterPoints.map(p => p.color),
        borderWidth: 1,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const d = ctx.raw;
              return `${d.label}  dist=${d.x}%  RR=${d.y}`;
            }
          }
        },
        annotation: {
          annotations: {
            rrLine: { type: 'line', yMin: 1, yMax: 1, borderColor: '#EF4444', borderWidth: 1, borderDash: [4,4] },
            distLine: { type: 'line', xMin: 5, xMax: 5, borderColor: '#64748B', borderWidth: 1, borderDash: [4,4] },
          }
        }
      },
      scales: {
        x: { title: { display: true, text: 'Distance to Ceiling (%)', color: '#64748B' },
             grid: { color: '#2D3748' }, ticks: { color: '#64748B' } },
        y: { title: { display: true, text: 'R:R Ratio', color: '#64748B' },
             grid: { color: '#2D3748' }, ticks: { color: '#64748B' } },
      }
    }
  });

  // 3. Histogram – days in box
  new Chart(document.getElementById('histChart'), {
    type: 'bar',
    data: {
      labels: chartData.hist_labels,
      datasets: [{
        label: 'Stocks by Days in Box',
        data: chartData.hist_values,
        backgroundColor: '#3B82F655',
        borderColor: '#3B82F6',
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: '#2D3748' }, ticks: { color: '#64748B' } },
        y: { grid: { color: '#2D3748' }, ticks: { color: '#64748B', stepSize: 1 } },
      }
    }
  });
});
"""


def generate_html(latest_df, prev_df, orders_df, latest_path, prev_path, notes_map=None):
    notes_map = notes_map or {}

    alerts      = compute_deltas(latest_df, prev_df)
    chart_data  = build_charts_data(latest_df)

    # Scan timestamps
    fname       = Path(latest_path).stem  # darvas_scan_20260223_2314
    parts       = fname.replace("darvas_scan_", "").split("_")
    try:
        dt_latest = datetime.strptime(f"{parts[0]}_{parts[1]}", "%Y%m%d_%H%M")
        scan_time = dt_latest.strftime("%d %b %Y, %I:%M %p")
    except: scan_time = fname

    prev_time = "–"
    if prev_path:
        pfname = Path(prev_path).stem
        pparts = pfname.replace("darvas_scan_", "").split("_")
        try:
            dt_prev  = datetime.strptime(f"{pparts[0]}_{pparts[1]}", "%Y%m%d_%H%M")
            prev_time = dt_prev.strftime("%d %b %Y, %I:%M %p")
        except: prev_time = pfname

    generated_at = datetime.now().strftime("%d %b %Y, %I:%M %p")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DarvasTrader — Morning Briefing {datetime.now().strftime('%d %b %Y')}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>{CSS}</style>
  <script>window.__CHART_DATA__ = {json.dumps(chart_data)};</script>
</head>
<body>

<header class="report-header">
  <div>
    <div class="report-title">📈 Darvas<span>Trader</span> — Morning Briefing</div>
    <div style="color:var(--muted);font-size:12px;margin-top:4px;">
      Nicholas Darvas Box Scanner · NSE Equities
    </div>
  </div>
  <div class="scan-meta">
    <div><strong>Latest Scan:</strong> {scan_time}</div>
    <div><strong>Prior Scan:</strong>  {prev_time}</div>
    <div><strong>Report Generated:</strong> {generated_at}</div>
    <div style="margin-top:6px;"><span class="market-status">● System Active</span></div>
  </div>
</header>

<main class="container">

  {build_kpi_cards(latest_df, orders_df)}

  {build_alerts_section(alerts)}

  <div class="charts-row">
    <div class="chart-card">
      <div class="chart-title">📊 Universe by Status</div>
      <div class="chart-wrap"><canvas id="statusChart"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">🎯 Distance to Ceiling vs R:R</div>
      <div class="chart-wrap"><canvas id="scatterChart"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">📅 Days in Box Distribution</div>
      <div class="chart-wrap"><canvas id="histChart"></canvas></div>
    </div>
  </div>

  {build_breakouts_table(latest_df)}
  {build_approaching_table(latest_df)}
  {build_darcards_section(latest_df, notes_map)}
  {build_watching_table(latest_df)}

  <div class="divider"></div>

  {build_orders_section(orders_df)}

</main>

<footer class="report-footer">
  DarvasTrader · Automated Daily Briefing ·
  Scan file: <code>{Path(latest_path).name}</code> ·
  {len(latest_df)} stocks analysed
</footer>

<script>{JS}</script>
</body>
</html>"""
    return html


# ── Entry Point ───────────────────────────────────────────────────────────────
def load_watchlist_notes():
    """Return {symbol: notes} from watchlist.csv if the notes column exists."""
    wl_path = SCANNER_DIR / "watchlist.csv"
    if not wl_path.exists():
        return {}
    try:
        wl = pd.read_csv(wl_path)
        if "notes" in wl.columns and "symbol" in wl.columns:
            return {str(r["symbol"]): str(r["notes"]) for _, r in wl.iterrows()}
    except Exception as e:
        print(f"⚠️  Could not load watchlist notes: {e}")
    return {}


def main():
    no_open = "--no-open" in sys.argv

    latest_df, prev_df, latest_path, prev_path = load_scan_files()
    orders_df  = load_today_orders()
    notes_map  = load_watchlist_notes()

    print(f"📂 Scan file : {Path(latest_path).name}  ({len(latest_df)} stocks)")
    if prev_path:
        print(f"📂 Prior file: {Path(prev_path).name}")
    else:
        print("ℹ️  No prior scan found — movement alerts skipped.")
    print(f"📋 Orders    : {len(orders_df)} orders loaded for today")

    html = generate_html(latest_df, prev_df, orders_df, latest_path, prev_path, notes_map)

    out_name = f"morning_briefing_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    out_path = REPORT_DIR / out_name
    out_path.write_text(html, encoding="utf-8")

    # Always update a fixed "latest" copy for quick access
    latest_link = REPORT_DIR / "latest.html"
    latest_link.write_text(html, encoding="utf-8")

    print(f"\n✅ Report saved  → {out_path}")
    print(f"✅ Latest copy   → {latest_link}")

    if not no_open:
        webbrowser.open(latest_link.as_uri())
        print("🌐 Opened in browser.")


if __name__ == "__main__":
    main()
