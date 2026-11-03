"""Analytic base-path motion in real feet and seconds, without pygame or RNG.

The batter's fitted home-to-first time includes the swing recovery and start.
Integrating a short delay, acceleration, then cruise to that exact endpoint
keeps the picture on the clock used by both infield and extra-base races.
Defenders use their own speed and current momentum on a fixed approach to
the bag; its arrival and its drawn position are two readings of one path.
"""

import copy
import math
from bisect import bisect_right
from dataclasses import dataclass, field, replace
from functools import cached_property

from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.infield_timing import FIRST_BASE_FT


@dataclass(frozen=True)
class BatterRun:
    arrival_s: float

    @property
    def start_delay_s(self):
        return 0.05 * self.arrival_s

    @property
    def acceleration_s(self):
        return 0.22 * self.arrival_s

    @property
    def cruise_fts(self):
        return 90.0 / (self.arrival_s - self.start_delay_s - self.acceleration_s / 2)

    def position_at(self, elapsed_s):
        t = max(0.0, elapsed_s - self.start_delay_s)
        ramp = self.acceleration_s
        if elapsed_s >= self.arrival_s:
            # Run through the bag, with a short deceleration on the far side.
            since = elapsed_s - self.arrival_s
            distance = 90.0 + 10.0 * (1.0 - math.exp(-self.cruise_fts * since / 10.0))
        elif t < ramp:
            distance = self.cruise_fts * t * t / (2 * ramp)
        else:
            distance = self.cruise_fts * (t - ramp / 2)
        return tuple(axis * distance / 90.0 for axis in FIRST_BASE_FT)


@dataclass(frozen=True)
class BaseApproach:
    origin: tuple
    target: tuple
    start_s: float
    speed_fts: float
    acceleration_s: float
    initial_fraction: float = 0.0

    @property
    def distance_ft(self):
        return math.dist(self.origin, self.target)

    @property
    def initial_fts(self):
        return self.speed_fts * min(1.0, max(0.0, self.initial_fraction))

    @property
    def acceleration(self):
        return self.speed_fts / max(0.001, self.acceleration_s)

    @property
    def ramp_s(self):
        return (self.speed_fts - self.initial_fts) / self.acceleration

    @property
    def duration_s(self):
        distance = self.distance_ft
        ramp_distance = (self.initial_fts + self.speed_fts) * self.ramp_s / 2
        if distance <= ramp_distance:
            return 2 * distance / (math.sqrt(self.initial_fts ** 2 + 2 * self.acceleration * distance)
                                   + self.initial_fts) if distance else 0.0
        return self.ramp_s + (distance - ramp_distance) / self.speed_fts

    @property
    def arrival_s(self):
        return self.start_s + self.duration_s

    def position_at(self, elapsed_s):
        if elapsed_s >= self.arrival_s:
            return self.target
        t = max(0.0, elapsed_s - self.start_s)
        ramp_t = min(t, self.ramp_s)
        distance = (self.initial_fts * ramp_t + self.acceleration * ramp_t ** 2 / 2
                    + self.speed_fts * max(0.0, t - self.ramp_s))
        fraction = min(1.0, distance / self.distance_ft) if self.distance_ft else 1.0
        return tuple(a + (b - a) * fraction for a, b in zip(self.origin, self.target))


# ---- Continuous routes around the diamond ---------------------------------

def _unit(vector):
    length = math.hypot(*vector) or 1.0
    return tuple(x / length for x in vector)


def _corner_direction(base):
    before, after = BASE_FT[base - 1], BASE_FT[base + 1]
    return _unit(tuple(c - a for a, c in zip(before, after)))


# A runner carries through a bag he is rounding at this share of top speed,
# forward or retracing.
ROUNDING_SPEED_SHARE = 0.72


