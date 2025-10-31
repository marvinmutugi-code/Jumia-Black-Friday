import requests
from bs4 import BeautifulSoup
import random
import time
import os
import telegram
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
CHAT_ID ="-1003285979057"
AFF_ID = "5bed0bdf3d1ca"
BITLY TOKEN="77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b"
bot = telegram.Bot(token=BOT_TOKEN)

CATEGORIES = [
    "https://www.jumia.co.ke/mlp-top-deals/",
    "https://www.jumia.co.ke/mlp-flash-sales/",
    "https://www.jumia.co.ke/mlp-black-friday/",
    "https://www.jumia.co.ke/phones-tablets/",
    "https://www.jumia.co.ke/home-office/",
    "https://www.jumia.co.ke/supermarket/",
    "https://www.jumia.co.ke/health-beauty/",
    "https://www.jumia.co.ke/fashion/",
]

def fetch_deals(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("article.prd._fb.col.c-prd")
        deals = []
        for item in items[:5]:  # pick top 5 per category
            title = item.select_one("h3.name").text.strip() if item.select_one("h3.name") else "No title"
            price = item.select_one("div.prc").text.strip() if item.select_one("div.prc") else "N/A"
            old_price = item.select_one("div.old").text.strip() if item.select_one("div.old") else "N/A"
            discount = item.select_one("div.bdg._dsct._sm").text.strip() if item.select_one("div.bdg._dsct._sm") else ""
            link = "https://www.jumia.co.ke" + item.select_one("a.core")["href"]

            # ✅ ensure affiliate code is added correctly
            if "?" in link:
                link += f"&aff_id={AFF_ID}"
            else:
                link += f"?aff_id={AFF_ID}"

            deals.append({
                "title": title,
                "price": price,
                "old_price": old_price,
                "discount": discount,
                "link": link,
            })
        return deals
    except Exception as e:
        print(f"Error fetching from {url}: {e}")
        return []

def post_deals():
    category = random.choice(CATEGORIES)
    deals = fetch_deals(category)
    random.shuffle(deals)
    for deal in deals[:5]:  # post 5 deals every 10 min
        message = f"🛍️ {deal['title']}\n💰 {deal['price']} (was {deal['old_price']}) {deal['discount']}\n⚡️ Top Deal from Jumia!\n🔗 [Shop Now]({deal['link']})"
        bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown", disable_web_page_preview=False)
        time.sleep(10)  # 10s between posts

while True:
    post_deals()
    print("✅ Posted 5 new deals.")
    time.sleep(600)  # wait 10 minutes
