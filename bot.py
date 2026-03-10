import os
import asyncio
import psycopg2
import hashlib
import pandas as pd
import sys
from datetime import datetime
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    ContextTypes, ConversationHandler, filters
)

# Reconfigure output for Unicode support
if sys.version_info >= (3, 7):
    sys.stdout.reconfigure(encoding='utf-8')

# ======================================
# CONFIG & ENV
# ======================================
load_dotenv()
ADMIN_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
USER_TOKEN = os.getenv("USER_BOT_TOKEN")
DB_URL = os.getenv("NEON_DB_URL")
FERNET_KEY = os.getenv("FERNET_KEY").encode()

cipher_suite = Fernet(FERNET_KEY)

# Conversation States
(ADMIN_MAIN, ADD_CHOICE, ADD_CAT, ADD_SUB, ADD_CODES,
 USER_MGMT_MENU, ADD_USER_ID, REMOVE_USER_ID,
 USER_MAIN, USER_SELECT_CAT, USER_SELECT_SUB) = range(11)

# ======================================
# CORE HELPERS
# ======================================
def get_connection():
    safe_url = DB_URL
    if "sslmode=require" not in safe_url:
        safe_url += "?sslmode=require"
    return psycopg2.connect(safe_url)

def hash_id(tg_id: int) -> str:
    """Creates a deterministic hash of the Telegram ID for secure login."""
    return hashlib.sha256(str(tg_id).encode()).hexdigest()

def get_role_by_id(tg_id: int):
    h_id = hash_id(tg_id)
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE hashed_id = %s", (h_id,))
            res = cur.fetchone()
            return res[0] if res else None
    except Exception:
        return None

# ======================================
# KEYBOARDS
# ======================================
def kb_admin_main():
    return ReplyKeyboardMarkup([
        ['📊 الاحصائيات', '➕ اضافة اكواد'], 
        ['👤 إدارة المستخدمين', '📥 تصدير Excel']
    ], resize_keyboard=True)

def kb_user_main():
    return ReplyKeyboardMarkup([['📂 عرض الأقسام']], resize_keyboard=True)

def kb_user_mgmt():
    return ReplyKeyboardMarkup([
        ['➕ إضافة مستخدم ID', '❌ حذف مستخدم'], 
        ['⬅️ عودة']
    ], resize_keyboard=True)

# ======================================
# SHARED AUTH & START
# ======================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    role = get_role_by_id(tg_id)

    if role == "admin":
        await update.message.reply_text("👑 لوحة تحكم المسؤول", reply_markup=kb_admin_main())
        return ADMIN_MAIN
    elif role == "user":
        await update.message.reply_text("👋 أهلاً بك في بوت الأكواد.", reply_markup=kb_user_main())
        return USER_MAIN
    else:
        await update.message.reply_text(f"❌ غير مسجل. الـ ID الخاص بك: `{tg_id}`", parse_mode="Markdown")
        return ConversationHandler.END

