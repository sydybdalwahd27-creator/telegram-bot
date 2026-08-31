import os
import time
import threading
import asyncio
from functools import wraps
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
import logging
from groq import Groq

# ───────────────────────────────────────────────
# إعداد السجل (Logging)
# ───────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────
# تهيئة المتغيرات والعملاء
# ───────────────────────────────────────────────
DEVELOPER_USERNAME = "@ota_m_pro"
ADMIN_ID = 8504617214

BOT_TOKEN = os.environ.get("BOT_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GROQ_API_KEY = (os.environ.get("GROQ_API_KEY") or "").strip()
GROQ_MODEL = "llama-3.3-70b-versatile"

if not BOT_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "يرجى التأكد من ضبط BOT_TOKEN و SUPABASE_URL و SUPABASE_KEY في متغيرات البيئة!"
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = (
    Groq(api_key=GROQ_API_KEY, timeout=30.0, max_retries=2)
    if GROQ_API_KEY
    else None
)
if not groq_client:
    logger.warning("GROQ_API_KEY is missing; AI service is disabled.")

# ───────────────────────────────────────────────
# خادم ويب وهمي (للـ Health Check على Render)
# ───────────────────────────────────────────────
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()


# ───────────────────────────────────────────────
# نظام الحماية من السبام (مع تنظيف تلقائي)
# ───────────────────────────────────────────────
user_last_message_time = {}
SPAM_INTERVAL = 0.3
SPAM_CLEANUP_INTERVAL = 3600  # تنظيف كل ساعة


def check_spam(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return False

    current_time = time.time()

    # تنظيف المستخدمين القدامى (تسريب الذاكرة)
    cutoff = current_time - SPAM_CLEANUP_INTERVAL
    for uid, last in list(user_last_message_time.items()):
        if last < cutoff:
            user_last_message_time.pop(uid, None)

    last_time = user_last_message_time.get(user_id, 0)
    if current_time - last_time < SPAM_INTERVAL:
        return True

    user_last_message_time[user_id] = current_time
    return False


# ───────────────────────────────────────────────
# التخزين المؤقت المحلي (Caching)
# ───────────────────────────────────────────────
local_cache = {
    "subjects": {},
    "sections": {},
    "lessons": {},
    "notes": {},
}


def clear_user_cache(user_id: int):
    local_cache["subjects"].pop(user_id, None)
    for key in list(local_cache["sections"].keys()):
        if key.startswith(f"{user_id}_"):
            local_cache["sections"].pop(key, None)
    for key in list(local_cache["lessons"].keys()):
        if key.startswith(f"{user_id}_"):
            local_cache["lessons"].pop(key, None)
    for key in list(local_cache["notes"].keys()):
        if key.startswith(f"{user_id}_"):
            local_cache["notes"].pop(key, None)


# ───────────────────────────────────────────────
# دوال مساعدة لـ Supabase (غير المتزامنة)
# ───────────────────────────────────────────────
async def sb_execute(func):
    """تشغيل عمليات Supabase المتزامنة في thread منفصل."""
    return await asyncio.to_thread(func)


# ───────────────────────────────────────────────
# Decorator للأوامر المخصصة للمطور
# ───────────────────────────────────────────────
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id != ADMIN_ID:
            if update.message:
                await update.message.reply_text("هذا الأمر مخصص للمطور فقط ❌")
            return
        return await func(update, context)
    return wrapper


# ───────────────────────────────────────────────
# معالج الأخطاء العام
# ───────────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "عذراً، حدث خطأ غير متوقع. يرجى المحاولة لاحقاً."
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")


# ───────────────────────────────────────────────
# أوامر البوت (تظهر في قائمة /)
# ───────────────────────────────────────────────
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "القائمة الرئيسية 🏠"),
        BotCommand("lessons", "عرض موادي ودروسي 📚"),
        BotCommand("tasks", "المهام اليومية 📅"),
        BotCommand("help", "مساعدة ℹ️"),
    ])


