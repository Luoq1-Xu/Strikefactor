"""
StrikeFactor Batting Performance Analysis
Generates visualizations of the player's batting tendencies from the SQLite pitch database.

Filterable by game mode, difficulty, and batter handedness (mirrors
pitch_analysis.py). Each filter slice writes to its own subfolder under
analysis_output/ and produces a combined batting_report.html alongside the PNGs.

Filtering, palettes, and outcome groups come from the shared analysis package
(see docs/pitch-analysis-refactor.md); only the figures are local to this file.

Usage:
    python batting_analysis.py                         # default: gameday · hall_of_fame
    python batting_analysis.py --mode all --difficulty all
    python batting_analysis.py --handedness L          # left-handed batter only
    python batting_analysis.py --pitcher degrom
"""
import argparse
import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.gridspec import GridSpec
from collections import defaultdict

# Filtering, palettes, and outcome groups are shared with pitch_analysis.py via
# the analysis package so the two scripts can't drift apart again.
from analysis import theme
from analysis.data import DEFAULT_OUT_DIR, connect
from analysis.filters import (DIFFICULTY_LABEL, Filter, add_filter_args,
                              filter_from_args)

OUT_DIR = DEFAULT_OUT_DIR
os.makedirs(OUT_DIR, exist_ok=True)

conn = connect()


def fetch(sql, params=()):
    return conn.execute(sql, params).fetchall()


# Module-level filter; set in __main__ from CLI args.
FILTER = Filter()


def parse_args():
    p = argparse.ArgumentParser(description="StrikeFactor batting analysis (filterable).")
    add_filter_args(p)
    return p.parse_args()


def pw():
    """Return (sql_fragment, params) for the active FILTER on the pitches table.

    The fragment is prefixed with ' AND ' (or empty). All pitches queries append
    it so every figure honours the same mode/difficulty/handedness slice.
    """
    clauses, params = [], []
    if FILTER.modes:
        clauses.append(f"game_mode IN ({','.join('?' * len(FILTER.modes))})")
        params.extend(FILTER.modes)
    if FILTER.difficulties:
        clauses.append(f"difficulty IN ({','.join('?' * len(FILTER.difficulties))})")
        params.extend(FILTER.difficulties)
    if FILTER.hands:
        clauses.append(f"batter_hand IN ({','.join('?' * len(FILTER.hands))})")
        params.extend(FILTER.hands)
    if FILTER.pitchers:
        clauses.append(f"pitcher_name IN ({','.join('?' * len(FILTER.pitchers))})")
        params.extend(FILTER.pitchers)
    return (" AND " + " AND ".join(clauses) if clauses else "", params)


# ── Styling (shared with pitch_analysis.py via analysis.theme) ───────────
theme.apply_mpl_style()

PITCH_COLORS = theme.PITCH_COLORS
PITCH_NAMES = theme.PITCH_NAMES
OUTCOME_COLORS = theme.OUTCOME_COLORS

# on_time grades how well the swing was *timed*, not whether it made contact:
# 0 = mistimed, 1 = foul-ball timing, 2 = on time. A swing graded 1 or 2 can
# still miss if the bat is in the wrong place, so these are timing labels only.
TIMING_COLORS = {0: "#e74c3c", 1: "#f39c12", 2: "#2ecc71"}
TIMING_LABELS = {0: "Mistimed", 1: "Foul timing", 2: "On time"}

# Strike zone boundaries (feet)
SZ_X_MIN, SZ_X_MAX = -theme.SZ_X_HALF, theme.SZ_X_HALF
SZ_Z_MIN, SZ_Z_MAX = theme.SZ_Z_MIN, theme.SZ_Z_MAX

# A swing that produced no contact. Fouls carry outcome='foul' and contact
# carries an in-play outcome, so this test is exact — see
# docs/pitch-analysis-refactor.md. The old `on_time = 0` test missed every
# well-timed swing that still whiffed, understating Whiff% by ~40%.
WHIFF_SQL = "(swing_type > 0 AND outcome IN ('strike','strikeout'))"

# Heatmap grid bounds (wider than zone to show chase area)
GRID_X_MIN, GRID_X_MAX = -1.5, 1.5
GRID_Z_MIN, GRID_Z_MAX = 0.5, 4.5
GRID_BINS = 15
MIN_SAMPLES = 3

# MLB reference baselines (rough modern-era averages, for context).
MLB_AVG = 0.248
MLB_CHASE = 28.0   # O-Swing%
MLB_WHIFF = 24.0   # whiff per swing


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


def _no_data(name, idx):
    print(f"  [{idx}/7] {name} - no data for {FILTER.label}")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 1: Hit Rate Heatmap (fine-grained zone hit rate)
