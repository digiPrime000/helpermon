"""
Planner. Decides exactly one next action.

Ground rules, derived from measurements

  1. Every wanted power-up is collected, however expensive
  2. They are worked through left to right, so steps left never arise by default
  3. Vertical steps do not scroll the world, so a visible object cannot be lost
  4. Only what sits in visible column 0 is lost when stepping right out of
     column 1, so exactly that step is blocked then
  5. Metres come only from stepping right out of column 1 and from the skill

Costs in Bits, derived from the shop prices: 50 paws cost 2,000, one claw 200,
one fireball 400.
"""

import router as router_mod
import vision
from world import FIG_COL_MAX

# Surcharge for steps left. They are allowed when cheaper, but not free,
# otherwise back-and-forth would result.
BIT_LEFT_PENALTY = 20

# Tiny surcharge per row of distance from the middle row. Only matters on a
# tie. The greatest distance from the middle to any row is 2, from an edge
# row it is 4, so standing in the middle is cheaper on average.
BIT_MIDDLE_BIAS = 1

# Shop prices, 50 paws cost 2,000 Bits
BIT_PAW = 40
BIT_CLAW = 200
BIT_SKILL = 400

# Value of a saved action in Bits. Standard 40, because items per time is
# the goal and resources can be bought again. Set to 0, only resources count.
BIT_PER_ACTION = 40

# Expected value of the loot under a pyramid, in Bits. It comes out lean,
# orange 20 instead of 125 and just 1 for everything else, and it does not
# sit under every pyramid. Deliberately small because of that. It only
# counts when the pyramid is in the way anyway; opening pyramids on the
# chance of loot does not pay off.
BIT_PYRAMID_LOOT = 25

# Tendency to change row earlier. 0 means only change when there are
# genuinely fewer pyramids there. Higher values change more readily.
ROW_SLACK = 0


class Action:
    def __init__(self, kind, direction=None, cell=None, reason=""):
        self.kind = kind  # step, destroy, skill, wait, stop
        self.direction = direction
        self.cell = cell  # visible (row, col) for the click
        self.reason = reason

    def __repr__(self):
        parts = [self.kind]
        if self.direction:
            parts.append(self.direction)
        if self.cell:
            parts.append("r%dc%d" % (self.cell[0] + 1, self.cell[1] + 1))
        return "%s (%s)" % (" ".join(parts), self.reason)


DELTA = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}


