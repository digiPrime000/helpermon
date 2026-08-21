"""
Check the action verification offline.

Exactly this part failed in the first real run, because it expected an exact
delta and a power-up collected at the same moment shifts that delta.
"""
import actions
import planner


def judge(kind, deltas, banner=None, col=1, direction="right"):
    act = planner.Action(kind, direction, (0, 0))
    dummy = actions.Actor.__new__(actions.Actor)
    return actions.Actor._judge(dummy, act, col, deltas, banner)


CASES = [
    ("step, one paw gone", "step", {"paws": -1}, None, actions.OK),
    ("step right with scroll", "step", {"paws": -1, "meters": 1}, None, actions.OK),
    ("step collects a paw power-up", "step", {"paws": 4}, None, actions.OK),
    ("step collects a ticket", "step", {"paws": -1, "top_orange": 125}, None, actions.OK),
    ("paws unreadable, but a ticket arrived", "step", {"top_orange": 125}, None, actions.OK),
    ("nothing happened, move banner", "step", {}, "move", actions.BANNER_MOVE),
    ("nothing happened, no banner", "step", {}, None, actions.NO_EFFECT),
    ("pyramid, one claw gone", "destroy", {"claws": -1}, None, actions.OK),
    ("pyramid plus power-up underneath", "destroy", {"claws": -1, "fireballs": 1}, None, actions.OK),
    ("pyramid already gone, click was a step", "destroy",
     {"paws": -1, "meters": 1}, None, actions.MOVED_INSTEAD),
    ("pyramid, nothing", "destroy", {}, None, actions.NO_EFFECT),
    ("claws empty, Insufficient banner", "destroy", {}, "insufficient",
     actions.INSUFFICIENT),
    ("paws empty, Insufficient banner", "step", {}, "insufficient",
     actions.INSUFFICIENT),
    ("skill from column 2", "skill", {"fireballs": -1, "meters": 3}, None, actions.OK),
    ("skill, fireball unreadable, metres plus 2", "skill", {"meters": 2}, None, actions.OK),
    ("skill, nothing", "skill", {}, None, actions.NO_EFFECT),
]


def main():
    ok = 0
    for name, kind, deltas, banner, expect in CASES:
        got = judge(kind, deltas, banner)
        good = got == expect
        ok += good
        print("%-42s -> %-12s %s" % (name, got, "ok" if good else "EXPECTED " + expect))
    print("\n%d of %d ok" % (ok, len(CASES)))


if __name__ == "__main__":
    main()
