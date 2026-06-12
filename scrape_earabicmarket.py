"""
Scraper for Saudi Arabia Business Directory - earabicmarket.com
Start URL: https://www.earabicmarket.com/en/company/saudi-arabia/all
           (redirects to /en/companies/saudi-arabia/all)

Each page lists 10 companies. Pagination follows the pre-signed '>' next link.

Output: saudi_arabia_companies.csv  +  saudi_arabia_companies.json

Usage:
    pip install requests beautifulsoup4 lxml
    python scrape_earabicmarket.py
"""

import csv
import json
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────
START_URL   = "https://www.earabicmarket.com/en/company/saudi-arabia/all"
BASE_URL    = "https://www.earabicmarket.com"
DELAY       = 2.0          # polite delay between pages (seconds)
MAX_PAGES   = 999          # safety cap; set to e.g. 2 for a quick test
OUTPUT_CSV  = "saudi_arabia_companies.csv"
OUTPUT_JSON = "saudi_arabia_companies.json"
SAVE_JSON   = True
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

FIELDNAMES = [
    "name", "profile_url", "description",
    "city", "country", "address", "phone", "website", "logo_url",
]

# Nav/footer slugs to exclude when matching company profile links
NAV_SLUGS = {
    "companies", "products", "premium-companies", "earabicmarket-membership",
    "site-map", "aboutus", "terms-of-use", "privacy-policy", "contactus",
    "subscribe-email-updates", "services", "en", "search",
}


def get_page(session: requests.Session, url: str) -> BeautifulSoup | None:
    """Fetch a URL and return parsed HTML, or None on failure."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as e:
        print(f"  [ERROR] {url}: {e}", file=sys.stderr)
        return None


def parse_companies(soup: BeautifulSoup) -> list[dict]:
    """
    Each company block in the HTML looks like:

        <a href="/en/<slug>">
          <img src=".../Companies/Logo/..." title="Company Name">
        </a>
        <strong><a href="/en/<slug>">Company Name</a></strong>
        <img src=".../PremiumEcommerceTag.gif">
        Description text...
        <img src=".../Flags/sa.gif" alt="City (Saudi Arabia)">City (Saudi Arabia)
        <img src=".../map-marker..."> Address text
        <img src=".../phone..."> Phone number
        <img src=".../globe..."> <a>website</a>

    Anchor: company logo <img title="Name"> inside <a href="/en/slug">.
    """
    companies = []

    for logo_img in soup.find_all("img", src=re.compile(r"/Companies/Logo/"), title=True):
        name = logo_img.get("title", "").strip()
        if not name:
            continue

        logo_anchor = logo_img.find_parent("a", href=re.compile(r"^/en/[^/]+$"))
        if not logo_anchor:
            continue

        slug = logo_anchor["href"].strip("/").split("/")[-1]
        if slug in NAV_SLUGS:
            continue

        profile_url = urljoin(BASE_URL, logo_anchor["href"])
        logo_url    = urljoin(BASE_URL, logo_img["src"])

        # Enclosing container for this company's block
        container = logo_anchor.find_parent("td") or logo_anchor.find_parent("div")

        description = city = country = address = phone = website = ""

        if container:
            # Description: first substantial text run that isn't the company name
            for text_node in container.find_all(string=True):
                text = text_node.strip()
                if len(text) > 40 and text != name and "Add your company" not in text:
                    description = text
                    break

            # Flag image → "City (Country)"
            flag = container.find("img", src=re.compile(r"/Images/Flags/"))
            if flag:
                loc = flag.get("alt", "")
                m = re.match(r"^(.+?)\s*\((.+?)\)$", loc)
                if m:
                    city, country = m.group(1).strip(), m.group(2).strip()
                else:
                    city = loc.strip()

            # Icon images followed by plain-text or link siblings
            for img in container.find_all("img", src=True):
                src = img["src"]
                raw = img.next_sibling
                next_text = raw.strip() if isinstance(raw, str) else ""

                if "map-marker" in src and not address:
                    address = next_text

                elif "phone" in src and not phone:
                    phone = next_text

                elif "globe" in src and not website:
                    a_tag = img.find_next_sibling("a")
                    if a_tag:
                        website = a_tag.get_text(strip=True) or a_tag.get("href", "")
                    else:
                        website = next_text

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


def get_next_url(soup: BeautifulSoup) -> str | None:
    """
    Follow the '>' pagination link. The site uses pre-signed qry= tokens
    baked into each page, so we must use the href exactly as found.
    """
    for a in soup.find_all("a", href=True):
        if a.get_text(strip=True) == ">":
            return urljoin(BASE_URL, a["href"])
    return None


def scrape_all() -> list[dict]:
    all_companies: list[dict] = []
    session = requests.Session()
    # Seed cookies by visiting the homepage first (avoids some bot checks)
    session.get(BASE_URL, headers=HEADERS, timeout=30)
    time.sleep(1)

    url  = START_URL
    page = 1

    print("Starting scrape of Saudi Arabia Business Directory")
    print(f"  Start URL : {START_URL}")
    print(f"  Max pages : {MAX_PAGES}")
    print(f"  Delay     : {DELAY}s\n")

    while url and page <= MAX_PAGES:
        print(f"  Page {page:>3}: {url}")
        soup = get_page(session, url)
        if soup is None:
            print("  Stopping: fetch error.")
            break

        companies = parse_companies(soup)
        if not companies:
            print("  No companies parsed — end of results or unexpected HTML.")
            break

        all_companies.extend(companies)
        print(f"           → {len(companies)} companies  (total: {len(all_companies)})")

        url = get_next_url(soup)
        page += 1
        if url:
            time.sleep(DELAY)

    return all_companies


def save_csv(companies: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(companies)
    print(f"\n✓ CSV  → {path}  ({len(companies)} rows)")


def save_json_file(companies: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(companies, f, ensure_ascii=False, indent=2)
    print(f"✓ JSON → {path}")


if __name__ == "__main__":
    companies = scrape_all()

    if not companies:
        print("\nNo companies scraped. Check connectivity or site structure.")
        sys.exit(1)

    save_csv(companies, OUTPUT_CSV)
    if SAVE_JSON:
        save_json_file(companies, OUTPUT_JSON)

    print(f"\nDone. {len(companies)} companies total.")
