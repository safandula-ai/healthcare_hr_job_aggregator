"""Shared and employer-specific scrapers for nationwide career sites."""

import json
import re
import logging
import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import unquote, urljoin
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from scrapers.base_scraper import BaseScraper, ScraperRegistry
from utils.profile_matcher import ProfileMatcher
from utils.location_matcher import LocationMatcher
from utils.deduplication import Deduplicator
from models.database import SessionLocal, JobOffer, Website, OfferStatus

logger = logging.getLogger("scraper_nationwide")

@ScraperRegistry.register("company_nationwide")
class NationwideScraper(BaseScraper):
    """Handle shared and employer-specific parsing for nationwide career sites."""

    def __init__(self, db_session):
        """Initialize database, profile matching, location, and deduplication helpers."""
        super().__init__(db_session)
        self.db = db_session
        self.matcher = ProfileMatcher()
        self.location_filter = LocationMatcher()
        self.dedup = Deduplicator(db_session)

    def _add_job_offer_to_db(self, title, company, location, url, score, website_id, offer_info=None):
        """Add an offer and its initial application status to the active session."""
        url_hash = self.dedup._generate_url_hash(url)
        new_offer = JobOffer(
            title=title,
            company_name=company or "N/A",
            location=location or "Kraków",
            url=url,
            offer_info=offer_info,
            score=score,
            url_hash=url_hash,
            scraped_at=datetime.utcnow(),
            website_id=website_id
        )
        self.db.add(new_offer)
        self.db.flush()
        self.db.add(OfferStatus(offer_id=new_offer.id, status="new"))

    def scrape_website(self, website_record: Website):
        """Alias for run() maintained for backward compatibility within this class."""
        self.run(website_record)

    def run(self, website_record: Website):
        """Choose a strategy for the source and persist matching listings."""
        url = website_record.url
        company_name = website_record.company_name.lower().strip()
        custom_config = json.loads(website_record.custom_config or "{}")
        
        # Determine strategy: default to Selenium for known JS-heavy medical portals
        strategy = custom_config.get("strategy")
        if not strategy:
            # Normalize name to alpha-numeric only to catch variations like "LUX MED" or "LUX-MED"
            normalized_name = re.sub(r'[^a-z0-9]', '', company_name)
            js_heavy_brands = ["luxmed", "medicover", "enelmed", "scanmed", "synevo", "alab", "affidea"]
            
            strategy = "selenium" if any(brand in normalized_name for brand in js_heavy_brands) else "requests"
            logger.info(f"Auto-selected strategy '{strategy}' for {company_name}")
            
        logger.info(f"Starting {strategy} scrape for {company_name} via {url}")
        
        try:
            if strategy == "selenium":
                if not self.get_page(url):
                    logger.error(f"Failed to load {url} with Selenium.")
                    return

                # Global cookie dismissal attempt for all Selenium nationwide sites
                self.accept_cookies()
                
                # Fallback to generic DOM parsing
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                self._parse_generic_html(soup, website_record, custom_config)

            else: # Default to requests + BeautifulSoup
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code != 200:
                    logger.error(f"Failed to load {url}. Status code: {response.status_code}")
                    return
                soup = BeautifulSoup(response.text, 'html.parser')

                if company_name.lower() == "allmedica":
                    self._scrape_allmedica_requests(soup, website_record, custom_config)
                else:
                    self._parse_generic_html(soup, website_record, custom_config)
            self.db.commit()

        except Exception as e:
            self.save_failure_artifact(f"{company_name}_scrape_error")
            logger.error(f"Error processing nationwide site {company_name}: {str(e)}")

    def _parse_enel_med_json(self, soup, website_record):
        """Parse Enel-Med offer data embedded in JSON script elements."""
        found_offers_count = 0
        scripts = soup.find_all('script')
        offers_data = []

        for script in scripts:
            if script.string and '"offers":[' in script.string:
                match = re.search(r'["\']offers["\']\s*:\s*(\[.*?\])', script.string)
                if match:
                    try:
                        json_str = match.group(1).encode().decode('unicode-escape')
                        offers_data = json.loads(json_str)
                        break
                    except Exception as json_err:
                        logger.debug(f"Enel-Med JSON parsing error: {json_err}")
                        continue

        if not offers_data:
            logger.warning("Could not automatically locate the JSON offers block for Enel-Med. Running DOM fallback extraction.")
            self._parse_enel_med_dom_fallback(soup, website_record)
            return

        logger.info(f"Enel-Med JSON: found {len(offers_data)} candidate offers.")

        for offer in offers_data:
            title = offer.get("positionTitle", "").strip()
            raw_url = offer.get("link", "").strip()
            offer_url = unquote(raw_url).replace('&amp;', '&')
            places = offer.get("jobPlace", [])
            location_text = ", ".join(places) if isinstance(places, list) else str(places)

            if not title or not offer_url:
                continue

            offer_info = self.normalize_offer_info(
                " | ".join(str(value) for value in offer.values() if value),
                title=title
            )
            company = self.clean_company_name(None, website_record, offer_info, offer_url)
            location_text = self.clean_location(location_text, website_record, offer_info)
            score = self.matcher.calculate_score(self.build_match_text(title, company, location_text, offer_info), location_text=location_text)
            if score < self.matcher.min_match_score:
                continue
            if not self.location_filter.is_within_radius(location_text):
                continue
            if self.dedup.is_duplicate(offer_url):
                continue

            self._add_job_offer_to_db(
                title=title,
                company=company,
                location=location_text,
                url=offer_url,
                score=score,
                website_id=website_record.id,
                offer_info=offer_info
            )
            found_offers_count += 1

        logger.info(f"Enel-Med JSON parsing completed. Candidates {len(offers_data)}, stored {found_offers_count} offers.")

    def _parse_enel_med_dom_fallback(self, soup, website_record):
        """Parse Enel-Med offer cards when embedded JSON is unavailable."""
        offer_cards = soup.select("div[class*='border-b'][class*='border-grey200']") or soup.find_all("div", class_=lambda x: x and "border-b" in x and "grey200" in x)
        found_offers_count = 0
        candidate_count = len(offer_cards)
        logger.info(f"Enel-Med DOM fallback: found {candidate_count} candidate cards.")

        for card in offer_cards:
            title_el = card.find(re.compile(r'^(h2|h3|h4|div)'), class_=lambda x: x and 'font-medium' in x)
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            
            link_el = card.find('a', href=lambda h: h and 'erecruiter.pl' in h)
            if not link_el:
                continue
            offer_url = link_el['href']
            
            loc_divs = card.find_all('div', class_=lambda x: x and 'text-grey800' in x)
            location_text = loc_divs[-1].get_text(strip=True) if loc_divs else "Unknown"
            offer_info = self.extract_offer_info(card, title=title)

            company = self.clean_company_name(None, website_record, offer_info, offer_url)
            location_text = self.clean_location(location_text, website_record, offer_info)
            score = self.matcher.calculate_score(self.build_match_text(title, company, location_text, offer_info), location_text=location_text)
            if score >= self.matcher.min_match_score and \
               self.location_filter.is_within_radius(location_text) and \
               not self.dedup.is_duplicate(offer_url):
                self._add_job_offer_to_db(
                    title=title,
                    company=company,
                    location=location_text,
                    url=offer_url,
                    score=score,
                    website_id=website_record.id,
                    offer_info=offer_info
                )
                found_offers_count += 1
        logger.info(f"Enel-Med DOM fallback completed. Candidates {candidate_count}, stored {found_offers_count} offers.")

    def _scrape_luxmed_selenium(self, website_record, custom_config):
        """Apply LUX MED filters and read listings through Selenium."""
        logger.info(f"Scraping LUX MED with Selenium...")
        try:
            # Example: Interact with location input
            location_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[matinput][placeholder="Cała Polska"]'))
            )
            location_input.send_keys("Kraków") # Or use website_record.location
            self.wait_random(1, 2)
            location_input.send_keys(Keys.ENTER)
            
            # Example: Click "Obsługa Pacjenta" category
            category_checkbox = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'checkbox__label') and text()='Obsługa Pacjenta']"))
            )
            category_checkbox.click()
            self.wait_random(2, 3)

            # Now scrape the results, which often link to erecruiter.pl
            self._scrape_erecruiter_widget_selenium(website_record, custom_config)

        except TimeoutException:
            logger.warning("LUX MED: Timeout waiting for elements. Page structure might have changed or no results.")
        except NoSuchElementException:
            logger.warning("LUX MED: Element not found. Page structure might have changed.")
        except Exception as e:
            logger.error(f"LUX MED Selenium error: {e}")

    def _scrape_medicover_selenium(self, website_record, custom_config):
        """Apply Medicover filters and parse the resulting offer cards."""
        logger.info(f"Scraping Medicover with Selenium...")
        try:
            # Fill Job Type
            job_type_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input#ddlJobType'))
            )
            job_type_input.send_keys("Recepcja i administracja")
            self.wait_random(1, 2)
            job_type_input.send_keys(Keys.ENTER)

            # Fill City
            city_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input#ddlCity'))
            )
            city_input.send_keys("Kraków") # Or use website_record.location
            self.wait_random(1, 2)
            city_input.send_keys(Keys.ENTER)

            # Click search button
            search_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'button#btnSubmitSearch'))
            )
            search_button.click()
            self.wait_random(3, 5)

            # Scrape results from the current page
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            self._parse_generic_html(soup, website_record, custom_config) # Use generic parser for results

        except TimeoutException:
            logger.warning("Medicover: Timeout waiting for elements. Page structure might have changed or no results.")
        except NoSuchElementException:
            logger.warning("Medicover: Element not found. Page structure might have changed.")
        except Exception as e:
            logger.error(f"Medicover Selenium error: {e}")

    def _scrape_erecruiter_widget_selenium(self, website_record, custom_config):
        """Read paginated offer rows from an embedded eRecruiter widget."""
        logger.info(f"Scraping eRecruiter widget for {website_record.company_name} with Selenium...")

        # Handle potential iframe switch (Common for Synevo and Affidea)
        try:
            # Wait for widget initialization
            time.sleep(3)
            iframes = self.driver.find_elements(By.CSS_SELECTOR, "iframe[src*='erecruiter.pl'], iframe#skk_iframe")
            if iframes:
                self.driver.switch_to.frame(iframes[0])
                logger.info("Switched to eRecruiter iframe.")
        except Exception as e:
            logger.debug(f"Proceeding without iframe switch: {e}")

        found_offers_count = 0
        candidate_count = 0
        page = 1
        
        # Try to find the eRecruiter configuration ID (cfg)
        cfg = custom_config.get("erecruiter_cfg")
        
        while True:
            self.wait_random(2, 4)
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            if not cfg:
                script_tags = soup.find_all("script", src=re.compile(r"cfg="))
                for script in script_tags:
                    match = re.search(r"cfg=([a-zA-Z0-9]+)", script.get('src', ''))
                    if match:
                        cfg = match.group(1)
                        logger.debug(f"Detected eRecruiter cfg: {cfg}")
                        break

            # Common eRecruiter widget selectors
            # Look for rows that are explicitly marked as offers or within the offers table
            offer_rows = soup.select("tr[skkresult='offer']") or soup.select("table.skk_offers tbody tr")
            if not offer_rows:
                break
            candidate_count += len(offer_rows)
            logger.info(f"eRecruiter widget: found {len(offer_rows)} candidate rows on page {page} for {website_record.company_name}.")

            for row in offer_rows:
                try:
                    # Title can be in an 'a' tag or directly in the 'td'
                    title_el = row.select_one("td.skk_positionName a") or row.select_one("td.skk_positionName")
                    if not title_el: continue
                    
                    title = title_el.get_text(strip=True)
                    
                    # Construct URL from attributes (common in Synevo/ALAB/Affidea)
                    oid = row.get('offerid')
                    if oid and cfg:
                        com_id = row.get('comid')
                        ejo_id = row.get('externaljobofferid')
                        ejor_id = row.get('externaljobofferregionid')
                        offer_url = f"https://skk.erecruiter.pl/Offer.aspx?oid={oid}&cfg={cfg}&ejoId={ejo_id}&ejorId={ejor_id}&comId={com_id}"
                    else:
                        # Fallback to finding an anchor tag with href
                        link_el = row.find('a', href=True)
                        if not link_el: continue
                        offer_url = urljoin(website_record.url, link_el['href'])
                    
                    # Location is often in a specific class or the last cell
                    location_el = row.select_one("td.skk_col_work_place")
                    if location_el:
                        location_text = location_el.get_text(strip=True)
                    else:
                        # Fallback: take the last cell text (usually the city)
                        cells = row.find_all("td")
                        location_text = cells[-1].get_text(strip=True) if cells else website_record.location

                    offer_info = self.extract_offer_info(row, title=title)
                    company = self.clean_company_name(None, website_record, offer_info, offer_url)
                    location_text = self.clean_location(location_text, website_record, offer_info)
                    score = self.matcher.calculate_score(self.build_match_text(title, company, location_text, offer_info), location_text=location_text)
                    if score >= self.matcher.min_match_score and \
                       self.location_filter.is_within_radius(location_text) and \
                       not self.dedup.is_duplicate(offer_url):
                        self._add_job_offer_to_db(
                            title=title,
                            company=company,
                            location=location_text,
                            url=offer_url,
                            score=score,
                            website_id=website_record.id,
                            offer_info=offer_info
                        )
                        found_offers_count += 1
                except Exception as e:
                    logger.warning(f"Error parsing eRecruiter offer for {website_record.company_name}: {e}")

            # Pagination for eRecruiter widgets
            try:
                next_btn = self.driver.find_element(By.CSS_SELECTOR, "a.skk_pager_next")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                self.driver.execute_script("arguments[0].click();", next_btn)
                page += 1
            except Exception:
                break
        logger.info(f"eRecruiter widget scrape for {website_record.company_name} finished. Candidates {candidate_count}, stored {found_offers_count} offers.")

    def _scrape_allmedica_requests(self, soup, website_record, custom_config):
        """Inspect Allmedica career links fetched with Requests."""
        logger.info(f"Scraping Allmedica with requests...")
        # Allmedica often redirects to Pracuj.pl or Facebook.
        # For now, we'll just check for direct links on their career page.
        # If it redirects to Pracuj.pl, the orchestrator should ideally handle it by calling PracujScraper.
        
        # Look for links that might lead to job offers
        links = soup.find_all('a', href=True)
        candidate_count = len(links)
        logger.info(f"Allmedica requests scrape: found {candidate_count} candidate links.")
        found_offers_count = 0
        for link in links:
            href = link['href']
            if "pracuj.pl" in href or "facebook.com" in href:
                logger.info(f"Allmedica link to external site detected: {href}. Skipping direct scrape.")
                continue
            
            # Basic check for career-related keywords in link text or URL
            if "kariera" in href.lower() or "praca" in href.lower() or \
               "job" in href.lower() or "rekrutacja" in link.get_text(strip=True).lower():
                
                full_url = urljoin(website_record.url, href)
                # For Allmedica, if it's a direct link on their site, we'd need to visit it
                # and parse. For simplicity, we'll just log it for now.
                logger.info(f"Allmedica potential internal job link: {full_url}")
                # Further logic would involve fetching this page and parsing it.
                # This is a placeholder for more complex logic if Allmedica hosts offers directly.
                
                # Placeholder for adding to DB if a direct offer is found
                # if not self.dedup.is_duplicate(full_url):
                #     self._add_job_offer_to_db(
                #         title=link.get_text(strip=True),
                #         company=website_record.company_name,
                #         location=website_record.location,
                #         url=full_url,
                #         score=self.matcher.calculate_score(link.get_text(strip=True)),
                #         website_id=website_record.id
                #     )
                #     found_offers_count += 1
        logger.info(f"Allmedica requests scrape finished. Candidates {candidate_count}, found {found_offers_count} direct offers (external links logged).")

    def _parse_generic_html(self, soup, website_record, custom_config):
        """Parse job cards using CSS selectors from the source configuration."""
        logger.info(f"Parsing generic HTML for {website_record.company_name}...")
        card_selector = custom_config.get("card_selector")
        title_selector = custom_config.get("title_selector")
        url_selector = custom_config.get("url_selector")
        location_selector = custom_config.get("location_selector")
        found_offers_count = 0

        if not card_selector or not title_selector:
            logger.warning(f"Generic parser: Missing card_selector or title_selector for {website_record.company_name}. Skipping.")
            return

        cards = soup.select(card_selector)
        candidate_count = len(cards)
        logger.info(f"Generic parser: found {candidate_count} candidate cards for {website_record.company_name}.")

        for card in cards:
            try:
                title_el = card.select_one(title_selector)
                url_el = card.select_one(url_selector) if url_selector else card.find('a', href=True)
                loc_el = card.select_one(location_selector) if location_selector else None

                if not title_el or not url_el:
                    continue

                title = title_el.get_text(strip=True)
                offer_url = urljoin(website_record.url, url_el.get('href', '')).split('#')[0]
                location = loc_el.get_text(strip=True) if loc_el else website_record.location
                offer_info = self.extract_offer_info(card, title=title)

                company = self.clean_company_name(None, website_record, offer_info, offer_url)
                location = self.clean_location(location, website_record, offer_info)
                score = self.matcher.calculate_score(self.build_match_text(title, company, location, offer_info), location_text=location)
                if score >= self.matcher.min_match_score and \
                   self.location_filter.is_within_radius(location) and \
                   not self.dedup.is_duplicate(offer_url):
                    self._add_job_offer_to_db(
                        title=title,
                        company=company,
                        location=location,
                        url=offer_url,
                        score=score,
                        website_id=website_record.id,
                        offer_info=offer_info
                    )
                    found_offers_count += 1
            except Exception as e:
                logger.warning(f"Error parsing generic offer card for {website_record.company_name}: {e}")
        logger.info(f"Generic HTML scrape for {website_record.company_name} finished. Candidates {candidate_count}, stored {found_offers_count} offers.")
