from __future__ import annotations

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

def send_file(data: bytes, filename: str, caption: str | None = None):
    """
    Отправка документа в Telegram из памяти.
    Для VCF передаём MIME 'text/vcard' (можно и без него, но так корректнее).
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_TARGET_CHAT_ID is not set in .env")

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    files = {
        "document": (filename, data, "text/vcard"),
    }
    payload = {
        "chat_id": chat_id,
    }
    if caption:
        payload["caption"] = caption

    resp = requests.post(url, data=payload, files=files, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram API error: {resp.text}")
    return resp.json()