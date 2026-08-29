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

# جدول لتخزين المواد الخاصة بكل مستخدم
cursor.execute('''
    CREATE TABLE IF NOT EXISTS subjects (
        user_id INTEGER,
        subject_name TEXT
    )
''')

# جدول لتخزين الفروع الخاصة بكل مادة
cursor.execute('''
    CREATE TABLE IF NOT EXISTS sections (
        user_id INTEGER,
        subject_name TEXT,
        section_name TEXT
    )
''')

# جدول لتخزين الدروس داخل الفروع
cursor.execute('''
    CREATE TABLE IF NOT EXISTS lessons (
        user_id INTEGER,
        subject_name TEXT,
        section_name TEXT,
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
        "مساحتك الشخصية لتنظيم دروسك عبر الأزرار التفاعلية للمواد والفروع 📚✨.\n"
        "اختر من القائمة أدناه للبدء:"
    )
    
    keyboard = [
        [InlineKeyboardButton("📚 عرض موادي ودروسي", callback_data="show_subjects")],
        [InlineKeyboardButton("💬 مراسلة المطور", url=f"https://t.me/{DEVELOPER_USERNAME.replace('@', '')}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup)

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

    cursor.execute("SELECT state, temp_data FROM user_states WHERE user_id = ?", (user_id,))
    state_row = cursor.fetchone()

    if state_row:
        state, temp_data = state_row[0], state_row[1]
        
        if state == "waiting_for_subject":
            sub_name = text
            cursor.execute("SELECT * FROM subjects WHERE user_id = ? AND subject_name = ?", (user_id, sub_name))
            if cursor.fetchone():
                await update.message.reply_text(f"⚠️ المادة '{sub_name}' موجودة مسبقاً!")
            else:
                cursor.execute("INSERT INTO subjects VALUES (?, ?)", (user_id, sub_name))
                conn.commit()
                await update.message.reply_text(f"✅ تمت إضافة المادة '{sub_name}' بنجاح!")
            
            cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
            conn.commit()
            await show_subjects_menu(update, context)
            return

        elif state == "waiting_for_section":
            subject = temp_data
            sec_name = text
            cursor.execute("SELECT * FROM sections WHERE user_id = ? AND subject_name = ? AND section_name = ?", (user_id, subject, sec_name))
            if cursor.fetchone():
                await update.message.reply_text(f"⚠️ الفرع '{sec_name}' موجود مسبقاً في هذه المادة!")
            else:
                cursor.execute("INSERT INTO sections VALUES (?, ?, ?)", (user_id, subject, sec_name))
                conn.commit()
                await update.message.reply_text(f"✅ تم إضافة الفرع '{sec_name}' لمادة [{subject}] بنجاح!")

            cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
            conn.commit()
            
            # إعادة عرض فروع المادة
            await show_sections_menu_direct(update, context, user_id, subject)
            return

        elif state.startswith("waiting_for_lesson_title_"):
            # temp_data يحتوي على "subject|section"
            parts = temp_data.split("|")
            subject, section = parts[0], parts[1]
            title = text
            
            # حفظ عنوان الدرس مؤقتاً والانتقال لطلب محتوى الدرس
            cursor.execute("INSERT OR REPLACE INTO user_states (user_id, state, temp_data) VALUES (?, ?, ?)", 
                           (user_id, f"waiting_for_lesson_content_{subject}|{section}|{title}", title))
            conn.commit()
            await update.message.reply_text(f"✍️ أرسل الآن محتوى الدرس '{title}' (أو أرسل صورة/ملف مباشرة):")
            return

        elif state.startswith("waiting_for_lesson_content_"):
            parts = state.replace("waiting_for_lesson_content_", "").split("|")
            subject, section, title = parts[0], parts[1], parts[2]
            
            cursor.execute("INSERT INTO lessons VALUES (?, ?, ?, ?, ?, ?)", (user_id, subject, section, title, "text", text))
            conn.commit()
            cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
            conn.commit()
            
            await update.message.reply_text(f"✅ تم حفظ الدرس '{title}' في [{subject} ➔ {section}] بنجاح!")
            await show_lessons_menu_direct(update, context, user_id, subject, section)
            return

    # إذا أرسل كلمة مفتاحية لعرض القائمة
    list_keywords = ["قائمة", "اعرض", "اضهر", "أضهر", "دروسي", "الدروس", "موادي"]
    if any(keyword in text for keyword in list_keywords):
        await show_subjects_menu(update, context)
        return

    await update.message.reply_text("❌ يرجى استخدام الأزرار التفاعلية لتصفح موادك أو كتابة أمر صحيح.\nاضغط /start للعودة للقائمة الرئيسية.")

async def handle_photo_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("SELECT state, temp_data FROM user_states WHERE user_id = ?", (user_id,))
    state_row = cursor.fetchone()

    if state_row and state_row[0].startswith("waiting_for_lesson_content_"):
        parts = state_row[0].replace("waiting_for_lesson_content_", "").split("|")
        subject, section, title = parts[0], parts[1], parts[2]

        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            c_type = "photo"
        elif update.message.document:
            file_id = update.message.document.file_id
            c_type = "document"
        else:
            return

        cursor.execute("INSERT INTO lessons VALUES (?, ?, ?, ?, ?, ?)", (user_id, subject, section, title, c_type, file_id))
        conn.commit()
        cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
        conn.commit()

        await update.message.reply_text(f"✅ تم حفظ الملف/الصورة للدرس '{title}' في [{subject} ➔ {section}] بنجاح!")
        await show_lessons_menu_direct(update, context, user_id, subject, section)
    else:
        await update.message.reply_text("⚠️ يرجى استخدام زر 'إضافة درس' من الأزرار التفاعلية قبل إرسال الملفات أو الصور.")

async def show_subjects_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else update.callback_query.from_user.id
    cursor.execute("SELECT subject_name FROM subjects WHERE user_id = ?", (user_id,))
    subjects = cursor.fetchall()
    
    text = "📚 قائمة موادي الدراسية:\nاختر المادة لتصفح فروعها ودروسها أو إدارتها:"
    keyboard = []
    
    if subjects:
        for (sub,) in subjects:
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

async def show_sections_menu_direct(update, context, user_id, subject):
    cursor.execute("SELECT section_name FROM sections WHERE user_id = ? AND subject_name = ?", (user_id, subject))
    sections = cursor.fetchall()
    
    keyboard = []
    if sections:
        text = f"📚 مادة: {subject}\nاختر الفرع المطلوب:"
        for (sec,) in sections:
            keyboard.append([
                InlineKeyboardButton(f"📂 فرع: {sec}", callback_data=f"sec_{subject}_{sec}"),
                InlineKeyboardButton("حذف الفرع 🗑️", callback_data=f"del_sec_{subject}_{sec}")
            ])
    else:
        text = f"📚 مادة: {subject}\n❌ أنت لا تملك أي فروع في هذه المادة حالياً."

    keyboard.append([InlineKeyboardButton("➕ إضافة فرع جديد", callback_data=f"add_sec_{subject}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للمواد", callback_data="show_subjects")])
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_lessons_menu_direct(update, context, user_id, subject, section):
    cursor.execute("SELECT rowid, title, content_type FROM lessons WHERE user_id = ? AND subject_name = ? AND section_name = ?", (user_id, subject, section))
    lessons = cursor.fetchall()
    
    keyboard = []
    if lessons:
        text = f"📂 مادة: {subject} ➔ فرع: {section}\nقائمة الدروس المحفوظة:"
        for rowid, title, c_type in lessons:
            type_label = "🖼️" if c_type == "photo" else ("📄" if c_type == "document" else "📝")
            keyboard.append([
                InlineKeyboardButton(f"{type_label} {title}", callback_data=f"op_{rowid}"),
                InlineKeyboardButton("حذف 🗑️", callback_data=f"dl_{rowid}")
            ])
    else:
        text = f"📂 مادة: {subject} ➔ فرع: {section}\n❌ أنت لا تملك أي دروس في هذا الفرع."

    keyboard.append([InlineKeyboardButton("➕ إضافة درس جديد", callback_data=f"add_lesson_{subject}_{section}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للفروع", callback_data=f"sub_{subject}")])
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))

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
        await query.message.edit_text("🏠 القائمة الرئيسية للبوت. اضغط /start للبدء من جديد.")
        return
    elif data == "add_subject":
        cursor.execute("INSERT OR REPLACE INTO user_states (user_id, state, temp_data) VALUES (?, ?, ?)", (user_id, "waiting_for_subject", ""))
        conn.commit()
        await query.message.edit_text("✍️ أرسل الآن اسم المادة الجديدة التي تريد إضافتها:")
        return

    # حذف مادة كاملة مع فروعها ودروسها
    if data.startswith("del_sub_"):
        sub_to_del = data.replace("del_sub_", "", 1)
        cursor.execute("DELETE FROM subjects WHERE user_id = ? AND subject_name = ?", (user_id, sub_to_del))
        cursor.execute("DELETE FROM sections WHERE user_id = ? AND subject_name = ?", (user_id, sub_to_del))
        cursor.execute("DELETE FROM lessons WHERE user_id = ? AND subject_name = ?", (user_id, sub_to_del))
        conn.commit()
        await show_subjects_menu(update, context)
        return

    # اختيار مادة لعرض فروعها
    if data.startswith("sub_"):
        subject = data.replace("sub_", "", 1)
        await show_sections_menu_direct(update, context, user_id, subject)
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
        cursor.execute("DELETE FROM sections WHERE user_id = ? AND subject_name = ? AND section_name = ?", (user_id, subject, section))
        cursor.execute("DELETE FROM lessons WHERE user_id = ? AND subject_name = ? AND section_name = ?", (user_id, subject, section))
        conn.commit()
        await show_sections_menu_direct(update, context, user_id, subject)
        return

    # اختيار فرع لعرض دروسه
    if data.startswith("sec_"):
        parts = data.replace("sec_", "", 1).split("_", 1)
        subject, section = parts[0], parts[1]
        await show_lessons_menu_direct(update, context, user_id, subject, section)
        return

    # طلب إضافة درس داخل فرع
    if data.startswith("add_lesson_"):
        parts = data.replace("add_lesson_", "", 1).split("_", 1)
        subject, section = parts[0], parts[1]
        cursor.execute("INSERT OR REPLACE INTO user_states (user_id, state, temp_data) VALUES (?, ?, ?)", 
                       (user_id, f"waiting_for_lesson_title_{subject}|{section}", f"{subject}|{section}"))
        conn.commit()
        await query.message.edit_text(f"✍️ أرسل الآن **عنوان الدرس** الجديد الذي تريد إضافته تحت [{subject} ➔ {section}]:", parse_mode="Markdown")
        return

    # فتح أو حذف درس منفرد
    if data.startswith("op_") or data.startswith("dl_"):
        prefix, rowid = data.split("_", 1)
        cursor.execute("SELECT subject_name, section_name, title, content_type, file_or_text FROM lessons WHERE rowid = ? AND user_id = ?", (rowid, user_id))
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
            await show_lessons_menu_direct(update, context, user_id, subject, section)
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
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_photo_document))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("Bot is starting...")
    app.run_polling()

if __name__ == '__main__':
    t = threading.Thread(target=run_web)
    t.start()
    main()
