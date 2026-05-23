"""Chess analysis handler with merged single-pass Stockfish analysis."""

import io
import math
import logging

import chess
import chess.engine
import chess.pgn
from telebot import types

from bot.config import STOCKFISH_PATH, CHESS_DEFAULT_DEPTH, CHESS_GRAPH_DEPTH
from bot.state import user_state
from bot.database import get_user_config
from bot.utils import (
    clean_txt, send_long_message, log_error, try_delete_message,
)

logger = logging.getLogger(__name__)

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


def _get_estimated_elo(acc):
    """Estimate ELO rating from accuracy percentage."""
    if acc >= 99:
        return 2800
    if acc >= 95:
        return 2200 + int((acc - 95) * 120)
    if acc >= 90:
        return 1800 + int((acc - 90) * 80)
    if acc >= 80:
        return 1300 + int((acc - 80) * 50)
    if acc >= 70:
        return 900 + int((acc - 70) * 40)
    if acc >= 55:
        return 500 + int((acc - 55) * 26)
    return max(100, int(acc * 7))


def _calculate_accuracy(loss_list):
    """Calculate accuracy from centipawn loss list."""
    if not loss_list:
        return 100.0
    avg_loss = sum(loss_list) / len(loss_list)
    acc = 103.1668 * math.exp(-0.04354 * math.sqrt(avg_loss)) - 3.1668
    return round(max(0.0, min(100.0, acc)), 1)


def _acc_bar(acc):
    """Generate a text-based accuracy bar."""
    filled = int(acc / 10)
    return "█" * filled + "░" * (10 - filled) + f" {acc}%"


def _generate_eval_graph(scores):
    """Generate evaluation graph from pre-computed scores list."""
    if not MATPLOTLIB_AVAILABLE or not scores:
        return None
    try:
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.fill_between(
            range(1, len(scores) + 1), scores, 0,
            where=[s > 0 for s in scores], color='white', alpha=0.6
        )
        ax.fill_between(
            range(1, len(scores) + 1), scores, 0,
            where=[s < 0 for s in scores], color='gray', alpha=0.6
        )
        ax.plot(
            range(1, len(scores) + 1), scores,
            color='black', linewidth=1.2
        )
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
        logger.warning(f"Graph generation failed: {e}")
        return None


def _process_chess(bot, message, pgn_data, analysis_depth=CHESS_DEFAULT_DEPTH):
    """Process a chess PGN with single-pass Stockfish analysis.

    FIX: Merged the previously separate generate_eval_graph loop and
    the move classification loop into a single pass through the game.
    This halves the Stockfish computation time.
    """
    msg_wait = None
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_data))
        if not game:
            bot.reply_to(message, "❌ PGN غير صالح.")
            return

        white = game.headers.get("White", "White")
        black = game.headers.get("Black", "Black")
        event = game.headers.get("Event", "")
        date = game.headers.get("Date", "")

        msg_wait = bot.reply_to(
            message,
            f"⏳ جاري تحليل مباراة:\n⚪ {white} vs ⚫ {black}..."
        )
        w_losses, b_losses, moments = [], [], []
        graph_scores = []
        ply = 0
        clf = {
            "brilliant": 0, "best": 0, "blunder": 0,
            "mistake": 0, "inaccuracy": 0
        }

        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            board = game.board()
            for move in game.mainline_moves():
                ply += 1
                move_number = (ply + 1) // 2
                is_white_turn = (board.turn == chess.WHITE)
                player = white if is_white_turn else black
                icon = "⚪" if is_white_turn else "⚫"

                # Single analysis before the move (full depth)
                info = engine.analyse(
                    board, chess.engine.Limit(depth=analysis_depth)
                )
                best_score = info["score"].relative.score(mate_score=1000)
                best_move = info.get("pv", [None])[0]

                # Collect score for graph (clamped to +/- 10 pawns)
                graph_score = max(
                    -1000, min(1000, best_score)
                ) / 100.0
                graph_scores.append(graph_score)

                try:
                    best_san = (
                        board.san(best_move) if best_move else "غير متاح"
                    )
                except Exception:
                    best_san = "غير متاح"
                try:
                    move_san = board.san(move)
                except Exception:
                    move_san = str(move)

                is_brilliant = False
                if best_move and move == best_move:
                    val = {
                        chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                        chess.ROOK: 5, chess.QUEEN: 9
                    }
                    mat_before = sum(
                        len(board.pieces(pt, board.turn)) * v
                        for pt, v in val.items()
                    )
                    board.push(move)
                    mat_after = sum(
                        len(board.pieces(pt, not board.turn)) * v
                        for pt, v in val.items()
                    )
                    if mat_after < mat_before - 2:
                        is_brilliant = True
                    clf["best"] += 1
                else:
                    board.push(move)

                # Post-move analysis at graph depth for loss calculation
                post = engine.analyse(
                    board, chess.engine.Limit(depth=CHESS_GRAPH_DEPTH)
                )
                played_score = -post["score"].relative.score(mate_score=1000)
                loss = max(0, best_score - played_score)

                if is_white_turn:
                    w_losses.append(loss)
                else:
                    b_losses.append(loss)

                if is_brilliant:
                    clf["brilliant"] += 1
                    moments.append(
                        f"{icon} نقلة {move_number} | {player} | "
                        f"✨ Brilliant!!\n   لعب: {move_san}"
                    )
                elif loss > 400:
                    clf["blunder"] += 1
                    moments.append(
                        f"{icon} نقلة {move_number} | {player} | "
                        f"❌ Blunder ??\n   لعب: {move_san}  /  "
                        f"الأفضل: {best_san}"
                    )
                elif loss > 200:
                    clf["mistake"] += 1
                    moments.append(
                        f"{icon} نقلة {move_number} | {player} | "
                        f"⚠️ Mistake ?\n   لعب: {move_san}  /  "
                        f"الأفضل: {best_san}"
                    )
                elif loss > 90:
                    clf["inaccuracy"] += 1
                    if len(moments) < 12:
                        moments.append(
                            f"{icon} نقلة {move_number} | {player} | "
                            f"💛 Inaccuracy\n   لعب: {move_san}  /  "
                            f"الأفضل: {best_san}"
                        )

        # Generate graph from collected scores (no extra engine calls)
        graph_buf = _generate_eval_graph(graph_scores)

        w_acc = _calculate_accuracy(w_losses)
        b_acc = _calculate_accuracy(b_losses)
        w_elo = _get_estimated_elo(w_acc)
        b_elo = _get_estimated_elo(b_acc)
        header = f"📅 {event}  |  {date}" if (event or date) else ""

        res = (
            f"♟️ التقرير النهائي\n"
            + (f"{header}\n" if header else "")
            + f"\n"
            f"⚪ {white}\n"
            f"{_acc_bar(w_acc)}  |  ELO ~{w_elo}\n\n"
            f"⚫ {black}\n"
            f"{_acc_bar(b_acc)}  |  ELO ~{b_elo}\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"✨ Brilliant: {clf['brilliant']}   ✅ Best: {clf['best']}\n"
            f"❌ Blunder: {clf['blunder']}   ⚠️ Mistake: {clf['mistake']}\n"
            f"💛 Inaccuracy: {clf['inaccuracy']}\n"
            f"━━━━━━━━━━━━━━\n"
        )
        if moments:
            res += "🎯 أبرز اللحظات:\n\n" + "\n\n".join(moments[:8])

        try_delete_message(bot, message.chat.id, msg_wait.message_id)
        if graph_buf:
            bot.send_photo(
                message.chat.id, graph_buf,
                caption="📈 رسم تقييم المباراة"
            )
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(
                "🏠 الرئيسية", callback_data="main_menu"
            )
        )
        send_long_message(bot, message.chat.id, res, reply_markup=markup)

    except Exception as e:
        log_error(message.chat.id, e)
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(
                "🏠 الرئيسية", callback_data="main_menu"
            )
        )
        err_text = f"❌ خطأ: {clean_txt(str(e))}"
        if msg_wait:
            try:
                bot.edit_message_text(
                    err_text, message.chat.id,
                    msg_wait.message_id, reply_markup=markup
                )
            except Exception:
                bot.send_message(
                    message.chat.id, err_text, reply_markup=markup
                )
        else:
            bot.send_message(
                message.chat.id, err_text, reply_markup=markup
            )


