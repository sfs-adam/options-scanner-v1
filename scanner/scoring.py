"""
scoring.py — Weighted scoring engine for the Options Scanner.

Eight categories, weights sum to 100:
  Trend Quality        25
  Pullback / Entry     20
  Option Liquidity     15
  Momentum             10
  Relative Strength    10
  Volatility           10
  Earnings Risk         5
  Risk Factors          5

Research infrastructure only — does not recommend trades as financial advice.
"""


# ─── Category weights ────────────────────────────────────────────────────────

WEIGHTS = {
    "trend_quality":    25,
    "pullback_entry":   20,
    "option_liquidity": 15,
    "momentum":         10,
    "relative_strength": 10,
    "volatility":       10,
    "earnings_risk":     5,
    "risk_factors":      5,
}

assert sum(WEIGHTS.values()) == 100, "Weights must sum to 100"


def _safe(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ─── Individual category scorers ─────────────────────────────────────────────

def score_trend_quality(d):
    """
    25 pts — granular, not binary.

      Above 200 SMA       +6   (long-term institutional trend)
      200 SMA rising      +5   (trend accelerating, not just alive)
      Above 50 SMA        +5   (primary intermediate trend)
        └ below 50 but above 200 → +2 partial (pullback, not breakdown)
      50 SMA rising       +4   (intermediate trend healthy)
      Above 20 SMA        +3   (short-term momentum)
      5 SMA slope up      +2   (very recent price acceleration)

    Total raw = 25. Designed so a strong trending stock scores 20-25,
    a pullback-within-uptrend scores 12-17, a breakdown scores 0-8.
    """
    pts = 0
    detail = {}

    above_200    = d.get("above_200")
    sma200_rising = d.get("sma200_rising")
    above_50     = d.get("above_50")
    sma50_rising  = d.get("sma50_rising")
    above_20     = d.get("above_20")
    sma5_slope   = _safe(d.get("sma5_slope"))

    # Above 200 SMA (+6)
    if above_200 is True:
        pts += 6
        detail["above_200_sma"] = "✓ (+6) — above institutional trend line"
    elif above_200 is False:
        detail["above_200_sma"] = "✗ (0) — below 200 SMA"
    else:
        detail["above_200_sma"] = "? (0) — insufficient history"

    # 200 SMA rising (+5)
    if sma200_rising is True:
        pts += 5
        detail["sma200_rising"] = "✓ (+5) — 200 SMA rising"
    elif sma200_rising is False:
        detail["sma200_rising"] = "✗ (0) — 200 SMA flat or declining"
    else:
        detail["sma200_rising"] = "? (0) — insufficient history"

    # Above 50 SMA (+5 full, +2 partial if above 200)
    if above_50 is True:
        pts += 5
        detail["above_50_sma"] = "✓ (+5) — above primary trend line"
    elif above_50 is False and above_200 is True:
        pts += 2
        detail["above_50_sma"] = "~ (+2) — below 50 SMA but above 200 (pullback)"
    elif above_50 is False:
        detail["above_50_sma"] = "✗ (0) — below 50 SMA in downtrend"
    else:
        detail["above_50_sma"] = "? (0) — insufficient history"

    # 50 SMA rising (+4)
    if sma50_rising is True:
        pts += 4
        detail["sma50_rising"] = "✓ (+4) — 50 SMA rising"
    elif sma50_rising is False:
        detail["sma50_rising"] = "✗ (0) — 50 SMA flat or declining"
    else:
        detail["sma50_rising"] = "? (0) — insufficient history"

    # Above 20 SMA (+3)
    if above_20 is True:
        pts += 3
        detail["above_20_sma"] = "✓ (+3) — above 20 SMA (short-term trend)"
    elif above_20 is False:
        detail["above_20_sma"] = "✗ (0) — below 20 SMA"
    else:
        detail["above_20_sma"] = "? (0) — insufficient history"

    # 5 SMA slope positive (+2)
    if sma5_slope is not None:
        if sma5_slope > 0.1:
            pts += 2
            detail["sma5_slope"] = "✓ (+2) — 5 SMA slope positive (" + str(round(sma5_slope, 2)) + "%)"
        elif sma5_slope > 0:
            pts += 1
            detail["sma5_slope"] = "~ (+1) — 5 SMA slope slightly positive"
        else:
            detail["sma5_slope"] = "✗ (0) — 5 SMA slope negative (" + str(round(sma5_slope, 2)) + "%)"
    else:
        detail["sma5_slope"] = "? (0) — slope unavailable"

    raw_max = 25
    score = round(pts / raw_max * WEIGHTS["trend_quality"], 1)
    return min(score, WEIGHTS["trend_quality"]), detail


def score_pullback_entry(d):
    """
    20 pts.

    Crossed above 5 SMA recently   → 8 pts
    Not extended (< 8% above 50)   → 6 pts  (progressively penalized)
    RSI not overbought (< 70)      → 3 pts
    Volume expanding on entry      → 3 pts
    """
    pts = 0
    detail = {}

    crossed  = d.get("crossed_above_5sma")
    pct50    = _safe(d.get("pct_above_50"))
    rsi      = _safe(d.get("rsi"))
    vol_ratio = _safe(d.get("vol_ratio_5_20"))

    # 5 SMA crossover
    if crossed:
        pts += 8
        detail["5sma_cross"] = "✓ (+8) — price just crossed above 5 SMA"
    else:
        sma5  = _safe(d.get("sma5"))
        price = _safe(d.get("current_price"))
        if sma5 and price and price > sma5:
            pts += 4
            detail["5sma_cross"] = "~ (+4) — above 5 SMA but no fresh cross"
        else:
            detail["5sma_cross"] = "✗ (0) — price below 5 SMA"

    # Extension check
    if pct50 is not None:
        if pct50 <= 5:
            pts += 6
            detail["extension"] = "✓ (+6) — " + str(round(pct50, 1)) + "% above 50 SMA, not extended"
        elif pct50 <= 8:
            pts += 4
            detail["extension"] = "~ (+4) — " + str(round(pct50, 1)) + "% above 50 SMA, mildly extended"
        elif pct50 <= 12:
            pts += 1
            detail["extension"] = "⚠ (+1) — " + str(round(pct50, 1)) + "% above 50 SMA, extended"
        else:
            detail["extension"] = "✗ (0) — " + str(round(pct50, 1)) + "% above 50 SMA, too extended"
    else:
        detail["extension"] = "? (0) — 50 SMA unavailable"

    # RSI
    if rsi is not None:
        if rsi < 60:
            pts += 3
            detail["rsi"] = "✓ (+3) — RSI " + str(round(rsi)) + ", momentum building"
        elif rsi < 70:
            pts += 2
            detail["rsi"] = "~ (+2) — RSI " + str(round(rsi)) + ", approaching overbought"
        else:
            detail["rsi"] = "⚠ (0) — RSI " + str(round(rsi)) + ", overbought"
    else:
        detail["rsi"] = "? (0) — RSI unavailable"

    # Volume expansion
    if vol_ratio is not None:
        if vol_ratio >= 1.3:
            pts += 3
            detail["volume"] = "✓ (+3) — volume ratio " + str(round(vol_ratio, 2)) + "x, strong expansion"
        elif vol_ratio >= 1.0:
            pts += 2
            detail["volume"] = "~ (+2) — volume ratio " + str(round(vol_ratio, 2)) + "x, normal"
        else:
            detail["volume"] = "✗ (0) — volume ratio " + str(round(vol_ratio, 2)) + "x, declining"
    else:
        detail["volume"] = "? (0) — volume data unavailable"

    score = round(pts / 20 * WEIGHTS["pullback_entry"], 1)
    return min(score, WEIGHTS["pullback_entry"]), detail


def score_option_liquidity(d):
    """
    15 pts.

    Open interest >= 1000       → 5 pts
    Bid-ask spread <= 5%        → 5 pts  (graded)
    IV available                → 3 pts
    Options data present        → 2 pts
    """
    pts = 0
    detail = {}

    oi     = _safe(d.get("open_interest"))
    spread = _safe(d.get("spread_pct"))
    iv     = _safe(d.get("iv"))
    atm_call = d.get("atm_call")

    if atm_call is not None:
        pts += 2
        detail["options_available"] = "✓ (+2)"
    else:
        detail["options_available"] = "✗ (0) — no options chain"
        return 0, detail

    if oi is not None:
        if oi >= 5000:
            pts += 5
            detail["open_interest"] = "✓ (+5) — OI " + str(int(oi)) + ", excellent"
        elif oi >= 1000:
            pts += 3
            detail["open_interest"] = "~ (+3) — OI " + str(int(oi)) + ", adequate"
        elif oi >= 200:
            pts += 1
            detail["open_interest"] = "⚠ (+1) — OI " + str(int(oi)) + ", thin"
        else:
            detail["open_interest"] = "✗ (0) — OI " + str(int(oi)) + ", too thin"
    else:
        detail["open_interest"] = "? (0) — OI unavailable"

    if spread is not None:
        if spread <= 2:
            pts += 5
            detail["spread"] = "✓ (+5) — spread " + str(round(spread, 1)) + "%, tight"
        elif spread <= 5:
            pts += 3
            detail["spread"] = "~ (+3) — spread " + str(round(spread, 1)) + "%, acceptable"
        elif spread <= 10:
            pts += 1
            detail["spread"] = "⚠ (+1) — spread " + str(round(spread, 1)) + "%, wide"
        else:
            detail["spread"] = "✗ (0) — spread " + str(round(spread, 1)) + "%, too wide"
    else:
        detail["spread"] = "? (0) — spread unavailable"

    if iv is not None:
        pts += 3
        detail["iv_available"] = "✓ (+3) — IV " + str(round(iv, 1)) + "%"
    else:
        detail["iv_available"] = "✗ (0) — IV unavailable"

    score = round(pts / 15 * WEIGHTS["option_liquidity"], 1)
    return min(score, WEIGHTS["option_liquidity"]), detail


def score_momentum(d):
    """
    10 pts — measures acceleration, not just a static RSI reading.

    RSI in momentum zone (50-70)    → 3 pts
    RSI trending up (vs 10 days ago) → 2 pts
    20-day price move controlled     → 3 pts
    20 SMA slope positive            → 2 pts
    """
    pts = 0
    detail = {}

    rsi       = _safe(d.get("rsi"))
    move20    = _safe(d.get("move_20d_pct"))
    sma20_slope = _safe(d.get("sma20_slope"))

    # RSI level (zone, not exact number)
    if rsi is not None:
        if 55 <= rsi <= 70:
            pts += 3
            detail["rsi_level"] = "✓ (+3) — RSI " + str(round(rsi)) + ", ideal momentum zone"
        elif 50 <= rsi < 55:
            pts += 2
            detail["rsi_level"] = "~ (+2) — RSI " + str(round(rsi)) + ", building"
        elif 45 <= rsi < 50:
            pts += 1
            detail["rsi_level"] = "⚠ (+1) — RSI " + str(round(rsi)) + ", neutral"
        elif rsi > 70:
            pts += 1
            detail["rsi_level"] = "⚠ (+1) — RSI " + str(round(rsi)) + ", overbought"
        else:
            detail["rsi_level"] = "✗ (0) — RSI " + str(round(rsi)) + ", weak"
    else:
        detail["rsi_level"] = "? (0) — RSI unavailable"

    # 20-day price move (controlled momentum, not a runaway spike)
    if move20 is not None:
        if 2 <= move20 <= 12:
            pts += 3
            detail["move_20d"] = "✓ (+3) — " + str(round(move20, 1)) + "% over 20d, controlled"
        elif 0 <= move20 < 2:
            pts += 2
            detail["move_20d"] = "~ (+2) — " + str(round(move20, 1)) + "% over 20d, building"
        elif move20 > 12:
            pts += 0
            detail["move_20d"] = "⚠ (0) — " + str(round(move20, 1)) + "% over 20d, extended"
        else:
            pts += 1
            detail["move_20d"] = "⚠ (+1) — " + str(round(move20, 1)) + "% over 20d, slight decline"
    else:
        detail["move_20d"] = "? (0) — insufficient history"

    # 20 SMA slope — is the intermediate trend accelerating?
    if sma20_slope is not None:
        if sma20_slope > 0.15:
            pts += 2
            detail["sma20_slope"] = "✓ (+2) — 20 SMA slope " + str(round(sma20_slope, 2)) + "%, accelerating"
        elif sma20_slope > 0:
            pts += 1
            detail["sma20_slope"] = "~ (+1) — 20 SMA slope slightly positive"
        else:
            detail["sma20_slope"] = "✗ (0) — 20 SMA slope negative (" + str(round(sma20_slope, 2)) + "%)"
    else:
        detail["sma20_slope"] = "? (0) — slope unavailable"

    # RSI direction bonus (+2): compare current RSI to approximate 10-day-ago RSI
    # We use move_20d as a proxy — if price moved positively, RSI likely rose
    # Real RSI series would be ideal; this is a reasonable approximation
    if rsi is not None and move20 is not None:
        if rsi >= 50 and move20 > 0:
            pts += 2
            detail["momentum_direction"] = "✓ (+2) — RSI above 50 with positive price trend"
        elif rsi >= 45 and move20 > 0:
            pts += 1
            detail["momentum_direction"] = "~ (+1) — RSI recovering with positive price trend"
        else:
            detail["momentum_direction"] = "✗ (0) — momentum not confirming"
    else:
        detail["momentum_direction"] = "? (0) — insufficient data"

    score = round(pts / 10 * WEIGHTS["momentum"], 1)
    return min(score, WEIGHTS["momentum"]), detail


def score_relative_strength(d):
    """
    10 pts — true relative strength: stock 20d return vs SPY 20d return.

    RS = stock_20d_return - spy_20d_return

    RS >= +8%   → 10 pts  (strongly outperforming)
    RS >= +4%   →  8 pts
    RS >= +1%   →  6 pts  (slight outperformance)
    RS >= -2%   →  4 pts  (roughly in line with market)
    RS >= -5%   →  2 pts  (mild underperformance)
    RS <  -5%   →  0 pts  (clear underperformer)

    Fallback (no SPY data): use pct_above_200 + volume as before.
    """
    pts = 0
    detail = {}

    move20    = _safe(d.get("move_20d_pct"))
    spy_20d   = _safe(d.get("spy_20d_return"))

    if move20 is not None and spy_20d is not None:
        rs = round(move20 - spy_20d, 2)
        label = ("+" if rs >= 0 else "") + str(rs) + "%"
        if rs >= 8:
            pts = 10
            detail["vs_spy"] = "✓ (+10) — RS " + label + " vs SPY (strongly outperforming)"
        elif rs >= 4:
            pts = 8
            detail["vs_spy"] = "✓ (+8) — RS " + label + " vs SPY (outperforming)"
        elif rs >= 1:
            pts = 6
            detail["vs_spy"] = "~ (+6) — RS " + label + " vs SPY (slight edge)"
        elif rs >= -2:
            pts = 4
            detail["vs_spy"] = "~ (+4) — RS " + label + " vs SPY (in line with market)"
        elif rs >= -5:
            pts = 2
            detail["vs_spy"] = "⚠ (+2) — RS " + label + " vs SPY (mild underperformance)"
        else:
            pts = 0
            detail["vs_spy"] = "✗ (0) — RS " + label + " vs SPY (clear underperformer)"
        detail["stock_20d"] = "Stock 20d: " + str(round(move20, 1)) + "%"
        detail["spy_20d"]   = "SPY 20d:   " + str(round(spy_20d, 1)) + "%"
    else:
        # Fallback: position vs 200 SMA + volume
        pct200    = _safe(d.get("pct_above_200"))
        vol_ratio = _safe(d.get("vol_ratio_5_20"))
        above_200 = d.get("above_200")

        detail["vs_spy"] = "? — SPY data unavailable, using fallback"
        if above_200 is True and pct200 is not None:
            if 1 <= pct200 <= 15:
                pts += 6
                detail["vs_200sma"] = "✓ (+6) — " + str(round(pct200, 1)) + "% above 200 SMA"
            elif pct200 > 15:
                pts += 2
                detail["vs_200sma"] = "~ (+2) — " + str(round(pct200, 1)) + "% above 200 SMA, extended"
            else:
                pts += 3
                detail["vs_200sma"] = "~ (+3) — just above 200 SMA"
        elif above_200 is False:
            detail["vs_200sma"] = "✗ (0) — below 200 SMA"
        else:
            detail["vs_200sma"] = "? (0) — insufficient data"

        if vol_ratio is not None:
            if vol_ratio >= 1.2:
                pts += 4
                detail["volume_confirm"] = "✓ (+4) — volume expanding (" + str(round(vol_ratio, 2)) + "x)"
            elif vol_ratio >= 0.9:
                pts += 2
                detail["volume_confirm"] = "~ (+2) — volume normal (" + str(round(vol_ratio, 2)) + "x)"
            else:
                detail["volume_confirm"] = "✗ (0) — volume contracting (" + str(round(vol_ratio, 2)) + "x)"
        else:
            detail["volume_confirm"] = "? (0) — volume data unavailable"

    score = round(pts / 10 * WEIGHTS["relative_strength"], 1)
    return min(score, WEIGHTS["relative_strength"]), detail


def score_volatility(d):
    """
    10 pts.

    IV <= 35%     → 4-5 pts (progressively penalized above)
    ATR range     → 3-5 pts (ideal movement without erratic swings)
    """
    pts = 0
    detail = {}

    iv  = _safe(d.get("iv"))
    atr = _safe(d.get("atr_pct"))

    if iv is not None:
        if iv <= 20:
            pts += 5
            detail["iv"] = "✓ (+5) — IV " + str(round(iv, 1)) + "%, low (cheap premium)"
        elif iv <= 35:
            pts += 4
            detail["iv"] = "✓ (+4) — IV " + str(round(iv, 1)) + "%, reasonable"
        elif iv <= 50:
            pts += 2
            detail["iv"] = "~ (+2) — IV " + str(round(iv, 1)) + "%, elevated"
        elif iv <= 70:
            pts += 1
            detail["iv"] = "⚠ (+1) — IV " + str(round(iv, 1)) + "%, high"
        else:
            detail["iv"] = "✗ (0) — IV " + str(round(iv, 1)) + "%, very high"
    else:
        detail["iv"] = "? (0) — IV unavailable"

    if atr is not None:
        if atr <= 1.5:
            pts += 3
            detail["atr"] = "✓ (+3) — ATR " + str(round(atr, 1)) + "%, controlled"
        elif atr <= 3.0:
            pts += 5
            detail["atr"] = "✓ (+5) — ATR " + str(round(atr, 1)) + "%, ideal"
        elif atr <= 5.0:
            pts += 3
            detail["atr"] = "~ (+3) — ATR " + str(round(atr, 1)) + "%, elevated"
        else:
            pts += 1
            detail["atr"] = "⚠ (+1) — ATR " + str(round(atr, 1)) + "%, high daily swings"
    else:
        detail["atr"] = "? (0) — ATR unavailable"

    score = round(pts / 10 * WEIGHTS["volatility"], 1)
    return min(score, WEIGHTS["volatility"]), detail


def score_earnings_risk(d):
    """
    5 pts.

    Earnings within 7 days  → 0 pts (hard gate in recommender)
    Earnings 8-14 days      → 1 pt
    Earnings 15-30 days     → 3 pts
    Earnings > 30 days      → 5 pts
    Earnings unknown        → 2 pts
    """
    pts = 0
    detail = {}
    dte = d.get("days_to_earnings")

    if dte is None:
        pts = 2
        detail["earnings"] = "? (+2) — earnings date unknown"
    elif dte <= 7:
        pts = 0
        detail["earnings"] = "✗ (0) — earnings in " + str(dte) + "d — RISK"
    elif dte <= 14:
        pts = 1
        detail["earnings"] = "⚠ (+1) — earnings in " + str(dte) + "d — caution"
    elif dte <= 30:
        pts = 3
        detail["earnings"] = "~ (+3) — earnings in " + str(dte) + "d"
    else:
        pts = 5
        detail["earnings"] = "✓ (+5) — earnings in " + str(dte) + "d, safe window"

    score = round(pts / 5 * WEIGHTS["earnings_risk"], 1)
    return min(score, WEIGHTS["earnings_risk"]), detail


def score_risk_factors(d):
    """
    5 pts. Start at 5, deduct for red flags.
    """
    pts = 5
    detail = {}
    flags = []

    pct200    = _safe(d.get("pct_above_200"))
    rsi       = _safe(d.get("rsi"))
    vol_ratio = _safe(d.get("vol_ratio_5_20"))
    spread    = _safe(d.get("spread_pct"))

    if pct200 is not None and pct200 > 20:
        pts -= 2
        flags.append("Price " + str(round(pct200, 1)) + "% above 200 SMA — overextended")

    if rsi is not None and rsi > 75:
        pts -= 1
        flags.append("RSI " + str(round(rsi)) + " — overbought")

    if vol_ratio is not None and vol_ratio < 0.7:
        pts -= 1
        flags.append("Volume drying up (" + str(round(vol_ratio, 2)) + "x 20d avg)")

    if spread is not None and spread > 8:
        pts -= 2
        flags.append("Options spread " + str(round(spread, 1)) + "% — too wide")

    pts = max(pts, 0)
    detail["flags"] = flags if flags else ["No major risk flags"]

    score = round(pts / 5 * WEIGHTS["risk_factors"], 1)
    return min(score, WEIGHTS["risk_factors"]), detail


# ─── Master scorer ────────────────────────────────────────────────────────────

def compute_score(d):
    """
    Run all eight category scorers. Returns (total_score, breakdown_dict).
    """
    scorers = [
        ("trend_quality",     score_trend_quality),
        ("pullback_entry",    score_pullback_entry),
        ("option_liquidity",  score_option_liquidity),
        ("momentum",          score_momentum),
        ("relative_strength", score_relative_strength),
        ("volatility",        score_volatility),
        ("earnings_risk",     score_earnings_risk),
        ("risk_factors",      score_risk_factors),
    ]

    breakdown = {}
    total = 0.0

    for name, fn in scorers:
        try:
            score, detail = fn(d)
        except Exception as e:
            score, detail = 0, {"error": str(e)}
        breakdown[name] = {
            "score": score,
            "max": WEIGHTS[name],
            "detail": detail,
        }
        total += score

    return round(total, 1), breakdown
