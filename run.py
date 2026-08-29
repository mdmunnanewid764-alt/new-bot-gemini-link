import asyncio
import logging
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

import database
from shop_api import ShopAPIClient

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"OK - Telegram Shop Bot is live and running!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress routine health check logs from spamming
        return

def start_health_server():
    """Start an HTTP health-check server for Render Web Service compatibility."""
    port_str = os.getenv("PORT")
    if port_str:
        port = int(port_str)
    else:
        # Default port if PORT is not set
        port = 8080
    
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Health check HTTP server started on port {port} for Render Free Web Service.")
    except Exception as e:
        logger.warning(f"Could not start HTTP health server on port {port}: {e}")

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
    start_health_server()
    asyncio.run(startup_checks())
    
    from bot import main as start_bot
    start_bot()

if __name__ == "__main__":
    main()
