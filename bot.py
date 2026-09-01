import os
import logging
import uuid
import time
from typing import Dict, Any, List
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

from datetime import datetime
import database
import catalog_sync
from shop_api import ShopAPIClient, ShopAPIError
from payment_api import PaymentAPIClient, PaymentAPIError
from binance_api import BinanceAPIClient

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8934646392:AAGNMWA0AftNgJ56SXBuxzzVOk0qHkOkgVg")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6575066703"))
NOTIFICATION_GROUP_ID = int(os.getenv("NOTIFICATION_GROUP_ID", "-1003721268860"))

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

api_client = ShopAPIClient()
payment_client = PaymentAPIClient()
binance_client = BinanceAPIClient()

def is_admin(user_id: int) -> bool:
    return int(user_id) == int(ADMIN_ID)

async def get_notification_group_id() -> int:
    stored = await database.get_setting("notification_group_id")
    if stored:
        try:
            return int(stored)
        except ValueError:
            pass
    return NOTIFICATION_GROUP_ID

async def broadcast_group_order(bot, buyer_name: str, username: str, user_id: int, order_id: str, prod_name: str, qty: int, total_price: float):
    """Send real-time order success notification to Telegram Group without clickable username."""
    try:
        grp_id = await get_notification_group_id()
        display_name = (buyer_name or f"User {user_id}").strip()
        date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        msg = (
            "🛍️ *New Order Delivered Successfully!*\n\n"
            f"👤 *Buyer:* {display_name}\n"
            f"🆔 *User ID:* `{user_id}`\n"
            f"🧾 *Order ID:* `#{order_id}`\n"
            f"📦 *Product:* {prod_name}\n"
            f"🔢 *Quantity:* `{qty}`\n"
            f"💰 *Total Paid:* `${total_price:.2f}` USD\n"
            f"⚡ *Status:* `Completed / Instant Delivery`\n"
            f"📅 *Date:* `{date_str}`"
        )
        try:
            bot_info = await bot.get_me()
            bot_user = bot_info.username or "NexvoraGeminiShopebot"
        except Exception:
            bot_user = "NexvoraGeminiShopebot"

        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Open Bot / Buy Now 🚀", url=f"https://t.me/{bot_user}?start=group_order")]
        ])
        await bot.send_message(chat_id=grp_id, text=msg, parse_mode=ParseMode.MARKDOWN, reply_markup=btn)
    except Exception as e:
        logger.warning(f"Could not send order notification to group: {e}")

async def broadcast_group_deposit(bot, user_name: str, username: str, user_id: int, amount: float, method: str, ref_id: str):
    """Send real-time deposit success notification to Telegram Group without clickable username."""
    try:
        grp_id = await get_notification_group_id()
        display_name = (user_name or f"User {user_id}").strip()
        date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        msg = (
            "💰 *Deposit Confirmed & Credited!*\n\n"
            f"👤 *User:* {display_name}\n"
            f"🆔 *User ID:* `{user_id}`\n"
            f"💵 *Amount Credited:* `+${amount:.2f}` USD\n"
            f"🌐 *Payment Method:* `{method}`\n"
            f"🆔 *Ref / Trade No:* `{ref_id}`\n"
            f"⚡ *Status:* `Approved & Verified`\n"
            f"📅 *Date:* `{date_str}`"
        )
        try:
            bot_info = await bot.get_me()
            bot_user = bot_info.username or "NexvoraGeminiShopebot"
        except Exception:
            bot_user = "NexvoraGeminiShopebot"

        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Open Bot / Deposit 🚀", url=f"https://t.me/{bot_user}?start=group_deposit")]
        ])
        await bot.send_message(chat_id=grp_id, text=msg, parse_mode=ParseMode.MARKDOWN, reply_markup=btn)
    except Exception as e:
        logger.warning(f"Could not send deposit notification to group: {e}")

# --- KEYBOARDS & UI HELPERS ---

def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("🛒 Browse Products", callback_data="nav_products"),
            InlineKeyboardButton("💰 Deposit Funds", callback_data="nav_deposit")
        ],
        [
            InlineKeyboardButton("👤 My Account", callback_data="nav_account"),
            InlineKeyboardButton("📜 My Orders", callback_data="nav_orders")
        ],
        [InlineKeyboardButton("ℹ️ Help & Support", callback_data="nav_help")]
    ]
    if is_admin(user_id):
        buttons.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")])
    return InlineKeyboardMarkup(buttons)

# --- HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await database.register_user(user.id, user.username, user.first_name)
    balance = await database.get_user_balance(user.id)

    welcome_text = (
        f"👋 *Hello {user.first_name or 'there'}! Welcome to Digital Shop Bot.*\n\n"
        f"💳 *Your Balance:* `${balance:.2f}` USD\n\n"
        "🛍️ Browse top-grade digital products with *instant automated delivery*.\n\n"
        "Select an option from the menu below to get started:"
    )

    if update.message:
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard(user.id))
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard(user.id))

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    await database.register_user(user.id, user.username, user.first_name)
    
    data = query.data

    if data == "nav_main":
        await start_command(update, context)
    elif data == "nav_products":
        await show_products_list(query, context)
    elif data == "nav_deposit":
        await show_deposit_menu(query, context)
    elif data == "nav_account":
        await show_account_info(query, context)
    elif data == "nav_orders":
        await show_orders_history(query, context)
    elif data == "nav_help":
        await show_help(query, context)
    elif data == "nav_admin":
        if is_admin(user.id):
            await show_admin_panel(query, context)
        else:
            await query.edit_message_text("❌ Unauthorized access.", reply_markup=main_menu_keyboard(user.id))

async def show_products_list(query, context: ContextTypes.DEFAULT_TYPE):
    try:
        products = await catalog_sync.get_local_catalog()
        if not products:
            # First sync if local DB empty
            await catalog_sync.sync_catalog_now(api_client)
            products = await catalog_sync.get_local_catalog()
    except Exception as e:
        logger.error(f"Error fetching local products: {e}")
        text = "❌ Failed to fetch products. Please try again later."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="nav_main")]])
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    if not products:
        text = "📦 *Product Catalog*\n\nNo products are currently in stock or available."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="nav_main")]])
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        return

    text = "🛒 *Available Products*\n\nSelect a product to view details and purchase:"
    buttons = []
    for p in products:
        p_id = p.get("id") or p.get("product_id")
        name = p.get("name", "Product")
        price = p.get("sell_price", 0.0)
        stock = p.get("stock_count")
        stock_str = f"{stock} in stock" if stock is not None else "In Stock"
        button_text = f"{name} - ${price:.2f} ({stock_str})"
        buttons.append([InlineKeyboardButton(button_text, callback_data=f"prod_{p_id}")])

    buttons.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="nav_products"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="nav_main")
    ])
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_product_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prod_id = int(query.data.split("_")[1])

    try:
        p = await catalog_sync.get_local_product(prod_id)
        if not p:
            await query.edit_message_text("⚠️ Product not found or out of stock.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav_products")]]))
            return

        name = p.get("name", "Digital Product")
        price = float(p.get("sell_price", 0.0))
        margin = float(p.get("margin", 0.20))
        stock = p.get("stock_count")
        stock_str = f"{stock} available" if stock is not None else "Unlimited"

        text = (
            f"📦 *Product Details*\n\n"
            f"📌 *Name:* {name}\n"
            f"💵 *Price:* `${price:.2f}` USD\n"
            f"📊 *Stock:* {stock_str}\n"
            f"🆔 *Product ID:* `{prod_id}`\n\n"
            "⚡ *Instant automated delivery after purchase.*"
        )

        buttons = [
            [InlineKeyboardButton("🛒 Buy Now", callback_data=f"qty_{prod_id}_1")],
            [
                InlineKeyboardButton("🔙 Back to Catalog", callback_data="nav_products"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="nav_main")
            ]
        ]
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

    except Exception as e:
        logger.error(f"Error product detail: {e}")
        await query.edit_message_text("❌ Error loading product details.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav_products")]]))

async def handle_quantity_selector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    prod_id = int(parts[1])
    qty = int(parts[2])
    if qty < 1:
        qty = 1
    if qty > 20:
        qty = 20

    try:
        p = await catalog_sync.get_local_product(prod_id)
        if not p:
            await query.edit_message_text("⚠️ Product not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav_products")]]))
            return

        name = p.get("name", "Product")
        unit_price = float(p.get("sell_price", 0.0))
        total_price = unit_price * qty
        stock = p.get("stock_count")

        if stock is not None and stock > 0 and qty > stock:
            qty = stock
            total_price = unit_price * qty

        stock_str = f"{stock}" if stock is not None else "Available"

        text = (
            f"🛒 *Order Confirmation*\n\n"
            f"📦 *Product:* {name}\n"
            f"💵 *Unit Price:* `${unit_price:.2f}` USD\n"
            f"🔢 *Quantity:* `{qty}`\n"
            f"💰 *Total Amount:* `${total_price:.2f}` USD\n"
            f"📊 *Stock Available:* {stock_str}\n\n"
            "Adjust quantity below or click *Confirm & Pay* to complete purchase:"
        )

        buttons = [
            [
                InlineKeyboardButton("➖ 1", callback_data=f"qty_{prod_id}_{max(1, qty-1)}"),
                InlineKeyboardButton(f"Qty: {qty}", callback_data="noop"),
                InlineKeyboardButton("➕ 1", callback_data=f"qty_{prod_id}_{min(20, qty+1)}")
            ],
            [
                InlineKeyboardButton("5x", callback_data=f"qty_{prod_id}_5"),
                InlineKeyboardButton("10x", callback_data=f"qty_{prod_id}_10"),
                InlineKeyboardButton("20x", callback_data=f"qty_{prod_id}_20")
            ],
            [InlineKeyboardButton(f"✅ Confirm & Pay (${total_price:.2f})", callback_data=f"buy_{prod_id}_{qty}")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"prod_{prod_id}")]
        ]

        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

    except Exception as e:
        logger.error(f"Quantity selector error: {e}")
        await query.edit_message_text("❌ Failed to update quantity.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav_products")]]))

