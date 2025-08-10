import pygame
import pygame_gui
import json
from helpers import StatSwing
from config import get_path, resource_path


class UIManager:
    def __init__(self, screen, screen_size, theme_path=None):
        self.screen = screen
        self.manager = self._create_ui_manager(screen_size, theme_path)
        self.font = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 40)
        self.big_font = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 70)
        self.button_callbacks = {}
        self._create_ui_elements()

    def register_button_callback(self, button_name, callback):
        """
        Registers a callback function for a button click event.

        :param button_name: The name of the button to register the callback for.
        :param callback: The function to call when the button is clicked.
        """
        if button_name in self.buttons:
            self.button_callbacks[button_name] = callback
        else:
            raise ValueError(f"Button '{button_name}' does not exist.")

    def _create_ui_manager(self, screen_size, theme_path=None):
        """Creates and configures the pygame_gui.UIManager."""
        theme_file = get_path(theme_path or 'assets/theme.json')
        with open(theme_file, 'r') as f:
            theme_data = json.load(f)
        
        # Update font paths in the theme
        dynamic_font_path = resource_path(get_path('ui/font/8bitoperator_jve.ttf'))
        if "label" in theme_data and "font" in theme_data["label"]:
            theme_data["label"]["font"]["regular_path"] = dynamic_font_path
        if "button" in theme_data and "font" in theme_data["button"]:
            theme_data["button"]["font"]["regular_path"] = dynamic_font_path

        manager = pygame_gui.UIManager(screen_size, theme_path=theme_data)
        manager.preload_fonts([{'name': 'noto_sans', 'point_size': 18, 'style': 'regular'},
                            {'name': 'noto_sans', 'point_size': 18, 'style': 'bold'}])
        return manager
    
    def _create_game_buttons(self, manager):
        """Creates and returns a dictionary of in-game UI buttons."""
        buttons = {
            'strikezone': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((0, 100), (200, 100)),
                text='STRIKEZONE', manager=manager),
            'pitch': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((0, 0), (200, 100)),
                text='PITCH', manager=manager),
            'main_menu': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((0, 620), (200, 100)),
                text='MAIN MENU', manager=manager),
            'toggle_ump_sound': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((0, 200), (200, 100)),
                text='TOGGLEUMP', manager=manager),
            'view_pitches': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((0, 300), (200, 100)),
                text='VIEW PITCHES', manager=manager),
            'return_to_game': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((0, 300), (200, 100)),
                text='RETURN', manager=manager),
            'toggle_batter': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((0, 400), (200, 100)),
                text='BATTER', manager=manager),
            'visualise': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((0, 500), (200, 100)),
                text='VISUALISE', manager=manager),

            # Pitcher selection buttons for main  menu
            'sale': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 500), (190, 50)),
                text='Chris Sale', manager=manager),
            'degrom': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 600), (190, 50)),
                text='Jacob deGrom', manager=manager),
            'sasaki': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 500), (190, 50)),
                text='Roki Sasaki', manager=manager),
            'yamamoto': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 600), (190, 50)),
                text='Y. Yamamoto', manager=manager),
            'mcclanahan': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((800, 500), (190, 50)),
                text='S. Mcclanahan', manager=manager),

            # Random scenario button
            'random_scenario': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((500, 400), (280, 50)),
                text='Random Scenario', manager=manager),

            # Button for summary screen
            'back_to_main_menu': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((540, 530), (200, 50)),
                text='MAIN MENU', manager=manager),
                
            # Button for inning end screen
            'continue_to_summary': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((540, 630), (200, 50)),
                text='CONTINUE', manager=manager)
        }
        return buttons

    def _create_ui_elements(self):
        """
        Initializes all UI elements for the game.
        """

        # pygame_gui elements
        self.buttons = self._create_game_buttons(self.manager)
        self.container = pygame_gui.core.UIContainer(
            relative_rect=pygame.Rect((0, 0), self.screen.get_size()),
            manager=self.manager
        )
        self.banner = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect((340, 0), (600, 100)),
            manager=self.manager,
            text=""
        )
        self.scoreboard = pygame_gui.elements.UITextBox(
            html_text="",
            relative_rect=pygame.Rect((1000, 50), (250, 200)),
            manager=self.manager
        )
        self.pitch_result = pygame_gui.elements.UITextBox(
            html_text="",
            relative_rect=pygame.Rect((1000, 250), (250, 200)),
            manager=self.manager
        )
        self.view_window = StatSwing((25, 25), self.manager, [], [])
        self.banner.hide()
        self.view_window.hide()
        self.scoreboard.hide()
        self.pitch_result.hide()

        # Hide all buttons initially
        for button in self.buttons.values():
            button.hide() 

    def process_events(self, event):
        """Processes events for the UI manager."""
        self.manager.process_events(event)
        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            for key, button in self.buttons.items():
                if event.ui_element == button and key in self.button_callbacks:
                    # Call the registered callback for the button
                    self.button_callbacks[key]()
                    break

    def update_scoreboard(self, text, typing_speed=0.0075):
        """Updates the scoreboard with new text and a typing effect."""
        self.scoreboard.show()
        self.scoreboard.set_text(text)
        self.scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': typing_speed})

    def update_pitch_result(self, text, typing_speed=0.0085):
        """Updates the pitch result box with new text and a typing effect."""
        self.pitch_result.show()
        self.pitch_result.set_text(text)
        self.pitch_result.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': typing_speed})

    def clear_pitch_result(self):
        """Clears the pitch result and scoreboard."""
        self.pitch_result.set_text("")
        self.scoreboard.set_text("")

    def show_banner(self, text, typing_speed=0.1):
        """Shows the banner with the given text and a typing effect."""
        self.banner.set_text(text)
        self.banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': typing_speed})
        self.banner.show()

    def update(self, time_delta):
        """Updates the UI manager and all UI elements."""
        self.manager.update(time_delta)

    def draw(self):
        """Draws the UI manager and all UI elements to the screen."""
        self.manager.draw_ui(self.screen)

    def create_scoreboard(self, results):
        """Creates and returns a new scoreboard text box."""
        return pygame_gui.elements.UITextBox(
            html_text=results,
            relative_rect=pygame.Rect((1000, 50), (250, 200)),
            manager=self.manager
        )

    def update_container(self, textbox, scoreboard):
        """Updates the container with new textbox and scoreboard."""
        self.container.clear()
        self.container.add_element(textbox)
        self.container.add_element(scoreboard)

    def update_pitch_info(self, pitch_trajectories, last_pitch_info):
        """Updates pitch information in the view window."""
        self.view_window.update_pitch_info(pitch_trajectories, last_pitch_info)

    def show_view_window(self):
        """Shows the pitch view window."""
        self.view_window.show()
        
    def hide_view_window(self):
        """Hides the pitch view window."""
        self.view_window.hide()

    def hide_banner(self):
        self.banner.hide()

    def set_button_visibility(self, state):
        """Show or hide buttons based on game state ('in_game', 'pitching', 'menu')."""

        # Hide all buttons initially
        for button in self.buttons.values():
            button.hide()

        if state == 'in_game':
            self.buttons['strikezone'].show()
            self.buttons['main_menu'].show()
            self.buttons['toggle_ump_sound'].show()
            self.buttons['view_pitches'].show()
            self.buttons['toggle_batter'].show()
            self.buttons['visualise'].show()
            self.buttons['pitch'].show()
            self.scoreboard.show()
            self.pitch_result.show()
        elif state == 'pitching':
            # All buttons are hidden during the pitch animation
            pass
        elif state == 'view_pitches':
            self.buttons['return_to_game'].show()
            self.buttons['main_menu'].show()
            self.buttons['strikezone'].show()
        elif state == 'main_menu':
            self.buttons['sale'].show()
            self.buttons['degrom'].show()
            self.buttons['sasaki'].show()
            self.buttons['yamamoto'].show()
            self.buttons['mcclanahan'].show()
            self.buttons['random_scenario'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == "visualise":
            self.buttons['return_to_game'].show()
            self.buttons['main_menu'].show()
            self.buttons['strikezone'].show()
        elif state == 'summary':
            self.buttons['back_to_main_menu'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'inning_end':
            self.buttons['continue_to_summary'].show()
            self.buttons['visualise'].show()
            self.buttons['view_pitches'].show()
            self.buttons['strikezone'].show()
            self.buttons['main_menu'].show()
            self.scoreboard.show()
            self.pitch_result.show()

    def draw_typing_effect(self, message, counter, speed, position, use_big_font=False):
        """Draws text with a typing effect at the given position."""
        font = self.big_font if use_big_font else self.font
        snip = font.render(message[0:counter//speed], True, 'white')
        self.screen.blit(snip, position)
        
    def draw_completed_message(self, message, position, use_big_font=False):
        """Draws a completed message at the given position."""
        font = self.big_font if use_big_font else self.font
        text = font.render(message, True, 'white')
        self.screen.blit(text, position)