# Changelog — Options Scanner v1

All notable changes to this project are documented here.
Format: `[YYYY-MM-DD] — Description`

---

## [2026-06-30] — Initial build + full feature sprint

### Core architecture
- Built complete options scanner from scratch: data fetcher → scoring engine → recommender → Flask server → frontend UI
- Data sources: Yahoo Finance (primary) + Polygon.io (EOD fallback)
- `run.bat` launcher with automatic dependency install

### Scoring engine (8 categories, 100 pts total)
- Trend Quality (25 pts): above 200/50/20 SMA, rising MAs, 5 SMA slope
- Pullback/Entry (20 pts): 5 SMA cross, extension from 50 SMA, RSI, volume
- Option Liquidity (15 pts): OI, bid-ask spread, IV availability
- Momentum (10 pts): RSI zone, 20-day move, 20 SMA slope, direction confirmation
- Relative Strength (10 pts): stock 20d return vs SPY 20d return (true RS)
- Volatility (10 pts): IV level, ATR range
- Earnings Risk (5 pts): days to earnings
- Risk Factors (5 pts): extension, overbought RSI, volume, spread flags

### Recommendation tiers
- BUY CALL: score ≥ 70, all hard gates clear, valid liquid contract exists
- WATCH: score 55-69 or soft gate triggered (below 50 SMA, extended, wide spread)
- NO TRADE: earnings ≤7d, below 200 SMA, spread >15%, OI <100, score <55, or no valid contract

### Contract selection
- Target DTE window: 75-105 days (not a fixed point)
- Skips expirations where earnings fall inside the trade window
- Fetches all expirations in window, evaluates all ITM contracts across all of them
- Hard filters: spread >10% rejected, OI <500 rejected, delta out of 0.45-0.85 range rejected
- Ranking: delta proximity to 0.65 → OI desc → spread asc → ask asc (cheapest is tiebreaker, not primary)
- If no contract passes all filters: forced NO TRADE (stock score alone cannot produce BUY CALL)

### Frontend UI
- Dark theme, card-based layout
- BUY CALL / WATCH / NO TRADE sections with color coding
- Contract Evaluation table: every contract evaluated shown with delta, spread, OI, ask, status, rejection reason
- Missing Requirements checklist on WATCH cards (tiered: Primary / Timing / Entry Confirmation)
- Expected Catalyst line on every card
- Data Quality checklist (5-point reliability check, replaces "Confidence" label)
- Cross-scan "Why ranked #1 today" panel on top BUY CALL
- Score breakdown panel per category
- Backup strategy suggestions (debit spread, put credit spread)

### Bug fixes
- Fixed trend score showing 0/25 in ranked-first annotation (wrong breakdown key)
- Fixed options contract grabbing nearest weekly instead of targeting 75 DTE
- Fixed "cheapest" contract overriding liquidity (UNP/LYG bug)
- Fixed null bid/ask showing as 999% spread in UI
- Fixed BUY CALL issued when all contracts rejected (LYG bug)
- Fixed file truncation from Edit tool (switched to bash heredoc writes)
- Fixed UTF-16 null bytes introduced by Write tool in data_fetcher.py

---

## How to commit changes after a session

```powershell
cd "C:\Users\adamj\Cursor Apps\options-scanner-v1"
git add -A
git commit -m "brief description of what changed"
git push
```

---
