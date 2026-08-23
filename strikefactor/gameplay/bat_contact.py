"""Did the bat hit the ball, and where on the bat.

Pure module on the `ball_flight.py` / `ground_roll.py` contract — real feet and
seconds, no pygame, no game state. Given the swing `bat_path` built from the
player's aim and the `PitchTrajectory` the pitch was flown with, it sweeps one
against the other and reports the closest approach.

**This is the module that makes contact emergent.** Before it, the engine asked
two unrelated questions: a timing gate (`|swing_start + 150 - ball_at_plate|`
against a difficulty window) and, if that passed, a geometry gate (a 120 x 50 px
rectangle at the cursor, tested against the ball's *screen* position for one
frame). Neither knew about the other, neither had a depth axis, and the bat in
the second was a 1.3 ft box rather than a bat. Contact depth could not be an
output of that arrangement because nothing in it had a depth; the replay
therefore had to invent one, which is what drove the bat model to build itself
backwards from the pitch.

Here there is one question — do these two solids intersect — and the answers to
"when", "how square", "how far out in front" all fall out of it together.

Three things are worth knowing.

**The bat is a swept sphere of varying radius, not a cylinder.** It sweeps
`bat_path.BAT_PROFILE_IN`, so a ball caught on the handle is a different event
from one caught on the barrel — which is the whole basis of `along` and
therefore of contact quality. A uniform-radius bat would make them
indistinguishable and quality would collapse onto the vertical offset alone.

**The timing forgiveness is an assist, not a tolerance, and that distinction
is the whole of this module's history.** The window over which a real 2.9 in
bat can catch a 95 mph pitch is a few milliseconds; this game has always
granted the player tens. It used to spend that budget *in space*: the bat was
treated as an ellipsoid stretched along the ball's own flight line by the
cushion times the ball's speed, which at ROOKIE is 5.7 ft against a 99 mph
fastball — a tolerance tube eleven feet long, four times the length of the bat
inside it. So "contact" routinely meant the bat was on the ball's *line* and
feet away from the ball. Measured over recorded play, 63% of contacts had
visible daylight between bat and ball, 31% over a foot of it and 16% over two
feet; the replay drew that honestly and it read, correctly, as the bat never
having touched the ball.

The residual was then *charged back* as an aim error, which is the part that
reached gameplay. `vertical_offset_ft` measured the whole separation and the
ball's flight descends, so 2.6 ft of reach is five inches of vertical — well
past the 2.75 in the geometry can physically reach, and graded by a sigma
picked for a range half that size. Timing error was arriving disguised as "the
bat was over the ball", and it was the largest single term in contact quality.

So the budget is spent *in time* instead. `resolve_contact` slides the whole
swing by up to `timing_assist_s` toward the ball and then asks the plain
isotropic question — do these two solids intersect. Contact is a real
intersection, `vertical_offset_ft` is a real aim error inside its documented
range, and the borrowed time is charged where it can be seen
(`Contact.timing_score`). This is deliberately the same shape as the aim
assist below: **an assist moves the bat, a tolerance widens it**, and keeping
those two legible as separate things is a rule this codebase already had
everywhere except here.

The slide deliberately does *not* let the *ball* be sampled at a time of the
model's choosing. An earlier draft swept the ball as a capsule and took the
closest approach, which let a mistimed swing pick the instant that flattered
it: quality came out non-monotone in timing error, dipping at dead-on and
peaking at +/-20 ms. The swing is slid by a stated amount off a datum the
player is actually racing; the ball is left exactly where it is.

**Timing shows up as spray, not as weakness**, and with the bat isotropic that
is now what the geometry does on its own rather than an aspiration. Sweeping
the residual error against a plain bat, `along` runs 1.00 — the very tip — at
14 ms early, through the sweet spot at 0, to 0.62 on the handle at 30 ms late,
and the swing misses entirely past about 14 ms early because not even the tip
is there yet. That is a hitter getting jammed when late and reaching the end of
the bat when early, and it falls out of two solids and a clock. Only once the
ball is off the barrel entirely does quality fall, which is the point at which
a real hitter also stops squaring it up.

**The best contact wins, not the first.** The bat's fattened surface reaches
the ball over a span of instants, and "first touch" among them is not the one
the player means by having hit the ball, so the sweep takes the global minimum.

**There are two assists and one tolerance, and they are three different
things.** `margin_ft` is the tolerance: it widens the bat, so it can only move
the hit-or-miss verdict, and what it lets through scores badly for it. The two
assists *move* the bat — `aim_at_pitch` in space, by a difficulty-scaled
fraction of the player's aim error capped at `MAX_ASSIST_FT`; `resolve_contact`
in time, by up to `timing_assist_s` of their timing error. Because they move it
they lift contact *quality*, which is what lets them reach getting hits rather
than only making contact, and it is why the timing one has to be charged for
explicitly. `bat_path` still never sees the pitch — what the aim assist changes
is which point on the cursor's ray the player is taken to have meant, and what
the timing assist changes is when the swing they made is taken to have started.
"""

