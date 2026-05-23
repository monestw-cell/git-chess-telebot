"""GitHub file browsing, replacement, and ZIP upload handlers."""

import io
import logging
import base64
import zipfile

from telebot import types
from github import Github, InputGitTreeElement, GithubException

from bot.state import user_state
from bot.database import get_user_config
from bot.utils import clean_txt, log_error, try_delete_message

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB - GitHub blob API practical limit


def _search_file_recursive(repo, target_name, path=""):
    """Recursive search for a file in all repository directories."""
    try:
        contents = repo.get_contents(path)
        if not isinstance(contents, list):
            contents = [contents]
        for item in contents:
            if item.type == "dir":
                result = _search_file_recursive(repo, target_name, item.path)
                if result:
                    return result
            elif item.name == target_name:
                return {"path": item.path, "sha": item.sha}
    except Exception:
        pass
    return None


def _extract_and_upload(bot, repo, zip_bytes, chat_id, progress_msg_id=None):
    """Extract ZIP and upload all files in a single commit."""
    def upd(text):
        if progress_msg_id:
            try:
                bot.edit_message_text(text, chat_id, progress_msg_id)
            except Exception:
                pass

    try:
        if not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
            upd("❌ الملف المرسل ليس ZIP صالحاً!")
            return

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            files = [
                f for f in z.infolist()
                if not f.is_dir()
                and not f.filename.startswith('__MACOSX')
                and '.DS_Store' not in f.filename
                and not f.filename.endswith('/')
                and f.file_size > 0
            ]
            total = len(files)
            if total == 0:
                upd("⚠️ الملف المضغوط فارغ من الملفات الصالحة!")
                return

            upd(f"📊 تم اكتشاف {total} ملف\nجاري إعداد الـ Commit...")

            base_commit = None
            base_tree_sha = None
            try:
                branch_obj = repo.get_branch(repo.default_branch)
                base_commit = repo.get_git_commit(branch_obj.commit.sha)
                base_tree_sha = base_commit.tree.sha
            except GithubException as branch_err:
                logger.info(
                    f"No existing branch (empty repo?): {branch_err}"
                )
            except Exception as branch_err:
                logger.warning(
                    f"Error fetching branch: {branch_err}"
                )

            # Detect common root directory
            top_dirs = set()
            for fi in files:
                parts = fi.filename.split('/')
                if len(parts) > 1:
                    top_dirs.add(parts[0])
            strip_prefix = (
                (list(top_dirs)[0] + '/') if len(top_dirs) == 1 else ''
            )

            tree_elements = []
            skipped = 0
            binary_count = 0
            text_count = 0

            for fi in files:
                raw_path = fi.filename
                file_path = (
                    raw_path[len(strip_prefix):]
                    if strip_prefix and raw_path.startswith(strip_prefix)
                    else raw_path
                )
                if not file_path or file_path.endswith('/'):
                    skipped += 1
                    continue
                if fi.file_size > MAX_FILE_SIZE:
                    skipped += 1
                    logger.warning(
                        f"Skipping large file {file_path}: "
                        f"{fi.file_size} bytes"
                    )
                    continue
                try:
                    content_bytes = z.read(fi.filename)
                except Exception as read_err:
                    skipped += 1
                    logger.warning(
                        f"Failed to read {file_path} from ZIP: {read_err}"
                    )
                    continue

                try:
                    content_str = content_bytes.decode('utf-8')
                    tree_elements.append(InputGitTreeElement(
                        path=file_path, mode='100644', type='blob',
                        content=content_str
                    ))
                    text_count += 1
                except (UnicodeDecodeError, ValueError):
                    try:
                        b64_str = base64.b64encode(
                            content_bytes
                        ).decode('ascii')
                        blob_obj = repo.create_git_blob(b64_str, "base64")
                        tree_elements.append(InputGitTreeElement(
                            path=file_path, mode='100644', type='blob',
                            sha=blob_obj.sha
                        ))
                        binary_count += 1
                    except GithubException as blob_err:
                        logger.warning(
                            f"GitHub blob creation failed for "
                            f"{file_path}: {blob_err}"
                        )
                        skipped += 1
                    except Exception as blob_err:
                        logger.warning(
                            f"Blob upload failed for "
                            f"{file_path}: {blob_err}"
                        )
                        skipped += 1

            if not tree_elements:
                upd("❌ لم يتم العثور على ملفات صالحة!")
                return

            if len(tree_elements) > 500:
                upd(
                    f"⚠️ عدد الملفات كبير ({len(tree_elements)}), "
                    f"قد يستغرق وقتاً..."
                )

            upd(
                f"🔗 جاري بناء شجرة Git\n"
                f"نصية: {text_count} | ثنائية: {binary_count}"
            )
            new_tree = repo.create_git_tree(
                tree_elements, base_tree=base_tree_sha
            )
            upd("💾 جاري إنشاء الـ Commit...")
            parents = [base_commit] if base_commit else []
            new_commit = repo.create_git_commit(
                message=f"رفع {len(tree_elements)} ملف عبر ZIP",
                tree=new_tree, parents=parents
            )

            upd("🔄 جاري تحديث المرجع...")
            if base_commit:
                git_ref = repo.get_git_ref(f"heads/{repo.default_branch}")
                try:
                    git_ref.edit(sha=new_commit.sha, force=False)
                except GithubException as ref_err:
                    logger.warning(f"Force-pushing due to: {ref_err}")
                    git_ref.edit(sha=new_commit.sha, force=True)
            else:
                repo.create_git_ref(
                    f"refs/heads/{repo.default_branch}", new_commit.sha
                )

            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🌐 فتح المستودع", url=repo.html_url
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            result = (
                f"✅ تم الرفع في Commit واحد!\n\n"
                f"الكلي: {total} | تم رفعه: {len(tree_elements)} | "
                f"تخطي: {skipped}\n"
                f"نصية: {text_count} | ثنائية: {binary_count}\n\n"
                f"{repo.html_url}"
            )
            if progress_msg_id:
                try:
                    bot.edit_message_text(result, chat_id, progress_msg_id)
                    bot.edit_message_reply_markup(
                        chat_id, progress_msg_id, reply_markup=markup
                    )
                except Exception:
                    bot.send_message(chat_id, result, reply_markup=markup)
            else:
                bot.send_message(chat_id, result, reply_markup=markup)

    except zipfile.BadZipFile:
        upd("❌ الملف المرسل ليس ZIP صالحاً!")
    except GithubException as ge:
        log_error(chat_id, ge)
        msg_data = (
            ge.data.get('message', str(ge))
            if isinstance(ge.data, dict) else str(ge)
        )
        upd(f"❌ خطأ GitHub: {clean_txt(msg_data)}")
    except Exception as e:
        log_error(chat_id, e)
        upd(f"❌ خطأ أثناء الرفع: {clean_txt(str(e))}")


