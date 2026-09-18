# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

StrikeFactor is a pygame-ce baseball batting simulator. The player bats against AI pitchers (Sale, deGrom, McClanahan, Yamamoto, Sasaki). Pitches use Statcast-style physics, the bat is a 3D contact model, and a top-down fielding simulation decides what happens to each ball in play. There are three modes: Arcade, GameDay (a full 9-inning game) and Sandbox.

**Module docstrings and the comments above constants record the rationale, the measurements and the past bugs behind the code, and they are thorough.** Read them before you change a module. This file covers the rules that apply across modules and where things live. It does not repeat the docstrings.

## Running and development

The project is managed with **uv**. `uv run` syncs `.venv` to `uv.lock` before it runs anything, so you never need to activate it.

```bash
uv run strikefactor                   # play (also: uv run python -m strikefactor)
uv sync                               # set up / update .venv: runtime + dev group, editable install

uv run pytest                         # ~1200 tests, headless, parallel; ~20 s on 12 cores
uv run pytest -n0                     # serial: needed for a debugger, -s, or a single test
uv run ruff check .                   # currently green; keep it that way
uv run python -m tools.calibrate_defense --n 2500 --by-shape   # ball-in-play calibration sweep (~75 s)
uv run python pitch_analysis.py       # offline analysis (see Analysis package)
```

- **Dependencies.** Declared in pyproject.toml: `[project.dependencies]` for runtime, `[dependency-groups] dev` for pytest, xdist and ruff. `uv.lock` pins exact versions and is committed; change dependencies with `uv add` / `uv remove` / `uv lock --upgrade-package X`, never by hand. `.python-version` pins 3.12. The pip fallback is `pip install -e . --group dev` (pip ≥ 25.1).
- **scikit-learn is pinned (`~=1.4.2`) to the release `ai_umpire.pkl` was pickled with.** Unpickling under any other version raises `InconsistentVersionWarning`. Re-save the pickle before you move the pin.
- **Package layout.** `strikefactor` is a package whose modules import each other as `strikefactor.<module>`, so the repository root must be on `sys.path`; the editable install handles that. Running `python strikefactor/main.py` directly does not work.
- **Launching the game writes data.** On shutdown it re-saves the `ai/*_ai.pkl` Q-tables and `data/batting_stats.json`. Don't launch it to smoke-test a change unless you mean to touch those files.
- The deferred ruff rules (`B`, `UP`, `E731`) are listed in a comment in pyproject.toml.
- tests/conftest.py switches SDL to its dummy drivers before pygame is imported, so the tests need no display. `addopts` runs `-n auto --dist worksteal`. See the pyproject comment for why it is `worksteal`.
- **A few Monte Carlo fielding tests take almost all of the test runtime** (test_infield_hit_verdict.py, test_defense.py). Nearly every other test finishes in under 5 ms, so removing tests will not make the suite faster. Don't change a Monte Carlo test's `n` in either direction. The bands are calibrated against MLB rates, and several sit within about 2.5σ.
- Deterministic sweeps are memoized and shared between tests. In test_defense.py, `_sweep` also serves prefixes of a longer sweep. Tests that share a sample share the same *objects*, so a test that mutates an animation (for example by moving its clock) must restore it; that is what `_scratch` does.
- `tools/` is dev tooling and is not part of the installed package (`packages.find` covers only `strikefactor*` and `analysis*`). pytest's `pythonpath = ["."]` is what lets tests import `tools.sim`.
- **Pickled AIs:** the `ai/*_ai.pkl` Q-tables were pickled under a legacy module path (`ai.AI_2`), and ai/compat.py remaps it when they load. If loading fails, `PitcherManager._load_ai` falls back to a fresh AI, so a broken path silently throws away the training. tests/test_ai_pickles.py guards against this.

## Rules that apply everywhere

Most bugs in this project's history broke one of these rules.

1. **Physics uses real units** (feet, seconds, mph, degrees). Pixels and milliseconds appear only at render seams: `HitAnimation._anim_ms` / `_travel_ms` / `_ft_dist` / `_fts_to_px_ms`, and `HitOutcomeManager.contact_metrics` for the vertical offset. Be suspicious of any constant that decides an outcome and is stated in px or ms. Ask whether a person could state it in feet or seconds. Several bugs were pixel constants whose comments assumed a stale scale. The field projection is anisotropic (`FT_TO_PX_X = 1.85`, `FT_TO_PX_Y = 1.10`), so one px/ms speed means two different real speeds.
2. **Each quantity has one model, and each random value is drawn once.** A batted ball has exactly one exit velocity, drawn in `PitchSimulation._evaluate_contact` and passed to the animation, the audio, the DB and the replay. It also has one bearing (`Contact.spray_deg`), one launch angle and shape, and one flight arc (`ball_flight.height_at_distance_ft`). Never recompute or re-roll any of these downstream. "Two models of one thing" is the most common defect in this codebase.
3. **Decisions read the physics, never the picture.** Catch gates, fence checks and fielder distances use the ball's ground (shadow) position and its height in feet. They never use the drawn, lifted ball.
4. **Contact quality is not uniformly distributed.** It exists only for swings that squared the ball up, so it skews high (p25/p50/p90 ≈ 0.72/0.81/0.94). Never tune against a `range(0, 1)` sweep. Use `tools/sim.py` instead: `realistic_contact` is the joint quality and launch-angle draw, and `realistic_spray` samples direction. You can also key off exit velocity. A `HitAnimation` built without `spray_deg` sends every ball to dead centre, so any sweep must pass one.
5. **A contact-geometry change invalidates recorded play and the quantile anchors.** This applies to any change that alters which contacts are fair or how quality is distributed: the bat model, `bat_contact`, `spray`, or the foul threshold. After such a change, archive and clear recorded play with `python -m strikefactor.data.reset_tracking`, then re-derive all of these together:
   - `contact_audio.EV_CALIBRATION`
   - in `tools/sim.py` (re-exported by tests/conftest.py): `QUALITY_QUANTILES`, `QUALITY_BY_SHAPE`, `LAUNCH_ANGLE_QUANTILES`, `SPRAY_MEAN_DEG` / `SPRAY_SD_DEG` and `BATTED_BALL_MIX`
   - the mirrors of those in tests/test_infield_hit_verdict.py, which drift tests pin to the originals

   strikefactor.db holds rows from several geometry vintages. Calibrate against the simulator, not against raw recorded rates.
6. **A rate that matches MLB does not prove the model is right.** 2B/1B was on target twice because an artifact happened to cancel an error. When a change moves a rate, check the per-shape breakdown (`--by-shape`) and the controls. An airborne-only change must leave GB-hit%, IF-hit% and ERR% identical.
7. **Outcome strings come from `strikefactor/outcomes.py`.** They are matched by exact string in many places that fail silently: an at-bat never closes, a plate appearance drops out of AVG, or an error is credited as a hit. Build new groups by composing the ones in outcomes.py; don't enumerate strings.
8. **DB columns: never coalesce NULL, never back-fill, and never widen what an existing column means.** NULL means either "it didn't happen" (no contact means no spray; no play means no fielder or margin) or "the row predates the column". To record something new, add a column, bump `SCHEMA_VERSION` and migrate in `PitchDB._migrate`.
9. **Handedness and frames.** World `+x` is the third-base side. The code is correct here, and the `pitch_physics` docstring's "catcher's right" is wrong. The hit animation uses `field_x = -world_x`, with the foul lines at 45°/135°. Spray is pull-positive for both hands, and `spray.field_angle_deg` / `world_direction` are the only conversions out of that frame. A sign error mirrors the batter, so test every directional claim for both hands.
10. **Test hygiene.**
    - `test_*_are_gone` tests pin removed constants. Don't reintroduce those names.
    - A test that can fail only on exact float equality is not a test. Measure a rate instead.
    - To check a guarantee, assert on the extreme deterministic case rather than on a random sample.

## Architecture

### Core loop and game states
`Game` (main.py) owns these managers:
- `GameStateManager`
- `PitcherManager` (pitchers and their AIs)
- `AssetManager`
- `UIManager` (pygame_gui)
- `SoundManager`
- `ChallengeManager`
- `BatterProfile`
- the three HUDs
- the `PitchDatabaseService` singleton

States live in gameplay/game_states.py. Each extends `GameState` (`enter` / `exit` / `update` / `handle_event` / `render`) and is registered in `GameStateManager._initialize_states()`.

```
ModeSelectState
 ├── ARCADE  → MenuState (pitcher pick; settings + key bindings are sub-modes) → GameplayState → InningEndState → SummaryState
 ├── GAMEDAY → GameDayState (PitcherCarousel) → GameplayState ⇄ GameDayTransitionState   (+ GameDayResumeState, GameDayHistoryState)
 └── SANDBOX → SandboxMenuState → SandboxGameplayState
```

Arcade and GameDay share `GameplayState`. `VisualizationState` is the T-key pitch-flight view, and `Game.toggle_track` swaps it in and out. `ViewPitchesState` is legacy; V now opens Review.

### Pitchers and pitch selection (pitchers/, ai/)
- **Arsenals.** `Pitcher` (pitcher.py) is the base class, and each concrete pitcher is in its own file (Sale.py and so on). Each pitch is a method that draws `speed_mph`, `pfx_x` and `pfx_z` (inches of break), takes `target_x, target_y = self.get_pitch_target(type)` and calls `simulation_func(release_point, name, speed_mph, pfx_x, pfx_z, target_x, target_y, pitch_type)`. Methods are registered with `add_pitch_type`.
- **Choice: which pitch.** The AI makes this choice. `ERAI` (ai/AI_2.py) is epsilon-greedy Q-learning over the count, outs, runners and previous pitch. It is blended with the real usage priors in ai/pitch_priors.py, which are validated against each arsenal at startup. It also consults `BatterProfile` (ai/batter_profile.py): the player's swing tendencies by zone quadrant, pitch type and count, persisted per (mode, difficulty) in the DB.
- **Location: where it goes.** `get_pitch_target` works in three steps:
  1. `_choose_intent` picks zone, edge, chase or waste from `INTENT_TABLE` by count state.
  2. It picks a named archetype from data/pitch_locations.json via pitch_locations.py. Lookup tries pitcher → pitch → platoon, then falls back to the defaults.
  3. `_execute` applies command error (`pitch_command`).

  The result is recorded as a `PitchIntent` on `last_intent`.
- **At-bat plans** (at_bat_plan.py) give each plate appearance a through-line. A plan is rolled when `game.pitchnumber == 0` and held on `Pitcher.plan` until the at-bat ends. A plan never chooses the pitch. Per phase (`get_ahead` / `put_away` / `behind`), it multiplies the intent probabilities. It also pulls archetype weights by `exp(pull_x·in_away + pull_z·height)` in batter-relative coordinates, optionally per pitch class. The plans (`ladder`, `east_west`, `jam_then_expand`, `steal_early`) and each pitcher's mix of them (`_plans`) are data in pitch_locations.json. Averaged over the mix, the intent mix stays at the book value; the variety shows up *between* at-bats. tests/test_at_bat_plan.py pins both properties. A plan can pull only toward archetypes that exist. The plan's name is carried on `PitchIntent.plan`; it is not yet a DB column.

