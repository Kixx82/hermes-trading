"""
worker.py — main loop. Multi-indicator strategy with RSI filter, SL/TP, funding rate.
Runs as background thread controlled via state module.
"""
import os
import time
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from hermes_trading import strategy as strat
from hermes_trading import state

logger = logging.getLogger("worker")
logger.setLevel(logging.INFO)

STATE_DIR = Path(os.getenv("STATE_DIR", "/app/state"))
HISTORY_DIR = STATE_DIR / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

MODE = os.getenv("HERMES_TRADING_MODE", "paper")
_INITIAL_EQUITY = 10000.0  # paper starting capital


def _setup_exchange() -> ccxt.Exchange:
    cls = getattr(ccxt, state.get_config()["exchange"])
    if MODE == "live" and state.is_running():
        api_key = os.getenv("EXCHANGE_API_KEY", "")
        secret = os.getenv("EXCHANGE_SECRET", "")
        if state.get_config()["exchange"] == "hyperliquid":
            return cls({"walletAddress": api_key, "privateKey": secret})
        return cls({"apiKey": api_key, "secret": secret})
    return cls()


def _record_trade(action, price, size, params, pnl=None, exit_reason=None):
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "price": price,
        "size": size,
        "pnl": pnl,
        "exit_reason": exit_reason,
        "strategy_snapshot": params,
    }
    fname = HISTORY_DIR / f"{record['ts'].replace(':', '-')}.json"
    with open(fname, "w") as f:
        json.dump(record, f, indent=2)


def run_loop():
    logger.info("Worker loop started — mode=%s", MODE)
    state.set_running(True)
    state.set_paused(False)
    state.add_log("INFO", f"Bot started — mode={MODE}")

    try:
        exchange = _setup_exchange()
        params = strat.load()
        logger.info("Strategy: %s", params)

        while state.is_running():
            try:
                cfg = state.get_config()
                symbol = cfg["symbol"]
                size_pct = cfg["position_size_pct"]

                if state.is_paused():
                    time.sleep(5)
                    continue

                # Fetch candles (need enough for RSI + longest MA)
                needed = max(cfg["slow_period"], cfg.get("rsi_period", 14)) + 10
                ohlcv = exchange.fetch_ohlcv(symbol, cfg["timeframe"], limit=needed)
                closes = [c[4] for c in ohlcv]
                price = closes[-1]
                ts = datetime.now(timezone.utc).isoformat()

                # Calculate indicators
                fast = strat.ema(closes, cfg["fast_period"])
                slow = strat.ema(closes, cfg["slow_period"])
                current_rsi = strat.rsi(closes, cfg.get("rsi_period", 14))
                state.add_price_point(ts, price, fast, slow)

                # --- Funding rate check (Hyperliquid specific) ---
                try:
                    if cfg["exchange"] == "hyperliquid":
                        ticker = exchange.fetch_funding_rate(symbol)
                        if ticker and "fundingRate" in ticker:
                            state.set_funding_rate(ticker["fundingRate"] * 100)
                except Exception:
                    pass  # non-fatal if funding rate unavailable

                position = state.get_position()

                # --- SL/TP check first ---
                if position:
                    pnl_pct = (price - position["entry"]) / position["entry"]
                    sl = cfg.get("stop_loss_pct", 0.03)
                    tp = cfg.get("take_profit_pct", 0.06)

                    if pnl_pct <= -sl:
                        _record_trade("close", price, position["size"], params, pnl=pnl_pct, exit_reason="stop_loss")
                        msg = f"STOP LOSS @ {price:.2f}  pnl={pnl_pct*100:.2f}%"
                        logger.info(msg)
                        state.add_log("SELL", msg)
                        state.set_position(None)
                        state.increment_trade_count()
                        state.add_equity_point(ts, _INITIAL_EQUITY * (1 + pnl_pct))
                        time.sleep(60)
                        continue

                    if pnl_pct >= tp:
                        _record_trade("close", price, position["size"], params, pnl=pnl_pct, exit_reason="take_profit")
                        msg = f"TAKE PROFIT @ {price:.2f}  pnl={pnl_pct*100:.2f}%"
                        logger.info(msg)
                        state.add_log("SELL", msg)
                        state.set_position(None)
                        state.increment_trade_count()
                        state.add_equity_point(ts, _INITIAL_EQUITY * (1 + pnl_pct))
                        time.sleep(60)
                        continue

                # --- Generate signal ---
                signal = strat.generate_signal(closes, cfg, position)

                if signal == "buy":
                    position = {"side": "long", "entry": price, "size": size_pct}
                    state.set_position(position)
                    _record_trade("open", price, size_pct, params)
                    rsi_info = f" rsi={current_rsi:.1f}" if cfg.get("use_rsi_filter") else ""
                    msg = f"PAPER BUY @ {price:.2f}  size={size_pct*100:.1f}%{rsi_info}"
                    logger.info(msg)
                    state.add_log("BUY", msg)
                    state.add_equity_point(ts, _INITIAL_EQUITY)

                elif signal == "sell" and position:
                    pnl = (price - position["entry"]) / position["entry"]
                    _record_trade("close", price, position["size"], params, pnl=pnl)
                    msg = f"PAPER SELL @ {price:.2f}  pnl={pnl*100:.2f}%"
                    logger.info(msg)
                    state.add_log("SELL", msg)
                    state.set_position(None)
                    state.increment_trade_count()
                    state.add_equity_point(ts, _INITIAL_EQUITY * (1 + pnl))

                else:
                    rsi_info = f" rsi={current_rsi:.1f}" if cfg.get("use_rsi_filter") else ""
                    state.add_log("INFO", f"price={price:.2f} fast={fast:.4f} slow={slow:.4f}{rsi_info} — holding")

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
