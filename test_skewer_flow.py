"""
Check the skewer bot flow offline, no emulator needed.

Same approach as test_dungeon_flow.py: a scripted sequence of recognise()
results is played back and the resulting clicks are checked, without ever
touching a real screen. This works because SkewerBot only ever calls the
bare module-level recognise(img), never self.recognise(img), so it can be
swapped out process-wide for the duration of one call.

SkewerBot has two nested reactive loops, play_round() wrapping
solve_current_order(). Most cases below exercise solve_current_order()
directly; the two play_round-focused cases stub out solve_current_order so
the round-level stop conditions (UI gone, safety cap) are tested in
isolation from the order-solving logic already covered elsewhere.

solve_current_order() tracks its own click count instead of re-reading
"how many are already on the plate" from the current/plate strip every
step -- a live run showed that reading never once registered a successful
add, so click_ingredient/click_undo (which do rely on it) are no longer
called from the main loop. They stay in the class, and are tested here
directly rather than through solve_current_order, in case current-strip
reading is proven reliable later and the main loop switches back to using
them.

Deliberately not tested here: a "3 mistakes -> game over" counter. The bot
does not track lives itself (see skewer.py's module docstring) -- "round
ends" is detected purely by the Failed dialog or the gameplay UI
disappearing, both covered below regardless of what caused them.

The find_strip_icons cases at the bottom are the exception to "no images
needed": they build a synthetic plate in memory. They check counting and
the empty case only -- correct NAMING is a property of real game artwork
and is verified by hand against real --probe captures, not here.
"""
import cv2

import skewer as S


def mk_state(order, gameplay_visible=True, round_over_dialog=False,
            current=None, mistake_flash=False):
    """Build one recognise()-shaped dict. Every name in order (and current,
    if given) is placed on its own grid cell so a lookup by name finds it,
    mirroring Sim's button() helper in test_dungeon_flow.py."""
    current = current or []
    grid = []
    for fy in S.GRID_ROWS_FY:
        for fx in S.GRID_COLS_FX:
            grid.append({"name": None, "val": 0.0, "fx": fx, "fy": fy})
    for i, name in enumerate(sorted(set(order) | set(current))):
        if i < len(grid):
            grid[i]["name"] = name
            grid[i]["val"] = 0.9

    return {
        "state": S.UNKNOWN, "gameplay_visible": gameplay_visible,
        "order": order, "current": current, "next_ingredient": None,
        "grid": grid,
        "complete_button": {"fx": 0.81, "fy": 0.55},
        "plate_click": {"fx": 0.47, "fy": 0.55},
        "mistake_flash": mistake_flash, "mistake_hsv": (0.0, 0.0, 0.0),
        "mistake_red_share": 0.0,
        "round_over_dialog": round_over_dialog, "dialog_blue_share": 0.0,
    }


class Sim:
    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.i = 0
        self.clicks = []
        self.messages = []

    def next_state(self, _img=None):
        state = self.sequence[min(self.i, len(self.sequence) - 1)]
        self.i += 1
        return state


def make_bot(sim, **kw):
    bot = S.SkewerBot.__new__(S.SkewerBot)
    bot.dry_run = kw.get("dry_run", False)
    bot.log = sim.messages.append
    bot.tick = 0
    bot.patience = kw.get("patience", 1)
    bot.settle_tries = 1
    bot.round_seconds = kw.get("round_seconds", 60.0)
    bot.debugdir = "debug_skewer"
    bot.control = S.guard.Stop()
    bot.stats = {"orders_done": 0, "mistakes_seen": 0, "undo_clicks": 0,
                "unknown_reads": 0, "round_over_reason": ""}
    bot.max_loops = kw.get("max_loops", 400)
    bot.no_complete = kw.get("no_complete", False)
    bot.device = (1080, 1920)
    bot.grab = lambda: "img"
    bot.tap = lambda fx, fy, was="": sim.clicks.append(was)
    return bot


