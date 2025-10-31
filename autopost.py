import requests
import schedule
import time
import random
from bs4 import BeautifulSoup
import os

# ========== CONFIGURATION ==========
# Telegram setup
TELEGRAM_TOKEN = "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
TELEGRAM_CHAT_ID = "-1003285979057"

# Affiliate + Bitly setup
AFFILIATE_CODE = "5bed0bdf3d1ca"
BITLY_TOKEN = "77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b"

# Categories to pull from Jumia (update as needed)
JUMIA_CATEGORIES = [
    "phones-tablets",
    "computing",
    "home-office",
    "electronics",
    "fashion",
    "groceries",
    "health-beauty",
    "gaming"
]

# Memory of posted deals
posted_urls = set()

# ========== FUNCTIONS ==========

def shorten_link(long_url):
    """Shorten a link using Bitly API"""
    try:
        headers = {"Authorization": f"Bearer {BITLY_TOKEN}"}
        json_data = {"long_url": long_url}
        r = requests.post("https://api-ssl.bitly.com/v4/shorten", headers=headers, json=json_data)
        return r.json().get("link", long_url)
    except Exception:
        return long_url


def get_deals():
    """Fetch deals from Jumia categories"""
    all_deals = []

    for category in JUMIA_CATEGORIES:
        url = f"https://www.jumia.co.ke/{category}/?sort=popularity"
        response = requests.get(url, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")

        for item in soup.select("article.prd"):
            title = item.select_one("h3.name")
            price = item.select_one("div.prc")
            link_tag = item.select_one("a.core")

            if not (title and price and link_tag):
                continue

            product_url = "https://www.jumia.co.ke" + link_tag.get("href")
            if product_url in posted_urls:
                continue

            # Add affiliate code
            aff_link = f"{product_url}?aff={AFFILIATE_CODE}"

            # Shorten with Bitly
            short_url = shorten_link(aff_link)

            deal = f"🔥 {title.text.strip()}\n💰 Price: {price.text.strip()}\n👉 Buy Now: {short_url}"
            all_deals.append(deal)

    # Shuffle deals to mix categories
    random.shuffle(all_deals)
    return all_deals[:5]


def post_to_telegram(message):
    """Send a message to Telegram channel"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, data=payload)


def autopost():
    """Main posting function"""
    print("Fetching new deals...")
    deals = get_deals()
    if not deals:
        print("No new deals found.")
        return

    for deal in deals:
        post_to_telegram(deal)
        # mark as posted
        posted_urls.add(deal)
        time.sleep(10)  # slight delay between messages

    print("✅ Posted new round of deals.")


# Schedule every 10 minutes
schedule.every(10).minutes.do(autopost)

print("🚀 Autopost started... Running every 10 minutes.")
autopost()  # run once at start

while True:
    schedule.run_pending()
    time.sleep(30)
