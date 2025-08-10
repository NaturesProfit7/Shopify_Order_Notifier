import os
from dotenv import load_dotenv

load_dotenv()  # Загружаем переменные из .env

def get_shopify_webhook_secret() -> str:
    secret = os.getenv("SHOPIFY_WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("SHOPIFY_WEBHOOK_SECRET is not set in .env")
    return secret
