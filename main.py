import os
import logging
import threading
import time
import sqlite3
import asyncio
from datetime import datetime
from typing import Dict, List
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import Conflict, TimedOut, NetworkError

# Bot konfiguratsiyasi
BOT_TOKEN = "8273588414:AAEA-hTsPMtfhOnpITe6A5uFcoDIr0M9WJM"
ADMIN_ID = 7632409181
SUPPORT_USERNAME = "@DavlatBoshqarmasi"

# Database setup - PostgreSQL asosiy, SQLite backup
import psycopg2
import psycopg2.extras

# PostgreSQL URL
POSTGRES_URL = "postgresql://gaming_wy9h_user:wzTJ9WUzd8UK2HvzvnwLdeti0y6J39u8@dpg-d47lujjipnbc73cvte60-a/gaming_wy9h"

# SQLite backup
SQLITE_DB = "backup.db"

def get_postgres_connection():
    """PostgreSQL connection"""
    try:
        conn = psycopg2.connect(POSTGRES_URL)
        return conn
    except Exception as e:
        print(f"❌ PostgreSQL connection error: {e}")
        return None

def get_sqlite_connection():
    """SQLite connection"""
    try:
        conn = sqlite3.connect(SQLITE_DB, check_same_thread=False)
        return conn
    except Exception as e:
        print(f"❌ SQLite connection error: {e}")
        return None

def get_db_connection():
    """Asosiy PostgreSQL, agar ishlamasa SQLite"""
    conn = get_postgres_connection()
    if conn is not None:
        return conn, 'postgres'
    
    print("⚠️  PostgreSQL ishlamayapti, SQLite ishlatilmoqda...")
    sqlite_conn = get_sqlite_connection()
    return sqlite_conn, 'sqlite'

# Database initialization
def init_db():
    try:
        # PostgreSQL initialization
        postgres_conn = get_postgres_connection()
        if postgres_conn:
            cur = postgres_conn.cursor()
            
            # Products table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    price DECIMAL(10,2) NOT NULL,
                    quantity INTEGER NOT NULL,
                    image_url TEXT,
                    image_file_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Orders table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    product_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    total_price DECIMAL(10,2) NOT NULL,
                    address TEXT NOT NULL,
                    phone VARCHAR(20) NOT NULL,
                    payment_method VARCHAR(50) NOT NULL,
                    payment_screenshot TEXT,
                    status VARCHAR(50) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (product_id) REFERENCES products (id)
                )
            ''')
            
            postgres_conn.commit()
            cur.close()
            postgres_conn.close()
            print("✅ PostgreSQL database initialized successfully")
        
        # SQLite initialization (backup)
        sqlite_conn = get_sqlite_connection()
        if sqlite_conn:
            cur = sqlite_conn.cursor()
            
            # Products table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    price REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    image_url TEXT,
                    image_file_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Orders table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    total_price REAL NOT NULL,
                    address TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    payment_method TEXT NOT NULL,
                    payment_screenshot TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (product_id) REFERENCES products (id)
                )
            ''')
            
            sqlite_conn.commit()
            cur.close()
            sqlite_conn.close()
            print("✅ SQLite backup database initialized successfully")
            
        return True
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
        return False

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# States for conversation
(
    MAIN_MENU,
    VIEW_PRODUCTS,
    VIEW_ORDERS,
    DELIVERY_INFO,
    PRODUCT_DETAIL,
    ORDER_QUANTITY,
    ORDER_ADDRESS,
    ORDER_PHONE,
    ORDER_PAYMENT,
    PAYMENT_SCREENSHOT,
    ADMIN_MENU,
    ADMIN_ADD_PRODUCT_NAME,
    ADMIN_ADD_PRODUCT_DESC,
    ADMIN_ADD_PRODUCT_PRICE,
    ADMIN_ADD_PRODUCT_QUANTITY,
    ADMIN_ADD_PRODUCT_IMAGE
) = range(16)

# User states dictionary
user_states = {}
user_data = {}

# ========== Flask web server for uptime ping ==========
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Бот работает", 200

@app.route('/health')
def health():
    return "OK", 200

