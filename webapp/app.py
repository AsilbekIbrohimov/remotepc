import asyncio
import base64
import ctypes
import hashlib
import hmac
import io
import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qsl

import aiohttp
import numpy as np
import cv2
from aiohttp import web
from PIL import ImageGrab, ImageDraw
from dotenv import load_dotenv

# Tez ekran olish: dxcam (DXGI, GPU-tez ~100+fps). Bo'lmasa mss, u ham bo'lmasa PIL.
# ON-DEMAND: faqat oqim (Mini App ochiq) bo'lganda grab qilinadi -> bekorga yuk yo'q.
_HAS_DX = False
_dx_last = {"frame": None}
try:
    import dxcam
    _dx = dxcam.create(output_color="BGR")
    _HAS_DX = True
except Exception as _e:
    _dx = None
try:
    import mss as _mss_mod
except Exception:
    _mss_mod = None

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

OWNER_ID = int(os.environ["TG_OWNER_ID"])
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip().strip("'\"")
MAX_TG_BYTES = 50 * 1024 * 1024

# Bot API bazasi (lokal server yoqilgan bo'lsa 2GB limit)
_USE_LOCAL = os.environ.get("USE_LOCAL_BOT_API", "").strip() in ("1", "true", "yes")
_BOT_API_BASE = (os.environ.get("LOCAL_BOT_API_URL", "http://127.0.0.1:8081").strip()
                 if _USE_LOCAL else "https://api.telegram.org")

# Bot orqali ruxsat berilgan sessiyalar (bot yozadi, webapp o'qiydi)
GRANTS_FILE = BASE_DIR / "access_grants.json"

# Mini App maxfiy kaliti (bot yozadi) — Telegram tugmasidan kelgan URL'da bo'ladi
_MINIAPP_KEY_FILE = BASE_DIR / "miniapp_key.txt"


def _miniapp_key() -> str:
    try:
        return _MINIAPP_KEY_FILE.read_text("utf-8").strip()
    except Exception:
        return ""

# ===== REMOTE CONTROL (sichqoncha / klaviatura) =====
_user32 = ctypes.windll.user32
try:
    _user32.SetProcessDPIAware()
except Exception:
    pass
_SCREEN_W = _user32.GetSystemMetrics(0)
_SCREEN_H = _user32.GetSystemMetrics(1)
_SM_XVIRT, _SM_YVIRT, _SM_CXVIRT, _SM_CYVIRT = 76, 77, 78, 79


def _capture_bounds():
    # STREAM_CFG["allscreens"] yoqilsa — barcha monitorlar (virtual ekran), aks holda asosiy
    if STREAM_CFG.get("allscreens"):
        return (
            _user32.GetSystemMetrics(_SM_XVIRT),
            _user32.GetSystemMetrics(_SM_YVIRT),
            _user32.GetSystemMetrics(_SM_CXVIRT),
            _user32.GetSystemMetrics(_SM_CYVIRT),
        )
    return 0, 0, _SCREEN_W, _SCREEN_H

MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000

_BTN_EV = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004

SPECIAL_KEYS = {
    "enter": 0x0D, "backspace": 0x08, "tab": 0x09, "esc": 0x1B,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "win": 0x5B, "delete": 0x2E, "space": 0x20, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "volup": 0xAF, "voldown": 0xAE, "mute": 0xAD,
    "playpause": 0xB3, "next": 0xB0, "prev": 0xB1,
}

MODIFIERS = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}


def do_combo(combo: str) -> None:
    vks = []
    for p in combo.lower().split("+"):
        p = p.strip()
        if p in MODIFIERS:
            vks.append(MODIFIERS[p])
        elif p in SPECIAL_KEYS:
            vks.append(SPECIAL_KEYS[p])
        elif len(p) == 1:
            vks.append(ord(p.upper()))
    for vk in vks:
        _user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        _user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def do_click(fx: float, fy: float, button: str = "left") -> None:
    ox, oy, w, h = _capture_bounds()
    x = int(ox + fx * w)
    y = int(oy + fy * h)
    _user32.SetCursorPos(x, y)
    if button == "right":
        _user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        _user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    elif button == "double":
        for _ in range(2):
            _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    else:
        _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def do_move(fx: float, fy: float) -> None:
    ox, oy, w, h = _capture_bounds()
    _user32.SetCursorPos(int(ox + fx * w), int(oy + fy * h))


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def do_move_rel(dx: int, dy: int) -> None:
    pt = _POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    _user32.SetCursorPos(pt.x + dx, pt.y + dy)


