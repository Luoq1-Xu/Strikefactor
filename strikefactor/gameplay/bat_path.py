"""Where the bat is, in real feet, at every instant of a swing.

Same contract as `engine/contact_audio.py` and `ball_flight.py` — real feet
and seconds, no pygame, no game state, no rendering. The swing replay reads
it; nothing in the live pitch path does.

This module exists because the game's bat has a position but no *motion*.
`HitOutcomeManager.get_ball_to_bat_contact_outcome` swings a real geometric
object — a rotated rectangle 120 px long by 50 px (contact) or 25 px (power)
tall, centred 30 px inboard of the aim point, at `atan2(aim - pivot)` about a
fixed pivot — but that rectangle exists for exactly one frame, in the plane of
the screen, with no depth. Every question a timing replay wants to ask ("where
was the barrel 40 ms ago", "how far in front of the plate did they meet it")
is a question about the two axes the engine's bat does not have.

Four things are worth knowing before changing anything here.

**The swing is modelled hands-first: a small hand arc, and a bat swung about
the hands.** It was not always. The first model put the sweet spot on a
fixed-radius horizontal circle and layered ~4 ft of height loss on top as
functions of rotation-remaining, deriving the knob *backwards* from the
barrel. Three visible faults followed: the barrel plunged nearly straight
down at initiation (the height terms spend fastest exactly where the eased
rotation covers the least ground), the barrel's depth overshot and reversed
late in the swing on ordinary contacts — median |timing| is ~21 ms, which is
±2.7 ft of depth — drawing a sharp V where a swing has a rounded loop, and
the hands ended up wherever the circle arithmetic put them, including 2.7 ft
into the catcher's box. Modelled the way a swing actually works — hands on a
small orbit about the spine, the barrel whipping around the hands — the
rounded loop, the overhead spiral, and a believable knob track all *emerge*.
The knob path is authored now; nothing derives it backwards.

**The bat's screen-plane attitude at contact is pinned to the collision
check; its depth attitude is not, because the engine has none.** The engine's
rectangle lives in the plane of the screen, so it constrains exactly two of
the drawn bat's three axis components: the (x, z) projection must lie along
the pivot-to-aim ray `collision_angled` tested (see `bat_axis`, and the test
that walks the true axis out of the collision itself). The third — how far
the barrel leads or lags the hands in *depth* — the engine never had an
opinion about, and forcing it to zero is what drew the hands directly under
the ball. It is chosen here instead (`_contact_lead`) so the hands land on
their orbit: met deep, the barrel lags and the hands stay ahead of the ball —
an inside-out swing; met out front, the barrel has released past square — a
ball that got pulled. Both are what those mistimings look like in life.

**Contact depth is not modelled here, it is measured.** The caller passes
`contact_depth_ft` straight off the pitch's own
`PitchTrajectory.position_at(bat_arrival_s).y`. Early swings meet the ball out
in front (positive), late swings let it get deep (negative), and because it is
the same trajectory the pitch was flown with there is no second model that can
disagree with the first. Nothing in this module is allowed to re-derive it.

**Bat speed is a calibration target, not a shape parameter.** The game has no
bat-speed input — no swing-strength control, no per-batter attribute — so the
barrel arrives at contact at a stated MLB-average speed on every swing, and
the angular profile's exponent is *solved* from that (per swing, since the
rotation radius depends on where the ball was met). Stating the speed and
deriving the exponent keeps the calibration visible; the other way round
hides a real number behind a shape parameter.
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


# --- The engine's contact geometry, in screen pixels ---------------------
# Restated from HitOutcomeManager so this module does not import the gameplay
# layer. A test pins every one of these to the real attributes; if they drift
# the test fails rather than the replay silently lying.

PIVOT_PX = {"R": (490.0, 453.0), "L": (770.0, 453.0)}
CONTACT_ZONE_WIDTH_PX = 120.0
CONTACT_ZONE_HEIGHT_PX = {1: 50.0, 2: 25.0}   # 1 = contact swing (W), 2 = power (E)
# The cursor sits 30 px inboard of the rectangle centre, so of the 120 px
# span, 30 px lie outboard of the cursor and 90 px inboard.
CURSOR_TO_ZONE_CENTRE_PX = 30.0


# --- The bat -------------------------------------------------------------

BAT_LENGTH_FT = 2.79          # 33.5 in, the common MLB length
CURSOR_TO_TIP_FT = 0.33       # the 30 px of rectangle outboard of the aim point
# Grip to the point that meets the ball — the lever every attitude change
# swings on, since the bat pivots about the hands.
HANDS_TO_SWEET_SPOT_FT = BAT_LENGTH_FT - CURSOR_TO_TIP_FT

# Distance from the plate's centreline to the batter's rotational axis, on
# their own side. The one fixed anchor of the whole kinematic chain: the
# hands orbit it, and the rotation radius that calibrates bat speed is
# measured from it.
SPINE_OFFSET_FT = 2.9

# The body's turn from initiation to contact. Bearing sweep beyond this comes
# from the lag term below, so the barrel's total wrap is ARC + LAG.
SWING_ARC_DEG = 120.0
SWING_ARC_RAD = math.radians(SWING_ARC_DEG)

# Upward attack angle of the barrel's path *through contact*, and the tilt of
# the swing plane from horizontal, which are the same number for a reason
# worth stating: the plane's dip term takes the whole bat down by
# r*tan(phi)*sin(|theta|), so at contact its rate of change is r*tan(phi)*w
# of climb against a horizontal r*w — exactly phi, on the line of nodes, with
# the lowest point a quarter turn earlier. A stated assumption, not a
# measurement — the game has no attack-angle input, and the replay must never
# present this as something the player did.
SWING_PLANE_DEG = 10.0
SWING_PLANE_RAD = math.radians(SWING_PLANE_DEG)
# The dip radius is capped so an extreme mistime (contact 8 ft deep exists in
# the data) does not sink the hands two feet mid-swing. Inside the cap the
# attack angle at contact is exactly SWING_PLANE_DEG; past it, shallower —
# which is what a lunge does to a swing plane anyway.
PLANE_DIP_RADIUS_CAP_FT = 4.0

# --- The hands -----------------------------------------------------------

# How far the hands orbit from the spine axis. Biomechanically the hands stay
# a forearm's reach from the chest through the turn; this is that reach.
HAND_ORBIT_RADIUS_FT = 1.15

# Hand height at initiation — up by the back shoulder. An *absolute* height,
# like LOAD_BAT_ANGLE_DEG below: a low pitch costs the hands a longer drop,
# it does not lower where they start.
LOAD_HANDS_HEIGHT_FT = 4.6

# Where the hands like to be, in depth, at contact: slightly out in front of
# the ball. Used only to pick between geometrically valid contact poses in
# `_contact_lead` — virtually every real swing finishes with the hands a
# touch ahead of the barrel's depth.
HAND_DEPTH_PRIOR_FT = 0.5

# The most the barrel may lead or lag the hands in depth at contact. Past
# this the orbit stretches instead (the hands reach — a lunge), because the
# alternative is a bat folded impossibly around its own grip.
MAX_CONTACT_LEAD_DEG = 70.0
MAX_CONTACT_LEAD_RAD = math.radians(MAX_CONTACT_LEAD_DEG)

# --- The load ------------------------------------------------------------
# Where the bat is when the swing starts, expressed as attitudes given up on
# the way to contact. All stated assumptions in the same sense as
# SWING_PLANE_DEG: the game has no load input either.

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

# How the load is given up: as a function of the rotation *still to go*,
# never of the clock. The bat gets on plane because the body has turned, and
# tying it to time instead drops the barrel before the swing has begun, since
# the eased rotation leaves most of the turn still to come at half time.
#
# The exponent has to be at least 2, or the load terms are still moving as
# the ball is met and the attack angle at contact is not SWING_PLANE_DEG at
# all — the zero-rate-at-contact property holds for any power >= 2, since
# d(load)/dt = (d(load)/dtheta) * theta' and the theta-derivative vanishes at
# theta = 0. Exactly 2, not 3: a barrel met deep reverses its depth late in
# the swing, and the loop only rounds there if something is still moving
# vertically — at power 3 the tilt is dead by 40° out and the reversal drew
# as a sharp V, the very artifact the hands-first model exists to fix.
ON_PLANE_EASE = 2.0

# MLB average barrel speed at contact. Not a free dial: it is what the
# angular profile's exponent is solved for, per swing, in `BatSwing`.
PEAK_BAT_SPEED_MPH = 72.0
PEAK_BAT_SPEED_FT_S = PEAK_BAT_SPEED_MPH / MPH_PER_FT_S

# Sanity rails on the solved exponent. The peak-to-mean angular speed ratio
# *is* k, so past ~3 the swing reads as a bat that stands still and then
# teleports — at that rail the contact speed gives way instead (a ball met
# barely off the hands was not hit at 72 mph, and clamping *up* would report
# lunges as faster than clean swings). The floor only keeps the profile a
# swing: k must stay above 1 or the speed would peak before contact.
EASE_K_MIN = 1.05
EASE_K_MAX = 3.0


# --- Screen pixels to feet at the plate ----------------------------------

def _to_ft(screen_xy):
    """A screen point at the plate, in world feet. Thin alias for the camera."""
    return DEFAULT_CAMERA.screen_to_world_at_plate(screen_xy[0], screen_xy[1])


def pivot_ft(handedness):
    """The bat's orientation pivot in world feet, as (x, z)."""
    return _to_ft(PIVOT_PX["R" if handedness == "R" else "L"])


