import os
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import Conflict, TimedOut, NetworkError

# Bot konfiguratsiyasi
BOT_TOKEN = "8273588414:AAEA-hTsPMtfhOnpITe6A5uFcoDIr0M9WJM"
ADMIN_ID = 7632409181

# Database setup - TO'G'RI URL
import psycopg2
import psycopg2.extras

# Database URL ni to'g'rilaymiz
DATABASE_URL = "postgresql://dream_6s3v_user:vkAOuqwN79nizVnBlJddDgaeryO5PXaQ@dpg-d47l0sjipnbc73cv7vsg-a/dream_6s3v"

def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        return None

# Database initialization
def init_db():
    try:
        conn = get_db_connection()
        if conn is None:
            print("❌ Database connection failed")
            return False
            
        cur = conn.cursor()
        
        # Products table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                price DECIMAL(10,2) NOT NULL,
                quantity INTEGER NOT NULL,
                image_url TEXT,
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
        [InlineKeyboardButton("🧨 Tovarlar", callback_data="view_products")],
        [InlineKeyboardButton("✨️ Mening Buyurtmalarim", callback_data="my_orders")],
        [InlineKeyboardButton("🚖 Yetkazib Berish", callback_data="delivery_info")]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ Tovar qo'shish", callback_data="admin_add_product")],
        [InlineKeyboardButton("📦 Barcha buyurtmalar", callback_data="admin_view_orders")],
        [InlineKeyboardButton("🏪 Barcha tovarlar", callback_data="admin_view_products")],
        [InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def payment_methods_keyboard():
    keyboard = [
        [InlineKeyboardButton("СБЕР", callback_data="payment_sber")],
        [InlineKeyboardButton("CRYPTO", callback_data="payment_crypto")]
    ]
    return InlineKeyboardMarkup(keyboard)

def crypto_networks_keyboard():
    keyboard = [
        [InlineKeyboardButton("USDT TRC20", callback_data="crypto_trc20")],
        [InlineKeyboardButton("USDT BSC20", callback_data="crypto_bsc20")],
        [InlineKeyboardButton("🔙 Ortga", callback_data="back_to_payment")]
    ]
    return InlineKeyboardMarkup(keyboard)

def order_action_keyboard(order_id):
    keyboard = [
        [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_order_{order_id}")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel_order_{order_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "👋 Admin, xush kelibsiz!",
            reply_markup=admin_menu_keyboard()
        )
        user_states[user_id] = ADMIN_MENU
    else:
        await update.message.reply_text(
            "👋 Assalomu alaykum! Magazine botimizga xush kelibsiz!",
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
    
    # Admin handlers
    elif user_id == ADMIN_ID:
        if data == "admin_menu":
            await show_admin_menu(query)
        
        elif data == "admin_add_product":
            await start_add_product(query)
        
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
        conn = get_db_connection()
        if conn is None:
            await query.edit_message_text(
                "❌ Database bilan bog'lanishda xatolik. Iltimos, keyinroq urinib ko'ring.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="main_menu")]])
            )
            return
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cur.execute("SELECT * FROM products WHERE quantity > 0 ORDER BY created_at DESC")
        products = cur.fetchall()
        
        cur.close()
        conn.close()
        
        if not products:
            await query.edit_message_text(
                "😔 Hozirda tovarlar mavjud emas.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="main_menu")]])
            )
            return
        
        keyboard = []
        for product in products:
            keyboard.append([InlineKeyboardButton(
                f"🧨 {product['name']} - {product['price']:,} UZS",
                callback_data=f"product_{product['id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 Ortga", callback_data="main_menu")])
        
        await query.edit_message_text(
            "🛍️ Barcha tovarlar:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        user_states[query.from_user.id] = VIEW_PRODUCTS
    except Exception as e:
        print(f"❌ Show products error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="main_menu")]])
        )

async def show_product_detail(query, product_id):
    try:
        conn = get_db_connection()
        if conn is None:
            await query.answer("Database xatolik!")
            return
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if not product:
            await query.answer("Tovar topilmadi!")
            return
        
        message_text = f"""
🧨 {product['name']}

💰 Narxi: {product['price']:,} UZS
📦 Miqdori: {product['quantity']} ta
📝 Tavsif: {product['description']}
        """
        
        keyboard = [
            [InlineKeyboardButton("🛒 Buyurtma Berish", callback_data=f"order_product_{product['id']}")],
            [InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]
        ]
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        print(f"❌ Show product detail error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
        )

async def ask_order_quantity(query):
    await query.edit_message_text(
        "📝 Qancha miqdorda kerak? Raqamda yozing:\n\nMasalan: 2",
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
        "📞 Aloqa uchun telefon raqamingizni yozing:\n\nMasalan: +998901234567",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
    )
    user_states[query.from_user.id] = ORDER_PHONE

async def ask_payment_method(query, user_id):
    try:
        product_id = user_data[user_id]["product_id"]
        quantity = user_data[user_id]["quantity"]
        
        conn = get_db_connection()
        if conn is None:
            await query.edit_message_text(
                "❌ Database xatolik. Iltimos, keyinroq urinib ko'ring.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
            )
            return
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        
        cur.close()
        conn.close()
        
        total_price = product['price'] * quantity
        
        user_data[user_id]["total_price"] = float(total_price)
        
        await query.edit_message_text(
            f"💳 To'lov usulini tanlang:\n\n"
            f"📦 Tovar: {product['name']}\n"
            f"🔢 Miqdor: {quantity} ta\n"
            f"💰 Jami narx: {total_price:,} UZS",
            reply_markup=payment_methods_keyboard()
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
            f"💳 СБЕР Bank orqali to'lov:\n\n"
            f"💳 Karta raqami: `2202208046692951`\n"
            f"💰 To'lov miqdori: {total_price:,} UZS\n\n"
            f"To'lov qilgach, screenshot yuboring:",
            parse_mode="Markdown",
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
        f"💳 Manzil: `{address}`\n"
        f"💰 To'lov miqdori: {usdt_amount:.2f} USDT\n\n"
        f"To'lov qilgach, screenshot yuboring:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="back_to_payment")]])
    )
    user_states[user_id] = PAYMENT_SCREENSHOT

async def show_my_orders(query, user_id):
    try:
        conn = get_db_connection()
        if conn is None:
            await query.edit_message_text(
                "❌ Database xatolik. Iltimos, keyinroq urinib ko'ring.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="main_menu")]])
            )
            return
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cur.execute('''
            SELECT o.*, p.name as product_name 
            FROM orders o 
            JOIN products p ON o.product_id = p.id 
            WHERE o.user_id = %s 
            ORDER BY o.created_at DESC
        ''', (user_id,))
        orders = cur.fetchall()
        
        cur.close()
        conn.close()
        
        if not orders:
            await query.edit_message_text(
                "📦 Hali sizda buyurtmalar mavjud emas.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="main_menu")]])
            )
            return
        
        message_text = "📦 Mening buyurtmalarim:\n\n"
        for order in orders:
            status_emoji = "⏳" if order['status'] == 'pending' else "✅" if order['status'] == 'confirmed' else "❌"
            message_text += f"{status_emoji} {order['product_name']} - {order['quantity']} ta\n"
            message_text += f"💰 {order['total_price']:,} UZS\n"
            message_text += f"📅 {order['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
            message_text += f"📊 Holati: {order['status']}\n\n"
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="main_menu")]])
        )
    except Exception as e:
        print(f"❌ Show my orders error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="main_menu")]])
        )

