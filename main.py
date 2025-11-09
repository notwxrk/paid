# -*- coding: utf-8 -*-
"""
main.py

Telegram mini-magazine bot (single-file)
Requirements:
  pip install python-telegram-bot==20.6 sqlalchemy psycopg2-binary python-dotenv

How to run:
  - Set environment variables BOT_TOKEN and DATABASE_URL (recommended).
  - python main.py

Features:
  - Admin can add products with photo, title, price (UZS), quantity, description via /admin_add_product
  - Users see products via "🧨 Tovarlar" and can press "Buyurtma Berish"
  - Order flow: quantity -> address -> phone -> payment method (SBER or CRYPTO)
  - SBER: show card number and total UZS
  - CRYPTO: choose TRC20/BSC20, compute USDT based on admin-set rate
  - User uploads payment screenshot; order is saved and admin gets a notification with Approve/Reject/Delete
  - Admin can list orders and products, delete products, set USDT rate
"""

import os
import logging
from uuid import uuid4
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Numeric, DateTime, ForeignKey
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
)

# -------------------- CONFIG --------------------
BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "8273588414:AAEA-hTsPMtfhOnpITe6A5uFcoDIr0M9WJM"  # default provided (move to env for prod)
)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://zworld_user:dX0c9sh3kmVGEUBbqRMuK5Djrozfiek3@dpg-d47oviidbo4c73fbnrfg-a/zworld"
)
ADMIN_ID = int(os.getenv("ADMIN_ID", "7632409181"))

USDT_TRC20_ADDR = os.getenv("USDT_TRC20_ADDR", "TDDzr7Fup4SgUwv71sq1Mmbk1ntNrGuMzx")
USDT_BSC20_ADDR = os.getenv("USDT_BSC20_ADDR", "0xdf2e737d8d439432f8e06b767e540541728c635f")
DEFAULT_UZS_PER_USDT = Decimal(os.getenv("DEFAULT_UZS_PER_USDT", "12000"))  # default rate

# -------------------- LOGGING --------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# -------------------- DATABASE --------------------
Base = declarative_base()

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    price_uzs = Column(Numeric(18, 2), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    photo_file_id = Column(Text)  # telegram file_id
    created_at = Column(DateTime, default=datetime.utcnow)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    uid = Column(String(64), unique=True, index=True)
    user_id = Column(Integer, nullable=False)
    user_name = Column(String(255))
    product_id = Column(Integer, ForeignKey("products.id"))
    product = relationship("Product")
    qty = Column(Integer, nullable=False)
    address = Column(Text)
    phone = Column(String(100))
    payment_method = Column(String(50))  # SBER or CRYPTO
    crypto_network = Column(String(50), nullable=True)
    total_uzs = Column(Numeric(18, 2))
    total_usdt = Column(Numeric(18, 6), nullable=True)
    screenshot_file_id = Column(Text, nullable=True)
    status = Column(String(50), default="pending")  # pending / approved / rejected
    created_at = Column(DateTime, default=datetime.utcnow)

class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(200), unique=True, index=True)
    value = Column(String(200))

# Create engine & session
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(bind=engine)

# Helpers for settings
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

# -------------------- STATES --------------------
(
    ADD_TITLE, ADD_PRICE, ADD_QTY, ADD_DESC, ADD_PHOTO,
    ORDER_QTY, ORDER_ADDRESS, ORDER_PHONE, ORDER_PAYMENT_CHOICE, ORDER_CRYPTO_NET, ORDER_SCREENSHOT
) = range(11)

# -------------------- KEYBOARDS --------------------
main_menu_kb = ReplyKeyboardMarkup(
    [["🧨 Tovarlar", "✨️ Mening Buyurtmalarim"], ["🚖 Yetkazib Berish"]],
    resize_keyboard=True
)

# -------------------- HANDLERS --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = f"Assalomu alaykum, {user.first_name}!\nMagazin botga xush kelibsiz."
    await update.message.reply_text(text, reply_markup=main_menu_kb)

async def delivery_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🚚 Yetkazib berish:\n"
        "- Biz O'zbekistonning barcha hududlariga yetkazib beramiz.\n"
        "- Yetkazib berish muddati: 3 kun ichida.\n"
        "- Yetkazib berish BEPUL."
    )
    await update.message.reply_text(text)

# List products to user
async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    try:
        prods = session.query(Product).order_by(Product.created_at.desc()).all()
        if not prods:
            await update.message.reply_text("Hozircha tovarlar mavjud emas.")
            return
        for p in prods:
            caption = f"{p.title}\nNarxi: {int(p.price_uzs):,} UZS\nMiqdori: {p.quantity}\n\n{p.description or ''}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Buyurtma Berish", callback_data=f"buy_{p.id}")]])
            if p.photo_file_id:
                try:
                    await update.message.reply_photo(photo=p.photo_file_id, caption=caption, reply_markup=kb)
                except Exception:
                    await update.message.reply_text(caption, reply_markup=kb)
            else:
                await update.message.reply_text(caption, reply_markup=kb)
    finally:
        session.close()

# Show user's orders
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = SessionLocal()
    try:
        orders = session.query(Order).filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()
        if not orders:
            await update.message.reply_text("Sizda buyurtmalar topilmadi.")
            return
        for o in orders:
            prod_title = o.product.title if o.product else "Noma'lumot"
            text = (
                f"📦 Buyurtma: {o.uid}\nMahsulot: {prod_title}\nMiqdor: {o.qty}\n"
                f"Jami: {int(o.total_uzs):,} UZS\nStatus: {o.status}\nManzil: {o.address}\nTelefon: {o.phone}\n"
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

# When user presses Buyurtma Berish
async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("buy_"):
        return
    prod_id = int(data.split("_", 1)[1])
    session = SessionLocal()
    try:
        prod = session.query(Product).get(prod_id)
        if not prod:
            await query.message.reply_text("Tanlangan mahsulot topilmadi.")
            return
        if prod.quantity <= 0:
            await query.message.reply_text("Kechirasiz, ushbu mahsulot zaxirada yo'q.")
            return
        context.user_data["buy_product_id"] = prod.id
        await query.message.reply_text(f"{prod.title} — Narxi: {int(prod.price_uzs):,} UZS\nNechta dona kerak?")
        return
    finally:
        session.close()

# Order flow handlers
async def order_qty_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if not txt.isdigit() or int(txt) <= 0:
        await update.message.reply_text("Iltimos, to'g'ri miqdor yozing (faqat son).")
        return
    qty = int(txt)
    session = SessionLocal()
    try:
        prod_id = context.user_data.get("buy_product_id")
        prod = session.query(Product).get(prod_id) if prod_id else None
        if not prod:
            await update.message.reply_text("Mahsulot topilmadi. Iltimos buyurtmani qayta boshlang.")
            context.user_data.clear()
            return
        if qty > prod.quantity:
            await update.message.reply_text(f"Kechirasiz, faqat {prod.quantity} dona mavjud.")
            return
        context.user_data["order_qty"] = qty
        await update.message.reply_text("Yetkazib berish manzilini kiriting:")
    finally:
        session.close()

async def order_address_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order_address"] = update.message.text.strip()
    await update.message.reply_text("Aloqa uchun telefon raqamingizni kiriting (masalan +998901234567):")

async def order_phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data["order_phone"] = phone
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("СБЕР", callback_data="pay_sber"), InlineKeyboardButton("CRYPTO", callback_data="pay_crypto")]
    ])
    await update.message.reply_text("To'lov usulini tanlang:", reply_markup=kb)

# Payment choice callback
async def payment_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    session = SessionLocal()
    try:
        prod_id = context.user_data.get("buy_product_id")
        qty = context.user_data.get("order_qty")
        prod = session.query(Product).get(prod_id) if prod_id else None
        if not prod:
            await query.message.reply_text("Mahsulot topilmadi. Iltimos buyurtmani qayta boshlang.")
            context.user_data.clear()
            return
        # total UZS
        total_uzs = (Decimal(prod.price_uzs) * Decimal(qty)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        context.user_data["total_uzs"] = str(total_uzs)
        if data == "pay_sber":
            context.user_data["payment_method"] = "SBER"
            await query.message.reply_text(
                f"СБЕР Bank karta raqami: 2202208046692951\n\n"
                f"Mahsulot: {prod.title}\nMiqdor: {qty}\nJami: {int(total_uzs):,} UZS\n\n"
                "Iltimos to'lov qilganingizdan so'ng skrinshot yuboring."
            )
            return
        elif data == "pay_crypto":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("USDT TRC20", callback_data="crypto_trc20")],
                [InlineKeyboardButton("USDT BSC20", callback_data="crypto_bsc20")]
            ])
            await query.message.reply_text("Iltimos tarmoqni tanlang:", reply_markup=kb)
            return
    finally:
        session.close()

