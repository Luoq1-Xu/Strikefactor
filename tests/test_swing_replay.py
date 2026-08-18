"""The swing replay: the record it reads, and the overlay that draws it.

The feature's one substantive claim is that "early" and "late" are measured
rather than asserted — `contact_depth_ft` is the pitch's own trajectory
evaluated at the instant the bat arrived, so it cannot disagree with the ball
the player watched. Most of what follows guards that, plus the handful of
things that were wrong before: a clamped depth that erased late swings, a
`SwingRecord` that a taken pitch wiped out, and fouls reading a
`contact_quality` that is null on them by design.
"""

import math

import pygame
import pytest

from strikefactor.gameplay import bat_path
from strikefactor.gameplay.swing_record import SwingRecord
from strikefactor.ui.swing_replay_overlay import SwingReplayOverlay
from strikefactor.utils.pitch_physics import PitchTrajectory

SCREEN = (1280, 720)


def make_trajectory(speed_mph=93.0, target_z=2.5):
    return PitchTrajectory.from_pitch_params(
        release_pos=(-1.8, 54.0, 6.0),
        speed_mph=speed_mph,
        pfx_x_inches=-4.0,
        pfx_z_inches=14.0,
        target_x_ft=0.0,
        target_z_ft=target_z,
    )


def make_record(timing_ms=0.0, made_contact="hit", outcome="SINGLE",
                hand="R", swing_type=1, **kw):
    """A SwingRecord with `timing_ms` of error. Negative early, positive late."""
    traj = make_trajectory()
    fields = dict(
        trajectory=traj,
        travel_time_s=traj.travel_time,
        bat_arrival_s=traj.travel_time + timing_ms / 1000.0,
        signed_timing_ms=timing_ms,
        perfect_ms=30.0,
        foul_ms=60.0,
        aim_ft=(0.0, 2.5),
        handedness=hand,
        swing_type=swing_type,
        zone_size_mult=1.0,
        on_time=2,
        made_contact=made_contact,
        outcome=outcome,
        pitch_type="FOUR-SEAM",
        speed_mph=93.0,
        contact_quality=0.88,
        vertical_offset_px=-9.0,
        exit_velocity_mph=98.0,
        batted_ball_type="LINER",
    )
    fields.update(kw)
    return SwingRecord(**fields)


class FakeGame:
    internal_width, internal_height = SCREEN


# ---- from_simulation, the seam onto the live pitch ---------------------------

class _FakeSim:
    """The subset of `PitchSimulation` that `from_simulation` reads.

    Written out rather than mocked so that renaming a field on the real
    simulation makes this fail loudly instead of quietly producing a record
    full of `None`.
    """

    def __init__(self, **kw):
        self.trajectory = make_trajectory()
        self.starttime = 10_000
        self.windup = 1100
        self.traveltime = self.trajectory.travel_time_ms
        self.swing_starttime = int(self.starttime + self.windup
                                   + self.traveltime - bat_path.SWING_DURATION_MS)
        self.swing_type = 1
        self.on_time = 2
        self.made_contact = "hit"
        self.outcome = "SINGLE"
        self.pitchtype = "SLIDER"
        self.speed_mph = 88.0
        self.contact_quality = 0.9
        self.vertical_offset_in = -6.0
        self.exit_velocity_mph = 101.0
        self.batted_ball_type = "LINER"
        self.aim_screen_at_swing = (630, 470)
        self.aim_screen_at_contact = (632, 472)
        self.ball_screen_at_contact = (628, 480)
        self._foul_quality = 0.4
        self._foul_vertical_offset = 14.0
        self.__dict__.update(kw)
        self.game = self

    # the two helpers from_simulation calls back into
    def _timing_windows(self):
        return 30.0, 60.0

    def _signed_timing_ms(self):
        if self.swing_starttime is None:
            return None
        return ((self.swing_starttime + bat_path.SWING_DURATION_MS)
                - (self.starttime + self.windup + self.traveltime))

    # the `game` surface it reaches through
    class _Batter:
        @staticmethod
        def get_handedness():
            return "R"

    batter = _Batter()

    class _Settings:
        @staticmethod
        def get_difficulty_multipliers():
            return {"contact_zone_size": 1.0}

    settings_manager = _Settings()