async def show_delivery_info(query):
    delivery_text = """
🚖 Yetkazib Berish

📍 O'zbekistonning barcha hududlariga yetkazib berish

⏰ Yetkazib berish muddati: 3 kun

💰 Yetkazib berish: BEPUL

📦 Buyurtmalar tez va ishonchli yetkazib beriladi!
    """
    
    await query.edit_message_text(
        delivery_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="main_menu")]])
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
        if quantity <= 0:
            await update.message.reply_text("❌ Miqdor 0 dan katta bo'lishi kerak!")
            return
        
        product_id = user_data[user_id]["product_id"]
        
        conn = get_db_connection()
        if conn is None:
            await update.message.reply_text("❌ Database xatolik. Iltimos, keyinroq urinib ko'ring.")
            return
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cur.execute("SELECT quantity FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if quantity > product['quantity']:
            await update.message.reply_text(f"❌ Siz so'ragan miqdor mavjud emas! Maksimal: {product['quantity']} ta")
            return
        
        user_data[user_id]["quantity"] = quantity
        await ask_order_address_after_message(update)
        
    except ValueError:
        await update.message.reply_text("❌ Iltimos, raqam kiriting!")
    except Exception as e:
        print(f"❌ Handle order quantity error: {e}")
        await update.message.reply_text("❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")

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
        "📞 Aloqa uchun telefon raqamingizni yozing:\n\nMasalan: +998901234567",
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
        
        conn = get_db_connection()
        if conn is None:
            await update.message.reply_text("❌ Database xatolik. Iltimos, keyinroq urinib ko'ring.")
            return
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        
        cur.close()
        conn.close()
        
        total_price = product['price'] * quantity
        user_data[user_id]["total_price"] = float(total_price)
        
        await update.message.reply_text(
            f"💳 To'lov usulini tanlang:\n\n"
            f"📦 Tovar: {product['name']}\n"
            f"🔢 Miqdor: {quantity} ta\n"
            f"💰 Jami narx: {total_price:,} UZS",
            reply_markup=payment_methods_keyboard()
        )
        user_states[user_id] = ORDER_PAYMENT
    except Exception as e:
        print(f"❌ Ask payment method after message error: {e}")
        await update.message.reply_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="view_products")]])
        )

