"""
Check pathfinding offline. No emulator, no interface.

Boards are written as text: P is a pyramid, F the figure, Z the target.
"""
import router

PAW, CLAW, ACTION, LOOT = 40, 200, 40, 25
COST_STEP = PAW + ACTION            # 80
COST_DESTROY = CLAW + ACTION - LOOT  # 215


def build(rows):
    grid = [list(r.replace(" ", "")) for r in rows]
    start = goal = None
    pyr = set()
    for r, line in enumerate(grid):
        for c, ch in enumerate(line):
            if ch == "P":
                pyr.add((r, c))
            elif ch == "F":
                start = (r, c)
            elif ch == "Z":
                goal = (r, c)
    return start, goal, pyr


def route(rows, can_destroy=True, goals=None):
    start, goal, pyr = build(rows)
    rt = router.Router(lambda r, c: (r, c) in pyr, COST_STEP, COST_DESTROY,
                       can_destroy=can_destroy)
    return rt.search(start, goals if goals is not None else
                     ({goal} if goal else set()))


CASES = [
    ("clear path to the right", [
        ".....", ".....", ".F..Z", ".....", "....."], "right", 0),

    # Zwei Schritte Umweg kosten 160 Bits, eine Kralle 215. Also umgehen
    ("pyramid in the way, detour is cheaper", [
        ".....", ".....", ".FP.Z", ".....", "....."], None, 0),

    # Mauer aus drei Pyramiden senkrecht, kein Umweg moeglich, also zerstoeren
    ("vertical wall, destroy", [
        "..P..", "..P..", ".FP.Z", "..P..", "..P.."], "right", 1),

    ("without claws a vertical wall is impassable", [
        "..P..", "..P..", ".FP.Z", "..P..", "..P.."], None, 0),
]


def main():
    ok = 0
    print("Prices: step %d Bits, entering a pyramid costs %d Bits more\n"
          % (COST_STEP, COST_DESTROY))
    for name, rows, first, destroys in CASES:
        can = "without claws" not in name
        rt = route(rows, can_destroy=can)
        good = True
        if first and rt.first != first:
            good = False
        if not can:
            good = not rt.reachable
        elif rt.destroys != destroys:
            good = False
        ok += good
        print("%-46s -> %-6s %s Bits, %d Schritte, %d zerstoert  %s"
              % (name, rt.first, rt.cost, rt.steps, rt.destroys,
                 "ok" if good else "UNEXPECTED"))

    print("\nDodge direction on a tie, expected towards the centre")
    for name, rows in [
        ("figure row 2, centre is below", ["....." , ".FP.Z", ".....", ".....", "....."]),
        ("figure row 4, centre is above", ["....." , ".....", ".....", ".FP.Z", "....."]),
    ]:
        rt = route(rows)
        print("  %-34s -> %-6s path %s" % (name, rt.first, rt.path))

    print("\nStep left when it is the cheapest path")
    rows = ["PPPPP", "PPPPP", ".FPPP", "PPPPP", "PPPPP"]
    rt = route(rows, goals={(2, 0)})
    print("  target left of the figure        -> %s, %s Bits" % (rt.first, rt.cost))

    print("\n%d of %d cases as expected" % (ok, len(CASES)))


if __name__ == "__main__":
    main()
