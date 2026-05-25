"""
app.py — FastAPI web server for trading dashboard.
REST API: status, config, bot control, backtest, equity curve, funding rate.
"""
import json
import logging
import threading
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from hermes_trading import state, worker, backtest

logger = logging.getLogger("api")
logger.setLevel(logging.INFO)

API_KEY = os.getenv("DASHBOARD_API_KEY", "")

app = FastAPI(title="Hermes Trading Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_bot_thread: Optional[threading.Thread] = None


# ---- Simple API key auth (optional) ----
def verify_auth(authorization: Optional[str] = Header(None)):
    if not API_KEY:
        return True  # no key configured = open
    if authorization and authorization.startswith("Bearer ") and authorization[7:] == API_KEY:
        return True
    raise HTTPException(401, "Unauthorized — provide X-API-Key or Bearer token")


# ---- API Routes ----

@app.get("/api/status")
def get_status(_=Depends(verify_auth)):
    s = state.get_status()
    s["summary"] = state.get_summary()
    s["funding_rate"] = state.get_funding_rate()
    return s


@app.get("/api/config")
def get_config(_=Depends(verify_auth)):
    return state.get_config()


@app.post("/api/config")
def set_config(body: dict, _=Depends(verify_auth)):
    allowed = {"symbol", "timeframe", "fast_period", "slow_period",
               "rsi_period", "rsi_overbought", "rsi_oversold", "use_rsi_filter",
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
def get_markets(_=Depends(verify_auth)):
    return {"markets": state.AVAILABLE_SYMBOLS, "current": state.get_symbol()}


@app.post("/api/bot/start")
def start_bot(_=Depends(verify_auth)):
    global _bot_thread
    if _bot_thread and _bot_thread.is_alive():
        return {"status": "already_running"}
    state.set_paused(False)
    _bot_thread = threading.Thread(target=worker.run_loop, daemon=True)
    _bot_thread.start()
    return {"status": "started"}


@app.post("/api/bot/stop")
def stop_bot(_=Depends(verify_auth)):
    if not state.is_running():
        return {"status": "not_running"}
    state.set_running(False)
    return {"status": "stopping"}


@app.post("/api/bot/pause")
def pause_bot(_=Depends(verify_auth)):
    state.set_paused(True)
    state.add_log("INFO", "Bot paused")
    return {"status": "paused"}


@app.post("/api/bot/resume")
def resume_bot(_=Depends(verify_auth)):
    state.set_paused(False)
    state.add_log("INFO", "Bot resumed")
    return {"status": "resumed"}


@app.get("/api/logs")
def get_logs(limit: int = 100, _=Depends(verify_auth)):
    return {"logs": state.get_logs(limit)}


@app.get("/api/price-history")
def get_price_history(limit: int = 200, _=Depends(verify_auth)):
    return {"points": state.get_price_history(limit)}


@app.get("/api/equity-curve")
def get_equity_curve(limit: int = 500, _=Depends(verify_auth)):
    return {"points": state.get_equity_curve(limit)}


@app.get("/api/funding-rate")
def get_funding_rate(_=Depends(verify_auth)):
    return {"rate": state.get_funding_rate()}


@app.get("/api/trades")
def get_trades(_=Depends(verify_auth)):
    trades = state.load_trade_history()
    return {"trades": trades, "count": len(trades)}


@app.get("/api/summary")
def get_summary(_=Depends(verify_auth)):
    return state.get_summary()


@app.get("/api/backtest/result")
def get_backtest_result(_=Depends(verify_auth)):
    result = state.get_backtest_result()
    if result is None:
        return {"status": "no_result"}
    return result


@app.post("/api/backtest/run")
def run_backtest(body: dict, _=Depends(verify_auth)):
    """Run a backtest with given config over historical data."""
    cfg = {**state.get_config()}
    for k in ("symbol", "timeframe", "fast_period", "slow_period",
              "rsi_period", "rsi_overbought", "rsi_oversold", "use_rsi_filter",
              "position_size_pct", "stop_loss_pct", "take_profit_pct"):
        if k in body:
            cfg[k] = body[k]

    symbol = cfg["symbol"]
    timeframe = body.get("timeframe", cfg["timeframe"])
    start = body.get("start_date", "2026-01-01")
    end = body.get("end_date", "2026-05-25")

    # Run in background thread so it doesn't block
    def _run():
        result = backtest.run(
            exchange_id=cfg["exchange"],
            symbol=symbol,
            timeframe=timeframe,
            cfg=cfg,
            start_date=start,
            end_date=end,
        )
        state.set_backtest_result(result)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"status": "running", "message": f"Backtesting {symbol} {timeframe} from {start} to {end}"}


# ---- Dashboard HTML ----

@app.get("/", response_class=HTMLResponse)
def dashboard(_=Depends(verify_auth)):
    html_path = Path(__file__).parent / "templates" / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


@app.get("/health")
def health():
    return {"status": "ok"}


def run_server(host: str = "0.0.0.0", port: int = int(os.getenv("PORT", "8000"))):
    logger.info("Starting web server on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")