import math
from dataclasses import dataclass

from strikefactor.gameplay import bat_path, spray

# A baseball is 2.9 in across.
BALL_RADIUS_FT = 0.121

# How finely the swing is walked. 1 ms over a 220 ms window is 220 samples,
# and the refinement below makes the reported instant far finer than that.
COARSE_STEP_S = 0.002
# Coarse bracket for the refinement of the station, and how hard it is then
# refined. Nine spans and eight golden-section steps put the sweet-spot
# fraction within a thousandth and the gap within a hundredth of an inch.
BRACKET_STATIONS = 9
# How far past touching the coarse walk may report before the swing is called
# a whiff without refining. The coarse and precise station solves agree to
# about a fortieth of an inch, so this is orders of magnitude of headroom.
COARSE_WHIFF_MARGIN_FT = 0.05
ALONG_REFINE_ITERATIONS = 8
REFINE_ITERATIONS = 24

# Loop-invariant, and the sweep runs them tens of thousands of times a swing.
_INV_PHI = (math.sqrt(5.0) - 1.0) / 2.0
_BRACKET_ALONGS = tuple(i / BRACKET_STATIONS for i in range(BRACKET_STATIONS + 1))

# Difficulty knobs, converted here so the callers pass real quantities.
#
# The bat's own tolerance beyond its physical surface, before `contact_zone_size`
# (1.4 at ROOKIE down to 0.7 at HALL_OF_FAME) scales it. An absolute margin
# rather than a multiple of the bat's radius: a 40% fatter barrel is only three
# quarters of an inch, which is too small to be the difficulty dial the setting
# is documented as.
#
# The multiplier *scales* this rather than offsetting it, and that is a fix.
# Written as `(mult - 1.0) * K` the margin was exactly 0.0 at AMATEUR and
# negative above it, so the default difficulty asked the player to put a mouse
# cursor inside the real 2.75 in that a bat and a ball are between them — 22 px,
# on a moving target — and PROFESSIONAL and up asked for less room than physics
# allows. Measured on a perfectly timed swing it was q=1.00 dead on, a foul 3 in
# high and an outright miss at 4. "Contact zone size" has never meant "how much
# is added relative to Amateur".
#
# Re-derived from 0.12 when the timing forgiveness moved out of space and into
# time, and that is bookkeeping rather than a difficulty change. The old
# ellipsoid was stretched along the ball's *flight line*, and a pitch descends,
# so a tube 5.7 ft long was also about 0.9 ft of hidden **vertical** tolerance
# — it was doing a large part of this constant's job without saying so.
# Measured: doubling the timing budget moves the contact rate by 1.4 points
# while the margin moves it strongly, so the contacts the slide model lost were
# aim errors, not timing errors, and this is where they belong. 2.4 in at
# AMATEUR, which is what holds the whiff rate across the whole ladder.
BASE_MARGIN_FT = 0.20
# How much of the player's timing error the engine slides the swing to remove,
# before `contact_timing_window` (1.5 down to 0.4) scales it.
#
# It keeps the value the old spatial cushion had, and that is not a
# coincidence: the cushion was worth `cushion x ball speed` of reach along the
# flight line, which is the same forgiveness measured in feet instead of
# seconds. Spending it in time rather than in space leaves the *verdict*
# boundary where it was — the isotropic bat covers about -14..+40 ms on its
# own, and 26 ms of slide takes that to roughly -40..+66 ms, against the
# -45..+65 ms the cushion gave — while changing what a contact means.
#
# Symmetric on purpose. Recorded swings run systematically +19 ms late (median
# foul +30), which is human reaction time against a 150 ms
# `bat_path.SWING_DURATION_MS` rather than noise, and helping the late side
# more would paper over the one habit a player can actually be taught. It stays
# visible in `swing_timing_signed_ms` and in the replay's timing bands.
TIMING_ASSIST_BASE_S = 0.026

