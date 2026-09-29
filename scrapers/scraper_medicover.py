"""Scraper for job listings on the Medicover career site."""

import logging
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from scrapers.base_scraper import BaseScraper, ScraperRegistry
from utils.profile_matcher import ProfileMatcher
from utils.location_matcher import LocationMatcher
from utils.deduplication import Deduplicator
from models.database import JobOffer, OfferStatus
from datetime import datetime

logger = logging.getLogger("scraper_medicover")

@ScraperRegistry.register("medicover")
class MedicoverScraper(BaseScraper):
    """Search Medicover's career site using its role and city filters."""

    def __init__(self, db_session):
        """Initialize matching and deduplication for this database session."""
        super().__init__(db_session)
        self.db = db_session
        self.matcher = ProfileMatcher()
        self.dedup = Deduplicator(db_session)

    def run(self, website_record):
        """Search for matching offers on the configured Medicover page."""
        if not self.get_page(website_record.url):
            return

        try:
            self.accept_cookies()
            
            # 1. Fill Job Type
            self._select_expandable_filter("ddlJobType", "Recepcja i administracja")

            # 2. Fill City
            city_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input#ddlCity')))
            city_input.clear()
            city_input.send_keys(website_record.location or "Kraków")
            self.random_delay(1, 2)
            city_input.send_keys(Keys.ENTER)
            self._select_expandable_filter("ddlCity", website_record.location or "Krak\u00f3w")

            # 3. Click Search
            search_btn = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button#btnSubmitSearch, button.erecruter-offer__select--button')))
            search_btn.click()
            self.random_delay(3, 5)

            # 4. Parse results from DOM
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            # Medicover uses standard result rows
            rows = soup.select("div.result-row, .position-item") 
            candidate_count = len(rows)
            logger.info(f"Medicover: found {candidate_count} candidate offer rows.")
            
            new_count = 0
            for row in rows:
                title_el = row.select_one(".title, h2, h3")
                link_el = row.find('a', href=True)
                if not title_el or not link_el: continue
                
                title = title_el.get_text(strip=True)
                url = urljoin(website_record.url, link_el['href'])
                offer_info = self.extract_offer_info(row, title=title)
                
                company = self.clean_company_name("Medicover", website_record, offer_info, url)
                location = self.clean_location(website_record.location, website_record, offer_info)
                score = self.matcher.calculate_score(self.build_match_text(title, company, location, offer_info), location_text=location)
                if score >= self.matcher.min_match_score and \
                   not self.dedup.is_duplicate(url):
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
            logger.info(f"Medicover Scraper finished. Candidates {candidate_count}, stored {new_count} matches.")
        except Exception as e:
            self.save_failure_artifact("medicover_error")
            logger.error(f"Medicover scraping error: {e}")

    def _select_expandable_filter(self, input_id, wanted_text):
        """Choose a value from a filter whose options expand after interaction."""
        input_el = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, f"input#{input_id}")))
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", input_el)
        self.driver.execute_script("arguments[0].click();", input_el)
        try:
            input_el.clear()
        except Exception:
            pass
        input_el.send_keys(wanted_text)
        self.random_delay(0.5, 1)

        wanted_norm = self._normalize_ascii(wanted_text)
        clicked = self.driver.execute_script(
            """
            const wanted = arguments[0];
            const normalize = (value) => (value || '')
                .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
            const input = document.querySelector('#' + arguments[1]);
            const container = input ? input.closest('.erecruter-offer__select--kontener') : null;
            const roots = container ? [container] : [document];
            for (const root of roots) {
                const items = Array.from(root.querySelectorAll('li.expandable-filter-item'));
                const item = items.find((el) => normalize(el.textContent).includes(wanted) || normalize(el.dataset.value).includes(wanted));
                if (item) {
                    item.style.display = '';
                    item.click();
                    if (input) {
                        input.value = item.dataset.value || item.textContent.trim();
                        input.dispatchEvent(new Event('input', {bubbles: true}));
                        input.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                    return item.textContent.trim();
                }
            }
            return null;
            """,
            wanted_norm,
            input_id,
        )
        if not clicked:
            input_el.send_keys(Keys.ENTER)
            clicked = wanted_text
        logger.info(f"Medicover: selected {input_id} filter {clicked!r}.")
        self.random_delay(1, 2)
