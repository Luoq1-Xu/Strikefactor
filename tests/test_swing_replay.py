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

from strikefactor.gameplay import bat_contact, bat_path, spray
from strikefactor.gameplay.swing_record import SwingRecord
from strikefactor.ui import swing_replay_overlay as sro
from strikefactor.ui.swing_replay_overlay import SwingReplayOverlay
from strikefactor.utils.pitch_physics import DEFAULT_CAMERA, PitchTrajectory

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


def barrel_depth(aim=(0.0, 2.5), hand="R", traj=None):
    """Where this cursor puts the barrel, in feet in front of the plate.

    Through `aim_at_pitch`, because that is the engine's path: the cursor is
    resolved against the pitch before the bat is built, so a bat built from
    the raw cursor is not the bat that was swung.
    """
    traj = traj if traj is not None else make_trajectory()
    return bat_path.swing(bat_contact.aim_at_pitch(aim, traj, hand),
                          hand).contact_depth_ft


def make_record(timing_ms=0.0, made_contact="hit", outcome="SINGLE",
                hand="R", swing_type=1, **kw):
    """A SwingRecord with `timing_ms` of error. Negative early, positive late.

    Zero is the ball reaching *the barrel's own contact depth*, not the plate:
    the bat meets the ball a couple of feet out in front, and grading against
    the plate reported a perfectly struck ball as ~17 ms early.
    """
    traj = make_trajectory()
    aim = kw.get("aim_ft", (0.0, 2.5))
    due = traj.time_at_depth(barrel_depth(aim, hand, traj))
    fields = dict(
        trajectory=traj,
        travel_time_s=traj.travel_time,
        bat_arrival_s=due + timing_ms / 1000.0,
        signed_timing_ms=timing_ms,
        aim_ft=(0.0, 2.5),
        handedness=hand,
        swing_type=swing_type,
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
        # Built the way the engine builds it: the cursor, resolved against
        # this pitch and pulled toward it by the difficulty's assist, then
        # handed to `bat_path`.
        self.aim_assist = 0.0
        self.zone_size_mult = 1.0
        self.timing_window_mult = 1.0
        self.swing_aim_ft = bat_contact.aim_at_pitch(
            (0.0, 2.5), self.trajectory, "R", assist=self.aim_assist)
        self.bat_swing = bat_path.swing(self.swing_aim_ft, "R")
        self.barrel_depth_ft = self.bat_swing.contact_depth_ft
        self.contact = None
        # A perfectly timed swing: the barrel reaches its contact pose exactly
        # as the ball reaches the depth it arrives at.
        due_ms = self.trajectory.time_at_depth(self.barrel_depth_ft) * 1000.0
        self.swing_starttime = int(self.starttime + self.windup + due_ms
                                   - bat_path.SWING_DURATION_MS)
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

    # the helper from_simulation calls back into
    def _signed_timing_ms(self):
        if self.swing_starttime is None:
            return None
        due_ms = (self.starttime + self.windup
                  + self.trajectory.time_at_depth(self.barrel_depth_ft) * 1000.0)
        return (self.swing_starttime + bat_path.SWING_DURATION_MS) - due_ms

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
    # A perfectly timed swing puts the ball where the barrel is, which is out
    # in front of the plate rather than on it.
    assert rec.barrel_depth_ft > 1.5
    # Not exactly zero: `swing_starttime` is whole milliseconds, and one ms of
    # rounding is 0.13 ft of ball at 90 mph. That the residual is *this* small
    # is the check — anything larger means the arrival clock is misaligned.
    assert abs(rec.depth_gap_ft) < 0.2
    assert rec.pitch_type == "SLIDER"
    rec.bat_swing()
    rec.bat_state_at_ball_arrival()


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


def test_the_aim_at_commit_is_preferred_over_the_aim_at_contact():
    """The whole swing is decided when the key goes down.

    `_handle_swing_input` builds the bat from the cursor as it was then and
    sweeps it there and then, so the arrival-time cursor names a bat that was
    never swung. Replaying that one would show a swing the player did not
    make — and it used to, because this preference ran the other way, left
    over from the engine that tested a rectangle 150 ms after the keypress
    against wherever the mouse had drifted to by then.
    """
    from strikefactor.gameplay import swing_record
    rec = swing_record.from_simulation(_FakeSim())
    assert rec.aim_ft == DEFAULT_CAMERA.screen_to_world_at_plate(630, 470)


def test_the_replayed_bat_is_the_assisted_bat():
    """The replay must show the bat that was swung, assist included.

    `swing_aim_ft()` recomputes the resolved aim rather than carrying it, so
    that the drawn bat cannot drift away from the swept one. That argument only
    holds if every input to the recompute travels with the record — and
    `aim_assist` is a *difficulty setting*, so re-reading it at replay time
    would show a player who changed difficulty a bat nobody swung, the same
    failure as preferring the cursor at bat arrival over the cursor at commit.
    """
    from strikefactor.gameplay import bat_contact, swing_record
    sim = _FakeSim(aim_assist=0.65)
    # Rebuild the commit exactly as `_handle_swing_input` does, assist and all.
    sim.swing_aim_ft = bat_contact.aim_at_pitch(
        DEFAULT_CAMERA.screen_to_world_at_plate(*sim.aim_screen_at_swing),
        sim.trajectory, "R", assist=sim.aim_assist)

    rec = swing_record.from_simulation(sim)
    assert rec.aim_assist == 0.65
    assert rec.swing_aim_ft() == pytest.approx(sim.swing_aim_ft)
    # And it is genuinely a different bat from the unassisted one, or this
    # test would pass for the wrong reason.
    unassisted = bat_contact.aim_at_pitch(rec.aim_ft, rec.trajectory, "R")
    assert rec.swing_aim_ft() != pytest.approx(unassisted)


def test_a_record_with_only_an_arrival_cursor_still_replays():
    """The commit cursor is preferred, not required: a record built without
    one still has to be reviewable rather than vanish."""
    from strikefactor.gameplay import swing_record
    rec = swing_record.from_simulation(
        _FakeSim(on_time=0, made_contact="swung_and_miss",
                 aim_screen_at_swing=None))
    assert rec is not None
    assert rec.aim_ft[0] != 0.0 or rec.aim_ft[1] != 0.0


# ---- Contact depth is measured, not modelled --------------------------------

def test_a_perfectly_timed_swing_meets_the_ball_where_the_barrel_is():
    """Not at the plate. The barrel arrives a couple of feet out in front —
    further on a pitch inside, which is more foreshortened — and a swing is on
    time when the ball is *there*, which is the datum `_signed_timing_ms` was
    moved onto."""
    rec = make_record(0.0)
    assert rec.barrel_depth_ft == pytest.approx(barrel_depth((0.0, 2.5), "R"))
    assert rec.contact_depth_ft == pytest.approx(rec.barrel_depth_ft, abs=1e-6)
    assert rec.depth_gap_ft == pytest.approx(0.0, abs=1e-6)


def test_an_early_swing_leaves_the_ball_still_out_in_front():
    """The bat got there first, so the ball has not arrived yet."""
    rec = make_record(-30.0)
    assert rec.contact_depth_ft > rec.barrel_depth_ft
    assert rec.depth_gap_ft < 0


def test_a_late_swing_lets_the_ball_get_deep():
    """The depth must be allowed to go past the plate. Clamping it — which is
    what the engine's *old* contact test did, since `_update_ball_position`
    clamps `t` at travel_time — would show every late swing meeting the ball
    exactly at the plate, the one thing that cannot have happened."""
    rec = make_record(+30.0)
    assert rec.contact_depth_ft < rec.barrel_depth_ft
    assert rec.depth_gap_ft > 0


def test_depth_is_monotonic_in_timing():
    depths = [make_record(ms).contact_depth_ft for ms in range(60, -61, -10)]
    assert depths == sorted(depths)


def test_typical_timing_error_lands_feet_apart_not_inches():
    """Median |timing| in `strikefactor.db` is ~21 ms and p90 is ~47 ms. At
    ~90 mph that is feet of separation between barrel and ball, which is what
    makes the side view legible. If this ever reads in inches, the depth math
    is wrong."""
    assert 2.0 < abs(make_record(-21.0).depth_gap_ft) < 4.0
    assert 5.0 < abs(make_record(-47.0).depth_gap_ft) < 9.0


def test_the_replay_uses_the_same_trajectory_the_pitch_was_flown_with():
    """No second model of where the ball was — the fault CLAUDE.md tracks
    through the batted-ball code."""
    rec = make_record(-25.0)
    assert rec.contact_depth_ft == rec.trajectory.position_at(rec.bat_arrival_s)[1]


# ---- The two instants a swing names ----------------------------------------
#
# `bat_arrival_s` is when the barrel reached its contact pose; `contact_time_s`
# is when the sweep found the bat and the ball at their closest. They are the
# same only on a squared-up swing, and the replay froze on the first while
# marking the second, which is how a HOME RUN came to be drawn with the bat
# eight feet from the ball.


def struck_record(timing_ms, speed_mph=93.0, zone=1.4, window=1.5,
                  aim_high_in=0.0):
    """A record carrying the `Contact` a real sweep produced.

    `make_record` leaves `contact` None, which is the whiff path; nothing
    below is exercised without an actual sweep behind it. Defaults are ROOKIE,
    where the timing assist is largest and the effect most visible.
    """
    traj = make_trajectory(speed_mph=speed_mph)
    cursor = (0.0, 2.5 + aim_high_in / 12.0)
    aim = bat_contact.aim_at_pitch(cursor, traj, "R")
    swing = bat_path.swing(aim, "R")
    due = traj.time_at_depth(swing.contact_depth_ft)
    start = due - bat_path.SWING_DURATION_S + timing_ms / 1000.0
    contact = bat_contact.resolve_contact(
        swing, traj, start, zone_size_mult=zone, timing_window_mult=window)
    assert contact is not None, "the fixture must actually make contact"
    # The **raw cursor**, not `aim`. `SwingRecord.aim_ft` is what the player
    # pointed at and the record resolves it itself (`swing_aim_ft`), so handing
    # it the resolved aim resolves twice — a few inches of correction applied
    # again, which is enough to leave the record's own swing several inches off
    # the one the contact above was swept from. That made `timing_windows_ms`
    # report no fair window at all, so a test asserting "this reads LATE"
    # passed for the wrong reason.
    # The multipliers have to reach the record too, or it describes a
    # different difficulty from the one the contact above was swept at: the
    # assist marker would read the contact's ROOKIE slide while the budget
    # ticks drew an AMATEUR budget.
    return make_record(timing_ms, aim_ft=cursor, contact=contact,
                       resolved_aim_ft=aim,
                       contact_quality=contact.quality,
                       vertical_offset_px=(contact.vertical_offset_ft
                                           / DEFAULT_CAMERA.ft_per_px_z),
                       zone_size_mult=zone, timing_window_mult=window,
                       bat_arrival_s=start + bat_path.SWING_DURATION_S), contact


def _axis_gap_ft(state, ball):
    """Feet from the ball's centre to the nearest point on the bat's axis."""
    knob, tip = bat_path.bat_solid_axis(state)
    axis = [tip[i] - knob[i] for i in range(3)]
    rel = [ball[i] - knob[i] for i in range(3)]
    dd = sum(v * v for v in axis)
    u = max(0.0, min(1.0, sum(rel[i] * axis[i] for i in range(3)) / dd))
    return math.dist([knob[i] + axis[i] * u for i in range(3)], ball)


@pytest.mark.parametrize("ms", [-40.0, -20.0, 0.0, 20.0, 40.0])
def test_the_freeze_is_the_instant_the_bat_and_the_ball_met(ms):
    """The replay's clock ends at contact, not at bat arrival.

    They are different instants by up to ~25 ms of pitch time, and at 101 mph
    that is six feet of ball. The clip used to run past a late contact and stop
    short of an early one, so the frame the player studies had a bat, a ball
    and a crosshair in three different places.
    """
    rec, contact = struck_record(ms)
    assert rec.contact_time_s == pytest.approx(contact.pitch_t_s)
    assert rec.struck_depth_ft == pytest.approx(contact.depth_ft)
    if ms != 0.0:
        assert rec.contact_time_s != pytest.approx(rec.bat_arrival_s, abs=1e-4)


def test_a_swing_with_no_contact_freezes_where_the_barrel_arrived():
    """A whiff names one instant only, and the daylight to the ball there is
    the finding rather than an artefact."""
    rec = make_record(-70.0, made_contact="swung_and_miss", contact=None)
    assert rec.contact_time_s == rec.bat_arrival_s
    assert rec.struck_depth_ft == rec.contact_depth_ft
    assert rec.contact_reach_ft is None


# ---- Where a clip stops -----------------------------------------------------

@pytest.mark.parametrize("ms", [-100.0, -70.0, -40.0, -10.0])
def test_a_missed_swing_is_replayed_until_the_ball_reaches_the_plate(ms):
    """The reported fault: an early miss froze with the ball in mid-air.

    `contact_time_s` answers a swing that missed with the barrel's arrival,
    which is a fact about the bat — the ball is still feet out in front there,
    so the pitch stopped happening part way through. It runs to the plate now.
    """
    rec = make_record(ms, made_contact="swung_and_miss", outcome="STRIKE",
                      contact=None)
    assert rec.clip_end_s >= rec.travel_time_s
    assert rec.ball_at(rec.clip_end_s)[1] == pytest.approx(0.0, abs=1e-3)
    # And the bat got there first: it is the ball that is still travelling.
    assert rec.clip_end_s > rec.bat_arrival_s


@pytest.mark.parametrize("ms", [20.0, 40.0, 90.0])
def test_a_late_miss_still_ends_where_the_barrel_arrived(ms):
    """The plate is a floor, never a ceiling. A swing late enough that the
    barrel arrived after the ball was already by keeps its own arrival — the
    later instant, with the ball genuinely past the plate and into the mitt,
    which is what a late miss looks like."""
    rec = make_record(ms, made_contact="swung_and_miss", outcome="STRIKE",
                      contact=None)
    assert rec.bat_arrival_s > rec.travel_time_s
    assert rec.clip_end_s == rec.bat_arrival_s
    assert rec.ball_at(rec.clip_end_s)[1] < 0.0


@pytest.mark.parametrize("ms", [-40.0, 0.0, 40.0])
def test_a_struck_swing_still_ends_at_contact(ms):
    """Nothing about the extension may reach a swing that met the ball: the
    frozen frame is the two of them touching, and a tail past it drags the
    ball away from the mark that names it."""
    rec, contact = struck_record(ms)
    assert rec.clip_end_s == pytest.approx(rec.replay_contact.pitch_t_s)


@pytest.mark.parametrize("ms", [-40.0, -20.0, 20.0, 40.0])
def test_the_freeze_leaves_nothing_but_the_cushion_between_bat_and_ball(ms):
    """The regression pin, stated the way the screenshots showed it: how far
    apart the bat and the ball are in the frame that gets held.

    Two things are asserted, and the second is the stronger one. Freezing at
    contact rather than at bat arrival always closes daylight; and what is left
    is *entirely* the model's own tolerance — the drawn gap comes back to
    `surface_gap_ft` plus the two radii, so there is no rendering error left in
    the frame. Shrinking that is a difficulty decision
    (`bat_contact.BASE_MARGIN_FT` and `contact_zone_size`), not a drawing one.
    """
    rec, contact = struck_record(ms)
    swing = rec.bat_swing()
    at_contact = _axis_gap_ft(
        swing.state_at(contact.swing_t_s), contact.ball_ft)
    at_arrival = _axis_gap_ft(
        swing.state_at(bat_path.SWING_DURATION_S),
        rec.ball_at(rec.bat_arrival_s))
    assert at_contact < at_arrival
    # The bat's radius plus the ball's is 0.23 ft; the slack is for the
    # difference between the metric-solved station and a plain projection.
    assert at_contact - max(0.0, contact.surface_gap_ft) < 0.4


@pytest.mark.parametrize("ms", [20.0, 30.0, 40.0])
def test_a_late_swing_is_where_the_clock_error_was_worst(ms):
    """Which is what the screenshots were: a swing 48 ms late, drawn with six
    feet of daylight under a HOME RUN banner.

    The asymmetry is real and worth pinning. A late bat catches the ball
    *earlier* in its arc, so the old freeze ran a long way past the meeting;
    an early bat catches it a few milliseconds after arrival and then runs
    away, so most of that gap was the cushion all along and the freeze can only
    take the rest.
    """
    rec, contact = struck_record(ms)
    swing = rec.bat_swing()
    at_contact = _axis_gap_ft(
        swing.state_at(contact.swing_t_s), contact.ball_ft)
    at_arrival = _axis_gap_ft(
        swing.state_at(bat_path.SWING_DURATION_S),
        rec.ball_at(rec.bat_arrival_s))
    assert at_contact < 0.4 * at_arrival


@pytest.mark.parametrize("ms", [-40.0, -20.0, 0.0, 20.0, 35.0, 40.0])
def test_the_bat_and_the_ball_actually_touch(ms):
    """**The pin this whole rewrite exists for.**

    A foul ball or a ball in play means the bat touched the ball, and the
    frozen frame has to be able to show that. It could not before: the timing
    forgiveness was spent as a reach along the ball's flight line worth
    `cushion x ball speed`, so `surface_gap_ft` ran to *feet* — the screenshot
    that started this read `REACH 2.6 FT` under a FOUL banner, and 63% of
    recorded contacts had visible daylight.

    Difficulty forgiveness now moves the swing and the final sweep is strict,
    so the physical surface gap itself is the invariant.
    """
    rec, contact = struck_record(ms)
    assert contact.gap_ft <= 0.0
    assert contact.surface_gap_ft <= 1e-9
    assert rec.contact_reach_ft == pytest.approx(contact.surface_gap_ft)

    squared, dead_on = struck_record(0.0)
    assert dead_on.surface_gap_ft < 0.0, "a squared-up swing overlaps the ball"
    assert squared.contact_reach_ft < 0.0


def test_the_assist_is_drawn_and_always_points_toward_on_time():
    """The borrowed time is a first-class quantity now, so the panel shows it.

    `_draw_assist` marks where the engine put the swing against where the
    player put it. The slid marker must always sit between the player's marker
    and dead centre — the assist moves a swing toward on-time, never past it
    and never away — which is the same pair of bounds `bat_contact` pins on the
    slide itself, checked here in the units the player reads.

    Without this the panel would report a quality the player has no way to
    account for, which is exactly the fault the model change removed.
    """
    for ms in (-40.0, -20.0, 20.0, 40.0):
        rec, contact = struck_record(ms)
        assert rec.shift_s == contact.shift_s
        slid_ms = rec.signed_timing_ms + rec.shift_s * 1000.0
        assert abs(slid_ms) <= abs(rec.signed_timing_ms) + 1e-6, "toward on-time"
        assert slid_ms * rec.signed_timing_ms >= -1e-6, "never past it"

    squared, _ = struck_record(0.0)
    assert squared.shift_s == pytest.approx(0.0, abs=1e-6), "nothing to give"

    whiff = make_record(-90.0)
    assert whiff.shift_s == 0.0, "no contact, no slide"


def test_the_replay_draws_the_swing_that_was_swept_not_the_one_committed():
    """The engine slides the swing by up to `timing_assist_s` before sweeping
    it, so `swing_launch_s` has to carry that shift or the drawn bat is one
    nobody swung — the same failure as preferring the cursor at bat arrival
    over the cursor at commit.

    What the player *did* is reported separately and unmodified: the shift
    never touches `signed_timing_ms`.
    """
    rec, contact = struck_record(35.0)
    assert contact.shift_s < 0.0, "a late swing is slid earlier"
    committed = rec.bat_arrival_s - bat_path.SWING_DURATION_S
    assert rec.swing_launch_s == pytest.approx(committed + contact.shift_s)
    assert rec.signed_timing_ms == pytest.approx(35.0, abs=1.0)

    # And the phase the freeze samples puts the bat on the ball.
    state = rec.bat_swing().state_at(rec.contact_time_s - rec.swing_launch_s)
    assert _axis_gap_ft(state, contact.ball_ft) < 0.35


# ---- Labels and units -------------------------------------------------------

@pytest.mark.parametrize("ms,label", [
    # Outside the fair window a perfectly aimed swing gets at these defaults
    # (AMATEUR, -42.5..+45.0 ms). The late side is the forgiving one — see
    # `test_the_measured_windows_are_asymmetric_and_late_is_the_forgiving_side`
    # — so the two ends are not the same distance out, and +45 sits exactly on
    # the boundary rather than outside it.
    (-45.0, "EARLY"), (50.0, "LATE"),
    (-12.0, "ON TIME"), (12.0, "ON TIME"), (0.0, "ON TIME"),
])
def test_timing_label_respects_this_swings_own_window(ms, label):
    assert make_record(ms).timing_label == label


def test_the_window_is_this_difficulty_s_and_is_measured_not_assumed():
    """A 40 ms swing is on time at ROOKIE and late at HALL OF FAME — and the
    boundary comes from re-sweeping the swing, not from a constant."""
    easy = make_record(40.0, zone_size_mult=1.4, timing_window_mult=1.5)
    hard = make_record(40.0, zone_size_mult=0.7, timing_window_mult=0.4)
    assert easy.timing_label == "ON TIME"
    assert hard.timing_label == "LATE"
    assert easy.timing_windows_ms.fair[1] > hard.timing_windows_ms.fair[1]


@pytest.mark.parametrize("zone,window", [(1.4, 1.5), (1.0, 1.0), (0.7, 0.4)])
# Inside the contact window at every difficulty in the row above: the early
# side is the binding one, and it closes at about -25 ms at HALL OF FAME.
@pytest.mark.parametrize("ms", [-20.0, -10.0, 0.0, 10.0, 25.0, 45.0])
def test_on_time_means_exactly_that_the_swing_squared_it_up(zone, window, ms):
    """**The invariant the whole fix buys**, and it holds by construction now.

    The window is measured on *this* swing at *this* difficulty, so a swing the
    model scores fair must land inside it and one it scores foul must land
    outside. `ON TIME` therefore cannot appear over a foul, whatever the pitch,
    the aim or the difficulty. It used to be a constant that knew about none of
    those, which is how the screenshot read ON TIME at 40 ms late over a foul.
    """
    rec, contact = struck_record(ms, zone=zone, window=window)
    fair = not contact.is_foul(bat_contact.foul_threshold(window))
    assert (rec.timing_label == "ON TIME") == fair, (
        f"label {rec.timing_label} against a "
        f"{'fair' if fair else 'foul'} contact")


def test_the_screenshot_no_longer_reads_on_time_over_a_foul():
    """The reported case, reconstructed: ROOKIE, 40 ms late, aimed high.

    It read `ON TIME` because `perfect_ms` was 45 — 30 ms scaled by difficulty,
    inherited from the timing gate the geometry replaced. Over that same range
    quality ran from 1.00 down to 0.12, so the panel called a swing on time
    while the model was busy scoring it a foul.

    The aim error is part of the reconstruction, not decoration: at ROOKIE the
    assist covers 39 ms, so a *well-aimed* swing 40 ms late is slid to within a
    millisecond and really is fair. What made the real one a foul was missing
    by nearly three inches as well, and the measured window sees that — it
    narrows to about +/-27 ms for this swing where a well-aimed one gets
    -57/+65.

    The aim error needed to reproduce the foul is a moving target, and it moves
    every time the foul verdict is retuned — which is the point of keeping it a
    parameter rather than a constant of the fixture. It went 2.5 in -> 2.9 when
    `timing_charge_sigma_s` stopped charging a 39 ms ROOKIE slide against a
    20 ms Gaussian, and back to 2.6 when `FOUL_QUALITY_THRESHOLD` rose 0.52 ->
    0.59 to hold the total foul rate after `spray`'s location term was made to
    saturate. Both times that is the retune working rather than this case
    expiring. The property under test is unchanged — a foul must not read ON
    TIME — and `test_on_time_means_exactly_that_the_swing_squared_it_up` pins
    it across the whole ladder without depending on any particular aim error.
    """
    rec, contact = struck_record(40.0, aim_high_in=3.0)
    threshold = bat_contact.foul_threshold(rec.timing_window_mult)
    assert contact.is_foul(threshold), "the model scores this a foul"
    assert rec.timing_label == "LATE", "so the panel must not call it on time"
    # And for the right reason: there *is* a fair window here and +40 is
    # outside it, rather than the window being empty — a different finding
    # wearing the same label.
    fair = rec.timing_windows_ms.fair
    assert fair is not None and fair[1] < 40.0

    # A well-aimed swing at the same timing is a different story, and the
    # bands say so: this is why they are per-swing rather than per-difficulty.
    aimed, _ = struck_record(40.0)
    assert aimed.timing_windows_ms.fair[1] > fair[1]


def test_the_measured_windows_are_asymmetric_and_late_is_the_forgiving_side():
    """The thing a symmetric pair of constants could never show, and the most
    useful fact on the bar: a late bat still catches the ball on the handle
    while an early one runs out of barrel."""
    rec = make_record(0.0, zone_size_mult=1.0, timing_window_mult=1.0)
    lo, hi = rec.timing_windows_ms.contact
    assert lo < 0.0 < hi
    assert hi > 1.5 * abs(lo), f"late {hi:.0f} ms vs early {lo:.0f} ms"


def test_the_fair_window_sits_inside_the_contact_window():
    """Squaring the ball up is harder than touching it, at every difficulty."""
    for zone, window in ((1.4, 1.5), (1.0, 1.0), (0.7, 0.4)):
        rec = make_record(0.0, zone_size_mult=zone, timing_window_mult=window)
        contact, fair = rec.timing_windows_ms
        assert contact is not None and fair is not None
        assert contact[0] <= fair[0] and fair[1] <= contact[1]


@pytest.mark.parametrize("zone,window", [(1.4, 1.5), (1.0, 1.0), (0.7, 0.4)])
def test_the_verdict_is_contiguous_in_timing_which_is_what_lets_it_bisect(
        zone, window):
    """`timing_windows_ms` bisects rather than sweeps, which is only sound if
    "makes contact" and "is fair" are each a single interval in the offset. If
    that ever stops being true the bisection reports a boundary that is not
    one, so it is pinned rather than assumed."""
    rec = make_record(0.0, zone_size_mult=zone, timing_window_mult=window)
    seen = [rec._probe_contact(ms) for ms in range(-90, 121, 3)]
    for level in (1, 2):
        flags = [v >= level for v in seen]
        flips = sum(1 for a, b in zip(flags, flags[1:]) if a != b)
        assert flips <= 2, f"level {level} is not one interval"


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

@pytest.mark.parametrize("ms", [-60.0, -21.0, 0.0, 21.0, 60.0])
def test_the_bat_is_the_same_bat_however_the_swing_was_timed(ms):
    """The regression pin at the record level.

    `bat_swing()` used to pass the ball's depth at bat arrival into
    `bat_path.swing`, so a mistimed swing was drawn as a differently-shaped
    swing — hands feet from the body, the knob starting on the wrong side of
    the plate. The pitch reaches the bat through exactly one channel now, and
    it moves the drawn bat by inches of height, not by feet of everything.
    """
    ref = make_record(0.0).bat_swing().full_track(24)
    got = make_record(ms).bat_swing().full_track(24)
    for a, b in zip(ref, got):
        assert math.dist(a.knob_ft, b.knob_ft) < 0.25
        assert math.dist(a.barrel_ft, b.barrel_ft) < 0.25


@pytest.mark.parametrize("ms", [-45.0, -15.0, 0.0, 30.0])
def test_the_drawn_bat_and_the_reported_offset_agree(ms):
    """The replay samples the exact bat axis that produced the offset."""
    rec, contact = struck_record(ms)
    state = rec.bat_swing().state_at(contact.swing_t_s)
    axis_point, _ = bat_path.bat_solid_point(state, contact.along)
    assert axis_point == pytest.approx(contact.axis_point_ft, abs=1e-9)
    drawn_offset_in = (axis_point[2] - contact.ball_ft[2]) * 12.0
    # Reported offset is bat-below-ball positive; world z is up.
    assert drawn_offset_in == pytest.approx(-rec.vertical_offset_inches,
                                             abs=1e-6)


def test_the_replay_uses_the_engine_resolved_aim_without_rebuilding_it():
    rec, contact = struck_record(-40.0, aim_high_in=3.0)
    assert rec.bat_swing().aim_ft == pytest.approx(contact.resolved_aim_ft)
    assert rec.bat_swing().spatial_shift_ft == pytest.approx(
        contact.spatial_shift_ft)
    state = rec.bat_swing().state_at(contact.swing_t_s)
    assert state.knob_ft == pytest.approx(contact.knob_ft, abs=1e-9)
    assert state.barrel_ft == pytest.approx(contact.barrel_ft, abs=1e-9)


def test_a_swing_with_no_measured_offset_falls_back_to_the_aim_point():
    """A mistimed whiff never reaches the geometry test, so there is no
    relationship to preserve and the aim is all there is.

    The *resolved* aim, which is the one the engine swung — the raw cursor
    names a bat that was never built. It sits a couple of inches high of the
    cursor, because that is how much the ball has left to fall between the
    barrel and the plate."""
    rec = make_record(-70.0, vertical_offset_px=None)
    swing = rec.bat_swing()
    contact = swing.state_at(bat_path.SWING_DURATION_S).sweet_spot_ft
    named = bat_path.to_plate_frame((contact[0], contact[2]),
                                    swing.contact_depth_ft)
    assert named[1] == pytest.approx(rec.swing_aim_ft()[1])
    assert 0.0 < named[1] - rec.aim_ft[1] < 0.5


def test_the_ghost_is_the_same_swing_at_another_phase_not_a_second_swing():
    """The reference the player reads the error off costs nothing now.

    With the path independent of the pitch, "where the bat should have been"
    is this swing sampled where the ball crossed the barrel's plane. A late
    swing was still on its way there; an early one is already through it,
    which is one of the things the follow-through exists for.
    """
    swing = make_record(-30.0).bat_swing()
    early = make_record(-30.0).bat_state_at_ball_arrival()
    late = make_record(+30.0).bat_state_at_ball_arrival()
    contact = swing.state_at(bat_path.SWING_DURATION_S).sweet_spot_ft

    # Both ghosts are points on this same swing's path.
    track = [st.sweet_spot_ft for st in swing.full_track(400)]
    for ghost in (early.sweet_spot_ft, late.sweet_spot_ft):
        assert min(math.dist(ghost, p) for p in track) < 0.05
    # And they sit either side of contact: early is past it, late short of it.
    assert early.sweet_spot_ft[1] > contact[1]
    assert late.sweet_spot_ft[1] < contact[1]


def test_a_perfectly_timed_swing_has_no_daylight_from_its_ghost():
    rec = make_record(0.0)
    real = rec.bat_swing().state_at(bat_path.SWING_DURATION_S).sweet_spot_ft
    ghost = rec.bat_state_at_ball_arrival().sweet_spot_ft
    assert math.dist(real, ghost) == pytest.approx(0.0, abs=1e-3)


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


@pytest.mark.parametrize("ms", [-40.0, -20.0, 0.0, 20.0, 40.0])
def test_the_clip_runs_to_contact_and_holds_there(overlay, ms):
    """End to end through the overlay's own clock.

    `_now_s` at the freeze must be the instant the sweep found, and the bat
    sampled there must be the bat the sweep was holding — the picture and the
    crosshair are then the same event rather than two.
    """
    rec, contact = struck_record(ms)
    _run(overlay, rec)
    assert overlay._replay_progress() == pytest.approx(1.0)
    assert overlay._now_s() == pytest.approx(rec.replay_contact.pitch_t_s)
    assert overlay._swing_t(overlay._now_s()) == pytest.approx(rec.replay_contact.swing_t_s)


@pytest.mark.parametrize("ms", [-90.0, -60.0, -30.0])
def test_a_missed_swing_runs_the_whole_pitch_through_the_overlay(overlay, ms):
    """End to end: the clip that used to stop in mid-air now finishes at the
    plate, with the swing carried into its follow-through beside it."""
    rec = make_record(ms, made_contact="swung_and_miss", outcome="STRIKE",
                      contact=None)
    _run(overlay, rec, ms=6000)
    assert overlay._replay_progress() == pytest.approx(1.0)
    assert overlay._now_s() == pytest.approx(rec.travel_time_s)
    assert overlay._record.ball_at(overlay._now_s())[1] == pytest.approx(0.0,
                                                                        abs=1e-3)
    # The frame has to hold the ball it ends on, and the bat beside it.
    lo, hi = overlay._depth_range()
    state = overlay._swing.state_at(overlay._swing_t(overlay._now_s()))
    assert lo < 0.0 < hi
    assert lo < state.barrel_ft[1] < hi


def test_the_frozen_miss_still_shows_the_ball_the_panel_reports(overlay):
    """`BALL AT` names where the ball was when the barrel arrived, and the
    crosshair marks the bat at that same instant. The clip runs on past both
    now, so the ball at that moment is outlined — without it the panel reports
    a depth that is nowhere on screen."""
    import numpy as np
    from pygame import surfarray

    rec = make_record(-70.0, made_contact="swung_and_miss", outcome="STRIKE",
                      contact=None)
    surface = _run(overlay, rec, ms=6000)
    px, py = overlay._project(rec.ball_at(rec.bat_arrival_s))
    patch = surfarray.array3d(surface)[int(px) - 7:int(px) + 8,
                                       int(py) - 7:int(py) + 8]
    assert np.asarray(patch).max() > 0, "nothing drawn where BALL AT points"
    # And it is a different place from the ball the clip ends on.
    end = overlay._project(rec.ball_at(rec.clip_end_s))
    assert math.dist((px, py), end) > 10


def test_the_slow_motion_rate_is_the_same_for_every_swing(overlay):
    """One rate, not one duration.

    Divided out of a fixed 2180 ms the rate was a function of the swing — the
    clips with the most pitch to show played fastest, which is backwards. A
    longer window now buys a longer clip and the bat sweeps at one speed.
    """
    records = [make_record(ms, made_contact="swung_and_miss", contact=None)
               for ms in (-90.0, -40.0, 0.0, 40.0)]
    records += [struck_record(ms)[0] for ms in (-40.0, 0.0, 40.0)]
    rates = []
    for rec in records:
        overlay.trigger(record=rec)
        start, end = overlay._window_s()
        rates.append((overlay._replay_end_ms - 420) / (end - start))
    # Within a millisecond of rounding on the clip length, which is the only
    # thing between the rate and an exact constant.
    assert max(rates) - min(rates) < 0.001 * min(rates), rates
    # And a clip with more pitch in it takes longer, rather than speeding up.
    overlay.trigger(record=records[0])
    long_ms = overlay._replay_end_ms
    overlay.trigger(record=records[2])
    assert long_ms > overlay._replay_end_ms


@pytest.mark.parametrize("ms", [-40.0, 0.0, 40.0])
def test_the_bat_enters_the_frame_before_it_starts_moving(overlay, ms):
    """The window is anchored to the swing's launch, not measured back from
    the end, so moving the end onto contact cannot pull the bat into the first
    frame already mid-arc."""
    rec, _ = struck_record(ms)
    overlay.trigger(record=rec)
    start, _ = overlay._window_s()
    assert overlay._swing_t(start) == 0.0
    assert start < rec.swing_launch_s


@pytest.mark.parametrize("ms", [-40.0, 0.0, 40.0])
def test_the_frame_holds_everything_it_draws(overlay, ms):
    """The depth window used to be framed on the ball at bat arrival, which on
    a late swing is several feet past anything the clip now reaches — half the
    view was empty air behind the catcher."""
    rec, contact = struck_record(ms)
    overlay.trigger(record=rec)
    lo, hi = overlay._depth_range()
    state = overlay._swing.state_at(contact.swing_t_s)
    for depth in (contact.depth_ft, rec.barrel_depth_ft,
                  state.knob_ft[1], state.barrel_ft[1]):
        assert lo < depth < hi


def test_a_struck_swing_renders_in_both_views(overlay):
    """Including the reach annotation, which only exists on a real contact —
    every other overlay test runs the whiff path, where `contact` is None."""
    for ms in (-40.0, 0.0, 40.0):
        rec, _ = struck_record(ms)
        for view in (0, 1):
            overlay.trigger(record=rec)
            overlay._view = view
            _run(overlay, rec)


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
    """A scrub step is a fortieth of the replay, whatever length that is —
    read off the overlay rather than off a literal, since the clip is as long
    as the slice of pitch it has to show."""
    overlay.trigger(record=make_record())
    step = (overlay._replay_end_ms - 420) // 40
    for _ in range(80):
        overlay.update(16)
    before = overlay._elapsed_ms
    overlay.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT))
    assert overlay._paused
    assert overlay._elapsed_ms < before
    overlay.update(16)
    assert overlay._elapsed_ms == pytest.approx(before - step, abs=1)


