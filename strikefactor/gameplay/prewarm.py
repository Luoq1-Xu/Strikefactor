"""Background warm-up for the heavyweight gameplay imports.

Two costs used to land in the middle of the first pitch of a session:

* ``gameplay.pitch_simulation`` is imported lazily by ``GameplayState.
  _create_pitch_simulation``, and imports pandas at module level (~200 ms).
  That fires at release.
* ``pitch_simulation.get_umpire_model`` unpickles an SVC, which triggers the
  process's first ``import sklearn`` (~680 ms). That fires on the first frame
  past plate arrival — as a freeze partway through the swing animation, on a
  whiff.

Both are one-time process costs that nothing about them needs to happen at
that moment, so this module does them on a daemon thread while the player is
still in the menus. Nothing here touches pygame, so it is safe off the main
thread.

Deliberately kept free of module-level imports of either module: ``main``
imports *this*, and pulling pandas in at import time would just move the stall
back onto the startup path instead of off it.
"""

import threading

_prewarm_thread = None


def _load_gameplay_modules():
    """Import pandas + scikit-learn and build the umpire model."""
    try:
        # Imports pandas as a side effect of the module-level import.
        from strikefactor.gameplay.pitch_simulation import get_umpire_model

        # Unpickling the SVC is what actually pulls in scikit-learn.
        get_umpire_model()
    except Exception as exc:
        # Never let warm-up break startup. If the model can't be loaded here
        # it will be retried inline on the first call, exactly as before —
        # this is an optimization, not a prerequisite.
        print(f"Prewarm skipped ({type(exc).__name__}: {exc})")


def prewarm_gameplay(block=False):
    """Start loading the gameplay-critical modules in the background.

    Idempotent: repeated calls reuse the one thread. Pass ``block=True`` to
    wait for it (used by tests; the game never needs to).
    """
    global _prewarm_thread
    if _prewarm_thread is None:
        _prewarm_thread = threading.Thread(
            target=_load_gameplay_modules,
            name="strikefactor-prewarm",
            daemon=True,
        )
        _prewarm_thread.start()
    if block:
        _prewarm_thread.join()
    return _prewarm_thread
