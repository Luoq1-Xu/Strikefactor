# ⚾ StrikeFactor

A pygame baseball batting simulator that puts you in the batter's box against elite MLB pitchers. Easy to start up and quickly jump into the action. Face off against AI-controlled pitchers with realistic pitch physics and precise timing mechanics.

## 🎮 Getting Started

### Setup
```bash
pip install -r requirements.txt
python strikefactor/main_refactored.py
```

### How to Play
1. **Choose your opponent** - Select which pitcher you want to face
2. **Watch the pitch** - Follow the ball as it flies toward home plate
3. **Time your swing** - Move your mouse cursor to where you think the ball will be
4. **Make contact** - Press **W** for a contact swing or **E** for a power swing at just the right moment

The key is timing and positioning - swing too early or too late, and you'll miss. Power swings have a smaller contact window (requiring more precise timing) but yield better hit outcomes. Contact swings are easier to connect but produce weaker results.

## 🎯 Game Modes

### Standard At-Bat Mode
Face a single inning of continuous at-bats against your selected pitcher.

### GameDay Mode
Full 9-inning baseball simulation featuring:
- Player batting in bottom innings
- Simulated opponent at-bats in top innings
- Automatic pitcher substitutions based on performance
- Complete game log with final statistics
- Win/loss determination

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
| **Chris Sale** | L | Fastball (93), Slider (79), Sinker (92), Changeup (87) |
| **Jacob deGrom** | R | Fastball (99), Curveball (81), Slider (91), Changeup (89) |
| **Roki Sasaki** | R | Fastball (96), Splitter (85) |
| **Yoshinobu Yamamoto** | R | Fastball (96), Splitter (89), Curveball (73) |
| **Shane McClanahan** | R | Fastball (97), Slider (83), Changeup (87), Curveball (78) |

## 🎮 Controls

| Key | Action |
|-----|--------|
| **W** | Contact Swing |
| **E** | Power Swing |
| **SPACE** | Quick Pitch |
| **H** | Toggle UI |
| **Z** | Cycle Strikezone Modes |
| **M** | Toggle Umpire Sound |
| **B** | Toggle Batter Visibility |
| **V** | View Pitches (review pitch locations) |
| **T** | Toggle Track/Analytics Display |
| **ESC** | Return to Main Menu |

All key bindings can be customized in the settings menu.

## ⚙️ Settings

### Difficulty Levels
| Level | Timing Window | Contact Zone |
|-------|---------------|--------------|
| Rookie | +50% | +40% |
| Amateur | Baseline | Baseline |
| Professional | -20% | -10% |
| All-Star | -40% | -20% |
| Hall of Fame | -60% | -30% |

### Display Options
- **Display FPS**: 60 or 120 Hz
- **Engine FPS**: 60 or 120 Hz (affects physics calculations)
- **Display Mode**: Windowed or Fullscreen
- **Resizable Window**: Adjustable game window size

### Audio Settings
- Master volume control
- Umpire calls toggle
- Individual sound effects (pitch, contact, foul, hit, home run)

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

### Statistics Tracking
- Hit location heatmap (9-segment field breakdown)
- Batting average by zone
- Career statistics saved to `batting_stats.json`
- In-game stats: hits, walks, strikeouts, runs

## 🤖 AI System

### Pitcher AI
Q-learning based pitch selection that considers:
- Current count (balls-strikes)
- Outs and runner positioning
- Previous pitch history
- Adaptive learning from player behavior

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