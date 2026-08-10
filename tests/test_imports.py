"""Import smoke tests.

These exist to make the package structure itself a tested property: before the
Phase 0 repackaging, `import strikefactor.main` was impossible from anywhere,
which is what kept the codebase untestable. If someone reintroduces a
script-relative import, these fail immediately.
"""

import importlib
import pkgutil

import pytest

import strikefactor

# Modules that must not pull in heavy or on-disk resources merely by being
# imported. See test_no_import_time_model_load.
LAZY_MODULES = ["strikefactor.gameplay.pitch_simulation"]


def _all_module_names():
    names = []
    for info in pkgutil.walk_packages(strikefactor.__path__, prefix="strikefactor."):
        # __main__ would execute the game loop guard; skip it.
        if info.name.endswith(".__main__"):
            continue
        names.append(info.name)
    return sorted(names)


@pytest.mark.parametrize("module_name", _all_module_names())
def test_module_imports(module_name):
    """Every module in the package imports cleanly."""
    importlib.import_module(module_name)


def test_package_has_expected_subpackages():
    """Guard against a subpackage losing its __init__.py."""
    for sub in ["ai", "data", "engine", "gameplay", "pitchers", "ui", "utils"]:
        importlib.import_module(f"strikefactor.{sub}")


def test_no_import_time_model_load(monkeypatch):
    """Importing gameplay modules must not read the umpire pickle from disk.

    The model used to be unpickled at module scope, so importing anything under
    gameplay required both the .pkl file and scikit-learn. Keeping it lazy is
    what lets these tests run at all.
    """
    import builtins

    real_open = builtins.open
    opened = []

    def tracking_open(path, *args, **kwargs):
        opened.append(str(path))
        return real_open(path, *args, **kwargs)

    for name in LAZY_MODULES:
        # Force a genuine re-import so module-level code runs again.
        import sys

        sys.modules.pop(name, None)
        monkeypatch.setattr(builtins, "open", tracking_open)
        importlib.import_module(name)
        monkeypatch.undo()

    assert not [p for p in opened if p.endswith(".pkl")], (
        f"a .pkl was read at import time: {opened}"
    )
