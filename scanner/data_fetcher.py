"""
data_fetcher.py - Per-ticker data fetching for the Options Scanner.

Fetches:
  - Daily OHLCV (Polygon primary, Yahoo fallback) for MA calculations,
    relative strength, volume trend, and price move analysis
  - 5-min bars (Yahoo) for current price
  - Options chain (Yahoo v7) for IV, liquidity, and nearest expiration

Research infrastructure only - does not recommend trades as financial advice.
"""

import datetime
import sys
import time

from .yahoo_session import get_proxies, get_session, reset_session
from .polygon_client import fetch_polygon_daily, get_polygon_api_key, SOURCE_LABEL as POLY_LABEL

UTC = datetime.timezone.utc
YAHOO_LABEL = "Yahoo Finance"

# SPY baseline cache — fetched once per scan batch, reused for all tickers
_spy_cache = {"return_20d": None}

def set_spy_baseline(spy_20d_return):
    """Called once per scan batch with SPY's 20-day return."""
    _spy_cache["return_20d"] = spy_20d_return

def get_spy_baseline():
    return _spy_cache["return_20d"]

def fetch_spy_20d_return():
    """Fetch SPY 20-day price return. Returns float or None."""
    try:
        session, crumb = get_session()
        hist = fetch_daily_history("SPY", session=session, crumb=crumb)
        closes = [c for c in hist.get("closes", []) if c is not None]
        if len(closes) >= 21:
            return round((closes[-1] - closes[-21]) / closes[-21] * 100, 2)
    except Exception:
        pass
    return None


# --- Helpers ---

def _now():
    return datetime.datetime.now(UTC)


def _today():
    return _now().date()


