"""Select active sources, run their scrapers, and track progress."""

import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from models.database import SessionLocal, Website
from scrapers.base_scraper import ScraperRegistry
from utils.logging_config import configure_app_logging
# Import all scrapers to ensure they are registered
import scrapers.scraper_olx
import scrapers.scraper_pracuj
import scrapers.scraper_nationwide
import scrapers.scraper_local
import scrapers.scraper_erecruiter
import scrapers.scraper_luxmed
import scrapers.scraper_medicover
import scrapers.scraper_enelmed
import scrapers.scraper_su

configure_app_logging()
logger = logging.getLogger("orchestrator")

MAX_WORKERS = 1  # Sequential processing for better stability and debugging
_scrape_status_lock = Lock()
_scrape_status = {
    "running": False,
    "current_website": None,
    "completed": 0,
    "total": 0,
    "started_at": None,
    "finished_at": None,
    "last_error": None,
}


def get_scrape_status():
    """Return a thread-safe snapshot of the current scrape status."""
    with _scrape_status_lock:
        return dict(_scrape_status)


def is_scrape_running():
    """Report whether a scrape has been queued or is still running."""
    with _scrape_status_lock:
        return bool(_scrape_status["running"])


def mark_scrape_queued():
    """Reserve the scrape slot; return false when one is already reserved."""
    with _scrape_status_lock:
        if _scrape_status["running"]:
            return False
        _scrape_status.update({
            "running": True,
            "current_website": "W kolejce...",
            "completed": 0,
            "total": 0,
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "last_error": None,
        })
        return True


def _update_scrape_status(**updates):
    """Atomically update selected fields in the shared scrape status."""
    with _scrape_status_lock:
        _scrape_status.update(updates)

def run_single_website(website_id):
    """Load one active source, resolve its scraper, and run it safely."""
    db = SessionLocal()
    try:
        website = db.query(Website).filter(Website.id == website_id).first()
        if not website or not website.active:
            return

        _update_scrape_status(current_website=website.company_name)

        # Try to find a specific scraper by company name first, then by category
        scraper_cls = ScraperRegistry.get_scraper(website.company_name) or \
                      ScraperRegistry.get_scraper(website.category)

        if not scraper_cls:
            logger.warning(f"No scraper plugin found for {website.company_name} ({website.category})")
            return

        logger.info(f"Using {scraper_cls.__name__} for {website.company_name}")
        scraper = None
        try:
            scraper = scraper_cls(db)
            scraper.run(website)
        finally:
            if scraper and hasattr(scraper, 'close'):
                scraper.close()
        
    except Exception as e:
        _update_scrape_status(last_error=str(e))
        logger.error(f"Failed to scrape {website_id}: {str(e)}")
    finally:
        db.close()
        status = get_scrape_status()
        _update_scrape_status(completed=min(status["completed"] + 1, status["total"]))

def run_all_scrapers(status_already_started=False):
    """Run every active website scraper and update overall progress."""
    if is_scrape_running() and not status_already_started:
        logger.info("Scrape request ignored because another scrape is already running.")
        return

    db = SessionLocal()
    try:
        active_websites = db.query(Website).filter(Website.active == True).all()
        website_ids = [w.id for w in active_websites]
        db.close() # Close session before starting threads

        _update_scrape_status(
            running=True,
            current_website=None,
            completed=0,
            total=len(website_ids),
            started_at=datetime.now().isoformat(),
            finished_at=None,
            last_error=None,
        )
        logger.info(f"Starting orchestration for {len(website_ids)} websites with {MAX_WORKERS} workers.")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            executor.map(run_single_website, website_ids)

        logger.info("All scrapers finished.")
    except Exception as e:
        _update_scrape_status(last_error=str(e))
        logger.error(f"Orchestration error: {e}")
    finally:
        _update_scrape_status(
            running=False,
            current_website=None,
            finished_at=datetime.now().isoformat(),
        )
        # Ensure all db connections are handled
        try:
            db.close()
        except: pass

if __name__ == "__main__":
    run_all_scrapers()
