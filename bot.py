from functools import lru_cache
import os
import time
import threading
from flask import Flask
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.request import HTTPXRequest
from supabase import create_client, Client

app = Flask(__name__)


@app.route("/")
def home():
  return "Bot is running 24/7!"


def run_web():
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)


DEVELOPER_USERNAME = "@ota_m_pro"
ADMIN_ID = 8504617214

# جلب المتغيرات من البيئة
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not BOT_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
  raise ValueError(
      "يرجى التأكد من ضبط BOT_TOKEN و SUPABASE_URL و SUPABASE_KEY في متغيرات البيئة!"
  )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- نظام الحماية من السبام وتخزين الذاكرة المؤقتة (Caching) ---
user_last_message_time = {}
SPAM_INTERVAL = 1.5  # الفاصل الزمني بالثواني لمنع السبام


def check_spam(user_id: int) -> bool:
  if user_id == ADMIN_ID:
    return False
  current_time = time.time()
  last_time = user_last_message_time.get(user_id, 0)
  if current_time - last_time < SPAM_INTERVAL:
    return True
  user_last_message_time[user_id] = current_time
  return False


# تخزين مؤقت محلي للبيانات المتكررة لتخفيف الضغط
local_cache = {
    "subjects": {},
    "sections": {},
    "notes": {},
}


def clear_user_cache(user_id: int):
  local_cache["subjects"].pop(user_id, None)
  local_cache["sections"].pop(user_id, None)
  local_cache["notes"].pop(user_id, None)


# --- القائمة الرئيسية ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user = update.effective_user
  if not user:
    return
  user_id = user.id

  if check_spam(user_id):
    return

  username = f"@{user.username}" if user.username else "بدون يوزر"
  first_name = user.first_name or "مستخدم"

  res = (
      supabase.table("users")
      .select("welcomed")
      .eq("user_id", user_id)
      .execute()
  )
  data = res.data

  if not data:
    supabase.table("users").insert({
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "welcomed": 0,
    }).execute()
    try:
      admin_msg = f"🔔 عضو جديد انضم للبوت!\n\n👤 الاسم: {first_name}\n🆔 المعرف: {username}\n🔢 الـ ID: `{user_id}`"
      await context.bot.send_message(
          chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown"
      )
    except Exception:
      pass
    is_first_time = True
  else:
    is_first_time = data[0].get("welcomed") == 0

  keyboard = [
      [InlineKeyboardButton("📚 عرض موادي ودروسي", callback_data="show_subjects")],
      [InlineKeyboardButton("📅 المهام اليومية", callback_data="show_tasks")],
      [
          InlineKeyboardButton(
              "💬 مراسلة المطور",
              url=f"https://t.me/{DEVELOPER_USERNAME.replace('@', '')}",
          )
      ],
  ]
  reply_markup = InlineKeyboardMarkup(keyboard)

  if is_first_time:
    supabase.table("users").update({"welcomed": 1}).eq(
        "user_id", user_id
    ).execute()
    welcome_text = (
        f"👋 أهلاً بك يا {first_name} في بوت BAC 2027 المطور!\n\n"
        "📌 **طريقة استخدام البوت:**\n"
        "• انقر على 'عرض موادي ودروسي' لإدارة جدولك، دروسك، وملاحظات كل مادة.\n"
        "• تنظيم خطتك ودراستك اليومية عبر 'المهام اليومية'.\n\n"
        "اختر من القائمة أدناه للبدء:"
    )
  else:
    welcome_text = (
        f"👋 أهلاً بك مجدداً يا {first_name}!\n\n"
        "مساحتك الشخصية لتنظيم دروسك، مهامك اليومية، وملاحظات موادك 📚✨.\n"
        "اختر من القائمة أدناه:"
    )

  if update.message:
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
  elif update.callback_query:
    await update.callback_query.message.edit_text(
        welcome_text, reply_markup=reply_markup
    )


