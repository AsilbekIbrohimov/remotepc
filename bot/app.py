import asyncio
import ctypes
import io
import json
import os
import socket
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import imageio.v2 as imageio
import imageio_ffmpeg
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import psutil
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from dotenv import load_dotenv
from PIL import ImageGrab
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
OWNER_ID = int(os.environ["TG_OWNER_ID"])
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://example.com")
CHATS_FILE = BASE_DIR / "subscribed_chats.json"
STATUS_INTERVAL_SECONDS = 30 * 60
ALERT_CHECK_INTERVAL_SECONDS = 2 * 60
ALERT_COOLDOWN_SECONDS = 15 * 60
CPU_ALERT_THRESHOLD = 90
RAM_ALERT_THRESHOLD = 90
SHUTDOWN_DELAY_SECONDS = 60
HISTORY_SAMPLE_SECONDS = 60
HISTORY_MAX_SAMPLES = 6 * 60  # 6 soat
LOCK_POLL_SECONDS = 10
DESKTOP_SWITCHDESKTOP = 0x0100
# Lokal Bot API server yoqilgan bo'lsa fayl chegarasi 2000MB, aks holda 50MB
USE_LOCAL_BOT_API = os.environ.get("USE_LOCAL_BOT_API", "").strip() in ("1", "true", "yes")
LOCAL_BOT_API_URL = os.environ.get("LOCAL_BOT_API_URL", "http://127.0.0.1:8081").strip()
MAX_TELEGRAM_FILE_BYTES = (2000 if USE_LOCAL_BOT_API else 50) * 1024 * 1024

def _build_watch_folders() -> list[Path]:
    names = ["Desktop", "Documents", "Pictures", "Videos", "Music"]
    roots = [Path.home()]
    one = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if one:
        roots.append(Path(one))
    roots.append(Path.home() / "OneDrive")
    folders, seen = [], set()
    for root in roots:
        # OneDrive ildizining o'zini ham kuzatamiz (undagi yangi fayllar uchun)
        candidates = [root] + [root / n for n in names] if "onedrive" in str(root).lower() else [root / n for n in names]
        for f in candidates:
            try:
                rp = f.resolve()
            except OSError:
                continue
            if f.exists() and rp not in seen:
                seen.add(rp)
                folders.append(f)
    # 1C hisobot jo'natmalari papkasi (Рассылки отчётов shu yerga saqlaydi)
    extra = os.environ.get("ONEC_REPORTS_DIR")
    if extra:
        p = Path(extra)
        try:
            p.mkdir(parents=True, exist_ok=True)
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                folders.append(p)
        except OSError:
            pass
    return folders


WATCH_FOLDERS = _build_watch_folders()
EXCLUDED_DIR_NAMES = {
    "node_modules", ".git", "__pycache__", "appdata", "$recycle.bin",
    "system volume information", "cache", "tmp", "temp", ".vscode",
    ".idea", "venv", ".venv", "site-packages", ".cache", ".mypy_cache",
    ".pytest_cache", "telegram desktop",
}
EXCLUDED_EXTENSIONS = {".tmp", ".crdownload", ".part", ".partial", ".download", ".session-journal"}
NEW_FILE_SETTLE_SECONDS = 2

if USE_LOCAL_BOT_API:
    # Lokal Bot API server orqali — 2GB gacha fayl yuborish mumkin
    _session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_BOT_API_URL, is_local=True))
    bot = Bot(token=BOT_TOKEN, session=_session)
else:
    bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.message.filter(F.from_user.id == OWNER_ID)
dp.callback_query.filter(F.from_user.id == OWNER_ID)

# ── Buyruq log ─────────────────────────────────────────────
# Bot orqali kelgan har bir buyruq shu faylga yoziladi. Shunday qilib bu
# sessiya (va /ai) foydalanuvchi bot orqali nima qilganini doim biladi.
CMD_LOG = BASE_DIR / "bot_activity.log"


def _log_command(text: str, kind: str = "cmd") -> None:
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(CMD_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts}\t{kind}\t{text}\n")
    except Exception:
        pass


def _recent_activity(n: int = 20) -> str:
    try:
        lines = CMD_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    return "\n".join(lines[-n:])


async def _log_message_mw(handler, event, data):
    try:
        txt = (getattr(event, "text", None) or "").strip()
        if txt:
            _log_command(txt, "cmd")
    except Exception:
        pass
    return await handler(event, data)


async def _log_callback_mw(handler, event, data):
    try:
        d = (getattr(event, "data", None) or "").strip()
        if d:
            _log_command(d, "btn")
    except Exception:
        pass
    return await handler(event, data)


dp.message.outer_middleware(_log_message_mw)
dp.callback_query.outer_middleware(_log_callback_mw)

# ── Masofadan ulanishga ruxsat (Mini App begona brauzerdan ochilganda) ──
GRANTS_FILE = BASE_DIR / "access_grants.json"
ACCESS_TTL_SECONDS = 60 * 60  # ruxsat 1 soat amal qiladi


def _write_grant(sid: str, status: str) -> None:
    try:
        try:
            data = json.loads(GRANTS_FILE.read_text("utf-8"))
        except Exception:
            data = {}
        # eski (muddati o'tgan) yozuvlarni tozalaymiz
        now = time.time()
        data = {k: v for k, v in data.items()
                if v.get("status") == "denied" or v.get("expires", 0) > now - 3600}
        data[sid] = {"status": status, "expires": now + ACCESS_TTL_SECONDS}
        GRANTS_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        print(f"grant yozish xato: {e}")


def _revoke_grant(sid: str) -> None:
    try:
        data = json.loads(GRANTS_FILE.read_text("utf-8"))
    except Exception:
        return
    if sid in data:
        data.pop(sid, None)
        try:
            GRANTS_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass


def _revoke_all() -> None:
    try:
        GRANTS_FILE.write_text("{}", encoding="utf-8")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("acc:"))
async def on_access(callback: CallbackQuery):
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        return
    _, act, sid = parts
    if act == "a":
        _write_grant(sid, "allowed")
        await callback.answer("✅ Ruxsat berildi")
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔌 Ulanishni uzish", callback_data=f"acc:x:{sid}")
            ]])
            await callback.message.edit_text(
                "✅ Ulanishga ruxsat berildi (1 soat).\n"
                "Istalgan vaqt uzishingiz mumkin 👇", reply_markup=kb)
        except Exception:
            pass
    elif act == "x":
        _revoke_grant(sid)
        await callback.answer("🔌 Ulanish uzildi")
        try:
            await callback.message.edit_text("🔌 Ulanish uzildi.")
        except Exception:
            pass
    else:
        _write_grant(sid, "denied")
        await callback.answer("⛔ Rad etildi")
        try:
            await callback.message.edit_text("⛔ Ulanish rad etildi.")
        except Exception:
            pass


@dp.message(Command("uzish"))
async def on_uzish(message: Message):
    _revoke_all()
    await message.answer("🔌 Barcha masofaviy ulanishlar uzildi.\n(Telegram orqali o'zingiz baribir ochasiz.)")

