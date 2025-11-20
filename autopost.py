#!/usr/bin/env python3
"""
autopost.py - Full Jumia Smart Scraper Engine (Mode B+, expanded)

Features:
- Scrapes Flash Sales, Deals, Top Selling, Black Friday hub, Treasure / Hidden deals & vouchers, plus a compact list of categories.
- Prioritizes high-discount and fast-moving items.
- Uses Jumia kol redirect affiliate format + Bitly shortening (so affiliate code is hidden from users).
- Posts product image + caption (HTML) to Telegram via sendPhoto.
- Persists posted hashes to posted_hashes.json.
- /test and /trigger endpoints. Scheduler interval configurable via env.
"""

import os
import time
import json
import logging
import requests
from hashlib import sha256
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, quote_plus

from bs4 import BeautifulSoup
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

# -------------------------
# Configuration (env preferred)
# -------------------------
# Set these in Render Environment for production
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1003285979057")
AFF_ID = os.getenv("AFF_CODE", "5bed0bdf3d1ca")
BITLY_TOKEN = os.getenv("BITLY_TOKEN", "77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b")

JUMIA_BASE = "https://www.jumia.co.ke"
FLASH_SALES = "https://www.jumia.co.ke/flash-sales/"
DEALS_PAGE = "https://www.jumia.co.ke/deals/"
TOP_SELLING = "https://www.jumia.co.ke/top-selling/"
BLACK_FRIDAY = "https://www.jumia.co.ke/black-friday/"
VOUCHERS_PAGE = "https://www.jumia.co.ke/black-friday-vouchers/"
TREASURE_PAGE = "https://www.jumia.co.ke/black-friday-treasure-hunt/"

# Compact category list for Mode B+
CATEGORIES = [
    "phones-tablets",
    "computing",
    "tv-video",
    "home-appliances",
    "home-office",
    "fashion",
    "beauty-health",
    "groceries",
    "gaming",
    "kitchen-dining"
]

# Behavior params
POST_LIMIT_PER_RUN = int(os.getenv("POST_LIMIT_PER_RUN", "20"))
ITEMS_PER_SOURCE = int(os.getenv("ITEMS_PER_SOURCE", "10"))
SCHED_INTERVAL_MINUTES = int(os.getenv("SCHED_INTERVAL_MINUTES", "60"))
HASH_STORE_FILE = os.getenv("HASH_STORE_FILE", "posted_hashes.json")
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.8"))
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")

HEADERS = {"User-Agent": USER_AGENT}

# -------------------------
# Logging
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("autopost")

# -------------------------
# Flask + Scheduler
# -------------------------
app = Flask(__name__)
scheduler = BackgroundScheduler()

# -------------------------
# Posted hashes persistence
# -------------------------
posted_hashes = set()


def load_posted_hashes():
    global posted_hashes
    try:
        if os.path.exists(HASH_STORE_FILE):
            with open(HASH_STORE_FILE, "r", encoding="utf-8") as f:
                arr = json.load(f)
                posted_hashes = set(arr if isinstance(arr, list) else [])
            logger.info("Loaded %d posted hashes", len(posted_hashes))
        else:
            posted_hashes = set()
    except Exception as e:
        logger.exception("Error loading posted hashes: %s", e)
        posted_hashes = set()


def save_posted_hashes():
    try:
        with open(HASH_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(posted_hashes), f)
        logger.debug("Saved %d posted hashes", len(posted_hashes))
    except Exception as e:
        logger.exception("Error saving posted hashes: %s", e)


# -------------------------
# Utilities
# -------------------------
def item_hash(item: dict) -> str:
    s = (item.get("url", "") + "|" + item.get("price", "") + "|" + item.get("title", "")).encode("utf-8")
    return sha256(s).hexdigest()


def escape_html(text: str) -> str:
    if not text:
        return ""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def fetch_html(url: str, timeout=12) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        time.sleep(REQUEST_DELAY)
        if r.status_code == 200:
            return r.text
        logger.warning("HTTP %s for %s", r.status_code, url)
        return ""
    except Exception as e:
        logger.exception("fetch_html error for %s: %s", url, e)
        return ""


