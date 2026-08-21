"""
Start the game by clicking its icon, the way a person would.

Why this exists. The cold start goes through `ldconsole.exe`, and that is two
dependencies in one: it is LDPlayer's own tool, so it does nothing for
BlueStacks or MEmu, and opening the *game* through it needs the Android
package name, which needs ADB to look up. On a machine where ADB does not
work, `ensure_running` brings the emulator up and then cannot open the game.

Everything else in this project needs neither. It reads the window and moves
the mouse, which is why it works at all when ADB is broken. This closes the
one gap: learn what the game's icon looks like once, find it on the emulator's
home screen, click it. No ADB, no vendor tool, no package name.

  py launcher.py --probe        show whether the icon is on screen right now

The icon is learned in the setup wizard, from your own screen, and stored with
everything else under userdata. Nothing about it is shipped.
"""

import json
import os

import cv2
import numpy as np

import userdata

ICON_NAME = "game_icon"
META_NAME = "game_icon.json"

# Correlation the icon has to reach before it counts as found. A starting
# point, not a measured one: it is the same figure vision.py uses for "match
# one small picture against a screenshot", and the probe prints the score it
# actually got so it can be checked against real screens. Being wrong here is
# cheap in one direction and not the other -- a missed icon means the cold
# start says so and stops, a false one means a click into the desktop.
ICON_MIN_SCORE = 0.80

# Two icons of the same app do not exist, but a home screen full of similar
# tiles can produce a near-tie. A clear winner is required for the same
# reason skewer.match_icon requires one.
ICON_MIN_MARGIN = 0.05

_CACHE = None


# ----------------------------------------------------------------------------
def icon_path():
    return userdata.template_path(ICON_NAME)


def meta_path():
    return os.path.join(userdata.templates_dir(), META_NAME)


def save_icon(crop, frame_width):
    """Store the icon and the window width it was cut at.

    The width matters: the same icon is drawn larger in a larger emulator
    window, and a template cut at 765 px across does not match at 574 without
    being rescaled first.
    """
    global _CACHE
    cv2.imwrite(icon_path(), crop)
    with open(meta_path(), "w") as fh:
        json.dump({"frame_width": int(frame_width)}, fh)
    _CACHE = None
    return icon_path()


def _icon_stamp():
    """What the icon file looks like from outside: when and how big, or None
    if it is not there."""
    try:
        info = os.stat(icon_path())
        return (info.st_mtime, info.st_size)
    except OSError:
        return None


def load_icon(force=False):
    """The learned icon and the width it was learned at, or (None, 0).

    Cached against the file's own timestamp, not once and for ever. The
    wizard runs in its own process, so a launcher that had already looked
    and found nothing kept answering "no icon" for the rest of the session
    -- and Instant AFK refused to start with the icon sitting on disk. A
    stat per call is cheap; find_icon calls this in a polling loop, which is
    why the picture itself is still only read when it changes.
    """
    global _CACHE
    stamp = _icon_stamp()
    if force:
        _CACHE = None
    if _CACHE is not None and _CACHE[2] == stamp:
        return _CACHE[0], _CACHE[1]
    if stamp is None:
        _CACHE = (None, 0, None)
        return _CACHE[0], _CACHE[1]
    img = cv2.imread(icon_path())
    width = 0
    try:
        with open(meta_path()) as fh:
            width = int(json.load(fh).get("frame_width", 0))
    except Exception:
        width = 0
    _CACHE = (img, width, stamp)
    return _CACHE[0], _CACHE[1]


def forget_icon():
    global _CACHE
    _CACHE = None


def have_icon():
    return load_icon()[0] is not None


