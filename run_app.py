"""Start the local web server and open the dashboard in a browser."""

import uvicorn
import webbrowser
import logging
import os
import time
from pathlib import Path
from threading import Thread
from urllib.request import urlopen
from utils.logging_config import configure_app_logging

APP_URL = "http://127.0.0.1:8000"
BASE_DIR = Path(__file__).resolve().parent


def open_browser_when_ready():
    """Open the dashboard once the local server is accepting connections."""
    for _ in range(40):
        try:
            with urlopen(f"{APP_URL}/api/offer-filter-options", timeout=1):
                webbrowser.open_new(APP_URL)
                logging.info("Opened dashboard at %s", APP_URL)
                return
        except Exception:
            time.sleep(0.5)

    logging.error("Server did not become ready at %s", APP_URL)

if __name__ == "__main__":
    os.chdir(BASE_DIR)
    configure_app_logging()
    logging.info("Starting AP Job Aggregator from %s", BASE_DIR)

    Thread(target=open_browser_when_ready, daemon=True).start()

    try:
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=8000,
            reload=False,
            log_config=None,
        )
    except Exception:
        logging.exception("AP Job Aggregator failed to start")
        raise