# What the borrowed time costs, as a Gaussian in it.
#
# **The charge is the price of spending the budget in time, and leaving it out
# is the one way this rewrite could quietly make the game easier.** Inside the
# assist the slide cancels the error outright, so the geometry sees a perfectly
# timed swing and would score every one of them 1.00 — a flat plateau of
# max-quality contact 52 ms wide at ROOKIE. The geometry cannot charge for the
# borrowed time because it deliberately cannot see it; this is where it is
# seen.
#
# Calibrated, not chosen: it is the value that holds the whiff/foul/fair split
# and the fair-contact quality quantiles at what the anisotropic model produced
# over the same player model, so the change is neutral to gameplay by
# construction and any rebalancing stays a separate decision. Re-derive it the
# same way if the assist budget moves. Outside the budget the charge saturates
# and the residual geometry takes over, so the two regimes meet continuously.
TIMING_CHARGE_SIGMA_S = 0.020
# A power swing is harder to put on the ball than a contact swing. It always
# has been — the old rectangle was 50 px tall on a W swing and 25 on an E —
# and this is where that lives now, because the difference was never in the
# swing's shape. Most of it comes free, since `power_timing_window` is tighter
# than `contact_timing_window` at every difficulty; this is the part that is
# not, so a power swing stays harder even where the two windows agree.
POWER_MARGIN_FT = -0.035

# Contact quality. Both sigmas are stated in the units the geometry produces,
# which is the point of the rewrite: `vertical_offset` used to be screen pixels
# and `along` did not exist at all.
#
# The reachable range of the vertical offset is bounded by the geometry: the
# ball centre cannot be further from the bat's axis than the two radii and the
# margin sum to, which is 5.1 in at AMATEUR and 6.4 in at ROOKIE — the bat's
# real 2.75 in plus whatever tolerance the difficulty grants. So this sigma has
# to be well inside that or every contact scores 1.0. The old 25 px sigma was
# 4 in, which was wider than most of the reachable range.
#
# Note the bound is the *margin's*, not the cushion's. Under the anisotropic
# model the offset was not bounded by anything meaningful — it picked up the
# ball's descent over feet of along-flight reach and ran past 5 in on a swing
# whose aim was fine, which is what this sigma was being asked to grade.
CENTRE_SIGMA_FT = 0.115
# Off the sweet spot, in bat lengths. 0.13 is about 4.4 in of bat.
SWEET_SIGMA = 0.13
# Below this the ball was clipped, or caught on the handle or off the end, and
# goes foul rather than fair.
#
# **This is no longer the whole foul verdict**, and that is why it came down
# from 0.67. A ball can now also be fouled by *direction* — hooked or sliced
# past a pole, which `spray` decides and which a well-struck ball is perfectly
# capable of. Direction carries about 24% of contact at AMATEUR, so what is
# left for quality is the other kind of foul: tipped, topped, fouled straight
# back. Together they hold the total at ~48% of contact, where quality alone
# used to sit at 57%.
#
# Both were measured before they were set. Direction cannot carry the verdict
# alone — it caps near 25% against a real ~50% — and quality alone cannot see
# which way the ball went. They are the two independent ways to foul a ball,
# not two models of one thing.
#
# Difficulty still moves this (see `foul_threshold`), and now reaches fair/foul
# by a second route as well: a smaller `timing_assist_s` leaves more residual
# timing on the bat, which sprays more contact foul on its own — 19% at ROOKIE
# against 38% at HALL OF FAME, with nothing tuned. The span came in from 0.30
# because of it: the threshold has less of the ladder left to carry.
FOUL_QUALITY_THRESHOLD = 0.52
FOUL_THRESHOLD_SPAN = 0.22


