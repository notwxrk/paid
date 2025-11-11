import os
import logging
import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

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
from flask import Flask

# Flask app for uptimerobot
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=5000)

# Database configuration
DATABASE_URL = "postgresql://zworld_user:dX0c9sh3kmVGEUBbqRMuK5Djrozfiek3@dpg-d47oviidbo4c73fbnrfg-a/zworld"

# Bot configuration
BOT_TOKEN = "8526778595:AAGP5ZINtNu6M2vYiZt2onz6bFRostthM8k"
ADMIN_ID = 36261771626
CHANNEL_USERNAMES = ["@ishowxworld", "@dengigo"]  # Majburiy kanallar

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
        "image": "https://i.ibb.co/Lzz0shFS/20251111-132601.png"
    },
    "damas": {
        "name": "Damas", 
        "daily_income": 10000,
        "duration": 100,
        "total_income": 1000000,
        "price": 75000,
        "image": "https://i.ibb.co/Lzz0shFS/20251111-132601.png"
    },
    "nexia": {
        "name": "Nexia",
        "daily_income": 20000,
        "duration": 100,
        "total_income": 2000000,
        "price": 150000,
        "image": "https://i.ibb.co/Lzz0shFS/20251111-132601.png"
    },
    "cobalt": {
        "name": "Cobalt",
        "daily_income": 30000,
        "duration": 100,
        "total_income": 3000000,
        "price": 300000,
        "image": "https://i.ibb.co/Lzz0shFS/20251111-132601.png"
    },
    "gentra": {
        "name": "Gentra",
        "daily_income": 40000,
        "duration": 100,
        "total_income": 4000000,
        "price": 400000,
        "image": "https://i.ibb.co/Lzz0shFS/20251111-132601.png"
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
        
    finally:
        await conn.close()

# User management
async def get_user(user_id: int) -> Optional[dict]:
    conn = await init_db()
    try:
        user = await conn.fetchrow(
            'SELECT * FROM users WHERE user_id = $1', user_id
        )
        return dict(user) if user else None
    finally:
        await conn.close()

async def create_user(user_id: int, phone_number: str, referred_by: int = None):
    conn = await init_db()
    try:
        await conn.execute(
            'INSERT INTO users (user_id, phone_number, referred_by) VALUES ($1, $2, $3)',
            user_id, phone_number, referred_by
        )
        
        # Referal bonus
        if referred_by:
            await conn.execute(
                'UPDATE users SET balance = balance + 1000 WHERE user_id = $1',
                referred_by
            )
            await conn.execute(
                'INSERT INTO referrals (referrer_id, referred_id) VALUES ($1, $2)',
                referred_by, user_id
            )
    finally:
        await conn.close()

async def update_balance(user_id: int, amount: float):
    conn = await init_db()
    try:
        await conn.execute(
            'UPDATE users SET balance = balance + $1 WHERE user_id = $2',
            amount, user_id
        )
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
        return [dict(car) for car in cars]
    finally:
        await conn.close()

async def buy_car(user_id: int, car_type: str):
    car = CARS[car_type]
    conn = await init_db()
    try:
        # Check balance
        user = await get_user(user_id)
        if user['balance'] < car['price']:
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
        
        return True, "Car purchased successfully"
    finally:
        await conn.close()

# Income calculation
async def calculate_daily_income(user_id: int):
    cars = await get_user_cars(user_id)
    total_income = 0
    
    for car in cars:
        if car['expires_at'] > datetime.now():
            total_income += CARS[car['car_type']]['daily_income']
    
    if total_income > 0:
        await update_balance(user_id, total_income)
        conn = await init_db()
        try:
            await conn.execute(
                'UPDATE users SET total_earned = total_earned + $1 WHERE user_id = $2',
                total_income, user_id
            )
        finally:
            await conn.close()
    
    return total_income

# Channel check - TO'G'RI VERSIYA
async def check_channel_membership(user_id: int, bot) -> bool:
    try:
        for channel in CHANNEL_USERNAMES:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        return True
    except Exception as e:
        print(f"Channel check error: {e}")
        return False

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check referral
    referred_by = None
    if context.args:
        try:
            referred_by = int(context.args[0])
        except:
            pass
    
    user = await get_user(user_id)
    
    if not user:
        # Check channel membership - TO'G'RI TEKSHIRISH
        if not await check_channel_membership(user_id, context.bot):
            keyboard = []
            for channel in CHANNEL_USERNAMES:
                keyboard.append([InlineKeyboardButton(f"📢 {channel} kanaliga a'zo bo'lish", url=f"https://t.me/{channel[1:]}")])
            keyboard.append([InlineKeyboardButton("✅ A'zolikni tekshirish", callback_data="check_membership")])
            
            await update.message.reply_text(
                "Botdan to'liq foydalanish uchun quyidagi kanallarga a'zo bo'ling:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    
    if not user:
        # Ask for phone number
        keyboard = [[KeyboardButton("📞 Telefon raqamimni yuborish", request_contact=True)]]
        await update.message.reply_text(
            "Assalomu alaykum! Goo Taksi botiga xush kelibsiz!\n\n"
            "Davom etish uchun telefon raqamingizni tasdiqlang:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return PHONE
    
    await show_main_menu(update, context)
    return MENU

async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if await check_channel_membership(user_id, context.bot):
        await query.edit_message_text("✅ Siz barcha kanallarga a'zo bo'lgansiz! Endi telefon raqamingizni tasdiqlashingiz mumkin.")
        
        keyboard = [[KeyboardButton("📞 Telefon raqamimni yuborish", request_contact=True)]]
        await context.bot.send_message(
            chat_id=user_id,
            text="Davom etish uchun telefon raqamingizni tasdiqlang:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return PHONE
    else:
        keyboard = []
        for channel in CHANNEL_USERNAMES:
            keyboard.append([InlineKeyboardButton(f"📢 {channel} kanaliga a'zo bo'lish", url=f"https://t.me/{channel[1:]}")])
        keyboard.append([InlineKeyboardButton("✅ A'zolikni tekshirish", callback_data="check_membership")])
        
        await query.edit_message_text(
            "❌ Siz hali barcha kanallarga a'zo bo'lmagansiz!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    phone_number = update.message.contact.phone_number
    
    # Check if Uzbekistan number
    if not phone_number.startswith('+998') and not phone_number.startswith('998'):
        await update.message.reply_text(
            "❌ Faqat O'zbekiston telefon raqamlari qabul qilinadi!\n"
            "Iltimos, +998 kodli raqamingizni yuboring.",
            reply_markup=ReplyKeyboardRemove()
        )
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
    
    # Calculate daily income
    daily_income = await calculate_daily_income(user_id)
    
    keyboard = [
        ["🚖 Mashinalar", "🚘 Mening Mashinam"],
        ["💸 Hisobim", "📥 Hisobni To'ldirish"],
        ["👥 Referal", "🎁 Kunlik bonus"],
        ["💬 Qo'llab Quvvatlash"]
    ]
    
    text = (
        f"🏠 Asosiy menyu\n\n"
        f"💰 Balans: {user['balance']:,.0f} so'm\n"
        f"📈 Kunlik daromad: {daily_income:,.0f} so'm"
    )
    
    if update.message:
        await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    else:
        await update.callback_query.edit_message_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

# Car section
async def show_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    success, message = await buy_car(user_id, car_type)
    
    if success:
        await query.answer("✅ Mashina muvaffaqiyatli sotib olindi!", show_alert=True)
        await show_main_menu(update, context)
    else:
        await query.answer(f"❌ {message}", show_alert=True)

# My Cars section
async def show_my_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cars = await get_user_cars(user_id)
    
    if not cars:
        await update.message.reply_text("🚫 Sizda hali mashinalar yo'q")
        return
    
    text = "🚘 Mening mashinalarim:\n\n"
    for car in cars:
        car_data = CARS[car['car_type']]
        days_left = (car['expires_at'] - datetime.now()).days
        text += (
            f"🚗 {car_data['name']}\n"
            f"💰 Kunlik: {car_data['daily_income']:,.0f} so'm\n"
            f"⏰ Qolgan kun: {days_left} kun\n\n"
        )
    
    await update.message.reply_text(text)

# Balance section
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    cars = await get_user_cars(user_id)
    
    has_cars = len(cars) > 0
    
    text = (
        f"💸 Hisobim\n\n"
        f"💰 Joriy balans: {user['balance']:,.0f} so'm\n"
        f"📈 Umumiy daromad: {user['total_earned']:,.0f} so'm\n"
        f"🚗 Faol mashinalar: {len(cars)} ta"
    )
    
    if user['balance'] >= 20000:  # Minimal pul yechish miqdori
        keyboard = [[InlineKeyboardButton("💳 Pul yechish", callback_data="withdraw")]]
    else:
        text += f"\n\n⚠️ Pul yechish uchun balansingiz kamida 20,000 so'm bo'lishi kerak!"
        keyboard = []
    
    if not has_cars:
        text += "\n\n🚗 Pul yechish uchun kamida 1 ta mashina sotib olishingiz kerak!"
        keyboard = []
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def withdraw_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = await get_user(user_id)
    
    # Minimal pul yechish miqdori tekshirish
    if user['balance'] < 20000:
        await query.answer("❌ Pul yechish uchun balansingiz kamida 20,000 so'm bo'lishi kerak!", show_alert=True)
        return
    
    context.user_data['withdraw_amount'] = user['balance']
    
    text = (
        f"💳 Pul yechish\n\n"
        f"💰 Mavjud balans: {user['balance']:,.0f} so'm\n"
        f"💸 Yechish miqdori: {user['balance']:,.0f} so'm\n"
        f"📉 Komissiya (10%): {user['balance'] * 0.1:,.0f} so'm\n"
        f"🎯 Olinadigan summa: {user['balance'] * 0.9:,.0f} so'm\n\n"
        f"UzCard/Humo kartangiz raqamini yuboring:"
    )
    
    await query.message.reply_text(text)
    await query.answer()
    return WITHDRAW

async def handle_withdraw_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    card_number = update.message.text
    amount = context.user_data['withdraw_amount']
    
    # Minimal miqdor tekshirish
    if amount < 20000:
        await update.message.reply_text("❌ Pul yechish uchun minimal miqdor 20,000 so'm!")
        await show_main_menu(update, context)
        return MENU
    
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
            f"💳 Karta: {card_number}\n"
            f"💰 Miqdor: {amount:,.0f} so'm\n"
            f"🎯 Olinadigan: {amount * 0.9:,.0f} so'm"
        )
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

# Referral section
async def show_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = await init_db()
    try:
        referrals_count = await conn.fetchval(
            'SELECT COUNT(*) FROM referrals WHERE referrer_id = $1', user_id
        )
        
        referral_bonus = await conn.fetchval(
            'SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = $1 AND type = $2',
            user_id, 'referral'
        )
    finally:
        await conn.close()
    
    referral_link = f"https://t.me/{(await context.bot.get_me()).username}?start={user_id}"
    
    text = (
        f"👥 Referal tizimi\n\n"
        f"📊 Jami takliflar: {referrals_count} ta\n"
        f"💰 Referal bonus: {referral_bonus:,.0f} so'm\n\n"
        f"🔗 Sizning referal havolangiz:\n`{referral_link}`\n\n"
        f"🎯 Taklif qilish shartlari:\n"
        f"• Har bir taklif uchun: 1,000 so'm\n"
        f"• Do'stingiz pul yechganda: 3% bonus"
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

# Button handler
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "back_to_menu":
        await back_to_menu(update, context)
    elif data == "back_to_cars":
        await back_to_cars(update, context)
    elif data.startswith("car_"):
        await show_car_detail(update, context)
    elif data.startswith("buy_"):
        await buy_car_handler(update, context)
    elif data == "withdraw":
        await withdraw_money(update, context)
    elif data == "check_membership":
        await check_membership_callback(update, context)

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
        
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {e}")

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
            text += (
                f"🆔 So'rov ID: {req['id']}\n"
                f"👤 User: {req['user_id']}\n"
                f"📞 Tel: {user['phone_number']}\n"
                f"💳 Karta: {req['card_number']}\n"
                f"💰 Miqdor: {req['amount']:,.0f} so'm\n"
                f"⏰ Vaqt: {req['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
                f"────────────────────\n"
            )
        
        text += "\nTasdiqlash: `/approve id`\nRad etish: `/reject id`"
        
        await update.message.reply_text(text)
        
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
                
                # Deduct balance from user
                await conn.execute(
                    'UPDATE users SET balance = balance - $1 WHERE user_id = $2',
                    request['amount'], request['user_id']
                )
                
                # Notify user
                await context.bot.send_message(
                    request['user_id'],
                    f"✅ Pul yechish so'rovingiz tasdiqlandi!\n"
                    f"💰 {request['amount'] * 0.9:,.0f} so'm kartangizga o'tkazildi"
                )
                
                await update.message.reply_text("✅ So'rov tasdiqlandi!")
                
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
                
        finally:
            await conn.close()
            
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {e}")

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
        
    finally:
        await conn.close()

# Main function
def main():
    # Create tables
    asyncio.get_event_loop().run_until_complete(create_tables())
    
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
            ],
            WITHDRAW: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_withdraw_card)
            ]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Admin handlers
    application.add_handler(CommandHandler("admin", admin_menu))
    application.add_handler(CommandHandler("fill", fill_user_balance))
    application.add_handler(CommandHandler("approve", handle_withdraw_action))
    application.add_handler(CommandHandler("reject", handle_withdraw_action))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_admin_commands))
    
    # Start Flask in separate thread for uptimerobot
    import threading
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start the bot with polling
    print("Bot started with polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
