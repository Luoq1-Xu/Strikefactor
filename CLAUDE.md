# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

StrikeFactor is a pygame-based baseball batting simulator where players face off against AI-controlled pitchers with realistic pitch physics and timing mechanics. The game features multiple elite pitchers, each with unique pitch arsenals and AI behavior patterns.

## Running the Game

```bash
# Install dependencies
pip install -r requirements.txt

# Run the game
python strikefactor/main.py
```

The game uses Python 3.12+ and pygame-ce for the core rendering and game loop.

## Architecture Overview

### Core Game Loop
The main game is managed by the `Game` class in [main.py](strikefactor/main.py), which orchestrates:
- **GameStateManager** ([game_state_manager.py](strikefactor/gameplay/game_state_manager.py)): Manages transitions between game states (menu, gameplay, summary, visualization, etc.)
- **PitcherManager**: Handles pitcher instances and their AI counterparts
- **AssetManager**: Loads and caches game sprites and assets
- **UIManager** ([ui_manager.py](strikefactor/ui/ui_manager.py)): Manages all pygame_gui UI elements
- **SoundManager** ([sound_manager.py](strikefactor/engine/sound_manager.py)): Handles audio playback
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
- An AI umpire model (`ai_umpire.pkl`) determines ball/strike calls

### Hit Outcome System
[hit_outcome_manager.py](strikefactor/gameplay/hit_outcome_manager.py) determines hit results:
- Factors: swing timing, swing location (high/low relative to ball), contact quality
- Difficulty modifiers affect out probabilities and hit outcomes
- Separate logic for contact swings (W key) vs power swings (E key)
- Outcomes: SINGLE, DOUBLE, TRIPLE, HOME RUN, FLYOUT, GROUNDOUT, LINEOUT, FOUL BALL
- Once an outcome is resolved, `pitch_simulation._start_hit_animation()` hands off rendering to [HitAnimation](#hit-animation), which classifies the trajectory shape and plays it before the result banner appears.

### Hit Animation
[hit_animation.py](strikefactor/gameplay/hit_animation.py) renders a top-down ball-flight animation between hit resolution and the outcome banner:
- **HitAnimation class**: Geometric primitives only (no sprite assets). Three motion layers:
  - **Trajectory shape**: `GROUNDER` / `LINER` / `FLY` / `POP_UP`, chosen by `_pick_shape()` from the outcome plus the swing's vertical offset (outs are deterministic; hits are weighted-random per outcome).
  - **Fielders**: All 9 defenders visible (`Fielder` class), with per-outcome primary/backup assignments moving toward the play; idle sway keeps them alive at rest. Defaults in `FIELDER_HOMES`.
  - **HR distance overlay**: Quality-driven ~365–485 ft readout once the ball clears the wall.
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
- **Box score**: `get_box_score_lines()` feeds the [BoxScorePanel](strikefactor/ui/box_score_panel.py) rendered in the GameDay finale.
- **Play-by-play**: [PlayByPlayPanel](strikefactor/ui/play_by_play_panel.py) renders a stored/live `play_log` as a scrollable log grouped by half-inning, with a running score, ALL/SCORING/YOU/OPP filters, and a sticky inning header. Used by the GameDay history detail screen and the in-game GAME LOG overlay (`GameDayTransitionState._show_game_log`).
- **History**: Saved per-game to `data/gameday_history.json` via `save_game_result()`; class methods `get_career_record()` and `load_history_record_vs(pitcher)` power the pitcher-vs-record line on the [PitcherCarousel](strikefactor/ui/pitcher_carousel.py).
- **Resume**: `resume_gameday_session()` reattaches the pitch DB to the session's `db_game_id` via `PitchDatabaseService.resume_game()`, so a resumed game keeps **one** `game_id` end to end. Opening a second row instead splits one logical game in two, and the first half then has no final score — its runs become unattributable in the pitching line.
- **Maintenance**: [gameday_maintenance.py](strikefactor/data/gameday_maintenance.py) archives, resets, and restores GameDay state. GameDay lives in *three* stores — `gameday_history.json`, `gameday_sessions.json`, and the `game_mode = 'gameday'` rows of `strikefactor.db` — and every operation must cover all three. Archiving the JSON alone lets history say one game while the analysis still aggregates every pitch ever thrown. `--keep-latest` / `--keep-game` retain specific games; `merge_game_fragments()` repairs games split by the pre-fix resume path. Snapshots land in `data/gameday_archives/<timestamp>/` with the DB slice as a standalone queryable SQLite file.

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
- **`POP_UP` is a terminal outcome** and belongs in every PA/BF/out denominator (`theme.TERMINAL_OUTCOMES`).
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
    ├── main.py                  # Game class, managers, HUD dispatch
    ├── config.py                # Global constants (screen, physics, ABS, CHALLENGES_PER_SIDE)
    ├── settings_manager.py      # Settings persistence (settings.json)
    ├── key_binding_manager.py   # Key binding management
    ├── helpers.py               # ScoreKeeper, PitchDataManager, UI helpers
    ├── ai/                      # Q-learning pitch selection + BatterProfile
    │   ├── AI_2.py              # ERAI Q-learning class
    │   ├── batter_profile.py    # In-session player tendency tracking
    │   ├── *_ai.pkl             # Per-pitcher Q-tables
    │   └── ai_umpire.pkl        # ML model for ball/strike calls
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
    │   ├── box_score_panel.py   # Retro 9-inning box score
    │   ├── play_by_play_panel.py # Scrollable, filterable play-by-play log
    │   ├── lap_log_panel.py     # Sandbox lap history viewer
    │   └── components.py        # Shared UI primitives
    ├── engine/
    │   └── sound_manager.py     # Audio playback
    ├── assets/
    │   ├── fonts/
    │   ├── images/              # Pitcher/ball/batter sprites + abs/
    │   ├── sounds/              # Hit/foul sfx + umpire_sounds/{ball,strike,strike_3}/
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
