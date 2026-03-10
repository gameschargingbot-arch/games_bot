import os
import asyncio
import psycopg2
import pandas as pd
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    ContextTypes, ConversationHandler, filters
)

# ======================================
# CONFIG & ENV
# ======================================
load_dotenv()
ADMIN_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
USER_TOKEN = os.getenv("USER_BOT_TOKEN")
DB_URL = os.getenv("NEON_DB_URL")
FERNET_KEY = os.getenv("FERNET_KEY").encode()

cipher_suite = Fernet(FERNET_KEY)

# States
(ADMIN_MAIN, ADD_CHOICE, ADD_CAT, ADD_SUB, ADD_CODES,
 USER_MGMT_MENU, ADD_USER_ID, CHANGE_PASS_VAL, REMOVE_USER_ID,
 USER_SELECT_CAT, USER_SELECT_SUB) = range(11)

# ======================================
# DATABASE HELPERS
# ======================================
def get_connection():
    safe_url = DB_URL + ("?sslmode=require" if "sslmode=require" not in DB_URL else "")
    return psycopg2.connect(safe_url)

def get_user_role(tg_id):
    """Checks the DB for the Telegram ID and returns the role."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            # We assume 'username' in your table stores the Telegram ID string
            cur.execute("SELECT role FROM users WHERE username = %s", (str(tg_id),))
            result = cur.fetchone()
            return result[0] if result else None
    except:
        return None

# ======================================
# KEYBOARDS
# ======================================
def get_admin_main_keyboard():
    return ReplyKeyboardMarkup([
        ['📊 الاحصائيات', '➕ اضافة اكواد'],
        ['👤 إدارة المستخدمين', '📥 تصدير Excel']
    ], resize_keyboard=True)

def get_user_main_keyboard():
    return ReplyKeyboardMarkup([['📂 عرض الأقسام']], resize_keyboard=True)

def get_user_mgmt_keyboard():
    return ReplyKeyboardMarkup([
        ['➕ إضافة مستخدم ID', '❌ حذف مستخدم'],
        ['⬅️ عودة']
    ], resize_keyboard=True)

# ======================================
# AUTHENTICATION LOGIC (ID BASED)
# ======================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    role = get_user_role(tg_id)

    if role == "admin":
        await update.message.reply_text(f"👑 أهلاً بك أيها المسؤول (ID: {tg_id})", reply_markup=get_admin_main_keyboard())
        return ADMIN_MAIN
    elif role == "user":
        await update.message.reply_text(f"👋 أهلاً بك (ID: {tg_id})", reply_markup=get_user_main_keyboard())
        return USER_SELECT_CAT
    else:
        await update.message.reply_text(f"❌ غير مسجل. رقم الـ ID الخاص بك هو: `{tg_id}`", parse_mode="Markdown")
        return ConversationHandler.END

# ======================================
# ADMIN LOGIC
# ======================================
async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📊 الاحصائيات':
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM code WHERE is_active=TRUE")
            active = cur.fetchone()[0]
            await update.message.reply_text(f"📈 الأكواد المتاحة حالياً: {active}")
    elif text == '➕ اضافة اكواد':
        kb = [['بدون قسم فرعي', 'مع قسم فرعي'], ['⬅️ عودة']]
        await update.message.reply_text("طريقة الإضافة:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return ADD_CHOICE
    elif text == '👤 إدارة المستخدمين':
        await update.message.reply_text("إدارة المستخدمين:", reply_markup=get_user_mgmt_keyboard())
        return USER_MGMT_MENU
    return ADMIN_MAIN

async def add_choice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    if choice == '⬅️ عودة':
        await update.message.reply_text("القائمة الرئيسية:", reply_markup=get_admin_main_keyboard())
        return ADMIN_MAIN
    context.user_data['mode'] = 'sub' if 'مع' in choice else 'single'
    await update.message.reply_text("أدخل اسم القسم الرئيسي:", reply_markup=ReplyKeyboardRemove())
    return ADD_CAT

async def save_codes_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    codes = update.message.text.split('\n')
    main_cat = context.user_data['main_cat']
    sub_cat = context.user_data.get('sub_cat')
    
    with get_connection() as conn, conn.cursor() as cur:
        # Parent lookup
        cur.execute("INSERT INTO code (name, is_active) SELECT %s, TRUE WHERE NOT EXISTS (SELECT 1 FROM code WHERE name=%s AND parent_id IS NULL) RETURNING id", (main_cat, main_cat))
        res = cur.fetchone()
        parent_id = res[0] if res else None # Simplified for demo
        
        target_name = sub_cat if sub_cat else main_cat
        for c in codes:
            if c.strip():
                enc = cipher_suite.encrypt(c.strip().encode()).decode()
                cur.execute("INSERT INTO code (name, code, is_active, parent_id) VALUES (%s, %s, TRUE, %s)", (target_name, enc, parent_id))
        conn.commit()
    await update.message.reply_text("✅ تم الحفظ", reply_markup=get_admin_main_keyboard())
    return ADMIN_MAIN

# ======================================
# USER MANAGEMENT (ID BASED)
# ======================================
async def user_mgmt_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '➕ إضافة مستخدم ID':
        await update.message.reply_text("أرسل رقم الـ Telegram ID للمستخدم الجديد:", reply_markup=ReplyKeyboardRemove())
        return ADD_USER_ID
    elif text == '❌ حذف مستخدم':
        await update.message.reply_text("أرسل الـ ID المراد حذفه:")
        return REMOVE_USER_ID
    elif text == '⬅️ عودة':
        await update.message.reply_text("القائمة الرئيسية", reply_markup=get_admin_main_keyboard())
        return ADMIN_MAIN

async def add_user_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_id = update.message.text
    with get_connection() as conn, conn.cursor() as cur:
        # Password hashed just to satisfy DB schema, but we use ID for login
        dummy_pass = generate_password_hash("id_login") 
        cur.execute("INSERT INTO users (username, pass, role) VALUES (%s, %s, 'user')", (new_id, dummy_pass))
        conn.commit()
    await update.message.reply_text(f"✅ تم تفعيل ID: {new_id}", reply_markup=get_user_mgmt_keyboard())
    return USER_MGMT_MENU

# ======================================
# USER BOT Logic
# ======================================
async def user_cat_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT name FROM code WHERE parent_id IS NULL")
        cats = [[r[0]] for r in cur.fetchall()]
    await update.message.reply_text("اختر القسم:", reply_markup=ReplyKeyboardMarkup(cats, resize_keyboard=True))
    return USER_SELECT_CAT

# ======================================
# MAIN RUNNER
# ======================================
async def main():
    # 1. ADMIN BOT
    admin_app = ApplicationBuilder().token(ADMIN_TOKEN).build()
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            ADMIN_MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu_handler)],
            ADD_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_choice_handler)],
            ADD_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (c.user_data.update({'main_cat': u.message.text}), u.message.reply_text("فرعي؟") or ADD_SUB if c.user_data['mode']=='sub' else ADD_CODES)[-1])],
            ADD_SUB: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (c.user_data.update({'sub_cat': u.message.text}), u.message.reply_text("أرسل الأكواد:"))[-1] or ADD_CODES)],
            ADD_CODES: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_codes_handler)],
            USER_MGMT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_mgmt_router)],
            ADD_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_user_final)],
            REMOVE_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (get_connection().cursor().execute("DELETE FROM users WHERE username=%s",(u.message.text,)), u.message.reply_text("تم"))[-1] or USER_MGMT_MENU)],
        },
        fallbacks=[CommandHandler("start", start_command)]
    )
    admin_app.add_handler(admin_conv)

    # 2. USER BOT
    user_app = ApplicationBuilder().token(USER_TOKEN).build()
    user_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            USER_SELECT_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_cat_view)],
        },
        fallbacks=[CommandHandler("start", start_command)]
    )
    user_app.add_handler(user_conv)

    # Initialize Both
    await admin_app.initialize()
    await user_app.initialize()
    await admin_app.start()
    await user_app.start()

    print("🚀 Bots started. Listening to Admin and User tokens...")
    
    await asyncio.gather(
        admin_app.updater.start_polling(),
        user_app.updater.start_polling()
    )
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