@app.route('/ping')
def ping():
    return "pong", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# Keyboard functions
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🧨 Mahsulotlar", callback_data="view_products")],
        [InlineKeyboardButton("✨️ Mening Buyurtmalarim", callback_data="my_orders")],
        [InlineKeyboardButton("🚖 Yetkazib Berish", callback_data="delivery_info")],
        [InlineKeyboardButton("📞 Qo'llab-quvvatlash", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ Mahsulot qo'shish", callback_data="admin_add_product")],
        [InlineKeyboardButton("🗑️ Mahsulot o'chirish", callback_data="admin_delete_product")],
        [InlineKeyboardButton("📦 Barcha buyurtmalar", callback_data="admin_view_orders")],
        [InlineKeyboardButton("🏪 Barcha mahsulotlar", callback_data="admin_view_products")],
        [InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_products_keyboard():
    products = get_products()
    keyboard = []
    
    for product in products:
        keyboard.append([
            InlineKeyboardButton(f"❌ {product[1]}", callback_data=f"delete_product_{product[0]}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")])
    return InlineKeyboardMarkup(keyboard)

def payment_methods_keyboard():
    keyboard = [
        [InlineKeyboardButton("💳 СБЕР Bank", callback_data="payment_sber")],
        [InlineKeyboardButton("₿ Crypto (USDT)", callback_data="payment_crypto")]
    ]
    return InlineKeyboardMarkup(keyboard)

def crypto_networks_keyboard():
    keyboard = [
        [InlineKeyboardButton("🌐 USDT TRC20", callback_data="crypto_trc20")],
        [InlineKeyboardButton("🔗 USDT BSC20", callback_data="crypto_bsc20")],
        [InlineKeyboardButton("🔙 Ortga", callback_data="back_to_payment")]
    ]
    return InlineKeyboardMarkup(keyboard)

def order_action_keyboard(order_id):
    keyboard = [
        [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_order_{order_id}")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel_order_{order_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def confirm_delete_keyboard(product_id):
    keyboard = [
        [InlineKeyboardButton("✅ HA, o'chirish", callback_data=f"confirm_delete_{product_id}")],
        [InlineKeyboardButton("❌ BEKOR QILISH", callback_data="admin_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Database operations
def execute_query(query, params=(), fetch=False, fetch_one=False):
    """Universal database query function"""
    conn, db_type = get_db_connection()
    if conn is None:
        return None
    
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        
        if fetch:
            if db_type == 'postgres':
                result = cur.fetchall()
            else:
                result = cur.fetchall()
        elif fetch_one:
            if db_type == 'postgres':
                result = cur.fetchone()
            else:
                result = cur.fetchone()
        else:
            result = None
        
        if not fetch and not fetch_one:
            conn.commit()
        
        cur.close()
        conn.close()
        
        return result
    except Exception as e:
        print(f"❌ Database query error: {e}")
        try:
            conn.close()
        except:
            pass
        return None

def save_product(name, description, price, quantity, image_file_id=None):
    """Save product to both databases"""
    query = '''
        INSERT INTO products (name, description, price, quantity, image_file_id)
        VALUES (%s, %s, %s, %s, %s)
    '''
    result = execute_query(query, (name, description, price, quantity, image_file_id))
    print(f"✅ Product saved: {name}, Image: {image_file_id is not None}")
    return result

def delete_product(product_id):
    """Delete product from database"""
    query = "DELETE FROM products WHERE id = %s"
    return execute_query(query, (product_id,))

def save_order(user_id, product_id, quantity, total_price, address, phone, payment_method, payment_screenshot):
    """Save order to both databases"""
    query = '''
        INSERT INTO orders (user_id, product_id, quantity, total_price, address, phone, payment_method, payment_screenshot)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    '''
    return execute_query(query, (user_id, product_id, quantity, total_price, address, phone, payment_method, payment_screenshot))

def get_products():
    """Get all products"""
    query = "SELECT * FROM products ORDER BY created_at DESC"
    return execute_query(query, fetch=True)

def get_available_products():
    """Get available products"""
    query = "SELECT * FROM products WHERE quantity > 0 ORDER BY created_at DESC"
    return execute_query(query, fetch=True)

def get_product(product_id):
    """Get product by ID"""
    query = "SELECT * FROM products WHERE id = %s"
    return execute_query(query, (product_id,), fetch_one=True)

def get_user_orders(user_id):
    """Get user orders"""
    query = '''
        SELECT o.*, p.name as product_name 
        FROM orders o 
        JOIN products p ON o.product_id = p.id 
        WHERE o.user_id = %s 
        ORDER BY o.created_at DESC
    '''
    return execute_query(query, (user_id,), fetch=True)

def get_all_orders():
    """Get all orders"""
    query = '''
        SELECT o.*, p.name as product_name 
        FROM orders o 
        JOIN products p ON o.product_id = p.id 
        ORDER BY o.created_at DESC
    '''
    return execute_query(query, fetch=True)

def update_order_status(order_id, status):
    """Update order status"""
    query = "UPDATE orders SET status = %s WHERE id = %s"
    return execute_query(query, (status, order_id))

def update_product_quantity(product_id, quantity_change):
    """Update product quantity"""
    query = "UPDATE products SET quantity = quantity + %s WHERE id = %s"
    return execute_query(query, (quantity_change, product_id))

def get_order(order_id):
    """Get order by ID"""
    query = "SELECT * FROM orders WHERE id = %s"
    return execute_query(query, (order_id,), fetch_one=True)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    welcome_text = f"""
Assalomu alaykum! 

"Paqildoq Zakaz*"  do'konimizga xush kelibsiz! 

Bizda siz uchun yuqori sifatli mahsulotlar keng assortimentda mavjud. 

Quyidagi menyudan kerakli bo'limni tanlang 👇
    """
    
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "👋 Admin, xush kelibsiz! Boshqaruv paneliga o'tdingiz.",
            reply_markup=admin_menu_keyboard()
        )
        user_states[user_id] = ADMIN_MENU
    else:
        await update.message.reply_text(
            welcome_text,
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
        user_states[user_id] = MAIN_MENU

# Handle callback queries
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    await query.answer()
    
    if data == "main_menu":
        await show_main_menu(query)
    
    elif data == "view_products":
        await show_products(query)
    
    elif data == "my_orders":
        await show_my_orders(query, user_id)
    
    elif data == "delivery_info":
        await show_delivery_info(query)
    
    elif data.startswith("product_"):
        product_id = int(data.split("_")[1])
        await show_product_detail(query, product_id)
    
    elif data.startswith("order_product_"):
        product_id = int(data.split("_")[2])
        user_data[user_id] = {"product_id": product_id}
        await ask_order_quantity(query)
    
    elif data.startswith("payment_"):
        await handle_payment_method(query, data, user_id)
    
    elif data.startswith("crypto_"):
        await handle_crypto_payment(query, data, user_id)
    
    elif data == "back_to_payment":
        await ask_payment_method(query, user_id)
    
    elif data == "skip_image":
        if user_id == ADMIN_ID and user_id in user_data and 'new_product' in user_data[user_id]:
            product_data = user_data[user_id]["new_product"]
            result = save_product(
                product_data["name"],
                product_data["description"],
                product_data["price"],
                product_data["quantity"]
            )
            
            if result:
                await query.edit_message_text(
                    "✅ Mahsulot muvaffaqiyatli qo'shildi! (Rasmsiz)",
                    reply_markup=admin_menu_keyboard()
                )
                user_states[user_id] = ADMIN_MENU
                if user_id in user_data:
                    user_data.pop(user_id)
            else:
                await query.edit_message_text(
                    "❌ Mahsulot qo'shishda xatolik. Iltimos, qayta urinib ko'ring.",
                    reply_markup=admin_menu_keyboard()
                )
    
    # Admin handlers
    elif user_id == ADMIN_ID:
        if data == "admin_menu":
            await show_admin_menu(query)
        
        elif data == "admin_add_product":
            await start_add_product(query)
        
        elif data == "admin_delete_product":
            await show_delete_products(query)
        
        elif data.startswith("delete_product_"):
            product_id = int(data.split("_")[2])
            await confirm_delete_product(query, product_id)
        
        elif data.startswith("confirm_delete_"):
            product_id = int(data.split("_")[2])
            await delete_product_handler(query, product_id)
        
        elif data == "admin_view_orders":
            await show_all_orders(query)
        
        elif data == "admin_view_products":
            await show_all_products_admin(query)
        
        elif data.startswith("confirm_order_"):
            order_id = int(data.split("_")[2])
            await confirm_order(query, order_id)
        
        elif data.startswith("cancel_order_"):
            order_id = int(data.split("_")[2])
            await cancel_order(query, order_id)

# Main menu functions
async def show_main_menu(query):
    menu_text = """
🏠 *Asosiy Menyu*

Quyidagi bo'limlardan birini tanlang:
    """
    
    await query.edit_message_text(
        menu_text,
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )
    user_states[query.from_user.id] = MAIN_MENU

async def show_products(query):
    try:
        products = get_available_products()
        
        if not products:
            await query.edit_message_text(
                "😔 Hozirda mavjud mahsulotlar yo'q. Iltimos, keyinroq tekshirib ko'ring.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]])
            )
            return
        
        keyboard = []
        for product in products:
            keyboard.append([InlineKeyboardButton(
                f"🧨 {product[1]} - {product[3]:,} so'm",
                callback_data=f"product_{product[0]}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")])
        
        await query.edit_message_text(
            "🛍️ Barcha Mahsulotlar\n\nQuyidagi mahsulotlardan birini tanlang:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        user_states[query.from_user.id] = VIEW_PRODUCTS
    except Exception as e:
        print(f"❌ Show products error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]])
        )

async def show_product_detail(query, product_id):
    try:
        product = get_product(product_id)
        
        if not product:
            await query.answer("Mahsulot topilmadi!")
            return
        
        message_text = f"""
🧨 {product[1]}

💵 Narxi: {product[3]:,} so'm
📦 Mavjud miqdori: {product[4]} ta
📝 Tavsif: {product[2]}

🛒 Buyurtma berish uchun quyidagi tugmani bosing.
        """
        
        keyboard = [
            [InlineKeyboardButton("🛒 Buyurtma Berish", callback_data=f"order_product_{product[0]}")],
            [InlineKeyboardButton("🔙 Mahsulotlar ro'yxati", callback_data="view_products")]
        ]
        
        # Agar rasm bo'lsa, rasm bilan jo'nat
        if product[6]:  # image_file_id
            try:
                await query.message.reply_photo(
                    photo=product[6],
                    caption=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                await query.message.delete()
            except Exception as e:
                print(f"❌ Photo send error: {e}")
                await query.edit_message_text(
                    message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
        else:
            await query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
    except Exception as e:
        print(f"❌ Show product detail error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Mahsulotlar ro'yxati", callback_data="view_products")]])
        )

async def ask_order_quantity(query):
    await query.edit_message_text(
        "📝 Buyurtma Miqdori*\n\nQancha dona mahsulot buyurtma qilmoqchisiz? Raqamda kiriting:\n\nMasalan: 1\n\n💡 *Eslatma: Kamida 1 dona buyurtma berishingiz mumkin",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]]),
        parse_mode="Markdown"
    )
    user_states[query.from_user.id] = ORDER_QUANTITY

async def ask_order_address(query):
    await query.edit_message_text(
        "🏠 Yetkazib Berish Manzili\n\nIltimos, to'liq yetkazib berish manzilingizni kiriting:\n\nShahar/tuman, ko'cha, uy, kvartira raqami",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]]),
        parse_mode="Markdown"
    )
    user_states[query.from_user.id] = ORDER_ADDRESS

async def ask_order_phone(query):
    await query.edit_message_text(
        "📞 *Aloqa Uchun Telefon Raqam\n\nIltimos, bog'lanish uchun telefon raqamingizni kiriting:\n\nMasalan: +998901234567",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]]),
        parse_mode="Markdown"
    )
    user_states[query.from_user.id] = ORDER_PHONE

async def ask_payment_method(query, user_id):
    try:
        product_id = user_data[user_id]["product_id"]
        quantity = user_data[user_id]["quantity"]
        
        product = get_product(product_id)
        
        if not product:
            await query.edit_message_text(
                "❌ Mahsulot topilmadi.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
            )
            return
        
        total_price = product[3] * quantity
        
        user_data[user_id]["total_price"] = float(total_price)
        
        await query.edit_message_text(
            f"💳 To'lov Usulini Tanlang*\n\n"
            f"📦 Mahsulot: {product[1]}\n"
            f"🔢 Miqdor: {quantity} ta\n"
            f"💰 Jami narx: {total_price:,} so'm\n\n"
            f"Quyidagi to'lov usullaridan birini tanlang:",
            reply_markup=payment_methods_keyboard(),
            parse_mode="Markdown"
        )
        user_states[user_id] = ORDER_PAYMENT
    except Exception as e:
        print(f"❌ Ask payment method error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
        )

async def handle_payment_method(query, data, user_id):
    if data == "payment_sber":
        total_price = user_data[user_id]["total_price"]
        user_data[user_id]["payment_method"] = "sber"
        
        await query.edit_message_text(
            f"💳 СБЕР Bank orqali to'lov\n\n"
            f"💳 Karta raqami: `2202208046692951`\n"
            f"💰 To'lov miqdori: {total_price:,} so'm\n\n"
            f"To'lovni amalga oshirgach, to'lov chekining skrinshotini yuboring.\n\n"
            f"💡 Eslatma: To'lovni aniq belgilangan summani o'tkazganingizga ishonch hosil qiling.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="back_to_payment")]])
        )
        user_states[user_id] = PAYMENT_SCREENSHOT
        
    elif data == "payment_crypto":
        await query.edit_message_text(
            "₿ Crypto To'lov Tarmog'i\n\nQuyidagi crypto tarmoqlaridan birini tanlang:",
            reply_markup=crypto_networks_keyboard(),
            parse_mode="Markdown"
        )

