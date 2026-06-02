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

TOKEN          = os.environ.get('TELEGRAM_TOKEN')
apihelper.READ_TIMEOUT    = 120
apihelper.CONNECT_TIMEOUT = 120
CONFIG_FILE    = "config.json"
STOCKFISH_PATH = "/usr/games/stockfish"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_steps     = {}
awaiting_pgn   = {}
chess_wait_msg = {}
error_logs     = []
start_time     = datetime.now()

# ───────────────────────── أوامر البوت ─────────────────────────
def setup_commands():
    try:
        bot.set_my_commands([
            types.BotCommand("start",  "القائمة الرئيسية"),
            types.BotCommand("help",   "مساعدة"),
            types.BotCommand("check",  "تحليل شطرنج"),
            types.BotCommand("setup",  "ضبط GitHub"),
            types.BotCommand("logs",   "سجل الأخطاء"),
            types.BotCommand("status", "حالة البوت"),
        ])
    except Exception as e:
        logger.error(f"فشل تعيين الأوامر: {e}")

# ───────────────────────── إعدادات ─────────────────────────
def save_config(token, username):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({"token": token, "username": username}, f)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def clean_txt(text):
    return str(text).replace('`',"'").replace('*','').replace('_','').replace('[','(').replace(']',')')

def is_sha_str(s):
    """هل النص SHA hex؟"""
    s = str(s).strip()
    return len(s) >= 20 and all(c in '0123456789abcdefABCDEF' for c in s)

def safe_err(e):
    """تحويل أي استثناء لرسالة مقروءة - يمنع ظهور SHA أو بيانات تقنية"""
    try:
        # GithubException
        if hasattr(e, 'status') and hasattr(e, 'data'):
            if isinstance(e.data, dict):
                msg = e.data.get('message') or e.data.get('error') or ''
                if msg and not is_sha_str(msg):
                    return f"خطأ GitHub {e.status}: {msg}"
            return f"خطأ GitHub {e.status}"
        s = str(e).strip()
        if is_sha_str(s):
            return "خطأ في GitHub API"
        if len(s) > 150:
            return s[:150] + "..."
        return s or "خطأ غير معروف"
    except:
        return "خطأ غير معروف"

def log_error(chat_id, err):
    """تسجيل الأخطاء - يستخدم safe_err لمنع تسجيل SHA"""
    entry = f"{datetime.now().strftime('%H:%M:%S')} | {chat_id} | {safe_err(err)}"
    error_logs.append(entry)
    if len(error_logs) > 20: error_logs.pop(0)
    logger.error(entry)

def clear_user_state(chat_id):
    repo_map = user_steps.get(chat_id, {}).get('repo_map')
    wf_map   = user_steps.get(chat_id, {}).get('wf_map')
    current  = user_steps.get(chat_id, {}).get('current_repo')
    user_steps.pop(chat_id, None)
    awaiting_pgn.pop(chat_id, None)
    chess_wait_msg.pop(chat_id, None)
    p = {}
    if repo_map: p['repo_map']     = repo_map
    if wf_map:   p['wf_map']       = wf_map
    if current:  p['current_repo'] = current
    if p:        user_steps[chat_id] = p

def send_long(chat_id, text, markup=None):
    MAX = 4000
    if len(text) <= MAX:
        bot.send_message(chat_id, text, reply_markup=markup)
        return
    parts, buf = [], text
    while len(buf) > MAX:
        idx = buf.rfind('\n', 0, MAX)
        if idx == -1: idx = MAX
        parts.append(buf[:idx]); buf = buf[idx:].lstrip('\n')
    parts.append(buf)
    for i, p in enumerate(parts):
        bot.send_message(chat_id, p, reply_markup=markup if i == len(parts)-1 else None)

# ───────────────────────── شطرنج helpers ─────────────────────────
def get_elo(acc):
    if acc >= 99: return 2800
    if acc >= 95: return 2200 + int((acc-95)*120)
    if acc >= 90: return 1800 + int((acc-90)*80)
    if acc >= 80: return 1300 + int((acc-80)*50)
    if acc >= 70: return 900  + int((acc-70)*40)
    if acc >= 55: return 500  + int((acc-55)*26)
    return max(100, int(acc*7))

def calc_accuracy(losses):
    if not losses: return 100.0
    avg = sum(losses)/len(losses)
    return round(max(0.0, min(100.0, 103.1668*math.exp(-0.04354*math.sqrt(avg))-3.1668)), 1)

def acc_bar(acc):
    f = int(acc/10)
    return "█"*f + "░"*(10-f) + f" {acc}%"

def draw_eval_graph(game, engine):
    if not MATPLOTLIB_AVAILABLE: return None
    try:
        board, scores = game.board(), []
        for mv in game.mainline_moves():
            info = engine.analyse(board, chess.engine.Limit(depth=10))
            s = info["score"].relative.score(mate_score=10000)
            scores.append(max(-1000, min(1000, s/100.0)))
            board.push(mv)
        fig, ax = plt.subplots(figsize=(9,4))
        ax.fill_between(range(1,len(scores)+1), scores, 0, where=[s>0 for s in scores], color='white', alpha=0.6)
        ax.fill_between(range(1,len(scores)+1), scores, 0, where=[s<0 for s in scores], color='gray',  alpha=0.6)
        ax.plot(range(1,len(scores)+1), scores, color='black', linewidth=1.2)
        ax.axhline(0, color='black', linewidth=1.0)
        ax.set_title('تقييم المباراة', fontsize=13)
        ax.set_xlabel('رقم النقلة'); ax.set_ylabel('التقييم (بيدق)')
        ax.grid(True, alpha=0.2); ax.set_ylim(-12,12)
        plt.tight_layout()
        buf = io.BytesIO(); plt.savefig(buf, format='png', dpi=110); buf.seek(0); plt.close()
        return buf
    except Exception as e:
        logger.warning(f"فشل الرسم: {e}"); return None

# ───────────────────────── القائمة الرئيسية ─────────────────────────
@bot.message_handler(commands=['start'])
def cmd_start(message):
    clear_user_state(message.chat.id)
    show_main_menu(message.chat.id)