def test_from_simulation_builds_a_usable_record():
    from strikefactor.gameplay import swing_record
    rec = swing_record.from_simulation(_FakeSim())
    assert rec is not None
    assert rec.bat_arrival_s == pytest.approx(rec.travel_time_s, abs=1e-3)
    # Not exactly zero: `swing_starttime` is whole milliseconds, and one ms of
    # rounding is 0.13 ft of ball at 90 mph. That the residual is *this* small
    # is the check — anything larger means the arrival clock is misaligned.
    assert abs(rec.contact_depth_ft) < 0.2
    assert rec.pitch_type == "SLIDER"
    rec.bat_swing()
    rec.perfect_swing()


def test_a_taken_pitch_produces_no_record():
    """And so leaves the previous swing on `Game.last_swing` — the review key
    has to keep working after a take."""
    from strikefactor.gameplay import swing_record
    assert swing_record.from_simulation(
        _FakeSim(swing_type=0, made_contact="no_swing")) is None
    assert swing_record.from_simulation(_FakeSim(swing_starttime=None)) is None


def test_a_foul_reads_its_own_contact_metrics():
    """`contact_quality` is NULL on fouls by design — they never run the hit
    pipeline — so the record has to take the foul-specific fields or the
    panel shows a stale number from the previous ball in play."""
    from strikefactor.gameplay import swing_record
    rec = swing_record.from_simulation(_FakeSim(made_contact="fouled"))
    assert rec.contact_quality == pytest.approx(0.4)
    assert rec.vertical_offset_px == pytest.approx(14.0)


def test_the_aim_at_contact_is_preferred_over_the_aim_at_commit():
    """The engine tested the cursor as it was when the barrel arrived."""
    from strikefactor.gameplay import swing_record
    from strikefactor.utils.pitch_physics import DEFAULT_CAMERA
    rec = swing_record.from_simulation(_FakeSim())
    assert rec.aim_ft == DEFAULT_CAMERA.screen_to_world_at_plate(632, 472)


def test_a_mistimed_whiff_falls_back_to_the_aim_at_commit():
    """`on_time == 0` never reaches the contact frame, so there is no
    arrival-time cursor — but the swing still has to be reviewable."""
    from strikefactor.gameplay import swing_record
    rec = swing_record.from_simulation(
        _FakeSim(on_time=0, made_contact="swung_and_miss",
                 aim_screen_at_contact=None))
    assert rec is not None
    assert rec.aim_ft[0] != 0.0 or rec.aim_ft[1] != 0.0


# ---- Contact depth is measured, not modelled --------------------------------

def test_a_perfectly_timed_swing_meets_the_ball_at_the_plate():
    assert make_record(0.0).contact_depth_ft == pytest.approx(0.0, abs=1e-6)


def test_an_early_swing_meets_the_ball_out_in_front():
    assert make_record(-30.0).contact_depth_ft > 0


def test_a_late_swing_lets_the_ball_get_deep():
    """The depth must be allowed to go negative. Clamping it at the plate —
    which is what the engine's own contact test does, since
    `_update_ball_position` clamps `t` at travel_time — would show every late
    swing meeting the ball exactly at the plate, the one thing that cannot
    have happened."""
    assert make_record(+30.0).contact_depth_ft < 0


def test_depth_is_monotonic_in_timing():
    depths = [make_record(ms).contact_depth_ft for ms in range(60, -61, -10)]
    assert depths == sorted(depths)


def test_typical_timing_error_lands_feet_from_the_plate_not_inches():
    """Median |timing| in `strikefactor.db` is ~21 ms and p90 is ~47 ms. At
    ~90 mph that is feet of separation, which is what makes the side view
    legible. If this ever reads in inches, the depth math is wrong."""
    assert 2.0 < abs(make_record(-21.0).contact_depth_ft) < 4.0
    assert 5.0 < abs(make_record(-47.0).contact_depth_ft) < 9.0


