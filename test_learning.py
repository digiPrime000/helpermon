"""
Check the wizard logic offline, no emulator and no interface.

Screenshots are needed. The default is the folder where debug images land.
Without images the test is skipped rather than failing.

  py test_learning.py image.png [more.png ...]
"""
import glob
import os
import sys

import cv2

import learning
import userdata
import vision


def main():
    paths = sys.argv[1:] or sorted(glob.glob("debug/*.png"))
    print("Learned data folder: %s" % userdata.describe())

    st = learning.status()
    print("\nState")
    print("  missing templates   %s" % (", ".join(st["missing"]) or "none"))
    print("  shipped             %d" % len(st["shipped"]))
    print("  missing digits      %s" % (", ".join(st["ziffern_fehlen"]) or "none"))
    print("  thinly covered      %s" % (", ".join(st["ziffern_duenn"]) or "none"))
    print("  ready to run        %s" % st["fertig"])

    if not paths:
        print("\nno images given, rest skipped")
        return

    for path in paths:
        img = cv2.imread(path)
        if img is None:
            continue
        try:
            calib = vision.calibrate(img)
        except vision.CalibrationError as err:
            print("\n%s, Kalibrierung fehlgeschlagen, %s" % (os.path.basename(path), err))
            continue
        print("\n%s  Zelle %.1f" % (os.path.basename(path), calib["cell_w"]))
        offen = learning.object_candidates(img, calib)
        print("  open colourful finds %s"
              % (", ".join("r%dc%d" % (c["row"] + 1, c["col"] + 1) for c in offen)
                 or "none"))
        py = learning.pyramid_candidates(img, calib, limit=3)
        print("  pyramid suggestions  %s"
              % ", ".join("r%dc%d (%.1f)" % (c["row"] + 1, c["col"] + 1, c["energie"])
                          for c in py))
        values = vision.read_counters(img, calib)
        print("  counters read        %s"
              % ", ".join("%s=%s" % (k, v) for k, v in values.items()))


if __name__ == "__main__":
    main()
