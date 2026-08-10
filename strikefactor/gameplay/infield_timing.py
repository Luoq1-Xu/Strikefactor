"""Real-time model of an infield play: does the throw beat the runner?

Two clocks, both starting at bat-on-ball contact:

    defense = ball travel to the fielder + fielder release + throw flight
    offense = the batter's home-to-first time

This is the framing Statcast's infield Outs Above Average model uses, and
Tango's original writeup walks a real play through exactly these four
components. See docs/infield-timing-refactor.md for sourcing on every
constant below.

Everything here is in **real seconds and real feet**. Nothing in this
module knows about pixels, the animation clock, pygame, or game state —
same contract as engine/contact_audio.py, and for the same reason: the
numbers are calibrated against the real world, so they have to be
testable without a renderer in the way.

The verdict is a *probability*, not a boolean. A hard `margin > 0` makes
every play deterministic and brittle exactly at the boundary that matters
most; the logistic absorbs throw accuracy, the first baseman's scoop,
umpire error and the batter's own variance. It is also what makes a
bang-bang play feel like one — at SIGMA_S a play that is "out by a tenth"
comes out around 70% an out, not a certainty.
"""

import math
import random
from dataclasses import dataclass

MPH_TO_FTS = 5280.0 / 3600.0            # 1.46667

# Bases in real feet, home at the origin, +y toward centre field. Matches
# hit_animation's _BASE_AXIS_FT = 90/sqrt(2) exactly — same diamond, so
# fielder positions can be handed straight across after unprojection.
FIRST_BASE_FT = (63.64, 63.64)


# ---- Runner ---------------------------------------------------------------
# Home-to-first, contact to touching the bag.
#
# Use the max-effort scouting figure (4.3 RHB / 4.2 LHB), NOT Statcast's
# 4.62 league average: that average includes jogs on obvious outs, and a
# batter in this game is always running out a play close enough for the
# timing to matter.
#
# Sprint Speed is a trap and must not be used as an average. It is a
# *top-speed* metric measured over the fastest one-second window, so
# 90 ft / 27 ft/s = 3.33 s, against a real 4.30 s — a runner averages
# roughly 77% of top speed over the distance. Rather than model
# acceleration explicitly, the two endpoints are fitted: 27 ft/s -> 4.30 s
# and each additional ft/s of top speed is worth 0.143 s.
SPRINT_SPEED_LEAGUE_FTS = 27.0          # MLB average; elite 29-30, slow 23-25
HOME_TO_FIRST_LEAGUE_S = 4.30           # RHB, max effort
HOME_TO_FIRST_S_PER_FTS = 0.143
LHB_HOME_TO_FIRST_BONUS_S = 0.10        # starts ~3 ft closer, already moving
HOME_TO_FIRST_MIN_S = 3.55              # Buxton's 3.72 is the real record
HOME_TO_FIRST_MAX_S = 5.00


# ---- Ball to the fielder --------------------------------------------------
# A grounder bleeds a lot of speed to its first bounce and then to
# friction, so the average speed over its path is well under exit
# velocity. Hard-hit balls skip and hold their speed; weakly-topped ones
# die almost immediately, which is precisely why the slow roller is the
# canonical infield hit and why this curve is not a constant fraction.
#
# Calibrated so that: 95 mph over 140 ft -> ~1.4 s (target 1.3-1.5), and a
# 45 mph chopper over 110 ft -> ~3.2 s (target 2.5-3.5).
GROUND_SPEED_RETENTION = (
    (35.0, 0.48),
    (45.0, 0.52),
    (60.0, 0.57),
    (70.0, 0.60),
    (80.0, 0.645),
    (90.0, 0.68),
    (100.0, 0.72),
    (115.0, 0.75),
)
MIN_GROUND_SPEED_FTS = 8.0              # a ball trickling to a stop


