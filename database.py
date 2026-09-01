import os
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "bot_data.db")

# PostgreSQL / Supabase config
DATABASE_URL = os.getenv("DATABASE_URL")
PG_HOST = os.getenv("POSTGRES_HOST") or os.getenv("PG_HOST")
PG_PORT = int(os.getenv("POSTGRES_PORT") or os.getenv("PG_PORT") or 5432)
PG_USER = os.getenv("POSTGRES_USER") or os.getenv("PG_USER")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD") or os.getenv("PG_PASSWORD")
PG_DATABASE = os.getenv("POSTGRES_DATABASE") or os.getenv("PG_DATABASE") or "postgres"

USE_POSTGRES = bool(DATABASE_URL or (PG_HOST and PG_USER and PG_PASSWORD))

import asyncio
_pg_pool = None
_pg_pool_loop = None

async def get_pg_pool():
    global _pg_pool, _pg_pool_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _pg_pool is None or _pg_pool_loop is None or _pg_pool_loop != current_loop or _pg_pool_loop.is_closed():
        if _pg_pool is not None:
            try:
                _pg_pool.terminate()
            except Exception:
                pass
            _pg_pool = None

        import asyncpg
        from urllib.parse import urlparse, unquote
        
        host = PG_HOST
        port = PG_PORT
        user = PG_USER
        password = PG_PASSWORD
        database_name = PG_DATABASE

        if DATABASE_URL:
            try:
                # Handle cases where password contains '@'
                url = DATABASE_URL
                if url.startswith("postgres://"):
                    url = "postgresql://" + url[len("postgres://"):]
                
                # If direct parse works
                parsed = urlparse(url)
                if parsed.hostname:
                    host = parsed.hostname
                    port = parsed.port or 5432
                    user = unquote(parsed.username) if parsed.username else user
                    password = unquote(parsed.password) if parsed.password else password
                    database_name = parsed.path.lstrip("/") or database_name
            except Exception:
                pass

        _pg_pool = await asyncpg.create_pool(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database_name,
            ssl="require",
            min_size=1,
            max_size=10,
            timeout=10
        )
        _pg_pool_loop = current_loop
    return _pg_pool

