import pygame
import pygame.gfxdraw
import pandas as pd
from utils.physics import collision
from main_refactored import Game

# Load the model once, ideally passed in or as a singleton
import pickle
from config import get_path
model = pickle.load(open(get_path("ai/ai_umpire.pkl"), "rb"))

class PitchSimulation:
    def __init__(self, game, release_point, pitchername, ax, ay, vx, vy, traveltime, pitchtype):
        self.game: Game = game
        self.release_point = release_point
        self.pitchername = pitchername
        self.ax = ax
        self.ay = ay
        self.vx = vx
        self.vy = vy
        self.traveltime = traveltime
        self.pitchtype = pitchtype

        # Initialize state from the original main_simulation method
        self.running = True
        self.game.first_pitch_thrown = True
        self.game.swing_started = 0
        self.game.ball = [self.release_point[0], self.release_point[1], 4600]
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

    def run(self):
        self.game.ui_manager.hide_banner()
        self.game.ui_manager.set_button_visibility('pitching')

        while self.running:
            self.update()

    def update(self):
        """Main simulation update loop."""
        self.game.sound_manager.update()
        self.game.screen.fill("black")
        time_delta = self.game.clock.tick_busy_loop(60)/1000.0
        self.game.ui_manager.draw()
        self.game.ui_manager.update(time_delta)
        
        current_time = pygame.time.get_ticks()
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
                dist = self.game.ball[2]/300
                entry = [self.game.ball[0], self.game.ball[1], min(max(11/dist, 4), 11), (255,255,255), ""]
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
            
    def _handle_windup_phase(self, current_time):
        """Handle pitcher windup phase."""
        self.game.batter.leg_kick(current_time, self.starttime + self.windup - 300)
        self.game.field_renderer.draw_strikezone()
        self.game.field_renderer.draw_field(self.game.scoreKeeper.get_bases())
        pygame.display.flip()
        
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
        self._update_ball_position()
        self.game.field_renderer.draw_strikezone()
        self.game.field_renderer.draw_field(self.game.scoreKeeper.get_bases())
        pygame.display.flip()
        
        # Ball reaching glove sound
        if ((current_time > (self.arrival_time - 30) and self.soundplayed == 0 and self.on_time == 0) or 
            (current_time > self.contact_time and self.soundplayed == 0 and 
             (self.on_time > 0 and self.made_contact == "swung_and_miss"))):
            self.game.sound_manager.glovepop()
            self.soundplayed += 1
            
    def _handle_swing_input(self, event, current_time):
        """Handle swing input from player."""
        mousepos = pygame.mouse.get_pos()
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
        pygame.display.flip()
        
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
        mousepos = pygame.mouse.get_pos()
        
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
        self.game._display_pitch_results("FOUL", self.pitchtype)
        
    def _handle_successful_hit(self):
        """Handle successful hit outcome."""
        self.game.strikes += 1
        self.made_contact = "hit"
        self.pitch_results_done = True
        self.game.pitchnumber += 1
        
        # Get swing and ball positions for more realistic outcomes
        mousepos = pygame.mouse.get_pos()
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
        
        # Handle different outcomes
        if hit_string in ["FLYOUT", "GROUNDOUT"]:
            self._handle_out_result(hit_string)
        else:
            self._handle_hit_result(hit_string)
    
    def _handle_out_result(self, out_type):
        """Handle flyout or groundout results."""
        self.is_hit = False  # This is an out, not a hit
        self.game.currentouts += 1
        self.outcome = out_type
        
        # Display the out result
        self.game.ui_manager.show_banner(out_type)
        self.game._display_pitch_results(out_type, self.pitchtype)
        self.new_entry['isHit'] = out_type
        
        # Reset counts after out (similar to strikeout)
        self.game.pitchnumber = 0
        self.game.currentstrikes = 0
        self.game.currentballs = 0
    
    def _handle_hit_result(self, hit_string):
        """Handle successful hit results."""
        self.is_hit = True
        self.game.hits += 1
        
        if self.game.hit_outcome_manager.get_homerun_text() != '':
            self.game.ui_manager.show_banner("{}".format(self.game.hit_outcome_manager.get_homerun_text()))
            self.game.homeruns_allowed += 1
        else:
            self.game.ui_manager.show_banner("{}".format(hit_string))
            
        self.game._display_pitch_results(f"HIT - {hit_string}", self.pitchtype)
        self.new_entry['isHit'] = hit_string
        self.outcome = hit_string
        
        # Reset counts after hit
        self.game.pitchnumber = 0
        self.game.currentstrikes = 0
        self.game.currentballs = 0
        
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
        pygame.display.flip()
        
        if not self.pitch_results_done:
            self._make_ball_strike_call()
            
    def _make_ball_strike_call(self):
        """Make the umpire's ball/strike call."""
        self.pitch_results_done = True
        
        # Check if it's a ball (outside zone and not swung at)
        if not model.predict(pd.DataFrame([[self.game.ball[0], self.game.ball[1]]], 
                                         columns=['finalx', 'finaly'])) and self.game.swing_started == 0:
            self._handle_ball_call()
        else:
            self._handle_strike_call()
            
    def _handle_ball_call(self):
        """Handle ball call."""
        self.game.balls += 1
        self.new_entry['ball'] = True
        if self.game.umpsound:
            self.game.sound_manager.schedule_sound('ball', delay=200)
        self.game.currentballs += 1
        self.game.pitchnumber += 1
        
        if self.game.currentballs == 4:
            self.outcome = 'walk'
            self.game.currentwalks += 1
            self.game.scoreKeeper.update_walk_event()
            self.game._display_pitch_results("WALK", self.pitchtype)
            self.game.ui_manager.show_banner("WALK")
            self.game.currentstrikes = 0
            self.game.currentballs = 0
            self.game.pitchnumber = 0
        else:
            self.outcome = 'ball'
            self.game._display_pitch_results("BALL", self.pitchtype)
            
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
            self.game.sound_manager.schedule_sound('strike3', delay=200)
        elif self.game.swing_started == 0 and self.game.currentstrikes != 3 and self.game.umpsound:
            self.game.sound_manager.schedule_sound('strike', delay=200)
            
        if self.game.currentstrikes == 3:
            self.outcome = 'strikeout'
            self.game.currentstrikeouts += 1
            self.game.currentouts += 1
            
            if self.game.swing_started == 0:
                self.new_entry['called_strike'] = True
                self.game._display_pitch_results("CALLED STRIKE", self.pitchtype)
            else:
                self.new_entry['swinging_strike'] = True
                self.game._display_pitch_results("SWINGING STRIKE", self.pitchtype)
                
            self.game.ui_manager.show_banner("STRIKEOUT")
            self.game.pitchnumber = 0
            self.game.currentstrikes = 0
            self.game.currentballs = 0
        else:
            self.outcome = 'strike'
            if self.game.swing_started == 0:
                self.new_entry['called_strike'] = True
                self.game._display_pitch_results("CALLED STRIKE", self.pitchtype)
            else:
                self.new_entry['swinging_strike'] = True
                self.game._display_pitch_results("SWINGING STRIKE", self.pitchtype)
                
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
            
    def _update_ball_position(self):
        """Update ball position and physics."""
        dist = self.game.ball[2]/300
        if dist > 1:
            self.game.blitfunc(self.game.screen, self.game.ball)
            self.game.ball[1] += self.vy * (1/dist)
            self.game.ball[2] -= (4300 * 1000)/(60 * self.traveltime)
            self.game.ball[0] += self.vx * (1/dist)
            self.vy += (self.ay*300) * (1/dist)
            self.vx += (self.ax*300) * (1/dist)
            
    def _finish_pitch(self):
        """Finish the pitch and clean up."""
        self.running = False
        self.game.ui_manager.set_button_visibility('in_game')
        from ui.components import create_pci_cursor
        pygame.mouse.set_cursor(create_pci_cursor())
        self.cleanup()
        
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
            
        # Record hit if it was a successful hit
        if self.is_hit:
            self.game.field_renderer.record_hit(final_x, final_y)
            
        # Save data periodically (every 10 pitches) to prevent too frequent saves
        if self.game.field_renderer.total_pitches % 10 == 0:
            self.game.field_renderer.save_data()
        
        # Update records
        if self.game.records.empty:
            self.game.records = pd.DataFrame([self.new_entry])
        else:
            self.game.records = pd.concat([self.game.records, pd.DataFrame([self.new_entry])], ignore_index=True)
            
        # Update pitch trajectory colors
        if self.game.last_pitch_information:
            last_ball = self.game.last_pitch_information[-1]
            for pitch in self.game.last_pitch_information:
                if pitch[0] == last_ball[0] and pitch[1] == last_ball[1]:
                    pitch[3] = last_ball[3]
                    
        # Update data and AI
        self.game.last_pitch_type_thrown = self.pitchtype
        self.game.pitchDataManager.insert_row(self.new_data_entry)
        
        new_state = (self.game.currentouts, self.game.currentstrikes, self.game.currentballs,
                    self.game.scoreKeeper.get_runners_on_base(), self.game.hits, self.game.scoreKeeper.get_score())
        self.game.current_pitcher.get_ai().update(self.previous_state, self.game.pitch_chosen, 
                                                 new_state, self.game.outcome_value[self.outcome])
        self.game.current_state = new_state
        self.game.pitch_trajectories.append(self.game.last_pitch_information)
        self.game.pitches_display.append((self.game.ball[0], self.game.ball[1]))
        self.game.current_pitches += 1