async def lessons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if update.effective_user and check_spam(update.effective_user.id):
    return
  await show_subjects_menu(update, context)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if update.effective_user.id == ADMIN_ID:
    res = supabase.table("users").select("user_id", count="exact").execute()
    total_users = res.count if res.count is not None else len(res.data)
    await update.message.reply_text(
        f"📊 إحصائيات البوت:\nعدد الأعضاء المسجلين: {total_users}"
    )


async def list_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if update.effective_user.id == ADMIN_ID:
    res = (
        supabase.table("users")
        .select("user_id, username, first_name")
        .execute()
    )
    users = res.data
    if not users:
      await update.message.reply_text("لا توجد أي أعضاء مسجلين حتى الآن.")
      return
    text = "👥 قائمة الأعضاء المسجلين في البوت:\n\n"
    for idx, u in enumerate(users, 1):
      u_id = u.get("user_id")
      username = u.get("username")
      first_name = u.get("first_name") or "مستخدم"
      user_link = (
          f"[{first_name}](https://t.me/{username.replace('@', '')})"
          if username and username != "بدون يوزر"
          else f"{first_name} (بدون معرف)"
      )
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
      await update.message.reply_text(
          "❌ يرجى كتابة النص بعد الأمر هكذا:\n`/broadcast [الرسالة]`",
          parse_mode="Markdown",
      )
      return
    announcement = " ".join(context.args)
    res = supabase.table("users").select("user_id").execute()
    users = res.data
    success_count = fail_count = 0
    for u in users:
      u_id = u.get("user_id")
      try:
        await context.bot.send_message(
            chat_id=u_id, text=announcement, parse_mode="Markdown"
        )
        success_count += 1
      except Exception:
        fail_count += 1
    await update.message.reply_text(
        f"📢 تم الإرسال بنجاح!\n✅ وصل إلى: {success_count}\n❌ فشل: {fail_count}"
    )
  else:
    await update.message.reply_text("هذا الأمر مخصص للمطور فقط ❌")