# ======================================
# ADMIN: CODE ADDITION FUNCTIONS
# ======================================
async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📊 الاحصائيات':
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM code WHERE is_active=TRUE")
            active = cur.fetchone()[0]
            await update.message.reply_text(f"📊 الأكواد المتوفرة: {active}")
    elif text == '➕ اضافة اكواد':
        kb = [['بدون قسم فرعي', 'مع قسم فرعي'], ['⬅️ عودة']]
        await update.message.reply_text("اختر طريقة الإضافة:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return ADD_CHOICE
    elif text == '👤 إدارة المستخدمين':
        await update.message.reply_text("إدارة الوصول بالـ ID:", reply_markup=kb_user_mgmt())
        return USER_MGMT_MENU
    elif text == '📥 تصدير Excel':
        await update.message.reply_text("⌛ جاري استخراج البيانات...")
        with get_connection() as conn:
            df = pd.read_sql("SELECT name, code, is_active FROM code", conn)
        df['code'] = df['code'].apply(lambda x: cipher_suite.decrypt(x.encode()).decode() if x else "N/A")
        df.to_excel("export.xlsx", index=False)
        await update.message.reply_document(document=open("export.xlsx", "rb"))
    return ADMIN_MAIN

async def add_choice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '⬅️ عودة':
        await update.message.reply_text("الرئيسية", reply_markup=kb_admin_main())
        return ADMIN_MAIN
    context.user_data['mode'] = 'sub' if 'مع' in text else 'single'
    await update.message.reply_text("أدخل اسم القسم الرئيسي:", reply_markup=ReplyKeyboardRemove())
    return ADD_CAT

async def add_cat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['main_cat'] = update.message.text
    if context.user_data['mode'] == 'sub':
        await update.message.reply_text("أدخل اسم القسم الفرعي:")
        return ADD_SUB
    await update.message.reply_text("أرسل قائمة الأكواد (كود في كل سطر):")
    return ADD_CODES

async def add_sub_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sub_cat'] = update.message.text
    await update.message.reply_text("أرسل قائمة الأكواد الآن:")
    return ADD_CODES

async def save_codes_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_codes = update.message.text.split('\n')
    main_cat = context.user_data['main_cat']
    sub_cat = context.user_data.get('sub_cat')
    
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO code (name, is_active) SELECT %s, TRUE WHERE NOT EXISTS (SELECT 1 FROM code WHERE name=%s AND parent_id IS NULL) RETURNING id", (main_cat, main_cat))
        res = cur.fetchone()
        parent_id = res[0] if res else None
        if not parent_id:
            cur.execute("SELECT id FROM code WHERE name=%s AND parent_id IS NULL", (main_cat,))
            parent_id = cur.fetchone()[0]

        target_name = sub_cat if sub_cat else main_cat
        for c in raw_codes:
            if c.strip():
                enc = cipher_suite.encrypt(c.strip().encode()).decode()
                cur.execute("INSERT INTO code (name, code, is_active, parent_id) VALUES (%s, %s, TRUE, %s)", (target_name, enc, parent_id if sub_cat else None))
        conn.commit()
    await update.message.reply_text("✅ تم الحفظ بنجاح.", reply_markup=kb_admin_main())
    return ADMIN_MAIN

# ======================================
# ADMIN: USER MANAGEMENT (FIXED FUNCTIONS)
# ======================================
async def user_mgmt_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '➕ إضافة مستخدم ID':
        await update.message.reply_text("أرسل رقم الـ Telegram ID للمستخدم الجديد:", reply_markup=ReplyKeyboardRemove())
        return ADD_USER_ID
    elif text == '❌ حذف مستخدم':
        await update.message.reply_text("أرسل الـ ID المراد حذفه:", reply_markup=ReplyKeyboardRemove())
        return REMOVE_USER_ID
    await update.message.reply_text("الرئيسية", reply_markup=kb_admin_main())
    return ADMIN_MAIN

async def process_add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.text.strip()
    if not user_id.isdigit():
        await update.message.reply_text("❌ يرجى إدخال أرقام فقط.")
        return ADD_USER_ID
    
    h_id = hash_id(user_id)
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO users (hashed_id, role) VALUES (%s, 'user')", (h_id,))
            conn.commit()
        await update.message.reply_text("✅ تم تفعيل المستخدم.", reply_markup=kb_user_mgmt())
    except:
        await update.message.reply_text("⚠️ المستخدم موجود بالفعل.", reply_markup=kb_user_mgmt())
    return USER_MGMT_MENU

async def process_remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    h_id = hash_id(update.message.text.strip())
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE hashed_id=%s AND role='user'", (h_id,))
        conn.commit()
    await update.message.reply_text("🗑️ تم حذف المستخدم.", reply_markup=kb_user_mgmt())
    return USER_MGMT_MENU

# ======================================
# USER BOT: LOGIC
# ======================================
async def user_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '📂 عرض الأقسام':
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT name FROM code WHERE parent_id IS NULL")
            cats = [[r[0]] for r in cur.fetchall()]
        if not cats:
            await update.message.reply_text("المتجر فارغ حالياً.")
            return USER_MAIN
        cats.append(['⬅️ عودة'])
        await update.message.reply_text("اختر القسم:", reply_markup=ReplyKeyboardMarkup(cats, resize_keyboard=True))
        return USER_SELECT_CAT
    return USER_MAIN

async def user_cat_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat_name = update.message.text
    if cat_name == '⬅️ عودة':
        await update.message.reply_text("القائمة الرئيسية", reply_markup=kb_user_main())
        return USER_MAIN

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT name FROM code WHERE parent_id = (SELECT id FROM code WHERE name=%s AND parent_id IS NULL)", (cat_name,))
        subs = [[r[0]] for r in cur.fetchall()]
        
        if subs:
            subs.append(['⬅️ عودة'])
            await update.message.reply_text(f"قسم {cat_name}:", reply_markup=ReplyKeyboardMarkup(subs, resize_keyboard=True))
            return USER_SELECT_SUB
        else:
            return await redeem_code(update, cat_name)

async def redeem_code(update: Update, target):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE code SET is_active=FALSE, used_at=NOW() WHERE id=(SELECT id FROM code WHERE name=%s AND is_active=TRUE LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING code", (target,))
        res = cur.fetchone()
        conn.commit()
    if res:
        code = cipher_suite.decrypt(res[0].encode()).decode()
        await update.message.reply_text(f"✅ كود {target}:\n\n`{code}`", parse_mode="Markdown", reply_markup=kb_user_main())
    else:
        await update.message.reply_text("❌ نفدت الكمية.", reply_markup=kb_user_main())
    return USER_MAIN

# ======================================
# MAIN ASYNC RUNNER
# ======================================
async def main():
    admin_app = ApplicationBuilder().token(ADMIN_TOKEN).build()
    user_app = ApplicationBuilder().token(USER_TOKEN).build()

    # Admin Conversation
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ADMIN_MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu_handler)],
            ADD_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_choice_handler)],
            ADD_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_cat_handler)],
            ADD_SUB: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_sub_handler)],
            ADD_CODES: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_codes_handler)],
            USER_MGMT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_mgmt_router)],
            ADD_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_user)],
            REMOVE_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_remove_user)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # User Conversation
    user_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            USER_MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_main_handler)],
            USER_SELECT_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_cat_selection)],
            USER_SELECT_SUB: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: redeem_code(u, u.message.text))],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    admin_app.add_handler(admin_conv)
    user_app.add_handler(user_conv)

    await admin_app.initialize()
    await user_app.initialize()
    await admin_app.start()
    await user_app.start()

    print("🚀 All systems operational.")
    await asyncio.gather(admin_app.updater.start_polling(), user_app.updater.start_polling())
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
