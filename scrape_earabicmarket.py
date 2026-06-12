"""
Scraper for Saudi Arabia Business Directory on earabicmarket.com
URL: https://www.earabicmarket.com/en/company/saudi-arabia/all

Scrapes all companies and saves to CSV (and optionally JSON).
Respects the site by adding delays between requests.

Usage:
    pip install requests beautifulsoup4
    python scrape_earabicmarket.py

Output:
    saudi_arabia_companies.csv
    saudi_arabia_companies.json  (optional, set SAVE_JSON = True)
"""

import requests
from bs4 import BeautifulSoup
import csv
import json
import time
import re
import sys
from urllib.parse import urljoin

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL    = "https://www.earabicmarket.com"
START_URL   = "https://www.earabicmarket.com/en/company/saudi-arabia/all"
DELAY       = 1.5          # seconds between page requests (be polite)
MAX_PAGES   = 999          # safety cap; set lower to test (e.g. 2)
OUTPUT_CSV  = "saudi_arabia_companies.csv"
OUTPUT_JSON = "saudi_arabia_companies.json"
SAVE_JSON   = True         # also save a .json file
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

FIELDNAMES = [
    "name",
    "profile_url",
    "description",
    "city",
    "country",
    "address",
    "phone",
    "website",
    "logo_url",
]


def get_page(session: requests.Session, url: str) -> BeautifulSoup | None:
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [ERROR] Failed to fetch {url}: {e}", file=sys.stderr)
        return None


def parse_companies(soup: BeautifulSoup) -> list[dict]:
    """Extract all company cards from a single directory page."""
    companies = []

    # Each company sits inside an <a> or block identified by having a logo img
    # and several small-icon images for location / phone / website.
    # The pattern: <table> or <div> containing the company block – parse broadly.

    # Company name links all follow href like /en/<slug>
    name_links = soup.select("a[href^='/en/']")

    # Filter to actual company profile links (exclude nav/footer links)
    company_blocks = []
    for link in name_links:
        href = link.get("href", "")
        # Company pages: /en/<username>  (no sub-paths like /en/companies/...)
        parts = href.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "en" and parts[1] not in {
            "companies", "products", "premium-companies", "earabicmarket-membership",
            "site-map", "aboutus", "terms-of-use", "privacy-policy", "contactus",
            "subscribe-email-updates", "services",
        }:
            company_blocks.append(link)

    for link in company_blocks:
        name = link.get_text(strip=True)
        if not name:
            continue

        profile_url = urljoin(BASE_URL, link["href"])

        # Walk up to the enclosing company card container
        container = link.find_parent("td") or link.find_parent("div") or link.parent

        # Logo
        logo_url = ""
        logo_img = container.find("img", src=re.compile(r"/Companies/Logo/")) if container else None
        if logo_img:
            logo_url = urljoin(BASE_URL, logo_img["src"])

        # Description – longest text sibling that isn't an icon alt text
        description = ""
        if container:
            texts = [
                t.strip()
                for t in container.stripped_strings
                if len(t.strip()) > 40 and t.strip() != name
            ]
            if texts:
                description = texts[0]

        # Location (city + country come from flag img alt text pattern "City (Country)")
        city = country = ""
        if container:
            flag_img = container.find("img", src=re.compile(r"/Images/Flags/"))
            if flag_img:
                loc_text = flag_img.get("alt", "")
                m = re.match(r"^(.+?)\s*\((.+?)\)$", loc_text)
                if m:
                    city, country = m.group(1).strip(), m.group(2).strip()
                else:
                    city = loc_text.strip()

        # Address, phone, website – identified by their small icon images
        address = phone = website = ""
        if container:
            for img in container.find_all("img", src=True):
                src = img["src"]
                # The text immediately after the icon image
                next_node = img.find_next_sibling(string=True) or (
                    img.parent.get_text(separator=" ", strip=True) if img.parent else ""
                )
                sibling_text = (img.next_sibling or "")
                if hasattr(sibling_text, "strip"):
                    sibling_text = sibling_text.strip()
                else:
                    sibling_text = ""

                if "map-marker" in src and not address:
                    address = sibling_text
                elif "phone" in src and not phone:
                    phone = sibling_text
                elif "globe" in src and not website:
                    # website may be a link
                    a_tag = img.find_next_sibling("a")
                    if a_tag:
                        website = a_tag.get_text(strip=True) or a_tag.get("href", "")
                    else:
                        website = sibling_text

        companies.append({
            "name":        name,
            "profile_url": profile_url,
            "description": description,
            "city":        city,
            "country":     country,
            "address":     address,
            "phone":       phone,
            "website":     website,
            "logo_url":    logo_url,
        })

    return companies


def get_next_page_url(soup: BeautifulSoup, current_page: int) -> str | None:
    """Return the URL of the next page, or None if we're on the last page."""
    next_page = current_page + 1
    # Look for a pagination link with text matching next_page number
    for a in soup.select("a[href*='page=']"):
        href = a.get("href", "")
        if f"page={next_page}" in href:
            return urljoin(BASE_URL, href)
    return None


def scrape_all() -> list[dict]:
    all_companies: list[dict] = []
    session = requests.Session()
    url = START_URL
    page = 1

    print(f"Starting scrape of Saudi Arabia Business Directory")
    print(f"  Base URL : {START_URL}")
    print(f"  Max pages: {MAX_PAGES}")
    print(f"  Delay    : {DELAY}s per page\n")

    while url and page <= MAX_PAGES:
        print(f"  Fetching page {page}: {url}")
        soup = get_page(session, url)
        if soup is None:
            print(f"  Stopping due to fetch error on page {page}.")
            break

        companies = parse_companies(soup)
        if not companies:
            print(f"  No companies found on page {page}. Stopping.")
            break

        all_companies.extend(companies)
        print(f"  → {len(companies)} companies found (total so far: {len(all_companies)})")

        url = get_next_page_url(soup, page)
        page += 1

        if url:
            time.sleep(DELAY)

    return all_companies


def save_csv(companies: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(companies)
    print(f"\n✓ CSV saved → {path}  ({len(companies)} rows)")


def save_json_file(companies: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(companies, f, ensure_ascii=False, indent=2)
    print(f"✓ JSON saved → {path}")


if __name__ == "__main__":
    companies = scrape_all()

    if not companies:
        print("\nNo companies scraped. Check your internet connection or the site structure.")
        sys.exit(1)

    save_csv(companies, OUTPUT_CSV)
    if SAVE_JSON:
        save_json_file(companies, OUTPUT_JSON)

    print(f"\nDone. {len(companies)} companies scraped in total.")
