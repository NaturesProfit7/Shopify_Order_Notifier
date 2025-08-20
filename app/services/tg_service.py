from __future__ import annotations

import os
import json
import requests
from pathlib import Path

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
    """Отправка документа в Telegram из памяти.

    MIME-тип выбирается на основании расширения файла: для PDF используется
    ``application/pdf``, для ``.vcf`` — ``text/vcard``. Для остальных
    файлов используется ``application/octet-stream``.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_TARGET_CHAT_ID is not set in .env")

    url = f"https://api.telegram.org/bot{token}/sendDocument"

    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        mime = "application/pdf"
    elif suffix in {".vcf", ".vcard"}:
        mime = "text/vcard"
    else:
        mime = "application/octet-stream"

    files = {"document": (filename, data, mime)}
    payload = {"chat_id": chat_id}
    if caption:
        payload["caption"] = caption

    resp = requests.post(url, data=payload, files=files, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram API error: {resp.text}")
    return resp.json()

def send_text_with_buttons(message: str, buttons: list[list[dict]]):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_TARGET_CHAT_ID is not set")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "reply_markup": json.dumps({"inline_keyboard": buttons}),
    }
    r = requests.post(url, data=payload, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram API error: {r.text}")
    return r.json()

def answer_callback_query(callback_query_id: str, text: str | None = None, show_alert: bool = False):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = "true" if show_alert else "false"
    r = requests.post(url, data=payload, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram API error: {r.text}")
    return r.json()

def edit_message_text(chat_id: str, message_id: int, new_text: str, buttons: list[list[dict]] | None = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": new_text}
    if buttons is not None:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    r = requests.post(url, data=payload, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram API error: {r.text}")
    return r.json()
