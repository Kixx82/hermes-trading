"""
main.py — Entry point for Railway.
Starts the FastAPI web server (trading bot runs in background thread).
"""
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)

from hermes_trading import app

if __name__ == "__main__":
    app.run_server()
