"""
Linux (Wayland/GNOME) platform moslik qatlami.

Windows'ga bog'liq chaqiriqlar (ctypes.windll, shutdown.exe, powershell,
os.startfile, ImageGrab) o'rniga Linux ekvivalentlarini beradi. Bot shu modul
orqali ishlaydi, shunda bot/app.py va boshqa fayllar OS-dan mustaqil bo'ladi.

Ekran olish GNOME Wayland'da faqat rasmiy ScreenCast portali orqali mumkin —
u birinchi marta "Ekranni ulashish?" oynasini chiqaradi. Ruxsat berilgach,
restore-token saqlanadi va keyingi safar so'rovsiz ochiladi.
"""

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"
BASE_DIR = Path(__file__).resolve().parent


def _dbg(msg: str) -> None:
    if os.environ.get("REMOTEPC_DEBUG"):
        try:
            with open("/tmp/capstage.log", "a") as _f:
                _f.write("%.2f %s\n" % (time.time(), msg))
        except Exception:
            pass


# ─────────────────────────── Quvvat / sessiya ───────────────────────────
def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _mins(delay_seconds: int) -> str:
    # Linux `shutdown` soniya emas, daqiqa oladi. 0 -> darhol (now).
    if delay_seconds <= 0:
        return "now"
    return "+%d" % max(1, round(delay_seconds / 60))


def power_off(delay_seconds: int = 0) -> None:
    if IS_WINDOWS:
        _run(["shutdown", "/s", "/t", str(max(0, delay_seconds)), "/f"])
    else:
        _run(["shutdown", "-h", _mins(delay_seconds)])


def reboot(delay_seconds: int = 0) -> None:
    if IS_WINDOWS:
        _run(["shutdown", "/r", "/t", str(max(0, delay_seconds)), "/f"])
    else:
        _run(["shutdown", "-r", _mins(delay_seconds)])


def cancel_shutdown() -> None:
    _run(["shutdown", "/a"] if IS_WINDOWS else ["shutdown", "-c"])


def suspend() -> tuple[bool, str]:
    if IS_WINDOWS:
        _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
        return True, "😴 Uxlash rejimiga o'tkazildi."
    # Linux: masofadan ulanish uchun uyqu odatda o'chirilgan bo'ladi — qulflaymiz.
    lock_screen()
    return False, ("😴 Uyqu rejimi masofaviy ulanishni uzib qo'yadi, shuning uchun "
                   "o'rniga ekran qulflandi. Haqiqiy uyqu kerak bo'lsa ayting.")


def lock_screen() -> None:
    if IS_WINDOWS:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
    elif shutil.which("loginctl"):
        _run(["loginctl", "lock-session"])
    else:
        _run(["gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
              "--object-path", "/org/gnome/ScreenSaver",
              "--method", "org.gnome.ScreenSaver.Lock"])


def is_screen_locked() -> bool:
    try:
        if IS_WINDOWS:
            import ctypes
            DESKTOP_SWITCHDESKTOP = 0x0100
            h = ctypes.windll.user32.OpenDesktopW("Default", 0, False, DESKTOP_SWITCHDESKTOP)
            if not h:
                return True
            try:
                return not ctypes.windll.user32.SwitchDesktop(h)
            finally:
                ctypes.windll.user32.CloseDesktop(h)
        r = _run(["gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
                  "--object-path", "/org/gnome/ScreenSaver",
                  "--method", "org.gnome.ScreenSaver.GetActive"])
        return "true" in (r.stdout or "").lower()
    except Exception:
        return False


# ─────────────────────────── Clipboard ───────────────────────────
def clip_get() -> str:
    if IS_WINDOWS:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout or ""
    if shutil.which("wl-paste"):
        return _run(["wl-paste", "-n"]).stdout or ""
    return ""


def clip_set(text: str) -> None:
    if IS_WINDOWS:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard", "-Value", text], timeout=10)
    elif shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=text, text=True)


