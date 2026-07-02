# StrikeFactor : A baseball batting simulator
import pygame
import sys
import os
import pickle

# Import pitcher classes
from pitchers.Mcclanahan import Mcclanahan
from pitchers.Sale import Sale
from pitchers.Degrom import Degrom
from pitchers.Yamamoto import Yamamoto
from pitchers.Sasaki import Sasaki
from ai.AI_2 import ERAI, build_state
from ai.batter_profile import BatterProfile

# Import game components
from ui.components import create_pci_cursor
from engine.sound_manager import SoundManager
from gameplay.batter import Batter
from config import get_path, resource_path
from utils.pitch_physics import DEFAULT_CAMERA
from gameplay.field_renderer import FieldRenderer
from gameplay.hit_outcome_manager import HitOutcomeManager
from ui.ui_manager import UIManager
from ui.scorebug import Scorebug
from ui.minimal_hud import MinimalHUD
from ui.broadcast_hud import BroadcastHUD
from helpers import ScoreKeeper
from gameplay.game_state_manager import GameStateManager
from gameplay.random_scenario import RandomScenarioGenerator
from gameplay.challenge_manager import ChallengeManager
from ui.abs_challenge_overlay import ABSChallengeOverlay
from settings_manager import SettingsManager

class AssetManager:
    """Manages loading and caching of game assets."""
    
    def __init__(self):
        self.ball_list = self._load_ball_sprites()
        
    @staticmethod
    def load_pitcher_sprites(name: str, number: int) -> list:
        """Load pitcher sprite images."""
        name = get_path(name)
        counter = 1
        storage = []
        while counter <= number:
            storage.append(pygame.image.load(resource_path(f'{name}{counter}.png')).convert_alpha())
            counter += 1
        return storage
        
    @staticmethod
    def load_pitcher_sprites_experimental(name: str, number: int) -> list:
        """Load experimental pitcher sprites with scaling."""
        counter = 1
        storage = []
        name = get_path(name)
        while counter <= number:
            image = pygame.image.load(resource_path(f'{name}{counter}.png')).convert_alpha()
            storage.append(pygame.transform.scale_by(image, 118 / image.get_height()))
            counter += 1
        return storage
        
    def _load_ball_sprites(self) -> list:
        """Load ball animation sprites."""
        out = []
        ball_dir = get_path('assets/images/ball')
        for filename in os.listdir(ball_dir):
            out.append(pygame.image.load(f'{ball_dir}/{filename}').convert_alpha())
        return out
        
    def create_ball_renderer(self):
        """Create a ball rendering function."""
        counter = 0

        def render_ball(screen, ball_pos):
            nonlocal counter
            # ball_pos[2] is world-y (feet from plate)
            world_y = ball_pos[2]
            proj_radius = DEFAULT_CAMERA.project_radius(world_y)
            size = max(3, min(11, proj_radius))
            ratio = size / 54

            image = pygame.transform.scale(self.ball_list[counter], (int(ratio * 64), int(ratio * 66)))
            screen.blit(image, (ball_pos[0] - (29.22 * ratio), ball_pos[1] - (32.62 * ratio)))
            counter = (counter + 1) % len(self.ball_list)

        return render_ball
class PitcherManager:
    """Manages pitcher instances and AI."""
    
    def __init__(self, screen, asset_manager: AssetManager):
        self.screen = screen
        self.asset_manager = asset_manager
        self.pitchers = {}
        self.current_pitcher = None
        self._initialize_pitchers()
        
    def _initialize_pitchers(self):
        """Initialize all pitchers with their AI."""
        # Create pitcher instances
        self.pitchers = {
            'sale': Sale(self.screen, self.asset_manager.load_pitcher_sprites),
            'degrom': Degrom(self.screen, self.asset_manager.load_pitcher_sprites),
            'yamamoto': Yamamoto(self.screen, self.asset_manager.load_pitcher_sprites),
            'sasaki': Sasaki(self.screen, self.asset_manager.load_pitcher_sprites),
            'mcclanahan': Mcclanahan(self.screen, self.asset_manager.load_pitcher_sprites_experimental)
        }
        
        # Pitcher-specific tunnel pairs: {pitch: [good follow-ups]}
        tunnel_pairs = {
            'sale': {
                'FF': ['SL', 'CH'], 'SI': ['CH', 'SL'],
                'SL': ['FF', 'SI'], 'CH': ['FF', 'SI'],
            },
            'degrom': {
                'FF': ['SL', 'CB', 'CH'], 'SL': ['FF', 'CH'],
                'CB': ['FF'], 'CH': ['FF', 'SL'],
            },
            'sasaki': {
                'FF': ['FO', 'FS'], 'FO': ['FF', 'FS'], 'FS': ['FF', 'FO'],
            },
            'yamamoto': {
                'FF': ['FS', 'CB', 'FC'], 'FS': ['FF', 'SI'],
                'CB': ['FF', 'FC'], 'FC': ['FS', 'CB'], 'SI': ['FS', 'CB'],
            },
            'mcclanahan': {
                'FF': ['SL', 'CB', 'CH'], 'SL': ['FF', 'CH'],
                'CB': ['FF'], 'CH': ['FF', 'SL'],
            },
        }

        # Attach AI to each pitcher with tunnel pairs
        for name, pitcher in self.pitchers.items():
            ai = self._load_ai(name, pitcher)
            if name in tunnel_pairs:
                ai.set_tunnel_pairs(tunnel_pairs[name])
            pitcher.attach_ai(ai)

        # Set default pitcher
        self.current_pitcher = self.pitchers['sale']
        
    def get_pitcher(self, name: str):
        """Get a pitcher by name."""
        return self.pitchers.get(name.lower())
        
    def set_current_pitcher(self, name: str):
        """Set the current active pitcher."""
        pitcher = self.get_pitcher(name)
        if pitcher:
            self.current_pitcher = pitcher
            
    def get_current_pitcher(self):
        """Get the current active pitcher."""
        return self.current_pitcher

    def _load_ai(self, name, pitcher):
        """Load a pitcher's AI from disk, or create a fresh one if unavailable."""
        import sys
        import ai.AI_2 as AI_2
        sys.modules['AI_2'] = AI_2

        pitcher_pitch_names = set(pitcher.get_pitch_names())
        ai_file = get_path(f"ai/{name}_ai.pkl")
        try:
            with open(ai_file, "rb") as f:
                ai = pickle.load(f)
            if set(ai.actions) == pitcher_pitch_names:
                print(f"Loaded AI for {name} ({len(ai.q)} Q-values)")
                return ai
            else:
                print(f"AI action mismatch for {name}, creating fresh AI")
        except (FileNotFoundError, Exception) as e:
            print(f"No saved AI for {name}, creating fresh AI: {e}")
        return ERAI(pitcher.get_pitch_names())

    def save_all_ai(self):
        """Save all pitcher AIs to disk."""
        for name, pitcher in self.pitchers.items():
            ai = pitcher.get_ai()
            if ai is None:
                continue
            ai_file = get_path(f"ai/{name}_ai.pkl")
            try:
                with open(ai_file, "wb") as f:
                    pickle.dump(ai, f)
                print(f"Saved AI for {name} ({len(ai.q)} Q-values)")
            except Exception as e:
                print(f"Failed to save AI for {name}: {e}")

class GameStats:
    """Manages game statistics and state."""
    
    def __init__(self):
        self.reset_game_stats()
        self.outcome_value = {
            'strike': 0.5, 'ball': -0.25, 'foul': 0.3, 'strikeout': 2, 'walk': -1,
            'SINGLE': -1.5, 'DOUBLE': -2, 'TRIPLE': -2.5, 'HOME RUN': -3,
            'FLYOUT': 1.5, 'GROUNDOUT': 1.5, 'LINEOUT': 1.5, 'POP_UP': 1.5
        }
        
    def reset_game_stats(self):
        """Reset all game statistics."""
        self.strikes = 0
        self.balls = 0
        self.current_pitches = 0
        self.pitchnumber = 0
        self.currentballs = 0
        self.currentstrikes = 0
        self.currentouts = 0
        self.currentstrikeouts = 0
        self.currentwalks = 0
        self.homeruns_allowed = 0
        self.hits = 0
        self.last_pitch_type_thrown = None
        self.first_pitch_thrown = False
        self.current_state = build_state(0, 0, 0, 0, 0, None, 'R', 0)
        self.pitch_chosen = None
        self.pitch_history = []

