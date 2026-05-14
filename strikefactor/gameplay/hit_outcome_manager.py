import random
import math
from utils.physics import collision_angled


# Batted-ball type model. Classified at contact from (quality, vertical_offset);
# drives both the hit/out split and the trajectory shape passed to the
# animation. Convention follows _pick_shape in hit_animation.py: negative
# vertical_offset is the fly direction, positive is the grounder direction.
#
# Marginals target 2025 MLB league split — GB 42% / FB 27% / LD 24% / PU 7%
# — integrated over the natural quality/offset distribution the game produces.
# Tuned via a Monte Carlo harness (see tests not shipped; throwaway).
_BATTED_BALL_TYPES = ("POP_UP", "FLY", "LINER", "GROUNDER")

# Gaussian-anchored shape preferences. Each type peaks around an offset
# anchor; sigma controls how aggressively it claims nearby offsets.
# Anchors are inside the contact-zone reach (~±25 px) so each type has a
# realistic shot at being selected by a typical swing.
_TYPE_OFFSET_ANCHORS = {
    "POP_UP":   -22.0,
    "FLY":      -11.0,
    "LINER":      0.0,
    "GROUNDER":  11.0,
}
_TYPE_OFFSET_SIGMA = {
    "POP_UP":     8.5,
    "FLY":       11.5,
    "LINER":      8.5,
    "GROUNDER":  14.0,
}

# Per-type quality bias. Positive = type favored by solid contact;
# negative = favored by weak contact. Multiplier = 1 + bias * (2q - 1)
# so at q=0.5 the bias is neutral.
_TYPE_QUALITY_BIAS = {
    "POP_UP":   -0.85,   # popups come from weak under-swings
    "FLY":       0.20,
    "LINER":     0.55,
    "GROUNDER": -0.20,
}

# Base prior on type frequency — pre-quality, pre-offset. Anchors the
# overall mix near the MLB marginal even before geometry pulls each
# contact toward a specific type.
_TYPE_BASE_PRIOR = {
    "POP_UP":   0.34,
    "FLY":      0.22,
    "LINER":    0.20,
    "GROUNDER": 0.40,
}

# Per-type base out rate at neutral quality (q=0.5). Matches MLB 2025
# ratios. Quality fully drives deviation: at q=1 a screaming liner is
# almost always a hit; at q=0 even a "liner" type contact is mostly an
# out. out_rate = base * (1 - QUALITY_SCALE * (2q - 1)), clamped [0, 1].
# Typical in-game mean quality is ~0.9, so total hit rate sits well above
# MLB's .289 BABIP — the game intentionally rewards skilled contact.
_BBT_BASE_OUT_RATE = {
    "POP_UP":   0.98,
    "FLY":      0.89,
    "GROUNDER": 0.77,
    "LINER":    0.34,
}
_BBT_QUALITY_OUT_SCALE = {
    "POP_UP":   0.30,
    "FLY":      0.85,
    "GROUNDER": 0.65,
    "LINER":    0.95,
}
# Power swing applies a small reduction to the type-driven out rate
# (the existing "power swings are slightly safer" bias, now type-aware).
_POWER_OUT_RATE_BONUS = 0.06

