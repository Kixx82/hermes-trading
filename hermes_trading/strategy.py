"""
strategy.py — loaded and hot-reloaded by the worker.
Supports EMA cross, RSI filter, and combined signals.
"""
import os
import math
import yaml
from pathlib import Path

STATE_DIR = Path(os.getenv("STATE_DIR", "/app/state"))
STRATEGY_FILE = STATE_DIR / "strategy.yaml"
GOAL_FILE = STATE_DIR / "goal.yaml"

DEFAULTS = {
    "indicator": "ema_cross",
    "fast_period": 9,
    "slow_period": 21,
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "use_rsi_filter": False,
    "position_size_pct": 0.10,
    "stop_loss_pct": 0.03,
    "take_profit_pct": 0.06,
}


def load() -> dict:
    if STRATEGY_FILE.exists():
        with open(STRATEGY_FILE) as f:
            data = yaml.safe_load(f) or {}
        return {**DEFAULTS, **data}
    return DEFAULTS.copy()


def load_goal() -> dict:
    if GOAL_FILE.exists():
        with open(GOAL_FILE) as f:
            return yaml.safe_load(f) or {}
    return {}


# ---- Indicator calculations ----

def ema(prices: list[float], period: int) -> float:
    k = 2 / (period + 1)
    val = prices[0]
    for p in prices[1:]:
        val = p * k + val * (1 - k)
    return val


def rsi(prices: list[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0  # neutral
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def generate_signal(closes: list[float], cfg: dict, position: dict | None) -> str | None:
    """Return 'buy', 'sell', or None based on configured strategy."""
    fast_p = cfg["fast_period"]
    slow_p = cfg["slow_period"]
    rsi_p = cfg.get("rsi_period", 14)
    use_rsi = cfg.get("use_rsi_filter", False)
    rsi_ob = cfg.get("rsi_overbought", 70)
    rsi_os = cfg.get("rsi_oversold", 30)

    fast = ema(closes, fast_p)
    slow = ema(closes, slow_p)
    current_rsi = rsi(closes, rsi_p) if use_rsi else None

    result = {"fast": fast, "slow": slow, "rsi": current_rsi}

    # Buy signal: fast > slow, and (if RSI filter on) RSI not overbought
    if fast > slow and position is None:
        if use_rsi and current_rsi is not None and current_rsi >= rsi_ob:
            return None  # RSI overbought, skip buy
        result["signal"] = "buy"
        return "buy"

    # Sell signal: fast < slow and we have a position
    if fast < slow and position is not None:
        result["signal"] = "sell"
        return "sell"

    return None


def check_sl_tp(current_price: float, position: dict, cfg: dict) -> str | None:
    """Check if stop loss or take profit is hit. Returns 'stop_loss', 'take_profit', or None."""
    if position is None:
        return None
    entry = position["entry"]
    sl_pct = cfg.get("stop_loss_pct", 0.03)
    tp_pct = cfg.get("take_profit_pct", 0.06)
    pnl_pct = (current_price - entry) / entry
    if pnl_pct <= -sl_pct:
        return "stop_loss"
    if pnl_pct >= tp_pct:
        return "take_profit"
    return None
