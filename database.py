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

_pg_pool = None

async def get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
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
                return {
                    "total_users": u_count,
                    "total_orders": o_count,
                    "total_sales": total_sales
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
        return {
            "total_users": u_count,
            "total_orders": o_count,
            "total_sales": total_sales
        }

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

async def reject_deposit(merchant_trade_no: str) -> dict:
    rec = await get_deposit_record(merchant_trade_no)
    if not rec:
        return None
    await update_deposit_status(merchant_trade_no, "REJECTED")
    rec["status"] = "REJECTED"
    return rec

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
