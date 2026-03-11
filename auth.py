from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from db import get_role_by_id
from keyboards import kb_admin_main, kb_user_main
from config import ADMIN_MAIN, USER_MAIN

async def start_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):

    role = get_role_by_id(update.effective_user.id)

    if role == "admin":
        await update.message.reply_text("👑 لوحة المسؤول", reply_markup=kb_admin_main())
        return ADMIN_MAIN

    elif role == "user":
        await update.message.reply_text("👋 بوت الأكواد", reply_markup=kb_user_main())
        return USER_MAIN

    await update.message.reply_text(
        f"❌ غير مسجل. ID: `{update.effective_user.id}`",
        parse_mode="Markdown"
    )

    return ConversationHandler.END