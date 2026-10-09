"""Small filesystem helpers shared across persistence modules."""

import json
import os
import tempfile


def atomic_write_json(path, data, indent=2):
    """Write ``data`` as JSON to ``path`` atomically.

    The payload is written to a temporary file in the same directory and then
    swapped into place with ``os.replace`` (atomic on POSIX and Windows). This
    prevents a crash / full disk mid-write from truncating the live file, which
    would otherwise leave the readers to silently fall back to defaults and
    permanently discard saved data.

    Returns True on success, False on failure (errors are swallowed so a save
    failure never crashes the game; callers already treat persistence as
    best-effort).
    """
    directory = os.path.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=directory)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=indent)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            return True
        except Exception:
            # Clean up the partial temp file; never leave litter behind.
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        print(f"Failed to write {path}: {e}")
        return False