def get_main_keyboard() -> ReplyKeyboardMarkup:
    rows = []
    # Telegram Mini App faqat HTTPS URL qabul qiladi; aks holda /start crash bo'ladi.
    if WEB_APP_URL.startswith("https://"):
        rows.append([KeyboardButton(text="🌐 Mini App", web_app=WebAppInfo(url=WEB_APP_URL))])
    rows += [
        [KeyboardButton(text="📊 Holat"), KeyboardButton(text="📸 Skrinshot")],
        [KeyboardButton(text="📋 Menyu")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def menu_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🖥 Tizim", "menu:sys"), _btn("🎬 Media", "menu:media")],
        [_btn("⚡ Quvvat", "menu:power"), _btn("🧰 Vositalar", "menu:tools")],
    ])


def menu_sys() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 Holat", "menu:act:status"), _btn("💻 Jarayonlar", "menu:act:proc")],
        [_btn("📈 Grafik", "menu:act:graph"), _btn("📋 Clipboard", "menu:act:clip")],
        [_btn("🔒 Qulflash", "menu:act:lock")],
        [_btn("◀ Orqaga", "menu:home")],
    ])


def menu_media() -> InlineKeyboardMarkup:
    rec = _btn("⏹ Yozishni to'xtatish", "menu:act:recstop") if _rec["on"] else _btn("🎬 Ekran yozish", "menu:act:rec")
    face = _btn("🚫 Yuz kuzatuv OFF", "menu:act:faceoff") if _face["on"] else _btn("👤 Yuz kuzatuv", "menu:act:faceon")
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📸 Skrinshot", "menu:act:shot"), _btn("🎥 Live oqim", "menu:act:live")],
        [rec],
        [face],
        [_btn("◀ Orqaga", "menu:home")],
    ])


def menu_tools() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🤖 AI yordamchi", "menu:hint:ai")],
        [_btn("🌐 URL ochish", "menu:hint:open"), _btn("▶️ Dastur", "menu:hint:run")],
        [_btn("📋 Clipboard olish", "menu:act:clip"), _btn("📁 Fayl olish", "menu:hint:getfile")],
        [_btn("◀ Orqaga", "menu:home")],
    ])

def power_menu() -> InlineKeyboardMarkup:
    rec_btn = (
        InlineKeyboardButton(text="⏹ Yozishni to'xtatish", callback_data="pw:recstop")
        if _rec["on"]
        else InlineKeyboardButton(text="🎬 Ekran yozish", callback_data="pw:rec")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Qayta yuklash", callback_data="pw:r"),
             InlineKeyboardButton(text="🛑 O'chirish", callback_data="pw:s")],
            [InlineKeyboardButton(text="😴 Uxlash", callback_data="pw:sleep"),
             InlineKeyboardButton(text="🔒 Qulflash", callback_data="pw:lock")],
            [rec_btn],
            [InlineKeyboardButton(text="📸 Skrinshot", callback_data="pw:shot"),
             InlineKeyboardButton(text="📊 Holat", callback_data="pw:status")],
            [InlineKeyboardButton(text="✅ Rejani bekor qilish", callback_data="pw:cancel")],
        ]
    )


def delay_menu(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Darhol", callback_data=f"pw:go:{kind}:0")],
            [InlineKeyboardButton(text="⏱ 1 daqiqa", callback_data=f"pw:go:{kind}:60")],
            [InlineKeyboardButton(text="⏱ 5 daqiqa", callback_data=f"pw:go:{kind}:300")],
            [InlineKeyboardButton(text="◀ Orqaga", callback_data="pw:menu")],
        ]
    )


def build_confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, tasdiqlayman", callback_data=f"confirm_{action}"),
                InlineKeyboardButton(text="❌ Yo'q", callback_data="dismiss"),
            ]
        ]
    )


# ===== EKRAN YOZISH =====
REC_FPS = 10
REC_MAX_WIDTH = 1280
REC_MAX_SECONDS = 600  # xavfsizlik: 10 daqiqadan keyin avtomatik to'xtaydi
_rec = {"on": False, "thread": None, "path": None, "start": 0.0}


def _record_worker(path: str, flag):
    first = ImageGrab.grab()
    ow, oh = first.size
    if ow > REC_MAX_WIDTH:
        sc = REC_MAX_WIDTH / ow
        out_w, out_h = REC_MAX_WIDTH, int(oh * sc)
    else:
        out_w, out_h = ow, oh
    out_w -= out_w % 2
    out_h -= out_h % 2
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), REC_FPS, (out_w, out_h))
    interval = 1.0 / REC_FPS
    started = time.time()
    while flag() and (time.time() - started) < REC_MAX_SECONDS:
        t0 = time.time()
        frame = np.array(ImageGrab.grab())
        if (frame.shape[1], frame.shape[0]) != (out_w, out_h):
            frame = cv2.resize(frame, (out_w, out_h))
        writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        dt = time.time() - t0
        if dt < interval:
            time.sleep(interval - dt)
    writer.release()


async def start_recording() -> str:
    if _rec["on"]:
        return "⚠️ Yozib olish allaqachon boshlangan. To'xtatish: /stop"
    path = str(BASE_DIR / f"rec_{int(time.time())}.mp4")
    _rec.update(on=True, path=path, start=time.time())
    _rec["thread"] = threading.Thread(target=_record_worker, args=(path, lambda: _rec["on"]), daemon=True)
    _rec["thread"].start()
    return "🔴 Ekran yozib olinmoqda... To'xtatish uchun /stop yuboring."


_last_rec = {"path": None, "dur": 0}


def rec_format_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🎬 Media (video)", callback_data="rec:media"),
            InlineKeyboardButton(text="📄 Fayl (hujjat)", callback_data="rec:file"),
        ]]
    )


async def stop_recording(chat_id: int) -> str:
    if not _rec["on"]:
        return "Hozir yozib olish yo'q. Boshlash: /record"
    _rec["on"] = False
    th = _rec["thread"]
    if th:
        await asyncio.get_event_loop().run_in_executor(None, th.join)
    path = _rec["path"]
    dur = int(time.time() - _rec["start"])
    try:
        size = os.path.getsize(path)
    except OSError:
        return "❌ Video fayli topilmadi."
    if size > MAX_TELEGRAM_FILE_BYTES:
        try:
            os.remove(path)
        except OSError:
            pass
        return f"⚠️ Video {size // (1024**2)}MB — 50MB limitidan katta, yubora olmayman. ({dur}s)"
    _last_rec.update(path=path, dur=dur)
    mb = max(1, size // (1024**2))
    await bot.send_message(
        chat_id,
        f"🎬 Yozuv tayyor • {dur}s • ~{mb}MB\nQaysi formatda yuboray?",
        reply_markup=rec_format_keyboard(),
    )
    return ""

_last_alert_time: dict[str, float] = {}
_history: deque[tuple[float, float, float]] = deque(maxlen=HISTORY_MAX_SAMPLES)


def load_chats() -> set[int]:
    if CHATS_FILE.exists():
        return set(json.loads(CHATS_FILE.read_text()))
    return set()


def save_chats(chats: set[int]) -> None:
    CHATS_FILE.write_text(json.dumps(list(chats)))


def check_internet() -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3).close()
        return True
    except OSError:
        return False


