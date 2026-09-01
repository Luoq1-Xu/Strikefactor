"""How good the nine gloves behind the pitcher are, in real feet and seconds.

Difficulty in this game has always been about the bat — `aim_assist`,
`contact_zone_size`, `contact_timing_window`, `foul_threshold` — plus one
seconds-on-the-runner's-clock offset. The fielders were a fixed league-average
team: `FIELDER_SPRINT_FT_S = 27.0`, `REACTION_DELAY_MIN/MAX_S = 0.200/0.380`,
`RELEASE_ROUTINE_S = 0.80`, `THROW_EFFECTIVE_FTS = 110.0`. There was no way to
face a bad defense or a great one, and no such thing as an error: a ground ball
got a probabilistic verdict from `infield_timing`, but a fly ball reached was a
fly ball caught, with no roll anywhere.

This module is the settings->physics seam for that. It holds no state, imports
no pygame, and knows nothing about the animation — same contract as
`contact_audio`, `infield_timing`, `extra_bases` and `spray`, and for the same
reason: every number here has to be tuned by Monte Carlo, so it has to be
runnable without a renderer in the way. A `DefenseProfile` is a *value*, which
is what lets a calibration harness sweep four levels in a loop; a settings
manager is not.

**LEAGUE is defined to reproduce the existing constants exactly.** That is not
a convenience, it is what makes the integration phase verifiable: wiring the
profile through must move no rate at all, and any band that shifts means the
identity is wrong. Unlike the clock unification -- whose "rates must not move"
check was mistaken because the thing it replaced was only approximately right
-- here the neutral row *is* today's numbers, and a test pins it field by field.

Four levels, not five. Five invites a false parallel with the difficulty
ladder, and there is not enough real spread in fielding percentage to anchor
five rungs honestly.

See docs/defense-strength.md for sourcing on every number below.
"""

from dataclasses import dataclass
from enum import Enum

from strikefactor.gameplay.infield_timing import RELEASE_STRETCH_FT


class DefenseLevel(Enum):
    SANDLOT = "sandlot"
    MINORS = "minors"
    LEAGUE = "league"            # MLB average - the default, and the identity
    GOLD_GLOVE = "gold_glove"


@dataclass(frozen=True)
class DefenseProfile:
    """One defense, stated as physical quantities rather than multipliers.

    Everything here is a real number a scout could quote: a top speed in feet
    per second, a reaction in seconds, a throw in feet per second. Difficulty
    reaches the runner's clock as seconds rather than as a fudge on the
    verdict, and this follows the same discipline for the defense -- there is
    no "out probability" dial anywhere in this module.
    """

    label: str
    # --- legs ---
    sprint_fts: float          # top speed, before the per-fielder jitter
    reaction_min_s: float      # see-react to first stride
    reaction_max_s: float
    # --- arm ---
    throw_fts: float           # effective average over the throw, not release velocity
    release_scale: float       # multiplies the whole release family + its jitter
    # --- glove ---
    field_misplay_p: float     # base P(a ball handled off the ground is mishandled)
    catch_muff_p: float        # base P(a ball reached in the air is dropped)
    body_block: float          # of balls they fail to glove, the share they still
                               # keep in front of them; the rest go through
    muff_recovery_s: float     # ball on the grass -> back under control


