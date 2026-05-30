import random
import math
from utils.physics import collision_angled


# Batted-ball type model. Classified at contact from (quality, vertical_offset);
# drives the trajectory shape passed to the animation. The hit/out split is
# no longer rolled here — it emerges from fielder routing + interception
# inside HitAnimation. We still classify the type up front because the
# trajectory shape (high arc vs. line drive vs. bouncing grounder) is a
# property of how the bat met the ball, not of who fielded it.
# Convention (pygame y-down): vertical_offset = swing_y - ball_y, so positive
# means the bat sat below the ball at contact — catching the underside sends
# the ball up (POP_UP / FLY). Negative means the bat was above the ball,
# scraping the top down into the ground (GROUNDER).
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
    "POP_UP":    22.0,
    "FLY":       11.0,
    "LINER":      0.0,
    "GROUNDER": -11.0,
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
    "POP_UP":   0.15,
    "FLY":      0.22,
    "LINER":    0.20,
    "GROUNDER": 0.40,
}

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
        # Signed horizontal offset of the ball at contact, in screen pixels,
        # relative to the *batter's* inside/outside. Positive = inside the
        # batter (drives pull-direction HRs); negative = outside (drives
        # opposite-field HRs). Computed from ball_x vs the strike zone
        # center, sign-flipped by handedness so a single sign convention
        # works for both RHB and LHB downstream.
        self.last_horizontal_inside = 0.0
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
        """Classify batted-ball type and roll HR. Everything else is deferred.

        Out vs hit is no longer decided here — that emerges from the
        animation's fielder routing and interception detection. HR is a
        contact-time property (the ball is aimed past the wall by
        definition) so we still roll it here; downstream the result is
        either "HOME RUN" with runners already advanced, or "HIT" (the
        generic in-play outcome) whose final classification — FLYOUT,
        GROUNDOUT, SINGLE, DOUBLE, or TRIPLE — is set by the animation
        and applied via apply_classified_outcome().
        """
        batted_ball_type = self._classify_batted_ball_type(quality, vertical_offset)
        self.last_batted_ball_type = batted_ball_type

        # HR roll — only FLY/LINER can clear the wall. Difficulty/momentum
        # modulate the rate: harder difficulty (out_modifier > 1) suppresses
        # HRs, hot-streak momentum amplifies them.
        hr_base = _BBT_HR_RATE_BASE[batted_ball_type]
        hr_qscale = _BBT_HR_QUALITY_SCALE[batted_ball_type]
        hr_rate = hr_base + hr_qscale * max(0.0, (2.0 * quality - 1.0))
        if swing_type == "power" and batted_ball_type in ("FLY", "LINER"):
            hr_rate += _POWER_HR_RATE_BONUS
        multipliers = self._get_difficulty_multipliers()
        out_modifier = multipliers["out_probability_modifier"]
        hr_rate = hr_rate / max(0.01, out_modifier)
        hr_rate = hr_rate * (1.0 + self.momentum_bonus)
        hr_rate = max(0.0, min(1.0, hr_rate))
        if hr_rate > 0.0 and random.random() < hr_rate:
            self.hit_type = 4
            self.update_runners_and_score()
            return "HOME RUN"
        return "IN_PLAY"

    def _compute_horizontal_inside(self, ball_location_x, batter_handedness):
        """Signed inside/outside offset (px) relative to the batter's body.

        Positive = pitch was inside (close to the batter); negative = outside.
        Strike zone is centered at x=630 (ABS_ZONE). RHB stands at low x,
        so inside is ball_x < 630; LHB stands at high x, so inside is
        ball_x > 630. The sign flip here lets downstream consumers use a
        single convention (positive = pull, negative = oppo) regardless of
        handedness.
        """
        if ball_location_x is None:
            return 0.0
        zone_center_x = 630.0
        if batter_handedness == 'L':
            return ball_location_x - zone_center_x
        return zone_center_x - ball_location_x

    def get_contact_hit_outcome(self, swing_location_y=None, ball_location_y=None, timing_diff=None,
                                ball_location_x=None, batter_handedness='R'):
        """Coarse outcome at contact. Returns one of:
            "HOME RUN" — predetermined; runners advance now.
            "IN_PLAY"  — ball is live. The HitAnimation classifies the
                         final result (FLYOUT, GROUNDOUT, SINGLE, DOUBLE,
                         TRIPLE) from fielder routing + interception and
                         pitch_simulation then calls
                         apply_classified_outcome() to settle stats and
                         runners.

        The batted-ball type is classified first (and stored on
        self.last_batted_ball_type) — it drives the HR gate and the
        trajectory shape used by the animation.
        """
        quality, vertical_offset = self._compute_contact_quality(
            swing_location_y, ball_location_y, timing_diff
        )
        self.last_quality = quality
        self.last_vertical_offset = vertical_offset
        self.last_horizontal_inside = self._compute_horizontal_inside(
            ball_location_x, batter_handedness
        )
        return self._resolve_outcome(quality, vertical_offset, swing_type="contact")

    def get_power_hit_outcome(self, swing_location_y=None, ball_location_y=None, timing_diff=None,
                              ball_location_x=None, batter_handedness='R'):
        quality, vertical_offset = self._compute_contact_quality(
            swing_location_y, ball_location_y, timing_diff
        )
        self.last_quality = quality
        self.last_vertical_offset = vertical_offset
        self.last_horizontal_inside = self._compute_horizontal_inside(
            ball_location_x, batter_handedness
        )
        return self._resolve_outcome(quality, vertical_offset, swing_type="power")

    def apply_classified_outcome(self, outcome_str):
        """Called by pitch_simulation once the animation has classified an
        IN_PLAY contact into its final outcome. Hits advance runners; outs
        do not (the game doesn't model sac flies / productive outs yet).
        """
        if outcome_str in ("GROUNDOUT", "FLYOUT", "LINEOUT"):
            return
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
        if outcome == "HOME RUN" or self.hit_type == 4:
            self.sound_manager.play('homerun')
            return
        # All other contacts: the outcome isn't known yet (FLYOUT vs
        # GROUNDOUT vs SINGLE/DOUBLE/TRIPLE emerges from the animation).
        # Pick a sound from contact quality so weak contact sounds weak
        # and a hard-hit ball gets a satisfying crack — the actual
        # outcome banner arrives after the animation.
        q = self.last_quality
        if q < 0.4:
            sound_choice = random.choice(['single', 'foul'])
        elif q < 0.7:
            sound_choice = random.choice(['single', 'double'])
        else:
            sound_choice = random.choice(['double', 'triple'])
        self.sound_manager.play(sound_choice)
    
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
