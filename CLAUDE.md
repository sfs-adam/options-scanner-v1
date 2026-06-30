# CLAUDE.md — Instructions for AI working on this project

This file tells any AI assistant (Claude, Cursor, etc.) how to work on this codebase.

---

## Project summary

Options scanner that fetches stock + options data, scores setups across 8 categories,
and recommends BUY CALL / WATCH / NO TRADE with specific contract details.

Stack: Python 3, Flask, Yahoo Finance API, Polygon.io, vanilla JS frontend.

---

## Mandatory: log every change to CHANGELOG.md

**Every time you modify this codebase, you must add an entry to `CHANGELOG.md`.**

Format:
```
## [YYYY-MM-DD] — Short title

- What changed and why
- Which files were modified
- Any bugs fixed
```

Add new entries at the TOP of the changelog (most recent first), below the header.
Do not rewrite old entries. Append only.

---

## Key files

| File | Purpose |
|------|---------|
| `scanner/data_fetcher.py` | Fetches price history, options chain, computes MAs/RSI/ATR |
| `scanner/scoring.py` | 8-category scoring engine (100 pts total) |
| `scanner/recommender.py` | BUY CALL / WATCH / NO TRADE logic, contract gate |
| `scanner/scan_engine.py` | Orchestrates batch scans, SPY baseline, annotates top pick |
| `server.py` | Flask server, serves frontend and `/api/scan` endpoint |
| `frontend/index.html` | Single-file dark-theme UI |
| `watchlists/default_watchlist.json` | Default ticker list |

---

## Critical rules

### File writes
**Never use the Edit tool for large sections — it truncates files.**
Always use bash heredoc for rewrites of more than ~20 lines:
```bash
cat > filepath << 'PYEOF'
...content...
PYEOF
```
For targeted patches, use Python string replacement via bash, not the Edit tool.
Always run `python3 -c "import ast; ast.parse(open('file.py').read()); print('OK')"` after any Python edit.

### Contract selection logic (do not break this)
- Hard filters run before score: spread >10% → reject, OI <500 → reject
- If no contract passes filters → NO TRADE (stock score alone cannot produce BUY CALL)
- `_no_valid_contract()` in recommender.py enforces this — do not remove it
- Cheapest ask is a tiebreaker only, not the primary ranking criterion

### Score thresholds (do not change without strong reason)
- BUY CALL: score ≥ 70
- WATCH: score 55-69
- NO TRADE: score < 55 or any hard gate triggered
- These thresholds were validated across multiple real scans

### SPY baseline
- Fetched once at scan start in `scan_batch()`, stored via `set_spy_baseline()`
- Used by `score_relative_strength()` for true stock-vs-market RS
- If SPY fetch fails, falls back to 200 SMA position method

---

## After making changes

1. Add entry to `CHANGELOG.md`
2. Run syntax check on any modified Python files
3. Remind the user to commit:
   ```powershell
   git add -A
   git commit -m "description"
   git push
   ```
