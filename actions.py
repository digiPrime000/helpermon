"""
Clicking with verification.

Principle: after every action, check whether it actually took effect, and check
it against the counters rather than the picture. The counters are unambiguous.

  step                    paws minus 1
  step right in column 1  additionally metres plus 1
  pyramid                 claws minus 1, no paw
  skill                   fireballs minus 1, metres plus 2 or 3

Do not check for an exact delta. A step costs one paw but may collect a power-up
at the same moment, which makes the delta +4 instead of -1. Instead: if any
counter moved plausibly the action happened, and only if none moved is a banner
checked. Without a confirmed change the bot re-reads instead of clicking again,
otherwise the bookkeeping drifts.
"""

import time

import vision

# Outcomes of an action
OK = "ok"
NO_EFFECT = "no_effect"
BANNER_MOVE = "banner_move"
BANNER_UNKNOWN = "banner_unknown"
BLIND = "blind"  # counter unreadable, outcome unclear
BANNER_UNKNOWN_TEXT = "unknown"  # vision.classify_banner's name for this case
MOVED_INSTEAD = "moved_instead"  # the pyramid was already gone, the click became a step
INSUFFICIENT = "insufficient"  # 'Insufficient ...' banner, a resource is used up


def merge_counters(cap, calib, tries=4, pause=0.25, need=None):
    """Merge counters across several frames.

    A single frame may fall inside an animation, making a counter unreadable.
    Across three to four frames, practically all values show up. The first
    readable value per counter is taken.

    This function used to also live in bot.py. Two versions of the same
    logic are a source of bugs, so now it only lives here.
    """
    merged = {}
    banner = None
    img = None
    for i in range(tries):
        img = cap.grab()
        if banner is None:
            banner = vision.classify_banner(img, calib)
        for key, value in vision.read_counters(img, calib).items():
            if value is not None and key not in merged:
                merged[key] = value
        if all(k in merged for k in (need or vision.COUNTER_KEYS)):
            break
        if i < tries - 1:
            time.sleep(pause)
    return merged, banner, img


