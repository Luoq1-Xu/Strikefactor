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
            'SINGLE': -1.5, 'DOUBLE': -2, 'TRIPLE': -2.5, 'HOME RUN': -3
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
        self.hit_outcome_manager = HitOutcomeManager(self.scoreKeeper, self.sound_manager)
        self.ui_manager = UIManager(self.screen, (1280, 720), theme_path=get_path("assets/theme.json"))
        
        # Random scenario generator
        self.random_scenario_generator = RandomScenarioGenerator()
        
        # State management
        self.state_manager = GameStateManager(self)
        self.state_manager.change_state('menu')
        
        # Legacy compatibility
        self.ball = [0, 0, 4600]
        self.blitfunc = self.asset_manager.create_ball_renderer()
        self.records = pd.DataFrame()
        self.fourseamballsize = 11
        self.umpsound = True
        self.swing_started = 0
        self.speed = 3
        self.menu_state = 0
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
        
        # Show scenario description
        description = self.random_scenario_generator.get_scenario_description(scenario)
        self.ui_manager.show_banner(description, typing_speed=0.05)
        
        crosshair = create_pci_cursor()
        pygame.mouse.set_cursor(crosshair)
        self.state_manager.handle_menu_state_change(self.menu_state)
        
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
        

def main():
    """Main entry point."""
    game = Game()
    game.run()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()