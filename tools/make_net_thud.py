"""Synthesize the backstop-net thud: strikefactor/assets/sounds/net/thud.mp3.

    python -m tools.make_net_thud [--out PATH] [--wav PATH]

The game had no recording of a ball hitting a net, so this one is built from
three pieces of what that sounds like:

  * **the body** — a low thump, the netting bellying back and springing out:
    a sine falling from about 220 Hz to 110 Hz over a few tens of
    milliseconds, gone in a quarter of a second. Not lower: laptop speakers
    give up below about 150 Hz, and a thud an octave down was mostly silence
    on them;
  * **the impact** — a very short burst of mid-band noise, the ball meeting
    the mesh;
  * **the rustle** — a quieter, longer wash of high noise with a slight
    flutter, the net settling.

No crack and no slap: it has to read as softer than any bat or glove sound
in `assets/sounds/`. The noise is seeded, so a run reproduces the same samples
every time; tune the numbers below and re-run to change it, or drop a
recording in at the same path to replace it outright.

Needs `ffmpeg` with libmp3lame on PATH to encode — a development tool, like
the rest of `tools/`; the game only ever reads the finished file.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100        # what every other sample in assets/sounds is
DURATION_S = 0.45
PEAK_DBFS = -6.0
SEED = 7

OUT_PATH = Path(__file__).resolve().parent.parent / "strikefactor" / "assets" / "sounds" / "net" / "thud.mp3"


def _band(noise, lo_hz, hi_hz):
    """`noise` band-limited to lo-hi Hz, with soft edges (FFT mask)."""
    spectrum = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(noise.size, 1.0 / SAMPLE_RATE)
    edge = 0.25
    mask = (1.0 / (1.0 + np.exp(-(freqs - lo_hz) / (edge * lo_hz)))
            * 1.0 / (1.0 + np.exp((freqs - hi_hz) / (edge * hi_hz))))
    out = np.fft.irfft(spectrum * mask, n=noise.size)
    return out / (np.max(np.abs(out)) or 1.0)


def synthesize(seed=SEED):
    """The thud, as float samples in [-1, 1], mono."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(SAMPLE_RATE * DURATION_S)) / SAMPLE_RATE
    attack = 1.0 - np.exp(-t / 0.0025)

    pitch_hz = 110.0 + 110.0 * np.exp(-t / 0.03)
    phase = 2.0 * np.pi * np.cumsum(pitch_hz) / SAMPLE_RATE
    # A quieter octave on top, so a speaker that cannot play the thump itself
    # still plays its outline, and the ear fills the low note back in.
    body = np.sin(phase) + 0.35 * np.sin(2.0 * phase)
    body *= attack * np.exp(-t / 0.07)

    impact = _band(rng.standard_normal(t.size), 400.0, 3000.0)
    impact *= attack * np.exp(-t / 0.012)

    rustle = _band(rng.standard_normal(t.size), 1500.0, 6000.0)
    rustle *= np.exp(-t / 0.09) * (0.6 + 0.4 * np.sin(2.0 * np.pi * 23.0 * t))

    mix = 1.0 * body + 0.6 * impact + 0.15 * rustle
    fade = min(t.size, int(0.02 * SAMPLE_RATE))
    mix[-fade:] *= np.linspace(1.0, 0.0, fade)
    return mix / np.max(np.abs(mix)) * 10.0 ** (PEAK_DBFS / 20.0)


def write_wav(samples, path):
    """16-bit stereo WAV, the same channel layout as the other samples."""
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(stereo.tobytes())


def encode_mp3(wav_path, mp3_path):
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is needed to encode the mp3 (or pass --wav only)")
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(wav_path), "-codec:a", "libmp3lame", "-b:a", "128k",
                    "-map_metadata", "-1", "-fflags", "+bitexact",
                    str(mp3_path)], check=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT_PATH, help="mp3 to write")
    ap.add_argument("--wav", type=Path, default=None,
                    help="also keep the uncompressed WAV here, for listening")
    args = ap.parse_args(argv)
    samples = synthesize()
    with tempfile.TemporaryDirectory() as tmp:
        wav = args.wav or Path(tmp) / "thud.wav"
        write_wav(samples, wav)
        encode_mp3(wav, args.out)
    print(f"wrote {args.out} ({DURATION_S:.2f} s, peak {PEAK_DBFS:.0f} dBFS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
