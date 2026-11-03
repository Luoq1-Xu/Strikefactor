"""Swing a plausible player through the real contact seam and report what the
bat produces.

    python -m tools.calibrate_contact --n 13000

The companion to `tools/calibrate_defense.py`, one stage upstream of it. That
harness takes a batted ball as given and measures the fielding; this one
measures the batted ball — whether the bat found the pitch, whether the result
was fair, how squarely it was struck, and which way it left.

It exists for the reason that one does. Every anchor CLAUDE.md's rule 5 lists
(`contact_audio.EV_CALIBRATION`, and `QUALITY_QUANTILES`, `QUALITY_BY_SHAPE`,
`LAUNCH_ANGLE_QUANTILES`, `SPRAY_MEAN_DEG` / `SPRAY_SD_DEG` and
`BATTED_BALL_MIX` in `tools/sim.py`) was measured by a script that was never
committed, so none of them could be re-derived and a contact-geometry change
had to rebuild the instrument before it could measure anything.

**The player model is the canonical one**: aim scatter 0.75 ft per axis and
timing N(+19, 48) ms, through `bat_contact.aim_at_pitch` and
`bat_contact.resolve_contact` at the difficulty named. It is the model
`settings_manager.DIFFICULTY_MULTIPLIERS` and `EV_CALIBRATION` quote. Never
substitute a uniform sweep of quality, launch angle or spray for it — see
CLAUDE.md, rule 4.

Every swing is a function of `(seed, index)` alone, so a longer run is a
superset of a shorter one and `--jobs` cannot change a number.

A left-handed run mirrors the whole pitch (release point, break and target),
so the two hands are shown the same pitch relative to themselves and every
rate has to agree between them. That is the check on rule 9.
"""

import argparse
import importlib
import math
import random
import statistics
import sys
import time
from dataclasses import dataclass
from multiprocessing import Pool

from strikefactor.gameplay import ball_flight, spray
from strikefactor.gameplay import bat_contact as bc
from strikefactor.gameplay import bat_path as bp
from strikefactor.settings_manager import DIFFICULTY_MULTIPLIERS, DifficultyLevel
from strikefactor.utils.pitch_physics import DEFAULT_CAMERA, PitchTrajectory

# ---- The player ------------------------------------------------------------

AIM_SCATTER_FT = 0.75           # per axis, at the plate
TIMING_MEAN_MS = 19.0           # late: human reaction against a 150 ms swing
TIMING_SD_MS = 48.0

# The pitches the player is shown. Locations scatter about the middle of the
# zone, a little wider than the zone itself, across the speeds the arsenals
# throw. Stated for a right-handed batter; `_pitch` mirrors it.
RELEASE_FT = (-1.8, 54.0, 6.0)
PFX_IN = (-4.0, 14.0)
TARGET_X_SD_FT = 0.55
TARGET_Z_MEAN_FT, TARGET_Z_SD_FT = 2.5, 0.62
SPEED_MPH = (80.0, 99.0)

LEVELS = {level.value: level for level in DifficultyLevel}
SHAPES = ("GROUNDER", "LINER", "FLY", "POP_UP")

# Spray thirds. The Statcast convention splits fair territory into three equal
# 30 degree wedges.
THIRD_DEG = 15.0


def _pitch(hand, target_x, target_z, speed_mph):
    """A pitch at `target_x` *relative to this batter* (inside-positive)."""
    spin = spray.spin_for(hand)
    return PitchTrajectory.from_pitch_params(
        release_pos=(RELEASE_FT[0] * spin, RELEASE_FT[1], RELEASE_FT[2]),
        speed_mph=speed_mph,
        pfx_x_inches=PFX_IN[0] * spin, pfx_z_inches=PFX_IN[1],
        target_x_ft=target_x * spin, target_z_ft=target_z)


def _cursor_on_ball(trajectory):
    """The cursor of a player pointing exactly at the ball's plate crossing."""
    ball = trajectory.position_at(trajectory.travel_time)
    px, py, _ = DEFAULT_CAMERA.project(*ball)
    return DEFAULT_CAMERA.screen_to_world_at_plate(px, py)


@dataclass(frozen=True)
class Swing:
    """One swing by the model player, and what came of it."""

    verdict: int                # 0 whiff / 1 foul / 2 fair
    timing_ms: float            # the player's error, before any assist
    contact: object = None      # bat_contact.Contact, or None on a whiff
    launch_deg: float = None
    shape: str = None
    foul_by_quality: bool = False
    foul_by_direction: bool = False