# ─────────────────────────── Ochish / ishga tushirish ───────────────────────────
def open_path(path_or_url: str) -> None:
    if IS_WINDOWS:
        os.startfile(path_or_url)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path_or_url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ─────────────────────────── Fayl tizimi (webapp uchun) ───────────────────────────
def list_roots() -> list[str]:
    if IS_WINDOWS:
        import ctypes
        import string as _s
        bm = ctypes.windll.kernel32.GetLogicalDrives()
        return [f"{c}:\\" for i, c in enumerate(_s.ascii_uppercase) if bm & (1 << i)]
    roots = [str(Path.home()), "/"]
    for base in ("/media/" + os.environ.get("USER", ""), "/run/media/" + os.environ.get("USER", ""), "/mnt"):
        p = Path(base)
        if p.is_dir():
            for d in sorted(p.iterdir()):
                if d.is_dir():
                    roots.append(str(d))
    seen, out = set(), []
    for r in roots:
        if r not in seen:
            seen.add(r); out.append(r)
    return out


# ─────────────────────────── Claude CLI (/ai uchun) ───────────────────────────
def find_claude() -> str | None:
    exe = "claude.exe" if IS_WINDOWS else "claude"
    p = shutil.which(exe)
    if p:
        return p
    for pat in (".vscode/extensions", ".vscode-server/extensions", ".cursor-server/extensions"):
        base = Path.home() / pat
        if base.is_dir():
            hits = sorted(base.glob(f"anthropic.claude-code-*/resources/native-binary/{exe}"))
            if hits:
                return str(hits[-1])
    if not IS_WINDOWS:
        for cand in (Path.home() / ".local/bin/claude", Path("/usr/local/bin/claude")):
            if cand.exists():
                return str(cand)
    return None


# ─────────────────────────── Ekran olish (Wayland ScreenCast portali) ───────────────────────────
class CaptureUnavailable(Exception):
    pass


