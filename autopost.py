#!/usr/bin/env python3
"""
autopost.py - Mode B (Smart Scanning) for Jumia Black Friday deals

Features:
- Scrapes Flash Sales, Deals page, Top Selling, Black Friday pages and a compact list of categories.
- Prioritizes discounted & fast-moving items.
- Inserts affiliate code into the long URL, then shortens with Bitly (so clients do not see aff code).
- Posts using Telegram with HTML parse mode. Format uses: "🛒 BUY NOW ➜ https://bit.ly/xxxx"
- Persists posted hashes in posted_hashes.json to avoid reposts across restarts.
- /test and /trigger endpoints. Scheduler runs every SCHED_INTERVAL_MINUTES (default 60).
"""

import os
import time
import json
import logging
import requests
from hashlib import sha256
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from bs4 import BeautifulSoup
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

# -------------------------
# CONFIGURATION (env preferred)
# -------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1003285979057")
AFF_CODE = os.getenv("AFF_CODE", "5bed0bdf3d1ca")
BITLY_TOKEN = os.getenv("BITLY_TOKEN", "77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b")

# Smart scanning sources (Mode B)
JUMIA_BASE = "https://www.jumia.co.ke"
FLASH_SALES = "https://www.jumia.co.ke/flash-sales/"
DEALS_PAGE = "https://www.jumia.co.ke/deals/"
TOP_SELLING = "https://www.jumia.co.ke/top-selling/"
BLACK_FRIDAY = "https://www.jumia.co.ke/black-friday/"

# Compact category list for Mode B (expand if needed)
CATEGORIES = [
    "phones-tablets",
    "computing",
    "tv-video",
    "home-office",
    "home-appliances",
    "fashion",
    "beauty-health",
    "groceries",
]

# Behavior parameters
POST_LIMIT_PER_RUN = int(os.getenv("POST_LIMIT_PER_RUN", "20"))  # max items to post per run
ITEMS_PER_SOURCE = int(os.getenv("ITEMS_PER_SOURCE", "8"))      # how many per listing page to fetch
SCHED_INTERVAL_MINUTES = int(os.getenv("SCHED_INTERVAL_MINUTES", "60"))  # scheduler interval
HASH_STORE_FILE = os.getenv("HASH_STORE_FILE", "posted_hashes.json")
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.9"))  # seconds between requests

# HTTP headers
HEADERS = {
    "User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
}

# -------------------------
# LOGGING
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("autopost")

# -------------------------
# APP + SCHEDULER
# -------------------------
app = Flask(__name__)
scheduler = BackgroundScheduler()

# Posted items store (in-memory + persisted file)
posted_hashes = set()