### Pitch physics and the umpire
- `utils/pitch_physics.py`: `PitchTrajectory` is the Statcast 9-parameter constant-acceleration model, built by `from_pitch_params` from speed, pfx and target. `UmpireCamera` projects it to the screen. `position_at(t)` and `time_at_depth(y)` are the clock the rest of the game reads.
- `PitchSimulation` (gameplay/pitch_simulation.py) runs the sequence: windup → flight → swing → contact or miss → hit animation.
- Ball/strike calls come from `ai_umpire.pkl`, an SVC loaded through `get_umpire_model()`. Unpickling it imports sklearn, which takes about 680 ms, so gameplay/prewarm.py loads it (and pandas) on a daemon thread from `Game.__init__`. **Keep that import lazy.** Moved to module level, it freezes the first called pitch mid-swing and puts sklearn on the tests' import path.
- `utils/physics.collision` (circle against rect) is used only for the ABS zone-truth test.

### Swing and contact (bat_path.py, bat_contact.py, hit_outcome_manager.py)
The bat is one 3D object swung by one model. Contact asks one question: do two solids intersect?
- **`bat_path` gives the bat's position at every instant, in feet and seconds.**
  - The swing depends only on the player's aim and handedness, never on the pitch. `test_the_swing_does_not_depend_on_the_pitch` pins this.
  - The engine's aiming pivot (`HitOutcomeManager.rhpos`) is the hands. The contact pose is *solved* from a quadratic (`_contact_pose`), so contact depth is an output. When no pose reaches the ball, `_reach` takes the quadratic's vertex.
  - A cursor is a ray (`_unproject`), not a point.
  - `SWING_DURATION_MS` (150) is the one swing duration. `PEAK_BAT_SPEED_MPH` is a calibration target.
  - The swing continues past contact (`EXTENSION_DURATION_MS`), and the sweep uses that part too.
  - `BAT_PROFILE_IN` is the real bat's radius profile. Both the sweep and the replay sample `bat_solid_point`, so the bat that is graded and the bat that is drawn are the same object.
- **The whole swing is decided when the key goes down** (`PitchSimulation._handle_swing_input`). The bat is built from the cursor at that moment and swept against the pitch's trajectory immediately. It cannot be re-aimed mid-swing.
- **`bat_contact.aim_at_pitch` moves the cursor to the barrel's depth.** The player aims at a ball drawn at the plate, but the barrel meets it about 2 ft out front, where the ball is 2–5 in higher. Without this step, perfectly aimed swings fouled. Anything else that gains a depth axis has to answer the same question.
- **`resolve_contact`** works in three steps:
  1. It slides the swing in time by up to `timing_assist_s`, then sweeps.
  2. On a near miss, it translates the bat in x/z by up to `spatial_assist_ft`.
  3. It then requires a real intersection.

  **Every forgiveness moves the bat, and none makes it wider**, so the replay can draw every contact honestly. Borrowed time and space are charged back into quality through `timing_score` and `spatial_score`. Quality is the geometric mean of the sweet-spot, centre and timing scores, multiplied by the spatial score.
- **Timing error shows up first as where on the bat the ball is struck and as spray direction.** An early swing puts the ball toward the tip (`along` → 1) and a late one toward the handle. Quality falls only once the ball is off the barrel or the assist has been spent.
- **A ball can be foul in two independent ways** (`Contact.is_foul`): `quality < foul_threshold` (tipped, topped or off the handle), **or** `spray.is_foul(spray_deg)` (past a pole). `FOUL_QUALITY_THRESHOLD` and `spray`'s location term are tuned together so that total fouls stay at about 48% of contact. If you move one, re-measure the other.
- **Difficulty.** `settings_manager.DIFFICULTY_MULTIPLIERS` values are converted in bat_contact. The gameplay layer reads them only through `HitOutcomeManager.contact_multipliers` / `resolve_aim` / `_foul_threshold`.

  | Multiplier | Reaches | ROOKIE → HALL_OF_FAME |
  |---|---|---|
  | `aim_assist` | fraction of the aim error that `aim_at_pitch` removes (radial cap `MAX_ASSIST_FT`) | 0.90 → 0.20 |
  | `contact_timing_window` / `power_timing_window` | `timing_assist_s` (26 ms base), the charge width, and `foul_threshold` | 39 → 10 ms; threshold 0.48 → 0.72 |
  | `contact_zone_size` | `spatial_assist_ft` (0.20 ft base; −0.035 ft on a power swing) | 1.4 → 0.7 |
  | `out_probability_modifier` | seconds on the runner's clock (`DIFFICULTY_SECONDS_PER_MODIFIER`) | −0.15 → +0.30 s |

  - `aim_assist` is the only dial that turns more swings into balls in play, because it raises quality. The other dials mostly turn whiffs into fouls.
  - Multipliers *scale* base constants and never offset them. An offset once made AMATEUR's tolerance exactly zero.
  - The timing charge is never narrower than its budget. Otherwise easier settings charge more (`test_the_charge_is_never_narrower_than_the_budget_it_charges_for`).
  - `spray` has no difficulty dial and must not get one. Difficulty reaches direction only through the timing error that the assist leaves.
  - `foul_ball_chance` and `strike_zone_tolerance` are defined in the table but read by nothing.
- **Difficulty values are stamped on the swing when it is committed** and carried on `SwingRecord` (`aim_assist`, `zone_size_mult`, `timing_window_mult`). The replay never re-reads them.
- `on_time` (0 whiff / 1 foul / 2 fair) is `swing_verdict(contact)`: the geometry's verdict, not a timing grade.
- The sweep runs within an input frame, so `_closest_along` must stay analytic. A test guards its cost.
- Recorded swings run about 19 ms late, which is human reaction time. The assist is symmetric on purpose.