def build_status_text() -> str:
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(os.sep)
    uptime_seconds = int(time.time() - psutil.boot_time())
    uptime = str(timedelta(seconds=uptime_seconds))
    net = psutil.net_io_counters()
    internet = "✅ ulangan" if check_internet() else "❌ ulanmagan"

    return (
        "🖥 *Kompyuter holati*\n\n"
        f"⚙️ CPU: {cpu}%\n"
        f"🧠 RAM: {mem.percent}% ({mem.used // (1024**2)} MB / {mem.total // (1024**2)} MB)\n"
        f"💾 Disk: {disk.percent}% ({disk.used // (1024**3)} GB / {disk.total // (1024**3)} GB)\n"
        f"⏱ Uptime: {uptime}\n"
        f"🌐 Internet: {internet}\n"
        f"📶 Tarmoq: ⬇ {net.bytes_recv // (1024**2)} MB / ⬆ {net.bytes_sent // (1024**2)} MB"
    )


def build_processes_text(top_n: int = 5) -> str:
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    by_cpu = sorted(procs, key=lambda p: p["cpu_percent"] or 0, reverse=True)[:top_n]
    by_ram = sorted(procs, key=lambda p: p["memory_percent"] or 0, reverse=True)[:top_n]

    lines = ["💻 *Top jarayonlar (CPU bo'yicha)*"]
    for p in by_cpu:
        lines.append(f"  {p['name']} (PID {p['pid']}) — {p['cpu_percent']:.1f}%")

    lines.append("\n🧠 *Top jarayonlar (RAM bo'yicha)*")
    for p in by_ram:
        lines.append(f"  {p['name']} (PID {p['pid']}) — {p['memory_percent']:.1f}%")

    return "\n".join(lines)


def is_screen_locked() -> bool:
    hdesktop = ctypes.windll.user32.OpenDesktopW("Default", 0, False, DESKTOP_SWITCHDESKTOP)
    if not hdesktop:
        return True
    try:
        return not ctypes.windll.user32.SwitchDesktop(hdesktop)
    finally:
        ctypes.windll.user32.CloseDesktop(hdesktop)


def build_graph_photo() -> BufferedInputFile | None:
    if len(_history) < 2:
        return None

    times = [datetime.fromtimestamp(t) for t, _, _ in _history]
    cpu_vals = [c for _, c, _ in _history]
    ram_vals = [r for _, _, r in _history]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(times, cpu_vals, label="CPU %", color="#e74c3c")
    ax.plot(times, ram_vals, label="RAM %", color="#3498db")
    ax.set_ylim(0, 100)
    ax.set_ylabel("%")
    ax.set_title("CPU / RAM tarixi")
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return BufferedInputFile(buf.read(), filename="graph.png")


def take_screenshot() -> BufferedInputFile:
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return BufferedInputFile(buf.read(), filename="screenshot.png")


def is_excluded_path(path: Path) -> bool:
    try:
        path.relative_to(BASE_DIR)
        return True
    except ValueError:
        pass

    if any(part.lower() in EXCLUDED_DIR_NAMES for part in path.parts):
        return True
    if path.suffix.lower() in EXCLUDED_EXTENSIONS:
        return True
    if path.name.startswith(".") or path.name.startswith("~$"):
        return True
    return False


_file_debounce: dict[str, float] = {}
_file_sent: dict[str, tuple[float, int]] = {}


async def handle_new_file(path: Path, is_update: bool = False):
    key = str(path)
    stamp = time.time()
    _file_debounce[key] = stamp
    # debounce: bir necha soniya kutamiz, agar yangi hodisa kelsa — o'shanisi yuboradi
    await asyncio.sleep(NEW_FILE_SETTLE_SECONDS)
    if _file_debounce.get(key, 0) > stamp:
        return
    try:
        if not path.is_file():
            return
        st = path.stat()
        size, mtime = st.st_size, st.st_mtime
        await asyncio.sleep(NEW_FILE_SETTLE_SECONDS)
        if _file_debounce.get(key, 0) > stamp:
            return
        if not path.is_file() or path.stat().st_size != size:
            return  # hali yozilmoqda
    except OSError:
        return

    # dedup: aynan shu (mtime, size) allaqachon yuborilgan bo'lsa, qayta yubormaymiz
    if _file_sent.get(key) == (mtime, size):
        return
    is_update = key in _file_sent
    _file_sent[key] = (mtime, size)

    chats = load_chats()
    if not chats:
        return

    label = "♻️ Fayl yangilandi" if is_update else "🆕 Yangi fayl"
    caption = f"{label}\n📄 `{path}`\n📦 {size / (1024**2):.2f} MB"
    for chat_id in chats:
        try:
            if size <= MAX_TELEGRAM_FILE_BYTES:
                await bot.send_document(chat_id, FSInputFile(path), caption=caption, parse_mode="Markdown")
            else:
                await bot.send_message(
                    chat_id, caption + "\n⚠️ Fayl 50MB dan katta, yubora olmayman.", parse_mode="Markdown"
                )
        except Exception as e:
            print(f"Fayl xabarini yuborishda xato ({chat_id}): {e}")


