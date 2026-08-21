"""
Shared run control for every bot: pause, resume, abort.

One implementation instead of each bot inventing its own pause handling.
Three ways to trigger a pause, all landing on the same flag:

  - a bot's own console key (space), handled by the bot itself
  - a global hotkey (default F7), works even when the emulator window has
    focus instead of the console, because it hooks the keyboard driver
    directly instead of reading console input
  - moving the real mouse while the bot is not driving it itself

A hotkey pause needs an explicit resume, that is a deliberate stop. A
mouse-triggered pause resumes on its own once the mouse has been still for
`resume_after` seconds, so nobody has to remember to un-pause after just
glancing at the screen.

The mouse part can be switched off from any window, through
`userdata.mouse_pause`. The watcher asks that flag on every tick rather than
once at the start, so the switch reaches a bot that is already running -- and
switching it off while it holds a pause lets that pause go, otherwise the bot
would sit paused with nothing left to resume it.

Needs the Windows API for the cursor position and the `keyboard` package for
the global hotkey. Both are optional at runtime: without them, that part of
the feature quietly does nothing instead of crashing a bot that only cares
about its own console keys.
"""

import threading
import time

import userdata

try:
    import keyboard
except ImportError:
    keyboard = None


def cursor_pos():
    """Current physical mouse position on screen, or None if it cannot be
    read (only Windows is supported)."""
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    except Exception:
        return None


class Stop:
    """Abort and pause signal. Checked before every action.

    The two belong together because both are checked at the same point,
    between two actions and never in the middle of one. Otherwise a click
    could be sent but never verified, and the bookkeeping would drift out of
    sync with what actually happened on screen.
    """

    def __init__(self):
        self._set = False
        self._paused = False
        self.reason = ""

    # abort
    def request(self, reason="abort requested"):
        self.reason = reason
        self._set = True

    def clear(self):
        self._set = False
        self._paused = False
        self.reason = ""

    def is_set(self):
        return self._set

    # pause
    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def toggle_pause(self):
        self._paused = not self._paused
        return self._paused

    def is_paused(self):
        return self._paused

    def wait_while_paused(self, emit=None, tick=0.15):
        """Blocks while paused. Returns (go_on, was_paused).

        was_paused tells the caller whether it actually waited, so it can
        re-read the screen afterwards. During the pause, a human may have
        moved the figure, or the mouse, themselves.
        """
        if not self._paused:
            return True, False
        if emit:
            emit({"art": "info", "text": "paused"})
        while self._paused and not self._set:
            time.sleep(tick)
        if self._set:
            return False, True
        if emit:
            emit({"art": "info", "text": "resuming, re-reading"})
        return True, True


