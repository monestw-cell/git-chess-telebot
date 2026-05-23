"""User settings handler - language and chess depth configuration."""

import logging
from telebot import types
from bot.state import user_state
from bot.database import get_user_config, update_user_setting, ensure_user_exists
from bot.i18n import get_text, get_lang

logger = logging.getLogger(__name__)


def register(bot):
    """Register settings handlers."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_settings")
    def settings_menu(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        lang = config.get('language', 'ar') if config else 'ar'
        depth = config.get('chess_depth', 14) if config else 14

        lang_display = "\u0627\u0644\u0639\u0631\u0628\u064a\u0629 \U0001f1f8\U0001f1e6" if lang == 'ar' else "English \U0001f1fa\U0001f1f8"

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                f"\U0001f310 \u0627\u0644\u0644\u063a\u0629: {lang_display}",
                callback_data="settings_lang"
            ),
            types.InlineKeyboardButton(
                f"\u265f\ufe0f \u0639\u0645\u0642 \u0627\u0644\u062a\u062d\u0644\u064a\u0644: {depth}",
                callback_data="settings_depth"
            ),
            types.InlineKeyboardButton(
                "\U0001f511 \u0625\u0639\u062f\u0627\u062f GitHub", callback_data="setup_now"
            ),
            types.InlineKeyboardButton(
                get_text(chat_id, 'home'), callback_data="main_menu"
            )
        )
        bot.edit_message_text(
            get_text(chat_id, 'settings_menu'),
            chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data == "settings_lang")
    def settings_language(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                "\u0627\u0644\u0639\u0631\u0628\u064a\u0629 \U0001f1f8\U0001f1e6",
                callback_data="set_lang_ar"
            ),
            types.InlineKeyboardButton(
                "English \U0001f1fa\U0001f1f8",
                callback_data="set_lang_en"
            ),
            types.InlineKeyboardButton(
                get_text(chat_id, 'back'), callback_data="cmd_settings"
            )
        )
        bot.edit_message_text(
            get_text(chat_id, 'select_language'),
            chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("set_lang_"))
    def set_language(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        lang = call.data.replace("set_lang_", "")
        if lang not in ('ar', 'en'):
            lang = 'ar'
        ensure_user_exists(chat_id)
        update_user_setting(chat_id, 'language', lang)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                get_text(chat_id, 'back'), callback_data="cmd_settings"
            ),
            types.InlineKeyboardButton(
                get_text(chat_id, 'home'), callback_data="main_menu"
            )
        )
        bot.edit_message_text(
            get_text(chat_id, 'language_changed'),
            chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data == "settings_depth")
    def settings_depth(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(
                "10 (\u0633\u0631\u064a\u0639)", callback_data="set_depth_10"
            ),
            types.InlineKeyboardButton(
                "14 (\u0645\u062a\u0648\u0633\u0637)", callback_data="set_depth_14"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "18 (\u0639\u0645\u064a\u0642)", callback_data="set_depth_18"
            ),
            types.InlineKeyboardButton(
                "22 (\u062e\u0628\u064a\u0631)", callback_data="set_depth_22"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                get_text(chat_id, 'back'), callback_data="cmd_settings"
            )
        )
        text = get_text(chat_id, 'select_depth') + "\n" + get_text(chat_id, 'depth_info')
        bot.edit_message_text(
            text, chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("set_depth_"))
    def set_depth(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        try:
            depth = int(call.data.replace("set_depth_", ""))
            if depth not in (10, 14, 18, 22):
                depth = 14
        except ValueError:
            depth = 14
        ensure_user_exists(chat_id)
        update_user_setting(chat_id, 'chess_depth', depth)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                get_text(chat_id, 'back'), callback_data="cmd_settings"
            ),
            types.InlineKeyboardButton(
                get_text(chat_id, 'home'), callback_data="main_menu"
            )
        )
        bot.edit_message_text(
            get_text(chat_id, 'depth_changed', depth=depth),
            chat_id, call.message.message_id, reply_markup=markup
        )
