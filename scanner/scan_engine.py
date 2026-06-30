"""
scan_engine.py — Orchestrates fetch → score → recommend for a list of tickers.

Research infrastructure only — does not recommend trades as financial advice.
"""

import datetime
import sys
import time

from .data_fetcher import fetch_ticker, fetch_spy_20d_return, set_spy_baseline
from .scoring import compute_score
from .recommender import generate_recommendation

UTC = datetime.timezone.utc


def scan_one(ticker: str, is_etf: bool = False):
    """Scan a single ticker. Returns the full result dict."""
    raw = fetch_ticker(ticker, is_etf=is_etf)

    if not raw.get("ok"):
        return {
            "ticker": ticker,
            "is_etf": is_etf,
            "ok": False,
            "error": raw.get("error", "Unknown fetch error"),
            "score": 0,
            "breakdown": {},
            "recommendation": {
                "trade": "NO TRADE",
                "confidence": None,
                "gate_blocks": [{"label": "Data unavailable", "detail": raw.get("error", "")}],
                "summary_reasons": ["Data could not be fetched"],
                "why_explanation": [],
                "strike": None,
                "expiration": None,
                "expected_hold": None,
                "risk_level": None,
                "option_target": None,
                "backups": [],
            },
            "raw_data": raw,
        }

    score, breakdown = compute_score(raw)
    rec = generate_recommendation(raw, score, breakdown)

    return {
        "ticker": ticker,
        "is_etf": is_etf,
        "ok": True,
        "error": raw.get("error"),  # non-fatal warnings
        "score": score,
        "breakdown": breakdown,
        "recommendation": rec,
        "raw_data": raw,
    }


def _annotate_top_pick(top, buy_calls, all_results):
    """
    Add a 'ranked_first' block to the top BUY CALL explaining why it
    beat every other candidate in this scan.
    """
    reasons = []
    ticker = top["ticker"]
    top_score = top["score"]
    top_raw = top.get("raw_data", {})
    top_iv = top_raw.get("iv")
    top_bd = top.get("breakdown", {})

    # Trend score comparison (key is "trend_quality" in breakdown)
    trend_scores = [
        (r["ticker"], r["breakdown"].get("trend_quality", {}).get("score", 0))
        for r in buy_calls
        if r["ticker"] != ticker
    ]
    top_trend = top_bd.get("trend_quality", {}).get("score", 0)
    top_trend_max = top_bd.get("trend_quality", {}).get("max", 25)
    if trend_scores:
        if top_trend >= max(s for _, s in trend_scores):
            reasons.append("Highest trend score of all BUY CALL candidates (" + str(top_trend) + "/" + str(top_trend_max) + ")")
    else:
        reasons.append("Only BUY CALL candidate this scan — trend score " + str(top_trend) + "/" + str(top_trend_max))

    # IV comparison (lower IV = cheaper premium = better for buying calls)
    iv_vals = [
        (r["ticker"], r["raw_data"].get("iv"))
        for r in buy_calls
        if r["ticker"] != ticker and r["raw_data"].get("iv") is not None
    ]
    if top_iv is not None and iv_vals:
        if top_iv <= min(v for _, v in iv_vals):
            reasons.append("Lowest IV of BUY CALL candidates (" + str(round(top_iv)) + "%) — call premium is cheapest here")
    elif top_iv is not None:
        reasons.append("IV " + str(round(top_iv)) + "% — only candidate with options data")

    # Score gap
    if len(buy_calls) > 1:
        second_score = buy_calls[1]["score"]
        gap = top_score - second_score
        reasons.append("Score " + str(round(top_score)) + " vs next best " + str(round(second_score)) + " (+" + str(round(gap)) + " pts)")
    else:
        reasons.append("Score " + str(round(top_score)) + " — sole qualifying candidate")

    # How many qualified vs total
    total = len(all_results)
    n_buy = len(buy_calls)
    if n_buy == 1:
        reasons.append("1 of " + str(total) + " tickers scanned passed the trade gate")
    else:
        reasons.append(str(n_buy) + " qualifiers out of " + str(total) + " scanned — this ranked highest")

    # Pullback entry quality (not extended)
    pct50 = top_raw.get("pct_above_50")
    if pct50 is not None and pct50 <= 6:
        reasons.append("Clean entry — only " + str(round(pct50, 1)) + "% above 50 SMA, not overextended")

    top["ranked_first"] = {
        "is_top": True,
        "reasons": reasons,
    }


