# ⚾ StrikeFactor

A pygame baseball batting simulator that puts you in the batter's box against elite MLB pitchers. Easy to start up and quickly jump into the action. Face off against AI-controlled pitchers with Statcast-style 3D pitch physics, continuous contact quality scoring, and precise timing mechanics.

## 🎮 Getting Started

### Setup
```bash
pip install -r requirements.txt
python -m strikefactor
```

Run from the repository root. (`python strikefactor/main.py` no longer works —
`strikefactor` is a proper package now, so it must be launched as a module.)

### How to Play
1. **Choose your mode** - Select Arcade or Sandbox from the main menu
2. **Choose your opponent** - Select which pitcher you want to face
3. **Watch the pitch** - Follow the ball as it flies toward home plate
4. **Time your swing** - Move your mouse cursor to where you think the ball will be
5. **Make contact** - Press **W** for a contact swing or **E** for a power swing at just the right moment

The key is timing and positioning - swing too early or too late, and you'll miss. Power swings have a smaller contact window (requiring more precise timing) but yield better hit outcomes. Contact swings are easier to connect but produce weaker results.

Contact quality is scored on a continuous 0.0–1.0 scale using timing accuracy and vertical bat-ball alignment (combined via geometric mean), so both dimensions matter equally.

## 🎯 Game Modes

### Arcade Mode
Face a single inning of continuous at-bats against your selected pitcher. Access settings, key bindings, and pitcher selection from the arcade menu.

### GameDay Mode
Full 9-inning baseball simulation featuring:
- Player batting in bottom innings
- Simulated opponent at-bats in top innings with a 9-batter lineup
- Starting pitcher with reliever substitutions based on pitch count, innings pitched, and runs allowed
- Pitcher fatigue system that increases hit probability from pitch 50 onward
- Momentum bonuses for consecutive hits (up to +8%)
- Clutch bonuses with runners in scoring position (+3%)
- Retro-styled inning-by-inning box score panel
- Career win/loss record saved across sessions

### Sandbox Mode
Practice mode for honing your skills against specific pitches:
- Manually select which pitch type to face via on-screen buttons
- Press **Q** to trigger each pitch on demand
- Live triple slash line (BA/OBP/SLG) displayed in the scoreboard
- Great for learning pitch movement and practicing timing

### Random Scenario Mode
Challenge-based at-bats with specific game situations:
- Clutch hitting (2 outs, runners in scoring position)
- Two-strike battles
- Full count scenarios (3-2)
- Bases loaded situations
- Various pressure scenarios

## ⚾ Pitchers

Five elite pitchers, each with unique pitch arsenals and AI behavior:

| Pitcher | Hand | Pitches |
|---------|------|---------|
| **Chris Sale** | L | Four-Seam Fastball (95), Slider (79), Sinker (94), Changeup (87) |
| **Jacob deGrom** | R | Fastball (99), Slider (91), Changeup (89), Curveball (81) |
| **Roki Sasaki** | R | Fastball (96), Splitter (85) |
| **Yoshinobu Yamamoto** | R | Fastball (96), Splitter (89), Curveball (73) |
| **Shane McClanahan** | L | Fastball (97), Slider (83), Changeup (87), Curveball (78) |

Each pitcher has a pre-trained Q-learning AI model that adapts pitch selection based on the game situation. Pitchers also use an intent-based targeting system that classifies count state (first pitch, ahead, behind, even, full) and adjusts zone/edge/chase/ball probabilities accordingly, with per-pitch-type biases (e.g., fastballs target the zone more, sliders target the chase zone).

## 🎮 Controls

| Key | Action |
|-----|--------|
| **W** | Contact Swing |
| **E** | Power Swing |
| **Q** | Trigger Pitch (Sandbox mode) |
| **SPACE** | Quick Pitch |
| **H** | Toggle UI |
| **Z** | Cycle Strikezone Modes |
| **M** | Toggle Umpire Sound |
| **B** | Toggle Batter Visibility |
| **V** | View Pitches (review pitch locations) |
| **T** | Toggle Track/Analytics Display |
| **ESC** | Return to Main Menu |

All key bindings (except swing controls) can be customized in the settings menu.

## ⚙️ Settings

### Difficulty Levels
| Level | Timing Window | Contact Zone | Out Probability |
|-------|---------------|--------------|-----------------|
| Rookie | +50% | +40% | Reduced |
| Amateur | Baseline | Baseline | Baseline |
| Professional | -20% | -10% | +20% |
| All-Star | -40% | -20% | +40% |
| Hall of Fame | -60% | -30% | +60% |

### Display Options
- **Display FPS**: 60 or 120 Hz
- **Engine FPS**: 60 or 120 Hz (affects physics calculations)
- **Display Mode**: Windowed or Fullscreen

### Audio Settings
- Master volume control
- Umpire calls toggle

