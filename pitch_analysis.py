"""
StrikeFactor Pitch Database Analysis
Generates visualizations from the SQLite pitch database.
"""
import argparse
import sqlite3
import os
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from dataclasses import dataclass
from matplotlib.gridspec import GridSpec
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(__file__), "strikefactor", "data", "strikefactor.db")
OUT_DIR = os.path.join(os.path.dirname(__file__), "analysis_output")
os.makedirs(OUT_DIR, exist_ok=True)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row


def fetch(sql, params=()):
    return conn.execute(sql, params).fetchall()


# ── Filter (mode + difficulty) ───────────────────────────────────────────
MODE_CHOICES = ("arcade", "gameday", "sandbox")
DIFFICULTY_CHOICES = ("rookie", "amateur", "professional", "all_star", "hall_of_fame")

MODE_LABEL = {
    "arcade": "Arcade",
    "gameday": "GameDay",
    "sandbox": "Sandbox",
}
DIFFICULTY_LABEL = {
    "rookie": "Rookie",
    "amateur": "Amateur",
    "professional": "Professional",
    "all_star": "All-Star",
    "hall_of_fame": "Hall of Fame",
}


@dataclass(frozen=True)
class Filter:
    modes: tuple        # subset of MODE_CHOICES; () = all
    difficulties: tuple # subset of DIFFICULTY_CHOICES; () = all
    hands: tuple = ()   # subset of ("L", "R"); () = both

    @property
    def label(self):
        m = ", ".join(MODE_LABEL[x] for x in self.modes) if self.modes else "All modes"
        d = ", ".join(DIFFICULTY_LABEL[x] for x in self.difficulties) if self.difficulties else "All difficulties"
        h = ", ".join(f"{x}HB" for x in self.hands) if self.hands else "Both hands"
        return f"{m} · {d} · {h}"

    @property
    def slug(self):
        """Filesystem-safe key — one output subfolder per filter slice."""
        parts = list(self.modes) + list(self.difficulties) + [f"{x}HB" for x in self.hands]
        return "__".join(parts) if parts else "all"


def parse_args():
    p = argparse.ArgumentParser(description="StrikeFactor pitch analysis (filterable).")
    p.add_argument("--mode", choices=list(MODE_CHOICES) + ["all"], default="gameday",
                   help="Game mode to include (default: gameday). 'all' = no mode filter.")
    p.add_argument("--difficulty", choices=list(DIFFICULTY_CHOICES) + ["all"],
                   default="hall_of_fame",
                   help="Difficulty to include (default: hall_of_fame). 'all' = no difficulty filter.")
    p.add_argument("--handedness", choices=["L", "R", "all"], default="all",
                   help="Batter handedness to include (default: all). Split L/R to avoid "
                        "smearing inside/outside in location plots.")
    return p.parse_args()


def pitches_where(filt, alias=""):
    """Returns (sql_fragment, params) — sql is prefixed with ' AND ' or empty.

    The fragment filters the pitches table (or any aliased view of it that
    exposes game_mode and difficulty columns directly).
    """
    a = f"{alias}." if alias else ""
    clauses, params = [], []
    if filt.modes:
        clauses.append(f"{a}game_mode IN ({','.join('?' * len(filt.modes))})")
        params.extend(filt.modes)
    if filt.difficulties:
        clauses.append(f"{a}difficulty IN ({','.join('?' * len(filt.difficulties))})")
        params.extend(filt.difficulties)
    if filt.hands:
        clauses.append(f"{a}batter_hand IN ({','.join('?' * len(filt.hands))})")
        params.extend(filt.hands)
    return (" AND " + " AND ".join(clauses) if clauses else "", params)


# Outcomes that terminate an at-bat. Counting pitches whose `outcome` is in
# this set is equivalent to counting completed at-bats — and lets us derive
# AB-level stats from pitches directly, which is the only table that has
# game_mode/difficulty for historical rows. (pitches.ab_id is NULL for
# pre-V2 data and games table is sparse, so neither can be joined reliably.)
TERMINAL_OUTCOMES_TUPLE = (
    "strikeout", "walk", "SINGLE", "DOUBLE", "TRIPLE", "HOME RUN",
    "GROUNDOUT", "FLYOUT", "LINEOUT",
)
TERMINAL_OUTCOMES_SQL = (
    "('strikeout','walk','SINGLE','DOUBLE','TRIPLE','HOME RUN',"
    "'GROUNDOUT','FLYOUT','LINEOUT')"
)


# Module-level filter; set in __main__ from CLI args. Default = today's
# "show me everything" so importing the module doesn't blow up on missing
# state.
FILTER = Filter(modes=(), difficulties=())


# ── Styling ──────────────────────────────────────────────────────────────
plt.rcParams.update({
    "figure.facecolor": "#1a1a2e",
    "axes.facecolor": "#16213e",
    "axes.edgecolor": "#e0e0e0",
    "axes.labelcolor": "#e0e0e0",
    "text.color": "#e0e0e0",
    "xtick.color": "#e0e0e0",
    "ytick.color": "#e0e0e0",
    "grid.color": "#2a2a4a",
    "grid.alpha": 0.5,
    "font.family": "monospace",
    "font.size": 11,
})

PITCH_COLORS = {
    "FF": "#e74c3c",  # Four-Seam Fastball - red
    "SI": "#e67e22",  # Sinker - orange
    "SL": "#3498db",  # Slider - blue
    "CB": "#2ecc71",  # Curveball - green
    "CH": "#9b59b6",  # Changeup - purple
    "FS": "#f39c12",  # Splitter - gold
    "FC": "#1abc9c",  # Cutter - teal (was silently dropped from movement/trajectory plots)
}

PITCH_NAMES = {
    "FF": "Four-Seam",
    "SI": "Sinker",
    "SL": "Slider",
    "CB": "Curveball",
    "CH": "Changeup",
    "FS": "Splitter",
    "FC": "Cutter",
}

PITCHER_DISPLAY = {
    "chrissale": "Chris Sale",
    "jacobdegrom": "Jacob deGrom",
    "rokisasaki": "Roki Sasaki",
    "Yamamoto": "Yoshinobu Yamamoto",
    "shanemcclanahan": "Shane McClanahan",
}

# ── Strike zone (matches gameplay) ───────────────────────────────────────
SZ_X_HALF = 0.83   # ft
SZ_Z_MIN = 1.5
SZ_Z_MAX = 3.5
IN_ZONE_SQL = (
    f"(ABS(plate_x_ft) <= {SZ_X_HALF} "
    f"AND plate_z_ft BETWEEN {SZ_Z_MIN} AND {SZ_Z_MAX})"
)

# Outcome groups
HIT_OUTCOMES = ("SINGLE", "DOUBLE", "TRIPLE", "HOME RUN")
IN_PLAY_OUTCOMES = HIT_OUTCOMES + ("GROUNDOUT", "FLYOUT", "LINEOUT")
OUT_OUTCOMES = ("strikeout", "GROUNDOUT", "FLYOUT", "LINEOUT")

# Maps gameday "opponent_starter" key → pitcher_name as stored in the DB.
GAMEDAY_HISTORY_PATH = os.path.join(
    os.path.dirname(__file__), "strikefactor", "data", "gameday_history.json"
)
STARTER_TO_DB_NAME = {
    "sale": "chrissale",
    "degrom": "jacobdegrom",
    "mcclanahan": "shanemcclanahan",
    "sasaki": "rokisasaki",
    "yamamoto": "Yamamoto",
}

_gameday_runs_cache = None