def test_space_restarts_a_finished_replay(overlay):
    overlay.trigger(record=make_record())
    end = overlay._freeze_end_ms
    for _ in range(300):
        overlay.update(16)
    assert overlay._elapsed_ms == end
    overlay.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    assert overlay._elapsed_ms < end
    assert not overlay._paused


# ---- The camera stands where the label says --------------------------------

@pytest.mark.parametrize("hand,pitcher_left", [("R", False), ("L", True)])
def test_the_side_camera_stands_on_the_batters_open_side(overlay, hand, pitcher_left):
    """First-base line for a right-hander, third-base line for a left-hander.

    A camera down the third-base line sees the pitcher on its left and the
    catcher on its right; one down the first-base line sees the reverse. So
    which way `+y` runs across the screen *is* which foul line the camera is
    standing on, and it has to follow the batter: fixed on one line it films
    one hand from the front and the other from behind, where the hands travel
    away from the camera and the barrel is hidden by the body for most of the
    swing.

    It was fixed on the third-base line, and before that it was mirrored — a
    first-base camera under a caption reading `PITCHER ->`. Both are cheap to
    get wrong and impossible to notice from inside the view, since a mirrored
    swing is still a swing; it is only wrong against the ball, the batter and
    every other side-on picture of a swing ever drawn.
    """
    overlay.trigger(record=make_record(hand=hand))
    overlay._view = 0
    mound = overlay._project((0.0, 6.0, 3.0))
    plate = overlay._project((0.0, 0.0, 3.0))
    backstop = overlay._project((0.0, -6.0, 3.0))
    assert (mound[0] < plate[0] < backstop[0]) is pitcher_left
    assert (backstop[0] < plate[0] < mound[0]) is not pitcher_left
    # And up is up in either case: the vertical axis is height, flipped for
    # screen y. Only the horizontal one belongs to the camera.
    assert overlay._project((0.0, 0.0, 4.0))[1] < overlay._project((0.0, 0.0, 1.0))[1]


