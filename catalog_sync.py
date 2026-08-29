import asyncio
import logging
import aiosqlite
from datetime import datetime
from typing import List, Dict, Any, Optional
import database
from shop_api import ShopAPIClient, ShopAPIError

logger = logging.getLogger(__name__)

async def init_catalog_tables():
    """Initialize local synced catalog tables."""
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
                last_synced TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sync_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                synced_at TEXT,
                items_count INTEGER,
                status TEXT
            )
        """)
        await db.commit()

async def sync_catalog_now(api_client: Optional[ShopAPIClient] = None) -> Dict[str, Any]:
    """Fetch live products from Shop API and update local synced database."""
    if api_client is None:
        api_client = ShopAPIClient()

    await init_catalog_tables()

    try:
        remote_products = await api_client.get_products()
    except Exception as e:
        logger.error(f"Catalog sync failed: {e}")
        return {"status": "error", "message": str(e), "synced_count": 0}

    now_str = datetime.utcnow().isoformat()
    synced_ids = []

    async with aiosqlite.connect(database.DB_PATH) as db:
        for p in remote_products:
            p_id = p.get("id") or p.get("product_id")
            if not p_id:
                continue
            synced_ids.append(p_id)
            name = p.get("name", "Product")
            price = float(p.get("sell_price", 0.0))
            stock = p.get("stock_count")
            in_stock = 1 if p.get("in_stock", True) else 0

            await db.execute("""
                INSERT INTO products_synced (supplier_product_id, name, sell_price, stock_count, in_stock, is_enabled, last_synced)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(supplier_product_id) DO UPDATE SET
                    name = excluded.name,
                    sell_price = excluded.sell_price,
                    stock_count = excluded.stock_count,
                    in_stock = excluded.in_stock,
                    last_synced = excluded.last_synced
            """, (p_id, name, price, stock, in_stock, now_str))

        # Mark items not in payload as out of stock
        if synced_ids:
            placeholders = ",".join("?" * len(synced_ids))
            await db.execute(f"""
                UPDATE products_synced SET in_stock = 0 WHERE supplier_product_id NOT IN ({placeholders})
            """, synced_ids)

        await db.execute("""
            INSERT INTO sync_history (synced_at, items_count, status)
            VALUES (?, ?, 'success')
        """, (now_str, len(synced_ids)))
        await db.commit()

    logger.info(f"Catalog Sync Success: {len(synced_ids)} products synchronized locally.")
    return {"status": "success", "synced_count": len(synced_ids)}

async def get_local_catalog(filter_gemini: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Retrieve in-stock synced products from local DB with added profit margin.
    If filter_gemini is None, respects database setting 'catalog_gemini_only' (default: True).
    """
    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)

    if filter_gemini is None:
        setting_val = await database.get_setting("catalog_gemini_only", "1")
        should_filter_gemini = (setting_val == "1")
    else:
        should_filter_gemini = filter_gemini

    async with aiosqlite.connect(database.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock
            FROM products_synced
            WHERE in_stock = 1 AND is_enabled = 1
            ORDER BY sell_price ASC
        """) as cursor:
            rows = await cursor.fetchall()
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
                products.append(p_dict)
            return products

async def get_gemini_products() -> List[Dict[str, Any]]:
    """Retrieve all Gemini products for admin pricing and margin management."""
    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)

    async with aiosqlite.connect(database.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock
            FROM products_synced
            WHERE LOWER(name) LIKE '%gemini%'
            ORDER BY sell_price ASC
        """) as cursor:
            rows = await cursor.fetchall()
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
    """Retrieve a single product from local synced DB with margin applied."""
    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)
    p_id_str = str(product_id)
    margin = margins.get(p_id_str, default_margin)

    async with aiosqlite.connect(database.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT supplier_product_id as id, supplier_product_id as product_id, name, sell_price as supplier_price, stock_count, in_stock
            FROM products_synced
            WHERE supplier_product_id = ?
        """, (product_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            p_dict = dict(row)
            supplier_price = p_dict["supplier_price"]
            p_dict["sell_price"] = round(supplier_price + margin, 2)
            p_dict["margin"] = margin
            p_dict["supplier_price"] = supplier_price
            return p_dict

async def start_periodic_catalog_sync(api_client: ShopAPIClient, interval_seconds: int = 180):
    """Background task to sync product catalog periodically (default 3 mins)."""
    logger.info(f"Starting periodic product sync worker (interval: {interval_seconds}s)...")
    while True:
        try:
            await sync_catalog_now(api_client)
        except Exception as e:
            logger.error(f"Error in catalog sync loop: {e}")
        await asyncio.sleep(interval_seconds)
