import random
import math
from utils.physics import collision_angled

class HitOutcomeManager:
    def __init__(self, score_keeper, sound_manager, settings_manager=None):
        self.score_keeper = score_keeper
        self.sound_manager = sound_manager
        self.settings_manager = settings_manager
        self.hit_type = 0
        self.ishomerun = ''

        # Right-handed batter's hand position
        # These positions are used to determine the contact zone for the bat
        self.rhpos = (490, 453)
        self.rhpos_high = (497, 405)

    def get_contact_hit_outcome(self, swing_location_y=None, ball_location_y=None, timing_diff=None):
        # Determine if swing was above/below ball based on swing location
        location_factor = self._calculate_location_factor(swing_location_y, ball_location_y)
        timing_factor = self._calculate_timing_factor(timing_diff)

        # Get difficulty multipliers
        multipliers = self._get_difficulty_multipliers()

        # Base random value
        rand = random.uniform(0, 10)

        # Apply difficulty multipliers to out probabilities
        out_modifier = multipliers["out_probability_modifier"]
        foul_chance = multipliers["foul_ball_chance"]

        # Adjust probabilities based on swing mechanics
        if location_factor == "high_swing":  # Swing above ball - more likely flyout
            flyout_threshold = 4 * out_modifier
            if rand <= flyout_threshold:
                return "FLYOUT"
            elif rand <= 6.5:
                self.hit_type = 1
                hit_result = "SINGLE"
            elif rand <= 8.5:
                self.hit_type = 2
                hit_result = "DOUBLE"
            elif rand <= 9.2:
                self.hit_type = 3
                hit_result = "TRIPLE"
            else:
                self.hit_type = 4
                hit_result = "HOME RUN"
        elif location_factor == "low_swing":  # Swing below ball - more likely groundout
            groundout_threshold = 5 * out_modifier
            if rand <= groundout_threshold:
                return "GROUNDOUT"
            elif rand <= 7.5:
                self.hit_type = 1
                hit_result = "SINGLE"
            elif rand <= 9:
                self.hit_type = 2
                hit_result = "DOUBLE"
            elif rand <= 9.5:
                self.hit_type = 3
                hit_result = "TRIPLE"
            else:
                self.hit_type = 4
                hit_result = "HOME RUN"
        else:  # Good contact - original distribution but with some outs
            out_threshold = 3 * out_modifier
            if timing_factor == "way_off" and rand <= out_threshold:
                return "FLYOUT" if rand <= (out_threshold / 2) else "GROUNDOUT"
            elif rand <= 7:
                self.hit_type = 1
                hit_result = "SINGLE"
            elif rand <= 8.5:
                self.hit_type = 2
                hit_result = "DOUBLE"
            elif rand <= 9.2:
                self.hit_type = 3
                hit_result = "TRIPLE"
            else:
                self.hit_type = 4
                hit_result = "HOME RUN"

        # Only update runners if it's a hit (not an out)
        if hit_result not in ["FLYOUT", "GROUNDOUT"]:
            self.update_runners_and_score()

        return hit_result
    
    def get_power_hit_outcome(self, swing_location_y=None, ball_location_y=None, timing_diff=None):
        # Determine if swing was above/below ball based on swing location
        location_factor = self._calculate_location_factor(swing_location_y, ball_location_y)
        timing_factor = self._calculate_timing_factor(timing_diff)

        # Get difficulty multipliers
        multipliers = self._get_difficulty_multipliers()

        # Base random value
        rand = random.uniform(0, 10)

        # Apply difficulty multipliers to out probabilities
        out_modifier = multipliers["out_probability_modifier"]

        # Power swings have different characteristics
        if location_factor == "high_swing":  # Power swing above ball - more flyouts but stronger hits
            flyout_threshold = 3.5 * out_modifier
            if rand <= flyout_threshold:
                return "FLYOUT"
            elif rand <= 5:
                self.hit_type = 1
                hit_result = "SINGLE"
            elif rand <= 7:
                self.hit_type = 2
                hit_result = "DOUBLE"
            elif rand <= 8:
                self.hit_type = 3
                hit_result = "TRIPLE"
            else:
                self.hit_type = 4
                hit_result = "HOME RUN"
        elif location_factor == "low_swing":  # Power swing below ball - fewer groundouts, more pop-ups
            groundout_threshold = 4 * out_modifier
            if rand <= groundout_threshold:
                return "GROUNDOUT"
            elif rand <= 5.5:
                self.hit_type = 1
                hit_result = "SINGLE"
            elif rand <= 7.5:
                self.hit_type = 2
                hit_result = "DOUBLE"
            elif rand <= 8.5:
                self.hit_type = 3
                hit_result = "TRIPLE"
            else:
                self.hit_type = 4
                hit_result = "HOME RUN"
        else:  # Good contact with power swing - more extra base hits
            out_threshold = 2.5 * out_modifier
            if timing_factor == "way_off" and rand <= out_threshold:
                return "FLYOUT" if rand <= (out_threshold / 2) else "GROUNDOUT"
            elif rand <= 2.5:
                self.hit_type = 1
                hit_result = "SINGLE"
            elif rand <= 5.5:
                self.hit_type = 2
                hit_result = "DOUBLE"
            elif rand <= 7:
                self.hit_type = 3
                hit_result = "TRIPLE"
            else:
                self.hit_type = 4
                hit_result = "HOME RUN"

        # Only update runners if it's a hit (not an out)
        if hit_result not in ["FLYOUT", "GROUNDOUT"]:
            self.update_runners_and_score()

        return hit_result
    
    def power_timing_quality(self, swing_starttime, starttime, traveltime, windup_time):
        diff = abs((swing_starttime + 150) - (starttime + windup_time + traveltime))

        # Get difficulty multipliers
        multipliers = self._get_difficulty_multipliers()
        power_window = multipliers["power_timing_window"]

        # Adjust timing windows based on difficulty
        perfect_window = 20 * power_window
        foul_window = 35 * power_window

        if perfect_window < diff < foul_window:
            return 1  # Foul timing
        elif diff <= perfect_window:
            return 2  # Perfect timing
        else:
            return 0  # Miss

    def contact_timing_quality(self, swing_starttime, starttime, traveltime, windup_time):
        diff = abs((swing_starttime + 150) - (starttime + windup_time + traveltime))

        # Get difficulty multipliers
        multipliers = self._get_difficulty_multipliers()
        contact_window = multipliers["contact_timing_window"]

        # Adjust timing windows based on difficulty
        perfect_window = 30 * contact_window
        foul_window = 60 * contact_window

        if perfect_window < diff < foul_window:
            return 1  # Foul timing
        elif diff <= perfect_window:
            return 2  # Contact timing
        else:
            return 0  # Miss
    
    def _calculate_location_factor(self, swing_y, ball_y):
        """Determine swing location relative to ball."""
        if swing_y is None or ball_y is None:
            return "good_contact"
            
        y_diff = swing_y - ball_y
        
        # Thresholds for determining swing location (adjust based on your coordinate system)
        if y_diff < -20:  # Swing significantly above ball
            return "high_swing"
        elif y_diff > 20:  # Swing significantly below ball
            return "low_swing"
        else:
            return "good_contact"
    
    def _calculate_timing_factor(self, timing_diff):
        """Determine timing quality."""
        if timing_diff is None:
            return "good_timing"
            
        abs_diff = abs(timing_diff)
        
        if abs_diff > 60:  # Very late or very early
            return "way_off"
        elif abs_diff > 30:  # Somewhat off
            return "slightly_off"
        else:
            return "good_timing"
        
    # Check for contact based on mouse cursor position when self.ball impacts bat
    def get_ball_to_bat_contact_outcome(self, batpos, ballpos, swing_type, ballsize=11, batter_handedness='R'):
        x = 1 if batter_handedness == "R" else -1
        angle = math.atan2(batpos[1] - self.rhpos[1], batpos[0] - self.rhpos[0])

        # Get difficulty multipliers
        multipliers = self._get_difficulty_multipliers()
        contact_zone_modifier = multipliers["contact_zone_size"]

        # Adjust contact zone based on difficulty
        base_contact_zone_height = 50 if swing_type == 1 else 25
        contact_zone_height = base_contact_zone_height * contact_zone_modifier
        base_contact_zone_width = 120
        contact_zone_width = base_contact_zone_width * contact_zone_modifier

        if collision_angled(ballpos[0], ballpos[1], ballsize, (batpos[0] - (30 * x)), batpos[1], contact_zone_width, contact_zone_height, angle):
            outcome = "hit"
        else:
            outcome = "miss"
        return outcome

    def update_runners_and_score(self):
        self.ishomerun = ''
        scored = self.score_keeper.update_hit_event(self.hit_type)[1]
        
        if self.hit_type == 4:
            if scored == 1:
                self.ishomerun = 'SOLO HOME RUN'
            elif scored == 2:
                self.ishomerun = 'TWO-RUN HOME RUN'
            elif scored == 3:
                self.ishomerun = 'THREE-RUN HOME RUN'
            else:
                self.ishomerun = 'GRAND SLAM'
    
    def handle_out_event(self, out_type):
        """Handle flyout or groundout events."""
        # Add an out to the game
        # This will be called from the pitch simulation when an out occurs
        return out_type
    
    def play_hit_sound(self, outcome=None):
        if outcome == "FLYOUT":
            # Flyouts play random batting sounds: foul, double, or homerun
            flyout_sounds = ['foul', 'double', 'homerun']
            sound_choice = random.choice(flyout_sounds)
            self.sound_manager.play(sound_choice)
        elif outcome == "GROUNDOUT":
            # Groundouts play either foul or single sounds
            groundout_sounds = ['foul', 'single']
            sound_choice = random.choice(groundout_sounds)
            self.sound_manager.play(sound_choice)
        elif self.hit_type == 1:
            self.sound_manager.play('single')
        elif self.hit_type == 2:
            self.sound_manager.play('double')
        elif self.hit_type == 3:
            self.sound_manager.play('triple')
        elif self.hit_type == 4:
            self.sound_manager.play('homerun')
    
    def get_homerun_text(self):
        return self.ishomerun

    def _get_difficulty_multipliers(self):
        """Get difficulty multipliers from settings manager, or default values."""
        if self.settings_manager:
            return self.settings_manager.get_difficulty_multipliers()
        else:
            # Default multipliers (Amateur difficulty)
            return {
                "contact_timing_window": 1.0,
                "power_timing_window": 1.0,
                "contact_zone_size": 1.0,
                "out_probability_modifier": 1.0,
                "strike_zone_tolerance": 1.0,
                "foul_ball_chance": 1.0
            }