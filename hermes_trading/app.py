"""
app.py — FastAPI web server for trading dashboard.
Provides REST API + serves the dashboard HTML.
"""
import json
import logging
import threading
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from hermes_trading import state, worker

logger = logging.getLogger("api")
logger.setLevel(logging.INFO)

app = FastAPI(title="Hermes Trading Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_bot_thread: Optional[threading.Thread] = None


# ---- API Routes ----

@app.get("/api/status")
def get_status():
    """Full bot status."""
    s = state.get_status()
    s["summary"] = state.get_summary()
    return s


@app.get("/api/config")
def get_config():
    """Current trading config."""
    return state.get_config()


@app.post("/api/config")
def set_config(body: dict):
    """Update trading config params."""
    allowed = {"symbol", "timeframe", "fast_period", "slow_period",
               "position_size_pct", "stop_loss_pct", "take_profit_pct"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid config keys provided")
    cfg = state.update_config(**updates)
    if "symbol" in updates:
        state.set_symbol(updates["symbol"])
        state.add_log("INFO", f"Symbol changed to {updates['symbol']}")
    return cfg


@app.get("/api/markets")
def get_markets():
    """Available trading symbols."""
    return {"markets": state.AVAILABLE_SYMBOLS, "current": state.get_symbol()}


@app.post("/api/bot/start")
def start_bot():
    """Start the trading bot loop."""
    global _bot_thread
    if _bot_thread and _bot_thread.is_alive():
        return {"status": "already_running"}
    state.set_paused(False)
    _bot_thread = threading.Thread(target=worker.run_loop, daemon=True)
    _bot_thread.start()
    return {"status": "started"}


@app.post("/api/bot/stop")
def stop_bot():
    """Stop the trading bot loop."""
    if not state.is_running():
        return {"status": "not_running"}
    state.set_running(False)
    return {"status": "stopping"}


@app.post("/api/bot/pause")
def pause_bot():
    """Pause the bot (stop trading but keep alive)."""
    state.set_paused(True)
    state.add_log("INFO", "Bot paused")
    return {"status": "paused"}


@app.post("/api/bot/resume")
def resume_bot():
    """Resume the bot after pause."""
    state.set_paused(False)
    state.add_log("INFO", "Bot resumed")
    return {"status": "resumed"}


@app.get("/api/logs")
def get_logs(limit: int = 100):
    """Recent bot logs."""
    return {"logs": state.get_logs(limit)}


@app.get("/api/price-history")
def get_price_history(limit: int = 200):
    """Price + MA history for charts."""
    return {"points": state.get_price_history(limit)}


@app.get("/api/trades")
def get_trades():
    """Full trade history."""
    trades = state.load_trade_history()
    return {"trades": trades, "count": len(trades)}


@app.get("/api/summary")
def get_summary():
    """Performance summary metrics."""
    return state.get_summary()


# ---- Dashboard HTML ----

@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the dashboard UI."""
    html_path = Path(__file__).parent / "templates" / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


@app.get("/health")
def health():
    """Health check for Railway."""
    return {"status": "ok"}


def run_server(host: str = "0.0.0.0", port: int = int(os.getenv("PORT", "8000"))):
    """Start the web server."""
    logger.info("Starting web server on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")