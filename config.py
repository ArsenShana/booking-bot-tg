import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7390259573"))
_extra = os.getenv("EXTRA_ADMIN_IDS", "6255328618")
ADMIN_IDS = {ADMIN_ID} | {int(x) for x in _extra.split(',') if x.strip()}
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
API_URL = os.getenv("API_URL", "http://localhost:8002")
DB_PATH = os.getenv("DB_PATH", "/root/telegram_zaman/booking.db")
API_SECRET = os.getenv("API_SECRET", "zaman_secret_2026")