async def handle_buy_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer("Processing your purchase...")
    
    parts = query.data.split("_")
    prod_id = int(parts[1])
    qty = int(parts[2])

    p = await catalog_sync.get_local_product(prod_id)
    if not p:
        await query.edit_message_text("⚠️ Product not found or unavailable.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Catalog", callback_data="nav_products")]]))
        return

    unit_price = float(p.get("sell_price", 0.0))
    total_price = unit_price * qty
    prod_name = p.get("name", f"Product #{prod_id}")

    # Balance Check
    user_balance = await database.get_user_balance(user.id)
    if user_balance < total_price:
        missing = total_price - user_balance
        text = (
            "⚠️ *Insufficient Bot Balance*\n\n"
            f"📦 *Product:* {prod_name}\n"
            f"🔢 *Quantity:* `{qty}`\n"
            f"💰 *Total Required:* `${total_price:.2f}` USD\n"
            f"💳 *Your Balance:* `${user_balance:.2f}` USD\n"
            f"🔴 *Shortfall:* `${missing:.2f}` USD\n\n"
            "Please click **Deposit Funds** below to top up your account balance!"
        )
        buttons = [
            [InlineKeyboardButton("💰 Deposit Funds", callback_data="nav_deposit")],
            [InlineKeyboardButton("🔙 Back to Catalog", callback_data="nav_products")]
        ]
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # Deduct user balance
    deducted = await database.deduct_user_balance(user.id, total_price)
    if not deducted:
        await query.edit_message_text("❌ Balance deduction failed.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav_products")]]))
        return

    idempotency_key = f"tg-{user.id}-{prod_id}-{int(time.time())}"
    customer_label = f"@{user.username}" if user.username else f"TG:{user.id}"

    try:
        order_res = await api_client.create_order(
            product_id=prod_id,
            quantity=qty,
            idempotency_key=idempotency_key,
            customer_name=customer_label
        )

        order_data = order_res.get("order", {})
        delivered_keys = order_res.get("delivered_keys", [])
        order_id = order_data.get("id", "N/A")
        status = order_data.get("status", "delivered")

        # Save order in local DB
        await database.record_order(
            user_id=user.id,
            order_id=order_id,
            product_id=prod_id,
            product_name=prod_name,
            quantity=qty,
            total=total_price,
            status=status,
            delivered_keys=delivered_keys
        )

        # Get updated user balance
        new_balance = await database.get_user_balance(user.id)

        # Format Delivered Keys
        keys_formatted = ""
        if delivered_keys:
            keys_formatted = "\n\n🔑 *Delivered Keys / Credentials:*\n"
            for k in delivered_keys:
                keys_formatted += f"`{k}`\n"
        else:
            keys_formatted = "\n\n⚠️ No keys returned. Contact support with your order ID."

        success_text = (
            f"🎉 *Order Completed Successfully!*\n\n"
            f"🆔 *Order ID:* `{order_id}`\n"
            f"📦 *Product:* {prod_name}\n"
            f"🔢 *Quantity:* {qty}\n"
            f"💰 *Total Paid:* `${total_price:.2f}` USD\n"
            f"💳 *Remaining Balance:* `${new_balance:.2f}` USD\n"
            f"⚡ *Status:* `{status}`"
            f"{keys_formatted}\n\n"
            "💡 *Tip:* Tap on the delivered keys above to copy them instantly!"
        )

        buttons = [
            [InlineKeyboardButton("📜 View My Orders", callback_data="nav_orders")],
            [InlineKeyboardButton("🛒 Continue Shopping", callback_data="nav_products")]
        ]

        await query.edit_message_text(success_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

        # Broadcast to Notification Group (-1003721268860)
        await broadcast_group_order(
            bot=context.bot,
            buyer_name=user.first_name or "Buyer",
            username=user.username,
            user_id=user.id,
            order_id=str(order_id),
            prod_name=prod_name,
            qty=qty,
            total_price=total_price
        )

        # Notify Admin of new sale
        try:
            admin_msg = (
                f"🛍️ *New Order Notification*\n\n"
                f"👤 *Buyer:* {user.first_name} (@{user.username or 'N/A'})\n"
                f"🆔 *User ID:* `{user.id}`\n"
                f"📦 *Product:* {prod_name}\n"
                f"🔢 *Qty:* {qty} | 💰 *Total:* ${total_price:.2f}"
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

    except Exception as e:
        # Auto-refund user balance on API failure
        await database.add_user_balance(user.id, total_price)
        logger.error(f"Purchase error (refunded ${total_price:.2f}): {e}")
        
        error_msg = str(e)
        if isinstance(e, ShopAPIError):
            error_msg = e.message

        error_text = f"❌ *Purchase Failed*\n\n{error_msg}\n\n🟢 *Your balance of `${total_price:.2f}` USD has been refunded.*"
        buttons = [
            [InlineKeyboardButton("🔄 Try Again", callback_data=f"qty_{prod_id}_{qty}")],
            [InlineKeyboardButton("🔙 Back to Catalog", callback_data="nav_products")]
        ]
        await query.edit_message_text(error_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def show_account_info(query, context: ContextTypes.DEFAULT_TYPE):
    user = query.from_user
    orders = await database.get_user_orders(user.id, limit=100)
    total_orders = len(orders)
    total_spent = sum(float(o.get('total', 0.0)) for o in orders)
    balance = await database.get_user_balance(user.id)

    text = (
        f"👤 *My Account Profile*\n\n"
        f"🆔 *Telegram ID:* `{user.id}`\n"
        f"👤 *Name:* {user.first_name or 'User'}\n"
        f"💳 *Available Balance:* `${balance:.2f}` USD\n"
        f"🛍️ *Total Orders Placed:* `{total_orders}`\n"
        f"💵 *Total Spent:* `${total_spent:.2f}` USD"
    )

    buttons = [
        [
            InlineKeyboardButton("💰 Deposit Funds", callback_data="nav_deposit"),
            InlineKeyboardButton("📜 Order History", callback_data="nav_orders")
        ],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="nav_main")]
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def show_orders_history(query, context: ContextTypes.DEFAULT_TYPE):
    user = query.from_user
    local_orders = await database.get_user_orders(user.id, limit=10)

    if not local_orders:
        text = "📜 *Order History*\n\nYou haven't placed any orders yet."
        buttons = [
            [InlineKeyboardButton("🛒 Browse Shop", callback_data="nav_products")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="nav_main")]
        ]
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
        return

    text = f"📜 *Order History (Last {len(local_orders)})*\n\n"
    for o in local_orders:
        text += (
            f"🆔 *Order #{o['order_id']}*\n"
            f"📦 {o['product_name']} (x{o['quantity']})\n"
            f"💰 Total: `${o['total']:.2f}` USD | Status: `{o['status']}`\n"
        )
        if o.get("delivered_keys"):
            text += f"🔑 *Keys:* `{o['delivered_keys']}`\n"
        text += "-------------------------------\n"

    buttons = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="nav_orders")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="nav_main")]
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def show_help(query, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "ℹ️ *Help & Support*\n\n"
        "• *How to buy?*\n"
        "  1. Tap 🛒 *Browse Products*\n"
        "  2. Select your product and quantity\n"
        "  3. Click *Confirm & Pay*\n"
        "  4. Your credentials/keys are delivered instantly!\n\n"
        "• *Order Issues?*\n"
        "  Check your 📜 *My Orders* section to copy your keys anytime.\n\n"
        "• *Need Assistance?*\n"
        f"  Contact Administrator: [Admin Support](tg://user?id={ADMIN_ID})"
    )
    buttons = [[InlineKeyboardButton("🔙 Main Menu", callback_data="nav_main")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

# --- ADMIN COMMANDS & PANELS ---

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized access.")
        return
    await show_admin_panel(update, context)

async def show_admin_panel(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    user_id = update_or_query.from_user.id if hasattr(update_or_query, "from_user") else update_or_query.effective_user.id
    if not is_admin(user_id):
        if hasattr(update_or_query, "edit_message_text"):
            await update_or_query.edit_message_text("❌ Unauthorized access.", reply_markup=main_menu_keyboard(user_id))
        else:
            await update_or_query.message.reply_text("❌ Unauthorized access.")
        return

    # Clear pending admin input states
    for state_key in [
        "waiting_for_admin_setwallet",
        "waiting_for_admin_setkey",
        "waiting_for_admin_addbalance",
        "waiting_for_admin_deductbalance",
        "waiting_for_admin_setexactbalance",
        "waiting_for_admin_checkbalance",
        "waiting_for_admin_broadcast",
        "waiting_for_admin_setmargin_default",
        "waiting_for_admin_setmargin_product",
        "waiting_for_admin_setmargin",
        "waiting_for_binance_api_key",
        "waiting_for_binance_api_secret"
    ]:
        context.user_data.pop(state_key, None)

    stats = await database.get_stats()
    current_key = await api_client.get_api_key()
    key_preview = f"{current_key[:8]}...{current_key[-4:]}" if current_key and len(current_key) > 12 else (current_key or "NOT SET")
    
    b_key, b_sec = await binance_client.get_credentials()
    binance_status = "🟢 Configured" if (b_key and b_sec) else "🔴 Not Configured"

    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)
    bep20 = await database.get_setting("wallet_bep20") or "NOT SET"
    catalog_gemini_only = (await database.get_setting("catalog_gemini_only", "1") == "1")
    store_mode_label = "💎 Only Gemini Products" if catalog_gemini_only else "🌐 All Synced Products"
    total_users_bal = stats.get("total_users_balance", 0.0)
    users_with_bal = stats.get("users_with_balance", 0)

    text = (
        "⚙️ *Admin Control Dashboard*\n\n"
        f"👥 *Total Users:* `{stats['total_users']}`\n"
        f"💳 *Total User Balances:* `${total_users_bal:.2f}` USD (`{users_with_bal}` with balance)\n"
        f"🛍️ *Total Orders:* `{stats['total_orders']}`\n"
        f"💰 *Total Sales:* `${stats['total_sales']:.2f}` USD\n\n"
        f"🏪 *Store Visibility:* `{store_mode_label}`\n"
        f"💵 *Default Profit Margin:* `${default_margin:.2f}` USD\n"
        f"🔑 *Shop API Key:* `{key_preview}`\n"
        f"🟡 *Binance API:* `{binance_status}`\n"
        f"🟡 *BEP20 Wallet:* `{bep20[:12]}...{bep20[-6:]}`" if len(bep20) > 20 else f"🟡 *BEP20 Wallet:* `{bep20}`\n\n"
        "⚡ _Select an action from the interactive buttons below:_"
    )

    toggle_btn_text = "💎 Store: Gemini Only (Switch)" if catalog_gemini_only else "🌐 Store: All Products (Switch)"

    buttons = [
        [
            InlineKeyboardButton("💰 Shop Balance", callback_data="admin_balance"),
            InlineKeyboardButton("🟡 Binance Live Balance", callback_data="admin_binance_balance"),
        ],
        [
            InlineKeyboardButton("🟡 Binance Live Deposits", callback_data="admin_binance_deposits"),
            InlineKeyboardButton("🔐 Binance API Keys", callback_data="admin_binance_keys"),
        ],
        [
            InlineKeyboardButton("🔑 Shop API Key", callback_data="admin_key"),
            InlineKeyboardButton("💎 Pricing & Profit", callback_data="admin_margins"),
        ],
        [
            InlineKeyboardButton("📊 Sales Stats", callback_data="admin_stats"),
            InlineKeyboardButton(toggle_btn_text, callback_data="admin_toggle_catalog_filter"),
        ],
        [
            InlineKeyboardButton("📍 Deposit Wallets", callback_data="admin_wallets"),
            InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance"),
        ],
        [
            InlineKeyboardButton("📋 Pending Deposits", callback_data="admin_deposits"),
            InlineKeyboardButton("📜 All Deposits History", callback_data="admin_all_deposits"),
        ],
        [
            InlineKeyboardButton("👥 Deposited Users & Balances", callback_data="admin_deposited_users"),
            InlineKeyboardButton("🔄 Sync Products", callback_data="admin_sync"),
        ],
        [
            InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast"),
            InlineKeyboardButton("💾 Download Backup", callback_data="admin_backup"),
        ],
        [
            InlineKeyboardButton("🏠 Main Menu", callback_data="nav_main"),
        ],
    ]
    markup = InlineKeyboardMarkup(buttons)

    if hasattr(update_or_query, "edit_message_text"):
        await update_or_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    else:
        await update_or_query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def handle_admin_manage_balance_callback(query, context: ContextTypes.DEFAULT_TYPE):
    total_bal, users_count = await database.get_total_users_balance()
    text = (
        "💸 *User Balance Management*\n\n"
        f"💳 *Total Users Combined Balance:* `${total_bal:.2f}` USD\n"
        f"👥 *Users Holding Balance:* `{users_count}` users\n\n"
        "You can manage any user's balance by *Username* (e.g. `@username`) or *Telegram ID*.\n\n"
        "Choose an action below:"
    )
    buttons = [
        [
            InlineKeyboardButton("➕ Add Balance", callback_data="admin_addbalance"),
            InlineKeyboardButton("➖ Deduct / Remove", callback_data="admin_deductbalance"),
        ],
        [
            InlineKeyboardButton("✏️ Set Exact Balance", callback_data="admin_setexactbalance"),
            InlineKeyboardButton("🔍 Check User Info", callback_data="admin_checkbalance"),
        ],
        [
            InlineKeyboardButton("👥 Browse Users & Quick Edit", callback_data="admin_list_users"),
        ],
        [
            InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")
        ]
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_list_users_callback(query, context: ContextTypes.DEFAULT_TYPE):
    users = await database.get_all_users_with_balances(limit=15)
    if not users:
        await query.edit_message_text(
            "👥 *No registered users found.*",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Balance Manager", callback_data="admin_manage_balance")]])
        )
        return

    text = "👥 *Registered Users List (Tap to Quick-Manage)*\n\n"
    buttons = []
    for u in users:
        u_name = f"@{u['username']}" if u.get("username") else (u.get("first_name") or f"User {u['user_id']}")
        bal = float(u.get("balance", 0.0))
        btn_label = f"{u_name} (${bal:.2f})"
        buttons.append([InlineKeyboardButton(btn_label, callback_data=f"admin_usr_{u['user_id']}")])

    buttons.append([InlineKeyboardButton("🔙 Balance Manager", callback_data="admin_manage_balance")])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_user_detail_callback(query, context: ContextTypes.DEFAULT_TYPE, target_uid: int):
    u_info = await database.get_user_info(target_uid)
    bal = float(u_info.get("balance", 0.0))
    orders = await database.get_user_orders(target_uid, limit=5)
    u_name = f"@{u_info['username']}" if u_info.get("username") else "N/A"

    text = (
        f"👤 *User Profile & Quick Balance Control*\n\n"
        f"🆔 *User ID:* `{target_uid}`\n"
        f"👤 *Name:* {u_info.get('first_name') or 'N/A'}\n"
        f"🌐 *Username:* {u_name}\n"
        f"💳 *Current Balance:* `${bal:.2f}` USD\n"
        f"🛍️ *Total Orders:* `{len(orders)}`\n\n"
        "⚡ _Use the 1-Tap Quick Action buttons below:_"
    )

    buttons = [
        [
            InlineKeyboardButton("➕ Add $1", callback_data=f"admin_uadd_{target_uid}_1"),
            InlineKeyboardButton("➕ Add $5", callback_data=f"admin_uadd_{target_uid}_5"),
            InlineKeyboardButton("➕ Add $10", callback_data=f"admin_uadd_{target_uid}_10"),
        ],
        [
            InlineKeyboardButton("➖ Deduct $1", callback_data=f"admin_uded_{target_uid}_1"),
            InlineKeyboardButton("➖ Deduct $5", callback_data=f"admin_uded_{target_uid}_5"),
            InlineKeyboardButton("➖ Deduct $10", callback_data=f"admin_uded_{target_uid}_10"),
        ],
        [
            InlineKeyboardButton("✏️ Set Custom Amount", callback_data=f"admin_uset_{target_uid}"),
            InlineKeyboardButton("👥 User List", callback_data="admin_list_users"),
        ],
        [
            InlineKeyboardButton("🔙 Balance Manager", callback_data="admin_manage_balance")
        ]
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_backup_callback(query, context: ContextTypes.DEFAULT_TYPE):
    await query.answer("Generating backup files...")
    try:
        json_path, db_path = await database.export_full_backup()
        user_id = query.from_user.id

        await query.message.reply_text("📦 *Exporting Database & JSON Backup Files...*", parse_mode=ParseMode.MARKDOWN)

        # Send SQLite Database file
        if os.path.exists(db_path):
            with open(db_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=f,
                    filename="bot_data.db",
                    caption="💾 *SQLite Database File (Complete Data)*\n_Store this in the bot root folder to restore everything._",
                    parse_mode=ParseMode.MARKDOWN
                )

        # Send JSON Backup file
        if os.path.exists(json_path):
            with open(json_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=f,
                    filename="bot_backup_latest.json",
                    caption="📋 *JSON Export Backup File*\n_Human-readable export of all users, balances, orders, and deposits._",
                    parse_mode=ParseMode.MARKDOWN
                )

        await query.message.reply_text(
            "✅ *Backup Files Sent Successfully!*\n\nAll your data is permanently saved on your local disk in `bot_data.db` and `backups/` folder.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
        )
    except Exception as e:
        logger.error(f"Error exporting backup: {e}")
        await query.message.reply_text(f"❌ Error generating backup: `{e}`")

async def handle_admin_binance_balance_callback(query, context: ContextTypes.DEFAULT_TYPE):
    await query.answer("Fetching live Binance balance...")
    res = await binance_client.get_live_balances()

    if not res.get("success"):
        err_msg = res.get("error", "Unknown error")
        text = (
            "🟡 *Binance Account Balance*\n\n"
            f"❌ *Could not fetch balance:*\n`{err_msg}`\n\n"
            "Please configure your Binance API Key and Secret Key below:"
        )
        buttons = [
            [InlineKeyboardButton("🔐 Setup Binance Keys", callback_data="admin_binance_keys")],
            [InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")]
        ]
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
        return

    spot_usdt = res.get("total_usdt_spot", 0.0)
    funding_usdt = res.get("total_usdt_funding", 0.0)
    total_usdt = res.get("total_usdt_all", 0.0)
    spot_assets = res.get("spot_assets", [])
    funding_assets = res.get("funding_assets", [])

    text = (
        "🟡 *Binance Account Live Balances*\n\n"
        f"💵 *Total Estimated Balance:* `${total_usdt:.2f}` USD\n"
        f"• *Spot Wallet USDT:* `${spot_usdt:.2f}`\n"
        f"• *Funding Wallet USDT:* `${funding_usdt:.2f}`\n\n"
    )

    if spot_assets:
        text += "*📊 Spot Wallet Non-Zero Assets:*\n"
        for a in spot_assets[:8]:
            text += f"• *{a['asset']}:* `{a['total']:.4f}` (Free: `{a['free']:.4f}`)\n"
        text += "\n"

    if funding_assets:
        text += "*💼 Funding Wallet Assets:*\n"
        for fa in funding_assets[:5]:
            text += f"• *{fa['asset']}:* `{fa['total']:.4f}`\n"
        text += "\n"

    text += f"🟢 *Trading Enabled:* `{res.get('can_trade')}` | *Deposits:* `{res.get('can_deposit')}`"

    buttons = [
        [
            InlineKeyboardButton("🔄 Refresh Balance", callback_data="admin_binance_balance"),
            InlineKeyboardButton("🟡 View Live Deposits", callback_data="admin_binance_deposits"),
        ],
        [
            InlineKeyboardButton("🔐 Edit API Keys", callback_data="admin_binance_keys"),
            InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")
        ]
    ]
    if hasattr(query, "edit_message_text"):
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_binance_deposits_callback(query, context: ContextTypes.DEFAULT_TYPE):
    if hasattr(query, "answer"):
        await query.answer("Fetching live Binance deposits...")
    res = await binance_client.get_live_deposit_history(limit=10)

    if not res.get("success"):
        err_msg = res.get("error", "Unknown error")
        text = (
            "🟡 *Binance Live Crypto Deposits*\n\n"
            f"❌ *Could not fetch deposits:*\n`{err_msg}`\n\n"
            "Make sure your Binance API key and Secret key are configured and have permissions enabled."
        )
        buttons = [
            [InlineKeyboardButton("🔄 Try Again", callback_data="admin_binance_deposits")],
            [InlineKeyboardButton("🔐 Binance Keys Setup", callback_data="admin_binance_keys")],
            [InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")]
        ]
        if hasattr(query, "edit_message_text"):
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
        return

    deposits = res.get("deposits", [])
    text = (
        f"🟡 *Binance Live Deposits (Last {len(deposits)})*\n\n"
        "⚡ _Live crypto deposits directly fetched from your Binance account:_\n\n"
    )

    status_labels = {
        0: "⏳ Pending",
        1: "🟢 Success",
        6: "⏳ Credited / Confirming",
        7: "🔴 Rejected"
    }

    buttons = []
    for d in deposits:
        coin = d.get("coin", "USDT")
        amt = float(d.get("amount", 0.0))
        net = d.get("network", "CRYPTO")
        st_code = d.get("status", 1)
        st_text = status_labels.get(st_code, f"⚪ Status {st_code}")
        tx = d.get("txId", "")
        tx_short = f"`{tx[:8]}...{tx[-6:]}`" if len(tx) > 16 else f"`{tx}`"
        addr = d.get("address", "")
        addr_short = f"`{addr[:8]}...{addr[-6:]}`" if len(addr) > 16 else f"`{addr}`"

        time_ms = d.get("insertTime") or d.get("completeTime") or 0
        if time_ms:
            time_str = datetime.utcfromtimestamp(time_ms / 1000).strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            time_str = "N/A"

        transfer_type = " (Internal)" if d.get("transferType") == 1 else ""

        text += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💵 *+{amt:.4f} {coin}* ({net}){transfer_type} | {st_text}\n"
            f"🔗 TxID: {tx_short}\n"
            f"📍 Addr: {addr_short}\n"
            f"🕒 Time: `{time_str}`\n"
        )

        if len(tx) > 20 and all(c in "0123456789abcdefABCDEFxX" for c in tx):
            exp_url = get_explorer_url(net, tx)
            buttons.append([InlineKeyboardButton(f"🔍 Explorer: +{amt:.2f} {coin} ({net})", url=exp_url)])

    if not deposits:
        text += "_No recent deposit history found on Binance._\n"
    else:
        text += "━━━━━━━━━━━━━━━━━━━\n"

    buttons.append([
        InlineKeyboardButton("🔄 Refresh Deposits", callback_data="admin_binance_deposits"),
        InlineKeyboardButton("🟡 Live Balances", callback_data="admin_binance_balance"),
    ])
    buttons.append([
        InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")
    ])

    if hasattr(query, "edit_message_text"):
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_binance_keys_callback(query, context: ContextTypes.DEFAULT_TYPE):
    b_key, b_sec = await binance_client.get_credentials()
    key_preview = f"{b_key[:8]}...{b_key[-4:]}" if b_key and len(b_key) > 12 else (b_key or "NOT SET")
    sec_preview = f"{b_sec[:6]}...{b_sec[-4:]}" if b_sec and len(b_sec) > 10 else ("CONFIGURED" if b_sec else "NOT SET")

    text = (
        "🔐 *Binance API Key Configuration*\n\n"
        f"🔑 *API Key:* `{key_preview}`\n"
        f"🔒 *API Secret:* `{sec_preview}`\n\n"
        "Tap a button below to update your keys or test live connection:"
    )

    buttons = [
        [
            InlineKeyboardButton("✏️ Set API Key", callback_data="admin_set_binance_key"),
            InlineKeyboardButton("✏️ Set Secret Key", callback_data="admin_set_binance_secret"),
        ],
        [
            InlineKeyboardButton("⚡ Test Connection & Live Balance", callback_data="admin_binance_balance"),
        ],
        [
            InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")
        ]
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_balance_callback(query, context: ContextTypes.DEFAULT_TYPE):
    try:
        me = await api_client.get_me()
        bal = me.get("deposit_balance", 0.0)
        tg_id = me.get("telegram_id", "N/A")
        shop_enabled = "🟢 Active" if me.get("shop_enabled") else "🔴 Disabled"
        key_enabled = "🟢 Active" if me.get("api_key_enabled") else "🔴 Disabled"
        text = (
            f"💰 *Supplier Account Balance*\n\n"
            f"💳 *Deposit Balance:* `${bal:.2f}` USD\n"
            f"🆔 *Supplier Telegram ID:* `{tg_id}`\n"
            f"🏪 *Shop Status:* {shop_enabled}\n"
            f"🔑 *API Key Status:* {key_enabled}"
        )
    except Exception as e:
        text = f"❌ *Error checking supplier balance:*\n`{e}`"

    buttons = [
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="admin_balance"),
            InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")
        ]
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_stats_callback(query, context: ContextTypes.DEFAULT_TYPE):
    if hasattr(query, "answer"):
        await query.answer()
    stats = await database.get_stats()
    total_users_bal = stats.get("total_users_balance", 0.0)
    users_with_bal = stats.get("users_with_balance", 0)
    total_deposited = stats.get("total_deposited", 0.0)

    text = (
        "📊 *Bot Sales & Performance Statistics*\n\n"
        f"👥 *Total Registered Users:* `{stats['total_users']}`\n"
        f"💳 *Total User Balances:* `${total_users_bal:.2f}` USD (`{users_with_bal}` users with balance)\n"
        f"📥 *Total Paid Deposits:* `${total_deposited:.2f}` USD\n"
        f"📦 *Total Orders Processed:* `{stats['total_orders']}`\n"
        f"💵 *Total Sales Revenue:* `${stats['total_sales']:.2f}` USD"
    )
    buttons = [
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats"),
            InlineKeyboardButton("👥 Deposited Users", callback_data="admin_deposited_users")
        ],
        [
            InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")
        ]
    ]
    if hasattr(query, "edit_message_text"):
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_wallets_callback(query, context: ContextTypes.DEFAULT_TYPE):
    bep20 = await database.get_setting("wallet_bep20") or "NOT SET"
    trc20 = await database.get_setting("wallet_trc20") or "NOT SET"
    erc20 = await database.get_setting("wallet_erc20") or "NOT SET"

    text = (
        "📍 *Deposit Wallet Addresses*\n\n"
        f"🟡 *BEP20 (BSC):*\n`{bep20}`\n\n"
        f"🔴 *TRC20 (TRON):*\n`{trc20}`\n\n"
        f"🔵 *ERC20 (ETH):*\n`{erc20}`\n\n"
        "Tap a button below to edit a wallet address:"
    )
    buttons = [
        [
            InlineKeyboardButton("🟡 Edit BEP20", callback_data="admin_setwallet_BEP20"),
            InlineKeyboardButton("🔴 Edit TRC20", callback_data="admin_setwallet_TRC20"),
        ],
        [
            InlineKeyboardButton("🔵 Edit ERC20", callback_data="admin_setwallet_ERC20"),
            InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin"),
        ]
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_setwallet_callback(query, context: ContextTypes.DEFAULT_TYPE, network: str):
    label = NETWORK_LABELS.get(network, network)
    current = await database.get_setting(f"wallet_{network.lower()}") or "NOT SET"

    context.user_data["admin_setwallet_network"] = network
    context.user_data["waiting_for_admin_setwallet"] = True

    await query.edit_message_text(
        f"📍 *Edit {label} Wallet*\n\n"
        f"Current: `{current}`\n\n"
        f"Send the new wallet address in your next message:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_wallets")]])
    )

async def handle_admin_margins_callback(query, context: ContextTypes.DEFAULT_TYPE):
    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)
    all_prods = await catalog_sync.get_local_catalog(filter_gemini=False)

    text = (
        "💎 *Product Pricing & Profit Margins Manager*\n\n"
        f"🌐 *Global Default Profit Margin:* `+${default_margin:.2f}` USD\n\n"
        "👇 *Tap any product below to set its profit margin or custom selling price:*\n\n"
    )

    buttons = []
    if all_prods:
        for p in all_prods:
            p_id = p["id"]
            name = p["name"]
            base_p = p.get("supplier_price", 0.0)
            margin = p.get("margin", default_margin)
            sell_p = p.get("sell_price", base_p + margin)
            is_custom = str(p_id) in margins
            custom_badge = "⭐ Custom" if is_custom else "🌐 Default"
            
            text += (
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📦 *{name}* (ID: `{p_id}`)\n"
                f"  • 🏢 Base Price: `${base_p:.2f}` | 🏷️ Selling: *${sell_p:.2f}* USD\n"
                f"  • 💵 Profit: *+${margin:.2f}* USD ({custom_badge})\n"
            )
            
            name_btn = name[:20] + "..." if len(name) > 23 else name
            buttons.append([
                InlineKeyboardButton(
                    f"✏️ {name_btn} (+${margin:.2f} ➔ ${sell_p:.2f})",
                    callback_data=f"admin_editprodmargin_{p_id}"
                )
            ])
        text += "━━━━━━━━━━━━━━━━━━━\n"
    else:
        text += "_No products found in catalog. Tap Sync Products below._\n\n"

    catalog_gemini_only = (await database.get_setting("catalog_gemini_only", "1") == "1")
    toggle_label = "💎 Store: Gemini Only (Switch)" if catalog_gemini_only else "🌐 Store: All Products (Switch)"

    buttons.append([
        InlineKeyboardButton("🌐 Set Global Default Margin", callback_data="admin_setmargin_default"),
    ])
    buttons.append([
        InlineKeyboardButton(toggle_label, callback_data="admin_toggle_catalog_filter"),
        InlineKeyboardButton("🔄 Sync Prices & Stock", callback_data="admin_sync_margins"),
    ])
    buttons.append([
        InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin"),
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_edit_product_margin_callback(query, context: ContextTypes.DEFAULT_TYPE, prod_id: int):
    p = await catalog_sync.get_local_product(prod_id)
    if not p:
        await query.answer("Product not found!", show_alert=True)
        await handle_admin_margins_callback(query, context)
        return

    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)
    is_custom = str(prod_id) in margins
    margin_type = "⭐ Custom Profit Margin" if is_custom else "🌐 Global Default Margin"
    
    base_p = float(p.get("supplier_price", 0.0))
    margin = float(p.get("margin", default_margin))
    sell_p = float(p.get("sell_price", base_p + margin))
    stock = p.get("stock_count", "Unlimited")
    if stock is None:
        stock = "Unlimited"

    text = (
        f"📦 *Product Profit & Pricing Setup*\n\n"
        f"📌 *Product Name:* {p['name']}\n"
        f"🆔 *Product ID:* `{prod_id}`\n"
        f"📊 *In Stock:* `{stock}`\n\n"
        f"🏢 *Supplier Base Price:* `${base_p:.2f}` USD\n"
        f"💵 *Your Current Profit:* `+${margin:.2f}` USD ({margin_type})\n"
        f"🏷️ *Final User Selling Price:* `${sell_p:.2f}` USD\n\n"
        "⚡ Choose a preset profit margin below or enter custom values:"
    )

    buttons = [
        [
            InlineKeyboardButton("+$0.10", callback_data=f"admin_setpmar_{prod_id}_0.10"),
            InlineKeyboardButton("+$0.25", callback_data=f"admin_setpmar_{prod_id}_0.25"),
            InlineKeyboardButton("+$0.50", callback_data=f"admin_setpmar_{prod_id}_0.50"),
            InlineKeyboardButton("+$1.00", callback_data=f"admin_setpmar_{prod_id}_1.00"),
        ],
        [
            InlineKeyboardButton("+$1.50", callback_data=f"admin_setpmar_{prod_id}_1.50"),
            InlineKeyboardButton("+$2.00", callback_data=f"admin_setpmar_{prod_id}_2.00"),
            InlineKeyboardButton("+$3.00", callback_data=f"admin_setpmar_{prod_id}_3.00"),
            InlineKeyboardButton("+$5.00", callback_data=f"admin_setpmar_{prod_id}_5.00"),
        ],
        [
            InlineKeyboardButton("✏️ Set Custom Profit ($)", callback_data=f"admin_prodcustommargin_{prod_id}"),
            InlineKeyboardButton("🏷️ Set Selling Price ($)", callback_data=f"admin_prodcustomprice_{prod_id}"),
        ],
        [
            InlineKeyboardButton("🔄 Reset to Default Margin", callback_data=f"admin_resetprodmargin_{prod_id}"),
        ],
        [
            InlineKeyboardButton("📋 All Products List", callback_data="admin_margins"),
            InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin"),
        ]
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_setmargin_val_callback(query, context: ContextTypes.DEFAULT_TYPE, val: float):
    await database.set_product_margin("default", val)
    await query.answer(f"✅ Default global margin set to ${val:.2f} USD")
    await handle_admin_margins_callback(query, context)

async def handle_admin_key_callback(query, context: ContextTypes.DEFAULT_TYPE):
    current_key = await api_client.get_api_key()
    key_preview = f"{current_key[:8]}...{current_key[-4:]}" if current_key and len(current_key) > 12 else (current_key or "NOT SET")

    text = (
        "🔑 *Shop API Key Configuration*\n\n"
        f"🔐 *Current Key:* `{key_preview}`\n\n"
        "Tap **Change API Key** to input a new key, or **Test Connection** to verify."
    )
    buttons = [
        [
            InlineKeyboardButton("✏️ Change API Key", callback_data="admin_setkey"),
            InlineKeyboardButton("⚡ Test Connection", callback_data="admin_testkey"),
        ],
        [
            InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin"),
        ]
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_key_test_callback(query, context: ContextTypes.DEFAULT_TYPE):
    await query.answer("Testing Shop API Key connection...")
    try:
        me = await api_client.get_me()
        bal = me.get("deposit_balance", 0.0)
        status_text = (
            f"✅ *API Key Verified & Connected!*\n\n"
            f"💳 *Deposit Balance:* `${bal:.2f}` USD\n"
            f"🆔 *Supplier Telegram ID:* `{me.get('telegram_id', 'N/A')}`\n"
            f"🟢 *Shop Enabled:* `{me.get('shop_enabled')}`"
        )
    except Exception as e:
        status_text = f"❌ *API Key Test Failed:*\n`{e}`"

    buttons = [
        [
            InlineKeyboardButton("✏️ Change API Key", callback_data="admin_setkey"),
            InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")
        ]
    ]
    await query.edit_message_text(status_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_sync_callback(query, context: ContextTypes.DEFAULT_TYPE):
    await query.answer("🔄 Syncing catalog with shop API...")
    try:
        await catalog_sync.sync_catalog_now(api_client)
        products = await catalog_sync.get_local_catalog()
        text = (
            f"✅ *Product Catalog Synchronized!*\n\n"
            f"📦 *{len(products)} products* are now available in your bot store."
        )
    except Exception as e:
        text = f"❌ *Sync Failed:* `{e}`"

    buttons = [
        [
            InlineKeyboardButton("🔄 Sync Again", callback_data="admin_sync"),
            InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")
        ]
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

def get_explorer_url(network: str, tx_hash: str) -> str:
    tx = (tx_hash or "").strip()
    net = (network or "").upper()
    if net == "BEP20":
        return f"https://bscscan.com/tx/{tx}"
    elif net == "TRC20":
        return f"https://tronscan.org/#/transaction/{tx}"
    elif net == "ERC20":
        return f"https://etherscan.io/tx/{tx}"
    return f"https://bscscan.com/tx/{tx}"

async def handle_admin_deposits_callback(query, context: ContextTypes.DEFAULT_TYPE):
    pending = await database.get_pending_deposits()
    text = f"📋 *Pending Crypto Deposits ({len(pending)})*\n\n"
    buttons = []
    for d in pending[:8]:
        t_no = d['merchant_trade_no']
        amt = d['amount']
        net = d.get('network') or "BEP20"
        tx = d.get('tx_hash') or "Pending TxHash"
        tx_short = f"{tx[:10]}...{tx[-6:]}" if len(tx) > 16 else tx

        text += (
            f"🆔 `{t_no[-15:]}` | 👤 `{d['user_id']}`\n"
            f"💵 *${amt:.2f}* USDT ({net}) | ⏳ `{d['status']}`\n"
            f"🔗 TxHash: `{tx_short}`\n\n"
        )
        row = [
            InlineKeyboardButton(f"✅ Approve (${amt:.2f})", callback_data=f"dep_appr_{t_no}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"dep_rej_{t_no}"),
        ]
        if d.get('tx_hash'):
            exp_url = get_explorer_url(net, d['tx_hash'])
            row.append(InlineKeyboardButton("🔍 Explorer", url=exp_url))
        buttons.append(row)

    if not pending:
        text += "_No pending deposit orders._"

    buttons.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="admin_deposits"),
        InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_all_deposits_callback(query, context: ContextTypes.DEFAULT_TYPE, status_filter: str = None):
    deposits = await database.get_all_deposits(limit=12, status=status_filter)
    filter_label = status_filter.upper() if status_filter else "ALL"
    text = f"📜 *Deposits History ({filter_label}) — Total: {len(deposits)}*\n\n"

    status_emojis = {
        "PAID": "🟢 PAID",
        "PENDING": "⏳ PENDING",
        "PENDING_VERIFICATION": "⏳ PENDING",
        "INITIAL": "⚪ INITIAL",
        "REJECTED": "🔴 REJECTED"
    }

    buttons = []
    for d in deposits:
        t_no = d['merchant_trade_no']
        amt = d['amount']
        net = d.get('network') or "CRYPTO"
        st = d.get('status', 'INITIAL').upper()
        st_badge = status_emojis.get(st, f"⚪ {st}")
        u_label = f"@{d['username']}" if d.get('username') else (d.get('first_name') or f"ID {d['user_id']}")
        tx = d.get('tx_hash') or ""
        tx_short = f"`{tx[:8]}...{tx[-6:]}`" if len(tx) > 14 else (f"`{tx}`" if tx else "_No TxHash_")

        created = str(d.get('created_at', ''))[:16].replace("T", " ")
        text += (
            f"👤 {u_label} (`{d['user_id']}`)\n"
            f"💵 *${amt:.2f}* USDT ({net}) | {st_badge}\n"
            f"🆔 `{t_no}`\n"
            f"🔗 Tx: {tx_short} | 🕒 `{created}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        if st in ("PENDING", "PENDING_VERIFICATION", "INITIAL"):
            buttons.append([
                InlineKeyboardButton(f"✅ Approve (${amt:.2f})", callback_data=f"dep_appr_{t_no}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"dep_rej_{t_no}")
            ])

    if not deposits:
        text += "_No deposits found for this filter._\n\n"

    buttons.append([
        InlineKeyboardButton("🌐 All", callback_data="admin_all_deposits"),
        InlineKeyboardButton("🟢 Paid", callback_data="admin_all_deposits_paid"),
        InlineKeyboardButton("⏳ Pending", callback_data="admin_all_deposits_pending"),
        InlineKeyboardButton("🔴 Rejected", callback_data="admin_all_deposits_rejected"),
    ])
    buttons.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="admin_all_deposits"),
        InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_deposited_users_callback(query, context: ContextTypes.DEFAULT_TYPE):
    users = await database.get_deposited_users_summary()
    total_volume = sum(u.get('total_deposited_paid', 0.0) for u in users)
    text = (
        f"👥 *Deposited Users & Balances Summary*\n\n"
        f"👤 *Total Depositing Users:* `{len(users)}`\n"
        f"💰 *Total Deposited Volume (Paid):* `${total_volume:.2f}` USD\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )

    buttons = []
    for u in users[:15]:
        u_id = u['user_id']
        u_name = f"@{u['username']}" if u.get('username') else (u.get('first_name') or f"User {u_id}")
        paid_sum = float(u.get('total_deposited_paid', 0.0))
        curr_bal = float(u.get('live_balance', 0.0))
        dep_count = u.get('total_deposits_count', 0)

        text += (
            f"👤 *{u_name}* (`{u_id}`)\n"
            f"💵 Total Paid: `${paid_sum:.2f}` ({dep_count} deposits)\n"
            f"💳 Current Balance: *${curr_bal:.2f}* USD\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        buttons.append([
            InlineKeyboardButton(f"⚙️ Manage {u_name} (${curr_bal:.2f})", callback_data=f"admin_usr_{u_id}")
        ])

    if not users:
        text += "_No user has deposited yet._"

    buttons.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="admin_deposited_users"),
        InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.edit_message_text("❌ Unauthorized access.")
        return

    data = query.data

    if data == "admin_panel":
        await show_admin_panel(query, context)
    elif data == "admin_deposits":
        await handle_admin_deposits_callback(query, context)
    elif data == "admin_all_deposits":
        await handle_admin_all_deposits_callback(query, context)
    elif data == "admin_all_deposits_paid":
        await handle_admin_all_deposits_callback(query, context, status_filter="PAID")
    elif data == "admin_all_deposits_pending":
        await handle_admin_all_deposits_callback(query, context, status_filter="PENDING_VERIFICATION")
    elif data == "admin_all_deposits_rejected":
        await handle_admin_all_deposits_callback(query, context, status_filter="REJECTED")
    elif data == "admin_deposited_users":
        await handle_admin_deposited_users_callback(query, context)
    elif data == "admin_balance":
        await handle_admin_balance_callback(query, context)
    elif data == "admin_binance_deposits":
        await handle_admin_binance_deposits_callback(query, context)
    elif data == "admin_binance_balance":
        await handle_admin_binance_balance_callback(query, context)
    elif data == "admin_binance_keys":
        await handle_admin_binance_keys_callback(query, context)
    elif data == "admin_stats":
        await handle_admin_stats_callback(query, context)
    elif data == "admin_wallets":
        await handle_admin_wallets_callback(query, context)
    elif data.startswith("admin_setwallet_"):
        net = data.replace("admin_setwallet_", "")
        await handle_admin_setwallet_callback(query, context, net)
    elif data == "admin_margins":
        await handle_admin_margins_callback(query, context)
    elif data == "admin_toggle_catalog_filter":
        current = await database.get_setting("catalog_gemini_only", "1")
        new_val = "0" if current == "1" else "1"
        await database.set_setting("catalog_gemini_only", new_val)
        mode_text = "💎 Store Mode: Only Gemini Products" if new_val == "1" else "🌐 Store Mode: All Products Visible"
        await query.answer(f"✅ Switched: {mode_text}", show_alert=True)
        await show_admin_panel(query, context)
    elif data == "admin_sync_margins":
        await catalog_sync.sync_catalog_now(api_client)
        await query.answer("✅ Prices and stock synchronized with Shop API!", show_alert=True)
        await handle_admin_margins_callback(query, context)
    elif data.startswith("admin_editprodmargin_"):
        prod_id = int(data.replace("admin_editprodmargin_", ""))
        await handle_admin_edit_product_margin_callback(query, context, prod_id)
    elif data.startswith("admin_setpmar_"):
        parts = data.split("_")
        p_id = int(parts[2])
        val = float(parts[3])
        await database.set_product_margin(str(p_id), val)
        await query.answer(f"✅ Margin set to +${val:.2f} USD")
        await handle_admin_edit_product_margin_callback(query, context, p_id)
    elif data.startswith("admin_resetprodmargin_"):
        p_id = int(data.replace("admin_resetprodmargin_", ""))
        await database.delete_product_margin(str(p_id))
        await query.answer("🔄 Reset to default global margin!", show_alert=True)
        await handle_admin_edit_product_margin_callback(query, context, p_id)
    elif data.startswith("admin_prodcustommargin_"):
        p_id = int(data.replace("admin_prodcustommargin_", ""))
        p = await catalog_sync.get_local_product(p_id)
        p_name = p['name'] if p else f"Product {p_id}"
        context.user_data["waiting_for_prod_margin_id"] = p_id
        await query.edit_message_text(
            f"✏️ *Set Custom Profit Margin*\n\n"
            f"📦 *Product:* {p_name} (ID: `{p_id}`)\n\n"
            f"Send your desired profit margin in USD to add on top of supplier price (e.g. `0.65`):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"admin_editprodmargin_{p_id}")]])
        )
    elif data.startswith("admin_prodcustomprice_"):
        p_id = int(data.replace("admin_prodcustomprice_", ""))
        p = await catalog_sync.get_local_product(p_id)
        p_name = p['name'] if p else f"Product {p_id}"
        base_p = float(p.get("supplier_price", 0.0)) if p else 0.0
        context.user_data["waiting_for_prod_sellprice_id"] = p_id
        await query.edit_message_text(
            f"🏷️ *Set Direct Selling Price*\n\n"
            f"📦 *Product:* {p_name} (ID: `{p_id}`)\n"
            f"🏢 *Supplier Base Price:* `${base_p:.2f}` USD\n\n"
            f"Send your desired **Final Selling Price** in USD (e.g. `1.80`):\n"
            f"_(The bot will automatically calculate your profit margin)_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"admin_editprodmargin_{p_id}")]])
        )
    elif data.startswith("admin_setmargin_val_"):
        val = float(data.replace("admin_setmargin_val_", ""))
        await handle_admin_setmargin_val_callback(query, context, val)
    elif data == "admin_setmargin_default":
        context.user_data["waiting_for_admin_setmargin_default"] = True
        await query.edit_message_text(
            "📐 *Set Global Default Profit Margin*\n\n"
            "This margin applies to all products that don't have an individual custom margin.\n\n"
            "Send the default profit margin in USD (e.g. `0.30`):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_margins")]])
        )
    elif data == "admin_setsellprice_gemini":
        context.user_data["waiting_for_admin_gemini_sell_price"] = True
        gemini_prods = await catalog_sync.get_gemini_products()
        base_p = gemini_prods[0].get("supplier_price", 0.40) if gemini_prods else 0.40
        await query.edit_message_text(
            f"🏷️ *Set Direct Selling Price for Gemini*\n\n"
            f"🏢 Current Supplier Base Price: `${base_p:.2f}` USD\n\n"
            f"Send your desired **Final Selling Price** in USD (e.g. `0.75`):\n"
            f"_(The bot will automatically calculate your profit margin)_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_margins")]])
        )
    elif data == "admin_setmargin_product":
        context.user_data["waiting_for_admin_setmargin_product"] = True
        await query.edit_message_text(
            "📦 *Set Custom Product Margin*\n\nSend the Product ID and Margin Amount:\n`<product_id> <amount>`\n\nExample: `9 0.50`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_margins")]])
        )
    elif data == "admin_key":
        await handle_admin_key_callback(query, context)
    elif data == "admin_setkey":
        context.user_data["waiting_for_admin_setkey"] = True
        await query.edit_message_text(
            "🔑 *Set Shop API Key*\n\nSend the new Shop API Key (sk_shop_xxx...):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_key")]])
        )
    elif data == "admin_testkey":
        await handle_admin_key_test_callback(query, context)
    elif data == "admin_manage_balance":
        await handle_admin_manage_balance_callback(query, context)
    elif data == "admin_list_users":
        await handle_admin_list_users_callback(query, context)
    elif data.startswith("admin_usr_"):
        target_uid = int(data.replace("admin_usr_", ""))
        await handle_admin_user_detail_callback(query, context, target_uid)
    elif data.startswith("admin_uadd_"):
        parts = data.split("_")
        t_uid, amt = int(parts[2]), float(parts[3])
        new_bal = await database.add_user_balance(t_uid, amt)
        u_info = await database.get_user_info(t_uid)
        await broadcast_group_deposit(
            bot=context.bot,
            user_name=u_info.get("first_name", "User"),
            username=u_info.get("username"),
            user_id=t_uid,
            amount=amt,
            method="Admin Top-Up",
            ref_id=f"ADM-{int(time.time())}"
        )
        await query.answer(f"✅ Added +${amt:.2f}! New balance: ${new_bal:.2f}", show_alert=True)
        await handle_admin_user_detail_callback(query, context, t_uid)
    elif data.startswith("admin_uded_"):
        parts = data.split("_")
        t_uid, amt = int(parts[2]), float(parts[3])
        new_bal = await database.force_deduct_user_balance(t_uid, amt)
        await query.answer(f"✅ Deducted -${amt:.2f}! New balance: ${new_bal:.2f}", show_alert=True)
        await handle_admin_user_detail_callback(query, context, t_uid)
    elif data.startswith("admin_uset_"):
        t_uid = int(data.replace("admin_uset_", ""))
        context.user_data["admin_balance_single_uid"] = t_uid
        context.user_data["waiting_for_admin_setexactbalance_single"] = True
        await query.edit_message_text(
            f"✏️ *Set Exact Balance for User `{t_uid}`*\n\nSend the new exact balance in USD (e.g. `15.00`):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"admin_usr_{t_uid}")]])
        )
    elif data == "admin_addbalance":
        context.user_data["waiting_for_admin_addbalance"] = True
        await query.edit_message_text(
            "➕ *Add User Balance*\n\n"
            "Send the **Username** or **User ID** and Amount:\n"
            "`<@username|user_id> <amount>`\n\n"
            "Example:\n"
            "• `@john_doe 10.00`\n"
            "• `6575066703 10.00`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_manage_balance")]])
        )
    elif data == "admin_deductbalance":
        context.user_data["waiting_for_admin_deductbalance"] = True
        await query.edit_message_text(
            "➖ *Deduct / Remove User Balance*\n\n"
            "Send the **Username** or **User ID** and Amount:\n"
            "`<@username|user_id> <amount>`\n\n"
            "Example:\n"
            "• `@john_doe 5.00`\n"
            "• `6575066703 5.00`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_manage_balance")]])
        )
    elif data == "admin_setexactbalance":
        context.user_data["waiting_for_admin_setexactbalance"] = True
        await query.edit_message_text(
            "✏️ *Set Exact User Balance*\n\n"
            "Send the **Username** or **User ID** and New Balance:\n"
            "`<@username|user_id> <exact_amount>`\n\n"
            "Example:\n"
            "• `@john_doe 20.00`\n"
            "• `6575066703 20.00`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_manage_balance")]])
        )
    elif data == "admin_checkbalance":
        context.user_data["waiting_for_admin_checkbalance"] = True
        await query.edit_message_text(
            "🔍 *Check User Balance & Info*\n\n"
            "Send the **Username** (e.g. `@john_doe`) or **User ID** (e.g. `6575066703`):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_manage_balance")]])
        )
    elif data == "admin_broadcast":
        context.user_data["waiting_for_admin_broadcast"] = True
        await query.edit_message_text(
            "📢 *Broadcast Message*\n\nType the message you want to send to all bot users:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="nav_admin")]])
        )
    elif data == "admin_binance_balance":
        await handle_admin_binance_balance_callback(query, context)
    elif data == "admin_binance_keys":
        await handle_admin_binance_keys_callback(query, context)
    elif data == "admin_set_binance_key":
        context.user_data["waiting_for_binance_api_key"] = True
        await query.edit_message_text(
            "🔑 *Set Binance API Key*\n\nSend your Binance API Key in your next message:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_binance_keys")]])
        )
    elif data == "admin_set_binance_secret":
        context.user_data["waiting_for_binance_api_secret"] = True
        await query.edit_message_text(
            "🔒 *Set Binance Secret Key*\n\nSend your Binance Secret Key in your next message:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_binance_keys")]])
        )
    elif data == "admin_deposits":
        await handle_admin_deposits_callback(query, context)
    elif data == "admin_backup":
        await handle_admin_backup_callback(query, context)
    elif data == "admin_sync":
        await handle_admin_sync_callback(query, context)
    elif data.startswith("dep_appr_"):
        trade_no = data.replace("dep_appr_", "")
        rec = await database.approve_deposit(trade_no)
        if rec:
            amount = rec['amount']
            uid = rec['user_id']
            new_bal = rec.get('new_balance') or (await database.get_user_balance(uid))
            await query.edit_message_text(
                f"✅ *Deposit Approved & Credited!*\n\n"
                f"🆔 *Trade No:* `{trade_no}`\n"
                f"👤 *User ID:* `{uid}`\n"
                f"💵 *Amount Credited:* `${amount:.2f}` USD\n"
                f"💳 *User New Balance:* `${new_bal:.2f}` USD",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 View Pending Deposits", callback_data="admin_deposits")],
                    [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
                ])
            )
            # Broadcast to Notification Group (-1003721268860)
            u_info = await database.get_user_info(uid)
            await broadcast_group_deposit(
                bot=context.bot,
                user_name=u_info.get("first_name", "User"),
                username=u_info.get("username"),
                user_id=uid,
                amount=amount,
                method="Crypto Deposit",
                ref_id=trade_no
            )

            try:
                user_msg = (
                    f"🎉 *Deposit Confirmed & Credited!*\n\n"
                    f"🆔 *Trade No:* `{trade_no}`\n"
                    f"💵 *Amount Added:* `${amount:.2f}` USD\n"
                    f"💳 *New Bot Balance:* `${new_bal:.2f}` USD\n\n"
                    "You can now use your balance to purchase products!"
                )
                await context.bot.send_message(
                    chat_id=uid,
                    text=user_msg,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Browse Products", callback_data="nav_products")]])
                )
            except Exception as e:
                logger.warning(f"Could not notify user of approved deposit: {e}")
        else:
            await query.edit_message_text("❌ Deposit record not found or already processed.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")]]))
    elif data.startswith("dep_rej_"):
        trade_no = data.replace("dep_rej_", "")
        rec = await database.reject_deposit(trade_no)
        if rec:
            uid = rec['user_id']
            await query.edit_message_text(
                f"❌ *Deposit Rejected!*\n\n"
                f"🆔 *Trade No:* `{trade_no}`\n"
                f"👤 *User ID:* `{uid}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 View Pending Deposits", callback_data="admin_deposits")],
                    [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
                ])
            )
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"❌ *Deposit Notice*\n\nYour deposit invoice `{trade_no}` was rejected. Please contact admin if you need assistance.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
        else:
            await query.edit_message_text("❌ Deposit record not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel", callback_data="nav_admin")]]))

