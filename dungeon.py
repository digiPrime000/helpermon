"""
Dungeon bot. Works through the dungeon list in rounds.

A different bot from the minigame one. That one solves a grid with cost
arithmetic; this one deals with screens and buttons, so it is a state machine.

Recognition without any game images. The buttons separate unambiguously by
colour and horizontal position, measured across two window sizes.

  Attempt                    blue,   rel. x 0.66, or 0.50 when it stands alone
  Find a Party               blue,   rel. x 0.50
  Clear Previous Difficulty  violet, rel. x 0.34, ignored
  Ad                         violet, rel. x 0.50

That way no third-party image material sits in the program folder, and a game
update only breaks recognition if colours or layout change.

Same principle as the other bot: never click blindly. Every action is verified
by the state change. If the expected state does not arrive, nothing is clicked
again; the bot resets or stops.

  py dungeon.py --probe          shows what is recognised, clicks nothing
  py dungeon.py                  dry run, plans but does NOT click
  py dungeon.py --go             actually clicks
  py dungeon.py --go --rounds 3
  py dungeon.py --list-dungeons  short names for --only and --skip

F7 pauses/resumes and F8 aborts globally, even with the emulator window in
focus instead of this console. Touching the real mouse also pauses on its
own, and resumes again once it has been still for a few seconds. See
guard.py. Disable all of that with --no-mouse-guard.
"""

import argparse
import time

import cv2
import numpy as np

import capture
import guard
import vision

# Device aspect ratio. Used to compute away the emulator window's title bar
# without detecting it.
DEVICE_ASPECT = 1080 / 1920.0

# Colour ranges in HSV
BLUE = ((95, 150, 150), (115, 255, 255))
# Measured on the buttons themselves, H 122 to 125, S 152 to 170, V 235.
# The old lower bound of 125 sat exactly on the edge and found the ad button
# or not depending on the frame.
VIOLET = ((117, 100, 120), (145, 255, 255))

# Expected horizontal position of the buttons, relative to the game width
POS_ATTEMPT = 0.66
POS_CENTER = 0.50
POS_CLEAR = 0.34
POS_TOLERANCE = 0.06

# Attempt sits at 0.66 when Clear Previous Difficulty is next to it. If that
# is missing, Attempt sits centred, measured at Apocalymon Wall 0.501. A
# single blue button in the dialog is therefore always Attempt.
BUTTON_MAX_Y = 0.88
ATTEMPT_W = (0.18, 0.36)

# The Close button on Apocalymon Wall's results screen sits centred at 0.503
# and 0.792, almost exactly where Apocalymon's own Attempt button sits,
# measured 0.501 and 0.756. They are told apart by width, measured Close
# 0.216 against Attempt 0.261 to 0.301. The threshold sits between them with
# margin on both sides.
CLOSE_W_MAX = 0.24

# Give Up during a battle, centred at the very bottom. Measured 0.502 at
# 0.954. Without this detection the bot mistook battle artwork for the
# Attempt button, measured 0.681 at 0.698 with matching size.
POS_GIVEUP_Y = 0.90

# Buttons sit in the lower part of the dialog. The filter keeps artwork out,
# for example DemiDevimon's violet wings at y 0.34.
BUTTON_MIN_Y = 0.45

# Neutral spot for tapping away rewards. Deliberately high up, above any
# dialog. A tap in the middle of the screen acts like the back key when a
# party exists and opens the "disband the party" prompt.
NEUTRAL_TAP_Y = 0.12

# Party slots at Network Defense Ops. Three fields side by side. An empty
# slot is a uniformly dark area, measured standard deviation 0.0, an
# occupied one shows a figure, measured 28 to 56. The dialog itself looks
# identical with and without a party, both buttons sit at the same place, so
# this is the only way to see the difference before clicking.
#
# The half-width is 0.07 and not 0.10 because the wider crop reached past
# the right-hand slot onto the panel's own bright edge. Measured on a real
# frame with one slot filled, half-width against standard deviation:
#
#              left (empty)   middle (full)   right (empty)
#   0.10            3.0            49.9            13.8   <- counted as full
#   0.08            0.0            55.0             8.5
#   0.07            0.0            56.0             3.6
#
# That misread said two slots were filled, so the bot never searched for a
# party, pressed Attempt without one, and Attempt does nothing without one.
PARTY_SLOTS = (0.27, 0.50, 0.73)
PARTY_SLOT_Y = 0.45
PARTY_SLOT_HALF_W = 0.07
PARTY_SLOT_MIN_STD = 12.0

# Bottom nav bar, dungeon tab. Fixed, because the bar does not scroll.
NAV_DUNGEON = (0.377, 0.957)

# The OK button of the pop-ups the game opens after logging in. Measured on
# two of them: centred at 0.475 with the button spanning roughly a third of
# the width, at 0.905 down the screen.
#
# Note what this collides with: POS_GIVEUP_Y is 0.90, so recognise() calls
# any blue button below that near the centre a battle's Give Up button, and
# these pop-ups therefore read as BATTLE. That is only safe to act on while
# waking the game up, when no battle can be running yet -- see wake_up.
POPUP_OK_Y = (0.86, 0.95)
POPUP_OK_FX = (0.35, 0.65)
POPUP_OK_MIN_W = 0.15

# The Claim button of the idle-rewards dialog, measured off a real one:
# centred at 0.597, 0.746, with a violet "Extra Rewards" button immediately
# to its left that watches ads for more.
#
# That violet neighbour is not decoration, it is the identification. The
# Notices dialog puts its "Campaigns" tab at 0.476, 0.733 -- same colour,
# same band, near enough the same width -- and an earlier version pressed it
# repeatedly believing it was Claim. No position test separates those two.
# The pair does: Notices has no violet button anywhere.
POS_CLAIM_Y = (0.68, 0.82)
POS_CLAIM_FX = (0.45, 0.85)
POS_CLAIM_MIN_W = 0.12
CLAIM_PAIR_DY = 0.03

# List cards. They all sit centred at relative x 0.49 and have width 0.77,
# measured across both window sizes. Dialogs and the battle screen show
# different widths, so this signature separates the list unambiguously.
CARD_X = 0.49
CARD_X_TOL = 0.05
CARD_W_MIN = 0.72
CARD_W_MAX = 0.85
LIST_MIN_CARDS = 3

# Dungeon names, in the order of the list from top to bottom. The bot does
# not read them, it counts cards. The names only serve the log, so the
# transcript shows what is being played rather than "card 3".
DUNGEON_NAMES = [
    "Apocalymon Wall",
    "Fight! DemiDevimon",
    "Fight! Bakemon",
    "Fight! Digifactory",
    "Network Defense Ops",
    "Metal Sea",
    "Daily changing dungeon",
]


# Short names for the command line, in the same order as DUNGEON_NAMES
DUNGEON_KEYS = ["apocalymon", "demidevimon", "bakemon", "digifactory",
                "network", "metalsea", "daily"]


def dungeon_index(key):
    """Number of a dungeon from its short name. Partial matches are also
    accepted, so 'apo' is enough."""
    key = key.strip().lower()
    if not key:
        return None
    if key.isdigit():
        n = int(key) - 1
        return n if 0 <= n < len(DUNGEON_KEYS) else None
    matches = [i for i, k in enumerate(DUNGEON_KEYS) if k.startswith(key)]
    return matches[0] if len(matches) == 1 else None


def parse_selection(text, total=7):
    """Translate a list of short names into numbers.

    A leading minus excludes, everything else includes. With no argument, all
    are included except the last, which changes daily.

      --only apocalymon,network     nur diese beiden
      --skip apocalymon             alle ausser Apocalymon
    """
    unknown_names = []
    numbers = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        idx = dungeon_index(part)
        if idx is None:
            unknown_names.append(part)
        else:
            numbers.append(idx)
    return numbers, unknown_names


def dungeon_label(index, von_unten=False, total=7, sichtbar=5):
    """Name of an entry. Counted from the bottom, the first visible entry
    sits at total minus sichtbar."""
    pos = (total - sichtbar + index) if von_unten else index
    if 0 <= pos < len(DUNGEON_NAMES):
        return DUNGEON_NAMES[pos]
    return "Eintrag %d" % (pos + 1)

# Ticket badge in the list card. The ticket count sits at the bottom left,
# possibly with a second counter for ad attempts next to it.
BADGE_X = 0.10
BADGE_W = 0.34  # wide enough for the ticket and ad counters side by side
# Distance of the badge from the card's bottom edge, plus its height
BADGE_BOTTOM_OFF = 0.008
BADGE_H = 0.040

# Whether a counter reads 0 can be read from the leading digit, without any
# digit recognition. The zero has a hole in the middle, measured 0.00 against
# 0.33 to 0.93 for all other digits. The digit set from the minigame does not
# fit here, the font is different.
ZERO_HOLE_MAX = 0.15

# States
LIST = "liste"
DIALOG = "dialog"
DIALOG_PARTY = "dialog_party"
DIALOG_AD = "dialog_werbung"
BATTLE = "kampf"
# Confirmation dialogs with two buttons side by side, cancel on the left,
# confirm on the right. Two cases are known and both are dangerous.
#
#   "Exit the game?"                OK closes the game
#   "Disband the party and leave?"  OK disbands the party
#
# Measured, both buttons sit at the same place, OK at 0.59 to 0.64 and Cancel
# at 0.36 to 0.40, same size each. Hence one state for both, leaving is
# always done via the left button.
EXIT = "sicherheitsabfrage"

