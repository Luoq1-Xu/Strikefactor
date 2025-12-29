import pygame
import json
from enum import Enum
from config import get_path
from typing import Dict, Callable, Optional, Set

class KeyAction(Enum):
    TOGGLE_UI = "toggle_ui"
    TOGGLE_STRIKEZONE = "toggle_strikezone"
    TOGGLE_SOUND = "toggle_sound"
    TOGGLE_BATTER = "toggle_batter"
    QUICK_PITCH = "quick_pitch"
    VIEW_PITCHES = "view_pitches"
    MAIN_MENU = "main_menu"
    TOGGLE_TRACK = "toggle_track"

class KeyBindingManager:
    def __init__(self, settings_manager):
        self.settings_manager = settings_manager
        self.settings_file = get_path("key_bindings.json")

        self.default_bindings = {
            KeyAction.TOGGLE_UI.value: pygame.K_h,
            KeyAction.TOGGLE_STRIKEZONE.value: pygame.K_z,
            KeyAction.TOGGLE_SOUND.value: pygame.K_m,
            KeyAction.TOGGLE_BATTER.value: pygame.K_b,
            KeyAction.QUICK_PITCH.value: pygame.K_SPACE,
            KeyAction.VIEW_PITCHES.value: pygame.K_v,
            KeyAction.MAIN_MENU.value: pygame.K_ESCAPE,
            KeyAction.TOGGLE_TRACK.value: pygame.K_t
        }

        self.current_bindings = self.load_bindings()
        self.action_callbacks: Dict[KeyAction, Callable] = {}
        self.pressed_keys: Set[int] = set()
        self.ui_visible = True

    def load_bindings(self) -> Dict[str, int]:
        """Load key bindings from file, create with defaults if doesn't exist."""
        try:
            with open(self.settings_file, 'r') as f:
                bindings = json.load(f)
                for key, value in self.default_bindings.items():
                    if key not in bindings:
                        bindings[key] = value
                return bindings
        except (json.JSONDecodeError, FileNotFoundError):
            return self.default_bindings.copy()

    def save_bindings(self):
        """Save current key bindings to file."""
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.current_bindings, f, indent=2)
        except Exception as e:
            print(f"Failed to save key bindings: {e}")

    def bind_key(self, action: KeyAction, key_code: int):
        """Bind a key to an action."""
        self.current_bindings[action.value] = key_code
        self.save_bindings()

    def get_key_for_action(self, action: KeyAction) -> int:
        """Get the key code bound to an action."""
        return self.current_bindings.get(action.value, self.default_bindings.get(action.value, 0))

    def get_key_name(self, key_code: int) -> str:
        """Convert key code to readable name."""
        key_names = {
            pygame.K_SPACE: "Space",
            pygame.K_ESCAPE: "Escape",
            pygame.K_RETURN: "Enter",
            pygame.K_BACKSPACE: "Backspace",
            pygame.K_TAB: "Tab",
            pygame.K_LSHIFT: "Left Shift",
            pygame.K_RSHIFT: "Right Shift",
            pygame.K_LCTRL: "Left Ctrl",
            pygame.K_RCTRL: "Right Ctrl",
            pygame.K_LALT: "Left Alt",
            pygame.K_RALT: "Right Alt",
        }

        if key_code in key_names:
            return key_names[key_code]
        elif pygame.K_a <= key_code <= pygame.K_z:
            return chr(key_code).upper()
        elif pygame.K_0 <= key_code <= pygame.K_9:
            return str(key_code - pygame.K_0)
        elif pygame.K_F1 <= key_code <= pygame.K_F12:
            return f"F{key_code - pygame.K_F1 + 1}"
        else:
            return f"Key {key_code}"

    def get_action_name(self, action: KeyAction) -> str:
        """Get human-readable name for action."""
        action_names = {
            KeyAction.TOGGLE_UI: "Toggle UI",
            KeyAction.TOGGLE_STRIKEZONE: "Toggle Strikezone",
            KeyAction.TOGGLE_SOUND: "Toggle Sound",
            KeyAction.TOGGLE_BATTER: "Toggle Batter",
            KeyAction.QUICK_PITCH: "Quick Pitch",
            KeyAction.VIEW_PITCHES: "View Pitches",
            KeyAction.MAIN_MENU: "Main Menu",
            KeyAction.TOGGLE_TRACK: "Toggle Track"
        }
        return action_names.get(action, action.value.replace('_', ' ').title())

    def register_callback(self, action: KeyAction, callback: Callable):
        """Register a callback function for an action."""
        self.action_callbacks[action] = callback

    def handle_key_down(self, key_code: int):
        """Handle key press events."""
        self.pressed_keys.add(key_code)

        for action in KeyAction:
            if self.get_key_for_action(action) == key_code:
                if action in self.action_callbacks:
                    self.action_callbacks[action]()
                else:
                    self._handle_default_action(action)

    def handle_key_up(self, key_code: int):
        """Handle key release events."""
        self.pressed_keys.discard(key_code)

    def _handle_default_action(self, action: KeyAction):
        """Handle default actions that don't require callbacks."""
        if action == KeyAction.TOGGLE_UI:
            self.ui_visible = not self.ui_visible
            print(f"UI {'shown' if self.ui_visible else 'hidden'}")
        elif action == KeyAction.TOGGLE_STRIKEZONE:
            current = self.settings_manager.get_setting("show_strikezone")
            self.settings_manager.set_setting("show_strikezone", not current)
        elif action == KeyAction.TOGGLE_SOUND:
            current = self.settings_manager.get_setting("umpire_sound")
            self.settings_manager.set_setting("umpire_sound", not current)

    def is_key_pressed(self, key_code: int) -> bool:
        """Check if a key is currently pressed."""
        return key_code in self.pressed_keys

    def is_ui_visible(self) -> bool:
        """Check if UI should be visible."""
        return self.ui_visible

    def set_ui_visibility(self, visible: bool):
        """Set UI visibility state."""
        self.ui_visible = visible

    def get_all_bindings(self) -> Dict[str, tuple]:
        """Get all current bindings as (action_name, key_name) tuples."""
        bindings = {}
        for action in KeyAction:
            key_code = self.get_key_for_action(action)
            action_name = self.get_action_name(action)
            key_name = self.get_key_name(key_code)
            bindings[action.value] = (action_name, key_name)
        return bindings

    def unbind_key(self, action: KeyAction):
        """Remove binding for an action."""
        if action.value in self.current_bindings:
            del self.current_bindings[action.value]
            self.save_bindings()

    def reset_to_defaults(self):
        """Reset all key bindings to default values."""
        self.current_bindings = self.default_bindings.copy()
        self.save_bindings()

    def is_key_available(self, key_code: int, exclude_action: Optional[KeyAction] = None) -> bool:
        """Check if a key is available for binding."""
        for action in KeyAction:
            if exclude_action and action == exclude_action:
                continue
            if self.get_key_for_action(action) == key_code:
                return False
        return True