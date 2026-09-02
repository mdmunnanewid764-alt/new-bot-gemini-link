import os
import httpx
from typing import Optional, Dict, Any, List
import database
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://shopbot.00969600.xyz/shop-api/v1"

class ShopAPIError(Exception):
    def __init__(self, message: str, status_code: int = 500, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data or {}

class ShopAPIClient:
    def __init__(self, base_url: Optional[str] = None):
        self._custom_base_url = base_url

    async def get_base_url(self) -> str:
        if self._custom_base_url and "upibot" not in self._custom_base_url:
            return self._custom_base_url.rstrip("/")
        db_url = await database.get_setting("shop_api_base_url")
        if db_url and "upibot" not in db_url:
            return db_url.rstrip("/")
        env_url = os.getenv("SHOP_API_BASE_URL")
        if env_url and "upibot" not in env_url:
            return env_url.rstrip("/")
        return DEFAULT_BASE_URL.rstrip("/")

    async def get_api_key(self) -> Optional[str]:
        """Fetch API key from database setting or .env environment variable."""
        key = await database.get_setting("shop_api_key")
        if not key:
            key = os.getenv("SHOP_API_KEY")
        return key.strip() if key else None

    async def _get_headers(self, requires_auth: bool = True) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if requires_auth:
            key = await self.get_api_key()
            if not key:
                raise ShopAPIError("API Key is not configured. Please set it using /setkey command in Telegram.", status_code=401)
            headers["X-Shop-API-Key"] = key
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        try:
            data = response.json()
        except Exception:
            data = {"message": response.text}

        if response.status_code in (200, 201):
            return data

        msg = data.get("error") or data.get("message") or "API Request failed"
        
        if response.status_code == 400:
            msg = f"❌ Bad Request (400): {msg}"
        elif response.status_code == 401:
            msg = f"❌ Auth Error (401): {msg}. Please check your API key."
        elif response.status_code == 404:
            msg = f"❌ Not Found (404): Product or order not found / out of stock."
        elif response.status_code == 409:
            msg = f"❌ Stock/Balance Error (409): {msg}"
        elif response.status_code == 423:
            msg = f"❌ Shop Unavailable (423): Shop is currently closed or in sleep mode."
        elif response.status_code in (500, 502, 503):
            msg = f"❌ Supplier Server Error ({response.status_code}): {msg}"

        raise ShopAPIError(msg, status_code=response.status_code, data=data)

    async def health(self) -> Dict[str, Any]:
        """Public health check."""
        base_url = await self.get_base_url()
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{base_url}/health")
            return await self._handle_response(res)

    async def get_me(self) -> Dict[str, Any]:
        """Account + wallet balance info."""
        base_url = await self.get_base_url()
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{base_url}/me", headers=headers)
            return await self._handle_response(res)

    async def get_categories(self) -> List[Dict[str, Any]]:
        """Lists visible shop categories."""
        base_url = await self.get_base_url()
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{base_url}/categories", headers=headers)
            data = await self._handle_response(res)
            return data.get("categories", []) if isinstance(data.get("categories"), list) else []

    async def get_products(self, category_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Lists buyable products. Optional category filter."""
        base_url = await self.get_base_url()
        headers = await self._get_headers(requires_auth=True)
        url = f"{base_url}/products"
        if category_id:
            url += f"?category_id={category_id}"
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.get(url, headers=headers)
            data = await self._handle_response(res)
            return data.get("products", []) if isinstance(data.get("products"), list) else []

    async def get_product(self, product_id: int) -> Dict[str, Any]:
        """Get one product with category and pricing info."""
        base_url = await self.get_base_url()
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{base_url}/products/{product_id}", headers=headers)
            data = await self._handle_response(res)
            return data.get("product", data)

    async def create_order(
        self,
        product_id: int,
        quantity: int = 1,
        idempotency_key: Optional[str] = None,
        customer_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Buys stock immediately from wallet balance and returns delivered keys."""
        base_url = await self.get_base_url()
        headers = await self._get_headers(requires_auth=True)
        payload = {
            "product_id": int(product_id),
            "quantity": int(quantity)
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        if customer_name:
            payload["customer_name"] = customer_name

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(f"{base_url}/orders", headers=headers, json=payload)
            return await self._handle_response(res)

    async def get_order(self, order_code: str) -> Dict[str, Any]:
        """Get one order owned by this API key, including delivery payloads."""
        base_url = await self.get_base_url()
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{base_url}/orders/{order_code}", headers=headers)
            data = await self._handle_response(res)
            return data.get("order", data)

    async def get_orders(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent orders."""
        base_url = await self.get_base_url()
        headers = await self._get_headers(requires_auth=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{base_url}/orders?limit={limit}", headers=headers)
            data = await self._handle_response(res)
            return data.get("orders", []) if isinstance(data.get("orders"), list) else []