class _PortalCapture:
    """ScreenCast portali + GStreamer orqali ekran kadrlarini oladi.
    Birinchi ishga tushishda GNOME 'Ekranni ulashish?' oynasini chiqaradi;
    ruxsatdan keyin restore-token saqlanib, keyingi safar so'rovsiz ochiladi."""

    def __init__(self):
        self._frame = None
        self._lock = threading.Lock()
        self._boot_lock = threading.Lock()
        self._pipeline = None
        self._started = False
        self._start_error = None
        self._size = (0, 0)
        self._nsamp = 0
        self._session = None
        self._node_id = None
        self._bus = None
        self._token_file = BASE_DIR / ".screencast_token"

    def _load_token(self) -> str:
        try:
            return self._token_file.read_text("utf-8").strip()
        except Exception:
            return ""

    def _save_token(self, tok: str) -> None:
        try:
            if tok:
                self._token_file.write_text(tok, encoding="utf-8")
        except Exception:
            pass

    def ensure_started(self, timeout: float = 30.0):
        if self._started:
            return
        if self._start_error:
            raise CaptureUnavailable(self._start_error)
        # Diqqat: self._lock faqat kadr ma'lumoti uchun. Boot uchun alohida
        # lock ishlatamiz, aks holda _boot ichidagi `with self._lock` qayta-band
        # qilinib deadlock bo'ladi (threading.Lock reentrant emas).
        with self._boot_lock:
            if self._started:
                return
            if self._start_error:
                raise CaptureUnavailable(self._start_error)
            self._boot(timeout)

    def _boot(self, timeout: float):
        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst, GLib, Gio
        except Exception as e:
            self._start_error = f"GStreamer/gi topilmadi: {e}"
            raise CaptureUnavailable(self._start_error)

        Gst.init(None)
        self._Gst = Gst
        self._GLib = GLib
        loop = GLib.MainLoop()
        self._loop = loop
        t = threading.Thread(target=loop.run, daemon=True)
        t.start()

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._bus = bus
        PORTAL = "org.freedesktop.portal.Desktop"
        PATH = "/org/freedesktop/portal/desktop"
        SC = "org.freedesktop.portal.ScreenCast"
        RD = "org.freedesktop.portal.RemoteDesktop"
        self._PORTAL, self._PATH, self._RD = PORTAL, PATH, RD

        unique = bus.get_unique_name().lstrip(":").replace(".", "_")
        results = {}
        done = threading.Event()

        def call(iface, method, params):
            ev = threading.Event()
            holder = {}
            token = "t%d" % (int(time.time() * 1000) % 1000000)
            handle = f"/org/freedesktop/portal/desktop/request/{unique}/{token}"

            def on_response(conn, sender, path, ifc, sig, parameters):
                holder["resp"] = parameters.unpack()
                ev.set()

            sub = bus.signal_subscribe(
                PORTAL, "org.freedesktop.portal.Request", "Response", handle,
                None, Gio.DBusSignalFlags.NONE, on_response)
            # options ichiga handle_token qo'shamiz
            opts = dict(params[-1])
            opts["handle_token"] = GLib.Variant("s", token)
            newp = list(params[:-1]) + [opts]
            variant = _pack(GLib, iface, method, newp)
            bus.call_sync(PORTAL, PATH, iface, method, variant, None,
                          Gio.DBusCallFlags.NONE, -1, None)
            if not ev.wait(timeout):
                bus.signal_unsubscribe(sub)
                raise CaptureUnavailable(f"{method}: javob kutish vaqti tugadi")
            bus.signal_unsubscribe(sub)
            code, res = holder["resp"]
            if code != 0:
                raise CaptureUnavailable(f"{method}: rad etildi (foydalanuvchi ruxsat bermadi)")
            return res

        try:
            # 1) ScreenCast sessiyasi — faqat ekran (boshqaruv emas).
            # ScreenCast persist/restore'ni QO'LLAYDI -> bir marta ruxsatdan keyin
            # qayta yonishda ham so'rovsiz ochiladi. Boshqaruv alohida (uinput).
            _dbg("CreateSession(SC) ->")
            r = call(SC, "CreateSession", [{
                "session_handle_token": GLib.Variant("s", "sc%d" % (int(time.time()) % 100000)),
            }])
            session = r["session_handle"]
            self._session = session
            _dbg("CreateSession OK: " + str(session))
            # 2) ekran manbasi (monitor, kursor ko'rinsin, eslab qol)
            sel = {
                "types": GLib.Variant("u", 1),          # 1 = monitor
                "cursor_mode": GLib.Variant("u", 2),    # 2 = embedded
                "persist_mode": GLib.Variant("u", 2),   # 2 = eslab qol
            }
            tok = self._load_token()
            if tok:
                sel["restore_token"] = GLib.Variant("s", tok)
            _dbg("SelectSources ->")
            call(SC, "SelectSources", [session, sel])
            _dbg("SelectSources OK")
            # 3) start
            _dbg("Start ->")
            res = call(SC, "Start", [session, "", {}])
            _dbg("Start OK keys=" + str(list(res.keys())))
            streams = res["streams"]
            if "restore_token" in res:
                self._save_token(res["restore_token"])
            node_id = streams[0][0]
            self._node_id = node_id
            _dbg("node_id=" + str(node_id))
            # 4) pipewire fd
            fd_variant = bus.call_with_unix_fd_list_sync(
                PORTAL, PATH, SC, "OpenPipeWireRemote",
                GLib.Variant("(oa{sv})", (session, {})),
                GLib.VariantType.new("(h)"), Gio.DBusCallFlags.NONE, -1, None, None)
            (res_tuple, fd_list) = fd_variant
            idx = res_tuple.unpack()[0]
            fd = fd_list.get(idx)
            _dbg("fd=" + str(fd))
        except CaptureUnavailable as e:
            self._start_error = str(e)
            raise
        except Exception as e:
            self._start_error = "portal xato: " + repr(e)
            _dbg("EXC " + repr(e))
            raise CaptureUnavailable(self._start_error)

        # 5) GStreamer pipeline
        desc = (f"pipewiresrc fd={fd} path={node_id} do-timestamp=true keepalive-time=1000 "
                f"! videoconvert ! video/x-raw,format=BGR "
                f"! appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false")
        pipeline = Gst.parse_launch(desc)
        sink = pipeline.get_by_name("sink")

        self._nsamp = 0

        def on_sample(s):
            sample = s.emit("pull-sample")
            if sample is None:
                return Gst.FlowReturn.OK
            self._nsamp += 1
            if self._nsamp == 1:
                _dbg("FIRST SAMPLE")
            buf = sample.get_buffer()
            caps = sample.get_caps().get_structure(0)
            w = caps.get_value("width"); h = caps.get_value("height")
            ok, mapinfo = buf.map(Gst.MapFlags.READ)
            if ok:
                try:
                    import numpy as np
                    arr = np.frombuffer(mapinfo.data, dtype=np.uint8)
                    if self._nsamp == 1:
                        _dbg("map ok size=%d need=%d (%dx%d)" % (arr.size, w * h * 3, w, h))
                    if arr.size >= w * h * 3:
                        frame = arr[:w * h * 3].reshape((h, w, 3)).copy()
                        with self._lock:
                            self._frame = frame
                            self._size = (w, h)
                        if self._nsamp == 1:
                            _dbg("FRAME STORED")
                except Exception as _e:
                    if self._nsamp == 1:
                        _dbg("sample err: " + repr(_e))
                finally:
                    buf.unmap(mapinfo)
            elif self._nsamp == 1:
                _dbg("buf.map FAILED")
            return Gst.FlowReturn.OK

        sink.connect("new-sample", on_sample)

        def _on_bus(bus_, msg):
            t = msg.type
            if t == Gst.MessageType.ERROR:
                err, dbgs = msg.parse_error()
                _dbg("GST ERROR: " + str(err) + " | " + str(dbgs))
            elif t == Gst.MessageType.WARNING:
                err, dbgs = msg.parse_warning()
                _dbg("GST WARN: " + str(err))
            elif t == Gst.MessageType.STATE_CHANGED and msg.src == self._pipeline:
                old, new, _p = msg.parse_state_changed()
                _dbg("GST state: %s -> %s" % (old.value_nick, new.value_nick))
            return True

        pbus = pipeline.get_bus()
        pbus.add_signal_watch()
        pbus.connect("message", _on_bus)
        _dbg("pipeline PLAYING ->")
        pipeline.set_state(Gst.State.PLAYING)
        self._pipeline = pipeline
        _dbg("pipeline set")

        # birinchi kadrni kutamiz
        deadline = time.time() + 10
        while time.time() < deadline:
            with self._lock:
                if self._frame is not None:
                    break
            time.sleep(0.1)
        self._started = True

    def grab_bgr(self):
        self.ensure_started()
        deadline = time.time() + 5
        while time.time() < deadline:
            with self._lock:
                if self._frame is not None:
                    return self._frame.copy()
            time.sleep(0.05)
        raise CaptureUnavailable("Kadr olinmadi")

    def size(self):
        with self._lock:
            return self._size


