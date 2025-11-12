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
DATABASE_URL = "postgresql://mytaxi_user:oq0x7wzTfgKRRmc9k1PAkF1KxrNqxSNC@dpg-d49un63ipnbc739a95b0-a/mytaxi"

# Bot configuration
BOT_TOKEN = "8526778595:AAGP5ZINtNu6M2vYiZt2onz6bFRostthM8k"
ADMIN_ID = 7431672482
CHANNEL_USERNAME = "@gootaksi"
GROUP_USERNAME = "@gootaksi_chat"

# Conversation states
PHONE, CHECK_SUBSCRIPTION, MENU, BUY_CAR, FILL_BALANCE, WITHDRAW_AMOUNT, WITHDRAW_CARD, SUPPORT = range(8)

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
                last_bonus TIMESTAMP,
                last_income TIMESTAMP,
                has_received_tico_bonus BOOLEAN DEFAULT FALSE,
                referral_bonus_earned DECIMAL DEFAULT 0
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
                last_income_date TIMESTAMP,
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

# YANGI: Kanal va guruh a'zoligini tekshirish
async def check_channel_and_group_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        # Kanalni tekshirish
        channel_member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        channel_ok = channel_member.status in ['member', 'administrator', 'creator']
        
        # Guruhni tekshirish
        group_member = await context.bot.get_chat_member(GROUP_USERNAME, user_id)
        group_ok = group_member.status in ['member', 'administrator', 'creator']
        
        logger.info(f"Membership checked for {user_id}: channel={channel_ok}, group={group_ok}")
        return channel_ok and group_ok
    except Exception as e:
        logger.error(f"Error checking membership for {user_id}: {e}")
        return False

