"""Where the bat is, in real feet, at every instant of a swing.

Same contract as `engine/contact_audio.py` and `ball_flight.py` — real feet
and seconds, no pygame, no game state, no rendering.

This module exists because the game's bat used to have a position but no
*motion*. The engine swung a rotated rectangle 120 px long by 50 px (contact)
or 25 px (power) tall, centred 30 px inboard of the aim point, at
`atan2(aim - pivot)` about a fixed pivot — and that rectangle existed for
exactly one frame, in the plane of the screen, with no depth. Every question a
timing replay wants to ask ("where was the barrel 40 ms ago", "how far in front
of the plate did they meet it") is a question about the two axes it did not
have. `bat_contact` sweeps this model instead now, and the rectangle is gone.

**The swing is a function of the player's inputs and nothing else** — aim and
handedness. Not of the pitch, and not of the swing type. This is the whole
shape of the module and it is worth stating as a prohibition, because the
previous model violated it: `swing()` took a `contact_depth_ft` read off the
*pitch's* own trajectory at bat arrival, and `hands_contact`, the bat's
bearing and tilt, the rotation radius, the eased profile's exponent and
therefore the entire load pose were all derived from it. The bat was modelled
as a consequence of the ball — the two-models-of-one-thing fault CLAUDE.md
tracks through the batted-ball code, in its purest form. What it drew: on a
swing 68 ms early the hands finished 5.13 ft from the spine (they orbit at
1.15) and the knob *started* four feet behind the plate on the wrong side of
it; 51 ms late, the knob started seven and a half feet toward third base.
Where and whether the barrel meets the ball is now an intersection of two
independent motions, and `bat_contact.resolve_contact` is what computes it.

Four things are worth knowing before changing anything here.

**The contact pose is closed by a stated bearing, and the hands move.** The
sweet spot lands on the cursor's ray, and the bat is a known length; that
leaves one condition to choose. It used to be "the knob sits on the engine's
aiming pivot", one fixed point for every pitch, 1.55 ft off the plate's
centreline. The bat is 2.46 ft from grip to sweet spot, so the only way to put
the sweet spot over the plate from there was to point the bat at the pitcher:
49 degrees past square on a middle pitch and anywhere from 19 to 71 across the
zone. `spray` then subtracted the 49 and rescaled the rest, and the replay drew
the real bat beside the remapped ball.

The condition now is that the bat has a bearing (`pose_bearing_rad`): a few
degrees past square on a middle pitch, further round on one inside, behind
square on one away. The hands go wherever that puts them — in toward the body
on an inside pitch, out over the plate on one away — which is what a hitter's
hands do. See `_contact_pose`.

**Contact depth is an output.** It follows from the bearing: the barrel leads
the hands by the bat's length times the sine of it. A middle pitch is met
about half a foot in front of the plate, an inside one over a foot out, and
one on the outside corner a couple of inches *behind* the plate's front edge.
So depth can be negative, and nothing here or downstream may clamp it. Nothing
may re-derive it from the ball either.

**A cursor is a ray, not a point.** The camera is a perspective projection
from 30 ft behind the plate, so the same pixel is a different world position at
every depth. `_unproject` is where that is handled, and it is not a detail: the
barrel meets the ball out in front of (or behind) the plate, where a tracked
ball sits measurably higher or lower on screen than it will at the plate,
against a bat and ball that are 2.75 inches of tolerance between them.

**The swing is modelled hands-first: a small hand arc, and a bat swung about
the hands.** The hands ride a curve authored in the *rotating body frame* — a
radius that tightens into the slot and extends through contact, a height
working down off the back shoulder — from a load position that is a constant
of the stance to the contact pose the aim solved. The bat's attitude about
the hands
(bearing wrapped by the turn plus a decaying `LAG_DEG`, tilt easing off
`LOAD_BAT_ANGLE_DEG`) is what carries the barrel down off the shoulder and
around. Modelled this way the rounded side-view loop and the overhead spiral
*emerge*.

**Bat speed is a calibration target, not a shape parameter.** The game has no
bat-speed input — no swing-strength control, no per-batter attribute — so the
barrel arrives at contact at a stated MLB-average speed on every swing, and the
angular profile's exponent is *solved* from that. Stating the speed and
deriving the exponent keeps the calibration visible; the other way round hides
a real number behind a shape parameter.

**Not modelled: a tilted swing plane.** The body turns about a vertical axis
and the hands stay low (`HAND_CONTACT_HEIGHT_FT`), so the bat is flatter than a
real one — a real bat is 25 to 30 degrees barrel-down on a belt-high pitch.
Raising the hands alone does not fix it: a tilted bat swept about a vertical
axis traces a cone, and sliding along it changes the vertical offset in the
direction that cancels the turn timing should put on the ball. It needs the
plane tilted with the bat, and it is the known follow-up to this model.
"""

import math

from strikefactor.utils.pitch_physics import DEFAULT_CAMERA

MPH_PER_FT_S = 0.681818


# --- Timing --------------------------------------------------------------

# Initiation to contact. This is the `+ 150` that `pitch_simulation` and
# `hit_outcome_manager` both hard-code; it is the single most load-bearing
# number in the swing system and it lives here now.
SWING_DURATION_MS = 150
SWING_DURATION_S = SWING_DURATION_MS / 1000.0

