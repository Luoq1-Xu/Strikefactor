"""One clock per play.

The animation used to run two. Ball flight came from
`HIT_BASE_DURATION_MS * (1.2 - 0.4 * quality)` — about 3.3 s to cover
140 ft, an implied 29 mph for a ball struck at 90 — while fielders moved at
a correct MLB sprint speed against that stretched window, so they covered
two to three times the ground they ever could. `INFIELD_LOW_BALL_RANGE_PX`,
`INFIELD_CHASE_RANGE_PX` and `FIRST_BASE_GROUNDER_RANGE_PX` all existed to
claw that back by hand, and all three are gone.

Everything physical is now specified in real feet and real seconds and
crosses to the animated clock through exactly two methods. These guard that
boundary — the discipline is only worth having if a violation is caught.
"""

import math

import pytest

from strikefactor.gameplay import ball_flight, ground_roll, infield_timing
from strikefactor.gameplay import hit_animation as ha


class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubSettings:
    def get_difficulty_multipliers(self):
        return {"out_probability_modifier": 1.0}


class _StubGame:
    def __init__(self):
        self.batter = _StubBatter()
        self.settings_manager = _StubSettings()


def _make(shape="GROUNDER", quality=0.8):
    return ha.HitAnimation(_StubGame(), outcome="IN_PLAY",
                           on_complete=lambda: None, quality=quality,
                           batted_ball_type=shape)


# ---- The boundary ----------------------------------------------------------

def test_anim_ms_is_the_only_scaling_and_it_is_linear():
    anim = _make()
    assert anim._anim_ms(1.0) == pytest.approx(1000.0 * anim.time_scale)
    assert anim._anim_ms(2.5) == pytest.approx(2.5 * anim._anim_ms(1.0))
    assert anim._anim_ms(0.0) == 0.0


def test_flight_duration_is_the_physical_flight_time_scaled_once():
    """`duration_ms` is no longer a tuning value — it is what `ball_flight`
    says, shown through the one presentation constant."""
    for shape in ("GROUNDER", "LINER", "FLY", "POP_UP"):
        anim = _make(shape)
        assert anim.duration_ms == pytest.approx(
            anim._anim_ms(anim.flight_time_s), abs=1.0)
        assert anim.flight_time_s > 0


def test_a_ball_hit_farther_now_hangs_longer():
    """The inversion that quality-scaled duration produced: harder contact
    goes farther *and* was given less time in the air, so the deepest fly
    balls gave outfielders the least time to run them down."""
    shallow = _make("FLY", quality=0.55)
    deep = _make("FLY", quality=0.99)
    shallow_ft = ha._ft_dist(shallow._hit_end[0] - ha.HOME[0],
                             shallow._hit_end[1] - ha.HOME[1])
    deep_ft = ha._ft_dist(deep._hit_end[0] - ha.HOME[0],
                          deep._hit_end[1] - ha.HOME[1])
    assert deep_ft > shallow_ft
    assert deep.duration_ms > shallow.duration_ms


# ---- Speed is honest in feet, in every direction ---------------------------

def test_a_sprint_covers_the_same_ground_whichever_way_it_runs():
    """The projection is anisotropic — a pixel is 1/1.85 ft across and
    1/1.10 ft deep — so a scalar px/ms speed silently meant two different
    real speeds. 40 px/s was 21.6 ft/s laterally and 36.4 ft/s straight
    back, which is faster than any human has run."""
    anim = _make()
    fielder = anim.fielders["CF"]
    fielder.max_speed = ha.FIELDER_SPRINT_FT_S
    origin = (640.0, 400.0)
    distance_ft = 60.0
    times = []
    for angle in (0.0, math.pi / 4, math.pi / 2, 3 * math.pi / 4):
        # A point exactly `distance_ft` away along this screen bearing.
        dx, dy = math.cos(angle), math.sin(angle)
        scale = distance_ft / ha._ft_dist(dx, dy)
        target = (origin[0] + dx * scale, origin[1] + dy * scale)
        times.append(anim._travel_ms(fielder, origin, target))
    assert max(times) == pytest.approx(min(times), rel=1e-6)


