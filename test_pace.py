"""
Check the adaptive pacing offline.

The bot speeds up after clean actions and becomes cautious again on any failure.
That has to stay traceable.
"""
import actions


def make():
    a = actions.Actor.__new__(actions.Actor)
    a.base_click_delay = 1.5
    a.base_settle = 0.55
    a.base_verify_pause = 0.2
    a.pace = 1.0
    a.min_pace = 0.35
    a.adaptive = True
    a.clean_streak = 0
    return a


def main():
    ok = []
    a = make()
    a.on_clean_success()
    a.on_clean_success()
    ok.append(("first two successes do not speed up", a.pace == 1.0))

    a.on_clean_success()
    ok.append(("from the third success it speeds up", a.pace < 1.0))

    for _ in range(30):
        a.on_clean_success()
    ok.append(("lower bound is respected", abs(a.pace - a.min_pace) < 1e-9))

    a.on_trouble()
    ok.append(("a failure resets to cautious at once", a.pace == 1.0))
    ok.append(("a failure resets the streak", a.clean_streak == 0))

    # Zweitversuch bremst nur leicht, er setzt nicht zurueck. Vorher hat das
    # den Tempofaktor alle drei Aktionen auf 1,0 geworfen
    c = make()
    for _ in range(10):
        c.on_clean_success()
    p = c.pace
    c.on_slow_confirm()
    ok.append(("a retry only slows down slightly", p < c.pace < 1.0))

    b = make()
    b.adaptive = False
    for _ in range(20):
        b.on_clean_success()
    ok.append(("a fixed tick stays fixed", b.pace == 1.0))

    for name, good in ok:
        print("%-46s %s" % (name, "ok" if good else "FAILED"))
    print("\n%d of %d ok" % (sum(1 for _, g in ok if g), len(ok)))


if __name__ == "__main__":
    main()