def register(bot):
    """Register file handling handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_browse_files")
    def browse_files(call):
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
            "⏳ جاري جلب الملفات...",
            chat_id, call.message.message_id
        )
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            try:
                contents = repo.get_contents("")
                if not isinstance(contents, list):
                    contents = [contents]
                lines = []
                for item in contents[:30]:
                    if item.type == "dir":
                        lines.append(f"📁 {item.name}/")
                    else:
                        size = (
                            f"{item.size // 1024}KB"
                            if item.size > 1024
                            else f"{item.size}B"
                        )
                        lines.append(f"📄 {item.name}  ({size})")
                text = (
                    f"📂 ملفات {repo_name}:\n\n" + "\n".join(lines)
                )
            except GithubException as ge:
                if ge.status == 404 or (
                    isinstance(ge.data, dict)
                    and "empty" in ge.data.get("message", "").lower()
                ):
                    text = (
                        f"📂 المستودع {repo_name} فارغ.\n"
                        "ارفع ملفات عبر ZIP لتهيئته."
                    )
                else:
                    raise ge
            # Find back callback for current repo
            repo_map = user_state.get_field(chat_id, 'repo_map', {})
            back_cb = "my_projects"
            for cb, name in repo_map.items():
                if name == repo_name:
                    back_cb = cb
                    break
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🌐 فتح في GitHub", url=repo.html_url
                ),
                types.InlineKeyboardButton(
                    "🔙 رجوع", callback_data=back_cb
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

    @bot.callback_query_handler(func=lambda c: c.data == "cmd_replace_file")
    def ask_replace_file(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        repo_name = user_state.get_field(chat_id, 'current_repo')
        if not repo_name:
            return
        user_state.set_field(chat_id, 'mode', 'replace_file')
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu")
        )
        msg = bot.edit_message_text(
            f"🔄 استبدال ملف في: {repo_name}\n\n"
            "أرسل الملف الجديد الآن.\n\n"
            "يجب أن يكون اسمه مطابقاً تماماً للملف الموجود في المستودع.\n"
            "سيتم البحث عنه في جميع المجلدات واستبداله تلقائياً.",
            chat_id, call.message.message_id, reply_markup=markup
        )
        user_state.set_field(chat_id, 'waiting_replace_msg', msg.message_id)

    @bot.message_handler(content_types=['document'])
    def handle_any_document(message):
        chat_id = message.chat.id
        mode = user_state.get_field(chat_id, 'mode')
        if mode == 'replace_file':
            _do_replace_file(bot, message)
        elif mode in ('update', 'create'):
            _do_handle_zip(bot, message)

    def _do_replace_file(bot_inst, message):
        chat_id = message.chat.id
        config = get_user_config(chat_id)
        repo_name = user_state.get_field(chat_id, 'current_repo')
        file_name = message.document.file_name or ""
        if not config or not repo_name or not file_name:
            bot_inst.reply_to(message, "❌ خطأ في البيانات.")
            return
        wait_id = user_state.get_field(chat_id, 'waiting_replace_msg')
        user_state.set_field(chat_id, 'waiting_replace_msg', None)
        if wait_id:
            try_delete_message(bot_inst, chat_id, wait_id)
        pmsg = bot_inst.reply_to(
            message,
            f"🔍 جاري البحث عن '{file_name}' في {repo_name}..."
        )
        try:
            file_bytes = bot_inst.download_file(
                bot_inst.get_file(message.document.file_id).file_path
            )
        except Exception as e:
            log_error(chat_id, e)
            bot_inst.edit_message_text(
                f"❌ فشل تحميل الملف: {clean_txt(e)}",
                chat_id, pmsg.message_id
            )
            user_state.set_field(chat_id, 'mode', None)
            return
        try:
            repo = Github(config['token']).get_repo(
                f"{config['username']}/{repo_name}"
            )
            found = _search_file_recursive(repo, file_name)
            if not found:
                # Find back callback for current repo
                repo_map = user_state.get_field(chat_id, 'repo_map', {})
                back_cb = "my_projects"
                for cb, name in repo_map.items():
                    if name == repo_name:
                        back_cb = cb
                        break
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton(
                        "📤 رفع عبر ZIP",
                        callback_data="cmd_update_repo"
                    ),
                    types.InlineKeyboardButton(
                        "🔙 رجوع للمستودع", callback_data=back_cb
                    ),
                    types.InlineKeyboardButton(
                        "🏠 الرئيسية", callback_data="main_menu"
                    )
                )
                bot_inst.edit_message_text(
                    f"❌ لم يُعثر على ملف باسم:\n{file_name}\n\n"
                    "تأكد أن الاسم مطابق تماماً "
                    "(بما فيه الامتداد والحروف الكبيرة/الصغيرة).",
                    chat_id, pmsg.message_id, reply_markup=markup
                )
                user_state.set_field(chat_id, 'mode', None)
                return
            bot_inst.edit_message_text(
                f"✅ وُجد الملف في: {found['path']}\n⏳ جاري الاستبدال...",
                chat_id, pmsg.message_id
            )
            try:
                content_str = file_bytes.decode('utf-8')
            except (UnicodeDecodeError, ValueError):
                content_str = base64.b64encode(file_bytes).decode('ascii')
            repo.update_file(
                path=found['path'],
                message=f"استبدال {file_name} عبر البوت",
                content=content_str,
                sha=found['sha']
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🌐 فتح المستودع", url=repo.html_url
                ),
                types.InlineKeyboardButton(
                    "🔄 استبدال ملف آخر",
                    callback_data="cmd_replace_file"
                ),
                types.InlineKeyboardButton(
                    "🏠 الرئيسية", callback_data="main_menu"
                )
            )
            bot_inst.edit_message_text(
                f"✅ تم الاستبدال بنجاح!\n\n"
                f"الملف: {file_name}\n"
                f"المسار: {found['path']}\n"
                f"المستودع: {repo_name}",
                chat_id, pmsg.message_id, reply_markup=markup
            )
        except GithubException as ge:
            log_error(chat_id, ge)
            msg_data = (
                ge.data.get('message', str(ge))
                if isinstance(ge.data, dict) else str(ge)
            )
            bot_inst.edit_message_text(
                f"❌ خطأ GitHub: {clean_txt(msg_data)}",
                chat_id, pmsg.message_id
            )
        except Exception as e:
            log_error(chat_id, e)
            bot_inst.edit_message_text(
                f"❌ خطأ: {clean_txt(e)}", chat_id, pmsg.message_id
            )
        finally:
            user_state.set_field(chat_id, 'mode', None)

    def _do_handle_zip(bot_inst, message):
        chat_id = message.chat.id
        config = get_user_config(chat_id)
        mode = user_state.get_field(chat_id, 'mode')
        if not config:
            bot_inst.reply_to(
                message, "⚠️ يرجى ضبط إعدادات GitHub أولاً عبر /setup"
            )
            return
        fname = message.document.file_name or ""
        if not fname.lower().endswith('.zip'):
            bot_inst.reply_to(message, "⚠️ يرجى إرسال ملف ZIP فقط.")
            return
        wait_id = user_state.get_field(chat_id, 'waiting_zip_msg')
        user_state.set_field(chat_id, 'waiting_zip_msg', None)
        if wait_id:
            try_delete_message(bot_inst, chat_id, wait_id)
        if message.document.file_size > 50 * 1024 * 1024:
            bot_inst.reply_to(message, "❌ حجم الملف يتجاوز 50MB.")
            return
        pmsg = bot_inst.reply_to(message, "⏳ جاري تحميل الملف...")
        try:
            zip_bytes = bot_inst.download_file(
                bot_inst.get_file(message.document.file_id).file_path
            )
        except Exception as e:
            log_error(chat_id, e)
            bot_inst.edit_message_text(
                f"❌ فشل التحميل: {clean_txt(e)}",
                chat_id, pmsg.message_id
            )
            return
        if mode == 'update':
            repo_name = user_state.get_field(chat_id, 'current_repo')
            if not repo_name:
                bot_inst.edit_message_text(
                    "❌ لم يتم تحديد المستودع.",
                    chat_id, pmsg.message_id
                )
                return
            try:
                repo = Github(config['token']).get_repo(
                    f"{config['username']}/{repo_name}"
                )
                bot_inst.edit_message_text(
                    "📊 جاري معالجة الملفات...",
                    chat_id, pmsg.message_id
                )
                _extract_and_upload(
                    bot_inst, repo, zip_bytes, chat_id, pmsg.message_id
                )
            except Exception as e:
                log_error(chat_id, e)
                bot_inst.edit_message_text(
                    f"❌ خطأ: {clean_txt(e)}",
                    chat_id, pmsg.message_id
                )
            finally:
                user_state.set_field(chat_id, 'mode', None)
        elif mode == 'create':
            state = user_state.get(chat_id)
            state['file'] = zip_bytes
            state['progress_msg_id'] = pmsg.message_id
            markup = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    "🚫 إلغاء", callback_data="main_menu"
                )
            )
            bot_inst.edit_message_text(
                "✅ تم استلام الملف!\nأرسل اسم المستودع الجديد:",
                chat_id, pmsg.message_id, reply_markup=markup
            )
            bot_inst.register_next_step_handler_by_chat_id(
                chat_id, lambda m: _finalize_create_repo(bot_inst, m)
            )

    def _finalize_create_repo(bot_inst, message):
        chat_id = message.chat.id
        repo_name = message.text.strip().replace(" ", "-")
        config = get_user_config(chat_id)
        state = user_state.get(chat_id)
        pmid = state.get('progress_msg_id')
        zb = state.get('file')
        if not zb or not config:
            bot_inst.reply_to(message, "❌ حدث خطأ، ابدأ من جديد.")
            return
        try:
            bot_inst.edit_message_text(
                "⏳ جاري إنشاء المستودع...", chat_id, pmid
            )
        except Exception:
            pmid = bot_inst.send_message(
                chat_id, "⏳ جاري الإنشاء..."
            ).message_id
        try:
            repo = Github(config['token']).get_user().create_repo(repo_name)
            user_state.set_field(chat_id, 'current_repo', repo_name)
            _extract_and_upload(bot_inst, repo, zb, chat_id, pmid)
        except Exception as e:
            log_error(chat_id, e)
            try:
                bot_inst.edit_message_text(
                    f"❌ فشل: {clean_txt(e)}", chat_id, pmid
                )
            except Exception:
                bot_inst.send_message(
                    chat_id, f"❌ فشل: {clean_txt(e)}"
                )
        finally:
            user_state.set_field(chat_id, 'mode', None)
            state.pop('file', None)