async def handle_crypto_payment(query, data, user_id):
    total_price = user_data[user_id]["total_price"]
    usdt_amount = total_price / 12400  # Approximate exchange rate
    
    if data == "crypto_trc20":
        address = "TDDzr7Fup4SgUwv71sq1Mmbk1ntNrGuMzx"
        network = "USDT TRC20"
        user_data[user_id]["payment_method"] = "crypto_trc20"
    else:  # crypto_bsc20
        address = "0xdf2e737d8d439432f8e06b767e540541728c635f"
        network = "USDT BSC20"
        user_data[user_id]["payment_method"] = "crypto_bsc20"
    
    await query.edit_message_text(
        f"🌐 {network} orqali to'lov\n\n"
        f"💳 Hamyon manzili: `{address}`\n"
        f"💰 To'lov miqdori: {usdt_amount:.2f} USDT\n\n"
        f"To'lovni amalga oshirgach, tranzaksiya skrinshotini yuboring.\n\n"
        f"💡 Eslatma: To'lovni aniq belgilangan summani o'tkazganingizga ishonch hosil qiling.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="back_to_payment")]])
    )
    user_states[user_id] = PAYMENT_SCREENSHOT

async def show_my_orders(query, user_id):
    try:
        orders = get_user_orders(user_id)
        
        if not orders:
            await query.edit_message_text(
                "📦 Hali sizda buyurtmalar mavjud emas. Birinchi buyurtma qilish uchun mahsulotlar bo'limiga o'ting.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]])
            )
            return
        
        message_text = "📦 Mening Buyurtmalarim\n\n"
        for order in orders:
            status_emoji = "⏳" if order[9] == 'pending' else "✅" if order[9] == 'confirmed' else "❌"
            status_text = "Kutilmoqda" if order[9] == 'pending' else "Tasdiqlandi" if order[9] == 'confirmed' else "Bekor qilindi"
            
            message_text += f"{status_emoji} *{order[11]}* - {order[3]} ta\n"
            message_text += f"💰 {order[4]:,} so'm\n"
            message_text += f"📅 {order[10].strftime('%d.%m.%Y %H:%M')}\n"
            message_text += f"📊 Holati: {status_text}\n\n"
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]]),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"❌ Show my orders error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]])
        )

