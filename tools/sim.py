"""Headless balls in play: the batter model, and one way to simulate a play.

This exists because there was only ever *one* way to run a `HitAnimation`
without a screen, and it lived inside `tests/test_defense.py`. That is the
wrong home for it twice over. `docs/defense-strength.md` says a
`DefenseProfile` is a value precisely so "a calibration harness can sweep four
levels in a loop", and the numbers quoted throughout that document and in the
test docstrings -- the ladder running 3.04% / 2.16% / 1.00% / 0.64% of balls
in play at n=2500 -- were produced by a harness that was never committed. So
the claims could not be re-derived, and the next person to tune a constant had
to rebuild the measuring instrument before they could measure anything.

Nothing here is test-only. `tests/conftest.py` re-exports the samplers,
`tests/test_defense.py` takes the builder, and `tools/calibrate_defense.py`
sweeps with both -- so the harness and the suite are looking at the same
batter facing the same defense, which is the only way a band asserted in a
test and a number quoted in a doc can mean the same thing.

Pygame is imported lazily, inside `ball_in_play`, so importing this module
costs nothing and stays out of the way of the purity tests.
"""

import os
import random

# Before pygame is initialised anywhere, for the reason `tests/conftest.py`
# gives: the driver choice is cached on first init. `setdefault` so a caller
# that wants a real window can still ask for one.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


# ---- The batter the model actually faces ----------------------------------
#
# **Contact quality is not uniform.** It is only computed for swings that
# already squared the ball up enough to put it in play, so its real
# distribution is crowded toward 1.0. Tuning against a `range(0, 1)` sweep is
# tuning against a batter who does not exist — it is how the infield release
# time, the batted-ball landing depth, the wall-ball rate and the contact-audio
# ladder were each miscalibrated in turn. Anchored to the same quantiles as
# `contact_audio.EV_CALIBRATION`; the two must move together.
#
# Approximated by quantiles rather than read from the DB: a harness that needs
# strikefactor.db is a harness that breaks on a fresh checkout, and the DB
# holds rows from several contact-geometry vintages at once anyway.
QUALITY_QUANTILES = (
    (0.10, 0.643), (0.25, 0.689), (0.50, 0.763), (0.75, 0.871), (0.90, 0.937),
)

# **And spray is not uniform either** — the same trap one axis over, and it
# bites harder: a `HitAnimation` built without a `spray_deg` sends the ball to
# *exactly* dead centre, so a sweep that forgets it puts every grounder over
# second base, the one place middle infielders cannot reach, and reports an
# infield-hit rate of 17% against a real 6-8%. Before `spray` the animation
# drew its own angle, so callers got a spread for free; now the swing supplies
# it and the harness has to. Mean +1.8°, sd 19.9°, pull-positive.
#
# The mean came in from +4.4° when the location term in `spray` was made to
# saturate. It is *not* that the bat stopped pulling: the straight-line term
# was sending the opposite-field tail past the foul line, so those balls were
# missing from the fair population entirely and the surviving mean sat too far
# to the pull side. Releasing them moves the mean back, not the bat.
SPRAY_MEAN_DEG, SPRAY_SD_DEG = 1.8, 19.9

# What this game's bat actually produces, measured over 170 recorded balls in
# play (`batted_ball_type` is never set on a foul, so that is the true
# population). It is markedly liner-heavy and fly-light against MLB's
# ~43/21/36 — which matters for anything about catches, because the population
# a drop can happen to is a third smaller than MLB's while the liners in it are
# the hardest catches there are.
BATTED_BALL_MIX = (
    ("GROUNDER", 0.459),
    ("LINER", 0.276),
    ("FLY", 0.235),
    ("POP_UP", 0.029),
)


def realistic_quality(rng):
    """Draw a contact quality from the distribution players produce."""
    u = rng.random()
    pts = QUALITY_QUANTILES
    if u <= pts[0][0]:
        return pts[0][1] * u / pts[0][0]
    for (p0, q0), (p1, q1) in zip(pts, pts[1:]):
        if u <= p1:
            return q0 + (q1 - q0) * (u - p0) / (p1 - p0)
    last_p, last_q = pts[-1]
    return last_q + (1.0 - last_q) * (u - last_p) / (1.0 - last_p)


