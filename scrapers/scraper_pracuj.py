"""Scraper for job listings on Pracuj.pl."""

import logging
import re
from datetime import datetime
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from scrapers.base_scraper import BaseScraper, ScraperRegistry
from utils.profile_matcher import ProfileMatcher
from utils.location_matcher import LocationMatcher
from utils.deduplication import Deduplicator
from models.database import JobOffer, OfferStatus

logger = logging.getLogger("scraper_pracuj")

@ScraperRegistry.register("pracuj.pl")
@ScraperRegistry.register("pracuj")
class PracujScraper(BaseScraper):
    """Search Pracuj.pl keyword results and employer profile listings."""

    def __init__(self, db_session):
        """Initialize matching, location filtering, and deduplication helpers."""
        super().__init__(db_session)
        self.matcher = ProfileMatcher()
        self.location_filter = LocationMatcher()
        self.db = db_session
        self.dedup = Deduplicator(db_session)

    def run(self, website_record):
        """Standard entry point for the orchestrator."""
        if website_record.url and "pracodawcy.pracuj.pl/company/" in website_record.url:
            self._scrape_company_page(website_record)
            return

        # Aggregators usually iterate over a list of keywords
        keywords = website_record.keywords.split(',') if website_record.keywords else ["rejestratorka medyczna"]
        location = website_record.location or "Kraków"

        for kw in keywords:
            self.scrape(kw.strip(), location, website_record.id)

    def scrape(self, keyword: str, search_location: str, website_id: int):
        """
        Scrapes Pracuj.pl by visiting detail pages for rich info extraction.
        """
        # slugify for path
        slug_kw = quote(keyword.replace(' ', '-'))
        slug_wp = quote(search_location.replace(' ', '-'))

        page = 1
        new_count = 0
        candidate_count = 0
        offer_selector = 'div[data-test="default-offer"], div.offer-tile_b18pwp01'

        while page <= 10:
            search_url = f"https://www.pracuj.pl/praca/{slug_kw};kw/{slug_wp};wp?pn={page}"
            logger.info(f"Scraping Pracuj.pl page {page}: {search_url}")

            if not self.get_page(search_url):
                break

            self.accept_cookies()
            self.random_delay(2, 4)

            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, offer_selector)))
            except Exception:
                logger.info(f"Pracuj.pl: no more offers found on page {page}.")
                break

            offers_elements = self.driver.find_elements(By.CSS_SELECTOR, offer_selector)
            if not offers_elements:
                break
            candidate_count += len(offers_elements)
            logger.info(f"Pracuj.pl: found {len(offers_elements)} candidate offer tiles on page {page}.")

            # Collect basic data first to avoid stale element exceptions when navigating
            offer_summaries = []
            for el in offers_elements:
                try:
                    title_el = el.find_element(By.CSS_SELECTOR, 'a[data-test="link-offer"], a[data-test="link-offer-title"], h2[data-test="offer-title"] > a')
                    title = title_el.text.strip()
                    if not title:
                        title = (title_el.get_attribute('title') or "").replace('Zobacz ofertę', '').strip(': ').strip()
                    
                    url = title_el.get_attribute('href').split('?')[0]
                    if not title or not url:
                        continue

                    offer_summaries.append({
                        'url': url,
                        'title': title,
                        'tile_company': self.extract_text(el, 'h3[data-test="text-company-name"]'),
                        'tile_location': self.extract_text(el, 'h4[data-test="text-region"]'),
                        'tile_info': self.extract_offer_info(el, title=title)
                    })
                except Exception: continue

            for summary in offer_summaries:
                url_addr = summary['url']
                if self.dedup.is_duplicate(url_addr):
                    continue

                # Fetch detail page
                detail_text, detail_company, detail_location = self._fetch_offer_details(url_addr)
                
                offer_info = self.normalize_offer_info(detail_text or summary['tile_info'], title=summary['title'])
                company = self.clean_company_name(
                    detail_company or summary['tile_company'],
                    offer_text=offer_info,
                    url=url_addr
                )
                loc_text = self.clean_location(
                    detail_location or summary['tile_location'],
                    offer_text=offer_info,
                    fallback=search_location
                )

                if not self.location_filter.is_within_radius(loc_text) and not self.location_filter.is_within_radius(search_location):
                    continue

                score = self.matcher.calculate_score(
                    self.build_match_text(summary['title'], company, loc_text, offer_info),
                    location_text=loc_text
                )
                if score < self.matcher.min_match_score:
                    continue

                logger.info(f"Pracuj.pl: accepted {summary['title']!r} score={score} company={company!r} url={url_addr}")
                new_offer = JobOffer(
                    title=summary['title'],
                    url=url_addr,
                    offer_info=offer_info,
                    location=loc_text,
                    score=score,
                    company_name=company,
                    url_hash=self.dedup._generate_url_hash(url_addr),
                    scraped_at=datetime.utcnow(),
                    website_id=website_id
                )
                try:
                    self.db.add(new_offer)
                    self.db.flush()
                    self.db.add(OfferStatus(offer_id=new_offer.id, status="new"))
                    new_count += 1
                except Exception as e:
                    logger.error(f"Pracuj.pl: DB error saving {url_addr}: {e}")
                    self.db.rollback()

            self.db.commit()
            page += 1

        logger.info(f"Pracuj.pl scrape finished. Candidates {candidate_count}, stored {new_count} new matching offers.")

    def _scrape_company_page(self, website_record):
        """Scrape direct employer pages on pracodawcy.pracuj.pl."""
        if not self.get_page(website_record.url):
            return

        self.accept_cookies()
        self.random_delay(2, 4)
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        links = []
        seen_urls = set()

        for link in soup.select('a[href*="pracuj.pl/praca/"], a[href*="/praca/"]'):
            href = link.get("href")
            if not href:
                continue
            offer_url = urljoin(website_record.url, href).split("?")[0].split("#")[0]
            if "pracuj.pl/praca/" not in offer_url or offer_url in seen_urls:
                continue
            title = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
            if len(title) < 5:
                title = (link.get("title") or "").strip()
            if len(title) < 5:
                continue
            seen_urls.add(offer_url)
            links.append({"url": offer_url, "title": title})

        candidate_count = len(links)
        logger.info(f"Pracuj.pl company page: found {candidate_count} candidate offer links for {website_record.company_name}.")
        new_count = 0
        fallback_location = website_record.location or "Krak\u00f3w"

        for summary in links:
            url_addr = summary["url"]
            if self.dedup.is_duplicate(url_addr):
                continue

            detail_text, detail_company, detail_location = self._fetch_offer_details(url_addr)
            offer_info = self.normalize_offer_info(detail_text, title=summary["title"])
            company = self.clean_company_name(detail_company or website_record.company_name, website_record, offer_info, url_addr)
            loc_text = self.clean_location(detail_location, website_record, offer_info, fallback=fallback_location)

            if not self.location_filter.is_within_radius(loc_text) and not self.location_filter.is_within_radius(fallback_location):
                continue

            score = self.matcher.calculate_score(
                self.build_match_text(summary["title"], company, loc_text, offer_info),
                location_text=loc_text
            )
            if score < self.matcher.min_match_score:
                continue

            new_offer = JobOffer(
                title=summary["title"],
                url=url_addr,
                offer_info=offer_info,
                location=loc_text,
                score=score,
                company_name=company,
                url_hash=self.dedup._generate_url_hash(url_addr),
                scraped_at=datetime.utcnow(),
                website_id=website_record.id
            )
            try:
                self.db.add(new_offer)
                self.db.flush()
                self.db.add(OfferStatus(offer_id=new_offer.id, status="new"))
                new_count += 1
            except Exception as e:
                logger.error(f"Pracuj.pl company page: DB error saving {url_addr}: {e}")
                self.db.rollback()

        self.db.commit()
        logger.info(f"Pracuj.pl company page finished for {website_record.company_name}. Candidates {candidate_count}, stored {new_count} matches.")

    def _fetch_offer_details(self, url):
        """Navigates to the detail page to extract rich info and sections."""
        if not self.get_page(url):
            return None, None, None
        
        self.random_delay(1, 2)
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'h1, [data-test="text-employerName"], main')))
        except Exception:
            logger.debug(f"Pracuj.pl: detail page loaded without expected header for {url}")

        # Some Pracuj detail blocks render lower on the page; scrolling helps lazy sections appear.
        try:
            self.driver.execute_script("window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.75));")
            self.random_delay(0.5, 1)
            self.driver.execute_script("window.scrollTo(0, 0);")
        except Exception:
            pass

        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        
        # 1. Extract sections (Responsibilities, Requirements, Offered)
        sections = []
        section_labels = {
            "section-responsibilities": "Zakres obowiązków",
            "section-requirements": "Wymagania",
            "section-offered": "Oferujemy",
        }
        for data_test, label in section_labels.items():
            node = soup.select_one(f'section[data-test="{data_test}"], div[data-test="{data_test}"]')
            if node:
                text = self.normalize_offer_info(node.get_text("\n", strip=True))
                if text:
                    sections.append(f"{label}\n{text}")
        
        full_info = "\n\n".join(sections) if sections else None
        
        # 2. Extract Company: prefer legal map company, fallback to visible employer brand.
        legal_node = soup.select_one('[data-test="section-map-company-details"] [data-test="text-employer-name"]')
        if not legal_node:
            legal_node = soup.select_one('[data-test="text-employer-name"]')
        legal_name = self._clean_detail_text(legal_node.get_text(" ", strip=True)) if legal_node else None

        brand_node = soup.select_one('[data-test="text-employerName"], [data-scroll-id="employer-name"]')
        brand_name = self._clean_detail_text(brand_node.get_text(" ", strip=True)) if brand_node else None
        
        # 3. Extract Precise Location (Address)
        address_node = soup.select_one('[data-test="section-map-company-details"] [data-test="text-address"]')
        if not address_node:
            address_node = soup.select_one('[data-test="text-address"]')
        address = self._clean_detail_text(address_node.get_text(" ", strip=True)) if address_node else None
        
        return full_info, legal_name or brand_name, address

    def _clean_detail_text(self, text):
        """Normalize text extracted from a Pracuj.pl offer detail page."""
        if not text:
            return None
        cleaned = re.sub(r"\s+", " ", text).strip()
        cleaned = re.sub(r"\bO firmie\b", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned or None
