"""Main menu, help, status, and account info handlers."""

import logging
from datetime import datetime

import chess
import chess.engine
from telebot import types

from bot.config import STOCKFISH_PATH
from bot.state import user_state
from bot.database import get_user_config
from bot.utils import (
    clean_txt, send_long_message, log_error, get_error_logs,
    try_delete_message, get_github_client,
)

logger = logging.getLogger(__name__)

start_time = datetime.now()


def setup_commands(bot):
    """Set up bot commands list."""
    commands = [
        types.BotCommand("start", "القائمة الرئيسية"),
        types.BotCommand("help", "مساعدة"),
        types.BotCommand("check", "تحليل شطرنج"),
        types.BotCommand("setup", "ضبط GitHub"),
        types.BotCommand("logs", "سجل الأخطاء"),
        types.BotCommand("status", "حالة البوت"),
    ]
    try:
        bot.set_my_commands(commands)
    except Exception as e:
        logger.error(f"Failed to set commands: {e}")


def show_main_menu(bot, chat_id):
    """Display the main menu."""
    user_state.clear(chat_id)
    config = get_user_config(chat_id)
    status = f"متصل: {config['username']}" if config else "غير متصل بـ GitHub"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📁 مشاريعي", callback_data="my_projects"),
        types.InlineKeyboardButton("➕ مشروع جديد", callback_data="create_new_repo")
    )
    markup.add(
        types.InlineKeyboardButton("📊 إحصائيات", callback_data="account_info"),
        types.InlineKeyboardButton("♟️ تحليل شطرنج", callback_data="start_check")
    )
    markup.add(
        types.InlineKeyboardButton("⚙️ الإعدادات", callback_data="cmd_settings"),
        types.InlineKeyboardButton("❓ مساعدة", callback_data="help_menu")
    )
    markup.add(
        types.InlineKeyboardButton("📝 Gists", callback_data="cmd_gists"),
        types.InlineKeyboardButton("🔔 الإشعارات", callback_data="cmd_notifications")
    )
    markup.add(types.InlineKeyboardButton("📈 حالة البوت", callback_data="bot_status"))
    bot.send_message(
        chat_id,
        f"🤖 مدير المشاريع السحابي\n\n✅ {status}\n\nاختر من القائمة:",
        reply_markup=markup
    )