# --- TEXT COMMANDS FOR ADMIN (POWER USERS) ---

async def setmargin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ *Profit Margin Management Usage:*\n\n"
            "• Set default margin for all products:\n"
            "  `/setmargin default 0.20`\n\n"
            "• Set custom margin for a specific product ID:\n"
            "  `/setmargin 9 0.50`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💵 Open Margin UI", callback_data="admin_margins")]])
        )
        return

    target_key = context.args[0].strip().lower()
    try:
        margin_val = float(context.args[1].strip())
        if margin_val < 0:
            await update.message.reply_text("❌ Margin cannot be negative.")
            return
    except ValueError:
        await update.message.reply_text("❌ Invalid margin amount. Please enter a valid number (e.g. 0.20).")
        return

    await database.set_product_margin(target_key, margin_val)
    
    if target_key == "default":
        msg = f"✅ *Default Profit Margin updated:* `${margin_val:.2f}` USD added to all products."
    else:
        msg = f"✅ *Profit Margin for Product ID `{target_key}` updated:* `${margin_val:.2f}` USD."

    buttons = [[InlineKeyboardButton("💵 Margin Settings", callback_data="admin_margins"), InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]]
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def margins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    margins = await database.get_all_margins()
    default_margin = margins.get("default", 0.20)

    text = "💰 *Configured Profit Margins*\n\n"
    text += f"🌐 *Default Margin:* `${default_margin:.2f}` USD\n\n"
    text += "*Custom Product Margins:*\n"

    custom_found = False
    for k, v in margins.items():
        if k != "default":
            custom_found = True
            text += f"• Product ID `{k}`: `${v:.2f}` USD\n"

    if not custom_found:
        text += "_No custom product margins configured._\n"

    buttons = [
        [InlineKeyboardButton("💵 Open Margin Menu", callback_data="admin_margins")],
        [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
    ]
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def setkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/setkey sk_shop_xxxxxxxx`", parse_mode=ParseMode.MARKDOWN)
        return

    new_key = context.args[0].strip()
    await database.set_setting("shop_api_key", new_key)
    
    try:
        me = await api_client.get_me()
        bal = me.get("deposit_balance", 0.0)
        await update.message.reply_text(
            f"✅ *API Key updated successfully!*\n\n"
            f"💳 *Deposit Balance:* `${bal:.2f}` USD\n"
            f"🟢 *Shop Active:* `{me.get('shop_enabled')}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
        )
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ *Key saved, but validation returned error:*\n`{e}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
        )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    try:
        me = await api_client.get_me()
        bal = me.get("deposit_balance", 0.0)
        await update.message.reply_text(
            f"💳 *Supplier Deposit Balance:* `${bal:.2f}` USD",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="admin_balance"), InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    stats = await database.get_stats()
    text = (
        "📊 *Bot Statistics*\n\n"
        f"👥 *Total Registered Users:* {stats['total_users']}\n"
        f"📦 *Total Orders Processed:* {stats['total_orders']}\n"
        f"💵 *Total Sales Revenue:* `${stats['total_sales']:.2f}` USD"
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats"), InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
    )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/broadcast Your message here...`", parse_mode=ParseMode.MARKDOWN)
        return

    broadcast_text = update.message.text.split(None, 1)[1]
    all_users = await database.get_all_user_ids()

    success_count = 0
    fail_count = 0
    for u_id in all_users:
        try:
            await context.bot.send_message(chat_id=u_id, text=broadcast_text, parse_mode=ParseMode.MARKDOWN)
            success_count += 1
        except Exception:
            fail_count += 1
    await update.message.reply_text(
        f"📢 *Broadcast Complete!*\n\n🟢 Delivered: `{success_count}`\n🔴 Failed: `{fail_count}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
    )

