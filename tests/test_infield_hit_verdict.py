"""Fielding a ground ball is no longer the same thing as recording an out.

Reaching the ball used to *be* the verdict — a fielder's body within 12 px
of it and the batter was out, with the throw to first played afterwards as
decoration that could not change the call. So there was no runner, no throw
distance, no bang-bang play, and the softest contact was converted most
reliably of all: dawdling to the fielder gave them more time to get there.

These guard the race that replaced it. `infield_timing` is unit-tested on
its own; what is checked here is that the animation actually consults it
and that the resulting distribution looks like baseball.
"""

import collections
import random

import pytest

from strikefactor.engine import contact_audio
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay import infield_timing


class _StubBatter:
    def __init__(self, hand="R"):
        self._hand = hand

    def get_handedness(self):
        return self._hand


class _StubSettings:
    def __init__(self, modifier=1.0):
        self._m = modifier

    def get_difficulty_multipliers(self):
        return {"out_probability_modifier": self._m}


class _StubGame:
    def __init__(self, hand="R", modifier=1.0):
        self.batter = _StubBatter(hand)
        self.settings_manager = _StubSettings(modifier)


def _play(seed, quality, hand="R", modifier=1.0, spray_deg=0.0):
    """Run one grounder to completion; returns the finished animation."""
    random.seed(seed)
    anim = ha.HitAnimation(_StubGame(hand, modifier), outcome="IN_PLAY",
                           on_complete=lambda: None, quality=quality,
                           batted_ball_type="GROUNDER", spray_deg=spray_deg)
    t = 0
    while not anim.finished and t < 12000:
        t += 16
        anim.update(t)
    return anim


# Contact quality is NOT uniform, and assuming it is has now caused the
# same class of miscalibration three times in this codebase (see
# contact_audio.EV_CALIBRATION and ball_flight.carry_distance_ft). Quality
# is only computed for swings that squared the ball up enough to put it in
# play, so its real distribution is crowded against 1.0 — nothing like the
# `(i % 50) / 50.0` sweep these tests used to run. That sweep reported a
# 7.6% infield-hit rate where the real distribution gave 3.8%, which is how
# the model came to be calibrated against a batter who does not exist.
#
# Re-derived most recently when the ball got a *direction* (`spray`), which
# changed which contacts are fair: p10 0.580 / p25 0.653 / p50 0.743 / p75
# 0.858 / p90 0.932, against 0.690 / 0.717 / 0.769 / 0.851 / 0.918 for the
# slide model before it. Both tails widened — the quality threshold came down
# to 0.52 because it no longer carries the whole foul verdict, and a
# well-struck ball can now be hooked foul and leave the fair population.
# These must stay in step with EV_CALIBRATION, which is anchored to the same
# quantiles — move one without the other and this file silently starts
# describing a different batter from the one the exit-velocity model does.
#
# Approximated here by its quantiles rather than read from the DB: a test
# that needs strikefactor.db is a test that breaks on a fresh checkout.
_QUALITY_QUANTILES = (
    (0.10, 0.580), (0.25, 0.653), (0.50, 0.743), (0.75, 0.858), (0.90, 0.932),
)

# **And spray is not uniform either.** This is the same trap one axis over, and
# it bites harder: a `HitAnimation` built without a `spray_deg` sends the ball
# to *exactly* dead centre, so a sweep that forgets it hits every grounder over
# second base — the one place middle infielders cannot reach — and reports an
# infield-hit rate of 17% against a real 6-8%. Before `spray` the landing angle
# was drawn from `random.uniform(50°, 130°)` inside the animation, so tests got
# a spread for free; now the swing supplies it and the harness has to.
#
# Measured over the fair balls a plausible player produces at AMATEUR: mean
# +4.4°, sd 20.0°. Pull-positive, so a right-handed batter's positive is
# toward third.
_SPRAY_MEAN_DEG, _SPRAY_SD_DEG = 4.4, 20.0


def _realistic_spray(rng):
    """Draw a spray angle from the distribution players produce."""
    while True:
        deg = rng.gauss(_SPRAY_MEAN_DEG, _SPRAY_SD_DEG)
        if abs(deg) <= 45.0:
            return deg


def _realistic_quality(rng):
    """Draw a contact quality from the distribution players produce."""
    u = rng.random()
    pts = _QUALITY_QUANTILES
    if u <= pts[0][0]:
        return pts[0][1] * u / pts[0][0]
    for (p0, q0), (p1, q1) in zip(pts, pts[1:]):
        if u <= p1:
            return q0 + (q1 - q0) * (u - p0) / (p1 - p0)
    last_p, last_q = pts[-1]
    return last_q + (1.0 - last_q) * (u - last_p) / (1.0 - last_p)


