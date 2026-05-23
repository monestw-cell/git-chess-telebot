"""Application configuration loaded from environment variables."""

import os

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
STOCKFISH_PATH = os.environ.get('STOCKFISH_PATH', '/usr/games/stockfish')
BOT_ENCRYPTION_KEY = os.environ.get('BOT_ENCRYPTION_KEY', '')
DB_PATH = os.environ.get('DB_PATH', 'bot_data.db')

MAX_MESSAGE_LENGTH = 4000
MAX_ERROR_LOGS = 50
CHESS_DEFAULT_DEPTH = 14
CHESS_GRAPH_DEPTH = 10

API_READ_TIMEOUT = 120
API_CONNECT_TIMEOUT = 120