# YANGI: Majburiy obuna tekshiruvi
async def check_subscription_required(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    return not await check_channel_and_group_membership(user_id, context)

# YANGI: Referal bonus berish funksiyasi
async def give_referral_bonus(referrer_id: int, referred_id: int, context: ContextTypes.DEFAULT_TYPE):
    conn = await init_db()
    try:
        # Tekshiramiz, oldin bonus berilganmi
        existing_referral = await conn.fetchrow(
            'SELECT * FROM referrals WHERE referrer_id = $1 AND referred_id = $2',
            referrer_id, referred_id
        )
        
        if existing_referral:
            logger.info(f"Referral bonus already paid: {referrer_id} -> {referred_id}")
            return
        
        # 500 so'm bonus
        await conn.execute(
            'UPDATE users SET balance = balance + 500, referral_bonus_earned = referral_bonus_earned + 500 WHERE user_id = $1',
            referrer_id
        )
        
        await conn.execute(
            'INSERT INTO referrals (referrer_id, referred_id, bonus_paid) VALUES ($1, $2, $3)',
            referrer_id, referred_id, True
        )
        
        # Foydalanuvchiga xabar
        try:
            await context.bot.send_message(
                referrer_id,
                "🎉 Tabriklaymiz! Muvaffaqiyatli taklif qildingiz!\n\n"
                "💰 +500 so'm bonus qo'shildi!\n"
                "👥 Do'stingiz botga muvaffaqiyatli qo'shildi!"
            )
        except Exception as e:
            logger.error(f"Error sending bonus message to {referrer_id}: {e}")
        
        # YANGI: 12 ta referal tekshirish va Tico bonus
        referrals_count = await conn.fetchval(
            'SELECT COUNT(*) FROM referrals WHERE referrer_id = $1', 
            referrer_id
        )
        
        user_data = await get_user(referrer_id)
        if referrals_count >= 12 and not user_data['has_received_tico_bonus']:
            # Tico mashinasini sovg'a qilamiz
            expires_at = datetime.now() + timedelta(days=CARS['tico']['duration'])
            await conn.execute(
                'INSERT INTO user_cars (user_id, car_type, expires_at, last_income_date) VALUES ($1, $2, $3, $4)',
                referrer_id, 'tico', expires_at, datetime.now()
            )
            
            await conn.execute(
                'UPDATE users SET has_received_tico_bonus = TRUE WHERE user_id = $1',
                referrer_id
            )
            
            # Foydalanuvchiga xabar
            try:
                await context.bot.send_message(
                    referrer_id,
                    "🎁 Ajoyib yangilik! 🎉\n\n"
                    "Siz 12 ta do'stingizni taklif qilganingiz uchun BEPUL Tico mashinasi sovg'a qilindi! 🚗\n\n"
                    "Mashina avtomatik ravishda hisobingizga qo'shildi va kunlik daromad olishni boshladi!"
                )
            except Exception as e:
                logger.error(f"Error sending tico bonus message to {referrer_id}: {e}")
            
            logger.info(f"Tico bonus given to user {referrer_id} for 12 referrals")
        
        logger.info(f"Referral bonus paid: {referrer_id} -> {referred_id}: 500 so'm")
        
    except Exception as e:
        logger.error(f"Error giving referral bonus: {e}")
    finally:
        await conn.close()

async def create_user(user_id: int, phone_number: str, referred_by: int = None, context: ContextTypes.DEFAULT_TYPE = None):
    conn = await init_db()
    try:
        await conn.execute(
            'INSERT INTO users (user_id, phone_number, referred_by) VALUES ($1, $2, $3)',
            user_id, phone_number, referred_by
        )
        
        # YANGI: Referal bonus berish
        if referred_by and context:
            await give_referral_bonus(referred_by, user_id, context)
        
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
        # Check balance - To'liq tekshirish
        user = await get_user(user_id)
        if float(user['balance']) < car['price']:
            logger.warning(f"Insufficient balance for user {user_id}: {user['balance']} < {car['price']}")
            return False, "Not enough balance"
        
        # Balansni to'g'ri ayiramiz
        await conn.execute(
            'UPDATE users SET balance = balance - $1 WHERE user_id = $2',
            car['price'], user_id
        )
        
        expires_at = datetime.now() + timedelta(days=car['duration'])
        await conn.execute(
            'INSERT INTO user_cars (user_id, car_type, expires_at, last_income_date) VALUES ($1, $2, $3, $4)',
            user_id, car_type, expires_at, datetime.now()
        )
        
        logger.info(f"Car purchased: {car_type} for user {user_id}")
        return True, "Car purchased successfully"
    except Exception as e:
        logger.error(f"Error buying car for user {user_id}: {e}")
        return False, "Error purchasing car"
    finally:
        await conn.close()

# YANGI: Daromadni hisoblash funksiyasi (24 soatdan keyin)
async def calculate_and_update_income(user_id: int):
    """Mashinalardan avtomatik daromadni hisoblaydi (24 soatdan keyin)"""
    conn = await init_db()
    try:
        # Barcha mashinalarni olamiz
        cars = await conn.fetch(
            '''SELECT * FROM user_cars 
               WHERE user_id = $1 AND is_active = TRUE 
               AND expires_at > NOW()''',
            user_id
        )
        
        total_income = 0
        car_details = []
        notifications = []
        
        for car in cars:
            car_data = CARS[car['car_type']]
            
            # 24 soat o'tganini tekshiramiz
            if car['last_income_date'] and (datetime.now() - car['last_income_date']).total_seconds() >= 86400:
                # Kunlik daromadni hisoblaymiz
                daily_income = car_data['daily_income']
                total_income += daily_income
                
                # last_income_date ni yangilaymiz
                await conn.execute(
                    'UPDATE user_cars SET last_income_date = NOW() WHERE id = $1',
                    car['id']
                )
                notifications.append(f"🎉 {car_data['name']} dan: {daily_income:,.0f} so'm")
            
            # Qolgan vaqtni hisoblaymiz
            time_left = car['expires_at'] - datetime.now()
            days_left = time_left.days
            hours_left = time_left.seconds // 3600
            
            # Keyingi daromad vaqtini hisoblaymiz
            next_income_time = car['last_income_date'] + timedelta(hours=24) if car['last_income_date'] else datetime.now() + timedelta(hours=24)
            time_until_next_income = next_income_time - datetime.now()
            
            if time_until_next_income.total_seconds() > 0:
                hours_until = int(time_until_next_income.total_seconds() // 3600)
                minutes_until = int((time_until_next_income.total_seconds() % 3600) // 60)
                next_income_str = f"{hours_until} soat {minutes_until} daqiqa"
            else:
                next_income_str = "Hozir"
            
            car_details.append({
                'name': car_data['name'],
                'daily_income': car_data['daily_income'],
                'days_left': days_left,
                'hours_left': hours_left,
                'next_income': next_income_str
            })
        
        # Agar daromad bo'lsa, balansga qo'shamiz
        if total_income > 0:
            await conn.execute(
                'UPDATE users SET balance = balance + $1, total_earned = total_earned + $1 WHERE user_id = $2',
                total_income, user_id
            )
            
            logger.info(f"Auto income updated for user {user_id}: {total_income}")
        
        # Keyingi daromad vaqtini hisoblaymiz
        next_income_time = None
        for car in cars:
            if car['last_income_date']:
                car_next_income = car['last_income_date'] + timedelta(hours=24)
                if next_income_time is None or car_next_income < next_income_time:
                    next_income_time = car_next_income
        
        return total_income, car_details, notifications, next_income_time
        
    except Exception as e:
        logger.error(f"Error calculating income for user {user_id}: {e}")
        return 0, [], [], None
    finally:
        await conn.close()

# Start command - YANGI: AVVAL TELEFON, KEYIN KANAL
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
    
    # YANGI: Agar user mavjud bo'lsa, kanal tekshirish
    if user:
        if await check_subscription_required(user_id, context):
            await ask_for_subscription(update, context)
            return CHECK_SUBSCRIPTION
        else:
            await show_main_menu(update, context)
            return MENU
    
    # Agar user mavjud bo'lmasa, telefon so'rash
    keyboard = [[KeyboardButton("📞 Telefon raqamimni yuborish", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    if update.message:
        await update.message.reply_text(
            "Assalomu alaykum! Goo Taksi botiga xush kelibsiz!\n\n"
            "Botdan foydalanish uchun avval telefon raqamingizni tasdiqlang:",
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.message.reply_text(
            "Assalomu alaykum! Goo Taksi botiga xush kelibsiz!\n\n"
            "Botdan foydalanish uchun avval telefon raqamingizni tasdiqlang:",
            reply_markup=reply_markup
        )
        
    context.user_data['referred_by'] = referred_by
    logger.info(f"User {user_id} not registered, asking for phone")
    return PHONE

# YANGI: Kanalga a'zo bo'lishni so'rash funksiyasi
async def ask_for_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📢 Kanalga a'zo bo'lish", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
        [InlineKeyboardButton("💬 Guruhga a'zo bo'lish", url=f"https://t.me/{GROUP_USERNAME[1:]}")],
        [InlineKeyboardButton("✅ Tekshirish", callback_data="check_membership")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(
            f"❌ Kechirasiz, botimizdan foydalanish uchun ushbu kanallarga obuna bo'lishingiz kerak:\n\n"
            f"📢 Kanal: {CHANNEL_USERNAME}\n"
            f"💬 Guruh: {GROUP_USERNAME}\n\n"
            f"Iltimos, kanallarga a'zo bo'ling va 'Tekshirish' tugmasini bosing.",
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.edit_message_text(
            f"❌ Kechirasiz, botimizdan foydalanish uchun ushbu kanallarga obuna bo'lishingiz kerak:\n\n"
            f"📢 Kanal: {CHANNEL_USERNAME}\n"
            f"💬 Guruh: {GROUP_USERNAME}\n\n"
            f"Iltimos, kanallarga a'zo bo'ling va 'Tekshirish' tugmasini bosing.",
            reply_markup=reply_markup
        )

async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    logger.info(f"Membership check callback from user {user_id}")
    
    if await check_channel_and_group_membership(user_id, context):
        await query.edit_message_text("✅ Siz kanal va guruhga a'zo bo'lgansiz! Endi botdan to'liq foydalanishingiz mumkin iltimos /start bosing.")
        await show_main_menu(update, context)
        return MENU
    else:
        await query.answer("Siz hali kanal yoki guruhga a'zo bo'lmagansiz!", show_alert=True)
        logger.info(f"User {user_id} failed channel/group check")

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if update.message.contact:
        phone_number = update.message.contact.phone_number
    else:
        await update.message.reply_text("❌ Iltimos, telefon raqamingizni 'Telefon raqamimni yuborish' tugmasi orqali yuboring.")
        return PHONE
    
    logger.info(f"Phone received from user {user_id}: {phone_number}")
    
    # Check if Uzbekistan number
    if not phone_number.startswith('+998') and not phone_number.startswith('998'):
        await update.message.reply_text(
            "❌ Faqat O'zbekiston telefon raqamlari qabul qilinadi!\n"
            "Iltimos, +998 kodli hisobingizdan yuboring.",
            reply_markup=ReplyKeyboardRemove()
        )
        logger.warning(f"Non-Uzbekistan phone number rejected: {phone_number}")
        return PHONE
    
    # Get referral from context
    referred_by = context.user_data.get('referred_by')
    
    # YANGI: Context bilan create_user ni chaqiramiz
    await create_user(user_id, phone_number, referred_by, context)
    await update.message.reply_text(
        "✅ Telefon raqamingiz muvaffaqiyatli tasdiqlandi!\n\n"
        "Endi botdan to'liq foydalanish uchun quyidagi kanal va guruhga a'zo bo'ling:",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # YANGI: Telefon tasdiqlangandan keyin kanal so'rash
    await ask_for_subscription(update, context)
    return CHECK_SUBSCRIPTION

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # YANGI: Har doim kanal a'zoligini tekshirish
    if await check_subscription_required(user_id, context):
        await ask_for_subscription(update, context)
        return CHECK_SUBSCRIPTION
    
    user = await get_user(user_id)
    
    # Avtomatik daromadni hisoblaymiz (24 soatdan keyin)
    daily_income, car_details, notifications, next_income_time = await calculate_and_update_income(user_id)
    
    # Referral count
    conn = await init_db()
    try:
        referrals_count = await conn.fetchval(
            'SELECT COUNT(*) FROM referrals WHERE referrer_id = $1', user_id
        )
        
        # YANGI: 12 ta referal tekshirish
        if referrals_count >= 12 and not user['has_received_tico_bonus']:
            # Tico mashinasini sovg'a qilamiz
            expires_at = datetime.now() + timedelta(days=CARS['tico']['duration'])
            await conn.execute(
                'INSERT INTO user_cars (user_id, car_type, expires_at, last_income_date) VALUES ($1, $2, $3, $4)',
                user_id, 'tico', expires_at, datetime.now()
            )
            
            await conn.execute(
                'UPDATE users SET has_received_tico_bonus = TRUE WHERE user_id = $1',
                user_id
            )
            
            notifications.append("🎁 Siz 12 ta do'stingizni taklif qilganingiz uchun BEPUL Tico mashinasi sovg'a qilindi! 🚗")
            logger.info(f"Tico bonus given to user {user_id} for 12 referrals")
            
    except Exception as e:
        logger.error(f"Error getting referral data for user {user_id}: {e}")
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
    
    # Notifikatsiyalarni qo'shamiz
    if notifications:
        text += f"\n\n{' '.join(notifications)}"
    
    # Keyingi daromad vaqtini ko'rsatamiz
    if next_income_time:
        time_left = next_income_time - datetime.now()
        if time_left.total_seconds() > 0:
            hours_left = int(time_left.total_seconds() // 3600)
            minutes_left = int((time_left.total_seconds() % 3600) // 60)
            text += f"\n\n⏰ Keyingi daromad: {hours_left} soat {minutes_left} daqiqadan keyin"
    
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

# YANGI: Har bir command uchun obuna tekshirish decorator
def check_subscription(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if await check_subscription_required(user_id, context):
            await ask_for_subscription(update, context)
            return CHECK_SUBSCRIPTION
        return await func(update, context)
    return wrapper

# Car section
@check_subscription
async def show_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Show cars requested by user {update.effective_user.id}")
    keyboard = [
        [InlineKeyboardButton("Tico", callback_data="car_tico")],
        [InlineKeyboardButton("Damas", callback_data="car_damas")],
        [InlineKeyboardButton("Nexia", callback_data="car_nexia")],
        [InlineKeyboardButton("Cobalt", callback_data="car_cobalt")],
        [InlineKeyboardButton("Gentra", callback_data="car_gentra")],
        [InlineKeyboardButton("Malibu", callback_data="car_malibu")]
    ]
    
    text = (
        "🚖 Mashinalar bo'limiga xush kelibsiz!\n\n"
        "Har bir tanlagan mashinangiz sizga kunlik foyda olib keladi. Bu qanday ishlaydi ? siz mashina harid qilganingizda mashina darhol ish boshlaydi va sizga kunlik foyda olib keladi.\n"
        "Quyidagi mashinalardan birini tanlang:"
    )
    
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

@check_subscription
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
        [InlineKeyboardButton("🛒 Harid qilish", callback_data=f"buy_{car_type}")]
    ]
    
    # Send car image with caption
    await query.message.reply_photo(
        photo=car['image'],
        caption=text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await query.delete_message()

@check_subscription
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
@check_subscription
async def show_my_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"My cars requested by user {user_id}")
    
    cars = await get_user_cars(user_id)
    
    if not cars:
        await update.message.reply_text("🚫 Sizda hali mashinalar yo'q")
        return
    
    text = "🚘 Mening mashinalarim:\n\n"
    for car in cars:
        car_data = CARS[car['car_type']]
        
        # Qolgan vaqtni hisoblaymiz
        time_left = car['expires_at'] - datetime.now()
        days_left = time_left.days
        hours_left = time_left.seconds // 3600
        
        # Keyingi daromad vaqtini hisoblaymiz
        next_income_time = car['last_income_date'] + timedelta(hours=24) if car['last_income_date'] else datetime.now() + timedelta(hours=24)
        time_until_next_income = next_income_time - datetime.now()
        
        if time_until_next_income.total_seconds() > 0:
            hours_until = int(time_until_next_income.total_seconds() // 3600)
            minutes_until = int((time_until_next_income.total_seconds() % 3600) // 60)
            next_income_str = f"{hours_until} soat {minutes_until} daqiqa"
        else:
            next_income_str = "Hozir"
        
        text += (
            f"🚗 {car_data['name']}\n"
            f"💰 Kunlik: {car_data['daily_income']:,.0f} so'm\n"
            f"⏰ Qolgan vaqt: {days_left} kun {hours_left} soat\n"
            f"🕐 Keyingi daromad: {next_income_str}\n\n"
        )
    
    await update.message.reply_text(text)

# Balance section
@check_subscription
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    cars = await get_user_cars(user_id)
    
    has_cars = len(cars) > 0
    can_withdraw = has_cars and float(user['balance']) >= 25000
    
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
        elif float(user['balance']) < 25000:
            text += f"\n\n⚠️ Pul yechish uchun balansingiz kamida 25,000 so'm bo'lishi kerak!"
    
    # Message turini tekshirish
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    logger.info(f"Balance shown for user {user_id}")

@check_subscription
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
    if float(user['balance']) < 25000:
        await query.answer("❌ Balansingiz 25,000 so'mdan kam!", show_alert=True)
        return
    
    text = (
        f"💳 Pul yechish\n\n"
        f"💰 Mavjud balans: {user['balance']:,.0f} so'm\n"
        f"💸 Minimal yechish: 25,000 so'm\n"
        f"📉 Komissiya: 15%\n\n"
        f"Yechish uchun miqdorni kiriting (so'mda):"
    )
    
    await query.message.reply_text(text)
    await query.answer()
    logger.info(f"Withdrawal initiated by user {user_id}")
    return WITHDRAW_AMOUNT

@check_subscription
async def handle_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    try:
        amount = float(update.message.text)
        
        # Tekshiramiz, mashina bormi
        cars = await get_user_cars(user_id)
        if not cars:
            await update.message.reply_text("❌ Pul yechish uchun mashina sotib olishingiz kerak!")
            await show_main_menu(update, context)
            return MENU
        
        # Tekshiramiz, minimal miqdor bormi
        if amount < 25000:
            await update.message.reply_text("❌ Minimal yechish miqdori 25,000 so'm!")
            return WITHDRAW_AMOUNT
        
        # Tekshiramiz, balans yetarlimi
        if amount > float(user['balance']):
            await update.message.reply_text("❌ Balansingizda yetarli mablag' yo'q!")
            return WITHDRAW_AMOUNT
        
        context.user_data['withdraw_amount'] = amount
        
        commission = amount * 0.15
        final_amount = amount - commission
        
        text = (
            f"💳 Pul yechish tasdiqlash\n\n"
            f"💰 Yechish miqdori: {amount:,.0f} so'm\n"
            f"📉 Komissiya (15%): {commission:,.0f} so'm\n"
            f"🎯 Olinadigan summa: {final_amount:,.0f} so'm\n\n"
            f"UzCard/Humo kartangiz raqamini kiriting:"
        )
        
        await update.message.reply_text(text)
        logger.info(f"Withdrawal amount set for user {user_id}: {amount}")
        return WITHDRAW_CARD
        
    except ValueError:
        await update.message.reply_text("❌ Iltimos, raqam kiriting!")
        return WITHDRAW_AMOUNT

@check_subscription
async def handle_withdraw_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    card_number = update.message.text
    amount = context.user_data['withdraw_amount']
    
    # Tekshiramiz, mashina bormi
    cars = await get_user_cars(user_id)
    if not cars:
        await update.message.reply_text("❌ Pul yechish uchun mashina sotib olishingiz kerak!")
        await show_main_menu(update, context)
        return MENU
    
    # Save withdrawal request
    conn = await init_db()
    try:
        result = await conn.fetchrow(
            'INSERT INTO transactions (user_id, amount, type, card_number) VALUES ($1, $2, $3, $4) RETURNING id',
            user_id, amount, 'withdraw', card_number
        )
        
        request_id = result['id']
        commission = amount * 0.15
        final_amount = amount - commission
        
        # Admin ga so'rov yuborish inline keyboard bilan
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes", callback_data=f"approve_{request_id}"),
                InlineKeyboardButton("❌ No", callback_data=f"reject_{request_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            ADMIN_ID,
            f"🔄 Yangi pul yechish so'rovi:\n\n"
            f"🆔 So'rov ID: {request_id}\n"
            f"👤 User ID: {user_id}\n"
            f"📞 Tel: {(await get_user(user_id))['phone_number']}\n"
            f"💳 Karta: {card_number}\n"
            f"💰 Miqdor: {amount:,.0f} so'm\n"
            f"📉 Komissiya (15%): {commission:,.0f} so'm\n"
            f"🎯 Olinadigan: {final_amount:,.0f} so'm\n"
            f"⏰ Vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Pul tushirildimi?",
            reply_markup=reply_markup
        )
        
        logger.info(f"Withdrawal request submitted by user {user_id}: {amount} to card {card_number}")
    except Exception as e:
        logger.error(f"Error processing withdrawal for user {user_id}: {e}")
    finally:
        await conn.close()
    
    await update.message.reply_text(
        "✅ Pul yechish so'rovingiz qabul qilindi!\n"
        "Admin 24 soat ichida ko'rib chiqadi."
    )
    
    await show_main_menu(update, context)
    return MENU

# YANGI: Admin uchun so'rovni tasdiqlash/rad etish handler
async def handle_withdraw_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    # Faqat admin tasdiqlashi mumkin
    if user_id != ADMIN_ID:
        await query.answer("Sizda bu amalni bajarish uchun ruxsat yo'q!", show_alert=True)
        return
    
    data = query.data
    action, request_id = data.split('_')
    request_id = int(request_id)
    
    conn = await init_db()
    try:
        # So'rovni bazadan olamiz
        request = await conn.fetchrow(
            'SELECT * FROM transactions WHERE id = $1', request_id
        )
        
        if not request:
            await query.answer("❌ So'rov topilmadi!", show_alert=True)
            return
        
        if action == 'approve':
            # So'rovni tasdiqlaymiz
            await conn.execute(
                'UPDATE transactions SET status = $1 WHERE id = $2',
                'approved', request_id
            )
            
            # Foydalanuvchi balansidan pulni ayiramiz
            commission = float(request['amount']) * 0.15
            amount_to_deduct = float(request['amount'])
            
            await conn.execute(
                'UPDATE users SET balance = balance - $1 WHERE user_id = $2',
                amount_to_deduct, request['user_id']
            )
            
            # Foydalanuvchiga xabar
            await context.bot.send_message(
                request['user_id'],
                f"✅ Pul yechish so'rovingiz tasdiqlandi!\n\n"
                f"💰 {float(request['amount']) - commission:,.0f} so'm kartangizga o'tkazildi\n"
                f"📉 Komissiya (15%): {commission:,.0f} so'm\n"
                f"💳 Karta: {request['card_number']}\n\n"
                f"Pul muvaffaqiyatli tushirildi! 🎉"
            )
            
            # Admin ga tasdiqlash xabari
            await query.edit_message_text(
                f"✅ So'rov tasdiqlandi!\n\n"
                f"🆔 So'rov ID: {request_id}\n"
                f"👤 User ID: {request['user_id']}\n"
                f"💰 Miqdor: {request['amount']:,.0f} so'm\n"
                f"💳 Karta: {request['card_number']}\n\n"
                f"Pul muvaffaqiyatli tushirildi!"
            )
            
            logger.info(f"Withdrawal approved: {request_id} for user {request['user_id']}")
            
        elif action == 'reject':
            # So'rovni rad etamiz
            await conn.execute(
                'UPDATE transactions SET status = $1 WHERE id = $2',
                'rejected', request_id
            )
            
            # Foydalanuvchiga xabar
            await context.bot.send_message(
                request['user_id'],
                f"❌ Pul yechish so'rovingiz rad etildi!\n\n"
                f"Sabab: Admin tomonidan rad etildi\n"
                f"Iltimos, qaytadan urinib ko'ring yoki admin bilan bog'laning."
            )
            
            # Admin ga rad etish xabari
            await query.edit_message_text(
                f"❌ So'rov rad etildi!\n\n"
                f"🆔 So'rov ID: {request_id}\n"
                f"👤 User ID: {request['user_id']}\n"
                f"💰 Miqdor: {request['amount']:,.0f} so'm\n"
                f"💳 Karta: {request['card_number']}\n\n"
                f"So'rov rad etildi!"
            )
            
            logger.info(f"Withdrawal rejected: {request_id} for user {request['user_id']}")
        
        await query.answer()
        
    except Exception as e:
        logger.error(f"Error processing withdrawal approval: {e}")
        await query.answer("❌ Xatolik yuz berdi!", show_alert=True)
    finally:
        await conn.close()

# Fill balance section
@check_subscription
async def fill_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📥 Hisobni to'ldirish\n\n"
        "Hisobingizni to'ldirish uchun admin bilan bog'laning:\n"
        f"👤 Admin: @GooTaksi_Admin\n\n"
        "ish vaqti 7:00 23:00 gacha."
    )
    
    await update.message.reply_text(text)

# Referral section - YANGI: 500 so'm har bir taklif uchun va 12 ta uchun Tico
@check_subscription
async def show_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = await init_db()
    try:
        referrals_count = await conn.fetchval(
            'SELECT COUNT(*) FROM referrals WHERE referrer_id = $1', user_id
        )
        
        # Referal bonusini hisoblaymiz
        user = await get_user(user_id)
        referral_bonus = float(user['referral_bonus_earned']) if user['referral_bonus_earned'] else 0
        
        # YANGI: 12 ta referal tekshirish
        has_tico_bonus = user['has_received_tico_bonus']
        
    except Exception as e:
        logger.error(f"Error getting referral data for user {user_id}: {e}")
        referrals_count = 0
        referral_bonus = 0
        has_tico_bonus = False
    finally:
        await conn.close()
    
    referral_link = f"https://t.me/{(await context.bot.get_me()).username}?start={user_id}"
    
    text = (
        f"👥 Referal tizimi\n\n"
        f"📊 Jami takliflar: {referrals_count} ta\n"
        f"💰 Referal bonus: {referral_bonus:,.0f} so'm\n\n"
        f"🔗 Sizning referal havolangiz:\n`{referral_link}`\n\n"
        f"🎯 Taklif qilish shartlari:\n"
        f"• Har bir taklif uchun: 500 so'm bonus\n"
        f"• 12 ta do'st taklif qilsangiz: BEPUL Tico mashinasi 🚗\n"
    )
    
    if referrals_count >= 12 and not has_tico_bonus:
        text += f"\n🎁 Siz {referrals_count} ta do'stingizni taklif qildingiz! Tico mashinasi sovg'a qilindi! 🚗"
    elif has_tico_bonus:
        text += f"\n✅ Siz 12 ta do'stingizni taklif qilganingiz uchun BEPUL Tico mashinasi olgansiz! 🎉"
    else:
        text += f"\n📈 Tico mashinasini olish uchun {12 - referrals_count} ta do'stingizni taklif qiling!"
    
    await update.message.reply_text(text)

# Daily bonus
@check_subscription
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
@check_subscription
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💬 Qo'llab Quvvatlash\n\n"
        "Savol yoki takliflaringiz bo'lsa, admin bilan bog'laning:\n"
        f"👤 Admin: @GooTaksi_Admin\n\n"
        "Yordam kerak bo'lsa, murojaat qiling!"
    )
    
    await update.message.reply_text(text)

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
            commission = float(req['amount']) * 0.15
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
        
        await update.message.reply_text(text)
        
    except Exception as e:
        logger.error(f"Error showing withdraw requests: {e}")
        await update.message.reply_text(f"❌ Xato: {e}")
    finally:
        await conn.close()

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
            ],
            CHECK_SUBSCRIPTION: [
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
                CallbackQueryHandler(show_car_detail, pattern="^car_"),
                CallbackQueryHandler(buy_car_handler, pattern="^buy_"),
                CallbackQueryHandler(withdraw_money, pattern="^withdraw$"),
            ],
            WITHDRAW_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_withdraw_amount)
            ],
            WITHDRAW_CARD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_withdraw_card)
            ]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    application.add_handler(conv_handler)
    
    # YANGI: Admin uchun withdraw approval handler
    application.add_handler(CallbackQueryHandler(handle_withdraw_approval, pattern="^(approve|reject)_"))
    
    # Admin handlers
    application.add_handler(CommandHandler("admin", admin_menu))
    application.add_handler(CommandHandler("fill", fill_user_balance))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_admin_commands))
    
    # Start the bot
    logger.info("Bot starting polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