### Gameplay Options
- Strikezone visibility toggle
- Batter handedness (Right/Left)
- Scouting report display

## 📊 Analytics & Visualization

### Strikezone Display Modes
Cycle through 5 modes with the **Z** key:
1. Hidden
2. Outline only
3. 9-segment grid overlay
4. Heatmap by hit count
5. Heatmap with batting averages

### PitchViz Mode
Visual replay and analysis of thrown pitches:
- Frame-by-frame trajectory animation
- Pitch location visualization on strikezone grid
- Real-time pitch velocity display
- Color-coded outcome indicators (strikes, balls, hits, outs)

### Scouting Report Panel
In-game overlay showing:
- Current pitcher stats (K/9, BB/9, Strike%, WHIP)
- Pitch arsenal with velocity ranges
- Pitch count tracking
- Color-coded performance indicators

### Lap System
Snapshot and track your batting performance over time:
- Press the **LAP** button to save a snapshot of your current session stats
- Each lap records: batting average, hits, at-bats, pitch count, swing count, triple slash (BA/OBP/SLG), and hit breakdown (1B/2B/3B/HR/BB)
- **View Laps** panel shows a scrollable history of all saved laps (most recent first)
- Lap history persists across sessions in `lap_history.json`
- Great for tracking improvement over multiple practice sessions

### Pitch Database
Every pitch is recorded to a SQLite database (`strikefactor.db`) with:
- Full 9-parameter kinematics (position, velocity, acceleration)
- 20-point sampled trajectory for each pitch
- At-bat context (count, outs, runners, batter handedness, previous pitch)
- Swing data (type, timing, outcome)
- Derived metrics (speed, horizontal/vertical break, plate location)
- Session tracking with timestamps for longitudinal analysis

### Statistics Tracking
- Hit location heatmap (9-segment strikezone breakdown)
- Batting average by zone
- Career statistics saved to `batting_stats.json` (cumulative all-time stats)
- Triple slash line (BA/OBP/SLG) and OPS
- In-game stats: hits, walks, strikeouts, runs

## ⚾ Pitch Physics

### Statcast-Style 3D Simulation
Pitches are modeled using MLB Statcast's 9-parameter constant-acceleration kinematic model:
- Full 3D trajectory tracking: x (horizontal), y (toward pitcher), z (vertical)
- Realistic air drag deceleration (~30 ft/s²)
- Magnus force acceleration for spin-induced pitch movement (break)
- Umpire camera projection converts 3D world coordinates to 2D screen view
- Each pitcher has a 3D release position computed from their sprite and camera geometry

### Contact Quality Gradient
Hit outcomes use a continuous quality score (0.0–1.0) based on:
- **Timing accuracy**: Gaussian falloff centered on perfect contact (σ ~35ms)
- **Vertical alignment**: Gaussian falloff centered on perfect bat-ball alignment (σ ~25px)
- Combined via geometric mean so both timing and position matter equally
- Higher quality reduces out probability and increases extra-base hit chance
- Separate outcome tables for contact swings (more singles) vs power swings (more XBH)

### Pitcher Fatigue
- Fatigue builds from pitch 50 onward (0.0–1.0 scale)
- Velocity penalty: up to -5% at max fatigue
- Movement penalty: up to -10% at max fatigue
- Mistake pitch chance: increases with fatigue (up to 15% at 100+ pitches)
- Fatigue labels: Fresh → Low → Moderate → High → Gassed

## 🤖 AI System

### Pitcher AI
Q-learning based pitch selection that considers:
- Current count (balls-strikes)
- Outs and runner positioning
- Previous pitch history
- Adaptive learning from player behavior
- Zone/chase pitch targeting for advanced pitchers (e.g., deGrom)

### Intent-Based Pitch Targeting
Count-aware pitch location system layered on top of Q-learning:
- Count state classification: `first_pitch`, `ahead`, `behind`, `even`, `full`
- Intent probability table determines zone vs. edge vs. chase vs. ball targeting
- Per-pitch-type biases (fastballs favor zone, sliders favor chase, changeups favor edge)
- Command error based on pitcher's individual command rating

### Umpire AI
Pre-trained ML model for consistent ball/strike calls based on pitch location.

## 🎯 Hit Outcomes

Possible results based on timing, swing type, and contact location:
- **Strikeout** (called or swinging)
- **Walk** (4 balls)
- **Single**, **Double**, **Triple**, **Home Run**
- **Foul Ball**
- **Flyout**, **Groundout**, **Lineout**

Power swings increase extra-base hit potential but require more precise timing. Contact swings are more forgiving but produce weaker outcomes.

## 🔧 Requirements

- Python 3.12+
- pygame-ce
- pygame_gui
- pandas
- numpy
- scikit-learn
- matplotlib/seaborn

Have fun!
