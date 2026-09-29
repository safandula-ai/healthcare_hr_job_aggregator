"""Scraper for eRecruiter job widgets used by selected employers."""

import logging
import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from scrapers.base_scraper import BaseScraper, ScraperRegistry
from utils.profile_matcher import ProfileMatcher
from utils.location_matcher import LocationMatcher
from utils.deduplication import Deduplicator
from models.database import JobOffer, OfferStatus
from datetime import datetime

logger = logging.getLogger("scraper_erecruiter")

@ScraperRegistry.register("synevo")
@ScraperRegistry.register("alab laboratoria")
@ScraperRegistry.register("affidea")
@ScraperRegistry.register("scanmed")
class ERecruiterScraper(BaseScraper):
    """Read job listings from employer career pages using eRecruiter widgets."""

    def __init__(self, db_session):
        """Initialize matching, location filtering, and deduplication helpers."""
        super().__init__(db_session)
        self.db = db_session
        self.matcher = ProfileMatcher()
        self.location_filter = LocationMatcher()
        self.dedup = Deduplicator(db_session)

    def run(self, website_record):
        """Load the employer page and dispatch to its eRecruiter layout parser."""
        if not self.get_page(website_record.url):
            return

        self.accept_cookies()
        if "scanmed" in self._normalize_ascii(website_record.company_name):
            self._scrape_scanmed(website_record)
            return
        
        # Synevo often injects a DIV widget, while others (Scanmed/Affidea) use an IFRAME.
        # We check for the iframe non-blockingly.
        iframes = self.driver.find_elements(By.CSS_SELECTOR, "iframe[src*='erecruiter.pl'], iframe#skk_iframe")
        if iframes:
            self.driver.switch_to.frame(iframes[0])
            logger.info(f"Switched to eRecruiter iframe for {website_record.company_name}")
        else:
            logger.info(f"No iframe found for {website_record.company_name}, assuming DIV widget.")

        found_offers_count = 0
        candidate_count = 0
        cfg = None
        page = 1

        # Wait for the widget content to actually appear in the DOM. Support both table rows and card-based widgets.
        try:
            self.wait.until(EC.presence_of_element_located((
                By.CSS_SELECTOR, "tr[skkresult='offer'], table.skk_offers tbody tr, div.jobs-ad-card, div.job-offer, a[href*='/Offer.aspx'], a[href*='/oferta/']"
            )))
        except Exception:
            logger.warning(f"Timeout waiting for widget content for {website_record.company_name}")

        while True:
            self.random_delay(2, 4)
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            if not cfg:
                script_tags = soup.find_all("script", src=re.compile(r"cfg="))
                for script in script_tags:
                    # Regex updated to include hyphens for GUID-style IDs found on Synevo
                    match = re.search(r"cfg=([a-zA-Z0-9\-]+)", script.get('src', ''))
                    if match:
                        cfg = match.group(1)
                        break

            # Prefer table rows, but fall back to card/anchor-based listings used by some DIV widgets
            offer_rows = soup.select("tr[skkresult='offer'], tr[jobofferid]")
            card_items = []
            if not offer_rows:
                # card-based widgets: look for common card containers or direct offer anchors
                card_items = soup.select('div.jobs-ad-card, div.job-offer, div.skk-offer, div[data-offer-id], a[href*="/Offer.aspx"], a[href*="/oferta/"]')
                if not card_items:
                    logger.warning(f"No offer rows or cards found in the current frame for {website_record.company_name}")
                    break
            page_candidate_count = len(offer_rows) if offer_rows else len(card_items)
            candidate_count += page_candidate_count
            logger.info(f"ERecruiter: found {page_candidate_count} candidate offers on page {page} for {website_record.company_name}.")

            for row in offer_rows:
                try:
                    title_el = row.select_one("td.skk_positionName a, td.skk_positionName")
                    if not title_el:
                        continue
                    
                    title = title_el.get_text(strip=True)
                    oid = row.get('offerid') or row.get('jobofferid')
                    
                    if oid and cfg:
                        com_id = row.get('comid')
                        ejo_id = row.get('externaljobofferid')
                        ejor_id = row.get('externaljobofferregionid')
                        offer_url = f"https://skk.erecruiter.pl/Offer.aspx?oid={oid}&cfg={cfg}&ejoId={ejo_id}&ejorId={ejor_id}&comId={com_id}"
                    else:
                        link_el = row.find('a', href=True)
                        if not link_el: continue
                        offer_url = urljoin("https://skk.erecruiter.pl/", link_el['href'])
                    
                    location_el = row.select_one("td.skk_col_work_place")
                    if location_el:
                        location_text = location_el.get_text(strip=True)
                    else:
                        tds = row.find_all("td")
                        if len(tds) > 1:
                            location_text = ", ".join(td.get_text(strip=True) for td in tds[1:] if td.get_text(strip=True))
                        else:
                            location_text = website_record.location or "Kraków"

                    offer_info = self.extract_offer_info(row, title=title)
                    company = self.clean_company_name(None, website_record, offer_info, offer_url)
                    location_text = self.clean_location(location_text, website_record, offer_info)
                    score = self.matcher.calculate_score(self.build_match_text(title, company, location_text, offer_info), location_text=location_text)
                    if score >= self.matcher.min_match_score and \
                       self.location_filter.is_within_radius(location_text) and \
                       not self.dedup.is_duplicate(offer_url):
                        
                        new_offer = JobOffer(
                            title=title,
                            company_name=company,
                            location=location_text,
                            url=offer_url,
                            offer_info=offer_info,
                            score=score,
                            url_hash=self.dedup._generate_url_hash(offer_url),
                            scraped_at=datetime.utcnow(),
                            website_id=website_record.id
                        )
                        self.db.add(new_offer)
                        self.db.flush()
                        self.db.add(OfferStatus(offer_id=new_offer.id, status="new"))
                        found_offers_count += 1
                except Exception:
                    logger.debug("ERecruiter: skipped a malformed table row", exc_info=True)
                    continue

            # Process card-based items if present
            for card in card_items:
                try:
                    # card may be an <a> or contain an <a> with title in h3/h4
                    link = card if card.name == 'a' and card.get('href') else card.select_one('a[href]')
                    if not link:
                        continue
                    href = link.get('href')
                    # title candidates
                    title_el = link.select_one('h4, h3') or card.select_one('h4, h3') or link
                    title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)

                    # build absolute URL
                    offer_url = href if href.startswith('http') else urljoin('https://skk.erecruiter.pl/', href)

                    # location extraction from nearby elements
                    location_text = ''
                    loc_el = card.select_one('.css-1lnzsw9, .skk_col_work_place, .job-location')
                    if loc_el:
                        location_text = loc_el.get_text(strip=True)
                    else:
                        location_text = website_record.location or 'Kraków'

                    offer_info = self.extract_offer_info(card, title=title)
                    company = self.clean_company_name(None, website_record, offer_info, offer_url)
                    location_text = self.clean_location(location_text, website_record, offer_info)
                    score = self.matcher.calculate_score(self.build_match_text(title, company, location_text, offer_info), location_text=location_text)
                    if score < self.matcher.min_match_score:
                        logger.debug(f"ERecruiter: candidate filtered by score ({score}) - {title}")
                        continue
                    if not self.location_filter.is_within_radius(location_text):
                        logger.debug(f"ERecruiter: candidate filtered by location ({location_text}) - {title}")
                        continue
                    if self.dedup.is_duplicate(offer_url):
                        logger.debug(f"ERecruiter: duplicate offer skipped {offer_url}")
                        continue

                    new_offer = JobOffer(
                        title=title,
                        company_name=company,
                        location=location_text,
                        url=offer_url,
                        offer_info=offer_info,
                        score=score,
                        url_hash=self.dedup._generate_url_hash(offer_url),
                        scraped_at=datetime.utcnow(),
                        website_id=website_record.id
                    )
                    self.db.add(new_offer)
                    self.db.flush()
                    self.db.add(OfferStatus(offer_id=new_offer.id, status='new'))
                    found_offers_count += 1
                except Exception:
                    logger.debug('ERecruiter: skipped a malformed card item', exc_info=True)
                    continue

            self.db.commit()

            try:
                next_page = page + 1
                next_btn = None
                for selector in [f"a.skk_pager_page[pn='{next_page}']", "a.skk_pager_next"]:
                    try:
                        candidate = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if candidate and candidate.is_displayed() and candidate.is_enabled():
                            next_btn = candidate
                            break
                    except Exception:
                        continue
                if next_btn:
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                    self.driver.execute_script("arguments[0].click();", next_btn)
                    self.random_delay(2, 4)
                    try:
                        self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tr[skkresult='offer'], tr[jobofferid], table.skk_offers tbody tr")))
                    except Exception:
                        logger.warning(f"ERecruiter: pagination moved but no rows detected for {website_record.company_name}.")
                    page += 1
                    if page > 15:
                        break
                else:
                    break
            except Exception:
                break
            
        logger.info(f"ERecruiter Scraper finished for {website_record.company_name}. Candidates {candidate_count}, stored {found_offers_count} matches.")

    def _scrape_scanmed(self, website_record):
        """Handle the Scanmed career page's custom search and listing layout."""
        logger.info("Scanmed: using city-filtered career page parser.")
        candidate_count = 0
        found_offers_count = 0

        try:
            city_select = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select#oferty-pracy-miasto")))
            selector = Select(city_select)
            target_city = website_record.location or "Krak\u00f3w"
            selected = False
            for option in selector.options:
                label = option.text.strip()
                value = (option.get_attribute("value") or "").strip()
                if "krak" in self._normalize_ascii(label) or "krak" in self._normalize_ascii(value):
                    selector.select_by_value(value)
                    selected = True
                    logger.info(f"Scanmed: selected city filter option {label!r}.")
                    break
            if not selected:
                logger.warning(f"Scanmed: could not find Krakow city option; requested location={target_city!r}.")
            self.driver.execute_script(
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                city_select
            )
            self.random_delay(2, 4)
        except Exception as e:
            logger.warning(f"Scanmed: city filter was not available or could not be selected: {e}")

        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        all_cards = soup.select("div.oferta-pracy")
        visible_cards = [
            card for card in all_cards
            if "display: none" not in (card.get("style") or "").lower()
        ]
        cards = visible_cards or all_cards
        if not cards:
            cards = soup.select("a[href*='elevato.net'], a[href*=',j,']")
        candidate_count = len(cards)
        logger.info(f"Scanmed: found {candidate_count} candidate offer cards.")

        for card in cards:
            try:
                title_el = card.select_one(".oferta-title h2, h2, h3")
                link_el = card.find("a", href=True) if getattr(card, "name", None) != "a" else card
                if not title_el or not link_el:
                    continue

                title = title_el.get_text(" ", strip=True)
                offer_url = urljoin(website_record.url, link_el.get("href"))
                offer_info = self.extract_offer_info(card, title=title)
                location_el = card.select_one(".jednostka-title, .location, [class*='place']")
                location_text = location_el.get_text(" ", strip=True) if location_el else website_record.location

                company = self.clean_company_name("Scanmed", website_record, offer_info, offer_url)
                location_text = self.clean_location(location_text, website_record, offer_info)
                score = self.matcher.calculate_score(
                    self.build_match_text(title, company, location_text, offer_info),
                    location_text=location_text
                )
                if score < self.matcher.min_match_score:
                    logger.debug(f"Scanmed: candidate filtered by score ({score}) - {title}")
                    continue
                if not self.location_filter.is_within_radius(location_text):
                    logger.debug(f"Scanmed: candidate filtered by location ({location_text}) - {title}")
                    continue
                if self.dedup.is_duplicate(offer_url):
                    logger.debug(f"Scanmed: duplicate skipped {offer_url}")
                    continue

                new_offer = JobOffer(
                    title=title,
                    company_name=company,
                    location=location_text,
                    url=offer_url,
                    offer_info=offer_info,
                    score=score,
                    url_hash=self.dedup._generate_url_hash(offer_url),
                    scraped_at=datetime.utcnow(),
                    website_id=website_record.id
                )
                self.db.add(new_offer)
                self.db.flush()
                self.db.add(OfferStatus(offer_id=new_offer.id, status="new"))
                found_offers_count += 1
            except Exception:
                logger.debug("Scanmed: skipped a malformed offer card", exc_info=True)

        self.db.commit()
        logger.info(f"Scanmed Scraper finished. Candidates {candidate_count}, stored {found_offers_count} matches.")
