"""Guards for the trained pitch-selection Q-tables.

The committed ``*_ai.pkl`` files are training output, not source — they cannot
be regenerated from the repo. They also fail *silently*: `_load_ai` falls back
to a fresh ERAI on any load error, so a broken load shows up as an AI that has
simply forgotten everything, not as a crash.

These tests assert the files still load and still contain real training, which
is what makes it safe to keep moving modules around in later refactor phases.
"""

import pickle

import pytest

from strikefactor.ai import compat as ai_compat
from strikefactor.ai.AI_2 import ERAI
from strikefactor.config import get_path

# Pitcher -> arsenal, as committed. A mismatch here means the game would
# discard the saved Q-table and start that pitcher from scratch.
EXPECTED_ACTIONS = {
    "sale": {"FF", "SL", "CH", "SI"},
    "degrom": {"FF", "SL", "CB", "CH"},
    "yamamoto": {"FF", "FS", "CB", "FC", "SI"},
    "sasaki": {"FF", "FS", "SL"},
    "mcclanahan": {"FF", "SL", "CB", "CH"},
}


@pytest.mark.parametrize("name", sorted(EXPECTED_ACTIONS))
def test_ai_pickle_loads(name):
    """Each committed Q-table unpickles through the compat shim."""
    ai = ai_compat.load_path(get_path(f"ai/{name}_ai.pkl"))
    assert isinstance(ai, ERAI)


@pytest.mark.parametrize("name", sorted(EXPECTED_ACTIONS))
def test_ai_pickle_actions_match_arsenal(name):
    """Action set matches the pitcher's arsenal, so the game keeps the file."""
    ai = ai_compat.load_path(get_path(f"ai/{name}_ai.pkl"))
    assert set(ai.actions) == EXPECTED_ACTIONS[name]


@pytest.mark.parametrize("name", sorted(EXPECTED_ACTIONS))
def test_ai_pickle_retains_training(name):
    """The Q-table is non-trivial — i.e. training was not silently discarded."""
    ai = ai_compat.load_path(get_path(f"ai/{name}_ai.pkl"))
    assert len(ai.q) > 100, f"{name} has only {len(ai.q)} Q-values"


def _pickle_under_module_path(obj, module_path: str) -> bytes:
    """Dump ``obj`` as if its class had lived at ``module_path``.

    Protocol 2's GLOBAL opcode stores the module path as plain newline-
    terminated text with no frame length prefix, so it can be rewritten
    byte-for-byte. (Protocol 4+ wraps the stream in a length-prefixed FRAME,
    where the same edit would truncate the pickle.)
    """
    data = pickle.dumps(obj, protocol=2)
    current = b"cstrikefactor.ai.AI_2\n"
    assert current in data, "ERAI is no longer where this helper expects it"
    return data.replace(current, f"c{module_path}\n".encode())


@pytest.mark.parametrize("legacy_path", ["AI_2", "ai.AI_2"])
def test_compat_loads_pickles_written_under_legacy_paths(legacy_path):
    """A Q-table saved under a pre-package module path still loads.

    Deliberately does not assert which path the *committed* files carry: the
    game re-saves them under the current path on every clean exit, so their
    recorded path migrates forward on its own. What must stay true is that the
    older paths keep resolving, for files saved by an older build.
    """
    legacy = _pickle_under_module_path(ERAI(["FF", "SL"]), legacy_path)

    with pytest.raises(ModuleNotFoundError):
        # Plain pickle cannot resolve the legacy path any more...
        pickle.loads(legacy)

    # ...but the compat unpickler can.
    restored = ai_compat.loads(legacy)
    assert isinstance(restored, ERAI)
    assert set(restored.actions) == {"FF", "SL"}


def test_compat_still_loads_current_module_path():
    """Freshly-saved files load through the same code path."""
    restored = ai_compat.loads(pickle.dumps(ERAI(["FF", "SL"])))
    assert isinstance(restored, ERAI)
    assert set(restored.actions) == {"FF", "SL"}


def test_umpire_model_loads_lazily_and_predicts():
    """The SVC umpire model is still readable through the lazy accessor."""
    import pandas as pd

    from strikefactor.gameplay.pitch_simulation import get_umpire_model

    model = get_umpire_model()
    pred = model.predict(pd.DataFrame([[630, 485]], columns=["finalx", "finaly"]))
    assert len(pred) == 1
