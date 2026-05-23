"""GitHub file editor handlers - browse, view, and edit files."""

import logging
import base64

from telebot import types
from github import Github, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, send_long_message, try_delete_message

logger = logging.getLogger(__name__)


def register(bot):
    """Register GitHub editor handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_editor")
    def cmd_editor(call):
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
        user_state.set_field(chat_id, 'editor_path', '')
        _show_directory(bot, chat_id, call.message.message_id, config, repo_name, '')

    def _show_directory(bot_inst, chat_id, message_id, config, repo_name, path):
        """Show directory contents for browsing."""
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            contents = repo.get_contents(path)
            if not isinstance(contents, list):
                contents = [contents]

            # Store items in state for index-based callbacks
            items = []
            for item in contents[:30]:
                items.append({
                    'name': item.name,
                    'path': item.path,
                    'type': item.type,
                    'size': item.size
                })
            user_state.set_field(chat_id, 'editor_items', items)
            user_state.set_field(chat_id, 'editor_path', path)

            markup = types.InlineKeyboardMarkup(row_width=1)
            for idx, item in enumerate(items):
                if item['type'] == 'dir':
                    markup.add(types.InlineKeyboardButton(
                        f"📁 {item['name']}/",
                        callback_data=f"ed_d_{idx}"
                    ))
                else:
                    size = item['size']
                    size_str = f"{size // 1024}KB" if size > 1024 else f"{size}B"
                    markup.add(types.InlineKeyboardButton(
                        f"📄 {item['name']} ({size_str})",
                        callback_data=f"ed_f_{idx}"
                    ))

            # Add back navigation
            if path:
                parent = '/'.join(path.split('/')[:-1])
                markup.add(types.InlineKeyboardButton(
                    "⬆️ المجلد السابق", callback_data="ed_up"
                ))
            markup.add(
                types.InlineKeyboardButton(
                    "🔙 رجوع", callback_data="cmd_more_tools"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            display_path = path or "/"
            bot_inst.edit_message_text(
                f"📂 محرر الملفات - {repo_name}\n"
                f"المسار: {display_path}",
                chat_id, message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot_inst.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}",
                chat_id, message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("ed_d_"))
    def ed_navigate_dir(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        items = user_state.get_field(chat_id, 'editor_items', [])
        try:
            idx = int(call.data.replace("ed_d_", ""))
            item = items[idx]
            path = item['path']
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في التنقل.",
                chat_id, call.message.message_id
            )
            return
        _show_directory(bot, chat_id, call.message.message_id, config, repo_name, path)

    @bot.callback_query_handler(func=lambda c: c.data == "ed_up")
    def ed_navigate_up(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        current_path = user_state.get_field(chat_id, 'editor_path', '')
        parent = '/'.join(current_path.split('/')[:-1])
        _show_directory(bot, chat_id, call.message.message_id, config, repo_name, parent)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("ed_f_"))
    def ed_view_file(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        items = user_state.get_field(chat_id, 'editor_items', [])
        try:
            idx = int(call.data.replace("ed_f_", ""))
            item = items[idx]
            file_path = item['path']
        except (ValueError, IndexError):
            bot.edit_message_text(
                "❌ خطأ في تحديد الملف.",
                chat_id, call.message.message_id
            )
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            file_content = repo.get_contents(file_path)
            user_state.set_field(chat_id, 'editor_file_path', file_path)
            user_state.set_field(chat_id, 'editor_file_sha', file_content.sha)

            try:
                content = base64.b64decode(file_content.content).decode('utf-8')
            except (UnicodeDecodeError, Exception):
                content = "[ملف ثنائي - لا يمكن عرضه]"

            # Add line numbers and truncate
            lines = content.split('\n')[:100]
            numbered = '\n'.join(
                f"{i + 1:3}| {line}" for i, line in enumerate(lines)
            )
            if len(numbered) > 3500:
                numbered = numbered[:3500] + "\n..."

            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton(
                "✏️ تعديل", callback_data="ed_edit"
            ))
            markup.add(
                types.InlineKeyboardButton(
                    "⬆️ رجوع للمجلد", callback_data="ed_back_dir"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.edit_message_text(
                f"📄 {file_path}\n\n{numbered}",
                chat_id, call.message.message_id, reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}",
                chat_id, call.message.message_id
            )

    @bot.callback_query_handler(func=lambda c: c.data == "ed_back_dir")
    def ed_back_to_dir(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        current_path = user_state.get_field(chat_id, 'editor_path', '')
        _show_directory(bot, chat_id, call.message.message_id, config, repo_name, current_path)

    @bot.callback_query_handler(func=lambda c: c.data == "ed_edit")
    def ed_edit_file(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        file_path = user_state.get_field(chat_id, 'editor_file_path', '')
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="cmd_editor")
        )
        msg = bot.send_message(
            chat_id,
            f"✏️ أرسل المحتوى الجديد للملف:\n{file_path}",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, do_edit_file)
        try_delete_message(bot, chat_id, call.message.message_id)

    def do_edit_file(message):
        chat_id = message.chat.id
        new_content = message.text
        file_path = user_state.get_field(chat_id, 'editor_file_path', '')
        file_sha = user_state.get_field(chat_id, 'editor_file_sha', '')
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not config or not repo_name or not file_path:
            bot.reply_to(message, "❌ خطأ في البيانات.")
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            repo.update_file(
                path=file_path,
                message=f"تعديل {file_path} عبر البوت",
                content=new_content,
                sha=file_sha
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "📂 المحرر", callback_data="cmd_editor"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot.reply_to(
                message,
                f"✅ تم تحديث الملف: {file_path}",
                reply_markup=markup
            )
        except Exception as e:
            log_error(chat_id, e)
            bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")
