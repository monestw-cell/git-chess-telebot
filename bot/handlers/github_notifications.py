"""GitHub notifications management handlers."""

import logging

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub notifications handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_notifications")
    def cmd_notifications(call):
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
            notifications = list(g.get_user().get_notifications()[:20])
            markup = types.InlineKeyboardMarkup(row_width=1)
            if notifications:
                notif_ids = []
                for idx, notif in enumerate(notifications):
                    repo_name = notif.repository.name if notif.repository else ""
                    reason = notif.reason or ""
                    title = notif.subject.title[:25] if notif.subject else ""
                    markup.add(types.InlineKeyboardButton(
                        f"🔔 [{repo_name}] {title}",
                        callback_data=f"ntf_r_{idx}"
                    ))
                    notif_ids.append(notif.id)
                user_state.set_field(chat_id, 'notif_list', notif_ids)
                text = f"🔔 الإشعارات غير المقروءة ({len(notifications)}):"
            else:
                text = "✅ لا توجد إشعارات غير مقروءة"

            if notifications:
                markup.add(types.InlineKeyboardButton(
                    "✅ قراءة الكل", callback_data="notif_read_all"
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

    @bot.callback_query_handler(func=lambda c: c.data.startswith("ntf_r_"))
    def notif_mark_read(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        notif_list = user_state.get_field(chat_id, 'notif_list', [])
        try:
            idx = int(call.data.replace("ntf_r_", ""))
            notif_id = notif_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد الإشعار.",
                chat_id, call.message.message_id
            )
            return
        try:
            g = Github(config['token'])
            notif = g.get_user().get_notification(notif_id)
            notif.mark_as_read()
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🔔 الإشعارات", callback_data="cmd_notifications"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                "✅ تم تعليم الإشعار كمقروء!",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "notif_read_all")
    def notif_read_all(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        if not config:
            return
        try:
            g = Github(config['token'])
            g.get_user().mark_notifications_as_read()
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🔔 الإشعارات", callback_data="cmd_notifications"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                "✅ تم تعليم جميع الإشعارات كمقروءة!",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )
