from __future__ import annotations

import os
import json
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
        "document": (filename, data, "text/vcard" if filename.endswith('.vcf') else "application/pdf"),
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


def send_text_with_buttons(message: str, buttons: list[list[dict]]):
    """
    Отправка текста с inline-кнопками через HTTP API Telegram.

    Args:
        message: Текст сообщения
        buttons: Список списков кнопок в формате [{"text": "...", "callback_data": "..."}]
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_TARGET_CHAT_ID is not set in .env")

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }

    # Добавляем клавиатуру, если есть кнопки
    if buttons:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": buttons
        })

    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram API error: {resp.text}")

    return resp.json()


def edit_message_text(chat_id: int | str, message_id: int, text: str,
                      buttons: list[list[dict]] | None = None):
    """Редактирование текста сообщения с опциональными кнопками."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})

    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram API error: {resp.text}")
    return resp.json()


def answer_callback_query(callback_query_id: str, text: str | None = None,
                          show_alert: bool = False):
    """Ответ на callback query"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload: dict[str, object] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True

    resp = requests.post(url, data=payload, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram API error: {resp.text}")
    return resp.json()