@pytest.mark.parametrize("hand", ["R", "L"])
def test_the_side_caption_names_the_line_the_camera_is_on(overlay, hand):
    """The caption is the only thing that says where the viewer is standing,
    so it is the thing that can quietly outlive the geometry — which is how
    this view came to be captioned `PITCHER ->` while drawing the opposite.
    Read the arrows back out of the picture instead of trusting them."""
    overlay.trigger(record=make_record(hand=hand))
    overlay._view = 0
    label = overlay._axis_label()
    mound_left = overlay._project((0.0, 6.0, 0.0))[0] < overlay._project((0.0, -6.0, 0.0))[0]
    assert label.startswith("FROM 3B SIDE" if mound_left else "FROM 1B SIDE")
    assert ("<- PITCHER" in label) is mound_left
    assert ("PITCHER ->" in label) is not mound_left
    # And the batter is filmed from their open side, never their back.
    assert (overlay._side_camera_x() > 0) is (hand == "L")


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

@pytest.mark.parametrize("view", [0, 1])
def test_collision_and_rendering_share_the_same_bat_stations(overlay, view):
    rec = make_record(-21.0)
    overlay.trigger(record=rec)
    overlay._view = view
    state = rec.bat_swing().state_at(bat_path.SWING_DURATION_S * 0.6)
    ellipses = overlay._bat_ellipses(state, (0.0, 1.0))
    centres = [centre for centre, _ in ellipses]
    lo, hi = bat_path.bat_solid_axis(state)
    assert overlay._project(lo) in centres
    assert overlay._project(hi) in centres


