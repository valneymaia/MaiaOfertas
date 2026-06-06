import os

from dotenv import load_dotenv


load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

SESSION_NAME = "affiliate_bot"

SOURCE_GROUPS = [group.strip() for group in os.getenv("SOURCE_GROUPS", "").split(",") if group.strip()]
TARGET_GROUP = os.getenv("TARGET_GROUP", "")

ML_AFFILIATE_ID = os.getenv("ML_AFFILIATE_ID", "")
ML_AFFILIATE_WORD = os.getenv("ML_AFFILIATE_WORD", "")
ML_CREATE_LINK_COOKIE = os.getenv("ML_CREATE_LINK_COOKIE", "")
ML_CSRF_TOKEN = os.getenv("ML_CSRF_TOKEN", "")

AMAZON_AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "")
