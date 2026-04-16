import os

# توکن ربات تلگرام - از متغیرهای محیطی خوانده می‌شود
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# آیدی عددی ادمین‌ها. (اگر خالی باشد، اولین نفری که ربات را استارت کند ادمین می‌شود)
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# تنظیمات درگاه زرین پال
ZARINPAL_MERCHANT = os.getenv("ZARINPAL_MERCHANT", "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
ZARINPAL_SANDBOX = os.getenv("ZARINPAL_SANDBOX", "true").lower() == "true"

# پایگاه داده محلی (SQLite) که بدون نیاز به نصب سرور، اطلاعات را نگه می‌دارد.
DB_URL = os.getenv("DB_URL", "sqlite+aiosqlite:///ecommerce.db")