class NewFileHandler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def _submit(self, src):
        path = Path(src)
        if is_excluded_path(path):
            return
        asyncio.run_coroutine_threadsafe(handle_new_file(path), self.loop)

    def on_created(self, event):
        if not event.is_directory:
            self._submit(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._submit(event.src_path)

    def on_moved(self, event):
        # temp fayl → yakuniy nomga rename (Office, yuklab olishlar shunday ishlaydi)
        if not event.is_directory:
            self._submit(event.dest_path)


def start_file_watcher(loop: asyncio.AbstractEventLoop) -> Observer:
    handler = NewFileHandler(loop)
    observer = Observer()
    for folder in WATCH_FOLDERS:
        if folder.exists():
            observer.schedule(handler, str(folder), recursive=True)
    observer.start()
    return observer


@dp.message(CommandStart())
async def on_start(message: Message):
    chats = load_chats()
    chats.add(message.chat.id)
    save_chats(chats)
    await message.answer(
        "Salom! Endi kompyuteringiz holatini shu yerdan kuzatib borasiz.\n\n"
        "/status - hozirgi holat\n"
        "/processes - top jarayonlar\n"
        "/screenshot - ekran surati\n"
        "/lock - ekranni qulflash\n"
        "/restart confirm - qayta yuklash (60s kechikish)\n"
        "/shutdown confirm - o'chirish (60s kechikish)\n"
        "/cancel - rejalashtirilgan restart/shutdown'ni bekor qilish\n"
        "/getfile <yo'l> - faylni yuborish\n"
        "/kill <PID yoki nom> - jarayonni to'xtatish\n"
        "/graph - CPU/RAM tarixi grafigi\n"
        "/live - real vaqtda ekran oqimi (1.5 min)\n\n"
        f"Har {STATUS_INTERVAL_SECONDS // 60} daqiqada avtomatik xabar keladi, "
        f"CPU yoki RAM {CPU_ALERT_THRESHOLD}% dan oshsa ham ogohlantiraman.\n"
        "Kompyuter qulflansa/ochilsa va tizimga kirilganda ham xabar beraman.\n"
        "Desktop/Documents/Pictures/Videos/Music papkalarida paydo bo'lgan "
        "yangi fayllarni ham (tizim/vaqtinchalik fayllardan tashqari) avtomatik yuboraman.\n\n"
        "🌐 Mini App tugmasi — real vaqtda ekrani kuzatish va harakatlarga javob berish uchun.\n"
        "Pastdagi tugmalardan ham foydalanishingiz mumkin. /menu - tugmalarni qayta chiqarish.",
        reply_markup=get_main_keyboard(),
    )


@dp.message(Command("menu"))
async def on_menu(message: Message):
    await message.answer("Menyu:", reply_markup=get_main_keyboard())


@dp.message(Command("status"))
@dp.message(F.text == "📊 Holat")
async def on_status(message: Message):
    await message.answer(build_status_text(), parse_mode="Markdown")


@dp.message(Command("processes"))
@dp.message(F.text == "💻 Jarayonlar")
async def on_processes(message: Message):
    await message.answer(build_processes_text(), parse_mode="Markdown")


@dp.message(Command("screenshot"))
@dp.message(F.text == "📸 Skrinshot")
async def on_screenshot(message: Message):
    await message.answer_photo(take_screenshot())


@dp.message(Command("lock"))
@dp.message(F.text == "🔒 Qulflash")
async def on_lock(message: Message):
    ctypes.windll.user32.LockWorkStation()
    await message.answer("🔒 Ekran qulflandi.")


@dp.message(Command("graph"))
@dp.message(F.text == "📈 Grafik")
async def on_graph(message: Message):
    photo = build_graph_photo()
    if photo is None:
        await message.answer("Hali yetarli tarix yo'q, bir necha daqiqadan so'ng qayta urinib ko'ring.")
        return
    await message.answer_photo(photo)


@dp.message(F.text == "⚙️ Ko'proq")
async def on_more_menu(message: Message):
    await message.answer("⚙️ Boshqaruv:", reply_markup=power_menu())


@dp.message(F.text == "📋 Menyu")
async def on_menu_hub(message: Message):
    await message.answer("📋 Asosiy menyu:", reply_markup=menu_home())


_MENU_HINTS = {
    "ai": "🤖 AI yordamchi — kompyuterda vazifa bajaradi:\n`/ai eng katta 5 faylni top`\n`/ai qaysi dastur ko'p RAM ishlatyapti`",
    "open": "🌐 URL ochish uchun:\n`/open google.com`",
    "run": "▶️ Dastur ishga tushirish:\n`/run notepad`",
    "getfile": "📁 Faylni olish uchun:\n`/getfile C:\\\\yo'l\\\\fayl.txt`",
}


@dp.callback_query(F.data.startswith("menu:"))
async def on_menu_nav(callback: CallbackQuery):
    d = callback.data.split(":")
    sec = d[1]
    msg = callback.message
    cid = msg.chat.id
    if sec == "home":
        await msg.edit_text("📋 Asosiy menyu:", reply_markup=menu_home())
    elif sec == "sys":
        await msg.edit_text("🖥 Tizim:", reply_markup=menu_sys())
    elif sec == "media":
        await msg.edit_text("🎬 Media:", reply_markup=menu_media())
    elif sec == "power":
        await msg.edit_text("⚡ Quvvat:", reply_markup=power_menu())
    elif sec == "tools":
        await msg.edit_text("🧰 Vositalar:", reply_markup=menu_tools())
    elif sec == "hint":
        await bot.send_message(cid, _MENU_HINTS.get(d[2], ""), parse_mode="Markdown")
    elif sec == "act":
        a = d[2]
        if a == "status":
            await bot.send_message(cid, build_status_text(), parse_mode="Markdown")
        elif a == "proc":
            await bot.send_message(cid, build_processes_text(), parse_mode="Markdown")
        elif a == "graph":
            photo = build_graph_photo()
            await (bot.send_photo(cid, photo) if photo else bot.send_message(cid, "Hali tarix yetarli emas."))
        elif a == "shot":
            await bot.send_photo(cid, take_screenshot())
        elif a == "lock":
            ctypes.windll.user32.LockWorkStation()
            await bot.send_message(cid, "🔒 Ekran qulflandi.")
        elif a == "clip":
            await on_clip(msg)
        elif a == "live":
            await bot.send_message(cid, "🎥 Live uchun: /live buyrug'ini yuboring.")
        elif a == "rec":
            await bot.send_message(cid, await start_recording())
        elif a == "recstop":
            err = await stop_recording(cid)
            if err:
                await bot.send_message(cid, err)
        elif a == "faceon":
            await on_watchface(msg)
            await msg.edit_text("🎬 Media:", reply_markup=menu_media())
        elif a == "faceoff":
            await on_stopface(msg)
            await msg.edit_text("🎬 Media:", reply_markup=menu_media())
    await callback.answer()


@dp.callback_query(F.data.startswith("pw:"))
async def on_power(callback: CallbackQuery):
    parts = callback.data.split(":")
    act = parts[1]
    msg = callback.message
    if act == "menu":
        await msg.edit_text("⚙️ Boshqaruv:", reply_markup=power_menu())
    elif act == "r":
        await msg.edit_text("🔄 Qayta yuklash — qachon?", reply_markup=delay_menu("r"))
    elif act == "s":
        await msg.edit_text("🛑 O'chirish — qachon?", reply_markup=delay_menu("s"))
    elif act == "go":
        kind, delay = parts[2], int(parts[3])
        flag = "/r" if kind == "r" else "/s"
        subprocess.run(["shutdown", flag, "/t", str(delay), "/f"])
        verb = "Qayta yuklash" if kind == "r" else "O'chirish"
        when = "darhol" if delay == 0 else f"{delay} soniyadan so'ng"
        await msg.edit_text(f"✅ {verb}: {when}. Bekor qilish: /cancel")
    elif act == "sleep":
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
        await msg.edit_text("😴 Uxlash rejimiga o'tkazildi.")
    elif act == "lock":
        ctypes.windll.user32.LockWorkStation()
        await msg.edit_text("🔒 Ekran qulflandi.", reply_markup=power_menu())
    elif act == "rec":
        await msg.edit_text(await start_recording(), reply_markup=power_menu())
    elif act == "recstop":
        await msg.edit_text("⏳ Video tayyorlanmoqda...")
        err = await stop_recording(msg.chat.id)
        if err:
            await bot.send_message(msg.chat.id, err, reply_markup=power_menu())
    elif act == "shot":
        await bot.send_photo(msg.chat.id, take_screenshot())
    elif act == "status":
        await bot.send_message(msg.chat.id, build_status_text(), parse_mode="Markdown")
    elif act == "cancel":
        subprocess.run(["shutdown", "/a"])
        await msg.edit_text("✅ Rejalashtirilgan restart/shutdown bekor qilindi.", reply_markup=power_menu())
    await callback.answer()


@dp.callback_query(F.data.startswith("rec:"))
async def on_rec_format(callback: CallbackQuery):
    kind = callback.data.split(":")[1]
    path = _last_rec["path"]
    if not path or not os.path.exists(path):
        await callback.message.edit_text("❌ Fayl topilmadi (eskirgan yoki yuborilgan).")
        await callback.answer()
        return
    await callback.answer("Yuborilmoqda...")
    dur = _last_rec["dur"]
    try:
        if kind == "media":
            await bot.send_video(callback.message.chat.id, FSInputFile(path), caption=f"🎬 Ekran yozuvi • {dur}s")
        else:
            await bot.send_document(callback.message.chat.id, FSInputFile(path), caption=f"📄 Ekran yozuvi • {dur}s")
        await callback.message.edit_text("✅ Yuborildi.")
    except Exception as e:
        await callback.message.edit_text(f"❌ Xato: {e}")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
        _last_rec["path"] = None


@dp.message(Command("record"))
async def on_record(message: Message):
    await message.answer(await start_recording())


@dp.message(Command("stop"))
async def on_stop(message: Message):
    err = await stop_recording(message.chat.id)
    if err:
        await message.answer(err)


@dp.message(Command("restart"))
async def on_restart(message: Message, command: CommandObject):
    if (command.args or "").strip() != "confirm":
        await message.answer(
            f"⚠️ Kompyuter {SHUTDOWN_DELAY_SECONDS} soniyadan so'ng qayta yuklanadi.\n"
            "Tasdiqlash uchun: `/restart confirm`\n"
            "Bekor qilish uchun: `/cancel`",
            parse_mode="Markdown",
        )
        return
    subprocess.run(["shutdown", "/r", "/t", str(SHUTDOWN_DELAY_SECONDS)])
    await message.answer(f"🔄 Qayta yuklash {SHUTDOWN_DELAY_SECONDS}s dan so'ng bo'ladi. Bekor qilish: /cancel")


@dp.message(Command("shutdown"))
async def on_shutdown(message: Message, command: CommandObject):
    if (command.args or "").strip() != "confirm":
        await message.answer(
            f"⚠️ Kompyuter {SHUTDOWN_DELAY_SECONDS} soniyadan so'ng o'chadi.\n"
            "Tasdiqlash uchun: `/shutdown confirm`\n"
            "Bekor qilish uchun: `/cancel`",
            parse_mode="Markdown",
        )
        return
    subprocess.run(["shutdown", "/s", "/t", str(SHUTDOWN_DELAY_SECONDS)])
    await message.answer(f"🛑 O'chirish {SHUTDOWN_DELAY_SECONDS}s dan so'ng bo'ladi. Bekor qilish: /cancel")


@dp.message(Command("cancel"))
async def on_cancel(message: Message):
    subprocess.run(["shutdown", "/a"])
    await message.answer("✅ Rejalashtirilgan restart/shutdown bekor qilindi (agar mavjud bo'lsa).")


@dp.message(Command("getfile"))
async def on_getfile(message: Message, command: CommandObject):
    path_str = (command.args or "").strip().strip('"')
    if not path_str:
        await message.answer("Foydalanish: `/getfile C:\\yo'l\\fayl.txt`", parse_mode="Markdown")
        return

    path = Path(path_str)
    if not path.is_file():
        await message.answer("❌ Bunday fayl topilmadi.")
        return

    size = path.stat().st_size
    if size > MAX_TELEGRAM_FILE_BYTES:
        await message.answer(f"❌ Fayl juda katta ({size // (1024**2)} MB). Limit: 50 MB.")
        return

    await message.answer_document(FSInputFile(path))


@dp.message(Command("kill"))
async def on_kill(message: Message, command: CommandObject):
    target = (command.args or "").strip()
    if not target:
        await message.answer("Foydalanish: `/kill <PID yoki dastur nomi>`", parse_mode="Markdown")
        return

    killed = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            match = str(p.info["pid"]) == target or p.info["name"].lower() == target.lower()
            if match:
                p.terminate()
                killed.append(f"{p.info['name']} (PID {p.info['pid']})")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if killed:
        await message.answer("✅ To'xtatildi:\n" + "\n".join(killed))
    else:
        await message.answer("❌ Mos jarayon topilmadi.")


@dp.message(Command("graph"))
async def on_graph(message: Message):
    photo = build_graph_photo()
    if photo is None:
        await message.answer("Hali yetarli tarix yo'q, bir necha daqiqadan so'ng qayta urinib ko'ring.")
        return
    await message.answer_photo(photo)


_live_sessions: dict[int, bool] = {}


@dp.message(Command("live"))
async def on_live(message: Message):
    chat_id = message.chat.id
    if chat_id in _live_sessions and _live_sessions[chat_id]:
        await message.answer("⏹️ Live kuzatish allaqachon ishlamoquyabdi. /stop_live bilan to'xtatang.")
        return

    _live_sessions[chat_id] = True
    await message.answer("🔴 Live ekran kuzatishi boshlanadi... (har 3s, /stop_live bilan to'xtat)")

    try:
        for _ in range(30):  # 30 x 3s = 1.5 min
            if not _live_sessions.get(chat_id, False):
                break
            try:
                await bot.send_photo(chat_id, take_screenshot())
            except Exception as e:
                print(f"Live screenshot yuborishda xato: {e}")
                break
            await asyncio.sleep(3)
    finally:
        _live_sessions[chat_id] = False
        try:
            await bot.send_message(chat_id, "🟢 Live ekran kuzatishi tugadi.")
        except:
            pass


@dp.message(Command("stop_live"))
async def on_stop_live(message: Message):
    _live_sessions[message.chat.id] = False
    await message.answer("✅ Live to'xtatildi.")


async def periodic_broadcast():
    while True:
        await asyncio.sleep(STATUS_INTERVAL_SECONDS)
        chats = load_chats()
        if not chats:
            continue
        text = build_status_text()
        for chat_id in chats:
            try:
                await bot.send_message(chat_id, text, parse_mode="Markdown")
            except Exception as e:
                print(f"Xabar yuborishda xato ({chat_id}): {e}")


async def periodic_alerts():
    while True:
        await asyncio.sleep(ALERT_CHECK_INTERVAL_SECONDS)
        chats = load_chats()
        if not chats:
            continue

        now = time.time()
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent

        alerts = []
        if cpu >= CPU_ALERT_THRESHOLD and now - _last_alert_time.get("cpu", 0) > ALERT_COOLDOWN_SECONDS:
            alerts.append(f"⚠️ CPU yuklamasi yuqori: {cpu}%")
            _last_alert_time["cpu"] = now
        if ram >= RAM_ALERT_THRESHOLD and now - _last_alert_time.get("ram", 0) > ALERT_COOLDOWN_SECONDS:
            alerts.append(f"⚠️ RAM yuklamasi yuqori: {ram}%")
            _last_alert_time["ram"] = now

        if not alerts:
            continue

        text = "\n".join(alerts)
        for chat_id in chats:
            try:
                await bot.send_message(chat_id, text)
            except Exception as e:
                print(f"Ogohlantirish yuborishda xato ({chat_id}): {e}")


async def history_sampler():
    while True:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        _history.append((time.time(), cpu, ram))
        await asyncio.sleep(HISTORY_SAMPLE_SECONDS)


async def lock_watcher():
    was_locked = is_screen_locked()
    while True:
        await asyncio.sleep(LOCK_POLL_SECONDS)
        chats = load_chats()
        now_locked = is_screen_locked()
        if now_locked != was_locked:
            text = "🔒 Kompyuter qulflandi." if now_locked else "🔓 Kompyuter qulfdan chiqarildi."
            for chat_id in chats:
                try:
                    await bot.send_message(chat_id, text)
                except Exception as e:
                    print(f"Xabar yuborishda xato ({chat_id}): {e}")
            was_locked = now_locked


async def set_bot_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="Botni ishga tushirish / menyu"),
        BotCommand(command="status", description="Hozirgi holat (CPU, RAM, disk, uptime)"),
        BotCommand(command="processes", description="Top jarayonlar (CPU/RAM)"),
        BotCommand(command="screenshot", description="Ekran surati"),
        BotCommand(command="lock", description="Ekranni qulflash"),
        BotCommand(command="restart", description="Qayta yuklash (confirm bilan)"),
        BotCommand(command="shutdown", description="O'chirish (confirm bilan)"),
        BotCommand(command="cancel", description="Restart/shutdown'ni bekor qilish"),
        BotCommand(command="getfile", description="Fayl yuborish (/getfile <yo'l>)"),
        BotCommand(command="kill", description="Jarayonni to'xtatish (/kill <PID/nom>)"),
        BotCommand(command="graph", description="CPU/RAM tarixi grafigi"),
        BotCommand(command="menu", description="Tugmali menyuni ko'rsatish"),
        BotCommand(command="live", description="Real vaqtda ekran kuzatish (1.5 min)"),
        BotCommand(command="stop_live", description="Live kuzatishni to'xtatish"),
        BotCommand(command="record", description="Ekranni videoga yozib olishni boshlash"),
        BotCommand(command="stop", description="Ekran yozuvini to'xtatib, videoni yuborish"),
        BotCommand(command="ai", description="AI yordamchi — kompyuterda vazifa bajaradi"),
        BotCommand(command="ai_reset", description="AI suhbatini tozalash (yangi sessiya)"),
        BotCommand(command="open", description="Brauzerda URL ochish (/open google.com)"),
        BotCommand(command="run", description="Dastur ishga tushirish (/run notepad)"),
        BotCommand(command="clip", description="Kompyuter clipboard matnini olish"),
        BotCommand(command="setclip", description="Clipboard'ga matn yozish (/setclip matn)"),
        BotCommand(command="watchface", description="Kamera: yuz ko'rinsa rasm yuborish"),
        BotCommand(command="stopface", description="Yuz kuzatuvini to'xtatish"),
        BotCommand(command="lastrec", description="Oxirgi 10 daqiqa ekran yozuvini olish"),
        BotCommand(command="dvr", description="Doimiy yozib borishni yoqish/o'chirish"),
        BotCommand(command="uzish", description="Barcha masofaviy ulanishlarni uzish"),
    ])