def _gameday_runs_by_pitcher():
    """Sum runs allowed per pitcher across completed GameDay games.

    Why: at_bats has no game_mode column and the DB doesn't track runs
    scored, but gameday_history.json records final scores per game and
    attributes them to a single starter. Approximate but the only source.

    Honors FILTER.difficulties so ERA tracks the difficulty slice the rest
    of the analysis is showing.
    """
    global _gameday_runs_cache
    if _gameday_runs_cache is not None:
        return _gameday_runs_cache
    runs, games = defaultdict(int), defaultdict(int)
    allowed = set(FILTER.difficulties) if FILTER.difficulties else None
    try:
        with open(GAMEDAY_HISTORY_PATH) as f:
            data = json.load(f)
        for g in data.get("games", []):
            if allowed is not None and g.get("difficulty") not in allowed:
                continue
            db_name = STARTER_TO_DB_NAME.get(str(g.get("opponent_starter", "")).lower())
            if db_name:
                runs[db_name] += g.get("opponent_score", 0)
                games[db_name] += 1
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    _gameday_runs_cache = (dict(runs), dict(games))
    return _gameday_runs_cache


def _format_ip(outs):
    """Render outs as standard IP notation (7 outs → '2.1')."""
    return f"{outs // 3}.{outs % 3}"


def _pct(n, d, digits=1):
    return f"{(100*n/d):.{digits}f}%" if d else "—"


def _ratio(n, d, digits=2):
    return f"{n/d:.{digits}f}" if d else "—"


def _avg(rate):
    """Format a baseball rate (e.g. .305) without leading zero."""
    s = f"{rate:.3f}"
    return s.lstrip("0") if rate < 1 else s


def pitcher_pitch_metrics(pname):
    """Pitch-level (Statcast-style) metrics for one pitcher."""
    where_extra, params = pitches_where(FILTER)
    sql = f"""
        SELECT
            COUNT(*) AS np,
            SUM(CASE WHEN {IN_ZONE_SQL} THEN 1 ELSE 0 END) AS zone,
            SUM(CASE WHEN swing_type > 0 THEN 1 ELSE 0 END) AS swings,
            SUM(CASE WHEN swing_type > 0 AND {IN_ZONE_SQL} THEN 1 ELSE 0 END) AS z_swings,
            SUM(CASE WHEN swing_type > 0 AND NOT {IN_ZONE_SQL} THEN 1 ELSE 0 END) AS o_swings,
            -- whiff = swing-and-miss. on_time==0 is the canonical miss signal;
            -- the old outcome-based test also swept in fouls/contact rows whose
            -- outcome happened to read 'strike'/'strikeout', inflating Whiff%/CSW%.
            SUM(CASE WHEN swing_type > 0 AND on_time = 0 THEN 1 ELSE 0 END) AS whiffs,
            SUM(CASE WHEN swing_type = 0
                       AND outcome IN ('strike','strikeout') THEN 1 ELSE 0 END) AS called_strikes,
            SUM(CASE WHEN outcome IN ('ball','walk') THEN 1 ELSE 0 END) AS balls_thrown,
            SUM(CASE WHEN balls_before = 0 AND strikes_before = 0 THEN 1 ELSE 0 END) AS first_pitches,
            SUM(CASE WHEN balls_before = 0 AND strikes_before = 0
                       AND outcome NOT IN ('ball','walk') THEN 1 ELSE 0 END) AS first_strikes,
            SUM(CASE WHEN strikes_before = 2 THEN 1 ELSE 0 END) AS two_strike_pitches,
            SUM(CASE WHEN strikes_before = 2 AND outcome = 'strikeout' THEN 1 ELSE 0 END) AS putaways
        FROM pitches WHERE pitcher_name = ?{where_extra}
    """
    row = dict(fetch(sql, (pname, *params))[0])
    np_ = row["np"] or 0
    swings = row["swings"] or 0
    zone = row["zone"] or 0
    o_zone = np_ - zone
    return {
        **row,
        "strike_pct": (np_ - row["balls_thrown"]) / np_ if np_ else 0,
        "csw_pct": (row["called_strikes"] + row["whiffs"]) / np_ if np_ else 0,
        "whiff_pct": row["whiffs"] / swings if swings else 0,
        "swing_pct": swings / np_ if np_ else 0,
        "zone_pct": zone / np_ if np_ else 0,
        "z_swing_pct": row["z_swings"] / zone if zone else 0,
        "chase_pct": row["o_swings"] / o_zone if o_zone else 0,
        "f_strike_pct": row["first_strikes"] / row["first_pitches"] if row["first_pitches"] else 0,
        "putaway_pct": row["putaways"] / row["two_strike_pitches"] if row["two_strike_pitches"] else 0,
    }


def pitcher_classic_line(pname):
    """Standard pitcher box-score line (IP, BF, H, R, ER, HR, BB, K, ERA, WHIP).

    Always pinned to GameDay (ERA/WHIP only make sense for full innings),
    but honors the active difficulty filter. Runs are sourced from
    gameday_history.json (see _gameday_runs_by_pitcher).
    """
    # Force gameday regardless of FILTER.modes — classic stats require innings.
    diff_filter = Filter(modes=("gameday",), difficulties=FILTER.difficulties)
    where_extra, params = pitches_where(diff_filter)
    rows = fetch(
        f"SELECT outcome, COUNT(*) AS c FROM pitches "
        f"WHERE pitcher_name = ?{where_extra} "
        f"GROUP BY outcome",
        (pname, *params),
    )
    counts = {r["outcome"]: r["c"] for r in rows}

    bf = sum(counts.get(o, 0) for o in (
        "strikeout", "walk", "SINGLE", "DOUBLE", "TRIPLE", "HOME RUN",
        "GROUNDOUT", "FLYOUT", "LINEOUT",
    ))
    outs = sum(counts.get(o, 0) for o in OUT_OUTCOMES)
    h = sum(counts.get(o, 0) for o in HIT_OUTCOMES)
    bb = counts.get("walk", 0)
    k = counts.get("strikeout", 0)
    hr = counts.get("HOME RUN", 0)

    runs_map, games_map = _gameday_runs_by_pitcher()
    r = runs_map.get(pname, 0)
    games = games_map.get(pname, 0)

    ip = outs / 3 if outs else 0
    return {
        "g": games, "bf": bf, "outs": outs, "ip": ip,
        "h": h, "r": r, "er": r,  # no errors tracked → ER == R
        "hr": hr, "bb": bb, "k": k,
        "era": (r * 9) / ip if ip > 0 else 0,
        "whip": (h + bb) / ip if ip > 0 else 0,
        "k_per_9": (k * 9) / ip if ip > 0 else 0,
        "bb_per_9": (bb * 9) / ip if ip > 0 else 0,
        "hr_per_9": (hr * 9) / ip if ip > 0 else 0,
    }


