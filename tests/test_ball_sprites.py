"""The ball's spin animation plays its frames in order.

`os.listdir` returns names in an arbitrary order — hash order on APFS — and
the loader used it as-is, so the 160-frame spin played scrambled.
"""

from strikefactor.config import get_path
from strikefactor.main import AssetManager


def test_ball_frames_load_in_numeric_order_and_only_images(tmp_path):
    for name in ("frame_003.png", "frame_001.png", ".DS_Store", "frame_002.png", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    assert AssetManager.ball_frame_files(str(tmp_path)) == [
        "frame_001.png", "frame_002.png", "frame_003.png"]


def test_the_shipped_frames_sort_into_playback_order():
    frames = AssetManager.ball_frame_files(get_path("assets/images/ball"))
    assert len(frames) == 160
    numbers = [int(name.rsplit("_", 1)[1].split(".")[0]) for name in frames]
    assert numbers == list(range(1, 161))
