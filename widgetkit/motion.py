"""Motion that can be interrupted: springs, momentum, rubber-banding (after Apple's fluid-interface talks).

A spring is described by how it feels, not how long it takes: `response` (seconds to roughly arrive) and `damping`
(1.0 settles without overshoot; ~0.8 gives the slight bounce of a thrown thing). Changing its target mid-flight keeps
the value and the velocity it has, so a gesture can be reversed at any moment with no seam. The host calls
`step(dt)` on its animation clock (`nativeui/animation_clock.py`) and draws `value`.

    s = Spring(0.0)
    s.target = 1.0          # pressed: starts from where it is now
    s.target = 0.0          # released half-way: carries on from its current speed
    s.step(1 / 60)
"""
import math

_reduced = False


def set_reduced_motion(on):
    """Under reduced motion springs do not travel: they are at their target at once (the host cross-fades instead)."""
    global _reduced
    _reduced = bool(on)


def reduced_motion():
    return _reduced


class Spring:
    def __init__(self, value=0.0, response=0.35, damping=1.0):
        self.value, self.velocity = float(value), 0.0
        self.target = float(value)
        self.response, self.damping = response, damping

    def kick(self, velocity, bounce=True):
        """Hand a gesture's release velocity (units/s) to the spring. `bounce` (a flick or a throw, not a tap)
        lets it overshoot a little (damping 0.8)."""
        self.velocity = velocity
        if bounce:
            self.damping = min(self.damping, 0.8)

    @property
    def at_rest(self):
        return abs(self.value - self.target) < 1e-3 and abs(self.velocity) < 1e-2

    def step(self, dt):
        if _reduced:
            self.value, self.velocity = self.target, 0.0
            return self.value
        w = 2 * math.pi / self.response              # natural frequency
        k, c = w * w, 2 * self.damping * w
        n = max(1, math.ceil(dt / (1 / 240)))        # small steps keep it stable on a slow frame
        h = dt / n
        for _ in range(n):
            self.velocity += (k * (self.target - self.value) - c * self.velocity) * h
            self.value += self.velocity * h
        if self.at_rest:
            self.value, self.velocity = self.target, 0.0
        return self.value


def project(position, velocity, rate=0.998):
    """Where something thrown at `velocity` (units/s) comes to rest, from the exponential decay a scroll view uses:
    snap to the nearest target to this, not to where it was let go."""
    return position + velocity / 1000.0 * rate / (1.0 - rate)


def rubber_band(offset, limit, stiffness=0.55):
    """Resistance past an edge: the further `offset` is dragged beyond 0, the less the content follows
    (never more than `limit`)."""
    sign = -1 if offset < 0 else 1
    x = abs(offset)
    return sign * (1.0 - 1.0 / (x * stiffness / limit + 1.0)) * limit
