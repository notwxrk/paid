import os
import logging
import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from decimal import Decimal

import aiohttp
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    MessageHandler, 
    filters,
    CallbackQueryHandler,
    ConversationHandler
)
import asyncpg
from PIL import Image, ImageDraw, ImageFont
import io
from flask import Flask, render_template_string

# Log konfiguratsiyasi
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask app for uptimerobot
app = Flask(__name__)

@app.route('/')
def home():
    return render_template_string("Bot is running!")

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# Database configuration
DATABASE_URL = "postgresql://taksigo_user:t8vPyH7ZECp2wM8BNfg1wFrDDoz0DVIM@dpg-d49golemcj7s73efusj0-a/taksigo"

# Bot configuration
BOT_TOKEN = "8526778595:AAGP5ZINtNu6M2vYiZt2onz6bFRostthM8k"
ADMIN_ID = 7431672482
CHANNEL_USERNAME = "@goo_taksi"

# Conversation states
PHONE, MENU, BUY_CAR, FILL_BALANCE, WITHDRAW, SUPPORT = range(6)

# Car data
CARS = {
    "tico": {
        "name": "Tico",
        "daily_income": 5000,
        "duration": 100,
        "total_income": 500000,
        "price": 25000,
        "image": "https://i.ibb.co/bgjr7xNW/20251111-131622.png"
    },
    "damas": {
        "name": "Damas", 
        "daily_income": 10000,
        "duration": 100,
        "total_income": 1000000,
        "price": 75000,
        "image": "https://i.ibb.co/Xf3JgpGS/20251111-131901.png"
    },
    "nexia": {
        "name": "Nexia",
        "daily_income": 20000,
        "duration": 100,
        "total_income": 2000000,
        "price": 150000,
        "image": "https://i.ibb.co/tTVdQ70c/20251111-132004.png"
    },
    "cobalt": {
        "name": "Cobalt",
        "daily_income": 30000,
        "duration": 100,
        "total_income": 3000000,
        "price": 300000,
        "image": "https://i.ibb.co/3ywTRf7R/20251111-132135.png"
    },
    "gentra": {
        "name": "Gentra",
        "daily_income": 40000,
        "duration": 100,
        "total_income": 4000000,
        "price": 400000,
        "image": "https://i.ibb.co/9mc1RWkB/20251111-132318.png"
    },
    "malibu": {
        "name": "Malibu",
        "daily_income": 50000,
        "duration": 100,
        "total_income": 5000000,
        "price": 500000,
        "image": "https://i.ibb.co/Lzz0shFS/20251111-132601.png"
    }
}

# Database setup
async def init_db():
    logger.info("Database connection initialized")
    return await asyncpg.connect(DATABASE_URL)

