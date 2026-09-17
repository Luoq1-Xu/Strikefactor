from strikefactor.gameplay import ball_flight, bat_contact, park, spray
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
# reachable offset is +/- 2.75 in, which at the current `ft_per_px_z` of
# 0.01333 is +/- 17.2 px.
FT_PER_PX_Z = DEFAULT_CAMERA.ft_per_px_z

# Batted-ball type. Classified at contact from the contact geometry, and now
# only a *name* for it: `launch_angle_deg` is the quantity, the type is the
# Statcast band it falls in, and `ball_flight` flies the angle rather than the
# band. The hit/out split is not rolled here either — it emerges from fielder
# routing and interception inside HitAnimation.
#
# Convention (pygame y-down): vertical_offset = swing_y - ball_y, so positive
# means the bat sat below the ball at contact — catching the underside sends
# the ball up (POP_UP / FLY). Negative means the bat was above the ball,
# scraping the top down into the ground (GROUNDER).
#
# That convention is now *load-bearing rather than descriptive*. It used to be
# a weighted random roll over four types in which the offset only tilted a
# Gaussian weight, so the sign above was a tendency and not a rule: a bat 1.2
# in over the ball drew a FLY 11% of the time. `ball_flight.launch_angle_deg`
# owns the model now — see the long note there for what was wrong with the
# tables this replaced and why two of them were unreachable.

# Inches in a foot, for the one conversion this module makes: the offset
# arrives in screen pixels (the scale the DB column and `hit_animation` speak)
# and the launch model is stated in real inches.
INCHES_PER_FT = 12.0

# **The home-run probability table is gone.** `_BBT_HR_RATE_BASE`,
# `_BBT_HR_QUALITY_SCALE` and `_POWER_HR_RATE_BONUS` decided whether a ball
# left the park from contact quality alone, and they could not see how far the
# ball was about to be flown — so one batted ball was asked "did it clear the
# fence?" twice, by two models that disagreed. They disagreed *systematically*,
# not occasionally: measured at each shape's real median quality, a line drive
# carrying 241 ft was given a 9.8% chance of clearing a fence no nearer than
# 360 ft (21.8% on a power swing), and a fly carrying 327 ft got 25.9%. That is
# the mechanism behind home runs running ~25% of hits against MLB's ~14% — the
# rates were not mistuned, they were disconnected.
#
# A ball leaves the park now when it is higher than the fence at the fence's
# own distance: `park.fence_verdict`, off this ball's launch angle, exit
# velocity and bearing. Each of those three is drawn exactly once upstream and
# carried, so the verdict here and the flight the animation draws are the same
# flight.
#
# Two levers that used to act on the roll are gone with it, and both were
# second uses of something that already reaches the ball:
#
#   * `out_probability_modifier`. Difficulty is documented as reaching a batted
#     ball as *seconds on the runner's clock*; dividing the home-run rate by it
#     as well was a second, undocumented channel. Difficulty still reaches the
#     fence, the way it reaches a real hitter — through the aim and timing
#     assists, into contact quality, into exit velocity, into carry.
#   * `momentum_bonus`, which is now an exit-velocity bonus applied at the one
#     place this ball's exit velocity is drawn (`MOMENTUM_EV_MPH_PER_UNIT`
#     below, spent in `PitchSimulation._evaluate_contact`). A hot hitter
#     squaring the ball up better is the same statement, made once, where it
#     also reaches the crack, the carry and the recorded EV.

