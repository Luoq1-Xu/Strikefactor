"""
StrikeFactor Pitch Database Analysis
Generates visualizations from the SQLite pitch database.
"""
import sqlite3
import os
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.gridspec import GridSpec
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(__file__), "strikefactor", "data", "strikefactor.db")
OUT_DIR = os.path.join(os.path.dirname(__file__), "analysis_output")
os.makedirs(OUT_DIR, exist_ok=True)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row


def fetch(sql, params=()):
    return conn.execute(sql, params).fetchall()


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
    """Sum runs allowed per pitcher across all completed GameDay games.

    Why: at_bats has no game_mode column and the DB doesn't track runs
    scored, but gameday_history.json records final scores per game and
    attributes them to a single starter. Approximate but the only source.
    """
    global _gameday_runs_cache
    if _gameday_runs_cache is not None:
        return _gameday_runs_cache
    runs, games = defaultdict(int), defaultdict(int)
    try:
        with open(GAMEDAY_HISTORY_PATH) as f:
            data = json.load(f)
        for g in data.get("games", []):
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
    sql = f"""
        SELECT
            COUNT(*) AS np,
            SUM(CASE WHEN {IN_ZONE_SQL} THEN 1 ELSE 0 END) AS zone,
            SUM(CASE WHEN swing_type > 0 THEN 1 ELSE 0 END) AS swings,
            SUM(CASE WHEN swing_type > 0 AND {IN_ZONE_SQL} THEN 1 ELSE 0 END) AS z_swings,
            SUM(CASE WHEN swing_type > 0 AND NOT {IN_ZONE_SQL} THEN 1 ELSE 0 END) AS o_swings,
            SUM(CASE WHEN swing_type > 0
                       AND outcome IN ('strike','strikeout') THEN 1 ELSE 0 END) AS whiffs,
            SUM(CASE WHEN swing_type = 0
                       AND outcome IN ('strike','strikeout') THEN 1 ELSE 0 END) AS called_strikes,
            SUM(CASE WHEN outcome IN ('ball','walk') THEN 1 ELSE 0 END) AS balls_thrown,
            SUM(CASE WHEN balls_before = 0 AND strikes_before = 0 THEN 1 ELSE 0 END) AS first_pitches,
            SUM(CASE WHEN balls_before = 0 AND strikes_before = 0
                       AND outcome NOT IN ('ball','walk') THEN 1 ELSE 0 END) AS first_strikes,
            SUM(CASE WHEN strikes_before = 2 THEN 1 ELSE 0 END) AS two_strike_pitches,
            SUM(CASE WHEN strikes_before = 2 AND outcome = 'strikeout' THEN 1 ELSE 0 END) AS putaways
        FROM pitches WHERE pitcher_name = ?
    """
    row = dict(fetch(sql, (pname,))[0])
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

    Uses GameDay-mode pitches only — ERA/WHIP are only meaningful when the
    pitcher worked through innings rather than arcade at-bats. Runs are
    sourced from gameday_history.json (see _gameday_runs_by_pitcher).
    """
    rows = fetch(
        "SELECT outcome, COUNT(*) AS c FROM pitches "
        "WHERE pitcher_name = ? AND game_mode = 'gameday' "
        "GROUP BY outcome",
        (pname,),
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
    rows = fetch(
        "SELECT final_outcome, COUNT(*) AS c FROM at_bats "
        "WHERE pitcher_name = ? GROUP BY final_outcome",
        (pname,),
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
    pitches = fetch(
        "SELECT COUNT(*) AS c FROM pitches WHERE pitcher_name = ?", (pname,)
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


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 1: Pitch Arsenal Speed Distributions (violin/box per pitcher)
# ═══════════════════════════════════════════════════════════════════════
def fig1_speed_distributions():
    pitchers = fetch("SELECT DISTINCT pitcher_name FROM pitches")
    pitcher_names = [r["pitcher_name"] for r in pitchers]

    fig, axes = plt.subplots(1, len(pitcher_names), figsize=(18, 6), sharey=True)
    fig.suptitle("Pitch Speed Distributions by Pitcher", fontsize=16, fontweight="bold", y=0.98)

    for ax, pname in zip(axes, pitcher_names):
        types = fetch(
            "SELECT DISTINCT pitch_type FROM pitches WHERE pitcher_name = ?", (pname,)
        )
        data, labels, colors = [], [], []
        for pt in types:
            pt_name = pt["pitch_type"]
            speeds = [r["speed_mph"] for r in fetch(
                "SELECT speed_mph FROM pitches WHERE pitcher_name = ? AND pitch_type = ?",
                (pname, pt_name)
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
    pitchers = fetch("SELECT DISTINCT pitcher_name FROM pitches")
    pitcher_names = [r["pitcher_name"] for r in pitchers]

    fig, axes = plt.subplots(1, len(pitcher_names), figsize=(20, 5))
    fig.suptitle("Pitch Locations at the Plate", fontsize=16, fontweight="bold", y=1.02)

    # Strike zone approx: x ∈ [-0.83, 0.83] ft, z ∈ [1.5, 3.5] ft
    sz_x, sz_w = -0.83, 1.66
    sz_z, sz_h = 1.5, 2.0

    for ax, pname in zip(axes, pitcher_names):
        rows = fetch(
            "SELECT plate_x_ft, plate_z_ft, pitch_type FROM pitches WHERE pitcher_name = ?",
            (pname,)
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
    ax.set_title("Pitch Movement Profile (All Pitchers)", fontsize=14, fontweight="bold")

    for pt in PITCH_COLORS:
        rows = fetch(
            "SELECT pfx_x_inches, pfx_z_inches FROM pitches WHERE pitch_type = ?", (pt,)
        )
        if not rows:
            continue
        xs = [r["pfx_x_inches"] for r in rows]
        zs = [r["pfx_z_inches"] for r in rows]
        ax.scatter(xs, zs, c=PITCH_COLORS[pt], label=f"{PITCH_NAMES.get(pt, pt)} ({len(rows)})",
                   alpha=0.55, s=40, edgecolors="white", linewidths=0.4)
        # Draw mean marker
        ax.scatter(np.mean(xs), np.mean(zs), c=PITCH_COLORS[pt], s=200,
                   marker="X", edgecolors="white", linewidths=1.5, zorder=5)

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
    pitchers = fetch("SELECT DISTINCT pitcher_name FROM at_bats")
    pitcher_names = [r["pitcher_name"] for r in pitchers]

    outcome_order = ["strikeout", "GROUNDOUT", "FLYOUT", "LINEOUT", "SINGLE", "DOUBLE", "TRIPLE", "HOME RUN", "walk"]
    outcome_colors = {
        "strikeout": "#e74c3c", "GROUNDOUT": "#95a5a6", "FLYOUT": "#7f8c8d",
        "LINEOUT": "#bdc3c7", "SINGLE": "#2ecc71", "DOUBLE": "#27ae60",
        "TRIPLE": "#1abc9c", "HOME RUN": "#f1c40f", "walk": "#3498db",
    }

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.suptitle("At-Bat Outcomes by Pitcher", fontsize=14, fontweight="bold")

    x = np.arange(len(pitcher_names))
    bottoms = np.zeros(len(pitcher_names))

    for outcome in outcome_order:
        counts = []
        for pname in pitcher_names:
            rows = fetch(
                "SELECT COUNT(*) as c FROM at_bats WHERE pitcher_name = ? AND final_outcome = ?",
                (pname, outcome)
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
    rows = fetch(
        "SELECT balls_before, strikes_before, pitch_type, COUNT(*) as c "
        "FROM pitches GROUP BY balls_before, strikes_before, pitch_type"
    )

    counts_map = defaultdict(lambda: defaultdict(int))
    all_types = set()
    for r in rows:
        count_str = f"{r['balls_before']}-{r['strikes_before']}"
        counts_map[count_str][r["pitch_type"]] += r["c"]
        all_types.add(r["pitch_type"])

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
    ax.set_title("Pitch Type Usage % by Count", fontsize=14, fontweight="bold")

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
    fig.suptitle("Pitch Trajectories (sampled)", fontsize=14, fontweight="bold")

    # Side view (y vs z) and top view (y vs x)
    for pt in PITCH_COLORS:
        pitch_ids = fetch(
            "SELECT pitch_id FROM pitches WHERE pitch_type = ? ORDER BY RANDOM() LIMIT 8", (pt,)
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
    fig.suptitle("StrikeFactor Session Dashboard", fontsize=16, fontweight="bold", y=0.99)
    gs = GridSpec(3, 3, figure=fig, hspace=0.40, wspace=0.30,
                  height_ratios=[0.8, 1.0, 1.0])

    # ── Panel HEADLINE: Classic pitching line (GameDay) ────────────
    ax_h = fig.add_subplot(gs[0, :])
    pitchers_all = [r["pitcher_name"] for r in fetch("SELECT DISTINCT pitcher_name FROM at_bats")]
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
        ax_h.text(0.5, 0.5, "No GameDay innings recorded yet",
                  ha="center", va="center", fontsize=12, color="#888")
        ax_h.set_title("Pitching Line — GameDay", fontweight="bold", pad=12, fontsize=12)
    ax_h.axis("off")

    # Panel A: Strike rate by pitch type
    ax_a = fig.add_subplot(gs[1, 0])
    types = fetch(
        "SELECT pitch_type, SUM(is_strike) as strikes, COUNT(*) as total "
        "FROM pitches GROUP BY pitch_type ORDER BY pitch_type"
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
        "SELECT pitch_type, SUM(CASE WHEN swing_type > 0 THEN 1 ELSE 0 END) as swings, COUNT(*) as total "
        "FROM pitches GROUP BY pitch_type ORDER BY pitch_type"
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
    type_counts = fetch("SELECT pitch_type, COUNT(*) as c FROM pitches GROUP BY pitch_type ORDER BY c DESC")
    wedge_labels = [PITCH_NAMES.get(r["pitch_type"], r["pitch_type"]) for r in type_counts]
    wedge_sizes = [r["c"] for r in type_counts]
    wedge_colors = [PITCH_COLORS.get(r["pitch_type"], "#888") for r in type_counts]
    ax_c.pie(wedge_sizes, labels=wedge_labels, colors=wedge_colors, autopct="%1.0f%%",
             textprops={"fontsize": 9, "color": "#e0e0e0"}, pctdistance=0.75,
             wedgeprops={"edgecolor": "#1a1a2e", "linewidth": 1})
    ax_c.set_title("Pitch Type Distribution", fontweight="bold")

    # Panel D: Batting line by pitcher (slash line + rate stats)
    ax_d = fig.add_subplot(gs[2, 0:2])
    pitchers = fetch("SELECT DISTINCT pitcher_name FROM at_bats")
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
    table = ax_d.table(cellText=table_data, colLabels=col_labels, loc="center",
                        cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.6)
    # Style table
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#2a2a4a")
        if row == 0:
            cell.set_facecolor("#2c3e50")
            cell.set_text_props(fontweight="bold", color="#e0e0e0")
        else:
            cell.set_facecolor("#16213e")
            cell.set_text_props(color="#e0e0e0")
    ax_d.axis("off")
    ax_d.set_title("Batting Performance vs Each Pitcher", fontweight="bold", pad=20)

    # Panel E: Pitch speed box by pitcher
    ax_e = fig.add_subplot(gs[2, 2])
    pitcher_names = [r["pitcher_name"] for r in fetch("SELECT DISTINCT pitcher_name FROM pitches")]
    speed_data = []
    labels_e = []
    for pn in pitcher_names:
        speeds = [r["speed_mph"] for r in fetch("SELECT speed_mph FROM pitches WHERE pitcher_name = ?", (pn,))]
        speed_data.append(speeds)
        labels_e.append(PITCHER_DISPLAY.get(pn, pn).split()[-1])  # Last name only

    bp = ax_e.boxplot(speed_data, patch_artist=True, labels=labels_e)
    palette = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6"]
    for patch, color in zip(bp["boxes"], palette):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
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
    pitchers = [r["pitcher_name"] for r in fetch("SELECT DISTINCT pitcher_name FROM at_bats")]

    fig = plt.figure(figsize=(16, 9))
    fig.suptitle("Pitcher Plate-Discipline & Rate Stats", fontsize=15, fontweight="bold", y=0.98)
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
# FIGURE 9: Per-pitch-type performance matrix (heatmap of key rates)
# ═══════════════════════════════════════════════════════════════════════
def fig9_pitch_type_performance():
    types = [r["pitch_type"] for r in fetch(
        "SELECT pitch_type, COUNT(*) c FROM pitches GROUP BY pitch_type "
        "HAVING c >= 20 ORDER BY c DESC"
    )]
    if not types:
        print("  [9/9] Skipped (no pitch types with enough samples)")
        return

    metric_keys = ["Usage%", "Strike%", "CSW%", "Whiff%", "Swing%", "Chase%",
                   "Zone%", "PutAway%", "GB%", "xBA"]
    matrix = np.zeros((len(types), len(metric_keys)))

    total_pitches = fetch("SELECT COUNT(*) c FROM pitches")[0]["c"] or 1

    for i, pt in enumerate(types):
        sql = f"""
            SELECT
                COUNT(*) AS np,
                SUM(CASE WHEN outcome NOT IN ('ball','walk') THEN 1 ELSE 0 END) AS strikes,
                SUM(CASE WHEN swing_type > 0 THEN 1 ELSE 0 END) AS swings,
                SUM(CASE WHEN swing_type > 0 AND outcome IN ('strike','strikeout')
                         THEN 1 ELSE 0 END) AS whiffs,
                SUM(CASE WHEN swing_type = 0 AND outcome IN ('strike','strikeout')
                         THEN 1 ELSE 0 END) AS called_strikes,
                SUM(CASE WHEN {IN_ZONE_SQL} THEN 1 ELSE 0 END) AS zone,
                SUM(CASE WHEN swing_type > 0 AND NOT {IN_ZONE_SQL} THEN 1 ELSE 0 END) AS o_swings,
                SUM(CASE WHEN strikes_before = 2 THEN 1 ELSE 0 END) AS two_strike,
                SUM(CASE WHEN strikes_before = 2 AND outcome = 'strikeout' THEN 1 ELSE 0 END) AS putaway,
                SUM(CASE WHEN outcome = 'GROUNDOUT' THEN 1 ELSE 0 END) AS go,
                SUM(CASE WHEN outcome IN ('GROUNDOUT','FLYOUT','LINEOUT',
                                          'SINGLE','DOUBLE','TRIPLE','HOME RUN')
                         THEN 1 ELSE 0 END) AS bip,
                SUM(CASE WHEN outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN')
                         THEN 1 ELSE 0 END) AS hits
            FROM pitches WHERE pitch_type = ?
        """
        r = dict(fetch(sql, (pt,))[0])
        np_ = r["np"] or 1
        swings = r["swings"] or 0
        zone = r["zone"] or 0
        o_zone = np_ - zone
        bip = r["bip"] or 0
        ab_like = swings - (r["whiffs"] or 0) - 0  # in-play + foul; no walks here
        # xBA proxy: hits / (in-play balls + whiffs) treats every swing-and-miss as out
        ab_proxy = bip + (r["whiffs"] or 0)
        matrix[i] = [
            100 * np_ / total_pitches,
            100 * r["strikes"] / np_,
            100 * (r["called_strikes"] + r["whiffs"]) / np_,
            100 * r["whiffs"] / swings if swings else 0,
            100 * swings / np_,
            100 * r["o_swings"] / o_zone if o_zone else 0,
            100 * zone / np_,
            100 * r["putaway"] / r["two_strike"] if r["two_strike"] else 0,
            100 * r["go"] / bip if bip else 0,
            1000 * r["hits"] / ab_proxy if ab_proxy else 0,  # ‰ for color scale
        ]

    fig, ax = plt.subplots(figsize=(13, 1.0 + 0.7 * len(types)))
    im = ax.imshow(matrix, aspect="auto", cmap="RdYlGn")
    ax.set_xticks(range(len(metric_keys)))
    ax.set_xticklabels(metric_keys, rotation=0, fontsize=10)
    ax.set_yticks(range(len(types)))
    ax.set_yticklabels([f"{PITCH_NAMES.get(t, t)}" for t in types], fontsize=11)
    ax.set_title("Pitch-Type Performance Matrix", fontsize=14, fontweight="bold", pad=14)

    for i in range(len(types)):
        for j, key in enumerate(metric_keys):
            v = matrix[i, j]
            if key == "xBA":
                txt = f".{int(round(v)):03d}"
            else:
                txt = f"{v:.0f}%"
            ax.text(j, i, txt, ha="center", va="center", fontsize=10,
                    color="black", fontweight="bold")

    plt.colorbar(im, ax=ax, label="value (relative scale)", shrink=0.7)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "09_pitch_type_performance.png"),
                dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [9/9] Pitch-type performance matrix")


# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("Generating StrikeFactor pitch analysis...")
    fig1_speed_distributions()
    fig2_pitch_locations()
    fig3_movement_plot()
    fig4_outcome_breakdown()
    fig5_pitch_by_count()
    fig6_trajectories()
    fig7_dashboard()
    fig8_plate_discipline()
    fig9_pitch_type_performance()
    conn.close()
    print(f"\nAll figures saved to {OUT_DIR}/")
