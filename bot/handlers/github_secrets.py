"""GitHub repository secrets management handlers."""

import logging

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub secrets handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_secrets")
    def cmd_secrets(call):
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
            secrets = list(repo.get_secrets())
            markup = types.InlineKeyboardMarkup(row_width=1)
            if secrets:
                secret_names = []
                for idx, secret in enumerate(secrets[:20]):
                    secret_names.append(secret.name)
                    markup.add(types.InlineKeyboardButton(
                        f"🔒 {secret.name}",
                        callback_data=f"sec_dl_{idx}"
                    ))
                user_state.set_field(chat_id, 'secret_list', secret_names)
                text = f"🔐 أسرار {repo_name} ({len(secrets)}):\n(لا يمكن عرض القيم)"
            else:
                text = f"🔐 لا توجد أسرار في {repo_name}"

            markup.add(types.InlineKeyboardButton(
                "➕ إضافة سر جديد", callback_data="sec_add"
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

    @bot.callback_query_handler(func=lambda c: c.data.startswith("sec_dl_"))
    def sec_delete_confirm(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        secret_list = user_state.get_field(chat_id, 'secret_list', [])
        try:
            idx = int(call.data.replace("sec_dl_", ""))
            secret_name = secret_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد السر.",
                chat_id, call.message.message_id
            )
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(
                "✅ نعم، احذف",
                callback_data=f"sec_cf_{idx}"
            ),
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cmd_secrets"
            )
        )
        bot.edit_message_text(
            f"⚠️ هل تريد حذف السر: {secret_name}؟",
            chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("sec_cf_"))
    def sec_delete_execute(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        secret_list = user_state.get_field(chat_id, 'secret_list', [])
        try:
            idx = int(call.data.replace("sec_cf_", ""))
            secret_name = secret_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد السر.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            repo.delete_secret(secret_name)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🔐 الأسرار", callback_data="cmd_secrets"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                f"✅ تم حذف السر: {secret_name}",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "sec_add")
    def sec_add(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cmd_secrets"
            )
        )
        msg = bot.send_message(
            chat_id,
            "✏️ أرسل اسم السر الجديد:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, sec_add_name)
        try_delete_message(bot, chat_id, call.message.message_id)

    def sec_add_name(message):
        chat_id = message.chat.id
        name = message.text.strip().upper().replace(" ", "_")
        user_state.set_field(chat_id, 'new_secret_name', name)
        msg = bot.send_message(
            chat_id,
            f"🔑 أرسل قيمة السر ({name}):"
        )
        bot.register_next_step_handler(msg, sec_add_value)

    def sec_add_value(message):
        chat_id = message.chat.id
        value = message.text.strip()
        name = user_state.get_field(chat_id, 'new_secret_name', '')
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not config or not repo_name or not name:
            bot.reply_to(message, "❌ خطأ في البيانات.")
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            # Use PyGithub's create_secret method
            repo.create_secret(name, value)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🔐 الأسرار", callback_data="cmd_secrets"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.reply_to(
                message,
                f"✅ تم إنشاء/تحديث السر: {name}",
                reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")
