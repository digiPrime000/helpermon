"""
Plausibility checks on counter values.

Two cases have to be covered.

First, a single misread, for example 11 instead of 11,925 when the figure stands
in the bottom row and covers digits of the metre label. That value is rejected.

Second, a real jump the bot missed. If the same implausible value is read
several times in a row it is the truth and the stored value is stale, so the
tracker re-syncs. Without that the counter got stuck and reported a wrong delta
on every action; in one test run it claimed "metres +9" for thirteen actions
straight.
"""

ONLY_UP = {"top_orange", "top_green", "top_pink"}
MAX_METER_STEP = 3


class CounterTracker:
    """Prueft Zaehler gegen Spielregeln und zieht sich selbst nachs.

    Zwei Faelle muessen abgedeckt sein.

    Erstens ein einzelner Fehlwert, zum Beispiel 11 statt 11.925, wenn die
    Figur in der untersten Zeile ueber dem Meterlabel steht und Ziffern
    verdeckt. Der wird verworfen.

    Zweitens ein echter Sprung, den der Bot verpasst hat. Wird derselbe
    unplausible Wert mehrfach hintereinander gelesen, ist er die Wahrheit und
    der gespeicherte Wert ist veraltet. Dann wird nachgezogen. Ohne das blieb
    der Zaehler dauerhaft haengen und meldete bei jeder Aktion ein falsches
    Delta, im Testlauf 13 Aktionen lang Meter plus 9.
    """

    def __init__(self, max_actions_per_frame=1, accept_after=3):
        self.values = {}
        self.suspicious = []
        self.resynced = []
        self.accept_after = accept_after
        self._pending = {}
        # im Lesemodus spielt ein Mensch, der pro Frame mehrere Schritte macht.
        # Der Bot macht genau eine Aktion, dann steht das hier auf 1.
        self.max_actions = max_actions_per_frame

    def _plausible(self, key, old, new):
        delta = new - old
        if key == "meters":
            return 0 <= delta <= MAX_METER_STEP * self.max_actions
        if key in ONLY_UP:
            return delta >= 0
        if key in ("paws", "claws", "fireballs"):
            # nach unten hoechstens so viele Aktionen wie moeglich, nach oben
            # nur durch Power-ups, die klein sind
            return -6 * self.max_actions <= delta <= 60
        return True

    def update(self, counters):
        """Uebernimmt plausible Werte, gibt die Deltas zurueck."""
        deltas = {}
        self.suspicious = []
        self.resynced = []
        for key, new in counters.items():
            if new is None:
                continue
            old = self.values.get(key)
            if old is None:
                self.values[key] = new
                continue
            if new == old:
                continue
            if self._plausible(key, old, new):
                deltas[key] = new - old
                self.values[key] = new
                self._pending.pop(key, None)
                continue

            # unplausibel. Zaehlen, wie oft derselbe Wert schon kam
            seen, count = self._pending.get(key, (None, 0))
            count = count + 1 if seen == new else 1
            self._pending[key] = (new, count)
            if count >= self.accept_after:
                # mehrfach derselbe Wert, also ist der gespeicherte veraltet
                self.values[key] = new
                self._pending.pop(key, None)
                self.resynced.append((key, old, new))
            else:
                self.suspicious.append((key, old, new))
        return deltas

    def get(self, key):
        return self.values.get(key)
