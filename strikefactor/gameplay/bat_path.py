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
have. `bat_contact` sweeps this model instead now, and the rectangle is gone;
it survives below only as the derivation of `PIVOT_PX` and the contact pose,
which were solved against it.

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

**The engine's aiming pivot is the hands.** `HitOutcomeManager.rhpos` is
(490, 453) px, which is (1.53, 2.93) ft — within a couple of inches of where a
right-hander's hands are at contact. Read that way the whole contact pose is
*solved* rather than fitted. The rectangle the engine used to swing was a
screen-space object centred on the cursor with its long axis pointing at the
pivot, so the 3D bat whose projection is that rectangle is pinned by two
conditions — knob onto the pivot pixel, sweet spot onto the cursor pixel — and
perspective maps lines to lines, so the whole bat lies along that axis. That
leaves one unknown, the depth the sweet spot sits at, against one equation,
the bat's length. See `_contact_pose`; it comes out to a quadratic.

**Contact depth is an output.** It is the root of that quadratic, and it lands
where real contact depth lands without a single tuned number: a pitch aimed
inside sits close to the hands on screen, so the bat is heavily foreshortened
and the ball is met 2.7 ft out in front — pulled; a pitch away sits far from
them, the bat lies nearly across the view, and it is met 1.2 ft out — deeper;
a ball low and away is further off than the bat is long, has no root at all,
and the hitter extends after it and meets it at the plate, inside-out. Nothing
here may re-derive it from the ball.

**A cursor is a ray, not a point.** The camera is a perspective projection
from 30 ft behind the plate, so the same pixel is a different world position at
every depth. `_unproject` is where that is handled, and it is not a detail: the
barrel meets the ball a couple of feet out in front, where a tracked ball sits
about 2.3 inches higher on screen than it will at the plate, against a bat and
ball that are 2.75 inches of tolerance between them. Resolving the aim at the
plate and the ball at contact spends 84% of the contact window on a bias no
player can correct.

**The swing is modelled hands-first: a small hand arc, and a bat swung about
the hands.** The hands ride a curve authored in the *rotating body frame* — a
radius that tightens into the slot and extends through contact, a height
working down off the back shoulder — so the load pose is a constant of the
stance rather than the contact pose rotated backwards. The bat's attitude
about the hands (bearing wrapped by the turn plus a decaying `LAG_DEG`, tilt
easing off `LOAD_BAT_ANGLE_DEG`) is what carries the barrel down off the
shoulder and around. Modelled this way the rounded side-view loop and the
overhead spiral *emerge*.

**Bat speed is a calibration target, not a shape parameter.** The game has no
bat-speed input — no swing-strength control, no per-batter attribute — so the
barrel arrives at contact at a stated MLB-average speed on every swing, and the
angular profile's exponent is *solved* from that. Stating the speed and
deriving the exponent keeps the calibration visible; the other way round hides
a real number behind a shape parameter.
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


# --- The batter's hands, in screen pixels --------------------------------
# `HitOutcomeManager.rhpos` / `lhpos`, restated so this module need not import
# the gameplay layer, and pinned to the real attributes by a test.
#
# It was the pivot the engine's contact rectangle rotated about. The rectangle
# is gone — `bat_contact` sweeps a real bat now — but the pivot survives it,
# because what it always was is where the hitter's hands are: (490, 453) px is
# (1.53, 2.93) ft, within a couple of inches of a right-hander's grip at
# contact. The whole contact pose is solved from it.
PIVOT_PX = {"R": (490.0, 453.0), "L": (770.0, 453.0)}


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
_BAT_TIP_RADIUS_FT = BAT_PROFILE_IN[-1][1] / 12.0


def bat_radius_ft(frac):
    """The bat's radius in feet at `frac` of the way from knob to tip."""
    f = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
    for x_hi, lo_ft, slope, x_lo in _BAT_SEGMENTS:
        if f <= x_hi:
            return lo_ft + slope * (f - x_lo)
    return _BAT_TIP_RADIUS_FT


