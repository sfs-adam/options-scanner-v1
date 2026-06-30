"""
server.py — FastAPI backend for the Options Scanner v1.

Research infrastructure only — does not recommend trades as financial advice.
"""

import os
import sys
import json
import datetime
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Options Scanner v1", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
WATCHLIST_DIR = os.path.join(BASE_DIR, "watchlists")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(WATCHLIST_DIR, exist_ok=True)


# ─── Frontend ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Options Scanner — frontend not found</h1>")


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ─── Watchlists ──────────────────────────────────────────────────────────────

@app.get("/api/watchlists")
async def list_watchlists():
    if not os.path.isdir(WATCHLIST_DIR):
        return {"watchlists": []}
    files = []
    for fname in sorted(os.listdir(WATCHLIST_DIR)):
        if fname.endswith(".json"):
            fpath = os.path.join(WATCHLIST_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                files.append({
                    "filename": fname,
                    "name": data.get("name", fname),
                    "ticker_count": len(data.get("tickers", [])),
                })
            except Exception:
                files.append({"filename": fname, "name": fname, "ticker_count": 0})
    return {"watchlists": files}


@app.get("/api/watchlist/{name}")
async def get_watchlist(name: str):
    fpath = os.path.join(WATCHLIST_DIR, f"{name}.json")
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail=f"Watchlist '{name}' not found")
    with open(fpath, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/watchlist/{name}")
async def save_watchlist(name: str, request: Request):
    body = await request.json()
    fpath = os.path.join(WATCHLIST_DIR, f"{name}.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2)
    return {"status": "saved", "filename": f"{name}.json"}


# ─── Scan ────────────────────────────────────────────────────────────────────

@app.post("/api/scan")
async def run_scan(request: Request):
    """
    Body: {"tickers": [{"symbol": "AAPL", "is_etf": false, "name": "Apple"}], "delay": 2}
    """
    try:
        body = await request.json()
        tickers = body.get("tickers", [])
        delay = float(body.get("delay", 13))

        if not tickers:
            raise HTTPException(status_code=400, detail="No tickers provided")

        from scanner.scan_engine import scan_batch
        results = scan_batch(tickers, delay=delay)

        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(OUTPUT_DIR, f"scan_{ts}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)

        results["output_file"] = f"scan_{ts}.json"
        return results

    except HTTPException:
        raise
    except Exception as exc:
        tb = traceback.format_exc()
        print("\n=== /api/scan ERROR ===", file=sys.stderr)
        print(tb, file=sys.stderr)
        return JSONResponse(
            status_code=500,
            content={"error": "scan_failed", "detail": f"{type(exc).__name__}: {exc}"},
        )


# ─── Shutdown ────────────────────────────────────────────────────────────────

@app.post("/api/shutdown")
async def shutdown():
    """Graceful shutdown triggered from the UI."""
    import threading
    def _stop():
        import time
        time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=_stop, daemon=True).start()
    return {"status": "shutting_down"}


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    import socket

    port = int(os.environ.get("PORT", 8001))

    def port_in_use(p):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", p)) == 0

    if port_in_use(port):
        print(f"[options-scanner] Server already running on port {port}. Reusing.", flush=True)
        sys.exit(0)

    print(f"[options-scanner] Starting on http://localhost:{port}", flush=True)
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
