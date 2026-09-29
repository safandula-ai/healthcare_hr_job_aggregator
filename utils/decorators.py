"""Reusable decorators for application and scraper functions."""

import time
import functools
import logging

logger = logging.getLogger("decorators")

def retry_scraper(retries=3, delay=2, backoff=2):
    """
    Decorator to retry a function if it raises an exception.
    Useful for Selenium-based scrapers that might fail due to timeouts.
    """
    def decorator(func):
        """Wrap a scraper operation in the configured retry policy."""

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            """Retry failures with an exponentially increasing delay."""
            mtries, mdelay = retries, delay
            while mtries > 1:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"Retrying {func.__name__} in {mdelay}s... Error: {e}")
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return func(*args, **kwargs)
        return wrapper
    return decorator
