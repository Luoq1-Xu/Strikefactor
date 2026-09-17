# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

StrikeFactor is a pygame-based baseball batting simulator where players face off against AI-controlled pitchers with realistic pitch physics and timing mechanics. The game features multiple elite pitchers, each with unique pitch arsenals and AI behavior patterns.

## Running the Game

```bash
# Install dependencies
pip install -r requirements.txt

# Run the game (from the repository root)
python -m strikefactor
```

The game uses Python 3.12+ and pygame-ce for the core rendering and game loop.

`strikefactor` is an importable package: modules import each other as
`strikefactor.<module>`, so the **repository root** must be on `sys.path`.
Running `python strikefactor/main.py` directly does not work.

### The `strikefactor` command
`pip install -e .` installs the console script declared in
[pyproject.toml](pyproject.toml) (`[project.scripts]` → `strikefactor.__main__:main`),
after which the game launches with just:

```bash
strikefactor
```

The editable install also puts the repository root on `sys.path` permanently, so
this form works from **any** working directory, not only the repo root. The
script lives in the active venv's `bin/`, so it needs that venv on PATH — either
activate it, call the full path, or alias it.

## Development

```bash
pip install -e ".[dev]"    # adds pytest, pytest-xdist + ruff

pytest                     # test suite (headless, parallel; ~20 s on 12 cores)
pytest -n0                 # serial — for a debugger, `-s`, or a single test
ruff check .               # lint — currently green, keep it that way
```

- Dependencies and tool config live in [pyproject.toml](pyproject.toml).
  `requirements.txt` holds the same runtime set for plain `pip install -r`.
- Tests live in [tests/](tests/). [conftest.py](tests/conftest.py) forces SDL to
  its dummy video/audio drivers before pygame is imported, so no display is needed.
- The ruff rule set is deliberately narrow so `ruff check` passes today; the
  deferred rules (`B`, `UP`, `E731`) are listed in a comment in pyproject.toml.

### What the test suite actually costs
**The runtime is not spread across the tests, and the test count is close to
free.** Of ~900 tests, about 850 finish in under 5 ms each; the whole of
`test_bat_path.py` (158 parametrized cases) does not register on `--durations`.
What costs is a few dozen Monte Carlo fielding tests that run thousands of
complete `HitAnimation`s — `test_infield_hit_verdict.py` and
`test_defense.py` alone were 69% of a 115 s serial run. **Trimming tests is
therefore the wrong lever for speed**: deleting every fast test in the suite
would save a couple of seconds and throw away most of its coverage. The three
things that did work, in order of size:
- **`-n auto --dist worksteal`**, now the default in `addopts`. `worksteal`
  specifically: `loadfile` pins a file to one worker and leaves the slowest
  *file* as a floor, and `load` deals tests out up front so a worker handed
  two slow ones finishes last. See the comment in pyproject.toml for the
  measurements.
- **Memoizing the deterministic sweeps.** These sweeps seed the RNG per play
  from a locally seeded `random.Random`, so the same arguments always produce
  the same plays — and tests deliberately assert *different* properties of the
  *same* sample, four of them asking for `_misplayed(worst, 300,
  shape="GROUNDER")` verbatim. Simulating once and handing the result out kept
  the assertions separately legible (a failure names the property it guards,
  not one of six possible causes) and took the serial run 115 s → 83 s. In
  `test_defense.py` the cache also serves **prefixes**: play `i` depends only
  on `i` and the draws before it, so `_sweep(p, 400, seed)[:200]` is exactly
  `_sweep(p, 200, seed)`.
- **The one hazard that introduces**, and the reason `_scratch` exists: a
  shared sample is shared *objects*, so a test that pokes an animation's clock
  to drive `_error_mark_alpha` hands the next test a doctored play. It is
  restored explicitly rather than left to the accident that the fields happen
  not to be read again.

Do not raise a Monte Carlo test's `n` casually — it is the one thing in this
suite that costs real time — and do not lower one to save time either: the
bands are calibrated against MLB rates and several sit within ~2.5σ at the
sample sizes chosen.

### Pickled AI models
The committed `ai/*_ai.pkl` Q-tables record the module path of `ERAI` as it was
at dump time (`ai.AI_2`, from before `strikefactor` was a package). They are
loaded through [ai/compat.py](strikefactor/ai/compat.py), which remaps legacy
module paths. This matters because `PitcherManager._load_ai` falls back to a
**fresh** AI when loading fails — a broken path would silently discard training
rather than raise. `tests/test_ai_pickles.py` guards this.

## Architecture Overview

