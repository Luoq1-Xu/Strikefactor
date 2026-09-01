"""Shared test setup.

Forces SDL onto its dummy video/audio drivers *before* pygame is imported by
any test or module under test, so the suite needs no display and no sound
device. This must stay at import time of conftest — pygame caches the driver
choice on first init.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402  (must follow the env setup above)
import pytest


@pytest.fixture(scope="session", autouse=True)
def _pygame_session():
    """Initialise pygame once for the whole session and tear it down after."""
    pygame.init()
    pygame.display.set_mode((1280, 720))
    yield
    pygame.quit()


# ---- The batter the model actually faces ----------------------------------
# These live here rather than in one test file because two files now sample
# them, and CLAUDE.md records that drifting copies of exactly these numbers
# have caused four separate miscalibrations. One definition, imported.
#
# **Contact quality is not uniform.** It is only computed for swings that
# already squared the ball up enough to put it in play, so its real
# distribution is crowded toward 1.0. Tuning against a `range(0, 1)` sweep is
# tuning against a batter who does not exist — it is how the infield release
# time, the batted-ball landing depth, the wall-ball rate and the contact-audio
# ladder were each miscalibrated in turn. Anchored to the same quantiles as
# `contact_audio.EV_CALIBRATION`; the two must move together.
#
# Approximated by quantiles rather than read from the DB: a test that needs
# strikefactor.db is a test that breaks on a fresh checkout.
QUALITY_QUANTILES = (
    (0.10, 0.643), (0.25, 0.689), (0.50, 0.763), (0.75, 0.871), (0.90, 0.937),
)

# **And spray is not uniform either** — the same trap one axis over, and it
# bites harder: a `HitAnimation` built without a `spray_deg` sends the ball to
# *exactly* dead centre, so a sweep that forgets it puts every grounder over
# second base, the one place middle infielders cannot reach, and reports an
# infield-hit rate of 17% against a real 6-8%. Before `spray` the animation
# drew its own angle, so tests got a spread for free; now the swing supplies it
# and the harness has to. Mean +1.8°, sd 19.9°, pull-positive.
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
