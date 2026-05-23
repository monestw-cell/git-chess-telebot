"""Fernet-based token encryption for secure storage."""

import os
import base64
import logging
from cryptography.fernet import Fernet

from bot.config import BOT_ENCRYPTION_KEY

logger = logging.getLogger(__name__)

_fernet_instance = None
_KEY_FILE = '.bot_key'


def get_fernet():
    """Get or create a Fernet instance using env key or local key file."""
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    key = BOT_ENCRYPTION_KEY
    if key:
        # Ensure the key is proper Fernet format (url-safe base64, 32 bytes)
        try:
            _fernet_instance = Fernet(key.encode() if isinstance(key, str) else key)
            return _fernet_instance
        except Exception as e:
            logger.error(f"BOT_ENCRYPTION_KEY is set but invalid: {e}. Falling back to local key file.")

    # Try loading from local key file
    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, 'rb') as f:
            key_data = f.read().strip()
        _fernet_instance = Fernet(key_data)
        return _fernet_instance

    # Generate a new key and save it
    new_key = Fernet.generate_key()
    with open(_KEY_FILE, 'wb') as f:
        f.write(new_key)
    os.chmod(_KEY_FILE, 0o600)
    _fernet_instance = Fernet(new_key)
    return _fernet_instance


def encrypt_token(plain_text):
    """Encrypt a plain text token."""
    f = get_fernet()
    if isinstance(plain_text, str):
        plain_text = plain_text.encode('utf-8')
    return f.encrypt(plain_text).decode('utf-8')


def decrypt_token(encrypted_text):
    """Decrypt an encrypted token."""
    f = get_fernet()
    if isinstance(encrypted_text, str):
        encrypted_text = encrypted_text.encode('utf-8')
    return f.decrypt(encrypted_text).decode('utf-8')
