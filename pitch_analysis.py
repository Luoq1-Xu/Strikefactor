"""
StrikeFactor Pitch Database Analysis
Generates visualizations from the SQLite pitch database.
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
    print("  [1/7] Speed distributions")


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
    print("  [2/7] Pitch locations")


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
    print("  [3/7] Movement plot")


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
    print("  [4/7] Outcome breakdown")


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
    print("  [5/7] Pitch by count heatmap")


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
    print("  [6/7] Pitch trajectories")


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 7: Strike/Ball/Hit Rates + Swing Summary Dashboard
# ═══════════════════════════════════════════════════════════════════════
def fig7_dashboard():
    fig = plt.figure(figsize=(16, 10))
    fig.suptitle("StrikeFactor Session Dashboard", fontsize=16, fontweight="bold", y=0.98)
    gs = GridSpec(2, 3, figure=fig, hspace=0.35, wspace=0.3)

    # Panel A: Strike rate by pitch type
    ax_a = fig.add_subplot(gs[0, 0])
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
    ax_b = fig.add_subplot(gs[0, 1])
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
    ax_c = fig.add_subplot(gs[0, 2])
    type_counts = fetch("SELECT pitch_type, COUNT(*) as c FROM pitches GROUP BY pitch_type ORDER BY c DESC")
    wedge_labels = [PITCH_NAMES.get(r["pitch_type"], r["pitch_type"]) for r in type_counts]
    wedge_sizes = [r["c"] for r in type_counts]
    wedge_colors = [PITCH_COLORS.get(r["pitch_type"], "#888") for r in type_counts]
    ax_c.pie(wedge_sizes, labels=wedge_labels, colors=wedge_colors, autopct="%1.0f%%",
             textprops={"fontsize": 9, "color": "#e0e0e0"}, pctdistance=0.75,
             wedgeprops={"edgecolor": "#1a1a2e", "linewidth": 1})
    ax_c.set_title("Pitch Type Distribution", fontweight="bold")

    # Panel D: Batting line by pitcher
    ax_d = fig.add_subplot(gs[1, 0:2])
    pitchers = fetch("SELECT DISTINCT pitcher_name FROM at_bats")
    table_data = []
    for p in pitchers:
        pn = p["pitcher_name"]
        abs_total = fetch("SELECT COUNT(*) as c FROM at_bats WHERE pitcher_name = ?", (pn,))[0]["c"]
        hits = fetch(
            "SELECT COUNT(*) as c FROM at_bats WHERE pitcher_name = ? AND final_outcome IN ('SINGLE','DOUBLE','TRIPLE','HOME RUN')",
            (pn,)
        )[0]["c"]
        walks = fetch("SELECT COUNT(*) as c FROM at_bats WHERE pitcher_name = ? AND final_outcome = 'walk'", (pn,))[0]["c"]
        ks = fetch("SELECT COUNT(*) as c FROM at_bats WHERE pitcher_name = ? AND final_outcome = 'strikeout'", (pn,))[0]["c"]
        ab_no_walk = abs_total - walks
        ba = hits / ab_no_walk if ab_no_walk > 0 else 0
        obp = (hits + walks) / abs_total if abs_total > 0 else 0
        table_data.append([PITCHER_DISPLAY.get(pn, pn), abs_total, hits, walks, ks, f"{ba:.3f}", f"{obp:.3f}"])

    col_labels = ["Pitcher", "PA", "H", "BB", "K", "AVG", "OBP"]
    table = ax_d.table(cellText=table_data, colLabels=col_labels, loc="center",
                        cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(10)
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
    ax_e = fig.add_subplot(gs[1, 2])
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
    print("  [7/7] Dashboard")


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
    conn.close()
    print(f"\nAll figures saved to {OUT_DIR}/")
