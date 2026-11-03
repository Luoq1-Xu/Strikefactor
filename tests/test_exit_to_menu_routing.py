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

    def __init__(self, gamemode, state_name, in_gameday_mode=False):
        self.current_gamemode = gamemode
        self.in_gameday_mode = in_gameday_mode
        self.state_manager = _StubStateManager(state_name)
        self.went = None
        self.torn_down = False

    def return_to_sandbox_menu(self):
        self.went = 'sandbox_menu'

    def set_menu_state(self, state):
        self.went = ('set_menu_state', state)

    def _teardown_active_session(self):
        self.torn_down = True

    def enter_gameday_mode(self):
        self.went = 'gameday_setup'


def test_sandbox_gameplay_escapes_to_sandbox_menu():
    g = _StubGame('sandbox_gameplay', 'sandbox_gameplay')
    g.exit_to_menu()
    assert g.went == 'sandbox_menu'


def test_sandbox_side_screens_escape_to_sandbox_menu():
    """The visualization screen keeps `current_gamemode` on sandbox."""
    g = _StubGame('sandbox_gameplay', 'visualization')
    g.exit_to_menu()
    assert g.went == 'sandbox_menu'


def test_arcade_gameplay_escapes_to_arcade_menu():
    g = _StubGame('Sasaki', 'gameplay')
    g.exit_to_menu()
    assert g.went == ('set_menu_state', 0)


def test_gameday_gameplay_escapes_to_gameday_setup():
    """GameDay is a mode on the main menu, not a button on the Arcade one, so
    its menu is its own setup screen: the one that can resume the game just
    left. The session is torn down first, as every other exit does."""
    g = _StubGame(0, 'gameplay', in_gameday_mode=True)
    g.exit_to_menu()
    assert g.went == 'gameday_setup'
    assert g.torn_down
