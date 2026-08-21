"""
Check the dungeon bot flow offline, no emulator needed.

State sequences are played back and what the bot clicks is counted. That
surfaces endless loops and miscounting without needing a real run. Bugs of
exactly that kind cost several test runs during development.
"""
import cv2
import numpy as np

import dungeon as D


class Sim:
    def __init__(self, sequence, confirm_kind="party"):
        self.confirm_kind = confirm_kind
        self.sequence = list(sequence)
        self.i = 0
        self.clicks = []
        self.messages = []

    def next_state(self, _img=None):
        state = self.sequence[min(self.i, len(self.sequence) - 1)]
        self.i += 1
        def button(w, fy=0.70):
            return {"fx": 0.5, "fy": fy, "fw": w, "fh": 0.05}
        return {
            "state": state,
            "attempt": (button(0.21) if state == "close"
                        else button(0.30) if state == D.DIALOG else None),
            "party": button(0.28, 0.79) if state == D.DIALOG_PARTY else None,
            "ad": button(0.62) if state == D.DIALOG_AD else None,
            "clear": None, "blau": [], "violett": [], "karten": [0.3],
            "giveup": None, "party_voll": 0, "exit_ok": button(0.20),
            # For the party dialog, OK is the correct answer, it ends the
            # dungeon. The exit dialog, in contrast, is cancelled and the
            # flow continues.
            "exit_kind": self.confirm_kind,
        }


def make_bot(sim, **kw):
    bot = D.DungeonBot.__new__(D.DungeonBot)
    bot.dry_run = False
    bot.log = sim.messages.append
    bot.use_ads = True
    bot.max_ads = kw.get("max_ads", 2)
    bot.max_attempts = 6
    bot.max_loops = 14
    bot.battle_timeout = 1
    bot.start_timeout = 1
    bot.min_battle = kw.get("min_battle", 6)
    bot.patience = 0
    bot.pause_short = bot.pause_long = bot.tick = 0
    bot.device = (1080, 1920)
    bot.stats = {k: 0 for k in ("versuche", "kaempfe", "werbung", "uebersprungen",
                                "unklar", "abgelehnt", "exit_abgefangen")}
    bot.exhausted = set()
    bot.control = D.guard.Stop()
    bot.max_minutes = 0
    bot.deadline = None
    bot._saved = 0
    bot.debugdir = "/tmp"
    bot.entries = 7
    bot.visible_at_bottom = 5
    bot.swipes = 1
    bot.grab = lambda: "bild"
    bot.tap = lambda fx, fy, was="": sim.clicks.append(was)
    bot.back = lambda only_if_dialog=True, leaving_dungeon=False: True
    bot.return_to_list = lambda tries=5: True
    bot.dialog_settled = lambda tries=2, pause=None: sim.next_state()
    bot.wait_dialog_gone = lambda t: kw.get("attempt_wirkt", False)
    bot.wait_dialog_back = lambda t: sim.next_state()
    bot.dismiss_confirm = lambda info=None, leaving_dungeon=False: None
    bot.save_unknown = lambda img, tag: None
    bot.label_of = lambda i, l: "Test"
    return bot


def run_case(sequence, name, expected_ads=None, **kw):
    sim = Sim(sequence)
    orig_rec, orig_cards = D.recognise, D.list_cards
    D.recognise = sim.next_state
    D.list_cards = lambda img, with_size=False: ([(0.3, 0.12)] if with_size
                                                 else [0.3])
    try:
        bot = make_bot(sim, **kw)
        bot.play_entry(0, "oben")
    finally:
        D.recognise, D.list_cards = orig_rec, orig_cards
    ad_clicks = sum(1 for k in sim.clicks if k == "Werbung")
    good = expected_ads is None or ad_clicks == expected_ads
    print("%-44s ad clicks %d%s" % (
        name, ad_clicks,
        "" if expected_ads is None else
        "  expected %d  %s" % (expected_ads, "ok" if good else "FAILED")))
    return good, ad_clicks, sim


