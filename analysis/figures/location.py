"""Where pitches go, and what happens there.

Replaces the old raw scatter: 24k semi-transparent dots over a 3ft box is a
solid blob, so every panel here is a binned 5x5 zone grid instead.
"""

import math

import numpy as np
from matplotlib.gridspec import GridSpec

from .. import metrics, theme
from ..render_mpl import (draw_strike_zone, draw_zone_grid, empty_figure,
                          figure_title, note, plt, save, styled_table)

AGGREGATE_PANELS = [
    ("density", "Pitch Density", "{:.1f}%", theme.HEAT_CMAP),
    ("swing", "Swing Rate", "{:.0f}%", "viridis"),
    ("whiff", "Whiff Rate", "{:.0f}%", "magma"),
    ("damage", "Hits per Ball in Play", "{:.0f}%", "inferno"),
]


def zone_profile(ctx):
    if ctx.empty:
        return empty_figure(ctx, "06_zone_profile.png", "Zone Profile")

    types = [pt for pt in ctx.pitch_types
             if len(ctx.pitches[ctx.pitches["pitch_type"] == pt]) >= 60]
    per_row = 4
    type_rows = math.ceil(len(types) / per_row) if types else 0

    fig = plt.figure(figsize=(4.2 * per_row, 4.6 * (1 + type_rows)))
    figure_title(fig, "Zone Profile (catcher's view, batter-relative)", ctx,
                 y=0.995)
    gs = GridSpec(1 + type_rows, per_row, figure=fig, hspace=0.30, wspace=0.18)

    for i, (value, title, fmt, cmap) in enumerate(AGGREGATE_PANELS):
        ax = fig.add_subplot(gs[0, i])
        vals, counts = metrics.zone_grid(ctx.pitches, value=value)
        draw_zone_grid(ax, vals, counts, cmap=cmap, fmt=fmt)
        ax.set_title(title, fontsize=11, fontweight="bold")

    # Per-type panels share one colour scale so a hot cell means the same thing
    # in every panel; scaling each independently made every pitch look equally
    # dominant somewhere.
    grids = {pt: metrics.zone_grid(ctx.pitches[ctx.pitches["pitch_type"] == pt],
                                   value="whiff")
             for pt in types}
    finite = np.concatenate([v[np.isfinite(v)].ravel() for v, _ in grids.values()]
                            or [np.array([0.0])])
    vmin = float(finite.min()) if finite.size else 0.0
    vmax = float(finite.max()) if finite.size else 1.0

    for idx, pt in enumerate(types):
        ax = fig.add_subplot(gs[1 + idx // per_row, idx % per_row])
        sub = ctx.pitches[ctx.pitches["pitch_type"] == pt]
        vals, counts = grids[pt]
        draw_zone_grid(ax, vals, counts, cmap="magma", fmt="{:.0f}%",
                       vmin=vmin, vmax=vmax)
        ax.set_title(f"{theme.pitch_name(pt)} — Whiff%  (n={len(sub)})",
                     fontsize=10, fontweight="bold",
                     color=theme.pitch_color(pt))

    fig.text(0.5, 0.005,
             "Horizontal axis is batter-relative: right of centre is inside. "
             "Middle 3×3 is the strike zone; the outer ring is the chase band. "
             "Cells with fewer than 5 pitches are left blank. Per-pitch-type "
             "panels share one colour scale.",
             ha="center", fontsize=9, color=theme.MUTED, style="italic")
    return save(fig, ctx, "06_zone_profile.png")


def platoon_splits(ctx):
    """Same zone grids, split by batter handedness — inside/outside stops smearing."""
    hands = [h for h in ("L", "R")
             if len(ctx.pitches[ctx.pitches["batter_hand"] == h]) >= 100]
    if ctx.empty or len(hands) < 1:
        return empty_figure(ctx, "07_platoon.png", "Platoon Splits",
                            "Not enough pitches to either handedness in this slice.")

    fig = plt.figure(figsize=(16, 4.6 * len(hands) + 2.4))
    figure_title(fig, "Platoon Splits", ctx, y=0.99)
    gs = GridSpec(len(hands) + 1, 4, figure=fig, hspace=0.35, wspace=0.18,
                  height_ratios=[1.0] * len(hands) + [0.75])

    for r, hand in enumerate(hands):
        sub = ctx.pitches[ctx.pitches["batter_hand"] == hand]
        for i, (value, title, fmt, cmap) in enumerate(AGGREGATE_PANELS):
            ax = fig.add_subplot(gs[r, i])
            vals, counts = metrics.zone_grid(sub, value=value)
            draw_zone_grid(ax, vals, counts, cmap=cmap, fmt=fmt)
            ax.set_title(f"{hand}HB — {title}", fontsize=10, fontweight="bold")

    ax = fig.add_subplot(gs[len(hands), :])
    rows = []
    for hand in hands:
        sub = ctx.pitches[ctx.pitches["batter_hand"] == hand]
        for platoon, g in sorted(sub.groupby("platoon")):
            swings = int(g["is_swing"].sum())
            term = g[g["is_terminal"]]
            o = metrics._outcome_metrics(g) if len(term) else None
            rows.append([
                platoon, len(g), len(term),
                metrics.fmt_pct(100 * g["in_zone"].mean()),
                metrics.fmt_pct(100 * g["is_swing"].mean()),
                metrics.fmt_pct(100 * g["is_whiff"].sum() / swings if swings else 0),
                metrics.fmt_pct(100 * g["is_chase"].sum()
                                / max(len(g) - int(g["in_zone"].sum()), 1)),
                metrics.fmt_avg(o["avg"]) if o else "—",
                metrics.fmt_avg(o["woba"]) if o else "—",
            ])
    styled_table(ax, rows,
                 ["Matchup", "Pitches", "PA", "Zone%", "Swing%", "Whiff%",
                  "Chase%", "AVG", "wOBA"],
                 fontsize=10)
    ax.set_title("Matchup Summary", fontweight="bold", pad=10)
    return save(fig, ctx, "07_platoon.png")


def umpire(ctx):
    """AI-umpire calls vs ground truth, and where the misses cluster."""
    summary, miscalls = metrics.umpire_accuracy(ctx)
    if not summary or summary.get("graded", 0) == 0:
        return empty_figure(
            ctx, "08_umpire.png", "Umpire Accuracy",
            "No graded calls in this slice — ai_umpire_strike / truth_strike "
            "are only recorded on newer pitches.")

    fig = plt.figure(figsize=(15, 6.4))
    figure_title(fig, "Umpire Accuracy vs Ground Truth", ctx, y=1.0)
    gs = GridSpec(1, 3, figure=fig, wspace=0.24, width_ratios=[1.15, 1.0, 1.0])

    ax = fig.add_subplot(gs[0, 0])
    rows = [
        ["Graded calls", f"{summary['graded']:,}"],
        ["Coverage of slice", metrics.fmt_pct(summary["coverage_pct"])],
        ["Correct", metrics.fmt_pct(summary["accuracy_pct"], 2)],
        ["Miscalls", f"{summary['miscalls']:,}"],
        ["Strikes stolen (ball → strike)", f"{summary['stolen_strikes']:,}"],
        ["Strikes lost (strike → ball)", f"{summary['lost_strikes']:,}"],
        ["ABS challenges used", f"{summary['challenged']:,}"],
        ["Challenges overturned", f"{summary['overturned']:,}"],
    ]
    styled_table(ax, rows, ["Metric", "Value"], fontsize=11)
    ax.set_title("Summary", fontweight="bold", pad=10)

    ax = fig.add_subplot(gs[0, 1])
    stolen = miscalls[miscalls["ai_umpire_strike"] == 1]
    lost = miscalls[miscalls["ai_umpire_strike"] == 0]
    if len(stolen):
        ax.scatter(stolen["plate_x_ft"], stolen["plate_z_ft"], s=26, c="#e74c3c",
                   alpha=0.75, edgecolors="white", linewidths=0.3,
                   label=f"Ball called strike ({len(stolen)})")
    if len(lost):
        ax.scatter(lost["plate_x_ft"], lost["plate_z_ft"], s=26, c="#3498db",
                   alpha=0.75, edgecolors="white", linewidths=0.3,
                   label=f"Strike called ball ({len(lost)})")
    draw_strike_zone(ax)
    ax.set_xlim(-2.2, 2.2)
    ax.set_ylim(0, 5)
    ax.set_aspect("equal")
    ax.set_xlabel("Horizontal (ft)")
    ax.set_ylabel("Vertical (ft)")
    ax.set_title("Where the misses happen", fontweight="bold")
    ax.legend(fontsize=8, loc="upper right", framealpha=0.3)

    ax = fig.add_subplot(gs[0, 2])
    graded = ctx.pitches[ctx.pitches["ai_umpire_strike"].notna()
                         & ctx.pitches["truth_strike"].notna()]
    if len(graded):
        wrong = graded["ai_umpire_strike"] != graded["truth_strike"]
        tmp = graded.assign(_wrong=wrong)
        vals = np.full((5, 5), np.nan)
        counts = np.zeros((5, 5), dtype=int)
        xi = np.digitize(tmp["plate_x_ft"], metrics.ZONE_X_EDGES) - 1
        zi = np.digitize(tmp["plate_z_ft"], metrics.ZONE_Z_EDGES) - 1
        inside = (xi >= 0) & (xi < 5) & (zi >= 0) & (zi < 5)
        for col in range(5):
            for row in range(5):
                sel = inside & (xi == col) & (zi == row)
                g = tmp[sel]
                counts[4 - row, col] = len(g)
                if len(g) >= 3:
                    vals[4 - row, col] = 100 * g["_wrong"].mean()
        draw_zone_grid(ax, vals, counts, cmap="inferno", fmt="{:.0f}%")
        ax.set_title("Miscall rate by location", fontweight="bold")
    else:
        note(ax, "No graded calls")

    if summary["challenged"] == 0:
        fig.text(0.5, -0.02,
                 "No ABS challenge has ever been logged (abs_challenged is 0 for "
                 "every pitch), so the challenge rows are structurally empty rather "
                 "than filtered out.",
                 ha="center", fontsize=9, color=theme.MUTED, style="italic")
    return save(fig, ctx, "08_umpire.png")