# ---- Fielder release ------------------------------------------------------
# Glove contact to the ball leaving the hand. This is the weakest-sourced
# input in the whole chain: there is no public infielder release
# leaderboard, so 0.75 s is Tango's figure and the spread is borrowed from
# catcher exchange time (MLB avg 0.73, elite 0.64, poor 0.85), which is a
# footwork-included transfer and maps reasonably onto an infielder
# planting and throwing.
#
# Because it is the least-certain number it is also the designated
# calibration dial: tune release time to hit the infield-hit rate target,
# rather than distorting the better-measured runner or throw figures.
#
# These sit ~0.05 s above the point estimates (0.75 / 0.55 / 0.95) because
# that is what puts the infield-hit rate on fielded grounders at 7.2%,
# inside the 6-8% MLB band; at the point estimates it came out at 5.5%.
# 0.80 s is still comfortably inside the observed exchange spread, and
# spending the correction here rather than on the runner or the throw is
# deliberate — it is the input whose uncertainty is real, so absorbing the
# calibration error into it does not distort a better-measured number.
RELEASE_ROUTINE_S = 0.80                # set, on balance
RELEASE_CHARGE_S = 0.60                 # barehand / charging a slow roller
RELEASE_STRETCHED_S = 1.00              # backhand, from the hole, off balance
RELEASE_STRETCH_FT = 18.0               # ranging this far = fully stretched
RELEASE_JITTER_S = 0.05                 # footwork noise, play to play


# ---- Throw ----------------------------------------------------------------
# Do NOT use Statcast "arm strength" here: it is the average of a player's
# top 5% of throws, so those 85-95 mph figures are max effort, not what a
# routine 6-3 looks like. What matters is the *effective average speed*
# over the throw, which accounts for drag (a ball sheds ~8-10% of its
# velocity per 55 ft) and for most throws not being max effort. A 90 mph
# release across 130 ft arrives near 72 and averages about 80.
THROW_EFFECTIVE_FTS = 110.0             # routine throw across the diamond
THROW_EFFECTIVE_FTS_RANGE = (100.0, 118.0)
UNASSISTED_MAX_FT = 12.0                # close enough to step on the bag


# ---- Verdict --------------------------------------------------------------
# Width of the logistic on the margin, in seconds. Absorbs throw accuracy,
# the scoop at first, umpire error, and the batter's own variance. At 0.12
# a play that is out by 0.1 s resolves ~80% out; by 0.3 s, ~92%.
SIGMA_S = 0.12
BANG_BANG_S = 0.15                      # |margin| under this reads as close


@dataclass(frozen=True)
class PlayTiming:
    """Both clocks and the verdict, with the components kept visible.

    Deliberately a timing rather than a boolean: double plays, tag plays
    and force outs all need the parts, not the answer.
    """

    ball_to_glove_s: float
    release_s: float
    throw_flight_s: float
    defense_s: float
    runner_s: float
    margin_s: float                     # runner_s - defense_s; > 0 favours defense
    p_out: float

    @property
    def is_bang_bang(self):
        return abs(self.margin_s) < BANG_BANG_S


def _interpolate(x, table):
    """Piecewise-linear lookup on an ascending (x, y) table."""
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            span = x1 - x0
            if span <= 0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / span
    return table[-1][1]


def ball_travel_time_s(ev_mph, distance_ft):
    """Seconds from contact until the ball reaches a fielder `distance_ft` away.

    The single biggest driver of whether an infield play is close. A
    scorched grounder gets to the fielder so early that the throw is
    routine; a topped roller eats most of the runner's clock before anyone
    touches it.
    """
    ev = max(0.0, ev_mph or 0.0)
    speed_fts = max(MIN_GROUND_SPEED_FTS,
                    ev * MPH_TO_FTS * _interpolate(ev, GROUND_SPEED_RETENTION))
    return max(0.0, distance_ft) / speed_fts


def release_time_s(ranging_ft=0.0, is_charging=False, rng=None):
    """Glove contact to release.

    `ranging_ft` is how far the fielder had to move off their set position
    — the further they went, the less balanced the throw. `is_charging`
    marks the barehand play in on a slow roller, which is *faster* than
    routine, not slower: the fielder is already moving toward first.
    """
    if is_charging:
        base = RELEASE_CHARGE_S
    else:
        stretch = min(1.0, max(0.0, ranging_ft) / RELEASE_STRETCH_FT)
        base = RELEASE_ROUTINE_S + (RELEASE_STRETCHED_S - RELEASE_ROUTINE_S) * stretch
    if rng is not None and RELEASE_JITTER_S:
        base += rng.gauss(0.0, RELEASE_JITTER_S)
    return max(0.35, base)


