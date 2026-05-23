"""GitHub collaborator management handlers."""

import logging

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub collaborator handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_collabs")
    def cmd_collabs(call):
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
            collabs = list(repo.get_collaborators())
            markup = types.InlineKeyboardMarkup(row_width=1)
            collab_names = []
            for idx, c_user in enumerate(collabs[:20]):
                perm = "admin"
                try:
                    perm_obj = repo.get_collaborator_permission(c_user.login)
                    perm = perm_obj
                except Exception:
                    pass
                collab_names.append(c_user.login)
                markup.add(types.InlineKeyboardButton(
                    f"👤 {c_user.login} ({perm})",
                    callback_data=f"col_rm_{idx}"
                ))
            user_state.set_field(chat_id, 'collab_list', collab_names)

            markup.add(types.InlineKeyboardButton(
                "➕ إضافة متعاون", callback_data="collab_add"
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
                f"👥 المتعاونون في {repo_name} ({len(collabs)}):",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("col_rm_"))
    def collab_remove_confirm(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        collab_list = user_state.get_field(chat_id, 'collab_list', [])
        try:
            idx = int(call.data.replace("col_rm_", ""))
            username = collab_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد المتعاون.",
                chat_id, call.message.message_id
            )
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(
                "✅ نعم، أزل",
                callback_data=f"col_cf_{idx}"
            ),
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cmd_collabs"
            )
        )
        bot.edit_message_text(
            f"⚠️ هل تريد إزالة المتعاون: {username}؟",
            chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("col_cf_"))
    def collab_remove_execute(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        collab_list = user_state.get_field(chat_id, 'collab_list', [])
        try:
            idx = int(call.data.replace("col_cf_", ""))
            username = collab_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد المتعاون.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            repo.remove_from_collaborators(username)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "👥 المتعاونون", callback_data="cmd_collabs"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                f"✅ تم إزالة المتعاون: {username}",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "collab_add")
    def collab_add(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cmd_collabs"
            )
        )
        msg = bot.send_message(
            chat_id,
            "✏️ أرسل اسم المستخدم للإضافة كمتعاون:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, do_add_collab)
        try_delete_message(bot, chat_id, call.message.message_id)

    def do_add_collab(message):
        chat_id = message.chat.id
        username = message.text.strip().replace("@", "")
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not config or not repo_name:
            bot.reply_to(message, "❌ خطأ في البيانات.")
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            repo.add_to_collaborators(username, permission='push')
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "👥 المتعاونون", callback_data="cmd_collabs"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.reply_to(
                message,
                f"✅ تم إرسال دعوة لـ {username} بصلاحية push",
                reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")
