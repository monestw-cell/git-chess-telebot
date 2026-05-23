"""GitHub Workflows listing and dispatch handlers."""

import logging

import requests
from telebot import types
from github import Github

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error

logger = logging.getLogger(__name__)


def register(bot):
    """Register workflow handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_workflows")
    def list_workflows(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        repo_name = user_state.get_field(chat_id, 'current_repo')
        config = get_user_config(chat_id)
        if not config or not repo_name:
            bot.edit_message_text(
                "❌ خطأ في البيانات.",
                chat_id, call.message.message_id
            )
            return
        bot.edit_message_text(
            "⏳ جاري فحص الـ Workflows...",
            chat_id, call.message.message_id
        )
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            workflows = list(repo.get_workflows())
            markup = types.InlineKeyboardMarkup(row_width=1)
            wf_map = {}
            for wf in workflows:
                wf_map[str(wf.id)] = wf.name
                icon = "🟢" if wf.state == "active" else "🔴"
                markup.add(types.InlineKeyboardButton(
                    f"{icon} {wf.name} — ▶️ تشغيل",
                    callback_data=f"run_wf_{wf.id}"
                ))
            user_state.set_field(chat_id, 'wf_map', wf_map)
            # Find back callback for current repo
            repo_map = user_state.get_field(chat_id, 'repo_map', {})
            back_cb = "my_projects"
            for cb, name in repo_map.items():
                if name == repo_name:
                    back_cb = cb
                    break
            markup.add(types.InlineKeyboardButton(
                "🔙 رجوع", callback_data=back_cb
            ))
            markup.add(types.InlineKeyboardButton(
                "🏠 الرئيسية", callback_data="main_menu"
            ))
            text = (
                f"⚡ Workflows في {repo_name}:"
                if workflows
                else f"ℹ️ لا يوجد Workflows في {repo_name}."
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

    @bot.callback_query_handler(func=lambda c: c.data.startswith("run_wf_"))
    def run_workflow(call):
        bot.answer_callback_query(call.id, "⏳ جاري التشغيل...")
        chat_id = call.message.chat.id
        wf_id = call.data.replace("run_wf_", "")
        repo_name = user_state.get_field(chat_id, 'current_repo')
        config = get_user_config(chat_id)
        if not config or not repo_name:
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            branch = repo.default_branch
            url = (
                f"https://api.github.com/repos/{config['username']}/"
                f"{repo_name}/actions/workflows/{wf_id}/dispatches"
            )
            headers = {
                "Authorization": f"token {config['token']}",
                "Accept": "application/vnd.github.v3+json"
            }
            r = requests.post(
                url, headers=headers, json={"ref": branch}, timeout=30
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton(
                "⚡ عرض Workflows", callback_data="cmd_workflows"
            ))
            markup.add(types.InlineKeyboardButton(
                "🏠 الرئيسية", callback_data="main_menu"
            ))
            wf_name = user_state.get_field(
                chat_id, 'wf_map', {}
            ).get(wf_id, wf_id)
            if r.status_code == 204:
                bot.edit_message_text(
                    f"✅ تم تشغيل {wf_name} على فرع {branch}!",
                    chat_id, call.message.message_id, reply_markup=markup
                )
            else:
                err = r.json().get('message', r.text)
                bot.edit_message_text(
                    f"❌ فشل التشغيل: {clean_txt(err)}",
                    chat_id, call.message.message_id, reply_markup=markup
                )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}",
                chat_id, call.message.message_id
            )