# Crypto network callback
async def crypto_net_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    session = SessionLocal()
    try:
        total_uzs = Decimal(context.user_data.get("total_uzs", "0"))
        saved_rate = get_setting(session, "uzs_per_usdt", None)
        rate = Decimal(saved_rate) if saved_rate is not None else DEFAULT_UZS_PER_USDT
        if rate == 0:
            rate = DEFAULT_UZS_PER_USDT
        total_usdt = (total_uzs / rate).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if data == "crypto_trc20":
            addr = USDT_TRC20_ADDR
            net = "TRC20"
        else:
            addr = USDT_BSC20_ADDR
            net = "BSC20"
        context.user_data["payment_method"] = "CRYPTO"
        context.user_data["crypto_network"] = net
        context.user_data["total_usdt"] = str(total_usdt)
        await query.message.reply_text(
            f"USDT {net} manzil: {addr}\n"
            f"Jami: {int(total_uzs):,} UZS\n"
            f"Yuborish kerak: {total_usdt} USDT\n\n"
            "To'lovni amalga oshirib, skrinshot yuboring."
        )
    finally:
        session.close()

# Receive screenshot and create order
async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = SessionLocal()
    try:
        prod_id = context.user_data.get("buy_product_id")
        prod = session.query(Product).get(prod_id) if prod_id else None
        if not prod:
            await update.message.reply_text("Mahsulot topilmadi. Iltimos buyurtmani qayta boshlang.")
            context.user_data.clear()
            return
        qty = context.user_data.get("order_qty")
        address = context.user_data.get("order_address")
        phone = context.user_data.get("order_phone")
        payment_method = context.user_data.get("payment_method")
        crypto_net = context.user_data.get("crypto_network")
        total_uzs = Decimal(context.user_data.get("total_uzs", "0"))
        total_usdt = context.user_data.get("total_usdt")
        # get file_id
        file_id = None
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
        elif update.message.document:
            file_id = update.message.document.file_id
        else:
            await update.message.reply_text("Iltimos to'lov skrinshotini rasm yoki fayl sifatida yuboring.")
            return
        # create order
        order = Order(
            uid=str(uuid4())[:16],
            user_id=user.id,
            user_name=(user.full_name or user.username or ""),
            product_id=prod.id,
            qty=qty,
            address=address,
            phone=phone,
            payment_method=payment_method,
            crypto_network=crypto_net,
            total_uzs=total_uzs,
            total_usdt=(Decimal(total_usdt) if total_usdt else None),
            screenshot_file_id=file_id,
            status="pending"
        )
        session.add(order)
        # decrement stock safely
        prod.quantity = max(0, prod.quantity - qty)
        session.commit()
        # notify user
        await update.message.reply_text(
            "Sizning buyurtmangiz qabul qilindi va ko'rib chiqilmoqda.\n"
            "Adminlar tekshiradi. Agar hammasi to'g'ri bo'lsa, buyurtma 3 kun ichida yetkazib beriladi."
        )
        # notify admin
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Tasdiqlash", callback_data=f"admin_approve_{order.id}"),
                InlineKeyboardButton("Rad etish", callback_data=f"admin_reject_{order.id}")
            ],
            [InlineKeyboardButton("O'chirish", callback_data=f"admin_delete_{order.id}")]
        ])
        admin_text = (
            f"🔔 Yangi buyurtma!\nID: {order.uid}\nUser: {order.user_name} ({order.user_id})\n"
            f"Mahsulot: {prod.title}\nMiqdor: {order.qty}\nJami: {int(order.total_uzs):,} UZS\n"
            f"To'lov: {order.payment_method} {('('+ (order.crypto_network or '') +')') if order.crypto_network else ''}\n"
            f"Telefon: {order.phone}\nManzil: {order.address}\nVaqt: {order.created_at.strftime('%Y-%m-%d %H:%M')}"
        )
        try:
            await context.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=admin_text, reply_markup=kb)
        except Exception:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=kb)
    finally:
        session.close()
        context.user_data.clear()

# Admin callbacks for approve/reject/delete
async def admin_order_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    # patterns: admin_approve_<id>, admin_reject_<id>, admin_delete_<id>
    parts = data.split("_")
    if len(parts) < 3:
        return
    action = parts[1]
    try:
        order_id = int(parts[2])
    except ValueError:
        return
    session = SessionLocal()
    try:
        order = session.query(Order).get(order_id)
        if not order:
            await query.message.reply_text("Buyurtma topilmadi yoki oldin o'chirilgan.")
            return
        if action == "approve":
            order.status = "approved"
            session.commit()
            try:
                await context.bot.send_message(chat_id=order.user_id, text=f"Buyurtmangiz tasdiqlandi. Buyurtma tayyorlanmoqda va 3 kun ichida yetkazib beriladi. (ID: {order.uid})")
            except Exception:
                pass
            await query.message.reply_text("Buyurtma tasdiqlandi va userga habar yuborildi.")
        elif action == "reject":
            order.status = "rejected"
            # restore stock
            if order.product:
                order.product.quantity = order.product.quantity + order.qty
            session.commit()
            try:
                await context.bot.send_message(chat_id=order.user_id, text=f"Kechirasiz, buyurtmangiz rad etildi. Iltimos admin bilan bog'laning. (ID: {order.uid})")
            except Exception:
                pass
            await query.message.reply_text("Buyurtma rad etildi.")
        elif action == "delete":
            # restore stock then delete
            if order.product:
                order.product.quantity = order.product.quantity + order.qty
            session.delete(order)
            session.commit()
            await query.message.reply_text("Buyurtma o'chirildi va zaxira tiklandi.")
    finally:
        session.close()

# Admin: add product conversation
async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
        return ConversationHandler.END
    await update.message.reply_text("Mahsulot nomini kiriting:")
    return ADD_TITLE

async def admin_add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_title"] = update.message.text.strip()
    await update.message.reply_text("Narxni kiriting (UZS, faqat son):")
    return ADD_PRICE

async def admin_add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip().replace(",", "")
    try:
        price = Decimal(txt)
    except Exception:
        await update.message.reply_text("Iltimos to'g'ri narx kiriting (faqat son).")
        return ADD_PRICE
    context.user_data["new_price"] = price
    await update.message.reply_text("Miqdorini kiriting (son):")
    return ADD_QTY

async def admin_add_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if not txt.isdigit():
        await update.message.reply_text("Iltimos butun son kiriting.")
        return ADD_QTY
    context.user_data["new_qty"] = int(txt)
    await update.message.reply_text("Mahsulot haqida ta'rif kiriting:")
    return ADD_DESC

async def admin_add_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_desc"] = update.message.text.strip()
    await update.message.reply_text("Mahsulot rasmini yuboring (rasm):")
    return ADD_PHOTO

async def admin_add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Iltimos rasm yuboring.")
        return ADD_PHOTO
    file_id = update.message.photo[-1].file_id
    session = SessionLocal()
    try:
        prod = Product(
            title=context.user_data.get("new_title"),
            description=context.user_data.get("new_desc"),
            price_uzs=context.user_data.get("new_price"),
            quantity=context.user_data.get("new_qty"),
            photo_file_id=file_id
        )
        session.add(prod)
        session.commit()
        await update.message.reply_text(f"✅ Mahsulot qo'shildi: {prod.title}")
    finally:
        session.close()
        context.user_data.clear()
    return ConversationHandler.END

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Operatsiya bekor qilindi.")
    return ConversationHandler.END

# Admin: list products for management
async def admin_list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
        return
    session = SessionLocal()
    try:
        prods = session.query(Product).order_by(Product.created_at.desc()).all()
        if not prods:
            await update.message.reply_text("Hozircha mahsulotlar yo'q.")
            return
        for p in prods:
            text = f"{p.title}\nNarx: {int(p.price_uzs):,} UZS\nMiqdor: {p.quantity}\nID: {p.id}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("O'chirish", callback_data=f"prod_delete_{p.id}")]])
            if p.photo_file_id:
                try:
                    await update.message.reply_photo(photo=p.photo_file_id, caption=text, reply_markup=kb)
                except Exception:
                    await update.message.reply_text(text, reply_markup=kb)
            else:
                await update.message.reply_text(text, reply_markup=kb)
    finally:
        session.close()

async def admin_prod_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split("_")
    if len(parts) < 3:
        return
    try:
        prod_id = int(parts[2])
    except ValueError:
        return
    session = SessionLocal()
    try:
        p = session.query(Product).get(prod_id)
        if not p:
            await query.message.reply_text("Mahsulot topilmadi.")
            return
        session.delete(p)
        session.commit()
        await query.message.reply_text("Mahsulot o'chirildi.")
    finally:
        session.close()

