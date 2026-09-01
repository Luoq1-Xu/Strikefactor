"""Which way a batted ball went, in real degrees.

Same contract as `engine/contact_audio.py` and `ball_flight.py` — real units,
no pygame, no game state, no animation objects. One question: given the bat at
the instant it met the ball, what direction did the ball leave in.

This module exists because that question had **four** answers and the one that
mattered most was a coin toss. A ball in play drew
`random.uniform(50 deg, 130 deg)`; a home run biased off the *pitch's* location;
a ball that reached the wall picked its side with `random.choice((-1, 1))`; and
only a foul consulted the swing at all, through the sign of a timing error.
Four models of one thing, none of them the bat.

**The bat already knew.** `bat_path` carries a full ground bearing at every
instant of the swing and `bat_contact` sweeps against it — the bearing was
simply discarded at the module boundary. Everything here is read off it:

  * a cylinder's surface normal is radial to its own axis, so the ball leaves
    perpendicular to the bat, and the horizontal part of that perpendicular is
    the spray;
  * the bat turns as the swing runs, so being early or late rotates the face
    and the ball follows — early pulls, late goes the other way;
  * `bat_path._contact_pose` meets an inside pitch further out front (more
    foreshortened, so the bat is further round) and a pitch away deeper, so
    inside is pulled and away is not.

None of those three is stated anywhere. They are consequences of a bat that has
a bearing, which is why this module contains no rule — only a calibration.

Spray is **deliberately deterministic** given the swing. There is no jitter
term: the spread the player produces already comes from their own aim and
timing scatter, and a ball that goes where it was hit is the thing the swing
replay exists to teach.

Sign convention, stated once and applied nowhere else: `spray_angle_deg` is
**pull-positive** for both batters — positive is toward the batter's own pull
field, left for a right-hander and right for a left-hander. `field_angle_deg`
is the one conversion into the animation's frame, and the only place the
handedness flip lives. Three coordinate frames meet around here and two of them
disagree about the sign of x; see `field_angle_deg`.
"""

import math

# Fair territory. The real foul lines, not the animation's screen-space ones.
FOUL_LINE_DEG = 45.0


# --- The geometry ---------------------------------------------------------

def attack_direction_deg(bat_axis_ft, spin):
    """The bat's face normal, degrees from centre field. Pull-positive.

    Pure geometry — nothing here is tuned, and this is the number the
    calibration below is a calibration *of*.

    `bat_axis_ft` is the bat's long axis, knob to barrel, in world feet; only
    its horizontal part is read. `spin` is `BatSwing.spin`: +1 for a
    right-handed batter and -1 for a left-handed one, which is also the sign of
    that batter's own side of the plate and therefore of their pull field.

    Mirror-symmetric by construction: the depth component `ay` is the same for
    both batters at the same point in the swing, and the lateral component
    flips with `spin` exactly as the batter does. Writing it the other obvious
    way — signing the *normal* rather than the angle — is right for a
    right-hander and reports a left-hander's pull as opposite field, which is
    the mirror bug `collision_angled` carried for the life of the project.
    `tests/test_spray.py` pins it.
    """
    ax, ay = bat_axis_ft[0], bat_axis_ft[1]
    if math.hypot(ax, ay) < 1e-9:
        return 0.0
    return math.degrees(math.atan2(ay, -spin * ax))


# --- The calibration ------------------------------------------------------

