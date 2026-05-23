"""GitHub Gists management handlers."""

import logging

from telebot import types
from github import Github, GithubException, InputFileContent

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub gists handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_gists")
    def cmd_gists(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        if not config:
            bot.edit_message_text(
                "⚠️ يرجى ضبط الإعدادات أولاً.",
                chat_id, call.message.message_id
            )
            return
        try:
            g = Github(config['token'])
            user = g.get_user()
            gists = list(user.get_gists()[:15])
            markup = types.InlineKeyboardMarkup(row_width=1)
            if gists:
                gist_ids = []
                for idx, gist in enumerate(gists):
                    desc = gist.description[:30] if gist.description else "بدون وصف"
                    files_count = len(gist.files)
                    vis = "🌐" if gist.public else "🔒"
                    markup.add(types.InlineKeyboardButton(
                        f"{vis} {desc} ({files_count} ملف)",
                        callback_data=f"gist_d_{idx}"
                    ))
                    gist_ids.append(gist.id)
                user_state.set_field(chat_id, 'gist_list', gist_ids)
                text = f"📝 Gists الخاصة بك ({len(gists)}):"
            else:
                text = "📝 لا توجد Gists"

            markup.add(types.InlineKeyboardButton(
                "➕ إنشاء Gist جديد", callback_data="gist_create"
            ))
            markup.add(
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                text, chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("gist_d_"))
    def gist_delete_confirm(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        try:
            idx = int(call.data.replace("gist_d_", ""))
        except ValueError:
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(
                "🗑️ حذف",
                callback_data=f"gist_cf_{idx}"
            ),
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cmd_gists"
            )
        )
        bot.edit_message_text(
            "⚠️ هل تريد حذف هذا الـ Gist؟",
            chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("gist_cf_"))
    def gist_delete_execute(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        gist_list = user_state.get_field(chat_id, 'gist_list', [])
        try:
            idx = int(call.data.replace("gist_cf_", ""))
            gist_id = gist_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد الـ Gist.",
                chat_id, call.message.message_id
            )
            return
        try:
            g = Github(config['token'])
            gist = g.get_gist(gist_id)
            gist.delete()
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "📝 Gists", callback_data="cmd_gists"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                "✅ تم حذف الـ Gist!",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "gist_create")
    def gist_create(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cmd_gists"
            )
        )
        msg = bot.send_message(
            chat_id,
            "✏️ أرسل وصف الـ Gist (أو - للتخطي):",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, gist_create_desc)
        try_delete_message(bot, chat_id, call.message.message_id)

    def gist_create_desc(message):
        chat_id = message.chat.id
        desc = message.text.strip()
        if desc == "-":
            desc = ""
        user_state.set_field(chat_id, 'new_gist_desc', desc)
        msg = bot.send_message(
            chat_id,
            "📄 أرسل اسم الملف (مثل: code.py):"
        )
        bot.register_next_step_handler(msg, gist_create_filename)

    def gist_create_filename(message):
        chat_id = message.chat.id
        filename = message.text.strip()
        user_state.set_field(chat_id, 'new_gist_filename', filename)
        msg = bot.send_message(
            chat_id,
            "📝 أرسل محتوى الملف:"
        )
        bot.register_next_step_handler(msg, gist_create_content)

    def gist_create_content(message):
        chat_id = message.chat.id
        content = message.text
        user_state.set_field(chat_id, 'new_gist_content', content)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(
                "🌐 عام", callback_data="gist_pub"
            ),
            types.InlineKeyboardButton(
                "🔒 خاص", callback_data="gist_priv"
            )
        )
        bot.send_message(
            chat_id,
            "🔐 اختر مستوى الخصوصية:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data in ["gist_pub", "gist_priv"])
    def gist_create_finish(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        is_public = call.data == "gist_pub"
        desc = user_state.get_field(chat_id, 'new_gist_desc', '')
        filename = user_state.get_field(chat_id, 'new_gist_filename', 'file.txt')
        content = user_state.get_field(chat_id, 'new_gist_content', '')
        if not config or not content:
            bot.edit_message_text(
                "❌ خطأ في البيانات.",
                chat_id, call.message.message_id
            )
            return
        try:
            g = Github(config['token'])
            user = g.get_user()
            gist = user.create_gist(
                public=is_public,
                files={filename: InputFileContent(content)},
                description=desc
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🌐 فتح Gist", url=gist.html_url
                ),
                types.InlineKeyboardButton(
                    "📝 Gists", callback_data="cmd_gists"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                f"✅ تم إنشاء Gist بنجاح!\n{gist.html_url}",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )
