"""The pitcher card: an arsenal in every mode, a record only in GameDay."""

from types import SimpleNamespace

import pygame
import pytest

from strikefactor.ai.AI_2 import ERAI
from strikefactor.ai.pitch_priors import BASE_USAGE
from strikefactor.gameplay import game_states as gs
from strikefactor.gameplay.gameday_manager import GameDayManager
from strikefactor.ui import gameday_theme as gdt
from strikefactor.ui import pitcher_carousel
from strikefactor.ui.pitcher_carousel import PitcherCarousel, arsenal_rows
from strikefactor.ui.pitcher_select import CARD_RECT


def _game():
    return SimpleNamespace(pitcher_manager=None,
                           banner=SimpleNamespace(hide_banner=lambda: None))


def _pitcher(key):
    ai = ERAI(list(BASE_USAGE[key]))
    ai.set_usage_prior(BASE_USAGE[key])
    return SimpleNamespace(name=key.title(), command=0.75, sprites=None, ai=ai,
                           get_pitch_names=lambda: list(BASE_USAGE[key]))


def _carousel(key, *, show_record):
    manager = SimpleNamespace(get_pitcher=lambda name: _pitcher(key))
    return PitcherCarousel(manager, default=key, show_record=show_record)


def _render(carousel, monkeypatch):
    """Draw the card and return every piece of text drawn, with its rect."""
    pygame.font.init()
    drawn = []
    real = gdt.blit_text

    def spy(screen, text, font, pos, color, align='left'):
        rect = real(screen, text, font, pos, color, align)
        drawn.append((text, rect))
        return rect
    monkeypatch.setattr(pitcher_carousel.gdt, 'blit_text', spy)
    carousel.render(pygame.Surface((gdt.SCREEN_W, gdt.SCREEN_H)), CARD_RECT)
    return drawn


def test_only_gameday_puts_the_record_on_the_card():
    assert not gs.MenuState(_game()).select.carousel.show_record
    assert not gs.SandboxMenuState(_game()).select.carousel.show_record
    assert gs.GameDayState(_game()).select.carousel.show_record


def test_a_card_without_the_record_never_reads_gameday_history(monkeypatch):
    def fail(name):
        raise AssertionError("Arcade and Sandbox have no GameDay record")
    monkeypatch.setattr(GameDayManager, 'load_history_record_vs', fail)
    drawn = _render(_carousel('sale', show_record=False), monkeypatch)
    assert not any("record" in text.lower() for text, _ in drawn)


def test_the_record_is_read_once_per_visit_not_once_per_frame(monkeypatch):
    reads = []
    monkeypatch.setattr(GameDayManager, 'load_history_record_vs',
                        lambda name: reads.append(name) or {'wins': 3, 'losses': 1, 'total': 4})
    carousel = _carousel('sale', show_record=True)
    for _ in range(3):
        drawn = _render(carousel, monkeypatch)
    assert reads == ['sale']
    assert "3W - 1L" in {text for text, _ in drawn}
    carousel.refresh()
    _render(carousel, monkeypatch)
    assert reads == ['sale', 'sale']


@pytest.mark.parametrize('key', sorted(BASE_USAGE))
def test_the_arsenal_shows_the_ais_own_mix_most_used_first(key):
    pitcher = _pitcher(key)
    rows = arsenal_rows(pitcher)
    assert {code for code, _, _ in rows} == set(pitcher.get_pitch_names())
    assert {code: share for code, _, share in rows} == pytest.approx(pitcher.ai.usage_prior())
    assert sum(share for _, _, share in rows) == pytest.approx(1.0)
    shares = [share for _, _, share in rows]
    assert shares == sorted(shares, reverse=True)
    assert all(name in pitcher_carousel.PITCH_NAMES.values() for _, name, _ in rows)


def test_the_largest_arsenal_and_the_record_both_fit_on_the_card(monkeypatch):
    key = max(BASE_USAGE, key=lambda k: len(BASE_USAGE[k]))
    monkeypatch.setattr(GameDayManager, 'load_history_record_vs',
                        lambda name: {'wins': 0, 'losses': 0, 'total': 0})
    drawn = dict(_render(_carousel(key, show_record=True), monkeypatch))
    names = [drawn[name] for _, name, _ in arsenal_rows(_pitcher(key))]
    assert len(names) == len(BASE_USAGE[key])  # no row was dropped for lack of room
    assert max(rect.bottom for rect in names) < drawn["Your record"].top
    assert all(CARD_RECT.contains(rect) for rect in drawn.values())
