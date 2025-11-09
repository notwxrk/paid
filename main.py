import os
import logging
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import psycopg2
from psycopg2.extras import RealDictCursor
import threading

# Flask app for health check
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# Database connection
DATABASE_URL = "postgresql://zworld_user:dX0c9sh3kmVGEUBbqRMuK5Djrozfiek3@dpg-d47oviidbo4c73fbnrfg-a/zworld"

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# Create tables if they don't exist
def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Products table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                price DECIMAL(10,2) NOT NULL,
                quantity INTEGER NOT NULL,
                photo_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')
        
        # Orders table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                product_id INTEGER REFERENCES products(id),
                quantity INTEGER NOT NULL,
                total_price DECIMAL(10,2) NOT NULL,
                address TEXT NOT NULL,
                phone VARCHAR(20) NOT NULL,
                payment_method VARCHAR(50) NOT NULL,
                payment_screenshot TEXT,
                status VARCHAR(50) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        cur.close()
        conn.close()
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization error: {e}")

# Initialize database
init_db()

# Bot configuration
BOT_TOKEN = "8273588414:AAEA-hTsPMtfhOnpITe6A5uFcoDIr0M9WJM"
ADMIN_ID = 7632409181

# Conversation states
WAITING_QUANTITY, WAITING_ADDRESS, WAITING_PHONE, WAITING_PAYMENT_SCREENSHOT = range(4)
PRODUCT_NAME, PRODUCT_DESC, PRODUCT_PRICE, PRODUCT_QUANTITY, PRODUCT_PHOTO = range(5)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id == ADMIN_ID:
        # Admin menu
        keyboard = [
            [InlineKeyboardButton("🧨 Tovarlar", callback_data="admin_products")],
            [InlineKeyboardButton("➕ Tovar qo'shish", callback_data="add_product")],
            [InlineKeyboardButton("📦 Buyurtmalar", callback_data="admin_orders")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "👋 Admin panelga xush kelibsiz!\nQuyidagi menyudan tanlang:",
            reply_markup=reply_markup
        )
    else:
        # User menu
        keyboard = [
            [InlineKeyboardButton("🧨 Tovarlar", callback_data="view_products")],
            [InlineKeyboardButton("✨️ Mening Buyurtmalarim", callback_data="my_orders")],
            [InlineKeyboardButton("🚖 Yetkazib Berish", callback_data="delivery_info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "👋 Xush kelibsiz!\nQuyidagi menyudan tanlang:",
            reply_markup=reply_markup
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "view_products":
        await show_products(update, context)
    elif data == "my_orders":
        await show_my_orders(update, context)
    elif data == "delivery_info":
        await delivery_info(update, context)
    elif data.startswith("product_"):
        product_id = int(data.split("_")[1])
        await show_product_detail(update, context, product_id)
    elif data.startswith("order_"):
        product_id = int(data.split("_")[1])
        context.user_data['selected_product'] = product_id
        await ask_quantity(update, context)
    elif data == "admin_products":
        await admin_products(update, context)
    elif data == "add_product":
        await add_product_start(update, context)
    elif data == "admin_orders":
        await admin_orders(update, context)
    elif data.startswith("delete_product_"):
        product_id = int(data.split("_")[2])
        await delete_product(update, context, product_id)
    elif data.startswith("confirm_order_"):
        order_id = int(data.split("_")[2])
        await confirm_order(update, context, order_id)
    elif data.startswith("cancel_order_"):
        order_id = int(data.split("_")[2])
        await cancel_order(update, context, order_id)
    elif data in ["sber", "crypto"]:
        context.user_data['payment_method'] = data
        await ask_payment_details(update, context)
    elif data in ["trc20", "bsc20"]:
        await handle_crypto_network(update, context)

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE is_active = TRUE ORDER BY id DESC")
        products = cur.fetchall()
        cur.close()
        conn.close()
        
        if not products:
            await update.callback_query.message.reply_text("🤷‍♂️ Hozircha tovarlar mavjud emas.")
            return
        
        for product in products:
            caption = f"🏷 {product['name']}\n💵 Narxi: {product['price']:,} UZS\n📦 Miqdori: {product['quantity']} ta\n📝 {product['description']}"
            
            keyboard = [[InlineKeyboardButton("🛒 Buyurtma berish", callback_data=f"order_{product['id']}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if product['photo_url']:
                try:
                    await update.callback_query.message.reply_photo(
                        photo=product['photo_url'],
                        caption=caption,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    await update.callback_query.message.reply_text(
                        f"{caption}\n\n⚠️ Rasm yuklanmadi",
                        reply_markup=reply_markup
                    )
            else:
                await update.callback_query.message.reply_text(
                    caption,
                    reply_markup=reply_markup
                )
                
    except Exception as e:
        logging.error(f"Error showing products: {e}")
        await update.callback_query.message.reply_text("❌ Xatolik yuz berdi.")

async def show_product_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        cur.close()
        conn.close()
        
        if product:
            caption = f"🏷 {product['name']}\n💵 Narxi: {product['price']:,} UZS\n📦 Miqdori: {product['quantity']} ta\n📝 {product['description']}"
            
            keyboard = [[InlineKeyboardButton("🛒 Buyurtma berish", callback_data=f"order_{product['id']}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if product['photo_url']:
                try:
                    await update.callback_query.message.reply_photo(
                        photo=product['photo_url'],
                        caption=caption,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    await update.callback_query.message.reply_text(
                        f"{caption}\n\n⚠️ Rasm yuklanmadi",
                        reply_markup=reply_markup
                    )
            else:
                await update.callback_query.message.reply_text(
                    caption,
                    reply_markup=reply_markup
                )
    except Exception as e:
        logging.error(f"Error showing product detail: {e}")

async def ask_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("📝 Iltimos, kerakli miqdorni kiriting:")
    return WAITING_QUANTITY

async def handle_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            await update.message.reply_text("❌ Miqdor 0 dan katta bo'lishi kerak. Iltimos, qaytadan kiriting:")
            return WAITING_QUANTITY
        
        context.user_data['quantity'] = quantity
        
        # Get product price
        product_id = context.user_data['selected_product']
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT price, quantity FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        cur.close()
        conn.close()
        
        if quantity > product['quantity']:
            await update.message.reply_text(f"❌ Siz so'ragan miqdor mavjud emas. Maksimal miqdor: {product['quantity']}. Iltimos, qaytadan kiriting:")
            return WAITING_QUANTITY
        
        total_price = product['price'] * quantity
        context.user_data['total_price'] = float(total_price)
        
        await update.message.reply_text("🏠 Iltimos, yetkazib berish manzilingizni kiriting:")
        return WAITING_ADDRESS
        
    except ValueError:
        await update.message.reply_text("❌ Iltimos, raqam kiriting:")
        return WAITING_QUANTITY

async def handle_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['address'] = update.message.text
    await update.message.reply_text("📞 Iltimos, telefon raqamingizni kiriting:")
    return WAITING_PHONE

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("СБЕР", callback_data="sber")],
        [InlineKeyboardButton("CRYPTO", callback_data="crypto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    total_price = context.user_data['total_price']
    await update.message.reply_text(
        f"💳 To'lov usulini tanlang:\n💰 Jami summa: {total_price:,.0f} UZS",
        reply_markup=reply_markup
    )
    return ConversationHandler.END

async def ask_payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment_method = context.user_data['payment_method']
    total_price = context.user_data['total_price']
    
    if payment_method == "sber":
        message = f"""
💳 СБЕР Bank orqali to'lov:

💰 To'lov summasi: {total_price:,.0f} UZS
📞 Hisob raqam: `2202208046692951`

💡 To'lov qilgach, skrinshot yuboring.
        """
        await update.callback_query.message.reply_text(message, parse_mode='Markdown')
        context.user_data['waiting_screenshot'] = True
        
    else:  # crypto
        keyboard = [
            [InlineKeyboardButton("USDT TRC20", callback_data="trc20")],
            [InlineKeyboardButton("USDT BSC20", callback_data="bsc20")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.message.reply_text(
            f"🔗 To'lov tarmog'ini tanlang:\n💰 Jami summa: ${total_price/12500:.2f} USDT (taxminan)",
            reply_markup=reply_markup
        )

async def handle_crypto_network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    network = query.data
    total_price = context.user_data['total_price']
    usdt_amount = total_price / 12500  # Taxminiy kurs
    
    if network == "trc20":
        address = "TDDzr7Fup4SgUwv71sq1Mmbk1ntNrGuMzx"
        network_name = "USDT TRC20"
    else:
        address = "0xdf2e7d8d439432f8e06b767e540541728c635f"
        network_name = "USDT BSC20"
    
    message = f"""
🔗 {network_name} orqali to'lov:

💰 To'lov summasi: ${usdt_amount:.2f} USDT
📞 Hamyoni: `{address}`

💡 To'lov qilgach, skrinshot yuboring.
    """
    
    await query.message.reply_text(message, parse_mode='Markdown')
    context.user_data['waiting_screenshot'] = True

async def handle_payment_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_screenshot'):
        return
    
    if update.message.photo:
        # Save order to database
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            cur.execute('''
                INSERT INTO orders (user_id, product_id, quantity, total_price, address, phone, payment_method, payment_screenshot)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                update.effective_user.id,
                context.user_data['selected_product'],
                context.user_data['quantity'],
                context.user_data['total_price'],
                context.user_data['address'],
                context.user_data['phone'],
                context.user_data['payment_method'],
                "screenshot_received"
            ))
            
            # Update product quantity
            cur.execute('''
                UPDATE products SET quantity = quantity - %s WHERE id = %s
            ''', (context.user_data['quantity'], context.user_data['selected_product']))
            
            conn.commit()
            cur.close()
            conn.close()
            
            # Notify admin
            admin_message = f"""
🆕 Yangi buyurtma!

📦 Mahsulot ID: {context.user_data['selected_product']}
👤 Foydalanuvchi: @{update.effective_user.username or 'Noma\'lum'}
📞 Telefon: {context.user_data['phone']}
🏠 Manzil: {context.user_data['address']}
💰 Miqdor: {context.user_data['quantity']} ta
💵 Jami: {context.user_data['total_price']:,.0f} UZS
💳 To'lov usuli: {context.user_data['payment_method']}

✅ Buyurtmani tasdiqlash uchun admin panelga kiring.
            """
            
            await context.bot.send_message(ADMIN_ID, admin_message)
            
            # Confirm to user
            await update.message.reply_text("""
✅ Sizning buyurtmangiz qabul qilindi!

📦 Buyurtmangiz tekshirilmoqda. Adminlar tez orada buyurtmangizni tasdiqlashadi.

⏰ Barchasi to'g'ri bo'lsa, buyurtmangiz 3 kun ichida yetkazib beriladi.

🙏 Bizni tanlaganingiz uchun rahmat!
            """)
            
            # Clear user data
            context.user_data.clear()
            
        except Exception as e:
            logging.error(f"Error saving order: {e}")
            await update.message.reply_text("❌ Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.")

async def show_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT o.*, p.name as product_name 
            FROM orders o 
            LEFT JOIN products p ON o.product_id = p.id 
            WHERE o.user_id = %s 
            ORDER BY o.created_at DESC
        ''', (update.effective_user.id,))
        orders = cur.fetchall()
        cur.close()
        conn.close()
        
        if not orders:
            await update.callback_query.message.reply_text("🤷‍♂️ Sizda hali buyurtmalar mavjud emas.")
            return
        
        for order in orders:
            status_emoji = "⏳" if order['status'] == 'pending' else "✅" if order['status'] == 'confirmed' else "❌"
            
            message = f"""
📦 Buyurtma #{order['id']}
🏷 Mahsulot: {order['product_name']}
💰 Miqdor: {order['quantity']} ta
💵 Jami: {order['total_price']:,.0f} UZS
🏠 Manzil: {order['address']}
📞 Telefon: {order['phone']}
💳 To'lov: {order['payment_method']}
📊 Holat: {status_emoji} {order['status']}
📅 Sana: {order['created_at'].strftime('%Y-%m-%d %H:%M')}
            """
            await update.callback_query.message.reply_text(message)
            
    except Exception as e:
        logging.error(f"Error showing orders: {e}")
        await update.callback_query.message.reply_text("❌ Xatolik yuz berdi.")

async def delivery_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = """
🚖 Yetkazib berish:

📍 Toshkent bo'ylab: 1 kun ichida
📍 O'zbekiston barcha hududlari: 5 kun ichida
💰 Yetkazib berish: BEPUL

⏰ Ish vaqti: 9:00 - 18:00
📞 Aloqa: bot orqali
    """
    await update.callback_query.message.reply_text(message)

# Admin functions
async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM products ORDER BY id DESC")
        products = cur.fetchall()
        cur.close()
        conn.close()
        
        if not products:
            await update.callback_query.message.reply_text("🤷‍♂️ Hozircha tovarlar mavjud emas.")
            return
        
        for product in products:
            status = "✅ Aktiv" if product['is_active'] else "❌ Noaktiv"
            caption = f"🏷 {product['name']}\n💵 Narxi: {product['price']:,} UZS\n📦 Miqdori: {product['quantity']} ta\n📝 {product['description']}\n📊 {status}"
            
            keyboard = [[InlineKeyboardButton("🗑 O'chirish", callback_data=f"delete_product_{product['id']}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if product['photo_url']:
                try:
                    await update.callback_query.message.reply_photo(
                        photo=product['photo_url'],
                        caption=caption,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    await update.callback_query.message.reply_text(
                        f"{caption}\n\n⚠️ Rasm yuklanmadi",
                        reply_markup=reply_markup
                    )
            else:
                await update.callback_query.message.reply_text(
                    caption,
                    reply_markup=reply_markup
                )
                
    except Exception as e:
        logging.error(f"Error showing admin products: {e}")

async def delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
        conn.commit()
        cur.close()
        conn.close()
        
        await update.callback_query.message.reply_text("✅ Mahsulot muvaffaqiyatli o'chirildi.")
        await admin_products(update, context)
        
    except Exception as e:
        logging.error(f"Error deleting product: {e}")
        await update.callback_query.message.reply_text("❌ Xatolik yuz berdi.")

# Add product conversation - FIXED VERSION
async def add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    await update.callback_query.message.reply_text("🏷 Mahsulot nomini kiriting:")
    return PRODUCT_NAME

async def handle_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['product_name'] = update.message.text
    await update.message.reply_text("📝 Mahsulot tavsifini kiriting:")
    return PRODUCT_DESC

async def handle_product_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['product_desc'] = update.message.text
    await update.message.reply_text("💵 Mahsulot narxini (UZS) kiriting:")
    return PRODUCT_PRICE

async def handle_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text)
        context.user_data['product_price'] = price
        await update.message.reply_text("📦 Mahsulot miqdorini kiriting:")
        return PRODUCT_QUANTITY
    except ValueError:
        await update.message.reply_text("❌ Iltimos, raqam kiriting:")
        return PRODUCT_PRICE

async def handle_product_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        quantity = int(update.message.text)
        context.user_data['product_quantity'] = quantity
        await update.message.reply_text("🖼 Mahsulot rasmini yuboring (agar kerak bo'lmasa, 'skip' deb yozing):")
        return PRODUCT_PHOTO
    except ValueError:
        await update.message.reply_text("❌ Iltimos, raqam kiriting:")
        return PRODUCT_QUANTITY

async def handle_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        photo_url = None
        
        if update.message.photo:
            # Get the photo file
            photo_file = await update.message.photo[-1].get_file()
            photo_url = photo_file.file_path
            print(f"Photo URL: {photo_url}")  # Debug uchun
        elif update.message.text and update.message.text.lower() == 'skip':
            photo_url = None
        else:
            await update.message.reply_text("❌ Iltimos, rasm yuboring yoki 'skip' deb yozing:")
            return PRODUCT_PHOTO
        
        # Save product to database
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO products (name, description, price, quantity, photo_url)
            VALUES (%s, %s, %s, %s, %s)
        ''', (
            context.user_data['product_name'],
            context.user_data['product_desc'],
            context.user_data['product_price'],
            context.user_data['product_quantity'],
            photo_url
        ))
        conn.commit()
        cur.close()
        conn.close()
        
        await update.message.reply_text("✅ Mahsulot muvaffaqiyatli qo'shildi!")
        
    except Exception as e:
        logging.error(f"Error adding product: {e}")
        await update.message.reply_text(f"❌ Xatolik yuz berdi: {str(e)}")
    
    # Clear user data
    context.user_data.clear()
    return ConversationHandler.END

async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT o.*, p.name as product_name 
            FROM orders o 
            LEFT JOIN products p ON o.product_id = p.id 
            ORDER BY o.created_at DESC
        ''')
        orders = cur.fetchall()
        cur.close()
        conn.close()
        
        if not orders:
            await update.callback_query.message.reply_text("🤷‍♂️ Hozircha buyurtmalar mavjud emas.")
            return
        
        for order in orders:
            status_emoji = "⏳" if order['status'] == 'pending' else "✅" if order['status'] == 'confirmed' else "❌"
            
            message = f"""
📦 Buyurtma #{order['id']}
👤 Foydalanuvchi ID: {order['user_id']}
🏷 Mahsulot: {order['product_name']}
💰 Miqdor: {order['quantity']} ta
💵 Jami: {order['total_price']:,.0f} UZS
🏠 Manzil: {order['address']}
📞 Telefon: {order['phone']}
💳 To'lov: {order['payment_method']}
📊 Holat: {status_emoji} {order['status']}
📅 Sana: {order['created_at'].strftime('%Y-%m-%d %H:%M')}
            """
            
            keyboard = []
            if order['status'] == 'pending':
                keyboard.append([InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_order_{order['id']}")])
            keyboard.append([InlineKeyboardButton("🗑 Bekor qilish", callback_data=f"cancel_order_{order['id']}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.callback_query.message.reply_text(message, reply_markup=reply_markup)
            
    except Exception as e:
        logging.error(f"Error showing admin orders: {e}")

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int):
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get order info
        cur.execute("SELECT user_id FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        
        # Update order status
        cur.execute("UPDATE orders SET status = 'confirmed' WHERE id = %s", (order_id,))
        conn.commit()
        cur.close()
        conn.close()
        
        # Notify user
        try:
            await context.bot.send_message(
                order['user_id'],
                "✅ Buyurtmangiz tasdiqlandi!\n\n📦 Buyurtmangiz tayyorlanmoqda va tez orada yetkazib beriladi.\n⏰ Yetkazib berish: 3 kun ichida"
            )
        except Exception as e:
            logging.error(f"Error notifying user: {e}")
        
        await update.callback_query.message.reply_text("✅ Buyurtma tasdiqlandi va foydalanuvchi xabarlandi.")
        await admin_orders(update, context)
        
    except Exception as e:
        logging.error(f"Error confirming order: {e}")
        await update.callback_query.message.reply_text("❌ Xatolik yuz berdi.")

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int):
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get order info for restoring product quantity
        cur.execute("SELECT product_id, quantity FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        
        # Restore product quantity
        if order['product_id']:
            cur.execute("UPDATE products SET quantity = quantity + %s WHERE id = %s", 
                       (order['quantity'], order['product_id']))
        
        # Delete order
        cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
        conn.commit()
        cur.close()
        conn.close()
        
        await update.callback_query.message.reply_text("✅ Buyurtma bekor qilindi.")
        await admin_orders(update, context)
        
    except Exception as e:
        logging.error(f"Error canceling order: {e}")
        await update.callback_query.message.reply_text("❌ Xatolik yuz berdi.")

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Amal bekor qilindi.")
    context.user_data.clear()
    return ConversationHandler.END

def main():
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add conversation handler for ordering
    order_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_quantity, pattern="^order_")],
        states={
            WAITING_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quantity)],
            WAITING_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_address)],
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    # Add conversation handler for adding products
    add_product_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_product_start, pattern="^add_product$")],
        states={
            PRODUCT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_name)],
            PRODUCT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_desc)],
            PRODUCT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_price)],
            PRODUCT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_quantity)],
            PRODUCT_PHOTO: [MessageHandler(filters.PHOTO | filters.TEXT, handle_product_photo)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(order_conv_handler)
    application.add_handler(add_product_conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO, handle_payment_screenshot))
    
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start bot polling
    print("Bot starting...")
    application.run_polling()

if __name__ == '__main__':
    main()
