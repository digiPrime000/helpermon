"""
Setup wizard.

  py setup_wizard.py

It learns everything the bot needs to see from your own screen. That way no
third-party image material sits in the program folder, and after a skin change
or a game update you can set up again in minutes.

Steps
  1. Overview, what is present and what is missing
  2. Counters, type in seven numbers, which yields labelled digit images
  3. Objects, label the colourful finds
  4. Pyramid, confirm one suggestion
  5. Banners, the wizard provokes the first text itself
  6. Skewer, name the twelve ingredient icons of the cooking minigame
  7. Game icon, click the game's icon so the bot can start it itself
  8. Open cases, label finds collected during runs

Steps 2 to 5 belong to the board minigame and need its board on screen. Step
6 belongs to the skewer bot and needs the cooking minigame on screen instead,
so it asks only for a frame, not for a calibrated board -- see grab().

Rare types do not show up in a short session. Green ticket, pink ticket, claw,
paw and fireball on the ground appear seldom, so the bot queues unknown finds
during runs and you label them later in step 6.
"""

import argparse
import base64
import os
import threading
import tkinter as tk
from tkinter import messagebox

import cv2

import engine
import learning
import userdata
import vision

STEPS = ["Overview", "Counters", "Objects", "Pyramid", "Banners", "Skewer",
         "Game icon", "Open cases"]

# Which of those steps belong to which bot, and the name to put on the
# window. One bot, one window, and nothing in it that belongs to another:
# setting up the Night Market used to walk you straight on into the World
# Search's four steps, with no sign that you had left the thing you came for.
#
# The full list stays reachable by starting this file with no --bot, which is
# where Diagnostics and the overview live.
# Step name to the method that draws it. A dict rather than a list indexed
# by step number, because the sequence is no longer always the same one.
PAGE_FOR = {"Overview": "page_overview", "Counters": "page_counters",
            "Objects": "page_objects", "Pyramid": "page_pyramid",
            "Banners": "page_banner", "Skewer": "page_skewer",
            "Game icon": "page_icon", "Open cases": "page_queue"}

BOT_STEPS = {
    "dungeon": ("Dungeons", ["Game icon"]),
    "mini": ("Digital World Search",
             ["Counters", "Objects", "Pyramid", "Banners", "Open cases"]),
    "skewer": ("Midsummer Digimon Night Market", ["Skewer"]),
}
COUNTER_ORDER = ["top_orange", "top_green", "top_pink", "paws", "claws",
                 "fireballs", "meters"]
COUNTER_LABEL = {"top_orange": "orange, top", "top_green": "green, top",
                 "top_pink": "pink, top", "paws": "paws", "claws": "claws",
                 "fireballs": "fireballs", "meters": "metres"}


def to_photo(bgr, scale=3):
    """OpenCV image to a tkinter image, without an extra package.

    Tk 8.6 reads PNG, but expects the data base64 encoded. Raw bytes are not
    recognised by every version and raise "couldn't recognize image data".
    Hence PNG plus base64, with PPM as a fallback. If both fail, None is
    returned and the page builds without that image instead of dying.
    """
    if bgr is None or getattr(bgr, "size", 0) == 0:
        return None
    if scale != 1:
        bgr = cv2.resize(bgr, (bgr.shape[1] * scale, bgr.shape[0] * scale),
                         interpolation=cv2.INTER_NEAREST)
    for ext in (".png", ".ppm"):
        try:
            ok, buf = cv2.imencode(ext, bgr)
            if not ok:
                continue
            data = base64.b64encode(buf.tobytes())
            return tk.PhotoImage(data=data)
        except Exception:
            try:
                return tk.PhotoImage(data=buf.tobytes())
            except Exception:
                continue
    return None