def apply_overrides(overrides):
    """Set `module.NAME` constants for a trial run, from `--set`.

    Applied in every worker, because a worker process imports the modules
    afresh. A constant that another is derived from at import (an angle and
    its radians, say) does not carry over: set the one the code reads.
    """
    for dotted, value in overrides:
        module_name, name = dotted.rsplit(".", 1)
        module = importlib.import_module(
            f"strikefactor.gameplay.{module_name}")
        if not hasattr(module, name):
            raise SystemExit(f"--set: {module_name} has no {name}")
        setattr(module, name, value)


def swing_once(args):
    """Swing number `index` of the run named by the rest of `args`."""
    seed, index, hand, level_name, power, overrides, aim_assist = args
    apply_overrides(overrides)
    rng = random.Random(seed * 1_000_003 + index)
    mult = DIFFICULTY_MULTIPLIERS[LEVELS[level_name]]
    if aim_assist is not None:
        mult = dict(mult, aim_assist=aim_assist)
    window = mult["power_timing_window" if power else "contact_timing_window"]

    tr = _pitch(hand, rng.gauss(0.0, TARGET_X_SD_FT),
                rng.gauss(TARGET_Z_MEAN_FT, TARGET_Z_SD_FT),
                rng.uniform(*SPEED_MPH))
    cx, cz = _cursor_on_ball(tr)
    cursor = (cx + rng.gauss(0.0, AIM_SCATTER_FT),
              cz + rng.gauss(0.0, AIM_SCATTER_FT))
    aim = bc.aim_at_pitch(cursor, tr, hand, assist=mult["aim_assist"])
    swing = bp.swing(aim, hand)
    timing_ms = rng.gauss(TIMING_MEAN_MS, TIMING_SD_MS)
    start = (tr.time_at_depth(swing.contact_depth_ft) - bp.SWING_DURATION_S
             + timing_ms / 1000.0)
    contact = bc.resolve_contact(
        swing, tr, start, zone_size_mult=mult["contact_zone_size"],
        timing_window_mult=window, power=power)
    if contact is None:
        return Swing(verdict=0, timing_ms=timing_ms)

    threshold = bc.foul_threshold(window)
    by_quality = contact.quality < threshold
    by_direction = spray.is_foul(contact.spray_deg)
    launch = contact.launch_deg
    return Swing(
        verdict=1 if contact.is_foul(threshold) else 2,
        timing_ms=timing_ms, contact=contact, launch_deg=launch,
        shape=ball_flight.shape_for_launch_angle(launch),
        foul_by_quality=by_quality, foul_by_direction=by_direction)


