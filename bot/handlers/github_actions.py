"""GitHub Actions workflow management handlers."""

import logging

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error

logger = logging.getLogger(__name__)


def _status_icon(status, conclusion):
    """Return status icon based on workflow run status."""
    if status == "in_progress":
        return "🔵"
    if status == "queued":
        return "🟡"
    if conclusion == "success":
        return "🟢"
    if conclusion == "failure":
        return "🔴"
    if conclusion == "cancelled":
        return "⚪"
    return "🟡"


def register(bot):
    """Register GitHub Actions handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_actions")
    def cmd_actions(call):
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
            runs = list(repo.get_workflow_runs()[:15])
            markup = types.InlineKeyboardMarkup(row_width=1)
            if runs:
                run_ids = []
                for idx, run in enumerate(runs):
                    icon = _status_icon(run.status, run.conclusion)
                    name = run.name[:20] if run.name else "workflow"
                    branch = run.head_branch[:10] if run.head_branch else ""
                    markup.add(types.InlineKeyboardButton(
                        f"{icon} {name} [{branch}]",
                        callback_data=f"act_v_{idx}"
                    ))
                    run_ids.append(run.id)
                user_state.set_field(chat_id, 'action_runs', run_ids)
                text = f"⚡ Actions في {repo_name} ({len(runs)}):"
            else:
                text = f"⚡ لا توجد عمليات تشغيل في {repo_name}"

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

    @bot.callback_query_handler(func=lambda c: c.data.startswith("act_v_"))
    def act_view(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        action_runs = user_state.get_field(chat_id, 'action_runs', [])
        try:
            idx = int(call.data.replace("act_v_", ""))
            run_id = action_runs[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد العملية.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            run = repo.get_workflow_run(run_id)
            icon = _status_icon(run.status, run.conclusion)
            text = (
                f"{icon} تفاصيل العملية\n\n"
                f"الاسم: {run.name}\n"
                f"الحالة: {run.status}\n"
                f"النتيجة: {run.conclusion or 'جاري'}\n"
                f"الفرع: {run.head_branch}\n"
                f"التاريخ: {run.created_at.strftime('%Y-%m-%d %H:%M')}"
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            if run.status == "in_progress" or run.status == "queued":
                markup.add(types.InlineKeyboardButton(
                    "🚫 إلغاء", callback_data=f"act_cn_{idx}"
                ))
            if run.conclusion == "failure":
                markup.add(types.InlineKeyboardButton(
                    "🔄 إعادة تشغيل", callback_data=f"act_rr_{idx}"
                ))
            markup.add(
                types.InlineKeyboardButton(
                    "⚡ Actions", callback_data="cmd_actions"
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

    @bot.callback_query_handler(func=lambda c: c.data.startswith("act_rr_"))
    def act_rerun(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        action_runs = user_state.get_field(chat_id, 'action_runs', [])
        try:
            idx = int(call.data.replace("act_rr_", ""))
            run_id = action_runs[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد العملية.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            run = repo.get_workflow_run(run_id)
            run.rerun()
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "⚡ Actions", callback_data="cmd_actions"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                "✅ تم إعادة تشغيل العملية!",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("act_cn_"))
    def act_cancel(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        action_runs = user_state.get_field(chat_id, 'action_runs', [])
        try:
            idx = int(call.data.replace("act_cn_", ""))
            run_id = action_runs[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد العملية.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            run = repo.get_workflow_run(run_id)
            run.cancel()
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "⚡ Actions", callback_data="cmd_actions"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                "✅ تم إلغاء العملية!",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )
