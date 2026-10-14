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

The logistic estimates a play's difficulty and supports scoring chances
that never became throws (a ball through a fielder). A live first-base race
uses scheduled possession and bag-contact times, including coverage and
misplays, and a deterministic verdict. Randomness belongs in those physical
inputs; a final coin flip must never contradict the runner on screen.
"""

import math
import random
from dataclasses import dataclass, replace

from strikefactor.gameplay.base_geometry import BASE_FT

MPH_TO_FTS = 5280.0 / 3600.0            # 1.46667

# Bases in real feet, home at the origin, +y toward centre field. Matches
# hit_animation's _BASE_AXIS_FT = 90/sqrt(2) exactly — same diamond, so
# fielder positions can be handed straight across after unprojection.
FIRST_BASE_FT = BASE_FT[1]


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

# The plays that don't go cleanly. Not errors — a short hop that eats the
# fielder up, an in-between hop they have to wait on, a backhand they have
# to plant out of, a ball stuck in the webbing, a throw that pulls the
# first baseman off the bag. This is where infield hits actually come from,
# and none of it is visible to a model that only knows the geometry.
#
# Deliberately *not* named for a bobble: it is standing in for every source
# of play-to-play difficulty the geometry cannot see, which is why 22% is
# not as high as it first reads. Roughly a fifth of ground balls being
# something other than a clean set-and-throw is unremarkable.
#
# It exists because without it the margin distribution had no left tail at
# all: p25 sat at +0.82 s, so the *hardest quarter* of plays were still
# comfortable outs and the infield-hit rate came out at 2-3% against an
# MLB 6-8%. Every component matched the §3 reference table play for play —
# ball travel 1.42 s against 1.50, release 0.84 against 0.75, throw
# distance right for every position — and the rate was still less than half
# of MLB's, because the spread was far too narrow.
#
# The alternative was to raise *mean* release time until the rate came out,
# which needed 1.08 s: outside even the "poor catcher exchange" end of the
# sourced range, and wrong in kind, because it makes routine plays close
# rather than adding hard ones. Variance, not bias, was what was missing —
# these leave the median play untouched (p50 margin 1.12 s -> 1.03 s) and
# put the tail where the runner can reach it (p10 0.44 s -> 0.14 s).
# Lowered from 0.22 when `defense.py`'s misplay model arrived. Both terms
# feed the same left tail, so they double-counted: with misplays added on top,
# the infield-hit rate on fielded grounders ran past its 6-8% band. This is
# the better trade rather than merely the necessary one — a flat rate is what
# §8 of docs/infield-timing-refactor.md criticises about this constant ("the
# real fix is a fielding-difficulty model rather than one flat probability"),
# and the misplay term is that model: it reads how far the fielder ranged and
# how hard the ball was hit. Handing it a share of the tail replaces a
# hand-fit constant with a modelled one.
HARD_PLAY_PROB = 0.18
HARD_PLAY_COST_S = (0.25, 1.40)         # uniform: a hitch at one end, a fumble at the other


# ---- Throw ----------------------------------------------------------------
# Do NOT use Statcast "arm strength" here: it is the average of a player's
# top 5% of throws, so those 85-95 mph figures are max effort, not what a
# routine 6-3 looks like. What matters is the *effective average speed*
# over the throw, which accounts for drag (a ball sheds ~8-10% of its
# velocity per 55 ft) and for most throws not being max effort. A 90 mph
# release across 130 ft arrives near 72 and averages about 80.
THROW_EFFECTIVE_FTS = 110.0             # routine throw across the diamond
THROW_EFFECTIVE_FTS_RANGE = (100.0, 118.0)
# A first baseman feeding the pitcher on a 3-1 does not make a max-effort
# infield throw over 15-35 ft.  It is normally an underhand flip or an easy
# overhand toss, with an effective flight speed of about 37.5 mph.  Keeping
# this separate from THROW_EFFECTIVE_FTS matters most at short range: using
# the across-the-diamond figure turns a 20 ft feed into a 0.18 s bullet.
FIRST_BASE_SOFT_TOSS_FTS = 55.0
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
    # The sampled bobble cost and estimated clean-play difficulty. Coverage
    # can absorb some of that cost; clean_defense_s records the rescheduled
    # alternative used by timed_verdict for live error scoring.
    p_out_clean: float
    misplay_s: float = 0.0
    clean_defense_s: float | None = None

    @property
    def is_bang_bang(self):
        return abs(self.margin_s) < BANG_BANG_S


def schedule_first_base(timing, runner_s, *, cover_at_s=0.0,
                        throw_flight_s=None, carry_s=None):
    """Finalize the race before drawing it, including the clean alternative.

    A receiver must be on the bag when the throw arrives. Waiting for them
    delays release, not ball speed. The same wait may absorb part or all of
    a bobble, so the clean play is rescheduled rather than simply subtracting
    the bobble from the defensive total. An unassisted carry needs no throw
    transfer; only the misplay delays the defender's approach to the base.
    """
    if carry_s is not None:
        release_s = timing.misplay_s
        clean_release_s = 0.0
        flight_s = carry_s
    else:
        flight_s = timing.throw_flight_s if throw_flight_s is None else throw_flight_s
        wait_s = max(0.0, cover_at_s - timing.ball_to_glove_s - flight_s)
        release_s = max(timing.release_s, wait_s)
        clean_release_s = max(timing.release_s - timing.misplay_s, wait_s)
    defense_s = max(cover_at_s, timing.ball_to_glove_s + release_s + flight_s)
    clean_s = max(cover_at_s, timing.ball_to_glove_s + clean_release_s + flight_s)
    margin_s = runner_s - defense_s
    return replace(timing, release_s=release_s, throw_flight_s=flight_s,
                   defense_s=defense_s, clean_defense_s=clean_s,
                   runner_s=runner_s, margin_s=margin_s,
                   p_out=p_out_from_margin(margin_s),
                   p_out_clean=p_out_from_margin(runner_s - clean_s))


def timed_verdict(timing):
    """The runner is out only if possession at the bag occurred first.

    Exact simultaneous arrival is safe. The clean and actual alternatives
    share every input except the misplay, with no additional random draw.
    """
    if timing.defense_s < timing.runner_s:
        return "OUT"
    if (timing.misplay_s > 0 and timing.clean_defense_s is not None
            and timing.clean_defense_s < timing.runner_s):
        return "ERROR"
    return "HIT"


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


def ground_speed_retention(ev_mph):
    """Fraction of exit velocity a ground ball holds *on average* over its
    path, from GROUND_SPEED_RETENTION.

    Public because `ground_roll` derives a grounder's end-of-path speed
    from the same curve — the ball that reaches the outfield grass has to
    be the ball the infield verdict was computed against.
    """
    return _interpolate(max(0.0, ev_mph or 0.0), GROUND_SPEED_RETENTION)


def ball_travel_time_s(ev_mph, distance_ft):
    """Seconds from contact until the ball reaches a fielder `distance_ft` away.

    The single biggest driver of whether an infield play is close. A
    scorched grounder gets to the fielder so early that the throw is
    routine; a topped roller eats most of the runner's clock before anyone
    touches it.
    """
    return max(0.0, distance_ft) / ground_speed_fts(ev_mph)


def ground_speed_fts(ev_mph):
    """How fast the ball is actually moving along the ground, in ft/s.

    Public because it is not only the infield race that needs it: a ball
    that goes *through* a fielder has to leave at the pace it really had,
    and that has to be the same number the verdict was computed against.
    """
    ev = max(0.0, ev_mph or 0.0)
    return max(MIN_GROUND_SPEED_FTS,
               ev * MPH_TO_FTS * ground_speed_retention(ev))


def stretch_fraction(ranging_ft):
    """How far off their set position the fielder had to go, in [0, 1].

    One definition, because two things interpolate on it: the release
    penalty below and `defense.misplay_prob`. See `RELEASE_STRETCH_FT`.
    """
    return min(1.0, max(0.0, ranging_ft or 0.0) / RELEASE_STRETCH_FT)


def defense_arm_fts(defense, override=None):
    """The speed the ball leaves this fielder's hand at, in ft/s.

    `override` is for the play with no throw in it: an unassisted first
    baseman carries the ball to the bag on their own legs, so the caller
    substitutes a sprint speed. Everything else takes the profile's arm.
    """
    if override is not None:
        return override
    return THROW_EFFECTIVE_FTS if defense is None else defense.throw_fts


def defense_release_scale(defense):
    """How quick this defense's hands are; 1.0 for the neutral defense."""
    return 1.0 if defense is None else defense.release_scale