async def notify_startup():
    chats = load_chats()
    for chat_id in chats:
        try:
            await bot.send_message(chat_id, "🟢 Kompyuter yoqildi / tizimga kirildi. Bot ishga tushdi.")
        except Exception as e:
            print(f"Xabar yuborishda xato ({chat_id}): {e}")


def _find_claude_exe():
    ext = Path.home() / ".vscode" / "extensions"
    matches = sorted(ext.glob("anthropic.claude-code-*/resources/native-binary/claude.exe"))
    return str(matches[-1]) if matches else None


CLAUDE_EXE = _find_claude_exe()
_ai_busy = False


def _latest_session_id():
    proj = Path.home() / ".claude" / "projects"
    jsonls = []
    for d in list(proj.glob("*Documents-remote")) + list(proj.glob("*remote")):
        jsonls += list(d.glob("*.jsonl"))
    if not jsonls:
        return None
    return max(jsonls, key=lambda f: f.stat().st_mtime).stem


# ── Dedicated AI sessiya ─────────────────────────────────────
# /ai uchun alohida, barqaror sessiya. Har safar ulkan VS Code chatini
# fork qilish (8.8 MB!) sekin/bo'sh natija berardi. Buning o'rniga bitta
# o'z sessiyamizni yaratib, keyingi so'rovlarda o'shani davom ettiramiz.
AI_SESSION_FILE = BASE_DIR / ".ai_session"


