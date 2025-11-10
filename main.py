import os
import logging
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
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
        
        # Drop and recreate tables to ensure all columns exist
        cur.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                price DECIMAL(10,2) NOT NULL,
                quantity INTEGER NOT NULL,
                photo_url TEXT,
                photo_file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')
        
        # Check and add missing columns
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='products'
        """)
        existing_columns = [row['column_name'] for row in cur.fetchall()]
        
        required_columns = ['photo_url', 'photo_file_id', 'is_active', 'created_at']
        for column in required_columns:
            if column not in existing_columns:
                if column == 'photo_url':
                    cur.execute("ALTER TABLE products ADD COLUMN photo_url TEXT")
                elif column == 'photo_file_id':
                    cur.execute("ALTER TABLE products ADD COLUMN photo_file_id TEXT")
                elif column == 'is_active':
                    cur.execute("ALTER TABLE products ADD COLUMN is_active BOOLEAN DEFAULT TRUE")
                elif column == 'created_at':
                    cur.execute("ALTER TABLE products ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                print(f"Added {column} column to products table")
        
        # Orders table with delivery info
        cur.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                product_id INTEGER REFERENCES products(id),
                quantity INTEGER NOT NULL,
                total_price DECIMAL(10,2) NOT NULL,
                address TEXT NOT NULL,
                location_lat DECIMAL(10,8),
                location_lng DECIMAL(10,8),
                phone VARCHAR(20) NOT NULL,
                payment_method VARCHAR(50) NOT NULL,
                payment_screenshot TEXT,
                delivery_region VARCHAR(50) DEFAULT 'tashkent',
                delivery_cost DECIMAL(10,2) DEFAULT 0,
                status VARCHAR(50) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Check and add location columns
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='orders' AND column_name IN ('location_lat', 'location_lng', 'delivery_region', 'delivery_cost')
        """)
        existing_order_columns = [row['column_name'] for row in cur.fetchall()]
        
        if 'location_lat' not in existing_order_columns:
            cur.execute("ALTER TABLE orders ADD COLUMN location_lat DECIMAL(10,8)")
        if 'location_lng' not in existing_order_columns:
            cur.execute("ALTER TABLE orders ADD COLUMN location_lng DECIMAL(10,8)")
        if 'delivery_region' not in existing_order_columns:
            cur.execute("ALTER TABLE orders ADD COLUMN delivery_region VARCHAR(50) DEFAULT 'tashkent'")
        if 'delivery_cost' not in existing_order_columns:
            cur.execute("ALTER TABLE orders ADD COLUMN delivery_cost DECIMAL(10,2) DEFAULT 0")
        
        conn.commit()
        cur.close()
        conn.close()
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization error: {e}")

# Initialize database
init_db()

# Bot configuration
BOT_TOKEN = "8598744941:AAEeY_6i-hU1nKBq-7mRbbH06s7gr-bJJOY"
ADMIN_ID = 7632409181

