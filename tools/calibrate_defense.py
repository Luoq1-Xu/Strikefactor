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

`--by-ev` breaks one shape's errors down by exit velocity; `MISPLAY_HOP_GAIN`
is the dial for how they split between soft and hard contact. Errors are rare,
so read it at n=10000 (about 75 s per level).

The HR column is read off the *fence verdict*, not off the animation.
`sim.ball_in_play` forces `IN_PLAY` — the home run is decided upstream, in
`HitOutcomeManager._resolve_outcome` — so a sweep here never produces one as
an outcome, and for a long time there was deliberately no column. What made
one necessary is that a ball the verdict calls gone still gets *flown*: to a
landing clamped inside the fence, under a hang time long enough for the
outfielder to be there, and so it came out a fly out. About 2% of fair
contact, scored as the defense's doing. Any change that moved the home-run
rate then read as a change to the fielding — the real flight arc took FLY
hit% .086 -> .069 and 2B/1B 0.31 -> 0.27 at LEAGUE on this harness before the
column existed, and most of that was home runs being caught. `measure` now
asks `park.fence_verdict` of every finished play and sets the gone ones aside,
so BABIP is a real BABIP and HR% is what the fence says.
"""

import argparse
import collections
import sys
import time

from strikefactor.gameplay import defense as d
from strikefactor.gameplay import park
from tools import sim

HITS = ("SINGLE", "DOUBLE", "TRIPLE", "HOME RUN")
LADDER = ("sandlot", "minors", "league", "gold_glove")


def measure(level, n, seed):
    """Every rate this module reports, from one sweep."""
    profile = d.profile_for(level)
    plays = sim.sweep(profile, n, seed=seed)

    played = [p for p in plays if p.classified_outcome is not None]
    # A ball the fence verdict calls gone is a home run, whatever the
    # animation did with it. The harness forces `IN_PLAY` (the home run is
    # decided upstream, in `HitOutcomeManager`), so without this every ball
    # that would have left the park is flown to a landing clamped inside the
    # fence and caught there — which counted about 2% of fair contact as fly
    # outs, depressed FLY hit% and 2B/1B, and made a change that moved the
    # home-run rate read as a change to the *fielding*. Read off the play
    # after the fact, so the RNG stream and every memoized sweep are exactly
    # what they were.
    gone = [p for p in played if park.fence_verdict(
        p.launch_deg, p.exit_velocity_mph, p.spray_field_rad) == park.OUT_OF_PARK]
    hr = len(gone)
    live = [p for p in played if p not in gone]
    outcomes = collections.Counter(p.classified_outcome for p in live)
    misplays = collections.Counter(p._misplay_kind for p in plays
                                   if p._misplay_kind is not None)

    hits = sum(outcomes[o] for o in HITS)
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
        "hr_pct": 100.0 * hr / max(1, bip + hr),
        "babip": hits / max(1, bip),
        "error_pct": 100.0 * outcomes["REACHED ON ERROR"] / max(1, bip),
        "gb_hit_pct": 100.0 * gb_hits / max(1, len(grounders)),
        "if_hit_pct": 100.0 * infield_hits / max(1, len(infield)),
        "xbh_ratio": outcomes["DOUBLE"] / max(1, outcomes["SINGLE"]),
        "bobble": misplays["BOBBLE"],
        "through": misplays["THROUGH"],
        "muff": misplays["MUFF"],
        "misplay_pct": 100.0 * sum(misplays.values()) / max(1, len(plays)),
        "by_shape": _by_shape(live),
        "live": live,
    }


# The shapes, in the order `ball_flight`'s launch bands run.
SHAPES = ("GROUNDER", "LINER", "FLY", "POP_UP")


def _by_shape(live):
    """Hit rate and error rate per batted-ball shape, off the same sweep.

    CLAUDE.md quotes these four numbers in several places and this harness
    could not produce one of them — they were measured by hand off
    `sim.sweep`, which is exactly the complaint this module was written to
    answer. A shape is the one axis that is *independent* of the fielding
    model, because `hit_outcome_manager` classifies it at contact, so it is
    the axis that says which part of the model a change actually moved.
    """
    rows = {}
    for shape in SHAPES:
        plays = [p for p in live if p.shape == shape]
        hits = sum(1 for p in plays if p.classified_outcome in HITS)
        errs = sum(1 for p in plays
                   if p.classified_outcome == "REACHED ON ERROR")
        rows[shape] = {
            "n": len(plays),
            "hit_rate": hits / max(1, len(plays)),
            "err_pct": 100.0 * errs / max(1, len(plays)),
        }
    return rows


# Exit-velocity buckets for `--by-ev`, in mph. 95 is Statcast's hard-hit line;
# the others split the ground-ball mass roughly evenly.
EV_BUCKETS = ((0, 70), (70, 80), (80, 88), (88, 95), (95, 102), (102, None))


def _by_ev(live, shape):
    """How the error rate of one shape is built, per exit-velocity bucket.

    The error rate per ball is three factors, and they do not move together:
    how often a fielder reaches the ball at all, how often a reached ball is
    misplayed, and how often a misplay is scored an error rather than a hit.
    On ground balls the first falls with exit velocity (the hardest are past
    the infield before anyone gets there) while the other two rise, so the
    per-ball rate on its own cannot say whether a change to the hop term did
    what it meant to.

    `Model p%` is `defense.misplay_prob` averaged over the balls reached, as
    the animation rolled it (`_misplay_p`). It carries none of the draw's
    noise, so it is the column to read for the shape of the per-reach curve;
    `Misp/reach%` is the same thing realised, and should sit near it.

    "Reached" means a misplay was rolled, which happens only when a fielder
    gets to the ball before it stops (`_check_in_flight_intercept`).

    Errors are rare enough that a bucket holds a handful per level at n=2500;
    read this at n>=10000.
    """
    rows = []
    for lo, hi in EV_BUCKETS:
        plays = [p for p in live if p.shape == shape
                 and lo <= p.exit_velocity_mph and (hi is None or p.exit_velocity_mph < hi)]
        reached = [p for p in plays if p._misplay_rolled]
        misplayed = [p for p in reached if p._misplay_kind is not None]
        model_p = [p._misplay_p for p in reached if p._misplay_p is not None]
        errs = sum(1 for p in plays if p.classified_outcome == "REACHED ON ERROR")
        hits = sum(1 for p in plays if p.classified_outcome in HITS)
        rows.append({
            "bucket": f"{lo}-{hi}" if hi is not None else f"{lo}+",
            "n": len(plays),
            "reach_pct": 100.0 * len(reached) / max(1, len(plays)),
            "model_p_pct": 100.0 * sum(model_p) / max(1, len(model_p)),
            "misplay_per_reach_pct": 100.0 * len(misplayed) / max(1, len(reached)),
            "err_per_misplay_pct": 100.0 * errs / max(1, len(misplayed)),
            "err_pct": 100.0 * errs / max(1, len(plays)),
            "hit_pct": 100.0 * hits / max(1, len(plays)),
        })
    return rows


def _print_by_ev(rows, shape):
    print(f"\n{shape} by exit velocity (mph)")
    head = (f"{'LEVEL':<11}  {'EV':>7}  {'n':>5}  {'Reach%':>7}  {'Model p%':>8}  {'Misp/reach%':>11}  "
            f"{'Err/misp%':>9}  {'ERR%':>6}  {'Hit%':>6}")
    print(head)
    print("-" * len(head))
    for row in rows:
        for b in _by_ev(row["live"], shape):
            print(f"{row['level']:<11}  {b['bucket']:>7}  {b['n']:>5}  {b['reach_pct']:>7.1f}  "
                  f"{b['model_p_pct']:>8.2f}  "
                  f"{b['misplay_per_reach_pct']:>11.2f}  {b['err_per_misplay_pct']:>9.0f}  "
                  f"{b['err_pct']:>6.2f}  {b['hit_pct']:>6.1f}")
        print()


_COLUMNS = (
    ("BIP", "bip", "{:>6d}"),
    ("HR%", "hr_pct", "{:>6.2f}"),
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
    ap.add_argument("--by-shape", action="store_true",
                    help="also break hits and errors down by batted-ball shape")
    ap.add_argument("--by-ev", nargs="?", const="GROUNDER", choices=SHAPES,
                    metavar="SHAPE",
                    help="also break one shape's errors down by exit velocity "
                         "(default GROUNDER; use n>=10000)")
    args = ap.parse_args(argv)

    sim.init_headless()
    levels = args.level or list(LADDER)

    print(f"n={args.n} per level, seed={args.seed}\n")
    print(_header())
    print("-" * len(_header()))
    rows = []
    for level in levels:
        started = time.time()
        row = measure(level, args.n, args.seed)
        rows.append(row)
        print(_row(row) + f"   ({time.time() - started:.1f}s)")

    if args.by_shape:
        head = "  ".join(["%-11s" % "LEVEL"]
                         + ["%-22s" % s for s in SHAPES])
        print("\n" + head)
        print("-" * len(head))
        for row in rows:
            cells = []
            for shape in SHAPES:
                r = row["by_shape"][shape]
                cells.append("%-22s" % ("%.3f hit  %.2f%% err"
                                        % (r["hit_rate"], r["err_pct"])))
            print("  ".join(["%-11s" % row["level"]] + cells))
        print("\nMLB per-shape hit rate:  GROUNDER ~.24   LINER ~.68   "
              "FLY ~.12   POP_UP ~.02")
    if args.by_ev:
        _print_by_ev(rows, args.by_ev)
    # Same figures docs/defense-strength.md sources against, so the harness
    # and the document cannot quote different targets at each other.
    print("\nMLB reference:  HR% ~4.5-5 of fair contact   BABIP ~.290   "
          "ERR% ~1.5   GB-hit% ~24   IF-hit% 6-8   2B/1B ~0.33")
    return 0


if __name__ == "__main__":
    sys.exit(main())
