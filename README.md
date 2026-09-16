# PC Remote — Telegram orqali kompyuter monitoring va boshqaruv

Telegram bot + Mini App orqali kompyuterni masofadan kuzatish va boshqarish.

## Imkoniyatlar

- 📊 Tizim holati (CPU, RAM, disk, uptime, internet)
- 📈 CPU/RAM tarixi grafigi
- 💻 Jarayonlar ro'yxati, jarayonni to'xtatish (`/kill`)
- 📸 Skrinshot, 🎬 ekran videosini yozib olish (`/record`, `/stop`)
- 🌐 **Mini App** — real vaqtda ekran oqimi (MJPEG), to'liq **touchpad** (kursor, klik, scroll, drag), klaviatura, media va tizim tugmalari
- 🔒 Qulflash, 😴 uxlash, 🔄 qayta yuklash / 🛑 o'chirish (darhol / 1 daq / 5 daq)
- 🆕 Yangi va yangilangan fayllarni avtomatik yuborish (Desktop, Documents, OneDrive, ...)
- ⚠️ CPU/RAM ogohlantirishlari, kirish/qulflash hodisalari

## Tuzilma

```
bot/app.py       — Telegram bot (aiogram)
webapp/app.py    — Mini App server (aiohttp): ekran oqimi + boshqaruv (WebSocket)
scripts/         — SSH tunnel / yordamchi skriptlar
setup/           — dastlabki sozlash skriptlari
monitor_bot.py   — bot ishga tushiruvchisi (shim)
web_server.py    — web server ishga tushiruvchisi (shim)
```

## Ishga tushirish

1. `.env` faylini yarating (namuna uchun `.env.example`):
   ```
   TG_BOT_TOKEN=...
   TG_OWNER_ID=...
   WEB_APP_URL=https://<sizning-tunnel>.example
   ```
2. Kutubxonalar: `pip install aiogram aiohttp psutil pillow matplotlib watchdog python-dotenv opencv-python numpy`
3. Mini App uchun HTTPS tunnel oching (ngrok yoki serveo), URL'ni `.env`ga yozing.
4. Ishga tushiring:
   ```
   python web_server.py
   python monitor_bot.py
   ```

## Xavfsizlik

- `.env`, session va bot ma'lumotlari `.gitignore` orqali repozitoriyga **kirmaydi**.
- Bot faqat `TG_OWNER_ID` egasidan buyruq qabul qiladi.
