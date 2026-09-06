import asyncio
import logging
import aiosqlite
from datetime import datetime
from typing import List, Dict, Any, Optional
import database
from shop_api import ShopAPIClient, ShopAPIError
from telegram.constants import ParseMode
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

# Flag to avoid announcing existing stock during the very first boot sync
_is_first_sync_done: bool = False

async def init_catalog_tables():
    """Initialize synced catalog tables in PostgreSQL or SQLite with last_notified_stock tracking and multi-provider support."""
    if database.USE_POSTGRES:
        try:
            pool = await database.get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS products_synced (
                        id SERIAL PRIMARY KEY,
                        supplier_product_id INTEGER UNIQUE,
                        name TEXT,
                        sell_price DOUBLE PRECISION,
                        stock_count INTEGER,
                        in_stock INTEGER,
                        is_enabled INTEGER DEFAULT 1,
                        last_notified_stock INTEGER DEFAULT 0,
                        last_synced TEXT,
                        api_source TEXT DEFAULT 'api1',
                        supplier_slug TEXT,
                        description TEXT
                    )
                """)
                # Ensure columns exist if table already existed
                for col_sql in [
                    "ALTER TABLE products_synced ADD COLUMN IF NOT EXISTS last_notified_stock INTEGER DEFAULT 0",
                    "ALTER TABLE products_synced ADD COLUMN IF NOT EXISTS api_source TEXT DEFAULT 'api1'",
                    "ALTER TABLE products_synced ADD COLUMN IF NOT EXISTS supplier_slug TEXT",
                    "ALTER TABLE products_synced ADD COLUMN IF NOT EXISTS description TEXT"
                ]:
                    try:
                        await conn.execute(col_sql)
                    except Exception:
                        pass

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS sync_history (
                        id SERIAL PRIMARY KEY,
                        synced_at TEXT,
                        items_count INTEGER,
                        status TEXT
                    )
                """)
                return
        except Exception as e:
            logger.error(f"PG init_catalog_tables error: {e}")

    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products_synced (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_product_id INTEGER UNIQUE,
                name TEXT,
                sell_price REAL,
                stock_count INTEGER,
                in_stock INTEGER,
                is_enabled INTEGER DEFAULT 1,
                last_notified_stock INTEGER DEFAULT 0,
                last_synced TEXT,
                api_source TEXT DEFAULT 'api1',
                supplier_slug TEXT,
                description TEXT
            )
        """)
        for col_name, col_type in [
            ("last_notified_stock", "INTEGER DEFAULT 0"),
            ("api_source", "TEXT DEFAULT 'api1'"),
            ("supplier_slug", "TEXT"),
            ("description", "TEXT")
        ]:
            try:
                await db.execute(f"ALTER TABLE products_synced ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sync_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                synced_at TEXT,
                items_count INTEGER,
                status TEXT
            )
        """)
        await db.commit()

async def notify_new_products_alert(bot, new_products: List[Dict[str, Any]], restocked_products: List[Dict[str, Any]]):
    """Broadcast an eye-catching alert to the group and all active users when genuine new products or restocks occur."""
    if not bot or (not new_products and not restocked_products):
        return

    try:
        lines = []
        if new_products:
            lines.append("🔥 *NEW PRODUCTS JUST ADDED!* 🔥\n")
            for p in new_products:
                stock_str = f"`{p['stock_count']} in stock`" if p.get("stock_count") is not None else "`In Stock`"
                lines.append(f"✨ *{p['name']}*\n   💰 Price: `${p['sell_price']:.2f}` USD | 📦 Stock: {stock_str}")
            lines.append("")

        if restocked_products:
            lines.append("⚡ *FRESH RESTOCK ALERT!* ⚡\n")
            for p in restocked_products:
                added = p.get('added_count', 0)
                tot = p.get('stock_count', 0)
                lines.append(f"🔄 *{p['name']}*\n   ➕ Added: `+{added}` pcs | 📦 Total Available: `{tot}` pcs | 💰 `${p['sell_price']:.2f}`")
            lines.append("")

        lines.append("👉 _Grab yours now before it sells out!_")
        broadcast_msg = "\n".join(lines)

        try:
            bot_info = await bot.get_me()
            bot_user = bot_info.username or "NexvoraGeminiShopebot"
        except Exception:
            bot_user = "NexvoraGeminiShopebot"

        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Open Shop / Buy Now 🚀", url=f"https://t.me/{bot_user}?start=new_products")]
        ])

        # 1. Send to Notification Group / Channel
        notif_grp = await database.get_setting("notification_group_id")
        grp_id = int(notif_grp) if notif_grp else None
        if grp_id:
            try:
                await bot.send_message(chat_id=grp_id, text=broadcast_msg, parse_mode=ParseMode.MARKDOWN, reply_markup=btn)
            except Exception as e:
                logger.warning(f"Failed to send new products alert to group: {e}")

        # 2. Broadcast to all registered bot users in background
        all_user_ids = await database.get_all_user_ids()
        logger.info(f"Broadcasting stock update alert to {len(all_user_ids)} users...")

        async def _broadcast_task():
            success = 0
            for u_id in all_user_ids:
                try:
                    await bot.send_message(chat_id=u_id, text=broadcast_msg, parse_mode=ParseMode.MARKDOWN, reply_markup=btn)
                    success += 1
                except Exception:
                    pass
                await asyncio.sleep(0.04)
            logger.info(f"Stock update alert delivered to {success} users.")

        asyncio.create_task(_broadcast_task())

    except Exception as e:
        logger.error(f"Error notifying stock update: {e}")

