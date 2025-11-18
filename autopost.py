import os
import requests
import time
import random
import threading
import schedule
from flask import Flask
import json
import re

# === CONFIGURATION ===
BOT_TOKEN = "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
CHAT_ID = -1003285979057  # Numeric Telegram channel ID
AFF_CODE = "5bed0bdf3d1ca"
BITLY_TOKEN = "77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b"

# === JUMIA CATEGORY LINKS ===
categories = [
    "https://www.jumia.co.ke/mlp-top-deals/",
    "https://www.jumia.co.ke/mlp-flash-sales/",
    "https://www.jumia.co.ke/electronics/",
    "https://www.jumia.co.ke/fashion/",
    "https://www.jumia.co.ke/home-office/",
    "https://www.jumia.co.ke/phones-tablets/",
    "https://www.jumia.co.ke/health-beauty/",
    "https://www.jumia.co.ke/supermarket/",
    "https://www.jumia.co.ke/baby-products/",
    "https://www.jumia.co.ke/computing/",
]

# === MEMORY TO AVOID REPEATS ===
posted_links = set()

# === SHORTEN LINK USING BITLY ===
def shorten_url(long_url):
    url = "https://api-ssl.bitly.com/v4/shorten"
    headers = {"Authorization": f"Bearer {BITLY_TOKEN}", "Content-Type": "application/json"}
    data = {"long_url": long_url}
    try:
        r = requests.post(url, json=data, headers=headers)
        if r.status_code == 200:
            return r.json().get("link", long_url)
        else:
            return long_url
    except Exception as e:
        print("⚠️ Bitly error:", e)
        return long_url

# === FETCH DEALS USING JUMIA JSON DATA ===
def fetch_all_deals():
    deals = []
    headers = {"User-Agent": "Mozilla/5.0"}

    for category in categories:
        try:
            res = requests.get(category, headers=headers, timeout=10)
            if res.status_code != 200:
                continue

            # Extract JSON data embedded in the page
            match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.*\});', res.text)
            if not match:
                continue

            data = json.loads(match.group(1))
            products = data.get("listings", {}).get("products", [])

            for p in products:
                link = "https://www.jumia.co.ke" + p.get("url", "")
                discount = p.get("discount", 0)
                deals.append((link, discount))

        except Exception as e:
            print("⚠️ Error fetching category:", e)

    return deals

# === POST TO TELEGRAM ===
def post_to_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": message}
    try:
        r = requests.get(url, params=params)
        if r.status_code != 200:
            print("⚠️ Telegram API error:", r.text)
    except Exception as e:
        print("⚠️ Exception posting to Telegram:", e)

# === MAIN POSTING FUNCTION ===
def post_top_20_deals():
    global posted_links
    deals = fetch_all_deals()

    # Remove already posted links
    new_deals = [d for d in deals if d[0] not in posted_links]

    if not new_deals:
        print("⚠️ No new deals found.")
        return

    # Sort deals by discount descending
    new_deals.sort(key=lambda x: x[1], reverse=True)

    # Pick top 20 deals
    top_20 = new_deals[:20]

    for link, discount in top_20:
        posted_links.add(link)
        aff_link = f"{link}?aff={AFF_CODE}"
        short_link = shorten_url(aff_link)
        msg = f"🔥 {discount}% OFF | Jumia Deal\n{short_link}"
        post_to_telegram(msg)
        print(f"✅ Posted: {short_link}")
        time.sleep(5)

# === SCHEDULER THREAD ===
def run_scheduler():
    print("⏳ Scheduler started… Running every hour.")
    schedule.every(1).hours.do(post_top_20_deals)
    while True:
        schedule.run_pending()
        time.sleep(1)

# === FLASK APP ===
app = Flask(__name__)

@app.route("/")
def home():
    return """
    <h1>✅ Autopost is running successfully!</h1>
    <p>Deals are automatically posted every hour.</p>
    """

@app.route("/run-now")
def manual_run():
    post_top_20_deals()
    return "Manual post job started!"

# === MAIN ENTRY (REQUIRED FOR RENDER) ===
if __name__ == '__main__':
    # 🚀 Post deals immediately on startup
    print("🚀 Posting top 20 deals immediately...")
    post_top_20_deals()

    # Start scheduler thread
    t = threading.Thread(target=run_scheduler)
    t.daemon = True
    t.start()

    # Run Flask on Render-assigned port
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