@dataclass(frozen=True)
class Contact:
    """One bat-on-ball event, in real feet and seconds."""

    swing_t_s: float          # seconds after the swing was initiated
    pitch_t_s: float          # seconds after release
    ball_ft: tuple            # the ball's centre when it was struck
    axis_point_ft: tuple      # the point on the bat's axis nearest it
    along: float              # 0 at the knob, 1 at the tip
    gap_ft: float             # surface separation; <= 0 is contact
    vertical_offset_ft: float # ball centre minus bat axis, positive = ball high
    bat_speed_mph: float
    # Seconds the engine slid the swing to bring it to the ball: negative for a
    # late swing (slid earlier), positive for an early one. Zero when the swing
    # needed no help, and never more than `timing_assist_s` in magnitude.
    #
    # Carried rather than recomputed because anything drawing this swing has to
    # draw the *slid* one or the picture comes apart from the verdict again —
    # the same reason `SwingRecord` carries `aim_assist`.
    shift_s: float = 0.0
    # Where the bat was pointing, as `spray.attack_direction_deg` of the axis
    # the sweep was holding: degrees from centre field, pull-positive for
    # either batter.
    #
    # Two of them, because spray is calibrated on the two separately.
    # `pose_attack_deg` is the *nominal* contact pose — a function of the aim
    # alone, so it is the pitch-location half — and the difference between them
    # is the turn the residual timing put on the bat. See `spray`.
    #
    # The bearing used to die here. `axis_point_ft` and `along` were kept and
    # the axis they came from was dropped, so five modules downstream had to
    # invent a direction for the ball out of a timing sign or a coin flip.
    attack_deg: float = 0.0
    pose_attack_deg: float = 0.0

    @property
    def depth_ft(self):
        """Feet in front of the plate where the ball was struck.

        An output, and the one the whole rebuild was for. It varies with where
        the pitch was — an inside pitch is met further out front, because the
        bat is more foreshortened reaching it — *and* with how the swing was
        timed, because an early bat crosses the ball's line while the ball is
        still out there.
        """
        return self.ball_ft[1]

    @property
    def surface_gap_ft(self):
        """Real feet of daylight between the bat's surface and the ball's.

        Bounded by `margin_ft` — two inches at ROOKIE, one and a half at
        AMATEUR — because that is now the only forgiveness with a distance in
        it. `gap_ft` is this minus the margin, so it is <= 0 on every contact
        by construction and this is <= the margin on every contact.

        It used to run to *feet*: the timing cushion was a reach along the
        ball's flight line worth `cushion x ball speed`, 5.8 ft at ROOKIE
        against a 101 mph fastball, so the model granted contact to a bat that
        was a foot or two from the ball while sitting within an inch or two of
        its line. Anything drawing the bat and the ball at their real sizes had
        to draw that daylight, and it read — correctly — as the bat never
        having touched the ball. Keeping the property is what pins that it
        cannot come back: see `tests/test_swing_replay.py`.
        """
        centre = math.dist(self.ball_ft, self.axis_point_ft)
        return centre - bat_path.bat_radius_ft(self.along) - BALL_RADIUS_FT

    @property
    def sweet_spot_score(self):
        return math.exp(-0.5 * ((self.along - bat_path.SWEET_SPOT_FRAC)
                                / SWEET_SIGMA) ** 2)

    @property
    def centre_score(self):
        return math.exp(-0.5 * (self.vertical_offset_ft / CENTRE_SIGMA_FT) ** 2)

    @property
    def timing_score(self):
        """What the borrowed time cost, 0 to 1.

        1.0 for a swing that needed no help. The geometry cannot charge for
        the slide because it is shown the slid swing and nothing else, so
        without this a swing anywhere inside the assist budget would score
        exactly 1.00 — see `TIMING_CHARGE_SIGMA_S`.
        """
        return math.exp(-0.5 * (self.shift_s / TIMING_CHARGE_SIGMA_S) ** 2)

    @property
    def _scores(self):
        return (self.sweet_spot_score, self.centre_score, self.timing_score)

    @property
    def quality(self):
        """0 to 1, how well the ball was struck.

        The geometric mean of the three independent ways a swing can be off —
        along the bat, across it, and how much of the clock it had to be given
        — which is the same shape
        `_compute_contact_quality` used for timing and alignment, deliberately:
        it keeps the distribution `contact_audio.EV_CALIBRATION` is fitted
        against recognisable rather than replacing it wholesale. Times what the
        timing assist cost, which is the one part of the swing the geometry is
        not shown.

        The two do not double-charge: inside the assist budget the slide
        cancels the error and `timing_score` is the whole penalty, outside it
        the charge saturates and the residual error is what the geometry sees.

        **The timing term joins the mean rather than multiplying it**, which
        is not cosmetic. Multiplied on the outside it is a full-strength
        penalty on top of a mean of two, and it flattened the top of the
        distribution — the best contact a player could get while borrowing any
        time at all came out around 0.89 against the 0.96 the old model
        produced, which is the end of the scale `contact_audio.EV_CALIBRATION`
        is anchored on. As a third independent way to be off it is the same
        kind of thing as the other two and is weighted like them.
        """
        a, b, c = self._scores
        return (a * b * c) ** (1.0 / 3.0)

    @property
    def spray_deg(self):
        """Where this ball went: degrees from centre field, pull-positive.

        Difficulty-free, unlike everything else about the verdict. Difficulty
        reaches spray the way it reaches a real hitter — through
        `timing_assist_s`, which decides how much of the player's timing error
        is still on the bat when it meets the ball — rather than through a
        dial on the direction itself.
        """
        return spray.spray_angle_deg(self.pose_attack_deg, self.attack_deg)

    def is_foul(self, threshold=FOUL_QUALITY_THRESHOLD):
        """Whether this contact goes foul rather than into play.

        **Two independent ways to foul a ball**, and the second one is new:

          * the ball was not struck cleanly — tipped, topped, caught on the
            handle or off the end. That is what `quality` measures, and it is
            the `threshold` argument, difficulty-scaled by the caller because
            difficulty belongs to the caller;
          * the ball was struck cleanly and went the wrong side of a pole.
            That is `spray`, and it could not happen before: with the verdict
            resting on quality alone a barrelled ball could never be hooked
            foul, and a mishit that stayed between the lines could never be
            the dribbler in play that it is.

        Not two models of one thing — the first is about how square the contact
        was and the second about which way it left, and a ball can fail either
        independently.
        """
        return self.quality < threshold or spray.is_foul(self.spray_deg)


