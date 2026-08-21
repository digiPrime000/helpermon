"""
Cold start: from a launched game to the dungeon list.

Every case here is a screen that stopped a real run, rebuilt from the
screenshot that showed it. They are reconstructions, not captures -- no image
from the game is stored in this repository.

  login pop-ups     0, 3 and 7 of them, since the number varies by day
  a creeping load   "Now Loading ... Connecting 57.6%", where the only moving
                    things are a progress bar and three dots
  idle rewards      with and without claiming
  Notices           whose Campaigns tab is the same blue button in the same
                    place as Claim
  the exit prompt   which must never be answered with OK

  py test_wake_flow.py
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dungeon as D
import guard

W, H = 799, 1387



def screen(popup=True, seed=0):
    """Game screen, optionally with a pop-up over it."""
    rng = np.random.RandomState(seed)
    img = np.full((H, W, 3), 30, np.uint8)
    img[:, :] = rng.randint(20, 60, 3)
    # the bottom navigation, always there
    cv2.rectangle(img, (0, int(H * 0.93)), (W, H), (40, 35, 30), -1)
    if popup:
        # Each pop-up carries different artwork, as the real ones do -- the
        # Collab card and the Overdrive card share nothing but the button.
        art = tuple(int(c) for c in rng.randint(60, 250, 3))
        cv2.rectangle(img, (int(W * 0.14), int(H * 0.12)),
                      (int(W * 0.86), int(H * 0.85)), art, -1)
        # OK button: wide, blue, centred, low. BGR blue.
        cv2.rectangle(img, (int(W * 0.33), int(H * 0.885)),
                      (int(W * 0.62), int(H * 0.925)), (230, 150, 40), -1)
    return img


with_popup = screen(popup=True)
without = screen(popup=False, seed=3)

ok = D.popup_ok(with_popup)
assert ok is not None, "OK button not found on a pop-up screen"
print("pop-up OK found at fx %.3f fy %.3f, width %.3f"
      % (ok["fx"], ok["fy"], ok["fw"]))
assert 0.40 <= ok["fx"] <= 0.55, ok
assert 0.86 <= ok["fy"] <= 0.95, ok

assert D.popup_ok(without) is None, "found an OK button where there is none"
print("no false OK button on a screen without a pop-up")

# recognise() calls this a battle -- which is exactly why wake_up must not
# treat BATTLE as "hand over".
print("recognise() says: %r" % D.recognise(with_popup)["state"])


# --- wake_up: three pop-ups, then the list --------------------------------
class Sim:
    """Screens in sequence; each accepted tap advances one."""

    def __init__(self, popups):
        self.left = popups
        self.taps = []
        self.done = False

    def grab(self):
        if self.done:
            img = screen(popup=False, seed=9)
            cv2.rectangle(img, (0, 0), (W, 40), (255, 255, 255), -1)
            return img
        return screen(popup=self.left > 0, seed=self.left)

    def tap(self, fx, fy, was=""):
        self.taps.append((round(fx, 3), round(fy, 3), was))
        if self.left > 0:
            self.left -= 1
        else:
            self.done = True


def make_bot(sim, states):
    bot = D.DungeonBot.__new__(D.DungeonBot)
    bot.dry_run = False
    bot.log = lambda t: log.append(str(t))
    bot.control = guard.Stop()
    bot.pause_long = 0.0
    bot.pause_short = 0.0
    bot.grab = sim.grab
    bot.tap = sim.tap
    bot.open_list = lambda: True
    bot._states = states
    bot.saved = []
    bot.save_unknown = lambda img, tag: bot.saved.append(tag)
    return bot


for popups in (0, 3, 7):
    log = []
    sim = Sim(popups)
    bot = make_bot(sim, None)
    # the list appears once every pop-up is gone
    real_recognise = D.recognise
    D.recognise = lambda img: {"state": D.LIST if sim.done else real_recognise(img)["state"]}
    try:
        got = bot.wake_up(timeout=30, max_taps=25)
    finally:
        D.recognise = real_recognise
    kinds = [t[2] for t in sim.taps]
    print("%d pop-up(s): reached the list = %s after %d tap(s) %s"
          % (popups, got, len(sim.taps), kinds))
    assert got is True, log[-3:]
    assert len(sim.taps) == popups + 1, sim.taps
    if popups:
        assert all(k == "pop-up OK" for k in kinds[:popups]), kinds

print("wake_up clears however many pop-ups there are, then opens the list")


# --- the real sequence: load, title, load, pop-ups, dungeon --------------
def loading(n):
    """A loading screen: something moves on it."""
    img = np.full((H, W, 3), 20, np.uint8)
    cv2.circle(img, (W // 2, int(H * 0.5) + (n % 4) * 25), 30,
               (240, 240, 240), -1)
    return img


def title():
    """Static, and it wants one touch."""
    img = np.full((H, W, 3), 90, np.uint8)
    cv2.rectangle(img, (100, 400), (700, 700), (200, 160, 60), -1)
    return img


class Journey:
    """load 8 frames, title, load 6, three pop-ups, then the list."""

    def __init__(self):
        self.phase = "loading1"
        self.n = 0
        self.popups = 3
        self.taps = []

    def grab(self):
        self.n += 1
        if self.phase == "loading1":
            if self.n > 8:
                self.phase = "title"
            return loading(self.n)
        if self.phase == "title":
            return title()
        if self.phase == "loading2":
            if self.n > 6:
                self.phase = "popup"
            return loading(self.n)
        if self.phase == "popup":
            return screen(popup=True, seed=self.popups)
        return screen(popup=False, seed=1)   # main screen, and later the list

    def tap(self, fx, fy, was=""):
        self.taps.append(was)
        if self.phase == "title":
            self.phase, self.n = "loading2", 0
        elif self.phase == "popup":
            self.popups -= 1
            if self.popups <= 0:
                # Pop-ups gone, main screen showing. The dungeon tab still
                # has to be pressed, as it does in the real game.
                self.phase = "main"
        elif self.phase == "main":
            self.phase = "done"


log = []
j = Journey()
bot = make_bot(j, None)
real_recognise = D.recognise
D.recognise = lambda img: {"state": D.LIST if j.phase == "done"
                           else real_recognise(img)["state"]}
try:
    got = bot.wake_up(timeout=60, max_taps=40)
finally:
    D.recognise = real_recognise

print("full journey: reached the list = %s, taps %s" % (got, j.taps))
assert got is True, log[-3:]
# one touch for the title screen, one OK per pop-up, one for the dungeon tab
assert j.taps.count("pop-up OK") == 3, j.taps
# one touch for the title, one OK per pop-up, one for the dungeon tab
assert j.taps == (["touch to start / dungeon tab"] + ["pop-up OK"] * 3
                  + ["touch to start / dungeon tab"]), j.taps
assert not any("never changed" in t for t in log), log
print("no tap was wasted on a loading screen")


# --- the screen that actually broke it: a long, barely-moving load -------
# "Now Loading ... Connecting 57.6%". Everything that moves on it is tiny:
# measured, a couple of hundred pixels out of 1.1 million.
def connecting(pct):
    img = np.full((H, W, 3), 60, np.uint8)
    cv2.rectangle(img, (60, 200), (W - 60, 900), (150, 190, 220), -1)
    # the progress bar, and nothing else of any size
    cv2.rectangle(img, (90, 1240), (90 + int(330 * pct), 1252),
                  (250, 200, 60), -1)
    cv2.putText(img, "%.1f%%" % (pct * 100), (330, 1300),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return img


changed = float(np.count_nonzero(cv2.absdiff(
    cv2.cvtColor(connecting(0.50), cv2.COLOR_BGR2GRAY),
    cv2.cvtColor(connecting(0.52), cv2.COLOR_BGR2GRAY)) > 30))
print("a 2%% step of that loading bar changes %.0f px = %.4f%% of the frame"
      % (changed, 100.0 * changed / (W * H)))


class SlowLoad:
    """Loads for 40 polls, then the main screen appears."""

    def __init__(self):
        self.n = 0
        self.taps = []

    def grab(self):
        self.n += 1
        if self.n <= 40:
            return connecting(0.4 + self.n * 0.012)
        return screen(popup=False, seed=1)

    def tap(self, fx, fy, was=""):
        self.taps.append(was)


log = []
sim = SlowLoad()
bot = make_bot(sim, None)
real_recognise = D.recognise
D.recognise = lambda img: {"state": D.LIST if sim.taps and sim.n > 41
                           else real_recognise(img)["state"]}
try:
    got = bot.wake_up(timeout=40)
finally:
    D.recognise = real_recognise
print("long slow load: reached the list = %s, %d tap(s)" % (got, len(sim.taps)))
assert got is True, log[-3:]
assert not any("has changed for" in t for t in log), log
print("a load that creeps is not mistaken for a stuck screen")


# --- the idle-rewards dialog ---------------------------------------------
# Its Claim button sits at about 0.60, 0.75 -- above the band a dismiss
# button lives in, which is why popup_ok must not match it.
def idle_rewards():
    """Claim, blue, with the violet Extra Rewards button beside it."""
    img = screen(popup=False, seed=4)
    cv2.rectangle(img, (int(W * 0.17), int(H * 0.21)),
                  (int(W * 0.79), int(H * 0.82)), (120, 60, 20), -1)
    cv2.rectangle(img, (int(W * 0.50), int(H * 0.725)),
                  (int(W * 0.72), int(H * 0.775)), (230, 150, 40), -1)
    # Extra Rewards, violet, immediately left of it
    cv2.rectangle(img, (int(W * 0.24), int(H * 0.725)),
                  (int(W * 0.47), int(H * 0.775)), (200, 50, 130), -1)
    return img


def notices():
    """The Notices dialog. Its Campaigns tab is blue, the same size, in the
    same band -- and there is no violet button anywhere."""
    img = screen(popup=False, seed=6)
    cv2.rectangle(img, (int(W * 0.15), int(H * 0.21)),
                  (int(W * 0.81), int(H * 0.76)), (60, 40, 25), -1)
    cv2.rectangle(img, (int(W * 0.38), int(H * 0.715)),
                  (int(W * 0.58), int(H * 0.752)), (230, 150, 40), -1)
    return img


card = idle_rewards()
assert D.popup_ok(card) is None, "a Claim button must not read as dismiss"
claim = D.claim_button(card)
assert claim is not None, "Claim button not found"
print("Claim found at fx %.3f fy %.3f; popup_ok correctly ignores it"
      % (claim["fx"], claim["fy"]))

# The one that broke it: Campaigns must not read as Claim.
note = notices()
assert D.claim_button(note) is None, "the Campaigns tab still reads as Claim"
print("the Notices dialog's Campaigns tab is correctly not taken for Claim")


class Idle:
    """The dialog is up; back key or Claim both close it."""

    def __init__(self):
        self.open = True
        self.taps = []
        self.backs = 0

    def grab(self):
        return idle_rewards() if self.open else screen(popup=False, seed=1)

    def tap(self, fx, fy, was=""):
        self.taps.append(was)
        if self.open and was == "Claim":
            self.open = False


def run_idle(claim_rewards):
    sim = Idle()
    bot = make_bot(sim, None)

    def fake_back(only_if_dialog=True):
        sim.backs += 1
        sim.open = False
        return True

    bot.back = fake_back
    bot.cap = sim
    real = D.recognise
    D.recognise = lambda img: {"state": D.DIALOG if sim.open else D.LIST}
    try:
        got = bot.wake_up(timeout=20, claim_rewards=claim_rewards)
    finally:
        D.recognise = real
    return got, sim


log = []
got, sim = run_idle(claim_rewards=False)
print("claim off: list=%s, back key used %d time(s), taps %s"
      % (got, sim.backs, sim.taps))
assert got is True and sim.backs == 1 and "Claim" not in sim.taps

log = []
got, sim = run_idle(claim_rewards=True)
print("claim on : list=%s, back key used %d time(s), taps %s"
      % (got, sim.backs, sim.taps))
assert got is True and sim.backs == 0 and sim.taps == ["Claim"]
print("Claim is pressed only when it was asked for")


# --- the Notices dialog: nothing here is pressable, so close it ----------
class Notices:
    """Taps achieve nothing; only the back key closes it."""

    def __init__(self):
        self.open = True
        self.taps = []
        self.backs = 0

    def grab(self):
        return notices() if self.open else screen(popup=False, seed=1)

    def tap(self, fx, fy, was=""):
        self.taps.append(was)          # deliberately changes nothing


sim = Notices()
log = []
bot = make_bot(sim, None)


def fake_back(only_if_dialog=True):
    sim.backs += 1
    sim.open = False
    return True


bot.back = fake_back
bot.cap = sim
real = D.recognise
# The worst case: the game does not even report it as a dialog.
D.recognise = lambda img: {"state": D.LIST if not sim.open else D.UNKNOWN}
try:
    got = bot.wake_up(timeout=25, claim_rewards=True)
finally:
    D.recognise = real
print("Notices: list=%s, taps %s, back key %d time(s)"
      % (got, sim.taps, sim.backs))
assert got is True, log[-3:]
assert "Claim" not in sim.taps, sim.taps
assert sim.backs >= 1, "never tried closing it"
print("a tap that achieves nothing leads to the back key, not to repetition")


# --- "Exit the game?" must never be answered with OK ----------------------
# Measured off the real dialog: grey Cancel at 0.383, blue OK at 0.561. They
# are not symmetric about 0.5, so mirroring OK lands between them, on the
# dialog's blue -- which used to read as the pink of the party dialog, whose
# answer is OK, which closes the game.
def exit_dialog(pink_cancel=False):
    img = np.full((H, W, 3), 40, np.uint8)
    cv2.rectangle(img, (int(W * 0.18), int(H * 0.43)),
                  (int(W * 0.77), int(H * 0.67)), (150, 90, 30), -1)  # blue
    cancel = (200, 60, 210) if pink_cancel else (170, 170, 170)
    cv2.rectangle(img, (int(W * 0.31), int(H * 0.63)),
                  (int(W * 0.46), int(H * 0.665)), cancel, -1)
    cv2.rectangle(img, (int(W * 0.49), int(H * 0.63)),
                  (int(W * 0.63), int(H * 0.665)), (230, 150, 40), -1)  # OK
    return img


ok_button = {"fx": 0.561, "fy": 0.647}
kind = D.confirm_kind(exit_dialog(pink_cancel=False), ok_button)
print("grey Cancel -> %r" % kind)
assert kind == "beenden", "an exit dialog read as a party dialog"

kind = D.confirm_kind(exit_dialog(pink_cancel=True), ok_button)
print("pink Cancel -> %r" % kind)
assert kind == "party", "the party dialog is no longer recognised"


# and wake_up must cancel it rather than press OK
class ExitTrap:
    """A static title screen. The back key raises the exit prompt."""

    def __init__(self):
        self.exit_open = False
        self.taps = []
        self.done = False

    def grab(self):
        if self.done:
            return screen(popup=False, seed=1)
        return exit_dialog() if self.exit_open else title()

    def tap(self, fx, fy, was=""):
        self.taps.append((was, round(fx, 3)))
        if self.exit_open:
            # Cancel is left of centre; OK would be right of it.
            assert fx < 0.5, "pressed OK on the exit dialog"
            self.exit_open = False
            return
        # A tap on the title screen that changes nothing -- which is what
        # made the loop reach for the back key in the first place. It takes
        # three to get through, so the whole ladder is walked: the dungeon
        # tab, then a tap high up, then the back key, which is the one that
        # springs the trap.
        self.title_taps = getattr(self, "title_taps", 0) + 1
        if self.title_taps >= 3:
            self.done = True


sim = ExitTrap()
log = []
bot = make_bot(sim, None)
bot.cap = sim


def raise_exit(only_if_dialog=True):
    sim.exit_open = True
    return True


bot.back = raise_exit
real = D.recognise
D.recognise = lambda img: {
    "state": (D.EXIT if sim.exit_open else (D.LIST if sim.done else D.UNKNOWN)),
    "exit_ok": ok_button}
try:
    got = bot.wake_up(timeout=25)
finally:
    D.recognise = real
print("exit trap: list=%s, taps %s" % (got, sim.taps))
assert got is True, log[-3:]
assert any(w == "Cancel, stay in the game" for w, _ in sim.taps), sim.taps
kinds = [w for w, _ in sim.taps]
assert kinds.index("neutral") < kinds.index("Cancel, stay in the game"), kinds
print("the exit prompt is cancelled, never confirmed, and the harmless tap "
      "was tried before the back key that raised it")


# --- the rewards dialog must not be taken for an exit prompt -------------
# Claim is blue, fx 0.597, width 0.229, fy 0.746. The exit dialog's OK is
# looked for at 0.61 +- 0.07, width 0.12-0.24, fy 0.50-0.75 -- Claim fits all
# of it. Mistaking them puts the mirrored "Cancel" at 0.403, inside Extra
# Rewards, which watches an advert.
card = idle_rewards()
state = D.recognise(card)["state"]
print("idle rewards reads as %r" % state)
assert state != D.EXIT, "the rewards dialog still reads as an exit prompt"

# and the exit dialog itself must still be recognised
ex = exit_dialog()
assert D.claim_button(ex) is None, "an exit dialog must have no Claim pair"
print("the real exit dialog still has no Claim pair, so the veto misses it")


class Rewards:
    """The rewards dialog. Anything tapped right of centre is Claim; left of
    it is Extra Rewards, which must never be touched."""

    def __init__(self):
        self.open = True
        self.taps = []
        self.backs = 0

    def grab(self):
        return idle_rewards() if self.open else screen(popup=False, seed=1)

    def tap(self, fx, fy, was=""):
        self.taps.append((was, round(fx, 3)))
        if self.open and 0.68 <= fy <= 0.82:
            assert fx > 0.5, "tapped Extra Rewards at fx %.3f" % fx


sim = Rewards()
log = []
bot = make_bot(sim, None)
bot.cap = sim


def close_it(only_if_dialog=True):
    sim.backs += 1
    sim.open = False
    return True


bot.back = close_it
real = D.recognise
D.recognise = lambda img: ({"state": D.LIST} if not sim.open
                           else real(img))
try:
    got = bot.wake_up(timeout=25, claim_rewards=False)
finally:
    D.recognise = real
print("rewards dialog: list=%s, back %d, taps %s"
      % (got, sim.backs, sim.taps))
assert got is True, log[-3:]
assert sim.backs >= 1, "never closed the rewards dialog"
print("closed with the back key, and Extra Rewards was never touched")


# --- the reward window that Claim leaves behind ---------------------------
# Claiming does not end the dialog. A window of what was won drops over it,
# says "Tap to close", and the Claim button still shows behind it. Reading
# that leftover Claim as a dialog waiting to be closed sent the back key at
# it in a live run, and the back key there raised the exit prompt.
def reward_window():
    img = idle_rewards()
    cv2.rectangle(img, (0, int(H * 0.33)), (W, int(H * 0.68)),
                  (200, 90, 20), -1)
    return img


assert D.claim_button(reward_window()) is not None,     "the reward window is meant to still show Claim behind it"


class Claimed:
    """Claim, then a reward window that only a tap closes."""

    def __init__(self):
        self.stage = "dialog"
        self.taps = []
        self.backs = 0

    def grab(self):
        if self.stage == "dialog":
            return idle_rewards()
        if self.stage == "reward":
            return reward_window()
        return screen(popup=False, seed=1)

    def tap(self, fx, fy, was=""):
        self.taps.append(was)
        if self.stage == "dialog" and was == "Claim":
            self.stage = "reward"
        elif self.stage == "reward":
            self.stage = "done"


log = []
sim = Claimed()
bot = make_bot(sim, None)
bot.cap = sim


def count_back(only_if_dialog=True):
    sim.backs += 1
    return True


bot.back = count_back
real = D.recognise
D.recognise = lambda img: {"state": D.LIST if sim.stage == "done"
                           else D.UNKNOWN}
try:
    got = bot.wake_up(timeout=40, claim_rewards=True)
finally:
    D.recognise = real
print("after claiming: list=%s, back %d, taps %s" % (got, sim.backs, sim.taps))
assert got is True, log[-3:]
assert "Claim" in sim.taps, sim.taps
assert sim.backs == 0, "the back key was used on the reward window"
print("the reward window is tapped away, and Claim is not pressed twice")
assert sim.taps.count("Claim") == 1, sim.taps


# --- Stage Failed, which greets a cold start ------------------------------
# The red banner from the idle battle, with the Growth Guide panel over it.
# No button on either that this bot knows, and it goes away with one tap.
def stage_failed():
    img = screen(popup=False, seed=8)
    cv2.putText(img, "Stage", (int(W * 0.30), int(H * 0.13)),
                cv2.FONT_HERSHEY_SIMPLEX, 2.0, (40, 40, 220), 6)
    cv2.putText(img, "Failed...", (int(W * 0.22), int(H * 0.19)),
                cv2.FONT_HERSHEY_SIMPLEX, 2.0, (40, 40, 220), 6)
    # the Growth Guide panel: grey, no button anywhere on it
    cv2.rectangle(img, (int(W * 0.15), int(H * 0.21)),
                  (int(W * 0.81), int(H * 0.84)), (90, 90, 95), -1)
    return img


guide = stage_failed()
assert D.popup_ok(guide) is None, "found an OK button on the Growth Guide"
assert D.claim_button(guide) is None, "found a Claim button on it"
assert D.stage_failed(guide), "the red banner was not recognised"
assert not D.stage_failed(screen(popup=False, seed=3)), "banner where none is"
print("the red banner is recognised by its colour, not by its words")


class Failed:
    """It sits there until something taps it. The back key would raise the
    exit prompt, so pressing it counts as a failure here."""

    def __init__(self):
        self.open = True
        self.taps = []
        self.backs = 0

    def grab(self):
        return stage_failed() if self.open else screen(popup=False, seed=2)

    def tap(self, fx, fy, was=""):
        self.taps.append(was)
        self.open = False


log = []
sim = Failed()
bot = make_bot(sim, None)
bot.cap = sim
bot.back = count_back
real = D.recognise
D.recognise = lambda img: {"state": D.LIST if not sim.open else D.UNKNOWN}
try:
    got = bot.wake_up(timeout=40)
finally:
    D.recognise = real
print("Stage Failed: list=%s, back %d, taps %s" % (got, sim.backs, sim.taps))
assert got is True, log[-3:]
assert sim.backs == 0, "the back key was used on the Stage Failed screen"
print("Stage Failed is tapped away without reaching for the back key")


# --- the auto button ------------------------------------------------------
# Pressed once, on a clear main screen, before the dungeon tab. Never twice:
# it is a toggle. Never while anything is drawn over the screen -- the game
# dims what is behind a dialog, and a dimmed disc breaks up under the blue
# mask, which is what the roundness test measures.
def main_screen(auto=True, dim=False, radius=21):
    """The main screen, with the auto button where the real one sits."""
    img = screen(popup=False, seed=11)
    if auto:
        cx = int(D.POS_AUTO[0] * W)
        cy = int(D.POS_AUTO[1] * H)
        colour = (150, 90, 40) if dim else (230, 150, 40)
        cv2.circle(img, (cx, cy), radius, colour, -1)
        cv2.putText(img, "A", (cx - 7, cy + 7), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 2)
    return img


# The banner is not the bot's business -- the stage restarts by itself --
# except that any click dismisses it, so a press aimed at the auto button
# would be swallowed by it. It has to be left alone.
def failed_over_main():
    img = main_screen()
    cv2.putText(img, "Stage Failed", (int(W * 0.12), int(H * 0.17)),
                cv2.FONT_HERSHEY_SIMPLEX, 2.6, (40, 40, 220), 14)
    return img


assert D.stage_failed(failed_over_main()), "banner over the main screen missed"
assert D.auto_button(failed_over_main()) is not None,     "the button is still plainly there, which is why colour alone is not enough"

found = D.auto_button(main_screen())
assert found is not None, "auto button not found on a clear main screen"
print("auto button found at fx %.3f fy %.3f, width %.3f"
      % (found["fx"], found["fy"], found["fw"]))
assert abs(found["fx"] - D.POS_AUTO[0]) < 0.02, found
assert D.auto_button(main_screen(auto=False)) is None, "found one that is absent"
assert D.auto_button(idle_rewards()) is None, "found one on the rewards dialog"
assert D.auto_button(screen(popup=True)) is None, "found one on a pop-up"
print("and nowhere on a screen that has something else in front")


class Auto:
    """Main screen first, the list once the dungeon tab is tapped."""

    def __init__(self):
        self.taps = []
        self.open = False

    def grab(self):
        return screen(popup=False, seed=2) if self.open else main_screen()

    def tap(self, fx, fy, was=""):
        self.taps.append(was)
        if was != "auto":
            self.open = True


class Failing:
    """Stage Failed over the main screen, until something is clicked."""

    def __init__(self):
        self.taps = []
        self.banner = True
        self.open = False

    def grab(self):
        if self.open:
            return screen(popup=False, seed=2)
        return failed_over_main() if self.banner else main_screen()

    def tap(self, fx, fy, was=""):
        self.taps.append(was)
        if self.banner:
            # Any click at all only clears the banner.
            self.banner = False
        elif was != "auto":
            self.open = True


log = []
sim = Failing()
bot = make_bot(sim, None)
bot.cap = sim
bot.press_auto = D.DungeonBot.press_auto.__get__(bot)
bot._auto_patch = D.DungeonBot._auto_patch
real = D.recognise
D.recognise = lambda img: {"state": D.LIST if sim.open else D.UNKNOWN}
try:
    got = bot.wake_up(timeout=40, start_auto=True)
finally:
    D.recognise = real
print("Stage Failed first: list=%s, taps %s" % (got, sim.taps))
assert got is True, log[-3:]
assert sim.taps[0] == "neutral", ("the banner should be tapped away on "
                                  "purpose, got %s" % sim.taps)
assert sim.taps.count("auto") == 1, sim.taps
assert sim.taps.index("auto") == 1, ("auto has to follow the banner tap "
                                     "straight away, got %s" % sim.taps)
print("the banner is tapped away first, then auto goes once")


for want in (True, False):
    log = []
    sim = Auto()
    bot = make_bot(sim, None)
    bot.cap = sim
    bot.press_auto = D.DungeonBot.press_auto.__get__(bot)
    bot._auto_patch = D.DungeonBot._auto_patch
    real = D.recognise
    D.recognise = lambda img: {"state": D.LIST if sim.open else D.UNKNOWN}
    try:
        got = bot.wake_up(timeout=30, start_auto=want)
    finally:
        D.recognise = real
    print("start_auto=%-5s -> list %s, taps %s" % (want, got, sim.taps))
    assert got is True, log[-3:]
    assert sim.taps.count("auto") == (1 if want else 0), sim.taps
print("the auto button is pressed once when asked for, and never otherwise")


# --- a screen nothing gets past ------------------------------------------
# The one exit that leaves a person with nothing to go on. It has to keep the
# frame, because that frame is the whole of the next round's evidence.
class Wall:
    """A screen that never changes, whatever is tapped."""

    def __init__(self):
        self.taps = []

    def grab(self):
        return screen(popup=False, seed=5)

    def tap(self, fx, fy, was=""):
        self.taps.append(was)


log = []
sim = Wall()
bot = make_bot(sim, None)
bot.back = lambda only_if_dialog=True: True
freeze, tap_pause = D.FREEZE_WINDOW, D.WAKE_TAP_PAUSE
D.FREEZE_WINDOW, D.WAKE_TAP_PAUSE = 2.0, 0.0
try:
    got = bot.wake_up(timeout=30)
finally:
    D.FREEZE_WINDOW, D.WAKE_TAP_PAUSE = freeze, tap_pause
print("a wall: reached the list = %s, %d tap(s), saved %s"
      % (got, len(sim.taps), bot.saved))
assert got is False, log[-3:]
assert any("has changed for" in t for t in log), log
assert bot.saved == ["wake_stuck"], bot.saved
print("a screen nothing gets past stops the run and keeps the frame")



# --- one vocabulary for two sources ---------------------------------------
# Frames arrive either from screen capture, where LDPlayer's tab bar and
# sidebar are part of the picture, or from ADB, where they are not. Every
# fraction in dungeon.py was measured on the first kind. game_rect answers
# both with the same numbers by handing back the window the game sits in
# rather than the image, and this is the case that proves it: the same screen
# as both kinds of frame has to be read the same way.
def as_device(img):
    """The same screen as ADB delivers it: the game area alone, 1080 x 1920."""
    fx0, fy0, fw, fh = D.GAME_IN_WINDOW
    h, w = img.shape[:2]
    x, y = int(round(fx0 * w)), int(round(fy0 * h))
    crop = img[y:y + int(round(fh * h)), x:x + int(round(fw * w))]
    return cv2.resize(crop, (1080, 1920), interpolation=cv2.INTER_AREA)


dev = as_device(main_screen())
assert abs(dev.shape[1] / float(dev.shape[0]) - D.DEVICE_ASPECT) < 1e-6
rect = D.game_rect(dev)
print("a 1080x1920 ADB frame reads as a window of %d x %d at %d, %d"
      % (rect[2], rect[3], rect[0], rect[1]))
assert rect[0] < 0 and rect[1] < 0, rect
assert rect[2] > 1080 and rect[3] > 1920, rect

# The window frame is left exactly as it was, or window mode changes meaning.
assert D.game_rect(main_screen()) == (0, 0, W, H), D.game_rect(main_screen())

# A point named by the same fraction has to land on the same spot in both.
fx0, fy0, fw, fh = D.GAME_IN_WINDOW
worst = 0.0
for fx, fy in ((0.361, 0.766), (0.5, 0.5), (0.377, 0.957), (0.12, 0.12)):
    # where that fraction sits in the window frame, carried into the crop
    want = (((fx - fx0) / fw) * 1080, ((fy - fy0) / fh) * 1920)
    got = D.to_pixel(dev, fx, fy)
    worst = max(worst, abs(got[0] - want[0]), abs(got[1] - want[1]))
print("fractions land within %.1f device pixels of where they should" % worst)
assert worst < 3.0, worst

found = D.auto_button(dev)
assert found is not None, "auto button lost on an ADB frame"
print("auto button on an ADB frame: fx %.3f fy %.3f against the constant %.3f %.3f"
      % (found["fx"], found["fy"], D.POS_AUTO[0], D.POS_AUTO[1]))
assert abs(found["fx"] - D.POS_AUTO[0]) < 0.02, found
assert abs(found["fy"] - D.POS_AUTO[1]) < 0.02, found

assert D.stage_failed(as_device(failed_over_main())), "banner lost on an ADB frame"
assert not D.stage_failed(dev), "banner where none is, on an ADB frame"

# A window that is not the size the constants were measured at. The chrome
# does not scale with it -- 43 px of sidebar is 5.3 % of an 805 wide window
# and 6.9 % of a 619 wide one -- so the frame has to be stretched back to the
# reference before a fraction means anything. Measured against ADB at both
# sizes; without this the smaller window was read 18 device pixels out.
def resized(img, width):
    """The same screen in a smaller window, chrome kept at its pixel size."""
    left, top, right, bottom = D.WINDOW_CHROME
    game = img[top:img.shape[0] - bottom, left:img.shape[1] - right]
    gw = width - left - right
    gh = int(round(gw / D.DEVICE_ASPECT))
    small = cv2.resize(game, (gw, gh), interpolation=cv2.INTER_AREA)
    out = np.zeros((gh + top + bottom, width, 3), np.uint8)
    out[top:top + gh, left:left + gw] = small
    return out


narrow = resized(main_screen(), 619)
print("a %d x %d window reads as a reference window of %d x %d at %d, %d"
      % (narrow.shape[1], narrow.shape[0], *D.game_rect(narrow)[2:],
         *D.game_rect(narrow)[:2]))
found = D.auto_button(narrow)
assert found is not None, "auto button lost in a resized window"
print("auto button in a resized window: fx %.3f fy %.3f" % (found["fx"], found["fy"]))
assert abs(found["fx"] - D.POS_AUTO[0]) < 0.02, found
assert abs(found["fy"] - D.POS_AUTO[1]) < 0.02, found

win_ok = D.popup_ok(screen(popup=True))
dev_ok = D.popup_ok(as_device(screen(popup=True)))
assert dev_ok is not None, "pop-up OK lost on an ADB frame"
print("pop-up OK: window fx %.3f fy %.3f, ADB fx %.3f fy %.3f"
      % (win_ok["fx"], win_ok["fy"], dev_ok["fx"], dev_ok["fy"]))
assert abs(win_ok["fx"] - dev_ok["fx"]) < 0.01, (win_ok, dev_ok)
assert abs(win_ok["fy"] - dev_ok["fy"]) < 0.01, (win_ok, dev_ok)
print("both sources are read with the same fractions")

print("all cold-start cases as expected")