# Sourcing, field by field:
#
# sprint_fts      Statcast Sprint Speed: slow 23-25, league mean 27, elite
#                 29-30. It is a *top* speed, which is the right thing here --
#                 a fielder's range is a sprint, not a home-to-first average.
#
# reaction_*      The existing REACTION_DELAY_MIN/MAX_S range, scaled about its
#                 centre. Elite is both faster *and narrower*: consistency is
#                 part of being good, and a wide draw at the top of the ladder
#                 would show up as a Gold Glove infielder occasionally
#                 statue-ing on a routine ball.
#
#                 Reaction matters more than speed here, which is easy to get
#                 backwards. Over a ~1.5 s grounder, the sprint band is worth
#                 about 4 ft of range end to end; the reaction band is worth
#                 about 5.7 ft on its own, and the two compound.
#
# throw_fts       infield_timing.THROW_EFFECTIVE_FTS_RANGE is (100, 118) and
#                 was already declared there and never used -- this ladder
#                 fills a hole the physics left open rather than inventing an
#                 axis. SANDLOT sits deliberately below the MLB floor.
#                 NB: this is *effective average speed over the throw*, not
#                 Statcast arm strength, which is the mean of a player's top
#                 5% of throws and would be badly wrong used here.
#
# release_scale   Catcher exchange time is the only published distribution
#                 shaped like an infielder's transfer: poor 0.85, average
#                 0.73, elite 0.64, i.e. x1.16 / x1.00 / x0.88 about the mean.
#                 Multiplicative rather than additive on purpose -- the
#                 sourcing is a percentage band, and an additive offset would
#                 drag RELEASE_CHARGE_S (0.60) below any observed exchange,
#                 making the barehand play on a slow roller nearly free. The
#                 slow roller is the canonical infield hit; it must not become
#                 the canonical easy out.
#
# field_misplay_p THE CALIBRATION DIAL, and now a measurement rather than a
#                 guess. Fielding percentage .984 means ~1.6% of chances
#                 become charged errors, but a charged error needs *both* a
#                 misplay and that the misplay cost the out:
#                     P(error) = field_misplay_p * mod * E[p_out_clean - p_out]
#
#                 Both of those were measured over the batter this game
#                 actually produces (quality from the recorded quantiles,
#                 spray from the recorded distribution), forcing every
#                 reached ball to be bobbled:
#                     E[p_out_clean - p_out] = 0.495   (median 0.522)
#                     mean modulation         = 3.18x
#
#                 The modulation is the part that is easy to miss and it is
#                 the larger of the two: the ranging and hop gains multiply
#                 the base by more than three on a *typical* play, because a
#                 fielder who came up with a ball has usually moved for it.
#                 The base is therefore not the rate — 0.045 here meant an
#                 11% effective misplay rate, which ran errors at 3.4% of
#                 balls in play against MLB's ~1.4% and took the ground-ball
#                 hit rate to 41%.
#
#                 0.015 / (0.495 * 3.18) = 0.0095. Re-derive it the same way
#                 whenever the gains or the contact distribution change, and
#                 tune this rather than the better-sourced numbers above.
#
# catch_muff_p    MLB outfielders convert well over 99% of balls they reach;
#                 outright drops are a few tenths of a percent of fly balls.
#
# body_block      Getting the body in front is what stops a ball you cannot
#                 glove cleanly, and it is the most coachable difference
#                 between a good infielder and a bad one -- a good one blocks
#                 it and keeps it on the dirt, a bad one waves at it. That is
#                 why this is a per-level field and not a constant.
#
#                 It has an independent calibration target, which makes it the
#                 best-anchored number in this table: docs/infield-timing-
#                 refactor.md measures ground-ball hit rate at 21.3% against a
#                 real ~24%, and its section 8 names the residual as "our
#                 fielders execute a clean route on every ball they can reach;
#                 MLB's do not". That 2.7-point gap was recorded before this
#                 feature existed, so LEAGUE's body_block is fitted to close
#                 it -- not to the error rate, which is field_misplay_p's job.
#
# muff_recovery_s The ball is at your feet, but you still have to find it,
#                 pick it and set. It is spent by extra_bases through
#                 retrieved_at_s, so it is a real cost, not a cosmetic pause.
_PROFILES = {
    DefenseLevel.SANDLOT: DefenseProfile(
        label="Sandlot",
        sprint_fts=23.0, reaction_min_s=0.260, reaction_max_s=0.480,
        throw_fts=98.0, release_scale=1.20,
        field_misplay_p=0.061, catch_muff_p=0.0100, body_block=0.40,
        muff_recovery_s=1.80,
    ),
    DefenseLevel.MINORS: DefenseProfile(
        label="Minors",
        sprint_fts=25.5, reaction_min_s=0.225, reaction_max_s=0.420,
        throw_fts=104.0, release_scale=1.09,
        field_misplay_p=0.038, catch_muff_p=0.0050, body_block=0.55,
        muff_recovery_s=1.60,
    ),
    DefenseLevel.LEAGUE: DefenseProfile(
        label="League",
        sprint_fts=27.0, reaction_min_s=0.200, reaction_max_s=0.380,
        throw_fts=110.0, release_scale=1.00,
        field_misplay_p=0.023, catch_muff_p=0.0025, body_block=0.70,
        muff_recovery_s=1.50,
    ),
    DefenseLevel.GOLD_GLOVE: DefenseProfile(
        label="Gold Glove",
        sprint_fts=29.0, reaction_min_s=0.170, reaction_max_s=0.320,
        throw_fts=118.0, release_scale=0.88,
        field_misplay_p=0.012, catch_muff_p=0.0012, body_block=0.85,
        muff_recovery_s=1.30,
    ),
}

