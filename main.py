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

# Database setup - Faqat SQLite ishlatamiz
SQLITE_DB = "bot_database.db"

def get_db_connection():
    """SQLite connection"""
    try:
        conn = sqlite3.connect(SQLITE_DB, check_same_thread=False)
        return conn
    except Exception as e:
        print(f"❌ SQLite connection error: {e}")
        return None

# Database initialization
def init_db():
    try:
        print("🔄 Database initializing...")
        
        conn = get_db_connection()
        if not conn:
            print("❌ Database ga ulanmadi!")
            return False
            
        cur = conn.cursor()
        
        # Products table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                price INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                image_url TEXT,
                image_file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("✅ Products table yaratildi")
        
        # Orders table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                total_price INTEGER NOT NULL,
                address TEXT NOT NULL,
                phone TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                payment_screenshot TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        ''')
        print("✅ Orders table yaratildi")
        
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database initialized successfully")
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
    return "✅ Bot ishlamoqda", 200

@app.route('/health')
def health():
    return "OK", 200

@app.route('/ping')
def ping():
    return "pong", 200

# Keyboard functions
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🧨 Mahsulotlar", callback_data="view_products")],
        [InlineKeyboardButton("📦 Mening buyurtmalarim", callback_data="my_orders")],
        [InlineKeyboardButton("🚖 Yetkazib berish", callback_data="delivery_info")]
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
    conn = get_db_connection()
    if conn is None:
        print("❌ Database ga ulanmadi!")
        return None
    
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        
        if fetch:
            result = cur.fetchall()
        elif fetch_one:
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
    """Save product to database"""
    query = '''
        INSERT INTO products (name, description, price, quantity, image_file_id)
        VALUES (?, ?, ?, ?, ?)
    '''
    result = execute_query(query, (name, description, price, quantity, image_file_id))
    print(f"✅ Product saved: {name}")
    return result

def delete_product(product_id):
    """Delete product from database"""
    query = "DELETE FROM products WHERE id = ?"
    return execute_query(query, (product_id,))

def save_order(user_id, product_id, quantity, total_price, address, phone, payment_method, payment_screenshot):
    """Save order to database"""
    query = '''
        INSERT INTO orders (user_id, product_id, quantity, total_price, address, phone, payment_method, payment_screenshot)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    '''
    return execute_query(query, (user_id, product_id, quantity, total_price, address, phone, payment_method, payment_screenshot))

def get_products():
    """Get all products"""
    query = "SELECT * FROM products ORDER BY created_at DESC"
    result = execute_query(query, fetch=True)
    return result or []

def get_available_products():
    """Get available products"""
    query = "SELECT * FROM products WHERE quantity > 0 ORDER BY created_at DESC"
    result = execute_query(query, fetch=True)
    return result or []

def get_product(product_id):
    """Get product by ID"""
    query = "SELECT * FROM products WHERE id = ?"
    return execute_query(query, (product_id,), fetch_one=True)

def get_user_orders(user_id):
    """Get user orders"""
    query = '''
        SELECT o.*, p.name as product_name 
        FROM orders o 
        JOIN products p ON o.product_id = p.id 
        WHERE o.user_id = ? 
        ORDER BY o.created_at DESC
    '''
    result = execute_query(query, (user_id,), fetch=True)
    return result or []

def get_all_orders():
    """Get all orders"""
    query = '''
        SELECT o.*, p.name as product_name 
        FROM orders o 
        JOIN products p ON o.product_id = p.id 
        ORDER BY o.created_at DESC
    '''
    result = execute_query(query, fetch=True)
    return result or []

def update_order_status(order_id, status):
    """Update order status"""
    query = "UPDATE orders SET status = ? WHERE id = ?"
    return execute_query(query, (status, order_id))

def update_product_quantity(product_id, quantity_change):
    """Update product quantity"""
    query = "UPDATE products SET quantity = quantity + ? WHERE id = ?"
    return execute_query(query, (quantity_change, product_id))

def get_order(order_id):
    """Get order by ID"""
    query = "SELECT * FROM orders WHERE id = ?"
    return execute_query(query, (order_id,), fetch_one=True)

def get_last_order_id():
    """Get last order ID"""
    query = "SELECT id FROM orders ORDER BY id DESC LIMIT 1"
    result = execute_query(query, fetch_one=True)
    return result[0] if result else None

# Format price without .00
def format_price(price):
    """Format price without decimal places"""
    return f"{int(price):,}".replace(",", " ")

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    welcome_text = """
👋 Assalomu alaykum! 

Premium Store do'konimizga xush kelibsiz! 

Quyidagi menyudan kerakli bo'limni tanlang 👇
    """
    
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "👋 Admin, xush kelibsiz!",
            reply_markup=admin_menu_keyboard()
        )
        user_states[user_id] = ADMIN_MENU
    else:
        await update.message.reply_text(
            welcome_text,
            reply_markup=main_menu_keyboard()
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
                    "✅ Mahsulot qo'shildi!",
                    reply_markup=admin_menu_keyboard()
                )
                user_states[user_id] = ADMIN_MENU
                if user_id in user_data:
                    user_data.pop(user_id)
            else:
                await query.edit_message_text(
                    "❌ Mahsulot qo'shishda xatolik.",
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
    await query.edit_message_text(
        "🏠 Asosiy menyu",
        reply_markup=main_menu_keyboard()
    )
    user_states[query.from_user.id] = MAIN_MENU

async def show_products(query):
    try:
        products = get_available_products()
        
        if not products:
            await query.edit_message_text(
                "😔 Hozirda mahsulotlar yo'q.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]])
            )
            return
        
        keyboard = []
        for product in products:
            keyboard.append([InlineKeyboardButton(
                f"🧨 {product[1]} - {format_price(product[3])} so'm",
                callback_data=f"product_{product[0]}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")])
        
        await query.edit_message_text(
            "🛍️ Mahsulotlar",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        user_states[query.from_user.id] = VIEW_PRODUCTS
    except Exception as e:
        print(f"❌ Show products error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi.",
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

💰 Narxi: {format_price(product[3])} so'm
📦 Mavjud: {product[4]} ta
📝 {product[2]}

🛒 Buyurtma berish uchun quyidagi tugmani bosing.
        """
        
        keyboard = [
            [InlineKeyboardButton("🛒 Buyurtma berish", callback_data=f"order_product_{product[0]}")],
            [InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]
        ]
        
        if product[6]:  # image_file_id
            try:
                await query.message.reply_photo(
                    photo=product[6],
                    caption=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                await query.message.delete()
            except Exception as e:
                print(f"❌ Photo send error: {e}")
                await query.edit_message_text(
                    message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            await query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        print(f"❌ Show product detail error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
        )

async def ask_order_quantity(query):
    await query.edit_message_text(
        "📝 Qancha dona kerak? Raqamda yozing:\n\nMasalan: 1",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
    )
    user_states[query.from_user.id] = ORDER_QUANTITY

async def ask_order_address(query):
    await query.edit_message_text(
        "🏠 Yetkazib berish manzilini yozing:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
    )
    user_states[query.from_user.id] = ORDER_ADDRESS

async def ask_order_phone(query):
    await query.edit_message_text(
        "📞 Telefon raqamingizni yozing:\n\nMasalan: +998901234567",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
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
        
        user_data[user_id]["total_price"] = total_price
        
        await query.edit_message_text(
            f"💳 To'lov usulini tanlang:\n\n"
            f"📦 Mahsulot: {product[1]}\n"
            f"🔢 Miqdor: {quantity} ta\n"
            f"💰 Jami: {format_price(total_price)} so'm",
            reply_markup=payment_methods_keyboard()
        )
        user_states[user_id] = ORDER_PAYMENT
    except Exception as e:
        print(f"❌ Ask payment method error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
        )

async def handle_payment_method(query, data, user_id):
    if data == "payment_sber":
        total_price = user_data[user_id]["total_price"]
        user_data[user_id]["payment_method"] = "sber"
        
        await query.edit_message_text(
            f"💳 СБЕР Bank orqali to'lov:\n\n"
            f"💳 Karta raqami: 2202208046692951\n"
            f"💰 To'lov miqdori: {format_price(total_price)} so'm\n\n"
            f"To'lov qilgach, skrinshot yuboring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="back_to_payment")]])
        )
        user_states[user_id] = PAYMENT_SCREENSHOT
        
    elif data == "payment_crypto":
        await query.edit_message_text(
            "🌐 Crypto tarmog'ini tanlang:",
            reply_markup=crypto_networks_keyboard()
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
        f"🌐 {network} orqali to'lov:\n\n"
        f"💳 Manzil: {address}\n"
        f"💰 To'lov miqdori: {usdt_amount:.2f} USDT\n\n"
        f"To'lov qilgach, skrinshot yuboring.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="back_to_payment")]])
    )
    user_states[user_id] = PAYMENT_SCREENSHOT

async def show_my_orders(query, user_id):
    try:
        orders = get_user_orders(user_id)
        
        if not orders:
            await query.edit_message_text(
                "📦 Hali buyurtmalar yo'q.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]])
            )
            return
        
        message_text = "📦 Mening buyurtmalarim:\n\n"
        for order in orders:
            status_emoji = "⏳" if order[9] == 'pending' else "✅" if order[9] == 'confirmed' else "❌"
            status_text = "Kutilmoqda" if order[9] == 'pending' else "Tasdiqlandi" if order[9] == 'confirmed' else "Bekor qilindi"
            
            message_text += f"{status_emoji} {order[11]} - {order[3]} ta\n"
            message_text += f"💰 {format_price(order[4])} so'm\n"
            message_text += f"📅 {order[10].split()[0]}\n"
            message_text += f"📊 {status_text}\n\n"
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]])
        )
    except Exception as e:
        print(f"❌ Show my orders error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]])
        )

async def show_delivery_info(query):
    delivery_text = """
🚖 Yetkazib berish

📍 O'zbekistonning barcha hududlariga

⏰ Yetkazib berish muddati:
• Toshkent bo'ylab: 1 kun
• Boshqa viloyatlar: 3-7 kun

💰 Yetkazib berish: BEPUL

📦 Buyurtmalar tez va ishonchli yetkazib beriladi.
    """
    
    await query.edit_message_text(
        delivery_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]])
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
                "❌ Kamida 1 dona buyurtma bering.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
            )
            return
        
        product_id = user_data[user_id]["product_id"]
        product = get_product(product_id)
        
        if quantity > product[4]:
            await update.message.reply_text(
                f"❌ Maksimal {product[4]} dona buyurtma bering.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
            )
            return
        
        user_data[user_id]["quantity"] = quantity
        await ask_order_address_after_message(update)
        
    except ValueError:
        await update.message.reply_text(
            "❌ Faqat raqam kiriting! Masalan: 1",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
        )
    except Exception as e:
        print(f"❌ Handle order quantity error: {e}")
        await update.message.reply_text(
            "❌ Xatolik yuz berdi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
        )

async def ask_order_address_after_message(update):
    await update.message.reply_text(
        "🏠 Yetkazib berish manzilini yozing:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
    )
    user_states[update.effective_user.id] = ORDER_ADDRESS

async def handle_order_address(update, user_id, address):
    user_data[user_id]["address"] = address
    await ask_order_phone_after_message(update)

async def ask_order_phone_after_message(update):
    await update.message.reply_text(
        "📞 Telefon raqamingizni yozing:\n\nMasalan: +998901234567",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
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
        user_data[user_id]["total_price"] = total_price
        
        await update.message.reply_text(
            f"💳 To'lov usulini tanlang:\n\n"
            f"📦 Mahsulot: {product[1]}\n"
            f"🔢 Miqdor: {quantity} ta\n"
            f"💰 Jami: {format_price(total_price)} so'm",
            reply_markup=payment_methods_keyboard()
        )
        user_states[user_id] = ORDER_PAYMENT
    except Exception as e:
        print(f"❌ Ask payment method after message error: {e}")
        await update.message.reply_text(
            "❌ Xatolik yuz berdi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
        )

# Photo handlers
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    
    if state == PAYMENT_SCREENSHOT:
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()
        
        try:
            product_id = user_data[user_id]["product_id"]
            quantity = user_data[user_id]["quantity"]
            total_price = user_data[user_id]["total_price"]
            address = user_data[user_id]["address"]
            phone = user_data[user_id]["phone"]
            payment_method = user_data[user_id].get("payment_method", "sber")
            
            result = save_order(user_id, product_id, quantity, total_price, address, phone, payment_method, photo_file.file_id)
            
            if result:
                update_product_quantity(product_id, -quantity)
                
                order_id = get_last_order_id()
                
                success_text = f"""
✅ Buyurtmangiz qabul qilindi!

📦 Mahsulot: {get_product(product_id)[1]}
🔢 Miqdor: {quantity} ta
💰 Jami: {format_price(total_price)} so'm
🏠 Manzil: {address}

📞 Tez orada siz bilan bog'lanamiz.

🚚 Yetkazib berish:
• Toshkent bo'ylab: 1 kun
• Boshqa viloyatlar: 3-7 kun

Rahmat!
                """
                
                await update.message.reply_text(
                    success_text,
                    reply_markup=main_menu_keyboard()
                )
                
                try:
                    admin_notification = f"""
🆕 Yangi buyurtma!

📦 Buyurtma ID: #{order_id}
👤 Foydalanuvchi: {user_id}
📞 Telefon: {phone}
🏠 Manzil: {address}
💰 Jami: {format_price(total_price)} so'm
💳 To'lov usuli: {payment_method}
                    """
                    
                    await context.bot.send_message(
                        ADMIN_ID,
                        admin_notification,
                        reply_markup=order_action_keyboard(order_id)
                    )
                except Exception as e:
                    print(f"❌ Notify admin error: {e}")
                
                user_states[user_id] = MAIN_MENU
                if user_id in user_data:
                    user_data.pop(user_id)
            else:
                await update.message.reply_text(
                    "❌ Buyurtma saqlashda xatolik.",
                    reply_markup=main_menu_keyboard()
                )
                
        except Exception as e:
            print(f"❌ Handle photo error: {e}")
            await update.message.reply_text(
                "❌ Buyurtma saqlashda xatolik.",
                reply_markup=main_menu_keyboard()
            )
    
    elif state == ADMIN_ADD_PRODUCT_IMAGE:
        if user_id == ADMIN_ID and 'new_product' in user_data.get(user_id, {}):
            photo = update.message.photo[-1]
            photo_file_id = photo.file_id
            
            user_data[user_id]["new_product"]["image_file_id"] = photo_file_id
            
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
                    "✅ Mahsulot qo'shildi!",
                    reply_markup=admin_menu_keyboard()
                )
                user_states[user_id] = ADMIN_MENU
                if user_id in user_data:
                    user_data.pop(user_id)
            else:
                await update.message.reply_text(
                    "❌ Mahsulot qo'shishda xatolik.",
                    reply_markup=admin_menu_keyboard()
                )

# Admin functions
async def show_admin_menu(query):
    await query.edit_message_text(
        "👨‍💼 Admin paneli",
        reply_markup=admin_menu_keyboard()
    )
    user_states[query.from_user.id] = ADMIN_MENU

async def start_add_product(query):
    await query.edit_message_text(
        "📝 Yangi mahsulot nomini kiriting:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
    )
    user_states[query.from_user.id] = ADMIN_ADD_PRODUCT_NAME

async def show_delete_products(query):
    products = get_products()
    
    if not products:
        await query.edit_message_text(
            "😔 Mahsulotlar yo'q.",
            reply_markup=admin_menu_keyboard()
        )
        return
    
    await query.edit_message_text(
        "🗑️ O'chirmoqchi bo'lgan mahsulotni tanlang:",
        reply_markup=admin_products_keyboard()
    )

async def confirm_delete_product(query, product_id):
    product = get_product(product_id)
    if product:
        await query.edit_message_text(
            f"⚠️ Quyidagi mahsulotni o'chirishni istaysizmi?\n\n"
            f"🧨 {product[1]}\n"
            f"💰 {format_price(product[3])} so'm\n"
            f"📦 {product[4]} ta\n\n"
            f"❌ Bu amalni qaytarib bo'lmaydi!",
            reply_markup=confirm_delete_keyboard(product_id)
        )

async def delete_product_handler(query, product_id):
    result = delete_product(product_id)
    if result:
        await query.edit_message_text(
            "✅ Mahsulot o'chirildi!",
            reply_markup=admin_menu_keyboard()
        )
    else:
        await query.edit_message_text(
            "❌ Mahsulot o'chirishda xatolik.",
            reply_markup=admin_menu_keyboard()
        )

async def handle_admin_add_product_name(update, user_id, product_name):
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id]["new_product"] = {"name": product_name}
    
    await update.message.reply_text(
        "📝 Mahsulot tavsifini kiriting:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
    )
    user_states[user_id] = ADMIN_ADD_PRODUCT_DESC

async def handle_admin_add_product_desc(update, user_id, description):
    user_data[user_id]["new_product"]["description"] = description
    await update.message.reply_text(
        "💰 Mahsulot narxini kiriting (so'mda):\n\nMasalan: 50000",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
    )
    user_states[user_id] = ADMIN_ADD_PRODUCT_PRICE

async def handle_admin_add_product_price(update, user_id, price_text):
    try:
        price = int(price_text)
        user_data[user_id]["new_product"]["price"] = price
        await update.message.reply_text(
            "📦 Mahsulot miqdorini kiriting:\n\nMasalan: 10",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
        )
        user_states[user_id] = ADMIN_ADD_PRODUCT_QUANTITY
    except ValueError:
        await update.message.reply_text("❌ To'g'ri narx kiriting!")

async def handle_admin_add_product_quantity(update, user_id, quantity_text):
    try:
        quantity = int(quantity_text)
        user_data[user_id]["new_product"]["quantity"] = quantity
        
        await update.message.reply_text(
            "🖼️ Mahsulot uchun rasm yuboring (ixtiyoriy).\n\n"
            "Agar rasm yubormasangiz, 'Rasmsiz davom etish' tugmasini bosing.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Rasmsiz davom etish", callback_data="skip_image")]
            ])
        )
        user_states[user_id] = ADMIN_ADD_PRODUCT_IMAGE
        
    except ValueError:
        await update.message.reply_text("❌ To'g'ri miqdor kiriting!")

async def show_all_orders(query):
    try:
        orders = get_all_orders()
        
        if not orders:
            await query.edit_message_text(
                "📦 Buyurtmalar yo'q.",
                reply_markup=admin_menu_keyboard()
            )
            return
        
        message_text = "📦 Barcha buyurtmalar:\n\n"
        for order in orders:
            status_emoji = "⏳" if order[9] == 'pending' else "✅" if order[9] == 'confirmed' else "❌"
            status_text = "Kutilmoqda" if order[9] == 'pending' else "Tasdiqlandi" if order[9] == 'confirmed' else "Bekor qilindi"
            
            message_text += f"{status_emoji} Buyurtma #{order[0]}\n"
            message_text += f"📦 {order[11]} - {order[3]} ta\n"
            message_text += f"👤 {order[1]}\n"
            message_text += f"📞 {order[6]}\n"
            message_text += f"💰 {format_price(order[4])} so'm\n"
            message_text += f"📊 {status_text}\n\n"
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
        )
    except Exception as e:
        print(f"❌ Show all orders error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi.",
            reply_markup=admin_menu_keyboard()
        )

async def show_all_products_admin(query):
    try:
        products = get_products()
        
        if not products:
            await query.edit_message_text(
                "😔 Mahsulotlar yo'q.",
                reply_markup=admin_menu_keyboard()
            )
            return
        
        message_text = "🏪 Barcha mahsulotlar:\n\n"
        for product in products:
            has_image = "🖼️" if product[6] else "📄"
            message_text += f"{has_image} {product[1]}\n"
            message_text += f"💰 {format_price(product[3])} so'm\n"
            message_text += f"📦 {product[4]} ta\n"
            message_text += f"📝 {product[2][:50]}...\n\n"
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
        )
    except Exception as e:
        print(f"❌ Show all products error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi.",
            reply_markup=admin_menu_keyboard()
        )

async def confirm_order(query, order_id):
    try:
        update_order_status(order_id, 'confirmed')
        
        order = get_order(order_id)
        if order:
            user_id = order[1]
            product = get_product(order[2])
            
            try:
                user_notification = f"""
✅ Buyurtmangiz tasdiqlandi!

📦 {product[1]}
🔢 {order[3]} ta
💰 {format_price(order[4])} so'm

🚚 Yetkazib berish:
• Toshkent bo'ylab: 1 kun
• Boshqa viloyatlar: 3-7 kun

Tez orada siz bilan bog'lanamiz.
                """
                
                await query.bot.send_message(
                    user_id,
                    user_notification
                )
            except Exception as e:
                print(f"❌ Notify user error: {e}")
        
        await query.edit_message_text(
            f"✅ Buyurtma #{order_id} tasdiqlandi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_view_orders")]])
        )
    except Exception as e:
        print(f"❌ Confirm order error: {e}")
        await query.edit_message_text(
            f"❌ Xatolik: {e}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_view_orders")]])
        )

async def cancel_order(query, order_id):
    try:
        update_order_status(order_id, 'cancelled')
        
        order = get_order(order_id)
        if order:
            user_id = order[1]
            update_product_quantity(order[2], order[3])
            
            try:
                await query.bot.send_message(
                    user_id,
                    "❌ Buyurtmangiz bekor qilindi.\n\nAgar xato deb o'ylasangiz, qayta buyurtma bering."
                )
            except Exception as e:
                print(f"❌ Notify user error: {e}")
        
        await query.edit_message_text(
            f"❌ Buyurtma #{order_id} bekor qilindi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_view_orders")]])
        )
    except Exception as e:
        print(f"❌ Cancel order error: {e}")
        await query.edit_message_text(
            f"❌ Xatolik: {e}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_view_orders")]])
        )

def run_bot():
    """Run the Telegram bot"""
    try:
        print("🤖 Starting Telegram bot...")
        
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(handle_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        
        print("✅ Bot handlers added")
        
        # Start polling
        print("🔄 Bot polling started...")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
    except Exception as e:
        print(f"❌ Bot failed to start: {e}")
        print("🔄 Restarting bot in 10 seconds...")
        time.sleep(10)
        run_bot()

def run_flask():
    """Run Flask server"""
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    print("🚀 Starting application...")
    
    # Initialize database first
    print("🔄 Initializing database...")
    if init_db():
        print("✅ Database initialized successfully")
        
        # Start Flask in a separate thread
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        print("🌐 Flask server started")
        
        # Run bot in main thread
        run_bot()
    else:
        print("❌ Database initialization failed, exiting...")