# The follow-through. Not a second authored arc: the bat carries its contact
# angular speed past the ball and decelerates to a stop over this long, so how
# far it wraps is a *consequence* of how fast it was going. Drawn by the replay
# and swept by `bat_contact`, which is why a swing that arrives early can still
# catch a ball on the way through.
EXTENSION_DURATION_MS = 70
EXTENSION_DURATION_S = EXTENSION_DURATION_MS / 1000.0
TOTAL_DURATION_S = SWING_DURATION_S + EXTENSION_DURATION_S
# Phase (u) at the end of the extension. u is time in units of the swing, so
# it runs past 1 and the whole model is written in it.
U_MAX = TOTAL_DURATION_S / SWING_DURATION_S


# --- The bat -------------------------------------------------------------

BAT_LENGTH_FT = 2.79          # 33.5 in, the common MLB length
# How much bat sits outboard of the point that meets the ball. It is where the
# engine's old rectangle put it: the cursor sat 30 px inboard of the 120 px
# box's centre, so 30 px of bat lay beyond the aim point.
CURSOR_TO_TIP_FT = 0.33
# Grip to the point that meets the ball — the lever every attitude change
# swings on, since the bat pivots about the hands.
HANDS_TO_SWEET_SPOT_FT = BAT_LENGTH_FT - CURSOR_TO_TIP_FT
SWEET_SPOT_FRAC = HANDS_TO_SWEET_SPOT_FT / BAT_LENGTH_FT

# A bat is a *swept sphere of varying radius*, sampled here as fraction of the
# way from the knob to the tip against the real radius there in inches. An MLB
# bat is 2.61 in across the barrel and under an inch through the handle, and
# that taper is essentially the whole of why a bat is recognisable in
# silhouette — and, more to the point, why a ball caught on the handle is not
# the same event as one caught on the barrel.
#
# It lives here rather than in the renderer because `bat_contact` sweeps these
# same radii against the ball. One profile, or the bat the player is graded by
# is a different object from the bat they are shown.
#
# The stations are placed to keep the taper **concave**, which is the shape's
# whole signature: a thin handle held most of the way, a quick flare, and a
# barrel that is then very nearly parallel-sided. Spread the same radii evenly
# and the flare straightens into a cone.
BAT_PROFILE_IN = (
    (0.00, 1.05),   # knob, ~2.1 in across
    (0.02, 1.05),
    (0.05, 0.48),   # handle, a shade under 1 in and held to a third of the way
    (0.36, 0.50),
    (0.45, 0.58),   # into the taper
    (0.52, 0.72),
    (0.60, 0.94),
    (0.67, 1.13),
    (0.73, 1.24),
    (0.80, 1.29),   # barrel, 2.6 in across — the MLB maximum
    (1.00, 1.30),
)


def _bat_profile_segments():
    """`(x_hi, r_lo_ft, slope_ft_per_frac, x_lo)` per segment of the profile.

    The inches-to-feet division and the segment slope are the same numbers on
    every call, and `bat_contact` asks for a radius ~200k times per swing, so
    they are worked out once at import instead of inside that loop.
    """
    segments = []
    prev_x, prev_r = BAT_PROFILE_IN[0]
    for x, r in BAT_PROFILE_IN[1:]:
        span = x - prev_x
        lo_ft = prev_r / 12.0
        slope = 0.0 if span <= 0.0 else (r / 12.0 - lo_ft) / span
        segments.append((x, lo_ft, slope, prev_x))
        prev_x, prev_r = x, r
    return tuple(segments)


_BAT_SEGMENTS = _bat_profile_segments()
BAT_KNOB_RADIUS_FT = BAT_PROFILE_IN[0][1] / 12.0
BAT_TIP_RADIUS_FT = BAT_PROFILE_IN[-1][1] / 12.0

# The profile describes a bat whose declared length includes its rounded
# ends.  The centres of the two end spheres therefore sit one radius in from
# `BatState.knob_ft` / `barrel_ft`; using the endpoints as sphere centres makes
# the collision bat longer than the bat drawn on screen by both end radii.
BAT_SOLID_SPAN_FT = BAT_LENGTH_FT - BAT_KNOB_RADIUS_FT - BAT_TIP_RADIUS_FT

# `Contact.along` is measured over the solid's centre span.  Keep the quality
# peak at the authored sweet spot rather than silently moving it inward when
# the end centres are inset.
CONTACT_SWEET_SPOT_FRAC = (
    (HANDS_TO_SWEET_SPOT_FT - BAT_KNOB_RADIUS_FT) / BAT_SOLID_SPAN_FT
)


def bat_radius_ft(frac):
    """The bat's radius in feet at `frac` of the way from knob to tip."""
    f = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
    for x_hi, lo_ft, slope, x_lo in _BAT_SEGMENTS:
        if f <= x_hi:
            return lo_ft + slope * (f - x_lo)
    return BAT_TIP_RADIUS_FT


def bat_solid_axis(state):
    """Return the centreline endpoints of the physical swept-sphere bat.

    `BatState.knob_ft` and `barrel_ft` are the outside ends of a 33.5-inch
    bat.  A sphere centred directly on either point extends the collision
    solid beyond that length.  Insetting the centres by their radii gives the
    collision solver and renderer one explicit, shared endpoint convention.
    """
    axis = tuple(state.barrel_ft[i] - state.knob_ft[i] for i in range(3))
    length = math.sqrt(sum(v * v for v in axis))
    if length <= 1e-12:
        return state.knob_ft, state.barrel_ft
    unit = tuple(v / length for v in axis)
    lo = tuple(state.knob_ft[i] + unit[i] * BAT_KNOB_RADIUS_FT
               for i in range(3))
    hi = tuple(state.barrel_ft[i] - unit[i] * BAT_TIP_RADIUS_FT
               for i in range(3))
    return lo, hi


