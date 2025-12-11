"""
Website Change Radar (Discord + Web Scraping Project)

What this app does:
- Watches a small list of "sites" you care about.
- For each site, it grabs an important value (price, title, status, version, etc).
- If the value changes since last time, it sends an alert to a Discord channel.

Example sites we include:
1. local_test      -> fake site that always changes (no internet needed)
2. stock_msft      -> Microsoft stock page on Yahoo Finance (previous close price)
3. book_demo       -> Book price on "Books to Scrape" demo store
4. blog_python     -> Latest post title from the Python blog
5. status_github   -> Overall status text from GitHub status page
6. nasa_apod       -> Title + image from NASA Astronomy Picture of the Day
7. python_release  -> First "Python 3.x.y" version from Python downloads page
"""

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# =====================================
# CONFIGURATION
# =====================================

DISCORD_WEBHOOK_URL = "DISCORD_WEBHOOK_URL"

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "radar_state.json"

USER_AGENT = "WebsiteChangeRadarStudentProject/1.0"

# value_type:
#   - "price"       -> grab a $ or £ style price from the text
#   - "stock_price" -> special logic for stock pages
#   - "title"       -> use the page <title> text
#   - "text"        -> short text snippet
#   - "version"     -> grab a version like "Python 3.13.2"
SITES = [
    {
        "id": "local_test",
        "url": "LOCAL_TEST",
        "description": "Built in test that always changes so you can see Discord alerts",
        "css_selector": None,
        "normalize_whitespace": True,
        "value_type": "text",
    },
    {
        "id": "stock_msft",
        "url": "https://finance.yahoo.com/quote/MSFT",
        "description": "Microsoft stock quote page on Yahoo Finance (previous close price)",
        "css_selector": None,          # use full text, special logic below
        "normalize_whitespace": True,
        "value_type": "stock_price",
    },
    {
        "id": "book_demo",
        "url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        "description": "Demo book price from Books to Scrape",
        "css_selector": ".product_main .price_color",
        "normalize_whitespace": True,
        "value_type": "price",
    },
    {
        # NEW: grab the *latest post title*, not just "Python Insider"
        "id": "blog_python",
        "url": "https://blog.python.org/",
        "description": "Latest post title from Python blog front page",
        # Python blog posts usually use classes like post-title / entry-title
        "css_selector": ".post-title a, .post-title, .entry-title a, .entry-title",
        "normalize_whitespace": True,
        "value_type": "text",
    },
    {
        # NEW: grab the big status line like "All Systems Operational"
        "id": "status_github",
        "url": "https://www.githubstatus.com/",
        "description": "Overall status from GitHub status page",
        # GitHub status uses a Statuspage layout; these selectors catch the main banner text
        "css_selector": ".page-status .status, .page-status .status-text, .status.font-large",
        "normalize_whitespace": True,
        "value_type": "text",
    },
    {
        "id": "nasa_apod",
        "url": "https://apod.nasa.gov/apod/astropix.html",
        "description": "Title from NASA Astronomy Picture of the Day",
        "css_selector": None,
        "normalize_whitespace": True,
        "value_type": "title",
    },
    {
        "id": "python_release",
        "url": "https://www.python.org/downloads/",
        "description": "First release version from Python downloads page",
        "css_selector": None,
        "normalize_whitespace": True,
        "value_type": "version",
    },
]


# =====================================
# DATA CLASS
# =====================================

@dataclass
class SiteConfig:
    id: str
    url: str
    description: str
    css_selector: Optional[str] = None
    normalize_whitespace: bool = True
    value_type: str = "text"


def to_site_configs(raw_sites: List[dict]) -> List[SiteConfig]:
    sites: List[SiteConfig] = []
    for idx, entry in enumerate(raw_sites):
        try:
            sites.append(
                SiteConfig(
                    id=entry["id"],
                    url=entry["url"],
                    description=entry.get("description", entry["id"]),
                    css_selector=entry.get("css_selector"),
                    normalize_whitespace=entry.get("normalize_whitespace", True),
                    value_type=entry.get("value_type", "text"),
                )
            )
        except KeyError as exc:
            print(f"[WARN] Skipping site entry {idx}: missing key {exc}")
    return sites


# =====================================
# STATE HELPERS
# =====================================

