import asyncio
import logging
import aiosqlite
from datetime import datetime
from typing import List, Dict, Any, Optional
import database
from shop_api import ShopAPIClient, ShopAPIError

logger = logging.getLogger(__name__)

# Flag to avoid announcing existing stock during the very first boot sync
_is_first_sync_done: bool = False

async def init_catalog_tables():
    """Initialize synced catalog tables in PostgreSQL or SQLite with last_notified_stock tracking."""
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
                        last_synced TEXT
                    )
                """)
                # Ensure column exists if table already existed
                try:
                    await conn.execute("ALTER TABLE products_synced ADD COLUMN IF NOT EXISTS last_notified_stock INTEGER DEFAULT 0")
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
                last_synced TEXT
            )
        """)
        try:
            await db.execute("ALTER TABLE products_synced ADD COLUMN last_notified_stock INTEGER DEFAULT 0")
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
    """Notify group and all registered users ONCE when new products or fresh stock are added."""
    if not bot or (not new_products and not restocked_products):
        return

    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)

    items_text = ""
    if new_products:
        items_text += "🆕 *Newly Added Products:*\n"
        for p in new_products:
            p_id = p["id"]
            name = p["name"]
            if p.get("is_custom") or (isinstance(p_id, int) and p_id >= 90000):
                sell_p = float(p.get("sell_price", 0.0))
            else:
                supplier_p = float(p.get("sell_price", 0.0))
                margin = margins.get(str(p_id), default_margin)
                sell_p = round(supplier_p + margin, 2)
            stock = p.get("stock_count")
            stock_str = f"`{stock}` in stock" if stock is not None else "`Available`"

            items_text += (
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📦 *{name}*\n"
                f"💵 Price: `${sell_p:.2f}` USD\n"
                f"📊 Stock Added: {stock_str}\n"
                f"⚡ Auto-Delivered Instantly\n"
            )

    if restocked_products:
        items_text += "\n🔄 *Restocked Products (Fresh Stock Added):*\n"
        for p in restocked_products:
            p_id = p["id"]
            name = p["name"]
            if p.get("is_custom") or (isinstance(p_id, int) and p_id >= 90000):
                sell_p = float(p.get("sell_price", 0.0))
            else:
                supplier_p = float(p.get("sell_price", 0.0))
                margin = margins.get(str(p_id), default_margin)
                sell_p = round(supplier_p + margin, 2)
            stock = p.get("stock_count")
            added_cnt = p.get("added_count")
            if added_cnt and added_cnt > 0:
                stock_str = f"`+{added_cnt}` added (`{stock}` total)"
            else:
                stock_str = f"`{stock}` available" if stock is not None else "`Available`"

            items_text += (
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📦 *{name}*\n"
                f"💵 Price: `${sell_p:.2f}` USD\n"
                f"📊 Stock: {stock_str}\n"
                f"⚡ Auto-Delivered Instantly\n"
            )

    total_added = len(new_products) + len(restocked_products)
    broadcast_msg = (
        f"🎉 *New Products & Stock Restock Alert! ({total_added} items)*\n\n"
        "We have just added fresh stock to the shop:\n\n"
        f"{items_text}"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        "🛍️ *Tap the button below to browse and buy instantly!*"
    )

    try:
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        from telegram.constants import ParseMode

        bot_info = await bot.get_me()
        bot_user = bot_info.username or "NexvoraGeminiShopebot"
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