def bat_solid_point(state, frac):
    """Centre and radius of the bat solid at profile fraction ``frac``."""
    f = max(0.0, min(1.0, frac))
    lo, hi = bat_solid_axis(state)
    centre = tuple(lo[i] + (hi[i] - lo[i]) * f for i in range(3))
    return centre, bat_radius_ft(f)


# --- The body ------------------------------------------------------------

# Distance from the plate's centreline to the batter's rotational axis, on
# their own side. The one fixed anchor of the whole kinematic chain: the
# hands orbit it, and the rotation radius that calibrates bat speed is
# measured from it.
SPINE_OFFSET_FT = 2.9

# Where that axis sits in depth: level with the middle of the plate, which is
# where a hitter stands. It was level with the plate's front edge while the
# hands were pinned 1.55 ft off the centreline, and that only worked because
# they were pinned: the hands meet a middle pitch about 2.4 ft off the
# centreline now and come in to 2.9 on an inside one, which with the axis at
# the front edge is an orbit of half a foot shrinking to nothing. Set back
# here the hands stay 1.1 ft in front of the body wherever they are.
SPINE_DEPTH_FT = -0.7

# The body's turn from initiation to contact. Bearing sweep beyond this comes
# from the lag term below, so the barrel's total wrap is ARC + LAG.
SWING_ARC_DEG = 120.0
SWING_ARC_RAD = math.radians(SWING_ARC_DEG)

# Upward attack angle of the barrel's path *through contact*. The swing plane
# is a tilted circle about the spine, so its dip term takes the whole bat down
# by r*tan(phi)*sin(theta_plane): at contact that is r*tan(phi)*w of climb
# against a horizontal r*w — exactly phi, since every other term is
# momentarily still there. A stated assumption, not a measurement: the game
# has no attack-angle input, and the replay must never present this as
# something the player did.
ATTACK_ANGLE_DEG = 10.0
ATTACK_ANGLE_RAD = math.radians(ATTACK_ANGLE_DEG)


# --- The hands -----------------------------------------------------------

# Where the hands are at contact, in depth and height. Authored rather than
# solved: a hitter's hands are a few inches out in front of the plate and
# just below the belt at contact whatever the pitch was. Where they are
# *laterally* is the part that is solved — see `_contact_pose`.
#
# These two were a screen pixel once (`PIVOT_PX`, the point the engine's
# contact rectangle rotated about, restated from `HitOutcomeManager.rhpos`),
# and this is the same point said in feet.
#
# The height is lower than a real hitter's, on purpose: see "Not modelled" in
# the module docstring before raising it.
HAND_CONTACT_DEPTH_FT = 0.40
HAND_CONTACT_HEIGHT_FT = 2.93


# --- The bat's bearing at contact ------------------------------------------
# How far past square the bat is when the barrel arrives, as a function of
# where the player aimed across the plate. Zero is the bat lying straight
# across the plate; positive is the barrel further round toward the pitcher.
#
#   bearing = POSE_MEAN_DEG
#             + POSE_SPAN_DEG * tanh(POSE_GAIN_DEG_PER_FT * x_in / POSE_SPAN_DEG)
#
# with `x_in` the aim's distance inside of the plate's centreline, in feet.
#
# These are the three constants `spray` used to hold (`LEAGUE_MEAN_DEG`,
# `LOCATION_GAIN`, `LOCATION_SPAN_DEG`), moved to where they are physically
# true. There they remapped the direction of a ball struck by a bat that was
# 49 degrees past square; here they say where the bat is, and
# `bat_ball_collision` says where the ball goes off it.
#
#   * The mean is the bearing a middle pitch is met at, a few degrees past
#     square. The ball leaves further round than the bat faces, so a middle
#     pitch struck on time goes about 6 degrees to the pull side of centre.
#   * The gain is how fast the bat comes round as the pitch moves inside,
#     through the middle of the plate. It is what spreads contact across the
#     field, and it is bounded from above by a constraint, not a fit: an
#     on-time swing has to be fair at every strike-zone location with a few
#     degrees to spare (`test_an_on_time_swing_is_fair_anywhere_in_the_zone`).
#     The high inside corner is the one that binds.
#   * The span is where the response saturates. It bends the response by
#     about a fifth at the edge of the zone, which is what keeps the corners
#     fair at this gain, and past the zone it means a ball the hitter reaches
#     a long way for still has a bat a person could be holding.
#
# Fitted together through the collision, over the canonical player model
# (`tools/calibrate_contact.py`): the corner constraint first, then the
# pull / centre / opposite split of fair contact, which these hold where it
# was (30 / 45 / 25 against MLB's 40 / 35 / 25). Half of all contact is on
# time once the assist has run, so its direction is the pitch's location
# alone, and a steeper gain to spread it would foul the corners.
POSE_MEAN_DEG = 3.25
POSE_GAIN_DEG_PER_FT = 30.0
POSE_SPAN_DEG = 21.0

# How far the bat may tilt out of level at contact, either way. Past it the
# barrel falls short of the cursor rather than the bat standing on end.
MAX_CONTACT_TILT_DEG = 60.0
MAX_CONTACT_TILT_RAD = math.radians(MAX_CONTACT_TILT_DEG)

