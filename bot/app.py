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
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import psutil
from aiogram import Bot, Dispatcher, F
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
MAX_TELEGRAM_FILE_BYTES = 50 * 1024 * 1024

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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.message.filter(F.from_user.id == OWNER_ID)
dp.callback_query.filter(F.from_user.id == OWNER_ID)

def get_main_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📊 Holat"), KeyboardButton(text="💻 Jarayonlar")],
        [KeyboardButton(text="📸 Skrinshot"), KeyboardButton(text="📈 Grafik")],
    ]
    # Telegram Mini App faqat HTTPS URL qabul qiladi; aks holda /start crash bo'ladi.
    if WEB_APP_URL.startswith("https://"):
        rows.append([KeyboardButton(text="🌐 Mini App", web_app=WebAppInfo(url=WEB_APP_URL))])
    rows.append([KeyboardButton(text="🔒 Qulflash"), KeyboardButton(text="⚙️ Ko'proq")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

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
        if size > MAX_TELEGRAM_FILE_BYTES:
            return f"⚠️ Video {size // (1024**2)}MB — 50MB dan katta, yubora olmayman. ({dur}s)"
        await bot.send_video(chat_id, FSInputFile(path), caption=f"🎬 Ekran yozuvi • {dur}s")
        return ""
    except Exception as e:
        return f"❌ Xato: {e}"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

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
        await bot.send_message(msg.chat.id, err or "✅ Yozuv yuborildi.", reply_markup=power_menu())
    elif act == "shot":
        await bot.send_photo(msg.chat.id, take_screenshot())
    elif act == "status":
        await bot.send_message(msg.chat.id, build_status_text(), parse_mode="Markdown")
    elif act == "cancel":
        subprocess.run(["shutdown", "/a"])
        await msg.edit_text("✅ Rejalashtirilgan restart/shutdown bekor qilindi.", reply_markup=power_menu())
    await callback.answer()


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
    ])


async def notify_startup():
    chats = load_chats()
    for chat_id in chats:
        try:
            await bot.send_message(chat_id, "🟢 Kompyuter yoqildi / tizimga kirildi. Bot ishga tushdi.")
        except Exception as e:
            print(f"Xabar yuborishda xato ({chat_id}): {e}")


async def main():
    await set_bot_commands()
    await notify_startup()
    asyncio.create_task(periodic_broadcast())
    asyncio.create_task(periodic_alerts())
    asyncio.create_task(history_sampler())
    asyncio.create_task(lock_watcher())
    start_file_watcher(asyncio.get_running_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
