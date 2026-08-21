"""Self-test of the vision layer against saved screenshots. Clicks nothing."""
import glob, os, sys
import cv2
import vision

def run(paths, outdir="debug"):
    os.makedirs(outdir, exist_ok=True)
    tpl = vision.load_templates()
    tpl_obj = vision.board_templates(tpl)
    print("Templates:", sorted(tpl.keys()))
    for path in paths:
        img = cv2.imread(path)
        name = os.path.basename(path)
        try:
            cal = vision.calibrate(img)
        except vision.CalibrationError as err:
            print(name, "KALIBRIERUNG FEHLGESCHLAGEN", err)
            continue
        banner = vision.banner_visible(img, cal)
        grid, scores = vision.read_grid(img, cal, tpl_obj)
        fig = vision.find_figure(img, cal, tpl)
        counters = vision.read_counters(img, cal)
        print("\n=== %s  cell=%.1fx%.1f  banner=%s" % (name, cal["cell_w"], cal["cell_h"], banner))
        for r in range(vision.ROWS):
            print("  " + " ".join(
                ("%-13s" % (grid[r][c] or ".")) for c in range(vision.COLS)))
        print("  Figur:", fig)
        print("  Zaehler:", counters)
        vis = vision.draw_overlay(img, cal, grid, fig, counters)
        cv2.imwrite(os.path.join(outdir, "dbg_" + name), vis)

if __name__ == "__main__":
    args = sys.argv[1:] or sorted(glob.glob("/mnt/user-data/uploads/17*")) + sorted(
        glob.glob("/mnt/user-data/uploads/Screen*"))
    run(args)
