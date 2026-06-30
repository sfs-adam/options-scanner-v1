"""
polygon_client.py — Polygon.io REST API v2 daily bars fetcher.

Uses the /v2/aggs/ticker endpoint for daily OHLCV history.
Falls back gracefully if no key is configured.
Research infrastructure only.
"""

import os
import datetime
import requests

SOURCE_LABEL = "Polygon.io"
UTC = datetime.timezone.utc
_BASE = "https://api.polygon.io"


def get_polygon_api_key():
    return os.environ.get("POLYGON_API_KEY", "").strip() or None


def _last_completed_trading_day(today):
    """
    Return the most recent completed trading day (never today).
    Free Polygon tier only has End of Day data — today's session isn't
    available until after market close and the free plan blocks it entirely.
    Skips back over weekends so Monday queries use Friday's data.
    """
    day = today - datetime.timedelta(days=1)
    # Roll back over Saturday (5) and Sunday (6)
    while day.weekday() >= 5:
        day -= datetime.timedelta(days=1)
    return day


def fetch_polygon_daily(ticker: str, lookback_days: int = 365, api_key: str = None, now=None):
    """
    Fetch daily OHLCV bars from Polygon /v2/aggs/ticker.

    End date is always the last completed trading day (never today) so the
    free-tier "End of Day" restriction doesn't block the request.

    Returns:
        dict: {"ok": bool, "bars": [...], "reason_code": str|None}
    """
    key = api_key or get_polygon_api_key()
    if not key:
        return {"ok": False, "bars": [], "reason_code": "POLYGON_NO_KEY"}

    now = now or datetime.datetime.now(UTC)
    end_date = _last_completed_trading_day(now.date())
    start_date = end_date - datetime.timedelta(days=lookback_days)

    url = (
        f"{_BASE}/v2/aggs/ticker/{ticker}/range/1/day"
        f"/{start_date.isoformat()}/{end_date.isoformat()}"
    )
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 365,
        "apiKey": key,
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 403:
            return {"ok": False, "bars": [], "reason_code": "POLYGON_AUTH_FAILED"}
        if r.status_code == 404:
            return {"ok": False, "bars": [], "reason_code": "POLYGON_TICKER_NOT_FOUND"}
        if r.status_code != 200:
            return {"ok": False, "bars": [], "reason_code": f"POLYGON_HTTP_{r.status_code}"}

        data = r.json()
        results = data.get("results") or []
        if not results:
            return {"ok": False, "bars": [], "reason_code": "POLYGON_NO_RESULTS"}

        bars = []
        for b in results:
            ts = b.get("t")
            if ts is None:
                continue
            date_str = datetime.datetime.fromtimestamp(ts / 1000, UTC).date().isoformat()
            bars.append({
                "date": date_str,
                "open": b.get("o"),
                "high": b.get("h"),
                "low": b.get("l"),
                "close": b.get("c"),
                "volume": b.get("v"),
                "vwap": b.get("vw"),
            })

        if not bars:
            return {"ok": False, "bars": [], "reason_code": "POLYGON_NO_BARS_PARSED"}

        return {"ok": True, "bars": bars, "reason_code": None}

    except Exception as e:
        return {"ok": False, "bars": [], "reason_code": f"POLYGON_EXCEPTION: {e}"}
