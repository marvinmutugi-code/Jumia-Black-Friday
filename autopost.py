"""
autopost.py

- Scrapes Jumia (flash-sales, deals, categories)
- Adds affiliate code to product links
- Shortens links with Bitly (v4)
- Posts multiple deals to Telegram with "🛒 BUY NOW ➜ <shortlink>"
- Scheduler runs every 60 minutes. Has /test and /trigger endpoints.

Environment variables (recommended to set in Render):
  TELEGRAM_TOKEN
  TELEGRAM_CHAT_ID
  AFF_CODE
  BITLY_TOKEN

This script will fall back to embedded defaults if env vars are not present.
Rotate secrets after deployment if they have been exposed.
"""

import os
import time
import logging
import requests
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup
from datetime import datetime
from hashlib import sha256

# -----------------------
# CONFIG & SECRETS
# -----------------------
# Defaults here come from what you've used earlier; prefer setting via environment
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1003285979057")
AFF_CODE = os.getenv("AFF_CODE", "5bed0bdf3d1ca")
BITLY_TOKEN = os.getenv("BITLY_TOKEN", "77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b")

# Core settings
JUMIA_BASE = "https://www.jumia.co.ke"
FLASH_SALES = "https://www.jumia.co.ke/flash-sales/"
DEALS_PAGE = "https://www.jumia.co.ke/deals/"

