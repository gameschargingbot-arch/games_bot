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
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pass, role FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        if user and check_password_hash(user[0], password) and user[1] == role:
            return True
    return False

# ======================================
# KEYBOARDS
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

# ======================================
# ADMIN: USER MANAGEMENT LOGIC
# ======================================
async def admin_auth_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get('tmp_user')
    password = update.message.text
    if verify_login(username, password, "admin"):
        await update.message.reply_text("✅ تم الدخول للمسؤول", reply_markup=get_admin_main_keyboard())
        return ADMIN_MAIN
    await update.message.reply_text("❌ بيانات خاطئة.")
    return ConversationHandler.END

async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📊 الاحصائيات':
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM code")
            await update.message.reply_text(f"📈 إجمالي الأكواد: {cur.fetchone()[0]}")
    
    elif text == '👤 إدارة المستخدمين':
        await update.message.reply_text("👥 قائمة إدارة المستخدمين:", reply_markup=get_user_mgmt_keyboard())
        return USER_MGMT_MENU
    
    elif text == '➕ اضافة اكواد':
        kb = ReplyKeyboardMarkup([['بدون قسم فرعي', 'مع قسم فرعي'], ['⬅️ عودة']], resize_keyboard=True)
        await update.message.reply_text("اختر طريقة الإضافة:", reply_markup=kb)
        return ADD_CHOICE
    
    return ADMIN_MAIN

# User Management Sub-actions
async def user_mgmt_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '➕ إضافة مستخدم':
        await update.message.reply_text("أدخل اسم المستخدم الجديد:", reply_markup=ReplyKeyboardRemove())
        return ADD_USER_NAME
    elif text == '🔑 تغيير كلمة مرور':
        await update.message.reply_text("أدخل اسم المستخدم المراد تغيير كلمته:", reply_markup=ReplyKeyboardRemove())
        return CHANGE_PASS_NAME
    elif text == '❌ حذف مستخدم':
        await update.message.reply_text("أدخل اسم المستخدم المراد حذفه:", reply_markup=ReplyKeyboardRemove())
        return REMOVE_USER_NAME
    elif text == '⬅️ عودة للقائمة الرئيسية':
        await update.message.reply_text("القائمة الرئيسية:", reply_markup=get_admin_main_keyboard())
        return ADMIN_MAIN

# Action Logic: Add User
async def add_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_target_user'] = update.message.text
    await update.message.reply_text("أدخل كلمة المرور للمستخدم الجديد:")
    return ADD_USER_PASS

async def add_user_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = context.user_data['new_target_user']
    pword = generate_password_hash(update.message.text)
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO users (username, pass, role) VALUES (%s, %s, 'user')", (uname, pword))
            conn.commit()
        await update.message.reply_text(f"✅ تم إضافة المستخدم {uname}", reply_markup=get_user_mgmt_keyboard())
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ (ربما المستخدم موجود بالفعل).", reply_markup=get_user_mgmt_keyboard())
    return USER_MGMT_MENU

# Action Logic: Remove User
async def remove_user_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = update.message.text
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE username=%s AND role='user'", (uname,))
        conn.commit()
    await update.message.reply_text(f"🗑️ تم حذف المستخدم {uname} (إذا كان موجوداً).", reply_markup=get_user_mgmt_keyboard())
    return USER_MGMT_MENU

# Action Logic: Change Password
async def change_pass_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['target_pass_user'] = update.message.text
    await update.message.reply_text("أدخل كلمة المرور الجديدة:")
    return CHANGE_PASS_VAL

async def change_pass_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = context.user_data['target_pass_user']
    new_pword = generate_password_hash(update.message.text)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET pass=%s WHERE username=%s", (new_pword, uname))
        conn.commit()
    await update.message.reply_text(f"🔐 تم تحديث كلمة المرور لـ {uname}", reply_markup=get_user_mgmt_keyboard())
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
            # Add User States
            ADD_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_user_name)],
            ADD_USER_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_user_final)],
            # Change Pass States
            CHANGE_PASS_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_pass_name)],
            CHANGE_PASS_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_pass_final)],
            # Remove User States
            REMOVE_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_user_final)],
            # Code Adding states (from previous prompt)
            ADD_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: ADMIN_MAIN)], # Simplified placeholder
        },
        fallbacks=[CommandHandler("start", start)]
    )

    admin_app.add_handler(admin_conv)
    
    await admin_app.initialize()
    await admin_app.start()
    print("Admin Bot with User Management is running...")
    await admin_app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