def do_press(button: str = "left") -> None:
    if button == "double":
        down, up = _BTN_EV["left"]
        for _ in range(2):
            _user32.mouse_event(down, 0, 0, 0, 0)
            _user32.mouse_event(up, 0, 0, 0, 0)
        return
    down, up = _BTN_EV.get(button, _BTN_EV["left"])
    _user32.mouse_event(down, 0, 0, 0, 0)
    _user32.mouse_event(up, 0, 0, 0, 0)


def do_button(button: str, down: bool) -> None:
    ev = _BTN_EV.get(button, _BTN_EV["left"])
    _user32.mouse_event(ev[0] if down else ev[1], 0, 0, 0, 0)


def do_scroll(amount: int) -> None:
    _user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, amount, 0)


def do_hscroll(amount: int) -> None:
    # Yon tomonga aylantirish (ikki barmoq chapga/o'ngga)
    _user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, amount, 0)


def do_type(text: str) -> None:
    for ch in text:
        code = ord(ch)
        _user32.keybd_event(0, code, KEYEVENTF_UNICODE, 0)
        _user32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)


def do_special(name: str) -> None:
    vk = SPECIAL_KEYS.get(name)
    if not vk:
        return
    _user32.keybd_event(vk, 0, 0, 0)
    _user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


# ===== SCREENSHOT =====
STREAM_CFG = {"w": 540, "q": 28, "fps": 30, "cursor": 1, "allscreens": 0}

# Windows kursor o'qi shakli (uchidan boshlab)
_CURSOR_SHAPE = [(0, 0), (0, 18), (5, 14), (8, 20), (11, 19), (7, 12), (13, 12)]


def _draw_cursor_cv(frame, x, y):
    # frame: BGR numpy
    pts = np.array([(x + px, y + py) for px, py in _CURSOR_SHAPE], np.int32)
    cv2.fillPoly(frame, [pts], (255, 255, 255))
    cv2.polylines(frame, [pts], True, (0, 0, 0), 1, cv2.LINE_AA)


def _capture_bgr(allscreens: bool):
    """Eng tez usul bilan BGR numpy kadr qaytaradi (dxcam -> mss -> PIL)."""
    if _HAS_DX and not allscreens:
        try:
            f = _dx.grab()  # o'zgarmagan bo'lsa None -> oxirgi kadrni ishlatamiz
            if f is not None:
                _dx_last["frame"] = f
            if _dx_last["frame"] is not None:
                return _dx_last["frame"]
        except Exception:
            pass
    if _mss_mod is not None:
        try:
            with _mss_mod.mss() as sct:
                mon = sct.monitors[0] if allscreens else sct.monitors[1]
                raw = sct.grab(mon)
                return np.ascontiguousarray(np.asarray(raw)[:, :, :3])
        except Exception:
            pass
    # oxirgi chora: PIL
    img = ImageGrab.grab(all_screens=allscreens)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def take_jpeg_bytes() -> bytes:
    w = STREAM_CFG["w"]
    q = STREAM_CFG["q"]
    allscreens = bool(STREAM_CFG.get("allscreens"))
    ox, oy, _, _ = _capture_bounds()
    frame = _capture_bgr(allscreens)
    h, wid = frame.shape[:2]
    if wid > w:
        ratio = w / wid
        frame = cv2.resize(frame, (w, int(h * ratio)), interpolation=cv2.INTER_LINEAR)
    else:
        ratio = 1.0
    if STREAM_CFG.get("cursor"):
        try:
            pt = _POINT()
            _user32.GetCursorPos(ctypes.byref(pt))
            _draw_cursor_cv(frame, int((pt.x - ox) * ratio), int((pt.y - oy) * ratio))
        except Exception:
            pass
    ok, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, q])
    return enc.tobytes()


def take_screenshot_b64() -> str:
    return base64.b64encode(take_jpeg_bytes()).decode()


def _valid_telegram_init(init_data: str) -> bool:
    """Telegram WebApp initData ni HMAC bilan tekshiradi; egasi (OWNER) bo'lsa True."""
    if not init_data or not BOT_TOKEN:
        return False
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        their_hash = pairs.pop("hash", None)
        if not their_hash:
            return False
        data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, their_hash):
            return False
        user = json.loads(pairs.get("user", "{}"))
        return int(user.get("id", 0)) == OWNER_ID
    except Exception:
        return False