# --- DEPOSIT SYSTEM & PAYMENT HANDLERS ---

NETWORK_LABELS = {
    "BEP20": "BEP20 (BSC / Binance Smart Chain)",
    "TRC20": "TRC20 (TRON Network)",
    "ERC20": "ERC20 (Ethereum Network)",
}
NETWORK_DB_KEYS = {
    "BEP20": "wallet_bep20",
    "TRC20": "wallet_trc20",
    "ERC20": "wallet_erc20",
}
DEFAULT_WALLETS = {
    "BEP20": "NOT SET — use /setwallet BEP20 <address>",
    "TRC20": "NOT SET — use /setwallet TRC20 <address>",
    "ERC20": "NOT SET — use /setwallet ERC20 <address>",
}

async def get_wallet(network: str) -> str:
    key = NETWORK_DB_KEYS.get(network, "wallet_bep20")
    val = await database.get_setting(key)
    return val if val else DEFAULT_WALLETS.get(network, "NOT SET")

async def show_deposit_menu(query_or_update, context: ContextTypes.DEFAULT_TYPE):
    user = query_or_update.from_user if hasattr(query_or_update, "from_user") else query_or_update.effective_user
    balance = await database.get_user_balance(user.id)

    text = (
        "💳 *Deposit Funds*\n\n"
        f"💰 *Your Bot Balance:* `${balance:.2f}` USD\n\n"
        "Select the amount you want to deposit (USDT):"
    )

    buttons = [
        [
            InlineKeyboardButton("$5", callback_data="dep_amt_5"),
            InlineKeyboardButton("$10", callback_data="dep_amt_10"),
            InlineKeyboardButton("$25", callback_data="dep_amt_25"),
            InlineKeyboardButton("$50", callback_data="dep_amt_50"),
        ],
        [
            InlineKeyboardButton("$100", callback_data="dep_amt_100"),
            InlineKeyboardButton("✏️ Custom Amount", callback_data="dep_amt_custom"),
        ],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="nav_main")],
    ]

    if hasattr(query_or_update, "edit_message_text"):
        await query_or_update.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await query_or_update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_deposit_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "dep_amt_custom":
        context.user_data["waiting_for_custom_deposit"] = True
        await query.edit_message_text(
            "✏️ *Custom Deposit Amount*\n\n"
            "Send the amount you wish to deposit in USD (e.g. `15.50`):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="nav_deposit")]]),
        )
        return

    amt_str = data.split("_")[2]
    amount = float(amt_str)
    await show_network_selector(query, context, amount)