def pitcher_outcome_metrics(pname):
    """At-bat-level rate stats (K%, BB%, BABIP, wOBA, etc.) for one pitcher."""
    w, params = pitches_where(FILTER)
    rows = fetch(
        f"SELECT outcome AS final_outcome, COUNT(*) AS c FROM pitches "
        f"WHERE pitcher_name = ? AND outcome IN {TERMINAL_OUTCOMES_SQL}{w} "
        f"GROUP BY outcome",
        (pname, *params),
    )
    counts = {r["final_outcome"]: r["c"] for r in rows}
    pa = sum(counts.values())
    bb = counts.get("walk", 0)
    k = counts.get("strikeout", 0)
    s = counts.get("SINGLE", 0)
    d = counts.get("DOUBLE", 0)
    t = counts.get("TRIPLE", 0)
    hr = counts.get("HOME RUN", 0)
    go = counts.get("GROUNDOUT", 0)
    ao = counts.get("FLYOUT", 0) + counts.get("LINEOUT", 0)
    h = s + d + t + hr
    ab = pa - bb
    bip = ab - k - hr  # balls in play
    tb = s + 2 * d + 3 * t + 4 * hr
    avg = h / ab if ab else 0
    obp = (h + bb) / pa if pa else 0
    slg = tb / ab if ab else 0
    # wOBA (linear-weights, simplified — no HBP/SF/IBB tracked)
    woba = (0.69 * bb + 0.89 * s + 1.27 * d + 1.62 * t + 2.10 * hr) / pa if pa else 0
    babip = (h - hr) / bip if bip > 0 else 0
    p_where, p_params = pitches_where(FILTER)
    pitches = fetch(
        f"SELECT COUNT(*) AS c FROM pitches WHERE pitcher_name = ?{p_where}",
        (pname, *p_params),
    )[0]["c"]
    return {
        "pa": pa, "ab": ab, "h": h, "bb": bb, "k": k, "hr": hr,
        "go": go, "ao": ao, "tb": tb, "bip": bip, "pitches": pitches,
        "avg": avg, "obp": obp, "slg": slg, "ops": obp + slg,
        "iso": slg - avg, "babip": babip, "woba": woba,
        "k_pct": k / pa if pa else 0,
        "bb_pct": bb / pa if pa else 0,
        "k_minus_bb_pct": (k - bb) / pa if pa else 0,
        "k_per_bb": k / bb if bb else float("inf"),
        "hr_pct": hr / pa if pa else 0,
        "go_ao": go / ao if ao else float("inf"),
        "p_per_pa": pitches / pa if pa else 0,
    }


