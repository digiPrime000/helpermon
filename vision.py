"""
Minigame vision layer. Calibration and image analysis. Clicks nothing.

Everything is derived from the current frame; there are no hard-coded pixel
values for a particular window size.

Anchor chain
  1. find the grey card in the emulator window, the largest bright desaturated
     contour
  2. fit the column grid periodically onto the vertical edge profile
  3. fit rows with the cell aspect ratio forced, because cells are NOT square
"""

import os

import cv2
import numpy as np

ROWS = 5
COLS = 5

# Zellverhaeltnis Breite zu Hoehe, aus 8 Emulator Screenshots gemessen
ASPECT = 1.220
ASPECT_TOL = 0.03

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def _only_learned():
    """Schalter, mitgelieferte Bilder ignorieren. Dient dazu, den
    Einrichtungsassistenten wie ein frischer Nutzer durchzuspielen, ohne Ordner
    umzubenennen."""
    try:
        import userdata
        return userdata.only_learned()
    except Exception:
        return False


def _learned_dirs():
    """Ordner mit selbst Gelerntem. Er hat Vorfahrt vor dem mitgelieferten
    Ordner, damit ein Programmupdate nichts ueberschreibt und eine
    Veroeffentlichung ganz ohne mitgelieferte Bilder auskommt."""
    try:
        import userdata
        return userdata.templates_dir(create=False), userdata.digits_dir(create=False)
    except Exception:
        return None, None

# Reihenfolge ist wichtig, spezifische Templates zuerst
OBJECT_TYPES = [
    "ticket_orange",
    "ticket_green",
    "ticket_pink",
    "claw",
    "paw",
    "fireball",
    "pyramid",
    "figure",
]
# Templates, die nicht auf dem Spielfeld gesucht werden
# Diese Templates werden nicht Zelle fuer Zelle auf dem Brett gesucht. Die
# Figur nicht, weil find_figure das separat und zuverlaessiger macht, der Pfeil
# nicht, weil er kein Objekt ist, und die Bannerteile nicht, weil sie in einem
# eigenen Bereich liegen.
NON_BOARD_TEMPLATES = ["arrow", "figure", "banner_badge", "banner_text_move",
                       "banner_text_insufficient"]
POWERUPS = ["ticket_orange", "ticket_green", "ticket_pink", "claw", "paw", "fireball"]