def test_travel_time_matches_the_real_sprint():
    anim = _make()
    fielder = anim.fielders["SS"]
    fielder.max_speed = 27.0
    start = (640.0, 400.0)
    end = (640.0 + 27.0 * ha.FT_TO_PX_X, 400.0)      # exactly 27 ft to the side
    # One real second, on the animated clock.
    assert anim._travel_ms(fielder, start, end) == pytest.approx(
        anim._anim_ms(1.0), rel=1e-6)


def test_ranging_range_is_a_circle_on_the_field_not_on_the_screen():
    """`_max_intercept_dist` is in feet, so the zone it carves out is the
    ellipse the projection makes of a real circle. As a pixel radius the
    pitcher's 28 px bought 15 ft laterally and 25 ft straight back — a
    fielding zone shaped like a teardrop pointing at centre field."""
    anim = _make()
    pitcher = anim.fielders["P"]
    cap_ft = anim._max_intercept_dist(pitcher)
    for angle in (0.0, math.pi / 3, math.pi / 2, 2 * math.pi / 3):
        far = (pitcher.home_pos[0] + math.cos(angle) * 400,
               pitcher.home_pos[1] + math.sin(angle) * 400)
        clamped = anim._range_limited_point(pitcher, far)
        assert anim._range_ft(pitcher, clamped) == pytest.approx(cap_ft, rel=1e-6)


# ---- The caps are gone, and the physics reproduces them ---------------------

def test_the_dilation_correction_constants_are_gone():
    """Named explicitly so re-adding one is a deliberate act. Each existed
    only to correct the clock; a real sprint against a real flight time
    reproduces the ~30 ft of infield range the first of them hand-set."""
    for name in ("INFIELD_LOW_BALL_RANGE_PX", "INFIELD_CHASE_RANGE_PX",
                 "FIRST_BASE_GROUNDER_RANGE_PX", "FIELDER_MAX_SPEED_PX_MS",
                 "ROLLING_DECEL_PX_MS2", "RETRIEVE_TIME_SINGLE_MAX_MS",
                 "RETRIEVE_TIME_DOUBLE_MAX_MS"):
        assert not hasattr(ha, name), f"{name} is back"


def test_the_post_landing_render_unit_constants_are_gone():
    """The same fault one phase later, and the reported bug: every one of
    these stated a physical property of a bouncing ball in pixels or
    animated milliseconds. `gameplay/ground_roll.py` owns them now, in feet
    and seconds."""
    for name in ("SHAPE_LAND_FACTOR", "ROLLING_DECEL_FT_S2", "BOUNCE_COR",
                 "BOUNCE_INITIAL_DURATION_MS", "BOUNCE_HEIGHT_THRESHOLD_PX",
                 "BOUNCE_HORIZONTAL_RETENTION", "SHAPE_BOUNCE_HEIGHT_FRAC",
                 "BOUNCE_HEIGHT_MAX_PX"):
        assert not hasattr(ha, name), f"{name} is back"