def _save_empty_figure(filename, title):
    """Render a placeholder figure when the active filter yields no data."""
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.suptitle(f"{title}\n{FILTER.label}", fontsize=14, fontweight="bold")
    ax.text(0.5, 0.5, f"No pitches match the active filter:\n{FILTER.label}",
            ha="center", va="center", fontsize=13, color="#888")
    ax.axis("off")
    fig.savefig(os.path.join(OUT_DIR, filename), dpi=150, bbox_inches="tight")
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 1: Pitch Arsenal Speed Distributions (violin/box per pitcher)
# ═══════════════════════════════════════════════════════════════════════
def fig1_speed_distributions():
    w, p = pitches_where(FILTER)
    pitchers = fetch(f"SELECT DISTINCT pitcher_name FROM pitches WHERE 1=1{w}", p)
    pitcher_names = [r["pitcher_name"] for r in pitchers]
    if not pitcher_names:
        _save_empty_figure("01_speed_distributions.png",
                           "Pitch Speed Distributions by Pitcher")
        print("  [1/9] Speed distributions (no data)")
        return

    fig, axes = plt.subplots(1, len(pitcher_names), figsize=(18, 6), sharey=True)
    if len(pitcher_names) == 1:
        axes = [axes]
    fig.suptitle(f"Pitch Speed Distributions by Pitcher\n{FILTER.label}",
                 fontsize=16, fontweight="bold", y=0.98)

    for ax, pname in zip(axes, pitcher_names):
        types = fetch(
            f"SELECT DISTINCT pitch_type FROM pitches WHERE pitcher_name = ?{w}",
            (pname, *p),
        )
        data, labels, colors = [], [], []
        for pt in types:
            pt_name = pt["pitch_type"]
            speeds = [r["speed_mph"] for r in fetch(
                f"SELECT speed_mph FROM pitches WHERE pitcher_name = ? AND pitch_type = ?{w}",
                (pname, pt_name, *p),
            )]
            if speeds:
                data.append(speeds)
                labels.append(f"{pt_name}\n({len(speeds)})")
                colors.append(PITCH_COLORS.get(pt_name, "#888"))

        if data:
            vp = ax.violinplot(data, showmeans=True, showmedians=True)
            for i, body in enumerate(vp["bodies"]):
                body.set_facecolor(colors[i])
                body.set_alpha(0.7)
            vp["cmeans"].set_color("#fff")
            vp["cmedians"].set_color("#ffff00")
            ax.set_xticks(range(1, len(labels) + 1))
            ax.set_xticklabels(labels, fontsize=9)

        ax.set_title(PITCHER_DISPLAY.get(pname, pname), fontsize=11, fontweight="bold")
        ax.grid(True, axis="y")

    axes[0].set_ylabel("Speed (mph)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "01_speed_distributions.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [1/9] Speed distributions")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 2: Pitch Location Scatter (plate_x vs plate_z with strikezone)
# ═══════════════════════════════════════════════════════════════════════
def fig2_pitch_locations():
    w, p = pitches_where(FILTER)
    pitchers = fetch(f"SELECT DISTINCT pitcher_name FROM pitches WHERE 1=1{w}", p)
    pitcher_names = [r["pitcher_name"] for r in pitchers]
    if not pitcher_names:
        _save_empty_figure("02_pitch_locations.png", "Pitch Locations at the Plate")
        print("  [2/9] Pitch locations (no data)")
        return

    fig, axes = plt.subplots(1, len(pitcher_names), figsize=(20, 5))
    if len(pitcher_names) == 1:
        axes = [axes]
    fig.suptitle(f"Pitch Locations at the Plate\n{FILTER.label}",
                 fontsize=16, fontweight="bold", y=1.02)

    # Strike zone approx: x ∈ [-0.83, 0.83] ft, z ∈ [1.5, 3.5] ft
    sz_x, sz_w = -0.83, 1.66
    sz_z, sz_h = 1.5, 2.0

    for ax, pname in zip(axes, pitcher_names):
        rows = fetch(
            f"SELECT plate_x_ft, plate_z_ft, pitch_type FROM pitches WHERE pitcher_name = ?{w}",
            (pname, *p),
        )
        for pt in set(r["pitch_type"] for r in rows):
            xs = [r["plate_x_ft"] for r in rows if r["pitch_type"] == pt]
            zs = [r["plate_z_ft"] for r in rows if r["pitch_type"] == pt]
            ax.scatter(xs, zs, c=PITCH_COLORS.get(pt, "#888"), label=PITCH_NAMES.get(pt, pt),
                       alpha=0.6, s=30, edgecolors="white", linewidths=0.3)

        rect = patches.Rectangle((sz_x, sz_z), sz_w, sz_h, linewidth=2,
                                  edgecolor="#ffffff", facecolor="none", linestyle="--")
        ax.add_patch(rect)
        ax.set_xlim(-2.5, 2.5)
        ax.set_ylim(0, 5)
        ax.set_aspect("equal")
        ax.set_title(PITCHER_DISPLAY.get(pname, pname), fontsize=10, fontweight="bold")
        ax.set_xlabel("Horizontal (ft)")
        ax.legend(fontsize=7, loc="upper right")

    axes[0].set_ylabel("Vertical (ft)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "02_pitch_locations.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [2/9] Pitch locations")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 3: Pitch Movement Plot (pfx_x vs pfx_z, Statcast-style)
# ═══════════════════════════════════════════════════════════════════════
def fig3_movement_plot():
    fig, ax = plt.subplots(figsize=(9, 8))
    ax.set_title(f"Pitch Movement Profile (All Pitchers) — {FILTER.label}",
                 fontsize=13, fontweight="bold")

    w, p = pitches_where(FILTER)
    any_data = False
    for pt in PITCH_COLORS:
        rows = fetch(
            f"SELECT pfx_x_inches, pfx_z_inches FROM pitches WHERE pitch_type = ?{w}",
            (pt, *p),
        )
        if not rows:
            continue
        any_data = True
        xs = [r["pfx_x_inches"] for r in rows]
        zs = [r["pfx_z_inches"] for r in rows]
        ax.scatter(xs, zs, c=PITCH_COLORS[pt], label=f"{PITCH_NAMES.get(pt, pt)} ({len(rows)})",
                   alpha=0.55, s=40, edgecolors="white", linewidths=0.4)
        # Draw mean marker
        ax.scatter(np.mean(xs), np.mean(zs), c=PITCH_COLORS[pt], s=200,
                   marker="X", edgecolors="white", linewidths=1.5, zorder=5)

    if not any_data:
        ax.text(0.5, 0.5, f"No pitches match:\n{FILTER.label}",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=13, color="#888")
    ax.axhline(0, color="#555", linewidth=0.8)
    ax.axvline(0, color="#555", linewidth=0.8)
    ax.set_xlabel("Horizontal Break (inches)")
    ax.set_ylabel("Induced Vertical Break (inches)")
    ax.legend(fontsize=10, loc="upper left")
    ax.grid(True)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "03_pitch_movement.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [3/9] Movement plot")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 4: At-Bat Outcome Breakdown (stacked bar by pitcher)
# ═══════════════════════════════════════════════════════════════════════
def fig4_outcome_breakdown():
    w, p = pitches_where(FILTER)
    pitchers = fetch(
        f"SELECT DISTINCT pitcher_name FROM pitches "
        f"WHERE outcome IN {TERMINAL_OUTCOMES_SQL}{w}",
        p,
    )
    pitcher_names = [r["pitcher_name"] for r in pitchers]
    if not pitcher_names:
        _save_empty_figure("04_outcome_breakdown.png", "At-Bat Outcomes by Pitcher")
        print("  [4/9] Outcome breakdown (no data)")
        return

    outcome_order = ["strikeout", "GROUNDOUT", "FLYOUT", "LINEOUT", "SINGLE", "DOUBLE", "TRIPLE", "HOME RUN", "walk"]
    outcome_colors = {
        "strikeout": "#e74c3c", "GROUNDOUT": "#95a5a6", "FLYOUT": "#7f8c8d",
        "LINEOUT": "#bdc3c7", "SINGLE": "#2ecc71", "DOUBLE": "#27ae60",
        "TRIPLE": "#1abc9c", "HOME RUN": "#f1c40f", "walk": "#3498db",
    }

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.suptitle(f"At-Bat Outcomes by Pitcher — {FILTER.label}",
                 fontsize=14, fontweight="bold")

    x = np.arange(len(pitcher_names))
    bottoms = np.zeros(len(pitcher_names))

    for outcome in outcome_order:
        counts = []
        for pname in pitcher_names:
            rows = fetch(
                f"SELECT COUNT(*) as c FROM pitches "
                f"WHERE pitcher_name = ? AND outcome = ?{w}",
                (pname, outcome, *p),
            )
            counts.append(rows[0]["c"])
        counts = np.array(counts, dtype=float)
        if counts.sum() > 0:
            ax.bar(x, counts, bottom=bottoms, color=outcome_colors.get(outcome, "#888"),
                   label=outcome, edgecolor="#1a1a2e", linewidth=0.5)
            bottoms += counts

    ax.set_xticks(x)
    ax.set_xticklabels([PITCHER_DISPLAY.get(p, p) for p in pitcher_names], fontsize=10)
    ax.set_ylabel("Count")
    ax.legend(fontsize=9, loc="upper right", ncol=2)
    ax.grid(True, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "04_outcome_breakdown.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [4/9] Outcome breakdown")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 5: Pitch Type Usage by Count (heatmap)
# ═══════════════════════════════════════════════════════════════════════
def fig5_pitch_by_count():
    w, p = pitches_where(FILTER)
    rows = fetch(
        f"SELECT balls_before, strikes_before, pitch_type, COUNT(*) as c "
        f"FROM pitches WHERE 1=1{w} "
        f"GROUP BY balls_before, strikes_before, pitch_type",
        p,
    )

    counts_map = defaultdict(lambda: defaultdict(int))
    all_types = set()
    for r in rows:
        count_str = f"{r['balls_before']}-{r['strikes_before']}"
        counts_map[count_str][r["pitch_type"]] += r["c"]
        all_types.add(r["pitch_type"])

    if not all_types:
        _save_empty_figure("05_pitch_by_count.png", "Pitch Type Usage % by Count")
        print("  [5/9] Pitch by count (no data)")
        return

    count_order = ["0-0", "0-1", "0-2", "1-0", "1-1", "1-2", "2-0", "2-1", "2-2", "3-0", "3-1", "3-2"]
    count_order = [c for c in count_order if c in counts_map]
    type_order = sorted(all_types)

    matrix = np.zeros((len(type_order), len(count_order)))
    for j, cnt in enumerate(count_order):
        total = sum(counts_map[cnt].values())
        for i, pt in enumerate(type_order):
            matrix[i, j] = counts_map[cnt].get(pt, 0) / total * 100 if total > 0 else 0

    fig, ax = plt.subplots(figsize=(12, 5))
    im = ax.imshow(matrix, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(len(count_order)))
    ax.set_xticklabels(count_order)
    ax.set_yticks(range(len(type_order)))
    ax.set_yticklabels([PITCH_NAMES.get(t, t) for t in type_order])
    ax.set_xlabel("Count (B-S)")
    ax.set_title(f"Pitch Type Usage % by Count — {FILTER.label}",
                 fontsize=13, fontweight="bold")

    # Annotate cells
    for i in range(len(type_order)):
        for j in range(len(count_order)):
            val = matrix[i, j]
            if val > 0:
                color = "white" if val > 30 else "#e0e0e0"
                ax.text(j, i, f"{val:.0f}%", ha="center", va="center", fontsize=8, color=color)

    plt.colorbar(im, ax=ax, label="Usage %", shrink=0.8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "05_pitch_by_count.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [5/9] Pitch by count heatmap")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 6: 3D Pitch Trajectories (side view: y vs z, colored by type)
# ═══════════════════════════════════════════════════════════════════════
def fig6_trajectories():
    # Sample a few pitches per type for clarity
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle(f"Pitch Trajectories (sampled) — {FILTER.label}",
                 fontsize=14, fontweight="bold")

    w, p = pitches_where(FILTER)
    # Side view (y vs z) and top view (y vs x)
    for pt in PITCH_COLORS:
        pitch_ids = fetch(
            f"SELECT pitch_id FROM pitches WHERE pitch_type = ?{w} "
            f"ORDER BY RANDOM() LIMIT 8",
            (pt, *p),
        )
        for pid_row in pitch_ids:
            traj = fetch(
                "SELECT y_ft, z_ft, x_ft FROM pitch_trajectories WHERE pitch_id = ? ORDER BY sample_idx",
                (pid_row["pitch_id"],)
            )
            if not traj:
                continue
            ys = [r["y_ft"] for r in traj]
            zs = [r["z_ft"] for r in traj]
            xs = [r["x_ft"] for r in traj]
            axes[0].plot(ys, zs, color=PITCH_COLORS[pt], alpha=0.4, linewidth=1.2)
            axes[1].plot(ys, xs, color=PITCH_COLORS[pt], alpha=0.4, linewidth=1.2)

    # Add strikezone reference on side view
    axes[0].axhspan(1.5, 3.5, xmin=0.95, xmax=1.0, color="#ffffff", alpha=0.3)
    axes[0].set_xlabel("Distance from Plate (ft)")
    axes[0].set_ylabel("Height (ft)")
    axes[0].set_title("Side View (height vs distance)")
    axes[0].invert_xaxis()
    axes[0].grid(True)

    axes[1].set_xlabel("Distance from Plate (ft)")
    axes[1].set_ylabel("Horizontal Position (ft)")
    axes[1].set_title("Top View (horizontal vs distance)")
    axes[1].invert_xaxis()
    axes[1].grid(True)

    # Shared legend
    from matplotlib.lines import Line2D
    legend_elements = [Line2D([0], [0], color=c, label=PITCH_NAMES.get(pt, pt), linewidth=2)
                       for pt, c in PITCH_COLORS.items()]
    fig.legend(handles=legend_elements, loc="lower center", ncol=6, fontsize=10,
               bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "06_trajectories.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [6/9] Pitch trajectories")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 7: Strike/Ball/Hit Rates + Swing Summary Dashboard
# ═══════════════════════════════════════════════════════════════════════
def fig7_dashboard():
    fig = plt.figure(figsize=(16, 13))
    fig.suptitle(f"StrikeFactor Session Dashboard — {FILTER.label}",
                 fontsize=16, fontweight="bold", y=0.99)
    gs = GridSpec(3, 3, figure=fig, hspace=0.40, wspace=0.30,
                  height_ratios=[0.8, 1.0, 1.0])

    pw, pp = pitches_where(FILTER)

    # ── Panel HEADLINE: Classic pitching line (GameDay) ────────────
    # Pitcher list derived from pitches with terminal outcomes (= completed
    # at-bats) so it honors the active filter even on historical data.
    ax_h = fig.add_subplot(gs[0, :])
    pitchers_all = [r["pitcher_name"] for r in fetch(
        f"SELECT DISTINCT pitcher_name FROM pitches "
        f"WHERE outcome IN {TERMINAL_OUTCOMES_SQL}{pw}",
        pp,
    )]
    line_rows = []
    for pn in pitchers_all:
        c = pitcher_classic_line(pn)
        if c["bf"] == 0:  # never faced in GameDay
            continue
        line_rows.append([
            PITCHER_DISPLAY.get(pn, pn),
            c["g"], _format_ip(c["outs"]), c["bf"],
            c["h"], c["r"], c["er"], c["hr"], c["bb"], c["k"],
            f"{c['era']:.2f}" if c["ip"] else "—",
            f"{c['whip']:.2f}" if c["ip"] else "—",
            f"{c['k_per_9']:.1f}" if c["ip"] else "—",
        ])
    line_cols = ["Pitcher", "G", "IP", "BF", "H", "R", "ER", "HR",
                 "BB", "K", "ERA", "WHIP", "K/9"]
    if line_rows:
        tbl_h = ax_h.table(cellText=line_rows, colLabels=line_cols,
                           loc="center", cellLoc="center")
        tbl_h.auto_set_font_size(False)
        tbl_h.set_fontsize(11)
        tbl_h.scale(1, 1.7)
        for (r, c), cell in tbl_h.get_celld().items():
            cell.set_edgecolor("#2a2a4a")
            if r == 0:
                cell.set_facecolor("#1f4068")
                cell.set_text_props(fontweight="bold", color="#ffffff")
            else:
                cell.set_facecolor("#16213e")
                cell.set_text_props(color="#e0e0e0")
        ax_h.set_title("Pitching Line — GameDay (R from final scores; ER = R, no errors tracked)",
                       fontweight="bold", pad=12, fontsize=12)
    else:
        ax_h.text(0.5, 0.5, f"No GameDay innings recorded for {FILTER.label}",
                  ha="center", va="center", fontsize=12, color="#888")
        ax_h.set_title("Pitching Line — GameDay", fontweight="bold", pad=12, fontsize=12)
    ax_h.axis("off")

    # Panel A: Strike rate by pitch type
    ax_a = fig.add_subplot(gs[1, 0])
    types = fetch(
        f"SELECT pitch_type, SUM(is_strike) as strikes, COUNT(*) as total "
        f"FROM pitches WHERE 1=1{pw} GROUP BY pitch_type ORDER BY pitch_type",
        pp,
    )
    names = [PITCH_NAMES.get(r["pitch_type"], r["pitch_type"]) for r in types]
    rates = [r["strikes"] / r["total"] * 100 for r in types]
    colors = [PITCH_COLORS.get(r["pitch_type"], "#888") for r in types]
    ax_a.barh(names, rates, color=colors, edgecolor="#1a1a2e")
    ax_a.set_xlabel("Strike %")
    ax_a.set_title("Strike Rate by Pitch Type", fontweight="bold")
    for i, v in enumerate(rates):
        ax_a.text(v + 1, i, f"{v:.0f}%", va="center", fontsize=9)

    # Panel B: Swing rate (swing_type > 0) by pitch type
    ax_b = fig.add_subplot(gs[1, 1])
    swing_data = fetch(
        f"SELECT pitch_type, SUM(CASE WHEN swing_type > 0 THEN 1 ELSE 0 END) as swings, COUNT(*) as total "
        f"FROM pitches WHERE 1=1{pw} GROUP BY pitch_type ORDER BY pitch_type",
        pp,
    )
    names_b = [PITCH_NAMES.get(r["pitch_type"], r["pitch_type"]) for r in swing_data]
    swing_rates = [r["swings"] / r["total"] * 100 for r in swing_data]
    colors_b = [PITCH_COLORS.get(r["pitch_type"], "#888") for r in swing_data]
    ax_b.barh(names_b, swing_rates, color=colors_b, edgecolor="#1a1a2e")
    ax_b.set_xlabel("Swing %")
    ax_b.set_title("Swing Rate by Pitch Type", fontweight="bold")
    for i, v in enumerate(swing_rates):
        ax_b.text(v + 1, i, f"{v:.0f}%", va="center", fontsize=9)

    # Panel C: Pitch count pie chart
    ax_c = fig.add_subplot(gs[1, 2])
    type_counts = fetch(
        f"SELECT pitch_type, COUNT(*) as c FROM pitches WHERE 1=1{pw} "
        f"GROUP BY pitch_type ORDER BY c DESC",
        pp,
    )
    wedge_labels = [PITCH_NAMES.get(r["pitch_type"], r["pitch_type"]) for r in type_counts]
    wedge_sizes = [r["c"] for r in type_counts]
    wedge_colors = [PITCH_COLORS.get(r["pitch_type"], "#888") for r in type_counts]
    if wedge_sizes:
        ax_c.pie(wedge_sizes, labels=wedge_labels, colors=wedge_colors, autopct="%1.0f%%",
                 textprops={"fontsize": 9, "color": "#e0e0e0"}, pctdistance=0.75,
                 wedgeprops={"edgecolor": "#1a1a2e", "linewidth": 1})
    else:
        ax_c.text(0.5, 0.5, "No data", ha="center", va="center",
                  fontsize=11, color="#888")
        ax_c.axis("off")
    ax_c.set_title("Pitch Type Distribution", fontweight="bold")

    # Panel D: Batting line by pitcher (slash line + rate stats)
    ax_d = fig.add_subplot(gs[2, 0:2])
    pitchers = fetch(
        f"SELECT DISTINCT pitcher_name FROM pitches "
        f"WHERE outcome IN {TERMINAL_OUTCOMES_SQL}{pw}",
        pp,
    )
    table_data = []
    for p in pitchers:
        pn = p["pitcher_name"]
        m = pitcher_outcome_metrics(pn)
        table_data.append([
            PITCHER_DISPLAY.get(pn, pn),
            m["pa"], m["h"], m["hr"], m["bb"], m["k"],
            _avg(m["avg"]), _avg(m["obp"]), _avg(m["slg"]), _avg(m["ops"]),
            _pct(m["k"], m["pa"]),
            _pct(m["bb"], m["pa"]),
            _avg(m["babip"]) if m["bip"] else "—",
            _avg(m["woba"]),
        ])

    col_labels = ["Pitcher", "PA", "H", "HR", "BB", "K",
                  "AVG", "OBP", "SLG", "OPS", "K%", "BB%", "BABIP", "wOBA"]
    if table_data:
        table = ax_d.table(cellText=table_data, colLabels=col_labels, loc="center",
                            cellLoc="center")
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.6)
        for (row, col), cell in table.get_celld().items():
            cell.set_edgecolor("#2a2a4a")
            if row == 0:
                cell.set_facecolor("#2c3e50")
                cell.set_text_props(fontweight="bold", color="#e0e0e0")
            else:
                cell.set_facecolor("#16213e")
                cell.set_text_props(color="#e0e0e0")
    else:
        ax_d.text(0.5, 0.5, f"No at-bats match {FILTER.label}",
                  ha="center", va="center", fontsize=12, color="#888")
    ax_d.axis("off")
    ax_d.set_title("Batting Performance vs Each Pitcher", fontweight="bold", pad=20)

    # Panel E: Pitch speed box by pitcher
    ax_e = fig.add_subplot(gs[2, 2])
    pitcher_names = [r["pitcher_name"] for r in fetch(
        f"SELECT DISTINCT pitcher_name FROM pitches WHERE 1=1{pw}", pp,
    )]
    speed_data = []
    labels_e = []
    for pn in pitcher_names:
        speeds = [r["speed_mph"] for r in fetch(
            f"SELECT speed_mph FROM pitches WHERE pitcher_name = ?{pw}",
            (pn, *pp),
        )]
        if speeds:
            speed_data.append(speeds)
            labels_e.append(PITCHER_DISPLAY.get(pn, pn).split()[-1])  # Last name only

    if speed_data:
        try:
            bp = ax_e.boxplot(speed_data, patch_artist=True, tick_labels=labels_e)
        except TypeError:  # matplotlib < 3.9 still uses the old 'labels' kwarg
            bp = ax_e.boxplot(speed_data, patch_artist=True, labels=labels_e)
        palette = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6"]
        for patch, color in zip(bp["boxes"], palette):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
    else:
        ax_e.text(0.5, 0.5, "No data", ha="center", va="center",
                  fontsize=11, color="#888")
    ax_e.set_ylabel("Speed (mph)")
    ax_e.set_title("Speed Range by Pitcher", fontweight="bold")
    ax_e.tick_params(axis="x", rotation=30)
    ax_e.grid(True, axis="y")

    fig.savefig(os.path.join(OUT_DIR, "07_dashboard.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [7/9] Dashboard")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 8: Pitcher Plate Discipline / Statcast-style profile
# ═══════════════════════════════════════════════════════════════════════
def fig8_plate_discipline():
    w, p = pitches_where(FILTER)
    pitchers = [r["pitcher_name"] for r in fetch(
        f"SELECT DISTINCT pitcher_name FROM pitches "
        f"WHERE outcome IN {TERMINAL_OUTCOMES_SQL}{w}",
        p,
    )]
    if not pitchers:
        _save_empty_figure("08_plate_discipline.png",
                           "Pitcher Plate-Discipline & Rate Stats")
        print("  [8/9] Plate-discipline summary (no data)")
        return

    fig = plt.figure(figsize=(16, 9))
    fig.suptitle(f"Pitcher Plate-Discipline & Rate Stats — {FILTER.label}",
                 fontsize=15, fontweight="bold", y=0.98)
    gs = GridSpec(2, 2, figure=fig, height_ratios=[1.4, 1.0], hspace=0.35, wspace=0.25)

    # ── Top: full Statcast-style table ────────────────────────────────
    ax_t = fig.add_subplot(gs[0, :])
    cols = ["Pitcher", "TBF", "NP", "P/PA",
            "K%", "BB%", "K-BB%", "K/BB",
            "CSW%", "Whiff%", "Swing%", "Zone%", "Chase%", "F-Strike%",
            "GO/AO", "BABIP", "wOBA"]
    rows = []
    for pn in pitchers:
        o = pitcher_outcome_metrics(pn)
        p = pitcher_pitch_metrics(pn)
        rows.append([
            PITCHER_DISPLAY.get(pn, pn),
            o["pa"], o["pitches"], f"{o['p_per_pa']:.2f}",
            _pct(o["k"], o["pa"]),
            _pct(o["bb"], o["pa"]),
            _pct(o["k"] - o["bb"], o["pa"]),
            f"{o['k_per_bb']:.2f}" if o["bb"] else "—",
            f"{p['csw_pct']*100:.1f}%",
            f"{p['whiff_pct']*100:.1f}%",
            f"{p['swing_pct']*100:.1f}%",
            f"{p['zone_pct']*100:.1f}%",
            f"{p['chase_pct']*100:.1f}%",
            f"{p['f_strike_pct']*100:.1f}%",
            f"{o['go_ao']:.2f}" if o["ao"] else "—",
            _avg(o["babip"]) if o["bip"] else "—",
            _avg(o["woba"]),
        ])

    table = ax_t.table(cellText=rows, colLabels=cols, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.7)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor("#2a2a4a")
        if r == 0:
            cell.set_facecolor("#2c3e50")
            cell.set_text_props(fontweight="bold", color="#e0e0e0")
        else:
            cell.set_facecolor("#16213e")
            cell.set_text_props(color="#e0e0e0")
    ax_t.axis("off")
    ax_t.set_title("Per-Pitcher Statcast Summary", fontweight="bold", pad=12)

    # ── Bottom-left: CSW% / Whiff% / Chase% grouped bars ──────────────
    ax_l = fig.add_subplot(gs[1, 0])
    short_names = [PITCHER_DISPLAY.get(pn, pn).split()[-1] for pn in pitchers]
    metrics_data = {"CSW%": [], "Whiff%": [], "Chase%": []}
    for pn in pitchers:
        p = pitcher_pitch_metrics(pn)
        metrics_data["CSW%"].append(p["csw_pct"] * 100)
        metrics_data["Whiff%"].append(p["whiff_pct"] * 100)
        metrics_data["Chase%"].append(p["chase_pct"] * 100)
    width = 0.27
    x = np.arange(len(short_names))
    bar_colors = {"CSW%": "#e74c3c", "Whiff%": "#f39c12", "Chase%": "#3498db"}
    for i, (label, vals) in enumerate(metrics_data.items()):
        ax_l.bar(x + (i - 1) * width, vals, width, label=label,
                 color=bar_colors[label], edgecolor="#1a1a2e")
    ax_l.set_xticks(x)
    ax_l.set_xticklabels(short_names, rotation=20, fontsize=9)
    ax_l.set_ylabel("Percent")
    ax_l.set_title("Stuff & Discipline by Pitcher", fontweight="bold")
    ax_l.legend(fontsize=9)
    ax_l.grid(True, axis="y")

    # ── Bottom-right: K% vs BB% scatter (with K-BB% iso-lines) ────────
    ax_r = fig.add_subplot(gs[1, 1])
    palette = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6"]
    for i, pn in enumerate(pitchers):
        o = pitcher_outcome_metrics(pn)
        ax_r.scatter(o["bb_pct"] * 100, o["k_pct"] * 100,
                     s=220, c=palette[i % len(palette)],
                     edgecolors="white", linewidths=1.4, zorder=3)
        ax_r.annotate(short_names[i], (o["bb_pct"] * 100, o["k_pct"] * 100),
                      xytext=(8, 4), textcoords="offset points", fontsize=9)
    # MLB-average reference lines (~22% K, ~8% BB, 2024)
    ax_r.axhline(22, color="#888", linewidth=0.8, linestyle=":", alpha=0.7)
    ax_r.axvline(8, color="#888", linewidth=0.8, linestyle=":", alpha=0.7)
    ax_r.text(8.2, ax_r.get_ylim()[1] * 0.0 + 1, "MLB BB% ≈ 8", fontsize=7, color="#888")
    ax_r.set_xlabel("BB%")
    ax_r.set_ylabel("K%")
    ax_r.set_title("K% vs BB% (upper-left = dominant)", fontweight="bold")
    ax_r.grid(True)

    fig.savefig(os.path.join(OUT_DIR, "08_plate_discipline.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [8/9] Plate-discipline summary")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 9: Pitch-Type Scouting Card
# ═══════════════════════════════════════════════════════════════════════

# Per-metric MLB reference points (poor / avg / elite). Each column is
# colored independently using these thresholds — green = better than league
# average from the pitcher's perspective, red = worse. xBA flips because
# lower is better.
SCOUTING_BENCH = {
    # higher-is-better metrics
    "CSW%":     (26.0, 30.0, 34.0),
    "Whiff%":   (18.0, 24.0, 32.0),
    "Chase%":   (25.0, 31.0, 36.0),
    "PutAway%": (17.0, 21.0, 25.0),
    # lower-is-better — elite < avg < poor flips the score automatically
    "xBA":      (0.270, 0.245, 0.220),
}


def _scouting_score(val, key, col_min, col_max):
    """Return a directional score in [-1, +1]: +1 = elite, -1 = poor.

    Anchored on MLB average (score = 0). The green/red endpoints extend to
    whichever is more extreme — the MLB poor/elite threshold or the column's
    own min/max. That way the gradient stretches across whatever range the
    data actually occupies (avoids "everything saturated green" when the
    whole dataset sits above MLB average).
    """
    poor, avg, elite = SCOUTING_BENCH[key]
    higher_better = (elite > avg)
    if higher_better:
        if val < avg:
            denom = avg - min(col_min, poor)
            return -min(1.0, (avg - val) / denom) if denom else 0.0
        denom = max(col_max, elite) - avg
        return min(1.0, (val - avg) / denom) if denom else 0.0
    # xBA — lower is better; poor sits above avg, elite below
    if val > avg:
        denom = max(col_max, poor) - avg
        return -min(1.0, (val - avg) / denom) if denom else 0.0
    denom = avg - min(col_min, elite)
    return min(1.0, (avg - val) / denom) if denom else 0.0


def _scouting_color(val, key, col_stats):
    """Pick a fill color for a single scouting-card cell.

    col_stats: dict mapping metric key -> (min, max) across the rendered rows.
    """
    bad = (192, 57, 43)        # #c0392b
    neutral = (236, 219, 143)  # #ecdb8f — pale cream around league avg
    good = (39, 174, 96)       # #27ae60
    usage_lo = (45, 55, 72)    # #2d3748
    usage_hi = (49, 130, 206)  # #3182ce

    def blend(c1, c2, t):
        return tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))

    def to_hex(c):
        return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"

    if key == "Usage%":
        mx = col_stats[key][1]
        t = (val / mx) if mx else 0
        return to_hex(blend(usage_lo, usage_hi, t))

    col_min, col_max = col_stats[key]
    score = _scouting_score(val, key, col_min, col_max)
    if score >= 0:
        return to_hex(blend(neutral, good, score))
    return to_hex(blend(neutral, bad, -score))


