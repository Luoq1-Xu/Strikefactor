"""Contact sound selection, driven by a modelled exit velocity.

Every bat-on-ball event in the game — weak foul tick, routine grounder,
no-doubt homer — routes through `pick_contact_sound()` here. The *only*
thing that separates a foul from a home run acoustically is the exit
velocity number, not a separate code branch. That is deliberate: the old
code played one fixed sample per outcome, so every foul sounded identical
and a wind-blown 96-mph fly ball that snuck over the wall got the same
max-crack sample as a 112-mph line drive.

Two layers produce the spectrum, because five crack samples cannot carry
it alone:

  * Selection — an ordered ladder of samples with *overlapping* EV bands.
    Blending at the edges means 97 mph lands on TRIPLE sometimes and
    DOUBLE others, rather than snapping at a hard threshold.
  * Gain — volume scales continuously with EV inside the chosen band, so
    the ladder supplies texture and the gain supplies the gradient.

Pure module: no pygame, no I/O, no game state. Everything here is a
function of (quality, swing_type), so it is unit-testable without a mixer
and stays off the gameplay layer's import path.
"""

import math
import random

# ── Exit velocity model ──────────────────────────────────────────────────
# MLB batted balls run roughly 40 mph (checked-swing tappers) to 120 mph
# (Stanton). We compress slightly at both ends: the floor is a foul tip
# off the very end of the bat, the ceiling a perfectly barreled power
# swing.
EV_FLOOR_MPH = 52.0
EV_CEIL_MPH = 116.0

# Quality -> EV is a *calibrated* curve, not an analytic one, because the
# game's `quality` is nowhere near uniform on [0, 1]. It is only computed
# for swings that squared the ball up enough to put it in play, so its real
# distribution is skewed hard toward 1.0. A naive linear or power mapping
# therefore puts the *median* batted ball near the top of the scale, which
# is how you end up with the max-crack sample on routine grounders — the
# exact failure this module exists to fix.
#
# So the observed quality quantiles are pinned to MLB exit-velocity
# quantiles (mean ~89, p25 ~81, p50 ~91, p75 ~101, p90 ~106) and
# interpolated between.
#
# Re-derived most recently when the location term in `spray` was made to
# **saturate** — see `spray.LOCATION_SPAN_DEG`. Over fair contact at AMATEUR
# it now runs:
#
#     p10 0.643  p25 0.689  p50 0.763  p75 0.871  p90 0.937  p99 0.988
#
# against 0.580 / 0.653 / 0.743 / 0.858 / 0.932 / 0.987 immediately before it,
# 0.690 / 0.717 / 0.769 / 0.851 / 0.918 / 0.985 for the slide model, 0.61 /
# 0.70 / 0.81 / 0.93 / 0.98 / 1.00 for the anisotropic bat, and 0.631 / 0.770 /
# 0.886 / 0.954 / 0.982 / 0.998 for the rectangle.
#
# **The bottom tail lifted and the top barely moved** (+0.063 at p10 against
# +0.001 at p99), which is the signature of the change rather than a side
# effect of it. The straight-line location term was sending every ball the
# hitter had to reach for past the foul line at about -59 deg, and those balls
# were **well struck** — reaching out and putting the barrel on an outside
# pitch is not a mishit. Releasing them back into fair territory adds solid
# contact at the bottom of the fair distribution, so the low quantiles rise.
# `FOUL_QUALITY_THRESHOLD` came up 0.52 -> 0.59 at the same time to hold the
# total foul rate (47.4% -> 47.6% measured), which lifts the floor again.
#
# Re-anchoring is not optional. Left on the previous anchors this table read
# the p10 batted ball about 6 mph hot, which is a thumb on the scale toward
# extra bases on exactly the balls that should be dying in the infield.
#
# **Never fit this against a uniform sweep of quality.** The numbers above
# come from a Monte Carlo over a plausible player model (aim error in
# pixels, timing error in ms) run through the real `resolve_contact`; the
# alternative, once enough play is recorded, is quantiles of
# `contact_quality` straight out of the pitch DB. Both describe the swings
# players actually make. A `range(0, 1)` sweep does not, and four separate
# constants in this codebase have been miscalibrated by assuming it does.
EV_CALIBRATION = (
    (0.000,  52.0),
    (0.300,  62.0),
    (0.450,  68.0),
    (0.643,  74.0),   # observed p10
    (0.689,  82.0),   # observed p25
    (0.763,  91.0),   # observed p50
    (0.871, 101.0),   # observed p75
    (0.937, 106.0),   # observed p90
    (0.988, 112.0),   # observed p99
    (1.000, EV_CEIL_MPH),
)

