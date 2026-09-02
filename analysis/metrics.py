"""Pure metric functions: DataFrame in, DataFrame out.

Nothing here draws or prints. Every panel in both renderers is built from one
of these, which is what keeps the PNG and terminal outputs numerically
identical by construction.
"""

import numpy as np
import pandas as pd

from . import theme


def _safe_div(n, d):
    return n / d if d else 0.0


def _rate(series):
    return float(series.mean()) if len(series) else 0.0


# ═════════════════════════════════════════════════════════════════════════
# Count-state run value
# ═════════════════════════════════════════════════════════════════════════
COUNTS = [(b, s) for b in range(4) for s in range(3)]


class RunValueModel:
    """Empirical count values, solved by backward induction over this dataset.

    V(b,s) is the expected run value of a plate appearance sitting at that
    count, in runs above average. Terminal events are priced with standard
    linear weights (theme.EVENT_RUN_VALUE); everything else is priced by where
    the count goes next. A pitch's run value is then simply the change in V it
    caused, which is what makes RV/100 comparable across pitch types.
    """

    def __init__(self, count_value, sample_size):
        self.count_value = count_value
        self.sample_size = sample_size

    def value_of(self, b, s):
        return self.count_value.get((int(b), int(s)), 0.0)

    def pitch_run_value(self, df):
        """Run value of each pitch, batter-positive, as a Series aligned to df."""
        if df.empty:
            return pd.Series(dtype=float)
        before = np.array([self.value_of(b, s) for b, s
                           in zip(df["balls_before"], df["strikes_before"])])
        after = np.array([
            self._value_after(o, b, s)
            for o, b, s in zip(df["outcome"], df["balls_before"], df["strikes_before"])
        ])
        return pd.Series(after - before, index=df.index)

    def _value_after(self, outcome, b, s):
        b, s = int(b), int(s)
        if outcome in theme.EVENT_RUN_VALUE:
            return theme.EVENT_RUN_VALUE[outcome]
        if outcome == "ball":
            if b >= 3:
                return theme.EVENT_RUN_VALUE["walk"]
            return self.value_of(b + 1, s)
        if outcome == "strike":
            if s >= 2:
                return theme.EVENT_RUN_VALUE["strikeout"]
            return self.value_of(b, s + 1)
        if outcome == "foul":
            # A foul with two strikes returns to the same count: zero net value.
            return self.value_of(b, min(s + 1, 2))
        return self.value_of(b, s)


def run_value_model(df):
    """Solve V(b,s) by backward induction from observed transitions."""
    count_value = {}
    if df.empty:
        return RunValueModel({c: 0.0 for c in COUNTS}, 0)

    grouped = {k: g for k, g in df.groupby(["balls_before", "strikes_before"])}

    # V(b,s) depends on V(b+1,s) and V(b,s+1), so walk both axes downward.
    for b in range(3, -1, -1):
        for s in range(2, -1, -1):
            g = grouped.get((b, s))
            if g is None or g.empty:
                count_value[(b, s)] = 0.0
                continue

            total = len(g)
            acc = 0.0
            self_loop = 0

            for outcome, n in g["outcome"].value_counts().items():
                if outcome in theme.EVENT_RUN_VALUE:
                    acc += n * theme.EVENT_RUN_VALUE[outcome]
                elif outcome == "ball":
                    acc += n * (theme.EVENT_RUN_VALUE["walk"] if b >= 3
                                else count_value.get((b + 1, s), 0.0))
                elif outcome == "strike":
                    acc += n * (theme.EVENT_RUN_VALUE["strikeout"] if s >= 2
                                else count_value.get((b, s + 1), 0.0))
                elif outcome == "foul":
                    if s >= 2:
                        # Self-transition — excluded and renormalised below.
                        self_loop += n
                    else:
                        acc += n * count_value.get((b, s + 1), 0.0)
                else:
                    acc += n * 0.0

            denom = total - self_loop
            count_value[(b, s)] = acc / denom if denom > 0 else 0.0

    return RunValueModel(count_value, len(df))


def count_value_table(model):
    rows = []
    for b in range(4):
        for s in range(3):
            rows.append({"balls": b, "strikes": s, "count": f"{b}-{s}",
                         "value": model.value_of(b, s)})
    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════════════════