async def show_network_selector(query_or_update, context: ContextTypes.DEFAULT_TYPE, amount: float):
    """Step 2: After amount chosen, show network buttons."""
    text = (
        "🌐 *Select Payment Network*\n\n"
        f"💵 *Deposit Amount:* `${amount:.2f}` USDT\n\n"
        "Choose the network you will send from:"
    )
    buttons = [
        [InlineKeyboardButton("🟡 BEP20 (BSC)", callback_data=f"dep_net_BEP20_{amount}")],
        [InlineKeyboardButton("🔴 TRC20 (TRON)", callback_data=f"dep_net_TRC20_{amount}")],
        [InlineKeyboardButton("🔵 ERC20 (ETH)", callback_data=f"dep_net_ERC20_{amount}")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_deposit")],
    ]
    if hasattr(query_or_update, "edit_message_text"):
        await query_or_update.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await query_or_update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_deposit_network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 3: Show wallet address for chosen network."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    parts = query.data.split("_")
    network = parts[2]
    amount = float(parts[3])

    wallet_address = await get_wallet(network)
    trade_no = f"DEP-TG{user.id}-{int(time.time())}"

    # Save deposit record
    await database.create_deposit_record(
        merchant_trade_no=trade_no,
        user_id=user.id,
        amount=amount,
        status="INITIAL",
        checkout_url="",
        bep20=wallet_address if network == "BEP20" else "",
        trc20=wallet_address if network == "TRC20" else "",
        erc20=wallet_address if network == "ERC20" else "",
    )

    context.user_data["pending_trade_no"] = trade_no
    context.user_data["pending_network"] = network

    label = NETWORK_LABELS.get(network, network)
    text = (
        f"📥 *Deposit Invoice*\n\n"
        f"💵 *Amount:* `${amount:.2f}` USDT\n"
        f"🌐 *Network:* `{label}`\n\n"
        f"📍 *Send USDT to this address:*\n"
        f"`{wallet_address}`\n\n"
        f"🆔 *Trade No:* `{trade_no}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ After sending, tap *Submit TxHash* below."
    )
    buttons = [
        [InlineKeyboardButton("⚡ Submit TxHash", callback_data=f"dep_tx_{network}_{trade_no}")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_deposit")],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_txhash_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 4: Prompt user to paste TxHash."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 3)
    network = parts[2]
    trade_no = parts[3]

    context.user_data["txhash_network"] = network
    context.user_data["waiting_for_txhash_input"] = trade_no

    label = NETWORK_LABELS.get(network, network)
    await query.edit_message_text(
        f"⚡ *Submit TxHash / Transfer ID — {label}*\n\n"
        f"🆔 *Trade No:* `{trade_no}`\n\n"
        "📋 *Paste your TxID / TxHash below:*\n"
        "• **Blockchain TxHash** (e.g. `0x123abc...`)\n"
        "• Or **Binance Internal Transfer ID** (e.g. `406636190834`)\n\n"
        "💡 _In Binance: Go to Wallets ➔ History ➔ Withdrawal ➔ Copy the TxID._",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="nav_deposit")]]),
    )