def _safe(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _date_from_epoch(seconds):
    if seconds is None:
        return None
    try:
        return datetime.datetime.fromtimestamp(seconds, UTC).date().isoformat()
    except Exception:
        return None


def _iso_from_epoch(seconds):
    if seconds is None:
        return None
    try:
        return datetime.datetime.fromtimestamp(seconds, UTC).isoformat()
    except Exception:
        return None


# --- MA / Indicator math ---

def _sma(closes, period):
    vals = [c for c in closes if c is not None]
    if len(vals) < period:
        return None
    return sum(vals[-period:]) / period


def _ema(closes, period):
    vals = [c for c in closes if c is not None]
    if len(vals) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(vals[:period]) / period
    for c in vals[period:]:
        ema = c * k + ema * (1 - k)
    return ema


def _ema_series(closes, period):
    vals = [c for c in closes if c is not None]
    result = [None] * len(vals)
    if len(vals) < period:
        return result
    k = 2 / (period + 1)
    ema = sum(vals[:period]) / period
    result[period - 1] = ema
    for i in range(period, len(vals)):
        ema = vals[i] * k + ema * (1 - k)
        result[i] = ema
    return result


def _is_rising(series, lookback=5):
    vals = [v for v in (series or []) if v is not None]
    if len(vals) < lookback + 1:
        return None
    return vals[-1] > vals[-(lookback + 1)]


def _rsi(closes, period=14):
    vals = [c for c in closes if c is not None]
    if len(vals) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    if len(gains) < period:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _atr(highs, lows, closes, period=14):
    if not highs or not lows or not closes:
        return None
    trs = []
    for i in range(1, min(len(highs), len(lows), len(closes))):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        if h is None or l is None or pc is None:
            continue
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    atr = sum(trs[-period:]) / period
    last_close = next((c for c in reversed(closes) if c is not None), None)
    if not last_close:
        return None
    return round(atr / last_close * 100, 2)


def _volume_ratio(volumes, short=5, long=20):
    vals = [v for v in (volumes or []) if v is not None]
    if len(vals) < long:
        return None
    avg_long = sum(vals[-long:]) / long
    avg_short = sum(vals[-short:]) / short
    if avg_long == 0:
        return None
    return round(avg_short / avg_long, 3)


def _pct_above_ma(price, ma):
    if price is None or ma is None or ma == 0:
        return None
    return round((price - ma) / ma * 100, 2)


def _crossed_above_5sma(closes, sma5_series):
    closes_clean = [c for c in closes if c is not None]
    sma_clean = [s for s in sma5_series if s is not None]
    if len(closes_clean) < 2 or len(sma_clean) < 2:
        return False
    prev_below = closes_clean[-2] < sma_clean[-2]
    now_above = closes_clean[-1] >= sma_clean[-1]
    return prev_below and now_above


# --- Options helpers ---

def _pick_atm(options, price):
    if not options or price is None:
        return None
    return min(options, key=lambda o: abs((o.get("strike") or 0) - price))


def _option_mid(opt):
    if opt is None:
        return None
    bid, ask = _safe(opt.get("bid")), _safe(opt.get("ask"))
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2


def _spread_pct(opt):
    mid = _option_mid(opt)
    if mid is None or mid == 0:
        return None
    bid, ask = _safe(opt.get("bid")), _safe(opt.get("ask"))
    return round((ask - bid) / mid * 100, 2)


# --- Earnings date parsing ---

def _next_earnings(quote):
    today = _today()
    candidates = []
    for key in ("earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd"):
        val = quote.get(key)
        if val:
            try:
                d = datetime.datetime.fromtimestamp(val, UTC).date()
                if d >= today:
                    candidates.append(d)
            except Exception:
                pass
    return min(candidates).isoformat() if candidates else None


# --- Expiration / strike selection ---

# DTE window: 75-105 days, prefer cheapest ask inside range
DTE_MIN = 75
DTE_MAX = 105

def _pick_target_expiration(exps_epochs, earnings_date_str=None):
    """
    Find the best expiration in the 75-105 DTE window.
    - Skip any expiration that falls after an earnings date (earnings risk)
    - Among qualifying expirations, return all epochs in the window
      (caller picks cheapest after fetching chain)
    - Fallback: closest to 90 DTE if none in window
    """
    today = _today()
    earnings_cutoff = None
    if earnings_date_str:
        try:
            earnings_cutoff = datetime.date.fromisoformat(earnings_date_str[:10])
        except Exception:
            pass

    in_window = []
    all_candidates = []
    for ep in exps_epochs:
        try:
            exp_date = datetime.datetime.fromtimestamp(ep, UTC).date()
            dte = (exp_date - today).days
            # Skip if earnings fall before this expiration (earnings risk inside trade)
            if earnings_cutoff and earnings_cutoff <= exp_date:
                continue
            diff = abs(dte - 90)
            all_candidates.append((diff, ep, exp_date))
            if DTE_MIN <= dte <= DTE_MAX:
                in_window.append((dte, ep, exp_date))
        except Exception:
            continue

    if in_window:
        # Return all in-window epochs sorted by DTE; caller picks cheapest
        return sorted(in_window, key=lambda x: x[0])
    # Fallback: closest to 90 DTE
    if all_candidates:
        best = sorted(all_candidates)[0]
        return [(best[0], best[1], best[2])]
    return []


# Liquidity thresholds for contract selection
CONTRACT_MIN_OI     = 500
CONTRACT_MAX_SPREAD = 10.0   # %
TARGET_DELTA        = 0.65
DELTA_TARGET_MIN    = 0.60
DELTA_TARGET_MAX    = 0.70
DELTA_ACCEPT_MIN    = 0.45   # fallback if nothing in target range


def _evaluate_contracts(calls, price, exp_label=""):
    """
    Score all ITM calls in a chain against liquidity + delta criteria.
    Returns:
      candidates: list of dicts that pass all hard filters, sorted by rank
      rejected:   list of {"label", "reason"} for UI display
    """
    if not calls or price is None:
        return [], []

    candidates = []
    rejected = []

    for c in calls:
        strike = _safe(c.get("strike"))
        if strike is None or strike >= price:
            continue   # not ITM

        oi     = _safe(c.get("openInterest")) or 0
        sp_raw = _spread_pct(c)   # None if bid/ask missing
        sp     = sp_raw if sp_raw is not None else 999
        delta  = _safe(c.get("delta"))
        ask    = _safe(c.get("ask"))
        label  = exp_label + " $" + str(round(strike)) + "C"
        sp_display = round(sp_raw, 1) if sp_raw is not None else None

        # Hard filter 1: spread (also reject if ask/bid are missing entirely)
        if sp_raw is None:
            rejected.append({"label": label, "strike": strike,
                             "spread": None, "oi": int(oi),
                             "reason": "No bid/ask data (untradeable)"})
            continue
        if sp > CONTRACT_MAX_SPREAD:
            rejected.append({"label": label, "strike": strike,
                             "spread": sp_display, "oi": int(oi),
                             "reason": "Spread " + str(sp_display) + "% > " + str(CONTRACT_MAX_SPREAD) + "% limit"})
            continue

        # Hard filter 2: OI
        if oi < CONTRACT_MIN_OI:
            rejected.append({"label": label, "strike": strike,
                             "spread": sp_display, "oi": int(oi),
                             "reason": "OI " + str(int(oi)) + " < " + str(CONTRACT_MIN_OI) + " minimum"})
            continue

        # Hard filter 3: delta range (only if delta is available)
        if delta is not None and not (DELTA_ACCEPT_MIN <= delta <= 0.85):
            rejected.append({"label": label, "strike": strike,
                             "spread": sp_display, "oi": int(oi),
                             "reason": "Delta " + str(round(delta, 2)) + " out of range"})
            continue

        candidates.append({
            "contract": c,
            "strike": strike,
            "delta": delta,
            "oi": oi,
            "spread": sp,
            "ask": ask,
            "label": label,
        })

    # Rank survivors: delta proximity → OI desc → spread asc → ask asc
    def _rank(item):
        d = item["delta"] if item["delta"] is not None else TARGET_DELTA
        return (abs(d - TARGET_DELTA), -item["oi"], item["spread"], item["ask"] or 999)

    candidates.sort(key=_rank)
    return candidates, rejected


def _pick_best_itm_call(calls, price, exp_label=""):
    """Convenience wrapper — returns best contract dict or None."""
    candidates, _ = _evaluate_contracts(calls, price, exp_label)
    if candidates:
        return candidates[0]["contract"]
    return _pick_atm(calls, price)


# --- Main fetch functions ---

def fetch_daily_history(ticker, session=None, crumb=None):
    api_key = get_polygon_api_key()
    if api_key:
        result = fetch_polygon_daily(ticker, lookback_days=365, api_key=api_key)
        if result["ok"] and len(result["bars"]) >= 50:
            bars = result["bars"]
            return {
                "closes": [b["close"] for b in bars],
                "highs": [b["high"] for b in bars],
                "lows": [b["low"] for b in bars],
                "volumes": [b["volume"] for b in bars],
                "dates": [b["date"] for b in bars],
                "source": POLY_LABEL,
                "error": None,
            }

    if session is None:
        try:
            session, crumb = get_session()
        except Exception as e:
            return {"closes": [], "highs": [], "lows": [], "volumes": [], "dates": [],
                    "source": None, "error": str(e)}

    url = "https://query2.finance.yahoo.com/v8/finance/chart/" + ticker
    try:
        r = session.get(
            url,
            params={"range": "60d", "interval": "1d", "crumb": crumb},
            proxies=get_proxies(),
            timeout=15,
        )
        if r.status_code != 200:
            return {"closes": [], "highs": [], "lows": [], "volumes": [], "dates": [],
                    "source": YAHOO_LABEL, "error": "HTTP " + str(r.status_code)}
        res = r.json()["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        ts = res.get("timestamp") or []
        return {
            "closes": q.get("close") or [],
            "highs": q.get("high") or [],
            "lows": q.get("low") or [],
            "volumes": q.get("volume") or [],
            "dates": [_date_from_epoch(t) for t in ts],
            "source": YAHOO_LABEL,
            "error": None,
        }
    except Exception as e:
        return {"closes": [], "highs": [], "lows": [], "volumes": [], "dates": [],
                "source": YAHOO_LABEL, "error": str(e)}


def fetch_current_price(ticker, session, crumb):
    url = "https://query2.finance.yahoo.com/v8/finance/chart/" + ticker
    try:
        r = session.get(
            url,
            params={"range": "1d", "interval": "5m", "includePrePost": "false", "crumb": crumb},
            proxies=get_proxies(),
            timeout=15,
        )
        if r.status_code != 200:
            return None, None
        res = r.json()["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        closes = [c for c in (q.get("close") or []) if c is not None]
        ts_list = res.get("timestamp") or []
        if not closes:
            return None, None
        return closes[-1], _iso_from_epoch(ts_list[-1] if ts_list else None)
    except Exception:
        return None, None


def fetch_options_data(ticker, session, crumb, current_price=None):
    url = "https://query2.finance.yahoo.com/v7/finance/options/" + ticker
    empty = {
        "atm_call": None, "itm_call": None, "iv": None,
        "open_interest": None, "spread_pct": None,
        "expiration": None, "underlying_price": None,
        "earnings_date": None, "error": None,
    }
    try:
        r = session.get(url, params={"crumb": crumb}, proxies=get_proxies(), timeout=15)
        if r.status_code != 200:
            empty["error"] = "HTTP " + str(r.status_code)
            return empty

        data = r.json()["optionChain"]["result"][0]
        quote = data.get("quote", {})
        exps = data.get("expirationDates") or []
        price = current_price or _safe(quote.get("regularMarketPrice"))
        earnings_date = _next_earnings(quote)

        if not exps:
            empty["error"] = "No expirations in options chain"
            empty["underlying_price"] = price
            empty["earnings_date"] = earnings_date
            return empty

        candidates = _pick_target_expiration(exps, earnings_date_str=earnings_date)
        if not candidates:
            empty["error"] = "Could not select target expiration"
            empty["underlying_price"] = price
            empty["earnings_date"] = earnings_date
            return empty

        # Fetch each candidate expiration; collect all liquid contracts across expirations
        # Selection order: liquidity (spread + OI) → delta proximity → cheapest ask
        all_liquid   = []   # [(ask, dte, exp_date_str, contract_item)]
        all_rejected = []   # [{"label", "strike", "spread", "oi", "reason"}]
        any_chain    = False

        for _dte, target_epoch, exp_date_obj in candidates:
            try:
                r2 = session.get(
                    url,
                    params={"crumb": crumb, "date": str(target_epoch)},
                    proxies=get_proxies(),
                    timeout=15,
                )
                if r2.status_code != 200:
                    continue
                data2 = r2.json()["optionChain"]["result"][0]
                opts2 = data2.get("options") or []
                calls = opts2[0].get("calls", []) if opts2 else []
                if not calls:
                    continue
                any_chain = True
                exp_label = exp_date_obj.strftime("%b %d") if hasattr(exp_date_obj, "strftime") else str(exp_date_obj)
                survivors, rejected = _evaluate_contracts(calls, price, exp_label=exp_label)
                all_rejected.extend(rejected)
                for item in survivors:
                    all_liquid.append((_dte, exp_date_obj.isoformat(), item))
            except Exception:
                continue

        if not all_liquid:
            reason = "No liquid ITM contracts found in 75-105 DTE window (spread >10% or OI <500)"
            if not any_chain:
                reason = "Could not fetch options chain"
            empty["error"] = reason
            empty["rejected_contracts"] = all_rejected
            empty["underlying_price"] = price
            empty["earnings_date"] = earnings_date
            return empty

        # Among liquid survivors: rank by delta proximity → OI → spread → cheapest ask
        def _global_rank(entry):
            _dte, _exp, item = entry
            d = item["delta"] if item["delta"] is not None else TARGET_DELTA
            return (abs(d - TARGET_DELTA), -item["oi"], item["spread"], item["ask"] or 999)

        all_liquid.sort(key=_global_rank)
        best_dte, best_exp_date, best_item = all_liquid[0]

        # Mark best as selected in rejected log for UI display
        selected_label = best_item["label"]
        all_rejected.append({
            "label": selected_label,
            "strike": best_item["strike"],
            "spread": round(best_item["spread"], 1),
            "oi": int(best_item["oi"]),
            "reason": "SELECTED",
            "delta": best_item["delta"],
            "ask": best_item["ask"],
        })

        chosen = best_item["contract"]
        atm    = _pick_atm([], price)   # ATM not critical once we have ITM
        iv     = _safe(chosen.get("impliedVolatility"))
        oi     = _safe(chosen.get("openInterest"))
        sp     = _spread_pct(chosen)
        chosen_delta = _safe(chosen.get("delta"))

        return {
            "atm_call": chosen,   # use ITM as primary; ATM fallback not needed
            "itm_call": chosen,
            "iv": round(iv * 100, 1) if iv is not None else None,
            "open_interest": int(oi) if oi is not None else None,
            "spread_pct": sp,
            "expiration": best_exp_date,
            "expiration_dte": best_dte,
            "chosen_delta": round(chosen_delta, 3) if chosen_delta is not None else None,
            "rejected_contracts": all_rejected,
            "underlying_price": price,
            "earnings_date": earnings_date,
            "error": None,
        }
    except Exception as e:
        empty["error"] = str(e)
        return empty


# --- Aggregate per-ticker fetch ---

def fetch_ticker(ticker, is_etf=False):
    try:
        session, crumb = get_session()
    except Exception as e:
        return {"ticker": ticker, "is_etf": is_etf, "error": str(e), "ok": False}

    history = fetch_daily_history(ticker, session=session, crumb=crumb)
    closes = history["closes"]
    highs = history["highs"]
    lows = history["lows"]
    volumes = history["volumes"]

    current_price, price_ts = fetch_current_price(ticker, session, crumb)
    if current_price is None and closes:
        current_price = next((c for c in reversed(closes) if c is not None), None)

    options = fetch_options_data(ticker, session, crumb, current_price=current_price)

    sma5 = _sma(closes, 5)
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)
    sma5_series = [_sma(closes[:i+1], 5) for i in range(len(closes))]
    sma20_series = [_sma(closes[:i+1], 20) for i in range(len(closes))]
    sma50_series = [_sma(closes[:i+1], 50) for i in range(len(closes))]
    sma200_series = [_sma(closes[:i+1], 200) for i in range(len(closes))]
    sma50_rising = _is_rising(sma50_series, lookback=5)
    sma200_rising = _is_rising(sma200_series, lookback=10)
    sma20_rising = _is_rising(sma20_series, lookback=5)
    # Slope: compare current SMA to value 5 bars ago (as % change)
    def _slope_pct(series, lookback=5):
        clean = [s for s in series if s is not None]
        if len(clean) < lookback + 1:
            return None
        old_val = clean[-(lookback+1)]
        new_val = clean[-1]
        if not old_val:
            return None
        return round((new_val - old_val) / old_val * 100, 3)
    sma5_slope = _slope_pct(sma5_series, 3)
    sma20_slope = _slope_pct(sma20_series, 5)
    ema5 = _ema(closes, 5)
    ema5_series = _ema_series(closes, 5)
    crossed_above_5sma = _crossed_above_5sma(closes, sma5_series)
    rsi = _rsi(closes, 14)
    atr_pct = _atr(highs, lows, closes, 14)
    vol_ratio = _volume_ratio(volumes, short=5, long=20)
    above_50 = (current_price > sma50) if (current_price and sma50) else None
    above_200 = (current_price > sma200) if (current_price and sma200) else None
    pct_above_50 = _pct_above_ma(current_price, sma50)
    pct_above_200 = _pct_above_ma(current_price, sma200)

    move_20d = None
    clean_closes = [c for c in closes if c is not None]
    if len(clean_closes) >= 21:
        prior = clean_closes[-21]
        latest = clean_closes[-1]
        if prior and prior != 0:
            move_20d = round((latest - prior) / prior * 100, 2)

    days_to_earnings = None
    ed = options.get("earnings_date")
    if ed:
        try:
            d = datetime.date.fromisoformat(ed[:10])
            days_to_earnings = (d - _today()).days
        except Exception:
            pass

    return {
        "ticker": ticker,
        "is_etf": is_etf,
        "ok": True,
        "error": history.get("error") or options.get("error"),
        "data_source": history.get("source"),
        "current_price": current_price,
        "price_timestamp": price_ts,
        "sma5": sma5,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "ema5": ema5,
        "sma5_slope": sma5_slope,
        "sma20_slope": sma20_slope,
        "sma20_rising": sma20_rising,
        "sma50_rising": sma50_rising,
        "sma200_rising": sma200_rising,
        "crossed_above_5sma": crossed_above_5sma,
        "above_20": (current_price > sma20) if (current_price and sma20) else None,
        "above_50": above_50,
        "above_200": above_200,
        "pct_above_20": _pct_above_ma(current_price, sma20),
        "pct_above_50": pct_above_50,
        "pct_above_200": pct_above_200,
        "rsi": rsi,
        "atr_pct": atr_pct,
        "vol_ratio_5_20": vol_ratio,
        "move_20d_pct": move_20d,
        "iv": options["iv"],
        "open_interest": options["open_interest"],
        "spread_pct": options["spread_pct"],
        "nearest_expiration": options["expiration"],
        "expiration_dte": options.get("expiration_dte"),
        "chosen_delta": options.get("chosen_delta"),
        "rejected_contracts": options.get("rejected_contracts", []),
        "atm_call": options["atm_call"],
        "itm_call": options["itm_call"],
        "earnings_date": ed,
        "days_to_earnings": days_to_earnings,
        "spy_20d_return": get_spy_baseline(),
    }
