"""Scraper for local career pages configured with CSS selectors."""

import logging
import requests
import json
import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
from selenium.webdriver.common.by import By
from datetime import datetime

from scrapers.base_scraper import BaseScraper, ScraperRegistry
from utils.profile_matcher import ProfileMatcher
from utils.location_matcher import LocationMatcher
from utils.deduplication import Deduplicator
from models.database import JobOffer, Website, OfferStatus

logger = logging.getLogger("scraper_local")

@ScraperRegistry.register("company_local")
class LocalScraper(BaseScraper):
    """Parse local career pages using configured selectors or Selenium."""

    JOB_URL_KEYWORDS = (
        "praca", "pracy", "kariera", "kariery", "oferty-pracy", "oferta-pracy",
        "rekrutacja", "rekrutacje", "job", "jobs", "career", "vacancy", "bip"
    )
    NON_OFFER_URL_KEYWORDS = (
        "kontakt", "contact", "dojazd", "map", "rodo", "privacy", "prywatnosci",
        "cookies", "polityka", "regulamin", "sitemap", "rss", "login", "logowanie",
        "aktualnosci", "news", "wydarzenia", "pacjent", "dla-pacjenta", "poradnik",
        "media", "galeria", "zamowienia-publiczne", "przetargi", "archiwum",
        "archive", "zgoda", "przyszle-rekrutacje", "przyszle_rekrutacje",
        "wspolpraca", "testdna"
    )
    NON_OFFER_TITLES = {
        "kontakt", "strona glowna", "strona główna", "o nas", "aktualnosci",
        "aktualności", "dla pacjenta", "zamowienia publiczne", "zamówienia publiczne",
        "polityka prywatnosci", "polityka prywatności", "rodo", "mapa strony",
        "bip", "menu", "archiwum", "zgoda na przetwarzanie na przyszle rekrutacje",
        "wspolpraca z testdna"
    }
    JOB_TITLE_KEYWORDS = (
        "recepc", "rejestrat", "asystent", "sekretark", "pracownik", "specjalist",
        "koordynator", "konsultant", "technik", "laborant", "pielęgni", "pielegni",
        "lekarz", "ratownik", "opiekun", "stanowisko", "zatrudni", "nabór", "nabor",
        "konkurs", "referent", "administr"
    )

    def __init__(self, db_session):
        """Initialize matching, location filtering, and duplicate detection."""
        super().__init__(db_session)
        self.db = db_session
        self.matcher = ProfileMatcher()
        self.location_filter = LocationMatcher()
        self.dedup = Deduplicator(db_session)

    def run(self, website_record: Website):
        """
        Standard entry point for local company scrapers.
        Uses requests for static sites as planned, with custom_config for parsing.
        """
        url = website_record.url
        company_name = website_record.company_name
        custom_config = json.loads(website_record.custom_config or "{}")
        
        # Local sites are usually static. If selenium is explicitly requested in config, use it.
        strategy = custom_config.get("strategy", "requests")
        
        logger.info(f"Starting {strategy} local scrape for {company_name}")

        try:
            if strategy == "selenium":
                self._scrape_with_selenium(website_record, custom_config)
            else:
                self._scrape_with_requests(website_record, custom_config)
        except Exception as e:
            logger.error(f"Failed to scrape local site {company_name}: {e}")
        # Cleanup is handled by the orchestrator

    def _apply_default_config(self, website_record, config):
        """Provide safe selectors for known local sites when DB config is empty."""
        if config.get("card_selector") and config.get("title_selector"):
            return config

        normalized_name = self._normalize_ascii(website_record.company_name)
        defaults = {
            "szpital uniwersytecki": {
                "card_selector": "a.btn-article[itemprop='url'], a[href*='/kariera/oferty-pracy/']",
                "title_selector": "h3.btn-article__title, h3[itemprop='name']"
            },
            "szpital rydygiera": {
                "card_selector": "a[href*='oferty-pracy'], a[href*='praca'], a[href*='nabor'], a[href*='konkurs']",
            },
            "nio krakow": {
                "card_selector": "h2.entry-title a, a[href*='praca'], a[href*='kariera'], a[href*='nabor'], a[href*='konkurs']",
            },
            "szpital dworska": {
                "card_selector": "a[href*='kariera'], a[href*='praca'], a[href*='rekrutacja']",
            },
        }

        for name, default_config in defaults.items():
            if name in normalized_name:
                merged = {**default_config, **config}
                logger.info(f"Using built-in local selectors for {website_record.company_name}")
                return merged

        return config

    def _looks_like_offer(self, title, full_url, website_record, configured):
        """Reject navigation links and identify links likely to be job offers."""
        title_clean = re.sub(r"\s+", " ", title or "").strip()
        if len(title_clean) < 5:
            return False

        title_norm = self._normalize_ascii(title_clean)
        if "@" in title_norm:
            return False

        parsed = urlparse(full_url)
        path_norm = self._normalize_ascii(unquote(parsed.path))
        base_path_norm = self._normalize_ascii(unquote(urlparse(website_record.url).path))

        if parsed.scheme in {"mailto", "tel"}:
            return False

        if title_norm in self.NON_OFFER_TITLES:
            return False
        if any(keyword in title_norm for keyword in self.NON_OFFER_TITLES):
            return False
        if any(keyword in path_norm for keyword in self.NON_OFFER_URL_KEYWORDS):
            return False

        # A career landing page is not itself an offer.
        if path_norm.rstrip("/") == base_path_norm.rstrip("/"):
            return False

        text_has_job_signal = any(keyword in title_norm for keyword in self.JOB_TITLE_KEYWORDS)
        url_has_job_signal = any(keyword in path_norm for keyword in self.JOB_URL_KEYWORDS)

        if configured:
            return text_has_job_signal or url_has_job_signal

        return text_has_job_signal and url_has_job_signal

    def _scrape_with_requests(self, website_record, config):
        """Fetch a static career page and parse its configured offer cards."""
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(website_record.url, headers=headers, timeout=15)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code} for {website_record.company_name}")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        self._parse_content(soup, website_record, self._apply_default_config(website_record, config))

    def _scrape_with_selenium(self, website_record, config):
        """Load a dynamic career page, expand configured sections, and parse it."""
        if not self.get_page(website_record.url):
            return
            
        # Handle accordions/expanding content if specified in custom_config
        expand_selector = config.get("expand_selector")
        if expand_selector:
            logger.info(f"Expanding items with selector: {expand_selector}")
            elements = self.driver.find_elements(By.CSS_SELECTOR, expand_selector)
            for el in elements:
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                    self.driver.execute_script("arguments[0].click();", el)
                    time.sleep(0.5) # Allow time for expansion animation
                except Exception:
                    continue

        self.random_delay(2, 4)
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        self._parse_content(soup, website_record, self._apply_default_config(website_record, config))

    def _parse_content(self, soup, website_record, config):
        """
        Generic parser using CSS selectors from custom_config.
        Local sites often just list titles and links in simple lists or divs.
        """
        # Do not scrape every link by default; unconfigured local pages contain many nav/footer links.
        card_selector = config.get("card_selector")
        title_selector = config.get("title_selector")
        configured = bool(card_selector)
        if not card_selector:
            logger.warning(
                f"Local parser: Missing card_selector for {website_record.company_name}. "
                "Falling back to job-looking links only."
            )
            card_selector = "a[href*='praca'], a[href*='kariera'], a[href*='rekrutacja'], a[href*='nabor'], a[href*='konkurs'], a[href*='job'], a[href*='career']"
        
        items = soup.select(card_selector)
        candidate_count = len(items)
        logger.info(f"Local parser: found {candidate_count} candidate items for {website_record.company_name}.")
        new_count = 0

        for item in items:
            try:
                # If title_selector is provided, use it; otherwise, use the text of the card itself
                title_el = item.select_one(title_selector) if title_selector else None
                title = title_el.get_text(" ", strip=True) if title_el else item.get_text(" ", strip=True)
                
                # Get URL: check item itself if it's an 'a' tag, or look for 'a' inside
                link_el = item if item.name == 'a' else item.find('a', href=True)
                if not link_el:
                    continue
                url_addr = link_el.get('href')
                if not url_addr:
                    continue
                
                full_url = urljoin(website_record.url, url_addr).split('#')[0]
                if not self._looks_like_offer(title, full_url, website_record, configured):
                    logger.debug(f"Local parser: skipped non-offer link title={title!r} url={full_url}")
                    continue
                location = website_record.location or "Kraków"
                offer_info = self.extract_offer_info(item, title=title)

                # 1. Deduplication
                if self.dedup.is_duplicate(full_url):
                    continue

                # 2. Match Scoring
                company = self.clean_company_name(None, website_record, offer_info, full_url)
                location = self.clean_location(location, website_record, offer_info)
                match_text = f"{self.build_match_text(title, company, location, offer_info)} {full_url}"
                score = self.matcher.calculate_score(match_text, location_text=location)
                if score < self.matcher.min_match_score:
                    continue

                # 3. Save to DB
                new_offer = JobOffer(
                    title=title,
                    company_name=company,
                    location=location,
                    url=full_url,
                    offer_info=offer_info,
                    score=score,
                    url_hash=self.dedup._generate_url_hash(full_url),
                    website_id=website_record.id
                )
                self.db.add(new_offer)
                self.db.flush()
                self.db.add(OfferStatus(offer_id=new_offer.id, status="new"))
                new_count += 1
            except Exception:
                continue
        
        self.db.commit()
        logger.info(f"Finished {website_record.company_name}. Candidates {candidate_count}, stored {new_count} matches.")