def with_recognise(sim, fn):
    """Swap sim.next_state in as skewer.recognise for the duration of fn()."""
    original = S.recognise
    S.recognise = sim.next_state
    try:
        return fn()
    finally:
        S.recognise = original


def check(name, good, detail=""):
    print("%-46s %s%s" % (name, "ok" if good else "FAILED", "  " + detail if detail else ""))
    return good


def main():
    ok = 0
    total = 0

    # Correct order end-to-end: settle on the order (two agreeing reads),
    # click each ingredient by count, then complete once as many clicks went
    # out as the order is long. click_complete polls for a changed order
    # afterwards, one extra state.
    order = ["tomato", "corn"]
    seq = [
        mk_state(order),          # settled_order, first read
        mk_state(order),          # settled_order, agrees -> target
        mk_state(order),          # built=0 -> click tomato
        mk_state(order),          # built=1 -> click corn
        mk_state(order),          # built=2 -> complete
        mk_state(["egg"]),        # click_complete sees the new order
    ]
    sim = Sim(seq)
    bot = make_bot(sim)
    result = with_recognise(sim, bot.solve_current_order)
    good = result is True and sim.clicks == ["add:tomato", "add:corn", "complete"]
    ok += check("correct order end-to-end", good, str(sim.clicks))
    total += 1

    # The failure this guards against: an order caught half-drawn. Two reads
    # that disagree must produce NO clicks at all -- the old code acted on
    # the first frame it saw, built the part that had appeared, and
    # submitted that as if it were the whole order.
    seq = [
        mk_state(["tomato"]),                     # half of it drawn
        mk_state(["tomato", "corn", "egg"]),      # the rest arrives
        mk_state(["tomato", "corn", "egg"]),      # now it agrees
        mk_state(["tomato", "corn", "egg"]),
        mk_state(["tomato", "corn", "egg"]),
        mk_state(["tomato", "corn", "egg"]),
        mk_state(["tomato", "corn", "egg"]),
        mk_state(["radish"]),                     # click_complete: new order
    ]
    sim = Sim(seq)
    bot = make_bot(sim)
    result = with_recognise(sim, bot.solve_current_order)
    good = (result is True
            and sim.clicks == ["add:tomato", "add:corn", "add:egg", "complete"])
    ok += check("a half-drawn order is waited out, not acted on", good,
               str(sim.clicks))
    total += 1

    # An order that never holds still is never clicked on either.
    seq = [mk_state(["tomato"]), mk_state(["corn"])] * 6
    sim = Sim(seq)
    bot = make_bot(sim)
    result = with_recognise(sim, bot.solve_current_order)
    good = result is False and sim.clicks == []
    ok += check("an order that never settles produces no clicks", good,
               str(sim.clicks))
    total += 1

    # If the order swaps mid-build, `built` is counting against something no
    # longer on screen. Submitting on that count would serve a wrong skewer,
    # so it must hand back instead of pressing Complete.
    order = ["tomato", "corn", "egg"]
    seq = [
        mk_state(order),          # settle
        mk_state(order),
        mk_state(order),          # click tomato
        mk_state(["radish", "onion"]),   # order swapped under us
    ]
    sim = Sim(seq)
    bot = make_bot(sim)
    result = with_recognise(sim, bot.solve_current_order)
    good = result is False and "complete" not in sim.clicks
    ok += check("an order changing mid-build never gets completed", good,
               str(sim.clicks))
    total += 1

    # --no-complete: builds the order but stops right before Complete,
    # leaving the built skewer and its order on screen instead of clicking.
    order = ["tomato", "corn"]
    seq = [mk_state(order), mk_state(order), mk_state(order)]
    sim = Sim(seq)
    bot = make_bot(sim, no_complete=True)
    result = with_recognise(sim, bot.solve_current_order)
    good = result == S.ORDER_HELD and sim.clicks == ["add:tomato", "add:corn"]
    ok += check("--no-complete holds instead of clicking complete", good, str(sim.clicks))
    total += 1

    # play_round() stops the round the moment an order is held, same as
    # any other stop condition -- no further orders, no more clicks.
    seq = [mk_state(order), mk_state(order), mk_state(order)]
    sim = Sim(seq)
    bot = make_bot(sim, no_complete=True, max_loops=50)
    stats = with_recognise(sim, lambda: bot.play_round(seconds=1000))
    good = (stats["round_over_reason"] == "held before Complete (--no-complete)"
            and sim.clicks == ["add:tomato", "add:corn"])
    ok += check("play_round stops on an order held for --no-complete", good,
               stats["round_over_reason"])
    total += 1

    # An ingredient not currently found on the grid is retried, not
    # guessed at or skipped, and gives up after a bounded number of tries.
    order = ["tomato"]
    seq = [mk_state([])] * 8  # empty order every read -> never on the grid
    sim = Sim(seq)
    bot = make_bot(sim)
    result = with_recognise(sim, bot.solve_current_order)
    good = result is False and sim.clicks == []
    ok += check("unreadable order produces no clicks", good, str(sim.clicks))
    total += 1

    # click_ingredient in isolation: dry run never checks the plate and
    # always reports success; a real run checks current grew by exactly
    # the one expected name.
    info = mk_state(["tomato"])
    bot = make_bot(Sim([info]), dry_run=True)
    ok += check("click_ingredient dry run always succeeds",
               bot.click_ingredient("tomato", info) is True)
    total += 1

    sim = Sim([mk_state(["tomato"], current=["tomato"])])
    bot = make_bot(sim)
    result = with_recognise(sim, lambda: bot.click_ingredient("tomato", mk_state(["tomato"])))
    ok += check("click_ingredient verifies current grew by the right name",
               result is True, str(sim.clicks))
    total += 1

    # click_undo in isolation: current shrinking by one and matching the
    # prior prefix counts as success, and it is tracked in stats.
    sim = Sim([mk_state(["tomato", "corn"], current=["tomato"])])
    bot = make_bot(sim)
    before_info = mk_state(["tomato", "corn"], current=["tomato", "corn"])
    result = with_recognise(sim, lambda: bot.click_undo(before_info))
    good = result is True and sim.clicks == ["undo"] and bot.stats["undo_clicks"] == 1
    ok += check("click_undo verifies current shrank by one", good, str(sim.clicks))
    total += 1

    # Round ends cleanly once the gameplay UI is gone for several reads in
    # a row, with solve_current_order never called and nothing clicked.
    seq = [mk_state([], gameplay_visible=False)] * 5
    sim = Sim(seq)
    bot = make_bot(sim, max_loops=50)
    calls = []
    bot.solve_current_order = lambda max_steps=20: calls.append(1)
    stats = with_recognise(sim, lambda: bot.play_round(seconds=1000))
    good = (stats["round_over_reason"] == "round over (UI absent)"
            and not calls and sim.clicks == [])
    ok += check("round ends cleanly on UI absence", good, stats["round_over_reason"])
    total += 1

    # The "Failed..." dialog ends the round immediately, on the very first
    # read, without waiting for the UI-absence counter.
    seq = [mk_state([], round_over_dialog=True)] * 3
    sim = Sim(seq)
    bot = make_bot(sim, max_loops=50)
    calls = []
    bot.solve_current_order = lambda max_steps=20: calls.append(1)
    stats = with_recognise(sim, lambda: bot.play_round(seconds=1000))
    good = (stats["round_over_reason"] == "round over (Failed dialog)"
            and not calls and sim.clicks == [] and sim.i == 1)
    ok += check("Failed dialog ends the round on the first read", good,
               "%s, %d reads" % (stats["round_over_reason"], sim.i))
    total += 1

    # If round-over is never detected, the hard safety cap still ends the
    # round rather than looping forever.
    seq = [mk_state(["a"], gameplay_visible=True)] * 10
    sim = Sim(seq)
    bot = make_bot(sim, max_loops=5)
    calls = []
    bot.solve_current_order = lambda max_steps=20: calls.append(1)
    stats = with_recognise(sim, lambda: bot.play_round(seconds=1000))
    good = stats["round_over_reason"] == "step limit reached" and len(calls) == 5
    ok += check("safety cap ends a stuck round", good,
               "%d calls, %s" % (len(calls), stats["round_over_reason"]))
    total += 1

    # restart_round: Close only when the Failed dialog is actually showing,
    # Start always follows.
    seq = [mk_state([], round_over_dialog=True)]
    sim = Sim(seq)
    bot = make_bot(sim, patience=0)
    with_recognise(sim, bot.restart_round)
    good = sim.clicks == ["close_failed_dialog", "start_stage"]
    ok += check("restart_round closes the dialog, then starts", good, str(sim.clicks))
    total += 1

    seq = [mk_state([], round_over_dialog=False)]
    sim = Sim(seq)
    bot = make_bot(sim, patience=0)
    with_recognise(sim, bot.restart_round)
    good = sim.clicks == ["start_stage"]
    ok += check("restart_round skips Close when no dialog is showing", good,
               str(sim.clicks))
    total += 1

    # enter_from_menu: Play Game then Start, unconditionally, no recognise()
    # call in between -- there is nothing to check against on the main menu.
    sim = Sim([])
    bot = make_bot(sim, patience=0)
    bot.enter_from_menu()
    good = sim.clicks == ["play_game", "start_stage"]
    ok += check("enter_from_menu clicks Play Game then Start", good, str(sim.clicks))
    total += 1

    ok_s, total_s = speed_cases()
    ok_r, total_r = reading_cases()
    print("\n%d of %d cases as expected"
          % (ok + ok_s + ok_r, total + total_s + total_r))