# ─────────────────────────── Windows ekran olish ───────────────────────────
class _WinCapture:
    """Windows: dxcam (GPU-tez) -> mss -> PIL.ImageGrab."""

    def __init__(self):
        self._dx = None
        self._mss = None
        self._last = None
        self._size = (0, 0)
        self._init = False

    def _setup(self):
        if self._init:
            return
        self._init = True
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
        self._size = (ctypes.windll.user32.GetSystemMetrics(0),
                      ctypes.windll.user32.GetSystemMetrics(1))
        try:
            import dxcam
            self._dx = dxcam.create(output_color="BGR")
        except Exception:
            self._dx = None
        try:
            import mss as _m
            self._mss = _m
        except Exception:
            self._mss = None

    def ensure_started(self):
        self._setup()

    def grab_bgr(self):
        import numpy as np
        import cv2
        self._setup()
        if self._dx is not None:
            try:
                f = self._dx.grab()
                if f is not None:
                    self._last = f
                if self._last is not None:
                    return self._last
            except Exception:
                pass
        if self._mss is not None:
            try:
                with self._mss.mss() as sct:
                    raw = sct.grab(sct.monitors[1])
                    return np.ascontiguousarray(np.asarray(raw)[:, :, :3])
            except Exception:
                pass
        from PIL import ImageGrab
        img = ImageGrab.grab()
        return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)

    def size(self):
        self._setup()
        return self._size


