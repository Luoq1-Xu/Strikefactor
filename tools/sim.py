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

# Pure module (real feet and seconds, no pygame), so importing it here keeps
# this file's promise that importing it costs nothing.
from strikefactor.gameplay import ball_flight

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
# Measured through the real seam — `bat_contact.resolve_contact` at AMATEUR
# over a player model with 0.75 ft/axis of aim scatter and timing N(+19, 48) ms
# — over 20,353 fair balls in play:
#
#     uv run python -m tools.calibrate_contact --n 52000 --seed 3 --anchors
#
# That prints every constant in this block. Re-derive them the same way, and
# together, whenever the contact geometry moves; CLAUDE.md lists the sites
# anchored to them.
#
# The whole distribution moved up with the square bat (it was 0.649 / 0.720 /
# 0.807 / 0.883 / 0.941). Fair contact has to be squarer than it was, because
# the launch angle comes off a real collision now and a glancing one is a
# pop-up or a chopper: the foul threshold rose and AMATEUR's aim assist with
# it. See the note over `bat_contact.FOUL_QUALITY_THRESHOLD`.
QUALITY_QUANTILES = (
    (0.10, 0.757), (0.25, 0.798), (0.50, 0.850), (0.75, 0.928), (0.90, 0.967),
)

# **And quality is not independent of what kind of batted ball it is**, which
# is the trap one level up from the one above. Drawing the two separately —
# which this harness did — gives a batter whose pop-ups are struck as well as
# its line drives and whose line drives are struck as weakly as its pop-ups.
# That is not a small distortion: quality feeds exit velocity feeds carry, so
# an independently-drawn pop-up flies like a line drive.
#
# The correlation is not a coincidence to be modelled around, it is the
# geometry. `vertical_offset_ft` is the undercut, and it decides *both* things
# at once: the launch angle (`bat_ball_collision`, so the shape) and most of
# the contact quality (`Contact.centre_score`, whose sigma is 1.38 in). A ball
# you got right under is a pop-up *and* weakly struck, for one reason.
#
# Measured over the same 20,353 contacts. Note the spread: a line drive's
# median quality is 0.900 against a pop-up's 0.771, with grounders and fly
# balls level between them at about 0.85.
QUALITY_BY_SHAPE = {
    "GROUNDER": ((0.10, 0.759), (0.25, 0.804), (0.50, 0.849), (0.75, 0.938),
                 (0.90, 0.975)),
    "LINER":    ((0.10, 0.790), (0.25, 0.830), (0.50, 0.900), (0.75, 0.955),
                 (0.90, 0.978)),
    "FLY":      ((0.10, 0.752), (0.25, 0.787), (0.50, 0.844), (0.75, 0.895),
                 (0.90, 0.930)),
    "POP_UP":   ((0.10, 0.720), (0.25, 0.741), (0.50, 0.771), (0.75, 0.804),
                 (0.90, 0.831)),
}

# **The launch angle, which is the quantity the shape is only a band of.**
# `ball_flight` flies the angle now rather than the band's centre, so a harness
# that supplies only a shape is asking the animation to fall back to 14, 32 or
# 68 degrees — which is exactly the quantisation that change removed. Sampling
# the angle and *deriving* the shape from it keeps the harness on the same
# model the game runs.
#
# The angle is `Contact.launch_deg`, the vertical reading of the exit
# direction the collision gives. There is no jitter in it or on top of it.
# Banding these reproduces `BATTED_BALL_MIX` below to within a point, which is
# the check that the two describe one batter.
#
# They are within two or three degrees of what the fitted model gave (-20.7 /
# -13.5 / -0.7 / 15.6 / 32.0 / 45.9 / 53.1), and that is the calibration and
# not a coincidence: the collision's own response is nearly twice as steep,
# and the squarer fair contact is what brings the spread back.
LAUNCH_ANGLE_QUANTILES = (
    (0.05, -23.8), (0.10, -15.4), (0.25, -1.6), (0.50, 15.0), (0.75, 30.6),
    (0.90, 43.5), (0.95, 50.9),
)

# **And spray is not uniform either** — the same trap one axis over, and it
# bites harder: a `HitAnimation` built without a `spray_deg` sends the ball to
# *exactly* dead centre, so a sweep that forgets it puts every grounder over
# second base, the one place middle infielders cannot reach, and reports an
# infield-hit rate of 17% against a real 6-8%. Before `spray` the animation
# drew its own angle, so callers got a spread for free; now the swing supplies
# it and the harness has to. Pull-positive.
#
# The fair mean sits well under where an on-time middle pitch goes (+6°),
# because the pull side is the one the foul line cuts into: an inside strike
# struck on time is already within a few degrees of the line, so the fair
# population is dragged back toward centre.
SPRAY_MEAN_DEG, SPRAY_SD_DEG = 1.81, 21.5

# What this game's bat actually produces, measured through the real seam over
# the same 20,353 fair balls in play as the quantiles above.
#
# **It used to be measured off 170 recorded rows, and those rows were from a
# superseded model.** They read 0.459 / 0.276 / 0.235 / 0.029, which is much
# closer to the weighted-random-prior model the launch-angle geometry
# replaced (recorded at 45.2 / 31.6 / 22.2 / 1.0) than to the geometry then in
# the game — the pop-up share alone was out by 2.4x. That is
# the hazard CLAUDE.md names about `strikefactor.db` holding rows from several
# contact-geometry vintages at once: a measurement taken from it is a
# measurement of whichever bat was in the game when those rows were written.
#
# Against MLB's ~42/24/27/7 this is close on every band.
BATTED_BALL_MIX = (
    ("GROUNDER", 0.423),
    ("LINER", 0.244),
    ("FLY", 0.277),
    ("POP_UP", 0.056),
)