def speed_cases():
    """--speed divides the wait between clicks, and is bounded at both ends
    so the dial cannot stall the bot or make it tap a screen it has not
    looked at. Constructed for real here rather than through make_bot,
    because it is __init__ that does the arithmetic."""
    ok = 0
    total = 0

    class NoCap:
        def grab(self):
            raise RuntimeError("no screen in this test")

    def build(**kw):
        return S.SkewerBot(NoCap(), log=lambda *a: None, **kw)

    base = build()
    fast = build(speed=2.0)
    ok += check("speed 2.0 halves the wait between clicks",
               abs(fast.tick - base.tick / 2.0) < 1e-9,
               "%.3f vs %.3f" % (fast.tick, base.tick))
    total += 1

    # Waits for the GAME stay put. Shortening them along with the click tick
    # is what let the bot act on a half-drawn order.
    ok += check("speed leaves the waits for the game alone",
               fast.patience == base.patience,
               "%.3f vs %.3f" % (fast.patience, base.patience))
    total += 1

    slow = build(speed=0.5)
    ok += check("speed below 1 waits longer", slow.tick > base.tick,
               "%.3f vs %.3f" % (slow.tick, base.tick))
    total += 1

    wild = build(speed=99.0)
    ok += check("an absurd speed is clamped, not obeyed",
               wild.speed == S.MAX_SPEED and wild.tick >= S.MIN_TICK,
               "speed %.2f tick %.3f" % (wild.speed, wild.tick))
    total += 1

    stopped = build(speed=0.0)
    ok += check("speed 0 does not stall or divide by zero",
               stopped.speed == S.MIN_SPEED and stopped.tick > 0,
               "speed %.2f tick %.3f" % (stopped.speed, stopped.tick))
    total += 1
    return ok, total