_capture = _WinCapture() if IS_WINDOWS else _PortalCapture()


# ═══════════ BOSHQARUV: uinput virtual qurilma (ruxsat so'ramaydi) ═══════════
class _UInputController:
    """Virtual sichqoncha+klaviatura (uinput). Portal ruxsati kerak emas —
    /dev/uinput ochiq bo'lsa (udev qoidasi) bevosita ishlaydi."""

    def __init__(self):
        self._ui = None
        self._lock = threading.Lock()
        self._err = None

    def _dev(self):
        if self._ui is not None:
            return self._ui
        with self._lock:
            if self._ui is not None:
                return self._ui
            if self._err:
                raise RuntimeError(self._err)
            try:
                from evdev import UInput, ecodes as e, AbsInfo
                self._e = e
                keys = [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE, e.BTN_TOUCH,
                        e.BTN_TOOL_PEN]
                keys += list(_KEYMAP_KEYS)
                cap = {
                    e.EV_KEY: keys,
                    e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL],
                    e.EV_ABS: [
                        (e.ABS_X, AbsInfo(0, 0, 65535, 0, 0, 0)),
                        (e.ABS_Y, AbsInfo(0, 0, 65535, 0, 0, 0)),
                    ],
                }
                self._ui = UInput(cap, name="remotepc-virtual-input", version=1)
                time.sleep(0.3)  # kompozitor qurilmani tanishi uchun
            except Exception as ex:
                self._err = "uinput ochilmadi: " + repr(ex)
                raise RuntimeError(self._err)
        return self._ui

    def move_abs(self, fx, fy):
        e = self._e_or_load()
        ui = self._dev()
        ui.write(e.EV_ABS, e.ABS_X, int(max(0.0, min(1.0, fx)) * 65535))
        ui.write(e.EV_ABS, e.ABS_Y, int(max(0.0, min(1.0, fy)) * 65535))
        ui.write(e.EV_KEY, e.BTN_TOOL_PEN, 1)
        ui.syn()

    def move_rel(self, dx, dy):
        ui = self._dev(); e = self._e
        ui.write(e.EV_REL, e.REL_X, int(dx))
        ui.write(e.EV_REL, e.REL_Y, int(dy))
        ui.syn()

    def button(self, btn, down):
        ui = self._dev(); e = self._e
        code = {"left": e.BTN_LEFT, "right": e.BTN_RIGHT, "middle": e.BTN_MIDDLE}.get(btn, e.BTN_LEFT)
        ui.write(e.EV_KEY, code, 1 if down else 0)
        ui.syn()

    def click(self, btn="left"):
        if btn == "double":
            for _ in range(2):
                self.button("left", True); self.button("left", False)
                time.sleep(0.03)
            return
        self.button(btn, True)
        time.sleep(0.01)
        self.button(btn, False)

    def scroll(self, amount):
        ui = self._dev(); e = self._e
        steps = int(round(amount / 120.0)) or (1 if amount > 0 else -1)
        ui.write(e.EV_REL, e.REL_WHEEL, steps)
        ui.syn()

    def _tap(self, code, shift=False):
        ui = self._dev(); e = self._e
        if shift:
            ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1); ui.syn()
        ui.write(e.EV_KEY, code, 1); ui.syn()
        ui.write(e.EV_KEY, code, 0); ui.syn()
        if shift:
            ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0); ui.syn()

    def type_text(self, text):
        for ch in text:
            m = _CHARMAP.get(ch)
            if m:
                self._tap(m[0], m[1])
            elif ch.isupper():
                b = _CHARMAP.get(ch.lower())
                if b:
                    self._tap(b[0], True)

    def special(self, name):
        code = _SPECIAL.get(name)
        if code is not None:
            self._tap(code)

    def combo(self, combo):
        codes = []
        for p in combo.lower().split("+"):
            p = p.strip()
            if p in _MODS:
                codes.append(_MODS[p])
            elif p in _SPECIAL:
                codes.append(_SPECIAL[p])
            elif len(p) == 1 and p in _CHARMAP:
                codes.append(_CHARMAP[p][0])
        ui = self._dev(); e = self._e
        for c in codes:
            ui.write(e.EV_KEY, c, 1); ui.syn()
        for c in reversed(codes):
            ui.write(e.EV_KEY, c, 0); ui.syn()

    def _e_or_load(self):
        self._dev()
        return self._e


