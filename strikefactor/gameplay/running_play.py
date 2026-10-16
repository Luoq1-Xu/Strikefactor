"""Immutable events/results for a live baserunning play, in real seconds.

Hit credit, final occupancy and running outs are separate facts. A double
followed by a tag at third is still a double, but puts nobody on third.
"""

import math
from dataclasses import dataclass

from strikefactor import outcomes
from strikefactor.gameplay.base_geometry import BASE_FT

TAG_REACH_FT = 3.0
TAG_SWEEP_S = 0.12
TAG_UP_REACTION_S = 0.20


def schedule_tag_s(route, base, received_s):
    """Earliest glove contact in reach, after receiving and sweeping the tag.

    The last approach is monotonic toward the bag. Search that physical
    route for reach; a receiver cannot tag a runner halfway up the basepath.
    A tag at or after foot contact leaves the runner safe.
    """
    left = route.pieces[-1].start_s
    right = route.arrival_s
    for _ in range(40):
        middle = (left + right) / 2
        if math.dist(route.position_at(middle), BASE_FT[base]) > TAG_REACH_FT:
            left = middle
        else:
            right = middle
    contact = max(received_s + TAG_SWEEP_S, right)
    return contact if contact < route.arrival_s - 1e-12 else None


@dataclass(frozen=True)
class RunningEvent:
    time_s: float
    label: str
    runner_id: str | None = None
    base: int | None = None
    role: str | None = None


@dataclass(frozen=True)
class RunnerMovement:
    runner_id: str
    start_base: int
    final_base: int | None
    touches: tuple  # (base, contact-to-touch seconds)
    out_s: float | None = None
    on_throw_bases: tuple = ()  # successful contacts earned by another throw

    @property
    def scored_s(self):
        return next((t for base, t in self.touches if base == 4), None)


@dataclass(frozen=True)
class RunnerRetirement:
    runner_id: str
    time_s: float
    base: int
    kind: str  # force, batter_before_first, tag, catch
    role: str | None = None


@dataclass(frozen=True)
class RunningResult:
    outcome: str
    hit_bases: int
    movements: tuple
    events: tuple = ()
    error_out: str | None = None
    error_bases: int = 0
    retirements: tuple = ()
    fielding_sequence: tuple = ()

    @property
    def outs_added(self):
        return len(self.retirements) if self.retirements else sum(m.out_s is not None for m in self.movements)

    @property
    def double_play(self):
        return self.outs_added == 2

    @property
    def ground_double_play(self):
        return (self.double_play and self.outcome == outcomes.GROUNDOUT
                and any(r.kind in ("force", "batter_before_first") for r in self.retirements))

    @property
    def display_name(self):
        return outcomes.play_display_name(self.outcome, self.double_play, self.fielding_sequence)

    @property
    def running_outs(self):
        return self.outs_added - int(self.outcome in outcomes.BATTED_OUT_OUTCOMES)

    @property
    def batter(self):
        return next(m for m in self.movements if m.runner_id == "B")

    @property
    def batter_on_throw_base(self):
        batter = self.batter
        return (batter.final_base if self.outcome in outcomes.HIT_OUTCOMES
                and batter.final_base is not None and batter.final_base > self.hit_bases else None)


@dataclass(frozen=True)
class ThrowLeg:
    origin: tuple
    target: tuple
    release_s: float
    arrival_s: float
    thrower: str
    receiver: str

    def position_at(self, time_s):
        fraction = min(1.0, max(0.0, (time_s - self.release_s)
                               / max(1e-9, self.arrival_s - self.release_s)))
        return tuple(a + (b - a) * fraction for a, b in zip(self.origin, self.target))


@dataclass(frozen=True)
class BaseRace:
    base: int
    runner_s: float
    defense_s: float
    tag_s: float | None = None
    kind: str = "tag"

    @property
    def margin_s(self):
        return self.runner_s - self.defense_s

    @property
    def tag_margin_s(self):
        return None if self.tag_s is None else self.runner_s - self.tag_s
