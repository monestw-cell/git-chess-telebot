"""Setup flow handlers for GitHub token configuration."""

import logging

from telebot import types
from github import Github

from bot.state import user_state
from bot.database import save_user_config
from bot.utils import try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register setup handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "setup_now")
    def callback_setup(call):
        bot.answer_callback_query(call.id)
        start_setup(bot, call.message)

    @bot.message_handler(commands=['setup'])
    def cmd_setup(message):
        start_setup(bot, message)

    def start_setup(bot_inst, message):
        user_state.clear(message.chat.id)
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu")
        )
        bot_inst.register_next_step_handler(
            bot_inst.send_message(
                message.chat.id,
                "🔑 أرسل GitHub Token الخاص بك:\nسيتم التحقق منه تلقائياً",
                reply_markup=markup
            ),
            lambda m: get_token_step(bot_inst, m)
        )

    def get_token_step(bot_inst, message):
        token_val = message.text.strip()
        # Delete the message containing the token for security
        try_delete_message(bot_inst, message.chat.id, message.message_id)
        try:
            user = Github(token_val).get_user()
            markup = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu")
            )
            bot_inst.register_next_step_handler(
                bot_inst.send_message(
                    message.chat.id,
                    f"✅ توكن صالح! مرحباً {user.login}\nأرسل اسم المستخدم لتأكيده:",
                    reply_markup=markup
                ),
                lambda m: finish_setup(bot_inst, m, token_val)
            )
        except Exception:
            markup = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")
            )
            bot_inst.send_message(
                message.chat.id,
                "❌ التوكن غير صالح.\nحاول مجدداً /setup",
                reply_markup=markup
            )

    def finish_setup(bot_inst, message, token):
        chat_id = message.chat.id
        username = message.text.strip()
        save_user_config(chat_id, token, username)
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")
        )
        bot_inst.reply_to(message, "✅ تم حفظ الإعدادات بنجاح!", reply_markup=markup)
