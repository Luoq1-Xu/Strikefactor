import random
import math
from utils.physics import collision_angled

class HitOutcomeManager:
    def __init__(self, score_keeper, sound_manager):
        self.score_keeper = score_keeper
        self.sound_manager = sound_manager
        self.hit_type = 0
        self.ishomerun = ''

        # Right-handed batter's hand position
        # These positions are used to determine the contact zone for the bat
        self.rhpos = (490, 453)
        self.rhpos_high = (497, 405)

    def get_contact_hit_outcome(self):
        rand = random.uniform(0, 10)
        if rand <= 8:
            self.hit_type = 1
            hit_result = "SINGLE"
        elif rand <= 9.5:
            self.hit_type = 2
            hit_result = "DOUBLE"
        elif rand <= 9.8:
            self.hit_type = 3
            hit_result = "TRIPLE"
        else:
            self.hit_type = 4
            hit_result = "HOME RUN"
            
        self.update_runners_and_score()
        return hit_result
    
    def get_power_hit_outcome(self):
        rand = random.uniform(0, 10)
        if rand <= 3:
            self.hit_type = 1
            hit_result = "SINGLE"
        elif rand <= 6.5:
            self.hit_type = 2
            hit_result = "DOUBLE"
        elif rand <= 7.5:
            self.hit_type = 3
            hit_result = "TRIPLE"
        else:
            self.hit_type = 4
            hit_result = "HOME RUN"
            
        self.update_runners_and_score()
        return hit_result
    
    def power_timing_quality(self, swing_starttime, starttime, traveltime, windup_time):
        diff = abs((swing_starttime + 150) - (starttime + windup_time + traveltime))
        if 20 < diff < 35:
            return 1
        elif diff <= 20:
            return 2
        else:
            return 0
        
    def contact_timing_quality(self, swing_starttime, starttime, traveltime, windup_time):
        diff = abs((swing_starttime + 150) - (starttime + windup_time + traveltime))
        if 30 < diff < 60:
            return 1 # Foul
        elif diff <= 30:
            return 2 # Contact
        else:
            return 0
        
    # Check for contact based on mouse cursor position when self.ball impacts bat
    def get_ball_to_bat_contact_outcome(self, batpos, ballpos, swing_type, ballsize=11, batter_handedness='R'):
        x = 1 if batter_handedness == "R" else -1
        angle = math.atan2(batpos[1] - self.rhpos[1], batpos[0] - self.rhpos[0])
        contact_zone_height = 50 if swing_type == 1 else 25
        if collision_angled(ballpos[0], ballpos[1], ballsize, (batpos[0] - (30 * x)), batpos[1], 120, contact_zone_height, angle):
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
    
    def play_hit_sound(self):
        if self.hit_type == 1:
            self.sound_manager.play('single')
        elif self.hit_type == 2:
            self.sound_manager.play('double')
        elif self.hit_type == 3:
            self.sound_manager.play('triple')
        elif self.hit_type == 4:
            self.sound_manager.play('homerun')
    
    def get_homerun_text(self):
        return self.ishomerun