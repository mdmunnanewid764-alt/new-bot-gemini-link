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

DEFAULT_BINANCE_ENDPOINTS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]

class BinanceAPIClient:
    def __init__(self, base_url: Optional[str] = None):
        if base_url:
            self.endpoints = [base_url.rstrip("/")]
        else:
            custom_url = os.getenv("BINANCE_BASE_URL")
            if custom_url:
                self.endpoints = [custom_url.rstrip("/")] + DEFAULT_BINANCE_ENDPOINTS
            else:
                self.endpoints = list(DEFAULT_BINANCE_ENDPOINTS)

    async def get_credentials(self) -> tuple[Optional[str], Optional[str]]:
        """Fetch Binance API Key & Secret from database or .env."""
        api_key = await database.get_setting("binance_api_key")
        if not api_key:
            api_key = os.getenv("BINANCE_API_KEY")

        api_secret = await database.get_setting("binance_api_secret")
        if not api_secret:
            api_secret = os.getenv("BINANCE_API_SECRET")

        return (api_key.strip() if api_key else None, api_secret.strip() if api_secret else None)

    async def get_proxy(self) -> Optional[str]:
        """Fetch Proxy URL from DB or environment."""
        proxy = await database.get_setting("binance_proxy")
        if not proxy:
            proxy = os.getenv("BINANCE_PROXY_URL") or os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        return proxy.strip() if proxy else None

    def _sign(self, query_string: str, secret_key: str) -> str:
        """Create HMAC-SHA256 signature for Binance API."""
        return hmac.new(
            secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    async def get_server_time_offset(self, client: httpx.AsyncClient, base_url: str) -> int:
        """Fetch server time from Binance and calculate offset relative to local clock."""
        try:
            r = await client.get(f"{base_url}/api/v3/time")
            if r.status_code == 200:
                server_time = r.json().get("serverTime")
                local_time = int(time.time() * 1000)
                return server_time - local_time
        except Exception:
            pass
        return 0

    async def get_live_balances(self) -> Dict[str, Any]:
        """
        Fetch Live Spot and Funding balances from Binance account across available endpoints.
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

        proxy = await self.get_proxy()
        client_kwargs = {"timeout": 12.0}
        if proxy:
            client_kwargs["proxy"] = proxy

        last_error = "Unknown error"

        async with httpx.AsyncClient(**client_kwargs) as client:
            for base_url in self.endpoints:
                try:
                    offset = await self.get_server_time_offset(client, base_url)
                    timestamp = int(time.time() * 1000) + offset
                    query_params = f"timestamp={timestamp}&recvWindow=60000"
                    signature = self._sign(query_params, api_secret)
                    url = f"{base_url}/api/v3/account?{query_params}&signature={signature}"

                    # 1. Fetch Spot Wallet Balances
                    res = await client.get(url, headers=headers)
                    if res.status_code == 418 or res.status_code == 429:
                        last_error = f"Binance Rate/IP Limit on {base_url} ({res.status_code}): {res.text}"
                        logger.warning(f"Endpoint {base_url} IP limited/banned. Trying next cluster endpoint...")
                        continue

                    if res.status_code != 200:
                        err_msg = res.json().get("msg", res.text)
                        return {
                            "success": False,
                            "error": f"Binance API Error ({res.status_code}): {err_msg}"
                        }

                    account_data = res.json()
                    spot_assets = []
                    funding_assets = []
                    total_usdt_spot = 0.0
                    total_usdt_funding = 0.0

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
                        f_url = f"{base_url}/sapi/v1/asset/get-funding-asset?{f_query}&signature={f_signature}"
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
                    last_error = str(e)
                    logger.warning(f"Error calling {base_url}: {e}")
                    continue

        return {"success": False, "error": last_error}

    async def get_live_deposit_history(self, limit: int = 10, coin: Optional[str] = None) -> Dict[str, Any]:
        """Fetch latest live deposits from Binance account."""
        api_key, api_secret = await self.get_credentials()
        if not api_key or not api_secret:
            return {
                "success": False,
                "error": "Binance API Key and Secret Key are not configured."
            }

        headers = {
            "X-MBX-APIKEY": api_key,
            "Content-Type": "application/json"
        }

        proxy = await self.get_proxy()
        client_kwargs = {"timeout": 15.0}
        if proxy:
            client_kwargs["proxy"] = proxy

        last_error = "Unknown error"

        async with httpx.AsyncClient(**client_kwargs) as client:
            for base_url in self.endpoints:
                try:
                    offset = await self.get_server_time_offset(client, base_url)
                    timestamp = int(time.time() * 1000) + offset
                    params_list = [f"timestamp={timestamp}", "recvWindow=60000"]
                    if coin:
                        params_list.append(f"coin={coin.upper()}")
                    if limit:
                        params_list.append(f"limit={limit}")

                    query = "&".join(params_list)
                    signature = self._sign(query, api_secret)
                    url = f"{base_url}/sapi/v1/capital/deposit/hisrec?{query}&signature={signature}"

                    res = await client.get(url, headers=headers)
                    if res.status_code == 200:
                        return {
                            "success": True,
                            "deposits": res.json()
                        }
                    elif res.status_code in (418, 429):
                        last_error = f"Binance IP limit on {base_url} ({res.status_code})"
                        continue
                    else:
                        err_msg = res.json().get("msg", res.text)
                        return {
                            "success": False,
                            "error": f"Binance API Error ({res.status_code}): {err_msg}"
                        }
                except Exception as e:
                    last_error = str(e)
                    continue

        return {"success": False, "error": last_error}

    async def get_recent_deposits(self, coin: str = "USDT", limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent crypto deposits history into Binance account."""
        res = await self.get_live_deposit_history(limit=limit, coin=coin)
        if res.get("success"):
            return res.get("deposits", [])
        return []