def _load_ai_session():
    try:
        sid = AI_SESSION_FILE.read_text(encoding="utf-8").strip()
        return sid or None
    except Exception:
        return None


def _save_ai_session(sid: str) -> None:
    try:
        if sid:
            AI_SESSION_FILE.write_text(sid, encoding="utf-8")
    except Exception:
        pass


def _run_claude(task: str) -> str:
    args = [CLAUDE_EXE, "-p", task, "--output-format", "text", "--dangerously-skip-permissions"]
    sid = _latest_session_id()
    if sid:
        # Joriy VS Code chatini fork qilamiz — shu suhbat konteksti bor, jonli sessiya buzilmaydi
        args += ["--resume", sid, "--fork-session"]
    try:
        r = subprocess.run(
            args, capture_output=True, encoding="utf-8", errors="replace",
            timeout=900, cwd=str(BASE_DIR),
        )
        out = (r.stdout or "").strip()
        if not out and r.stderr:
            out = "⚠️ " + r.stderr.strip()[:1500]
        return out or "(natija bo'sh)"
    except subprocess.TimeoutExpired:
        return "⏱️ Timeout (10 daqiqa) — vazifa juda uzoq davom etdi."
    except Exception as e:
        return f"❌ Xato: {e}"


def _summarize_tool(name, inp):
    inp = inp or {}
    n = str(name or "")
    if n == "Bash":
        return "🔧 Bash: " + str(inp.get("command", ""))[:90]
    if n == "Read":
        return "📖 Read: " + str(inp.get("file_path", ""))
    if n in ("Edit", "Write", "NotebookEdit"):
        return "✏️ " + n + ": " + str(inp.get("file_path", ""))
    if n == "Grep":
        return "🔍 Grep: " + str(inp.get("pattern", ""))[:70]
    if n == "Glob":
        return "🔍 Glob: " + str(inp.get("pattern", ""))[:70]
    if n == "TodoWrite":
        return "📝 Reja yangilandi"
    if n in ("WebFetch", "WebSearch"):
        return "🌐 " + n + ": " + str(inp.get("url") or inp.get("query", ""))[:70]
    return "🔧 " + (n or "tool")