# THREE dialogs wear this face, and they do not share an answer. Cancel is
# not always the safe choice, and neither is OK.
#
#   "Exit the game?"                 grey Cancel, OK at 0.561 / 0.652.
#                                    Only ever seen on the title screen.
#                                    OK ends the session, so Cancel.
#   "Disband the party and leave?"   pink Cancel, OK at 0.602 / 0.599.
#                                    Cancel keeps the bot stuck in the
#                                    dungeon panel, OK returns to the list.
#                                    Looks the same whether or not there is
#                                    a party in the slots, confirmed by the
#                                    player -- so the pink test holds for
#                                    the solo case too.
#   "Return to the title screen?"    pink Cancel, OK at 0.602 / 0.599.
#                                    What the back key raises in the game
#                                    with nothing open. OK throws the
#                                    session away, so Cancel.
#
# The last two are the same picture. Measured on real frames of both, the
# sample over the Cancel button is identical to the pixel: 0.648 of it in
# hue 140-150 either way. Nothing in the dialog separates them -- only the
# text does, and this bot reads no text so that it works in every language.
#
# So colour answers one question only: is this the game-exit prompt (grey,
# measured 0.000 in that hue band) or one of the two in-game prompts (pink,
# 0.648). Which of the two in-game ones it is has to come from the caller,
# which knows whether it was just trying to leave a dungeon. See
# dismiss_confirm.
EXIT_CANCEL_SAT_MAX = 100
# Hue of the pink Cancel button, in OpenCV's 0-179 scale. Saturation alone
# cannot carry this: the dialog's own background is blue and just as
# saturated, and sampling that instead of the button is how an exit dialog
# came to be read as a party dialog. Pink is a hue; blue is a different one.
#
# The band starts at 135 and not at 150 because the real button measures
# hue 140-150 with saturation 147. At (150, 179) it scored 0.021 against the
# 0.15 the test asks for, so every pink prompt read as the exit prompt, was
# answered with Cancel, and the bot sat in the dungeon panel until it gave
# up. The grey Cancel of the real exit prompt sits at hue 100-110 and scores
# 0.000 in this band, so the margin is the whole range.
PARTY_PINK_HUE = (135, 175)
UNKNOWN = "unknown"

# The game's exit confirmation. It appears when the back key is pressed and
# no dialog is open. Two buttons side by side at about half height, grey
# Cancel on the left at 0.40 and blue OK on the right at 0.59, measured. OK
# would close the game, so this screen must be reliably recognised and left
# via Cancel.
POS_EXIT_OK = 0.61
POS_EXIT_CANCEL = 0.38
EXIT_TOL = 0.07
EXIT_Y = (0.50, 0.75)
EXIT_W = (0.12, 0.24)


# Every fx/fy in this file is a fraction of the *window image*, because that
# is what they were measured on: 805 x 1390 frames from screen capture, with
# LDPlayer's own chrome part of the picture. GAME_IN_WINDOW says where the
# game sat inside that reference window -- left, top, width, height as
# fractions of it -- and so defines what those numbers mean.
#
# Measured by matching a window frame against the ADB frame of the same
# screen, correlation 0.99: the game is 758 x 1348 at 4, 40. A 40 px tab bar
# on top and a 43 px sidebar on the right are therefore inside every fraction
# in this file.
# Measured in capture.py, next to the window class it describes.
GAME_IN_WINDOW = capture.GAME_IN_WINDOW

# The same chrome in pixels: left, top, right, bottom. It does not scale with
# the window, which is why a fraction of the window image is only worth
# anything once the window has been measured -- at 619 wide the sidebar is
# 6.9 % of the width instead of 5.3 %, and a fraction read as if the window
# were still 805 wide lands 18 device pixels off.
WINDOW_CHROME = capture.WINDOW_CHROME

# The chrome above, cross-checked against the one thing that cannot change:
# the game's own aspect. If what is left after taking the chrome off is not
# that shape, this is not the window layout that was measured, and the frame
# is used as it comes rather than on a guess.
CHROME_ASPECT_TOL = 0.01

# How far a frame's aspect may sit from the device's before it is taken for a
# window frame rather than a bare game frame. The two are 0.5625 against
# 0.5791, so anything under half that gap separates them with room to spare.
DEVICE_ASPECT_TOL = 0.008


# ----------------------------------------------------------------------------
def _window_space(x0, y0, gw, gh):
    """The window a game area of this size and place would sit in.

    Returned rather than the game area itself so that one vocabulary covers
    both sources. See GAME_IN_WINDOW for why that vocabulary is the window
    and not the game.
    """
    fx0, fy0, fw, fh = GAME_IN_WINDOW
    ww, wh = gw / fw, gh / fh
    return (int(round(x0 - ww * fx0)), int(round(y0 - wh * fy0)),
            int(round(ww)), int(round(wh)))


def game_rect(img):
    """Reference rect for every fraction in this file, in this frame's pixels.

    Two kinds of frame arrive here and both have to answer with the same
    vocabulary, because the same constants are read off both.

    A frame from ADB is the game area and nothing else, so what comes back is
    wider than the image and starts above and left of it -- the window the
    game would sit in. Checked against the auto button: found at 0.3778 and
    0.7604 of a device frame, which is 0.3607 and 0.7662 of that window,
    against the measured constant 0.361 and 0.766.

    A window frame has the chrome in it. The game area is found by taking
    WINDOW_CHROME off, and is then stretched back to the reference window, so
    that a window of any size answers with the numbers the reference window
    would have given. At 805 x 1390 that is exactly the frame as it comes,
    which is what every constant here was measured against.

    Anything whose shape does not fit the measured layout is used as it comes.
    That is the old behaviour, and it is the right answer for a picture this
    function has no business making assumptions about.
    """
    h, w = img.shape[:2]
    if abs(w / float(h) - DEVICE_ASPECT) <= DEVICE_ASPECT_TOL:
        return _window_space(0, 0, w, h)
    left, top, right, bottom = WINDOW_CHROME
    gw, gh = w - left - right, h - top - bottom
    if gw > 0 and gh > 0 and abs(gw / float(gh) - DEVICE_ASPECT) <= CHROME_ASPECT_TOL:
        return _window_space(left, top, gw, gh)
    return 0, 0, w, h


def to_pixel(img, fx, fy):
    """Relative position in window pixels."""
    x0, y0, gw, gh = game_rect(img)
    return int(round(x0 + fx * gw)), int(round(y0 + fy * gh))


def find_buttons(img, colour, min_area=0.004, min_y=BUTTON_MIN_Y):
    """Find wide, strongly coloured buttons."""
    x0, y0, gw, gh = game_rect(img)
    mask = cv2.inRange(cv2.cvtColor(img, cv2.COLOR_BGR2HSV), *colour)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 15), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area * gw * gh:
            continue
        # The ad button, at about 7 to 1, is clearly wider than the others.
        # With the old upper bound of 6 it fell through and the bot treated
        # the dialog as unknown.
        if not 1.2 < w / max(h, 1) < 9.0:
            continue
        fx = (x + w / 2.0) / gw
        fy = (y + h / 2.0 - y0) / gh
        if fy < min_y:
            continue
        out.append({"fx": fx, "fy": fy, "fw": w / gw, "fh": h / gh})
    out.sort(key=lambda b: b["fy"])
    return out


def near(value, target, tol=POS_TOLERANCE):
    return abs(value - target) <= tol


def list_cards(img, with_size=False):
    """Vertical centres of the list entries, from top to bottom.

    Detected live instead of read from fixed positions. That way it fits any
    scroll position and any window size. With with_size, the card height is
    included too, needed because the first entry is a taller banner and a
    fixed offset from the centre would not hold for it.
    """
    out = []
    for b in find_buttons(img, BLUE, min_area=0.002, min_y=0.0):
        if not near(b["fx"], CARD_X, CARD_X_TOL):
            continue
        if not CARD_W_MIN <= b["fw"] <= CARD_W_MAX:
            continue
        out.append((b["fy"], b["fh"]))
    out.sort()
    return out if with_size else [fy for fy, _ in out]


def badge_crop(img, fy, fh=None):
    """Crop containing a list card's counters.

    The reference point is the card's bottom edge, not its centre. Cards
    vary in height, the first banner is noticeably taller than the rest. With
    a fixed offset from the centre, the crop missed there.
    """
    x0, y0, gw, gh = game_rect(img)
    fh = fh if fh else 0.118
    bottom_list = fy + fh / 2.0
    y = int(y0 + (bottom_list - BADGE_BOTTOM_OFF - BADGE_H) * gh)
    h = int(BADGE_H * gh)
    x = int(x0 + BADGE_X * gw)
    w = int(BADGE_W * gw)
    return img[max(0, y):y + h, max(0, x):x + w]


def badge_glyphs(img, fy, fh=None, scale=4):
    """Characters in the ticket badge, from left to right."""
    crop = badge_crop(img, fy, fh)
    if crop.size == 0:
        return None, []
    big = cv2.resize(crop, (crop.shape[1] * scale, crop.shape[0] * scale),
                     interpolation=cv2.INTER_CUBIC)
    mask = cv2.inRange(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY), 200, 255)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = [s for s in stats[1:]
           if s[4] > 200 and 0.15 < s[2] / max(s[3], 1) < 1.2
           and s[3] > 0.28 * mask.shape[0]]
    out.sort(key=lambda s: s[0])
    return mask, out


def is_zero_digit(mask, stat):
    """Is this digit a zero? Measured by the hole in the middle."""
    glyph = mask[stat[1]:stat[1] + stat[3], stat[0]:stat[0] + stat[2]]
    if glyph.size == 0:
        return False
    glyph = cv2.resize(glyph, (20, 28))
    return float((glyph[9:19, 7:13] > 127).mean()) <= ZERO_HOLE_MAX


def card_has_attempts(img, fy, fh=None):
    """Does this list card still have attempts left?

    Only reads whether a counter's leading digit is a zero. The card has
    either one counter, the tickets, or two, with the ad counter added. It is
    playable if at least one of the two is not at zero.

    Returns None if nothing could be read. The card is then played to be
    safe, not skipped.
    """
    mask, digits = badge_glyphs(img, fy, fh)
    if mask is None or not digits:
        return None
    # Group characters into counters by gap, not by fixed position. A counter
    # looks like n/2, its characters sit close together, while a clear gap
    # separates two counters.
    groups = [[digits[0]]]
    for before, jetzt in zip(digits, digits[1:]):
        gap = jetzt[0] - (before[0] + before[2])
        if gap > 3 * before[2]:
            groups.append([jetzt])
        else:
            groups[-1].append(jetzt)

    # Only the ticket counter, the first group, is evaluated.
    #
    # The ad counter next to it sits on the artwork rather than in a dark
    # box. Its digits merge with the background under thresholding, no
    # threshold from 150 to 215 captured them cleanly. Measured right next to
    # the slash, the hole value is 0.20 for the zero against 0.57 for the
    # two. That does separate them, but with only 0.05 of margin to the
    # threshold, and a wrong call would cost a whole dungeon per day. So it
    # is deliberately not read.
    #
    # Consequence, three outcomes. Tickets present means play, tickets at 0
    # with no ad counter means safe to skip, tickets at 0 with an ad counter
    # means unclear and gets tried. The third case costs one open-and-close,
    # after which the bot remembers the outcome.
    digits = [s for s in groups[0] if s[2] / max(s[3], 1) > 0.55]
    if not digits:
        return None
    if not is_zero_digit(mask, digits[0]):
        return True
    return None if len(groups) > 1 else False


