FROM python:3.11-slim

WORKDIR /app

RUN pip install uv --quiet

COPY pyproject.toml .
COPY hermes_trading/ hermes_trading/
COPY main.py .

RUN uv pip install --system ccxt yfinance pyyaml httpx fastapi uvicorn --quiet

EXPOSE 8000

CMD ["python", "main.py"]
