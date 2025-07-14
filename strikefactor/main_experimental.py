import pygame
import pygame_gui
from engine.game import GameEngine
from gameplay.state_machine import MainMenuState, GameplayState, SummaryState
from engine.sound_manager import SoundManager
from ui.components import create_ui_manager
from config import SCREEN_WIDTH, SCREEN_HEIGHT

def main():
    pygame.mixer.pre_init(44100, 16, 2, 4096)
    pygame.init()
    
    # Create game engine
    engine = GameEngine()
    
    # Create UI manager
    ui_manager = create_ui_manager((SCREEN_WIDTH, SCREEN_HEIGHT))
    
    # Create sound manager
    sound_mgr = SoundManager()
    
    # Create game states
    main_menu = MainMenuState(engine, ui_manager, sound_mgr)
    gameplay = GameplayState(engine, ui_manager, sound_mgr)
    summary = SummaryState(engine, ui_manager, sound_mgr)
    
    # Add states to engine
    engine.add_state("menu", main_menu)
    engine.add_state("play", gameplay)
    engine.add_state("summary", summary)
    
    # Set initial state
    engine.change_state("menu")
    
    # Run the game
    engine.run()

if __name__ == "__main__":
    main()