"""SoundManager playback guards.

Covers the two things the contact-audio refactor depends on: per-playback
gain that does not leak between plays, and master_volume actually being
applied (it sat unread in the settings defaults before this).
"""

import os

import pytest

from strikefactor.config import get_path, resource_path
from strikefactor.engine.contact_audio import CONTACT_LADDER
from strikefactor.engine.sound_manager import SoundManager


class _FakeChannel:
    def __init__(self):
        self.volume = None

    def set_volume(self, v):
        self.volume = v


class _FakeSound:
    """Stands in for pygame.mixer.Sound, recording how it was played."""

    def __init__(self):
        self.plays = 0
        self.channels = []
        self.object_volume_set = False

    def play(self):
        self.plays += 1
        ch = _FakeChannel()
        self.channels.append(ch)
        return ch

    def set_volume(self, v):  # pragma: no cover - must never be called
        self.object_volume_set = True


class _StubSettings:
    def __init__(self, master_volume=1.0):
        self._v = master_volume

    def get_setting(self, name):
        return self._v if name == "master_volume" else None


@pytest.fixture
def sm():
    """A SoundManager with loading bypassed, so no assets or mixer needed."""
    manager = SoundManager.__new__(SoundManager)
    manager.sound_dir = "assets/sounds"
    manager.settings_manager = None
    manager.sounds = {}
    manager.strike_sounds = []
    manager.ball_sounds = []
    manager.pending_sounds = []
    return manager


def test_gain_is_set_on_the_channel_not_the_sound(sm):
    """Shared Sound objects must never be mutated — it leaks across plays."""
    sound = _FakeSound()
    sm.sounds["contact_medium"] = sound

    sm.play("contact_medium", volume=0.5)

    assert sound.object_volume_set is False, "mutated the shared Sound object"
    assert sound.channels[0].volume == pytest.approx(0.5)


def test_successive_plays_get_independent_volumes(sm):
    sound = _FakeSound()
    sm.sounds["contact_medium"] = sound

    sm.play("contact_medium", volume=0.45)
    sm.play("contact_medium", volume=1.0)

    assert sound.channels[0].volume == pytest.approx(0.45)
    assert sound.channels[1].volume == pytest.approx(1.0)


def test_master_volume_scales_playback(sm):
    sound = _FakeSound()
    sm.sounds["contact_medium"] = sound
    sm.set_settings_manager(_StubSettings(0.5))

    sm.play("contact_medium", volume=0.8)
    assert sound.channels[0].volume == pytest.approx(0.4)


def test_master_volume_applies_without_an_explicit_volume(sm):
    sound = _FakeSound()
    sm.sounds["contact_medium"] = sound
    sm.set_settings_manager(_StubSettings(0.25))

    sm.play("contact_medium")
    assert sound.channels[0].volume == pytest.approx(0.25)


def test_bad_master_volume_falls_back_to_full(sm):
    sound = _FakeSound()
    sm.sounds["contact_medium"] = sound
    sm.set_settings_manager(_StubSettings("loud"))

    sm.play("contact_medium")
    assert sound.channels[0].volume == pytest.approx(1.0)


def test_unknown_sound_is_a_no_op(sm):
    assert sm.play("does_not_exist") is None


def test_play_contact_plays_exactly_one_sound_and_returns_ev(sm):
    for name, _, _ in CONTACT_LADDER:
        sm.sounds[name] = _FakeSound()

    ev = sm.play_contact(0.9, "power")

    assert isinstance(ev, float)
    assert sum(s.plays for s in sm.sounds.values()) == 1


def test_play_contact_only_selects_loaded_samples(sm):
    """A trimmed asset set must not select a sample that isn't there."""
    sm.sounds["contact_medium"] = _FakeSound()

    for quality in (0.0, 0.25, 0.5, 0.75, 1.0):
        sm.play_contact(quality, "contact")

    assert sm.sounds["contact_medium"].plays == 5


# ---- Asset wiring -------------------------------------------------------

def test_every_ladder_rung_is_a_registered_sound_key():
    """The ladder names keys, the loader names files — they must agree.

    A rename that touches one and not the other degrades silently: the
    rung is skipped as "unavailable" and contact quietly loses a level
    instead of raising.
    """
    missing = [name for name, _, _ in CONTACT_LADDER
               if name not in SoundManager.SOUND_FILES]
    assert not missing, f"ladder rungs with no sound file: {missing}"


def test_every_registered_sound_file_exists_on_disk():
    """Catches renames that update code but not the asset, and vice versa."""
    missing = []
    for key, filename in SoundManager.SOUND_FILES.items():
        path = resource_path(get_path(os.path.join("assets/sounds", filename)))
        if not os.path.exists(path):
            missing.append(f"{key} -> {filename}")
    assert not missing, f"missing sound assets: {missing}"


def test_every_ladder_rung_comes_from_the_contact_directory():
    """Bat sounds and mitt sounds live in separate directories for a reason.

    The mitt pops were briefly wired into the ladder as weak-contact ticks,
    which put a catcher's mitt slap on balls the batter had just hit. A rung
    sourced from anywhere but contact/ means that has happened again.
    """
    offenders = []
    for name, _, _ in CONTACT_LADDER:
        path = SoundManager.SOUND_FILES.get(name, "")
        if not path.startswith(SoundManager.CONTACT_DIR + "/"):
            offenders.append(f"{name} -> {path or '<missing>'}")
    assert not offenders, f"ladder rungs sourced outside contact/: {offenders}"


def test_mitt_sounds_are_not_in_the_contact_ladder():
    rungs = {name for name, _, _ in CONTACT_LADDER}
    mitt_keys = {k for k, v in SoundManager.SOUND_FILES.items()
                 if v.startswith(SoundManager.MITT_DIR + "/")}
    assert mitt_keys, "expected mitt samples to be registered"
    assert not (rungs & mitt_keys), f"mitt sounds in the bat ladder: {rungs & mitt_keys}"


def test_no_sound_key_is_named_after_an_outcome():
    """Contact samples are a loudness ladder, not outcome cues.

    They were called SINGLE/DOUBLE/TRIPLE/HOMERUN, which became wrong once
    selection moved to exit velocity — 'double' plays on any ~95 mph ball
    whatever the result. Guard against the naming creeping back.
    """
    outcome_words = {"single", "double", "triple", "homerun", "home_run",
                     "foul", "foulball", "out", "outside", "strikeout"}
    offenders = [k for k in SoundManager.SOUND_FILES if k.lower() in outcome_words]
    assert not offenders, f"outcome-named sound keys: {offenders}"