def show_main_menu(chat_id):
    clear_user_state(chat_id)
    config = load_config()
    status = f"متصل: {config['username']}" if config else "غير متصل بـ GitHub"
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        types.InlineKeyboardButton("📁 مشاريعي",      callback_data="my_projects"),
        types.InlineKeyboardButton("➕ مشروع جديد",   callback_data="create_new_repo"),
        types.InlineKeyboardButton("📊 إحصائيات",     callback_data="account_info"),
        types.InlineKeyboardButton("♟️ تحليل شطرنج", callback_data="start_check"),
        types.InlineKeyboardButton("⚙️ الإعدادات",    callback_data="setup_now"),
        types.InlineKeyboardButton("❓ مساعدة",        callback_data="help_menu"),
    )
    mk.add(types.InlineKeyboardButton("📈 حالة البوت", callback_data="bot_status"))
    bot.send_message(chat_id, f"🤖 مدير المشاريع السحابي\n\n✅ {status}\n\nاختر من القائمة:", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "main_menu")
def cb_main(call):
    bot.answer_callback_query(call.id)
    clear_user_state(call.message.chat.id)
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
    show_main_menu(call.message.chat.id)

# ───────────────────────── مساعدة ─────────────────────────
@bot.message_handler(commands=['help'])
def cmd_help(msg): show_help(msg.chat.id, None)

@bot.callback_query_handler(func=lambda c: c.data == "help_menu")
def cb_help(call):
    bot.answer_callback_query(call.id)
    show_help(call.message.chat.id, call.message.message_id)

def show_help(chat_id, mid):
    txt = (
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
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
    if mid:
        try:    bot.edit_message_text(txt, chat_id, mid, reply_markup=mk)
        except: bot.send_message(chat_id, txt, reply_markup=mk)
    else:
        bot.send_message(chat_id, txt, reply_markup=mk)

# ───────────────────────── حالة البوت ─────────────────────────
@bot.message_handler(commands=['status'])
def cmd_status(msg): show_status(msg.chat.id, None)

@bot.callback_query_handler(func=lambda c: c.data == "bot_status")
def cb_status(call):
    bot.answer_callback_query(call.id)
    show_status(call.message.chat.id, call.message.message_id)

def show_status(chat_id, mid):
    up = datetime.now() - start_time
    h, r = divmod(int(up.total_seconds()), 3600); m, s = divmod(r, 60)
    config = load_config()
    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as e:
            e.analyse(chess.Board(), chess.engine.Limit(depth=1))
        sf = "✅ يعمل"
    except: sf = "❌ متوقف"
    txt = (
        f"📈 حالة البوت:\n\n"
        f"⏱️ وقت التشغيل: {h}h {m}m {s}s\n"
        f"🐙 GitHub: {'✅ متصل' if config else '❌ غير متصل'}\n"
        f"♟️ Stockfish: {sf}\n"
        f"🔴 أخطاء: {len(error_logs)}\n"
        f"👥 جلسات نشطة: {len(user_steps)}\n"
    )
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
    if mid:
        try:    bot.edit_message_text(txt, chat_id, mid, reply_markup=mk)
        except: bot.send_message(chat_id, txt, reply_markup=mk)
    else:
        bot.send_message(chat_id, txt, reply_markup=mk)

# ───────────────────────── إحصائيات GitHub ─────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "account_info")
def cb_account(call):
    bot.answer_callback_query(call.id)
    cid, mid = call.message.chat.id, call.message.message_id
    config = load_config()
    if not config:
        bot.edit_message_text("⚠️ يرجى ضبط الإعدادات أولاً.", cid, mid); return
    bot.edit_message_text("⏳ جاري جلب بيانات حسابك...", cid, mid)
    try:
        g    = Github(config['token'])
        user = g.get_user()
        repos = list(user.get_repos())
        stars = sum(r.stargazers_count for r in repos)
        forks = sum(r.forks_count for r in repos)
        langs = {}
        for r in repos[:20]:
            try:
                for l, b in r.get_languages().items(): langs[l] = langs.get(l,0)+b
            except: pass
        top = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:3]
        ls  = " | ".join(l[0] for l in top) if top else "غير محدد"
        try:
            rl = g.get_rate_limit()
            if   hasattr(rl,'core'): api = f"🔑 API: {rl.core.remaining}/{rl.core.limit}"
            elif hasattr(rl,'rate'): api = f"🔑 API: {rl.rate.remaining}/{rl.rate.limit}"
            else:                    api = "🔑 API: متصل"
        except: api = "🔑 API: متصل"
        txt = (
            f"👤 معلومات GitHub:\n\n"
            f"الاسم: {user.name or user.login}\n"
            f"المستخدم: {user.login}\n"
            f"البريد: {user.email or 'مخفي'}\n"
            f"الموقع: {user.location or 'غير محدد'}\n\n"
            f"📦 المستودعات: {user.public_repos} عامة\n"
            f"⭐ إجمالي النجوم: {stars}\n"
            f"🍴 إجمالي الفورك: {forks}\n"
            f"👥 المتابعون: {user.followers} | يتابع: {user.following}\n\n"
            f"💻 أبرز اللغات: {ls}\n\n{api}"
        )
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.edit_message_text(txt, cid, mid, reply_markup=mk)
    except Exception as e:
        log_error(cid, e); bot.edit_message_text(f"❌ خطأ: {safe_err(e)}", cid, mid)

# ───────────────────────── قائمة المشاريع ─────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "my_projects")
def cb_projects(call):
    bot.answer_callback_query(call.id)
    cid, mid = call.message.chat.id, call.message.message_id
    config = load_config()
    if not config:
        bot.edit_message_text("⚠️ يرجى ضبط الإعدادات أولاً.", cid, mid); return
    bot.edit_message_text("⏳ جاري جلب مشاريعك...", cid, mid)
    try:
        repos = list(Github(config['token']).get_user().get_repos(sort="updated"))
        mk = types.InlineKeyboardMarkup(row_width=1)
        rmap = {}
        for repo in repos[:25]:
            vis = "🔒" if repo.private else "🌐"
            cb  = f"sel_{abs(hash(repo.name))%100000}"
            rmap[cb] = repo.name
            mk.add(types.InlineKeyboardButton(f"{vis} {repo.name}  ⭐{repo.stargazers_count}", callback_data=cb))
        mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        user_steps[cid] = user_steps.get(cid, {})
        user_steps[cid]['repo_map'] = rmap
        bot.edit_message_text(f"📁 مشاريعك ({len(repos)} مستودع) - مرتبة حسب آخر تحديث:", cid, mid, reply_markup=mk)
    except Exception as e:
        log_error(cid, e); bot.edit_message_text(f"❌ خطأ: {safe_err(e)}", cid, mid)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sel_"))
