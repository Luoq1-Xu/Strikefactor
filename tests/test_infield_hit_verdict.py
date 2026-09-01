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

import conftest
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
# Re-derived most recently when the location term in `spray` was made to
# saturate: p10 0.643 / p25 0.689 / p50 0.763 / p75 0.871 / p90 0.937, against
# 0.580 / 0.653 / 0.743 / 0.858 / 0.932 immediately before it. The bottom tail
# lifted and the top barely moved, because the balls the straight-line term was
# sending foul at -59 deg were *well struck* — an inside-out reach on an
# outside pitch — so releasing them back into fair territory adds solid contact
# at the bottom of the distribution.
# These must stay in step with EV_CALIBRATION, which is anchored to the same
# quantiles — move one without the other and this file silently starts
# describing a different batter from the one the exit-velocity model does.
#
# Approximated here by its quantiles rather than read from the DB: a test
# that needs strikefactor.db is a test that breaks on a fresh checkout.
_QUALITY_QUANTILES = (
    (0.10, 0.643), (0.25, 0.689), (0.50, 0.763), (0.75, 0.871), (0.90, 0.937),
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
# +1.8°, sd 19.9°. Pull-positive, so a right-handed batter's positive is
# toward third. The mean came in from +4.4° when the location term in `spray`
# was made to saturate — the opposite-field tail used to be fouled off past
# the line, so the surviving fair population sat too far to the pull side.
_SPRAY_MEAN_DEG, _SPRAY_SD_DEG = 1.8, 19.9


# Both samplers now live in conftest, because test_defense.py draws from the
# same distributions and two copies of these numbers is exactly how the four
# miscalibrations CLAUDE.md records happened. The module-level constants above
# are kept as the documented anchors and pinned to the shared ones below.
_realistic_spray = conftest.realistic_spray
_realistic_quality = conftest.realistic_quality


def test_the_sampler_constants_have_not_drifted_from_the_shared_ones():
    """`_QUALITY_QUANTILES` here and `EV_CALIBRATION` in contact_audio are
    anchored to the same measured distribution. If this file's copy and
    conftest's ever disagree, one of them is describing a different batter."""
    assert _QUALITY_QUANTILES == conftest.QUALITY_QUANTILES
    assert (_SPRAY_MEAN_DEG, _SPRAY_SD_DEG) == (conftest.SPRAY_MEAN_DEG,
                                                conftest.SPRAY_SD_DEG)


# One sample, many assertions. `_sample` is deterministic — `_play` seeds the
# global RNG per play and the draw stream comes from a locally seeded
# `random.Random` — so the same arguments always produce the same grounders.
# Four tests below ask for `_sample(800)` verbatim and two for `_sample(200)`,
# each deliberately asserting a *different* property of the same sample. Run
# once and handed out, that is one simulation instead of six, and the tests
# stay separately legible: a band that fails names the property it guards
# rather than one merged test failing for six possible reasons.
#
# Cached objects are read-only here. Nothing in this file mutates a returned
# animation, and nothing should start — see `_scratch` in test_defense.py for
# what it costs when a test needs to poke one.
_SAMPLE_CACHE = {}


def _sample(n=600, hand="R", modifier=1.0):
    """Grounders that an infielder actually came up with."""
    key = (n, hand, modifier)
    if key not in _SAMPLE_CACHE:
        _SAMPLE_CACHE[key] = _run_sample(n, hand, modifier)
    return _SAMPLE_CACHE[key]


def _run_sample(n, hand, modifier):
    rng = random.Random(n * 7919 + len(hand) + int(modifier * 100))
    fielded = []
    for i in range(n):
        anim = _play(i, _realistic_quality(rng), hand, modifier,
                     spray_deg=_realistic_spray(rng))
        if anim.play_timing is not None:
            fielded.append(anim)
    return fielded


# The batter reaching first, however they got there. An error is reaching:
# these tests are about whether the *runner beat the play*, not about how the
# scorer wrote it up. Counting only SINGLE would make
# `test_a_scorched_grounder_is_rarely_an_infield_hit` quietly *easier* every
# time the misplay rate went up, which is exactly the regression it exists to
# catch.
_REACHED = ("SINGLE", "REACHED ON ERROR")


def _reached(anim):
    return anim.classified_outcome in _REACHED


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
    assert sum(outcomes[o] for o in _REACHED) > 0, \
        "every fielded grounder was still an out"


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
    beaten = sum(1 for a in fielded if _reached(a))
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
            bucket["hit" if _reached(anim) else "out"] += 1
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
    beaten = sum(1 for a in hard if _reached(a))
    # Widened from 0.06 when the misplay model landed. Hard contact now has a
    # *second* channel to become a hit and it is a real one: a scorched short
    # hop eats the fielder up (`defense.hop_difficulty` feeds both the misplay
    # rate and the through-share), which is how a good share of real hard-hit
    # grounders get through. The two effects genuinely oppose — the ball also
    # reaches the fielder sooner — and the load-bearing claim is the *ordering*
    # asserted in `test_soft_contact_is_beaten_out_and_scorched_contact_is_not`,
    # which is unaffected. This band only says scorched grounders stay the
    # harder way to reach.
    assert beaten / len(hard) < 0.09


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
        return sum(1 for a in f if _reached(a)) / len(f)
    assert rate("L") > rate("R")


def test_difficulty_moves_the_runners_clock():
    """Harder difficulty = more outs, expressed as a slower batter rather
    than a thumb on the verdict."""
    def rate(modifier):
        f = _sample(700, modifier=modifier)
        return sum(1 for a in f if _reached(a)) / len(f)
    assert rate(0.7) > rate(1.6)      # ROOKIE beats out more than HALL_OF_FAME
