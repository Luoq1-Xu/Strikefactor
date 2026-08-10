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
pip install -e ".[dev]"    # adds pytest + ruff

pytest                     # test suite (headless; SDL uses dummy drivers)
ruff check .               # lint — currently green, keep it that way
```

- Dependencies and tool config live in [pyproject.toml](pyproject.toml).
  `requirements.txt` holds the same runtime set for plain `pip install -r`.
- Tests live in [tests/](tests/). [conftest.py](tests/conftest.py) forces SDL to
  its dummy video/audio drivers before pygame is imported, so no display is needed.
- The ruff rule set is deliberately narrow so `ruff check` passes today; the
  deferred rules (`B`, `UP`, `E731`) are listed in a comment in pyproject.toml.

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
- Factors: swing timing, swing location (high/low relative to ball), contact quality
- Difficulty modifiers affect out probabilities and hit outcomes
- Separate logic for contact swings (W key) vs power swings (E key)
- Outcomes: SINGLE, DOUBLE, TRIPLE, HOME RUN, FLYOUT, GROUNDOUT, LINEOUT, FOUL BALL
- Once an outcome is resolved, `pitch_simulation._start_hit_animation()` hands off rendering to [HitAnimation](#hit-animation), which classifies the trajectory shape and plays it before the result banner appears.

### Contact Audio
[contact_audio.py](strikefactor/engine/contact_audio.py) picks the bat-contact sample and its gain. Pure module — no pygame, no game state — so it is testable without a mixer.
- **Every** bat-on-ball event routes through `SoundManager.play_contact(quality, swing_type)`: fouls, in-play contact and home runs alike. The only thing separating them acoustically is the modelled exit velocity. Selection deliberately takes **no outcome** — the sound fires at impact, before the animation resolves what happened, and a home run that merely carried should not sound like a 112-mph barrel.
- **Home runs are the one exception, and it is not an outcome cue.** `play_contact(..., hr_distance_ft=...)` takes EV from the distance the player is about to see and floors selection at `HOMERUN_MIN_SAMPLE` (`contact_solid`). The reason is that `hit_animation`'s carry model rolls its own random `bias` for distance, so quality and distance genuinely disagree: before this, ~52% of home runs played `contact_weak`/`contact_medium`, which is how a soft crack ended up under a 460 FT readout. The distance is a *better measurement* of how hard the ball was struck than quality is, and it is already fixed by the time the sound plays — `_evaluate_contact()` builds the `HitAnimation` earlier in the same frame. Wall-scrapers still sound merely solid; the floor is not "home runs are always loudest".
- A foul that hooks past the pole (`is_foul_hr`) is **not** a home run and gets no floor and no distance — it takes the ordinary quality path.
- **The EV curve is calibrated, not analytic.** `quality` is only computed for swings that already timed the ball, so its real distribution is skewed hard toward 1.0 (median 0.886 over the recorded contacts, p25 0.770). `EV_CALIBRATION` pins the observed quality quantiles to MLB EV quantiles. A naive linear/power mapping puts the *median* batted ball near the top of the scale — routine grounders then draw the max-crack sample, which is the bug this module exists to prevent. Re-derive the table if `_compute_contact_quality` changes.
- Two layers make a spectrum out of five samples: overlapping EV bands blended at the edges (selection), plus continuous gain within the band (`contact_gain`).
- **Assets are grouped by sound source, one directory per source** — `contact/` (bat on ball), `mitt/` (catcher receiving), `umpire_sounds/` (ball/strike/strike_3 calls). `SoundManager.SOUND_FILES` is the key→path registry; umpire calls are directory-scanned instead, for random variant selection.
- **Keys and filenames describe the sound, never an outcome**: `contact_weak` → `contact_medium` → `contact_solid` → `contact_hard` → `contact_crushed` (files `contact/weak.mp3` … `contact/crushed.mp3`). They were `FOULBALL/SINGLE/DOUBLE/TRIPLE/HOMERUN.mp3`, which became actively misleading once selection moved to EV — `contact_solid` plays on any ~95 mph ball, which may end up a double, a lineout or a foul.
- `mitt_pop_*` are **catcher's mitt** sounds used by `glovepop()`, not bat sounds. They were briefly wired into the contact ladder as weak-contact ticks, which put a mitt slap on balls the batter had just hit — the directory split plus the key prefix is what makes that mistake visible.
- `tests/test_sound_manager.py` guards the whole chain: every ladder rung resolves to a registered key, every registered file exists on disk, every rung is sourced from `contact/`, no mitt sample appears in the ladder, and no key is named after an outcome.
- `HOMERUN_MIN_EV_MPH` hard-gates the top sample regardless of weights.
- **Gain is set on the Channel, never the Sound.** Sounds are shared singletons; `Sound.set_volume()` would leak one playback's level into every later and concurrent play of the same sample. `master_volume` is applied here too — it was in the settings defaults but read by nothing before this.
- Foul contact metrics are computed in `PitchSimulation._compute_foul_contact_metrics()`, called from `_handle_foul_ball` — **not** from `_start_foul_animation`, which is gated behind `foul_animation_enabled`. Moving it back under that gate would leave players with the setting off hearing one flat sample per foul.

### Hit Animation
[hit_animation.py](strikefactor/gameplay/hit_animation.py) renders a top-down ball-flight animation between hit resolution and the outcome banner:
- **HitAnimation class**: Geometric primitives only (no sprite assets). Three motion layers:
  - **Trajectory shape**: `GROUNDER` / `LINER` / `FLY` / `POP_UP`, chosen by `_pick_shape()` from the outcome plus the swing's vertical offset (outs are deterministic; hits are weighted-random per outcome). These are *shape* names, a separate namespace from recorded outcomes — `FLY` is not `FLYOUT`, and the shape keeps the underscore in `POP_UP` where the outcome is `POP UP`. The two meet only where `classified_outcome` is assigned.
  - **Fielders**: All 9 defenders visible (`Fielder` class), with per-outcome primary/backup assignments moving toward the play; idle sway keeps them alive at rest. Defaults in `FIELDER_HOMES`. Out vs. hit *emerges* from whether anyone reaches the ball, so two corrections keep balls up the middle honest: the pitcher carries a follow-through reaction bias (`ROLE_REACTION_BIAS_MS`) plus a per-play clean-fielding roll (`PITCHER_CLEAN_FIELD_PROB`) that drops them from the intercept pool on hard contact, and infielders are range-capped on GROUNDER/LINER (`INFIELD_LOW_BALL_RANGE_PX`) because the animation's stylised ~3 s flight would otherwise give realistic sprint speed two to three times its real range. Every in-flight routing decision reads that cap through `_max_intercept_dist` / `_range_limited_point` — bypassing either one silently restores the old "2B runs down everything over the bag" behavior.
  - **Whose ball it is**: among fielders who can make the play (`_path_intercept().can_make`), the primary is the one with the least ground to cover — *not* the earliest intercept. Ranking on the moment of intercept hands the ball to whoever stands nearest home plate, since the ball reaches their stretch of the path first: a grounder hit dead at the 2B was fielded by the 1B 100% of the time, and on FLY/POP_UP (where every fielder routes to the same landing point and therefore ties) the winner was decided by pool order. `can_make` excludes fielders *behind* the contact point but deliberately not those past the landing spot — a ball dying in front of a fielder is a fielder charging, the most ordinary play there is.
  - **First base is a strict priority list**, not an ETA race: `COVER_ROLE_PRIORITY = ["1B", "P", "2B"]`, first one who isn't fielding the ball and can beat the throw (`COVER_IN_TIME_BUDGET_MS`, measured from **when the ball gets fielded** — `_fielded_at_ms` — not from contact, because the cover man has the whole flight to get there). The 2B covering first is a busted play and lands at ~1% of grounders. Two things make the pitcher's 3-1 work and are easy to undo: `Fielder.break_delay_ms` (the follow-through bias in `ROLE_REACTION_BIAS_MS` is recovery time before they can *field*, and charging it against a run to the bag vetoed them on every 3-1), and `_check_in_flight_intercept` skipping the cover man, whose route to first crosses the flight path of anything hit at the 1B. `tests/test_fielding_assignment.py` guards all of it.
  - **HR distance overlay**: Readout computed from the actual landing point once the ball clears the wall (home runs only — see [Hit Animation](#hit-animation) notes on fouls).
  - **HR landing** is calibrated to MLB distances (mean ~400 ft, p50 ~400, p90 ~430, ~5% past 440). Two things make that work and are easy to break: the landing angle is **rejection-sampled** over fair territory (`_sample_hr_angle`), never clamped — a clamp stacks every out-of-range draw onto the two boundary angles, putting a visible line of home runs on the foul poles; and carry is specified in **feet**, converted per-angle via `_px_per_ft_at`. Both were wrong before: the angle was clamped to 50°–130° of screen angle, well inside the foul lines at ~30.7°/149.3°, so the corners where the wall is nearest were unreachable, and carry in pixels bought 17% more feet at centre field than down the line. Together they produced 392–476 ft, mean 423 — every home run a no-doubter. `tests/test_hr_distance.py` guards the distribution and the spray.
  - **The park is deep down the lines.** `_wall_r_at` is an ellipse in *screen* space, so the wall measures ~360 ft at the foul line rather than the 330 ft the `WALL_FT_X = 330.0` comment implies (330 is the semi-axis at screen angle 0°, which is in foul territory). Sub-360 ft home runs are therefore geometrically impossible, and the short tail of the distribution is compressed against MLB's. Fixing that means reshaping the drawn wall, not retuning carry.
- Field geometry uses anisotropic feet→pixel projection (`FT_TO_PX_X = 1.85`, `FT_TO_PX_Y = 1.10`) anchored to `HOME = (640, 670)` to mimic MLB Gameday's wide, y-foreshortened look.
- `HitAnimation.classified_outcome` is read back by `PitchSimulation` once the animation finishes — only then are score/runners updated and the outcome banner fired.

### ABS Challenge System
MLB-style automated ball-strike challenge after umpire calls:
- **ChallengeManager** ([challenge_manager.py](strikefactor/gameplay/challenge_manager.py)): Tracks remaining challenges per side (default `CHALLENGES_PER_SIDE` from `config.py`). Successful challenges are retained, failed ones decrement. `set_unlimited(True)` is used in Sandbox to make challenges free.
- **ABSChallengeOverlay** ([abs_challenge_overlay.py](strikefactor/ui/abs_challenge_overlay.py)): Phased replay overlay — intro card (`_PHASE_INTRO_END`) → 2D trajectory replay (`_PHASE_REPLAY_END`) → camera zoom (`_PHASE_ZOOM_END`) → CALL CONFIRMED/OVERTURNED banner.
- Enabled per-game by the `abs_enabled` setting; reset/configured around state transitions in `main.py` (`challenge_manager.reset_all()`, `set_unlimited()`).
- Triggered through the challenge keybind; routes through `Game._on_abs_challenge_*` in [main.py](strikefactor/main.py) (~lines 1450–1500).

### HUD System
Three pluggable HUD renderers, selectable via the `hud_mode` setting and cycled at runtime by `Game.toggle_hud_mode()`:
- **Scorebug** ([scorebug.py](strikefactor/ui/scorebug.py)): Full-width TV-style bottom bar (`hud_mode = "legacy"`)
- **BroadcastHUD** ([broadcast_hud.py](strikefactor/ui/broadcast_hud.py)): Four-corner layout — count top-left, inning/score top-right, pitcher/last-pitch bottom-left, bases bottom-right (`hud_mode = "broadcast"`)
- **MinimalHUD** ([minimal_hud.py](strikefactor/ui/minimal_hud.py)): Compact bottom-right corner widget (`hud_mode = "minimal"`)
- All share a strict black/white/gray palette. `Game._render_hud()` dispatches to the active one; visibility toggles in sync with the global UI toggle.
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
- **History**: Saved per-game to `data/gameday_history.json` via `save_game_result()`; class methods `get_career_record()` and `load_history_record_vs(pitcher)` power the pitcher-vs-record line on the [PitcherCarousel](strikefactor/ui/pitcher_carousel.py).
- **Resume**: `resume_gameday_session()` reattaches the pitch DB to the session's `db_game_id` via `PitchDatabaseService.resume_game()`, so a resumed game keeps **one** `game_id` end to end. Opening a second row instead splits one logical game in two, and the first half then has no final score — its runs become unattributable in the pitching line.
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
- **KeyBindingManager** ([key_binding_manager.py](strikefactor/key_binding_manager.py)): Manages customizable key bindings saved to `key_bindings.json`
  - Default actions: toggle UI (H), strikezone (Z), sound (M), quick pitch (SPACE), view pitches (V), toggle HUD mode, main menu (ESC)
- **config.py**: Global constants (screen size, FPS, strike zone dimensions, physics constants, ABS colors/zone, `CHALLENGES_PER_SIDE`)

### Data & Analytics
- **ScoreKeeper** ([helpers.py](strikefactor/helpers.py)): Tracks game state (outs, runners, score)
- **PitchDataManager** ([helpers.py](strikefactor/helpers.py)): In-memory pitch record used for the per-game PitchViz / VisualizationState
- **batting_stats.json** ([strikefactor/data/](strikefactor/data/)): Historical batting performance for heatmap visualization (legacy aggregate JSON, `batting_stats_legacy_v1.json` is the prior schema)
- **PitchDB / PitchDatabaseService** ([pitch_database.py](strikefactor/data/pitch_database.py)): SQLite-backed persistent pitch log at `strikefactor/data/strikefactor.db`.
  - Tables: `pitches` (full 9-parameter kinematics, derived speed/movement, AB context, outcomes, ABS truth-vs-call), `pitch_trajectories` (20-sample 3D trajectory per pitch), `at_bats`, `games` (one row per Arcade encounter / GameDay / Sandbox session), `batter_profiles` (persisted [BatterProfile](#ai-system) aggregates keyed by mode+difficulty).
  - `exit_velocity_mph` (schema v6) is set on every bat-on-ball event **including fouls**, while `contact_quality` stays NULL on fouls — fouls never run the hit pipeline that populates it. Don't "fix" that asymmetry by widening `contact_quality`: it would silently change what every existing aggregate over that column means. EV is a model output derived from quality (see [Contact Audio](#contact-audio)), not an independent measurement.
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

Key metric definitions worth knowing:
- **Whiff** = `swing_type > 0 AND outcome IN ('strike','strikeout')`. Fouls carry `outcome = 'foul'` and contact carries an in-play outcome, so this is exact. `on_time` grades *timing* (0 mistimed / 1 foul-timing / 2 on time), **not** contact — a well-timed swing still misses on location.
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

### Modifying Swing Mechanics
- Swing detection logic is in [pitch_simulation.py](strikefactor/gameplay/pitch_simulation.py) (W/E key handlers)
- Contact detection uses `collision()` or `collision_angled()` from [utils/physics.py](strikefactor/utils/physics.py)
- Hit outcome calculation is in [hit_outcome_manager.py](strikefactor/gameplay/hit_outcome_manager.py)
- Hit animation handoff is in `PitchSimulation._start_hit_animation()`; trajectory shape is picked in `hit_animation._pick_shape()`
- Timing windows and bat radius defined in [config.py](strikefactor/config.py)

### Adding a Field to the Pitch Database
1. Add the column to the `CREATE TABLE` string in `PitchDB.SCHEMA` in [pitch_database.py](strikefactor/data/pitch_database.py)
2. Bump `SCHEMA_VERSION` and add an `ALTER TABLE` branch in `PitchDB._migrate()` (an auto-backup runs before any migration)
3. Populate the field in `PitchDataExtractor.extract_pitch_record()` from `PitchSimulation` state
4. Add the column to the `INSERT` statement in `PitchDB.insert_pitch()`

### Adding a HUD Mode
1. Create a new HUD class in [strikefactor/ui/](strikefactor/ui/) following the `Scorebug` / `BroadcastHUD` / `MinimalHUD` pattern (palette, screen size constants, `draw(screen)` method)
2. Instantiate it on `Game` in `Game.__init__` ([main.py](strikefactor/main.py))
3. Add the mode string to `SettingsManager.cycle_hud_mode()` and the dispatch in `Game._render_hud()`
4. The `TOGGLE_HUD_MODE` keybind will pick it up automatically once it's in the cycle list

## File Organization
```
.
├── pyproject.toml           # Deps, ruff + pytest config, `strikefactor` console script
├── requirements.txt         # Runtime deps only (same set as pyproject)
├── tests/                   # Pytest suite; conftest.py forces headless SDL
├── pitch_analysis.py        # CLI: figures + report.html, or --terminal tables
├── batting_analysis.py      # Offline batting-tendency visualizations
├── docs/
│   └── pitch-analysis-refactor.md  # Analysis design doc (metric definitions, layering)
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
    ├── settings_manager.py      # Settings persistence (settings.json)
    ├── key_binding_manager.py   # Key binding management
    ├── helpers.py               # ScoreKeeper, PitchDataManager, UI helpers
    ├── ai/                      # Q-learning pitch selection + BatterProfile
    │   ├── AI_2.py              # ERAI Q-learning class
    │   ├── batter_profile.py    # In-session player tendency tracking
    │   ├── compat.py            # Legacy-module-path unpickler for *_ai.pkl
    │   ├── *_ai.pkl             # Per-pitcher Q-tables
    │   └── ai_umpire.pkl        # ML model for ball/strike calls (lazy; see prewarm.py)
    ├── pitchers/                # Pitcher classes (Sale, Degrom, Mcclanahan, Yamamoto, Sasaki)
    ├── gameplay/                # Game logic
    │   ├── game_states.py       # All game state classes (incl. Sandbox*)
    │   ├── game_state_manager.py# State machine management
    │   ├── pitch_simulation.py  # Pitch physics + simulation loop
    │   ├── hit_outcome_manager.py # Hit outcome resolution
    │   ├── hit_animation.py     # Top-down ball-flight playback after contact
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
    │   ├── pitcher_carousel.py  # GameDay starter picker
    │   ├── gameday_theme.py     # Shared GameDay palette/chrome + linescore renderer
    │   ├── play_by_play_panel.py # Scrollable, filterable play-by-play log
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
    │   ├── gameday_maintenance.py # Archive/reset/restore GameDay (JSON + DB slice)
    │   ├── gameday_archives/     # Timestamped GameDay snapshots
    │   ├── lap_history.json     # Sandbox lap log
    │   ├── pitcher_attributes.json # Bullpen role/cap/multiplier tuning
    │   ├── pitch_database.py    # SQLite layer (PitchDB, PitchDatabaseService)
    │   ├── strikefactor.db      # SQLite pitch/at-bat/game log
    │   └── backups/             # Auto-backup snapshots of strikefactor.db
    └── utils/                   # Utility functions (physics)
```

## Working with Assets
- Asset paths are resolved via `get_path()` and `resource_path()` from [config.py](strikefactor/config.py)
- `get_path()`: For development, joins paths from SCRIPT_DIR
- `resource_path()`: For PyInstaller builds, uses `sys._MEIPASS`
- Pitcher sprites stored in [assets/images/{pitcher_name}/](strikefactor/assets/images/)
- Ball sprites in [assets/images/ball/](strikefactor/assets/images/)