def scene(icons=(), plate=True):
    """A synthetic plate: white oval on a table, a wooden stick across it,
    and one coloured blob per icon. Only the geometry is realistic -- the
    blobs are flat colour, so this exercises _skewer_clusters' counting and
    grouping, NOT the colour classifier, which needs real captures.
    """
    import numpy as np
    img = np.full((1390, 765, 3), (60, 90, 140), np.uint8)
    if plate:
        cv2.ellipse(img, (380, 770), (150, 55), 0, 0, 360, (225, 228, 230), -1)
        cv2.ellipse(img, (380, 770), (150, 55), 0, 0, 360, (40, 40, 40), 3)
        cv2.rectangle(img, (240, 762), (520, 778), (150, 190, 215), -1)
    # Left apart rather than touching, the way a real short order draws its
    # ingredients, so each one is its own cluster. Big enough to clear the
    # "is anything on the skewer at all" gate, which is a share of the crop
    # height.
    for i, colour in enumerate(icons):
        centre = 255 + i * 62
        cv2.circle(img, (centre, 770), 26, colour, -1)
        cv2.circle(img, (centre, 770), 26, (30, 30, 30), 2)
    return img


def learned_signatures(colours=((60, 60, 200), (60, 200, 60), (200, 160, 60))):
    """Signatures built the way the program builds them, but from synthetic
    grid buttons rather than from whatever this machine happens to have
    learned.

    This used to call S.load_icon_signatures(), which reads the player's own
    userdata. On a machine where the Night Market wizard has never been run
    that is empty, every reading case below then found nothing and failed
    for a reason that says nothing about the code. A suite that only passes
    on a set-up machine cannot be the gate before a change.
    """
    import numpy as np
    import skewer as S
    out = {}
    for i, colour in enumerate(colours):
        # A grid button: dark grey field, the ingredient painted on it. That
        # is the shape _grid_icon_mask expects to separate.
        tpl = np.full((64, 64, 3), (40, 40, 45), np.uint8)
        cv2.circle(tpl, (32, 32), 20, colour, -1)
        out["ingredient_%d" % i] = S._colour_signature(tpl,
                                                       S._grid_icon_mask(tpl))
    return out