def register(bot):
    """Register chess handlers with the bot."""

    @bot.callback_query_handler(func=lambda c: c.data == "start_check")
    def start_chess_check(call):
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        user_state.clear(chat_id)
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(
                "🚫 إلغاء", callback_data="cancel_chess"
            )
        )
        msg = bot.edit_message_text(
            "♟️ تحليل الشطرنج\n\nالصق نص الـ PGN هنا:",
            chat_id, call.message.message_id, reply_markup=markup
        )
        user_state.set_field(chat_id, 'awaiting_pgn', True)
        user_state.set_field(chat_id, 'chess_wait_msg_id', msg.message_id)

    @bot.callback_query_handler(func=lambda c: c.data == "cancel_chess")
    def cancel_chess(call):
        bot.answer_callback_query(call.id)
        user_state.clear(call.message.chat.id)
        from bot.handlers.menu import show_main_menu
        show_main_menu(bot, call.message.chat.id)

    @bot.message_handler(commands=['check'])
    def handle_check_command(message):
        user_state.clear(message.chat.id)
        data = message.text.replace('/check', '').strip()
        if data:
            # Get user-specific depth if configured
            config = get_user_config(message.chat.id)
            depth = CHESS_DEFAULT_DEPTH
            if config and config.get('chess_depth'):
                depth = config['chess_depth']
            _process_chess(bot, message, data, depth)
        else:
            markup = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    "🚫 إلغاء", callback_data="cancel_chess"
                )
            )
            msg = bot.reply_to(
                message, "♟️ أرسل نص PGN للتحليل:", reply_markup=markup
            )
            user_state.set_field(
                message.chat.id, 'awaiting_pgn', True
            )
            user_state.set_field(
                message.chat.id, 'chess_wait_msg_id', msg.message_id
            )

    @bot.message_handler(
        func=lambda m: user_state.get_field(
            m.chat.id, 'awaiting_pgn', False
        ) and m.text
    )
    def receive_pgn(message):
        chat_id = message.chat.id
        user_state.set_field(chat_id, 'awaiting_pgn', False)
        wid = user_state.get_field(chat_id, 'chess_wait_msg_id')
        user_state.set_field(chat_id, 'chess_wait_msg_id', None)
        if wid:
            try_delete_message(bot, chat_id, wid)
        # Get user-specific depth if configured
        config = get_user_config(chat_id)
        depth = CHESS_DEFAULT_DEPTH
        if config and config.get('chess_depth'):
            depth = config['chess_depth']
        _process_chess(bot, message, message.text, depth)
