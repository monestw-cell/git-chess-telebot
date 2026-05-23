"""Shared utility functions."""

import logging
from collections import deque
from datetime import datetime

from github import Github

from bot.config import MAX_MESSAGE_LENGTH, MAX_ERROR_LOGS
from bot.database import get_user_config

logger = logging.getLogger(__name__)

_error_logs = deque(maxlen=MAX_ERROR_LOGS)


def clean_txt(text):
    """Clean text for safe display in Telegram messages."""
    return (str(text)
            .replace('`', "'")
            .replace('*', '')
            .replace('_', '')
            .replace('[', '(')
            .replace(']', ')'))


def send_long_message(bot, chat_id, text, reply_markup=None):
    """Send a long message by splitting it into chunks."""
    max_len = MAX_MESSAGE_LENGTH
    if len(text) <= max_len:
        try:
            return bot.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception:
            return bot.send_message(chat_id, text[:max_len], reply_markup=reply_markup)
    parts = []
    while len(text) > max_len:
        idx = text.rfind('\n', 0, max_len)
        if idx == -1:
            idx = max_len
        parts.append(text[:idx])
        text = text[idx:].lstrip('\n')
    parts.append(text)
    for i, p in enumerate(parts):
        bot.send_message(
            chat_id, p,
            reply_markup=reply_markup if i == len(parts) - 1 else None
        )


def log_error(chat_id, error_msg):
    """Log an error with timestamp and chat_id."""
    entry = f"{datetime.now().strftime('%H:%M:%S')} | {chat_id} | {str(error_msg)[:200]}"
    _error_logs.append(entry)
    logger.error(entry)


def get_error_logs():
    """Get the error log entries."""
    return list(_error_logs)


def try_delete_message(bot, chat_id, msg_id):
    """Safely attempt to delete a message."""
    try:
        bot.delete_message(chat_id, msg_id)
    except Exception:
        pass


def get_github_client(chat_id):
    """Get a Github instance for the user, or None if not configured."""
    config = get_user_config(chat_id)
    if not config or not config.get('token'):
        return None
    return Github(config['token'])