# --- The body ------------------------------------------------------------

# Distance from the plate's centreline to the batter's rotational axis, on
# their own side. The one fixed anchor of the whole kinematic chain: the
# hands orbit it, and the rotation radius that calibrates bat speed is
# measured from it.
SPINE_OFFSET_FT = 2.9

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

# Where the hands are, in depth, at contact. Authored rather than solved: it
# is the one number in the contact pose the engine's screen-plane rectangle
# cannot see, and a hitter's hands are a few inches out in front of the plate
# at contact whatever the pitch was. Everything else about the pose follows
# from it and from the aim.
HAND_CONTACT_DEPTH_FT = 0.40

# How far the hands may slide along the aiming ray from the pivot. Inboard
# never binds; outboard it is the reach on a ball the bat cannot otherwise
# span — low and away — and past it the bat honestly falls short of the
# cursor rather than the hands being flung after it.
MAX_HAND_SLIDE_FT = 1.30

# No cap on how far the barrel may lead the hands in depth: the geometry
# bounds it on its own. The camera sits 30 ft behind the plate, so an aim
# right on top of the hands puts the bat along the view ray, which is very
# nearly the y axis — and a bat is 2.46 ft long. Contact depth therefore
# cannot exceed HAND_CONTACT_DEPTH_FT + HANDS_TO_SWEET_SPOT_FT whatever the
# player does. A cap here would be a second, weaker statement of that.

# Hand height at initiation — up by the back shoulder. An *absolute* height,
# like LOAD_BAT_ANGLE_DEG below: a low pitch costs the hands a longer drop,
# it does not lower where they start.
LOAD_HANDS_HEIGHT_FT = 4.6

# The hands' distance from the spine axis over the swing, as a multiple of
# whatever it is at contact. Stated as a quadratic in the *load* (below)
# rather than in time, for two reasons: it is flat at contact, so the hands'
# radial motion cannot disturb the attack angle the plane owns; and the loop
# it describes — hands tighten into the slot, then extend through the ball —
# is a function of how far the body still has to turn, not of the clock.
#   scale = 1 + HAND_RADIUS_B*load + HAND_RADIUS_C*load^2
# gives 1.00 at contact, a 0.70 minimum around two-thirds of the turn out, and
# 0.76 at the load.
HAND_RADIUS_B = -0.88
HAND_RADIUS_C = 0.64
# How much further the hands reach in the follow-through, and how much they
# rise with it. Squared in the extension's own progress, so both are flat at
# contact for the same reason.
EXTENSION_REACH = 0.10
EXTENSION_RISE_FT = 0.55

# The hands lag the body's turn slightly at load and catch it by contact,
# which is what turns the hand circle into the small oval a swing actually
# draws. Small on purpose: it is a shape term, not a power source.
HAND_LEAD_DEG = 12.0
HAND_LEAD_RAD = math.radians(HAND_LEAD_DEG)


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
# function of aim alone these sit at about 1.8–2.2 over the plate and should
# never bind — a test says so, and a swing that rails is a sign the contact
# pose has come loose again.
EASE_K_MIN = 1.05
EASE_K_MAX = 3.0


# --- Screen pixels to feet at the plate ----------------------------------

def _to_ft(screen_xy):
    """A screen point at the plate, in world feet. Thin alias for the camera."""
    return DEFAULT_CAMERA.screen_to_world_at_plate(screen_xy[0], screen_xy[1])


def pivot_ft(handedness):
    """The bat's orientation pivot in world feet, as (x, z).

    Also the hands' contact position in those two axes — see `_contact_pose`.
    """
    return _to_ft(PIVOT_PX["R" if handedness == "R" else "L"])


# --- The contact pose -----------------------------------------------------