def margin_ft(zone_size_mult, power=False):
    """The bat's effective surface beyond its own, at this difficulty."""
    return BASE_MARGIN_FT * zone_size_mult + (POWER_MARGIN_FT if power else 0.0)


def timing_assist_s(timing_window_mult):
    """How much of the player's timing error this difficulty slides away.

    39 ms at ROOKIE down to 10 ms at HALL OF FAME. This is the whole of the
    timing forgiveness now: what it does not cover, the player keeps, and the
    geometry charges them for it in the ordinary way.
    """
    return TIMING_ASSIST_BASE_S * timing_window_mult


def timing_error_s(swing, trajectory, swing_start_s):
    """How far off this swing was, in seconds. Negative early, positive late.

    Measured against the ball reaching **the barrel's own contact depth**, the
    same datum `PitchSimulation._signed_timing_ms` reports to the player — so
    the number the engine acts on and the number the replay shows a player are
    one number, not two models of how late they were.
    """
    due = trajectory.time_at_depth(swing.contact_depth_ft)
    return (swing_start_s + bat_path.SWING_DURATION_S) - due


def foul_threshold(timing_window_mult):
    """The quality below which contact goes foul, at this difficulty.

    Runs from about 0.41 at ROOKIE to 0.65 at HALL OF FAME against 0.52 in the
    middle, mirroring what `contact_timing_window` did to the old perfect and
    foul windows — which it scaled together, so a harder setting made it harder
    both to touch the ball and to square it up.

    Only half the verdict now; `Contact.is_foul` asks direction as well.
    """
    return max(0.05, min(0.95,
                         FOUL_QUALITY_THRESHOLD
                         + FOUL_THRESHOLD_SPAN * (1.0 - timing_window_mult)))


# Passes of the fixed point in `aim_at_pitch`. The aim moves a couple of
# inches, which moves the barrel's depth by well under an inch, which moves
# the ball a few thousandths of a foot. Three passes settle it far below the
# radius of a baseball.
AIM_RESOLVE_PASSES = 3

# How far the in-swing adjustment may carry the barrel, whatever the aim error
# was. A hitter reads the ball late and adjusts the barrel's plane on the way
# to it; they do not relocate the bat. A foot is roughly the reach of that
# adjustment, and the cap is what keeps the assist a compensation rather than a
# magnet: a swing 4 in off is squared up, one 24 in off is pulled 12 in and
# still misses.
#
# It has to be this generous to do anything. Recorded play scatters the aim by
# about a foot, so a 4 in cap saturates on the majority of real swings and the
# assist strength stops mattering at all — measured, a 4 in cap left AMATEUR at
# 47% whiffs against 30% at a foot, with the strength dial doing nothing in
# between.
MAX_ASSIST_FT = 1.0