async def handle_user_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    # Custom deposit amount
    if context.user_data.get("waiting_for_custom_deposit"):
        context.user_data["waiting_for_custom_deposit"] = False
        try:
            amount = float(text)
            if amount < 1.0:
                await update.message.reply_text("❌ Minimum deposit amount is $1.00 USD.")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Please enter a number (e.g. 15.50).")
            return

        await show_network_selector(update, context, amount)
        return

    # TxHash submission
    if context.user_data.get("waiting_for_txhash_input"):
        trade_no = context.user_data.pop("waiting_for_txhash_input")
        network = context.user_data.pop("txhash_network", "BEP20")
        tx_hash = text.strip()

        # Clean up input in case user copies Binance prefix text (e.g. "Transferencia fuera de la cadena 406636190834")
        if " " in tx_hash:
            parts = tx_hash.split()
            # If last part is the actual ID / hash
            if len(parts[-1]) >= 8:
                tx_hash = parts[-1]

        # 1. Anti-Fake Protection: Format validation (supports 64-char blockchain hash & 8-20 digit Binance Internal IDs)
        is_valid_hash = (len(tx_hash) >= 20 and all(c in "0123456789abcdefABCDEFxX" for c in tx_hash))
        is_binance_internal = (len(tx_hash) >= 8 and tx_hash.isdigit())

        if not (is_valid_hash or is_binance_internal):
            await update.message.reply_text(
                "❌ *Invalid Transaction Hash Format!*\n\n"
                "Please enter a valid blockchain **TxHash** (e.g. `0x123abc...` / `a1b2c3...`) or **Binance Internal Transfer ID** (e.g. `406636190834`).\n\n"
                "Fake or random texts are not accepted.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Back to Deposit", callback_data="nav_deposit")]])
            )
            return

        # 2. Anti-Fake Protection: Duplicate / Replay attack prevention
        is_duplicate = await database.is_txhash_used(tx_hash, current_trade_no=trade_no)
        if is_duplicate:
            await update.message.reply_text(
                "🚫 *Duplicate / Reused TxHash Detected!*\n\n"
                "This Transaction ID has already been used or approved for another deposit.\n"
                "Duplicate submissions are strictly rejected.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 New Deposit", callback_data="nav_deposit")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="nav_main")]
                ])
            )
            return

        label = NETWORK_LABELS.get(network, network)
        await database.record_deposit_txhash(trade_no, network, tx_hash, status="PENDING_VERIFICATION")
        rec = await database.get_deposit_record(trade_no)
        amount = rec["amount"] if rec else 0.0

        auto_approved = False
        try:
            res = await payment_client.submit_tx(trade_no, network, tx_hash)
            status = res.get("status", "").upper()
            if status == "PAID":
                auto_approved = True
                credit_amount = float(res.get("amount", amount))
                await database.update_deposit_status(trade_no, "PAID")
                new_bal = await database.add_user_balance(user.id, credit_amount)
                # Broadcast to Notification Group (-1003721268860)
                await broadcast_group_deposit(
                    bot=context.bot,
                    user_name=user.first_name or "User",
                    username=user.username,
                    user_id=user.id,
                    amount=credit_amount,
                    method=label,
                    ref_id=trade_no
                )
                
                # Send instant notification to Admin
                try:
                    admin_success_msg = (
                        "💰 *Deposit Auto-Verified & Credited!*\n\n"
                        f"👤 *User:* {user.first_name} (@{user.username or 'N/A'})\n"
                        f"🆔 *User ID:* `{user.id}`\n"
                        f"💵 *Amount Credited:* `+${credit_amount:.2f}` USD\n"
                        f"🌐 *Network / Method:* `{label}`\n"
                        f"🆔 *Trade No:* `{trade_no}`\n"
                        f"🔗 *TxHash / TxID:* `{tx_hash}`\n"
                        f"💳 *User New Balance:* `${new_bal:.2f}` USD\n"
                        f"📅 *Date & Time:* `{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}`"
                    )
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=admin_success_msg,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Error sending auto-deposit notification to admin: {e}")

                await update.message.reply_text(
                    f"🎉 *Deposit Auto-Verified & Credited!*\n\n"
                    f"🆔 *Trade No:* `{trade_no}`\n"
                    f"💵 *Amount Credited:* `${credit_amount:.2f}` USD\n"
                    f"💳 *New Bot Balance:* `${new_bal:.2f}` USD",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛒 Browse Shop", callback_data="nav_products")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="nav_main")]
                    ])
                )
        except Exception as e:
            logger.info(f"Automatic gateway verification deferred to admin: {e}")

        if not auto_approved:
            # User Confirmation
            await update.message.reply_text(
                f"✅ *TxHash Submitted Successfully!*\n\n"
                f"🆔 *Trade No:* `{trade_no}`\n"
                f"💵 *Amount:* `${amount:.2f}` USDT\n"
                f"🌐 *Network:* `{label}`\n"
                f"🔗 *TxHash / ID:* `{tx_hash}`\n\n"
                "⏳ *Status:* `Pending Verification`\n"
                "⚡ Your deposit will be credited as soon as it is confirmed on the blockchain / verified by admin!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Browse Shop", callback_data="nav_products")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="nav_main")]
                ])
            )

            # Notify Admin immediately with full User Info & 1-click Approval Buttons
            try:
                curr_user_bal = await database.get_user_balance(user.id)
                explorer_url = get_explorer_url(network, tx_hash)
                admin_notif = (
                    "📥 *New User Deposit Submitted — Pending Review!*\n\n"
                    f"👤 *User:* {user.first_name} (@{user.username or 'N/A'})\n"
                    f"🆔 *User ID:* `{user.id}`\n"
                    f"💵 *Deposit Amount:* `${amount:.2f}` USDT\n"
                    f"🌐 *Network:* `{label}`\n"
                    f"🆔 *Trade No:* `{trade_no}`\n"
                    f"🔗 *TxHash / Binance TxID:* `{tx_hash}`\n"
                    f"💳 *Current User Balance:* `${curr_user_bal:.2f}` USD\n"
                    f"📅 *Date & Time:* `{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}`\n\n"
                    "⚡ _Check your Binance/Wallet and tap Approve below:_"
                )
                admin_btns = [
                    [
                        InlineKeyboardButton(f"✅ Approve (+${amount:.2f})", callback_data=f"dep_appr_{trade_no}"),
                        InlineKeyboardButton("❌ Reject", callback_data=f"dep_rej_{trade_no}")
                    ]
                ]
                if len(tx_hash) > 20 and all(c in "0123456789abcdefABCDEFxX" for c in tx_hash):
                    admin_btns.append([InlineKeyboardButton("🔍 Open Explorer", url=explorer_url)])

                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=admin_notif,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(admin_btns)
                )
            except Exception as e:
                logger.error(f"Error sending admin deposit notification: {e}")
        return

    # ── Admin: Set Wallet Address ──
    if context.user_data.get("waiting_for_admin_setwallet") and is_admin(user.id):
        context.user_data["waiting_for_admin_setwallet"] = False
        network = context.user_data.pop("admin_setwallet_network", "BEP20")
        db_key = {"BEP20": "wallet_bep20", "TRC20": "wallet_trc20", "ERC20": "wallet_erc20"}.get(network, "wallet_bep20")
        await database.set_setting(db_key, text)
        label = NETWORK_LABELS.get(network, network)
        await update.message.reply_text(
            f"✅ *{label} Wallet Updated!*\n\n📍 `{text}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📍 Back to Wallets", callback_data="admin_wallets")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        return

    # ── Admin: Set Shop API Key ──
    if context.user_data.get("waiting_for_admin_setkey") and is_admin(user.id):
        context.user_data["waiting_for_admin_setkey"] = False
        await database.set_setting("shop_api_key", text)
        try:
            me = await api_client.get_me()
            bal = me.get("deposit_balance", 0.0)
            await update.message.reply_text(
                f"✅ *Shop API Key Updated & Connected!*\n\n"
                f"💳 *Deposit Balance:* `${bal:.2f}` USD\n"
                f"🟢 *Shop Enabled:* `{me.get('shop_enabled')}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
            )
        except Exception as e:
            await update.message.reply_text(
                f"⚠️ *Key saved, but validation warning:*\n`{e}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
            )
        return

    # ── Admin: Add User Balance ──
    if context.user_data.get("waiting_for_admin_addbalance") and is_admin(user.id):
        context.user_data["waiting_for_admin_addbalance"] = False
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text(
                "❌ Format: `<@username|user_id> <amount>` (e.g. `@john_doe 10.00`)",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")]])
            )
            return
        
        target_uid = await database.get_user_id_by_identifier(parts[0])
        if not target_uid:
            await update.message.reply_text(
                f"❌ User `{parts[0]}` not found in database. User must start the bot at least once.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")]])
            )
            return
        try:
            amt = float(parts[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid amount. Please enter a valid number.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")]])
            )
            return

        new_bal = await database.add_user_balance(target_uid, amt)
        u_info = await database.get_user_info(target_uid)
        u_label = f"@{u_info['username']}" if u_info.get("username") else (u_info.get("first_name") or f"ID {target_uid}")
        
        # Broadcast to Notification Group (-1003721268860)
        await broadcast_group_deposit(
            bot=context.bot,
            user_name=u_info.get("first_name", "User"),
            username=u_info.get("username"),
            user_id=target_uid,
            amount=amt,
            method="Admin Top-Up",
            ref_id=f"ADM-{int(time.time())}"
        )

        await update.message.reply_text(
            f"✅ *Balance Added Successfully!*\n\n"
            f"👤 *User:* {u_label} (`{target_uid}`)\n"
            f"💵 *Amount Added:* `+${amt:.2f}` USD\n"
            f"💳 *New User Balance:* `${new_bal:.2f}` USD",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 Manage User", callback_data=f"admin_usr_{target_uid}")],
                [InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text=f"🎁 *Admin Deposit Credited!*\n\n💵 *Amount:* `+${amt:.2f}` USD\n💳 *New Balance:* `${new_bal:.2f}` USD",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        return

    # ── Admin: Deduct User Balance ──
    if context.user_data.get("waiting_for_admin_deductbalance") and is_admin(user.id):
        context.user_data["waiting_for_admin_deductbalance"] = False
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text(
                "❌ Format: `<@username|user_id> <amount>` (e.g. `@john_doe 5.00`)",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")]])
            )
            return

        target_uid = await database.get_user_id_by_identifier(parts[0])
        if not target_uid:
            await update.message.reply_text(
                f"❌ User `{parts[0]}` not found in database.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")]])
            )
            return
        try:
            amt = float(parts[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid amount. Please enter a valid number.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")]])
            )
            return

        new_bal = await database.force_deduct_user_balance(target_uid, amt)
        u_info = await database.get_user_info(target_uid)
        u_label = f"@{u_info['username']}" if u_info.get("username") else (u_info.get("first_name") or f"ID {target_uid}")
        await update.message.reply_text(
            f"✅ *Balance Deducted Successfully!*\n\n"
            f"👤 *User:* {u_label} (`{target_uid}`)\n"
            f"➖ *Amount Deducted:* `-${amt:.2f}` USD\n"
            f"💳 *New User Balance:* `${new_bal:.2f}` USD",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 Manage User", callback_data=f"admin_usr_{target_uid}")],
                [InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text=f"⚠️ *Balance Adjustment Notification*\n\n➖ *Amount Deducted:* `-${amt:.2f}` USD\n💳 *Current Balance:* `${new_bal:.2f}` USD",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        return

    # ── Admin: Set Exact User Balance ──
    if context.user_data.get("waiting_for_admin_setexactbalance") and is_admin(user.id):
        context.user_data["waiting_for_admin_setexactbalance"] = False
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text(
                "❌ Format: `<@username|user_id> <amount>` (e.g. `@john_doe 20.00`)",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")]])
            )
            return

        target_uid = await database.get_user_id_by_identifier(parts[0])
        if not target_uid:
            await update.message.reply_text(
                f"❌ User `{parts[0]}` not found in database.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")]])
            )
            return
        try:
            amt = float(parts[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid amount. Please enter a valid number.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")]])
            )
            return

        new_bal = await database.set_user_balance(target_uid, amt)
        u_info = await database.get_user_info(target_uid)
        u_label = f"@{u_info['username']}" if u_info.get("username") else (u_info.get("first_name") or f"ID {target_uid}")
        await update.message.reply_text(
            f"✅ *Exact Balance Set Successfully!*\n\n"
            f"👤 *User:* {u_label} (`{target_uid}`)\n"
            f"💳 *Set Balance:* `${new_bal:.2f}` USD",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 Manage User", callback_data=f"admin_usr_{target_uid}")],
                [InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        return

    # ── Admin: Set Exact Balance Single User ──
    if context.user_data.get("waiting_for_admin_setexactbalance_single") and is_admin(user.id):
        context.user_data["waiting_for_admin_setexactbalance_single"] = False
        target_uid = context.user_data.pop("admin_balance_single_uid", None)
        if not target_uid:
            await update.message.reply_text("❌ Session expired. Please try again from Balance Manager.")
            return
        try:
            amt = float(text.strip())
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Please send a valid number.")
            return
        new_bal = await database.set_user_balance(target_uid, amt)
        u_info = await database.get_user_info(target_uid)
        u_label = f"@{u_info['username']}" if u_info.get("username") else (u_info.get("first_name") or f"ID {target_uid}")
        await update.message.reply_text(
            f"✅ *Exact Balance Updated!*\n\n"
            f"👤 *User:* {u_label} (`{target_uid}`)\n"
            f"💳 *New Balance:* `${new_bal:.2f}` USD",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 Back to User Control", callback_data=f"admin_usr_{target_uid}")],
                [InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        return

    # ── Admin: Check User Info & Balance ──
    if context.user_data.get("waiting_for_admin_checkbalance") and is_admin(user.id):
        context.user_data["waiting_for_admin_checkbalance"] = False
        target_uid = await database.get_user_id_by_identifier(text.strip())
        if not target_uid:
            await update.message.reply_text(
                f"❌ User `{text.strip()}` not found in database. User must start the bot at least once.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")]])
            )
            return

        u_info = await database.get_user_info(target_uid)
        orders = await database.get_user_orders(target_uid, limit=5)
        text_res = (
            f"🔍 *User Information*\n\n"
            f"🆔 *User ID:* `{target_uid}`\n"
            f"👤 *Name:* {u_info.get('first_name') or 'N/A'}\n"
            f"🌐 *Username:* @{u_info.get('username') or 'N/A'}\n"
            f"💳 *Bot Balance:* `${u_info.get('balance', 0.0):.2f}` USD\n"
            f"🛍️ *Recent Orders:* `{len(orders)}`\n"
        )
        await update.message.reply_text(
            text_res,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("👤 Quick Control Buttons", callback_data=f"admin_usr_{target_uid}")
                ],
                [
                    InlineKeyboardButton("➕ Add Balance", callback_data="admin_addbalance"),
                    InlineKeyboardButton("➖ Deduct", callback_data="admin_deductbalance")
                ],
                [InlineKeyboardButton("💸 Balance Manager", callback_data="admin_manage_balance")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        return

    # ── Admin: Broadcast ──
    if context.user_data.get("waiting_for_admin_broadcast") and is_admin(user.id):
        context.user_data["waiting_for_admin_broadcast"] = False
        all_users = await database.get_all_user_ids()
        
        # Launch broadcast in background non-blocking task
        asyncio.create_task(send_broadcast_background(context.bot, user.id, text))
        
        await update.message.reply_text(
            f"🚀 *Broadcast Launched in Background!*\n\n"
            f"👥 Sending to `{len(all_users)}` registered users.\n\n"
            "⚡ *The bot remains 100% active and will respond to /start and all users instantly!* "
            "You will receive a completion summary when it finishes.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
        )
        return

    # ── Admin: Set Direct Gemini Selling Price ──
    if context.user_data.get("waiting_for_admin_gemini_sell_price") and is_admin(user.id):
        context.user_data["waiting_for_admin_gemini_sell_price"] = False
        try:
            target_sell_price = float(text.strip())
            if target_sell_price <= 0:
                await update.message.reply_text("❌ Price must be greater than 0.")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid price. Please enter a valid number.")
            return

        gemini_prods = await catalog_sync.get_gemini_products()
        base_p = gemini_prods[0].get("supplier_price", 0.40) if gemini_prods else 0.40
        calc_margin = round(max(0.0, target_sell_price - base_p), 2)

        await database.set_product_margin("default", calc_margin)
        for gp in gemini_prods:
            await database.set_product_margin(str(gp["id"]), calc_margin)

        await update.message.reply_text(
            f"✅ *Gemini Selling Price & Profit Updated!*\n\n"
            f"🏢 *Supplier API Base Price:* `${base_p:.2f}` USD\n"
            f"💵 *Your Profit Margin:* `+${calc_margin:.2f}` USD\n"
            f"🏷️ *Final User Selling Price:* `${target_sell_price:.2f}` USD",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 View Gemini Margins", callback_data="admin_margins")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        return

    # ── Admin: Set Individual Product Custom Margin ──
    if context.user_data.get("waiting_for_prod_margin_id") and is_admin(user.id):
        prod_id = context.user_data.pop("waiting_for_prod_margin_id")
        try:
            margin_val = float(text.strip())
            if margin_val < 0:
                await update.message.reply_text("❌ Margin cannot be negative.")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid margin. Please enter a valid number (e.g. `0.50`).")
            return

        await database.set_product_margin(str(prod_id), margin_val)
        p = await catalog_sync.get_local_product(prod_id)
        p_name = p['name'] if p else f"Product {prod_id}"
        base_p = float(p.get("supplier_price", 0.0)) if p else 0.0
        final_sell_p = round(base_p + margin_val, 2)

        await update.message.reply_text(
            f"✅ *Profit Margin Saved for `{p_name}`!*\n\n"
            f"🏢 *Supplier Base Price:* `${base_p:.2f}` USD\n"
            f"💵 *Your Profit Margin:* `+${margin_val:.2f}` USD\n"
            f"🏷️ *User Selling Price:* `${final_sell_p:.2f}` USD",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Manage This Product", callback_data=f"admin_editprodmargin_{prod_id}")],
                [InlineKeyboardButton("📋 All Products List", callback_data="admin_margins")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        return

    # ── Admin: Set Individual Product Direct Selling Price ──
    if context.user_data.get("waiting_for_prod_sellprice_id") and is_admin(user.id):
        prod_id = context.user_data.pop("waiting_for_prod_sellprice_id")
        try:
            target_price = float(text.strip())
            if target_price <= 0:
                await update.message.reply_text("❌ Selling price must be greater than 0.")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid price. Please enter a valid number (e.g. `1.50`).")
            return

        p = await catalog_sync.get_local_product(prod_id)
        p_name = p['name'] if p else f"Product {prod_id}"
        base_p = float(p.get("supplier_price", 0.0)) if p else 0.0
        calc_margin = round(max(0.0, target_price - base_p), 2)
        await database.set_product_margin(str(prod_id), calc_margin)

        await update.message.reply_text(
            f"✅ *Selling Price Updated for `{p_name}`!*\n\n"
            f"🏢 *Supplier Base Price:* `${base_p:.2f}` USD\n"
            f"💵 *Calculated Profit Margin:* `+${calc_margin:.2f}` USD\n"
            f"🏷️ *Final User Selling Price:* `${target_price:.2f}` USD",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Manage This Product", callback_data=f"admin_editprodmargin_{prod_id}")],
                [InlineKeyboardButton("📋 All Products List", callback_data="admin_margins")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        return

    # ── Admin: Set Default Margin ──
    if context.user_data.get("waiting_for_admin_setmargin_default") and is_admin(user.id):
        context.user_data["waiting_for_admin_setmargin_default"] = False
        try:
            margin_val = float(text)
            if margin_val < 0:
                await update.message.reply_text("❌ Margin cannot be negative.")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid margin amount.")
            return
        await database.set_product_margin("default", margin_val)

        await update.message.reply_text(
            f"✅ *Global Default Profit Margin Updated:*\n\n"
            f"🌐 *New Default Margin:* `+${margin_val:.2f}` USD\n\n"
            "This margin is now applied to all products that do not have custom individual margins.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 All Products Pricing", callback_data="admin_margins")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        return

    # ── Admin: Set Product Margin ──
    if context.user_data.get("waiting_for_admin_setmargin_product") and is_admin(user.id):
        context.user_data["waiting_for_admin_setmargin_product"] = False
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text("❌ Format: `<product_id> <amount>` (e.g. `9 0.50`)", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            prod_key = parts[0].strip().lower()
            margin_val = float(parts[1])
            if margin_val < 0:
                await update.message.reply_text("❌ Margin cannot be negative.")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid margin value.")
            return
        await database.set_product_margin(prod_key, margin_val)
        await update.message.reply_text(
            f"✅ *Product `{prod_key}` Margin Updated:*\n`${margin_val:.2f}` USD.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💵 Back to Margins", callback_data="admin_margins")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        return

    # ── Admin: Generic Set Margin ──
    if context.user_data.get("waiting_for_admin_setmargin") and is_admin(user.id):
        context.user_data["waiting_for_admin_setmargin"] = False
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text("❌ Format: `default 0.30` or `<product_id> 0.50`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            margin_val = float(parts[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid margin value.")
            return
        target_key = parts[0].strip().lower()
        await database.set_product_margin(target_key, margin_val)
        if target_key == "default":
            msg = f"✅ *Default Margin updated:* `${margin_val:.2f}` USD added to all products."
        else:
            msg = f"✅ *Product `{target_key}` Margin updated:* `${margin_val:.2f}` USD."
        await update.message.reply_text(
            msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💵 Back to Margins", callback_data="admin_margins")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        return

    # ── Admin: Set Binance API Key ──
    if context.user_data.get("waiting_for_binance_api_key") and is_admin(user.id):
        context.user_data["waiting_for_binance_api_key"] = False
        await database.set_setting("binance_api_key", text)
        await update.message.reply_text(
            f"✅ *Binance API Key Saved!*\n\n`{text[:8]}...{text[-4:]}`\n\nTap **Set Secret Key** below to set your API Secret:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔒 Set Secret Key", callback_data="admin_set_binance_secret")],
                [InlineKeyboardButton("🔐 Binance Settings", callback_data="admin_binance_keys")],
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
            ])
        )
        return

    # ── Admin: Set Binance Secret Key ──
    if context.user_data.get("waiting_for_binance_api_secret") and is_admin(user.id):
        context.user_data["waiting_for_binance_api_secret"] = False
        await database.set_setting("binance_api_secret", text)
        await update.message.reply_text(
            "✅ *Binance Secret Key Saved!*\n\nTesting live connection now...",
            parse_mode=ParseMode.MARKDOWN
        )
        # Test connection
        res = await binance_client.get_live_balances()
        if res.get("success"):
            total_usdt = res.get("total_usdt_all", 0.0)
            await update.message.reply_text(
                f"🎉 *Binance API Connected Successfully!*\n\n"
                f"💰 *Live Total Balance:* `${total_usdt:.2f}` USD\n"
                f"• Spot Wallet: `${res.get('total_usdt_spot', 0.0):.2f}` USDT\n"
                f"• Funding Wallet: `${res.get('total_usdt_funding', 0.0):.2f}` USDT\n\n"
                "Auto-Payment and live balance monitoring are now fully active!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🟡 View Full Balance", callback_data="admin_binance_balance")],
                    [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
                ])
            )
        else:
            await update.message.reply_text(
                f"⚠️ *Keys saved, but validation warning:*\n`{res.get('error')}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔐 Binance Settings", callback_data="admin_binance_keys")],
                    [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
                ])
            )
        return