def test_the_replay_uses_the_same_trajectory_the_pitch_was_flown_with():
    """No second model of where the ball was — the fault CLAUDE.md tracks
    through the batted-ball code."""
    rec = make_record(-25.0)
    assert rec.contact_depth_ft == rec.trajectory.position_at(rec.bat_arrival_s)[1]


# ---- Labels and units -------------------------------------------------------

@pytest.mark.parametrize("ms,label", [
    (-45.0, "EARLY"), (45.0, "LATE"),
    (-12.0, "ON TIME"), (12.0, "ON TIME"), (0.0, "ON TIME"),
])
def test_timing_label_respects_this_swings_own_window(ms, label):
    assert make_record(ms).timing_label == label


def test_the_window_is_the_difficulty_scaled_one_not_a_constant():
    """`perfect_ms` runs 30 x 1.5 at ROOKIE down to 30 x 0.4 at HALL OF FAME.
    A 40 ms swing is on time at one and late at the other."""
    assert make_record(40.0, perfect_ms=45.0, foul_ms=90.0).timing_label == "ON TIME"
    assert make_record(40.0, perfect_ms=12.0, foul_ms=24.0).timing_label == "LATE"


def test_vertical_offset_converts_pixels_to_real_inches():
    """The DB column is named `vertical_offset_in` but holds screen pixels —
    a comment in `pitch_simulation` admits it. The replay must convert rather
    than print the raw number as inches."""
    rec = make_record(vertical_offset_px=25.0)
    assert rec.vertical_offset_inches == pytest.approx(25.0 * (30.0 / 2250.0) * 12.0)
    assert 3.0 < rec.vertical_offset_inches < 4.5


def test_vertical_offset_is_none_when_it_was_never_measured():
    assert make_record(vertical_offset_px=None).vertical_offset_inches is None


# ---- The bats ---------------------------------------------------------------

def test_the_bat_is_built_at_the_measured_depth():
    rec = make_record(-30.0)
    contact = rec.bat_swing().state_at(bat_path.SWING_DURATION_S).sweet_spot_ft
    assert contact[1] == pytest.approx(rec.contact_depth_ft)
    assert contact[0] == pytest.approx(rec.aim_ft[0])


@pytest.mark.parametrize("ms", [-45.0, -15.0, 0.0, 30.0])
def test_the_drawn_bat_and_the_reported_offset_agree(ms):
    """The picture must not contradict the numbers. `aim_ft` is the cursor
    resolved at the *plate*, but the ball is 6.4 inches higher at a contact
    point 5.6 ft out front — so drawing the bat at its plate height put it
    half a foot under a ball the panel said it was 1.4 inches over."""
    rec = make_record(ms)
    contact = rec.bat_swing().state_at(bat_path.SWING_DURATION_S).sweet_spot_ft
    ball_z = rec.ball_at(rec.bat_arrival_s)[2]
    drawn_offset_in = (contact[2] - ball_z) * 12.0
    # Reported offset is bat-below-ball positive; drawn is z-up.
    assert drawn_offset_in == pytest.approx(-rec.vertical_offset_inches, abs=1e-6)


def test_a_swing_with_no_measured_offset_falls_back_to_the_aim_point():
    """A mistimed whiff never reaches the geometry test, so there is no
    relationship to preserve and the cursor height is all there is."""
    rec = make_record(-70.0, vertical_offset_px=None)
    contact = rec.bat_swing().state_at(bat_path.SWING_DURATION_S).sweet_spot_ft
    assert contact[2] == pytest.approx(rec.aim_ft[1])


def test_the_ghost_bat_differs_from_the_real_one_only_in_timing():
    """The reference the player reads the error off: the same swing, aimed the
    same way, that met the ball at the plate. It holds the *alignment* fixed,
    not the absolute height — the ball is lower at the plate than out front,
    so a bat with the same offset to it is lower too."""
    rec = make_record(-30.0)
    real = rec.bat_swing().state_at(bat_path.SWING_DURATION_S).sweet_spot_ft
    ghost = rec.perfect_swing().state_at(bat_path.SWING_DURATION_S).sweet_spot_ft
    assert ghost[1] == pytest.approx(0.0)
    assert ghost[0] == pytest.approx(real[0])
    assert abs(real[1] - ghost[1]) > 1.0
    ghost_offset = ghost[2] - rec.ball_at(rec.travel_time_s)[2]
    assert ghost_offset == pytest.approx(rec.vertical_offset_ft)