def reading_cases():
    """The geometry half of find_strip_icons, on synthetic skewers.

    Deliberately NOT asserting which ingredients come back. Naming is a
    property of real game artwork -- flat coloured blobs classify
    arbitrarily, and two of them can easily land on the same name, which
    would make a count assertion fail for reasons that say nothing about
    the code. What is checked here is what synthetic images can honestly
    support: an empty skewer reads as empty, and a longer skewer is found
    to be longer.
    """
    import skewer as S
    ok = 0
    total = 0
    signatures = learned_signatures()

    got = S.find_strip_icons(scene(), S.POS_CURRENT_STRIP, signatures)
    ok += check("bare stick reads as no ingredients", got == [], str(got))
    total += 1

    got = S.find_strip_icons(scene(plate=False), S.POS_CURRENT_STRIP, signatures)
    ok += check("no plate on screen reads as no ingredients", got == [], str(got))
    total += 1

    # Nothing learned yet must not crash or invent ingredients.
    got = S.find_strip_icons(scene([(60, 60, 200)]), S.POS_CURRENT_STRIP, {})
    ok += check("no templates learned yields nothing", got == [], str(got))
    total += 1

    # Every ingredient present must come back as an entry. This is the whole
    # point of the reader -- one going missing is the bug it exists to
    # prevent -- so it is asserted on count, not on names. Four is the most
    # that fits the synthetic plate.
    for n in (1, 2, 3, 4):
        got = S.find_strip_icons(scene([(60, 60, 200)] * n), S.POS_CURRENT_STRIP,
                                 signatures)
        ok += check("%d ingredients are counted as %d" % (n, n), len(got) == n,
                   "read %d: %s" % (len(got), got))
        total += 1
    return ok, total


if __name__ == "__main__":
    main()