# Per-type HR probability on a hit. POP_UP / GROUNDER never become HRs
# (physically impossible — popups are caught, grounders never clear a
# wall). FLY/LINER can be HRs, with FLY much more so. Quality scales
# the chance: q=0.5 -> base, q=1.0 -> base + quality_scale.
_BBT_HR_RATE_BASE = {
    "POP_UP":   0.00,
    "GROUNDER": 0.00,
    "LINER":    0.04,
    "FLY":      0.15,
}
_BBT_HR_QUALITY_SCALE = {
    "POP_UP":   0.00,
    "GROUNDER": 0.00,
    "LINER":    0.08,
    "FLY":      0.18,
}
# Power swings convert more flies into HRs — same "swing for the fences"
# bias the previous formula had, now type-gated.
_POWER_HR_RATE_BONUS = 0.12


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
        # Last batted-ball type — drives the animation shape and is the
        # canonical record of what kind of contact was made.
        self.last_batted_ball_type = None

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

    def _classify_batted_ball_type(self, quality, vertical_offset):
        """Pick a batted-ball type from contact metrics.

        Each type weight = base_prior * offset_gaussian * (1 + quality_bias*(2q-1)).
        Marginals across the natural quality/offset distribution target
        2025 MLB league split (GB 42 / FB 27 / LD 24 / PU 7).
        """
        weights = {}
        for t in _BATTED_BALL_TYPES:
            anchor = _TYPE_OFFSET_ANCHORS[t]
            sigma = _TYPE_OFFSET_SIGMA[t]
            offset_w = math.exp(-0.5 * ((vertical_offset - anchor) / sigma) ** 2)
            qual_w = max(0.05, 1.0 + _TYPE_QUALITY_BIAS[t] * (2.0 * quality - 1.0))
            weights[t] = _TYPE_BASE_PRIOR[t] * offset_w * qual_w

        total = sum(weights.values())
        if total <= 0.0:
            return "LINER"
        roll = random.uniform(0.0, total)
        cum = 0.0
        for t in _BATTED_BALL_TYPES:
            cum += weights[t]
            if roll <= cum:
                return t
        return "LINER"

    def _resolve_outcome(self, quality, vertical_offset, swing_type):
        """Common outcome resolution: classify type, then roll out/HR/hit."""
        batted_ball_type = self._classify_batted_ball_type(quality, vertical_offset)
        self.last_batted_ball_type = batted_ball_type

        multipliers = self._get_difficulty_multipliers()
        out_modifier = multipliers["out_probability_modifier"]

        # Per-type out rate at q=0.5 matches MLB; quality scales it
        # multiplicatively (q=1 -> base * (1 - scale), q=0 -> base * (1 + scale)).
        base = _BBT_BASE_OUT_RATE[batted_ball_type]
        qscale = _BBT_QUALITY_OUT_SCALE[batted_ball_type]
        out_rate = base * max(0.0, 1.0 - qscale * (2.0 * quality - 1.0))
        if swing_type == "power":
            out_rate = max(0.0, out_rate - _POWER_OUT_RATE_BONUS)
        out_rate = max(0.0, min(1.0, out_rate * out_modifier * (1.0 - self.momentum_bonus)))

        if random.random() < out_rate:
            if batted_ball_type == "GROUNDER":
                return "GROUNDOUT"
            return "FLYOUT"

        # Hit branch — only FLY/LINER can be HRs. HR roll fires before
        # the generic "HIT" so the runners can be advanced at contact.
        hr_base = _BBT_HR_RATE_BASE[batted_ball_type]
        hr_qscale = _BBT_HR_QUALITY_SCALE[batted_ball_type]
        hr_rate = hr_base + hr_qscale * max(0.0, (2.0 * quality - 1.0))
        if swing_type == "power" and batted_ball_type in ("FLY", "LINER"):
            hr_rate += _POWER_HR_RATE_BONUS
        if hr_rate > 0.0 and random.random() < hr_rate:
            self.hit_type = 4
            self.update_runners_and_score()
            return "HOME RUN"
        return "HIT"

    def get_contact_hit_outcome(self, swing_location_y=None, ball_location_y=None, timing_diff=None):
        """Coarse outcome at contact. Returns one of:
            "FLYOUT", "GROUNDOUT" — out paths.
            "HOME RUN"            — predetermined; runners advance now.
            "HIT"                 — generic non-HR hit; the HitAnimation will
                                    classify SINGLE/DOUBLE/TRIPLE by retrieve
                                    time and pitch_simulation will then call
                                    apply_classified_outcome() to advance the
                                    runners.

        The batted-ball type is classified first (and stored on
        self.last_batted_ball_type) — it drives the out vs hit roll, the HR
        gate, and the trajectory shape used by the animation.
        """
        quality, vertical_offset = self._compute_contact_quality(
            swing_location_y, ball_location_y, timing_diff
        )
        self.last_quality = quality
        self.last_vertical_offset = vertical_offset
        return self._resolve_outcome(quality, vertical_offset, swing_type="contact")

    def get_power_hit_outcome(self, swing_location_y=None, ball_location_y=None, timing_diff=None):
        quality, vertical_offset = self._compute_contact_quality(
            swing_location_y, ball_location_y, timing_diff
        )
        self.last_quality = quality
        self.last_vertical_offset = vertical_offset
        return self._resolve_outcome(quality, vertical_offset, swing_type="power")

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