# Power swings trade contact area for bat speed. Same quality, harder ball.
EV_POWER_BONUS_MPH = 5.0
EV_POWER_JITTER_MPH = 4.5      # power swings are streakier
EV_CONTACT_JITTER_MPH = 2.5

# `quality` already folds in all three ways a swing can be off: where along
# the bat, how far across it, and how much of the clock the swing had to be
# given (`bat_contact.Contact.quality` is the geometric mean of the three).
# Do not re-apply vertical_offset here — that would double-count the mishit
# and push every off-centre ball into the silent floor.


def _interpolate(q, table):
    """Piecewise-linear lookup on an ascending (x, y) table."""
    if q <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if q <= x1:
            span = x1 - x0
            if span <= 0:
                return y1
            return y0 + (y1 - y0) * (q - x0) / span
    return table[-1][1]


def exit_velocity_mph(quality, swing_type="contact", rng=random):
    """Model an exit velocity in mph from contact quality.

    `swing_type` is "power" (E key) or "contact" (W key). `rng` is
    injectable so tests can pin the jitter.
    """
    q = max(0.0, min(1.0, quality or 0.0))
    ev = _interpolate(q, EV_CALIBRATION)

    if swing_type == "power":
        ev += EV_POWER_BONUS_MPH
        jitter = EV_POWER_JITTER_MPH
    else:
        jitter = EV_CONTACT_JITTER_MPH

    # Jitter keeps identical swings from sounding mechanically identical.
    ev += rng.gauss(0.0, jitter)
    return max(EV_FLOOR_MPH, min(EV_CEIL_MPH, ev))


# ── Sample ladder ────────────────────────────────────────────────────────
# Ordered weakest -> hardest. `centre` is the EV where the sample is most
# characteristic; `width` sets how far either side it stays plausible.
# Bands overlap on purpose so adjacent samples trade off gradually.
#
# The keys are named for how the contact sounds, never for an outcome.
# These assets used to be called SINGLE/DOUBLE/TRIPLE/HOMERUN, which was
# actively misleading once selection moved here: "contact_solid" plays on
# any ~95 mph ball, which may end up a double, a lineout or a foul.
CONTACT_LADDER = (
    ("contact_weak",     64.0, 14.0),   # thin, off-the-end tick
    ("contact_medium",   84.0, 13.0),
    ("contact_solid",    95.0, 11.0),
    ("contact_hard",    103.0, 10.0),
    ("contact_crushed", 111.0,  9.0),   # reserved for scorched contact
)

# The top sample is gated: no matter how the weights fall, the crushed
# sample never plays under this EV. This is the whole point of the
# exercise — a home run that merely carried should not sound like a
# demolition.
HOMERUN_MIN_EV_MPH = 103.0
CRUSHED_SAMPLE = "contact_crushed"

# ── Home runs ────────────────────────────────────────────────────────────
# A home run's EV comes from the distance the player is about to *see*,
# not from contact quality. The two disagree badly otherwise: the HR carry
# model in hit_animation rolls a largely random `bias` for distance, so a
# mediocre-quality contact can legitimately land 460 ft away — and then a
# soft "medium" crack plays under a no-doubter. Reading the distance back
# makes what you hear and what you see the same event.
#
# Statcast reference points: a wall-scraper at ~330 ft leaves the bat
# around 95-98 mph, a routine 400 ft homer ~104, 450 ft ~110, and the
# 480 ft moonshots ~114.
HR_DISTANCE_TO_EV = (
    (330.0,  96.0),
    (370.0, 101.0),
    (400.0, 104.0),
    (430.0, 108.0),
    (460.0, 112.0),
    (490.0, EV_CEIL_MPH),
)