def _text_color_for(bg_hex):
    """Pick black or white text for adequate contrast on a given fill."""
    r, g, b = (int(bg_hex[i:i+2], 16) for i in (1, 3, 5))
    # YIQ luminance — standard formula for contrast decisions
    return "#1a1a2e" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"


def _format_scouting_value(val, key):
    if key == "xBA":
        s = f"{val:.3f}"
        return s.lstrip("0") if val < 1 else s
    return f"{val:.0f}%"


def fig9_pitch_type_performance():
    """One-glance scouting card: which pitch types are working, vs MLB.

    Each column has its own directional palette anchored on MLB benchmarks
    so a green cell always means "good for the pitcher" — regardless of
    whether the metric reads higher- or lower-is-better.
    """
    w, p = pitches_where(FILTER)
    types = [r["pitch_type"] for r in fetch(
        f"SELECT pitch_type, COUNT(*) c FROM pitches WHERE 1=1{w} "
        f"GROUP BY pitch_type HAVING c >= 20 ORDER BY c DESC",
        p,
    )]
    if not types:
        _save_empty_figure("09_pitch_type_performance.png",
                           "Pitch-Type Scouting Card")
        print("  [9/9] Skipped (no pitch types with enough samples)")
        return

    total_pitches = fetch(
        f"SELECT COUNT(*) c FROM pitches WHERE 1=1{w}", p,
    )[0]["c"] or 1

    rows = []
    for pt in types:
        sql = f"""
            SELECT
                COUNT(*) AS np,
                SUM(CASE WHEN swing_type > 0 THEN 1 ELSE 0 END) AS swings,
                SUM(CASE WHEN swing_type > 0 AND on_time = 0 THEN 1 ELSE 0 END) AS whiffs,
                SUM(CASE WHEN swing_type = 0 AND outcome IN ('strike','strikeout')
                         THEN 1 ELSE 0 END) AS called_strikes,
                SUM(CASE WHEN {IN_ZONE_SQL} THEN 1 ELSE 0 END) AS zone,
                SUM(CASE WHEN swing_type > 0 AND NOT {IN_ZONE_SQL} THEN 1 ELSE 0 END) AS o_swings,
                SUM(CASE WHEN strikes_before = 2 THEN 1 ELSE 0 END) AS two_strike,
                SUM(CASE WHEN strikes_before = 2 AND outcome = 'strikeout' THEN 1 ELSE 0 END) AS putaway,
                SUM(CASE WHEN outcome IN ('GROUNDOUT','FLYOUT','LINEOUT',
                                          'SINGLE','DOUBLE','TRIPLE','HOME RUN')
                         THEN 1 ELSE 0 END) AS bip,
                SUM(CASE WHEN outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN')
                         THEN 1 ELSE 0 END) AS hits
            FROM pitches WHERE pitch_type = ?{w}
        """
        r = dict(fetch(sql, (pt, *p))[0])
        np_ = r["np"] or 1
        swings = r["swings"] or 0
        o_zone = np_ - (r["zone"] or 0)
        # xBA proxy: hits / (balls in play + whiffs) — every swing-and-miss
        # counts as an out, so this approximates MLB Statcast xBA's role.
        ab_proxy = (r["bip"] or 0) + (r["whiffs"] or 0)
        rows.append({
            "type":     pt,
            "Usage%":   100 * np_ / total_pitches,
            "CSW%":     100 * ((r["called_strikes"] or 0) + (r["whiffs"] or 0)) / np_,
            "Whiff%":   100 * (r["whiffs"] or 0) / swings if swings else 0,
            "Chase%":   100 * (r["o_swings"] or 0) / o_zone if o_zone else 0,
            "PutAway%": 100 * (r["putaway"] or 0) / r["two_strike"] if r["two_strike"] else 0,
            "xBA":      (r["hits"] or 0) / ab_proxy if ab_proxy else 0,
        })

    # Most-thrown pitches at top — the eye lands where it matters most.
    rows.sort(key=lambda x: -x["Usage%"])

    metric_keys = ["Usage%", "CSW%", "Whiff%", "Chase%", "PutAway%", "xBA"]
    col_stats = {
        key: (min(r[key] for r in rows), max(r[key] for r in rows))
        for key in metric_keys
    }
    n_cols = len(metric_keys)
    n_rows = len(rows)

    fig, ax = plt.subplots(figsize=(11, 1.5 + 0.85 * n_rows))
    ax.set_xlim(0, n_cols)
    ax.set_ylim(0, n_rows)
    ax.invert_yaxis()  # row 0 (highest usage) at the top

    for i, row in enumerate(rows):
        for j, key in enumerate(metric_keys):
            val = row[key]
            color = _scouting_color(val, key, col_stats)
            ax.add_patch(plt.Rectangle((j, i), 1, 1, facecolor=color,
                                        edgecolor="#1a1a2e", linewidth=1.2))
            ax.text(j + 0.5, i + 0.5, _format_scouting_value(val, key),
                    ha="center", va="center", fontsize=13, fontweight="bold",
                    color=_text_color_for(color))

    # Y-axis: pitch type names
    ax.set_yticks([i + 0.5 for i in range(n_rows)])
    ax.set_yticklabels([PITCH_NAMES.get(r["type"], r["type"]) for r in rows],
                        fontsize=12, fontweight="bold")

    # X-axis: metric + MLB benchmark on a second line
    ax.set_xticks([j + 0.5 for j in range(n_cols)])
    labels = []
    for key in metric_keys:
        if key in SCOUTING_BENCH:
            _, avg, _ = SCOUTING_BENCH[key]
            if key == "xBA":
                labels.append(f"{key}\nMLB ≈ .{int(round(avg * 1000)):03d}")
            else:
                labels.append(f"{key}\nMLB ≈ {avg:.0f}%")
        else:
            labels.append(f"{key}\n(volume)")
    ax.set_xticklabels(labels, fontsize=11)
    ax.tick_params(axis="x", length=0, pad=10)
    ax.tick_params(axis="y", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.set_title(f"Pitch-Type Scouting Card — {FILTER.label}",
                 fontsize=14, fontweight="bold", pad=18)
    fig.text(0.5, 0.01,
             "Color reads from the pitcher's POV: green = better than MLB avg, "
             "red = worse · Usage% is volume only (blue = thrown more often) · "
             "xBA is inverted: lower is better",
             ha="center", fontsize=9, color="#9aa", style="italic")
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    fig.savefig(os.path.join(OUT_DIR, "09_pitch_type_performance.png"),
                dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [9/9] Pitch-type scouting card")


# ═══════════════════════════════════════════════════════════════════════
def _apply_cli_filter():
    """Replace the module-level FILTER from parsed CLI args; set per-filter OUT_DIR."""
    global FILTER, OUT_DIR
    args = parse_args()
    FILTER = Filter(
        modes=() if args.mode == "all" else (args.mode,),
        difficulties=() if args.difficulty == "all" else (args.difficulty,),
        hands=() if args.handedness == "all" else (args.handedness,),
    )
    # Per-filter output subfolder so different slices don't overwrite each
    # other's PNGs (previously every run clobbered analysis_output/ directly).
    OUT_DIR = os.path.join(OUT_DIR, FILTER.slug)
    os.makedirs(OUT_DIR, exist_ok=True)


# (figure filename, caption) in render order — drives the combined HTML report.
REPORT_FIGURES = [
    ("01_speed_distributions.png", "Pitch speed distribution by pitcher and pitch type."),
    ("02_pitch_locations.png", "Pitch locations at the plate (catcher's view), per pitcher."),
    ("03_pitch_movement.png", "Movement profile: horizontal vs induced-vertical break."),
    ("04_outcome_breakdown.png", "At-bat outcomes by pitcher."),
    ("05_pitch_by_count.png", "Pitch-type usage by ball-strike count."),
    ("06_trajectories.png", "Sampled 3-D pitch trajectories (side & top view)."),
    ("07_dashboard.png", "Session dashboard: pitching line, mix, and batting results."),
    ("08_plate_discipline.png", "Per-pitcher plate-discipline & rate-stat summary."),
    ("09_pitch_type_performance.png", "Pitch-type scouting card vs MLB benchmarks."),
]


def write_html_report():
    """Combine the generated PNGs into a single self-contained report.html."""
    imgs = [(fn, cap) for fn, cap in REPORT_FIGURES
            if os.path.exists(os.path.join(OUT_DIR, fn))]
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>StrikeFactor Pitch Analysis</title><style>",
        "body{background:#1a1a2e;color:#e0e0e0;font-family:Menlo,monospace;margin:0;}",
        ".wrap{max-width:1200px;margin:0 auto;padding:28px 20px;}",
        "h1{margin:0 0 4px;} .sub{color:#9aa;margin:0 0 22px;}",
        ".card{background:#16213e;border:1px solid #2a2a4a;border-radius:10px;",
        "padding:16px;margin:0 0 22px;} .card h2{margin:0 0 10px;font-size:15px;color:#9aa;}",
        "img{max-width:100%;height:auto;border-radius:6px;}",
        ".cap{color:#9aa;font-size:13px;margin-top:8px;}",
        ".nav{margin:0 0 20px;} .nav a{color:#3498db;margin-right:14px;",
        "text-decoration:none;font-size:13px;}",
        "</style></head><body><div class='wrap'>",
        "<h1>StrikeFactor — Pitch Analysis</h1>",
        f"<p class='sub'>{FILTER.label}</p>",
    ]
    parts.append("<div class='nav'>" + " ".join(
        f"<a href='#f{i}'>{fn.split('_', 1)[0]}</a>" for i, (fn, _) in enumerate(imgs)
    ) + "</div>")
    for i, (fn, cap) in enumerate(imgs):
        parts.append(
            f"<div class='card' id='f{i}'><h2>{fn}</h2>"
            f"<img src='{fn}' alt='{fn}'><div class='cap'>{cap}</div></div>"
        )
    parts.append("</div></body></html>")
    path = os.path.join(OUT_DIR, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return path


if __name__ == "__main__":
    _apply_cli_filter()
    print(f"Generating StrikeFactor pitch analysis ({FILTER.label})...")
    if FILTER.modes or FILTER.difficulties or FILTER.hands:
        print("  (filtered view — pass --mode all --difficulty all --handedness all "
              "to include every pitch)")
    fig1_speed_distributions()
    fig2_pitch_locations()
    fig3_movement_plot()
    fig4_outcome_breakdown()
    fig5_pitch_by_count()
    fig6_trajectories()
    fig7_dashboard()
    fig8_plate_discipline()
    fig9_pitch_type_performance()
    report = write_html_report()
    conn.close()
    print(f"\nAll figures saved to {OUT_DIR}/")
    print(f"Open the combined report: {report}")
