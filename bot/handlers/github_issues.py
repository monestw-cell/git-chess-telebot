"""GitHub issues management handlers."""

import logging

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, send_long_message, try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub issues handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_issues")
    def cmd_issues(call):
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
            issues = list(repo.get_issues(state='open')[:15])
            # Filter out pull requests (GitHub API returns PRs as issues)
            issues = [i for i in issues if not i.pull_request]

            markup = types.InlineKeyboardMarkup(row_width=1)
            if issues:
                issue_data = []
                for idx, issue in enumerate(issues):
                    labels_str = ""
                    if issue.labels:
                        labels_str = " " + " ".join(
                            f"[{l.name}]" for l in issue.labels[:2]
                        )
                    markup.add(types.InlineKeyboardButton(
                        f"#{issue.number} {issue.title[:30]}{labels_str}",
                        callback_data=f"iss_v_{idx}"
                    ))
                    issue_data.append(issue.number)
                user_state.set_field(chat_id, 'issue_list', issue_data)
                text = f"🐛 قضايا {repo_name} المفتوحة ({len(issues)}):"
            else:
                text = f"✅ لا توجد قضايا مفتوحة في {repo_name}"

            markup.add(types.InlineKeyboardButton(
                "➕ إنشاء قضية جديدة", callback_data="iss_create"
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
                text, chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("iss_v_"))
    def iss_view(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        issue_list = user_state.get_field(chat_id, 'issue_list', [])
        try:
            idx = int(call.data.replace("iss_v_", ""))
            issue_num = issue_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد القضية.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            issue = repo.get_issue(issue_num)
            labels_str = ", ".join(l.name for l in issue.labels) or "لا يوجد"
            assignees_str = ", ".join(
                a.login for a in issue.assignees
            ) or "لا يوجد"
            body = issue.body[:500] if issue.body else "لا يوجد وصف"
            created = issue.created_at.strftime("%Y-%m-%d")

            text = (
                f"🐛 قضية #{issue.number}\n\n"
                f"العنوان: {issue.title}\n"
                f"الحالة: {'مفتوحة' if issue.state == 'open' else 'مغلقة'}\n"
                f"التصنيفات: {labels_str}\n"
                f"المسؤولون: {assignees_str}\n"
                f"التاريخ: {created}\n\n"
                f"الوصف:\n{body}"
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton(
                    "🔒 إغلاق", callback_data=f"iss_cl_{idx}"
                ),
                types.InlineKeyboardButton(
                    "🐛 القضايا", callback_data="cmd_issues"
                )
            )
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

    @bot.callback_query_handler(func=lambda c: c.data.startswith("iss_cl_"))
    def iss_close(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        issue_list = user_state.get_field(chat_id, 'issue_list', [])
        try:
            idx = int(call.data.replace("iss_cl_", ""))
            issue_num = issue_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد القضية.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            issue = repo.get_issue(issue_num)
            issue.edit(state='closed')
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🐛 القضايا", callback_data="cmd_issues"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                f"✅ تم إغلاق القضية #{issue_num}",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "iss_create")
    def iss_create(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="cmd_issues")
        )
        msg = bot.send_message(
            chat_id,
            "✏️ أرسل عنوان القضية الجديدة:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, iss_create_title)
        try_delete_message(bot, chat_id, call.message.message_id)

    def iss_create_title(message):
        chat_id = message.chat.id
        title = message.text.strip()
        user_state.set_field(chat_id, 'new_issue_title', title)
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="cmd_issues")
        )
        msg = bot.send_message(
            chat_id,
            "📝 أرسل وصف القضية (أو أرسل - للتخطي):",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, iss_create_body)

    def iss_create_body(message):
        chat_id = message.chat.id
        body = message.text.strip()
        if body == "-":
            body = ""
        title = user_state.get_field(chat_id, 'new_issue_title', '')
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not config or not repo_name or not title:
            bot.reply_to(message, "❌ خطأ في البيانات.")
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            issue = repo.create_issue(title=title, body=body)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🐛 القضايا", callback_data="cmd_issues"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.reply_to(
                message,
                f"✅ تم إنشاء القضية #{issue.number}\n"
                f"العنوان: {title}",
                reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")