# Admin: list orders
async def admin_list_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
        return
    session = SessionLocal()
    try:
        orders = session.query(Order).order_by(Order.created_at.desc()).all()
        if not orders:
            await update.message.reply_text("Buyurtmalar mavjud emas.")
            return
        for o in orders:
            prod = o.product
            text = (
                f"ID: {o.uid}\nUser: {o.user_name} ({o.user_id})\n"
                f"Mahsulot: {prod.title if prod else ''}\nMiqdor: {o.qty}\n"
                f"Jami: {int(o.total_uzs):,} UZS\nStatus: {o.status}"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Tasdiqlash", callback_data=f"admin_approve_{o.id}"),
                 InlineKeyboardButton("Rad etish", callback_data=f"admin_reject_{o.id}")],
                [InlineKeyboardButton("O'chirish", callback_data=f"admin_delete_{o.id}")]
            ])
            if o.screenshot_file_id:
                try:
                    await update.message.reply_photo(photo=o.screenshot_file_id, caption=text, reply_markup=kb)
                except Exception:
                    await update.message.reply_text(text, reply_markup=kb)
            else:
                await update.message.reply_text(text, reply_markup=kb)
    finally:
        session.close()

# Admin: set USDT rate
async def admin_set_rate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
        return ConversationHandler.END
    await update.message.reply_text("Iltimos 1 USDT uchun UZS kursini son bilan kiriting (masalan 12000):")
    return ADD_PRICE

async def admin_set_rate_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip().replace(",", "")
    try:
        rate = Decimal(txt)
    except Exception:
        await update.message.reply_text("Iltimos to'g'ri son kiriting.")
        return ADD_PRICE
    session = SessionLocal()
    try:
        set_setting(session, "uzs_per_usdt", str(rate))
        await update.message.reply_text(f"Kurs o'rnatildi: 1 USDT = {int(rate):,} UZS")
    finally:
        session.close()
    return ConversationHandler.END

# Generic message router for text menu
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt == "🧨 Tovarlar":
        return await list_products(update, context)
    if txt == "✨️ Mening Buyurtmalarim":
        return await my_orders(update, context)
    if txt == "🚖 Yetkazib Berish":
        return await delivery_info(update, context)
    # fallback
    await update.message.reply_text("Iltimos menyudan tanlang.", reply_markup=main_menu_kb)

# -------------------- MAIN --------------------
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Basic commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_router))

    # Product purchase callback
    application.add_handler(CallbackQueryHandler(buy_callback, pattern=r"^buy_"))

    # Order sequence (simple routing by content)
    # Quantity (only digits)
    application.add_handler(MessageHandler(filters.Regex(r"^\d+$") & (~filters.COMMAND), order_qty_handler))
    # Address (text that is not just digits)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & ~filters.Regex(r"^\d+$"), order_address_handler))
    # Phone (loosely matching phone-like strings)
    application.add_handler(MessageHandler(filters.Regex(r"^\+?\d[\d\s-]{5,}$") & (~filters.COMMAND), order_phone_handler))

    # Payment callbacks
    application.add_handler(CallbackQueryHandler(payment_choice_callback, pattern=r"^pay_"))
    application.add_handler(CallbackQueryHandler(crypto_net_callback, pattern=r"^crypto_"))

    # Screenshot handler (photo or document image)
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, receive_screenshot))

    # Admin order actions (approve/reject/delete)
    application.add_handler(CallbackQueryHandler(admin_order_action_callback, pattern=r"^admin_"))

    # Admin add product conversation
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("admin_add_product", admin_add_start)],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & (~filters.COMMAND), admin_add_title)],
            ADD_PRICE: [MessageHandler(filters.TEXT & (~filters.COMMAND), admin_add_price)],
            ADD_QTY: [MessageHandler(filters.TEXT & (~filters.COMMAND), admin_add_qty)],
            ADD_DESC: [MessageHandler(filters.TEXT & (~filters.COMMAND), admin_add_desc)],
            ADD_PHOTO: [MessageHandler(filters.PHOTO, admin_add_photo)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        allow_reentry=True
    )
    application.add_handler(add_conv)

    # Admin list/delete products and orders
    application.add_handler(CommandHandler("admin_products", admin_list_products))
    application.add_handler(CallbackQueryHandler(admin_prod_delete_callback, pattern=r"^prod_delete_"))
    application.add_handler(CommandHandler("admin_orders", admin_list_orders))

    # Admin set rate conversation
    rate_conv = ConversationHandler(
        entry_points=[CommandHandler("admin_set_rate", admin_set_rate_start)],
        states={ADD_PRICE: [MessageHandler(filters.TEXT & (~filters.COMMAND), admin_set_rate_finish)]},
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        allow_reentry=True
    )
    application.add_handler(rate_conv)

    logger.info("Bot started (polling)...")
    application.run_polling()

if __name__ == "__main__":
    main()
