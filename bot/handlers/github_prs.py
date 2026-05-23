"""GitHub Pull Request management handlers."""

import logging

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, send_long_message, try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub PR handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_prs")
    def cmd_prs(call):
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
            prs = list(repo.get_pulls(state='open')[:15])
            markup = types.InlineKeyboardMarkup(row_width=1)
            if prs:
                pr_data = []
                for idx, pr in enumerate(prs):
                    markup.add(types.InlineKeyboardButton(
                        f"#{pr.number} {pr.title[:25]} ({pr.head.ref}->{pr.base.ref})",
                        callback_data=f"pr_v_{idx}"
                    ))
                    pr_data.append(pr.number)
                user_state.set_field(chat_id, 'pr_list', pr_data)
                text = f"🔀 طلبات الدمج المفتوحة في {repo_name} ({len(prs)}):"
            else:
                text = f"✅ لا توجد طلبات دمج مفتوحة في {repo_name}"

            markup.add(types.InlineKeyboardButton(
                "➕ إنشاء طلب دمج", callback_data="pr_create"
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

    @bot.callback_query_handler(func=lambda c: c.data.startswith("pr_v_"))
    def pr_view(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        pr_list = user_state.get_field(chat_id, 'pr_list', [])
        try:
            idx = int(call.data.replace("pr_v_", ""))
            pr_num = pr_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد طلب الدمج.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            pr = repo.get_pull(pr_num)
            text = (
                f"🔀 طلب دمج #{pr.number}\n\n"
                f"العنوان: {pr.title}\n"
                f"من: {pr.head.ref} -> {pr.base.ref}\n"
                f"الحالة: {pr.state}\n"
                f"الملفات المتغيرة: {pr.changed_files}\n"
                f"الإضافات: +{pr.additions} | الحذف: -{pr.deletions}\n"
                f"قابل للدمج: {'نعم' if pr.mergeable else 'لا'}\n"
                f"التاريخ: {pr.created_at.strftime('%Y-%m-%d')}"
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton(
                    "🔀 دمج", callback_data=f"pr_mg_{idx}"
                ),
                types.InlineKeyboardButton(
                    "🔀 PRs", callback_data="cmd_prs"
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

    @bot.callback_query_handler(func=lambda c: c.data.startswith("pr_mg_"))
    def pr_merge(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        pr_list = user_state.get_field(chat_id, 'pr_list', [])
        try:
            idx = int(call.data.replace("pr_mg_", ""))
            pr_num = pr_list[idx]
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد طلب الدمج.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            pr = repo.get_pull(pr_num)
            pr.merge()
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🔀 PRs", callback_data="cmd_prs"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                f"✅ تم دمج طلب الدمج #{pr_num} بنجاح!",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل الدمج: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "pr_create")
    def pr_create(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="cmd_prs")
        )
        msg = bot.send_message(
            chat_id,
            "✏️ أرسل عنوان طلب الدمج:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, pr_create_title)
        try_delete_message(bot, chat_id, call.message.message_id)

    def pr_create_title(message):
        chat_id = message.chat.id
        title = message.text.strip()
        user_state.set_field(chat_id, 'new_pr_title', title)
        msg = bot.send_message(
            chat_id,
            "🌿 أرسل اسم الفرع المصدر (head branch):"
        )
        bot.register_next_step_handler(msg, pr_create_head)

    def pr_create_head(message):
        chat_id = message.chat.id
        head = message.text.strip()
        user_state.set_field(chat_id, 'new_pr_head', head)
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            default_branch = repo.default_branch
        except Exception:
            default_branch = "main"
        msg = bot.send_message(
            chat_id,
            f"🎯 أرسل اسم الفرع الهدف (base branch)\n"
            f"أو أرسل - لاستخدام {default_branch}:"
        )
        user_state.set_field(chat_id, 'new_pr_default', default_branch)
        bot.register_next_step_handler(msg, pr_create_base)

    def pr_create_base(message):
        chat_id = message.chat.id
        base = message.text.strip()
        if base == "-":
            base = user_state.get_field(chat_id, 'new_pr_default', 'main')
        user_state.set_field(chat_id, 'new_pr_base', base)
        msg = bot.send_message(
            chat_id,
            "📝 أرسل وصف طلب الدمج (أو - للتخطي):"
        )
        bot.register_next_step_handler(msg, pr_create_body)

    def pr_create_body(message):
        chat_id = message.chat.id
        body = message.text.strip()
        if body == "-":
            body = ""
        title = user_state.get_field(chat_id, 'new_pr_title', '')
        head = user_state.get_field(chat_id, 'new_pr_head', '')
        base = user_state.get_field(chat_id, 'new_pr_base', 'main')
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not config or not repo_name or not title or not head:
            bot.reply_to(message, "❌ خطأ في البيانات.")
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            pr = repo.create_pull(
                title=title, body=body, head=head, base=base
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🔀 PRs", callback_data="cmd_prs"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.reply_to(
                message,
                f"✅ تم إنشاء طلب الدمج #{pr.number}\n"
                f"{head} -> {base}",
                reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")