# ───────────────────────────────────────────────
# /start
# ───────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    user_id = user.id
    if check_spam(user_id):
        return

    username = f"@{user.username}" if user.username else "بدون يوزر"
    first_name = user.first_name or "مستخدم"

    try:
        res = await sb_execute(
            lambda: supabase.table("users")
            .select("welcomed")
            .eq("user_id", user_id)
            .execute()
        )
        data = res.data
    except Exception:
        data = []

    if not data:
        try:
            await sb_execute(
                lambda: supabase.table("users").insert({
                    "user_id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "welcomed": 0,
                }).execute()
            )
        except Exception:
            pass
        try:
            admin_msg = (
                f"🔔 عضو جديد انضم للبوت!\n\n"
                f"👤 الاسم: {first_name}\n"
                f"🆔 المعرف: {username}\n"
                f"🔢 الـ ID: `{user_id}`"
            )
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
        try:
            await sb_execute(
                lambda: supabase.table("users")
                .update({"welcomed": 1})
                .eq("user_id", user_id)
                .execute()
            )
        except Exception:
            pass
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


# ───────────────────────────────────────────────
# /lessons
# ───────────────────────────────────────────────
async def lessons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or check_spam(user.id):
        return
    await show_subjects_menu(update, context)


# ───────────────────────────────────────────────
# /tasks
# ───────────────────────────────────────────────
async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or check_spam(user.id):
        return
    await show_tasks_menu(update, context)


# ───────────────────────────────────────────────
# /help
# ───────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 **دليل استخدام البوت:**\n\n"
        "• /start — القائمة الرئيسية\n"
        "• /lessons — عرض موادك ودروسك\n"
        "• /tasks — المهام اليومية\n"
        "• يمكنك إرسال أي سؤال علمي وسيجيبك الذكاء الاصطناعي 📚\n\n"
        f"للتواصل: [مراسلة المطور](https://t.me/ota_m_pro)"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ───────────────────────────────────────────────
# أوامر المطور
# ───────────────────────────────────────────────
@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        res = await sb_execute(
            lambda: supabase.table("users").select("user_id", count="exact").execute()
        )
        total_users = res.count if res.count is not None else len(res.data)
    except Exception:
        total_users = 0
    await update.message.reply_text(
        f"📊 إحصائيات البوت:\nعدد الأعضاء المسجلين: {total_users}"
    )


@admin_only
async def list_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        res = await sb_execute(
            lambda: supabase.table("users")
            .select("user_id, username, first_name")
            .execute()
        )
        users = res.data
    except Exception:
        users = []

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


@admin_only
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ يرجى كتابة النص بعد الأمر هكذا:\n`/broadcast [الرسالة]`",
            parse_mode="Markdown",
        )
        return

    announcement = " ".join(context.args)
    try:
        res = await sb_execute(
            lambda: supabase.table("users").select("user_id").execute()
        )
        users = res.data
    except Exception:
        users = []

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
        await asyncio.sleep(0.05)  # Rate limiting

    await update.message.reply_text(
        f"📢 تم الإرسال بنجاح!\n✅ وصل إلى: {success_count}\n❌ فشل: {fail_count}"
    )


# ───────────────────────────────────────────────
# القوائم التفاعلية
# ───────────────────────────────────────────────
async def show_subjects_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id

    if user_id in local_cache["subjects"]:
        subjects = local_cache["subjects"][user_id]
    else:
        try:
            res = await sb_execute(
                lambda: supabase.table("subjects")
                .select("subject_name")
                .eq("user_id", user_id)
                .execute()
            )
            subjects = res.data
        except Exception:
            subjects = []
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
            await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
        except Exception:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text=text, reply_markup=reply_markup
            )
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


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


async def show_sections_menu_direct(update, context, user_id, subject):
    cache_key = f"{user_id}_{subject}"
    if cache_key in local_cache["sections"]:
        sections = local_cache["sections"][cache_key]
    else:
        try:
            res = await sb_execute(
                lambda: supabase.table("sections")
                .select("section_name")
                .eq("user_id", user_id)
                .eq("subject_name", subject)
                .execute()
            )
            sections = res.data
        except Exception:
            sections = []
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
    cache_key = f"{user_id}_{subject}_{section}"
    if cache_key in local_cache["lessons"]:
        lessons = local_cache["lessons"][cache_key]
    else:
        try:
            res = await sb_execute(
                lambda: supabase.table("lessons")
                .select("id, title, content_type")
                .eq("user_id", user_id)
                .eq("subject_name", subject)
                .eq("section_name", section)
                .execute()
            )
            lessons = res.data
        except Exception:
            lessons = []
        local_cache["lessons"][cache_key] = lessons

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


