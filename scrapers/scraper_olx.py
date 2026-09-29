"""Scraper for job listings on OLX."""

import logging
import re
import unicodedata
from datetime import datetime
from urllib.parse import quote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time
import random
from urllib.parse import urljoin
from models.database import JobOffer, OfferStatus
from utils.profile_matcher import ProfileMatcher
from utils.location_matcher import LocationMatcher
from utils.deduplication import Deduplicator

from .base_scraper import BaseScraper, ScraperRegistry

logger = logging.getLogger("scraper_olx")

@ScraperRegistry.register("olx.pl")
class OlxScraper(BaseScraper):
    """Search OLX job listings by the configured keyword and city."""

    def __init__(self, db_session):
        """Initialize profile matching, location filtering, and deduplication."""
        super().__init__(db_session)
        self.matcher = ProfileMatcher()
        self.location_filter = LocationMatcher()
        self.dedup = Deduplicator(db_session)

    def _slugify_for_olx(self, text: str) -> str:
        """Convert Polish text to the ASCII slug format used in OLX URLs."""
        normalized = unicodedata.normalize('NFKD', text)
        ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
        return ascii_text.replace(' ', '-')

    def _clean_olx_company_text(self, text):
        """Normalize employer text extracted from an OLX listing."""
        if not text:
            return None
        cleaned = re.sub(r"\s+", " ", text).strip()
        cleaned = re.sub(r"\bDowiedz się więcej\b", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\bLearn more\b", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned or None

    def _fetch_offer_details(self, offer_url):
        """Read detail-page text and employer name from an OLX offer."""
        if not offer_url:
            return None, None, None

        original_window = self.driver.current_window_handle
        original_windows = set(self.driver.window_handles)
        detail_text = None
        detail_company = None
        detail_location = None

        try:
            self.driver.execute_script("window.open(arguments[0], '_blank');", offer_url)
            WebDriverWait(self.driver, 10).until(lambda driver: len(driver.window_handles) > len(original_windows))
            new_window = next(handle for handle in self.driver.window_handles if handle not in original_windows)
            self.driver.switch_to.window(new_window)

            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'h1, [data-testid="job-ad-desktop-container"]'))
                )
            except Exception:
                logger.debug(f"OLX: detail page loaded without expected header for url={offer_url}")

            for selector in [
                '[data-testid="job-ad-desktop-container"] h1 + div span',
                '[data-testid="job-ad-desktop-container"] h1 + div',
                '.css-1xl5ij2 h1 + div span',
                '.css-1xl5ij2 h1 + div'
            ]:
                try:
                    company_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    detail_company = self._clean_olx_company_text(company_element.text)
                    if detail_company:
                        break
                except Exception:
                    continue

            if not detail_company:
                try:
                    company_element = self.driver.find_element(
                        By.XPATH,
                        '//h1/following-sibling::div[1]//span | //h1/following-sibling::div[1]'
                    )
                    detail_company = self._clean_olx_company_text(company_element.text)
                except Exception:
                    pass

            for selector in [
                '[data-testid="job-ad-desktop-container"]',
                'main',
                'body'
            ]:
                try:
                    detail_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    detail_text = self.extract_offer_info(detail_element)
                    if detail_text:
                        break
                except Exception:
                    continue

            try:
                location_label = self.driver.find_element(
                    By.XPATH,
                    '//*[normalize-space()="Lokalizacja"]/following::*[self::p or self::span][1]'
                )
                detail_location = location_label.text.strip()
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"OLX: could not fetch detail page for url={offer_url}: {e}")
        finally:
            try:
                if self.driver.current_window_handle != original_window:
                    self.driver.close()
                    self.driver.switch_to.window(original_window)
            except Exception:
                try:
                    self.driver.switch_to.window(original_window)
                except Exception:
                    pass

        return detail_text, detail_company, detail_location

    def run(self, website_record):
        """Search OLX and save new offers that pass profile and location filters."""
        keyword = website_record.keywords.split(',')[0] if website_record.keywords else "rejestratorka medyczna"
        city_name = website_record.location or "Kraków"
        
        logger.info(f"Starting OLX.pl scrape for '{keyword}' in '{city_name}'")
        
        # Normalize city and keyword to OLX-style ASCII slugs
        slug_city = quote(self._slugify_for_olx(city_name).lower().replace(' ', '-'))
        slug_keyword = quote(self._slugify_for_olx(keyword).lower().replace(' ', '-'))
        base_search_url = f"https://www.olx.pl/praca/{slug_city}/q-{slug_keyword}/"
        
        try:
            if not self.get_page(base_search_url):
                return
            
            self.accept_cookies()
            new_count = 0
            candidate_count = 0
            self.random_delay(2, 4)

            # Safely wait for offers to be visible
            offers_selector = ('//article[@data-testid="listing-item"] | //div[@data-cy="l-card"] '
                               '| //div[contains(@class, "jobs-ad-card")] | //div[contains(@class, "offer-wrapper")] '
                               '| //li[contains(@class, "offer")]')
            try:
                self.wait.until(EC.presence_of_element_located((By.XPATH, offers_selector)))
            except:
                logger.warning("OLX: No listing items appeared within timeout.")
            
            page_num = 1
            while True:
                logger.info(f"Scraping OLX.pl page {page_num} for '{keyword}' in '{city_name}'")
                offers_on_page = self.driver.find_elements(By.XPATH, offers_selector)
                logger.info(f"OLX: found {len(offers_on_page)} offer containers on page {page_num}")
                if not offers_on_page:
                    # fallback: try direct anchor selector used in rendered OLX listings
                    anchors = self.driver.find_elements(By.CSS_SELECTOR, 'a.css-m43axb, a.css-12tznnm, a[data-testid="ad-title"], a[data-cy="listing-ad-title"], a[data-testid="listing-ad-title"]')
                    if anchors:
                        logger.info(f"OLX: using {len(anchors)} anchor elements as fallback on page {page_num}")
                        offers_on_page = anchors
                    else:
                        logger.info(f"No more offers found on page {page_num}.")
                        break
                candidate_count += len(offers_on_page)
                logger.info(f"OLX: candidate offers seen so far: {candidate_count}")

                for offer_element in offers_on_page:
                    try:
                        title_element = None
                        if offer_element.tag_name.lower() == 'a':
                            title_element = offer_element

                        for selector in [
                            'a.css-m43axb',
                            'a.css-12tznnm',
                            'a[data-testid="ad-title"]',
                            'h3[data-testid="ad-title"] > a',
                            'a[data-cy="listing-ad-title"]',
                            'a[data-testid="listing-ad-title"]'
                        ]:
                            if title_element:
                                break
                            try:
                                candidate = offer_element.find_element(By.CSS_SELECTOR, selector)
                                if candidate:
                                    text = candidate.text.strip()
                                    if text:
                                        title_element = candidate
                                        break
                                    title_attr = candidate.get_attribute('title') or ""
                                    if title_attr:
                                        title_element = candidate
                                        break
                            except Exception:
                                continue

                        if not title_element:
                            try:
                                title_element = offer_element.find_element(By.XPATH, './/a[contains(@href, "/praca/") or contains(@href, "/oferta/")]')
                            except Exception:
                                title_element = None

                        if not title_element:
                            logger.debug("OLX: skipped an element without a title anchor")
                            continue

                        title = title_element.text.strip()
                        if not title:
                            title = title_element.get_attribute('title') or ""
                            if title.startswith("Zobacz ofertę"):
                                title = title.replace("Zobacz ofertę", "").strip(': ').strip()
                        offer_url = title_element.get_attribute('href')
                        if offer_url:
                            offer_url = urljoin("https://www.olx.pl", offer_url)
                        
                        company = "N/A"
                        for company_selector in [
                            'p[data-testid="company-name"]',
                            'span[data-testid="company-name"]',
                            '.offer-item__seller',
                            '.offer-item__seller-name',
                            'div[class*="seller"]',
                            'span[class*="seller"]',
                            'div[class*="company"]',
                            'span[class*="company"]'
                        ]:
                            try:
                                company_element = offer_element.find_element(By.CSS_SELECTOR, company_selector)
                                if company_element and company_element.text.strip():
                                    company = company_element.text.strip()
                                    break
                            except Exception:
                                continue
                        if company == "N/A":
                            try:
                                fallback_company = offer_element.find_element(By.XPATH, './/div[contains(@class, "seller") or contains(@class, "company") or contains(@class, "dealer") or contains(@class, "firm")][1]')
                                if fallback_company and fallback_company.text.strip():
                                    company = fallback_company.text.strip()
                            except Exception:
                                pass

                        location = None
                        posted_date = None
                        full_text = offer_element.text
                        for location_selector in ['p[data-testid="location-date"]', 'span[data-testid="location-date"]', 'p[data-testid="city"]', 'span[data-testid="city"]', 'div[data-testid="location"]', 'div[data-testid="ad-location"]']:
                            try:
                                location_date_element = offer_element.find_element(By.CSS_SELECTOR, location_selector)
                                location_date_text = location_date_element.text
                                parts = location_date_text.split(' - ')
                                if len(parts) > 0:
                                    location = parts[0].strip()
                                if len(parts) > 1:
                                    posted_date = parts[-1].strip()
                                break
                            except Exception:
                                continue

                        if not location:
                            location = self.location_filter.extract_known_city(full_text)
                        offer_info_parts = [full_text]
                        if posted_date:
                            offer_info_parts.append(f"Data w ogloszeniu: {posted_date}")
                        offer_info = self.normalize_offer_info(" | ".join(filter(None, offer_info_parts)), title=title)

                        if self.dedup.is_duplicate(offer_url):
                            logger.debug(f"OLX: skipped duplicate url={offer_url}")
                            continue

                        detail_text, detail_company, detail_location = self._fetch_offer_details(offer_url)
                        offer_info = self.normalize_offer_info(detail_text or offer_info, title=title)

                        company = self.clean_company_name(detail_company or company, website_record, offer_info, offer_url)
                        location = self.clean_location(detail_location or location, website_record, offer_info, fallback=city_name)

                        logger.debug(f"OLX: candidate parsed title={title!r} url={offer_url} company={company!r} location={location!r}")

                        score = self.matcher.calculate_score(
                            self.build_match_text(title, company, location, offer_info),
                            location_text=location
                        )
                        logger.debug(f"OLX: score for url={offer_url} -> {score}")
                        if score < self.matcher.min_match_score:
                            logger.debug(f"OLX: skipped by score (score={score} < min={self.matcher.min_match_score}) url={offer_url}")
                            continue

                        # If OLX listing lacks explicit location, fall back to the requested city
                        loc_to_check = location or city_name
                        if not self.location_filter.is_within_radius(loc_to_check):
                            logger.debug(f"OLX: skipped by location (loc={loc_to_check!r}) url={offer_url}")
                            continue

                        new_offer = JobOffer(
                            title=title,
                            company_name=company,
                            location=location,
                            url=offer_url,
                            offer_info=offer_info,
                            score=score,
                            url_hash=self.dedup._generate_url_hash(offer_url),
                            scraped_at=datetime.utcnow(),
                            website_id=website_record.id
                        )
                        try:
                            self.db.add(new_offer)
                            self.db.flush()
                            self.db.add(OfferStatus(offer_id=new_offer.id, status="new"))
                            new_count += 1
                            logger.info(f"OLX: accepted offer title={title!r} score={score} loc={loc_to_check!r} url={offer_url}")
                        except Exception as db_e:
                            logger.error(f"OLX: DB error when saving offer url={offer_url}: {db_e}")
                            self.db.rollback()

                    except Exception as e:
                        logger.warning(f"Could not extract all details for an OLX offer: {e}")
                
                self.db.commit()
                
                current_url = self.driver.current_url
                previous_url = current_url
                next_page_num = page_num + 1
                next_page_url = None
                
                next_page_link_element = self.find_element_safe(By.CSS_SELECTOR, f'a[data-testid="pagination-link-page-{next_page_num}"]')
                if next_page_link_element:
                    next_page_url = next_page_link_element.get_attribute('href')
                else:
                    next_button = self.find_element_safe(By.CSS_SELECTOR, 'a[data-testid="pagination-forward"], a[aria-label*="Next"], a[aria-label*="Następna"], li.pagination-next a')
                    if next_button and next_button.is_enabled() and next_button.is_displayed():
                        next_page_url = next_button.get_attribute('href')
                        if not next_page_url:
                            try:
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                                self.random_delay(1, 2)
                                self.driver.execute_script("arguments[0].click();", next_button)
                                self.random_delay(2, 4)
                                if self.driver.current_url != previous_url:
                                    page_num += 1
                                    if page_num > 10:
                                        break
                                    try:
                                        self.wait.until(
                                            EC.presence_of_element_located((By.XPATH, offers_selector))
                                        )
                                    except Exception:
                                        logger.warning(f"OLX: clicked next but no offer selector found on page {page_num}.")
                                    continue
                            except Exception:
                                next_page_url = None

                if next_page_url and next_page_url != current_url:
                    self.driver.get(next_page_url)
                    self.random_delay(3, 5)
                    page_num += 1
                    if page_num > 10:
                        break
                    try:
                        self.wait.until(
                            EC.presence_of_element_located((By.XPATH, offers_selector))
                        )
                    except Exception:
                        logger.warning(f"OLX: next page {page_num} loaded but no offer selector found.")
                else:
                    break
            
            logger.info(f"Finished OLX.pl scrape. Candidates {candidate_count}, stored {new_count} offers.")

        except Exception as e:
            self.save_failure_artifact(f"olx_search_error_{website_record.company_name}")
            logger.error(f"Error during OLX.pl search for '{keyword}' in '{city_name}': {e}")

ScraperRegistry.register_scraper("olx", OlxScraper)