@dataclass(frozen=True)
class RunLeg:
    origin: tuple
    base: int
    start_s: float
    speed_fts: float
    initial_fts: float = 0.0
    end_fts: float = 0.0
    start_direction: tuple | None = None
    end_direction: tuple | None = None
    cutoff_s: float = math.inf

    @cached_property
    def samples(self):
        target = BASE_FT[self.base]
        straight = _unit(tuple(b - a for a, b in zip(self.origin, target)))
        start = self.start_direction or straight
        end = self.end_direction or straight
        handle = min(8.0, math.dist(self.origin, target) / 3)
        p = tuple(a + handle * d for a, d in zip(self.origin, start))
        q = tuple(b - handle * d for b, d in zip(target, end))
        points, distances = [self.origin], [0.0]
        for i in range(1, 41):
            t = i / 40
            point = tuple((1-t)**3*a + 3*(1-t)**2*t*b + 3*(1-t)*t*t*c + t**3*d
                          for a, b, c, d in zip(self.origin, p, q, target))
            distances.append(distances[-1] + math.dist(points[-1], point))
            points.append(point)
        return tuple(points), tuple(distances)

    @property
    def acceleration_s(self):
        return min(0.70 if self.initial_fts == 0 else 0.24,
                   self.samples[1][-1] / max(1.0, self.speed_fts) / 3)

    @property
    def braking_s(self):
        return min(0.24, self.samples[1][-1] / max(1.0, self.speed_fts) / 3)

    @property
    def duration_s(self):
        # Accelerate and brake along the curved path, never above top speed.
        lost = ((self.speed_fts-self.initial_fts)*self.acceleration_s
                + (self.speed_fts-self.end_fts)*self.braking_s) / 2
        return (self.samples[1][-1] + lost) / self.speed_fts

    @property
    def arrival_s(self):
        return self.start_s + self.duration_s

    def distance_at(self, time_s):
        t = min(self.duration_s, max(0.0, time_s - self.start_s))
        ramp = self.acceleration_s
        if ramp == 0:
            return 0.0
        if t <= ramp:
            return self.initial_fts*t + (self.speed_fts-self.initial_fts)*t*t/(2*ramp)
        first = (self.initial_fts + self.speed_fts)*ramp/2
        cruise = self.duration_s - ramp - self.braking_s
        if t <= ramp + cruise:
            return first + self.speed_fts*(t-ramp)
        down = t-ramp-cruise
        return (first + self.speed_fts*cruise + self.speed_fts*down
                - (self.speed_fts-self.end_fts)*down*down/(2*self.braking_s))

    def position_at(self, time_s):
        if time_s >= self.arrival_s:
            return BASE_FT[self.base]
        points, distances = self.samples
        distance = self.distance_at(time_s)
        i = min(len(points)-2, max(0, bisect_right(distances, distance)-1))
        u = (distance-distances[i]) / max(1e-9, distances[i+1]-distances[i])
        return tuple(a+(b-a)*u for a, b in zip(points[i], points[i+1]))