def release_time_s(ranging_ft=0.0, is_charging=False, rng=None,
                   release_scale=1.0, misplay_s=0.0):
    """Glove contact to release.

    `ranging_ft` is how far the fielder had to move off their set position
    — the further they went, the less balanced the throw. `is_charging`
    marks the barehand play in on a slow roller, which is *faster* than
    routine, not slower: the fielder is already moving toward first.

    `release_scale` is how quick this defense's hands are (see
    `gameplay/defense.py`). Multiplicative rather than additive because the
    sourcing is a percentage band — catcher exchange 0.85 / 0.73 / 0.64 is
    ±16% about the mean — and because an additive offset would drag
    RELEASE_CHARGE_S below any observed exchange, making the barehand play
    on a slow roller nearly free. The slow roller is the canonical infield
    hit; it must not become the canonical easy out.

    `misplay_s` is a bobble the caller already rolled, in seconds. It is
    added here rather than anywhere else for two reasons: glove contact to
    release *is* what a bobble delays, and `defense_s` has to stay equal to
    ball + release + throw. It is deliberately *not* scaled — defense
    strength decides how often a ball is misplayed, not how badly.

    HARD_PLAY_COST_S is not scaled either: it models the play, not the
    fielder, and scaling it would move HARD_PLAY_PROB's calibration behind
    its back.
    """
    if is_charging:
        base = RELEASE_CHARGE_S
    else:
        stretch = stretch_fraction(ranging_ft)
        base = RELEASE_ROUTINE_S + (RELEASE_STRETCHED_S - RELEASE_ROUTINE_S) * stretch
    base *= release_scale
    if rng is not None:
        if RELEASE_JITTER_S:
            base += rng.gauss(0.0, RELEASE_JITTER_S * release_scale)
        # The left tail of the margin distribution — see HARD_PLAY_PROB.
        if rng.random() < HARD_PLAY_PROB:
            base += rng.uniform(*HARD_PLAY_COST_S)
    return max(0.35, base) + max(0.0, misplay_s)


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
                         effective_throw_fts=None,
                         ball_to_glove_s=None,
                         defense=None,
                         misplay_s=0.0,
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

    `defense` is a `gameplay.defense.DefenseProfile`, passed as the value it
    is rather than destructured into a keyword per attribute. It used to
    arrive as `effective_throw_fts` and `release_scale` separately, so every
    new attribute of a defense meant widening this signature and every call
    site again. It is read by duck-typing rather than imported, deliberately:
    `defense` imports *this* module for `RELEASE_STRETCH_FT`, and the edge
    must not close into a cycle. `None` means the neutral defense, the same
    thing it means to `HitAnimation`.
    """
    ball_s = (ball_to_glove_s if ball_to_glove_s is not None
              else ball_travel_time_s(ev_mph, ball_distance_ft))
    rel_s = release_time_s(ranging_ft, is_charging, rng,
                           defense_release_scale(defense), misplay_s)
    throw_s = throw_time_s(fielder_xy_ft, defense_arm_fts(defense, effective_throw_fts))
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
        misplay_s=max(0.0, misplay_s),
        # What this play would have been without the bobble. The error
        # window in `roll_verdict` is exactly the gap between the two.
        p_out_clean=p_out_from_margin(margin_s + max(0.0, misplay_s)),
    )


def roll_verdict(timing, rng=random):
    """Sample OUT / ERROR / HIT for analysis and legacy model callers.

    A shared draw evaluates the clean and misplayed chances together. This
    probability model does not guarantee agreement with visible arrivals;
    live first-base plays use schedule_first_base and timed_verdict instead.
    """
    return verdict_from(timing.p_out, timing.p_out_clean, rng)


def verdict_from(p_out, p_out_clean, rng=random):
    """The scorer's rule as a function of the two clocks, not of a `PlayTiming`.

    Stated this way because a play can reach it without a race having run.
    A ball that goes *through* a fielder is the `p_out = 0` case: nobody
    threw, so the batter reached, and the only question left is whether the
    clean play would have been an out — which is exactly the window
    `[0, p_out_clean)`. `hit_animation._trigger_through` used to write that
    out as its own second draw, which is the two-models-of-one-thing fault
    this function exists to prevent, 400 lines from the rule it copied.
    """
    u = rng.random()
    if u < p_out:
        return "OUT"
    if u < p_out_clean:
        return "ERROR"
    return "HIT"
