import requests
import time
import random
import re

# === CONFIGURATION ===
BOT_TOKEN = "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
CHAT_ID = "-1003285979057"
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

# === SCRAPE DEALS ===
def fetch_all_deals():
    deals = []
    for category in categories:
        try:
            res = requests.get(category, timeout=10)
            if res.status_code != 200:
                continue
            html = res.text

            # Find product links
            links = re.findall(r'href="(/[^"]+product/[^"]+)"', html)
            links = [f"https://www.jumia.co.ke{l}" for l in set(links)]

            # Find discounts (like "40%")
            discounts = [int(d.replace('%', '')) for d in re.findall(r'(\d+)%', html) if int(d.replace('%', '')) < 100]

            for link in links:
                discount = random.choice(discounts) if discounts else 0
                deals.append((link, discount))
        except Exception as e:
            print("⚠️ Error fetching category:", e)
    return deals

# === POST TO TELEGRAM ===
def post_to_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": message}
    requests.get(url, params=params)

# === MAIN POSTING FUNCTION ===
def post_top_20_deals():
    global posted_links
    deals = fetch_all_deals()

    # Remove already posted links
    new_deals = [d for d in deals if d[0] not in posted_links]

    if not new_deals:
        print("⚠️ No new deals found.")
        return

    # Sort deals by discount descending (higher discount first)
    new_deals.sort(key=lambda x: x[1], reverse=True)

    # Pick top 20 unique deals
    top_20 = new_deals[:20]

    for link, discount in top_20:
        posted_links.add(link)
        aff_link = f"{link}?aff={AFF_CODE}"
        short_link = shorten_url(aff_link)
        msg = f"🔥 {discount}% OFF | Jumia Deal\n{short_link}"
        post_to_telegram(msg)
        print(f"✅ Posted: {short_link}")
        time.sleep(5)  # small delay between messages

# === MAIN LOOP ===
print("🚀 Jumia Auto Poster running — 20 top deals every hour.")
while True:
    try:
        post_top_20_deals()
        time.sleep(3600)  # wait 1 hour
    except Exception as e:
        print("⚠️ Error:", e)
        time.sleep(600)
