"""GitHub release management handlers."""

import logging

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub release handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_releases")
    def cmd_releases(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not config or not repo_name:
            bot.edit_message_text(
                "⚠️ يرجى ضبط الإعدادات أولاً.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            releases = list(repo.get_releases()[:15])
            markup = types.InlineKeyboardMarkup(row_width=1)
            if releases:
                rel_ids = []
                for idx, rel in enumerate(releases):
                    pre = "🔶" if rel.prerelease else "🟢"
                    date_str = rel.created_at.strftime("%Y-%m-%d")
                    name = rel.title or rel.tag_name
                    markup.add(types.InlineKeyboardButton(
                        f"{pre} {name} ({rel.tag_name}) - {date_str}",
                        callback_data=f"rel_del_{idx}"
                    ))
                    rel_ids.append(rel.id)
                user_state.set_field(chat_id, 'release_list', rel_ids)
                text = f"📦 إصدارات {repo_name} ({len(releases)}):"
            else:
                text = f"📦 لا توجد إصدارات في {repo_name}"

            markup.add(types.InlineKeyboardButton(
                "➕ إنشاء إصدار جديد", callback_data="rel_create"
            ))
            markup.add(
                types.InlineKeyboardButton(
                    "🔙 رجوع", callback_data="cmd_more_tools"
                ),
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

    @bot.callback_query_handler(func=lambda c: c.data.startswith("rel_del_"))
    def rel_delete_confirm(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        try:
            idx = int(call.data.replace("rel_del_", ""))
        except ValueError:
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(
                "✅ نعم، احذف",
                callback_data=f"rel_cf_{idx}"
            ),
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cmd_releases"
            )
        )
        bot.edit_message_text(
            "⚠️ هل تريد حذف هذا الإصدار؟",
            chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("rel_cf_"))
    def rel_delete_execute(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        release_list = user_state.get_field(chat_id, 'release_list', [])
        try:
            idx = int(call.data.replace("rel_cf_", ""))
            rel_id = release_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد الإصدار.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            release = repo.get_release(rel_id)
            release.delete_release()
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "📦 الإصدارات", callback_data="cmd_releases"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                "✅ تم حذف الإصدار بنجاح!",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "rel_create")
    def rel_create(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cmd_releases"
            )
        )
        msg = bot.send_message(
            chat_id,
            "🏷️ أرسل اسم الوسم (tag) للإصدار (مثل: v1.0.0):",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, rel_create_tag)
        try_delete_message(bot, chat_id, call.message.message_id)

    def rel_create_tag(message):
        chat_id = message.chat.id
        tag = message.text.strip()
        user_state.set_field(chat_id, 'new_rel_tag', tag)
        msg = bot.send_message(
            chat_id,
            "✏️ أرسل عنوان الإصدار:"
        )
        bot.register_next_step_handler(msg, rel_create_title)

    def rel_create_title(message):
        chat_id = message.chat.id
        title = message.text.strip()
        user_state.set_field(chat_id, 'new_rel_title', title)
        msg = bot.send_message(
            chat_id,
            "📝 أرسل وصف الإصدار (أو - للتخطي):"
        )
        bot.register_next_step_handler(msg, rel_create_body)

    def rel_create_body(message):
        chat_id = message.chat.id
        body = message.text.strip()
        if body == "-":
            body = ""
        tag = user_state.get_field(chat_id, 'new_rel_tag', '')
        title = user_state.get_field(chat_id, 'new_rel_title', '')
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not config or not repo_name or not tag:
            bot.reply_to(message, "❌ خطأ في البيانات.")
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            release = repo.create_git_release(
                tag=tag, name=title, message=body
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "📦 الإصدارات", callback_data="cmd_releases"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.reply_to(
                message,
                f"✅ تم إنشاء الإصدار: {title}\n"
                f"الوسم: {tag}",
                reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")