def run(n, seed=17, hand="R", level="amateur", power=False, jobs=1,
        overrides=(), aim_assist=None):
    """`n` swings by the model player, in index order.

    `aim_assist` replaces the level's own, for sweeping that one dial.

    `overrides` are applied here as well as in each worker. A `Contact`'s
    quality is worked out when it is read, from the module's constants, and
    the reading happens in this process.
    """
    apply_overrides(overrides)
    work = [(seed, i, hand, level, power, tuple(overrides), aim_assist)
            for i in range(n)]
    if jobs <= 1:
        return [swing_once(w) for w in work]
    with Pool(jobs) as pool:
        return pool.map(swing_once, work, chunksize=max(1, n // (jobs * 8)))


# ---- Reading a run ---------------------------------------------------------

def quantile(values, p):
    """Linear-interpolated quantile of `values` at probability `p`."""
    xs = sorted(values)
    if not xs:
        return float("nan")
    pos = p * (len(xs) - 1)
    lo = int(math.floor(pos))
    hi = min(len(xs) - 1, lo + 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def summarise(swings):
    """Every rate this module reports, from one run."""
    n = len(swings)
    contacts = [s for s in swings if s.contact is not None]
    fouls = [s for s in swings if s.verdict == 1]
    fair = [s for s in swings if s.verdict == 2]
    nc, nf = max(1, len(contacts)), max(1, len(fair))

    sprays = [s.contact.spray_deg for s in fair]
    shapes = {shape: [s for s in fair if s.shape == shape] for shape in SHAPES}
    return {
        "n": n,
        "whiff": (n - len(contacts)) / max(1, n),
        "foul": len(fouls) / max(1, n),
        "fair": len(fair) / max(1, n),
        "contact": len(contacts) / max(1, n),
        "foul_of_contact": len(fouls) / nc,
        "foul_by_direction": sum(s.foul_by_direction for s in contacts) / nc,
        "foul_by_quality": sum(s.foul_by_quality for s in contacts) / nc,
        "foul_by_both": sum(s.foul_by_direction and s.foul_by_quality
                            for s in contacts) / nc,
        "n_fair": len(fair),
        "quality": [s.contact.quality for s in fair],
        "quality_by_shape": {shape: [s.contact.quality for s in rows]
                             for shape, rows in shapes.items()},
        "launch": [s.launch_deg for s in fair],
        "mix": {shape: len(rows) / nf for shape, rows in shapes.items()},
        "spray": sprays,
        "spray_by_shape": {shape: [s.contact.spray_deg for s in rows]
                           for shape, rows in shapes.items()},
        "pull": sum(1 for d in sprays if d > THIRD_DEG) / nf,
        "centre": sum(1 for d in sprays if abs(d) <= THIRD_DEG) / nf,
        "oppo": sum(1 for d in sprays if d < -THIRD_DEG) / nf,
        "depth": [s.contact.depth_ft for s in fair],
        "contact_depth": [s.contact.depth_ft for s in contacts],
    }


# ---- The deterministic table -----------------------------------------------

ON_TIME_X = (0.7, 0.35, 0.0, -0.35, -0.7)       # inside-positive, ft
ON_TIME_Z = (3.3, 2.5, 1.7)


def on_time_swing(hand, x, z, speed_mph=93.0, timing_ms=0.0, **kw):
    """`(swing, contact)` for a perfectly aimed swing at one pitch.

    No aim assist and no scatter: the cursor sits on the ball's plate crossing
    and the swing is `timing_ms` off. The extreme deterministic case, which is
    what a guarantee is asserted on (CLAUDE.md, rule 10).
    """
    tr = _pitch(hand, x, z, speed_mph)
    swing = bp.swing(bc.aim_at_pitch(_cursor_on_ball(tr), tr, hand), hand)
    start = (tr.time_at_depth(swing.contact_depth_ft) - bp.SWING_DURATION_S
             + timing_ms / 1000.0)
    return swing, bc.resolve_contact(swing, tr, start, **kw)


def on_time_table(hand):
    """One row per zone location: where the on-time bat is and where the ball goes."""
    rows = []
    for z in ON_TIME_Z:
        for x in ON_TIME_X:
            swing, c = on_time_swing(hand, x, z)
            rows.append({
                "x": x, "z": z,
                "bearing": spray.attack_direction_deg(swing.contact_axis,
                                                      swing.spin),
                "tilt": math.degrees(swing.contact_tilt_rad),
                "depth": swing.contact_depth_ft,
                "hand_orbit": swing.hand_radius_ft,
                "ease_k": swing.ease_k,
                "spray": None if c is None else c.spray_deg,
                "launch": None if c is None else c.launch_deg,
                "quality": None if c is None else c.quality,
            })
    return rows


# The residual timing a swing keeps is what turns the ball, and at AMATEUR the
# assist removes all of it inside 26 ms. So the response is read at a budget
# small enough to leave the geometry nearly bare.
TIMING_RESPONSE_MULT = 0.2
TIMING_RESPONSE_MS = tuple(range(-14, 23, 2))


def timing_response(hand, x=0.0, z=2.5):
    """Degrees of spray per ms of *residual* timing error, on a middle pitch.

    A least-squares slope over the contacts found, signed so that early
    (negative ms) pulling the ball is a positive rate.
    """
    pts = []
    for ms in TIMING_RESPONSE_MS:
        _, c = on_time_swing(hand, x, z, timing_ms=float(ms),
                             timing_window_mult=TIMING_RESPONSE_MULT)
        if c is not None:
            pts.append((ms + c.shift_s * 1000.0, c.spray_deg))
    if len(pts) < 3:
        return float("nan"), pts
    mx = statistics.fmean(p[0] for p in pts)
    my = statistics.fmean(p[1] for p in pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    return -sxy / sxx, pts


# ---- Printing --------------------------------------------------------------

QUALITY_PS = (0.10, 0.25, 0.50, 0.75, 0.90, 0.99)
SHAPE_PS = (0.10, 0.25, 0.50, 0.75, 0.90)
LAUNCH_PS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def _pct(x):
    return f"{100.0 * x:5.1f}%"


def _quantile_row(values, ps, fmt="{:.3f}"):
    return "  ".join(f"p{int(round(p * 100)):02d} " + fmt.format(quantile(values, p))
                     for p in ps)


def print_summary(s, label):
    print(f"\n== {label}: {s['n']} swings, {s['n_fair']} fair ==")
    print(f"whiff / foul / fair     {_pct(s['whiff'])} {_pct(s['foul'])} "
          f"{_pct(s['fair'])}      (contact {_pct(s['contact'])})")
    print(f"fouls, share of contact {_pct(s['foul_of_contact'])}   "
          f"by direction {_pct(s['foul_by_direction'])}   "
          f"by quality {_pct(s['foul_by_quality'])}   "
          f"both {_pct(s['foul_by_both'])}")
    if not s["n_fair"]:
        return
    print("\nfair contact quality    " + _quantile_row(s["quality"], QUALITY_PS))
    for shape in SHAPES:
        rows = s["quality_by_shape"][shape]
        if rows:
            print(f"  {shape:<9} n={len(rows):<5}     "
                  + _quantile_row(rows, SHAPE_PS))
    print("\nlaunch angle, deg       "
          + _quantile_row(s["launch"], LAUNCH_PS, "{:+.1f}"))
    print(f"  mean {statistics.fmean(s['launch']):+.1f}  "
          f"sd {statistics.pstdev(s['launch']):.1f}")
    print("batted-ball mix         " + "  ".join(
        f"{shape} {_pct(s['mix'][shape])}" for shape in SHAPES))
    print(f"\nfair spray, deg         mean {statistics.fmean(s['spray']):+.2f}  "
          f"sd {statistics.pstdev(s['spray']):.1f}")
    print(f"  pull / centre / oppo  {_pct(s['pull'])} {_pct(s['centre'])} "
          f"{_pct(s['oppo'])}")
    for shape in SHAPES:
        rows = s["spray_by_shape"][shape]
        if len(rows) > 1:
            print(f"  {shape:<9} mean {statistics.fmean(rows):+.1f}")
    print("\ncontact depth, ft       fair "
          + _quantile_row(s["depth"], (0.10, 0.50, 0.90), "{:+.2f}")
          + "    all contact "
          + _quantile_row(s["contact_depth"], (0.10, 0.50, 0.90), "{:+.2f}"))


def print_on_time(hand):
    print(f"\n== on-time, perfectly aimed, {hand}HB "
          "(x is inside-positive; bearing is degrees past square) ==")
    head = (f"{'x':>6} {'z':>5}  {'bearing':>8} {'tilt':>6} {'depth':>6} "
            f"{'orbit':>6} {'ease_k':>6}  {'spray':>7} {'launch':>7} "
            f"{'quality':>7}")
    print(head)
    print("-" * len(head))
    for r in on_time_table(hand):
        hit = ("    whiff" if r["spray"] is None else
               f"{r['spray']:>+7.1f} {r['launch']:>+7.1f} {r['quality']:>7.2f}")
        print(f"{r['x']:>+6.2f} {r['z']:>5.2f}  {r['bearing']:>+8.1f} "
              f"{r['tilt']:>+6.1f} {r['depth']:>+6.2f} {r['hand_orbit']:>6.2f} "
              f"{r['ease_k']:>6.2f}  {hit}")
    rate, pts = timing_response(hand)
    print(f"\nball direction per ms of residual timing error: {rate:.2f} deg/ms "
          f"over {len(pts)} contacts, "
          f"{min(p[0] for p in pts):+.0f} to {max(p[0] for p in pts):+.0f} ms")


def print_ladder(n, seed, hand, jobs, overrides=()):
    print(f"\n== difficulty ladder, {hand}HB, {n} swings each ==")
    head = (f"{'LEVEL':<13} {'whiff':>6} {'foul':>6} {'fair':>6}   "
            f"{'foul/contact':>12} {'by dir':>7} {'by qual':>7}")
    print(head)
    print("-" * len(head))
    for level in DifficultyLevel:
        s = summarise(run(n, seed=seed, hand=hand, level=level.value,
                          jobs=jobs, overrides=overrides))
        print(f"{level.value:<13} {_pct(s['whiff'])} {_pct(s['foul'])} "
              f"{_pct(s['fair'])}   {_pct(s['foul_of_contact']):>12} "
              f"{_pct(s['foul_by_direction']):>7} {_pct(s['foul_by_quality']):>7}")


def print_anchors(s):
    """The run restated as the constants it is the source of."""
    print("\n== anchors (tools/sim.py, contact_audio.EV_CALIBRATION) ==")
    q = s["quality"]
    print("QUALITY_QUANTILES = (" + ", ".join(
        f"({p:.2f}, {quantile(q, p):.3f})" for p in SHAPE_PS) + ")")
    print(f"quality p99 = {quantile(q, 0.99):.3f}")
    print("QUALITY_BY_SHAPE = {")
    for shape in SHAPES:
        rows = s["quality_by_shape"][shape]
        if rows:
            print(f'    "{shape}": (' + ", ".join(
                f"({p:.2f}, {quantile(rows, p):.3f})" for p in SHAPE_PS) + "),")
    print("}")
    print("LAUNCH_ANGLE_QUANTILES = (" + ", ".join(
        f"({p:.2f}, {quantile(s['launch'], p):.1f})" for p in LAUNCH_PS) + ")")
    print(f"SPRAY_MEAN_DEG, SPRAY_SD_DEG = {statistics.fmean(s['spray']):.2f}, "
          f"{statistics.pstdev(s['spray']):.1f}")
    print("BATTED_BALL_MIX = (" + ", ".join(
        f'("{shape}", {s["mix"][shape]:.3f})' for shape in SHAPES) + ")")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Swing the canonical player model through the contact "
                    "seam and report the batted ball it produces.")
    ap.add_argument("--n", type=int, default=13000,
                    help="swings (about 39%% are fair at AMATEUR)")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--hand", choices=("R", "L", "both"), default="R")
    ap.add_argument("--level", choices=sorted(LEVELS), default="amateur")
    ap.add_argument("--power", action="store_true",
                    help="swing the power (E) swing")
    ap.add_argument("--jobs", type=int, default=1,
                    help="worker processes; never changes a number")
    ap.add_argument("--ladder", action="store_true",
                    help="also sweep every difficulty")
    ap.add_argument("--anchors", action="store_true",
                    help="also print the run as tools/sim.py constants")
    ap.add_argument("--no-table", action="store_true",
                    help="skip the deterministic on-time table")
    ap.add_argument("--aim-assist", type=float, default=None,
                    help="replace the level's aim assist, to sweep that dial")
    ap.add_argument("--set", action="append", default=[], metavar="MOD.NAME=X",
                    help="try a constant without editing it, e.g. "
                         "bat_contact.FOUL_QUALITY_THRESHOLD=0.55 (repeatable)")
    args = ap.parse_args(argv)

    overrides = []
    for item in args.set:
        dotted, _, value = item.partition("=")
        overrides.append((dotted, float(value)))
    apply_overrides(overrides)

    hands = ("R", "L") if args.hand == "both" else (args.hand,)
    print(f"player: aim scatter {AIM_SCATTER_FT} ft/axis, timing "
          f"N({TIMING_MEAN_MS:+.0f}, {TIMING_SD_MS:.0f}) ms, "
          f"{args.level}{', power swing' if args.power else ''}"
          f"{'' if args.aim_assist is None else f', aim assist {args.aim_assist:g}'}, "
          f"seed {args.seed}"
          + "".join(f", {dotted}={value:g}" for dotted, value in overrides))
    for hand in hands:
        started = time.time()
        s = summarise(run(args.n, seed=args.seed, hand=hand, level=args.level,
                          power=args.power, jobs=args.jobs,
                          overrides=overrides, aim_assist=args.aim_assist))
        print_summary(s, f"{hand}HB")
        print(f"({time.time() - started:.1f}s)")
        if args.anchors:
            print_anchors(s)
        if not args.no_table:
            print_on_time(hand)
        if args.ladder:
            print_ladder(args.n, args.seed, hand, args.jobs, overrides)
    print("\nTargets (AMATEUR):  whiff/foul/fair 30/31/39   "
          "mix 42/24/27/7 (MLB)   spray thirds 40/35/25 (MLB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