def cb_repo_selected(call):
    bot.answer_callback_query(call.id)
    cid  = call.message.chat.id
    rmap = user_steps.get(cid, {}).get('repo_map', {})
    name = rmap.get(call.data)
    if not name:
        bot.edit_message_text("❌ حدث خطأ، حاول مجدداً.", cid, call.message.message_id); return
    config = load_config()
    user_steps[cid] = user_steps.get(cid, {})
    user_steps[cid]['current_repo'] = name
    user_steps[cid]['repo_map']     = rmap
    try:
        repo = Github(config['token']).get_repo(f"{config['username']}/{name}")
        vis  = "🔒 خاص" if repo.private else "🌐 عام"
        info = (
            f"📦 {name}\n{repo.description or 'لا يوجد وصف'}\n\n"
            f"الحالة: {vis}\nاللغة: {repo.language or 'غير محدد'}\n"
            f"⭐ {repo.stargazers_count} | 🍴 {repo.forks_count}\nالفرع: {repo.default_branch}"
        )
    except: info = f"📦 {name}"
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        types.InlineKeyboardButton("📤 رفع ZIP",      callback_data="cmd_update_repo"),
        types.InlineKeyboardButton("🔄 استبدال ملف", callback_data="cmd_replace_file"),
        types.InlineKeyboardButton("⚡ Workflows",    callback_data="cmd_workflows"),
        types.InlineKeyboardButton("📄 الملفات",      callback_data="cmd_browse_files"),
        types.InlineKeyboardButton("⚙️ إعدادات",     callback_data="cmd_repo_settings"),
        types.InlineKeyboardButton("🗑️ حذف",          callback_data="cmd_delete_repo"),
        types.InlineKeyboardButton("🔙 رجوع",         callback_data="my_projects"),
        types.InlineKeyboardButton("🏠 الرئيسية",     callback_data="main_menu"),
    )
    bot.edit_message_text(info, cid, call.message.message_id, reply_markup=mk)

# ───────────────────────── استعراض الملفات ─────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "cmd_browse_files")
def cb_browse(call):
    bot.answer_callback_query(call.id)
    cid, mid = call.message.chat.id, call.message.message_id
    name   = user_steps.get(cid, {}).get('current_repo')
    config = load_config()
    if not config or not name:
        bot.edit_message_text("❌ خطأ في البيانات.", cid, mid); return
    bot.edit_message_text("⏳ جاري جلب الملفات...", cid, mid)
    try:
        repo = Github(config['token']).get_repo(f"{config['username']}/{name}")
        try:
            contents = repo.get_contents("")
            if not isinstance(contents, list): contents = [contents]
            lines = []
            for item in contents[:30]:
                if item.type == "dir": lines.append(f"📁 {item.name}/")
                else:
                    sz = f"{item.size//1024}KB" if item.size > 1024 else f"{item.size}B"
                    lines.append(f"📄 {item.name}  ({sz})")
            txt = f"📂 ملفات {name}:\n\n" + "\n".join(lines)
        except GithubException as ge:
            if ge.status == 404 or (isinstance(ge.data,dict) and "empty" in ge.data.get("message","").lower()):
                txt = f"📂 المستودع {name} فارغ.\nارفع ملفات عبر ZIP لتهيئته."
            else: raise ge
        mk = types.InlineKeyboardMarkup(row_width=1)
        mk.add(
            types.InlineKeyboardButton("🌐 فتح في GitHub", url=repo.html_url),
            types.InlineKeyboardButton("🔙 رجوع", callback_data=f"sel_{abs(hash(name))%100000}"),
            types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"),
        )
        bot.edit_message_text(txt, cid, mid, reply_markup=mk)
    except Exception as e:
        log_error(cid, e); bot.edit_message_text(f"❌ خطأ: {safe_err(e)}", cid, mid)

# ───────────────────────── استبدال ملف واحد ─────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "cmd_replace_file")
def cb_replace_file(call):
    bot.answer_callback_query(call.id)
    cid  = call.message.chat.id
    name = user_steps.get(cid, {}).get('current_repo')
    if not name: return
    user_steps[cid]['mode'] = 'replace_file'
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    msg = bot.edit_message_text(
        f"🔄 استبدال ملف في: {name}\n\n"
        "أرسل الملف الجديد الآن.\n"
        "يجب أن يكون اسمه مطابقاً تماماً للملف الموجود في المستودع.\n"
        "سيتم البحث عنه في جميع المجلدات واستبداله تلقائياً.",
        cid, call.message.message_id, reply_markup=mk)
    user_steps[cid]['waiting_replace_msg'] = msg.message_id

def search_recursive(repo, target, path=""):
    try:
        items = repo.get_contents(path)
        if not isinstance(items, list): items = [items]
        for item in items:
            if item.type == "dir":
                r = search_recursive(repo, target, item.path)
                if r: return r
            elif item.name == target:
                return {"path": item.path, "sha": item.sha}
    except: pass
    return None

# ───────────────────────── معالج الملفات الموحد ─────────────────────────
@bot.message_handler(content_types=['document'])
def handle_document(message):
    cid  = message.chat.id
    mode = user_steps.get(cid, {}).get('mode')
    if   mode == 'replace_file':      do_replace_file(message)
    elif mode in ('update', 'create'): do_zip(message)

