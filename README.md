# Interactive Chess Telegram Bot ♟️🤖

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![pyTelegramBotAPI](https://img.shields.io/badge/Library-pyTelegramBotAPI-2CA5E0?logo=telegram&logoColor=white)](https://github.com/eternnoir/pyTelegramBotAPI)
[![Docker](https://img.shields.io/badge/Container-Docker-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A full-featured Telegram Bot for playing and analyzing chess games directly inside Telegram chats, private groups, and supergroups using interactive inline keyboards and on-the-fly board rendering.

---

## ✨ Features

- **👥 Player vs Player (PvP):** Challenge friends in group chats or direct messages.
- **🤖 Player vs AI (PvE):** Challenge an embedded chess engine with multiple difficulty levels.
- **🎨 Dynamic Board Rendering:** Generates and delivers high-contrast chessboard images for every move.
- **📋 International Chess Rules:** Complete enforcement of standard chess rules (En Passant, Castling, Pawn Promotion, 50-move rule, Threefold repetition).
- **📜 PGN / FEN Support:** Export game transcripts or load custom board positions.
- **🌐 Cloud-Ready Health Server:** Integrated Flask health check server for continuous cloud deployment (Koyeb, Render, Railway, VPS).

---

## 🚀 Quickstart

### 1. Environment Setup
```bash
git clone https://github.com/monestw-cell/chess-telegram-bot.git
cd chess-telegram-bot
pip install -r requirements.txt
```

### 2. Configure Environment Variables
```bash
export BOT_TOKEN="your_telegram_bot_token_from_botfather"
python main.py
```

### 3. Run with Docker
```bash
docker build -t chess-telegram-bot .
docker run -d -e BOT_TOKEN="your_token" -p 8080:8080 chess-telegram-bot
```

---

## 📄 License
Licensed under the [MIT License](LICENSE).
