import random
from utils.pitch_physics import DEFAULT_CAMERA

# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


def colorize(text, color):
    """Wrap text with ANSI color codes."""
    return f"{color}{text}{Colors.RESET}"


class Pitcher:

    # Strike zone boundaries (from config.py STRIKEZONE_RECT)
    ZONE_LEFT = 565
    ZONE_RIGHT = 695
    ZONE_TOP = 410
    ZONE_BOTTOM = 560
    ZONE_CENTER_X = 630
    ZONE_CENTER_Y = 485

    # Intent probabilities: [zone, edge, chase, ball]
    INTENT_TABLE = {
        'first_pitch': [0.50, 0.30, 0.15, 0.05],
        'ahead':       [0.15, 0.25, 0.45, 0.15],
        'behind':      [0.65, 0.25, 0.05, 0.05],
        'even':        [0.45, 0.30, 0.20, 0.05],
        'full':        [0.55, 0.30, 0.10, 0.05],
    }

    # Per-pitch-category intent bias adjustments
    PITCH_INTENT_BIAS = {
        'strike': {'FF': 0.08, 'SI': 0.05},
        'chase':  {'SL': 0.10, 'CB': 0.10, 'SLD': 0.10, 'FS': 0.08},
        'low':    {'CH': 0.06},
    }

    def __init__(self, xpos, ypos, release_point, screen, name, windup_time, arm_extension, command=0.70) -> None:
        self.name = name
        self.xpos = xpos
        self.ypos = ypos
        self.release_point = release_point
        self.arm_extension = arm_extension
        self.command = command
        self.command_error_px = 55 - (command * 30)
        # Derive 3D release position from the sprite's visual release point
        # so the ball always appears from where the pitcher's hand is in the sprite
        y0 = 60.5 - arm_extension
        depth = y0 + DEFAULT_CAMERA.cam_dist
        release_side = (DEFAULT_CAMERA.screen_center_x - release_point.x) * depth / DEFAULT_CAMERA.scale_x
        release_height = DEFAULT_CAMERA.cam_height - (release_point.y - DEFAULT_CAMERA.screen_center_y) * depth / DEFAULT_CAMERA.scale_y
        self.release_pos_3d = (
            release_side,
            y0,
            release_height,
        )
        self.pitch_count = 0
        self.outs = 0
        self.era = 0
        self.runs = 0
        self.hits_allowed = 0
        self.strikeouts = 0
        self.walks = 0
        self.pitch_arsenal = {}
        self.actions = []
        self.screen = screen
        self._fatigue_stats = None  # Set by gameday manager for fatigue modifiers
        self.basic_stats = {
            'pitch_count': 0,
            'strikes': 0,
            'balls': 0,
            'strikeouts': 0,
            'walks': 0,
            'outs': 0,
            'hits_allowed': 0,
            'runs_allowed': 0,
            'home_runs_allowed': 0
        }
        self.windup = windup_time

    def load_img(self, loadfunc, name, number):
        self.sprites = loadfunc(name, number)

    def draw(self, screen, number, xoffset=0, yoffset=0):
        screen.blit(self.sprites[number - 1],
                    (self.xpos + xoffset,
                     self.ypos + yoffset))

    def add_pitch_type(self, pitch_func, pitch_name):
        self.pitch_arsenal[pitch_name] = pitch_func

    def recalculate_era(self):
        if not self.outs:
            return
        era = 9 * (self.runs / (self.outs / 3))
        return era

    def update_stats(self, input_dict):
        if 'outs' in input_dict:
            self.outs += input_dict['outs']
        if 'runs' in input_dict:
            self.runs += input_dict['runs']
        if 'strikeouts' in input_dict:
            self.strikeouts += input_dict['strikeouts']
        if 'walks' in input_dict:
            self.walks += input_dict['walks']
        if 'hits_allowed' in input_dict:
            self.hits_allowed += input_dict['hits_allowed']
        if 'pitch_count' in input_dict:
            self.pitch_count += input_dict['pitch_count']
        self.era = self.recalculate_era()

    def update_basic_stats(self, input_dict):
        for key in input_dict:
            self.basic_stats[key] += input_dict[key]

    def get_basic_stats(self):
        return self.basic_stats

    def draw_pitcher(self, start_time, current_time):
        return

    def pitch(self, simulation_func, pitch_name):
        if pitch_name not in self.pitch_arsenal:
            print(f"[WARNING] Unknown pitch '{pitch_name}', falling back to random pitch")
            pitch_name = random.choice(list(self.pitch_arsenal.keys()))
        self.pitch_arsenal[pitch_name](simulation_func)

    # --- Stat Calculation Methods ---
    def _get_innings_pitched(self):
        """Calculate innings pitched from outs."""
        return self.outs / 3.0

    def _calculate_k9(self):
        """Calculate strikeouts per 9 innings."""
        ip = self._get_innings_pitched()
        if ip == 0:
            return 0.0
        return (self.strikeouts / ip) * 9

    def _calculate_bb9(self):
        """Calculate walks per 9 innings."""
        ip = self._get_innings_pitched()
        if ip == 0:
            return 0.0
        return (self.walks / ip) * 9

    def _calculate_kbb_ratio(self):
        """Calculate strikeout to walk ratio."""
        if self.walks == 0:
            return None  # Infinite/undefined
        return self.strikeouts / self.walks

    def _calculate_strike_pct(self):
        """Calculate strike percentage."""
        total = self.basic_stats['pitch_count']
        if total == 0:
            return 0.0
        return (self.basic_stats['strikes'] / total) * 100

    def _calculate_pitches_per_ip(self):
        """Calculate pitches per inning pitched."""
        ip = self._get_innings_pitched()
        if ip == 0:
            return 0.0
        return self.basic_stats['pitch_count'] / ip

    def _calculate_whip(self):
        """Calculate WHIP (Walks + Hits per Innings Pitched)."""
        ip = self._get_innings_pitched()
        if ip == 0:
            return 0.0
        return (self.hits_allowed + self.walks) / ip

    # --- Color Helpers ---
    def _get_era_color(self, era):
        """Get color for ERA based on thresholds."""
        if era is None or era == 0:
            return Colors.GREEN
        if era < 3.00:
            return Colors.GREEN
        elif era < 4.50:
            return Colors.YELLOW
        else:
            return Colors.RED

    def _get_k9_color(self, k9):
        """Get color for K/9 based on thresholds."""
        if k9 >= 9.0:
            return Colors.GREEN
        elif k9 >= 6.0:
            return Colors.YELLOW
        else:
            return Colors.RED

    def _get_bb9_color(self, bb9):
        """Get color for BB/9 based on thresholds."""
        if bb9 <= 2.5:
            return Colors.GREEN
        elif bb9 <= 4.0:
            return Colors.YELLOW
        else:
            return Colors.RED

    def _get_strike_pct_color(self, pct):
        """Get color for strike percentage."""
        if pct >= 65:
            return Colors.GREEN
        elif pct >= 55:
            return Colors.YELLOW
        else:
            return Colors.RED

    def _get_whip_color(self, whip):
        """Get color for WHIP."""
        if whip <= 1.10:
            return Colors.GREEN
        elif whip <= 1.35:
            return Colors.YELLOW
        else:
            return Colors.RED

    # --- Formatted Stats Output ---
    def print_formatted_stats(self):
        """Print a formatted box-style stats summary with colors."""
        BOX_WIDTH = 68

        # Calculate stats
        ip = self._get_innings_pitched()
        era = self.era if self.era else 0.0
        whip = self._calculate_whip()
        k9 = self._calculate_k9()
        bb9 = self._calculate_bb9()
        kbb = self._calculate_kbb_ratio()
        strike_pct = self._calculate_strike_pct()
        pitches_per_ip = self._calculate_pitches_per_ip()

        # Format values
        ip_str = f"{ip:.1f}"
        era_str = f"{era:.2f}"
        whip_str = f"{whip:.2f}"
        k9_str = f"{k9:.2f}"
        bb9_str = f"{bb9:.2f}"
        kbb_str = f"{kbb:.2f}" if kbb is not None else "---"
        strike_pct_str = f"{strike_pct:.1f}%"
        pitches_per_ip_str = f"{pitches_per_ip:.1f}"

        # Build the box
        print()
        print("╔" + "═" * BOX_WIDTH + "╗")

        # Title
        title = f"{self.name.upper()} - PITCHING SUMMARY"
        title_padding = (BOX_WIDTH - len(title)) // 2
        print("║" + " " * title_padding + colorize(title, Colors.BOLD + Colors.CYAN) + " " * (BOX_WIDTH - title_padding - len(title)) + "║")

        print("╠" + "═" * BOX_WIDTH + "╣")

        # Pitching Line Header
        print("║  " + colorize("PITCHING LINE", Colors.CYAN) + " " * (BOX_WIDTH - 15) + "║")

        # Column headers
        headers = f"  {'IP':<8}{'ERA':<8}{'WHIP':<8}{'K':<8}{'BB':<8}{'H':<8}{'R':<8}{'HR':<8}"
        print("║" + headers + " " * (BOX_WIDTH - len(headers)) + "║")

        # Values with colors
        era_colored = colorize(era_str, self._get_era_color(era))
        whip_colored = colorize(whip_str, self._get_whip_color(whip))

        # For colored values, we need to account for ANSI codes in padding
        values_plain = f"  {ip_str:<8}{era_str:<8}{whip_str:<8}{self.strikeouts:<8}{self.walks:<8}{self.hits_allowed:<8}{self.runs:<8}{self.basic_stats['home_runs_allowed']:<8}"
        values_display = f"  {ip_str:<8}{era_colored}{' ' * (8 - len(era_str))}{whip_colored}{' ' * (8 - len(whip_str))}{self.strikeouts:<8}{self.walks:<8}{self.hits_allowed:<8}{self.runs:<8}{self.basic_stats['home_runs_allowed']:<8}"
        print("║" + values_display + " " * (BOX_WIDTH - len(values_plain)) + "║")

        print("╠" + "═" * BOX_WIDTH + "╣")

        # Rate Stats
        print("║  " + colorize("RATE STATS", Colors.CYAN) + " " * (BOX_WIDTH - 12) + "║")

        k9_colored = colorize(k9_str, self._get_k9_color(k9))
        bb9_colored = colorize(bb9_str, self._get_bb9_color(bb9))
        kbb_colored = colorize(kbb_str, Colors.GREEN if kbb and kbb >= 2.5 else (Colors.YELLOW if kbb and kbb >= 1.5 else Colors.RED)) if kbb else kbb_str

        rate_plain = f"  K/9: {k9_str:<10}BB/9: {bb9_str:<10}K/BB: {kbb_str:<10}"
        rate_display = f"  K/9: {k9_colored}{' ' * (10 - len(k9_str))}BB/9: {bb9_colored}{' ' * (10 - len(bb9_str))}K/BB: {kbb_colored}{' ' * (10 - len(kbb_str))}"
        print("║" + rate_display + " " * (BOX_WIDTH - len(rate_plain)) + "║")

        print("╠" + "═" * BOX_WIDTH + "╣")

        # Pitch Efficiency
        print("║  " + colorize("PITCH EFFICIENCY", Colors.CYAN) + " " * (BOX_WIDTH - 18) + "║")

        total_pitches = self.basic_stats['pitch_count']
        strikes = self.basic_stats['strikes']
        balls = self.basic_stats['balls']

        strike_pct_colored = colorize(strike_pct_str, self._get_strike_pct_color(strike_pct))
        ball_pct = 100 - strike_pct if total_pitches > 0 else 0
        ball_pct_str = f"{ball_pct:.1f}%"

        eff_line1_plain = f"  Total: {total_pitches:<6}Strikes: {strikes} ({strike_pct_str})    Balls: {balls} ({ball_pct_str})"
        eff_line1_display = f"  Total: {total_pitches:<6}Strikes: {strikes} ({strike_pct_colored})    Balls: {balls} ({ball_pct_str})"
        print("║" + eff_line1_display + " " * (BOX_WIDTH - len(eff_line1_plain)) + "║")

        eff_line2 = f"  Pitches/IP: {pitches_per_ip_str}"
        print("║" + eff_line2 + " " * (BOX_WIDTH - len(eff_line2)) + "║")

        print("╚" + "═" * BOX_WIDTH + "╝")
        print()

    def get_pitch_arsenal(self):
        return self.pitch_arsenal

    def get_pitch_names(self):
        return [key for key in self.pitch_arsenal]

    def add_action(self, action):
        self.actions.append(action)

    def random_pitch_name(self):
        return random.choice(self.get_pitch_names())

    def attach_ai(self, ai):
        self.ai = ai

    def get_ai(self):
        return self.ai
    
    def get_windup(self):
        return self.windup

    def set_game_ref(self, game):
        """Store reference to game object for count-aware pitching."""
        self._game_ref = game

    def _get_count_state(self):
        """Classify the current count into a state for intent lookup."""
        if not hasattr(self, '_game_ref') or self._game_ref is None:
            return 'even'
        balls = self._game_ref.currentballs
        strikes = self._game_ref.currentstrikes
        if balls == 0 and strikes == 0:
            return 'first_pitch'
        if balls == 3 and strikes == 2:
            return 'full'
        if strikes == 2 and balls <= 1:
            return 'ahead'
        if balls >= 2 and strikes <= 1:
            return 'behind'
        return 'even'

    # Pitch categories for sequencing logic
    FASTBALL_TYPES = {'FF', 'SI'}
    BREAKING_TYPES = {'SL', 'CB', 'SLD', 'FS', 'CH', 'FC'}

    def get_pitch_target(self, pitch_type='FF'):
        """Choose a target location using intent system + command error + sequencing.
        Returns (target_x, target_y)."""
        count_state = self._get_count_state()
        probs = list(self.INTENT_TABLE[count_state])  # [zone, edge, chase, ball]

        # Apply pitch-type bias
        if pitch_type in self.PITCH_INTENT_BIAS.get('strike', {}):
            probs[0] += self.PITCH_INTENT_BIAS['strike'][pitch_type]
        if pitch_type in self.PITCH_INTENT_BIAS.get('chase', {}):
            probs[2] += self.PITCH_INTENT_BIAS['chase'][pitch_type]
        if pitch_type in self.PITCH_INTENT_BIAS.get('low', {}):
            # Bias toward edge (low edge specifically)
            probs[1] += self.PITCH_INTENT_BIAS['low'][pitch_type]

        # Normalize
        total = sum(probs)
        probs = [p / total for p in probs]

        # Choose intent
        intent = random.choices(['zone', 'edge', 'chase', 'ball'], weights=probs, k=1)[0]

        # Pick base target based on intent
        if intent == 'zone':
            target_x = random.uniform(self.ZONE_LEFT + 15, self.ZONE_RIGHT - 15)
            target_y = random.uniform(self.ZONE_TOP + 15, self.ZONE_BOTTOM - 15)
        elif intent == 'edge':
            edge = random.choice(['left', 'right', 'top', 'bottom'])
            if edge == 'left':
                target_x = self.ZONE_LEFT + random.gauss(0, 10)
                target_y = random.uniform(self.ZONE_TOP, self.ZONE_BOTTOM)
            elif edge == 'right':
                target_x = self.ZONE_RIGHT + random.gauss(0, 10)
                target_y = random.uniform(self.ZONE_TOP, self.ZONE_BOTTOM)
            elif edge == 'top':
                target_x = random.uniform(self.ZONE_LEFT, self.ZONE_RIGHT)
                target_y = self.ZONE_TOP + random.gauss(0, 10)
            else:  # bottom
                target_x = random.uniform(self.ZONE_LEFT, self.ZONE_RIGHT)
                target_y = self.ZONE_BOTTOM + random.gauss(0, 10)
        elif intent == 'chase':
            edge = random.choice(['left', 'right', 'top', 'bottom'])
            offset = random.uniform(30, 80)
            if edge == 'left':
                target_x = self.ZONE_LEFT - offset
                target_y = random.uniform(self.ZONE_TOP - 20, self.ZONE_BOTTOM + 20)
            elif edge == 'right':
                target_x = self.ZONE_RIGHT + offset
                target_y = random.uniform(self.ZONE_TOP - 20, self.ZONE_BOTTOM + 20)
            elif edge == 'top':
                target_x = random.uniform(self.ZONE_LEFT - 20, self.ZONE_RIGHT + 20)
                target_y = self.ZONE_TOP - offset
            else:  # bottom — most common chase direction
                target_x = random.uniform(self.ZONE_LEFT - 20, self.ZONE_RIGHT + 20)
                target_y = self.ZONE_BOTTOM + offset
        else:  # ball — clearly outside
            edge = random.choice(['left', 'right', 'top', 'bottom'])
            offset = random.uniform(60, 120)
            if edge == 'left':
                target_x = self.ZONE_LEFT - offset
                target_y = random.uniform(self.ZONE_TOP - 40, self.ZONE_BOTTOM + 40)
            elif edge == 'right':
                target_x = self.ZONE_RIGHT + offset
                target_y = random.uniform(self.ZONE_TOP - 40, self.ZONE_BOTTOM + 40)
            elif edge == 'top':
                target_x = random.uniform(self.ZONE_LEFT - 40, self.ZONE_RIGHT + 40)
                target_y = self.ZONE_TOP - offset
            else:
                target_x = random.uniform(self.ZONE_LEFT - 40, self.ZONE_RIGHT + 40)
                target_y = self.ZONE_BOTTOM + offset

        # Apply sequence-aware location bias
        target_x, target_y = self._apply_sequence_bias(
            target_x, target_y, pitch_type, intent
        )

        # Apply command error
        target_x += random.gauss(0, self.command_error_px)
        target_y += random.gauss(0, self.command_error_px)

        return target_x, target_y

    def _apply_sequence_bias(self, target_x, target_y, pitch_type, intent):
        """Adjust target location based on the previous pitch for tunneling effect.

        Key sequencing patterns:
        - Fastball up → breaking ball down (classic tunnel setup)
        - After a low pitch, bias next pitch higher (eye-level change)
        - After inside, bias outside (and vice versa)
        """
        if not hasattr(self, '_game_ref') or self._game_ref is None:
            return target_x, target_y

        prev_pitch = self._game_ref.last_pitch_type_thrown
        if prev_pitch is None:
            return target_x, target_y

        # Only apply sequencing bias for zone/edge/chase intents (not waste pitches)
        if intent == 'ball':
            return target_x, target_y

        prev_is_fastball = prev_pitch in self.FASTBALL_TYPES
        curr_is_breaking = pitch_type in self.BREAKING_TYPES
        curr_is_fastball = pitch_type in self.FASTBALL_TYPES
        prev_is_breaking = prev_pitch in self.BREAKING_TYPES

        # Classic tunnel: fastball up → breaking ball low
        # Bias breaking balls down after a fastball
        if prev_is_fastball and curr_is_breaking:
            # Pull target toward lower third of zone / below zone
            low_target = self.ZONE_BOTTOM + random.uniform(0, 30)
            target_y = target_y * 0.6 + low_target * 0.4

        # Reverse tunnel: breaking ball low → fastball up
        # Bias fastballs up after a breaking ball
        elif prev_is_breaking and curr_is_fastball:
            # Pull target toward upper third of zone
            high_target = self.ZONE_TOP + random.uniform(-10, 20)
            target_y = target_y * 0.6 + high_target * 0.4

        return target_x, target_y

    def set_fatigue_stats(self, pitcher_stats):
        """Attach PitcherStats from GameDayManager for fatigue modifiers."""
        self._fatigue_stats = pitcher_stats

    def clear_fatigue_stats(self):
        """Remove fatigue stats reference."""
        self._fatigue_stats = None

    def get_fatigue_modifiers(self):
        """Get current fatigue modifiers (velocity_mult, movement_mult, mistake_chance).
        Returns (1.0, 1.0, 0.0) if no fatigue stats attached."""
        if self._fatigue_stats is None:
            return 1.0, 1.0, 0.0
        return (
            self._fatigue_stats.get_velocity_modifier(),
            self._fatigue_stats.get_movement_modifier(),
            self._fatigue_stats.get_mistake_chance(),
        )