def contact_zone_ft(swing_type, zone_size_mult=1.0):
    """The engine's contact rectangle as (length_ft, height_ft).

    Difficulty scales it — `contact_zone_size` runs 1.4 at ROOKIE down to 0.7
    at HALL_OF_FAME — so the replay can show the player how much bat they
    actually had, which changes under them without any on-screen indication
    anywhere else in the game.
    """
    height_px = CONTACT_ZONE_HEIGHT_PX.get(swing_type, CONTACT_ZONE_HEIGHT_PX[1])
    # The projection is anisotropic, so a length and a height do not share a
    # scale: 30/2753.4 ft per px across, 30/2250 down.
    ft_per_px_x = DEFAULT_CAMERA.cam_dist / DEFAULT_CAMERA.scale_x
    ft_per_px_z = DEFAULT_CAMERA.cam_dist / DEFAULT_CAMERA.scale_y
    return (CONTACT_ZONE_WIDTH_PX * zone_size_mult * ft_per_px_x,
            height_px * zone_size_mult * ft_per_px_z)


def bat_axis(aim_ft, pivot_xz):
    """Unit vector along the bat's long axis at contact, in the (x, z) plane.

    The plain hands-to-aim-point ray. It used to carry a z-flip, to match the
    mirrored rectangle `collision_angled` was testing before its sign was
    fixed; with the engine and the eye now agreeing, there is nothing to
    correct for.
    """
    dx = aim_ft[0] - pivot_xz[0]
    dz = aim_ft[1] - pivot_xz[1]
    mag = math.hypot(dx, dz)
    if mag < 1e-9:
        return (1.0, 0.0)
    return (dx / mag, dz / mag)


