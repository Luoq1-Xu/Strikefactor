"""Does the batter-runner take the extra base? Same race, one base over.

`infield_timing` asks whether a throw to first beats the runner. This asks
the same question about second and third, and it is the larger of the two
distortions in recorded play: doubles ran at 0.96 per single against an
MLB 0.32, and triples at 7-8% of hits against ~1%.

The reason was the same as the infield's. Bases were decided by
`RETRIEVE_TIME_SINGLE_MAX_MS = 2800` / `..._DOUBLE_MAX_MS = 4200` — how
many *animated* milliseconds the fielder took to pick the ball up, with no
runner in the race at all. So the classification could not see how far
from a base the ball was retrieved, only how long it took, and a bloop
that took a while to run down scored the same as a ball off the wall. It
was also measured on the animation clock, which made those two thresholds
silently dependent on presentation pacing: unifying the clock moved every
flight time and took triples from 8% of hits to 23% without anyone
touching the constants.

Real feet and real seconds, no pygame, no game state — same contract as
`infield_timing` and `contact_audio`. Shared primitives (throw speed, the
runner's clock, the logistic) are imported rather than re-derived, so the
two races cannot drift apart.

The decision rule is the one a third-base coach uses, and it is not "am I
faster than the ball": it is "am I *safely* faster". A runner who arrives
a tenth ahead of the throw has run into a tag more often than not, so
`AGGRESSION_MARGIN_S` is subtracted before the verdict. Without it,
runners take every base they can theoretically reach and every gapper is
a triple — which is precisely the shape the retrieve-time thresholds
produced.
"""

import math

from strikefactor.gameplay import infield_timing
from strikefactor.gameplay.infield_timing import (
    SIGMA_S,
    THROW_EFFECTIVE_FTS,
    home_to_first_s,
    p_out_from_margin,
)

# Bases in real feet, home at the origin, +y toward centre field.
BASE_FT = {
    1: (63.64, 63.64),
    2: (0.0, 127.28),
    3: (-63.64, 63.64),
}

# Leg time for a base the runner reaches with a running start, in seconds.
# Home-to-first is a standing start with a bat to drop and a swing to
# recover from; every base after it is run at speed, which is why they are
# roughly 0.85 s quicker. MLB home-to-second on a double is ~7.8 s against
# a 4.3 s home-to-first, and home-to-third on a triple ~11.2 s — so the
# second and third legs are ~3.5 s and ~3.4 s.
#
# Expressed against sprint speed rather than as a constant so a fast
# runner's advantage compounds over a long advance, which is the whole
# reason triples belong to fast runners.
RUNNING_START_EFFICIENCY = 0.96         # fraction of top speed held over a 90 ft leg
BASE_PATH_FT = 90.0

# Outfielder glove-to-release. Slower than an infielder's `RELEASE_ROUTINE_S`
# because an outfielder throwing to a base crow-hops into it rather than
# planting and flipping — and because they are throwing for distance, not
# for speed of exchange.
OF_RELEASE_S = 1.05
IF_RELEASE_S = 0.80                     # a ball retrieved by an infielder

# Beyond this, the throw goes through a cutoff man rather than on the fly.
# The relay is *not* slower per foot — a two-leg throw is thrown harder
# than a 250 ft heave — but the exchange costs a fixed beat, which is what
# gives the runner the chance a straight throw would not.
RELAY_DISTANCE_FT = 180.0
RELAY_EXCHANGE_S = 0.75

# How much daylight a runner needs before committing to the next base.
# A runner who beats the throw by a tenth is out on the tag more often
# than not, and coaches send accordingly. This is what keeps a routine
# gapper a double instead of a triple.
AGGRESSION_MARGIN_S = 0.55

# Reaching a base is not the same as being safe at it: the tag still has
# to be applied. Slightly wider than the infield's sigma because a force
# at first is a foot on a bag and this is a fielder finding a sliding
# runner with a glove.
SIGMA_TAG_S = 0.16


def leg_time_s(sprint_fts):
    """Seconds to run one 90 ft base path with a running start."""
    return BASE_PATH_FT / max(1.0, sprint_fts * RUNNING_START_EFFICIENCY)


def home_to_base_s(base, handedness="R", sprint_fts=27.0, difficulty_offset_s=0.0):
    """Contact to the batter-runner touching `base` (1, 2 or 3)."""
    t = home_to_first_s(handedness, sprint_fts, difficulty_offset_s)
    return t + max(0, base - 1) * leg_time_s(sprint_fts)


def throw_to_base_s(ball_xy_ft, base, effective_fts=THROW_EFFECTIVE_FTS):
    """Flight time of a throw from where the ball was retrieved to `base`,
    including the cutoff exchange when the throw is too long to make on
    the fly.
    """
    bx, by = BASE_FT[base]
    distance_ft = math.hypot(bx - ball_xy_ft[0], by - ball_xy_ft[1])
    flight = distance_ft / max(1.0, effective_fts)
    if distance_ft > RELAY_DISTANCE_FT:
        flight += RELAY_EXCHANGE_S
    return flight


def defense_to_base_s(base, ball_xy_ft, retrieved_at_s, is_outfielder=True,
                      defense=None):
    """Contact until the ball is in a fielder's glove *at* `base`.

    `defense` is a `gameplay.defense.DefenseProfile` (or None for neutral).
    Its arm and its hands are applied to the same release family the infield
    uses, so an arm cannot be quick to first and slow to second.
    """
    release = ((OF_RELEASE_S if is_outfielder else IF_RELEASE_S)
               * infield_timing.defense_release_scale(defense))
    return retrieved_at_s + release + throw_to_base_s(
        ball_xy_ft, base, infield_timing.defense_arm_fts(defense))


def final_base(ball_xy_ft, retrieved_at_s, is_outfielder=True,
               handedness="R", sprint_fts=27.0, difficulty_offset_s=0.0,
               min_base=1, rng=None, defense=None):
    """How far the batter-runner gets. Returns (base, margin_s).

    The runner advances one base at a time, and stops at the first base
    they cannot reach with `AGGRESSION_MARGIN_S` to spare. `margin_s` is
    for the last base they *attempted* — positive means they beat the
    throw there — so it is the number worth recording as the play's
    margin.

    `min_base` is the floor a ball that reached the wall gets: it is past
    every outfielder by definition, so it cannot be a single no matter how
    the carom comes back.
    """
    base = max(1, min_base)
    margin = None
    while base < 3:
        nxt = base + 1
        runner_s = home_to_base_s(nxt, handedness, sprint_fts,
                                  difficulty_offset_s)
        defense_s = defense_to_base_s(nxt, ball_xy_ft, retrieved_at_s,
                                      is_outfielder, defense)
        m = defense_s - runner_s - AGGRESSION_MARGIN_S
        if m <= 0:
            # Not enough daylight — hold. The margin at the base they
            # stopped at is what the play was decided by.
            if margin is None:
                margin = m
            break
        margin = m
        base = nxt
        if rng is not None and rng.random() > p_out_from_margin(m, SIGMA_TAG_S):
            # Sent anyway and thrown out — the runner reached the base but
            # the tag beat them. Still counts as reaching it for the hit's
            # classification; the out is not modelled here (see the module
            # note on double plays in infield_timing).
            break
    return base, (margin if margin is not None else 0.0)


__all__ = [
    "AGGRESSION_MARGIN_S",
    "BASE_FT",
    "SIGMA_S",
    "defense_to_base_s",
    "final_base",
    "home_to_base_s",
    "leg_time_s",
    "throw_to_base_s",
]