async def sync_catalog_now(
    api_client: Optional[ShopAPIClient] = None,
    bot = None
) -> Dict[str, Any]:
    """Fetch live products from Supplier API and update database.
    Detects newly added or restocked products and broadcasts EXACTLY ONCE when stock increases.
    """
    global _is_first_sync_done
    if api_client is None:
        api_client = ShopAPIClient()

    await init_catalog_tables()

    # Clean up any leftover Devine API products from previous integrations
    if database.USE_POSTGRES:
        try:
            pool = await database.get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM products_synced WHERE api_source = 'devine' OR (supplier_product_id >= 70000 AND supplier_product_id < 90000)")
        except Exception as e:
            logger.warning(f"PG cleanup devine products warning: {e}")
    else:
        try:
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute("DELETE FROM products_synced WHERE api_source = 'devine' OR (supplier_product_id >= 70000 AND supplier_product_id < 90000)")
                await db.commit()
        except Exception as e:
            logger.warning(f"SQLite cleanup devine products warning: {e}")

    # Fetch existing products from DB
    existing_products = {}
    if database.USE_POSTGRES:
        try:
            pool = await database.get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT supplier_product_id, name, sell_price, stock_count, in_stock, COALESCE(last_notified_stock, 0) as last_notified_stock FROM products_synced")
                for r in rows:
                    existing_products[r["supplier_product_id"]] = dict(r)
        except Exception as e:
            logger.error(f"PG fetch existing products error: {e}")
    else:
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT supplier_product_id, name, sell_price, stock_count, in_stock, COALESCE(last_notified_stock, 0) as last_notified_stock FROM products_synced") as cursor:
                rows = await cursor.fetchall()
                for r in rows:
                    existing_products[r["supplier_product_id"]] = dict(r)

    now_str = datetime.utcnow().isoformat()
    new_products = []
    restocked_products = []
    products_to_save = []

    # ---------------------------------------------------------
    # Sync Supplier API
    # ---------------------------------------------------------
    synced_ids = []
    try:
        api_key = await api_client.get_api_key()
        if api_key:
            remote = await api_client.get_products()
            for p in remote:
                p_id = p.get("id") or p.get("product_id")
                if not p_id:
                    continue
                p_id = int(p_id)
                synced_ids.append(p_id)
                name = str(p.get("name", "Product")).strip()
                price = float(p.get("unit_price") if p.get("unit_price") is not None else (p.get("sell_price") or p.get("list_price") or 0.0))
                stock = p.get("stock_count")
                in_stock = 1 if (p.get("in_stock") is True or p.get("in_stock") == 1 or (stock is not None and stock > 0)) else 0
                curr_stock = stock if stock is not None else (1 if in_stock == 1 else 0)

                db_prod = existing_products.get(p_id)
                last_notified = db_prod.get("last_notified_stock", 0) if db_prod else 0

                if _is_first_sync_done and existing_products:
                    if p_id not in existing_products and in_stock == 1 and curr_stock > 0:
                        new_products.append({"id": p_id, "name": name, "sell_price": price, "stock_count": stock})
                        last_notified = curr_stock
                    elif p_id in existing_products:
                        if curr_stock > last_notified and in_stock == 1:
                            added_cnt = curr_stock - last_notified
                            restocked_products.append({"id": p_id, "name": name, "sell_price": price, "stock_count": stock, "added_count": added_cnt})
                            last_notified = curr_stock
                else:
                    last_notified = max(last_notified, curr_stock)

                products_to_save.append({
                    "p_id": p_id,
                    "name": name,
                    "price": price,
                    "stock": stock,
                    "in_stock": in_stock,
                    "last_notified": last_notified,
                    "api_source": "api1",
                    "supplier_slug": str(p_id),
                    "description": p.get("description", "")
                })
    except Exception as e:
        logger.warning(f"Supplier API sync warning: {e}")

    # ---------------------------------------------------------
    # Save to PostgreSQL / SQLite
    # ---------------------------------------------------------
    if database.USE_POSTGRES:
        try:
            pool = await database.get_pg_pool()
            async with pool.acquire() as conn:
                for item in products_to_save:
                    await conn.execute("""
                        INSERT INTO products_synced (supplier_product_id, name, sell_price, stock_count, in_stock, is_enabled, last_notified_stock, last_synced, api_source, supplier_slug, description)
                        VALUES ($1, $2, $3, $4, $5, 1, $6, $7, $8, $9, $10)
                        ON CONFLICT(supplier_product_id) DO UPDATE SET
                            name = EXCLUDED.name,
                            sell_price = EXCLUDED.sell_price,
                            stock_count = EXCLUDED.stock_count,
                            in_stock = EXCLUDED.in_stock,
                            last_notified_stock = EXCLUDED.last_notified_stock,
                            last_synced = EXCLUDED.last_synced,
                            api_source = EXCLUDED.api_source,
                            supplier_slug = EXCLUDED.supplier_slug,
                            description = EXCLUDED.description
                    """, item["p_id"], item["name"], item["price"], item["stock"], item["in_stock"], item["last_notified"], now_str, item["api_source"], item["supplier_slug"], item["description"])

                if synced_ids:
                    await conn.execute("UPDATE products_synced SET in_stock = 0 WHERE supplier_product_id != ALL($1)", synced_ids)
                
                tot_synced = len(synced_ids)
                await conn.execute("INSERT INTO sync_history (synced_at, items_count, status) VALUES ($1, $2, 'success')", now_str, tot_synced)
        except Exception as e:
            logger.error(f"PG save synced products error: {e}")
    else:
        async with aiosqlite.connect(database.DB_PATH) as db:
            for item in products_to_save:
                await db.execute("""
                    INSERT INTO products_synced (supplier_product_id, name, sell_price, stock_count, in_stock, is_enabled, last_notified_stock, last_synced, api_source, supplier_slug, description)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                    ON CONFLICT(supplier_product_id) DO UPDATE SET
                        name = excluded.name,
                        sell_price = excluded.sell_price,
                        stock_count = excluded.stock_count,
                        in_stock = excluded.in_stock,
                        last_notified_stock = excluded.last_notified_stock,
                        last_synced = excluded.last_synced,
                        api_source = excluded.api_source,
                        supplier_slug = excluded.supplier_slug,
                        description = excluded.description
                """, (item["p_id"], item["name"], item["price"], item["stock"], item["in_stock"], item["last_notified"], now_str, item["api_source"], item["supplier_slug"], item["description"]))

            if synced_ids:
                p1 = ",".join("?" * len(synced_ids))
                await db.execute(f"UPDATE products_synced SET in_stock = 0 WHERE supplier_product_id NOT IN ({p1})", synced_ids)

            tot_synced = len(synced_ids)
            await db.execute("INSERT INTO sync_history (synced_at, items_count, status) VALUES (?, ?, 'success')", (now_str, tot_synced))
            await db.commit()

    invalidate_catalog_cache()
    _is_first_sync_done = True
    tot_synced = len(synced_ids)
    logger.info(f"Catalog Sync Success: {tot_synced} products synchronized.")

    # Trigger announcement ONCE if new products or genuine restocks detected
    if bot and (new_products or restocked_products):
        await notify_new_products_alert(bot, new_products, restocked_products)

    return {
        "status": "success",
        "synced_count": tot_synced,
        "new_count": len(new_products),
        "restocked_count": len(restocked_products)
    }