# How far the hands may be from the body at contact, measured across the
# plate from the spine. `HAND_REACH_FT` is toward the plate: arms extended
# after a ball away. `HAND_TUCK_FT` is the other way: hands pulled in on a
# ball inside until they are level with the body's own axis and a little past
# it. Both in feet, both bounds on a body rather than dials.
#
# Inside the strike zone neither binds. Outside it the solved hands would run
# away — out over the plate's far edge on a ball a foot off it — so past the
# bound the bat honestly falls short of the cursor and the sweep whiffs.
HAND_REACH_FT = 2.0
HAND_TUCK_FT = 0.3

# Passes of the fixed point in `_contact_pose`. Each one shrinks the error by
# about a hundredfold, so this is far below anything a pixel could show.
POSE_SOLVE_PASSES = 5

# Hand height at initiation — up by the back shoulder. An *absolute* height,
# like LOAD_BAT_ANGLE_DEG below: a low pitch costs the hands a longer drop,
# it does not lower where they start.
LOAD_HANDS_HEIGHT_FT = 4.6

# Where the hands are at initiation, across the ground from the spine: by the
# back shoulder, a little toward the plate and the same toward the catcher.
# **A constant of the stance.** Every swing starts here whatever it is aimed
# at, and `BatSwing` solves how the hands get from here to the contact pose.
#
# It used to be the contact position turned back through the swing and scaled
# (`HAND_RADIUS_B`, `HAND_LEAD_DEG`), which was only a constant because the
# hands' contact position was one. Once the hands move with the pitch, that
# rule starts the swing somewhere different for every aim — a foot and a half
# apart between an inside pitch and one away.
LOAD_HANDS_IN_FT = 0.65
LOAD_HANDS_BACK_FT = 0.65

# How far the hands tuck in toward the body between the load and contact, as a
# share of their distance from the spine at contact: the slot. The radius runs
# from the load's to contact's along
#   radius = r_contact + (r_load - r_contact)*load - HAND_SLOT*r_contact*load*(1 - load)
# Stated in the *load* (below) rather than in time, for two reasons: it is
# flat at contact, so the hands' radial motion cannot disturb the attack angle
# the plane owns; and the loop it describes — hands tighten into the slot,
# then extend through the ball — is a function of how far the body still has
# to turn, not of the clock.
HAND_SLOT = 0.64
# How much further the hands reach in the follow-through, and how much they
# rise with it. Squared in the extension's own progress, so both are flat at
# contact for the same reason.
EXTENSION_REACH = 0.10
EXTENSION_RISE_FT = 0.55


# --- The load ------------------------------------------------------------
# Where the bat is when the swing starts, expressed as attitudes given up on
# the way to contact. All stated assumptions in the same sense as
# ATTACK_ANGLE_DEG: the game has no load input either.

# The bat's angle above horizontal at initiation, barrel high. Real launch
# positions run from about 45° (flat) to 75° (near vertical); this is the
# middle. Absolute, not an offset from the contact attitude, which is what
# makes a low pitch cost the barrel a bigger drop than a high one.
LOAD_BAT_ANGLE_DEG = 60.0
LOAD_BAT_ANGLE_RAD = math.radians(LOAD_BAT_ANGLE_DEG)

# How far the barrel's bearing is wrapped *beyond* the body's turn at
# initiation — the lag a swing releases through the zone. It decays with
# rotation remaining like every other load term, so it is flat at contact and
# can disturb neither the attack angle nor the speed calibration. Kept
# moderate: with the body's 120° it puts the total wrap at 150°, and much
# past that the barrel comes all the way around to pointing forward at load.
LAG_DEG = 30.0
LAG_RAD = math.radians(LAG_DEG)

# How much the barrel tips up as the hitter wraps the bat past contact. The
# wrists roll over in the follow-through; without it the bat sweeps round
# frozen at its contact attitude, which reads as a rigid pole rather than a
# swing finishing.
EXTENSION_ROLL_DEG = 28.0
EXTENSION_ROLL_RAD = math.radians(EXTENSION_ROLL_DEG)

# How the load is given up: as a function of the rotation *still to go*,
# never of the clock. The bat gets on plane because the body has turned, and
# tying it to time instead drops the barrel before the swing has begun, since
# the eased rotation leaves most of the turn still to come at half time.
#
# The exponent has to be at least 2, or the load terms are still moving as
# the ball is met and the attack angle at contact is not ATTACK_ANGLE_DEG at
# all — the zero-rate-at-contact property holds for any power >= 2, since
# d(load)/dt = (d(load)/dtheta) * theta' and the theta-derivative vanishes at
# theta = 0. Exactly 2, not 3: at power 3 the tilt is dead by 40° out and the
# barrel's turnaround draws as a sharp V, the artifact the hands-first model
# exists to fix — the loop only rounds if something is still moving
# vertically there.
ON_PLANE_EASE = 2.0

# MLB average barrel speed at contact. Not a free dial: it is what the
# angular profile's exponent is solved for, per swing, in `BatSwing`.
PEAK_BAT_SPEED_MPH = 72.0
PEAK_BAT_SPEED_FT_S = PEAK_BAT_SPEED_MPH / MPH_PER_FT_S

# Sanity rails on the solved exponent. The peak-to-mean angular speed ratio
# *is* k, so past ~3 the swing reads as a bat that stands still and then
# teleports; the floor only keeps the profile a swing, since k must stay above
# 1 or the speed would peak before contact. With the rotation radius now a
# function of aim alone these sit at about 2.0–2.6 over the plate and should
# never bind — a test says so, and a swing that rails is a sign the contact
# pose has come loose again.
EASE_K_MIN = 1.05
EASE_K_MAX = 3.0


