"""
Storage for learned data.

Everything the setup wizard learns lands here and never in the program folder.
That way a published copy contains no third-party image material, and a program
update deletes nothing that was learned.

Order of preference

  1. the DGUP_DATA environment variable, if set
  2. a `userdata` folder next to the program, if writable. The normal case,
     because it is easy to find, back up and delete there
  3. AppData, as a fallback. That applies for example to a future executable
     placed under Program Files, where writing is not allowed

Layout

  userdata/templates/<name>.png     objects, pyramid, banner parts
  userdata/digits/<digit>/NN.png    digit images, several per digit
  userdata/unbekannt/*.png          open cases collected during runs
"""

import os

APP_NAME = "digibot"
HERE = os.path.dirname(os.path.abspath(__file__))

_CACHED = None


def _writable(path):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".schreibtest")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def data_dir():
    """Folder for learned data, created when it is first needed."""
    global _CACHED
    if _CACHED:
        return _CACHED

    env = os.environ.get("DGUP_DATA")
    if env and _writable(env):
        _CACHED = env
        return _CACHED

    local = os.path.join(HERE, "userdata")
    if _writable(local):
        _CACHED = local
        return _CACHED

    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    fallback = os.path.join(base, APP_NAME)
    if _writable(fallback):
        _CACHED = fallback
        return _CACHED

    raise RuntimeError("no writable folder found for learned data")


def sub(*parts, create=True):
    path = os.path.join(data_dir(), *parts)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def templates_dir(create=True):
    return sub("templates", create=create)


def digits_dir(create=True):
    return sub("digits", create=create)


def unknown_dir(create=True):
    return sub("unknown", create=create)


def template_path(name, create=True):
    return os.path.join(templates_dir(create=create), name + ".png")


def digit_dir(digit, create=True):
    return sub("digits", str(digit), create=create)


def next_index(folder, suffix=".png"):
    """Next free number in a folder, so learning samples do not overwrite
    each other."""
    try:
        files = [f for f in os.listdir(folder) if f.endswith(suffix)]
    except FileNotFoundError:
        return 0
    return len(files)


ONLY_FLAG = "nur_gelernt.flag"


def only_learned():
    """Should the images that ship with the program be ignored?

    A file in the data folder rather than an environment variable, so that
    the switch applies to the wizard and the bot at the same time. They run
    as separate processes.
    """
    if os.environ.get("DGUP_ONLY_LEARNED") == "1":
        return True
    try:
        return os.path.exists(os.path.join(data_dir(), ONLY_FLAG))
    except Exception:
        return False


def set_only_learned(value):
    path = os.path.join(data_dir(), ONLY_FLAG)
    if value:
        with open(path, "w") as fh:
            fh.write("The images shipped with the program are ignored.\n")
    elif os.path.exists(path):
        os.remove(path)
    return only_learned()


# The mouse-movement pause, on or off for the whole program.
#
# A flag file for the same reason as ONLY_FLAG above: the launcher, the wizard
# and a bot started from a console are three processes, and a switch that only
# reached one of them would be a switch that appears to do nothing. Reading
# the file rather than remembering it is what makes the toggle in one window
# take effect in another, and in a bot that is already running.
#
# The file means "off", so that the absence of it -- a fresh install, a
# deleted data folder -- is the safe answer: the pause is on unless somebody
# has said otherwise.
MOUSE_PAUSE_FLAG = "mouse_pause_off.flag"


def mouse_pause():
    """Should a bot pause when the real mouse moves?"""
    if os.environ.get("DGUP_MOUSE_PAUSE") in ("0", "1"):
        return os.environ["DGUP_MOUSE_PAUSE"] == "1"
    try:
        return not os.path.exists(os.path.join(data_dir(), MOUSE_PAUSE_FLAG))
    except Exception:
        # No writable folder is not a reason to let a bot drive over
        # somebody's hand. On is the safe answer.
        return True


def set_mouse_pause(value):
    path = os.path.join(data_dir(), MOUSE_PAUSE_FLAG)
    if value and os.path.exists(path):
        os.remove(path)
    elif not value:
        with open(path, "w") as fh:
            fh.write("Bots do not pause when the mouse moves.\n")
    return mouse_pause()


def describe():
    """Short line for showing where the data lives."""
    where = data_dir()
    kind = ("DGUP_DATA environment variable" if os.environ.get("DGUP_DATA")
            else "project folder" if where.startswith(HERE) else "AppData")
    return "%s (%s)" % (where, kind)