def realistic_spray(rng):
    """Draw a spray angle from the distribution players produce."""
    while True:
        deg = rng.gauss(SPRAY_MEAN_DEG, SPRAY_SD_DEG)
        if abs(deg) <= 45.0:
            return deg


def realistic_batted_ball(rng):
    """Draw a batted-ball type from the mix this game's bat produces."""
    u = rng.random()
    cum = 0.0
    for shape, share in BATTED_BALL_MIX:
        cum += share
        if u <= cum:
            return shape
    return BATTED_BALL_MIX[-1][0]


# ---- Enough game to build a HitAnimation ----------------------------------

class StubBatter:
    def get_handedness(self):
        return "R"


class StubGame:
    """A `HitAnimation` reads exactly this much of the game.

    Deliberately without a `settings_manager`: the right answer for a game
    that has none is the neutral defense, which the `defense=` kwarg's default
    already says. See `PitchSimulation._defense_profile`.
    """

    def __init__(self, handedness="R"):
        self.batter = StubBatter()
        self.batter.get_handedness = lambda: handedness


def init_headless(size=(1280, 720)):
    """Bring pygame up with no display or sound device.

    For standalone callers. The test suite has its own session fixture, which
    has to own teardown as well.
    """
    import pygame
    pygame.init()
    pygame.display.set_mode(size)


# ---- One ball in play -----------------------------------------------------

FRAME_MS = 16
MAX_PLAY_MS = 14000


def ball_in_play(seed, quality, shape, spray_deg, profile, handedness="R"):
    """Run one batted ball to completion and hand back the finished animation.

    The global RNG is seeded from `seed` so that play `i` is a function of `i`
    alone. That is what makes a sweep reproducible and, more usefully, makes a
    longer sweep a strict superset of a shorter one with the same parameters —
    see `sweep`.
    """
    from strikefactor.gameplay.hit_animation import HitAnimation
    random.seed(seed)
    anim = HitAnimation(StubGame(handedness), outcome="IN_PLAY",
                        on_complete=lambda: None,
                        quality=quality, batted_ball_type=shape,
                        spray_deg=spray_deg, defense=profile)
    t = 0
    while not anim.finished and t < MAX_PLAY_MS:
        t += FRAME_MS
        anim.update(t)
    return anim


# ---- Sweeps, memoized and extending ---------------------------------------
#
# These sweeps are deterministic: `ball_in_play` seeds the global RNG from the
# play index and every draw comes from a locally seeded `random.Random`, so
# the same arguments always produce the same plays. Callers deliberately
# assert *different* properties of the same sample — a merged test that failed
# would name six possible causes instead of one — so simulating once and
# handing the result out keeps both: separate assertions, one run.
#
# A longer sweep is a *superset* of a shorter one with the same
# (profile, seed, shape, handedness): play `i` depends only on `i` and on the
# draws made before it, so `sweep(p, 400, seed)[:200] == sweep(p, 200, seed)`
# exactly. The cache serves those prefixes rather than re-simulating them, and
# it also *extends* — keeping the `random.Random` alongside the plays and
# continuing it, so asking for 400 after 260 simulates 140 more rather than
# throwing the 260 away.
#
# `shape` belongs in the key because passing one *skips* the batted-ball draw,
# which shifts the whole downstream stream — a forced-GROUNDER run and a free
# run are different samples, not the same one filtered.
#
# Cached plays are shared objects. Nothing that reads a sweep may mutate one;
# see `_scratch` in tests/test_defense.py for what it costs when something
# genuinely has to.
_PLAY_CACHE = {}


def sweep(profile, n, seed=4242, shape=None, handedness="R"):
    """`n` balls in play against one defense, memoized and prefix-served."""
    key = (profile, seed, shape, handedness)
    plays, rng = _PLAY_CACHE.get(key) or ([], random.Random(seed))
    for i in range(len(plays), n):
        q = realistic_quality(rng)
        s = shape or realistic_batted_ball(rng)
        deg = realistic_spray(rng)
        plays.append(ball_in_play(i, q, s, deg, profile, handedness))
    _PLAY_CACHE[key] = (plays, rng)
    return plays[:n]
