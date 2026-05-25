"""Shared state for bot + web interface. Thread-safe singleton."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

STATE_DIR = Path(__file__).parent.parent / "state"
HISTORY_DIR = STATE_DIR / "history"
TRADES_FILE = STATE_DIR / "trades.json"

_lock = threading.Lock()
_bot_running = threading.Event()
_bot_paused = threading.Event()

# --- Bot lifecycle ---
_bot_thread: Optional[threading.Thread] = None
_current_symbol = "BTC/USDC:USDC"
_current_position: Optional[dict] = None
_trade_count = 0
_last_logs: list[dict] = []  # keep last 1000 log entries
_price_history: list[dict] = []  # {ts, price, fast, slow} for charts

# --- Config ---
DEFAULT_CONFIG = {
    "symbol": "BTC/USDC:USDC",
    "exchange": "hyperliquid",
    "timeframe": "1h",
    "indicator": "ema_cross",
    "fast_period": 9,
    "slow_period": 21,
    "position_size_pct": 0.10,
    "stop_loss_pct": 0.03,
    "take_profit_pct": 0.06,
}
_current_config = dict(DEFAULT_CONFIG)

AVAILABLE_SYMBOLS = [
    {"id": "BTC/USDC:USDC", "label": "BTC/USD"},
    {"id": "ETH/USDC:USDC", "label": "ETH/USD"},
    {"id": "SOL/USDC:USDC", "label": "SOL/USD"},
    {"id": "XRP/USDC:USDC", "label": "XRP/USD"},
    {"id": "DOGE/USDC:USDC", "label": "DOGE/USD"},
    {"id": "ADA/USDC:USDC", "label": "ADA/USD"},
    {"id": "AVAX/USDC:USDC", "label": "AVAX/USD"},
    {"id": "LINK/USDC:USDC", "label": "LINK/USD"},
]


def get_config() -> dict:
    with _lock:
        return dict(_current_config)


def update_config(**kwargs) -> dict:
    with _lock:
        for k, v in kwargs.items():
            if k in _current_config:
                _current_config[k] = v
        return dict(_current_config)


def get_position() -> Optional[dict]:
    with _lock:
        return _current_position.copy() if _current_position else None


def set_position(pos: Optional[dict]):
    with _lock:
        global _current_position
        _current_position = pos


def get_symbol() -> str:
    with _lock:
        return _current_symbol


def set_symbol(sym: str):
    with _lock:
        global _current_symbol
        _current_symbol = sym


def increment_trade_count():
    with _lock:
        global _trade_count
        _trade_count += 1


def get_trade_count() -> int:
    with _lock:
        return _trade_count


def is_running() -> bool:
    return _bot_running.is_set()


def set_running(val: bool):
    if val:
        _bot_running.set()
    else:
        _bot_running.clear()


def is_paused() -> bool:
    return _bot_paused.is_set()


def set_paused(val: bool):
    if val:
        _bot_paused.set()
    else:
        _bot_paused.clear()


def add_log(level: str, msg: str):
    global _last_logs
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "msg": msg,
    }
    with _lock:
        _last_logs.append(entry)
        if len(_last_logs) > 1000:
            _last_logs = _last_logs[-1000:]


def get_logs(limit: int = 100) -> list[dict]:
    with _lock:
        return list(_last_logs[-limit:])


def add_price_point(ts: str, price: float, fast: float, slow: float):
    global _price_history
    with _lock:
        _price_history.append({"ts": ts, "price": price, "fast": fast, "slow": slow})
        if len(_price_history) > 500:
            _price_history = _price_history[-500:]


def get_price_history(limit: int = 200) -> list[dict]:
    with _lock:
        return list(_price_history[-limit:])


def get_status() -> dict:
    with _lock:
        pos = _current_position.copy() if _current_position else None
        return {
            "running": _bot_running.is_set(),
            "paused": _bot_paused.is_set(),
            "symbol": _current_symbol,
            "config": dict(_current_config),
            "position": pos,
            "trade_count": _trade_count,
        }


def load_trade_history() -> list[dict]:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(HISTORY_DIR.glob("*.json"))
    trades = []
    for f in files:
        try:
            with open(f) as fh:
                trades.append(json.load(fh))
        except Exception:
            pass
    return trades


def get_summary() -> dict:
    trades = load_trade_history()
    closed = [t for t in trades if t.get("action") == "close" and t.get("pnl") is not None]
    total_trades = len(closed)
    winning = [t for t in closed if t["pnl"] > 0]
    losing = [t for t in closed if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in closed) if closed else 0
    avg_pnl = (sum(t["pnl"] for t in closed) / len(closed)) if closed else 0
    win_rate = (len(winning) / total_trades * 100) if total_trades else 0
    best_trade = max(closed, key=lambda t: t["pnl"])["pnl"] if winning else 0
    worst_trade = min(closed, key=lambda t: t["pnl"])["pnl"] if losing else 0
    return {
        "total_trades": total_trades,
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "win_rate": round(win_rate, 1),
        "total_pnl_pct": round(total_pnl * 100, 2),
        "avg_pnl_pct": round(avg_pnl * 100, 2),
        "best_trade_pct": round(best_trade * 100, 2),
        "worst_trade_pct": round(worst_trade * 100, 2),
    }
