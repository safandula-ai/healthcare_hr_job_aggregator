"""Scraper registry and shared Selenium, page, and cleanup helpers."""

import logging
import os
import time
import random
import uuid
import re
import shutil
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from dotenv import load_dotenv
from config.settings import settings

load_dotenv()

logger = logging.getLogger("base_scraper")

class ScraperRegistry:
    """Map source names and categories to scraper implementation classes."""

    _scrapers = {}

    @classmethod
    def register_scraper(cls, name, scraper_class):
        """Register a scraper class under a lowercase lookup key."""
        cls._scrapers[name.lower()] = scraper_class

    @classmethod
    def register(cls, name):
        """Return a class decorator that registers a scraper for ``name``."""
        def decorator(scraper_class):
            """Register and return one scraper implementation class."""
            cls.register_scraper(name, scraper_class)
            return scraper_class
        return decorator

    @classmethod
    def get_scraper(cls, name):
        """Return the scraper registered for ``name``, or ``None``."""
        return cls._scrapers.get(name.lower())

class BaseScraper:
    """Shared Selenium lifecycle and parsing helpers for site scrapers."""

    _stale_profiles_cleaned = False
    PROFILE_MAX_AGE_SECONDS = 6 * 60 * 60

    def __init__(self, db_session):
        """Create a scraper bound to a SQLAlchemy session."""
        self.db = db_session
        self._driver = None
        self._wait = None
        self._profile_path = None
        self._cleanup_stale_profiles_once()

    @classmethod
    def _profiles_dir(cls):
        """Return the directory where temporary Chrome profiles are stored."""
        return os.path.abspath(os.path.join("logs", "profiles"))

    @classmethod
    def _cleanup_stale_profiles_once(cls):
        """Run stale-profile cleanup at most once per process."""
        if cls._stale_profiles_cleaned:
            return
        cls._stale_profiles_cleaned = True
        cls._cleanup_stale_profiles()

    @classmethod
    def _cleanup_stale_profiles(cls):
        """Remove scraper-owned browser profiles older than the retention limit."""
        profiles_dir = cls._profiles_dir()
        if not os.path.isdir(profiles_dir):
            return

        cutoff = time.time() - cls.PROFILE_MAX_AGE_SECONDS
        for entry in os.scandir(profiles_dir):
            if not entry.is_dir():
                continue
            if not (entry.name.startswith("chrome_profile_") or entry.name.startswith("profile_")):
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry.path, ignore_errors=True)
                    logger.info(f"Removed stale Chrome profile: {entry.path}")
            except Exception as e:
                logger.debug(f"Could not remove stale Chrome profile {entry.path}: {e}")

    @property
    def driver(self):
        """Lazily create and return this scraper's Chrome WebDriver."""
        if self._driver is None:
            self._driver = self._initialize_driver()
        return self._driver

    @property
    def wait(self):
        """Return a Selenium wait object bound to the current driver."""
        if self._wait is None:
            self._wait = WebDriverWait(self.driver, 15)
        return self._wait

    def _initialize_driver(self):
        """Configure and start Chrome using the application's Selenium settings."""
        options = Options()
        
        # Headless mode control
        if settings.SELENIUM_HEADLESS:
            options.add_argument("--headless=new")
            logger.info("Running Chrome in headless mode.")
        else:
            logger.info("Running Chrome in headful mode.")

        chrome_binary_path = settings.CHROME_BINARY_PATH.strip()
        if chrome_binary_path:
            if not os.path.isfile(chrome_binary_path):
                raise FileNotFoundError(f"Chrome executable not found: {chrome_binary_path}")
            options.binary_location = chrome_binary_path

        # Common arguments for stability and stealth
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled") # Stealth
        options.add_experimental_option("excludeSwitches", ["enable-automation"]) # Stealth
        options.add_experimental_option("useAutomationExtension", False) # Stealth
        
        # User-Agent rotation (simple example, more complex rotation needed for production)
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:107.0) Gecko/20100101 Firefox/107.0"
        ]
        options.add_argument(f"user-agent={random.choice(user_agents)}")
        options.add_argument("--remote-allow-origins=*")

        instance_id = uuid.uuid4().hex[:8]
        profile_path = os.path.join(self._profiles_dir(), f"chrome_profile_{os.getpid()}_{instance_id}")
        self._profile_path = profile_path
        os.makedirs(profile_path, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_path}")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        logger.info("BaseScraper: WebDriver initialized.")
        return driver

    def accept_cookies(self):
        """Attempts to dismiss a common cookie banner using JavaScript click."""
        cookie_selectors = [
            'button[data-test="button-submitCookie"]', # Pracuj.pl
            'button#onetrust-accept-btn-handler', # OneTrust (common)
            'button.cmp-button_button--accept-all', # Another common one
            'button.accept-all-cookies',
            'a.accept-cookies-button',
            'div.coi-banner__accept', # Cookiebot (Enel-Med uses this)
            'button.cmpboxbtnyes',
            'button.cmpboxbtnaccept',
            'a.cmpboxbtnyes',
            'a.cmpboxbtnaccept',
            '.cmpboxbtnyes',
            '.cmpboxbtnaccept'
        ]
        
        for selector in cookie_selectors:
            try:
                # Use JavaScript click to bypass "Element Click Intercepted" errors
                # Check if the element exists before trying to click
                if self.driver.execute_script(f"return document.querySelector('{selector}')"):
                    self.driver.execute_script(f"document.querySelector('{selector}').click();")
                    logger.info(f"Attempted to dismiss cookie banner with selector: {selector}")
                    time.sleep(random.uniform(1, 2)) # Give it time to disappear
                    return True
            except Exception as js_e:
                logger.debug(f"Could not click cookie banner with selector {selector}: {js_e}")

        try:
            shadow_click_result = self.driver.execute_script(
                """
                const selectors = arguments[0];
                const roots = [document];
                document.querySelectorAll('*').forEach((el) => {
                    if (el.shadowRoot) roots.push(el.shadowRoot);
                });
                for (const root of roots) {
                    for (const selector of selectors) {
                        const el = root.querySelector(selector);
                        if (el) {
                            el.click();
                            document.body.style.overflow = 'auto';
                            return selector;
                        }
                    }
                }
                return null;
                """,
                cookie_selectors
            )
            if shadow_click_result:
                logger.info(f"Attempted to dismiss cookie banner inside shadow DOM with selector: {shadow_click_result}")
                time.sleep(random.uniform(1, 2))
                return True
        except Exception as shadow_e:
            logger.debug(f"Could not click cookie banner inside shadow DOM: {shadow_e}")

        logger.info("No known cookie banner dismissed or already gone.")
        return False

    def save_failure_artifact(self, name):
        """Saves a screenshot and page source on failure."""
        screenshot_dir = os.path.join("logs", "screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        screenshot_path = os.path.join(screenshot_dir, f"{name}_{timestamp}.png")
        page_source_path = os.path.join(screenshot_dir, f"{name}_{timestamp}.html")

        try:
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Screenshot saved: {screenshot_path}")
        except Exception as e:
            logger.error(f"Failed to save screenshot: {e}")

        try:
            with open(page_source_path, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logger.info(f"Page source saved: {page_source_path}")
        except Exception as e:
            logger.error(f"Failed to save page source: {e}")

    def close(self):
        """Closes the WebDriver."""
        if self._driver:
            try:
                self._driver.quit()
                logger.info("WebDriver closed.")
            except Exception as e:
                logger.debug(f"Error while closing driver: {e}")
            finally:
                self._driver = None
                self._wait = None

        if self._profile_path:
            try:
                time.sleep(0.5)
                shutil.rmtree(self._profile_path, ignore_errors=True)
                logger.info(f"Removed Chrome profile: {self._profile_path}")
            except Exception as e:
                logger.debug(f"Could not remove Chrome profile {self._profile_path}: {e}")
            finally:
                self._profile_path = None

    def find_element_safe(self, by, value, timeout=10):
        """Safely finds an element, returning None if not found after timeout."""
        try:
            return self.wait.until(EC.presence_of_element_located((by, value)))
        except:
            return None

    def find_elements_safe(self, by, value, timeout=10):
        """Safely finds elements, returning empty list if none found after timeout."""
        try:
            return self.wait.until(EC.presence_of_all_elements_located((by, value)))
        except:
            return []

    def extract_text(self, parent_element, selector, default="N/A"):
        """Helper to safely extract text from a child element."""
        try:
            element = parent_element.find_element(By.CSS_SELECTOR, selector)
            return element.text.strip()
        except Exception:
            return default

    def normalize_offer_info(self, text, title=None, limit=4000):
        """Prepare compact offer text for storage and UI display."""
        if not text:
            return None
        cleaned = re.sub(r"\s+", " ", text).strip()
        if title and cleaned == title:
            return None
        return cleaned[:limit]

    def extract_offer_info(self, source, title=None, limit=4000):
        """Extract offer text from Selenium elements or BeautifulSoup nodes."""
        try:
            text = source.text
        except Exception:
            try:
                text = source.get_text(" ", strip=True)
            except Exception:
                text = ""
        return self.normalize_offer_info(text, title=title, limit=limit)

    def clean_company_name(self, company, website_record=None, offer_text=None, url=None):
        """Return a useful company name when the listing omits it."""
        company = self.normalize_offer_info(company, limit=200)
        if company and company.upper() not in {"N/A", "BRAK", "UNKNOWN"}:
            return company

        text = self._plain_text(offer_text)
        known_companies = [
            "Synevo", "Scanmed", "Diagnostyka", "LUX MED", "Medicover", "Enel-Med",
            "ALAB laboratoria", "Affidea", "Szpital Uniwersytecki"
        ]
        normalized_text = self._normalize_ascii(text)
        for known in known_companies:
            if self._normalize_ascii(known) in normalized_text:
                return known

        if website_record and getattr(website_record, "company_name", None):
            return website_record.company_name

        if url:
            host = urlparse(url).netloc.replace("www.", "")
            if host:
                return host.split(".")[0].replace("-", " ").title()

        return "N/A"

    def clean_location(self, location, website_record=None, offer_text=None, fallback=None):
        """Return a useful location when the listing omits it."""
        location = self.normalize_offer_info(location, limit=200)
        if location and location.upper() not in {"N/A", "BRAK", "UNKNOWN", "NONE"}:
            return location

        text = self._plain_text(offer_text)
        if hasattr(self, "location_filter"):
            extracted = self.location_filter.extract_known_city(text)
            if extracted:
                return extracted

        if website_record and getattr(website_record, "location", None):
            return website_record.location

        return fallback or "Kraków"

    def build_match_text(self, title=None, company=None, location=None, offer_info=None):
        """Combine offer fields into the text consumed by the profile matcher."""
        return " ".join(part for part in [title, company, location, offer_info] if part)

    def _plain_text(self, value):
        """Strip markup and normalize whitespace in scraped text."""
        if not value:
            return ""
        if isinstance(value, str):
            return value
        try:
            return value.text
        except Exception:
            try:
                return value.get_text(" ", strip=True)
            except Exception:
                return str(value)

    def _normalize_ascii(self, value):
        """Normalize text to lowercase ASCII for robust source matching."""
        import unicodedata
        normalized = unicodedata.normalize("NFKD", value or "")
        return normalized.encode("ascii", "ignore").decode("ascii").lower()

    def scroll_to_bottom(self):
        """Scrolls to the bottom of the page."""
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(1, 2))

    def random_delay(self, min_sec=1, max_sec=3):
        """Introduces a random delay."""
        time.sleep(random.uniform(min_sec, max_sec))

    def wait_random(self, min_sec=1, max_sec=3):
        """Alias for random_delay used by subclasses."""
        self.random_delay(min_sec, max_sec)

    def get_page(self, url):
        """Standard wrapper to load a page with error handling."""
        try:
            self.driver.get(url)
            return True
        except Exception as e:
            logger.error(f"Failed to load page {url}: {e}")
            return False