def show_help_menu(bot, chat_id, message_id):
    """Display help menu."""
    text = (
        "📖 دليل الاستخدام:\n\n"
        "🗂️ GitHub:\n"
        "  • إنشاء مستودع برفع ZIP أو فارغ\n"
        "  • تحديث المستودع في Commit واحد\n"
        "  • استبدال ملف واحد مباشرة\n"
        "  • حذف المستودعات\n"
        "  • تشغيل Workflows\n"
        "  • إعادة تسمية / تغيير الوصف / الخصوصية\n"
        "  • استعراض ملفات المستودع\n\n"
        "♟️ الشطرنج:\n"
        "  • اضغط (تحليل شطرنج) وأرسل PGN\n\n"
        "أوامر: /start /help /check /setup /logs /status"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception:
            bot.send_message(chat_id, text, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)


def show_bot_status(bot, chat_id, message_id):
    """Display bot status information."""
    uptime = datetime.now() - start_time
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    config = get_user_config(chat_id)
    gh_status = "✅ متصل" if config else "❌ غير متصل"
    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as e:
            e.analyse(chess.Board(), chess.engine.Limit(depth=1))
        sf_status = "✅ يعمل"
    except Exception:
        sf_status = "❌ متوقف"
    text = (
        f"📈 حالة البوت:\n\n"
        f"⏱️ وقت التشغيل: {h}h {m}m {s}s\n"
        f"🐙 GitHub: {gh_status}\n"
        f"♟️ Stockfish: {sf_status}\n"
        f"🔴 أخطاء مسجلة: {len(get_error_logs())}\n"
        f"👥 جلسات نشطة: {user_state.active_count()}\n"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception:
            bot.send_message(chat_id, text, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)


def show_account_info(bot, call):
    """Display GitHub account information."""
    chat_id = call.message.chat.id
    config = get_user_config(chat_id)
    if not config:
        bot.edit_message_text(
            "⚠️ يرجى ضبط الإعدادات أولاً.",
            chat_id, call.message.message_id
        )
        return
    bot.edit_message_text(
        "⏳ جاري جلب بيانات حسابك...",
        chat_id, call.message.message_id
    )
    try:
        from github import Github
        g = Github(config['token'])
        user = g.get_user()
        repos = list(user.get_repos())
        total_stars = sum(r.stargazers_count for r in repos)
        total_forks = sum(r.forks_count for r in repos)
        langs = {}
        for r in repos[:20]:
            try:
                for lang, bc in r.get_languages().items():
                    langs[lang] = langs.get(lang, 0) + bc
            except Exception:
                pass
        top_langs = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:3]
        langs_str = " | ".join(l[0] for l in top_langs) if top_langs else "غير محدد"
        try:
            rl = g.get_rate_limit()
            if hasattr(rl, 'core'):
                api_info = f"🔑 API: {rl.core.remaining}/{rl.core.limit} طلب متبقي"
            elif hasattr(rl, 'rate'):
                api_info = f"🔑 API: {rl.rate.remaining}/{rl.rate.limit} طلب متبقي"
            else:
                api_info = "🔑 API: متصل"
        except Exception:
            api_info = "🔑 API: متصل"
        text = (
            f"👤 معلومات GitHub:\n\n"
            f"الاسم: {user.name or user.login}\n"
            f"المستخدم: {user.login}\n"
            f"البريد: {user.email or 'مخفي'}\n"
            f"الموقع: {user.location or 'غير محدد'}\n\n"
            f"📦 المستودعات: {user.public_repos} عامة\n"
            f"⭐ إجمالي النجوم: {total_stars}\n"
            f"🍴 إجمالي الفورك: {total_forks}\n"
            f"👥 المتابعون: {user.followers} | يتابع: {user.following}\n\n"
            f"💻 أبرز اللغات: {langs_str}\n\n"
            f"{api_info}"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        log_error(chat_id, e)
        bot.edit_message_text(
            f"❌ خطأ: {clean_txt(e)}", chat_id, call.message.message_id
        )


def register(bot):
    """Register menu handlers with the bot."""

    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        user_state.clear(message.chat.id)
        show_main_menu(bot, message.chat.id)

    @bot.callback_query_handler(func=lambda c: c.data == "main_menu")
    def back_to_main(call):
        bot.answer_callback_query(call.id)
        user_state.clear(call.message.chat.id)
        try_delete_message(bot, call.message.chat.id, call.message.message_id)
        show_main_menu(bot, call.message.chat.id)

    @bot.message_handler(commands=['help'])
    def cmd_help(message):
        show_help_menu(bot, message.chat.id, None)

    @bot.callback_query_handler(func=lambda c: c.data == "help_menu")
    def callback_help(call):
        bot.answer_callback_query(call.id)
        show_help_menu(bot, call.message.chat.id, call.message.message_id)

    @bot.message_handler(commands=['status'])
    def cmd_status(message):
        show_bot_status(bot, message.chat.id, None)

    @bot.callback_query_handler(func=lambda c: c.data == "bot_status")
    def callback_status(call):
        bot.answer_callback_query(call.id)
        show_bot_status(bot, call.message.chat.id, call.message.message_id)

    @bot.callback_query_handler(func=lambda c: c.data == "account_info")
    def callback_account_info(call):
        bot.answer_callback_query(call.id)
        show_account_info(bot, call)

    @bot.message_handler(commands=['logs'])
    def show_logs(message):
        logs = get_error_logs()
        if not logs:
            bot.reply_to(message, "✅ لا توجد أخطاء مسجلة.")
            return
        send_long_message(
            bot, message.chat.id,
            "🔴 آخر الأخطاء:\n\n" + "\n".join(f"• {l}" for l in reversed(logs))
        )