# ─── استبدال ملف ───
def do_replace_file(message):
    cid    = message.chat.id
    config = load_config()
    name   = user_steps.get(cid, {}).get('current_repo')
    fname  = message.document.file_name or ""
    if not config or not name or not fname:
        bot.reply_to(message, "❌ خطأ في البيانات."); return
    wid = user_steps[cid].pop('waiting_replace_msg', None)
    if wid:
        try: bot.delete_message(cid, wid)
        except: pass
    pmsg = bot.reply_to(message, f"🔍 جاري البحث عن '{fname}' في {name}...")
    try:
        fbytes = bot.download_file(bot.get_file(message.document.file_id).file_path)
    except Exception as e:
        log_error(cid, e)
        bot.edit_message_text(f"❌ فشل تحميل الملف: {safe_err(e)}", cid, pmsg.message_id)
        user_steps[cid]['mode'] = None; return
    try:
        repo  = Github(config['token']).get_repo(f"{config['username']}/{name}")
        found = search_recursive(repo, fname)
        if not found:
            mk = types.InlineKeyboardMarkup(row_width=1)
            mk.add(
                types.InlineKeyboardButton("📤 رفع عبر ZIP",    callback_data="cmd_update_repo"),
                types.InlineKeyboardButton("🔙 رجوع",           callback_data=f"sel_{abs(hash(name))%100000}"),
                types.InlineKeyboardButton("🏠 الرئيسية",       callback_data="main_menu"),
            )
            bot.edit_message_text(
                f"❌ لم يُعثر على ملف باسم: {fname}\n\n"
                "تأكد أن الاسم مطابق تماماً (الامتداد + الحروف الكبيرة/الصغيرة).",
                cid, pmsg.message_id, reply_markup=mk)
            user_steps[cid]['mode'] = None; return
        bot.edit_message_text(f"✅ وُجد الملف في: {found['path']}\n⏳ جاري الاستبدال...", cid, pmsg.message_id)
        # تحديد المحتوى: نصي أو ثنائي
        try:
            content = fbytes.decode('utf-8')
        except (UnicodeDecodeError, ValueError):
            content = base64.b64encode(fbytes).decode('ascii')
        repo.update_file(
            path=found['path'],
            message=f"استبدال {fname} عبر البوت",
            content=content,
            sha=found['sha'])
        mk = types.InlineKeyboardMarkup(row_width=1)
        mk.add(
            types.InlineKeyboardButton("🌐 فتح المستودع",     url=repo.html_url),
            types.InlineKeyboardButton("🔄 استبدال ملف آخر", callback_data="cmd_replace_file"),
            types.InlineKeyboardButton("🏠 الرئيسية",         callback_data="main_menu"),
        )
        bot.edit_message_text(
            f"✅ تم الاستبدال بنجاح!\n\nالملف: {fname}\nالمسار: {found['path']}\nالمستودع: {name}",
            cid, pmsg.message_id, reply_markup=mk)
    except GithubException as ge:
        log_error(cid, ge)
        m = ge.data.get('message', str(ge)) if isinstance(ge.data, dict) else str(ge)
        bot.edit_message_text(f"❌ خطأ GitHub: {clean_txt(m)}", cid, pmsg.message_id)
    except Exception as e:
        log_error(cid, e)
        bot.edit_message_text(f"❌ خطأ: {safe_err(e)}", cid, pmsg.message_id)
    finally:
        user_steps[cid]['mode'] = None

# ─── رفع ZIP ───
def do_zip(message):
    cid    = message.chat.id
    config = load_config()
    mode   = user_steps.get(cid, {}).get('mode')
    if not config:
        bot.reply_to(message, "⚠️ يرجى ضبط إعدادات GitHub أولاً عبر /setup"); return
    fname = message.document.file_name or ""
    if not fname.lower().endswith('.zip'):
        bot.reply_to(message, "⚠️ يرجى إرسال ملف ZIP فقط."); return
    wid = user_steps[cid].pop('waiting_zip_msg', None)
    if wid:
        try: bot.delete_message(cid, wid)
        except: pass
    if message.document.file_size > 50 * 1024 * 1024:
        bot.reply_to(message, "❌ حجم الملف يتجاوز 50MB."); return
    pmsg = bot.reply_to(message, "⏳ جاري تحميل الملف...")
    try:
        zbytes = bot.download_file(bot.get_file(message.document.file_id).file_path)
    except Exception as e:
        log_error(cid, e)
        bot.edit_message_text(f"❌ فشل التحميل: {safe_err(e)}", cid, pmsg.message_id); return
    if mode == 'update':
        rname = user_steps[cid].get('current_repo')
        if not rname:
            bot.edit_message_text("❌ لم يتم تحديد المستودع.", cid, pmsg.message_id); return
        try:
            repo = Github(config['token']).get_repo(f"{config['username']}/{rname}")
            bot.edit_message_text("📊 جاري معالجة الملفات...", cid, pmsg.message_id)
            extract_and_upload(repo, zbytes, cid, pmsg.message_id)
        except Exception as e:
            log_error(cid, e)
            bot.edit_message_text(f"❌ خطأ: {safe_err(e)}", cid, pmsg.message_id)
        finally:
            user_steps[cid]['mode'] = None
    elif mode == 'create':
        user_steps[cid]['file']            = zbytes
        user_steps[cid]['progress_msg_id'] = pmsg.message_id
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
        bot.edit_message_text("✅ تم استلام الملف!\nأرسل اسم المستودع الجديد:", cid, pmsg.message_id, reply_markup=mk)
        bot.register_next_step_handler_by_chat_id(cid, finalize_create)

def finalize_create(message):
    cid    = message.chat.id
    rname  = message.text.strip().replace(" ", "-")
    config = load_config()
    pmid   = user_steps.get(cid, {}).get('progress_msg_id')
    zbytes = user_steps.get(cid, {}).get('file')
    if not zbytes or not config:
        bot.reply_to(message, "❌ حدث خطأ، ابدأ من جديد."); return
    try:    bot.edit_message_text("⏳ جاري إنشاء المستودع...", cid, pmid)
    except: pmid = bot.send_message(cid, "⏳ جاري الإنشاء...").message_id
    try:
        repo = Github(config['token']).get_user().create_repo(rname)
        user_steps[cid]['current_repo'] = rname
        extract_and_upload(repo, zbytes, cid, pmid)
    except Exception as e:
        log_error(cid, e)
        try:    bot.edit_message_text(f"❌ فشل: {safe_err(e)}", cid, pmid)
        except: bot.send_message(cid, f"❌ فشل: {safe_err(e)}")
    finally:
        user_steps[cid]['mode'] = None
        user_steps[cid].pop('file', None)

