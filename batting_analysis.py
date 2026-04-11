"""
StrikeFactor Batting Performance Analysis
Generates visualizations of the player's batting tendencies from the SQLite pitch database.
"""
import sqlite3
import os
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
    "FF": "#e74c3c",
    "SI": "#e67e22",
    "SL": "#3498db",
    "CB": "#2ecc71",
    "CH": "#9b59b6",
    "FS": "#f39c12",
    "FC": "#1abc9c",
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

OUTCOME_COLORS = {
    "SINGLE": "#2ecc71",
    "DOUBLE": "#27ae60",
    "TRIPLE": "#1abc9c",
    "HOME RUN": "#f1c40f",
    "GROUNDOUT": "#95a5a6",
    "FLYOUT": "#7f8c8d",
    "LINEOUT": "#bdc3c7",
}

TIMING_COLORS = {0: "#e74c3c", 1: "#f39c12", 2: "#2ecc71"}
TIMING_LABELS = {0: "Miss", 1: "Foul", 2: "Perfect"}

# Strike zone boundaries (feet)
SZ_X_MIN, SZ_X_MAX = -0.83, 0.83
SZ_Z_MIN, SZ_Z_MAX = 1.5, 3.5

# Heatmap grid bounds (wider than zone to show chase area)
GRID_X_MIN, GRID_X_MAX = -1.5, 1.5
GRID_Z_MIN, GRID_Z_MAX = 0.5, 4.5
GRID_BINS = 15
MIN_SAMPLES = 3


def draw_strike_zone(ax):
    rect = patches.Rectangle(
        (SZ_X_MIN, SZ_Z_MIN), SZ_X_MAX - SZ_X_MIN, SZ_Z_MAX - SZ_Z_MIN,
        linewidth=2, edgecolor="#ffffff", facecolor="none", linestyle="--"
    )
    ax.add_patch(rect)
    ax.set_xlim(GRID_X_MIN, GRID_X_MAX)
    ax.set_ylim(GRID_Z_MIN, GRID_Z_MAX)
    ax.set_xlabel("Horizontal (ft)")
    ax.set_ylabel("Vertical (ft)")
    ax.set_aspect("equal")


def safe_rate(num, denom):
    return num / denom if denom >= MIN_SAMPLES else np.nan


def build_rate_heatmap(xs, zs, mask_arr):
    """Build a 2D histogram of rate = sum(mask_arr) / count, per bin."""
    xs, zs, mask_arr = np.array(xs), np.array(zs), np.array(mask_arr, dtype=float)
    total, xedges, zedges = np.histogram2d(
        xs, zs, bins=GRID_BINS, range=[[GRID_X_MIN, GRID_X_MAX], [GRID_Z_MIN, GRID_Z_MAX]]
    )
    hits, _, _ = np.histogram2d(
        xs, zs, bins=GRID_BINS, range=[[GRID_X_MIN, GRID_X_MAX], [GRID_Z_MIN, GRID_Z_MAX]],
        weights=mask_arr
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        rate = np.where(total >= MIN_SAMPLES, hits / total, np.nan)
    return rate.T, xedges, zedges  # transpose for imshow (row=z, col=x)


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 1: Hit Rate Heatmap (fine-grained zone hit rate)
# ═══════════════════════════════════════════════════════════════════════
def fig1_hit_rate_heatmap():
    rows = fetch(
        "SELECT plate_x_ft, plate_z_ft, is_hit FROM pitches WHERE swing_type > 0 AND on_time = 2"
    )
    if not rows:
        print("  [1/7] Hit rate heatmap - no data")
        return

    xs = [r["plate_x_ft"] for r in rows]
    zs = [r["plate_z_ft"] for r in rows]
    hits = [r["is_hit"] for r in rows]

    rate, xedges, zedges = build_rate_heatmap(xs, zs, hits)

    fig, ax = plt.subplots(figsize=(8, 8))
    fig.suptitle("Hit Rate by Zone (on well-timed swings)", fontsize=14, fontweight="bold")

    im = ax.imshow(
        rate, extent=[GRID_X_MIN, GRID_X_MAX, GRID_Z_MIN, GRID_Z_MAX],
        origin="lower", cmap="RdYlGn", vmin=0, vmax=1, aspect="equal"
    )
    draw_strike_zone(ax)
    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Hit Rate")

    ax.set_title(f"n = {len(rows)} well-timed swings", fontsize=10, style="italic")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "bat_01_hit_rate_heatmap.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [1/7] Hit rate heatmap")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 2: Whiff & Foul Rate Heatmaps