### From contact to verdict: the batted-ball modules
These are pure modules on the contact_audio.py pattern: no pygame, no game state, real units. They are listed in the order a batted ball goes through them. docs/infield-timing-refactor.md sources the constants.
- **hit_outcome_manager.`hit_outcome`** classifies the batted-ball type and asks `park.fence_verdict` whether the ball is a home run. Everything else is `IN_PLAY` and emerges from the fielding simulation; there are no outcome-probability tables. Difficulty reaches the ball only as runner seconds, and `momentum_bonus` only as exit velocity (`MOMENTUM_EV_MPH_PER_UNIT`).
- **ball_flight.py:**
  - **Launch angle** comes from the contact normal: `vertical_offset_ft` → `launch_angle_deg`, with jitter truncated at `JITTER_LIMIT_SIGMA` so that a bat over the ball never produces a fly ball. Contact quality is deliberately *not* an input.
  - **Shape** is banded at the Statcast cuts: GB <10°, LD 10–25°, FB 25–50°, PU >50° (`shape_for_launch_angle`).
  - **Flight** depends only on launch angle and EV: `carry_distance_ft`, `flight_time_s`, `height_at_distance_ft`. Shape is a classification, not a flight input. `launch_angle_for_shape` returns the band centre for callers that have only a shape.
  - `DRAG_RANGE_ANCHORS`, `DRAG_HANG_ANCHORS` and `DRAG_APEX_ANCHORS` are fitted to the same integrated flights. **Re-derive all three or none.**
- **park.py:**
  - The fence is 360 ft down the lines and 400 ft to centre, deeper than MLB lines, so no home run carries less than 360 ft. `FENCE_HEIGHT_FT` is 12.
  - `fence_verdict` returns `OUT_OF_PARK`, `OFF_THE_WALL` or `SHORT_OF_WALL`. The verdict and the drawing use the same fence.
  - The fence must stay taller than a fielder's reach (`GLOVE_REACH_FT` = 8). The band between glove and rim is where doubles off the wall come from (`test_the_fence_is_taller_than_a_fielder_can_reach`).
  - **Don't move the fence to change the home-run rate.** The top rows of `EV_CALIBRATION` control that rate.
- **spray.py:**
  - Direction comes from the bat's bearing at contact, because the ball leaves perpendicular to the bat. The result is `Contact.spray_deg`, pull-positive.
  - Location and timing are calibrated separately:
    - `LOCATION_GAIN` is bounded so that a flawless swing is fair anywhere in the zone (`test_a_flawless_swing_can_be_fair_anywhere_in_the_zone`).
    - The location term saturates through a tanh at `LOCATION_SPAN_DEG`.
    - `TIMING_GAIN` is the other term.
  - Spray is deterministic, with no jitter.
  - `foul_departure_deg` is the direction a foul actually leaves in. It is always foul, continuous with `spray_deg` at the line, and never straightened. A popped-up foul goes behind the plate.
- **batted_ball_path.py** adds a bounded lateral bend (sidespin) to the spray bearing, driven by `attack_deg − pose_attack_deg`.
  - Maximum drift is 2/12/18/8 ft for GB/LD/FB/PU.
  - It never changes carry, and it never flips a fair/foul or home-run call already made upstream.
  - Rendering, the shadow, interception, wall collision and `ground_roll`'s starting tangent all use this one path.
  - `HitAnimation.handedness_sign` is a coordinate mirror, not spin.
- **ground_roll.py** handles everything after the first landing.
  - Every ball lands at about terminal speed (`LANDING_SPEED_MPH`).
  - A bounce is an impulse calculation that depends on the descent angle, and hops are real projectile arcs.
  - Friction applies only while the ball is on the ground. `GRASS_ROLL_DECEL_FT_S2` is the calibration dial; `ROLL_AIR_DRAG_PER_FT` is physics, not a dial.
  - An untouched ball rolls 60–200 ft. Fielders end outfield plays, not friction.
- **infield_timing.py** races the throw against the runner to first. `HARD_PLAY_PROB` adds variance (hard plays), not bias. `roll_verdict` / `verdict_from(p_out, p_out_clean)` draw **once**: the window `[p_out, p_out_clean)` is exactly the set of plays a misplay cost, and those are the errors.
- **extra_bases.py** runs the same race one base further. `AGGRESSION_MARGIN_S` is load-bearing; without it, every gapper is a triple.

### Contact audio (engine/contact_audio.py, engine/sound_manager.py)
- **One entry point.** Every bat-on-ball event goes through `SoundManager.play_contact(quality, swing_type, ev_mph=, is_home_run=)`.
- **Samples are chosen by exit velocity, never by outcome.** The sound fires at impact, before the outcome is known.
  - A home run gets only a sample floor (`HOMERUN_MIN_SAMPLE`).
  - `HOMERUN_MIN_EV_MPH` hard-gates the top sample.
  - A foul that hooks past the pole is not a home run.
- **EV calibration.** `exit_velocity_mph` maps quality through `EV_CALIBRATION`, which pins the quality quantiles to MLB EV quantiles. The top rows (99.5/103/108 mph at p75/p90/p99) hold the home-run rate. A power swing adds `EV_POWER_BONUS_MPH` to the physics as well as to the sound; that constant is the dial if extra-base hits run hot.
- **Gain is set on the Channel, never on the Sound**, because Sounds are shared singletons. `master_volume` is applied here.
- **Foul contact metrics** are computed in `_handle_foul_ball` → `_compute_foul_contact_metrics`, not in the animation path gated by `foul_animation_enabled`.
- **Sounds are grouped by source:**
  - `sounds/contact/`: weak → medium → solid → hard → crushed.
  - `mitt/`: the catcher's mitt, used only by `glovepop()` and never in the contact ladder.
  - `umpire_sounds/`: scanned by directory for random variants.

  Keys describe the sound, never an outcome. tests/test_sound_manager.py guards all of this.