async def show_delivery_info(query):
    delivery_text = f"""
🚖 Yetkazib Berish Xizmati

📍 O'zbekistonning barcha hududlariga yetkazib beramiz

⏰ Yetkazib berish muddati:
• Toshkent bo'ylab: 1 kun ichida
• Boshqa viloyatlar: 3-7 kun ichida

🚖 Yetkazib berish Bepul 

📦 Buyurtmalar tez, ishonchli va ehtiyotkorlik bilan yetkazib beriladi.

📞 **Texnik yordam:**
{SUPPORT_USERNAME}
    """
    
    await query.edit_message_text(
        delivery_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]]),
        parse_mode="Markdown"
    )

# Message handlers
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    state = user_states.get(user_id, MAIN_MENU)
    
    if state == ORDER_QUANTITY:
        await handle_order_quantity(update, user_id, message_text)
    
    elif state == ORDER_ADDRESS:
        await handle_order_address(update, user_id, message_text)
    
    elif state == ORDER_PHONE:
        await handle_order_phone(update, user_id, message_text)
    
    elif state == ADMIN_ADD_PRODUCT_NAME:
        await handle_admin_add_product_name(update, user_id, message_text)
    
    elif state == ADMIN_ADD_PRODUCT_DESC:
        await handle_admin_add_product_desc(update, user_id, message_text)
    
    elif state == ADMIN_ADD_PRODUCT_PRICE:
        await handle_admin_add_product_price(update, user_id, message_text)
    
    elif state == ADMIN_ADD_PRODUCT_QUANTITY:
        await handle_admin_add_product_quantity(update, user_id, message_text)

async def handle_order_quantity(update, user_id, quantity_text):
    try:
        quantity = int(quantity_text)
        if quantity < 1:
            await update.message.reply_text(
                "❌ Kamida 1 dona mahsulot buyurtma berishingiz kerak. Iltimos, 1 yoki undan ko'p raqam kiriting.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
            )
            return
        
        product_id = user_data[user_id]["product_id"]
        product = get_product(product_id)
        
        if quantity > product[4]:
            await update.message.reply_text(
                f"❌ Siz so'ragan miqdor mavjud emas! Maksimal {product[4]} dona buyurtma berishingiz mumkin.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
            )
            return
        
        user_data[user_id]["quantity"] = quantity
        await ask_order_address_after_message(update)
        
    except ValueError:
        await update.message.reply_text(
            "❌ Iltimos, faqat raqam kiriting! Masalan: 1, 2, 3",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
        )
    except Exception as e:
        print(f"❌ Handle order quantity error: {e}")
        await update.message.reply_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
        )

async def ask_order_address_after_message(update):
    await update.message.reply_text(
        "🏠 *Yetkazib Berish Manzili*\n\nIltimos, to'liq yetkazib berish manzilingizni kiriting:\n\nShahar/tuman, ko'cha, uy, kvartira raqami",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]]),
        parse_mode="Markdown"
    )
    user_states[update.effective_user.id] = ORDER_ADDRESS

async def handle_order_address(update, user_id, address):
    user_data[user_id]["address"] = address
    await ask_order_phone_after_message(update)

async def ask_order_phone_after_message(update):
    await update.message.reply_text(
        "📞 *Aloqa Uchun Telefon Raqam*\n\nIltimos, bog'lanish uchun telefon raqamingizni kiriting:\n\nMasalan: +998901234567",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]]),
        parse_mode="Markdown"
    )
    user_states[update.effective_user.id] = ORDER_PHONE

async def handle_order_phone(update, user_id, phone):
    user_data[user_id]["phone"] = phone
    await ask_payment_method_after_message(update, user_id)