NEUTRAL = _PROFILES[DefenseLevel.LEAGUE]

# Ladder order, for cycling a setting and for pinning against
# SettingsManager.DEFENSE_LEVELS. Settings deliberately does not import this
# module -- gameplay already depends on settings, and the reverse edge would
# close a cycle -- so a test holds the two lists together instead.
LEVEL_VALUES = tuple(level.value for level in DefenseLevel)


def profile_for(level):
    """The profile for a level, given the enum, its string value, or None.

    Total by construction: anything unrecognised returns NEUTRAL. Callers
    reach this from a settings string that a hand-edited settings.json can
    make arbitrary, and a defense setting is not worth an exception on the
    path that decides a batted ball.
    """
    if isinstance(level, DefenseProfile):
        return level
    if isinstance(level, DefenseLevel):
        return _PROFILES[level]
    if isinstance(level, str):
        try:
            return _PROFILES[DefenseLevel(level)]
        except ValueError:
            return NEUTRAL
    return NEUTRAL


# ---- Misplays -------------------------------------------------------------
# What a misplay costs, and how often one happens.
#
# This is NOT infield_timing.HARD_PLAY_PROB, and the distinction is worth
# keeping sharp because the two are adjacent. That constant's own comment says
# it is "deliberately *not* named for a bobble" -- it stands in for the short
# hop, the in-betweener, the backhand, every source of play-to-play difficulty
# the geometry cannot see, and it exists to give the margin distribution a left
# tail. It is calibrated to hold the infield-hit rate at 6-8%. A misplay here
# is a different event: the fielder had the play and did not make it, and it is
# charged as an error when it cost the out.
#
# Both add to the same left tail, though, so the two interact. If adding
# misplays pushes the infield-hit rate on fielded grounders out of its band,
# HARD_PLAY_PROB comes down by whatever the misplay term added.

MISPLAY_COST_S = (0.6, 1.8)     # a bobble, in seconds on the release clock

# How much harder a play gets as the fielder is stretched or the ball is hot.
# `RANGING_FULL_FT` is imported rather than restated so that "how hard was this
# play" has exactly one definition -- release time already interpolates on it,
# and a second copy is how two models of one thing start.
RANGING_FULL_FT = RELEASE_STRETCH_FT     # 18 ft = fully stretched
HOP_REF_MPH = 70.0                       # below this the hop is not a problem
HOP_SPAN_MPH = 40.0                      # ...and by 110 it fully is

MISPLAY_RANGING_GAIN = 1.5      # fully stretched: 2.5x as likely to be misplayed
MISPLAY_HOP_GAIN = 0.8          # a scorched short hop
MISPLAY_CHARGE_MULT = 1.4       # the barehand play in on a slow roller
MISPLAY_P_MAX = 0.35            # even the worst play is mostly made

# Of the balls a fielder fails to glove, the share that are not stopped at all
# and continue into the outfield. See `body_block`.
#
# These degrade the fielder's *blocking*, rather than scaling the share that
# gets through. Written the other way round -- share = (1 - body_block) times
# these gains -- an ordinary play (6 ft of range, 95 mph) already multiplied
# out past 1.0 at the bottom two levels, so both clamped to the cap and became
# indistinguishable: body_block stopped mattering on exactly the contact where
# the setting should read most clearly. Degrading the block keeps the result in
# [0, 1] by construction and leaves the levels separated everywhere.
THROUGH_HOP_GAIN = 0.9          # a scorched short hop gets through
THROUGH_STRETCH_GAIN = 1.1      # you cannot get your body in front of a ball in the hole
THROUGH_SHARE_MAX = 0.85        # even the worst ball is sometimes knocked down

# What the ball keeps. A muffed catch is nearly dead -- the glove absorbs it
# and it squirts a few feet. A ball through a fielder keeps most of its pace,
# and how much it kept says what happened: a ball that kept everything went
# clean under the glove and did not turn, one that lost half its pace clearly
# hit something and should have deflected. The caller couples the bearing
# jitter to the speed lost for exactly that reason.
MUFF_RETENTION = 0.10
THROUGH_RETENTION = (0.55, 1.0)


def _unit(value, ref, span):
    """Clamp `(value - ref) / span` into [0, 1]."""
    if value is None:
        return 0.0
    return min(1.0, max(0.0, (value - ref) / span))