# ═══════════════════════════════════════════════════════════════════════
def fig2_whiff_foul_heatmap():
    rows = fetch("SELECT plate_x_ft, plate_z_ft, on_time FROM pitches WHERE swing_type > 0")
    if not rows:
        print("  [2/7] Whiff/foul heatmap - no data")
        return

    xs = [r["plate_x_ft"] for r in rows]
    zs = [r["plate_z_ft"] for r in rows]
    on_times = [r["on_time"] for r in rows]

    whiffs = [1 if t == 0 else 0 for t in on_times]
    fouls = [1 if t == 1 else 0 for t in on_times]

    whiff_rate, xedges, zedges = build_rate_heatmap(xs, zs, whiffs)
    foul_rate, _, _ = build_rate_heatmap(xs, zs, fouls)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7))
    fig.suptitle("Whiff Rate & Foul Rate by Zone", fontsize=14, fontweight="bold")

    im1 = ax1.imshow(
        whiff_rate, extent=[GRID_X_MIN, GRID_X_MAX, GRID_Z_MIN, GRID_Z_MAX],
        origin="lower", cmap="Reds", vmin=0, vmax=1, aspect="equal"
    )
    draw_strike_zone(ax1)
    ax1.set_title("Whiff Rate (swing & miss)")
    plt.colorbar(im1, ax=ax1, shrink=0.8)

    im2 = ax2.imshow(
        foul_rate, extent=[GRID_X_MIN, GRID_X_MAX, GRID_Z_MIN, GRID_Z_MAX],
        origin="lower", cmap="Oranges", vmin=0, vmax=1, aspect="equal"
    )
    draw_strike_zone(ax2)
    ax2.set_title("Foul Rate (off-timing contact)")
    plt.colorbar(im2, ax=ax2, shrink=0.8)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "bat_02_whiff_foul_heatmap.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [2/7] Whiff/foul heatmap")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 3: Swing Decision Map (swing rate + chase rate)