### Hit animation (gameplay/hit_animation.py, ~5100 lines)
The hit animation draws the top-down play, and it also **decides** in-play outcomes: out or hit emerges from whether a fielder reaches the ball. `PitchSimulation` reads `classified_outcome` when the animation finishes, and only then updates the score, runners and banner.

**Clock, height and flight**
- **One clock.** Physics runs in real seconds. `PRESENTATION_TIME_SCALE` (1.25) is the only place pacing departs from physics, and it is applied through `_anim_ms` / `_travel_ms`. tests/test_animation_clock.py guards this boundary.
- **One height model.** `_flight_height_ft(progress)` is `ball_flight.height_at_distance_ft` for this ball, and `_flight_lift_px` is the only place it crosses into pixels. Catch gates compare feet against `GLOVE_REACH_FT`. The only allowed disagreement between the picture and the flight is `_fence_lift_correction`, which accounts for the ball's radius against the rim.
  - **Exception:** a grounder's in-flight hops are still in pixels (`GROUNDER_BOUNCE_PROFILE`, `_arc_grounder`, `INTERCEPT_MAX_LIFT_PX`). This is the last height model in pixels; unifying it with `ground_roll` is open work.
- **The flight decelerates onto the landing speed** (`_decel_path_fraction`), so the flight and the roll are one motion. `_path_intercept` inverts that easing (`_decel_time_fraction`) rather than assuming linear time.
- **Landing.** Every airborne ball lands at `ball_flight.carry_distance_ft` along its bearing: in play, off the wall and home run alike, with no extra random spread. Only grounders use `IN_PLAY_LANDING_FT`.
- **After landing** the ball follows `ground_roll`, converted once in `_init_ball_on_ground`.
  - `_forecast_ball` / `_chase_target` let fielders charge the ball.
  - `_pick_retrieval_role` searches the ball's post-landing path and always routes an outfielder as backup.
  - Only a wall strike in flight forces an extra base (`_wall_hit_in_flight`), not a ball that rolls to the wall.

**Fielders**
- **Who fields it.** `FIELDER_HOMES` are static. The primary fielder is the eligible one with the least ground to cover, not the one with the earliest intercept.
- **Who may catch it.** Eligibility (`_eligible_intercept_pool`) depends on where the ball is going, not on its shape.
  - Only grounders keep a shape rule.
  - Outfielders may take pop-ups; P and C never do in fair ground.
  - The catch check runs **before** the wall-impact check.
- **Range.** Infielders have no range cap; time limits them. `ROLE_MAX_INTERCEPT_DIST_FT` (P, C) and `FIRST_BASE_GROUNDER_RANGE_FT` (the 1B owes the bag) are positional limits, stated in feet.
- **The pitcher** carries a follow-through reaction bias (`ROLE_REACTION_BIAS_S`) and a clean-fielding roll (`PITCHER_CLEAN_FIELD_PROB`).
- **Infield plays.**
  - Every fielded grounder goes through `_begin_infield_play`, which draws the throw and the cover man.
  - `_post_fielding` (a sub-animation owns the ball) is not `_secured_in_flight` (the ball never landed). Don't merge them.
  - `_resolve_extra_bases` runs before `_stand_down_non_primary`.
  - Cover at first follows a strict priority, `COVER_ROLE_PRIORITY = ["1B", "P", "2B"]`, within `COVER_IN_TIME_BUDGET_S`, counted from `_fielded_at_ms`.
  - `Fielder.break_delay_s` is separate from the fielding reaction bias.

**Wall**
- Fielders' bodies are kept inside the wall (`FIELDER_WALL_MARGIN_PX`); their targets may lie off the field.
- The out-of-park boundary is the fence itself (≥ 1.0 in normalized ellipse units), not `BALL_WALL_LIMIT_NORM`, which is where a rolling ball is held.
- A wall ball strikes the face at its physical height, falls (`_begin_wall_drop`), and caroms from `wall_r * BALL_WALL_LIMIT_NORM`.
- `_ball_behind_wall` hides a ball the fence hides, taking its height into account. `_wall_r_at` is a screen-space ellipse. tests/test_wall_containment.py guards this.

**Direction**
- `spray_deg` becomes `spray_field_rad` once, in `__init__`.
- `_screen_angle_of` is the one conversion from a real bearing to screen polar.
- `_fair_field_angle` insets by 0.5° rather than clamping.
- Keep `_polar_point_ft(angle, dist_ft)` called positionally; tests monkeypatch it.
- **Fouls** read `spray.foul_departure_deg`, resolved at the handoff. Their shape comes from `PitchSimulation._foul_shape`, which uses the same classifier as balls in play and is kept off `batted_ball_type`.

**Naming and readout**
- The shape names (`GROUNDER` / `LINER` / `FLY` / `POP_UP`) are a separate namespace from outcomes (`FLYOUT`, `POP UP`). They meet only where `classified_outcome` is assigned.
- The home-run distance is read from the actual landing and revealed just after it (`_hr_distance_alpha`).

### Defense, misplays and errors (gameplay/defense.py)
- **`DefenseProfile`** is a frozen set of physical quantities: sprint speed, reaction band, throw speed, release scale, misplay rates, `muff_recovery_s` and `through_turn_s`.
  - `profile_for(level)` accepts `sandlot` / `minors` / `league` / `gold_glove`, and anything else returns `NEUTRAL`.
  - It reaches the animation as `HitAnimation(defense=)` via `PitchSimulation._defense_profile()`. The animation does not look up settings itself, because fielding tests use stub games.
- **`LEAGUE` is exactly the neutral constants.** `defense=None` and `"league"` must produce identical plays and consume the RNG identically (`test_the_neutral_profile_changes_nothing_at_all`).
- **Dials:**
  - `field_misplay_p` sets the error rate. **Measure it with the harness; don't derive it.**
  - `body_block` sets how many balls a fielder reaches but lets through. Play difficulty degrades the block rather than scaling the through share.
  - `RANGING_FULL_FT` is `infield_timing.RELEASE_STRETCH_FT`, imported rather than restated.
  - `_runner_sprint_fts()` stays unscaled, because defense strength is not batter speed.