@pytest.mark.parametrize("view", [0, 1])
def test_projected_bat_radii_follow_each_view_axis(overlay, view):
    rec = make_record(-21.0)
    overlay.trigger(record=rec)
    overlay._view = view
    sx, sy = overlay._px_per_ft()
    radius = bat_path.BAT_TIP_RADIUS_FT
    rx, ry = overlay._projected_radius(radius)
    assert rx == pytest.approx(radius * sx)
    assert ry == pytest.approx(radius * sy)
    assert rx / ry == pytest.approx(sx / sy)


def test_a_bat_pointed_at_the_camera_still_draws(overlay):
    """Dense projected spheres need no end-on special case."""
    rec = make_record()
    overlay.trigger(record=rec)
    overlay._view = 0
    surface = pygame.Surface(SCREEN)
    overlay._draw_bat(surface, rec.contact_time_s)
    assert surface.get_bounding_rect().width > 0


@pytest.mark.parametrize("view", [0, 1])
@pytest.mark.parametrize("ms", [-40.0, -20.0, 0.0, 20.0, 40.0])
def test_first_touch_has_adjacent_bat_and_ball_pixels(overlay, view, ms):
    """The screenshot-level invariant: a hit cannot render as a whiff."""
    rec, contact = struck_record(ms)
    overlay.trigger(record=rec)
    overlay._view = view
    overlay._elapsed_ms = overlay._replay_end_ms

    bat = pygame.Surface(SCREEN, pygame.SRCALPHA)
    ball = pygame.Surface(SCREEN, pygame.SRCALPHA)
    overlay._draw_bat(bat, rec.clip_end_s)
    overlay._draw_ball(ball, rec.clip_end_s)
    overlap = pygame.mask.from_surface(bat).overlap(
        pygame.mask.from_surface(ball), (0, 0))
    # Raster rounding can leave one pixel between tangent silhouettes.
    if overlap is None:
        bat_mask = pygame.mask.from_surface(bat)
        ball_mask = pygame.mask.from_surface(ball)
        assert any(bat_mask.overlap(ball_mask, (dx, dy)) is not None
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1))


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