def throw_time_s(fielder_xy_ft, effective_fts=THROW_EFFECTIVE_FTS):
    """Flight time of the throw to first base, in seconds.

    Returns 0 for a fielder already on top of the bag — that is a step,
    not a throw.
    """
    dx = FIRST_BASE_FT[0] - fielder_xy_ft[0]
    dy = FIRST_BASE_FT[1] - fielder_xy_ft[1]
    distance_ft = math.hypot(dx, dy)
    if distance_ft <= UNASSISTED_MAX_FT:
        return 0.0
    return distance_ft / max(1.0, effective_fts)


def home_to_first_s(handedness="R", sprint_fts=SPRINT_SPEED_LEAGUE_FTS,
                    difficulty_offset_s=0.0):
    """Contact to the batter-runner touching first base.

    `difficulty_offset_s` is how difficulty enters the model — as time,
    not as a probability multiplier on the verdict. Negative gives the
    batter a head start (easier).
    """
    t = HOME_TO_FIRST_LEAGUE_S - HOME_TO_FIRST_S_PER_FTS * (
        (sprint_fts or SPRINT_SPEED_LEAGUE_FTS) - SPRINT_SPEED_LEAGUE_FTS)
    if handedness == "L":
        t -= LHB_HOME_TO_FIRST_BONUS_S
    t += difficulty_offset_s
    return max(HOME_TO_FIRST_MIN_S, min(HOME_TO_FIRST_MAX_S, t))


def p_out_from_margin(margin_s, sigma_s=SIGMA_S):
    """Logistic on the margin. Kept separate so it can be tested alone."""
    z = margin_s / max(1e-6, sigma_s)
    if z > 40:                                   # avoid math.exp overflow
        return 1.0
    if z < -40:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def resolve_infield_play(ev_mph, fielder_xy_ft, ball_distance_ft,
                         ranging_ft=0.0, is_charging=False,
                         handedness="R", sprint_fts=SPRINT_SPEED_LEAGUE_FTS,
                         difficulty_offset_s=0.0,
                         effective_throw_fts=THROW_EFFECTIVE_FTS,
                         ball_to_glove_s=None,
                         rng=None):
    """Run both clocks and return the timing.

    `ball_distance_ft` is how far the ball travelled to reach the fielder,
    which is not the same as the fielder's distance from home — a fielder
    who ranged to their left covers ground the ball did not.

    `ball_to_glove_s` overrides the modelled travel time for callers that
    *know* when the ball was actually gloved. The model assumes the fielder
    was there to meet the ball, which is true of a ball fielded on the fly
    and false of one chased down and picked up — for that play the clock
    starts when the fielder reaches it, which can be seconds later.
    """
    ball_s = (ball_to_glove_s if ball_to_glove_s is not None
              else ball_travel_time_s(ev_mph, ball_distance_ft))
    rel_s = release_time_s(ranging_ft, is_charging, rng)
    throw_s = throw_time_s(fielder_xy_ft, effective_throw_fts)
    defense_s = ball_s + rel_s + throw_s
    runner_s = home_to_first_s(handedness, sprint_fts, difficulty_offset_s)
    margin_s = runner_s - defense_s
    return PlayTiming(
        ball_to_glove_s=ball_s,
        release_s=rel_s,
        throw_flight_s=throw_s,
        defense_s=defense_s,
        runner_s=runner_s,
        margin_s=margin_s,
        p_out=p_out_from_margin(margin_s),
    )


def roll_is_out(timing, rng=random):
    """Sample the verdict. Separated from `resolve_infield_play` so the
    timing can be computed, logged and displayed without consuming
    randomness — and so a replay can re-derive the numbers."""
    return rng.random() < timing.p_out