def confirm_kind(img, ok_button):
    """Which confirmation dialog is this, 'beenden' (exit) or 'party'.

    Told apart by the left button: grey for the exit dialog, where OK closes
    the game, pink for the party dialog, where OK is the correct answer.

    "Party" has to be proved, and the proof is pink pixels. It used to be
    enough for the sample to be saturated, which the dialog's blue interior
    also is -- and the sample lands on that interior whenever the two buttons
    are not symmetric about the middle of the screen. Measured on a real exit
    dialog: OK at 0.561, Cancel at 0.383, mirror at 0.439, which is the gap
    between them. That read as party, and the answer to party is OK.

    Anything inconclusive is therefore the exit dialog. Being wrong that way
    costs a Cancel that was not needed; being wrong the other way ends the
    session.
    """
    x0, y0, gw, gh = game_rect(img)
    left = 1.0 - ok_button["fx"]
    # Wide enough to cover the button even when the mirror is off by the
    # measured 0.056, which is what happens on a dialog that is not centred.
    x = int(x0 + (left - 0.09) * gw)
    w = int(0.18 * gw)
    y = int(y0 + (ok_button["fy"] - 0.015) * gh)
    h = int(0.03 * gh)
    patch = img[max(0, y):y + h, max(0, x):x + w]
    if patch.size == 0:
        return "beenden"
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    pink = ((hsv[:, :, 0] >= PARTY_PINK_HUE[0])
            & (hsv[:, :, 0] <= PARTY_PINK_HUE[1])
            & (hsv[:, :, 1] > EXIT_CANCEL_SAT_MAX))
    share = float(np.count_nonzero(pink)) / pink.size
    return "party" if share >= 0.15 else "beenden"


def party_slots_filled(img):
    """How many party slots are filled. Returns a count from 0 to 3."""
    x0, y0, gw, gh = game_rect(img)
    filled = 0
    for fx in PARTY_SLOTS:
        x = int(x0 + (fx - PARTY_SLOT_HALF_W) * gw)
        w = int(2 * PARTY_SLOT_HALF_W * gw)
        y = int(y0 + (PARTY_SLOT_Y - 0.05) * gh)
        h = int(0.10 * gh)
        patch = img[max(0, y):y + h, max(0, x):x + w]
        if patch.size == 0:
            continue
        if float(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).std()) >= PARTY_SLOT_MIN_STD:
            filled += 1
    return filled


# Measured on the real "Now Loading ... Connecting 57.6%" screen, against a
# 799x1387 frame of 1.1 M pixels:
#
#   progress bar advancing 2%        79 px   0.007%
#   one more loading dot            324 px   0.029%
#   the small sprite animating     2025 px   0.183%
#
# Everything that moves on it is tiny. A test asking for 0.2% of the frame
# calls all of that stillness, which is how the loop decided a perfectly
# healthy load was a screen it could not get past.
MOVING_SHARE = 0.0002
# "Did my tap do anything?" wants a blunt one, so a blinking icon does not
# count as an answer.
CHANGED_SHARE = 0.01
# How long the picture has to be literally unchanged before this gives up.
# Not "how many taps did nothing": taps during a load do nothing by
# definition, and counting them is what aborted three good runs. A screen
# that has not altered one pixel in this long really is stuck.
FREEZE_WINDOW = 25.0
FREEZE_SHARE = 0.0002
# How long to wait for a moving screen to settle before tapping it anyway.
# Without this an idle animation on the main screen would be waited on for
# ever.
MOVING_PATIENCE = 8.0
# Least time between two taps while waking the game up. The menus need a
# moment to react and a burst of clicks arrives before any of them has been
# drawn, which reads as "nothing is happening" and starts the loop guessing.
WAKE_TAP_PAUSE = 1.0


def _same_screen(before, after, min_share=CHANGED_SHARE):
    """Did nothing change? The threshold is the caller's decision, see
    MOVING_SHARE and CHANGED_SHARE."""
    if before is None or after is None or before.shape != after.shape:
        return False
    diff = cv2.absdiff(cv2.cvtColor(before, cv2.COLOR_BGR2GRAY),
                       cv2.cvtColor(after, cv2.COLOR_BGR2GRAY))
    return float(np.count_nonzero(diff > 30)) / diff.size < min_share


def popup_ok(img):
    """A pop-up's OK button, or None.

    Found by colour and rough position, not by a remembered pixel, so a
    slightly different card still works. Deliberately narrow: it has to be a
    wide blue button low down and near the middle.
    """
    for b in find_buttons(img, BLUE, min_y=POPUP_OK_Y[0]):
        if (POPUP_OK_Y[0] <= b["fy"] <= POPUP_OK_Y[1]
                and POPUP_OK_FX[0] <= b["fx"] <= POPUP_OK_FX[1]
                and b["fw"] >= POPUP_OK_MIN_W):
            return b
    return None


def claim_button(img):
    """The idle-rewards Claim button, or None.

    A wide blue button in the lower middle WITH a violet one beside it. The
    violet half is what makes it Claim rather than the Notices dialog's
    Campaigns tab, which is otherwise the same button in the same place.
    """
    def in_band(b):
        return POS_CLAIM_Y[0] <= b["fy"] <= POS_CLAIM_Y[1]

    blue = [b for b in find_buttons(img, BLUE, min_y=POS_CLAIM_Y[0])
            if in_band(b) and b["fw"] >= POS_CLAIM_MIN_W
            and POS_CLAIM_FX[0] <= b["fx"] <= POS_CLAIM_FX[1]]
    violet = [b for b in find_buttons(img, VIOLET, min_y=POS_CLAIM_Y[0])
              if in_band(b)]
    for b in blue:
        for v in violet:
            if abs(v["fy"] - b["fy"]) <= CLAIM_PAIR_DY and v["fx"] < b["fx"]:
                return b
    return None


# The auto button on the main game screen: a blue disc with an A between two
# arrows, below and left of the middle. Pressing it makes the game spend the
# tickets by itself.
#
# Measured on a real frame, 805 x 1390. In the band searched below, the blue
# mask finds four things, and only one of them is this button:
#
#   the panel edge        241 x 12 px            far too wide
#   the sun icon           64 x 62, fill 0.62    a rounded square
#   THE AUTO BUTTON        43 x 43, fill 0.72    a disc, 0.053 of the width
#   a bar right of it      49 x 17               too flat
#
# So width and roundness carry it, not position alone.
#
# Roundness does a second job, and this is the useful part. The game dims
# everything behind a dialog, and a dimmed disc loses its edges out of the
# blue range and breaks up. Measured on the same button, twice:
#
#   main screen clear          43 x 43, area 1331   fill 0.72
#   a dialog open over it      42 x 42, area  754   fill 0.43
#
# So a button found at full fill is evidence of both things a caller needs:
# where to tap, and that nothing is covering the screen. 0.65 keeps its
# distance from the dimmed case, which is the error that matters -- failing
# to find the button costs nothing but a press that does not happen.
# The "Stage Failed..." banner: big red letters across the upper third. It
# appears when the character dies, the stage restarts by itself, and nothing
# needs doing about it -- except that it stays until something is clicked,
# and ANY click dismisses it. A tap on the auto button while it is up is
# swallowed by the banner and the press is lost.
#
# Measured, share of saturated red in the band 0.10 to 0.22 of the height:
#
#   the banner (and dimmed by a dialog on top of it)   0.0584
#   the main screen, its red notification badges       0.0053
#   every other frame there is                         0.0000
#
# 0.02 sits between with an order of magnitude either side, and the measured
# banner was a dimmed one, so an undimmed banner scores higher still.
STAGE_FAILED_BAND = (0.10, 0.22)
STAGE_FAILED_RED = 0.02
STAGE_FAILED_HUE = ((0, 120, 120), (8, 255, 255),
                    (170, 120, 120), (179, 255, 255))

# Its own blue range, a little wider than BLUE: this is an icon, not one of
# the flat buttons BLUE was measured on, and its disc is shaded.
AUTO_BLUE = ((95, 120, 120), (115, 255, 255))
POS_AUTO = (0.361, 0.766)
AUTO_BAND = (0.28, 0.45, 0.72, 0.82)
AUTO_W = (0.040, 0.068)
AUTO_ASPECT = (0.80, 1.25)
AUTO_FILL_MIN = 0.65

def stage_failed(img):
    """Is the red Stage Failed banner up?

    Red and not text: reading the words would be text recognition, which
    this bot does without so that it works in every language. The banner is
    the only thing that paints that much saturated red across the top.
    """
    x0, y0, gw, gh = game_rect(img)
    # Clamped, because on an ADB frame the reference rect starts above and
    # left of the image and a negative index would wrap to the far edge.
    top = max(0, int(y0 + STAGE_FAILED_BAND[0] * gh))
    band = img[top:int(y0 + STAGE_FAILED_BAND[1] * gh),
               max(0, x0):x0 + gw]
    if band.size == 0:
        return False
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    low = cv2.inRange(hsv, np.array(STAGE_FAILED_HUE[0]),
                      np.array(STAGE_FAILED_HUE[1]))
    high = cv2.inRange(hsv, np.array(STAGE_FAILED_HUE[2]),
                       np.array(STAGE_FAILED_HUE[3]))
    share = float(np.count_nonzero(low | high)) / low.size
    return share >= STAGE_FAILED_RED


def auto_button(img):
    """The auto button on the main screen, or None if it is not plainly there.

    None is also the answer to "is the main screen really in front, with
    nothing over it". Every dialog in this game is drawn across the middle
    and covers this button, so a caller that finds it has evidence for both
    questions at once -- where to tap, and that it is safe to.
    """
    x0, y0, gw, gh = game_rect(img)
    fx0, fx1, fy0, fy1 = AUTO_BAND
    left = max(0, int(x0 + fx0 * gw))
    top = max(0, int(y0 + fy0 * gh))
    sub = img[top:int(y0 + fy1 * gh), left:int(x0 + fx1 * gw)]
    if sub.size == 0:
        return None
    mask = cv2.inRange(cv2.cvtColor(sub, cv2.COLOR_BGR2HSV),
                       np.array(AUTO_BLUE[0]), np.array(AUTO_BLUE[1]))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not h:
            continue
        fw = w / float(gw)
        if not AUTO_W[0] <= fw <= AUTO_W[1]:
            continue
        if not AUTO_ASPECT[0] <= w / float(h) <= AUTO_ASPECT[1]:
            continue
        if area / float(w * h) < AUTO_FILL_MIN:
            continue
        return {"fx": (left + x + w / 2.0 - x0) / gw,
                "fy": (top + y + h / 2.0 - y0) / gh,
                "fw": fw, "fh": h / float(gh)}
    return None


