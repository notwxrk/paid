
"""
Minimal Telegram Magazine Bot (single-file): main.py
- Uses python-telegram-bot v20 (async)
- Uses SQLAlchemy for PostgreSQL
- Single admin (ADMIN_ID)

Features implemented (as requested):
- Menu: Tovarlar, Mening Buyurtmalarim, Yetkazib Berish
- Admin commands to add product with photo, price (UZS), quantity, description
- Users see product list with "Buyurtma Berish" button
- Order flow: quantity -> address -> phone -> payment method (SBER or CRYPTO)
  - SBER shows card number and calculates total UZS
  - CRYPTO asks for network (TRC20/BSC20) and calculates required USDT using admin-set rate
- User uploads screenshot of payment; admin receives order with Approve/Reject buttons
- Admin can view & delete orders and products
- Simple settings: admin can set UZS per USDT rate

WARNING:
- You shared BOT_TOKEN and DATABASE_URL in the chat. For security production deploy, move them to environment variables instead of hardcoding.
- This file contains basic error handling but is for demonstration/minimal admin panel purposes.

Dependencies:
pip install python-telegram-bot==20.6 sqlalchemy psycopg2-binary python-dotenv

Run:
python main.py

Deploy on Render/GitHub: push this file to repo, create a Render web service (or worker) that runs `python main.py` and set environment variables for BOT_TOKEN and DATABASE_URL.

"""

import os
import logging
import asyncio
from uuid import uuid4
from decimal import Decimal
from datetime import datetime

from sqlalchemy import (create_engine, Column, Integer, String, Text, Numeric, DateTime, Boolean, ForeignKey)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto)
from telegram.ext import (ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler,
                          ConversationHandler)

# -------------------- CONFIG --------------------
# -- You provided these values; for safety it's better to use environment variables.
BOT_TOKEN = os.getenv('BOT_TOKEN', '8273588414:AAEA-hTsPMtfhOnpITe6A5uFcoDIr0M9WJM')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://zworld_user:dX0c9sh3kmVGEUBbqRMuK5Djrozfiek3@dpg-d47oviidbo4c73fbnrfg-a/zworld')
ADMIN_ID = int(os.getenv('ADMIN_ID', '7632409181'))

# Default crypto addresses (as requested)
USDT_TRC20_ADDR = os.getenv('USDT_TRC20_ADDR', 'TDDzr7Fup4SgUwv71sq1Mmbk1ntNrGuMzx')
USDT_BSC20_ADDR = os.getenv('USDT_BSC20_ADDR', '0xdf2e737d8d439432f8e06b767e540541728c635f')

# -------------------- LOGGING --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- DATABASE --------------------
Base = declarative_base()

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    price_uzs = Column(Numeric(18,2), nullable=False)  # price per unit in UZS
    quantity = Column(Integer, nullable=False, default=0)
    photo_file_id = Column(Text)  # telegram file_id for photo
    created_at = Column(DateTime, default=datetime.utcnow)

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    order_uid = Column(String(60), unique=True, index=True)
    user_id = Column(Integer, nullable=False)
    user_name = Column(String(200))
    product_id = Column(Integer, ForeignKey('products.id'))
    product = relationship('Product')
    quantity = Column(Integer, nullable=False)
    address = Column(Text)
    phone = Column(String(100))
    payment_method = Column(String(50))  # SBER or CRYPTO
    crypto_network = Column(String(50), nullable=True)  # TRC20 or BSC20
    total_uzs = Column(Numeric(18,2))
    total_usdt = Column(Numeric(18,6), nullable=True)
    screenshot_file_id = Column(Text, nullable=True)
    status = Column(String(50), default='pending')  # pending, approved, rejected
    created_at = Column(DateTime, default=datetime.utcnow)

class Setting(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    key = Column(String(200), unique=True, index=True)
    value = Column(String(200))

# Create engine and session
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)

Base.metadata.create_all(bind=engine)

# Helpers to get/set settings
def get_setting(session, key, default=None):
    s = session.query(Setting).filter_by(key=key).first()
    return s.value if s else default