# Pitcher-level aggregates
# ═════════════════════════════════════════════════════════════════════════
def _pitch_metrics(g):
    """Statcast-style rate stats for one group of pitches."""
    np_ = len(g)
    swings = int(g["is_swing"].sum())
    zone = int(g["in_zone"].sum())
    o_zone = np_ - zone
    whiffs = int(g["is_whiff"].sum())
    called = int(g["is_called_strike"].sum())
    balls_thrown = int(g["outcome"].isin(("ball", "walk")).sum())

    fp = g[g["is_first_pitch"]]
    first_strikes = int((~fp["outcome"].isin(("ball", "walk"))).sum()) if len(fp) else 0

    two_k = g[g["strikes_before"] == 2]
    putaways = int((two_k["outcome"] == "strikeout").sum()) if len(two_k) else 0

    return {
        "pitches": np_,
        "swings": swings,
        "whiffs": whiffs,
        "zone": zone,
        "strike_pct": _safe_div(np_ - balls_thrown, np_),
        "csw_pct": _safe_div(called + whiffs, np_),
        "whiff_pct": _safe_div(whiffs, swings),
        "swing_pct": _safe_div(swings, np_),
        "zone_pct": _safe_div(zone, np_),
        "z_swing_pct": _safe_div(int((g["is_swing"] & g["in_zone"]).sum()), zone),
        "chase_pct": _safe_div(int(g["is_chase"].sum()), o_zone),
        "f_strike_pct": _safe_div(first_strikes, len(fp)),
        "putaway_pct": _safe_div(putaways, len(two_k)),
        "power_swing_pct": _safe_div(int(g["is_power_swing"].sum()), swings),
    }


def _outcome_metrics(g):
    """At-bat-level rate stats derived from terminal pitches."""
    counts = g[g["is_terminal"]]["outcome"].value_counts().to_dict()
    pa = sum(counts.values())
    bb = counts.get("walk", 0)
    k = counts.get("strikeout", 0)
    s1 = counts.get("SINGLE", 0)
    d2 = counts.get("DOUBLE", 0)
    t3 = counts.get("TRIPLE", 0)
    hr = counts.get("HOME RUN", 0)
    go = counts.get("GROUNDOUT", 0)
    ao = sum(counts.get(o, 0) for o in ("FLYOUT", "LINEOUT", "POP UP"))
    # Reached on error. Not a hit and not an out, so it needs no special case
    # in any of the rates below — it lands in `ab` and `bip` and stays out of
    # `h` and `tb` purely by not being in HIT_OUTCOMES, which is the standard
    # scoring convention for a ROE. Counted here so it is *visible*: a
    # defensive event that moves BABIP has to be reportable, or the defense
    # setting has no readout anywhere. Rendered as ROE% beside BABIP in the
    # plate-discipline and slash-line tables, and in the terminal renderer —
    # all three, because a metric with no readout is one nobody checks.
    roe = sum(counts.get(o, 0) for o in theme.REACH_OUTCOMES)

    h = s1 + d2 + t3 + hr
    ab = pa - bb
    bip = ab - k - hr
    tb = s1 + 2 * d2 + 3 * t3 + 4 * hr

    avg = _safe_div(h, ab)
    slg = _safe_div(tb, ab)
    return {
        "pa": pa, "ab": ab, "h": h, "bb": bb, "k": k, "hr": hr,
        "singles": s1, "doubles": d2, "triples": t3,
        "go": go, "ao": ao, "tb": tb, "bip": bip,
        "roe": roe, "roe_pct": _safe_div(roe, bip),
        "avg": avg,
        "obp": _safe_div(h + bb, pa),
        "slg": slg,
        "ops": _safe_div(h + bb, pa) + slg,
        "iso": slg - avg,
        "babip": _safe_div(h - hr, bip) if bip > 0 else 0.0,
        # Simplified wOBA — no HBP/SF/IBB are tracked by the game.
        "woba": _safe_div(0.69 * bb + 0.89 * s1 + 1.27 * d2 + 1.62 * t3 + 2.10 * hr, pa),
        "k_pct": _safe_div(k, pa),
        "bb_pct": _safe_div(bb, pa),
        "k_minus_bb_pct": _safe_div(k - bb, pa),
        "k_per_bb": _safe_div(k, bb) if bb else float("inf"),
        "hr_pct": _safe_div(hr, pa),
        "go_ao": _safe_div(go, ao) if ao else float("inf"),
        "p_per_pa": _safe_div(len(g), pa),
    }


def plate_discipline(ctx):
    """One row per pitcher: pitch-level and AB-level rate stats combined."""
    rows = []
    for name, g in ctx.pitches.groupby("pitcher_name"):
        if not g["is_terminal"].any():
            continue
        row = {"pitcher": name, "display": theme.pitcher_display(name)}
        row.update(_outcome_metrics(g))
        row.update(_pitch_metrics(g))
        rv = ctx.run_value.pitch_run_value(g)
        row["rv_per_100"] = -100 * rv.mean() if len(rv) else 0.0
        rows.append(row)
    df = pd.DataFrame(rows)
    return df.sort_values("pitches", ascending=False).reset_index(drop=True) if len(df) else df


def pitching_line(ctx):
    """Classic box-score line, GameDay only — ERA/WHIP need real innings.

    Every column is computed over the same slice: rows whose ``game_id`` is
    known, which is exactly the set whose runs can be attributed. Rows without
    one are dropped wholesale and reported via ``dropped_pitches`` on the frame.

    That "same slice" rule is the point. The previous version counted H/HR/BB/K
    over *all* GameDay rows but runs over only the run-covered ones, and since
    ``game_id IS NULL`` and ``runs_scored_on_pitch IS NULL`` are perfectly
    correlated (both arrived in the v2 migration), the whole pre-v2 era
    contributed innings and home runs but structurally zero runs — which is how
    a line ends up showing more HR than R, and a 0.73 ERA behind it.

    Within the kept slice, runs come per-pitch from ``runs_scored_on_pitch``
    where present, else prorated from the game's final score by batters faced;
    ``runs_exact`` flags which method was used.
    """
    gd = ctx.pitches[ctx.pitches["game_mode"] == "gameday"]
    if gd.empty:
        return pd.DataFrame()

    attributable = gd[gd["game_id"].notna()] if "game_id" in gd else gd.iloc[0:0]
    dropped = len(gd) - len(attributable)
    if attributable.empty:
        return pd.DataFrame()

    rows = []
    for name, g in attributable.groupby("pitcher_name"):
        counts = g[g["is_terminal"]]["outcome"].value_counts().to_dict()
        bf = sum(counts.values())
        if bf == 0:
            continue
        outs = sum(counts.get(o, 0) for o in theme.OUT_OUTCOMES)
        h = sum(counts.get(o, 0) for o in theme.HIT_OUTCOMES)
        bb = counts.get("walk", 0)
        k = counts.get("strikeout", 0)
        hr = counts.get("HOME RUN", 0)

        scored = g["runs_scored_on_pitch"]
        covered = scored.notna()
        runs_exact = bool(covered.all())
        r = int(scored.fillna(0).sum())
        if not covered.all():
            r += _fallback_runs(ctx, g[~covered])

        # A home run scores at least the batter. If per-pitch attribution is
        # incomplete, that floor is still knowable, so honour it rather than
        # publishing a line that says a pitcher allowed 21 homers and 9 runs.
        r = max(r, hr)

        ip = outs / 3
        games = int(g["game_id"].nunique())
        rows.append({
            "pitcher": name,
            "display": theme.pitcher_display(name),
            "g": int(games), "outs": outs, "ip": ip, "bf": bf,
            "h": h, "r": r, "er": r, "hr": hr, "bb": bb, "k": k,
            "runs_exact": runs_exact,
            "era": _safe_div(r * 9, ip),
            "whip": _safe_div(h + bb, ip),
            "k_per_9": _safe_div(k * 9, ip),
            "bb_per_9": _safe_div(bb * 9, ip),
            "hr_per_9": _safe_div(hr * 9, ip),
        })
    df = pd.DataFrame(rows)
    if not len(df):
        return df
    df = df.sort_values("outs", ascending=False).reset_index(drop=True)
    df.attrs["dropped_pitches"] = int(dropped)
    return df


def _fallback_runs(ctx, uncovered):
    """Pre-`runs_scored_on_pitch` rows: prorate the game's runs by batters faced.

    The runs charged here are the runs the *player's* team scored: the pitches
    table only holds pitches thrown to the player by the opposing arm, so a
    pitcher in this line is scored on `final_player_score`. `final_opponent_score`
    is what the player's own (simulated) staff gave up and never appears here.
    """
    games = ctx.games
    if games.empty or "game_id" not in uncovered.columns:
        return 0
    gid_runs = games.set_index("game_id")["final_player_score"].to_dict()
    total = 0.0
    all_gd = ctx.pitches[ctx.pitches["game_mode"] == "gameday"]
    for gid, chunk in uncovered.groupby("game_id"):
        if gid is None or gid not in gid_runs:
            continue
        game_rows = all_gd[all_gd["game_id"] == gid]
        share = _safe_div(int(chunk["is_terminal"].sum()),
                          int(game_rows["is_terminal"].sum()))
        total += (gid_runs.get(gid) or 0) * share
    return int(round(total))


