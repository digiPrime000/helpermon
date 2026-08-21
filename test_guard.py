"""
The run control: the mouse-movement pause and the switch that turns it off.

No emulator and no display needed. The mouse is faked, so the watcher can be
driven through the exact sequence that matters -- pause, switch off, and
whether the bot is left sitting paused with nothing to resume it.

  py test_guard.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guard
import userdata


# --- the flag file, which is what two processes share ---------------------
def flag_file():
    folder = tempfile.mkdtemp(prefix="helpermon_test_")
    old_env, old_cache = os.environ.get("DGUP_DATA"), userdata._CACHED
    os.environ["DGUP_DATA"] = folder
    userdata._CACHED = None
    try:
        assert userdata.mouse_pause() is True, "a fresh folder must mean on"
        assert userdata.set_mouse_pause(False) is False
        assert os.path.exists(os.path.join(folder, userdata.MOUSE_PAUSE_FLAG)), \
            "off has to leave something on disk, or the other process cannot see it"
        assert userdata.mouse_pause() is False
        assert userdata.set_mouse_pause(True) is True
        assert not os.path.exists(os.path.join(folder, userdata.MOUSE_PAUSE_FLAG))
        print("the switch is a file, so a second window sees it")

        # A deleted data folder must not silently turn the pause off.
        userdata.set_mouse_pause(False)
        shutil.rmtree(folder)
        assert userdata.mouse_pause() is True, \
            "a missing folder read as off would let a bot drive over your hand"
        print("a folder that is gone reads as on, not as off")
    finally:
        userdata._CACHED = old_cache
        if old_env is None:
            os.environ.pop("DGUP_DATA", None)
        else:
            os.environ["DGUP_DATA"] = old_env
        shutil.rmtree(folder, ignore_errors=True)


# --- the watcher, driven with a fake mouse --------------------------------
class Flag:
    """Stands in for userdata, so the real setting is never touched."""

    def __init__(self, on=True):
        self.on = on

    def mouse_pause(self):
        return self.on


def watcher():
    """A started RunControl with a mouse that can be moved by hand."""
    stop = guard.Stop()
    # resume_after is long on purpose: a mouse pause lifts itself once the
    # mouse has been still, and with a short window it would already have
    # done so before the assertion got to look.
    control = guard.RunControl(stop, tick=0.02, resume_after=30.0,
                               log=lambda _t: None)
    control._running = True
    return stop, control


def run_watch(control, seconds=0.3):
    thread = threading.Thread(target=control._watch_mouse, daemon=True)
    thread.start()
    time.sleep(seconds)
    control._running = False
    thread.join(timeout=1.0)


def main():
    flag_file()

    real_userdata, real_cursor = guard.userdata, guard.cursor_pos
    position = [(0, 0)]
    guard.cursor_pos = lambda: position[0]
    flag = Flag(True)
    guard.userdata = flag
    try:
        # A moving mouse pauses.
        stop, control = watcher()
        thread = threading.Thread(target=control._watch_mouse, daemon=True)
        thread.start()
        time.sleep(0.1)
        position[0] = (500, 500)
        time.sleep(0.15)
        assert stop.is_paused(), "a moved mouse did not pause the bot"
        print("a moved mouse pauses the bot")

        # Switching the pause off while it holds the pause has to let go.
        flag.on = False
        time.sleep(0.15)
        assert not stop.is_paused(), \
            "switched off while paused and left the bot paused for ever"
        print("switching it off while it holds the pause releases it")

        # And with it off, moving the mouse does nothing at all.
        position[0] = (900, 900)
        time.sleep(0.15)
        assert not stop.is_paused(), "paused although the switch is off"
        print("with the switch off a moving mouse is ignored")
        control._running = False
        thread.join(timeout=1.0)

        # A pause somebody asked for by hotkey is not this watcher's to undo.
        stop, control = watcher()
        flag.on = True
        control._on_hotkey_pause()
        assert stop.is_paused()
        flag.on = False
        run_watch(control, 0.15)
        assert stop.is_paused(), \
            "the switch cancelled a pause that a person had asked for"
        print("a hotkey pause survives the switch, it was not the mouse's")
    finally:
        guard.userdata, guard.cursor_pos = real_userdata, real_cursor

    print("all run-control cases as expected")


if __name__ == "__main__":
    main()