def _assist_correction(error_xz, assist):
    """How far the in-swing adjustment moves the aim, toward the ball.

    A fraction of the error the player made, clamped in length. Returned as a
    displacement rather than an aim so the caller can subtract it inside the
    fixed point without restating the translation.
    """
    if assist <= 0.0:
        return 0.0, 0.0
    cx, cz = assist * error_xz[0], assist * error_xz[1]
    mag = math.hypot(cx, cz)
    if mag > MAX_ASSIST_FT:
        cx *= MAX_ASSIST_FT / mag
        cz *= MAX_ASSIST_FT / mag
    return cx, cz


def aim_at_pitch(cursor_ft, trajectory, handedness, *, assist=0.0):
    """The aim to swing at, for a player pointing `cursor_ft` at this pitch.

    `cursor_ft` is the cursor resolved at the plate — `screen_to_world_at_plate`
    of the mouse — and the return value is another plate-frame aim, ready for
    `bat_path.swing`. What it carries is the player's *statement*, not their
    error: whatever they were pointing at relative to the ball is preserved
    exactly, because the whole thing is a translation of their cursor.

    **This is the seam the swing rewrite left open, and it is worth stating
    why it is a bug rather than a difficulty setting.** A cursor is a ray, and
    `bat_path._unproject` already handles that for the *bat*: the barrel goes
    onto the cursor's ray at the depth the barrel reaches, a couple of feet in
    front of the plate. Nothing did the same for the *ball*. The player is
    looking at a ball drawn all the way to the plate, inside a strike zone
    drawn at the plate, so their cursor is a statement about where the ball
    crosses it — but the ball is still descending, and two feet earlier it is
    two to five inches higher and an inch or two further across. Against a bat
    and ball that are 2.75 inches of tolerance between them, that is the whole
    window, and it is signed the same way on every pitch.

    Measured: a swing whose cursor sits exactly on the ball's plate-crossing
    pixel, timed exactly, met a middle-middle fastball 3.2 inches under its
    centre for a quality of 0.23 — a foul — and never touched a 12-6 curveball
    at all. It also explains why recorded swings ran ~45 ms late as a *habit*:
    swinging late lets the ball drop into a bat that is sitting too low, so
    the best contact available to a correctly-aimed player was at +8 to +39 ms.
    The old rectangle test had no such bias because it compared a cursor at the
    plate against a ball frozen at the plate; the bias arrived with the depth
    axis and nothing was carrying the player's aim along it.

    So the ball is expressed as the aim that names it *where the barrel will
    be*, and the cursor is shifted by the difference. There is no pitch
    dependency in `bat_path` — the swing's shape still comes from the aim and
    the handedness alone. What depends on the pitch is which point on the
    cursor's ray the player meant, and that is a question about the ball.

    **`assist` is the in-swing adjustment, and it is the one thing here that is
    game feel rather than geometry.** Everything above corrects a bias the
    player could not have seen; `assist` shrinks the error they genuinely made,
    by the fraction difficulty allows, capped at `MAX_ASSIST_FT`. The
    justification is real — a hitter reads the ball late and adjusts the
    barrel's plane on the way to it, so where the bat ends up is not exactly
    where they set out to put it — but the size of it is chosen, not derived.
    Keep the two separated in any future reading of this function: at
    `assist = 0` it is the pure translation it has always been, and every test
    of the translation runs at that default.

    It is deliberately *not* a tolerance. `margin_ft` says "close enough
    counts as contact, and scores badly for it"; the assist moves the bat,
    so it lifts quality too. That is what makes it reach getting *hits* rather
    than only making contact, and it is why it belongs on the aim rather than on
    the ellipsoid.
    """
    plate = trajectory.position_at(trajectory.travel_time)
    cx, cz = _assist_correction(
        (cursor_ft[0] - plate[0], cursor_ft[1] - plate[2]), assist)
    aim = (cursor_ft[0], cursor_ft[1])
    for _ in range(AIM_RESOLVE_PASSES):
        depth = bat_path.swing(aim, handedness).contact_depth_ft
        met = trajectory.position_at(trajectory.time_at_depth(depth))
        named = bat_path.to_plate_frame((met[0], met[2]), depth)
        aim = (cursor_ft[0] + named[0] - plate[0] - cx,
               cursor_ft[1] + named[1] - plate[2] - cz)
    return aim