def load_state(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[WARN] Could not read {path}: {exc}", file=sys.stderr)
        return {}


def save_state(path: Path, data: Dict[str, Dict[str, str]]) -> None:
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
    except Exception as exc:
        print(f"[ERROR] Could not write {path}: {exc}", file=sys.stderr)


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


# =====================================
# FETCHING
# =====================================

def fetch_content(site: SiteConfig) -> str:
    if site.url == "LOCAL_TEST":
        now = time.time()
        text = f"local test value at {now}"
        print(f"[INFO] Using LOCAL_TEST content: {text}")
        return text

    print(f"[INFO] Fetching {site.id} from {site.url}")
    resp = requests.get(
        site.url,
        timeout=30,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    if site.value_type == "title":
        if soup.title is not None:
            text = soup.title.get_text(" ", strip=True)
        else:
            text = site.description
    else:
        if site.css_selector:
            nodes = soup.select(site.css_selector)
            if not nodes:
                raise RuntimeError(
                    f"CSS selector '{site.css_selector}' found nothing on {site.url}"
                )
            text = "\n".join(n.get_text(separator=" ", strip=True) for n in nodes)
        else:
            text = soup.get_text(separator=" ", strip=True)

    if site.normalize_whitespace:
        text = " ".join(text.split())

    return text


# =====================================
# VALUE EXTRACTION
# =====================================

PRICE_PATTERN = re.compile(r"[£$]\s*([0-9][0-9,]*(?:\.[0-9]{2})?)")
STOCK_PREV_CLOSE_PATTERN = re.compile(
    r"Previous\s+close\s+([0-9][0-9,]*(?:\.[0-9]{2})?)", re.IGNORECASE
)
PYTHON_VERSION_PATTERN = re.compile(r"Python\s+3\.\d+\.\d+")


def extract_stock_price_value(text: str) -> str:
    m = STOCK_PREV_CLOSE_PATTERN.search(text)
    if m:
        number = m.group(1).replace(" ", "")
        return f"${number}"
    m2 = PRICE_PATTERN.search(text)
    if m2:
        currency_symbol = text[m2.start()]
        number_part = m2.group(1).replace(" ", "")
        return f"{currency_symbol}{number_part}"
    return text[:160]


def extract_value(site: SiteConfig, text: str) -> str:
    if site.value_type == "stock_price":
        return extract_stock_price_value(text)

    if site.value_type == "price":
        match = PRICE_PATTERN.search(text)
        if match:
            currency_symbol = text[match.start()]
            number_part = match.group(1).replace(" ", "")
            return f"{currency_symbol}{number_part}"
        return text[:160]

    if site.value_type == "version":
        m = PYTHON_VERSION_PATTERN.search(text)
        if m:
            return m.group(0)
        return text[:160]

    # "title" and "text" use whatever text we already selected
    return text[:160]


def parse_number_from_value(value: str) -> Optional[float]:
    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]{2})?)", value)
    if not m:
        return None
    number_str = m.group(1).replace(",", "")
    try:
        return float(number_str)
    except ValueError:
        return None


def describe_difference(old_value: str, new_value: str) -> str:
    old_num = parse_number_from_value(old_value)
    new_num = parse_number_from_value(new_value)
    if old_num is None or new_num is None:
        return ""
    diff = new_num - old_num
    if diff > 0:
        arrow = "▲"
    elif diff < 0:
        arrow = "▼"
    else:
        arrow = "▶"
    return f"{arrow} {diff:+.2f}"


# =====================================
# NASA APOD IMAGE
# =====================================

def get_nasa_image_url(site: SiteConfig) -> Optional[str]:
    try:
        resp = requests.get(
            site.url,
            timeout=30,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"[WARN] Could not fetch NASA image: {exc}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    img = soup.find("img")
    if not img or not img.get("src"):
        return None
    src = img["src"]
    return urljoin(site.url, src)


# =====================================
# DISCORD ALERTS
# =====================================

def send_discord_message(message: str) -> None:
    if not DISCORD_WEBHOOK_URL or "PASTE_YOUR_DISCORD_WEBHOOK_URL_HERE" in DISCORD_WEBHOOK_URL:
        print("[WARN] Discord webhook not set. Set DISCORD_WEBHOOK_URL at the top.")
        return

    try:
        payload = {"content": message}
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code >= 300:
            print(f"[WARN] Discord webhook failed: {resp.status_code} {resp.text}")
    except Exception as exc:
        print(f"[WARN] Discord webhook exception: {exc}")


def maybe_append_image_line(site: SiteConfig, message: str) -> str:
    if site.id != "nasa_apod":
        return message
    img_url = get_nasa_image_url(site)
    if img_url:
        message += f"\nImage: {img_url}"
    return message


def alert_baseline(site: SiteConfig, value: str) -> None:
    message = (
        "🛰️ **Website Change Radar started tracking**\n"
        f"Site: **{site.description}**\n"
        f"URL: {site.url}\n"
        f"Current value: **{value}**"
    )
    message = maybe_append_image_line(site, message)
    print(f"[INFO] Baseline set for {site.id}: {value}")
    send_discord_message(message)


def alert_change(site: SiteConfig, old_value: str, new_value: str) -> None:
    diff_str = describe_difference(old_value, new_value)
    message = (
        "🔔 **Website Change Radar**\n"
        f"Site: **{site.description}**\n"
        f"URL: {site.url}\n"
        f"Previous: **{old_value}**\n"
        f"Now: **{new_value}**"
    )
    if diff_str:
        message += f"\nChange: **{diff_str}**"
    message = maybe_append_image_line(site, message)
    print(f"[ALERT] {site.id} changed from {old_value} to {new_value}")
    send_discord_message(message)


# =====================================
# MAIN
# =====================================

def check_sites():
    sites = to_site_configs(SITES)
    if not sites:
        print("[INFO] No sites configured in SITES list.")
        return

    state = load_state(STATE_FILE)
    any_changes = False

    for site in sites:
        try:
            raw_text = fetch_content(site)
        except Exception as exc:
            print(f"[ERROR] Failed to fetch {site.id}: {exc}")
            continue

        value = extract_value(site, raw_text)
        new_hash = compute_hash(value)
        previous = state.get(site.id)
        previous_hash = previous["hash"] if previous else None
        previous_value = previous.get("value") if previous else None

        if previous_hash is None:
            state[site.id] = {"hash": new_hash, "value": value}
            alert_baseline(site, value)
            continue

        if new_hash != previous_hash:
            any_changes = True
            alert_change(site, previous_value, value)
            state[site.id]["hash"] = new_hash
            state[site.id]["value"] = value
        else:
            print(f"[OK] No change for {site.id} (value still {value})")

    save_state(STATE_FILE, state)

    if any_changes:
        print("[INFO] Changes detected and state saved.")
    else:
        print("[INFO] No changes detected, state saved.")


def main():
    check_sites()


if __name__ == "__main__":
    main()
