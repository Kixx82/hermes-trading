"""paper.py — paper trading stub. Always imported in paper mode."""


class PaperAdapter:
    def __init__(self):
        self.balance = 10_000.0
        self.position = None

    def buy(self, asset, price, size_pct):
        amount = self.balance * size_pct
        self.position = {"asset": asset, "entry": price, "amount": amount}
        self.balance -= amount
        return {"status": "paper_filled", "price": price, "amount": amount}

    def sell(self, asset, price):
        if not self.position:
            return {"status": "no_position"}
        pnl = (price - self.position["entry"]) / self.position["entry"]
        self.balance += self.position["amount"] * (1 + pnl)
        result = {"status": "paper_filled", "price": price, "pnl": pnl, "balance": self.balance}
        self.position = None
        return result