def _grant_ok(sid: str) -> bool:
    """Bot orqali tasdiqlangan (va muddati o'tmagan) sessiyami?"""
    if not sid:
        return False
    try:
        data = json.loads(GRANTS_FILE.read_text("utf-8"))
    except Exception:
        return False
    g = data.get(sid)
    return bool(g) and g.get("status") == "allowed" and g.get("expires", 0) > time.time()


def _auth_ok(request: web.Request) -> bool:
    # 1) Mini App maxfiy kaliti (Telegram tugmasidan ochilgan URL'da bo'ladi) -> egasi
    key = request.headers.get("X-Key") or request.query.get("k", "")
    mk = _miniapp_key()
    if key and mk and hmac.compare_digest(key, mk):
        return True
    # 2) Telegram initData (imzolangan, egasi) -> so'rovsiz ruxsat
    init = request.headers.get("X-Tg-Init") or request.query.get("tg_init", "")
    if _valid_telegram_init(init):
        return True
    # 3) Begona (ngrok havolasi brauzerda) -> bot orqali tasdiqlangan sessiya
    sid = request.headers.get("X-Sid") or request.query.get("sid", "")
    return _grant_ok(sid)


def _cors(resp: web.Response) -> web.Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


async def cors_handler(request: web.Request) -> web.Response:
    resp = web.Response()
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


async def test_api(request: web.Request) -> web.Response:
    return _cors(web.json_response({"status": "ok"}))


