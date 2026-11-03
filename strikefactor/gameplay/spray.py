"""Which way a batted ball went, in real degrees.

Same contract as `engine/contact_audio.py` and `ball_flight.py` — real units,
no pygame, no game state, no animation objects.

This module exists because the direction of a batted ball had **four** answers
and the one that mattered most was a coin toss. A ball in play drew
`random.uniform(50 deg, 130 deg)`; a home run biased off the *pitch's* location;
a ball that reached the wall picked its side with `random.choice((-1, 1))`; and
only a foul consulted the swing at all, through the sign of a timing error.
Four models of one thing, none of them the bat.

**The direction itself is no longer worked out here.** It comes from one
collision between the bat and the ball (`bat_ball_collision`), which
`bat_contact.resolve_contact` evaluates once and stamps on the `Contact`.
`Contact.spray_deg` is the horizontal reading of that vector and
`Contact.launch_deg` the vertical one.

What this module used to hold in its place was a remap. The bat was 49
degrees past square on a middle pitch, because its hands were pinned to one
point, so its face normal could not be read as a direction. `spray_angle_deg`
subtracted the 49 (`SQUARE_REF_DEG`), rescaled what was left
(`LOCATION_GAIN`, `LOCATION_SPAN_DEG`), multiplied the timing response by 2.4
(`TIMING_GAIN`) and added a league mean. The swing replay then drew the real
bat beside the remapped ball. `bat_path` meets a middle pitch within a few
degrees of square now and the collision supplies the rest, so all five
constants are gone and no gain stands between the bat and the ball.

What is left here is what was always this module's own:

  * the frame. `spray_deg` is **pull-positive** for both batters — positive is
    toward the batter's own pull field, left for a right-hander and right for a
    left-hander. `pull_frame` converts into it, and `field_angle_deg` and
    `world_direction` are the only conversions out. Three coordinate frames
    meet around here and two of them disagree about the sign of x; see
    `field_angle_deg`;
  * the bat's bearing, `attack_direction_deg`, which is a fact about the bat
    and no longer a statement about the ball;
  * the foul lines, and where a ball already ruled foul actually went.

Spray is **deterministic** given the swing. There is no jitter term anywhere
in the chain: the spread the player produces comes from their own aim and
timing scatter, and a ball that goes where it was hit is the thing the swing
replay exists to teach.
"""

import math

# Fair territory. The real foul lines, not the animation's screen-space ones.
FOUL_LINE_DEG = 45.0


# --- The geometry ---------------------------------------------------------

