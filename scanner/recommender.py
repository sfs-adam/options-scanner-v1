"""
recommender.py - Trade Quality Gate and Buy Call recommendation engine.

Recommendation tiers:
  BUY CALL  - Score >= 70, all hard gates clear
  WATCH     - Score 55-69, or good setup needing one confirmation
  NO TRADE  - Hard disqualifiers: bad liquidity, earnings imminent,
              below 200 SMA, score < 55

Research infrastructure only - does not recommend trades as financial advice.
"""


# --- Constants ---

MIN_SCORE_NO_TRADE = 55
MIN_SCORE_BUY_CALL = 70
MIN_SCORE_FOR_BACKUP = 70


def _safe(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# --- Hard Gate: NO TRADE ---

def check_hard_gate(d, score):
    blocks = []

    dte = d.get("days_to_earnings")
    if dte is not None and dte <= 7:
        n = dte
        s = "s" if n != 1 else ""
        blocks.append((
            "Earnings in " + str(n) + " day" + s,
            "Holding a long call through earnings risks a large gap-down that can wipe the position.",
        ))

    if d.get("above_200") is False:
        blocks.append((
            "Below 200 SMA",
            "Stock is not in a long-term uptrend. Buying calls against the institutional trend has a low win rate.",
        ))

    spread = _safe(d.get("spread_pct"))
    if spread is not None and spread > 15:
        blocks.append((
            "Option spread " + str(round(spread, 1)) + "% - untradeable",
            "The bid-ask spread is too wide. Slippage will absorb any profit.",
        ))

    oi = _safe(d.get("open_interest"))
    if oi is not None and oi < 100:
        blocks.append((
            "Open interest only " + str(int(oi)) + " contracts",
            "Extremely thin options market. Fills will be difficult and exit may be impossible.",
        ))

    if score < MIN_SCORE_NO_TRADE:
        blocks.append((
            "Overall score " + str(round(score)) + " - no edge",
            "Setup does not meet the minimum threshold for any recommendation.",
        ))

    return blocks


# --- Soft Gate: WATCH ---

def check_soft_gate(d, score):
    soft = []

    if d.get("above_50") is False and d.get("above_200") is True:
        soft.append((
            "Below 50 SMA",
            "Wait for reclaim of the 50 SMA before entering.",
        ))

    pct50 = _safe(d.get("pct_above_50"))
    if pct50 is not None and pct50 > 12:
        soft.append((
            str(round(pct50, 1)) + "% above 50 SMA - extended",
            "Wait for a pullback closer to the 50 SMA before buying calls.",
        ))

    spread = _safe(d.get("spread_pct"))
    if spread is not None and 10 < spread <= 15:
        soft.append((
            "Option spread " + str(round(spread, 1)) + "% - wide",
            "Wait for tighter liquidity or consider a different expiration.",
        ))

    if MIN_SCORE_NO_TRADE <= score < MIN_SCORE_BUY_CALL:
        soft.append((
            "Score " + str(round(score)) + " - needs confirmation",
            "Setup is developing but has not reached BUY CALL threshold yet.",
        ))

    return soft


# --- Confidence checklist ---


# --- Missing requirements for WATCH cards ---

def build_watch_missing(d, score, breakdown):
    """
    Return tiered list of items preventing BUY CALL.
    Tiers: "primary" (structural), "secondary" (timing), "fine" (entry confirmation)
    Each item: {"label": str, "current": str, "target": str, "met": bool, "tier": str}
    """
    items = []

    # ── PRIMARY: structural blockers ──
    # Option spread (structural — can't trade it regardless of price action)
    spread = _safe(d.get("spread_pct"))
    if spread is not None and spread > 10:
        items.append({
            "label": "Option Spread",
            "current": str(round(spread, 1)) + "%",
            "target": "Below 10%",
            "met": False,
            "tier": "primary",
        })

    # OI (structural)
    oi = _safe(d.get("open_interest"))
    if oi is not None and oi < 200:
        items.append({
            "label": "Open Interest",
            "current": str(int(oi)) + " contracts",
            "target": "200+ contracts",
            "met": False,
            "tier": "primary",
        })

    # ── SECONDARY: timing / trend blockers ──
    # Score gap
    if score < MIN_SCORE_BUY_CALL:
        items.append({
            "label": "Trade Score",
            "current": str(round(score)) + "/100",
            "target": str(MIN_SCORE_BUY_CALL) + " minimum",
            "met": False,
            "tier": "secondary",
        })
    else:
        items.append({
            "label": "Trade Score",
            "current": str(round(score)) + "/100",
            "target": "Met",
            "met": True,
            "tier": "secondary",
        })

    # Above 50 SMA (timing — recoverable)
    if d.get("above_50") is False and d.get("above_200") is True:
        items.append({
            "label": "50 SMA Reclaim",
            "current": "Below 50 SMA",
            "target": "Two closes above 50 SMA",
            "met": False,
            "tier": "secondary",
        })

    # Extended above 50 SMA
    pct50 = _safe(d.get("pct_above_50"))
    if pct50 is not None and pct50 > 12:
        items.append({
            "label": "Pullback Needed",
            "current": str(round(pct50, 1)) + "% above 50 SMA",
            "target": "Below 12% above 50 SMA",
            "met": False,
            "tier": "secondary",
        })

    # ── FINE-TUNING: entry confirmation ──
    # Momentum sub-score
    mom_bd = breakdown.get("momentum", {})
    mom_score = mom_bd.get("score", 0)
    mom_max = mom_bd.get("max", 10)
    mom_needed = round(mom_max * 0.5)
    if mom_score < mom_needed:
        items.append({
            "label": "Momentum",
            "current": str(mom_score) + "/" + str(mom_max),
            "target": str(mom_needed) + "/" + str(mom_max) + " minimum",
            "met": False,
            "tier": "fine",
        })

    # RSI
    rsi = _safe(d.get("rsi"))
    if rsi is not None and rsi < 45:
        items.append({
            "label": "RSI Recovery",
            "current": "RSI " + str(round(rsi, 1)),
            "target": "RSI above 45",
            "met": False,
            "tier": "fine",
        })

    # 5 SMA cross
    if not d.get("crossed_above_5sma"):
        items.append({
            "label": "5 SMA Cross",
            "current": "Not confirmed",
            "target": "Two closes above 5 SMA",
            "met": False,
            "tier": "fine",
        })

    # Only return unmet items (score always shown even if met)
    score_item = next((x for x in items if x["label"] == "Trade Score"), None)
    unmet_others = [x for x in items if not x["met"] and x["label"] != "Trade Score"]
    result = []
    if score_item:
        result.append(score_item)
    result.extend(unmet_others)
    return result

def build_confidence_checklist(d, score):
    checks = []

    above_200 = d.get("above_200")
    above_50 = d.get("above_50")
    if above_200 is True and above_50 is True:
        checks.append(("Trend confirmed (above 50 & 200 SMA)", True, None))
    elif above_200 is None or above_50 is None:
        checks.append(("Trend data", False, "MA data incomplete"))
    else:
        checks.append(("Trend confirmed", False, "Below key moving average"))

    oi = _safe(d.get("open_interest"))
    spread = _safe(d.get("spread_pct"))
    if oi is not None and spread is not None:
        if oi >= 500 and spread <= 8:
            checks.append(("Liquid options (OI + spread)", True,
                           "OI " + str(int(oi)) + " - Spread " + str(round(spread, 1)) + "%"))
        elif oi >= 100 and spread <= 12:
            checks.append(("Options liquidity marginal", False,
                           "OI " + str(int(oi)) + " - Spread " + str(round(spread, 1)) + "%"))
        else:
            checks.append(("Liquid options", False,
                           "OI " + str(int(oi)) + " - Spread " + str(round(spread, 1)) + "%"))
    else:
        checks.append(("Options data", False, "Options chain unavailable"))

    dte = d.get("days_to_earnings")
    if dte is None:
        checks.append(("Earnings date", False, "Unknown - verify before entering"))
    elif dte > 30:
        checks.append(("No earnings risk (" + str(dte) + "d away)", True, None))
    elif dte > 7:
        checks.append(("Earnings in " + str(dte) + "d", False, "Manageable but exit before report"))
    else:
        checks.append(("Earnings in " + str(dte) + "d - too close", False, "Hard block triggered"))

    price = _safe(d.get("current_price"))
    source = d.get("data_source", "")
    if price and price > 0:
        note = "via " + source if source else None
        checks.append(("Price data fresh", True, note))
    else:
        checks.append(("Price data", False, "Could not fetch current price"))

    if score >= 80:
        checks.append(("High-quality setup (score " + str(round(score)) + ")", True, None))
    elif score >= 70:
        checks.append(("Good setup (score " + str(round(score)) + ")", True, None))
    else:
        checks.append(("Weak setup (score " + str(round(score)) + ")", False, "Below BUY CALL threshold"))

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    pct = round(passed / total * 100)
    pct = round(pct / 5) * 5

    return {
        "checks": [{"label": lbl, "passed": ok, "note": nt} for lbl, ok, nt in checks],
        "passed": passed,
        "total": total,
        "pct": pct,
    }


# --- Strike / expiration selection ---

def recommend_strike(d):
    """
    Delta-first strike selection: target delta 0.60-0.70.
    Falls back to highest-strike ITM if delta not in chain.
    """
    itm = d.get("itm_call")
    atm = d.get("atm_call")
    chosen_delta = _safe(d.get("chosen_delta"))

    TARGET_DELTA = 0.65

    if itm:
        strike = _safe(itm.get("strike"))
        delta = chosen_delta or _safe(itm.get("delta"))
        if strike:
            if delta is not None:
                delta_str = str(round(delta, 2))
                if 0.60 <= delta <= 0.70:
                    desc = "Delta " + delta_str + " (target 0.60-0.70 ✓)"
                    rationale = "Delta " + delta_str + " is in the ideal range — high directional exposure, meaningful intrinsic value, reasonable premium."
                else:
                    desc = "Delta " + delta_str + " (closest to 0.65 target)"
                    rationale = "Best available delta toward 0.65 target. Higher delta = more intrinsic value and less theta decay risk."
            else:
                desc = "ITM call (delta unavailable)"
                rationale = "ITM calls have more intrinsic value and higher effective delta than ATM. Verify delta on your broker."
            return {"strike": strike, "description": desc, "rationale": rationale, "delta": delta}

    if atm:
        strike = _safe(atm.get("strike"))
        delta = _safe(atm.get("delta"))
        if strike:
            desc = "ATM call" + (" — delta " + str(round(delta, 2)) if delta else "")
            return {
                "strike": strike,
                "description": desc,
                "rationale": "No ITM strikes available — ATM selected. Consider going one strike lower if liquidity allows.",
                "delta": delta,
            }

    return {
        "strike": None,
        "description": "Strike unavailable — verify options chain",
        "rationale": "Could not determine appropriate strike from available data.",
        "delta": None,
    }


def recommend_expiration(d):
    """
    Show the actual chosen expiration from the 75-105 DTE window.
    The scanner already picked the cheapest qualifying contract.
    """
    exp_date = d.get("nearest_expiration")
    exp_dte  = d.get("expiration_dte")
    iv       = _safe(d.get("iv"))

    if exp_date and exp_dte is not None:
        dte_str = str(exp_dte) + " DTE"
        if iv and iv > 50:
            rationale = "Cheapest contract in 75-105 DTE window. IV is elevated (" + str(round(iv)) + "%) — 90 DTE window limits excess premium vs longer dates."
        else:
            rationale = "Cheapest contract in 75-105 DTE window. Enough time for the trade to work with manageable theta decay."
        return {
            "date": exp_date,
            "dte": exp_dte,
            "label": exp_date + " (" + dte_str + ")",
            "rationale": rationale,
        }

    # Fallback if dte not populated
    if iv and iv > 50:
        rationale = "IV is elevated (" + str(round(iv)) + "%) — 75-105 DTE window limits premium overpay vs longer dates."
    else:
        rationale = "75-105 DTE window selected — enough time for the trade with reasonable theta."
    return {
        "date": exp_date,
        "dte": None,
        "label": exp_date or "See options chain",
        "rationale": rationale,
    }


# --- Why explanation ---

def build_why_explanation(d, score, breakdown):
    reasons = []
    iv = _safe(d.get("iv"))
    pct50 = _safe(d.get("pct_above_50"))
    rsi = _safe(d.get("rsi"))
    move20 = _safe(d.get("move_20d_pct"))
    dte = d.get("days_to_earnings")
    vol_ratio = _safe(d.get("vol_ratio_5_20"))

    if d.get("above_200") and d.get("above_50"):
        reasons.append("Stock is above both the 50 and 200 SMA - trend is confirmed.")
    if d.get("sma200_rising"):
        reasons.append("200 SMA is rising - institutional trend is healthy.")
    if d.get("sma50_rising"):
        reasons.append("50 SMA is rising - intermediate trend supports the move.")
    if d.get("above_200") and not d.get("above_50"):
        reasons.append("Above 200 SMA but below 50 SMA - pullback within a healthy uptrend. Watch for 50 SMA reclaim.")

    if d.get("crossed_above_5sma"):
        reasons.append("Price just crossed above the 5 SMA - early momentum signal.")
    if pct50 is not None and pct50 <= 8:
        reasons.append("Only " + str(round(pct50, 1)) + "% above 50 SMA - not extended, room to run.")

    if iv is not None:
        if iv <= 35:
            reasons.append("IV is " + str(round(iv)) + "% - low enough that buying premium is reasonable.")
        elif iv <= 50:
            reasons.append("IV is " + str(round(iv)) + "% - moderate. A straight call is still viable.")

    if rsi is not None and 50 <= rsi <= 70:
        reasons.append("RSI " + str(round(rsi)) + " - momentum is building without being overbought.")

    if move20 is not None and 0 < move20 <= 12:
        reasons.append("Up " + str(round(move20, 1)) + "% over the last 20 sessions - controlled, sustainable move.")

    if vol_ratio is not None and vol_ratio >= 1.2:
        reasons.append("Volume expanding (" + str(round(vol_ratio, 2)) + "x 20-day average) - institutional participation likely.")

    if dte is None:
        reasons.append("Earnings date unknown - verify before entering.")
    elif dte > 30:
        reasons.append("Earnings are " + str(dte) + " days away - safe window for a 2-6 week hold.")
    elif dte > 14:
        reasons.append("Earnings in " + str(dte) + " days - manageable but exit before report.")

    reasons.append("90 DTE target minimizes theta decay during the expected hold period.")
    return reasons


# --- Risk / target estimates ---

def estimate_risk_target(d, score):
    atr = _safe(d.get("atr_pct"))

    if score >= 85:
        risk = "Medium"
    elif score >= 75:
        risk = "Medium"
    else:
        risk = "Medium-High"

    if atr and atr > 4:
        risk = "High" if score < 80 else "Medium-High"

    return {
        "risk_level": risk,
        "option_target": "+50% on call",
        "expected_hold": "2-6 weeks",
    }


# --- Summary reasons ---

def build_summary_reasons(d, breakdown):
    reasons = []

    if d.get("above_200") and d.get("sma200_rising"):
        reasons.append("Strong institutional trend (above rising 200 SMA)")
    if d.get("above_50") and d.get("sma50_rising"):
        reasons.append("Primary trend healthy (above rising 50 SMA)")
    if d.get("above_200") and not d.get("above_50"):
        reasons.append("Pullback within uptrend - watch for 50 SMA reclaim")
    if d.get("crossed_above_5sma"):
        reasons.append("First pullback / 5 SMA recross entry")

    rsi = _safe(d.get("rsi"))
    if rsi and 50 <= rsi <= 70:
        reasons.append("Momentum increasing (RSI " + str(round(rsi)) + ")")

    iv = _safe(d.get("iv"))
    if iv and iv <= 35:
        reasons.append("Reasonable IV (" + str(round(iv)) + "%) - call premium not overpriced")
    elif iv:
        reasons.append("IV " + str(round(iv)) + "% - premium elevated but manageable")

    oi = _safe(d.get("open_interest"))
    if oi and oi >= 1000:
        reasons.append("High option liquidity (OI: " + str(int(oi)) + ")")

    dte = d.get("days_to_earnings")
    if dte and dte > 30:
        reasons.append("No earnings risk (" + str(dte) + "d to earnings)")

    vol_ratio = _safe(d.get("vol_ratio_5_20"))
    if vol_ratio and vol_ratio >= 1.2:
        reasons.append("Volume expanding - institutional buying")

    return reasons[:6]


# --- Expected catalyst ---

def build_expected_catalyst(d, score, breakdown, trade):
    """
    One-line specific event the trader is waiting for.
    Returned as a short string shown in the card header area.
    """
    above_200 = d.get("above_200")
    above_50 = d.get("above_50")
    pct50 = _safe(d.get("pct_above_50"))
    rsi = _safe(d.get("rsi"))
    crossed_5 = d.get("crossed_above_5sma")
    spread = _safe(d.get("spread_pct"))
    mom_bd = breakdown.get("momentum", {})
    mom_score = mom_bd.get("score", 0)
    mom_max = mom_bd.get("max", 10)

    if trade == "BUY CALL":
        if crossed_5:
            return "Trend continuation — 5 SMA already confirmed, hold for next leg up"
        if pct50 is not None and pct50 <= 6:
            return "Trend continuation — tight pullback to 50 SMA, favorable entry"
        return "Trend continuation — momentum and trend aligned"

    if trade == "WATCH":
        catalysts = []
        # Most important first
        if above_50 is False and above_200 is True:
            catalysts.append("Reclaim 50 SMA")
        if pct50 is not None and pct50 > 12:
            catalysts.append("Pullback to within 12% of 50 SMA")
        if rsi is not None and rsi < 45:
            catalysts.append("RSI recovery above 45")
        if mom_score < round(mom_max * 0.5):
            catalysts.append("Momentum score improvement")
        if not crossed_5:
            catalysts.append("5 SMA cross confirmation")
        if spread is not None and spread > 10:
            catalysts.append("Option spread tightening below 10%")
        if score < 70:
            gap = round(70 - score)
            catalysts.append("Score +" + str(gap) + " pts to reach 70")

        if not catalysts:
            return "Monitor for entry confirmation"
        if len(catalysts) == 1:
            return "Wait for: " + catalysts[0]
        return "Wait for: " + catalysts[0] + " + " + catalysts[1]

    # NO TRADE
    if above_200 is False:
        return "Needs to reclaim 200 SMA before any consideration"
    if spread is not None and spread > 15:
        return "Option spread must tighten significantly (" + str(round(spread, 1)) + "% currently)"
    if score < 40:
        return "Setup too weak — multiple categories need improvement"
    return "Structural issues must resolve before re-evaluation"


# --- Master recommender ---

def _no_valid_contract(d):
    """
    Returns a gate block tuple if no tradable contract was selected.
    Fires when: all contracts in the DTE window were rejected (bad spread/OI/delta),
    OR options data is entirely missing.
    """
    rejected = d.get("rejected_contracts", [])
    has_selected = any(c.get("reason") == "SELECTED" for c in rejected)
    if has_selected:
        return None  # a valid contract was found

    itm = d.get("itm_call")
    atm = d.get("atm_call")
    if itm is None and atm is None:
        # No contract at all
        if rejected:
            # We tried but everything failed liquidity checks
            reasons = list({c.get("reason", "Unknown") for c in rejected if c.get("reason") != "SELECTED"})
            detail = "All contracts in 75-105 DTE window rejected. Reasons: " + "; ".join(reasons[:3])
        else:
            detail = "No options chain found for this ticker."
        return ("No tradable options contract", detail)

    return None  # itm or atm present — legacy path, assume ok


def generate_recommendation(d, score, breakdown):
    # 0. Contract gate — must have a valid, liquid contract before anything else
    contract_block = _no_valid_contract(d)
    if contract_block:
        rejected = d.get("rejected_contracts", [])
        return {
            "trade": "NO TRADE",
            "watch_reasons": [],
            "confidence": None,
            "gate_blocks": [{"label": contract_block[0], "detail": contract_block[1]}],
            "summary_reasons": [contract_block[0]],
            "why_explanation": ["[blocked] " + contract_block[0] + ": " + contract_block[1]],
            "expected_catalyst": "Verify options chain manually — no liquid contract found in 75-105 DTE window",
            "strike": None,
            "expiration": None,
            "expected_hold": None,
            "risk_level": None,
            "option_target": None,
            "rejected_contracts": rejected,
            "backups": [],
        }

    # 1. Hard gate - NO TRADE
    hard_blocks = check_hard_gate(d, score)
    if hard_blocks:
        return {
            "trade": "NO TRADE",
            "watch_reasons": [],
            "confidence": None,
            "gate_blocks": [{"label": b[0], "detail": b[1]} for b in hard_blocks],
            "summary_reasons": [b[0] for b in hard_blocks],
            "why_explanation": ["[blocked] " + b[0] + ": " + b[1] for b in hard_blocks],
            "expected_catalyst": build_expected_catalyst(d, score, breakdown, "NO TRADE"),
            "strike": None,
            "expiration": None,
            "expected_hold": None,
            "risk_level": None,
            "option_target": None,
            "rejected_contracts": d.get("rejected_contracts", []),
            "backups": [],
        }

    # 2. Soft gate - WATCH
    soft_blocks = check_soft_gate(d, score)
    if soft_blocks:
        why = build_why_explanation(d, score, breakdown)
        summary_reasons = build_summary_reasons(d, breakdown)
        missing = build_watch_missing(d, score, breakdown)
        return {
            "trade": "WATCH",
            "watch_reasons": [{"label": b[0], "detail": b[1]} for b in soft_blocks],
            "missing_requirements": missing,
            "confidence": None,
            "gate_blocks": [],
            "summary_reasons": [b[0] for b in soft_blocks],
            "why_explanation": why,
            "expected_catalyst": build_expected_catalyst(d, score, breakdown, "WATCH"),
            "strike": None,
            "expiration": None,
            "expected_hold": None,
            "risk_level": None,
            "option_target": None,
            "backups": [],
        }

    # 3. BUY CALL
    confidence = build_confidence_checklist(d, score)
    strike_rec = recommend_strike(d)
    exp_rec = recommend_expiration(d)
    risk_target = estimate_risk_target(d, score)
    why = build_why_explanation(d, score, breakdown)
    summary_reasons = build_summary_reasons(d, breakdown)

    result = {
        "trade": "BUY CALL",
        "watch_reasons": [],
        "confidence": confidence,
        "gate_blocks": [],
        "summary_reasons": summary_reasons,
        "why_explanation": why,
        "expected_catalyst": build_expected_catalyst(d, score, breakdown, "BUY CALL"),
        "strike": strike_rec,
        "expiration": exp_rec,
        "expected_hold": risk_target["expected_hold"],
        "risk_level": risk_target["risk_level"],
        "option_target": risk_target["option_target"],
        "rejected_contracts": d.get("rejected_contracts", []),
        "backups": [],
    }

    # Optional backups
    if score >= MIN_SCORE_FOR_BACKUP:
        iv = _safe(d.get("iv"))
        conf_pct = confidence["pct"]

        if iv and iv >= 40:
            result["backups"].append({
                "trade": "BULL CALL DEBIT SPREAD",
                "confidence_pct": max(conf_pct - 8, 50),
                "rationale": (
                    "IV at " + str(round(iv)) + "% makes outright calls expensive. "
                    "A debit spread caps max loss while reducing premium cost, "
                    "at the cost of capping upside."
                ),
            })

        pct50 = _safe(d.get("pct_above_50"))
        sma50_rising = d.get("sma50_rising")
        if sma50_rising and pct50 is not None and pct50 >= 3 and score >= 80:
            result["backups"].append({
                "trade": "BULL PUT CREDIT SPREAD",
                "confidence_pct": max(conf_pct - 12, 50),
                "rationale": (
                    "Strong trend with price well above 50 SMA. "
                    "A put credit spread generates income if the stock stays above the short strike."
                ),
            })

    result["backups"] = result["backups"][:2]
    return result