async def show_subject_notes_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, subject: str
):
    cache_key = f"{user_id}_{subject}"
    if cache_key in local_cache["notes"]:
        notes = local_cache["notes"][cache_key]
    else:
        try:
            res = await sb_execute(
                lambda: supabase.table("subject_notes")
                .select("id, note_text")
                .eq("user_id", user_id)
                .eq("subject_name", subject)
                .order("id", desc=True)
                .execute()
            )
            notes = res.data
        except Exception:
            notes = []
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
    user = update.effective_user
    if not user:
        return
    user_id = user.id

    try:
        res = await sb_execute(
            lambda: supabase.table("tasks")
            .select("id, task_text, is_completed")
            .eq("user_id", user_id)
            .order("id", desc=False)
            .execute()
        )
        tasks = res.data
    except Exception:
        tasks = []

    text = (
        "📅 **قائمة مهامك اليومية:**\n"
        "(انقر على المهمة لتغيير حالتها مكتملة/غير مكتملة)\n\n"
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


# ───────────────────────────────────────────────
# معالج النصوص (الحالات + الذكاء الاصطناعي)
# ───────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id

    if check_spam(user_id):
        await update.message.reply_text(
            "⚠️ أرجو التمهل قليلاً، أنت تقوم بإرسال الرسائل بسرعة كبيرة!"
        )
        return

    text = update.message.text.strip()
    state = context.user_data.get("state")
    temp_data = context.user_data.get("temp_data", "")

    # ── حالة: إضافة مادة ──
    if state == "waiting_for_subject":
        sub_name = text
        try:
            check = await sb_execute(
                lambda: supabase.table("subjects")
                .select("*")
                .eq("user_id", user_id)
                .eq("subject_name", sub_name)
                .execute()
            )
        except Exception:
            check = type("obj", (object,), {"data": []})()

        if check.data:
            await update.message.reply_text(f"⚠️ المادة '{sub_name}' موجودة مسبقاً!")
        else:
            try:
                await sb_execute(
                    lambda: supabase.table("subjects").insert(
                        {"user_id": user_id, "subject_name": sub_name}
                    ).execute()
                )
            except Exception:
                pass
            clear_user_cache(user_id)
            await update.message.reply_text(
                f"✅ تمت إضافة المادة '{sub_name}' بنجاح!"
            )
        context.user_data.pop("state", None)
        context.user_data.pop("temp_data", None)
        await show_subjects_menu(update, context)
        return

    # ── حالة: إضافة فرع ──
    if state == "waiting_for_section":
        subject = temp_data
        sec_name = text
        try:
            check = await sb_execute(
                lambda: supabase.table("sections")
                .select("*")
                .eq("user_id", user_id)
                .eq("subject_name", subject)
                .eq("section_name", sec_name)
                .execute()
            )
        except Exception:
            check = type("obj", (object,), {"data": []})()

        if check.data:
            await update.message.reply_text(
                f"⚠️ الفرع '{sec_name}' موجود مسبقاً في هذه المادة!"
            )
        else:
            try:
                await sb_execute(
                    lambda: supabase.table("sections").insert({
                        "user_id": user_id,
                        "subject_name": subject,
                        "section_name": sec_name,
                    }).execute()
                )
            except Exception:
                pass
            clear_user_cache(user_id)
            await update.message.reply_text(
                f"✅ تم إضافة الفرع '{sec_name}' لمادة [{subject}] بنجاح!"
            )
        context.user_data.pop("state", None)
        context.user_data.pop("temp_data", None)
        await show_sections_menu_direct(update, context, user_id, subject)
        return

    # ── حالة: عنوان الدرس ──
    if state and state.startswith("waiting_for_lesson_title_"):
        parts = temp_data.split("|")
        subject, section = parts[0], parts[1]
        title = text
        context.user_data["state"] = f"waiting_for_lesson_content_{subject}|{section}|{title}"
        context.user_data["temp_data"] = title
        await update.message.reply_text(
            f"✍️ أرسل الآن محتوى الدرس '{title}' (أو أرسل صورة/فيديو/ملف مباشرة):"
        )
        return

    # ── حالة: محتوى الدرس نصي ──
    if state and state.startswith("waiting_for_lesson_content_"):
        parts = state.replace("waiting_for_lesson_content_", "").split("|", 2)
        subject, section, title = parts[0], parts[1], parts[2]
        try:
            await sb_execute(
                lambda: supabase.table("lessons").insert({
                    "user_id": user_id,
                    "subject_name": subject,
                    "section_name": section,
                    "title": title,
                    "content_type": "text",
                    "file_or_text": text,
                }).execute()
            )
        except Exception:
            pass
        context.user_data.pop("state", None)
        context.user_data.pop("temp_data", None)
        clear_user_cache(user_id)
        await update.message.reply_text(
            f"✅ تم حفظ الدرس '{title}' في [{subject} ➔ {section}] بنجاح!"
        )
        await show_lessons_menu_direct(update, context, user_id, subject, section)
        return

    # ── حالة: تعديل اسم الدرس ──
    if state and state.startswith("waiting_for_edit_lesson_"):
        lesson_id = int(state.replace("waiting_for_edit_lesson_", ""))
        new_title = text
        try:
            await sb_execute(
                lambda: supabase.table("lessons")
                .update({"title": new_title})
                .eq("id", lesson_id)
                .eq("user_id", user_id)
                .execute()
            )
            res_lesson = await sb_execute(
                lambda: supabase.table("lessons")
                .select("subject_name, section_name")
                .eq("id", lesson_id)
                .execute()
            )
        except Exception:
            res_lesson = type("obj", (object,), {"data": []})()

        context.user_data.pop("state", None)
        context.user_data.pop("temp_data", None)
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

    # ── حالة: إضافة ملاحظة للمادة ──
    if state and state.startswith("waiting_for_sub_note_"):
        subject = state.replace("waiting_for_sub_note_", "")
        try:
            await sb_execute(
                lambda: supabase.table("subject_notes").insert({
                    "user_id": user_id,
                    "subject_name": subject,
                    "note_text": text,
                }).execute()
            )
        except Exception:
            pass
        context.user_data.pop("state", None)
        context.user_data.pop("temp_data", None)
        clear_user_cache(user_id)
        await update.message.reply_text(
            f"✅ تم حفظ الملاحظة لمادة [{subject}] بنجاح!"
        )
        await show_subject_notes_menu(update, context, user_id, subject)
        return

    # ── حالة: إضافة مهمة ──
    if state == "waiting_for_task":
        try:
            await sb_execute(
                lambda: supabase.table("tasks").insert(
                    {"user_id": user_id, "task_text": text, "is_completed": False}
                ).execute()
            )
        except Exception:
            pass
        context.user_data.pop("state", None)
        context.user_data.pop("temp_data", None)
        await update.message.reply_text("✅ تم إضافة المهمة بنجاح!")
        await show_tasks_menu(update, context)
        return

    # ── كلمات مفتاحية سريعة ──
    list_keywords = ["قائمة", "اعرض", "اضهر", "أضهر", "دروسي", "الدروس", "موادي"]
    if any(keyword in text for keyword in list_keywords):
        await show_subjects_menu(update, context)
        return

    # ── fallback: الذكاء الاصطناعي ──
    await handle_ai_chat(update, context)


# ───────────────────────────────────────────────
# معالج الوسائط (صور، ملفات، فيديو)
# ───────────────────────────────────────────────
async def handle_photo_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id

    if check_spam(user_id):
        return

    state = context.user_data.get("state")
    temp_data = context.user_data.get("temp_data", "")

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

    # ── إضافة درس بوسائط (من حالة العنوان أو المحتوى) ──
    if state and state.startswith("waiting_for_lesson_title_"):
        parts = temp_data.split("|")
        subject, section = parts[0], parts[1]
        title = update.message.caption if update.message.caption else "ملف/فيديو/صورة درس"
        try:
            await sb_execute(
                lambda: supabase.table("lessons").insert({
                    "user_id": user_id,
                    "subject_name": subject,
                    "section_name": section,
                    "title": title,
                    "content_type": c_type,
                    "file_or_text": file_id,
                }).execute()
            )
        except Exception:
            pass
        context.user_data.pop("state", None)
        context.user_data.pop("temp_data", None)
        clear_user_cache(user_id)
        await update.message.reply_text(
            f"✅ تم حفظ الوسائط للدرس '{title}' في [{subject} ➔ {section}] بنجاح!"
        )
        await show_lessons_menu_direct(update, context, user_id, subject, section)
        return

    if state and state.startswith("waiting_for_lesson_content_"):
        parts = state.replace("waiting_for_lesson_content_", "").split("|", 2)
        subject, section, title = parts[0], parts[1], parts[2]
        try:
            await sb_execute(
                lambda: supabase.table("lessons").insert({
                    "user_id": user_id,
                    "subject_name": subject,
                    "section_name": section,
                    "title": title,
                    "content_type": c_type,
                    "file_or_text": file_id,
                }).execute()
            )
        except Exception:
            pass
        context.user_data.pop("state", None)
        context.user_data.pop("temp_data", None)
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


# ───────────────────────────────────────────────
# الذكاء الاصطناعي (Groq)
# ───────────────────────────────────────────────
async def handle_ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not groq_client:
        await update.message.reply_text(
            "⛔ خدمة الذكاء الاصطناعي غير متاحة حالياً."
        )
        return

    user_message = update.message.text
    try:
        def request_ai_response():
            return groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "أنت معلم خبير ومحترف في كافة العلوم والمواد الدراسية. تجيب"
                            " بطريقة مبسطة، ودقيقة، وداعمة للطلاب باللغة العربية."
                        ),
                    },
                    {"role": "user", "content": user_message},
                ],
                temperature=0.7,
                max_tokens=1024,
            )

        # مكتبة Groq المتزامنة تُشغّل في thread حتى لا يتوقف البوت أثناء انتظار الرد.
        chat_completion = await asyncio.to_thread(request_ai_response)
        if not chat_completion.choices:
            raise RuntimeError("Groq returned no choices")

        ai_reply = chat_completion.choices[0].message.content
        if not ai_reply:
            raise RuntimeError("Groq returned an empty response")

        await update.message.reply_text(ai_reply)
    except Exception as e:
        logger.exception("AI request failed: %s", e)
        error_code = getattr(e, "status_code", None)
        if error_code == 401:
            user_error = "مفتاح GROQ_API_KEY غير صحيح أو منتهي."
        elif error_code == 429:
            user_error = "تم تجاوز حد Groq أو الرصيد المتاح مؤقتاً."
        elif error_code == 404:
            user_error = f"نموذج الذكاء الاصطناعي غير متاح: {GROQ_MODEL}"
        else:
            user_error = "تعذر الاتصال بخدمة الذكاء الاصطناعي حالياً. تحقق من إعدادات Groq وسجل التشغيل."
        await update.message.reply_text(f"⚠️ {user_error}")