def attack_direction_deg(bat_axis_ft, spin):
    """How far past square the bat is, in degrees. Pull-positive.

    Zero is the bat lying straight across the plate, its face square to the
    pitcher. Positive is the barrel further round toward the pitcher, which
    turns the face toward the batter's pull field. Pure geometry.

    **This is the bat's bearing, not the ball's.** The ball leaves about 1.6
    times as far round as the bat faces, and getting under or over it on a
    tilted bat turns it again; `bat_ball_collision` works that out.
    `batted_ball_path` reads the difference between two of these as the
    sidespin a mistimed swing puts on the ball.

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


def is_foul(spray_deg):
    """Whether this ball left fair territory to the side.

    **Not the whole foul verdict.** Direction is one of the two ways to foul
    a ball: hooked or sliced past a pole, which a well-struck ball is
    perfectly capable of, or struck so glancingly that it left backward. The
    other is contact that was not clean — caught on the handle, off the end,
    or on borrowed time — and that is what contact *quality* measures.
    `bat_contact.Contact.is_foul` asks both.

    Splitting them is not a compromise, it is the decomposition. Asking quality
    alone meant a barrelled ball could never be hooked foul and a mishit
    between the lines could never be a dribbler in play. Asking direction alone
    leaves out the ball that stayed between the lines off the bat's handle.

    The two overlap more than they did. The direction used to be read off the
    bat's bearing alone, so a tipped ball kept a fair-looking bearing and only
    quality could call it foul. It is read off the collision now, and a ball
    struck glancingly enough leaves behind the plate on its own.
    """
    return abs(spray_deg) > FOUL_LINE_DEG


# --- Where a foul actually went -------------------------------------------

# `is_foul` above answers *whether*; these answer *where*, and they exist
# because for half of all fouls nothing did.
#
# **A glancing blow deflects the ball, and that was not modelled anywhere.**
# `bat_contact.Contact.is_foul` has two limbs and only one of them leaves a
# bearing behind: a ball hooked past the pole has `spray_deg` outside the
# lines and is done, but a ball that was merely *tipped* — topped, caught on
# the handle, fouled straight back — keeps whatever bearing the bat had, which
# is usually a perfectly fair one. Something then has to say where it went,
# and until this existed the thing that said so was `hit_animation._setup_foul`,
# in render code, out of `random`.
#
# What that cost, measured over 600 real fouls: the swing replay drew
# `spray_deg` while the animation flew its own invention, and the two
# disagreed by a median of **40.7 degrees**. 271 of the 600 were drawn by the
# replay as a *fair* ray under a FOUL banner, and on 272 the animation put the
# ball behind the plate while the replay pointed forward. One identical
# contact animated at eight different bearings across eight plays, so the
# replay could not have matched it even if it had tried — which also broke
# this module's own promise that spray is deterministic given the swing.
#
# So the deflection is stated here, once, in real degrees, deterministically,
# and both the animation and the replay read it. There is no jitter term for
# the same reason the collision has none: the spread already comes from the
# player's own quality and aim. If scatter is ever wanted it has to be
# drawn *once* upstream and carried, the way `exit_velocity_mph` is.
#
# The severity ramp is `_setup_foul`'s own expression, lifted unchanged, so
# this is a move rather than a retune. Its shape is the useful part: a ball
# already foul *by direction* keeps its own bearing, so the two limbs meet
# continuously at the line, and a ball foul by *quality* is pushed further out
# the more glancing the contact was.
FOUL_OFF_MAX_DEG = 45.0           # how far past the line a fully glancing blow goes
FOUL_OFF_MIN_DEG = 2.0            # a ball a degree past the pole draws a degree past it
FOUL_GROUNDER_MIN_OFF_DEG = 10.0  # a chopper has to clearly leave fair ground
# A pop-up comes down near where it was struck, so it is behind the plate
# rather than out past a pole: 165 deg (nearly straight back over the catcher)
# when the bat was square, swinging round to 120 as the bat turns.
FOUL_POP_BACK_DEG = (120.0, 165.0)


def foul_severity(spray_deg, quality):
    """How badly this foul left fair territory, 0 to 1.

    0 is a ball a hair the wrong side of a pole; 1 is one sprayed as far foul
    as the model goes. `max` of the two limbs rather than a sum: they are two
    independent ways to be foul (see `is_foul`) and a ball is as foul as the
    worse of them, not as foul as both put together.
    """
    past = max(0.0, abs(spray_deg) - FOUL_LINE_DEG)
    q = max(0.0, min(1.0, quality or 0.0))
    return min(1.0, max(past, (1.0 - q) * FOUL_OFF_MAX_DEG) / FOUL_OFF_MAX_DEG)


def foul_departure_deg(spray_deg, quality, shape="LINER"):
    """The bearing a ball *already ruled foul* actually left on.

    Same units and sign as `Contact.spray_deg` — degrees from centre field,
    pull-positive — so it drops into every place that reads a bearing, and
    `is_foul` is true of the result by construction. That is the property that
    makes the picture and the verdict unable to disagree: whatever draws this
    number draws a ball in foul ground.

    `shape` is the trajectory shape (`ball_flight.shape_for_launch_angle`), and
    only two of the four change the answer. A pop-up is a ball hit almost
    straight up, so it comes down behind the plate rather than out past a pole;
    a chopper needs a floor under it or it draws rolling up the line in fair
    ground on a play nobody made.

    Deterministic, and the sign is taken as `spray_deg >= 0`. The animation
    used to take it as `spray_field_rad > 90 deg`, which is false at exactly
    90 — so every dead-centre foul went to the first-base side.
    """
    side = 1.0 if spray_deg >= 0.0 else -1.0
    severity = foul_severity(spray_deg, quality)
    if shape == "POP_UP":
        lo, hi = FOUL_POP_BACK_DEG
        turned = min(1.0, abs(spray_deg) / FOUL_LINE_DEG)
        return side * (hi - (hi - lo) * turned)
    # **A deflection can only push the ball further foul, never straighten
    # it.** `foul_severity` saturates at 1 because the foul-HR gate needs a
    # bounded number, but a ball the bat genuinely sent 128 deg round is not a
    # ball at 90 — that would be the render layer's old cap, which threw away
    # the one part of the bearing that was never in doubt. So the bat's own
    # excess past the line is a floor here, and the glancing-blow term is what
    # can add to it.
    off = max(severity * FOUL_OFF_MAX_DEG, abs(spray_deg) - FOUL_LINE_DEG)
    off = max(FOUL_OFF_MIN_DEG, off)
    if shape == "GROUNDER":
        off = max(off, FOUL_GROUNDER_MIN_OFF_DEG)
    return side * (FOUL_LINE_DEG + off)


# --- The one frame conversion ---------------------------------------------

def field_angle_deg(spray_deg, spin):
    """Pull-signed degrees into `hit_animation`'s real-field angle.

    Three frames meet here and two of them disagree about the sign of x:

        world (bat, pitch)   +x is the THIRD base side, so +x is a
                             right-hander's pull field. Note that
                             `pitch_physics`'s module docstring says the
                             opposite ("positive to catcher's right") — the
                             code is what is right: `UmpireCamera.project`
                             negates x, and a right-hander's spine is at
                             `+bat_path.SPINE_OFFSET_FT`.
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


def pull_frame(world_vec, spin):
    """A world vector, restated pull-positive: `(pull, toward the pitcher, up)`.

    The conversion *into* the frame `spray_deg` is stated in, and the one place
    the handedness flip happens on the way in. World `+x` is the third-base
    side, which is a right-hander's pull field and a left-hander's opposite
    field, so only the lateral component changes sign.

    `bat_contact` uses it to stamp the ball's exit direction on the `Contact`,
    so everything downstream reads one handedness-free vector.
    """
    return (spin * world_vec[0], world_vec[1], world_vec[2])


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
