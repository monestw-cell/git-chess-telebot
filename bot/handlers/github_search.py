"""GitHub search handlers - code and repository search."""

import logging

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, send_long_message, try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub search handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_search")
    def cmd_search(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                "🔍 بحث في الكود", callback_data="search_code"
            ),
            types.InlineKeyboardButton(
                "📦 بحث عن مستودعات", callback_data="search_repos"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔙 رجوع", callback_data="cmd_more_tools"
            ),
            types.InlineKeyboardButton(
                "🏠 الرئيسية", callback_data="main_menu"
            )
        )
        bot.edit_message_text(
            "🔍 خيارات البحث:",
            chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data == "search_code")
    def search_code(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cmd_search"
            )
        )
        msg = bot.send_message(
            chat_id,
            "🔍 أرسل نص البحث في الكود:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, do_search_code)
        try_delete_message(bot, chat_id, call.message.message_id)

    def do_search_code(message):
        chat_id = message.chat.id
        query = message.text.strip()
        config = get_user_config(chat_id)
        if not config:
            bot.reply_to(message, "⚠️ يرجى ضبط الإعدادات أولاً.")
            return
        try:
            g = Github(config['token'])
            # Search in user's repos
            search_query = f"{query} user:{config['username']}"
            results = list(g.search_code(search_query)[:10])
            if results:
                lines = []
                for r in results:
                    lines.append(
                        f"📄 {r.repository.name}/{r.path}\n"
                        f"   السطر: {r.name}"
                    )
                text = (
                    f"🔍 نتائج البحث عن: {query}\n\n"
                    + "\n\n".join(lines)
                )
            else:
                text = f"🔍 لا توجد نتائج لـ: {query}"
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🔍 بحث جديد", callback_data="search_code"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            send_long_message(bot, chat_id, text, reply_markup=markup)
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ خطأ: {clean_txt(e)}")

    @bot.callback_query_handler(func=lambda c: c.data == "search_repos")
    def search_repos(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cmd_search"
            )
        )
        msg = bot.send_message(
            chat_id,
            "🔍 أرسل اسم المستودع للبحث عنه:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, do_search_repos)
        try_delete_message(bot, chat_id, call.message.message_id)

    def do_search_repos(message):
        chat_id = message.chat.id
        query = message.text.strip()
        config = get_user_config(chat_id)
        if not config:
            bot.reply_to(message, "⚠️ يرجى ضبط الإعدادات أولاً.")
            return
        try:
            g = Github(config['token'])
            results = list(g.search_repositories(query)[:10])
            if results:
                lines = []
                for r in results:
                    vis = "🔒" if r.private else "🌐"
                    lines.append(
                        f"{vis} {r.full_name}\n"
                        f"   ⭐ {r.stargazers_count} | "
                        f"{r.language or 'N/A'}\n"
                        f"   {r.description[:50] if r.description else 'لا وصف'}"
                    )
                text = (
                    f"🔍 نتائج البحث عن: {query}\n\n"
                    + "\n\n".join(lines)
                )
            else:
                text = f"🔍 لا توجد نتائج لـ: {query}"
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🔍 بحث جديد", callback_data="search_repos"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            send_long_message(bot, chat_id, text, reply_markup=markup)
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ خطأ: {clean_txt(e)}")
