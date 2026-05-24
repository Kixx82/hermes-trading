"""
strategy.py — loaded and hot-reloaded by the worker.
Hermes writes ~/hermes-trading/state/strategy.yaml to change behaviour.
"""
import os
import yaml
from pathlib import Path

STATE_DIR = Path(os.getenv("STATE_DIR", "/app/state"))
STRATEGY_FILE = STATE_DIR / "strategy.yaml"
GOAL_FILE = STATE_DIR / "goal.yaml"

DEFAULTS = {
    "indicator": "ema_cross",
    "fast_period": 9,
    "slow_period": 21,
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