async def ask_payment_method_after_message(update, user_id):
    try:
        product_id = user_data[user_id]["product_id"]
        quantity = user_data[user_id]["quantity"]
        
        product = get_product(product_id)
        total_price = product[3] * quantity
        user_data[user_id]["total_price"] = float(total_price)
        
        await update.message.reply_text(
            f"💳 *To'lov Usulini Tanlang*\n\n"
            f"📦 *Mahsulot:* {product[1]}\n"
            f"🔢 *Miqdor:* {quantity} ta\n"
            f"💰 *Jami narx:* {total_price:,} so'm\n\n"
            f"Quyidagi to'lov usullaridan birini tanlang:",
            reply_markup=payment_methods_keyboard(),
            parse_mode="Markdown"
        )
        user_states[user_id] = ORDER_PAYMENT
    except Exception as e:
        print(f"❌ Ask payment method after message error: {e}")
        await update.message.reply_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
        )

# Photo handlers
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    
    if state == PAYMENT_SCREENSHOT:
        # Payment screenshot
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()
        
        try:
            product_id = user_data[user_id]["product_id"]
            quantity = user_data[user_id]["quantity"]
            total_price = user_data[user_id]["total_price"]
            address = user_data[user_id]["address"]
            phone = user_data[user_id]["phone"]
            payment_method = user_data[user_id].get("payment_method", "sber")
            
            # Save order
            result = save_order(user_id, product_id, quantity, total_price, address, phone, payment_method, photo_file.file_id)
            
            if result:
                # Update product quantity
                update_product_quantity(product_id, -quantity)
                
                # Notify user
                success_text = f"""
✅ *Buyurtmangiz Muvaffaqiyatli Qabul Qilindi!*

📦 **Buyurtma tafsilotlari:**
• Mahsulot: {get_product(product_id)[1]}
• Miqdor: {quantity} ta
• Jami narx: {total_price:,} so'm
• Manzil: {address}

🕐 **Keyingi qadamlar:**
Buyurtmangiz tekshirish uchun adminlarga yuborildi. Tez orada siz bilan bog'lanamiz.

📞 **Bog'lanish:**
Agar savollaringiz bo'lsa, {SUPPORT_USERNAME} ga murojaat qiling.

🚚 **Yetkazib berish:**
• Toshkent bo'ylab: 1 kun ichida
• Boshqa viloyatlar: 3-7 kun ichida

Rahmat sizning buyurtmangiz uchun! 🙏
                """
                
                await update.message.reply_text(
                    success_text,
                    reply_markup=main_menu_keyboard(),
                    parse_mode="Markdown"
                )
                
                # Notify admin
                try:
                    # Get last order ID (simplified approach)
                    orders = get_all_orders()
                    if orders:
                        order_id = orders[0][0]  # First order's ID
                        
                        admin_notification = f"""
🆕 *Yangi Buyurtma!*

📦 **Buyurtma ID:** #{order_id}
👤 **Foydalanuvchi:** {user_id}
📞 **Telefon:** {phone}
🏠 **Manzil:** {address}
💰 **Jami summa:** {total_price:,} so'm
💳 **To'lov usuli:** {payment_method}

Mahsulotni tekshirib, mijozga javob bering.
                        """
                        
                        await context.bot.send_message(
                            ADMIN_ID,
                            admin_notification,
                            reply_markup=order_action_keyboard(order_id),
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    print(f"❌ Notify admin error: {e}")
                
                user_states[user_id] = MAIN_MENU
                if user_id in user_data:
                    user_data.pop(user_id)
            else:
                await update.message.reply_text(
                    "❌ Buyurtma saqlashda xatolik. Iltimos, qayta urinib ko'ring.",
                    reply_markup=main_menu_keyboard()
                )
                
        except Exception as e:
            print(f"❌ Handle photo error: {e}")
            await update.message.reply_text(
                "❌ Buyurtma saqlashda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
                reply_markup=main_menu_keyboard()
            )
    
    elif state == ADMIN_ADD_PRODUCT_IMAGE:
        # Product image for admin
        if user_id == ADMIN_ID and 'new_product' in user_data.get(user_id, {}):
            photo = update.message.photo[-1]
            photo_file_id = photo.file_id
            
            user_data[user_id]["new_product"]["image_file_id"] = photo_file_id
            
            # Save product with image
            product_data = user_data[user_id]["new_product"]
            result = save_product(
                product_data["name"],
                product_data["description"],
                product_data["price"],
                product_data["quantity"],
                photo_file_id
            )
            
            if result:
                await update.message.reply_text(
                    "✅ Mahsulot muvaffaqiyatli qo'shildi! 🖼️\n\nYangi mahsulot muvaffaqiyatli bazaga qo'shildi va foydalanuvchilar uchun mavjud.",
                    reply_markup=admin_menu_keyboard()
                )
                user_states[user_id] = ADMIN_MENU
                if user_id in user_data:
                    user_data.pop(user_id)
            else:
                await update.message.reply_text(
                    "❌ Mahsulot qo'shishda xatolik. Iltimos, qayta urinib ko'ring.",
                    reply_markup=admin_menu_keyboard()
                )

# Admin functions
async def show_admin_menu(query):
    admin_text = """
👨‍💼 *Admin Boshqaruv Paneli*

Kerakli bo'limni tanlang:
    """
    
    await query.edit_message_text(
        admin_text,
        reply_markup=admin_menu_keyboard(),
        parse_mode="Markdown"
    )
    user_states[query.from_user.id] = ADMIN_MENU

async def start_add_product(query):
    await query.edit_message_text(
        "📝 *Yangi Mahsulot Qo'shish*\n\nYangi mahsulot nomini kiriting:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]]),
        parse_mode="Markdown"
    )
    user_states[query.from_user.id] = ADMIN_ADD_PRODUCT_NAME

async def show_delete_products(query):
    products = get_products()
    
    if not products:
        await query.edit_message_text(
            "😔 Hozirda mahsulotlar mavjud emas.",
            reply_markup=admin_menu_keyboard()
        )
        return
    
    await query.edit_message_text(
        "🗑️ *Mahsulot O'chirish*\n\nO'chirmoqchi bo'lgan mahsulotingizni tanlang:",
        reply_markup=admin_products_keyboard(),
        parse_mode="Markdown"
    )

async def confirm_delete_product(query, product_id):
    product = get_product(product_id)
    if product:
        await query.edit_message_text(
            f"⚠️ *Mahsulot O'chirishni Tasdiqlash*\n\n"
            f"Quyidagi mahsulotni o'chirishni istaysizmi?\n\n"
            f"🧨 *{product[1]}*\n"
            f"💰 {product[3]:,} so'm\n"
            f"📦 {product[4]} ta\n\n"
            f"❌ *Diqqat:* Bu amalni qaytarib bo'lmaydi!",
            reply_markup=confirm_delete_keyboard(product_id),
            parse_mode="Markdown"
        )

async def delete_product_handler(query, product_id):
    result = delete_product(product_id)
    if result:
        await query.edit_message_text(
            "✅ Mahsulot muvaffaqiyatli o'chirildi!",
            reply_markup=admin_menu_keyboard()
        )
    else:
        await query.edit_message_text(
            "❌ Mahsulot o'chirishda xatolik. Iltimos, qayta urinib ko'ring.",
            reply_markup=admin_menu_keyboard()
        )

async def handle_admin_add_product_name(update, user_id, product_name):
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id]["new_product"] = {"name": product_name}
    
    await update.message.reply_text(
        "📝 *Mahsulot Tavsifi*\n\nMahsulot tavsifini kiriting:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]]),
        parse_mode="Markdown"
    )
    user_states[user_id] = ADMIN_ADD_PRODUCT_DESC

