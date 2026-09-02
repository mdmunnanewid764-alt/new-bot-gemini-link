import os
import logging
import time
import json
from typing import Optional, Dict, Any, List
from aiohttp import web
from datetime import datetime

import database
import catalog_sync
from shop_api import ShopAPIClient

logger = logging.getLogger("api_server")

# Reference to upstream client and telegram bot instance for notifications
_upstream_api_client: Optional[ShopAPIClient] = None
_tg_bot = None

def set_server_dependencies(upstream_client: ShopAPIClient, bot=None):
    global _upstream_api_client, _tg_bot
    _upstream_api_client = upstream_client
    _tg_bot = bot

def json_response(data: Any, status: int = 200) -> web.Response:
    return web.json_response(
        data,
        status=status,
        dumps=lambda obj: json.dumps(obj, default=str),
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Shop-API-Key"
        }
    )

async def extract_api_user(request: web.Request) -> Optional[dict]:
    """Authenticate request via X-Shop-API-Key or Bearer Authorization header."""
    key = request.headers.get("X-Shop-API-Key")
    if not key:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            key = auth_header[7:].strip()

    if not key:
        return None

    user_info = await database.get_user_by_api_key(key)
    if not user_info or user_info.get("is_enabled") != 1:
        return None

    # Track usage asynchronously
    import asyncio
    asyncio.create_task(database.touch_api_key(key))
    return user_info

# ─────────────────────────────────────────────────────────────
#  API ROUTES
# ─────────────────────────────────────────────────────────────

async def handle_options(request: web.Request) -> web.Response:
    return web.Response(
        status=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Shop-API-Key"
        }
    )

async def handle_health(request: web.Request) -> web.Response:
    return json_response({
        "ok": True,
        "status": "ok",
        "service": "nexvora-shop-api",
        "version": "v1"
    })

async def handle_me(request: web.Request) -> web.Response:
    api_user = await extract_api_user(request)
    if not api_user:
        return json_response({"error": "Missing, disabled, or invalid API key."}, status=401)

    user_id = api_user["user_id"]
    orders = await database.get_user_orders(user_id, limit=1000)
    total_spent = sum(float(o.get("total", 0.0)) for o in orders)

    return json_response({
        "ok": True,
        "telegram_id": str(user_id),
        "username": api_user.get("username") or "",
        "first_name": api_user.get("first_name") or "User",
        "balance": round(float(api_user.get("balance", 0.0)), 3),
        "total_spent": round(total_spent, 3),
        "label": api_user.get("label", "default")
    })

async def handle_categories(request: web.Request) -> web.Response:
    api_user = await extract_api_user(request)
    if not api_user:
        return json_response({"error": "Missing, disabled, or invalid API key."}, status=401)

    # Categories list
    prods = await catalog_sync.get_local_catalog(filter_gemini=False)
    cats_map = {
        1: {"id": 1, "name": "In-House Digital Products", "slug": "in-house", "emoji": "📦", "product_count": 0},
        2: {"id": 2, "name": "AI & Subscription Tools", "slug": "ai-tools", "emoji": "🤖", "product_count": 0},
        3: {"id": 3, "name": "Accounts & Utilities", "slug": "accounts", "emoji": "⚡", "product_count": 0},
    }

    for p in prods:
        if p.get("is_custom") or p.get("id", 0) >= 90000:
            cats_map[1]["product_count"] += 1
        elif "gemini" in str(p.get("name", "")).lower() or "ai" in str(p.get("name", "")).lower():
            cats_map[2]["product_count"] += 1
        else:
            cats_map[3]["product_count"] += 1

    cats_list = [c for c in cats_map.values() if c["product_count"] > 0]
    return json_response({
        "ok": True,
        "count": len(cats_list),
        "categories": cats_list
    })