def _from_quantiles(pts, u, floor=0.0, ceiling=1.0):
    """Piecewise-linear inverse CDF over `(probability, value)` anchors.

    Linear from `floor` up to the first anchor and on to `ceiling` past the
    last, so the tails are bounded rather than extrapolated.
    """
    if u <= pts[0][0]:
        return floor + (pts[0][1] - floor) * u / pts[0][0]
    for (p0, v0), (p1, v1) in zip(pts, pts[1:]):
        if u <= p1:
            return v0 + (v1 - v0) * (u - p0) / (p1 - p0)
    last_p, last_v = pts[-1]
    return last_v + (ceiling - last_v) * (u - last_p) / (1.0 - last_p)


def realistic_quality(rng, shape=None):
    """Draw a contact quality from the distribution players produce.

    `shape` conditions the draw, and passing one is almost always what a
    caller wants: quality and batted-ball type are two readings of the same
    undercut, so drawing them independently builds a batter whose pop-ups are
    struck as hard as its line drives. See `QUALITY_BY_SHAPE`.

    Without one this is the marginal, which is what every caller that predates
    the conditional meant.
    """
    pts = QUALITY_BY_SHAPE.get(shape, QUALITY_QUANTILES)
    return _from_quantiles(pts, rng.random())


def realistic_launch_angle(rng):
    """Draw a launch angle, in degrees above horizontal.

    The quantity, rather than the band it falls in — `ball_flight` flies this
    now. The anchors are the angles the collision produces, and nothing is
    added to them.
    """
    return _from_quantiles(LAUNCH_ANGLE_QUANTILES, rng.random(),
                           floor=-45.0, ceiling=80.0)


def realistic_contact(rng):
    """One batted ball's `(quality, launch_deg, shape)`, drawn jointly.

    **The joint draw is the point.** The three used to come from three
    independent calls, and two of them are not independent — the launch angle
    and the contact quality are both consequences of the same undercut. So the
    angle is drawn first, the shape is *derived* from it (never drawn
    separately, or the two disagree), and the quality is drawn conditional on
    that shape.

    Spray is drawn separately, by `realistic_spray`. It is independent of the
    launch angle (r = 0.05 through the real seam) and nearly so of quality
    (r = 0.24: a late swing pushes the ball and costs a little quality at
    once), and the sampler leaves that last part out.
    """
    launch = realistic_launch_angle(rng)
    shape = ball_flight.shape_for_launch_angle(launch)
    return realistic_quality(rng, shape), launch, shape


def realistic_spray(rng):
    """Draw a spray angle from the distribution players produce."""
    while True:
        deg = rng.gauss(SPRAY_MEAN_DEG, SPRAY_SD_DEG)
        if abs(deg) <= 45.0:
            return deg


def realistic_batted_ball(rng):
    """Draw a batted-ball type from the mix this game's bat produces.

    The marginal. Prefer `realistic_contact`, which draws the launch angle and
    derives this from it, so the shape and the quality cannot come apart.
    """
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


def ball_in_play(seed, quality, shape, spray_deg, profile, handedness="R",
                 launch_deg=None):
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
                        spray_deg=spray_deg, defense=profile,
                        launch_deg=launch_deg)
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

# How many redraws `_launch_in_band` will take before giving up and returning
# the band's centre. The rarest band (POP_UP) is 7% of draws, so 200 attempts
# fail about once in 10^6 sweeps.
_LAUNCH_BAND_TRIES = 200


def _launch_in_band(rng, shape):
    """A launch angle from the real distribution, restricted to one band.

    Rejection rather than a clamp, for the reason this codebase keeps
    rediscovering: a clamp stacks every out-of-band draw onto the band's two
    edges, and the edges are exactly where the flight model is most sensitive.
    """
    for _ in range(_LAUNCH_BAND_TRIES):
        angle = realistic_launch_angle(rng)
        if ball_flight.shape_for_launch_angle(angle) == shape:
            return angle
    return ball_flight.launch_angle_for_shape(shape)


def sweep(profile, n, seed=4242, shape=None, handedness="R"):
    """`n` balls in play against one defense, memoized and prefix-served."""
    key = (profile, seed, shape, handedness)
    plays, rng = _PLAY_CACHE.get(key) or ([], random.Random(seed))
    for i in range(len(plays), n):
        q, launch, drawn_shape = realistic_contact(rng)
        if shape is not None:
            # A forced shape still needs an angle *inside that band*, or the
            # animation falls back to the band's centre and the sweep stops
            # exercising the continuous flight model. Redrawn until it lands
            # there rather than clamped, so the within-band distribution is the
            # real one.
            drawn_shape, launch = shape, _launch_in_band(rng, shape)
            q = realistic_quality(rng, shape)
        deg = realistic_spray(rng)
        plays.append(ball_in_play(i, q, drawn_shape, deg, profile, handedness,
                                  launch_deg=launch))
    _PLAY_CACHE[key] = (plays, rng)
    return plays[:n]