async def create_tables():
    conn = await init_db()
    try:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                phone_number VARCHAR(20),
                balance DECIMAL DEFAULT 0,
                total_earned DECIMAL DEFAULT 0,
                referred_by BIGINT,
                created_at TIMESTAMP DEFAULT NOW(),
                last_bonus TIMESTAMP
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_cars (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                car_type VARCHAR(50),
                purchase_date TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount DECIMAL,
                type VARCHAR(20),
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                card_number VARCHAR(50),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id SERIAL PRIMARY KEY,
                referrer_id BIGINT,
                referred_id BIGINT,
                bonus_paid BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                FOREIGN KEY (referred_id) REFERENCES users(user_id)
            )
        ''')
        
        logger.info("Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"Error creating tables: {e}")
    finally:
        await conn.close()

# User management
async def get_user(user_id: int) -> Optional[dict]:
    conn = await init_db()
    try:
        user = await conn.fetchrow(
            'SELECT * FROM users WHERE user_id = $1', user_id
        )
        logger.info(f"User data retrieved for user_id: {user_id}")
        return dict(user) if user else None
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        return None
    finally:
        await conn.close()

async def create_user(user_id: int, phone_number: str, referred_by: int = None):
    conn = await init_db()
    try:
        await conn.execute(
            'INSERT INTO users (user_id, phone_number, referred_by) VALUES ($1, $2, $3)',
            user_id, phone_number, referred_by
        )
        
        # HAR BIR YANGI TAKLIF UCHUN BONUS
        if referred_by:
            # Faqat yangi foydalanuvchi uchun bonus beramiz
            existing_referral = await conn.fetchrow(
                'SELECT * FROM referrals WHERE referrer_id = $1 AND referred_id = $2',
                referred_by, user_id
            )
            
            if not existing_referral:
                await conn.execute(
                    'UPDATE users SET balance = balance + 1000 WHERE user_id = $1',
                    referred_by
                )
                await conn.execute(
                    'INSERT INTO referrals (referrer_id, referred_id, bonus_paid) VALUES ($1, $2, $3)',
                    referred_by, user_id, True
                )
                logger.info(f"Referral bonus paid: {referred_by} -> {user_id}")
        
        logger.info(f"New user created: {user_id}, phone: {phone_number}")
    except Exception as e:
        logger.error(f"Error creating user {user_id}: {e}")
    finally:
        await conn.close()

async def update_balance(user_id: int, amount: float):
    conn = await init_db()
    try:
        await conn.execute(
            'UPDATE users SET balance = balance + $1 WHERE user_id = $2',
            amount, user_id
        )
        logger.info(f"Balance updated for user {user_id}: {amount}")
    except Exception as e:
        logger.error(f"Error updating balance for user {user_id}: {e}")
    finally:
        await conn.close()

# Car management
async def get_user_cars(user_id: int) -> List[dict]:
    conn = await init_db()
    try:
        cars = await conn.fetch(
            'SELECT * FROM user_cars WHERE user_id = $1 AND is_active = TRUE',
            user_id
        )
        logger.info(f"Retrieved {len(cars)} cars for user {user_id}")
        return [dict(car) for car in cars]
    except Exception as e:
        logger.error(f"Error getting cars for user {user_id}: {e}")
        return []
    finally:
        await conn.close()

async def buy_car(user_id: int, car_type: str):
    car = CARS[car_type]
    conn = await init_db()
    try:
        # Check balance
        user = await get_user(user_id)
        if user['balance'] < car['price']:
            logger.warning(f"Insufficient balance for user {user_id}: {user['balance']} < {car['price']}")
            return False, "Not enough balance"
        
        # Deduct balance and add car
        await conn.execute(
            'UPDATE users SET balance = balance - $1 WHERE user_id = $2',
            car['price'], user_id
        )
        
        expires_at = datetime.now() + timedelta(days=car['duration'])
        await conn.execute(
            'INSERT INTO user_cars (user_id, car_type, expires_at) VALUES ($1, $2, $3)',
            user_id, car_type, expires_at
        )
        
        logger.info(f"Car purchased: {car_type} for user {user_id}")
        return True, "Car purchased successfully"
    except Exception as e:
        logger.error(f"Error buying car for user {user_id}: {e}")
        return False, "Error purchasing car"
    finally:
        await conn.close()

# Avtomatik daromad va vaqt hisoblash
async def calculate_and_update_income(user_id: int):
    """Mashinalardan avtomatik daromadni hisoblaydi va yangilaydi"""
    conn = await init_db()
    try:
        # Faqat aktiv va muddati o'tmagan mashinalarni olamiz
        cars = await conn.fetch(
            'SELECT * FROM user_cars WHERE user_id = $1 AND is_active = TRUE AND expires_at > NOW()',
            user_id
        )
        
        total_income = 0
        car_details = []
        
        for car in cars:
            car_data = CARS[car['car_type']]
            
            # Kunlik daromadni hisoblaymiz
            daily_income = car_data['daily_income']
            total_income += daily_income
            
            # Qolgan vaqtni hisoblaymiz
            time_left = car['expires_at'] - datetime.now()
            days_left = time_left.days
            hours_left = time_left.seconds // 3600
            
            car_details.append({
                'name': car_data['name'],
                'daily_income': daily_income,
                'days_left': days_left,
                'hours_left': hours_left
            })
        
        # Agar daromad bo'lsa, balansga qo'shamiz
        if total_income > 0:
            await conn.execute(
                'UPDATE users SET balance = balance + $1, total_earned = total_earned + $1 WHERE user_id = $2',
                total_income, user_id
            )
            logger.info(f"Auto income updated for user {user_id}: {total_income}")
        
        return total_income, car_details
        
    except Exception as e:
        logger.error(f"Error calculating income for user {user_id}: {e}")
        return 0, []
    finally:
        await conn.close()

# Channel check
async def check_channel_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        logger.info(f"Channel membership checked for {user_id}: {member.status}")
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking channel membership for {user_id}: {e}")
        return False

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"Start command received from user {user_id}")
    
    # Check referral
    referred_by = None
    if context.args:
        try:
            referred_by = int(context.args[0])
            logger.info(f"Referral detected: {referred_by} -> {user_id}")
        except:
            pass
    
    user = await get_user(user_id)
    
    if not user:
        # Check channel membership
        if not await check_channel_membership(user_id, context):
            keyboard = [
                [InlineKeyboardButton("📢 Kanalga a'zo bo'lish", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("✅ Tekshirish", callback_data="check_membership")]
            ]
            await update.message.reply_text(
                f"Botdan to'liq foydalanish uchun quyidagi kanalga a'zo bo'ling: {CHANNEL_USERNAME}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logger.info(f"User {user_id} not in channel, asking to join")
            return
    
    if not user:
        # Ask for phone number
        keyboard = [[KeyboardButton("📞 Telefon raqamimni yuborish", request_contact=True)]]
        await update.message.reply_text(
            "Assalomu alaykum! Goo Taksi botiga xush kelibsiz!\n\n"
            "Davom etish uchun telefon raqamingizni tasdiqlang:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        context.user_data['referred_by'] = referred_by
        logger.info(f"User {user_id} not registered, asking for phone")
        return PHONE
    
    await show_main_menu(update, context)
    return MENU

async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    logger.info(f"Membership check callback from user {user_id}")
    
    if await check_channel_membership(user_id, context):
        await query.edit_message_text("✅ Siz kanalga a'zo bo'lgansiz! Endi telefon raqamingizni tasdiqlashingiz mumkin.")
        
        keyboard = [[KeyboardButton("📞 Telefon raqamimni yuborish", request_contact=True)]]
        await context.bot.send_message(
            chat_id=user_id,
            text="Davom etish uchun telefon raqamingizni tasdiqlang:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        logger.info(f"User {user_id} passed channel check")
        return PHONE
    else:
        await query.answer("Siz hali kanalga a'zo bo'lmagansiz!", show_alert=True)
        logger.info(f"User {user_id} failed channel check")

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    phone_number = update.message.contact.phone_number
    logger.info(f"Phone received from user {user_id}: {phone_number}")
    
    # Check if Uzbekistan number
    if not phone_number.startswith('+998') and not phone_number.startswith('998'):
        await update.message.reply_text(
            "❌ Faqat O'zbekiston telefon raqamlari qabul qilinadi!\n"
            "Iltimos, +998 kodli raqamingizni yuboring.",
            reply_markup=ReplyKeyboardRemove()
        )
        logger.warning(f"Non-Uzbekistan phone number rejected: {phone_number}")
        return PHONE
    
    # Get referral from context
    referred_by = context.user_data.get('referred_by')
    
    await create_user(user_id, phone_number, referred_by)
    await update.message.reply_text(
        "✅ Telefon raqamingiz muvaffaqiyatli tasdiqlandi!",
        reply_markup=ReplyKeyboardRemove()
    )
    
    await show_main_menu(update, context)
    return MENU

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    # Avtomatik daromadni hisoblaymiz
    daily_income, car_details = await calculate_and_update_income(user_id)
    
    # Referral count
    conn = await init_db()
    try:
        referrals_count = await conn.fetchval(
            'SELECT COUNT(*) FROM referrals WHERE referrer_id = $1', user_id
        )
    except Exception as e:
        logger.error(f"Error getting referral count for user {user_id}: {e}")
        referrals_count = 0
    finally:
        await conn.close()
    
    keyboard = [
        ["🚖 Mashinalar", "🚘 Mening Mashinam"],
        ["💸 Hisobim", "📥 Hisobni To'ldirish"],
        ["👥 Referal", "🎁 Kunlik bonus"],
        ["💬 Qo'llab Quvvatlash"]
    ]
    
    text = (
        f"🏠 Asosiy menyu\n\n"
        f"💰 Balans: {user['balance']:,.0f} so'm\n"
        f"📈 Kunlik daromad: {daily_income:,.0f} so'm\n"
        f"👥 Referallar: {referrals_count} ta"
    )
    
    # Mashinalar vaqt qoldig'ini ko'rsatamiz
    if car_details:
        text += f"\n\n⏰ Mashinalar holati:"
        for car in car_details:
            text += f"\n🚗 {car['name']}: {car['days_left']} kun {car['hours_left']} soat qoldi"
    
    if update.message:
        await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    else:
        await update.callback_query.edit_message_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    
    logger.info(f"Main menu shown for user {user_id}")

# Car section
async def show_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Show cars requested by user {update.effective_user.id}")
    keyboard = [
        [InlineKeyboardButton("Tico", callback_data="car_tico")],
        [InlineKeyboardButton("Damas", callback_data="car_damas")],
        [InlineKeyboardButton("Nexia", callback_data="car_nexia")],
        [InlineKeyboardButton("Cobalt", callback_data="car_cobalt")],
        [InlineKeyboardButton("Gentra", callback_data="car_gentra")],
        [InlineKeyboardButton("Malibu", callback_data="car_malibu")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back_to_menu")]
    ]
    
    text = (
        "🚖 Mashinalar bo'limiga xush kelibsiz!\n\n"
        "Har bir tanlagan mashinangiz sizga kunlik foyda olib keladi.\n"
        "Quyidagi mashinalardan birini tanlang:"
    )
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_car_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    car_type = query.data.split('_')[1]
    car = CARS[car_type]
    logger.info(f"Car detail requested: {car_type} by user {query.from_user.id}")
    
    text = (
        f"🚗 {car['name']}\n\n"
        f"💰 Kunlik daromad: {car['daily_income']:,.0f} so'm\n"
        f"⏰ Ish muddati: {car['duration']} kun\n"
        f"🎯 Jami daromad: {car['total_income']:,.0f} so'm\n"
        f"💵 Narxi: {car['price']:,.0f} so'm"
    )
    
    keyboard = [
        [InlineKeyboardButton("🛒 Harid qilish", callback_data=f"buy_{car_type}")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back_to_cars")]
    ]
    
    # Send car image with caption
    await query.message.reply_photo(
        photo=car['image'],
        caption=text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await query.delete_message()

async def buy_car_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    car_type = query.data.split('_')[1]
    logger.info(f"Car purchase attempted: {car_type} by user {user_id}")
    
    success, message = await buy_car(user_id, car_type)
    
    if success:
        await query.answer("✅ Mashina muvaffaqiyatli sotib olindi!", show_alert=True)
        await show_main_menu(update, context)
    else:
        await query.answer(f"❌ {message}", show_alert=True)

# My Cars section
async def show_my_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"My cars requested by user {user_id}")
    
    # Yangi funksiya orqali ma'lumotlarni olamiz
    daily_income, car_details = await calculate_and_update_income(user_id)
    
    if not car_details:
        await update.message.reply_text("🚫 Sizda hali mashinalar yo'q")
        return
    
    text = "🚘 Mening mashinalarim:\n\n"
    for car in car_details:
        text += (
            f"🚗 {car['name']}\n"
            f"💰 Kunlik: {car['daily_income']:,.0f} so'm\n"
            f"⏰ Qolgan vaqt: {car['days_left']} kun {car['hours_left']} soat\n\n"
        )
    
    text += f"📈 Jami kunlik daromad: {daily_income:,.0f} so'm"
    
    await update.message.reply_text(text)

# Balance section - PUL YECHISH KNOPKASI BARCHA USERLARGA KO'RINADI
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    cars = await get_user_cars(user_id)
    
    has_cars = len(cars) > 0
    can_withdraw = has_cars and user['balance'] >= 25000
    
    text = (
        f"💸 Hisobim\n\n"
        f"💰 Joriy balans: {user['balance']:,.0f} so'm\n"
        f"📈 Umumiy daromad: {user['total_earned']:,.0f} so'm\n"
        f"🚗 Faol mashinalar: {len(cars)} ta"
    )
    
    # PUL YECHISH KNOPKASI BARCHA USERLARGA KO'RINADI
    keyboard = [[InlineKeyboardButton("💳 Pul yechish", callback_data="withdraw")]]
    
    if can_withdraw:
        text += f"\n\n💳 Minimal pul yechish: 25,000 so'm\n📉 Komissiya: 15%"
    else:
        if not has_cars:
            text += "\n\n⚠️ Pul yechish uchun kamida 1 ta mashina sotib olishingiz kerak!"
        elif user['balance'] < 25000:
            text += f"\n\n⚠️ Pul yechish uchun balansingiz kamida 25,000 so'm bo'lishi kerak!"
    
    # Message turini tekshirish
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    logger.info(f"Balance shown for user {user_id}")

async def withdraw_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = await get_user(user_id)
    
    # Tekshiramiz, mashina bormi
    cars = await get_user_cars(user_id)
    if not cars:
        await query.answer("❌ Pul yechish uchun mashina sotib olishingiz kerak!", show_alert=True)
        return
    
    # Tekshiramiz, minimal miqdor bormi
    if user['balance'] < 25000:
        await query.answer("❌ Balansingiz 25,000 so'mdan kam!", show_alert=True)
        return
    
    context.user_data['withdraw_amount'] = float(user['balance'])  # Decimal ni float ga o'tkazamiz
    
    # Decimal muammosini hal qilish
    balance_float = float(user['balance'])
    commission = balance_float * 0.15
    final_amount = balance_float - commission
    
    text = (
        f"💳 Pul yechish\n\n"
        f"💰 Mavjud balans: {user['balance']:,.0f} so'm\n"
        f"💸 Yechish miqdori: {user['balance']:,.0f} so'm\n"
        f"📉 Komissiya (15%): {commission:,.0f} so'm\n"
        f"🎯 Olinadigan summa: {final_amount:,.0f} so'm\n\n"
        f"UzCard/Humo kartangiz raqamini yuboring:"
    )
    
    await query.message.reply_text(text)
    await query.answer()
    logger.info(f"Withdrawal initiated by user {user_id}: {user['balance']}")
    return WITHDRAW

async def handle_withdraw_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    card_number = update.message.text
    amount = context.user_data['withdraw_amount']
    
    # Tekshiramiz, mashina bormi
    cars = await get_user_cars(user_id)
    if not cars:
        await update.message.reply_text("❌ Pul yechish uchun mashina sotib olishingiz kerak!")
        await show_main_menu(update, context)
        return
    
    # Tekshiramiz, minimal miqdor bormi
    if amount < 25000:
        await update.message.reply_text("❌ Balansingiz 25,000 so'mdan kam!")
        await show_main_menu(update, context)
        return
    
    # Save withdrawal request
    conn = await init_db()
    try:
        await conn.execute(
            'INSERT INTO transactions (user_id, amount, type, card_number) VALUES ($1, $2, $3, $4)',
            user_id, amount, 'withdraw', card_number
        )
        
        # Notify admin
        await context.bot.send_message(
            ADMIN_ID,
            f"🔄 Yangi pul yechish so'rovi:\n\n"
            f"👤 User ID: {user_id}\n"
            f"📞 Tel: {(await get_user(user_id))['phone_number']}\n"
            f"💳 Karta: {card_number}\n"
            f"💰 Miqdor: {amount:,.0f} so'm\n"
            f"📉 Komissiya (15%): {amount * 0.15:,.0f} so'm\n"
            f"🎯 Olinadigan: {amount * 0.85:,.0f} so'm"
        )
        
        logger.info(f"Withdrawal request submitted by user {user_id}: {amount} to card {card_number}")
    except Exception as e:
        logger.error(f"Error processing withdrawal for user {user_id}: {e}")
    finally:
        await conn.close()
    
    await update.message.reply_text(
        "✅ Pul yechish so'rovingiz qabul qilindi!\n"
        "Admin tez orada ko'rib chiqadi."
    )
    
    await show_main_menu(update, context)
    return MENU

# Fill balance section
async def fill_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📥 Hisobni to'ldirish\n\n"
        "Hisobingizni to'ldirish uchun admin bilan bog'laning:\n"
        f"👤 Admin: @admin\n\n"
        "To'lov qilgach, admin bilan bog'lanib, to'lov chekini yuboring."
    )
    
    await update.message.reply_text(text)

# Referral section - HAR BIR YANGI TAKLIF UCHUN BONUS
async def show_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = await init_db()
    try:
        referrals_count = await conn.fetchval(
            'SELECT COUNT(*) FROM referrals WHERE referrer_id = $1', user_id
        )
        
        # Faqat bonus to'langan referallarni hisoblaymiz
        successful_referrals = await conn.fetchval(
            'SELECT COUNT(*) FROM referrals WHERE referrer_id = $1 AND bonus_paid = TRUE',
            user_id
        )
        
        referral_bonus = successful_referrals * 1000  # Har bir referal uchun 1000 so'm
        
    except Exception as e:
        logger.error(f"Error getting referral data for user {user_id}: {e}")
        referrals_count = 0
        referral_bonus = 0
    finally:
        await conn.close()
    
    referral_link = f"https://t.me/{(await context.bot.get_me()).username}?start={user_id}"
    
    text = (
        f"👥 Referal tizimi\n\n"
        f"📊 Jami takliflar: {referrals_count} ta\n"
        f"✅ Bonus olinganlar: {successful_referrals} ta\n"
        f"💰 Referal bonus: {referral_bonus:,.0f} so'm\n\n"
        f"🔗 Sizning referal havolangiz:\n`{referral_link}`\n\n"
        f"🎯 Taklif qilish shartlari:\n"
        f"• Har bir yangi taklif uchun: 1,000 so'm\n"
        f"• Do'stingiz ro'yxatdan o'tganda bonus olasiz"
    )
    
    await update.message.reply_text(text)

# Daily bonus
async def daily_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    now = datetime.now()
    
    if user['last_bonus'] and (now - user['last_bonus']).total_seconds() < 86400:
        next_bonus = user['last_bonus'] + timedelta(days=1)
        time_left = next_bonus - now
        
        hours = int(time_left.total_seconds() // 3600)
        minutes = int((time_left.total_seconds() % 3600) // 60)
        
        await update.message.reply_text(
            f"⏰ Siz bonusni allaqachon olgansiz!\n"
            f"Keyingi bonus: {hours} soat {minutes} daqiqadan keyin"
        )
        return
    
    bonus_amount = random.randint(700, 1000)
    
    conn = await init_db()
    try:
        await conn.execute(
            'UPDATE users SET balance = balance + $1, last_bonus = $2 WHERE user_id = $3',
            bonus_amount, now, user_id
        )
        logger.info(f"Daily bonus given to user {user_id}: {bonus_amount}")
    except Exception as e:
        logger.error(f"Error giving daily bonus to user {user_id}: {e}")
    finally:
        await conn.close()
    
    await update.message.reply_text(
        f"🎉 Tabriklaymiz! Kunlik bonus:\n"
        f"💰 {bonus_amount} so'm\n\n"
        f"Keyingi bonus: 24 soatdan keyin"
    )

# Support
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💬 Qo'llab Quvvatlash\n\n"
        "Savol yoki takliflaringiz bo'lsa, admin bilan bog'laning:\n"
        f"👤 Admin: @admin\n\n"
        "Yordam kerak bo'lsa, murojaat qiling!"
    )
    
    await update.message.reply_text(text)

# Back handlers
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)
    return MENU

async def back_to_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_cars(update, context)

# Admin functions
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    keyboard = [
        ["💰 Hisob to'ldirish", "📊 Statistika"],
        ["🔄 So'rovlar", "🔙 Asosiy menyu"]
    ]
    
    await update.message.reply_text(
        "👤 Admin panel",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def handle_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    text = update.message.text
    
    if text == "💰 Hisob to'ldirish":
        await update.message.reply_text(
            "Foydalanuvchi hisobini to'ldirish uchun quyidagi formatda yozing:\n"
            "`/fill user_id amount`\n\n"
            "Misol: `/fill 123456789 50000`"
        )
    
    elif text == "🔄 So'rovlar":
        await show_withdraw_requests(update, context)
    
    elif text == "📊 Statistika":
        await show_stats(update, context)
    
    elif text == "🔙 Asosiy menyu":
        await show_main_menu(update, context)

async def fill_user_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        user_id = int(context.args[0])
        amount = float(context.args[1])
        
        await update_balance(user_id, amount)
        
        # Notify user
        await context.bot.send_message(
            user_id,
            f"✅ Hisobingiz to'ldirildi!\n"
            f"💰 Miqdor: {amount:,.0f} so'm\n"
            f"💳 Yangi balans: {(await get_user(user_id))['balance']:,.0f} so'm"
        )
        
        await update.message.reply_text("✅ Hisob muvaffaqiyatli to'ldirildi!")
        logger.info(f"Admin filled balance for user {user_id}: {amount}")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {e}")
        logger.error(f"Error in admin fill balance: {e}")

async def show_withdraw_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = await init_db()
    try:
        requests = await conn.fetch(
            'SELECT * FROM transactions WHERE type = $1 AND status = $2 ORDER BY created_at',
            'withdraw', 'pending'
        )
        
        if not requests:
            await update.message.reply_text("🔄 Hozircha so'rovlar yo'q")
            return
        
        text = "🔄 Pul yechish so'rovlari:\n\n"
        for req in requests:
            user = await get_user(req['user_id'])
            commission = float(req['amount']) * 0.15  # Decimal to float
            final_amount = float(req['amount']) - commission
            
            text += (
                f"🆔 So'rov ID: {req['id']}\n"
                f"👤 User: {req['user_id']}\n"
                f"📞 Tel: {user['phone_number']}\n"
                f"💳 Karta: {req['card_number']}\n"
                f"💰 Miqdor: {req['amount']:,.0f} so'm\n"
                f"📉 Komissiya: {commission:,.0f} so'm\n"
                f"🎯 O'tkazish: {final_amount:,.0f} so'm\n"
                f"⏰ Vaqt: {req['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
                f"────────────────────\n"
            )
        
        text += "\nTasdiqlash: `/approve id`\nRad etish: `/reject id`"
        
        await update.message.reply_text(text)
        
    except Exception as e:
        logger.error(f"Error showing withdraw requests: {e}")
        await update.message.reply_text(f"❌ Xato: {e}")
    finally:
        await conn.close()

async def handle_withdraw_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        action = context.args[0]
        request_id = int(context.args[1])
        
        conn = await init_db()
        try:
            request = await conn.fetchrow(
                'SELECT * FROM transactions WHERE id = $1', request_id
            )
            
            if not request:
                await update.message.reply_text("❌ So'rov topilmadi")
                return
            
            if action == 'approve':
                await conn.execute(
                    'UPDATE transactions SET status = $1 WHERE id = $2',
                    'approved', request_id
                )
                
                # Deduct balance from user (with commission)
                commission = float(request['amount']) * 0.15
                amount_to_deduct = float(request['amount'])
                
                await conn.execute(
                    'UPDATE users SET balance = balance - $1 WHERE user_id = $2',
                    amount_to_deduct, request['user_id']
                )
                
                # Notify user
                await context.bot.send_message(
                    request['user_id'],
                    f"✅ Pul yechish so'rovingiz tasdiqlandi!\n"
                    f"💰 {float(request['amount']) - commission:,.0f} so'm kartangizga o'tkazildi\n"
                    f"📉 Komissiya (15%): {commission:,.0f} so'm"
                )
                
                await update.message.reply_text("✅ So'rov tasdiqlandi!")
                logger.info(f"Withdrawal approved: {request_id} for user {request['user_id']}")
                
            elif action == 'reject':
                await conn.execute(
                    'UPDATE transactions SET status = $1 WHERE id = $2',
                    'rejected', request_id
                )
                
                # Notify user
                await context.bot.send_message(
                    request['user_id'],
                    f"❌ Pul yechish so'rovingiz rad etildi!\n"
                    f"Iltimos, admin bilan bog'laning."
                )
                
                await update.message.reply_text("❌ So'rov rad etildi!")
                logger.info(f"Withdrawal rejected: {request_id} for user {request['user_id']}")
                
        finally:
            await conn.close()
            
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {e}")
        logger.error(f"Error in admin withdraw action: {e}")

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = await init_db()
    try:
        total_users = await conn.fetchval('SELECT COUNT(*) FROM users')
        total_balance = await conn.fetchval('SELECT COALESCE(SUM(balance), 0) FROM users')
        total_cars = await conn.fetchval('SELECT COUNT(*) FROM user_cars WHERE is_active = TRUE')
        total_withdrawals = await conn.fetchval(
            'SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type = $1 AND status = $2',
            'withdraw', 'approved'
        )
        
        text = (
            f"📊 Bot statistikasi:\n\n"
            f"👥 Jami foydalanuvchilar: {total_users}\n"
            f"💰 Jami balans: {total_balance:,.0f} so'm\n"
            f"🚗 Faol mashinalar: {total_cars} ta\n"
            f"💸 Yechilgan pullar: {total_withdrawals:,.0f} so'm"
        )
        
        await update.message.reply_text(text)
        logger.info("Admin viewed statistics")
        
    except Exception as e:
        logger.error(f"Error showing statistics: {e}")
        await update.message.reply_text(f"❌ Xato: {e}")
    finally:
        await conn.close()

# Main function
def main():
    logger.info("Starting bot initialization...")
    
    # Create tables
    asyncio.get_event_loop().run_until_complete(create_tables())
    
    # Start Flask server in background for uptimerobot
    import threading
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask server started for uptimerobot")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler for user registration
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PHONE: [
                MessageHandler(filters.CONTACT, handle_phone),
                CallbackQueryHandler(check_membership_callback, pattern="^check_membership$")
            ],
            MENU: [
                MessageHandler(filters.Regex("^🚖 Mashinalar$"), show_cars),
                MessageHandler(filters.Regex("^🚘 Mening Mashinam$"), show_my_cars),
                MessageHandler(filters.Regex("^💸 Hisobim$"), show_balance),
                MessageHandler(filters.Regex("^📥 Hisobni To'ldirish$"), fill_balance),
                MessageHandler(filters.Regex("^👥 Referal$"), show_referral),
                MessageHandler(filters.Regex("^🎁 Kunlik bonus$"), daily_bonus),
                MessageHandler(filters.Regex("^💬 Qo'llab Quvvatlash$"), support),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(show_car_detail, pattern="^car_"),
                CallbackQueryHandler(buy_car_handler, pattern="^buy_"),
                CallbackQueryHandler(back_to_cars, pattern="^back_to_cars$"),
                CallbackQueryHandler(withdraw_money, pattern="^withdraw$"),
            ],
            WITHDRAW: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_withdraw_card)
            ]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))
    
    # Admin handlers
    application.add_handler(CommandHandler("admin", admin_menu))
    application.add_handler(CommandHandler("fill", fill_user_balance))
    application.add_handler(CommandHandler("approve", handle_withdraw_action))
    application.add_handler(CommandHandler("reject", handle_withdraw_action))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_admin_commands))
    
    # Start the bot
    logger.info("Bot starting polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