async def handle_products(request: web.Request) -> web.Response:
    api_user = await extract_api_user(request)
    if not api_user:
        return json_response({"error": "Missing, disabled, or invalid API key."}, status=401)

    category_id_param = request.query.get("category_id")
    category_id = int(category_id_param) if category_id_param and category_id_param.isdigit() else None

    local_prods = await catalog_sync.get_local_catalog(filter_gemini=False)
    result_list = []

    for p in local_prods:
        p_id = p["id"]
        is_custom = p.get("is_custom") or (isinstance(p_id, int) and p_id >= 90000)
        stock_count = p.get("stock_count", 0)
        in_stock = bool(p.get("in_stock", True) and stock_count > 0)
        
        # Categorize
        cat_id = 1 if is_custom else (2 if ("gemini" in p["name"].lower() or "ai" in p["name"].lower()) else 3)
        if category_id and cat_id != category_id:
            continue

        sell_price = round(float(p.get("sell_price", 0.0)), 3)
        description = p.get("description") or ("Instant automated digital delivery via Nexvora API." if is_custom else "Supplied digital credentials.")

        result_list.append({
            "id": p_id,
            "category_id": cat_id,
            "name": p["name"],
            "description": description,
            "delivery_type": "Text",
            "unit_price": sell_price,
            "list_price": sell_price,
            "min_qty": 1,
            "max_qty": min(100, stock_count) if stock_count > 0 else 1,
            "stock_count": stock_count,
            "in_stock": in_stock
        })

    return json_response({
        "ok": True,
        "count": len(result_list),
        "products": result_list
    })

async def handle_product_detail(request: web.Request) -> web.Response:
    api_user = await extract_api_user(request)
    if not api_user:
        return json_response({"error": "Missing, disabled, or invalid API key."}, status=401)

    try:
        p_id = int(request.match_info["id"])
    except ValueError:
        return json_response({"error": "Invalid product ID."}, status=400)

    p = await catalog_sync.get_local_product(p_id)
    if not p:
        return json_response({"error": "Product not found."}, status=404)

    is_custom = p.get("is_custom") or (isinstance(p_id, int) and p_id >= 90000)
    stock_count = p.get("stock_count", 0)
    cat_id = 1 if is_custom else (2 if ("gemini" in p["name"].lower() or "ai" in p["name"].lower()) else 3)
    cat_name = "In-House Digital Products" if cat_id == 1 else ("AI & Subscription Tools" if cat_id == 2 else "Accounts & Utilities")
    sell_price = round(float(p.get("sell_price", 0.0)), 3)

    return json_response({
        "ok": True,
        "product": {
            "id": p_id,
            "category_id": cat_id,
            "name": p["name"],
            "description": p.get("description") or "Instant automated digital delivery.",
            "delivery_type": "Text",
            "unit_price": sell_price,
            "list_price": sell_price,
            "min_qty": 1,
            "max_qty": min(100, stock_count) if stock_count > 0 else 1,
            "stock_count": stock_count,
            "in_stock": bool(p.get("in_stock", True) and stock_count > 0),
            "category": {
                "id": cat_id,
                "name": cat_name,
                "slug": "digital-goods",
                "emoji": "📦"
            }
        }
    })