# --- The contact pose -----------------------------------------------------

def _contact_lead(contact_ft, axis_xz, spine_xy):
    """How far the barrel leads (+) or lags (-) the hands in depth at
    contact, in radians — the one attitude the engine's screen-plane
    rectangle leaves free.

    The bat's axis at contact is `(ax*cos(psi), sin(psi), az*cos(psi))`: unit
    by construction (ax² + az² = 1), and its (x, z) projection stays along
    the ray the collision tested for every psi. What pins psi down is the
    body: the hands sit one bat-grip back along that axis from the ball, and
    they have to land on their orbit around the spine. Where several poses
    satisfy that, the one keeping the hands nearest their natural depth —
    slightly out front — wins; where none does (an extreme mistime), the
    closest approach wins and the orbit stretches, which is a lunge.
    """
    ax, az = axis_xz
    h2s = HANDS_TO_SWEET_SPOT_FT

    def hands_xy(psi):
        return (contact_ft[0] - h2s * ax * math.cos(psi),
                contact_ft[1] - h2s * math.sin(psi))

    def orbit_error(psi):
        hx, hy = hands_xy(psi)
        return (math.hypot(hx - spine_xy[0], hy - spine_xy[1])
                - HAND_ORBIT_RADIUS_FT)

    n = 281
    psis = [-MAX_CONTACT_LEAD_RAD + 2.0 * MAX_CONTACT_LEAD_RAD * i / (n - 1)
            for i in range(n)]
    errs = [orbit_error(p) for p in psis]

    roots = []
    for i in range(1, n):
        if errs[i - 1] * errs[i] <= 0.0 and errs[i - 1] != errs[i]:
            lo, hi = psis[i - 1], psis[i]
            e_lo = errs[i - 1]
            for _ in range(30):
                mid = 0.5 * (lo + hi)
                e_mid = orbit_error(mid)
                if e_lo * e_mid <= 0.0:
                    hi = mid
                else:
                    lo, e_lo = mid, e_mid
            roots.append(0.5 * (lo + hi))

    if roots:
        return min(roots,
                   key=lambda p: abs(hands_xy(p)[1] - HAND_DEPTH_PRIOR_FT))
    return min(psis, key=lambda p: abs(orbit_error(p)))