def set_setting(session, key, value):
    s = session.query(Setting).filter_by(key=key).first()
    if s:
        s.value = str(value)
    else:
        s = Setting(key=key, value=str(value))
        session.add(s)
    session.commit()

# -------------------- STATES for ConversationHandlers
(
    ADD_TITLE, ADD_PRICE, ADD_QTY, ADD_DESC, ADD_PHOTO_CONFIRM, ADD_PHOTO,
    ORDER_QTY, ORDER_ADDRESS, ORDER_PHONE, ORDER_PAYMENT_METHOD, ORDER_CRYPTO_NETWORK, ORDER_SCREENSHOT
) = range(12)

# -------------------- BOT KEYBOARDS --------------------
main_menu_kb = ReplyKeyboardMarkup(
    [["🧨 Tovarlar", "✨️ Mening Buyurtmalarim"], ["🚖 Yetkazib Berish"]], resize_keyboard=True
)

sber_button = InlineKeyboardButton("СБЕР", callback_data='pay_sber')
crypto_button = InlineKeyboardButton("CRYPTO", callback_data='pay_crypto')

# -------------------- BOT HANDLERS --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = SessionLocal()
    try:
        text = f"Assalomu alaykum, {user.first_name}!\n\nMagazin botimizga xush kelibsiz."
        await update.message.reply_text(text, reply_markup=main_menu_kb)
    finally:
        session.close()

# Show delivery info
async def delivery_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🚚 Yetkazib berish:\n"
        "Biz O'zbekistonning barcha hududlariga yetkazib beramiz.\n"
        "Yetkazib berish muddati: 3 kun ichida.\n"
        "Yetkazib berish BEPUL."
    )
    await update.message.reply_text(text)

# List products
async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    try:
        products = session.query(Product).order_by(Product.created_at.desc()).all()
        if not products:
            await update.message.reply_text("Hozircha tovarlar yo'q. Admin tez orada joylaydi.")
            return
        for p in products:
            caption = f"{p.title}\nNarxi: {int(p.price_uzs):,} UZS\nMiqdori: {p.quantity}\n\n{p.description or ''}"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Buyurtma Berish", callback_data=f'buy_{p.id}')]])
            if p.photo_file_id:
                await update.message.reply_photo(photo=p.photo_file_id, caption=caption, reply_markup=keyboard)
            else:
                await update.message.reply_text(caption, reply_markup=keyboard)
    finally:
        session.close()

# My orders
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = SessionLocal()
    try:
        orders = session.query(Order).filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()
        if not orders:
            await update.message.reply_text("Sizning buyurtmalaringiz topilmadi.")
            return
        for o in orders:
            prod = o.product
            text = (
                f"📦 Buyurtma ID: {o.order_uid}\n"
                f"Mahsulot: {prod.title if prod else 'Malumot'}\n"
                f"Miqdor: {o.quantity}\n"
                f"Narx jami: {int(o.total_uzs):,} UZS\n"
                f"Status: {o.status}\n"
                f"Manzil: {o.address}\n"
                f"Telefon: {o.phone}\n"
                f"To'lov: {o.payment_method} {('('+o.crypto_network+')' if o.crypto_network else '')}\n"
                f"Vaqt: {o.created_at.strftime('%Y-%m-%d %H:%M')}"
            )
            if o.screenshot_file_id:
                try:
                    await update.message.reply_photo(photo=o.screenshot_file_id, caption=text)
                except Exception:
                    await update.message.reply_text(text)
            else:
                await update.message.reply_text(text)
    finally:
        session.close()

# -------------------- ORDER FLOW --------------------
async def product_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith('buy_'):
        return
    prod_id = int(data.split('_',1)[1])
    session = SessionLocal()
    try:
        prod = session.query(Product).get(prod_id)
        if not prod:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("Tanlangan tovar topilmadi.")
            return
        if prod.quantity <= 0:
            await query.message.reply_text("Kechirasiz, ushbu mahsulot zaxirada yo'q.")
            return
        # save product id to user_data and ask qty
        context.user_data['buy_product_id'] = prod.id
        await query.message.reply_text(f"{prod.title} - narxi: {int(prod.price_uzs):,} UZS\nNecha dona kerak?")
        return
    finally:
        session.close()