def _sample(n=600, hand="R", modifier=1.0):
    """Grounders that an infielder actually came up with."""
    rng = random.Random(n * 7919 + len(hand) + int(modifier * 100))
    fielded = []
    for i in range(n):
        anim = _play(i, _realistic_quality(rng), hand, modifier,
                     spray_deg=_realistic_spray(rng))
        if anim.play_timing is not None:
            fielded.append(anim)
    return fielded


# ---- The animation consults the model -------------------------------------

def test_a_fielded_grounder_records_both_clocks():
    fielded = _sample(200)
    assert fielded, "no grounder was fielded by an infielder"
    t = fielded[0].play_timing
    assert t.defense_s == pytest.approx(
        t.ball_to_glove_s + t.release_s + t.throw_flight_s)
    assert t.runner_s > 0
    assert 0.0 <= t.p_out <= 1.0


def test_reaching_the_ball_is_no_longer_automatically_an_out():
    """The headline change. Some balls the infield fields are still hits."""
    outcomes = collections.Counter(a.classified_outcome for a in _sample(600))
    assert outcomes["GROUNDOUT"] > 0
    assert outcomes["SINGLE"] > 0, "every fielded grounder was still an out"


def test_the_verdict_is_computed_in_real_feet_not_pixels():
    """The model reasons in feet; the animation draws in an anisotropically
    projected pixel space. Feeding it pixels would bake the projection into
    the physics."""
    fielded = _sample(200)
    # A throw to first is ~35-160 ft; in pixels the same span reads 60-300.
    for anim in fielded[:40]:
        assert anim.play_timing.throw_flight_s < 2.0


# ---- The distribution looks like baseball ---------------------------------

def test_infield_hit_rate_on_fielded_grounders_is_mlb_realistic():
    """~6-8% of grounders an infielder handles are beaten out. Above that
    band the time budget is too generous; below it, infield hits vanish."""
    fielded = _sample(800)
    beaten = sum(1 for a in fielded if a.classified_outcome == "SINGLE")
    rate = beaten / len(fielded)
    assert 0.05 <= rate <= 0.10, f"infield-hit rate {rate:.1%} off target"


def test_soft_contact_is_beaten_out_and_scorched_contact_is_not():
    """The sign flip, and the single clearest proof the clock rather than
    the geometry is deciding. The old model had this exactly backwards."""
    soft, hard = collections.Counter(), collections.Counter()
    for anim in _sample(800):
        ev = contact_audio.exit_velocity_mph(anim.quality)
        bucket = soft if ev < 70 else (hard if ev >= 95 else None)
        if bucket is not None:
            bucket["hit" if anim.classified_outcome == "SINGLE" else "out"] += 1
    soft_rate = soft["hit"] / max(1, sum(soft.values()))
    hard_rate = hard["hit"] / max(1, sum(hard.values()))
    assert soft_rate > hard_rate, (
        f"soft contact beaten out {soft_rate:.1%}, scorched {hard_rate:.1%}")


def test_a_scorched_grounder_is_rarely_an_infield_hit():
    """Rarely, not never. A ball hit hard enough gets to the fielder so
    early that the throw is routine — but `HARD_PLAY_PROB` means the
    fielder does not always handle it cleanly, and a mishandled 100 mph
    grounder is a hit in real baseball too. The band is what stops that
    becoming an excuse: the *sign flip* against soft contact is the
    load-bearing property, guarded above."""
    hard = [a for a in _sample(800)
            if contact_audio.exit_velocity_mph(a.quality) >= 95]
    assert hard, "no hard-hit sample"
    beaten = sum(1 for a in hard if a.classified_outcome == "SINGLE")
    assert beaten / len(hard) < 0.06


def test_close_plays_exist_at_all():
    """A threshold verdict makes every play a blowout in one direction.
    The logistic is there so bang-bang plays happen."""
    margins = [a.play_timing.margin_s for a in _sample(800)]
    close = sum(1 for m in margins if abs(m) < infield_timing.BANG_BANG_S)
    assert 0.03 <= close / len(margins) <= 0.20


# ---- The inputs that should matter, do ------------------------------------

def test_left_handed_batters_beat_out_more_infield_hits():
    """Their half-step down the line is worth ~0.10 s, which only shows up
    on plays that were close to begin with."""
    def rate(hand):
        f = _sample(700, hand=hand)
        return sum(1 for a in f if a.classified_outcome == "SINGLE") / len(f)
    assert rate("L") > rate("R")


def test_difficulty_moves_the_runners_clock():
    """Harder difficulty = more outs, expressed as a slower batter rather
    than a thumb on the verdict."""
    def rate(modifier):
        f = _sample(700, modifier=modifier)
        return sum(1 for a in f if a.classified_outcome == "SINGLE") / len(f)
    assert rate(0.7) > rate(1.6)      # ROOKIE beats out more than HALL_OF_FAME