def test_a_perfectly_timed_swing_has_no_daylight_from_its_ghost():
    rec = make_record(0.0)
    real = rec.bat_swing().state_at(bat_path.SWING_DURATION_S).sweet_spot_ft
    ghost = rec.perfect_swing().state_at(bat_path.SWING_DURATION_S).sweet_spot_ft
    assert math.dist(real, ghost) == pytest.approx(0.0, abs=1e-6)


# ---- The overlay ------------------------------------------------------------

@pytest.fixture
def overlay():
    pygame.display.init()
    pygame.font.init()
    return SwingReplayOverlay(FakeGame())


def _run(overlay, record, ms=4000, step=16):
    surface = pygame.Surface(SCREEN)
    overlay.trigger(record=record)
    elapsed = 0
    while elapsed < ms:
        overlay.update(step)
        surface.fill((0, 0, 0))
        overlay.render(surface)
        elapsed += step
    return surface


@pytest.mark.parametrize("made_contact,outcome", [
    ("hit", "HOME RUN"), ("fouled", "FOUL BALL"),
    ("swung_and_miss", "STRIKE"), ("hit", "SINGLE"),
])
def test_every_swing_outcome_renders(overlay, made_contact, outcome):
    _run(overlay, make_record(-20.0, made_contact=made_contact, outcome=outcome))


@pytest.mark.parametrize("ms", [-90.0, -30.0, 0.0, 30.0, 90.0])
@pytest.mark.parametrize("hand", ["R", "L"])
def test_both_views_render_across_the_timing_range(overlay, ms, hand):
    for view in (0, 1):
        overlay.trigger(record=make_record(ms, hand=hand))
        overlay._view = view
        surface = pygame.Surface(SCREEN)
        for _ in range(60):
            overlay.update(16)
            overlay.render(surface)


def test_a_swing_with_no_measured_contact_still_renders(overlay):
    """A mistimed whiff never reaches `_evaluate_contact`, so it has no
    quality, no offset and no exit velocity — and is exactly the swing a
    player most needs explained."""
    _run(overlay, make_record(-70.0, made_contact="swung_and_miss",
                              outcome="STRIKE", on_time=0,
                              contact_quality=None, vertical_offset_px=None,
                              exit_velocity_mph=None, batted_ball_type=None))


def test_the_overlay_closes_itself(overlay):
    overlay.trigger(record=make_record())
    assert overlay.is_active()
    overlay.dismiss()
    for _ in range(40):
        overlay.update(16)
    assert not overlay.is_active()


def test_escape_closes_and_tab_toggles_the_view(overlay):
    overlay.trigger(record=make_record())
    start = overlay._view
    assert overlay.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
    assert overlay._view != start
    assert overlay.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    for _ in range(40):
        overlay.update(16)
    assert not overlay.is_active()


