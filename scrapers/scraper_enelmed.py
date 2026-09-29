"""Scraper for Enel-Med job listings."""

import logging
import time
import json
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from scrapers.base_scraper import BaseScraper, ScraperRegistry
from utils.profile_matcher import ProfileMatcher
from utils.deduplication import Deduplicator
from models.database import JobOffer, OfferStatus
from datetime import datetime

logger = logging.getLogger("scraper_enelmed")

@ScraperRegistry.register("enel-med")
class EnelMedScraper(BaseScraper):
    """Search Enel-Med listings and parse its dynamic career page."""

    def __init__(self, db_session):
        """Initialize matching and duplicate detection for this database session."""
        super().__init__(db_session)
        self.db = db_session
        self.matcher = ProfileMatcher()
        self.dedup = Deduplicator(db_session)

    def run(self, website_record):
        """Scrape the configured Enel-Med career URL and save matching offers."""
        # Use the specific offers page directly if possible, or main career
        url = website_record.url
        if not self.get_page(url):
            return

        try:
            self.accept_cookies()
            self._select_city_filter(website_record.location or "Krak\u00f3w")
            
            # 1. Interact with React Selects if we are on the landing page
            # Note: If the URL in DB is already filtered, this might be skippable
            try:
                # Filter Category: Obsługa klienta
                category_container = self.wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'Stanowisko')]")))
                # (Interaction logic for these custom React selects often requires clicking the container then the option)
            except:
                logger.debug("Enel-Med: Could not find filters, attempting direct parse.")

            # 2. Handle "Pokaż więcej" (Show more) pagination
            while True:
                try:
                    more_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Poka') and contains(., 'wi')]")
                    if more_btn.is_displayed():
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", more_btn)
                        more_btn.click()
                        time.sleep(2)
                    else:
                        break
                except:
                    break # No more buttons

            # 3. Parse result cards
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            # Based on saved logs: cards are <a> tags with specific classes
            cards = soup.select("a.shadow.rounded-2xl")
            candidate_count = len(cards)
            logger.info(f"Enel-Med: found {candidate_count} candidate offer cards.")
            
            new_count = 0
            for card in cards:
                try:
                    # Title is in a <p> with header-s class
                    title_el = card.select_one("p[class*='text-header-s'], p.text-header-s")
                    if not title_el: continue
                    
                    title = title_el.get_text(strip=True)
                    url = urljoin(website_record.url, card['href'])
                    offer_info = self.extract_offer_info(card, title=title)
                    
                    # Location is in a <p> after "MIEJSCE PRACY" label
                    loc_el = card.find("p", string=re.compile(r"Miejsce pracy", re.I))
                    location_text = website_record.location
                    if loc_el:
                        actual_loc = loc_el.find_next_sibling("p")
                        if actual_loc: location_text = actual_loc.get_text(strip=True)

                    company = self.clean_company_name("Enel-Med", website_record, offer_info, url)
                    location_text = self.clean_location(location_text, website_record, offer_info)
                    score = self.matcher.calculate_score(self.build_match_text(title, company, location_text, offer_info), location_text=location_text)
                    if score >= self.matcher.min_match_score and \
                       not self.dedup.is_duplicate(url):
                        
                        new_offer = JobOffer(
                            title=title,
                            company_name=company,
                            location=location_text,
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
                except Exception: continue

            if candidate_count == 0:
                json_new_count, json_candidate_count = self._parse_next_json_offers(soup, website_record)
                new_count += json_new_count
                candidate_count += json_candidate_count
            
            self.db.commit()
            logger.info(f"Enel-Med Scraper finished. Candidates {candidate_count}, stored {new_count} matches.")
        except Exception as e:
            self.save_failure_artifact("enelmed_error")
            logger.error(f"Enel-Med scraping error: {e}")

    def _select_city_filter(self, city_name):
        """Set the requested city in Enel-Med's career search filters."""
        try:
            city_input = self.wait.until(EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                'input[aria-label="Miejsce pracy"], input[id="Miejsce pracy"]'
            )))
            control = city_input.find_element(By.XPATH, "./ancestor::div[contains(@class, 'react-select__control')][1]")
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", control)
            self.driver.execute_script("arguments[0].click();", control)
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", city_input)
            city_input.click()
            city_input.send_keys(Keys.CONTROL, "a")
            city_input.send_keys(city_name)
            self.random_delay(0.5, 1)
            city_input.send_keys(Keys.ENTER)
            self._click_react_option(city_name)
            self.random_delay(2, 3)
            logger.info(f"Enel-Med: selected city filter {city_name!r}.")
        except Exception as e:
            logger.debug(f"Enel-Med: city filter not selected, continuing with current page: {e}")

    def _click_react_option(self, city_name):
        """Select a matching option from a React-rendered dropdown."""
        try:
            option_xpath = (
                "//*[contains(@id, 'react-select') and contains(@id, 'option') "
                "and contains(normalize-space(.), 'Krak')]"
            )
            option = WebDriverWait(self.driver, 3).until(EC.element_to_be_clickable((By.XPATH, option_xpath)))
            self.driver.execute_script("arguments[0].click();", option)
        except Exception:
            pass

    def _parse_next_json_offers(self, soup, website_record):
        """Extract offer records embedded in the page's Next.js data."""
        found_offers_count = 0
        offers_data = []

        for script in soup.find_all("script"):
            content = script.string or script.get_text()
            if not content or '"offers"' not in content:
                continue
            match = re.search(r'["\']offers["\']\s*:\s*(\[.*?\])', content)
            if not match:
                continue
            try:
                offers_data = json.loads(match.group(1).encode().decode("unicode-escape"))
                break
            except Exception as json_err:
                logger.debug(f"Enel-Med: JSON offer parse failed: {json_err}")

        candidate_count = len(offers_data)
        logger.info(f"Enel-Med: found {candidate_count} candidate offers in JSON fallback.")

        for offer in offers_data:
            try:
                title = (offer.get("positionTitle") or "").strip()
                raw_url = (offer.get("link") or "").strip()
                if not title or not raw_url:
                    continue
                location_values = offer.get("jobPlace") or website_record.location or "Krak\u00f3w"
                location_text = ", ".join(location_values) if isinstance(location_values, list) else str(location_values)
                offer_info = self.normalize_offer_info(
                    " | ".join(str(value) for value in offer.values() if value),
                    title=title
                )
                company = self.clean_company_name("Enel-Med", website_record, offer_info, raw_url)
                location_text = self.clean_location(location_text, website_record, offer_info)
                score = self.matcher.calculate_score(
                    self.build_match_text(title, company, location_text, offer_info),
                    location_text=location_text
                )
                if score < self.matcher.min_match_score or self.dedup.is_duplicate(raw_url):
                    continue

                new_offer = JobOffer(
                    title=title,
                    company_name=company,
                    location=location_text,
                    url=raw_url,
                    offer_info=offer_info,
                    score=score,
                    url_hash=self.dedup._generate_url_hash(raw_url),
                    scraped_at=datetime.utcnow(),
                    website_id=website_record.id
                )
                self.db.add(new_offer)
                self.db.flush()
                self.db.add(OfferStatus(offer_id=new_offer.id, status="new"))
                found_offers_count += 1
            except Exception:
                logger.debug("Enel-Med: skipped malformed JSON offer", exc_info=True)

        return found_offers_count, candidate_count
