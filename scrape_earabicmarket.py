"""
Scraper for Saudi Arabia Business Directory - earabicmarket.com
Uses Playwright (headless Chromium) to bypass bot detection.

Install:
    pip install playwright beautifulsoup4 lxml
    playwright install chromium

Run:
    python scrape_earabicmarket.py
"""

import csv
import json
import re
import sys
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────
START_URL   = "https://www.earabicmarket.com/en/companies/saudi-arabia/all/search?order=05teNvEVbrc%3d"
BASE_URL    = "https://www.earabicmarket.com"
DELAY       = 2.5          # seconds between pages
MAX_PAGES   = 999
OUTPUT_CSV  = "saudi_arabia_companies.csv"
OUTPUT_JSON = "saudi_arabia_companies.json"
SAVE_JSON   = True
DEBUG_HTML  = "debug_page1.html"
DEBUG_SHOT  = "debug_page1.png"
# ─────────────────────────────────────────────────────────────────────────────

FIELDNAMES = [
    "name", "description",
    "city", "country", "address", "phone", "website", "logo_url",
]


def parse_companies(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    companies = []

    # Each company is anchored by <span id="dlCompanies_lblCompany_N" class="company-name">
    for name_span in soup.find_all("span", id=re.compile(r"^dlCompanies_lblCompany_\d+$")):
        m = re.search(r"_(\d+)$", name_span["id"])
        idx = m.group(1)

        name = name_span.get_text(strip=True)
        if not name:
            continue

        def by_id(prefix: str):
            return soup.find(id=f"{prefix}_{idx}")

        description = ""
        desc_el = by_id("dlCompanies_lblDescription")
        if desc_el:
            description = desc_el.get_text(strip=True)

        city = country = ""
        city_el = by_id("dlCompanies_lblCity")
        country_el = by_id("dlCompanies_Label1")
        if city_el:
            city = city_el.get_text(strip=True)
        if country_el:
            country = country_el.get_text(strip=True)

        address = ""
        addr_el = by_id("dlCompanies_lblAddress")
        if addr_el:
            address = addr_el.get_text(strip=True)

        phone = ""
        phone_el = by_id("dlCompanies_lblTelephone")
        if phone_el:
            phone = phone_el.get_text(strip=True)

        website = ""
        site_el = by_id("dlCompanies_lnkWebSite")
        if site_el:
            website = site_el.get_text(strip=True)

        logo_url = ""
        logo_el = by_id("dlCompanies_imgLogo")
        if logo_el and logo_el.get("src"):
            logo_url = urljoin(BASE_URL, logo_el["src"])

        companies.append({
            "name": name, "description": description,
            "city": city, "country": country, "address": address,
            "phone": phone, "website": website, "logo_url": logo_url,
        })

    return companies


def get_next_url(html: str, current_url: str) -> str | None:
    """Find the '>' pagination link, avoiding loops if it points to current page."""
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        if a.get_text(strip=True) == ">":
            next_url = urljoin(BASE_URL, a["href"])
            if next_url != current_url:
                return next_url
    return None


def dump_debug(page, html: str | None = None) -> None:
    try:
        page.screenshot(path=DEBUG_SHOT, full_page=True)
        with open(DEBUG_HTML, "w", encoding="utf-8") as f:
            f.write(html if html is not None else page.content())
        print(f"  [DEBUG] Saved {DEBUG_SHOT} and {DEBUG_HTML}")
    except Exception as e:
        print(f"  [DEBUG] Failed to save debug artifacts: {e}")


def scrape_all() -> list[dict]:
    all_companies: list[dict] = []

    print("Starting scrape of Saudi Arabia Business Directory")
    print(f"  Start URL : {START_URL}")
    print(f"  Max pages : {MAX_PAGES}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        url  = START_URL
        pnum = 1

        while url and pnum <= MAX_PAGES:
            print(f"  Page {pnum:>3}: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(2000)
                page.wait_for_selector("span[id*='dlCompanies_lblCompany_']", timeout=30_000)
            except PWTimeout:
                print("  [WARN] Timeout waiting for content — trying anyway")
                if pnum == 1:
                    dump_debug(page)
            except Exception as e:
                print(f"  [ERROR] {e}")
                if pnum == 1:
                    dump_debug(page)
                break

            html = page.content()
            companies = parse_companies(html)

            if not companies:
                print("  No companies found — end of results.")
                if pnum == 1:
                    dump_debug(page, html)
                break

            all_companies.extend(companies)
            print(f"           → {len(companies)} companies  (total: {len(all_companies)})")

            next_url = get_next_url(html, url)
            pnum += 1
            url = next_url

            if url:
                time.sleep(DELAY)

        browser.close()

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
        print("\nNo companies scraped.")
        sys.exit(1)

    save_csv(companies, OUTPUT_CSV)
    if SAVE_JSON:
        save_json_file(companies, OUTPUT_JSON)

    print(f"\nDone. {len(companies)} companies total.")
