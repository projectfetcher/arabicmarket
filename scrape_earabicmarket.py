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
START_URL   = "https://www.earabicmarket.com/en/company/saudi-arabia/all"
BASE_URL    = "https://www.earabicmarket.com"
DELAY       = 2.5          # seconds between pages
MAX_PAGES   = 999
OUTPUT_CSV  = "saudi_arabia_companies.csv"
OUTPUT_JSON = "saudi_arabia_companies.json"
SAVE_JSON   = True
# ─────────────────────────────────────────────────────────────────────────────

FIELDNAMES = [
    "name", "profile_url", "description",
    "city", "country", "address", "phone", "website", "logo_url",
]

NAV_SLUGS = {
    "companies", "products", "premium-companies", "earabicmarket-membership",
    "site-map", "aboutus", "terms-of-use", "privacy-policy", "contactus",
    "subscribe-email-updates", "services", "en", "search",
}


def parse_companies(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
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

        container = logo_anchor.find_parent("td") or logo_anchor.find_parent("div")
        description = city = country = address = phone = website = ""

        if container:
            for text_node in container.find_all(string=True):
                text = text_node.strip()
                if len(text) > 40 and text != name and "Add your company" not in text:
                    description = text
                    break

            flag = container.find("img", src=re.compile(r"/Images/Flags/"))
            if flag:
                loc = flag.get("alt", "")
                m = re.match(r"^(.+?)\s*\((.+?)\)$", loc)
                if m:
                    city, country = m.group(1).strip(), m.group(2).strip()
                else:
                    city = loc.strip()

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
                    website = (a_tag.get_text(strip=True) if a_tag else next_text)

        companies.append({
            "name": name, "profile_url": profile_url, "description": description,
            "city": city, "country": country, "address": address,
            "phone": phone, "website": website, "logo_url": logo_url,
        })

    return companies


def get_next_url(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        if a.get_text(strip=True) == ">":
            return urljoin(BASE_URL, a["href"])
    return None


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
        # Hide webdriver flag
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        url  = START_URL
        pnum = 1

        while url and pnum <= MAX_PAGES:
            print(f"  Page {pnum:>3}: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                # Wait for at least one company logo to appear
                page.wait_for_selector("img[src*='/Companies/Logo/']", timeout=15_000)
            except PWTimeout:
                print("  [WARN] Timeout waiting for content — trying anyway")
            except Exception as e:
                print(f"  [ERROR] {e}")
                break

            html = page.content()
            companies = parse_companies(html)

            if not companies:
                print("  No companies found — end of results.")
                break

            all_companies.extend(companies)
            print(f"           → {len(companies)} companies  (total: {len(all_companies)})")

            next_url = get_next_url(html)
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
