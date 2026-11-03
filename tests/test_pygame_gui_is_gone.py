"""pygame_gui is gone, and so is everything that existed to serve it.

The game drew its buttons two ways for a long time: a hand-drawn kit on
`gameday_theme` for the newer screens, and `pygame_gui` widgets for the rest.
The widgets always drew on top and hit-tested globally, which is what forced
the visibility switch, the buttons hidden by faking another screen, and the
modal loops that skipped the gui draw. One system is left; these pin that a
second one does not grow back.
"""

import pathlib
import re

import pytest

from strikefactor import config

REPO = pathlib.Path(__file__).resolve().parent.parent
_IMPORT = re.compile(r"^\s*(?:import|from)\s+pygame_gui\b", re.MULTILINE)


def _sources():
    for root in ('strikefactor', 'analysis', 'tools', 'tests'):
        yield from (REPO / root).rglob('*.py')


def test_no_module_imports_pygame_gui():
    offenders = [str(path.relative_to(REPO)) for path in _sources()
                 if _IMPORT.search(path.read_text())]
    assert not offenders


def test_pygame_gui_is_not_a_dependency():
    assert 'pygame_gui' not in (REPO / 'pyproject.toml').read_text()
    assert 'pygame-gui' not in (REPO / 'uv.lock').read_text()


def test_the_widget_theme_is_gone():
    """`theme.json` styled the widgets and nothing else. Looks live in
    `gameday_theme` now; a theme file would be a second place to set them."""
    assert not pathlib.Path(config.get_path('assets/theme.json')).exists()
    assert 'theme.json' not in (REPO / 'pyproject.toml').read_text()


@pytest.mark.parametrize('name', [
    'set_button_visibility', 'set_visibility_state',
    'register_button_callback', 'process_events',
    'update_sandbox_pitch_buttons', 'draw_typing_effect',
    'draw_completed_message',
])
def test_the_widget_plumbing_is_gone(name):
    """The global switch that showed and hid widgets by screen name, the
    callback registry, the event pump and the typewriter text helpers. A
    screen lists its own buttons now (`buttons()`), so none of these has a
    job; a call to one means a screen has stopped owning its interface."""
    pattern = re.compile(rf"\.{name}\(")
    offenders = [str(path.relative_to(REPO))
                 for root in ('strikefactor', 'tools')
                 for path in (REPO / root).rglob('*.py')
                 if pattern.search(path.read_text())]
    assert not offenders


def test_game_wires_keys_not_button_callbacks():
    from strikefactor.main import Game

    assert not hasattr(Game, '_setup_ui_callbacks')
    assert not hasattr(Game, '_sandbox_select_pitch')
    assert not hasattr(Game, '_sandbox_switch_pitcher')
