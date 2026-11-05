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


# The batter: contact quality and spray drawn from the distributions players
# actually produce. `tools/sim.py` owns the numbers and explains them. Neither
# is uniform, and sweeping either as if it were is how this file once reported
# a 7.6% infield-hit rate against a real 3.8% (quality) and 17% against 6-8%
# (no spray: every grounder over second base). There used to be a copy of the
# numbers here, pinned to the shared ones by a test; the shared ones are the
# only copy now.
_realistic_spray = conftest.realistic_spray
_realistic_quality = conftest.realistic_quality


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
#
# The seed must not be a function of `n`. Seeding on the sample size made
# `_sample(200)`, `_sample(600)` and `_sample(800)` three *unrelated*
# populations for the same batter, so 1000 plays were simulated to obtain a
# sample the 800 already contained. It is pinned at the largest size asked for
# here instead, which keeps the four `_sample(800)` tests — the MLB-anchored
# infield-hit band among them — on exactly the sample they were calibrated
# against, and makes the smaller sizes prefixes of it.
#
# The cache holds the *raw* plays rather than the fielded ones, because
# `_sample(200)` means "the fielded subset of the first 200 plays". A prefix of
# the filtered list would mean "the first 200 fielded plays", which is a
# different and larger sample.
_SEED_N = 800
_RAW_CACHE = {}

# One draw stream for every setting, so that play `i` is the same ball off the
# bat whatever the hand or difficulty: that is what lets `_paired` compare two
# settings play by play. Pinned at the value the default (R, 1.0) sample has
# always used, so the calibrated `_sample(800)` is unchanged.
_SEED = _SEED_N * 7919 + 101


def _raw(n, hand="R", modifier=1.0):
    """The first `n` grounders, fielded or not, in draw order.

    A left-hander's spray is mirrored. Spray is pull-positive, so the same
    angle would send a left-hander's ball to the other side of the infield;
    mirrored, play `i` lands on the same spot for both hands.
    """
    key = (hand, modifier)
    raw, rng = _RAW_CACHE.get(key) or ([], random.Random(_SEED))
    mirror = -1.0 if hand == "L" else 1.0
    for i in range(len(raw), n):
        quality = _realistic_quality(rng)
        raw.append(_play(i, quality, hand, modifier,
                         spray_deg=mirror * _realistic_spray(rng)))
    _RAW_CACHE[key] = (raw, rng)
    return raw[:n]


def _sample(n=600, hand="R", modifier=1.0):
    """Grounders that an infielder actually came up with."""
    return [a for a in _raw(n, hand, modifier) if a.play_timing is not None]


def _paired(n, a, b):
    """Play `i` under settings `a` beside play `i` under settings `b`.

    The same ball, the same fielders and the same draws, so the only thing
    that differs is the setting. A comparison between two independent samples
    needed 700 plays a side to stay clear of its own noise; paired, a setting
    that helps the runner has to win *every* close play, which is both a
    stronger claim and one that 200 plays settle.
    """
    pairs = list(zip(_raw(n, **a), _raw(n, **b)))
    for x, y in pairs:
        assert (x.play_timing is None) == (y.play_timing is None), \
            "a setting about the runner changed who fielded the ball"
    return [(x, y) for x, y in pairs if x.play_timing is not None]


def _assert_only_the_runner_moved(pairs):
    """`faster` beats out every play `slower` does, on an identical defense."""
    gained = 0
    for faster, slower in pairs:
        assert faster.play_timing.defense_s == pytest.approx(
            slower.play_timing.defense_s, abs=1e-9)
        assert faster.play_timing.runner_s <= slower.play_timing.runner_s
        assert _reached(faster) or not _reached(slower), \
            "the faster runner was thrown out on a play the slower one beat"
        gained += _reached(faster) and not _reached(slower)
    assert gained > 0, "the faster runner never turned a close play"


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
    pairs = _paired(200, dict(hand="L"), dict(hand="R"))
    for lefty, righty in pairs:
        assert lefty.play_timing.runner_s < righty.play_timing.runner_s
    _assert_only_the_runner_moved(pairs)


def test_difficulty_moves_the_runners_clock():
    """Harder difficulty = more outs, expressed as a slower batter rather
    than a thumb on the verdict: the defense is untouched and ROOKIE beats
    out every play HALL_OF_FAME does, and more."""
    pairs = _paired(200, dict(modifier=0.7), dict(modifier=1.6))
    for rookie, hall_of_fame in pairs:
        assert rookie.play_timing.runner_s < hall_of_fame.play_timing.runner_s
    _assert_only_the_runner_moved(pairs)
