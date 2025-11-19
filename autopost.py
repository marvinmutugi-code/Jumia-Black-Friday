import os
import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# ========================
# CONFIGURATIONS
# ========================
TELEGRAM_TOKEN = "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
TELEGRAM_CHAT_ID = "-1003285979057"
AFF_CODE = "5bed0bdf3d1ca"
BITLY_TOKEN = "77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b"

JUMIA_URL = "https://www.jumia.co.ke/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

POST_INTERVAL_MINUTES = 60   # Fixed since you removed ENV version

app = Flask(__name__)


# ========================
# AFFILIATE LINK BUILDER
# ========================
def make_affiliate_link(url):
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query["aff_id"] = [AFF_CODE]   # Insert affiliate code

        new_query = urlencode(query, doseq=True)
        new_url = urlunparse(parsed._replace(query=new_query))

        return new_url
    except Exception as e:
        print("Affiliate link error:", e)
        return url


# ========================
# BITLY SHORTENER
# ========================
def shorten_link(long_url):
    try:
        res = requests.post(
            "https://api-ssl.bitly.com/v4/shorten",
            json={"long_url": long_url},
            headers={"Authorization": f"Bearer {BITLY_TOKEN}"}
        )

        if res.status_code == 200:
            return res.json().get("link", long_url)

        print("Bitly error:", res.text)
        return long_url

    except Exception as e:
        print("Bitly exception:", e)
        return long_url


# ========================
# TELEGRAM POSTER
# ========================
def send_to_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }

        r = requests.post(url, data=payload)
        print("Telegram Response:", r.text)
        return r.status_code == 200

    except Exception as e:
        print("Telegram Error:", e)
        return False


# ========================
# SCRAPER (Dummy – replace with your code)
# ========================
def fetch_deals():
    """
    Replace this with your real scraping logic.
    Must return:
    [
        {"name": "...", "price": "...", "url": "..."},
        ...
    ]
    """
    return [
        {
            "name": "Example Product",
            "price": "KSh 2,999",
            "url": "https://www.jumia.co.ke/example-product/?ref=home"
        }
    ]


# ========================
# AUTOPOST LOGIC
# ========================
def autopost_job():
    print("Running autopost job...")

    products = fetch_deals()

    for p in products:
        aff_link = make_affiliate_link(p["url"])
        short_link = shorten_link(aff_link)

        message = (
            f"🔥 <b>{p['name']}</b>\n"
            f"💰 Price: <b>{p['price']}</b>\n"
            f"👉 Buy here: {short_link}"
        )

        send_to_telegram(message)

    print("Job finished.")


# ========================
# FLASK ROUTES
# ========================
@app.route("/")
def home():
    return "Autopost service running."

@app.route("/test")
def test():
    send_to_telegram("🚀 Test message from your Render autopost bot!")
    return "Test message sent!"

@app.route("/trigger")
def trigger():
    autopost_job()
    return "Manual job triggered."


# ========================
# SCHEDULER
# ========================
scheduler = BackgroundScheduler()
scheduler.add_job(autopost_job, "interval", minutes=POST_INTERVAL_MINUTES)
scheduler.start()


# ========================
# MAIN APP
# ========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