# --- ADDITIONAL COMMANDS ---

async def setbinancekey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/setbinancekey bg_live_xxxxxx`", parse_mode=ParseMode.MARKDOWN)
        return

    new_key = context.args[0].strip()
    await database.set_setting("binance_pay_api_key", new_key)
    await update.message.reply_text(f"✅ *Binance Pay Merchant API Key updated:* `{new_key[:8]}...`", parse_mode=ParseMode.MARKDOWN)

async def setbinanceproxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    if not context.args:
        curr_proxy = await database.get_setting("binance_proxy", "None")
        await update.message.reply_text(
            f"ℹ️ *Current Binance Proxy:* `{curr_proxy}`\n\n"
            "Usage:\n"
            "• Set proxy: `/setbinanceproxy http://user:pass@host:port`\n"
            "• Remove proxy: `/setbinanceproxy clear`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    proxy_val = context.args[0].strip()
    if proxy_val.lower() == "clear":
        await database.set_setting("binance_proxy", "")
        await update.message.reply_text("✅ *Binance Proxy removed (Direct connection restored).*", parse_mode=ParseMode.MARKDOWN)
    else:
        await database.set_setting("binance_proxy", proxy_val)
        await update.message.reply_text(f"✅ *Binance Proxy updated:*\n`{proxy_val}`\n\nTesting connection...", parse_mode=ParseMode.MARKDOWN)
        res = await binance_client.get_live_balances()
        if res.get("success"):
            total_usdt = res.get("total_usdt_all", 0.0)
            await update.message.reply_text(f"🎉 *Proxy Connected Successfully! Total Balance:* `${total_usdt:.2f}` USDT", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"⚠️ *Proxy saved, but test failed:*\n`{res.get('error')}`", parse_mode=ParseMode.MARKDOWN)

async def binancedeposits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    await handle_admin_binance_deposits_callback(update, context)

async def binancebalance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    await handle_admin_binance_balance_callback(update, context)


async def margins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    await handle_admin_margins_callback(update, context)

async def setmargin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ *Usage:*\n"
            "• Set for specific product: `/setmargin <product_id> <margin_amount>` (e.g. `/setmargin 9 0.60`)\n"
            "• Set global default margin: `/setmargin default <amount>` (e.g. `/setmargin default 0.25`)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Open Pricing UI", callback_data="admin_margins")]])
        )
        return

    target = context.args[0].strip().lower()
    try:
        margin_val = float(context.args[1].strip())
        if margin_val < 0:
            await update.message.reply_text("❌ Margin cannot be negative.")
            return
    except ValueError:
        await update.message.reply_text("❌ Invalid margin amount. Enter a number (e.g. 0.50).")
        return

    await database.set_product_margin(target, margin_val)
    if target == "default":
        msg = f"✅ *Global Default Profit Margin updated:*\n`+${margin_val:.2f}` USD added to all default products."
    else:
        try:
            prod_id = int(target)
            p = await catalog_sync.get_local_product(prod_id)
            p_name = p['name'] if p else f"Product {prod_id}"
            base_p = float(p.get('supplier_price', 0.0)) if p else 0.0
            sell_p = round(base_p + margin_val, 2)
            msg = (
                f"✅ *Profit Margin Updated for `{p_name}`:*\n\n"
                f"🏢 Supplier Base Price: `${base_p:.2f}` USD\n"
                f"💵 Your Profit: `+${margin_val:.2f}` USD\n"
                f"🏷️ Final Selling Price: `${sell_p:.2f}` USD"
            )
        except Exception:
            msg = f"✅ *Product `{target}` Margin updated:*\n`+${margin_val:.2f}` USD."

    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 Product Pricing UI", callback_data="admin_margins")],
            [InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]
        ])
    )

