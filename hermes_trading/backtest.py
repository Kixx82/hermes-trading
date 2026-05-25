"""
backtest.py — Run historical data through a strategy and get performance metrics.
"""
import json
import math
from datetime import datetime, timezone

import ccxt

from hermes_trading import strategy as strat, state


def run(exchange_id: str, symbol: str, timeframe: str, cfg: dict,
        start_date: str = None, end_date: str = None) -> dict:
    """Backtest a strategy over historical data.

    Args:
        exchange_id: e.g. 'hyperliquid', 'binance'
        symbol: e.g. 'BTC/USDC:USDC'
        timeframe: e.g. '1h', '4h'
        cfg: strategy config dict (fast_period, slow_period, etc.)
        start_date: ISO date string, e.g. '2026-01-01'
        end_date: ISO date string, e.g. '2026-05-25'

    Returns:
        dict with metrics and equity curve
    """
    try:
        cls = getattr(ccxt, exchange_id)
        exchange = cls()
        since = None
        if start_date:
            from datetime import datetime as dt
            since = int(dt.fromisoformat(start_date).timestamp() * 1000)

        state.add_log("INFO", f"Backtest started: {symbol} {timeframe}")

        # Fetch all historical candles
        all_ohlcv = []
        while True:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=500)
            if not ohlcv:
                break
            all_ohlcv.extend(ohlcv)
            since = ohlcv[-1][0] + 1
            if end_date:
                end_ts = int(datetime.fromisoformat(end_date).timestamp() * 1000)
                if ohlcv[-1][0] >= end_ts:
                    break

        if len(all_ohlcv) < cfg["slow_period"] + 5:
            return {"error": f"Not enough data ({len(all_ohlcv)} candles, need {cfg['slow_period'] + 5})"}

        closes = [c[4] for c in all_ohlcv]
        timestamps = [c[0] for c in all_ohlcv]

        # Run strategy
        position = None
        trades = []
        equity = [10000.0]
        timestamps_eq = [timestamps[0]]
        max_equity = 10000.0

        for i in range(max(cfg["slow_period"], cfg.get("rsi_period", 14)), len(closes)):
            window = closes[:i+1]
            price = closes[i]
            ts = timestamps[i]

            # SL/TP check
            if position:
                pnl_pct = (price - position["entry"]) / position["entry"]
                sl = cfg.get("stop_loss_pct", 0.03)
                tp = cfg.get("take_profit_pct", 0.06)
                if pnl_pct <= -sl:
                    trades.append({
                        "ts": datetime.fromtimestamp(ts/1000, tz=timezone.utc).isoformat(),
                        "action": "close", "price": price,
                        "pnl": pnl_pct, "exit_reason": "stop_loss"
                    })
                    equity.append(equity[-1] * (1 + pnl_pct))
                    timestamps_eq.append(ts)
                    position = None
                    continue
                if pnl_pct >= tp:
                    trades.append({
                        "ts": datetime.fromtimestamp(ts/1000, tz=timezone.utc).isoformat(),
                        "action": "close", "price": price,
                        "pnl": pnl_pct, "exit_reason": "take_profit"
                    })
                    equity.append(equity[-1] * (1 + pnl_pct))
                    timestamps_eq.append(ts)
                    position = None
                    continue

            # Signal
            signal = strat.generate_signal(window, cfg, position)
            if signal == "buy" and position is None:
                position = {"entry": price, "size": cfg["position_size_pct"]}
                trades.append({
                    "ts": datetime.fromtimestamp(ts/1000, tz=timezone.utc).isoformat(),
                    "action": "open", "price": price, "size": cfg["position_size_pct"]
                })
            elif signal == "sell" and position:
                pnl = (price - position["entry"]) / position["entry"]
                trades.append({
                    "ts": datetime.fromtimestamp(ts/1000, tz=timezone.utc).isoformat(),
                    "action": "close", "price": price, "pnl": pnl
                })
                equity.append(equity[-1] * (1 + pnl))
                timestamps_eq.append(ts)
                position = None

        # Close any open position at last price
        if position:
            pnl = (closes[-1] - position["entry"]) / position["entry"]
            trades.append({
                "ts": datetime.fromtimestamp(timestamps[-1]/1000, tz=timezone.utc).isoformat(),
                "action": "close", "price": closes[-1], "pnl": pnl
            })
            equity.append(equity[-1] * (1 + pnl))
            timestamps_eq.append(timestamps[-1])

        # Calculate metrics
        closed_trades = [t for t in trades if t.get("action") == "close" and t.get("pnl") is not None]
        total = len(closed_trades)
        if total == 0:
            result = {
                "total_trades": 0, "win_rate": 0, "total_return": 0,
                "max_drawdown": 0, "sharpe": 0, "trades": trades,
                "equity_curve": [{"ts": str(timestamps_eq[i]), "equity": round(e, 2)}
                                 for i, e in enumerate(equity)],
                "error": "No closed trades"
            }
            state.set_backtest_result(result)
            state.add_log("INFO", "Backtest complete: 0 trades")
            return result

        winning = [t for t in closed_trades if t["pnl"] > 0]
        losing = [t for t in closed_trades if t["pnl"] <= 0]
        win_rate = len(winning) / total * 100
        total_return = (equity[-1] - 10000) / 10000 * 100

        # Max drawdown
        peak = equity[0]
        max_dd = 0
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio (using trade returns as sample)
        returns = [t["pnl"] for t in closed_trades]
        avg_ret = sum(returns) / len(returns) if returns else 0
        std_ret = math.sqrt(sum((r - avg_ret)**2 for r in returns) / len(returns)) if len(returns) > 1 else 0
        sharpe = (avg_ret / std_ret * math.sqrt(365)) if std_ret > 0 else 0

        # Avg win / avg loss
        avg_win = (sum(t["pnl"] for t in winning) / len(winning) * 100) if winning else 0
        avg_loss = (sum(t["pnl"] for t in losing) / len(losing) * 100) if losing else 0

        result = {
            "total_trades": total,
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(win_rate, 1),
            "total_return": round(total_return, 2),
            "max_drawdown": round(max_dd, 2),
            "sharpe": round(sharpe, 2),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "profit_factor": round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else float('inf'),
            "trades": trades,
            "equity_curve": [{"ts": str(timestamps_eq[i]), "equity": round(e, 2)}
                             for i, e in enumerate(equity)],
        }

        state.set_backtest_result(result)
        state.add_log("INFO", f"Backtest complete: {total} trades, return={total_return:.1f}%, Sharpe={sharpe:.2f}")
        return result

    except Exception as e:
        state.add_log("ERROR", f"Backtest failed: {e}")
        return {"error": str(e)}
