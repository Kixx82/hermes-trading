"""
live.py — live trading adapter.
NOT imported unless HERMES_TRADING_MODE=live AND HERMES_TRADING_I_ACCEPT_RISK=true.
"""
import os
import ccxt


class LiveAdapter:
    def __init__(self):
        exchange_id = os.getenv("EXCHANGE", "binance")
        cls = getattr(ccxt, exchange_id)
        self.exchange = cls({
            "apiKey": os.getenv("EXCHANGE_API_KEY"),
            "secret": os.getenv("EXCHANGE_SECRET"),
        })

    def buy(self, asset, price, size_pct):
        raise NotImplementedError("Live adapter not implemented — use paper mode first.")

    def sell(self, asset, price):
        raise NotImplementedError("Live adapter not implemented — use paper mode first.")