# How much exit velocity a full hot streak is worth, in mph per unit of
# `GameDayManager.get_player_momentum_bonus` (which runs 0 to 0.12). Sized so
# the maximum streak is worth about 1.9 mph — roughly 8 ft of carry on a fly
# ball, which moves a warning-track out onto the fence without manufacturing
# home runs out of ordinary contact.
MOMENTUM_EV_MPH_PER_UNIT = 16.0


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
        # model of one thing. The bearing is not latched here: consumers read
        # `Contact.spray_deg` directly, so there is no stale copy to go wrong.
        # Last batted-ball type — drives the animation shape and is the
        # canonical record of what kind of contact was made.
        self.last_batted_ball_type = None

        # Batter hand/pivot position used to angle the contact zone.
        # The left-handed pivot is the right-handed one mirrored across the
        # plate center (x=630, the strike-zone center), so a LHB's contact
        # zone is angled symmetrically rather than reusing the RHB pivot.
        self.rhpos = (490, 453)
        self.lhpos = (770, 453)

    def launch_angle_deg(self, contact):
        """This ball's launch angle, drawn once.

        **Drawn**, not derived: `ball_flight.launch_angle_deg` carries a
        bounded jitter for swing-plane scatter, so calling it twice gives one
        ball two angles. It used to be called inside `_classify_batted_ball_type`
        and the angle thrown away the moment the band was read off it — which
        is how a continuous geometric quantity ended up quantised to three
        values by the time anything flew the ball. The caller draws it here and
        carries it, the same way `exit_velocity_mph` and `spray_deg` are drawn
        once and carried.
        """
        _, offset_px = self.contact_metrics(contact)
        return ball_flight.launch_angle_deg(
            offset_px * FT_PER_PX_Z * INCHES_PER_FT)

    @staticmethod
    def _classify_batted_ball_type(launch_deg):
        """The Statcast band this launch angle falls in.

        Now only a *classification* — it names what kind of batted ball this
        was, for the DB, the animation's arc and `ground_roll`'s descent angle.
        It is no longer an input to how far the ball goes: `ball_flight` takes
        the angle itself.

        `quality` is deliberately not an input, and it used to be one — a
        per-type bias, positive for liners and sharply negative for pop-ups. It
        does not belong: how square the contact was is the *magnitude* of the
        miss, and the launch angle is its vertical *direction*. Two different
        questions about one geometry, and only the second one is being asked
        here. What the bias was standing in for survives anyway, emergent: an
        extreme undercut is far off centre, so `Contact.centre_score` is low,
        so the ball is struck weakly and carries nowhere. A pop-up is a mishit
        because of where the bat was, not because a table said pop-ups are
        mishits.
        """
        return ball_flight.shape_for_launch_angle(launch_deg)

    def hot_streak_ev_bonus_mph(self):
        """Exit velocity a GameDay hot streak is worth, in mph.

        The whole of what momentum does to a batted ball now. It used to
        multiply a home-run probability, which is a lever on the *outcome*; a
        hitter who is seeing it well squares the ball up better, which is a
        lever on the *ball*, and stating it that way means it reaches the
        carry, the hang time, the crack and the recorded EV through the one
        channel each of those already reads.
        """
        return MOMENTUM_EV_MPH_PER_UNIT * self.momentum_bonus

    def _resolve_outcome(self, launch_deg, ev_mph, spray_deg, handedness):
        """Classify the batted ball and ask the fence about it.

        Two things happen here and neither is a roll. The shape is the band the
        launch angle falls in; the home run is `park.fence_verdict` — is this
        flight higher than the fence when it reaches the fence's own distance.

        Everything else is still deferred to the animation as `IN_PLAY`, and
        emerges there from fielder routing and interception. The home run stays
        here because it is the one outcome fully settled at contact: nobody can
        field it, so runners advance now.

        The inputs are this ball's own launch angle, exit velocity and bearing,
        each drawn once upstream. `hit_animation` places the ball from the same
        three, through the same function, so the banner and the picture cannot
        come apart.
        """
        batted_ball_type = self._classify_batted_ball_type(launch_deg)
        self.last_batted_ball_type = batted_ball_type

        field_rad = spray.field_angle_rad(spray_deg, spray.spin_for(handedness))
        if park.fence_verdict(launch_deg, ev_mph, field_rad) == park.OUT_OF_PARK:
            self.hit_type = 4
            self.update_runners_and_score()
            return "HOME RUN"
        return "IN_PLAY"

    def hit_outcome(self, contact, launch_deg, ev_mph, handedness="R"):
        """Coarse outcome at contact. Returns one of:
            "HOME RUN" — predetermined; runners advance now.
            "IN_PLAY"  — ball is live. The HitAnimation classifies the
                         final result (FLYOUT, GROUNDOUT, SINGLE, DOUBLE,
                         TRIPLE) from fielder routing + interception and
                         pitch_simulation then calls
                         apply_classified_outcome() to settle stats and
                         runners.

        `launch_deg` and `ev_mph` are this ball's own, drawn once by the caller
        — see `launch_angle_deg` and `PitchSimulation.exit_velocity_mph`. They
        are arguments rather than something recomputed here for the reason
        every other once-drawn quantity in this pipeline is: drawing twice
        gives one ball two flights.

        It replaced `get_contact_hit_outcome` / `get_power_hit_outcome`, whose
        only difference was a `swing_type` that fed the home-run roll's power
        bonus. With the fence deciding home runs there is nothing left for the
        swing type to do here — a power swing already reaches the fence the way
        it always claimed to, through `contact_audio.EV_POWER_BONUS_MPH` on the
        exit velocity the caller drew.
        """
        self.hit_type = 0
        self.ishomerun = ''
        quality, vertical_offset = self.contact_metrics(contact)
        self.last_quality = quality
        self.last_vertical_offset = vertical_offset
        return self._resolve_outcome(launch_deg, ev_mph, contact.spray_deg,
                                     handedness)

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
    
    def play_hit_sound(self, swing_type="contact", ev_mph=None,
                       is_home_run=False):
        """Play the contact sound for the swing just resolved.

        Deliberately takes no outcome. Sample and loudness come from how
        hard the ball was hit, so a scorched liner sounds enormous whether
        it lands for a double or in a glove. This fires at impact, before
        the animation resolves the result — which is why outcome must not
        be an input.

        `ev_mph` is this ball's already-drawn exit velocity — see
        `SoundManager.play_contact`. A batted ball has exactly one, and the
        caller drew it before building the animation.

        `is_home_run` is the one thing here that *is* keyed to an outcome,
        and it reaches only the sample floor — never the exit velocity. It
        replaced an `hr_distance_ft` that read the EV back out of the carry
        distance and outranked `ev_mph`; the caller then recorded what came
        back. See the note above `contact_audio.HOMERUN_MIN_SAMPLE`.
        """
        return self.sound_manager.play_contact(
            self.last_quality, swing_type, ev_mph=ev_mph,
            is_home_run=is_home_run)
    
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
