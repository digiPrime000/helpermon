"""
Start LDPlayer and open the game.

LDPlayer ships `ldconsole.exe` for this, in the same folder as the ADB we
already look for. That covers the cold start.

  list instances     list2
  is it running      isrunning --index N
  start              launch --index N
  start the app      launchex --index N --packagename P
  quit               quit --index N

Deliberately not included: navigating the menus from the title screen into the
minigame. Those are daily rewards, event banners and shifting buttons, the most
fragile part and the one that changes with every game update. Instead the bot
waits until the board is recognisable and then takes over.

  py ldplayer.py                    show instances
  py ldplayer.py --start            start the emulator and wait
  py ldplayer.py --start --app      also open the game
  py ldplayer.py --quit
"""

import argparse
import glob
import os
import subprocess
import time

# Fallback locations for ldconsole.exe, same idea as the ADB search in
# capture.py. Only a fallback: capture.ld_installs finds the newest install
# by version, which these fixed paths cannot express.
CONSOLE_CANDIDATES = [
    r"C:\LDPlayer\LDPlayer9\ldconsole.exe",
    r"C:\LDPlayer\LDPlayer64\ldconsole.exe",
    r"C:\Program Files\LDPlayer\LDPlayer9\ldconsole.exe",
    r"C:\Program Files (x86)\LDPlayer\LDPlayer9\ldconsole.exe",
    r"D:\LDPlayer\LDPlayer9\ldconsole.exe",
]

# How the game package is recognised when no package name was given
PACKAGE_HINTS = ("digimon", "bandai", "bnei", "namco")


class LdError(RuntimeError):
    pass


def find_console():
    """Order: environment variable, newest install, next to the found ADB,
    fixed fallback locations.

    The newest install comes first on purpose. A machine that has had two
    versions installed keeps both folders, and driving the old one is how
    "Start LDPlayer" ended up launching version 9 on a machine using 14.
    """
    env = os.environ.get("DGUP_LDCONSOLE")
    if env and os.path.exists(env):
        return env

    try:
        import capture
        installs = capture.ld_installs("ldconsole.exe")
        if installs:
            return installs[0]
        # ADB sits in the same folder, so look there too
        adb = capture.find_adb()
        if adb and adb != "adb":
            guess = os.path.join(os.path.dirname(adb), "ldconsole.exe")
            if os.path.exists(guess):
                return guess
    except Exception:
        pass

    for path in CONSOLE_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