async def order_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("Iltimos, to'g'ri miqdor yozing (faqat son).")
        return
    qty = int(text)
    session = SessionLocal()
    try:
        prod_id = context.user_data.get('buy_product_id')
        prod = session.query(Product).get(prod_id)
        if not prod:
            await update.message.reply_text("Mahsulot topilmadi yoki o'chirilgan.")
            return
        if qty > prod.quantity:
            await update.message.reply_text(f"Kechirasiz, faqat {prod.quantity} dona mavjud.")
            return
        context.user_data['order_qty'] = qty
        await update.message.reply_text("Yetkazib berish manzilini kiriting:")
    finally:
        session.close()

async def order_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['order_address'] = update.message.text.strip()
    await update.message.reply_text("Aloqa uchun telefon raqamingizni kiriting (masalan +998901234567):")

async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data['order_phone'] = phone
    # payment method keyboard via inline
    keyboard = InlineKeyboardMarkup([[sber_button, crypto_button]])
    await update.message.reply_text("To'lov usulini tanlang:", reply_markup=keyboard)

# Payment callbacks
async def payment_choice_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    session = SessionLocal()
    try:
        prod_id = context.user_data.get('buy_product_id')
        qty = context.user_data.get('order_qty')
        prod = session.query(Product).get(prod_id)
        if not prod:
            await query.message.reply_text('Mahsulot topilmadi, qaytadan boshlang.')
            return
        total_uzs = Decimal(prod.price_uzs) * Decimal(qty)
        if data == 'pay_sber':
            # show card number and total
            text = (
                f"To'lov - SBER Bank\nKart raqam: 2202208046692951\n\n"
                f"Mahsulot: {prod.title}\nMiqdor: {qty}\nJami to'lov: {int(total_uzs):,} UZS\n\n"
                "Iltimos to'lov qilganingizdan so'ng to'lov ekranining skrinshotini yuboring."
            )
            context.user_data['payment_method'] = 'SBER'
            context.user_data['total_uzs'] = float(total_uzs)
            await query.message.reply_text(text)
            return
        elif data == 'pay_crypto':
            # ask for network choice
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton('USDT TRC20', callback_data='crypto_trc20')],
                [InlineKeyboardButton('USDT BSC20', callback_data='crypto_bsc20')]
            ])
            await query.message.reply_text('Iltimos tarmoqni tanlang:', reply_markup=keyboard)
            return
    finally:
        session.close()

async def crypto_network_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    session = SessionLocal()
    try:
        prod_id = context.user_data.get('buy_product_id')
        qty = context.user_data.get('order_qty')
        prod = session.query(Product).get(prod_id)
        if not prod:
            await query.message.reply_text('Mahsulot topilmadi, qaytadan boshlang.')
            return
        total_uzs = Decimal(prod.price_uzs) * Decimal(qty)
        # get rate from settings
        rate = get_setting(session, 'uzs_per_usdt', '12000')  # default 12000 UZS per USDT
        rate_decimal = Decimal(rate)
        total_usdt = (Decimal(total_uzs) / rate_decimal).quantize(Decimal('0.000001'))

        if data == 'crypto_trc20':
            addr = USDT_TRC20_ADDR
            net = 'TRC20'
        else:
            addr = USDT_BSC20_ADDR
            net = 'BSC20'

        context.user_data['payment_method'] = 'CRYPTO'
        context.user_data['crypto_network'] = net
        context.user_data['total_uzs'] = float(total_uzs)
        context.user_data['total_usdt'] = float(total_usdt)

        text = (
            f"USDT {net} uchun to'lov\nAdres: {addr}\n\nMahsulot: {prod.title}\nMiqdor: {qty}\nJami: {int(total_uzs):,} UZS\n"
            f"Shu miqdor uchun yuborish kerak: {total_usdt} USDT\n\n"
            "Iltimos to'lov qilganingizdan so'ng to'lov ekranining skrinshotini yuboring."
        )
        await query.message.reply_text(text)
    finally:
        session.close()