class Game:
    """Main game class - refactored for better OOP design."""
    
    def __init__(self):
        self._initialize_pygame()
        self._setup_display()
        self._initialize_components()
        self._setup_ui_callbacks()
        
    def _initialize_pygame(self):
        """Initialize pygame subsystems."""
        pygame.mixer.pre_init(44100, 16, 2, 4096)
        pygame.init()
        crosshair = create_pci_cursor()
        pygame.mouse.set_cursor(crosshair)
        
    def _setup_display(self):
        """Setup the game display with scaling support."""
        from config import SCREEN_WIDTH, SCREEN_HEIGHT
        self.internal_width = SCREEN_WIDTH
        self.internal_height = SCREEN_HEIGHT
        self.window = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE)
        self.screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.fullscreen = False
        self._update_scaling()
        self.clock = pygame.time.Clock()
        icon = pygame.image.load(get_path("assets/images/icon.png")).convert_alpha()
        pygame.display.set_icon(icon)
        pygame.display.set_caption('StrikeFactor 0.1')

    def _update_scaling(self):
        """Compute scale factor and letterbox offset for current window size."""
        win_w, win_h = self.window.get_size()
        scale_x = win_w / self.internal_width
        scale_y = win_h / self.internal_height
        self._scale = min(scale_x, scale_y)
        self._scaled_w = int(self.internal_width * self._scale)
        self._scaled_h = int(self.internal_height * self._scale)
        self._offset_x = (win_w - self._scaled_w) // 2
        self._offset_y = (win_h - self._scaled_h) // 2

    def get_mouse_pos(self):
        """Get mouse position translated to internal surface coordinates."""
        wx, wy = pygame.mouse.get_pos()
        return self._window_to_internal(wx, wy)

    def _window_to_internal(self, wx, wy):
        """Convert window coordinates to internal 1280x720 coordinates."""
        ix = (wx - self._offset_x) / self._scale
        iy = (wy - self._offset_y) / self._scale
        # Clamp to internal bounds
        ix = max(0, min(self.internal_width - 1, ix))
        iy = max(0, min(self.internal_height - 1, iy))
        return (int(ix), int(iy))

    def _translate_mouse_event(self, event):
        """Create a copy of a mouse event with translated coordinates."""
        if not hasattr(event, 'pos'):
            return event
        new_pos = self._window_to_internal(*event.pos)
        if event.type == pygame.MOUSEMOTION:
            return pygame.event.Event(event.type, pos=new_pos, rel=event.rel, buttons=event.buttons, touch=getattr(event, 'touch', False))
        elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            return pygame.event.Event(event.type, pos=new_pos, button=event.button, touch=getattr(event, 'touch', False))
        return event

    def flip_display(self):
        """Scale internal surface to window and flip. Use instead of pygame.display.flip()."""
        self.window.fill((0, 0, 0))
        scaled = pygame.transform.smoothscale(self.screen, (self._scaled_w, self._scaled_h))
        self.window.blit(scaled, (self._offset_x, self._offset_y))
        pygame.display.flip()

    def toggle_fullscreen(self):
        """Toggle between fullscreen and windowed mode."""
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN | pygame.RESIZABLE)
        else:
            self.window = pygame.display.set_mode((self.internal_width, self.internal_height), pygame.RESIZABLE)
        self._update_scaling()
        
    def _initialize_components(self):
        """Initialize all game components."""
        # Core components
        self.asset_manager = AssetManager()
        self.pitcher_manager = PitcherManager(self.screen, self.asset_manager)
        # Set game ref on all pitchers for count-aware location targeting
        for pitcher in self.pitcher_manager.pitchers.values():
            pitcher.set_game_ref(self)
        self.game_stats = GameStats()
        
        # Game systems
        self.batter = Batter(self.screen)
        self.batter.set_handedness("R")
        self.sound_manager = SoundManager(sound_dir="assets/sounds")
        self.field_renderer = FieldRenderer(self.screen)
        self.scoreKeeper = ScoreKeeper()
        self.batter_profile = BatterProfile()

        # GameDay mode management
        self.gameday_manager = None
        self.in_gameday_mode = False
        # One-shot hint set by resume_gameday_session() and consumed by
        # GameDayTransitionState.enter() to restore the saved phase without
        # re-simulating an already-played opponent half.
        self._resuming_gameday_phase = None

        # ABS challenge system
        self.challenge_manager = ChallengeManager()
        self.abs_overlay = ABSChallengeOverlay(self)
        self.pending_challenge = None
        # Per-pitch ABS verdict flags consumed by PitchSimulation.cleanup
        # to populate pitches.abs_challenged / abs_overturned.
        self._last_pitch_abs_challenged = False
        self._last_pitch_abs_overturned = False

        # Settings management (initialize early so other components can use it)
        self.settings_manager = SettingsManager()

        # Key binding system
        from key_binding_manager import KeyBindingManager
        self.key_binding_manager = KeyBindingManager(self.settings_manager)
        self.key_rebind_action = None  # Track current key rebinding

        self.hit_outcome_manager = HitOutcomeManager(self.scoreKeeper, self.sound_manager, self.settings_manager)
        self.ui_manager = UIManager(self.screen, (1280, 720), theme_path=get_path("assets/theme.json"))

        # Set the key binding manager reference in UI manager
        self.ui_manager.set_key_binding_manager(self.key_binding_manager)
        # Settings reference is needed for HUD-mode-aware button visibility.
        self.ui_manager.set_settings_manager(self.settings_manager)

        # Sync PitchViz animation timing with display FPS setting
        self.ui_manager.update_view_window_fps(self.settings_manager.get_display_fps())

        # Set callback for PitchViz window close button
        self.ui_manager.view_window.set_close_callback(self.exit_view_pitches)

        # Three HUDs: Legacy (full bottom bar), Broadcast (4 corners), Minimal (corner widget).
        self.scorebug = Scorebug(self)
        self.broadcast_hud = BroadcastHUD(self)
        self.minimal_hud = MinimalHUD(self)
        # Only legacy mode wants the field-rendered base diamond — broadcast
        # and minimal both display bases themselves.
        self.field_renderer.show_bases = (
            self.settings_manager.get_hud_mode() == "legacy"
        )

        # Random scenario generator
        self.random_scenario_generator = RandomScenarioGenerator()

        # Legacy compatibility and initial state variables (needed before state manager)
        self.ball = [0, 0, 4600]
        self.blitfunc = self.asset_manager.create_ball_renderer()
        self.fourseamballsize = 11

        # Load settings and initialize state variables
        self.umpsound = self.settings_manager.get_setting("umpire_sound")
        self.swing_started = 0
        self.speed = 3
        self.menu_state = 0

        # State management (must come after menu_state is initialized)
        self.state_manager = GameStateManager(self)
        self.state_manager.change_state('mode_select')
        self.current_gamemode = 0
        self.inning_ended = False
        self.pitches_display = []
        self.pitch_trajectories = []
        self.enhanced_pitch_records = []  # Enhanced pitch data for visualization
        self.last_pitch_information = []
        self.previous_mode_before_pitchviz = None  # Track mode before entering PitchViz

    def _setup_ui_callbacks(self):
        """Setup UI button callbacks."""
        # Pitcher selection callbacks
        self.ui_manager.register_button_callback('sale', lambda: self.enter_gamemode('Sale', 'sale'))
        self.ui_manager.register_button_callback('degrom', lambda: self.enter_gamemode('Degrom', 'degrom'))
        self.ui_manager.register_button_callback('sasaki', lambda: self.enter_gamemode('Sasaki', 'sasaki'))
        self.ui_manager.register_button_callback('yamamoto', lambda: self.enter_gamemode('Yamamoto', 'yamamoto'))
        self.ui_manager.register_button_callback('mcclanahan', lambda: self.enter_gamemode('Experimental', 'mcclanahan'))
        self.ui_manager.register_button_callback('random_scenario', lambda: self.enter_random_scenario())
        self.ui_manager.register_button_callback('gameday', lambda: self.enter_gameday_mode())

        # Mode selection callbacks
        self.ui_manager.register_button_callback('arcade_mode', lambda: self.enter_arcade_mode())
        self.ui_manager.register_button_callback('sandbox_mode', lambda: self.enter_sandbox_mode())
        self.ui_manager.register_button_callback('back_to_mode_select', lambda: self.return_to_mode_select())

        # Sandbox menu callbacks - pitcher selection (enters gameplay)
        self.ui_manager.register_button_callback('sandbox_menu_sale', lambda: self._enter_sandbox_gameplay('sale'))
        self.ui_manager.register_button_callback('sandbox_menu_degrom', lambda: self._enter_sandbox_gameplay('degrom'))
        self.ui_manager.register_button_callback('sandbox_menu_sasaki', lambda: self._enter_sandbox_gameplay('sasaki'))
        self.ui_manager.register_button_callback('sandbox_menu_yamamoto', lambda: self._enter_sandbox_gameplay('yamamoto'))
        self.ui_manager.register_button_callback('sandbox_menu_mcclanahan', lambda: self._enter_sandbox_gameplay('mcclanahan'))

        # Sandbox gameplay callbacks - pitcher switching
        self.ui_manager.register_button_callback('sandbox_pitcher_sale', lambda: self._sandbox_switch_pitcher('sale'))
        self.ui_manager.register_button_callback('sandbox_pitcher_degrom', lambda: self._sandbox_switch_pitcher('degrom'))
        self.ui_manager.register_button_callback('sandbox_pitcher_sasaki', lambda: self._sandbox_switch_pitcher('sasaki'))
        self.ui_manager.register_button_callback('sandbox_pitcher_yamamoto', lambda: self._sandbox_switch_pitcher('yamamoto'))
        self.ui_manager.register_button_callback('sandbox_pitcher_mcclanahan', lambda: self._sandbox_switch_pitcher('mcclanahan'))

        # Sandbox mode callbacks - pitch type selection
        self.ui_manager.register_button_callback('sandbox_pitch_1', lambda: self._sandbox_select_pitch(0))
        self.ui_manager.register_button_callback('sandbox_pitch_2', lambda: self._sandbox_select_pitch(1))
        self.ui_manager.register_button_callback('sandbox_pitch_3', lambda: self._sandbox_select_pitch(2))
        self.ui_manager.register_button_callback('sandbox_pitch_4', lambda: self._sandbox_select_pitch(3))
        self.ui_manager.register_button_callback('sandbox_pitch_5', lambda: self._sandbox_select_pitch(4))
        self.ui_manager.register_button_callback('sandbox_pitch_6', lambda: self._sandbox_select_pitch(5))

        # Sandbox mode - system buttons
        self.ui_manager.register_button_callback('sandbox_sound', lambda: self.toggle_ump_sound())
        self.ui_manager.register_button_callback('sandbox_exit', lambda: self.return_to_mode_select())

        # Navigation callbacks
        self.ui_manager.register_button_callback('main_menu', lambda: self.set_menu_state(0))
        self.ui_manager.register_button_callback('back_to_main_menu', lambda: self.set_menu_state(0))
        self.ui_manager.register_button_callback('gameday_main_menu', lambda: self.set_menu_state(0))
        self.ui_manager.register_button_callback('visualise', self.toggle_track)
        self.ui_manager.register_button_callback('return_to_game', lambda: self.exit_view_pitches())
        self.ui_manager.register_button_callback('view_pitches', self.toggle_view_pitches)
        self.ui_manager.register_button_callback('continue_to_summary', lambda: self.continue_to_summary())
        
        # Game control callbacks
        self.ui_manager.register_button_callback('strikezone', lambda: self.field_renderer.toggle_strikezone_mode())
        self.ui_manager.register_button_callback('toggle_ump_sound', lambda: self.toggle_ump_sound())
        self.ui_manager.register_button_callback('toggle_batter', lambda: self.batter.toggle_handedness())
        self.ui_manager.register_button_callback('scout', lambda: self.toggle_scouting_report())

        # Lap feature callbacks
        self.ui_manager.register_button_callback('lap_stats', lambda: self.create_lap())
        self.ui_manager.register_button_callback('view_laps', lambda: self.toggle_lap_log())

        # Settings menu callbacks
        self.ui_manager.register_button_callback('settings', lambda: self.enter_settings_menu())
        self.ui_manager.register_button_callback('back_to_main', lambda: self.exit_settings_menu())

        # Difficulty selection callbacks
        self.ui_manager.register_button_callback('difficulty_rookie', lambda: self.set_difficulty('rookie'))
        self.ui_manager.register_button_callback('difficulty_amateur', lambda: self.set_difficulty('amateur'))
        self.ui_manager.register_button_callback('difficulty_professional', lambda: self.set_difficulty('professional'))
        self.ui_manager.register_button_callback('difficulty_allstar', lambda: self.set_difficulty('all_star'))
        self.ui_manager.register_button_callback('difficulty_halloffame', lambda: self.set_difficulty('hall_of_fame'))

        # Settings toggle callbacks
        self.ui_manager.register_button_callback('toggle_ump_sound_settings', lambda: self.toggle_umpire_sound_setting())
        self.ui_manager.register_button_callback('toggle_strikezone_settings', lambda: self.toggle_strikezone_setting())
        self.ui_manager.register_button_callback('toggle_abs_settings', lambda: self.toggle_abs_setting())
        self.ui_manager.register_button_callback('toggle_hud_mode_settings', lambda: self.toggle_hud_mode())
        self.ui_manager.register_button_callback('reset_settings', lambda: self.reset_settings())

        # FPS settings callbacks
        self.ui_manager.register_button_callback('display_fps_setting', lambda: self.cycle_display_fps())
        self.ui_manager.register_button_callback('engine_fps_setting', lambda: self.cycle_engine_fps())

        # Key binding callbacks
        self.ui_manager.register_button_callback('key_bindings', lambda: self.enter_key_bindings_menu())
        self.ui_manager.register_button_callback('back_from_keybinds', lambda: self.exit_key_bindings_menu())
        self.ui_manager.register_button_callback('reset_keybinds', lambda: self.reset_key_bindings())

        # Individual key binding buttons
        from key_binding_manager import KeyAction
        self.ui_manager.register_button_callback('bind_toggle_ui', lambda: self.start_key_rebind(KeyAction.TOGGLE_UI))
        self.ui_manager.register_button_callback('bind_toggle_strikezone', lambda: self.start_key_rebind(KeyAction.TOGGLE_STRIKEZONE))
        self.ui_manager.register_button_callback('bind_toggle_sound', lambda: self.start_key_rebind(KeyAction.TOGGLE_SOUND))
        self.ui_manager.register_button_callback('bind_toggle_batter', lambda: self.start_key_rebind(KeyAction.TOGGLE_BATTER))
        self.ui_manager.register_button_callback('bind_quick_pitch', lambda: self.start_key_rebind(KeyAction.QUICK_PITCH))
        self.ui_manager.register_button_callback('bind_view_pitches', lambda: self.start_key_rebind(KeyAction.VIEW_PITCHES))
        self.ui_manager.register_button_callback('bind_main_menu', lambda: self.start_key_rebind(KeyAction.MAIN_MENU))
        self.ui_manager.register_button_callback('bind_toggle_track', lambda: self.start_key_rebind(KeyAction.TOGGLE_TRACK))
        self.ui_manager.register_button_callback('bind_challenge', lambda: self.start_key_rebind(KeyAction.CHALLENGE))

        # Setup key binding system callbacks
        self._setup_key_binding_callbacks()
        
    # Properties for backward compatibility
    @property
    def current_pitcher(self):
        return self.pitcher_manager.get_current_pitcher()
        
    @current_pitcher.setter
    def current_pitcher(self, pitcher):
        self.pitcher_manager.current_pitcher = pitcher
        
    @property
    def strikes(self):
        return self.game_stats.strikes
        
    @strikes.setter 
    def strikes(self, value):
        self.game_stats.strikes = value
        
    @property
    def balls(self):
        return self.game_stats.balls
        
    @balls.setter
    def balls(self, value):
        self.game_stats.balls = value
        
    @property
    def current_pitches(self):
        return self.game_stats.current_pitches
        
    @current_pitches.setter
    def current_pitches(self, value):
        self.game_stats.current_pitches = value
        
    @property
    def pitchnumber(self):
        return self.game_stats.pitchnumber
        
    @pitchnumber.setter
    def pitchnumber(self, value):
        self.game_stats.pitchnumber = value
        
    @property
    def currentballs(self):
        return self.game_stats.currentballs
        
    @currentballs.setter
    def currentballs(self, value):
        self.game_stats.currentballs = value
        
    @property
    def currentstrikes(self):
        return self.game_stats.currentstrikes
        
    @currentstrikes.setter
    def currentstrikes(self, value):
        self.game_stats.currentstrikes = value
        
    @property
    def currentouts(self):
        return self.game_stats.currentouts
        
    @currentouts.setter
    def currentouts(self, value):
        self.game_stats.currentouts = value
        
    @property
    def currentstrikeouts(self):
        return self.game_stats.currentstrikeouts
        
    @currentstrikeouts.setter
    def currentstrikeouts(self, value):
        self.game_stats.currentstrikeouts = value
        
    @property
    def currentwalks(self):
        return self.game_stats.currentwalks
        
    @currentwalks.setter
    def currentwalks(self, value):
        self.game_stats.currentwalks = value
        
    @property
    def homeruns_allowed(self):
        return self.game_stats.homeruns_allowed
        
    @homeruns_allowed.setter
    def homeruns_allowed(self, value):
        self.game_stats.homeruns_allowed = value
        
    @property
    def hits(self):
        return self.game_stats.hits
        
    @hits.setter
    def hits(self, value):
        self.game_stats.hits = value
        
    @property
    def last_pitch_type_thrown(self):
        return self.game_stats.last_pitch_type_thrown
        
    @last_pitch_type_thrown.setter
    def last_pitch_type_thrown(self, value):
        self.game_stats.last_pitch_type_thrown = value
        
    @property
    def first_pitch_thrown(self):
        return self.game_stats.first_pitch_thrown
        
    @first_pitch_thrown.setter
    def first_pitch_thrown(self, value):
        self.game_stats.first_pitch_thrown = value
        
    @property
    def current_state(self):
        return self.game_stats.current_state
        
    @current_state.setter
    def current_state(self, value):
        self.game_stats.current_state = value
        
    @property
    def pitch_chosen(self):
        return self.game_stats.pitch_chosen
        
    @pitch_chosen.setter
    def pitch_chosen(self, value):
        self.game_stats.pitch_chosen = value
        
    @property
    def outcome_value(self):
        return self.game_stats.outcome_value

    @property
    def pitch_history(self):
        return self.game_stats.pitch_history

    @pitch_history.setter
    def pitch_history(self, value):
        self.game_stats.pitch_history = value

    def enter_gamemode(self, gamemode_name: str, pitcher_name: str):
        """Enter a specific game mode with a pitcher."""
        self.menu_state = gamemode_name
        self.pitcher_manager.set_current_pitcher(pitcher_name)
        self.game_stats.reset_game_stats()
        self._load_batter_profile_for_current_bucket()
        self.challenge_manager.set_unlimited(False)
        self.challenge_manager.reset_all()
        self.inning_ended = False
        self.pitches_display = []
        self.pitch_trajectories = []
        self.enhanced_pitch_records = []
        self.scorebug.last_pitch_type = ""  # Reset last pitch display
        crosshair = create_pci_cursor()
        pygame.mouse.set_cursor(crosshair)
        # Begin a new game in the pitch DB so all pitches share a game_id.
        self._db_start_game("arcade", pitcher_name=pitcher_name)
        self.state_manager.handle_menu_state_change(gamemode_name)
        # Update scouting panel with new pitcher
        self.ui_manager.update_scouting_panel(self.current_pitcher)

    def toggle_scouting_report(self):
        """Toggle the scouting report panel visibility."""
        self.ui_manager.toggle_scouting_panel(self.current_pitcher)

    def create_lap(self):
        """Create a new lap from current batting stats."""
        if not self.field_renderer.has_stats_to_lap():
            self.ui_manager.show_banner("No stats to record!", typing_speed=0.02)
            return

        lap_entry = self.field_renderer.create_lap()
        ba = lap_entry.get('batting_average', 0)
        lap_num = lap_entry.get('lap_number', 0)
        self.ui_manager.show_banner(f"Lap {lap_num} saved! BA: {ba:.3f}", typing_speed=0.02)

    def toggle_lap_log(self):
        """Toggle the lap log panel visibility."""
        self.ui_manager.toggle_lap_log_panel(self.field_renderer)

    def enter_random_scenario(self):
        """Enter a random scenario game mode."""
        scenario = self.random_scenario_generator.generate_random_scenario()

        # Set the pitcher
        pitcher_name = scenario['pitcher']
        self.pitcher_manager.set_current_pitcher(pitcher_name)

        # Set up the game state with the scenario
        self.game_stats.reset_game_stats()
        self._load_batter_profile_for_current_bucket()
        self.challenge_manager.set_unlimited(False)
        self.challenge_manager.reset_all()
        self.game_stats.currentballs = scenario['balls']
        self.game_stats.currentstrikes = scenario['strikes']
        self.game_stats.currentouts = scenario['outs']
        
        # Set up runners on base
        self.scoreKeeper.reset()
        from helpers import Runner
        for base in scenario['runners']:
            runner = Runner(base)  # Create a runner starting at this base
            runner.base = base     # Make sure they're on the correct base
            self.scoreKeeper.runners.append(runner)
            self.scoreKeeper.basesfilled[base] = runner
            self.scoreKeeper.bases[base - 1] = 'yellow'
        
        # Set menu state and initialize
        self.menu_state = f"Random: {pitcher_name.title()}"
        self.inning_ended = False
        self.pitches_display = []
        self.scorebug.last_pitch_type = ""  # Reset last pitch display

        # Reset cursor (like in enter_gamemode)
        crosshair = create_pci_cursor()
        pygame.mouse.set_cursor(crosshair)

        # Random scenarios are part of arcade play — start a new arcade game.
        self._db_start_game("arcade", pitcher_name=pitcher_name)

        # Transition to gameplay state
        self.state_manager.change_state('gameplay')
        # Update scouting panel with new pitcher
        self.ui_manager.update_scouting_panel(self.current_pitcher)

    # ---------------- Pitch DB / batter profile helpers ----------------

    def _current_bucket_key(self):
        """Return the (game_mode, difficulty) tuple matching the current
        session, used for both batting_stats.json and the SQLite per-bucket
        batter profile.
        """
        if self.in_gameday_mode:
            mode = "gameday"
        elif self.menu_state == "sandbox_gameplay":
            mode = "sandbox"
        else:
            mode = "arcade"
        difficulty = self.settings_manager.get_difficulty().value
        return mode, difficulty

    def _db_start_game(self, game_mode, pitcher_name=None):
        """Open a games row in the pitch DB so all subsequent pitches share a game_id."""
        try:
            from data.pitch_database import PitchDatabaseService
            difficulty = self.settings_manager.get_difficulty().value
            PitchDatabaseService.get_instance().start_game(game_mode, difficulty, pitcher_name)
            # Steer the FieldRenderer to the matching aggregate bucket so
            # heatmap/triple-slash counters update the right partition.
            self.field_renderer.set_active_bucket(game_mode, difficulty)
        except Exception as e:
            print(f"[pitch_db] _db_start_game failed: {e}")

    def _db_end_game_if_open(self, player_score=None, opponent_score=None, result=None):
        """Close the active games row, if any. Safe to call from any transition."""
        try:
            from data.pitch_database import PitchDatabaseService
            svc = PitchDatabaseService.get_instance()
            if svc.current_game_id is not None:
                svc.end_game(player_score=player_score,
                             opponent_score=opponent_score,
                             result=result)
        except Exception as e:
            print(f"[pitch_db] _db_end_game_if_open failed: {e}")

    def _load_batter_profile_for_current_bucket(self):
        """Load the persisted BatterProfile for the active (mode, difficulty)
        bucket so AI exploitation doesn't carry across difficulties or modes.
        Falls back to a fresh profile if none is stored yet.
        """
        try:
            from data.pitch_database import PitchDatabaseService
            mode, difficulty = self._current_bucket_key()
            data = PitchDatabaseService.get_instance().load_batter_profile(mode, difficulty)
            if data is None:
                self.batter_profile.reset()
            else:
                self.batter_profile.from_dict(data)
        except Exception as e:
            print(f"[pitch_db] load_batter_profile failed: {e}; resetting profile")
            self.batter_profile.reset()

    def _save_batter_profile_for_current_bucket(self):
        """Persist the in-memory BatterProfile back to the pitch DB so it
        survives across launches (segregated by game_mode and difficulty).
        """
        try:
            from data.pitch_database import PitchDatabaseService
            mode, difficulty = self._current_bucket_key()
            PitchDatabaseService.get_instance().save_batter_profile(
                mode, difficulty, self.batter_profile.to_dict()
            )
        except Exception as e:
            print(f"[pitch_db] save_batter_profile failed: {e}")

    def enter_gameday_mode(self):
        """Enter GameDay mode - show the pitcher selection screen.

        The actual GameDayManager is constructed in start_gameday_with_starter
        once the user confirms their starter from the carousel.
        """
        self.in_gameday_mode = True
        self.gameday_manager = None
        self.menu_state = 'gameday'
        self.state_manager.change_state('gameday')

    def start_gameday_with_starter(self, starter_name: str):
        """Build the GameDayManager with the chosen starter and begin play."""
        from gameplay.gameday_manager import GameDayManager

        difficulty = self.settings_manager.get_difficulty().value
        self.gameday_manager = GameDayManager(
            player_name="Player",
            difficulty=difficulty,
            starter_name=starter_name,
        )
        self.in_gameday_mode = True

        # Install the chosen pitcher as current and attach fatigue tracking.
        self.pitcher_manager.set_current_pitcher(starter_name)
        self.current_pitcher = self.pitcher_manager.get_current_pitcher()
        self.current_pitcher.set_fatigue_stats(
            self.gameday_manager.get_active_pitcher_stats()
        )

        # Fresh per-game state.
        self.game_stats.reset_game_stats()
        self._load_batter_profile_for_current_bucket()
        self.scoreKeeper.reset()
        self.challenge_manager.set_unlimited(False)
        self.challenge_manager.reset_all()
        self.inning_ended = False
        # Starting fresh — drop any stale resume hint from a prior resume.
        self._resuming_gameday_phase = None

        # Begin a new GameDay record. pitcher_name is None at the game level
        # because the opponent uses a staff (starter + relievers).
        self._db_start_game("gameday", pitcher_name=None)

        self.menu_state = 'gameday'
        self.state_manager.change_state('gameday_transition')
        self.ui_manager.update_scouting_panel(self.current_pitcher)

    def resume_gameday_session(self, session_id: str):
        """Rebuild and resume a previously-saved in-progress GameDay game.

        Resumes at the half-inning boundary the session was saved at: the
        GameDayManager is reconstructed from its snapshot and the player is
        dropped back into the transition screen, which recomputes the phase.
        """
        from gameplay.gameday_manager import GameDayManager
        from data import gameday_sessions

        record = gameday_sessions.get_session(session_id)
        if not record or not record.get('state'):
            print(f"[gameday] resume failed: session {session_id} not found")
            return

        self.gameday_manager = GameDayManager.from_dict(record['state'])
        self.in_gameday_mode = True

        # Align the global difficulty with the resumed game so the batter-profile
        # bucket (load + save) and gameplay difficulty match what was saved.
        self.settings_manager.set_difficulty(self.gameday_manager.difficulty)

        # Install the active opponent pitcher and re-link fatigue tracking.
        self.pitcher_manager.set_current_pitcher(
            self.gameday_manager.current_pitcher_name)
        self.current_pitcher = self.pitcher_manager.get_current_pitcher()
        self.current_pitcher.set_fatigue_stats(
            self.gameday_manager.get_active_pitcher_stats()
        )

        # Fresh per-game side state (the manager itself carries score/innings).
        self.game_stats.reset_game_stats()
        self._load_batter_profile_for_current_bucket()
        self.scoreKeeper.reset()
        self.challenge_manager.set_unlimited(False)
        self.challenge_manager.reset_all()
        self.inning_ended = False

        # Continued pitches log under a fresh DB game row (FK'd into history).
        self._db_start_game("gameday", pitcher_name=None)

        # One-shot resume hint consumed by GameDayTransitionState.enter() so it
        # restores the saved phase and skips re-simulating an already-played half.
        self._resuming_gameday_phase = record.get('phase')

        self.menu_state = 'gameday'
        self.state_manager.change_state('gameday_transition')
        self.ui_manager.update_scouting_panel(self.current_pitcher)

    def autosave_gameday_session(self, phase: str):
        """Persist the in-progress GameDay game so it can be resumed later.

        Called at each half-inning boundary (GameDayTransitionState). Best-effort:
        a save failure must never interrupt play.
        """
        if not (self.in_gameday_mode and self.gameday_manager is not None):
            return
        try:
            from data import gameday_sessions
            record = gameday_sessions.build_record(self.gameday_manager, phase)
            gameday_sessions.upsert_session(record)
        except Exception as e:
            print(f"[gameday] autosave_gameday_session failed: {e}")

    def clear_gameday_session(self, session_id: str):
        """Remove a saved in-progress session (on completion or abandonment)."""
        if not session_id:
            return
        try:
            from data import gameday_sessions
            gameday_sessions.remove_session(session_id)
        except Exception as e:
            print(f"[gameday] clear_gameday_session failed: {e}")

    def enter_gameday_history(self):
        """Show the paginated list of completed GameDay games."""
        self.state_manager.change_state('gameday_history')

    def enter_gameday_resume(self):
        """Show the list of resumable in-progress GameDay games."""
        self.state_manager.change_state('gameday_resume')

    def enter_arcade_mode(self):
        """Enter Arcade mode (pitcher selection menu)."""
        self._db_end_game_if_open()
        self.in_gameday_mode = False
        self.gameday_manager = None
        self.current_gamemode = 0
        self.menu_state = 0
        self.state_manager.change_state('menu')

    def enter_sandbox_mode(self):
        """Enter Sandbox mode - show pitcher selection menu."""
        self._db_end_game_if_open()
        self.in_gameday_mode = False
        self.gameday_manager = None
        self.menu_state = 'sandbox_menu'
        self.current_gamemode = 0
        self.state_manager.change_state('sandbox_menu')

    def _enter_sandbox_gameplay(self, pitcher_name: str):
        """Enter sandbox gameplay with the selected pitcher."""
        self.pitcher_manager.set_current_pitcher(pitcher_name)

        # Reset game stats for fresh start
        self.game_stats.reset_game_stats()
        self._load_batter_profile_for_current_bucket()
        self.scoreKeeper.reset()
        self.challenge_manager.reset_all()
        # Sandbox is for exploration — challenges are unlimited there.
        self.challenge_manager.set_unlimited(True)

        # Clear pitch data
        self.pitch_trajectories = []
        self.enhanced_pitch_records = []
        self.pitches_display = []

        # Set cursor
        crosshair = create_pci_cursor()
        pygame.mouse.set_cursor(crosshair)

        # Begin a new sandbox session in the pitch DB.
        self._db_start_game("sandbox", pitcher_name=pitcher_name)

        self.menu_state = 'sandbox_gameplay'
        self.current_gamemode = 'sandbox_gameplay'
        self.state_manager.change_state('sandbox_gameplay')

    def _sandbox_switch_pitcher(self, pitcher_name: str):
        """Switch pitcher in sandbox mode."""
        if self.state_manager.is_current_state('sandbox_gameplay'):
            state = self.state_manager.get_current_state()
            state.switch_pitcher(pitcher_name)

    def _sandbox_select_pitch(self, pitch_index: int):
        """Toggle pitch type in sandbox mode by button index."""
        if self.state_manager.is_current_state('sandbox_gameplay'):
            state = self.state_manager.get_current_state()
            pitch_names = self.current_pitcher.get_pitch_names()
            if pitch_index < len(pitch_names):
                state.toggle_pitch(pitch_names[pitch_index])

    def return_to_mode_select(self):
        """Return to main mode selection menu."""
        self.pitcher_manager.save_all_ai()
        self._save_batter_profile_for_current_bucket()
        self._db_end_game_if_open()
        self.menu_state = 'mode_select'
        self.current_gamemode = 0
        self.inning_ended = False
        self.in_gameday_mode = False
        self.gameday_manager = None
        self.previous_mode_before_pitchviz = None
        self.game_stats.reset_game_stats()
        # Clear fatigue stats if a pitcher has them
        if hasattr(self.current_pitcher, 'clear_fatigue_stats'):
            self.current_pitcher.clear_fatigue_stats()
        self.state_manager.change_state('mode_select')

    def set_menu_state(self, state):
        """Set the current menu state."""
        self.menu_state = state
        if state == 0:  # Returning to main menu
            self.pitcher_manager.save_all_ai()
            self._save_batter_profile_for_current_bucket()
            self._db_end_game_if_open()
            self.current_gamemode = 0
            self.inning_ended = False
            self.in_gameday_mode = False
            self.gameday_manager = None
            self.previous_mode_before_pitchviz = None
            # Reset game stats so a fresh game can be started
            self.game_stats.reset_game_stats()
            # Clear fatigue stats if a pitcher has them
            if hasattr(self.current_pitcher, 'clear_fatigue_stats'):
                self.current_pitcher.clear_fatigue_stats()
        self.state_manager.handle_menu_state_change(state)
        
    def exit_view_pitches(self):
        """Exit the view pitches mode."""
        self.ui_manager.hide_view_window()

        # Use stored previous mode to determine where to return
        previous_mode = self.previous_mode_before_pitchviz

        # Return to the appropriate state based on inning status and mode.
        # Gate on `inning_ended` alone — a walk-off ends the half-inning
        # without reaching 3 outs, and we must not let the user fall back
        # into gameplay from view-pitches in that case.
        if self.inning_ended:
            self.ui_manager.set_button_visibility('inning_end')
            self.menu_state = 'inning_end'
            self.state_manager.change_state('inning_end')
        elif previous_mode == 'sandbox_gameplay' or self.current_gamemode == 'sandbox_gameplay':
            # Return to sandbox gameplay mode
            self.ui_manager.set_button_visibility('sandbox_gameplay')
            self.menu_state = 'sandbox_gameplay'
            self.state_manager.change_state('sandbox_gameplay')
            # Re-update pitch buttons after returning
            state = self.state_manager.get_current_state()
            if hasattr(state, '_update_pitch_buttons'):
                state._update_pitch_buttons()
        else:
            self.ui_manager.set_button_visibility('in_game')
            self.menu_state = self.current_gamemode
            self.state_manager.change_state('gameplay')

        # Clear the stored previous mode
        self.previous_mode_before_pitchviz = None
        
    def enter_view_pitches(self):
        """Enter the view pitches mode."""
        # Store current mode before switching to view_pitches
        self.previous_mode_before_pitchviz = self.menu_state

        # Use appropriate visibility state based on current mode
        if self.menu_state == 'sandbox_gameplay' or self.current_gamemode == 'sandbox_gameplay':
            self.ui_manager.set_button_visibility('sandbox_view_pitches')
        else:
            self.ui_manager.set_button_visibility('view_pitches')

        self.ui_manager.update_pitch_info(self.pitch_trajectories, self.last_pitch_information)
        self.ui_manager.show_view_window()
        self.menu_state = 'view_pitches'
        self.state_manager.change_state('view_pitches')

    def toggle_view_pitches(self):
        """Toggle between view pitches mode and gameplay."""
        if (hasattr(self, 'state_manager') and
            self.state_manager.current_state and
            self.state_manager.current_state.__class__.__name__ == 'ViewPitchesState'):
            # Currently in view pitches mode, return to game
            self.exit_view_pitches()
        else:
            # Not in view pitches mode, enter it
            self.enter_view_pitches()

    def toggle_track(self):
        """Toggle between track/visualization mode and gameplay."""
        if (hasattr(self, 'state_manager') and
            self.state_manager.current_state and
            self.state_manager.current_state.__class__.__name__ == 'VisualizationState'):
            # Currently in visualization mode, return to game
            self.exit_view_pitches()  # Uses same exit logic
        else:
            # Not in visualization mode, enter it
            self.set_menu_state('visualise')
        
    def toggle_ump_sound(self):
        """Toggle umpire sound effects."""
        self.umpsound = not self.umpsound

    def enter_settings_menu(self):
        """Enter the settings menu."""
        self.menu_state = 'settings'
        self.ui_manager.set_button_visibility('settings', force_show=True)
        self.ui_manager.update_settings_button_states(self.settings_manager)
        self.ui_manager.show_settings_info(self.settings_manager)
        self.state_manager.change_state('menu')

    def exit_settings_menu(self):
        """Exit settings menu and return to the mode-select screen."""
        self.menu_state = 'mode_select'
        self.ui_manager.hide_banner()
        self.state_manager.change_state('mode_select')

    def set_difficulty(self, difficulty_level):
        """Set the difficulty level."""
        self.settings_manager.set_difficulty(difficulty_level)
        # Steer aggregates to the new (mode, difficulty) bucket so the
        # heatmap and triple-slash track the right partition immediately.
        mode, difficulty = self._current_bucket_key()
        self.field_renderer.set_active_bucket(mode, difficulty)
        self.ui_manager.update_settings_button_states(self.settings_manager)
        self.ui_manager.show_settings_info(self.settings_manager)

    def toggle_umpire_sound_setting(self):
        """Toggle umpire sound setting."""
        current = self.settings_manager.get_setting("umpire_sound")
        self.settings_manager.set_setting("umpire_sound", not current)
        # Also update the legacy umpsound variable
        self.umpsound = self.settings_manager.get_setting("umpire_sound")
        self.ui_manager.update_settings_button_states(self.settings_manager)

    def toggle_strikezone_setting(self):
        """Toggle strikezone display setting."""
        current = self.settings_manager.get_setting("show_strikezone")
        self.settings_manager.set_setting("show_strikezone", not current)
        self.ui_manager.update_settings_button_states(self.settings_manager)

    def toggle_abs_setting(self):
        """Toggle MLB-style ABS ball/strike challenge system on or off."""
        current = self.settings_manager.get_setting("abs_enabled")
        self.settings_manager.set_setting("abs_enabled", not current)
        # If disabling mid-state, drop any in-flight challenge prompt so the
        # gameplay overlay stops drawing it immediately.
        if not self.settings_manager.get_setting("abs_enabled"):
            self.pending_challenge = None
        self.ui_manager.update_settings_button_states(self.settings_manager)

    def _draw_active_hud(self, surface):
        """Dispatch to the HUD selected by the current setting. Only renders
        on the gameplay-style states where the legacy scorebug also showed."""
        if self.state_manager.current_state_name not in (
            'gameplay', 'sandbox_gameplay', 'inning_end'
        ):
            return
        mode = self.settings_manager.get_hud_mode()
        if mode == "minimal":
            self.minimal_hud.draw(surface)
        elif mode == "broadcast":
            self.broadcast_hud.draw(surface)
        else:
            self.scorebug.draw(surface)

    def toggle_hud_mode(self):
        """Cycle Legacy → Broadcast → Minimal → Legacy."""
        new_mode = self.settings_manager.cycle_hud_mode()
        self.ui_manager.update_settings_button_states(self.settings_manager)
        # Big field-drawn base diamond is redundant in broadcast/minimal —
        # both draw their own bases.
        self.field_renderer.show_bases = (new_mode == "legacy")
        # Re-apply visibility for the current state so side buttons show/hide
        # immediately without waiting for the next state transition.
        state_name = self.state_manager.current_state_name
        visibility_map = {
            'gameplay': 'in_game',
            'sandbox_gameplay': 'sandbox_gameplay',
            'view_pitches': 'view_pitches',
            'visualization': 'visualise',
            'inning_end': 'inning_end',
        }
        if state_name in visibility_map:
            self.ui_manager.set_button_visibility(visibility_map[state_name])

    def reset_settings(self):
        """Reset all settings to defaults."""
        self.settings_manager.reset_to_defaults()
        # Update legacy variables
        self.umpsound = self.settings_manager.get_setting("umpire_sound")
        self.ui_manager.update_settings_button_states(self.settings_manager)
        self.ui_manager.show_settings_info(self.settings_manager)

    def cycle_display_fps(self):
        """Cycle through display FPS options."""
        self.settings_manager.cycle_display_fps()
        self.ui_manager.update_settings_button_states(self.settings_manager)
        # Update PitchViz animation timing to match new display FPS
        self.ui_manager.update_view_window_fps(self.settings_manager.get_display_fps())

    def cycle_engine_fps(self):
        """Cycle through engine FPS options."""
        self.settings_manager.cycle_engine_fps()
        self.ui_manager.update_settings_button_states(self.settings_manager)

    def _setup_key_binding_callbacks(self):
        """Setup key binding system callbacks for various actions."""
        from key_binding_manager import KeyAction

        # Register callbacks for key actions
        self.key_binding_manager.register_callback(KeyAction.TOGGLE_UI, self.toggle_ui_visibility)
        self.key_binding_manager.register_callback(KeyAction.TOGGLE_STRIKEZONE, lambda: self.field_renderer.toggle_strikezone_mode())
        self.key_binding_manager.register_callback(KeyAction.TOGGLE_SOUND, self.toggle_umpire_sound_setting)
        self.key_binding_manager.register_callback(KeyAction.TOGGLE_BATTER, lambda: self.batter.toggle_handedness())
        self.key_binding_manager.register_callback(KeyAction.QUICK_PITCH, self.quick_pitch)
        self.key_binding_manager.register_callback(KeyAction.VIEW_PITCHES, self.toggle_view_pitches)
        self.key_binding_manager.register_callback(KeyAction.MAIN_MENU, lambda: self.set_menu_state(0))
        self.key_binding_manager.register_callback(KeyAction.TOGGLE_TRACK, self.toggle_track)
        self.key_binding_manager.register_callback(KeyAction.CHALLENGE, self.request_abs_challenge)
        self.key_binding_manager.register_callback(KeyAction.TOGGLE_HUD_MODE, self.toggle_hud_mode)

    def enter_key_bindings_menu(self):
        """Enter key bindings configuration menu."""
        self.menu_state = 'key_bindings'
        self.ui_manager.set_button_visibility('key_bindings', force_show=True)
        self.ui_manager.update_key_binding_buttons(self.key_binding_manager)
        self.ui_manager.show_key_bindings_info()

    def exit_key_bindings_menu(self):
        """Exit key bindings menu back to settings."""
        self.menu_state = 'settings'
        self.ui_manager.set_button_visibility('settings', force_show=True)
        self.ui_manager.update_settings_button_states(self.settings_manager)
        self.ui_manager.show_settings_info(self.settings_manager)
        self.key_rebind_action = None  # Cancel any active rebind

    def reset_key_bindings(self):
        """Reset all key bindings to defaults."""
        self.key_binding_manager.reset_to_defaults()
        self.ui_manager.update_key_binding_buttons(self.key_binding_manager)

    def start_key_rebind(self, action):
        """Start rebinding a key for the given action."""
        self.key_rebind_action = action
        # Update the button to show it's waiting for input
        from key_binding_manager import KeyAction
        action_name = self.key_binding_manager.get_action_name(action)
        button_mapping = {
            KeyAction.TOGGLE_UI: 'bind_toggle_ui',
            KeyAction.TOGGLE_STRIKEZONE: 'bind_toggle_strikezone',
            KeyAction.TOGGLE_SOUND: 'bind_toggle_sound',
            KeyAction.TOGGLE_BATTER: 'bind_toggle_batter',
            KeyAction.QUICK_PITCH: 'bind_quick_pitch',
            KeyAction.VIEW_PITCHES: 'bind_view_pitches',
            KeyAction.MAIN_MENU: 'bind_main_menu',
            KeyAction.TOGGLE_TRACK: 'bind_toggle_track',
            KeyAction.CHALLENGE: 'bind_challenge',
        }
        if action in button_mapping:
            button_key = button_mapping[action]
            self.ui_manager.buttons[button_key].set_text(f"{action_name}: Press any key...")

    def toggle_ui_visibility(self):
        """Toggle UI visibility using key binding."""
        current_visibility = self.key_binding_manager.is_ui_visible()
        new_visibility = not current_visibility
        self.key_binding_manager.set_ui_visibility(new_visibility)

        # Toggle every HUD's visibility in sync with the global UI toggle.
        self.scorebug.visible = new_visibility
        self.broadcast_hud.visible = new_visibility
        self.minimal_hud.visible = new_visibility

        if new_visibility:
            # Determine current state
            current_state = 'main_menu'  # default
            if hasattr(self, 'state_manager') and self.state_manager.current_state:
                if self.state_manager.current_state.__class__.__name__ == 'GameplayState':
                    current_state = 'in_game'
                elif self.state_manager.current_state.__class__.__name__ == 'SandboxGameplayState':
                    current_state = 'sandbox_gameplay'
                elif self.state_manager.current_state.__class__.__name__ == 'MenuState':
                    if hasattr(self, 'menu_state'):
                        if self.menu_state == 'settings':
                            current_state = 'settings'
                        elif self.menu_state == 'key_bindings':
                            current_state = 'key_bindings'
                        else:
                            current_state = 'main_menu'
                elif self.state_manager.current_state.__class__.__name__ == 'SummaryState':
                    current_state = 'summary'
                elif self.state_manager.current_state.__class__.__name__ == 'ViewPitchesState':
                    current_state = 'view_pitches'
                elif self.state_manager.current_state.__class__.__name__ == 'VisualizationState':
                    current_state = 'visualise'
                elif self.state_manager.current_state.__class__.__name__ == 'InningEndState':
                    current_state = 'inning_end'

            # Show UI based on current state
            self.ui_manager.set_ui_visibility(True, current_state)
        else:
            # Hide all UI
            self.ui_manager.set_ui_visibility(False)

    def quick_pitch(self):
        """Quick pitch action via key binding (Arcade/GameDay + Sandbox)."""
        if not hasattr(self, 'state_manager'):
            return
        state = self.state_manager.current_state
        if state is None or state.__class__.__name__ not in (
                'GameplayState', 'SandboxGameplayState'):
            return
        if getattr(state, 'pitch_simulation', None) is None:
            state._initiate_pitch()

    def complete_key_rebind(self, new_key):
        """Complete the key rebinding process."""
        if hasattr(self, 'key_rebind_action') and self.key_rebind_action is not None:
            # Check if key is already used
            if self.key_binding_manager.is_key_available(new_key, exclude_action=self.key_rebind_action):
                # Bind the new key
                self.key_binding_manager.bind_key(self.key_rebind_action, new_key)
                # Update the UI buttons
                self.ui_manager.update_key_binding_buttons(self.key_binding_manager)
            else:
                # Key is already in use, show error
                from key_binding_manager import KeyAction
                key_name = self.key_binding_manager.get_key_name(new_key)
                # Find which action uses this key
                for action in KeyAction:
                    if self.key_binding_manager.get_key_for_action(action) == new_key:
                        used_by = self.key_binding_manager.get_action_name(action)
                        break
                else:
                    used_by = "Unknown"

                # Show error message in banner
                error_msg = f"Key '{key_name}' is already used by {used_by}"
                self.ui_manager.show_banner(error_msg, typing_speed=0.01)

                # Restore the button text
                self.ui_manager.update_key_binding_buttons(self.key_binding_manager)

            # Clear rebind state
            self.key_rebind_action = None

    def _display_pitch_results(self, outcome: str, pitchtype: str, speed_mph: float):
        """Display pitch results on the scorebug."""
        self.scorebug.set_last_pitch(pitchtype, speed_mph, outcome)
        # Refresh scouting panel stats after each pitch
        self.ui_manager.refresh_scouting_panel()

    # ------------------------------------------------------------------
    # ABS challenge system
    # ------------------------------------------------------------------

    def snapshot_for_abs(self):
        """Capture mutable state needed to roll back an umpire's call."""
        import copy
        snap = {
            'game_stats': copy.deepcopy(self.game_stats),
            'scoreKeeper': copy.deepcopy(self.scoreKeeper),
            'inning_ended': self.inning_ended,
            'last_pitch_information': copy.deepcopy(self.last_pitch_information),
            'menu_state': self.menu_state,
            'state_name': self.state_manager.current_state_name,
        }
        if self.gameday_manager is not None:
            snap['gameday'] = {
                'player_score': self.gameday_manager.player_score,
                'opponent_score': self.gameday_manager.opponent_score,
                '_current_half_runs': self.gameday_manager._current_half_runs,
                'current_outs': self.gameday_manager.current_outs,
                '_consecutive_hits': self.gameday_manager._consecutive_hits,
                'player_consecutive_hits': self.gameday_manager.player_consecutive_hits,
                'event_log_len': len(self.gameday_manager.event_log),
                'is_walkoff': self.gameday_manager.is_walkoff,
                'game_over': self.gameday_manager.game_over,
                'opponent_pitcher_stats': copy.deepcopy(self.gameday_manager.opponent_pitcher_stats),
                'player_pitcher_stats': copy.deepcopy(self.gameday_manager.player_pitcher_stats),
                'player_inning_scores': list(self.gameday_manager.player_inning_scores),
                'opponent_inning_scores': list(self.gameday_manager.opponent_inning_scores),
            }
        snap['field_renderer'] = {
            'total_pitches': getattr(self.field_renderer, 'total_pitches', 0),
            'total_at_bats': getattr(self.field_renderer, 'total_at_bats', 0),
            'total_walks': getattr(self.field_renderer, 'total_walks', 0),
            'hit_records_len': len(getattr(self.field_renderer, 'hit_records', [])),
        }
        return snap

    def restore_for_abs(self, snap):
        """Roll the game back to the snapshot and cancel any scheduled side effects."""
        import copy
        src = snap['game_stats']
        for attr in ('strikes', 'balls', 'currentballs', 'currentstrikes',
                     'currentouts', 'currentstrikeouts', 'currentwalks',
                     'homeruns_allowed', 'hits', 'pitchnumber',
                     'last_pitch_type_thrown', 'first_pitch_thrown',
                     'pitch_chosen', 'current_state', 'current_pitches'):
            if hasattr(src, attr):
                setattr(self.game_stats, attr, getattr(src, attr))
        if hasattr(src, 'pitch_history'):
            self.game_stats.pitch_history = list(src.pitch_history)

        # Re-clone the saved ScoreKeeper as a single object so that the
        # references between `runners` and `basesfilled` stay intact —
        # walk_event() mutates Runner objects via basesfilled and expects them
        # to be the same instances stored in `runners`.
        sk_clone = copy.deepcopy(snap['scoreKeeper'])
        self.scoreKeeper.bases = sk_clone.bases
        self.scoreKeeper.runners = sk_clone.runners
        self.scoreKeeper.basesfilled = sk_clone.basesfilled
        self.scoreKeeper.score = sk_clone.score

        self.inning_ended = snap['inning_ended']
        self.last_pitch_information = list(snap['last_pitch_information'])

        # If the call moved us to a different state (e.g. inning_end after a
        # strike-3 walkoff), walk back to where we were when the pitch ended.
        if snap.get('state_name') and self.state_manager.current_state_name != snap['state_name']:
            self.menu_state = snap.get('menu_state', self.menu_state)
            self.state_manager.change_state(snap['state_name'])

        if 'gameday' in snap and self.gameday_manager is not None:
            gd = snap['gameday']
            self.gameday_manager.player_score = gd['player_score']
            self.gameday_manager.opponent_score = gd['opponent_score']
            self.gameday_manager._current_half_runs = gd['_current_half_runs']
            self.gameday_manager.current_outs = gd['current_outs']
            self.gameday_manager._consecutive_hits = gd['_consecutive_hits']
            self.gameday_manager.player_consecutive_hits = gd['player_consecutive_hits']
            self.gameday_manager.event_log = self.gameday_manager.event_log[:gd['event_log_len']]
            self.gameday_manager.is_walkoff = gd['is_walkoff']
            self.gameday_manager.game_over = gd['game_over']
            self.gameday_manager.opponent_pitcher_stats = copy.deepcopy(gd['opponent_pitcher_stats'])
            self.gameday_manager.player_pitcher_stats = copy.deepcopy(gd['player_pitcher_stats'])
            self.gameday_manager.player_inning_scores = list(gd['player_inning_scores'])
            self.gameday_manager.opponent_inning_scores = list(gd['opponent_inning_scores'])

        fr = snap['field_renderer']
        if hasattr(self.field_renderer, 'total_pitches'):
            self.field_renderer.total_pitches = fr['total_pitches']
        if hasattr(self.field_renderer, 'total_at_bats'):
            self.field_renderer.total_at_bats = fr['total_at_bats']
        if hasattr(self.field_renderer, 'total_walks'):
            self.field_renderer.total_walks = fr['total_walks']
        if hasattr(self.field_renderer, 'hit_records'):
            self.field_renderer.hit_records = self.field_renderer.hit_records[:fr['hit_records_len']]

        # Cancel scheduled side effects from the original (now-undone) call.
        if hasattr(self.ui_manager, '_pending_banner'):
            self.ui_manager._pending_banner = None
        self.ui_manager.hide_banner()
        if hasattr(self.sound_manager, 'pending_sounds'):
            self.sound_manager.pending_sounds = []

    def dispatch_ball_call(self, pitchtype, speed_mph, ball_y, *, with_sound=True):
        """Apply a ball call against the current game state. Mirrors
        PitchSimulation._handle_ball_call but without sim-local fields, so
        the ABS reversal can use it."""
        self.balls += 1
        if with_sound and self.umpsound:
            if ball_y > 560:
                self.sound_manager.schedule_sound('ball_low', delay=450)
            else:
                self.sound_manager.schedule_sound('ball', delay=450)
        self.currentballs += 1
        self.pitchnumber += 1

        if self.currentballs == 4:
            self.currentwalks += 1
            self.field_renderer.record_walk()
            score_before = self.scoreKeeper.get_score() if self.in_gameday_mode else 0
            self.scoreKeeper.update_walk_event()
            runs_scored = self.scoreKeeper.get_score() - score_before
            self._display_pitch_results("WALK", pitchtype, speed_mph)
            self.ui_manager.schedule_banner("WALK", delay=450)
            if self.in_gameday_mode and self.gameday_manager is not None:
                self.gameday_manager.record_player_at_bat(
                    'WALK', runs_scored=runs_scored, pitches_thrown=self.pitchnumber
                )
                self._abs_check_walkoff()
            self.currentstrikes = 0
            self.currentballs = 0
            self.pitchnumber = 0
        else:
            self._display_pitch_results("BALL", pitchtype, speed_mph)

    def dispatch_strike_call(self, pitchtype, speed_mph, *, with_sound=True,
                              was_swung=False):
        """Apply a strike call. Mirrors PitchSimulation._handle_strike_call."""
        self.strikes += 1
        self.pitchnumber += 1
        self.currentstrikes += 1

        if with_sound and not was_swung and self.umpsound:
            if self.currentstrikes == 3:
                self.sound_manager.schedule_sound('strike3', delay=450)
            else:
                self.sound_manager.schedule_sound('strike', delay=450)

        label = "SWINGING STRIKE" if was_swung else "CALLED STRIKE"

        if self.currentstrikes == 3:
            self.currentstrikeouts += 1
            self.currentouts += 1
            self.field_renderer.record_at_bat()
            self._display_pitch_results(label, pitchtype, speed_mph)
            self.ui_manager.schedule_banner("STRIKEOUT", delay=450)
            if self.in_gameday_mode and self.gameday_manager is not None:
                self.gameday_manager.record_player_at_bat(
                    'STRIKEOUT', runs_scored=0, pitches_thrown=self.pitchnumber
                )
            self.pitchnumber = 0
            self.currentstrikes = 0
            self.currentballs = 0
        else:
            self._display_pitch_results(label, pitchtype, speed_mph)

    def _abs_check_walkoff(self):
        """Trigger walkoff handling after an ABS-applied walk in gameday."""
        if (self.in_gameday_mode and self.gameday_manager is not None
                and self.gameday_manager.check_walkoff()):
            # player_score / _current_half_runs are already up-to-date via
            # record_player_at_bat. Just commit the partial inning to the box
            # score before transitioning.
            self.gameday_manager.player_inning_scores.append(
                self.gameday_manager._current_half_runs
            )
            self.ui_manager.show_banner("WALK-OFF WIN!", typing_speed=0.05)
            self.inning_ended = True
            self.menu_state = 'inning_end'
            self.state_manager.change_state('inning_end')

    def open_abs_challenge_window(self, *, ball_xy, original_call, truth_strike,
                                   trajectory, pitchtype, speed_mph, snapshot):
        """Called by PitchSimulation right after the call commits. Stores the
        pre-commit snapshot so the call can be fully reversed within the
        challenge window (including terminal walks / strikeouts)."""
        # Respect the user setting — if ABS is off, never open a window.
        if not self.settings_manager.get_setting("abs_enabled"):
            self.pending_challenge = None
            return

        if self.in_gameday_mode and self.gameday_manager is not None:
            side = "away" if self.gameday_manager.is_top_inning else "home"
        else:
            side = "home"

        # No window if the side has no challenges left.
        if not self.challenge_manager.can_challenge(side):
            self.pending_challenge = None
            return

        self.pending_challenge = {
            'opened_at': pygame.time.get_ticks(),
            'ball_xy': ball_xy,
            'original_call': original_call,
            'truth_strike': bool(truth_strike),
            'trajectory': trajectory,
            'pitchtype': pitchtype,
            'speed_mph': speed_mph,
            'side': side,
            'snapshot': snapshot,
        }

    def _challenge_window_active(self):
        from config import CHALLENGE_WINDOW_MS
        if not self.pending_challenge:
            return False
        elapsed = pygame.time.get_ticks() - self.pending_challenge['opened_at']
        return elapsed <= CHALLENGE_WINDOW_MS

    def challenge_seconds_remaining(self):
        from config import CHALLENGE_WINDOW_MS
        if not self.pending_challenge:
            return 0.0
        elapsed = pygame.time.get_ticks() - self.pending_challenge['opened_at']
        return max(0.0, (CHALLENGE_WINDOW_MS - elapsed) / 1000.0)

    def clear_pending_challenge(self):
        """Called when the next pitch starts (window closes)."""
        self.pending_challenge = None
        # Reset per-pitch ABS challenge result flags so cleanup of pitch N+1
        # doesn't inherit pitch N's verdict.
        self._last_pitch_abs_challenged = False
        self._last_pitch_abs_overturned = False

    def request_abs_challenge(self):
        """Triggered by the CHALLENGE key. Runs the overlay synchronously."""
        if not self._challenge_window_active():
            return
        pc = self.pending_challenge
        side = pc['side']
        if not self.challenge_manager.can_challenge(side):
            self.pending_challenge = None
            return

        # Project the post-call count for the banner.
        snap_stats = pc['snapshot']['game_stats']
        pre_b = snap_stats.currentballs
        pre_s = snap_stats.currentstrikes
        truth_call = "strike" if pc['truth_strike'] else "ball"
        overturned = (truth_call != pc['original_call'])
        if overturned:
            new_balls = pre_b + (0 if pc['truth_strike'] else 1)
            new_strikes = pre_s + (1 if pc['truth_strike'] else 0)
            if new_strikes >= 3:
                post_count = "K"  # strikeout
            elif new_balls >= 4:
                post_count = "BB"  # walk
            else:
                post_count = f"{new_balls}-{new_strikes}"
        else:
            post_count = f"{self.currentballs}-{self.currentstrikes}"

        self.abs_overlay.trigger(
            ball_xy=pc['ball_xy'],
            original_call=pc['original_call'],
            truth_strike=pc['truth_strike'],
            trajectory=pc['trajectory'],
            pre_balls=pre_b,
            pre_strikes=pre_s,
            pitch_label=f"{pc['pitchtype']}  {pc['speed_mph']:.0f} MPH",
            post_count_label=post_count,
        )
        self._run_abs_overlay_loop()

        # Consume challenge (retain on success).
        self.challenge_manager.consume(side, successful=overturned)

        if overturned:
            self._reverse_last_call()

        # Stash for the active pitch's DB record. Read from
        # PitchSimulation.cleanup via self.game._last_pitch_abs_*.
        self._last_pitch_abs_challenged = True
        self._last_pitch_abs_overturned = bool(overturned)

        self.pending_challenge = None

    def _run_abs_overlay_loop(self):
        """Synchronous render loop for the overlay. Mirrors PitchSimulation.run.
        Drains input during the animation; once the overlay enters its
        wait-for-dismiss state, SPACE/ENTER (or mouse click) closes it."""
        clock = self.clock
        screen = self.screen
        while self.abs_overlay.is_active():
            time_delta = clock.tick_busy_loop(60) / 1000.0
            screen.fill("black")
            if self.state_manager.current_state is not None:
                self.state_manager.current_state.render(screen)
            self._draw_active_hud(screen)
            self.abs_overlay.update(int(time_delta * 1000))
            self.abs_overlay.render(screen)
            self.ui_manager.draw()
            self.flip_display()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    # Close the overlay AND re-post the quit so the main loop
                    # actually exits — otherwise the window can't be closed
                    # while a challenge overlay is on screen.
                    self.abs_overlay.dismiss()
                    pygame.event.post(event)
                elif event.type in (pygame.VIDEORESIZE, pygame.WINDOWRESIZED):
                    self._update_scaling()
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    self.toggle_fullscreen()
                elif (event.type == pygame.KEYDOWN
                      and self.abs_overlay.is_waiting_for_dismiss()
                      and event.key in (pygame.K_SPACE, pygame.K_RETURN,
                                        pygame.K_KP_ENTER, pygame.K_ESCAPE)):
                    self.abs_overlay.dismiss()
                elif (event.type == pygame.MOUSEBUTTONDOWN
                      and self.abs_overlay.is_waiting_for_dismiss()):
                    self.abs_overlay.dismiss()

    def _reverse_last_call(self):
        """Reverse the umpire's call after a successful challenge.
        Restores the pre-commit snapshot, then re-dispatches the opposite call
        silently (no umpire SFX, per ABS UX)."""
        pc = self.pending_challenge
        if not pc or 'snapshot' not in pc:
            return

        new_call = "strike" if pc['truth_strike'] else "ball"
        if new_call == pc['original_call']:
            return

        # Roll the world back to just before the umpire's call.
        self.restore_for_abs(pc['snapshot'])

        # Apply the geometric truth as the new call. Silent — the user wants
        # no umpire voice line to play on overturn.
        if new_call == "ball":
            self.dispatch_ball_call(
                pc['pitchtype'], pc['speed_mph'], pc['ball_xy'][1], with_sound=False
            )
        else:
            self.dispatch_strike_call(
                pc['pitchtype'], pc['speed_mph'], with_sound=False, was_swung=False
            )

        # Recolor the on-field trail dot to match the new call.
        if self.last_pitch_information:
            new_color = (227, 75, 80) if new_call == "strike" else (75, 227, 148)
            last = self.last_pitch_information[-1]
            for entry in self.last_pitch_information:
                if entry[0] == last[0] and entry[1] == last[1]:
                    entry[3] = new_color

    def check_inning_end(self):
        """Check if the inning should end."""
        if self.currentouts == 3 and not self.inning_ended:
            self.inning_ended = True

            # In gameday mode, player_score and _current_half_runs are kept in
            # sync incrementally by record_player_at_bat. The transition state
            # is responsible for calling end_half_inning().

            # Show inning end screen with continue button (both modes)
            self.menu_state = 'inning_end'
            self.state_manager.change_state('inning_end')
            
    def continue_to_summary(self):
        """Continue from inning end to summary or gameday transition."""
        if self.in_gameday_mode:
            self.menu_state = 'gameday_transition'
            self.state_manager.change_state('gameday_transition')
        else:
            self.menu_state = 100
            self.state_manager.change_state('summary')
            
    def run(self):
        """Main game loop."""
        running = True
        while running:
            display_fps = self.settings_manager.get_display_fps()
            time_delta = self.clock.tick(display_fps) / 1000.0
            
            # Process events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    break

                # Handle window resize
                if event.type in (pygame.VIDEORESIZE, pygame.WINDOWRESIZED):
                    self._update_scaling()
                    continue

                # F11 fullscreen toggle
                if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    self.toggle_fullscreen()
                    continue

                # Translate mouse events to internal coordinates
                if hasattr(event, 'pos'):
                    event = self._translate_mouse_event(event)

                # Handle key binding events (only in gameplay-related states)
                _hotkey_states = {'gameplay', 'sandbox_gameplay', 'view_pitches',
                                  'visualization', 'inning_end'}
                if event.type == pygame.KEYDOWN:
                    # Check if we're waiting for a key rebind
                    if hasattr(self, 'key_rebind_action') and self.key_rebind_action is not None:
                        self.complete_key_rebind(event.key)
                        continue
                    elif self.state_manager.current_state_name in _hotkey_states:
                        # If a bound hotkey consumed the key (it may also have
                        # changed state), don't also forward the same keypress
                        # to the now-current state's handle_event.
                        if self.key_binding_manager.handle_key_down(event.key):
                            continue
                elif event.type == pygame.KEYUP:
                    if self.state_manager.current_state_name in _hotkey_states:
                        self.key_binding_manager.handle_key_up(event.key)

                # Let state manager handle events
                if not self.state_manager.handle_event(event):
                    running = False
                    break
                    
            # Check for inning end only when in gameplay state (not sandbox mode - sandbox has unlimited outs)
            if self.state_manager.is_current_state('gameplay'):
                self.check_inning_end()
            
            # Update current state
            self.state_manager.update(time_delta)
            self.ui_manager.update(time_delta)
            
            # Render current state to internal surface
            self.screen.fill("black")
            self.state_manager.render(self.screen)
            # Draw whichever HUD the user has selected.
            self._draw_active_hud(self.screen)
            self.ui_manager.draw()

            # Scale and flip
            self.flip_display()
            
        # Cleanup
        self.cleanup()
        
    def cleanup(self):
        """Clean up resources."""
        print("Game shutting down...")

        # Save pitcher AI learning progress
        if hasattr(self, 'pitcher_manager'):
            print("Saving pitcher AI models...")
            self.pitcher_manager.save_all_ai()

        # Save final batting statistics before exit
        if hasattr(self, 'field_renderer'):
            print("Saving final batting statistics...")
            self.field_renderer.save_data()

def main():
    """Main entry point."""
    game = Game()
    game.run()
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