# Conversation states
WAITING_QUANTITY, WAITING_PHONE, WAITING_LOCATION, WAITING_ADDRESS = range(4)
PRODUCT_NAME, PRODUCT_DESC, PRODUCT_PRICE, PRODUCT_QUANTITY, PRODUCT_PHOTO = range(5)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Exchange rates (approximate)
UZS_TO_RUB = 0.0075  # 1 UZS = 0.0075 RUB
UZS_TO_USD = 0.00008  # 1 UZS = 0.00008 USD

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
    elif data in ["sber", "crypto", "uzcard"]:
        context.user_data['payment_method'] = data
        await ask_payment_details(update, context)
    elif data in ["trc20", "bsc20"]:
        await handle_crypto_network(update, context)

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Use COALESCE to handle NULL is_active values
        cur.execute("SELECT * FROM products WHERE COALESCE(is_active, TRUE) = TRUE ORDER BY id DESC")
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
            
            # Try to use file_id first (more reliable)
            if product.get('photo_file_id'):
                try:
                    await update.callback_query.message.reply_photo(
                        photo=product['photo_file_id'],
                        caption=caption,
                        reply_markup=reply_markup
                    )
                    continue
                except Exception as e:
                    print(f"File ID failed: {e}")
            
            # Fallback to URL
            if product.get('photo_url'):
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
            
            # Try to use file_id first (more reliable)
            if product.get('photo_file_id'):
                try:
                    await update.callback_query.message.reply_photo(
                        photo=product['photo_file_id'],
                        caption=caption,
                        reply_markup=reply_markup
                    )
                    return
                except Exception as e:
                    print(f"File ID failed: {e}")
            
            # Fallback to URL
            if product.get('photo_url'):
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
        
        # Ask for phone number
        await update.message.reply_text("📞 Iltimos, telefon raqamingizni kiriting:")
        return WAITING_PHONE
        
    except ValueError:
        await update.message.reply_text("❌ Iltimos, raqam kiriting:")
        return WAITING_QUANTITY

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    
    # Create location keyboard
    location_keyboard = [[KeyboardButton("📍 Lokatsiyani yuborish", request_location=True)]]
    reply_markup = ReplyKeyboardMarkup(location_keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        "📍 Iltimos, lokatsiyangizni yuboring:\n\n"
        "📱 Telefoningizdagi '📍 Lokatsiyani yuborish' tugmasini bosing",
        reply_markup=reply_markup
    )
    return WAITING_LOCATION

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        location = update.message.location
        context.user_data['location_lat'] = location.latitude
        context.user_data['location_lng'] = location.longitude
        
        # Remove location keyboard
        remove_keyboard = ReplyKeyboardMarkup.remove_keyboard()
        await update.message.reply_text(
            "✅ Lokatsiya qabul qilindi!\n\n"
            "🏠 Endi manzilingizni aniq yozib yuboring (ko'cha, uy, kvartira):",
            reply_markup=remove_keyboard
        )
        return WAITING_ADDRESS
    else:
        await update.message.reply_text("❌ Iltimos, lokatsiyangizni yuboring:")
        return WAITING_LOCATION

