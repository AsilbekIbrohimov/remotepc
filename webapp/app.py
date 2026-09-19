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
from aiohttp import web
from PIL import ImageGrab, ImageDraw
from dotenv import load_dotenv

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
STREAM_CFG = {"w": 900, "q": 38, "fps": 20, "cursor": 1, "allscreens": 0}

# Windows kursor o'qi shakli (uchidan boshlab)
_CURSOR_SHAPE = [(0, 0), (0, 18), (5, 14), (8, 20), (11, 19), (7, 12), (13, 12)]


def _draw_cursor(img, x, y):
    d = ImageDraw.Draw(img)
    pts = [(x + px, y + py) for px, py in _CURSOR_SHAPE]
    # qora chegara (qalinroq ko'rinsin) + oq to'ldirish
    d.polygon(pts, fill=(255, 255, 255), outline=(0, 0, 0))
    d.line(pts + [pts[0]], fill=(0, 0, 0), width=1)


def take_jpeg_bytes() -> bytes:
    w = STREAM_CFG["w"]
    q = STREAM_CFG["q"]
    allscreens = bool(STREAM_CFG.get("allscreens"))
    ox, oy, _, _ = _capture_bounds()
    img = ImageGrab.grab(all_screens=allscreens)
    if img.width > w:
        ratio = w / img.width
        img = img.resize((w, int(img.height * ratio)))
    else:
        ratio = 1.0
    if STREAM_CFG.get("cursor"):
        try:
            pt = _POINT()
            _user32.GetCursorPos(ctypes.byref(pt))
            _draw_cursor(img, int((pt.x - ox) * ratio), int((pt.y - oy) * ratio))
        except Exception:
            pass
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=q)
    return buf.getvalue()


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
    # 1) Telegram ichidan (imzolangan initData, egasi) -> so'rovsiz ruxsat
    init = request.headers.get("X-Tg-Init") or request.query.get("tg_init", "")
    if _valid_telegram_init(init):
        return True
    # 2) Begona (ngrok havolasi brauzerda) -> bot orqali tasdiqlangan sessiya
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


async def mini_app_handler(request: web.Request) -> web.Response:
    html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>PC Remote</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-user-select:none; user-select:none; -webkit-tap-highlight-color:transparent; }