def test_scrubbing_pauses_and_moves_the_clock(overlay):
    overlay.trigger(record=make_record())
    for _ in range(80):
        overlay.update(16)
    before = overlay._elapsed_ms
    overlay.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT))
    assert overlay._paused
    assert overlay._elapsed_ms < before
    overlay.update(16)
    assert overlay._elapsed_ms == pytest.approx(before - (2600 - 420) // 40, abs=1)


def test_space_restarts_a_finished_replay(overlay):
    overlay.trigger(record=make_record())
    for _ in range(300):
        overlay.update(16)
    assert overlay._elapsed_ms == 3100
    overlay.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    assert overlay._elapsed_ms < 3100
    assert not overlay._paused


# ---- The camera stands where the label says --------------------------------

def test_the_side_view_is_a_third_base_camera(overlay):
    """Pitcher on the left, catcher on the right.

    It was drawn the other way round: `+y` ran rightward, which is the view
    from the *first* base line under a caption reading `PITCHER ->`. Cheap to
    get wrong and impossible to notice from inside the view, since a mirrored
    swing is still a swing — it is only wrong against the ball, the batter and
    every other side-on picture of a swing ever drawn.
    """
    overlay.trigger(record=make_record())
    overlay._view = 0
    mound = overlay._project((0.0, 6.0, 3.0))
    plate = overlay._project((0.0, 0.0, 3.0))
    backstop = overlay._project((0.0, -6.0, 3.0))
    assert mound[0] < plate[0] < backstop[0]
    # And up is up: the vertical axis is height, flipped for screen y.
    assert overlay._project((0.0, 0.0, 4.0))[1] < overlay._project((0.0, 0.0, 1.0))[1]


def test_the_overhead_view_is_a_birds_eye_not_a_worms_eye(overlay):
    """Third base left, first base right, pitcher up — matching the labels,
    which the projection contradicted: `+x` *is* the third-base side (a
    right-hander's pivot is at `+1.53`) and it was drawn on the right."""
    overlay.trigger(record=make_record())
    overlay._view = 1
    third = overlay._project((3.0, 0.0, 0.0))
    first = overlay._project((-3.0, 0.0, 0.0))
    assert third[0] < first[0]
    assert overlay._project((0.0, 6.0, 0.0))[1] < overlay._project((0.0, -6.0, 0.0))[1]


@pytest.mark.parametrize("hand,expect_left", [("R", True), ("L", False)])
def test_the_batter_stands_on_their_own_side_of_the_plate(overlay, hand, expect_left):
    """The end-to-end check on both the projection and the swing's spin: a
    right-hander's hands are on the third-base side, which is screen left from
    above. Mirror either one and the batter swings from the wrong box."""
    rec = make_record(hand=hand)
    overlay.trigger(record=rec)
    overlay._view = 1
    knob = rec.bat_swing().state_at(bat_path.SWING_DURATION_S).knob_ft
    plate = overlay._project((0.0, 0.0, 0.0))
    assert (overlay._project(knob)[0] < plate[0]) is expect_left


# ---- The bat is drawn as a bat ----------------------------------------------

class _Bat:
    """The two attributes `_bat_silhouette` reads off a `BatState`."""

    def __init__(self, knob_ft, barrel_ft):
        self.knob_ft = knob_ft
        self.barrel_ft = barrel_ft


def _half_widths(polygon):
    """Half-width in pixels at each profile station, out of the silhouette.

    The polygon is the near edge followed by the far edge reversed, so the
    two points a station apart are `i` and `-1 - i`.
    """
    n = len(polygon) // 2
    return [math.dist(polygon[i], polygon[-1 - i]) / 2.0 for i in range(n)]


@pytest.mark.parametrize("view", [0, 1])
def test_the_drawn_bat_spans_exactly_the_projected_bat_length(overlay, view):
    """Caps are inset by their own radii, so the silhouette ends where the
    model's knob and barrel project to. Drawn without the inset the bat grows
    by an end cap at each end every time it is drawn — three inches of bat
    the collision geometry does not have."""
    rec = make_record(-21.0)
    overlay.trigger(record=rec)
    overlay._view = view
    state = rec.bat_swing().state_at(bat_path.SWING_DURATION_S * 0.6)
    polygon, ((lo, r_lo), (hi, r_hi)) = overlay._bat_silhouette(state)
    assert polygon is not None
    projected = math.dist(overlay._project(state.knob_ft),
                          overlay._project(state.barrel_ft))
    assert math.dist(lo, hi) + r_lo + r_hi == pytest.approx(projected, abs=0.5)


@pytest.mark.parametrize("view", [0, 1])
def test_the_silhouette_is_a_bat_and_not_a_cone(overlay, view):
    """The shape's whole signature: a knob flare, a thin handle held a third
    of the way out, and a barrel two and a half times the handle. Recovered
    as real inches from the drawn pixels, so it pins the profile *and* the
    scaling — a fixed pixel width would pass a ratio test but report a
    different real bat in each view."""
    rec = make_record(-21.0)
    overlay.trigger(record=rec)
    overlay._view = view
    state = rec.bat_swing().state_at(bat_path.SWING_DURATION_S * 0.6)
    polygon, _ = overlay._bat_silhouette(state)
    inches = [2.0 * hw / overlay._bat_scale() * 12.0
              for hw in _half_widths(polygon)]

    knob, handle, barrel = inches[0], min(inches), max(inches)
    assert 2.0 < knob < 2.3            # ~2.1 in across the knob
    assert 0.9 < handle < 1.15         # ~1 in through the handle
    assert 2.5 < barrel <= 2.61        # the MLB maximum, and not over it
    assert inches[-1] == pytest.approx(barrel, abs=0.05), "tip must be barrel"
    # Concave, not conical: still thin at a third of the way out, and
    # essentially parallel-sided over the last fifth.
    assert inches[3] < 1.2 * handle
    assert inches[-1] - inches[-2] < 0.1


def test_the_bat_keeps_one_thickness_as_it_turns(overlay):
    """What the single `_bat_scale` buys. Projected honestly, thickness is a
    function of which way the bat points — 12 px across the screen against 5
    px down it in the OVERHEAD view — so the bat would swell and thin through
    the swing, which no real bat does."""
    rec = make_record(-21.0)
    overlay.trigger(record=rec)
    overlay._view = 1
    swing = rec.bat_swing()
    widest = []
    for i in range(1, 12):
        polygon, _ = overlay._bat_silhouette(
            swing.state_at(bat_path.SWING_DURATION_S * i / 12.0))
        if polygon is not None:
            widest.append(max(_half_widths(polygon)))
    assert len(widest) > 6
    assert max(widest) == pytest.approx(min(widest), abs=0.01)


def test_a_bat_pointed_at_the_camera_draws_as_its_end_caps(overlay):
    """The SIDE view looks down x and a bat at contact points largely along
    it, so end-on is ordinary rather than exceptional. There is no length to
    taper along and the insets would cross over, so the caps are the whole
    picture — and drawing must not fall over or invert the polygon."""
    overlay.trigger(record=make_record())
    overlay._view = 0
    polygon, caps = overlay._bat_silhouette(
        _Bat((1.4, 0.0, 3.0), (1.4 - bat_path.BAT_LENGTH_FT, 0.0, 3.0)))
    assert polygon is None
    assert len(caps) == 2
    surface = pygame.Surface(SCREEN)
    overlay._draw_bat(surface, 0.0, state=_Bat((1.4, 0.0, 3.0),
                                               (1.4 - bat_path.BAT_LENGTH_FT,
                                                0.0, 3.0)))


# ---- Drawing stays inside the panel -----------------------------------------

def _lit_bounds(surface):
    """Bounding box of everything actually drawn.

    Not `get_bounding_rect`: the overlay lays a full-screen dim down first,
    and (0, 0, 0, alpha) over black is still black, so on an opaque surface
    that helper reports the whole screen no matter what was drawn. The dim is
    the thing we need to see *through*, so scan for non-black pixels instead.
    """
    import numpy as np
    from pygame import surfarray
    lit = np.argwhere(surfarray.array3d(surface).max(axis=2) > 0)
    if not len(lit):
        return None
    (x0, y0), (x1, y1) = lit.min(axis=0), lit.max(axis=0)
    return pygame.Rect(int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1))


@pytest.mark.parametrize("ms", [-90.0, -21.0, 90.0])
@pytest.mark.parametrize("view", [0, 1])
def test_nothing_is_drawn_outside_the_panel(overlay, ms, view):
    """The views clip to their own rect. A bat that met the ball 9 ft out
    front runs off the end of the field of view, and without the clip it
    scribbles across the dimmed gameplay behind the panel.

    Checked over the whole bounding box rather than by probing corners,
    because a spill that happens at one row height slips past corners — the
    same reason `test_pitching_box_panel` measures it this way.
    """
    overlay.trigger(record=make_record(ms))
    overlay._view = view
    surface = pygame.Surface(SCREEN)
    for _ in range(250):
        overlay.update(16)
        surface.fill((0, 0, 0))
        overlay.render(surface)
    lit = _lit_bounds(surface)
    assert lit is not None, "the overlay drew nothing"
    assert overlay._panel_rect().contains(lit), f"{lit} escaped {overlay._panel_rect()}"
