import os
import threading
import sqlite3
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

DEVELOPER_USERNAME = "@ota_m_pro"
ADMIN_ID = 8504617214

conn = sqlite3.connect('study_data.db', check_same_thread=False)
cursor = conn.cursor()

# تحديث قاعدة البيانات لدعم المواد، الفروع، والدروس
cursor.execute('''
    CREATE TABLE IF NOT EXISTS lessons (
        user_id INTEGER,
        subject TEXT,
        section TEXT,
        title TEXT,
        content_type TEXT,
        file_or_text TEXT
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT
    )
''')
# جدول مؤقت لحفظ الحالة عندما يكتب الطالب اسم مادة جديدة أو فرع جديد
cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_states (
        user_id INTEGER PRIMARY KEY,
        state TEXT,
        temp_data TEXT
    )
''')
conn.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = f"@{user.username}" if user.username else "بدون يوزر"
    first_name = user.first_name

    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users VALUES (?, ?, ?)", (user_id, username, first_name))
        conn.commit()
        try:
            admin_msg = f"🔔 عضو جديد انضم للبوت!\n\n👤 الاسم: {first_name}\n🆔 المعرف: {username}\n🔢 الـ ID: `{user_id}`"
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
        except Exception:
            pass

    welcome_text = (
        "👋 أهلاً بك في بوت BAC 2027 المطور!\n\n"
        "مساحتك الشخصية لتنظيم دروسك ومراجعك عبر أزرار تفاعلية للمواد والفروع 📚✨.\n\n"
        "📌 **طريقة الحفظ السريع:**\n"
        "• أرسل بالصيغة: `المادة: الفرع: عنوان الدرس: المحتوى`\n"
        "• أو أرسل صورة/ملف واكتب في الوصف: `المادة: الفرع: عنوان الدرس`"
    )
    
    keyboard = [
        [InlineKeyboardButton("📚 عرض دروسي وموادي", callback_data="show_subjects")],
        [InlineKeyboardButton("💬 مراسلة المطور", url=f"https://t.me/{DEVELOPER_USERNAME.replace('@', '')}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        await update.message.reply_text(f"📊 إحصائيات البوت:\nعدد الأعضاء المسجلين: {total_users}")

async def list_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        cursor.execute("SELECT user_id, username, first_name FROM users")
        users = cursor.fetchall()
        
        if not users:
            await update.message.reply_text("لا توجد أي أعضاء مسجلين حتى الآن.")
            return

        text = "👥 قائمة الأعضاء المسجلين في البوت:\n\n"
        for idx, (u_id, username, first_name) in enumerate(users, 1):
            user_link = f"[{first_name}](https://t.me/{username.replace('@', '')})" if username and username != "بدون يوزر" else f"{first_name} (بدون معرف)"
            text += f"{idx}. {user_link} — `[ID: {u_id}]`\n"
            if len(text) > 3500:
                await update.message.reply_text(text, parse_mode="Markdown")
                text = ""
        if text:
            await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text("هذا الأمر مخصص للمطور فقط ❌")

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        if not context.args:
            await update.message.reply_text("❌ يرجى كتابة النص بعد الأمر هكذا:\n`/broadcast [الرسالة]`", parse_mode="Markdown")
            return
        announcement = " ".join(context.args)
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        success_count = fail_count = 0
        for (u_id,) in users:
            try:
                await context.bot.send_message(chat_id=u_id, text=announcement, parse_mode="Markdown")
                success_count += 1
            except Exception:
                fail_count += 1
        await update.message.reply_text(f"📢 تم الإرسال بنجاح!\n✅ وصل إلى: {success_count}\n❌ فشل: {fail_count}")
    else:
        await update.message.reply_text("هذا الأمر مخصص للمطور فقط ❌")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    # التحقق من حالة المستخدم إذا كان بصدد إضافة مادة أو فرع جديد عبر الأزرار
    cursor.execute("SELECT state, temp_data FROM user_states WHERE user_id = ?", (user_id,))
    state_row = cursor.fetchone()

    if state_row:
        state, temp_data = state_row[0], state_row[1]
        if state == "waiting_for_subject":
            sub_name = text
            cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
            conn.commit()
            await update.message.reply_text(f"✅ تمت إضافة المادة '{sub_name}' بنجاح!\nيمكنك الآن حفظ الدروس فيها بهذه الصيغة:\n`{sub_name}: اسم الفرع: العنوان: المحتوى`", parse_mode="Markdown")
            return
        elif state == "waiting_for_section":
            subject = temp_data
            sec_name = text
            cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
            conn.commit()
            await update.message.reply_text(f"✅ تم إضافة الفرع '{sec_name}' لمادة [{subject}] بنجاح!\nلحفظ درس فيه أرسل:\n`{subject}: {sec_name}: العنوان: المحتوى`", parse_mode="Markdown")
            return

    # الكلمات المفتاحية لعرض القائمة
    list_keywords = ["قائمة", "اعرض", "اضهر", "أضهر", "دروسي", "الدروس", "موادي"]
    if any(keyword in text for keyword in list_keywords) and ":" not in text:
        await show_subjects_menu(update, context)
        return

    # صيغة الحفظ الذكية المباشرة
    if ":" in text:
        try:
            parts = [p.strip() for p in text.split(":", 3)]
            if len(parts) >= 4:
                subject, section, title, content = parts[0], parts[1], parts[2], parts[3]
                cursor.execute("INSERT INTO lessons VALUES (?, ?, ?, ?, ?, ?)", (user_id, subject, section, title, "text", content))
                conn.commit()
                await update.message.reply_text(f"✅ تم حفظ الدرس '{title}' في [{subject} ➔ {section}] بنجاح!")
                return
        except Exception:
            pass

    await update.message.reply_text("❌ الصيغة غير صحيحة.\nاستخدم الأزرار لتصفح موادك أو أرسل بالصيغة:\n`المادة: الفرع: عنوان الدرس: المحتوى`", parse_mode="Markdown")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    caption = update.message.caption
    if caption and ":" in caption:
        parts = [p.strip() for p in caption.split(":", 2)]
        if len(parts) >= 3:
            subject, section, title = parts[0], parts[1], parts[2]
            photo_id = update.message.photo[-1].file_id
            cursor.execute("INSERT INTO lessons VALUES (?, ?, ?, ?, ?, ?)", (user_id, subject, section, title, "photo", photo_id))
            conn.commit()
            await update.message.reply_text(f"✅ تم حفظ الصورة '{title}' تحت [{subject} ➔ {section}] بنجاح!")
            return
    await update.message.reply_text("❌ يرجى كتابة الوصف بالشكل التالي:\n`المادة: الفرع: عنوان الدرس`", parse_mode="Markdown")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    caption = update.message.caption
    if caption and ":" in caption:
        parts = [p.strip() for p in caption.split(":", 2)]
        if len(parts) >= 3:
            subject, section, title = parts[0], parts[1], parts[2]
            doc_id = update.message.document.file_id
            cursor.execute("INSERT INTO lessons VALUES (?, ?, ?, ?, ?, ?)", (user_id, subject, section, title, "document", doc_id))
            conn.commit()
            await update.message.reply_text(f"✅ تم حفظ الملف '{title}' تحت [{subject} ➔ {section}] بنجاح!")
            return
    await update.message.reply_text("❌ يرجى كتابة الوصف بالشكل التالي:\n`المادة: الفرع: عنوان الدرس`", parse_mode="Markdown")

async def show_subjects_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else update.callback_query.from_user.id
    cursor.execute("SELECT DISTINCT subject FROM lessons WHERE user_id = ?", (user_id,))
    subjects = cursor.fetchall()
    
    text = "📚 اختر المادة الدراسية لعرض فروعها ودروسها:"
    keyboard = []
    
    if subjects:
        for (sub,) in subjects:
            # زر عرض المادة وأزرار الحذف بجانبها
            keyboard.append([
                InlineKeyboardButton(f"📖 {sub}", callback_data=f"sub_{sub}"),
                InlineKeyboardButton("حذف المادة 🗑️", callback_data=f"del_sub_{sub}")
            ])
            
    keyboard.append([InlineKeyboardButton("➕ إضافة مادة جديدة", callback_data="add_subject")])
    keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data

    if data == "show_subjects":
        await show_subjects_menu(update, context)
        return
    elif data == "main_menu":
        cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
        conn.commit()
        await query.message.edit_text("🏠 القائمة الرئيسية للبوت.")
        return
    elif data == "add_subject":
        cursor.execute("INSERT OR REPLACE INTO user_states (user_id, state, temp_data) VALUES (?, ?, ?)", (user_id, "waiting_for_subject", ""))
        conn.commit()
        await query.message.edit_text("✍️ أرسل الآن اسم المادة الجديدة التي تريد إضافتها:")
        return

    # حذف مادة كاملة
    if data.startswith("del_sub_"):
        sub_to_del = data.replace("del_sub_", "", 1)
        cursor.execute("DELETE FROM lessons WHERE user_id = ? AND subject = ?", (user_id, sub_to_del))
        conn.commit()
        await show_subjects_menu(update, context)
        return

    # اختيار مادة لعرض فروعها
    if data.startswith("sub_"):
        subject = data.replace("sub_", "", 1)
        cursor.execute("SELECT DISTINCT section FROM lessons WHERE user_id = ? AND subject = ?", (user_id, subject))
        sections = cursor.fetchall()
        
        keyboard = []
        if sections:
            for (sec,) in sections:
                keyboard.append([
                    InlineKeyboardButton(f"📂 فرع: {sec}", callback_data=f"sec_{subject}_{sec}"),
                    InlineKeyboardButton("حذف الفرع 🗑️", callback_data=f"del_sec_{subject}_{sec}")
                ])
        
        keyboard.append([InlineKeyboardButton("➕ إضافة فرع جديد", callback_data=f"add_sec_{subject}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع للمواد", callback_data="show_subjects")])
        
        await query.message.edit_text(f"📚 مادة: {subject}\nاختر الفروع المطلوبة:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # طلب إضافة فرع جديد لمادة معينة
    if data.startswith("add_sec_"):
        subject = data.replace("add_sec_", "", 1)
        cursor.execute("INSERT OR REPLACE INTO user_states (user_id, state, temp_data) VALUES (?, ?, ?)", (user_id, "waiting_for_section", subject))
        conn.commit()
        await query.message.edit_text(f"✍️ أرسل الآن اسم الفرع الجديد الذي تريد إضافته لمادة [{subject}]:")
        return

    # حذف فرع كامل مع دروسه
    if data.startswith("del_sec_"):
        parts = data.replace("del_sec_", "", 1).split("_", 1)
        subject, section = parts[0], parts[1]
        cursor.execute("DELETE FROM lessons WHERE user_id = ? AND subject = ? AND section = ?", (user_id, subject, section))
        conn.commit()
        
        # إعادة توجيه لنفس قائمة فروع المادة
        cursor.execute("SELECT DISTINCT section FROM lessons WHERE user_id = ? AND subject = ?", (user_id, subject))
        sections = cursor.fetchall()
        keyboard = []
        if sections:
            for (sec,) in sections:
                keyboard.append([
                    InlineKeyboardButton(f"📂 فرع: {sec}", callback_data=f"sec_{subject}_{sec}"),
                    InlineKeyboardButton("حذف الفرع 🗑️", callback_data=f"del_sec_{subject}_{sec}")
                ])
        keyboard.append([InlineKeyboardButton("➕ إضافة فرع جديد", callback_data=f"add_sec_{subject}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع للمواد", callback_data="show_subjects")])
        
        await query.message.edit_text(f"📚 مادة: {subject}\nتم حذف الفرع بنجاح.", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # عرض دروس الفرع المحدد
    if data.startswith("sec_"):
        parts = data.replace("sec_", "", 1).split("_", 1)
        subject, section = parts[0], parts[1]
        
        cursor.execute("SELECT rowid, title, content_type FROM lessons WHERE user_id = ? AND subject = ? AND section = ?", (user_id, subject, section))
        lessons = cursor.fetchall()
        
        keyboard = []
        for rowid, title, c_type in lessons:
            type_label = "🖼️" if c_type == "photo" else ("📄" if c_type == "document" else "📝")
            keyboard.append([InlineKeyboardButton(f"{type_label} {title}", callback_data=f"op_{rowid}")])
            keyboard.append([InlineKeyboardButton("حذف الدرس 🗑️", callback_data=f"dl_{rowid}")])
            
        keyboard.append([InlineKeyboardButton("🔙 رجوع للفروع", callback_data=f"sub_{subject}")])
        
        await query.message.edit_text(f"📂 مادة: {subject} ➔ فرع: {section}\nاختر الدرس:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # فتح أو حذف درس منفرد
    if data.startswith("op_") or data.startswith("dl_"):
        prefix, rowid = data.split("_", 1)
        cursor.execute("SELECT subject, section, title, content_type, file_or_text FROM lessons WHERE rowid = ? AND user_id = ?", (rowid, user_id))
        row = cursor.fetchone()
        
        if not row:
            await query.message.reply_text("❌ عذراً، لم يتم العثور على العنصر.")
            return
            
        subject, section, title, c_type, data_val = row[0], row[1], row[2], row[3], row[4]
        chat_id = query.message.chat_id
        
        if prefix == "dl":
            cursor.execute("DELETE FROM lessons WHERE rowid = ? AND user_id = ?", (rowid, user_id))
            conn.commit()
            await query.message.edit_text(f"❌ تم حذف الدرس '{title}' بنجاح.")
        elif prefix == "op":
            if c_type == "text":
                await context.bot.send_message(chat_id=chat_id, text=f"📖 [{subject} / {section}] - {title}:\n\n{data_val}")
            elif c_type == "photo":
                await context.bot.send_photo(chat_id=chat_id, photo=data_val, caption=f"📖 [{subject} / {section}] - {title}")
            elif c_type == "document":
                await context.bot.send_document(chat_id=chat_id, document=data_val, caption=f"📖 [{subject} / {section}] - {title}")

def main():
    request = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0)
    app = ApplicationBuilder().token("8965186384:AAEadFB6hGmoazwbQsoTe8oTTaUFRSZfIro").request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("users", list_all_users))
    app.add_handler(CommandHandler("broadcast", broadcast_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("Bot is starting...")
    app.run_polling()

if __name__ == '__main__':
    t = threading.Thread(target=run_web)
    t.start()
    main()
