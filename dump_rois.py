"""
Write the seven counter regions as individual images together with the
recognised value. That shows immediately whether a region is too narrow and cuts
off a digit.

  py dump_rois.py
  py dump_rois.py image.png
"""
import os
import sys

import cv2
import numpy as np

import vision
from calibrate import grab_and_calibrate

def main():
    if len(sys.argv) > 1:
        img = cv2.imread(sys.argv[1])
        calib = vision.calibrate(img)
    else:
        img, calib = grab_and_calibrate()
    os.makedirs("debug", exist_ok=True)
    strips = []
    for key in vision.COUNTER_KEYS:
        x, y, w, h = calib[key]
        crop = img[max(0, y): y + h, max(0, x): x + w]
        value = vision.read_number(img, key, calib)
        glyphs = vision.segment_digits(img, calib[key], vision.POLARITY[key])
        print("%-16s %-8s Zeichen %d  Bereich %s"
              % (key.replace("roi_", ""), value, len(glyphs), [x, y, w, h]))
        strip = cv2.resize(crop, (360, 60))
        cv2.putText(strip, "%s=%s" % (key.replace("roi_", ""), value),
                    (4, 16), 0, 0.45, (0, 0, 255), 1)
        strips.append(strip)
    out = os.path.join("debug", "rois.png")
    cv2.imwrite(out, np.vstack(strips))
    print("\nBild:", out)
    print("Pruefen, ob jede Zahl vollstaendig im Ausschnitt liegt.")

if __name__ == "__main__":
    main()