# **Location and timing are calibrated separately, and in opposite
# directions.** That is the whole shape of this table and it is not an
# indulgence: a single gain over the raw angle cannot be fitted at all.
#
# The raw geometry gets the *shape* of both responses right and the *scale* of
# both wrong:
#
#   * **Location over-responds.** `_contact_pose` swings the bat's angle 79 deg
#     across a two-foot plate, because it is pinned to the engine's
#     screen-space aiming pivot: on an inside pitch the hands and the barrel
#     end up five inches apart laterally with a 2.46 ft bat between them, so
#     the bat points nearly at the pitcher. A real hitter's hands come in on an
#     inside pitch; these cannot.
#
#     What bounds this gain is a *constraint rather than a fit*: a flawless
#     swing anywhere in the strike zone has to be able to stay fair. At 1.30 it
#     runs -41 deg to +35 across the zone — gap to gap, with four degrees of
#     margin at the outside corner. Passed through at full strength (2.5, which
#     is what a single gain fitted to the foul rate wants) half the zone became
#     unhittable: a perfect swing on an inside or outside strike was an
#     automatic foul.
#   * **Timing under-responds, by about 2.4x.** A real bat turns about
#     1.5 deg/ms, so a swing 20 ms late meets the ball with the face 30 deg
#     less turned. This model produces 0.63 deg/ms, because the sweep finds the
#     closest *approach* rather than a fixed phase: a late bat catches the ball
#     on the handle at a time nearer the ball's own arrival, which gives back
#     most of the rotation. `TIMING_GAIN` puts the real rate back.
#
# Raising the timing gain is **free in a way raising the location gain is
# not**, and that asymmetry is why they are separate constants rather than one
# scale. A perfectly timed swing has a timing term of exactly zero, so no
# amount of `TIMING_GAIN` can move it; the flawless-swing range below is a
# function of `LOCATION_GAIN` alone. All the timing gain does is spread
# mistimed contact, which is the thing that should be spread.
#
# So the two are split — `pose_attack_deg` is the nominal contact pose, which
# is a function of the aim alone, and the difference between it and
# `attack_deg` is the turn the residual timing put on the bat.
#
# Same kind of object as `contact_audio.EV_CALIBRATION`, and it carries the
# same warning: **never fit it against a uniform sweep of anything.** The
# anchors come from a Monte Carlo over a plausible player model (aim scatter
# 0.42 ft, timing N(+19, 35) ms) run through the real `resolve_contact`.
#
# The two checks that matter, and either one alone is misleading:
#   1. a flawless swing anywhere in the strike zone must be able to be fair
#      (it runs -25 deg to +27 deg here, gap to gap);
#   2. the fair population must look like MLB's. Measured at AMATEUR: mean
#      +4.4 deg, sd 20.0, split 33% pull / 49% centre / 18% opposite against
#      MLB's 40/35/25. Still flatter than real, because half of all contact has
#      near-zero residual timing once `timing_assist_s` has done its work, and
#      a term that is zero cannot be spread. Note the fair mean sits below
#      `LEAGUE_MEAN_DEG`: the pull tail is the side the foul lines cut into, so
#      the surviving population is dragged back toward centre.
#
# **The centre share is not only a realism target, it is a BABIP dial**, and
# that is the reason `LOCATION_GAIN` sits where it does rather than lower.
# `hit_animation.FIELDER_HOMES` is static and was implicitly calibrated against
# the uniform spray this replaced, so a centre-heavy distribution puts balls
# where the alignment has holes — over second base, which middle infielders
# cannot reach. Measured on one fixed set of fair balls in play: uniform spray
# gives BABIP .328, this model at a 0.95 gain gives .390, and at 1.30 it gives
# .343. Widening it toward the league split and recovering BABIP are the same
# adjustment. What is left of the gap belongs to the defensive alignment, not
# here.
#
# Together these put 18-21% of contact foul by direction, depending on how wide
# a player model it is measured over (it was 24-28% before the location term
# saturated, and that difference was not real — see below). That is the *whole*
# of what direction can carry — see `is_foul`.
#
# **The location term saturates, and it has to.** `_contact_pose` pins the bat
# by knob-on-pivot and sweet-spot-on-the-cursor-ray, and past the point where
# the bat can no longer span the ball from where the hands are, the pose comes
# off the quadratic's vertex — the perpendicular foot from a *fixed* knob to a
# family of near-parallel camera rays. That foot's bearing converges: pose runs
# -1.7 deg at an aim of -0.90 ft and -2.7 at -1.40, a response of 1.9 deg/ft
# against 27-136 deg/ft on the reachable side. The bat has stopped answering
# the question.
#
# The limit it converges on is pose ~ 0, which is the bat square across and its
# face normal at **dead centre field** — a perfectly good inside-out reach, and
# harmless. What was not harmless was amplifying it. Read through a straight
# line, `LEAGUE_MEAN_DEG + (0 - 49) * 1.30` is -55.7 deg: more than ten degrees
# **foul**, on a pitch the hitter reached out and put the barrel on. So the
# gain was manufacturing a foul ball out of a term that had no information left
# in it, and doing it hardest exactly where a pitcher lives.
#
# Measured in recorded play before the change: 43% of all right-handed contact
# landed in a **1.5 deg wide band at -59 deg**, every ball of it foul, over
# pitches spanning 0.8 ft of plate. The same ball, over and over. It is the
# flat spot `bat_path._reach` was rewritten to remove, and the rewrite did not
# remove it — it moved the attractor from exactly 0 deg (fair, centre field) to
# about -59 (foul), which is strictly worse.
#
# `tanh` is the smallest honest repair: it has slope exactly `LOCATION_GAIN` at
# the reference, so the middle of the plate is untouched — bit-identical, not
# merely close — and it only bends where the response was already fake. The
# asymptote is `LEAGUE_MEAN_DEG +/- LOCATION_SPAN_DEG`, so a maximally reached
# outside pitch goes to -40 deg: opposite field, just fair, which is what an
# inside-out reach *is*. The pull side has no asymptote to hit (pose keeps
# climbing at ~26 deg/ft on an inside aim, with no reach boundary to run into),
# so hooking an inside pitch foul is still perfectly possible.
#
# Note what this does **not** fix: the dead zone is still there, so every ball
# past the reach boundary still goes to about the same place. It is now a fair
# place. Giving the reach genuine bearing authority means letting the hands come
# off the anchor laterally — the same fixed-pivot problem named above for the
# inside pitch — and that is a `bat_path` change that would need both constants
# here re-derived. Worth knowing: at the knees the boundary sits at an aim of
# -0.51 ft, which is inside the strike zone.
SQUARE_REF_DEG = 49.0     # the bat's angle on a middle-middle pitch, met square
LEAGUE_MEAN_DEG = 8.0     # MLB mean spray, pull side of centre
LOCATION_GAIN = 1.30      # slope at the reference; 79 deg of raw bat angle -> ~76
LOCATION_SPAN_DEG = 48.0  # where the location term saturates, +/- from the mean
TIMING_GAIN = 2.4         # 0.63 deg/ms of model -> the real bat's ~1.5