# --- Screen pixels to feet at the plate ----------------------------------

def _to_ft(screen_xy):
    """A screen point at the plate, in world feet. Thin alias for the camera."""
    return DEFAULT_CAMERA.screen_to_world_at_plate(screen_xy[0], screen_xy[1])


# --- The contact pose -----------------------------------------------------

def _unproject(plate_xz, depth_ft):
    """The world point a cursor names, at `depth_ft` rather than at the plate.

    The game's camera is a *perspective* projection from 30 ft behind the
    plate, so a screen pixel is a ray and not a point: the same cursor is a
    different world position at every depth, spreading with distance. Callers
    hand this module `screen_to_world_at_plate(cursor)`, which is the ray's
    intersection with `y = 0`; this walks it back out to where the bat is.

    It matters more than the scale suggests. The barrel meets the ball out in
    front of the plate — over a foot out on a pitch inside — where a tracked
    ball sits an inch or two higher on the screen than it will at the plate,
    and a bat and a ball together are only 2.75 inches of tolerance. Resolving
    the aim at the plate and the ball at contact spends most of that on a bias
    the player has no way to correct. When the barrel met everything two feet
    out, it showed up as every swing scoring under 0.5 for quality.
    """
    scale = (depth_ft + DEFAULT_CAMERA.cam_dist) / DEFAULT_CAMERA.cam_dist
    cam_h = DEFAULT_CAMERA.cam_height
    return (plate_xz[0] * scale, cam_h + (plate_xz[1] - cam_h) * scale)


def to_plate_frame(point_xz, depth_ft):
    """The inverse of `_unproject`: a world point at `depth_ft` expressed as
    the plate-frame aim that names it.

    Callers hand `swing()` an aim resolved at the plate, because that is what
    `screen_to_world_at_plate` gives them and what the cursor means. When a
    caller instead knows where it wants the barrel *at contact* — the replay
    does, since it places the bat by the offset the engine measured there —
    this is how that becomes an aim.
    """
    scale = (depth_ft + DEFAULT_CAMERA.cam_dist) / DEFAULT_CAMERA.cam_dist
    cam_h = DEFAULT_CAMERA.cam_height
    return (point_xz[0] / scale, cam_h + (point_xz[1] - cam_h) / scale)


def pose_bearing_rad(x_in_ft):
    """How far past square the bat is at contact, in radians.

    `x_in_ft` is the aim's distance inside of the plate's centreline: positive
    toward the batter, for either hand. See the note over `POSE_MEAN_DEG`.

    A `tanh`, so it has slope exactly `POSE_GAIN_DEG_PER_FT` over the middle
    of the plate and saturates smoothly either side. Smooth matters: the
    bearing decides where the ball goes, and a clamp would stack every aim
    past it onto one direction.
    """
    return math.radians(POSE_MEAN_DEG + POSE_SPAN_DEG * math.tanh(
        POSE_GAIN_DEG_PER_FT * x_in_ft / POSE_SPAN_DEG))


def _contact_pose(aim_ft, handedness):
    """The bat at the instant the barrel arrives, from the aim alone.

    Returns `(hands_ft, axis3)` — the hands in world feet and the bat's unit
    long axis, knob to barrel.

    Three conditions fix it. The sweet spot is on the cursor's ray. The bat is
    `HANDS_TO_SWEET_SPOT_FT` from grip to sweet spot. And the bat has the
    bearing `pose_bearing_rad` gives this aim. The hands' depth and height are
    authored, so their lateral position is what the three solve for:

        depth = HAND_CONTACT_DEPTH_FT + L * cos(tilt) * sin(bearing)
        hands = sweet(depth) - L * axis(bearing, tilt)

    The tilt is whatever spans the height between the hands and the ray, and
    the ray's height depends on the depth, so the two are settled together by
    a short fixed point.

    **Contact depth is an output.** It is where the barrel is when the bat has
    that bearing with the hands that far out front: over a foot in front of
    the plate on a pitch inside, about half a foot on one down the middle, and
    slightly *behind* the plate's front edge on the outside corner. Negative
    is a real answer here and is not clamped.

    **The hands are bounded, and the bearing is not.** Past `HAND_REACH_FT` or
    `HAND_TUCK_FT` the hands stop and the barrel falls short of the cursor, as
    it does past `MAX_CONTACT_TILT_DEG` in height. The bat's attitude is
    unaffected by any of the three, so it stays continuous in the aim however
    absurd the aim is.
    """
    spin = 1.0 if handedness == "R" else -1.0
    bearing = pose_bearing_rad(spin * aim_ft[0])
    cos_b, sin_b = math.cos(bearing), math.sin(bearing)
    length = HANDS_TO_SWEET_SPOT_FT
    max_sin = math.sin(MAX_CONTACT_TILT_RAD)

    depth = HAND_CONTACT_DEPTH_FT
    sweet_x = sin_t = 0.0
    cos_t = 1.0
    for _ in range(POSE_SOLVE_PASSES):
        sweet_x, sweet_z = _unproject(aim_ft, depth)
        sin_t = max(-max_sin, min(max_sin,
                                  (sweet_z - HAND_CONTACT_HEIGHT_FT) / length))
        cos_t = math.sqrt(1.0 - sin_t * sin_t)
        depth = HAND_CONTACT_DEPTH_FT + length * cos_t * sin_b

    axis3 = (-spin * cos_b * cos_t, sin_b * cos_t, sin_t)
    # The hands' distance from the centreline, on the batter's own side.
    hands_in = spin * sweet_x + length * cos_b * cos_t
    hands_in = max(SPINE_OFFSET_FT - HAND_REACH_FT,
                   min(SPINE_OFFSET_FT + HAND_TUCK_FT, hands_in))
    return (spin * hands_in, HAND_CONTACT_DEPTH_FT,
            HAND_CONTACT_HEIGHT_FT), axis3