def selection_cases():
    """The short-name selection must act on the right cards.

    What matters is that numbers refer to the overall list, not cards in the
    current view. Counted from the bottom, the first visible card sits at
    total minus visible.
    """
    cases = [
        (None, [], "no selection", [(0, "oben"), (4, "unten")], [True, True]),
        (None, [0], "skip apocalymon", [(0, "oben"), (1, "oben")], [False, True]),
        ([0, 4], [], "only apocalymon and network",
         [(0, "oben"), (1, "oben"), (2, "unten")], [True, False, True]),
        (None, [5], "skip metalsea", [(3, "unten"), (2, "unten")], [False, True]),
    ]
    ok = 0
    for only, skip, name, cards, expected in cases:
        bot = D.DungeonBot.__new__(D.DungeonBot)
        bot.entries = 7
        bot.visible_at_bottom = 5
        bot.only = set(only) if only else None
        bot.skip = set(skip)
        got = [bot.is_selected(i, label) for i, label in cards]
        good = got == expected
        ok += good
        details = ", ".join(
            "%s %s" % (D.dungeon_label(i, label == "unten", 7, 5), g)
            for (i, label), g in zip(cards, got))
        print("  %-30s %s   %s" % (name, "ok" if good else "FAILED", details))
    return ok, len(cases)


def party_panel(filled=(False, True, False)):
    """The dungeon dialog with its three party slots.

    Rebuilt from a real frame, not captured from one. What matters is the
    thing that fooled the reader: the panel's own bright edge sits just to
    the right of the third slot, and a crop that reaches it measures
    contrast that is the panel, not a team-mate.
    """
    h, w = 1390, 805
    img = np.full((h, w, 3), 18, np.uint8)
    # the panel, with a bright border down its right-hand side
    cv2.rectangle(img, (int(0.11 * w), int(0.18 * h)),
                  (int(0.845 * w), int(0.83 * h)), (90, 45, 20), -1)
    cv2.rectangle(img, (int(0.815 * w), int(0.18 * h)),
                  (int(0.845 * w), int(0.83 * h)), (240, 190, 90), -1)
    for fx, occupied in zip(D.PARTY_SLOTS, filled):
        x = int((fx - 0.09) * w)
        y = int((D.PARTY_SLOT_Y - 0.05) * h)
        cv2.rectangle(img, (x, y), (x + int(0.18 * w), y + int(0.10 * h)),
                      (55, 30, 14), -1)
        if occupied:
            # a figure: bright, and nothing like the flat slot behind it
            cv2.circle(img, (x + int(0.09 * w), y + int(0.05 * h)),
                       int(0.03 * w), (230, 230, 240), -1)
            cv2.rectangle(img, (x + int(0.05 * w), y + int(0.06 * h)),
                          (x + int(0.13 * w), y + int(0.09 * h)),
                          (60, 200, 240), -1)
    return img


def party_cases():
    """One team-mate must read as one.

    A live run read two, never searched for a party, and pressed Attempt
    without one -- which does nothing. It then sat in the dialog until it
    gave up.
    """
    ok = 0
    img = party_panel()
    wide = D.PARTY_SLOT_HALF_W
    try:
        D.PARTY_SLOT_HALF_W = 0.10
        fooled = D.party_slots_filled(img)
    finally:
        D.PARTY_SLOT_HALF_W = wide
    got = D.party_slots_filled(img)
    print("  one filled slot: %d with the crop as it is, %d with the wide "
          "crop that reached the panel edge" % (got, fooled))
    ok += got == 1
    ok += fooled > got
    ok += D.party_slots_filled(party_panel((True, True, True))) == 3
    ok += D.party_slots_filled(party_panel((False, False, False))) == 0
    print("  three filled read as 3, none read as 0")
    return ok, 4


def hsv(h, sat, val):
    """One BGR colour from the HSV numbers measured on the real frames."""
    return tuple(int(c) for c in cv2.cvtColor(
        np.uint8([[[h, sat, val]]]), cv2.COLOR_HSV2BGR)[0][0])


# Measured over the Cancel button of real frames of all three prompts:
# the in-game pink at hue 147-149 (89.6% of the button) saturation 147, the
# exit prompt's grey-blue at hue 100-110 saturation 151, and the dialog body
# behind both at hue 103 saturation 233.
#
# 147 and not 145: VIOLET ends at 145, and the two must not touch. Measured
# 0.000 of the real pink button inside the violet range, which is what lets
# a violet neighbour veto the exit reading without vetoing a real prompt.
PINK = hsv(148, 147, 225)
GREY = hsv(103, 151, 159)
BODY = hsv(103, 233, 139)

PINK_OK = {"fx": 0.602, "fy": 0.599, "fw": 0.195, "fh": 0.04}
GREY_OK = {"fx": 0.561, "fy": 0.652, "fw": 0.153, "fh": 0.04}