# ═════════════════════════════════════════════════════════════════════════
# Arsenal / pitch-type level
# ═════════════════════════════════════════════════════════════════════════
def arsenal(ctx, by_pitcher=True):
    """Per pitch type (optionally per pitcher): velo, movement, results, RV."""
    keys = ["pitcher_name", "pitch_type"] if by_pitcher else ["pitch_type"]
    if ctx.empty:
        return pd.DataFrame()

    total = len(ctx.pitches)
    rows = []
    for key, g in ctx.pitches.groupby(keys):
        key = key if isinstance(key, tuple) else (key,)
        rec = dict(zip(keys, key))
        pt = rec["pitch_type"]
        denom = len(ctx.for_pitcher(rec["pitcher_name"])) if by_pitcher else total

        rv = ctx.run_value.pitch_run_value(g)
        two_k = g[g["strikes_before"] == 2]
        bip = int(g["is_in_play"].sum())
        whiffs = int(g["is_whiff"].sum())
        hits = int(g["is_hit_outcome"].sum())

        rec.update({
            "pitch_type": pt,
            "name": theme.pitch_name(pt),
            "n": len(g),
            "usage_pct": 100 * _safe_div(len(g), denom),
            "velo": float(g["speed_mph"].mean()),
            "velo_max": float(g["speed_mph"].max()),
            "pfx_x": float(g["pfx_x_inches"].mean()),
            "pfx_z": float(g["pfx_z_inches"].mean()),
            "csw_pct": 100 * _safe_div(int(g["is_called_strike"].sum()) + whiffs, len(g)),
            "whiff_pct": 100 * _safe_div(whiffs, int(g["is_swing"].sum())),
            "chase_pct": 100 * _safe_div(int(g["is_chase"].sum()),
                                         len(g) - int(g["in_zone"].sum())),
            "zone_pct": 100 * _safe_div(int(g["in_zone"].sum()), len(g)),
            "putaway_pct": 100 * _safe_div(int((two_k["outcome"] == "strikeout").sum()),
                                           len(two_k)),
            # xBA proxy: a whiff is a guaranteed out, so it belongs in the
            # denominator alongside balls in play.
            "xba": _safe_div(hits, bip + whiffs),
            "rv_per_100": -100 * rv.mean() if len(rv) else 0.0,
        })
        rows.append(rec)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    sort_keys = ["pitcher_name", "usage_pct"] if by_pitcher else ["usage_pct"]
    asc = [True, False] if by_pitcher else [False]
    return df.sort_values(sort_keys, ascending=asc).reset_index(drop=True)


def scouting_card(ctx, min_pitches=20):
    """Pitch-type summary for the scouting card, with dataset percentiles.

    MLB thresholds alone saturate — this game's rates run far above league
    norms — so each metric also carries its rank within the current slice.
    """
    df = arsenal(ctx, by_pitcher=False)
    if df.empty:
        return df
    df = df[df["n"] >= min_pitches].copy()
    if df.empty:
        return df
    for col in ("csw_pct", "whiff_pct", "chase_pct", "putaway_pct", "rv_per_100"):
        df[f"{col}_pctile"] = df[col].rank(pct=True) * 100
    # Lower xBA is better, so invert before ranking.
    df["xba_pctile"] = (-df["xba"]).rank(pct=True) * 100
    return df.sort_values("usage_pct", ascending=False).reset_index(drop=True)


# ═════════════════════════════════════════════════════════════════════════
# Count / sequencing
# ═════════════════════════════════════════════════════════════════════════
COUNT_ORDER = ["0-0", "0-1", "0-2", "1-0", "1-1", "1-2",
               "2-0", "2-1", "2-2", "3-0", "3-1", "3-2"]


def usage_by_count(ctx):
    """Pitch-type usage % per ball-strike count (columns sum to 100)."""
    if ctx.empty:
        return pd.DataFrame()
    tab = pd.crosstab(ctx.pitches["pitch_type"], ctx.pitches["count_str"])
    cols = [c for c in COUNT_ORDER if c in tab.columns]
    tab = tab[cols]
    return (tab / tab.sum()).fillna(0) * 100


def performance_by_count_state(ctx):
    """How the slice performs when ahead / even / behind / two strikes.

    Deliberately carries no RV column: the count-value model is fitted per
    count, so the mean run value of every pitch thrown in a given count is
    exactly zero by construction. Reporting it would be a tautology dressed as
    a finding. `terminal_pct` / `k_share` carry the real signal instead.
    """
    if ctx.empty:
        return pd.DataFrame()
    rows = []
    order = ["first_pitch", "ahead", "even", "behind", "two_strike"]
    for state in order:
        g = ctx.pitches[ctx.pitches["count_state"] == state]
        if g.empty:
            continue
        term = g[g["is_terminal"]]
        rows.append({
            "state": state,
            "n": len(g),
            "usage_pct": 100 * len(g) / len(ctx.pitches),
            "swing_pct": 100 * _rate(g["is_swing"]),
            "whiff_pct": 100 * _safe_div(int(g["is_whiff"].sum()), int(g["is_swing"].sum())),
            "csw_pct": 100 * _safe_div(int(g["is_called_strike"].sum())
                                       + int(g["is_whiff"].sum()), len(g)),
            "zone_pct": 100 * _rate(g["in_zone"]),
            "chase_pct": 100 * _safe_div(int(g["is_chase"].sum()),
                                         len(g) - int(g["in_zone"].sum())),
            "terminal_pct": 100 * _safe_div(len(term), len(g)),
            "k_share": 100 * _safe_div(int((term["outcome"] == "strikeout").sum()),
                                       len(term)),
        })
    return pd.DataFrame(rows)


def sequencing(ctx, min_n=15):
    """prev pitch → current pitch: usage share and whiff% vs that pitch's baseline.

    `prev_pitch_type` is 93.8% populated and was never read by the old script.
    The delta column is the interesting one: how much more (or less) a pitch
    misses bats given what preceded it.
    """
    if ctx.empty or "prev_pitch_type" not in ctx.pitches.columns:
        return pd.DataFrame()
    df = ctx.pitches[ctx.pitches["prev_pitch_type"].notna()]
    if df.empty:
        return pd.DataFrame()

    baseline = {}
    for pt, g in df.groupby("pitch_type"):
        baseline[pt] = 100 * _safe_div(int(g["is_whiff"].sum()), int(g["is_swing"].sum()))

    rows = []
    for (prev, cur), g in df.groupby(["prev_pitch_type", "pitch_type"]):
        if len(g) < min_n:
            continue
        swings = int(g["is_swing"].sum())
        whiff = 100 * _safe_div(int(g["is_whiff"].sum()), swings)
        rv = ctx.run_value.pitch_run_value(g)
        rows.append({
            "prev": prev, "cur": cur,
            "prev_name": theme.pitch_name(prev), "cur_name": theme.pitch_name(cur),
            "n": len(g),
            "whiff_pct": whiff,
            "baseline_whiff_pct": baseline.get(cur, 0.0),
            "whiff_delta": whiff - baseline.get(cur, 0.0),
            "rv_per_100": -100 * rv.mean() if len(rv) else 0.0,
        })
    out = pd.DataFrame(rows)
    return out.sort_values("whiff_delta", ascending=False).reset_index(drop=True) if len(out) else out


def best_and_worst_sequences(seq, n=8):
    """Top-n and bottom-n rows, without repeating any when there are ≤2n rows."""
    if seq.empty:
        return seq, seq.iloc[0:0]
    if len(seq) <= 2 * n:
        split = len(seq) // 2
        return seq.iloc[:split], seq.iloc[split:].iloc[::-1]
    return seq.head(n), seq.tail(n).iloc[::-1]


# ═════════════════════════════════════════════════════════════════════════
# Location
# ═════════════════════════════════════════════════════════════════════════
# 5x5 grid: the middle 3x3 is the strike zone, the outer ring is the shadow /
# chase band one cell wide on each side.
_ZX = theme.SZ_X_HALF * 2 / 3
_ZZ = (theme.SZ_Z_MAX - theme.SZ_Z_MIN) / 3
ZONE_X_EDGES = [-theme.SZ_X_HALF - _ZX, -theme.SZ_X_HALF, -theme.SZ_X_HALF + _ZX,
                theme.SZ_X_HALF - _ZX, theme.SZ_X_HALF, theme.SZ_X_HALF + _ZX]
ZONE_Z_EDGES = [theme.SZ_Z_MIN - _ZZ, theme.SZ_Z_MIN, theme.SZ_Z_MIN + _ZZ,
                theme.SZ_Z_MAX - _ZZ, theme.SZ_Z_MAX, theme.SZ_Z_MAX + _ZZ]


def zone_grid(df, value="whiff", batter_view=True, min_n=5):
    """5x5 grid of a rate statistic. Returns (values, counts) as 2-D arrays.

    Row 0 is the TOP of the zone so the array can be imshow'd directly.
    """
    vals = np.full((5, 5), np.nan)
    counts = np.zeros((5, 5), dtype=int)
    if df.empty:
        return vals, counts

    x = df["plate_x_batter"] if batter_view else df["plate_x_ft"]
    xi = np.digitize(x, ZONE_X_EDGES) - 1
    zi = np.digitize(df["plate_z_ft"], ZONE_Z_EDGES) - 1
    inside = (xi >= 0) & (xi < 5) & (zi >= 0) & (zi < 5)

    for col in range(5):
        for row in range(5):
            sel = inside & (xi == col) & (zi == row)
            g = df[sel.values] if hasattr(sel, "values") else df[sel]
            counts[4 - row, col] = len(g)
            if len(g) < min_n:
                continue
            if value == "whiff":
                v = 100 * _safe_div(int(g["is_whiff"].sum()), int(g["is_swing"].sum()))
            elif value == "swing":
                v = 100 * _rate(g["is_swing"])
            elif value == "damage":
                ip = g[g["is_in_play"]]
                v = 100 * _safe_div(int(ip["is_hit_outcome"].sum()), len(ip)) if len(ip) else np.nan
            elif value == "density":
                v = 100 * len(g) / len(df)
            else:
                raise ValueError(f"unknown zone_grid value: {value}")
            vals[4 - row, col] = v
    return vals, counts


# ═════════════════════════════════════════════════════════════════════════
# Tunneling
# ═════════════════════════════════════════════════════════════════════════
def slice_trajectories(ctx, max_ids=8000):
    """Trajectory samples for the active slice, joined to pitch metadata.

    Cached on the context — both the tunneling table and the trajectory figure
    need it, and it is the one genuinely large read in the pipeline.
    """
    from . import data as data_mod

    if getattr(ctx, "_traj", None) is not None:
        return ctx._traj
    if ctx.empty:
        ctx._traj = pd.DataFrame()
        return ctx._traj

    df = ctx.pitches
    ids = df["pitch_id"].tolist()
    if len(ids) > max_ids:
        # Cheaper to stream the whole table once than to chunk 24k parameters.
        traj = data_mod.load_trajectories(db_path=ctx.db_path)
        traj = traj[traj["pitch_id"].isin(set(ids))]
    else:
        traj = data_mod.load_trajectories(ids, db_path=ctx.db_path)

    if not traj.empty:
        meta = df.set_index("pitch_id")[["pitcher_name", "pitch_type", "batter_hand"]]
        traj = traj.join(meta, on="pitch_id")
    ctx._traj = traj
    return traj


def mean_trajectories(ctx, min_n=30):
    """Average flight path per (pitcher, pitch type), for the tunneling plot."""
    traj = slice_trajectories(ctx)
    if traj.empty:
        return pd.DataFrame()
    grouped = traj.groupby(["pitcher_name", "pitch_type", "sample_idx"]).agg(
        x_ft=("x_ft", "mean"), y_ft=("y_ft", "mean"), z_ft=("z_ft", "mean"),
        n=("pitch_id", "nunique"),
    ).reset_index()
    keep = grouped.groupby(["pitcher_name", "pitch_type"])["n"].transform("max") >= min_n
    return grouped[keep].reset_index(drop=True)


def tunneling(ctx, min_n=30):
    """Trajectory separation at the commit point vs at the plate.

    A low commit-point separation with a high plate separation is the textbook
    definition of a tunneled pitch pair: indistinguishable when the hitter has
    to decide, far apart when the bat arrives. `tunnel_ratio` is
    plate ÷ commit — bigger is better for the pitcher.
    """
    if ctx.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = ctx.pitches
    traj = slice_trajectories(ctx)
    if traj.empty:
        return pd.DataFrame(), pd.DataFrame()
    meta = df.set_index("pitch_id")[["pitcher_name", "pitch_type", "batter_hand"]]

    # Interpolate each pitch to the commit point. y_ft decreases with sample
    # index (54ft at release → 0 at the plate), so sort ascending by y first.
    commit = _interp_at_y(traj, theme.COMMIT_POINT_FT)
    plate = _interp_at_y(traj, 0.0)
    if commit.empty or plate.empty:
        return pd.DataFrame(), pd.DataFrame()

    merged = commit.merge(plate, on="pitch_id", suffixes=("_commit", "_plate"))
    merged = merged.join(meta, on="pitch_id")

    per_type = merged.groupby(["pitcher_name", "pitch_type"]).agg(
        n=("pitch_id", "count"),
        x_commit=("x_ft_commit", "mean"), z_commit=("z_ft_commit", "mean"),
        x_plate=("x_ft_plate", "mean"), z_plate=("z_ft_plate", "mean"),
    ).reset_index()
    per_type = per_type[per_type["n"] >= min_n]

    pairs = []
    for pitcher, g in per_type.groupby("pitcher_name"):
        recs = g.to_dict("records")
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                a, b = recs[i], recs[j]
                commit_sep = float(np.hypot(a["x_commit"] - b["x_commit"],
                                            a["z_commit"] - b["z_commit"])) * 12
                plate_sep = float(np.hypot(a["x_plate"] - b["x_plate"],
                                           a["z_plate"] - b["z_plate"])) * 12
                pairs.append({
                    "pitcher_name": pitcher,
                    "display": theme.pitcher_display(pitcher),
                    "pair": f"{a['pitch_type']}/{b['pitch_type']}",
                    "a": a["pitch_type"], "b": b["pitch_type"],
                    "n": int(min(a["n"], b["n"])),
                    "commit_sep_in": commit_sep,
                    "plate_sep_in": plate_sep,
                    "tunnel_ratio": _safe_div(plate_sep, commit_sep),
                })
    pairs_df = pd.DataFrame(pairs)
    if len(pairs_df):
        pairs_df = pairs_df.sort_values("tunnel_ratio", ascending=False).reset_index(drop=True)
    return per_type, pairs_df


def _interp_at_y(traj, y_target):
    """Linear interpolation of x/z at a given remaining-distance y, per pitch."""
    out = []
    for pid, g in traj.groupby("pitch_id", sort=False):
        g = g.sort_values("y_ft")
        y = g["y_ft"].to_numpy()
        if len(y) < 2 or y_target < y[0] or y_target > y[-1]:
            continue
        out.append({
            "pitch_id": pid,
            "x_ft": float(np.interp(y_target, y, g["x_ft"].to_numpy())),
            "z_ft": float(np.interp(y_target, y, g["z_ft"].to_numpy())),
        })
    return pd.DataFrame(out)


# ═════════════════════════════════════════════════════════════════════════
# Umpire / ABS
# ═════════════════════════════════════════════════════════════════════════
def umpire_accuracy(ctx):
    """AI umpire calls vs ground truth. Returns (summary dict, miscall rows)."""
    df = ctx.pitches
    if df.empty or "truth_strike" not in df.columns:
        return {}, pd.DataFrame()
    graded = df[df["ai_umpire_strike"].notna() & df["truth_strike"].notna()]
    if graded.empty:
        return {"graded": 0}, pd.DataFrame()

    miscalled = graded[graded["ai_umpire_strike"] != graded["truth_strike"]]
    stolen = miscalled[miscalled["ai_umpire_strike"] == 1]   # ball called strike
    lost = miscalled[miscalled["ai_umpire_strike"] == 0]     # strike called ball
    challenged = int(df["abs_challenged"].fillna(0).sum())
    summary = {
        "graded": len(graded),
        "coverage_pct": 100 * len(graded) / len(df),
        "miscalls": len(miscalled),
        "accuracy_pct": 100 * (1 - len(miscalled) / len(graded)),
        "stolen_strikes": len(stolen),
        "lost_strikes": len(lost),
        "challenged": challenged,
        "overturned": int(df["abs_overturned"].fillna(0).sum()),
    }
    return summary, miscalled


# ═════════════════════════════════════════════════════════════════════════
# Trends
# ═════════════════════════════════════════════════════════════════════════
def trends(ctx, window=7):
    """Per-day rates with a rolling mean — is the player improving?"""
    if ctx.empty or ctx.pitches["day"].isna().all():
        return pd.DataFrame()
    rows = []
    for day, g in ctx.pitches.groupby("day"):
        term = g[g["is_terminal"]]
        o = _outcome_metrics(g) if len(term) else None
        rv = ctx.run_value.pitch_run_value(g)
        rows.append({
            "day": day,
            "pitches": len(g),
            "pa": len(term),
            "csw_pct": 100 * _safe_div(int(g["is_called_strike"].sum())
                                       + int(g["is_whiff"].sum()), len(g)),
            "whiff_pct": 100 * _safe_div(int(g["is_whiff"].sum()), int(g["is_swing"].sum())),
            "chase_pct": 100 * _safe_div(int(g["is_chase"].sum()),
                                         len(g) - int(g["in_zone"].sum())),
            "woba": o["woba"] if o else np.nan,
            "rv_per_100": 100 * rv.mean() if len(rv) else 0.0,
        })
    df = pd.DataFrame(rows).sort_values("day").reset_index(drop=True)
    for col in ("csw_pct", "whiff_pct", "chase_pct", "woba", "rv_per_100"):
        df[f"{col}_roll"] = df[col].rolling(window, min_periods=2).mean()
    return df


# ═════════════════════════════════════════════════════════════════════════
# Misc summaries
# ═════════════════════════════════════════════════════════════════════════
def overview(ctx):
    """Headline numbers for the report/terminal header."""
    df = ctx.pitches
    if df.empty:
        return {}
    span = ctx.date_span
    o = _outcome_metrics(df)
    p = _pitch_metrics(df)
    return {
        "pitches": len(df),
        "pa": o["pa"],
        "pitchers": df["pitcher_name"].nunique(),
        "pitch_types": df["pitch_type"].nunique(),
        "days": int(df["day"].nunique()),
        "first_day": span[0] if span else None,
        "last_day": span[1] if span else None,
        "csw_pct": 100 * p["csw_pct"],
        "whiff_pct": 100 * p["whiff_pct"],
        "chase_pct": 100 * p["chase_pct"],
        "zone_pct": 100 * p["zone_pct"],
        "k_pct": 100 * o["k_pct"],
        "bb_pct": 100 * o["bb_pct"],
        "avg": o["avg"], "obp": o["obp"], "slg": o["slg"], "ops": o["ops"],
        "woba": o["woba"],
        # No aggregate RV here on purpose: the count-value model is fitted to
        # this same slice, so run values sum to ~0 by construction. RV is only
        # meaningful comparing sub-groups within a slice.
    }


