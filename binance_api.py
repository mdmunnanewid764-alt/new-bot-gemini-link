import os
import time
import hmac
import hashlib
import httpx
import logging
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
import database

load_dotenv()
logger = logging.getLogger(__name__)

BINANCE_BASE_URL = "https://api.binance.com"

class BinanceAPIClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or BINANCE_BASE_URL).rstrip("/")

    async def get_credentials(self) -> tuple[Optional[str], Optional[str]]:
        """Fetch Binance API Key & Secret from database or .env."""
        api_key = await database.get_setting("binance_api_key")
        if not api_key:
            api_key = os.getenv("BINANCE_API_KEY")

        api_secret = await database.get_setting("binance_api_secret")
        if not api_secret:
            api_secret = os.getenv("BINANCE_API_SECRET")

        return (api_key.strip() if api_key else None, api_secret.strip() if api_secret else None)

    def _sign(self, query_string: str, secret_key: str) -> str:
        """Create HMAC-SHA256 signature for Binance API."""
        return hmac.new(
            secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    async def get_server_time_offset(self, client: httpx.AsyncClient) -> int:
        """Fetch server time from Binance and calculate offset relative to local clock."""
        try:
            r = await client.get(f"{self.base_url}/api/v3/time")
            if r.status_code == 200:
                server_time = r.json().get("serverTime")
                local_time = int(time.time() * 1000)
                return server_time - local_time
        except Exception:
            pass
        return 0

    async def get_live_balances(self) -> Dict[str, Any]:
        """
        Fetch Live Spot and Funding balances from Binance account.
        """
        api_key, api_secret = await self.get_credentials()
        if not api_key or not api_secret:
            return {
                "success": False,
                "error": "Binance API Key and Secret Key are not configured yet."
            }

        headers = {
            "X-MBX-APIKEY": api_key,
            "Content-Type": "application/json"
        }

        spot_assets = []
        funding_assets = []
        total_usdt_spot = 0.0
        total_usdt_funding = 0.0

        proxy = os.getenv("BINANCE_PROXY_URL") or os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        client_kwargs = {"timeout": 12.0}
        if proxy:
            client_kwargs["proxy"] = proxy

        async with httpx.AsyncClient(**client_kwargs) as client:
            try:
                offset = await self.get_server_time_offset(client)
                timestamp = int(time.time() * 1000) + offset
                query_params = f"timestamp={timestamp}&recvWindow=60000"
                signature = self._sign(query_params, api_secret)
                url = f"{self.base_url}/api/v3/account?{query_params}&signature={signature}"

                # 1. Fetch Spot Wallet Balances
                res = await client.get(url, headers=headers)
                if res.status_code != 200:
                    err_msg = res.json().get("msg", res.text)
                    return {
                        "success": False,
                        "error": f"Binance API Error ({res.status_code}): {err_msg}"
                    }

                account_data = res.json()
                for b in account_data.get("balances", []):
                    asset = b["asset"]
                    free = float(b["free"])
                    locked = float(b["locked"])
                    total = free + locked
                    if total > 0.0001:
                        spot_assets.append({
                            "asset": asset,
                            "free": free,
                            "locked": locked,
                            "total": total
                        })
                        if asset.upper() in ("USDT", "BUSD", "FDUSD", "USDC"):
                            total_usdt_spot += total

                # 2. Fetch Funding Wallet Balances
                try:
                    f_timestamp = int(time.time() * 1000) + offset
                    f_query = f"timestamp={f_timestamp}&recvWindow=60000"
                    f_signature = self._sign(f_query, api_secret)
                    f_url = f"{self.base_url}/sapi/v1/asset/get-funding-asset?{f_query}&signature={f_signature}"
                    f_res = await client.post(f_url, headers=headers)
                    if f_res.status_code == 200:
                        funding_list = f_res.json()
                        for fb in funding_list:
                            asset = fb["asset"]
                            free = float(fb["free"])
                            locked = float(fb.get("locked", 0.0)) + float(fb.get("freeze", 0.0))
                            total = free + locked
                            if total > 0.0001:
                                funding_assets.append({
                                    "asset": asset,
                                    "free": free,
                                    "locked": locked,
                                    "total": total
                                })
                                if asset.upper() in ("USDT", "BUSD", "FDUSD", "USDC"):
                                    total_usdt_funding += total
                except Exception as fe:
                    logger.warning(f"Could not fetch funding assets: {fe}")

                return {
                    "success": True,
                    "account_type": account_data.get("accountType", "SPOT"),
                    "can_deposit": account_data.get("canDeposit", True),
                    "can_trade": account_data.get("canTrade", True),
                    "total_usdt_spot": total_usdt_spot,
                    "total_usdt_funding": total_usdt_funding,
                    "total_usdt_all": total_usdt_spot + total_usdt_funding,
                    "spot_assets": spot_assets,
                    "funding_assets": funding_assets
                }

            except Exception as e:
                logger.error(f"Error fetching Binance balances: {e}")
                return {"success": False, "error": str(e)}

    async def get_recent_deposits(self, coin: str = "USDT", limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent crypto deposits history into Binance account."""
        api_key, api_secret = await self.get_credentials()
        if not api_key or not api_secret:
            return []

        headers = {"X-MBX-APIKEY": api_key}
        proxy = os.getenv("BINANCE_PROXY_URL") or os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        client_kwargs = {"timeout": 12.0}
        if proxy:
            client_kwargs["proxy"] = proxy

        async with httpx.AsyncClient(**client_kwargs) as client:
            try:
                offset = await self.get_server_time_offset(client)
                timestamp = int(time.time() * 1000) + offset
                query = f"coin={coin}&status=1&limit={limit}&timestamp={timestamp}&recvWindow=60000"
                signature = self._sign(query, api_secret)
                url = f"{self.base_url}/sapi/v1/capital/deposit/hisrec?{query}&signature={signature}"

                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    return res.json()
            except Exception as e:
                logger.error(f"Error fetching Binance deposit history: {e}")
        return []
