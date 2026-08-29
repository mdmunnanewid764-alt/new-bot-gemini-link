import os
import aiosqlite
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "bot_data.db")

async def init_db():
    """Initialize SQLite database tables if they do not exist."""
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
        # Ensure optional columns exist for backwards compatibility
        for col, col_type in [("tx_hash", "TEXT"), ("network", "TEXT")]:
            try:
                await db.execute(f"ALTER TABLE deposits ADD COLUMN {col} {col_type}")
            except Exception:
                pass
        await db.commit()

async def register_user(user_id: int, username: str = None, first_name: str = None):
    """Save or update user info in DB."""
    now = datetime.utcnow().isoformat()
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
    """Get total count of registered users."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_user_id_by_identifier(identifier: str) -> int:
    """Resolve identifier (Telegram User ID or @username or username) to integer user_id."""
    clean = str(identifier).strip().lstrip("@")
    if clean.isdigit():
        return int(clean)
    
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
    """Retrieve list of registered users along with their live balances."""
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
    """Get all registered Telegram user IDs for broadcast."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

async def set_setting(key: str, value: str):
    """Store or update a setting key-value pair."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        await db.commit()

async def get_setting(key: str, default: str = None) -> str:
    """Retrieve a setting value by key."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default

async def record_order(user_id: int, order_id: int, product_id: int, product_name: str, quantity: int, total: float, status: str, delivered_keys: list):
    """Cache delivered order info locally."""
    now = datetime.utcnow().isoformat()
    keys_str = "\n".join(delivered_keys) if delivered_keys else ""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO orders_local (user_id, order_id, product_id, product_name, quantity, total, status, delivered_keys, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, order_id, product_id, product_name, quantity, total, status, keys_str, now))
        await db.commit()

async def get_user_orders(user_id: int, limit: int = 10) -> list[dict]:
    """Get recent orders for a given user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM orders_local WHERE user_id = ? ORDER BY id DESC LIMIT ?
        """, (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_stats() -> dict:
    """Get aggregate bot statistics."""
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
    """Set or update margin for 'default' or a specific product_id (as string)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO product_margins (product_key, margin)
            VALUES (?, ?)
            ON CONFLICT(product_key) DO UPDATE SET margin = excluded.margin
        """, (str(product_key).strip(), float(margin)))
        await db.commit()

async def get_all_margins() -> dict:
    """Retrieve dictionary of all configured margins."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT product_key, margin FROM product_margins") as cursor:
            rows = await cursor.fetchall()
            return {r[0]: float(r[1]) for r in rows}

async def get_margin_for_product(product_id: int) -> float:
    """Get profit margin for a specific product ID (returns product margin or default margin or 0.20)."""
    margins = await get_all_margins()
    p_key = str(product_id)
    if p_key in margins:
        return margins[p_key]
    return margins.get("default", 0.20)

async def get_user_balance(user_id: int) -> float:
    """Get user's current bot account deposit balance."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM user_balances WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return float(row[0]) if row else 0.0

async def add_user_balance(user_id: int, amount: float) -> float:
    """Credit funds to user's bot balance."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO user_balances (user_id, balance)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance
        """, (user_id, float(amount)))
        await db.commit()
    return await get_user_balance(user_id)

async def deduct_user_balance(user_id: int, amount: float) -> bool:
    """Deduct funds from user's bot balance if sufficient."""
    curr = await get_user_balance(user_id)
    if curr < amount:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE user_balances SET balance = balance - ? WHERE user_id = ?
        """, (float(amount), user_id))
        await db.commit()
    return True

async def force_deduct_user_balance(user_id: int, amount: float) -> float:
    """Deduct funds from user balance (flooring at 0.0) and return new balance."""
    curr = await get_user_balance(user_id)
    new_bal = max(0.0, curr - float(amount))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO user_balances (user_id, balance)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET balance = ?
        """, (user_id, new_bal, new_bal))
        await db.commit()
    return new_bal

async def set_user_balance(user_id: int, amount: float) -> float:
    """Set user's exact balance."""
    new_bal = max(0.0, float(amount))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO user_balances (user_id, balance)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET balance = excluded.balance
        """, (user_id, new_bal))
        await db.commit()
    return await get_user_balance(user_id)

async def get_user_info(user_id: int) -> dict:
    """Get user profile info and balance."""
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
    """Save new deposit transaction record."""
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO deposits (merchant_trade_no, user_id, amount, status, checkout_url, bep20, trc20, erc20, network, tx_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (merchant_trade_no, user_id, float(amount), status, checkout_url, bep20, trc20, erc20, network, tx_hash, now))
        await db.commit()

async def record_deposit_txhash(merchant_trade_no: str, network: str, tx_hash: str, status: str = "PENDING_VERIFICATION"):
    """Update deposit with submitted tx_hash and set pending status."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE deposits SET network = ?, tx_hash = ?, status = ? WHERE merchant_trade_no = ?
        """, (network, tx_hash, status, merchant_trade_no))
        await db.commit()

async def update_deposit_status(merchant_trade_no: str, status: str):
    """Update deposit status."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE deposits SET status = ? WHERE merchant_trade_no = ?
        """, (status, merchant_trade_no))
        await db.commit()

async def get_deposit_record(merchant_trade_no: str) -> dict:
    """Get single deposit record by merchant trade number."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM deposits WHERE merchant_trade_no = ?", (merchant_trade_no,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_pending_deposits() -> list[dict]:
    """Get all non-final deposits (status INITIAL / PENDING / PENDING_VERIFICATION)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM deposits WHERE status IN ('INITIAL', 'PENDING', 'PENDING_VERIFICATION') ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def approve_deposit(merchant_trade_no: str) -> dict:
    """Approve a deposit, update status to PAID and credit user balance. Returns record."""
    rec = await get_deposit_record(merchant_trade_no)
    if not rec:
        return None
    if rec["status"] == "PAID":
        return rec # already paid

    await update_deposit_status(merchant_trade_no, "PAID")
    new_bal = await add_user_balance(rec["user_id"], rec["amount"])
    rec["new_balance"] = new_bal
    rec["status"] = "PAID"
    return rec

async def reject_deposit(merchant_trade_no: str) -> dict:
    """Reject a deposit and update status."""
    rec = await get_deposit_record(merchant_trade_no)
    if not rec:
        return None
    await update_deposit_status(merchant_trade_no, "REJECTED")
    rec["status"] = "REJECTED"
    return rec

async def export_full_backup() -> tuple[str, str]:
    """
    Export all SQLite tables into a formatted JSON backup file
    and return (json_path, db_path).
    """
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

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        for table in ["users", "user_balances", "orders_local", "deposits", "settings", "product_margins"]:
            key_name = "orders" if table == "orders_local" else table
            async with db.execute(f"SELECT * FROM {table}") as cursor:
                rows = await cursor.fetchall()
                backup_data[key_name] = [dict(r) for r in rows]

    # Write formatted JSON files
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False)

    with open(latest_json_path, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False)

    return (latest_json_path, DB_PATH)



