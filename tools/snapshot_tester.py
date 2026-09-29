"""Manual utility for checking parsers against saved HTML pages."""

import os
import sys
import re
import hashlib
from bs4 import BeautifulSoup
# Ensure project package root (apjobs/) is on sys.path so relative imports work
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.profile_matcher import ProfileMatcher
from config.settings import settings

BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..')
SNAP_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'zapisane_strony'))

matcher = ProfileMatcher()
seen_hashes = set()

def hash_url(u):
    """Return the same URL digest used by the database deduplicator."""
    return hashlib.sha1(u.encode('utf-8')).hexdigest()


def load_html(name):
    """Read a saved HTML snapshot or report that the fixture is missing."""
    path = os.path.join(SNAP_DIR, name)
    if not os.path.exists(path):
        print(f"MISSING: {name}")
        return None
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def test_su():
    """Inspect saved University Hospital pages with the current offer rules."""
    names = ['szpital_uniwersytecki_offers_page.txt', 'szpital_uniwersyteck_job_offeri.txt']
    total_candidates = 0
    matched = 0
    for name in names:
        html = load_html(name)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        anchors = soup.select('a.btn-article[itemprop="url"], a[href*="/kariera/oferty-pracy/"]')
        total_candidates += len(anchors)
        for a in anchors:
            href = a.get('href')
            title_elem = a.select_one('h3.btn-article__title, h3[itemprop="name"]')
            if title_elem:
                title = title_elem.get_text(' ', strip=True)
            else:
                title_raw = a.get_text(' ', strip=True)
                title = re.sub(r'Data publikacji:.*$', '', title_raw, flags=re.I).replace('Więcej', '').strip()
                title = ' '.join(title.split())
            if not title or len(title) < 5:
                continue
            url = href if href.startswith('http') else ('https://www.su.krakow.pl' + href)
            h = hash_url(url)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            score = matcher.calculate_score(title)
            if score >= matcher.min_match_score:
                matched += 1
    print(f"SU: candidates={total_candidates}, matched_by_score={matched}")


def test_erecruiter():
    """Inspect saved eRecruiter pages with the current offer rules."""
    name = 'synevo_with_pagination.txt'
    html = load_html(name)
    if not html:
        print('ERecruiter: snapshot missing')
        return
    soup = BeautifulSoup(html, 'html.parser')
    # try to find cfg
    cfg = None
    for s in soup.find_all('script', src=True):
        m = re.search(r'cfg=([a-zA-Z0-9\-]+)', s['src'])
        if m:
            cfg = m.group(1)
            break
    offer_rows = soup.select("tr[skkresult='offer']") or [row for row in soup.select('tr[jobofferid]') if row.get('offerid') or row.get('jobofferid')]
    total = 0
    matched = 0
    for row in offer_rows:
        title_el = row.select_one('td.skk_positionName a, td.skk_positionName')
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        oid = row.get('offerid') or row.get('jobofferid')
        if oid and cfg:
            com_id = row.get('comid') or ''
            ejo_id = row.get('externaljobofferid') or ''
            ejor_id = row.get('externaljobofferregionid') or ''
            offer_url = f"https://skk.erecruiter.pl/Offer.aspx?oid={oid}&cfg={cfg}&ejoId={ejo_id}&ejorId={ejor_id}&comId={com_id}"
        else:
            link_el = row.find('a', href=True)
            if not link_el:
                continue
            offer_url = link_el['href'] if link_el['href'].startswith('http') else urljoin('https://skk.erecruiter.pl/', link_el['href'])
        total += 1
        h = hash_url(offer_url)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        score = matcher.calculate_score(title)
        if score >= matcher.min_match_score:
            matched += 1
    print(f"ERecruiter: candidates={total}, matched_by_score={matched}")


from urllib.parse import urljoin


def test_pracuj():
    """Inspect saved Pracuj.pl pages with the current offer rules."""
    names = ['pracuj_pl.txt']
    total = 0
    matched = 0
    for name in names:
        html = load_html(name)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        offers = soup.select('div[data-test="default-offer"], div.offer-tile_b18pwp01, div[data-test*="offer"]')
        total += len(offers)
        for off in offers:
            a = off.select_one('a[data-test="link-offer-title"]') or off.select_one('a[data-test="link-offer"]') or off.select_one('h2[data-test="offer-title"] a')
            if not a:
                continue
            title = a.get_text(' ', strip=True)
            url = a.get('href')
            if not url:
                continue
            h = hash_url(url)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            score = matcher.calculate_score(title)
            print(f"Pracuj title: '{title}' -> score={score}")
            if score >= matcher.min_match_score:
                matched += 1
    print(f"Pracuj: candidates={total}, matched_by_score={matched}")


def test_olx():
    """Inspect saved OLX pages with the current offer rules."""
    names = ['olx_offers_listing.txt', 'olx_offer_example.txt', 'oferty_pracy_rejestratorka_krakow.txt']
    total = 0
    matched = 0
    for name in names:
        html = load_html(name)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        # OLX job tiles have anchors with href like '/oferta/...', title often in an h4 inside
        for a in soup.select('a[href*="/oferta/"]'):
            title_el = a.select_one('h4, h3')
            title = title_el.get_text(' ', strip=True) if title_el else a.get_text(' ', strip=True)
            href = a.get('href')
            if not title or len(title) < 5 or not href:
                continue
            total += 1
            url = href if href.startswith('http') else urljoin('https://www.olx.pl', href)
            h = hash_url(url)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            score = matcher.calculate_score(title)
            if score >= matcher.min_match_score:
                matched += 1
    print(f"OLX(generic): candidates={total}, matched_by_score={matched}")


if __name__ == '__main__':
    print('Running snapshot tests (score threshold={})'.format(settings.MIN_MATCH_SCORE))
    test_su()
    test_erecruiter()
    test_pracuj()
    test_olx()