def _unproject(plate_xz, depth_ft):
    """The world point a cursor names, at `depth_ft` rather than at the plate.

    The game's camera is a *perspective* projection from 30 ft behind the
    plate, so a screen pixel is a ray and not a point: the same cursor is a
    different world position at every depth, spreading with distance. Callers
    hand this module `screen_to_world_at_plate(cursor)`, which is the ray's
    intersection with `y = 0`; this walks it back out to where the bat is.

    It matters more than the 7% scale suggests. The barrel meets the ball a
    couple of feet in front of the plate, where a tracked ball sits about 2.3
    inches higher on the screen than it will at the plate — and a bat and a
    ball together are only 2.75 inches of tolerance. Resolving the aim at the
    plate and the ball at contact therefore spent 84% of the contact window on
    a bias the player has no way to correct, which showed up as every swing
    scoring under 0.5 for quality.
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


def hands_anchor_ft(handedness):
    """The hands' contact position in world feet, as (x, y, z).

    The engine's aiming pivot, unprojected at the depth the hands are at. It
    is within a couple of inches of where a real hitter's hands are when they
    meet the ball, which is the observation the whole contact pose rests on.
    """
    xz = _unproject(pivot_ft(handedness), HAND_CONTACT_DEPTH_FT)
    return (xz[0], HAND_CONTACT_DEPTH_FT, xz[1])


def _contact_pose(aim_ft, handedness):
    """The bat at the instant the barrel arrives, from the aim alone.

    Returns `(hands_ft, axis3)` — the hands in world feet and the bat's unit
    long axis, knob to barrel.

    The rectangle the engine used to swing was a screen-space object: centred
    on the cursor, long axis pointing at the pivot. The 3D bat whose
    *projection* is that rectangle is therefore pinned by two conditions — the
    knob projects to the pivot pixel, the sweet spot projects to the cursor
    pixel — and since a perspective projection maps lines to lines, the whole
    bat then lies along that axis on screen.

    That leaves exactly one unknown, the depth `d` the sweet spot sits at, and
    one equation: the bat is `HANDS_TO_SWEET_SPOT_FT` long. Both unprojected
    coordinates are linear in depth, so the equation is a quadratic and the
    pose is solved outright — no search and no fitted parameter. The
    rectangle is gone; what it leaves behind is this pose, which is what
    `bat_contact` now sweeps.

    Contact depth is the root. It is an *output*, and it lands where real
    contact depth lands: an inside pitch sits close to the hands on screen, so
    the bat is heavily foreshortened and the ball is met well out in front —
    pulled; a pitch away sits far from them, the bat lies nearly across the
    view, and the ball is met deeper. A ball further away than the bat is long
    has no root at all — the hitter cannot reach it from where their hands are,
    so they extend after it (`_reach`) and meet it at arm's length, inside-out,
    off the quadratic's vertex rather than off a root that does not exist.
    """
    knob = hands_anchor_ft(handedness)
    cam_dist = DEFAULT_CAMERA.cam_dist
    cam_h = DEFAULT_CAMERA.cam_height

    # sweet(d) = (ax0 + ax0*d/D, d, az0 + (az0-h)*d/D), both linear in d.
    ax0, az0 = aim_ft
    a_lin, g_lin = ax0 / cam_dist, (az0 - cam_h) / cam_dist
    a_con = ax0 - knob[0]
    g_con = az0 - knob[2]
    h = HAND_CONTACT_DEPTH_FT

    qa = a_lin * a_lin + 1.0 + g_lin * g_lin
    qb = 2.0 * (a_con * a_lin - h + g_con * g_lin)
    qc = (a_con * a_con + h * h + g_con * g_con
          - HANDS_TO_SWEET_SPOT_FT * HANDS_TO_SWEET_SPOT_FT)

    disc = qb * qb - 4.0 * qa * qc
    if disc < 0.0:
        # No depth lets the bat span the ball from where the hands are. The
        # vertex is the depth at which it comes closest, and it is the
        # *analytic continuation* of the root — the two meet exactly where
        # `disc` reaches zero — so taking it keeps the pose, and with it the
        # bat's bearing, continuous in the aim.
        #
        # This matters because the bearing is now read downstream as the
        # ball's direction (`spray`). The previous answer put the bat flat in
        # the plane of the plate, which pinned its face normal at *exactly*
        # centre field; 9.6% of swings at AMATEUR reach that pose, so a tenth
        # of all contact would have stacked on one spray angle. Same failure
        # as clamping the home-run angle onto the foul poles.
        depth = -qb / (2.0 * qa)
    else:
        root = math.sqrt(disc)
        depth = max((-qb + root) / (2.0 * qa), (-qb - root) / (2.0 * qa))
    # Behind the plate the barrel is chasing a pitch already past it; the
    # sweep will call that a whiff, and the pose only has to stay finite.
    depth = max(0.0, depth)

    sweet_xz = _unproject(aim_ft, depth)
    sweet = (sweet_xz[0], depth, sweet_xz[1])
    delta = tuple(sweet[i] - knob[i] for i in range(3))
    span = math.sqrt(sum(v * v for v in delta))
    if span < 1e-9:
        return knob, (1.0, 0.0, 0.0)
    axis3 = tuple(v / span for v in delta)
    if span <= HANDS_TO_SWEET_SPOT_FT + 1e-9:
        return knob, axis3
    return _reach(knob, axis3, span)


def _reach(knob, axis3, span):
    """The pose for a ball the bat cannot span from where the hands are.

    Low and away, mostly. The hands go out after it along the bat's own line
    and get as far along it as they can, which draws as the inside-out swing
    it is.

    The *axis* is the caller's, and that is the whole difference from the
    version this replaced. It comes from the quadratic's vertex, so the barrel
    goes on trailing the hands further and further as the hitter has to reach
    further — rather than snapping flat, and flattening every such swing's
    direction onto centre field, the moment the ball stops being spannable.
    """
    slide = min(MAX_HAND_SLIDE_FT, span - HANDS_TO_SWEET_SPOT_FT)
    return tuple(knob[i] + axis3[i] * slide for i in range(3)), axis3


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


class BatSwing:
    """A swing, sampleable at any time from initiation through the finish.

    Built from the player's aim and handedness and nothing else. Hands-first:
    the knob is *authored* and the barrel follows.

      * the **hands** orbit the spine axis on a radius that tightens into the
        slot and extends through the ball, working down from
        `LOAD_HANDS_HEIGHT_FT` to the contact grip as the body turns;
      * the **bat's attitude** about the hands — bearing wrapped by the turn
        remaining plus the lag, tilt easing off `LOAD_BAT_ANGLE_DEG` — is
        what carries the barrel down off the shoulder and around;
      * the **plane** moves the whole assembly by `r*tan(phi)*sin(theta_p)`,
        so the barrel bottoms out a quarter turn before contact and is met on
        the way up at exactly `ATTACK_ANGLE_DEG`, since every other term is
        momentarily still there.

    `state_at(SWING_DURATION_S)` is pinned: the sweet spot sits at the aim
    point in (x, z), and the bat's (x, z) projection lies along the ray the
    engine's old collision tested — the pose is solved against that geometry,
    which is why it can be stated rather than fitted. Its *depth*,
    `contact_depth_ft`, is an output.
    """

    def __init__(self, aim_ft, handedness):
        self.aim_ft = tuple(aim_ft)
        self.handedness = "R" if handedness == "R" else "L"
        self.spin = 1.0 if self.handedness == "R" else -1.0
        self.bat_speed_mph = PEAK_BAT_SPEED_MPH
        self.spine_xy = (SPINE_OFFSET_FT * self.spin, 0.0)

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
        # and their height eased up toward the load.
        sx, sy = self.spine_xy
        bearing = self._turn(self.hand_bearing,
                             theta - self.spin * HAND_LEAD_RAD * load)
        radius = self.hand_radius_ft * (
            1.0 + HAND_RADIUS_B * load + HAND_RADIUS_C * load * load
            + EXTENSION_REACH * ext * ext)
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