# ---- One scale per view -----------------------------------------------------

@pytest.mark.parametrize("view", [0, 1])
@pytest.mark.parametrize("ms", [-40.0, 0.0, 40.0])
def test_a_foot_is_a_foot_along_both_axes(overlay, view, ms):
    """OVERHEAD used to fit 11 ft of width into 1072 px and 14 ft of depth
    into 340 — a 4:1 squash that drew the swing's round arc as a flattened
    ellipse and looked, in the words of the report, "very weird". One scale
    per view now: the axis with less room per foot sets it and the other is
    widened to match. Checked off the projection itself, not only the number
    it reports."""
    rec, _ = struck_record(ms)
    overlay.trigger(record=rec)
    overlay._view = view
    sx, sy = overlay._px_per_ft()
    assert sx == pytest.approx(sy)
    origin = overlay._project((0.0, 0.0, 1.0))
    if view == 0:
        across = overlay._project((0.0, 1.0, 1.0))
        up = overlay._project((0.0, 0.0, 2.0))
    else:
        across = overlay._project((1.0, 0.0, 1.0))
        up = overlay._project((0.0, 1.0, 1.0))
    assert math.dist(origin, across) == pytest.approx(sx)
    assert math.dist(origin, up) == pytest.approx(sx)


def test_a_bat_across_the_plate_is_as_long_as_one_pointing_at_the_mound(overlay):
    """The defect stated directly: the same bat laid along x and then along y
    has to come out the same length on screen. It came out four times longer
    one way than the other, which is why the frozen frame's bat read as a
    needle lying across the view."""
    overlay.trigger(record=make_record())
    overlay._view = 1
    length = bat_path.BAT_LENGTH_FT
    across = bat_path.BatState((0.0, 1.0, 3.0), (length, 1.0, 3.0),
                               (0.8 * length, 1.0, 3.0))
    along = bat_path.BatState((0.0, 1.0, 3.0), (0.0, 1.0 + length, 3.0),
                              (0.0, 1.0 + 0.8 * length, 3.0))

    def drawn(state):
        return math.dist(overlay._project(state.knob_ft),
                         overlay._project(state.barrel_ft))

    assert drawn(across) == pytest.approx(drawn(along))
    assert drawn(across) == pytest.approx(length * overlay._px_per_ft()[0])


