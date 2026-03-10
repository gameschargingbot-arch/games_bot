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

# ======================================
# CONFIG & ENV
# ======================================
load_dotenv()
BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN") 
DB_URL = os.getenv("NEON_DB_URL")
FERNET_KEY = os.getenv("FERNET_KEY").encode()

cipher_suite = Fernet(FERNET_KEY)

# States
(ADMIN_MAIN, ADD_CHOICE, ADD_CAT, ADD_SUB, ADD_CODES,
 USER_MGMT_MENU, ADD_USER_ID, REMOVE_USER_ID,
 USER_MAIN, USER_SELECT_CAT, USER_SELECT_SUB,
 ADMIN_STATS_CAT, ADMIN_STATS_SUB) = range(13)

# ======================================
# HELPERS
# ======================================
def get_connection():
    safe_url = DB_URL
    if "sslmode=require" not in safe_url:
        safe_url += "?sslmode=require"
    return psycopg2.connect(safe_url)

def hash_id(tg_id: int) -> str:
    return hashlib.sha256(str(tg_id).encode()).hexdigest()

def get_role_by_id(tg_id: int):
    h_id = hash_id(tg_id)
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE hashed_id = %s", (h_id,))
            res = cur.fetchone()
            return res[0] if res else None
    except Exception: return None

# ======================================
# KEYBOARDS
# ======================================
def kb_admin_main():
    return ReplyKeyboardMarkup([['📊 الاحصائيات', '➕ اضافة اكواد'], ['👤 إدارة المستخدمين', '📥 تصدير Excel']], resize_keyboard=True)

def kb_user_main():
    return ReplyKeyboardMarkup([['📂 عرض الأقسام']], resize_keyboard=True)

def kb_user_mgmt():
    return ReplyKeyboardMarkup([['➕ إضافة مستخدم ID', '❌ حذف مستخدم'], ['⬅️ عودة']], resize_keyboard=True)

# ======================================
# ADMIN: STATS LOGIC
# ======================================
async def admin_stats_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT name FROM code WHERE parent_id IS NULL")
        cats = [[r[0]] for r in cur.fetchall()]
    
    if not cats:
        await update.message.reply_text("📭 لا توجد بيانات.")
        return ADMIN_MAIN
        
    cats.append(['⬅️ عودة للقائمة الرئيسية'])
    await update.message.reply_text("📊 اختر القسم لعرض إحصائياته:", reply_markup=ReplyKeyboardMarkup(cats, resize_keyboard=True))
    return ADMIN_STATS_CAT

async def admin_stats_cat_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat_name = update.message.text
    if cat_name == '⬅️ عودة للقائمة الرئيسية':
        await update.message.reply_text("القائمة الرئيسية", reply_markup=kb_admin_main())
        return ADMIN_MAIN

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT name FROM code WHERE parent_id = (SELECT id FROM code WHERE name=%s AND parent_id IS NULL LIMIT 1)", (cat_name,))
        subs = [[r[0]] for r in cur.fetchall()]
        
        if subs:
            subs.append(['⬅️ عودة'])
            await update.message.reply_text(f"📁 قسم {cat_name}: اختر النوع الفرعي", reply_markup=ReplyKeyboardMarkup(subs, resize_keyboard=True))
            return ADMIN_STATS_SUB
        else:
            return await show_final_stats(update, cat_name)

async def show_final_stats(update: Update, target):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM code WHERE name=%s AND is_active=TRUE", (target,))
        unused = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM code WHERE name=%s AND is_active=FALSE", (target,))
        used = cur.fetchone()[0]
        
    msg = f"📊 **إحصائيات {target}**\n\n✅ متاح: `{unused}`\n❌ مستخدم: `{used}`\n🔢 الإجمالي: `{unused + used}`"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_admin_main())
    return ADMIN_MAIN

# ======================================
# ADMIN: ACTIONS
# ======================================
async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📊 الاحصائيات': return await admin_stats_main(update, context)
    if text == '➕ اضافة اكواد':
        await update.message.reply_text("اختر طريقة الإضافة:", reply_markup=ReplyKeyboardMarkup([['بدون قسم فرعي', 'مع قسم فرعي'], ['⬅️ عودة']], resize_keyboard=True))
        return ADD_CHOICE
    if text == '👤 إدارة المستخدمين':
        await update.message.reply_text("إدارة الوصول:", reply_markup=kb_user_mgmt())
        return USER_MGMT_MENU
    if text == '📥 تصدير Excel':
        with get_connection() as conn: df = pd.read_sql("SELECT name, code, is_active FROM code", conn)
        df['code'] = df['code'].apply(lambda x: cipher_suite.decrypt(x.encode()).decode() if x else "N/A")
        df.to_excel("export.xlsx", index=False)
        await update.message.reply_document(document=open("export.xlsx", "rb"))
    return ADMIN_MAIN

