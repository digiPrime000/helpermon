"""
Tk pieces that more than one window needs.

Right now that is one thing: the switch for the mouse-movement pause. It is
here rather than in `guard.py` because guard has to stay importable by a bot
running in a console with no display, and rather than in `app.py` because
more than one window shows it.

It belongs on windows where a bot runs and nowhere else. The setup wizard
does not drive the mouse, so a switch about that there is a control for
something that is not happening in front of you.
"""

import tkinter as tk

import userdata

# How often the switch re-reads the flag. The launcher, the minigame window
# and a bot started from a console are separate processes, so a switch
# flipped in one has to show up in the others without a restart. A second is
# far below noticing and costs one file check.
POLL_MS = 1000

LABEL = "Pause Bot on mouse move"


class MousePauseSwitch(tk.Frame):
    """On/off for the mouse-movement pause, for the top right of a window.

    The state lives in a file, not in this widget: see userdata.mouse_pause.
    So the widget shows what is actually in force rather than what this
    window last set, which is the difference that matters when two windows
    are open at once.
    """

    def __init__(self, parent, bg=None, **kwargs):
        bg = bg or parent.cget("bg")
        tk.Frame.__init__(self, parent, bg=bg, **kwargs)
        self.var = tk.BooleanVar(value=userdata.mouse_pause())
        self.button = tk.Checkbutton(
            self, text=LABEL, variable=self.var, bg=bg, activebackground=bg,
            font=("Segoe UI", 9), command=self._toggle)
        self.button.pack(side="left")
        self._poll()

    def _toggle(self):
        # What comes back is what is now in force, which is not always what
        # was asked for: with no writable data folder the flag cannot be
        # written and the switch has to go back to showing the truth.
        self.var.set(userdata.set_mouse_pause(self.var.get()))

    def _poll(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        now = userdata.mouse_pause()
        if now != self.var.get():
            self.var.set(now)
        self.after(POLL_MS, self._poll)