### Core Game Loop
The main game is managed by the `Game` class in [main.py](strikefactor/main.py), which orchestrates:
- **GameStateManager** ([game_state_manager.py](strikefactor/gameplay/game_state_manager.py)): Manages transitions between game states (menu, gameplay, summary, visualization, etc.)
- **PitcherManager**: Handles pitcher instances and their AI counterparts
- **AssetManager**: Loads and caches game sprites and assets
- **UIManager** ([ui_manager.py](strikefactor/ui/ui_manager.py)): Manages all pygame_gui UI elements
- **SoundManager** ([sound_manager.py](strikefactor/engine/sound_manager.py)): Handles audio playback; see [Contact Audio](#contact-audio)
- **ChallengeManager** ([challenge_manager.py](strikefactor/gameplay/challenge_manager.py)): Tracks ABS challenges remaining per side
- **BatterProfile** ([batter_profile.py](strikefactor/ai/batter_profile.py)): In-session player swing tendencies, read by pitch-selection AI
- **HUDs**: `Scorebug`, `BroadcastHUD`, `MinimalHUD` — see [HUD System](#hud-system)
- **PitchDatabaseService** (singleton, [pitch_database.py](strikefactor/data/pitch_database.py)): SQLite logging of every pitch

### Game States
The game uses a state machine pattern with states defined in [game_states.py](strikefactor/gameplay/game_states.py):

**Main Menu Flow:**
- **ModeSelectState**: Top-level mode selection (Arcade/Sandbox/GameDay) with typing effect animation
- **MenuState**: Arcade mode — pitcher selection, settings, and key bindings
- **SandboxMenuState**: Sandbox pitcher selection (typing effect)
- **GameDayState**: Entry screen for full 9-inning GameDay mode, uses `PitcherCarousel` to pick the opponent starter

**Gameplay States:**
- **GameplayState**: Active batting gameplay (Arcade + GameDay share this state)
- **SandboxGameplayState**: Sandbox batting — user controls pitch selection via on-screen pitch buttons (`update_sandbox_pitch_buttons`) and accumulates "laps" (see [Sandbox Mode](#sandbox-mode))
- **SummaryState**: Post-game statistics
- **VisualizationState**: Pitch trajectory animation playback
- **ViewPitchesState**: Review all pitch locations with PitchViz
- **InningEndState**: End-of-inning transition (before summary)
- **GameDayTransitionState**: Manages flow between innings in GameDay mode (relief decisions, opponent at-bats, box score)

**Navigation Flow:**
```
ModeSelectState (game start)
    ├── ARCADE  → MenuState (pitcher selection) ──→ GameplayState
    ├── GAMEDAY → GameDayState (carousel pick) ──→ GameplayState ⇄ GameDayTransitionState
    └── SANDBOX → SandboxMenuState ──→ SandboxGameplayState
```

Each state extends the abstract `GameState` class and implements `enter()`, `exit()`, `update()`, `handle_event()`, and `render()` methods.

### Pitcher System
Pitchers are defined in [strikefactor/pitchers/](strikefactor/pitchers/):
- **Base class**: [pitcher.py](strikefactor/pitchers/pitcher.py) - Defines core pitcher functionality, stats tracking, and pitch arsenal management
- **Concrete pitchers**: Sale.py, Degrom.py, Mcclanahan.py, Yamamoto.py, Sasaki.py
- Each pitcher defines their pitch types as methods that call the simulation with specific physics parameters (acceleration, velocity, travel time)
- Pitch types are registered via `add_pitch_type(function, name)` in the pitcher's `__init__`

### AI System
The AI uses Q-learning for pitch selection:
- **ERAI class** ([AI_2.py](strikefactor/ai/AI_2.py)): Implements epsilon-greedy Q-learning
- Pre-trained models stored as pickle files in [strikefactor/ai/](strikefactor/ai/) (e.g., `sale_ai.pkl`, `degrom_ai.pkl`)
- Each pitcher has an attached AI that learns pitch selection based on game state (count, outs, runners on base, previous pitch)
- The AI chooses actions using `choose_action(state)` which balances exploration (epsilon) vs exploitation
- **BatterProfile** ([batter_profile.py](strikefactor/ai/batter_profile.py)): Tracks the live player's swing tendencies by zone quadrant (`up_in` / `up_away` / `down_in` / `down_away`), pitch type, count state, chase rate, and first-pitch rate. The pitch-selection AI consults this profile to exploit patterns. Profiles are persisted per `(mode, difficulty)` bucket via `PitchDatabaseService.{load,save}_batter_profile` so behavior carries across sessions.

### Pitch Physics & Simulation
The pitch simulation is handled by [pitch_simulation.py](strikefactor/gameplay/pitch_simulation.py):
- **PitchSimulation class**: Manages the entire pitch sequence from windup to contact/miss
- Physics parameters: `ax`, `ay` (acceleration), `vx`, `vy` (velocity), `traveltime`
- Ball position tracked in 3D: `[x, y, z]` where z is distance from plate
- Collision detection uses physics utilities from [utils/physics.py](strikefactor/utils/physics.py)
- An AI umpire model (`ai_umpire.pkl`) determines ball/strike calls, via
  `get_umpire_model()`. The pickle is tiny but holds an SVC, so unpickling
  triggers the process's first `import sklearn` (~680 ms). Its only caller is
  `_make_ball_strike_call()`, one frame past plate arrival, so left to load on
  demand it froze the first taken/whiffed pitch of a session mid-swing.
  [prewarm.py](strikefactor/gameplay/prewarm.py) now loads it (and pandas, via
  `pitch_simulation`) on a daemon thread from `Game.__init__`. Keep the import
  lazy — hoisting it to module level is what put sklearn back on the gameplay
  layer's import path and out of reach of tests.

### Hit Outcome System
[hit_outcome_manager.py](strikefactor/gameplay/hit_outcome_manager.py) determines hit results:
- Factors: swing timing, swing location (high/low relative to ball), contact quality, and — since [spray.py](strikefactor/gameplay/spray.py) — which way the bat was pointing
- Difficulty modifiers reach the batted ball as **seconds on the runner's clock**, not as a multiplier on the verdict — `out_probability_modifier` converts via `DIFFICULTY_SECONDS_PER_MODIFIER` (−0.15 s at ROOKIE to +0.30 s at HALL_OF_FAME). Far more intelligible, and it cannot overrule the physics on a routine play.
- Separate logic for contact swings (W key) vs power swings (E key)
- Outcomes: SINGLE, DOUBLE, TRIPLE, HOME RUN, FLYOUT, GROUNDOUT, LINEOUT, POP UP, REACHED ON ERROR, FOUL BALL
- **The home run is decided by the fence, not by a roll.** `_resolve_outcome` classifies the batted-ball type and asks `park.fence_verdict` one question — is this flight higher than the fence when it reaches the fence's own distance — off the ball's launch angle, exit velocity and bearing. Everything else is still deferred to the animation as `IN_PLAY` and emerges from the fielding and timing models. It replaced `_BBT_HR_RATE_BASE` / `_BBT_HR_QUALITY_SCALE` / `_POWER_HR_RATE_BONUS`, a quality-indexed probability computed *independently of* `ball_flight.carry_distance_ft` — the last surviving two-models-of-one-thing fault, and it disagreed **systematically**: at each shape's real median quality a line drive carrying 241 ft was given a 9.8% chance of clearing a fence no nearer than 360 ft (21.8% on a power swing), and a fly carrying 327 ft got 25.9%. That is why HR ran at ~25% of hits against MLB's ~14%. Two levers went with it, both second uses of something that already reaches the ball: `out_probability_modifier` (difficulty reaches the fence through the assists, into quality, into exit velocity) and `momentum_bonus`, which is now an exit-velocity bonus applied at the one place this ball's EV is drawn (`MOMENTUM_EV_MPH_PER_UNIT`). `get_contact_hit_outcome` / `get_power_hit_outcome` are one `hit_outcome` now — the swing type only ever fed the roll's power bonus, and a power swing reaches the fence through `EV_POWER_BONUS_MPH` instead.
- `Contact.spray_deg` carries the ball's direction downstream (a `last_spray_deg` latch on `HitOutcomeManager` was the first form of this and is gone — every consumer reads the contact). It replaced `last_horizontal_inside`, which was the *pitch's* inside/outside offset in screen pixels and was read by exactly one thing (the home-run angle). Pitch location does belong in the answer — it just belongs the way it reaches a real hitter, by moving where the bat points when it arrives, which `bat_path` already models. `_compute_horizontal_inside` and `contact_screen_x` are gone with it.
- **`swing_verdict` asks two questions now**, and `Contact.is_foul` is where they meet: was the ball struck cleanly (`quality`), and did it leave between the lines (`spray`). See [Modifying Swing Mechanics](#modifying-swing-mechanics).
- Once an outcome is resolved, `pitch_simulation._start_hit_animation()` hands off rendering to [HitAnimation](#hit-animation), which classifies the trajectory shape and plays it before the result banner appears.

### Contact Audio
[contact_audio.py](strikefactor/engine/contact_audio.py) picks the bat-contact sample and its gain. Pure module — no pygame, no game state — so it is testable without a mixer.
- **Every** bat-on-ball event routes through `SoundManager.play_contact(quality, swing_type)`: fouls, in-play contact and home runs alike. The only thing separating them acoustically is the modelled exit velocity. Selection deliberately takes **no outcome** — the sound fires at impact, before the animation resolves what happened, and a home run that merely carried should not sound like a 112-mph barrel.
- **A home run reaches the audio layer as a sample floor and nothing else** (`is_home_run=True` → `HOMERUN_MIN_SAMPLE`, `contact_solid`). It is not an outcome cue: ~52% of home runs used to play `contact_weak`/`contact_medium`, which is how a soft crack ended up under a 460 FT readout. Wall-scrapers still sound merely solid; the floor is not "home runs are always loudest". **It is not near-redundant either**, which is worth measuring rather than assuming: the ladder is a *weighted draw*, not a nearest-centre lookup, so at the 89.5 mph that is the softest ball able to clear this park, **47.0%** of draws are still a quiet rung (32.1% at 95, 23.0% at 100, 10.9% at 105). The floor does four fifths of the job the distance lookup was added for.
- **It used to also take an exit velocity back out of the carry, and that is gone.** `play_contact(..., hr_distance_ft=)` outranked the caller's `ev_mph`, read an EV off the landing distance through the six-row `HR_DISTANCE_TO_EV`, and `PitchSimulation` wrote the result over `self.exit_velocity_mph`. That was right while it lasted — `hit_animation`'s carry model rolled its own random `bias`, so quality and distance genuinely disagreed and the distance was the better measurement. `ball_flight.carry_distance_ft(launch_deg, ev_mph)` is a **pure function** now (`test_the_distance_is_the_carry_the_flight_model_gives` pins the landing to it), so `ev → carry → table → ev'` was a lossy re-reading of the number it started from, through a table with **no launch-angle term** against a carry that depends on the angle strongly: 112 mph at 20° carries 412 ft and read back 105.6, 95 mph at 40° carries 370 ft and read back 101.0. A deterministic **±6 mph** distortion decided by the launch angle alone, on the DB column and on the swing replay's `EXIT VELO` — larger than the 3.5 mph sd the one-draw refactor below was written to remove. **It was already visible**: `swing_replay_overlay` draws the overwritten `sim.exit_velocity_mph` while `review_views` draws the animation's copy, which was never overwritten, so one home run showed two different EVs a few pixels from the distance the round trip came out of. `tests/test_contact_audio.py::test_the_home_run_distance_round_trip_is_gone` pins all three kwargs the name reached.
- A foul that hooks past the pole (`is_foul_hr`) is **not** a home run and gets no floor — it takes the ordinary quality path.
- **One draw per batted ball, and *once* now means once across the whole pitch with no exception.** The home run kept one until the carry model became deterministic (see above); `self.exit_velocity_mph` is assigned exactly once, in `_evaluate_contact`, and never reassigned. `PitchSimulation` draws this ball's exit velocity once in `_evaluate_contact` — with the *real* `swing_type` — and hands the same number to `HitAnimation(ev_mph=)` and to `play_contact(ev_mph=)`. It used to be drawn twice: once inside the animation for the physics and again inside `contact_sound_for` for the sound, and the second is the one that reached the DB and the swing replay's `EXIT VELO`. So the number the player was shown was not the number the ball was flown at — mean 0 but **sd 3.5 mph** on a contact swing. On a power swing it was worse and biased: the animation's call took the default `swing_type="contact"`, so **`EV_POWER_BONUS_MPH` reached the crack and the readout and never once reached the ball** (mean +4.8 mph, max 25). Putting it into the physics is what the E key has always claimed to do, and it costs something: over 2500 identical balls in play, drawing EV as `power` rather than `contact` moves BABIP **.332 → .376** and doubles **5.4% → 8.8%**. That applies only to power swings, and it is the dial to reach for if the extra-base rate runs hot.
- **The EV curve is calibrated, not analytic.** `quality` is only computed for swings that squared the ball up enough to put it in play, so its real distribution is skewed hard toward 1.0 — p25 0.720 / p50 0.807 / p90 0.941 as re-measured on 2026-09-10 (the tails were already right — p10 0.646 against 0.643 and p99 0.988 against 0.988 — which is what identifies it as a genuine drift in the middle rather than a different player model being swept), against 0.689 / 0.763 / 0.937 when `spray`'s location term was made to saturate, 0.653 / 0.743 / 0.932 immediately before it, 0.717 / 0.769 / 0.918 for the slide model, 0.70 / 0.81 / 0.98 for the anisotropic bat, and 0.770 / 0.886 / 0.982 for the rectangle. **The bottom tail lifted and the top barely moved** at the last change (+0.063 at p10 against +0.001 at p99), which is the signature of it rather than a side effect: the straight-line location term was sending every ball the hitter had to *reach* for past the foul line at ≈−59°, and those balls were well struck — an inside-out reach on an outside pitch is not a mishit — so releasing them adds solid contact at the bottom of the fair distribution. `FOUL_QUALITY_THRESHOLD` went 0.52 → 0.59 at the same time to hold the total foul rate (47.4% → 47.6% measured), which lifts the floor again. `EV_CALIBRATION` pins those observed quantiles to MLB EV quantiles — and since 2026-09-16 its top three rows are the lever that holds the home-run rate (99.5/103/108 at p75/p90/p99, against the 101/106/112 that ran the batter's line drives ~6 mph hot); see the calibration entry under [The calibration harness](#the-calibration-harness-tools). A naive linear/power mapping puts the *median* batted ball near the top of the scale — routine grounders then draw the max-crack sample, which is the bug this module exists to prevent. Re-derive the table whenever the contact geometry changes: left on the rectangle's anchors it read the whole distribution ~6 mph soft at the median, which is a thumb on the scale toward outs on every ball in play. `tests/test_infield_hit_verdict.py::_QUALITY_QUANTILES` is anchored to the same numbers and must move with it, and `tests/test_contact_audio.py` now reads `conftest.QUALITY_QUANTILES` rather than keeping a private copy.
- Two layers make a spectrum out of five samples: overlapping EV bands blended at the edges (selection), plus continuous gain within the band (`contact_gain`).
- **Assets are grouped by sound source, one directory per source** — `contact/` (bat on ball), `mitt/` (catcher receiving), `umpire_sounds/` (ball/strike/strike_3 calls). `SoundManager.SOUND_FILES` is the key→path registry; umpire calls are directory-scanned instead, for random variant selection.
- **Keys and filenames describe the sound, never an outcome**: `contact_weak` → `contact_medium` → `contact_solid` → `contact_hard` → `contact_crushed` (files `contact/weak.mp3` … `contact/crushed.mp3`). They were `FOULBALL/SINGLE/DOUBLE/TRIPLE/HOMERUN.mp3`, which became actively misleading once selection moved to EV — `contact_solid` plays on any ~95 mph ball, which may end up a double, a lineout or a foul.
- `mitt_pop_*` are **catcher's mitt** sounds used by `glovepop()`, not bat sounds. They were briefly wired into the contact ladder as weak-contact ticks, which put a mitt slap on balls the batter had just hit — the directory split plus the key prefix is what makes that mistake visible.
- `tests/test_sound_manager.py` guards the whole chain: every ladder rung resolves to a registered key, every registered file exists on disk, every rung is sourced from `contact/`, no mitt sample appears in the ladder, and no key is named after an outcome.
- `HOMERUN_MIN_EV_MPH` hard-gates the top sample regardless of weights.
- **Gain is set on the Channel, never the Sound.** Sounds are shared singletons; `Sound.set_volume()` would leak one playback's level into every later and concurrent play of the same sample. `master_volume` is applied here too — it was in the settings defaults but read by nothing before this.
- Foul contact metrics are computed in `PitchSimulation._compute_foul_contact_metrics()`, called from `_handle_foul_ball` — **not** from `_start_foul_animation`, which is gated behind `foul_animation_enabled`. Moving it back under that gate would leave players with the setting off hearing one flat sample per foul.

### Batted-ball physics (`ball_flight.py`, `ground_roll.py`, `infield_timing.py`, `extra_bases.py`)
Four pure modules on the [contact_audio.py](strikefactor/engine/contact_audio.py) pattern — real feet and seconds, no pygame, no game state — that own everything physical about a batted ball, in the order it happens: flight, landing and roll, then the two races. See [docs/infield-timing-refactor.md](docs/infield-timing-refactor.md) for sourcing on every constant.
- **[ball_flight.py](strikefactor/gameplay/ball_flight.py)**: which way the ball left the bat (`launch_angle_deg`, `shape_for_launch_angle`), how long it is then in the air (`flight_time_s`), how far it carries (`carry_distance_ft`) and how high it is at any distance (`height_at_distance_ft`), from one projectile identity. **`height_at_distance_ft` is the animation's drawn arc as well as the fence predicate** — see [Hit Animation](#hit-animation) — so its *shape* decides a home run and a catch as well as the picture, and the shape it had was wrong. It was the vacuum parabola over the drag-corrected range, and its docstring confessed it "reads a little high on the way down"; against the integration `DRAG_RANGE_ANCHORS` is fitted to it read **low** everywhere past a sixth of the path, with the apex **1.5-1.6x too low** at every home-run angle (105 mph at 28° peaks at 89 ft and drew at 56) and at half the path where the real apex is at 58%. Drag costs a ball far more range than height, so for the distance it actually covers it goes much higher than a vacuum ball covering the same distance. `DRAG_APEX_ANCHORS` is the third table — `(angle, apex gain over R·tanθ/4, apex path fraction)`, fitted to the same flights at the same angles — and the profile is two half-parabolas meeting at that apex, which keeps the three properties every consumer rests on (zero at the carry, negative beyond it, `tanθ` the initial slope) and gets the descent steeper than the ascent. **Re-derive all three tables together or none.** `tests/test_ball_flight.py` pins the apex to the integration, the whole profile above the vacuum one, and the apex past the midpoint.
  - **This was found as "line-drive home runs".** Every home run drew as a low arc gliding in over its last third, which is the signature of a line drive, so the fly balls leaving the park did not look like fly balls — and the perception was of the *picture*: re-flying all recorded contacts through the model put only 15-21% of home runs in the LINER band with a launch-angle p50 of 29-30°, against MLB's ~25-30% and ~28°. Two decisions read the same wrong number. `park.fence_verdict` needed 1.6-2.7x more height at the fence than a real ball has there, so a home run needed more carry than it should and the 12 ft fence was raised against that; and the catch gate read a 90 mph liner at 200 ft as 7.7 ft up, inside an 8 ft glove, where the real ball is 14.5 ft over it.
  - **An airborne flight is a function of the launch angle and the exit velocity and of nothing else.** It used to be a function of the *shape*: `launch_angle_deg` produced a real continuous angle, `shape_for_launch_angle` banded it, and then the carry and the hang time threw the angle away and looked up the band's **centre** — so every airborne ball in the game flew at exactly 14°, 32° or 68°, with a cliff at each band edge worth **116 ft of carry and 2.25 s of hang time** at 100 mph, crossed by a fifth of an inch of bat position. The shape survives as a *classification* (the DB column, the animation's arc, `ground_roll`'s descent) and is no longer an input to how far the ball goes. `launch_angle_for_shape` is the bridge for a caller that has only a shape, and returns the band centre so those callers see exactly what they saw before.
  - **`DRAG_RANGE_ANCHORS` and `DRAG_HANG_ANCHORS` are fits to reality at the same angles, not fits to each other.** The range table is fitted to a numerically integrated trajectory carrying drag *and lift*, scaled so 100 mph at 30° carries 400 ft. That mattered: the three rows it replaced came off a *no-lift* integration and ran ~15% short at line-drive angles and ~20% long at pop-up angles, which nobody saw because `hit_animation` clamped every landing into a per-shape range that happened to compensate. The hang table is fitted to observed hang times instead, because the same integration over-predicts hang by ~12% (a 400 ft fly at 5.1 s against a real 4.5) — and handing every outfielder 12% more time is not a free change.
- **[park.py](strikefactor/gameplay/park.py)**: how far away the fence is (`wall_distance_ft`) and how high (`FENCE_HEIGHT_FT`), and so what it does to a flight (`fence_verdict` → `OUT_OF_PARK` / `OFF_THE_WALL` / `SHORT_OF_WALL`). One definition, read by `hit_outcome_manager` for the home run and by `hit_animation` for the landing *and* for its own render semi-axes, so the fence a verdict is computed against and the fence that gets drawn are one fence. **The park is deep**: the ellipse measures 360 ft down the lines against an MLB norm of 325-335, so a sub-360 ft home run is geometrically impossible and the HR distance distribution sits ~20 ft right of MLB's. Bringing the lines in means reshaping the drawn wall. **And the fence is tall — 12 ft, against the ordinary MLB 8 — and only one of its two original reasons survives.** It was raised for the home-run rate (at 8 ft this deep park put **6.3%** of fair batted balls out against MLB's 4-5%, 12 ft gave **4.9%**), but those were measured against the vacuum parabola that read a ball's height at the fence 1.6-2.7x low — the fence was being raised to hold a rate the flat arc was already suppressing. With the arc physical the same batter puts **6.0%** out at 12 ft, and the rate is held by the top of `EV_CALIBRATION` instead (see [Contact Audio](#contact-audio)); **do not raise the fence for the home-run rate again**. Less obviously, and still the reason, **the height decides what a ball off the wall is allowed to be**: a ball is off the wall exactly when it arrives *below the rim*, so a fence no taller than a fielder's 8 ft reach means every wall ball arrives inside a glove and a fielder standing there catches it — 50 of 58 at LEAGUE, which is how doubles came to run 0.16 per single against MLB's 0.33. The band between the glove and the rim is where a double off the wall lives, and `tests/test_catchable_in_flight.py::test_the_fence_is_taller_than_a_fielder_can_reach` is the pin that it exists. Distance and hang time are two consequences of *one* flight — deriving them separately is how the animation ended up showing a 400 ft fly with 2.7 s of hang. Ground balls are not projectiles and delegate to `infield_timing`'s retention curve, so the ball the viewer watches reach the shortstop is the ball the verdict was computed against.
  - **The launch angle is `spray`'s argument on the vertical axis**, and it is the newest of them: a cylinder's surface normal is radial to its own axis, so the ball leaves perpendicular to the bat, and `bat_contact` has been handing the normal over all along — `axis_point_ft` is the *nearest* point on the axis, so `vertical_offset_ft` is that normal's rise. `launch = ZERO_OFFSET_LAUNCH_DEG + NORMAL_GAIN * asin(offset / CONTACT_NORMAL_RADIUS_IN)`, banded by Statcast's cuts (GB <10°, LD 10–25°, FB 25–50°, PU >50°) — the same bands `LAUNCH_ANGLE_DEG` already stated the *centres* of, so "what shape is this" now has one definition serving the classifier and the flight model.
  - **It replaced a weighted random roll in `hit_outcome_manager`** in which the geometry only tilted a Gaussian weight and never fixed the *sign*. A bat 1.2 in **over** the ball drew a FLY 11% of the time and a LINER 30%; over recorded play, **14.8%** of every bat-over-the-ball contact was classified airborne and 29.2% of bat-under contacts came out grounders. The swing replay reports that offset to the player, so they were shown the contact and then handed a trajectory contradicting it — which is how it was found. It is now 1.5% / 3.5%, and all of that residual is inside ±0.6 in, where near-square contact genuinely is ambiguous.
  - **Two of the three tables it replaced were unreachable, and silently so.** Bat and ball stop touching at the sum of their radii, 1.30 + 1.45 = **2.75 in = 17.2 px** — but the POP_UP offset anchor sat at 22 px = 3.5 in, naming a contact that cannot happen, so pop-ups ran **1.0%** of recorded play against MLB's 7% and could only win out of a Gaussian tail. That table's comment claimed a reach of "~±25 px", true when `ft_per_px_z` was ~0.0111 and stale ever since — the same units-drift trap CLAUDE.md records for `EV_CALIBRATION`, one axis over. The sigmas failed from the other end: 1.4–2.2 in against a domain of ±2.75 left the offset term nearly flat over everything possible, so `_TYPE_BASE_PRIOR` did most of the work. `tests/test_batted_ball_type.py::test_the_prior_tables_are_gone` is the pin.
  - **Quality is deliberately not an input.** It was one, as a per-type bias running to −0.85 for pop-ups, and it does not belong: how square the contact was is the *magnitude* of the miss and the launch angle is its vertical *direction*. What the bias stood in for survives, emergent — an extreme undercut is far off centre, so `centre_score` is low, so the ball is struck weakly. A pop-up is a mishit because of where the bat was, not because a table said so.
  - **`JITTER_LIMIT_SIGMA` is why the guarantee is a guarantee.** Swing-plane scatter is real, but a Gaussian has infinite support, so however narrow it is set there is some tail that contradicts the geometry it is perturbing — and a tail that rare is *worse* than a common one, because it reads as the model being arbitrary rather than noisy. Truncating at 2σ costs 0.2 points of any marginal and makes "bat over the ball is never a fly ball" exactly true beyond 0.4 in. A sampled test of that property fails once every few thousand runs unbounded, which is the worst way to hold a guarantee; `test_the_bounded_jitter_cannot_outvote_the_geometry` asserts the extreme draw instead.
  - **The marginals come out of the geometry rather than a prior**, which is the whole gain: GB **41.7** / LD **24.1** / FB **27.7** / PU **6.5** against MLB's 42/24/27/7, measured through the real seam over 4,527 simulated fair contacts (the old model, recorded: 45.2 / 31.6 / 22.2 / 1.0). The offset distribution it integrates over is symmetric because the contact geometry is unbiased — a perfect cursor through `aim_at_pitch` gives 0.00 in of offset at every point in the zone — so nothing here is correcting for a bias upstream.
  - **The blast radius is smaller than the usual contact-geometry change**, and worth stating because the reflex here is to archive. The bat, `contact_quality` and `Contact` are all untouched, so `contact_audio.EV_CALIBRATION` and the four quantile-anchored sites listed under [Modifying Swing Mechanics](#modifying-swing-mechanics) do **not** need re-deriving — this changed which *shape* a given contact becomes, not which contacts happen or how well they were struck. What is not comparable across the change is any aggregate over `batted_ball_type` (and the GB/FB-derived rates in `analysis`), since the pre-change rows carry a mix produced by a prior rather than by the geometry.
- **[ground_roll.py](strikefactor/gameplay/ground_roll.py)**: what the ball does after it first touches the grass. Three facts carry it:
  - **Every batted ball lands at about terminal velocity** — 46–59 mph across the whole launch grid, whether it was struck at 60 or 110. Exit velocity buys distance and hang time and does not survive the trip as speed, which is why `LANDING_SPEED_MPH` can be stated outright instead of derived from a carry model that might disagree with it. What varies by shape is the *descent angle* (20° on a line drive, 47° on a fly, 73° on a pop-up), and the angle is what the bounce is a function of.
  - **A bounce is an impulse problem, not a decay constant.** `_impact_impulse` is one rigid-sphere calculation covering both the line drive that skids and keeps its speed and the backspun fly ball the grass grips and converts to topspin. Nearly all the horizontal loss happens at the *first* contact.
  - **A ball in the air is not subject to rolling friction.** Hops are real projectile arcs (`h = u²/2g`, `T = 2u/g`), so height and duration come from one rebound speed.
  - `GRASS_ROLL_DECEL_FT_S2` is the designated calibration dial, for the same reason `infield_timing` calibrates on release time — published rolling resistance for a ball on cut grass spans 0.1–0.25 g, so it is the input whose uncertainty is real. `ROLL_AIR_DRAG_PER_FT` is *not* a dial: it is Cd·ρ·A/2m for a baseball, and it matters because it is 40% of what stops a ball leaving its last hop at 46 ft/s.
  - **A ball nobody touches travels 60–200 ft after landing, over 4–7 seconds.** What ends a play in the outfield is a fielder, not friction. Any change that makes the ball die where it lands is the bug this module was written to fix.
- **[infield_timing.py](strikefactor/gameplay/infield_timing.py)**: does the throw to first beat the runner. `HARD_PLAY_PROB` supplies the left tail of the margin distribution — without it the *hardest quarter* of plays were still comfortable outs and infield hits ran at 2-3% against MLB's 6-8%. It is variance, deliberately, not bias: raising mean release time to hit the same rate needed 1.08 s, outside the sourced range, and would have made routine plays close instead of adding hard ones.
- **[extra_bases.py](strikefactor/gameplay/extra_bases.py)**: the same race one base over. `AGGRESSION_MARGIN_S` is load-bearing — a runner needs *daylight*, not a dead heat, and without it every gapper is a triple.
- **The batter's contact quality is not uniformly distributed.** Its real median is 0.88 (p25 0.77, p90 0.98) because quality is only computed for swings that already timed the ball. Four separate constants in this codebase have been miscalibrated by assuming otherwise — see the note on `EV_CALIBRATION` under [Contact Audio](#contact-audio). **Never tune against a `range(0, 1)` quality sweep**; sample `(contact_quality, vertical_offset_in)` from `strikefactor.db`, or use the quantiles in `tests/test_infield_hit_verdict.py`. Prefer keying off exit velocity, which already has the real distribution baked in.

### Defense strength (`defense.py`)
[defense.py](strikefactor/gameplay/defense.py) is the settings→physics seam for how good the nine gloves behind the pitcher are, on the [contact_audio.py](strikefactor/engine/contact_audio.py) pattern — real feet and seconds, no pygame, no game state. A `DefenseProfile` is a frozen dataclass of physical quantities (sprint speed, reaction band, throw speed, release scale, misplay rates); `profile_for(level)` is total and answers anything unrecognised with `NEUTRAL`. Four levels: `sandlot` / `minors` / `league` / `gold_glove`. See [docs/defense-strength.md](docs/defense-strength.md) for sourcing and calibration.
- **`LEAGUE` is the exact identity, and that is the load-bearing fact.** It restates `FIELDER_SPRINT_FT_S`, `REACTION_DELAY_MIN/MAX_S`, `THROW_EFFECTIVE_FTS` and a release scale of 1.0, so passing `defense=None` and `defense="league"` produce **zero differing plays** over 900 balls in play — identical outcomes *and* identical margins, because the RNG is consumed identically. That is what made it safe to wire into a 4200-line file. `tests/test_defense.py::test_the_neutral_profile_changes_nothing_at_all` is the pin, and it compares against the real constants rather than literals.
- **It reaches the game as a `HitAnimation(..., defense=)` kwarg**, resolved by `PitchSimulation._defense_profile()`. Reading `game.settings_manager` inside the animation was rejected: every fielding test builds a stub game with no settings manager, and the right stub answer is "neutral", which a default kwarg already says.
- **`field_misplay_p` is the calibration dial, and a modulated base is not a rate.** The ranging and hop gains multiply it by a measured **3.18×** on a *typical* play, because a fielder who came up with a ball has usually moved for it. Set from `0.015 / (E[Δp] × mod)` with `E[p_out_clean − p_out] = 0.495` measured, not guessed — at the original 0.045 the effective misplay rate was 11%, errors ran 3.4% of balls in play against MLB's 1.4%, and ground-ball hits hit 41%.
- **`body_block` has an independent target**, which makes it the best-anchored number: it sets how many balls an infielder *reaches* and still lets through — the third state the model never had (a ball was either untouched, i.e. a hit, or touched, i.e. a race). §8 of [docs/infield-timing-refactor.md](docs/infield-timing-refactor.md) measured the ground-ball hit rate 2.7 points light and named exactly this cause, and that gap predates the feature.
- **Play difficulty degrades the *block*, it does not scale the share that gets through.** Written the other way round, an ordinary play (6 ft of range, 95 mph) multiplied past 1.0 at the bottom two levels, so both clamped to `THROUGH_SHARE_MAX` and became indistinguishable — `body_block` stopped mattering on exactly the contact where the setting should read most clearly.
- `RANGING_FULL_FT` **is** `infield_timing.RELEASE_STRETCH_FT`, imported rather than restated, so "how hard was this play" has one definition across the release penalty and the misplay probability.
- **`through_turn_s` is `muff_recovery_s`'s sibling and used to be a render-layer constant.** How long a fielder takes to recover from a misplay is one quantity with two cases — the ball at your feet (`muff_recovery_s`) and the ball past you (`through_turn_s`) — but the second sat in `hit_animation` as a flat `THROUGH_TURN_S = 0.45` while the first was per-level, so a Sandlot fielder turned round exactly as fast as a Gold Glove one on the mechanism that produces most of this module's errors. Now on the profile, scaled off LEAGUE by the same ratios `muff_recovery_s` uses; LEAGUE stays exactly 0.45 so the neutral identity holds.
- **`HARD_PLAY_PROB` came down 0.22 → 0.18** because both terms feed the same left tail and double-counted. The better trade, not just the necessary one: §8 criticises that constant *for being flat*, and the misplay term is the model it asked for.
- **`_runner_sprint_fts()` must stay unscaled.** Defense strength is not batter speed — scaling it would make a weak defense silently a fast batter and double-count against `_difficulty_time_offset_s`, which already moves that clock.

### The outcome vocabulary (`outcomes.py`)
[outcomes.py](strikefactor/outcomes.py) is the single definition of what can happen to a plate appearance: the outcome strings, the HIT / BATTED_OUT / REACH / IN_PLAY / OUT / TERMINAL groups **composed** from them, `HIT_BASES`, the display names and the colours. Top-level beside `config.py`, importing nothing, so nothing that needs it can be made cyclic by taking it.
- **It exists because there were four vocabularies and they disagreed about spelling.** `helpers.OUTCOME_COLORS` (spaced), `GameDayTransitionState._HIT/_OUT/_REACH_RESULTS` (spaced, upper), `PitchDataExtractor.TERMINAL_OUTCOMES` (**underscored**) and `GameStats.outcome_value` (mixed — `'strikeout'` beside `'SINGLE'`). "Is this outcome in that set" had a different answer depending on which set was asked, and adding `REACHED ON ERROR` meant editing all four plus `_finalize_batted_ball`'s `is_out`, its trail colours and six sets in `analysis/theme.py`.
- **All three failure modes are silent**, which is what makes composition rather than enumeration load-bearing: an outcome missing from `TERMINAL_OUTCOMES` never *closes the at-bat*, one missing from `_OUT_RESULTS` vanishes from the AVG denominator, one missing from `is_out` is credited as a hit and fed to the batting heatmap.
- **`db_key` is the one producer of the underscored form.** It was written out as `.upper().replace(" ", "_")` at each comparison site, which is how `POP_UP` and `POP UP` came to be two spellings of one outcome that both had to be matched.
- **The amber was a literal in four files** and `hit_animation.ERROR_MARK_COLOR`'s own comment *listed* the other three copies — the tell that it was not authoritative. `COLORS`, `OUT_COLOR`, `HIT_COLOR` and `ERROR_COLOR` are now the one source; the trail dot and the banner are one fact drawn twice.
- **`analysis/theme.py` deliberately keeps its own copy.** It is an offline process that must read an archived database without the game installed, and it already composes its groups. That makes it the one place drift cannot be prevented by construction, so `tests/test_outcome_names.py` prevents it by assertion instead — along with pinning that every consumer still *derives* its sets.

### The calibration harness (`tools/`)
[tools/sim.py](tools/sim.py) is the headless ball-in-play simulator and the batter model; [tools/calibrate_defense.py](tools/calibrate_defense.py) sweeps the defense ladder with it. Run as `python -m tools.calibrate_defense --n 2500` from the repository root.
- **It exists because the numbers in `docs/defense-strength.md` could not be re-derived.** That document says a `DefenseProfile` is a value precisely so "a calibration harness can sweep four levels in a loop", and the ladder quoted there and in `tests/test_defense.py` was produced by a harness that was never committed — so the only way to simulate a ball in play lived inside a test file, and anyone tuning a constant had to rebuild the measuring instrument first.
- **The suite and the harness share one batter.** `QUALITY_QUANTILES` / `QUALITY_BY_SHAPE` / `LAUNCH_ANGLE_QUANTILES` / `SPRAY_MEAN_DEG` / `BATTED_BALL_MIX` and `sweep()` live here; `tests/conftest.py` re-exports the samplers under their old names. **`realistic_contact` is the joint draw and is what callers want**: quality and batted-ball type are two readings of the same undercut, so drawing them independently — which this harness did — builds a batter whose pop-ups are struck as hard as its line drives (measured medians 0.671 against 0.868). It samples the *launch angle* and derives the shape from it, because `ball_flight` flies the angle now and a caller supplying only a shape gets the band centre back. Every constant here was re-measured through the real seam on 2026-09-10; `BATTED_BALL_MIX` had been taken from 170 recorded rows written by the *superseded* prior-table model (0.459/0.276/0.235/0.029 against a measured 0.408/0.241/0.281/0.069 — pop-ups out by 2.4x), which is the hazard about `strikefactor.db` holding several contact-geometry vintages at once. A band asserted in a test and a number quoted in a doc can only mean the same thing if one definition produced both — CLAUDE.md records four miscalibrations caused by drifting copies of exactly these numbers.
- **`tools` is deliberately outside the installed package** (`packages.find` covers only `strikefactor*` and `analysis*`), which is why `[tool.pytest.ini_options] pythonpath = ["."]` is needed: an editable install's finder does not expose it.
- **Test bands are deliberately wider than the harness's numbers.** A test has to pass at a sample size a test can afford, and adjacent rungs sit inside each other's noise at n=260. Tune at n>=2500; use the suite to catch a regression.
- **The HR column is read off `park.fence_verdict`, not off the animation.** The harness forces `IN_PLAY` — the home run is decided upstream in `HitOutcomeManager._resolve_outcome` — and for a long time there was deliberately no column, on the argument that a sweep here can never produce one. What made one necessary is that a ball the verdict calls gone still gets *flown*, to a landing clamped inside the fence under a hang time long enough for the outfielder to be standing there, and so it came out a **fly out**: ~2% of fair contact scored as the defense's doing, which made any change to the home-run rate read as a change to the fielding. `measure` sets the gone balls aside after the fact (the RNG stream and every memoized sweep are untouched), so BABIP is a real BABIP and HR% is what the fence says. **It changed the ladder's BABIP by +.004 and nothing else**, which is the measure of how much home-run contact the outfield was being credited with.
- **It found the error rate was ~1.4x hot, and why** (fixed 2026-09-02). The ladder measured **5.40 / 3.28 / 2.08 / 1.12%** of balls in play against MLB's ~1.5% at LEAGUE, while BABIP agreed closely with the documented figures — so the drift was specific to errors. Cause: `field_misplay_p`'s derivation modelled `E[p_out_clean − p_out]`, the **bobble** conversion, and was read as though it gave the total. Measured at LEAGUE, the bobble is much the smallest of three mechanisms — BOBBLE 39% of them become errors (0.28% of BIP), THROUGH 93% (1.56%), MUFF 100% (0.24%) — because a through-ball had no race at all, so the batter has reached by construction and only the counterfactual is left. Rescaled ×0.72 across the ladder to **3.84 / 2.48 / 1.56 / 0.72%**. The lesson is in the module comment: two things the closed form cannot see (the ~3.18× gain modulation, and how often a fielder reaches the ball at all), so **measure this dial, do not derive it**.
- **Next calibration item, measured but not tuned (re-measured 2026-09-10, after the flight model became continuous):** BABIP is **.219** at LEAGUE against MLB's ~.300, and it is entirely line drives and fly balls — GROUNDER .259 against MLB's .24 and POP_UP .083 against .02 are fine, while LINER runs **.416 against .68** and FLY **.073 against .12**. The cause is the one CLAUDE.md already predicted would be the residual: `hit_animation.FIELDER_HOMES` is static and was implicitly calibrated against the old, ~15%-short carry model, so with liners now landing at a median of 314 ft the outfielders (302-320 ft) are standing exactly where the ball comes down. Home runs run 6.6% of balls in play on a contact swing and 12.1% on a power swing against MLB's ~4-5%, from the same root. **This is a two-variable fit** — the outfield alignment and the per-shape exit velocity (`QUALITY_BY_SHAPE` maps a line drive to ~100 mph against MLB's ~94) — not another single pass. The pre-change figures, for comparison: BABIP .324 and a ground-ball hit rate of 29.8% against ~24%. `body_block` is the named dial, but it and `field_misplay_p` interact — raising the block removes through-balls, which are also most of the errors — so it is a two-variable fit, not another single pass. The infield-hit rate is in band at **7.9%** (MLB 6-8%).
- **That item got harder, and the reason is worth more than the numbers (2026-09-16).** Letting a fielder catch what he is standing under — the two eligibility fixes under [Hit Animation](#hit-animation) — took **BABIP .248 → .218** at LEAGUE, measured with `python -m tools.calibrate_defense --n 2500 --seed 808` on either side of the change. It moves the same ~.030 at every rung (sandlot .346 → .313, minors .280 → .248, gold_glove .213 → .183), and **ERR%, GB-hit% and IF-hit% are identical to the digit at every rung** — which is the check that it touched only airborne balls. Per shape over the same sweep, hits: GROUNDER .279 → .279 (bit-identical), LINER .433 → .404, FLY **.103 → .035** against MLB's .12, POP_UP .069 → **.000** against MLB's .02, with each shape's error rate unchanged. **FLY is the gap now**, and it is the alignment directly: the outfielders are standing where these balls come down.
  - **The alarming column is 2B/1B, which fell 0.33 → 0.17** against MLB's ~0.33, and it had been the one rate sitting exactly on its target. It was on target *for the wrong reason*: every ball that reached the fence was an automatic double, so an artifact was supplying the extra-base hits the outfield alignment was not. **A rate that matches MLB is not evidence the model is right**, and this is the cleanest example of it in the codebase — the artifact and the error cancelled, and removing the artifact is what exposed the error. Expect it back in band from the alignment refit, not from a dial here.
  - Nothing above changes the named remedy or makes it more urgent than it reads: it is still `FIELDER_HOMES` against `QUALITY_BY_SHAPE`, still a two-variable fit. What changed is that the hits masking it are gone, so a fit now has a clean signal to fit against.
  - **Two height constants put it back, and neither was a dial being turned** (same day, same harness and seed). The catch ceiling was 23 ft where its comment claimed 10, and the fence was 8 ft where the glove is 8 — a coincidence that made every ball off the wall catchable. Fixing both took LEAGUE **BABIP .218 → .247** and **2B/1B 0.17 → 0.28**, with the ladder at .346 / .278 / .247 / .212. Per shape: LINER **.404 → .495** (the ceiling), FLY **.035 → .068** (the fence), GROUNDER .279 and POP_UP .000 both unmoved, and the home-run share **6.3% → 4.9%** of fair contact, inside MLB's 4-5% for the first time. **Both were wrong in the direction that made the game harder, and both were found by asking what a number meant in feet** — which is the argument for the unit discipline this file keeps insisting on, stated as a saving rather than as a rule.
  - What was left at that point: **BABIP .247 against ~.290, LINER .495 against .68, FLY .068 against .12**, and the outfield standing where the ball comes down. 2B/1B at 0.28 against 0.33 was *short* by real doubles rather than propped up by fake ones.
- **The arc became the flight model, and it was nearly free (2026-09-16).** Replacing the per-shape pixel arc peak with `ball_flight.height_at_distance_ft` — see [Hit Animation](#hit-animation) — moved the ladder from **.346 / .278 / .247 / .212** to **.347 / .279 / .248 / .211**, i.e. within ±.001 at every rung. That is a much smaller move than the ~.030 the last two height fixes each produced, and the reason is worth keeping: the old peak was *already* the right order of magnitude for liners and flies (20–35 px physical against a drawn 25–40; 55–77 against 60–130). What it was not was *tied to anything* — it was `random.uniform`, so the same contact got a different catchability every time. **The gain here is determinism, not a rate.**
  - **GB-hit% and IF-hit% come back identical to the digit at all four rungs** (41.9 / 32.9 / 27.9 / 23.0 and 15.8 / 9.2 / 6.2 / 4.2), which is the control: the grounder keeps its pixel hop schedule and its pixel catch gate verbatim, so a ground ball cannot have moved. Per shape at LEAGUE, GROUNDER **.279 → .279** and POP_UP **.000 → .000** likewise.
  - **The airborne shapes moved in opposite directions and both toward MLB.** FLY **.068 → .086** against .12, LINER **.495 → .475** against .68. The liner is the interesting one: the physical arc does not lower liners uniformly, it *swaps which ones are catchable* — a soft 85 mph liner drawn at a random 22 ft over the shortstop is physically at 7.8 ft and a routine lineout, while a 24° liner is genuinely over everyone. That is correct baseball in both directions.
  - **2B/1B went 0.28 → 0.31 at LEAGUE** (ladder 0.33 / 0.31 / 0.31 / 0.26) against MLB's 0.33, closing most of the gap the last fix left open — and by real doubles off the wall rather than by an artifact. ERR% eased slightly (1.08 → 1.04 at LEAGUE, 3.68 → 3.32 at sandlot), all of it MUFF: a ball whose height is now modelled is one a fielder is less often standing under by accident.
  - **The home-run share is the untouched control and it holds at 4.88%** of fair contact against the documented 4.9% — `park.fence_verdict` never entered this change, so anything else would have meant something reached it that should not have.
  - `tools/calibrate_defense.py` grew **`--by-shape`** for this, because CLAUDE.md quoted four per-shape hit rates that the harness could not produce — they had been measured by hand off `sim.sweep`, which is the exact complaint the harness exists to answer. The shape is the one axis *independent* of the fielding model, since `hit_outcome_manager` classifies it at contact, so it is what says which part of the model a change actually moved.
  - The named remedy is unchanged and no more urgent than it was: **LINER .475 against .68 and FLY .086 against .12** are still `FIELDER_HOMES` against `QUALITY_BY_SHAPE`, still a two-variable fit. What this change buys that fit is a physical arc to fit against instead of a random one.
- **The arc became the *right* flight model, and it was not free (2026-09-16, later the same day).** The parabola above was the right order of magnitude and the wrong shape — see `DRAG_APEX_ANCHORS` under [Batted-ball physics](#batted-ball-physics-ball_flightpy-ground_rollpy-infield_timingpy-extra_basespy). Measured on the HR-aware harness, same seed, three states at LEAGUE:

  | | HR% | BABIP | 2B/1B | LINER | FLY |
  |---|---|---|---|---|---|
  | vacuum arc, old EV table | 4.08 | .252 | 0.31 | .471 | .087 |
  | real arc alone | 6.00 | .250 | 0.25 | .479 | .065 |
  | real arc + EV top pulled in | **4.08** | .246 | 0.23 | .482 | .061 |

  - **The arc alone moves ~1.9% of fair contact from doubles off the wall to home runs**, and that is the physics, not a dial: the off-the-wall band is the set of balls arriving at the fence between the grass and the rim, and on the real descent it is about **2.4 mph** of exit velocity wide at a 30° launch, because past the fence a real ball is still 60-90 ft up. The flat arc had it several times wider, and the extra wall balls were most of the model's doubles. **2B/1B at 0.31 was on target for the wrong reason a second time** — the first was the automatic-double rule this file records above — and it fell to 0.23 when the artifact went, against MLB's 0.33. What is left is real: the outfielders stand where these balls land, which is the `FIELDER_HOMES` / `QUALITY_BY_SHAPE` fit this file has named three times now, and this change gives that fit a physical arc *and* an honest doubles count to fit against.
  - **The home-run rate is held by `EV_CALIBRATION`, not the fence.** The top three rows came in 101/106/112 → 99.5/103/108 at p75/p90/p99 (Statcast ~98-99/~104/~110; the batter's line drives had been measured at ~100 mph against MLB's ~94). A flat EV shift holds the same rate but slows every grounder with it and leaves the line-drive share of home runs at 21%; compressing only the top takes it to ~15% against MLB's 25-30%, with the HR launch-angle p10/p50 at 24/32°. The 105+ mph liner that leaves a real park still leaves this one; there are fewer of them. **GB-hit%, IF-hit% and ERR% are identical to the digit across all three states**, which is the control that the change touched only airborne balls. Power swings are untouched and still run ~10% HR; `EV_POWER_BONUS_MPH` is the dial if that reads as cheap.
  - **A ball off the wall is gloved only if it arrives under about 5 ft**, not 8. The catch is asked on the frame the shadow reaches `BALL_WALL_LIMIT_NORM`, ~2.7 ft in front of the face, and a ball falling at a foot per foot of path is that much higher there. `tests/test_catchable_in_flight._WALL_BALL_HEIGHT_FT` bisects the fixture on *height at the fence* for exactly this reason: bisected on the midpoint of the band, as it was, the ball arrived 6 ft up the face and ~8.5 at the catch, over every glove on every seed, and the ordering tests had nothing to exercise. `FIELDER_WALL_MARGIN_PX` was suspected and measured — 8 px, 2 px and 0 give identical catch counts at every arrival height — so it is still cosmetic.
  - **A wall-scraper's rim clearance is solved a frame *past* the fence** (`HR_RIM_CLEARANCE_FT`, 2.5 ft of path). The animation samples once a frame, the crossing frame is up to a frame's travel beyond the fence, and on the real descent that is 1.3-2.1 px of drop at 60 fps; solved at the crossing itself a 45° scraper drew its bottom edge a pixel into the face on the one frame the viewer is watching for.

### The misplay model and `REACHED ON ERROR`
Three mechanisms, told apart by **what happens to the ball**: a **BOBBLE** is retained and costs seconds on the release clock; a **THROUGH** ball is not stopped at all and carries into the outfield; a **MUFF** is dropped and dies at the fielder's feet. All are one latched roll per batted ball (`_roll_misplay`), taken at the moment a fielder first reaches the ball — *not* at setup like `PITCHER_CLEAN_FIELD_PROB`, so the fielder is seen making the attempt and failing rather than never routing to it.
- **The rule is stated once, as `infield_timing.verdict_from(p_out, p_out_clean)`**, because a play can reach it without a race having run. A ball that goes *through* a fielder is the `p_out = 0` case — nobody threw, so the batter reached, and the only question left is whether the clean play would have been an out, which is exactly the window `[0, p_out_clean)`. `_trigger_through` used to write that out as its own second draw 400 lines away, guarded by a `role in OUTFIELD_ROLES` short-circuit asserting that a ball through an *outfielder* is always an error. That short-circuit fired **zero** times in 5000 plays (a through-ball comes only from `_check_in_flight_intercept`, which outfielders do not reach) and asserted the opposite of what the model says: `_clean_play_p_out` is ~0 at 250 ft, so a ball past an outfielder is a hit — and an outfielder who *drops* one is a MUFF, charged unconditionally. Removing it changed nothing measurable and made the general rule the only rule.
- **One draw, three outcomes.** `infield_timing.roll_verdict` computes `p_out` (with the misplay) and `p_out_clean` (without) and draws **once**: the window `[p_out, p_out_clean)` is exactly the set of plays the misplay cost, which is the official scorer's rule arrived at rather than judged. Two independent draws would charge errors on plays the runner was beating anyway. It also makes the picture and the record structurally unable to disagree — the throw is scheduled off `release_s`, which contains `misplay_s`, and the verdict is drawn against `p_out`, computed from the same number. With no misplay the window is empty and this is a plain draw against `p_out` (the superseded `roll_is_out` is gone).
- A ball never goes "through" a fielder who was going to catch it — that is a drop. And a through-ball fires only from `_check_in_flight_intercept`, never the securing gate: a ball does not go through you while you are jogging up to a dying roller, which keeps the slow roller the canonical *infield hit* rather than the canonical error.
- **A dropped fly ball or pop-up is a MUFF, and so it is an error rather than a hit.** This is the only way a ball somebody was under can fall in, and it is the *right* way: the fielder got there, so the batter did not earn a hit, and the official scorer's rule is what `verdict_from` already states. It is worth writing down because the alternative keeps getting built by accident — an eligibility rule that forbids the catch produces the same ball on the same grass, but scores it a double and charges nobody (see `_eligible_intercept_pool` under [Hit Animation](#hit-animation), where that happened twice). **The tell is the scoring, not the picture**: if balls are falling in with a fielder camped under them and the box score shows hits rather than errors, the misplay model is not what is dropping them. Measured over 1,500 pop-ups: 0 hits, 0.73% errors.
- **A through-ball keeps the speed it actually had**, off `infield_timing`'s retention curve — not the nominal landing speed `_init_ball_on_ground` builds for the shape. Scaling the latter left the ball dead 16 ft on, so the fielder turned round and picked it up on 28 of 35 through-balls and a third were still outs. Fixed: median 104 ft past the fielder, 8 of 35 recovered, 2 of 35 outs.
- **`REACHED ON ERROR` is neither a hit nor an out**, and the vocabulary is free text matched by exact string in about a dozen places that **fail silently** on an unknown value. The three that would have: `pitch_simulation._finalize_batted_ball`'s binary `is_out` (which credited a hit and fed the batting heatmap), `PitchDataExtractor.TERMINAL_OUTCOMES` (a closed frozenset — an outcome missing from it never *closes the at-bat*), and `GameDayTransitionState._player_batting_stats` (which counts `ab` only inside its result lists, so the plate appearance vanished from the AVG denominator). `tests/test_outcome_names.py` guards all three.
- In `analysis/theme.py` it is in `REACH_OUTCOMES`, `IN_PLAY_OUTCOMES` and `TERMINAL_OUTCOMES` but **not** `HIT_OUTCOMES`, `BATTED_OUT_OUTCOMES` or `OUT_OUTCOMES` — which is what makes AVG fall, OBP not rise, and BABIP count it in the denominator only, with no special case in `metrics`.
- `GameStats.outcome_value` is the **Q-learning reward** and is scored from the *pitcher's* side. An error sits near the out value (`+1.0`), because the pitch did its job and the defense lost it. Unmapped it would return a neutral `0`; scored like a single it would teach the AI to stop inducing ground balls.
- **The player is told twice, and neither telling is the record.** `_charge_error(role)` is the one place `is_error` is set — all three mechanisms go through it — and it latches `_error_role` / `_error_marked_at_ms`, which `_draw_error_mark` renders as a brief amber **"!"** over that fielder's head at the instant of the misplay. It is the only thing on screen that reports `is_error` before the banner: an error used to have no picture at all, so a muff read as the ball bouncing oddly and a ball through the shortstop read as an ordinary single. The fielder marked is the one who **misplayed** it, not `_primary_role` — a ball through the SS is retrieved by the LF, and the LF did nothing wrong. Held 1.10 s and faded over 0.45, stated in real seconds and crossed by `_anim_ms` like every other duration in that file.
- **The banner says `ERROR`; the record still says `REACHED ON ERROR`.** `PitchSimulation._DISPLAY_NAMES` is a display-name map applied in `_format_display_outcome`, the one seam where an outcome becomes words on screen, precisely because the recorded string is matched by exact value in the dozen silent-failure places above. Renaming the *value* to "ERROR" would break all of them; renaming it at the seam breaks nothing. `tests/test_outcome_names.py` pins both halves.

### Spray direction (`spray.py`)
[spray.py](strikefactor/gameplay/spray.py) answers one question — *which way did the ball go* — in real degrees, on the [contact_audio.py](strikefactor/engine/contact_audio.py) pattern. It exists because that question had **four** answers and the one that mattered most was noise: a ball in play drew `random.uniform(50°, 130°)`, a home run biased off the *pitch's* location, a ball that reached the wall picked its side with `random.choice((-1, 1))`, and only a foul consulted the swing at all (through the sign of a timing error). Four models, none of them the bat.
- **The bat already knew, and the bearing was being discarded at a module boundary.** `bat_path._pose` carries a full ground bearing at every instant and `bat_contact` sweeps against it, but `Contact` kept `axis_point_ft` and `along` and dropped the axis. It now carries `attack_deg` and `pose_attack_deg`.
- A cylinder's surface normal is radial to its own axis, so the ball leaves perpendicular to the bat. Three behaviours fall out and **none of them is stated anywhere**: the bat turns as the swing runs, so early pulls and late goes the other way; `_contact_pose` meets an inside pitch further out front, so inside is pulled; and a pitch away is met deeper, so it is not.
- **Location and timing are calibrated separately and in opposite directions**, which is the whole shape of the module. The raw geometry gets both shapes right and both scales wrong: location **over**-responds (`_contact_pose` swings the bat 79° across a two-foot plate, because it is pinned to the engine's screen-space aiming pivot and a real hitter's hands come in on an inside pitch where these cannot), while timing **under**-responds by ~2.4× (0.63°/ms against a real bat's ~1.5, because the sweep finds closest *approach* rather than a fixed phase). A single gain over the raw angle cannot be fitted at all — at the scale that produces MLB foul rates a *flawless* swing on an inside or outside strike is an automatic foul and half the strike zone becomes unhittable. `LOCATION_GAIN` is bounded by that constraint rather than fitted: at 1.30 a flawless swing runs −41° to +35° across the zone, gap to gap, with four degrees of margin at the outside corner. `tests/test_spray.py::test_a_flawless_swing_can_be_fair_anywhere_in_the_zone` is the pin.
- **The location term saturates (`LOCATION_SPAN_DEG`), and that is not a clamp — it is where the geometry stops answering.** Past the point where the bat can no longer span the ball from where the hands are, `_contact_pose` takes the quadratic's vertex: the perpendicular foot from a *fixed* knob to a family of near-parallel camera rays. Its bearing converges — 1.9°/ft of response against 27–136 on the reachable side — on pose ≈ 0, the bat square across with its face normal at dead centre field. That limit is a perfectly good inside-out reach and is harmless. Amplifying it was not: read through a straight line, `8 + (0 − 49) × 1.30` is −55.7°, **thirteen degrees foul**, so every ball the hitter stretched for was an automatic foul, well struck, hooking deep past the same pole every time. Measured in recorded play, 43% of all right-handed contact landed in a **1.5°-wide band at −59°**. `tanh` has slope exactly `LOCATION_GAIN` at the reference, so the middle of the plate is *bit-identical* and only the saturated region bends; the asymptote lands at −34°, opposite field and fair. The pull side has no asymptote to hit (pose keeps climbing at ~26°/ft on an inside aim with no reach boundary), so hooking an inside pitch foul is still possible. On the outside corner this took fair contact 34% → 57% of swings.
- **The flat spot itself is still there — it was made harmless, not removed.** Every ball past the reach boundary still goes to about the same place; it is now a fair place. Closing it means letting the hands come off the stance anchor *laterally*, which is the same fixed-pivot problem named above for the inside pitch, and it is a `bat_path` change that would need both gains here re-derived. Worth knowing before starting: at the knees the boundary sits at an aim of −0.51 ft, **inside** the strike zone. `tests/test_spray.py::test_the_flat_spot_starts_where_the_bat_runs_out_of_reach` records where the edge is so that work has a baseline.
- **The guard test that missed this was a tautology, and it is the reusable lesson.** `test_the_attack_angle_is_continuous_across_the_reach_boundary` asserted monotonicity and that no two aims produced a bit-identical angle. A step is monotone, and two floats out of a trig chain essentially never compare equal — so it could not fail, and sat green over the exact defect it was written to catch. Its replacement measures the *rate*. Any test whose failure requires exact float equality is not a test.
- **The centre share is a BABIP dial as well as a realism target**, which is why `LOCATION_GAIN` sits at the top of its range rather than the bottom. `hit_animation.FIELDER_HOMES` is static and was implicitly calibrated against the uniform spray this replaced, so a centre-heavy distribution puts balls over second base, where middle infielders cannot reach. Measured on one fixed set of fair balls in play: uniform spray gives BABIP .328, this model at a 0.95 gain gives .390, and at 1.30 gives .343. Widening toward the league split and recovering BABIP are the same adjustment; **what is left of that gap belongs to the defensive alignment, not to `spray`.**
- **Raising `TIMING_GAIN` is free in a way raising `LOCATION_GAIN` is not**, and that asymmetry is why they are two constants. A perfectly timed swing has a timing term of exactly zero, so no amount of timing gain can move it; the flawless-swing range is a function of `LOCATION_GAIN` alone.
- **`spray` has no difficulty dial and must not grow one.** Difficulty reaches the ball's direction the way it reaches a real hitter — through `timing_assist_s`, which decides how much of the player's timing error is still on the bat when it arrives. Direction fouls 19% of contact at ROOKIE against 38% at HALL OF FAME with nothing tuned for it.
- **One sign convention, applied in one place.** `spray_angle_deg` is pull-positive for both batters; `field_angle_deg` is the only conversion into the animation's frame. Three coordinate frames meet here and two disagree about the sign of x — world `+x` is the third-base side (note `pitch_physics`'s module docstring says the opposite; the code is what is right), the animation's `field_x = -world_x` with lines at 45°/135°, and screen polar flattens those to ~30.7°/149.3°. A sign error mirrors the batter, which is the defect `collision_angled` carried for the life of the project. Every directional claim in `tests/test_spray.py` is made for both hands.
- **Where the bat pointed is not where a foul went, and `foul_departure_deg` is the difference.** `Contact.is_foul` has two limbs and only one of them leaves a bearing behind: a ball hooked past a pole is already outside the lines, but a ball fouled off *by quality* — tipped, topped, caught on the handle — keeps a perfectly fair-looking bearing while the ball itself deflects into foul ground. Nothing modelled that deflection, so `hit_animation._setup_foul` improvised one in render code out of `random`, and the swing replay drew the bat's bearing instead. `foul_severity` / `foul_departure_deg` state it once, in real degrees, deterministically. Three properties carry it and each has a test: the result is **always** foul (so the picture cannot contradict the banner); it is **continuous with `spray_deg` at the line**, so a ball a degree past the pole draws a degree past the pole and a barrelled ball's deflection is zero; and it can only push the ball **further** foul, never straighten it — the animation's old 45° cap discarded 38° on a swing the bat genuinely sent 128° round. A `POP_UP` is the exception in kind rather than degree: a ball hit almost straight up comes down *behind the plate*, not out past a pole, which is the shape of the most ordinary foul there is.
- **It is handedness-free**, like `spray_angle_deg` and `is_foul`, because it is stated pull-positive. The flip still happens exactly once, in `field_angle_deg` / `world_direction`.
- Spray is **deterministic** given the swing — no jitter term, and that now includes the foul deflection. The spread comes from the player's own aim and timing scatter, and a ball that goes where it was hit is what the swing replay exists to teach. The `random.gauss` in the old foul path was a live counter-example: it meant the animation's own bearing could not be reproduced by anything, including the replay.
- **`bat_path._reach` had to change for this.** It used to answer an unreachable pitch with the bat lying flat in the plane of the plate, whose face normal points at *exactly* centre field — and it fires on 9.6% of swings, so the spray distribution grew a spike one value wide. The pose comes off the quadratic's **vertex** now, which is the analytic continuation of its root, so contact depth can dip below the hands and the barrel trails them. `test_the_attack_angle_is_continuous_across_the_reach_boundary` pins it.

### Hit Animation
[hit_animation.py](strikefactor/gameplay/hit_animation.py) renders a top-down ball-flight animation between hit resolution and the outcome banner:
- **One clock per play.** `PRESENTATION_TIME_SCALE` (1.25) is the *only* place pacing may diverge from physics. Everything physical is stated in real feet and seconds and crosses to the animated clock through exactly two methods, `_anim_ms` and `_travel_ms`; `_ft_dist` converts a screen displacement to feet first, because the projection is anisotropic and a scalar px/ms speed silently means two different real speeds (40 px/s was 21.6 ft/s laterally and 36.4 ft/s straight back). `tests/test_animation_clock.py` guards the boundary.
- **One model of the ball's height, and every decision reads it in feet.** `_flight_height_ft(path_fraction)` is `ball_flight.height_at_distance_ft` over this ball's own launch angle and carry — the same arc `park.fence_verdict` compared against the fence when it decided this was a home run — and `_flight_lift_px` is the one seam it crosses to pixels. There used to be a second model, and it was the one that got drawn: a per-shape peak in *pixels* (`HR_PEAK_H = 200`, a quality lerp over `FLY_HIT_PEAK_RANGE`, `random.uniform` over `LINER_PEAK_RANGE` / `POPUP_PEAK_RANGE`) rendered as `peak · sin(π · phase)`, tied to neither the launch angle nor the carry. **It was not merely redundant — the catch gate reads how high the ball is**, so whether a fielder could take a line drive in flight came out of `random.uniform(25, 40)`; and one frame later, past the landing, the identical expression read a genuinely physical height, because `_init_ball_on_ground` converts `ground_roll`'s `hop.height_ft`. The same number meant two different things either side of the grass. `HR_PEAK_H` is `HR_DURATION_MS`'s twin one axis over — the home run came off its scripted 5000 ms clock for exactly this reason and kept a scripted arc; a 420 ft home run at 27° really does peak at about 54 ft, which is 59 px, not 200. `test_the_render_peak_constants_are_gone` fails if one comes back.
  - **Parameterised on path fraction × carry**, not on radial ground distance, which is what lets one expression cover every case with no branch: a fair airborne ball has `_hit_end` at the carry, so the two are the same number and the height reaches exactly 0 at the landing; it sidesteps `batted_ball_path`'s curve, where arc length and radius differ; and a flight truncated by something other than the ground — a wall ball cut at the fence, a foul pop clamped onto the visible apron — keeps its real apex instead of having it compressed onto the shortened draw. That last one is what keeps a foul pop-up readable at 65–125 px across the whole 55–85° band, since a steeper launch buys less carry.
  - **The path/phase split collapses for the vertical, and that is the cleanest thing the change buys.** `_arc_sine` needed both because a sine's apex sits at half the flight *time* while the ball is elsewhere on its *path* — it had no tie to position at all. A parabola in the path is a function of where the ball *is*, and where the ball is already carries the deceleration. `_arc_phase` and `_arc_landing_phase` are **gone**; `_arc_sine` survives only for the infield throw (`THROW_PEAK_H`), which is genuinely cosmetic because nothing decides anything off how high a throw arcs.
  - **Two fence corrections collapse into geometry.** `_wall_impact_landing_phase` retimed the sine so it would meet the face at the physical height, and `_home_run_peak_floor` raised the peak so a home run would clear the rim — three generations (`WALL_HIT_FLY_PEAK_SCALE`, `_wall_impact_peak_cap`, then those) of solving for a property the geometry now supplies. What is left is `_fence_lift_correction`, one scale on the whole parabola that exists solely because **the drawn ball has a radius and the rim is a line**: a home run clearing by inches draws its centre at 13.75 px against a 13.2 px rim and its *bottom* edge still clips. It is 1.0 unless the ball arrives within about a ball's radius of the rim, and it is the only place the picture may disagree with the flight. It also covers the legacy asserted-HR caller (`HR_MIN_CLEARANCE_FT`), which is the one home run that genuinely does not clear the fence — the picture overrules the flight there because the caller overruled it first.
  - **The GROUNDER is deliberately untouched** and is the last px-unit height model in the file: `GROUNDER_BOUNCE_PROFILE` / `GROUNDER_BOUNCE_COR_SQ` / `_arc_grounder` state its in-flight hops in pixels while `ground_roll` owns hops in feet after the landing — the same two-models-of-one-thing fault, one phase earlier. The catch gate keeps the pixel comparison for grounders verbatim, which is what makes ground-ball outcomes identical across this change and is the control the calibration sweep checks. Unifying it means driving the in-flight hops off `ground_roll.ground_path` too, and it is harder than it looks: the in-flight hop *count* is currently keyed to travel distance to stop a long grounder arcing over the infield, while `ground_roll`'s hops are keyed to speed.
- This replaced two clocks: flight was `HIT_BASE_DURATION_MS * (1.2 - 0.4 * quality)` — an implied 29 mph for a ball struck at 90, and *decreasing* in quality, so the deepest fly balls got the least hang time — while fielders sprinted at a correct MLB speed against it. `INFIELD_LOW_BALL_RANGE_PX`, `INFIELD_CHASE_RANGE_PX`, `FIRST_BASE_GROUNDER_RANGE_PX` and `FIELDER_MAX_SPEED_PX_MS` existed only to correct that and are **gone** — a real sprint against a real flight time reproduces their ~30 ft of infield range on its own. `test_the_dilation_correction_constants_are_gone` fails if one comes back.
- **Anything whose units mention a millisecond or a pixel is suspect.** `ROLLING_DECEL_PX_MS2` and the `RETRIEVE_TIME_*` thresholds were both physics wearing render units, and unifying the clock moved both without anyone editing them (triples went 8% → 23% of hits). Ask of each constant whether a human could state it in seconds or feet.
- **The post-landing phase was the last place that fault survived**, and it is why a ball hit to the outfield used to land, lose half its speed in one frame, take three cosmetic hops and stop 14 ft later (median, over 500 fly balls). `SHAPE_LAND_FACTOR`, `ROLLING_DECEL_FT_S2`, `BOUNCE_COR`, `BOUNCE_INITIAL_DURATION_MS`, `BOUNCE_HEIGHT_THRESHOLD_PX`, `BOUNCE_HORIZONTAL_RETENTION`, `SHAPE_BOUNCE_HEIGHT_FRAC` and `BOUNCE_HEIGHT_MAX_PX` are **gone** — [ground_roll.py](strikefactor/gameplay/ground_roll.py) owns all of it in feet and seconds, and `_init_ball_on_ground` converts once. `test_the_post_landing_render_unit_constants_are_gone` fails if one comes back.
  - The physics crosses to the screen through `_fts_to_px_ms` / `_px_ms_to_fts`, which use the px-per-foot of *the ball's own bearing* for the same reason `_ft_dist` exists.
  - `_step_ball_on_ground` applies exactly one thing at a time: a per-impact retention at each hop boundary, friction **only while the ball is on the ground**, and the wall. Friction running through the hops is most of why the ball used to die.
  - `_forecast_ball` / `_chase_target` let a fielder **charge**. Aiming the chase at the ball's resting point is right for a ball rolling away and exactly wrong for one coming at you — an outfielder at 300 ft would retreat to a predicted stop at 390 ft while a line drive rolled underneath them. That alone took doubles to 69% of hits.
  - `_pick_retrieval_role` decides who goes after a ball nobody can catch, by searching the ball's *post-landing path* rather than asking whose home is nearest the landing spot. It picks the primary in that case and, always, routes the responsible **outfielder as a backup from the first frame** — outfielders run everything down whether or not somebody in front of them has a play. Without that backup, a liner down the line went to the 1B, who missed it by 10 ft, while the RF stood still and the ball reached the wall on 23% of line drives.
  - **Only an in-flight wall strike forces an extra base** (`_wall_hit_in_flight`), not a ball that rolled there. They were the same event when the only way to reach the wall was to be aimed past it; with honest roll physics, rolling to the wall is an ordinary thing for a line drive to do, and `extra_bases` can see both where the ball was retrieved and when.
  - Securing is gated on `GLOVE_REACH_FT` and measured against the ball's **shadow**. Neither mattered when a hop was a 3 px bump; a fly ball's first bounce now clears 7 ft, and without the gate the centre fielder gloves it at the apex.
  - **The wall is a boundary for the defenders and for the camera, and neither is free.** A fielder's *target* is the answer to a physical question — where the ball is, where it will land, where it will stop — and is allowed to be off the field; a HOME RUN or wall-candidate `_hit_end` is past the fence by construction. Only the body is contained, by `FIELDER_WALL_MARGIN_PX` at the mover (`_step_fielder`) and once more over all nine in `update` — one place each rather than at the half-dozen sites a target is set. Purely cosmetic: it fires on ~0.1% of fielder-frames and moves no outcome. Separately, `_point_outside_wall` / `_ball_behind_wall` stop drawing a ball the fence is hiding — the HOME RUN branch of `_update_hit` parks the ball at its landing point, which left a white dot sitting in the black beyond the wall for the rest of the animation. The height term is load-bearing in the other direction: a ball clearing the fence is *above* it, and testing the ground point alone blinks the ball out mid-arc. The out-of-the-park boundary is **the fence itself** (`>= 1.0` in normalized-ellipse units, since a home run's carry past it starts at zero), *not* `BALL_WALL_LIMIT_NORM` — see the carom notes below. `tests/test_wall_containment.py` guards both.
- **The flight decelerates onto the landing speed, so the flight and the roll are one motion.** Horizontal motion used to be linear in time: the ball crossed its whole path at the path's *average* speed and then changed speed in a single frame where `ground_roll` took over — to 53% of it on a 90 mph grounder and 8% on a 45 mph roller (0.61–0.95 across the airborne shapes), which read on screen as the ball hitting a wall of molasses the moment it reached the outfield grass. Not a new model: `ground_roll.grounder_landing_fraction` already derives the end-of-path speed by assuming a uniform deceleration whose time-average is the retention curve's `r · v0`, and the animation simply flew the average of that profile instead of the profile. `_decel_path_fraction(u, f) = (2−f)u − (1−f)u²` flies it, parameterised on `f` = landing speed ÷ average speed (`_landing_speed_ratio`, read off the same cached `GroundPath` that `_init_ball_on_ground` starts the roll from). Three things make it safe and are easy to undo:
  - **Both ends are pinned**, so `flight_time_s`, `duration_ms` and every whole-flight schedule are untouched — which is what lets it sit under models calibrated on the full path. The implied contact speed `(2−f)·v_avg` is the check that it is physics rather than an easing curve: it comes out at exactly the exit velocity on a grounder and at 145 ft/s against a physical 143 on a 100 mph liner.
  - The arc helpers take **two parameters, path and phase** — position from `p(u)`, vertical shape from the flight *time*. Grounder hops are spaced over the phase, so a decelerating ball takes equal-duration hops covering less and less ground; spacing them over the path instead makes the last hop of a dying roller one long float through 58% of the flight.
  - `_path_intercept` inverts the ease (`_decel_time_fraction`) instead of using `t_proj · duration_ms`. A decelerating ball is *ahead* of the linear schedule everywhere in between, so the linear one told an infielder they had time on a ball already past them — line-drive outs ran 8 points high because of it. `tests/test_animation_clock.py` guards the handoff, the ease and this timing.
- **A batted ball has exactly one exit velocity.** `contact_audio.exit_velocity_mph` jitters on purpose, so it must be drawn *once* — `HitAnimation.exit_velocity_mph`, now taken from the `ev_mph` kwarg whenever the caller has one. Carry, hang time, wall candidacy and the infield verdict were each calling it separately, so one ball could get a 380 ft carry and the hang time of a 340 ft one. **"Once" means once across the pitch, not once inside this object**, which is the half that was missed: the contact sound drew a fifth one, and that draw is what the DB and the swing replay report. See [Contact Audio](#contact-audio).
- **Every direction decision reads one number.** `spray_deg` (pull-positive degrees, from [spray.py](#spray-direction-sprayspy)) is resolved once in `__init__` into `spray_field_rad`, and the four sites that used to answer independently — the ball in play, the home run, the ball that reaches the wall, and the foul — all take it. `horizontal_inside`, `foul_timing_norm`, `IN_PLAY_ANGLE_MIN/MAX`, `HR_INSIDE_NORM_PX`, `HR_PULL_SHIFT_RAD`, `HR_BASE_PULL_RAD` and `FOUL_OFF_MIN_RAD` are **gone**. `_screen_angle_of` is the one crossing from real-field bearings to screen polar, which anything reaching the wall needs because the wall is a screen-space ellipse.
  - The IN_PLAY landing keeps calling `_polar_point_ft(angle, dist_ft)` positionally — `tests/test_animation_clock.py` monkeypatches it by position and fails confusingly if the call shape moves.
  - `_fair_field_angle` insets by half a degree rather than clamping. Fair balls are bounded inside the lines by `spray.FOUL_LINE_DEG` already, so the only ball it moves is one landing at exactly 45.0°; a real clamp here would stack contact onto the two boundary angles, which is the defect `_sample_hr_angle` exists to avoid.
  - `HR_ANGLE_SIGMA_RAD` came down from 20° to 7°. It was noise around a mean carrying very little information (the old location bias could shift it 29° at most); the mean is a real measurement now.
  - **`_setup_foul` no longer has a direction model, and that is the second time it has lost one.** It reads the bearing it is handed, exactly as the fair path does. The first loss was the *sign of a timing error* against a window of hand-tuned milliseconds, replaced by `spray`; but only the sign was replaced, and this method went on inventing the **magnitude** out of `quality` plus three `random` draws while the swing replay drew `Contact.spray_deg`. Over 600 recorded fouls the two disagreed by a median of **40.7°**, 271 of them drawn by the replay as a *fair* ray under a FOUL banner, and on 272 the animation flew the ball behind the plate while the replay pointed forward. It was not even reproducible — one identical contact animated at eight different bearings — so no replay could have matched it. The deflection is `spray.foul_departure_deg` now, resolved once at the handoff; `_setup_foul` keeps depth, arc height and which fielder drifts, and reads `severity` *back off* the bearing so the foul-HR gate and the flight cannot come from two severities. `FOUL_OFF_MAX_RAD` and `FOUL_HR_OFF_RAD` are **gone**; the foul HR crosses to screen polar through `_screen_angle_of` like everything else that reaches the wall. Median disagreement is now **2.4°**, which is `batted_ball_path`'s bend between departure and landing — and the replay draws that too.
  - **The two ways to foul a ball still draw as two different pictures**, which is worth keeping and now lives in `spray`: a ball hooked just past the pole was struck cleanly and hugs the line, a glancing one sprays sharply foul.
- **HitAnimation class**: Geometric primitives only (no sprite assets). Three motion layers:
  - **Trajectory shape**: `GROUNDER` / `LINER` / `FLY` / `POP_UP`, chosen by `_pick_shape()`, which takes `hit_outcome_manager`'s resolved `batted_ball_type` when there is one and otherwise derives it from the contact's own launch angle (`_shape_from_offset`, the same `ball_flight` model the classifier uses, so the two cannot disagree). **The game no longer reaches that fallback**, and the reason it used to is worth keeping: `_start_foul_animation` passed `batted_ball_type=None` on every animated foul, because a foul never runs the hit pipeline that resolves a type — so the shape was decided *here*, by re-rolling `launch_angle_deg`'s jitter, and could not be reproduced afterwards. Since the shape decides whether a foul is popped up behind the plate or sprayed past a pole, that made the whole bearing unreproducible with it. `PitchSimulation._compute_foul_contact_metrics` now resolves it once into `_foul_shape` — through the *classifier a ball in play uses*, not a second copy — and passes it in. It is kept off `batted_ball_type` and so off the DB, where that column means "a ball in play" and widening it would silently change every aggregate over it; the swing record carries it separately. The fallback stays live for legacy callers and is still pinned. It used to bucket raw pixels, with two thresholds above the reachable offset, so no foul had ever animated as a pop-up. A FLYOUT is airborne by name, so the bands may only choose *which* airborne shape it was. These are *shape* names, a separate namespace from recorded outcomes — `FLY` is not `FLYOUT`, and the shape keeps the underscore in `POP_UP` where the outcome is `POP UP`. The two meet only where `classified_outcome` is assigned.
  - **Fielders**: All 9 defenders visible (`Fielder` class), with per-outcome primary/backup assignments moving toward the play; idle sway keeps them alive at rest. Defaults in `FIELDER_HOMES`. Out vs. hit *emerges* from whether anyone reaches the ball, so two corrections keep balls up the middle honest: the pitcher carries a follow-through reaction bias (`ROLE_REACTION_BIAS_S`, real seconds) plus a per-play clean-fielding roll (`PITCHER_CLEAN_FIELD_PROB`) that drops them from the intercept pool on hard contact. Infielders are **no longer range-capped** — the cap corrected the old dilated clock and the honest one reproduces it; what bounds them now is time. `_max_intercept_dist` / `_range_limited_point` survive for the genuinely positional limits (`ROLE_MAX_INTERCEPT_DIST_FT` for the pitcher and catcher, `FIRST_BASE_GROUNDER_RANGE_FT` for the 1B, who owes the bag) and are **stated in feet**, so a fielder's range is a circle on the field rather than on the screen.
  - **Whose ball it is**: among fielders who can make the play (`_path_intercept().can_make`), the primary is the one with the least ground to cover — *not* the earliest intercept. Ranking on the moment of intercept hands the ball to whoever stands nearest home plate, since the ball reaches their stretch of the path first: a grounder hit dead at the 2B was fielded by the 1B 100% of the time, and on FLY/POP_UP (where every fielder routes to the same landing point and therefore ties) the winner was decided by pool order. `can_make` excludes fielders *behind* the contact point but deliberately not those past the landing spot — a ball dying in front of a fielder is a fielder charging, the most ordinary play there is.
  - **Who may catch it is a question about where the ball goes, not about which shape it is** (`_eligible_intercept_pool`), and the two rules that said otherwise produced the same picture: a fielder camped under the ball, the ball landing on him, and an extra-base hit. **Only the grounder keeps a shape-level rule**, because a ball on the ground genuinely has to reach the outfield to be an outfielder's.
    - **A ball on its way to the fence was not checked at all.** The catch check was skipped outright for wall candidates, because those "pass every fielder by design" — true of the coin flip that once picked them, which also aimed the ball into a gap, and false of `park.fence_verdict`, which picks them off *this ball's* carry along *its own* bearing. So a fly carrying 402 ft straight at the centre fielder was one, and it was an automatic extra-base hit: over 2,500 balls in play **all 72 wall candidates were doubles**, and on 60 of them a fielder stood inside glove range at glove height while the check was forbidden to run. There was also nothing left to protect. A ball is off the wall **precisely when it reaches the fence below the 8 ft rim** — anything higher cleared it and is a home run — so every wall ball arrives at catchable height by construction, and whether it is caught is the ordinary question of whether somebody got there. About one in six still are not, and those still carom.
    - **The catch is asked before the fence is**, and the ordering is the whole of it. `_maybe_trigger_in_flight_wall_impact` plants the ball at the face and truncates the flight on the crossing frame, so if it runs first — where it used to sit — the catch check then finds the ball sitting at the wall and hands the carom to whichever fielder happens to be standing there, which is a ball rebounding into somebody rather than a catch.
    - **Outfielders could not catch pop-ups.** `POP_UP` is a launch angle over 50 degrees and nothing else since the flight model became continuous, and at these exit velocities that carries: pop-ups land a median of 178 ft out and reach 380. The shape's name stopped meaning "over the diamond" while the pool went on assuming it did, and it showed up at both ends of the same sweep's 178 pop-ups — **10 fell for hits** (5 singles, 5 doubles), 9 of them with a fielder inside glove range at glove height and the traced ones standing **a pixel and a half** from the ball; and every one of the 167 that *were* caught was caught by an infielder, the SS and 2B taking balls landing a median of 212 ft away and sprinting up to 157 ft to do it. P and C stay out, which is the half of the old rule that was right: infielders call both of them off in fair territory.
    - **A pop-up can still fall in — as an error, never as a hit.** That is the misplay model doing it rather than an eligibility hole, so it is a **MUFF**, charged through `_charge_error` and recorded `REACHED ON ERROR`. Measured over 1,500 pop-ups: 0 hits, **0.73% dropped**, split across shallow and deep and across both infielders and outfielders. A pop-up falling for a *hit* means somebody was not allowed to catch it, which is the defect above.
    - **How high a fielder can catch is `GLOVE_REACH_FT`, and it is no longer converted at all** — the gate asks `_flight_height_ft` in feet, so `INTERCEPT_MAX_LIFT_PX` is **gone** for airborne balls and survives only on the grounder's pixel path. A decision must not read the picture, and this one did. It was a bare `25` under a comment reading "px ≈ ft × 2.5 at the render scale" — and the render scale is `FT_TO_PX_Y` = **1.10**, so what read as a 10 ft ceiling was a **23 ft** one and fielders were catching balls two storeys over their heads. Same units drift this file records for `EV_CALIBRATION` and the batted-ball offset anchors, and the tell is the same: nothing could state it in feet. Worth **8 points of line-drive BABIP** on its own (.406 → .492 at LEAGUE over 2,000 balls in play), since the ball a fielder is not tall enough to reach is exactly the liner over the infield that should fall in. **Fly balls are untouched** at .039 — a fly comes *down* through this ceiling into a waiting glove, so where the ceiling sits never decided one.
    - `tests/test_catchable_in_flight.py` pins all of it, including the two regression guards — a ball nobody reaches still caroms, and a shallow pop-up still belongs to the infield. `conftest.uncaught` is how the wall-*rendering* tests still get a ball to the fence: they are about the picture, and which wall ball beats the defense depends on where the defense is standing.
  - **Every fielded infield grounder shows a play on the ball**, and both ways a fielder can end up holding one schedule it through the same method (`_begin_infield_play`). It used to live inline in `_trigger_in_flight_intercept`, so only a ball cut off *in the air* ever got a throw drawn: a grounder secured after it had already landed ran its race in `_resolve_extra_bases` and jumped straight to the banner — the fielder reached the ball and GROUNDOUT appeared, with no throw and nobody covering first. That is exactly the slow roller, which dies short of every set position and so is *never* intercepted in flight, i.e. the most ordinary infield play there is was the one with no picture. The two paths differ only in how the ball reached the glove, which is `_resolve_ground_ball`'s business (it reads `_secured_at_ms` for precisely that) and not the throw's; `unassisted` was the one that had actually drifted, hard-coded `False` on the ground path so a first baseman who picked the ball up beside the bag was modelled as throwing it to somebody. Unifying it changed **zero verdicts over 900 balls in play** — the fix is presentational. `tests/test_fielding_assignment.py` pins all of it, including that a SINGLE still shows the throw: an infield hit is a race the runner won, not a ball nobody played.
  - **`_post_fielding` is not `_secured_in_flight`.** The first means a sub-animation owns the ball's position and the finish clock (the catch hold on a fly, the throw to first on a grounder); the second means the ball never landed. Gating the throw on the second is what caused the bug above, and the two must not be re-merged — a ball picked up off the grass is still a play.
  - **`_resolve_extra_bases` runs before `_stand_down_non_primary`, not after.** The stand-down sends every non-primary fielder home, and on an infield grounder the resolve is what names the cover man, so doing it the other way round left the throw arcing to an empty bag. `keep_at_bag` then spares whoever was just assigned.
  - **First base is a strict priority list**, not an ETA race: `COVER_ROLE_PRIORITY = ["1B", "P", "2B"]`, first one who isn't fielding the ball and can beat the throw (`COVER_IN_TIME_BUDGET_S`, measured from **when the ball gets fielded** — `_fielded_at_ms` — not from contact, because the cover man has the whole flight to get there). The 2B covering first is a busted play and lands at ~1% of grounders. Two things make the pitcher's 3-1 work and are easy to undo: `Fielder.break_delay_s` (the follow-through bias in `ROLE_REACTION_BIAS_S` is recovery time before they can *field*, and charging it against a run to the bag vetoed them on every 3-1), and `_check_in_flight_intercept` skipping the cover man, whose route to first crosses the flight path of anything hit at the 1B. `tests/test_fielding_assignment.py` guards all of it.
  - **A ball off the wall strikes the *face*, comes down it, and is never hidden doing either.** Reported as "the ball appears to go over the wall, then clips and abruptly reappears in play". Three independent causes, all in the handful of frames around the carom, all purely how the ball is drawn — an A/B over 900 balls in play changes **zero outcomes**.
    - **The impact height was a leftover.** The arc is aimed 5–35 ft *past* the fence and `_maybe_trigger_in_flight_wall_impact` cuts it when the ground point crosses, so how high the ball was at that moment was whatever the arc happened to give: measured over 162 wall balls, **54% were drawn above the top of the fence when they struck it** — median 12 px against an 11 px fence, out to 27.8 px — and were then planted on the grass in one frame. `WALL_HIT_FLY_PEAK_SCALE = 0.60` existed to prevent exactly this and could not, because the height at the fence depends on where the arc was *aimed* and how the flight is *paced*, and a scale on the peak sees neither. It is **gone**, replaced by `_wall_impact_peak_cap`, which inverts `peak · sin(π·phase)` for the peak that puts the ball `WALL_IMPACT_MAX_HEIGHT_FRAC` of the way up the face at the crossing — solved rather than guessed, and shape-independent (only FLY has ever reached the fence: `ball_flight` caps a liner's carry at ~320 ft against `WALL_REACH_FT`'s 380, which is why nobody noticed the scale was FLY-only). It has to run after `_flight_end_speed_ratio` is set, not beside the peak. **The decelerating flight ease is what made this the common case**: the last 2% of the path is covered over the last 10% of the flight *time*, and the arc's height is keyed to the time — the same measurement on a linear flight gives a median of 7.8 px.
    - **And the impact height is now in feet, not in fractions of the face.** `_wall_impact_lift_px` took the physical height at the fence as a *fraction* of `WALL_IMPACT_MAX_LIFT_PX`, which looks equivalent to converting it and is not: that constant is the face *less the ball's radius*, so every height came out short by that radius' share — 10 ft up a 12 ft fence drew at 8.5 px where `FT_TO_PX_Y` gives 11.0. Harmless while a ball at the fence could not be caught; **the moment one could, it put a ball two feet over a fielder's glove into it**, because the catch gate then read the drawn lift. The failing test found it on the first seed, which is the argument for writing the behavioural one rather than only pinning the constant. **Both of these bullets are history now**: the drawn arc *is* the flight the verdict was computed from, so the height at the fence is the verdict's own number and there is nothing left to aim, pace or scale. `_wall_impact_lift_px` is `_flight_height_ft` evaluated at the wall.
    - **A decision must not read the drawn ball, and `_ball_past_fielder` was the last one that did.** It measured the infielders' bail-out distance from `self._ball` rather than `self._ball_shadow` — and lift is *up* the screen, which is the same direction as away from home, so a ball in the air read as further out than its ground position by its whole height. Its docstring had always said it meant the ground distance. Measured on the full ladder at n=2500 it changes **nothing to the digit in any column**, which is what makes it a correctness fix rather than a calibration one.
    - **Then it falls down the face** (`_begin_wall_drop`), free fall from rest over `sqrt(2h/g)`, while the rebound carries it back into the field. Vertical only; `_bounces_end_ms` is set to the fall so `_integrate_ball`'s existing airborne gate suspends friction for exactly as long as the ball is off the ground. Largest single-frame drop went from 19–31 px to under 1.2.
    - **`_point_outside_wall` tested the wrong line.** It used `BALL_WALL_LIMIT_NORM`, which is where a *rolling* ball is held — 8 px inside the fence at centre, 11 down the line — so a band in front of the fence read "out of the park" and `_ball_behind_wall` blinked a low approaching ball out for its last several frames. And the impact point itself was `wall_r - BALL_WALL_MARGIN_PX`, **a radial subtraction where the constant is normalized against the smaller semi-axis**, so it landed *outside* that line at every angle but dead centre and the ball was hidden on the very frame it hit the wall, on every carom. Both fixed: the boundary is the fence, and the carom point is `wall_r * BALL_WALL_LIMIT_NORM`, the one expression of the line the containment step uses.
    - **A test that builds a `HitAnimation` with no `spray_deg` cannot see the second of those**, because dead centre is the one bearing where the ellipse radius equals the semi-axis and the two expressions coincide. Same trap CLAUDE.md already records for the infield-hit rate, one axis over.
  - **HR distance overlay**: Readout computed from the actual landing point once the ball clears the wall (home runs only — see [Hit Animation](#hit-animation) notes on fouls). It is revealed *after the landing*, not during the flight (`_hr_distance_alpha`, `HR_DISTANCE_REVEAL_DELAY_MS`): the number is the payoff, and fading it in at 70% of the flight answered the only question the flight was asking. The delay is deliberately short — the outcome banner and its continue prompt fire at landing, so a long one lets an impatient player key past the number entirely.
  - **An airborne ball lands where it carries, and all three branches take the same number.** `_pick_hit_landing`'s depth was a per-shape range with a uniform spread inside it, a ball off the wall got a *random* 5-35 ft past the fence, and a home run a *random* 0-61 ft past it — none of which had looked at the exit velocity. All three are `ball_flight.carry_distance_ft` now, at this ball's own launch angle and EV: the same call `park.fence_verdict` made to decide which of the three it was. No spread, deliberately — both inputs are jittered once upstream (`LAUNCH_JITTER_DEG`, `EV_CONTACT_JITTER_MPH`), so a third draw here would be a fourth model of the same variation *and* could land a ball the fence verdict called short past the fence. `WALL_REACH_FT` (a scalar 380 tested against a fence running 360-400, so a fly carrying 365 into the corner cleared it and was not even a candidate), `WALL_HIT_CARRY_FT_MIN/_MAX/_BIAS_EXP`, `HR_CARRY_MIN_FT/_BASE_RANGE_FT/_QUALITY_BONUS_FT/_BIAS_EXPONENT`, `HIT_BASE_DURATION_MS` and `HR_DURATION_MS` are all **gone**. `IN_PLAY_LANDING_FT` keeps only its `GROUNDER` row — a grounder is not a projectile, so where it stops is friction and whether anybody cut it off. Its clamp is still written `mid`-first, because built as `uniform(max(lo, mid - spread), min(hi, mid + spread))` the bounds cross over once `mid` sits outside the range and `random.uniform` samples them backwards.
  - **HR landing** is the physical carry along the swing's own bearing. `_sample_hr_angle` and `HR_ANGLE_SIGMA_RAD` / `HR_FOUL_MARGIN_RAD` are **gone** — they scattered the landing 7° around a bearing the bat had already given, the last place in the file that re-drew a direction, and the fair-ball path next door had never done it. It had to go once the fence decided home runs: the park is 40 ft deeper to centre than down the line, so a bearing jittered inward could put a certified home run in front of the fence. A home run takes `_fair_field_angle` like every other fair ball, and `HR_MIN_CLEARANCE_FT` is a floor only for a caller that asserts the outcome without supplying a flight. Distances now run mean ~425 / p50 ~423 / min ~371, high of MLB's ~400 because the park is deep rather than because the model is generous. **The home run is also on the one clock now**: it used to keep a scripted `HR_DURATION_MS = 5000` and then set `flight_time_s = 5.0` from it, so for that one outcome `duration_ms` was `flight_time_s * 1000` with no `PRESENTATION_TIME_SCALE` in between and `flight_time_s` was carrying an animated duration. `tests/test_hr_distance.py` measures the distribution rather than pinning the roll that used to produce it.
  - **The park is deep down the lines.** `_wall_r_at` is an ellipse in *screen* space, so the wall measures ~360 ft at the foul line rather than the 330 ft the `WALL_FT_X = 330.0` comment implies (330 is the semi-axis at screen angle 0°, which is in foul territory). Sub-360 ft home runs are therefore geometrically impossible, and the short tail of the distribution is compressed against MLB's. Fixing that means reshaping the drawn wall, not retuning carry.
- Field geometry uses anisotropic feet→pixel projection (`FT_TO_PX_X = 1.85`, `FT_TO_PX_Y = 1.10`) anchored to `HOME = (640, 670)` to mimic MLB Gameday's wide, y-foreshortened look.
- `HitAnimation.classified_outcome` is read back by `PitchSimulation` once the animation finishes — only then are score/runners updated and the outcome banner fired.

### Unified Review
V/R/F now enter one modal [ReviewOverlay](strikefactor/ui/review_overlay.py),
not separate game states. See [docs/unified-review.md](docs/unified-review.md).
- **T is deliberately not part of Review.** It is the quick pitch-flight glance:
  `Game.toggle_track` swaps to `VisualizationState` and the same key swaps back
  (to `inning_end`, Sandbox or gameplay). PitchViz is the analytical view; don't
  fold flight back in as a Review tab.
- `ReviewStore` joins pitch points, optional `SwingRecord` and optional
  `FieldingRecord` by an ID allocated **at pitch creation**. Focus and checked
  comparison pitches are independent. Never join the old `last_*` aliases.
- `PitchSimulation._publish_review` is side-effect-free with respect to gameplay:
  it runs after a play finalizes **before Continue**, or at cleanup for an
  unanimated result. Publication is idempotent. Moving swing capture back to
  cleanup alone makes the completed-play screen show the preceding swing.
- `review_modal.run_modal` owns input isolation and paused wall-clock deadlines.
  It does not re-enter the underlying state. Both outer event loops discard the
  pre-modal batch on return so a queued click cannot advance the play.
- `review_views` retains the three data domains: timestamped original screen
  traces, the resolved swing in pitch seconds, and immutable fielding frames in
  original-animation milliseconds. There is no normalized cross-view timeline.
  Fielding never calls `HitAnimation.update` during review.
- GameDay history can be filtered per inning or across the session. Fielding
  retention is bounded by total frames and clip count, with the latest complete
  clip pinned; metadata and swings survive eviction. New sessions clear all
  review state. ABS revises outcome metadata using the same pitch ID.
- Legacy `StatSwing`, view-state classes and `_run_swing_replay_loop` remain for
  compatibility, but normal controls route only to Review. The old extra sidebar
  buttons are hidden. Replay transports do not depend on display FPS.
- **A compatibility wrapper may keep an *entry point* alive; it may not keep a
  second *renderer* alive.** `_run_swing_replay_loop` is free because it drives
  the same `SwingReplayOverlay` that `review_views.SwingView` wraps — one object,
  two ways in. Fielding had no such object: `ui/fielding_replay_overlay.py` was a
  184-line second implementation of `Playback` + `FieldingView` + `ReviewOverlay`'s
  timeline, buttons and key handling, reachable from nothing but a test, and it had
  already drifted — `FieldingView`'s scaled-frame cache (a ~1 ms smoothscale per
  frame spent redrawing an identical paused picture) exists in the live copy only.
  It is **deleted**, along with `Game._run_fielding_replay_loop` and the
  `self.fielding_replay_overlay` field. Its `FieldingRecord.play_label` header
  survives, at the head of `FieldingView`'s stats row. Nothing was preserved by
  keeping it: the whole review stack is one uncommitted change, so the version the
  "compatibility" was owed to has never existed outside this working tree.
- `request_fielding_replay` no longer re-checks `can_review` before delegating —
  `request_review` gates identically, so the three entry points are now one shape.

### Swing Replay
On-demand slow-motion replay of the last swing — bat path, contact point and timing analysis — opened with the `SWING_REPLAY` keybind (default `R`) from any hotkey state. Three pieces:
- **[bat_path.py](strikefactor/gameplay/bat_path.py)**: pure module on the [ball_flight.py](strikefactor/gameplay/ball_flight.py) pattern (real feet and seconds, no pygame) that gives the bat the two axes the game's bat did not have: **time** and **depth**.
  - **The swing is a function of the player's inputs and nothing else** — aim and handedness. Not of the pitch, not of the difficulty, not of which key was pressed. `swing()` used to take a `contact_depth_ft` read off the *pitch's* trajectory at bat arrival, and `hands_contact`, the bearing, the tilt, the rotation radius, the eased exponent and therefore the whole load pose were derived from it: the bat was modelled as a consequence of the ball, which is the two-models-of-one-thing fault in its purest form. It drew a swing 68 ms early with the hands 5.13 ft from a spine they orbit at 1.15 and the knob starting four feet behind the plate *on the wrong side of it*; 51 ms late, the knob started seven and a half feet toward third base. `test_the_swing_does_not_depend_on_the_pitch` and `test_the_load_pose_is_a_constant_of_the_stance` are the pins.
  - **The engine's aiming pivot is the hands.** `HitOutcomeManager.rhpos` is (490, 453) px — (1.53, 2.93) ft, within a couple of inches of a right-hander's grip at contact. Read that way the contact pose is *solved*, not fitted: the old rectangle was a screen-space object centred on the cursor with its long axis pointing at the pivot, so the 3D bat whose projection is that rectangle is pinned by knob-onto-pivot-pixel and sweet-spot-onto-cursor-pixel, and perspective maps lines to lines. One unknown (the sweet spot's depth) against one equation (the bat's length) — a quadratic, in `_contact_pose`.
  - **Contact depth is an output.** It is that quadratic's root, and it lands where real contact depth lands with nothing tuned: a pitch inside sits close to the hands on screen, so the bat is heavily foreshortened and the ball is met ~2.7 ft out in front (pulled); one away is met ~1.2 ft out (deeper); one low and away is further off than the bat is long, has no root, and the hitter extends after it (`_reach`) and meets it at arm's length, inside-out. **The no-root case comes off the quadratic's vertex**, which is the analytic continuation of the root, so contact depth can dip below the hands and the barrel trails them — see [spray](#spray-direction-sprayspy) for why the old flat answer had to go.
  - **A cursor is a ray, not a point** (`_unproject`). The camera is a perspective projection from 30 ft back, so the same pixel is a different world position at every depth. The barrel meets the ball a couple of feet out front, where a tracked ball sits ~2.3 in higher on screen than it will at the plate — against a bat and ball that are 2.75 in of tolerance between them. Resolving the aim at the plate and the ball at contact spent 84% of the contact window on a bias no player can correct, and capped every swing's quality under 0.5.
  - **The swing is modelled hands-first: a small hand arc, and a bat swung about the hands.** The hands ride a curve authored in the *rotating body frame* — a radius that tightens into the slot and extends through contact, a height working down off the back shoulder — so the load pose is a constant of the stance rather than the contact pose rotated backwards. The bat's attitude about the hands (bearing wrapped by the turn plus a decaying `LAG_DEG`, tilt easing off `LOAD_BAT_ANGLE_DEG`) carries the barrel down off the shoulder and around. The rounded side-view loop and the overhead spiral *emerge*.
  - `ON_PLANE_EASE` is exactly **2**, and the hand-radius profile is stated as a polynomial in the *load* for the same reason: any power ≥ 2 leaves every load term still at contact, which is what makes the attack angle exactly `ATTACK_ANGLE_DEG`. At 3 the tilt was dead by 40° out and the barrel's turnaround drew as a corner.
  - **The swing carries on past contact** (`EXTENSION_DURATION_MS`, `full_track`). Not a second authored arc: the bat keeps its contact angular speed and decelerates to a stop, so how far it wraps is a consequence. It earns its keep twice — `bat_contact` sweeps it, because a swing that arrived early is still moving when the ball gets there, and it is what lets the replay's ghost be a phase of the same swing.
  - **Bat speed is a calibration target, not a shape parameter** (`PEAK_BAT_SPEED_MPH = 72`), because the game has no bat-speed input. The angular profile's exponent is *solved* from it per swing. It now sits at 1.8–2.2 across the plate and never rails, where the old model railed at its 1.05 floor on any mistimed swing — flattening the acceleration profile entirely. `_speed_at` differentiates the drawn chain numerically, so the number includes what the load terms actually do.
  - `SWING_DURATION_MS` is the `+ 150` that was hard-coded in six places across `pitch_simulation` and `hit_outcome_manager`.
  - **`bat_axis` and `contact_zone_ft` are gone, and so is `utils.physics.collision_angled`.** They restated a 120×50 px rectangle the engine no longer swings; keeping a copy of it would be the second model of contact this refactor exists to remove. `PIVOT_PX` survives, because what it always was is where the hands are.
- **[bat_contact.py](strikefactor/gameplay/bat_contact.py)**: pure module that sweeps the bat against the ball and reports the closest approach — **the module that makes contact emergent**, and what the engine now grades a swing with. It also owns `aim_at_pitch`, the seam where the player's cursor becomes an aim. See [Modifying Swing Mechanics](#modifying-swing-mechanics).
  - **A cursor is a ray, and the *ball* has to be carried along it too.** `bat_path._unproject` puts the barrel on the ray at the barrel's depth, ~2.2 ft in front of the plate. Nothing did the same for the ball, and the player is pointing at a ball drawn all the way *to* the plate, inside a strike zone drawn at the plate — so their statement was resolved at one depth and tested at another. The ball is 2–5 in higher and an inch or two across where the bat is, against 2.75 in of total tolerance, and the sign is the same on every pitch. A swing aimed *exactly* on the ball's plate crossing and timed *exactly* met a middle-middle fastball 3.2 in under its centre (quality 0.23, a foul) and missed a 12-6 curveball outright; the best contact available to a correctly-aimed player sat at +8 to +39 ms, which is why recorded swings ran ~45 ms late as a habit — players were swinging late to let the ball fall into a bat placed too low. `aim_at_pitch` translates the cursor onto the barrel's depth, iterated to a fixed point because the barrel's depth is itself a function of the aim.
  - **The depth resolution is a translation, not a correction.** Whatever the player was pointing at relative to the ball survives exactly; the only thing removed is a bias nothing on screen could have told them about. And it keeps `bat_path` free of the pitch — what depends on the pitch is *which point on the ray the cursor meant*, which is a question about the ball. `tests/test_bat_contact.py` pins a perfect swing at quality > 0.99 on every location, with no tolerance, on purpose.
  - **The `assist` argument is the exception**, and one of exactly two in the module. It shrinks the error the player genuinely made, by the fraction difficulty allows, capped radially at `MAX_ASSIST_FT` — game feel rather than geometry, and the reason the two must stay legible as separate things. At `assist = 0` the function is the pure translation above, which is what every test of the translation runs at. Its sibling is the timing assist in `resolve_contact`, which does the same thing on the clock instead of on the plate. See [Modifying Swing Mechanics](#modifying-swing-mechanics).
  - **The rectangle had no such bias**, because it compared a cursor at the plate against a ball frozen at the plate. The bias arrived with the depth axis, which is why it is worth naming: the next thing to grow a depth has the same trap waiting.
- **[swing_record.py](strikefactor/gameplay/swing_record.py)**: the captured swing, built by `PitchSimulation._publish_review()` before Continue (or at cleanup for unanimated results), attached to that pitch's `ReviewRecord` and aliased as `Game.last_swing`. A taken pitch builds no swing and deliberately leaves the previous latest-swing alias in place.
  - **A swing names two instants and they are not the same one**, which is the single most load-bearing fact in this module now: `bat_arrival_s` (the barrel reached its contact pose) versus `contact_time_s` (the sweep found bat and ball at their closest). `contact_depth_ft` / `struck_depth_ft` are the same split stated as a place. The timing readouts belong to the first; anything drawn belongs to the second.
  - **The cursor it stores is the one at commit**, and `swing_aim_ft()` re-runs `bat_contact.aim_at_pitch` on it rather than carrying a second copy — so the replayed bat is the swept bat by construction. It used to prefer the cursor at *bat arrival*, left over from the engine that tested a rectangle 150 ms after the keypress against wherever the mouse had drifted to: with the swing decided at commit, that names a bat nobody swung.
  - **`aim_assist` is carried, not re-read**, and that is what keeps the recompute honest. It is a difficulty setting, so a player who changes difficulty between the swing and the replay would otherwise be shown a bat nobody swung — the same failure, one input over. `PitchSimulation` stamps it at commit.
  - **"Early or late" is measured, not modelled.** `contact_depth_ft` is `trajectory.position_at(bat_arrival_s).y` — the pitch's own trajectory evaluated at the instant the bat arrived. Same physics the pitch was flown with, so there is no second model to disagree with the first.
  - **It is the *ball's* depth; `barrel_depth_ft` is the bat's**, and `depth_gap_ft` is what separates them. Two different objects, allowed to be in different places — that separation *is* the timing error, in feet, and drawing it is the whole point of the side view. Median |timing| of ~21 ms is ~2.7 ft of gap.
  - **The datum is the ball reaching the barrel's own depth, not the plate.** The bat meets the ball a couple of feet out in front (further on a pitch inside, which is more foreshortened and so pulled earlier), so grading against the plate reported a perfectly struck ball as ~17 ms early. `PitchTrajectory.time_at_depth` is the inverse both `_signed_timing_ms` and the replay run on.
  - `bat_swing()` is **iterated to a fixed point**, because `_drawn_aim_ft`'s vertical placement feeds back: nudging the aim's height moves it along the cursor's ray, which moves the barrel's depth about half an inch, which moves where the ball is when it gets there. `barrel_depth_ft` deliberately does not follow the iteration — it reports the depth the engine's own bat reached, from the raw cursor.
  - It holds the `PitchTrajectory` **object**, not samples. The DB's 20-sample table is too coarse to slow down and the live screen trail carries no timestamps at all, so this is the only function-of-time the game has.
  - **Depth is deliberately unclamped.** The engine tests contact against a ball frozen at the plate (`_update_ball_position` clamps `t`, and `_handle_contact_phase` never re-runs it), so clamping here would show every late swing meeting the ball exactly at the plate — the one thing that cannot have happened.
  - **`_drawn_aim_ft` is not `aim_ft`, and it has to be.** `aim_ft` is the cursor resolved at the *plate*; the ball is ~6.4 inches higher at a contact point 5.6 ft out front. Drawing the bat at its plate height put it half a foot *under* a ball the panel simultaneously reported it was 1.4 inches *over*. The bat is placed by the relationship the engine measured, carried out to the depth where the *barrel* is — the plane the ball passes through, and so the only place the two heights can honestly be compared. The offset must be applied *at* that depth and turned back into a plate-frame aim (`bat_path.to_plate_frame`), never applied to the plate-frame aim directly: a cursor is a ray, and 7% of a plate-frame offset is not the offset that was measured.
- **[swing_replay_overlay.py](strikefactor/ui/swing_replay_overlay.py)**: phased overlay following `ABSChallengeOverlay`'s shape and `main.py`'s nested-loop pause (`request_swing_replay` → `_run_swing_replay_loop`), but drawn in `gameday_theme` — the ABS card's `SysFont("arial")` and pink palette are the UI's exception, not its pattern.
  - **SIDE** (down the x axis) puts feet-from-the-plate on the horizontal, so the timing error *is* the visible gap between barrel and ball; **OVERHEAD** (down z) shows the barrel sweeping across the plate. Both project from the same world-feet models. TAB toggles; SPACE replays; ←/→ scrub.
  - **Both views are seen from a real place, and both were mirror images of it.** The world's `+x` is the third-base side (`pivot_ft("R")` is `+1.53`, and a right-hander stands at third), so `_project` orients the horizontal axis in each rather than taking `y` and `x` as they come: a camera on the third-base line sees the pitcher on its *left*, and a bird's eye sees third base on the left. Drawn straight through, SIDE was a first-base camera captioned `PITCHER ->` and OVERHEAD put `+x` on the right under a label reading `<- 3B` — a view from underneath the infield, with the batter standing in the wrong box. Nothing about a swing is symmetric, so a mirrored replay reverses which way the hitter is turning. `tests/test_swing_replay.py` pins both cameras and the batter's side.
  - **The SIDE camera changes foul lines with the batter** (`_side_camera_x`): the first-base line for a right-hander, the third-base line for a left-hander — the hitter's **open** side in both cases, and `_axis_label` names which one it is standing on since a mirrored swing is still a swing. Fixed on the third-base line it filmed one hand from the front and the other from *behind*, and those are not two renderings of one swing: from back there the hands travel away from the camera, the barrel is hidden behind the body for most of the arc, and the ball arrives over the hitter's back, so every quantity the view exists to show — how far out front contact was, whether the barrel got on plane, the daylight between bat and ball — is a foreshortened guess. It is the same reason a broadcast's swing camera is on the open side. **OVERHEAD does not flip**: a bird's eye has no open side, and 3B-left/1B-right is shared with the hit animation, so the spray ray reads the same way in both.
  - **The ghost is the same swing at another phase, not a second swing.** With the path independent of the pitch, "where the bat should have been" is `bat_state_at_ball_arrival()` — this swing sampled where the ball crossed the barrel's plane. A late swing was still on its way there; an early one is already into the follow-through. `perfect_swing()`, which built a whole second bat, is gone.
  - **The replay ends at the instant the bat and the ball met, with no tail.** Not at bat arrival — and conflating the two is what made a HOME RUN draw with the bat eight feet from the ball. A swing names *two* instants: `bat_arrival_s`, when the barrel reached its contact pose (a fact about the swing alone, and the datum `signed_timing_ms` is measured against), and `SwingRecord.contact_time_s`, where `bat_contact`'s sweep found the two at their closest. The sweep is free to catch the ball anywhere in the arc, and on a mistimed swing it does — up to ~25 ms of pitch time away, which at 101 mph is six feet of ball. The clip used to run past a late contact and stop short of an early one while the crosshair marked the real one, so the frozen frame held a bat, a ball and a mark in three different places. Measured on a 48 ms late swing at ROOKIE: 6.0 ft of daylight at bat arrival against 0.84 ft at contact. **Anything meant to be looked at runs on `contact_time_s`; the timing readouts stay on `bat_arrival_s`.** `struck_depth_ft` is the ball's depth in the frame that gets held, which is what `BALL AT` reports. No tail, for the old reason: at 93 mph even 60 ms drags the ball eight feet past the contact marker.
  - **A swing that missed names neither instant, so its clip runs to the plate** (`SwingRecord.clip_end_s`). `contact_time_s` answers a miss with `bat_arrival_s` — a fact about the *bat*, not the ball — and on an early miss the ball is still two or three feet out in front there, so the clip stopped with the pitch hanging in mid-air, unfinished, which is the one frame nothing can be read off. The plate is a **floor and never a ceiling**: a swing late enough that the barrel arrived after the ball was by keeps its own arrival, with the ball genuinely past the plate, which is what a late miss looks like. `BALL AT` still reports the ball at bat arrival, and `_draw_missed_ball` outlines it there, because the clip now runs on past the instant the crosshair marks and a number with nothing on screen behind it is the fault this whole view exists to avoid.
  - **One slow-motion rate, not one duration** (`_REPLAY_MS_PER_PITCH_S`, 12x). The clip's wall-clock length is the length of the slice of pitch it shows. Divided out of a fixed 2180 ms, as it was, the *rate* became a function of the swing — a late contact is more pitch than an early one and played faster for it, and a miss followed to the plate would have been faster again, i.e. the clips with the most to show were the ones hurried. The old duration is reproduced exactly for an ordinary swing (0.18 s of pitch: `_PRE_SWING_S` plus the swing), and `_PHASE_REPLAY_END` / `_PHASE_FREEZE_END` are gone — `_compute_phases` sets both at `trigger`.
  - **The bat and the ball touch, and it took a model change to make that true.** `bat_contact` used to grant contact anisotropically — the bat was an ellipsoid stretched along the ball's flight line by `cushion_s` seconds of ball travel, 39 ms at ROOKIE and so 5.8 ft against a 101 mph fastball — so the model put the bat within an inch or two of the ball's *line* and a foot or more from the ball itself, and **no instant existed where they touched**. This view drew that honestly, which is how it was found: a FOUL banner over `REACH 2.6 FT` of daylight. Measured over recorded play, 63% of contacts had visible daylight, 31% over a foot and 16% over two feet. The forgiveness is now spent by sliding the swing in time, so the frozen frame shows a real intersection; what survives is the *spatial assist* (`bat_contact.spatial_assist_ft`, `BASE_SPATIAL_ASSIST_FT`, `POWER_SPATIAL_ASSIST_FT`), which **moves** the bat rather than widening it and is charged back through `Contact.spatial_score`. Shrinking that is a difficulty decision (`contact_zone_size`), not a drawing one. `tests/test_swing_replay.py::test_the_bat_and_the_ball_actually_touch` asserts the daylight against the contact's own `surface_gap_ft` rather than a constant, so a regression that reopens it from anywhere else fails there.
  - **The timing bands are measured, not assumed.** `SwingRecord.timing_windows_ms` re-sweeps this swing against its own pitch and bisects the two boundaries: the outer band is where it would have touched the ball at all, the inner one where it would have been fair. They were `perfect_ms` / `foul_ms` — 30 and 60 ms scaled by difficulty, inherited from the timing *gate* the geometry replaced — and by the end they were fiction: at ROOKIE the panel drew `ON TIME` across ±45 ms while quality over that range ran from 1.00 to 0.12, which is how the screenshot came to read ON TIME over a foul. `timing_label` now asks the fair window, so that swing reads `LATE 40 MS`.
    - **The measured windows are strongly asymmetric**, and that is the most useful thing on the bar: about −42…+83 ms at AMATEUR, because a late bat still catches the ball on the handle while an early one runs out of barrel. A symmetric pair of constants could not show it and the player has no other way to learn it. Fair windows run ±41 ms at ROOKIE down to ±17 at HALL OF FAME.
    - **They are a property of *this swing*, not of the difficulty**, so a pitch the player was never on top of draws a narrower band — 2 in high at AMATEUR is a fair window of ±6 ms, 4 in high has none at any timing, and the inner band is simply not drawn. Saying "no timing would have squared this up" is more use than drawing a band the swing could never have reached.
    - Bisected rather than swept: ~37 `resolve_contact` calls at 1.6 ms, **warmed in `trigger`** and cached. Left lazy it fires on the first frame `_draw_stats` runs, 420 ms in, which is a visible stutter partway through the replay. Both predicates are contiguous in the offset, which is what makes bisection sound, and a test pins that.
    - The assist budget is drawn as **ticks, not a third band**, because it very nearly coincides with the fair window (±39 against −41…+42 at ROOKIE) and a band would imply a distinction that is not there.
    - Nothing is left of the old constants. The foul's direction was the last thing reading them — a signed timing severity against a window of hand-tuned milliseconds, which the animation turned into "pull side" or "opposite field" — and it now comes off `Contact.spray_deg` like every other bearing.
  - **The bat drawn is the bat that was swept, which means the *slid* swing.** `SwingRecord.swing_launch_s` carries `Contact.shift_s`; drawing the committed swing instead would put the picture back at odds with the verdict, the same failure as preferring the cursor at bat arrival. The timing readouts stay on what the player actually did (`signed_timing_ms`), and `_draw_assist` marks the difference on the timing bar as `ASSIST n MS` — the borrowed time is charged for in quality, so leaving it off the panel would report a number the player has no way to account for.
  - **The OVERHEAD view draws where the ball went** (`_draw_spray`), which is what it was always for — the module docstring already called it the view "where pull-versus-oppo contact reads", and until the ball had a bearing there was nothing there to read. The ray is `SwingRecord.departure_or_spray_deg` — where the ball actually **left**, which on a foul is not `Contact.spray_deg` (see [spray](#spray-direction-sprayspy)) — and it is drawn as `SwingRecord.flight_path`, the animation's *own* `BattedBallPath` object rather than a line rebuilt from a bearing, so a second flight model cannot grow here. The bend is not uniformly small: 2-4 in over the drawn 40 ft on a 380 ft fly, but **2.4 ft on a 110 ft foul**, since the drift goes as the square of the fraction of carry covered. This docstring claimed the picture and the outcome could not disagree for a long time before it was true; it is projected through `_project` rather than stepped in pixels, because that function orients its horizontal axis (and now swings it with the batter) and anything building its own screen vector gets the mirror wrong. Frozen-frame only, like the contact marker and for the same reason: until the two have met there is no direction yet.
  - The depth window is framed on **what the frozen frame draws** — the struck ball, the barrel's arrival, and the bat at contact. Framed on the ball at bat *arrival* it reserved several feet the clip no longer reaches, so half the view was empty air behind the catcher. It is computed once at `trigger` and cached: `_project` asks for it on every point it converts, and `barrel_depth_ft` rebuilds four swings each time it is read.
  - Depth is framed **per swing** (`_depth_range`), because contact runs from ~11 ft out front to ~11 ft deep and any fixed window wide enough for both squeezes the ordinary swing into a sixth of the view.
  - **The bat is drawn as a swept sphere of varying radius** (`bat_path.BAT_PROFILE_IN`, `_bat_ellipses`) — knob flare, thin handle, concave taper, near-parallel barrel, rounded tip — because drawn as a line a bat is a line. The profile is stated in real inches (2.61 in at the barrel, the MLB maximum, against under an inch at the handle) and the stations are placed to keep the taper **concave**; spread evenly, the same radii straighten into a cone. It is sampled from the same `bat_solid_point` the collision sweep uses, so the bat the player is graded by and the bat they are shown are one object and a real intersection cannot open into daylight on screen; a bat pointed at the camera draws as its projected spheres stacked, with no end-on special case.
  - **A foot is a foot in every direction, in both views** (`_fit_isotropic`). Each view has one scale, set by whichever axis has the least room per foot; the other axis is widened about its centre until it fills its side of the rect, so the binding axis comes back exactly as required and nothing the view had to hold is ever shrunk. It used to be two scales per view — the range framed along each axis simply stretched across the rect — and OVERHEAD fitted 11 ft of width into 1072 px against 14 ft of depth in 340, a 4:1 squash that drew the swing's round arc as a flattened ellipse and a bat lying across the plate at four times the length of one pointing at the mound; SIDE carried the same fault at 1.6:1. Two consequences worth knowing. The depth window is OVERHEAD's *short* axis and so sets that picture's scale directly, which is why `_compute_depth_range` frames the swing's own path (plus the ghost) at a 1.5 ft margin over a (-4, 5) floor rather than its end points at 4 ft over (-5, 9) — the load pose puts the barrel nearly 4 ft behind the plate, which the old floor happened to cover. And the OVERHEAD rect now shows some 30 ft of field from above, so the batter's boxes and the foul lines are drawn in it (`_draw_field_lines`), the lines at `spray.FOUL_LINE_DEG` from the apex through `spray.world_direction` — the number and the frame conversion `is_foul` and the ray use, so the ray's verdict sits beside the thing it is a verdict about. The spray label is anchored where the ray *leaves* the frame (`_exit_point`); at the ray's end it was outside the clip and had never once appeared on screen. `tests/test_swing_replay.py` pins the equal scales off the projection itself, the bat's equal length along both axes, the frame holding every drawn bat sample, and the label landing inside the view.
  - `tests/test_swing_replay.py` guards the depth measurement, the picture-agrees-with-the-numbers property, the bat's real profile recovered back out of the drawn pixels, and panel containment.

### ABS Challenge System
MLB-style automated ball-strike challenge after umpire calls:
- **ChallengeManager** ([challenge_manager.py](strikefactor/gameplay/challenge_manager.py)): Tracks remaining challenges per side (default `CHALLENGES_PER_SIDE` from `config.py`). Successful challenges are retained, failed ones decrement. `set_unlimited(True)` is used in Sandbox to make challenges free.
- **ABSChallengeOverlay** ([abs_challenge_overlay.py](strikefactor/ui/abs_challenge_overlay.py)): Phased replay overlay — intro card (`_PHASE_INTRO_END`) → 2D trajectory replay (`_PHASE_REPLAY_END`) → camera zoom (`_PHASE_ZOOM_END`) → CALL CONFIRMED/OVERTURNED banner.
- Enabled per-game by the `abs_enabled` setting; reset/configured around state transitions in `main.py` (`challenge_manager.reset_all()`, `set_unlimited()`).
- Triggered through the challenge keybind; routes through the `# ABS challenge system` block in [main.py](strikefactor/main.py) (`request_abs_challenge` → `_run_abs_overlay_loop` → `_reverse_last_call`, ~lines 1359–1735).

### HUD System
Three pluggable HUD renderers, selectable via the `hud_mode` setting and cycled at runtime by `Game.toggle_hud_mode()`:
- **Scorebug** ([scorebug.py](strikefactor/ui/scorebug.py)): Full-width TV-style bottom bar (`hud_mode = "legacy"`)
- **BroadcastHUD** ([broadcast_hud.py](strikefactor/ui/broadcast_hud.py)): Four-corner layout — count top-left, inning/score top-right, pitcher/last-pitch bottom-left, bases bottom-right (`hud_mode = "broadcast"`)
- **MinimalHUD** ([minimal_hud.py](strikefactor/ui/minimal_hud.py)): Compact bottom-right corner widget (`hud_mode = "minimal"`)
- All share a strict black/white/gray palette. `Game._draw_active_hud()` dispatches to the active one; visibility toggles in sync with the global UI toggle.
- Keybinding: `TOGGLE_HUD_MODE` cycles modes during gameplay.

### GameDay Mode
Full 9-inning game simulation in [gameday_manager.py](strikefactor/gameplay/gameday_manager.py):
- **GameDayManager**: Owns inning/half state, opponent at-bat simulation, bullpen management, momentum/clutch bonuses, and event log.
- **PitcherStats**: Per-pitcher pitch count, outs recorded, fatigue label, and mistake/velocity/movement modifiers — used by both pitching sides.
- **Opponent at-bats**: `simulate_opponent_at_bat()` rolls outcomes using `_get_adjusted_probabilities()`, which factors in pitcher fatigue, momentum, and clutch.
- **Bullpen logic**: `should_consider_relief_pitcher()` / `substitute_relief_pitcher()` for the opponent; `should_consider_player_relief_pitcher()` / `_pick_player_reliever()` / `substitute_player_relief_pitcher()` for the player team. Roles, pitch caps, IP caps, and outcome multipliers are loaded from [data/pitcher_attributes.json](strikefactor/data/pitcher_attributes.json) via `get_pitcher_attrs(name)`.
- **Walk-off detection**: `check_walkoff()` ends the game immediately when the home team takes the lead in the bottom of the 9th or later.
- **Box score**: `get_box_score_lines()` feeds `gameday_theme.draw_linescore_from_arrays()`, the immediate-mode linescore drawn by `GameDayTransitionState._draw_linescore` on the transition and FINAL screens and by `_render_detail` on the history screen. It replaced a `BoxScorePanel` pygame_gui widget, which was left constructed and hidden but never shown; the widget and its `@box_score_*` theme entries are gone.
- **Play-by-play**: [PlayByPlayPanel](strikefactor/ui/play_by_play_panel.py) renders a stored/live `play_log` as a scrollable log grouped by half-inning, with a running score, ALL/SCORING/YOU/OPP filters, and a sticky inning header. Used by the GameDay history detail screen and the in-game GAME LOG overlay (`GameDayTransitionState._show_game_log`).
- **Pitching box score**: [PitchingBoxPanel](strikefactor/ui/pitching_box_panel.py) is the second tab of the GAME LOG overlay (`_LOG_TABS`, switched with ←/→ or by clicking the chips), showing **every arm both staffs used** — IP / H / R / BB / K / HR / PC / ERA, a per-side totals row, and the on-the-mound arm marked with its fatigue while the game is live (`set_sides(..., live=)`).
  - It replaced a fixed 76px strip under the play-by-play that drew `stats[-2:]` per side, so in any game that went to the bullpen the earlier arms had **no screen anywhere** that could show them. Height is a scrolling problem here, never a truncation problem — `tests/test_pitching_box_panel.py` asserts the row count against the staffs, not against the rect.
  - The panel takes handedness/role tags as **data** (`PitchingSide.tags`, built by `GameDayTransitionState._pitching_sides`) rather than looking them up, so it stays out of the gameplay layer. Opponent arms are tagged by handedness because the player bats against them; their own staff by bullpen role because they only ever manage it.
  - `format_ip` / `format_era` live in the panel because the totals row formats a *summed* out count, which belongs to no `PitcherStats` instance. A test pins `format_ip` to `PitcherStats.get_ip_display`. ERA of an arm with no outs is `'-'` (or `'INF'` once a run is in), never a fake `0.00`.
  - Column x-positions are derived from the caller's rect and anchored to its right edge, so a too-narrow rect must clamp rather than push the leftmost stat column out sideways — the containment test compares the bounding box of every lit pixel against the rect, because probing corners misses a spill that happens at one row height.
  - Chip rows (these tabs and the play-by-play's filters) share `gameday_theme.draw_chips`. The tabs are drawn just *outside* `_LOG_RECT`, so `handle_event` must hit-test them **before** the click-outside-to-close branch.
- **History**: Saved per-game to `data/gameday_history.json` via `save_game_result()`; class methods `get_career_record()` and `load_history_record_vs(pitcher)` power the pitcher-vs-record line on the [PitcherCarousel](strikefactor/ui/pitcher_carousel.py).
- **Resume**: `resume_gameday_session()` reattaches the pitch DB to the session's `db_game_id` via `PitchDatabaseService.resume_game()`, so a resumed game keeps **one** `game_id` end to end. Opening a second row instead splits one logical game in two, and the first half then has no final score — its runs become unattributable in the pitching line.
- **Full reset**: [reset_tracking.py](strikefactor/data/reset_tracking.py) archives and clears *all* recorded play, across every mode and every store — the pitch log, at-bats, games, batter profiles, the batting heatmap, the Sandbox lap log and the GameDay career record. The wider sibling of `gameday_maintenance`, for when a change to the contact geometry makes previously recorded play describe a different game (its first use was the `collision_angled` sign fix). Snapshots go to `data/archives/<timestamp>/` as a **whole copy** of the database — at this scope there is nothing to slice — plus every JSON store and a manifest of what was there. `--dry-run` reports without touching anything, `--restore` puts a snapshot back.
  - **Archive everything or archive nothing**, for the reason `gameday_maintenance` gives: clearing the JSON while leaving the pitch log makes history say one thing and the analysis another.
  - Reset deletes **rows, never tables**, and preserves `user_version`, so the next launch opens a current database rather than migrating one from scratch. JSON stores are emptied in place so their `version` survives.
  - Snapshot directories are second-resolution timestamps and are **uniquified**: `restore` takes a safety snapshot of live state first, so without that a restore within a second of archiving overwrote the snapshot it was restoring *from* and read the emptied copy back. `tests/test_reset_tracking.py` pins it — losing data on the recovery path is the one failure this module cannot have.
- **Maintenance**: [gameday_maintenance.py](strikefactor/data/gameday_maintenance.py) archives, resets, and restores GameDay state. GameDay lives in *three* stores — `gameday_history.json`, `gameday_sessions.json`, and the `game_mode = 'gameday'` rows of `strikefactor.db` — and every operation must cover all three. Archiving the JSON alone lets history say one game while the analysis still aggregates every pitch ever thrown. `--keep-latest` / `--keep-game` retain specific games; `merge_game_fragments()` repairs games split by the pre-fix resume path. Snapshots land in `data/gameday_archives/<timestamp>/` with the DB slice as a standalone queryable SQLite file. Run it from the repository root as a module: `python -m strikefactor.data.gameday_maintenance --list`.

### Sandbox Mode
Free-practice mode where the player picks every pitch:
- **SandboxGameplayState** ([game_states.py](strikefactor/gameplay/game_states.py)): Wires the active pitcher's arsenal to on-screen pitch buttons (`UIManager.update_sandbox_pitch_buttons`) so the player chooses what gets thrown next.
- Challenges are unlimited in Sandbox (`challenge_manager.set_unlimited(True)`).
- **Lap system**: A "lap" is a self-contained practice run with a count of at-bats and pitch-by-pitch results. Lap history is persisted to `data/lap_history.json` and viewed in-game through [LapLogPanel](strikefactor/ui/lap_log_panel.py).
- **RandomScenarioGenerator** ([random_scenario.py](strikefactor/gameplay/random_scenario.py)): Produces themed starting states (clutch, two-strike, full count, bases loaded, etc.) for variety inside Sandbox.

### Settings & Configuration
- **SettingsManager** ([settings_manager.py](strikefactor/settings_manager.py)): Persists user settings to `settings.json`
  - `difficulty`: ROOKIE to HALL_OF_FAME
  - `umpire_sound`, `master_volume`
  - `display_mode`, `display_fps`, `engine_fps`
  - `batter_handedness`, `show_strikezone`
  - `abs_enabled`: Toggles the ABS challenge feature
  - `hud_mode`: `"legacy"` / `"broadcast"` / `"minimal"` — see [HUD System](#hud-system)
  - `defense_strength`: `"sandlot"` / `"minors"` / `"league"` / `"gold_glove"` — how good the nine gloves behind the pitcher are, resolved by [defense.py](strikefactor/gameplay/defense.py). `SettingsManager.DEFENSE_LEVELS` is a plain string list rather than an import of `DefenseLevel`, because gameplay already imports settings and the reverse edge would close a cycle; `tests/test_defense.py` pins the two lists together. Its settings row cost the page its last spare inch — `_CONTENT_TOP` went 132→120 and `_SECTION_GAP` 18→16 to fit eight rows above `_FOOTER_DIVIDER_Y`, and **there is now room for no further row at this stride**. The next setting needs a scroll, a second column or a sub-screen; `tests/test_settings_layout.py::test_the_settings_page_has_headroom_left` fails first.
- **KeyBindingManager** ([key_binding_manager.py](strikefactor/key_binding_manager.py)): Manages customizable key bindings saved to `key_bindings.json`
  - Default actions: toggle UI (H), strikezone (Z), sound (M), quick pitch (SPACE), view pitches (V), toggle HUD mode (U), swing replay (R), main menu (ESC)
- **config.py**: Global constants (screen size, FPS, strike zone dimensions, physics constants, ABS colors/zone, `CHALLENGES_PER_SIDE`)

### Settings Screens
[settings_panel.py](strikefactor/ui/settings_panel.py) draws the settings and key-binding screens as **rows**, in the same chrome as [GameDay](#gameday-mode): `gameday_theme`'s header rail, 40px margins, micro-subhead over headline, black/white/gray, and `draw_chips` for difficulty. They are sub-modes of `MenuState` (`menu_state == 'settings' / 'key_bindings'`), not states of their own.
- **Nothing on these screens carries its own x.** They used to be 21 absolutely-positioned `UIButton`s declared as literal rects in `UIManager._create_game_buttons`, and because no rect was derived from anything, each row ended up centred on a *different* axis: against a screen centre of 640, the difficulty rows sat at 620, the toggle row at 800 with its right edge 10px off-screen, the FPS row at 740, and only the bottom pair at 640. That is what read as "off centre" — the two correct rows anchored the eye and the rest appeared to drift. Rows now span one content column (`content_bounds()`) and the surviving footer nav comes from `UIManager._footer_row_right`, which is a function of `SCREEN_WIDTH`. `tests/test_settings_layout.py` guards it and asserts the old grid is gone.
- **Layout is a cursor walked down the page**, not a table of positions. Adding a setting means adding a row to `SettingsPanel.SECTIONS`; nothing below it needs moving.
- **The panels return `(action_id, payload)`; `MenuState._SETTINGS_ACTIONS` maps that to a `Game` method.** So the panels never import `Game` and are testable with a bare `SettingsManager`, and `Game` keeps one method per *setting* rather than one per widget — the old `update_settings_button_states` had to re-push the label of every button after any change, from eleven call sites.
- **`_nav_keys` is static, not accumulated during render.** A row must know whether it is the selected one *while it is being drawn*, and a list built as the rows are drawn is always short by exactly the row in hand — the cursor would never appear on the last row.
- **Neither screen uses the shared `banner`.** The difficulty description used to go through `show_banner`, i.e. the global `label` theme rule at **80px bold italic**, so a settings *value* was the loudest thing on a page whose own title was smaller. Rebind collisions had the same problem. Both now draw in place (`Game.key_rebind_error`, `SettingsPanel._caption`), and the caption drops the level name the chip already shows.
- The active difficulty chip **is** the selected-state indicator. The five old buttons were styled identically, so nothing on screen said which one was live; `update_settings_button_states` carried a comment admitting it. `@settings_button` in `theme.json` styled only that grid and is gone with it.
- `KeyBindingsPanel.ACTIONS` lists **every** `KeyAction`. `TOGGLE_HUD_MODE` was bound and dispatched but had no button, so it was unrebindable and undiscoverable; a drawn list has no per-row cost, and a test pins the list to the enum.

### Data & Analytics
- **ScoreKeeper** ([helpers.py](strikefactor/helpers.py)): Tracks game state (outs, runners, score)
- **PitchDataManager** ([helpers.py](strikefactor/helpers.py)): In-memory pitch record used for the per-game PitchViz / VisualizationState
- **batting_stats.json** ([strikefactor/data/](strikefactor/data/)): Historical batting performance for heatmap visualization (legacy aggregate JSON, `batting_stats_legacy_v1.json` is the prior schema)
- **PitchDB / PitchDatabaseService** ([pitch_database.py](strikefactor/data/pitch_database.py)): SQLite-backed persistent pitch log at `strikefactor/data/strikefactor.db`.
  - Tables: `pitches` (full 9-parameter kinematics, derived speed/movement, AB context, outcomes, ABS truth-vs-call), `pitch_trajectories` (20-sample 3D trajectory per pitch), `at_bats`, `games` (one row per Arcade encounter / GameDay / Sandbox session), `batter_profiles` (persisted [BatterProfile](#ai-system) aggregates keyed by mode+difficulty).
  - `exit_velocity_mph` (schema v6) is set on every bat-on-ball event **including fouls**, while `contact_quality` stays NULL on fouls — fouls never run the hit pipeline that populates it. Don't "fix" that asymmetry by widening `contact_quality`: it would silently change what every existing aggregate over that column means. EV is a model output derived from quality (see [Contact Audio](#contact-audio)), not an independent measurement.
  - `swing_timing_signed_ms` (schema v8) is the signed form of `swing_timing_diff_ms`, which has always been stored `abs()`'d — so before v8 the DB could say how far off a swing was but never whether it was **early or late**, making the most useful coaching fact the game holds structurally unanswerable. The value was already computed with its sign; only the foul path saw it, into a field that was never persisted. The unsigned column is left exactly as it is: `abs()` of the new one recovers it, and widening it in place would silently change every existing aggregate over it.
  - `spray_angle_deg` (schema v9) is which way the ball went: degrees from centre field, **pull-positive for either batter** so an aggregate over both hands means something without a join. It is the first direction the DB has ever held, and before it spray was not merely unrecorded but *unmodelled* — a ball in play drew its bearing from `random.uniform`, so there was nothing to record. NULL when the bat never met the ball, and per the v7 precedent that must not be coalesced to `0.0`: zero is dead centre field, a real and common value, so filling it in puts a spike in the middle of the one distribution the column exists to show the shape of. `analysis`'s `spray_profile` / `spray_vs_timing` and the `spray` figure read it.
  - `defense_strength` (schema v10) is which defense the ball was hit into — a sibling of `difficulty` and a **separate axis from it on purpose**: difficulty is the bat, this is the glove. It exists because the setting moves BABIP, ground-ball hit rate, 2B/1B and (once errors land) the reached-on-error rate, so a rate measured across a mix of levels is a mix of games. **NULL for rows written before the setting existed, and it must not be back-filled to `"league"`** — those rows are not league-defense rows, they are rows from a build with no misplay model at all, so their error rate is structurally zero. Same shape as the pre-v2 `game_id IS NULL` correlation that makes the pitching line compute over one slice: any error aggregate takes `defense_strength IS NOT NULL` and surfaces what it dropped. `analysis` opens the DB **read-only**, so an archive snapshot is never migrated and genuinely lacks the column — `analysis/data.py::_derive` materialises it as all-NA so `--defense` cannot `KeyError` on old data.
  - `batted_ball_type` / `fielder_role` / `play_margin_s` (schema v7) record what happened to a batted ball. **`batted_ball_type` is the useful one**: it is classified at *contact* by `HitOutcomeManager`, upstream of any fielding decision, so it is an independent axis to slice on — before v7 the DB could not tell a ground ball from a fly ball, and any check of the fielding model had to infer type from `outcome`, which is what the model produced. `play_margin_s` is the decisive race's margin, signed so positive favours the defense. Both `fielder_role` and `play_margin_s` are **NULL when no play happened** — a ball nobody fielded has no fielder, and a ball nobody raced for has no margin. Don't coalesce those to `0.0`: it would put a spike at dead-even in a distribution whose entire purpose is its shape. `tests/test_batted_ball_schema.py` guards it.
  - `PitchDatabaseService` is a singleton (`PitchDatabaseService.get_instance()`) with `start_game()` / `end_game()` / `record_pitch()` / `load_batter_profile()` / `save_batter_profile()`. Migrations are versioned by `SCHEMA_VERSION` and run in `PitchDB._migrate()`; an auto-backup runs into `data/backups/`.
- **Analytics scripts** (repo root, run outside the game):
  - [pitch_analysis.py](pitch_analysis.py): Thin CLI over the [analysis/](analysis/) package. Renders 15 figures plus `report.html`, or prints the same numbers as terminal tables with `--terminal`. Output goes to `analysis_output/<filter-slug>/`.
  - [batting_analysis.py](batting_analysis.py): Player batting-tendency figures, writing `batting_report.html` into the same per-filter folder. Shares filtering/palettes/outcome groups with the analysis package.
  - Shared flags: `--mode`, `--difficulty`, `--handedness`, `--pitcher`. `pitch_analysis.py` adds `--terminal`, `--figures`, `--sections`, `--only`, `--list`, `--width`, `--out`, `--db`, `--no-report`.

### Analysis Package
[analysis/](analysis/) is layered so metrics are computed once and rendered many ways — see [docs/pitch-analysis-refactor.md](docs/pitch-analysis-refactor.md) for the design rationale.

- **[data.py](analysis/data.py)**: SQLite → pandas plus derived columns (`is_whiff`, `in_zone`, `is_chase`, `count_state`, `platoon`, `plate_x_batter`, backfilled `pitcher_hand`). `Context` bundles filter + frame + output dir, replacing the old module-level globals.
- **[filters.py](analysis/filters.py)**: `Filter` dataclass and the shared CLI options. One output subfolder per filter slug.
- **[metrics.py](analysis/metrics.py)**: Pure DataFrame → DataFrame statistics. No I/O, no drawing — this is what keeps the PNG and terminal outputs identical.
- **[theme.py](analysis/theme.py)**: Palettes, pitch/pitcher labels, outcome groups, MLB benchmarks, strike-zone constants.
- **[render_mpl.py](analysis/render_mpl.py)** / **[render_term.py](analysis/render_term.py)**: The two renderers. `render_term` uses `rich` when present and falls back to plain ASCII.
- **[figures/](analysis/figures/)**: One module per section, registered in `figures.FIGURES`. Adding a figure means adding a row to that list.
- The **spray** figure (`results.spray`, `metrics.spray_profile` / `spray_vs_timing`) is what makes the [spray](#spray-direction-sprayspy) calibration checkable instead of eyeballed: the fair-ball distribution against MLB's 40/35/25, how much contact direction fouls, and mean spray against signed swing timing. If that last curve comes back flat, the bearing has stopped reaching the ball somewhere between `bat_contact` and `hit_animation`.

Key metric definitions worth knowing:
- **Whiff** = `swing_type > 0 AND outcome IN ('strike','strikeout')`. Fouls carry `outcome = 'foul'` and contact carries an in-play outcome, so this is exact. `on_time` is 0 whiff / 1 foul / 2 fair, and since the `bat_contact` rewrite it is the *geometry's* verdict rather than a timing grade — timing reaches it the way it reaches a real swing, by putting the ball off the end of the bat or on the handle. Rows from before that rewrite mean the older thing; they were archived at the cutover.
- **`POP UP` is a terminal outcome** and belongs in every PA/BF/out denominator (`theme.TERMINAL_OUTCOMES`). It was recorded as `POP_UP` before schema v5; `PitchDB._migrate` rewrites the old rows, so never match on both spellings — the DB holds only the spaced form.
- **Run value** comes from a count-value model solved by backward induction over the active slice, so run values sum to ~0 across it and are only meaningful *between* sub-groups. Any per-count aggregate is structurally zero.
- **The pitching line computes every column over one slice**: GameDay rows with a non-null `game_id`, which is exactly the set whose runs can be attributed. `game_id IS NULL` and `runs_scored_on_pitch IS NULL` are perfectly correlated (both arrived in the v2 migration), so counting H/HR/BB/K over all rows while counting R over only the covered ones makes the pre-v2 era contribute innings and homers but structurally zero runs — which is how a line ends up reporting more HR than R. Excluded rows are surfaced via `df.attrs["dropped_pitches"]`, not silently dropped. Runs charged to these pitchers are `final_player_score`: the pitches table only holds pitches thrown *to* the player.

## Key Dependencies
- **pygame-ce**: Game engine and rendering
- **pygame_gui**: UI components (buttons, sliders, windows)
- **pandas**: Data analysis and statistics
- **numpy**: Numerical operations for physics
- **scikit-learn**: ML models for AI umpire
- **matplotlib/seaborn**: Visualization of batting stats

## Important Patterns

### Adding a New Pitcher
1. Create a new file in [strikefactor/pitchers/](strikefactor/pitchers/) inheriting from `Pitcher`
2. Define pitch methods with physics parameters (ax, ay, vx, vy, travel_time, pitch_type)
3. Register pitches in `__init__` using `add_pitch_type()`
4. Implement `draw_pitcher()` for animation timing
5. Load sprites via `load_img(loadfunc, sprite_path, frame_count)`
6. Import and add to PitcherManager in [main.py](strikefactor/main.py)
7. Train an AI model and save as `{pitcher_name}_ai.pkl` in [strikefactor/ai/](strikefactor/ai/)

### Adding a New Game State
1. Create a class in [game_states.py](strikefactor/gameplay/game_states.py) extending `GameState`
2. Implement all abstract methods: `enter()`, `exit()`, `update()`, `handle_event()`, `render()`
3. Register the state in `GameStateManager._initialize_states()` in [game_state_manager.py](strikefactor/gameplay/game_state_manager.py)
4. Add transition logic in `GameStateManager.handle_menu_state_change()` if needed
5. Add a button visibility state in `UIManager.set_button_visibility()` in [ui_manager.py](strikefactor/ui/ui_manager.py)
6. Register button callbacks in `Game._setup_ui_callbacks()` in [main.py](strikefactor/main.py)

### Adding New UI Buttons
1. Add button definition in `UIManager._create_game_buttons()` in [ui_manager.py](strikefactor/ui/ui_manager.py)
2. Add visibility logic in `UIManager.set_button_visibility()` for relevant states
3. Register callback in `Game._setup_ui_callbacks()` in [main.py](strikefactor/main.py)
4. Buttons automatically inherit styling from [theme.json](strikefactor/assets/theme.json)

Prefer `@broadcast_button` for anything on a menu screen — it is the black/1px-border style the GameDay and [settings](#settings-screens) screens share. And note that a **new setting is not a new button**: add a row to `SettingsPanel.SECTIONS` instead, or the screen grows a second source of layout truth.

### Modifying Swing Mechanics
The bat is one object, swung by one model, in three dimensions. `bat_path`
says where it is at every instant of a swing; `bat_contact` sweeps that against
the ball and reports what happened. Everything downstream reads the result.

- **Contact used to be two unrelated gates, and now it is one question.** The
  first compared `swing_start + 150` against the ball reaching the *plate* and
  graded it on a difficulty window; the second, only if that passed, tested a
  120×50 px rectangle at the cursor against the ball's *screen* position for
  one frame. Neither knew about the other and neither had a depth axis, so
  contact depth could not be an output of the pair — which is why the replay
  ended up modelling a bat backwards from the pitch to get one. `resolve_contact`
  asks whether two solids intersect, and when / where on the bat / how square
  all fall out together.
- **The whole swing is decided at commit** (`_handle_swing_input`). The bat is
  built from the cursor as it was when the key went down, and swept against the
  pitch's own trajectory then and there. Previously the geometry test ran 150 ms
  later against the cursor *as it was then*, which let a player re-aim during
  the swing; a real swing path cannot change once it has started.
- **The cursor is resolved against the pitch before the bat is built**
  (`bat_contact.aim_at_pitch`). This is the seam, and skipping it is what made
  the game near-unplayable after the rewrite: the barrel goes on the cursor's
  ray at the barrel's depth, ~2.2 ft out front, but the player is aiming at a
  ball drawn to the plate, where it is 2–5 in lower. A perfectly aimed,
  perfectly timed swing fouled everything and whiffed on a curveball. Fixing it
  roughly doubled fair contact at every difficulty (AMATEUR 23% → 39% of swings,
  fouls 55% → 44%) without touching a single difficulty multiplier — the
  multipliers were never the problem. Any future change that gives something a
  depth axis has to ask the same question of the player's input.
- **Timing shows up as spray and as where on the bat first, and only then as a
  quality penalty.** Being 20 ms early with the bat square is not a worse
  *strike*, it is a pulled ball — so what moves first is `along` (early meets it
  off the end, late on the handle) and the bat's bearing. With the bat isotropic
  this is what the geometry does on its own rather than an aspiration: sweeping
  the **residual** error, `along` runs 1.00 at the very tip 14 ms early, through
  the sweet spot at 0, to 0.62 on the handle 30 ms late, and misses entirely
  past ~14 ms early because not even the tip is there yet. That is a hitter
  getting jammed when late and reaching when early, out of two solids and a
  clock. Quality then falls for two reasons: the ball coming off the barrel
  entirely, and the borrowed time the assist had to cover (`timing_score`).
  - A consequence worth knowing when reading tests: at the default difficulty
    the assist covers ±26 ms, so a sweep of ±20 ms is slid to on-time and the
    geometry sees a *perfectly timed* swing every time. Any test about how
    timing reaches the bat has to work in the residual — `tests/test_bat_contact.py`
    does it with a `TIGHT` difficulty whose budget is 5 ms. A test that swept
    ±20 ms at AMATEUR and still saw the ball move would mean the assist had
    stopped working.
- **The timing forgiveness is an assist, not a tolerance — it moves the swing
  in time rather than stretching the bat in space.** A real 2.9 in bat can catch
  a 95 mph pitch over a few milliseconds; this game has always granted tens.
  `resolve_contact` slides the whole swing by up to `timing_assist_s`
  (`TIMING_ASSIST_BASE_S` 0.026 s, scaled by `contact_timing_window`) toward the
  ball, then asks the plain isotropic question — do these two solids intersect.
  Contact is therefore a real intersection and `Contact.surface_gap_ft` is
  bounded by `margin_ft`.
  - **It used to be spent in space, and that was the bug.** The bat was an
    ellipsoid stretched along the ball's flight line by `cushion × ball speed`
    — 5.7 ft at ROOKIE against a 99 mph fastball, a tube four bat-lengths long
    — so "contact" routinely meant the bat was on the ball's *line* and feet
    away from the ball. 63% of recorded contacts had visible daylight, 16% over
    two feet. Worse, the residual was **charged back as an aim error**: a pitch
    descends, so 2.6 ft of reach is five inches of vertical, well past the
    2.75 in the geometry can reach and graded by a sigma picked for half that
    range. Timing error arrived disguised as "the bat was over the ball" and
    was the largest single term in quality.
  - **The borrowed time is charged explicitly** (`timing_charge_sigma_s`, over
    a `TIMING_CHARGE_SIGMA_FLOOR_S` of 0.020 s). The geometry is shown the slid
    swing and cannot see the slide, so without this a swing anywhere inside the
    budget scores exactly 1.00 — a flat plateau of max-quality contact 52 ms
    wide at ROOKIE. The floor is **calibrated, not chosen**: it holds the
    whiff/foul/fair split and the fair-quality quantiles at what the anisotropic
    model produced over the same player model.
  - **The charge is never narrower than the budget it charges for**, and it was
    a bare 0.020 s for a while, which **inverted the ladder at the easy end**.
    The charge is a Gaussian in the slide while `timing_assist_s` runs 39 ms
    (ROOKIE) down to 10 (HALL OF FAME), so a fixed width meant the easier the
    setting the more slide it granted and the deeper the charge could dig. A
    swing that spent its whole allowance capped at quality 0.531 at ROOKIE
    against 0.956 at HALL OF FAME, and once `foul_threshold` moved with it that
    left ROOKIE **1.72 in** of vertical aim room against 2.06 at AMATEUR, 2.12
    at PROFESSIONAL and 2.13 at ALL STAR — *the easiest setting was the
    strictest on the ladder for a mistimed swing*, and ~45% of AMATEUR contacts
    sat at full saturation. That is the mechanism behind "even on rookie it is
    all foul balls": difficulty gave with one hand (a bigger slide, so contact
    instead of a whiff) and took with the other (a bigger charge, so a lower
    quality and a foul), converting whiffs into fouls rather than either into
    balls in play. Scaling with the budget makes spending your whole allowance
    cost the same fraction of quality everywhere — the setting decides how much
    error is forgiven, not what forgiveness costs. The floor keeps PROFESSIONAL
    and up exactly as calibrated, since their budgets are already inside it.
    `test_the_charge_is_never_narrower_than_the_budget_it_charges_for` and
    `test_an_easier_difficulty_never_charges_a_full_budget_swing_more` are the
    pins.
  - **The charge joins the geometric mean rather than multiplying it.** Quality
    is now the geometric mean of *three* independent ways to be off — along the
    bat, across it, and how much of the clock the swing was given. Multiplied on
    the outside it flattened the top of the distribution (best available 0.89
    against 0.96), which is the end of the scale EV is anchored on.
  - The slide deliberately does not let the *ball* be sampled at a time of the
    model's choosing. An earlier draft swept the ball as a capsule and took the
    closest approach, which let a mistimed swing pick the instant that flattered
    it: quality came out non-monotone in timing error, dipping at dead-on and
    peaking at ±20 ms. The swing is slid by a stated amount off a datum the
    player is actually racing; the ball is left where it is.
  - Symmetric on purpose. Recorded swings run **systematically +19 ms late**
    (median foul +30) — human reaction time against a 150 ms `SWING_DURATION_MS`,
    not noise — and helping the late side more would paper over the one habit a
    player can be taught. It stays legible in `swing_timing_signed_ms`, in the
    replay's bands, and now in the `ASSIST n MS` marker.
- **Difficulty is carried on the swing, never re-read at replay time.**
  `aim_assist`, `zone_size_mult` and `timing_window_mult` are all stamped at
  commit and carried on `SwingRecord`, because the replay both rebuilds the bat
  and re-sweeps the swing to measure its timing windows. A player who changed
  difficulty between the swing and the replay would otherwise be shown a bat
  nobody swung and a window nobody swung in. `HitOutcomeManager.contact_multipliers`
  is the seam, so the gameplay layer still never reads the multiplier dict.
- **A ball can be foul in two independent ways, and only one of them is about
  how well it was struck.** `Contact.is_foul` asks both: `quality < threshold`
  (tipped, topped, caught on the handle or off the end) **or**
  `spray.is_foul(spray_deg)` (hooked or sliced past a pole). Not two models of
  one thing — the first is about how square the contact was and the second
  about which way it left, and a ball can fail either alone. With the verdict
  resting on quality alone a barrelled ball could never be hooked foul and a
  mishit that stayed between the lines could never be the dribbler in play that
  it is; both are ordinary baseball and neither could happen.
  - **Direction cannot carry the verdict alone**, and this was measured before
    it was written: it caps near 25% of contact against a real ~50%, because
    the term that would have to carry the rest is *location*, and pushing that
    far makes a flawless swing on a strike an automatic foul. Quality cannot
    carry it alone either — it cannot see which way the ball went.
  - `FOUL_QUALITY_THRESHOLD` came down from 0.67 to 0.52 and the span from 0.30
    to 0.22 because of it, then **back up to 0.59** when `spray`'s location term
    was made to saturate. The two must move together or the total foul rate
    drifts: direction was carrying 24–28% of contact by manufacturing a foul out
    of a saturated term, and carries 18–21% honestly now, so quality takes the
    difference back. Measured over identical contacts, total foul 47.4% before
    against 47.6% after. Direction supplies ~24% of contact at AMATEUR, so
    the two together hold the total at ~48% where quality alone sat at 57%.
- **Difficulty has to reach both touching the ball and squaring it up.**
  `contact_zone_size` → `margin_ft` (the bat's isotropic tolerance),
  `contact_timing_window` → `timing_assist_s` (how much of the clock is given)
  **and** `foul_threshold`. Without that last one a harder setting would only convert
  fair contact into fouls at the edges and leave squaring-it-up exactly as easy,
  which is not what the setting has ever meant — it scaled the perfect and foul
  windows together. `POWER_MARGIN_FT` keeps a power swing harder than a contact
  swing even at the difficulty where the two windows agree; that difference used
  to be the rectangle's 50 px versus 25 px.
  - It now reaches fair/foul by a **third** route as well, and that one is
    emergent: a smaller `timing_assist_s` leaves more residual timing on the
    bat, and the bat is what points the ball. Nothing in `spray` is tuned for
    difficulty and nothing there should be.
- **`margin_ft` scales `BASE_MARGIN_FT`; it does not offset it.** Written as
  `(contact_zone_size - 1.0) * K` the bat's tolerance was exactly **0.0 at
  AMATEUR** and negative at every setting above it — a bat thinner than a bat —
  so the default difficulty asked the player to place a mouse cursor inside the
  real 2.75 in a bat and a ball are between them, which is 22 px on a moving
  target. It read as a cliff: dead-on scored 1.00, three inches high fouled,
  four inches high missed outright. Recorded play at AMATEUR whiffed **79% of
  222 swings** against MLB's 24%. "Contact zone size" has never meant "how much
  is added relative to Amateur". `test_amateur_has_real_vertical_tolerance` and
  `test_the_zone_multiplier_scales_the_margin_rather_than_offsetting_it` pin it.
- **The aim assist moves the bat; the tolerances only widen it, and the
  difference is the point.** `aim_assist` (0.90 at ROOKIE down to 0.20 at HALL
  OF FAME) is the fraction of the player's *own* aim error that
  `bat_contact.aim_at_pitch` removes before the swing is built — the adjustment
  a hitter makes once they have read the pitch, so the bat does not end up
  exactly where they set out to put it. Because it moves the bat rather than
  fattening it, it lifts contact **quality**, which is what lets it reach
  getting hits rather than only making contact; `margin_ft` cannot do that by
  construction. **It is the only difficulty dial that produces balls in play,
  and that is measured, not asserted.** Swept alone at AMATEUR over a player
  model fitted to recorded play (aim scatter 0.75 ft/axis, timing N(+19, 48) ms),
  `contact_zone_size` from 0.7 to 2.5 — a 3.6× change in the bat's tolerance —
  moves fair contact 24.4% → 25.0% of swings while whiffs go 34% → 17% and
  fouls 42% → 58%: a 1:1 whiff-to-foul conversion and nothing else, because a
  marginal contact admitted by a wider tolerance has a large
  `vertical_offset_ft` by construction and lands under the foul threshold. Over
  the same model `aim_assist` from 0.20 to 0.95 moves fair contact 8.3% → 39.0%.
  The easy end was raised off that measurement (AMATEUR 0.65 → 0.80, ROOKIE
  0.85 → 0.90), which puts the default at whiff 28% / foul 34% / fair 38%
  against MLB's 24/38/38. The response **saturates around 0.85–0.90**, so
  ROOKIE has little left to gain and the harder rungs are where the ladder now
  has a cliff — AMATEUR 38% fair against PROFESSIONAL's 15%. The **timing
  assist is its sibling** — it moves the bat in time
  where this one moves it in space — which is why it also lifts quality and why
  it has to be charged for. There are two assists and one tolerance now, and
  keeping the three legible as separate things is the rule.
  - It is the one thing in that function that is **game feel rather than
    geometry**. Everything else there corrects a projection bias the player
    could not have seen; the assist shrinks an error they genuinely made. Keep
    the two legible as separate things — at `assist = 0` the function is the
    pure translation it has always been, and every test of the translation runs
    at that default.
  - **`MAX_ASSIST_FT` (1.0) is what keeps it a compensation and not a magnet**,
    and it has to be that generous to do anything: recorded play scatters the
    aim by about a foot, so a 4 in cap saturates on most real swings and the
    strength dial stops mattering (47% whiffs against 30% at a foot, with
    nothing in between). The clamp is **radial**, so the assist can change the
    size of the player's error but never its direction.
  - **Difficulty reaches it through `HitOutcomeManager.resolve_aim`**, beside
    `resolve_swing` and `_foul_threshold`, so the gameplay layer never reads
    the multiplier dict. The strength used is stamped on the simulation at
    commit and carried on `SwingRecord.aim_assist` — *not* re-read at replay
    time, or a player who changed difficulty afterwards is shown a bat nobody
    swung, the same failure as preferring the cursor at bat arrival.
  - **`bat_path` still never sees the pitch.** What the assist changes is which
    point on the cursor's ray the player is taken to have meant, which was
    already this seam's job.
- **`on_time` keeps its name and its three values but is no longer a timing
  grade** — it is `swing_verdict(contact)`, i.e. what the geometry produced.
  The analysis package's definition of it needs reading in that light.
- **`vertical_offset` is measured in real feet now** (`Contact.vertical_offset_ft`)
  and converted once, in `HitOutcomeManager.contact_metrics`, into the screen
  pixels the batted-ball type anchors and `hit_animation._pick_shape` have
  always spoken. Don't restate those constants in inches — the two scales happen
  to be close: the reachable offset is ±2.75 in, which at the current
  `ft_per_px_z` of 0.01333 is **±17.2 px**. (This file said ±20.6 for a long
  time — that figure belongs to a `scale_y` of 2700 and is the same units-drift
  trap it warns about, one axis over.) Converting at the seam keeps one set of
  tuned numbers.
- **The sweep runs on an input frame, so it has a budget.** Walking 33 stations
  along the bat at every one of 221 time samples cost 12 ms a swing — most of a
  frame, spent at the exact moment the game is reading the player. `_closest_along`
  solves the closest point instead of walking to it, and it is *also* more
  accurate: the walk landed the sweet-spot fraction 0.19 out on average, and
  that fraction is most of what quality is made of. A test guards the order of
  magnitude.
- **`collision_angled` is gone, with the rectangle it tested.** It had a sign
  error for the life of the project (fixed 2026-08): it rotated the circle by
  `R(+angle)` and tested an axis-aligned box, which is a test against a box at
  `-angle` — the mirror image, so aiming at a low pitch tilted the barrel *up*.
  Because the rectangle was long and thin that changed the bat's effective
  reach as a function of aim height, and contact ran 67% low / 93% middle / 88%
  high. The solved pose cannot reproduce it: the knob goes on the pivot pixel
  and the sweet spot on the cursor pixel, and there is no sign to get wrong.
  `test_aiming_low_points_the_barrel_low` is the successor pin.
- **Recorded play from before a contact-geometry change describes a different
  bat**, and this has now happened five times: the `collision_angled` sign fix,
  the rectangle→`bat_contact` rewrite, the cushion→slide change, the arrival
  of [spray](#spray-direction-sprayspy), and `spray`'s location term being made
  to **saturate**. The last two both changed the *foul verdict*'s shape:
  direction became an independent way to be foul (threshold 0.67 → 0.52), and
  then stopped manufacturing fouls out of a saturated geometry (0.52 → 0.59).
  Either way which contacts are fair is a different set, `contact_quality` has a
  different distribution over them, and `on_time` means a slightly different
  thing again. Rows either side are not comparable. Archive and clear with
  [reset_tracking.py](strikefactor/data/reset_tracking.py), then re-derive
  `contact_audio.EV_CALIBRATION` from the new quantiles — see the warning under
  [Contact Audio](#contact-audio) about never tuning against a uniform quality
  sweep.
  - **Four places are anchored to those same quantiles and must move
    together**: `contact_audio.EV_CALIBRATION`, `tools/sim.py`'s
    `QUALITY_QUANTILES` / `QUALITY_BY_SHAPE` / `LAUNCH_ANGLE_QUANTILES` /
    `SPRAY_MEAN_DEG` / `BATTED_BALL_MIX` (the shared samplers, re-exported
    by `tests/conftest.py` under their old names),
    `tests/test_infield_hit_verdict.py::_QUALITY_QUANTILES` (a mirror, pinned to
    conftest by a drift test), and `tests/test_contact_audio.py`'s quantile
    checks. Move one without the others and the exit-velocity model and the
    fielding model start describing different batters. A Monte Carlo over a
    plausible player model puts quality at p25/p50/p90 = **0.720/0.807/0.941**
    (re-measured 2026-09-10), against 0.689/0.763/0.937 immediately before,
    now that the location term saturates, against 0.653/0.743/0.932 immediately
    before it, 0.717/0.769/0.918 for the slide model, 0.70/0.81/0.98 for the
    anisotropic bat and 0.77/0.89/0.98 for the rectangle. At the last change the
    bottom tail lifted and the top barely moved, because the balls the
    straight-line term was sending foul at −59° were *well struck*.
  - **`SPRAY_MEAN_DEG` moved too, and not because the bat stopped pulling**:
    +4.4° → +1.8°. The opposite-field tail used to be fouled off past the line,
    so it was missing from the fair population and the surviving mean sat too
    far to the pull side. Releasing it moves the mean, not the bat.
  - **Spray is not uniform either, and that is the same trap one axis over.**
    A `HitAnimation` built without a `spray_deg` sends the ball to *exactly*
    dead centre, so a sweep that forgets it puts every grounder over second
    base — the one place middle infielders cannot reach — and reports a 17%
    infield-hit rate against a real 6-8%. Before `spray` the animation drew its
    own angle, so tests got a spread for free. `conftest.realistic_spray` is the
    sampler (mean +1.8°, sd 19.9°); `tests/test_infield_hit_verdict.py` mirrors
    its constants and a drift test pins the two together.
  - **Calibrate against the model you are replacing, not against the recorded
    rates**, unless the recording is all post-change: `strikefactor.db` holds
    rows from several vintages at once, and only the most recent describe the
    bat currently in the game.

### Batted-ball sidespin (`batted_ball_path.py`)
`BattedBallPath` adds a bounded lateral bend to the existing carry/hang-time
model; it does not integrate aerodynamic forces and does not change carry.
The signal is `Contact.attack_deg - Contact.pose_attack_deg`, resolved once at
the `PitchSimulation` handoff and mirrored into field coordinates by batter
handedness. The quadratic path keeps the original spray bearing as its initial
tangent, then accumulates 2/12/18/8 ft maximum drift for grounders, liners,
flies and pop-ups. Rendering, the shadow, low-ball fielder interception and
wall collision all inspect that same path. Its landing tangent is handed to
`ground_roll`, so the ball does not snap back to the old straight bearing when
it touches grass. Curvature is reduced near a wall or foul line rather than
being allowed to reverse a fair/foul or in-park classification already settled
upstream. `HitAnimation.handedness_sign` used to be named `spin`; it is only a
coordinate mirror and must not be reused as physical ball spin.

- Swing detection is in [pitch_simulation.py](strikefactor/gameplay/pitch_simulation.py) (W/E key handlers)
- Hit outcome calculation is in [hit_outcome_manager.py](strikefactor/gameplay/hit_outcome_manager.py)
- Hit animation handoff is in `PitchSimulation._start_hit_animation()`; trajectory shape is picked in `hit_animation._pick_shape()`
- Difficulty multipliers are defined in [settings_manager.py](strikefactor/settings_manager.py) and converted in [bat_contact.py](strikefactor/gameplay/bat_contact.py)
- Batted-ball direction is [spray.py](strikefactor/gameplay/spray.py); every consumer reads `Contact.spray_deg`

## File Organization
```
.
├── pyproject.toml           # Deps, ruff + pytest config, `strikefactor` console script
├── requirements.txt         # Runtime deps only (same set as pyproject)
├── tests/                   # Pytest suite; conftest.py forces headless SDL
├── pitch_analysis.py        # CLI: figures + report.html, or --terminal tables
├── batting_analysis.py      # Offline batting-tendency visualizations
├── tools/                   # Dev tooling; NOT installed (see packages.find)
│   ├── sim.py               # Headless ball-in-play sim + the batter model
│   └── calibrate_defense.py # Sweeps the defense ladder; python -m tools.calibrate_defense
├── docs/
│   ├── defense-strength.md         # Defense setting + misplay model (sourcing, calibration)
│   ├── fielding-replay-plan.md     # Fielding capture; its presentation half is superseded
│   ├── infield-timing-refactor.md  # Batted-ball physics: sourcing for every constant
│   ├── pitch-analysis-refactor.md  # Analysis design doc (metric definitions, layering)
│   └── unified-review.md           # The one review workspace (V/R/F): design + lifecycle
├── analysis/                # Offline analysis package (shared by both scripts)
│   ├── data.py              # SQLite -> pandas, derived columns, Context
│   ├── filters.py           # Filter dataclass + shared CLI options
│   ├── metrics.py           # Pure DataFrame -> DataFrame statistics
│   ├── theme.py             # Palettes, labels, outcome groups, benchmarks
│   ├── render_mpl.py        # Figure/table helpers
│   ├── render_term.py       # rich terminal renderer (ASCII fallback)
│   ├── report.py            # HTML index over the generated PNGs
│   └── figures/             # One module per section; registry in __init__.py
└── strikefactor/
    ├── __init__.py              # Package marker (see "Running the Game")
    ├── __main__.py              # `python -m strikefactor` entry point
    ├── main.py                  # Game class, managers, HUD dispatch
    ├── config.py                # Global constants (screen, physics, ABS, CHALLENGES_PER_SIDE)
    ├── outcomes.py              # The outcome vocabulary: words, groups, colors, db_key
    ├── settings_manager.py      # Settings persistence (settings.json)
    ├── key_binding_manager.py   # Key binding management
    ├── helpers.py               # ScoreKeeper, PitchDataManager, UI helpers
    ├── ai/                      # Q-learning pitch selection + BatterProfile
    │   ├── AI_2.py              # ERAI Q-learning class
    │   ├── batter_profile.py    # In-session player tendency tracking
    │   ├── compat.py            # Legacy-module-path unpickler for *_ai.pkl
    │   ├── pitch_priors.py      # Real usage priors anchoring the Q-learned mix
    │   ├── *_ai.pkl             # Per-pitcher Q-tables
    │   └── ai_umpire.pkl        # ML model for ball/strike calls (lazy; see prewarm.py)
    ├── pitchers/                # See "Adding a New Pitcher"
    │   ├── pitcher.py           # Base class: arsenal, stats, pitch registration
    │   ├── pitch_locations.py   # Named location archetypes (pitch_locations.json)
    │   └── {Sale,Degrom,Mcclanahan,Yamamoto,Sasaki}.py  # Concrete arsenals
    ├── gameplay/                # Game logic
    │   ├── game_states.py       # All game state classes (incl. Sandbox*)
    │   ├── game_state_manager.py# State machine management
    │   ├── pitch_simulation.py  # Pitch physics + simulation loop
    │   ├── hit_outcome_manager.py # Hit outcome resolution
    │   ├── hit_animation.py     # Top-down ball-flight playback after contact
    │   ├── ball_flight.py       # Pure: launch angle, hang time + carry (deg, ft, s)
    │   ├── bat_path.py          # Pure: where the bat is over a swing (ft, s)
    │   ├── bat_contact.py       # Pure: does the bat hit the ball, and where on it
    │   ├── spray.py             # Pure: which way the ball went (deg, pull-positive)
    │   ├── batted_ball_path.py  # Pure: bounded lateral bend on that bearing (ft)
    │   ├── park.py              # Pure: where the fence is, and what it does to a flight
    │   ├── defense.py           # Pure: how good the defense is (ft/s, s, misplay rates)
    │   ├── ground_roll.py       # Pure: landing speed, bounce, roll (ft, s)
    │   ├── infield_timing.py    # Pure: does the throw to first beat the runner
    │   ├── extra_bases.py       # Pure: does the runner take second / third
    │   ├── swing_record.py      # Captured swing, replayable (Game.last_swing)
    │   ├── fielding_record.py   # Immutable presentation frames of a played ball
    │   ├── review_record.py     # One pitch's review data: points + swing + fielding
    │   ├── review_store.py      # Session review history; bounded fielding-clip cache
    │   ├── challenge_manager.py # ABS challenges-remaining bookkeeping
    │   ├── gameday_manager.py   # 9-inning sim, bullpen, walk-offs, box score
    │   ├── random_scenario.py   # Themed Sandbox start states
    │   ├── prewarm.py           # Background load of pandas/sklearn at startup
    │   ├── batter.py            # Batter sprite/state
    │   └── field_renderer.py    # In-game field rendering
    ├── ui/                      # UI components and managers
    │   ├── ui_manager.py        # Main UI orchestrator (button visibility, pitch buttons)
    │   ├── scouting_panel.py    # Pitcher scouting report panel
    │   ├── scorebug.py          # Legacy bottom-bar HUD
    │   ├── broadcast_hud.py     # Four-corner HUD
    │   ├── minimal_hud.py       # Corner-widget HUD
    │   ├── abs_challenge_overlay.py # ABS replay overlay
    │   ├── swing_replay_overlay.py  # Slow-mo bat path + timing analysis
    │   ├── review_overlay.py    # The one modal review workspace (V/R/F)
    │   ├── review_views.py      # PitchViz / swing / fielding view adapters
    │   ├── review_playback.py   # Shared transport: source ms, never frame counts
    │   ├── review_modal.py      # The one pause + input boundary for review
    │   ├── fielding_renderer.py # Shared drawing: live fielding and recorded frames
    │   ├── pitcher_carousel.py  # GameDay starter picker
    │   ├── gameday_theme.py     # Shared GameDay palette/chrome + linescore renderer
    │   ├── play_by_play_panel.py # Scrollable, filterable play-by-play log
    │   ├── pitching_box_panel.py # Scrollable pitching box score (all arms, both staffs)
    │   ├── settings_panel.py    # Settings + key-binding screens (drawn rows)
    │   ├── lap_log_panel.py     # Sandbox lap history viewer
    │   └── components.py        # Shared UI primitives
    ├── engine/
    │   ├── contact_audio.py     # Exit-velocity model -> contact sample + gain
    │   └── sound_manager.py     # Audio playback
    ├── assets/
    │   ├── fonts/
    │   ├── images/              # Pitcher/ball/batter sprites + abs/
    │   ├── sounds/              # Grouped by source — see "Contact Audio"
    │   │   ├── contact/         # Bat on ball: weak/medium/solid/hard/crushed
    │   │   ├── mitt/            # Catcher receiving: short/medium/long
    │   │   └── umpire_sounds/   # {ball,strike,strike_3}/ — scanned, not registered
    │   └── theme.json           # pygame_gui theme
    ├── data/                    # Persisted game data
    │   ├── batting_stats.json
    │   ├── batting_stats_legacy_v1.json
    │   ├── gameday_history.json # GameDay results / career record
    │   ├── gameday_sessions.json # Resumable in-progress GameDay games
    │   ├── gameday_sessions.py  # Resumable-session store (writes the JSON above)
    │   ├── gameday_maintenance.py # Archive/reset/restore GameDay (JSON + DB slice)
    │   ├── reset_tracking.py    # Archive/reset/restore ALL recorded play
    │   ├── archives/             # Full timestamped snapshots (all modes)
    │   ├── gameday_archives/     # Timestamped GameDay snapshots
    │   ├── lap_history.json     # Sandbox lap log
    │   ├── pitch_locations.json # Location archetypes per pitch type
    │   ├── pitcher_attributes.json # Bullpen role/cap/multiplier tuning
    │   ├── pitch_database.py    # SQLite layer (PitchDB, PitchDatabaseService)
    │   ├── strikefactor.db      # SQLite pitch/at-bat/game log
    │   └── backups/             # Auto-backup snapshots of strikefactor.db
    └── utils/
        ├── physics.py           # Circle/rect collision helpers
        ├── pitch_physics.py     # Statcast-style 3D trajectory + umpire projection
        └── io.py                # Filesystem helpers shared by persistence modules
```

## Working with Assets
- Asset paths are resolved via `get_path()` and `resource_path()` from [config.py](strikefactor/config.py)
- `get_path()`: For development, joins paths from SCRIPT_DIR
- `resource_path()`: For PyInstaller builds, uses `sys._MEIPASS`
- Pitcher sprites stored in [assets/images/{pitcher_name}/](strikefactor/assets/images/)
- Ball sprites in [assets/images/ball/](strikefactor/assets/images/)
