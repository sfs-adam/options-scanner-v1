"""
yahoo_session.py — Crumb-authenticated Yahoo Finance session.

Reused from Opening Bell Scanner pattern with minor cleanup.
Research infrastructure only.
"""

import os
import re
import requests

_SESSION = None
_CRUMB = None


def get_proxies():
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    return {"https": proxy, "http": proxy} if proxy else {}


def create_session():
    """Create a crumb-authenticated Yahoo Finance session."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    proxies = get_proxies()

    # Step 1: Hit Yahoo Finance to get cookies
    r = session.get(
        "https://finance.yahoo.com",
        proxies=proxies,
        timeout=15,
    )
    r.raise_for_status()

    # Step 2: Fetch crumb
    r2 = session.get(
        "https://query2.finance.yahoo.com/v1/test/getcrumb",
        proxies=proxies,
        timeout=15,
    )
    crumb = r2.text.strip()
    if not crumb or len(crumb) > 50:
        raise RuntimeError(f"Yahoo crumb fetch failed: {crumb!r}")

    return session, crumb


def get_session():
    """Return (session, crumb), creating them if needed."""
    global _SESSION, _CRUMB
    if _SESSION is None or _CRUMB is None:
        _SESSION, _CRUMB = create_session()
    return _SESSION, _CRUMB


def reset_session():
    """Force a new session on the next call to get_session()."""
    global _SESSION, _CRUMB
    _SESSION = None
    _CRUMB = None
