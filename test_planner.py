"""
Check the planner offline, no emulator needed.

Boards are built from text and the chosen action is compared against
expectations.
"""
import planner as planner_mod
import world as world_mod

LEGEND = {".": None, "P": "pyramid", "O": "ticket_orange", "G": "ticket_green",
          "R": "ticket_pink", "K": "claw", "T": "paw", "F": "fireball"}


def build(rows, fig_row, fig_col, scroll=0):
    grid = [[LEGEND[ch] for ch in row.split()] for row in rows]
    w = world_mod.World()
    w.scroll_offset = scroll
    # twice, because an object needs two sightings to be confirmed
    w.observe(grid, dict(row=fig_row, col=fig_col, how="test"))
    w.observe(grid, dict(row=fig_row, col=fig_col, how="test"))
    return w


CASES = [
    ("empty board, figure in column 2", [
        ". . . . .", ". . . . .", ". . . . .", ". . . . .", ". . . . ."],
     2, 1, dict(paws=500, meters=100, fireballs=10, claws=10), "step right"),

    ("ticket same row, to the right", [
        ". . . . .", ". . . . .", ". . . O .", ". . . . .", ". . . . ."],
     2, 1, dict(paws=500, meters=100, fireballs=10, claws=10), "step right"),

    ("ticket one column right, other row, postponed", [
        ". . . . .", ". . . . .", ". . . . .", ". . O . .", ". . . . ."],
     2, 1, dict(paws=500, meters=100, fireballs=10, claws=10), "step right"),

    ("pyramid in the way, neighbour row clear, go around", [
        ". . . . .", ". . . . .", ". . P . .", ". . . . .", ". . . . ."],
     2, 1, dict(paws=500, meters=100, fireballs=0, claws=10), "step"),

    # The pyramid sits on the vertical path in the current column. Going
    # right first and then vertically is cheaper than destroying it
    ("pyramid on the vertical path, go right first", [
        ". . . . .", ". . . . .", ". . . . .", ". P . . .", ". . O . ."],
     2, 1, dict(paws=500, meters=100, fireballs=0, claws=10), "step right"),

    # Target row full of pyramids, current row clear. So walk in the clear
    # row to the target column and only change afterwards
    ("target row full of pyramids, continue in the clear row", [
        ". . . . .", ". . . . .", ". . . . .", ". P P P O", ". . . . ."],
     2, 1, dict(paws=500, meters=100, fireballs=0, claws=10), "step right"),

    # The other way around, current row full of pyramids, target row clear.
    # Now the early change pays off
    ("current row full of pyramids, change now", [
        ". . . . .", ". . . . .", ". . P P P", ". . . . O", ". . . . ."],
     2, 1, dict(paws=500, meters=100, fireballs=0, claws=10), "step down"),

    # Three pyramids. With a time value, and because the fireball also
    # picks up the loot underneath, it pays off here despite a clear
    # detour row being available
    ("three pyramids, fireball pays despite a clear row", [
        ". . . . .", ". . . . .", ". . P P P", ". . . . .", ". . . . ."],
     2, 1, dict(paws=500, meters=100, fireballs=5, claws=10), "skill"),

    # Change row only when necessary. Target three columns right, one row
    # below. There is time left, so go right first and change row later
    ("target far right, row change postponed", [
        ". . . . .", ". . . . .", ". . . . .", ". . . . O", ". . . . ."],
     2, 1, dict(paws=500, meters=100, fireballs=0, claws=10), "step right"),

    # Dodging prefers the middle. Figure in row 2, both directions clear,
    # so downward towards row 3
    ("dodging picks the direction towards the middle", [
        ". . . . .", ". . P . .", ". . . . .", ". . . . .", ". . . . ."],
     1, 1, dict(paws=500, meters=100, fireballs=0, claws=0), "step down"),

    # Without a detour row only the claw is left, three claws cost 600 Bits.
    # Then the fireball pays off
    ("three pyramids, no way around, skill pays", [
        ". . P P P", ". . P P P", ". . P P P", ". . . . .", ". . . . ."],
     1, 1, dict(paws=500, meters=100, fireballs=5, claws=10), "skill"),

    ("object in the left column, step right blocked", [
        ". . . . .", ". . . . .", "O . . . .", ". . . . .", ". . . . ."],
     2, 1, dict(paws=500, meters=100, fireballs=0, claws=10), "step left"),

    ("paws almost empty", [
        ". . . . .", ". . . . .", ". . . . .", ". . . . .", ". . . . ."],
     2, 1, dict(paws=5, meters=100, fireballs=0, claws=10), "stop"),

    ("high metre count, no limit set", [
        ". . . . .", ". . . . .", ". . . . .", ". . . . .", ". . . . ."],
     2, 1, dict(paws=500, meters=98000, fireballs=0, claws=10), "step right"),

    ("no claws, ticket behind a pyramid, skipped", [
        ". . . . .", ". . . . .", ". . . . .", ". P . . .", ". . O . ."],
     2, 1, dict(paws=500, meters=100, fireballs=5, claws=0), "step right"),

    ("claws empty, pyramid directly right, go around instead of clicking", [
        ". . . . .", ". . . . .", ". . P . .", ". . . . .", ". . . . ."],
     2, 1, dict(paws=500, meters=100, fireballs=0, claws=0), "step"),

    # Figure stands in edge row 1, target in edge row 5. Both paths have 5
    # steps, but the search leaves the edge row earlier because the middle
    # surcharge sums the row distance along the whole path, 6 against 8.
    # From the middle, the paths to the next object are shorter on average
    ("leave the edge row when the target is far away", [
        ". . . . .", ". . . . .", ". . . . .", ". . . . .", ". . R . ."],
     0, 1, dict(paws=500, meters=100, fireballs=0, claws=10), "step down"),

    # Cross-check. If the figure already stands centred, it stays in the
    # row and only changes at the target column, here 0 against 1 on the
    # middle surcharge
    ("stay centred and postpone the row change", [
        ". . . . .", ". . . . .", ". . . . .", ". . . . O", ". . . . ."],
     2, 1, dict(paws=500, meters=100, fireballs=0, claws=10), "step right"),

    ("ticket in the same column, go vertical now", [
        ". . . . .", ". . . . .", ". . . . .", ". . . . .", ". R . . ."],
     0, 1, dict(paws=500, meters=100, fireballs=0, claws=10), "step down"),
]


def time_cases():
    """Shows how the time value tips the skill decision."""
    rows = [". . . . .", ". . . . .", ". . P P P", ". . . . .", ". . . . ."]
    counters = dict(paws=500, meters=100, fireballs=5, claws=10)
    print("\nThree pyramids with a clear row, influence of the time value")
    for bpa in (0, 20, 40, 80):
        w = build(rows, 2, 1)
        p = planner_mod.Planner(w, bit_per_action=bpa)
        act = p.next_action(counters)
        print("  Bits per saved action %3d  ->  %-12s %s"
              % (bpa, act.kind, act.reason))


def main():
    ok = 0
    for name, rows, fr, fc, counters, expect in CASES:
        w = build(rows, fr, fc)
        p = planner_mod.Planner(w)
        act = p.next_action(counters)
        got = ("%s %s" % (act.kind, act.direction or "")).strip()
        good = got.startswith(expect)
        ok += good
        print("%-46s -> %-14s %s" % (name, got, "ok" if good else "EXPECTED " + expect))
        print("   %s" % act.reason)
    print("\n%d of %d cases as expected" % (ok, len(CASES)))
    time_cases()


if __name__ == "__main__":
    main()