# ═══════════════════════════════════════════════════════════════════════
def fig3_swing_decisions():
    rows = fetch("SELECT plate_x_ft, plate_z_ft, swing_type FROM pitches")
    if not rows:
        print("  [3/7] Swing decisions - no data")
        return

    xs = [r["plate_x_ft"] for r in rows]
    zs = [r["plate_z_ft"] for r in rows]
    swung = [1 if r["swing_type"] > 0 else 0 for r in rows]

    # Overall swing rate
    swing_rate, xedges, zedges = build_rate_heatmap(xs, zs, swung)

    # Chase rate: only pitches outside the geometric strike zone
    outside_xs, outside_zs, outside_swung = [], [], []
    for r in rows:
        px, pz = r["plate_x_ft"], r["plate_z_ft"]
        if px < SZ_X_MIN or px > SZ_X_MAX or pz < SZ_Z_MIN or pz > SZ_Z_MAX:
            outside_xs.append(px)
            outside_zs.append(pz)
            outside_swung.append(1 if r["swing_type"] > 0 else 0)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7))
    fig.suptitle("Swing Decision Map", fontsize=14, fontweight="bold")

    im1 = ax1.imshow(
        swing_rate, extent=[GRID_X_MIN, GRID_X_MAX, GRID_Z_MIN, GRID_Z_MAX],
        origin="lower", cmap="Blues", vmin=0, vmax=1, aspect="equal"
    )
    draw_strike_zone(ax1)
    ax1.set_title("Overall Swing Rate")
    plt.colorbar(im1, ax=ax1, shrink=0.8, label="Swing %")

    if outside_xs:
        chase_rate, _, _ = build_rate_heatmap(outside_xs, outside_zs, outside_swung)
        im2 = ax2.imshow(
            chase_rate, extent=[GRID_X_MIN, GRID_X_MAX, GRID_Z_MIN, GRID_Z_MAX],
            origin="lower", cmap="Oranges", vmin=0, vmax=1, aspect="equal"
        )
        plt.colorbar(im2, ax=ax2, shrink=0.8, label="Chase %")
    draw_strike_zone(ax2)
    ax2.set_title("Chase Rate (outside zone only)")

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "bat_03_swing_decisions.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [3/7] Swing decisions")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 4: Timing Quality by Pitch Type
# ═══════════════════════════════════════════════════════════════════════
def fig4_timing_analysis():
    rows = fetch(
        "SELECT pitch_type, on_time, COUNT(*) as c "
        "FROM pitches WHERE swing_type > 0 "
        "GROUP BY pitch_type, on_time"
    )
    if not rows:
        print("  [4/7] Timing analysis - no data")
        return

    # Build {pitch_type: {on_time: count}}
    data = defaultdict(lambda: {0: 0, 1: 0, 2: 0})
    for r in rows:
        data[r["pitch_type"]][r["on_time"]] = r["c"]

    # Sort by perfect timing rate descending
    pitch_types = sorted(data.keys(), key=lambda pt: data[pt][2] / max(1, sum(data[pt].values())), reverse=True)

    # Panel 1: By pitch type
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
    fig.suptitle("Timing Quality Analysis", fontsize=14, fontweight="bold")

    y_pos = np.arange(len(pitch_types))
    for timing_val in [0, 1, 2]:
        lefts = np.zeros(len(pitch_types))
        widths = []
        for i, pt in enumerate(pitch_types):
            total = sum(data[pt].values())
            pct = data[pt][timing_val] / total * 100 if total > 0 else 0
            # Stack: compute left offset from previous timing values
            for prev in range(timing_val):
                lefts[i] += data[pt][prev] / total * 100 if total > 0 else 0
            widths.append(pct)
        ax1.barh(y_pos, widths, left=lefts, color=TIMING_COLORS[timing_val],
                 label=TIMING_LABELS[timing_val], edgecolor="#1a1a2e", linewidth=0.5)

    ax1.set_yticks(y_pos)
    ax1.set_yticklabels([f"{PITCH_NAMES.get(pt, pt)} ({sum(data[pt].values())})" for pt in pitch_types])
    ax1.set_xlabel("Percentage of Swings")
    ax1.set_title("By Pitch Type")
    ax1.legend(loc="lower right")
    ax1.set_xlim(0, 100)

    # Panel 2: By count situation (ahead / even / behind)
    count_rows = fetch(
        "SELECT balls_before, strikes_before, on_time, COUNT(*) as c "
        "FROM pitches WHERE swing_type > 0 "
        "GROUP BY balls_before, strikes_before, on_time"
    )
    situations = {"Ahead\n(B > S)": {}, "Even\n(B = S)": {}, "Behind\n(B < S)": {}}
    for r in count_rows:
        b, s, ot = r["balls_before"], r["strikes_before"], r["on_time"]
        if b > s:
            key = "Ahead\n(B > S)"
        elif b == s:
            key = "Even\n(B = S)"
        else:
            key = "Behind\n(B < S)"
        situations[key][ot] = situations[key].get(ot, 0) + r["c"]

    sit_names = list(situations.keys())
    y_pos2 = np.arange(len(sit_names))
    for timing_val in [0, 1, 2]:
        lefts = np.zeros(len(sit_names))
        widths = []
        for i, sit in enumerate(sit_names):
            total = sum(situations[sit].values())
            pct = situations[sit].get(timing_val, 0) / total * 100 if total > 0 else 0
            for prev in range(timing_val):
                lefts[i] += situations[sit].get(prev, 0) / total * 100 if total > 0 else 0
            widths.append(pct)
        ax2.barh(y_pos2, widths, left=lefts, color=TIMING_COLORS[timing_val],
                 label=TIMING_LABELS[timing_val], edgecolor="#1a1a2e", linewidth=0.5)

    ax2.set_yticks(y_pos2)
    ax2.set_yticklabels([f"{s} ({sum(situations[s].values())})" for s in sit_names])
    ax2.set_xlabel("Percentage of Swings")
    ax2.set_title("By Count Situation")
    ax2.set_xlim(0, 100)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "bat_04_timing_analysis.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [4/7] Timing analysis")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 5: Contact vs Power Swing Analysis