async def init_db():
    """Initialize database tables."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        created_at TEXT,
                        last_active TEXT
                    );
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    );
                    CREATE TABLE IF NOT EXISTS orders_local (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        order_id BIGINT,
                        product_id BIGINT,
                        product_name TEXT,
                        quantity INTEGER,
                        total DOUBLE PRECISION,
                        status TEXT,
                        delivered_keys TEXT,
                        created_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS product_margins (
                        product_key TEXT PRIMARY KEY,
                        margin DOUBLE PRECISION
                    );
                    CREATE TABLE IF NOT EXISTS user_balances (
                        user_id BIGINT PRIMARY KEY,
                        balance DOUBLE PRECISION DEFAULT 0.0
                    );
                    CREATE TABLE IF NOT EXISTS deposits (
                        merchant_trade_no TEXT PRIMARY KEY,
                        user_id BIGINT,
                        amount DOUBLE PRECISION,
                        status TEXT,
                        checkout_url TEXT,
                        bep20 TEXT,
                        trc20 TEXT,
                        erc20 TEXT,
                        network TEXT,
                        tx_hash TEXT,
                        created_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS blocked_buyers (
                        user_id BIGINT PRIMARY KEY,
                        reason TEXT,
                        blocked_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS assistants (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        added_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS custom_products (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        price DOUBLE PRECISION NOT NULL,
                        description TEXT,
                        is_active INTEGER DEFAULT 1,
                        created_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS custom_product_stocks (
                        id SERIAL PRIMARY KEY,
                        product_id INTEGER NOT NULL,
                        stock_data TEXT NOT NULL,
                        is_sold INTEGER DEFAULT 0,
                        sold_to_user_id BIGINT,
                        sold_at TEXT,
                        created_at TEXT
                    );
                """)
                logger.info("Supabase PostgreSQL tables initialized.")
                return
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL DB: {e}. Falling back to SQLite.")

    # SQLite fallback
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TEXT,
                last_active TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders_local (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                order_id INTEGER,
                product_id INTEGER,
                product_name TEXT,
                quantity INTEGER,
                total REAL,
                status TEXT,
                delivered_keys TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS product_margins (
                product_key TEXT PRIMARY KEY,
                margin REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_balances (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0.0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                merchant_trade_no TEXT PRIMARY KEY,
                user_id INTEGER,
                amount REAL,
                status TEXT,
                checkout_url TEXT,
                bep20 TEXT,
                trc20 TEXT,
                erc20 TEXT,
                network TEXT,
                tx_hash TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blocked_buyers (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                blocked_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS assistants (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                added_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS custom_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                description TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS custom_product_stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                stock_data TEXT NOT NULL,
                is_sold INTEGER DEFAULT 0,
                sold_to_user_id INTEGER,
                sold_at TEXT,
                created_at TEXT
            )
        """)
        for col, col_type in [("tx_hash", "TEXT"), ("network", "TEXT")]:
            try:
                await db.execute(f"ALTER TABLE deposits ADD COLUMN {col} {col_type}")
            except Exception:
                pass
        await db.commit()
        logger.info("SQLite database tables initialized.")

async def register_user(user_id: int, username: str = None, first_name: str = None):
    now = datetime.utcnow().isoformat()
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO users (user_id, username, first_name, created_at, last_active)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT(user_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_active = EXCLUDED.last_active
                """, int(user_id), username, first_name, now, now)
                return
        except Exception as e:
            logger.error(f"PG register_user error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, first_name, created_at, last_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_active = excluded.last_active
        """, (user_id, username, first_name, now, now))
        await db.commit()

async def get_user_count() -> int:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                return await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        except Exception as e:
            logger.error(f"PG get_user_count error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_user_id_by_identifier(identifier: str) -> int:
    clean = str(identifier).strip().lstrip("@")
    if clean.isdigit():
        return int(clean)
    
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                u_id = await conn.fetchval("SELECT user_id FROM users WHERE LOWER(username) = LOWER($1)", clean)
                if u_id:
                    return u_id
                u_id2 = await conn.fetchval("SELECT user_id FROM users WHERE LOWER(first_name) = LOWER($1)", clean)
                if u_id2:
                    return u_id2
                return None
        except Exception as e:
            logger.error(f"PG get_user_id_by_identifier error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)", (clean,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
        async with db.execute("SELECT user_id FROM users WHERE LOWER(first_name) = LOWER(?)", (clean,)) as cursor2:
            row2 = await cursor2.fetchone()
            if row2:
                return row2[0]
    return None

async def get_all_users_with_balances(limit: int = 15) -> list[dict]:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT u.user_id, u.username, u.first_name, COALESCE(b.balance, 0.0) as balance, u.last_active
                    FROM users u
                    LEFT JOIN user_balances b ON u.user_id = b.user_id
                    ORDER BY u.last_active DESC
                    LIMIT $1
                """, limit)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"PG get_all_users_with_balances error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT u.user_id, u.username, u.first_name, COALESCE(b.balance, 0.0) as balance, u.last_active
            FROM users u
            LEFT JOIN user_balances b ON u.user_id = b.user_id
            ORDER BY u.last_active DESC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_all_user_ids() -> list[int]:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT user_id FROM users")
                return [r["user_id"] for r in rows]
        except Exception as e:
            logger.error(f"PG get_all_user_ids error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

async def set_setting(key: str, value: str):
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO settings (key, value)
                    VALUES ($1, $2)
                    ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
                """, str(key), str(value))
                return
        except Exception as e:
            logger.error(f"PG set_setting error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        await db.commit()

async def get_setting(key: str, default: str = None) -> str:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                val = await conn.fetchval("SELECT value FROM settings WHERE key = $1", str(key))
                return val if val is not None else default
        except Exception as e:
            logger.error(f"PG get_setting error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default

async def record_order(user_id: int, order_id: int, product_id: int, product_name: str, quantity: int, total: float, status: str, delivered_keys: list):
    now = datetime.utcnow().isoformat()
    keys_str = "\n".join(delivered_keys) if delivered_keys else ""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO orders_local (user_id, order_id, product_id, product_name, quantity, total, status, delivered_keys, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """, int(user_id), int(order_id) if order_id else None, int(product_id) if product_id else None, product_name, int(quantity), float(total), status, keys_str, now)
                return
        except Exception as e:
            logger.error(f"PG record_order error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO orders_local (user_id, order_id, product_id, product_name, quantity, total, status, delivered_keys, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, order_id, product_id, product_name, quantity, total, status, keys_str, now))
        await db.commit()

async def get_user_orders(user_id: int, limit: int = 10) -> list[dict]:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM orders_local WHERE user_id = $1 ORDER BY id DESC LIMIT $2
                """, int(user_id), limit)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"PG get_user_orders error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM orders_local WHERE user_id = ? ORDER BY id DESC LIMIT ?
        """, (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_stats() -> dict:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                u_count = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
                row = await conn.fetchrow("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM orders_local")
                o_count, total_sales = row[0], float(row[1]) if row else 0.0
                total_users_bal = await conn.fetchval("SELECT COALESCE(SUM(balance), 0.0) FROM user_balances") or 0.0
                users_with_bal = await conn.fetchval("SELECT COUNT(*) FROM user_balances WHERE balance > 0") or 0
                total_deposited = await conn.fetchval("SELECT COALESCE(SUM(amount), 0.0) FROM deposits WHERE status = 'PAID'") or 0.0
                return {
                    "total_users": u_count,
                    "total_orders": o_count,
                    "total_sales": total_sales,
                    "total_users_balance": float(total_users_bal),
                    "users_with_balance": users_with_bal,
                    "total_deposited": float(total_deposited)
                }
        except Exception as e:
            logger.error(f"PG get_stats error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1:
            u_count = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM orders_local") as c2:
            row = await c2.fetchone()
            o_count, total_sales = row[0], row[1]
        async with db.execute("SELECT COALESCE(SUM(balance), 0.0) FROM user_balances") as c3:
            total_users_bal = (await c3.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM user_balances WHERE balance > 0") as c4:
            users_with_bal = (await c4.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(amount), 0.0) FROM deposits WHERE status = 'PAID'") as c5:
            total_deposited = (await c5.fetchone())[0]
        return {
            "total_users": u_count,
            "total_orders": o_count,
            "total_sales": total_sales,
            "total_users_balance": float(total_users_bal or 0.0),
            "users_with_balance": users_with_bal,
            "total_deposited": float(total_deposited or 0.0)
        }

async def get_total_users_balance() -> tuple[float, int]:
    """Returns (total_combined_balance, count_of_users_with_balance)."""
    stats = await get_stats()
    return (stats.get("total_users_balance", 0.0), stats.get("users_with_balance", 0))

async def set_product_margin(product_key: str, margin: float):
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO product_margins (product_key, margin)
                    VALUES ($1, $2)
                    ON CONFLICT(product_key) DO UPDATE SET margin = EXCLUDED.margin
                """, str(product_key).strip(), float(margin))
                return
        except Exception as e:
            logger.error(f"PG set_product_margin error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO product_margins (product_key, margin)
            VALUES (?, ?)
            ON CONFLICT(product_key) DO UPDATE SET margin = excluded.margin
        """, (str(product_key).strip(), float(margin)))
        await db.commit()

async def get_all_margins() -> dict:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT product_key, margin FROM product_margins")
                return {r["product_key"]: float(r["margin"]) for r in rows}
        except Exception as e:
            logger.error(f"PG get_all_margins error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT product_key, margin FROM product_margins") as cursor:
            rows = await cursor.fetchall()
            return {r[0]: float(r[1]) for r in rows}

async def get_margin_for_product(product_id: int) -> float:
    margins = await get_all_margins()
    p_key = str(product_id)
    if p_key in margins:
        return margins[p_key]
    return margins.get("default", 0.20)

async def delete_product_margin(product_key: str):
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM product_margins WHERE product_key = $1", str(product_key).strip())
                return
        except Exception as e:
            logger.error(f"PG delete_product_margin error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM product_margins WHERE product_key = ?", (str(product_key).strip(),))
        await db.commit()

async def get_user_balance(user_id: int) -> float:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                bal = await conn.fetchval("SELECT balance FROM user_balances WHERE user_id = $1", int(user_id))
                return float(bal) if bal is not None else 0.0
        except Exception as e:
            logger.error(f"PG get_user_balance error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM user_balances WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return float(row[0]) if row else 0.0

async def add_user_balance(user_id: int, amount: float) -> float:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO user_balances (user_id, balance)
                    VALUES ($1, $2)
                    ON CONFLICT(user_id) DO UPDATE SET balance = user_balances.balance + EXCLUDED.balance
                """, int(user_id), float(amount))
                return await get_user_balance(user_id)
        except Exception as e:
            logger.error(f"PG add_user_balance error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO user_balances (user_id, balance)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance
        """, (user_id, float(amount)))
        await db.commit()
    return await get_user_balance(user_id)

async def deduct_user_balance(user_id: int, amount: float) -> bool:
    curr = await get_user_balance(user_id)
    if curr < amount:
        return False
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE user_balances SET balance = balance - $1 WHERE user_id = $2
                """, float(amount), int(user_id))
                return True
        except Exception as e:
            logger.error(f"PG deduct_user_balance error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE user_balances SET balance = balance - ? WHERE user_id = ?
        """, (float(amount), user_id))
        await db.commit()
    return True

async def force_deduct_user_balance(user_id: int, amount: float) -> float:
    curr = await get_user_balance(user_id)
    new_bal = max(0.0, curr - float(amount))
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO user_balances (user_id, balance)
                    VALUES ($1, $2)
                    ON CONFLICT(user_id) DO UPDATE SET balance = $2
                """, int(user_id), new_bal)
                return new_bal
        except Exception as e:
            logger.error(f"PG force_deduct_user_balance error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO user_balances (user_id, balance)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET balance = ?
        """, (user_id, new_bal, new_bal))
        await db.commit()
    return new_bal

async def set_user_balance(user_id: int, amount: float) -> float:
    new_bal = max(0.0, float(amount))
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO user_balances (user_id, balance)
                    VALUES ($1, $2)
                    ON CONFLICT(user_id) DO UPDATE SET balance = EXCLUDED.balance
                """, int(user_id), new_bal)
                return await get_user_balance(user_id)
        except Exception as e:
            logger.error(f"PG set_user_balance error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO user_balances (user_id, balance)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET balance = excluded.balance
        """, (user_id, new_bal))
        await db.commit()
    return await get_user_balance(user_id)

async def get_user_info(user_id: int) -> dict:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", int(user_id))
                user_dict = dict(row) if row else {"user_id": user_id, "username": None, "first_name": "Unknown"}
                user_dict["balance"] = await get_user_balance(user_id)
                return user_dict
        except Exception as e:
            logger.error(f"PG get_user_info error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user_row = await cursor.fetchone()
            user_dict = dict(user_row) if user_row else {"user_id": user_id, "username": None, "first_name": "Unknown"}
    user_dict["balance"] = await get_user_balance(user_id)
    return user_dict

async def create_deposit_record(
    merchant_trade_no: str,
    user_id: int,
    amount: float,
    status: str = "INITIAL",
    checkout_url: str = None,
    bep20: str = None,
    trc20: str = None,
    erc20: str = None,
    network: str = None,
    tx_hash: str = None
):
    now = datetime.utcnow().isoformat()
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO deposits (merchant_trade_no, user_id, amount, status, checkout_url, bep20, trc20, erc20, network, tx_hash, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """, merchant_trade_no, int(user_id), float(amount), status, checkout_url, bep20, trc20, erc20, network, tx_hash, now)
                return
        except Exception as e:
            logger.error(f"PG create_deposit_record error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO deposits (merchant_trade_no, user_id, amount, status, checkout_url, bep20, trc20, erc20, network, tx_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (merchant_trade_no, user_id, float(amount), status, checkout_url, bep20, trc20, erc20, network, tx_hash, now))
        await db.commit()

async def record_deposit_txhash(merchant_trade_no: str, network: str, tx_hash: str, status: str = "PENDING_VERIFICATION"):
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE deposits SET network = $1, tx_hash = $2, status = $3 WHERE merchant_trade_no = $4
                """, network, tx_hash, status, merchant_trade_no)
                return
        except Exception as e:
            logger.error(f"PG record_deposit_txhash error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE deposits SET network = ?, tx_hash = ?, status = ? WHERE merchant_trade_no = ?
        """, (network, tx_hash, status, merchant_trade_no))
        await db.commit()

async def update_deposit_status(merchant_trade_no: str, status: str):
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE deposits SET status = $1 WHERE merchant_trade_no = $2
                """, status, merchant_trade_no)
                return
        except Exception as e:
            logger.error(f"PG update_deposit_status error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE deposits SET status = ? WHERE merchant_trade_no = ?
        """, (status, merchant_trade_no))
        await db.commit()

async def get_deposit_record(merchant_trade_no: str) -> dict:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM deposits WHERE merchant_trade_no = $1", merchant_trade_no)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"PG get_deposit_record error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM deposits WHERE merchant_trade_no = ?", (merchant_trade_no,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_pending_deposits() -> list[dict]:
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM deposits WHERE status IN ('INITIAL', 'PENDING', 'PENDING_VERIFICATION') ORDER BY created_at DESC")
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"PG get_pending_deposits error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM deposits WHERE status IN ('INITIAL', 'PENDING', 'PENDING_VERIFICATION') ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def approve_deposit(merchant_trade_no: str) -> dict:
    rec = await get_deposit_record(merchant_trade_no)
    if not rec:
        return None
    if rec["status"] == "PAID":
        return rec

    await update_deposit_status(merchant_trade_no, "PAID")
    new_bal = await add_user_balance(rec["user_id"], rec["amount"])
    rec["new_balance"] = new_bal
    rec["status"] = "PAID"
    return rec

async def is_txhash_used(tx_hash: str, current_trade_no: str = None) -> bool:
    """Check if a TxHash has already been submitted or approved to prevent fake duplicate submissions."""
    clean_tx = tx_hash.strip().lower()
    if not clean_tx:
        return False
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                if current_trade_no:
                    count = await conn.fetchval(
                        "SELECT COUNT(*) FROM deposits WHERE LOWER(tx_hash) = $1 AND merchant_trade_no != $2 AND status IN ('PAID', 'PENDING_VERIFICATION')",
                        clean_tx, current_trade_no
                    )
                else:
                    count = await conn.fetchval(
                        "SELECT COUNT(*) FROM deposits WHERE LOWER(tx_hash) = $1 AND status IN ('PAID', 'PENDING_VERIFICATION')",
                        clean_tx
                    )
                return bool(count and count > 0)
        except Exception as e:
            logger.error(f"PG is_txhash_used error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        if current_trade_no:
            async with db.execute(
                "SELECT COUNT(*) FROM deposits WHERE LOWER(tx_hash) = LOWER(?) AND merchant_trade_no != ? AND status IN ('PAID', 'PENDING_VERIFICATION')",
                (clean_tx, current_trade_no)
            ) as cursor:
                row = await cursor.fetchone()
                return bool(row and row[0] > 0)
        else:
            async with db.execute(
                "SELECT COUNT(*) FROM deposits WHERE LOWER(tx_hash) = LOWER(?) AND status IN ('PAID', 'PENDING_VERIFICATION')",
                (clean_tx,)
            ) as cursor:
                row = await cursor.fetchone()
                return bool(row and row[0] > 0)

async def get_all_deposits(limit: int = 30, status: str = None) -> list[dict]:
    """Retrieve full history of deposits with user info."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                if status:
                    rows = await conn.fetch("""
                        SELECT d.*, u.username, u.first_name, COALESCE(b.balance, 0.0) as current_balance
                        FROM deposits d
                        LEFT JOIN users u ON d.user_id = u.user_id
                        LEFT JOIN user_balances b ON d.user_id = b.user_id
                        WHERE d.status = $1
                        ORDER BY d.created_at DESC
                        LIMIT $2
                    """, status.upper(), limit)
                else:
                    rows = await conn.fetch("""
                        SELECT d.*, u.username, u.first_name, COALESCE(b.balance, 0.0) as current_balance
                        FROM deposits d
                        LEFT JOIN users u ON d.user_id = u.user_id
                        LEFT JOIN user_balances b ON d.user_id = b.user_id
                        ORDER BY d.created_at DESC
                        LIMIT $1
                    """, limit)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"PG get_all_deposits error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            async with db.execute("""
                SELECT d.*, u.username, u.first_name, COALESCE(b.balance, 0.0) as current_balance
                FROM deposits d
                LEFT JOIN users u ON d.user_id = u.user_id
                LEFT JOIN user_balances b ON d.user_id = b.user_id
                WHERE d.status = ?
                ORDER BY d.created_at DESC
                LIMIT ?
            """, (status.upper(), limit)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        else:
            async with db.execute("""
                SELECT d.*, u.username, u.first_name, COALESCE(b.balance, 0.0) as current_balance
                FROM deposits d
                LEFT JOIN users u ON d.user_id = u.user_id
                LEFT JOIN user_balances b ON d.user_id = b.user_id
                ORDER BY d.created_at DESC
                LIMIT ?
            """, (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

async def get_deposited_users_summary() -> list[dict]:
    """Get aggregated list of all users who deposited, total paid amount, and their current live balance."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT 
                        u.user_id,
                        u.username,
                        u.first_name,
                        COALESCE(b.balance, 0.0) as live_balance,
                        COUNT(d.merchant_trade_no) as total_deposits_count,
                        COALESCE(SUM(CASE WHEN d.status = 'PAID' THEN d.amount ELSE 0.0 END), 0.0) as total_deposited_paid,
                        MAX(d.created_at) as last_deposit_time
                    FROM users u
                    JOIN deposits d ON u.user_id = d.user_id
                    LEFT JOIN user_balances b ON u.user_id = b.user_id
                    GROUP BY u.user_id, u.username, u.first_name, b.balance
                    ORDER BY total_deposited_paid DESC, live_balance DESC
                """)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"PG get_deposited_users_summary error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT 
                u.user_id,
                u.username,
                u.first_name,
                COALESCE(b.balance, 0.0) as live_balance,
                COUNT(d.merchant_trade_no) as total_deposits_count,
                COALESCE(SUM(CASE WHEN d.status = 'PAID' THEN d.amount ELSE 0.0 END), 0.0) as total_deposited_paid,
                MAX(d.created_at) as last_deposit_time
            FROM users u
            JOIN deposits d ON u.user_id = d.user_id
            LEFT JOIN user_balances b ON u.user_id = b.user_id
            GROUP BY u.user_id, u.username, u.first_name, b.balance
            ORDER BY total_deposited_paid DESC, live_balance DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def export_full_backup() -> tuple[str, str]:
    import json
    backup_dir = os.path.join(os.path.dirname(__file__), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(backup_dir, f"bot_backup_{timestamp_str}.json")
    latest_json_path = os.path.join(backup_dir, "bot_backup_latest.json")

    backup_data = {
        "exported_at": datetime.utcnow().isoformat(),
        "users": [],
        "user_balances": [],
        "orders": [],
        "deposits": [],
        "settings": [],
        "product_margins": []
    }

    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                for table in ["users", "user_balances", "orders_local", "deposits", "settings", "product_margins"]:
                    key_name = "orders" if table == "orders_local" else table
                    rows = await conn.fetch(f"SELECT * FROM {table}")
                    backup_data[key_name] = [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"PG export error: {e}")
    else:
        import aiosqlite
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            for table in ["users", "user_balances", "orders_local", "deposits", "settings", "product_margins"]:
                key_name = "orders" if table == "orders_local" else table
                async with db.execute(f"SELECT * FROM {table}") as cursor:
                    rows = await cursor.fetchall()
                    backup_data[key_name] = [dict(r) for r in rows]

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False)

    with open(latest_json_path, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False)

    return (latest_json_path, DB_PATH)

async def block_user_buying(user_id: int, reason: str = "Admin Restricted") -> bool:
    """Block a specific user from placing orders/buying products."""
    now = datetime.utcnow().isoformat()
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO blocked_buyers (user_id, reason, blocked_at)
                    VALUES ($1, $2, $3)
                    ON CONFLICT(user_id) DO UPDATE SET reason = EXCLUDED.reason, blocked_at = EXCLUDED.blocked_at
                """, int(user_id), reason, now)
                return True
        except Exception as e:
            logger.error(f"PG block_user_buying error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO blocked_buyers (user_id, reason, blocked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET reason = excluded.reason, blocked_at = excluded.blocked_at
        """, (int(user_id), reason, now))
        await db.commit()
    return True

async def unblock_user_buying(user_id: int) -> bool:
    """Unblock a user to restore their buying permissions."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM blocked_buyers WHERE user_id = $1", int(user_id))
                return True
        except Exception as e:
            logger.error(f"PG unblock_user_buying error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM blocked_buyers WHERE user_id = ?", (int(user_id),))
        await db.commit()
    return True

async def is_user_buying_blocked(user_id: int) -> bool:
    """Check if user has been blocked by Admin from making purchases."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                cnt = await conn.fetchval("SELECT COUNT(*) FROM blocked_buyers WHERE user_id = $1", int(user_id))
                return bool(cnt and cnt > 0)
        except Exception as e:
            logger.error(f"PG is_user_buying_blocked error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM blocked_buyers WHERE user_id = ?", (int(user_id),)) as cursor:
            row = await cursor.fetchone()
            return bool(row and row[0] > 0)
    return False

async def get_blocked_buyers() -> list[dict]:
    """Get list of all users whose buying permissions are currently blocked."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT b.user_id, b.reason, b.blocked_at, u.username, u.first_name, COALESCE(ub.balance, 0.0) as balance
                    FROM blocked_buyers b
                    LEFT JOIN users u ON b.user_id = u.user_id
                    LEFT JOIN user_balances ub ON b.user_id = ub.user_id
                    ORDER BY b.blocked_at DESC
                """)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"PG get_blocked_buyers error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT b.user_id, b.reason, b.blocked_at, u.username, u.first_name, COALESCE(ub.balance, 0.0) as balance
            FROM blocked_buyers b
            LEFT JOIN users u ON b.user_id = u.user_id
            LEFT JOIN user_balances ub ON b.user_id = ub.user_id
            ORDER BY b.blocked_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

# ── CUSTOM IN-HOUSE PRODUCTS & STOCK MANAGEMENT ──

async def add_custom_product(name: str, price: float, description: str = "") -> int:
    """Create a new in-house custom product (e.g. Gmail:Pass, Accounts, Keys)."""
    now = datetime.utcnow().isoformat()
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                prod_id = await conn.fetchval("""
                    INSERT INTO custom_products (name, price, description, is_active, created_at)
                    VALUES ($1, $2, $3, 1, $4)
                    RETURNING id
                """, name.strip(), float(price), description.strip(), now)
                return int(prod_id)
        except Exception as e:
            logger.error(f"PG add_custom_product error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO custom_products (name, price, description, is_active, created_at)
            VALUES (?, ?, ?, 1, ?)
        """, (name.strip(), float(price), description.strip(), now))
        await db.commit()
        return cursor.lastrowid

async def get_custom_products(only_active: bool = True) -> list[dict]:
    """Retrieve all in-house products with live available stock count."""
    rows = []
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                query = """
                    SELECT p.id, p.name, p.price, p.description, p.is_active, p.created_at,
                           COALESCE(COUNT(s.id) FILTER (WHERE s.is_sold = 0), 0) as stock_count
                    FROM custom_products p
                    LEFT JOIN custom_product_stocks s ON p.id = s.product_id
                """
                if only_active:
                    query += " WHERE p.is_active = 1"
                query += " GROUP BY p.id ORDER BY p.id ASC"
                res = await conn.fetch(query)
                rows = [dict(r) for r in res]
        except Exception as e:
            logger.error(f"PG get_custom_products error: {e}")
    else:
        import aiosqlite
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            query = """
                SELECT p.id, p.name, p.price, p.description, p.is_active, p.created_at,
                       COALESCE(SUM(CASE WHEN s.is_sold = 0 THEN 1 ELSE 0 END), 0) as stock_count
                FROM custom_products p
                LEFT JOIN custom_product_stocks s ON p.id = s.product_id
            """
            if only_active:
                query += " WHERE p.is_active = 1"
            query += " GROUP BY p.id ORDER BY p.id ASC"
            async with db.execute(query) as cursor:
                res = await cursor.fetchall()
                rows = [dict(r) for r in res]
    return rows

async def get_custom_product(product_id: int) -> Optional[dict]:
    """Retrieve single custom product with live stock count."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                r = await conn.fetchrow("""
                    SELECT p.id, p.name, p.price, p.description, p.is_active, p.created_at,
                           COALESCE(COUNT(s.id) FILTER (WHERE s.is_sold = 0), 0) as stock_count
                    FROM custom_products p
                    LEFT JOIN custom_product_stocks s ON p.id = s.product_id
                    WHERE p.id = $1
                    GROUP BY p.id
                """, int(product_id))
                return dict(r) if r else None
        except Exception as e:
            logger.error(f"PG get_custom_product error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT p.id, p.name, p.price, p.description, p.is_active, p.created_at,
                   COALESCE(SUM(CASE WHEN s.is_sold = 0 THEN 1 ELSE 0 END), 0) as stock_count
            FROM custom_products p
            LEFT JOIN custom_product_stocks s ON p.id = s.product_id
            WHERE p.id = ?
            GROUP BY p.id
        """, (int(product_id),)) as cursor:
            r = await cursor.fetchone()
            return dict(r) if r else None

async def delete_custom_product(product_id: int) -> bool:
    """Delete or deactivate a custom product."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM custom_products WHERE id = $1", int(product_id))
                await conn.execute("DELETE FROM custom_product_stocks WHERE product_id = $1 AND is_sold = 0", int(product_id))
                return True
        except Exception as e:
            logger.error(f"PG delete_custom_product error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM custom_products WHERE id = ?", (int(product_id),))
        await db.execute("DELETE FROM custom_product_stocks WHERE product_id = ? AND is_sold = 0", (int(product_id),))
        await db.commit()
    return True

async def add_custom_product_stock(product_id: int, stock_lines: list[str]) -> int:
    """Add new stock items (e.g. email:pass, credentials, keys) to custom product."""
    now = datetime.utcnow().isoformat()
    clean_lines = [line.strip() for line in stock_lines if line and line.strip()]
    if not clean_lines:
        return 0

    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                for line in clean_lines:
                    await conn.execute("""
                        INSERT INTO custom_product_stocks (product_id, stock_data, is_sold, created_at)
                        VALUES ($1, $2, 0, $3)
                    """, int(product_id), line, now)
                return len(clean_lines)
        except Exception as e:
            logger.error(f"PG add_custom_product_stock error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        for line in clean_lines:
            await db.execute("""
                INSERT INTO custom_product_stocks (product_id, stock_data, is_sold, created_at)
                VALUES (?, ?, 0, ?)
            """, (int(product_id), line, now))
        await db.commit()
    return len(clean_lines)

async def get_custom_product_available_preview(product_id: int, limit: int = 10) -> list[str]:
    """View sample available stock items for Admin inspection."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT stock_data FROM custom_product_stocks
                    WHERE product_id = $1 AND is_sold = 0
                    ORDER BY id ASC LIMIT $2
                """, int(product_id), limit)
                return [r["stock_data"] for r in rows]
        except Exception as e:
            logger.error(f"PG get_custom_product_available_preview error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT stock_data FROM custom_product_stocks
            WHERE product_id = ? AND is_sold = 0
            ORDER BY id ASC LIMIT ?
        """, (int(product_id), limit)) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

async def purchase_custom_product_stock(product_id: int, user_id: int, quantity: int) -> list[str]:
    """Atomically pop and reserve unsold stock items for customer delivery."""
    now = datetime.utcnow().isoformat()
    delivered = []
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    rows = await conn.fetch("""
                        SELECT id, stock_data FROM custom_product_stocks
                        WHERE product_id = $1 AND is_sold = 0
                        ORDER BY id ASC LIMIT $2
                        FOR UPDATE
                    """, int(product_id), int(quantity))
                    if len(rows) < quantity:
                        return []
                    ids = [r["id"] for r in rows]
                    delivered = [r["stock_data"] for r in rows]
                    await conn.execute("""
                        UPDATE custom_product_stocks
                        SET is_sold = 1, sold_to_user_id = $1, sold_at = $2
                        WHERE id = ANY($3)
                    """, int(user_id), now, ids)
                    return delivered
        except Exception as e:
            logger.error(f"PG purchase_custom_product_stock error: {e}")
            return []

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT id, stock_data FROM custom_product_stocks
            WHERE product_id = ? AND is_sold = 0
            ORDER BY id ASC LIMIT ?
        """, (int(product_id), int(quantity))) as cursor:
            rows = await cursor.fetchall()
            if len(rows) < quantity:
                return []
            ids = [r["id"] for r in rows]
            delivered = [r["stock_data"] for r in rows]

        placeholders = ",".join("?" * len(ids))
        await db.execute(f"""
            UPDATE custom_product_stocks
            SET is_sold = 1, sold_to_user_id = ?, sold_at = ?
            WHERE id IN ({placeholders})
        """, [int(user_id), now] + ids)
        await db.commit()
    return delivered

async def get_all_synced_products_for_admin() -> list[dict]:
    """Retrieve all API-synced products including disabled/hidden ones for Admin control."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT supplier_product_id as id, name, sell_price, stock_count, in_stock, is_enabled
                    FROM products_synced
                    ORDER BY is_enabled DESC, supplier_product_id ASC
                """)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"PG get_all_synced_products_for_admin error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT supplier_product_id as id, name, sell_price, stock_count, in_stock, is_enabled
            FROM products_synced
            ORDER BY is_enabled DESC, supplier_product_id ASC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def toggle_synced_product_status(supplier_product_id: int) -> dict:
    """Toggle a synced product between Enabled (1 - Visible) and Disabled (0 - Hidden from Users)."""
    current_status = 1
    prod_name = f"Product #{supplier_product_id}"
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT name, is_enabled FROM products_synced WHERE supplier_product_id = $1", int(supplier_product_id))
                if row:
                    prod_name = row["name"]
                    current_status = row["is_enabled"]
                new_status = 0 if current_status == 1 else 1
                await conn.execute("UPDATE products_synced SET is_enabled = $1 WHERE supplier_product_id = $2", new_status, int(supplier_product_id))
                return {"id": supplier_product_id, "name": prod_name, "is_enabled": new_status}
        except Exception as e:
            logger.error(f"PG toggle_synced_product_status error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT name, is_enabled FROM products_synced WHERE supplier_product_id = ?", (int(supplier_product_id),)) as cursor:
            row = await cursor.fetchone()
            if row:
                prod_name = row["name"]
                current_status = row["is_enabled"]
        new_status = 0 if current_status == 1 else 1
        await db.execute("UPDATE products_synced SET is_enabled = ? WHERE supplier_product_id = ?", (new_status, int(supplier_product_id)))
        await db.commit()
    return {"id": supplier_product_id, "name": prod_name, "is_enabled": new_status}

async def add_assistant(user_id: int, username: str = None, first_name: str = None) -> bool:
    """Add a user as an Assistant / Product Manager."""
    now = datetime.utcnow().isoformat()
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO assistants (user_id, username, first_name, added_at)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT(user_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        added_at = EXCLUDED.added_at
                """, int(user_id), username, first_name, now)
                return True
        except Exception as e:
            logger.error(f"PG add_assistant error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO assistants (user_id, username, first_name, added_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                added_at = excluded.added_at
        """, (int(user_id), username, first_name, now))
        await db.commit()
    return True

async def remove_assistant(user_id: int) -> bool:
    """Remove a user from Assistant / Product Manager role."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM assistants WHERE user_id = $1", int(user_id))
                return True
        except Exception as e:
            logger.error(f"PG remove_assistant error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM assistants WHERE user_id = ?", (int(user_id),))
        await db.commit()
    return True

async def get_assistants() -> list[dict]:
    """Retrieve all active Assistants."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT a.user_id, COALESCE(a.username, u.username) as username, 
                           COALESCE(a.first_name, u.first_name) as first_name, a.added_at
                    FROM assistants a
                    LEFT JOIN users u ON a.user_id = u.user_id
                    ORDER BY a.added_at DESC
                """)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"PG get_assistants error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT a.user_id, COALESCE(a.username, u.username) as username, 
                   COALESCE(a.first_name, u.first_name) as first_name, a.added_at
            FROM assistants a
            LEFT JOIN users u ON a.user_id = u.user_id
            ORDER BY a.added_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def is_assistant_in_db(user_id: int) -> bool:
    """Check if a user is an authorized assistant in DB."""
    if USE_POSTGRES:
        try:
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                val = await conn.fetchval("SELECT 1 FROM assistants WHERE user_id = $1", int(user_id))
                return bool(val)
        except Exception as e:
            logger.error(f"PG is_assistant_in_db error: {e}")

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM assistants WHERE user_id = ?", (int(user_id),)) as cursor:
            row = await cursor.fetchone()
            return bool(row)
    return False