class RunControl:
    """Global hotkey and mouse-movement watcher, layered on top of a Stop.

    Works with any capture object, whether or not it moves the real mouse
    for its own clicks. A capture object that does (WindowCapture) stamps a
    `last_bot_move` timestamp every time it does; RunControl waits out a
    grace window after the most recent stamp instead of mistaking the bot's
    own cursor movement for a human grabbing the mouse. A timestamp rather
    than a plain busy flag, because a single click finishes faster than this
    watcher is guaranteed to poll, so a boolean sampled by polling would
    often miss the click entirely and misread it as an interruption. A
    capture object that never touches the mouse itself (hybrid or ADB,
    clicks go through ADB) needs no such attribute at all: any real movement
    there is always a human, by construction, since the bot never puts its
    own hand on the mouse in that mode.
    """

    def __init__(self, control, cap=None, hotkey="f7", abort_key="f8",
                 mouse_tolerance=15, resume_after=3.0, tick=0.2,
                 settle_grace=0.35, log=print):
        self.control = control
        self.cap = cap
        self.hotkey = hotkey
        self.abort_key = abort_key
        self.mouse_tolerance = mouse_tolerance
        self.resume_after = resume_after
        self.tick = tick
        self.settle_grace = settle_grace
        self.log = log
        self._mouse_owns_pause = False
        self._running = False
        self._thread = None

    def start(self):
        self._register_hotkeys()
        if cursor_pos() is None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_mouse, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if keyboard is not None:
            try:
                keyboard.remove_hotkey(self.hotkey)
                keyboard.remove_hotkey(self.abort_key)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _register_hotkeys(self):
        if keyboard is None:
            # Not "pip install keyboard": the packages live in the .venv
            # install.bat builds, and a pip typed into a terminal is a
            # different Python that this one never sees.
            self.log("'keyboard' package missing, no global hotkey. "
                     "Run install.bat again to repair the installation.")
            return
        try:
            keyboard.add_hotkey(self.hotkey, self._on_hotkey_pause)
            keyboard.add_hotkey(self.abort_key, self._on_hotkey_abort)
            self.log("Keys: %s pauses/resumes, %s aborts, work even without "
                     "focus on this console" % (self.hotkey, self.abort_key))
        except Exception as err:
            self.log("global hotkeys not available (%s). If the emulator "
                     "runs as administrator, this script has to as well, "
                     "or neither of them does. Windows lets no ordinary "
                     "program reach an elevated window." % err)

    def _on_hotkey_pause(self):
        self._mouse_owns_pause = False
        paused = self.control.toggle_pause()
        self.log("    %s (hotkey %s)"
                 % ("paused" if paused else "resumed", self.hotkey))

    def _on_hotkey_abort(self):
        self.control.request("hotkey %s" % self.abort_key)
        self.log("    abort requested (hotkey %s)" % self.abort_key)

    # ------------------------------------------------------------------
    def _watch_mouse(self):
        """Poll the real cursor and pause on unexpected movement.

        `baseline` is reset to None while the capture object is still within
        `settle_grace` seconds of its own last bot-driven cursor move, so the
        first check afterwards only records a fresh baseline instead of
        comparing against a position from before that move. The grace window
        has to be a little longer than one poll tick, otherwise a click that
        finishes faster than `tick` could slip through both polls unseen and
        get misread as a human grabbing the mouse.
        """
        baseline = None
        still_since = None
        while self._running and not self.control.is_set():
            time.sleep(self.tick)
            if not userdata.mouse_pause():
                self._release_own_pause("mouse pause switched off")
                baseline = None
                still_since = None
                continue
            last_move = getattr(self.cap, "last_bot_move", None)
            if last_move is not None and time.monotonic() - last_move < self.settle_grace:
                baseline = None
                continue
            pos = cursor_pos()
            if pos is None:
                continue
            if baseline is None:
                baseline = pos
                continue
            moved = (abs(pos[0] - baseline[0]) > self.mouse_tolerance
                     or abs(pos[1] - baseline[1]) > self.mouse_tolerance)
            baseline = pos
            if moved:
                still_since = None
                if not self.control.is_paused():
                    self.log("    mouse moved, pausing")
                    self.control.pause()
                    self._mouse_owns_pause = True
            elif self._mouse_owns_pause:
                if not self.control.is_paused():
                    self._mouse_owns_pause = False
                elif still_since is None:
                    still_since = time.time()
                elif time.time() - still_since >= self.resume_after:
                    self.control.resume()
                    self._mouse_owns_pause = False
                    self.log("    mouse still for %.0f s, resuming"
                             % self.resume_after)


    def _release_own_pause(self, why):
        """Let go of a pause this watcher put on, and nothing else.

        A hotkey pause is somebody deciding to stop, and switching off the
        mouse watcher is not the same decision. Only the pause the mouse
        itself caused is lifted here.
        """
        if not self._mouse_owns_pause:
            return
        self._mouse_owns_pause = False
        if self.control.is_paused():
            self.control.resume()
            self.log("    %s, resuming" % why)


def start(control, cap=None, log=print, **kwargs):
    """Create and start a RunControl in one call."""
    rc = RunControl(control, cap=cap, log=log, **kwargs)
    rc.start()
    return rc