async def handle_admin_add_product_desc(update, user_id, description):
    user_data[user_id]["new_product"]["description"] = description
    await update.message.reply_text(
        "💰 *Mahsulot Narxi*\n\nMahsulot narxini so'mda kiriting:\n\nMasalan: 50000",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]]),
        parse_mode="Markdown"
    )
    user_states[user_id] = ADMIN_ADD_PRODUCT_PRICE

async def handle_admin_add_product_price(update, user_id, price_text):
    try:
        price = float(price_text)
        user_data[user_id]["new_product"]["price"] = price
        await update.message.reply_text(
            "📦 *Mahsulot Miqdori*\n\nMahsulot miqdorini kiriting:\n\nMasalan: 10",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]]),
            parse_mode="Markdown"
        )
        user_states[user_id] = ADMIN_ADD_PRODUCT_QUANTITY
    except ValueError:
        await update.message.reply_text("❌ Iltimos, to'g'ri narx kiriting!")

async def handle_admin_add_product_quantity(update, user_id, quantity_text):
    try:
        quantity = int(quantity_text)
        user_data[user_id]["new_product"]["quantity"] = quantity
        
        await update.message.reply_text(
            "🖼️ *Mahsulot Rasmi*\n\nMahsulot uchun rasm yuboring (ixtiyoriy).\n\n"
            "Agar rasm yubormoqchi bo'lmasangiz, 'Rasmsiz davom etish' tugmasini bosing.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Rasmsiz davom etish", callback_data="skip_image")]
            ])
        )
        user_states[user_id] = ADMIN_ADD_PRODUCT_IMAGE
        
    except ValueError:
        await update.message.reply_text("❌ Iltimos, to'g'ri miqdor kiriting!")

async def show_all_orders(query):
    try:
        orders = get_all_orders()
        
        if not orders:
            await query.edit_message_text(
                "📦 Hozirda buyurtmalar mavjud emas.",
                reply_markup=admin_menu_keyboard()
            )
            return
        
        message_text = "📦 *Barcha Buyurtmalar*\n\n"
        for order in orders:
            status_emoji = "⏳" if order[9] == 'pending' else "✅" if order[9] == 'confirmed' else "❌"
            status_text = "Kutilmoqda" if order[9] == 'pending' else "Tasdiqlandi" if order[9] == 'confirmed' else "Bekor qilindi"
            
            message_text += f"{status_emoji} *Buyurtma #{order[0]}*\n"
            message_text += f"📦 {order[11]} - {order[3]} ta\n"
            message_text += f"👤 Foydalanuvchi: {order[1]}\n"
            message_text += f"📞 {order[6]}\n"
            message_text += f"💰 {order[4]:,} so'm\n"
            message_text += f"📊 Holati: {status_text}\n\n"
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]]),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"❌ Show all orders error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=admin_menu_keyboard()
        )