@pytest.mark.parametrize("view", [0, 1])
def test_isotropy_is_bought_with_field_of_view_not_by_shrinking(overlay, view):
    """Along the binding axis the window is exactly the range the view has to
    hold, and the other axis only ever comes back wider. A fit that shrank
    the required range to make the scales agree would clip the swing."""
    rec, _ = struck_record(0.0)
    overlay.trigger(record=rec)
    overlay._view = view
    (h_lo, h_hi), (v_lo, v_hi) = overlay._frame_ft()
    lo, hi = overlay._depth_range()
    if view == 1:
        assert (v_lo, v_hi) == pytest.approx((lo, hi))
        assert h_hi - h_lo >= sro._OVER_X_RANGE[1] - sro._OVER_X_RANGE[0]
    else:
        assert (v_lo, v_hi) == pytest.approx(sro._SIDE_Z_RANGE)
        assert h_hi - h_lo >= hi - lo


@pytest.mark.parametrize("ms", [-63.0, -21.0, 0.0, 40.0])
def test_the_overhead_frame_holds_the_whole_swing(overlay, ms):
    """Depth stands on OVERHEAD's short axis and sets its scale, so the
    window is framed on the swing's own path — the load pose puts the barrel
    nearly 4 ft behind the plate — rather than on its end points plus a
    margin wide enough to catch the arc by accident. Every sample of the bat
    the clip draws, and the plate, land inside the rect."""
    rec = make_record(ms)
    overlay.trigger(record=rec)
    overlay._view = 1
    rect = overlay._view_rect()
    t_end = overlay._swing_t(rec.clip_end_s)
    for i in range(41):
        state = overlay._swing.state_at(t_end * i / 40)
        for point in (state.knob_ft, state.barrel_ft):
            assert rect.collidepoint(overlay._project(point))
    for point in ((0.0, 0.0, 0.0), (0.0, -sro._PLATE_DEPTH_FT, 0.0)):
        assert rect.collidepoint(overlay._project(point))


