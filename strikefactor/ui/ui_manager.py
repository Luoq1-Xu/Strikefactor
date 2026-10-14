import json

import pygame
import pygame_gui

from strikefactor.config import get_path
from strikefactor.ui.banner import OutcomeBanner


class UIManager:
    def __init__(self, screen, screen_size, theme_path=None):
        self.screen = screen
        self.manager = self._create_ui_manager(screen_size, theme_path)
        self.small_font = pygame.font.Font(get_path("ui/font/8bitoperator_jve.ttf"), 28)
        self.font = pygame.font.Font(get_path("ui/font/8bitoperator_jve.ttf"), 48)  # +20% from 40
        self.big_font = pygame.font.Font(get_path("ui/font/8bitoperator_jve.ttf"), 84)  # +20% from 70
        self.button_callbacks = {}
        self.key_binding_manager = None  # Will be set after initialization
        self._create_ui_elements()

    def set_key_binding_manager(self, key_binding_manager):
        """Set the key binding manager reference for UI visibility control."""
        self.key_binding_manager = key_binding_manager

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
        dynamic_font_path = get_path('ui/font/8bitoperator_jve.ttf')
        for key, section in theme_data.items():
            if isinstance(section, dict) and "font" in section:
                if section["font"].get("name") == "8bitoperator_jve":
                    section["font"]["regular_path"] = dynamic_font_path

        manager = pygame_gui.UIManager(screen_size, theme_path=theme_data)
        manager.preload_fonts([{'name': 'noto_sans', 'point_size': 18, 'style': 'regular'},
                            {'name': 'noto_sans', 'point_size': 18, 'style': 'bold'}])
        return manager
    
    def _create_game_buttons(self, manager):
        """No screen has a widget any more: each draws and handles its own
        buttons through ui/widgets.py. What is left of this class goes with
        pygame_gui itself."""
        return {}

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
        self.banner = OutcomeBanner(self.screen)

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

    # The banner is drawn by ui/banner.py. These forward to it so the callers
    # that speak to `game.ui_manager` keep working while the widgets go.
    def show_banner(self, text, typing_speed=0.1):
        """Shows the banner with the given text and a typing effect."""
        self.banner.show_banner(text, typing_speed)

    def schedule_banner(self, text, delay=450, typing_speed=0.1):
        """Schedule a banner to show after a delay (in ms), to sync with umpire call."""
        self.banner.schedule_banner(text, delay, typing_speed)

    @property
    def _pending_banner(self):
        return self.banner._pending_banner

    @_pending_banner.setter
    def _pending_banner(self, value):
        self.banner._pending_banner = value

    def update(self, time_delta):
        """Updates the UI manager and all UI elements."""
        self.banner.update(time_delta)
        self.manager.update(time_delta)

    def draw(self):
        """Draws the UI manager and all UI elements to the screen."""
        self.manager.draw_ui(self.screen)
        self.banner.draw()

    def hide_banner(self):
        self.banner.hide_banner()

    def set_visibility_state(self, state):
        """Alias for set_button_visibility for clearer state-based visibility."""
        self.set_button_visibility(state)

    def set_button_visibility(self, state, force_show=False):
        """Show or hide buttons based on game state ('in_game', 'pitching', 'menu')."""

        # States that should always show their UI regardless of H-toggle
        ui_toggle_exempt = {
            'gameday_start', 'gameday_transition', 'gameday_simulation',
            'gameday_final', 'gameday_resume', 'gameday_history',
            'gameday_history_detail', 'main_menu', 'mode_select', 'settings',
            'key_bindings', 'summary', 'sandbox_menu',
        }

        # Check if UI should be hidden due to key binding toggle
        if (self.key_binding_manager and
            not self.key_binding_manager.is_ui_visible() and
            not force_show and
            state not in ui_toggle_exempt):
            # Hide all UI elements when UI visibility is toggled off (except banner)
            for button in self.buttons.values():
                button.hide()
            # Keep banner visible - it should be unaffected by UI toggle
            # self.banner.hide_banner()  # Commented out to keep banner visible
            return

        # Hide all buttons initially
        for button in self.buttons.values():
            button.hide()

        if state in ('main_menu', 'summary', 'settings', 'key_bindings',
                     'mode_select', 'sandbox_menu', 'sandbox_gameplay'):
            # What these branches did besides showing their widgets.
            self.banner.hide_banner()

    def draw_typing_effect(self, message, counter, speed, position, use_big_font=False):
        """Draws text with a typing effect at the given position."""
        font = self.big_font if use_big_font else self.font
        snip = font.render(message[0:counter//speed], True, 'white')
        self.screen.blit(snip, position)

    def draw_completed_message(self, message, position, use_big_font=False, use_small_font=False, color='white'):
        """Draws a completed message at the given position."""
        if use_big_font:
            font = self.big_font
        elif use_small_font:
            font = self.small_font
        else:
            font = self.font
        text = font.render(message, True, color)
        self.screen.blit(text, position)

    def set_ui_visibility(self, visible: bool, current_state: str = None):
        """Toggle visibility of all UI elements except the game screen."""
        if visible and current_state:
            # Show all UI elements based on current state
            self.set_button_visibility(current_state)
        elif not visible:
            # Hide all UI elements except banner
            for button in self.buttons.values():
                button.hide()
            # Keep banner visible - it should be unaffected by UI toggle
            # self.banner.hide_banner()  # Commented out to keep banner visible
