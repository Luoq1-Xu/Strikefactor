"""Everything needed to replay one swing, captured at the end of the pitch.

Built once per swing in `PitchSimulation.cleanup()` and parked on
`Game.last_swing`, where the replay overlay picks it up. Pure data plus the
derivations that follow from it — no pygame, no rendering, no game state.

Two decisions in here are worth keeping.

**It holds the `PitchTrajectory` object, not samples.** The trajectory is nine
floats and a solver; re-evaluating it at any instant is exact and free. The
alternatives were the DB's 20-sample table (too coarse to slow down) and the
live screen trail, which carries no timestamps at all — it is appended roughly
once per engine frame with no record of when, so it cannot be aligned to a
swing clock. Slow motion needs a *function of time*, and this is the only one
the game has.

**Contact depth is measured, not modelled.** `contact_depth_ft` is the ball's
own `y` at the instant the bat arrived, straight off that trajectory. Early
swings meet the ball out in front (positive), late swings let it get deep
(negative). Because it comes from the same trajectory the pitch was flown
with, there is no second model of "how early was it" that can disagree with
the first — the fault CLAUDE.md tracks throughout the batted-ball code.

One consequence to be aware of when reading the replay: the engine evaluates
contact against a ball *clamped* at the plate (`_update_ball_position` does
`t = min(t, travel_time)`, and `_handle_contact_phase` never re-runs it). So
on a late swing the rectangle test used a ball frozen at `y = 0` while the
real ball was already past. The replay draws the unclamped trajectory, since
that is the physically real ball and the whole basis of the depth readout, and
keeps the engine's evaluated screen position separately in
`ball_screen_at_contact` so the two can be told apart.
"""

from dataclasses import dataclass

from strikefactor.gameplay import bat_path
from strikefactor.utils.pitch_physics import DEFAULT_CAMERA

# Vertical offset is stored in screen pixels throughout the codebase — the DB
# column is named `vertical_offset_in` but a comment in `pitch_simulation`
# admits the name is aspirational. Converting here rather than renaming the
# column keeps every existing aggregate meaning what it meant.
FT_PER_PX_Z = DEFAULT_CAMERA.cam_dist / DEFAULT_CAMERA.scale_y
INCHES_PER_FT = 12.0


