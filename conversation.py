from telegram.ext import ConversationHandler, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

from db import get_role_by_id
from keyboards import kb_admin_main, kb_user_main
from config import *

from handlers.admin_handlers import *
from handlers.user_handlers import *


async def start_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):

    role = get_role_by_id(update.effective_user.id)

    if role == "admin":

        await update.message.reply_text(
            "👑 لوحة المسؤول",
            reply_markup=kb_admin_main()
        )

        return ADMIN_MAIN

    elif role == "user":

        await update.message.reply_text(
            "👋 بوت الأكواد",
            reply_markup=kb_user_main()
        )

        return USER_MAIN

    await update.message.reply_text(
        f"❌ غير مسجل. ID: `{update.effective_user.id}`",
        parse_mode="Markdown"
    )

    return ConversationHandler.END


conv = ConversationHandler(

    entry_points=[CommandHandler("start", start_auth)],

    states={

        ADMIN_MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu_handler)],

        ADMIN_STATS_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_stats_cat_selection)],

        ADD_CODES: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_codes_handler)],

        USER_MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_main_handler)],

        USER_SELECT_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_cat_selection)],

    },

    fallbacks=[CommandHandler("start", start_auth)]

)