r"""
Create a desktop shortcut so the launcher opens with a double click.

  py make_shortcut.py            shortcut on the desktop plus a starter
  py make_shortcut.py --here     only the starter in the project folder

Normally run by install.bat, not by hand.

It uses pythonw.exe rather than python.exe. The difference is that pythonw opens
no black console window. Output goes to the window log anyway.

The interpreter it points at is whichever one is running this script, so when
install.bat calls it through .venv\Scripts\python.exe the shortcut lands on
the venv. That is the whole mechanism by which a virtual environment needs no
activating: the full path is in the shortcut.

The shortcut is created via PowerShell, which ships with every Windows, so no
extra package such as pywin32 is required.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BAT_NAME = "Start Helpermon.bat"
# The starter used to be called "Bot starten.bat". Cleaned up when found, so a
# folder that has been through both versions does not end up with two of them.
OLD_BAT_NAMES = ["Start bot.bat", "Bot starten.bat"]


def pythonw():
    """Path to pythonw.exe next to the running interpreter."""
    exe = sys.executable
    guess = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return guess if os.path.exists(guess) else exe


def write_bat():
    """Starter in the project folder. It always works, even when creating the
    shortcut fails."""
    for old in OLD_BAT_NAMES:
        path = os.path.join(HERE, old)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    path = os.path.join(HERE, BAT_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("@echo off\r\n")
        fh.write('cd /d "%~dp0"\r\n')
        fh.write('start "" "%s" app.py\r\n' % pythonw())
    return path


def known_desktop():
    """The desktop as Windows itself reports it.

    SHGetKnownFolderPath answers the question rather than guessing at it, and
    it is right in both layouts: with OneDrive's folder backup switched on it
    returns the OneDrive path, without it the local one. It also removes the
    need to know what the folder is called in another language -- on a German
    Windows the folder on disk is still `Desktop`, only its displayed name is
    translated, and this returns the real path either way.
    """
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    # FOLDERID_Desktop, {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
    folder = GUID(0xB4BFCC3A, 0xDB2C, 0x424C,
                  (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9,
                                       0x9A, 0x87, 0xC6, 0x41))
    out = ctypes.c_wchar_p()
    try:
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folder), 0, None, ctypes.byref(out))
        if hr != 0:
            return None
        try:
            return out.value
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception:
        return None


def desktop():
    """Where the shortcut goes.

    Ask first, guess second. The guess used to be the whole of it, and it
    tried OneDrive before the user profile -- right on a machine where
    OneDrive has taken the desktop over, wrong on one where an empty
    `OneDrive\\Desktop` is merely left lying about. On such a machine the
    shortcut landed in a folder the player never looks at, while install.bat
    reported it created.
    """
    path = known_desktop()
    if path and os.path.isdir(path):
        return path

    # Only if the system did not answer. Then there is nothing left but to
    # guess, and the old order is as good a guess as any.
    for var in ("OneDrive", "USERPROFILE"):
        base = os.environ.get(var)
        if not base:
            continue
        for name in ("Desktop", "Schreibtisch"):
            candidate = os.path.join(base, name)
            if os.path.isdir(candidate):
                return candidate
    return None


def make_shortcut(target, args, workdir, link_path):
    """Create the shortcut through PowerShell's COM interface."""
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath = '%s';"
        "$s.Arguments = '%s';"
        "$s.WorkingDirectory = '%s';"
        "$s.Description = 'Helpermon, the launcher';"
        "$s.Save()"
    ) % (link_path, target, args, workdir)
    res = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or "PowerShell error").strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--here", action="store_true",
                    help="only create the starter in the project folder")
    ap.add_argument("--name", default="Helpermon")
    args = ap.parse_args()

    bat = write_bat()
    print("Starter created: %s" % bat)
    print("It can be double-clicked directly.")

    if args.here:
        return
    if os.name != "nt":
        print("Shortcuts are Windows only, the starter above is enough here.")
        return

    target_dir = desktop()
    if not target_dir:
        print("Desktop not found. Drag the starter above there yourself.")
        return

    link = os.path.join(target_dir, args.name + ".lnk")
    try:
        make_shortcut(pythonw(), "app.py", HERE, link)
    except Exception as err:
        print("Shortcut failed (%s)." % err)
        print("Alternative: right-click the starter, Send to, Desktop.")
        return
    print("Shortcut created: %s" % link)
    print("It starts %s with app.py in the folder %s" % (pythonw(), HERE))
    print("\nNote: you can give it your own icon via right-click, "
          "Properties, Change Icon.")


if __name__ == "__main__":
    main()
