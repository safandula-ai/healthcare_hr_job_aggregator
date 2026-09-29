"""Configure rotating logs for the app and its scrapers."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import settings


def configure_app_logging() -> Path:
    """Configure process-wide logging to files under the application logs directory."""
    logs_dir = Path(settings.BASE_DIR) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    level_name = str(getattr(settings, "LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    app_log_path = logs_dir / "app.log"
    scraper_log_path = logs_dir / "scrapers.log"

    _ensure_handler(root, app_log_path, formatter, level, "apjobs_app_file")

    for logger_name in [
        "orchestrator",
        "base_scraper",
        "scraper_enelmed",
        "scraper_erecruiter",
        "scraper_local",
        "scraper_luxmed",
        "scraper_medicover",
        "scraper_nationwide",
        "scraper_olx",
        "scraper_pracuj",
        "scraper_su",
    ]:
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        logger.propagate = True
        _ensure_handler(logger, scraper_log_path, formatter, level, "apjobs_scraper_file")

    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    return logs_dir


def _ensure_handler(logger: logging.Logger, path: Path, formatter: logging.Formatter, level: int, marker: str) -> None:
    """Add one rotating file handler unless this logger already has it."""
    for handler in logger.handlers:
        if getattr(handler, "_apjobs_marker", None) == marker and getattr(handler, "baseFilename", None) == str(path):
            return

    handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(formatter)
    handler._apjobs_marker = marker
    logger.addHandler(handler)
