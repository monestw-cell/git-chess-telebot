"""Bot package - Telegram bot instance creation."""

import telebot
from telebot import apihelper

from bot.config import TELEGRAM_TOKEN, API_READ_TIMEOUT, API_CONNECT_TIMEOUT

apihelper.READ_TIMEOUT = API_READ_TIMEOUT
apihelper.CONNECT_TIMEOUT = API_CONNECT_TIMEOUT

bot_instance = telebot.TeleBot(TELEGRAM_TOKEN)
