# Chess Telegram Bot (بوت الشطرنج التفاعلي) ♟️🤖

بوت تيليجرام تفاعلي متقدم للعب وتحليل مباريات الشطرنج فردياً ومع الأصدقاء داخل محادثات ومجموعات Telegram.

---

## 🌟 نبذة عن المشروع (Overview)

**Chess Telegram Bot** هو بوت تلغرام ذكي مبني بلغة بايثون، يتيح للمستخدمين والمجموعات خوض مباريات شطرنج مباشرة مع واجهة تفاعلية مرئية لتوليد رقعة الشطرنج وتحديثها تلقائياً بعد كل نقلة، بالإضافة إلى دعم تحليل المواقف وتوليد سجلات المباريات بصيغة PGN.

---

## ✨ المميزات الرئيسية (Key Features)

- **اللعب التفاعلي المباشر:** لوحة شطرنج رسومية تفاعلية تعتمد على أزرار التلغرام (Inline Keyboard).
- **أنماط لعب متعددة:**
  - لعب ثنائي بين صديقين في المحادثات الخاصة أو المجموعات.
  - اللعب ضد محرك شطرنج ذكي بمستويات صعوبة متعددة.
- **توليد الرقعة الرسومية:** إنشاء وتحديث صور رقعة الشطرنج فورياً بعد كل حركة.
- **التحقق من صحة القواعد والنقلات:** دعم قواعد الشطرنج الدولية (التبييت، الأخذ بالتجاوز، كش ملك، الترقية، وحالات التعادل).
- **تصدير واستيراد PGN / FEN:** حفظ سجلات المباريات ومشاركتها بسهولة.
- **سيرفر ويب صحي مدمج (Health Check Server):** يدعم الاستضافة المستمرة على منصات السحابة (Render, Koyeb, Railway, VPS).

---

## 🛠️ التقنيات المستخدمة (Tech Stack)

- **Language:** Python 3.10+
- **Telegram Framework:** `pyTelegramBotAPI` (`telebot`)
- **Chess Engine & Logic:** `python-chess`
- **Deployment & Web Server:** Flask / Threading, Docker

---

## 🚀 التثبيت والتشغيل (Setup & Run)

### 1. المتطلبات
- Python 3.10 أو أحدث
- توكن بوت من [BotFather](https://t.me/BotFather)

### 2. التثبيت المحلي
```bash
# استنساخ المشروع
git clone https://github.com/monestw-cell/chess-telegram-bot.git
cd chess-telegram-bot

# تثبيت الحزم المطلوبة
pip install -r requirements.txt

# ضبط متغير البيئة وتشغيل البوت
export BOT_TOKEN="your_telegram_bot_token"
python main.py
```

### 3. التشغيل عبر Docker
```bash
docker build -t chess-telegram-bot .
docker run -e BOT_TOKEN="your_telegram_bot_token" -p 8080:8080 chess-telegram-bot
```

---

## 📄 الترخيص (License)
هذا المشروع مرخص تحت رخصة [MIT](LICENSE).