# Tugma jadvallari (evdev) — dangasa tuzamiz, chunki evdev import vaqtida kerak
def _build_maps():
    from evdev import ecodes as e
    base = {}
    for c in "abcdefghijklmnopqrstuvwxyz":
        base[c] = (getattr(e, "KEY_" + c.upper()), False)
    digits = "1234567890"
    for d in digits:
        base[d] = (getattr(e, "KEY_" + d), False)
    punct = {
        " ": e.KEY_SPACE, "-": e.KEY_MINUS, "=": e.KEY_EQUAL, "[": e.KEY_LEFTBRACE,
        "]": e.KEY_RIGHTBRACE, "\\": e.KEY_BACKSLASH, ";": e.KEY_SEMICOLON,
        "'": e.KEY_APOSTROPHE, "`": e.KEY_GRAVE, ",": e.KEY_COMMA, ".": e.KEY_DOT,
        "/": e.KEY_SLASH, "\t": e.KEY_TAB, "\n": e.KEY_ENTER,
    }
    for c, code in punct.items():
        base[c] = (code, False)
    shifted = {
        "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
        "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]",
        "|": "\\", ":": ";", '"': "'", "~": "`", "<": ",", ">": ".", "?": "/",
    }
    for sym, basech in shifted.items():
        base[sym] = (base[basech][0], True)
    special = {
        "enter": e.KEY_ENTER, "backspace": e.KEY_BACKSPACE, "tab": e.KEY_TAB,
        "esc": e.KEY_ESC, "up": e.KEY_UP, "down": e.KEY_DOWN, "left": e.KEY_LEFT,
        "right": e.KEY_RIGHT, "win": e.KEY_LEFTMETA, "delete": e.KEY_DELETE,
        "space": e.KEY_SPACE, "home": e.KEY_HOME, "end": e.KEY_END,
        "pageup": e.KEY_PAGEUP, "pagedown": e.KEY_PAGEDOWN,
        "volup": e.KEY_VOLUMEUP, "voldown": e.KEY_VOLUMEDOWN, "mute": e.KEY_MUTE,
        "playpause": e.KEY_PLAYPAUSE, "next": e.KEY_NEXTSONG, "prev": e.KEY_PREVIOUSSONG,
    }
    mods = {"ctrl": e.KEY_LEFTCTRL, "alt": e.KEY_LEFTALT,
            "shift": e.KEY_LEFTSHIFT, "win": e.KEY_LEFTMETA}
    allkeys = set(code for code, _ in base.values()) | set(special.values()) | set(mods.values())
    return base, special, mods, sorted(allkeys)


try:
    _CHARMAP, _SPECIAL, _MODS, _KEYMAP_KEYS = _build_maps()
except Exception:
    _CHARMAP, _SPECIAL, _MODS, _KEYMAP_KEYS = {}, {}, {}, []

# ─────────────────────────── Windows boshqaruv (ctypes) ───────────────────────────
_WIN_BTN = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
_WIN_VK = {
    "enter": 0x0D, "backspace": 0x08, "tab": 0x09, "esc": 0x1B,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "win": 0x5B,
    "delete": 0x2E, "space": 0x20, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "volup": 0xAF, "voldown": 0xAE,
    "mute": 0xAD, "playpause": 0xB3, "next": 0xB0, "prev": 0xB1,
}
_WIN_MODS = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}


