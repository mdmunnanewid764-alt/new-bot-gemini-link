import os
import httpx
from typing import Optional, Dict, Any, List
import database
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://upibot.00969600.xyz/shop-api/v1"

class ShopAPIError(Exception):
    def __init__(self, message: str, status_code: int = 500, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data or {}

class ShopAPIClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("SHOP_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")

    async def get_api_key(self) -> Optional[str]:
        """Fetch API key from database setting or .env environment variable."""
        key = await database.get_setting("shop_api_key")
        if not key:
            key = os.getenv("SHOP_API_KEY")
        return key.strip() if key else None

    async def _get_headers(self, requires_auth: bool = True) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if requires_auth:
            key = await self.get_api_key()
            if not key:
                raise ShopAPIError("API Key is not configured. Please set it using /setkey command in Telegram.", status_code=401)
            headers["X-Shop-API-Key"] = key
        return headers

    async def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        try:
            data = response.json()
        except Exception:
            data = {"message": response.text}

        if response.status_code == 200:
            return data

        msg = data.get("message") or data.get("error") or "API Request failed"
        
        if response.status_code == 401:
            msg = f"❌ Auth Error (401): {msg}. Please check your API key."
        elif response.status_code == 402:
            msg = f"❌ Balance Error (402): Insufficient deposit balance on supplier account."
        elif response.status_code == 404:
            msg = f"❌ Not Found (404): Product or order not found."
        elif response.status_code == 409:
            msg = f"❌ Stock/Price Error (409): {msg} (Item may be out of stock)."
        elif response.status_code == 423:
            msg = f"❌ Shop Unavailable (423): Shop is turned off or in sleep mode."
        elif response.status_code in (502, 503):
            msg = f"❌ Supplier Error ({response.status_code}): Supplier failed (auto refund triggered)."

        raise ShopAPIError(msg, status_code=response.status_code, data=data)

    async def health(self) -> Dict[str, Any]:
        """Public health check."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/health")
            return await self._handle_response(res)

    async def get_me(self) -> Dict[str, Any]:
        """Account + deposit balance + key status."""
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/me", headers=headers)
            return await self._handle_response(res)

    async def get_products(self) -> List[Dict[str, Any]]:
        """List enabled + in-stock products only."""
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/products", headers=headers)
            data = await self._handle_response(res)
            return data.get("products", [])

    async def get_product(self, product_id: int) -> Dict[str, Any]:
        """Get product detail by local product ID."""
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/products/{product_id}", headers=headers)
            return await self._handle_response(res)

    async def create_order(
        self,
        product_id: int,
        quantity: int = 1,
        idempotency_key: Optional[str] = None,
        customer_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Buy a product. Debits deposit balance and returns delivered keys."""
        headers = await self._get_headers(requires_auth=True)
        payload = {
            "product_id": int(product_id),
            "quantity": int(quantity)
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        if customer_name:
            payload["customer_name"] = customer_name

        async with httpx.AsyncClient(timeout=25.0) as client:
            res = await client.post(f"{self.base_url}/orders", headers=headers, json=payload)
            return await self._handle_response(res)

    async def get_order(self, order_id: int) -> Dict[str, Any]:
        """Get one order details including delivered keys."""
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/orders/{order_id}", headers=headers)
            return await self._handle_response(res)

    async def get_orders(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent orders."""
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/orders?limit={limit}", headers=headers)
            data = await self._handle_response(res)
            return data.get("orders", []) if isinstance(data.get("orders"), list) else []