async def handle_create_order(request: web.Request) -> web.Response:
    api_user = await extract_api_user(request)
    if not api_user:
        return json_response({"error": "Missing, disabled, or invalid API key."}, status=401)

    user_id = api_user["user_id"]
    try:
        body = await request.json()
    except Exception:
        return json_response({"error": "Invalid JSON payload."}, status=400)

    prod_id = body.get("product_id")
    quantity = int(body.get("quantity", 1))

    if not prod_id:
        return json_response({"error": "Field 'product_id' is required."}, status=400)
    if quantity < 1:
        return json_response({"error": "Quantity must be at least 1."}, status=400)

    try:
        prod_id = int(prod_id)
    except ValueError:
        return json_response({"error": "Invalid product ID."}, status=400)

    # Check product availability
    p = await catalog_sync.get_local_product(prod_id)
    if not p:
        return json_response({"error": "Product not found."}, status=404)

    is_custom = p.get("is_custom") or (isinstance(prod_id, int) and prod_id >= 90000)
    unit_price = float(p.get("sell_price", 0.0))
    total_price = round(unit_price * quantity, 3)

    # Check user live balance
    current_bal = await database.get_user_balance(user_id)
    if current_bal < total_price:
        return json_response({
            "error": "Insufficient balance.",
            "required": total_price,
            "current_balance": round(current_bal, 3)
        }, status=409)

    # Check stock
    avail_stock = p.get("stock_count", 0)
    if avail_stock < quantity or not p.get("in_stock"):
        return json_response({"error": "Quantity is outside the available range / Out of stock."}, status=409)

    # Deduct balance atomically
    deducted = await database.deduct_user_balance(user_id, total_price)
    if not deducted:
        return json_response({"error": "Balance deduction failed. Please retry."}, status=409)

    delivered_keys = []
    order_code = f"ORD-NEX-{int(time.time())}-{secrets.token_hex(2).upper()}"
    status = "fulfilled"

    try:
        if is_custom:
            custom_id = prod_id - 90000 if prod_id >= 90000 else prod_id
            delivered_keys = await database.purchase_custom_product_stock(custom_id, user_id, quantity)
            if not delivered_keys or len(delivered_keys) < quantity:
                # Refund
                await database.add_user_balance(user_id, total_price)
                return json_response({"error": "Not enough in-house stock available to fulfill order."}, status=409)
        else:
            # Synced API product from supplier
            if not _upstream_api_client:
                await database.add_user_balance(user_id, total_price)
                return json_response({"error": "Supplier gateway temporarily unavailable."}, status=503)

            supplier_order = await _upstream_api_client.create_order(
                product_id=prod_id,
                quantity=quantity,
                customer_name=f"API:{user_id}"
            )
            delivered_keys = supplier_order.get("delivered_keys") or supplier_order.get("order", {}).get("delivered_keys", [])
            if not delivered_keys:
                # Refund
                await database.add_user_balance(user_id, total_price)
                return json_response({"error": "Supplier fulfillment failed. Balance refunded."}, status=502)

        # Save order record in database
        await database.record_order(
            user_id=user_id,
            order_id=order_code,
            product_id=prod_id,
            product_name=p["name"],
            quantity=quantity,
            total=total_price,
            status=status,
            delivered_keys=delivered_keys
        )

        new_bal = await database.get_user_balance(user_id)

        # Notify Telegram Admin & Group
        try:
            if _tg_bot:
                import bot as bot_module
                admin_id = int(os.getenv("ADMIN_ID", "6575066703"))
                admin_keys_text = ""
                if delivered_keys:
                    admin_keys_text = "\n\n🔑 *Delivered Item(s) [Admin Copy]:*\n"
                    for i, k in enumerate(delivered_keys, 1):
                        if len(delivered_keys) > 1:
                            admin_keys_text += f"\n📦 *Item #{i}:*\n```{k}```\n"
                        else:
                            admin_keys_text += f"```{k}```\n"
                else:
                    admin_keys_text = "\n\n⚠️ _No keys were delivered._"

                notif_msg = (
                    f"⚡ *New API Order Processed (Admin Copy)*\n\n"
                    f"👤 *API User:* `{api_user.get('first_name')}` (`@{api_user.get('username') or 'N/A'}`)\n"
                    f"🆔 *User ID:* `{user_id}`\n"
                    f"🏷️ *Order Code:* `{order_code}`\n"
                    f"📦 *Product:* `{p['name']}`\n"
                    f"🔢 *Qty:* `{quantity}` | 💰 *Total:* `${total_price:.2f}` USD\n"
                    f"💳 *User Remaining Balance:* `${new_bal:.2f}` USD"
                    f"{admin_keys_text}"
                )
                import asyncio
                from telegram.constants import ParseMode
                asyncio.create_task(_tg_bot.send_message(chat_id=admin_id, text=notif_msg, parse_mode=ParseMode.MARKDOWN))
        except Exception as e:
            logger.warning(f"Could not dispatch API order alert: {e}")

        return json_response({
            "ok": True,
            "order_code": order_code,
            "quantity": quantity,
            "total": total_price,
            "balance_after": round(new_bal, 3),
            "delivered_keys": delivered_keys
        })

    except Exception as e:
        logger.error(f"Error executing API order: {e}")
        await database.add_user_balance(user_id, total_price)
        return json_response({"error": f"Order processing failed: {str(e)}"}, status=500)

