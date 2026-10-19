# 🔄 GitHub'dan tiklash — Remote PC Monitor

Dastur kompyuterdan o'chib ketsa, GitHub'dan shu bosqichlar bilan qayta sozlanadi.

> Repo: `github.com/AsilbekIbrohimov/remotepc`

---

## ⚡ Tez yo'l (avtomat)

```powershell
# 1) Kodni klonlash (WARP yoqiq bo'lsin — github bloklangan bo'lsa)
git clone git@github.com:AsilbekIbrohimov/remotepc.git
cd remotepc

# 2) Avtomat sozlash (paketlar + cloudflared + papkalar + startup)
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 3) .env yarating (pastga qarang) va ishga tushiring
```

---

## 📋 Qo'lda — bosqichma-bosqich

### 1. Kodni olish
```powershell
git clone git@github.com:AsilbekIbrohimov/remotepc.git
cd remotepc
```
- GitHub bloklansa: **WARP (1.1.1.1)** yoqing. SSH (22-port) ishlamasa, WARP orqali HTTPS klon qiling.

### 2. Python + paketlar
- **Python 3.12+** o'rnating (python.org).
```powershell
python -m pip install -r requirements.txt
```

### 3. `.env` yaratish (MAJBURIY — maxfiy, repoda yo'q)
`.env.example` ni `.env` deb nusxalang va to'ldiring:
| Kalit | Qayerdan |
|---|---|
| `TG_BOT_TOKEN` | @BotFather |
| `TG_OWNER_ID` | o'z Telegram ID (@userinfobot) |
| `TG_API_ID`, `TG_API_HASH` | my.telegram.org |
| `USE_LOCAL_BOT_API=1` | 2GB fayl limiti uchun |

### 4. Binarylar (repoda yo'q — alohida)
- **cloudflared.exe** (tunnel) — `github.com/cloudflare/cloudflared/releases/latest` → `cloudflared-windows-amd64.exe` ni `cloudflared.exe` deb loyiha ildiziga qo'ying. (setup.ps1 avtomat yuklaydi)
- **telegram-bot-api** (lokal server, 2GB) — `github.com/SwissCore92/telegram-bot-api-bin/releases` → `windows-amd64.zip` ichidagini `botapi\` ga chiqaring.
  - Kerak bo'lmasa: `.env` da `USE_LOCAL_BOT_API=0` (limit 50MB bo'ladi).

### 5. Userbot sessiyasi (ixtiyoriy — Saqlangan xabarlar/chatlar uchun)
- Eski `gifts_session.session` faylini ko'chiring, **yoki** Telethon bilan qayta login:
```python
from telethon import TelegramClient
TelegramClient('gifts_session', API_ID, API_HASH).start()  # telefon + kod so'raydi
```

### 6. Ishga tushirish
- `scripts\startup.vbs` ni ikki marta bosing (hammasini oynasiz ishga tushiradi),
  **yoki** kompyuterni qayta yoqing (setup.ps1 startup'ga qo'ygan).
- Telegram'da botga `/start` → menyu tugmasidan (⊞) Mini App.

---

## 🧩 Qismlar (nima nima qiladi)
| Fayl/papka | Vazifa |
|---|---|
| `monitor_bot.py` → `bot/` | Telegram bot (boshqaruv, DVR, fayllar, /ai, 1C) |
| `web_server.py` → `webapp/` | Mini App serveri (jonli ekran, touchpad) |
| `scripts/keep_cloudflared.ps1` | Tunnel (bepul, http2) + `web_url.txt` |
| `scripts/keep_botapi.ps1` | Lokal Bot API server (2GB) |
| `scripts/startup.vbs` | Hammasini oynasiz ishga tushiradi |

## 🔐 GitHub'da SAQLANMAYDIGAN (qayta kerak)
`.env`, `*.session`, `cloudflared.exe`, `botapi/`, `miniapp_key.txt`, videolar.
Bular maxfiy yoki katta — yuqoridagi bosqichlarda qayta tiklanadi.

## 🐧 Linux (dual-boot)
Kod cross-platform. `pywin32`/`dxcam` Windows-only (pip o'tkazib yuboradi), ekran olish `mss`/PIL ga tushadi. Ishga tushirish uchun `.ps1`/`.vbs` o'rniga shell/systemd ishlating. `REMOTE_DATA_DIR` env bilan video papkasini belgilang.