def _closest_along(knob, axis, ball):
    """Where on the bat's axis the ball is nearest. A fraction, clamped.

    The plain orthogonal projection, solved rather than searched. It used to
    be taken in a metric squashed along the ball's flight line, and then
    re-solved against the radius it found because the squash depended on it;
    with the bat isotropic the metric is Euclidean and the fixed point is gone.

    Walking 33 stations instead cost 12 ms a swing, which is most of a frame at
    the exact moment the game is reading the player, and it landed the
    sweet-spot fraction 0.19 out on average.
    """
    r = tuple(ball[i] - knob[i] for i in range(3))
    dd = sum(v * v for v in axis)
    if dd <= 1e-12:
        return 0.0
    return min(1.0, max(0.0, sum(r[i] * axis[i] for i in range(3)) / dd))


def _best_along(f, candidates):
    """The candidate with the smallest `f`, as `(x, f(x))`; first wins a tie.

    Keeps the winning value rather than re-evaluating `f` at the winner, which
    is what `min(..., key=f)` forces and what the two scans here used to do.
    """
    best_x = best_v = None
    for x in candidates:
        v = f(x)
        if best_v is None or v < best_v:
            best_x, best_v = x, v
    return best_x, best_v


def _golden_min(f, lo, hi, iterations, key=None):
    """Golden-section minimum of `f` on `[lo, hi]`, as `(x, f(x))`.

    Written once because the sweep refines twice — along the bat, and along
    the clock — with the same bracket-shrinking loop and different objectives.
    `key` pulls the compared scalar out of a richer return value, so the
    caller that wants the whole `(gap, along, state, ball)` tuple at the
    winner gets it back without paying for another evaluation.
    """
    a, b = lo, hi
    c = b - _INV_PHI * (b - a)
    d = a + _INV_PHI * (b - a)
    fc, fd = f(c), f(d)
    kc = fc if key is None else key(fc)
    kd = fd if key is None else key(fd)
    for _ in range(iterations):
        if kc < kd:
            b, d, fd, kd = d, c, fc, kc
            c = b - _INV_PHI * (b - a)
            fc = f(c)
            kc = fc if key is None else key(fc)
        else:
            a, c, fc, kc = c, d, fd, kd
            d = a + _INV_PHI * (b - a)
            fd = f(d)
            kd = fd if key is None else key(fd)
    return (c, fc) if kc < kd else (d, fd)


def _gap_at(swing, trajectory, swing_start_s, t_s, margin, precise=True):
    """How close the bat came to the ball at swing time `t_s`.

    Returns `(gap, along, state, ball)`. Negative gap is contact.

    `precise=False` skips the refinement of the station and is used only by the
    coarse walk, which is looking for a bracket rather than an answer. The two
    agree to well under an inch, which is far finer than the 2 ms the bracket
    is wide.

    Plain isotropic separation: the surface of the bat at that station, plus
    `margin`, against the surface of the ball, in real feet. There is no
    direction the bat is more forgiving in any more. The timing budget is spent
    by sliding the whole swing (see `resolve_contact`), which is a statement
    about *when* the swing happened rather than about how wide the bat is, so
    what is left here is the honest question.
    """
    state = swing.state_at(t_s)
    ball = trajectory.position_at(swing_start_s + t_s)

    knob, tip = state.knob_ft, state.barrel_ft
    axis = tuple(tip[j] - knob[j] for j in range(3))

    # Unpacked into scalars because this is the innermost thing in the game:
    # it runs ~200k times per swing, on the frame the player is committing.
    # Built out of tuples and generator expressions it allocated four objects
    # an evaluation and was the largest single cost of a swing.
    ax, ay, az = axis
    rx = ball[0] - knob[0]
    ry = ball[1] - knob[1]
    rz = ball[2] - knob[2]
    slack = margin + BALL_RADIUS_FT
    bat_radius_ft = bat_path.bat_radius_ft

    def gap_at_along(along):
        dx = rx - ax * along
        dy = ry - ay * along
        dz = rz - az * along
        return (math.sqrt(dx * dx + dy * dy + dz * dz)
                - bat_radius_ft(along) - slack)

    along = _closest_along(knob, axis, ball)

    # The objective is the distance *minus* the radius, and the radius triples
    # toward the barrel — so the nearest point on the axis is not the smallest
    # gap, and the function is not unimodal. The projection is only a good
    # starting guess: it is bracketed against a coarse walk and then refined,
    # which is what buys back the last inch of gap accuracy the solve alone
    # gives up.
    if not precise:
        best_along, best_gap = _best_along(gap_at_along, (along, 0.0, 1.0))
        return best_gap, best_along, state, ball

    best_along, _ = _best_along(gap_at_along, (along,) + _BRACKET_ALONGS)
    span = 1.0 / BRACKET_STATIONS
    best_along, best_gap = _golden_min(
        gap_at_along, max(0.0, best_along - span), min(1.0, best_along + span),
        ALONG_REFINE_ITERATIONS)
    return best_gap, best_along, state, ball


