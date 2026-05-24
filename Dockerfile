FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
COPY hermes_trading/ hermes_trading/

RUN uv pip install --system ccxt yfinance pyyaml httpx

COPY . .

CMD ["python", "-m", "hermes_trading.worker"]
