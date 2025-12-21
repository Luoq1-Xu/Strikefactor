# StrikeFactor : A baseball batting simulator
import pygame
import sys
import os
import pandas as pd
import pickle

# Import pitcher classes
from pitchers.Mcclanahan import Mcclanahan
from pitchers.Sale import Sale
from pitchers.Degrom import Degrom
from pitchers.Yamamoto import Yamamoto
from pitchers.Sasaki import Sasaki
from ai.AI_2 import ERAI

# Import game components
from ui.components import create_pci_cursor
from engine.sound_manager import SoundManager
from gameplay.batter import Batter
from config import get_path, resource_path
from gameplay.field_renderer import FieldRenderer
from gameplay.hit_outcome_manager import HitOutcomeManager
from ui.ui_manager import UIManager
from helpers import ScoreKeeper, PitchDataManager
from gameplay.game_state_manager import GameStateManager
from gameplay.random_scenario import RandomScenarioGenerator
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
            max_distance = 4600
            min_size = 3
            max_size = 11

            dist = ball_pos[2] / max_distance
            size = min_size + (max_size - min_size) * (1 - dist)
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
        
        # Attach AI to each pitcher
        for pitcher in self.pitchers.values():
            ai = ERAI(pitcher.get_pitch_names())
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

class GameStats:
    """Manages game statistics and state."""
    
    def __init__(self):
        self.reset_game_stats()
        self.outcome_value = {
            'strike': 0.5, 'ball': -0.25, 'foul': 0.3, 'strikeout': 2, 'walk': -1,
            'SINGLE': -1.5, 'DOUBLE': -2, 'TRIPLE': -2.5, 'HOME RUN': -3,
            'FLYOUT': 1.5, 'GROUNDOUT': 1.5
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
        self.current_state = (0, 0, 0, 0, 0, 0)
        self.pitch_chosen = None

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
        """Setup the game display."""
        self.screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        icon = pygame.image.load(get_path("assets/images/icon.png")).convert_alpha()
        pygame.display.set_icon(icon)
        pygame.display.set_caption('StrikeFactor 0.1')
        
    def _initialize_components(self):
        """Initialize all game components."""
        # Core components
        self.asset_manager = AssetManager()
        self.pitcher_manager = PitcherManager(self.screen, self.asset_manager)
        self.game_stats = GameStats()
        
        # Game systems
        self.batter = Batter(self.screen)
        self.batter.set_handedness("R")
        self.sound_manager = SoundManager(sound_dir="assets/sounds")
        self.field_renderer = FieldRenderer(self.screen)
        self.scoreKeeper = ScoreKeeper()
        self.pitchDataManager = PitchDataManager()

        # GameDay mode management
        self.gameday_manager = None
        self.in_gameday_mode = False

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

        # Random scenario generator
        self.random_scenario_generator = RandomScenarioGenerator()

        # Legacy compatibility and initial state variables (needed before state manager)
        self.ball = [0, 0, 4600]
        self.blitfunc = self.asset_manager.create_ball_renderer()
        self.records = pd.DataFrame()
        self.fourseamballsize = 11

        # Load settings and initialize state variables
        self.umpsound = self.settings_manager.get_setting("umpire_sound")
        self.swing_started = 0
        self.speed = 3
        self.menu_state = 0

        # State management (must come after menu_state is initialized)
        self.state_manager = GameStateManager(self)
        self.state_manager.change_state('menu')
        self.just_refreshed = 0
        self.current_gamemode = 0
        self.inning_ended = False
        self.pitches_display = []
        self.pitch_trajectories = []
        self.last_pitch_information = []
        
        # Load AI model
        self.ai_model = pickle.load(open(get_path("ai/ai_umpire.pkl"), "rb"))
        
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

        # Navigation callbacks
        self.ui_manager.register_button_callback('main_menu', lambda: self.set_menu_state(0))
        self.ui_manager.register_button_callback('back_to_main_menu', lambda: self.set_menu_state(0))
        self.ui_manager.register_button_callback('visualise', lambda: self.set_menu_state('visualise'))
        self.ui_manager.register_button_callback('return_to_game', lambda: self.exit_view_pitches())
        self.ui_manager.register_button_callback('view_pitches', lambda: self.enter_view_pitches())
        self.ui_manager.register_button_callback('continue_to_summary', lambda: self.continue_to_summary())
        
        # Game control callbacks
        self.ui_manager.register_button_callback('strikezone', lambda: self.field_renderer.toggle_strikezone_mode())
        self.ui_manager.register_button_callback('toggle_ump_sound', lambda: self.toggle_ump_sound())
        self.ui_manager.register_button_callback('toggle_batter', lambda: self.batter.toggle_handedness())

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
        self.ui_manager.register_button_callback('reset_settings', lambda: self.reset_settings())

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
        
    def enter_gamemode(self, gamemode_name: str, pitcher_name: str):
        """Enter a specific game mode with a pitcher."""
        self.menu_state = gamemode_name
        self.pitcher_manager.set_current_pitcher(pitcher_name)
        self.game_stats.reset_game_stats()
        self.inning_ended = False
        self.just_refreshed = 1
        self.pitches_display = []
        crosshair = create_pci_cursor()
        pygame.mouse.set_cursor(crosshair)
        self.state_manager.handle_menu_state_change(gamemode_name)
        
    def enter_random_scenario(self):
        """Enter a random scenario game mode."""
        scenario = self.random_scenario_generator.generate_random_scenario()
        
        # Set the pitcher
        pitcher_name = scenario['pitcher']
        self.pitcher_manager.set_current_pitcher(pitcher_name)
        
        # Set up the game state with the scenario
        self.game_stats.reset_game_stats()
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
        self.just_refreshed = 1
        self.pitches_display = []

        # Reset cursor (like in enter_gamemode)
        crosshair = create_pci_cursor()
        pygame.mouse.set_cursor(crosshair)

        # Transition to gameplay state
        self.state_manager.change_state('gameplay')

    def enter_gameday_mode(self):
        """Enter GameDay mode - a full 9-inning simulated game."""
        from gameplay.gameday_manager import GameDayManager

        # Initialize gameday manager and set flag
        self.gameday_manager = GameDayManager(player_name="Player")
        self.in_gameday_mode = True

        # Set starting pitcher (Yamamoto)
        self.pitcher_manager.set_current_pitcher('yamamoto')
        self.current_pitcher = self.pitcher_manager.get_current_pitcher()

        # Reset game stats for fresh start
        self.game_stats.reset_game_stats()
        self.scoreKeeper.reset()

        self.menu_state = 'gameday'
        self.state_manager.change_state('gameday')
        
    def set_menu_state(self, state):
        """Set the current menu state."""
        self.menu_state = state
        if state == 0:  # Returning to main menu
            self.inning_ended = False
            # Reset game stats so a fresh game can be started
            self.game_stats.reset_game_stats()
        self.state_manager.handle_menu_state_change(state)
        
    def exit_view_pitches(self):
        """Exit the view pitches mode."""
        self.ui_manager.hide_view_window()
        # Return to the appropriate state based on inning status
        if self.currentouts == 3 and self.inning_ended:
            if self.in_gameday_mode:
                self.ui_manager.set_button_visibility('gameday_transition')
                self.menu_state = 'gameday_transition'
                self.state_manager.change_state('gameday_transition')
            else:
                self.ui_manager.set_button_visibility('inning_end')
                self.menu_state = 'inning_end'
                self.state_manager.change_state('inning_end')
        else:
            self.ui_manager.set_button_visibility('in_game')
            self.menu_state = self.current_gamemode
            self.state_manager.change_state('gameplay')
        
    def enter_view_pitches(self):
        """Enter the view pitches mode."""
        self.ui_manager.set_button_visibility('view_pitches')
        self.ui_manager.update_pitch_info(self.pitch_trajectories, self.last_pitch_information)
        self.ui_manager.show_view_window()
        self.menu_state = 'view_pitches'
        self.state_manager.change_state('view_pitches')
        
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
        """Exit settings menu and return to main menu."""
        self.menu_state = 0
        self.ui_manager.set_button_visibility('main_menu')
        self.ui_manager.hide_banner()
        self.state_manager.change_state('menu')

    def set_difficulty(self, difficulty_level):
        """Set the difficulty level."""
        self.settings_manager.set_difficulty(difficulty_level)
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

    def reset_settings(self):
        """Reset all settings to defaults."""
        self.settings_manager.reset_to_defaults()
        # Update legacy variables
        self.umpsound = self.settings_manager.get_setting("umpire_sound")
        self.ui_manager.update_settings_button_states(self.settings_manager)
        self.ui_manager.show_settings_info(self.settings_manager)

    def _setup_key_binding_callbacks(self):
        """Setup key binding system callbacks for various actions."""
        from key_binding_manager import KeyAction

        # Register callbacks for key actions
        self.key_binding_manager.register_callback(KeyAction.TOGGLE_UI, self.toggle_ui_visibility)
        self.key_binding_manager.register_callback(KeyAction.TOGGLE_STRIKEZONE, lambda: self.field_renderer.toggle_strikezone_mode())
        self.key_binding_manager.register_callback(KeyAction.TOGGLE_SOUND, self.toggle_umpire_sound_setting)
        self.key_binding_manager.register_callback(KeyAction.TOGGLE_BATTER, lambda: self.batter.toggle_handedness())
        self.key_binding_manager.register_callback(KeyAction.QUICK_PITCH, self.quick_pitch)
        self.key_binding_manager.register_callback(KeyAction.VIEW_PITCHES, self.enter_view_pitches)
        self.key_binding_manager.register_callback(KeyAction.MAIN_MENU, lambda: self.set_menu_state(0))

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
            KeyAction.MAIN_MENU: 'bind_main_menu'
        }
        if action in button_mapping:
            button_key = button_mapping[action]
            self.ui_manager.buttons[button_key].set_text(f"{action_name}: Press any key...")

    def toggle_ui_visibility(self):
        """Toggle UI visibility using key binding."""
        current_visibility = self.key_binding_manager.is_ui_visible()
        new_visibility = not current_visibility
        self.key_binding_manager.set_ui_visibility(new_visibility)

        if new_visibility:
            # Determine current state
            current_state = 'main_menu'  # default
            if hasattr(self, 'state_manager') and self.state_manager.current_state:
                if self.state_manager.current_state.__class__.__name__ == 'GameplayState':
                    current_state = 'in_game'
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
        """Quick pitch action via key binding."""
        # Only work if we're in gameplay state and can pitch
        if (hasattr(self, 'state_manager') and
            self.state_manager.current_state and
            self.state_manager.current_state.__class__.__name__ == 'GameplayState'):
            # Trigger pitch if ready
            if hasattr(self.state_manager.current_state, 'ready_to_pitch') and self.state_manager.current_state.ready_to_pitch:
                self.state_manager.current_state.start_pitch()

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


    def _display_pitch_results(self, outcome: str, pitchtype: str):
        """Display pitch results on the UI."""
        pitch_result_string = (
            f"<font size=5>PITCH {self.pitchnumber}: {pitchtype}<br>{outcome}<br>"
            f"COUNT IS {self.currentballs} - {self.currentstrikes}</font>"
        )
        game_status_result_string = (
            f"<font size=5>CURRENT OUTS : {self.currentouts}<br>"
            f"STRIKEOUTS : {self.currentstrikeouts}<br>WALKS : {self.currentwalks}<br>"
            f"HITS : {self.hits}<br>RUNS SCORED: {self.scoreKeeper.get_score()}</font>"
        )
        self.ui_manager.clear_pitch_result()
        self.ui_manager.update_pitch_result(pitch_result_string)
        self.ui_manager.update_scoreboard(game_status_result_string)
        
    def check_inning_end(self):
        """Check if the inning should end."""
        if self.currentouts == 3 and not self.inning_ended:
            self.inning_ended = True

            # Check if in gameday mode
            if self.in_gameday_mode:
                # Update player's score in gameday manager (add to cumulative score)
                self.gameday_manager.player_score += self.scoreKeeper.get_score()

                # DON'T call end_half_inning() here - let the transition state handle it
                # This ensures the state machine sees the correct inning state

                # Transition to gameday transition state
                self.menu_state = 'gameday_transition'
                self.state_manager.change_state('gameday_transition')
            else:
                # Normal mode - go to inning end
                self.menu_state = 'inning_end'
                self.state_manager.change_state('inning_end')
            
    def continue_to_summary(self):
        """Continue from inning end to summary state."""
        self.menu_state = 100
        self.state_manager.change_state('summary')
            
    def run(self):
        """Main game loop."""
        running = True
        while running:
            time_delta = self.clock.tick(60) / 1000.0
            
            # Process events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    break

                # Handle key binding events
                if event.type == pygame.KEYDOWN:
                    # Check if we're waiting for a key rebind
                    if hasattr(self, 'key_rebind_action') and self.key_rebind_action is not None:
                        self.complete_key_rebind(event.key)
                    else:
                        # Normal key handling
                        self.key_binding_manager.handle_key_down(event.key)
                elif event.type == pygame.KEYUP:
                    self.key_binding_manager.handle_key_up(event.key)

                # Let state manager handle events
                if not self.state_manager.handle_event(event):
                    running = False
                    break
                    
            # Check for inning end only when in gameplay state
            if self.state_manager.is_current_state('gameplay'):
                self.check_inning_end()
            
            # Update current state
            self.state_manager.update(time_delta)
            self.ui_manager.update(time_delta)
            
            # Render current state
            self.screen.fill("black")
            self.state_manager.render(self.screen)
            self.ui_manager.draw()
            
            pygame.display.flip()
            
        # Cleanup
        self.cleanup()
        
    def cleanup(self):
        """Clean up resources."""
        print("Game shutting down...")
        
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