# ═══════════════════════════════════════════════════════════════════════
def fig1_hit_rate_heatmap():
    w, p = pw()
    rows = fetch(
        f"SELECT plate_x_ft, plate_z_ft, is_hit FROM pitches "
        f"WHERE swing_type > 0 AND on_time = 2{w}", p
    )
    if not rows:
        _no_data("Hit rate heatmap", 1)
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

    ax.set_title(f"{FILTER.label}  ·  n = {len(rows)} well-timed swings",
                 fontsize=10, style="italic")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "bat_01_hit_rate_heatmap.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [1/7] Hit rate heatmap")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 2: Whiff & Foul Rate Heatmaps
# ═══════════════════════════════════════════════════════════════════════
def fig2_whiff_foul_heatmap():
    w, p = pw()
    rows = fetch(
        f"SELECT plate_x_ft, plate_z_ft, on_time, outcome FROM pitches "
        f"WHERE swing_type > 0{w}", p
    )
    if not rows:
        _no_data("Whiff/foul heatmap", 2)
        return

    xs = [r["plate_x_ft"] for r in rows]
    zs = [r["plate_z_ft"] for r in rows]

    whiffs = [1 if r["outcome"] in ("strike", "strikeout") else 0 for r in rows]
    fouls = [1 if r["outcome"] == "foul" else 0 for r in rows]

    whiff_rate, xedges, zedges = build_rate_heatmap(xs, zs, whiffs)
    foul_rate, _, _ = build_rate_heatmap(xs, zs, fouls)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7))
    fig.suptitle(f"Whiff Rate & Foul Rate by Zone — {FILTER.label}",
                 fontsize=14, fontweight="bold")

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
    w, p = pw()
    rows = fetch(f"SELECT plate_x_ft, plate_z_ft, swing_type FROM pitches WHERE 1=1{w}", p)
    if not rows:
        _no_data("Swing decisions", 3)
        return

    xs = [r["plate_x_ft"] for r in rows]
    zs = [r["plate_z_ft"] for r in rows]
    swung = [1 if r["swing_type"] > 0 else 0 for r in rows]

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
    fig.suptitle(f"Swing Decision Map — {FILTER.label}", fontsize=14, fontweight="bold")

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
    w, p = pw()
    rows = fetch(
        f"SELECT pitch_type, on_time, COUNT(*) as c "
        f"FROM pitches WHERE swing_type > 0{w} "
        f"GROUP BY pitch_type, on_time", p
    )
    if not rows:
        _no_data("Timing analysis", 4)
        return

    data = defaultdict(lambda: {0: 0, 1: 0, 2: 0})
    for r in rows:
        data[r["pitch_type"]][r["on_time"]] = r["c"]

    pitch_types = sorted(data.keys(),
                         key=lambda pt: data[pt][2] / max(1, sum(data[pt].values())),
                         reverse=True)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
    fig.suptitle(f"Timing Quality Analysis — {FILTER.label}", fontsize=14, fontweight="bold")

    y_pos = np.arange(len(pitch_types))
    for timing_val in [0, 1, 2]:
        lefts = np.zeros(len(pitch_types))
        widths = []
        for i, pt in enumerate(pitch_types):
            total = sum(data[pt].values())
            pct = data[pt][timing_val] / total * 100 if total > 0 else 0
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

    count_rows = fetch(
        f"SELECT balls_before, strikes_before, on_time, COUNT(*) as c "
        f"FROM pitches WHERE swing_type > 0{w} "
        f"GROUP BY balls_before, strikes_before, on_time", p
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
    w, p = pw()
    rows = fetch(
        f"SELECT swing_type, on_time, outcome, plate_x_ft, plate_z_ft, "
        f"balls_before, strikes_before FROM pitches WHERE swing_type > 0{w}", p
    )
    if not rows:
        _no_data("Contact vs power", 5)
        return

    fig = plt.figure(figsize=(16, 10))
    fig.suptitle(f"Contact vs Power Swing Analysis — {FILTER.label}",
                 fontsize=14, fontweight="bold", y=0.98)
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
    w, p = pw()
    rows = fetch(
        f"SELECT plate_x_ft, plate_z_ft, outcome FROM pitches "
        f"WHERE outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN','GROUNDOUT','FLYOUT','LINEOUT'){w}",
        p
    )
    if not rows:
        _no_data("Outcomes by zone", 6)
        return

    fig, ax = plt.subplots(figsize=(9, 8))
    fig.suptitle(f"Batted Ball Outcomes by Zone — {FILTER.label}",
                 fontsize=14, fontweight="bold")

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
# At-bat-terminating outcomes (used to derive PA/AB from the pitches table —
# at_bats has no game_mode/difficulty columns so it can't honour the filter).
# Sourced from analysis.theme so POP_UP can't go missing here again: it was
# absent from this tuple, silently dropping 86 at-bats from every denominator.
TERMINAL = theme.TERMINAL_OUTCOMES


def _terminal_counts():
    """Counts of each at-bat-ending outcome from pitches, honouring FILTER."""
    w, p = pw()
    rows = fetch(
        "SELECT outcome, COUNT(*) c FROM pitches WHERE outcome IN "
        f"({','.join('?' * len(TERMINAL))}){w} GROUP BY outcome",
        (*TERMINAL, *p)
    )
    return {r["outcome"]: r["c"] for r in rows}


def fig7_batting_dashboard():
    w, p = pw()
    fig = plt.figure(figsize=(18, 11))
    fig.suptitle(f"StrikeFactor Batting Dashboard — {FILTER.label}",
                 fontsize=16, fontweight="bold", y=0.98)
    gs = GridSpec(2, 3, figure=fig, hspace=0.35, wspace=0.35)

    # ── Panel A: Key stats text (derived from pitches so the filter applies) ──
    ax_a = fig.add_subplot(gs[0, 0])
    ax_a.axis("off")

    tc = _terminal_counts()
    pa = sum(tc.values())
    walks = tc.get("walk", 0)
    strikeouts = tc.get("strikeout", 0)
    singles = tc.get("SINGLE", 0)
    doubles = tc.get("DOUBLE", 0)
    triples = tc.get("TRIPLE", 0)
    homers = tc.get("HOME RUN", 0)
    hits = singles + doubles + triples + homers

    ab = pa - walks
    total_bases = singles + 2 * doubles + 3 * triples + 4 * homers
    ba = hits / ab if ab > 0 else 0
    obp = (hits + walks) / pa if pa > 0 else 0
    slg = total_bases / ab if ab > 0 else 0
    ops = obp + slg
    k_pct = strikeouts / pa * 100 if pa > 0 else 0
    bb_pct = walks / pa * 100 if pa > 0 else 0

    total_swings = fetch(
        f"SELECT COUNT(*) c FROM pitches WHERE swing_type > 0{w}", p)[0]["c"]
    total_whiffs = fetch(
        f"SELECT COUNT(*) c FROM pitches WHERE {WHIFF_SQL}{w}", p)[0]["c"]
    whiff_pct = total_whiffs / total_swings * 100 if total_swings > 0 else 0

    chase_swings = fetch(
        f"SELECT COUNT(*) c FROM pitches WHERE swing_type > 0 "
        f"AND (plate_x_ft < ? OR plate_x_ft > ? OR plate_z_ft < ? OR plate_z_ft > ?){w}",
        (SZ_X_MIN, SZ_X_MAX, SZ_Z_MIN, SZ_Z_MAX, *p))[0]["c"]
    outside_pitches = fetch(
        f"SELECT COUNT(*) c FROM pitches "
        f"WHERE (plate_x_ft < ? OR plate_x_ft > ? OR plate_z_ft < ? OR plate_z_ft > ?){w}",
        (SZ_X_MIN, SZ_X_MAX, SZ_Z_MIN, SZ_Z_MAX, *p))[0]["c"]
    chase_pct = chase_swings / outside_pitches * 100 if outside_pitches > 0 else 0

    def _cmp(v, base, hi=True):
        if v == 0:
            return ""
        return " ▲" if (v >= base) == hi else " ▼"

    stats_text = (
        f"PA    {pa}\n"
        f"AVG   {ba:.3f}{_cmp(ba, MLB_AVG)}\n"
        f"OBP   {obp:.3f}\n"
        f"SLG   {slg:.3f}\n"
        f"OPS   {ops:.3f}\n"
        f"\n"
        f"K%    {k_pct:.1f}%\n"
        f"BB%   {bb_pct:.1f}%\n"
        f"Whiff% {whiff_pct:.1f}%{_cmp(whiff_pct, MLB_WHIFF, hi=False)}\n"
        f"Chase% {chase_pct:.1f}%{_cmp(chase_pct, MLB_CHASE, hi=False)}\n"
        f"\nMLB avg: AVG .248\nWhiff 24% · Chase 28%"
    )
    ax_a.text(0.05, 0.97, stats_text, transform=ax_a.transAxes,
              fontsize=13, fontfamily="monospace", verticalalignment="top",
              bbox=dict(boxstyle="round,pad=0.5", facecolor="#2c3e50", edgecolor="#e0e0e0"))
    ax_a.set_title("Key Batting Stats", fontweight="bold")

    # ── Panel B: Pitch outcome donut ──
    ax_b = fig.add_subplot(gs[0, 1])
    oc = {}
    oc["Taken Ball"] = fetch(
        f"SELECT COUNT(*) c FROM pitches WHERE swing_type = 0 AND is_strike = 0{w}", p)[0]["c"]
    oc["Taken Strike"] = fetch(
        f"SELECT COUNT(*) c FROM pitches WHERE swing_type = 0 AND is_strike = 1{w}", p)[0]["c"]
    oc["Whiff"] = total_whiffs
    oc["Foul"] = fetch(
        f"SELECT COUNT(*) c FROM pitches WHERE outcome = 'foul'{w}", p)[0]["c"]
    oc["Hit"] = fetch(f"SELECT COUNT(*) c FROM pitches WHERE is_hit = 1{w}", p)[0]["c"]
    oc["Out (in play)"] = fetch(
        f"SELECT COUNT(*) c FROM pitches WHERE outcome IN ('GROUNDOUT','FLYOUT','LINEOUT'){w}",
        p)[0]["c"]

    oc = {k: v for k, v in oc.items() if v > 0}
    donut_colors = ["#3498db", "#e74c3c", "#c0392b", "#f39c12", "#2ecc71", "#95a5a6"]
    if oc:
        ax_b.pie(
            list(oc.values()), labels=[f"{k}\n({v})" for k, v in oc.items()],
            colors=donut_colors[:len(oc)], autopct="%1.0f%%", pctdistance=0.8,
            textprops={"fontsize": 8, "color": "#e0e0e0"},
            wedgeprops={"edgecolor": "#1a1a2e", "linewidth": 1, "width": 0.5}
        )
    ax_b.set_title("All Pitch Outcomes", fontweight="bold")

    # ── Panel C: Hit type pie ──
    ax_c = fig.add_subplot(gs[0, 2])
    hit_counts = {"1B": singles, "2B": doubles, "3B": triples, "HR": homers}
    hit_colors = ["#2ecc71", "#27ae60", "#1abc9c", "#f1c40f"]
    if sum(hit_counts.values()) > 0:
        ax_c.pie(list(hit_counts.values()), labels=[f"{k} ({v})" for k, v in hit_counts.items()],
                 colors=hit_colors, autopct="%1.0f%%",
                 textprops={"fontsize": 9, "color": "#e0e0e0"},
                 wedgeprops={"edgecolor": "#1a1a2e", "linewidth": 1})
    else:
        ax_c.text(0.5, 0.5, "No hits", ha="center", va="center", color="#888")
        ax_c.axis("off")
    ax_c.set_title("Hit Type Distribution", fontweight="bold")

    # ── Panel D: Timing by difficulty ──
    ax_d = fig.add_subplot(gs[1, 0])
    diff_rows = fetch(
        f"SELECT difficulty, on_time, COUNT(*) c "
        f"FROM pitches WHERE swing_type > 0{w} GROUP BY difficulty, on_time", p)
    diff_data = defaultdict(lambda: {0: 0, 1: 0, 2: 0})
    for r in diff_rows:
        diff_data[r["difficulty"]][r["on_time"]] = r["c"]

    if diff_data:
        diff_names = sorted(diff_data.keys())
        display_names = [DIFFICULTY_LABEL.get(d, str(d)) for d in diff_names]
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
        f"SELECT balls_before, strikes_before, "
        f"SUM(CASE WHEN outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN') THEN 1 ELSE 0 END) as hits, "
        f"SUM(CASE WHEN outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN','GROUNDOUT','FLYOUT','LINEOUT','strikeout') THEN 1 ELSE 0 END) as abs "
        f"FROM pitches WHERE 1=1{w} "
        f"GROUP BY balls_before, strikes_before", p)
    count_order = ["0-0", "0-1", "0-2", "1-0", "1-1", "1-2", "2-0", "2-1", "2-2", "3-0", "3-1", "3-2"]
    count_map = {}
    for r in count_rows:
        key = f"{r['balls_before']}-{r['strikes_before']}"
        count_map[key] = safe_rate(r["hits"], r["abs"])

    counts_present = [c for c in count_order if c in count_map]
    avgs = [count_map[c] for c in counts_present]
    x = np.arange(len(counts_present))
    ax_e.bar(x, avgs, color="#3498db", edgecolor="#1a1a2e")
    ax_e.axhline(MLB_AVG, color="crimson", ls="--", lw=1, alpha=0.8, label=f"MLB .{int(MLB_AVG*1000)}")
    ax_e.set_xticks(x)
    ax_e.set_xticklabels(counts_present, fontsize=8, rotation=45)
    ax_e.set_ylabel("Batting Average")
    ax_e.set_title("AVG by Count", fontweight="bold")
    ax_e.legend(fontsize=8)
    ax_e.grid(True, axis="y")
    for i, v in enumerate(avgs):
        if not np.isnan(v):
            ax_e.text(i, v + 0.01, f".{int(v*1000):03d}", ha="center", fontsize=7)

    # ── Panel F: Batting avg by pitch type ──
    ax_f = fig.add_subplot(gs[1, 2])
    pt_rows = fetch(
        f"SELECT pitch_type, "
        f"SUM(CASE WHEN outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN') THEN 1 ELSE 0 END) as hits, "
        f"SUM(CASE WHEN outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN','GROUNDOUT','FLYOUT','LINEOUT','strikeout') THEN 1 ELSE 0 END) as abs "
        f"FROM pitches WHERE 1=1{w} GROUP BY pitch_type", p)
    pt_data = [(r["pitch_type"], safe_rate(r["hits"], r["abs"])) for r in pt_rows]
    pt_data = [(pt, avg) for pt, avg in pt_data if not np.isnan(avg)]
    pt_data.sort(key=lambda x: x[1], reverse=True)

    if pt_data:
        names = [PITCH_NAMES.get(pt, pt) for pt, _ in pt_data]
        avgs = [avg for _, avg in pt_data]
        colors = [PITCH_COLORS.get(pt, "#888") for pt, _ in pt_data]
        y = np.arange(len(names))
        ax_f.barh(y, avgs, color=colors, edgecolor="#1a1a2e")
        ax_f.axvline(MLB_AVG, color="crimson", ls="--", lw=1, alpha=0.8)
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
# Combined HTML report
# ═══════════════════════════════════════════════════════════════════════
REPORT_FIGURES = [
    ("bat_07_dashboard.png", "Slash line, plate discipline, and outcome mix vs MLB baselines."),
    ("bat_01_hit_rate_heatmap.png", "Hit rate by zone on well-timed swings."),
    ("bat_02_whiff_foul_heatmap.png", "Whiff and foul rate by zone."),
    ("bat_03_swing_decisions.png", "Swing rate and chase rate by location."),
    ("bat_04_timing_analysis.png", "Timing quality by pitch type and count situation."),
    ("bat_05_contact_vs_power.png", "Contact vs power swing usage, outcomes, and locations."),
    ("bat_06_outcomes_by_zone.png", "Where batted-ball outcomes happen in the zone."),
]