class Planner:
    def __init__(self, world, min_paws=20, target_meters=0,
                 bit_paw=BIT_PAW, bit_claw=BIT_CLAW, bit_skill=BIT_SKILL,
                 bit_pyramid_loot=BIT_PYRAMID_LOOT, row_slack=ROW_SLACK,
                 bit_left_penalty=BIT_LEFT_PENALTY,
                 bit_middle_bias=BIT_MIDDLE_BIAS,
                 bit_per_action=BIT_PER_ACTION):
        self.world = world
        self.min_paws = min_paws
        self.target_meters = target_meters
        self.bit_paw = bit_paw
        self.bit_claw = bit_claw
        self.bit_skill = bit_skill
        self.bit_per_action = bit_per_action
        self.bit_pyramid_loot = bit_pyramid_loot
        self.row_slack = row_slack
        self.bit_left_penalty = bit_left_penalty
        self.bit_middle_bias = bit_middle_bias

    # ------------------------------------------------------------------
    def next_action(self, counters, depth=0):
        w = self.world
        if w.row is None or w.col is None:
            return Action("wait", reason="position unknown")

        paws = counters.get("paws")
        if paws is not None and paws <= self.min_paws:
            return Action("stop", reason="paws almost empty (%s)" % paws)
        meters = counters.get("meters")
        # target_meters 0 means no limit. The 10,000 in the game is only the
        # next reward, not the end
        if self.target_meters and meters is not None and meters >= self.target_meters:
            return Action("stop", reason="metre target reached (%s m)" % meters)

        # The skill used to be checked only when no power-up at all was
        # visible. Since one is visible almost always, it practically never
        # got used. Now it is checked first, even on the way to a target.
        skill = self._skill_worth_it(counters)
        if skill:
            return skill

        targets = w.visible_wanted()
        if targets:
            act = self._go_to_target(targets[0], counters)
            if act.kind == "unreachable":
                w.mark_unreachable(*act.cell)
                if depth < 6:
                    return self.next_action(counters, depth + 1)
                return Action("wait", reason="too many unreachable targets")
            return act
        return self._advance(counters)

    # ------------------------------------------------------------------
    def _go_to_target(self, target, counters):
        """To the next wanted power-up, via cost search.

        No fixed scheme anymore for when the row is changed. The cheapest
        path decides, and it weighs pyramids in both rows, detours, steps
        left and the tendency towards the middle row all at once.
        """
        w = self.world
        gcol, row, kind = target
        col = gcol - w.scroll_offset
        if not 0 <= col < vision.COLS:
            return Action("wait", reason="target lies outside the board")

        skill = self._skill_worth_it(counters)
        if skill:
            return skill

        route = self._router(counters).search((w.row, w.col), {(row, col)})
        return self._route_action(route, counters, "towards %s" % kind,
                                  target=(gcol, row))

    def _advance(self, counters):
        """No power-up visible, so make progress.

        Target is the furthest reachable column. That way the search dodges
        pyramids by itself and, on a tie, prefers the middle row, because
        from there the paths to the next object are shorter on average.
        """
        skill = self._skill_worth_it(counters)
        if skill:
            return skill
        w = self.world
        route = self._router(counters).search((w.row, w.col), set())
        return self._route_action(route, counters, "making progress")

    def _router(self, counters):
        """Cost search over the visible board.

        The prices are the same as everywhere, paw plus action value per
        step, and claw plus action minus expected loot for entering a
        pyramid cell. That way a calculation decides whether to detour or
        destroy, instead of an individual rule.
        """
        w = self.world
        claws = counters.get("claws")
        return router_mod.Router(
            is_pyramid=lambda row, col: w.is_pyramid(w.scroll_offset + col, row),
            cost_step=self.bit_paw + self.bit_per_action,
            cost_destroy=self.bit_claw + self.bit_per_action - self.bit_pyramid_loot,
            left_penalty=self.bit_left_penalty,
            middle_bias=self.bit_middle_bias,
            can_destroy=claws is None or claws > 0)

    def _route_action(self, route, counters, reason, target=None):
        """Turn the first action of a found route into an Action."""
        w = self.world
        if not route.reachable or route.first is None:
            return self._unreachable(counters, target)

        direction = route.first
        dr, dc = DELTA[direction]
        row, col = w.row + dr, w.col + dc
        gcol = w.scroll_offset + col

        # Safety rule. A step right out of the second column scrolls and
        # would lose everything in the left visible column.
        if direction == "right" and w.col >= FIG_COL_MAX:
            if self._would_lose_items(1):
                return self._fetch_left(counters)

        if w.is_pyramid(gcol, row):
            return Action("destroy", direction, (row, col),
                          "destroy pyramid, %d Bits for the whole path"
                          % route.cost)
        detail = "%s, %d steps, %d Bits" % (reason, route.steps, route.cost)
        if route.destroys:
            detail += ", %d of them pyramid(s)" % route.destroys
        return Action("step", direction, (row, col), detail)

    def _fetch_left(self, counters):
        """Something wanted sits in the left visible column and would be
        lost on the next scroll. Fetch it first."""
        w = self.world
        left_gcol = w.scroll_offset
        for row in range(vision.ROWS):
            if not w.is_wanted(left_gcol, row):
                continue
            route = self._router(counters).search((w.row, w.col), {(row, 0)})
            return self._route_action(route, counters,
                                      "fetching object in the left column",
                                      target=(left_gcol, row))
        return Action("wait", reason="safety rule with no target")

    def _unreachable(self, counters, target):
        """No path found. Check the skill first, then give up on the target."""
        skill = self._skill_worth_it(counters, min_pyramids=1)
        if skill:
            skill.reason = "no path free, skill clears it"
            return skill
        if target:
            return Action("unreachable", cell=target,
                          reason="no path, no claws and no skill")
        return Action("wait", reason="no path found")

    def _cell_cost(self, gcol, row, counters):
        """What it costs to pass this cell, in Bits.

        Without a pyramid, just the step. With a pyramid, either one claw or
        a detour via the neighbouring row, whichever is cheaper counts.
        """
        cost = self.bit_paw
        if not w_is_pyramid(self.world, gcol, row):
            return cost, 1
        claws = counters.get("claws")
        options = []
        if claws is None or claws > 0:
            # one claw plus one action, in exchange for the loot underneath
            options.append((self.bit_claw - self.bit_pyramid_loot, 1))
        if self._row_free_around(gcol, row):
            options.append((2 * self.bit_paw, 2))  # up and back down
        if not options:
            return None, None  # not passable
        # comparison in one currency, Bits plus valued actions
        extra, acts = min(options,
                          key=lambda o: o[0] + o[1] * self.bit_per_action)
        return cost + extra, 1 + acts

    def _would_lose_items(self, scroll, keep_row=None):
        """Would scrolling by this many columns push a wanted object off the
        left edge of the board?

        For a step right, scroll is 1; for the skill, 2 or 3. Objects in row
        keep_row are collected by the skill and do not count.
        """
        w = self.world
        for col in range(scroll):
            gcol = w.scroll_offset + col
            for row in range(vision.ROWS):
                if keep_row is not None and row == keep_row:
                    continue
                if w.is_wanted(gcol, row):
                    return True
        return False

    def _row_free_around(self, gcol, row):
        for other in (row - 1, row + 1):
            if not 0 <= other < vision.ROWS:
                continue
            if not w_is_pyramid(self.world, gcol, other):
                return True
        return False

    def _skill_worth_it(self, counters, min_pyramids=None):
        """The skill pays off when walking would cost more than it does.

        It flies over cells without collecting, so never over a wanted
        power-up. It is compared against the cheapest path on foot over the
        same columns, i.e. steps plus, per pyramid, either one claw or a
        detour.
        """
        w = self.world
        charges = counters.get("fireballs")
        if not charges:
            return None
        span = 3 if w.col >= FIG_COL_MAX else 2
        cells = [(w.fig_gcol + i, w.row) for i in range(1, span + 1)]
        # The skill also picks up from the ground, so it is allowed to fly
        # over items. But it scrolls by span columns, and that pushes
        # objects off the left edge of the board. In its own row they get
        # collected; in every other row they would be lost.
        if self._would_lose_items(span, keep_row=w.row):
            return None
        pyramids = sum(1 for gcol, row in cells if w.is_pyramid(gcol, row))
        if pyramids < (min_pyramids or 1):
            return None

        walk_bits = 0
        walk_acts = 0
        for gcol, row in cells:
            bits, acts = self._cell_cost(gcol, row, counters)
            if bits is None:
                walk_bits = None
                break
            walk_bits += bits
            walk_acts += acts
        if walk_bits is None:
            return Action("skill", reason="path on foot blocked, %d pyramids"
                          % pyramids)

        # The fireball collects whatever it uncovers under the pyramids
        skill_bits = self.bit_skill - pyramids * self.bit_pyramid_loot
        # The skill is one action, walking is several. Anyone who values
        # time sets bit_per_action higher
        walk_bits += max(0, walk_acts - 1) * self.bit_per_action
        if walk_bits <= skill_bits:
            return None
        return Action("skill",
                      reason="%d pyramids, path on foot costs %d Bits against %d"
                             % (pyramids, walk_bits, skill_bits))


def w_is_pyramid(world, gcol, row):
    return world.is_pyramid(gcol, row)