@dataclass(frozen=True)
class SwingRecord:
    """One swing, reconstructable."""

    trajectory: object          # PitchTrajectory
    travel_time_s: float
    bat_arrival_s: float        # seconds after release that the barrel got there
    signed_timing_ms: float     # negative early, positive late
    perfect_ms: float           # this swing's difficulty-scaled windows
    foul_ms: float

    aim_ft: tuple               # (x, z) in world feet at the plate
    handedness: str
    swing_type: int             # 1 contact (W), 2 power (E)
    zone_size_mult: float

    on_time: int                # 0 mistimed, 1 foul window, 2 perfect
    made_contact: str           # no_swing / swung_and_miss / fouled / hit
    outcome: str

    pitch_type: str = ""
    speed_mph: float = 0.0
    contact_quality: float = None
    vertical_offset_px: float = None
    exit_velocity_mph: float = None
    batted_ball_type: str = None
    ball_screen_at_contact: tuple = None

    # -- derived ----------------------------------------------------------

    @property
    def contact_depth_ft(self):
        """Feet in front of the plate where the barrel met the ball.

        Positive is out front (early), negative is deep (late). Deliberately
        unclamped: past the plate the pitch model still describes a real ball
        heading into the catcher's mitt, and clamping it at zero would erase
        exactly the signal the replay exists to show.
        """
        return self.trajectory.position_at(self.bat_arrival_s)[1]

    @property
    def is_early(self):
        return self.signed_timing_ms < 0

    @property
    def timing_label(self):
        if abs(self.signed_timing_ms) <= self.perfect_ms:
            return "ON TIME"
        return "EARLY" if self.is_early else "LATE"

    @property
    def vertical_offset_ft(self):
        """Bat minus ball at contact, in world feet, positive *up*.

        The stored value is screen pixels in pygame's y-down convention, so a
        positive offset means the bat sat below the ball; this flips it into
        the world's z-up sense so it can be added to a height.
        """
        if self.vertical_offset_px is None:
            return None
        return -self.vertical_offset_px * FT_PER_PX_Z

    @property
    def vertical_offset_inches(self):
        """Bat over/under the ball at contact, in real inches.

        Positive means the bat was *below* the ball — the pygame y-down
        convention `hit_outcome_manager` uses, kept rather than flipped so
        this reads the same way as `_compute_contact_quality`.
        """
        if self.vertical_offset_px is None:
            return None
        return self.vertical_offset_px * FT_PER_PX_Z * INCHES_PER_FT

    def _drawn_aim_ft(self, depth_ft):
        """The aim point to draw the bat at, for a bat meeting the ball at
        `depth_ft`.

        Not simply `aim_ft`, and the reason is worth stating. `aim_ft` is the
        cursor resolved to world feet *at the plate*, because that is the only
        depth `screen_to_world_at_plate` knows about. But the barrel meets the
        ball out in front of the plate, and the ball is meaningfully higher
        there — 6.4 inches higher on an ordinary 45 ms early swing, since it
        has that much less time to drop. Drawing the bat at its plate height
        against a ball at its true contact height therefore showed the bat
        half a foot *under* a ball the stats panel simultaneously reported it
        was 1.4 inches *over*. A replay whose picture contradicts its own
        numbers is worse than useless.

        So the bat is placed by the relationship the engine actually measured
        — `vertical_offset` is bat minus ball, in pygame's y-down screen
        convention, hence the sign flip into world feet — carried out to the
        depth where contact happened. Timing (depth) and alignment (offset)
        are both then exactly what the engine judged, and the only thing given
        up is the bat's absolute height above the ground, which no player can
        perceive and nothing in the game reports.

        When no offset was measured at all — a mistimed whiff never reaches
        the geometry test — there is nothing to align to and the plate-height
        aim is used unchanged.
        """
        offset_ft = self.vertical_offset_ft
        if offset_ft is None:
            return self.aim_ft
        ball_z = self.trajectory.position_at(self._time_at_depth(depth_ft))[2]
        return (self.aim_ft[0], ball_z + offset_ft)

    def _time_at_depth(self, depth_ft):
        """When the ball was `depth_ft` in front of the plate."""
        if depth_ft == self.contact_depth_ft:
            return self.bat_arrival_s
        return self.travel_time_s

    def bat_swing(self):
        """The bat that made this swing."""
        depth = self.contact_depth_ft
        return bat_path.swing(
            aim_ft=self._drawn_aim_ft(depth),
            contact_depth_ft=depth,
            handedness=self.handedness,
            swing_type=self.swing_type,
            zone_size_mult=self.zone_size_mult,
        )

    def perfect_swing(self):
        """The same swing timed perfectly — the ghost drawn beside the real one.

        Same aim, same alignment, contact depth zero. What separates it from
        `bat_swing()` is precisely the timing error, which is what makes the
        pair legible where a number alone is not.
        """
        return bat_path.swing(
            aim_ft=self._drawn_aim_ft(0.0),
            contact_depth_ft=0.0,
            handedness=self.handedness,
            swing_type=self.swing_type,
            zone_size_mult=self.zone_size_mult,
        )

    def ball_at(self, t_s):
        """The ball's world position `t_s` seconds after release."""
        return self.trajectory.position_at(t_s)


def from_simulation(sim):
    """Build a `SwingRecord` off a finished `PitchSimulation`, or None.

    Returns None when the pitch was taken — there is no swing to replay, and
    a take must not clear the previous swing off `Game.last_swing`.
    """
    if sim.swing_type == 0 or sim.swing_starttime is None:
        return None

    aim_screen = sim.aim_screen_at_contact or sim.aim_screen_at_swing
    if aim_screen is None:
        return None

    perfect_ms, foul_ms = sim._timing_windows()
    bat_arrival_ms = (sim.swing_starttime + bat_path.SWING_DURATION_MS
                      - sim.starttime - sim.windup)

    # Fouls never run the hit pipeline, so `contact_quality` stays null on
    # them by design and their real numbers live in the foul-specific fields.
    quality = sim.contact_quality
    offset = sim.vertical_offset_in
    if sim.made_contact == "fouled":
        quality = sim._foul_quality
        offset = sim._foul_vertical_offset

    return SwingRecord(
        trajectory=sim.trajectory,
        travel_time_s=sim.trajectory.travel_time,
        bat_arrival_s=bat_arrival_ms / 1000.0,
        signed_timing_ms=sim._signed_timing_ms(),
        perfect_ms=perfect_ms,
        foul_ms=foul_ms,
        aim_ft=DEFAULT_CAMERA.screen_to_world_at_plate(*aim_screen),
        handedness=sim.game.batter.get_handedness(),
        swing_type=sim.swing_type,
        zone_size_mult=sim.game.settings_manager.get_difficulty_multipliers()["contact_zone_size"],
        on_time=sim.on_time,
        made_contact=sim.made_contact,
        outcome=getattr(sim, "outcome", "") or "",
        pitch_type=sim.pitchtype,
        speed_mph=sim.speed_mph,
        contact_quality=quality,
        vertical_offset_px=offset,
        exit_velocity_mph=sim.exit_velocity_mph,
        batted_ball_type=sim.batted_ball_type,
        ball_screen_at_contact=sim.ball_screen_at_contact,
    )