async def handle_orders_list(request: web.Request) -> web.Response:
    api_user = await extract_api_user(request)
    if not api_user:
        return json_response({"error": "Missing, disabled, or invalid API key."}, status=401)

    user_id = api_user["user_id"]
    limit_param = request.query.get("limit", "20")
    limit = int(limit_param) if limit_param.isdigit() else 20
    limit = max(1, min(100, limit))

    raw_orders = await database.get_user_orders(user_id, limit=limit)
    orders_out = []
    for o in raw_orders:
        orders_out.append({
            "order_code": str(o.get("order_id")),
            "product_id": o.get("product_id"),
            "product_name": o.get("product_name"),
            "quantity": o.get("quantity"),
            "total": round(float(o.get("total", 0.0)), 3),
            "status": "fulfilled" if o.get("status") in ("delivered", "fulfilled", "paid") else o.get("status", "fulfilled"),
            "created_at": o.get("created_at")
        })

    return json_response({
        "ok": True,
        "count": len(orders_out),
        "orders": orders_out
    })

async def handle_order_detail(request: web.Request) -> web.Response:
    api_user = await extract_api_user(request)
    if not api_user:
        return json_response({"error": "Missing, disabled, or invalid API key."}, status=401)

    code = request.match_info["code"].strip()
    user_id = api_user["user_id"]
    raw_orders = await database.get_user_orders(user_id, limit=200)

    matched = None
    for o in raw_orders:
        if str(o.get("order_id")) == code or str(o.get("id")) == code:
            matched = o
            break

    if not matched:
        return json_response({"error": "Order not found."}, status=404)

    raw_keys = matched.get("delivered_keys") or ""
    delivered_keys = [k.strip() for k in raw_keys.split("\n") if k.strip()] if isinstance(raw_keys, str) else (raw_keys if isinstance(raw_keys, list) else [])

    return json_response({
        "ok": True,
        "order": {
            "order_code": str(matched.get("order_id")),
            "product_id": matched.get("product_id"),
            "product_name": matched.get("product_name"),
            "quantity": matched.get("quantity"),
            "total": round(float(matched.get("total", 0.0)), 3),
            "status": "fulfilled" if matched.get("status") in ("delivered", "fulfilled") else matched.get("status", "fulfilled"),
            "created_at": matched.get("created_at"),
            "delivered_keys": delivered_keys
        }
    })

# ─────────────────────────────────────────────────────────────
#  INTERACTIVE API DOCUMENTATION HTML PORTAL
# ─────────────────────────────────────────────────────────────

