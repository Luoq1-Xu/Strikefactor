"""Guards for the background warm-up of pandas / scikit-learn.

The point of prewarm is that the ~880 ms of one-time imports behind the first
pitch happen off the main thread, before the ball is in the air. These tests
pin the two properties that make that true: it doesn't block the caller, and it
can't race a real ``get_umpire_model()`` call into loading the SVC twice.
"""

import threading
import time

import pytest

from strikefactor.gameplay import prewarm


@pytest.fixture(autouse=True)
def _reset_prewarm_thread():
    """Each test starts its own warm-up thread."""
    prewarm._prewarm_thread = None
    yield
    prewarm._prewarm_thread = None


def test_prewarm_does_not_block_caller():
    start = time.perf_counter()
    thread = prewarm.prewarm_gameplay()
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Spawning a thread is microseconds; the load itself is ~700 ms. Anything
    # near the latter means the work landed on the calling thread.
    assert elapsed_ms < 100, f"prewarm blocked the caller for {elapsed_ms:.0f} ms"
    thread.join(timeout=30)
    assert not thread.is_alive()


def test_prewarm_is_idempotent():
    first = prewarm.prewarm_gameplay()
    assert prewarm.prewarm_gameplay() is first
    first.join(timeout=30)


def test_prewarm_thread_is_daemon():
    """A stuck import must never hold the process open on quit."""
    thread = prewarm.prewarm_gameplay()
    assert thread.daemon
    thread.join(timeout=30)


def test_umpire_model_loads_once_under_concurrent_access():
    """A pitch resolving mid-warm-up waits for the in-flight load, not a second one."""
    from strikefactor.gameplay import pitch_simulation as ps

    ps._umpire_model = None
    try:
        loads = []
        real_open = open

        def counting_open(path, *args, **kwargs):
            if "ai_umpire" in str(path):
                loads.append(path)
            return real_open(path, *args, **kwargs)

        import builtins

        builtins.open = counting_open
        try:
            models = []
            threads = [
                threading.Thread(target=lambda: models.append(ps.get_umpire_model()))
                for _ in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
        finally:
            builtins.open = real_open

        assert len(loads) == 1, f"SVC pickle was loaded {len(loads)} times"
        assert len(models) == 8
        assert all(m is models[0] for m in models)
    finally:
        ps._umpire_model = None


def test_prewarm_survives_a_broken_model(monkeypatch, capsys):
    """Warm-up is an optimization — a failure must not break startup.

    ``_load_gameplay_modules`` imports the accessor inside the function body,
    so it picks up the patched attribute at call time.
    """
    from strikefactor.gameplay import pitch_simulation as ps

    def boom():
        raise FileNotFoundError("ai_umpire.pkl")

    monkeypatch.setattr(ps, "get_umpire_model", boom)

    prewarm._load_gameplay_modules()  # must not raise

    assert "Prewarm skipped" in capsys.readouterr().out