class Wizard(tk.Tk):
    def __init__(self, step=0, note="", bot=""):
        super().__init__()
        # `order` is the sequence this window walks, and it is the whole of
        # what this window can reach. Continue past the last step finishes;
        # there is no way from here into another bot's setup.
        title, self.order = BOT_STEPS.get(bot, ("", list(STEPS)))
        self.bot = bot if title else ""
        self.title("Helpermon - %s" % (title + " setup" if title else "setup"))
        self.geometry("860x600")
        self.cap = None
        self.calib = None
        self.frame_img = None
        self.photos = []  # keep references, or the images disappear
        self.step = max(0, min(step, len(self.order) - 1))
        # Why this window opened, when something else opened it. Shown once,
        # at the top of the first page seen: landing on step 6 of 7 with no
        # explanation is worse than not jumping there at all.
        self.note = note

        head = tk.Frame(self, padx=12, pady=8)
        head.pack(fill="x")
        self.title_lab = tk.Label(head, text="", font=("Segoe UI", 14, "bold"))
        self.title_lab.pack(side="left")
        self.step_lab = tk.Label(head, text="", fg="#666")
        self.step_lab.pack(side="right")

        # Scrollable content area. With this many picture-heavy steps not
        # everything fits on every screen otherwise, and the button below
        # ends up out of reach.
        outer = tk.Frame(self, padx=12)
        outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer, highlightthickness=0)
        bar = tk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas)
        self._body_id = self.canvas.create_window((0, 0), window=self.body,
                                                  anchor="nw")
        self.body.bind("<Configure>", lambda _e: self._resize_scrollregion())
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._body_id, width=e.width))
        self.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(
            int(-e.delta / 120), "units"))

        foot = tk.Frame(self, padx=12, pady=10)
        foot.pack(fill="x")
        self.log_lab = tk.Label(foot, text="", anchor="w", fg="#444")
        self.log_lab.pack(side="left", fill="x", expand=True)
        tk.Button(foot, text="Grab a new frame", command=self.grab).pack(side="left", padx=6)
        self.b_back = tk.Button(foot, text="Back", command=self.back)
        self.b_back.pack(side="left")
        self.b_next = tk.Button(foot, text="Continue", command=self.forward)
        self.b_next.pack(side="left", padx=6)

        self.show()

    def _resize_scrollregion(self):
        """Scroll only as far as the content actually reaches.

        bbox("all") alone leaves the region at whatever the tallest page
        needed, because the canvas window item keeps its old size until it is
        redrawn. Clamping to the body's requested height keeps the scrollbar
        honest about how much there is to see.
        """
        height = max(self.body.winfo_reqheight(), self.canvas.winfo_height())
        self.canvas.configure(scrollregion=(0, 0, 0, height))

    # ------------------------------------------------------------------
    def say(self, text):
        self.log_lab.configure(text=text)
        self.update_idletasks()

    def ensure_cap(self):
        if self.cap is None:
            self.say("looking for the emulator")
            self.cap = engine.open_capture(engine.Settings())
        return self.cap

    def grab(self):
        """Fetch a fresh frame, then calibrate the board on it.

        The two are kept apart on purpose. Calibration measures the board
        minigame's grid and fails whenever something else is on screen -- the
        skewer minigame, for one. A failed calibration therefore clears only
        self.calib; the frame itself stays, because a page that needs a
        picture but no board (see need_image) must still be able to work.
        """
        try:
            cap = self.ensure_cap()
            self.frame_img = cap.grab()
        except Exception as err:
            self.frame_img = None
            self.calib = None
            self.say("no frame: %s" % err)
            self.show()
            return
        try:
            self.calib = vision.calibrate(self.frame_img)
            self.say("frame grabbed, cell %.1f x %.1f"
                     % (self.calib["cell_w"], self.calib["cell_h"]))
        except Exception as err:
            self.calib = None
            self.say("frame grabbed, but no board on it: %s" % err)
        self.show()

    def back(self):
        self.step = max(0, self.step - 1)
        self.show()

    def forward(self):
        if self.step >= len(self.order) - 1:
            self.finish()
            return
        self.step += 1
        self.show()

    def finish(self):
        """Last step. A short summary and close, so it is clear that this is
        the end. The button used to say Continue and did nothing.

        The summary covers this window's bot and no other. Being told that
        "something is still missing" about a bot you were not setting up is
        how the old, shared wizard sent people back round a second time for
        no reason.
        """
        st = learning.status()
        done, detail = self._bot_summary(st)
        where = "\n\nLearned images are stored in\n%s" % st["ort"]
        if done:
            messagebox.showinfo("Setup complete", detail + where)
        else:
            messagebox.showwarning(
                "Not finished yet",
                detail + "\n\nYou can reopen this from the bot's own page at "
                "any time." + where)
        self.destroy()

    def _bot_summary(self, st):
        """(finished, what to say) for whatever this window was set up for."""
        if self.bot == "dungeon":
            try:
                import launcher
                have = bool(launcher.have_icon())
            except Exception:
                have = False
            return have, ("The game icon is learned, so Instant AFK can open "
                          "the game by itself." if have else
                          "No game icon yet. The dungeon bot plays without "
                          "one; only Instant AFK needs it.")
        if self.bot == "skewer":
            return st["skewer_ready"], (
                "All twelve ingredient icons are there, the Night Market bot "
                "can read the grid." if st["skewer_ready"] else
                "Ingredient icons: %d of %d."
                % (len(st["skewer_have"]), st["skewer_total"]))
        if self.bot == "mini":
            return st["fertig"], (
                "Everything the Digital World Search needs is there."
                if st["fertig"] else
                "Board images: %s\nDigits: %s"
                % (", ".join(st["missing"]) or "none",
                   ", ".join(st["ziffern_fehlen"]) or "none"))
        every = st["fertig"] and st["skewer_ready"]
        return every, (
            "Everything needed is there, all bots can work." if every else
            "Board images: %s\nDigits: %s\nSkewer icons: %d of %d"
            % (", ".join(st["missing"]) or "none",
               ", ".join(st["ziffern_fehlen"]) or "none",
               len(st["skewer_have"]), st["skewer_total"]))

    # ------------------------------------------------------------------
    def show(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.photos = []
        if self.note:
            banner = tk.Frame(self.body, bg="#eef4ff", padx=10, pady=8)
            banner.pack(anchor="w", fill="x", pady=(4, 10))
            tk.Label(banner, text=self.note, bg="#eef4ff", justify="left",
                     font=("Segoe UI", 10), fg="#1a3d7c").pack(anchor="w")
            self.note = ""  # once is enough
        name = self.order[self.step]
        self.title_lab.configure(text=name)
        # Only worth a counter when there is more than one. "Step 1 of 1" on
        # the Night Market's single step reads like something is missing.
        self.step_lab.configure(
            text="" if len(self.order) == 1
            else "Step %d of %d" % (self.step + 1, len(self.order)))
        # Match the buttons to the situation, so there is never a button
        # that does nothing
        last = self.step >= len(self.order) - 1
        self.b_next.configure(text="Finish" if last else "Continue")
        self.b_back.configure(state="disabled" if self.step == 0 else "normal")
        page = getattr(self, PAGE_FOR[name])
        # A new page starts at the top. The canvas keeps its scroll offset
        # when the frame inside it is replaced, so leaving a tall page while
        # scrolled down left the next, shorter one sitting at the bottom of
        # an otherwise empty canvas.
        self.canvas.yview_moveto(0)
        try:
            page()
        except Exception as err:
            # Make it visible instead of failing silently. The page used
            # to be left half empty, looking like a dead end.
            import traceback
            traceback.print_exc()
            tk.Label(self.body, justify="left", fg="#b3261e",
                     text="Error building this page\n\n%s\n\nNext still takes you to the next step."
                          % err).pack(anchor="w", pady=20)
            self.say("Error: %s" % err)

    def need_frame(self):
        """For the board pages: a frame the board could be measured on."""
        if self.calib is None:
            tk.Label(self.body, justify="left", font=("Segoe UI", 10),
                     text=("No usable picture of the board.\n\n"
                           "Open the minigame in the emulator, then press "
                           "'Grab a new frame' below.")).pack(anchor="w", pady=20)
            return False
        return True

    def need_image(self):
        """For pages that only need a picture, with no board on it."""
        if self.frame_img is None:
            tk.Label(self.body, justify="left", font=("Segoe UI", 10),
                     text=("No picture yet.\n\n"
                           "Open the game in the emulator, then press "
                           "'Grab a new frame' below.")).pack(anchor="w", pady=20)
            return False
        return True

    # ------------------------------------------------------------------
    def page_overview(self):
        st = learning.status()
        tk.Label(self.body, justify="left", font=("Segoe UI", 10),
                 text=("The wizard learns everything from your own screen.\n"
                       "Learned images are stored in\n  %s" % st["ort"])
                 ).pack(anchor="w", pady=(6, 10))

        grid = tk.Frame(self.body)
        grid.pack(anchor="w")
        for i, (name, source) in enumerate(sorted(st["quellen"].items())):
            farbe = {"learned": "#1a7f37", "shipped": "#8a6d00",
                     "missing": "#b3261e"}[source]
            tk.Label(grid, text=name, width=26, anchor="w").grid(row=i % 6,
                                                                 column=(i // 6) * 2,
                                                                 sticky="w")
            tk.Label(grid, text=source, fg=farbe, width=14, anchor="w").grid(
                row=i % 6, column=(i // 6) * 2 + 1, sticky="w")

        digits = st["ziffern"]
        tk.Label(self.body, anchor="w", pady=10, justify="left",
                 text=("Digits, reference images per digit\n  "
                       + "  ".join("%s=%d" % (d, digits.get(d, 0))
                                   for d in "0123456789")
                       + ("\n  missing: " + ", ".join(st["ziffern_fehlen"])
                          if st["ziffern_fehlen"] else "\n  none missing"))
                 ).pack(anchor="w")

        # The switch itself lives behind Diagnostics now. What stays here is
        # the alarm: with it on, every shipped image counts as missing and
        # the whole program reports itself as not set up. That looked like a
        # broken install once already.
        if learning.only_learned():
            box = tk.Frame(self.body, bg="#fff4e5", padx=10, pady=8)
            box.pack(anchor="w", fill="x", pady=(4, 8))
            tk.Label(box, bg="#fff4e5", fg="#8a4b00", justify="left",
                     font=("Segoe UI", 10, "bold"),
                     text="Test mode: shipped images are being ignored"
                     ).pack(anchor="w")
            tk.Label(box, bg="#fff4e5", fg="#8a4b00", justify="left",
                     text=("Anything not learned by you counts as missing, so "
                           "the setup below\nwill look incomplete even when it "
                           "is not.")).pack(anchor="w")
            tk.Button(box, text="Use shipped images again",
                      command=lambda: self._set_only(False)).pack(anchor="w",
                                                                  pady=(6, 0))

        if st["shipped"]:
            tk.Label(self.body, justify="left", fg="#8a6d00",
                     text=("Note: %d images are shipped rather than learned\n"
                           "here. They work, but they do not belong in a published\n"
                           "copy. To start clean, learn them again here."
                           % len(st["shipped"]))).pack(anchor="w", pady=(8, 0))

        # The skewer bot's icons are counted, not listed by name: they are
        # named by whoever learns them, so only their number says anything.
        # Without this line setup can report "ready" while the skewer bot
        # cannot name a single ingredient.
        tk.Label(self.body, anchor="w", pady=10, justify="left",
                 text=("Skewer minigame, ingredient icons\n  %d of %d learned"
                       % (len(st["skewer_have"]), st["skewer_total"]))
                 ).pack(anchor="w")

        rows = [("Board minigame", st["fertig"]),
                ("Skewer minigame", st["skewer_ready"])]
        for name, ready in rows:
            tk.Label(self.body, fg="#1a7f37" if ready else "#b3261e",
                     font=("Segoe UI", 11, "bold"),
                     text="%s: %s" % (name, "ready" if ready
                                      else "not ready yet")).pack(anchor="w")
        tk.Label(self.body, fg="#666", justify="left",
                 text=("The dungeon bot needs none of this, it recognises "
                       "buttons by\ncolour and position.")).pack(anchor="w",
                                                                 pady=(4, 12))

        tk.Button(self.body, text="Diagnostics",
                  command=self._diagnostics).pack(anchor="w")

    # ------------------------------------------------------------------
    def page_skewer(self):
        """Name the twelve ingredient icons of the cooking minigame.

        Same job learn_skewer.py does standalone, and the same crops: the 4x3
        grid is at fixed relative positions, so nothing has to be searched
        for. This page needs the cooking minigame on screen, not the board.
        """
        import skewer

        tk.Label(self.body, justify="left", font=("Segoe UI", 10),
                 text=("The skewer bot plays the cooking minigame and has to "
                       "tell its\ntwelve ingredients apart.\n\n"
                       "Open that minigame in the emulator, press 'Grab a new "
                       "frame'\nbelow, then give every icon a name and save "
                       "it. The names are\nyours to choose, only the twelve "
                       "images matter.")).pack(anchor="w", pady=(6, 8))
        if not self.need_image():
            return

        learned = skewer.load_ingredient_templates(force=True)
        cells = len(skewer.GRID_COLS_FX) * len(skewer.GRID_ROWS_FY)
        tk.Label(self.body, fg="#666",
                 text="%d icon(s) learned so far, %d cells to fill"
                      % (len(learned), cells)).pack(anchor="w", pady=(0, 6))
        if len(learned) > cells:
            tk.Label(self.body, justify="left", fg="#b3261e",
                     text=("There are more icons than cells. If two of them "
                           "are the same\ningredient under different names, "
                           "the matcher has no margin\nbetween them and "
                           "refuses to name that cell at all.\n"
                           "Save all twelve again to clean this up.")
                     ).pack(anchor="w", pady=(0, 6))

        buttons = tk.Frame(self.body)
        buttons.pack(anchor="w", pady=(0, 8))
        tk.Button(buttons, text="Save all twelve",
                  command=self._save_all_skewer).pack(side="left")
        tk.Button(buttons, text="Test match",
                  command=self._test_skewer).pack(side="left", padx=8)
        tk.Label(buttons, fg="#666",
                 text="  reads every cell back, each should name itself"
                 ).pack(side="left")

        grid = tk.Frame(self.body)
        grid.pack(anchor="w")
        self.skewer_cells = []
        i = 0
        for fy in skewer.GRID_ROWS_FY:
            for fx in skewer.GRID_COLS_FX:
                box = tk.Frame(grid, padx=6, pady=6, relief="groove", bd=1)
                box.grid(row=i // len(skewer.GRID_COLS_FX),
                         column=i % len(skewer.GRID_COLS_FX))
                crop = skewer.crop_rel(self.frame_img, fx, fy,
                                       skewer.GRID_CELL_FW, skewer.GRID_CELL_FH)
                photo = to_photo(crop, scale=3)
                if photo:
                    self.photos.append(photo)
                    tk.Label(box, image=photo).pack()
                # What is already learned wins over the placeholder list.
                # Offering INGREDIENT_NAMES to someone whose icons carry
                # their own names is exactly how one "Save all twelve" turns
                # into four duplicate ingredients.
                starter = None
                if learned:
                    starter, _val = skewer.match_icon(crop, learned)
                if not starter:
                    starter = (skewer.INGREDIENT_NAMES[i]
                               if i < len(skewer.INGREDIENT_NAMES)
                               else "ingredient_%d" % i)
                var = tk.StringVar(value=starter)
                tk.Entry(box, textvariable=var, width=14).pack(pady=2)
                match = tk.Label(box, text="", fg="#555")
                match.pack()
                tk.Button(box, text="Save", width=10,
                          command=lambda fx=fx, fy=fy, v=var:
                          self._save_skewer_icon(fx, fy, v)).pack(pady=2)
                self.skewer_cells.append({"fx": fx, "fy": fy, "var": var,
                                          "match": match})
                i += 1

    def page_icon(self):
        """Learn the game's icon by clicking it on a picture of the screen.

        This is what lets the bot start the game without ADB and without
        LDPlayer's own tool: it finds this picture on the emulator's home
        screen and clicks it, which works on any emulator.
        """
        import launcher

        tk.Label(self.body, justify="left", font=("Segoe UI", 10),
                 text=("So the bot can start the game itself, it needs to "
                       "know what the icon\nlooks like.\n\n"
                       "Go to the emulator's home screen, where the game's "
                       "icon is visible,\npress 'Grab a new frame' below, "
                       "then click the icon in the picture.")
                 ).pack(anchor="w", pady=(6, 8))
        if not self.need_image():
            return

        known = launcher.find_icon(self.frame_img) if launcher.have_icon() else None
        if known:
            tk.Label(self.body, justify="left",
                     fg="#1a7f37" if known["ok"] else "#b3261e",
                     text=("Already learned. On this frame it matches %.2f "
                           "(runner-up %.2f) -- %s"
                           % (known["score"], known["second"],
                              "found" if known["ok"] else "not convincing "
                              "right now, is the home screen showing?"))
                     ).pack(anchor="w", pady=(0, 8))
        else:
            tk.Label(self.body, fg="#8a5b00",
                     text="Not learned yet.").pack(anchor="w", pady=(0, 8))

        # The frame is taller than the window, so it is shown scaled and the
        # click is scaled back. Keeping the factor here rather than guessing
        # it later is what makes the crop land where the eye did.
        h, w = self.frame_img.shape[:2]
        shown_w = 330
        factor = shown_w / float(w)
        small = cv2.resize(self.frame_img,
                           (shown_w, max(1, int(round(h * factor)))),
                           interpolation=cv2.INTER_AREA)
        photo = to_photo(small, scale=1)
        if photo is None:
            tk.Label(self.body, fg="#b3261e",
                     text="Could not show the frame.").pack(anchor="w")
            return
        self.photos.append(photo)
        label = tk.Label(self.body, image=photo, cursor="crosshair")
        label.pack(anchor="w", pady=4)
        label.bind("<Button-1>",
                   lambda e, f=factor: self._learn_icon(e.x / f, e.y / f))

        tk.Label(self.body, fg="#666", justify="left",
                 text=("Click the centre of the game's icon above. A square "
                       "around that point\nis saved as the template.")
                 ).pack(anchor="w")

    def _learn_icon(self, x, y):
        """Cut a square around the clicked point and keep it."""
        import launcher

        h, w = self.frame_img.shape[:2]
        # An icon is roughly a tenth of the screen wide on every emulator
        # home screen looked at; the square is a little tighter so a
        # neighbouring icon cannot creep in.
        half = max(16, int(round(0.055 * w)))
        x, y = int(round(x)), int(round(y))
        x1, y1 = max(0, x - half), max(0, y - half)
        x2, y2 = min(w, x + half), min(h, y + half)
        crop = self.frame_img[y1:y2, x1:x2].copy()
        if crop.size == 0:
            self.say("that point is outside the picture")
            return
        launcher.save_icon(crop, w)
        launcher.forget_icon()
        found = launcher.find_icon(self.frame_img)
        if found and found["ok"]:
            self.say("icon saved, and found again at %.2f" % found["score"])
        else:
            self.say("icon saved, but it does not match itself convincingly. "
                     "Try clicking the centre of the icon.")
        self.show()

    def _skewer_crop(self, fx, fy):
        import skewer
        return skewer.crop_rel(self.frame_img, fx, fy,
                               skewer.GRID_CELL_FW, skewer.GRID_CELL_FH)

    def _save_skewer_icon(self, fx, fy, var):
        import skewer
        name = var.get().strip()
        if not name:
            self.say("type a name first")
            return
        skewer.save_ingredient_template(name, self._skewer_crop(fx, fy))
        self.say("%s saved" % name)

    def _save_all_skewer(self):
        import skewer
        names = [c["var"].get().strip() for c in self.skewer_cells]
        if not all(names):
            messagebox.showwarning("Name missing",
                                   "Every icon needs a name before saving.")
            return
        # A repeated name is not a small mistake: the second save overwrites
        # the first, and the bot ends up with eleven icons for twelve cells.
        if len(set(names)) != len(names):
            messagebox.showwarning(
                "Names repeat",
                "Two icons share a name, so one would overwrite the other.\n"
                "Give every icon its own name.")
            return
        for cell, name in zip(self.skewer_cells, names):
            skewer.save_ingredient_template(name,
                                            self._skewer_crop(cell["fx"],
                                                              cell["fy"]))
        self.say("%d icons saved" % len(names))
        self._retire_extra_icons(names)
        self.show()

    def _retire_extra_icons(self, keep):
        """Offer to move aside icons that are not on this grid.

        An icon left over under an old name is not harmless: it is a second
        copy of an ingredient that is now also saved under a new one, and two
        identical candidates leave match_icon no margin, so it names neither.
        Moved, never deleted -- the player may have meant to keep them.
        """
        import shutil

        import skewer

        learned = skewer.load_ingredient_templates(force=True)
        extra = sorted(set(learned) - set(keep))
        if not extra:
            return
        if not messagebox.askyesno(
                "More icons than cells",
                "There are now %d icons for %d cells.\n\n"
                "These %d are not on this grid:\n  %s\n\n"
                "If any of them is the same ingredient as one you just "
                "saved, the matcher cannot tell the two apart and will "
                "refuse to name that cell.\n\n"
                "Move them out of the way?"
                % (len(learned), len(keep), len(extra), ", ".join(extra))):
            return
        folder = userdata.templates_dir()
        target = os.path.join(folder, "replaced")
        os.makedirs(target, exist_ok=True)
        moved = 0
        for name in extra:
            source = os.path.join(folder, "skewer_" + name + ".png")
            if os.path.exists(source):
                shutil.move(source, os.path.join(target,
                                                 "skewer_" + name + ".png"))
                moved += 1
        skewer.forget_ingredient_templates()
        self.say("%d icons saved, %d moved to %s" % (len(keep), moved, target))

    def _test_skewer(self):
        """Read every cell back against what was saved. Nothing is trusted
        because it was written; it counts once it reads back as itself.

        Judged against the typed name only where that name was actually
        learned. The boxes pre-fill with skewer.INGREDIENT_NAMES, which are
        placeholders -- marking a cell wrong because the reading disagrees
        with a name nobody ever saved would flag correct cells as broken.
        """
        import skewer
        templates = skewer.load_ingredient_templates(force=True)
        if not templates:
            self.say("nothing learned yet, save the icons first")
            return
        wrong, unjudged = 0, 0
        for cell in self.skewer_cells:
            name, val = skewer.match_icon(self._skewer_crop(cell["fx"],
                                                            cell["fy"]),
                                          templates)
            typed = cell["var"].get().strip()
            if typed not in templates:
                colour = "#555"  # nothing to compare against, not a verdict
                unjudged += 1
            elif name == typed:
                colour = "#1a7f37"
            else:
                colour = "#b3261e"
                wrong += 1
            cell["match"].configure(text="%s  %.2f" % (name or "?", val),
                                    fg=colour)
        note = ("%d cell(s) disagree with the name in the box" % wrong
                if wrong else "every judged cell names itself")
        if unjudged:
            note += ", %d not judged (that name is not learned)" % unjudged
        self.say("matched against %d learned icon(s), %s"
                 % (len(templates), note))

    # ------------------------------------------------------------------
    def _set_only(self, value):
        active = learning.set_only_learned(value)
        self.say("shipped images %s"
                 % ("are ignored" if active else "are used"))
        self.show()

    def _diagnostics(self):
        """Switches that are useful to us and confusing to a player."""
        dlg = tk.Toplevel(self)
        dlg.title("Diagnostics")
        dlg.configure(padx=20, pady=16)
        dlg.transient(self)
        tk.Label(dlg, text="Diagnostics", font=("Segoe UI", 13, "bold")
                 ).pack(anchor="w")
        tk.Label(dlg, justify="left", fg="#444", pady=8,
                 text=("These are for testing the setup itself, not for "
                       "playing.")).pack(anchor="w")
        var = tk.BooleanVar(value=learning.only_learned())
        tk.Checkbutton(dlg, variable=var, text="Ignore shipped images",
                       command=lambda: (self._set_only(var.get()),
                                        dlg.destroy())).pack(anchor="w")
        tk.Label(dlg, justify="left", fg="#666",
                 text=("Pretends the shipped images are not there, so you can "
                       "walk through\nsetup the way a new player sees it. "
                       "While this is on, the program\nreports itself as not "
                       "set up.")).pack(anchor="w", padx=(24, 0))
        tk.Button(dlg, text="Close", width=12,
                  command=dlg.destroy).pack(anchor="e", pady=(14, 0))

    def page_counters(self):
        tk.Label(self.body, justify="left", font=("Segoe UI", 10),
                 text=("Type in what the counters currently show. That yields\n"
                       "labelled digit images. A region is only learned when the\n"
                       "number of characters matches the number you typed,\n"
                       "otherwise the mapping would be shifted.")).pack(anchor="w", pady=(6, 8))
        if not self.need_frame():
            return

        tk.Button(self.body, text="Learn the numbers",
                  command=self._do_counters).pack(anchor="w", pady=(0, 8))
        rows = tk.Frame(self.body)
        rows.pack(anchor="w")
        self.counter_vars = {}
        for i, key in enumerate(COUNTER_ORDER):
            roi = self.calib["roi_" + key]
            x, y, w, h = roi
            crop = self.frame_img[max(0, y):y + h, max(0, x):x + w]
            photo = to_photo(crop, scale=2)
            if photo:
                self.photos.append(photo)
                tk.Label(rows, image=photo).grid(row=i, column=0, padx=4, pady=2)
            tk.Label(rows, text=COUNTER_LABEL[key], width=14,
                     anchor="w").grid(row=i, column=1, sticky="w")
            read_ok = vision.read_number(self.frame_img, "roi_" + key, self.calib)
            var = tk.StringVar(value="" if read_ok is None else str(read_ok))
            self.counter_vars[key] = var
            tk.Entry(rows, textvariable=var, width=10).grid(row=i, column=2)
            tk.Label(rows, text="read %s" % ("nothing" if read_ok is None
                                             else read_ok),
                     fg="#666").grid(row=i, column=3, sticky="w", padx=8)

    def _do_counters(self):
        if self.calib is None or not getattr(self, "counter_vars", None):
            self.say("no frame, press Grab a new frame first")
            return
        values = {}
        for key, var in self.counter_vars.items():
            text = var.get().strip().replace(".", "").replace(",", "")
            if text.isdigit():
                values[key] = int(text)
        learned, report = learning.learn_digits(self.frame_img, self.calib,
                                                values)
        msg = "\n".join("%s, %s" % (COUNTER_LABEL.get(k, k), m) for k, m in report)
        messagebox.showinfo("Numbers learned",
                            "%d digit images learned.\n\n%s" % (learned, msg))
        self.show()

    # ------------------------------------------------------------------
    def page_objects(self):
        tk.Label(self.body, justify="left", font=("Segoe UI", 10),
                 text=("The bot could not identify these colourful finds.\n"
                       "Pick what each one is. Detection finds them reliably, it\n"
                       "just does not know which is which.")
                 ).pack(anchor="w", pady=(6, 8))
        if not self.need_frame():
            return

        found = learning.object_candidates(self.frame_img, self.calib)
        if not found:
            tk.Label(self.body, justify="left",
                     text=("Nothing open on the board right now.\n\n"
                           "Either everything is learned already, or there is\n"
                           "nothing lying about. Grab a new frame when power-ups\n"
                           "are visible.")
                     ).pack(anchor="w", pady=10)
            return

        for cand in found:
            row = tk.Frame(self.body, pady=4)
            row.pack(anchor="w", fill="x")
            photo = to_photo(cand["crop"], scale=2)
            if photo:
                self.photos.append(photo)
                tk.Label(row, image=photo).pack(side="left", padx=(0, 10))
            tk.Label(row, text="row %d column %d" % (cand["row"] + 1,
                                                    cand["col"] + 1),
                     width=16, anchor="w").pack(side="left")
            box = tk.Frame(row)
            box.pack(side="left")
            for i, name in enumerate(["ticket_orange", "ticket_green",
                                      "ticket_pink", "claw", "paw", "fireball"]):
                tk.Button(box, text=learning.LABELS[name].split(",")[0],
                          width=14,
                          command=lambda n=name, c=cand: self._save_object(n, c)
                          ).grid(row=i // 3, column=i % 3, padx=2, pady=2)

    def _save_object(self, name, cand):
        learning.save_template(name, cand["crop"], self.calib)
        self.say("%s learned" % name)
        self.show()

    # ------------------------------------------------------------------
    def page_pyramid(self):
        tk.Label(self.body, justify="left", font=("Segoe UI", 10),
                 text=("Pick the crop that shows a pyramid.\n"
                       "Sorted by edge energy, the best suggestion comes first.\n"
                       "The bottom row is left out: the wall ledge and the metre\n"
                       "label produce false edges there.")).pack(anchor="w", pady=(6, 8))
        if not self.need_frame():
            return

        cands = learning.pyramid_candidates(self.frame_img, self.calib, limit=6)
        if not cands:
            tk.Label(self.body, text="no suggestions, grab a new frame"
                     ).pack(anchor="w")
            return
        box = tk.Frame(self.body)
        box.pack(anchor="w")
        for i, cand in enumerate(cands):
            photo = to_photo(cand["crop"], scale=2)
            cell = tk.Frame(box, padx=6, pady=6)
            cell.grid(row=0, column=i)
            if photo:
                self.photos.append(photo)
                tk.Label(cell, image=photo).pack()
            tk.Label(cell, text="r%dc%d\nenergy %.1f"
                     % (cand["row"] + 1, cand["col"] + 1, cand["energie"])).pack()
            tk.Button(cell, text="that is it",
                      command=lambda c=cand: self._save_pyramid(c)).pack(pady=4)

    def _save_pyramid(self, cand):
        learning.save_template("pyramid", cand["crop"], self.calib)
        self.say("pyramid learned")
        self.show()

    # ------------------------------------------------------------------
    def page_banner(self):
        tk.Label(self.body, justify="left", font=("Segoe UI", 10),
                 text=("The game shows two error messages the bot has to "
                       "tell apart.\n\n"
                       "  1  Move not possible, after clicking an unreachable "
                       "tile\n"
                       "  2  Resource empty, when paws, claws or fireballs have "
                       "run out\n\n"
                       "Both look the same, only the text differs. Because that "
                       "text reads\ndifferently in every game language, it is "
                       "learned here from your own\nscreen instead of shipped. "
                       "That way it works in any language.")
                 ).pack(anchor="w", pady=(6, 10))
        if not self.need_frame():
            return

        st = learning.status()
        for name, description in learning.BANNER_KINDS.items():
            present = name in st["quellen"] and st["quellen"][name] != "missing"
            frame = tk.Frame(self.body, pady=6)
            frame.pack(anchor="w", fill="x")
            tk.Label(frame, text="learned" if present else "missing",
                     fg="#1a7f37" if present else "#b3261e", width=9,
                     anchor="w").pack(side="left")
            tk.Label(frame, text=description, anchor="w").pack(side="left")

        tk.Label(self.body, justify="left", font=("Segoe UI", 10), pady=8,
                 text=("The wizard can provoke text 1 itself. It clicks "
                       "diagonally next to\nthe figure, which the game does not "
                       "allow. That costs nothing.")).pack(anchor="w")
        tk.Button(self.body, text="Learn text 1, move not possible",
                  width=36, command=self._do_banner).pack(anchor="w", pady=4)

        tk.Label(self.body, justify="left", font=("Segoe UI", 10), pady=8,
                 text=("Text 2 cannot be provoked while the resources are "
                       "still there.\nTwo ways to get it.\n\n"
                       "  Provoke it yourself: try to spend a resource that is "
                       "empty, then\n  press the button here while the message "
                       "is on screen\n"
                       "  Or do nothing: the bot collects it while running and "
                       "stops once,\n  the first time it appears")
                 ).pack(anchor="w")
        tk.Button(self.body, text="Learn text 2 now, message is visible",
                  width=40,
                  command=lambda: self._learn_text("banner_text_insufficient")
                  ).pack(anchor="w", pady=4)

    def _do_banner(self):
        def job():
            try:
                cap = self.ensure_cap()
                img = cap.grab()
                calib = vision.calibrate(img)
                figure = vision.find_figure(img, calib, vision.load_templates())
                if not figure:
                    self.say("figure not found, is the skin right?")
                    return
                cell = learning.diagonal_cell(figure)
                if not cell:
                    self.say("no free diagonal cell, move the figure")
                    return
                x, y = vision.cell_center(calib, *cell)
                cap.tap(x, y)
                import time
                time.sleep(0.7)
                shot = cap.grab()
                names, msg = learning.learn_banner(shot, calib)
                self.say("banner, %s" % (", ".join(names) if names else msg))
            except Exception as err:
                self.say("Error: %s" % err)
            self.after(10, self.show)

        threading.Thread(target=job, daemon=True).start()

    # ------------------------------------------------------------------
    def _learn_text(self, name):
        """Learn a banner text from the current frame, for when the message
        happens to be on screen."""
        try:
            cap = self.ensure_cap()
            img = cap.grab()
            calib = vision.calibrate(img)
            if not vision.banner_visible(img, calib):
                self.say("no banner visible. Provoke the message in the game first, then press this")
                return
            names, message = learning.learn_banner(img, calib, text_name=name)
            self.say("learned: %s" % (", ".join(names) if names else message))
        except Exception as err:
            self.say("Error: %s" % err)
        self.show()

    def page_queue(self):
        paths = learning.queued_unknown()
        tk.Label(self.body, justify="left", font=("Segoe UI", 10),
                 text=("While the bot runs it puts colourful finds it could "
                       "not identify\nhere. Rare types do not show up in a short "
                       "session, so they are\nlearned afterwards rather than "
                       "demanded up front.\n\nOpen cases: %d" % len(paths))
                 ).pack(anchor="w", pady=(6, 8))
        if not paths:
            return
        for path in paths[:8]:
            crop = cv2.imread(path)
            row = tk.Frame(self.body, pady=4)
            row.pack(anchor="w", fill="x")
            photo = to_photo(crop, scale=2)
            if photo:
                self.photos.append(photo)
                tk.Label(row, image=photo).pack(side="left", padx=(0, 10))
            box = tk.Frame(row)
            box.pack(side="left")
            for i, name in enumerate(["ticket_orange", "ticket_green",
                                      "ticket_pink", "claw", "paw", "fireball",
                                      "pyramid"]):
                tk.Button(box, text=name, width=13,
                          command=lambda p=path, n=name: self._label(p, n)
                          ).grid(row=i // 4, column=i % 4, padx=2, pady=2)
            tk.Button(row, text="discard",
                      command=lambda p=path: self._discard(p)).pack(side="left", padx=8)

    def _label(self, path, name):
        learning.label_queued(path, name)
        self.say("%s learned" % name)
        self.show()

    def _discard(self, path):
        for extra in (path, path + ".txt"):
            try:
                os.remove(extra)
            except OSError:
                pass
        self.show()


def step_index(name, order):
    """Step number from a name, matched loosely so callers can say "skewer"."""
    wanted = (name or "").strip().lower()
    for i, step in enumerate(order):
        if step.lower() == wanted:
            return i
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default="",
                    help="set up one bot only: %s"
                         % ", ".join(sorted(BOT_STEPS)))
    ap.add_argument("--step", default="",
                    help="open on this step, e.g. --step skewer")
    ap.add_argument("--note", default="",
                    help="one line explaining why the wizard was opened here")
    args = ap.parse_args()
    _, order = BOT_STEPS.get(args.bot, ("", STEPS))
    app = Wizard(step=step_index(args.step, order), note=args.note,
                 bot=args.bot)
    app.after(200, app.grab)
    app.mainloop()


if __name__ == "__main__":
    main()
