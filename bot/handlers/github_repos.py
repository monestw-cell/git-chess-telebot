"""GitHub repository listing, selection, and management handlers."""

import logging

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub repos handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "my_projects")
    def list_projects(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        if not config:
            bot.edit_message_text(
                "⚠️ يرجى ضبط الإعدادات أولاً.",
                chat_id, call.message.message_id
            )
            return
        bot.edit_message_text(
            "⏳ جاري جلب مشاريعك...",
            chat_id, call.message.message_id
        )
        try:
            repos = list(
                Github(config['token']).get_user().get_repos(sort="updated")
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
            repo_map = {}
            for idx, repo in enumerate(repos[:25]):
                vis = "🔒" if repo.private else "🌐"
                cb = f"sel_{idx}"
                repo_map[cb] = repo.name
                markup.add(types.InlineKeyboardButton(
                    f"{vis} {repo.name}  ⭐{repo.stargazers_count}",
                    callback_data=cb
                ))
            markup.add(types.InlineKeyboardButton(
                "🏠 الرئيسية", callback_data="main_menu"
            ))
            state = user_state.get(chat_id)
            state['repo_map'] = repo_map
            bot.edit_message_text(
                f"📁 مشاريعك ({len(repos)} مستودع) - مرتبة حسب آخر تحديث:",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("sel_"))
    def repo_selected(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        repo_map = user_state.get_field(chat_id, 'repo_map', {})
        repo_name = repo_map.get(call.data)
        if not repo_name:
            bot.edit_message_text(
                "❌ حدث خطأ، حاول مجدداً.",
                chat_id, call.message.message_id
            )
            return
        config = get_user_config(chat_id)
        state = user_state.get(chat_id)
        state['current_repo'] = repo_name
        state['repo_map'] = repo_map
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            vis = "🔒 خاص" if repo.private else "🌐 عام"
            info = (
                f"📦 {repo_name}\n"
                f"{repo.description or 'لا يوجد وصف'}\n\n"
                f"الحالة: {vis}\n"
                f"اللغة: {repo.language or 'غير محدد'}\n"
                f"⭐ {repo.stargazers_count} | 🍴 {repo.forks_count}\n"
                f"الفرع: {repo.default_branch}"
            )
        except Exception:
            info = f"📦 {repo_name}"
        # Find the index for this repo in repo_map for back navigation
        current_cb = call.data
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(
                "📤 رفع ZIP", callback_data="cmd_update_repo"
            ),
            types.InlineKeyboardButton(
                "🔄 استبدال ملف", callback_data="cmd_replace_file"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "⚡ Workflows", callback_data="cmd_workflows"
            ),
            types.InlineKeyboardButton(
                "📄 الملفات", callback_data="cmd_browse_files"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🌿 الفروع", callback_data="cmd_branches"
            ),
            types.InlineKeyboardButton(
                "🐛 القضايا", callback_data="cmd_issues"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔀 PR", callback_data="cmd_prs"
            ),
            types.InlineKeyboardButton(
                "⚡ Actions", callback_data="cmd_actions"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "📦 المزيد...", callback_data="cmd_more_tools"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "⚙️ إعدادات", callback_data="cmd_repo_settings"
            ),
            types.InlineKeyboardButton(
                "🗑️ حذف", callback_data="cmd_delete_repo"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔙 رجوع", callback_data="my_projects"
            ),
            types.InlineKeyboardButton(
                "🏠 الرئيسية", callback_data="main_menu"
            )
        )
        bot.edit_message_text(
            info, chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_more_tools")
    def cmd_more_tools(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not repo_name:
            bot.edit_message_text(
                "❌ حدث خطأ، حاول مجدداً.",
                chat_id, call.message.message_id
            )
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(
                "👥 المتعاونون", callback_data="cmd_collabs"
            ),
            types.InlineKeyboardButton(
                "📦 الإصدارات", callback_data="cmd_releases"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🍴 Fork", callback_data="cmd_fork"
            ),
            types.InlineKeyboardButton(
                "📋 Clone", callback_data="cmd_clone_info"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "📜 Commits", callback_data="cmd_commits"
            ),
            types.InlineKeyboardButton(
                "⭐ النجوم", callback_data="cmd_stars"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔐 الأسرار", callback_data="cmd_secrets"
            ),
            types.InlineKeyboardButton(
                "📂 المحرر", callback_data="cmd_editor"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔍 البحث", callback_data="cmd_search"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔙 رجوع", callback_data="back_to_repo"
            ),
            types.InlineKeyboardButton(
                "🏠 الرئيسية", callback_data="main_menu"
            )
        )
        bot.edit_message_text(
            f"📦 أدوات إضافية لـ {repo_name}:",
            chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_repo_settings")
    def repo_settings(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not repo_name:
            return
        # Find the callback data for the current repo
        repo_map = user_state.get_field(chat_id, 'repo_map', {})
        back_cb = "my_projects"
        for cb, name in repo_map.items():
            if name == repo_name:
                back_cb = cb
                break
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                "✏️ تغيير الاسم", callback_data="cmd_rename_repo"
            ),
            types.InlineKeyboardButton(
                "📝 تغيير الوصف", callback_data="cmd_change_desc"
            ),
            types.InlineKeyboardButton(
                "🔐 تبديل الخصوصية", callback_data="cmd_toggle_visibility"
            ),
            types.InlineKeyboardButton("🔙 رجوع", callback_data=back_cb),
            types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")
        )
        bot.edit_message_text(
            f"⚙️ إعدادات {repo_name}:",
            chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_rename_repo")
    def ask_rename(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        repo_name = user_state.get_field(chat_id, 'current_repo')
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu")
        )
        msg = bot.send_message(
            chat_id,
            f"✏️ أرسل الاسم الجديد للمستودع {repo_name}:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, do_rename_repo)
        try_delete_message(bot, chat_id, call.message.message_id)

    def do_rename_repo(message):
        chat_id = message.chat.id
        new_name = message.text.strip().replace(" ", "-")
        repo_name = user_state.get_field(chat_id, 'current_repo')
        config = get_user_config(chat_id)
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            repo.edit(name=new_name)
            user_state.set_field(chat_id, 'current_repo', new_name)
            markup = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.reply_to(
                message,
                f"✅ تم إعادة التسمية إلى: {new_name}",
                reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_change_desc")
    def ask_desc(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        repo_name = user_state.get_field(chat_id, 'current_repo')
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu")
        )
        msg = bot.send_message(
            chat_id,
            f"📝 أرسل الوصف الجديد للمستودع {repo_name}:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, do_change_desc)
        try_delete_message(bot, chat_id, call.message.message_id)

    def do_change_desc(message):
        chat_id = message.chat.id
        new_desc = message.text.strip()
        repo_name = user_state.get_field(chat_id, 'current_repo')
        config = get_user_config(chat_id)
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            repo.edit(description=new_desc)
            markup = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.reply_to(
                message, "✅ تم تحديث الوصف بنجاح!", reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_toggle_visibility")
    def toggle_visibility(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        repo_name = user_state.get_field(chat_id, 'current_repo')
        config = get_user_config(chat_id)
        bot.edit_message_text(
            "⏳ جاري تغيير الخصوصية...",
            chat_id, call.message.message_id
        )
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            new_private = not repo.private
            repo.edit(private=new_private)
            status_txt = "🔒 خاص" if new_private else "🌐 عام"
            markup = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                f"✅ تم تغيير {repo_name} إلى {status_txt}",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_delete_repo")
    def confirm_delete_repo(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not repo_name:
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(
                "✅ نعم، احذف", callback_data="execute_delete_repo"
            ),
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="my_projects"
            )
        )
        markup.add(types.InlineKeyboardButton(
            "🏠 الرئيسية", callback_data="main_menu"
        ))
        bot.edit_message_text(
            f"⚠️ تحذير!\nهل أنت متأكد من حذف {repo_name} نهائياً؟\n"
            "لا يمكن التراجع!",
            chat_id, call.message.message_id, reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda c: c.data == "execute_delete_repo")
    def execute_delete(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        repo_name = user_state.get_field(chat_id, 'current_repo')
        config = get_user_config(chat_id)
        try:
            Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            ).delete()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "🏠 الرئيسية", callback_data="main_menu"
            ))
            bot.edit_message_text(
                f"✅ تم حذف {repo_name} بنجاح.",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ فشل: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(
        func=lambda c: c.data in ["cmd_update_repo", "create_new_repo"]
    )
    def ask_for_zip(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        state = user_state.get(chat_id)
        if call.data == "create_new_repo":
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "📦 رفع ZIP (مشروع جاهز)",
                    callback_data="zip_mode_create"
                ),
                types.InlineKeyboardButton(
                    "📭 مستودع فارغ", callback_data="zip_mode_empty"
                ),
                types.InlineKeyboardButton(
                    "🚫 إلغاء", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                "➕ إنشاء مشروع جديد\nاختر طريقة الإنشاء:",
                chat_id, call.message.message_id, reply_markup=markup
            )
        else:
            repo_name = state.get('current_repo', 'المشروع')
            state['mode'] = 'update'
            markup = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    "🚫 إلغاء", callback_data="main_menu"
                )
            )
            msg = bot.edit_message_text(
                f"📤 تحديث {repo_name}\n\n"
                "أرسل ملف ZIP الآن:\n"
                "سيتم رفع جميع الملفات في Commit واحد",
                chat_id, call.message.message_id, reply_markup=markup
            )
            state['waiting_zip_msg'] = msg.message_id

    @bot.callback_query_handler(func=lambda c: c.data == "zip_mode_create")
    def zip_mode_create(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        state = user_state.get(chat_id)
        state['mode'] = 'create'
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu")
        )
        msg = bot.edit_message_text(
            "📦 إنشاء من ZIP\n\n"
            "أرسل ملف ZIP الآن:\nسيتم رفع جميع الملفات في Commit واحد",
            chat_id, call.message.message_id, reply_markup=markup
        )
        state['waiting_zip_msg'] = msg.message_id

    @bot.callback_query_handler(func=lambda c: c.data == "zip_mode_empty")
    def zip_mode_empty(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        state = user_state.get(chat_id)
        state['mode'] = 'create_empty'
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu")
        )
        msg = bot.send_message(
            chat_id, "📭 أرسل اسم المستودع الجديد:", reply_markup=markup
        )
        bot.register_next_step_handler(msg, create_empty_repo_step)
        try_delete_message(bot, chat_id, call.message.message_id)

    def create_empty_repo_step(message):
        chat_id = message.chat.id
        repo_name = message.text.strip().replace(" ", "-")
        config = get_user_config(chat_id)
        if not config:
            bot.send_message(chat_id, "⚠️ يرجى ضبط الإعدادات أولاً.")
            return
        try:
            repo = Github(config['token']).get_user().create_repo(
                repo_name, auto_init=True
            )
            state = user_state.get(chat_id)
            state['current_repo'] = repo_name
            state['mode'] = None
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "📤 رفع ZIP لهذا المستودع",
                    callback_data="cmd_update_repo"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.send_message(
                chat_id,
                f"✅ تم إنشاء المستودع!\n{repo.html_url}",
                reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.send_message(
                chat_id, f"❌ فشل الإنشاء: {clean_txt(e)}"
            )
