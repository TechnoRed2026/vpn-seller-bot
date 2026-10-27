# Vpn Seller Bot

## English

Telegram bot for selling and managing VPN accounts through a compatible 3x-ui panel. Includes a customer shop, wallet and receipt review, account management, configurable trials, referral rewards, and administrator tools. The bot interface is primarily Persian.

### Setup

Requires Python 3.10 or newer, a Telegram bot token, and a reachable compatible 3x-ui panel with an API key. Panel capabilities vary by version; verify compatibility before accepting payments.

```sh
git clone https://github.com/TechnoRed2026/vpn-seller-bot.git
cd vpn-seller-bot
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

On Windows, activate the environment with `.venv\Scripts\Activate.ps1` in PowerShell.

Create a private local `.env` file using your own values:

```dotenv
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ADMIN_IDS=YOUR_TELEGRAM_USER_ID
XUI_URL=https://panel.example.com
XUI_API_KEY=YOUR_PANEL_API_KEY
VERIFY_SSL=true
```

`ADMIN_IDS` accepts comma-separated numeric Telegram user IDs. Replace all placeholders before starting. Set `XUI_BASE_PATH` if your panel uses a custom base path. `XUI_USER` and `XUI_PASS` configure panel login when required by your deployment.

```sh
python bot.py
```

Run one instance per bot token. The bot uses Telegram polling; no public webhook endpoint is required.

### Configuration

- Payments: set `PAYMENT_GROUP_ID` and `CARD_NUMBER` before accepting receipt-based payments. Review `PRICE_PER_GB`, discounts, and the fixed `PLAN_PRICES` in `config.py`; prices use thousand toman units.
- Optional notifications: `LOG_GROUP_ID` and `BACKUP_CHAT_ID`.
- Optional membership requirement: `FORCE_JOIN_CHANNEL_ID` and `FORCE_JOIN_CHANNEL_URL`; give the bot the appropriate channel permissions.
- Optional support link: `SUPPORT_URL`.
- Panel subscription links: `XUI_SUB_BASE_URL`. Restrict shop inbounds with comma-separated `SHOP_INBOUNDS`.
- Trials and referrals: review `TEST_ACCOUNT_*`, `REFERRAL_ENABLED`, and `REFERRAL_CONFIG_*` in `config.py` before enabling them.
- Optional proxy: `USE_PROXY` and `PROXY_URL`.

Runtime state is stored locally in `data.json`. Keep backups private: state may include customer identifiers, balances and account details. Never commit environment files, logs, certificates, private keys, or runtime data. No operator credentials or customer data are included in this repository. Keep TLS verification enabled and use a valid panel certificate.

## فارسی

ربات تلگرام برای فروش و مدیریت حساب VPN از طریق پنل سازگار 3x-ui. شامل فروشگاه، کیف پول و بررسی رسید، مدیریت حساب، تست قابل تنظیم، پاداش معرفی و ابزارهای مدیر است. رابط ربات عمدتاً فارسی است.

### نصب و اجرا

Python نسخهٔ ۳.۱۰ یا جدیدتر، توکن ربات تلگرام و پنل 3x-ui سازگار با کلید API لازم است. امکانات API به نسخهٔ پنل بستگی دارد؛ قبل از دریافت وجه، سازگاری پنل را بررسی کنید.

```sh
git clone https://github.com/TechnoRed2026/vpn-seller-bot.git
cd vpn-seller-bot
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

در PowerShell ویندوز، محیط را با `.venv\Scripts\Activate.ps1` فعال کنید.

یک فایل خصوصی `.env` روی سیستم خود بسازید و مقادیر خودتان را وارد کنید:

```dotenv
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ADMIN_IDS=YOUR_TELEGRAM_USER_ID
XUI_URL=https://panel.example.com
XUI_API_KEY=YOUR_PANEL_API_KEY
VERIFY_SSL=true
```

متغیر `ADMIN_IDS` شناسه‌های عددی مدیران را با جداکنندهٔ ویرگول می‌پذیرد. همهٔ مقادیر نمونه را پیش از اجرا جایگزین کنید. برای مسیر اختصاصی پنل، `XUI_BASE_PATH` را تنظیم کنید. در صورت نیاز به ورود با حساب پنل، `XUI_USER` و `XUI_PASS` را هم تنظیم کنید.

```sh
python bot.py
```

برای هر توکن فقط یک نمونه اجرا کنید. ربات از polling استفاده می‌کند و به آدرس عمومی webhook نیاز ندارد.

### تنظیمات

- پرداخت: پیش از پذیرش رسید، `PAYMENT_GROUP_ID` و `CARD_NUMBER` را تنظیم کنید. قیمت هر گیگابایت، تخفیف‌ها و جدول `PLAN_PRICES` در `config.py` را بررسی کنید؛ واحد قیمت هزار تومان است.
- اعلان و پشتیبان اختیاری: `LOG_GROUP_ID` و `BACKUP_CHAT_ID`.
- عضویت اجباری اختیاری: `FORCE_JOIN_CHANNEL_ID` و `FORCE_JOIN_CHANNEL_URL`؛ دسترسی لازم را به ربات در کانال بدهید.
- لینک پشتیبانی اختیاری: `SUPPORT_URL`.
- لینک اشتراک پنل: `XUI_SUB_BASE_URL`. برای محدودکردن ورودی‌های فروشگاه از `SHOP_INBOUNDS` با جداکنندهٔ ویرگول استفاده کنید.
- پیش از فعال‌کردن تست و معرفی، تنظیمات `TEST_ACCOUNT_*`، `REFERRAL_ENABLED` و `REFERRAL_CONFIG_*` را در `config.py` بررسی کنید.
- پراکسی اختیاری: `USE_PROXY` و `PROXY_URL`.

وضعیت اجرایی در `data.json` ذخیره می‌شود. نسخه‌های پشتیبان ممکن است شامل شناسهٔ مشتری، موجودی و اطلاعات حساب باشند؛ آن‌ها را خصوصی نگه دارید. فایل محیط، لاگ، گواهی، کلید خصوصی و دادهٔ اجرایی را commit نکنید. اطلاعات ورود اپراتور یا دادهٔ مشتری در این مخزن قرار ندارد. اعتبارسنجی TLS را فعال نگه دارید و از گواهی معتبر پنل استفاده کنید.