class LdPlayer:
    def __init__(self, console=None, log=print):
        self.console = console or find_console()
        self.log = log
        if not self.console:
            raise LdError(
                "ldconsole.exe nicht gefunden. Pfad setzen mit\n"
                '  $env:DGUP_LDCONSOLE = "C:\\LDPlayer\\LDPlayer9\\ldconsole.exe"')

    # ------------------------------------------------------------------
    def _run(self, *args, timeout=60):
        res = subprocess.run([self.console] + list(args), capture_output=True,
                             timeout=timeout)
        # ldconsole liefert je nach Version cp1252 oder utf-8, deshalb tolerant
        out = (res.stdout or b"").decode("utf-8", errors="replace")
        return out.strip()

    def instances(self):
        """Liste der Instanzen. list2 gibt Komma getrennte Felder, das erste ist
        der Index, das zweite der Name, das fuenfte der Laufstatus."""
        out = self._run("list2")
        rows = []
        for line in out.splitlines():
            parts = line.split(",")
            if len(parts) < 2 or not parts[0].strip().isdigit():
                continue
            running = None
            if len(parts) >= 5:
                running = parts[4].strip() not in ("0", "")
            rows.append({"index": int(parts[0]), "name": parts[1],
                         "running": running})
        return rows

    def is_running(self, index=0):
        out = self._run("isrunning", "--index", str(index)).lower()
        if "running" in out and "not" not in out:
            return True
        if "stop" in out or "not" in out:
            return False
        # manche Versionen antworten nur ueber list2
        for inst in self.instances():
            if inst["index"] == index and inst["running"] is not None:
                return inst["running"]
        return False

    def launch(self, index=0):
        self._run("launch", "--index", str(index), timeout=120)

    def quit(self, index=0):
        self._run("quit", "--index", str(index), timeout=120)

    def launch_app(self, index=0, package=None):
        package = package or self.find_package(index)
        if not package:
            raise LdError("game package not found. Provide it with --package.")
        self._run("launchex", "--index", str(index), "--packagename", package,
                  timeout=120)
        return package

    # ------------------------------------------------------------------
    def find_package(self, index=0):
        """The game's package name. Needs ADB.

        There is no way to find it without ADB. Then it has to be given
        through DGUP_PACKAGE, or the game started by hand.
        """
        env = os.environ.get("DGUP_PACKAGE")
        if env:
            return env
        import capture
        cap = capture.AdbCapture()
        for serial in cap.devices():
            cap.serial = serial
            out = subprocess.run(
                cap._cmd("shell", "pm", "list", "packages"),
                capture_output=True, timeout=30).stdout.decode(
                    "utf-8", errors="replace")
            names = [line.split(":", 1)[1].strip()
                     for line in out.splitlines() if ":" in line]
            for hint in PACKAGE_HINTS:
                for name in names:
                    if hint in name.lower():
                        return name
        return None

    # ------------------------------------------------------------------
    def wait_ready(self, index=0, timeout=180, poll=2.0, window_ok=True):
        """Wartet, bis Android hochgefahren ist und ADB ein Bild liefert.

        Zwei Bedingungen, weil die eine ohne die andere nichts wert ist. Ein
        Geraet kann in der Liste stehen und trotzdem kein Bild liefern, das
        hatten wir bei einer alten TCP Verbindung schon.
        """
        import capture
        deadline = time.time() + timeout
        cap = capture.AdbCapture()
        has_adb = bool(cap.devices()) if window_ok else True
        if not has_adb:
            # Without ADB, it waits for the window instead. That is coarser,
            # but it is enough, since only a usable frame is needed anyway.
            self.log("no ADB, waiting for a usable window frame")
            started = time.time()
            said = 0.0
            while time.time() < deadline:
                try:
                    win = capture.open_window()
                    if win.grab() is not None:
                        self.log("window is there after %d s"
                                 % (time.time() - started))
                        return "window"
                except Exception:
                    pass
                waited = time.time() - started
                # Silence for three minutes looks like a hang. Say something
                # every ten seconds, with the number that matters.
                if waited - said >= 10:
                    said = waited
                    self.log("still waiting for the emulator window, %d s of "
                             "%d" % (waited, timeout))
                time.sleep(poll)
            raise LdError("no emulator window after %d s. Is the emulator "
                          "actually starting?" % timeout)
        while time.time() < deadline:
            for serial in cap.devices():
                cap.serial = serial
                booted = subprocess.run(
                    cap._cmd("shell", "getprop", "sys.boot_completed"),
                    capture_output=True, timeout=20).stdout.decode(
                        "utf-8", errors="replace").strip()
                if booted.startswith("1") and cap.works():
                    self.log("emulator ready, device %s" % serial)
                    return serial
            self.log("waiting for the emulator")
            time.sleep(poll)
        raise LdError("emulator not ready within %d s" % timeout)

    def ensure_running(self, index=0, package=None, start_app=True,
                       timeout=180):
        """Kaltstart. Startet den Emulator falls noetig, wartet, oeffnet das
        Spiel. Rueckgabe ist die ADB Kennung der Instanz."""
        if not self.is_running(index):
            self.log("starting LDPlayer instance %d" % index)
            self.launch(index)
        else:
            self.log("LDPlayer instance %d is already running" % index)
        serial = self.wait_ready(index, timeout=timeout)
        # Whether the game itself came up is a separate question from whether
        # the emulator did, and the caller has to be able to tell: without
        # ADB this fails quietly and leaves the emulator on its home screen,
        # where a bot must not start tapping.
        self.app_started = False
        if start_app:
            try:
                pkg = self.launch_app(index, package)
                self.log("game started, %s" % pkg)
                self.app_started = True
            except LdError as err:
                self.log("game not started: %s" % err)
        return serial


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--app", action="store_true", help="dazu das Spiel oeffnen")
    ap.add_argument("--quit", action="store_true")
    ap.add_argument("--package")
    args = ap.parse_args()

    ld = LdPlayer()
    print("ldconsole: %s" % ld.console)
    for inst in ld.instances():
        print("  Instanz %d  %-24s laeuft %s"
              % (inst["index"], inst["name"], inst["running"]))

    if args.quit:
        ld.quit(args.index)
        print("instance %d stopped" % args.index)
        return
    if args.start:
        serial = ld.ensure_running(args.index, package=args.package,
                                   start_app=args.app)
        print("ready, device %s" % serial)
        print('Fuer den Bot festnageln mit\n  $env:DGUP_SERIAL = "%s"' % serial)


if __name__ == "__main__":
    main()