async def addbalance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: `/addbalance <@username|user_id> <amount>` (e.g. `/addbalance @john_doe 10.50`)", parse_mode=ParseMode.MARKDOWN)
        return

    target_uid = await database.get_user_id_by_identifier(context.args[0].strip())
    if not target_uid:
        await update.message.reply_text(f"❌ User `{context.args[0]}` not found in database.", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        amt = float(context.args[1].strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Enter a number.")
        return

    new_bal = await database.add_user_balance(target_uid, amt)
    u_info = await database.get_user_info(target_uid)
    u_label = f"@{u_info['username']}" if u_info.get("username") else (u_info.get("first_name") or f"ID {target_uid}")
    await update.message.reply_text(
        f"✅ *Balance Updated!*\n\n"
        f"👤 *User:* {u_label} (`{target_uid}`)\n"
        f"💵 *Amount Added:* `+${amt:.2f}` USD\n"
        f"💳 *New Balance:* `${new_bal:.2f}` USD",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
    )

async def send_broadcast_background(bot, admin_id: int, message_text: str):
    """Send broadcast messages in background with rate-limiting without blocking user interactions."""
    all_users = await database.get_all_user_ids()
    total_users = len(all_users)
    success_count = 0
    fail_count = 0
    
    logger.info(f"Starting background broadcast to {total_users} users...")
    for u_id in all_users:
        try:
            await bot.send_message(chat_id=u_id, text=message_text, parse_mode=ParseMode.MARKDOWN)
            success_count += 1
        except Exception:
            fail_count += 1
        # Smooth rate limiting (approx 25 msgs/sec to stay under Telegram limit)
        await asyncio.sleep(0.04)

    logger.info(f"Broadcast completed: {success_count} sent, {fail_count} failed.")
    try:
        await bot.send_message(
            chat_id=admin_id,
            text=(
                f"📢 *Broadcast Completed!*\n\n"
                f"👥 Total Target Users: `{total_users}`\n"
                f"🟢 Delivered Successfully: `{success_count}`\n"
                f"🔴 Failed / Blocked: `{fail_count}`"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error sending broadcast completion notification: {e}")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    if not context.args:
        context.user_data["waiting_for_admin_broadcast"] = True
        await update.message.reply_text(
            "📢 *Broadcast Announcement*\n\nSend the message you want to broadcast to all registered bot users:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="nav_admin")]])
        )
        return

    msg_text = " ".join(context.args)
    all_users = await database.get_all_user_ids()
    asyncio.create_task(send_broadcast_background(context.bot, user_id, msg_text))
    await update.message.reply_text(
        f"🚀 *Broadcast Launched in Background!*\n\n"
        f"👥 Sending to `{len(all_users)}` users in the background.\n"
        "⚡ The bot will continue responding normally to all users.",
        parse_mode=ParseMode.MARKDOWN
    )

async def deposits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    pending = await database.get_pending_deposits()
    text = f"💳 *Pending Deposits ({len(pending)})*\n\n"
    for d in pending[:10]:
        text += f"🆔 `{d['merchant_trade_no']}` | User: `{d['user_id']}` | Amount: `${d['amount']:.2f}` USD | Status: `{d['status']}`\n"

    if not pending:
        text += "_No pending deposit orders._"

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Deposits UI", callback_data="admin_deposits"), InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
    )

async def setwallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ *Usage:*\n"
            "`/setwallet BEP20 <address>`\n"
            "`/setwallet TRC20 <address>`\n"
            "`/setwallet ERC20 <address>`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📍 Open Wallets UI", callback_data="admin_wallets")]])
        )
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: `/setwallet <BEP20|TRC20|ERC20> <wallet_address>`", parse_mode=ParseMode.MARKDOWN)
        return

    network = context.args[0].strip().upper()
    if network not in ("BEP20", "TRC20", "ERC20"):
        await update.message.reply_text("❌ Invalid network. Choose BEP20, TRC20, or ERC20.")
        return

    new_wallet = context.args[1].strip()
    db_key = {"BEP20": "wallet_bep20", "TRC20": "wallet_trc20", "ERC20": "wallet_erc20"}[network]
    await database.set_setting(db_key, new_wallet)
    label = NETWORK_LABELS.get(network, network)
    await update.message.reply_text(
        f"✅ *{label} Wallet Updated!*\n\n"
        f"📍 *Address:*\n`{new_wallet}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📍 Wallets Menu", callback_data="admin_wallets"), InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
    )

async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    bep20 = await database.get_setting("wallet_bep20") or "NOT SET"
    trc20 = await database.get_setting("wallet_trc20") or "NOT SET"
    erc20 = await database.get_setting("wallet_erc20") or "NOT SET"

    text = (
        "📍 *Configured Deposit Wallet Addresses*\n\n"
        f"🟡 *BEP20 (BSC):*\n`{bep20}`\n\n"
        f"🔴 *TRC20 (TRON):*\n`{trc20}`\n\n"
        f"🔵 *ERC20 (ETH):*\n`{erc20}`"
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📍 Edit Wallets", callback_data="admin_wallets"), InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
    )

async def deductbalance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: `/deductbalance <@username|user_id> <amount>`", parse_mode=ParseMode.MARKDOWN)
        return
    
    target_uid = await database.get_user_id_by_identifier(context.args[0].strip())
    if not target_uid:
        await update.message.reply_text(f"❌ User `{context.args[0]}` not found in database.", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        amt = float(context.args[1].strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Enter a number.")
        return

    new_bal = await database.force_deduct_user_balance(target_uid, amt)
    u_info = await database.get_user_info(target_uid)
    u_label = f"@{u_info['username']}" if u_info.get("username") else (u_info.get("first_name") or f"ID {target_uid}")
    await update.message.reply_text(
        f"✅ *Balance Deducted:*\nUser {u_label} (`{target_uid}`): `-${amt:.2f}` USD\n💳 *New Balance:* `${new_bal:.2f}` USD",
        parse_mode=ParseMode.MARKDOWN
    )

async def setbalance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: `/setbalance <@username|user_id> <exact_amount>`", parse_mode=ParseMode.MARKDOWN)
        return

    target_uid = await database.get_user_id_by_identifier(context.args[0].strip())
    if not target_uid:
        await update.message.reply_text(f"❌ User `{context.args[0]}` not found in database.", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        amt = float(context.args[1].strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Enter a number.")
        return

    new_bal = await database.set_user_balance(target_uid, amt)
    u_info = await database.get_user_info(target_uid)
    u_label = f"@{u_info['username']}" if u_info.get("username") else (u_info.get("first_name") or f"ID {target_uid}")
    await update.message.reply_text(
        f"✅ *Exact Balance Set:*\nUser {u_label} (`{target_uid}`): `${new_bal:.2f}` USD",
        parse_mode=ParseMode.MARKDOWN
    )

async def checkbalance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/checkbalance <@username|user_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    target_uid = await database.get_user_id_by_identifier(context.args[0].strip())
    if not target_uid:
        await update.message.reply_text(f"❌ User `{context.args[0]}` not found in database.", parse_mode=ParseMode.MARKDOWN)
        return

    u_info = await database.get_user_info(target_uid)
    orders = await database.get_user_orders(target_uid, limit=5)
    await update.message.reply_text(
        f"🔍 *User Info:*\n"
        f"🆔 User ID: `{target_uid}`\n"
        f"👤 Name: {u_info.get('first_name') or 'N/A'}\n"
        f"🌐 Username: @{u_info.get('username') or 'N/A'}\n"
        f"💳 Balance: `${u_info.get('balance', 0.0):.2f}` USD\n"
        f"🛍️ Recent Orders: `{len(orders)}`",
        parse_mode=ParseMode.MARKDOWN
    )

async def getid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_type = chat.type
    chat_id = chat.id
    chat_title = chat.title or (f"@{chat.username}" if chat.username else "Private")
    
    await update.message.reply_text(
        f"🆔 *Chat Information*\n\n"
        f"📌 *Chat ID:* `{chat_id}`\n"
        f"🏷️ *Title:* {chat_title}\n"
        f"📂 *Type:* `{chat_type}`\n\n"
        f"💡 To set this group for order & deposit notifications, send:\n`/setgroup {chat_id}`",
        parse_mode=ParseMode.MARKDOWN
    )

async def testgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    grp_id = await get_notification_group_id()
    try:
        sent = await context.bot.send_message(
            chat_id=grp_id,
            text="🔔 *Test Notification:*\n\nTelegram Shop Bot is successfully connected to this group! ✅",
            parse_mode=ParseMode.MARKDOWN
        )
        await update.message.reply_text(
            f"✅ *Success!* Test message sent to group `{grp_id}` (Message ID: {sent.message_id}).",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ *Failed to send to group `{grp_id}`:*\n`{e}`\n\n"
            "👉 *Solution:*\n"
            "1. Make sure you have **added the Bot to the Group**.\n"
            "2. Make sure the Bot has **Admin / Send Messages permission** in the group.\n"
            "3. In the group, type `/getid` or `/setgroup` to auto-link the group!",
            parse_mode=ParseMode.MARKDOWN
        )

async def setgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    chat = update.effective_chat
    if context.args:
        new_grp = context.args[0].strip()
        try:
            new_grp_id = int(new_grp)
        except ValueError:
            await update.message.reply_text("❌ Invalid Group Chat ID. Must be integer e.g. `-1003721268860`")
            return
    elif chat.type in ("group", "supergroup", "channel"):
        new_grp_id = chat.id
    else:
        current_grp = await get_notification_group_id()
        await update.message.reply_text(
            f"📢 *Notification Group Settings*\n\n"
            f"Current Target Group Chat ID: `{current_grp}`\n\n"
            f"• To set manually: `/setgroup <group_chat_id>`\n"
            f"• To test connection: `/testgroup`\n"
            f"• Or add bot to your group and type `/setgroup` inside the group!",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await database.set_setting("notification_group_id", str(new_grp_id))
    
    # Try sending confirmation into the group directly
    try:
        await context.bot.send_message(
            chat_id=new_grp_id,
            text="🔔 *Telegram Shop Bot Connected!*\n\nOrder and deposit notifications will be posted here.",
            parse_mode=ParseMode.MARKDOWN
        )
        grp_status = "🟢 Successfully verified in group!"
    except Exception as e:
        grp_status = f"⚠️ Saved, but cannot message group yet: `{e}` (Make sure bot is added to group as Admin)"

    await update.message.reply_text(
        f"✅ *Notification Group Updated!*\n\n"
        f"📍 Target Group ID: `{new_grp_id}`\n"
        f"📊 Status: {grp_status}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
    )

async def toggleshop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    current = await database.get_setting("catalog_gemini_only", "1")
    new_val = "0" if current == "1" else "1"
    await database.set_setting("catalog_gemini_only", new_val)
    mode_text = "💎 Store Mode: Only Gemini Products" if new_val == "1" else "🌐 Store Mode: All Products Visible"
    await update.message.reply_text(
        f"✅ *Store Visibility Updated!*\n\n{mode_text}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin Panel", callback_data="nav_admin")]])
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    await handle_admin_stats_callback(update, context)

async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# --- MAIN ENGINE ---

def main():
    logger.info("Initializing Telegram Shop Bot...")

    proxy_url = os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    tg_base_url = os.getenv("TELEGRAM_BASE_URL")

    request_kwargs = {"connect_timeout": 30.0, "read_timeout": 30.0}
    if proxy_url:
        logger.info(f"Using Proxy: {proxy_url}")
        request_kwargs["proxy_url"] = proxy_url

    request = HTTPXRequest(**request_kwargs)
    builder = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).request(request)
    if tg_base_url:
        logger.info(f"Using custom Telegram Base URL: {tg_base_url}")
        builder.base_url(tg_base_url)

    async def on_startup(application):
        logger.info("Bot application started. Launching background product auto-sync & announcement worker (every 2 mins)...")
        asyncio.create_task(catalog_sync.start_periodic_catalog_sync(api_client, bot=application.bot, interval_seconds=120))

    builder.post_init(on_startup)
    app = builder.build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("setwallet", setwallet_command))
    app.add_handler(CommandHandler("wallet", wallet_command))
    app.add_handler(CommandHandler("setmargin", setmargin_command))
    app.add_handler(CommandHandler("margins", margins_command))
    app.add_handler(CommandHandler("setkey", setkey_command))
    app.add_handler(CommandHandler("setbinancekey", setbinancekey_command))
    app.add_handler(CommandHandler("setbinanceproxy", setbinanceproxy_command))
    app.add_handler(CommandHandler("setgroup", setgroup_command))
    app.add_handler(CommandHandler("getid", getid_command))
    app.add_handler(CommandHandler("testgroup", testgroup_command))
    app.add_handler(CommandHandler("addbalance", addbalance_command))
    app.add_handler(CommandHandler("deductbalance", deductbalance_command))
    app.add_handler(CommandHandler("setbalance", setbalance_command))
    app.add_handler(CommandHandler("checkbalance", checkbalance_command))
    app.add_handler(CommandHandler("toggleshop", toggleshop_command))
    app.add_handler(CommandHandler("deposits", deposits_command))
    app.add_handler(CommandHandler(["binancedeposits", "bdeposits"], binancedeposits_command))
    app.add_handler(CommandHandler(["binancebalance", "bbalance"], binancebalance_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_navigation, pattern=r"^nav_"))
    app.add_handler(CallbackQueryHandler(handle_product_detail, pattern=r"^prod_\d+"))
    app.add_handler(CallbackQueryHandler(handle_quantity_selector, pattern=r"^qty_\d+_\d+"))
    app.add_handler(CallbackQueryHandler(handle_buy_checkout, pattern=r"^buy_\d+_\d+"))
    app.add_handler(CallbackQueryHandler(handle_deposit_preset, pattern=r"^dep_amt_"))
    app.add_handler(CallbackQueryHandler(handle_deposit_network, pattern=r"^dep_net_"))
    app.add_handler(CallbackQueryHandler(handle_txhash_prompt, pattern=r"^dep_tx_"))
    app.add_handler(CallbackQueryHandler(handle_admin_router, pattern=r"^(admin_|dep_appr_|dep_rej_)"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern=r"^noop$"))

    # Text message listener
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_text_input))

    # Initialize DB & initial sync before polling
    import asyncio
    asyncio.run(database.init_db())
    try:
        asyncio.run(catalog_sync.sync_catalog_now(api_client))
    except Exception as e:
        logger.warning(f"Initial catalog sync warning: {e}")

    logger.info("Bot successfully configured. Launching polling (with auto-retry)...")
    app.run_polling(bootstrap_retries=-1)

if __name__ == "__main__":
    main()
