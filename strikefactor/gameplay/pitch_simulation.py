import random
from typing import TYPE_CHECKING

import pandas as pd
import pygame
import pygame.gfxdraw

from strikefactor.gameplay import bat_contact, bat_path, defense
from strikefactor.helpers import EnhancedPitchRecord
from strikefactor.utils.physics import collision
from strikefactor.utils.pitch_physics import DEFAULT_CAMERA, PitchTrajectory, UmpireCamera

if TYPE_CHECKING:
    from strikefactor.main import Game

import pickle
import threading

from strikefactor.config import ABS_BALL_RADIUS, ABS_ZONE, CHALLENGE_WINDOW_MS, get_path

# The ball/strike model is loaded lazily and cached. Loading it at import time
# made importing this module (and so anything that touches gameplay) require
# the pickle on disk plus scikit-learn, which is what kept the gameplay layer
# out of reach of tests.
#
# The pickle itself is ~6 KB and unpickles in well under a millisecond, but it
# holds an SVC, so unpickling triggers the first `import sklearn.svm` of the
# process — ~680 ms of import chain. The only caller is _make_ball_strike_call,
# reached the first frame past plate arrival, so left to fire on its own that
# cost lands as a visible freeze on the first taken or swung-through pitch of a
# session (mid-swing-animation, for a whiff). prewarm() moves it off the
# critical path; the lock keeps a prewarm in flight from racing a real call
# into loading it twice.
_umpire_model = None
_umpire_model_lock = threading.Lock()


def get_umpire_model():
    """Return the trained ball/strike SVC, loading it on first use."""
    global _umpire_model
    # Fast path: assignment is atomic, so a non-None read is always a fully
    # constructed model and needs no lock. Per-pitch calls never contend.
    if _umpire_model is not None:
        return _umpire_model
    with _umpire_model_lock:
        if _umpire_model is None:
            with open(get_path("ai/ai_umpire.pkl"), "rb") as f:
                _umpire_model = pickle.load(f)
    return _umpire_model