_CATALOG_CACHE: dict[str, Any] = {}
_CATALOG_CACHE_TS: float = 0.0

def invalidate_catalog_cache():
    global _CATALOG_CACHE, _CATALOG_CACHE_TS
    _CATALOG_CACHE.clear()
    _CATALOG_CACHE_TS = 0.0

async def get_local_catalog(filter_gemini: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Retrieve in-stock synced products from local DB with added profit margin."""
    import time
    global _CATALOG_CACHE, _CATALOG_CACHE_TS
    now_ts = time.time()
    cache_key = f"gemini_{filter_gemini}"

    # Return memory cache if fresh (< 3 seconds)
    if _CATALOG_CACHE.get(cache_key) and (now_ts - _CATALOG_CACHE_TS) < 3.0:
        return _CATALOG_CACHE[cache_key]

    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)

    if filter_gemini is None:
        setting_val = await database.get_setting("catalog_gemini_only", "0")
        should_filter_gemini = (setting_val == "1")
    else:
        should_filter_gemini = filter_gemini

    rows = []
    if database.USE_POSTGRES:
        try:
            pool = await database.get_pg_pool()
            async with pool.acquire() as conn:
                res = await conn.fetch("""
                    SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock, COALESCE(api_source, 'api1') as api_source, supplier_slug, description
                    FROM products_synced
                    WHERE in_stock = 1 AND is_enabled = 1
                    ORDER BY sell_price ASC
                """)
                rows = [dict(r) for r in res]
        except Exception as e:
            logger.error(f"PG get_local_catalog error: {e}")
    else:
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock, COALESCE(api_source, 'api1') as api_source, supplier_slug, description
                FROM products_synced
                WHERE in_stock = 1 AND is_enabled = 1
                ORDER BY sell_price ASC
            """) as cursor:
                res = await cursor.fetchall()
                rows = [dict(r) for r in res]

    api_products = []
    for r in rows:
        p_dict = dict(r)
        if should_filter_gemini and "gemini" not in p_dict["name"].lower():
            continue
        p_id_str = str(p_dict["id"])
        margin = margins.get(p_id_str, default_margin)
        supplier_price = p_dict["supplier_price"]
        p_dict["sell_price"] = round(supplier_price + margin, 2)
        p_dict["margin"] = margin
        p_dict["supplier_price"] = supplier_price
        p_dict["is_custom"] = False
        p_dict["api_source"] = p_dict.get("api_source", "api1")
        p_dict["supplier_slug"] = p_dict.get("supplier_slug")
        api_products.append(p_dict)

    custom_products_list = []
    # Priority 1: Admin / Assistant In-House Custom Products (Show at the very TOP of Page 1)
    try:
        custom_prods = await database.get_custom_products(only_active=True)
        for cp in custom_prods:
            stock_cnt = int(cp.get("stock_count", 0))
            if stock_cnt > 0:
                c_id = int(cp["id"])
                mapped_id = 90000 + c_id
                custom_products_list.append({
                    "id": mapped_id,
                    "product_id": mapped_id,
                    "name": cp["name"],
                    "sell_price": float(cp["price"]),
                    "supplier_price": float(cp["price"]),
                    "margin": 0.0,
                    "stock_count": stock_cnt,
                    "in_stock": 1,
                    "is_custom": True,
                    "custom_id": c_id,
                    "api_source": "custom"
                })
    except Exception as e:
        logger.error(f"Error merging custom products in catalog: {e}")

    # Base order: In-house custom products first, followed by supplier API products
    unpinned_products = custom_products_list + api_products

    # Priority 0 (Absolute Top): Admin Pinned Products
    try:
        pinned_ids = await database.get_pinned_product_ids()
        if pinned_ids:
            prod_map = {p["id"]: p for p in unpinned_products}
            pinned_list = []
            for pid in pinned_ids:
                if pid in prod_map:
                    p_item = prod_map[pid]
                    p_item["is_pinned"] = True
                    pinned_list.append(p_item)

            remaining_list = [p for p in unpinned_products if p["id"] not in pinned_ids]
            products = pinned_list + remaining_list
        else:
            products = unpinned_products
    except Exception as e:
        logger.error(f"Error ordering pinned products: {e}")
        products = unpinned_products

    _CATALOG_CACHE[cache_key] = products
    _CATALOG_CACHE_TS = now_ts
    return products