@dataclass
class CircuitRun:
    first: BatterRun | None
    sprint_fts: float
    start_base: int = 0
    pieces: list = field(default_factory=list)
    first_cutoff_s: float = math.inf
    target_base: int = 1
    stopped_at_s: float | None = None
    returning: bool = False
    run_through_first: bool = False  # keep the first-leg deceleration beyond the bag when holding
    advance_used: bool = False  # a corrective return never grants a new automatic advance

    def __post_init__(self):
        if self.start_base:
            self.target_base = self.start_base
        elif self.first is not None:
            self.advance_used = True

    @property
    def top_fts(self):
        # Curves, acceleration and braking are explicit here. Multiplying
        # by the old running-start efficiency would charge those losses twice.
        return max(1.0, self.sprint_fts)

    def arrival_at(self, base):
        if base == self.start_base:
            return 0.0
        for piece in self.pieces:
            if piece.base == base and piece.arrival_s <= piece.cutoff_s:
                return piece.arrival_s
        if base == 1 and self.first is not None and self.first.arrival_s <= self.first_cutoff_s:
            return self.first.arrival_s
        return math.inf

    @property
    def arrival_s(self):
        return self.pieces[-1].arrival_s if self.pieces else self.arrival_at(self.target_base)

    def position_at(self, time_s):
        if self.stopped_at_s is not None:
            time_s = min(time_s, self.stopped_at_s)
        if self.first is not None and time_s <= self.first_cutoff_s:
            return self.first.position_at(time_s if self.run_through_first else min(time_s, self.first.arrival_s))
        for piece in self.pieces:
            if time_s <= min(piece.cutoff_s, piece.arrival_s):
                return piece.position_at(time_s)
        return BASE_FT[self.target_base]

    def velocity_at(self, time_s):
        if time_s >= self.arrival_s and not (self.run_through_first and self.first is not None and not self.pieces):
            return (0.0, 0.0)
        a, b = self.position_at(time_s), self.position_at(time_s + 0.001)
        return tuple((y-x)/0.001 for x, y in zip(a, b))

    def _truncate(self, time_s):
        """End the played route at `time_s`, keeping everything before it.

        The leg in progress is cut there and any leg that has not started
        is dropped. Cutting only the last leg used to leave a rounding tail
        running after a retreat: the runner kept going to the bag, touched
        it after he had turned back, and then jumped onto the return leg.
        """
        kept = []
        for piece in self.pieces:
            if piece.start_s >= time_s:
                continue
            if time_s < min(piece.cutoff_s, piece.arrival_s):
                piece = replace(piece, cutoff_s=time_s)
            kept.append(piece)
        self.pieces[:] = kept
        if (not kept and self.first is not None
                and time_s < min(self.first_cutoff_s, self.first.arrival_s)):
            self.first_cutoff_s = time_s

    def commit_next(self, time_s):
        """Change only the unplayed tail; committed movement never jumps."""
        if self.target_base >= 4 or self.stopped_at_s is not None or self.returning:
            return False
        self.advance_used = True
        current, nxt = self.target_base, self.target_base + 1
        origin = BASE_FT[current]
        if time_s < self.arrival_s:
            point = self.position_at(time_s)
            velocity = self.velocity_at(time_s)
            speed = min(self.top_fts, math.hypot(*velocity))
            self._truncate(time_s)
            tail = RunLeg(point, current, time_s, self.top_fts, speed,
                          self.top_fts*ROUNDING_SPEED_SHARE,
                          _unit(velocity), _corner_direction(current))
            self.pieces.append(tail)
            start, initial, direction = tail.arrival_s, tail.end_fts, tail.end_direction
        else:
            start, initial, direction = time_s, 0.0, None
            if self.first is not None and not self.pieces:
                if self.run_through_first:
                    origin = self.position_at(time_s)
                    velocity = self.velocity_at(time_s)
                    initial = min(self.top_fts, math.hypot(*velocity))
                    direction = _unit(velocity) if initial > 0 else None
                self.first_cutoff_s = time_s if self.run_through_first else self.first.arrival_s
        self.pieces.append(RunLeg(origin, nxt, start, self.top_fts, initial,
                                  start_direction=direction))
        self.target_base = nxt
        return True

    def preview_next(self, time_s):
        projected = copy.deepcopy(self)
        projected.commit_next(time_s)
        return projected

    def projected_next(self, time_s):
        return self.preview_next(time_s).arrival_s

    def touches(self, through_s=math.inf):
        if self.stopped_at_s is not None:
            through_s = min(through_s, self.stopped_at_s)
        contacts = [(p.base, p.arrival_s) for p in self.pieces if p.arrival_s <= p.cutoff_s]
        if self.first is not None and self.first.arrival_s <= self.first_cutoff_s:
            contacts.insert(0, (1, self.first.arrival_s))
        return tuple((b, t) for b, t in contacts if t <= through_s)

    def base_at(self, time_s):
        return next((base for base, t in reversed(self.touches(time_s))), self.start_base)

    def contacts(self, base):
        """`(arrive_s, leave_s)` for each time the runner is on `base`.

        Read off the played and planned legs. A bag he carries through is a
        zero-length contact; a bag he holds has `leave_s = inf`. Nothing
        after a retirement counts.
        """
        out_s = math.inf if self.stopped_at_s is None else self.stopped_at_s
        arrivals = []
        if base == self.start_base and self.start_base > 0:
            arrivals.append((0.0, 0))
        if base == 1 and self.first is not None and self.first.arrival_s <= self.first_cutoff_s:
            arrivals.append((self.first.arrival_s, 0))
        for i, piece in enumerate(self.pieces):
            if piece.base == base and piece.arrival_s <= piece.cutoff_s:
                arrivals.append((piece.arrival_s, i + 1))
        spans = []
        for arrive, after in arrivals:
            if arrive > out_s:
                continue
            leave = next((p.start_s for p in self.pieces[after:] if p.start_s >= arrive), math.inf)
            if base == 1 and after == 0 and self.first is not None and self.run_through_first:
                leave = min(leave, self.first.arrival_s)
            spans.append((arrive, min(leave, out_s)))
        return tuple(spans)

    def retrace_to(self, base, time_s):
        """Go back to `base`, retouching every bag passed on the way out.

        A runner returning to his original base must touch the bases in
        reverse order (OBR 5.09(c)(2)), so a return from beyond second to
        first goes through second rather than across the diamond. He
        carries through an intermediate bag at rounding speed. Past
        positions and contacts are kept; only the unplayed tail changes.
        """
        point = self.position_at(time_s)
        last = self.base_at(time_s)
        self._truncate(time_s)
        stops = [b for b in range(max(last, base), base - 1, -1)]
        if len(stops) > 1 and math.dist(point, BASE_FT[stops[0]]) < 1e-6:
            stops = stops[1:]
        start, initial, direction, origin = time_s, 0.0, None, point
        for i, stop in enumerate(stops):
            through = i < len(stops) - 1
            leg = RunLeg(origin, stop, start, self.top_fts, initial,
                         self.top_fts*ROUNDING_SPEED_SHARE if through else 0.0,
                         direction, tuple(-x for x in _corner_direction(stop)) if through else None)
            self.pieces.append(leg)
            start, initial, direction, origin = leg.arrival_s, leg.end_fts, leg.end_direction, BASE_FT[stop]
        self.target_base, self.returning = base, True

    def return_to(self, base, time_s):
        self.retrace_to(base, time_s)

    def forward_base(self, time_s):
        """The next forward bag when interrupting a corrective return."""
        if not self.returning:
            return self.target_base + 1
        point = self.position_at(time_s)
        for base in range(1, 5):
            if math.dist(point, BASE_FT[base]) < 1e-6:
                return base + 1
        return next((p.base + 1 for p in self.pieces
                     if p.start_s <= time_s < min(p.arrival_s, p.cutoff_s)), self.target_base + 1)

    def resume_to(self, base, time_s):
        """Turn back toward an attempted bag without rewriting past contacts."""
        point = self.position_at(time_s)
        self._truncate(time_s)
        self.pieces.append(RunLeg(point, base, time_s, self.top_fts))
        self.target_base, self.returning = base, False
        self.advance_used = True