# --- The swing -----------------------------------------------------------

class BatState:
    """The bat at one instant: both ends and the point that meets the ball.

    `speed_mph` is computed on demand. It is a two-sided numerical derivative,
    so producing it eagerly cost three poses per state where one was wanted —
    and `bat_contact`'s sweep builds hundreds of states per swing and reads
    the speed of exactly the one it settles on.
    """

    __slots__ = ("knob_ft", "barrel_ft", "sweet_spot_ft", "_swing", "_u",
                 "_speed_mph")

    def __init__(self, knob_ft, barrel_ft, sweet_spot_ft, swing=None, u=0.0):
        self.knob_ft = knob_ft
        self.barrel_ft = barrel_ft
        self.sweet_spot_ft = sweet_spot_ft
        self._swing = swing
        self._u = u
        self._speed_mph = None

    @property
    def speed_mph(self):
        """Sweet-spot speed at this instant, in mph."""
        if self._speed_mph is None:
            self._speed_mph = (0.0 if self._swing is None
                               else self._swing._speed_at(self._u))
        return self._speed_mph


# Half-width of the central difference `point_velocity_at` takes. The barrel
# turns about a third of a degree in this long, so the chord is the tangent to
# well inside a tenth of a percent.
VELOCITY_STEP_S = 0.00025


class _SwingTracks:
    """The sampling helpers shared by a swing and its translated form.

    Both are written purely in terms of `state_at`, so a subclass gets the
    right states by defining that alone. They lived as byte-identical copies
    in each class, which meant a new track helper silently missed the
    translated variant — and that variant is the *assisted* path, so the gap
    only showed at non-zero difficulty assist.
    """

    def barrel_track(self, n=48):
        """`n` states evenly spaced from initiation to contact."""
        if n < 2:
            n = 2
        return [self.state_at(SWING_DURATION_S * i / (n - 1)) for i in range(n)]

    def full_track(self, n=64):
        """`n` states over the whole swing, follow-through included."""
        if n < 2:
            n = 2
        return [self.state_at(TOTAL_DURATION_S * i / (n - 1)) for i in range(n)]

    def point_velocity_at(self, t_s, frac):
        """Velocity, in feet per second, of one point of the bat at `t_s`.

        `frac` is the profile fraction `bat_solid_point` takes — 0 at the knob
        end of the solid, 1 at the tip — so it is `Contact.along`, and this is
        how fast the wood that met the ball was moving and which way. That is
        the bat's half of `bat_ball_collision`.

        Differentiated numerically from `state_at`, for the reason `_speed_at`
        is: it reports what the drawn bat does, load terms included. The bat
        is slower at the handle than at the barrel and moving in a slightly
        different direction, which is why this is asked of a point and not of
        the swing.
        """
        lo = max(0.0, t_s - VELOCITY_STEP_S)
        hi = min(TOTAL_DURATION_S, t_s + VELOCITY_STEP_S)
        if hi <= lo:
            return (0.0, 0.0, 0.0)
        a, _ = bat_solid_point(self.state_at(lo), frac)
        b, _ = bat_solid_point(self.state_at(hi), frac)
        return tuple((b[i] - a[i]) / (hi - lo) for i in range(3))


