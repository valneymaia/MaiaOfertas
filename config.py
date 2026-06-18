import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_NAME = "affiliate_bot"
SOURCE_GROUPS = [group.strip() for group in os.getenv("SOURCE_GROUPS", "").split(",") if group.strip()]
TARGET_GROUP = os.getenv("TARGET_GROUP", "")

# Mercado Livre
ML_AFFILIATE_ID = os.getenv("ML_AFFILIATE_ID", "")
ML_AFFILIATE_WORD = os.getenv("ML_AFFILIATE_WORD", "")
ML_CREATE_LINK_COOKIE = os.getenv("ML_CREATE_LINK_COOKIE", "")
ML_CSRF_TOKEN = os.getenv("ML_CSRF_TOKEN", "")

# Amazon
AMAZON_AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "")

# Shopee
SHOPEE_AFFILIATE_ID = os.getenv("SHOPEE_AFFILIATE_ID", "")
SHOPEE_APP_ID = os.getenv("SHOPEE_APP_ID", "")
SHOPEE_APP_SECRET = os.getenv("SHOPEE_APP_SECRET", "")

# AliExpress
ALIEXPRESS_APP_KEY = os.getenv("ALIEXPRESS_APP_KEY", "")
ALIEXPRESS_APP_SECRET = os.getenv("ALIEXPRESS_APP_SECRET", "")
ALIEXPRESS_TRACKING_ID = os.getenv("ALIEXPRESS_TRACKING_ID", "")