async def show_subject_options(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, subject: str
):
  text = f"📖 **مادة: {subject}**\nاختر القسم الذي تريد تصفحه أو إدارته:"
  keyboard = [
      [
          InlineKeyboardButton(
              "📂 الفروع والدروس", callback_data=f"show_sec_list|{subject}"
          )
      ],
      [
          InlineKeyboardButton(
              "📝 ملاحظات هذه المادة", callback_data=f"show_sub_notes|{subject}"
          )
      ],
      [InlineKeyboardButton("حذف المادة 🗑️", callback_data=f"delsub|{subject}")],
      [
          InlineKeyboardButton(
              "🔙 رجوع للمواد", callback_data="show_subjects"
          )
      ],
  ]
  reply_markup = InlineKeyboardMarkup(keyboard)

  if update.callback_query:
    await update.callback_query.message.edit_text(
        text, reply_markup=reply_markup, parse_mode="Markdown"
    )
  else:
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def show_subject_notes_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, subject: str
):
  # استخدام الكاش المحلي لتخفيف الضغط
  cache_key = f"{user_id}_{subject}"
  if cache_key in local_cache["notes"]:
    notes = local_cache["notes"][cache_key]
  else:
    res = (
        supabase.table("subject_notes")
        .select("id, note_text")
        .eq("user_id", user_id)
        .eq("subject_name", subject)
        .order("id", desc=True)
        .execute()
    )
    notes = res.data
    local_cache["notes"][cache_key] = notes

  text = f"📝 **ملاحظات مادة [{subject}]:**\n\n"
  keyboard = []
  if notes:
    for n in notes:
      n_id = n.get("id")
      n_text = n.get("note_text")
      display_text = n_text[:25] + "..." if len(n_text) > 25 else n_text
      keyboard.append([
          InlineKeyboardButton(
              f"📌 {display_text}", callback_data=f"view_sub_note|{n_id}"
          ),
          InlineKeyboardButton(
              "حذف 🗑️", callback_data=f"del_sub_note|{n_id}|{subject}"
          ),
      ])
  else:
    text += "لا توجد أي ملاحظات محفوظة لهذه المادة حالياً."

  keyboard.append([
      InlineKeyboardButton(
          "➕ إضافة ملاحظة للمادة", callback_data=f"add_sub_note|{subject}"
      )
  ])
  keyboard.append(
      [InlineKeyboardButton("🔙 رجوع خيارات المادة", callback_data=f"sub|{subject}")]
  )

  if update.callback_query:
    await update.callback_query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
  else:
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def show_tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = (
      update.effective_user.id
      if update.effective_user
      else update.callback_query.from_user.id
  )
  res = (
      supabase.table("tasks")
      .select("id, task_text, is_completed")
      .eq("user_id", user_id)
      .order("id", desc=False)
      .execute()
  )
  tasks = res.data

  text = (
      "📅 **قائمة مهامك اليومية:**\n(انقر على المهمة لتغيير حالتها"
      " مكتملة/غير مكتملة)\n\n"
  )
  keyboard = []
  if tasks:
    for t in tasks:
      t_id = t.get("id")
      t_text = t.get("task_text")
      is_done = t.get("is_completed")
      status_icon = "✅" if is_done else "❌"

      keyboard.append([
          InlineKeyboardButton(
              f"{status_icon} {t_text}", callback_data=f"toggle_task|{t_id}"
          ),
          InlineKeyboardButton("🗑️", callback_data=f"del_task|{t_id}"),
      ])
  else:
    text += "لا توجد مهام يومية حالياً."

  keyboard.append([InlineKeyboardButton("➕ إضافة مهمة جديدة", callback_data="add_task")])
  keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])

  if update.callback_query:
    await update.callback_query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
  else:
    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id
  if check_spam(user_id):
    await update.message.reply_text(
        "⚠️ أرجو التمهل قليلاً، أنت تقوم بإرسال الرسائل بسرعة كبيرة!"
    )
    return

  text = update.message.text.strip()

  res = (
      supabase.table("user_states")
      .select("state, temp_data")
      .eq("user_id", user_id)
      .execute()
  )
  state_row = res.data

  if state_row:
    state = state_row[0].get("state")
    temp_data = state_row[0].get("temp_data") or ""

    if state == "waiting_for_subject":
      sub_name = text
      check = (
          supabase.table("subjects")
          .select("*")
          .eq("user_id", user_id)
          .eq("subject_name", sub_name)
          .execute()
      )
      if check.data:
        await update.message.reply_text(
            f"⚠️ المادة '{sub_name}' موجودة مسبقاً!"
        )
      else:
        supabase.table("subjects").insert(
            {"user_id": user_id, "subject_name": sub_name}
        ).execute()
        clear_user_cache(user_id)
        await update.message.reply_text(
            f"✅ تمت إضافة المادة '{sub_name}' بنجاح!"
        )
      supabase.table("user_states").delete().eq("user_id", user_id).execute()
      await show_subjects_menu(update, context)
      return

    elif state == "waiting_for_section":
      subject = temp_data
      sec_name = text
      check = (
          supabase.table("sections")
          .select("*")
          .eq("user_id", user_id)
          .eq("subject_name", subject)
          .eq("section_name", sec_name)
          .execute()
      )
      if check.data:
        await update.message.reply_text(
            f"⚠️ الفرع '{sec_name}' موجود مسبقاً في هذه المادة!"
        )
      else:
        supabase.table("sections").insert({
            "user_id": user_id,
            "subject_name": subject,
            "section_name": sec_name,
        }).execute()
        clear_user_cache(user_id)
        await update.message.reply_text(
            f"✅ تم إضافة الفرع '{sec_name}' لمادة [{subject}] بنجاح!"
        )
      supabase.table("user_states").delete().eq("user_id", user_id).execute()
      await show_sections_menu_direct(update, context, user_id, subject)
      return

    elif state.startswith("waiting_for_lesson_title_"):
      parts = temp_data.split("|")
      subject, section = parts[0], parts[1]
      title = text
      supabase.table("user_states").upsert({
          "user_id": user_id,
          "state": f"waiting_for_lesson_content_{subject}|{section}|{title}",
          "temp_data": title,
      }).execute()
      await update.message.reply_text(
          f"✍️ أرسل الآن محتوى الدرس '{title}' (أو أرسل صورة/فيديو/ملف مباشرة):"
      )
      return

    elif state.startswith("waiting_for_lesson_content_"):
      parts = state.replace("waiting_for_lesson_content_", "").split("|", 2)
      subject, section, title = parts[0], parts[1], parts[2]
      supabase.table("lessons").insert({
          "user_id": user_id,
          "subject_name": subject,
          "section_name": section,
          "title": title,
          "content_type": "text",
          "file_or_text": text,
      }).execute()
      supabase.table("user_states").delete().eq("user_id", user_id).execute()
      clear_user_cache(user_id)
      await update.message.reply_text(
          f"✅ تم حفظ الدرس '{title}' في [{subject} ➔ {section}] بنجاح!"
      )
      await show_lessons_menu_direct(update, context, user_id, subject, section)
      return

    elif state.startswith("waiting_for_edit_lesson_"):
      lesson_id = int(state.replace("waiting_for_edit_lesson_", ""))
      new_title = text
      supabase.table("lessons").update({"title": new_title}).eq(
          "id", lesson_id
      ).eq("user_id", user_id).execute()
      res_lesson = (
          supabase.table("lessons")
          .select("subject_name, section_name")
          .eq("id", lesson_id)
          .execute()
      )
      supabase.table("user_states").delete().eq("user_id", user_id).execute()
      clear_user_cache(user_id)

      if res_lesson.data:
        sub = res_lesson.data[0].get("subject_name")
        sec = res_lesson.data[0].get("section_name")
        await update.message.reply_text(
            f"✅ تم تعديل اسم الدرس بنجاح إلى: '{new_title}'"
        )
        await show_lessons_menu_direct(update, context, user_id, sub, sec)
      else:
        await update.message.reply_text("✅ تم التعديل بنجاح.")
        await show_subjects_menu(update, context)
      return

    elif state.startswith("waiting_for_sub_note_"):
      subject = state.replace("waiting_for_sub_note_", "")
      supabase.table("subject_notes").insert({
          "user_id": user_id,
          "subject_name": subject,
          "note_text": text,
      }).execute()
      supabase.table("user_states").delete().eq("user_id", user_id).execute()
      clear_user_cache(user_id)
      await update.message.reply_text(
          f"✅ تم حفظ الملاحظة لمادة [{subject}] بنجاح!"
      )
      await show_subject_notes_menu(update, context, user_id, subject)
      return

    elif state == "waiting_for_task":
      supabase.table("tasks").insert(
          {"user_id": user_id, "task_text": text, "is_completed": False}
      ).execute()
      supabase.table("user_states").delete().eq("user_id", user_id).execute()
      await update.message.reply_text("✅ تم إضافة المهمة بنجاح!")
      await show_tasks_menu(update, context)
      return

  list_keywords = ["قائمة", "اعرض", "اضهر", "أضهر", "دروسي", "الدروس", "موادي"]
  if any(keyword in text for keyword in list_keywords):
    await show_subjects_menu(update, context)
    return

  await update.message.reply_text(
      "❌ يرجى استخدام الأزرار التفاعلية لتصفح موادك أو كتابة أمر صحيح.\nاضغط"
      " /start للعودة للقائمة الرئيسية."
  )