def scan_batch(tickers_list, delay: float = 13.0):
    """
    Scan multiple tickers with a delay between requests.

    Args:
        tickers_list: list of {"symbol": str, "is_etf": bool, "name": str} dicts
        delay: seconds between requests

    Returns:
        dict: Full scan output
    """
    now = datetime.datetime.now(UTC)
    results = []

    # Fetch SPY baseline once for relative strength comparison
    print("  [SPY] Fetching SPY baseline for relative strength...", end=" ", flush=True)
    spy_ret = fetch_spy_20d_return()
    set_spy_baseline(spy_ret)
    print("SPY 20d=" + (str(round(spy_ret, 2)) + "%" if spy_ret is not None else "unavailable"), flush=True)

    for i, item in enumerate(tickers_list):
        if isinstance(item, dict):
            ticker = item.get("symbol") or item.get("ticker") or str(item)
            is_etf = item.get("is_etf", False)
        else:
            ticker = str(item)
            is_etf = False

        print("  [" + str(i+1) + "/" + str(len(tickers_list)) + "] Scanning " + ticker + "...", end=" ", flush=True)

        try:
            result = scan_one(ticker, is_etf=is_etf)
            trade = result["recommendation"]["trade"]
            score = result["score"]
            print("score=" + str(round(score)) + " -> " + trade, flush=True)
            results.append(result)
        except Exception as e:
            print("FATAL: " + str(e), flush=True)
            results.append({
                "ticker": ticker,
                "is_etf": is_etf,
                "ok": False,
                "error": str(e),
                "score": 0,
                "breakdown": {},
                "recommendation": {
                    "trade": "NO TRADE",
                    "confidence": None,
                    "gate_blocks": [{"label": "Fatal error", "detail": str(e)}],
                    "summary_reasons": [str(e)],
                    "why_explanation": [],
                    "strike": None,
                    "expiration": None,
                    "expected_hold": None,
                    "risk_level": None,
                    "option_target": None,
                    "backups": [],
                },
                "raw_data": {},
            })

        if i < len(tickers_list) - 1:
            time.sleep(delay)

    # Sort: BUY CALL -> WATCH -> NO TRADE, each group by score desc
    buy_calls = sorted(
        [r for r in results if r["recommendation"]["trade"] == "BUY CALL"],
        key=lambda r: r["score"], reverse=True,
    )
    watches = sorted(
        [r for r in results if r["recommendation"]["trade"] == "WATCH"],
        key=lambda r: r["score"], reverse=True,
    )
    no_trades = sorted(
        [r for r in results if r["recommendation"]["trade"] == "NO TRADE"],
        key=lambda r: r["score"], reverse=True,
    )

    sorted_results = buy_calls + watches + no_trades

    # Annotate the top BUY CALL with cross-scan ranking context
    if buy_calls:
        _annotate_top_pick(buy_calls[0], buy_calls, results)

    return {
        "scan_timestamp_utc": now.isoformat(),
        "market_date": now.date().isoformat(),
        "tickers_scanned": len(results),
        "results": sorted_results,
        "summary": {
            "buy_call": [r["ticker"] for r in buy_calls],
            "watch": [r["ticker"] for r in watches],
            "no_trade": [r["ticker"] for r in no_trades],
            "avg_score": round(
                sum(r["score"] for r in results) / len(results), 1
            ) if results else 0,
        },
    }
