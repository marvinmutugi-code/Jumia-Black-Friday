#!/usr/bin/env python3
"""
autopost.py - Jumia Smart Scraper Engine (Mode B+ Updated)

Features:
- Scrapes Flash Sales, Deals, Top Selling, Black Friday, Treasure/Vouchers, and categories.
- Prioritizes high-discount and fast-moving items.
- Uses Jumia kol affiliate redirect links + Bitly shortening.
- Posts product image + caption to Telegram with hidden clickable "Shop Now" links.
- Avoids reposting the same deal using hash persistence.
- Scheduler + Flask endpoints (/test, /trigger).
"""

import os
import time
import json
import logging
import requests
from hashlib import sha256
from datetime import datetime
from urllib.parse import quote
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

# -------------------------
# Configuration
# -------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "YOUR_TELEGRAM_TOKEN"
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or "YOUR_CHAT_ID"
AFF_ID = os.getenv("AFF_CODE") or "YOUR_AFF_ID"
BITLY_TOKEN = "b61d8f44a9084b6309edb381b66654496a09292d"  # New token

JUMIA_BASE = "https://www.jumia.co.ke"
FLASH_SALES = "https://www.jumia.co.ke/flash-sales/"
DEALS_PAGE = "https://www.jumia.co.ke/deals/"
TOP_SELLING = "https://www.jumia.co.ke/top-selling/"
BLACK_FRIDAY = "https://www.jumia.co.ke/black-friday/"
VOUCHERS_PAGE = "https://www.jumia.co.ke/black-friday-vouchers/"
TREASURE_PAGE = "https://www.jumia.co.ke/black-friday-treasure-hunt/"

CATEGORIES = [
    "phones-tablets", "computing", "tv-video", "home-appliances",
    "home-office", "fashion", "beauty-health", "groceries",
    "gaming", "kitchen-dining"
]

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
    if not text: return ""
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
# Parsing helpers
# -------------------------
def parse_products_from_soup(soup) -> list:
    items = []
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
            title_tag = card.select_one("h3.name, h2.title, a.name, span.name, a.link")
            title = title_tag.get_text(strip=True) if title_tag else (card.get("aria-label") or "").strip()
            price_tag = card.select_one(".prc, span.price, .price, div.prc")
            price = price_tag.get_text(strip=True) if price_tag else ""
            old_tag = card.select_one(".old, .old-prc, span.old")
            old_price = old_tag.get_text(strip=True) if old_tag else None
            discount_tag = card.select_one(".bdg._dsct, .discount, span.discount")
            discount = discount_tag.get_text(strip=True) if discount_tag else None
            img_tag = card.select_one("img")
            img = img_tag.get("data-src") or img_tag.get("src") or img_tag.get("data-original") if img_tag else None
            a = card.select_one("a")
            href = a.get("href") if a and a.get("href") else None
            if href and href.startswith("/"):
                href = JUMIA_BASE.rstrip("/") + "/" + href.lstrip("/")
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
    try:
        encoded = quote(product_url, safe='')
        kol = f"https://kol.jumia.com/redirect?aff_id={AFF_ID}&url={encoded}"
        return kol
    except Exception as e:
        logger.exception("make_kol_affiliate_url error: %s", e)
        return product_url

def shorten_with_bitly(long_url: str) -> str:
    if not BITLY_TOKEN:
        return long_url
    try:
        endpoint = "https://api-ssl.bitly.com/v4/shorten"
        headers = {"Authorization": f"Bearer {BITLY_TOKEN}", "Content-Type": "application/json"}
        payload = {"long_url": long_url}
        r = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        data = r.json()
        if r.status_code in (200, 201) and "link" in data:
            return data["link"]
        logger.warning("Bitly failed %s: %s", r.status_code, r.text)
        return long_url
    except Exception as e:
        logger.exception("Bitly exception: %s", e)
        return long_url

# -------------------------
# Fetchers
# -------------------------
def fetch_flash_sales(): return fetch_listing(FLASH_SALES, ITEMS_PER_SOURCE)
def fetch_deals_page(): return fetch_listing(DEALS_PAGE, ITEMS_PER_SOURCE)
def fetch_top_selling(): return fetch_listing(TOP_SELLING, ITEMS_PER_SOURCE)
def fetch_black_friday(): return fetch_listing(BLACK_FRIDAY, ITEMS_PER_SOURCE)
def fetch_vouchers_and_treasure():
    out = []
    out.extend(fetch_listing(VOUCHERS_PAGE, ITEMS_PER_SOURCE))
    out.extend(fetch_listing(TREASURE_PAGE, ITEMS_PER_SOURCE))
    return out
def fetch_categories_compact():
    all_items = []
    for c in CATEGORIES:
        try:
            u = f"{JUMIA_BASE.rstrip('/')}/{c}/"
            all_items.extend(fetch_listing(u, ITEMS_PER_SOURCE))
        except Exception:
            logger.exception("Category fetch failed: %s", c)
    return all_items

