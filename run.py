import asyncio
import logging
import os
import sys
from dotenv import load_dotenv

import database
from shop_api import ShopAPIClient

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def startup_checks():
    logger.info("Initializing database...")
    await database.init_db()
    logger.info("Database initialized successfully.")

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    admin_id = os.getenv("ADMIN_ID")
    
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is missing in environment or .env file.")
        sys.exit(1)
        
    logger.info(f"Bot Token configured: {bot_token[:10]}...")
    logger.info(f"Admin Telegram ID configured: {admin_id}")

    api_client = ShopAPIClient()
    key = await api_client.get_api_key()
    if key:
        logger.info(f"Shop API Key configured: {key[:8]}...")
        try:
            me = await api_client.get_me()
            logger.info(f"Connected to Shop API! Deposit Balance: ${me.get('deposit_balance', 0.0):.2f} USD")
        except Exception as e:
            logger.warning(f"Could not connect to Shop API with key: {e}")
    else:
        logger.warning("Shop API Key is not set yet! You can set it in .env or send /setkey <YOUR_KEY> to the bot as admin.")

def main():
    asyncio.run(startup_checks())
    
    from bot import main as start_bot
    start_bot()

if __name__ == "__main__":
    main()
