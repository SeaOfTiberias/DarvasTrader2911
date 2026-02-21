# The Nicholas Darvas Method — Full Strategy Documentation

## Who Was Nicholas Darvas?

Nicholas Darvas was a professional dancer who turned $25,000 into over $2 million in the US stock market between 1957–1959; documented in his 1960 book *"How I Made $2,000,000 in the Stock Market"*.

He developed his system while touring the world as a dancer — without real-time data, using only weekly stock tables delivered by telegram. This forced discipline into his system: he only acted on **weekly price structure**, not daily noise.

---

## Core Principle: **Techno-Fundamentalist Approach**

Darvas combined two filters:
1. **Fundamental**: Only buy stocks in **strong growth industries** (e.g., electronics in the 1960s — equivalent to AI/Cloud/Biotech today). The underlying business must be growing rapidly.
2. **Technical**: Wait for the stock to prove itself via **box breakouts with strong volume**.

---

## Box Formation Rules

### Weekly Timeframe (the foundation)

**Ceiling:**
- The highest weekly high that is NOT exceeded for the next `N` weeks (typically 3).
- This represents supply exhaustion — sellers have absorbed demand and a price ceiling has formed.

**Floor:**
- The lowest weekly low that is NOT undercut for the next `N` weeks (typically 3).
- This represents demand support — buyers defend this level repeatedly.

**Box:**
- When BOTH a ceiling AND a floor have been confirmed, a **Darvas Box** exists.
- The box represents a **zone of equilibrium** between buyers and sellers.
- Boxes can be narrow (tight consolidation — preferred) or wide.

### Box Quality Criteria (Darvas's personal filter):
- ✅ Box width < 15% (tight consolidation preferred)
- ✅ Stock is near 52-week highs (not in a downtrend)
- ✅ Volume declining *during* box formation (calm before the storm)
- ✅ Industry sector in a strong uptrend

---

## Entry Rules

### Primary Entry
1. Stock breaks out **above the Ceiling** of a confirmed Darvas Box.
2. Volume on the breakout bar must be **significantly above average** (>1.5× 20-period SMA).
3. Entry: **Buy immediately on breakout close** (or next day open).
4. Never chase — if price runs away, wait for the next box.

### Stop Loss at Entry
- Initial stop placed **just below the Box Floor** (0.5–1% buffer).
- Darvas used a very tight stop: if the breakout fails quickly, exit fast — no exceptions.

---

## Position Management

### Pyramiding (Adding to Winners)
Darvas aggressively added to winning positions:
- **Only add when the stock makes new highs** — never on pullbacks.
- Each add should be a **smaller size** than the initial (1/2 or 1/3 of original position).
- Maximum 3 adds per position (pyramid up, not down).

### Trailing the Stop
- As the stock moves higher and forms a **new Darvas Box**, raise the stop to just below the **new box's floor**.
- Never lower the stop — it only ever moves up.
- This is the core of the system: let winners run, cut losers fast.

### Exit Triggers
| Trigger | Action |
|---|---|
| Price closes below current box floor | Exit immediately |
| Stop loss level (below floor) is hit on intraday | Exit immediately |
| Stock shows signs of distribution (high vol, no price progress) | Consider exit |
| Sector rotation — industry weakening | Pre-emptive exit |

**Never average down. Never hold hoping for recovery.**

---

## Key Psychological Rules (Darvas's Own Words)

1. **"I never buy a stock on the way down."** — Only buy at new highs.
2. **"I am always wrong sometimes."** — Losses are expected; keep them small.
3. **"My stop is my only insurance."** — Never move it down.
4. **"The trend is my friend."** — Hold as long as the uptrend continues.
5. **"I eliminated gut feelings."** — Follow rules mechanically; ignore opinions.

---

## Modern Adaptations

### Stock Universe (India NSE/BSE)
- Focus on sectors with strong multi-year tailwinds: IT, Pharma, Defence, Renewable Energy, Capital Goods.
- Filter for stocks with EPS growth > 20% YoY.
- Market cap: mid-large cap preferred (reduce manipulation risk).

### Timeframe Adaptation
- **Weekly chart**: Box formation (as Darvas intended).
- **Daily chart**: Entry signal and stop management (more precision than weekly).
- **No intraday**: Darvas never used intraday data — resist the temptation.

### Volume Configuration
- Indian markets: compare to 20-day average volume.
- US markets: same — 20-day average.
- Surge threshold: 150–200% of average volume.

---

## Scanning Criteria (for the Python scanner)

### Stage 1: Universe Filter
```
- Price > 52-week moving average (uptrend filter)
- ATH lookback: within 20% of all-time high
- Sector: manually curated growth sectors
- Volume: 30-day avg > minimum liquidity threshold
```

### Stage 2: Box Detection
```
- Weekly: Ceiling confirmed (3+ bars, no new high)
- Weekly: Floor confirmed (3+ bars, no new low)
- Box width: (Ceiling - Floor) / Floor < 15%
- Volume during box: below 20-day average (quiet)
```

### Stage 3: Breakout Readiness
```
- Current price within 3% of ceiling
- Volume starting to pick up
- No upcoming earnings within 2 weeks (avoid gaps)
```

---

*"The stock market is not a lottery or a casino. It is a precise scientific mechanism once you understand the rules."*
*— Nicholas Darvas*
