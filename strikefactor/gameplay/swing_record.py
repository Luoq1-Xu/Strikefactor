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

**It is the ball's depth, and `barrel_depth_ft` is the bat's.** They are two
different objects and the whole point of the replay is that they are allowed
to be in different places. `bat_path` no longer takes a contact depth at all:
the swing is built from the aim, arrives where the aim puts it, and the ball
is wherever the pitch put it at that instant. The separation between the two
*is* the timing error, in feet.

**A swing names two instants, and they are not the same one.**
`bat_arrival_s` is when the barrel reached its contact pose — a fact about the
swing alone, and the datum `signed_timing_ms` is measured against.
`contact_time_s` is when `bat_contact`'s sweep found the bat and the ball at
their closest, which is where they actually met. On a mistimed swing the sweep
catches the ball earlier or later in the arc, up to ~25 ms away; at 101 mph
that is six feet of ball. The replay froze on the first and drew a crosshair at
the second, which is why a HOME RUN could be shown with the bat eight feet from
the ball. Anything meant to be *looked at* runs on `contact_time_s`; the timing
readouts stay on `bat_arrival_s`, which is what they have always measured.

One consequence to be aware of when reading the replay: the engine evaluates
contact against a ball *clamped* at the plate (`_update_ball_position` does
`t = min(t, travel_time)`, and `_handle_contact_phase` never re-runs it). So
on a late swing the rectangle test used a ball frozen at `y = 0` while the
real ball was already past. The replay draws the unclamped trajectory, since
that is the physically real ball and the whole basis of the depth readout, and
keeps the engine's evaluated screen position separately in
`ball_screen_at_contact` so the two can be told apart.
"""

from collections import namedtuple
from dataclasses import dataclass
from functools import cached_property

from strikefactor.gameplay import bat_contact, bat_path
from strikefactor.utils.pitch_physics import DEFAULT_CAMERA

# Vertical offset is stored in screen pixels throughout the codebase — the DB
# column is named `vertical_offset_in` but a comment in `pitch_simulation`
# admits the name is aspirational. Converting here rather than renaming the
# column keeps every existing aggregate meaning what it meant.
FT_PER_PX_Z = DEFAULT_CAMERA.cam_dist / DEFAULT_CAMERA.scale_y
INCHES_PER_FT = 12.0

# How far either side of the datum `timing_windows_ms` looks, and how hard it
# then bisects. The widest window measured is about +99 ms (ROOKIE, late), so
# 160 clears it with room; eight steps put each boundary inside 1.3 ms, which
# is finer than the bar can draw.
_WINDOW_SEARCH_MS = 160.0
_WINDOW_BISECT_STEPS = 8

TimingWindows = namedtuple("TimingWindows", "contact fair")


@dataclass(frozen=True)
class SwingRecord:
    """One swing, reconstructable."""

    trajectory: object          # PitchTrajectory
    travel_time_s: float
    bat_arrival_s: float        # seconds after release that the barrel got there
    signed_timing_ms: float     # negative early, positive late

    aim_ft: tuple               # (x, z) in world feet at the plate
    handedness: str
    swing_type: int             # 1 contact (W), 2 power (E)

    on_time: int                # 0 mistimed, 1 foul window, 2 perfect
    made_contact: str           # no_swing / swung_and_miss / fouled / hit
    outcome: str

    # Fraction of the aim error the in-swing adjustment removed, from the
    # difficulty in force when the swing was committed. Defaulted rather than
    # required so a record built without one means "unassisted", which is what
    # every caller that predates the assist meant.
    aim_assist: float = 0.0
    # The difficulty in force when the swing was committed, carried for the
    # same reason `aim_assist` is: `timing_windows_ms` re-sweeps this swing to
    # measure the timing it actually had, and a player who changed difficulty
    # between the swing and the replay would otherwise be shown a window nobody
    # swung in.
    zone_size_mult: float = 1.0
    timing_window_mult: float = 1.0
    pitch_type: str = ""
    speed_mph: float = 0.0
    contact_quality: float = None
    vertical_offset_px: float = None
    exit_velocity_mph: float = None
    batted_ball_type: str = None
    ball_screen_at_contact: tuple = None
    # The sweep that decided this swing, when there was one. Held so the
    # replay can mark where the bat and the ball actually met rather than
    # where the barrel merely arrived — on a mistimed swing those are feet
    # apart, which is the whole thing the view is for.
    contact: object = None

    # -- derived ----------------------------------------------------------

    @property
    def contact_depth_ft(self):
        """Feet in front of the plate where the barrel met the ball.

        Positive is out front (early), negative is deep (late). Deliberately
        unclamped: past the plate the pitch model still describes a real ball
        heading into the catcher's mitt, and clamping it at zero would erase
        exactly the signal the replay exists to show.

        This is where the ball had got to when the **barrel arrived**, which on
        a mistimed swing is not where the two met — see `struck_depth_ft`. The
        pair is the timing error stated twice, once as a race and once as a
        place, and only the second is a frame anybody can be shown.
        """
        return self.trajectory.position_at(self.bat_arrival_s)[1]

    @property
    def shift_s(self):
        """Seconds the engine slid this swing to bring it to the ball.

        The timing assist, in the form the replay needs it: negative for a
        late swing, positive for an early one, zero when the swing needed no
        help or never made contact. See `bat_contact.resolve_contact`.
        """
        return 0.0 if self.contact is None else self.contact.shift_s

    @property
    def swing_launch_s(self):
        """When the *swept* swing started, in seconds after release.

        The clock `bat_contact.resolve_contact` actually walked, so a swing
        phase and a pitch instant convert into each other by adding it — which
        is the property everything drawn depends on.

        That is the commit instant plus `shift_s`, not the commit instant. The
        engine slides the swing by up to `timing_assist_s` before sweeping it,
        so the bat that produced this outcome started there; drawing the
        unslid one would put the picture back at odds with the verdict, the
        same failure as preferring the cursor at bat arrival over the cursor at
        commit. What the player *did* is reported separately and unmodified, by
        `signed_timing_ms`.
        """
        return self.bat_arrival_s - bat_path.SWING_DURATION_S + self.shift_s

    @property
    def contact_time_s(self):
        """When the bat and the ball actually met, in seconds after release.

        **Not `bat_arrival_s`, and conflating the two is what made the replay
        freeze on a frame where the bat and the ball are feet apart.**
        `bat_arrival_s` is when the *barrel reached its contact pose*, which is
        a fact about the swing and nothing else. The sweep is free to find the
        two at their closest anywhere in the swing — that is what sweeping
        means — and on a mistimed one it does, by up to ~25 ms of pitch time.
        At 101 mph that is six feet of ball, which is exactly the daylight the
        frozen frame used to show under a HOME RUN banner.

        Falls back to bat arrival when there was no contact to find: on a whiff
        the barrel's arrival is the only instant the swing names, and the gap
        to the ball there is the finding rather than an artefact.
        """
        if self.contact is None:
            return self.bat_arrival_s
        return self.contact.pitch_t_s

    @property
    def struck_depth_ft(self):
        """Feet in front of the plate where the ball was when it was struck.

        The depth of the frozen frame, and the one the replay draws. Distinct
        from `contact_depth_ft`, which is where the ball had got to when the
        *barrel arrived* — a different instant on a mistimed swing.
        """
        if self.contact is None:
            return self.contact_depth_ft
        return self.contact.depth_ft

    @property
    def contact_reach_ft(self):
        """Daylight between the bat's surface and the ball's when they "met".

        Negative on most contacts — the bat and the ball genuinely overlap —
        and never more than `margin_ft`, since that is the only forgiveness
        left with a distance in it. None when nothing was struck.

        It used to run to *feet*, because the timing forgiveness was spent as a
        reach along the ball's flight line; see
        `bat_contact.Contact.surface_gap_ft` for what that did and why it does
        not any more.
        """
        if self.contact is None:
            return None
        return self.contact.surface_gap_ft

    @property
    def spray_deg(self):
        """Which way the ball went: degrees from centre field, pull-positive.

        Read straight off the contact rather than stamped at commit, unlike
        `aim_assist` and the two multipliers beside it. Those have to be
        carried because the replay *rebuilds* the swing and re-sweeps it, so a
        player who changed difficulty in between would be shown a bat nobody
        swung. This is not rebuilt from anything — `spray` is difficulty-free,
        and the `Contact` on this record is the same object the verdict was
        reached from. None when nothing was struck.
        """
        if self.contact is None:
            return None
        return self.contact.spray_deg

    @property
    def is_early(self):
        return self.signed_timing_ms < 0

    @property
    def timing_label(self):
        """ON TIME when the timing alone would not have cost the ball.

        Measured against this swing's own fair window rather than a constant.
        It used to compare against `perfect_ms` — 30 ms scaled by difficulty,
        inherited from the timing *gate* the geometry replaced — which had
        stopped meaning anything: at ROOKIE it called everything inside 45 ms
        ON TIME while quality over that range ran from 1.00 down to 0.12, so
        the screenshot that started all of this read ON TIME over a foul.
        """
        window = self.timing_windows_ms.fair
        if window is not None and window[0] <= self.signed_timing_ms <= window[1]:
            return "ON TIME"
        return "EARLY" if self.is_early else "LATE"

    @property
    def timing_assist_ms(self):
        """How much of the clock this difficulty covers, in ms."""
        return bat_contact.timing_assist_s(self.timing_window_mult) * 1000.0

    @cached_property
    def timing_windows_ms(self):
        """The timing this swing actually had, measured by re-sweeping it.

        `TimingWindows(contact, fair)`, each an `(lo, hi)` pair of milliseconds
        about the datum `signed_timing_ms` is measured against, or None where
        no timing would have done — a swing aimed badly enough has no fair
        window at any timing, and saying so is more use than drawing a band it
        could never have reached.

        **Measured, not modelled**, which is the same choice `contact_depth_ft`
        makes: the swing is re-swept against its own pitch at a range of
        offsets and the boundaries are the ones `bat_contact` actually
        produces. The alternative is a difficulty-scaled constant, and the one
        that was here had drifted into fiction.

        Two things it shows that a symmetric pair of constants cannot. The
        windows are **strongly asymmetric** — about -42..+81 ms at AMATEUR,
        because a late bat still catches the ball on the handle while an early
        one runs out of barrel — and they are a property of **this swing**, so
        a pitch the player was never on top of draws a narrower band than one
        they were.

        Bisected rather than swept: 33 `resolve_contact` calls at about 1.6 ms,
        once, cached. Both predicates are contiguous in the offset (a test pins
        it), which is what makes bisection sound.
        """
        centre = self._probe_contact(0.0)
        return TimingWindows(
            contact=self._edge_pair(1) if centre >= 1 else None,
            fair=self._edge_pair(2) if centre >= 2 else None,
        )

    def _probe_contact(self, offset_ms):
        """0 whiff / 1 foul / 2 fair, for this swing mistimed by `offset_ms`."""
        swing = self._nominal_swing()
        due = self.trajectory.time_at_depth(swing.contact_depth_ft)
        contact = bat_contact.resolve_contact(
            swing, self.trajectory,
            due - bat_path.SWING_DURATION_S + offset_ms / 1000.0,
            zone_size_mult=self.zone_size_mult,
            timing_window_mult=self.timing_window_mult,
            power=(self.swing_type == 2))
        if contact is None:
            return 0
        threshold = bat_contact.foul_threshold(self.timing_window_mult)
        return 1 if contact.is_foul(threshold) else 2

    def _edge_pair(self, level):
        """(lo, hi) ms where this swing still reaches `level`, either side."""
        return (self._edge(-_WINDOW_SEARCH_MS, level),
                self._edge(_WINDOW_SEARCH_MS, level))

    def _edge(self, toward_ms, level):
        """Bisect the boundary between 0 (known good) and `toward_ms` (bad)."""
        ok, bad = 0.0, float(toward_ms)
        if self._probe_contact(bad) >= level:
            return bad
        for _ in range(_WINDOW_BISECT_STEPS):
            mid = 0.5 * (ok + bad)
            if self._probe_contact(mid) >= level:
                ok = mid
            else:
                bad = mid
        return ok

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

    @property
    def barrel_depth_ft(self):
        """Feet in front of the plate where the *barrel* was when it arrived.

        A property of the swing, not of the pitch: it follows from where the
        player aimed, because how far the aim point sits from the hands is how
        much the bat is foreshortened (see `bat_path._contact_pose`). Runs
        from about 0.4 ft on a ball low and away — met at the plate,
        inside-out — to 2.7 ft on one aimed inside, which is pulled and met
        well out in front. Compare it against `contact_depth_ft` to see the
        timing error as a distance.
        """
        return self._nominal_swing().contact_depth_ft

    @property
    def depth_gap_ft(self):
        """Barrel minus ball, in feet, at the instant the bat arrived.

        Negative means the ball had not got there yet and the bat was early;
        positive means it was already past and the bat was late. The same
        sign convention as `signed_timing_ms`, and the same fact, in the units
        the side view draws it in.
        """
        return self.barrel_depth_ft - self.contact_depth_ft

    def swing_aim_ft(self):
        """The aim the engine actually swung at: the cursor, resolved.

        `aim_ft` is the raw cursor at the plate, which is what the player
        pointed at; `bat_contact.aim_at_pitch` is what the engine turned that
        into before building the bat, because the barrel meets the ball a
        couple of feet out in front and the ball is not where the plate says
        it is out there. Recomputed here from the same pure function rather
        than carried on the record, so the replay's bat cannot drift away from
        the one that was swept.

        `aim_assist` is *carried*, not re-read, and that is what keeps the
        recompute honest: it is a difficulty setting, and a player who changes
        difficulty between the swing and the replay would otherwise be shown a
        bat nobody swung — the same failure as preferring the cursor at bat
        arrival over the cursor at commit.
        """
        return bat_contact.aim_at_pitch(self.aim_ft, self.trajectory,
                                        self.handedness,
                                        assist=self.aim_assist)

    def _nominal_swing(self):
        """The swing as the engine built it, at the resolved aim.

        Built only to read its own contact depth back off, which `bat_swing`
        then needs in order to work out how high to draw the bat. The final
        swing uses an aim a few inches different in `z`, which moves the
        barrel's depth by well under an inch — the aim's distance from the
        hands barely changes when only its height does.
        """
        return bat_path.swing(self.swing_aim_ft(), self.handedness)

    def _drawn_aim_ft(self, depth_ft):
        """The aim point to draw the bat at, for a barrel arriving at `depth_ft`.

        Not simply `aim_ft`, and the reason is worth stating. `aim_ft` is the
        cursor resolved to world feet *at the plate*, because that is the only
        depth `screen_to_world_at_plate` knows about. But the barrel meets the
        ball out in front of the plate, and the ball is meaningfully higher
        there — 6.4 inches higher at a contact point 5.6 ft out front, since it
        has that much less time to drop. Drawing the bat at its plate height
        against a ball at its true contact height therefore showed the bat
        half a foot *under* a ball the stats panel simultaneously reported it
        was 1.4 inches *over*. A replay whose picture contradicts its own
        numbers is worse than useless.

        So the bat is placed by the relationship the engine actually measured
        — `vertical_offset` is bat minus ball, in pygame's y-down screen
        convention, hence the sign flip into world feet — carried out to the
        depth where the *barrel* is. That is the plane the ball passes
        through, so it is the only place the two heights can honestly be
        compared. Timing (depth) and alignment (offset) are both then exactly
        what the engine judged, and the only thing given up is the bat's
        absolute height above the ground, which no player can perceive and
        nothing in the game reports.

        The offset has to be applied *at* that depth and then turned back into
        a plate-frame aim, not applied to the plate-frame aim directly: a
        cursor is a ray, so `bat_path` spreads whatever it is handed by 7% on
        the way out to the barrel, and 7% of a plate-frame offset is not the
        offset that was measured.

        When no offset was measured at all — a mistimed whiff never reaches
        the geometry test — there is nothing to align to and the plate-height
        aim is used unchanged.
        """
        aim = self.swing_aim_ft()
        offset_ft = self.vertical_offset_ft
        if offset_ft is None:
            return aim
        ball_z = self.trajectory.position_at(self._time_at_depth(depth_ft))[2]
        target = bat_path.to_plate_frame((0.0, ball_z + offset_ft), depth_ft)
        return (aim[0], target[1])

    def _time_at_depth(self, depth_ft):
        """When the ball was `depth_ft` in front of the plate."""
        return self.trajectory.time_at_depth(depth_ft)

    def bat_swing(self):
        """The bat that made this swing.

        Built from the aim and the batter's handedness alone. Nothing about
        the pitch reaches `bat_path` — that prohibition is the whole shape of
        this refactor, and `_drawn_aim_ft`'s few inches of vertical placement
        is the one concession, made so the picture agrees with the numbers
        printed under it.

        Iterated to a fixed point because that concession feeds back: nudging
        the aim's height moves it slightly along the cursor's ray, which moves
        the barrel's depth by about half an inch, which moves where the ball
        is when it gets there. Three passes settle it below a thousandth of an
        inch. `barrel_depth_ft` deliberately does *not* follow the iteration —
        it reports the depth the engine's own bat reached, from the raw cursor.
        """
        swing = self._nominal_swing()
        for _ in range(3):
            swing = bat_path.swing(
                aim_ft=self._drawn_aim_ft(swing.contact_depth_ft),
                handedness=self.handedness,
            )
        return swing

    def bat_state_at_ball_arrival(self):
        """Where the bat was when the ball reached the barrel's own depth.

        The reference frame the replay reads its timing error off, and it
        needs no second swing: with the path independent of the pitch, "the
        swing timed properly" is *this* swing sampled at a different phase.
        A late swing was still on its way there; an early one is already into
        the follow-through, which is why `bat_path` is defined past contact.
        """
        due = self._time_at_depth(self.barrel_depth_ft)
        return self.bat_swing().state_at(due - self.swing_launch_s)

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

    # The cursor at *commit*, not at bat arrival. The whole swing is decided
    # when the key goes down (`_handle_swing_input`), so the arrival-time
    # cursor names a bat that was never swung — it is kept only as a fallback
    # for a record built without one.
    aim_screen = sim.aim_screen_at_swing or sim.aim_screen_at_contact
    if aim_screen is None:
        return None

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
        aim_assist=sim.aim_assist,
        zone_size_mult=sim.zone_size_mult,
        timing_window_mult=sim.timing_window_mult,
        aim_ft=DEFAULT_CAMERA.screen_to_world_at_plate(*aim_screen),
        handedness=sim.game.batter.get_handedness(),
        swing_type=sim.swing_type,
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
        contact=sim.contact,
    )