class Actor:
    """Performs actions and regulates the pace itself.

    The pace is a factor on all wait times. After every action confirmed on
    the first try, it shrinks a little, so the bot gets faster. On any
    failure it jumps straight back to cautious. That way the bot runs as
    fast as is currently reliable, without you having to hand-tune values.
    """

    def __init__(self, cap, calib, templates, click_delay=1.5, settle=0.55,
                 verify_pause=0.2, verify_tries=3, dry_run=True,
                 min_pace=0.60, adaptive=True, log=print):
        self.cap = cap
        self.calib = calib
        self.templates = templates
        self.base_click_delay = click_delay
        self.base_settle = settle
        self.base_verify_pause = verify_pause
        self.verify_tries = verify_tries
        self.dry_run = dry_run
        self.log = log
        self.last_frame = None
        # Pace factor, 1.0 is cautious, smaller is faster
        self.pace = 1.0
        self.min_pace = min_pace
        self.adaptive = adaptive
        self.clean_streak = 0

    # ------------------------------------------------------------------
    @property
    def click_delay(self):
        return self.base_click_delay * self.pace

    @property
    def settle(self):
        return self.base_settle * self.pace

    @property
    def verify_pause(self):
        return self.base_verify_pause * self.pace

    def on_clean_success(self):
        """Action confirmed on the first try, so it is allowed to speed up."""
        self.clean_streak += 1
        if not self.adaptive:
            return
        # only start speeding up after three clean actions
        if self.clean_streak >= 3:
            self.pace = max(self.min_pace, self.pace * 0.90)

    def on_slow_confirm(self):
        """Confirmed, but only on the second try. Slow down a little instead
        of resetting the pace factor completely."""
        self.clean_streak = 0
        if self.adaptive:
            self.pace = min(1.0, self.pace * 1.08)

    def on_trouble(self):
        """Something was not right straight away, become cautious at once."""
        self.clean_streak = 0
        if self.adaptive:
            self.pace = 1.0

    def tempo(self):
        return "pace %.2f, tick %.2f s" % (self.pace, self.click_delay)

    # ------------------------------------------------------------------
    def grab(self):
        self.last_frame = self.cap.grab()
        return self.last_frame

    def read_counters(self, img=None):
        return vision.read_counters(img if img is not None else self.grab(), self.calib)

    def tap_cell(self, row, col):
        x, y = vision.cell_center(self.calib, row, col)
        if self.dry_run:
            self.log("    [dry run] click on r%dc%d, pixel %d,%d"
                     % (row + 1, col + 1, x, y))
            return
        self.cap.tap(x, y)

    def tap_skill(self):
        x, y = self.calib["skill_button"]
        if self.dry_run:
            self.log("    [dry run] click on the skill button, pixel %d,%d" % (x, y))
            return
        self.cap.tap(x, y)

    # ------------------------------------------------------------------
    # Which counters can prove an action happened. Only these are waited on,
    # not all seven. Waiting on all of them would cost every animation three
    # screenshots, and that costs seconds.
    RELEVANT = {
        "step": ("paws", "meters"),
        "destroy": ("claws",),
        "skill": ("fireballs", "meters"),
    }

    def read_counters_merged(self, tries=3, pause=None, need=None):
        merged, banner, img = merge_counters(
            self.cap, self.calib, tries=tries,
            pause=self.verify_pause if pause is None else pause, need=need)
        self.last_frame = img
        return merged, banner, img

    # ------------------------------------------------------------------
    def perform(self, action, before, world_col_at_start):
        """Perform an action and check whether it took effect.

        Does not check for an exact delta. A step costs one paw, but may
        collect a power-up at the same moment. With a paw power-up the delta
        is then +4 instead of -1. That used to be wrongly read as not
        executed.

        Evidence instead
          any counter moved plausibly       ->  executed
          no counter moved and a banner is there  ->  input error
          no counter moved, no banner       ->  no effect
        """
        if action.kind == "skill":
            self.tap_skill()
        else:
            self.tap_cell(*action.cell)

        if self.dry_run:
            return OK, before, None, {}

        time.sleep(self.settle)
        last = (NO_EFFECT, before, None, {})
        for attempt in range(self.verify_tries):
            self._attempt = attempt
            after, banner, img = self.read_counters_merged(
                need=self.RELEVANT.get(action.kind))
            deltas = {k: after[k] - before[k]
                      for k in after
                      if k in before and before[k] is not None
                      and after[k] != before[k]}
            state = self._judge(action, world_col_at_start, deltas, banner)
            last = (state, after, img, deltas)
            if state in (OK, MOVED_INSTEAD, INSUFFICIENT):
                if state == OK and attempt == 0:
                    self.on_clean_success()
                elif state == OK:
                    # a second try was needed. Not a failure, just a sign
                    # that it should not go any faster right now
                    self.on_slow_confirm()
                else:
                    self.on_trouble()
                return last
            if banner == BANNER_UNKNOWN_TEXT:
                return BANNER_UNKNOWN, after, img, deltas
            if attempt < self.verify_tries - 1:
                time.sleep(self.base_click_delay / self.verify_tries)
        state, after, img, deltas = last
        self.on_trouble()
        if state != OK and last[3] == {} and banner == "move":
            return BANNER_MOVE, after, img, deltas
        return state, after, img, deltas

    # ------------------------------------------------------------------
    def _judge(self, action, col_at_start, deltas, banner):
        if banner == "insufficient" and not deltas:
            # a resource is empty. Which one follows from the action
            return INSUFFICIENT
        if not deltas:
            if banner == "move":
                return BANNER_MOVE
            if banner == BANNER_UNKNOWN_TEXT:
                return BANNER_UNKNOWN
            return NO_EFFECT

        paw = deltas.get("paws")
        met = deltas.get("meters")
        claw = deltas.get("claws")
        fire = deltas.get("fireballs")
        pickup = any(deltas.get(k, 0) > 0
                     for k in ("top_orange", "top_green", "top_pink"))
        gain = any(deltas.get(k, 0) > 0 for k in ("paws", "claws", "fireballs"))

        if action.kind == "destroy":
            # A pyramid only costs one claw. There may be a power-up
            # underneath it, which immediately raises the counter again
            if claw is not None and claw < 0:
                return OK
            # If the pyramid was already gone, the click became a normal
            # step. This MUST be reported, otherwise the position
            # bookkeeping drifts out of sync
            if (paw is not None and paw < 0) or (met is not None and met > 0):
                return MOVED_INSTEAD
            if gain or pickup:
                return OK
            return NO_EFFECT

        if action.kind == "skill":
            if fire is not None and fire < 0:
                return OK
            if met is not None and met in (2, 3):
                return OK
            return NO_EFFECT

        # A step. Every movement costs one paw, but may collect something at
        # the same time. So any plausible movement of a counter is enough
        if paw is not None and paw != 0:
            return OK
        if met is not None and met > 0:
            return OK
        if pickup or gain:
            return OK
        return NO_EFFECT

    def wait_tick(self):
        time.sleep(self.click_delay)