async def _run_claude_stream(message: Message, task: str):
    recent = _recent_activity(15)
    if recent:
        task = (
            "[Bot orqali kelgan oxirgi buyruqlar jurnali — kerak bo'lsa foydalaning]\n"
            f"{recent}\n\n[Foydalanuvchi vazifasi]\n{task}"
        )
    args = [CLAUDE_EXE, "-p", task, "--output-format", "stream-json", "--verbose",
            "--dangerously-skip-permissions"]
    # Ulkan VS Code chatini fork qilmaymiz — o'zimizning barqaror sessiyamiz.
    ai_sid = _load_ai_session()
    if ai_sid:
        args += ["--resume", ai_sid]  # o'sha dedicated chatni davom ettiramiz (fork emas)

    progress = await message.answer("🤖 Boshlanmoqda...")
    log = []
    final = ""
    is_error = [False]
    new_sid = [""]
    last_assistant_text = [""]
    last_edit = [0.0]
    last_text = [""]

    async def flush(force=False):
        now = time.time()
        if not force and now - last_edit[0] < 2.5:
            return
        text = ("🤖 Ishlayapman...\n\n" + "\n".join(log[-16:]))[:4000]
        if text == last_text[0]:
            return
        last_text[0] = text
        last_edit[0] = now
        try:
            await progress.edit_text(text)
        except Exception:
            pass

    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(BASE_DIR),
        )
    except Exception as e:
        await progress.edit_text(f"❌ Ishga tushmadi: {e}")
        return

    # stderr ni alohida oqimda yig'amiz (pipe to'lib qolib deadlock bo'lmasin)
    stderr_buf = []

    async def _drain_stderr():
        try:
            while True:
                ln = await proc.stderr.readline()
                if not ln:
                    break
                stderr_buf.append(ln.decode("utf-8", "replace"))
        except Exception:
            pass

    stderr_task = asyncio.create_task(_drain_stderr())

    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                ev = json.loads(line.decode("utf-8", "replace"))
            except Exception:
                continue
            if ev.get("session_id"):
                new_sid[0] = ev["session_id"]
            t = ev.get("type")
            if t == "assistant":
                for block in ev.get("message", {}).get("content", []):
                    bt = block.get("type")
                    if bt == "tool_use":
                        log.append(_summarize_tool(block.get("name"), block.get("input")))
                        await flush()
                    elif bt == "text":
                        txt = (block.get("text") or "").strip()
                        if txt:
                            last_assistant_text[0] = txt
                            log.append("💬 " + txt[:140])
                            await flush()
            elif t == "result":
                if ev.get("is_error") or ev.get("subtype") not in (None, "success"):
                    is_error[0] = True
                final = ev.get("result", "") or final
        await proc.wait()
    except Exception as e:
        log.append("⚠️ " + str(e))
    finally:
        try:
            await asyncio.wait_for(stderr_task, timeout=5)
        except Exception:
            stderr_task.cancel()

    await flush(force=True)

    # Yangi/dedicated sessiyani saqlab qolamiz (keyingi /ai davom etsin)
    if new_sid[0] and new_sid[0] != ai_sid:
        _save_ai_session(new_sid[0])

    err_tail = ("".join(stderr_buf)).strip()

    # Natijani ishonchli tanlaymiz — endi hech qachon "sabab'siz bo'sh" bo'lmaydi
    if final and not is_error[0]:
        result_text = final
    elif last_assistant_text[0]:
        result_text = last_assistant_text[0]
    elif log:
        result_text = "✅ Bajarilgan amallar:\n\n" + "\n".join(log[-20:])
    elif err_tail:
        result_text = "⚠️ AI xatosi:\n\n" + err_tail[-1500:]
    else:
        rc = proc.returncode
        result_text = (
            f"⚠️ Natija bo'sh (exit={rc}). "
            "Sessiya buzilган bo'lishi mumkin — `/ai_reset` bilan yangilang."
        )
    if is_error[0] and err_tail and err_tail[-800:] not in result_text:
        result_text += "\n\n⚠️ " + err_tail[-800:]

    try:
        await progress.edit_text("✅ Tugadi! Natija:")
    except Exception:
        pass
    for i in range(0, len(result_text), 4000):
        await message.answer(result_text[i:i + 4000])


@dp.message(Command("ai"))
async def on_ai(message: Message, command: CommandObject):
    global _ai_busy
    task = (command.args or "").strip()
    if not task:
        await message.answer(
            "🤖 *AI yordamchi* — kompyuterda vazifa bajaraman.\n\n"
            "Foydalanish: `/ai <vazifa>`\n"
            "Masalan:\n"
            "`/ai eng katta 5 faylni top`\n"
            "`/ai qaysi dastur ko'p RAM ishlatyapti`\n"
            "`/ai bugungi rasmlarni sanab ber`",
            parse_mode="Markdown",
        )
        return
    if not CLAUDE_EXE or not os.path.exists(CLAUDE_EXE):
        await message.answer("❌ Claude CLI topilmadi.")
        return
    if _ai_busy:
        await message.answer("⏳ AI hozir band — oldingi vazifa tugashini kuting.")
        return
    _ai_busy = True
    try:
        await _run_claude_stream(message, task)
    finally:
        _ai_busy = False


@dp.message(Command("ai_reset"))
async def on_ai_reset(message: Message):
    try:
        if AI_SESSION_FILE.exists():
            AI_SESSION_FILE.unlink()
        await message.answer("♻️ AI suhbati tozalandi — keyingi /ai yangi sessiyada boshlanadi.")
    except Exception as e:
        await message.answer(f"❌ Tozalab bo'lmadi: {e}")


@dp.message(Command("open"))
async def on_open(message: Message, command: CommandObject):
    arg = (command.args or "").strip()
    if not arg:
        await message.answer("Foydalanish: `/open google.com` yoki `/open https://...`", parse_mode="Markdown")
        return
    url = arg if arg.startswith(("http://", "https://")) else "https://" + arg
    try:
        os.startfile(url)
        await message.answer(f"🌐 Brauzerda ochilmoqda:\n{url}")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")


@dp.message(Command("run"))
async def on_run(message: Message, command: CommandObject):
    cmd = (command.args or "").strip()
    if not cmd:
        await message.answer("Foydalanish: `/run notepad` yoki `/run calc`", parse_mode="Markdown")
        return
    try:
        subprocess.Popen(cmd, shell=True)
        await message.answer(f"▶️ Ishga tushirildi: `{cmd}`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")


@dp.message(Command("clip"))
async def on_clip(message: Message):
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            capture_output=True, text=True, timeout=10,
        )
        text = (out.stdout or "").strip()
        if not text:
            await message.answer("📋 Clipboard bo'sh yoki matn emas.")
        elif len(text) > 4000:
            await message.answer_document(
                BufferedInputFile(text.encode("utf-8"), filename="clipboard.txt"),
                caption="📋 Clipboard (uzun matn)",
            )
        else:
            await message.answer(f"📋 Clipboard:\n\n{text}")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")


@dp.message(Command("setclip"))
async def on_setclip(message: Message, command: CommandObject):
    text = command.args or ""
    if not text:
        await message.answer("Foydalanish: `/setclip yoziladigan matn`", parse_mode="Markdown")
        return
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard", "-Value", text], timeout=10)
        await message.answer("✅ Kompyuter clipboard'iga yozildi.")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")


# ===== YUZ ANIQLASH (kamera) =====
FACE_COOLDOWN_SECONDS = 30
_face = {"on": False, "thread": None}
_face_cascade = None


def _get_cascade():
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return _face_cascade


async def _send_face(jpeg_bytes: bytes, n: int):
    chats = load_chats()
    caption = f"👤 {n} ta yuz aniqlandi! ({datetime.now():%H:%M:%S})"
    for cid in chats:
        try:
            await bot.send_photo(cid, BufferedInputFile(jpeg_bytes, "face.jpg"), caption=caption)
        except Exception as e:
            print(f"Yuz rasmini yuborishda xato: {e}")


def _face_worker(loop, flag):
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        asyncio.run_coroutine_threadsafe(_notify_face_error(loop), loop)
        return
    cascade = _get_cascade()
    last_sent = 0.0
    try:
        while flag():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.5)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
            if len(faces) > 0 and (time.time() - last_sent) > FACE_COOLDOWN_SECONDS:
                last_sent = time.time()
                for (x, y, w, h) in faces:
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                ok, buf = cv2.imencode(".jpg", frame)
                if ok:
                    asyncio.run_coroutine_threadsafe(_send_face(buf.tobytes(), len(faces)), loop)
            time.sleep(0.2)
    finally:
        cap.release()


async def _notify_face_error(loop):
    chats = load_chats()
    for cid in chats:
        try:
            await bot.send_message(cid, "❌ Kamera ochilmadi (band yoki mavjud emas).")
        except Exception:
            pass


