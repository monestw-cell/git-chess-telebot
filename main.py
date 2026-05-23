"""Thin entry point for the Telegram bot."""
import logging
from threading import Thread
from datetime import datetime
from flask import Flask
from bot import bot_instance
from bot.database import init_db
from bot.handlers import register_all
from bot.handlers.menu import setup_commands

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

init_db()
register_all(bot_instance)

app = Flask(__name__)
_start_time = datetime.now()


@app.route('/')
def home():
    uptime = str(datetime.now() - _start_time).split('.')[0]
    return f"Bot is alive! Uptime: {uptime}"


@app.route('/health')
def health():
    uptime = str(datetime.now() - _start_time).split('.')[0]
    return {"status": "ok", "uptime": uptime}


def _run_flask():
    app.run(host='0.0.0.0', port=10000)


if __name__ == "__main__":
    setup_commands(bot_instance)
    Thread(target=_run_flask, daemon=True).start()
    logger.info("Bot is running...")
    bot_instance.infinity_polling(
        timeout=90, long_polling_timeout=90,
        allowed_updates=["message", "callback_query"]
    )
