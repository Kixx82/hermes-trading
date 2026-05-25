"""
worker.py — main loop. Fetches candles, applies strategy, fires paper trades.
Runs as background thread controlled via state module.
"""
import os
import time
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import yaml

from hermes_trading import strategy as strat
from hermes_trading import state

logger = logging.getLogger("worker")
logger.setLevel(logging.INFO)

STATE_DIR = Path(os.getenv("STATE_DIR", "/app/state"))
HISTORY_DIR = STATE_DIR / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

MODE = os.getenv("HERMES_TRADING_MODE", "paper")


def _setup_exchange() -> ccxt.Exchange:
    """Create exchange instance. In paper mode, no auth needed."""
    cls = getattr(ccxt, state.get_config()["exchange"])
    if MODE == "live" and state.is_running():
        api_key = os.getenv("EXCHANGE_API_KEY", "")
        secret = os.getenv("EXCHANGE_SECRET", "")
        if state.get_config()["exchange"] == "hyperliquid":
            return cls({"walletAddress": api_key, "privateKey": secret})
        return cls({"apiKey": api_key, "secret": secret})
    return cls()


def _ema(prices: list[float], period: int) -> float:
    k = 2 / (period + 1)
    val = prices[0]
    for p in prices[1:]:
        val = p * k + val * (1 - k)
    return val


def _record_trade(action, price, size, params, goal, pnl=None):
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "price": price,
        "size": size,
        "pnl": pnl,
        "strategy_snapshot": params,
        "goal_snapshot": goal,
    }
    fname = HISTORY_DIR / f"{record['ts'].replace(':', '-')}.json"
    with open(fname, "w") as f:
        json.dump(record, f, indent=2)


def run_loop():
    """Main trading loop — runs in a background thread."""
    logger.info("Worker loop started — mode=%s", MODE)
    state.set_running(True)
    state.set_paused(False)
    state.add_log("INFO", f"Bot started — mode={MODE}")

    try:
        exchange = _setup_exchange()
        params = strat.load()
        goal = strat.load_goal()
        logger.info("Strategy: %s", params)
        logger.info("Goal: %s", goal)

        while state.is_running():
            try:
                # Reload config every cycle (hot-reload)
                cfg = state.get_config()
                symbol = cfg["symbol"]
                fast_p = cfg["fast_period"]
                slow_p = cfg["slow_period"]
                size_pct = cfg["position_size_pct"]
                period_max = max(fast_p, slow_p)

                # Check if paused
                if state.is_paused():
                    time.sleep(5)
                    continue

                # Fetch candles
                ohlcv = exchange.fetch_ohlcv(symbol, cfg["timeframe"], limit=period_max + 5)
                closes = [c[4] for c in ohlcv]
                fast = _ema(closes, fast_p)
                slow = _ema(closes, slow_p)
                price = closes[-1]
                ts = datetime.now(timezone.utc).isoformat()

                # Store for dashboard
                state.add_price_point(ts, price, fast, slow)

                # Generate signal
                position = state.get_position()
                signal = None
                if fast > slow and position is None:
                    signal = "buy"
                elif fast < slow and position is not None:
                    signal = "sell"

                if signal == "buy":
                    size = size_pct
                    state.set_position({"side": "long", "entry": price, "size": size})
                    _record_trade("open", price, size, params, goal)
                    msg = f"PAPER BUY @ {price:.2f}  size={size*100:.1f}%"
                    logger.info(msg)
                    state.add_log("BUY", msg)

                elif signal == "sell" and position:
                    pnl = (price - position["entry"]) / position["entry"]
                    _record_trade("close", price, position["size"], params, goal, pnl=pnl)
                    msg = f"PAPER SELL @ {price:.2f}  pnl={pnl*100:.2f}%"
                    logger.info(msg)
                    state.add_log("SELL", msg)
                    state.set_position(None)
                    state.increment_trade_count()

                else:
                    state.add_log("INFO", f"price={price:.2f} fast={fast:.4f} slow={slow:.4f} — holding")

            except Exception as e:
                logger.error("Loop error: %s", e)
                state.add_log("ERROR", str(e))

            time.sleep(60)

    except Exception as e:
        logger.error("Fatal error: %s", e)
        state.add_log("ERROR", f"Fatal: {e}")
    finally:
        state.set_running(False)
        state.add_log("INFO", "Bot stopped")
        logger.info("Worker loop stopped")