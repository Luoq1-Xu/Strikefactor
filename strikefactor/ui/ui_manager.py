import json

import pygame
import pygame_gui
from pygame_gui.core import ObjectID

from strikefactor.config import SCREEN_WIDTH, get_path


class UIManager:
    # ── Left sidebar layout ──────────────────────────────────────────────
    # Only Sandbox has a sidebar: the pitcher switch and the pitch toggles,
    # which are selections and have no key. Everything else that used to sit
    # in this column (ZONE, BATTER, REVIEW, SOUND, MENU, EXIT) is a key
    # binding, so gameplay itself shows no buttons at all.
    SIDEBAR_X = 6
    SIDEBAR_W = 120
    SIDEBAR_H = 28
    SIDEBAR_TOP = 188
    SIDEBAR_STEP = 28

    # Sandbox column slots: 0-4 pitchers, 6-8 pitch toggles.

    # ── Menu footer (settings / key bindings) ────────────────────────────
    # These screens draw their body themselves (ui/settings_panel.py); the
    # only pygame_gui widgets left on them are the nav buttons along the
    # bottom, anchored to the same 40px margin the GameDay screens use.
    # Positions are *derived* from SCREEN_WIDTH — the grid that used to live
    # here was 21 literal rects whose rows centred on 620, 640, 740 and 800
    # against a screen centre of 640, which is what read as "off centre".
    MENU_MARGIN_X = 40
    MENU_FOOTER_Y = 646
    MENU_FOOTER_H = 36

    @classmethod
    def _footer_row_right(cls, widths, gap=10):
        """Right-align a run of footer buttons; returns rects left-to-right."""
        total = sum(widths) + gap * (len(widths) - 1)
        x = SCREEN_WIDTH - cls.MENU_MARGIN_X - total
        rects = []
        for width in widths:
            rects.append(pygame.Rect(x, cls.MENU_FOOTER_Y, width,
                                     cls.MENU_FOOTER_H))
            x += width + gap
        return rects

    @classmethod
    def _footer_back_rect(cls, width=150):
        return pygame.Rect(cls.MENU_MARGIN_X, cls.MENU_FOOTER_Y, width,
                           cls.MENU_FOOTER_H)

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
        """Creates and returns a dictionary of in-game UI buttons."""
        sandbox_x = self.SIDEBAR_X
        sandbox_w = self.SIDEBAR_W
        sandbox_h = self.SIDEBAR_H
        sandbox_top = self.SIDEBAR_TOP
        sandbox_step = self.SIDEBAR_STEP
        settings_footer = self._footer_row_right([190, 200])
        keybind_footer = self._footer_row_right([170])
        buttons = {
            # Pitcher selection buttons for main  menu
            'sale': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 500), (190, 50)),
                text='Chris Sale', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'degrom': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 600), (190, 50)),
                text='Jacob deGrom', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'sasaki': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 500), (190, 50)),
                text='Roki Sasaki', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'yamamoto': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 600), (190, 50)),
                text='Y. Yamamoto', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'mcclanahan': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((800, 500), (190, 50)),
                text='S. Mcclanahan', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),

            # Random scenario button
            'random_scenario': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((500, 400), (280, 50)),
                text='Random Scenario', manager=manager),

            # GameDay mode button
            'gameday': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((800, 600), (190, 50)),
                text='GameDay Mode', manager=manager),

            # Button for summary screen
            'back_to_main_menu': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((540, 600), (200, 50)),
                text='MAIN MENU', manager=manager),
                
            # Button for inning end screen
            'continue_to_summary': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((540, 630), (200, 50)),
                text='CONTINUE', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button_primary')),

            # Settings entry point (lives on the mode-select screen)
            'settings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((1130, 650), (140, 40)),
                text='Settings', manager=manager),

            # ── Settings screen nav ──────────────────────────────────────
            # The difficulty / toggle / FPS grid that used to sit here is
            # gone: ui/settings_panel.py draws those as rows. What is left
            # is nav, broadcast-styled and margin-anchored like GameDay's.
            'back_to_main': pygame_gui.elements.UIButton(
                relative_rect=self._footer_back_rect(),
                text='<  BACK', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'key_bindings': pygame_gui.elements.UIButton(
                relative_rect=settings_footer[0],
                text='KEY BINDINGS  >', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'reset_settings': pygame_gui.elements.UIButton(
                relative_rect=settings_footer[1],
                text='RESET DEFAULTS', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

            # ── Key bindings screen nav ──────────────────────────────────
            'back_from_keybinds': pygame_gui.elements.UIButton(
                relative_rect=self._footer_back_rect(),
                text='<  BACK', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'reset_keybinds': pygame_gui.elements.UIButton(
                relative_rect=keybind_footer[0],
                text='RESET KEYS', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

            # GameDay mode buttons (broadcast-styled to match the refreshed UI)
            'start_gameday': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 580), (300, 44)),
                text='STEP IN  >', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'gameday_prev_pitcher': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((255, 330), (50, 50)),
                text='<', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'gameday_next_pitcher': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((975, 330), (50, 50)),
                text='>', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            # Menu-screen sized "main menu" for the gameday menu states.
            'gameday_main_menu': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((40, 660), (150, 36)),
                text='MAIN MENU', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'next_inning': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((780, 600), (440, 44)),
                text='NEXT INNING  >', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'start_batting': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((780, 600), (440, 44)),
                text='STEP IN  >', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'view_game_log': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((780, 650), (210, 32)),
                text='GAME LOG', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'final_menu': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((780, 600), (440, 44)),
                text='NEXT GAME  >', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

            # GameDay setup-screen secondary entries (resume / browse history).
            'gameday_resume': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 634, 145, 36)),
                text='RESUME', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'gameday_past_games': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((645, 634, 145, 36)),
                text='PAST GAMES', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

            # Shared nav for the GameDay list screens (resume / history).
            'gd_list_back': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((40, 640, 150, 40)),
                text='<  BACK', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'gd_page_prev': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((900, 640, 150, 40)),
                text='<  PREV', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'gd_page_next': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((1090, 640, 150, 40)),
                text='NEXT  >', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

            # Mode selection buttons (for top-level menu)
            'arcade_mode': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 450), (300, 70)),
                text='ARCADE', manager=manager),
            'sandbox_mode': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 540), (300, 70)),
                text='SANDBOX', manager=manager),
            'back_to_mode_select': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((50, 650), (150, 50)),
                text='Back', manager=manager),

            # Sandbox menu - Pitcher selection buttons (matching arcade layout)
            'sandbox_menu_sale': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 500), (190, 50)),
                text='Chris Sale', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'sandbox_menu_degrom': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 600), (190, 50)),
                text='Jacob deGrom', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'sandbox_menu_sasaki': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 500), (190, 50)),
                text='Roki Sasaki', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'sandbox_menu_yamamoto': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 600), (190, 50)),
                text='Y. Yamamoto', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'sandbox_menu_mcclanahan': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((800, 500), (190, 50)),
                text='S. Mcclanahan', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),

            # Sandbox gameplay - Pitcher switch buttons (left sidebar, broadcast style)
            'sandbox_pitcher_sale': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top), (sandbox_w, sandbox_h)),
                text='SALE', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_degrom': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 1), (sandbox_w, sandbox_h)),
                text='DEGROM', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_sasaki': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 2), (sandbox_w, sandbox_h)),
                text='SASAKI', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_yamamoto': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 3), (sandbox_w, sandbox_h)),
                text='YAMAMOTO', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_mcclanahan': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 4), (sandbox_w, sandbox_h)),
                text='MCCLANAHAN', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

            # Sandbox gameplay - Pitch toggle buttons (left sidebar, 2-column broadcast style)
            'sandbox_pitch_1': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 6), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_2': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x + 62, sandbox_top + sandbox_step * 6), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_3': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 7), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_4': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x + 62, sandbox_top + sandbox_step * 7), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_5': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 8), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_6': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x + 62, sandbox_top + sandbox_step * 8), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
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
            relative_rect=pygame.Rect((150, 0), (980, 100)),
            manager=self.manager,
            text=""
        )
        self.banner.hide()

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

    def show_banner(self, text, typing_speed=0.1):
        """Shows the banner with the given text and a typing effect."""
        self.banner.set_text(text)
        self.banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': typing_speed})
        self.banner.show()

    def schedule_banner(self, text, delay=450, typing_speed=0.1):
        """Schedule a banner to show after a delay (in ms), to sync with umpire call."""
        self._pending_banner = {
            'text': text,
            'typing_speed': typing_speed,
            'show_time': pygame.time.get_ticks() + delay
        }

    def update(self, time_delta):
        """Updates the UI manager and all UI elements."""
        # Check for pending scheduled banners
        if hasattr(self, '_pending_banner') and self._pending_banner is not None:
            if pygame.time.get_ticks() >= self._pending_banner['show_time']:
                self.show_banner(self._pending_banner['text'], self._pending_banner['typing_speed'])
                self._pending_banner = None
        self.manager.update(time_delta)

    def draw(self):
        """Draws the UI manager and all UI elements to the screen."""
        self.manager.draw_ui(self.screen)

    def update_sandbox_pitch_buttons(self, pitch_names: list, active_pitches: set = None):
        """Update sandbox pitch type buttons based on current pitcher's arsenal.

        Args:
            pitch_names: List of available pitch type names (e.g., ['FF', 'SL', 'CH'])
            active_pitches: Set of currently active/toggled-on pitch types
        """
        if active_pitches is None:
            active_pitches = set()

        pitch_buttons = ['sandbox_pitch_1', 'sandbox_pitch_2', 'sandbox_pitch_3',
                         'sandbox_pitch_4', 'sandbox_pitch_5', 'sandbox_pitch_6']

        # Hide all pitch buttons first
        for btn_key in pitch_buttons:
            self.buttons[btn_key].hide()

        # Show and configure buttons for available pitches
        if len(pitch_names) > len(pitch_buttons):
            print(f"Warning: pitcher has {len(pitch_names)} pitches but only "
                  f"{len(pitch_buttons)} Sandbox buttons; "
                  f"{pitch_names[len(pitch_buttons):]} will be unselectable.")
        for i, pitch_name in enumerate(pitch_names):
            if i < len(pitch_buttons):
                btn = self.buttons[pitch_buttons[i]]
                # Add indicator for active pitches
                if pitch_name in active_pitches:
                    btn.set_text(f"[{pitch_name}]")
                else:
                    btn.set_text(pitch_name)
                btn.show()

    def hide_banner(self):
        self.banner.hide()

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
            # self.banner.hide()  # Commented out to keep banner visible
            return

        # Hide all buttons initially
        for button in self.buttons.values():
            button.hide()

        if state in ('in_game', 'pitching', 'visualise'):
            # Gameplay shows no buttons: every in-game action is a key
            # binding (see KeyBindingsPanel.ACTIONS).
            pass
        elif state == 'main_menu':
            self.buttons['sale'].show()
            self.buttons['degrom'].show()
            self.buttons['sasaki'].show()
            self.buttons['yamamoto'].show()
            self.buttons['mcclanahan'].show()
            self.buttons['random_scenario'].show()
            self.buttons['gameday'].show()
            self.buttons['back_to_mode_select'].show()
            self.banner.hide()
        elif state == 'summary':
            self.buttons['back_to_main_menu'].show()
            self.banner.hide()
        elif state == 'inning_end':
            # Continue button always shown so the player can advance.
            self.buttons['continue_to_summary'].show()
        elif state == 'settings':
            # The body of this screen is drawn by ui/settings_panel.py; only
            # the footer nav is a widget.
            self.buttons['back_to_main'].show()
            self.buttons['key_bindings'].show()
            self.buttons['reset_settings'].show()
            self.banner.hide()
        elif state == 'key_bindings':
            self.buttons['back_from_keybinds'].show()
            self.buttons['reset_keybinds'].show()
            self.banner.hide()
        elif state == 'gameday_start':
            # Initial gameday screen with pitcher carousel
            self.buttons['start_gameday'].show()
            self.buttons['gameday_prev_pitcher'].show()
            self.buttons['gameday_next_pitcher'].show()
            self.buttons['gameday_main_menu'].show()
            self.buttons['gameday_past_games'].show()
            # RESUME only appears when there's an in-progress game to resume.
            try:
                from strikefactor.data import gameday_sessions
                if gameday_sessions.load_sessions():
                    self.buttons['gameday_resume'].show()
            except Exception as e:
                print(f"[gameday] resume-button visibility check failed: {e}")
        elif state == 'gameday_resume':
            # Resumable-sessions list
            self.buttons['gd_list_back'].show()
            self.buttons['gd_page_prev'].show()
            self.buttons['gd_page_next'].show()
        elif state == 'gameday_history':
            # Completed-games list
            self.buttons['gd_list_back'].show()
            self.buttons['gd_page_prev'].show()
            self.buttons['gd_page_next'].show()
        elif state == 'gameday_history_detail':
            # Single completed-game detail (linescore) — back only
            self.buttons['gd_list_back'].show()
        elif state == 'gameday_transition':
            # After player's inning ends, before opponent bats
            self.buttons['next_inning'].show()
            self.buttons['view_game_log'].show()
            self.buttons['gameday_main_menu'].show()
        elif state == 'gameday_simulation':
            # After opponent simulation, ready to start player batting
            self.buttons['start_batting'].show()
            self.buttons['view_game_log'].show()
            self.buttons['gameday_main_menu'].show()
        elif state == 'gameday_final':
            # Game over screen
            self.buttons['final_menu'].show()
            self.buttons['view_game_log'].show()
        elif state == 'mode_select':
            # Top-level mode selection (Arcade/Sandbox)
            self.buttons['arcade_mode'].show()
            self.buttons['sandbox_mode'].show()
            self.buttons['settings'].show()
            self.banner.hide()
        elif state == 'sandbox_menu':
            # Sandbox mode menu - pitcher selection (matching arcade aesthetic)
            self.buttons['sandbox_menu_sale'].show()
            self.buttons['sandbox_menu_degrom'].show()
            self.buttons['sandbox_menu_sasaki'].show()
            self.buttons['sandbox_menu_yamamoto'].show()
            self.buttons['sandbox_menu_mcclanahan'].show()
            self.buttons['back_to_mode_select'].show()
            self.banner.hide()
        elif state == 'sandbox_gameplay':
            # Sandbox gameplay - broadcast-style left sidebar
            # Pitcher switch buttons
            self.buttons['sandbox_pitcher_sale'].show()
            self.buttons['sandbox_pitcher_degrom'].show()
            self.buttons['sandbox_pitcher_sasaki'].show()
            self.buttons['sandbox_pitcher_yamamoto'].show()
            self.buttons['sandbox_pitcher_mcclanahan'].show()
            # Pitch buttons shown via update_sandbox_pitch_buttons()
            self.banner.hide()

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
            # self.banner.hide()  # Commented out to keep banner visible