async def handle_photo_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id
  if check_spam(user_id):
    return

  res = (
      supabase.table("user_states")
      .select("state, temp_data")
      .eq("user_id", user_id)
      .execute()
  )
  state_row = res.data

  if update.message.photo:
    file_id = update.message.photo[-1].file_id
    c_type = "photo"
  elif update.message.document:
    file_id = update.message.document.file_id
    c_type = "document"
  elif update.message.video:
    file_id = update.message.video.file_id
    c_type = "video"
  else:
    return

  if state_row:
    state = state_row[0].get("state")
    temp_data = state_row[0].get("temp_data") or ""

    if state.startswith("waiting_for_lesson_title_"):
      parts = temp_data.split("|")
      subject, section = parts[0], parts[1]
      title = (
          update.message.caption
          if update.message.caption
          else "ملف/فيديو/صورة درس"
      )
      supabase.table("lessons").insert({
          "user_id": user_id,
          "subject_name": subject,
          "section_name": section,
          "title": title,
          "content_type": c_type,
          "file_or_text": file_id,
      }).execute()
      supabase.table("user_states").delete().eq("user_id", user_id).execute()
      clear_user_cache(user_id)
      await update.message.reply_text(
          f"✅ تم حفظ الوسائط للدرس '{title}' في [{subject} ➔ {section}] بنجاح!"
      )
      await show_lessons_menu_direct(update, context, user_id, subject, section)
      return

    elif state.startswith("waiting_for_lesson_content_"):
      parts = state.replace("waiting_for_lesson_content_", "").split("|", 2)
      subject, section, title = parts[0], parts[1], parts[2]
      supabase.table("lessons").insert({
          "user_id": user_id,
          "subject_name": subject,
          "section_name": section,
          "title": title,
          "content_type": c_type,
          "file_or_text": file_id,
      }).execute()
      supabase.table("user_states").delete().eq("user_id", user_id).execute()
      clear_user_cache(user_id)
      await update.message.reply_text(
          f"✅ تم حفظ الوسائط للدرس '{title}' في [{subject} ➔ {section}] بنجاح!"
      )
      await show_lessons_menu_direct(update, context, user_id, subject, section)
      return

  await update.message.reply_text(
      "⚠️ يرجى استخدام زر 'إضافة درس' من الأزرار التفاعلية قبل إرسال الملفات،"
      " الفيديوهات أو الصور."
  )


