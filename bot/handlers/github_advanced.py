"""GitHub advanced features: fork, clone info, commits, stars."""

import logging

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, send_long_message, try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub advanced feature handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_fork")
    def cmd_fork(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cmd_more_tools"
            )
        )
        msg = bot.send_message(
            chat_id,
            "🍴 أرسل الاسم الكامل للمستودع (owner/repo):",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, do_fork)
        try_delete_message(bot, chat_id, call.message.message_id)

    def do_fork(message):
        chat_id = message.chat.id
        full_name = message.text.strip()
        config = get_user_config(chat_id)
        if not config:
            bot.reply_to(message, "⚠️ يرجى ضبط الإعدادات أولاً.")
            return
        if "/" not in full_name:
            bot.reply_to(message, "❌ صيغة خاطئة. استخدم: owner/repo")
            return
        try:
            g = Github(config['token'])
            source_repo = g.get_repo(full_name)
            fork = g.get_user().create_fork(source_repo)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🌐 فتح Fork", url=fork.html_url
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.reply_to(
                message,
                f"✅ تم إنشاء Fork بنجاح!\n{fork.html_url}",
                reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_clone_info")
    def cmd_clone_info(call):
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
            https_url = repo.clone_url
            ssh_url = repo.ssh_url
            text = (
                f"📋 روابط الاستنساخ لـ {repo_name}:\n\n"
                f"🔗 HTTPS:\n{https_url}\n\n"
                f"🔑 SSH:\n{ssh_url}"
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
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

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_commits")
    def cmd_commits(call):
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
            commits = list(repo.get_commits()[:10])
            lines = []
            for commit in commits:
                sha_short = commit.sha[:7]
                author = commit.commit.author.name or "unknown"
                msg = commit.commit.message.split('\n')[0][:40]
                date = commit.commit.author.date.strftime("%m-%d %H:%M")
                lines.append(
                    f"• {sha_short} | {author}\n  {msg}\n  {date}"
                )
            text = (
                f"📜 آخر 10 commits في {repo_name}:\n\n"
                + "\n\n".join(lines)
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
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

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_stars")
    def cmd_stars(call):
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
            g = Github(config['token'])
            repo = g.get_repo(f"{config['username']}/{repo_name}")
            user = g.get_user()
            is_starred = user.has_in_starred(repo)
            stars_count = repo.stargazers_count

            markup = types.InlineKeyboardMarkup(row_width=1)
            if is_starred:
                markup.add(types.InlineKeyboardButton(
                    "⭐ إلغاء النجمة", callback_data="star_toggle"
                ))
            else:
                markup.add(types.InlineKeyboardButton(
                    "⭐ أضف نجمة", callback_data="star_toggle"
                ))
            markup.add(
                types.InlineKeyboardButton(
                    "🔙 رجوع", callback_data="cmd_more_tools"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            status = "مفعلة ⭐" if is_starred else "غير مفعلة"
            bot.edit_message_text(
                f"⭐ نجوم {repo_name}\n\n"
                f"عدد النجوم: {stars_count}\n"
                f"حالتك: {status}",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "star_toggle")
    def star_toggle(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not config or not repo_name:
            return
        try:
            g = Github(config['token'])
            repo = g.get_repo(f"{config['username']}/{repo_name}")
            user = g.get_user()
            if user.has_in_starred(repo):
                user.remove_from_starred(repo)
                msg = "✅ تم إلغاء النجمة"
            else:
                user.add_to_starred(repo)
                msg = "✅ تم إضافة النجمة"
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "⭐ النجوم", callback_data="cmd_stars"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                msg, chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}",
                chat_id, call.message.message_id
            )