# ───────────────────────── رفع ZIP - Commit واحد ─────────────────────────
def extract_and_upload(repo, zip_bytes, chat_id, progress_msg_id=None):
    def upd(txt):
        if progress_msg_id:
            try: bot.edit_message_text(txt, chat_id, progress_msg_id)
            except: pass

    def gh_err_msg(ge):
        """استخراج رسالة خطأ GitHub - يمنع إرجاع SHA كرسالة"""
        try:
            if isinstance(ge.data, dict):
                msg = ge.data.get('message') or ge.data.get('error') or ''
                if msg and not is_sha(msg):
                    return msg
            # أي شيء يبدو SHA نتجاهله
            return f"خطأ {getattr(ge, 'status', 'GitHub')}"
        except:
            return "خطأ غير معروف"

    def is_sha(s):
        """هل النص SHA hex؟"""
        s = str(s).strip()
        return len(s) >= 20 and all(c in '0123456789abcdefABCDEF' for c in s)

    try:
        if not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
            upd("❌ الملف المرسل ليس ZIP صالحاً!"); return

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            # تصفية الملفات غير المرغوبة
            all_files = [
                f for f in z.infolist()
                if not f.is_dir()
                and not f.filename.startswith('__MACOSX')
                and '.DS_Store' not in f.filename
                and not f.filename.endswith('/')
                and f.file_size > 0
            ]
            total = len(all_files)
            if total == 0:
                upd("⚠️ الملف المضغوط فارغ من الملفات الصالحة!"); return

            upd(f"📊 تم اكتشاف {total} ملف\nجاري إعداد الـ Commit...")

            # جلب المرجع الأساسي للفرع
            base_commit, base_tree_sha = None, None
            try:
                br            = repo.get_branch(repo.default_branch)
                base_commit   = repo.get_git_commit(br.commit.sha)
                base_tree_sha = base_commit.tree.sha
            except Exception:
                pass  # مستودع جديد فارغ - طبيعي

            # كشف المجلد الجذري المشترك وإزالته
            top_dirs = set()
            for fi in all_files:
                parts = fi.filename.split('/')
                if len(parts) > 1:
                    top_dirs.add(parts[0])
            strip = (list(top_dirs)[0] + '/') if len(top_dirs) == 1 else ''

            tree_elements = []
            skipped = binary_count = text_count = 0

            for fi in all_files:
                raw  = fi.filename
                path = raw[len(strip):] if strip and raw.startswith(strip) else raw
                if not path or path.endswith('/'):
                    skipped += 1; continue
                try:
                    data = z.read(fi.filename)
                except Exception:
                    skipped += 1; continue

                # ── محاولة UTF-8 أولاً (نصي) ──
                try:
                    text_str = data.decode('utf-8')
                    tree_elements.append(InputGitTreeElement(
                        path=path, mode='100644', type='blob',
                        content=text_str))
                    text_count += 1

                # ── ثنائي: رفع blob منفصل ثم الإشارة بـ SHA ──
                except (UnicodeDecodeError, ValueError):
                    try:
                        b64  = base64.b64encode(data).decode('ascii')
                        blob = repo.create_git_blob(b64, "base64")
                        # مهم: sha فقط بدون content للملفات الثنائية
                        elem = InputGitTreeElement(
                            path=path, mode='100644', type='blob',
                            sha=blob.sha)
                        tree_elements.append(elem)
                        binary_count += 1
                    except GithubException as be:
                        logger.warning(f"فشل blob {path}: {gh_err_msg(be)}")
                        skipped += 1
                    except Exception as be:
                        logger.warning(f"فشل blob {path}: {be}")
                        skipped += 1

            if not tree_elements:
                upd("❌ لم يتم العثور على ملفات صالحة!"); return

            upd(f"🔗 جاري بناء شجرة Git...\nنصية: {text_count} | ثنائية: {binary_count}")

            # إنشاء الشجرة الجديدة
            new_tree = repo.create_git_tree(tree_elements, base_tree=base_tree_sha)

            upd("💾 جاري إنشاء الـ Commit...")

            # Commit واحد
            parents    = [base_commit] if base_commit else []
            new_commit = repo.create_git_commit(
                message=f"رفع {len(tree_elements)} ملف عبر ZIP",
                tree=new_tree,
                parents=parents)

            # ── تحديث رأس الفرع ──
            default_br = repo.default_branch
            ref_updated = False

            # محاولة 1: تحديث ref موجود
            try:
                git_ref = repo.get_git_ref(f"heads/{default_br}")
                # استخدام requests مباشرة لتجنب مشاكل PyGithub مع edit()
                config_data = load_config()
                patch_url = f"https://api.github.com/repos/{config_data['username']}/{repo.name}/git/refs/heads/{default_br}"
                r = requests.patch(
                    patch_url,
                    headers={
                        "Authorization": f"token {config_data['token']}",
                        "Accept": "application/vnd.github.v3+json"
                    },
                    json={"sha": new_commit.sha, "force": True},
                    timeout=30
                )
                if r.status_code in (200, 201):
                    ref_updated = True
                else:
                    logger.warning(f"PATCH ref failed: {r.status_code} {r.text[:100]}")
            except GithubException as ge:
                if ge.status != 404:
                    logger.warning(f"get_git_ref failed: {ge.status}")

            # محاولة 2: إنشاء ref جديد (مستودع فارغ)
            if not ref_updated:
                try:
                    config_data = load_config()
                    post_url = f"https://api.github.com/repos/{config_data['username']}/{repo.name}/git/refs"
                    r = requests.post(
                        post_url,
                        headers={
                            "Authorization": f"token {config_data['token']}",
                            "Accept": "application/vnd.github.v3+json"
                        },
                        json={"ref": f"refs/heads/{default_br}", "sha": new_commit.sha},
                        timeout=30
                    )
                    if r.status_code in (200, 201):
                        ref_updated = True
                    else:
                        raise Exception(f"فشل إنشاء الفرع: {r.json().get('message', r.status_code)}")
                except Exception as re:
                    raise Exception(f"فشل تحديث الفرع: {re}")

            mk = types.InlineKeyboardMarkup(row_width=1)
            mk.add(
                types.InlineKeyboardButton("🌐 فتح المستودع", url=repo.html_url),
                types.InlineKeyboardButton("🏠 الرئيسية",     callback_data="main_menu"))
            result = (
                f"✅ تم الرفع في Commit واحد!\n\n"
                f"الكلي: {total}  |  مرفوع: {len(tree_elements)}  |  تخطي: {skipped}\n"
                f"نصية: {text_count}  |  ثنائية: {binary_count}\n\n"
                f"{repo.html_url}"
            )
            if progress_msg_id:
                try:
                    bot.edit_message_text(result, chat_id, progress_msg_id)
                    bot.edit_message_reply_markup(chat_id, progress_msg_id, reply_markup=mk)
                except:
                    bot.send_message(chat_id, result, reply_markup=mk)
            else:
                bot.send_message(chat_id, result, reply_markup=mk)

    except zipfile.BadZipFile:
        upd("❌ الملف المرسل ليس ZIP صالحاً!")
    except GithubException as ge:
        log_error(chat_id, ge)
        upd(f"❌ خطأ GitHub ({ge.status}): {gh_err_msg(ge)}")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"extract_and_upload traceback:\n{tb}")
        log_error(chat_id, e)
        upd(f"❌ خطأ أثناء الرفع: {safe_err(e)}")

