"""Scraper for job listings on the LUX MED career site."""

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

logger = logging.getLogger("scraper_luxmed")

@ScraperRegistry.register("lux med")
class LuxMedScraper(BaseScraper):
    """Search LUX MED's career site for matching healthcare administration roles."""

    def __init__(self, db_session):
        """Initialize matching and deduplication for this database session."""
        super().__init__(db_session)
        self.db = db_session
        self.matcher = ProfileMatcher()
        self.location_filter = LocationMatcher()
        self.dedup = Deduplicator(db_session)

    def run(self, website_record):
        """Apply the configured location filter and collect LUX MED offers."""
        if not self.get_page(website_record.url):
            return

        try:
            self.accept_cookies()
            
            # 1. Handle Location Input (Angular Material)
            loc_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[matinput][placeholder="Cała Polska"]')))
            loc_input.send_keys(website_record.location or "Kraków")
            self.random_delay(1, 2)
            loc_input.send_keys(Keys.ENTER)
            
            # 2. Select Category (Obsługa Pacjenta)
            category_xpath = "//div[contains(@class, 'checkbox__label') and contains(text(), 'Obsługa Pacjenta')]"
            category_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, category_xpath)))
            category_btn.click()
            self.random_delay(2, 3)

            # 3. Parse results
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            # LuxMed often lists cards that link to erecruiter.pl
            offer_cards = soup.select("div.job-offer-item, a.job-offer-card, a[href*='skk.erecruiter.pl/Offer.aspx']")
            candidate_count = len(offer_cards)
            logger.info(f"LuxMed: found {candidate_count} candidate offer cards.")
            
            new_count = 0
            for card in offer_cards:
                title_el = card.select_one("h3, h4, .title") if card.name != 'a' else None
                link_el = card if card.name == 'a' else card.find('a', href=True)
                
                if not link_el: continue
                
                title = title_el.get_text(strip=True) if title_el else link_el.get_text(" ", strip=True)
                if not title:
                    continue
                url = urljoin(website_record.url, link_el['href'])
                offer_info = self.extract_offer_info(card, title=title)
                
                company = self.clean_company_name("LUX MED", website_record, offer_info, url)
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
            logger.info(f"LuxMed Scraper finished. Candidates {candidate_count}, stored {new_count} matches.")
        except Exception as e:
            self.save_failure_artifact("luxmed_error")
            logger.error(f"LuxMed scraping error: {e}")