async def get_gemini_products() -> List[Dict[str, Any]]:
    """Retrieve all Gemini products for admin pricing and margin management."""
    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)

    rows = []
    if database.USE_POSTGRES:
        try:
            pool = await database.get_pg_pool()
            async with pool.acquire() as conn:
                res = await conn.fetch("""
                    SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock, COALESCE(api_source, 'api1') as api_source, supplier_slug
                    FROM products_synced
                    WHERE LOWER(name) LIKE '%gemini%'
                    ORDER BY sell_price ASC
                """)
                rows = [dict(r) for r in res]
        except Exception as e:
            logger.error(f"PG get_gemini_products error: {e}")
    else:
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock, COALESCE(api_source, 'api1') as api_source, supplier_slug
                FROM products_synced
                WHERE LOWER(name) LIKE '%gemini%'
                ORDER BY sell_price ASC
            """) as cursor:
                res = await cursor.fetchall()
                rows = [dict(r) for r in res]

    products = []
    for r in rows:
        p_dict = dict(r)
        p_id_str = str(p_dict["id"])
        margin = margins.get(p_id_str, default_margin)
        supplier_price = p_dict["supplier_price"]
        p_dict["sell_price"] = round(supplier_price + margin, 2)
        p_dict["margin"] = margin
        p_dict["supplier_price"] = supplier_price
        p_dict["api_source"] = p_dict.get("api_source", "api1")
        p_dict["supplier_slug"] = p_dict.get("supplier_slug")
        products.append(p_dict)
    return products

async def get_local_product(product_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve a single product from synced DB or Custom Admin Products with margin applied."""
    pid = int(product_id)
    # Instant in-memory lookup
    for k, prods in _CATALOG_CACHE.items():
        if isinstance(prods, list):
            for p in prods:
                if int(p.get("id", 0)) == pid or int(p.get("product_id", 0)) == pid:
                    return p

    if pid >= 90000:
        c_id = pid - 90000
        cp = await database.get_custom_product(c_id)
        if not cp:
            return None
        stock_cnt = int(cp.get("stock_count", 0))
        return {
            "id": int(product_id),
            "product_id": int(product_id),
            "name": cp["name"],
            "sell_price": float(cp["price"]),
            "supplier_price": float(cp["price"]),
            "margin": 0.0,
            "stock_count": stock_cnt,
            "in_stock": 1 if stock_cnt > 0 else 0,
            "is_custom": True,
            "custom_id": c_id,
            "api_source": "custom"
        }

    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)
    p_id_str = str(product_id)
    margin = margins.get(p_id_str, default_margin)

    row = None
    if database.USE_POSTGRES:
        try:
            pool = await database.get_pg_pool()
            async with pool.acquire() as conn:
                r = await conn.fetchrow("""
                    SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock, COALESCE(api_source, 'api1') as api_source, supplier_slug, description
                    FROM products_synced
                    WHERE supplier_product_id = $1
                """, int(product_id))
                if r:
                    row = dict(r)
        except Exception as e:
            logger.error(f"PG get_local_product error: {e}")
    else:
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock, COALESCE(api_source, 'api1') as api_source, supplier_slug, description
                FROM products_synced
                WHERE supplier_product_id = ?
            """, (int(product_id),)) as cursor:
                r = await cursor.fetchone()
                if r:
                    row = dict(r)

    if not row:
        return None
    p_dict = dict(row)
    supplier_price = p_dict["supplier_price"]
    p_dict["sell_price"] = round(supplier_price + margin, 2)
    p_dict["margin"] = margin
    p_dict["supplier_price"] = supplier_price
    p_dict["is_custom"] = False
    p_dict["api_source"] = p_dict.get("api_source", "api1")
    p_dict["supplier_slug"] = p_dict.get("supplier_slug")
    return p_dict

async def start_periodic_catalog_sync(
    api_client: Optional[ShopAPIClient] = None,
    bot = None,
    interval_seconds: int = 120
):
    """Background task to sync product catalog periodically from supplier and notify users ONCE when stock is added."""
    if api_client is None:
        api_client = ShopAPIClient()

    logger.info(f"Starting periodic product sync worker (interval: {interval_seconds}s)...")
    while True:
        try:
            await sync_catalog_now(api_client, bot=bot)
        except Exception as e:
            logger.error(f"Error in catalog sync loop: {e}")
        await asyncio.sleep(interval_seconds)
