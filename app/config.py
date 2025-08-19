import os
from dotenv import load_dotenv

load_dotenv()  # Загружаем переменные из .env

def get_shopify_webhook_secret() -> str:
    secret = os.getenv("SHOPIFY_WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("SHOPIFY_WEBHOOK_SECRET is not set in .env")
    return secret

def get_telegram_secret_token() -> str | None:
    # не обязателен; если задан — проверяем заголовок X-Telegram-Bot-Api-Secret-Token
    return os.getenv("TELEGRAM_WEBHOOK_SECRET_TOKEN") or None