# -------------------------
# Persistence helpers
# -------------------------
def load_posted_hashes():
    global posted_hashes
    try:
        if os.path.exists(HASH_STORE_FILE):
            with open(HASH_STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    posted_hashes = set(data)
                else:
                    posted_hashes = set()
                logger.info("Loaded %d posted hashes from %s", len(posted_hashes), HASH_STORE_FILE)
        else:
            posted_hashes = set()
    except Exception as e:
        logger.exception("Failed loading posted hashes: %s", e)
        posted_hashes = set()


def save_posted_hashes():
    try:
        with open(HASH_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(posted_hashes), f)
        logger.debug("Saved %d posted hashes", len(posted_hashes))
    except Exception as e:
        logger.exception("Failed saving posted hashes: %s", e)


# -------------------------
# Utility helpers
# -------------------------
def item_hash(item: dict) -> str:
    s = (item.get("url", "") + "|" + item.get("price", "") + "|" + item.get("title", "")).encode("utf-8")
    return sha256(s).hexdigest()


def escape_html(text: str) -> str:
    if not text:
        return ""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


# -------------------------
# Affiliate + Bitly
# -------------------------
def make_affiliate_link(long_url: str) -> str:
    """
    Add affiliate parameter aff_id to long_url while preserving existing query params.
    The aff code is added to the long URL, but we will send the long URL to Bitly
    so the shortened URL hides the affiliate code.
    """
    try:
        parsed = urlparse(long_url)
        qs = parse_qs(parsed.query)
        # common affiliate param names differ; we use aff_id unless you need another param
        qs["aff_id"] = [AFF_CODE]
        new_q = urlencode(qs, doseq=True)
        return urlunparse(parsed._replace(query=new_q))
    except Exception as e:
        logger.exception("make_affiliate_link error: %s", e)
        return long_url


def shorten_with_bitly(long_url: str) -> str:
    """
    Shorten the long_url with Bitly v4 API. If Bitly fails, return the long_url.
    """
    if not BITLY_TOKEN:
        logger.warning("BITLY_TOKEN not configured; returning long URL")
        return long_url

    endpoint = "https://api-ssl.bitly.com/v4/shorten"
    headers = {"Authorization": f"Bearer {BITLY_TOKEN}", "Content-Type": "application/json"}
    payload = {"long_url": long_url}
    try:
        r = requests.post(endpoint, json=payload, headers=headers, timeout=12)
        if r.status_code in (200, 201):
            data = r.json()
            short = data.get("link")
            if short:
                return short
            logger.warning("Bitly response without 'link': %s", data)
            return long_url
        else:
            logger.warning("Bitly error %s: %s", r.status_code, r.text)
            return long_url
    except Exception as e:
        logger.exception("Bitly exception: %s", e)
        return long_url


# -------------------------
# Generic scraper helpers
# -------------------------
def fetch_html(url: str, timeout=12) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        time.sleep(REQUEST_DELAY)
        if r.status_code == 200:
            return r.text
        else:
            logger.warning("Request failed %s status=%s", url, r.status_code)
            return ""
    except Exception as e:
        logger.exception("fetch_html exception for %s: %s", url, e)
        return ""


def parse_products_from_soup(soup) -> list:
    """
    Generic parser for common Jumia listing product cards.
    Returns list of dicts: {'title','price','old_price','discount','url'}
    """
    items = []
    # product card selectors: try several possibilities (site changes occasionally)
    card_selectors = [
        "article.prd",        # common product card
        "div.sku",            # alternate
        "div.c-prd",          # alternate
    ]
    cards = []
    for sel in card_selectors:
        found = soup.select(sel)
        if found:
            cards = found
            break

    if not cards:
        # fallback: try anchor blocks
        cards = soup.select("a[href*='/']")

    for card in cards:
        try:
            # title detection
            title_tag = card.select_one("h3.name, h2.title, a.name, span.title")
            title = title_tag.get_text(strip=True) if title_tag else (card.get("title") or "").strip()
            # price detection
            price_tag = card.select_one(".prc, span.price, .price")
            price = price_tag.get_text(strip=True) if price_tag else ""
            # old price
            old_tag = card.select_one(".old, .old-prc, span.old")
            old_price = old_tag.get_text(strip=True) if old_tag else None
            # discount
            dis_tag = card.select_one(".bdg._dsct, .discount, span.discount")
            discount = dis_tag.get_text(strip=True) if dis_tag else None
            # link
            a = card.select_one("a")
            href = a["href"] if a and a.get("href") else None
            if href and href.startswith("/"):
                href = JUMIA_BASE + href.lstrip("/")
            if not href:
                continue

            items.append({
                "title": title,
                "price": price,
                "old_price": old_price,
                "discount": discount,
                "url": href
            })
        except Exception:
            continue
    return items


def fetch_listing(url: str, limit=10) -> list:
    html = fetch_html(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = parse_products_from_soup(soup)
    return items[:limit]


# -------------------------
# Mode B aggregator (smart scanning)
# -------------------------
def fetch_deals_mode_b() -> list:
    """
    Aggregate curated sources: flash sales, deals page, top selling, black friday, categories.
    Returns deduped, scored, and sorted list of candidate deals.
    """
    logger.info("Fetching Mode B sources...")
    candidates = []

    # Flash sales
    try:
        candidates.extend(fetch_listing(FLASH_SALES, limit=ITEMS_PER_SOURCE))
        logger.info("Flash sales fetched: %d", len(candidates))
    except Exception:
        logger.exception("Flash sales fetch failed")

    # Deals page
    try:
        deals = fetch_listing(DEALS_PAGE, limit=ITEMS_PER_SOURCE)
        candidates.extend(deals)
        logger.info("Deals page fetched: %d", len(deals))
    except Exception:
        logger.exception("Deals fetch failed")

    # Top selling
    try:
        top = fetch_listing(TOP_SELLING, limit=ITEMS_PER_SOURCE)
        candidates.extend(top)
        logger.info("Top selling fetched: %d", len(top))
    except Exception:
        logger.exception("Top selling fetch failed")

    # Black Friday hub (sometimes includes treasure/treasure hunt)
    try:
        bf = fetch_listing(BLACK_FRIDAY, limit=ITEMS_PER_SOURCE)
        candidates.extend(bf)
        logger.info("Black Friday hub fetched: %d", len(bf))
    except Exception:
        logger.exception("BlackFriday fetch failed")

    # Selected categories (compact)
    for cat in CATEGORIES:
        try:
            cat_url = f"{JUMIA_BASE}/{cat}/"
            cat_items = fetch_listing(cat_url, limit=ITEMS_PER_SOURCE)
            candidates.extend(cat_items)
            logger.info("Category %s fetched: %d", cat, len(cat_items))
        except Exception:
            logger.exception("Category %s fetch failed", cat)

    # Deduplicate by product url
    unique_map = {}
    for it in candidates:
        u = it.get("url")
        if not u:
            continue
        if u not in unique_map:
            unique_map[u] = it

    unique_items = list(unique_map.values())

    # Score: discount presence & old_price > price gives higher score (best deals first)
    def score(it):
        s = 0
        if it.get("discount"):
            # try to extract digits
            try:
                raw = it["discount"]
                digits = "".join(ch for ch in raw if ch.isdigit() or ch == ".")
                s += float(digits) if digits else 5
            except Exception:
                s += 5
        if it.get("old_price"):
            s += 3
        # presence of both title and price
        if it.get("title") and it.get("price"):
            s += 1
        return s

    scored = sorted(unique_items, key=lambda x: score(x), reverse=True)
    logger.info("Aggregated %d unique candidate deals", len(scored))

    # limit total candidates (we will post up to POST_LIMIT_PER_RUN)
    return scored[: max(POST_LIMIT_PER_RUN * 2, 50)]


# -------------------------
# Message building & posting
# -------------------------
def build_message_for_item(item: dict) -> str:
    title = item.get("title", "No title")
    price = item.get("price", "")
    old = item.get("old_price")
    discount = item.get("discount")

    title_safe = escape_html(title)
    price_safe = escape_html(price)
    lines = []
    lines.append(f"🔥 <b>{title_safe}</b>")
    if price_safe:
        lines.append(f"💰 Price: <b>{price_safe}</b>")
    if old:
        lines.append(f"❌ Was: {escape_html(old)}")
    if discount:
        lines.append(f"💥 Discount: {escape_html(discount)}")

    # build affiliate then shorten with bitly
    aff_long = make_affiliate_link(item.get("url"))
    short = shorten_with_bitly(aff_long)

    lines.append(f"🛒 BUY NOW ➜ {short}")
    lines.append(f"<i>Posted: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')}</i>")

    return "\n".join(lines)


def send_to_telegram(text: str, disable_preview=True) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return False
    endpoint = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview
    }
    try:
        r = requests.post(endpoint, data=payload, timeout=12)
        logger.debug("Telegram status %s: %s", r.status_code, r.text)
        return r.status_code == 200
    except Exception as e:
        logger.exception("Telegram send error: %s", e)
        return False


# -------------------------
# Main job
# -------------------------
def post_deals_job():
    logger.info("Autopost job started")
    try:
        candidates = fetch_deals_mode_b()
        if not candidates:
            logger.info("No candidates found this run")
            return

        posted = 0
        for it in candidates:
            if posted >= POST_LIMIT_PER_RUN:
                break
            h = item_hash(it)
            if h in posted_hashes:
                logger.debug("Skipping already posted: %s", it.get("url"))
                continue

            msg = build_message_for_item(it)
            ok = send_to_telegram(msg)
            if ok:
                posted_hashes.add(h)
                posted += 1
                logger.info("Posted: %s", it.get("title"))
                save_posted_hashes()
            else:
                logger.warning("Failed to post item: %s", it.get("url"))

            # small pause to avoid rate limits
            time.sleep(1.0)

        logger.info("Autopost job finished — posted %d items", posted)
    except Exception as e:
        logger.exception("post_deals_job exception: %s", e)


# -------------------------
# Flask endpoints
# -------------------------
@app.route("/")
def index():
    return jsonify({
        "status": "ok",
        "time": datetime.utcnow().isoformat() + "Z",
        "info": "Use /test to send a test, /trigger to run job now"
    })


@app.route("/test")
def test_endpoint():
    ok = send_to_telegram("🚀 Test message from autopost bot at " + datetime.utcnow().isoformat() + "Z")
    return jsonify({"sent": ok})


@app.route("/trigger")
def trigger_endpoint():
    post_deals_job()
    return jsonify({"triggered": True, "time": datetime.utcnow().isoformat() + "Z"})


# -------------------------
# Scheduler start
# -------------------------
def start_scheduler():
    load_posted_hashes()
    # run immediately once, then on interval
    scheduler.add_job(post_deals_job, "interval", minutes=SCHED_INTERVAL_MINUTES, next_run_time=datetime.now())
    scheduler.start()
    logger.info("Scheduler started: every %d minutes", SCHED_INTERVAL_MINUTES)


# -------------------------
# MAIN
# -------------------------
if __name__ == "__main__":
    logger.info("Starting autopost service (Mode B - Smart Scanning)...")
    start_scheduler()
    port = int(os.getenv("PORT", os.getenv("RENDER_PORT", "10000")))
    app.run(host="0.0.0.0", port=port)