- **Misplays.** `_roll_misplay` makes one latched roll when a fielder first reaches the ball. There are three kinds:
  - **BOBBLE**: costs release time.
  - **THROUGH**: the ball carries on at its real speed. It fires only from `_check_in_flight_intercept`.
  - **MUFF**: the ball is dropped. This is the only way a ball somebody was under falls in, and it is scored as an error, never a hit. If balls fall in as *hits* with a fielder underneath them, an eligibility rule is wrong.
- **Charging the error.** `_charge_error(role)` is the only place `is_error` is set. It marks the fielder who misplayed the ball, not `_primary_role`, with a brief amber "!" (`_error_mark_alpha`).
- **`REACHED ON ERROR` is neither a hit nor an out.** It belongs to the REACH / IN_PLAY / TERMINAL groups, not HIT / BATTED_OUT / OUT.
  - The banner says `ERROR` through `PitchSimulation._DISPLAY_NAMES`; the stored value is unchanged.
  - `GameStats.outcome_value`, the Q-learning reward scored from the pitcher's side, counts it close to an out.

### Outcome vocabulary (strikefactor/outcomes.py)
This module is the single definition of:
- the outcome strings
- the composed groups (HIT / BATTED_OUT / REACH / IN_PLAY / OUT / TERMINAL)
- `HIT_BASES`
- display names
- colours (`COLORS`, `OUT_COLOR`, `HIT_COLOR`, `ERROR_COLOR`)
- `db_key`, the only producer of the underscored form

It imports nothing. `analysis/theme.py` deliberately keeps its own copy, because the analysis package must read an archived DB without the game installed. tests/test_outcome_names.py pins the copies together and checks that consumers derive their sets rather than enumerating them.

### Calibration harness (tools/) and current state
- **tools/sim.py** is the headless ball-in-play simulator plus the batter model that the tests share (conftest.py re-exports it).
- **tools/calibrate_defense.py** sweeps the defense ladder.
  - The harness forces `IN_PLAY` and reads HR% from `park.fence_verdict`. It sets home-run balls aside so BABIP is a real BABIP.
  - `--by-shape` gives the axis that is independent of fielding.
  - Tune at n ≥ 2500. Test bands are deliberately wider than the harness numbers.

Measured 2026-09-18 (`--n 2500 --seed 808`), LEAGUE:

| HR% | BABIP | ERR% | GB-hit% | IF-hit% | 2B/1B | GROUNDER | LINER | FLY | POP_UP |
|---|---|---|---|---|---|---|---|---|---|
| 4.08 | .246 | 1.04 | 27.4 | 6.3 | 0.23 | .274 | .482 | .061 | .000 |
| *MLB ~4.5–5* | *~.290* | *~1.5* | *~24* | *6–8* | *~0.33* | *~.24* | *~.68* | *~.12* | *~.02* |

Across the ladder, BABIP runs .341 / .277 / .246 / .207 and ERR% runs 3.38 / 2.04 / 1.04 / 0.42.

**Next calibration item:** liners and flies land where the static `FIELDER_HOMES` outfielders stand, so LINER, FLY, BABIP and 2B/1B all run low. The fix is a two-variable fit: outfield alignment (`FIELDER_HOMES`) against per-shape exit velocity (`QUALITY_BY_SHAPE`), not a single-dial pass. Power swings run about 10% HR; `EV_POWER_BONUS_MPH` is the dial for that.

### Review workspace: V / R / F (docs/unified-review.md)
- **Entry.** V (pitches), R (swing) and F (fielding) all open one modal `ReviewOverlay` through `Game.request_review(view=...)`. T is not part of Review; don't fold pitch flight into it.
- **Joining.** `ReviewStore` joins pitch points, `SwingRecord` and `FieldingRecord` by an ID allocated when the pitch is created. Never join on the `last_*` aliases.
- **Publishing.** `PitchSimulation._publish_review` has no gameplay side effects and is idempotent. It runs after a play finalizes and before Continue, or at cleanup for an unanimated result.
- **Modal and playback.**
  - `review_modal.run_modal` owns input isolation and paused deadlines. The outer loops discard the event batch from before the modal opened.
  - Fielding review plays back immutable frames and never calls `HitAnimation.update`. Retention is bounded by frame count and clip count.
  - Replay transports don't depend on the display FPS.
- **Legacy code.** A compatibility wrapper may keep an *entry point* alive (`request_swing_replay`, `_run_swing_replay_loop`, `StatSwing`). It may never keep a second renderer alive.

### Swing record and swing replay
**swing_record.py `SwingRecord`** holds the `PitchTrajectory` object itself, not samples.
- **Two instants.** `bat_arrival_s` is when the barrel reached its contact pose; timing readouts and `signed_timing_ms` use it. `contact_time_s` is when the sweep found bat and ball closest; anything drawn uses it.
- **Timing datum.** Timing is measured against the ball reaching the barrel's own depth, not the plate.
- **Aim.** `resolved_aim_ft` is stamped at commit and preferred. `swing_aim_ft()` re-runs `aim_at_pitch` with the carried `aim_assist` only for records that lack it.
- **The drawn bat is the swept bat.** `swing_launch_s` includes `Contact.shift_s`, and `spatial_shift_ft` is applied through `bat_path.translated_swing`.
- **Timing windows.** `timing_windows_ms` comes from re-sweeping this particular swing, so it is asymmetric. It is warmed at trigger, not lazily.
- **Depth is unclamped.** A miss's clip runs on to the plate (`clip_end_s`).

