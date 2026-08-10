import random
from dataclasses import dataclass

from strikefactor import config
from strikefactor.utils.pitch_physics import DEFAULT_CAMERA

from .pitch_locations import get_archetypes


@dataclass
class PitchIntent:
    """Where a pitch was aimed vs. where it was actually executed.

    Recorded on the Pitcher each time get_pitch_target() runs. The gap
    between (intent_x, intent_y) and (exec_x, exec_y) is the command miss.
    """
    pitch_type: str
    intent_kind: str      # zone | edge | chase | waste
    intent_x: float
    intent_y: float
    exec_x: float
    exec_y: float
    miss_kind: str        # normal | yank | hang | wild
    break_mult: float
    command_sigma_in: float
    archetype: str        # named location archetype, or '' if generic
    batter_hand: str
    platoon: str          # same | opp

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

    # Strike zone boundaries — single source in config.py.
    ZONE_LEFT = config.ZONE_LEFT
    ZONE_RIGHT = config.ZONE_RIGHT
    ZONE_TOP = config.ZONE_TOP
    ZONE_BOTTOM = config.ZONE_BOTTOM
    ZONE_CENTER_X = config.ZONE_CENTER_X
    ZONE_CENTER_Y = config.ZONE_CENTER_Y

    # Pixels per inch at the plate, derived from the camera so these stay
    # correct if the projection is ever recalibrated. The two axes differ
    # (scale_x != scale_y), which is why command error is applied in inches
    # and converted per-axis rather than as a single pixel sigma.
    PX_PER_INCH_X = DEFAULT_CAMERA.scale_x / DEFAULT_CAMERA.cam_dist / 12.0
    PX_PER_INCH_Y = DEFAULT_CAMERA.scale_y / DEFAULT_CAMERA.cam_dist / 12.0

    # Broad shape families. Location intent and miss behaviour are keyed off
    # these rather than individual pitch codes.
    PITCH_CLASS = {
        'FF': 'fastball', 'SI': 'fastball',
        'FC': 'cutter',
        'SL': 'breaking', 'SLD': 'breaking', 'CB': 'breaking', 'KC': 'breaking',
        'CH': 'offspeed', 'FS': 'offspeed', 'FO': 'offspeed',
    }

    # Where the pitcher is *trying* to put each class of pitch, per count:
    # [zone, edge, chase, waste]. This is intent only — execution error is
    # applied afterwards, so realized zone rates come out lower than these.
    # Calibrated so final zone% lands near Statcast rates per pitch type.
    INTENT_TABLE = {
        'fastball': {
            'first_pitch': [0.52, 0.34, 0.10, 0.04],
            'ahead':       [0.22, 0.36, 0.34, 0.08],
            'behind':      [0.62, 0.32, 0.05, 0.01],
            'even':        [0.45, 0.36, 0.15, 0.04],
            'full':        [0.55, 0.35, 0.08, 0.02],
        },
        'cutter': {
            'first_pitch': [0.45, 0.38, 0.13, 0.04],
            'ahead':       [0.18, 0.34, 0.40, 0.08],
            'behind':      [0.55, 0.36, 0.07, 0.02],
            'even':        [0.38, 0.38, 0.20, 0.04],
            'full':        [0.48, 0.38, 0.11, 0.03],
        },
        'breaking': {
            'first_pitch': [0.32, 0.40, 0.24, 0.04],
            'ahead':       [0.10, 0.26, 0.55, 0.09],
            'behind':      [0.48, 0.38, 0.12, 0.02],
            'even':        [0.25, 0.36, 0.34, 0.05],
            'full':        [0.38, 0.40, 0.19, 0.03],
        },
        'offspeed': {
            'first_pitch': [0.24, 0.38, 0.34, 0.04],
            'ahead':       [0.06, 0.20, 0.64, 0.10],
            'behind':      [0.40, 0.40, 0.18, 0.02],
            'even':        [0.18, 0.32, 0.45, 0.05],
            'full':        [0.30, 0.40, 0.27, 0.03],
        },
    }

    # Which edge of the zone each class works, as [left, right, top, bottom].
    # Replaces the old blanket LOW_BIASED_TYPES pull: fastballs live up,
    # breaking balls and splitters live at the bottom.
    EDGE_WEIGHTS = {
        'fastball': [0.30, 0.30, 0.22, 0.18],
        'cutter':   [0.32, 0.32, 0.14, 0.22],
        'breaking': [0.28, 0.28, 0.06, 0.38],
        'offspeed': [0.24, 0.24, 0.04, 0.48],
    }

    # Chase direction by class — fastballs get chased above the zone,
    # splitters below it.
    CHASE_WEIGHTS = {
        'fastball': [0.22, 0.22, 0.44, 0.12],
        'cutter':   [0.28, 0.28, 0.20, 0.24],
        'breaking': [0.26, 0.26, 0.04, 0.44],
        'offspeed': [0.18, 0.18, 0.02, 0.62],
    }

    # Probability of each non-normal miss, by class. The remainder is a plain
    # Gaussian miss around the intended spot.
    #   yank — pulled glove-side and down; the buried breaking ball
    #   hang — doesn't finish: drifts arm-side, stays up, loses break
    #   wild — non-competitive, nowhere near a strike
    MISS_PROFILES = {
        'fastball': {'yank': 0.08, 'hang': 0.03, 'wild': 0.015},
        'cutter':   {'yank': 0.10, 'hang': 0.05, 'wild': 0.015},
        'breaking': {'yank': 0.15, 'hang': 0.07, 'wild': 0.025},
        'offspeed': {'yank': 0.16, 'hang': 0.06, 'wild': 0.025},
    }

    # Spread of a zone-intent aim point, as a fraction of the zone half-width
    # and half-height. Small = the pitcher aims at a spot near the middle.
    ZONE_INTENT_SPREAD = 0.30

    # Per-pitch-type correction on top of the class intent table, as
    # probability mass moved between 'zone' and 'chase'. Needed where pitches
    # sharing a class have different real zone rates — a changeup is worked
    # in the zone far more than a splitter.
    ZONE_TENDENCY = {
        'FF': -0.05, 'SI': -0.09, 'FC': -0.08,
        'SL': -0.07, 'SLD': -0.07, 'CB': -0.06, 'KC': -0.06,
        'CH': 0.03, 'FS': -0.06, 'FO': -0.06,
    }

    # Command grade (0-1) maps linearly onto a per-axis miss sigma in inches.
    # Calibrated by simulation so realized zone rates match Statcast per pitch
    # type; the old model used one isotropic ~4-5in sigma for every pitch,
    # which is what made offspeed far too easy to land for strikes.
    COMMAND_SIGMA_MIN_IN = 3.0
    COMMAND_SIGMA_MAX_IN = 8.1
    # Misses run larger vertically than horizontally.
    VERTICAL_SIGMA_RATIO = 1.15
    # How much a hanger loses off its break.
    HANG_BREAK_MULT = 0.65

    def __init__(self, xpos, ypos, release_point, screen, name, windup_time, arm_extension,
                 command=0.70, throws='R', pitch_command=None) -> None:
        self.name = name
        self.xpos = xpos
        self.ypos = ypos
        self.release_point = release_point
        self.arm_extension = arm_extension
        self.command = command
        self.throws = throws
        # Per-pitch-type command grades; anything unlisted falls back to the
        # pitcher's overall grade.
        self.pitch_command = dict(pitch_command or {})
        # Screen-x direction of the pitcher's arm side. +pfx_x is screen-left
        # (see UmpireCamera.project), and a RHP runs the ball to +pfx_x.
        self.arm_side_sign = -1 if throws == 'R' else 1
        # Key into data/pitch_locations.json. Subclass names already match the
        # internal roster keys in config.ALL_PITCHERS ('sale', 'degrom', ...).
        self.pitcher_key = type(self).__name__.lower()
        # Populated by get_pitch_target() each pitch; read by PitchSimulation
        # for the break multiplier and by the DB extractor for intent logging.
        self.last_intent = None
        self._last_archetype = None
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

    def get_pitch_names(self):
        return [key for key in self.pitch_arsenal]

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
    BREAKING_TYPES = {'SL', 'CB', 'SLD', 'FS', 'FO', 'CH', 'FC'}

    def get_pitch_target(self, pitch_type='FF'):
        """Return the executed target (screen px) for this pitch.

        Intent and execution are separated: `_choose_intent` picks where the
        pitcher is aiming, `_execute` applies command error on top. The
        intended spot, the miss kind and the resulting break multiplier are
        recorded on `self.last_intent` for PitchSimulation and the pitch DB —
        without that split there is no way to tell a well-executed pitch off
        the corner from one that leaked over the middle.
        """
        pitch_class = self.PITCH_CLASS.get(pitch_type, 'breaking')
        count_state = self._get_count_state()

        intent_kind, intent_x, intent_y = self._choose_intent(
            pitch_type, pitch_class, count_state
        )
        intent_x, intent_y = self._apply_sequence_bias(
            intent_x, intent_y, pitch_type, intent_kind
        )

        exec_x, exec_y, miss_kind, break_mult, sigma_in = self._execute(
            intent_x, intent_y, pitch_class, pitch_type
        )

        batter_hand = self.get_batter_hand()
        self.last_intent = PitchIntent(
            pitch_type=pitch_type,
            intent_kind=intent_kind,
            intent_x=intent_x,
            intent_y=intent_y,
            exec_x=exec_x,
            exec_y=exec_y,
            miss_kind=miss_kind,
            break_mult=break_mult,
            command_sigma_in=sigma_in,
            archetype=getattr(self, '_last_archetype', None) or '',
            batter_hand=batter_hand,
            platoon=self.get_platoon(batter_hand),
        )
        return exec_x, exec_y

    @staticmethod
    def in_sign(batter_hand):
        """Screen-x direction that points *toward* the batter.

        A RHB stands at screen x=330 and a LHB at x=735 (see batter.py) with
        the zone centred at 630, so inside to a RHB is -x on screen. This is
        what lets one archetype table serve both batter hands.
        """
        return -1 if batter_hand == 'R' else 1

    def get_batter_hand(self):
        """Current batter handedness, defaulting to 'R' outside a live game."""
        game = getattr(self, '_game_ref', None)
        batter = getattr(game, 'batter', None) if game is not None else None
        if batter is None:
            return 'R'
        return batter.get_handedness()

    def get_platoon(self, batter_hand):
        """'same' when pitcher and batter share handedness, else 'opp'."""
        return 'same' if batter_hand == self.throws else 'opp'

    def _archetype_target(self, pitch_type, intent, count_state, batter_hand):
        """Pick a named location archetype for this intent. None if undefined."""
        archetypes = get_archetypes(
            self.pitcher_key, pitch_type, self.get_platoon(batter_hand)
        )
        candidates = [a for a in archetypes if a['intent'] == intent]
        if not candidates:
            return None

        weights = [a['weight'] * a.get('counts', {}).get(count_state, 1.0)
                   for a in candidates]
        if sum(weights) <= 0:
            return None
        spot = random.choices(candidates, weights=weights, k=1)[0]

        half_w = (self.ZONE_RIGHT - self.ZONE_LEFT) / 2
        half_h = (self.ZONE_BOTTOM - self.ZONE_TOP) / 2
        in_away = random.gauss(spot['in_away'], spot['spread_x'])
        height = random.gauss(spot['height'], spot['spread_z'])

        # Screen y grows downward, so a positive height is a smaller y.
        return (spot['name'],
                self.ZONE_CENTER_X + self.in_sign(batter_hand) * in_away * half_w,
                self.ZONE_CENTER_Y - height * half_h)

    def _choose_intent(self, pitch_type, pitch_class, count_state):
        """Pick where the pitcher is aiming. Returns (kind, x, y) in screen px."""
        probs = list(self.INTENT_TABLE[pitch_class][count_state])

        tendency = self.ZONE_TENDENCY.get(pitch_type, 0.0)
        if tendency > 0:
            shift = min(tendency, probs[2])
            probs[0] += shift
            probs[2] -= shift
        elif tendency < 0:
            shift = min(-tendency, probs[0])
            probs[0] -= shift
            probs[2] += shift

        intent = random.choices(['zone', 'edge', 'chase', 'waste'], weights=probs, k=1)[0]

        # Named archetypes take priority; the generic geometry below is the
        # fallback for any (pitch, platoon, intent) with no archetype defined.
        batter_hand = self.get_batter_hand()
        spot = self._archetype_target(pitch_type, intent, count_state, batter_hand)
        if spot is not None:
            self._last_archetype = spot[0]
            return intent, spot[1], spot[2]
        self._last_archetype = None

        if intent == 'zone':
            # Aim at a spot, not "somewhere in the zone" — spreading the aim
            # point uniformly across the zone stacks target variance on top of
            # command variance and forces an unrealistically small miss sigma
            # to hit real zone rates.
            half_w = (self.ZONE_RIGHT - self.ZONE_LEFT) / 2
            half_h = (self.ZONE_BOTTOM - self.ZONE_TOP) / 2
            return (intent,
                    self.ZONE_CENTER_X + random.gauss(0, self.ZONE_INTENT_SPREAD * half_w),
                    self.ZONE_CENTER_Y + random.gauss(0, self.ZONE_INTENT_SPREAD * half_h))

        if intent == 'edge':
            edge = random.choices(['left', 'right', 'top', 'bottom'],
                                  weights=self.EDGE_WEIGHTS[pitch_class], k=1)[0]
            if edge == 'left':
                return intent, self.ZONE_LEFT + random.gauss(0, 10), \
                    random.uniform(self.ZONE_TOP, self.ZONE_BOTTOM)
            if edge == 'right':
                return intent, self.ZONE_RIGHT + random.gauss(0, 10), \
                    random.uniform(self.ZONE_TOP, self.ZONE_BOTTOM)
            if edge == 'top':
                return intent, random.uniform(self.ZONE_LEFT, self.ZONE_RIGHT), \
                    self.ZONE_TOP + random.gauss(0, 10)
            return intent, random.uniform(self.ZONE_LEFT, self.ZONE_RIGHT), \
                self.ZONE_BOTTOM + random.gauss(0, 10)

        weights = self.CHASE_WEIGHTS[pitch_class]
        offset = random.uniform(30, 80) if intent == 'chase' else random.uniform(60, 120)
        spread = 20 if intent == 'chase' else 40
        edge = random.choices(['left', 'right', 'top', 'bottom'], weights=weights, k=1)[0]
        if edge == 'left':
            return intent, self.ZONE_LEFT - offset, \
                random.uniform(self.ZONE_TOP - spread, self.ZONE_BOTTOM + spread)
        if edge == 'right':
            return intent, self.ZONE_RIGHT + offset, \
                random.uniform(self.ZONE_TOP - spread, self.ZONE_BOTTOM + spread)
        if edge == 'top':
            return intent, random.uniform(self.ZONE_LEFT - spread, self.ZONE_RIGHT + spread), \
                self.ZONE_TOP - offset
        return intent, random.uniform(self.ZONE_LEFT - spread, self.ZONE_RIGHT + spread), \
            self.ZONE_BOTTOM + offset

    def get_command_grade(self, pitch_type):
        """Command grade (0-1) for one pitch type, falling back to overall."""
        return self.pitch_command.get(pitch_type, self.command)

    def _execute(self, intent_x, intent_y, pitch_class, pitch_type):
        """Apply command error to an intended location.

        Returns (x, y, miss_kind, break_mult, sigma_in). Screen Y increases
        downward, so negative dy is up.
        """
        grade = max(0.0, min(1.0, self.get_command_grade(pitch_type)))
        sigma_in = (self.COMMAND_SIGMA_MAX_IN
                    - grade * (self.COMMAND_SIGMA_MAX_IN - self.COMMAND_SIGMA_MIN_IN))

        # Fatigue degrades command on top of the per-pitch grade.
        _, _, mistake_chance = self.get_fatigue_modifiers()
        sigma_in *= 1.0 + mistake_chance

        sx = sigma_in * self.PX_PER_INCH_X
        sy = sigma_in * self.VERTICAL_SIGMA_RATIO * self.PX_PER_INCH_Y

        x = intent_x + random.gauss(0, sx)
        y = intent_y + random.gauss(0, sy)
        break_mult = 1.0

        profile = self.MISS_PROFILES[pitch_class]
        roll = random.random()
        yank_p = profile['yank']
        hang_p = yank_p + profile['hang']
        wild_p = hang_p + profile['wild']

        if roll < yank_p:
            # Yanked: pulled off glove-side and buried.
            miss_kind = 'yank'
            x -= self.arm_side_sign * random.uniform(0.8, 2.2) * sx
            y += random.uniform(0.5, 1.8) * sy
        elif roll < hang_p:
            # Hung: drifts back toward the middle, stays up, loses its bite.
            miss_kind = 'hang'
            x = x * 0.4 + self.ZONE_CENTER_X * 0.6 + self.arm_side_sign * random.uniform(0, 0.6) * sx
            y = y * 0.4 + self.ZONE_CENTER_Y * 0.6 - random.uniform(0.2, 0.9) * sy
            break_mult = self.HANG_BREAK_MULT
        elif roll < wild_p:
            # Non-competitive — nowhere near a strike.
            miss_kind = 'wild'
            x -= self.arm_side_sign * random.uniform(-2.0, 4.0) * sx
            y += random.uniform(-2.5, 4.5) * sy
        else:
            miss_kind = 'normal'

        return x, y, miss_kind, break_mult, sigma_in

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
        if intent == 'waste':
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