async def screenshot_api(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return _cors(web.json_response({"error": "Unauthorized"}, status=403))
    try:
        loop = asyncio.get_event_loop()
        b64 = await asyncio.wait_for(loop.run_in_executor(None, take_screenshot_b64), timeout=15)
        return _cors(web.json_response({"image": f"data:image/jpeg;base64,{b64}"}))
    except asyncio.TimeoutError:
        return _cors(web.json_response({"error": "Timeout"}, status=504))
    except Exception as e:
        return _cors(web.json_response({"error": str(e)}, status=500))


async def stream_api(request: web.Request) -> web.StreamResponse:
    if not _auth_ok(request):
        return web.Response(status=403, text="Unauthorized")
    boundary = "frame"
    resp = web.StreamResponse(status=200, headers={
        "Content-Type": f"multipart/x-mixed-replace; boundary={boundary}",
        "Cache-Control": "no-cache, no-store",
        "Connection": "close",
        "Access-Control-Allow-Origin": "*",
    })
    await resp.prepare(request)
    loop = asyncio.get_event_loop()
    last_check = time.time()
    try:
        while True:
            # Har ~2s da ruxsatni qayta tekshiramiz — egasi uzsa oqim darhol to'xtaydi
            if time.time() - last_check > 2:
                last_check = time.time()
                if not _auth_ok(request):
                    break
            jpeg = await loop.run_in_executor(None, take_jpeg_bytes)
            await resp.write(
                b"--frame\r\nContent-Type: image/jpeg\r\n"
                + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                + jpeg + b"\r\n"
            )
            await asyncio.sleep(1.0 / STREAM_CFG["fps"])
    except (ConnectionResetError, asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        print(f"[STREAM] error: {e}")
    return resp


async def config_api(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return _cors(web.json_response({"error": "Unauthorized"}, status=403))
    q = request.query
    if "w" in q:
        STREAM_CFG["w"] = max(480, min(1920, int(float(q["w"]))))
    if "q" in q:
        STREAM_CFG["q"] = max(20, min(85, int(float(q["q"]))))
    if "fps" in q:
        STREAM_CFG["fps"] = max(1, min(30, int(float(q["fps"]))))
    if "cursor" in q:
        STREAM_CFG["cursor"] = 1 if q["cursor"] in ("1", "true", "on") else 0
    if "allscreens" in q:
        STREAM_CFG["allscreens"] = 1 if q["allscreens"] in ("1", "true", "on") else 0
    return _cors(web.json_response(STREAM_CFG))


def _do_action(a: str, g) -> None:
    if a == "click":
        do_click(float(g("x", 0)), float(g("y", 0)), g("btn", "left"))
    elif a == "move":
        do_move(float(g("x", 0)), float(g("y", 0)))
    elif a == "moverel":
        do_move_rel(int(float(g("dx", 0))), int(float(g("dy", 0))))
    elif a == "press":
        do_press(g("btn", "left"))
    elif a == "down":
        do_button(g("btn", "left"), True)
    elif a == "up":
        do_button(g("btn", "left"), False)
    elif a == "scroll":
        do_scroll(int(float(g("amount", 0))))
    elif a == "hscroll":
        do_hscroll(int(float(g("amount", 0))))
    elif a == "type":
        do_type(g("text", ""))
    elif a == "special":
        do_special(g("key", ""))
    elif a == "combo":
        do_combo(g("keys", ""))
    else:
        raise ValueError("unknown action")


async def control_api(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return _cors(web.json_response({"error": "Unauthorized"}, status=403))
    q = request.query
    try:
        _do_action(q.get("action", ""), lambda k, d=None: q.get(k, d))
    except ValueError:
        return _cors(web.json_response({"error": "unknown action"}, status=400))
    except Exception as e:
        return _cors(web.json_response({"error": str(e)}, status=500))
    return _cors(web.json_response({"ok": True}))


async def ws_api(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    if not _auth_ok(request):
        await ws.close()
        return ws
    last_check = time.time()
    async for msg in ws:
        # Har ~2s da ruxsatni qayta tekshiramiz — egasi uzsa boshqaruv darhol to'xtaydi
        if time.time() - last_check > 2:
            last_check = time.time()
            if not _auth_ok(request):
                break
        if msg.type == web.WSMsgType.TEXT:
            try:
                d = json.loads(msg.data)
                _do_action(d.get("a", ""), lambda k, dv=None: d.get(k, dv))
            except Exception:
                pass
        elif msg.type == web.WSMsgType.ERROR:
            break
    await ws.close()
    return ws


_access_sent = set()


async def request_access_api(request: web.Request) -> web.Response:
    """Begona brauzer ulanmoqchi -> egasiga bot orqali ruxsat so'rovi yuboradi."""
    sid = request.query.get("sid", "").strip()
    if not sid:
        return _cors(web.json_response({"error": "no sid"}, status=400))
    # Allaqachon ruxsat/rad bo'lgan bo'lsa qayta yubormaymiz
    if _grant_ok(sid) or sid in _access_sent:
        return _cors(web.json_response({"ok": True}))
    _access_sent.add(sid)
    info = (request.query.get("info", "") or "")[:120]
    ip = request.headers.get("X-Forwarded-For", request.remote or "?").split(",")[0]
    text = (f"❓ *Kimdir kompyuterga ulanmoqchi*\n\n"
            f"🌐 Manba: brauzer (ngrok havolasi)\n"
            f"📍 IP: `{ip}`\n"
            f"🖥 {info}\n\n"
            f"Ruxsat berasizmi?")
    kb = {"inline_keyboard": [[
        {"text": "✅ Ruxsat", "callback_data": f"acc:a:{sid}"},
        {"text": "⛔ Rad et", "callback_data": f"acc:d:{sid}"},
    ]]}
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(f"{_BOT_API_BASE}/bot{BOT_TOKEN}/sendMessage",
                         json={"chat_id": OWNER_ID, "text": text,
                               "parse_mode": "Markdown", "reply_markup": kb},
                         timeout=aiohttp.ClientTimeout(total=20))
    except Exception as e:
        return _cors(web.json_response({"error": str(e)}, status=500))
    return _cors(web.json_response({"ok": True}))


async def access_status_api(request: web.Request) -> web.Response:
    sid = request.query.get("sid", "").strip()
    status = "pending"
    try:
        data = json.loads(GRANTS_FILE.read_text("utf-8"))
        g = data.get(sid)
        if g:
            if g.get("status") == "allowed" and g.get("expires", 0) > time.time():
                status = "allowed"
            elif g.get("status") == "denied":
                status = "denied"
    except Exception:
        pass
    return _cors(web.json_response({"status": status}))


_UI_FILE = Path(__file__).resolve().parent / "ui.html"
_ui_cache = {"mtime": 0.0, "html": ""}


async def mini_app_handler(request: web.Request) -> web.Response:
    """Mini App sahifasi — ui.html dan o'qiladi (o'zgarsa avtomat qayta yuklanadi)."""
    try:
        mtime = _UI_FILE.stat().st_mtime
        if mtime != _ui_cache["mtime"]:
            html = _UI_FILE.read_text(encoding="utf-8")
            _ui_cache["html"] = html.replace("%OWNER%", str(OWNER_ID))
            _ui_cache["mtime"] = mtime
    except OSError as e:
        return web.Response(text="UI fayli o'qilmadi: %s" % e, status=500)
    return web.Response(text=_ui_cache["html"], content_type="text/html")


def _list_drives():
    import string
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{letter}:\\" for i, letter in enumerate(string.ascii_uppercase) if bitmask & (1 << i)]


async def fs_list_api(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return _cors(web.json_response({"error": "Unauthorized"}, status=403))
    path = request.query.get("path", "").strip()
    try:
        if not path:
            return _cors(web.json_response({"path": "", "parent": None, "dirs": _list_drives(), "files": []}))
        p = Path(path)
        if not p.exists():
            return _cors(web.json_response({"error": "Topilmadi"}, status=404))
        dirs, files = [], []
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir():
                        dirs.append(e.name)
                    else:
                        files.append({"name": e.name, "size": e.stat().st_size})
                except OSError:
                    pass
        dirs.sort(key=str.lower)
        files.sort(key=lambda f: f["name"].lower())
        parent = "" if p.parent == p else str(p.parent)
        return _cors(web.json_response({"path": str(p), "parent": parent, "dirs": dirs, "files": files}))
    except Exception as e:
        return _cors(web.json_response({"error": str(e)}, status=500))


async def fs_get_api(request: web.Request) -> web.StreamResponse:
    if not _auth_ok(request):
        return web.Response(status=403, text="Unauthorized")
    p = Path(request.query.get("path", ""))
    if not p.is_file():
        return web.Response(status=404, text="Fayl topilmadi")
    return web.FileResponse(p, headers={
        "Content-Disposition": f'attachment; filename="{p.name}"',
        "Access-Control-Allow-Origin": "*",
    })


async def fs_send_api(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return _cors(web.json_response({"error": "Unauthorized"}, status=403))
    p = Path(request.query.get("path", ""))
    if not p.is_file():
        return _cors(web.json_response({"error": "Fayl topilmadi"}, status=404))
    if not BOT_TOKEN:
        return _cors(web.json_response({"error": "Bot token yo'q"}, status=500))
    size = p.stat().st_size
    if size > MAX_TG_BYTES:
        return _cors(web.json_response({"error": f"{size // (1024**2)}MB — 50MB dan katta"}, status=400))
    try:
        data = aiohttp.FormData()
        data.add_field("chat_id", str(OWNER_ID))
        data.add_field("document", p.read_bytes(), filename=p.name)
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, data=data, timeout=aiohttp.ClientTimeout(total=120)) as r:
                jr = await r.json()
                if not jr.get("ok"):
                    return _cors(web.json_response({"error": jr.get("description", "Telegram xato")}, status=500))
        return _cors(web.json_response({"ok": True}))
    except Exception as e:
        return _cors(web.json_response({"error": str(e)}, status=500))


async def fs_open_api(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return _cors(web.json_response({"error": "Unauthorized"}, status=403))
    p = Path(request.query.get("path", ""))
    if not p.exists():
        return _cors(web.json_response({"error": "Topilmadi"}, status=404))
    try:
        os.startfile(str(p))
        return _cors(web.json_response({"ok": True}))
    except Exception as e:
        return _cors(web.json_response({"error": str(e)}, status=500))


async def init_app():
    app = web.Application()
    app.router.add_get('/', mini_app_handler)
    app.router.add_get('/api/test', test_api)
    app.router.add_get('/api/screenshot', screenshot_api)
    app.router.add_get('/api/stream', stream_api)
    app.router.add_get('/api/config', config_api)
    app.router.add_get('/api/control', control_api)
    app.router.add_get('/api/ws', ws_api)
    app.router.add_get('/api/request_access', request_access_api)
    app.router.add_get('/api/access_status', access_status_api)
    app.router.add_get('/api/fs/list', fs_list_api)
    app.router.add_get('/api/fs/get', fs_get_api)
    app.router.add_get('/api/fs/send', fs_send_api)
    app.router.add_get('/api/fs/open', fs_open_api)
    app.router.add_options('/api/test', cors_handler)
    app.router.add_options('/api/screenshot', cors_handler)
    return app


if __name__ == "__main__":
    app = asyncio.run(init_app())
    web.run_app(app, host='127.0.0.1', port=8765, print=lambda *a: None)