**ui/swing_replay_overlay.py** is drawn in the `gameday_theme` style.
- **Cameras.** SIDE and OVERHEAD project from world feet through `_project`, which orients each axis like a real camera. SIDE films from the batter's open side (`_side_camera_x`). OVERHEAD puts 3B on the left.
- **Scale.** Each view has one isotropic scale (`_fit_isotropic`).
- **Playback.** The clip freezes at contact with no tail and plays at one slow-motion rate (`_REPLAY_MS_PER_PITCH_S`).
- **What is drawn.** The spray ray is the animation's own `flight_path` along `departure_or_spray_deg`. The ghost is the same swing at a different phase (`bat_state_at_ball_arrival`).

tests/test_swing_replay.py pins the cameras, the panel containment, and that the bat and ball actually touch.

### ABS challenges, HUDs, Sandbox
- **ABS.**
  - `ChallengeManager` tracks challenges per side (`CHALLENGES_PER_SIDE`). A successful challenge is retained; Sandbox has unlimited challenges.
  - `ABSChallengeOverlay` runs its phases: intro → 2D replay → zoom → CONFIRMED/OVERTURNED.
  - The feature is gated by `abs_enabled`. The flow in main.py is `request_abs_challenge` → `_run_abs_overlay_loop` → `_reverse_last_call`.
- **HUD.** `hud_mode` is one of `legacy` (Scorebug), `broadcast` (BroadcastHUD) or `minimal` (MinimalHUD). `Game.toggle_hud_mode` cycles it and `Game._draw_active_hud` dispatches. The palette is black, white and gray only.
- **Sandbox.**
  - The player picks each pitch (`UIManager.update_sandbox_pitch_buttons`).
  - Laps persist to data/lap_history.json and show in `LapLogPanel`.
  - `RandomScenarioGenerator` provides themed starting states.

### GameDay (gameplay/gameday_manager.py)
- **`GameDayManager`** covers:
  - innings and the opponent's at-bats (`simulate_opponent_at_bat` / `_get_adjusted_probabilities`, which account for fatigue, momentum and clutch)
  - bullpens for both sides, configured from data/pitcher_attributes.json via `get_pitcher_attrs`
  - walk-offs (`check_walkoff`)
  - the box score (`get_box_score_lines` → `gameday_theme.draw_linescore_from_arrays`)
  - history (data/gameday_history.json)

  `PitcherStats` tracks each arm.
- **Resume.** Resuming reattaches the DB game (`PitchDatabaseService.resume_game`), so one logical game keeps one `game_id`.
- **UI.**
  - `PlayByPlayPanel` is the filterable log.
  - `PitchingBoxPanel` is the second GAME LOG tab. It shows every arm on both staffs, scrolls rather than truncating, and receives role and hand tags as data. `format_ip` / `format_era` live in the panel.
  - Chip rows share `gameday_theme.draw_chips`. The log tabs sit just outside `_LOG_RECT`, so hit-test them before the click-outside-to-close check.
- **Maintenance.**
  - `python -m strikefactor.data.gameday_maintenance --list` archives, resets and restores GameDay data. GameDay lives in three stores (history JSON, sessions JSON, and the `game_mode='gameday'` DB rows); every operation must cover all three.
  - `python -m strikefactor.data.reset_tracking` archives and clears **all** recorded play (`--dry-run`, `--restore`). It deletes rows rather than tables, keeps `user_version`, and gives snapshot directories unique names.

### Settings, key bindings, UI
- **`SettingsManager`** (settings.json) stores `difficulty` (ROOKIE … HALL_OF_FAME), `umpire_sound`, `master_volume`, `show_strikezone`, `batter_handedness`, `display_mode`, `display_fps`, `engine_fps`, `abs_enabled`, `foul_animation_enabled`, `hud_mode` and `defense_strength`. `DEFENSE_LEVELS` and `HUD_MODES` are plain string lists because settings must not import gameplay; tests pin them to the enums.
- **`KeyBindingManager`** (key_bindings.json) defaults:

  | Key | Action | Key | Action |
  |---|---|---|---|
  | H | UI | T | track |
  | Z | strike zone | C | challenge |
  | M | sound | U | HUD mode |
  | B | batter | V | review: pitches |
  | SPACE | quick pitch | R | review: swing |
  | ESC | main menu | F | review: fielding |

  `KeyBindingsPanel.ACTIONS` must list every `KeyAction`.
- **Settings screens** (ui/settings_panel.py) are drawn rows and are sub-modes of `MenuState`.
  - A new setting is a row in `SettingsPanel.SECTIONS`, not a button.
  - Panels return `(action_id, payload)`, and `MenuState._SETTINGS_ACTIONS` maps that to a `Game` method.
  - Nothing has a hard-coded x (`content_bounds()`, `UIManager._footer_row_right`).
  - **The settings page is full.** The next setting needs scrolling, a second column or a sub-screen (`test_the_settings_page_has_headroom_left`).
- **Buttons.**
  - Add a button in `UIManager._create_game_buttons()`, give it visibility in `set_button_visibility()`, and register its callback in `Game._setup_ui_callbacks()`.
  - Styling comes from assets/theme.json; menu screens use `@broadcast_button`.

