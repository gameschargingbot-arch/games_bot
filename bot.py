import os
import sys
import asyncio
import time
import psycopg2
import pandas as pd

from dotenv import load_dotenv
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash, check_password_hash

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
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
(L_USER, L_PASS, 
 ADMIN_MAIN, ADD_CHOICE, 
 ADD_CAT, ADD_SUB, ADD_CODES,
 USER_MGMT_MENU, 
 ADD_USER_NAME, ADD_USER_PASS,
 CHANGE_PASS_NAME, CHANGE_PASS_VAL,
 REMOVE_USER_NAME) = range(13)

# ======================================
# DATABASE HELPERS
# ======================================
def get_connection():
    safe_url = DB_URL + ("?sslmode=require" if "sslmode=require" not in DB_URL else "")
    return psycopg2.connect(safe_url)

def verify_login(username, password, role):
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT pass, role FROM users WHERE username=%s", (username,))
            user = cur.fetchone()
            if user and check_password_hash(user[0], password) and user[1] == role:
                return True
    except:
        return False
    return False

# ======================================
# KEYBOARDS (The Menu Interface)
# ======================================
def get_admin_main_keyboard():
    return ReplyKeyboardMarkup([
        ['📊 الاحصائيات', '➕ اضافة اكواد'],
        ['👤 إدارة المستخدمين', '📥 تصدير Excel'],
        ['🚪 تسجيل خروج']
    ], resize_keyboard=True)

def get_user_mgmt_keyboard():
    return ReplyKeyboardMarkup([
        ['➕ إضافة مستخدم', '🔑 تغيير كلمة مرور'],
        ['❌ حذف مستخدم', '⬅️ عودة للقائمة الرئيسية']
    ], resize_keyboard=True)

def get_add_code_keyboard():
    return ReplyKeyboardMarkup([
        ['بدون قسم فرعي', 'مع قسم فرعي'],
        ['⬅️ عودة للقائمة الرئيسية']
    ], resize_keyboard=True)

# ======================================
# SHARED LOGIN FLOW
# ======================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلاً بك. أدخل اسم المستخدم:", reply_markup=ReplyKeyboardRemove())
    return L_USER

async def login_user_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tmp_user'] = update.message.text
    await update.message.reply_text("🔑 أدخل كلمة المرور:")
    return L_PASS

async def admin_auth_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get('tmp_user')
    password = update.message.text
    if verify_login(username, password, "admin"):
        await update.message.reply_text("✅ تم الدخول للمسؤول", reply_markup=get_admin_main_keyboard())
        return ADMIN_MAIN
    await update.message.reply_text("❌ بيانات خاطئة. استخدم /start للمحاولة مجدداً.")
    return ConversationHandler.END