# ----------------------------------------------------------------------------
def find_icon(img, min_score=ICON_MIN_SCORE):
    """Where the game icon is in this frame, or None.

    Returns pixel coordinates in the frame that was passed in, because that
    is what a window-mode tap wants. Also returns the score and the runner-up
    so a caller can print them; a threshold nobody can see the working of is
    a threshold nobody can fix.
    """
    tpl, learned_width = load_icon()
    if tpl is None or img is None or getattr(img, "size", 0) == 0:
        return None

    if learned_width and abs(img.shape[1] / float(learned_width) - 1.0) > 0.02:
        factor = img.shape[1] / float(learned_width)
        new_w = max(8, int(round(tpl.shape[1] * factor)))
        new_h = max(8, int(round(tpl.shape[0] * factor)))
        tpl = cv2.resize(tpl, (new_w, new_h), interpolation=cv2.INTER_AREA)

    if tpl.shape[0] >= img.shape[0] or tpl.shape[1] >= img.shape[1]:
        return None

    res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    _min_v, score, _min_l, loc = cv2.minMaxLoc(res)

    # Runner-up, ignoring everything touching the winner, so the margin means
    # "a different place on screen" and not "one pixel to the left".
    masked = res.copy()
    h, w = tpl.shape[:2]
    x0, y0 = max(0, loc[0] - w // 2), max(0, loc[1] - h // 2)
    masked[y0:loc[1] + h // 2, x0:loc[0] + w // 2] = -1.0
    second = float(masked.max()) if masked.size else -1.0

    found = {"x": int(loc[0] + w // 2), "y": int(loc[1] + h // 2),
             "score": float(score), "second": second,
             "ok": bool(score >= min_score and score - second >= ICON_MIN_MARGIN)}
    return found


# How much of the screen has to differ for "something is moving".
#
# Much smaller than the share start_game asks for, because the two questions
# are different. There, it is "did my click do anything meaningful"; here it
# is "is this thing still busy", and a boot screen can be a small spinner on
# black -- measured at 0.8% of the pixels, which a 1% test calls stillness and
# would have declared the emulator ready while it was still starting.
STILL_SHARE = 0.002

# How long the screen has to have been quiet, and how long the emulator has
# had overall, before "no icon and nothing moving" is allowed to mean the game
# is already up.
#
# Both are generous because that verdict is a guess, while the icon is proof.
# Measured on a real start: at 14 s the wallpaper was painted and the icons
# were not, which is perfectly still and perfectly not the finished home
# screen -- and being declared "already running" there sent the whole cold
# start down the wrong path. The icons turned up a few seconds later.
BUSY_AFTER = 30.0
STILL_NEEDED = 5


def wait_for_home(cap, log=print, timeout=120.0, busy_after=BUSY_AFTER,
                  poll=1.5, still_needed=STILL_NEEDED, min_wait=0.0):
    """Wait until the emulator has actually finished starting.

    Its window appears within a couple of seconds; the Android behind it
    takes another ten to twenty. Treating the window as "ready" is how the
    cold start ended up inspecting a boot screen, concluding the game must
    already be open, and then tapping at a splash.

    Two ways out, neither needing ADB:

      "home"  the learned icon is on screen, so the home screen is up
      "busy"  the screen has stopped changing for a few polls in a row and
              it is not the home screen -- something else is up, most
              likely the game itself. A boot animation moves; a finished
              screen does not.

    Returns a dict with the state, the icon match if there was one, and how
    long it waited.
    """
    import time

    started = time.time()
    said = 0.0
    still = 0
    previous = None
    while time.time() - started < timeout:
        img = cap.grab()
        waited = time.time() - started

        # The icon is proof, not a hint, so it is never held back by a
        # timer. Everything else here is guesswork that needs one.
        found = find_icon(img) if have_icon() else None
        if found and found["ok"] and waited >= min_wait:
            log("home screen is up after %d s (icon %.2f)"
                % (waited, found["score"]))
            return {"state": "home", "icon": found, "waited": waited}

        if previous is not None and not _changed(img, previous,
                                                 min_share=STILL_SHARE):
            still += 1
        else:
            still = 0
        previous = img

        if still >= still_needed and waited >= busy_after:
            log("no icon, and nothing has moved for %.0f s after %d s - "
                "taking it that something else is already running"
                % (still * poll, waited))
            return {"state": "busy", "icon": found, "waited": waited}

        if waited - said >= 10:
            said = waited
            log("still starting up, %d s of %d" % (waited, timeout))
        time.sleep(poll)

    log("emulator still not settled after %d s" % timeout)
    return {"state": "timeout", "icon": None, "waited": time.time() - started}


def start_game(cap, log=print, settle=6.0, tries=3, pause_before=1.0):
    """Click the game's icon and confirm that something happened.

    Verified rather than assumed, like every other click in this project: the
    home screen after a successful tap does not look like the home screen
    before it. If nothing changes, the tap missed and this says so instead of
    reporting success.
    """
    import time

    if not have_icon():
        log("no game icon learned yet, run the setup wizard's Game icon step")
        return False

    for attempt in range(1, tries + 1):
        before = cap.grab()
        found = find_icon(before)
        if found is None:
            log("no game icon learned yet")
            return False
        log("icon match %.2f (runner-up %.2f) at %d,%d"
            % (found["score"], found["second"], found["x"], found["y"]))
        if not found["ok"]:
            log("icon not clearly on screen. Is the emulator showing its home "
                "screen? Attempt %d of %d." % (attempt, tries))
            time.sleep(settle / 2.0)
            continue

        # A moment before the click as well as after it: the home screen
        # has usually only just finished drawing. Not called `before` -- that
        # name is already the frame this compares against afterwards.
        time.sleep(pause_before)
        cap.tap(found["x"], found["y"])
        time.sleep(settle)
        after = cap.grab()
        if _changed(before, after):
            log("game icon clicked, screen changed")
            return True
        log("clicked, but the screen did not change. Attempt %d of %d."
            % (attempt, tries))
    return False


def _changed(before, after, min_share=0.02):
    """Did the screen visibly change? Coarse on purpose: a clock ticking is
    not a change, a launching app is."""
    if before is None or after is None or before.shape != after.shape:
        return True
    diff = cv2.absdiff(cv2.cvtColor(before, cv2.COLOR_BGR2GRAY),
                       cv2.cvtColor(after, cv2.COLOR_BGR2GRAY))
    return float(np.count_nonzero(diff > 30)) / diff.size >= min_share


# ----------------------------------------------------------------------------
def main():
    import argparse

    import capture

    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="show whether the icon is on screen, click nothing")
    ap.add_argument("--go", action="store_true", help="actually click it")
    args = ap.parse_args()

    tpl, width = load_icon(force=True)
    if tpl is None:
        print("no icon learned. Run: py setup_wizard.py --step \"Game icon\"")
        return
    print("icon learned at a window width of %d px, template %dx%d"
          % (width, tpl.shape[1], tpl.shape[0]))

    cap = capture.open_window()
    img = cap.grab()
    print("window %d x %d" % (img.shape[1], img.shape[0]))
    found = find_icon(img)
    if not found:
        print("nothing to match against")
        return
    print("best %.3f, runner-up %.3f, at %d,%d -> %s"
          % (found["score"], found["second"], found["x"], found["y"],
             "found" if found["ok"] else "NOT convincing"))
    if args.go:
        print("clicking" if found["ok"] else "not clicking, no clear match")
        if found["ok"]:
            start_game(cap)


if __name__ == "__main__":
    main()
