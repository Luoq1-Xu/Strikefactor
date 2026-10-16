"""Physical return-throw previews and defensive choices, without pygame/RNG.

Released legs belong to the played timeline. Only their unthrown successors
may change. Every receiver/cutoff is an actual actor with one assignment.
"""

import math
from dataclasses import dataclass, replace

from strikefactor.gameplay import extra_bases, infield_timing
from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.runner_motion import BaseApproach
from strikefactor.gameplay.running_play import TAG_SWEEP_S, ThrowLeg

# A new target must materially improve the choice, rather than causing a
# defender to pivot back and forth between near-equal plays every frame.
SWITCH_ADVANTAGE = 0.20
TURN_SETUP_S = 0.12


@dataclass(frozen=True)
class Defender:
    role: str
    position: tuple
    speed_fts: float
    acceleration_s: float
    initial_fraction: float
    available_s: float


def project_defenders(defenders, approaches, time_s):
    """Read planned coverage at a future reception without moving any actor."""
    projected = dict(defenders)
    for role, path in approaches.items():
        speed = (0.0 if time_s >= path.arrival_s else
                 min(path.speed_fts, path.initial_fts + path.acceleration*max(0.0, time_s-path.start_s)))
        projected[role] = replace(defenders[role], position=path.position_at(time_s),
                                  initial_fraction=speed/path.speed_fts)
    return projected


@dataclass(frozen=True)
class ReturnCandidate:
    runner_id: str
    base: int
    runner_s: float
    legs: tuple
    approaches: dict
    concession: float = 0.0
    kind: str = "tag"

    @property
    def arrival_s(self):
        return self.legs[-1].arrival_s

    def value(self, outs):
        # This probability estimates a decision, never adjudicates a tag.
        sweep = TAG_SWEEP_S if self.kind == "tag" else 0.0
        probability = infield_timing.p_out_from_margin(
            self.runner_s - self.arrival_s - sweep, extra_bases.SIGMA_TAG_S)
        return probability * (1.0 + min(2, outs) * 0.5 + (self.base == 4)) - self.concession


def choose_return(candidates, outs, current=None):
    """Prefer a contestable out, charging for bases conceded behind it."""
    plausible = [c for c in candidates
                 if c.arrival_s + (TAG_SWEEP_S if c.kind == "tag" else 0.0)
                 <= c.runner_s + infield_timing.BANG_BANG_S]
    if not plausible:
        return None
    best = max(plausible, key=lambda c: (c.value(outs), c.base, c.runner_id))
    previous = next((c for c in plausible if (c.runner_id, c.base) == current), None)
    if previous is not None and best.value(outs) < previous.value(outs) + SWITCH_ADVANTAGE:
        return previous
    return best


def schedule_return(base, point, pickup_s, defenders, defense, *, holder,
                    transfer_s=None, allow_relay=True, carry_delay_s=None):
    """Preview with the same actors, cover waits and exchanges as execution."""
    receiver_pool = {1: ("1B", "P", "2B"), 2: ("SS", "2B"),
                     3: ("3B", "SS"), 4: ("C", "P")}[base]

    def approach(role, target):
        f = defenders[role]
        return BaseApproach(f.position, target, max(pickup_s, f.available_s),
                            f.speed_fts, f.acceleration_s, f.initial_fraction)

    receiver, cover = min(((r, approach(r, BASE_FT[base]))
                          for r in receiver_pool if r != holder),
                         key=lambda pair: pair[1].arrival_s)
    approaches = {receiver: cover}
    exchange = (extra_bases.OF_RELEASE_S if holder in ("LF", "CF", "RF")
                else extra_bases.IF_RELEASE_S) * defense.release_scale
    release = pickup_s + (exchange if transfer_s is None else transfer_s)
    arm, legs = defense.throw_fts, []
    if allow_relay and math.dist(point, BASE_FT[base]) > extra_bases.RELAY_DISTANCE_FT:
        cutoff_ft = tuple(a + (b-a)*0.5 for a, b in zip(point, BASE_FT[base]))
        relay, cutoff = min(((r, approach(r, cutoff_ft))
                             for r in ("2B", "SS", "P") if r not in (holder, receiver)),
                            key=lambda pair: pair[1].arrival_s)
        flight = math.dist(point, cutoff_ft) / arm
        if cutoff.arrival_s <= release + flight:
            approaches[relay] = cutoff
            legs.append(ThrowLeg(point, cutoff_ft, release, release + flight, holder, relay))
            point, holder = cutoff_ft, relay
            release = legs[-1].arrival_s + extra_bases.RELAY_EXCHANGE_S
    flight = math.dist(point, BASE_FT[base]) / arm
    release = max(release, cover.arrival_s - flight)
    legs.append(ThrowLeg(point, BASE_FT[base], release, release + flight, holder, receiver))
    if carry_delay_s is not None and holder in receiver_pool:
        f = defenders[holder]
        carry = BaseApproach(f.position, BASE_FT[base], pickup_s + carry_delay_s,
                            f.speed_fts, f.acceleration_s, 0.0)
        if carry.arrival_s <= legs[-1].arrival_s:
            return (ThrowLeg(f.position, BASE_FT[base], carry.start_s,
                             carry.arrival_s, holder, holder),), {holder: carry}
    return tuple(legs), approaches


def possession_forecast(legs, now_s):
    """Where the ball can next be played, accounting only for released legs."""
    for leg in legs:
        if now_s < leg.release_s:
            return leg.origin, now_s, leg.thrower
        if now_s < leg.arrival_s:
            return leg.target, leg.arrival_s, leg.receiver
    return legs[-1].target, now_s, legs[-1].receiver
