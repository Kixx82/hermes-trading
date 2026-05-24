"""
worker.py — main loop. Fetches candles, applies strategy, fires paper trades.
Hermes watches trade history and rewrites state/strategy.yaml.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

STATE_DIR = Path(os.getenv("STATE_DIR", "/app/state"))
HISTORY_DIR = STATE_DIR / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

MODE = os.getenv("HERMES_TRADING_MODE", "paper")
ACCEPT_RISK = os.getenv("HERMES_TRADING_I_ACCEPT_RISK", "false").lower() == "true"

EXCHANGE_ID = os.getenv("EXCHANGE", "binance").lower().strip()
# Hyperliquid perps: BTC/USDC:USDC
ASSET = "BTC/USDC:USDC" if EXCHANGE_ID == "hyperliquid" else "BTC/USDT"


def get_exchange():
    cls = getattr(ccxt, EXCHANGE_ID)
    if MODE == "live" and ACCEPT_RISK:
        api_key = os.getenv("EXCHANGE_API_KEY", "")
        secret = os.getenv("EXCHANGE_SECRET", "")
        # Hyperliquid uses walletAddress + privateKey instead of apiKey/secret
        if EXCHANGE_ID == "hyperliquid":
            return cls({"walletAddress": api_key, "privateKey": secret})
        return cls({"apiKey": api_key, "secret": secret})
    # Paper mode — public endpoints only, no auth needed
    return cls()


def ema(prices: list[float], period: int) -> float:
    k = 2 / (period + 1)
    val = prices[0]
    for p in prices[1:]:
        val = p * k + val * (1 - k)
    return val


def run():
    log.info("Worker started — mode=%s asset=%s", MODE, ASSET)
    exchange = get_exchange()
    params = strat.load()
    goal = strat.load_goal()
    log.info("Strategy loaded: %s", params)
    log.info("Goal: %s", goal)

    trade_count = 0
    position = None  # {"side": "long", "entry": float, "size": float}

    while True:
        try:
            params = strat.load()  # hot-reload on every cycle
            ohlcv = exchange.fetch_ohlcv(ASSET, "1h", limit=max(params["fast_period"], params["slow_period"]) + 5)
            closes = [c[4] for c in ohlcv]
            fast = ema(closes, params["fast_period"])
            slow = ema(closes, params["slow_period"])
            price = closes[-1]

            signal = None
            if fast > slow and position is None:
                signal = "buy"
            elif fast < slow and position is not None:
                signal = "sell"

            if signal == "buy":
                size = params["position_size_pct"]
                position = {"side": "long", "entry": price, "size": size}
                _record_trade("open", price, size, params, goal)
                log.info("PAPER BUY @ %.2f  size=%.2f%%", price, size * 100)

            elif signal == "sell" and position:
                pnl = (price - position["entry"]) / position["entry"]
                _record_trade("close", price, position["size"], params, goal, pnl=pnl)
                log.info("PAPER SELL @ %.2f  pnl=%.2f%%", price, pnl * 100)
                position = None
                trade_count += 1
                log.info("Closed trade #%d", trade_count)

            else:
                log.info("price=%.2f fast=%.4f slow=%.4f — holding", price, fast, slow)

        except Exception as e:
            log.error("Loop error: %s", e)

        time.sleep(60)


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


if __name__ == "__main__":
    run()
