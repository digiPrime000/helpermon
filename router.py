"""
Pathfinding as a cost search.

Special-case rules used to pile up here about when to dodge and when to destroy.
On the way to an item the planner destroyed a pyramid as soon as claws were
available, without ever comparing the detour. That was exactly the expensive
choice.

Now it calculates. Dijkstra over the five by five visible cells with real
prices, so the desired behaviours follow by themselves instead of being coded
individually.

  detour when it pays        two steps cost 80 Bits each, a claw 200
  dodge towards the centre   a tiny bias per row of distance from the middle
                             row, which only breaks ties
  step left when cheaper     allowed, with a surcharge so no shuffling arises
  destroy as a last resort   when no detour is cheaper

Simplification that keeps this small: planning happens in the visible frame. A
step right out of the second column really moves the world rather than the
figure, but the sequence of cells traversed is the same, so for path planning
the two are equivalent. Replanning happens after every action, so looking at the
current window is enough.
"""

import heapq

import vision

DIRECTIONS = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}


class Route:
    """Ergebnis einer Suche."""

    def __init__(self, first=None, cost=None, steps=0, destroys=0, path=None):
        self.first = first          # "up", "down", "left", "right" oder None
        self.cost = cost            # Bits, None wenn unerreichbar
        self.steps = steps
        self.destroys = destroys
        self.path = path or []      # Liste von (row, col)

    @property
    def reachable(self):
        return self.cost is not None

    def __repr__(self):
        return "Route(%s, %s Bits, %d Schritte, %d Zerstoerungen)" % (
            self.first, self.cost, self.steps, self.destroys)


class Router:
    def __init__(self, is_pyramid, cost_step, cost_destroy, left_penalty=20.0,
                 middle_bias=1.0, rows=vision.ROWS, cols=vision.COLS,
                 fig_col_max=1, can_destroy=True):
        """
        is_pyramid    Funktion (row, col) im sichtbaren Bild
        cost_step     Preis eines Schrittes, Tatze plus Aktionswert
        cost_destroy  Aufschlag fuer das Betreten einer Pyramidenzelle, also
                      Kralle plus Aktion minus erwartete Beute
        left_penalty  Zuschlag fuer Linksschritte, verhindert Hin und Her
        middle_bias   winziger Zuschlag je Zeile Abstand zur Mittelzeile. Wirkt
                      nur bei Gleichstand und darf nie eine echte Ersparnis
                      ueberstimmen
        can_destroy   False, wenn keine Krallen da sind
        """
        self.is_pyramid = is_pyramid
        self.cost_step = float(cost_step)
        self.cost_destroy = float(cost_destroy)
        self.left_penalty = float(left_penalty)
        self.middle_bias = float(middle_bias)
        self.rows = rows
        self.cols = cols
        self.fig_col_max = fig_col_max
        self.can_destroy = can_destroy
        self.middle = (rows - 1) / 2.0

    # ------------------------------------------------------------------
    def _enter_cost(self, row, col, direction):
        cost = self.cost_step
        if direction == "left":
            cost += self.left_penalty
        if self.is_pyramid(row, col):
            if not self.can_destroy:
                return None
            cost += self.cost_destroy
        cost += self.middle_bias * abs(row - self.middle)
        return cost

    def search(self, start, goals):
        """Billigster Weg von start zu einer der Zielzellen.

        goals ist eine Menge von (row, col). Ist sie leer, wird der billigste
        Weg zur rechtesten erreichbaren Spalte gesucht, also reines Vorruecken.
        """
        goals = set(goals or ())
        best = {start: 0.0}
        came = {}
        queue = [(0.0, start)]
        reached = None

        while queue:
            cost, node = heapq.heappop(queue)
            if cost > best.get(node, float("inf")):
                continue
            if node in goals:
                reached = node
                break
            row, col = node
            for direction, (dr, dc) in DIRECTIONS.items():
                nrow, ncol = row + dr, col + dc
                if not (0 <= nrow < self.rows and 0 <= ncol < self.cols):
                    continue
                extra = self._enter_cost(nrow, ncol, direction)
                if extra is None:
                    continue
                new = cost + extra
                if new < best.get((nrow, ncol), float("inf")):
                    best[(nrow, ncol)] = new
                    came[(nrow, ncol)] = (node, direction)
                    heapq.heappush(queue, (new, (nrow, ncol)))

        if not goals:
            # Vorruecken. Ziel ist die weiteste erreichbare Spalte, bei
            # Gleichstand der billigste Weg dorthin
            candidates = [(c, cost) for (r, c), cost in best.items()]
            if not candidates:
                return Route()
            far = max(c for c, _ in candidates)
            reached = min(((r, c) for (r, c) in best if c == far),
                          key=lambda n: best[n])

        if reached is None or reached == start:
            return Route()
        return self._build(start, reached, came, best[reached])

    def _build(self, start, goal, came, cost):
        path = []
        node = goal
        first = None
        destroys = 0
        while node != start:
            prev, direction = came[node]
            path.append(node)
            if self.is_pyramid(*node):
                destroys += 1
            first = direction
            node = prev
        path.reverse()
        return Route(first=first, cost=round(cost, 2), steps=len(path),
                     destroys=destroys, path=path)