class BatSwing(_SwingTracks):
    """A swing, sampleable at any time from initiation through the finish.

    Built from the player's aim and handedness and nothing else. Hands-first:
    the knob is *authored* and the barrel follows.

      * the **hands** start by the back shoulder, the same place on every
        swing, and orbit the spine axis on a radius that tightens into the
        slot and extends through the ball, working down from
        `LOAD_HANDS_HEIGHT_FT` to the contact grip as the body turns;
      * the **bat's attitude** about the hands — bearing wrapped by the turn
        remaining plus the lag, tilt easing off `LOAD_BAT_ANGLE_DEG` — is
        what carries the barrel down off the shoulder and around;
      * the **plane** moves the whole assembly by `r*tan(phi)*sin(theta_p)`,
        so the barrel bottoms out a quarter turn before contact and is met on
        the way up at exactly `ATTACK_ANGLE_DEG`, since every other term is
        momentarily still there.

    `state_at(SWING_DURATION_S)` is pinned: the sweet spot sits on the
    cursor's ray and the bat has the bearing `pose_bearing_rad` gives the aim
    (`_contact_pose`). Its *depth*, `contact_depth_ft`, is an output, and it
    can be negative.
    """

    def __init__(self, aim_ft, handedness):
        self.aim_ft = tuple(aim_ft)
        self.handedness = "R" if handedness == "R" else "L"
        self.spin = 1.0 if self.handedness == "R" else -1.0
        self.bat_speed_mph = PEAK_BAT_SPEED_MPH
        self.spine_xy = (SPINE_OFFSET_FT * self.spin, SPINE_DEPTH_FT)

        self.hands_contact, contact_axis = _contact_pose(aim_ft, self.handedness)
        self.contact_axis = contact_axis

        self.contact_ft = tuple(
            self.hands_contact[i] + HANDS_TO_SWEET_SPOT_FT * contact_axis[i]
            for i in range(3))
        self.contact_depth_ft = self.contact_ft[1]

        self.contact_tilt_rad = math.asin(
            max(-1.0, min(1.0, contact_axis[2])))
        bearing_mag = math.hypot(contact_axis[0], contact_axis[1])
        self.contact_bearing = (
            (contact_axis[0] / bearing_mag, contact_axis[1] / bearing_mag)
            if bearing_mag > 1e-9 else (float(self.spin), 0.0))

        # The hands' own orbit at contact, which the radius profile scales.
        hrel = (self.hands_contact[0] - self.spine_xy[0],
                self.hands_contact[1] - self.spine_xy[1])
        self.hand_radius_ft = math.hypot(*hrel)
        self.hand_bearing = ((hrel[0] / self.hand_radius_ft,
                              hrel[1] / self.hand_radius_ft)
                             if self.hand_radius_ft > 1e-9 else (0.0, -1.0))

        # And where they start, which is the stance's and not this swing's.
        # Turning the contact bearing back through the whole arc lands the
        # hands somewhere that depends on the aim; `_hand_lead` is the extra
        # turn, given up with the load, that lands them on the stance instead.
        # Worked in the batter's own frame (lateral flipped by `spin`), so the
        # two hands are mirror images by construction.
        self.load_hand_radius_ft = math.hypot(LOAD_HANDS_IN_FT,
                                              LOAD_HANDS_BACK_FT)
        contact_angle = math.atan2(hrel[1], self.spin * hrel[0])
        load_angle = math.atan2(-LOAD_HANDS_BACK_FT, -LOAD_HANDS_IN_FT)
        lead = load_angle - contact_angle - SWING_ARC_RAD
        self._hand_lead = math.atan2(math.sin(lead), math.cos(lead))

        # The rotation radius bat speed is calibrated on: spine axis to the
        # contact point. At contact every load term is flat, so the bat is
        # momentarily rigid about the spine and the sweet spot's speed is
        # w * r (times sec(phi) for the plane's climb — hence the cos in the
        # solve, so the *total* barrel speed is the stated 72).
        self.turn_radius_ft = math.hypot(self.contact_ft[0] - self.spine_xy[0],
                                         self.contact_ft[1] - self.spine_xy[1])
        k = (PEAK_BAT_SPEED_FT_S * math.cos(ATTACK_ANGLE_RAD)
             / max(self.turn_radius_ft, 1e-6)) * SWING_DURATION_S / SWING_ARC_RAD
        self.ease_k = max(EASE_K_MIN, min(EASE_K_MAX, k))

        # The follow-through carries the contact angular speed and decelerates
        # to a stop, so how far it wraps is a consequence rather than a
        # constant. d(theta)/du at contact is ARC*k; over the extension's
        # `s_max` of phase that integrates to half of ARC*k*s_max.
        self._ext_span = U_MAX - 1.0
        self._ext_rate = SWING_ARC_RAD * self.ease_k
        self.extension_arc_rad = 0.5 * self._ext_rate * self._ext_span

    # -- the angular profile ----------------------------------------------

    def _turn_remaining(self, u):
        """Rotation still to go at phase u, in radians. 0 at contact.

        Positive before contact and negative after, in the batter's own
        rotational sense: `spin` is +1 for a right-handed batter and -1 for a
        left-hander. Without it both hands load their barrel toward the
        *pitcher*, which is the finish of a swing rather than its start.
        """
        if u <= 1.0:
            return self.spin * SWING_ARC_RAD * (1.0 - u ** self.ease_k)
        s = min(self._ext_span, u - 1.0)
        return -self.spin * self._ext_rate * (s - 0.5 * s * s / self._ext_span)

    def _load(self, theta):
        """How much of the load is left, 1 at initiation and 0 at contact.

        A function of the rotation still to go, not of the clock, and flat at
        contact so nothing here disturbs the attack angle. Clamped at zero
        past contact: the load is given up once and does not come back, or
        the follow-through would un-swing the bat.
        """
        remaining = max(0.0, theta * self.spin)
        return (remaining / SWING_ARC_RAD) ** ON_PLANE_EASE

    def _extension(self, theta):
        """Progress through the follow-through, 0 at contact and 1 at the end."""
        if self.extension_arc_rad <= 1e-9:
            return 0.0
        past = max(0.0, -theta * self.spin)
        return min(1.0, past / self.extension_arc_rad)

    @staticmethod
    def _turn(vec_xy, theta):
        """A ground vector turned by `theta` about the vertical."""
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        return (vec_xy[0] * cos_t - vec_xy[1] * sin_t,
                vec_xy[0] * sin_t + vec_xy[1] * cos_t)

    # -- the kinematic chain ------------------------------------------------

    def _pose(self, u):
        """Knob position and bat axis at phase u — the whole chain."""
        theta = self._turn_remaining(u)
        load = self._load(theta)
        ext = self._extension(theta)

        # The plane is a circle about the spine tilted by the attack angle, so
        # it takes the whole assembly — hands included — below the line of
        # nodes on the way in and above it on the way out. Its phase is the
        # turn already made, which is why it bottoms out a quarter turn before
        # contact rather than sinking all the way there.
        plane = (self.turn_radius_ft * math.tan(ATTACK_ANGLE_RAD)
                 * math.sin(-self.spin * theta))

        # The hands: their orbit turned back by the rotation remaining, with
        # the radius tightening into the slot and extending through the ball,
        # and their height eased up toward the load. At `load = 1` this is the
        # stance's load position exactly, and at contact the solved pose.
        sx, sy = self.spine_xy
        bearing = self._turn(self.hand_bearing,
                             theta + self.spin * self._hand_lead * load)
        radius = (self.hand_radius_ft
                  + (self.load_hand_radius_ft - self.hand_radius_ft) * load
                  - HAND_SLOT * self.hand_radius_ft * load * (1.0 - load)
                  + EXTENSION_REACH * self.hand_radius_ft * ext * ext)
        knob = (sx + radius * bearing[0],
                sy + radius * bearing[1],
                self.hands_contact[2]
                + (LOAD_HANDS_HEIGHT_FT - self.hands_contact[2]) * load
                + EXTENSION_RISE_FT * ext * ext
                + plane)

        # The bat about the hands: the bearing carries the body's remaining
        # turn plus the lag still wrapped, the tilt is the load's plus the
        # wrists rolling over past contact. One unit vector, so the bat stays
        # one bat long.
        wrap = theta + self.spin * LAG_RAD * load
        bx, by = self._turn(self.contact_bearing, wrap)
        tilt = (self.contact_tilt_rad
                + (LOAD_BAT_ANGLE_RAD - self.contact_tilt_rad) * load
                + EXTENSION_ROLL_RAD * ext * ext)
        cos_tilt, sin_tilt = math.cos(tilt), math.sin(tilt)
        return knob, (bx * cos_tilt, by * cos_tilt, sin_tilt)

    def _sweet_at(self, u):
        knob, axis = self._pose(u)
        return tuple(knob[i] + axis[i] * HANDS_TO_SWEET_SPOT_FT
                     for i in range(3))

    def state_at(self, t_s):
        """The bat at `t_s` seconds after the swing was initiated.

        Defined through the follow-through, not just to contact: a swing that
        arrives early is still moving when the ball gets there, and both the
        replay and `bat_contact` need to see it.
        """
        u = max(0.0, min(U_MAX, t_s / SWING_DURATION_S))
        knob, axis = self._pose(u)
        return BatState(
            knob_ft=knob,
            barrel_ft=tuple(knob[i] + axis[i] * BAT_LENGTH_FT
                            for i in range(3)),
            sweet_spot_ft=tuple(knob[i] + axis[i] * HANDS_TO_SWEET_SPOT_FT
                                for i in range(3)),
            swing=self,
            u=u,
        )

    def _speed_at(self, u):
        """Sweet-spot speed at phase u, in mph.

        Differentiated numerically from the chain itself rather than stated
        as w * r, so it reports whatever the drawn barrel actually does —
        including the load terms' contribution mid-swing, which w * r would
        silently omit.
        """
        h = 1.0 / 1024.0
        a = max(0.0, u - h)
        b = min(U_MAX, u + h)
        dt = (b - a) * SWING_DURATION_S
        if dt <= 0.0:
            return 0.0
        pa, pb = self._sweet_at(a), self._sweet_at(b)
        return math.dist(pa, pb) / dt * MPH_PER_FT_S

