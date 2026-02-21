# 📦 DarvasTrader — Nicholas Darvas Automated Trading System

> *"I only buy stocks making new highs and box breakouts with strong volume."*
> — Nicholas Darvas, *How I Made $2,000,000 in the Stock Market*

---

## 🗂️ Project Structure

```
DarvasTrader/
├── pinescript/              ← TradingView Pine Script (visual scanner)
│   └── darvas_box_scanner.pine
├── scanner/                 ← Python: stock universe scanning
│   └── (coming soon)
├── portfolio/               ← Python: position tracking & management
│   └── (coming soon)
├── agents/                  ← AI agents for buy/add/exit decisions
│   └── (coming soon)
├── config/                  ← Universe lists, API config, parameters
│   └── (coming soon)
└── docs/                    ← Strategy documentation
    └── darvas_method.md
```

---

## 🧠 The Darvas Method — Core Rules

### Box Construction (Weekly HTF)
1. A **Ceiling** is established when a weekly bar's HIGH is NOT exceeded for `N` subsequent weekly bars.
2. A **Floor** is established when a weekly bar's LOW is NOT undercut for `N` subsequent weekly bars.
3. Together, Ceiling + Floor = a **Darvas Box** — a zone of consolidation.

### Entry (Breakout Buy)
- Daily close **above the Ceiling** → potential breakout.
- Must be accompanied by a **volume surge** (>1.5× 20-bar SMA by default).
- Optional: ATR buffer filter to avoid false breakouts.

### Add-to-Position (Pyramid Up)
- Only **add** when the stock makes a **new 52-week high** while trending.
- Never average down. Darvas only added to **winning** positions.

### Exit (Stop Loss / Breakdown)
- **Trailing Stop**: placed just below the **box floor** that preceded the breakout.
- As new, higher boxes form: raise the stop to the new box's floor.
- Exit immediately if price closes **below the current box floor**.

---

## 🚦 Phase 1: Pine Script Visual Scanner (✅ Ready)

### File: `pinescript/darvas_box_scanner.pine`

**How to use on TradingView:**
1. Open TradingView → Pine Script Editor (bottom panel).
2. Paste the contents of `darvas_box_scanner.pine`.
3. Click **Add to chart**.
4. Set your chart to **Daily timeframe** — the script reads Weekly data internally via `request.security`.

### What you'll see:
| Visual Element | Meaning |
|---|---|
| 🔵 Dashed Aqua line | Active Box Ceiling (from weekly HTF) |
| 🟣 Dashed Purple line | Active Box Floor (from weekly HTF) |
| 🟦 Shaded Box Region | Darvas Box consolidation zone |
| 🟢 Triangle Up ▲ (below bar) | **BREAKOUT** buy signal |
| 🔴 Triangle Down ▼ (above bar) | **EXIT / SL Hit** signal |
| 🟡 Circle ● (below bar) | **ADD-TO** signal (52W high while in trend) |
| 🟠 Solid Orange line | Trailing Stop Loss |
| 🟩 Green background | Currently in position |

### Dashboard (top-right table):
Shows live values for: Box Ceiling / Floor / Width % / Status / Entry Price / Stop Loss / Unrealised P&L / Volume vs SMA.

### Alert Setup:
Go to **Alerts → Create Alert** and select:
- `Darvas Breakout` — fires when breakout bar confirmed
- `Darvas Exit / SL Hit` — fires on exit signal
- `Darvas Add-To-Position` — fires when adding is appropriate
- `Darvas Box Formed` — fires when a new box is detected

---

## 🐍 Phase 2: Python Scanner (Planned)

Will scan a configurable stock universe (NSE/BSE or US equities) and:
- Detect **Darvas Box formations** on weekly data.
- Flag stocks where a **breakout is imminent** (price approaching ceiling).
- Export results as a ranked watchlist.

**Planned stack**: `yfinance` / `breeze-connect`, `pandas`, `schedule`.

---

## 📊 Phase 3: Portfolio Agent (Planned)

An automated agent that:
1. Reads the current portfolio (JSON / DB).
2. Evaluates each holding:
   - ✅ **Continue holding** → stock forms higher box → raise stop.
   - ➕ **Add signal** → 52W high confirmed → add to winner.
   - 🛑 **Exit signal** → stop hit or floor violated → sell immediately.
3. Logs all decisions with reasoning.

---

## ⚙️ Configuration (Planned: `config/settings.yaml`)

```yaml
universe:
  source: "nse_500"       # or custom CSV
  file: "config/watchlist.csv"

box:
  ceiling_bars: 3         # weekly bars for ceiling confirmation
  floor_bars: 3           # weekly bars for floor confirmation

breakout:
  atr_buffer: 0.1         # ATR multiplier filter
  volume_surge: 1.5       # minimum volume surge multiple
  volume_sma_len: 20

stop_loss:
  mode: "both"            # box_floor | atr_trailing | both
  atr_length: 14
  atr_multiplier: 2.0
  floor_buffer_pct: 0.5

portfolio:
  max_positions: 10
  position_size_pct: 10   # % of capital per position
  pyramid_max: 3          # max adds per position
```

---

## 📚 References
- *How I Made $2,000,000 in the Stock Market* — Nicholas Darvas (1960)
- *Secrets of the Darvas Trading System* — Richard Rockwood
- TradingView Pine Script v5 Reference Manual

---

*Built with ❤️ for the Darvas method. Respect the boxes. Follow the trend. Cut losses fast.*