async def handle_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['address'] = update.message.text
    
    # Determine delivery region and cost based on location
    location_lat = context.user_data.get('location_lat')
    location_lng = context.user_data.get('location_lng')
    
    # Simple region detection (in real app, use geocoding API)
    delivery_region = "other"
    delivery_cost = 25000  # 25,000 UZS for other regions
    
    # If we have coordinates, we could check if it's in Tashkent
    # For now, we'll assume Tashkent if coordinates are provided
    if location_lat and location_lng:
        # Simple check for Tashkent coordinates (approximate)
        if 41.0 <= location_lat <= 41.5 and 69.0 <= location_lng <= 69.5:
            delivery_region = "tashkent"
            delivery_cost = 0
    
    context.user_data['delivery_region'] = delivery_region
    context.user_data['delivery_cost'] = delivery_cost
    
    total_price = context.user_data['total_price']
    total_with_delivery = total_price + delivery_cost
    
    context.user_data['total_with_delivery'] = total_with_delivery
    
    # Show delivery info
    if delivery_region == "tashkent":
        delivery_info = "🚖 Yetkazib berish: Toshkent bo'ylab BEPUL\n⏰ Bugun yetkazib beriladi"
    else:
        delivery_info = f"🚖 Yetkazib berish: {delivery_cost:,} UZS\n⏰ 1-3 kun ichida yetkazib beriladi"
    
    keyboard = [
        [InlineKeyboardButton("💳 UZCARD/HUMO", callback_data="uzcard")],
        [InlineKeyboardButton("💳 СБЕР", callback_data="sber")],
        [InlineKeyboardButton("CRYPTO", callback_data="crypto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"💳 To'lov usulini tanlang:\n\n"
        f"💰 Mahsulot narxi: {total_price:,.0f} UZS\n"
        f"🚖 Yetkazib berish: {delivery_cost:,.0f} UZS\n"
        f"💵 Jami: {total_with_delivery:,.0f} UZS\n\n"
        f"{delivery_info}",
        reply_markup=reply_markup
    )
    return ConversationHandler.END

async def ask_payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment_method = context.user_data['payment_method']
    total_with_delivery = context.user_data['total_with_delivery']
    delivery_region = context.user_data['delivery_region']
    
    if payment_method == "sber":
        rub_amount = total_with_delivery * UZS_TO_RUB
        message = f"""
💳 СБЕР Bank orqali to'lov:

💰 To'lov summasi: {rub_amount:,.2f} RUB
💵 So'mda: {total_with_delivery:,.0f} UZS
📞 Hisob raqam: `2202208046692951`

💡 To'lov qilgach, skrinshot yuboring.
        """
        await update.callback_query.message.reply_text(message, parse_mode='Markdown')
        context.user_data['waiting_screenshot'] = True
        
    elif payment_method == "uzcard":
        message = f"""
💳 UZCARD/HUMO orqali to'lov:

💰 To'lov summasi: {total_with_delivery:,.0f} UZS
📞 Hisob raqam: `9860080314781347`

💡 To'lov qilgach, skrinshot yuboring.
        """
        await update.callback_query.message.reply_text(message, parse_mode='Markdown')
        context.user_data['waiting_screenshot'] = True
        
    else:  # crypto
        usd_amount = total_with_delivery * UZS_TO_USD
        keyboard = [
            [InlineKeyboardButton("USDT TRC20", callback_data="trc20")],
            [InlineKeyboardButton("USDT BSC20", callback_data="bsc20")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.message.reply_text(
            f"🔗 To'lov tarmog'ini tanlang:\n💰 Jami summa: ${usd_amount:.2f} USDT (taxminan)",
            reply_markup=reply_markup
        )

async def handle_crypto_network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    network = query.data
    total_with_delivery = context.user_data['total_with_delivery']
    usd_amount = total_with_delivery * UZS_TO_USD
    
    if network == "trc20":
        address = "TDDzr7Fup4SgUwv71sq1Mmbk1ntNrGuMzx"
        network_name = "USDT TRC20"
    else:
        address = "0xdf2e7d8d439432f8e06b767e540541728c635f"
        network_name = "USDT BSC20"
    
    message = f"""
🔗 {network_name} orqali to'lov:

💰 To'lov summasi: ${usd_amount:.2f} USDT
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
                INSERT INTO orders (user_id, product_id, quantity, total_price, address, 
                location_lat, location_lng, phone, payment_method, payment_screenshot,
                delivery_region, delivery_cost)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                update.effective_user.id,
                context.user_data['selected_product'],
                context.user_data['quantity'],
                context.user_data['total_price'],
                context.user_data['address'],
                context.user_data.get('location_lat'),
                context.user_data.get('location_lng'),
                context.user_data['phone'],
                context.user_data['payment_method'],
                "screenshot_received",
                context.user_data['delivery_region'],
                context.user_data['delivery_cost']
            ))
            
            # Update product quantity
            cur.execute('''
                UPDATE products SET quantity = quantity - %s WHERE id = %s
            ''', (context.user_data['quantity'], context.user_data['selected_product']))
            
            conn.commit()
            cur.close()
            conn.close()
            
            # Delivery info for admin
            delivery_info = ""
            if context.user_data['delivery_region'] == "tashkent":
                delivery_info = "📍 Toshkent - BEPUL, Bugun yetkaziladi"
            else:
                delivery_info = f"📍 Boshqa viloyat - {context.user_data['delivery_cost']:,} UZS, 1-3 kun"
            
            # Notify admin
            admin_message = f"""
🆕 Yangi buyurtma!

📦 Mahsulot ID: {context.user_data['selected_product']}
👤 Foydalanuvchi: @{update.effective_user.username or 'Noma\'lum'}
📞 Telefon: {context.user_data['phone']}
🏠 Manzil: {context.user_data['address']}
{delivery_info}
💰 Miqdor: {context.user_data['quantity']} ta
💵 Mahsulot: {context.user_data['total_price']:,.0f} UZS
🚖 Yetkazish: {context.user_data['delivery_cost']:,.0f} UZS
💵 Jami: {context.user_data['total_with_delivery']:,.0f} UZS
💳 To'lov usuli: {context.user_data['payment_method']}

✅ Buyurtmani tasdiqlash uchun admin panelga kiring.
            """
            
            await context.bot.send_message(ADMIN_ID, admin_message)
            
            # Confirm to user
            delivery_time = "bugun" if context.user_data['delivery_region'] == "tashkent" else "1-3 kun ichida"
            await update.message.reply_text(f"""
✅ Sizning buyurtmangiz qabul qilindi!

📦 Buyurtmangiz tekshirilmoqda. Adminlar tez orada buyurtmangizni tasdiqlashadi.

⏰ Barchasi to'g'ri bo'lsa, buyurtmangiz {delivery_time} yetkazib beriladi.

🚖 Yetkazib berish: {context.user_data['delivery_cost']:,.0f} UZS

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
            delivery_info = "🚖 BEPUL" if order['delivery_cost'] == 0 else f"🚖 {order['delivery_cost']:,} UZS"
            
            message = f"""
📦 Buyurtma #{order['id']}
🏷 Mahsulot: {order['product_name']}
💰 Miqdor: {order['quantity']} ta
💵 Mahsulot: {order['total_price']:,.0f} UZS
{delivery_info}
💵 Jami: {order['total_price'] + order['delivery_cost']:,.0f} UZS
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

📍 Toshkent bo'ylab: BEPUL
⏰ Buyurtma qilingan kunning o'zida yetkazib beriladi

📍 Boshqa viloyatlar: 25,000 UZS
⏰ 1-3 kun ichida yetkazib beriladi

💰 Yetkazib berish to'lovi tovarni olayotganda amalga oshiriladi
    """
    await update.callback_query.message.reply_text(message)

# Admin functions (unchanged from previous version)
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
            status = "✅ Aktiv" if product.get('is_active', True) else "❌ Noaktiv"
            caption = f"🏷 {product['name']}\n💵 Narxi: {product['price']:,} UZS\n📦 Miqdori: {product['quantity']} ta\n📝 {product['description']}\n📊 {status}"
            
            keyboard = [[InlineKeyboardButton("🗑 O'chirish", callback_data=f"delete_product_{product['id']}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Try to use file_id first (more reliable)
            if product.get('photo_file_id'):
                try:
                    await update.callback_query.message.reply_photo(
                        photo=product['photo_file_id'],
                        caption=caption,
                        reply_markup=reply_markup
                    )
                    continue
                except Exception as e:
                    print(f"File ID failed: {e}")
            
            # Fallback to URL
            if product.get('photo_url'):
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

# Add product conversation (unchanged from previous version)
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
        photo_file_id = None
        
        if update.message.photo:
            # Get the photo file_id (this is permanent)
            photo_file_id = update.message.photo[-1].file_id
            
            # Also get URL for backup
            photo_file = await update.message.photo[-1].get_file()
            photo_url = photo_file.file_path
            
            print(f"Photo File ID: {photo_file_id}")
            print(f"Photo URL: {photo_url}")
            
        elif update.message.text and update.message.text.lower() == 'skip':
            photo_url = None
            photo_file_id = None
        else:
            await update.message.reply_text("❌ Iltimos, rasm yuboring yoki 'skip' deb yozing:")
            return PRODUCT_PHOTO
        
        # Save product to database
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO products (name, description, price, quantity, photo_url, photo_file_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (
            context.user_data['product_name'],
            context.user_data['product_desc'],
            context.user_data['product_price'],
            context.user_data['product_quantity'],
            photo_url,
            photo_file_id
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
            delivery_info = "📍 Toshkent (BEPUL)" if order['delivery_region'] == 'tashkent' else f"📍 Viloyat ({order['delivery_cost']:,} UZS)"
            
            message = f"""
📦 Buyurtma #{order['id']}
👤 Foydalanuvchi ID: {order['user_id']}
🏷 Mahsulot: {order['product_name']}
💰 Miqdor: {order['quantity']} ta
💵 Mahsulot: {order['total_price']:,.0f} UZS
{delivery_info}
💵 Jami: {order['total_price'] + order['delivery_cost']:,.0f} UZS
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
        cur.execute("SELECT user_id, delivery_region FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        
        # Update order status
        cur.execute("UPDATE orders SET status = 'confirmed' WHERE id = %s", (order_id,))
        conn.commit()
        cur.close()
        conn.close()
        
        # Notify user
        delivery_time = "bugun" if order['delivery_region'] == 'tashkent' else "1-3 kun ichida"
        try:
            await context.bot.send_message(
                order['user_id'],
                f"✅ Buyurtmangiz tasdiqlandi!\n\n"
                f"📦 Buyurtmangiz tayyorlanmoqda va {delivery_time} yetkazib beriladi.\n"
                f"⏰ Yetkazib berish: {delivery_time}"
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
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
            WAITING_LOCATION: [MessageHandler(filters.LOCATION, handle_location)],
            WAITING_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_address)],
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
