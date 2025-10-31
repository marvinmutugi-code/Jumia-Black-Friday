import requests, random, time, os, json
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import schedule

load_dotenv()

TELEGRAM_BOT_TOKEN = "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
TELEGRAM_CHAT_ID = "-1003285979057"
AFF_ID = "5bed0bdf3d1ca"
BITLY_TOKEN = "77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b"

POSTED_FILE = "posted.json"

# ✅ Load posted deals (to prevent repeats)
if os.path.exists(POSTED_FILE):
    with open(POSTED_FILE, "r") as f:
        posted = set(json.load(f))
else:
    posted = set()

# ✅ Jumia top deals categories
CATEGORIES = [
    "https://www.jumia.co.ke/mlp-flash-sales/",
    "https://www.jumia.co.ke/mlp-top-deals/",
    "https://www.jumia.co.ke/smartphones/",
    "https://www.jumia.co.ke/computing/",
    "https://www.jumia.co.ke/home-appliances/",
    "https://www.jumia.co.ke/fashion/",
    "https://www.jumia.co.ke/health-beauty/",
    "https://www.jumia.co.ke/supermarket/",
]

def shorten_link(long_url):
    """Shorten URL using Bitly"""
    try:
        headers = {"Authorization": f"Bearer {BITLY_TOKEN}"}
        data = {"long_url": long_url}
        r = requests.post("https://api-ssl.bitly.com/v4/shorten", headers=headers, json=data)
        if r.status_code == 200:
            return r.json().get("link", long_url)
    except Exception as e:
        print("Bitly error:", e)
    return long_url

def fetch_deals():
    """Scrape 5 random hot deals"""
    url = random.choice(CATEGORIES)
    print(f"Fetching deals from {url}")
    html = requests.get(url, timeout=20).text
    soup = BeautifulSoup(html, "html.parser")

    items = soup.select("article.prd._fb.col.c-prd")
    deals = []

    for item in items[:20]:
        try:
            title = item.select_one("h3.name").text.strip()
            price = item.select_one("div.prc").text.strip()
            link = "https://www.jumia.co.ke" + item.select_one("a.core")["href"]
            old_price = item.select_one("div.old").text.strip() if item.select_one("div.old") else "N/A"
            discount = item.select_one("div.bdg._dsct").text.strip() if item.select_one("div.bdg._dsct") else "N/A"

            # Add affiliate tracking
            link = f"{link}?aff_id={AFF_ID}"
            short_link = shorten_link(link)

            deal_id = title + price
            if deal_id not in posted:
                deals.append({
                    "title": title,
                    "price": price,
                    "old_price": old_price,
                    "discount": discount,
                    "link": short_link
                })
        except Exception as e:
            continue

    return random.sample(deals, min(5, len(deals)))  # Pick 5 deals

def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    requests.post(url, data=payload)

def post_deals():
    global posted
    deals = fetch_deals()
    if not deals:
        print("No new deals found.")
        return

    for deal in deals:
        msg = (
            f"🛍️ <b>{deal['title']}</b>\n"
            f"💰 {deal['price']} (was {deal['old_price']}) 🔥 {deal['discount']} OFF!\n"
            f"⚡️ Hot Deal from Jumia\n"
            f"🔗 <a href='{deal['link']}'>Shop Now</a>"
        )
        send_to_telegram(msg)
        posted.add(deal['title'] + deal['price'])
        time.sleep(2)

    with open(POSTED_FILE, "w") as f:
        json.dump(list(posted), f)

# Run every 10 minutes
schedule.every(10).minutes.do(post_deals)

print("🤖 Auto-posting deals every 10 minutes...")
post_deals()

while True:
    schedule.run_pending()
    time.sleep(60)
