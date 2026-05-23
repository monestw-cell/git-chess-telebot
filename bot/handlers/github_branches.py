"""GitHub branch management handlers."""

import logging

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub branch handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_branches")
    def cmd_branches(call):
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
            branches = list(repo.get_branches())
            default_branch = repo.default_branch
            branch_names = [b.name for b in branches]
            user_state.set_field(chat_id, 'branch_list', branch_names)

            markup = types.InlineKeyboardMarkup(row_width=1)
            for idx, b in enumerate(branches[:20]):
                icon = "⭐" if b.name == default_branch else "🌿"
                markup.add(types.InlineKeyboardButton(
                    f"{icon} {b.name}",
                    callback_data=f"br_del_{idx}"
                ))
            markup.add(types.InlineKeyboardButton(
                "➕ إنشاء فرع جديد", callback_data="br_create"
            ))
            markup.add(
                types.InlineKeyboardButton(
                    "🔙 رجوع", callback_data="back_to_repo"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                f"🌿 فروع {repo_name} ({len(branches)}):\n"
                f"الفرع الافتراضي: ⭐ {default_branch}",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "br_create")
    def br_create(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="cmd_branches")
        )
        msg = bot.send_message(
            chat_id,
            "✏️ أرسل اسم الفرع الجديد:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, do_create_branch)
        try_delete_message(bot, chat_id, call.message.message_id)

    def do_create_branch(message):
        chat_id = message.chat.id
        branch_name = message.text.strip().replace(" ", "-")
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not config or not repo_name:
            bot.reply_to(message, "❌ خطأ في البيانات.")
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            source_branch = repo.get_branch(repo.default_branch)
            repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=source_branch.commit.sha
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🌿 الفروع", callback_data="cmd_branches"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.reply_to(
                message,
                f"✅ تم إنشاء الفرع: {branch_name}\n"
                f"من: {repo.default_branch}",
                reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("br_del_"))
    def br_delete(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        branch_list = user_state.get_field(chat_id, 'branch_list', [])
        try:
            idx = int(call.data.replace("br_del_", ""))
            branch_name = branch_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد الفرع.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            if branch_name == repo.default_branch:
                bot.edit_message_text(
                    "⚠️ لا يمكن حذف الفرع الافتراضي!",
                    chat_id, call.message.message_id
                )
                return
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton(
                    "✅ نعم، احذف",
                    callback_data=f"br_conf_{idx}"
                ),
                types.InlineKeyboardButton(
                    "🚫 إلغاء", callback_data="cmd_branches"
                )
            )
            bot.edit_message_text(
                f"⚠️ هل تريد حذف الفرع: {branch_name}؟",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("br_conf_"))
    def br_confirm_delete(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        branch_list = user_state.get_field(chat_id, 'branch_list', [])
        try:
            idx = int(call.data.replace("br_conf_", ""))
            branch_name = branch_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد الفرع.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            ref = repo.get_git_ref(f"heads/{branch_name}")
            ref.delete()
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🌿 الفروع", callback_data="cmd_branches"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                f"✅ تم حذف الفرع: {branch_name}",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل الحذف: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "back_to_repo")
    def back_to_repo(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        repo_map = user_state.get_field(chat_id, 'repo_map', {})
        repo_name = user_state.get_field(chat_id, 'current_repo')
        back_cb = "my_projects"
        for cb, name in repo_map.items():
            if name == repo_name:
                back_cb = cb
                break
        # Simulate pressing the repo selection button
        call.data = back_cb
        bot.process_new_callback_query([call])
