"""
Helpermon, the launcher for all three bots. One entry point for new users.

  py app.py

Layout, and why it is this one:

  +---------------------------------------------------------------+
  |  emulator state            [Start LDPlayer]  [Check again]    |   header
  +-----------+---------------------------------------------------+
  | Start here|                                                   |
  |           |                                                   |
  | Dungeons  |   the selected section                            |   sidebar
  | Minigame  |                                                   |   + content
  | Skewer    |                                                   |
  |           |                                                   |
  | Setup     |                                                   |
  | About     |                                                   |
  +-----------+---------------------------------------------------+
  |  status                                                       |
  +---------------------------------------------------------------+

One navigation, not two. The previous version had tabs across the top AND a
card per bot in the middle, which is the same list of destinations offered
twice -- and neither of them said what to do first.

Anything that is not about one particular bot lives in the header, where it is
reachable from every page. Starting the emulator was buried in the minigame
window before, although all three bots need it.

The sidebar is ordered the way a new user should meet things: Start here, then
the bots with the one that needs no setup first, then setup and legal.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox

import guard
import widgets

HERE = os.path.dirname(os.path.abspath(__file__))
_APPDATA = os.environ.get("APPDATA") or os.path.expanduser("~")
STATE_FILE = os.path.join(_APPDATA, "helpermon.json")
# What the file was called before the program was named. Read once if the new
# one is not there yet, so renaming the program does not silently throw away
# everyone's settings.
OLD_STATE_FILE = os.path.join(_APPDATA, "digibot_app.json")

# One entry per bot, in the order a new user should meet them: the one that
# needs no setup first, so there is something to run before anything is
# learned. `step` names the wizard step that makes this bot runnable.
# `name` is what the game calls it, `short` is what fits in the sidebar.
BOTS = [
    {"key": "dungeon", "name": "Dungeons", "short": "Dungeons",
     # It needs no images to play. The game icon is for Instant AFK only,
     # which is why this bot stays "ready" without it.
     "colour": "#3b6fd4", "step": "Game icon",
     "why": ("Spends your daily dungeon attempts and watches the ads for the "
             "extra tickets, so a day's rewards are collected without you "
             "sitting through them. Nothing has to be taught first, so this "
             "is the one to try first."),
     "what": "Works through the dungeon list and uses ad tickets",
     "long": ("Recognises buttons by colour and position, so it needs no "
              "images from the game and works in every language.")},
    {"key": "mini", "name": "Digital World Search", "short": "World Search",
     "colour": "#7a4fd4", "step": "Counters",
     "why": ("Walks the board collecting tickets, paws, claws and fireballs "
             "and keeps going as long as the paws last, so the currency "
             "piles up on its own."),
     "what": "Collects power-ups and runs to the right",
     "long": ("Has to tell tickets, claws, pyramids and your own character "
              "apart, so it needs images cropped from your own screen.")},
    {"key": "skewer", "name": "Midsummer Digimon Night Market",
     "short": "Night Market", "colour": "#d4703b", "step": "Skewer",
     "why": ("Grinds the items out of the seasonal missions. It plays round "
             "after round for the mission rewards, not for a high score, so "
             "the event currency piles up without you cooking for it."),
     "what": "Reads the order at the counter and builds that skewer",
     "long": ("Reads the order above the counter and builds the same skewer "
              "from the twelve-icon grid. Needs those twelve icons.")},
]

DEFAULT_NOTES = {
    "dungeon": ("Opened here because Instant AFK needs the game's icon: it "
                "is what lets Helpermon find and open the game on the "
                "emulator's home screen. The dungeon bot itself needs "
                "nothing from this wizard."),
    "mini": ("Opened here because the Digital World Search bot still needs "
             "its images. Work through this step and the three after it."),
    "skewer": ("Opened here because the Night Market bot needs its twelve "
               "ingredient icons. Open the Midsummer Digimon Night Market in "
               "the game, then press 'Grab a new frame'."),
}

# What has to be true before a bot can do anything.
#
# Kept in one place and shown in two: on the bot's own page, where it cannot
# be missed, and in a dialog the first time that bot is started. A
# requirement that lives only in a README is a requirement nobody meets, and
# every one of these is something that makes the bot do nothing at all if it
# is not so -- the Night Market bot pressing Play Game on a screen that has
# no Play Game, the World Search waiting for a board nobody opened.
REQUIREMENTS = {
    "dungeon": [
        "Digimon UP has to be open. Anywhere in the game will do, the bot "
        "finds its own way to the dungeon list.",
        "Nothing has to be taught first. This is the bot to try first.",
        "Instant AFK can open the emulator and the game for you instead. "
        "That needs ADB, or the game icon taught once.",
    ],
    "mini": [
        "Digimon UP has to be open.",
        "Open the Digital World Search yourself and stay on the board. This "
        "bot works no menus: it waits until it can see the board and takes "
        "over from there.",
        "Its setup has to be done: the counters, the objects, the pyramid "
        "and the banners, all cut from your own screen.",
        "The character skin matters, and it is the easiest thing to get "
        "wrong. This bot was built and measured with the Botamon skin. "
        "Another may work, but it can also make the bot miss the figure "
        "and steer by something else instead, without saying so.",
    ],
    "skewer": [
        "Digimon UP has to be open.",
        "Open the Midsummer Digimon Night Market and stop at its own main "
        "menu, the screen with the Play Game lantern. The bot presses Play "
        "Game itself and would tap into whatever else is there.",
        "Its setup has to be done: the twelve ingredient icons.",
    ],
}

# True for every bot, so it is said once rather than three times.
INPUT_REQUIREMENT = [
    "With ADB, taps go to the emulator directly and your mouse stays yours.",
    "Without ADB the bot uses your real mouse. Leave it alone while the bot "
    "runs, or switch on 'Pause Bot on mouse move' at the top right.",
    "Without ADB the emulator window also has to stay visible, in front and "
    "uncovered, and the screen must not go to sleep. Screen capture returns "
    "the last picture that was drawn, and a bot reading that clicks at what "
    "was there minutes ago.",
]

ADB_TITLE = "First: how Helpermon reaches the emulator"

ADB_NOTICE = (
    "There are two ways, and the first one is better.\n\n"
    "1. Through ADB. Helpermon sends its taps straight to the emulator. Your\n"
    "   mouse stays yours, and the emulator window may sit behind other\n"
    "   windows while a bot works.\n\n"
    "   You have to switch it on first: in LDPlayer, Settings, Other\n"
    "   settings, ADB debugging. Then press 'Check ADB now' below - that\n"
    "   asks the emulator rather than guessing.\n\n"
    "   One thing to know: LDPlayer itself puts up an error when a lot is\n"
    "   driven through ADB in one sitting. That is the emulator complaining,\n"
    "   not the game. Restart the emulator, or put that bot on mouse input\n"
    "   for the rest of the session.\n\n"
    "2. Through your mouse. If ADB is off or unavailable, the bot moves the\n"
    "   real cursor. Then do not touch the mouse while a bot runs, or switch\n"
    "   on 'Pause Bot on mouse move' at the top right and it will stop as\n"
    "   soon as you do. The emulator window has to stay visible and in\n"
    "   front, and the screen must not go to sleep."
)

# The mouse-input switch reads the same on all three bot pages. It said
# "Without ADB, mouse input", which named the setting without saying what it
# costs: that the mouse belongs to the bot for as long as it runs.
NO_ADB_LABEL = "Without ADB, using mouse input instead"
NO_ADB_NOTE = ("    The bot takes over your mouse while it runs, so you "
               "cannot use\n    the computer meanwhile. With ADB it clicks "
               "inside the emulator\n    and your mouse stays yours.")

HOTKEY_HINT = ("Without ADB a bot takes over the mouse; with ADB it does not."
               "\nF7 pauses and resumes, F8 stops - both work with any window "
               "in front.")

FAN_TITLE = "An unofficial fan project"

# First, before anything else that is read. Somebody meeting this program for
# the first time should not have to work out from the tone whether it comes
# from the people who made the game.
FAN_NOTICE = (
    "Helpermon is a fan project. It is not made, endorsed, sponsored or\n"
    "supported by Bandai Namco, Bandai, Toei Animation, or anyone else\n"
    "involved in Digimon UP.\n\n"
    "Digimon and every name, character and image belonging to the game are\n"
    "the property of their owners. Nothing from the game is shipped with this\n"
    "program; what the bots need, they learn from your own screen."
)

INTENT_TITLE = "Why this exists"

INTENT = (
    "Helpermon was written by someone who likes Digimon UP and wants to keep\n"
    "playing it. Its purpose is to make the game more enjoyable, not to take\n"
    "anything out of it: it carries the parts that are repetitive by design -\n"
    "spending a day's dungeon attempts, walking the search board, serving the\n"
    "night market - so that the time spent in the game goes to the parts that\n"
    "are worth playing.\n\n"
    "It reads the screen and moves the mouse, the same two things a player\n"
    "does. It does not modify the game, its files or its network traffic, and\n"
    "it obtains nothing that ordinary play does not. No harm to Bandai Namco\n"
    "is intended, and anyone finding it harmful is asked to say so."
)

LEGAL_NOTICE = (
    "Helpermon automates Digimon UP, running in the LDPlayer emulator.\n\n"
    "The publisher's terms of service explicitly prohibit the use of bots,\n"
    "emulators and similar tools in section 11 g. Anyone using it risks having\n"
    "their game account suspended.\n\n"
    "This software is provided without warranty. The decision to use it, and\n"
    "the consequences of doing so, are yours."
)

# Not offered in this build. The daily dungeon changes what it is from day
# to day, and nothing has been measured against enough of its faces to let a
# bot loose on it. It keeps its place in the list the bot counts against.
HIDDEN_DUNGEONS = {"Daily changing dungeon"}

BG = "#f4f5f7"
NAV_BG = "#e8eaed"
NAV_ACTIVE = "#ffffff"


class _StopHolder:
    """The minigame bot is a loop, not an object, so there is nothing to hold
    its Stop. Pause and Stop reach every bot through `.control`, and this
    gives the loop the same shape as the other two."""

    def __init__(self):
        self.control = guard.Stop()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Helpermon")
        # Big enough that the longest page -- Dungeons, controls and log --
        # is there on the first look. A window that opened with the log
        # below the edge meant nobody saw the log until they scrolled, and
        # the log is where the bot says what it is doing. Clamped to what
        # the screen actually has, so a short laptop display does not get a
        # window taller than its desktop.
        self.geometry("%dx%d" % (min(980, self.winfo_screenwidth() - 40),
                                 min(950, self.winfo_screenheight() - 90)))
        self.minsize(880, 560)
        self.state_data = self._load()
        self.events = queue.Queue()
        self.worker = None
        self.stop = None
        self.vars = {}
        # One entry per bot that runs in this window: its start buttons, its
        # pause and stop buttons, and its own log. Only one bot runs at a
        # time, and `active` names whose buttons the event pump talks to.
        self.panels = {}
        self.active = None
        self.emulator_ok = None  # None = not checked yet
        # Declared before the header is built: the header sets the emulator
        # state, which asks the start page to refresh, and tkinter turns a
        # missing attribute into a baffling error about the Tk object.
        self.pages = {}
        self.current_page = None

        self._build_header()
        self._build_body()
        self._build_statusbar()

        self._build_pages()
        self.show_page("home")

        self.bind_all("<MouseWheel>", self._on_wheel)

        self.after(80, self._pump)
        self.after(150, self._first_run_dialogs)
        self.after(400, self.check_emulator)

    # ==================================================================
    # Frame of the window: header, sidebar, content, status bar
    # ==================================================================
    def _build_header(self):
        head = tk.Frame(self, bg="#ffffff", padx=14, pady=10)
        head.pack(fill="x")
        tk.Frame(self, height=1, bg="#d0d3d8").pack(fill="x")

        left = tk.Frame(head, bg="#ffffff")
        left.pack(side="left")
        self.emu_dot = tk.Canvas(left, width=12, height=12, bg="#ffffff",
                                 highlightthickness=0)
        self.emu_dot.pack(side="left", padx=(0, 8))
        self.emu_label = tk.Label(left, text="Emulator: not checked yet",
                                  bg="#ffffff", font=("Segoe UI", 10))
        self.emu_label.pack(side="left")
        self._set_emulator(None, "Emulator: not checked yet")

        # The header reports, it does not act. Both emulator buttons live on
        # step 1 of Start here, which is the step about the emulator -- a row
        # of buttons repeated on every page competes with whatever that page
        # is actually for.
        #
        # One exception, top right: the mouse-movement pause. That one is not
        # about a page or a bot, it is about whether the machine is yours or
        # the bot's for the next minute, and it is wanted at the moment the
        # bot has just grabbed the mouse -- which is the worst possible moment
        # to go looking for it on some other page.
        widgets.MousePauseSwitch(head, bg="#ffffff").pack(side="right")

    def _build_body(self):
        body = tk.Frame(self)
        body.pack(fill="both", expand=True)

        self.nav = tk.Frame(body, bg=NAV_BG, width=170)
        self.nav.pack(side="left", fill="y")
        self.nav.pack_propagate(False)

        self.content = tk.Frame(body, bg=BG, padx=18, pady=16)
        self.content.pack(side="left", fill="both", expand=True)

        self.nav_buttons = {}
        self.nav_dots = {}
        self._nav_entry("home", "Start here")
        self._nav_heading("Bots")
        for bot in BOTS:
            self._nav_entry(bot["key"], bot["short"], dot=True)
        self._nav_heading("")
        # No Setup entry. Setting a bot up is part of that bot, and it is
        # reached from that bot's own page. One shared Setup page was how
        # people ended up in the wrong bot's steps.
        self._nav_entry("about", "About")

    def _nav_heading(self, text):
        tk.Label(self.nav, text=text.upper(), bg=NAV_BG, fg="#70757c",
                 font=("Segoe UI", 8, "bold"), anchor="w", padx=14
                 ).pack(fill="x", pady=(14, 2))

    def _nav_entry(self, key, label, dot=False):
        row = tk.Frame(self.nav, bg=NAV_BG)
        row.pack(fill="x")
        button = tk.Button(row, text=label, bg=NAV_BG, relief="flat", bd=0,
                           anchor="w", padx=14, pady=7, font=("Segoe UI", 10),
                           activebackground="#dcdfe3",
                           command=lambda k=key: self.show_page(k))
        button.pack(side="left", fill="x", expand=True)
        self.nav_buttons[key] = button
        if dot:
            canvas = tk.Canvas(row, width=14, height=14, bg=NAV_BG,
                               highlightthickness=0)
            canvas.pack(side="right", padx=(0, 10))
            self.nav_dots[key] = canvas

    def _build_statusbar(self):
        tk.Frame(self, height=1, bg="#d0d3d8").pack(fill="x")
        self.status = tk.Label(self, text="ready", anchor="w", fg="#555",
                               padx=14, pady=4, justify="left")
        self.status.pack(fill="x")
        # Wrap to whatever width the window currently is, so a long message
        # neither runs off the edge nor makes the window grow.
        self.status.bind(
            "<Configure>",
            lambda e: self.status.configure(wraplength=max(200, e.width - 28)))

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------
    def _scrollable(self, parent):
        """A page taller than the window has to stay reachable.

        On a short window the dungeon page ran off the bottom edge and its
        log could not be seen at all. Every page is built inside one of
        these: while the content fits it behaves exactly like the plain
        frame it replaced, and it grows a scrollbar the moment it does not.
        """
        host = tk.Frame(parent, bg=BG)
        host.rowconfigure(0, weight=1)
        host.columnconfigure(0, weight=1)
        canvas = tk.Canvas(host, bg=BG, highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        bar = tk.Scrollbar(host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.grid(row=0, column=1, sticky="ns")
        inner = tk.Frame(canvas, bg=BG)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        shown = {"bar": True}

        def fit(_event=None):
            view = canvas.winfo_height()
            needed = inner.winfo_reqheight()
            height = max(needed, view)
            # While it fits, the inner frame is stretched to the full height
            # of the view, so whatever is packed with expand=True -- the log
            # -- still fills the page as it did before there was a canvas in
            # the way.
            canvas.itemconfigure(window, width=canvas.winfo_width(),
                                 height=height)
            canvas.configure(scrollregion=(0, 0, 0, height))
            wanted = needed > view
            if wanted != shown["bar"]:
                shown["bar"] = wanted
                if wanted:
                    bar.grid()
                else:
                    canvas.yview_moveto(0)
                    bar.grid_remove()

        inner.bind("<Configure>", fit)
        canvas.bind("<Configure>", fit)
        inner.scroll_host = host
        inner.scroll_canvas = canvas
        inner.scroll_fit = fit
        return inner

    @staticmethod
    def _host(frame):
        """The widget a page is packed by: its scroll host if it has one."""
        return getattr(frame, "scroll_host", frame)

    def _on_wheel(self, event):
        """Scroll the page under the pointer -- unless that is something
        which scrolls itself. A bot's log is a Text with its own wheel
        binding, and without this check one turn of the wheel moved both."""
        widget = event.widget
        while widget is not None:
            if isinstance(widget, (tk.Text, tk.Listbox)):
                return
            widget = getattr(widget, "master", None)
        page = self.pages.get(self.current_page)
        canvas = getattr(page["frame"], "scroll_canvas", None) if page else None
        if canvas is not None:
            canvas.yview_scroll(int(-event.delta / 120), "units")

    # ------------------------------------------------------------------
    def show_page(self, key):
        for name, page in self.pages.items():
            self._host(page["frame"]).pack_forget()
            self.nav_buttons[name].configure(
                bg=NAV_BG, font=("Segoe UI", 10))
        page = self.pages[key]
        self._host(page["frame"]).pack(fill="both", expand=True)
        self.nav_buttons[key].configure(bg=NAV_ACTIVE,
                                        font=("Segoe UI", 10, "bold"))
        self.current_page = key
        # Setup happens in another window, so anything showing state has to
        # re-read it on the way in rather than trust what it found at launch.
        if page.get("refresh"):
            page["refresh"]()
        self._refresh_nav_dots()

    def _refresh_nav_dots(self):
        states = self.bot_states()
        for key, canvas in self.nav_dots.items():
            canvas.delete("all")
            ready = states.get(key, {}).get("ready", False)
            canvas.create_oval(4, 4, 11, 11,
                               fill="#1a7f37" if ready else "#c98a00",
                               outline="")

    # ==================================================================
    # State everything else reads
    # ==================================================================
    def bot_states(self):
        """Per bot: is it runnable, and one line saying why or why not."""
        out = {b["key"]: {"ready": True, "detail": ""} for b in BOTS}
        # The dungeon bot plays without a single learned image, so it stays
        # ready either way. The icon only decides whether Instant AFK can
        # open the game itself.
        try:
            import launcher
            out["dungeon"]["icon"] = bool(launcher.have_icon())
        except Exception:
            out["dungeon"]["icon"] = False
        out["dungeon"]["detail"] = (
            "Needs no setup. The game icon is learned, so Instant AFK can "
            "start from cold."
            if out["dungeon"]["icon"] else
            "Needs no setup to play. Instant AFK needs the game icon.")
        try:
            import learning
            st = learning.status()
        except Exception as err:
            for key in ("mini", "skewer"):
                out[key].update(ready=False,
                                detail="Cannot read state: %s" % err)
            out["test_mode"] = False
            return out

        missing, digits = len(st["missing"]), len(st["ziffern_fehlen"])
        out["mini"]["ready"] = st["fertig"]
        out["mini"]["detail"] = (
            "Ready" if st["fertig"]
            else "%d image%s and %d digit%s missing"
                 % (missing, "" if missing == 1 else "s",
                    digits, "" if digits == 1 else "s"))
        out["skewer"]["ready"] = st["skewer_ready"]
        out["skewer"]["detail"] = ("%d of %d ingredient icons learned"
                                   % (len(st["skewer_have"]),
                                      st["skewer_total"]))
        out["test_mode"] = learning.only_learned()
        out["folder"] = st["ort"]
        return out

    # ==================================================================
    # Emulator, the one thing every bot depends on
    # ==================================================================
    def _set_emulator(self, ok, text):
        """ok True = ready, "idle" = emulator up but the game is not,
        False = nothing found, None = not looked yet."""
        self.emulator_ok = ok
        colour = {True: "#1a7f37", "idle": "#c98a00",
                  False: "#b3261e", None: "#9aa0a6"}[ok]
        self.emu_dot.delete("all")
        self.emu_dot.create_oval(1, 1, 11, 11, fill=colour, outline="")
        self.emu_label.configure(text=text)
        home = self.pages.get("home")
        if home and home.get("refresh"):
            home["refresh"]()

    def check_emulator(self):
        self.status.configure(text="looking for the emulator window")

        def job():
            # The header says what, the status bar says why. The capture
            # error is a paragraph long and ran off both the header and the
            # window when it was put in either.
            try:
                import capture
                img = capture.open_window().grab()
            except Exception as err:
                self.events.put(("emu_bad", "Emulator: not found"))
                self.events.put(("status", str(err)))
                return
            size = "%d x %d" % (img.shape[1], img.shape[0])
            # Emulator up and game not open are different problems. The
            # learned icon settles it: if it is on screen, we are looking at
            # the emulator's home screen.
            try:
                import launcher
                found = launcher.find_icon(img) if launcher.have_icon() else None
            except Exception:
                found = None
            if found and found["ok"]:
                self.events.put(("emu_idle",
                                 "Emulator: running, game not open"))
                self.events.put(("status", "Emulator %s, showing its home "
                                 "screen. The game icon is visible at %d,%d."
                                 % (size, found["x"], found["y"])))
            else:
                self.events.put(("emu_ok", "Emulator: found, %s" % size))

        threading.Thread(target=job, daemon=True).start()

    def start_emulator(self):
        """Cold start, the same one engine.cold_start does for the minigame,
        but reachable from anywhere instead of only from that bot."""
        self.status.configure(text="starting LDPlayer, this takes a while")

        def job():
            try:
                import ldplayer
                ld = ldplayer.LdPlayer(
                    log=lambda t: self.events.put(("status", t)))
                serial = ld.ensure_running(0)
                os.environ["DGUP_SERIAL"] = serial
                self.events.put(("status", "emulator up, device %s" % serial))
            except Exception as err:
                self.events.put(("emu_bad", "Emulator: start failed (%s)"
                                 % str(err)[:60]))
                return
            self.events.put(("recheck", ""))

        threading.Thread(target=job, daemon=True).start()

    # ==================================================================
    # Pages
    # ==================================================================
    def _build_pages(self):
        self.pages["home"] = self._page_home()
        self.pages["dungeon"] = self._page_dungeon()
        self.pages["mini"] = self._page_mini()
        self.pages["skewer"] = self._page_skewer()
        self.pages["about"] = self._page_about()

    def _page_frame(self, title, subtitle="", detail=""):
        """Heading, then what this is for, then how it works.

        Two lines rather than one because they answer different questions: a
        player wants to know what a bot earns them, and only then what it
        needs to see in order to do it.
        """
        frame = self._scrollable(self.content)
        tk.Label(frame, text=title, bg=BG, font=("Segoe UI", 17, "bold")
                 ).pack(anchor="w")
        if subtitle:
            tk.Label(frame, text=subtitle, bg=BG, fg="#3c4043", justify="left",
                     wraplength=700, font=("Segoe UI", 10)
                     ).pack(anchor="w", pady=(4, 0))
        if detail:
            tk.Label(frame, text=detail, bg=BG, fg="#70757c", justify="left",
                     wraplength=700, font=("Segoe UI", 9)
                     ).pack(anchor="w", pady=(3, 0))
        return frame

    def _requirements(self, parent, key):
        """What has to be true before this bot can do anything.

        High on the page and in a colour nothing else on it uses, because
        every line in it is a way for the bot to sit there achieving
        nothing while looking like it is working. The same lines come up
        again in a dialog the first time this bot is started.
        """
        box = tk.Frame(parent, bg="#fff8e1", bd=1, relief="solid",
                       padx=14, pady=10)
        box.pack(anchor="w", fill="x", pady=(14, 0))
        tk.Label(box, text="Before you press Start", bg="#fff8e1",
                 fg="#7a4b00", anchor="w", font=("Segoe UI", 10, "bold")
                 ).pack(anchor="w")
        for line in REQUIREMENTS[key]:
            tk.Label(box, text="•  " + line, bg="#fff8e1", fg="#5a3a00",
                     anchor="w", justify="left", wraplength=680,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))

        # The way into setup, directly under the box that says what is still
        # missing and at the same right edge. It used to sit at the very
        # bottom of the page, under the log, which is the furthest point on
        # the page from the line that sends anybody there.
        #
        # Here rather than in each of the three pages: this method is called
        # by all of them and already knows which bot it is drawing for.
        row = tk.Frame(parent, bg=BG)
        row.pack(anchor="w", fill="x", pady=(6, 0))
        bot = self._bot_by_key(key)
        tk.Button(row, width=20,
                  text=("Teach the game icon" if key == "dungeon"
                        else "Set up this bot"),
                  command=lambda b=bot: self._setup_for(b)).pack(side="right")
        return box

    # --- Start here ---------------------------------------------------
    def _page_home(self):
        frame = self._page_frame(
            "Start here",
            # True whether or not the teaching has happened, because
            # this line is built once and the page is redrawn often.
            "The dungeon bot plays without any setup. The other two have "
            "to be taught what your screen looks like.")

        # Loud, and above everything else on the page. What follows it was
        # measured against one emulator and one language, and someone
        # running a different pair should learn that before their first run
        # rather than from a bot clicking at the wrong place. That is why it
        # stays above the quick start card as well, which is now the
        # shortest path there is to a first run.
        note = tk.Frame(frame, bg="#fff4e0", padx=14, pady=10,
                        highlightbackground="#e0a24a", highlightthickness=1)
        note.pack(anchor="w", fill="x", pady=(14, 0))
        tk.Label(note, text="What this has been tested with",
                 bg="#fff4e0", fg="#7a4a05", anchor="w",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(note, bg="#fff4e0", fg="#5a3a05", justify="left",
                 font=("Segoe UI", 10),
                 text=("LDPlayer 9 and LDPlayer 14, and Digimon UP in "
                       "English.\n\nAnother emulator may well not work: the "
                       "bots find the game window by name and\nsend their "
                       "clicks into it, and both of those differ from one "
                       "emulator to the next.\nThe game in another language "
                       "is the smaller risk, since the bots read colours\nand "
                       "positions rather than words - but it has not been "
                       "tried.")).pack(anchor="w", pady=(4, 0))

        body = tk.Frame(frame, bg=BG)
        body.pack(anchor="w", fill="x", pady=(16, 0))
        self.home_steps = body

        def refresh():
            for child in body.winfo_children():
                child.destroy()
            states = self.bot_states()

            emu_done = self.emulator_ok is True
            emu_detail = self.emu_label.cget("text").replace("Emulator: ", "")
            if self.emulator_ok == "idle":
                emu_detail += " - press Start LDPlayer, it opens the game too"

            waiting = [b for b in BOTS if not states[b["key"]]["ready"]]
            everything_ready = not waiting and not states.get("test_mode")

            # The quick start card is there only while something still needs
            # setting up. Its whole job is to tell a first-time user that
            # none of that has to happen before they see the program work;
            # somebody who has been through the wizard already knows and
            # does not need to read it on every visit.
            if not everything_ready:
                self._quick_start_card(body, emu_detail)
                self._or_divider(body)

            tk.Label(body, text="Set everything up", bg=BG, anchor="w",
                     font=("Segoe UI", 13, "bold")).pack(anchor="w")
            tk.Label(body, bg=BG, fg="#5f6368", anchor="w",
                     font=("Segoe UI", 9),
                     text="Three things, in this order. Each one only has to "
                          "be done once.").pack(anchor="w", pady=(2, 8))

            # Checking belongs on the step that is about the emulator, not
            # only in the header.
            self._step_row(
                body, 1, "Start the emulator and the game", emu_done,
                emu_detail,
                ("Check if running", self.check_emulator),
                None if emu_done else ("Start LDPlayer", self.start_emulator))

            if states.get("test_mode"):
                detail = ("Test mode is on, so shipped images count as "
                          "missing. Turn it off with  py setup_wizard.py , "
                          "on the Overview step.")
            elif waiting:
                detail = "%s still %s" % (
                    ", ".join(b["name"] for b in waiting),
                    "needs setup" if len(waiting) == 1 else "need setup")
            else:
                detail = "All three bots have what they need"
            # Straight to the bot that is missing something, not to a
            # shared setup page. Each bot's setup lives on its own page now.
            first = waiting[0] if waiting else None
            self._step_row(
                body, 2, "Teach it what your screen looks like",
                everything_ready, detail,
                ("Go to %s" % first["short"],
                 lambda k=first["key"]: self.show_page(k)) if first else None)

            if waiting and waiting[0]["key"] != "dungeon":
                hint = ("The dungeon bot needs no setup at all, so it is the "
                        "one to try first.")
                target = "dungeon"
            elif waiting:
                hint = "Pick a bot on the left when its setup is done."
                target = waiting[0]["key"]
            else:
                hint = "Everything is ready. Pick a bot on the left."
                target = "dungeon"
            self._step_row(body, 3, "Run a bot", not waiting, hint,
                           ("Go to %s" % self._bot_by_key(target)["name"],
                            lambda t=target: self.show_page(t)))

        return {"frame": frame, "refresh": refresh}

    def _quick_start_card(self, parent, emu_detail):
        """The offer to start now, with nothing set up.

        It reports the emulator but does not act on it. The card exists to
        answer "show me this working", and a button that starts an emulator
        first is a detour on the way to that: the Dungeons page says what it
        needs in its own box before anything is pressed, and step 1 below is
        where the emulator is dealt with. So the button here only ever goes
        to the bot.
        """
        bot = self._bot_by_key("dungeon")
        card = tk.Frame(parent, bg="#eef3fd", padx=16, pady=14,
                        highlightbackground=bot["colour"],
                        highlightthickness=2)
        card.pack(anchor="w", fill="x")

        tk.Label(card, text="Try it right now, with nothing set up",
                 bg="#eef3fd", fg="#1a3f8f", anchor="w",
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(card, bg="#eef3fd", fg="#28324a", anchor="w", justify="left",
                 wraplength=620, font=("Segoe UI", 10),
                 text=("The %s bot finds its buttons by colour and position. "
                       "It needs no images from the game, works in every "
                       "language, and there is nothing to teach it. The "
                       "emulator with the game open is all it wants."
                       % bot["name"])).pack(anchor="w", pady=(6, 0))
        tk.Label(card, bg="#eef3fd", fg="#4a5568", anchor="w", justify="left",
                 wraplength=620, font=("Segoe UI", 9),
                 text=("On its page, press Dry run first: it works out every "
                       "move and clicks nothing, so you can see what it would "
                       "do before it does it.")).pack(anchor="w", pady=(6, 0))

        row = tk.Frame(card, bg="#eef3fd")
        row.pack(anchor="w", fill="x", pady=(12, 0))
        tk.Label(row, text="Emulator: %s" % emu_detail, bg="#eef3fd",
                 fg="#28324a", anchor="w",
                 font=("Segoe UI", 9)).pack(side="left")
        # One button, and always the same one. It started out changing to
        # Start LDPlayer while the emulator was down, which put the same pair
        # of buttons on screen twice within a finger's width of step 1 and
        # made the short way round a two-stop journey.
        tk.Button(row, text="Go to %s" % bot["short"], width=16,
                  command=lambda: self.show_page("dungeon")
                  ).pack(side="right", padx=(6, 0))
        return card

    def _or_divider(self, parent):
        """A rule with OR in the middle of it.

        The two halves of this page are alternatives, not steps one and two
        of the same thing, and without the word they read as a sequence:
        the card first, and then set everything up anyway.
        """
        row = tk.Frame(parent, bg=BG)
        row.pack(anchor="w", fill="x", pady=(16, 14))
        tk.Frame(row, bg="#c8ccd1", height=1).pack(side="left", fill="x",
                                                   expand=True)
        tk.Label(row, text="OR", bg=BG, fg="#5f6368", padx=14,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Frame(row, bg="#c8ccd1", height=1).pack(side="left", fill="x",
                                                   expand=True)
        return row

    def _step_row(self, parent, number, title, done, detail, *actions):
        """One numbered step: where you are, and the buttons that move you
        on. The tick is the whole point -- a new user should be able to see
        how far they have got without reading anything."""
        row = tk.Frame(parent, bg="#ffffff", bd=1, relief="solid",
                       padx=14, pady=12)
        row.pack(anchor="w", fill="x", pady=5)

        mark = tk.Canvas(row, width=30, height=30, bg="#ffffff",
                         highlightthickness=0)
        mark.create_oval(2, 2, 28, 28,
                         fill="#1a7f37" if done else "#c8ccd1", outline="")
        if done:
            mark.create_line(9, 15, 13, 20, 21, 10, fill="white", width=3)
        else:
            mark.create_text(15, 15, text=str(number), fill="#3c4043",
                             font=("Segoe UI", 12, "bold"))
        mark.pack(side="left", padx=(0, 14))

        middle = tk.Frame(row, bg="#ffffff")
        middle.pack(side="left", fill="x", expand=True)
        tk.Label(middle, text=title, bg="#ffffff", anchor="w",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(middle, text=detail, bg="#ffffff", fg="#5f6368", anchor="w",
                 justify="left", font=("Segoe UI", 9)).pack(anchor="w")

        for action in actions:
            if not action:
                continue
            label, command = action
            tk.Button(row, text=label, width=16, command=command
                      ).pack(side="right", padx=(6, 0))

    # --- Dungeons -----------------------------------------------------
    def _page_dungeon(self):
        bot = self._bot_by_key("dungeon")
        frame = self._page_frame(bot["name"], bot["why"], bot["long"])
        import dungeon as D
        self._requirements(frame, "dungeon")

        settings = tk.Frame(frame, bg=BG)
        settings.pack(anchor="w", fill="x", pady=(14, 0))

        # Both columns carry their own heading, on the same line as each
        # other. Before this the right column started with "Rounds" level
        # with the heading "Which dungeons", which read as if Rounds were
        # one of the dungeons.
        left = tk.Frame(settings, bg=BG)
        left.pack(side="left", anchor="n")
        tk.Label(left, text="Which dungeons", bg=BG,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        chosen = self.state_data.get("dungeons",
                                     list(range(len(D.DUNGEON_KEYS) - 1)))
        for i, name in enumerate(D.DUNGEON_NAMES):
            # The hidden ones still get a variable, switched off. The bot
            # counts cards, so the list it plans against has to keep every
            # entry the game shows -- only the checkbox goes away.
            var = tk.BooleanVar(value=i in chosen and name not in HIDDEN_DUNGEONS)
            self.vars["dg_%d" % i] = var
            if name in HIDDEN_DUNGEONS:
                continue
            tk.Checkbutton(left, text=name, variable=var, bg=BG).pack(anchor="w")

        right = tk.Frame(settings, bg=BG, padx=28)
        right.pack(side="left", anchor="n")
        tk.Label(right, text="How it runs", bg=BG,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        self._spin(right, "runden", "Rounds", 2, 1, 20)
        self._spin(right, "max_minutes", "Time limit, minutes (0 = none)",
                   0, 0, 600)
        # Not seconds: dungeon.py multiplies every one of its waits by
        # this, so 1 is the pace it was written for.
        self._spin(right, "langsam", "Patience, 1 = normal pace",
                   1.5, 0.5, 4.0, floaty=True)
        tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 8),
                 text=("    Prevents too fast and therefore wrong "
                       "clicking.\n    Raise if you have a slow computer.")
                 ).pack(anchor="w")
        # Always on, no switch. Reading the ticket counters before opening
        # anything is what keeps the bot from working through dungeons that
        # have nothing left, and there is no reason a player would want it
        # off.
        self.vars["survey"] = tk.BooleanVar(value=True)
        for key, text, default in (
                ("use_ads", "Use ad tickets", True),
                ("no_adb", NO_ADB_LABEL, True)):
            var = tk.BooleanVar(value=self.state_data.get(key, default))
            self.vars[key] = var
            tk.Checkbutton(right, text=text, variable=var, bg=BG).pack(anchor="w")
            if key == "use_ads":
                tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                         font=("Segoe UI", 8),
                         text=("    Ads are only watched if you have bought "
                               "the ad pass.")).pack(anchor="w")
            if key == "no_adb":
                tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                         font=("Segoe UI", 8),
                         text=NO_ADB_NOTE).pack(anchor="w")

        afk = tk.Frame(frame, bg=BG, pady=10)
        afk.pack(anchor="w", fill="x")
        var = tk.BooleanVar(value=self.state_data.get("afk", False))
        self.vars["afk"] = var
        # The switch, then what it does, then the extras it can be given.
        # Each extra carries its own line: a block of explanation covering
        # three checkboxes at once left it unclear which sentence belonged
        # to which box.
        tk.Checkbutton(afk, text="Instant AFK mode (experimental, needs ADB "
                                 "or the game icon taught once)",
                       variable=var, bg=BG, font=("Segoe UI", 10, "bold")
                       ).pack(anchor="w")
        tk.Label(afk, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 9),
                 text=("    Start does everything from cold: launches "
                       "LDPlayer, opens the game, taps past the title "
                       "screen,\n    closes the login pop-ups, then plays "
                       "the dungeons. After every tap it checks that the "
                       "screen\n    changed, and stops and says so rather "
                       "than tapping at whatever is there.")
                 ).pack(anchor="w", pady=(2, 8))

        claim = tk.BooleanVar(value=self.state_data.get("afk_claim", False))
        self.vars["afk_claim"] = claim
        tk.Checkbutton(afk, text="Also claim the idle rewards", variable=claim,
                       bg=BG).pack(anchor="w", padx=(24, 0))

        auto = tk.BooleanVar(value=self.state_data.get("afk_auto", False))
        self.vars["afk_auto"] = auto
        tk.Checkbutton(afk, text="Also switch on Auto Spend for Hologram "
                                 "Tickets", variable=auto, bg=BG
                       ).pack(anchor="w", padx=(24, 0))
        tk.Label(afk, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 8),
                 text=("        Pressed once on the main screen, before the "
                       "dungeons, so the game spends the tickets by "
                       "itself.")).pack(anchor="w")

        self._run_controls(frame, "dungeon",
                           [("Start", lambda: self._start_dungeon(True))],
                           extra=[("Dry run",
                                   lambda: self._start_dungeon(False))])
        return {"frame": frame, "refresh": None}

    # --- Digital World Search -----------------------------------------
    def _page_mini(self):
        bot = self._bot_by_key("mini")
        frame = self._page_frame(bot["name"], bot["why"], bot["long"])
        import world as world_mod
        self._requirements(frame, "mini")

        self.mini_state = tk.Label(frame, bg=BG, justify="left", anchor="w",
                                   font=("Segoe UI", 10))
        self.mini_state.pack(anchor="w", pady=(14, 8))

        settings = tk.Frame(frame, bg=BG)
        settings.pack(anchor="w", fill="x")

        left = tk.Frame(settings, bg=BG)
        left.pack(side="left", anchor="n")
        tk.Label(left, text="What to collect", bg=BG,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        wanted = self.state_data.get("wanted", list(world_mod.ALL_WANTED))
        for key in world_mod.ALL_WANTED:
            var = tk.BooleanVar(value=key in wanted)
            self.vars["want_" + key] = var
            tk.Checkbutton(left, text=key.replace("_", " "), variable=var,
                           bg=BG).pack(anchor="w")

        right = tk.Frame(settings, bg=BG, padx=28)
        right.pack(side="left", anchor="n")
        self._spin(right, "min_paws", "Stop below this many paws", 0, 0, 500)
        tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 8),
                 text=("    0 keeps going until the paws run out. Set it "
                       "higher to\n    leave yourself a reserve to spend.")
                 ).pack(anchor="w")
        self._spin(right, "max_actions", "Action limit (0 = none)", 0, 0, 5000)
        tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 8),
                 text=("    Stops after this many moves, whatever is left "
                       "over.\n    Handy for a short test run; 0 lets it "
                       "play on.")).pack(anchor="w")
        self._spin(right, "target_meters", "Stop at metres (0 = none)",
                   0, 0, 100000)
        # This one really is seconds, engine passes it to actions.Actor.
        self._spin(right, "click_delay", "Seconds between clicks",
                   0.7, 0.1, 5.0, floaty=True)
        for key, text, default in (
                ("adaptive", "Speed up while it goes well", True),
                ("mini_no_adb", NO_ADB_LABEL, True)):
            var = tk.BooleanVar(value=self.state_data.get(key, default))
            self.vars[key] = var
            tk.Checkbutton(right, text=text, variable=var, bg=BG).pack(anchor="w")
            if key == "mini_no_adb":
                tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                         font=("Segoe UI", 8),
                         text=NO_ADB_NOTE).pack(anchor="w")
            if key == "adaptive":
                tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                         font=("Segoe UI", 8),
                         text=("    Shortens the wait between clicks while "
                               "every move lands, and\n    goes back to the "
                               "full wait the moment one does not.")
                         ).pack(anchor="w")

        self._run_controls(frame, "mini",
                           [("Start", lambda: self._start_mini(True))],
                           extra=[("Dry run", lambda: self._start_mini(False))])

        def refresh():
            state = self.bot_states()["mini"]
            self.mini_state.configure(
                text=("Ready to run." if state["ready"]
                      else "Not ready yet: %s. Press Start and the setup "
                           "opens where it is needed." % state["detail"]))

        return {"frame": frame, "refresh": refresh}

    def _start_mini(self, real_run):
        if not self._first_run_notice("mini"):
            return
        if self.worker and self.worker.is_alive():
            return
        import engine
        import world as world_mod

        # Same rule as the other two: never start without the images it
        # matches against, send them to the step that fixes it instead.
        states = self.bot_states()
        if not states["mini"]["ready"]:
            self._lock("mini")
            self._write("\nNot set up yet (%s), opening the setup."
                        % states["mini"]["detail"], "warn")
            self.events.put(("done", ""))
            self._setup_for(self._bot_by_key("mini"))
            return

        wanted = [k for k in world_mod.ALL_WANTED
                  if self.vars["want_" + k].get()]
        if not wanted:
            messagebox.showwarning("Nothing selected",
                                   "Pick at least one thing to collect.")
            return
        self.state_data["wanted"] = wanted
        self._save_keys(["min_paws", "max_actions", "target_meters",
                         "click_delay", "adaptive", "mini_no_adb"])
        self._lock("mini")
        self._write("\n%s, collecting %s"
                    % ("Start" if real_run else "Dry run", ", ".join(wanted)),
                    "dim")

        settings = engine.Settings(
            dry_run=not real_run, is_selected=wanted,
            min_paws=self.vars["min_paws"].get(),
            max_actions=self.vars["max_actions"].get(),
            target_meters=self.vars["target_meters"].get(),
            click_delay=self.vars["click_delay"].get(),
            adaptive=self.vars["adaptive"].get(),
            capture_mode="window" if self.vars["mini_no_adb"].get() else "hybrid")

        # engine.run starts its own guard, so this bot needs no _start_guard.
        holder = _StopHolder()
        self.stop = holder

        def job():
            try:
                stats = engine.run(settings, self._emit_engine, holder.control)
                self.events.put(("log", "\nSummary: %s" % stats))
            except Exception as err:
                self.events.put(("warn", "Error: %s" % err))
            finally:
                self.events.put(("done", ""))

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def _emit_engine(self, event):
        """engine speaks in event dicts, the log wants lines."""
        text = str(event.get("text", "")) if isinstance(event, dict) else str(event)
        if not text:
            return
        kind = event.get("art", "") if isinstance(event, dict) else ""
        self.events.put(("warn" if str(kind).lower().startswith("w") else "log",
                         text))

    # --- Skewer -------------------------------------------------------
    def _page_skewer(self):
        bot = self._bot_by_key("skewer")
        frame = self._page_frame(bot["name"], bot["why"], bot["long"])
        import skewer as S
        self._requirements(frame, "skewer")

        self.sk_state = tk.Label(frame, bg=BG, justify="left", anchor="w",
                                 font=("Segoe UI", 10))
        self.sk_state.pack(anchor="w", pady=(14, 8))

        settings = tk.Frame(frame, bg=BG)
        settings.pack(anchor="w", fill="x")
        self._spin(settings, "sk_rounds", "Rounds", 1, 1, 50)
        self._spin(settings, "sk_speed", "Speed, 1 = full pace",
                   1.0, S.MIN_SPEED, 1.0, floaty=True)
        # Always on, and no switch for it. The bot opens Play Game itself and
        # starts the stage, so the minigame's main menu is the one place it
        # can begin from. Offering the choice only invited it to be turned
        # off and the run to start with two taps into whatever was there.
        self.vars["sk_from_menu"] = tk.BooleanVar(value=True)
        var = tk.BooleanVar(value=self.state_data.get("sk_no_adb", True))
        self.vars["sk_no_adb"] = var
        tk.Checkbutton(settings, text=NO_ADB_LABEL,
                       variable=var, bg=BG).pack(anchor="w")
        tk.Label(settings, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 8), text=NO_ADB_NOTE).pack(anchor="w")

        tk.Label(frame, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 9),
                 text=("Speed is the wait between clicks. 1 is full pace; "
                       "lower it if this machine\ncannot keep up with "
                       "clicking faster than the emulator redraws."
                       )).pack(anchor="w", pady=(6, 0))

        self._run_controls(frame, "skewer",
                           [("Start", lambda: self._start_skewer(True))],
                           extra=[("Dry run",
                                   lambda: self._start_skewer(False)),
                                  ("Diagnostics", self._skewer_probe)])

        def refresh():
            state = self.bot_states()["skewer"]
            self.sk_state.configure(
                text=("%s. Ready to run." % state["detail"] if state["ready"]
                      else "%s. Press Start and the setup opens where it is "
                           "needed." % state["detail"]))

        return {"frame": frame, "refresh": refresh}

    # --- Setup --------------------------------------------------------
    # --- About --------------------------------------------------------
    def _page_about(self):
        frame = self._page_frame(
            "About",
            "Helpermon plays three parts of Digimon UP for you: the dungeon\n"
            "list, the Digital World Search and the Midsummer Digimon Night\n"
            "Market.")
        tk.Label(frame, text=FAN_TITLE, bg=BG, anchor="w",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(16, 4))
        tk.Label(frame, text=FAN_NOTICE, bg=BG, justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w")
        tk.Label(frame, text=INTENT_TITLE, bg=BG, anchor="w",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(16, 4))
        tk.Label(frame, text=INTENT, bg=BG, justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 14))
        tk.Frame(frame, height=1, bg="#d0d3d8").pack(fill="x")
        tk.Label(frame, text=LEGAL_NOTICE, bg=BG, justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(14, 12))
        tk.Label(frame, text=HOTKEY_HINT, bg=BG, justify="left", fg="#5f6368",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 12))
        row = tk.Frame(frame, bg=BG)
        row.pack(anchor="w", fill="x")
        tk.Button(row, text="Show the notice again", width=24,
                  command=self._legal_notice).pack(side="left")
        tk.Button(row, text="How it reaches the emulator", width=26,
                  command=self._adb_notice).pack(side="left", padx=(8, 0))

        # Last, and behind a line, because these undo things. There is no way
        # into the full wizard from here on purpose: setting a bot up belongs
        # on that bot's page, and a button offering all eight steps at once is
        # the thing that used to land people in the wrong bot's setup.
        #
        # Two buttons, not one: settings are cheap to set again, and the
        # learned images are twenty minutes of a player's evening.
        tk.Frame(frame, height=1, bg="#d0d3d8").pack(fill="x", pady=(18, 0))
        tk.Label(frame, text="Starting over", bg=BG, anchor="w",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(14, 4))

        row = tk.Frame(frame, bg=BG)
        row.pack(anchor="w", fill="x", pady=(4, 0))
        tk.Button(row, text="Reset the settings", width=22,
                  command=self._reset_settings).pack(side="left")
        tk.Label(row, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 9),
                 text=("  Puts every setting on every page back to its "
                       "default.\n  Learned images stay.")).pack(side="left")

        row = tk.Frame(frame, bg=BG)
        row.pack(anchor="w", fill="x", pady=(10, 0))
        tk.Button(row, text="Delete learned images", width=22,
                  command=self._reset_learned).pack(side="left")
        tk.Label(row, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 9),
                 text=("  Throws away every image and digit you taught it, "
                       "so every\n  bot needs its setup again. Settings "
                       "stay.")).pack(side="left")
        return {"frame": frame, "refresh": None}

    def _reset_settings(self):
        """Every page back to its defaults. Nothing learned is touched."""
        if not messagebox.askyesno(
                "Reset the settings",
                "Puts every setting on every page back to its default: "
                "which dungeons are ticked, rounds, patience, all of it.\n\n"
                "The images and digits you taught it stay where they are.\n\n"
                "Carry on?"):
            return

        failed = []
        for path in (STATE_FILE, OLD_STATE_FILE):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as err:
                failed.append(str(err))
        self.state_data = {}
        self._refresh_nav_dots()

        if failed:
            messagebox.showwarning(
                "Not reset", "Could not remove the settings: %s"
                % ", ".join(failed))
            return
        messagebox.showinfo(
            "Settings reset",
            "Every setting is back to its default.\n\n"
            "The pages you have open still show the old values until you "
            "restart Helpermon.")
        self.status.configure(text="settings reset to their defaults")

    def _reset_learned(self):
        """Throw away everything the bots learned to see. Settings stay.

        The images are moved rather than deleted. Relearning them is twenty
        minutes of a player's evening, and a mis-click on this button should
        not cost that -- the dialog says where they went, so anyone who
        really wants them gone can empty one folder.
        """
        import shutil
        import time

        import userdata

        folder = userdata.data_dir()
        if not messagebox.askyesno(
                "Delete learned images",
                "Goes away:\n"
                "  - every image and digit you taught it\n"
                "  - the open cases it collected while running\n\n"
                "Every bot that needs images needs its setup again "
                "afterwards. Your settings are not touched.\n\n"
                "The images are moved into a dated folder inside\n%s\n"
                "rather than deleted, so you can still get them back.\n\n"
                "Carry on?" % folder):
            return

        moved, failed = [], []
        backup = os.path.join(folder, "reset_" + time.strftime("%Y%m%d_%H%M%S"))
        for name in ("templates", "digits", "unknown"):
            source = os.path.join(folder, name)
            if not os.path.isdir(source):
                continue
            try:
                os.makedirs(backup, exist_ok=True)
                shutil.move(source, os.path.join(backup, name))
                moved.append(name)
            except Exception as err:
                failed.append("%s (%s)" % (name, err))

        # Caches hold the images that were just moved away.
        for module, forget in (("vision", "forget_templates"),
                               ("skewer", "forget_ingredient_templates")):
            try:
                forget_fn = getattr(__import__(module), forget)
                forget_fn()
            except Exception:
                pass
        try:
            import learning
            learning.set_only_learned(False)
        except Exception:
            pass

        self._refresh_nav_dots()
        self.show_page("about")
        if failed:
            messagebox.showwarning(
                "Deleted, partly",
                "Moved: %s\n\nCould not move: %s"
                % (", ".join(moved) or "nothing", ", ".join(failed)))
        else:
            messagebox.showinfo(
                "Learned images deleted",
                "Moved: %s\n\nThey are in\n%s"
                % (", ".join(moved) or "nothing was learned yet", backup))
        self.status.configure(text="learned images cleared")

    # ==================================================================
    # Shared widgets
    # ==================================================================
    def _spin(self, parent, key, label, default, lo, hi, floaty=False):
        row = tk.Frame(parent, bg=BG)
        row.pack(anchor="w", fill="x", pady=1)
        tk.Label(row, text=label, width=30, anchor="w", bg=BG).pack(side="left")
        # Clamped, not trusted. A value saved before a limit moved -- the
        # minigame's speed used to go to 4 -- would otherwise sit in the box
        # above its own maximum and be handed straight back to the bot.
        saved = self.state_data.get(key, default)
        try:
            saved = min(hi, max(lo, saved))
        except TypeError:
            saved = default
        var = (tk.DoubleVar if floaty else tk.IntVar)(value=saved)
        self.vars[key] = var
        tk.Spinbox(row, from_=lo, to=hi, textvariable=var, width=7,
                   increment=0.1 if floaty else 1).pack(side="left")

    def _run_controls(self, parent, key, starts, extra=()):
        """The same row of controls and the same log for every bot that runs
        in this window, so one bot's page never looks like a different
        program from the next.

        `extra` holds the actions that are for finding out what is wrong
        rather than for playing -- dry run, diagnostics. They still disable
        while something runs, but they sit apart from the button a player
        actually wants.
        """
        buttons = tk.Frame(parent, bg=BG, pady=12)
        buttons.pack(anchor="w", fill="x")
        start_buttons = []
        for label, command in starts:
            button = tk.Button(buttons, text=label, width=14, command=command)
            button.pack(side="left", padx=(0, 8))
            start_buttons.append(button)
        pause = tk.Button(buttons, text="Pause", width=12, state="disabled",
                          command=self._pause)
        pause.pack(side="left")
        stop = tk.Button(buttons, text="Stop", width=12, state="disabled",
                         command=self._panic)
        stop.pack(side="left", padx=8)
        tk.Button(buttons, text="Clear log", width=12,
                  command=lambda: self._clear_log(key)).pack(side="right")

        tk.Label(parent, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 9), text=HOTKEY_HINT
                 ).pack(anchor="w", pady=(0, 6))

        # The bottom row is packed BEFORE the log, so the log takes the space
        # that is left and this row ends up below it, as far from the button
        # a player wants as the page allows. That is the right place for a
        # dry run and for diagnostics, which are for reporting a problem.
        #
        # Setup no longer sits here. It is under the requirements box now,
        # beside the sentence that says what is missing. It is still on the
        # bot's own page and nowhere else: there used to be one Setup page
        # for all three, and from it one wizard that walked through
        # everybody's steps in a row -- so setting up the Night Market
        # carried you on into the World Search's four steps with nothing
        # saying you had left what you came for.
        bottom = tk.Frame(parent, bg=BG, pady=6)
        bottom.pack(side="bottom", anchor="w", fill="x")
        if extra:
            tk.Label(bottom, text="For testing:", bg=BG, fg="#70757c",
                     font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
            for label, command in extra:
                button = tk.Button(bottom, text=label, width=13,
                                   command=command)
                button.pack(side="left", padx=(0, 6))
                start_buttons.append(button)

        log_box = tk.Frame(parent, bg=BG)
        log_box.pack(fill="both", expand=True)
        # Wrapped, not clipped. With wrap="none" and no horizontal
        # scrollbar, a long line simply had its end cut off by the window
        # edge -- and the interesting half of a bot's line is the end.
        log = tk.Text(log_box, height=12, wrap="word", font=("Consolas", 9),
                      state="disabled")
        bar = tk.Scrollbar(log_box, command=log.yview)
        log.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        log.pack(side="left", fill="both", expand=True)
        log.tag_configure("warn", foreground="#b3261e")
        log.tag_configure("dim", foreground="#777")

        self.panels[key] = {"starts": start_buttons, "pause": pause,
                            "stop": stop, "log": log}

    def _clear_log(self, key):
        log = self.panels[key]["log"]
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")

    def _bot_by_key(self, key):
        for bot in BOTS:
            if bot["key"] == key:
                return bot
        return BOTS[0]

    # ==================================================================
    # Running the bots
    # ==================================================================
    def _start_dungeon(self, real_run):
        if not self._first_run_notice("dungeon"):
            return
        if self.worker and self.worker.is_alive():
            return
        import capture
        import dungeon as D

        chosen = [i for i in range(len(D.DUNGEON_KEYS))
                  if self.vars["dg_%d" % i].get()]
        if not chosen:
            messagebox.showwarning("Nothing selected",
                                   "Select at least one dungeon.")
            return
        self._save_keys(["dungeons", "runden", "max_minutes", "langsam",
                         "use_ads", "survey", "no_adb", "afk", "afk_claim",
                         "afk_auto"], dungeons=chosen)
        self._lock("dungeon")
        afk = bool(self.vars["afk"].get())
        claim_rewards = bool(self.vars["afk_claim"].get())
        start_auto = bool(self.vars["afk_auto"].get())
        self._write("\n%s%s, selected: %s"
                    % ("Start" if real_run else "Dry run",
                       ", instant AFK" if afk else "",
                       ", ".join(D.DUNGEON_NAMES[i] for i in chosen)), "dim")

        values = {k: self.vars[k].get() for k in
                  ("runden", "max_minutes", "langsam", "use_ads", "survey",
                   "no_adb")}
        # How many dungeons the list holds is not a setting, it is the length
        # of the list the player is looking at.
        values["entries"] = len(D.DUNGEON_NAMES)

        def job():
            watcher = None
            try:
                if afk and not self._afk_cold_start():
                    return
                cap = (capture.open_window() if values["no_adb"]
                       else capture.open_best(prefer_adb=True))
                bot = D.DungeonBot(
                    cap, dry_run=not real_run,
                    log=lambda t: self.events.put(("log", t)),
                    entries=values["entries"], use_ads=values["use_ads"],
                    survey_first=values["survey"], patience=values["langsam"],
                    max_minutes=values["max_minutes"], only=set(chosen))
                self.stop = bot
                watcher = self._start_guard(bot, cap)
                if afk and not bot.wake_up(claim_rewards=claim_rewards,
                                           start_auto=start_auto):
                    self.events.put(("warn", "could not reach the dungeon "
                                     "list, stopping before it clicks at "
                                     "whatever is on screen"))
                    return
                stats = bot.run(values["runden"])
                self.events.put(("log", "\nSummary: %s" % stats))
            except Exception as err:
                self.events.put(("warn", "Error: %s" % err))
            finally:
                if watcher:
                    watcher.stop()
                self.events.put(("done", ""))

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def _start_skewer(self, real_run):
        if not self._first_run_notice("skewer"):
            return
        if self.worker and self.worker.is_alive():
            return
        import capture
        import skewer as S

        # Never start blind: without the learned icons the bot cannot name a
        # single ingredient. Pressing Start is a clear statement of intent,
        # so send them to the step that makes it possible rather than
        # refusing and stopping.
        if not S.load_ingredient_templates(force=True):
            self._lock("skewer")
            self._write("\nNo ingredient icons learned yet, opening the setup "
                        "on the skewer step.", "warn")
            self.events.put(("done", ""))
            self._setup_for(self._bot_by_key("skewer"))
            return

        values = {k: self.vars["sk_" + k].get()
                  for k in ("rounds", "speed", "from_menu", "no_adb")}
        self._save_keys(["sk_rounds", "sk_speed", "sk_from_menu", "sk_no_adb"])
        self._lock("skewer")
        self._write("\n%s, %d round(s), speed %.2f"
                    % ("Start" if real_run else "Dry run",
                       values["rounds"], values["speed"]), "dim")

        def job():
            watcher = None
            try:
                cap = (capture.open_window() if values["no_adb"]
                       else capture.open_best(prefer_adb=True))
                bot = S.SkewerBot(
                    cap, dry_run=not real_run,
                    log=lambda t: self.events.put(("log", t)),
                    speed=values["speed"])
                self.stop = bot
                watcher = self._start_guard(bot, cap)
                if abs(bot.speed - values["speed"]) > 1e-9:
                    self.events.put(("log", "Speed %.2f is outside %g-%g, "
                                     "using %.2f" % (values["speed"],
                                                     S.MIN_SPEED, S.MAX_SPEED,
                                                     bot.speed)))
                self.events.put(("log", "Speed %.2f, %.0f ms between clicks"
                                 % (bot.speed, bot.tick * 1000)))
                stats = bot.run(values["rounds"],
                                from_menu=values["from_menu"])
                self.events.put(("log", "\nSummary: %s" % stats))
            except Exception as err:
                self.events.put(("warn", "Error: %s" % err))
            finally:
                if watcher:
                    watcher.stop()
                self.events.put(("done", ""))

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def _skewer_probe(self):
        """Diagnostics: read the current screen once, click nothing."""
        if self.worker and self.worker.is_alive():
            return
        import capture
        import skewer as S

        no_adb = self.vars["sk_no_adb"].get()
        self._lock("skewer")
        self._write("\nDiagnostics, reads the screen and clicks nothing", "dim")

        def job():
            try:
                cap = (capture.open_window() if no_adb
                       else capture.open_best(prefer_adb=True))
                S.probe(cap, log=lambda t: self.events.put(("log", str(t))))
            except Exception as err:
                self.events.put(("warn", "Error: %s" % err))
            finally:
                self.events.put(("done", ""))

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def _afk_cold_start(self):
        """Emulator up, then the game, before a bot touches anything.

        Two ways to open the game, tried in that order:

        1. the emulator's own tool. Fast and exact, but LDPlayer-only, and
           it needs the Android package name, which needs ADB to look up.
        2. clicking the game's icon on the home screen. Needs neither, and
           works on any emulator, but the icon has to have been learned.

        Returns whether the game may now be handed to a bot. False means
        neither way worked, and the caller must stop: what is on screen is
        then the emulator's own home screen, and a bot tapping at that hits
        the search bar, which is exactly what happened in a live run.

        Runs on the worker thread, so it reports through the event queue like
        everything else.
        """
        self.events.put(("step", "Instant AFK: starting the emulator"))
        app_started = False
        try:
            import ldplayer
            ld = ldplayer.LdPlayer(
                log=lambda t: self.events.put(("step", "  " + str(t))))
            serial = ld.ensure_running(0)
            app_started = bool(getattr(ld, "app_started", False))
            if serial and serial != "window":
                os.environ["DGUP_SERIAL"] = serial
            self.events.put(("log", "  emulator up (%s)" % serial))
        except Exception as err:
            self.events.put(("log", "  emulator tool not usable (%s)" % err))

        # Whether the game is actually open is a separate question: without
        # ADB, ensure_running raises no error and simply leaves the emulator
        # sitting on its home screen.
        import capture
        import launcher

        try:
            cap = capture.open_window()
        except Exception as err:
            self.events.put(("warn", "no emulator window (%s)" % err))
            return False

        say = lambda t: self.events.put(("step", "  " + str(t)))

        if not launcher.have_icon():
            if app_started:
                say("no game icon learned, but the emulator opened the game "
                    "itself")
                return True
            # Without the icon there is no way to open the game and no way
            # to tell the emulator's home screen from the game either --
            # wait_for_home can only ever answer "busy" here, and "busy" is
            # read as "the game must be up". So this stops instead.
            self.events.put(("warn",
                             "Instant AFK cannot open the game: its icon has "
                             "not been learned, and without ADB the emulator "
                             "cannot open it either. Teach the icon under "
                             "Setup, wizard step 'Game icon' -- or start the "
                             "game yourself and run without Instant AFK."))
            return False

        # The window exists within a couple of seconds, the Android behind it
        # does not. Asking "is the icon there?" straight away answers "no",
        # because a boot screen has no icons on it -- which is how this used
        # to decide the game must already be open and then tap at a splash.
        say("waiting for the emulator to finish starting")
        ready = launcher.wait_for_home(cap, log=say)

        if ready["state"] == "timeout":
            self.events.put(("warn", "the emulator never settled; is it "
                                     "actually starting?"))
            return False
        if ready["state"] == "busy":
            say("no home screen, so something is already running - assuming "
                "it is the game")
            return True

        say("opening the game by clicking its icon")
        if launcher.start_game(cap, log=say):
            say("game opened, waiting for it to load")
            return True
        self.events.put(("warn", "the game icon did not open anything, "
                                 "stopping rather than tapping at the "
                                 "emulator's own home screen"))
        return False

    def _start_guard(self, bot, cap):
        """Global hotkeys and the mouse-movement pause, same as the CLI.

        Without this the buttons in this window are unreachable the moment a
        bot starts driving the mouse.
        """
        import guard
        try:
            return guard.start(bot.control, cap=cap,
                               log=lambda t: self.events.put(("log", t)))
        except Exception as err:
            self.events.put(("warn", "no hotkeys or mouse guard: %s" % err))
            return None

    # ------------------------------------------------------------------
    def _panel_now(self):
        return self.panels.get(self.active) or self.panels["dungeon"]

    def _lock(self, name):
        """Hand the buttons and the log over to the bot that is starting."""
        self.active = name
        self.show_page(name)
        panel = self.panels[name]
        for b in panel["starts"]:
            b.configure(state="disabled")
        for b in (panel["pause"], panel["stop"]):
            b.configure(state="normal")
        panel["pause"].configure(text="Pause")

    def _pause(self):
        # Both bots carry a guard.Stop as `control`; that is the only thing
        # they check between two actions.
        if not self.stop:
            return
        paused = self.stop.control.toggle_pause()
        self._panel_now()["pause"].configure(
            text="Continue" if paused else "Pause")
        self.status.configure(text="paused" if paused else "running")

    def _panic(self):
        if self.stop:
            self.stop.control.request("stop from the launcher")
            self.status.configure(
                text="Stopping, it will halt after the current action")

    # ==================================================================
    # Plumbing
    # ==================================================================
    def _setup_for(self, bot, note=""):
        """Open a setup window for this bot and nothing else.

        `--bot` decides which steps that window has at all, so Continue past
        the last one finishes instead of wandering into another bot's setup.
        """
        self._start_file("setup_wizard.py",
                         ["--bot", bot["key"],
                          "--step", bot["step"] or "",
                          "--note", note or DEFAULT_NOTES.get(bot["key"], "")])

    def _start_file(self, name, args=()):
        try:
            subprocess.Popen([sys.executable, name] + list(args), cwd=HERE)
            self.status.configure(text="%s started" % name)
        except Exception as err:
            messagebox.showerror("Could not start", str(err))

    # ------------------------------------------------------------------
    def _first_run_dialogs(self):
        """What a new user is told before anything else, in this order.

        How Helpermon reaches the emulator comes first, because it decides
        whether the next hour is spent with the mouse or without it, and
        because somebody who reads only the first dialog should have read
        that one.
        """
        if not self.state_data.get("adb_notice_read"):
            self._adb_notice()
        if not self.state_data.get("notice_read"):
            self._legal_notice()

    def _adb_notice(self):
        dlg = tk.Toplevel(self)
        dlg.title("How Helpermon reaches the emulator")
        dlg.configure(padx=26, pady=20)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text=ADB_TITLE, font=("Segoe UI", 15, "bold")
                 ).pack(anchor="w")
        tk.Label(dlg, text=ADB_NOTICE, justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(10, 12))
        # ADB debugging has to be switched on in LDPlayer -- the first read
        # of this said otherwise, from a config file that showed it off
        # because the player had turned it off again after testing. So the
        # dialog says to switch it on, and this button reports whether that
        # worked rather than leaving anyone to wonder.
        result = tk.Label(dlg, text="", justify="left", fg="#3c4043",
                          wraplength=560, font=("Segoe UI", 10, "bold"))
        result.pack(anchor="w", pady=(0, 12))
        row = tk.Frame(dlg)
        row.pack(fill="x")

        def check():
            result.configure(text="checking...", fg="#3c4043")
            dlg.update_idletasks()
            ok, text = self._adb_probe()
            result.configure(text=text, fg="#1a7f37" if ok else "#8a4b00")

        tk.Button(row, text="Check ADB now", width=16, command=check
                  ).pack(side="left")
        tk.Button(row, text="Continue", width=14, command=dlg.destroy
                  ).pack(side="right")
        self.wait_window(dlg)
        self.state_data["adb_notice_read"] = True
        self._save()

    @staticmethod
    def _adb_probe():
        """(is it usable, one line about it)."""
        try:
            import capture
            path = capture.find_adb()
            if not path:
                return False, ("No ADB found. LDPlayer ships one; if it sits "
                               "somewhere unusual, point DGUP_ADB at it.")
            devices = capture.AdbCapture().devices()
            if not devices:
                return False, ("ADB is there, but no device answers. Most "
                               "likely ADB debugging is still off: LDPlayer, "
                               "Settings, Other settings, ADB debugging. If "
                               "it is on, start the emulator and check "
                               "again.")
            return True, ("ADB works, device %s. Nothing to do, the bots will "
                          "use it and leave your mouse alone."
                          % ", ".join(devices))
        except Exception as err:
            return False, "ADB could not be asked: %s" % err

    def _first_run_notice(self, key):
        """The bot's requirements, once, the first time it is started.

        Returns whether to go on. Once per bot rather than once per run: the
        list is about what has to be on screen before pressing Start, and
        that is a thing you learn once and then know.
        """
        if self.state_data.get("req_seen_" + key):
            return True
        bot = self._bot_by_key(key)
        dlg = tk.Toplevel(self)
        dlg.title("Before the %s bot can work" % bot["short"])
        dlg.configure(padx=26, pady=20)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text=bot["name"], font=("Segoe UI", 15, "bold")
                 ).pack(anchor="w")
        tk.Label(dlg, text="This has to be true before it can do anything:",
                 fg="#5f6368", font=("Segoe UI", 10)).pack(anchor="w",
                                                           pady=(4, 10))
        for line in REQUIREMENTS[key]:
            tk.Label(dlg, text="\u2022  " + line, justify="left",
                     wraplength=560, font=("Segoe UI", 10)
                     ).pack(anchor="w", pady=(0, 6))
        tk.Frame(dlg, height=1, bg="#d0d3d8").pack(fill="x", pady=(8, 10))
        for line in INPUT_REQUIREMENT:
            tk.Label(dlg, text="\u2022  " + line, justify="left", fg="#5f6368",
                     wraplength=560, font=("Segoe UI", 9)
                     ).pack(anchor="w", pady=(0, 5))
        row = tk.Frame(dlg)
        row.pack(fill="x", pady=(12, 0))
        go = {"on": False}
        tk.Button(row, text="Cancel", width=12, command=dlg.destroy
                  ).pack(side="left")

        def carry_on():
            go["on"] = True
            dlg.destroy()

        tk.Button(row, text="All set, start", width=16, command=carry_on
                  ).pack(side="right")
        self.wait_window(dlg)
        if go["on"]:
            # Only once it has been read to the end and acted on. Cancelling
            # is not having read it.
            self.state_data["req_seen_" + key] = True
            self._save()
        return go["on"]

    def _legal_notice(self):
        dlg = tk.Toplevel(self)
        dlg.title("Please read")
        dlg.configure(padx=26, pady=20)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text="Before first use",
                 font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(dlg, text=FAN_TITLE, justify="left",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 2))
        tk.Label(dlg, text=FAN_NOTICE, justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 12))
        tk.Label(dlg, text=LEGAL_NOTICE, justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 14))
        row = tk.Frame(dlg)
        row.pack(fill="x")
        read_ok = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="I have read and understood this",
                       variable=read_ok).pack(side="left")
        button = tk.Button(row, text="Continue", width=14, state="disabled",
                           command=dlg.destroy)
        button.pack(side="right")
        read_ok.trace_add("write", lambda *_: button.configure(
            state="normal" if read_ok.get() else "disabled"))
        self.wait_window(dlg)
        if read_ok.get():
            self.state_data["notice_read"] = True
            self._save()

    def _pump(self):
        while True:
            try:
                kind, text = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "done":
                panel = self._panel_now()
                for b in panel["starts"]:
                    b.configure(state="normal")
                for b in (panel["pause"], panel["stop"]):
                    b.configure(state="disabled")
                panel["pause"].configure(text="Pause")
                self.status.configure(text="stopped")
                self.stop = None
                self.active = None
            elif kind == "emu_ok":
                self._set_emulator(True, text)
                self.status.configure(text=text)
            elif kind == "emu_idle":
                self._set_emulator("idle", text)
            elif kind == "emu_bad":
                self._set_emulator(False, text)
                self.status.configure(text=text)
            elif kind == "step":
                # Progress: worth seeing in both places, because the log
                # scrolls and the status bar does not.
                self._write(text, "dim")
                self.status.configure(text=str(text).strip()[:110])
            elif kind == "recheck":
                self.check_emulator()
            elif kind == "status":
                self.status.configure(text=str(text)[:110])
            elif kind == "warn":
                self._write(text, "warn")
                self.status.configure(text=text[:110])
            else:
                self._write(text)
        self._sync_pause_button()
        self.after(80, self._pump)

    def _sync_pause_button(self):
        """Follow the bot's pause state instead of assuming this window
        caused it. F7 and the mouse guard both pause without touching the
        button, and a button claiming the opposite is worse than no button.
        """
        if self.stop is None:
            return
        paused = self.stop.control.is_paused()
        button = self._panel_now()["pause"]
        want = "Continue" if paused else "Pause"
        if button.cget("text") != want:
            button.configure(text=want)
            self.status.configure(text="paused" if paused else "running")

    def _write(self, text, tag=None):
        log = self._panel_now()["log"]
        log.configure(state="normal")
        log.insert("end", text + "\n", tag or ())
        log.see("end")
        log.configure(state="disabled")

    # ------------------------------------------------------------------
    def _load(self):
        for path in (STATE_FILE, OLD_STATE_FILE):
            try:
                with open(path) as fh:
                    return json.load(fh)
            except Exception:
                continue
        return {}

    def _save(self):
        try:
            with open(STATE_FILE, "w") as fh:
                json.dump(self.state_data, fh, indent=2)
        except Exception:
            pass

    def _save_keys(self, keys, **extra):
        for key in keys:
            if key in self.vars:
                self.state_data[key] = self.vars[key].get()
        self.state_data.update(extra)
        self._save()


def main():
    app = App()

    def on_close():
        if app.stop:
            app.stop.control.request("window closed")
        app._save()
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
