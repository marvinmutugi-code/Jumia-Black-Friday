import os
import time
import requests
from datetime import datetime

# === Configuration ===
BOT_TOKEN = "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
CHAT_ID = "-1003285979057"
AFF_CODE = "5bed0bdf3d1ca"
BITLY_TOKEN = "77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b"

# === Categories to Fetch Deals From ===
CATEGORIES = [
    "phones-tablets",
    "electronics",
    "fashion",
    "computing",
    "health-beauty",
    "home-office"
]

# === Bitly Shortener ===
def shorten_link(long_url):
    """Shorten URLs using Bitly"""
    if not BITLY_TOKEN:
        return long_url
    try:
        res = requests.post(
            "https://api-ssl.bitly.com/v4/shorten",
            headers={"Authorization": f"Bearer {BITLY_TOKEN}"},
            json={"long_url": long_url},
            timeout=10
        )
        if res.status_code == 200:
            return res.json().get("link", long_url)
        else:
            return long_url
    except Exception as e:
        print("⚠️ Bitly error:", e)
        return long_url


# === Fetch Fake Deals (Simulation) ===
def get_top_deals(category):
    """Fetch 3 sample top deals for each category (simulated for demo)"""
    base_url = f"https://www.jumia.co.ke/{category}/?aff={AFF_CODE}&sort=popularity"
    deals = []
    for i in range(1, 4):
        deals.append({
            "title": f"🔥 Top {category.title()} Deal #{i}",
            "discount": f"{40 + i * 5}%",
            "link": shorten_link(base_url)
        })
    return deals


# === Telegram Sender ===
def send_to_telegram(message):
    """Send a message to your Telegram channel"""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=10
        )
        print("✅ Telegram response:", resp.status_code)
    except Exception as e:
        print("❌ Telegram error:", e)


# === Main Posting Function ===
def post_all_deals():
    print(f"\n🕒 Checking top Jumia deals — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    for cat in CATEGORIES:
        deals = get_top_deals(cat)
        for deal in deals:
            msg = f"{deal['title']} — Save {deal['discount']}!\nShop now ➡️ {deal['link']}"
            send_to_telegram(msg)
            time.sleep(5)  # Avoid Telegram flood limits
    print("✅ Finished posting all category deals.\n")


# === Main Loop ===
if __name__ == "__main__":
    print("🚀 Auto-posting Jumia top deals started...")
    post_all_deals()
    while True:
        time.sleep(3600)  # Post every 1 hour
        post_all_deals()
