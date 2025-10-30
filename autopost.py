import os
import time
import requests

BOT_TOKEN = "8248716217:AAFlkDGIPGIIz1LHizS3OgSUdj94dp6C5-g"
CHAT_ID = "-1003285979057"
AFF_CODE = "5bed0bdf3d1ca"
BITLY_TOKEN = "77a3bc0d1d8e382c9dbd2b72efc8d748c0af814b"

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit("Missing BOT_TOKEN or CHAT_ID environment variable")

def send_deal():
    text = f"🔥 New Jumia Deal! Shop now ➡️ https://www.jumia.co.ke/mlp-black-friday/?aff={AFF_CODE}"
    resp = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                         data={"chat_id": CHAT_ID, "text": text})
    print("Telegram response:", resp.status_code, resp.text)
    return resp

if __name__ == "__main__":
    print("Starting autopost bot...")
    send_deal()
    while True:
        time.sleep(3600)  # wait 1 hour between posts
        send_deal()
added autopost script
fixed BITLY_TOKEN syntax