async def show_subjects_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = (
      update.effective_user.id
      if update.effective_user
      else update.callback_query.from_user.id
  )

  # استخدام الكاش المحلي
  if user_id in local_cache["subjects"]:
    subjects = local_cache["subjects"][user_id]
  else:
    res = (
        supabase.table("subjects")
        .select("subject_name")
        .eq("user_id", user_id)
        .execute()
    )
    subjects = res.data
    local_cache["subjects"][user_id] = subjects

  text = "📚 قائمة موادي الدراسية:\nاختر المادة لتصفح فروعها، ملاحظاتها أو إدارتها:"
  keyboard = []
  if subjects:
    for item in subjects:
      sub = item.get("subject_name")
      keyboard.append([InlineKeyboardButton(f"📖 {sub}", callback_data=f"sub|{sub}")])
  keyboard.append([InlineKeyboardButton("➕ إضافة مادة جديدة", callback_data="add_subject")])
  keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
  reply_markup = InlineKeyboardMarkup(keyboard)

  if update.callback_query:
    try:
      await update.callback_query.message.edit_text(
          text, reply_markup=reply_markup
      )
    except Exception:
      await context.bot.send_message(
          chat_id=update.effective_chat.id, text=text, reply_markup=reply_markup
      )
  else:
    await update.message.reply_text(text, reply_markup=reply_markup)


