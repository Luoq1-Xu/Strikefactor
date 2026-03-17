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

### Game States
The game uses a state machine pattern with states defined in [game_states.py](strikefactor/gameplay/game_states.py):

**Main Menu Flow:**
- **ModeSelectState**: Top-level mode selection (Arcade/Sandbox) with typing effect animation
- **MenuState**: Arcade mode - pitcher selection, settings, and key bindings
- **SandboxMenuState**: Sandbox mode placeholder (future implementation)

**Gameplay States:**
- **GameplayState**: Active batting gameplay
- **SummaryState**: Post-game statistics
- **VisualizationState**: Pitch trajectory animation playback
- **ViewPitchesState**: Review all pitch locations with PitchViz
- **InningEndState**: End-of-inning transition (before summary)
- **GameDayState**: Entry screen for 9-inning GameDay mode
- **GameDayTransitionState**: Manages flow between innings in GameDay mode

**Navigation Flow:**
```
ModeSelectState (game start)
    ├── ARCADE → MenuState (pitcher selection)
    │              ├── Select pitcher → GameplayState
    │              ├── Settings → MenuState (settings submenu)
    │              └── Back → ModeSelectState
    └── SANDBOX → SandboxMenuState (placeholder)
                   └── Back → ModeSelectState
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

### Settings & Configuration
- **SettingsManager** ([settings_manager.py](strikefactor/settings_manager.py)): Persists user settings to `settings.json`
  - Difficulty levels (ROOKIE to HALL_OF_FAME)
  - Audio settings, display mode, batter handedness, strikezone visibility
- **KeyBindingManager** ([key_binding_manager.py](strikefactor/key_binding_manager.py)): Manages customizable key bindings saved to `key_bindings.json`
  - Default actions: toggle UI (H), strikezone (Z), sound (M), quick pitch (SPACE), view pitches (V), main menu (ESC)
- **config.py**: Global constants (screen size, FPS, strike zone dimensions, physics constants)

### Data & Analytics
- **ScoreKeeper** ([helpers.py](strikefactor/helpers.py)): Tracks game state (outs, runners, score)
- **PitchDataManager** ([helpers.py](strikefactor/helpers.py)): Records pitch data for analysis
- **batting_stats.json** ([strikefactor/data/](strikefactor/data/)): Stores historical batting performance for heatmap visualization

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
- Timing windows and bat radius defined in [config.py](strikefactor/config.py)

## File Organization
```
strikefactor/
├── main.py                  # Main game loop and managers
├── config.py                # Global constants and configuration
├── settings_manager.py      # Settings persistence
├── key_binding_manager.py   # Key binding management
├── helpers.py               # ScoreKeeper, PitchDataManager, UI helpers
├── ai/                      # AI models and Q-learning implementation
├── pitchers/                # Pitcher classes and base Pitcher class
├── gameplay/                # Game logic (states, simulation, field rendering)
│   ├── game_states.py       # All game state classes
│   ├── game_state_manager.py # State machine management
│   ├── pitch_simulation.py  # Pitch physics and simulation
│   └── gameday_manager.py   # GameDay mode management
├── ui/                      # UI components and managers
│   ├── ui_manager.py        # Main UI orchestrator
│   └── scouting_panel.py    # Pitcher scouting report panel
├── engine/                  # Core engine components (sound, etc.)
├── assets/                  # Images, fonts, and audio files
├── data/                    # Game data (batting stats, etc.)
└── utils/                   # Utility functions (physics)
```

## Working with Assets
- Asset paths are resolved via `get_path()` and `resource_path()` from [config.py](strikefactor/config.py)
- `get_path()`: For development, joins paths from SCRIPT_DIR
- `resource_path()`: For PyInstaller builds, uses `sys._MEIPASS`
- Pitcher sprites stored in [assets/images/{pitcher_name}/](strikefactor/assets/images/)
- Ball sprites in [assets/images/ball/](strikefactor/assets/images/)
