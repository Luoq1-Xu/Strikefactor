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


def _play(seed, quality, hand="R", modifier=1.0):
    """Run one grounder to completion; returns the finished animation."""
    random.seed(seed)
    anim = ha.HitAnimation(_StubGame(hand, modifier), outcome="IN_PLAY",
                           on_complete=lambda: None, quality=quality,
                           batted_ball_type="GROUNDER")
    t = 0
    while not anim.finished and t < 12000:
        t += 16
        anim.update(t)
    return anim


def _sample(n=600, hand="R", modifier=1.0):
    """Grounders that an infielder actually came up with."""
    fielded = []
    for i in range(n):
        anim = _play(i, (i % 50) / 50.0, hand, modifier)
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


def test_a_scorched_grounder_is_essentially_never_an_infield_hit():
    hard = [a for a in _sample(800)
            if contact_audio.exit_velocity_mph(a.quality) >= 95]
    assert hard, "no hard-hit sample"
    beaten = sum(1 for a in hard if a.classified_outcome == "SINGLE")
    assert beaten / len(hard) < 0.03


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