# ───────────────────────── إنشاء مشروع ─────────────────────────
@bot.callback_query_handler(func=lambda c: c.data in ["cmd_update_repo", "create_new_repo"])
def cb_ask_zip(call):
    bot.answer_callback_query(call.id)
    cid = call.message.chat.id
    user_steps[cid] = user_steps.get(cid, {})
    if call.data == "create_new_repo":
        mk = types.InlineKeyboardMarkup(row_width=1)
        mk.add(
            types.InlineKeyboardButton("📦 رفع ZIP (مشروع جاهز)", callback_data="zip_mode_create"),
            types.InlineKeyboardButton("📭 مستودع فارغ",           callback_data="zip_mode_empty"),
            types.InlineKeyboardButton("🚫 إلغاء",                 callback_data="main_menu"),
        )
        bot.edit_message_text("➕ إنشاء مشروع جديد\nاختر طريقة الإنشاء:",
                              cid, call.message.message_id, reply_markup=mk)
    else:
        rname = user_steps[cid].get('current_repo', 'المشروع')
        user_steps[cid]['mode'] = 'update'
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
        msg = bot.edit_message_text(
            f"📤 تحديث {rname}\n\nأرسل ملف ZIP الآن:\nسيتم رفع جميع الملفات في Commit واحد",
            cid, call.message.message_id, reply_markup=mk)
        user_steps[cid]['waiting_zip_msg'] = msg.message_id

@bot.callback_query_handler(func=lambda c: c.data == "zip_mode_create")
def cb_zip_create(call):
    bot.answer_callback_query(call.id)
    cid = call.message.chat.id
    user_steps[cid] = user_steps.get(cid, {})
    user_steps[cid]['mode'] = 'create'
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    msg = bot.edit_message_text(
        "📦 إنشاء من ZIP\n\nأرسل ملف ZIP الآن:\nسيتم رفع جميع الملفات في Commit واحد",
        cid, call.message.message_id, reply_markup=mk)
    user_steps[cid]['waiting_zip_msg'] = msg.message_id

@bot.callback_query_handler(func=lambda c: c.data == "zip_mode_empty")
def cb_zip_empty(call):
    bot.answer_callback_query(call.id)
    cid = call.message.chat.id
    user_steps[cid] = user_steps.get(cid, {})
    user_steps[cid]['mode'] = 'create_empty'
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    msg = bot.send_message(cid, "📭 أرسل اسم المستودع الجديد:", reply_markup=mk)
    bot.register_next_step_handler(msg, step_empty_repo)
    try: bot.delete_message(cid, call.message.message_id)
    except: pass

def step_empty_repo(message):
    cid, rname = message.chat.id, message.text.strip().replace(" ", "-")
    config = load_config()
    if not config:
        bot.send_message(cid, "⚠️ يرجى ضبط الإعدادات أولاً."); return
    try:
        repo = Github(config['token']).get_user().create_repo(rname, auto_init=True)
        user_steps[cid] = user_steps.get(cid, {})
        user_steps[cid]['current_repo'] = rname
        user_steps[cid]['mode']         = None
        mk = types.InlineKeyboardMarkup(row_width=1)
        mk.add(
            types.InlineKeyboardButton("📤 رفع ZIP لهذا المستودع", callback_data="cmd_update_repo"),
            types.InlineKeyboardButton("🏠 الرئيسية",              callback_data="main_menu"))
        bot.send_message(cid, f"✅ تم إنشاء المستودع!\n{repo.html_url}", reply_markup=mk)
    except Exception as e:
        log_error(cid, e); bot.send_message(cid, f"❌ فشل الإنشاء: {safe_err(e)}")

# ───────────────────────── إعدادات المستودع ─────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "cmd_repo_settings")
def cb_settings(call):
    bot.answer_callback_query(call.id)
    cid, mid = call.message.chat.id, call.message.message_id
    name = user_steps.get(cid, {}).get('current_repo')
    if not name: return
    mk = types.InlineKeyboardMarkup(row_width=1)
    mk.add(
        types.InlineKeyboardButton("✏️ تغيير الاسم",     callback_data="cmd_rename_repo"),
        types.InlineKeyboardButton("📝 تغيير الوصف",     callback_data="cmd_change_desc"),
        types.InlineKeyboardButton("🔐 تبديل الخصوصية", callback_data="cmd_toggle_vis"),
        types.InlineKeyboardButton("🔙 رجوع",            callback_data=f"sel_{abs(hash(name))%100000}"),
        types.InlineKeyboardButton("🏠 الرئيسية",        callback_data="main_menu"),
    )
    bot.edit_message_text(f"⚙️ إعدادات {name}:", cid, mid, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "cmd_rename_repo")
def cb_rename(call):
    bot.answer_callback_query(call.id)
    cid  = call.message.chat.id
    name = user_steps.get(cid, {}).get('current_repo')
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    msg = bot.send_message(cid, f"✏️ أرسل الاسم الجديد للمستودع {name}:", reply_markup=mk)
    bot.register_next_step_handler(msg, step_rename)
    try: bot.delete_message(cid, call.message.message_id)
    except: pass

def step_rename(message):
    cid, new = message.chat.id, message.text.strip().replace(" ", "-")
    old = user_steps.get(cid, {}).get('current_repo')
    config = load_config()
    try:
        Github(config['token']).get_repo(f"{config['username']}/{old}").edit(name=new)
        user_steps[cid]['current_repo'] = new
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.reply_to(message, f"✅ تم إعادة التسمية إلى: {new}", reply_markup=mk)
    except Exception as e:
        log_error(cid, e); bot.reply_to(message, f"❌ فشل: {safe_err(e)}")

@bot.callback_query_handler(func=lambda c: c.data == "cmd_change_desc")
def cb_desc(call):
    bot.answer_callback_query(call.id)
    cid  = call.message.chat.id
    name = user_steps.get(cid, {}).get('current_repo')
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    msg = bot.send_message(cid, f"📝 أرسل الوصف الجديد للمستودع {name}:", reply_markup=mk)
    bot.register_next_step_handler(msg, step_desc)
    try: bot.delete_message(cid, call.message.message_id)
    except: pass

def step_desc(message):
    cid = message.chat.id
    name = user_steps.get(cid, {}).get('current_repo')
    config = load_config()
    try:
        Github(config['token']).get_repo(f"{config['username']}/{name}").edit(description=message.text.strip())
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.reply_to(message, "✅ تم تحديث الوصف بنجاح!", reply_markup=mk)
    except Exception as e:
        log_error(cid, e); bot.reply_to(message, f"❌ فشل: {safe_err(e)}")

@bot.callback_query_handler(func=lambda c: c.data == "cmd_toggle_vis")
def cb_toggle_vis(call):
    bot.answer_callback_query(call.id)
    cid, mid = call.message.chat.id, call.message.message_id
    name   = user_steps.get(cid, {}).get('current_repo')
    config = load_config()
    bot.edit_message_text("⏳ جاري تغيير الخصوصية...", cid, mid)
    try:
        repo = Github(config['token']).get_repo(f"{config['username']}/{name}")
        repo.edit(private=not repo.private)
        st = "🔒 خاص" if not repo.private else "🌐 عام"
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.edit_message_text(f"✅ تم تغيير {name} إلى {st}", cid, mid, reply_markup=mk)
    except Exception as e:
        log_error(cid, e); bot.edit_message_text(f"❌ فشل: {safe_err(e)}", cid, mid)