def test_the_spray_label_lands_inside_the_view(overlay, monkeypatch):
    """The ray is drawn long enough to leave the frame from anywhere inside
    it, and its label was anchored at the far end — outside the clip, so in
    the whole life of the feature it had never once appeared on screen. It
    sits where the ray leaves the view now."""
    rec, contact = struck_record(0.0)
    assert contact is not None
    placed = []
    real = sro.gdt.blit_text

    def spy(screen, text, font, pos, color, align='left'):
        rect = real(screen, text, font, pos, color, align)
        placed.append((text, rect))
        return rect

    monkeypatch.setattr(sro.gdt, "blit_text", spy)
    overlay.trigger(record=rec)
    overlay._view = 1
    _run(overlay, rec)
    labels = [r for text, r in placed
              if text.startswith(("PULL", "OPPO", "FOUL"))]
    assert labels, "no spray label was drawn"
    view = overlay._view_rect()
    assert all(view.contains(r) for r in labels), labels[-1]


# ---- The nested loop that runs the overlay ---------------------------------
# `Game` can't be constructed headlessly, so the loop is bound to a stub that
# carries only what it touches — the same shape as
# tests/test_exit_to_menu_routing.py.


class _StubOverlay:
    """Active for a fixed number of frames, then done."""

    def __init__(self, frames=3):
        self._left = frames
        self.rendered = 0

    def is_active(self):
        return self._left > 0

    def update(self, dt_ms):
        self._left -= 1

    def render(self, surface):
        self.rendered += 1

    def handle_event(self, event):
        return True

    def dismiss(self):
        self._left = 0


class _StubUIManager:
    def __init__(self):
        self.draws = 0

    def draw(self):
        self.draws += 1


class _StubReplayGame:
    from strikefactor.main import Game as _G
    _run_swing_replay_loop = _G._run_swing_replay_loop
    del _G

    def __init__(self):
        self.clock = pygame.time.Clock()
        self.screen = pygame.Surface(SCREEN)
        self.state_manager = type("_SM", (), {"current_state": None})()
        self.swing_replay_overlay = _StubOverlay()
        self.ui_manager = _StubUIManager()
        self.huds = 0
        self.flips = 0

    def _draw_active_hud(self, screen):
        self.huds += 1

    def flip_display(self):
        self.flips += 1


def test_the_replay_loop_draws_no_gui_over_the_panel():
    """pygame_gui draws over everything, so the sidebar buttons used to sit on
    top of the replay panel at full brightness — the field and the HUD are
    dimmed by the overlay's scrim, but anything drawn after it is not. The
    loop simply does not draw the gui while the overlay is up; the buttons'
    own shown/hidden state is untouched, so the main loop restores them."""
    g = _StubReplayGame()
    g._run_swing_replay_loop()
    assert g.swing_replay_overlay.rendered == 3
    assert g.huds == 3, "the HUD is still drawn — it is behind the scrim"
    assert g.ui_manager.draws == 0


class _AnimStubGame:
    """The whole of the game a `HitAnimation` reads. Same shape as
    `tools.sim.StubGame`, restated here rather than imported so this file
    keeps working without the harness on the path."""

    def __init__(self, hand="R"):
        self.batter = type("B", (), {"get_handedness": lambda self: hand})()


# ---- The picture and the flight are one ball --------------------------------
#
# `_draw_spray`'s docstring has always claimed the ray is "the same number the
# animation flies it along, so the picture and the outcome cannot disagree".
# Nothing tested it, and for fouls it was false: the replay drew the *bat's*
# bearing while `_setup_foul` invented its own out of `random`. Measured over
# 600 recorded fouls the two were a median of 40.7 degrees apart, 271 of them
# drawn as a fair ray under a FOUL banner. These are the pins that claim now
# has.

