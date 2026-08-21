"""
Screen sources and input. Three ways, all with the same interface.

  window   frames by screen capture, input by mouse and keyboard. No ADB needed
  hybrid   frames by screen capture, clicks via ADB. Fast and the mouse stays free
  ADB      everything through ADB. Slow but insensitive to window state

Frames always come from the window where possible, measured 9 ms against 430 ms
for ADB. ADB only ever handled input.

All classes provide `grab`, `tap`, `swipe`, `back` and `focus`. That matters
because the bots used to reach through to ADB directly in several places, and a
missing method would only have surfaced during a run.
"""

import glob
import os
import re
import struct
import subprocess
import time

import cv2
import numpy as np


class CaptureError(RuntimeError):
    pass


# LDPlayer ships ADB but does not put it on the PATH. So it is searched for
# here. A custom path can be set via the DGUP_ADB environment variable.
ADB_CANDIDATES = [
    r"C:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\LDPlayer\LDPlayer64\adb.exe",
    r"C:\Program Files\LDPlayer\LDPlayer9\adb.exe",
    r"C:\Program Files (x86)\LDPlayer\LDPlayer9\adb.exe",
    r"D:\LDPlayer\LDPlayer9\adb.exe",
]



# Where the game sits inside the emulator window: left, top, right, bottom in
# pixels. It does not scale with the window. Measured on two window sizes on
# the same machine, each matched against the ADB frame of the same screen:
#
#   window 805 x 1390   game 758 x 1348 at 4, 40   correlation 0.99
#   window 619 x 1059   game 572 x 1017 at 4, 40   correlation 0.95
#
# The 43 px on the right are LDPlayer's own sidebar, the 40 on top its tab
# bar. Both are in every window frame and in none of an ADB frame, which is
# the whole reason the two have to be reconciled at all.
WINDOW_CHROME = (4, 40, 43, 2)

# The same thing as fractions of the 805 x 1390 window the dungeon bot's
# positions were measured in. That window is the reference: see game_rect in
# dungeon.py for what the numbers there mean.
GAME_IN_WINDOW = (4 / 805.0, 40 / 1390.0, 758 / 805.0, 1348 / 1390.0)

# A window frame and an ADB frame of the same moment correlate at 0.99 once
# the chrome is off. A window frame showing something else scores near zero.
# Measured on four real pairs:
#
#   the same screen, 805 window          0.998
#   the same screen, 619 window          0.995
#   window one screen behind             0.036
#   window on the title screen, game on the dungeon list   -0.090
#
# The threshold sits in the middle of that gap. Without the chrome removed
# the same pairs score 0.43 against 0.24 and cannot be told apart at all.
FRAMES_AGREE_MIN = 0.5


def frames_agree(window_img, device_img):
    """Do a window frame and an ADB frame show the same thing?

    Worth asking because a window frame can go stale without any error: while
    the display sleeps, screen capture returns the last thing that was drawn
    for as long as it stays asleep, and a bot reading that picture clicks at
    what the screen showed minutes ago. ADB does not have that problem, so
    when the two disagree, ADB is the one to believe.
    """
    left, top, right, bottom = WINDOW_CHROME
    game = window_img[top:window_img.shape[0] - bottom,
                      left:window_img.shape[1] - right]
    if game.size == 0 or device_img.size == 0:
        return -1.0
    size = (96, 171)
    a = cv2.resize(cv2.cvtColor(game, cv2.COLOR_BGR2GRAY), size,
                   interpolation=cv2.INTER_AREA).astype(np.float32)
    b = cv2.resize(cv2.cvtColor(device_img, cv2.COLOR_BGR2GRAY), size,
                   interpolation=cv2.INTER_AREA).astype(np.float32)
    a -= a.mean()
    b -= b.mean()
    spread = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / spread) if spread else -1.0


