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
        self.momentum_bonus = 0.0  # Set by gameday mode for hot streak

        # Last contact metrics — read by HitAnimation for trajectory + HR distance.
        self.last_quality = 0.0
        self.last_vertical_offset = 0.0

        # Right-handed batter's hand position
        # Used to determine the contact zone for the bat
        self.rhpos = (490, 453)

    def _compute_contact_quality(self, swing_location_y, ball_location_y, timing_diff):
        """Compute a continuous contact quality score from 0.0 (terrible) to 1.0 (perfect).

        Components:
          - timing_score: how close timing is to perfect (gaussian falloff)
          - alignment_score: how close bat-ball vertical alignment is (gaussian falloff)
          - combined via geometric mean so both matter
        """
        # --- Timing score (0.0 to 1.0) ---
        if timing_diff is None:
            timing_score = 0.7  # default decent
        else:
            # Gaussian falloff: perfect at 0ms, sigma ~35ms
            timing_score = math.exp(-0.5 * (timing_diff / 35.0) ** 2)

        # --- Vertical alignment score (0.0 to 1.0) ---
        if swing_location_y is None or ball_location_y is None:
            alignment_score = 0.7
            vertical_offset = 0.0
        else:
            vertical_offset = swing_location_y - ball_location_y  # positive = bat below ball
            # Gaussian falloff: perfect at 0px, sigma ~25px
            alignment_score = math.exp(-0.5 * (vertical_offset / 25.0) ** 2)

        # Combined quality via geometric mean
        quality = math.sqrt(timing_score * alignment_score)

        return quality, vertical_offset

    def get_contact_hit_outcome(self, swing_location_y=None, ball_location_y=None, timing_diff=None):
        """Coarse outcome at contact. Returns one of:
            "FLYOUT", "GROUNDOUT" — out paths, unchanged.
            "HOME RUN"            — predetermined; runners advance now.
            "HIT"                 — generic non-HR hit; the HitAnimation will
                                    classify SINGLE/DOUBLE/TRIPLE by retrieve
                                    time and pitch_simulation will then call
                                    apply_classified_outcome() to advance the
                                    runners.
        """
        quality, vertical_offset = self._compute_contact_quality(
            swing_location_y, ball_location_y, timing_diff
        )
        self.last_quality = quality
        self.last_vertical_offset = vertical_offset

        multipliers = self._get_difficulty_multipliers()
        out_modifier = multipliers["out_probability_modifier"]
        rand = random.uniform(0, 10)

        # Out probability scales inversely with quality: high quality = fewer outs
        # Range: quality=1.0 -> out_chance ~1.0, quality=0.0 -> out_chance ~6.0
        # Momentum bonus reduces out chance (max ~12% reduction)
        out_chance = (1.0 + 5.0 * (1.0 - quality)) * out_modifier * (1.0 - self.momentum_bonus)

        # Determine out type based on vertical offset
        if rand <= out_chance:
            if vertical_offset < -10:  # bat above ball -> flyout
                return "FLYOUT"
            elif vertical_offset > 10:  # bat below ball -> groundout
                return "GROUNDOUT"
            else:
                return "FLYOUT" if random.random() < 0.5 else "GROUNDOUT"

        # Hit branch — only the HR boundary still matters here. Below it,
        # the outcome is generic "HIT" and the animation's retrieve-time
        # classification picks SINGLE/DOUBLE/TRIPLE later. The existing
        # ceiling math is reused only to derive the HR cutoff.
        hit_rand = random.uniform(0, 1)
        single_ceiling = 0.70 - 0.25 * quality
        double_ceiling = single_ceiling + 0.18 + 0.10 * quality
        triple_ceiling = double_ceiling + 0.06 + 0.04 * quality

        if hit_rand > triple_ceiling:
            self.hit_type = 4
            self.update_runners_and_score()
            return "HOME RUN"
        return "HIT"

    def get_power_hit_outcome(self, swing_location_y=None, ball_location_y=None, timing_diff=None):
        quality, vertical_offset = self._compute_contact_quality(
            swing_location_y, ball_location_y, timing_diff
        )
        self.last_quality = quality
        self.last_vertical_offset = vertical_offset

        multipliers = self._get_difficulty_multipliers()
        out_modifier = multipliers["out_probability_modifier"]
        rand = random.uniform(0, 10)

        # Power swings: slightly lower out chance but more variance
        # Momentum bonus reduces out chance
        out_chance = (0.8 + 4.5 * (1.0 - quality)) * out_modifier * (1.0 - self.momentum_bonus)

        if rand <= out_chance:
            if vertical_offset < -10:
                return "FLYOUT"
            elif vertical_offset > 10:
                return "GROUNDOUT"
            else:
                return "FLYOUT" if random.random() < 0.6 else "GROUNDOUT"

        # Same HR-boundary-only collapse as get_contact_hit_outcome. Power
        # swings push more random rolls past triple_ceiling so HRs are
        # naturally more common; SINGLE/DOUBLE/TRIPLE distribution comes
        # from physics + retrieve-time classification.
        hit_rand = random.uniform(0, 1)
        single_ceiling = 0.40 - 0.20 * quality
        double_ceiling = single_ceiling + 0.25 + 0.05 * quality
        triple_ceiling = double_ceiling + 0.10 + 0.05 * quality

        if hit_rand > triple_ceiling:
            self.hit_type = 4
            self.update_runners_and_score()
            return "HOME RUN"
        return "HIT"

    def apply_classified_outcome(self, outcome_str):
        """Called by pitch_simulation once the animation has classified a
        non-HR HIT into SINGLE / DOUBLE / TRIPLE based on retrieve time.
        Sets hit_type and advances runners accordingly.
        """
        mapping = {"SINGLE": 1, "DOUBLE": 2, "TRIPLE": 3}
        self.hit_type = mapping.get(outcome_str, 1)
        self.update_runners_and_score()
    
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
        elif outcome == "HIT":
            # Generic HIT plays at contact, before the SINGLE/DOUBLE/TRIPLE
            # classification is known. Pick a sound from contact quality so
            # weak contact sounds weak and a hard-hit ball gets a satisfying
            # crack — the actual outcome banner / classification arrives
            # after the animation, the sound is just immediate feedback.
            q = self.last_quality
            if q < 0.4:
                sound_choice = random.choice(['single', 'foul'])
            elif q < 0.7:
                sound_choice = random.choice(['single', 'double'])
            else:
                sound_choice = random.choice(['double', 'triple'])
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
