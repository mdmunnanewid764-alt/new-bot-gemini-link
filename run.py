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

def main():
    asyncio.run(startup_checks())
    
    from bot import main as start_bot
    start_bot()

if __name__ == "__main__":
    main()
