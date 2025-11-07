import telebot
from telebot import types
import requests
import json
import os
import time
import threading
from datetime import datetime, timedelta
from flask import Flask
import psycopg2
from urllib.parse import urlparse

# ========== CONFIG ==========
TOKEN = "8244634076:AAHJxLJaKS6F8PM1oGN-GOhBPnpYeeBuKNg"
ADMIN_ID = 7632409181
SECRET_CHANNEL = "-1002189548052"  # Maxfiy kanal ID
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://dengigo_5v4o_user:Ho7AW2U1hFVib73GQg12pQVyzBfWev15@dpg-d43jk66uk2gs7396bl40-a/dengigo_5v4o')

MIN_WITHDRAW = 10.0
REF_REWARD = 0.5
TASK_DEFAULT_REWARD = 2.0

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ========== O'ZBEKISTON VAQTI ==========
def get_uzbekistan_time():
    return datetime.utcnow() + timedelta(hours=5)

def format_uzbekistan_time(timestamp=None):
    if timestamp:
        dt = datetime.fromtimestamp(timestamp)
    else:
        dt = get_uzbekistan_time()
    return dt.strftime("%H:%M %d-%m-%Y")

# ========== DATABASE CLASS ==========
class Database:
    def __init__(self, db_url):
        self.db_url = db_url
        self.init_db()
    
    def get_connection(self):
        return psycopg2.connect(self.db_url, sslmode='require')
    
    def init_db(self):
        conn = self.get_connection()
        c = conn.cursor()
        
        # Drop and recreate tables
        c.execute('''DROP TABLE IF EXISTS submissions''')
        c.execute('''DROP TABLE IF EXISTS payouts''')
        c.execute('''DROP TABLE IF EXISTS tasks''')
        c.execute('''DROP TABLE IF EXISTS users''')
        c.execute('''DROP TABLE IF EXISTS channels''')
        c.execute('''DROP TABLE IF EXISTS blocked_users''')
        c.execute('''DROP TABLE IF EXISTS admins''')
        c.execute('''DROP TABLE IF EXISTS referrals''')
        
        # Users table - faqat o'zbek tili
        c.execute('''CREATE TABLE IF NOT EXISTS users
                    (user_id BIGINT PRIMARY KEY, 
                     balance REAL DEFAULT 0.0,
                     ref_id BIGINT,
                     payeer TEXT,
                     requested BOOLEAN DEFAULT FALSE,
                     refs_count INTEGER DEFAULT 0,
                     joined_at BIGINT)''')
        
        # Tasks table - faqat o'zbek tili
        c.execute('''CREATE TABLE IF NOT EXISTS tasks
                    (task_id TEXT PRIMARY KEY,
                     amount REAL,
                     text TEXT,
                     created_at BIGINT,
                     creator_id BIGINT)''')
        
        # Submissions table
        c.execute('''CREATE TABLE IF NOT EXISTS submissions
                    (sub_id TEXT PRIMARY KEY,
                     user_id BIGINT,
                     task_id TEXT,
                     file_id TEXT,
                     status TEXT DEFAULT 'pending',
                     created_at BIGINT,
                     accepted_at BIGINT)''')
        
        # Payouts table
        c.execute('''CREATE TABLE IF NOT EXISTS payouts
                    (payout_id TEXT PRIMARY KEY,
                     user_id BIGINT,
                     amount REAL,
                     payeer TEXT,
                     status TEXT DEFAULT 'pending',
                     created_at BIGINT,
                     admin_id BIGINT,
                     paid_at BIGINT,
                     reject_reason TEXT)''')
        
        # Channels table - faqat o'zbek tili
        c.execute('''CREATE TABLE IF NOT EXISTS channels
                    (channel_id SERIAL PRIMARY KEY,
                     username TEXT UNIQUE,
                     name TEXT,
                     added_at BIGINT)''')
        
        # Blocked users table
        c.execute('''CREATE TABLE IF NOT EXISTS blocked_users
                    (user_id BIGINT PRIMARY KEY,
                     blocked_by BIGINT,
                     blocked_at BIGINT,
                     reason TEXT)''')
        
        # Admins table
        c.execute('''CREATE TABLE IF NOT EXISTS admins
                    (user_id BIGINT PRIMARY KEY,
                     added_by BIGINT,
                     added_at BIGINT,
                     level TEXT DEFAULT 'moderator')''')
        
        # Referrals table
        c.execute('''CREATE TABLE IF NOT EXISTS referrals
                    (ref_id SERIAL PRIMARY KEY,
                     referrer_id BIGINT,
                     referred_id BIGINT UNIQUE,
                     joined_at BIGINT,
                     reward_given BOOLEAN DEFAULT FALSE,
                     reward_given_at BIGINT)''')
        
        # Add main admin
        c.execute("INSERT INTO admins (user_id, added_by, added_at, level) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                 (ADMIN_ID, ADMIN_ID, int(time.time()), 'superadmin'))
        
        conn.commit()
        conn.close()
        print("✅ Ma'lumotlar bazasi muvaffaqiyatli ishga tushirildi")
    
    def get_user(self, user_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = c.fetchone()
        conn.close()
        
        if user:
            return {
                "user_id": user[0],
                "balance": user[1],
                "ref": user[2],
                "payeer": user[3],
                "requested": user[4],
                "refs_count": user[5],
                "joined_at": user[6]
            }
        return None
    
    def create_user(self, user_id, ref_id=None):
        conn = self.get_connection()
        c = conn.cursor()
        try:
            c.execute('''INSERT INTO users 
                        (user_id, balance, ref_id, payeer, requested, refs_count, joined_at)
                        VALUES (%s, 0.0, %s, %s, FALSE, 0, %s)
                        ON CONFLICT (user_id) DO NOTHING''',
                     (user_id, ref_id, None, int(time.time())))
            
            # Agar referal bo'lsa, referrals jadvaliga qo'shamiz
            if ref_id:
                c.execute('''INSERT INTO referrals (referrer_id, referred_id, joined_at) 
                            VALUES (%s, %s, %s) ON CONFLICT (referred_id) DO NOTHING''',
                         (ref_id, user_id, int(time.time())))
            
            conn.commit()
        except Exception as e:
            print(f"Foydalanuvchi yaratish xatosi: {e}")
        finally:
            conn.close()
    
    def update_user(self, user_id, updates):
        conn = self.get_connection()
        c = conn.cursor()
        
        try:
            set_clause = ", ".join([f"{key} = %s" for key in updates.keys()])
            values = list(updates.values())
            values.append(user_id)
            
            c.execute(f"UPDATE users SET {set_clause} WHERE user_id = %s", values)
            conn.commit()
        except Exception as e:
            print(f"Foydalanuvchi yangilash xatosi: {e}")
        finally:
            conn.close()
    
    def get_all_users(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users")
        users = c.fetchall()
        conn.close()
        
        result = {}
        for user in users:
            result[str(user[0])] = {
                "balance": user[1],
                "ref": user[2],
                "payeer": user[3],
                "requested": user[4],
                "refs_count": user[5],
                "joined_at": user[6]
            }
        return result
    
    # Tasks methods
    def get_tasks(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM tasks")
        tasks = c.fetchall()
        conn.close()
        
        result = {}
        for task in tasks:
            result[task[0]] = {
                "amount": task[1],
                "text": task[2],
                "created_at": task[3],
                "creator_id": task[4]
            }
        return result
    
    def add_task(self, task_id, amount, text, creator_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO tasks (task_id, amount, text, created_at, creator_id) VALUES (%s, %s, %s, %s, %s)",
                 (task_id, amount, text, int(time.time()), creator_id))
        conn.commit()
        conn.close()
    
    def delete_task(self, task_id):
        conn = self.get_connection()
        c = conn.cursor()
        try:
            c.execute("DELETE FROM submissions WHERE task_id = %s", (task_id,))
            c.execute("DELETE FROM tasks WHERE task_id = %s", (task_id,))
            conn.commit()
            print(f"✅ Vazifa o'chirildi: {task_id}")
        except Exception as e:
            print(f"Vazifa o'chirish xatosi: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    # Submissions methods
    def get_submissions(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM submissions")
        subs = c.fetchall()
        conn.close()
        
        result = {}
        for sub in subs:
            result[sub[0]] = {
                "user_id": sub[1],
                "task_id": sub[2],
                "file_id": sub[3],
                "status": sub[4],
                "created_at": sub[5],
                "accepted_at": sub[6]
            }
        return result
    
    def add_submission(self, sub_id, user_id, task_id, file_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO submissions (sub_id, user_id, task_id, file_id, created_at) VALUES (%s, %s, %s, %s, %s)",
                 (sub_id, user_id, task_id, file_id, int(time.time())))
        conn.commit()
        conn.close()
    
    def update_submission(self, sub_id, updates):
        conn = self.get_connection()
        c = conn.cursor()
        
        set_clause = ", ".join([f"{key} = %s" for key in updates.keys()])
        values = list(updates.values())
        values.append(sub_id)
        
        c.execute(f"UPDATE submissions SET {set_clause} WHERE sub_id = %s", values)
        conn.commit()
        conn.close()
    
    # Payouts methods
    def get_payouts(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM payouts")
        pays = c.fetchall()
        conn.close()
        
        result = {}
        for pay in pays:
            result[pay[0]] = {
                "user_id": pay[1],
                "amount": pay[2],
                "payeer": pay[3],
                "status": pay[4],
                "created_at": pay[5],
                "admin_id": pay[6],
                "paid_at": pay[7],
                "reject_reason": pay[8]
            }
        return result
    
    def add_payout(self, payout_id, user_id, amount, payeer):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO payouts (payout_id, user_id, amount, payeer, created_at) VALUES (%s, %s, %s, %s, %s)",
                 (payout_id, user_id, amount, payeer, int(time.time())))
        conn.commit()
        conn.close()
    
    def update_payout(self, payout_id, updates):
        conn = self.get_connection()
        c = conn.cursor()
        
        set_clause = ", ".join([f"{key} = %s" for key in updates.keys()])
        values = list(updates.values())
        values.append(payout_id)
        
        c.execute(f"UPDATE payouts SET {set_clause} WHERE payout_id = %s", values)
        conn.commit()
        conn.close()
    
    # Channels methods
    def get_channels(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM channels ORDER BY channel_id")
        channels = c.fetchall()
        conn.close()
        
        result = []
        for channel in channels:
            result.append({
                "channel_id": channel[0],
                "username": channel[1],
                "name": channel[2],
                "added_at": channel[3]
            })
        return result
    
    def add_channel(self, username, name):
        conn = self.get_connection()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO channels (username, name, added_at) VALUES (%s, %s, %s)",
                     (username, name, int(time.time())))
            conn.commit()
            return True
        except Exception as e:
            print(f"Kanal qo'shish xatosi: {e}")
            return False
        finally:
            conn.close()
    
    def delete_channel(self, channel_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM channels WHERE channel_id = %s", (channel_id,))
        conn.commit()
        conn.close()
    
    # Blocked users methods
    def get_blocked_users(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM blocked_users")
        blocked = c.fetchall()
        conn.close()
        
        result = {}
        for user in blocked:
            result[str(user[0])] = {
                "blocked_by": user[1],
                "blocked_at": user[2],
                "reason": user[3]
            }
        return result
    
    def block_user(self, user_id, blocked_by, reason=""):
        conn = self.get_connection()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO blocked_users (user_id, blocked_by, blocked_at, reason) VALUES (%s, %s, %s, %s)",
                     (user_id, blocked_by, int(time.time()), reason))
            conn.commit()
            return True
        except Exception as e:
            print(f"Foydalanuvchini bloklash xatosi: {e}")
            return False
        finally:
            conn.close()
    
    def unblock_user(self, user_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM blocked_users WHERE user_id = %s", (user_id,))
        conn.commit()
        conn.close()
    
    def is_user_blocked(self, user_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM blocked_users WHERE user_id = %s", (user_id,))
        result = c.fetchone()
        conn.close()
        return result is not None
    
    # Admins methods
    def get_admins(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM admins")
        admins = c.fetchall()
        conn.close()
        
        result = {}
        for admin in admins:
            result[str(admin[0])] = {
                "added_by": admin[1],
                "added_at": admin[2],
                "level": admin[3]
            }
        return result
    
    def add_admin(self, user_id, added_by, level="moderator"):
        conn = self.get_connection()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO admins (user_id, added_by, added_at, level) VALUES (%s, %s, %s, %s)",
                     (user_id, added_by, int(time.time()), level))
            conn.commit()
            return True
        except Exception as e:
            print(f"Admin qo'shish xatosi: {e}")
            return False
        finally:
            conn.close()
    
    def remove_admin(self, user_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM admins WHERE user_id = %s", (user_id,))
        conn.commit()
        conn.close()
    
    def is_admin(self, user_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM admins WHERE user_id = %s", (user_id,))
        result = c.fetchone()
        conn.close()
        return result is not None
    
    def is_superadmin(self, user_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM admins WHERE user_id = %s AND level = 'superadmin'", (user_id,))
        result = c.fetchone()
        conn.close()
        return result is not None
    
    # Referrals methods
    def get_referrals(self, referrer_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM referrals WHERE referrer_id = %s", (referrer_id,))
        referrals = c.fetchall()
        conn.close()
        
        result = []
        for ref in referrals:
            result.append({
                "ref_id": ref[0],
                "referrer_id": ref[1],
                "referred_id": ref[2],
                "joined_at": ref[3],
                "reward_given": ref[4],
                "reward_given_at": ref[5]
            })
        return result
    
    def update_referral(self, referred_id, updates):
        conn = self.get_connection()
        c = conn.cursor()
        
        set_clause = ", ".join([f"{key} = %s" for key in updates.keys()])
        values = list(updates.values())
        values.append(referred_id)
        
        c.execute(f"UPDATE referrals SET {set_clause} WHERE referred_id = %s", values)
        conn.commit()
        conn.close()
    
    def has_referral(self, referred_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM referrals WHERE referred_id = %s", (referred_id,))
        result = c.fetchone()
        conn.close()
        return result is not None

# Initialize database
db = Database(DATABASE_URL)

# ========== Flask web server for uptime ping ==========
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot ishlayapti", 200

# Run Flask server in a separate thread
threading.Thread(
    target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000))),
    daemon=True
).start()

# ========== User utilities ==========
def get_user(uid):
    user = db.get_user(uid)
    if not user:
        db.create_user(uid)
        user = db.get_user(uid)
    return user

def is_member(channel_username, user_id):
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getChatMember",
            params={"chat_id": channel_username, "user_id": user_id},
            timeout=6
        ).json()
        if not r.get("ok"):
            return False
        status = r["result"]["status"]
        return status in ["member", "administrator", "creator"]
    except Exception:
        return False

def check_all_membership(uid):
    channels = db.get_channels()
    for channel in channels:
        if not is_member(channel["username"], uid):
            return False
    return len(channels) > 0

def get_user_completed_tasks(uid):
    submissions = db.get_submissions()
    completed_tasks = []
    for sub_id, sub in submissions.items():
        if sub["user_id"] == uid and sub["status"] == "accepted":
            completed_tasks.append(sub["task_id"])
    return completed_tasks

def log_to_secret_channel(message):
    try:
        bot.send_message(SECRET_CHANNEL, message)
    except Exception as e:
        print(f"Maxfiy kanalga yozish xatosi: {e}")

# ========== Start ==========
@bot.message_handler(commands=["start"])
def cmd_start(m):
    uid = m.from_user.id
    
    # Check if user is blocked
    if db.is_user_blocked(uid):
        bot.send_message(uid, "❌ Siz ushbu botda bloklangansiz.")
        return
    
    args = m.text.split()
    if len(args) > 1:
        ref = args[1]
        if ref.isdigit() and ref != str(uid):
            # Tekshirish: foydalanuvchi avval referal orqali kirganmi
            if db.has_referral(uid):
                bot.send_message(uid, "❌ Siz avval referal havoladan foydalangansiz. Iltimos, botdan adolatli foydalaning.")
                return
            
            ref_user = db.get_user(int(ref))
            if ref_user:
                # Foydalanuvchini referal bilan yaratamiz
                db.create_user(uid, int(ref))
                
                # Maxfiy kanalga log
                log_to_secret_channel(
                    f"🔗 YANGI REFERAL\n"
                    f"👤 Referal: {uid}\n"
                    f"👥 Taklif qilgan: {ref}\n"
                    f"🕒 Vaqt: {format_uzbekistan_time()}"
                )
    else:
        # Oddiy kirish
        get_user(uid)

    send_join_message(uid)

def send_join_message(uid):
    channels = db.get_channels()
    if not channels:
        bot.send_message(uid, "❌ Kanallar sozlanmagan. Administratorga murojaat qiling.")
        return
    
    markup = types.InlineKeyboardMarkup()
    for channel in channels:
        markup.add(types.InlineKeyboardButton(f"📢 {channel['name']}", url=f"https://t.me/{channel['username'].replace('@','')}"))
    markup.add(types.InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_join"))
    
    bot.send_message(uid, "👋 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "check_join")
def handle_check_join(c):
    uid = c.from_user.id
    if check_all_membership(uid):
        bot.answer_callback_query(c.id, "✅ Siz barcha kanallarga obuna bo'lgansiz!")
        bot.send_message(uid, "✅ Siz barcha kanallarga obuna bo'lgansiz!", reply_markup=main_menu())
        
        # Referal mukofotini tekshirish
        user = get_user(uid)
        if user["ref"]:
            referrals = db.get_referrals(user["ref"])
            for ref in referrals:
                if ref["referred_id"] == uid and not ref["reward_given"]:
                    # Mukofot berish
                    referrer = db.get_user(user["ref"])
                    db.update_user(user["ref"], {
                        "balance": round(referrer.get("balance", 0.0) + REF_REWARD, 2),
                        "refs_count": referrer.get("refs_count", 0) + 1
                    })
                    
                    db.update_referral(uid, {
                        "reward_given": True,
                        "reward_given_at": time.time()
                    })
                    
                    # Taklif qiluvchiga xabar
                    try:
                        bot.send_message(user["ref"], f"🎉 Taklif qilgan do'stingiz kanallarga obuna bo'lganda siz mukofot sifatida {REF_REWARD} RUB olasiz!")
                    except:
                        pass
                    
                    # Maxfiy kanalga log
                    log_to_secret_channel(
                        f"💰 REFERAL MUKOFOTI\n"
                        f"👤 Taklif qilgan: {user['ref']}\n"
                        f"👥 Referal: {uid}\n"
                        f"💎 Miqdor: {REF_REWARD} RUB\n"
                        f"🕒 Vaqt: {format_uzbekistan_time()}"
                    )
    else:
        bot.answer_callback_query(c.id, "❌ Siz barcha kanallarga obuna bo'lmagansiz!", show_alert=True)

# ========== Main menu keyboard ==========
def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("💰 Balans", "👥 Referal")
    kb.add("📤 Pul yechish", "📋 Vazifalar")
    return kb

# ========== Commands for users ==========
@bot.message_handler(func=lambda m: m.text == "💰 Balans")
def cmd_balance(m):
    uid = m.from_user.id
    if db.is_user_blocked(uid):
        bot.send_message(uid, "❌ Siz ushbu botda bloklangansiz.")
        return
    
    u = get_user(uid)
    bot.send_message(uid, f"💰 Balans: <b>{u.get('balance',0.0)}</b> RUB\n👥 Referallar: {u.get('refs_count',0)}")

@bot.message_handler(func=lambda m: m.text == "👥 Referal")
def cmd_ref(m):
    uid = m.from_user.id
    if db.is_user_blocked(uid):
        bot.send_message(uid, "❌ Siz ushbu botda bloklangansiz.")
        return
    
    link = f"https://t.me/{bot.get_me().username}?start={uid}"
    bot.send_message(uid, f"🔗 Sizning referal havolangiz:\n{link}\nHar bir yangi referal uchun +{REF_REWARD} RUB.")

# ========== Withdraw flow ==========
@bot.message_handler(func=lambda m: m.text == "📤 Pul yechish")
def cmd_withdraw(m):
    uid = m.from_user.id
    if db.is_user_blocked(uid):
        bot.send_message(uid, "❌ Siz ushbu botda bloklangansiz.")
        return
    
    u = get_user(uid)
    if u.get("balance",0.0) < MIN_WITHDRAW:
        bot.send_message(uid, f"❌ Minimal yechish miqdori {MIN_WITHDRAW} RUB.")
        return
    bot.send_message(uid, f"💳 Qancha yechmoqchisiz? Miqdorni kiriting (kamida {MIN_WITHDRAW} RUB):")
    bot.register_next_step_handler(m, withdraw_amount_step)

def withdraw_amount_step(m):
    uid = m.from_user.id
    if db.is_user_blocked(uid):
        bot.send_message(uid, "❌ Siz ushbu botda bloklangansiz.")
        return
    
    try:
        amt = float(m.text.replace(",", "."))
    except:
        bot.send_message(uid, f"❌ Noto'g'ri format. Iltimos raqam kiriting (masalan: {MIN_WITHDRAW}).")
        return
    
    u = get_user(uid)
    if amt <= 0 or amt > u.get("balance",0.0):
        bot.send_message(uid, "❌ Noto'g'ri miqdor yoki mablag' yetarli emas.")
        return
    
    if amt < MIN_WITHDRAW:
        bot.send_message(uid, f"❌ Minimal yechish {MIN_WITHDRAW} RUB.")
        return
    
    bot.send_message(uid, "💳 Iltimos Payeer hisob raqamingizni kiriting (masalan: P1000000):")
    bot.register_next_step_handler(m, withdraw_payeer_step, amt)

def withdraw_payeer_step(m, amt):
    uid = m.from_user.id
    if db.is_user_blocked(uid):
        bot.send_message(uid, "❌ Siz ushbu botda bloklangansiz.")
        return
    
    payeer = m.text.strip()
    
    # create payout record
    pid = str(int(time.time()*1000))
    db.add_payout(pid, uid, amt, payeer)
    
    # mark user requested
    db.update_user(uid, {"requested": True})
    
    bot.send_message(uid, "✅ So'rovingiz adminga yuborildi. Tasdiqlanishini kuting.")
    
    # notify admin with accept/reject buttons
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"pay_accept_{pid}"),
        types.InlineKeyboardButton("❌ Rad etish", callback_data=f"pay_reject_{pid}")
    )
    
    admin_msg = (f"📤 Yangi pul yechish so'rovi:\n"
                f"👤 {m.from_user.first_name} (ID: {uid})\n"
                f"💰 Miqdor: {amt} RUB\n"
                f"💳 Payeer: {payeer}")
    
    bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup)
    
    # Maxfiy kanalga log
    log_to_secret_channel(
        f"💸 YANGI PUL YECHISH\n"
        f"👤 User: {uid} ({m.from_user.first_name})\n"
        f"💰 Miqdor: {amt} RUB\n"
        f"💳 Payeer: {payeer}\n"
        f"🕒 Vaqt: {format_uzbekistan_time()}"
    )

# Pul yechish tasdiqlash/rad etish
@bot.callback_query_handler(func=lambda c: c.data.startswith("pay_"))
def handle_pay_action(c):
    if not db.is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, "Faqat admin uchun!", show_alert=True)
        return
    
    action, pid = c.data.split("_")[1], c.data.split("_")[2]
    payouts = db.get_payouts()
    rec = payouts.get(pid)
    
    if not rec:
        bot.answer_callback_query(c.id, "So'rov topilmadi", show_alert=True)
        return
    
    if rec["status"] != "pending":
        bot.answer_callback_query(c.id, "So'rov allaqachon qabul qilingan", show_alert=True)
        return
    
    uid = rec["user_id"]
    
    if action == "accept":
        # Deduct from user balance and mark paid
        u = get_user(uid)
        amt = float(rec["amount"])
        
        if u.get("balance",0.0) < amt:
            bot.answer_callback_query(c.id, "Foydalanuvchi balansida yetarli mablag' yo'q!", show_alert=True)
            return
        
        db.update_user(uid, {
            "balance": round(u.get("balance",0.0) - amt, 2),
            "requested": False
        })
        
        db.update_payout(pid, {
            "status": "paid",
            "admin_id": c.from_user.id,
            "paid_at": time.time()
        })
        
        bot.answer_callback_query(c.id, "✅ To'lov tasdiqlandi.")
        bot.edit_message_text(f"✅ Tasdiqlandi: {c.message.text}", c.message.chat.id, c.message.message_id)
        
        # Notify user
        try:
            bot.send_message(uid, f"💸 Sizga {amt} RUB to'lab berildi. Rahmat!")
        except:
            pass
        
        # Maxfiy kanalga log
        log_to_secret_channel(
            f"✅ PUL YECHISH ТАСДИҚЛАНДИ\n"
            f"👤 User: {uid}\n"
            f"💰 Miqdor: {amt} RUB\n"
            f"👨‍💼 Admin: {c.from_user.id}\n"
            f"🕒 Vaqt: {format_uzbekistan_time()}"
        )
        
    elif action == "reject":
        bot.send_message(c.from_user.id, f"❌ Pul so'rovini rad etish: {pid}\nSababni kiriting:")
        bot.register_next_step_handler(c.message, process_pay_reject_reason, pid, uid)

def process_pay_reject_reason(m, pid, uid):
    reason = m.text
    
    db.update_payout(pid, {
        "status": "rejected",
        "admin_id": m.from_user.id,
        "reject_reason": reason
    })
    
    db.update_user(uid, {"requested": False})
    
    bot.send_message(m.from_user.id, f"✅ Pul so'rovi rad etildi.")
    
    # Notify user
    try:
        bot.send_message(uid, f"❌ Sizning pul yechish so'rovingiz rad etildi. Sabab: {reason}")
    except:
        pass
    
    # Maxfiy kanalga log
    log_to_secret_channel(
        f"❌ PUL YECHISH RAD ETILDI\n"
        f"👤 User: {uid}\n"
        f"📝 Sabab: {reason}\n"
        f"👨‍💼 Admin: {m.from_user.id}\n"
        f"🕒 Vaqt: {format_uzbekistan_time()}"
    )

# ========== Admin panel ==========
@bot.message_handler(commands=["admin"])
def cmd_admin(m):
    if not db.is_admin(m.from_user.id):
        return
    
    users_data = db.get_all_users()
    payouts_data = db.get_payouts()
    
    today = get_uzbekistan_time().date()
    joins_today = 0
    for u in users_data.values():
        try:
            j = datetime.fromtimestamp(u.get("joined_at",0)).date()
            if j == today:
                joins_today += 1
        except:
            pass
    
    total_users = len(users_data)
    total_paid = 0.0
    for p in payouts_data.values():
        if p.get("status") == "paid":
            total_paid += float(p.get("amount",0.0))
    
    blocked_users = len(db.get_blocked_users())
    channels = db.get_channels()
    admins = db.get_admins()
    
    msg = (f"📊 <b>Admin paneli</b>\n\n"
          f"🟢 Bugun qo'shilganlar: {joins_today}\n"
          f"👥 Jami foydalanuvchilar: {total_users}\n"
          f"🚫 Bloklangan: {blocked_users}\n"
          f"📢 Kanallar: {len(channels)}\n"
          f"👨‍💼 Adminlar: {len(admins)}\n"
          f"💸 Jami to'langan: {round(total_paid,2)} RUB\n\n"
          "Buyruqlar:\n"
          "/tasks - Vazifalar\n"
          "/addtask - Vazifa qo'shish\n"
          "/payouts - So'rovlar\n"
          "/broadcast - Xabar tarqatish\n"
          "/channels - Kanallar\n"
          "/block - Bloklash\n"
          "/unblock - Blokni olish\n"
          "/admins - Adminlar\n"
          "/addadmin - Admin qo'shish\n"
          "/deladmin - Admin o'chirish")
    bot.send_message(m.from_user.id, msg)

@bot.message_handler(commands=["tasks"])
def cmd_tasks(m):
    if not db.is_admin(m.from_user.id):
        return
    
    tasks = db.get_tasks()
    if not tasks:
        bot.send_message(m.from_user.id, "Vazifalar yo'q.")
        return
    
    s = "📋 Vazifalar:\n\n"
    for tid, t in tasks.items():
        s += f"ID: {tid}\nHaқ: {t['amount']} RUB\nMatn: {t['text']}\nQo'shilgan: {format_uzbekistan_time(t['created_at'])}\n\n"
    
    bot.send_message(m.from_user.id, s)

@bot.message_handler(commands=["addtask"])
def cmd_addtask(m):
    if not db.is_admin(m.from_user.id):
        return
    
    txt = m.text.replace("/addtask","",1).strip()
    if "|" not in txt:
        bot.send_message(m.from_user.id, "Format: /addtask <summa>|<matn>\n\nMisol: /addtask 2|Kanalga obuna bo'ling")
        return
    
    amt_str, text = txt.split("|",1)
    try:
        amt = float(amt_str.strip())
    except:
        bot.send_message(m.from_user.id, "Xato: summa raqam bo'lishi kerak.")
        return
    
    tid = str(int(time.time()*1000))
    db.add_task(tid, amt, text.strip(), m.from_user.id)
    bot.send_message(m.from_user.id, f"✅ Vazifa qo'shildi. ID: {tid}")

# ========== YANGI: /deltask komandasi ==========
@bot.message_handler(commands=["deltask"])
def cmd_deltask(m):
    if not db.is_admin(m.from_user.id):
        bot.send_message(m.chat.id, "❌ Sizda admin huquqlari yo'q.")
        return
    
    task_id = m.text.replace("/deltask","",1).strip()
    if not task_id:
        bot.send_message(m.chat.id, "❌ Format: /deltask <task_id>\n\nMisol: /deltask 1762087459628")
        return
    
    # Vazifalar ro'yxatini olish
    tasks = db.get_tasks()
    
    if task_id not in tasks:
        bot.send_message(m.chat.id, f"❌ Vazifa topilmadi: {task_id}\n\n/tasks buyrug'i bilan mavjud vazifalarni ko'ring.")
        return
    
    try:
        # Vazifani o'chirish
        db.delete_task(task_id)
        bot.send_message(m.chat.id, f"✅ Vazifa muvaffaqiyatli o'chirildi:\nID: {task_id}")
        
        # Log
        print(f"Vazifa o'chirildi: {task_id} by {m.from_user.id}")
        
    except Exception as e:
        bot.send_message(m.chat.id, f"❌ Xatolik: {str(e)}")
        print(f"Deltask xatosi: {e}")

@bot.message_handler(commands=["payouts"])
def cmd_payouts(m):
    if not db.is_admin(m.from_user.id):
        return
    
    payouts = db.get_payouts()
    if not payouts:
        bot.send_message(m.from_user.id, "So'rovlar yo'q.")
        return
    
    s = "📥 Pul so'rovlari:\n\n"
    for pid, p in payouts.items():
        status_emoji = "✅" if p['status'] == 'paid' else "❌" if p['status'] == 'rejected' else "⏳"
        s += f"ID: {pid}\nFoydalanuvchi: {p['user_id']}\nSumma: {p['amount']}\nHolat: {status_emoji} {p['status']}\nYaratilgan: {format_uzbekistan_time(p['created_at'])}\n\n"
    bot.send_message(m.from_user.id, s)

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(m):
    if not db.is_admin(m.from_user.id):
        return
    
    msg_text = m.text.replace("/broadcast","",1).strip()
    if not msg_text:
        bot.send_message(m.from_user.id, "Format: /broadcast <xabar>")
        return
    
    users_data = db.get_all_users()
    sent = 0
    failed = 0
    
    for uid_str in users_data.keys():
        try:
            bot.send_message(int(uid_str), f"📢 Admin xabari:\n\n{msg_text}")
            sent += 1
        except:
            failed += 1
    
    bot.send_message(m.from_user.id, f"📊 Xabar tarqatish yakunlandi:\n✅ Yuborildi: {sent}\n❌ Yuborilmadi: {failed}")

@bot.message_handler(commands=["channels"])
def cmd_channels(m):
    if not db.is_admin(m.from_user.id):
        return
    
    channels = db.get_channels()
    if not channels:
        bot.send_message(m.from_user.id, "Kanallar qo'shilmagan.")
        return
    
    s = "📢 Kanallar:\n\n"
    for channel in channels:
        s += f"ID: {channel['channel_id']}\nUsername: {channel['username']}\nNomi: {channel['name']}\n\n"
    
    s += "Kanal qo'shish: /addchannel @username|Nomi\nKanal o'chirish: /delchannel id"
    bot.send_message(m.from_user.id, s)

@bot.message_handler(commands=["addchannel"])
def cmd_addchannel(m):
    if not db.is_admin(m.from_user.id):
        return
    
    txt = m.text.replace("/addchannel","",1).strip()
    if "|" not in txt:
        bot.send_message(m.from_user.id, "Format: /addchannel @username|Nomi\n\nMisol: /addchannel @ishowxworld|iShow World")
        return
    
    username, name = txt.split("|",1)
    if not username.startswith('@'):
        username = '@' + username
    
    if db.add_channel(username.strip(), name.strip()):
        bot.send_message(m.from_user.id, f"✅ Kanal {name} qo'shildi.")
    else:
        bot.send_message(m.from_user.id, "❌ Kanal qo'shishda xato.")

@bot.message_handler(commands=["delchannel"])
def cmd_delchannel(m):
    if not db.is_admin(m.from_user.id):
        return
    
    channel_id = m.text.replace("/delchannel","",1).strip()
    if not channel_id.isdigit():
        bot.send_message(m.from_user.id, "Format: /delchannel <id>")
        return
    
    db.delete_channel(int(channel_id))
    bot.send_message(m.from_user.id, f"✅ Kanal {channel_id} o'chirildi.")

@bot.message_handler(commands=["block"])
def cmd_block(m):
    if not db.is_admin(m.from_user.id):
        return
    
    txt = m.text.replace("/block","",1).strip()
    if not txt:
        bot.send_message(m.from_user.id, "Format: /block <user_id> [sabab]")
        return
    
    parts = txt.split(' ', 1)
    user_id = parts[0]
    reason = parts[1] if len(parts) > 1 else ""
    
    if not user_id.isdigit():
        bot.send_message(m.from_user.id, "❌ User ID raqam bo'lishi kerak.")
        return
    
    user_id = int(user_id)
    if db.block_user(user_id, m.from_user.id, reason):
        bot.send_message(m.from_user.id, f"✅ Foydalanuvchi {user_id} bloklandi.")
    else:
        bot.send_message(m.from_user.id, "❌ Foydalanuvchini bloklashda xato.")

@bot.message_handler(commands=["unblock"])
def cmd_unblock(m):
    if not db.is_admin(m.from_user.id):
        return
    
    user_id = m.text.replace("/unblock","",1).strip()
    if not user_id.isdigit():
        bot.send_message(m.from_user.id, "Format: /unblock <user_id>")
        return
    
    user_id = int(user_id)
    db.unblock_user(user_id)
    bot.send_message(m.from_user.id, f"✅ Foydalanuvchi {user_id} blokdan chiqarildi.")

@bot.message_handler(commands=["admins"])
def cmd_admins(m):
    if not db.is_admin(m.from_user.id):
        return
    
    admins = db.get_admins()
    if not admins:
        bot.send_message(m.from_user.id, "Adminlar yo'q.")
        return
    
    s = "👨‍💼 Adminlar:\n\n"
    for admin_id, admin_data in admins.items():
        s += f"ID: {admin_id}\nDaraja: {admin_data['level']}\nQo'shilgan: {format_uzbekistan_time(admin_data['added_at'])}\n\n"
    
    bot.send_message(m.from_user.id, s)

@bot.message_handler(commands=["addadmin"])
def cmd_addadmin(m):
    if not db.is_superadmin(m.from_user.id):
        bot.send_message(m.from_user.id, "❌ Faqat super admin uchun.")
        return
    
    txt = m.text.replace("/addadmin","",1).strip()
    if not txt:
        bot.send_message(m.from_user.id, "Format: /addadmin <user_id> [daraja]")
        return
    
    parts = txt.split(' ', 1)
    user_id = parts[0]
    level = parts[1] if len(parts) > 1 else "moderator"
    
    if not user_id.isdigit():
        bot.send_message(m.from_user.id, "❌ User ID raqam bo'lishi kerak.")
        return
    
    user_id = int(user_id)
    if db.add_admin(user_id, m.from_user.id, level):
        bot.send_message(m.from_user.id, f"✅ Foydalanuvchi {user_id} {level} sifatida qo'shildi.")
    else:
        bot.send_message(m.from_user.id, "❌ Admin qo'shishda xato.")

@bot.message_handler(commands=["deladmin"])
def cmd_deladmin(m):
    if not db.is_superadmin(m.from_user.id):
        bot.send_message(m.from_user.id, "❌ Faqat super admin uchun.")
        return
    
    user_id = m.text.replace("/deladmin","",1).strip()
    if not user_id.isdigit():
        bot.send_message(m.from_user.id, "Format: /deladmin <user_id>")
        return
    
    user_id = int(user_id)
    if user_id == m.from_user.id:
        bot.send_message(m.from_user.id, "❌ O'zingizni o'chira olmaysiz.")
        return
    
    db.remove_admin(user_id)
    bot.send_message(m.from_user.id, f"✅ Admin {user_id} o'chirildi.")

# ========== User: view tasks & submit ==========
@bot.message_handler(func=lambda m: m.text == "📋 Vazifalar")
def user_tasks(m):
    uid = m.from_user.id
    if db.is_user_blocked(uid):
        bot.send_message(uid, "❌ Siz ushbu botda bloklangansiz.")
        return
    
    tasks = db.get_tasks()
    if not tasks:
        bot.send_message(uid, "Hozircha vazifalar yo'q.")
        return
    
    completed_tasks = get_user_completed_tasks(uid)
    
    for tid, t in tasks.items():
        if tid in completed_tasks:
            continue  # O'tkazib yuborilgan vazifalar
        
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Vazifani bajarib screenshot yuborish", callback_data=f"do_task_{tid}")
        )
        
        # Adminlar uchun o'chirish tugmasi
        if db.is_admin(uid):
            markup.row(
                types.InlineKeyboardButton("🗑️ Vazifani o'chirish", callback_data=f"del_task_{tid}")
            )
        
        bot.send_message(uid, f"📌 <b>Vazifa ID {tid}</b>\n💰 Mukofot: {t['amount']} RUB\n\n{t['text']}", reply_markup=markup)

# ========== YANGI: Vazifani o'chirish tugmasi ==========
@bot.callback_query_handler(func=lambda c: c.data.startswith("del_task_"))
def handle_delete_task(c):
    uid = c.from_user.id
    if not db.is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Faqat adminlar vazifani o'chira oladi!", show_alert=True)
        return
    
    task_id = c.data.split("_")[2]
    
    try:
        # Vazifani o'chirish
        db.delete_task(task_id)
        bot.answer_callback_query(c.id, "✅ Vazifa muvaffaqiyatli o'chirildi!")
        bot.delete_message(c.message.chat.id, c.message.message_id)
        
        # Maxfiy kanalga log
        log_to_secret_channel(
            f"🗑️ VAZIFA O'CHIRILDI\n"
            f"👤 Admin: {uid}\n"
            f"📝 Vazifa ID: {task_id}\n"
            f"🕒 Vaqt: {format_uzbekistan_time()}"
        )
        
    except Exception as e:
        bot.answer_callback_query(c.id, f"❌ Xatolik: {str(e)}", show_alert=True)

last_task_for_user = {}

@bot.callback_query_handler(func=lambda c: c.data.startswith("do_task_"))
def do_task_cb(c):
    uid = c.from_user.id
    if db.is_user_blocked(uid):
        bot.answer_callback_query(c.id, "❌ Siz ushbu botda bloklangansiz.", show_alert=True)
        return
    
    tid = c.data.split("_",2)[2]
    bot.answer_callback_query(c.id, "Iltimos vazifani bajaring va screenshot (photo) yuboring, shu xabarga javoban yuboring.")
    bot.send_message(uid, f"Vazifa ID {tid} uchun screenshot yuboring. Shu xabarga javoban surat yuboring.")
    last_task_for_user[str(uid)] = tid

@bot.message_handler(content_types=["photo"])
def photo_handler(m):
    uid = m.from_user.id
    
    if db.is_user_blocked(uid):
        bot.send_message(uid, "❌ Siz ushbu botda bloklangansiz.")
        return
    
    if str(uid) not in last_task_for_user:
        bot.send_message(uid, "Agar vazifa uchun screenshot yuborayotgan bo'lsangiz, avval vazifani tanlang.")
        return
    
    tid = last_task_for_user.pop(str(uid))
    file_id = m.photo[-1].file_id
    
    # save submission
    sid = str(int(time.time()*1000))
    db.add_submission(sid, uid, tid, file_id)
    
    # notify admin with approve/reject buttons
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Qabul qilish", callback_data=f"sub_accept_{sid}"),
        types.InlineKeyboardButton("❌ Rad etish", callback_data=f"sub_reject_{sid}")
    )
    
    admin_msg = (f"📸 Yangi vazifa topshirildi.\n"
                f"👤 Foydalanuvchi: {m.from_user.first_name} (ID: {uid})\n"
                f"📝 Vazifa ID: {tid}\n"
                f"🆔 Submission ID: {sid}")
    
    bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup)
    
    # forward photo to admin for review
    try:
        bot.forward_message(ADMIN_ID, uid, m.message_id)
    except:
        try:
            bot.send_photo(ADMIN_ID, file_id, caption=f"Foydalanuvchi {uid} - Vazifa {tid}")
        except:
            pass
    
    bot.send_message(uid, "✅ Sizning screenshot yuborildi. Admin 24 soat ichida tekshiradi.")
    
    # Maxfiy kanalga log
    log_to_secret_channel(
        f"📸 YANGI VAZIFA BAJARILDI\n"
        f"👤 User: {uid} ({m.from_user.first_name})\n"
        f"📝 Vazifa ID: {tid}\n"
        f"🆔 Submission ID: {sid}\n"
        f"🕒 Vaqt: {format_uzbekistan_time()}"
    )

# Vazifa tasdiqlash/rad etish
@bot.callback_query_handler(func=lambda c: c.data.startswith("sub_"))
def handle_sub_action(c):
    if not db.is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, "Faqat admin uchun!", show_alert=True)
        return
    
    action, sid = c.data.split("_")[1], c.data.split("_")[2]
    submissions = db.get_submissions()
    sub = submissions.get(sid)
    
    if not sub:
        bot.answer_callback_query(c.id, "Topilmadi", show_alert=True)
        return
    
    if sub["status"] != "pending":
        bot.answer_callback_query(c.id, "Allaqachon qabul qilingan", show_alert=True)
        return
    
    tid = sub["task_id"]
    tasks = db.get_tasks()
    task = tasks.get(tid)
    
    if not task:
        bot.answer_callback_query(c.id, "Vazifa topilmadi", show_alert=True)
        return
    
    uid = sub["user_id"]
    
    if action == "accept":
        # reward user
        user = get_user(uid)
        db.update_user(uid, {
            "balance": round(user.get("balance",0.0) + float(task["amount"]), 2)
        })
        
        db.update_submission(sid, {
            "status": "accepted",
            "accepted_at": time.time()
        })
        
        bot.answer_callback_query(c.id, "✅ Vazifa qabul qilindi va mukofot qo'shildi.")
        bot.edit_message_text(f"✅ Qabul qilindi: {c.message.text}", c.message.chat.id, c.message.message_id)
        
        try:
            bot.send_message(uid, f"🎉 Sizga {task['amount']} RUB mukofot berildi (Vazifa: {tid}).")
        except:
            pass
        
        # Maxfiy kanalga log
        log_to_secret_channel(
            f"✅ VAZIFA ТАСДИҚЛАНДИ\n"
            f"👤 User: {uid}\n"
            f"📝 Vazifa ID: {tid}\n"
            f"💰 Mukofot: {task['amount']} RUB\n"
            f"👨‍💼 Admin: {c.from_user.id}\n"
            f"🕒 Vaqt: {format_uzbekistan_time()}"
        )
        
    elif action == "reject":
        bot.send_message(c.from_user.id, f"❌ Vazifani rad etish: {sid}\nSababni kiriting:")
        bot.register_next_step_handler(c.message, process_sub_reject_reason, sid, uid, tid)

def process_sub_reject_reason(m, sid, uid, tid):
    reason = m.text
    
    db.update_submission(sid, {
        "status": "rejected"
    })
    
    bot.send_message(m.from_user.id, f"✅ Vazifa rad etildi.")
    
    # Notify user
    try:
        bot.send_message(uid, f"❌ Sizning vazifangiz rad etildi. Sabab: {reason}")
    except:
        pass
    
    # Maxfiy kanalga log
    log_to_secret_channel(
        f"❌ VAZIFA RAD ETILDI\n"
        f"👤 User: {uid}\n"
        f"📝 Vazifa ID: {tid}\n"
        f"📝 Sabab: {reason}\n"
        f"👨‍💼 Admin: {m.from_user.id}\n"
        f"🕒 Vaqt: {format_uzbekistan_time()}"
    )

# ========== Background: referral check ==========
def referral_check_worker():
    while True:
        users_data = db.get_all_users()
        
        for uid_str, u in users_data.items():
            try:
                uid = int(uid_str)
                
                if db.is_user_blocked(uid):
                    continue
                
                # Referral check - remove reward if user left channel
                ref_id = u.get("ref")
                if ref_id:
                    if not check_all_membership(uid):
                        # User left channel, remove reward from referrer
                        referrals = db.get_referrals(ref_id)
                        for ref in referrals:
                            if ref["referred_id"] == uid and ref["reward_given"]:
                                # Referrer va referred ni yangilash
                                referrer = db.get_user(ref_id)
                                if referrer:
                                    new_balance = max(0, referrer.get("balance", 0.0) - REF_REWARD)
                                    db.update_user(ref_id, {
                                        "balance": new_balance,
                                        "refs_count": max(0, referrer.get("refs_count", 0) - 1)
                                    })
                                
                                db.update_referral(uid, {
                                    "reward_given": False,
                                    "reward_given_at": None
                                })
                                
                                # Notify referrer
                                try:
                                    bot.send_message(ref_id, f"❌ Sizning referalingiz kanaldan chiqib ketdi. {REF_REWARD} RUB hisobingizdan olindi.")
                                except:
                                    pass
            except:
                continue
        
        time.sleep(3600)  # Har 1 soatda tekshiradi

t = threading.Thread(target=referral_check_worker, daemon=True)
t.start()

# ========== Error handler ==========
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    print(f"Xabar qabul qilindi {message.from_user.id}: {message.text}")

# ========== Run bot ==========
if __name__ == "__main__":
    print("Bot ishga tushdi...")
    try:
        bot.infinity_polling()
    except Exception as e:
        print(f"Bot xatosi: {e}")
        time.sleep(5)
