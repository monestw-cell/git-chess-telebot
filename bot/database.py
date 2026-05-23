"""SQLite per-user storage replacing the old shared JSON config file."""

import sqlite3
from datetime import datetime

from bot.config import DB_PATH
from bot.encryption import encrypt_token, decrypt_token

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    github_token TEXT,
    github_username TEXT,
    language TEXT DEFAULT 'ar',
    chess_depth INTEGER DEFAULT 14,
    created_at TEXT,
    updated_at TEXT
)
"""


def _get_conn():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema."""
    conn = _get_conn()
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


def save_user_config(chat_id, token, username):
    """Save or update user configuration with encrypted token."""
    encrypted = encrypt_token(token)
    now = datetime.now().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO users (chat_id, github_token, github_username, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                   github_token = excluded.github_token,
                   github_username = excluded.github_username,
                   updated_at = excluded.updated_at""",
            (chat_id, encrypted, username, now, now)
        )
        conn.commit()
    finally:
        conn.close()


def get_user_config(chat_id):
    """Get user config. Returns dict with decrypted token or None."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        # Decrypt token
        if result.get('github_token'):
            try:
                result['token'] = decrypt_token(result['github_token'])
            except Exception:
                result['token'] = None
        else:
            result['token'] = None
        result['username'] = result.get('github_username', '')
        return result
    finally:
        conn.close()


def delete_user_config(chat_id):
    """Delete a user's configuration."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
        conn.commit()
    finally:
        conn.close()


def ensure_user_exists(chat_id):
    """Ensure a user record exists (for settings before GitHub setup)."""
    conn = _get_conn()
    try:
        existing = conn.execute(
            "SELECT chat_id FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if not existing:
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO users (chat_id, created_at, updated_at) VALUES (?, ?, ?)",
                (chat_id, now, now)
            )
            conn.commit()
    finally:
        conn.close()


def update_user_setting(chat_id, key, value):
    """Update a single user setting."""
    allowed_keys = {'language', 'chess_depth', 'github_username'}
    if key not in allowed_keys:
        return
    ensure_user_exists(chat_id)
    now = datetime.now().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            f"UPDATE users SET {key} = ?, updated_at = ? WHERE chat_id = ?",
            (value, now, chat_id)
        )
        conn.commit()
    finally:
        conn.close()