# The game runs portrait, 1080:1920, so the emulator window is markedly
# taller than it is wide: measured 574x1051 and 765x1390, ratio 1.83. The
# lower bound leaves room for LDPlayer's side toolbar, which widens the
# window without widening the game area; the upper bound is slack.
#
# This exists because a title match alone is not evidence. "DIGI" matched a
# browser window and the launcher cheerfully reported an emulator at
# 976x739, ratio 0.76, with LDPlayer not running.
EMULATOR_MIN_RATIO = 1.4
EMULATOR_MAX_RATIO = 2.3


# Window names worth trying. Which of them is the emulator is decided by
# the program behind the window, not by the name itself.
EMULATOR_TITLES = ("LDPlayer", "BlueStacks", "MEmu", "Nox", "MuMu")

# The emulator renames its own window to whatever app is running, so the
# game's name has to be tried too.
GAME_TITLES = ("DIGIMON", "DIGI")

# The executables those windows belong to. This is the part that does not
# change when the title does.
EMULATOR_PROCESSES = ("dnplayer.exe", "dnmultiplayer.exe", "ldplayer.exe",
                      "ld.exe", "ldconsole.exe", "bluestacks.exe",
                      "hd-player.exe", "bluestacksgp.exe", "memu.exe",
                      "memuheadless.exe", "nox.exe", "noxvmhandle.exe",
                      "mumuplayer.exe", "mumunxdevice.exe")


def window_process(win):
    """Executable owning a window, lowercased file name, or "" if it cannot
    be read. Windows only, and a failure here is not fatal -- the caller
    falls back to judging by shape."""
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = getattr(win, "_hWnd", None)
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
                handle, 0, buf, ctypes.byref(size))
            if not ok:
                return ""
            # Full path, not just the file name: an emulator installs its
            # programs into a folder named after itself, which identifies
            # the ones this list has never heard of.
            return buf.value.lower().replace("\\", "/")
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return ""


def is_emulator_process(path):
    """Known program, or any program living in an emulator's own folder."""
    if not path:
        return False
    if os.path.basename(path) in EMULATOR_PROCESSES:
        return True
    folder = os.path.dirname(path)
    return any(name.lower() in folder for name in EMULATOR_TITLES)


def looks_like_emulator(img):
    """True if this frame could be a portrait phone screen."""
    if img is None or getattr(img, "size", 0) == 0:
        return False
    h, w = img.shape[:2]
    if w < 200 or h < 200:
        return False
    return EMULATOR_MIN_RATIO <= h / float(w) <= EMULATOR_MAX_RATIO


def _ld_version(path):
    """Version number out of an LDPlayer install path, for sorting."""
    found = re.findall(r"ldplayer[ _-]*(\d+)", path.lower())
    return max((int(n) for n in found), default=0)


def ld_installs(filename, roots=("C:\\", "D:\\")):
    """Every LDPlayer install carrying this file, newest version first.

    Newest first because a machine can have two: version 9 left behind and
    version 14 in use. A fixed list of paths cannot express "the newer one",
    and the one that happened to be typed first won.
    """
    found = set()
    for root in roots:
        for pattern in (root + "LDPlayer*/" + filename,
                        root + "LDPlayer*/*/" + filename,
                        root + "Program Files/LDPlayer*/*/" + filename,
                        root + "Program Files (x86)/LDPlayer*/*/" + filename):
            found.update(glob.glob(pattern))
    return sorted(found, key=lambda p: (-_ld_version(p), p))


def find_adb():
    """Order: environment variable, PATH, newest LDPlayer install."""
    env = os.environ.get("DGUP_ADB")
    if env and os.path.exists(env):
        return env
    from shutil import which

    if which("adb"):
        return "adb"
    installs = ld_installs("adb.exe")
    if installs:
        return installs[0]
    for path in ADB_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