DOCS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Nexvora Shop API Documentation</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --card-bg: rgba(18, 24, 38, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --accent-primary: #38bdf8;
      --accent-glow: rgba(56, 189, 248, 0.15);
      --accent-green: #34d399;
      --accent-purple: #a78bfa;
      --accent-orange: #fbbf24;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --code-bg: #030712;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Plus Jakarta Sans', sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      line-height: 1.6;
      overflow-x: hidden;
    }
    .background-gradient {
      position: fixed;
      top: -20%;
      left: 20%;
      width: 60vw;
      height: 60vw;
      background: radial-gradient(circle, rgba(56, 189, 248, 0.08) 0%, rgba(167, 139, 250, 0.04) 50%, transparent 70%);
      pointer-events: none;
      z-index: 0;
    }
    .container {
      max-width: 1100px;
      margin: 0 auto;
      padding: 40px 24px 80px 24px;
      position: relative;
      z-index: 1;
    }
    header {
      text-align: center;
      margin-bottom: 50px;
      padding-bottom: 30px;
      border-bottom: 1px solid var(--card-border);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 9999px;
      background: rgba(56, 189, 248, 0.1);
      border: 1px solid rgba(56, 189, 248, 0.3);
      color: var(--accent-primary);
      font-size: 0.85rem;
      font-weight: 600;
      margin-bottom: 16px;
    }
    h1 {
      font-size: 2.8rem;
      font-weight: 800;
      letter-spacing: -0.03em;
      background: linear-gradient(135deg, #ffffff 40%, #94a3b8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 12px;
    }
    .subtitle {
      color: var(--text-muted);
      font-size: 1.15rem;
      max-width: 650px;
      margin: 0 auto 20px auto;
    }
    .quick-specs {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 12px;
      margin-top: 20px;
    }
    .spec-item {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 0.9rem;
      color: var(--text-muted);
    }
    .spec-item span { color: #fff; font-weight: 600; }
    
    .section-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      backdrop-filter: blur(12px);
      border-radius: 16px;
      padding: 28px;
      margin-bottom: 30px;
      box-shadow: 0 10px 30px -10px rgba(0,0,0,0.5);
    }
    .section-card h2 {
      font-size: 1.4rem;
      margin-bottom: 16px;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .endpoint {
      background: rgba(3, 7, 18, 0.6);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      margin-bottom: 20px;
      overflow: hidden;
    }
    .endpoint-header {
      padding: 14px 20px;
      display: flex;
      align-items: center;
      gap: 12px;
      border-bottom: 1px solid var(--card-border);
      background: rgba(255, 255, 255, 0.02);
    }
    .method {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8rem;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 6px;
      text-transform: uppercase;
    }
    .method.get { background: rgba(52, 211, 153, 0.15); color: var(--accent-green); border: 1px solid rgba(52, 211, 153, 0.3); }
    .method.post { background: rgba(56, 189, 248, 0.15); color: var(--accent-primary); border: 1px solid rgba(56, 189, 248, 0.3); }
    .path {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.95rem;
      color: #fff;
      font-weight: 500;
    }
    .desc {
      margin-left: auto;
      color: var(--text-muted);
      font-size: 0.85rem;
    }
    .endpoint-body {
      padding: 20px;
    }
    pre, code {
      font-family: 'JetBrains Mono', monospace;
    }
    pre {
      background: var(--code-bg);
      border: 1px solid rgba(255, 255, 255, 0.05);
      padding: 16px;
      border-radius: 8px;
      overflow-x: auto;
      color: #e2e8f0;
      font-size: 0.85rem;
      margin-top: 10px;
    }
    .code-label {
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-top: 12px;
      display: block;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      font-size: 0.9rem;
    }
    th, td {
      padding: 10px 14px;
      text-align: left;
      border-bottom: 1px solid var(--card-border);
    }
    th {
      color: var(--text-muted);
      font-weight: 600;
    }
    td code {
      background: rgba(255, 255, 255, 0.06);
      padding: 2px 6px;
      border-radius: 4px;
      color: var(--accent-primary);
    }
    .curl-example {
      color: #38bdf8;
    }
    footer {
      text-align: center;
      color: var(--text-muted);
      font-size: 0.9rem;
      padding-top: 40px;
      border-top: 1px solid var(--card-border);
    }
  </style>
</head>
<body>
  <div class="background-gradient"></div>
  <div class="container">
    <header>
      <div class="badge">🚀 REST API v1.0 Live</div>
      <h1>Nexvora Digital Shop API</h1>
      <p class="subtitle">Complete machine-to-machine interface for external apps, bots, and reseller portals to browse digital stock, debit wallet, and receive automated deliveries in real-time.</p>
      <div class="quick-specs">
        <div class="spec-item">Base URL: <span>/shop-api/v1</span></div>
        <div class="spec-item">Auth: <span>X-Shop-API-Key / Bearer</span></div>
        <div class="spec-item">Response: <span>JSON</span></div>
        <div class="spec-item">Delivery: <span>Instant Automated</span></div>
      </div>
    </header>

    <!-- Quick Start -->
    <div class="section-card">
      <h2>🔑 Authentication & Quick Start</h2>
      <p style="color: var(--text-muted); margin-bottom: 14px;">Protected endpoints require a valid API Key linked to your Telegram user wallet balance. Send either of the following HTTP headers with your requests:</p>
      <pre><code>X-Shop-API-Key: sk_shop_YOUR_API_KEY
Authorization: Bearer sk_shop_YOUR_API_KEY</code></pre>
      
      <p class="code-label">How to get your API Key:</p>
      <ol style="margin-left: 20px; color: var(--text-muted); font-size: 0.95rem; margin-top: 8px;">
        <li>Open the Telegram Bot ➔ Tap <b>👤 My Account</b> ➔ <b>🔑 Developer API Key</b> (or send <code>/api_key</code>).</li>
        <li>Click <b>🔄 Create / Rotate Key</b> to generate your secure <code>sk_shop_...</code> token.</li>
        <li>Deposit wallet balance into the Telegram Bot. All purchases via the API will debit from your wallet balance with zero delay.</li>
      </ol>
    </div>

    <!-- Endpoints -->
    <div class="section-card">
      <h2>📡 API Endpoints</h2>

      <!-- GET /health -->
      <div class="endpoint">
        <div class="endpoint-header">
          <span class="method get">GET</span>
          <span class="path">/shop-api/v1/health</span>
          <span class="desc">Public health status check</span>
        </div>
        <div class="endpoint-body">
          <span class="code-label">Response Example (200 OK):</span>
          <pre><code>{
  "ok": true,
  "status": "ok",
  "service": "nexvora-shop-api",
  "version": "v1"
}</code></pre>
        </div>
      </div>

      <!-- GET /me -->
      <div class="endpoint">
        <div class="endpoint-header">
          <span class="method get">GET</span>
          <span class="path">/shop-api/v1/me</span>
          <span class="desc">Profile, user ID, and live wallet balance</span>
        </div>
        <div class="endpoint-body">
          <span class="code-label">cURL Request:</span>
          <pre><code>curl -X GET "https://YOUR_DOMAIN/shop-api/v1/me" \\
  -H "X-Shop-API-Key: sk_shop_YOUR_KEY"</code></pre>
          <span class="code-label">Response Example (200 OK):</span>
          <pre><code>{
  "ok": true,
  "telegram_id": "6575066703",
  "username": "BD_Shopee",
  "first_name": "Developer Munna",
  "balance": 25.500,
  "total_spent": 10.000,
  "label": "default"
}</code></pre>
        </div>
      </div>

      <!-- GET /categories -->
      <div class="endpoint">
        <div class="endpoint-header">
          <span class="method get">GET</span>
          <span class="path">/shop-api/v1/categories</span>
          <span class="desc">List visible shop categories</span>
        </div>
        <div class="endpoint-body">
          <span class="code-label">Response Example (200 OK):</span>
          <pre><code>{
  "ok": true,
  "count": 3,
  "categories": [
    { "id": 1, "name": "In-House Digital Products", "slug": "in-house", "emoji": "📦", "product_count": 4 },
    { "id": 2, "name": "AI & Subscription Tools", "slug": "ai-tools", "emoji": "🤖", "product_count": 3 }
  ]
}</code></pre>
        </div>
      </div>

      <!-- GET /products -->
      <div class="endpoint">
        <div class="endpoint-header">
          <span class="method get">GET</span>
          <span class="path">/shop-api/v1/products</span>
          <span class="desc">Browse catalog with live prices & stock</span>
        </div>
        <div class="endpoint-body">
          <p style="color: var(--text-muted); font-size: 0.9rem;">Optional Query Parameter: <code>?category_id=1</code></p>
          <span class="code-label">Response Example (200 OK):</span>
          <pre><code>{
  "ok": true,
  "count": 2,
  "products": [
    {
      "id": 90007,
      "category_id": 1,
      "name": "Netflix 4K 1 Month Premium Account",
      "description": "Private ultra HD profile with instant credentials.",
      "delivery_type": "Text",
      "unit_price": 1.500,
      "list_price": 1.500,
      "min_qty": 1,
      "max_qty": 9,
      "stock_count": 9,
      "in_stock": true
    },
    {
      "id": 4,
      "category_id": 2,
      "name": "Gemini Pro 18 Months (link)",
      "description": "Activation invitation link with 24hr claim warranty.",
      "delivery_type": "Text",
      "unit_price": 0.600,
      "list_price": 0.600,
      "min_qty": 1,
      "max_qty": 12,
      "stock_count": 12,
      "in_stock": true
    }
  ]
}</code></pre>
        </div>
      </div>

      <!-- POST /orders -->
      <div class="endpoint">
        <div class="endpoint-header">
          <span class="method post">POST</span>
          <span class="path">/shop-api/v1/orders</span>
          <span class="desc">Buy stock immediately & receive automated delivery</span>
        </div>
        <div class="endpoint-body">
          <table>
            <thead>
              <tr><th>Field</th><th>Type</th><th>Required</th><th>Description</th></tr>
            </thead>
            <tbody>
              <tr><td><code>product_id</code></td><td>Integer</td><td>Yes</td><td>Product ID from /products</td></tr>
              <tr><td><code>quantity</code></td><td>Integer</td><td>No</td><td>Amount to buy (Default: 1)</td></tr>
            </tbody>
          </table>
          <span class="code-label">cURL Request:</span>
          <pre><code>curl -X POST "https://YOUR_DOMAIN/shop-api/v1/orders" \\
  -H "Content-Type: application/json" \\
  -H "X-Shop-API-Key: sk_shop_YOUR_KEY" \\
  -d '{"product_id": 90007, "quantity": 1}'</code></pre>
          <span class="code-label">Response Example (200 OK):</span>
          <pre><code>{
  "ok": true,
  "order_code": "ORD-NEX-1788356-9A1F",
  "quantity": 1,
  "total": 1.500,
  "balance_after": 23.500,
  "delivered_keys": [
    "user@outlook.com:Pass123:https://mailreader.tech/read_code?uuid=..."
  ]
}</code></pre>
        </div>
      </div>

      <!-- GET /orders -->
      <div class="endpoint">
        <div class="endpoint-header">
          <span class="method get">GET</span>
          <span class="path">/shop-api/v1/orders</span>
          <span class="desc">Recent orders history</span>
        </div>
        <div class="endpoint-body">
          <p style="color: var(--text-muted); font-size: 0.9rem;">Optional Query Parameter: <code>?limit=20</code> (Max 100)</p>
          <span class="code-label">Response Example:</span>
          <pre><code>{
  "ok": true,
  "count": 1,
  "orders": [
    {
      "order_code": "ORD-NEX-1788356-9A1F",
      "product_id": 90007,
      "product_name": "Netflix 4K 1 Month Premium Account",
      "quantity": 1,
      "total": 1.500,
      "status": "fulfilled",
      "created_at": "2026-09-02T03:38:29"
    }
  ]
}</code></pre>
        </div>
      </div>

      <!-- GET /orders/{code} -->
      <div class="endpoint">
        <div class="endpoint-header">
          <span class="method get">GET</span>
          <span class="path">/shop-api/v1/orders/{order_code}</span>
          <span class="desc">Lookup order with delivered credentials</span>
        </div>
        <div class="endpoint-body">
          <span class="code-label">Response Example:</span>
          <pre><code>{
  "ok": true,
  "order": {
    "order_code": "ORD-NEX-1788356-9A1F",
    "product_id": 90007,
    "product_name": "Netflix 4K 1 Month Premium Account",
    "quantity": 1,
    "total": 1.500,
    "status": "fulfilled",
    "created_at": "2026-09-02T03:38:29",
    "delivered_keys": [
      "user@outlook.com:Pass123:https://mailreader.tech/read_code?uuid=..."
    ]
  }
}</code></pre>
        </div>
      </div>

    </div>

    <!-- Python Sample Code -->
    <div class="section-card">
      <h2>🐍 Python Integration Example</h2>
      <pre><code>import requests

API_KEY = "sk_shop_YOUR_API_KEY"
BASE_URL = "https://YOUR_DOMAIN/shop-api/v1"
HEADERS = {"X-Shop-API-Key": API_KEY, "Content-Type": "application/json"}

# 1. Check Wallet Balance
me = requests.get(f"{BASE_URL}/me", headers=HEADERS).json()
print(f"Connected: {me['first_name']} | Balance: ${me['balance']:.2f}")

# 2. Browse Products
products = requests.get(f"{BASE_URL}/products", headers=HEADERS).json().get("products", [])
for p in products:
    print(f"ID #{p['id']}: {p['name']} - ${p['unit_price']:.2f} (Stock: {p['stock_count']})")

# 3. Buy Product
order = requests.post(f"{BASE_URL}/orders", headers=HEADERS, json={"product_id": 90007, "quantity": 1}).json()
if order.get("ok"):
    print(f"Order Success! Code: {order['order_code']}")
    for key in order["delivered_keys"]:
        print(f"Credentials: {key}")
else:
    print(f"Order Failed: {order.get('error')}")
</code></pre>
    </div>

    <footer>
      <p>© 2026 Nexvora Digital Shop System • Automated REST API v1.0</p>
    </footer>
  </div>
</body>
</html>
"""

async def handle_docs(request: web.Request) -> web.Response:
    web_url = os.getenv("WEB_URL", "https://new-bot-gemini-link.onrender.com")
    clean_host = web_url.replace("https://", "").replace("http://", "").rstrip("/")
    html_rendered = DOCS_HTML.replace("YOUR_DOMAIN", clean_host)
    return web.Response(text=html_rendered, content_type="text/html")

def create_api_app() -> web.Application:
    """Build the aiohttp web application for Shop API."""
    app = web.Application()

    # Documentation
    app.router.add_get("/", handle_docs)
    app.router.add_get("/docs", handle_docs)
    app.router.add_get("/shop-api/docs", handle_docs)

    # Health Checks
    app.router.add_get("/health", handle_health)
    app.router.add_get("/shop-api/v1/health", handle_health)

    # Protected Endpoints
    app.router.add_get("/shop-api/v1/me", handle_me)
    app.router.add_get("/shop-api/v1/categories", handle_categories)
    app.router.add_get("/shop-api/v1/products", handle_products)
    app.router.add_get("/shop-api/v1/products/{id}", handle_product_detail)
    app.router.add_post("/shop-api/v1/orders", handle_create_order)
    app.router.add_get("/shop-api/v1/orders", handle_orders_list)
    app.router.add_get("/shop-api/v1/orders/{code}", handle_order_detail)

    # CORS Options Preflight
    app.router.add_options("/{tail:.*}", handle_options)

    return app

async def start_api_server(host: str = "0.0.0.0", port: int = 8080):
    """Launch the async API server in the event loop without blocking bot polling."""
    port_env = os.getenv("PORT")
    actual_port = int(port_env) if port_env and port_env.isdigit() else port

    app = create_api_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, actual_port)
    await site.start()
    logger.info(f"🚀 Nexvora Shop API Server live & listening at http://{host}:{actual_port} (Docs: http://{host}:{actual_port}/shop-api/docs)")
