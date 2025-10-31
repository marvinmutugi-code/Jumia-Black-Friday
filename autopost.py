import requests
from bs4 import BeautifulSoup
import time
import schedule
import random
import os
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

# ================== CONFIG =====================
JUMIA_URL = "https://www.jumia.co.ke/"
TELEGRAM_BOT_TOKEN = "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
TELEGRAM_CHAT_ID = "-1003285979057"
AFF_CODE = "5bed0bdf3d1ca"  
POSTED_LINKS_FILE = "posted_links.txt"
DEALS_PER_POST = 5
POST_INTERVAL_MINUTES = 10
# ===============================================


def shorten_url(long_url):
    """Shorten URL using Bitly API."""
    BITLY_TOKEN = os.getenv("BITLY_TOKEN")
    if not BITLY_TOKEN:
        return long_url
    try:
        headers = {"Authorization": f"Bearer {BITLY_TOKEN}"}
        data = {"long_url": long_url}
        r = requests.post("https://api-ssl.bitly.com/v4/shorten", headers=headers, json=data)
        if r.status_code == 200:
            return r.json().get("link", long_url)
    except Exception:
        pass
    return long_url


def fetch_deals():
    """Fetch top deals from multiple Jumia categories."""
    categories = [
        "phones-tablets/",
        "electronics/",
        "fashion/",
        "home-office/",
        "health-beauty/",
        "computing/",
        "supermarket/",
        "baby-products/",
        "sporting-goods/",
        "gaming/",
        "automobile/"
    ]

    all_deals = []
    for category in categories:
        url = urljoin(JUMIA_URL, category)
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        items = soup.select(".prd._fb.col.c-prd")
        for item in items[:10]:
            name = item.select_one(".name")
            price = item.select_one(".prc")
            old_price = item.select_one(".old")
            discount = item.select_one(".bdg._dsct")
            link = item.find("a", href=True)

            if not all([name, price, link]):
                continue

            deal = {
                "name": name.text.strip(),
                "price": price.text.strip(),
                "old_price": old_price.text.strip() if old_price else "N/A",
                "discount": discount.text.strip() if discount else "0%",
                "link": urljoin(JUMIA_URL, link["href"])
            }
            all_deals.append(deal)

    # Sort by discount (highest first)
    all_deals.sort(key=lambda d: int(d["discount"].replace("%", "").replace("-", "") or 0), reverse=True)
    return all_deals


def load_posted_links():
    """Load posted product IDs from file."""
    if not os.path.exists(POSTED_LINKS_FILE):
        return set()
    with open(POSTED_LINKS_FILE, "r") as f:
        return set(f.read().splitlines())


def save_posted_link(product_id):
    """Save posted product ID to file."""
    with open(POSTED_LINKS_FILE, "a") as f:
        f.write(product_id + "\n")


def send_telegram_message(deal):
    """Send message to Telegram channel."""
    product_id = deal["link"].split("/")[-1].split("?")[0]
    link = f"{deal['link']}?aff_id={AFF_CODE}"
    short_link = shorten_url(link)

    message = (
        f"🛍️ {deal['name']}\n"
        f"💰 {deal['price']} (was {deal['old_price']}) 🔥 {deal['discount']} OFF!\n"
        f"⚡️ Trending Deal from Jumia!\n"
        f"🔗 Shop Now: {short_link}"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, data=payload)

    save_posted_link(product_id)


def job():
    """Main job that runs every 10 minutes."""
    print("🔄 Checking for new deals...")
    posted = load_posted_links()
    all_deals = fetch_deals()
    new_deals = []

    for deal in all_deals:
        product_id = deal["link"].split("/")[-1].split("?")[0]
        if product_id not in posted:
            new_deals.append(deal)
        if len(new_deals) >= DEALS_PER_POST:
            break

    if not new_deals:
        print("✅ No new deals found. Skipping...")
        return

    print(f"📦 Posting {len(new_deals)} new deals...")
    for deal in new_deals:
        send_telegram_message(deal)
        time.sleep(5)  # small delay to avoid rate-limit

    print("✅ Deals posted successfully!")


# Schedule every 10 minutes
schedule.every(POST_INTERVAL_MINUTES).minutes.do(job)

print("🤖 Autoposter running... (checks every 10 mins)")

# Run immediately on start
job()

while True:
    schedule.run_pending()
    time.sleep(30)
