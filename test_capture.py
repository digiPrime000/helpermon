"""
Check the interface of the screen sources, no emulator needed.

All three have to be able to do the same, otherwise switching between them only
fails during a run. That is exactly what happened when ADB went away.
"""
import inspect

import cv2
import numpy as np

import capture

NOETIG = ["grab", "tap", "swipe", "back", "focus"]
KLASSEN = ["WindowCapture", "AdbCapture", "HybridCapture"]


def main():
    print("Required methods per screen source\n")
    errors = 0
    for name in KLASSEN:
        klasse = getattr(capture, name)
        missing = [m for m in NOETIG if not hasattr(klasse, m)]
        errors += len(missing)
        print("  %-16s %s" % (name, "complete" if not missing
                              else "MISSING " + ", ".join(missing)))

    print("\nSignatures of swipe, they have to match")
    for name in KLASSEN:
        fn = getattr(getattr(capture, name), "swipe", None)
        if fn:
            print("  %-16s %s" % (name, inspect.signature(fn)))

    print("\nEntry points")
    for name in ("open_capture", "open_window", "open_window_adb",
                 "open_hybrid", "open_best"):
        print("  %-16s %s" % (name, "present" if hasattr(capture, name) else "MISSING"))

    print("\n%s" % ("all good" if not errors
                    else "%d missing methods" % errors))
    agreement()


def a_screen(seed):
    """Something with enough structure in it to correlate on."""
    rng = np.random.RandomState(seed)
    img = np.zeros((1920, 1080, 3), np.uint8)
    for _ in range(40):
        x, y = rng.randint(0, 900), rng.randint(0, 1700)
        cv2.rectangle(img, (x, y), (x + rng.randint(40, 180),
                                    y + rng.randint(40, 180)),
                      tuple(int(c) for c in rng.randint(30, 255, 3)), -1)
    return img


def in_a_window(device_img, width=805):
    """The same screen as screen capture delivers it, chrome included."""
    left, top, right, bottom = capture.WINDOW_CHROME
    gw = width - left - right
    gh = int(round(gw / (1080 / 1920.0)))
    out = np.full((gh + top + bottom, width, 3), 40, np.uint8)
    out[top:top + gh, left:left + gw] = cv2.resize(
        device_img, (gw, gh), interpolation=cv2.INTER_AREA)
    return out


def agreement():
    """A window frame that has gone stale has to be caught, not used.

    While the display sleeps, screen capture keeps returning the last picture
    drawn, with no error anywhere. A bot in hybrid mode then reads a screen
    from minutes ago and clicks into it.
    """
    print("\nWindow frame against device frame")
    device = a_screen(1)
    same = capture.frames_agree(in_a_window(device), device)
    small = capture.frames_agree(in_a_window(device, 619), device)
    stale = capture.frames_agree(in_a_window(a_screen(2)), device)
    print("  the same screen               %.3f" % same)
    print("  the same screen, small window %.3f" % small)
    print("  a window one screen behind    %.3f" % stale)
    assert same > capture.FRAMES_AGREE_MIN, same
    assert small > capture.FRAMES_AGREE_MIN, small
    assert stale < capture.FRAMES_AGREE_MIN, stale
    print("  a stale window is told apart from a live one")


if __name__ == "__main__":
    main()