async def show_all_products_admin(query):
    try:
        products = get_products()
        
        if not products:
            await query.edit_message_text(
                "😔 Hozirda mahsulotlar mavjud emas.",
                reply_markup=admin_menu_keyboard()
            )
            return
        
        message_text = "🏪 *Barcha Mahsulotlar*\n\n"
        for product in products:
            has_image = "🖼️" if product[6] else "📄"
            message_text += f"{has_image} *{product[1]}*\n"
            message_text += f"💰 {product[3]:,} so'm\n"
            message_text += f"📦 {product[4]} ta\n"
            message_text += f"📝 {product[2][:50]}...\n\n"
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]]),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"❌ Show all products error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=admin_menu_keyboard()
        )

async def confirm_order(query, order_id):
    try:
        # Update order status
        update_order_status(order_id, 'confirmed')
        
        # Get order details
        order = get_order(order_id)
        if order:
            user_id = order[1]
            product = get_product(order[2])
            
            # Notify user
            try:
                user_notification = f"""
✅ *Buyurtmangiz Tasdiqlandi!*

📦 **Buyurtma tafsilotlari:**
• Mahsulot: {product[1]}
• Miqdor: {order[3]} ta
• Jami narx: {order[4]:,} so'm

🚚 **Yetkazib berish:**
• Toshkent bo'ylab: 1 kun ichida
• Boshqa viloyatlar: 3-7 kun ichida

📞 **Aloqa:**
Agar savollaringiz bo'lsa, {SUPPORT_USERNAME} ga murojaat qiling.

Rahmat sizning buyurtmangiz uchun! Siz bilan tez orada bog'lanamiz. 🙏
                """
                
                await query.bot.send_message(
                    user_id,
                    user_notification,
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"❌ Notify user error: {e}")
        
        await query.edit_message_text(
            f"✅ *Buyurtma #{order_id} tasdiqlandi* va foydalanuvchiga xabar yuborildi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_view_orders")]]),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"❌ Confirm order error: {e}")
        await query.edit_message_text(
            f"❌ Buyurtma tasdiqlashda xatolik: {e}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_view_orders")]])
        )

async def cancel_order(query, order_id):
    try:
        # Update order status
        update_order_status(order_id, 'cancelled')
        
        # Get order details
        order = get_order(order_id)
        if order:
            user_id = order[1]
            
            # Restore product quantity
            update_product_quantity(order[2], order[3])
            
            # Notify user
            try:
                await query.bot.send_message(
                    user_id,
                    f"❌ *Buyurtmangiz Bekor Qilindi*\n\n"
                    f"Buyurtmangiz texnik sabablarga ko'ra bekor qilindi.\n\n"
                    f"Agar bu xato deb o'ylasangiz, qayta buyurtma bering yoki {SUPPORT_USERNAME} ga murojaat qiling.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"❌ Notify user error: {e}")
        
        await query.edit_message_text(
            f"❌ *Buyurtma #{order_id} bekor qilindi* va foydalanuvchiga xabar yuborildi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_view_orders")]]),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"❌ Cancel order error: {e}")
        await query.edit_message_text(
            f"❌ Buyurtma bekor qilishda xatolik: {e}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_view_orders")]])
        )

def run_bot():
    """Run the Telegram bot"""
    try:
        # Initialize database
        if not init_db():
            print("❌ Database initialization failed. Retrying in 10 seconds...")
            time.sleep(10)
            run_bot()
            return
        
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(handle_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        
        # Add error handler
        async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            error = context.error
            if isinstance(error, Conflict):
                print("⚠️  Bot conflict detected. Another instance might be running.")
                # Wait and try to restart
                time.sleep(10)
                return
            elif isinstance(error, (TimedOut, NetworkError)):
                print("⚠️  Network error. Retrying...")
                time.sleep(5)
                return
            else:
                print(f"❌ Error: {error}")
        
        application.add_error_handler(error_handler)
        
        # Start bot with polling (webhook emas!)
        print("🤖 Bot starting with polling...")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
    except Conflict as e:
        print("❌ Bot conflict. Waiting and restarting...")
        time.sleep(30)
        run_bot()
    except Exception as e:
        print(f"❌ Bot failed to start: {e}")
        time.sleep(10)
        run_bot()

if __name__ == "__main__":
    print("🚀 Starting application...")
    
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    print("🌐 Flask server started")
    
    # Run bot in main thread with restart capability
    run_bot()