# --- The swing -----------------------------------------------------------

class BatState:
    """The bat at one instant: both ends and the point that meets the ball."""

    __slots__ = ("knob_ft", "barrel_ft", "sweet_spot_ft", "speed_mph")

    def __init__(self, knob_ft, barrel_ft, sweet_spot_ft, speed_mph):
        self.knob_ft = knob_ft
        self.barrel_ft = barrel_ft
        self.sweet_spot_ft = sweet_spot_ft
        self.speed_mph = speed_mph


class BatSwing:
    """A swing, sampleable at any time from initiation to contact.

    Hands-first: the knob is *authored* and the barrel follows.

      * the **hands** orbit the spine axis at `HAND_ORBIT_RADIUS_FT`, working
        down from `LOAD_HANDS_HEIGHT_FT` to the contact grip as the body
        turns;
      * the **bat's attitude** about the hands — bearing wrapped by the turn
        remaining plus the lag, tilt easing off `LOAD_BAT_ANGLE_DEG` — is
        what carries the barrel down off the shoulder and around;
      * the **plane** dips the whole assembly by `r*tan(phi)*sin(|theta|)`,
        so the barrel bottoms out a quarter turn before contact and is met on
        the way up at exactly `SWING_PLANE_DEG`, since every other term is
        momentarily still there.

    `state_at(SWING_DURATION_S)` is pinned: the sweet spot sits at the aim
    point, at the depth the ball was, and the bat's (x, z) projection lies
    along the ray the engine's collision tested — so the drawn bat and the
    rectangle it was graded by cannot come apart in any plane the engine
    knows about.
    """

    def __init__(self, contact_ft, axis_xz, zone_ft, spin):
        self.contact_ft = contact_ft
        self.axis_xz = axis_xz
        self.spin = spin
        self.zone_length_ft, self.zone_height_ft = zone_ft
        self.bat_speed_mph = PEAK_BAT_SPEED_MPH
        self.spine_xy = (SPINE_OFFSET_FT * spin, 0.0)

        # The one free attitude at contact, and everything that follows from
        # it: the full 3D axis, the hands' contact position, and the split of
        # that axis into a ground bearing and a tilt for the load to move.
        ax, az = axis_xz
        psi = _contact_lead(contact_ft, axis_xz, self.spine_xy)
        self.contact_lead_rad = psi
        cos_psi = math.cos(psi)
        contact_axis = (ax * cos_psi, math.sin(psi), az * cos_psi)
        self.hands_contact = tuple(
            contact_ft[i] - HANDS_TO_SWEET_SPOT_FT * contact_axis[i]
            for i in range(3))

        self.contact_tilt_rad = math.asin(
            max(-1.0, min(1.0, contact_axis[2])))
        bearing_mag = math.hypot(contact_axis[0], contact_axis[1])
        self.contact_bearing = (
            (contact_axis[0] / bearing_mag, contact_axis[1] / bearing_mag)
            if bearing_mag > 1e-9 else (float(spin), 0.0))

        # The rotation radius bat speed is calibrated on: spine axis to the
        # contact point. At contact every load term is flat, so the bat is
        # momentarily rigid about the spine and the sweet spot's speed is
        # w * r (times sec(phi) for the plane's climb — hence the cos in the
        # solve, so the *total* barrel speed is the stated 72).
        self.turn_radius_ft = math.hypot(contact_ft[0] - self.spine_xy[0],
                                         contact_ft[1] - self.spine_xy[1])
        k = (PEAK_BAT_SPEED_FT_S * math.cos(SWING_PLANE_RAD)
             / max(self.turn_radius_ft, 1e-6)) * SWING_DURATION_S / SWING_ARC_RAD
        self.ease_k = max(EASE_K_MIN, min(EASE_K_MAX, k))

    # -- the angular profile ----------------------------------------------

    def _theta(self, u):
        """Rotation still to go at phase u, in radians. 0 at contact.

        `spin` is +1 for a right-handed batter and -1 for a left-hander.
        Without it both hands load their barrel toward the *pitcher*, which
        is the finish of a swing rather than its start.
        """
        return self.spin * SWING_ARC_RAD * (1.0 - u ** self.ease_k)

    def _load(self, theta):
        """How much of the load is left, 1 at initiation and 0 at contact.

        A function of the rotation still to go, not of the clock, and flat at
        contact so nothing here disturbs the attack angle.
        """
        return (abs(theta) / SWING_ARC_RAD) ** ON_PLANE_EASE

    @staticmethod
    def _turn(vec_xy, theta):
        """A ground vector turned by `theta` about the vertical."""
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        return (vec_xy[0] * cos_t - vec_xy[1] * sin_t,
                vec_xy[0] * sin_t + vec_xy[1] * cos_t)

    # -- the kinematic chain ------------------------------------------------

    def _pose(self, u):
        """Knob position and bat axis at phase u — the whole chain."""
        theta = self._theta(u)
        load = self._load(theta)

        # The hands: their orbit turned back by the rotation remaining, their
        # height eased up toward the load, and the plane's dip — which moves
        # the whole bat, hands included, because the plane belongs to the
        # rotation and not to the bat's attitude.
        sx, sy = self.spine_xy
        rel = self._turn((self.hands_contact[0] - sx,
                          self.hands_contact[1] - sy), theta)
        dip = (min(self.turn_radius_ft, PLANE_DIP_RADIUS_CAP_FT)
               * math.tan(SWING_PLANE_RAD) * math.sin(abs(theta)))
        knob = (sx + rel[0], sy + rel[1],
                self.hands_contact[2]
                + (LOAD_HANDS_HEIGHT_FT - self.hands_contact[2]) * load
                - dip)

        # The bat about the hands: the bearing carries the body's remaining
        # turn plus the lag still wrapped, the tilt is the load's. One unit
        # vector, so the bat stays one bat long.
        wrap = theta + self.spin * LAG_RAD * load
        bx, by = self._turn(self.contact_bearing, wrap)
        tilt = self.contact_tilt_rad + (LOAD_BAT_ANGLE_RAD
                                        - self.contact_tilt_rad) * load
        cos_tilt, sin_tilt = math.cos(tilt), math.sin(tilt)
        return knob, (bx * cos_tilt, by * cos_tilt, sin_tilt)

    def _sweet_at(self, u):
        knob, axis = self._pose(u)
        return tuple(knob[i] + axis[i] * HANDS_TO_SWEET_SPOT_FT
                     for i in range(3))

    def state_at(self, t_s):
        """The bat at `t_s` seconds after the swing was initiated."""
        u = max(0.0, min(1.0, t_s / SWING_DURATION_S))
        knob, axis = self._pose(u)
        return BatState(
            knob_ft=knob,
            barrel_ft=tuple(knob[i] + axis[i] * BAT_LENGTH_FT
                            for i in range(3)),
            sweet_spot_ft=tuple(knob[i] + axis[i] * HANDS_TO_SWEET_SPOT_FT
                                for i in range(3)),
            speed_mph=self._speed_at(u),
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
        b = min(1.0, u + h)
        dt = (b - a) * SWING_DURATION_S
        if dt <= 0.0:
            return 0.0
        pa, pb = self._sweet_at(a), self._sweet_at(b)
        return math.dist(pa, pb) / dt * MPH_PER_FT_S

    def barrel_track(self, n=48):
        """`n` states evenly spaced over the swing, for drawing the path."""
        if n < 2:
            n = 2
        return [self.state_at(SWING_DURATION_S * i / (n - 1)) for i in range(n)]


def swing(aim_ft, contact_depth_ft, handedness, swing_type, zone_size_mult=1.0):
    """Build the swing that met the ball at `aim_ft`, `contact_depth_ft` out front.

    `aim_ft` is the player's aim point as (x, z) in world feet at the plate —
    `UmpireCamera.screen_to_world_at_plate` of the cursor the engine tested
    against. `contact_depth_ft` is the ball's own y at the instant the bat
    arrived: positive is out in front of the plate (early), negative is deep
    (late).
    """
    side = 1.0 if handedness == "R" else -1.0
    return BatSwing(
        contact_ft=(aim_ft[0], contact_depth_ft, aim_ft[1]),
        axis_xz=bat_axis(aim_ft, pivot_ft(handedness)),
        zone_ft=contact_zone_ft(swing_type, zone_size_mult),
        spin=side,
    )