class AdbCapture:
    def __init__(self, adb=None, serial=None):
        self.adb = adb or find_adb() or "adb"
        serial = serial or os.environ.get("DGUP_SERIAL")
        self.method = os.environ.get("DGUP_SCREENCAP", "png")
        self.serial = serial

    def _cmd(self, *args):
        base = [self.adb]
        if self.serial:
            base += ["-s", self.serial]
        return base + list(args)

    def devices(self):
        out = subprocess.run(
            self._cmd("devices"), capture_output=True, text=True, timeout=15
        ).stdout
        return [
            line.split("\t")[0]
            for line in out.splitlines()[1:]
            if line.strip().endswith("device")
        ]

    # PNG is encoded on the device and costs time. Raw is usually faster but
    # larger to transfer. Which is faster depends on the system, so it is
    # measured.
    RAW_HEADER_SIZES = (12, 16)  # older and newer Android versions

    def grab(self):
        if self.method == "raw":
            try:
                return self._grab_raw()
            except Exception as err:
                self.method = "png"
                print("raw frame failed (%s), falling back to PNG" % err)
        return self._grab_png()

    def _grab_raw(self):
        res = subprocess.run(
            self._cmd("exec-out", "screencap"), capture_output=True, timeout=20)
        buf = res.stdout
        if not buf:
            raise CaptureError("raw screencap empty")
        for head in self.RAW_HEADER_SIZES:
            w, h, fmt = struct.unpack("<III", buf[:12])
            if 0 < w < 10000 and 0 < h < 10000 and len(buf) - head == w * h * 4:
                arr = np.frombuffer(buf[head:], np.uint8).reshape(h, w, 4)
                return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        raise CaptureError("raw format not recognised, %d bytes" % len(buf))

    def _grab_png(self):
        res = subprocess.run(
            self._cmd("exec-out", "screencap", "-p"), capture_output=True, timeout=20
        )
        if not res.stdout:
            hint = (res.stderr or b"").decode(errors="replace").strip()
            raise CaptureError(
                "ADB screencap empty from %s%s. The device is listed but returns no "
                "frame. Usually a stale TCP connection."
                % (self.serial or "default device", ", ADB says: " + hint if hint else ""))
        img = cv2.imdecode(np.frombuffer(res.stdout, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise CaptureError("ADB screencap could not be decoded")
        return img

    def benchmark(self, rounds=3):
        """Measure both methods and keep the faster one."""
        timings = {}
        for method in ("raw", "png"):
            self.method = method
            try:
                t0 = time.time()
                for _ in range(rounds):
                    self.grab()
                timings[method] = (time.time() - t0) / rounds
            except Exception:
                continue
        if not timings:
            self.method = "png"
            return timings
        self.method = min(timings, key=timings.get)
        return timings

    def works(self):
        """Real test. A device only counts as usable if a screenshot arrives.
        The device list alone lies, stale TCP connections still show up in
        it and yield nothing."""
        try:
            img = self.grab()
            return img is not None and img.shape[0] > 200
        except Exception:
            return False

    def tap(self, x, y):
        subprocess.run(self._cmd("shell", "input", "tap", str(int(x)), str(int(y))),
                       timeout=15)

    def swipe(self, x1, y1, x2, y2, ms=300):
        subprocess.run(self._cmd("shell", "input", "swipe", str(int(x1)),
                                 str(int(y1)), str(int(x2)), str(int(y2)), str(ms)),
                       capture_output=True, timeout=20)

    def back(self):
        subprocess.run(self._cmd("shell", "input", "keyevent", "4"),
                       capture_output=True, timeout=15)
        return True

    def focus(self):
        return True


class WindowCapture:
    """Frames and input exclusively via the window, without ADB.

    Frames come from screen capture, that was already the case before and is
    fast, measured 9 ms against 430 ms with ADB. Input goes through the mouse
    instead of ADB.

    The price for that: the mouse is blocked during the run and the window
    must be visible and in the foreground. It also computes in window
    coordinates, not device coordinates. Anyone using relative positions
    notices none of that.

    `last_bot_move` is a monotonic timestamp, refreshed every time this class
    moves the real cursor for one of its own clicks or swipes. A mouse-
    movement watcher can compare against it to tell the bot's own cursor
    movement apart from a human grabbing the mouse.

    A plain busy flag was tried first and was not enough: a tap() finishes
    in well under 100 ms, faster than a watcher polling every 200 ms is
    guaranteed to sample, so most clicks never got caught mid-flight and
    were misread as a human interruption. A timestamp does not have that
    race, the watcher just waits out a grace window after the most recent
    stamp instead of needing to observe the move itself.
    """

    def __init__(self, title_contains="LDPlayer"):
        import mss  # noqa
        import pygetwindow as gw  # noqa

        self.mss = __import__("mss").mss()
        self.gw = __import__("pygetwindow")
        self.title = title_contains
        self._input = None
        self.last_bot_move = 0.0

    def _note_move(self):
        self.last_bot_move = time.monotonic()

    # ------------------------------------------------------------------
    def _window(self):
        for win in self.gw.getAllWindows():
            if self.title.lower() in (win.title or "").lower() and win.width > 200:
                return win
        raise CaptureError("no emulator window with title %r" % self.title)

    def geometry(self):
        win = self._window()
        return win.left, win.top, win.width, win.height

    def grab(self):
        left, top, width, height = self.geometry()
        box = {"left": left, "top": top, "width": width, "height": height}
        shot = np.array(self.mss.grab(box))
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

    # ------------------------------------------------------------------
    def _pi(self):
        """Load pydirectinput lazily. It sends input at a lower level than
        pyautogui and is recognised more reliably by emulators."""
        if self._input is None:
            import pydirectinput
            pydirectinput.FAILSAFE = False
            pydirectinput.PAUSE = 0.0
            self._input = pydirectinput
        return self._input

    def focus(self):
        """Bring the window to the front. Without focus, clicks go nowhere
        or hit the wrong window."""
        try:
            win = self._window()
            if not win.isActive:
                win.activate()
                time.sleep(0.15)
            return True
        except Exception:
            return False

    def _abs(self, x, y):
        left, top, _, _ = self.geometry()
        return int(left + x), int(top + y)

    def tap(self, x, y):
        pi = self._pi()
        ax, ay = self._abs(x, y)
        self.focus()
        pi.moveTo(ax, ay)
        self._note_move()
        time.sleep(0.04)
        pi.click()
        self._note_move()
        time.sleep(0.04)

    def swipe(self, x1, y1, x2, y2, ms=300):
        """Swipe as a held-down mouse with intermediate steps.

        A jump from A to B is not recognised by the game as a swipe, it
        needs actual motion. So it moves in steps instead.
        """
        pi = self._pi()
        self.focus()
        ax1, ay1 = self._abs(x1, y1)
        ax2, ay2 = self._abs(x2, y2)
        steps = max(8, int(ms / 25))
        pi.moveTo(ax1, ay1)
        self._note_move()
        time.sleep(0.05)
        pi.mouseDown()
        for i in range(1, steps + 1):
            t = i / float(steps)
            pi.moveTo(int(ax1 + (ax2 - ax1) * t), int(ay1 + (ay2 - ay1) * t))
            self._note_move()
            time.sleep(ms / 1000.0 / steps)
        time.sleep(0.08)
        pi.mouseUp()
        self._note_move()
        time.sleep(0.1)

    def back(self):
        """Back without ADB.

        LDPlayer maps the Android back key to Escape by default. Should that
        be bound differently for you, it can be checked in the emulator's
        keyboard settings.
        """
        pi = self._pi()
        self.focus()
        pi.press("esc")
        time.sleep(0.15)
        return True

    @property
    def method(self):
        return "window"

    @method.setter
    def method(self, value):
        pass


class HybridCapture:
    """Frames via window capture, clicks via ADB.

    Reason: an ADB screenshot costs about 430 ms on the test system and thus
    dictates the bot's pace. A window capture is usually 30 to 60 ms. Clicks
    keep going through ADB, so the mouse stays free and the window may sit
    in the background as long as it stays visible.

    Coordinates differ between the window image and the device, so the
    conversion factor is determined once from a calibration of each image.
    """

    def __init__(self, window, adb):
        self.window = window
        self.adb = adb
        self.transform = None

    def grab(self):
        return self.window.grab()

    def calibrate_transform(self, calibrate_fn):
        """Determine the factor and offset between window image and device image."""
        win = calibrate_fn(self.window.grab())
        dev = calibrate_fn(self.adb.grab())
        scale = dev["cell_w"] / win["cell_w"]
        self.transform = dict(
            scale=scale,
            dx=dev["grid_x0"] - win["grid_x0"] * scale,
            dy=dev["grid_y0"] - win["grid_y0"] * scale,
        )
        # Cross-check, the cell heights must fit with the same factor
        err = abs(win["cell_h"] * scale - dev["cell_h"]) / dev["cell_h"]
        if err > 0.03:
            raise CaptureError(
                "window-to-device conversion implausible, deviation %.1f %%"
                % (err * 100))
        return self.transform

    def tap(self, x, y):
        if self.transform is None:
            # Without a conversion, coordinates are thought of as device
            # coordinates already, the way the dungeon bot does it. Pass
            # straight through in that case.
            self.adb.tap(x, y)
            return
        t = self.transform
        self.adb.tap(x * t["scale"] + t["dx"], y * t["scale"] + t["dy"])

    def swipe(self, x1, y1, x2, y2, ms=300):
        import subprocess
        try:
            subprocess.run(self.adb._cmd("shell", "input", "swipe", str(int(x1)),
                                         str(int(y1)), str(int(x2)), str(int(y2)),
                                         str(ms)),
                           capture_output=True, timeout=20)
        except Exception as err:
            raise CaptureError("swipe via ADB failed: %s" % err)

    def back(self):
        import subprocess
        try:
            subprocess.run(self.adb._cmd("shell", "input", "keyevent", "4"),
                           capture_output=True, timeout=15)
            return True
        except Exception:
            return False

    def geometry(self):
        return self.window.geometry()

    def focus(self):
        return self.window.focus()

    @property
    def method(self):
        return "window+ADB"

    @method.setter
    def method(self, value):
        self.adb.method = value


def open_capture(prefer="adb", **kwargs):
    if prefer == "adb":
        cap = AdbCapture(**{k: v for k, v in kwargs.items() if k in ("adb", "serial")})
        try:
            devs = cap.devices()
        except Exception as err:  # ADB fehlt oder antwortet nicht
            devs = []
            print("ADB not usable (%s), falling back to window capture" % err)

        if devs:
            # try the desired device first, then the rest
            order = ([cap.serial] if cap.serial in devs else []) +\
                    [d for d in devs if d != cap.serial]
            if cap.serial and cap.serial not in devs:
                print("preferred device %s is not in the list %s"
                      % (cap.serial, devs))
                order = devs
            for serial in order:
                cap.serial = serial
                if cap.works():
                    print("ADB via %s, device %s" % (cap.adb, serial))
                    if len(devs) > 1:
                        print("  (chosen from %s, pin it with DGUP_SERIAL)" % devs)
                    return cap
                print("device %s returns no frame, skipping" % serial)
            print("no ADB device returns a frame, falling back to window capture")
        else:
            print("ADB reported no device, falling back to window capture")
    return WindowCapture(**{k: v for k, v in kwargs.items() if k == "title_contains"})


def _find_emulator_window(title_contains="LDPlayer"):
    """First window that is credibly the emulator.

    Named after an emulator: believed. LDPlayer's own window is landscape
    when maximised, because its home screen is, and only the game inside it
    is portrait -- so demanding a portrait window here threw away the
    emulator itself.

    Named only after the game: has to have the shape of a phone screen.
    Those titles are matched by substring and "DIGI" finds a browser tab
    about the game, which is how the launcher once reported an emulator at
    976x739 with LDPlayer shut. What was rejected is collected and reported,
    because "not found" while a window plainly matched is the confusing case.
    """
    rejected = []
    wanted = [title_contains] + [t for t in EMULATOR_TITLES
                                 if t.lower() != title_contains.lower()]
    for title in wanted + list(GAME_TITLES):
        try:
            win = WindowCapture(title_contains=title)
            img = win.grab()
        except Exception:
            continue
        if img is None or getattr(img, "size", 0) == 0:
            continue
        h, w = img.shape[:2]
        try:
            process = window_process(win._window())
        except Exception:
            process = ""
        if is_emulator_process(process):
            return win, rejected
        if process:
            # The program is known and is not an emulator. That is a real
            # answer, not a doubt to resolve by shape.
            rejected.append("%r belongs to %s" % (title, process))
            continue
        # No answer from the system: fall back to the shape, which is all
        # there was before.
        if not looks_like_emulator(img):
            rejected.append("%r is %dx%d, not the shape of a phone screen"
                            % (title, w, h))
            continue
        return win, rejected
    return None, rejected


def _no_window_error(rejected):
    text = ("no emulator window found. Is LDPlayer running and the window "
            "visible, meaning not minimised?")
    if rejected:
        text += (" Windows matching the name but not the shape of a phone "
                 "screen were ignored: %s." % ", ".join(sorted(set(rejected))))
    return CaptureError(text)


def open_window(title_contains="LDPlayer", **kwargs):
    """Pure window mode, without ADB. Frames via screen capture, input via
    mouse and keyboard."""
    win, rejected = _find_emulator_window(title_contains)
    if win is None:
        raise _no_window_error(rejected)
    print("window mode active, input via mouse. The window has to stay visible.")
    return win


def open_best(title_contains="LDPlayer", prefer_adb=True, **kwargs):
    """Best available source. ADB for input first, then the window.

    Frames come from the window in both cases, that is clearly faster. The
    only difference is how clicks are sent.
    """
    if prefer_adb:
        try:
            hybrid = open_window_adb(title_contains, **kwargs)
            if isinstance(hybrid, HybridCapture):
                return hybrid
        except Exception:
            pass
    return open_window(title_contains, **kwargs)


def open_window_adb(title_contains="LDPlayer", **kwargs):
    """Frames via window capture, clicks via ADB, without conversion.

    For the dungeon bot. It works with relative positions and computes
    clicks into device coordinates itself, so it needs no conversion factor.
    open_hybrid, in contrast, determines the factor via the minigame
    calibration, and that fails in the menu because no game card is visible
    there.
    """
    adb = open_capture(prefer="adb", **kwargs)
    if not isinstance(adb, AdbCapture):
        return adb
    win, _rejected = _find_emulator_window(title_contains)
    if win is None:
        print("no suitable window found, staying with ADB")
        return adb
    score = _window_shows_the_game(win, adb)
    if score < FRAMES_AGREE_MIN:
        print("the window does not show what the device does (%.2f), "
              "staying with ADB" % score)
        return adb
    print("window capture active (%.2f), clicks via ADB" % score)
    return HybridCapture(win, adb)


def _window_shows_the_game(win, adb):
    """Agreement between the window and the device, or -1 if it cannot be had."""
    try:
        return frames_agree(win.grab(), adb.grab())
    except Exception as err:
        print("could not compare window and device (%s)" % err)
        return -1.0


def open_hybrid(calibrate_fn, title_contains="LDPlayer", **kwargs):
    """Tries window capture plus ADB clicks. Falls back to pure ADB on
    trouble, that is slower but insensitive."""
    adb = open_capture(prefer="adb", **kwargs)
    if not isinstance(adb, AdbCapture):
        return adb
    win, _rejected = _find_emulator_window(title_contains)
    if win is None:
        print("no suitable window found, staying with ADB")
        return adb
    score = _window_shows_the_game(win, adb)
    if score < FRAMES_AGREE_MIN:
        print("the window does not show what the device does (%.2f), "
              "staying with ADB" % score)
        return adb
    hybrid = HybridCapture(win, adb)
    try:
        hybrid.calibrate_transform(calibrate_fn)
    except Exception as err:
        print("window capture not usable (%s), staying with ADB" % err)
        return adb
    print("window capture active, factor %.3f, clicks still via ADB"
          % hybrid.transform["scale"])
    return hybrid
