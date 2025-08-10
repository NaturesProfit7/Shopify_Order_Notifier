import os
import requests
from dotenv import load_dotenv

load_dotenv()

def send_text(message: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_TARGET_CHAT_ID is not set in .env")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message
    }

    resp = requests.post(url, data=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram API error: {resp.text}")

    return resp.json()