# -------------------------
# Aggregator
# -------------------------
def aggregate_candidates() -> list:
    candidates = []
    try: candidates.extend(fetch_flash_sales())
    except: logger.exception("flash failed")
    try: candidates.extend(fetch_deals_page())
    except: logger.exception("deals failed")
    try: candidates.extend(fetch_top_selling())
    except: logger.exception("top selling failed")
    try: candidates.extend(fetch_black_friday())
    except: logger.exception("black friday failed")
    try: candidates.extend(fetch_vouchers_and_treasure())
    except: logger.exception("vouchers/treasure failed")
    try: candidates.extend(fetch_categories_compact())
    except: logger.exception("categories failed")

    # dedupe & filter login/category pages
    unique = {}
    for it in candidates:
        u = it.get("url")
        if not u or "/customer/account/login" in u or "/category-" in u:
            continue
        if u not in unique:
            unique[u] = it
    unique_items = list(unique.values())

    # scoring: prefer discount / old_price
    def score(it):
        s = 0
        if it.get("discount"):
            try: digits = "".join(ch for ch in it["discount"] if ch.isdigit() or ch=="."); s+=float(digits) if digits else 5
            except: s+=5
        if it.get("old_price"): s+=3
        if it.get("price") and it.get("title"): s+=1
        return s

    scored = sorted(unique_items, key=lambda x: score(x), reverse=True)
    return scored[: max(POST_LIMIT_PER_RUN*3, 50)]

# -------------------------
# Build caption
# -------------------------
def build_caption(it: dict) -> str:
    title = escape_html(it.get("title") or "No title")
    price = escape_html(it.get("price") or "")
    old = escape_html(it.get("old_price") or "")
    discount = escape_html(it.get("discount") or "")
    parts = []
    parts.append(f"🔥 <b>{title}</b>")
    if price:
        parts.append(f"💰 {price}" + (f" (was {old})" if old else ""))
    if discount:
        parts.append(f"🔥 {discount} OFF!")
    parts.append("⚡️ Top Deal of the Hour from Jumia!")

    kol_url = make_kol_affiliate_url(it.get("url"))
    short_url = shorten_with_bitly(kol_url)

    parts.append(f'🔗 <a href="{short_url}">Shop Now</a>')
    return "\n".join(parts)

# -------------------------
# Telegram send
# -------------------------
def send_photo_with_caption(image_url: str, caption: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return False
    endpoint = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        rimg = requests.get(image_url, headers=HEADERS, timeout=12, stream=True)
        img_bytes = rimg.content if rimg.status_code==200 else None
        if not img_bytes: return send_message(caption)
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
        files = {"photo": ("image.jpg", img_bytes)}
        r = requests.post(endpoint, data=data, files=files, timeout=20)
        return r.status_code == 200
    except Exception as e:
        logger.exception("send_photo_with_caption exception: %s", e)
        return send_message(caption)

def send_message(text: str) -> bool:
    endpoint = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(endpoint, data=payload, timeout=12)
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
        if not candidates: return
        posted = 0
        for it in candidates:
            if posted >= POST_LIMIT_PER_RUN: break
            h = item_hash(it)
            if h in posted_hashes: continue
            caption = build_caption(it)
            image = it.get("image") or ""
            ok = send_photo_with_caption(image, caption) if image else send_message(caption)
            if ok:
                posted_hashes.add(h)
                save_posted_hashes()
                posted += 1
                logger.info("Posted: %s", it.get("title"))
            else:
                logger.warning("Failed to post: %s", it.get("url"))
            time.sleep(1.0)
        logger.info("Autopost finished - posted %d items", posted)
    except Exception as e:
        logger.exception("post_deals_job exception: %s", e)

# -------------------------
# Flask endpoints
# -------------------------
@app.route("/")
def index(): return jsonify({"status":"ok","time":datetime.utcnow().isoformat()+"Z"})
@app.route("/test")
def test_endpoint():
    ok = send_message("🚀 Test message from autopost bot at "+datetime.utcnow().isoformat()+"Z")
    return jsonify({"sent": ok})
@app.route("/trigger")
def trigger_endpoint():
    post_deals_job()
    return jsonify({"triggered": True, "time": datetime.utcnow().isoformat()+"Z"})

def start_scheduler():
    load_posted_hashes()
    scheduler.add_job(post_deals_job, "interval", minutes=SCHED_INTERVAL_MINUTES, next_run_time=datetime.now())
    scheduler.start()
    logger.info("Scheduler started every %d minutes", SCHED_INTERVAL_MINUTES)

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    logger.info("Starting Autopost (Mode B+ Updated Kol redirect)...")
    start_scheduler()
    port = int(os.getenv("PORT") or os.getenv("RENDER_PORT") or 10000)
    app.run(host="0.0.0.0", port=port)
