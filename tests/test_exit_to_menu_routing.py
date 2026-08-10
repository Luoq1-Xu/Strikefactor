"""The MAIN_MENU hotkey must return to the menu of the mode being played.

`Game` can't be constructed headlessly (display + assets), so the routing
method is bound to a stub that carries only the fields it reads. That is
enough to pin the branch, which is the part that regressed: escaping a
Sandbox session used to land in the Arcade pitcher-select menu.
"""

from strikefactor.main import Game


class _StubStateManager:
    def __init__(self, name):
        self.current_state_name = name


class _StubGame:
    """Records which exit path `exit_to_menu` took."""

    exit_to_menu = Game.exit_to_menu

    def __init__(self, gamemode, state_name):
        self.current_gamemode = gamemode
        self.state_manager = _StubStateManager(state_name)
        self.went = None

    def return_to_sandbox_menu(self):
        self.went = 'sandbox_menu'

    def set_menu_state(self, state):
        self.went = ('set_menu_state', state)


def test_sandbox_gameplay_escapes_to_sandbox_menu():
    g = _StubGame('sandbox_gameplay', 'sandbox_gameplay')
    g.exit_to_menu()
    assert g.went == 'sandbox_menu'


def test_sandbox_side_screens_escape_to_sandbox_menu():
    """view-pitches/visualization keep `current_gamemode` on sandbox."""
    for state_name in ('view_pitches', 'visualization'):
        g = _StubGame('sandbox_gameplay', state_name)
        g.exit_to_menu()
        assert g.went == 'sandbox_menu', state_name


def test_arcade_gameplay_escapes_to_arcade_menu():
    g = _StubGame('Sasaki', 'gameplay')
    g.exit_to_menu()
    assert g.went == ('set_menu_state', 0)


def test_gameday_gameplay_escapes_to_arcade_menu():
    g = _StubGame(0, 'gameplay')
    g.exit_to_menu()
    assert g.went == ('set_menu_state', 0)
