import json

import pygame
import pygame_gui
from pygame_gui.core import ObjectID

from strikefactor.config import SCREEN_WIDTH, get_path, resource_path
from strikefactor.helpers import StatSwing
from strikefactor.ui.lap_log_panel import LapLogPanel
from strikefactor.ui.scouting_panel import ScoutingReportPanel


class UIManager:
    # ── Left sidebar layout ──────────────────────────────────────────────
    # Arcade and Sandbox stack *different* button sets into the same column.
    # Sandbox inserts five pitcher-switch rows where Arcade puts SCOUT/PITCHVIZ,
    # so any button shown by both layouts needs a per-layout position — leaving
    # PITCHVIZ at its Arcade slot puts it exactly on top of the SASAKI row and
    # it swallows the click. `_apply_sidebar_layout()` re-places them.
    SIDEBAR_X = 6
    SIDEBAR_W = 120
    SIDEBAR_H = 28
    SIDEBAR_TOP = 188
    SIDEBAR_STEP = 28

    # Sandbox column slots: 0 ZONE, 1 BATTER, 2 PITCHVIZ, 3-7 pitchers,
    # 9-11 pitch toggles, 13 SOUND, 14 EXIT.
    _SHARED_SIDEBAR_POS = {
        'arcade': {'view_pitches': (SIDEBAR_X, 326)},
        'sandbox': {'view_pitches': (SIDEBAR_X, SIDEBAR_TOP + SIDEBAR_STEP * 2)},
    }

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
        self.small_font = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 28)
        self.font = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 48)  # +20% from 40
        self.big_font = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 84)  # +20% from 70
        self.button_callbacks = {}
        self.key_binding_manager = None  # Will be set after initialization
        self.settings_manager = None  # Will be set after initialization
        self._sidebar_layout = 'arcade'  # Buttons are created at Arcade slots
        self._create_ui_elements()

    def set_key_binding_manager(self, key_binding_manager):
        """Set the key binding manager reference for UI visibility control."""
        self.key_binding_manager = key_binding_manager

    def set_settings_manager(self, settings_manager):
        """Set the settings manager reference (e.g. for HUD mode lookups)."""
        self.settings_manager = settings_manager

    def _hud_mode(self) -> str:
        if self.settings_manager is None:
            return "legacy"
        return self.settings_manager.get_hud_mode()

    def _is_legacy_hud(self) -> bool:
        """Side-panel buttons only render in legacy mode."""
        return self._hud_mode() == "legacy"

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
            # View toggles group
            'strikezone': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top), (sandbox_w, sandbox_h)),
                text='ZONE', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'toggle_batter': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step), (sandbox_w, sandbox_h)),
                text='BATTER', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'visualise': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 2), (sandbox_w, sandbox_h)),
                text='TRACK', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            # Analysis group
            'scout': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 296), (120, 28)),
                text='SCOUT', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'view_pitches': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect(self._SHARED_SIDEBAR_POS['arcade']['view_pitches'],
                                          (sandbox_w, sandbox_h)),
                text='PITCHVIZ', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            # Session group
            'lap_stats': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 362), (58, 28)),
                text='LAP', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'view_laps': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((68, 362), (58, 28)),
                text='LOG', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            # System group
            'toggle_ump_sound': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 398), (120, 28)),
                text='SOUND', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'main_menu': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 428), (120, 28)),
                text='MENU', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

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
            # Dedicated menu-screen sized "main menu" for gameday menu states,
            # so the tiny (6, 428) sidebar button isn't shown on full menu screens.
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
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 3), (sandbox_w, sandbox_h)),
                text='SALE', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_degrom': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 4), (sandbox_w, sandbox_h)),
                text='DEGROM', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_sasaki': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 5), (sandbox_w, sandbox_h)),
                text='SASAKI', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_yamamoto': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 6), (sandbox_w, sandbox_h)),
                text='YAMAMOTO', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_mcclanahan': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 7), (sandbox_w, sandbox_h)),
                text='MCCLANAHAN', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

            # Sandbox gameplay - Pitch toggle buttons (left sidebar, 2-column broadcast style)
            'sandbox_pitch_1': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 9), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_2': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x + 62, sandbox_top + sandbox_step * 9), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_3': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 10), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_4': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x + 62, sandbox_top + sandbox_step * 10), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_5': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 11), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_6': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x + 62, sandbox_top + sandbox_step * 11), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

            # Sandbox gameplay - System buttons (left sidebar bottom)
            'sandbox_sound': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 13), (sandbox_w, sandbox_h)),
                text='SOUND', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_exit': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 14), (sandbox_w, sandbox_h)),
                text='EXIT', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button'))
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
        self.scoreboard = pygame_gui.elements.UITextBox(
            html_text="",
            relative_rect=pygame.Rect((950, 30), (310, 260)),  # Enlarged: +60px width, +60px height
            manager=self.manager
        )
        self.pitch_result = pygame_gui.elements.UITextBox(
            html_text="",
            relative_rect=pygame.Rect((950, 300), (310, 200)),  # Enlarged: +60px width, adjusted position
            manager=self.manager
        )
        self.view_window = StatSwing((25, 25), self.manager, [], [])
        self.scouting_panel = ScoutingReportPanel(
            position=(1000, 50),  # Same position as scoreboard
            manager=self.manager
        )
        self.lap_log_panel = LapLogPanel(
            position=(465, 160),  # Center of screen
            manager=self.manager
        )
        self.banner.hide()
        self.view_window.hide()
        self.scoreboard.hide()
        self.pitch_result.hide()
        self.scouting_panel.hide()
        self.lap_log_panel.hide()

        # Hide all buttons initially
        for button in self.buttons.values():
            button.hide() 

    def process_events(self, event):
        """Processes events for the UI manager."""
        self.manager.process_events(event)
        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            # Handle lap log panel close button
            if event.ui_element == self.lap_log_panel.get_close_button():
                self.lap_log_panel.hide()
                return

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

    def update_pitch_info(self, pitch_trajectories, last_pitch_info):
        """Updates pitch information in the view window (legacy method)."""
        self.view_window.update_pitch_info(pitch_trajectories, last_pitch_info)

    def update_pitch_info_enhanced(self, enhanced_records):
        """Updates pitch information with enhanced record data for advanced visualization."""
        self.view_window.update_pitch_info_enhanced(enhanced_records)

    def show_view_window(self):
        """Shows the pitch view window."""
        self.view_window.show()

    def hide_view_window(self):
        """Hides the pitch view window."""
        self.view_window.hide()

    def toggle_scouting_panel(self, pitcher=None):
        """Toggle the scouting report panel visibility (replaces scoreboard when shown)."""
        if pitcher:
            self.scouting_panel.update_data(pitcher)

        if self.scouting_panel.visible:
            # Hide scouting panel, show scoreboard
            self.scouting_panel.hide()
            self.scoreboard.show()
        else:
            # Show scouting panel, hide scoreboard
            self.scoreboard.hide()
            self.scouting_panel.show()

    def update_scouting_panel(self, pitcher):
        """Update the scouting panel with pitcher data."""
        if pitcher:
            self.scouting_panel.update_data(pitcher)

    def hide_scouting_panel(self):
        """Hide the scouting report panel."""
        self.scouting_panel.hide()

    def refresh_scouting_panel(self):
        """Refresh the scouting panel stats (call after each pitch)."""
        if self.scouting_panel.visible:
            self.scouting_panel.refresh_stats()

    def toggle_lap_log_panel(self, field_renderer=None):
        """Toggle the lap log panel visibility."""
        # Hide scouting panel if visible to avoid overlap
        if self.scouting_panel.visible:
            self.scouting_panel.hide()
            self.scoreboard.show()

        if field_renderer:
            laps = field_renderer.get_lap_history()
            # Get current session stats
            current_stats = {
                'total_pitches': field_renderer.total_pitches,
                'total_swings': field_renderer.total_swings,
                'total_hits': field_renderer.total_hits,
                'total_at_bats': field_renderer.total_at_bats,
                'batting_average': field_renderer.get_overall_batting_average()
            }
            self.lap_log_panel.update_data(laps, current_stats)

        if self.lap_log_panel.visible:
            self.lap_log_panel.hide()
        else:
            self.lap_log_panel.show()

    def hide_lap_log_panel(self):
        """Hide the lap log panel."""
        self.lap_log_panel.hide()

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

    def update_view_window_fps(self, display_fps):
        """Update the view window's display FPS for animation timing."""
        self.view_window.set_display_fps(display_fps)

    def hide_banner(self):
        self.banner.hide()

    def set_visibility_state(self, state):
        """Alias for set_button_visibility for clearer state-based visibility."""
        self.set_button_visibility(state)

    def _apply_sidebar_layout(self, layout):
        """Move sidebar buttons shared by both column layouts to their slot.

        See `_SHARED_SIDEBAR_POS`: Sandbox and Arcade stack different button
        sets into the same column, so a button in both has to be re-placed on
        every layout change or it ends up sitting on another button's row.
        """
        if layout == self._sidebar_layout:
            return
        self._sidebar_layout = layout
        for name, pos in self._SHARED_SIDEBAR_POS[layout].items():
            self.buttons[name].set_relative_position(pos)

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
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.view_window.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
            return

        # Hide all buttons initially
        for button in self.buttons.values():
            button.hide()

        self._apply_sidebar_layout('sandbox' if state.startswith('sandbox') else 'arcade')

        if state == 'in_game':
            if self._is_legacy_hud():
                self.buttons['strikezone'].show()
                self.buttons['main_menu'].show()
                self.buttons['toggle_ump_sound'].show()
                self.buttons['view_pitches'].show()
                self.buttons['toggle_batter'].show()
                self.buttons['visualise'].show()
                self.buttons['scout'].show()
                self.buttons['lap_stats'].show()
                self.buttons['view_laps'].show()
            # Scorebug handles stats display during gameplay
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'pitching':
            # All buttons are hidden during the pitch animation
            pass
        elif state == 'view_pitches':
            # Show the same buttons as in_game so they can toggle back
            if self._is_legacy_hud():
                self.buttons['strikezone'].show()
                self.buttons['main_menu'].show()
                self.buttons['toggle_ump_sound'].show()
                self.buttons['view_pitches'].show()
                self.buttons['toggle_batter'].show()
                self.buttons['visualise'].show()
                self.buttons['scout'].show()
                self.buttons['lap_stats'].show()
                self.buttons['view_laps'].show()
            # Scorebug handles stats display
            self.scoreboard.hide()
            self.pitch_result.hide()
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
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
        elif state == "visualise":
            # Show the same buttons as in_game so they can toggle back
            if self._is_legacy_hud():
                self.buttons['strikezone'].show()
                self.buttons['main_menu'].show()
                self.buttons['toggle_ump_sound'].show()
                self.buttons['view_pitches'].show()
                self.buttons['toggle_batter'].show()
                self.buttons['visualise'].show()
                self.buttons['scout'].show()
                self.buttons['lap_stats'].show()
                self.buttons['view_laps'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'summary':
            self.buttons['back_to_main_menu'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
        elif state == 'inning_end':
            # Continue button always shown so the player can advance.
            self.buttons['continue_to_summary'].show()
            if self._is_legacy_hud():
                self.buttons['visualise'].show()
                self.buttons['view_pitches'].show()
                self.buttons['strikezone'].show()
                self.buttons['main_menu'].show()
                self.buttons['lap_stats'].show()
                self.buttons['view_laps'].show()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'settings':
            # The body of this screen is drawn by ui/settings_panel.py; only
            # the footer nav is a widget.
            self.buttons['back_to_main'].show()
            self.buttons['key_bindings'].show()
            self.buttons['reset_settings'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'key_bindings':
            self.buttons['back_from_keybinds'].show()
            self.buttons['reset_keybinds'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
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
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
        elif state == 'gameday_resume':
            # Resumable-sessions list
            self.buttons['gd_list_back'].show()
            self.buttons['gd_page_prev'].show()
            self.buttons['gd_page_next'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
        elif state == 'gameday_history':
            # Completed-games list
            self.buttons['gd_list_back'].show()
            self.buttons['gd_page_prev'].show()
            self.buttons['gd_page_next'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
        elif state == 'gameday_history_detail':
            # Single completed-game detail (linescore) — back only
            self.buttons['gd_list_back'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
        elif state == 'gameday_transition':
            # After player's inning ends, before opponent bats
            self.buttons['next_inning'].show()
            self.buttons['view_game_log'].show()
            self.buttons['gameday_main_menu'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
        elif state == 'gameday_simulation':
            # After opponent simulation, ready to start player batting
            self.buttons['start_batting'].show()
            self.buttons['view_game_log'].show()
            self.buttons['gameday_main_menu'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
        elif state == 'gameday_final':
            # Game over screen
            self.buttons['final_menu'].show()
            self.buttons['view_game_log'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
        elif state == 'mode_select':
            # Top-level mode selection (Arcade/Sandbox)
            self.buttons['arcade_mode'].show()
            self.buttons['sandbox_mode'].show()
            self.buttons['settings'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
        elif state == 'sandbox_menu':
            # Sandbox mode menu - pitcher selection (matching arcade aesthetic)
            self.buttons['sandbox_menu_sale'].show()
            self.buttons['sandbox_menu_degrom'].show()
            self.buttons['sandbox_menu_sasaki'].show()
            self.buttons['sandbox_menu_yamamoto'].show()
            self.buttons['sandbox_menu_mcclanahan'].show()
            self.buttons['back_to_mode_select'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
        elif state == 'sandbox_gameplay':
            # Sandbox gameplay - broadcast-style left sidebar
            # Standard controls
            self.buttons['strikezone'].show()
            self.buttons['toggle_batter'].show()
            self.buttons['view_pitches'].show()
            # Pitcher switch buttons
            self.buttons['sandbox_pitcher_sale'].show()
            self.buttons['sandbox_pitcher_degrom'].show()
            self.buttons['sandbox_pitcher_sasaki'].show()
            self.buttons['sandbox_pitcher_yamamoto'].show()
            self.buttons['sandbox_pitcher_mcclanahan'].show()
            # Pitch buttons shown via update_sandbox_pitch_buttons()
            # System buttons
            self.buttons['sandbox_sound'].show()
            self.buttons['sandbox_exit'].show()
            self.banner.hide()
            self.scouting_panel.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'sandbox_view_pitches':
            # Sandbox mode view pitches - same sidebar layout
            self.buttons['strikezone'].show()
            self.buttons['toggle_batter'].show()
            self.buttons['view_pitches'].show()
            self.buttons['sandbox_pitcher_sale'].show()
            self.buttons['sandbox_pitcher_degrom'].show()
            self.buttons['sandbox_pitcher_sasaki'].show()
            self.buttons['sandbox_pitcher_yamamoto'].show()
            self.buttons['sandbox_pitcher_mcclanahan'].show()
            self.buttons['sandbox_sound'].show()
            self.buttons['sandbox_exit'].show()
            self.banner.hide()
            self.scouting_panel.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()

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
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.view_window.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()