async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Save order to DB and notify admin
    user = update.effective_user
    session = SessionLocal()
    try:
        prod_id = context.user_data.get('buy_product_id')
        prod = session.query(Product).get(prod_id)
        if not prod:
            await update.message.reply_text('Mahsulot topilmadi, buyurtmani qayta boshlang.')
            return
        qty = context.user_data.get('order_qty')
        address = context.user_data.get('order_address')
        phone = context.user_data.get('order_phone')
        payment_method = context.user_data.get('payment_method')
        crypto_net = context.user_data.get('crypto_network')
        total_uzs = Decimal(context.user_data.get('total_uzs', 0))
        total_usdt = context.user_data.get('total_usdt')

        # get file_id of photo
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
        elif update.message.document:
            file_id = update.message.document.file_id
        else:
            await update.message.reply_text('Iltimos tolov skrinshotini yuboring (rasm yoki fayl).')
            return

        # create order
        order = Order(
            order_uid = str(uuid4())[:13],
            user_id = user.id,
            user_name = f"{user.first_name} {user.last_name or ''}".strip(),
            product_id = prod.id,
            quantity = qty,
            address = address,
            phone = phone,
            payment_method = payment_method,
            crypto_network = crypto_net,
            total_uzs = total_uzs,
            total_usdt = Decimal(total_usdt) if total_usdt else None,
            screenshot_file_id = file_id,
            status = 'pending'
        )
        session.add(order)
        # decrement product stock
        prod.quantity = prod.quantity - qty
        session.commit()

        # notify user
        await update.message.reply_text(
            "Sizning buyurtmangiz ko'rib chiqilmoqda. Adminlar tez orada qabul qiladi.\n"
            "Agar hammasi to'g'ri bo'lsa buyurtmangiz 3 kun ichida yetkazib beriladi."
        )

        # notify admin with order details and Approve/Reject buttons
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('Tasdiqlash', callback_data=f'admin_approve_{order.id}'), InlineKeyboardButton('Rad etish', callback_data=f'admin_reject_{order.id}')],
            [InlineKeyboardButton('Buyurtmani o\\'chirish', callback_data=f'admin_delete_{order.id}')]
        ])
        prod = order.product
        admin_text = (
            f"Yangi buyurtma!\nID: {order.order_uid}\nUser: {order.user_name} ({order.user_id})\n"
            f"Mahsulot: {prod.title if prod else 'malumot'}\nMiqdor: {order.quantity}\nJami: {int(order.total_uzs):,} UZS\n"
            f"To'lov: {order.payment_method} {('('+order.crypto_network+')' if order.crypto_network else '')}\n"
            f"Telefon: {order.phone}\nManzil: {order.address}\nVaqt: {order.created_at.strftime('%Y-%m-%d %H:%M')}"
        )
        try:
            await context.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=admin_text, reply_markup=keyboard)
        except Exception:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=keyboard)

    finally:
        session.close()
        # clear user_data
        context.user_data.clear()