def prompt(pink=True):
    """A confirmation prompt, built to the real one's proportions.

    Cancel deliberately does NOT sit where the mirror of OK would put it --
    measured 0.34 against a mirror of 0.398 -- because that offset is what
    makes the sample straddle the button and the dialog behind it, and a
    test on a neatly centred button would not exercise the case that failed.
    """
    button, ok = (PINK, PINK_OK) if pink else (GREY, GREY_OK)
    h, w = 1390, 805
    img = np.full((h, w, 3), 20, np.uint8)
    cv2.rectangle(img, (int(0.13 * w), int((ok["fy"] - 0.22) * h)),
                  (int(0.87 * w), int((ok["fy"] + 0.06) * h)), BODY, -1)
    cv2.rectangle(img, (int(0.25 * w), int((ok["fy"] - 0.021) * h)),
                  (int(0.435 * w), int((ok["fy"] + 0.020) * h)), button, -1)
    cv2.rectangle(img, (int((ok["fx"] - ok["fw"] / 2) * w),
                        int((ok["fy"] - 0.021) * h)),
                  (int((ok["fx"] + ok["fw"] / 2) * w),
                   int((ok["fy"] + 0.020) * h)), (230, 150, 40), -1)
    return img


def loading_panel():
    """The dungeon panel before its artwork has arrived.

    Placeholder text, empty slots, and an Attempt button that is narrower
    than the loaded one -- 0.214 against 0.251, measured -- which is what
    slipped it inside the exit prompt's width band. Its violet Clear
    Previous Difficulty sits beside it at the same height, and that pair is
    what no prompt has.
    """
    h, w = 1390, 805
    img = np.full((h, w, 3), 20, np.uint8)
    cv2.rectangle(img, (int(0.09 * w), int(0.24 * h)),
                  (int(0.86 * w), int(0.80 * h)), BODY, -1)
    for fx, colour in ((0.358, hsv(130, 200, 200)), (0.595, (230, 150, 40))):
        cv2.rectangle(img, (int((fx - 0.107) * w), int(0.556 * h)),
                      (int((fx + 0.107) * w), int(0.592 * h)), colour, -1)
    # Find a Party, below and centred, as on the real frame
    cv2.rectangle(img, (int(0.364 * w), int(0.738 * h)),
                  (int(0.589 * w), int(0.774 * h)), (230, 150, 40), -1)
    return img


def confirm_cases():
    """Which prompt is this, and what is the answer.

    Three dialogs wear the same face. The pink pair is identical to the
    pixel, so colour can only rule out the one whose OK ends the session;
    which of the other two it is comes from the caller.
    """
    ok = 0
    # A prompt is a prompt, and a loading panel is not -- read end to end,
    # not by handing confirm_kind a button that recognise never found.
    for img, name, want in ((prompt(True), "pink prompt", D.EXIT),
                            (prompt(False), "grey prompt", D.EXIT),
                            (loading_panel(), "loading panel", D.DIALOG)):
        got = D.recognise(img)["state"]
        print("  %-14s reads as %s" % (name, got))
        ok += got == want
    kind_pink = D.confirm_kind(prompt(True), PINK_OK)
    kind_grey = D.confirm_kind(prompt(False), GREY_OK)
    print("  pink Cancel reads %r, grey Cancel reads %r"
          % (kind_pink, kind_grey))
    ok += kind_pink == "party"
    ok += kind_grey == "beenden"

    sim = Sim([])
    bot = make_bot(sim)
    saved = []
    bot.save_unknown = lambda img, tag: saved.append(tag)
    bot.dismiss_confirm = D.DungeonBot.dismiss_confirm.__get__(bot)

    def answer(kind, **kw):
        sim.clicks = []
        saved[:] = []
        bot.dismiss_confirm({"state": D.EXIT, "exit_ok": PINK_OK,
                             "exit_kind": kind}, **kw)
        return list(sim.clicks), list(saved)

    clicks, _ = answer("party", leaving_dungeon=True)
    print("  pink, on the way out of a dungeon: %s" % clicks)
    ok += clicks == ["OK, Party verlassen"]

    clicks, _ = answer("party")
    print("  pink, anywhere else: %s" % clicks)
    ok += clicks == ["Abbrechen"]

    # Even asked to leave a dungeon, the exit prompt is never confirmed.
    clicks, kept = answer("beenden", leaving_dungeon=True)
    print("  grey, even on the way out of a dungeon: %s, kept %s"
          % (clicks, kept))
    ok += clicks == ["Abbrechen"]
    ok += kept == ["confirm_beenden"]
    return ok, 9