def _foul_contact(hand="R", timing_ms=30.0, aim=(0.0, 2.5)):
    """A real mistimed swing, swept by the real engine, that came out foul."""
    traj = make_trajectory()
    swing = bat_path.swing(bat_contact.aim_at_pitch(aim, traj, hand), hand)
    due = traj.time_at_depth(swing.contact_depth_ft)
    return bat_contact.resolve_contact(
        swing, traj, due - bat_path.SWING_DURATION_S + timing_ms / 1000.0,
        timing_window_mult=0.2)


def _animated_bearing_deg(anim, hand):
    """The bearing the animation actually put the ball on, pull-positive."""
    from strikefactor.gameplay import hit_animation as ha
    fx, fy = ha._to_field_ft(anim._hit_end)
    field = math.degrees(math.atan2(fy, fx))
    return (field - 90.0) / spray.spin_for(hand)


@pytest.mark.parametrize("hand", ["R", "L"])
@pytest.mark.parametrize("timing_ms", [-40.0, -15.0, 15.0, 40.0])
def test_the_replay_ray_is_the_bearing_the_animation_flew(hand, timing_ms):
    """The seam. One contact, resolved once the way `PitchSimulation` resolves
    it, then handed to both consumers — and they have to agree.

    Both hands, because a sign error here mirrors the batter in the one view
    whose whole job is showing which way the ball went.
    """
    from strikefactor.gameplay import hit_animation as ha
    from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager

    contact = _foul_contact(hand, timing_ms)
    if contact is None:
        pytest.skip("no contact at this timing")
    quality, offset_px = HitOutcomeManager.contact_metrics(contact)
    foul = contact.is_foul(bat_contact.foul_threshold(0.2))

    mgr = HitOutcomeManager.__new__(HitOutcomeManager)
    shape = mgr._classify_batted_ball_type(mgr.launch_angle_deg(contact))
    departure = (spray.foul_departure_deg(contact.spray_deg, quality, shape)
                 if foul else contact.spray_deg)

    anim = ha.HitAnimation(
        _AnimStubGame(hand), outcome="FOUL" if foul else "IN_PLAY",
        on_complete=lambda: None, vertical_offset=offset_px, quality=quality,
        batted_ball_type=shape, spray_deg=departure)

    rec = make_record(hand=hand, contact=contact, departure_deg=departure,
                      made_contact="fouled" if foul else "hit",
                      outcome="foul" if foul else "SINGLE")
    # What the replay draws is what the record hands it.
    assert rec.departure_or_spray_deg == pytest.approx(departure)

    got = _animated_bearing_deg(anim, hand)
    # The residual is `batted_ball_path`'s bend between departure and landing,
    # which the replay draws too (`_spray_track_ft` samples the same path).
    assert abs(((got - departure) + 180.0) % 360.0 - 180.0) < 15.0, (
        f"replay draws {departure:+.1f} deg, animation flew {got:+.1f}")


@pytest.mark.parametrize("hand", ["R", "L"])
def test_a_ball_the_banner_calls_foul_is_never_drawn_fair(hand):
    """The reported bug, stated as a property. A ball fouled straight back was
    drawn as a forward ray in the *fair* colour with no FOUL label, because
    the ray asked `spray.is_foul(bat bearing)` while the panel asked
    `Contact.is_foul(quality)` — two predicates for one verdict, eight inches
    apart on the same panel."""
    from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager
    for timing_ms in (-45.0, -30.0, -10.0, 10.0, 30.0, 45.0):
        contact = _foul_contact(hand, timing_ms)
        if contact is None or not contact.is_foul(bat_contact.foul_threshold(0.2)):
            continue
        quality, offset_px = HitOutcomeManager.contact_metrics(contact)
        mgr = HitOutcomeManager.__new__(HitOutcomeManager)
        shape = mgr._classify_batted_ball_type(mgr.launch_angle_deg(contact))
        departure = spray.foul_departure_deg(contact.spray_deg, quality, shape)
        assert spray.is_foul(departure), (
            f"{hand}HB at {timing_ms:+.0f} ms fouled, but the ray would draw "
            f"{departure:+.1f} deg — inside the lines")


def test_the_replay_draws_the_track_the_ball_actually_flew():
    """Not a ray reconstructed from a bearing: `SwingRecord.flight_path` is the
    animation's own `BattedBallPath`, so the two are the same object and a
    second flight model cannot grow here."""
    from strikefactor.gameplay import hit_animation as ha
    anim = ha.HitAnimation(_AnimStubGame("R"), outcome="IN_PLAY",
                           on_complete=lambda: None, quality=0.8,
                           batted_ball_type="LINER", spray_deg=12.0,
                           timing_turn_deg=9.0)
    assert anim.flight_path is not None
    rec = make_record(flight_path=anim.flight_path, departure_deg=12.0,
                      contact=_foul_contact("R", 0.0))
    pygame.display.init()
    pygame.font.init()
    view = SwingReplayOverlay(FakeGame())
    view.trigger(record=rec)
    view._view = sro._VIEW_OVERHEAD
    track = view._spray_track_ft(12.0)
    assert len(track) > 2, "a curved track needs more than a start and an end"
    # Every drawn point is on the animation's own path, converted once
    # (field_x = -world_x) and translated onto the contact point.
    start = rec.replay_contact.ball_ft
    for i, point in enumerate(track):
        fx, fy = anim.flight_path.point_ft(
            min(1.0, sro._SPRAY_RAY_FT / anim.flight_path.carry_ft)
            * i / sro._SPRAY_TRACK_SAMPLES)
        assert point[0] == pytest.approx(start[0] - fx)
        assert point[1] == pytest.approx(start[1] + fy)


def test_a_batted_ball_has_exactly_one_exit_velocity():
    """`contact_audio.exit_velocity_mph` jitters, so it has to be drawn once
    per ball — and "once" means once across the whole pitch, not once inside
    the animation. The sound drew its own, and *that* draw is what reached the
    DB and this panel's EXIT VELO, so the number the player was shown was not
    the number the ball was flown at."""
    from strikefactor.engine import contact_audio
    from strikefactor.gameplay import hit_animation as ha

    ev = 97.5
    anim = ha.HitAnimation(_AnimStubGame("R"), outcome="IN_PLAY",
                           on_complete=lambda: None, quality=0.8,
                           batted_ball_type="LINER", spray_deg=5.0, ev_mph=ev)
    assert anim.exit_velocity_mph == ev
    # And the sound takes the same number rather than drawing a second one.
    _, _, sound_ev = contact_audio.contact_sound_for(0.8, "power", ev_mph=ev)
    assert sound_ev == ev


@pytest.mark.parametrize("ms", [-40.0, 0.0, 40.0])
@pytest.mark.parametrize("aim_high_in", [-2.0, 0.0, 2.0])
def test_replay_stops_at_surface_entry_without_changing_scored_contact(ms, aim_high_in):
    rec, scored = struck_record(ms, aim_high_in=aim_high_in)
    touch = rec.replay_contact
    assert rec.contact is scored
    assert touch.pitch_t_s < scored.pitch_t_s
    assert touch.surface_gap_ft == pytest.approx(0.0, abs=1e-7)
    swing = rec.bat_swing()
    before = bat_contact._gap_at(swing, rec.trajectory, rec.swing_launch_s,
                                 touch.swing_t_s - 1e-5)[0]
    after = bat_contact._gap_at(swing, rec.trajectory, rec.swing_launch_s,
                                touch.swing_t_s + 1e-5)[0]
    assert before > 0.0
    assert after < 0.0