# Photo handler for payment screenshots
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    
    if state == PAYMENT_SCREENSHOT:
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()
        
        try:
            # Save order to database
            conn = get_db_connection()
            if conn is None:
                await update.message.reply_text("❌ Database xatolik. Iltimos, keyinroq urinib ko'ring.")
                return
                
            cur = conn.cursor()
            
            product_id = user_data[user_id]["product_id"]
            quantity = user_data[user_id]["quantity"]
            total_price = user_data[user_id]["total_price"]
            address = user_data[user_id]["address"]
            phone = user_data[user_id]["phone"]
            payment_method = user_data[user_id].get("payment_method", "sber")
            
            cur.execute('''
                INSERT INTO orders (user_id, product_id, quantity, total_price, address, phone, payment_method, payment_screenshot)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (user_id, product_id, quantity, total_price, address, phone, payment_method, photo_file.file_id))
            
            # Update product quantity
            cur.execute('''
                UPDATE products SET quantity = quantity - %s WHERE id = %s
            ''', (quantity, product_id))
            
            conn.commit()
            
            # Get the last order ID
            cur.execute("SELECT LASTVAL()")
            order_id = cur.fetchone()[0]
            
            cur.close()
            conn.close()
            
            # Notify user
            await update.message.reply_text(
                "✅ Buyurtmangiz qabul qilindi!\n\n"
                "📦 Sizning buyurtmangiz ko'rib chiqilmoqda. Adminlar tez orada qabul qilishadi. "
                "Barchasi to'g'ri bo'lsa, buyurtma 3 kun ichida yetkazib beriladi.",
                reply_markup=main_menu_keyboard()
            )
            
            # Notify admin
            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"🆕 Yangi buyurtma!\n\n"
                    f"📦 Buyurtma ID: {order_id}\n"
                    f"👤 Foydalanuvchi: {user_id}\n"
                    f"📞 Telefon: {phone}\n"
                    f"🏠 Manzil: {address}\n"
                    f"💰 Jami: {total_price:,} UZS\n"
                    f"💳 To'lov usuli: {payment_method}",
                    reply_markup=order_action_keyboard(order_id)
                )
            except Exception as e:
                print(f"❌ Notify admin error: {e}")
            
            user_states[user_id] = MAIN_MENU
            if user_id in user_data:
                user_data.pop(user_id)
                
        except Exception as e:
            print(f"❌ Handle photo error: {e}")
            await update.message.reply_text(
                "❌ Buyurtma saqlashda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
                reply_markup=main_menu_keyboard()
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
        "📝 Yangi tovar nomini kiriting:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
    )
    user_states[query.from_user.id] = ADMIN_ADD_PRODUCT_NAME

async def handle_admin_add_product_name(update, user_id, product_name):
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id]["new_product"] = {"name": product_name}
    
    await update.message.reply_text(
        "📝 Tovar tavsifini kiriting:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
    )
    user_states[user_id] = ADMIN_ADD_PRODUCT_DESC

async def handle_admin_add_product_desc(update, user_id, description):
    user_data[user_id]["new_product"]["description"] = description
    await update.message.reply_text(
        "💰 Tovar narxini kiriting (UZS):\n\nMasalan: 50000",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
    )
    user_states[user_id] = ADMIN_ADD_PRODUCT_PRICE

async def handle_admin_add_product_price(update, user_id, price_text):
    try:
        price = float(price_text)
        user_data[user_id]["new_product"]["price"] = price
        await update.message.reply_text(
            "📦 Tovar miqdorini kiriting:\n\nMasalan: 10",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
        )
        user_states[user_id] = ADMIN_ADD_PRODUCT_QUANTITY
    except ValueError:
        await update.message.reply_text("❌ Iltimos, to'g'ri narx kiriting!")

async def handle_admin_add_product_quantity(update, user_id, quantity_text):
    try:
        quantity = int(quantity_text)
        product_data = user_data[user_id]["new_product"]
        
        conn = get_db_connection()
        if conn is None:
            await update.message.reply_text("❌ Database xatolik. Iltimos, keyinroq urinib ko'ring.")
            return
            
        cur = conn.cursor()
        
        cur.execute('''
            INSERT INTO products (name, description, price, quantity)
            VALUES (%s, %s, %s, %s)
        ''', (product_data["name"], product_data["description"], product_data["price"], quantity))
        
        conn.commit()
        cur.close()
        conn.close()
        
        await update.message.reply_text(
            "✅ Tovar muvaffaqiyatli qo'shildi!",
            reply_markup=admin_menu_keyboard()
        )
        user_states[user_id] = ADMIN_MENU
        if user_id in user_data:
            user_data.pop(user_id)
        
    except Exception as e:
        print(f"❌ Add product error: {e}")
        await update.message.reply_text(
            "❌ Tovar qo'shishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=admin_menu_keyboard()
        )

async def show_all_orders(query):
    try:
        conn = get_db_connection()
        if conn is None:
            await query.edit_message_text(
                "❌ Database xatolik. Iltimos, keyinroq urinib ko'ring.",
                reply_markup=admin_menu_keyboard()
            )
            return
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cur.execute('''
            SELECT o.*, p.name as product_name 
            FROM orders o 
            JOIN products p ON o.product_id = p.id 
            ORDER BY o.created_at DESC
        ''')
        orders = cur.fetchall()
        
        cur.close()
        conn.close()
        
        if not orders:
            await query.edit_message_text(
                "📦 Hali buyurtmalar mavjud emas.",
                reply_markup=admin_menu_keyboard()
            )
            return
        
        message_text = "📦 Barcha buyurtmalar:\n\n"
        for order in orders:
            status_emoji = "⏳" if order['status'] == 'pending' else "✅" if order['status'] == 'confirmed' else "❌"
            message_text += f"{status_emoji} Buyurtma #{order['id']}\n"
            message_text += f"📦 {order['product_name']} - {order['quantity']} ta\n"
            message_text += f"👤 User: {order['user_id']}\n"
            message_text += f"📞 {order['phone']}\n"
            message_text += f"💰 {order['total_price']:,} UZS\n"
            message_text += f"📊 Holati: {order['status']}\n\n"
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
        )
    except Exception as e:
        print(f"❌ Show all orders error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=admin_menu_keyboard()
        )

async def show_all_products_admin(query):
    try:
        conn = get_db_connection()
        if conn is None:
            await query.edit_message_text(
                "❌ Database xatolik. Iltimos, keyinroq urinib ko'ring.",
                reply_markup=admin_menu_keyboard()
            )
            return
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cur.execute("SELECT * FROM products ORDER BY created_at DESC")
        products = cur.fetchall()
        
        cur.close()
        conn.close()
        
        if not products:
            await query.edit_message_text(
                "😔 Hozirda tovarlar mavjud emas.",
                reply_markup=admin_menu_keyboard()
            )
            return
        
        message_text = "🏪 Barcha tovarlar:\n\n"
        for product in products:
            message_text += f"🧨 {product['name']}\n"
            message_text += f"💰 {product['price']:,} UZS\n"
            message_text += f"📦 {product['quantity']} ta\n"
            message_text += f"📝 {product['description'][:50]}...\n\n"
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_menu")]])
        )
    except Exception as e:
        print(f"❌ Show all products error: {e}")
        await query.edit_message_text(
            "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=admin_menu_keyboard()
        )

async def confirm_order(query, order_id):
    try:
        conn = get_db_connection()
        if conn is None:
            await query.edit_message_text("❌ Database xatolik.")
            return
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cur.execute("UPDATE orders SET status = 'confirmed' WHERE id = %s", (order_id,))
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        
        conn.commit()
        cur.close()
        conn.close()
        
        # Notify user
        try:
            await query.bot.send_message(
                order['user_id'],
                "✅ Buyurtmangiz tasdiqlandi!\n\n"
                "📦 Buyurtmangiz tayyorlanmoqda va tez orada yetkazib beriladi. "
                "3 kun ichida yetkazib berilishi rejalashtirilgan."
            )
        except Exception as e:
            print(f"❌ Notify user error: {e}")
        
        await query.edit_message_text(
            f"✅ Buyurtma #{order_id} tasdiqlandi va foydalanuvchiga xabar yuborildi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_view_orders")]])
        )
    except Exception as e:
        print(f"❌ Confirm order error: {e}")
        await query.edit_message_text(
            f"❌ Buyurtma tasdiqlashda xatolik: {e}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_view_orders")]])
        )

async def cancel_order(query, order_id):
    try:
        conn = get_db_connection()
        if conn is None:
            await query.edit_message_text("❌ Database xatolik.")
            return
            
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        
        if order:
            # Restore product quantity
            cur.execute('''
                UPDATE products SET quantity = quantity + %s WHERE id = %s
            ''', (order['quantity'], order['product_id']))
            
            cur.execute("UPDATE orders SET status = 'cancelled' WHERE id = %s", (order_id,))
            
            conn.commit()
            
            # Notify user
            try:
                await query.bot.send_message(
                    order['user_id'],
                    "❌ Buyurtmangiz bekor qilindi.\n\n"
                    "Agar bu xato deb o'ylasangiz, qayta buyurtma bering yoki admin bilan bog'laning."
                )
            except Exception as e:
                print(f"❌ Notify user error: {e}")
        
        cur.close()
        conn.close()
        
        await query.edit_message_text(
            f"❌ Buyurtma #{order_id} bekor qilindi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ortga", callback_data="admin_view_orders")]])
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
        
        # Start bot with conflict handling
        print("🤖 Bot starting...")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            close_loop=False,
            stop_signals=None
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
