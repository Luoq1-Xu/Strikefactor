"""Backward-compatible unpickling for the trained pitch-selection Q-tables.

A pickle stores the fully-qualified module path of every class it references,
as that path was at dump time. The module holding ``ERAI`` has now moved twice:

    ``AI_2``                 - original, a loose script on ``sys.path``
    ``ai.AI_2``              - once ``strikefactor/`` was the script directory
    ``strikefactor.ai.AI_2`` - current, now that ``strikefactor`` is a package

The committed ``*_ai.pkl`` files were written under the second path and hold
thousands of trained Q-values each. They must keep loading: ``load_ai`` falls
back to a *fresh* ``ERAI`` when a load fails, so a path mismatch would not
raise — it would silently throw the training away.

Saving always writes the current path, so files re-saved by the game migrate
forward on their own.
"""

import pickle

# Legacy module path -> current module path.
_MODULE_ALIASES = {
    "AI_2": "strikefactor.ai.AI_2",
    "ai.AI_2": "strikefactor.ai.AI_2",
    "ai.batter_profile": "strikefactor.ai.batter_profile",
}


class _CompatUnpickler(pickle.Unpickler):
    """Unpickler that redirects pre-package module paths to their new homes."""

    def find_class(self, module, name):
        return super().find_class(_MODULE_ALIASES.get(module, module), name)


def loads(data: bytes):
    """Unpickle ``data``, remapping legacy StrikeFactor module paths."""
    import io

    return _CompatUnpickler(io.BytesIO(data)).load()


def load(file):
    """Unpickle from a binary file object, remapping legacy module paths."""
    return _CompatUnpickler(file).load()


def load_path(path):
    """Unpickle the file at ``path``, remapping legacy module paths."""
    with open(path, "rb") as f:
        return load(f)
