import requests
import time
import random
from bs4 import BeautifulSoup
import schedule
from dotenv import load_dotenv
import os

# Load .env variables if available
load_dotenv()

# ==============================
# 🔐 CONFIGURATION
# ==============================
BOT_TOKEN ="8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
CHANNEL_ID = "-1003285979057"
AFFILIATE_ID =  "5bed0bdf3d1ca"
BITLY_TOKEN =  "77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b"
CUSTOM_KEYWORDS = ["phone", "fridge", "tv", "laptop", "watch",]  

POST_LIMIT = 20  # number of items per round
POST_INTERVAL_MINUTES = 10  # time interval between rounds

# To avoid reposting
posted_links = set()

# ==============================
# 🔗 Bitly shortener
# ==============================
def shorten_url(long_url):
    try:
        headers = {
            "Authorization": f"Bearer {BITLY_TOKEN}",
            "Content-Type": "application/json"
        }
        json_data = {"long_url": long_url}
        res = requests.post("https://api-ssl.bitly.com/v4/shorten", headers=headers, json=json_data)
        if res.status_code == 200:
            return res.json()["link"]
        else:
            return long_url
    except Exception as e:
        print("Bitly error:", e)
        return long_url

# ==============================
# 🔍 Fetch deals (flash + trending + keywords)
# ==============================
def fetch_deals():
    urls = [
        "https://www.jumia.co.ke/flash-sales/",
        "https://www.jumia.co.ke/catalog/?q=discount",
        "https://www.jumia.co.ke/top-deals/",
    ]
    all_deals = []

    for url in urls:
        res = requests.get(url)
        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("article.prd")

        for item in items:
            title = item.select_one("h3.name")
            price = item.select_one("div.prc")
            link = item.select_one("a.core")
            discount = item.select_one("div.bdg._dsct")

            if not title or not link:
                continue

            title_text = title.text.strip()
            price_text = price.text.strip() if price else "N/A"
            discount_text = discount.text.strip() if discount else ""

            # Build affiliate URL
            full_link = f"https://www.jumia.co.ke{link['href']}?aff_id={AFFILIATE_ID}"

            # Filter custom keywords
            if any(word.lower() in title_text.lower() for word in CUSTOM_KEYWORDS):
                all_deals.append((title_text, price_text, discount_text, full_link))

            # Collect general deals too
            if "flash" in url or "top-deals" in url:
                all_deals.append((title_text, price_text, discount_text, full_link))

    # Remove duplicates
    unique = []
    seen = set()
    for deal in all_deals:
        if deal[3] not in seen:
            unique.append(deal)
            seen.add(deal[3])
    return unique

# ==============================
# 📤 Send to Telegram
# ==============================
def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"}
    requests.post(url, data=payload)

# ==============================
# 🚀 Main Posting Logic
# ==============================
def post_deals():
    print("Fetching new deals...")
    deals = fetch_deals()
    random.shuffle(deals)
    count = 0

    for title, price, discount, link in deals:
        if count >= POST_LIMIT:
            break
        if link in posted_links:
            continue

        short_link = shorten_url(link)
        message = f"🛍️ <b>{title}</b>\n💰 {price} 🔥 {discount} OFF!\n⚡️ Hurry! Top Deal on Jumia!\n🔗 {short_link}"
        send_to_telegram(message)
        print("Posted:", title)
        posted_links.add(link)
        count += 1
        time.sleep(random.randint(10, 20))  # space out messages

# ==============================
# ⏲️ Schedule every 10 minutes
# ==============================
schedule.every(POST_INTERVAL_MINUTES).minutes.do(post_deals)

# Initial start
print("🤖 AutoPoster started successfully...")
post_deals()  # Run immediately

while True:
    schedule.run_pending()
    time.sleep(5)