def spray_angle_deg(pose_attack_deg, attack_deg):
    """The ball's direction: degrees from centre field, pull-positive.

    `pose_attack_deg` is where the bat would have pointed had the swing been
    perfectly timed — the aim's contribution. `attack_deg` is where it actually
    pointed. Their difference is the timing's contribution, and the two are
    scaled differently for the reasons above.
    """
    location = LOCATION_SPAN_DEG * math.tanh(
        (pose_attack_deg - SQUARE_REF_DEG) * LOCATION_GAIN / LOCATION_SPAN_DEG)
    return (LEAGUE_MEAN_DEG
            + location
            + (attack_deg - pose_attack_deg) * TIMING_GAIN)


def is_foul(spray_deg):
    """Whether this ball left fair territory to the side.

    **Not the whole foul verdict** — about a seventh of it. Direction is the
    way to foul a ball that this game did not have: hooked or sliced past a
    pole, which a well-struck ball is perfectly capable of and could not do
    before. The other way is glancing contact — tipped, topped, caught on the
    handle, fouled straight back — and that is what contact *quality* measures.
    `bat_contact.Contact.is_foul` asks both.

    Splitting them is not a compromise, it is the decomposition. Asking quality
    alone meant a barrelled ball could never be hooked foul and a mishit
    between the lines could never be a dribbler in play. Asking direction alone
    is not reachable: it caps around 25% of contact against a real ~50%,
    because the term that would have to carry the rest is location, and pushing
    that far makes a flawless swing on a strike an automatic foul. Both were
    measured before this was written.
    """
    return abs(spray_deg) > FOUL_LINE_DEG


# --- The one frame conversion ---------------------------------------------

def field_angle_deg(spray_deg, spin):
    """Pull-signed degrees into `hit_animation`'s real-field angle.

    Three frames meet here and two of them disagree about the sign of x:

        world (bat, pitch)   +x is the THIRD base side, so +x is a
                             right-hander's pull field. Note that
                             `pitch_physics`'s module docstring says the
                             opposite ("positive to catcher's right") — the
                             code is what is right: `UmpireCamera.project`
                             negates x, and a right-hander's pivot is at +1.53.
        field (animation)    field_x = -world_x. 90 deg is centre field, above
                             90 is left field, and the real foul lines are at
                             45 and 135.
        screen polar         the same origin through an anisotropic projection,
                             which flattens those lines to ~30.7 and ~149.3.

    So this is `90 + spin * spray`, and it is the only place that flip is
    allowed to happen. A sign error here mirrors the batter, and a mirrored
    batter is a defect that survived a year of this project once already.
    """
    return 90.0 + spin * spray_deg


def field_angle_rad(spray_deg, spin):
    """`field_angle_deg` in radians, which is what the animation speaks."""
    return math.radians(field_angle_deg(spray_deg, spin))


def spin_for(handedness):
    """`BatSwing.spin` without building a swing: +1 for a RHB, -1 for a LHB."""
    return 1.0 if handedness != "L" else -1.0


def world_direction(spray_deg, spin):
    """The departure bearing as a unit vector in **world** feet, `(x, y, z)`.

    `field_angle_deg`'s sibling, for the one consumer that wants the world
    frame rather than the animation's: the swing replay, which draws the ray
    on a diagram built out of the same world-feet models as the bat.

    Here rather than open-coded there for the reason the module docstring
    gives — the handedness flip gets exactly one home per frame, or a sign
    error mirrors the batter in a view whose whole job is showing which way
    the swing went.
    """
    rad = math.radians(spray_deg)
    return (spin * math.sin(rad), math.cos(rad), 0.0)
