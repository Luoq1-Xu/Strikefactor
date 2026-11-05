"""Play the model player's fouls out and report what became of them.

    python -m tools.calibrate_fouls --n 13000 --hand both --jobs 4

The third harness, after `calibrate_contact` (what the bat produces) and
`calibrate_defense` (what the fielders do with a fair ball). This one takes
every swing `calibrate_contact` grades a foul, flies it through `HitAnimation`
exactly as the game does — the same departure bearing, launch angle and exit
velocity — and counts where it ended: on the ground, in the net, in the seats,
or down where a fielder could reach it, and then caught, dropped or fallen.

**The target is the caught share.** MLB had about 1.4 foul outs a game in 2019
against about 54 foul balls a game, so roughly 2.5% of fouls are caught. The
levers, in the order to reach for them, are the size of foul ground
(`park.FOUL_GROUND_AT_POLE_FT`; `park.BACKSTOP_FT` is pinned to the bottom of
the screen), the catcher's range and read on a pop-up
(`hit_animation.CATCHER_FOUL_RANGE_FT`, `CATCHER_MASK_OFF_S`), and the pop
deflection band (`spray.FOUL_POP_BACK_DEG`). Not a second flight model.

Every play is a function of `(seed, index)`, like the contact harness, so a
longer run is a superset of a shorter one and `--jobs` changes no number.
"""

import argparse
import collections
import math
import random
import sys
import time
from multiprocessing import Pool
from types import SimpleNamespace

from tools import calibrate_contact as contact

# MLB 2019: 3,355 foul outs over 2,429 games, against ~54 fouls a game.
TARGET_CAUGHT_SHARE = 0.025


def _play_foul(args):
    """Swing `index` and, if it was fouled off, what became of the foul."""
    seed, index, hand, level = args
    swing = contact.swing_once((seed, index, hand, level, False, (), None))
    if swing.verdict != 1:
        return None
    from strikefactor.engine import contact_audio
    from strikefactor.gameplay import hit_animation as ha
    from strikefactor.gameplay import spray

    rng = random.Random(seed * 7_368_787 + index)
    c = swing.contact
    random.seed(rng.random())
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: hand),
                           currentouts=0, game_mode="arcade")
    anim = ha.HitAnimation(
        game, "FOUL", lambda: None, quality=c.quality,
        batted_ball_type=swing.shape,
        spray_deg=spray.foul_departure_deg(c.spray_deg, c.quality, swing.shape),
        ev_mph=contact_audio.exit_velocity_mph(c.quality, "contact", rng=rng),
        launch_deg=swing.launch_deg,
        timing_turn_deg=c.attack_deg - c.pose_attack_deg,
        initial_bases=())
    t = 0
    while not anim.finished and t < 30000:
        anim.update(t)
        t += 16
    return (swing.shape, anim.foul_result, anim.fielder_role, t / 1000.0)


def run(n, seed=17, hand="R", level="amateur", jobs=1):
    work = [(seed, i, hand, level) for i in range(n)]
    if jobs <= 1:
        plays = [_play_foul(w) for w in work]
    else:
        with Pool(jobs, initializer=_headless) as pool:
            plays = pool.map(_play_foul, work, chunksize=max(1, n // (jobs * 8)))
    return [p for p in plays if p is not None]


def _headless():
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


def report(plays, label):
    n = len(plays)
    by_result = collections.Counter(p[1] for p in plays)
    caught = by_result.get("CAUGHT", 0)
    sd = math.sqrt(max(caught, 1)) / max(n, 1)
    print(f"\n{label}: {n} fouls")
    for result, count in by_result.most_common():
        lengths = sorted(p[3] for p in plays if p[1] == result)
        print(f"  {result:9} {count / n:6.1%}   play p50 {lengths[len(lengths) // 2]:.2f} s")
    print(f"  caught share {caught / max(n, 1):.2%} +/- {sd:.2%}   "
          f"(MLB ~{TARGET_CAUGHT_SHARE:.1%})")
    by_shape = collections.defaultdict(collections.Counter)
    for shape, result, _, _ in plays:
        by_shape[shape][result] += 1
    for shape, counts in sorted(by_shape.items()):
        total = sum(counts.values())
        print(f"  {shape:9} " + "  ".join(
            f"{r} {c / total:.0%}" for r, c in counts.most_common()))
    catchers = collections.Counter(p[2] for p in plays if p[1] == "CAUGHT")
    if catchers:
        print("  caught by  " + "  ".join(f"{r} {c}" for r, c in catchers.most_common()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=13000, help="swings (about 31%% foul)")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--hand", choices=("R", "L", "both"), default="both")
    ap.add_argument("--level", choices=sorted(contact.LEVELS), default="amateur")
    ap.add_argument("--jobs", type=int, default=1)
    args = ap.parse_args(argv)
    _headless()
    for hand in (("R", "L") if args.hand == "both" else (args.hand,)):
        started = time.time()
        report(run(args.n, args.seed, hand, args.level, args.jobs), f"{hand}HB")
        print(f"  ({time.time() - started:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