# ═══════════════════════════════════════════════════════════════════════
def fig5_contact_vs_power():
    rows = fetch(
        "SELECT swing_type, on_time, outcome, plate_x_ft, plate_z_ft, "
        "balls_before, strikes_before FROM pitches WHERE swing_type > 0"
    )
    if not rows:
        print("  [5/7] Contact vs power - no data")
        return

    fig = plt.figure(figsize=(16, 10))
    fig.suptitle("Contact vs Power Swing Analysis", fontsize=14, fontweight="bold", y=0.98)
    gs = GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.3)

    # Panel A: Usage by count
    ax_a = fig.add_subplot(gs[0, 0])
    count_usage = defaultdict(lambda: {1: 0, 2: 0})
    for r in rows:
        count_str = f"{r['balls_before']}-{r['strikes_before']}"
        count_usage[count_str][r["swing_type"]] += 1

    count_order = ["0-0", "0-1", "0-2", "1-0", "1-1", "1-2", "2-0", "2-1", "2-2", "3-0", "3-1", "3-2"]
    count_order = [c for c in count_order if c in count_usage]

    x = np.arange(len(count_order))
    contact_pcts, power_pcts = [], []
    for cnt in count_order:
        total = count_usage[cnt][1] + count_usage[cnt][2]
        contact_pcts.append(count_usage[cnt][1] / total * 100 if total > 0 else 0)
        power_pcts.append(count_usage[cnt][2] / total * 100 if total > 0 else 0)

    ax_a.bar(x - 0.15, contact_pcts, 0.3, label="Contact (W)", color="#3498db", edgecolor="#1a1a2e")
    ax_a.bar(x + 0.15, power_pcts, 0.3, label="Power (E)", color="#e74c3c", edgecolor="#1a1a2e")
    ax_a.set_xticks(x)
    ax_a.set_xticklabels(count_order, fontsize=8)
    ax_a.set_ylabel("Usage %")
    ax_a.set_title("Swing Type Usage by Count")
    ax_a.legend(fontsize=9)
    ax_a.grid(True, axis="y")

    # Panel B: Outcome comparison
    ax_b = fig.add_subplot(gs[0, 1])
    outcome_cats = {
        "Miss": lambda r: r["on_time"] == 0,
        "Foul": lambda r: r["on_time"] == 1,
        "Out": lambda r: r["outcome"] in ("GROUNDOUT", "FLYOUT", "LINEOUT"),
        "Single": lambda r: r["outcome"] == "SINGLE",
        "XBH": lambda r: r["outcome"] in ("DOUBLE", "TRIPLE"),
        "HR": lambda r: r["outcome"] == "HOME RUN",
    }
    cat_colors = ["#e74c3c", "#f39c12", "#95a5a6", "#2ecc71", "#27ae60", "#f1c40f"]

    contact_rows = [r for r in rows if r["swing_type"] == 1]
    power_rows = [r for r in rows if r["swing_type"] == 2]

    cat_names = list(outcome_cats.keys())
    contact_dist, power_dist = [], []
    for cat, fn in outcome_cats.items():
        contact_dist.append(sum(1 for r in contact_rows if fn(r)) / max(1, len(contact_rows)) * 100)
        power_dist.append(sum(1 for r in power_rows if fn(r)) / max(1, len(power_rows)) * 100)

    y = np.arange(len(cat_names))
    ax_b.barh(y - 0.15, contact_dist, 0.3, label=f"Contact (n={len(contact_rows)})",
              color="#3498db", edgecolor="#1a1a2e")
    ax_b.barh(y + 0.15, power_dist, 0.3, label=f"Power (n={len(power_rows)})",
              color="#e74c3c", edgecolor="#1a1a2e")
    ax_b.set_yticks(y)
    ax_b.set_yticklabels(cat_names)
    ax_b.set_xlabel("% of Swings")
    ax_b.set_title("Outcome Distribution")
    ax_b.legend(fontsize=9, loc="lower right")

    # Panel C: Zone heatmaps for contact vs power
    ax_c1 = fig.add_subplot(gs[1, 0])
    ax_c2 = fig.add_subplot(gs[1, 1])

    for ax, swing_rows, title, cmap in [
        (ax_c1, contact_rows, "Contact Swing Locations", "Blues"),
        (ax_c2, power_rows, "Power Swing Locations", "Reds"),
    ]:
        if swing_rows:
            sx = [r["plate_x_ft"] for r in swing_rows]
            sz = [r["plate_z_ft"] for r in swing_rows]
            total, xedges, zedges = np.histogram2d(
                sx, sz, bins=GRID_BINS,
                range=[[GRID_X_MIN, GRID_X_MAX], [GRID_Z_MIN, GRID_Z_MAX]]
            )
            im = ax.imshow(
                total.T, extent=[GRID_X_MIN, GRID_X_MAX, GRID_Z_MIN, GRID_Z_MAX],
                origin="lower", cmap=cmap, aspect="equal"
            )
            plt.colorbar(im, ax=ax, shrink=0.8, label="Count")
        draw_strike_zone(ax)
        ax.set_title(f"{title} (n={len(swing_rows)})")

    fig.savefig(os.path.join(OUT_DIR, "bat_05_contact_vs_power.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [5/7] Contact vs power")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 6: Outcome by Zone (scatter plot)
# ═══════════════════════════════════════════════════════════════════════
def fig6_outcomes_by_zone():
    rows = fetch(
        "SELECT plate_x_ft, plate_z_ft, outcome FROM pitches "
        "WHERE outcome IN ('SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN', 'GROUNDOUT', 'FLYOUT', 'LINEOUT')"
    )
    if not rows:
        print("  [6/7] Outcomes by zone - no data")
        return

    fig, ax = plt.subplots(figsize=(9, 8))
    fig.suptitle("Batted Ball Outcomes by Zone", fontsize=14, fontweight="bold")

    # Plot outs first (below), then hits on top
    out_types = ["GROUNDOUT", "FLYOUT", "LINEOUT"]
    hit_types = ["SINGLE", "DOUBLE", "TRIPLE", "HOME RUN"]

    for outcome_list in [out_types, hit_types]:
        for outcome in outcome_list:
            subset = [r for r in rows if r["outcome"] == outcome]
            if not subset:
                continue
            xs = [r["plate_x_ft"] for r in subset]
            zs = [r["plate_z_ft"] for r in subset]
            ax.scatter(
                xs, zs,
                c=OUTCOME_COLORS.get(outcome, "#888"),
                label=f"{outcome} ({len(subset)})",
                alpha=0.6, s=50,
                edgecolors="white", linewidths=0.3,
                zorder=3 if outcome in hit_types else 2,
            )

    draw_strike_zone(ax)
    ax.legend(fontsize=9, loc="upper right", framealpha=0.8)
    ax.set_title(f"n = {len(rows)} batted balls", fontsize=10, style="italic")

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "bat_06_outcomes_by_zone.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [6/7] Outcomes by zone")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 7: Batting Dashboard (6-panel summary)
# ═══════════════════════════════════════════════════════════════════════
def fig7_batting_dashboard():
    fig = plt.figure(figsize=(18, 11))
    fig.suptitle("StrikeFactor Batting Dashboard", fontsize=16, fontweight="bold", y=0.98)
    gs = GridSpec(2, 3, figure=fig, hspace=0.35, wspace=0.35)

    # ── Panel A: Key stats text ──
    ax_a = fig.add_subplot(gs[0, 0])
    ax_a.axis("off")

    total_pitches = fetch("SELECT COUNT(*) as c FROM pitches")[0]["c"]
    total_swings = fetch("SELECT COUNT(*) as c FROM pitches WHERE swing_type > 0")[0]["c"]
    total_whiffs = fetch("SELECT COUNT(*) as c FROM pitches WHERE swing_type > 0 AND on_time = 0")[0]["c"]
    total_abs = fetch("SELECT COUNT(*) as c FROM at_bats")[0]["c"]
    hits = fetch(
        "SELECT COUNT(*) as c FROM at_bats WHERE final_outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN')"
    )[0]["c"]
    walks = fetch("SELECT COUNT(*) as c FROM at_bats WHERE final_outcome = 'walk'")[0]["c"]
    strikeouts = fetch("SELECT COUNT(*) as c FROM at_bats WHERE final_outcome = 'strikeout'")[0]["c"]
    singles = fetch("SELECT COUNT(*) as c FROM at_bats WHERE final_outcome = 'SINGLE'")[0]["c"]
    doubles = fetch("SELECT COUNT(*) as c FROM at_bats WHERE final_outcome = 'DOUBLE'")[0]["c"]
    triples = fetch("SELECT COUNT(*) as c FROM at_bats WHERE final_outcome = 'TRIPLE'")[0]["c"]
    homers = fetch("SELECT COUNT(*) as c FROM at_bats WHERE final_outcome = 'HOME RUN'")[0]["c"]

    ab_no_walk = total_abs - walks
    total_bases = singles + 2 * doubles + 3 * triples + 4 * homers
    ba = hits / ab_no_walk if ab_no_walk > 0 else 0
    obp = (hits + walks) / total_abs if total_abs > 0 else 0
    slg = total_bases / ab_no_walk if ab_no_walk > 0 else 0
    ops = obp + slg
    k_pct = strikeouts / total_abs * 100 if total_abs > 0 else 0
    bb_pct = walks / total_abs * 100 if total_abs > 0 else 0
    whiff_pct = total_whiffs / total_swings * 100 if total_swings > 0 else 0

    # Chase rate
    chase_swings = fetch(
        "SELECT COUNT(*) as c FROM pitches WHERE swing_type > 0 "
        "AND (plate_x_ft < ? OR plate_x_ft > ? OR plate_z_ft < ? OR plate_z_ft > ?)",
        (SZ_X_MIN, SZ_X_MAX, SZ_Z_MIN, SZ_Z_MAX)
    )[0]["c"]
    outside_pitches = fetch(
        "SELECT COUNT(*) as c FROM pitches "
        "WHERE plate_x_ft < ? OR plate_x_ft > ? OR plate_z_ft < ? OR plate_z_ft > ?",
        (SZ_X_MIN, SZ_X_MAX, SZ_Z_MIN, SZ_Z_MAX)
    )[0]["c"]
    chase_pct = chase_swings / outside_pitches * 100 if outside_pitches > 0 else 0

    stats_text = (
        f"AVG   {ba:.3f}\n"
        f"OBP   {obp:.3f}\n"
        f"SLG   {slg:.3f}\n"
        f"OPS   {ops:.3f}\n"
        f"\n"
        f"K%    {k_pct:.1f}%\n"
        f"BB%   {bb_pct:.1f}%\n"
        f"Whiff%  {whiff_pct:.1f}%\n"
        f"Chase%  {chase_pct:.1f}%"
    )
    ax_a.text(0.1, 0.95, stats_text, transform=ax_a.transAxes,
              fontsize=14, fontfamily="monospace", verticalalignment="top",
              bbox=dict(boxstyle="round,pad=0.5", facecolor="#2c3e50", edgecolor="#e0e0e0"))
    ax_a.set_title("Key Batting Stats", fontweight="bold")

    # ── Panel B: Pitch outcome donut ──
    ax_b = fig.add_subplot(gs[0, 1])
    outcome_counts = {}
    outcome_counts["Taken Ball"] = fetch(
        "SELECT COUNT(*) as c FROM pitches WHERE swing_type = 0 AND is_strike = 0"
    )[0]["c"]
    outcome_counts["Taken Strike"] = fetch(
        "SELECT COUNT(*) as c FROM pitches WHERE swing_type = 0 AND is_strike = 1"
    )[0]["c"]
    outcome_counts["Whiff"] = total_whiffs
    outcome_counts["Foul"] = fetch(
        "SELECT COUNT(*) as c FROM pitches WHERE swing_type > 0 AND on_time = 1"
    )[0]["c"]
    outcome_counts["Hit"] = fetch("SELECT COUNT(*) as c FROM pitches WHERE is_hit = 1")[0]["c"]
    outcome_counts["Out (in play)"] = fetch(
        "SELECT COUNT(*) as c FROM pitches WHERE outcome IN ('GROUNDOUT','FLYOUT','LINEOUT')"
    )[0]["c"]

    donut_colors = ["#3498db", "#e74c3c", "#c0392b", "#f39c12", "#2ecc71", "#95a5a6"]
    labels = [f"{k}\n({v})" for k, v in outcome_counts.items()]
    wedges, texts, autotexts = ax_b.pie(
        outcome_counts.values(), labels=labels, colors=donut_colors,
        autopct="%1.0f%%", pctdistance=0.8,
        textprops={"fontsize": 8, "color": "#e0e0e0"},
        wedgeprops={"edgecolor": "#1a1a2e", "linewidth": 1, "width": 0.5}
    )
    ax_b.set_title("All Pitch Outcomes", fontweight="bold")

    # ── Panel C: Hit type pie ──
    ax_c = fig.add_subplot(gs[0, 2])
    hit_types = {"1B": singles, "2B": doubles, "3B": triples, "HR": homers}
    hit_colors = ["#2ecc71", "#27ae60", "#1abc9c", "#f1c40f"]
    hit_labels = [f"{k} ({v})" for k, v in hit_types.items()]
    if sum(hit_types.values()) > 0:
        ax_c.pie(hit_types.values(), labels=hit_labels, colors=hit_colors,
                 autopct="%1.0f%%", textprops={"fontsize": 9, "color": "#e0e0e0"},
                 wedgeprops={"edgecolor": "#1a1a2e", "linewidth": 1})
    ax_c.set_title("Hit Type Distribution", fontweight="bold")

    # ── Panel D: Timing by difficulty ──
    ax_d = fig.add_subplot(gs[1, 0])
    diff_rows = fetch(
        "SELECT difficulty, on_time, COUNT(*) as c "
        "FROM pitches WHERE swing_type > 0 "
        "GROUP BY difficulty, on_time"
    )
    diff_data = defaultdict(lambda: {0: 0, 1: 0, 2: 0})
    for r in diff_rows:
        diff_data[r["difficulty"]][r["on_time"]] = r["c"]

    if diff_data:
        diff_names = sorted(diff_data.keys())
        # Clean up difficulty names for display
        display_names = [d.replace("DifficultyLevel.", "").replace("_", " ").title() for d in diff_names]
        y = np.arange(len(diff_names))
        for timing_val in [0, 1, 2]:
            lefts = np.zeros(len(diff_names))
            widths = []
            for i, d in enumerate(diff_names):
                total = sum(diff_data[d].values())
                pct = diff_data[d][timing_val] / total * 100 if total > 0 else 0
                for prev in range(timing_val):
                    lefts[i] += diff_data[d][prev] / total * 100 if total > 0 else 0
                widths.append(pct)
            ax_d.barh(y, widths, left=lefts, color=TIMING_COLORS[timing_val],
                      label=TIMING_LABELS[timing_val], edgecolor="#1a1a2e", linewidth=0.5)
        ax_d.set_yticks(y)
        ax_d.set_yticklabels(display_names, fontsize=9)
        ax_d.set_xlabel("% of Swings")
        ax_d.set_xlim(0, 100)
        ax_d.legend(fontsize=8)
    ax_d.set_title("Timing by Difficulty", fontweight="bold")

    # ── Panel E: Batting avg by count ──
    ax_e = fig.add_subplot(gs[1, 1])
    count_rows = fetch(
        "SELECT balls_before, strikes_before, "
        "SUM(CASE WHEN outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN') THEN 1 ELSE 0 END) as hits, "
        "SUM(CASE WHEN outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN','GROUNDOUT','FLYOUT','LINEOUT','strikeout') THEN 1 ELSE 0 END) as abs "
        "FROM pitches "
        "GROUP BY balls_before, strikes_before"
    )
    count_order = ["0-0", "0-1", "0-2", "1-0", "1-1", "1-2", "2-0", "2-1", "2-2", "3-0", "3-1", "3-2"]
    count_map = {}
    for r in count_rows:
        key = f"{r['balls_before']}-{r['strikes_before']}"
        count_map[key] = safe_rate(r["hits"], r["abs"])

    counts_present = [c for c in count_order if c in count_map]
    avgs = [count_map[c] for c in counts_present]
    x = np.arange(len(counts_present))
    bars = ax_e.bar(x, avgs, color="#3498db", edgecolor="#1a1a2e")
    ax_e.set_xticks(x)
    ax_e.set_xticklabels(counts_present, fontsize=8, rotation=45)
    ax_e.set_ylabel("Batting Average")
    ax_e.set_title("AVG by Count", fontweight="bold")
    ax_e.grid(True, axis="y")
    for i, v in enumerate(avgs):
        if not np.isnan(v):
            ax_e.text(i, v + 0.01, f".{int(v*1000):03d}", ha="center", fontsize=7)

    # ── Panel F: Batting avg by pitch type ──
    ax_f = fig.add_subplot(gs[1, 2])
    pt_rows = fetch(
        "SELECT pitch_type, "
        "SUM(CASE WHEN outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN') THEN 1 ELSE 0 END) as hits, "
        "SUM(CASE WHEN outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN','GROUNDOUT','FLYOUT','LINEOUT','strikeout') THEN 1 ELSE 0 END) as abs "
        "FROM pitches GROUP BY pitch_type"
    )
    pt_data = [(r["pitch_type"], safe_rate(r["hits"], r["abs"])) for r in pt_rows]
    pt_data = [(pt, avg) for pt, avg in pt_data if not np.isnan(avg)]
    pt_data.sort(key=lambda x: x[1], reverse=True)

    if pt_data:
        names = [PITCH_NAMES.get(pt, pt) for pt, _ in pt_data]
        avgs = [avg for _, avg in pt_data]
        colors = [PITCH_COLORS.get(pt, "#888") for pt, _ in pt_data]
        y = np.arange(len(names))
        ax_f.barh(y, avgs, color=colors, edgecolor="#1a1a2e")
        ax_f.set_yticks(y)
        ax_f.set_yticklabels(names)
        ax_f.set_xlabel("Batting Average")
        for i, v in enumerate(avgs):
            ax_f.text(v + 0.005, i, f".{int(v*1000):03d}", va="center", fontsize=9)
    ax_f.set_title("AVG vs Pitch Type", fontweight="bold")

    fig.savefig(os.path.join(OUT_DIR, "bat_07_dashboard.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [7/7] Batting dashboard")


# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("Generating StrikeFactor batting analysis...")
    fig1_hit_rate_heatmap()
    fig2_whiff_foul_heatmap()
    fig3_swing_decisions()
    fig4_timing_analysis()
    fig5_contact_vs_power()
    fig6_outcomes_by_zone()
    fig7_batting_dashboard()
    conn.close()
    print(f"\nAll batting figures saved to {OUT_DIR}/")
