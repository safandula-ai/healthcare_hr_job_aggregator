"""Scraper for job listings on the University Hospital career site."""

import logging
import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from scrapers.base_scraper import BaseScraper, ScraperRegistry
from utils.profile_matcher import ProfileMatcher
from utils.location_matcher import LocationMatcher
from utils.deduplication import Deduplicator
from models.database import JobOffer, OfferStatus
from datetime import datetime

logger = logging.getLogger("scraper_su")

@ScraperRegistry.register("szpital uniwersytecki")
class SUScraper(BaseScraper):
    """Collect job offers from the University Hospital career page."""

    def __init__(self, db_session):
        """Initialize profile matching and URL-based duplicate detection."""
        super().__init__(db_session)
        self.db = db_session
        self.matcher = ProfileMatcher()
        self.dedup = Deduplicator(db_session)

    def run(self, website_record):
        """Load the hospital career page and persist matching offer links."""
        if not self.get_page(website_record.url):
            return

        self.accept_cookies()

        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'a.btn-article[itemprop="url"], a[href*="/kariera/oferty-pracy/"]')))
        except Exception:
            logger.warning("SU: page loaded but no career links were found.")

        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        anchors = soup.select('a.btn-article[itemprop="url"], a[href*="/kariera/oferty-pracy/"]')
        logger.info(f"SU: found {len(anchors)} candidate career links.")
        new_count = 0

        for anchor in anchors:
            href = anchor.get('href')
            if not href:
                continue

            # Prefer the structured title inside the anchor if present
            title_elem = anchor.select_one('h3.btn-article__title, h3[itemprop="name"]')
            if title_elem:
                title = title_elem.get_text(" ", strip=True)
            else:
                title_raw = anchor.get_text(" ", strip=True)
                title = re.sub(r'Data publikacji:.*$', '', title_raw, flags=re.I).replace('Więcej', '').strip()
                title = " ".join(title.split())
            if not title or len(title) < 5:
                continue

            url = urljoin(website_record.url, href)
            title_norm = self._normalize_ascii(title)
            path_norm = self._normalize_ascii(unquote(urlparse(url).path))
            non_offer_terms = (
                "archiwum", "zgoda na przetwarzanie", "przyszle rekrutacje",
                "przyszle-rekrutacje", "wspolpraca", "testdna"
            )
            if any(term in title_norm or term in path_norm for term in non_offer_terms):
                logger.debug(f"SU: skipped non-offer page {title} -> {url}")
                continue

            offer_info = self.extract_offer_info(anchor, title=title)
            if self.dedup.is_duplicate(url):
                logger.debug(f"SU: duplicate skipped {url}")
                continue

            company = self.clean_company_name(None, website_record, offer_info, url)
            location = self.clean_location(None, website_record, offer_info)
            match_text = f"{self.build_match_text(title, company, location, offer_info)} {url}"
            score = self.matcher.calculate_score(match_text, location_text=location)
            if score < self.matcher.min_match_score:
                logger.debug(f"SU: filtered by score {score} < {self.matcher.min_match_score} -> {title}")
                continue

            new_offer = JobOffer(
                title=title,
                company_name=company,
                location=location,
                url=url,
                offer_info=offer_info,
                score=score,
                url_hash=self.dedup._generate_url_hash(url),
                website_id=website_record.id
            )
            self.db.add(new_offer)
            self.db.flush()
            self.db.add(OfferStatus(offer_id=new_offer.id, status="new"))
            new_count += 1
        
        self.db.commit()
        logger.info(f"SU Scraper finished. Candidates {len(anchors)}, stored {new_count} matches.")