html,body { height:100%; background:#000; color:#fff; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; overflow:hidden; }
#app { display:flex; flex-direction:column; height:100%; }
#video { flex:0 0 auto; position:relative; background:#000; overflow:hidden; touch-action:none; min-height:170px; }
#screenshot { display:block; width:100%; height:auto; transform-origin:0 0; }
#fps { position:absolute; top:8px; left:8px; background:rgba(0,0,0,0.55); color:#0f0; font-size:11px; font-family:monospace; padding:3px 7px; border-radius:5px; z-index:20; }
#status { position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); font-size:14px; color:#888; text-align:center; z-index:15; }
.loading { animation:pulse 1.5s infinite; } .error{ color:#f55; }
@keyframes pulse { 0%,100%{opacity:.5} 50%{opacity:1} }
#ztoggle { position:absolute; right:8px; top:8px; width:38px; height:38px; border-radius:50%; border:none; background:rgba(0,0,0,0.55); color:#fff; font-size:20px; z-index:21; }
#fullbtn { position:absolute; right:52px; top:8px; width:38px; height:38px; border-radius:50%; border:none; background:rgba(0,0,0,0.55); color:#fff; font-size:18px; z-index:21; }
#fullbtn.active { background:#2fbf60; box-shadow:0 0 0 2px #2fbf60; }
#fsbtn { position:absolute; right:96px; top:8px; width:38px; height:38px; border-radius:50%; border:none; background:rgba(0,0,0,0.55); color:#fff; font-size:18px; z-index:21; }
#zoomctl { position:absolute; right:8px; top:52px; display:flex; flex-direction:column; gap:6px; z-index:20; }
#zoomctl.collapsed { display:none; }
#zoomctl button, #gear { width:38px; height:38px; border-radius:50%; border:none; background:rgba(0,0,0,0.55); color:#fff; font-size:18px; font-weight:bold; }
#zoomlevel { position:absolute; right:8px; bottom:8px; background:rgba(0,0,0,0.55); color:#0f0; font-size:11px; padding:3px 7px; border-radius:5px; z-index:20; }
#panel { position:fixed; right:10px; top:56px; width:220px; background:rgba(20,20,20,0.98); border:1px solid #555; border-radius:12px; padding:14px; z-index:200; display:none; box-shadow:0 8px 30px rgba(0,0,0,0.6); }
#panel h4 { font-size:13px; color:#0f0; margin-bottom:6px; }
#panel label { display:block; font-size:12px; color:#ccc; margin:9px 0 2px; }
#panel .val { color:#0f0; font-weight:bold; }
#panel input[type=range] { width:100%; }
#panel .presets { display:flex; gap:5px; margin-top:9px; }
#panel .presets button { flex:1; padding:6px 0; font-size:11px; border:none; border-radius:6px; background:#333; color:#fff; }
#controls { display:flex; flex-direction:column; flex:1; min-height:0; background:#181818; }
#tabs { display:flex; background:#141414; border-top:1px solid #2a2a2a; flex:0 0 auto; }
#tabs .tab { flex:1; padding:11px 4px; font-size:12px; border:none; background:transparent; color:#8a8a8a; border-bottom:2px solid transparent; }
#tabs .tab.active { color:#fff; border-bottom-color:#2fbf60; }
#panes { flex:1; overflow-y:auto; min-height:0; }
.pane { display:flex; flex-wrap:wrap; align-content:flex-start; gap:7px; padding:10px; }
.pane[hidden] { display:none; }
.pane button { flex:1 1 auto; min-width:70px; max-width:calc(50% - 4px); padding:14px 8px; font-size:14px; border:none; border-radius:11px; background:#2b2b2b; color:#fff; white-space:nowrap; transition:transform .05s, background .15s; }
.pane button:active { transform:scale(0.94); background:#3a3a3a; }
.pane button.active { background:#2fbf60; color:#04220f; font-weight:bold; }
.pane button.wide { flex-basis:100%; max-width:100%; }
.section { flex-basis:100%; font-size:10px; color:#6a6a72; margin:8px 2px 1px; text-transform:uppercase; letter-spacing:1.5px; font-weight:bold; }
.dpad { flex-basis:100%; display:grid; grid-template-columns:repeat(3,60px); grid-template-rows:repeat(3,46px); gap:6px; justify-content:center; margin:4px 0; }
.dpad button { min-width:0; max-width:none; padding:0; font-size:18px; }
.dpad .u{ grid-column:2; grid-row:1; } .dpad .l{ grid-column:1; grid-row:2; }
.dpad .r{ grid-column:3; grid-row:2; } .dpad .d{ grid-column:2; grid-row:3; }
.dpad .c{ grid-column:2; grid-row:2; background:#141418; color:#4a4a52; pointer-events:none; }
#trackpad { flex-basis:100%; height:150px; background:#101014; border:2px dashed #3a3a44; border-radius:12px; display:flex; align-items:center; justify-content:center; color:#555; font-size:13px; touch-action:none; position:relative; }
#trackpad.on { border-color:#2fbf60; color:#2fbf60; }
#trackpad.drag { border-color:#f0a020; color:#f0a020; border-style:solid; }
#trackpad .hint { font-size:11px; color:#666; text-align:center; line-height:1.5; padding:0 8px; }
#kbrow { display:flex; gap:6px; flex-basis:100%; margin-bottom:2px; }
#kbrow input { flex:1; padding:11px; border-radius:9px; border:1px solid #444; background:#222; color:#fff; font-size:14px; }
#kbrow button.send { padding:11px 16px; border:none; border-radius:9px; background:#2fbf60; color:#04220f; font-weight:bold; }
@media (orientation:landscape) {
  #app { flex-direction:row; }
  #video { flex:1 1 auto; height:100%; min-height:0; }
  #screenshot { width:auto; height:100%; max-width:100%; }
  #controls { flex:0 0 210px; border-left:1px solid #2a2a2a; }
  #tabs { border-top:none; }
  .pane button { max-width:100%; min-width:0; }
  #trackpad { height:120px; }
}
#fm { position:fixed; inset:0; background:#101014; z-index:300; display:flex; flex-direction:column; }
#fm[hidden]{ display:none; }
#fmbar { display:flex; align-items:center; gap:8px; padding:10px; background:#181820; border-bottom:1px solid #2a2a2a; }
#fmbar button { width:40px; height:40px; border:none; border-radius:8px; background:#2b2b2b; color:#fff; font-size:16px; }
#fmpath { flex:1; font-size:12px; color:#7ab8ff; font-family:monospace; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
#fmlist { flex:1; overflow-y:auto; padding:4px 6px; }
.fmitem { display:flex; align-items:center; gap:8px; padding:9px 10px; border-bottom:1px solid #1e1e26; font-size:14px; }
.fmitem[data-dir]:active { background:#22222a; }
.fmname { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.fmitem .sz { margin-left:auto; color:#777; font-size:11px; white-space:nowrap; }
.fmact { flex:0 0 auto; width:42px; height:38px; border:none; border-radius:8px; background:#2b2b2b; color:#fff; font-size:15px; }
.fmact:active { background:#2fbf60; }
.fmempty { text-align:center; color:#666; padding:30px; font-size:13px; }
</style>
</head>
<body>
<div id="accgate" style="display:none;position:fixed;inset:0;z-index:9999;background:#0b0b0f;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:24px;">
  <div style="font-size:46px;margin-bottom:14px;">🔐</div>
  <div style="font-size:19px;font-weight:bold;color:#fff;margin-bottom:8px;">Ruxsat kutilmoqda</div>
  <div id="accmsg" style="font-size:14px;color:#9a9aa4;max-width:320px;line-height:1.5;">Egasiga Telegram orqali so'rov yuborildi. Iltimos, u tasdiqlashini kuting…</div>
  <div style="margin-top:18px;width:36px;height:36px;border:3px solid #2b2b33;border-top-color:#2fbf60;border-radius:50%;animation:accspin 1s linear infinite;"></div>
</div>
<style>@keyframes accspin{to{transform:rotate(360deg)}}</style>
<div id="app">
  <div id="video">
    <img id="screenshot" src="" style="display:none;">
    <div id="fps">— FPS</div>
    <div id="status" class="loading">⏳ Ulanmoqda...</div>
    <button id="ztoggle">⌄</button>
    <button id="fullbtn" title="To'liq boshqaruv (AnyDesk rejimi)">🖥️</button>
    <button id="fsbtn" title="Butun ekran">⛶</button>
    <div id="zoomctl" class="collapsed">
      <button id="gear">⚙</button>
      <button id="zin">+</button>
      <button id="zout">−</button>
      <button id="zreset">⟲</button>
    </div>
    <div id="zoomlevel" style="display:none;">1.0x</div>
    <div id="panel">
      <h4>Sozlamalar <span id="panelClose" style="float:right;cursor:pointer;color:#f55;">✕</span></h4>
      <label>Kenglik: <span class="val" id="wval">900</span>px</label>
      <input type="range" id="wslider" min="480" max="1920" step="60" value="900">
      <label>Tiniqlik: <span class="val" id="qval">38</span></label>
      <input type="range" id="qslider" min="20" max="85" step="1" value="38">
      <label>Maks FPS: <span class="val" id="fval">20</span></label>
      <input type="range" id="fslider" min="1" max="30" step="1" value="20">
      <div class="presets">
        <button data-w="720" data-q="30" data-f="25">Tez</button>
        <button data-w="1100" data-q="50" data-f="15">O'rta</button>
        <button data-w="1600" data-q="70" data-f="8">Tiniq</button>
      </div>
      <div class="presets" style="margin-top:8px;">
        <button id="toggleScreens">🖥 Barcha monitorlar</button>
        <button id="toggleCursor">🖱️ Kursor: ON</button>
      </div>
    </div>
  </div>
  <div id="controls">
    <div id="tabs">
      <button class="tab active" data-tab="mouse">🖱️</button>
      <button class="tab" data-tab="keys">⌨️</button>
      <button class="tab" data-tab="media">🎵</button>
      <button class="tab" data-tab="sys">🖥</button>
    </div>
    <div id="panes">
      <div class="pane" data-pane="mouse">
        <div id="trackpad"><div class="hint">TOUCHPAD<br>1 barmoq: surish + bosish=chap<br>2 barmoq: bosish=o'ng, surish=scroll<br>3 barmoq: o'rta • uzoq bosib: tortish</div></div>
        <button id="btnClick" class="wide">🖱️ Chap klik</button>
        <button id="tpLeft">Chap klik</button>
        <button id="tpRight">O'ng klik</button>
        <button data-scroll="120">🔼 Scroll</button>
        <button data-scroll="-120">🔽 Scroll</button>
        <button data-combo="alt+left">◄ Orqaga</button>
        <button data-combo="alt+right">► Oldinga</button>
      </div>
      <div class="pane" data-pane="keys" hidden>
        <div id="kbrow">
          <input id="kbinput" type="text" placeholder="Matn yozing..." autocomplete="off">
          <button id="kbsend" class="send">Yubor</button>
        </div>
        <div class="section">Asosiy</div>
        <button data-special="enter">⏎ Enter</button>
        <button data-special="backspace">⌫ O'chir</button>
        <button data-special="space">␣ Probel</button>
        <button data-special="tab">⇥ Tab</button>
        <button data-special="esc">⎋ Esc</button>
        <button data-special="delete">⌦ Del</button>
        <div class="section">Yo'nalish</div>
        <div class="dpad">
          <button class="u" data-special="up">▲</button>
          <button class="l" data-special="left">◄</button>
          <button class="c">✜</button>
          <button class="r" data-special="right">►</button>
          <button class="d" data-special="down">▼</button>
        </div>
        <div class="section">Navigatsiya</div>
        <button data-special="home">⤒ Home</button>
        <button data-special="end">⤓ End</button>
        <button data-special="pageup">▲ PgUp</button>
        <button data-special="pagedown">▼ PgDn</button>
        <div class="section">Yorliqlar</div>
        <button data-combo="ctrl+c">📋 Nusxa</button>
        <button data-combo="ctrl+v">📥 Qo'y</button>
        <button data-combo="ctrl+x">✂️ Kes</button>
        <button data-combo="ctrl+z">↶ Bekor</button>
        <button data-combo="ctrl+y">↷ Qayta</button>
        <button data-combo="ctrl+a">⬚ Hammasi</button>
      </div>
      <div class="pane" data-pane="media" hidden>
        <button data-special="voldown">🔉 Ovoz−</button>
        <button data-special="volup">🔊 Ovoz+</button>
        <button data-special="mute">🔇 O'chir</button>
        <button data-special="prev">⏮ Oldingi</button>
        <button data-special="playpause">⏯ Play/Pauza</button>
        <button data-special="next">⏭ Keyingi</button>
      </div>
      <div class="pane" data-pane="sys" hidden>
        <button data-combo="win">⊞ Win menyu</button>
        <button data-combo="alt+tab">⇄ Oynalar</button>
        <button data-combo="win+d">🖥 Ish stoli</button>
        <button data-combo="win+e">📁 Explorer</button>
        <button data-combo="win+l">🔒 Qulflash</button>
        <button id="btnLand">⛶ Landscape</button>
        <button id="btnFiles">📁 Fayllar</button>
        <button id="btnSettings">⚙️ Video sozlama</button>
      </div>
    </div>
  </div>
</div>

<div id="fm" hidden>
  <div id="fmbar">
    <button id="fmUp">⬆</button>
    <span id="fmpath">/</span>
    <button id="fmClose">✕</button>
  </div>
  <div id="fmlist"></div>
</div>

<script>
var tg = window.Telegram && window.Telegram.WebApp;
var HEADERS = { 'ngrok-skip-browser-warning': 'true' };
var userId = 0;
var TGINIT = (tg && tg.initData) ? tg.initData : '';
var SID = '';
if (TGINIT) HEADERS['X-Tg-Init'] = TGINIT;
function authQS(){ return TGINIT ? '&tg_init='+encodeURIComponent(TGINIT) : (SID ? '&sid='+encodeURIComponent(SID) : ''); }
var img = document.getElementById('screenshot');
var statusEl = document.getElementById('status');
var fpsEl = document.getElementById('fps');

function api(qs) { return fetch('/api/control?user_id=' + userId + '&' + qs, { headers: HEADERS }).catch(function(){}); }

var ws=null, wsReady=false;
var FULL=false;
function ctrl(obj){
  if(wsReady){ try{ ws.send(JSON.stringify(obj)); return; }catch(e){} }
  var p='action='+obj.a;
  for(var k in obj){ if(k!=='a') p+='&'+k+'='+encodeURIComponent(obj[k]); }
  api(p);
}

var orientLocked = false;
function unlockOrient(){
  try { if (tg && tg.unlockOrientation) tg.unlockOrientation(); } catch(e){}
  try { if (screen.orientation && screen.orientation.unlock) screen.orientation.unlock(); } catch(e){}
  orientLocked = false;
}
function lockOrient(){
  try { if (tg && tg.lockOrientation) tg.lockOrientation(); } catch(e){}
  orientLocked = true;
}
function toggleOrient(){ if(orientLocked) unlockOrient(); else lockOrient(); return orientLocked; }

if (tg) { try { tg.ready(); tg.expand(); tg.setHeaderColor('#000000'); } catch(e){}
  unlockOrient();  // yuklanishda aylanishga ruxsat
  var u = (tg.initDataUnsafe && tg.initDataUnsafe.user) ? tg.initDataUnsafe.user : {};
  userId = u.id ? parseInt(u.id) : 0;
}
if (!userId) userId = %OWNER%;

// ===== STREAM (JS o'qiydi, FPS sanaladi) =====
var mode='none', gotFrame=false, curBlob=null, sframes=0, sLast=Date.now();
function startStream() {
  mode='stream';
  fetch('/api/stream?user_id=' + userId, { headers: HEADERS }).then(function(resp){
    if (!resp.ok || !resp.body) throw new Error('s'+resp.status);
    var reader = resp.body.getReader(); var buf = new Uint8Array(0);
    function pump(){ return reader.read().then(function(res){
      if (res.done) throw new Error('end');
      var nb = new Uint8Array(buf.length+res.value.length); nb.set(buf); nb.set(res.value,buf.length); buf=nb;
      while(true){
        var s=-1,e=-1,i;
        for(i=0;i<buf.length-1;i++){ if(buf[i]===0xFF&&buf[i+1]===0xD8){s=i;break;} }
        if(s<0)break;
        for(i=s+2;i<buf.length-1;i++){ if(buf[i]===0xFF&&buf[i+1]===0xD9){e=i+1;break;} }
        if(e<0)break;
        showFrame(buf.slice(s,e+1)); buf=buf.slice(e+1);
      }
      if(buf.length>3000000) buf=new Uint8Array(0);
      return pump();
    }); }
    return pump();
  }).catch(function(err){
    if(mode==='stream' && !gotFrame){ startPolling(); }
    else if(mode==='stream'){ setTimeout(startStream,1000); }
  });
  setTimeout(function(){ if(mode==='stream'&&!gotFrame) startPolling(); }, 7000);
}
function showFrame(bytes){
  gotFrame=true;
  var url=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));
  img.onload=function(){ if(curBlob)URL.revokeObjectURL(curBlob); curBlob=url; };
  img.src=url; img.style.display='block'; statusEl.style.display='none';
  sframes++; var now=Date.now();
  if(now-sLast>=1000){ fpsEl.textContent=sframes+' FPS · '+Math.round(bytes.length/1024)+'KB'; sframes=0; sLast=now; }
}
// ===== POLLING (zaxira) =====
var pInflight=0,pSeq=0,pShown=-1,pFrames=0,pLast=Date.now();
function pollOnce(){
  if(pInflight>=3)return; pInflight++; var my=pSeq++;
  fetch('/api/screenshot?user_id='+userId,{headers:HEADERS}).then(function(r){
    if(!r.ok){statusEl.innerHTML='❌ '+r.status;statusEl.classList.add('error');return;}
    return r.json().then(function(d){
      if(my<=pShown)return; pShown=my;
      if(d.image){ img.src=d.image; img.style.display='block'; statusEl.style.display='none';
        pFrames++; var now=Date.now(); if(now-pLast>=1000){fpsEl.textContent=pFrames+' FPS';pFrames=0;pLast=now;} }
    });
  }).catch(function(){}).finally(function(){pInflight--;});
}
function startPolling(){ if(mode==='polling')return; mode='polling'; pollOnce(); setInterval(pollOnce,150); }

// ===== RUXSAT DARVOZASI (Telegram'dan bo'lsa so'rovsiz, begona bo'lsa bot orqali) =====
function boot(){ startStream(); wsConnect(); }
function startGate(){
  if (TGINIT) { boot(); return; }   // Telegram ichida — egasiga tegishli, so'rovsiz
  // Begona brauzer (ngrok havolasi) — bot orqali ruxsat so'raymiz
  SID = 'w' + Date.now().toString(36) + Math.random().toString(36).slice(2,8);
  var ov = document.getElementById('accgate');
  if (ov) ov.style.display = 'flex';
  var info = (navigator.userAgent || '').slice(0,120);
  fetch('/api/request_access?sid='+encodeURIComponent(SID)+'&info='+encodeURIComponent(info), {headers:HEADERS}).catch(function(){});
  var tries = 0;
  var poll = setInterval(function(){
    tries++;
    fetch('/api/access_status?sid='+encodeURIComponent(SID), {headers:HEADERS})
      .then(function(r){ return r.json(); })
      .then(function(d){
        if (d.status === 'allowed'){ clearInterval(poll); HEADERS['X-Sid']=SID; if(ov) ov.style.display='none'; boot(); }
        else if (d.status === 'denied'){ clearInterval(poll); var m=document.getElementById('accmsg'); if(m) m.textContent='⛔ Ruxsat rad etildi.'; }
      }).catch(function(){});
    if (tries > 150){ clearInterval(poll); var m=document.getElementById('accmsg'); if(m) m.textContent='⌛ Vaqt tugadi. Sahifani yangilang.'; }
  }, 2000);
}

// ===== ZOOM & PAN & KLIK =====
var videoEl=document.getElementById('video');
var zlevel=document.getElementById('zoomlevel');
var scale=1,tx=0,ty=0;
function applyT(){ img.style.transform='translate('+tx+'px,'+ty+'px) scale('+scale+')'; zlevel.textContent=scale.toFixed(1)+'x'; zlevel.style.display=scale>1?'block':'none'; }
function clampPan(){ var r=videoEl.getBoundingClientRect(); var mx=(scale-1)*r.width,my=(scale-1)*r.height; if(tx>0)tx=0; if(tx<-mx)tx=-mx; if(ty>0)ty=0; if(ty<-my)ty=-my; }
function zoomAt(cx,cy,f){ var ns=Math.min(6,Math.max(1,scale*f)); var r=videoEl.getBoundingClientRect(); var ox=cx-r.left,oy=cy-r.top; tx=ox-(ox-tx)*(ns/scale); ty=oy-(oy-ty)*(ns/scale); scale=ns; if(scale===1){tx=0;ty=0;} clampPan(); applyT(); }
function resetZoom(){ scale=1;tx=0;ty=0; applyT(); }
document.getElementById('zin').onclick=function(){var r=videoEl.getBoundingClientRect();zoomAt(r.left+r.width/2,r.top+r.height/2,1.4);};
document.getElementById('zout').onclick=function(){var r=videoEl.getBoundingClientRect();zoomAt(r.left+r.width/2,r.top+r.height/2,1/1.4);};
document.getElementById('zreset').onclick=resetZoom;
var ztoggle=document.getElementById('ztoggle'), zoomctl=document.getElementById('zoomctl');
ztoggle.onclick=function(){
  var open=zoomctl.classList.toggle('collapsed')===false;
  ztoggle.textContent = open ? '⌃' : '⌄';
};

var clickMode='left'; // left | right | double
function sendClick(cx,cy){
  // rasm qutisi = tasvir (letterbox yo'q), transform getBoundingClientRect da hisobga olingan
  var r=img.getBoundingClientRect();
  if(!r.width||!r.height) return;
  var fx=(cx-r.left)/r.width, fy=(cy-r.top)/r.height;
  if(fx<0||fx>1||fy<0||fy>1) return;
  ctrl({a:'click',x:fx.toFixed(4),y:fy.toFixed(4),btn:clickMode});
  fpsEl.textContent=(clickMode==='right'?'O\\'ng':clickMode==='double'?'2x':'Chap')+' klik ✓';
}

var pointers={}, startDist=0, maxPtr=0, downX=0,downY=0, moved=0, downT=0, lastX=0,lastY=0, panning=false;
function isCtrl(t){ return t.closest('button,input,#panel'); }
videoEl.addEventListener('pointerdown',function(e){
  if(isCtrl(e.target))return;
  if(FULL && e.pointerType!=='touch') return;  // to'liq rejimda sichqoncha alohida ishlaydi
  // sozlama paneli ochiq bo'lsa, videoga bosilganda yopiladi (klik yuborilmaydi)
  if(panel && panel.style.display==='block'){ panel.style.display='none'; return; }
  pointers[e.pointerId]={x:e.clientX,y:e.clientY};
  var n=Object.keys(pointers).length; if(n>maxPtr)maxPtr=n;
  if(n===1){ downX=e.clientX;downY=e.clientY;moved=0;downT=Date.now();lastX=e.clientX;lastY=e.clientY;panning=true; }
  else if(n===2){ var p=Object.values(pointers); startDist=Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y); }
});
videoEl.addEventListener('pointermove',function(e){
  if(!pointers[e.pointerId])return;
  pointers[e.pointerId]={x:e.clientX,y:e.clientY};
  var keys=Object.keys(pointers);
  if(keys.length===2){ var p=Object.values(pointers); var d=Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y);
    if(startDist>0){ var mid_x=(p[0].x+p[1].x)/2, mid_y=(p[0].y+p[1].y)/2; zoomAt(mid_x,mid_y,(d/startDist)); startDist=d; } }
  else if(keys.length===1){ moved=Math.hypot(e.clientX-downX,e.clientY-downY);
    if(panning&&scale>1){ tx+=e.clientX-lastX; ty+=e.clientY-lastY; lastX=e.clientX; lastY=e.clientY; clampPan(); applyT(); } }
});
function endPtr(e){
  if(!pointers[e.pointerId] && Object.keys(pointers).length===0){}
  delete pointers[e.pointerId];
  var rem=Object.keys(pointers).length;
  if(rem<2)startDist=0;
  if(rem===0){
    panning=false;
    if(maxPtr===1 && moved<18 && (Date.now()-downT)<450){ sendClick(e.clientX,e.clientY); }
    maxPtr=0;
  }
}
videoEl.addEventListener('pointerup',endPtr);
videoEl.addEventListener('pointercancel',endPtr);
videoEl.addEventListener('wheel',function(e){ e.preventDefault(); if(FULL){ ctrl({a:'scroll',amount:e.deltaY<0?120:-120}); return; } zoomAt(e.clientX,e.clientY,e.deltaY<0?1.15:1/1.15); },{passive:false});

// ===== WEBSOCKET (past kechikishli boshqaruv) =====
function wsConnect(){
  try {
    var proto = location.protocol==='https:'?'wss:':'ws:';
    ws = new WebSocket(proto+'//'+location.host+'/api/ws?user_id='+userId+authQS());
    ws.onopen=function(){ wsReady=true; };
    ws.onclose=function(){ wsReady=false; setTimeout(wsConnect,1500); };
    ws.onerror=function(){ try{ws.close();}catch(e){} };
  } catch(e){}
}
// wsConnect boot() ichida chaqiriladi (ruxsatdan keyin)

// ===== SOZLAMALAR PANELI =====
var gear=document.getElementById('gear'), panel=document.getElementById('panel');
var wS=document.getElementById('wslider'),qS=document.getElementById('qslider'),fS=document.getElementById('fslider');
var wV=document.getElementById('wval'),qV=document.getElementById('qval'),fV=document.getElementById('fval');
var cfgTimer=null;
function togglePanel(){ panel.style.display=panel.style.display==='block'?'none':'block'; }
gear.onclick=togglePanel;
document.getElementById('panelClose').onclick=function(){ panel.style.display='none'; };
function sendCfg(){ fetch('/api/config?user_id='+userId+'&w='+wS.value+'&q='+qS.value+'&fps='+fS.value,{headers:HEADERS}).catch(function(){}); }
function onSlide(){ wV.textContent=wS.value;qV.textContent=qS.value;fV.textContent=fS.value; clearTimeout(cfgTimer); cfgTimer=setTimeout(sendCfg,250); }
wS.addEventListener('input',onSlide); qS.addEventListener('input',onSlide); fS.addEventListener('input',onSlide);
var pbtns=panel.querySelectorAll('.presets button[data-w]');
for(var i=0;i<pbtns.length;i++){ pbtns[i].onclick=function(){ wS.value=this.getAttribute('data-w'); qS.value=this.getAttribute('data-q'); fS.value=this.getAttribute('data-f'); onSlide(); }; }

var screensOn=false, cursorOn=true;
var tScreens=document.getElementById('toggleScreens'), tCursor=document.getElementById('toggleCursor');
tScreens.onclick=function(){
  screensOn=!screensOn;
  tScreens.classList.toggle('active',screensOn);
  tScreens.textContent = screensOn ? '🖥 Barcha: ON' : '🖥 Barcha monitorlar';
  fetch('/api/config?user_id='+userId+'&allscreens='+(screensOn?1:0),{headers:HEADERS}).catch(function(){});
};
tCursor.onclick=function(){
  cursorOn=!cursorOn;
  tCursor.textContent = '🖱️ Kursor: '+(cursorOn?'ON':'OFF');
  fetch('/api/config?user_id='+userId+'&cursor='+(cursorOn?1:0),{headers:HEADERS}).catch(function(){});
};

// ===== TABLAR =====
var tabBtns=document.querySelectorAll('#tabs .tab');
var paneEls=document.querySelectorAll('.pane');
for(var t=0;t<tabBtns.length;t++){
  tabBtns[t].onclick=function(){
    var name=this.getAttribute('data-tab');
    for(var i=0;i<tabBtns.length;i++) tabBtns[i].classList.toggle('active', tabBtns[i]===this);
    for(var j=0;j<paneEls.length;j++) paneEls[j].hidden = (paneEls[j].getAttribute('data-pane')!==name);
  };
}

// ===== KLIK REJIMI =====
var btnClick=document.getElementById('btnClick');
btnClick.onclick=function(){
  clickMode = clickMode==='left'?'right':(clickMode==='right'?'double':'left');
  btnClick.textContent = clickMode==='left'?'🖱️ Chap klik':(clickMode==='right'?'🖱️ O\\'ng klik':'🖱️ 2x klik');
  btnClick.classList.toggle('active', clickMode!=='left');
};
document.getElementById('tpLeft').onclick=function(){ ctrl({a:'press',btn:'left'}); };
document.getElementById('tpRight').onclick=function(){ ctrl({a:'press',btn:'right'}); };

// ===== SCROLL / SPECIAL / COMBO =====
var scBtns=document.querySelectorAll('[data-scroll]');
for(var s=0;s<scBtns.length;s++){ scBtns[s].onclick=function(){ ctrl({a:'scroll',amount:parseInt(this.getAttribute('data-scroll'))}); }; }
var actBtns=document.querySelectorAll('#panes button[data-special],#panes button[data-combo]');
for(var b=0;b<actBtns.length;b++){
  actBtns[b].onclick=function(){
    var sp=this.getAttribute('data-special'), cm=this.getAttribute('data-combo');
    if(sp) ctrl({a:'special',key:sp});
    else if(cm) ctrl({a:'combo',keys:cm});
  };
}

// ===== KLAVIATURA =====
var kbinput=document.getElementById('kbinput');
document.getElementById('kbsend').onclick=function(){ var v=kbinput.value; if(v){ ctrl({a:'type',text:v}); kbinput.value=''; } };
kbinput.addEventListener('keydown',function(e){ if(e.key==='Enter'){ e.preventDefault(); var v=kbinput.value; if(v){ ctrl({a:'type',text:v}); kbinput.value=''; } ctrl({a:'special',key:'enter'}); } });

// ===== TRACKPAD (to'liq gesture) =====
var tp=document.getElementById('trackpad');
var tpPts={}, tpMax=0, tpStartT=0, tpMoved=0, tpLastX=0, tpLastY=0, tpAccX=0, tpAccY=0, tpScrollY=0, dragging=false, holdTimer=null;
var TP_SENS=1.9;

tp.addEventListener('pointerdown',function(e){
  try{ tp.setPointerCapture(e.pointerId); }catch(_){}
  tpPts[e.pointerId]={x:e.clientX,y:e.clientY};
  var n=Object.keys(tpPts).length;
  if(n>tpMax)tpMax=n;
  if(n===1){
    tpStartT=Date.now(); tpMoved=0; tpLastX=e.clientX; tpLastY=e.clientY; tp.classList.add('on');
    holdTimer=setTimeout(function(){
      if(Object.keys(tpPts).length===1 && tpMoved<10){ dragging=true; ctrl({a:'down',btn:'left'}); tp.classList.add('drag'); }
    }, 500);
  } else if(n===2){
    var p=Object.values(tpPts); tpScrollY=(p[0].y+p[1].y)/2;
  }
});
tp.addEventListener('pointermove',function(e){
  if(!tpPts[e.pointerId])return;
  tpPts[e.pointerId]={x:e.clientX,y:e.clientY};
  var n=Object.keys(tpPts).length;
  if(n>=2){
    tpAccX=0; tpAccY=0;  // kutilayotgan kursor harakatini bekor qilamiz
    var p=Object.values(tpPts); var midY=(p[0].y+p[1].y)/2;
    var dsy=midY-tpScrollY; tpScrollY=midY;
    if(Math.abs(dsy)>1) ctrl({a:'scroll',amount:Math.round(dsy*4)});
    return;
  }
  // bu gesture'da 2 barmoq bo'lgan bo'lsa, bitta barmoq bilan kursorni qimirlatmaymiz
  if(tpMax>=2){ tpLastX=e.clientX; tpLastY=e.clientY; return; }
  var dx=e.clientX-tpLastX, dy=e.clientY-tpLastY;
  tpLastX=e.clientX; tpLastY=e.clientY;
  tpMoved += Math.abs(dx)+Math.abs(dy);
  if(tpMoved>10 && holdTimer){ clearTimeout(holdTimer); holdTimer=null; }
  tpAccX += dx*TP_SENS; tpAccY += dy*TP_SENS;
});
setInterval(function(){ if(Math.abs(tpAccX)>=1||Math.abs(tpAccY)>=1){ ctrl({a:'moverel',dx:Math.round(tpAccX),dy:Math.round(tpAccY)}); tpAccX=0; tpAccY=0; } }, 40);
function tpEnd(e){
  delete tpPts[e.pointerId];
  if(Object.keys(tpPts).length>0) return;
  if(holdTimer){ clearTimeout(holdTimer); holdTimer=null; }
  tp.classList.remove('on'); tp.classList.remove('drag');
  var dur=Date.now()-tpStartT;
  if(dragging){ ctrl({a:'up',btn:'left'}); dragging=false; }
  else if(tpMoved<10 && dur<300){
    if(tpMax>=3) ctrl({a:'press',btn:'middle'});
    else if(tpMax===2) ctrl({a:'press',btn:'right'});
    else ctrl({a:'press',btn:'left'});
  }
  tpMax=0;
}
tp.addEventListener('pointerup',tpEnd);
tp.addEventListener('pointercancel',tpEnd);

// ===== MAJBURIY LANDSCAPE =====
var landOn=false;
function setLandscape(on){
  try {
    if(on){
      if(tg && tg.requestFullscreen) tg.requestFullscreen();
      setTimeout(function(){ try{ if(screen.orientation && screen.orientation.lock) screen.orientation.lock('landscape'); }catch(e){} }, 250);
    } else {
      try{ if(screen.orientation && screen.orientation.unlock) screen.orientation.unlock(); }catch(e){}
      if(tg && tg.exitFullscreen) tg.exitFullscreen();
    }
  } catch(e){}
  landOn=on;
}
var btnLand=document.getElementById('btnLand');
btnLand.onclick=function(){ setLandscape(!landOn); btnLand.textContent=landOn?'⛶ Portret':'⛶ Landscape'; btnLand.classList.toggle('active',landOn); };
document.getElementById('btnSettings').onclick=togglePanel;

// ===== FAYL MENEJERI =====
var fm=document.getElementById('fm'), fmpath=document.getElementById('fmpath'), fmlist=document.getElementById('fmlist');
var fmCur='';
function fmFmt(n){ if(n>=1048576) return (n/1048576).toFixed(1)+'MB'; if(n>=1024) return (n/1024).toFixed(0)+'KB'; return n+'B'; }
function fmLoad(path){
  fmpath.textContent = path || 'Drayvlar';
  fmlist.innerHTML='<div class="fmempty">Yuklanmoqda...</div>';
  fetch('/api/fs/list?user_id='+userId+'&path='+encodeURIComponent(path||''),{headers:HEADERS})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d.error){ fmlist.innerHTML='<div class="fmempty">❌ '+d.error+'</div>'; return; }
      fmCur=d.path; fm.dataset.parent = (d.parent===null?'__drives__':d.parent);
      var html='';
      function joinP(base, n){ if(!base) return n; return (base.endsWith('\\\\')?base:base+'\\\\')+n; }
      d.dirs.forEach(function(name){
        var child=joinP(d.path, name);
        html+='<div class="fmitem" data-dir="'+encodeURIComponent(child)+'">📁 <span>'+name+'</span></div>';
      });
      d.files.forEach(function(f){
        var ef=encodeURIComponent(joinP(d.path, f.name));
        html+='<div class="fmitem"><span class="fmname">📄 '+f.name+'</span><span class="sz">'+fmFmt(f.size)+'</span>'+
          '<button class="fmact" data-send="'+ef+'">📤</button>'+
          '<button class="fmact" data-open="'+ef+'">▶</button></div>';
      });
      if(!html) html='<div class="fmempty">Bo\\'sh papka</div>';
      fmlist.innerHTML=html;
      var dirs=fmlist.querySelectorAll('.fmitem[data-dir]');
      for(var i=0;i<dirs.length;i++){ dirs[i].onclick=function(){ fmLoad(decodeURIComponent(this.getAttribute('data-dir'))); }; }
      var acts=fmlist.querySelectorAll('.fmact');
      for(var j=0;j<acts.length;j++){
        acts[j].onclick=function(e){
          e.stopPropagation();
          var send=this.getAttribute('data-send'), open=this.getAttribute('data-open');
          if(send) fmSend(decodeURIComponent(send));
          else if(open) fmOpen(decodeURIComponent(open));
        };
      }
    })
    .catch(function(e){ fmlist.innerHTML='<div class="fmempty">❌ '+e.message+'</div>'; });
}
function fmSend(path){
  fmpath.textContent='📤 Telegramga yuborilmoqda...';
  fetch('/api/fs/send?user_id='+userId+'&path='+encodeURIComponent(path),{headers:HEADERS})
    .then(function(r){ return r.json(); })
    .then(function(d){ fmpath.textContent = d.ok ? '✅ Telegramga yuborildi' : ('❌ '+(d.error||'xato')); setTimeout(function(){ fmpath.textContent=fmCur; }, 2800); })
    .catch(function(e){ fmpath.textContent='❌ '+e.message; });
}
function fmOpen(path){
  fmpath.textContent='▶ PC da ochilmoqda...';
  fetch('/api/fs/open?user_id='+userId+'&path='+encodeURIComponent(path),{headers:HEADERS})
    .then(function(r){ return r.json(); })
    .then(function(d){ fmpath.textContent = d.ok ? '▶ PC da ochildi' : ('❌ '+(d.error||'xato')); setTimeout(function(){ fmpath.textContent=fmCur; }, 2000); })
    .catch(function(e){ fmpath.textContent='❌ '+e.message; });
}
document.getElementById('btnFiles').onclick=function(){ fm.hidden=false; fmLoad(''); };
document.getElementById('fmClose').onclick=function(){ fm.hidden=true; };
document.getElementById('fmUp').onclick=function(){
  var par=fm.dataset.parent;
  if(par==='__drives__'||par==='') fmLoad('');
  else fmLoad(par);
};

// ===== TO'LIQ REMOTE (AnyDesk rejimi) =====
// Video ustida haqiqiy sichqoncha: harakat=kursor, bosish=klik, g'ildirak=scroll,
// klaviatura=to'g'ridan-to'g'ri PC ga. Brauzerda ochilganda avtomatik yoqiladi.
var fullbtn=document.getElementById('fullbtn'), fsbtn=document.getElementById('fsbtn');
function vmap(e){
  var r=img.getBoundingClientRect();
  if(!r.width||!r.height) return null;
  var fx=(e.clientX-r.left)/r.width, fy=(e.clientY-r.top)/r.height;
  if(fx<0||fx>1||fy<0||fy>1) return null;
  return {x:fx.toFixed(4), y:fy.toFixed(4)};
}
function btnName(b){ return b===2?'right':(b===1?'middle':'left'); }
var lastMove=0;
videoEl.addEventListener('mousemove',function(e){
  if(!FULL) return;
  var now=Date.now(); if(now-lastMove<30) return; lastMove=now;
  var m=vmap(e); if(m) ctrl({a:'move',x:m.x,y:m.y});
});
videoEl.addEventListener('mousedown',function(e){
  if(!FULL) return;
  if(isCtrl(e.target)) return;
  e.preventDefault();
  var m=vmap(e); if(m) ctrl({a:'move',x:m.x,y:m.y});
  ctrl({a:'down',btn:btnName(e.button)});
});
window.addEventListener('mouseup',function(e){
  if(!FULL) return;
  ctrl({a:'up',btn:btnName(e.button)});
});
videoEl.addEventListener('contextmenu',function(e){ if(FULL) e.preventDefault(); });
videoEl.addEventListener('dblclick',function(e){ if(FULL) e.preventDefault(); });

// Fizik klaviatura → PC (faqat FULL yoniq va input-ga yozilmayotgan bo'lsa)
var KMAP={'Enter':'enter','Backspace':'backspace','Tab':'tab','Escape':'esc',
  'ArrowUp':'up','ArrowDown':'down','ArrowLeft':'left','ArrowRight':'right',
  'Delete':'delete',' ':'space','Home':'home','End':'end','PageUp':'pageup','PageDown':'pagedown'};
window.addEventListener('keydown',function(e){
  if(!FULL) return;
  var tag=e.target&&e.target.tagName;
  if(tag==='INPUT'||tag==='TEXTAREA') return;
  var mods=[];
  if(e.ctrlKey)mods.push('ctrl'); if(e.altKey)mods.push('alt');
  if(e.shiftKey)mods.push('shift'); if(e.metaKey)mods.push('win');
  var k=e.key;
  // faqat modifikator bosilgan bo'lsa — hali kutamiz
  if(k==='Control'||k==='Alt'||k==='Shift'||k==='Meta') return;
  e.preventDefault();
  if(KMAP[k]){
    if(mods.length) ctrl({a:'combo',keys:mods.concat([KMAP[k]]).join('+')});
    else ctrl({a:'special',key:KMAP[k]});
    return;
  }
  if(k.length===1){
    // Ctrl/Alt/Win yorliqlari (masalan Ctrl+C) → combo, aks holda oddiy yozuv
    var hasCmd = e.ctrlKey||e.altKey||e.metaKey;
    if(hasCmd) ctrl({a:'combo',keys:mods.concat([k.toLowerCase()]).join('+')});
    else ctrl({a:'type',text:k});
    return;
  }
});

function setFull(on){
  FULL=on;
  fullbtn.classList.toggle('active',on);
  fullbtn.title = on ? 'To\\'liq boshqaruv: YONIQ (bosib o\\'chiring)' : 'To\\'liq boshqaruv (AnyDesk rejimi)';
  videoEl.style.cursor = on ? 'crosshair' : '';
  if(on){ resetZoom(); fpsEl.textContent='🖥️ To\\'liq boshqaruv YONIQ'; }
}
fullbtn.onclick=function(){ setFull(!FULL); };

// Fullscreen
fsbtn.onclick=function(){
  try{
    if(!document.fullscreenElement){ (document.getElementById('app')||document.body).requestFullscreen(); }
    else{ document.exitFullscreen(); }
  }catch(e){}
};

// Brauzerda (Telegram emas, sensorli ekran emas) — avtomatik to'liq rejim
(function(){
  var isTouch = ('ontouchstart' in window) || (navigator.maxTouchPoints>0);
  var inTelegram = !!(tg && tg.initData);
  if(!isTouch && !inTelegram){ setTimeout(function(){ setFull(true); }, 400); }
})();

startGate();
</script>
</body>
</html>"""
    html = html.replace("%OWNER%", str(OWNER_ID))
    return web.Response(text=html, content_type='text/html')


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