# ───────────────────────── Workflows ─────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "cmd_workflows")
def cb_workflows(call):
    bot.answer_callback_query(call.id)
    cid, mid = call.message.chat.id, call.message.message_id
    name   = user_steps.get(cid, {}).get('current_repo')
    config = load_config()
    if not config or not name:
        bot.edit_message_text("❌ خطأ في البيانات.", cid, mid); return
    bot.edit_message_text("⏳ جاري فحص الـ Workflows...", cid, mid)
    try:
        repo      = Github(config['token']).get_repo(f"{config['username']}/{name}")
        workflows = list(repo.get_workflows())
        mk = types.InlineKeyboardMarkup(row_width=1)
        wmap = {}
        for wf in workflows:
            wmap[str(wf.id)] = wf.name
            ico = "🟢" if wf.state == "active" else "🔴"
            mk.add(types.InlineKeyboardButton(f"{ico} {wf.name} — ▶️ تشغيل", callback_data=f"run_wf_{wf.id}"))
        user_steps[cid]['wf_map'] = wmap
        mk.add(types.InlineKeyboardButton("🔙 رجوع", callback_data=f"sel_{abs(hash(name))%100000}"))
        mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        txt = f"⚡ Workflows في {name}:" if workflows else f"ℹ️ لا يوجد Workflows في {name}."
        bot.edit_message_text(txt, cid, mid, reply_markup=mk)
    except Exception as e:
        log_error(cid, e); bot.edit_message_text(f"❌ خطأ: {safe_err(e)}", cid, mid)

@bot.callback_query_handler(func=lambda c: c.data.startswith("run_wf_"))
def cb_run_wf(call):
    bot.answer_callback_query(call.id, "⏳ جاري التشغيل...")
    cid    = call.message.chat.id
    wf_id  = call.data.replace("run_wf_", "")
    name   = user_steps.get(cid, {}).get('current_repo')
    config = load_config()
    if not config or not name: return
    try:
        repo   = Github(config['token']).get_repo(f"{config['username']}/{name}")
        branch = repo.default_branch
        r = requests.post(
            f"https://api.github.com/repos/{config['username']}/{name}/actions/workflows/{wf_id}/dispatches",
            headers={"Authorization": f"token {config['token']}", "Accept": "application/vnd.github.v3+json"},
            json={"ref": branch}, timeout=30)
        mk = types.InlineKeyboardMarkup(row_width=1)
        mk.add(types.InlineKeyboardButton("⚡ عرض Workflows", callback_data="cmd_workflows"))
        mk.add(types.InlineKeyboardButton("🏠 الرئيسية",     callback_data="main_menu"))
        wfname = user_steps.get(cid, {}).get('wf_map', {}).get(wf_id, wf_id)
        if r.status_code == 204:
            bot.edit_message_text(f"✅ تم تشغيل {wfname} على فرع {branch}!", cid, call.message.message_id, reply_markup=mk)
        else:
            bot.edit_message_text(f"❌ فشل: {clean_txt(r.json().get('message', r.text))}", cid, call.message.message_id, reply_markup=mk)
    except Exception as e:
        log_error(cid, e); bot.edit_message_text(f"❌ خطأ: {safe_err(e)}", cid, call.message.message_id)

# ───────────────────────── حذف المستودع ─────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "cmd_delete_repo")
def cb_confirm_delete(call):
    bot.answer_callback_query(call.id)
    cid  = call.message.chat.id
    name = user_steps.get(cid, {}).get('current_repo')
    if not name: return
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        types.InlineKeyboardButton("✅ نعم، احذف", callback_data="execute_delete"),
        types.InlineKeyboardButton("🚫 إلغاء",    callback_data=f"sel_{abs(hash(name))%100000}"))
    mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
    bot.edit_message_text(f"⚠️ تحذير!\nهل أنت متأكد من حذف {name} نهائياً؟\nلا يمكن التراجع!",
                          cid, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "execute_delete")
def cb_execute_delete(call):
    bot.answer_callback_query(call.id)
    cid    = call.message.chat.id
    name   = user_steps.get(cid, {}).get('current_repo')
    config = load_config()
    try:
        Github(config['token']).get_repo(f"{config['username']}/{name}").delete()
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.edit_message_text(f"✅ تم حذف {name} بنجاح.", cid, call.message.message_id, reply_markup=mk)
    except Exception as e:
        log_error(cid, e); bot.edit_message_text(f"❌ فشل: {safe_err(e)}", cid, call.message.message_id)

# ───────────────────────── الإعداد ─────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "setup_now")
def cb_setup(call):
    bot.answer_callback_query(call.id)
    start_setup(call.message)

@bot.message_handler(commands=['setup'])
def start_setup(message):
    clear_user_state(message.chat.id)
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
    bot.register_next_step_handler(
        bot.send_message(message.chat.id, "🔑 أرسل GitHub Token الخاص بك:\nسيتم التحقق منه تلقائياً", reply_markup=mk),
        step_token)

def step_token(message):
    token = message.text.strip()
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    try:
        user = Github(token).get_user()
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🚫 إلغاء", callback_data="main_menu"))
        bot.register_next_step_handler(
            bot.send_message(message.chat.id, f"✅ توكن صالح! مرحباً {user.login}\nأرسل اسم المستخدم لتأكيده:", reply_markup=mk),
            lambda m: step_finish(m, token))
    except Exception:
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        bot.send_message(message.chat.id, "❌ التوكن غير صالح.\nحاول مجدداً /setup", reply_markup=mk)

def step_finish(message, token):
    save_config(token, message.text.strip())
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
    bot.reply_to(message, "✅ تم حفظ الإعدادات بنجاح!", reply_markup=mk)

# ───────────────────────── الشطرنج ─────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "start_check")
def cb_start_chess(call):
    bot.answer_callback_query(call.id)
    cid = call.message.chat.id
    clear_user_state(cid)
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🚫 إلغاء", callback_data="cancel_chess"))
    msg = bot.edit_message_text("♟️ تحليل الشطرنج\n\nالصق نص الـ PGN هنا:", cid, call.message.message_id, reply_markup=mk)
    awaiting_pgn[cid]   = True
    chess_wait_msg[cid] = msg.message_id

@bot.callback_query_handler(func=lambda c: c.data == "cancel_chess")
def cb_cancel_chess(call):
    bot.answer_callback_query(call.id)
    clear_user_state(call.message.chat.id)
    show_main_menu(call.message.chat.id)