def violet_beside(button, violet):
    """Is there a violet button at the same height, to the left of this one?

    That pair is the dungeon panel's Clear Previous Difficulty next to
    Attempt, and no confirmation prompt has it. Measured over real frames of
    all three prompts: none carries a violet button within CLAIM_PAIR_DY of
    its OK, while the panel's pair sits at exactly the same fy.
    """
    return any(abs(v["fy"] - button["fy"]) <= CLAIM_PAIR_DY
               and v["fx"] < button["fx"] for v in violet)


def recognise(img):
    """Which screen is visible and where clicking is allowed."""
    blue = find_buttons(img, BLUE, min_y=0.0)
    violet = find_buttons(img, VIOLET, min_y=0.0)
    cards = list_cards(img)

    # Exit confirmation first. It has a blue button of a size and position
    # nothing else has, and a wrong click next to it would be costly.
    exit_ok = next((b for b in blue
                    if near(b["fx"], POS_EXIT_OK, EXIT_TOL)
                    and EXIT_Y[0] <= b["fy"] <= EXIT_Y[1]
                    and EXIT_W[0] <= b["fw"] <= EXIT_W[1]), None)
    # ... unless a violet button sits beside it. Two dialogs put a blue
    # button where the exit prompt's OK is looked for, and both are told
    # apart by their violet neighbour rather than by another position band:
    # the idle-rewards dialog, whose Extra Rewards would be tapped by the
    # "Cancel" that follows, and the dungeon panel while it is still
    # loading. Measured: a panel whose artwork has not arrived yet draws a
    # narrower Attempt, 0.214 against the loaded 0.251, which slips inside
    # EXIT_W -- and the mirrored Cancel then lands on Clear Previous
    # Difficulty. That happened four times in one live dungeon.
    if (exit_ok and len(cards) < LIST_MIN_CARDS and claim_button(img) is None
            and not violet_beside(exit_ok, violet)):
        return {"state": EXIT, "attempt": None, "party": None, "ad": None,
                "clear": None, "blau": blue, "violett": violet,
                "karten": cards, "giveup": None, "exit_ok": exit_ok,
                "exit_kind": confirm_kind(img, exit_ok)}

    # Check for battle next. During a battle there is game artwork that looks
    # very similar to a button. The Give Up button, centred at the very
    # bottom, is unambiguous by contrast.
    giveup = next((b for b in blue
                   if near(b["fx"], POS_CENTER) and b["fy"] > POS_GIVEUP_Y), None)
    if giveup:
        return {"state": BATTLE, "attempt": None, "party": None, "ad": None,
                "clear": None, "blau": blue, "violett": violet,
                "karten": cards, "giveup": giveup}

    # Only buttons at one of the known positions. Without this restriction, a
    # part of a list card at 0.42 was once mistaken for Attempt.
    usable = [b for b in blue
              if BUTTON_MIN_Y <= b["fy"] <= BUTTON_MAX_Y
              and ATTEMPT_W[0] <= b["fw"] <= ATTEMPT_W[1]
              and (near(b["fx"], POS_CENTER) or near(b["fx"], POS_ATTEMPT))]
    in_range = lambda b: BUTTON_MIN_Y <= b["fy"] <= BUTTON_MAX_Y
    ad = next((b for b in violet if near(b["fx"], POS_CENTER) and in_range(b)), None)
    clear = next((b for b in violet if near(b["fx"], POS_CLEAR) and in_range(b)), None)

    attempt = party = None
    if len(usable) >= 2:
        # two buttons, the right one is Attempt, the centred one is Find a Party
        attempt = next((b for b in usable if near(b["fx"], POS_ATTEMPT)), None)
        party = next((b for b in usable if near(b["fx"], POS_CENTER)), None)
        if attempt is None:
            attempt = usable[0]
    elif len(usable) == 1:
        attempt = usable[0]

    # Clear Previous Difficulty does not count as evidence of a dialog. The
    # failure screen has violet areas at the same position, and a dialog
    # always has either Attempt or the ad button.
    dialog_open = bool(attempt or ad)
    if dialog_open:
        if attempt and party:
            state = DIALOG_PARTY
        elif attempt:
            state = DIALOG
        elif ad:
            state = DIALOG_AD
        else:
            state = DIALOG
    elif len(cards) >= LIST_MIN_CARDS:
        state = LIST
    else:
        state = UNKNOWN

    ergebnis = {"state": state, "attempt": attempt, "party": party, "ad": ad,
                "clear": clear, "blau": blue, "violett": violet,
                "karten": cards, "giveup": None, "party_voll": 0}
    if state == DIALOG_PARTY:
        ergebnis["party_voll"] = party_slots_filled(img)
    return ergebnis