class PitchSimulation:
    # What the banner *calls* an outcome, where that differs from what the
    # game *records* it as. The recorded vocabulary is load-bearing free
    # text — "REACHED ON ERROR" is matched by exact string in about a dozen
    # places that fail silently on an unknown value (see
    # tests/test_outcome_names.py), so it is renamed here, at the one seam
    # where an outcome becomes words on screen, and nowhere else. On screen
    # the play has already shown itself: the fielder wears a "!" at the
    # moment of the misplay (hit_animation._charge_error), so the banner
    # only has to name it.
    _DISPLAY_NAMES = {
        "REACHED ON ERROR": "ERROR",
    }

    @staticmethod
    def _format_display_outcome(outcome):
        if not isinstance(outcome, str):
            return outcome
        return PitchSimulation._DISPLAY_NAMES.get(outcome, outcome.replace("_", " "))

    def __init__(self, game, release_point, pitchername, speed_mph, pfx_x, pfx_z,
                 target_x, target_y, pitchtype):
        self.game: "Game" = game
        self.release_point = release_point
        self.pitchername = pitchername
        self.speed_mph = speed_mph
        self.pfx_x = pfx_x
        self.pfx_z = pfx_z
        self.pitchtype = pitchtype

        # Camera for 3D -> 2D projection
        self.camera: UmpireCamera = DEFAULT_CAMERA

        # Convert screen-pixel targets to real-world feet at the plate
        self.target_x_ft, self.target_z_ft = self.camera.screen_to_world_at_plate(
            target_x, target_y
        )

        # Apply fatigue modifiers (GameDay mode)
        vel_mult, move_mult, mistake_chance = self.game.current_pitcher.get_fatigue_modifiers()
        effective_speed = speed_mph * vel_mult
        effective_pfx_x = pfx_x * move_mult
        effective_pfx_z = pfx_z * move_mult

        # Command outcome for this pitch (see Pitcher.get_pitch_target). A
        # hung pitch loses break as well as location — that combination is
        # what makes it punishable rather than just mislocated.
        self.pitch_intent = getattr(self.game.current_pitcher, 'last_intent', None)
        if self.pitch_intent is not None:
            if self.pitch_intent.break_mult != 1.0:
                effective_pfx_x *= self.pitch_intent.break_mult
                effective_pfx_z *= self.pitch_intent.break_mult
            self.intent_x_ft, self.intent_z_ft = self.camera.screen_to_world_at_plate(
                self.pitch_intent.intent_x, self.pitch_intent.intent_y
            )
        else:
            self.intent_x_ft = self.intent_z_ft = None

        # Mistake pitch: drift target toward center zone
        self.mistake_pitch = False
        if mistake_chance > 0 and random.random() < mistake_chance:
            # Center zone in feet: roughly x=0, z=2.8 (mid-zone height)
            self.target_x_ft = self.target_x_ft * 0.3  # Pull 70% toward center
            self.target_z_ft = self.target_z_ft * 0.3 + 2.8 * 0.7
            effective_pfx_x *= 0.5  # Reduced break on mistake pitches
            effective_pfx_z *= 0.5
            self.mistake_pitch = True

        # Store effective speed for display
        self.speed_mph = effective_speed

        # Get 3D release position from the current pitcher
        release_pos_3d = self.game.current_pitcher.release_pos_3d

        # Create 3D trajectory
        self.trajectory = PitchTrajectory.from_pitch_params(
            release_pos=release_pos_3d,
            speed_mph=effective_speed,
            pfx_x_inches=effective_pfx_x,
            pfx_z_inches=effective_pfx_z,
            target_x_ft=self.target_x_ft,
            target_z_ft=self.target_z_ft,
        )

        # Travel time from 3D physics (milliseconds)
        self.traveltime = self.trajectory.travel_time_ms

        # Initialize state from the original main_simulation method
        self.running = True
        self.game.first_pitch_thrown = True
        self.game.swing_started = 0
        # New pitch started → previous-pitch challenge window closes.
        if hasattr(self.game, 'clear_pending_challenge'):
            self.game.clear_pending_challenge()

        # Initialize ball at projected release position
        proj = self.camera.project(*release_pos_3d)
        if proj:
            self.game.ball = [proj[0], proj[1], self.trajectory.y0]
        else:
            self.game.ball = [self.release_point[0], self.release_point[1], self.trajectory.y0]

        self.soundplayed = 0
        self.sizz = False
        self.on_time = 0
        self.made_contact = "no_swing"
        self.contact_time = 0
        self.swing_type = 0
        self.pitch_results_done = False
        self.is_strike = False
        self.is_hit = False
        self.previous_state = self.game.current_state
        self.recording_state = 0

        # Pitch-data fields populated through the pitch lifecycle and
        # consumed by PitchDatabaseService.record_pitch in cleanup().
        self.swing_timing_diff_ms = None  # set in _handle_swing_input
        # Signed form of the same number: negative is early, positive is late.
        # The abs() above is what the DB has always stored, so it stays as it
        # is — widening it would change what every existing aggregate means.
        self.swing_timing_signed_ms = None
        # Swing reconstruction, consumed by SwingRecord in cleanup(). The bat
        # is the mouse cursor, and until these existed it was polled live
        # inside the contact frame and thrown away, so nothing after the fact
        # could say where the bat had been. swing_starttime is seeded here for
        # the same reason: it used to spring into existence only when a swing
        # happened, so every read of it needed a getattr.
        self.swing_starttime = None
        # The swing itself, and the sweep of it against this pitch. Both are
        # decided once, at commit, and everything after reads them.
        self.bat_swing = None
        self.contact = None
        # The cursor resolved against this pitch — see `bat_contact.aim_at_pitch`.
        self.swing_aim_ft = None
        # How much of the aim error the in-swing adjustment removed, recorded
        # at commit rather than read back later: difficulty can change between
        # the swing and the replay, and the replay must show the bat that was
        # swung.
        self.aim_assist = 0.0
        self.zone_size_mult = 1.0
        self.timing_window_mult = 1.0
        self.aim_screen_at_swing = None    # cursor when the swing was committed
        self.aim_screen_at_contact = None  # cursor when the bat arrived
        self.ball_screen_at_contact = None
        self.contact_quality = None       # mirrored from HitOutcomeManager.last_quality
        self.vertical_offset_in = None    # mirrored from HitOutcomeManager.last_vertical_offset
        self.exit_velocity_mph = None     # modelled at contact; drives the contact SFX
        # Batted-ball record, mirrored off the animation once it resolves (see
        # _finalize_batted_ball). Type is classified at contact, upstream of
        # any fielding decision, which is what makes it usable as an
        # independent slice; role and margin describe the play that decided
        # the outcome and stay None when no race was run.
        self.batted_ball_type = None
        self.fielder_role = None
        self.play_margin_s = None
        # Which way the ball left the bat, pull-positive degrees. Set on every
        # bat-on-ball event including fouls — a foul has a direction and it is
        # often *why* it was a foul — and left None on a whiff, where there is
        # no ball to have a direction. Same shape as `exit_velocity_mph`.
        self.spray_angle_deg = None
        # Foul contact metrics, computed in _handle_foul_ball. Fouls never
        # run the hit pipeline, so last_quality is stale for them — these
        # are the foul's own numbers, shared by the sound and the animation.
        self._foul_quality = None
        self._foul_vertical_offset = None
        self.ai_umpire_strike = None      # set in _make_ball_strike_call (taken pitches only)
        self.truth_strike = None          # set in _make_ball_strike_call (taken pitches only)
        self.abs_challenged = False       # toggled by ABS challenge wiring (see _challenge bookkeeping)
        self.abs_overturned = False
        self.runs_scored_on_pitch = 0     # filled in cleanup() from scoreKeeper delta
        self._score_before_pitch = self.game.scoreKeeper.get_score()

        # Set when a hit is registered; the animation runs in place of
        # follow-through and defers the outcome banner until it finishes.
        # Player presses any key to advance once the banner is up.
        self.hit_animation = None

        self.new_entry = {
            'Pitcher': self.pitchername, 'PitchType': self.pitchtype, 'FirstX': 0, 'FirstY': 0,
            'SecondX': 0, 'SecondY': 0, 'FinalX': 0, 'FinalY': 0, 'isHit': "false",
            'called_strike': False, 'foul': False, 'swinging_strike': False, 'ball': False, 'in_zone': False
        }

        self.new_data_entry = {
            'Pitcher': self.pitchername, 'PrevPitch': self.game.last_pitch_type_thrown,
            'Strikes': self.game.currentstrikes, 'Balls': self.game.currentballs, 'Outs': self.game.currentouts,
            'Handedness': self.game.batter.get_handedness(), 'RunnerFirst': self.game.scoreKeeper.isRunnerOnBase(1),
            'RunnerSecond': self.game.scoreKeeper.isRunnerOnBase(2), 'RunnerThird': self.game.scoreKeeper.isRunnerOnBase(3),
            'PitchResult': self.pitchtype,
        }

        self.game.last_pitch_information = []
        self.starttime = pygame.time.get_ticks()
        self.last_time = self.starttime
        self.windup = self.game.current_pitcher.get_windup()
        self.arrival_time = self.starttime + self.windup + self.traveltime

        # Get engine FPS setting for physics calculations
        self.engine_fps = self.game.settings_manager.get_engine_fps()

    def run(self):
        self.game.ui_manager.hide_banner()
        self.game.ui_manager.set_button_visibility('pitching')

        while self.running:
            self.update()

    def update(self):
        """Main simulation update loop."""
        self.game.sound_manager.update()
        self.game.screen.fill("black")
        time_delta = self.game.clock.tick_busy_loop(self.engine_fps)/1000.0

        current_time = pygame.time.get_ticks()

        # Hit animation owns the frame once active — bypasses pitcher draw,
        # trajectory tracking, and the normal phase dispatch below.
        if self.hit_animation is not None:
            self._handle_hit_animation_phase(current_time, time_delta)
            return

        self.game.ui_manager.draw()
        self.game.ui_manager.update(time_delta)

        self.game.current_pitcher.draw_pitcher(self.starttime, current_time)

        if self.starttime + self.windup < current_time < self.arrival_time:
            pass  # loops tracking if needed

        # Update pitch trajectory
        self._update_pitch_trajectory(current_time)
        self._capture_bat_arrival(current_time)

        # Handle different phases of the pitch
        if current_time <= self.starttime + self.windup:
            self._handle_windup_phase(current_time)
        elif self._is_ball_in_flight(current_time):
            self._handle_ball_flight_phase(current_time)
        elif self._is_contact_time(current_time):
            self._handle_contact_phase(current_time)
        elif self._is_follow_through_time(current_time):
            self._handle_follow_through_phase(current_time)
        elif current_time > self.arrival_time + 700:
            self._finish_pitch()

    def _update_pitch_trajectory(self, current_time):
        """Update pitch trajectory tracking."""
        elapsed_time = current_time - self.last_time

        if elapsed_time >= 10 and current_time - self.starttime > self.windup or (current_time - self.starttime > self.windup and not self.pitch_results_done):
            self.last_time = current_time
            if current_time > self.starttime + self.traveltime + self.windup and hasattr(self, 'outcome') and self.outcome in ['FLYOUT', 'GROUNDOUT', 'LINEOUT', 'POP UP']:
                entry = [self.game.ball[0], self.game.ball[1], self.game.fourseamballsize, (198, 169, 251), "out"]  # Purple for outs
            elif current_time > self.starttime + self.traveltime + self.windup and self.is_hit:
                entry = [self.game.ball[0], self.game.ball[1], self.game.fourseamballsize, (71, 204, 252), "hit"]
            elif current_time > self.starttime + self.traveltime + self.windup and self.pitch_results_done and self.is_strike:
                entry = [self.game.ball[0], self.game.ball[1], self.game.fourseamballsize, (227, 75, 80), "strike"]
            elif current_time > self.starttime + self.traveltime + self.windup and self.pitch_results_done and not self.is_strike:
                entry = [self.game.ball[0], self.game.ball[1], self.game.fourseamballsize, (75, 227, 148), "ball"]
            else:
                # Use projected ball radius for trail size
                ball_y_world = self._get_world_y(current_time)
                proj_radius = self.camera.project_radius(ball_y_world)
                trail_size = max(4, min(11, int(proj_radius * 1.2)))
                entry = [self.game.ball[0], self.game.ball[1], trail_size, (255,255,255), ""]
            self.game.last_pitch_information.append(entry)

        # Record trajectory points
        if self.recording_state == 0 and self.windup < (current_time - self.starttime) < self.windup + 200:
            self.recording_state += 1
            self.new_entry['FirstX'] = self.game.ball[0]
            self.new_entry['FirstY'] = self.game.ball[1]
        if self.recording_state == 1 and (current_time - self.starttime) > 1500:
            self.recording_state += 1
            self.new_entry['SecondX'] = self.game.ball[0]
            self.new_entry['SecondY'] = self.game.ball[1]

    def _get_world_y(self, current_time):
        """Get the ball's real-world y coordinate (distance from plate) at current time."""
        time_since_release = (current_time - self.starttime - self.windup) / 1000.0
        if time_since_release < 0:
            return self.trajectory.y0
        _, y, _ = self.trajectory.position_at(time_since_release)
        return max(0, y)

    def _handle_windup_phase(self, current_time):
        """Handle pitcher windup phase."""
        self.game.batter.leg_kick(current_time, self.starttime + self.windup - 300)
        self.game.field_renderer.draw_strikezone()
        self.game.field_renderer.draw_field(self.game.scoreKeeper.get_bases())
        self.game.flip_display()

    def _is_ball_in_flight(self, current_time):
        """Check if ball is in flight and available for hitting."""
        return ((current_time > self.starttime + self.windup
                and current_time < self.arrival_time
                and (self.on_time == 0 or (self.on_time > 0 and self.made_contact == "swung_and_miss")))
                or (self.on_time > 0 and current_time <= self.contact_time and self.made_contact == "no_swing"))

    def _handle_ball_flight_phase(self, current_time):
        """Handle ball flight phase with input detection."""
        if not self.sizz:
            self.sizz = True
            self.game.sound_manager.play('sizzle')

        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if current_time < self.arrival_time - 100:
                    self._handle_swing_input(event, current_time)

        self._draw_batter(current_time)
        self._update_ball_position(current_time)
        self.game.field_renderer.draw_strikezone()
        self.game.field_renderer.draw_field(self.game.scoreKeeper.get_bases())
        self.game.flip_display()

        # Ball reaching glove sound
        if ((current_time > (self.arrival_time - 30) and self.soundplayed == 0 and self.on_time == 0) or
            (current_time > self.contact_time and self.soundplayed == 0 and
             (self.on_time > 0 and self.made_contact == "swung_and_miss"))):
            self.game.sound_manager.glovepop()
            self.soundplayed += 1

    def _handle_swing_input(self, event, current_time):
        """Handle swing input from player."""
        # Only the first contact/power keypress of a pitch registers a swing.
        # Later keypresses (the flight phase keeps draining events until
        # contact) must be ignored, otherwise they re-stamp swing_starttime /
        # contact_time and shift the contact window of an already-committed
        # swing, corrupting its recorded timing and quality.
        if self.game.swing_started != 0 or event.key not in (pygame.K_w, pygame.K_e):
            return

        mousepos = self.game.get_mouse_pos()
        self.swing_starttime = pygame.time.get_ticks()
        self.aim_screen_at_swing = mousepos
        self.swing_type = 1 if event.key == pygame.K_w else 2

        # The whole swing is decided here, at the moment it is committed.
        #
        # It used to be decided in two places at two times: a timing grade
        # taken now, and a rectangle-versus-ball test taken 150 ms later
        # against the cursor *as it was then* — which let a player re-aim
        # during the swing. A real swing path cannot change once it has
        # started, and now neither can this one: the bat is built from the
        # cursor at commit and swept against the pitch's own trajectory.
        #
        # The cursor is resolved against the pitch before the bat is built.
        # A cursor is a ray: `bat_path` puts the barrel on it at the depth the
        # barrel reaches, a couple of feet in front of the plate, but the
        # player is pointing at a ball drawn all the way *to* the plate. The
        # ball is two to five inches higher where the bat will be, which is
        # the entire 2.75 in of tolerance between a bat and a ball — so a
        # perfectly aimed, perfectly timed swing fouled everything and missed
        # a curveball outright. `bat_contact.aim_at_pitch` translates the
        # cursor onto the barrel's depth, and `bat_path` still never sees the
        # pitch.
        #
        # `resolve_aim` does one further thing, and it is a different kind of
        # thing: it pulls the aim a difficulty-scaled fraction of the way toward
        # the ball — the adjustment a hitter makes once they have read the pitch,
        # capped at `bat_contact.MAX_ASSIST_FT` so a genuinely bad guess still
        # misses. The depth correction above is a bias the player could not have
        # seen; the assist shrinks an error they genuinely made. Don't let the
        # two be read as one thing: the first is a bug fix and the second is
        # game feel, and only the second belongs on a difficulty ladder.
        self.aim_assist = self.game.hit_outcome_manager.aim_assist()
        # Stamped at commit and carried on the record, so the replay can
        # re-sweep this swing to measure the timing it actually had. Re-reading
        # difficulty at replay time would show a window nobody swung in.
        self.zone_size_mult, self.timing_window_mult = (
            self.game.hit_outcome_manager.contact_multipliers(self.swing_type))
        self.swing_aim_ft = self.game.hit_outcome_manager.resolve_aim(
            DEFAULT_CAMERA.screen_to_world_at_plate(*mousepos),
            self.trajectory,
            self.game.batter.get_handedness(),
        )
        self.bat_swing = bat_path.swing(
            aim_ft=self.swing_aim_ft,
            handedness=self.game.batter.get_handedness(),
        )
        swing_start_s = (self.swing_starttime - self.starttime - self.windup) / 1000.0
        self.contact = self.game.hit_outcome_manager.resolve_swing(
            self.bat_swing, self.trajectory, swing_start_s, self.swing_type)
        self.on_time = self.game.hit_outcome_manager.swing_verdict(
            self.contact, self.swing_type)

        # When the barrel and the ball actually met, or when the barrel
        # reached its contact pose if they never did.
        #
        # Read off the *pitch* clock rather than by adding the swing's phase to
        # the keypress. The engine may have slid the swing to bring it to the
        # ball (`bat_contact.Contact.shift_s`) and the two clocks then differ
        # by exactly that much; `pitch_t_s` is when the ball was where the
        # contact says it was, which is the instant everything drawn has to
        # agree with. Identical to the old arithmetic whenever the shift is 0.
        if self.contact is not None:
            self.contact_time = int(self.starttime + self.windup
                                    + self.contact.pitch_t_s * 1000.0)
        else:
            self.contact_time = self.swing_starttime + bat_path.SWING_DURATION_MS

        # Capture timing diff for analytics regardless of contact result.
        # Swing-and-miss pitches still need a timing-diff signal to study
        # player skill — without this the field is null on every miss.
        self.swing_timing_signed_ms = self._signed_timing_ms()
        self.swing_timing_diff_ms = abs(self.swing_timing_signed_ms)

        self.game.swing_started = 1 if mousepos[1] > 500 else 2

    def _signed_timing_ms(self):
        """How far off the swing was, in ms. Negative early, positive late.

        Measured against the ball reaching **the barrel's own contact depth**,
        not the plate. The bat meets the ball a couple of feet out in front
        (further on a pitch inside, which is more foreshortened and so pulled
        earlier), and grading a swing against the plate therefore reported a
        swing that met the ball perfectly as about 17 ms early. The datum is
        now the thing the player is actually racing.

        The one place this is computed. It used to be written out twice —
        abs()'d at swing input for the DB, and recomputed with its sign in
        `_compute_foul_contact_metrics` under a comment explaining why — so
        the sign existed but only fouls ever saw it.
        """
        if self.swing_starttime is None or self.bat_swing is None:
            return None
        swing_start_s = (self.swing_starttime - self.starttime - self.windup) / 1000.0
        return 1000.0 * bat_contact.timing_error_s(
            self.bat_swing, self.trajectory, swing_start_s)

    @property
    def barrel_depth_ft(self):
        """Feet in front of the plate where this swing's barrel arrives."""
        if self.bat_swing is None:
            return 0.0
        return self.bat_swing.contact_depth_ft

    def _capture_bat_arrival(self, current_time):
        """Record where the bat and ball were when the barrel got there.

        Runs for *every* swing, which is the point. A mistimed swing
        (`on_time == 0`) never reaches `_evaluate_contact` at all — the whiff
        is decided by timing alone, with no geometry test — so the swings a
        player most needs explained were the ones leaving no trace.
        """
        if self.swing_starttime is None or self.aim_screen_at_contact is not None:
            return
        if current_time < self.contact_time:
            return
        self.aim_screen_at_contact = self.game.get_mouse_pos()
        self.ball_screen_at_contact = (self.game.ball[0], self.game.ball[1])

    def _is_contact_time(self, current_time):
        """Check if it's contact evaluation time."""
        return (self.on_time > 0
                and current_time > self.contact_time
                and current_time <= self.arrival_time + 700
                and self.made_contact != "swung_and_miss")

    def _handle_contact_phase(self, current_time):
        """Handle contact evaluation phase."""
        self._draw_batter(current_time)
        self.game.field_renderer.draw_strikezone()
        self.game.field_renderer.draw_field(self.game.scoreKeeper.get_bases())
        pygame.gfxdraw.aacircle(self.game.screen, int(self.game.ball[0]), int(self.game.ball[1]),
                               self.game.fourseamballsize, (255,255,255))
        self.game.flip_display()

        if not self.pitch_results_done:
            self._evaluate_contact()

        # Play contact sounds. Fouls and fair contact go through the same
        # exit-velocity model — the sample is chosen by how hard the ball
        # was struck, not by which branch we are in, so a scorched foul
        # cracks and a checked-swing tapper on the screws does not.
        if (current_time > self.contact_time and self.soundplayed == 0 and self.pitch_results_done):
            swing_type = "power" if self.swing_type == 2 else "contact"
            if self.on_time == 1:
                self.exit_velocity_mph = self.game.sound_manager.play_contact(
                    self._foul_quality, swing_type)
                self.soundplayed += 1
            elif self.on_time == 2:
                # On a home run the animation already exists (it is built in
                # _evaluate_contact, above) and has fixed the carry distance.
                # Hand that to the sound so the crack matches the FT readout
                # the player is about to see — the carry model's randomness
                # means quality alone can put a soft crack under a 460-footer.
                hr_distance = getattr(self.hit_animation, "hr_distance_ft", None)
                self.exit_velocity_mph = self.game.hit_outcome_manager.play_hit_sound(
                    swing_type, hr_distance_ft=hr_distance)
                self.soundplayed += 1

    def _evaluate_contact(self):
        """Play out the contact resolved at swing commit.

        Nothing is decided here any more — `resolve_swing` swept the bat
        against the ball the moment the player committed, and this is the
        frame where that result becomes visible.
        """
        if self.contact is not None:
            self.spray_angle_deg = self.contact.spray_deg

        if self.contact is None:
            self.made_contact = "swung_and_miss"
        elif self.on_time == 1:
            self._handle_foul_ball()
        elif self.on_time == 2:
            self._handle_successful_hit()

    def _compute_foul_contact_metrics(self):
        """Measure the foul's contact quality, offset and signed timing.

        Runs on every foul, not just animated ones: the contact sound is
        picked from `quality`, so gating this behind foul_animation_enabled
        would leave players with that setting off hearing one flat sample
        for every foul — the exact behaviour this refactor removes.
        Results are cached on self for _start_foul_animation to reuse.

        The foul's *direction* is no longer computed here. It used to be a
        `_foul_timing_norm` in [-1, 1] — the sign of the swing's timing error
        against a `_foul_spray_window` of hand-tuned milliseconds, which the
        animation turned into "pull side" or "opposite field". Both are gone:
        the ball has a real bearing now (`Contact.spray_deg`), the same one a
        fair ball gets, and a foul is simply one whose bearing fell outside the
        lines or whose contact was too glancing to matter. That comment's
        standing offer — *if it ever stops being cosmetic, measure it* — is
        what this is.
        """
        quality, vertical_offset = self.game.hit_outcome_manager.contact_metrics(
            self.contact)

        self._foul_quality = quality
        self._foul_vertical_offset = vertical_offset

    def _handle_foul_ball(self):
        """Handle foul ball outcome."""
        self._compute_foul_contact_metrics()
        self.outcome = 'foul'
        self.game.strikes += 1
        self.is_strike = True
        self.new_entry['foul'] = True
        self.made_contact = "fouled"
        self.pitch_results_done = True
        self.game.pitchnumber += 1
        if self.game.currentstrikes < 2:
            self.game.currentstrikes += 1
        if self.game.settings_manager.get_setting("foul_animation_enabled"):
            self._start_foul_animation()
        else:
            self.game._display_pitch_results("FOUL", self.pitchtype, self.speed_mph)

    def _handle_successful_hit(self):
        """Handle successful hit outcome."""
        self.game.strikes += 1
        self.made_contact = "hit"
        self.pitch_results_done = True
        self.game.pitchnumber += 1

        # Track score BEFORE hit for gameday mode (MUST be before calling hit_outcome_manager)
        score_before = self.game.scoreKeeper.get_score() if self.game.in_gameday_mode else 0

        # Apply momentum bonus in gameday mode
        if self.game.in_gameday_mode and self.game.gameday_manager:
            self.game.hit_outcome_manager.momentum_bonus = self.game.gameday_manager.get_player_momentum_bonus()
        else:
            self.game.hit_outcome_manager.momentum_bonus = 0.0

        if self.swing_type == 1:
            hit_string = self.game.hit_outcome_manager.get_contact_hit_outcome(
                self.contact)
        elif self.swing_type == 2:
            hit_string = self.game.hit_outcome_manager.get_power_hit_outcome(
                self.contact)

        # Snapshot contact metrics for the hit animation (shape + HR distance).
        contact_quality = self.game.hit_outcome_manager.last_quality
        contact_vertical_offset = self.game.hit_outcome_manager.last_vertical_offset

        # Mirror onto sim for the DB record. vertical_offset is in screen px;
        # the column name keeps "_in" for parity with future units cleanup.
        self.contact_quality = contact_quality
        self.vertical_offset_in = contact_vertical_offset
        # Classified at contact from (quality, offset), so it is set for home
        # runs too — those never reach _finalize_batted_ball, and a GB/FB
        # split that silently omitted every HR would be worse than none.
        self.batted_ball_type = self.game.hit_outcome_manager.last_batted_ball_type

        # Unified contact result. HOME RUN is decided at contact (the ball
        # is aimed past the wall); everything else is deferred to the
        # animation, which resolves FLYOUT / GROUNDOUT / SINGLE / DOUBLE /
        # TRIPLE from fielder routing + interception.
        self._handle_contact_result(hit_string, score_before, contact_vertical_offset, contact_quality)

    def _handle_contact_result(self, hit_string, score_before=0, vertical_offset=0.0, quality=0.0):
        """Unified ball-in-play path.

        For HOME RUN, the outcome is fully known at contact (the ball
        carries past the wall by definition) and the inline path advances
        runners, records stats, and fires the banner once the HR animation
        completes.

        For IN_PLAY — the generic ball-in-play outcome — the final result
        is whatever the animation resolves to: FLYOUT or GROUNDOUT if a
        fielder intercepts; SINGLE/DOUBLE/TRIPLE if the ball gets past
        them. We record the at-bat and reset counts here (those fire
        regardless of resolution) and stash the inputs needed at finalize
        time; the rest is applied by _finalize_batted_ball once
        HitAnimation.classified_outcome is set.
        """
        # At-bat is recorded unconditionally — every contact counts as an
        # AB regardless of how it resolves.
        self.game.field_renderer.record_at_bat()

        if hit_string == "HOME RUN":
            self.is_hit = True
            self.game.hits += 1
            homerun_text = self.game.hit_outcome_manager.get_homerun_text()
            self.game.field_renderer.record_hit(
                self.game.ball[0], self.game.ball[1], hit_type=hit_string
            )
            if homerun_text != '':
                self.game.homeruns_allowed += 1
            banner_text = homerun_text if homerun_text != '' else hit_string
            self._start_hit_animation(hit_string, banner_text, vertical_offset, quality)
            self.game._display_pitch_results(
                f"HIT - {self._format_display_outcome(hit_string)}",
                self.pitchtype,
                self.speed_mph,
            )
            self.new_entry['isHit'] = hit_string
            self.outcome = hit_string

            if self.game.in_gameday_mode:
                runs_scored = self.game.scoreKeeper.get_score() - score_before
                self.game.gameday_manager.record_player_at_bat(
                    hit_string, runs_scored=runs_scored, pitches_thrown=self.game.pitchnumber
                )
                self._check_walkoff()
        else:
            # IN_PLAY — defer everything that depends on the final outcome.
            # is_hit / hits / currentouts are NOT touched here;
            # _finalize_batted_ball sets them based on the animation's
            # resolution.
            self._pending_hit_score_before = score_before
            self._pending_hit_pitchnumber = self.game.pitchnumber
            # Placeholder; replaced with the classified outcome at finalize.
            self.outcome = hit_string
            self.new_entry['isHit'] = hit_string
            self._start_hit_animation(hit_string, banner_text=None,
                                      vertical_offset=vertical_offset, quality=quality)
            self.game._display_pitch_results("IN PLAY", self.pitchtype, self.speed_mph)

        # Reset pitch counts after contact (same as strikeout / walk).
        self.game.pitchnumber = 0
        self.game.currentstrikes = 0
        self.game.currentballs = 0

    def _finalize_batted_ball(self):
        """Apply deferred state once the animation has classified the
        contact into its final outcome — FLYOUT, GROUNDOUT, SINGLE,
        DOUBLE, or TRIPLE. Wired as the on_complete callback for the
        unified IN_PLAY animation.
        """
        # Safety fallback in case classification didn't run (animation
        # ended without resolving — shouldn't happen, but treat as SINGLE).
        classified = getattr(self.hit_animation, 'classified_outcome', None) or "SINGLE"
        score_before = getattr(self, '_pending_hit_score_before', 0)
        pitches_thrown = getattr(self, '_pending_hit_pitchnumber', 0)

        # Mirror the animation's fielding record for the DB (schema v7). The
        # margin stays None unless a race actually decided the play, which is
        # the distinction that makes the column falsifiable: a ball nobody
        # fielded has no margin, and recording a 0.0 for it would put a spike
        # at dead-even in a distribution whose whole purpose is its shape.
        self.fielder_role = getattr(self.hit_animation, 'fielder_role', None)
        timing = getattr(self.hit_animation, 'play_timing', None)
        self.play_margin_s = timing.margin_s if timing is not None else None

        # Three states, not two. Reaching on an error is neither an out nor a
        # hit, and the old binary put it in the `else` — crediting the batter
        # a hit, incrementing `game.hits`, and feeding it to the batting
        # heatmap as though they had earned it.
        is_out = classified in ("FLYOUT", "GROUNDOUT", "LINEOUT", "POP UP")
        is_error = classified == "REACHED ON ERROR"
        if is_out:
            self.is_hit = False
            self.game.currentouts += 1
        elif is_error:
            self.is_hit = False
        else:
            self.is_hit = True
            self.game.hits += 1

        # Recolor the trail dot now that we know whether contact resolved
        # as a hit or an out. _start_hit_animation appended a placeholder
        # blue marker because resolution is deferred until the ball is
        # fielded; track-mode keys off pitch[-1][3], so update it here.
        # _finish_pitch later propagates this color to any in-flight entries
        # sharing the same plate coordinates.
        out_color = (119, 86, 179)
        hit_color = (71, 204, 252)
        error_color = (214, 158, 46)      # amber: reached, but not earned
        new_trail_color = (out_color if is_out
                           else error_color if is_error
                           else hit_color)
        if self.game.last_pitch_information:
            last_entry = self.game.last_pitch_information[-1]
            if len(last_entry) >= 5 and last_entry[4] == "hit":
                last_entry[3] = new_trail_color

        # Advance runners + score for hits (no-op for outs).
        suppress_out_advancement = is_out and self.game.currentouts >= 3
        self.game.hit_outcome_manager.apply_classified_outcome(
            classified,
            suppress_out_advancement=suppress_out_advancement,
            bases=getattr(self.hit_animation, 'error_bases', 1),
        )

        # Hit-location stats only record actual hits — outs don't contribute
        # to the batting-zone heatmap.
        # `record_hit` increments `total_hits` unconditionally, so an error
        # must not reach it — the batting heatmap is a record of hits earned.
        if not is_out and not is_error:
            self.game.field_renderer.record_hit(
                self.game.ball[0], self.game.ball[1], hit_type=classified
            )

        if self.game.in_gameday_mode:
            runs_scored = self.game.scoreKeeper.get_score() - score_before
            self.game.gameday_manager.record_player_at_bat(
                classified, runs_scored=runs_scored, pitches_thrown=pitches_thrown
            )
            if not is_out:
                self._check_walkoff()

        # No sound here — the contact sound already played at impact via
        # play_hit_sound(), with selection driven by contact quality.
        # Playing again at the banner reveal would double-trigger the SFX.

        self.new_entry['isHit'] = classified
        self.outcome = classified

        self.game.ui_manager.show_banner(self._format_display_outcome(classified))

    def _check_walkoff(self):
        """Check for walk-off win and flag a deferred game-end transition.

        We do NOT stop the simulation here — letting the contact/follow-through
        phases run out so the swing animation completes, the glove sound plays,
        and `_finish_pitch` -> `cleanup()` records the winning pitch for
        pitchviz. The state change is performed in `_finish_pitch` once the
        pitch has fully resolved.

        The "WALK-OFF WIN!" banner is owned by the celebration sequence in
        InningEndState — letting the hit/walk banner stay visible through
        the follow-through gives the celebration a natural first beat.
        """
        if (self.game.in_gameday_mode
                and self.game.gameday_manager.check_walkoff()):
            # check_walkoff() already committed the walk-off half-inning's runs
            # to player_inning_scores and cleared _current_half_runs — appending
            # here as well would add a phantom 0-run inning to the linescore and
            # to the saved history record.

            # Mark inning as ended so check_inning_end() doesn't double-process
            # and so view-pitches navigation routes back to inning_end, not
            # gameplay.
            self.game.inning_ended = True

            self._pending_walkoff = True

    def _is_follow_through_time(self, current_time):
        """Check if it's follow through time."""
        return (current_time > self.arrival_time
                and current_time <= self.arrival_time + 700
                and (self.on_time == 0 or (self.on_time > 0 and self.made_contact == "swung_and_miss")))

    def _handle_follow_through_phase(self, current_time):
        """Handle follow through phase and ball/strike calls."""
        if (current_time > self.contact_time and self.soundplayed == 0 and
            (self.on_time > 0 and self.made_contact == "swung_and_miss")):
            self.game.sound_manager.glovepop()
            self.soundplayed += 1

        self._draw_batter(current_time)
        self.game.field_renderer.draw_strikezone()
        self.game.field_renderer.draw_field(self.game.scoreKeeper.get_bases())
        pygame.gfxdraw.aacircle(self.game.screen, int(self.game.ball[0]), int(self.game.ball[1]),
                               self.game.fourseamballsize, (255,255,255))
        self.game.flip_display()

        if not self.pitch_results_done:
            self._make_ball_strike_call()

    def _make_ball_strike_call(self):
        """Make the umpire's ball/strike call and open the ABS challenge window."""
        self.pitch_results_done = True

        is_taken = (self.game.swing_started == 0)

        # Determine umpire's call AND geometric truth at the same point.
        umpire_says_ball = (
            not get_umpire_model().predict(
                pd.DataFrame([[self.game.ball[0], self.game.ball[1]]],
                             columns=['finalx', 'finaly']))
            and is_taken
        )
        truth_strike = collision(
            self.game.ball[0], self.game.ball[1], ABS_BALL_RADIUS, *ABS_ZONE
        )
        original_call = "ball" if umpire_says_ball else "strike"

        # Snapshot for the DB row — these stay None for pitches that were
        # swung at, since the umpire never made a call on those.
        if is_taken:
            self.ai_umpire_strike = not umpire_says_ball
            self.truth_strike = bool(truth_strike)

        # Snapshot the full game state BEFORE commit so the ABS challenge can
        # fully reverse it later — including terminal walks and strikeouts.
        snapshot = None
        if is_taken and hasattr(self.game, 'snapshot_for_abs'):
            snapshot = self.game.snapshot_for_abs()

        if umpire_says_ball:
            self._handle_ball_call()
        else:
            self._handle_strike_call()

        # Only taken pitches are challengeable per MLB rule.
        if not is_taken or snapshot is None:
            return

        if hasattr(self.game, 'open_abs_challenge_window'):
            self.game.open_abs_challenge_window(
                ball_xy=(self.game.ball[0], self.game.ball[1]),
                original_call=original_call,
                truth_strike=bool(truth_strike),
                trajectory=list(self.game.last_pitch_information),
                pitchtype=self.pitchtype,
                speed_mph=self.speed_mph,
                snapshot=snapshot,
            )

    def _handle_ball_call(self):
        """Handle ball call."""
        self.game.balls += 1
        self.new_entry['ball'] = True
        if self.game.umpsound:
            if self.game.ball[1] > 560:  # Below strike zone (ZONE_BOTTOM)
                self.game.sound_manager.schedule_sound('ball_low', delay=450)
            else:
                self.game.sound_manager.schedule_sound('ball', delay=450)
        self.game.currentballs += 1
        self.game.pitchnumber += 1

        if self.game.currentballs == 4:
            self.outcome = 'walk'
            self.game.currentwalks += 1

            # Record walk to persistent stats
            self.game.field_renderer.record_walk()

            # Track score before walk for gameday mode
            score_before = self.game.scoreKeeper.get_score() if self.game.in_gameday_mode else 0
            self.game.scoreKeeper.update_walk_event()
            runs_scored = self.game.scoreKeeper.get_score() - score_before

            self.game._display_pitch_results("WALK", self.pitchtype, self.speed_mph)
            # Defer until the ABS challenge window closes so the banner can't
            # type itself in halfway underneath the challenge overlay. With
            # ABS turned off there's no window, so keep the original sync.
            abs_enabled = self.game.settings_manager.get_setting("abs_enabled")
            walk_delay = CHALLENGE_WINDOW_MS + 50 if abs_enabled else 450
            self.game.ui_manager.schedule_banner("WALK", delay=walk_delay)

            # Record in gameday mode
            if self.game.in_gameday_mode:
                self.game.gameday_manager.record_player_at_bat('WALK', runs_scored=runs_scored, pitches_thrown=self.game.pitchnumber)
                self._check_walkoff()

            self.game.currentstrikes = 0
            self.game.currentballs = 0
            self.game.pitchnumber = 0
        else:
            self.outcome = 'ball'
            self.game._display_pitch_results("BALL", self.pitchtype, self.speed_mph)

    def _handle_strike_call(self):
        """Handle strike call."""
        self.game.strikes += 1
        self.is_strike = True
        if collision(self.game.ball[0], self.game.ball[1], ABS_BALL_RADIUS, *ABS_ZONE):
            self.new_entry['in_zone'] = True
        self.game.pitchnumber += 1
        self.game.currentstrikes += 1

        # Play sounds
        if self.game.swing_started == 0 and self.game.currentstrikes == 3 and self.game.umpsound:
            self.game.sound_manager.schedule_sound('strike3', delay=450)
        elif self.game.swing_started == 0 and self.game.currentstrikes != 3 and self.game.umpsound:
            self.game.sound_manager.schedule_sound('strike', delay=450)

        if self.game.currentstrikes == 3:
            self.outcome = 'strikeout'
            self.game.currentstrikeouts += 1
            self.game.currentouts += 1

            # Record at-bat (strikeouts count as at-bats in baseball)
            self.game.field_renderer.record_at_bat()

            if self.game.swing_started == 0:
                self.new_entry['called_strike'] = True
                self.game._display_pitch_results("CALLED STRIKE", self.pitchtype, self.speed_mph)
            else:
                self.new_entry['swinging_strike'] = True
                self.game._display_pitch_results("SWINGING STRIKE", self.pitchtype, self.speed_mph)

            # Taken third strikes are challengeable — wait for the window to
            # close before showing the banner so it can't appear under the
            # ABS overlay. Swinging strikeouts aren't challengeable, and if
            # ABS is disabled in settings there's no window at all, so both
            # cases keep the original sync-with-umpire-call delay.
            is_taken = (self.game.swing_started == 0)
            abs_enabled = self.game.settings_manager.get_setting("abs_enabled")
            defer = is_taken and abs_enabled
            banner_delay = CHALLENGE_WINDOW_MS + 50 if defer else 450
            self.game.ui_manager.schedule_banner("STRIKEOUT", delay=banner_delay)

            # Record in gameday mode
            if self.game.in_gameday_mode:
                self.game.gameday_manager.record_player_at_bat('STRIKEOUT', runs_scored=0, pitches_thrown=self.game.pitchnumber)

            self.game.pitchnumber = 0
            self.game.currentstrikes = 0
            self.game.currentballs = 0
        else:
            self.outcome = 'strike'
            if self.game.swing_started == 0:
                self.new_entry['called_strike'] = True
                self.game._display_pitch_results("CALLED STRIKE", self.pitchtype, self.speed_mph)
            else:
                self.new_entry['swinging_strike'] = True
                self.game._display_pitch_results("SWINGING STRIKE", self.pitchtype, self.speed_mph)

    def _draw_batter(self, current_time):
        """Draw the batter in appropriate stance/swing."""
        if self.game.swing_started:
            swing_start_time = getattr(self, 'swing_starttime', current_time)
            if self.game.swing_started == 1:
                self.game.batter.swing_start(current_time, swing_start_time)
            else:
                self.game.batter.high_swing_start(current_time, swing_start_time)
        else:
            self.game.batter.leg_kick(current_time, self.starttime + self.windup - 300)

    def _update_ball_position(self, current_time=None):
        """Update ball position using 3D Statcast trajectory + perspective projection."""
        if current_time is None:
            current_time = pygame.time.get_ticks()

        # Time since ball was released (seconds)
        time_since_release = (current_time - self.starttime - self.windup) / 1000.0
        if time_since_release < 0:
            return

        # Clamp to travel time so ball doesn't fly past the plate
        t = min(time_since_release, self.trajectory.travel_time)

        # Get 3D world position from trajectory
        x, y, z = self.trajectory.position_at(t)

        # Project to screen
        proj = self.camera.project(x, y, z)
        if proj:
            screen_x, screen_y, depth = proj

            self.game.ball[0] = screen_x
            self.game.ball[1] = screen_y
            self.game.ball[2] = max(0, y)  # world-y in feet for ball renderer

        # Render the ball
        if self.game.ball[2] > 0.1:
            self.game.blitfunc(self.game.screen, self.game.ball)

    def _finish_pitch(self):
        """Finish the pitch and clean up."""
        self.running = False
        self.game.ui_manager.set_button_visibility('in_game')
        from strikefactor.ui.components import create_pci_cursor
        pygame.mouse.set_cursor(create_pci_cursor())
        self.cleanup()

        # Walk-off transition was deferred from _check_walkoff so the swing
        # animation and pitch recording could complete first.
        if getattr(self, '_pending_walkoff', False):
            self.game.menu_state = 'inning_end'
            self.game.state_manager.change_state('inning_end')

    def _start_hit_animation(self, outcome, banner_text, vertical_offset=0.0, quality=0.0):
        """Begin the post-contact animation; defers the outcome banner until it ends.

        For IN_PLAY (the unified ball-in-play outcome), the resolved
        classification isn't known until the animation fields the ball,
        so on_complete routes through _finalize_batted_ball which reads
        HitAnimation.classified_outcome and applies all deferred effects.
        HOME RUN is fully known up front so its callback just shows the
        banner.
        """
        from strikefactor.gameplay.hit_animation import HitAnimation
        if outcome == "IN_PLAY":
            on_complete = self._finalize_batted_ball
        else:
            def on_complete():
                self.game.ui_manager.show_banner(
                    self._format_display_outcome(banner_text)
                )

        # Append a labeled trail entry now — once hit_animation owns the frame,
        # _update_pitch_trajectory stops running, so the contact-point marker
        # the track-mode visualizer keys off (entry[4]) would otherwise never
        # be written and the ball would render grey. We don't know yet
        # whether this contact will resolve as a hit or out, so the marker
        # uses the generic "in-play" hit color; the visualizer treats both
        # the same.
        trail_color, trail_label = (71, 204, 252), "hit"
        self.game.last_pitch_information.append([
            self.game.ball[0], self.game.ball[1],
            self.game.fourseamballsize, trail_color, trail_label,
        ])

        self.hit_animation = HitAnimation(
            self.game,
            outcome=outcome,
            on_complete=on_complete,
            vertical_offset=vertical_offset,
            quality=quality,
            batted_ball_type=self.game.hit_outcome_manager.last_batted_ball_type,
            # Off the contact itself, like the foul path: `last_spray_deg` is
            # a snapshot of this same number, and one source cannot go stale.
            spray_deg=self.contact.spray_deg,
            defense=self._defense_profile(),
        )

    def _defense_profile(self):
        """The nine gloves behind this pitcher, resolved once per batted ball.

        This is the settings->physics seam for the defense setting, and it
        lives here rather than inside `HitAnimation` for the same reason
        `spray_deg` and `batted_ball_type` are passed in: the animation gets a
        resolved value, not a settings handle. `defense.profile_for` is total,
        so a hand-edited settings.json cannot raise on the path that decides a
        batted ball; the try/except covers a `game` with no settings manager
        at all, which is what every fielding test builds.

        Resolved per ball rather than cached, so changing the setting takes
        effect on the next ball in play and never mid-flight.
        """
        try:
            return defense.profile_for(
                self.game.settings_manager.get_defense_level())
        except Exception:
            return defense.NEUTRAL

    def _start_foul_animation(self):
        """Begin the cosmetic foul-ball animation; defers the FOUL result
        display until it ends.

        Deliberately does not go through _start_hit_animation: that path
        reads stale last_batted_ball_type / last_spray_deg from the previous
        hit (fouls never run the hit outcome pipeline) and writes a blue "hit"
        trail marker where track mode expects the foul's red strike entry.
        """
        from strikefactor.gameplay.hit_animation import HitAnimation

        quality = self._foul_quality
        vertical_offset = self._foul_vertical_offset
        # Off the contact itself rather than the manager's `last_*`, for the
        # reason in the docstring above: this path never ran the hit pipeline,
        # so those fields still describe the previous ball in play.
        spray_deg = self.contact.spray_deg

        def on_complete():
            self.game._display_pitch_results("FOUL", self.pitchtype, self.speed_mph)
            self.game.ui_manager.show_banner("FOUL BALL")

        # Replicate the trail entry the non-animated foul path writes via
        # _update_pitch_trajectory (pitch_results_done + is_strike -> red
        # "strike" marker) — the trajectory tracker stops running once the
        # animation owns the frame, so track mode would otherwise lose the
        # foul's contact-point marker.
        self.game.last_pitch_information.append([
            self.game.ball[0], self.game.ball[1],
            self.game.fourseamballsize, (227, 75, 80), "strike",
        ])

        self.hit_animation = HitAnimation(
            self.game,
            outcome="FOUL",
            on_complete=on_complete,
            vertical_offset=vertical_offset,
            quality=quality,
            batted_ball_type=None,
            spray_deg=spray_deg,
            defense=self._defense_profile(),
        )

    def _handle_hit_animation_phase(self, current_time, time_delta):
        """Render the hit animation; fire deferred banner; wait for player input.

        Events are drained every frame — pre-banner presses (e.g. a stale
        swing key from before contact resolved) are silently dropped. Once
        the banner has fired, the next key or click advances the play.
        """
        self.hit_animation.update(current_time)
        self.hit_animation.draw(self.game.screen)

        if self.hit_animation.finished and not self.hit_animation.banner_fired:
            self.hit_animation.on_complete()
            self.hit_animation.banner_fired = True

        self.game.ui_manager.update(time_delta)
        self.game.ui_manager.draw()
        self.game.flip_display()

        for event in pygame.event.get():
            if (self.hit_animation.banner_fired
                    and event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN)):
                self._finish_pitch()
                return

    def _calculate_velocity_mph(self) -> float:
        """Return the pitch speed in MPH (directly from input parameter)."""
        return self.speed_mph

    def _get_outcome_display(self) -> str:
        """Get display-friendly outcome string from internal outcome."""
        outcome = getattr(self, 'outcome', None)
        if outcome:
            outcome_map = {
                'strike': 'STRIKE',
                'ball': 'BALL',
                'foul': 'FOUL',
                'strikeout': 'STRIKEOUT',
                'walk': 'WALK',
                'SINGLE': 'SINGLE',
                'DOUBLE': 'DOUBLE',
                'TRIPLE': 'TRIPLE',
                'HOME RUN': 'HOME RUN',
                'FLYOUT': 'FLYOUT',
                'GROUNDOUT': 'GROUNDOUT',
                'LINEOUT': 'LINEOUT',
                'REACHED ON ERROR': 'REACHED ON ERROR',
            }
            return outcome_map.get(outcome, outcome.upper() if isinstance(outcome, str) else 'UNKNOWN')
        return 'UNKNOWN'

    def cleanup(self):
        """Clean up after pitch completion."""
        self.new_entry['FinalX'] = self.game.ball[0]
        self.new_entry['FinalY'] = self.game.ball[1]

        # Record that a pitch was thrown for statistics
        self.game.field_renderer.record_pitch()

        # Record heatmap data using final ball position
        final_x = self.game.ball[0]
        final_y = self.game.ball[1]

        # Record attempt if player swung
        if self.game.swing_started > 0:
            self.game.field_renderer.record_attempt(final_x, final_y)

        # Save data periodically (every 10 pitches) to prevent too frequent saves
        if self.game.field_renderer.total_pitches % 10 == 0:
            self.game.field_renderer.save_data()
            # Mirror BatterProfile to the pitch DB at the same cadence so
            # tendencies survive a hard quit (no menu transition).
            if hasattr(self.game, '_save_batter_profile_for_current_bucket'):
                self.game._save_batter_profile_for_current_bucket()

        # Update pitch trajectory colors
        if self.game.last_pitch_information:
            last_ball = self.game.last_pitch_information[-1]
            for pitch in self.game.last_pitch_information:
                if pitch[0] == last_ball[0] and pitch[1] == last_ball[1]:
                    pitch[3] = last_ball[3]

        # Update data and AI
        self.game.last_pitch_type_thrown = self.pitchtype

        # Record batter tendency data
        did_swing = self.game.swing_started > 0
        is_first_pitch = (self.game.pitchnumber <= 1 and
                          self.previous_state[1] == 0 and self.previous_state[2] == 0)
        count_state = self.game.current_pitcher._get_count_state()
        self.game.batter_profile.record_pitch(
            ball_x=self.game.ball[0],
            ball_y=self.game.ball[1],
            pitch_type=self.pitchtype,
            did_swing=did_swing,
            count_state=count_state,
            is_first_pitch=is_first_pitch,
            handedness=self.game.batter.get_handedness(),
        )

        # Track pitch history for sequencing
        self.game.pitch_history.append(self.pitchtype)
        # Keep only last 5 pitches
        if len(self.game.pitch_history) > 5:
            self.game.pitch_history = self.game.pitch_history[-5:]

        # Build new state with richer representation
        from strikefactor.ai.AI_2 import build_state
        new_state = build_state(
            outs=self.game.currentouts,
            strikes=self.game.currentstrikes,
            balls=self.game.currentballs,
            runners=self.game.scoreKeeper.get_runners_on_base(),
            pitch_number_in_ab=self.game.pitchnumber,
            prev_pitch=self.game.last_pitch_type_thrown,
            handedness=self.game.batter.get_handedness(),
            score_diff=self.game.scoreKeeper.get_score(),
        )
        self.game.current_pitcher.get_ai().update(self.previous_state, self.game.pitch_chosen,
                                                 new_state, self.game.outcome_value.get(self.outcome, 0))
        self.game.current_state = new_state
        self.game.pitch_trajectories.append(self.game.last_pitch_information)
        self.game.pitches_display.append((self.game.ball[0], self.game.ball[1]))
        self.game.current_pitches += 1

        # Create enhanced pitch record for visualization
        if hasattr(self.game, 'enhanced_pitch_records'):
            enhanced_record = EnhancedPitchRecord(
                trajectory=self.game.last_pitch_information.copy(),
                pitch_type=self.pitchtype,
                velocity_mph=self._calculate_velocity_mph(),
                outcome=self._get_outcome_display(),
                final_location=(self.game.ball[0], self.game.ball[1]),
                index=len(self.game.enhanced_pitch_records),
                selected=False
            )
            self.game.enhanced_pitch_records.append(enhanced_record)

        # Compute runs scored on THIS pitch from the inning scoreKeeper delta.
        # SummaryState.enter() resets scoreKeeper at inning end, but cleanup()
        # runs before that, so the delta is meaningful here.
        self.runs_scored_on_pitch = max(
            0, self.game.scoreKeeper.get_score() - self._score_before_pitch
        )

        # Pull any ABS challenge verdict that fired during this pitch.
        self.abs_challenged = bool(getattr(self.game, '_last_pitch_abs_challenged', False))
        self.abs_overturned = bool(getattr(self.game, '_last_pitch_abs_overturned', False))

        # Park the swing where the replay overlay can find it. Built here
        # because _finalize_batted_ball has already mirrored the animation by
        # now, so every field is settled. A taken pitch returns None and
        # deliberately leaves the previous swing in place.
        from strikefactor.gameplay import swing_record
        record = swing_record.from_simulation(self)
        if record is not None:
            self.game.last_swing = record

        # Record pitch to SQLite database
        from strikefactor.data.pitch_database import PitchDatabaseService
        PitchDatabaseService.get_instance().record_pitch(self)