### Pitch database (data/pitch_database.py)
- **Service.** `PitchDatabaseService.get_instance()` wraps strikefactor/data/strikefactor.db and provides `start_game`, `end_game`, `record_pitch` and `load_batter_profile` / `save_batter_profile`.
- **Tables.** `pitches`, `pitch_trajectories` (20 samples per pitch), `at_bats`, `games` and `batter_profiles`.
- **Versioning.** `SCHEMA_VERSION = 10`, with migrations in `PitchDB._migrate`. Auto-backups go to data/backups/.
- **Non-obvious column semantics:**
  - `exit_velocity_mph` is set on every bat-on-ball event, fouls included, while `contact_quality` is NULL on fouls. Leave that asymmetry alone.
  - `swing_timing_diff_ms` is stored as `abs()`. `swing_timing_signed_ms` (v8) carries the sign.
  - `spray_angle_deg` (v9) is pull-positive for both hands and NULL when there was no contact. 0.0 is dead centre field, a real value.
  - `batted_ball_type` (v7) is classified at contact, independent of fielding. `fielder_role` / `play_margin_s` are NULL when no play happened; a positive margin favours the defense.
  - `defense_strength` (v10) is NULL for rows from before the setting existed. Don't back-fill it; error aggregates filter on `IS NOT NULL`.
  - `vertical_offset_in` actually holds screen pixels, despite its name.
  - Outcomes are stored in spaced form (`POP UP`).
- **Other stores.** `ScoreKeeper` (outs, runners, score) is in helpers.py, and data/batting_stats.json feeds the batting heatmap.

### Analysis package (analysis/, pitch_analysis.py, batting_analysis.py)
- **Running it.** The package is offline and opens the DB read-only. `python pitch_analysis.py [--terminal] [--mode/--difficulty/--handedness/--pitcher …]` writes 16 figures plus report.html into analysis_output/<filter-slug>/. batting_analysis.py writes batting_report.html into the same folder.
- **Layers** (see docs/pitch-analysis-refactor.md):
  - `data.py`: SQLite → pandas plus derived columns, and `Context`
  - `filters.py`
  - `metrics.py`: pure functions
  - `theme.py`: palettes, outcome groups, MLB benchmarks
  - `render_mpl.py` / `render_term.py`
  - `figures/`, with its registry in `figures.FIGURES`

**Metric definitions worth knowing:**
- A whiff is `swing_type > 0 AND outcome IN ('strike','strikeout')`.
- `POP UP` is terminal and belongs in every PA/BF/out denominator.
- Run values come from a count-value model solved over the active slice, so they are only meaningful *between* sub-groups.
- **The pitching line uses one slice for every column:** GameDay rows with a non-null `game_id`, which are the rows whose runs can be attributed. Excluded rows are reported in `df.attrs["dropped_pitches"]`.
- If the spray figure's spray-vs-timing curve comes back flat, the bearing has stopped reaching the ball somewhere upstream.

## Common tasks

**Add a pitcher:**
1. Subclass `Pitcher` in strikefactor/pitchers/, following Sale.py. The constructor takes `command`, `throws` and `pitch_command`. Call `load_img(loadfunc, 'assets/images/<name>/…', frames)`, then `add_pitch_type` once per pitch, and implement `draw_pitcher` for the windup timing.
2. Add usage priors in ai/pitch_priors.py. They are validated against the arsenal.
3. Add archetypes and a plan mix in data/pitch_locations.json, and bullpen attributes in data/pitcher_attributes.json.
4. Register the pitcher in `PitcherManager` (main.py). Train the AI and save it as `ai/<name>_ai.pkl`.

**Add a game state:**
1. Write the class in game_states.py.
2. Register it in `GameStateManager._initialize_states()`.
3. Add its transitions in `handle_menu_state_change()`.
4. Set button visibility in `UIManager.set_button_visibility()`.
5. Register callbacks in `Game._setup_ui_callbacks()`.

## File organization

```
.
├── pyproject.toml, uv.lock, .python-version   # uv-managed project; see Running and development
├── pitch_analysis.py, batting_analysis.py   # offline analysis CLIs
├── analysis/                # data, filters, metrics, theme, render_*, report, figures/
├── tools/                   # sim.py (ball-in-play sim + batter model), calibrate_defense.py — not installed
├── tests/                   # pytest; conftest.py forces headless SDL, re-exports tools.sim samplers
├── docs/                    # defense-strength, fielding-replay-plan (capture half live), infield-timing-refactor,
│                            #   pitch-analysis-refactor, unified-review
└── strikefactor/
    ├── __main__.py, main.py # entry point; Game, PitcherManager, AssetManager
    ├── config.py, outcomes.py, settings_manager.py, key_binding_manager.py, helpers.py
    ├── ai/                  # AI_2 (ERAI), batter_profile, compat, pitch_priors, *_ai.pkl, ai_umpire.pkl
    ├── pitchers/            # pitcher.py, at_bat_plan.py, pitch_locations.py, one file per pitcher
    ├── gameplay/
    │   ├── game_states.py, game_state_manager.py, pitch_simulation.py, hit_outcome_manager.py, hit_animation.py
    │   ├── bat_path, bat_contact, spray, ball_flight, batted_ball_path, park, ground_roll,
    │   │   infield_timing, extra_bases, defense          # pure physics modules
    │   ├── swing_record, fielding_record, review_record, review_store
    │   ├── gameday_manager, challenge_manager, random_scenario, prewarm
    │   └── batter.py, field_renderer.py
    ├── ui/                  # ui_manager, HUDs (scorebug/broadcast_hud/minimal_hud), review_* + swing_replay_overlay,
    │                        #   fielding_renderer, abs_challenge_overlay, settings_panel, gameday_theme,
    │                        #   play_by_play_panel, pitching_box_panel, pitcher_carousel, lap_log_panel, font/
    ├── engine/              # contact_audio.py, sound_manager.py
    ├── utils/               # pitch_physics.py, physics.py (ABS zone collision), io.py
    ├── assets/              # images/<pitcher>/, ball/, batter_*/, abs/; sounds/{contact,mitt,umpire_sounds}/; theme.json
    └── data/                # strikefactor.db, pitch_database.py, JSON stores, pitch_locations.json,
                             #   pitcher_attributes.json, gameday_maintenance.py, reset_tracking.py, archives/, backups/
```

Asset paths resolve through `config.get_path()` in development and `resource_path()` in PyInstaller builds.