# -------------------------
# Parsing helpers (robust)
# -------------------------
def parse_products_from_soup(soup) -> list:
    items = []
    # Try common product card selectors used by Jumia; keep parser robust to small changes
    card_selectors = ["article.prd", "div.sku", "div.c-prd", "div.product", "div.prd"]
    cards = []
    for sel in card_selectors:
        found = soup.select(sel)
        if found:
            cards = found
            break
    if not cards:
        cards = soup.select("a[href*='/']")

    for card in cards:
        try:
            # title
            title_tag = card.select_one("h3.name, h2.title, a.name, span.name, a.link")
            title = title_tag.get_text(strip=True) if title_tag else (card.get("aria-label") or "").strip()

            # price current
            price_tag = card.select_one(".prc, span.price, .price, div.prc")
            price = price_tag.get_text(strip=True) if price_tag else ""

            # old price
            old_tag = card.select_one(".old, .old-prc, span.old")
            old_price = old_tag.get_text(strip=True) if old_tag else None

            # discount label
            discount_tag = card.select_one(".bdg._dsct, .discount, span.discount")
            discount = discount_tag.get_text(strip=True) if discount_tag else None

            # image
            img_tag = card.select_one("img")
            img = None
            if img_tag:
                img = img_tag.get("data-src") or img_tag.get("src") or img_tag.get("data-original")

            # link
            a = card.select_one("a")
            href = a.get("href") if a and a.get("href") else None
            if href and href.startswith("/"):
                href = JUMIA_BASE + href.lstrip("/")
            if not href or not title:
                continue

            items.append({
                "title": title,
                "price": price,
                "old_price": old_price,
                "discount": discount,
                "image": img,
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
# Affiliate & Bitly
# -------------------------
def make_kol_affiliate_url(product_url: str) -> str:
    """
    Build the kol.jumia affiliate redirect URL with encoded redirect param.
    Uses aff_id parameter and kol redirect path.
    """
    try:
        encoded = quote_plus(product_url)
        kol = f"https://kol.jumia.com/api/click/banner_id/48233/aff_id/{AFF_ID}?redirect={encoded}"
        return kol
    except Exception as e:
        logger.exception("make_kol_affiliate_url error: %s", e)
        return product_url


def shorten_with_bitly(long_url: str) -> str:
    if not BITLY_TOKEN:
        logger.warning("BITLY_TOKEN missing, returning long URL")
        return long_url
    endpoint = "https://api-ssl.bitly.com/v4/shorten"
    headers = {"Authorization": f"Bearer {BITLY_TOKEN}", "Content-Type": "application/json"}
    payload = {"long_url": long_url}
    try:
        r = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        if r.status_code in (200, 201):
            data = r.json()
            return data.get("link", long_url)
        else:
            logger.warning("Bitly error %s: %s", r.status_code, r.text)
            return long_url
    except Exception as e:
        logger.exception("Bitly exception: %s", e)
        return long_url


# -------------------------
# High-level source fetchers
# -------------------------
def fetch_flash_sales():
    return fetch_listing(FLASH_SALES, limit=ITEMS_PER_SOURCE)


def fetch_deals_page():
    return fetch_listing(DEALS_PAGE, limit=ITEMS_PER_SOURCE)


def fetch_top_selling():
    return fetch_listing(TOP_SELLING, limit=ITEMS_PER_SOURCE)


def fetch_black_friday():
    return fetch_listing(BLACK_FRIDAY, limit=ITEMS_PER_SOURCE)


def fetch_vouchers_and_treasure():
    # attempt both pages (vouchers and treasure)
    out = []
    out.extend(fetch_listing(VOUCHERS_PAGE, limit=ITEMS_PER_SOURCE))
    out.extend(fetch_listing(TREASURE_PAGE, limit=ITEMS_PER_SOURCE))
    return out


def fetch_categories_compact():
    all_items = []
    for c in CATEGORIES:
        try:
            u = f"{JUMIA_BASE}/{c}/"
            all_items.extend(fetch_listing(u, limit=ITEMS_PER_SOURCE))
        except Exception:
            logger.exception("Category fetch failed: %s", c)
    return all_items


# -------------------------
# Aggregator (Mode B+)
# -------------------------
def aggregate_candidates() -> list:
    logger.info("Aggregating candidates from Mode B+ sources...")
    candidates = []
    try:
        candidates.extend(fetch_flash_sales())
    except Exception:
        logger.exception("flash failed")
    try:
        candidates.extend(fetch_deals_page())
    except Exception:
        logger.exception("deals failed")
    try:
        candidates.extend(fetch_top_selling())
    except Exception:
        logger.exception("top selling failed")
    try:
        candidates.extend(fetch_black_friday())
    except Exception:
        logger.exception("black friday failed")
    try:
        candidates.extend(fetch_vouchers_and_treasure())
    except Exception:
        logger.exception("vouchers/treasure failed")
    try:
        candidates.extend(fetch_categories_compact())
    except Exception:
        logger.exception("categories failed")

    # dedupe by url, preserve first seen
    unique = {}
    for it in candidates:
        u = it.get("url")
        if not u:
            continue
        if u not in unique:
            unique[u] = it

    unique_items = list(unique.values())

    # scoring: prefer items with numeric discount or old_price
    def score(it):
        s = 0
        if it.get("discount"):
            try:
                digits = "".join(ch for ch in it["discount"] if ch.isdigit() or ch == ".")
                s += float(digits) if digits else 5
            except Exception:
                s += 5
        if it.get("old_price"):
            s += 3
        if it.get("price") and it.get("title"):
            s += 1
        return s

    scored = sorted(unique_items, key=lambda x: score(x), reverse=True)
    logger.info("Aggregated %d unique items, returning top %d candidates", len(scored), min(len(scored), POST_LIMIT_PER_RUN * 3))
    return scored[: max(POST_LIMIT_PER_RUN * 3, 50)]


# -------------------------
# Build message (image + caption)
# -------------------------
def build_caption(it: dict) -> str:
    title = escape_html(it.get("title") or "No title")
    price = escape_html(it.get("price") or "")
    old = escape_html(it.get("old_price") or "")
    discount = escape_html(it.get("discount") or "")

    parts = [f"🔥 <b>{title}</b>"]
    if price:
        parts.append(f"💰 Price: <b>{price}</b>")
    if old:
        parts.append(f"❌ Was: {old}")
    if discount:
        parts.append(f"💥 Discount: {discount}")

    # build affiliate & shorten
    kol = make_kol_affiliate_url(it.get("url"))
    short = shorten_with_bitly(kol)

    parts.append(f"🛒 BUY NOW ➜ {short}")
    parts.append(f"<i>Posted: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')}</i>")
    return "\n".join(parts)


# -------------------------
# Telegram send photo (resilient)
# -------------------------
def send_photo_with_caption(image_url: str, caption: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return False

    endpoint = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"

    try:
        # Download image bytes (timeout tolerant)
        rimg = requests.get(image_url, headers=HEADERS, timeout=12, stream=True)
        if rimg.status_code != 200:
            logger.warning("Image download failed %s: %s", image_url, rimg.status_code)
            # fallback: send message without image via sendMessage
            return send_message(caption)
        img_bytes = rimg.content

        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
        files = {"photo": ("image.jpg", img_bytes)}
        r = requests.post(endpoint, data=data, files=files, timeout=20)
        logger.debug("Telegram photo response: %s", r.text)
        return r.status_code == 200
    except Exception as e:
        logger.exception("send_photo_with_caption exception: %s", e)
        return send_message(caption)


def send_message(text: str) -> bool:
    endpoint = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(endpoint, data=payload, timeout=12)
        logger.debug("Telegram message response: %s", r.text)
        return r.status_code == 200
    except Exception as e:
        logger.exception("send_message exception: %s", e)
        return False


# -------------------------
# Main job
# -------------------------
def post_deals_job():
    logger.info("Autopost job started")
    try:
        candidates = aggregate_candidates()
        if not candidates:
            logger.info("No candidates found")
            return

        posted = 0
        for it in candidates:
            if posted >= POST_LIMIT_PER_RUN:
                break
            h = item_hash(it)
            if h in posted_hashes:
                logger.debug("Already posted, skip: %s", it.get("url"))
                continue

            caption = build_caption(it)
            image = it.get("image") or ""
            ok = False
            if image:
                ok = send_photo_with_caption(image, caption)
            else:
                ok = send_message(caption)

            if ok:
                posted_hashes.add(h)
                save_posted_hashes()
                posted += 1
                logger.info("Posted: %s", it.get("title"))
            else:
                logger.warning("Failed to post: %s", it.get("url"))

            time.sleep(1.0)  # small delay to avoid rate limits
        logger.info("Autopost finished - posted %d items", posted)
    except Exception as e:
        logger.exception("post_deals_job exception: %s", e)


# -------------------------
# Endpoints & Scheduler
# -------------------------
@app.route("/")
def index():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat() + "Z"})


@app.route("/test")
def test_endpoint():
    ok = send_message("🚀 Test message from autopost bot at " + datetime.utcnow().isoformat() + "Z")
    return jsonify({"sent": ok})


@app.route("/trigger")
def trigger_endpoint():
    post_deals_job()
    return jsonify({"triggered": True, "time": datetime.utcnow().isoformat() + "Z"})


def start_scheduler():
    load_posted_hashes()
    scheduler.add_job(post_deals_job, "interval", minutes=SCHED_INTERVAL_MINUTES, next_run_time=datetime.now())
    scheduler.start()
    logger.info("Scheduler started every %d minutes", SCHED_INTERVAL_MINUTES)


# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    logger.info("Starting Autopost (full Mode B+)...")
    start_scheduler()
    port = int(os.getenv("PORT", os.getenv("RENDER_PORT", "10000")))
    app.run(host="0.0.0.0", port=port)
