import math
import random

from strikefactor.gameplay import bat_contact
from strikefactor.settings_manager import (
    DIFFICULTY_MULTIPLIERS,
    DifficultyLevel,
)
from strikefactor.utils.pitch_physics import DEFAULT_CAMERA

# The vertical offset the batted-ball model below is tuned against is stated
# in screen pixels, because it always has been — the DB column, the type
# anchors and `hit_animation._pick_shape` all speak it. `bat_contact` measures
# the real thing in feet, so it is converted once, here, rather than restating
# every constant downstream in inches. The two scales happen to be close: the
# reachable offset is +/- 2.75 in, which is +/- 20.6 px, against anchors that
# run to 22.
FT_PER_PX_Z = DEFAULT_CAMERA.ft_per_px_z

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
        # Which way the ball went: degrees from centre field, pull-positive
        # for either batter. Read off the bat's own bearing at contact — see
        # `spray`.
        #
        # It replaced `last_horizontal_inside`, which was the *pitch's*
        # inside/outside offset in screen pixels and was consulted by exactly
        # one thing (the home-run angle). Pitch location does belong in the
        # answer, but it belongs in it the way it reaches a real hitter — by
        # moving where the bat is pointing when it arrives — and `bat_path`
        # already models that. Reading it off the pitch instead was the second
        # model of one thing.
        self.last_spray_deg = 0.0
        # Last batted-ball type — drives the animation shape and is the
        # canonical record of what kind of contact was made.
        self.last_batted_ball_type = None

        # Batter hand/pivot position used to angle the contact zone.
        # The left-handed pivot is the right-handed one mirrored across the
        # plate center (x=630, the strike-zone center), so a LHB's contact
        # zone is angled symmetrically rather than reusing the RHB pivot.
        self.rhpos = (490, 453)
        self.lhpos = (770, 453)

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

    def get_contact_hit_outcome(self, contact):
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
        self.hit_type = 0
        self.ishomerun = ''
        quality, vertical_offset = self.contact_metrics(contact)
        self.last_quality = quality
        self.last_vertical_offset = vertical_offset
        self.last_spray_deg = contact.spray_deg
        return self._resolve_outcome(quality, vertical_offset, swing_type="contact")

    def get_power_hit_outcome(self, contact):
        self.hit_type = 0
        self.ishomerun = ''
        quality, vertical_offset = self.contact_metrics(contact)
        self.last_quality = quality
        self.last_vertical_offset = vertical_offset
        self.last_spray_deg = contact.spray_deg
        return self._resolve_outcome(quality, vertical_offset, swing_type="power")

    def apply_classified_outcome(self, outcome_str, suppress_out_advancement=False,
                                 bases=1):
        """Called by pitch_simulation once the animation has classified an
        IN_PLAY contact into its final outcome. Runner movement is based on
        the resolved outcome so productive outs can advance runners.

        `bases` is how far the batter got on a REACHED ON ERROR — a drop in
        shallow left is a one-base error and one at the wall is a two-base
        error. It is ignored for every other outcome, which carries its own
        advance in its name.
        """
        self.score_keeper.update_hit_event(
            outcome_str,
            suppress_out_advancement=suppress_out_advancement,
            bases=bases,
        )
    
    def resolve_swing(self, swing, trajectory, swing_start_s, swing_type=1):
        """Sweep the bat against the ball. Returns a `bat_contact.Contact` or None.

        This replaced two unrelated gates. The first compared
        `swing_start + 150` against the ball reaching the *plate* and graded
        the result on a difficulty window; the second, only if that passed,
        tested a 120 x 50 px rectangle at the cursor against the ball's screen
        position for one frame. Neither knew about the other and neither had a
        depth axis, which is why contact depth could not be an output of the
        pair and the replay had to model a bat backwards from the pitch to get
        one. There is one question now, asked of two solids in three
        dimensions, and when / where / how square all fall out of it together.
        """
        zone_size_mult, timing_window_mult = self.contact_multipliers(swing_type)
        return bat_contact.resolve_contact(
            swing, trajectory, swing_start_s,
            zone_size_mult=zone_size_mult,
            timing_window_mult=timing_window_mult,
            power=(swing_type == 2),
        )

    def contact_multipliers(self, swing_type=1):
        """`(zone_size_mult, timing_window_mult)` for this swing type.

        Here for the same reason `resolve_swing`, `resolve_aim` and
        `_foul_threshold` are: this class is the one place a difficulty
        multiplier becomes a real quantity, so the gameplay layer never reads
        the multiplier dict itself.

        Exposed so `PitchSimulation` can *stamp* them on the swing, which
        `SwingRecord` then carries. The replay re-sweeps the swing to measure
        the timing it actually had, and re-reading difficulty at replay time
        would show a player who changed the setting a window nobody swung in —
        the same failure `aim_assist` is carried to avoid.
        """
        multipliers = self._get_difficulty_multipliers()
        return (multipliers["contact_zone_size"],
                multipliers["power_timing_window" if swing_type == 2
                            else "contact_timing_window"])

    def aim_assist(self):
        """The in-swing aim adjustment in force, as a fraction of the error.

        Here for the same reason `contact_multipliers` is: `PitchSimulation`
        has to *stamp* this on the swing so `SwingRecord` can carry it, and
        this class is the one place a difficulty multiplier becomes a real
        quantity. Read off `_get_difficulty_multipliers` rather than the
        settings manager directly, so the stamped value and the one
        `resolve_aim` applies cannot come from two different tables.
        """
        return self._get_difficulty_multipliers()["aim_assist"]

    def resolve_aim(self, cursor_ft, trajectory, handedness):
        """The aim the player's cursor names against this pitch, assisted.

        Two things at once, and `bat_contact.aim_at_pitch` documents both: the
        cursor is carried onto the barrel's own depth, which is a bias fix, and
        it is then pulled a difficulty-scaled fraction of the way toward the
        ball, which is the in-swing adjustment a hitter makes once they have
        read the pitch. The second is game feel; the first is not.

        Here for the same reason `resolve_swing` and `_foul_threshold` are:
        this class is the one place a difficulty multiplier becomes a real
        quantity, so the gameplay layer never reads the multiplier dict itself.
        """
        return bat_contact.aim_at_pitch(
            cursor_ft, trajectory, handedness, assist=self.aim_assist())

    def swing_verdict(self, contact, swing_type=1):
        """0 whiff / 1 foul / 2 fair, from the resolved contact.

        `on_time` keeps its name and its three values so every consumer of the
        column still reads, but it is no longer a *timing* grade — it is what
        the geometry produced. Timing reaches it the way it reaches a real
        swing: early meets the ball off the end of the bat, late on the handle,
        and both score badly enough to go foul — and, since `spray`, early also
        turns the bat further round and hooks the ball toward the pole.
        """
        if contact is None:
            return 0
        return 1 if contact.is_foul(self._foul_threshold(swing_type)) else 2

    def _foul_threshold(self, swing_type):
        return bat_contact.foul_threshold(self.contact_multipliers(swing_type)[1])

    @staticmethod
    def contact_metrics(contact):
        """`(quality, vertical_offset_px)` for a resolved contact.

        The offset is bat-below-ball positive, in pygame's y-down screen
        convention — the same sign and scale the old screen-space contact test
        produced, so the batted-ball type model and `hit_animation._pick_shape`
        read it unchanged.

        Fouls come through here too. That path used to have a method of its
        own, which relaxed the timing sigma from 35 ms to 70 because a
        foul-graded swing was 20-60 ms off *by definition*. Quality is
        geometric now — a foul is contact that genuinely was not squared up —
        so there is nothing left to compensate for and the two are one call.
        """
        return contact.quality, contact.vertical_offset_ft / FT_PER_PX_Z

    def update_runners_and_score(self):
        self.ishomerun = ''
        scored = self.score_keeper.update_hit_event("HOME RUN")[1]
        
        if self.hit_type == 4:
            if scored == 1:
                self.ishomerun = 'SOLO HOME RUN'
            elif scored == 2:
                self.ishomerun = 'TWO-RUN HOME RUN'
            elif scored == 3:
                self.ishomerun = 'THREE-RUN HOME RUN'
            else:
                self.ishomerun = 'GRAND SLAM'
    
    def play_hit_sound(self, swing_type="contact", hr_distance_ft=None):
        """Play the contact sound for the swing just resolved.

        Deliberately takes no outcome. Sample and loudness come from how
        hard the ball was hit, so a scorched liner sounds enormous whether
        it lands for a double or in a glove. This fires at impact, before
        the animation resolves the result — which is why outcome must not
        be an input.

        `hr_distance_ft` is not an outcome cue but a better measurement:
        on a home run the carry model has already fixed the distance, and
        that distance reflects how hard the ball was struck more faithfully
        than quality does. See SoundManager.play_contact.

        Returns the modelled exit velocity so the caller can record it.
        """
        return self.sound_manager.play_contact(
            self.last_quality, swing_type, hr_distance_ft=hr_distance_ft)
    
    def get_homerun_text(self):
        return self.ishomerun

    def _get_difficulty_multipliers(self):
        """Difficulty multipliers from the settings manager, or the defaults.

        The fallback is the **AMATEUR row of the real table**, not a copy of
        it. It used to be a dict literal restating that row, and a restatement
        drifts: `aim_assist` was added to `settings_manager` and not here, so
        every `HitOutcomeManager` built without a `SettingsManager` — the
        default in the constructor signature, and what the tests use — raised
        `KeyError: 'aim_assist'` the first time `resolve_aim` was called.
        Reading the table means a key can never again exist for a player and
        be missing for the fallback.
        """
        if self.settings_manager:
            return self.settings_manager.get_difficulty_multipliers()
        return dict(DIFFICULTY_MULTIPLIERS[DifficultyLevel.AMATEUR])