def hop_difficulty(ev_mph):
    """How much the ball's pace is working against the fielder, in [0, 1]."""
    return _unit(ev_mph, HOP_REF_MPH, HOP_SPAN_MPH)


def stretch(ranging_ft):
    """How far off their set position the fielder had to go, in [0, 1].

    The same quantity `infield_timing.release_time_s` interpolates its release
    penalty on, by construction -- see RANGING_FULL_FT.
    """
    return _unit(ranging_ft, 0.0, RANGING_FULL_FT)


def misplay_prob(profile, ranging_ft=0.0, ev_mph=None, is_charging=False,
                 in_air=False):
    """P(this fielder does not handle this ball cleanly).

    A function of the play, not a flat rate. Section 8 of the infield timing
    doc names the flat rate as what is wrong with HARD_PLAY_PROB -- "the real
    fix is a fielding-difficulty model (distance ranged x direction x hop
    quality) rather than one flat probability" -- and the ingredients are all
    computed at the call site already.

    `in_air` means the ball was going to be *caught* for an out (a fly, liner
    or pop-up), as opposed to fielded off the ground.
    """
    base = profile.catch_muff_p if in_air else profile.field_misplay_p
    p = base * (1.0 + MISPLAY_RANGING_GAIN * stretch(ranging_ft))
    if not in_air:
        p *= (1.0 + MISPLAY_HOP_GAIN * hop_difficulty(ev_mph))
    if is_charging:
        p *= MISPLAY_CHARGE_MULT
    return min(MISPLAY_P_MAX, p)


def through_share(profile, ranging_ft=0.0, ev_mph=None):
    """Of misplays on this play, the share where the ball is not stopped.

    The third state, and the one the model has never had: today a ball is
    either untouched (a hit) or touched (a race). Real baseball has "reached,
    and still through" -- and it is where a good chunk of ground-ball hits
    actually come from.

    The play's difficulty enters by degrading the *block*, not by scaling the
    share: a hot ball in the hole is one you cannot get your body in front of,
    which is a statement about the fielder's leverage rather than about the
    ball. That keeps the answer inside [0, 1] however hard the play, so the
    ladder stays separated instead of every level clamping to the cap.

    On a routine play this is exactly `1 - body_block`, which is what the
    level table was specified against.
    """
    block_efficiency = 1.0 / ((1.0 + THROUGH_HOP_GAIN * hop_difficulty(ev_mph))
                              * (1.0 + THROUGH_STRETCH_GAIN * stretch(ranging_ft)))
    share = 1.0 - profile.body_block * block_efficiency
    return min(THROUGH_SHARE_MAX, max(0.0, share))


def roll_misplay(profile, rng, ranging_ft=0.0, ev_mph=None, is_charging=False,
                 in_air=False):
    """Sample what happened to the ball: None, "BOBBLE", "THROUGH" or "MUFF".

    Composed here rather than in the animation so the whole decision is
    testable without a renderer, and so there is one place that knows a
    through-ball is only possible off the ground. A ball does not go "through"
    a fielder who was going to catch it in the air -- that is a drop.

    Two draws, deliberately: whether the play was misplayed, and then what
    kind. Folding them into one would make the through-rate and the
    misplay-rate move together, and they are calibrated against different
    targets (the ground-ball hit rate and the error rate respectively).
    """
    if rng.random() >= misplay_prob(profile, ranging_ft, ev_mph,
                                    is_charging, in_air):
        return None
    if in_air:
        return "MUFF"
    if rng.random() < through_share(profile, ranging_ft, ev_mph):
        return "THROUGH"
    return "BOBBLE"


def misplay_cost_s(rng):
    """Seconds a bobble adds to the release clock.

    Held fixed across the ladder on purpose. Defense strength decides how
    *often* a ball is misplayed, not how badly -- so retuning the frequency
    never changes what a bobble looks like on screen, and MISPLAY_COST_S is
    not a second dial fighting the first.
    """
    return rng.uniform(*MISPLAY_COST_S)


def through_retention(rng):
    """Fraction of its speed a ball keeps going through a fielder."""
    return rng.uniform(*THROUGH_RETENTION)


__all__ = [
    "DefenseLevel",
    "DefenseProfile",
    "LEVEL_VALUES",
    "MISPLAY_COST_S",
    "MUFF_RETENTION",
    "NEUTRAL",
    "THROUGH_RETENTION",
    "hop_difficulty",
    "misplay_cost_s",
    "misplay_prob",
    "profile_for",
    "roll_misplay",
    "stretch",
    "through_retention",
    "through_share",
]