def test_an_infielder_covers_about_thirty_feet_on_a_grounder():
    """The payoff, and the reason the caps could go: 55 px (~30 ft) was
    what `INFIELD_LOW_BALL_RANGE_PX` hand-set, and the honest clock lands
    in the same place on its own.

    Over a sample, because it is a claim about the typical grounder: where
    the ball is hit is random, so one draw ranges from 29 to 46 ft and a
    single-sample assertion on a 15-45 ft band fails at whatever rate the
    tail happens to have."""
    reaction_s = ha.REACTION_DELAY_MAX_S
    covered = sorted(
        ha.FIELDER_SPRINT_FT_S * max(0.0, _make("GROUNDER", quality=0.85).flight_time_s
                                     - reaction_s)
        for _ in range(200))
    median = covered[len(covered) // 2]
    assert 22.0 <= median <= 40.0, (
        f"an infielder covers {median:.0f} ft in a typical grounder's flight")
    assert 12.0 <= covered[0] and covered[-1] <= 60.0, (
        f"grounder range spans {covered[0]:.0f}-{covered[-1]:.0f} ft")


def test_the_ball_crosses_to_the_animated_clock_at_one_speed(monkeypatch):
    """Stopping distance goes as v²/2a, so a px-per-animated-ms² constant
    made roll distance a function of presentation pacing — unifying the
    clock multiplied it by ~1.7 and sent line drives rolling to the wall.

    The post-landing conversion is `_fts_to_px_ms`, and it has to mean the
    same real speed whichever way the ball is going: the projection is
    anisotropic, so one scalar px/ms is two different ft/s."""
    for point in ((ha.HOME[0] + 400, ha.HOME[1]),
                  (ha.HOME[0], ha.HOME[1] - 400),
                  (ha.HOME[0] + 260, ha.HOME[1] - 260)):
        monkeypatch.setattr(ha, "_pick_hit_landing", lambda *a, **k: point)
        anim = _make("LINER", quality=0.8)
        anim._init_ball_on_ground()
        px_ms = math.hypot(*anim._ball_v)
        # The pixels on screen carry exactly the ft/s ground_roll modelled,
        # whichever way the ball went.
        modelled = ground_roll.landing_speed_fts(
            anim.shape, anim.exit_velocity_mph,
            ha._ft_dist(point[0] - ha.HOME[0], point[1] - ha.HOME[1]),
            anim.flight_time_s)
        assert anim._px_ms_to_fts(px_ms) == pytest.approx(modelled, rel=1e-9)
        assert anim._fts_to_px_ms(modelled) == pytest.approx(px_ms, rel=1e-9)


# ---- The flight and the roll are one motion --------------------------------

def _flight_end_px_ms(anim, monkeypatch, dt=4.0):
    """The ball's speed on the last frame of flight, px per animated ms.

    Measured off the rendered shadow rather than computed, so this is the
    speed the player's eye actually gets. Interception is stubbed out
    because a caught ball has no landing to be continuous with.
    """
    monkeypatch.setattr(anim, "_check_in_flight_intercept", lambda: False)
    anim.update(0)
    anim._elapsed = anim.duration_ms - dt
    anim._update_hit(anim._elapsed)
    before = anim._ball_shadow
    anim._elapsed = anim.duration_ms
    anim._update_hit(anim._elapsed)
    after = anim._ball_shadow
    return math.hypot(after[0] - before[0], after[1] - before[1]) / dt


@pytest.mark.parametrize("shape", ["GROUNDER", "LINER", "FLY", "POP_UP"])
def test_the_ball_lands_at_the_speed_it_was_flying(shape, monkeypatch):
    """The reported bug: a grounder visibly slammed on the brakes where it
    reached the outfield grass.

    The flight ran at the path's *average* speed and then handed the ball
    to `ground_roll` at its landing speed, which is a different number —
    53% of the average on a 90 mph grounder, 8% on a 45 mph roller, and
    0.61-0.95 across the airborne shapes. Nothing was wrong with either
    model; they simply met at a step. The flight now decelerates onto the
    landing speed, so the two are one motion.
    """
    monkeypatch.setattr(ha, "_pick_hit_landing",
                        lambda *a, **k: (ha.HOME[0] + 150, ha.HOME[1] - 220))
    # Stubbing the landing is not on its own enough to pin this ball down.
    # A FLY whose carry reaches `WALL_REACH_FT` becomes a wall candidate, and
    # that branch never calls `_pick_hit_landing` — it aims its own landing
    # past the fence, and the in-flight detector then kills the arc at the
    # wall. Both samples below would sit past the end of a flight that
    # already ended, `flight_end` came out 0.0, and the test died dividing by
    # it on 7% of RNG seeds — the same shape of ordering-dependence as the
    # one `exit_velocity_mph` had. Put the fence out of reach: this test is
    # about the ordinary flight-to-roll handoff, not about the wall.
    monkeypatch.setattr(ha, "WALL_REACH_FT", 1e9)
    anim = _make(shape, quality=0.85)
    assert not anim._is_wall_candidate
    flight_end = _flight_end_px_ms(anim, monkeypatch)
    anim._init_ball_on_ground()
    roll_start = math.hypot(*anim._ball_v)
    assert roll_start == pytest.approx(flight_end, rel=0.02), (
        f"{shape} changes speed by {100 * (1 - roll_start / flight_end):.0f}% "
        "at the landing transition")


def test_deceleration_costs_the_flight_neither_time_nor_distance():
    """`p(u)` is a redistribution, not a retiming. Both ends are pinned, so
    `flight_time_s`, `duration_ms` and every whole-flight schedule built on
    them mean exactly what they did — which is what makes this safe to
    apply under a model calibrated on the full path."""
    for f in (0.0, 0.08, 0.53, 0.95, 1.0):
        assert ha._decel_path_fraction(0.0, f) == pytest.approx(0.0)
        assert ha._decel_path_fraction(1.0, f) == pytest.approx(1.0)
        # Monotone: the ball never stops or backs up partway down the path.
        seen = [ha._decel_path_fraction(i / 50.0, f) for i in range(51)]
        assert all(b >= a for a, b in zip(seen, seen[1:]))
        # And the inverse really is one.
        for s in (0.05, 0.3, 0.5, 0.77, 1.0):
            assert ha._decel_path_fraction(
                ha._decel_time_fraction(s, f), f) == pytest.approx(s, abs=1e-9)


def test_a_grounder_leaves_the_bat_at_its_exit_velocity():
    """The check that this is physics and not an easing curve.

    `ground_roll.grounder_landing_fraction` derives the end-of-path speed
    from `infield_timing`'s retention curve by assuming a uniform
    deceleration whose time-average is `r * v0`. Flying that profile
    should therefore put the ball's speed at contact back at exactly the
    exit velocity — and it does, without anywhere in the chain being told
    to.
    """
    for ev in (45.0, 70.0, 90.0, 105.0):
        f = ground_roll.grounder_landing_fraction(ev)
        v_avg = ev * infield_timing.ground_speed_retention(ev)
        # dp/du at u = 0, in units of the average speed.
        implied_v0 = (2.0 - f) * v_avg
        assert implied_v0 == pytest.approx(ev, rel=1e-9)


def test_the_defense_is_timed_against_the_flight_the_ball_flies(monkeypatch):
    """`_path_intercept` used `t_proj * duration_ms` — the linear schedule.
    A decelerating ball is ahead of that everywhere in between, so an
    infielder was being told they had time on a ball already past them."""
    monkeypatch.setattr(ha, "_pick_hit_landing",
                        lambda *a, **k: (ha.HOME[0] + 40, ha.HOME[1] - 300))
    anim = _make("GROUNDER", quality=0.85)
    assert anim._flight_end_speed_ratio < 0.95, "no deceleration to test"
    for role in ("2B", "SS", "3B", "1B"):
        info = anim._path_intercept(anim.fielders[role])
        px = anim._hit_end[0] - ha.HOME[0]
        py = anim._hit_end[1] - ha.HOME[1]
        t_proj = ((info["point"][0] - ha.HOME[0]) * px
                  + (info["point"][1] - ha.HOME[1]) * py) / (px * px + py * py)
        if not 0.02 < t_proj < 0.98:
            continue
        assert info["ball_arrives_ms"] < t_proj * anim.duration_ms
        assert info["ball_arrives_ms"] == pytest.approx(
            anim._flight_time_fraction(t_proj) * anim.duration_ms, rel=1e-9)


def test_the_throw_the_player_sees_is_the_throw_that_decided_the_play():
    """"Never let the verdict contradict the picture." A throw from deep in
    the hole has to visibly take longer than one from on top of the bag, and
    longer by the amount that lost the runner."""
    seen = []
    for i in range(120):
        anim = _make("GROUNDER", quality=0.5 + (i % 40) / 80.0)
        t = 0
        while not anim.finished and t < 25000:
            t += 16
            anim.update(t)
        if anim.play_timing is not None and anim._go_throw_ms:
            seen.append((anim.play_timing.throw_flight_s, anim._go_throw_ms))
    assert seen, "no throw to first was played"
    for real_s, anim_ms in seen:
        assert anim_ms == pytest.approx(
            ha.PRESENTATION_TIME_SCALE * 1000.0 * real_s, rel=1e-6)


def test_reaction_delays_are_real_latencies_projected_onto_the_animated_clock():
    anim = _make()
    for f in anim.fielders.values():
        assert f.reaction_delay_ms == pytest.approx(anim._anim_ms(f.reaction_delay_s))
        assert f.break_delay_ms == pytest.approx(anim._anim_ms(f.break_delay_s))
    # The pitcher's follow-through bias is real seconds, and now means it.
    p = anim.fielders["P"]
    assert p.reaction_delay_s - p.break_delay_s == pytest.approx(
        ha.ROLE_REACTION_BIAS_S["P"])


def test_flight_time_agrees_with_the_pure_model():
    """The animation must not re-derive flight time — that is how two
    clocks start again."""
    for shape in ("GROUNDER", "LINER", "FLY"):
        anim = _make(shape, quality=0.82)
        landing_ft = ha._ft_dist(anim._hit_end[0] - ha.HOME[0],
                                 anim._hit_end[1] - ha.HOME[1])
        expected = ball_flight.flight_time_s(
            shape, anim.exit_velocity_mph, landing_ft)
        assert anim.flight_time_s == pytest.approx(expected, rel=1e-9)


def test_a_batted_ball_has_exactly_one_exit_velocity(monkeypatch):
    """`contact_audio.exit_velocity_mph` jitters on purpose, so identical
    swings don't sound identical. That makes it something a play must draw
    *once*: carry, hang time, wall candidacy and the infield verdict were
    each calling it separately, so one ball could be given a 380 ft carry
    and the hang time of a 340 ft one. Same "two models of one thing"
    mistake as the two clocks, one scale down.

    Counted at the source rather than inferred from the landing. Inferring it
    meant asserting that the landing matches the EV-derived carry, and the
    landing passes through two clamps on the way out — the shape's
    `IN_PLAY_LANDING_FT` range and `_clamp_inside_wall` — so the comparison was
    really testing the clamps and happened to depend on the global RNG's state,
    and therefore on test ordering. Both clamps bite hardest at the top of the
    quality range, where a ball carries past a range that stops at 365 ft
    because whether it cleared the fence was already settled by an independent
    HR roll (the fault in §8 of docs/infield-timing-refactor.md). None of that
    is what this test is about.
    """
    draws = []
    real = ha.contact_audio.exit_velocity_mph

    def counted(*a, **kw):
        draws.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(ha.contact_audio, "exit_velocity_mph", counted)
    anim = _make("FLY", quality=0.9)
    assert len(draws) == 1, f"exit velocity drawn {len(draws)} times, not once"

    # And everything downstream is that one number: the hang time belongs to
    # where the ball actually landed, at the speed it was actually struck.
    landing_ft = ha._ft_dist(anim._hit_end[0] - ha.HOME[0],
                             anim._hit_end[1] - ha.HOME[1])
    assert anim.flight_time_s == pytest.approx(
        ball_flight.flight_time_s("FLY", anim.exit_velocity_mph, landing_ft),
        rel=1e-9)

@pytest.mark.parametrize("shape", sorted(ha.IN_PLAY_LANDING_FT))
def test_the_landing_range_is_a_range_and_not_an_inverted_pair(shape):
    """`IN_PLAY_LANDING_FT` has to actually bound the landing.

    The window was built as
    `uniform(max(dist_min, mid - spread), min(dist_max, mid + spread))`, and
    the two bounds cross over as soon as `mid` sits more than `spread`
    outside the range. `random.uniform(a, b)` does not care which way round
    its arguments are — it samples `[b, a]` — so at exactly the point the
    clamp was needed it inverted into its own opposite and put the ball
    outside the range on the far side.

    Measured over the real quality distribution before the fix: 62% of
    POP_UPs cleared their 160 ft cap and landed as far as 272 ft — a pop-up
    in the outfield — with 8.9% of FLYs past 365 ft (out to 416) and 4.3% of
    LINERs short of their 130 ft floor. Sweeping quality edge to edge here
    rather than sampling it, because this is a statement about the bound
    holding everywhere, not about how often it is reached.
    """
    dist_min, dist_max = ha.IN_PLAY_LANDING_FT[shape]
    seen = []
    real = ha._polar_point_ft

    def record(angle, dist_ft):
        seen.append(dist_ft)
        return real(angle, dist_ft)

    ha._polar_point_ft = record
    try:
        for i in range(201):
            q = i / 200.0
            for ev in (40.0, 70.0, 95.0, 110.0, 125.0):
                ha._pick_hit_landing("IN_PLAY", shape, quality=q, ev_mph=ev)
    finally:
        ha._polar_point_ft = real

    assert seen
    assert min(seen) >= dist_min - 1e-6, (
        f"{shape} landed {min(seen):.0f} ft, short of its {dist_min} ft floor")
    assert max(seen) <= dist_max + 1e-6, (
        f"{shape} landed {max(seen):.0f} ft, past its {dist_max} ft cap")