def resolve_contact(swing, trajectory, swing_start_s, *,
                    zone_size_mult=1.0, timing_window_mult=1.0, power=False):
    """Sweep `swing` against `trajectory` and return the `Contact`, or None.

    `swing_start_s` is when the swing was initiated, in seconds after release —
    the same clock `PitchTrajectory.position_at` runs on.

    **The swing is slid before it is swept.** The engine removes up to
    `timing_assist_s` of the player's timing error by moving when the swing
    started, and everything after that is the plain question of whether two
    solids intersect. What the slide does not cover, the player keeps: the
    residual error puts the ball off the end of the bat or on the handle, which
    is how being early or late reaches a real hitter. `Contact.shift_s` records
    what was given so it can be charged for (`timing_score`) and so anything
    drawing this swing draws the one that was actually swept.

    Sliding rather than stretching is the whole point — see the module
    docstring. The old model widened the bat along the ball's flight line
    instead, which granted contact with feet of daylight between the two and
    then charged that daylight back as an aim error.

    The whole swing is walked, follow-through included, because a swing that
    arrived early is still moving when the ball gets there and can still catch
    it off the end. That stretch of path exists precisely so this can see it.
    """
    margin = margin_ft(zone_size_mult, power)

    # Slide toward on-time, never past it and never further than the budget.
    budget = timing_assist_s(timing_window_mult)
    error = timing_error_s(swing, trajectory, swing_start_s)
    shift = -max(-budget, min(budget, error))
    start_s = swing_start_s + shift

    n = max(2, int(round(bat_path.TOTAL_DURATION_S / COARSE_STEP_S)))
    step = bat_path.TOTAL_DURATION_S / n
    best_i, best = 0, None
    for i in range(n + 1):
        got = _gap_at(swing, trajectory, start_s, i * step, margin,
                      precise=False)
        if best is None or got[0] < best[0]:
            best_i, best = i, got
    # The coarse walk can only be trusted to bracket, so a near miss is
    # re-asked precisely before it is called a whiff.
    if best[0] > COARSE_WHIFF_MARGIN_FT:
        return None

    # Golden-section refine inside the bracketing samples. The coarse step is
    # 1 ms and the bat covers ~1.3 in in that time, which is half a ball.
    t_s, (gap, along, state, ball) = _golden_min(
        lambda t: _gap_at(swing, trajectory, start_s, t, margin),
        max(0.0, (best_i - 1) * step),
        min(bat_path.TOTAL_DURATION_S, (best_i + 1) * step),
        REFINE_ITERATIONS,
        key=lambda got: got[0])
    pitch_t = start_s + t_s

    knob, tip = state.knob_ft, state.barrel_ft
    axis = tuple(tip[j] - knob[j] for j in range(3))
    axis_point = tuple(knob[j] + axis[j] * along for j in range(3))
    return Contact(
        swing_t_s=t_s,
        pitch_t_s=pitch_t,
        ball_ft=ball,
        axis_point_ft=axis_point,
        along=along,
        gap_ft=gap,
        vertical_offset_ft=ball[2] - axis_point[2],
        bat_speed_mph=state.speed_mph,
        shift_s=shift,
        attack_deg=spray.attack_direction_deg(axis, swing.spin),
        pose_attack_deg=spray.attack_direction_deg(swing.contact_axis,
                                                   swing.spin),
    )