@dp.message(Command("watchface"))
async def on_watchface(message: Message):
    if _face["on"]:
        await message.answer("📷 Yuz kuzatuvi allaqachon yoqilgan. To'xtatish: /stopface")
        return
    _face["on"] = True
    _face["thread"] = threading.Thread(
        target=_face_worker, args=(asyncio.get_running_loop(), lambda: _face["on"]), daemon=True
    )
    _face["thread"].start()
    await message.answer(
        "📷 Yuz kuzatuvi yoqildi. Kamera oldida yuz ko'ringanda rasm yuboraman.\n"
        f"(Har {FACE_COOLDOWN_SECONDS}s da bir marta) To'xtatish: /stopface"
    )


@dp.message(Command("stopface"))
async def on_stopface(message: Message):
    if not _face["on"]:
        await message.answer("Yuz kuzatuvi yoqilmagan. Yoqish: /watchface")
        return
    _face["on"] = False
    await message.answer("📷 Yuz kuzatuvi o'chirildi.")


# ===== DVR: doimiy yozib borish (oxirgi 10 daqiqa) =====
DVR_DIR = BASE_DIR / "dvr"
DVR_FPS = 8
DVR_MAX_WIDTH = 1280
DVR_SEGMENT_SECONDS = 30
DVR_KEEP_SECONDS = 11 * 60
_dvr = {"on": False, "thread": None}


def _dvr_cleanup():
    now = time.time()
    for f in DVR_DIR.glob("seg_*.mp4"):
        try:
            if now - int(f.stem.split("_")[1]) > DVR_KEEP_SECONDS:
                f.unlink()
        except (ValueError, OSError, IndexError):
            pass


def _dvr_worker(flag):
    DVR_DIR.mkdir(exist_ok=True)
    interval = 1.0 / DVR_FPS
    W = H = None
    while flag():
        try:
            # Ekran o'lchamini aniqlaymiz. Boot/qulf paytida ekran tayyor
            # bo'lmasligi mumkin — o'lchamni None qilib qayta urinamiz (thread o'lmaydi).
            if W is None:
                ow, oh = ImageGrab.grab().size
                if ow > DVR_MAX_WIDTH:
                    sc = DVR_MAX_WIDTH / ow
                    W, H = DVR_MAX_WIDTH, int(oh * sc)
                else:
                    W, H = ow, oh
                W -= W % 2
                H -= H % 2
            seg_start = time.time()
            path = str(DVR_DIR / f"seg_{int(seg_start)}.mp4")
            writer = imageio.get_writer(
                path, fps=DVR_FPS, codec="libx264", quality=5,
                macro_block_size=None, output_params=["-preset", "ultrafast"],
            )
            try:
                while flag() and (time.time() - seg_start) < DVR_SEGMENT_SECONDS:
                    t0 = time.time()
                    frame = np.array(ImageGrab.grab())
                    if (frame.shape[1], frame.shape[0]) != (W, H):
                        frame = cv2.resize(frame, (W, H))
                    writer.append_data(frame)
                    dt = time.time() - t0
                    if dt < interval:
                        time.sleep(interval - dt)
            finally:
                try:
                    writer.close()
                except Exception:
                    pass
            _dvr_cleanup()
        except Exception as e:
            # Har qanday xato — thread o'lmaydi, 3s dan keyin qayta urinadi
            print(f"DVR worker xatosi (qayta urinilmoqda): {e}")
            W = H = None
            time.sleep(3)


def _dvr_compile(minutes: int = 10):
    now = time.time()
    cutoff = now - minutes * 60 - DVR_SEGMENT_SECONDS
    segs = []
    for f in DVR_DIR.glob("seg_*.mp4"):
        try:
            ts = int(f.stem.split("_")[1])
            if ts >= cutoff:
                segs.append((ts, f))
        except (ValueError, IndexError):
            pass
    segs.sort()
    # Ayni damda yozilayotgan (tugallanmagan) oxirgi segmentni chiqarib tashlaymiz —
    # aks holda ffmpeg uni ocholmay "Invalid data" beradi.
    if segs and (now - segs[-1][0]) < DVR_SEGMENT_SECONDS:
        segs = segs[:-1]
    if not segs:
        return None
    out = str(BASE_DIR / f"lastrec_{int(now)}.mp4")
    list_path = str(DVR_DIR / "concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as lf:
        for _, f in segs:
            lf.write(f"file '{f.as_posix()}'\n")
    try:
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0",
             "-i", list_path, "-c", "copy", out],
            capture_output=True, timeout=120,
        )
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return out
    except Exception as e:
        print(f"DVR concat xato: {e}")
    return None


def _dvr_start():
    # Thread tirik bo'lmasa (o'lgan bo'lsa) qayta ishga tushiramiz
    t = _dvr.get("thread")
    if _dvr["on"] and t is not None and t.is_alive():
        return
    _dvr["on"] = True
    _dvr["thread"] = threading.Thread(target=_dvr_worker, args=(lambda: _dvr["on"],), daemon=True)
    _dvr["thread"].start()


async def dvr_watchdog():
    # DVR yoqiq bo'lsa-yu thread o'lgan bo'lsa — avtomatik qayta tiklaydi
    while True:
        await asyncio.sleep(60)
        try:
            t = _dvr.get("thread")
            if _dvr["on"] and (t is None or not t.is_alive()):
                print("DVR watchdog: thread o'lgan, qayta ishga tushirilmoqda")
                _dvr_start()
        except Exception:
            pass


@dp.message(Command("lastrec"))
async def on_lastrec(message: Message, command: CommandObject):
    if not _dvr["on"]:
        await message.answer("DVR o'chirilgan. Yoqish: /dvr")
        return
    mins = 10
    if command.args:
        try:
            mins = max(1, min(10, int(command.args.strip())))
        except ValueError:
            pass
    await message.answer(f"⏳ Oxirgi {mins} daqiqa tayyorlanmoqda...")
    out = await asyncio.get_running_loop().run_in_executor(None, _dvr_compile, mins)
    if not out:
        await message.answer("Hali yozuv yetarli emas (DVR yaqinda yoqilgan, bir oz kuting).")
        return
    try:
        size = os.path.getsize(out)
        if size > MAX_TELEGRAM_FILE_BYTES:
            await message.answer(f"⚠️ Video {size // (1024**2)}MB — 50MB dan katta. Kamroq: `/lastrec 5`", parse_mode="Markdown")
        else:
            await message.answer_video(FSInputFile(out), caption=f"🎥 Oxirgi {mins} daqiqa (DVR)")
    finally:
        try:
            os.remove(out)
        except OSError:
            pass


@dp.message(Command("dvr"))
async def on_dvr(message: Message):
    if _dvr["on"]:
        _dvr["on"] = False
        await message.answer("⏹ DVR o'chirildi (doimiy yozish to'xtatildi).")
    else:
        _dvr_start()
        await message.answer(
            "🔴 DVR yoqildi — ekran doimiy yozib borilmoqda.\n"
            "Oxirgi 10 daqiqa saqlanadi. Olish: /lastrec (yoki /lastrec 5)"
        )


async def main():
    await set_bot_commands()
    await notify_startup()
    _dvr_start()
    asyncio.create_task(periodic_broadcast())
    asyncio.create_task(periodic_alerts())
    asyncio.create_task(history_sampler())
    asyncio.create_task(lock_watcher())
    asyncio.create_task(dvr_watchdog())
    start_file_watcher(asyncio.get_running_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
