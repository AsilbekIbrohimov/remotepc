# 🤖 Claude agentiga: Remote PC Monitor'ni o'rnatish qo'llanmasi

> Salom, narigi Claude! **Jamshid aka billa** 😄 — bu loyihani do'stimning kompyuteriga
> sen o'rnatasan. Quyida hammasi bosqichma-bosqich. Windows 10/11 uchun.

Bu Telegram bot orqali kompyuterni masofadan boshqarish tizimi:
jonli ekran (Mini App), fayl yuborish, ekran yozuvi (DVR), touchpad, va h.k.

---

## 0. Oldindan kerak bo'ladigan narsalar (foydalanuvchidan so'ra)

Foydalanuvchidan quyidagilarni oldindan tayyorlashini so'ra — bularsiz bot ishga tushmaydi:

| Kalit | Qayerdan olinadi |
|---|---|
| `TG_BOT_TOKEN` | Telegram'da **@BotFather** → `/newbot` → token beradi |
| `TG_OWNER_ID` | **@userinfobot** ga `/start` → o'z raqamli ID' si |
| `TG_API_ID`, `TG_API_HASH` | **my.telegram.org** → API development tools |

GitHub bloklangan bo'lsa: **WARP (1.1.1.1)** ilovasini yoqib qo'ying.

---

## 1. Kodni olish

```powershell
git clone https://github.com/AsilbekIbrohimov/remotepc.git
cd remotepc
```

(SSH ishlasa `git@github.com:AsilbekIbrohimov/remotepc.git` ham bo'ladi.)

## 2. Avtomat sozlash — bitta buyruq

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Bu skript o'zi:
- Python 3.12 ni topadi yoki **o'zi o'rnatadi** (winget yoki python.org),
- `pip install -r requirements.txt`,
- `cloudflared.exe` (tunnel) va `telegram-bot-api` (2GB limit) ni yuklaydi,
- video papkasini `%LOCALAPPDATA%\RemotePC` da yaratadi (OneDrive'ni to'ldirmasligi uchun),
- **avtostart** (`startup.vbs`) ni shu mashina yo'llari bilan sozlaydi.

## 3. `.env` yaratish (MAJBURIY)

```powershell
copy .env.example .env
notepad .env
```

`.env.example` dagi `SIZNING_...` o'rinlariga 0-qadamdagi haqiqiy qiymatlarni yoz.
Minimal kerak bo'ladiganlar: `TG_BOT_TOKEN`, `TG_OWNER_ID`, `TG_API_ID`, `TG_API_HASH`.
`USE_LOCAL_BOT_API=1` qoldir (2GB fayl uchun). 1C kerak bo'lmasa `ONEC_*` bo'sh qolsin.

## 4. Ishga tushirish

```powershell
wscript "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\TelegramPCMonitorBot.vbs"
```

Yoki kompyuterni qayta yoqing — avtostart o'zi ishga tushiradi.
~30–60 soniyadan keyin Telegram'da botga `/start` yoz → chat pastidagi **menyu tugmasi (⊞)** dan Mini App ochiladi.

---

## 5. Tekshirish

- Botga `/start` → javob bermasa: `scripts\setup.ps1` ni qayta ishga tushir, `.env` to'g'riligini tekshir.
- Mini App "ulanmayapti": `web_url.txt` yaratilganini kuzat; cloudflared ishlab turganini tekshir
  (`scripts\keep_cloudflared.ps1` `--protocol http2` bilan ishga tushadi — ISP QUIC/UDP'ni bloklasa ham ishlaydi).
- Fayllar: bot `Downloads` papkasidagi **to'g'ridan-to'g'ri** fayllarni yuboradi (ichki papkalarni emas).

---

## 🔐 Muhim (maxfiylik)

- `.env`, `*.session`, `miniapp_key.txt`, `web_url.txt` — **hech qachon** repoga yuklanmaydi (`.gitignore` da).
- Bu bot kompyuterga **to'liq boshqaruv** beradi. Faqat ishonchli kompyuterga o'rnat va `.env` ni sir saqla.

Savol bo'lsa — SETUP.md da batafsilroq. Omad, **Jamshid aka billa!** 🚀