# ----------------------------------------------------------------------------
class DungeonBot:
    # Click origin, overwritten in __init__. A class default because the
    # offline tests build a bot with __new__ and never run __init__.
    origin = (0, 0)

    # States in which a dungeon dialog is open. Kept as a class attribute so
    # it does not get lost when individual methods are refactored.
    DIALOGS = (DIALOG, DIALOG_PARTY, DIALOG_AD)

    def __init__(self, cap, dry_run=True, log=print, entries=7, skip_last=1,
                 use_ads=True, battle_timeout=90.0, tick=1.0, max_minutes=0,
                 max_attempts=6, max_ads=2, min_battle=6.0, swipes=1,
                 survey_first=True, patience=1.5, only=None, skip=None,
                 debugdir="debug_dungeon"):
        self.cap = cap
        self.max_minutes = max_minutes
        self.deadline = None
        # Click targets are computed in device coordinates, not window
        # pixels. Otherwise window capture would need a conversion via the
        # minigame calibration, and that fails in the menu because no game
        # card is visible there. That is why this used to run over the slow
        # ADB path.
        self.origin, self.device = self._device_size()
        self.dry_run = dry_run
        self.log = log
        self.entries = entries
        self.skip_last = skip_last
        self.use_ads = use_ads
        self.battle_timeout = battle_timeout
        self.tick = tick
        self.stats = {"versuche": 0, "kaempfe": 0, "werbung": 0,
                      "uebersprungen": 0, "unklar": 0, "abgelehnt": 0,
                      "exit_abgefangen": 0}
        self.control = guard.Stop()
        # The bot does not read the ticket count. Instead it detects from
        # elapsed time whether a battle really happened. A battle takes 7 to
        # 40 seconds. If the dialog returns faster, nothing happened, so
        # attempts are used up.
        self.max_attempts = max_attempts
        # Battles measured take about 20 seconds, short ones about 7. Below
        # this threshold it was not a battle but a rejection.
        self.min_battle = min_battle
        # After Attempt the game needs a moment before the dialog goes away.
        # Measured about 3 seconds at Apocalymon Wall.
        self.start_timeout = 8.0 * patience
        # Hard upper limits. They should never trigger, but are the last
        # safeguard against a loop I did not foresee. Two ads per dungeon per
        # day, each granting exactly one ticket, gives at most four battles
        # per dungeon and day.
        self.max_ads = max_ads
        self.max_loops = 12
        self.survey_first = survey_first
        # All wait times hang off one factor. The animation windows measured
        # take about half a second longer than assumed, so it is set to 1.5.
        self.patience = patience
        self.pause_short = 0.5 * patience
        self.pause_long = 1.0 * patience
        # Dungeons that have demonstrably yielded nothing more this session.
        # The evidence comes from operation, not from the image. Reading
        # digits on the ad button was too unreliable, and by colour an
        # exhausted button looks the same as a usable one, measured both
        # H 125 S 170 V 235.
        self.exhausted = set()
        # How many cards are visible at the bottom is measured during
        # planning and remembered here, so the names from the bottom are
        # mapped correctly.
        self.visible_at_bottom = 5
        # Dungeon selection as numbers from 0, in list order. only wins over
        # skip, so that an explicit selection is not overridden by a stale
        # skip.
        self.only = set(only) if only else None
        self.skip = set(skip) if skip else set()
        self.swipes = swipes
        self.debugdir = debugdir
        self._saved = 0

    # ------------------------------------------------------------------
    def _device_size(self):
        """Reference frame for clicks: its origin and its size.

        Clicks and frames do not always come from the same picture. In hybrid
        mode the frames are window captures while the clicks go out through
        ADB in device pixels, so the reference has to be taken from the
        device, not from the frame the bot happens to be looking at.

        What comes back is the window the game sits in, expressed in the
        pixels of whatever receives the clicks -- so it is wider than the
        device screen and starts above and left of it. game_rect explains
        why. Every fx/fy in this file then lands on the same spot whichever
        source is in use.
        """
        img = None
        adb = getattr(self.cap, "adb", None)
        # HybridCapture holds an AdbCapture here; AdbCapture holds the path
        # to adb.exe under the same name, and that has no frames to give.
        if hasattr(adb, "grab"):
            try:
                img = adb.grab()
            except Exception:
                img = None
        if img is None:
            try:
                img = self.cap.grab()
            except Exception:
                return (0, 0), (1080, 1920)
        x0, y0, gw, gh = game_rect(img)
        return (x0, y0), (gw, gh)

    def grab(self):
        return self.cap.grab()

    def tap(self, fx, fy, was=""):
        """Click by relative position.

        No image parameter anymore. Clicks go out in device coordinates, the
        image was not needed. It only led to a caller wanting to pass
        info["img"], and not every recognition result provides that key. The
        result was a KeyError in the middle of a run.
        """
        ox, oy = self.origin
        dw, dh = self.device
        x, y = int(round(ox + fx * dw)), int(round(oy + fy * dh))
        if self.dry_run:
            self.log("    [dry run] click %s at rel. %.3f, %.3f, pixel %d,%d" % (was, fx, fy, x, y))
            return
        self.cap.tap(x, y)

    def back(self, only_if_dialog=True, leaving_dungeon=False):
        """Android back key.

        Only press it if a dialog is actually open. If none is open, the game
        answers with "Return to the title screen?", and OK on that throws the
        session away.

        `leaving_dungeon` says what the caller was trying to do, and only a
        caller that was closing a dungeon panel may set it. It is the only
        thing that separates the prompt for that from the one for the title
        screen -- they are the same picture. See dismiss_confirm.
        """
        if only_if_dialog and not self.dry_run:
            state = recognise(self.grab())["state"]
            if state in (LIST, UNKNOWN, BATTLE):
                self.log("    no dialog open, back key not pressed")
                return False
        if self.dry_run:
            self.log("    [Trockenlauf] Zurueck-Taste")
            return
        try:
            self.cap.back()
            time.sleep(self.pause_short)
        except Exception as err:
            self.log("    back key failed: %s" % err)
            return False
        # Check whether we ended up in the exit confirmation
        if not self.dry_run:
            info = recognise(self.grab())
            if info["state"] == EXIT:
                self.dismiss_confirm(info, leaving_dungeon=leaving_dungeon)
                return False
        return True

    def press_auto(self, img=None):
        """Press the auto button once, if the screen plainly allows it.

        Auto makes the game spend its tickets by itself, so it is worth one
        careful press and never a blind one. Everything has to line up: no
        confirmation prompt, no pop-up, no rewards dialog, and the button
        itself sharp and where it belongs -- which cannot be true while
        anything is drawn over the main screen, because the game dims what
        is behind a dialog and the dimmed button fails the roundness test.

        Returns True if it was pressed. The caller must not press again: it
        is a toggle, and a second press turns it back off.
        """
        img = self.grab() if img is None else img
        info = recognise(img)
        if info["state"] in (EXIT, DIALOG, DIALOG_PARTY, DIALOG_AD):
            return False
        if popup_ok(img) is not None or claim_button(img) is not None:
            return False
        if stage_failed(img):
            # Any click at all dismisses this banner, so a press aimed at
            # the auto button would be eaten by it. Leave it: whatever taps
            # next clears it, and the press comes round again.
            self.log("  Stage Failed is up, not pressing auto through it")
            return False
        button = auto_button(img)
        if button is None:
            return False

        before = self._auto_patch(img, button)
        self.log("  pressing the auto button, tickets are spent by the game "
                 "from here")
        self.tap(button["fx"], button["fy"], was="auto")
        if self.dry_run:
            return True
        time.sleep(max(self.pause_long, WAKE_TAP_PAUSE))

        # Say what changed rather than judge it. Whether this button visibly
        # answers a press has not been measured on a real frame yet, so the
        # numbers go in the log and the next run decides the threshold.
        after_img = self.grab()
        found = auto_button(after_img)
        after = self._auto_patch(after_img, found or button)
        self.log("    auto button before %s, after %s" % (before, after))
        return True

    @staticmethod
    def _auto_patch(img, button):
        """Mean colour of the button itself, as three numbers for the log."""
        x0, y0, gw, gh = game_rect(img)
        half = button["fw"] * 0.4
        x = int(x0 + (button["fx"] - half) * gw)
        y = int(y0 + (button["fy"] - half) * gh)
        w = max(1, int(2 * half * gw))
        patch = img[max(0, y):y + w, max(0, x):x + w]
        if patch.size == 0:
            return "nothing"
        return "%d/%d/%d" % tuple(int(v) for v in patch.reshape(-1, 3).mean(0))

    def settled_frame(self, timeout=2.5):
        """A frame the screen has stopped moving in.

        The pre-check reads digits off the list, and digits read while the
        list is still gliding are digits read from a smear -- which returns
        "nothing could be read", which the caller has to treat as "try it".
        Two frames that match is the proof it has come to rest. MOVING_SHARE
        is the threshold for "did anything at all move", which is exactly the
        question here.

        A screen that never settles, because something on it animates,
        returns its last frame rather than waiting for ever.
        """
        previous = self.grab()
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.15)
            current = self.grab()
            if _same_screen(previous, current, MOVING_SHARE):
                return current
            previous = current
        return previous

    def dismiss_confirm(self, info=None, leaving_dungeon=False):
        """Leave a confirmation dialog, differently depending on its kind.

        OK is pressed for exactly one of the three, and only when the caller
        says it was on its way out of a dungeon:

          grey Cancel                     "Exit the game?" -- Cancel, always.
          pink, leaving_dungeon=True      the dungeon's own prompt -- OK,
                                          which is the only way out of the
                                          panel. Cancel leaves the bot in it.
          pink, leaving_dungeon=False     could be "Return to the title
                                          screen?", so Cancel.

        The two pink ones cannot be told apart from the picture, measured
        identical to the pixel, so the caller's intent is the whole of the
        evidence. Being wrong in the cautious direction costs a Cancel that
        was not needed; being wrong the other way costs the session.
        """
        info = info or recognise(self.grab())
        if info["state"] != EXIT:
            return
        ok = info["exit_ok"]
        kind = info.get("exit_kind", "beenden")
        self.stats["exit_abgefangen"] += 1
        if kind == "party" and leaving_dungeon:
            self.log("  leaving the dungeon via OK, back to the list")
            self.tap(ok["fx"], ok["fy"], was="OK, Party verlassen")
        else:
            if kind == "party":
                self.log("  an in-game prompt, but nothing here was leaving "
                         "a dungeon -- Cancel")
            else:
                # Keep the frame. This is the prompt whose OK ends the
                # session, so any surprise about where it came from is worth
                # being able to look at afterwards.
                self.save_unknown(self.grab(), "confirm_beenden")
                self.log("  exit dialog, leaving via Cancel")
            # Cancel sits mirrored relative to OK
            cancel_x = 1.0 - ok["fx"] if ok["fx"] > 0.5 else POS_EXIT_CANCEL
            self.tap(cancel_x, ok["fy"], was="Abbrechen")
        time.sleep(self.pause_long)

    def wait_for(self, states, timeout, was=""):
        """Wait for one of the states. Returns the recognition result or None."""
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            info = recognise(self.grab())
            last = info
            if info["state"] in states:
                return info
            time.sleep(self.tick)
        self.log("    Warten auf %s ohne Erfolg%s"
                 % ("/".join(states), (", " + was) if was else ""))
        return None

    # ------------------------------------------------------------------
    def open_list(self):
        """Open the dungeon list and confirm that it is open.

        Without this confirmation, the bot would tap blindly somewhere after
        a failed click on the tab. That is more dangerous in the menu than
        in the minigame, so it stops here rather than guessing.
        """
        img = self.grab()
        if recognise(img)["state"] == LIST:
            self.log("already in the list")
            return True
        self.tap(*NAV_DUNGEON, was="Dungeon-Reiter")
        if self.dry_run:
            return True
        time.sleep(self.pause_long)
        for _ in range(6):
            if recognise(self.grab())["state"] == LIST:
                self.log("list is open")
                return True
            time.sleep(self.pause_short)
        self.log("list not recognised. Am I on the main screen, and does the "
                 "dungeon tab really sit at rel. %.3f, %.3f?"
                 % NAV_DUNGEON)
        return False

    def wake_up(self, timeout=180.0, max_taps=60, claim_rewards=False,
                start_auto=False):
        """From a just-started game to the dungeon list.

        With `start_auto`, the auto button gets one press along the way, at
        the first moment the main screen is unmistakably clear. See
        press_auto for what "clear" is measured against.

        Returns True once the list is open. Deliberately dumb about what it
        is looking at: the screens between a launch and the main menu are the
        part that changes with every game update, so instead of recognising
        them this repeats the taps whose outcome can be checked -- the
        pop-up OK button and the dungeon tab.

        Two rules keep it out of trouble.

        It waits for a moving screen to settle before tapping, because a
        screen in motion is loading and loading is not a problem to be tapped
        at. It gives that up after MOVING_PATIENCE, so an idle animation on
        the main screen cannot stall it for ever.

        And it only concludes it is stuck when the picture has not altered at
        all for FREEZE_WINDOW seconds. Counting taps that achieved nothing
        was the old test, and it aborted three healthy runs: during a load,
        every tap achieves nothing and that is correct behaviour.

        Only for the cold-start path, where nothing else is open.
        """
        deadline = time.time() + timeout
        started = time.time()
        said = 0.0
        taps = 0
        previous = None
        waiting_since = None
        frozen_ref = None
        frozen_since = time.time()
        stalled = False
        # The back key is a loaded gun on this path: with no dialog open it
        # raises "Exit the game?", whose OK ends the session. It gets one
        # chance, and loses it the moment it produces that dialog.
        back_allowed = True
        # A tap high up gets one go per screen as well, so a screen that
        # ignores it is not tapped at for ever.
        neutral_tried = False
        # Claiming leaves a reward window standing over the dialog, and the
        # Claim button stays visible behind it. Once claiming has happened,
        # a Claim button is no longer evidence of a dialog waiting to be
        # closed with the back key -- the window over it says "Tap to close",
        # and a tap is what it wants.
        claimed = False
        # The auto button is pressed at most once, on the main screen, before
        # the dungeon tab is reached. It is a toggle: a second press would
        # turn it off again, so this is set the moment it is pressed and not
        # when the press is confirmed.
        auto_pressed = False
        banner_taps = 0
        self.log("waiting for the game to be ready, up to %d s" % timeout)

        while time.time() < deadline and taps < max_taps:
            if self.control.is_set():
                return False
            # Plain pause wait, not _time_left(): that one tries to find its
            # way back to the list afterwards, and during wake-up there is
            # no list to find yet.
            while self.control.is_paused() and not self.control.is_set():
                time.sleep(0.2)
            if self.control.is_set():
                return False

            img = self.grab()
            state = recognise(img)["state"]
            if state == LIST:
                self.log("dungeon list is open after %d tap(s), %d s"
                         % (taps, time.time() - started))
                return True
            if state == EXIT:
                # Almost certainly this loop's own doing, from a back key
                # pressed with nothing open. Cancel it -- never OK, which
                # closes the game -- and stop using the back key.
                self.log("  exit prompt is open, cancelling it")
                self._cancel_exit(recognise(img))
                back_allowed = False
                stalled = False
                previous = None
                time.sleep(WAKE_TAP_PAUSE)
                continue
            if state in (DIALOG_PARTY, DIALOG_AD):
                # Already inside the game, on something this bot knows how to
                # handle. Hand over rather than tapping past it.
                self.log("game is up, state %s" % state)
                return self.open_list()

            now = time.time()
            waited = now - started
            if waited - said >= 10:
                said = waited
                self.log("  %d s, %d tap(s), screen reads %s"
                         % (waited, taps, state))

            # Has anything at all altered since the last frame kept for this?
            # Any movement resets the clock; only a picture that stays
            # identical runs it down.
            if frozen_ref is None or not _same_screen(frozen_ref, img,
                                                      FREEZE_SHARE):
                frozen_ref = img
                frozen_since = now
            elif now - frozen_since >= FREEZE_WINDOW and taps > 0:
                self.log("nothing on screen has changed for %d s. Something "
                         "is there that neither the OK button nor the "
                         "dungeon tab gets past -- close it by hand and "
                         "start again." % (now - frozen_since))
                # Keep the screen that stopped it. Every round of this so far
                # has been a screen nobody had seen before, and asking for it
                # by hand afterwards costs a whole run.
                self.save_unknown(img, "wake_stuck")
                return False

            # Moving? Then it is loading. Wait, but not indefinitely. The
            # very first frame counts as moving too: tapping a screen nobody
            # has looked at twice is exactly what this avoids.
            first = previous is None
            moving = not first and not _same_screen(previous, img,
                                                    MOVING_SHARE)
            previous = img
            if first or moving:
                if waiting_since is None:
                    waiting_since = now
                if now - waiting_since < MOVING_PATIENCE:
                    time.sleep(self.pause_short or 0.5)
                    continue
            waiting_since = None

            # BATTLE is deliberately not handled above. A login pop-up's OK
            # button sits where Give Up sits and so reads as a battle, and no
            # battle can be running seconds after the game started.
            ok = popup_ok(img)
            claim = claim_button(img)
            if ok is not None:
                self.tap(ok["fx"], ok["fy"], was="pop-up OK")
            elif claim is not None and claim_rewards and not claimed:
                self.log("  claiming the idle rewards, as asked")
                self.tap(claim["fx"], claim["fy"], was="Claim")
                claimed = True
            elif state == DIALOG or (claim is not None and not claimed):
                # Something recognisably a dialog. The back key is what
                # closes those, and for the rewards dialog it is the only
                # answer that does not spend the idle timer.
                self.log("  closing what is in front with the back key")
                self.back(only_if_dialog=False)
                if state != DIALOG:
                    # Only a guess, so it does not get a second go unless it
                    # turns out to have been right.
                    back_allowed = False
            elif (start_auto and not auto_pressed and banner_taps < 2
                    and stage_failed(img)):
                # Clear the way for the press rather than hope something
                # else clears it. Any tap at all dismisses this banner, and
                # in a live run the tap that did it was the dungeon tab --
                # which opened the list, ended the wake-up, and the press
                # never got its turn. Twice at most: a character that keeps
                # dying puts the banner straight back up, and this is not
                # the loop to fight that in.
                self.log("  Stage Failed is up, tapping it away first")
                self.tap(0.5, NEUTRAL_TAP_Y, was="neutral")
                banner_taps += 1
            elif (start_auto and not auto_pressed
                    and self.press_auto(img)):
                # Before the stalled branches, not after: a main screen with
                # no battle running does not move, so every tap on it reads
                # as stalled and the press would never get its turn. Its own
                # conditions are the stricter test anyway -- a crisp button
                # means no dialog is dimming the screen and no banner is up.
                auto_pressed = True
            elif stalled and not neutral_tried:
                # Unknown, and the last tap achieved nothing. A tap high up
                # is what the game itself asks for on the screens that say
                # "Tap to close" -- the reward window after claiming, and
                # the red Stage Failed banner that follows it on a cold
                # start. It is tried before the back key because it cannot
                # raise the exit prompt, and the back key can.
                self.log("  tapping high up to close what is in front")
                self.tap(0.5, NEUTRAL_TAP_Y, was="neutral")
                neutral_tried = True
            elif stalled and back_allowed:
                self.log("  closing what is in front with the back key")
                self.back(only_if_dialog=False)
                back_allowed = False
            else:
                self.tap(*NAV_DUNGEON, was="touch to start / dungeon tab")
            taps += 1
            if self.dry_run:
                self.log("[dry run] stopping here, nothing was really tapped")
                return True
            # Menus need a moment. A burst of taps lands before the first one
            # has been drawn, and the loop then reads its own impatience as
            # a screen that will not move.
            time.sleep(max(self.pause_long, WAKE_TAP_PAUSE))

            # Did that achieve anything? If not, the next round closes what
            # is in front instead of repeating itself.
            after = self.grab()
            stalled = _same_screen(img, after, CHANGED_SHARE)
            if not stalled:
                # Something moved, so whatever was tried worked; the back key
                # and the tap high up are allowed to be considered again.
                back_allowed = True
                neutral_tried = False

        self.log("gave up waiting for the game after %d tap(s) and %d s."
                 % (taps, time.time() - started))
        if previous is not None:
            self.save_unknown(previous, "wake_timeout")
        return False

    def _cancel_exit(self, info):
        """Press Cancel on the exit prompt. Never OK.

        Separate from dismiss_confirm on purpose: that one also handles the
        party dialog, where OK is right, and the two are told apart by a
        colour test. On this path there is no party to leave -- the game has
        only just started -- so there is nothing to weigh up and no way for a
        misread to close the game.
        """
        ok = info.get("exit_ok") if info else None
        if not ok:
            self.log("    no exit button found, leaving it alone")
            return False
        # Belt and braces: never press the mirrored position when it lands on
        # the idle-rewards dialog's Extra Rewards button.
        if claim_button(self.grab()) is not None:
            self.log("    that is the rewards dialog, not an exit prompt")
            return False
        cancel_x = 1.0 - ok["fx"] if ok["fx"] > 0.5 else POS_EXIT_CANCEL
        self.tap(cancel_x, ok["fy"], was="Cancel, stay in the game")
        time.sleep(max(self.pause_long, WAKE_TAP_PAUSE))
        return True

    def scroll_top(self, swipes=None):
        self._scroll(swipes or self.swipes, up=True)

    def scroll_bottom(self, swipes=None):
        self._scroll(swipes or self.swipes, up=False)

    def _scroll(self, swipes=None, up=True):
        """Scroll the list to the edge.

        One swipe is enough, measured. Then wait half a second, otherwise
        reading happens during the trailing motion and the cards sit at the
        wrong positions.
        """
        swipes = swipes or self.swipes
        ox, oy = self.origin
        dw, dh = self.device
        x = int(ox + 0.5 * dw)
        y_near, y_far = int(oy + 0.30 * dh), int(oy + 0.88 * dh)
        if self.dry_run:
            self.log("    [dry run] scroll list %s"
                     % ("up" if up else "down"))
            return
        for _ in range(swipes):
            if up:
                self._swipe(x, y_near, x, y_far)
            else:
                self._swipe(x, y_far, x, y_near)
            time.sleep(0.5)
        time.sleep(0.5)

    def _swipe(self, x1, y1, x2, y2, ms=300):
        try:
            self.cap.swipe(x1, y1, x2, y2, ms)
        except Exception as err:
            self.log("    swipe failed: %s" % err)

    # ------------------------------------------------------------------
    def return_to_list(self, tries=5):
        """Back to the list, via the tab if necessary.

        Without this, the bot used to get stuck somewhere after a dialog and
        skipped the following cards.
        """
        # back() answers False when the press raised the exit prompt instead
        # of closing anything. Some panels -- the dungeon's own, measured --
        # do not handle the back key at all, and repeating it there only
        # produced the exit prompt three more times in a live run.
        back_allowed = True
        neutral_tried = False
        # Whether the frame before this one showed a dungeon panel. That is
        # the whole evidence for answering the prompt with OK, so it is
        # tracked rather than assumed: a prompt already on screen when this
        # helper was called is none of its doing and gets Cancel.
        panel_before = False
        for i in range(tries):
            info = recognise(self.grab())
            if info["state"] == LIST:
                return True
            if info["state"] == EXIT:
                self.dismiss_confirm(info, leaving_dungeon=panel_before)
                panel_before = False
                continue
            panel_before = info["state"] in self.DIALOGS
            if back_allowed and i < tries - 2 and info["state"] in self.DIALOGS:
                # A dungeon panel is what is open here, so the prompt the
                # back key raises is the dungeon's own and OK is the way out.
                back_allowed = self.back(leaving_dungeon=True)
            elif not neutral_tried:
                # A tap high up, outside whatever panel is in front. In the
                # live run the dungeon's own panel answered the back key
                # with the exit prompt and ignored the dungeon tab, and this
                # is the one remaining way out that cannot do harm.
                self.log("    tapping high up, outside the panel")
                self.tap(0.5, NEUTRAL_TAP_Y, was="neutral")
                neutral_tried = True
            else:
                self.tap(*NAV_DUNGEON, was="Dungeon-Reiter")
            time.sleep(self.pause_long)
        self.log("  could not find the way back to the list")
        return False

    def save_unknown(self, img, tag):
        """Save an unknown screen once, so it can be reproduced later.
        Capped, so a long run does not fill the disk."""
        if self._saved >= 6:
            return None
        import os
        os.makedirs(self.debugdir, exist_ok=True)
        path = os.path.join(self.debugdir, "%s_%02d.png" % (tag, self._saved))
        cv2.imwrite(path, img)
        self._saved += 1
        self.log("  unknown screen saved: %s" % path)
        return path

    def global_index(self, index, label):
        """Number within the overall list, regardless of whether counting is
        from the top or the bottom."""
        if label == "unten":
            return self.entries - self.visible_at_bottom + index
        return index

    def is_selected(self, index, label):
        """Is this dungeon selected?"""
        pos = self.global_index(index, label)
        if self.only is not None:
            return pos in self.only
        return pos not in self.skip

    def label_of(self, index, label):
        """Name instead of card number, for the log only. The bot itself
        keeps counting cards; reading names would be text recognition and
        would break on every game update."""
        return dungeon_label(index, von_unten=(label == "unten"),
                            total=self.entries, sichtbar=self.visible_at_bottom)

    def survey(self, positions, label):
        """Read from the list in advance which dungeons still have attempts.

        From the list and not from the dialog, which saves opening and
        closing per dungeon. The Attempt button is not a reliable witness
        anyway, it is visible even at 0 tickets.

        Only reads whether the ticket counter's leading digit is a zero. The
        ad counter next to it is drawn more faintly and not reliably
        readable, measured Bakemon at 2/2 and at 0/2 ads yield the same
        characters. So the rule is: tickets at 0 with a second counter
        present means unclear, and unclear gets tried rather than skipped.
        """
        playable = []
        # Not self.grab(): this runs right after a scroll.
        img = self.settled_frame()
        for index in positions:
            if not self._time_left():
                break
            if not self.is_selected(index, label):
                self.log("  %-22s not selected" % self.label_of(index, label))
                self.stats["abgewaehlt"] += 1
                continue
            if (label, index) in self.exhausted:
                self.log("  %-22s already exhausted this session"
                         % self.label_of(index, label))
                continue
            cards = list_cards(img, with_size=True)
            if index >= len(cards):
                continue
            fy, fh = cards[index]
            available = card_has_attempts(img, fy, fh)
            if available is False:
                reason = "tickets at 0 and no ads"
            elif available is None:
                playable.append(index)
                reason = "unclear, will try it"
            else:
                playable.append(index)
                reason = "tickets available"
            self.log("  %-22s %s" % (self.label_of(index, label), reason))
        return playable

    def play_entry(self, index, label="", key=None):
        """Open a dungeon and play it until nothing more can be done.

        Reactive loop. Before every action, it checks which screen is
        visible and derives exactly one action from that. The earlier fixed
        sequence broke wherever something unexpected happened in between and
        had to be patched individually. Here, a new screen is one more line.
        """
        key = key if key is not None else (label, index)
        img = self.grab()
        info = recognise(img)
        if not self.dry_run and info["state"] != LIST:
            self.log("  not in the list, state %s" % info["state"])
            self.stats["unklar"] += 1
            self.save_unknown(img, "keine_liste")
            if not self.return_to_list():
                return
            img = self.grab()
            info = recognise(img)

        cards = info["karten"] if info["karten"] else list_cards(img)
        if index >= len(cards):
            self.log("  %s not visible, %d cards recognised"
                     % (self.label_of(index, label), len(cards)))
            self.stats["uebersprungen"] += 1
            return
        self.tap(CARD_X, cards[index], was=self.label_of(index, label))
        if self.dry_run:
            return
        time.sleep(self.pause_short)

        attempts_done = 0
        ads_used = 0
        party_searches = 0
        steps = 0
        expect_ticket = False
        ads_had_no_effect = False
        reopened = False
        while steps < self.max_loops:
            if not self._time_left():
                break
            steps += 1
            info = self.dialog_settled(tries=2)
            state = info["state"]

            if state == EXIT:
                kind = info.get("exit_kind", "beenden")
                self.dismiss_confirm(info, leaving_dungeon=True)
                if kind == "party":
                    # OK leaves the party and returns to the list. This
                    # dungeon is done with that, continuing to search would
                    # be a loop.
                    self.log("  left the party, dungeon done")
                    return
                continue

            if state == BATTLE:
                self.wait_dialog_back(self.battle_timeout)
                continue

            if state == LIST:
                if reopened or attempts_done == 0:
                    self.log("  back in the list, done")
                    return
                # Finishing an attempt sometimes drops the panel and leaves
                # the list showing, with tickets still on the card. Metal Sea
                # ended a live run that way with one attempt unspent. Open it
                # once more instead of calling the dungeon finished -- if it
                # really is empty the panel says so, and the loop ends on the
                # next pass. Once, so a card the game keeps closing cannot
                # become a loop.
                reopened = True
                here = list_cards(self.grab())
                if index >= len(here):
                    self.log("  back in the list, done")
                    return
                self.log("  back in the list, opening the card once more")
                self.tap(CARD_X, here[index], was=self.label_of(index, label))
                time.sleep(self.pause_long)
                continue

            if state == UNKNOWN:
                # Reward, result, or an intermediate screen. Tap high up,
                # that accepts rewards and does not trigger a party prompt.
                self.tap(0.5, NEUTRAL_TAP_Y, was="neutral")
                time.sleep(self.pause_short)
                continue

            if self.is_close_button(info["attempt"]):
                self.log("  reward window, closing")
                self.tap(info["attempt"]["fx"], info["attempt"]["fy"],
                         was="Close")
                time.sleep(self.pause_long)
                continue

            # After an ad, an Attempt button must appear. If the ad button
            # reappears instead, it did not yield a ticket.
            if expect_ticket:
                expect_ticket = False
                if state == DIALOG_AD:
                    ads_had_no_effect = True

            if state == DIALOG_PARTY and info["party_voll"] < 2:
                # Without team-mates, Attempt does nothing. The dialog looks
                # identical with and without a party, both buttons sit at the
                # same place. It can only be told apart by the party slots,
                # measured standard deviation 0.0 when empty against 28 to 48
                # when occupied.
                if party_searches >= 2:
                    self.log("  no party found, moving on")
                    break
                self.log("  searching for a party, %d of 3 slots filled"
                         % info["party_voll"])
                self.tap(info["party"]["fx"], info["party"]["fy"],
                         was="Find a Party")
                party_searches += 1
                time.sleep(self.pause_long * 3)
                continue

            if info["attempt"]:
                if attempts_done >= self.max_attempts:
                    self.log("  hit the limit of %d attempts"
                             % self.max_attempts)
                    break
                self.log("  attempt %d" % (attempts_done + 1))
                t0 = time.time()
                self.tap(info["attempt"]["fx"], info["attempt"]["fy"],
                         was="Attempt")
                attempts_done += 1
                self.stats["versuche"] += 1
                if self.wait_dialog_gone(self.start_timeout):
                    if self.wait_dialog_back(self.battle_timeout):
                        duration = time.time() - t0
                        if duration < self.min_battle:
                            # Too short for a battle. The dialog was only
                            # briefly gone, e.g. because of a message. Do not
                            # count it as a battle, otherwise six missed
                            # clicks would look like six battles in the log.
                            self.log("  only %.0f s, that was no battle" % duration)
                            self.stats["abgelehnt"] += 1
                            break
                        self.stats["kaempfe"] += 1
                        self.log("  battle finished after %.0f s" % duration)
                    continue
                # The dialog stayed open. Either rejected, or the click fell
                # inside an animation. The next pass will show which of the
                # two, since then the ad button appears instead of Attempt.
                self.log("  attempt had no effect")
                self.stats["abgelehnt"] += 1
                if attempts_done >= 2:
                    break
                continue

            if state == DIALOG_AD and info["ad"]:
                if not self.use_ads:
                    self.log("  no attempts left, ads disabled")
                    break
                if ads_had_no_effect:
                    # An ad that yielded no ticket will not yield one next
                    # time either. The game then reports "Ad viewing limit
                    # reached". Without this rule the bot used to watch six
                    # ads in a row for nothing.
                    self.log("  ads no longer yield a ticket, moving on")
                    self.exhausted.add(key)
                    break
                if ads_used >= self.max_ads:
                    self.log("  hit the limit of %d ads"
                             % self.max_ads)
                    self.exhausted.add(key)
                    break
                self.log("  attempts empty, watching an ad")
                self.tap(info["ad"]["fx"], info["ad"]["fy"], was="Werbung")
                ads_used += 1
                self.stats["werbung"] += 1
                expect_ticket = True
                time.sleep(self.pause_long)
                continue

            self.log("  nothing to do in state %s" % state)
            break

        if steps >= self.max_loops:
            self.log("  loop limit reached, moving on")
        self.return_to_list()

    def wait_dialog_gone(self, timeout=8.0):
        """Wait until the dialog disappears.

        This is the evidence that a click had an effect. Before this, I
        measured the time until return and caught the dialog while it had
        not actually gone yet. The result was 0.1 seconds and the false
        report that no battle had happened, even though the battle was
        running.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if recognise(self.grab())["state"] not in self.DIALOGS:
                return True
            time.sleep(0.4)
        return False

    @staticmethod
    def is_close_button(button):
        """Narrow, centred button, so Close and not Attempt."""
        return bool(button) and button["fw"] <= CLOSE_W_MAX

    def dialog_settled(self, tries=3, pause=None):
        """Wait until the dialog has actually settled.

        After a battle, a return animation runs for 2 to 3 seconds. The
        dialog is already visible during that, but not yet interactive. A
        click on Attempt then has no effect, and the bot used to wrongly
        treat that as a rejection due to empty tickets. In a test run that
        cost the second of two battles.

        "Settled" means several consecutive frames show the same state at
        the same button position. Same principle as in the minigame bot, a
        single frame is no proof.
        """
        pause = pause if pause is not None else 0.5 * self.patience
        previous = None
        same_count = 0
        for _ in range(tries * 4):
            info = recognise(self.grab())
            fingerprint = (info["state"],
                       round(info["attempt"]["fy"], 3) if info["attempt"] else None,
                       round(info["ad"]["fy"], 3) if info["ad"] else None)
            if fingerprint == previous:
                same_count += 1
                if same_count >= tries - 1:
                    return info
            else:
                same_count = 0
                previous = fingerprint
            time.sleep(pause)
        return recognise(self.grab())

    def wait_dialog_back(self, timeout):
        """Wait until the dialog is back, tapping away rewards along the way.

        No tapping happens during a battle, that could hit Give Up. Outside
        a battle, tapping accepts the reward, which also applies after the
        ad button, since a reward window appears there too.
        """
        deadline = time.time() + timeout
        taps = 0
        while time.time() < deadline:
            img = self.grab()
            info = recognise(img)
            if info["state"] in self.DIALOGS:
                # Close windows are no longer clicked here, the main loop
                # does that. Otherwise wait_dialog_back would never return
                # such a window and the caller would check against nothing.
                return info
            if info["state"] == BATTLE:
                time.sleep(self.tick)
                continue
            if info["state"] == EXIT:
                # The party prompt arises precisely from tapping somewhere
                # while a party exists. After OK the dungeon is left, so stop
                # here.
                self.dismiss_confirm(info, leaving_dungeon=True)
                return None
            if info["state"] == LIST:
                return None
            if taps and taps % 4 == 0:
                self.back()
            else:
                # Tap high up, outside any dialog. A tap in the middle of the
                # screen can trigger a confirmation prompt; with a party it
                # acts like the back key.
                self.tap(0.5, NEUTRAL_TAP_Y, was="neutral, Belohnung annehmen")
            taps += 1
            time.sleep(self.tick)
        return None

    # ------------------------------------------------------------------
    def plan(self):
        """Two-phase plan, so that without name recognition no entry is
        played twice or not at all.

        The list is longer than the window. The first cards are visible at
        the top, the last ones at the bottom. From the total count and the
        number of cards visible at the bottom follows how many must be
        played from the top, so the two views complement each other exactly.

        Example with seven entries and five visible at the bottom. At the
        bottom that is entries 3 to 7, so 1 and 2 are played from the top.
        The last one is skipped, it changes daily.
        """
        self.scroll_bottom()
        bottom_list = list_cards(self.grab())
        n_bottom = len(bottom_list)
        if not n_bottom:
            self.log("no list cards recognised, am I in the list?")
            return 0, 0
        self.visible_at_bottom = n_bottom
        play_from_top = max(0, self.entries - n_bottom)
        play_from_bottom = max(0, n_bottom - self.skip_last)
        self.log("plan: %d cards visible at the bottom. Play %d from the top, "
                 "%d from the bottom, %d of %d in total"
                 % (n_bottom, play_from_top, play_from_bottom,
                    play_from_top + play_from_bottom, self.entries))
        return play_from_top, play_from_bottom

    def _time_left(self):
        """Checks pause, abort, and the time limit between actions. Never in
        the middle of an action, so no click is left unverified."""
        was_paused = False
        while self.control.is_paused() and not self.control.is_set():
            was_paused = True
            time.sleep(0.2)
        if was_paused and not self.control.is_set() and not self.dry_run:
            # During the pause, you may have been active in the game
            # yourself. So do not just continue blindly; check where things
            # stand first, and find the way back to the list.
            self.log("  resuming, checking the screen first")
            info = recognise(self.grab())
            if info["state"] == EXIT:
                self.dismiss_confirm(info)
            if recognise(self.grab())["state"] != LIST:
                self.log("  not in the list, state %s, returning"
                         % recognise(self.grab())["state"])
                if not self.return_to_list():
                    self.log("  no way back, aborting")
                    self.control.request("no way back to the list")
                    return False
        if self.control.is_set():
            self.log("aborted")
            return False
        if not self.max_minutes:
            return True
        if self.deadline is None:
            self.deadline = time.time() + self.max_minutes * 60
        if time.time() < self.deadline:
            return True
        self.log("time limit of %d minutes reached" % self.max_minutes)
        return False

    def run(self, rounds=1):
        """Round-robin. Each round goes through the list once, completely.

        A lost dungeon comes up again next round. That way, an endlessly
        repeated loss does not mean the bot gets stuck on one battle and
        never reaches the others.
        """
        if not self.open_list():
            return self.stats
        play_from_top, play_from_bottom = self.plan()
        if self.dry_run:
            self.log("Note: a dry run does not scroll, so the plan is based on "
                     "whatever view is showing and may be off.")

        for round_no in range(rounds):
            if not self._time_left():
                break
            self.log("\n=== Round %d of %d" % (round_no + 1, rounds))

            top_list = [i for i in range(play_from_top) if self.is_selected(i, "oben")]
            bottom_list = [i for i in range(play_from_bottom) if self.is_selected(i, "unten")]
            if self.survey_first:
                self.log("\nPre-check: which dungeons still have attempts")
                self.scroll_top()
                top_list = self.survey(top_list, "oben")
                self.scroll_bottom()
                bottom_list = self.survey(bottom_list, "unten")
                self.log("Playable, top %s, bottom %s"
                         % ([i + 1 for i in top_list] or "none",
                            [i + 1 for i in bottom_list] or "none"))
                self.stats["uebersprungen"] += (play_from_top - len(top_list)
                                                + play_from_bottom - len(bottom_list))
                if not top_list and not bottom_list:
                    self.log("nothing left to collect, round finished")
                    break

            self.scroll_top()
            for index in top_list:
                if not self._time_left():
                    break
                self.log("\n%s" % self.label_of(index, "oben"))
                self.play_entry(index, "oben", key=("oben", index))
                self.scroll_top()
            self.scroll_bottom()
            for index in bottom_list:
                if not self._time_left():
                    break
                self.log("\n%s" % self.label_of(index, "unten"))
                self.play_entry(index, "unten", key=("unten", index))
                self.scroll_bottom()
        return self.stats


# ----------------------------------------------------------------------------
def probe(cap, log=print):
    """Shows what is recognised on the current screen. Clicks nothing."""
    img = cap.grab()
    x0, y0, gw, gh = game_rect(img)
    info = recognise(img)
    log("window %d x %d, title bar %d px, game area %d x %d"
        % (img.shape[1], img.shape[0], y0, gw, gh))
    log("state: %s" % info["state"])
    for name in ("attempt", "party", "ad", "clear"):
        b = info[name]
        log("  %-8s %s" % (name, "relativ x %.3f y %.3f, Pixel %d,%d"
                           % (b["fx"], b["fy"], *to_pixel(img, b["fx"], b["fy"]))
                           if b else "not found"))
    log("  all blue buttons:   %s"
        % ", ".join("%.3f/%.3f" % (b["fx"], b["fy"]) for b in info["blau"]) or "none")
    log("  all violet buttons: %s"
        % ", ".join("%.3f/%.3f" % (b["fx"], b["fy"]) for b in info["violett"]) or "none")
    log("\nRecognised list cards: %s"
        % (", ".join("%.3f" % c for c in info["karten"]) or "none"))
    log("\nClick targets the bot would use")
    log("  dungeon tab     pixel %d,%d" % to_pixel(img, *NAV_DUNGEON))
    for i, fy in enumerate(info["karten"]):
        log("  card %d          pixel %d,%d" % (i + 1, *to_pixel(img, CARD_X, fy)))
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually click")
    ap.add_argument("--probe", action="store_true", help="only show what is recognised")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--entries", type=int, default=7,
                    help="number of entries in the list")
    ap.add_argument("--skip-last", type=int, default=1,
                    help="skip this many entries at the end, the last one changes daily")
    ap.add_argument("--no-ads", action="store_true")
    ap.add_argument("--battle-timeout", type=float, default=90.0)
    ap.add_argument("--max-minutes", type=int, default=0,
                    help="time limit in minutes, 0 for none")
    # Two tickets plus two ad tickets give four battles per dungeon and day.
    # The limit sits above that, so it only triggers on an actual error.
    ap.add_argument("--max-attempts", type=int, default=6,
                    help="upper limit of Attempt clicks per dungeon and round")
    ap.add_argument("--max-ads", type=int, default=2,
                    help="upper limit of ad clicks per dungeon and round")
    ap.add_argument("--only", default=None,
                    help="only these dungeons, short names separated by commas. "
                         "Available: " + ", ".join(DUNGEON_KEYS))
    ap.add_argument("--skip", default=None,
                    help="skip these dungeons, same short names")
    ap.add_argument("--list-dungeons", action="store_true",
                    help="list the short names and exit")
    ap.add_argument("--no-adb", action="store_true",
                    help="without ADB, input via mouse and keyboard")
    ap.add_argument("--no-survey", action="store_true",
                    help="skip the pre-check, try every dungeon directly")
    ap.add_argument("--min-battle", type=float, default=6.0,
                    help="shorter than this was no battle, so attempts are used up")
    ap.add_argument("--patience", type=float, default=1.5,
                    help="factor on all wait times, higher is more patient")
    ap.add_argument("--swipes", type=int, default=1,
                    help="swipes needed to scroll to the end of the list")
    ap.add_argument("--no-mouse-guard", action="store_true",
                    help="disable the F7/F8 hotkey and the auto-pause on "
                         "real mouse movement")
    args = ap.parse_args()

    if args.list_dungeons:
        print("Short names for --only and --skip, partial matches are enough\n")
        for i, (key, name) in enumerate(zip(DUNGEON_KEYS, DUNGEON_NAMES)):
            print("  %d  %-12s %s" % (i + 1, key, name))
        print("\nExamples")
        print("  py dungeon.py --go --skip apocalymon")
        print("  py dungeon.py --go --only apo,network")
        return

    only, unknown_o = parse_selection(args.only) if args.only else (None, [])
    skip, unknown_s = parse_selection(args.skip) if args.skip else ([], [])
    if unknown_o or unknown_s:
        print("unknown names: %s" % ", ".join(unknown_o + unknown_s))
        print("py dungeon.py --list-dungeons shows the known names")
        return
    if only is not None and skip:
        print("--only wins, --skip is ignored")
    if only is not None:
        print("Only these dungeons: %s"
              % ", ".join(DUNGEON_NAMES[i] for i in sorted(only)))
    elif skip:
        print("Skipped: %s"
              % ", ".join(DUNGEON_NAMES[i] for i in sorted(skip)))

    cap = (capture.open_window() if args.no_adb
           else capture.open_best(prefer_adb=True))
    if args.probe:
        probe(cap)
        return

    print("Mode: %s" % ("REAL, it will click" if args.go
                        else "dry run, no clicks"))
    bot = DungeonBot(cap, dry_run=not args.go, entries=args.entries,
                     skip_last=args.skip_last, use_ads=not args.no_ads,
                     battle_timeout=args.battle_timeout,
                     max_minutes=args.max_minutes,
                     max_attempts=args.max_attempts, max_ads=args.max_ads,
                     survey_first=not args.no_survey, patience=args.patience,
                     only=only, skip=skip,
                     min_battle=args.min_battle, swipes=args.swipes)
    print("Reference frame %d x %d" % bot.device)
    _keys(bot)
    control = None if args.no_mouse_guard else guard.start(bot.control, cap=cap)
    try:
        stats = bot.run(args.rounds)
    except KeyboardInterrupt:
        stats = bot.stats
        print("\naborted")
    finally:
        if control:
            control.stop()
    print("\nSummary: %s" % stats)


def _keys(bot):
    """Space pauses, q aborts, console focus only. guard.py additionally
    wires up a global F7/F8 hotkey and mouse-movement auto-pause that work
    even when the emulator window has focus instead of this console."""
    try:
        import msvcrt
    except ImportError:
        return
    import threading

    def loop():
        while not bot.control.is_set():
            ch = msvcrt.getwch()
            if ch == " ":
                paused = bot.control.toggle_pause()
                print("    %s" % ("paused, space resumes"
                                  if paused else "resumed"), flush=True)
            elif ch in ("q", "Q"):
                bot.control.request("key q")
                print("    abort requested", flush=True)

    threading.Thread(target=loop, daemon=True).start()
    print("Keys: space pauses, q aborts (console focus needed)")


if __name__ == "__main__":
    main()
