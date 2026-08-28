import os
import threading
import sqlite3
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

# إعداد منصة Render لإيقاع سيرفر وهمي بـ Flask
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
cursor.execute('''
    CREATE TABLE IF NOT EXISTS lessons (
        user_id INTEGER,
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
        "👋 أهلاً بك في بوت BAC 2027!\n\n"
        "مساحتك الشخصية لتنظيم وحفظ دروسك ومراجعك بسهولة.\n\n"
        "📌 خطوات الاستخدام وطريقة العمل:\n"
        "1️⃣ لحفظ نص أو رابط: أرسل `حفظ اسم الدرس: محتوى الدرس`\n"
        "2️⃣ لحفظ صورة أو ملف: أرسل الصورة/الملف واكتب اسم الدرس في الوصف.\n"
        "3️⃣ لاسترجاع درس: أرسل كلمة `هات` متبوعة باسم الدرس.\n"
        "4️⃣ لعرض كل دروسك: أرسل كلمة `دروسي` أو `/list`.\n\n"
        "💡 تلميح: يمكنك الضغط على الأزرار أدناه للتصفح أو التواصل."
    )
    
    keyboard = [
        [InlineKeyboardButton("📚 عرض دروسي", callback_data="show_list")],
        [InlineKeyboardButton("💬 مراسلة المطور للاقتراحات", url=f"https://t.me/{DEVELOPER_USERNAME.replace('@', '')}")]
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
            if username and username != "بدون يوزر":
                user_link = f"[{first_name}](https://t.me/{username.replace('@', '')})"
            else:
                user_link = f"{first_name} (بدون معرف)"
            
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
        # التحقق مما إذا كنت كتبت نصاً بعد أمر الإذاعة
        if not context.args:
            await update.message.reply_text("❌ يرجى كتابة النص المراد إرساله بعد الأمر هكذا:\n`/broadcast [اكتب رسالتك هنا]`", parse_mode="Markdown")
            return

        # دمج الكلمات المكتوبة بعد الأمر لتصبح هي رسالة البث
        announcement = " ".join(context.args)

        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        
        success_count = 0
        fail_count = 0
        
        for (u_id,) in users:
            try:
                await context.bot.send_message(chat_id=u_id, text=announcement, parse_mode="Markdown")
                success_count += 1
            except Exception:
                fail_count += 1
                
        await update.message.reply_text(f"📢 تم إرسال الإعلان بنجاح!\n✅ وصل إلى: {success_count} مستخدم\n❌ فشل الوصول إلى: {fail_count} مستخدم")
    else:
        await update.message.reply_text("هذا الأمر مخصص للمطور فقط ❌")
        
        success_count = 0
        fail_count = 0
        
        for (u_id,) in users:
            try:
                await context.bot.send_message(chat_id=u_id, text=announcement, parse_mode="Markdown")
                success_count += 1
            except Exception:
                fail_count += 1
                
        await update.message.reply_text(f"📢 تم إرسال الإعلان بنجاح!\n✅ وصل إلى: {success_count} مستخدم\n❌ فشل الوصول إلى: {fail_count} مستخدم")
    else:
        await update.message.reply_text("هذا الأمر مخصص للمطور فقط ❌")

async def send_lesson_content(user_id, title, chat_id, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT title, content_type, file_or_text FROM lessons WHERE user_id = ? AND title = ?", (user_id, title))
    row = cursor.fetchone()

    if row:
        t_title, c_type, data = row[0], row[1], row[2]
        keyboard = [
            [InlineKeyboardButton("📖 فتح", callback_data=f"op_{t_title[:10]}")],
            [InlineKeyboardButton("حذف 🗑️", callback_data=f"dl_{t_title[:10]}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if c_type == "text":
            await context.bot.send_message(chat_id=chat_id, text=f"📖 محتوى {t_title}:\n\n{data}", reply_markup=reply_markup)
        elif c_type == "photo":
            await context.bot.send_photo(chat_id=chat_id, photo=data, caption=f"📖 الدرس: {t_title}", reply_markup=reply_markup)
        elif c_type == "document":
            await context.bot.send_document(chat_id=chat_id, document=data, caption=f"📖 الدرس: {t_title}", reply_markup=reply_markup)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    list_keywords = ["قائمة", "اعرض", "اضهر", "أضهر", "دروسي", "الدروس"]
    if any(keyword in text for keyword in list_keywords) and not any(text.startswith(k) for k in ["حفظ", "احفظ", "هات", "أعطني", "اعطني"]):
        await list_lessons(update, context)
        return

    if text.startswith("حفظ ") or text.startswith("احفظ "):
        try:
            clean_text = text.replace("احفظ ", "").replace("حفظ ", "")
            parts = clean_text.split(":", 1)
            title = parts[0].strip()
            content = parts[1].strip()
            cursor.execute("INSERT INTO lessons VALUES (?, ?, ?, ?)", (user_id, title, "text", content))
            conn.commit()
            await update.message.reply_text(f"تم حفظ '{title}' بنجاح!")
        except Exception:
            await update.message.reply_text("الصيغة الصحيحة: حفظ اسم الدرس: المحتوى")
        return

    query_title = text
    for prefix in ["هات ", "أعطني ", "اعطني ", "ارسل ", "وريني "]:
        if text.startswith(prefix):
            query_title = text[len(prefix):].strip()
            break

    cursor.execute("SELECT title FROM lessons WHERE user_id = ? AND (LOWER(title) = LOWER(?) OR title LIKE ?)", (user_id, query_title, f"%{query_title}%"))
    row = cursor.fetchone()

    if row:
        await send_lesson_content(user_id, row[0], update.effective_chat.id, context)
    elif text.startswith(("هات", "أعطني", "اعطني", "ارسل", "الدرس")):
        await update.message.reply_text(f"لم أجد درساً باسم '{query_title}'.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    caption = update.message.caption
    if caption:
        doc_id = update.message.photo[-1].file_id
        cursor.execute("INSERT INTO lessons VALUES (?, ?, ?, ?)", (user_id, caption.strip(), "photo", doc_id))
        conn.commit()
        await update.message.reply_text(f"تم حفظ صورة '{caption.strip()}' بنجاح!")
    else:
        await update.message.reply_text("يرجى كتابة اسم الدرس في وصف الصورة.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    caption = update.message.caption
    if caption:
        doc_id = update.message.document.file_id
        cursor.execute("INSERT INTO lessons VALUES (?, ?, ?, ?)", (user_id, caption.strip(), "document", doc_id))
        conn.commit()
        await update.message.reply_text(f"تم حفظ الملف '{caption.strip()}' بنجاح!")
    else:
        await update.message.reply_text("يرجى كتابة اسم الدرس في وصف الملف.")

async def list_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("SELECT rowid, title, content_type FROM lessons WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    
    chat_id = update.effective_chat.id
    
    if rows:
        text = "📚 قائمة الدروس المحفوظة لديك:\nاختر الدرس للفتح أو الحذف:"
        keyboard = []
        for r in rows:
            row_id, title, c_type = r[0], r[1], r[2]
            type_label = "🖼️" if c_type == "photo" else ("📄" if c_type == "document" else "📝")
            
            # زر اسم الدرس في صف مستقل، وزر الحذف في صف تحته بمفرده
            keyboard.append([InlineKeyboardButton(f"{type_label} {title}", callback_data=f"op_{row_id}")])
            keyboard.append([InlineKeyboardButton("حذف 🗑️", callback_data=f"dl_{row_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            try:
                await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    else:
        empty_msg = "⚠️ لا توجد دروس محفوظة لديك بعد!"
        if update.callback_query:
            try:
                await update.callback_query.message.edit_text(empty_msg)
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=empty_msg)
        else:
            await context.bot.send_message(chat_id=chat_id, text=empty_msg)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data

    if data == "show_list":
        await list_lessons(update, context)
        return

    prefix, row_id = data.split("_", 1)
    cursor.execute("SELECT title FROM lessons WHERE rowid = ? AND user_id = ?", (row_id, user_id))
    row = cursor.fetchone()

    if not row:
        await query.message.reply_text("❌ عذراً، لم يتم العثور على هذا الدرس.")
        return

    matched_title = row[0]

    if prefix == "dl":
        cursor.execute("DELETE FROM lessons WHERE rowid = ? AND user_id = ?", (row_id, user_id))
        conn.commit()
        try:
            await query.edit_message_text(f"❌ تم حذف الدرس '{matched_title}' بنجاح.")
        except Exception:
            await query.message.reply_text(f"❌ تم حذف الدرس '{matched_title}' بنجاح.")
    elif prefix == "op":
        await send_lesson_content(user_id, matched_title, query.message.chat_id, context)

def main():
    request = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0)
    app = ApplicationBuilder().token("8965186384:AAEadFB6hGmoazwbQsoTe8oTTaUFRSZfIro").request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_lessons))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("users", list_all_users))
    app.add_handler(CommandHandler("broadcast", broadcast_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("Bot is starting...")
    app.run_polling()

if __name__ == '__main__':
    t = threading.Thread(target=run_web)
    t.start()
    main()
