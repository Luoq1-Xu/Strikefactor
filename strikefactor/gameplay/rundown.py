"""Continuous ball-carrier pursuit and physical tags, in feet and seconds."""

import math
from dataclasses import dataclass

from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.running_play import TAG_REACH_FT, TAG_SWEEP_S


@dataclass(frozen=True)
class Pursuit:
    origin: tuple
    velocity: tuple
    target: tuple
    start_s: float
    speed_fts: float
    acceleration_s: float

    @property
    def desired_velocity(self):
        delta = tuple(b-a for a, b in zip(self.origin, self.target))
        distance = math.hypot(*delta)
        speed = min(self.speed_fts, distance/max(0.12, self.acceleration_s))
        return tuple(d*speed/distance for d in delta) if distance else (0.0, 0.0)

    @property
    def ramp_s(self):
        change = math.dist(self.velocity, self.desired_velocity)
        return change * max(0.001, self.acceleration_s) / self.speed_fts

    def velocity_at(self, time_s):
        u = min(1.0, max(0.0, time_s-self.start_s) / max(1e-12, self.ramp_s))
        return tuple(v+(d-v)*u for v, d in zip(self.velocity, self.desired_velocity))

    def position_at(self, time_s):
        t = max(0.0, time_s-self.start_s)
        ramp = min(t, self.ramp_s)
        velocity = self.velocity_at(self.start_s+ramp)
        return tuple(p+(v+w)*ramp/2+d*(t-ramp)
                     for p, v, w, d in zip(self.origin, self.velocity, velocity, self.desired_velocity))


def on_base(route, time_s):
    """A past touch does not protect a runner who has since left the bag."""
    point = route.position_at(time_s)
    return any(math.dist(point, bag) < 1e-6 and any(a <= time_s <= b for a, b in route.contacts(base))
               for base, bag in BASE_FT.items() if base > 0)


def reversal_count(route, time_s):
    """Count played changes of direction, ignoring future route segments."""
    bases = [route.start_base]
    if route.first is not None:
        bases.append(1)
    bases.extend(p.base for p in route.pieces if p.start_s <= time_s)
    directions = [1 if b > a else -1 for a, b in zip(bases, bases[1:]) if a != b]
    return sum(a != b for a, b in zip(directions, directions[1:]))


def tag_contact_s(path, route, start_s, end_s):
    """First contact within a short step, including crossing between poses.

    Minimize relative distance over the interval before bisecting its entry
    into glove reach. Testing just the final pose misses crossing actors.
    The caller splits steps at base contacts, where protection can change.
    """
    if end_s < start_s:
        return None

    def distance(t):
        return math.dist(path.position_at(t), route.position_at(t))

    if isinstance(path, Pursuit):
        closing_speed = max(path.speed_fts, math.hypot(*path.velocity)) + getattr(route, "top_fts", math.inf)
        if distance(start_s) > TAG_REACH_FT + closing_speed*(end_s-start_s):
            return None

    left, right = start_s, end_s
    for _ in range(32):
        a, b = (2*left+right)/3, (left+2*right)/3
        if distance(a) <= distance(b):
            right = b
        else:
            left = a
    closest = min((start_s, (left+right)/2, end_s), key=distance)
    if distance(closest) > TAG_REACH_FT:
        return None
    left, right = start_s, closest
    for _ in range(32):
        middle = (left+right)/2
        if distance(middle) > TAG_REACH_FT:
            left = middle
        else:
            right = middle
    return None if on_base(route, right) else right


@dataclass
class Rundown:
    runner_id: str
    holder: str
    start_s: float
    velocity: tuple = (0.0, 0.0)
    path: Pursuit | None = None

    @property
    def ready_s(self):
        return self.start_s + TAG_SWEEP_S