@bot.message_handler(commands=['check'])
def cmd_check(message):
    clear_user_state(message.chat.id)
    data = message.text.replace('/check', '').strip()
    if data:
        process_chess(message, data)
    else:
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🚫 إلغاء", callback_data="cancel_chess"))
        msg = bot.reply_to(message, "♟️ أرسل نص PGN للتحليل:", reply_markup=mk)
        awaiting_pgn[message.chat.id]   = True
        chess_wait_msg[message.chat.id] = msg.message_id

@bot.message_handler(func=lambda m: awaiting_pgn.get(m.chat.id, False) and m.text)
def receive_pgn(message):
    cid = message.chat.id
    awaiting_pgn.pop(cid, None)
    wid = chess_wait_msg.pop(cid, None)
    if wid:
        try: bot.delete_message(cid, wid)
        except: pass
    process_chess(message, message.text)

def process_chess(message, pgn_data):
    """
    FIX: جميع الرسائل بدون parse_mode - نقلات الشطرنج تحتوي + # *
    تكسر Markdown وتعطي Error 400
    """
    msg_wait = None
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_data))
        if not game:
            bot.reply_to(message, "❌ PGN غير صالح."); return

        white = game.headers.get("White", "White")
        black = game.headers.get("Black", "Black")
        event = game.headers.get("Event", "")
        date  = game.headers.get("Date",  "")

        msg_wait = bot.reply_to(message, f"⏳ جاري تحليل مباراة:\n⚪ {white} vs ⚫ {black}...")
        w_losses, b_losses, moments = [], [], []
        ply = 0
        clf = {"brilliant":0, "best":0, "blunder":0, "mistake":0, "inaccuracy":0}

        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            graph = draw_eval_graph(game, engine)
            board = game.board()
            for move in game.mainline_moves():
                ply += 1
                num  = (ply+1)//2
                wt   = board.turn == chess.WHITE
                plr  = white if wt else black
                ico  = "⚪" if wt else "⚫"

                info  = engine.analyse(board, chess.engine.Limit(depth=14))
                bscore = info["score"].relative.score(mate_score=1000)
                bmove  = info.get("pv",[None])[0]
                try:    bsan = board.san(bmove) if bmove else "غير متاح"
                except: bsan = "غير متاح"
                try:    msan = board.san(move)
                except: msan = str(move)

                brilliant = False
                if bmove and move == bmove:
                    val = {chess.PAWN:1,chess.KNIGHT:3,chess.BISHOP:3,chess.ROOK:5,chess.QUEEN:9}
                    mb  = sum(len(board.pieces(pt,board.turn))*v for pt,v in val.items())
                    board.push(move)
                    ma  = sum(len(board.pieces(pt,not board.turn))*v for pt,v in val.items())
                    if ma < mb-2: brilliant = True
                    clf["best"] += 1
                else:
                    board.push(move)

                post   = engine.analyse(board, chess.engine.Limit(depth=10))
                pscore = -post["score"].relative.score(mate_score=1000)
                loss   = max(0, bscore - pscore)

                if wt: w_losses.append(loss)
                else:  b_losses.append(loss)

                if brilliant:
                    clf["brilliant"] += 1
                    moments.append(f"{ico} نقلة {num} | {plr} | ✨ Brilliant!!\n   لعب: {msan}")
                elif loss > 400:
                    clf["blunder"] += 1
                    moments.append(f"{ico} نقلة {num} | {plr} | ❌ Blunder ??\n   لعب: {msan}  /  الأفضل: {bsan}")
                elif loss > 200:
                    clf["mistake"] += 1
                    moments.append(f"{ico} نقلة {num} | {plr} | ⚠️ Mistake ?\n   لعب: {msan}  /  الأفضل: {bsan}")
                elif loss > 90:
                    clf["inaccuracy"] += 1
                    if len(moments) < 12:
                        moments.append(f"{ico} نقلة {num} | {plr} | 💛 Inaccuracy\n   لعب: {msan}  /  الأفضل: {bsan}")

        wacc = calc_accuracy(w_losses); bacc = calc_accuracy(b_losses)
        welo = get_elo(wacc);           belo = get_elo(bacc)
        hdr  = f"📅 {event}  |  {date}" if (event or date) else ""

        res = (
            f"♟️ التقرير النهائي\n"
            + (f"{hdr}\n" if hdr else "")
            + f"\n⚪ {white}\n{acc_bar(wacc)}  |  ELO ~{welo}\n\n"
            f"⚫ {black}\n{acc_bar(bacc)}  |  ELO ~{belo}\n\n"
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
        if graph:
            bot.send_photo(message.chat.id, graph, caption="📈 رسم تقييم المباراة")
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        send_long(message.chat.id, res, mk)

    except Exception as e:
        log_error(message.chat.id, e)
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
        err = f"❌ خطأ: {clean_txt(str(e))}"
        if msg_wait:
            try:    bot.edit_message_text(err, message.chat.id, msg_wait.message_id, reply_markup=mk)
            except: bot.send_message(message.chat.id, err, reply_markup=mk)
        else:
            bot.send_message(message.chat.id, err, reply_markup=mk)

# ───────────────────────── سجل الأخطاء ─────────────────────────
@bot.message_handler(commands=['logs'])
def cmd_logs(message):
    if not error_logs:
        bot.reply_to(message, "✅ لا توجد أخطاء مسجلة."); return
    send_long(message.chat.id, "🔴 آخر الأخطاء:\n\n" + "\n".join(f"• {l}" for l in reversed(error_logs)))

# ───────────────────────── Flask ─────────────────────────
@app.route('/')
def home():
    return f"Bot is alive! Uptime: {str(datetime.now()-start_time).split('.')[0]}"

@app.route('/health')
def health():
    return {"status":"ok","uptime":str(datetime.now()-start_time).split('.')[0]}

def run_flask():
    app.run(host='0.0.0.0', port=10000)

# ───────────────────────── بدء التشغيل ─────────────────────────
if __name__ == "__main__":
    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as e:
            e.analyse(chess.Board(), chess.engine.Limit(depth=2))
        logger.info("✅ Stockfish يعمل.")
    except Exception as e:
        logger.critical(f"❌ فشل Stockfish: {e}"); exit(1)
    setup_commands()
    Thread(target=run_flask, daemon=True).start()
    logger.info("🤖 البوت يعمل...")
    bot.infinity_polling(timeout=90, long_polling_timeout=90,
                         allowed_updates=["message","callback_query"])
