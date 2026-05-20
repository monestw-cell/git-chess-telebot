import os
import telebot
from telebot import types, apihelper
import json
import io
import chess
import chess.engine
import chess.pgn
import math
import zipfile
import base64
import requests
from github import Github, InputGitTreeElement, GithubException
from flask import Flask
from threading import Thread
from datetime import datetime
import logging

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('TELEGRAM_TOKEN')
apihelper.READ_TIMEOUT = 120
apihelper.CONNECT_TIMEOUT = 120
CONFIG_FILE = "config.json"
STOCKFISH_PATH = "/usr/games/stockfish"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_steps = {}
awaiting_pgn = {}
chess_wait_msg = {}
error_logs = []
start_time = datetime.now()

# ===================== إعداد الأوامر =====================
def setup_commands():
    commands = [
        types.BotCommand("start",  "القائمة الرئيسية"),
        types.BotCommand("help",   "مساعدة"),
        types.BotCommand("check",  "تحليل شطرنج"),
        types.BotCommand("setup",  "ضبط GitHub"),
        types.BotCommand("logs",   "سجل الأخطاء"),
        types.BotCommand("status", "حالة البوت"),
    ]
    try:
        bot.set_my_commands(commands)
    except Exception as e:
        logger.error(f"فشل تعيين الأوامر: {e}")

# ===================== الإعدادات =====================
def save_config(token, username):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({"token": token, "username": username}, f)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def clean_txt(text):
    return str(text).replace('`', "'").replace('*', '').replace('_', '').replace('[', '(').replace(']', ')')

def clear_user_state(chat_id):
    repo_map = user_steps.get(chat_id, {}).get('repo_map')
    wf_map   = user_steps.get(chat_id, {}).get('wf_map')
    current  = user_steps.get(chat_id, {}).get('current_repo')
    user_steps.pop(chat_id, None)
    awaiting_pgn.pop(chat_id, None)
    chess_wait_msg.pop(chat_id, None)
    preserved = {}
    if repo_map:  preserved['repo_map']     = repo_map
    if wf_map:    preserved['wf_map']       = wf_map
    if current:   preserved['current_repo'] = current
    if preserved: user_steps[chat_id]       = preserved

def send_long_message(chat_id, text, reply_markup=None):
    max_len = 4000
    if len(text) <= max_len:
        try:
            return bot.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception:
            return bot.send_message(chat_id, text[:max_len], reply_markup=reply_markup)
    parts = []
    while len(text) > max_len:
        idx = text.rfind('\n', 0, max_len)
        if idx == -1: idx = max_len
        parts.append(text[:idx])
        text = text[idx:].lstrip('\n')
    parts.append(text)
    for i, p in enumerate(parts):
        bot.send_message(chat_id, p,
                         reply_markup=reply_markup if i == len(parts) - 1 else None)

def log_error(chat_id, error_msg):
    entry = f"{datetime.now().strftime('%H:%M:%S')} | {chat_id} | {str(error_msg)[:200]}"
    error_logs.append(entry)
    if len(error_logs) > 20:
        error_logs.pop(0)
    logger.error(entry)

# ===================== أدوات الشطرنج =====================
def get_estimated_elo(acc):
    if acc >= 99: return 2800
    if acc >= 95: return 2200 + int((acc - 95) * 120)
    if acc >= 90: return 1800 + int((acc - 90) * 80)
    if acc >= 80: return 1300 + int((acc - 80) * 50)
    if acc >= 70: return 900  + int((acc - 70) * 40)
    if acc >= 55: return 500  + int((acc - 55) * 26)
    return max(100, int(acc * 7))

def calculate_accuracy(loss_list):
    if not loss_list: return 100.0
    avg_loss = sum(loss_list) / len(loss_list)
    acc = 103.1668 * math.exp(-0.04354 * math.sqrt(avg_loss)) - 3.1668
    return round(max(0.0, min(100.0, acc)), 1)

def acc_bar(acc):
    filled = int(acc / 10)
    return "█" * filled + "░" * (10 - filled) + f" {acc}%"

def generate_eval_graph(game, engine):
    if not MATPLOTLIB_AVAILABLE:
        return None
    try:
        board = game.board()
        scores = []
        for move in game.mainline_moves():
            info = engine.analyse(board, chess.engine.Limit(depth=10))
            s = info["score"].relative.score(mate_score=10000)
            scores.append(max(-1000, min(1000, s / 100.0)))
            board.push(move)
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.fill_between(range(1, len(scores)+1), scores, 0,
                        where=[s > 0 for s in scores], color='white', alpha=0.6)
        ax.fill_between(range(1, len(scores)+1), scores, 0,
                        where=[s < 0 for s in scores], color='gray', alpha=0.6)
        ax.plot(range(1, len(scores)+1), scores, color='black', linewidth=1.2)
        ax.axhline(y=0, color='black', linewidth=1.0)
        ax.set_title('تقييم المباراة', fontsize=13)
        ax.set_xlabel('رقم النقلة')
        ax.set_ylabel('التقييم (بيدق)')
        ax.grid(True, alpha=0.2)
        ax.set_ylim(-12, 12)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=110)
        buf.seek(0)
        plt.close()
        return buf
    except Exception as e:
        logger.warning(f"فشل الرسم: {e}")
        return None

# ===================== القائمة الرئيسية =====================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    clear_user_state(message.chat.id)
    show_main_menu(message.chat.id)

def show_main_menu(chat_id):
    clear_user_state(chat_id)
    config = load_config()
    status = f"متصل: {config['username']}" if config else "غير متصل بـ GitHub"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📁 مشاريعي",      callback_data="my_projects"),
        types.InlineKeyboardButton("➕ مشروع جديد",   callback_data="create_new_repo")
    )
    markup.add(
        types.InlineKeyboardButton("📊 إحصائيات",     callback_data="account_info"),
        types.InlineKeyboardButton("♟️ تحليل شطرنج", callback_data="start_check")
    )
    markup.add(
        types.InlineKeyboardButton("⚙️ الإعدادات",    callback_data="setup_now"),
        types.InlineKeyboardButton("❓ مساعدة",        callback_data="help_menu")
    )
    markup.add(types.InlineKeyboardButton("📈 حالة البوت", callback_data="bot_status"))
    bot.send_message(chat_id,
        f"🤖 مدير المشاريع السحابي\n\n✅ {status}\n\nاختر من القائمة:",
        reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "main_menu")
def back_to_main(call):
    bot.answer_callback_query(call.id)
    clear_user_state(call.message.chat.id)
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
    show_main_menu(call.message.chat.id)

# ===================== المساعدة =====================
@bot.message_handler(commands=['help'])
def cmd_help(message):
    show_help_menu(message.chat.id, None)

@bot.callback_query_handler(func=lambda c: c.data == "help_menu")
def callback_help(call):
    bot.answer_callback_query(call.id)
    show_help_menu(call.message.chat.id, call.message.message_id)

def show_help_menu(chat_id, message_id):
    text = (
        "📖 دليل الاستخدام:\n\n"
        "🗂️ GitHub:\n"
        "  • إنشاء مستودع برفع ZIP أو فارغ\n"
        "  • تحديث المستودع في Commit واحد\n"
        "  • استبدال ملف واحد مباشرة\n"
        "  • حذف المستودعات\n"
        "  • تشغيل Workflows\n"
        "  • إعادة تسمية / تغيير الوصف / الخصوصية\n"
        "  • استعراض ملفات المستودع\n\n"
        "♟️ الشطرنج:\n"
        "  • اضغط (تحليل شطرنج) وأرسل PGN\n\n"
        "أوامر: /start /help /check /setup /logs /status"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
    if message_id:
        try:    bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except: bot.send_message(chat_id, text, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)

# ===================== حالة البوت =====================
@bot.message_handler(commands=['status'])
def cmd_status(message):
    show_bot_status(message.chat.id, None)

@bot.callback_query_handler(func=lambda c: c.data == "bot_status")
def callback_status(call):
    bot.answer_callback_query(call.id)
    show_bot_status(call.message.chat.id, call.message.message_id)

def show_bot_status(chat_id, message_id):
    uptime = datetime.now() - start_time
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    config  = load_config()
    gh_status = "✅ متصل" if config else "❌ غير متصل"
    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as e:
            e.analyse(chess.Board(), chess.engine.Limit(depth=1))
        sf_status = "✅ يعمل"
    except:
        sf_status = "❌ متوقف"
    text = (
        f"📈 حالة البوت:\n\n"
        f"⏱️ وقت التشغيل: {h}h {m}m {s}s\n"
        f"🐙 GitHub: {gh_status}\n"
        f"♟️ Stockfish: {sf_status}\n"
        f"🔴 أخطاء مسجلة: {len(error_logs)}\n"
        f"👥 جلسات نشطة: {len(user_steps)}\n"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
    if message_id:
        try:    bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except: bot.send_message(chat_id, text, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)

# ===================== إحصائيات GitHub =====================
@bot.callback_query_handler(func=lambda c: c.data == "account_info")
def show_account_info(call):
    bot.answer_callback_query(call.id)
    config = load_config()
    if not config:
        bot.edit_message_text("⚠️ يرجى ضبط الإعدادات أولاً.", call.message.chat.id, call.message.message_id)
        return
    bot.edit_message_text("⏳ جاري جلب بيانات حسابك...", call.message.chat.id, call.message.message_id)
    try:
        g    = Github(config['token'])
        user = g.get_user()
        repos = list(user.get_repos())
        total_stars = sum(r.stargazers_count for r in repos)
        total_forks = sum(r.forks_count for r in repos)
        langs = {}
        for r in repos[:20]:
            try:
                for lang, bc in r.get_languages().items():
                    langs[lang] = langs.get(lang, 0) + bc
            except: pass
        top_langs = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:3]
        langs_str = " | ".join(l[0] for l in top_langs) if top_langs else "غير محدد"
        try:
            rl = g.get_rate_limit()
            if   hasattr(rl, 'core'): api_info = f"🔑 API: {rl.core.remaining}/{rl.core.limit} طلب متبقي"
            elif hasattr(rl, 'rate'): api_info = f"🔑 API: {rl.rate.remaining}/{rl.rate.limit} طلب متبقي"
            else:                     api_info = "🔑 API: متصل"
        except: api_info = "🔑 API: متصل"
        text = (
            f"👤 معلومات GitHub:\n\n"
            f"الاسم: {user.name or user.login}\n"
            f"المستخدم: {user.login}\n"
            f"البريد: {user.email or 'مخفي'}\n"
            f"الموقع: {user.location or 'غير محدد'}\n\n"
            f"📦 المستودعات: {user.public_repos} عامة\n"
            f"⭐ إجمالي النجوم: {total_stars}\n"
            f"🍴 إجمالي الفورك: {total_forks}\n"
            f"👥 المتابعون: {user.followers} | يتابع: {user.following}\n\n"
            f"💻 أبرز اللغات: {langs_str}\n\n"
            f"{api_info}"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        log_error(call.message.chat.id, e)
        bot.edit_message_text(f"❌ خطأ: {clean_txt(e)}", call.message.chat.id, call.message.message_id)

# ===================== قائمة المشاريع =====================
@bot.callback_query_handler(func=lambda c: c.data == "my_projects")
def list_projects(call):
    bot.answer_callback_query(call.id)
    config = load_config()
    if not config:
        bot.edit_message_text("⚠️ يرجى ضبط الإعدادات أولاً.", call.message.chat.id, call.message.message_id)
        return
    bot.edit_message_text("⏳ جاري جلب مشاريعك...", call.message.chat.id, call.message.message_id)
    try:
        repos = list(Github(config['token']).get_user().get_repos(sort="updated"))
        markup = types.InlineKeyboardMarkup(row_width=1)
        repo_list = {}
        for repo in repos[:25]:
            vis = "🔒" if repo.private else "🌐"
            cb  = f"sel_{abs(hash(repo.name)) % 100000}"
            repo_list[cb] = repo.name
            markup.add(types.InlineKeyboardButton(
                f"{vis} {repo.name}  ⭐{repo.stargazers_count}",
                callback_data=cb))
        markup.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        user_steps[call.message.chat.id] = user_steps.get(call.message.chat.id, {})
        user_steps[call.message.chat.id]['repo_map'] = repo_list
        bot.edit_message_text(
            f"📁 مشاريعك ({len(repos)} مستودع) - مرتبة حسب آخر تحديث:",
            call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        log_error(call.message.chat.id, e)
        bot.edit_message_text(f"❌ خطأ: {clean_txt(e)}", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sel_"))
def repo_selected(call):
    bot.answer_callback_query(call.id)
    chat_id  = call.message.chat.id
    repo_map = user_steps.get(chat_id, {}).get('repo_map', {})
    repo_name = repo_map.get(call.data)
    if not repo_name:
        bot.edit_message_text("❌ حدث خطأ، حاول مجدداً.", chat_id, call.message.message_id)
        return
    config = load_config()
    user_steps[chat_id] = user_steps.get(chat_id, {})
    user_steps[chat_id]['current_repo'] = repo_name
    user_steps[chat_id]['repo_map']     = repo_map
    try:
        repo = Github(config['token']).get_repo(f"{config['username']}/{repo_name}")
        vis  = "🔒 خاص" if repo.private else "🌐 عام"
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
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📤 رفع ZIP",      callback_data="cmd_update_repo"),
        types.InlineKeyboardButton("🔄 استبدال ملف", callback_data="cmd_replace_file")
    )
    markup.add(
        types.InlineKeyboardButton("⚡ Workflows",    callback_data="cmd_workflows"),
        types.InlineKeyboardButton("📄 الملفات",      callback_data="cmd_browse_files")
    )
    markup.add(
        types.InlineKeyboardButton("⚙️ إعدادات",     callback_data="cmd_repo_settings"),
        types.InlineKeyboardButton("🗑️ حذف",          callback_data="cmd_delete_repo")
    )
    markup.add(
        types.InlineKeyboardButton("🔙 رجوع",         callback_data="my_projects"),
        types.InlineKeyboardButton("🏠 الرئيسية",     callback_data="main_menu")
    )
    bot.edit_message_text(info, chat_id, call.message.message_id, reply_markup=markup)

# ===================== استعراض الملفات =====================
@bot.callback_query_handler(func=lambda c: c.data == "cmd_browse_files")
def browse_files(call):
    bot.answer_callback_query(call.id)
    chat_id   = call.message.chat.id
    repo_name = user_steps.get(chat_id, {}).get('current_repo')
    config    = load_config()
    if not config or not repo_name:
        bot.edit_message_text("❌ خطأ في البيانات.", chat_id, call.message.message_id)
        return
    bot.edit_message_text("⏳ جاري جلب الملفات...", chat_id, call.message.message_id)
    try:
        repo = Github(config['token']).get_repo(f"{config['username']}/{repo_name}")
        try:
            contents = repo.get_contents("")
            if not isinstance(contents, list): contents = [contents]
            lines = []
            for item in contents[:30]:
                if item.type == "dir":
                    lines.append(f"📁 {item.name}/")
                else:
                    size = f"{item.size//1024}KB" if item.size > 1024 else f"{item.size}B"
                    lines.append(f"📄 {item.name}  ({size})")
            text = f"📂 ملفات {repo_name}:\n\n" + "\n".join(lines)
        except GithubException as ge:
            if ge.status == 404 or (isinstance(ge.data, dict) and "empty" in ge.data.get("message","").lower()):
                text = f"📂 المستودع {repo_name} فارغ.\nارفع ملفات عبر ZIP لتهيئته."
            else:
                raise ge
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🌐 فتح في GitHub", url=repo.html_url),
            types.InlineKeyboardButton("🔙 رجوع", callback_data=f"sel_{abs(hash(repo_name))%100000}"),
            types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")
        )
        bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        log_error(chat_id, e)
        bot.edit_message_text(f"❌ خطأ: {clean_txt(e)}", chat_id, call.message.message_id)

# ===================== استبدال ملف واحد =====================
@bot.callback_query_handler(func=lambda c: c.data == "cmd_replace_file")
def ask_replace_file(call):
    bot.answer_callback_query(call.id)
    chat_id   = call.message.chat.id
    repo_name = user_steps.get(chat_id, {}).get('current_repo')
    if not repo_name: return
    user_steps[chat_id]['mode'] = 'replace_file'
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    msg = bot.edit_message_text(
        f"🔄 استبدال ملف في: {repo_name}\n\n"
        "أرسل الملف الجديد الآن.\n\n"
        "يجب أن يكون اسمه مطابقاً تماماً للملف الموجود في المستودع.\n"
        "سيتم البحث عنه في جميع المجلدات واستبداله تلقائياً.",
        chat_id, call.message.message_id, reply_markup=markup)
    user_steps[chat_id]['waiting_replace_msg'] = msg.message_id

def search_file_recursive(repo, target_name, path=""):
    """بحث متكرر عن ملف في كل مجلدات المستودع"""
    try:
        contents = repo.get_contents(path)
        if not isinstance(contents, list): contents = [contents]
        for item in contents:
            if item.type == "dir":
                result = search_file_recursive(repo, target_name, item.path)
                if result: return result
            elif item.name == target_name:
                return {"path": item.path, "sha": item.sha}
    except Exception:
        pass
    return None

# ===================== معالج الملفات الموحد =====================
@bot.message_handler(content_types=['document'])
def handle_any_document(message):
    chat_id = message.chat.id
    mode    = user_steps.get(chat_id, {}).get('mode')
    if mode == 'replace_file':
        do_replace_file(message)
    elif mode in ('update', 'create'):
        do_handle_zip(message)

def do_replace_file(message):
    chat_id   = message.chat.id
    config    = load_config()
    repo_name = user_steps.get(chat_id, {}).get('current_repo')
    file_name = message.document.file_name or ""
    if not config or not repo_name or not file_name:
        bot.reply_to(message, "❌ خطأ في البيانات.")
        return
    wait_id = user_steps[chat_id].pop('waiting_replace_msg', None)
    if wait_id:
        try: bot.delete_message(chat_id, wait_id)
        except: pass
    pmsg = bot.reply_to(message, f"🔍 جاري البحث عن '{file_name}' في {repo_name}...")
    try:
        file_bytes = bot.download_file(bot.get_file(message.document.file_id).file_path)
    except Exception as e:
        log_error(chat_id, e)
        bot.edit_message_text(f"❌ فشل تحميل الملف: {clean_txt(e)}", chat_id, pmsg.message_id)
        user_steps[chat_id]['mode'] = None
        return
    try:
        repo  = Github(config['token']).get_repo(f"{config['username']}/{repo_name}")
        found = search_file_recursive(repo, file_name)
        if not found:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("📤 رفع عبر ZIP",     callback_data="cmd_update_repo"),
                types.InlineKeyboardButton("🔙 رجوع للمستودع",  callback_data=f"sel_{abs(hash(repo_name))%100000}"),
                types.InlineKeyboardButton("🏠 الرئيسية",        callback_data="main_menu")
            )
            bot.edit_message_text(
                f"❌ لم يُعثر على ملف باسم:\n{file_name}\n\n"
                "تأكد أن الاسم مطابق تماماً (بما فيه الامتداد والحروف الكبيرة/الصغيرة).",
                chat_id, pmsg.message_id, reply_markup=markup)
            user_steps[chat_id]['mode'] = None
            return
        bot.edit_message_text(
            f"✅ وُجد الملف في: {found['path']}\n⏳ جاري الاستبدال...",
            chat_id, pmsg.message_id)
        try:
            content_str = file_bytes.decode('utf-8')
        except (UnicodeDecodeError, ValueError):
            content_str = base64.b64encode(file_bytes).decode('ascii')
        repo.update_file(
            path=found['path'],
            message=f"استبدال {file_name} عبر البوت",
            content=content_str,
            sha=found['sha'])
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🌐 فتح المستودع",       url=repo.html_url),
            types.InlineKeyboardButton("🔄 استبدال ملف آخر",   callback_data="cmd_replace_file"),
            types.InlineKeyboardButton("🏠 الرئيسية",           callback_data="main_menu")
        )
        bot.edit_message_text(
            f"✅ تم الاستبدال بنجاح!\n\n"
            f"الملف: {file_name}\n"
            f"المسار: {found['path']}\n"
            f"المستودع: {repo_name}",
            chat_id, pmsg.message_id, reply_markup=markup)
    except GithubException as ge:
        log_error(chat_id, ge)
        msg_data = ge.data.get('message', str(ge)) if isinstance(ge.data, dict) else str(ge)
        bot.edit_message_text(f"❌ خطأ GitHub: {clean_txt(msg_data)}", chat_id, pmsg.message_id)
    except Exception as e:
        log_error(chat_id, e)
        bot.edit_message_text(f"❌ خطأ: {clean_txt(e)}", chat_id, pmsg.message_id)
    finally:
        user_steps[chat_id]['mode'] = None

def do_handle_zip(message):
    chat_id = message.chat.id
    config  = load_config()
    mode    = user_steps.get(chat_id, {}).get('mode')
    if not config:
        bot.reply_to(message, "⚠️ يرجى ضبط إعدادات GitHub أولاً عبر /setup")
        return
    fname = message.document.file_name or ""
    if not fname.lower().endswith('.zip'):
        bot.reply_to(message, "⚠️ يرجى إرسال ملف ZIP فقط.")
        return
    wait_id = user_steps[chat_id].pop('waiting_zip_msg', None)
    if wait_id:
        try: bot.delete_message(chat_id, wait_id)
        except: pass
    if message.document.file_size > 50 * 1024 * 1024:
        bot.reply_to(message, "❌ حجم الملف يتجاوز 50MB.")
        return
    pmsg = bot.reply_to(message, "⏳ جاري تحميل الملف...")
    try:
        zip_bytes = bot.download_file(bot.get_file(message.document.file_id).file_path)
    except Exception as e:
        log_error(chat_id, e)
        bot.edit_message_text(f"❌ فشل التحميل: {clean_txt(e)}", chat_id, pmsg.message_id)
        return
    if mode == 'update':
        repo_name = user_steps[chat_id].get('current_repo')
        if not repo_name:
            bot.edit_message_text("❌ لم يتم تحديد المستودع.", chat_id, pmsg.message_id)
            return
        try:
            repo = Github(config['token']).get_repo(f"{config['username']}/{repo_name}")
            bot.edit_message_text("📊 جاري معالجة الملفات...", chat_id, pmsg.message_id)
            extract_and_upload(repo, zip_bytes, chat_id, pmsg.message_id)
        except Exception as e:
            log_error(chat_id, e)
            bot.edit_message_text(f"❌ خطأ: {clean_txt(e)}", chat_id, pmsg.message_id)
        finally:
            user_steps[chat_id]['mode'] = None
    elif mode == 'create':
        user_steps[chat_id]['file']            = zip_bytes
        user_steps[chat_id]['progress_msg_id'] = pmsg.message_id
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
        bot.edit_message_text("✅ تم استلام الملف!\nأرسل اسم المستودع الجديد:",
                              chat_id, pmsg.message_id, reply_markup=markup)
        bot.register_next_step_handler_by_chat_id(chat_id, finalize_create_repo)

def finalize_create_repo(message):
    chat_id   = message.chat.id
    repo_name = message.text.strip().replace(" ", "-")
    config    = load_config()
    pmid = user_steps.get(chat_id, {}).get('progress_msg_id')
    zb   = user_steps.get(chat_id, {}).get('file')
    if not zb or not config:
        bot.reply_to(message, "❌ حدث خطأ، ابدأ من جديد.")
        return
    try:
        bot.edit_message_text("⏳ جاري إنشاء المستودع...", chat_id, pmid)
    except:
        pmid = bot.send_message(chat_id, "⏳ جاري الإنشاء...").message_id
    try:
        repo = Github(config['token']).get_user().create_repo(repo_name)
        user_steps[chat_id]['current_repo'] = repo_name
        extract_and_upload(repo, zb, chat_id, pmid)
    except Exception as e:
        log_error(chat_id, e)
        try:    bot.edit_message_text(f"❌ فشل: {clean_txt(e)}", chat_id, pmid)
        except: bot.send_message(chat_id, f"❌ فشل: {clean_txt(e)}")
    finally:
        user_steps[chat_id]['mode'] = None
        user_steps[chat_id].pop('file', None)

# ===================== رفع ZIP في Commit واحد =====================
def extract_and_upload(repo, zip_bytes, chat_id, progress_msg_id=None):
    def upd(text):
        if progress_msg_id:
            try: bot.edit_message_text(text, chat_id, progress_msg_id)
            except: pass
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

            # جلب المرجع الأساسي
            base_commit    = None
            base_tree_sha  = None
            try:
                branch_obj    = repo.get_branch(repo.default_branch)
                base_commit   = repo.get_git_commit(branch_obj.commit.sha)
                base_tree_sha = base_commit.tree.sha
            except Exception:
                pass

            # كشف المجلد الجذري المشترك
            top_dirs = set()
            for fi in files:
                parts = fi.filename.split('/')
                if len(parts) > 1:
                    top_dirs.add(parts[0])
            strip_prefix = (list(top_dirs)[0] + '/') if len(top_dirs) == 1 else ''

            tree_elements = []
            skipped       = 0
            binary_count  = 0
            text_count    = 0

            for fi in files:
                raw_path  = fi.filename
                file_path = (raw_path[len(strip_prefix):]
                             if strip_prefix and raw_path.startswith(strip_prefix)
                             else raw_path)
                if not file_path or file_path.endswith('/'):
                    skipped += 1
                    continue
                try:
                    content_bytes = z.read(fi.filename)
                except Exception:
                    skipped += 1
                    continue

                # نصي: يُرسل مباشرة كـ content
                try:
                    content_str = content_bytes.decode('utf-8')
                    tree_elements.append(InputGitTreeElement(
                        path=file_path, mode='100644', type='blob',
                        content=content_str))
                    text_count += 1
                except (UnicodeDecodeError, ValueError):
                    # ثنائي: يُرفع blob أولاً ثم يُشار بـ sha
                    try:
                        b64_str  = base64.b64encode(content_bytes).decode('ascii')
                        blob_obj = repo.create_git_blob(b64_str, "base64")
                        tree_elements.append(InputGitTreeElement(
                            path=file_path, mode='100644', type='blob',
                            sha=blob_obj.sha))
                        binary_count += 1
                    except Exception as blob_err:
                        logger.warning(f"فشل blob {file_path}: {blob_err}")
                        skipped += 1

            if not tree_elements:
                upd("❌ لم يتم العثور على ملفات صالحة!")
                return

            upd(f"🔗 جاري بناء شجرة Git\nنصية: {text_count} | ثنائية: {binary_count}")
            new_tree   = repo.create_git_tree(tree_elements, base_tree=base_tree_sha)
            upd("💾 جاري إنشاء الـ Commit...")
            parents    = [base_commit] if base_commit else []
            new_commit = repo.create_git_commit(
                message=f"رفع {len(tree_elements)} ملف عبر ZIP",
                tree=new_tree, parents=parents)
            git_ref    = repo.get_git_ref(f"heads/{repo.default_branch}")
            git_ref.edit(sha=new_commit.sha, force=False)

            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🌐 فتح المستودع", url=repo.html_url),
                types.InlineKeyboardButton("🏠 الرئيسية",     callback_data="main_menu"))
            result = (
                f"✅ تم الرفع في Commit واحد!\n\n"
                f"الكلي: {total} | تم رفعه: {len(tree_elements)} | تخطي: {skipped}\n"
                f"نصية: {text_count} | ثنائية: {binary_count}\n\n"
                f"{repo.html_url}"
            )
            if progress_msg_id:
                try:
                    bot.edit_message_text(result, chat_id, progress_msg_id)
                    bot.edit_message_reply_markup(chat_id, progress_msg_id, reply_markup=markup)
                except:
                    bot.send_message(chat_id, result, reply_markup=markup)
            else:
                bot.send_message(chat_id, result, reply_markup=markup)

    except zipfile.BadZipFile:
        upd("❌ الملف المرسل ليس ZIP صالحاً!")
    except GithubException as ge:
        log_error(chat_id, ge)
        msg_data = ge.data.get('message', str(ge)) if isinstance(ge.data, dict) else str(ge)
        upd(f"❌ خطأ GitHub: {clean_txt(msg_data)}")
    except Exception as e:
        log_error(chat_id, e)
        upd(f"❌ خطأ أثناء الرفع: {clean_txt(str(e))}")

# ===================== إعدادات المستودع =====================
@bot.callback_query_handler(func=lambda c: c.data == "cmd_repo_settings")
def repo_settings(call):
    bot.answer_callback_query(call.id)
    chat_id   = call.message.chat.id
    repo_name = user_steps.get(chat_id, {}).get('current_repo')
    if not repo_name: return
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✏️ تغيير الاسم",       callback_data="cmd_rename_repo"),
        types.InlineKeyboardButton("📝 تغيير الوصف",       callback_data="cmd_change_desc"),
        types.InlineKeyboardButton("🔐 تبديل الخصوصية",   callback_data="cmd_toggle_visibility"),
        types.InlineKeyboardButton("🔙 رجوع",              callback_data=f"sel_{abs(hash(repo_name))%100000}"),
        types.InlineKeyboardButton("🏠 الرئيسية",          callback_data="main_menu")
    )
    bot.edit_message_text(f"⚙️ إعدادات {repo_name}:", chat_id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "cmd_rename_repo")
def ask_rename(call):
    bot.answer_callback_query(call.id)
    chat_id   = call.message.chat.id
    repo_name = user_steps.get(chat_id, {}).get('current_repo')
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    msg = bot.send_message(chat_id, f"✏️ أرسل الاسم الجديد للمستودع {repo_name}:", reply_markup=markup)
    bot.register_next_step_handler(msg, do_rename_repo)
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass

def do_rename_repo(message):
    chat_id   = message.chat.id
    new_name  = message.text.strip().replace(" ", "-")
    repo_name = user_steps.get(chat_id, {}).get('current_repo')
    config    = load_config()
    try:
        repo = Github(config['token']).get_repo(f"{config['username']}/{repo_name}")
        repo.edit(name=new_name)
        user_steps[chat_id]['current_repo'] = new_name
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.reply_to(message, f"✅ تم إعادة التسمية إلى: {new_name}", reply_markup=markup)
    except Exception as e:
        log_error(chat_id, e)
        bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")

@bot.callback_query_handler(func=lambda c: c.data == "cmd_change_desc")
def ask_desc(call):
    bot.answer_callback_query(call.id)
    chat_id   = call.message.chat.id
    repo_name = user_steps.get(chat_id, {}).get('current_repo')
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    msg = bot.send_message(chat_id, f"📝 أرسل الوصف الجديد للمستودع {repo_name}:", reply_markup=markup)
    bot.register_next_step_handler(msg, do_change_desc)
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass

def do_change_desc(message):
    chat_id   = message.chat.id
    new_desc  = message.text.strip()
    repo_name = user_steps.get(chat_id, {}).get('current_repo')
    config    = load_config()
    try:
        repo = Github(config['token']).get_repo(f"{config['username']}/{repo_name}")
        repo.edit(description=new_desc)
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.reply_to(message, "✅ تم تحديث الوصف بنجاح!", reply_markup=markup)
    except Exception as e:
        log_error(chat_id, e)
        bot.reply_to(message, f"❌ فشل: {clean_txt(e)}")

@bot.callback_query_handler(func=lambda c: c.data == "cmd_toggle_visibility")
def toggle_visibility(call):
    bot.answer_callback_query(call.id)
    chat_id   = call.message.chat.id
    repo_name = user_steps.get(chat_id, {}).get('current_repo')
    config    = load_config()
    bot.edit_message_text("⏳ جاري تغيير الخصوصية...", chat_id, call.message.message_id)
    try:
        repo = Github(config['token']).get_repo(f"{config['username']}/{repo_name}")
        new_private = not repo.private
        repo.edit(private=new_private)
        status_txt = "🔒 خاص" if new_private else "🌐 عام"
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.edit_message_text(f"✅ تم تغيير {repo_name} إلى {status_txt}",
                              chat_id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        log_error(chat_id, e)
        bot.edit_message_text(f"❌ فشل: {clean_txt(e)}", chat_id, call.message.message_id)

# ===================== Workflows =====================
@bot.callback_query_handler(func=lambda c: c.data == "cmd_workflows")
def list_workflows(call):
    bot.answer_callback_query(call.id)
    chat_id   = call.message.chat.id
    repo_name = user_steps.get(chat_id, {}).get('current_repo')
    config    = load_config()
    if not config or not repo_name:
        bot.edit_message_text("❌ خطأ في البيانات.", chat_id, call.message.message_id)
        return
    bot.edit_message_text("⏳ جاري فحص الـ Workflows...", chat_id, call.message.message_id)
    try:
        repo      = Github(config['token']).get_repo(f"{config['username']}/{repo_name}")
        workflows = list(repo.get_workflows())
        markup    = types.InlineKeyboardMarkup(row_width=1)
        wf_map    = {}
        for wf in workflows:
            wf_map[str(wf.id)] = wf.name
            icon = "🟢" if wf.state == "active" else "🔴"
            markup.add(types.InlineKeyboardButton(
                f"{icon} {wf.name} — ▶️ تشغيل",
                callback_data=f"run_wf_{wf.id}"))
        user_steps[chat_id]['wf_map'] = wf_map
        markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data=f"sel_{abs(hash(repo_name))%100000}"))
        markup.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        text = (f"⚡ Workflows في {repo_name}:" if workflows else f"ℹ️ لا يوجد Workflows في {repo_name}.")
        bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        log_error(chat_id, e)
        bot.edit_message_text(f"❌ خطأ: {clean_txt(e)}", chat_id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("run_wf_"))
def run_workflow(call):
    bot.answer_callback_query(call.id, "⏳ جاري التشغيل...")
    chat_id   = call.message.chat.id
    wf_id     = call.data.replace("run_wf_", "")
    repo_name = user_steps.get(chat_id, {}).get('current_repo')
    config    = load_config()
    if not config or not repo_name: return
    try:
        repo   = Github(config['token']).get_repo(f"{config['username']}/{repo_name}")
        branch = repo.default_branch
        url    = (f"https://api.github.com/repos/{config['username']}/{repo_name}"
                  f"/actions/workflows/{wf_id}/dispatches")
        headers = {"Authorization": f"token {config['token']}",
                   "Accept": "application/vnd.github.v3+json"}
        r = requests.post(url, headers=headers, json={"ref": branch}, timeout=30)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("⚡ عرض Workflows", callback_data="cmd_workflows"))
        markup.add(types.InlineKeyboardButton("🏠 الرئيسية",     callback_data="main_menu"))
        wf_name = user_steps.get(chat_id, {}).get('wf_map', {}).get(wf_id, wf_id)
        if r.status_code == 204:
            bot.edit_message_text(f"✅ تم تشغيل {wf_name} على فرع {branch}!",
                                  chat_id, call.message.message_id, reply_markup=markup)
        else:
            err = r.json().get('message', r.text)
            bot.edit_message_text(f"❌ فشل التشغيل: {clean_txt(err)}",
                                  chat_id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        log_error(chat_id, e)
        bot.edit_message_text(f"❌ خطأ: {clean_txt(e)}", chat_id, call.message.message_id)

# ===================== حذف المستودع =====================
@bot.callback_query_handler(func=lambda c: c.data == "cmd_delete_repo")
def confirm_delete_repo(call):
    bot.answer_callback_query(call.id)
    repo_name = user_steps.get(call.message.chat.id, {}).get('current_repo')
    if not repo_name: return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ نعم، احذف", callback_data="execute_delete_repo"),
        types.InlineKeyboardButton("🚫 إلغاء",    callback_data=f"sel_{abs(hash(repo_name))%100000}")
    )
    markup.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
    bot.edit_message_text(
        f"⚠️ تحذير!\nهل أنت متأكد من حذف {repo_name} نهائياً؟\nلا يمكن التراجع!",
        call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "execute_delete_repo")
def execute_delete(call):
    bot.answer_callback_query(call.id)
    repo_name = user_steps.get(call.message.chat.id, {}).get('current_repo')
    config    = load_config()
    try:
        Github(config['token']).get_repo(f"{config['username']}/{repo_name}").delete()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.edit_message_text(f"✅ تم حذف {repo_name} بنجاح.",
                              call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        log_error(call.message.chat.id, e)
        bot.edit_message_text(f"❌ فشل: {clean_txt(e)}", call.message.chat.id, call.message.message_id)

# ===================== إنشاء مشروع / رفع ZIP =====================
@bot.callback_query_handler(func=lambda c: c.data in ["cmd_update_repo", "create_new_repo"])
def ask_for_zip(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    user_steps[chat_id] = user_steps.get(chat_id, {})
    if call.data == "create_new_repo":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📦 رفع ZIP (مشروع جاهز)", callback_data="zip_mode_create"),
            types.InlineKeyboardButton("📭 مستودع فارغ",           callback_data="zip_mode_empty"),
            types.InlineKeyboardButton("🚫 إلغاء",                 callback_data="main_menu")
        )
        bot.edit_message_text("➕ إنشاء مشروع جديد\nاختر طريقة الإنشاء:",
                              chat_id, call.message.message_id, reply_markup=markup)
    else:
        repo_name = user_steps[chat_id].get('current_repo', 'المشروع')
        user_steps[chat_id]['mode'] = 'update'
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
        msg = bot.edit_message_text(
            f"📤 تحديث {repo_name}\n\nأرسل ملف ZIP الآن:\nسيتم رفع جميع الملفات في Commit واحد",
            chat_id, call.message.message_id, reply_markup=markup)
        user_steps[chat_id]['waiting_zip_msg'] = msg.message_id

@bot.callback_query_handler(func=lambda c: c.data == "zip_mode_create")
def zip_mode_create(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    user_steps[chat_id] = user_steps.get(chat_id, {})
    user_steps[chat_id]['mode'] = 'create'
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    msg = bot.edit_message_text(
        "📦 إنشاء من ZIP\n\nأرسل ملف ZIP الآن:\nسيتم رفع جميع الملفات في Commit واحد",
        chat_id, call.message.message_id, reply_markup=markup)
    user_steps[chat_id]['waiting_zip_msg'] = msg.message_id

@bot.callback_query_handler(func=lambda c: c.data == "zip_mode_empty")
def zip_mode_empty(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    user_steps[chat_id] = user_steps.get(chat_id, {})
    user_steps[chat_id]['mode'] = 'create_empty'
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    msg = bot.send_message(chat_id, "📭 أرسل اسم المستودع الجديد:", reply_markup=markup)
    bot.register_next_step_handler(msg, create_empty_repo_step)
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass

def create_empty_repo_step(message):
    chat_id   = message.chat.id
    repo_name = message.text.strip().replace(" ", "-")
    config    = load_config()
    if not config:
        bot.send_message(chat_id, "⚠️ يرجى ضبط الإعدادات أولاً.")
        return
    try:
        repo = Github(config['token']).get_user().create_repo(repo_name, auto_init=True)
        user_steps[chat_id] = user_steps.get(chat_id, {})
        user_steps[chat_id]['current_repo'] = repo_name
        user_steps[chat_id]['mode']         = None
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📤 رفع ZIP لهذا المستودع", callback_data="cmd_update_repo"),
            types.InlineKeyboardButton("🏠 الرئيسية",              callback_data="main_menu"))
        bot.send_message(chat_id, f"✅ تم إنشاء المستودع!\n{repo.html_url}", reply_markup=markup)
    except Exception as e:
        log_error(chat_id, e)
        bot.send_message(chat_id, f"❌ فشل الإنشاء: {clean_txt(e)}")

# ===================== الإعداد =====================
@bot.callback_query_handler(func=lambda c: c.data == "setup_now")
def callback_setup(call):
    bot.answer_callback_query(call.id)
    start_setup(call.message)

@bot.message_handler(commands=['setup'])
def start_setup(message):
    clear_user_state(message.chat.id)
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    bot.register_next_step_handler(
        bot.send_message(message.chat.id,
                         "🔑 أرسل GitHub Token الخاص بك:\nسيتم التحقق منه تلقائياً",
                         reply_markup=markup),
        get_token_step)

def get_token_step(message):
    token_val = message.text.strip()
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    try:
        user = Github(token_val).get_user()
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
        bot.register_next_step_handler(
            bot.send_message(message.chat.id,
                             f"✅ توكن صالح! مرحباً {user.login}\nأرسل اسم المستخدم لتأكيده:",
                             reply_markup=markup),
            lambda m: finish_setup(m, token_val))
    except Exception:
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.send_message(message.chat.id,
                         "❌ التوكن غير صالح.\nحاول مجدداً /setup",
                         reply_markup=markup)

def finish_setup(message, token):
    save_config(token, message.text.strip())
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
    bot.reply_to(message, "✅ تم حفظ الإعدادات بنجاح!", reply_markup=markup)

# ===================== الشطرنج =====================
@bot.callback_query_handler(func=lambda c: c.data == "start_check")
def start_chess_check(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    clear_user_state(chat_id)
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🚫 إلغاء", callback_data="cancel_chess"))
    msg = bot.edit_message_text(
        "♟️ تحليل الشطرنج\n\nالصق نص الـ PGN هنا:",
        chat_id, call.message.message_id, reply_markup=markup)
    awaiting_pgn[chat_id]   = True
    chess_wait_msg[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda c: c.data == "cancel_chess")
def cancel_chess(call):
    bot.answer_callback_query(call.id)
    clear_user_state(call.message.chat.id)
    show_main_menu(call.message.chat.id)

@bot.message_handler(commands=['check'])
def handle_check_command(message):
    clear_user_state(message.chat.id)
    data = message.text.replace('/check', '').strip()
    if data:
        process_chess(message, data)
    else:
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🚫 إلغاء", callback_data="cancel_chess"))
        msg = bot.reply_to(message, "♟️ أرسل نص PGN للتحليل:", reply_markup=markup)
        awaiting_pgn[message.chat.id]   = True
        chess_wait_msg[message.chat.id] = msg.message_id

@bot.message_handler(func=lambda m: awaiting_pgn.get(m.chat.id, False) and m.text)
def receive_pgn(message):
    chat_id = message.chat.id
    awaiting_pgn.pop(chat_id, None)
    wid = chess_wait_msg.pop(chat_id, None)
    if wid:
        try: bot.delete_message(chat_id, wid)
        except: pass
    process_chess(message, message.text)

def process_chess(message, pgn_data):
    """
    FIX: جميع الرسائل بدون parse_mode لأن نقلات الشطرنج
    تحتوي على + و # و * تكسر Markdown
    """
    msg_wait = None
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_data))
        if not game:
            return bot.reply_to(message, "❌ PGN غير صالح.")

        white = game.headers.get("White", "White")
        black = game.headers.get("Black", "Black")
        event = game.headers.get("Event", "")
        date  = game.headers.get("Date",  "")

        msg_wait = bot.reply_to(message, f"⏳ جاري تحليل مباراة:\n⚪ {white} vs ⚫ {black}...")
        w_losses, b_losses, moments = [], [], []
        ply = 0
        clf = {"brilliant": 0, "best": 0, "blunder": 0, "mistake": 0, "inaccuracy": 0}

        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            graph_buf = generate_eval_graph(game, engine)
            board = game.board()
            for move in game.mainline_moves():
                ply += 1
                move_number   = (ply + 1) // 2
                is_white_turn = (board.turn == chess.WHITE)
                player = white if is_white_turn else black
                icon   = "⚪" if is_white_turn else "⚫"

                info       = engine.analyse(board, chess.engine.Limit(depth=14))
                best_score = info["score"].relative.score(mate_score=1000)
                best_move  = info.get("pv", [None])[0]
                try:    best_san = board.san(best_move) if best_move else "غير متاح"
                except: best_san = "غير متاح"
                try:    move_san = board.san(move)
                except: move_san = str(move)

                is_brilliant = False
                if best_move and move == best_move:
                    val = {chess.PAWN:1, chess.KNIGHT:3, chess.BISHOP:3,
                           chess.ROOK:5, chess.QUEEN:9}
                    mat_before = sum(len(board.pieces(pt, board.turn)) * v for pt, v in val.items())
                    board.push(move)
                    mat_after  = sum(len(board.pieces(pt, not board.turn)) * v for pt, v in val.items())
                    if mat_after < mat_before - 2: is_brilliant = True
                    clf["best"] += 1
                else:
                    board.push(move)

                post         = engine.analyse(board, chess.engine.Limit(depth=10))
                played_score = -post["score"].relative.score(mate_score=1000)
                loss         = max(0, best_score - played_score)

                if is_white_turn: w_losses.append(loss)
                else:             b_losses.append(loss)

                if is_brilliant:
                    clf["brilliant"] += 1
                    moments.append(f"{icon} نقلة {move_number} | {player} | ✨ Brilliant!!\n   لعب: {move_san}")
                elif loss > 400:
                    clf["blunder"] += 1
                    moments.append(f"{icon} نقلة {move_number} | {player} | ❌ Blunder ??\n   لعب: {move_san}  /  الأفضل: {best_san}")
                elif loss > 200:
                    clf["mistake"] += 1
                    moments.append(f"{icon} نقلة {move_number} | {player} | ⚠️ Mistake ?\n   لعب: {move_san}  /  الأفضل: {best_san}")
                elif loss > 90:
                    clf["inaccuracy"] += 1
                    if len(moments) < 12:
                        moments.append(f"{icon} نقلة {move_number} | {player} | 💛 Inaccuracy\n   لعب: {move_san}  /  الأفضل: {best_san}")

        w_acc = calculate_accuracy(w_losses)
        b_acc = calculate_accuracy(b_losses)
        w_elo = get_estimated_elo(w_acc)
        b_elo = get_estimated_elo(b_acc)
        header = f"📅 {event}  |  {date}" if (event or date) else ""

        res = (
            f"♟️ التقرير النهائي\n"
            + (f"{header}\n" if header else "")
            + f"\n"
            f"⚪ {white}\n"
            f"{acc_bar(w_acc)}  |  ELO ~{w_elo}\n\n"
            f"⚫ {black}\n"
            f"{acc_bar(b_acc)}  |  ELO ~{b_elo}\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"✨ Brilliant: {clf['brilliant']}   ✅ Best: {clf['best']}\n"
            f"❌ Blunder: {clf['blunder']}   ⚠️ Mistake: {clf['mistake']}\n"
            f"💛 Inaccuracy: {clf['inaccuracy']}\n"
            f"━━━━━━━━━━━━━━\n"
        )
        if moments:
            res += "🎯 أبرز اللحظات:\n\n" + "\n\n".join(moments[:8])

        try: bot.delete_message(message.chat.id, msg_wait.message_id)
        except: pass
        if graph_buf:
            bot.send_photo(message.chat.id, graph_buf, caption="📈 رسم تقييم المباراة")
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        send_long_message(message.chat.id, res, reply_markup=markup)

    except Exception as e:
        log_error(message.chat.id, e)
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        err_text = f"❌ خطأ: {clean_txt(str(e))}"
        if msg_wait:
            try:    bot.edit_message_text(err_text, message.chat.id, msg_wait.message_id, reply_markup=markup)
            except: bot.send_message(message.chat.id, err_text, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, err_text, reply_markup=markup)

# ===================== سجل الأخطاء =====================
@bot.message_handler(commands=['logs'])
def show_logs(message):
    if not error_logs:
        bot.reply_to(message, "✅ لا توجد أخطاء مسجلة.")
        return
    send_long_message(message.chat.id,
        "🔴 آخر الأخطاء:\n\n" + "\n".join(f"• {l}" for l in reversed(error_logs)))

# ===================== Flask =====================
@app.route('/')
def home():
    return f"Bot is alive! Uptime: {str(datetime.now()-start_time).split('.')[0]}"

@app.route('/health')
def health():
    return {"status": "ok", "uptime": str(datetime.now()-start_time).split('.')[0]}

def run_flask():
    app.run(host='0.0.0.0', port=10000)

# ===================== بدء التشغيل =====================
if __name__ == "__main__":
    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as e:
            e.analyse(chess.Board(), chess.engine.Limit(depth=2))
        logger.info("✅ Stockfish يعمل.")
    except Exception as e:
        logger.critical(f"❌ فشل Stockfish: {e}")
        exit(1)
    setup_commands()
    Thread(target=run_flask, daemon=True).start()
    logger.info("🤖 البوت يعمل...")
    bot.infinity_polling(timeout=90, long_polling_timeout=90,
                         allowed_updates=["message", "callback_query"])
