"""Sweep the defense ladder and report the rates it is calibrated against.

    python -m tools.calibrate_defense --n 2500

This is the harness `docs/defense-strength.md` refers to. It exists so that
every number quoted in that document and in `tests/test_defense.py`'s
docstrings can be re-derived rather than taken on trust, and so that changing
a constant means measuring the change rather than guessing at it.

The bands in the test suite are deliberately *wider* than these numbers: a
test has to pass at a sample size a test can afford, and adjacent rungs of the
ladder sit inside each other's noise at n=260. Use this at n>=2500 when
tuning; use the suite to catch a regression.

Targets, for reading the output against something:

    errors / BIP         MLB ~1.5%          field_misplay_p is the dial
    ground-ball hits     MLB ~24%           body_block is the dial
    infield hits         MLB 6-8%           of ground balls
    BABIP                MLB ~.290          the ladder is meant to straddle it
    2B / 1B              MLB ~0.33

There is deliberately no HR column. `sim.ball_in_play` forces `IN_PLAY`, and
the home-run roll happens *upstream* of the animation in
`HitOutcomeManager._resolve_outcome` — so a sweep here can never produce one
and a column for it would read as a flat zero rather than as "not measured
by this instrument". BABIP already excludes home runs from both halves.
"""

import argparse
import collections
import sys
import time

from strikefactor.gameplay import defense as d
from tools import sim

HITS = ("SINGLE", "DOUBLE", "TRIPLE", "HOME RUN")
LADDER = ("sandlot", "minors", "league", "gold_glove")


def measure(level, n, seed):
    """Every rate this module reports, from one sweep."""
    profile = d.profile_for(level)
    plays = sim.sweep(profile, n, seed=seed)

    live = [p for p in plays if p.classified_outcome is not None]
    outcomes = collections.Counter(p.classified_outcome for p in live)
    misplays = collections.Counter(p._misplay_kind for p in plays
                                   if p._misplay_kind is not None)

    hits = sum(outcomes[o] for o in HITS)
    hr = outcomes["HOME RUN"]
    bip = len(live)

    grounders = [p for p in live if p.shape == "GROUNDER"]
    gb_hits = sum(1 for p in grounders if p.classified_outcome in HITS)
    # An infield hit is a ground ball the *infield* got to and the runner beat
    # anyway — a race lost, not a ball that got through. `play_timing` is set
    # exactly when that race ran, which is what makes this the right test
    # rather than "a single on a grounder".
    infield = [p for p in grounders if p.play_timing is not None]
    infield_hits = sum(1 for p in infield if p.classified_outcome in HITS)

    return {
        "level": level,
        "bip": bip,
        "babip": (hits - hr) / max(1, bip - hr),
        "error_pct": 100.0 * outcomes["REACHED ON ERROR"] / max(1, bip),
        "gb_hit_pct": 100.0 * gb_hits / max(1, len(grounders)),
        "if_hit_pct": 100.0 * infield_hits / max(1, len(infield)),
        "xbh_ratio": outcomes["DOUBLE"] / max(1, outcomes["SINGLE"]),
        "bobble": misplays["BOBBLE"],
        "through": misplays["THROUGH"],
        "muff": misplays["MUFF"],
        "misplay_pct": 100.0 * sum(misplays.values()) / max(1, len(plays)),
    }


_COLUMNS = (
    ("BIP", "bip", "{:>6d}"),
    ("BABIP", "babip", "{:>7.3f}"),
    ("ERR%", "error_pct", "{:>7.2f}"),
    ("GB-hit%", "gb_hit_pct", "{:>8.1f}"),
    ("IF-hit%", "if_hit_pct", "{:>8.1f}"),
    ("2B/1B", "xbh_ratio", "{:>6.2f}"),
    ("Misp%", "misplay_pct", "{:>6.2f}"),
    ("BOB", "bobble", "{:>5d}"),
    ("THR", "through", "{:>5d}"),
    ("MUF", "muff", "{:>5d}"),
)


def _header():
    return "  ".join(["%-11s" % "LEVEL"]
                     + [f"{name:>{len(fmt.format(0) if 'd' in fmt else fmt.format(0.0))}}"
                        for name, _, fmt in _COLUMNS])


def _row(r):
    return "  ".join(["%-11s" % r["level"]]
                     + [fmt.format(r[key]) for _, key, fmt in _COLUMNS])


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Sweep the defense ladder and report calibration rates.")
    ap.add_argument("--n", type=int, default=1200,
                    help="balls in play per level (use >=2500 when tuning)")
    ap.add_argument("--seed", type=int, default=808,
                    help="sweep seed; shared with tests/test_defense.py")
    ap.add_argument("--level", choices=LADDER, action="append",
                    help="only this level (repeatable); default is all four")
    args = ap.parse_args(argv)

    sim.init_headless()
    levels = args.level or list(LADDER)

    print(f"n={args.n} per level, seed={args.seed}\n")
    print(_header())
    print("-" * len(_header()))
    for level in levels:
        started = time.time()
        row = measure(level, args.n, args.seed)
        print(_row(row) + f"   ({time.time() - started:.1f}s)")
    # Same figures docs/defense-strength.md sources against, so the harness
    # and the document cannot quote different targets at each other.
    print("\nMLB reference:  BABIP ~.290   ERR% ~1.5   GB-hit% ~24   "
          "IF-hit% 6-8   2B/1B ~0.33")
    return 0


if __name__ == "__main__":
    sys.exit(main())
