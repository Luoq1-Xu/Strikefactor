from typing import TYPE_CHECKING

import pygame
import pygame.gfxdraw
import pandas as pd
from utils.physics import collision
from helpers import EnhancedPitchRecord
from utils.pitch_physics import PitchTrajectory, UmpireCamera, DEFAULT_CAMERA

if TYPE_CHECKING:
    from main import Game

# Load the model once, ideally passed in or as a singleton
import pickle
from config import get_path, ABS_ZONE, ABS_BALL_RADIUS, CHALLENGE_WINDOW_MS
model = pickle.load(open(get_path("ai/ai_umpire.pkl"), "rb"))

class PitchSimulation:
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

        # Mistake pitch: drift target toward center zone
        import random as _rng
        if mistake_chance > 0 and _rng.random() < mistake_chance:
            # Center zone in feet: roughly x=0, z=2.8 (mid-zone height)
            self.target_x_ft = self.target_x_ft * 0.3  # Pull 70% toward center
            self.target_z_ft = self.target_z_ft * 0.3 + 2.8 * 0.7
            effective_pfx_x *= 0.5  # Reduced break on mistake pitches
            effective_pfx_z *= 0.5

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
            if current_time > self.starttime + self.traveltime + self.windup and hasattr(self, 'outcome') and self.outcome in ['FLYOUT', 'GROUNDOUT']:
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
        mousepos = self.game.get_mouse_pos()
        self.swing_starttime = pygame.time.get_ticks()
        self.contact_time = self.swing_starttime + 150

        if event.key == pygame.K_w and self.game.swing_started == 0:
            # Contact swing
            self.swing_type = 1
            self.on_time = self.game.hit_outcome_manager.contact_timing_quality(
                self.swing_starttime, self.starttime, self.traveltime, self.windup
            )
            self.game.swing_started = 1 if mousepos[1] > 500 else 2
        elif event.key == pygame.K_e and self.game.swing_started == 0:
            # Power swing
            self.swing_type = 2
            self.on_time = self.game.hit_outcome_manager.power_timing_quality(
                self.swing_starttime, self.starttime, self.traveltime, self.windup
            )
            self.game.swing_started = 1 if mousepos[1] > 500 else 2

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

        # Play contact sounds
        if (current_time > self.contact_time and self.soundplayed == 0 and self.pitch_results_done):
            if self.on_time == 1:
                self.game.sound_manager.play('foul')
                self.soundplayed += 1
            elif self.on_time == 2:
                # Pass the outcome to determine appropriate sound
                outcome = getattr(self, 'outcome', None)
                self.game.hit_outcome_manager.play_hit_sound(outcome)
                self.soundplayed += 1

    def _evaluate_contact(self):
        """Evaluate the contact outcome based on timing."""
        mousepos = self.game.get_mouse_pos()

        if self.on_time == 1:  # Foul ball timing
            outcome = self.game.hit_outcome_manager.get_ball_to_bat_contact_outcome(
                mousepos, (self.game.ball[0], self.game.ball[1]), self.swing_type,
                batter_handedness=self.game.batter.get_handedness()
            )
            if outcome == 'miss':
                self.made_contact = "swung_and_miss"
            else:
                self._handle_foul_ball()
        elif self.on_time == 2:  # Perfect timing
            outcome = self.game.hit_outcome_manager.get_ball_to_bat_contact_outcome(
                mousepos, (self.game.ball[0], self.game.ball[1]), self.swing_type,
                batter_handedness=self.game.batter.get_handedness()
            )
            if outcome == 'miss':
                self.made_contact = "swung_and_miss"
            else:
                self._handle_successful_hit()

    def _handle_foul_ball(self):
        """Handle foul ball outcome."""
        self.outcome = 'foul'
        self.game.strikes += 1
        self.is_strike = True
        self.new_entry['foul'] = True
        self.made_contact = "fouled"
        self.pitch_results_done = True
        self.game.pitchnumber += 1
        if self.game.currentstrikes < 2:
            self.game.currentstrikes += 1
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

        # Get swing and ball positions for more realistic outcomes
        mousepos = self.game.get_mouse_pos()
        swing_y = mousepos[1]
        ball_y = self.game.ball[1]

        # Calculate timing difference for more realistic outcomes
        timing_diff = abs((self.swing_starttime + 150) - (self.starttime + self.windup + self.traveltime))

        if self.swing_type == 1:
            hit_string = self.game.hit_outcome_manager.get_contact_hit_outcome(
                swing_location_y=swing_y, ball_location_y=ball_y, timing_diff=timing_diff
            )
        elif self.swing_type == 2:
            hit_string = self.game.hit_outcome_manager.get_power_hit_outcome(
                swing_location_y=swing_y, ball_location_y=ball_y, timing_diff=timing_diff
            )

        # DEBUG: Log hit_string from hit_outcome_manager
        print(f">>> _handle_successful_hit: hit_string='{hit_string}', swing_type={self.swing_type}", flush=True)

        # Snapshot contact metrics for the hit animation (shape + HR distance).
        contact_quality = self.game.hit_outcome_manager.last_quality
        contact_vertical_offset = self.game.hit_outcome_manager.last_vertical_offset

        # Handle different outcomes
        if hit_string in ["FLYOUT", "GROUNDOUT"]:
            self._handle_out_result(hit_string, contact_vertical_offset, contact_quality)
        else:
            self._handle_hit_result(hit_string, score_before, contact_vertical_offset, contact_quality)

    def _handle_out_result(self, out_type, vertical_offset=0.0, quality=0.0):
        """Handle flyout or groundout results."""
        self.is_hit = False  # This is an out, not a hit
        self.game.currentouts += 1
        self.outcome = out_type

        # Record at-bat (outs count as at-bats in baseball)
        self.game.field_renderer.record_at_bat()

        # Banner is deferred — fires once the hit animation finishes.
        self._start_hit_animation(out_type, out_type, vertical_offset, quality)
        self.game._display_pitch_results(out_type, self.pitchtype, self.speed_mph)
        self.new_entry['isHit'] = out_type

        # Record in gameday mode
        if self.game.in_gameday_mode:
            self.game.gameday_manager.record_player_at_bat(out_type, runs_scored=0, pitches_thrown=self.game.pitchnumber)

        # Reset counts after out (similar to strikeout)
        self.game.pitchnumber = 0
        self.game.currentstrikes = 0
        self.game.currentballs = 0

    def _handle_hit_result(self, hit_string, score_before=0, vertical_offset=0.0, quality=0.0):
        """Handle successful hit results."""
        self.is_hit = True
        self.game.hits += 1

        # DEBUG: Log the hit_string being passed
        print(f">>> _handle_hit_result called with hit_string='{hit_string}'", flush=True)
        homerun_text = self.game.hit_outcome_manager.get_homerun_text()
        print(f">>> homerun_text='{homerun_text}', hit_type={self.game.hit_outcome_manager.hit_type}", flush=True)

        # Record at-bat (hits count as at-bats in baseball)
        self.game.field_renderer.record_at_bat()

        # Record hit with type information
        self.game.field_renderer.record_hit(
            self.game.ball[0],
            self.game.ball[1],
            hit_type=hit_string  # Pass hit outcome string for triple slash tracking
        )

        if homerun_text != '':
            self.game.homeruns_allowed += 1
        banner_text = homerun_text if homerun_text != '' else hit_string
        # Banner is deferred — fires once the hit animation finishes.
        self._start_hit_animation(hit_string, banner_text, vertical_offset, quality)

        self.game._display_pitch_results(f"HIT - {hit_string}", self.pitchtype, self.speed_mph)
        self.new_entry['isHit'] = hit_string
        self.outcome = hit_string

        # Record in gameday mode (score has already been updated by hit_outcome_manager)
        if self.game.in_gameday_mode:
            runs_scored = self.game.scoreKeeper.get_score() - score_before
            self.game.gameday_manager.record_player_at_bat(hit_string, runs_scored=runs_scored, pitches_thrown=self.game.pitchnumber)
            self._check_walkoff()

        # Reset counts after hit
        self.game.pitchnumber = 0
        self.game.currentstrikes = 0
        self.game.currentballs = 0

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
            # player_score / _current_half_runs are already up-to-date via
            # record_player_at_bat. Just commit the partial inning to the box
            # score before transitioning.
            self.game.gameday_manager.player_inning_scores.append(
                self.game.gameday_manager._current_half_runs
            )

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
            not model.predict(pd.DataFrame([[self.game.ball[0], self.game.ball[1]]],
                                           columns=['finalx', 'finaly']))
            and is_taken
        )
        truth_strike = collision(
            self.game.ball[0], self.game.ball[1], ABS_BALL_RADIUS, *ABS_ZONE
        )
        original_call = "ball" if umpire_says_ball else "strike"

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
        if collision(self.game.ball[0], self.game.ball[1], 11, 630, 482.5, 130, 150):
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
        from ui.components import create_pci_cursor
        pygame.mouse.set_cursor(create_pci_cursor())
        self.cleanup()

        # Walk-off transition was deferred from _check_walkoff so the swing
        # animation and pitch recording could complete first.
        if getattr(self, '_pending_walkoff', False):
            self.game.menu_state = 'inning_end'
            self.game.state_manager.change_state('inning_end')

    def _start_hit_animation(self, outcome, banner_text, vertical_offset=0.0, quality=0.0):
        """Begin the post-contact animation; defers the outcome banner until it ends."""
        from gameplay.hit_animation import HitAnimation
        self.hit_animation = HitAnimation(
            self.game,
            outcome=outcome,
            on_complete=lambda: self.game.ui_manager.show_banner(banner_text),
            vertical_offset=vertical_offset,
            quality=quality,
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
        from ai.AI_2 import build_state
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
                                                 new_state, self.game.outcome_value[self.outcome])
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

        # Record pitch to SQLite database
        from data.pitch_database import PitchDatabaseService
        PitchDatabaseService.get_instance().record_pitch(self)