async def show_sections_menu_direct(update, context, user_id, subject):
  cache_key = f"{user_id}_{subject}"
  if cache_key in local_cache["sections"]:
    sections = local_cache["sections"][cache_key]
  else:
    res = (
        supabase.table("sections")
        .select("section_name")
        .eq("user_id", user_id)
        .eq("subject_name", subject)
        .execute()
    )
    sections = res.data
    local_cache["sections"][cache_key] = sections

  keyboard = []
  if sections:
    text = f"📚 مادة: {subject}\nاختر الفرع المطلوب:"
    for item in sections:
      sec = item.get("section_name")
      keyboard.append([
          InlineKeyboardButton(f"📂 فرع: {sec}", callback_data=f"sec|{subject}|{sec}"),
          InlineKeyboardButton(
              "حذف الفرع 🗑️", callback_data=f"delsec|{subject}|{sec}"
          ),
      ])
  else:
    text = f"📚 مادة: {subject}\n❌ أنت لا تملك أي فروع في هذه المادة حالياً."
  keyboard.append([
      InlineKeyboardButton(
          "➕ إضافة فرع جديد", callback_data=f"addsec|{subject}"
      )
  ])
  keyboard.append(
      [InlineKeyboardButton("🔙 رجوع خيارات المادة", callback_data=f"sub|{subject}")]
  )

  if update.callback_query:
    await update.callback_query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )
  else:
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_lessons_menu_direct(update, context, user_id, subject, section):
  res = (
      supabase.table("lessons")
      .select("id, title, content_type")
      .eq("user_id", user_id)
      .eq("subject_name", subject)
      .eq("section_name", section)
      .execute()
  )
  lessons = res.data

  keyboard = []
  if lessons:
    text = f"📂 مادة: {subject} ➔ فرع: {section}\nقائمة الدروس المحفوظة:"
    for item in lessons:
      lesson_id = item.get("id")
      title = item.get("title")
      c_type = item.get("content_type")
      type_label = (
          "🎥"
          if c_type == "video"
          else (
              "🖼️"
              if c_type == "photo"
              else ("📄" if c_type == "document" else "📝")
          )
      )
      keyboard.append([
          InlineKeyboardButton(
              f"{type_label} {title}", callback_data=f"op|{lesson_id}"
          ),
          InlineKeyboardButton("حذف 🗑️", callback_data=f"dl|{lesson_id}"),
      ])
  else:
    text = f"📂 مادة: {subject} ➔ فرع: {section}\n❌ أنت لا تملك أي دروس في هذا الفرع."
  keyboard.append([
      InlineKeyboardButton(
          "➕ إضافة درس جديد", callback_data=f"addles|{subject}|{section}"
      )
  ])
  keyboard.append(
      [
          InlineKeyboardButton(
              "🔙 رجوع للفروع", callback_data=f"show_sec_list|{subject}"
          )
      ]
  )

  if update.callback_query:
    await update.callback_query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )
  else:
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
  query = update.callback_query
  user_id = query.from_user.id
  if check_spam(user_id):
    await query.answer("⚠️ يرجى عدم الضغط بسرعة كبيرة!", show_alert=True)
    return

  await query.answer()
  data = query.data

  if data == "show_subjects":
    await show_subjects_menu(update, context)
    return
  elif data == "main_menu":
    supabase.table("user_states").delete().eq("user_id", user_id).execute()
    await start(update, context)
    return
  elif data == "add_subject":
    supabase.table("user_states").upsert({
        "user_id": user_id,
        "state": "waiting_for_subject",
        "temp_data": "",
    }).execute()
    await query.message.edit_text(
        "✍️ أرسل الآن اسم المادة الجديدة التي تريد إضافتها:"
    )
    return

  if data.startswith("sub|"):
    subject = data.split("|", 1)[1]
    await show_subject_options(update, context, user_id, subject)
    return

  if data.startswith("show_sec_list|"):
    subject = data.split("|", 1)[1]
    await show_sections_menu_direct(update, context, user_id, subject)
    return

  if data.startswith("show_sub_notes|"):
    subject = data.split("|", 1)[1]
    await show_subject_notes_menu(update, context, user_id, subject)
    return

  if data.startswith("add_sub_note|"):
    subject = data.split("|", 1)[1]
    supabase.table("user_states").upsert({
        "user_id": user_id,
        "state": f"waiting_for_sub_note_{subject}",
        "temp_data": subject,
    }).execute()
    await query.message.edit_text(
        f"✍️ أرسل الآن نص الملاحظة التي تريد إضافتها لمادة [{subject}]:"
    )
    return

  if data.startswith("view_sub_note|"):
    n_id = int(data.split("|")[1])
    res = (
        supabase.table("subject_notes")
        .select("note_text, subject_name")
        .eq("id", n_id)
        .eq("user_id", user_id)
        .execute()
    )
    if res.data:
      note_text = res.data[0].get("note_text")
      sub = res.data[0].get("subject_name")
      kb = InlineKeyboardMarkup([[
          InlineKeyboardButton(
              "🔙 رجوع لملاحظات المادة", callback_data=f"show_sub_notes|{sub}"
          )
      ]])
      await query.message.edit_text(
          f"📝 **ملاحظة [{sub}]:**\n\n{note_text}",
          reply_markup=kb,
          parse_mode="Markdown",
      )
    return

  if data.startswith("del_sub_note|"):
    parts = data.split("|")
    n_id = int(parts[1])
    subject = parts[2]
    supabase.table("subject_notes").delete().eq("id", n_id).eq(
        "user_id", user_id
    ).execute()
    clear_user_cache(user_id)
    await show_subject_notes_menu(update, context, user_id, subject)
    return

  if data == "show_tasks":
    await show_tasks_menu(update, context)
    return
  elif data == "add_task":
    supabase.table("user_states").upsert({
        "user_id": user_id,
        "state": "waiting_for_task",
        "temp_data": "",
    }).execute()
    await query.message.edit_text("✍️ أرسل الآن اسم أو نص المهمة الجديدة:")
    return
  elif data.startswith("toggle_task|"):
    t_id = int(data.split("|")[1])
    res = (
        supabase.table("tasks")
        .select("is_completed")
        .eq("id", t_id)
        .eq("user_id", user_id)
        .execute()
    )
    if res.data:
      current_status = res.data[0].get("is_completed")
      supabase.table("tasks").update({"is_completed": not current_status}).eq(
          "id", t_id
      ).eq("user_id", user_id).execute()
      await show_tasks_menu(update, context)
    return
  elif data.startswith("del_task|"):
    t_id = int(data.split("|")[1])
    supabase.table("tasks").delete().eq("id", t_id).eq(
        "user_id", user_id
    ).execute()
    await show_tasks_menu(update, context)
    return

  if data.startswith("delsub|"):
    sub_to_del = data.split("|", 1)[1]
    supabase.table("subjects").delete().eq("user_id", user_id).eq(
        "subject_name", sub_to_del
    ).execute()
    supabase.table("sections").delete().eq("user_id", user_id).eq(
        "subject_name", sub_to_del
    ).execute()
    supabase.table("lessons").delete().eq("user_id", user_id).eq(
        "subject_name", sub_to_del
    ).execute()
    supabase.table("subject_notes").delete().eq("user_id", user_id).eq(
        "subject_name", sub_to_del
    ).execute()
    clear_user_cache(user_id)
    await show_subjects_menu(update, context)
    return

  if data.startswith("addsec|"):
    subject = data.split("|", 1)[1]
    supabase.table("user_states").upsert({
        "user_id": user_id,
        "state": "waiting_for_section",
        "temp_data": subject,
    }).execute()
    await query.message.edit_text(
        f"✍️ أرسل الآن اسم الفرع الجديد الذي تريد إضافته لمادة [{subject}]:"
    )
    return

  if data.startswith("delsec|"):
    parts = data.split("|")
    subject, section = parts[1], parts[2]
    supabase.table("sections").delete().eq("user_id", user_id).eq(
        "subject_name", subject
    ).eq("section_name", section).execute()
    supabase.table("lessons").delete().eq("user_id", user_id).eq(
        "subject_name", subject
    ).eq("section_name", section).execute()
    clear_user_cache(user_id)
    await show_sections_menu_direct(update, context, user_id, subject)
    return

  if data.startswith("sec|"):
    parts = data.split("|")
    subject, section = parts[1], parts[2]
    await show_lessons_menu_direct(update, context, user_id, subject, section)
    return

  if data.startswith("addles|"):
    parts = data.split("|")
    subject, section = parts[1], parts[2]
    supabase.table("user_states").upsert({
        "user_id": user_id,
        "state": f"waiting_for_lesson_title_{subject}|{section}",
        "temp_data": f"{subject}|{section}",
    }).execute()
    await query.message.edit_text(
        "✍️ أرسل الآن **عنوان الدرس** الجديد (أو أرسل الفيديو/الصورة/الملف"
        " مباشرة):",
        parse_mode="Markdown",
    )
    return

  if data.startswith("edit|"):
    lesson_id = int(data.split("|")[1])
    supabase.table("user_states").upsert({
        "user_id": user_id,
        "state": f"waiting_for_edit_lesson_{lesson_id}",
        "temp_data": "",
    }).execute()
    await query.message.reply_text("✍️ أرسل الآن **اسم الدرس الجديد**:")
    return

  if data.startswith("op|") or data.startswith("dl|"):
    prefix, lesson_id_str = data.split("|", 1)
    lesson_id = int(lesson_id_str)
    res = (
        supabase.table("lessons")
        .select("*")
        .eq("id", lesson_id)
        .eq("user_id", user_id)
        .execute()
    )

    if not res.data:
      await query.message.reply_text("❌ عذراً، لم يتم العثور على العنصر.")
      return

    row = res.data[0]
    subject = row.get("subject_name")
    section = row.get("section_name")
    title = row.get("title")
    c_type = row.get("content_type")
    data_val = row.get("file_or_text")
    chat_id = query.message.chat_id

    if prefix == "dl":
      supabase.table("lessons").delete().eq("id", lesson_id).eq(
          "user_id", user_id
      ).execute()
      clear_user_cache(user_id)
      await query.message.reply_text(f"❌ تم حذف الدرس '{title}' بنجاح.")
      await show_lessons_menu_direct(update, context, user_id, subject, section)
    elif prefix == "op":
      action_keyboard = InlineKeyboardMarkup([[
          InlineKeyboardButton("تعديل الاسم ✏️", callback_data=f"edit|{lesson_id}"),
          InlineKeyboardButton(
              "حذف الدرس 🗑️", callback_data=f"dl|{lesson_id}"
          ),
      ]])
      if c_type == "text":
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📖 [{subject} / {section}] - {title}:\n\n{data_val}",
            reply_markup=action_keyboard,
        )
      elif c_type == "photo":
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=data_val,
            caption=f"📖 [{subject} / {section}] - {title}",
            reply_markup=action_keyboard,
        )
      elif c_type == "document":
        await context.bot.send_document(
            chat_id=chat_id,
            document=data_val,
            caption=f"📖 [{subject} / {section}] - {title}",
            reply_markup=action_keyboard,
        )
      elif c_type == "video":
        await context.bot.send_video(
            chat_id=chat_id,
            video=data_val,
            caption=f"📖 [{subject} / {section}] - {title}",
            reply_markup=action_keyboard,
        )


async def post_init(application):
  commands = [
      BotCommand("start", "تشغيل البوت وعرض القائمة الرئيسية"),
      BotCommand("lessons", "عرض قائمة المواد والدروس المحفوظة"),
  ]
  try:
    await application.bot.set_my_commands(commands)
  except Exception:
    pass


def main():
  request = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0)
  application = (
      ApplicationBuilder()
      .token(BOT_TOKEN)
      .request(request)
      .post_init(post_init)
      .build()
  )

  application.add_handler(CommandHandler("start", start))
  application.add_handler(CommandHandler("lessons", lessons_command))
  application.add_handler(CommandHandler("stats", stats))
  application.add_handler(CommandHandler("users", list_all_users))
  application.add_handler(CommandHandler("broadcast", broadcast_message))
  application.add_handler(
      MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
  )
  application.add_handler(
      MessageHandler(
          filters.PHOTO | filters.Document.ALL | filters.Video,
          handle_photo_document,
      )
  )
  application.add_handler(CallbackQueryHandler(button_callback))

  t = threading.Thread(target=run_web, daemon=True)
  t.start()

  print("Bot is starting with polling...")
  application.run_polling()


if __name__ == "__main__":
  main()