# categories to scan (more can be added)
CATEGORIES = [
    "phones-tablets",
    "tv-video",
    "home-office",
    "computing",
    "health-beauty",
    "fashion",
    "groceries",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

POST_LIMIT_PER_RUN = 25         # max items posted per run
ITEMS_PER_CATEGORY = 6          # how many items to take from each category
SCHED_INTERVAL_MINUTES = 60     # fixed schedule

# -----------------------
# LOGGING
# -----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("autopost")

# -----------------------
# FLASK APP & SCHEDULER
# -----------------------
app = Flask(__name__)
scheduler = BackgroundScheduler()

# Simple memory of posted deals (hashes) to avoid reposting on restart within process
# For persistence across restarts you could save to a file or DB (not implemented here)
posted_hashes = set()


# -----------------------
# UTILITIES
# -----------------------
def make_affiliate_link(url: str) -> str:
    """
    Insert affiliate parameter `aff_id` into URL query (keeps existing query params).
    """
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        qs["aff_id"] = [AFF_CODE]
        new_q = urlencode(qs, doseq=True)
        new_parsed = parsed._replace(query=new_q)
        new_url = urlunparse(new_parsed)
        return new_url
    except Exception as e:
        logger.exception("make_affiliate_link error: %s", e)
        return url


def shorten_with_bitly(long_url: str) -> str:
    """
    Shorten using Bitly v4 API. Returns shortened url or original on failure.
    """
    if not BITLY_TOKEN:
        logger.warning("No BITLY_TOKEN configured; skipping shortening.")
        return long_url

    endpoint = "https://api-ssl.bitly.com/v4/shorten"
    headers = {
        "Authorization": f"Bearer {BITLY_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"long_url": long_url}
    try:
        r = requests.post(endpoint, json=payload, headers=headers, timeout=12)
        if r.status_code in (200, 201):
            data = r.json()
            short = data.get("link")
            if short:
                return short
            logger.warning("Bitly response missing 'link' field: %s", data)
            return long_url
        else:
            logger.warning("Bitly failed (%s): %s", r.status_code, r.text)
            return long_url
    except Exception as e:
        logger.exception("Bitly request exception: %s", e)
        return long_url


def send_telegram(text: str, disable_preview: bool = True) -> bool:
    """
    Send a message to Telegram. Returns True on success.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview
    }
    try:
        r = requests.post(url, data=payload, timeout=12)
        logger.debug("Telegram response: %s", r.text)
        if r.status_code == 200:
            return True
        else:
            logger.warning("Telegram returned %s: %s", r.status_code, r.text)
            return False
    except Exception as e:
        logger.exception("Telegram send exception: %s", e)
        return False


def dedupe_by_url(items):
    seen = set()
    out = []
    for it in items:
        u = it.get("url")
        if not u:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(it)
    return out


def item_hash(it):
    s = (it.get("url","") + "|" + it.get("price","") + "|" + it.get("title","")).encode("utf-8")
    return sha256(s).hexdigest()


# -----------------------
# SCRAPERS
# -----------------------
def parse_products_from_soup(soup):
    """
    Generic parser for product cards found on Jumia listing pages.
    Returns list of dicts: {'title','price','old_price'(optional),'url','discount_pct'(optional)}
    """
    items = []
    # Jumia uses <article class="prd ..."> for product cards in many pages
    for card in soup.select("article.prd, div.sku, div.c-prd"):
        try:
            # name/title
            title_tag = card.select_one("h3.name, h3.title, h2.title, a.name")
            if title_tag:
                title = title_tag.get_text(strip=True)
            else:
                # fallback
                title = (card.get("aria-label") or "").strip()

            # price
            price_tag = card.select_one(".prc, span.price, .price, .prc-w, .old")
            price = price_tag.get_text(strip=True) if price_tag else ""

            # old price (to compute discount)
            old_tag = card.select_one(".old, .old-prc, span.old")
            old_price = old_tag.get_text(strip=True) if old_tag else None

            # discount percent if present
            discount_tag = card.select_one(".bdg._dsct, .discount, .prdPopUp .discount")
            discount = None
            if discount_tag:
                discount = discount_tag.get_text(strip=True)

            # url
            a = card.select_one("a")
            href = a["href"] if a and a.get("href") else None
            if href and href.startswith("/"):
                href = JUMIA_BASE + href
            elif href and href.startswith("http"):
                pass
            else:
                # skip if no usable URL
                href = None

            if not title or not href:
                continue

            items.append({
                "title": title,
                "price": price,
                "old_price": old_price,
                "discount": discount,
                "url": href
            })
        except Exception:
            # keep parser robust; continue on any product parse error
            continue

    return items


def fetch_listing(url, limit=20):
    """
    Fetch a listing page and return parsed products (limit controls number to return).
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            logger.warning("Failed to fetch %s: %s", url, r.status_code)
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        items = parse_products_from_soup(soup)
        return items[:limit]
    except Exception as e:
        logger.exception("fetch_listing error for %s: %s", url, e)
        return []


def fetch_deals():
    """
    Aggregate deals across flash sales, deals, and top categories.
    Prioritize items with discounts (where old_price exists or discount present).
    Returns a list of items sorted by likely attractiveness.
    """
    results = []

    logger.info("Scraping flash sales...")
    results.extend(fetch_listing(FLASH_SALES, limit=12))

    logger.info("Scraping deals page...")
    results.extend(fetch_listing(DEALS_PAGE, limit=12))

    for cat in CATEGORIES:
        cat_url = f"{JUMIA_BASE}/{cat}/"
        logger.info("Scraping category: %s", cat)
        results.extend(fetch_listing(cat_url, limit=ITEMS_PER_CATEGORY))

    # dedupe by URL
    unique = dedupe_by_url(results)

    # Score items: use discount presence, then old_price present, else 0
    def score(it):
        s = 0
        if it.get("discount"):
            # extract numeric percent if possible
            try:
                txt = it["discount"]
                # get digits in string
                num = "".join(ch for ch in txt if (ch.isdigit() or ch == "."))
                s += float(num) if num else 5
            except Exception:
                s += 5
        if it.get("old_price"):
            s += 3
        # small boost for items with both title+price
        if it.get("price") and it.get("title"):
            s += 1
        return s

    scored = sorted(unique, key=lambda x: score(x), reverse=True)

    # limit total
    final = scored[:POST_LIMIT_PER_RUN]
    logger.info("Fetched %d candidate deals (returning %d)", len(unique), len(final))
    return final


# -----------------------
# BUILD MESSAGE & POST
# -----------------------
def build_message(item):
    """
    Build the Telegram message text for an item.
    Format example:
    🔥 <b>Title</b>
    💰 Price: <b>KES ...</b>
    🛒 BUY NOW ➜ https://bit.ly/xxxxxxx
    (optionally include discount)
    """
    title = item.get("title", "No title")
    price = item.get("price", "")
    discount = item.get("discount")
    lines = []
    lines.append(f"🔥 <b>{escape_html(title)}</b>")
    if price:
        lines.append(f"💰 Price: <b>{escape_html(price)}</b>")
    if discount:
        lines.append(f"💥 Discount: {escape_html(discount)}")

    # Build affiliate + short link
    aff = make_affiliate_link(item.get("url"))
    short = shorten_with_bitly(aff)

    # B format chosen: "🛒 BUY NOW ➜ https://bit.ly/xxxxxxx"
    lines.append(f"🛒 BUY NOW ➜ {short}")

    # Optional: include original url as plain text below (commented out)
    # lines.append(f"🔗 {aff}")

    # Footer with time
    lines.append(f"<i>Posted: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')}</i>")

    return "\n".join(lines)


def escape_html(text: str) -> str:
    """Minimal HTML escape for Telegram HTML parse mode."""
    if not text:
        return ""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


def post_deals_job():
    try:
        logger.info("Starting autopost job...")
        items = fetch_deals()
        if not items:
            logger.info("No items found this run.")
            return

        posted_count = 0
        for it in items:
            if posted_count >= POST_LIMIT_PER_RUN:
                break

            h = item_hash(it)
            if h in posted_hashes:
                logger.debug("Skipping already posted item: %s", it.get("url"))
                continue

            msg = build_message(it)
            sent = send_telegram(msg)
            if sent:
                posted_hashes.add(h)
                posted_count += 1
                logger.info("Posted item: %s", it.get("title"))
            else:
                # If send fails, log but continue with others
                logger.warning("Failed to post item: %s", it.get("url"))

            # small delay to avoid being rate-limited
            time.sleep(1.0)

        logger.info("Autopost job finished. Posted %d items.", posted_count)
    except Exception as e:
        logger.exception("post_deals_job exception: %s", e)


# -----------------------
# FLASK ENDPOINTS
# -----------------------
@app.route("/")
def index():
    return jsonify({
        "status": "ok",
        "time": datetime.utcnow().isoformat() + "Z",
        "note": "Use /test to send a test message, /trigger to run now"
    })


@app.route("/test")
def test_endpoint():
    ok = send_telegram("🚀 Test message from autopost bot at " + datetime.utcnow().isoformat() + "Z")
    return jsonify({"sent": ok})


@app.route("/trigger")
def trigger_endpoint():
    # run synchronously
    post_deals_job()
    return jsonify({"triggered": True, "time": datetime.utcnow().isoformat() + "Z"})


# -----------------------
# SCHEDULER START
# -----------------------
def start_scheduler():
    # run immediately once then on interval
    scheduler.add_job(post_deals_job, "interval", minutes=SCHED_INTERVAL_MINUTES, next_run_time=datetime.now())
    scheduler.start()
    logger.info("Scheduler started: every %d minutes", SCHED_INTERVAL_MINUTES)


# -----------------------
# MAIN: start app and scheduler
# -----------------------
if __name__ == "__main__":
    logger.info("Starting autopost service...")
    start_scheduler()
    # Use PORT env var (Render uses PORT). Default 10000 or 5000 acceptable.
    port = int(os.getenv("PORT", os.getenv("RENDER_PORT", "10000")))
    app.run(host="0.0.0.0", port=port)
