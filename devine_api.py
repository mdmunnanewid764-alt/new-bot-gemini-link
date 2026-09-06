import os
import time
import uuid
import httpx
import asyncio
import logging
from typing import Optional, Dict, Any, List
import database
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_DEVINE_BASE_URL = "https://api.aisubscriptions.shop"

class DevineAPIError(Exception):
    def __init__(self, message: str, status_code: int = 500, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data or {}

class DevineAPIClient:
    def __init__(self, base_url: Optional[str] = None):
        self._custom_base_url = base_url

    async def get_base_url(self) -> str:
        if self._custom_base_url:
            return self._custom_base_url.rstrip("/")
        db_url = await database.get_setting("devine_api_base_url")
        if db_url:
            return db_url.rstrip("/")
        env_url = os.getenv("DEVINE_API_BASE_URL") or os.getenv("DEVINE_BASE_URL")
        if env_url:
            return env_url.rstrip("/")
        return DEFAULT_DEVINE_BASE_URL.rstrip("/")

    async def get_api_key(self) -> Optional[str]:
        """Fetch Devine API key from database settings or .env."""
        key = await database.get_setting("devine_api_key")
        if not key:
            key = os.getenv("DEVINE_API_KEY")
        return key.strip() if key else None

    async def _get_headers(self, requires_auth: bool = True) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if requires_auth:
            key = await self.get_api_key()
            if not key:
                raise DevineAPIError("Devine API Key is not configured. Please set it using /setkey2 command in Telegram.", status_code=401)
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        try:
            data = response.json()
        except Exception:
            data = {"message": response.text}

        if response.status_code in (200, 201) and data.get("ok", True):
            return data

        err_code = data.get("error") or ""
        msg = data.get("message") or err_code or "Devine API request failed"

        if response.status_code == 400:
            msg = f"❌ Bad Request (400): {msg}"
        elif response.status_code == 401:
            msg = f"❌ Auth Error (401): {msg}. Check DEVINE API key."
        elif response.status_code == 402:
            msg = f"❌ Supplier Insufficient Balance (402): {msg}. Please ask Admin to top up supplier balance."
        elif response.status_code == 404:
            msg = f"❌ Not Found (404): Product or order not found on supplier."
        elif response.status_code == 409:
            msg = f"❌ Out of Stock / Stock Race (409): {msg}"
        elif response.status_code == 429:
            msg = f"❌ Rate Limited (429): Too many requests to supplier."
        elif response.status_code in (500, 502, 503):
            msg = f"❌ Supplier Server Error ({response.status_code}): {msg}"

        raise DevineAPIError(msg, status_code=response.status_code, data=data)

    async def get_balance(self) -> Dict[str, Any]:
        """Check reseller balance on Devine Store."""
        base_url = await self.get_base_url()
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(f"{base_url}/api/public/v1/balance", headers=headers)
            return await self._handle_response(res)

    async def get_products(self) -> List[Dict[str, Any]]:
        """Fetch live catalog from Devine Store."""
        base_url = await self.get_base_url()
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=25.0) as client:
            res = await client.get(f"{base_url}/api/public/v1/products", headers=headers)
            data = await self._handle_response(res)
            return data.get("products", []) if isinstance(data.get("products"), list) else []

    async def create_order(
        self,
        product_id: str,
        quantity: int = 1,
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Places an order, debits reseller balance and returns delivery keys."""
        base_url = await self.get_base_url()
        headers = await self._get_headers(requires_auth=True)
        key = idempotency_key or str(uuid.uuid4())
        payload = {
            "product_id": str(product_id),
            "quantity": int(quantity),
            "idempotency_key": key
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(f"{base_url}/api/public/v1/order", headers=headers, json=payload)
            data = await self._handle_response(res)

        order = data.get("order", {})
        delivery_status = order.get("delivery_status", "")

        # Poll if delivery is pending
        if delivery_status == "pending":
            for _ in range(20):
                await asyncio.sleep(3)
                async with httpx.AsyncClient(timeout=20.0) as client:
                    poll_res = await client.get(f"{base_url}/api/public/v1/order?key={key}", headers=headers)
                    poll_data = await self._handle_response(poll_res)
                    order = poll_data.get("order", {})
                    delivery_status = order.get("delivery_status", "")
                    if delivery_status == "delivered":
                        break
                    elif delivery_status == "failed":
                        err = order.get("delivery_error") or "Order delivery failed."
                        raise DevineAPIError(err, status_code=400, data=order)

        if delivery_status != "delivered":
            raise DevineAPIError(order.get("delivery_error") or "Delivery timed out or failed.", status_code=500, data=order)

        delivery_content = order.get("delivery_content", "")
        delivered_keys = [delivery_content] if delivery_content else []

        return {
            "ok": True,
            "order_code": order.get("id") or key,
            "order": order,
            "delivered_keys": delivered_keys,
            "balance": data.get("balance")
        }