# ======================================
# ADMIN: MAIN MENU HANDLER
# ======================================
async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == '📊 الاحصائيات':
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM code WHERE is_active=TRUE")
            active = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM code WHERE is_active=FALSE")
            used = cur.fetchone()[0]
            await update.message.reply_text(f"📈 إحصائيات النظام:\nالأكواد المتاحة: {active}\nالأكواد المستخدمة: {used}")
            return ADMIN_MAIN

    elif text == '➕ اضافة اكواد':
        await update.message.reply_text("اختر طريقة الإضافة:", reply_markup=get_add_code_keyboard())
        return ADD_CHOICE

    elif text == '👤 إدارة المستخدمين':
        await update.message.reply_text("👥 قائمة إدارة المستخدمين:", reply_markup=get_user_mgmt_keyboard())
        return USER_MGMT_MENU

    elif text == '📥 تصدير Excel':
        await update.message.reply_text("جاري استخراج البيانات...")
        with get_connection() as conn:
            df = pd.read_sql("SELECT name, code, is_active FROM code", conn)
        df['code'] = df['code'].apply(lambda x: cipher_suite.decrypt(x.encode()).decode() if x else "")
        df.to_excel("codes_export.xlsx", index=False)
        await update.message.reply_document(document=open("codes_export.xlsx", "rb"))
        return ADMIN_MAIN

    elif text == '🚪 تسجيل خروج':
        await update.message.reply_text("تم تسجيل الخروج.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    return ADMIN_MAIN

# ======================================
# ADMIN: CODE ADDITION LOGIC
# ======================================
async def add_choice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    if choice == 'بدون قسم فرعي':
        context.user_data['add_mode'] = 'single'
        await update.message.reply_text("أدخل اسم القسم (مثال: NETFLIX):", reply_markup=ReplyKeyboardRemove())
        return ADD_CAT
    elif choice == 'مع قسم فرعي':
        context.user_data['add_mode'] = 'sub'
        await update.message.reply_text("أدخل اسم القسم الرئيسي (مثال: GAMES):", reply_markup=ReplyKeyboardRemove())
        return ADD_CAT
    elif choice == '⬅️ عودة للقائمة الرئيسية':
        await update.message.reply_text("القائمة الرئيسية:", reply_markup=get_admin_main_keyboard())
        return ADMIN_MAIN

async def add_cat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['main_cat'] = update.message.text
    if context.user_data['add_mode'] == 'sub':
        await update.message.reply_text("أدخل اسم القسم الفرعي (مثال: PUBG):")
        return ADD_SUB
    await update.message.reply_text("أرسل الأكواد الآن (كود واحد في كل سطر):")
    return ADD_CODES

async def add_sub_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sub_cat'] = update.message.text
    await update.message.reply_text(f"أرسل الأكواد لقسم {context.user_data['sub_cat']} الآن:")
    return ADD_CODES

async def save_codes_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_codes = update.message.text.split('\n')
    main_name = context.user_data['main_cat']
    sub_name = context.user_data.get('sub_cat')

    with get_connection() as conn, conn.cursor() as cur:
        # Check if parent exists or create it
        cur.execute("SELECT id FROM code WHERE name=%s AND parent_id IS NULL", (main_name,))
        parent = cur.fetchone()
        if not parent:
            cur.execute("INSERT INTO code (name, is_active) VALUES (%s, TRUE) RETURNING id", (main_name,))
            parent_id = cur.fetchone()[0]
        else:
            parent_id = parent[0]

        # Determine target name and parent association
        target_name = sub_name if sub_name else main_name
        final_parent = parent_id if sub_name else None

        for c in raw_codes:
            if c.strip():
                enc = cipher_suite.encrypt(c.strip().encode()).decode()
                cur.execute(
                    "INSERT INTO code (name, code, is_active, parent_id) VALUES (%s, %s, TRUE, %s)",
                    (target_name, enc, final_parent)
                )
        conn.commit()

    await update.message.reply_text(f"✅ تم حفظ الأكواد بنجاح في {target_name}", reply_markup=get_admin_main_keyboard())
    return ADMIN_MAIN

# ======================================
# ADMIN: USER MANAGEMENT LOGIC
# ======================================
async def user_mgmt_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '➕ إضافة مستخدم':
        await update.message.reply_text("أدخل اسم المستخدم الجديد:", reply_markup=ReplyKeyboardRemove())
        return ADD_USER_NAME
    elif text == '🔑 تغيير كلمة مرور':
        await update.message.reply_text("أدخل اسم المستخدم المراد تعديله:", reply_markup=ReplyKeyboardRemove())
        return CHANGE_PASS_NAME
    elif text == '❌ حذف مستخدم':
        await update.message.reply_text("أدخل اسم المستخدم المراد حذفه:", reply_markup=ReplyKeyboardRemove())
        return REMOVE_USER_NAME
    elif text == '⬅️ عودة للقائمة الرئيسية':
        await update.message.reply_text("القائمة الرئيسية:", reply_markup=get_admin_main_keyboard())
        return ADMIN_MAIN
    return USER_MGMT_MENU

async def add_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_target'] = update.message.text
    await update.message.reply_text("أدخل كلمة المرور الجديدة:")
    return ADD_USER_PASS

async def add_user_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = context.user_data['new_target']
    pword = generate_password_hash(update.message.text)
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO users (username, pass, role) VALUES (%s, %s, 'user')", (uname, pword))
            conn.commit()
        await update.message.reply_text("✅ تمت إضافة المستخدم", reply_markup=get_user_mgmt_keyboard())
    except:
        await update.message.reply_text("❌ خطأ: الاسم موجود مسبقاً", reply_markup=get_user_mgmt_keyboard())
    return USER_MGMT_MENU

async def change_pass_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['pass_target'] = update.message.text
    await update.message.reply_text("أدخل كلمة المرور الجديدة:")
    return CHANGE_PASS_VAL

async def change_pass_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = context.user_data['pass_target']
    pword = generate_password_hash(update.message.text)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET pass=%s WHERE username=%s", (pword, uname))
        conn.commit()
    await update.message.reply_text("🔐 تم تغيير كلمة المرور", reply_markup=get_user_mgmt_keyboard())
    return USER_MGMT_MENU

async def remove_user_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = update.message.text
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE username=%s AND role='user'", (uname,))
        conn.commit()
    await update.message.reply_text(f"🗑️ تم حذف {uname}", reply_markup=get_user_mgmt_keyboard())
    return USER_MGMT_MENU

# ======================================
# MAIN RUNNER
# ======================================
async def main():
    admin_app = ApplicationBuilder().token(ADMIN_TOKEN).build()

    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            L_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_user_step)],
            L_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_auth_check)],
            ADMIN_MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu_handler)],
            USER_MGMT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_mgmt_router)],
            ADD_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_choice_handler)],
            # Addition steps
            ADD_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_cat_handler)],
            ADD_SUB: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_sub_handler)],
            ADD_CODES: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_codes_handler)],
            # User mgmt steps
            ADD_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_user_name)],
            ADD_USER_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_user_final)],
            CHANGE_PASS_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_pass_name)],
            CHANGE_PASS_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_pass_final)],
            REMOVE_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_user_final)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    admin_app.add_handler(admin_conv)
    
    await admin_app.initialize()
    await admin_app.start()
    print("Admin Bot is fully operational with all menus.")
    await admin_app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