# ----------------------------------------------------------------------------
# Kalibrierung
# ----------------------------------------------------------------------------
def find_card(img):
    """Graue Spielkarte im Fenster finden. Rueckgabe (x, y, w, h)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 150), (180, 60, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise CalibrationError("keine helle Flaeche gefunden")
    # Nicht blind die groesste Kontur nehmen. Es kann helle Bereiche neben der
    # Karte geben, deshalb die groesste mit plausiblem Hochformat waehlen.
    tried = []
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:12]:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 0.20 * img.shape[1] or h < 0.20 * img.shape[0]:
            continue
        ratio = h / max(w, 1)
        tried.append("%dx%d h/w=%.2f" % (w, h, ratio))
        if 1.8 <= ratio <= 2.5:
            return x, y, w, h
    raise CalibrationError(
        "no portrait-format card found, candidates: %s"
        % (", ".join(tried) or "none"))


def _fit_periodic(profile, cell_lo, cell_hi, n, off_lo, off_hi, cell_step=0.25):
    """Sucht Zellgroesse und Offset, die die Kantenenergie auf den n+1
    Rasterlinien maximieren. Robuster als Peakpicking."""
    best = (-1.0, None, None)
    length = len(profile)
    for cell in np.arange(cell_lo, cell_hi, cell_step):
        hi = min(off_hi, length - n * cell - 2)
        for off in np.arange(off_lo, hi, 0.5):
            idx = [int(round(off + k * cell)) for k in range(n + 1)]
            score = sum(profile[i] for i in idx) / (n + 1)
            if score > best[0]:
                best = (score, off, cell)
    if best[1] is None:
        raise CalibrationError("periodischer Fit fehlgeschlagen")
    return best


def _smooth(a, k=3):
    return np.convolve(a, np.ones(k) / k, mode="same")


class CalibrationError(RuntimeError):
    pass


def calibrate(img):
    """Vollstaendige Geometrie aus einem Frame ableiten.

    Wichtig, nicht auf einem Frame mit Fehlerbanner aufrufen. Das Banner
    verzerrt die Kantenprofile. banner_visible() vorher pruefen.
    """
    cx, cy, cw, chh = find_card(img)
    card = img[cy : cy + chh, cx : cx + cw]
    gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Spalten, Band nur ueber dem Spielfeld
    band = gray[int(0.40 * chh) : int(0.68 * chh), :]
    prof_col = _smooth(np.abs(cv2.Sobel(band, cv2.CV_32F, 1, 0, ksize=3)).mean(axis=0))
    _, x0, cell_w = _fit_periodic(prof_col, 0.17 * cw, 0.20 * cw, COLS, 0.0, 0.10 * cw)

    # Zeilen, Zellhoehe an das gemessene Verhaeltnis gekoppelt
    band2 = gray[:, int(0.06 * cw) : int(0.85 * cw)]
    prof_row = _smooth(np.abs(cv2.Sobel(band2, cv2.CV_32F, 0, 1, ksize=3)).mean(axis=1))
    target = cell_w / ASPECT
    _, y0, cell_h = _fit_periodic(
        prof_row,
        target * (1 - ASPECT_TOL),
        target * (1 + ASPECT_TOL),
        ROWS,
        0.30 * chh,
        0.36 * chh,
    )

    calib = {
        "card": [int(cx), int(cy), int(cw), int(chh)],
        "grid_x0": float(cx + x0),
        "grid_y0": float(cy + y0),
        "cell_w": float(cell_w),
        "cell_h": float(cell_h),
    }
    calib.update(_counter_rois(calib))
    # Meterlabel klebt am unteren Brettrand in Spalte 3, deshalb an das
    # Raster gekoppelt und nicht an die Karte
    bottom = calib["grid_y0"] + ROWS * calib["cell_h"]
    mid_x = calib["grid_x0"] + 2.5 * calib["cell_w"]
    calib["roi_meters"] = [
        int(mid_x - 0.85 * cell_w),
        int(bottom - 0.325 * cell_h),
        int(1.70 * cell_w),
        int(0.30 * cell_h),
    ]
    _check(calib, img.shape)
    return calib


def _counter_rois(calib):
    """Zaehlerbereiche als Anteile der Kartenbox. Die Karte ist immer gleich
    aufgebaut, deshalb sind relative Anteile hier zulaessig."""
    cx, cy, cw, ch = calib["card"]

    def box(fx, fy, fw, fh):
        return [int(cx + fx * cw), int(cy + fy * ch), int(fw * cw), int(fh * ch)]

    return {
        # obere Leiste, drei Waehrungen ausserhalb des Minispiels
        "roi_top_orange": box(0.208, 0.014, 0.232, 0.036),
        "roi_top_green": box(0.428, 0.014, 0.232, 0.036),
        "roi_top_pink": box(0.648, 0.014, 0.232, 0.036),
        # untere Leiste, Ressourcen im Minispiel
        "roi_paws": box(0.235, 0.852, 0.245, 0.038),
        "roi_claws": box(0.235, 0.892, 0.245, 0.038),
        "roi_fireballs": box(0.235, 0.932, 0.245, 0.038),
        # Meterzaehler wird spaeter an den Brettrand geheftet, siehe calibrate
        # Skillbutton, der grosse runde Knopf unten rechts
        "skill_button": [int(cx + 0.655 * cw), int(cy + 0.905 * ch)],
        "skill_radius": int(0.075 * cw),
    }


def skill_button_ok(img, calib):
    """Prueft, ob am berechneten Punkt wirklich der Knopf sitzt. Der Knopf ist
    eine grosse helle, kraeftig gefaerbte Scheibe, die Karte drumherum ist
    hell und entsaettigt."""
    x, y = calib["skill_button"]
    r = int(calib["skill_radius"] * 0.55)
    patch = img[max(0, y - r) : y + r, max(0, x - r) : x + r]
    if patch.size == 0:
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    colored = cv2.inRange(hsv, (35, 70, 90), (110, 255, 255))
    return colored.mean() > 60


def _check(calib, shape):
    h, w = shape[:2]
    right = calib["grid_x0"] + COLS * calib["cell_w"]
    bottom = calib["grid_y0"] + ROWS * calib["cell_h"]
    if right > w + 2 or bottom > h + 2:
        raise CalibrationError("Raster liegt ausserhalb des Bildes")
    asp = calib["cell_w"] / calib["cell_h"]
    if abs(asp - ASPECT) > ASPECT * ASPECT_TOL * 1.5:
        raise CalibrationError("Zellverhaeltnis %.3f unplausibel" % asp)


def cell_center(calib, row, col):
    """row und col sind 0 basiert, row 0 ist oben, col 0 ist links."""
    x = calib["grid_x0"] + (col + 0.5) * calib["cell_w"]
    y = calib["grid_y0"] + (row + 0.5) * calib["cell_h"]
    return int(round(x)), int(round(y))


def cell_rect(calib, row, col):
    x = int(round(calib["grid_x0"] + col * calib["cell_w"]))
    y = int(round(calib["grid_y0"] + row * calib["cell_h"]))
    return x, y, int(round(calib["cell_w"])), int(round(calib["cell_h"]))


def median_calib(samples):
    """Mittelt mehrere Kalibrierungen ueber den Median. Damit kippt die
    Geometrie nicht wegen eines einzelnen unguenstigen Frames, so wie bei den
    beobachteten 130,9 statt 134,7 Pixel Zellhoehe."""
    keys = ["grid_x0", "grid_y0", "cell_w", "cell_h"]
    out = dict(samples[-1])
    for key in keys:
        out[key] = float(np.median([s[key] for s in samples]))
    out["card"] = [int(np.median([s["card"][i] for s in samples])) for i in range(4)]
    out.update(_counter_rois(out))
    bottom = out["grid_y0"] + ROWS * out["cell_h"]
    mid_x = out["grid_x0"] + 2.5 * out["cell_w"]
    out["roi_meters"] = [int(mid_x - 0.85 * out["cell_w"]),
                         int(bottom - 0.325 * out["cell_h"]),
                         int(1.70 * out["cell_w"]),
                         int(0.30 * out["cell_h"])]
    return out


# ----------------------------------------------------------------------------
# Objekterkennung
# ----------------------------------------------------------------------------
_TPL_CACHE = {}


def load_templates(directory=TEMPLATE_DIR):
    """Alle Templates, Objekte wie auch Banner. Wird gecacht, weil es pro
    Frame mehrfach gebraucht wird.

    Zuerst wird im Lernordner gesucht, dann im mitgelieferten Ordner. Damit
    gewinnt immer das selbst Gelernte.
    """
    if directory in _TPL_CACHE:
        return _TPL_CACHE[directory]
    learned, _ = _learned_dirs()
    templates = {}
    bundled = None if _only_learned() else directory
    for name in OBJECT_TYPES + NON_BOARD_TEMPLATES:
        for base in (learned, bundled):
            if not base:
                continue
            path = os.path.join(base, name + ".png")
            if os.path.exists(path):
                img = cv2.imread(path)
                if img is not None:
                    templates[name] = img
                    break
    _TPL_CACHE[directory] = templates
    return templates


def forget_templates():
    """Zwischenspeicher leeren, nach dem Lernen noetig."""
    _TPL_CACHE.clear()
    _DIGITS.clear()
    _SCALE_CACHE.clear()


def board_templates(templates=None):
    """Nur die Templates, die auf dem Spielfeld gesucht werden.

    Der Pfeil ist hier absichtlich dabei, obwohl er kein Objekt ist. read_grid
    prueft ihn mit und verwirft den Treffer, damit er nicht als unbekanntes
    Objekt gemeldet wird.
    """
    templates = templates or load_templates()
    skip = [n for n in NON_BOARD_TEMPLATES if n != "arrow"]
    return {k: v for k, v in templates.items() if k not in skip}


_SCALE_CACHE = {}


def _scaled(template, cell_w, ref_cell_w):
    """Template auf die aktuelle Zellgroesse bringen, mit Zwischenspeicher.

    Ohne Speicher wurde jedes Template fuer jede der 25 Zellen neu skaliert,
    also 225 Skalierungen pro Bild statt neun. Das war der groesste Posten
    beim Brett lesen.
    """
    factor = cell_w / ref_cell_w
    if abs(factor - 1.0) < 0.02:
        return template
    key = (id(template), round(factor, 4))
    hit = _SCALE_CACHE.get(key)
    if hit is None:
        h, w = template.shape[:2]
        hit = cv2.resize(template,
                         (max(4, int(w * factor)), max(4, int(h * factor))))
        if len(_SCALE_CACHE) > 200:
            _SCALE_CACHE.clear()
        _SCALE_CACHE[key] = hit
    return hit


# Die Pyramide ist halbtransparent und aehnelt der leeren Kachel, deshalb
# braucht sie eine hoehere Huerde als die kontrastreichen Power-ups.
THRESHOLDS = {"pyramid": 0.74, "figure": 0.60, "arrow": 0.55}
DEFAULT_THRESHOLD = 0.62


def read_grid(img, calib, templates, ref_cell_w=87.5, threshold=None,
              figure=None):
    """5x5 Matrix mit Objektnamen. Leere Zelle ist None, unbekanntes Objekt
    ist '?'. Ein Objekt in der unteren Zeile ist teils vom Mauersims und vom
    Meterlabel verdeckt, deshalb wird nur der obere Teil der Zelle geprueft."""
    grid = [[None] * COLS for _ in range(ROWS)]
    scores = [[0.0] * COLS for _ in range(ROWS)]
    powerups = [t for t in templates if t in POWERUPS]
    # Der gelbe Richtungspfeil ist bunt und kommt durch den Farbvorfilter. Er
    # wird mitgeprueft und danach verworfen, sonst waere er ein unbekanntes
    # Objekt und wuerde die Warteschlange des Assistenten fuellen.
    arrow = load_templates().get("arrow")
    for r in range(ROWS):
        for c in range(COLS):
            patch = search_patch(img, calib, r, c)
            if patch.size == 0:
                continue
            # Vorfilter ueber die Farbe. Das Brett ist blau, jedes Power-up
            # ist kraeftig orange, gruen, rosa oder gelb. Die Pruefung kostet
            # etwa 0,2 ms je Zelle, ein Templatevergleich das Vielfache. Ohne
            # bunte Pixel muss also nur die Pyramide geprueft werden.
            colourful = has_object_colour(img, calib, r, c)
            names = (powerups + ["pyramid"]) if colourful else ["pyramid"]
            if colourful and arrow is not None:
                names = names + ["arrow"]
            best_name, best_val, best_margin = None, 0.0, -9.0
            for name in names:
                tpl = templates.get(name)
                if tpl is None:
                    continue
                tpl_s = _scaled(tpl, calib["cell_w"], ref_cell_w)
                if tpl_s.shape[0] > patch.shape[0] or tpl_s.shape[1] > patch.shape[1]:
                    continue
                val = float(cv2.matchTemplate(patch, tpl_s, cv2.TM_CCOEFF_NORMED).max())
                need = THRESHOLDS.get(name, threshold or DEFAULT_THRESHOLD)
                if r == ROWS - 1:
                    need -= 0.06  # untere Zeile ist von Sims und Meterlabel verdeckt
                margin = val - need  # macht Typen mit anderer Huerde vergleichbar
                if margin > best_margin:
                    best_name, best_val, best_margin = name, val, margin
            if best_name == "arrow" and best_margin >= 0:
                continue  # Richtungspfeil, kein Objekt
            if best_name is not None and best_margin >= 0:
                grid[r][c] = best_name
                scores[r][c] = best_val
            elif colourful and figure_body_fraction(img, calib, r, c) < FIGURE_BODY_MIN:
                # Bunt, aber kein Template passt. Zwei Ausnahmen.
                # Erstens die Figur selbst, die hat bunte Augen.
                # Zweitens der gelbe Richtungspfeil. Er steht immer direkt
                # neben der Figur und zeigt die zuletzt gegangene Richtung.
                # Farbe und dunkler Glow trennen ihn nicht von Power-ups,
                # gemessen ueberlappen beide Merkmale vollstaendig. Die Lage
                # neben der Figur trennt dagegen eindeutig.
                if figure and _is_cross_neighbour(figure, r, c):
                    continue
                grid[r][c] = "?"
                scores[r][c] = best_val
    return grid, scores


def _is_cross_neighbour(figure, row, col):
    """Liegt die Zelle direkt ueber, unter, links oder rechts der Figur?"""
    fr, fc = (figure["row"], figure["col"]) if isinstance(figure, dict) else figure
    return abs(fr - row) + abs(fc - col) == 1


def search_patch(img, calib, row, col):
    """Suchbereich einer Zelle. Etwas groesser als die Zelle, weil Icons nicht
    exakt zentriert sitzen. Nach unten begrenzt, weil die untere Zeile vom
    Mauersims und vom Meterlabel verdeckt wird."""
    x, y, w, h = cell_rect(calib, row, col)
    pad_x = int(0.12 * w)
    pad_y = int(0.14 * h)
    y1 = max(0, y - pad_y)
    y2 = min(img.shape[0], y + h - int(0.05 * h))
    x1 = max(0, x - pad_x)
    x2 = min(img.shape[1], x + w + pad_x)
    return img[y1:y2, x1:x2]


# Anteil kraeftig bunter Pixel, ab dem eine Zelle als moegliches Power-up
# gilt. Ueber die Beispielbilder gemessen, Power-ups liegen bei 4 bis 9
# Prozent, leere Kacheln und Pyramiden bei 0. Die Figur selbst ist ebenfalls
# bunt, ihre Zelle wird deshalb beim Eintragen in die Karte uebersprungen.
OBJECT_COLOUR_MIN = 1.5


def has_object_colour(img, calib, row, col):
    """Billige Vorpruefung, ob in der Zelle ueberhaupt etwas Buntes liegt.

    Ersetzt das fruehere Merkmal 'dunkler Glow'. Das trennte nicht, denn
    dunkle Pixel gibt es auch auf leeren Kacheln, gemessen 0 bis 39 Prozent
    bei Power-ups wie bei leeren Feldern. Die Farbe trennt dagegen sauber,
    weil das Brett durchgehend blau ist.
    """
    patch = search_patch(img, calib, row, col)
    if patch.size == 0:
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = (s > 110) & (v > 110) & ((h < 80) | (h > 140))
    return 100.0 * mask.mean() >= OBJECT_COLOUR_MIN


# Die Figur ist ein dunkler Klumpen mit zwei leuchtend gelben Augen. Dieses
# Merkmal ist am Brett einzigartig und funktioniert auch dann, wenn der Sprite
# am linken Brettrand angeschnitten wird. Templatematching scheiterte dort.
HSV_EYE_LO = (18, 120, 170)
HSV_EYE_HI = (36, 255, 255)
HSV_BODY_LO = (0, 0, 0)
HSV_BODY_HI = (180, 255, 85)


# Optionaler Farbmodus. Wenn die Spielfigur eine Farbe hat, die am Brett
# sonst nicht vorkommt, ist eine Farbmaske die robusteste Erkennung. Sie
# uebersteht auch den Anschnitt in Spalte 1 und die Laufanimation.
# Brett ist blau, Power-ups orange, gruen, rosa und gelb, Pyramiden
# violettweiss. Ein sattes Rot ist damit eindeutig.
FIGURE_COLOR = None  # z.B. [((0, 150, 120), (8, 255, 255)), ((170, 150, 120), (180, 255, 255))]
FIGURE_COLOR_MIN_AREA = 0.02  # Anteil einer Zellflaeche


def _board_window(img, calib):
    """Suchfenster, links und oben ueber das Raster hinaus, weil der Sprite
    dort hinausragt."""
    gx, gy = int(calib["grid_x0"]), int(calib["grid_y0"])
    gw, gh = int(COLS * calib["cell_w"]), int(ROWS * calib["cell_h"])
    x1 = max(0, gx - int(0.60 * calib["cell_w"]))
    y1 = max(0, gy - int(0.40 * calib["cell_h"]))
    return img[y1 : gy + gh, x1 : gx + gw], x1, y1


def _find_by_color(img, calib):
    if not FIGURE_COLOR:
        return None
    board, x1, y1 = _board_window(img, calib)
    if board.size == 0:
        return None
    hsv = cv2.cvtColor(board, cv2.COLOR_BGR2HSV)
    mask = None
    for lo, hi in FIGURE_COLOR:
        part = cv2.inRange(hsv, lo, hi)
        mask = part if mask is None else cv2.bitwise_or(mask, part)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    need = FIGURE_COLOR_MIN_AREA * calib["cell_w"] * calib["cell_h"]
    best = None
    for i in range(1, n):
        if stats[i][cv2.CC_STAT_AREA] < need:
            continue
        if best is None or stats[i][cv2.CC_STAT_AREA] > best[0]:
            best = (stats[i][cv2.CC_STAT_AREA], cent[i])
    if best is None:
        return None
    return _to_cell(calib, x1 + best[1][0], y1 + best[1][1], "color", None)


def _eye_blobs(board, calib):
    """Kleine leuchtend gelbe Flecken, die in einem dunklen Koerper liegen."""
    hsv = cv2.cvtColor(board, cv2.COLOR_BGR2HSV)
    eyes = cv2.inRange(hsv, HSV_EYE_LO, HSV_EYE_HI)
    body = cv2.inRange(hsv, HSV_BODY_LO, HSV_BODY_HI)
    eyes = cv2.bitwise_and(eyes, cv2.dilate(body, np.ones((9, 9), np.uint8)))
    n, _, stats, cent = cv2.connectedComponentsWithStats(eyes, 8)
    min_area = max(6, int(0.0008 * calib["cell_w"] * calib["cell_h"]))
    max_area = int(0.05 * calib["cell_w"] * calib["cell_h"])
    return [(stats[i], cent[i]) for i in range(1, n)
            if min_area <= stats[i][cv2.CC_STAT_AREA] <= max_area]


def _eye_candidates(board, calib, x1, y1):
    """Erst Augenpaare, dann einzelne Augen. Das einzelne Auge ist der Fall
    Spalte 1, dort schneidet der Brettrand ein Auge weg."""
    blobs = _eye_blobs(board, calib)
    pairs = []
    used = set()
    for i in range(len(blobs)):
        for j in range(i + 1, len(blobs)):
            (sa, ca), (sb, cb) = blobs[i], blobs[j]
            dx, dy = abs(ca[0] - cb[0]), abs(ca[1] - cb[1])
            if dy > 0.12 * calib["cell_h"]:
                continue
            if not 0.08 * calib["cell_w"] < dx < 0.45 * calib["cell_w"]:
                continue
            used.add(i)
            used.add(j)
            pairs.append((min(sa[cv2.CC_STAT_AREA], sb[cv2.CC_STAT_AREA]) - dy,
                          x1 + (ca[0] + cb[0]) / 2, y1 + (ca[1] + cb[1]) / 2, "eyes"))
    singles = [(s[cv2.CC_STAT_AREA], x1 + c[0], y1 + c[1], "eye_single")
               for k, (s, c) in enumerate(blobs) if k not in used]
    pairs.sort(reverse=True)
    singles.sort(reverse=True)
    return pairs + singles


def _looks_like_claw(img, calib, px, py, templates):
    """Die gelbe Kralle besteht aus zwei Strichen und koennte als Augenpaar
    durchgehen. Deshalb ausdruecklich ausschliessen."""
    if not templates or "claw" not in templates:
        return False
    half_w = int(0.32 * calib["cell_w"])
    half_h = int(0.30 * calib["cell_h"])
    patch = img[max(0, int(py) - half_h) : int(py) + half_h,
                max(0, int(px) - half_w) : int(px) + half_w]
    tpl = _scaled(templates["claw"], calib["cell_w"], 87.5)
    if patch.shape[0] < tpl.shape[0] or patch.shape[1] < tpl.shape[1]:
        return False
    return cv2.matchTemplate(patch, tpl, cv2.TM_CCOEFF_NORMED).max() > 0.60


# Signatur der Figur, Anteil dunkler und entsaettigter Pixel in der Zelle.
# Gemessen ueber vier Screenshots, die Figur liegt bei 15 bis 19 Prozent,
# Pyramiden und Power-ups unter 1,3 Prozent. Damit ist das der schaerfste
# Unterschied, den ich gefunden habe, und er funktioniert auch dann, wenn der
# Sprite am linken Brettrand angeschnitten wird.
FIGURE_BODY_MIN = 5.0


def figure_body_fraction(img, calib, row, col):
    patch = search_patch(img, calib, row, col)
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    return 100.0 * ((hsv[:, :, 2] < 90) & (hsv[:, :, 1] < 120)).mean()


def _find_by_body(img, calib):
    """Zelle mit der staerksten Figursignatur.

    Ersetzt Templatematching als Hauptweg. Das Template scheiterte, wenn
    Nachbarfelder anders aussahen als beim Ausschneiden, im Feld gemessen mit
    0,505 statt der noetigen 0,62. Danach griff die Augensuche und hielt den
    Blitz eines orangen Tickets fuer ein Augenpaar.
    """
    best = (0.0, None, None)
    for row in range(ROWS):
        for col in range(COLS):
            frac = figure_body_fraction(img, calib, row, col)
            if frac > best[0]:
                best = (frac, row, col)
    if best[0] < FIGURE_BODY_MIN:
        return None
    return dict(row=best[1], col=best[2], how="body", score=round(best[0], 1))


def find_figure(img, calib, templates=None):
    """Zeile und Spalte der Figur, in drei Stufen.

    1. Farbmaske, falls FIGURE_COLOR gesetzt ist. Robusteste Variante
    2. Templatematching, praezise, greift aber nicht bei Anschnitt am linken
       Rand und nicht mitten in der Laufanimation
    3. Augen. Ein Paar ueberall, ein einzelnes Auge nur in Spalte 1, weil dort
       der Brettrand eines wegschneidet

    Gibt None zurueck, wenn nichts sicher ist. Der Bot fuehrt seine Position
    ohnehin selbst mit und braucht die Erkennung nur zum Start und beim
    resync, dann darf er auf einen ruhigen Frame warten.
    """
    by_color = _find_by_color(img, calib)
    if by_color:
        return by_color

    by_body = _find_by_body(img, calib)
    if by_body:
        return by_body

    board, x1, y1 = _board_window(img, calib)
    if board.size == 0:
        return None

    if templates and "figure" in templates:
        tpl = _scaled(templates["figure"], calib["cell_w"], 87.5)
        if board.shape[0] >= tpl.shape[0] and board.shape[1] >= tpl.shape[1]:
            res = cv2.matchTemplate(board, tpl, cv2.TM_CCOEFF_NORMED)
            _, val, _, loc = cv2.minMaxLoc(res)
            if val >= 0.62:
                return _to_cell(calib, x1 + loc[0] + tpl.shape[1] / 2,
                                y1 + loc[1] + tpl.shape[0] / 2, "template", val)

    for _, px, py, how in _eye_candidates(board, calib, x1, y1):
        col = int(np.floor((px - calib["grid_x0"]) / calib["cell_w"]))
        row = int(np.floor((py - calib["grid_y0"]) / calib["cell_h"]))
        if how == "eye_single" and col > 0:
            continue  # einzelnes Auge nur am linken Rand zulassen
        # Der Blitz eines orangen Tickets sieht wie ein Augenpaar aus. Nur
        # gelten lassen, was in einer dunklen Zelle liegt.
        if 0 <= row < ROWS and 0 <= col < COLS:
            if figure_body_fraction(img, calib, row, col) < FIGURE_BODY_MIN * 0.4:
                continue
        if _looks_like_claw(img, calib, px, py, templates):
            continue
        return _to_cell(calib, px, py, how, None)
    return None


def _to_cell(calib, px, py, how, score):
    col = int(np.floor((px - calib["grid_x0"]) / calib["cell_w"]))
    row = int(np.floor((py - calib["grid_y0"]) / calib["cell_h"]))
    if not (-1 <= row < ROWS and -1 <= col < COLS):
        return None
    return dict(row=min(max(row, 0), ROWS - 1), col=min(max(col, 0), COLS - 1),
                how=how, score=score, x=float(px), y=float(py))


# ----------------------------------------------------------------------------
# Zaehler und Banner
# ----------------------------------------------------------------------------
# Referenzzellbreite der Bannertemplates. Sie wurden aus 1080er Aufnahmen
# geschnitten, dort ist eine Zelle 164 Pixel breit.
BANNER_REF_CELL_W = 164.0
BANNER_BADGE_MIN = 0.60
BANNER_TEXT_MIN = 0.48  # bei kleiner Fenstergroesse sinkt der Score deutlich
BANNER_TEXT_MARGIN = 0.08  # Abstand zum zweitbesten Text, sonst unknown


def banner_roi(img, calib):
    """Bereich, in dem das Fehlerbanner erscheint."""
    gx = int(calib["grid_x0"])
    gy = int(calib["grid_y0"] + 1.2 * calib["cell_h"])
    gw = int(COLS * calib["cell_w"])
    gh = int(2.2 * calib["cell_h"])
    return img[max(0, gy) : gy + gh, max(0, gx) : gx + gw]


def _banner_score(img, calib, name):
    tpl = load_templates().get(name)
    if tpl is None:
        return 0.0
    roi = banner_roi(img, calib)
    tpl = _scaled(tpl, calib["cell_w"], BANNER_REF_CELL_W)
    if roi.size == 0 or roi.shape[0] < tpl.shape[0] or roi.shape[1] < tpl.shape[1]:
        return 0.0
    return float(cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED).max())


def banner_visible(img, calib):
    """Erkennt das Fehlerbanner am Ausrufezeichen links im Kasten.

    Farbstatistik allein reichte nicht, sie sprach auch auf den Skilleffekt,
    auf Ticketregen und auf eine Pyramidenzerstoerung an. Das Badge trennt
    dagegen sauber, echte Banner liegen bei 0,85 bis 1,00 und die drei
    Fehlausloeser bei 0,25 bis 0,30.
    """
    return _banner_score(img, calib, "banner_badge") >= BANNER_BADGE_MIN


def classify_banner(img, calib):
    """Rueckgabe None, 'move', 'insufficient' oder 'unknown'.

    'move'          Bedienfehler, Klick ausserhalb des Kreuzes oder auf die
                    Figur selbst. Neu einlesen und weitermachen
    'insufficient'  eine Ressource ist leer. Der Text lautet 'Insufficient
                    Attack(s).' bei Krallen, das Wort danach wechselt je
                    Ressource, deshalb wird nur 'Insufficient' geprueft.
                    Welche Ressource fehlt, folgt aus der versuchten Aktion
    'unknown'       alles andere. Dann anhalten statt raten
    """
    if not banner_visible(img, calib):
        return None
    # Beide Texttemplates deckten denselben Bereich ab, deshalb sind ihre
    # Scores direkt vergleichbar. Der bessere gewinnt, aber nur mit Abstand.
    scores = {
        "move": _banner_score(img, calib, "banner_text_move"),
        "insufficient": _banner_score(img, calib, "banner_text_insufficient"),
    }
    best = max(scores, key=scores.get)
    other = min(scores, key=scores.get)
    if scores[best] < BANNER_TEXT_MIN:
        return "unknown"
    if scores[best] - scores[other] < BANNER_TEXT_MARGIN:
        return "unknown"
    return best


GLYPH_W = 18
GLYPH_H = 26
DIGIT_DIR = os.path.join(os.path.dirname(__file__), "digits")

# Die obere Leiste hat helle Ziffern auf dunklem Grund, die untere dunkle
# Ziffern auf heller Karte. Deshalb je Bereich die passende Polaritaet.
POLARITY = {
    "roi_top_orange": "bright",
    "roi_top_green": "bright",
    "roi_top_pink": "bright",
    "roi_paws": "dark",
    "roi_claws": "dark",
    "roi_fireballs": "dark",
    "roi_meters": "bright",
}
# Ein einziger, gemeinsamer Ziffernsatz fuer alle Zaehler. Die Ziffern sind
# oben und unten dieselben Formen, nur die Polaritaet unterscheidet sich. Mit
# passender Schwelle ergeben beide dieselbe Maske, deshalb muss nichts doppelt
# gelernt werden.
DIGIT_SET = "shared"
_DIGITS = {}

# Vergleich ueber Bitmapdeckung statt Korrelation. Bei zweifarbigen Glyphen ist
# das deutlich stabiler, ein einzelnes verrauschtes Referenzbild kann nicht
# mehr die ganze Ziffer unlesbar machen.
DIGIT_MIN_SCORE = 0.82
DIGIT_MIN_MARGIN = 0.02


def _digit_templates(polarity=DIGIT_SET):
    """Mehrere Referenzbilder pro Ziffer. Ordnerstruktur
    digits/shared/<ziffer>/<n>.png. Der Parameter bleibt der Kompatibilitaet
    wegen erhalten, es wird immer der gemeinsame Satz geliefert."""
    polarity = DIGIT_SET
    if polarity in _DIGITS:
        return _DIGITS[polarity]
    table = {}
    _, learned_digits = _learned_dirs()
    bundled = None if _only_learned() else os.path.join(DIGIT_DIR, polarity)
    bases = [b for b in (learned_digits, bundled) if b]
    for d in "0123456789":
        samples = []
        for base in bases:
            folder = os.path.join(base, d)
            if os.path.isdir(folder):
                for fn in sorted(os.listdir(folder)):
                    if fn.endswith(".png"):
                        img = cv2.imread(os.path.join(folder, fn),
                                         cv2.IMREAD_GRAYSCALE)
                        if img is not None:
                            samples.append(img)
            legacy = os.path.join(base, d + ".png")
            if os.path.exists(legacy):
                img = cv2.imread(legacy, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    samples.append(img)
        if samples:
            table[d] = [cv2.resize(s, (GLYPH_W, GLYPH_H)) for s in samples]
    _DIGITS[polarity] = table
    return table


def digit_stats():
    """Wie viele Referenzbilder pro Ziffer vorhanden sind. Fuer Diagnose."""
    return {DIGIT_SET: {d: len(v)
                        for d, v in sorted(_digit_templates().items())}}


def segment_digits(img, roi, polarity, scale=3):
    """Zerlegt einen Zaehlerbereich in einzelne Ziffernbilder.

    Kommas, das 'm' beim Meterzaehler und Rahmenteile werden ueber Groesse,
    Seitenverhaeltnis und Hoehe verworfen.
    """
    x, y, w, h = roi
    crop = img[max(0, y) : y + h, max(0, x) : x + w]
    if crop.size == 0:
        return []
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if polarity == "bright":
        binary = cv2.inRange(gray, 175, 255)
    else:
        # 140 statt 100. Bei 100 wurde nur der dunkelste Kern der Ziffer
        # erfasst und die Form fiel duenner aus als oben. Mit 140 sind beide
        # Masken gleich dick und ein gemeinsamer Ziffernsatz reicht.
        binary = cv2.inRange(gray, 0, 140)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    colour = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV), (gray.shape[1],
                                                                gray.shape[0]),
                        interpolation=cv2.INTER_NEAREST)

    boxes = []
    for s in stats[1:]:
        gx, gy, gw, gh, area = s[0], s[1], s[2], s[3], s[4]
        if area < 50:
            continue
        if gx <= 1:  # Symbol am linken Rand des Bereichs
            continue
        if gh > 0.95 * binary.shape[0]:
            continue
        ratio = gw / float(gh)
        if ratio < 0.28 or ratio > 0.98:  # Komma, 'm', Rahmen, Kachelrauschen
            continue
        # Nur obere Leiste. Dort sind die Ziffern weiss und die
        # Waehrungssymbole kraeftig farbig, ein hereinragendes Symbol wird so
        # verworfen. Unten sind die Ziffern selbst marineblau und damit stark
        # gesaettigt, dort wuerde die Pruefung echte Ziffern wegwerfen.
        if polarity == "bright":
            sat = colour[gy:gy + gh, gx:gx + gw, 1]
            sel = labels[gy:gy + gh, gx:gx + gw] > 0
            if sel.any() and float(sat[sel].mean()) > 90:
                continue
        boxes.append((gx, gy, gw, gh))
    if not boxes:
        return []
    ref_h = float(np.median([b[3] for b in boxes]))
    glyphs = []
    for gx, gy, gw, gh in boxes:
        if gh < 0.80 * ref_h or gh > 1.25 * ref_h:
            continue
        glyphs.append((gx, binary[gy : gy + gh, gx : gx + gw]))
    glyphs.sort(key=lambda t: t[0])
    return [g for _, g in glyphs]


def _classify_glyph(glyph, table):
    """Beste Ziffer plus Score. Score ist die Bitmapdeckung, 1,0 ist gleich."""
    g = cv2.resize(glyph, (GLYPH_W, GLYPH_H))
    gb = (g > 127)
    ranked = []
    for d, samples in table.items():
        best = max((gb == (s > 127)).mean() for s in samples)
        ranked.append((best, d))
    ranked.sort(reverse=True)
    if not ranked:
        return None, 0.0
    best_score, best_digit = ranked[0]
    margin = best_score - (ranked[1][0] if len(ranked) > 1 else 0.0)
    if best_score < DIGIT_MIN_SCORE or margin < DIGIT_MIN_MARGIN:
        return None, best_score
    return best_digit, best_score


def read_number(img, roi_key, calib, debug=False):
    """Zahl aus einem Zaehlerbereich lesen.

    Rueckgabe None bei unlesbar. Der Aufrufer behandelt None als 'keine
    Information' und niemals als 0, sonst wuerde ein Lesefehler wie ein
    Verbrauch aussehen.
    """
    polarity = POLARITY[roi_key]
    table = _digit_templates()
    if not table:
        return None
    glyphs = segment_digits(img, calib[roi_key], polarity)
    if not glyphs:
        return (None, "keine Ziffern gefunden") if debug else None
    out = []
    for i, glyph in enumerate(glyphs):
        digit, score = _classify_glyph(glyph, table)
        if digit is None:
            return (None, "Zeichen %d unsicher, Score %.3f" % (i + 1, score)) if debug else None
        out.append(digit)
    try:
        value = int("".join(out))
    except ValueError:
        return (None, "keine Zahl") if debug else None
    return (value, "ok") if debug else value


COUNTER_KEYS = [
    "roi_top_orange",
    "roi_top_green",
    "roi_top_pink",
    "roi_paws",
    "roi_claws",
    "roi_fireballs",
    "roi_meters",
]


def read_counters(img, calib):
    return {k.replace("roi_", ""): read_number(img, k, calib) for k in COUNTER_KEYS}


# ----------------------------------------------------------------------------
# Debugbild
# ----------------------------------------------------------------------------
def draw_overlay(img, calib, grid=None, figure=None, counters=None):
    vis = img.copy()
    cx, cy, cw, ch = calib["card"]
    cv2.rectangle(vis, (cx, cy), (cx + cw, cy + ch), (200, 200, 0), 1)
    for r in range(ROWS):
        for c in range(COLS):
            x, y, w, h = cell_rect(calib, r, c)
            cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 255), 1)
            if grid and grid[r][c]:
                cv2.putText(
                    vis, grid[r][c][:9], (x + 3, y + 14), 0, 0.36, (0, 0, 255), 1
                )
    if figure:
        x, y, w, h = cell_rect(calib, figure["row"], figure["col"])
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 2)
    for key in COUNTER_KEYS:
        x, y, w, h = calib[key]
        cv2.rectangle(vis, (x, y), (x + w, y + h), (255, 0, 255), 1)
    bx, by = calib["skill_button"]
    ok = skill_button_ok(img, calib)
    cv2.circle(vis, (bx, by), calib["skill_radius"], (0, 255, 0) if ok else (0, 0, 255), 2)
    cv2.circle(vis, (bx, by), 4, (0, 255, 0) if ok else (0, 0, 255), -1)
    cv2.putText(vis, "skill %s" % ("ok" if ok else "PRUEFEN"),
                (bx - 40, by - calib["skill_radius"] - 8), 0, 0.45,
                (0, 255, 0) if ok else (0, 0, 255), 1)
    if counters:
        txt = " ".join("%s=%s" % (k[:5], v) for k, v in counters.items())
        cv2.putText(vis, txt, (5, 15), 0, 0.34, (255, 255, 255), 1)
    return vis