def outcome_breakdown(ctx):
    """Terminal-outcome counts per pitcher, as a share of PA."""
    if ctx.empty:
        return pd.DataFrame()
    term = ctx.pitches[ctx.pitches["is_terminal"]]
    if term.empty:
        return pd.DataFrame()
    tab = pd.crosstab(term["pitcher_name"], term["outcome"])
    for o in theme.OUTCOME_ORDER:
        if o not in tab.columns:
            tab[o] = 0
    return tab[list(theme.OUTCOME_ORDER)]


# Spray thirds. Pull / centre / opposite, split at +/-15 degrees off centre
# field — the conventional cut, and the one MLB's own 40/35/25 league split is
# quoted against.
SPRAY_THIRD_DEG = 15.0


def spray_profile(ctx):
    """Where batted balls went, by batted-ball type.

    `spray_angle_deg` is stored pull-positive for either batter (see the v9
    note in `pitch_database`), so this needs no handedness join and a
    right-handed and a left-handed pull look like the same thing — which is
    what makes the aggregate mean anything.

    Sliced by `batted_ball_type` because that is classified at contact,
    upstream of any fielding decision, so the two axes are independent. A
    ground ball being pulled harder than a fly ball is a real and checkable
    property of a swing model; reading spray against `outcome` instead would
    be reading it against something the spray helped produce.
    """
    if ctx.empty:
        return pd.DataFrame()
    df = ctx.pitches
    if "spray_angle_deg" not in df.columns:
        return pd.DataFrame()
    hit = df[df["spray_angle_deg"].notna() & df["is_in_play"]]
    if hit.empty:
        return pd.DataFrame()

    rows = []
    for label, grp in list(hit.groupby("batted_ball_type")) + [("All", hit)]:
        deg = grp["spray_angle_deg"]
        n = len(deg)
        rows.append({
            "Type": label,
            "N": n,
            "Mean": deg.mean(),
            "SD": deg.std(),
            "Pull%": 100.0 * (deg > SPRAY_THIRD_DEG).sum() / n,
            "Centre%": 100.0 * deg.between(-SPRAY_THIRD_DEG,
                                           SPRAY_THIRD_DEG).sum() / n,
            "Oppo%": 100.0 * (deg < -SPRAY_THIRD_DEG).sum() / n,
        })
    out = pd.DataFrame(rows).set_index("Type")
    # "All" last, the rest alphabetical, so the summary row reads as one.
    order = [i for i in out.index if i != "All"] + ["All"]
    return out.loc[order]


def spray_vs_timing(ctx, bin_ms=10.0, min_n=5):
    """Mean spray angle against signed swing timing.

    The single most useful thing this column can be asked, and the one the
    spray model exists to make true: a swing that got there early meets the
    ball with the bat further round and pulls it. If this comes back flat, the
    bearing has stopped reaching the ball somewhere between `bat_contact` and
    `hit_animation`.
    """
    if ctx.empty:
        return pd.DataFrame()
    df = ctx.pitches
    for col in ("spray_angle_deg", "swing_timing_signed_ms"):
        if col not in df.columns:
            return pd.DataFrame()
    hit = df[df["spray_angle_deg"].notna()
             & df["swing_timing_signed_ms"].notna()]
    if hit.empty:
        return pd.DataFrame()
    binned = (hit["swing_timing_signed_ms"] / bin_ms).round() * bin_ms
    grouped = hit.groupby(binned)["spray_angle_deg"]
    out = pd.DataFrame({"n": grouped.size(), "spray": grouped.mean()})
    out = out[out["n"] >= min_n]
    out.index.name = "timing_ms"
    return out


# ── Formatting helpers shared by both renderers ──────────────────────────
def fmt_ip(outs):
    return f"{outs // 3}.{outs % 3}"


def fmt_avg(rate):
    """Baseball rate without the leading zero (.305)."""
    if rate is None or (isinstance(rate, float) and np.isnan(rate)):
        return "—"
    s = f"{rate:.3f}"
    return s.lstrip("0") if 0 <= rate < 1 else s


def fmt_pct(v, digits=1):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:.{digits}f}%"


def fmt_num(v, digits=2):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    return f"{v:.{digits}f}"