class TranslatedBatSwing(_SwingTracks):
    """A swing moved rigidly in x/z by a bounded contact assist.

    Difficulty forgiveness must be visible without changing what kind of
    swing the player made. Rebuilding from a shifted aim changes the contact
    pose's bearing and therefore the batted-ball direction; translating the
    existing kinematic chain preserves its attitude, speed and timing while
    putting the physical bat where the collision solver placed it.
    """

    def __init__(self, base, shift_ft):
        self.base = base
        self.spatial_shift_ft = tuple(shift_ft)
        self.aim_ft = base.aim_ft
        self.handedness = base.handedness
        self.spin = base.spin
        self.contact_axis = base.contact_axis
        self.contact_depth_ft = base.contact_depth_ft
        self.contact_ft = self._shift_point(base.contact_ft)

    def _shift_point(self, point):
        dx, dz = self.spatial_shift_ft
        return point[0] + dx, point[1], point[2] + dz

    def state_at(self, t_s):
        state = self.base.state_at(t_s)
        return BatState(
            knob_ft=self._shift_point(state.knob_ft),
            barrel_ft=self._shift_point(state.barrel_ft),
            sweet_spot_ft=self._shift_point(state.sweet_spot_ft),
            swing=self,
            u=state._u,
        )

    def _speed_at(self, u):
        return self.base._speed_at(u)


def translated_swing(base, shift_ft):
    """Return `base` visibly displaced by `(x, z)` feet.

    A zero shift returns the original object so unassisted swings do not pay
    for a wrapper or acquire a second identity.
    """
    if math.hypot(*shift_ft) <= 1e-12:
        return base
    return TranslatedBatSwing(base, shift_ft)


def swing(aim_ft, handedness):
    """Build the swing a player aiming at `aim_ft` makes.

    `aim_ft` is the aim point as (x, z) in world feet at the plate —
    `UmpireCamera.screen_to_world_at_plate` of the cursor.

    There is deliberately no pitch argument. Where the barrel meets the ball,
    and whether it does at all, is `bat_contact.resolve_contact`'s question,
    and it is answered by intersecting this motion with the ball's rather than
    by building a bat that already knows the answer.

    There is no difficulty argument either, and no swing type. Neither changes
    the *shape* of a swing: a hitter on Hall of Fame swings the same bat as one
    on Rookie, and what the setting moves is how close that bat has to come.
    Both therefore live in `bat_contact`, which is where the bat and the ball
    are asked whether they touched.
    """
    return BatSwing(aim_ft=aim_ft, handedness=handedness)
