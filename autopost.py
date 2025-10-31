import os
import time
import random
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import schedule

# Load environment variables
load_dotenv()

# === Your credentials ===
TELEGRAM_BOT_TOKEN = "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
TELEGRAM_CHAT_ID = "-1003285979057"
BITLY_TOKEN ="77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b"
AFFILIATE_CODE = "5bed0bdf3d1ca"

POSTED_LINKS_FILE = "posted_links.txt"


# === Bitly Shortener ===
def shorten_link(long_url):
    try:
        headers = {"Authorization": f"Bearer {BITLY_TOKEN}", "Content-Type": "application/json"}
        data = {"long_url": long_url}
        r = requests.post("https://api-ssl.bitly.com/v4/shorten", json=data, headers=headers)
        if r.status_code == 200:
            return r.json()["link"]
    except Exception as e:
        print(f"⚠️ Bitly error: {e}")
    return long_url


# === Read/Save posted links ===
def get_posted_links():
    if not os.path.exists(POSTED_LINKS_FILE):
        return set()
    with open(POSTED_LINKS_FILE, "r") as f:
        return set(f.read().splitlines())


def save_posted_link(link):
    with open(POSTED_LINKS_FILE, "a") as f:
        f.write(link + "\n")


# === Scrape Deals ===
def scrape_deals(url):
    print(f"🕵️ Scraping: {url}")
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(res.text, "html.parser")

    deals = []
    products = soup.find_all("a", class_="core", limit=40)

    for p in products:
        try:
            title = p.find("h3", class_="name").text.strip()
            price = p.find("div", class_="prc").text.strip()
            discount_tag = p.find("div", class_="bdg _dsct _sm")
            discount = discount_tag.text.strip().replace("-", "").replace("%", "") if discount_tag else "0"
            link = "https://www.jumia.co.ke" + p["href"]

            # ✅ Add affiliate code
            if "?" in link:
                link += f"&{AFFILIATE_CODE}"
            else:
                link += f"?{AFFILIATE_CODE}"

            deals.append({
                "title": title,
                "price": price,
                "discount": int(discount) if discount.isdigit() else 0,
                "link": link
            })
        except Exception:
            continue

    # Sort by top discounts
    deals = sorted(deals, key=lambda x: x["discount"], reverse=True)
    return deals[:5]


# === Telegram Message Sender ===
def send_telegram_message(deal):
    short_link = shorten_link(deal["link"])
    message = (
        f"🔥 *{deal['title']}*\n"
        f"💰 Price: {deal['price']}\n"
        f"💸 Discount: {deal['discount']}% OFF\n\n"
        f"👉 Get it here: {short_link}\n"
        f"⚡️ #JumiaBlackFriday #Deals #Offers"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    r = requests.post(url, data=data)
    if r.status_code == 200:
        print(f"✅ Posted: {deal['title']}")
    else:
        print(f"❌ Failed: {deal['title']} — {r.text}")


# === Main Posting Function ===
def post_deals():
    print("🔁 Fetching new Jumia deals...")
    categories = [
        "https://www.jumia.co.ke/mlp-black-friday/",
        "https://www.jumia.co.ke/phones-tablets/",
        "https://www.jumia.co.ke/electronics/",
        "https://www.jumia.co.ke/fashion/",
        "https://www.jumia.co.ke/home-office/",
        "https://www.jumia.co.ke/health-beauty/",
        "https://www.jumia.co.ke/supermarket/",
        "https://www.jumia.co.ke/baby-products/",
        "https://www.jumia.co.ke/computing/",
        "https://www.jumia.co.ke/gaming/"
    ]

    random.shuffle(categories)
    posted = get_posted_links()

    for category in categories:
        deals = scrape_deals(category)
        for deal in deals:
            if deal["link"] not in posted:
                send_telegram_message(deal)
                save_posted_link(deal["link"])
                posted.add(deal["link"])
                time.sleep(random.randint(6, 15))
        time.sleep(random.randint(10, 20))

    print("✅ Finished this round!")


# === Scheduler (Every 10 minutes) ===
schedule.every(10).minutes.do(post_deals)
print("🤖 AutoPoster running! Posting every 10 minutes...")

# Run immediately
post_deals()

while True:
    schedule.run_pending()
    time.sleep(5)