class _WinInput:
    def __init__(self):
        self._u = None
        self._sw = self._sh = 0

    def _user32(self):
        if self._u is None:
            import ctypes
            self._u = ctypes.windll.user32
            try:
                self._u.SetProcessDPIAware()
            except Exception:
                pass
            self._sw = self._u.GetSystemMetrics(0)
            self._sh = self._u.GetSystemMetrics(1)
        return self._u

    def move_abs(self, fx, fy):
        u = self._user32()
        u.SetCursorPos(int(max(0.0, min(1.0, fx)) * self._sw),
                       int(max(0.0, min(1.0, fy)) * self._sh))

    def move_rel(self, dx, dy):
        import ctypes
        u = self._user32()

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        u.GetCursorPos(ctypes.byref(pt))
        u.SetCursorPos(pt.x + int(dx), pt.y + int(dy))

    def button(self, btn, down):
        u = self._user32()
        d, up = _WIN_BTN.get(btn, _WIN_BTN["left"])
        u.mouse_event(d if down else up, 0, 0, 0, 0)

    def click(self, btn="left"):
        if btn == "double":
            for _ in range(2):
                self.button("left", True); self.button("left", False)
            return
        self.button(btn, True); self.button(btn, False)

    def scroll(self, amount):
        self._user32().mouse_event(0x0800, 0, 0, int(amount), 0)

    def type_text(self, text):
        u = self._user32()
        for ch in text:
            c = ord(ch)
            u.keybd_event(0, c, 0x0004, 0)
            u.keybd_event(0, c, 0x0004 | 0x0002, 0)

    def special(self, name):
        vk = _WIN_VK.get(name)
        if vk:
            u = self._user32()
            u.keybd_event(vk, 0, 0, 0)
            u.keybd_event(vk, 0, 0x0002, 0)

    def combo(self, combo):
        vks = []
        for p in combo.lower().split("+"):
            p = p.strip()
            if p in _WIN_MODS:
                vks.append(_WIN_MODS[p])
            elif p in _WIN_VK:
                vks.append(_WIN_VK[p])
            elif len(p) == 1:
                vks.append(ord(p.upper()))
        u = self._user32()
        for v in vks:
            u.keybd_event(v, 0, 0, 0)
        for v in reversed(vks):
            u.keybd_event(v, 0, 0x0002, 0)


_input = _WinInput() if IS_WINDOWS else _UInputController()


# Boshqaruv — modul darajasidagi qulay funksiyalar (webapp ishlatadi)
def input_move(fx, fy): _input.move_abs(fx, fy)
def input_move_rel(dx, dy): _input.move_rel(dx, dy)
def input_click(btn="left"): _input.click(btn)
def input_button(btn, down): _input.button(btn, down)
def input_scroll(amount): _input.scroll(amount)
def input_type(text): _input.type_text(text)
def input_special(name): _input.special(name)
def input_combo(keys): _input.combo(keys)


def grab_bgr():
    """Ekranning BGR numpy massivini qaytaradi (OpenCV formati)."""
    return _capture.grab_bgr()


def grab_pil():
    """Ekranni PIL.Image (RGB) sifatida qaytaradi."""
    import numpy as np  # noqa
    from PIL import Image
    bgr = _capture.grab_bgr()
    return Image.fromarray(bgr[:, :, ::-1])


def screen_size():
    return _capture.size()


def capture_available() -> bool:
    try:
        _capture.ensure_started()
        return True
    except Exception:
        return False


def _pack(GLib, iface, method, params):
    """Portal metodlari uchun to'g'ri Variant tuple yasaydi."""
    sigs = {
        ("CreateSession",): "(a{sv})",
        ("SelectDevices",): "(oa{sv})",
        ("SelectSources",): "(oa{sv})",
        ("Start",): "(osa{sv})",
    }
    sig = sigs.get((method,))
    if sig is None:
        raise CaptureUnavailable(f"noma'lum metod: {method}")
    return GLib.Variant(sig, tuple(params))
