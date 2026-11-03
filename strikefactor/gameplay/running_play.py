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
        # A corrective return withdraws an early crossing. A subsequent
        # trip home scores at that later touch, never at the withdrawn one.
        if self.final_base in (1, 2, 3) or not self.touches:
            return None
        base, time_s = self.touches[-1]
        return time_s if base == 4 else None


@dataclass(frozen=True)
class RunnerRetirement:
    runner_id: str
    time_s: float
    base: int
    # force, batter_before_first, tag, catch, or appeal: the ball held on
    # the base a runner left before a caught fly was first touched.
    kind: str
    role: str | None = None
    # False only for an appeal made after the third out, which takes away
    # a run but does not add a fourth official inning out.
    official: bool = True


@dataclass(frozen=True)
class RetouchRecord:
    """A runner who was off his base when a caught fly was first touched.

    `resolution` is "pending" during play, "retouched", "appealed" or
    "moot" (retired another way, or no useful appeal remains after the
    half-inning ended). `retouched_s` is None unless he got back.
    """
    runner_id: str
    base: int
    departed_s: float
    retouched_s: float | None
    resolution: str


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
    first_touch_s: float | None = None  # a fielder's first touch of a fly ball, caught or dropped
    retouches: tuple = ()  # RetouchRecord for each runner who left too soon

    @property
    def outs_added(self):
        if self.retirements:
            return sum(r.official for r in self.retirements)
        return sum(m.out_s is not None for m in self.movements)

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

    def counts_run(self, movement, outs=0, *, unlimited_outs=False):
        """Resolve a home touch against actual outs and retouch appeals.

        A third-out appeal on a preceding runner also annuls following
        runs, even ones which crossed earlier. An advantageous subsequent
        appeal has the same scoring effect without adding an official out.
        """
        crossed = movement.scored_s
        if crossed is None or movement.out_s is not None:
            return False
        if unlimited_outs:
            return True
        retired = sorted((r for r in self.retirements if r.official), key=lambda r: r.time_s)
        times = ([r.time_s for r in retired] if self.retirements else
                 sorted(m.out_s for m in self.movements if m.out_s is not None))
        needed = 3 - outs
        if not 0 < needed <= len(times):
            return True
        third_s = times[needed - 1]
        if crossed >= third_s:
            return False
        if any(r.time_s == third_s and r.kind in ("force", "batter_before_first", "catch")
               for r in retired):
            return False
        if (not self.retirements and self.outcome in outcomes.BATTED_OUT_OUTCOMES
                and self.batter.out_s == third_s):
            return False
        starts = {m.runner_id: m.start_base for m in self.movements}
        return not any(r.kind == "appeal" and (not r.official or r.time_s == third_s)
                       and starts[r.runner_id] > movement.start_base for r in self.retirements)


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
    # None only for an appeal against a runner who is not retouching.
    runner_s: float | None
    defense_s: float
    tag_s: float | None = None
    kind: str = "tag"  # tag, force, batter_before_first or appeal

    @property
    def margin_s(self):
        return None if self.runner_s is None else self.runner_s - self.defense_s

    @property
    def tag_margin_s(self):
        return None if self.tag_s is None or self.runner_s is None else self.runner_s - self.tag_s
