from telegram import ReplyKeyboardMarkup

def kb_admin_main():
    return ReplyKeyboardMarkup(
        [
            ['📊 الاحصائيات', '➕ اضافة اكواد'],
            ['👤 إدارة المستخدمين', '📥 تصدير Excel']
        ],
        resize_keyboard=True
    )

def kb_user_main():
    return ReplyKeyboardMarkup(
        [['📂 عرض الأقسام']],
        resize_keyboard=True
    )

def kb_user_mgmt():
    return ReplyKeyboardMarkup(
        [
            ['➕ إضافة مستخدم ID', '❌ حذف مستخدم'],
            ['⬅️ عودة']
        ],
        resize_keyboard=True
    )