async def sync_catalog_now(api_client: Optional[ShopAPIClient] = None, bot = None) -> Dict[str, Any]:
    """Fetch live products from Shop API and update database.
    Detects newly added or restocked products and broadcasts EXACTLY ONCE when stock increases.
    """
    global _is_first_sync_done
    if api_client is None:
        api_client = ShopAPIClient()

    await init_catalog_tables()

    try:
        remote_products = await api_client.get_products()
    except Exception as e:
        logger.error(f"Catalog sync failed: {e}")
        return {"status": "error", "message": str(e), "synced_count": 0}

    # Fetch existing products with last_notified_stock from DB
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
    synced_ids = []
    new_products = []
    restocked_products = []
    products_to_save = []

    for p in remote_products:
        p_id = p.get("id") or p.get("product_id")
        if not p_id:
            continue
        synced_ids.append(p_id)
        name = p.get("name", "Product")
        price = float(p.get("unit_price") if p.get("unit_price") is not None else (p.get("sell_price") or p.get("list_price") or 0.0))
        stock = p.get("stock_count")
        in_stock = 1 if (p.get("in_stock") is True or p.get("in_stock") == 1 or (stock is not None and stock > 0)) else 0
        curr_stock = stock if stock is not None else (1 if in_stock == 1 else 0)

        db_prod = existing_products.get(p_id)
        last_notified = db_prod.get("last_notified_stock", 0) if db_prod else 0

        # Only detect new additions after the first startup cycle has seeded the database
        if _is_first_sync_done and existing_products:
            if p_id not in existing_products and in_stock == 1 and curr_stock > 0:
                # Brand new product added to shop
                new_products.append({"id": p_id, "name": name, "sell_price": price, "stock_count": stock})
                last_notified = curr_stock
            elif p_id in existing_products:
                # Stock increased (restocked)
                if curr_stock > last_notified and in_stock == 1:
                    added_cnt = curr_stock - last_notified
                    restocked_products.append({
                        "id": p_id,
                        "name": name,
                        "sell_price": price,
                        "stock_count": stock,
                        "added_count": added_cnt
                    })
                    last_notified = curr_stock
        else:
            # First sync cycle: Seed the last_notified baseline so current stock is not spammed
            last_notified = max(last_notified, curr_stock)

        products_to_save.append({
            "p_id": p_id,
            "name": name,
            "price": price,
            "stock": stock,
            "in_stock": in_stock,
            "last_notified": last_notified
        })

    # Save to PostgreSQL / SQLite
    if database.USE_POSTGRES:
        try:
            pool = await database.get_pg_pool()
            async with pool.acquire() as conn:
                for item in products_to_save:
                    await conn.execute("""
                        INSERT INTO products_synced (supplier_product_id, name, sell_price, stock_count, in_stock, is_enabled, last_notified_stock, last_synced)
                        VALUES ($1, $2, $3, $4, $5, 1, $6, $7)
                        ON CONFLICT(supplier_product_id) DO UPDATE SET
                            name = EXCLUDED.name,
                            sell_price = EXCLUDED.sell_price,
                            stock_count = EXCLUDED.stock_count,
                            in_stock = EXCLUDED.in_stock,
                            last_notified_stock = EXCLUDED.last_notified_stock,
                            last_synced = EXCLUDED.last_synced
                    """, item["p_id"], item["name"], item["price"], item["stock"], item["in_stock"], item["last_notified"], now_str)

                if synced_ids:
                    await conn.execute("UPDATE products_synced SET in_stock = 0 WHERE supplier_product_id != ALL($1)", synced_ids)
                await conn.execute("INSERT INTO sync_history (synced_at, items_count, status) VALUES ($1, $2, 'success')", now_str, len(synced_ids))
        except Exception as e:
            logger.error(f"PG save synced products error: {e}")
    else:
        async with aiosqlite.connect(database.DB_PATH) as db:
            for item in products_to_save:
                await db.execute("""
                    INSERT INTO products_synced (supplier_product_id, name, sell_price, stock_count, in_stock, is_enabled, last_notified_stock, last_synced)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(supplier_product_id) DO UPDATE SET
                        name = excluded.name,
                        sell_price = excluded.sell_price,
                        stock_count = excluded.stock_count,
                        in_stock = excluded.in_stock,
                        last_notified_stock = excluded.last_notified_stock,
                        last_synced = excluded.last_synced
                """, (item["p_id"], item["name"], item["price"], item["stock"], item["in_stock"], item["last_notified"], now_str))

            if synced_ids:
                placeholders = ",".join("?" * len(synced_ids))
                await db.execute(f"UPDATE products_synced SET in_stock = 0 WHERE supplier_product_id NOT IN ({placeholders})", synced_ids)
            await db.execute("INSERT INTO sync_history (synced_at, items_count, status) VALUES (?, ?, 'success')", (now_str, len(synced_ids)))
            await db.commit()

    logger.info(f"Catalog Sync Success: {len(synced_ids)} products synchronized.")
    _is_first_sync_done = True

    # Trigger announcement ONCE if new products or genuine restocks detected
    if bot and (new_products or restocked_products):
        await notify_new_products_alert(bot, new_products, restocked_products)

    return {
        "status": "success",
        "synced_count": len(synced_ids),
        "new_count": len(new_products),
        "restocked_count": len(restocked_products)
    }

async def get_local_catalog(filter_gemini: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Retrieve in-stock synced products from local DB with added profit margin."""
    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)

    if filter_gemini is None:
        setting_val = await database.get_setting("catalog_gemini_only", "1")
        should_filter_gemini = (setting_val == "1")
    else:
        should_filter_gemini = filter_gemini

    rows = []
    if database.USE_POSTGRES:
        try:
            pool = await database.get_pg_pool()
            async with pool.acquire() as conn:
                res = await conn.fetch("""
                    SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock
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
                SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock
                FROM products_synced
                WHERE in_stock = 1 AND is_enabled = 1
                ORDER BY sell_price ASC
            """) as cursor:
                res = await cursor.fetchall()
                rows = [dict(r) for r in res]

    products = []
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
        products.append(p_dict)

    # Seamlessly merge Admin In-House Custom Products (Gmail:Pass, Accounts, etc.)
    try:
        custom_prods = await database.get_custom_products(only_active=True)
        for cp in custom_prods:
            stock_cnt = int(cp.get("stock_count", 0))
            if stock_cnt > 0:
                c_id = int(cp["id"])
                mapped_id = 90000 + c_id
                products.append({
                    "id": mapped_id,
                    "product_id": mapped_id,
                    "name": cp["name"],
                    "sell_price": float(cp["price"]),
                    "supplier_price": float(cp["price"]),
                    "margin": 0.0,
                    "stock_count": stock_cnt,
                    "in_stock": 1,
                    "is_custom": True,
                    "custom_id": c_id
                })
    except Exception as e:
        logger.error(f"Error merging custom products in catalog: {e}")

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
                    SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock
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
                SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock
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
        products.append(p_dict)
    return products

async def get_local_product(product_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve a single product from synced DB or Custom Admin Products with margin applied."""
    if int(product_id) >= 90000:
        c_id = int(product_id) - 90000
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
            "custom_id": c_id
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
                    SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock
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
                SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock
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
    return p_dict

async def start_periodic_catalog_sync(api_client: ShopAPIClient, bot = None, interval_seconds: int = 120):
    """Background task to sync product catalog periodically and notify users ONCE when stock is added."""
    logger.info(f"Starting periodic product sync worker (interval: {interval_seconds}s)...")
    while True:
        try:
            await sync_catalog_now(api_client, bot=bot)
        except Exception as e:
            logger.error(f"Error in catalog sync loop: {e}")
        await asyncio.sleep(interval_seconds)