def write_html_report():
    imgs = [(fn, cap) for fn, cap in REPORT_FIGURES
            if os.path.exists(os.path.join(OUT_DIR, fn))]
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>StrikeFactor Batting Analysis</title><style>",
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
        "<h1>StrikeFactor — Batting Analysis</h1>",
        f"<p class='sub'>{FILTER.label}</p>",
    ]
    parts.append("<div class='nav'>" + " ".join(
        f"<a href='#f{i}'>{fn.split('_', 2)[-1].replace('.png','')}</a>"
        for i, (fn, _) in enumerate(imgs)
    ) + "</div>")
    for i, (fn, cap) in enumerate(imgs):
        parts.append(
            f"<div class='card' id='f{i}'><h2>{fn}</h2>"
            f"<img src='{fn}' alt='{fn}'><div class='cap'>{cap}</div></div>"
        )
    parts.append("</div></body></html>")
    # Distinct from pitch_analysis.py's report.html — both scripts write into
    # the same per-filter folder and used to overwrite each other's index.
    path = os.path.join(OUT_DIR, "batting_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return path


def _apply_cli_filter():
    global FILTER, OUT_DIR
    args = parse_args()
    FILTER = filter_from_args(args)
    OUT_DIR = os.path.join(OUT_DIR, FILTER.slug)
    os.makedirs(OUT_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    _apply_cli_filter()
    print(f"Generating StrikeFactor batting analysis ({FILTER.label})...")
    if not FILTER.is_empty:
        print("  (filtered view — pass --mode all --difficulty all --handedness all "
              "to include everything)")
    fig1_hit_rate_heatmap()
    fig2_whiff_foul_heatmap()
    fig3_swing_decisions()
    fig4_timing_analysis()
    fig5_contact_vs_power()
    fig6_outcomes_by_zone()
    fig7_batting_dashboard()
    report = write_html_report()
    conn.close()
    print(f"\nAll batting figures saved to {OUT_DIR}/")
    print(f"Open the combined report: {report}")