async def save_codes_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_codes = update.message.text.split('\n')
    m_cat, s_cat = context.user_data['main_cat'], context.user_data.get('sub_cat')
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM code WHERE name=%s AND parent_id IS NULL LIMIT 1", (m_cat,))
        parent = cur.fetchone()
        parent_id = parent[0] if parent else (cur.execute("INSERT INTO code (name, is_active) VALUES (%s, TRUE) RETURNING id", (m_cat,)) or cur.fetchone()[0])
        for c in raw_codes:
            if c.strip():
                enc = cipher_suite.encrypt(c.strip().encode()).decode()
                cur.execute("INSERT INTO code (name, code, is_active, parent_id) VALUES (%s, %s, TRUE, %s)", (s_cat if s_cat else m_cat, enc, parent_id if s_cat else None))
        conn.commit()
    await update.message.reply_text("✅ تم الحفظ.", reply_markup=kb_admin_main())
    return ADMIN_MAIN

# ======================================
# USER: LOGIC
# ======================================
async def user_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '📂 عرض الأقسام':
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT name FROM code WHERE parent_id IS NULL")
            cats = [[r[0]] for r in cur.fetchall()]
        if not cats: return USER_MAIN
        cats.append(['⬅️ عودة'])
        await update.message.reply_text("اختر القسم:", reply_markup=ReplyKeyboardMarkup(cats, resize_keyboard=True))
        return USER_SELECT_CAT
    return USER_MAIN

async def user_cat_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat_name = update.message.text
    if cat_name == '⬅️ عودة':
        await update.message.reply_text("الرئيسية", reply_markup=kb_user_main())
        return USER_MAIN
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT name FROM code WHERE parent_id = (SELECT id FROM code WHERE name=%s AND parent_id IS NULL LIMIT 1)", (cat_name,))
        subs = [[r[0]] for r in cur.fetchall()]
        if subs:
            subs.append(['⬅️ عودة'])
            await update.message.reply_text(f"قسم {cat_name}:", reply_markup=ReplyKeyboardMarkup(subs, resize_keyboard=True))
            return USER_SELECT_SUB
        return await redeem_code(update, cat_name)

async def redeem_code(update, target):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE code SET is_active=FALSE, used_at=NOW() WHERE id=(SELECT id FROM code WHERE name=%s AND is_active=TRUE LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING code", (target,))
        res = cur.fetchone()
        conn.commit()
    if res:
        code = cipher_suite.decrypt(res[0].encode()).decode()
        await update.message.reply_text(f"✅ كود {target}:\n`{code}`", parse_mode="Markdown", reply_markup=kb_user_main())
    else: await update.message.reply_text("❌ نفدت الكمية.", reply_markup=kb_user_main())
    return USER_MAIN

# ======================================
# AUTH & MAIN
# ======================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = get_role_by_id(update.effective_user.id)
    if role == "admin":
        await update.message.reply_text("👑 لوحة المسؤول", reply_markup=kb_admin_main())
        return ADMIN_MAIN
    elif role == "user":
        await update.message.reply_text("👋 بوت الأكواد", reply_markup=kb_user_main())
        return USER_MAIN
    await update.message.reply_text(f"❌ غير مسجل. ID: `{update.effective_user.id}`", parse_mode="Markdown")
    return ConversationHandler.END

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ADMIN_MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu_handler)],
            ADMIN_STATS_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_stats_cat_selection)],
            ADMIN_STATS_SUB: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: show_final_stats(u, u.message.text) if 'عودة' not in u.message.text else admin_stats_main(u,c))],
            ADD_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (c.user_data.update({'mode': 'sub' if 'مع' in u.message.text else 'single'}), u.message.reply_text("القسم الرئيسي:", reply_markup=ReplyKeyboardRemove()))[-1] or (ADD_CAT if 'عودة' not in u.message.text else ADMIN_MAIN))],
            ADD_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (c.user_data.update({'main_cat':u.message.text}), u.message.reply_text("الفرعي:") if c.user_data['mode']=='sub' else u.message.reply_text("الأكواد:"))[-1] or (ADD_SUB if c.user_data['mode']=='sub' else ADD_CODES))],
            ADD_SUB: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (c.user_data.update({'sub_cat':u.message.text}), u.message.reply_text("الأكواد:"))[-1] or ADD_CODES)],
            ADD_CODES: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_codes_handler)],
            USER_MGMT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (u.message.reply_text("ID:") or (ADD_USER_ID if 'إضافة' in u.message.text else REMOVE_USER_ID)) if 'عودة' not in u.message.text else (u.message.reply_text("الرئيسية", reply_markup=kb_admin_main()) or ADMIN_MAIN))],
            ADD_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (get_connection().cursor().execute("INSERT INTO users (hashed_id, role) VALUES (%s, 'user')",(hash_id(u.message.text),)), u.message.reply_text("✅"))[-1] or USER_MGMT_MENU)],
            REMOVE_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: (get_connection().cursor().execute("DELETE FROM users WHERE hashed_id=%s",(hash_id(u.message.text),)), u.message.reply_text("🗑️"))[-1] or USER_MGMT_MENU)],
            USER_MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_main_handler)],
            USER_SELECT_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_cat_selection)],
            USER_SELECT_SUB: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: redeem_code(u, u.message.text) if 'عودة' not in u.message.text else user_main_handler(u,c))],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    app.add_handler(conv)
    
    # --- MANUAL LIFECYCLE FOR PYTHON 3.14/RENDER ---
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("🚀 Bot is running...")
    
    # Stay alive forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
