import os
import requests
import random
import time
from bs4 import BeautifulSoup
from flask import Flask
import threading

# -----------------------------------
# 🔧 CONFIGURATION
# -----------------------------------
BOT_TOKEN = "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
CHAT_ID = "-1003285979057"
AFFILIATE_ID = "5bed0bdf3d1ca"
BITLY_TOKEN = "77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b"

# -----------------------------------
# 🌍 JUMIA CATEGORIES
# -----------------------------------
CATEGORIES = [
    "https://www.jumia.co.ke/mlp-black-friday/",
    "https://www.jumia.co.ke/smartphones/",
    "https://www.jumia.co.ke/televisions/",
    "https://www.jumia.co.ke/laptops/",
    "https://www.jumia.co.ke/health-beauty/",
    "https://www.jumia.co.ke/home-office/",
    "https://www.jumia.co.ke/fashion-men/",
    "https://www.jumia.co.ke/fashion-women/",
    "https://www.jumia.co.ke/groceries/",
    "https://www.jumia.co.ke/gaming/"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

# -----------------------------------
# 🔗 SHORTEN LINK WITH BITLY
# -----------------------------------
def shorten_link(long_url):
    try:
        bitly_url = "https://api-ssl.bitly.com/v4/shorten"
        headers = {"Authorization": f"Bearer {BITLY_TOKEN}", "Content-Type": "application/json"}
        payload = {"long_url": long_url}
        response = requests.post(bitly_url, headers=headers, json=payload)
        if response.status_code == 200:
            return response.json()["link"]
        else:
            print("⚠️ Bitly error:", response.text)
            return long_url
    except Exception as e:
        print("⚠️ Bitly shorten error:", e)
        return long_url

# -----------------------------------
# 🧩 SCRAPE TOP DEAL FROM CATEGORY
# -----------------------------------
def get_best_deal():
    category = random.choice(CATEGORIES)
    print(f"🔍 Checking category: {category}")
    response = requests.get(category, headers=HEADERS)
    soup = BeautifulSoup(response.text, "html.parser")
    products = soup.select("article.prd")

    if not products:
        print("⚠️ No products found.")
        return None

    best_deal = None
    best_discount = 0

    for prod in products:
        try:
            title_tag = prod.select_one("h3.name")
            price_tag = prod.select_one("div.prc")
            old_price_tag = prod.select_one("div.s-prc-w del")
            discount_tag = prod.select_one("div.bdg._dsct")
            link_tag = prod.find("a", href=True)

            if not title_tag or not price_tag or not link_tag:
                continue

            title = title_tag.text.strip()
            price = price_tag.text.strip()
            old_price = old_price_tag.text.strip() if old_price_tag else "N/A"
            discount_text = discount_tag.text.strip() if discount_tag else "0%"
            discount_value = int(discount_text.replace("%", "").replace("-", ""))

            link = "https://www.jumia.co.ke" + link_tag["href"]
            full_link = f"{link}?aff_id={AFFILIATE_ID}"

            if discount_value > best_discount:
                best_discount = discount_value
                best_deal = {
                    "title": title,
                    "price": price,
                    "old_price": old_price,
                    "discount": f"{discount_value}%",
                    "link": full_link
                }
        except Exception:
            continue

    if best_deal:
        best_deal["short_link"] = shorten_link(best_deal["link"])
    return best_deal

# -----------------------------------
# 💬 FORMAT MESSAGE
# -----------------------------------
def format_message(item):
    return (
        f"🛍️ <b>{item['title']}</b>\n"
        f"💰 <b>{item['price']}</b> (was {item['old_price']}) 🔥 {item['discount']} OFF!\n"
        f"⚡️ Top Deal of the Hour from Jumia!\n"
        f"🔗 <a href=\"{item['short_link']}\">Shop Now</a>\n\n"
        f"Powered by MediReach Digital Deals 🤖"
    )

# -----------------------------------
# 🚀 POST TO TELEGRAM
# -----------------------------------
def post_to_telegram(item):
    message = format_message(item)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    response = requests.post(url, data=payload)
    if response.status_code == 200:
        print("✅ Deal posted successfully!")
    else:
        print("❌ Telegram post failed:", response.text)

# -----------------------------------
# 🕒 MAIN POST LOOP
# -----------------------------------
def run_poster():
    while True:
        print("⏳ Fetching top discount deal...")
        deal = get_best_deal()
        if deal:
            post_to_telegram(deal)
        else:
            print("⚠️ No deal found this round.")
        print("⏰ Sleeping for 1 hour...\n")
        time.sleep(3600)

# -----------------------------------
# 🌐 KEEP-ALIVE SERVER (Render/Replit)
# -----------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 Jumia Auto Poster running — Powered by MediReach!"

def run_server():
    app.run(host="0.0.0.0", port=8080)

# -----------------------------------
# 🏁 START EVERYTHING
# -----------------------------------
if __name__ == "__main__":
    threading.Thread(target=run_server).start()
    run_poster()