def reopen_cases():
    """A card that drops back to the list gets one more look.

    A live run left Metal Sea with an attempt unspent: the panel closed
    itself after a battle, the list showed, and the dungeon counted as
    finished. Once, though -- a card the game keeps closing must not become
    a loop.
    """
    ok = 0
    # In the list, open the card, one attempt, and the panel is gone again.
    good, _, sim = run_case([D.LIST, D.DIALOG, D.LIST],
                            "card re-opened after dropping to the list",
                            None, attempt_wirkt=True, min_battle=0)
    taps = [c for c in sim.clicks if c == "Test"]
    print("     card taps: %d, clicks %s" % (len(taps), sim.clicks[:6]))
    ok += len(taps) == 2

    # Nothing was attempted, so the list means it never opened. No re-open.
    good, _, sim = run_case([D.LIST, D.LIST],
                            "list straight away is not re-opened", None)
    print("     card taps: %d" % len([c for c in sim.clicks if c == "Test"]))
    ok += len([c for c in sim.clicks if c == "Test"]) == 1
    return ok, 2


def return_cases():
    """Finding the way back to the list from a prompt.

    Whether OK may be pressed depends on what was on screen one frame
    earlier. A dungeon panel means the prompt is the dungeon's own; anything
    else means it could be "Return to the title screen?", which must not be
    confirmed.
    """
    ok = 0
    for before, expected in ((D.DIALOG_PARTY, True), (D.UNKNOWN, False)):
        sim = Sim([before, D.EXIT, D.LIST])
        bot = make_bot(sim)
        seen = []
        bot.dismiss_confirm = (lambda info=None, leaving_dungeon=False:
                               seen.append(leaving_dungeon))
        bot.return_to_list = D.DungeonBot.return_to_list.__get__(bot)
        orig = D.recognise
        D.recognise = sim.next_state
        try:
            bot.return_to_list()
        finally:
            D.recognise = orig
        print("  prompt after %-13s -> OK allowed: %s" % (before, seen))
        ok += seen == [expected]
    return ok, 2


def main():
    ok = 0
    total = 0

    print("Re-opening a card")
    a, b = reopen_cases()
    ok += a
    total += b
    print()

    print("Back to the list")
    a, b = return_cases()
    ok += a
    total += b
    print()

    print("Confirmation prompts")
    a, b = confirm_cases()
    ok += a
    total += b
    print()

    print("Party slots")
    a, b = party_cases()
    ok += a
    total += b
    print()

    print("Dungeon selection")
    a, b = selection_cases()
    ok += a
    total += b
    print()

    # The party dialog must end the dungeon, not lead into a loop. In a test
    # run it appeared four times in a row, because Cancel keeps the bot
    # stuck in the dialog.
    sim = Sim([D.EXIT] * 8, confirm_kind="party")
    orig_rec, orig_cards = D.recognise, D.list_cards
    D.recognise = sim.next_state
    D.list_cards = lambda img, with_size=False: ([(0.3, 0.12)] if with_size
                                                 else [0.3])
    try:
        bot = make_bot(sim)
        seen = []
        real_run = D.DungeonBot.dismiss_confirm
        def spy(info=None, leaving_dungeon=False):
            seen.append(leaving_dungeon)
        bot.dismiss_confirm = spy
        bot.play_entry(0, "oben")
        del real_run
    finally:
        D.recognise, D.list_cards = orig_rec, orig_cards
    good = len(seen) <= 2
    ok += good
    total += 1
    print("%-44s leave_exit %dx  should be at most 2  %s"
          % ("party dialog ends the dungeon", len(seen),
             "ok" if good else "FAILED"))

    # An ad never yields a ticket. After the first one has no effect, it
    # must stop, otherwise the bot runs six ads into nothing as it did in a
    # test run.
    good, _, _ = run_case([D.DIALOG_AD] * 12,
                     "ad without effect, must stop after 1", 1)
    ok += good
    total += 1

    # An ad works, then the Attempt button appears
    good, _, _ = run_case([D.DIALOG_AD, D.DIALOG, D.DIALOG_AD, D.DIALOG],
                     "ad works, then Attempt", None)
    ok += good
    total += 1

    # A reward window is closed and does not block
    good, _, sim = run_case(["close", D.DIALOG_AD, "close", D.DIALOG_AD],
                       "reward window in between", None)
    print("     click sequence: %s" % ", ".join(sim.clicks[:6]))
    ok += good
    total += 1

    print("\n%d of %d cases as expected" % (ok, total))


if __name__ == "__main__":
    main()
