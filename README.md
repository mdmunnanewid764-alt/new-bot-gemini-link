# 🛒 Telegram Digital Shop Bot

A high-performance, asynchronous Telegram Shop Bot built with Python (`python-telegram-bot`, `httpx`, `aiosqlite`) integrated with the [Shop API](https://upibot.00969600.xyz/shop-api/docs).

## Features

- 🛒 **Interactive Product Catalog**: Browse products with live prices and stock counts.
- 🔢 **Quantity Selector**: Choose 1–20 items with interactive `+` / `-` controls.
- ⚡ **Instant Automated Delivery**: Purchase items directly from your shop deposit balance; account credentials/keys are formatted into tap-to-copy code blocks.
- 🛡️ **Idempotency Safeguard**: Built-in unique idempotency key generation to prevent double-charging.
- 📜 **Order History**: View past orders and retrieve delivered credentials anytime.
- 👤 **Account Balance Checker**: Check your shop deposit balance and account status.
- ⚙️ **Admin Control Panel**:
  - `/setkey <api_key>` - Dynamically update the Shop API key.
  - `/balance` - Check supplier account deposit balance.
  - `/stats` - Real-time statistics (total users, total orders, revenue).
  - `/broadcast <message>` - Broadcast announcements to all bot users.

---

## Configuration

The bot uses `.env` for its initial configuration:

```env
TELEGRAM_BOT_TOKEN=8934646392:AAGNMWA0AftNgJ56SXBuxzzVOk0qHkOkgVg
ADMIN_ID=6575066703
SHOP_API_BASE_URL=https://upibot.00969600.xyz/shop-api/v1
SHOP_API_KEY=sk_shop_xxxxxxxx
```

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Your Shop API Key

- Get your API key from [@scanupigptbot](https://t.me/scanupigptbot) by tapping 🛒 **Shop** -> 🔑 **API Key** -> **Create API key**.
- Paste it into `.env` under `SHOP_API_KEY=` OR launch the bot and send `/setkey sk_shop_xxxxxxxx` in Telegram!

### 3. Run the Bot

```bash
python run.py
```

---

## Bot Commands

| Command | Permission | Description |
| :--- | :--- | :--- |
| `/start` | Everyone | Open the main menu & shopping catalog |
| `/admin` | Admin Only | Open the Admin Control Panel |
| `/setkey <key>` | Admin Only | Update the Shop API key |
| `/balance` | Admin Only | Check deposit balance on supplier account |
| `/stats` | Admin Only | Display user & order statistics |
| `/broadcast <msg>`| Admin Only | Send a broadcast message to all users |

---

## Project Structure

```
├── bot.py           # Telegram handlers, inline keyboard UI, order flow
├── shop_api.py      # Async HTTP client for Shop API (httpx)
├── database.py      # SQLite database manager (users, orders, settings)
├── run.py           # Startup checks and application entry point
├── requirements.txt # Python dependencies
├── .env             # Environment configuration file
└── bot_data.db      # SQLite database file (created automatically)
```