# ───────────────────────────────────────────────
# معالج الأزرار (Callbacks)
# ───────────────────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not user:
        return
    user_id = user.id

    if check_spam(user_id):
        await query.answer("⚠️ يرجى عدم الضغط بسرعة كبيرة!", show_alert=True)
        return

    await query.answer()
    data = query.data

    # ── القائمة الرئيسية ──
    if data == "show_subjects":
        await show_subjects_menu(update, context)
        return
    elif data == "main_menu":
        context.user_data.pop("state", None)
        context.user_data.pop("temp_data", None)
        await start(update, context)
        return
    elif data == "add_subject":
        context.user_data["state"] = "waiting_for_subject"
        context.user_data["temp_data"] = ""
        await query.message.edit_text(
            "✍️ أرسل الآن اسم المادة الجديدة التي تريد إضافتها:"
        )
        return

    # ── خيارات المادة ──
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
        context.user_data["state"] = f"waiting_for_sub_note_{subject}"
        context.user_data["temp_data"] = subject
        await query.message.edit_text(
            f"✍️ أرسل الآن نص الملاحظة التي تريد إضافتها لمادة [{subject}]:"
        )
        return

    if data.startswith("view_sub_note|"):
        n_id = int(data.split("|")[1])
        try:
            res = await sb_execute(
                lambda: supabase.table("subject_notes")
                .select("note_text, subject_name")
                .eq("id", n_id)
                .eq("user_id", user_id)
                .execute()
            )
        except Exception:
            res = type("obj", (object,), {"data": []})()
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
        try:
            await sb_execute(
                lambda: supabase.table("subject_notes")
                .delete()
                .eq("id", n_id)
                .eq("user_id", user_id)
                .execute()
            )
        except Exception:
            pass
        clear_user_cache(user_id)
        await show_subject_notes_menu(update, context, user_id, subject)
        return

    # ── المهام ──
    if data == "show_tasks":
        await show_tasks_menu(update, context)
        return
    elif data == "add_task":
        context.user_data["state"] = "waiting_for_task"
        context.user_data["temp_data"] = ""
        await query.message.edit_text("✍️ أرسل الآن اسم أو نص المهمة الجديدة:")
        return
    elif data.startswith("toggle_task|"):
        t_id = int(data.split("|")[1])
        try:
            res = await sb_execute(
                lambda: supabase.table("tasks")
                .select("is_completed")
                .eq("id", t_id)
                .eq("user_id", user_id)
                .execute()
            )
        except Exception:
            res = type("obj", (object,), {"data": []})()
        if res.data:
            current_status = res.data[0].get("is_completed")
            try:
                await sb_execute(
                    lambda: supabase.table("tasks")
                    .update({"is_completed": not current_status})
                    .eq("id", t_id)
                    .eq("user_id", user_id)
                    .execute()
                )
            except Exception:
                pass
            await show_tasks_menu(update, context)
        return
    elif data.startswith("del_task|"):
        t_id = int(data.split("|")[1])
        try:
            await sb_execute(
                lambda: supabase.table("tasks")
                .delete()
                .eq("id", t_id)
                .eq("user_id", user_id)
                .execute()
            )
        except Exception:
            pass
        await show_tasks_menu(update, context)
        return

    # ── حذف مادة ──
    if data.startswith("delsub|"):
        sub_to_del = data.split("|", 1)[1]
        try:
            await sb_execute(
                lambda: supabase.table("subjects")
                .delete()
                .eq("user_id", user_id)
                .eq("subject_name", sub_to_del)
                .execute()
            )
            await sb_execute(
                lambda: supabase.table("sections")
                .delete()
                .eq("user_id", user_id)
                .eq("subject_name", sub_to_del)
                .execute()
            )
            await sb_execute(
                lambda: supabase.table("lessons")
                .delete()
                .eq("user_id", user_id)
                .eq("subject_name", sub_to_del)
                .execute()
            )
            await sb_execute(
                lambda: supabase.table("subject_notes")
                .delete()
                .eq("user_id", user_id)
                .eq("subject_name", sub_to_del)
                .execute()
            )
        except Exception:
            pass
        clear_user_cache(user_id)
        await show_subjects_menu(update, context)
        return

    # ── حذف فرع ──
    if data.startswith("delsec|"):
        parts = data.split("|")
        subject = parts[1]
        sec_to_del = parts[2]
        try:
            await sb_execute(
                lambda: supabase.table("sections")
                .delete()
                .eq("user_id", user_id)
                .eq("subject_name", subject)
                .eq("section_name", sec_to_del)
                .execute()
            )
            await sb_execute(
                lambda: supabase.table("lessons")
                .delete()
                .eq("user_id", user_id)
                .eq("subject_name", subject)
                .eq("section_name", sec_to_del)
                .execute()
            )
        except Exception:
            pass
        clear_user_cache(user_id)
        await show_sections_menu_direct(update, context, user_id, subject)
        return

    # ── فتح فرع ──
    if data.startswith("sec|"):
        parts = data.split("|")
        subject = parts[1]
        section = parts[2]
        await show_lessons_menu_direct(update, context, user_id, subject, section)
        return

    # ── إضافة فرع ──
    if data.startswith("addsec|"):
        subject = data.split("|", 1)[1]
        context.user_data["state"] = "waiting_for_section"
        context.user_data["temp_data"] = subject
        await query.message.edit_text(
            f"✍️ أرسل الآن اسم الفرع الجديد الذي تريد إضافته لمادة [{subject}]:"
        )
        return

    # ── إضافة درس ──
    if data.startswith("addles|"):
        parts = data.split("|")
        subject = parts[1]
        section = parts[2]
        context.user_data["state"] = f"waiting_for_lesson_title_{subject}|{section}"
        context.user_data["temp_data"] = f"{subject}|{section}"
        await query.message.edit_text(
            f"✍️ أرسل الآن **عنوان الدرس** الجديد في [{subject} ➔ {section}]:",
            parse_mode="Markdown",
        )
        return

    # ── فتح درس ──
    if data.startswith("op|"):
        lesson_id = int(data.split("|")[1])
        try:
            res = await sb_execute(
                lambda: supabase.table("lessons")
                .select("title, content_type, file_or_text, subject_name, section_name")
                .eq("id", lesson_id)
                .eq("user_id", user_id)
                .execute()
            )
        except Exception:
            res = type("obj", (object,), {"data": []})()
        if res.data:
            lesson = res.data[0]
            title = lesson.get("title")
            c_type = lesson.get("content_type")
            content = lesson.get("file_or_text")
            subject = lesson.get("subject_name")
            section = lesson.get("section_name")

            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✏️ تعديل اسم الدرس", callback_data=f"edit_lesson|{lesson_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 رجوع للدروس", callback_data=f"sec|{subject}|{section}"
                    )
                ],
            ])

            if c_type == "text":
                await query.message.edit_text(
                    f"📖 **الدرس: {title}**\n\n{content}",
                    reply_markup=kb,
                    parse_mode="Markdown",
                )
            elif c_type == "photo":
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=content,
                    caption=f"📖 **الدرس: {title}**",
                    reply_markup=kb,
                    parse_mode="Markdown",
                )
            elif c_type == "video":
                await query.message.delete()
                await context.bot.send_video(
                    chat_id=user_id,
                    video=content,
                    caption=f"📖 **الدرس: {title}**",
                    reply_markup=kb,
                    parse_mode="Markdown",
                )
            elif c_type == "document":
                await query.message.delete()
                await context.bot.send_document(
                    chat_id=user_id,
                    document=content,
                    caption=f"📖 **الدرس: {title}**",
                    reply_markup=kb,
                    parse_mode="Markdown",
                )
        return

    # ── حذف درس ──
    if data.startswith("dl|"):
        lesson_id = int(data.split("|")[1])
        try:
            res = await sb_execute(
                lambda: supabase.table("lessons")
                .select("subject_name, section_name")
                .eq("id", lesson_id)
                .eq("user_id", user_id)
                .execute()
            )
        except Exception:
            res = type("obj", (object,), {"data": []})()
        sub = sec = None
        if res.data:
            sub = res.data[0].get("subject_name")
            sec = res.data[0].get("section_name")
        try:
            await sb_execute(
                lambda: supabase.table("lessons")
                .delete()
                .eq("id", lesson_id)
                .eq("user_id", user_id)
                .execute()
            )
        except Exception:
            pass
        clear_user_cache(user_id)
        if sub and sec:
            await show_lessons_menu_direct(update, context, user_id, sub, sec)
        else:
            await show_subjects_menu(update, context)
        return

    # ── تعديل درس ──
    if data.startswith("edit_lesson|"):
        lesson_id = int(data.split("|")[1])
        context.user_data["state"] = f"waiting_for_edit_lesson_{lesson_id}"
        context.user_data["temp_data"] = str(lesson_id)
        await query.message.edit_text(
            "✍️ أرسل الآن الاسم أو العنوان الجديد للدرس:"
        )
        return


# ───────────────────────────────────────────────
# الدالة الرئيسية
# ───────────────────────────────────────────────
def main():
    # تشغيل Flask في thread منفصل (للـ Health Check)
    keep_alive()

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(HTTPXRequest(connect_timeout=30, read_timeout=30))
        .post_init(post_init)
        .build()
    )

    # الأوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("lessons", lessons_command))
    application.add_handler(CommandHandler("tasks", tasks_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("users", list_all_users))
    application.add_handler(CommandHandler("broadcast", broadcast_message))

    # الأزرار التفاعلية
    application.add_handler(CallbackQueryHandler(button_callback))

    # النصوص (handle_text أولاً → يفحص الحالات ثم يسقط للذكاء الاصطناعي)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    # الوسائط
    application.add_handler(
        MessageHandler(
            filters.PHOTO | filters.Document.ALL | filters.VIDEO,
            handle_photo_document,
        )
    )

    # معالج الأخطاء
    application.add_error_handler(error_handler)

    logger.info("Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