# Admin callbacks: approve / reject / delete
async def admin_action_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split('_')
    if len(parts) < 3:
        return
    action = parts[1]
    order_id = int(parts[2])
    session = SessionLocal()
    try:
        order = session.query(Order).get(order_id)
        if not order:
            await query.message.reply_text('Buyurtma topilmadi yoki oldin o\\'chirildi.')
            return
        if action == 'approve':
            order.status = 'approved'
            session.commit()
            # notify user
            try:
                await context.bot.send_message(chat_id=order.user_id, text=f"Buyurtmangiz tasdiqlandi. Buyurtma tayyorlanmoqda va 3 kun ichida yetkazib beriladi. (ID: {order.order_uid})")
            except Exception:
                pass
            await query.message.reply_text('Buyurtma tasdiqlandi va userga habar yuborildi.')
        elif action == 'reject':
            order.status = 'rejected'
            session.commit()
            try:
                await context.bot.send_message(chat_id=order.user_id, text=f"Kechirasiz, buyurtmangiz rad etildi. Iltimos admin bilan bog'laning. (ID: {order.order_uid})")
            except Exception:
                pass
            await query.message.reply_text('Buyurtma rad etildi.')
        elif action == 'delete':
            # restore stock
            prod = order.product
            if prod:
                prod.quantity = prod.quantity + order.quantity
            session.delete(order)
            session.commit()
            await query.message.reply_text('Buyurtma o\\'chirildi va zaxira tiklandi.')
    finally:
        session.close()

# -------------------- ADMIN: add product --------------------
async def admin_start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text('Bu admin komandasi.')
        return
    await update.message.reply_text('Mahsulot nomini kiriting:')
    return ADD_TITLE

async def admin_add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_title'] = update.message.text.strip()
    await update.message.reply_text('Narxni kiriting (UZS, faqat son):')
    return ADD_PRICE

async def admin_add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(',', '')
    try:
        price = Decimal(text)
    except Exception:
        await update.message.reply_text('Iltimos to\\'g\\'ri narx yozing (faqat son).')
        return
    context.user_data['new_price'] = price
    await update.message.reply_text('Miqdorini kiriting (son):')
    return ADD_QTY

async def admin_add_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text('Iltimos son kiriting.')
        return
    context.user_data['new_qty'] = int(text)
    await update.message.reply_text('Mahsulot haqida qisqacha ta\\'rif kiriting:')
    return ADD_DESC

async def admin_add_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_desc'] = update.message.text.strip()
    await update.message.reply_text('Endi mahsulot rasmi yuboring (rasm yuboring):')
    return ADD_PHOTO

async def admin_add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text('Iltimos rasm yuboring.')
        return
    file_id = update.message.photo[-1].file_id
    session = SessionLocal()
    try:
        p = Product(
            title = context.user_data.get('new_title'),
            description = context.user_data.get('new_desc'),
            price_uzs = context.user_data.get('new_price'),
            quantity = context.user_data.get('new_qty'),
            photo_file_id = file_id
        )
        session.add(p)
        session.commit()
        await update.message.reply_text(f"Mahsulot qo'shildi: {p.title}")
    finally:
        session.close()
        context.user_data.clear()
    return ConversationHandler.END

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text('Operatsiya bekor qilindi.')
    return ConversationHandler.END

# Admin: list products and delete
async def admin_list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text('Bu admin komandasi.')
        return
    session = SessionLocal()
    try:
        prods = session.query(Product).order_by(Product.created_at.desc()).all()
        if not prods:
            await update.message.reply_text('Hozircha mahsulot yo\\'q.')
            return
        for p in prods:
            text = f"{p.title}\nNarx: {int(p.price_uzs):,} UZS\nMiqdor: {p.quantity}\nID: {p.id}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton('O\\'chirish', callback_data=f'prod_delete_{p.id}')]])
            if p.photo_file_id:
                await update.message.reply_photo(photo=p.photo_file_id, caption=text, reply_markup=kb)
            else:
                await update.message.reply_text(text, reply_markup=kb)
    finally:
        session.close()

async def admin_prod_delete_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split('_')
    if len(parts) < 3:
        return
    prod_id = int(parts[2])
    session = SessionLocal()
    try:
        p = session.query(Product).get(prod_id)
        if not p:
            await query.message.reply_text('Mahsulot topilmadi.')
            return
        session.delete(p)
        session.commit()
        await query.message.reply_text('Mahsulot o\\'chirildi.')
    finally:
        session.close()

# Admin: list orders
async def admin_list_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text('Bu admin komandasi.')
        return
    session = SessionLocal()
    try:
        orders = session.query(Order).order_by(Order.created_at.desc()).all()
        if not orders:
            await update.message.reply_text('Buyurtmalar mavjud emas.')
            return
        for o in orders:
            prod = o.product
            text = (
                f"ID: {o.order_uid}\nUser: {o.user_name} ({o.user_id})\nMahsulot: {prod.title if prod else ''}\nMiqdor: {o.quantity}\nJami: {int(o.total_uzs):,} UZS\nStatus: {o.status}"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton('Tasdiqlash', callback_data=f'admin_approve_{o.id}'), InlineKeyboardButton('Rad etish', callback_data=f'admin_reject_{o.id}')],[InlineKeyboardButton('O\\'chirish', callback_data=f'admin_delete_{o.id}')]])
            if o.screenshot_file_id:
                try:
                    await update.message.reply_photo(photo=o.screenshot_file_id, caption=text, reply_markup=kb)
                except Exception:
                    await update.message.reply_text(text, reply_markup=kb)
            else:
                await update.message.reply_text(text, reply_markup=kb)
    finally:
        session.close()

# Admin: set rate
async def admin_set_rate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text('Bu admin komandasi.')
        return
    await update.message.reply_text('Iltimos 1 USDT uchun UZS kursini kiriting (masalan 12000):')
    return ADD_PRICE

async def admin_set_rate_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(',', '')
    try:
        rate = Decimal(text)
    except Exception:
        await update.message.reply_text('Iltimos to\\'g\\'ri son kiriting.')
        return
    session = SessionLocal()
    try:
        set_setting(session, 'uzs_per_usdt', str(rate))
        await update.message.reply_text(f'Kurs o\\'rnatildi: 1 USDT = {int(rate):,} UZS')
    finally:
        session.close()
    return ConversationHandler.END

# Generic message handler to route based on text menu
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '🧨 Tovarlar':
        return await show_products(update, context)
    if text == '✨️ Mening Buyurtmalarim':
        return await my_orders(update, context)
    if text == '🚖 Yetkazib Berish':
        return await delivery_info(update, context)
    # fallback
    await update.message.reply_text('Iltimos menu orqali tanlang.', reply_markup=main_menu_kb)

# -------------------- MAIN --------------------

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Basic handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_router))

    # Show products callbacks
    application.add_handler(CallbackQueryHandler(product_buy_callback, pattern=r'^buy_'))

    # Order text flow: after pressing Buyurtma we expect quantity -> address -> phone
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & filters.Regex(r'^\\d+$'), order_quantity))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & ~filters.Regex(r'^\\d+$'), order_address))
    # Note: to keep flow simple, phone is next text after address
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & filters.Regex(r'\\+?\\d+'), order_phone))

    # Payment callbacks
    application.add_handler(CallbackQueryHandler(payment_choice_cb, pattern=r'^pay_'))
    application.add_handler(CallbackQueryHandler(crypto_network_cb, pattern=r'^crypto_'))

    # Screenshot handler (photo/doc)
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.MIME_TYPE('image/jpeg') | filters.Document.MIME_TYPE('image/png'), receive_screenshot))

    # Admin callbacks for order actions
    application.add_handler(CallbackQueryHandler(admin_action_cb, pattern=r'^admin_'))

    # Admin add product conversation
    add_conv = ConversationHandler(
        entry_points=[CommandHandler('admin_add_product', admin_start_add)],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_title)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_price)],
            ADD_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_qty)],
            ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_desc)],
            ADD_PHOTO: [MessageHandler(filters.PHOTO, admin_add_photo)],
        },
        fallbacks=[CommandHandler('cancel', admin_cancel)],
    )
    application.add_handler(add_conv)

    # Admin list products and orders
    application.add_handler(CommandHandler('admin_products', admin_list_products))
    application.add_handler(CallbackQueryHandler(admin_prod_delete_cb, pattern=r'^prod_delete_'))
    application.add_handler(CommandHandler('admin_orders', admin_list_orders))

    # Admin set rate conversation (reuse ADD_PRICE state)
    rate_conv = ConversationHandler(
        entry_points=[CommandHandler('admin_set_rate', admin_set_rate_start)],
        states={
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_rate_finish)]
        },
        fallbacks=[CommandHandler('cancel', admin_cancel)]
    )
    application.add_handler(rate_conv)

    # Admin delete order handled earlier via admin_action_cb

    # Run bot
    logger.info('Bot started')
    application.run_polling()

if __name__ == '__main__':
    main()