# Floor on the *rung*, independent of the EV maths above. Even the
# cheapest wall-scraper is solid contact — nobody hits a home run off the
# end of the bat — so the two quietest samples are never valid under one.
HOMERUN_MIN_SAMPLE = "contact_solid"


def exit_velocity_for_hr_distance(distance_ft):
    """EV implied by a home run's landing distance."""
    if distance_ft is None:
        return None
    return _interpolate(float(distance_ft), HR_DISTANCE_TO_EV)

# Gain curve. Quiet enough that a tapper is genuinely soft, without
# making it inaudible on small speakers.
MIN_GAIN = 0.45
MAX_GAIN = 1.0
GAIN_EV_LO = 60.0    # at/below this EV -> MIN_GAIN
GAIN_EV_HI = 110.0   # at/above this EV -> MAX_GAIN


def _weight(ev, centre, width):
    """Gaussian falloff of a sample's plausibility at a given EV."""
    return math.exp(-0.5 * ((ev - centre) / width) ** 2)


def contact_gain(ev):
    """Playback gain (0..1) for a contact at `ev`, clamped to the curve ends."""
    span = GAIN_EV_HI - GAIN_EV_LO
    frac = (ev - GAIN_EV_LO) / span
    frac = max(0.0, min(1.0, frac))
    return MIN_GAIN + (MAX_GAIN - MIN_GAIN) * frac


def _rung_index(name):
    for i, (rung, _, _) in enumerate(CONTACT_LADDER):
        if rung == name:
            return i
    return 0


def pick_contact_sound(ev, available=None, rng=random, min_sample=None):
    """Pick a (sample_name, gain) pair for a contact at `ev` mph.

    `available` is the set of sample names the SoundManager actually
    loaded; entries missing from it are skipped so a missing asset
    degrades to the next-best rung instead of silence.

    `min_sample` floors the selection at that rung — used for home runs,
    where the quiet samples are never physically plausible whatever the
    weights say.
    """
    gain = contact_gain(ev)
    floor_idx = _rung_index(min_sample) if min_sample else 0

    def usable(name):
        return available is None or name in available

    candidates = []
    for i, (name, centre, width) in enumerate(CONTACT_LADDER):
        if i < floor_idx or not usable(name):
            continue
        if name == CRUSHED_SAMPLE and ev < HOMERUN_MIN_EV_MPH:
            continue
        w = _weight(ev, centre, width)
        if w > 0.01:
            candidates.append((name, w))

    if not candidates:
        # Everything filtered out (unloaded assets, an EV past the top of
        # the ladder with the crushed sample missing, or a floor above
        # every usable rung). Fall back to the loudest rung we can play,
        # never below the requested floor.
        for i in range(len(CONTACT_LADDER) - 1, -1, -1):
            name = CONTACT_LADDER[i][0]
            if usable(name) and i >= floor_idx:
                return name, gain
        for name, _, _ in reversed(CONTACT_LADDER):
            if usable(name):
                return name, gain
        return CONTACT_LADDER[0][0], gain

    names, weights = zip(*candidates)
    return rng.choices(names, weights=weights, k=1)[0], gain


def contact_sound_for(quality, swing_type="contact", available=None, rng=random,
                      hr_distance_ft=None):
    """Convenience: quality -> (sample_name, gain, ev). One call per contact.

    Pass `hr_distance_ft` when the contact is a home run whose landing
    distance is already known. EV is then taken from that distance rather
    than from quality, and the selection is floored at HOMERUN_MIN_SAMPLE,
    so the crack matches the number on screen.
    """
    if hr_distance_ft is not None:
        ev = exit_velocity_for_hr_distance(hr_distance_ft)
        min_sample = HOMERUN_MIN_SAMPLE
    else:
        ev = exit_velocity_mph(quality, swing_type, rng=rng)
        min_sample = None

    name, gain = pick_contact_sound(
        ev, available=available, rng=rng, min_sample=min_sample)
    return name, gain, ev
