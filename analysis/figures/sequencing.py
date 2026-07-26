"""Deception: what a pitch is set up by, and how well pitches share a tunnel."""

import numpy as np
from matplotlib.gridspec import GridSpec

from .. import metrics, theme
from ..render_mpl import (empty_figure, figure_title, note, pitch_legend_handles,
                          plt, save, styled_table)


def sequencing(ctx):
    """prev → current pitch: how often, and how much more it misses bats."""
    seq = metrics.sequencing(ctx)
    if seq.empty:
        return empty_figure(
            ctx, "09_sequencing.png", "Pitch Sequencing",
            "Not enough consecutive-pitch pairs in this slice (need 15+ per pair).")

    prevs = sorted(seq["prev"].unique(), key=lambda p: theme.pitch_name(p))
    curs = sorted(seq["cur"].unique(), key=lambda p: theme.pitch_name(p))

    fig = plt.figure(figsize=(16, 13))
    figure_title(fig, "Pitch Sequencing", ctx, y=0.98)
    gs = GridSpec(2, 2, figure=fig, hspace=0.34, wspace=0.24,
                  height_ratios=[1.0, 1.15])

    # ── Whiff% delta matrix ───────────────────────────────────────────
    ax = fig.add_subplot(gs[0, 0])
    mat = np.full((len(prevs), len(curs)), np.nan)
    counts = np.zeros((len(prevs), len(curs)), dtype=int)
    for _, r in seq.iterrows():
        i, j = prevs.index(r["prev"]), curs.index(r["cur"])
        mat[i, j] = r["whiff_delta"]
        counts[i, j] = r["n"]
    vmax = float(np.nanmax(np.abs(mat))) if np.isfinite(mat).any() else 1.0
    im = ax.imshow(mat, cmap=theme.DIVERGING_CMAP, vmin=-vmax, vmax=vmax, aspect="auto")
    for i in range(len(prevs)):
        for j in range(len(curs)):
            if np.isnan(mat[i, j]):
                continue
            ax.text(j, i, f"{mat[i, j]:+.0f}", ha="center", va="center", fontsize=9,
                    fontweight="bold",
                    color="#111" if abs(mat[i, j]) < vmax * 0.55 else "#fff")
    ax.set_xticks(range(len(curs)))
    ax.set_xticklabels([theme.pitch_name(c) for c in curs], rotation=30, fontsize=9)
    ax.set_yticks(range(len(prevs)))
    ax.set_yticklabels([theme.pitch_name(p) for p in prevs], fontsize=9)
    ax.set_xlabel("this pitch")
    ax.set_ylabel("previous pitch")
    ax.set_title("Whiff% vs that pitch's own baseline", fontweight="bold")
    fig.colorbar(im, ax=ax, shrink=0.82, label="percentage points")

    # ── Usage matrix ──────────────────────────────────────────────────
    ax = fig.add_subplot(gs[0, 1])
    usage = np.zeros((len(prevs), len(curs)))
    for _, r in seq.iterrows():
        usage[prevs.index(r["prev"]), curs.index(r["cur"])] = r["n"]
    row_tot = usage.sum(axis=1, keepdims=True)
    pct = np.divide(usage, row_tot, out=np.zeros_like(usage), where=row_tot > 0) * 100
    im = ax.imshow(pct, cmap=theme.HEAT_CMAP, aspect="auto")
    for i in range(len(prevs)):
        for j in range(len(curs)):
            if pct[i, j] <= 0:
                continue
            ax.text(j, i, f"{pct[i, j]:.0f}%", ha="center", va="center", fontsize=8.5,
                    color="#fff" if pct[i, j] < pct.max() * 0.6 else "#111")
    ax.set_xticks(range(len(curs)))
    ax.set_xticklabels([theme.pitch_name(c) for c in curs], rotation=30, fontsize=9)
    ax.set_yticks(range(len(prevs)))
    ax.set_yticklabels([theme.pitch_name(p) for p in prevs], fontsize=9)
    ax.set_xlabel("this pitch")
    ax.set_ylabel("previous pitch")
    ax.set_title("What follows what (row = 100%)", fontweight="bold")
    fig.colorbar(im, ax=ax, shrink=0.82, label="usage %")

    # ── Best and worst sequences ──────────────────────────────────────
    ax = fig.add_subplot(gs[1, :])
    top, bottom = metrics.best_and_worst_sequences(seq, n=8)
    rows = []
    for tag, chunk in (("↑", top), ("↓", bottom)):
        for _, r in chunk.iterrows():
            rows.append([
                tag, f"{r['prev_name']} → {r['cur_name']}", r["n"],
                metrics.fmt_pct(r["whiff_pct"]),
                metrics.fmt_pct(r["baseline_whiff_pct"]),
                f"{r['whiff_delta']:+.1f}",
                f"{r['rv_per_100']:+.2f}",
            ])
    styled_table(ax, rows,
                 ["", "Sequence", "N", "Whiff%", "Baseline", "Δ", "RV/100"],
                 fontsize=9.5)
    ax.set_title("Most and least effective sequences (↑ best, ↓ worst)",
                 fontweight="bold", pad=10)

    fig.text(0.5, 0.005,
             "Δ compares a pitch's whiff rate after a given setup pitch against its "
             "overall whiff rate, so it isolates the sequencing effect from raw stuff.",
             ha="center", fontsize=9, color=theme.MUTED, style="italic")
    return save(fig, ctx, "09_sequencing.png")


def tunneling(ctx):
    """Mean flight paths with the commit point marked, plus tunnel ratios."""
    means = metrics.mean_trajectories(ctx)
    per_type, pairs = metrics.tunneling(ctx)
    if means.empty:
        return empty_figure(ctx, "10_tunneling.png", "Pitch Tunneling",
                            "No trajectory samples for this slice.")

    pitchers = [p for p in ctx.pitchers if p in set(means["pitcher_name"])]
    ncol = max(len(pitchers), 1)

    fig = plt.figure(figsize=(4.2 * ncol, 14))
    figure_title(fig, "Pitch Tunneling", ctx, y=0.985)
    gs = GridSpec(3, ncol, figure=fig, hspace=0.36, wspace=0.2,
                  height_ratios=[0.95, 0.95, 1.7])

    for i, pname in enumerate(pitchers):
        g = means[means["pitcher_name"] == pname]

        ax = fig.add_subplot(gs[0, i])
        _plot_view(ax, g, "z_ft")
        ax.set_title(theme.pitcher_short(pname), fontsize=11, fontweight="bold")
        if i == 0:
            ax.set_ylabel("Height (ft)")

        ax = fig.add_subplot(gs[1, i])
        _plot_view(ax, g, "x_ft")
        if i == 0:
            ax.set_ylabel("Horizontal (ft)")
        ax.set_xlabel("Distance from plate (ft)")

    ax = fig.add_subplot(gs[2, :])
    if pairs.empty:
        note(ax, "Not enough pitches per type to compute tunnel ratios (need 30+).")
    else:
        best = pairs.head(14)
        rows = [[
            r["display"], f"{theme.pitch_name(r['a'])} / {theme.pitch_name(r['b'])}",
            r["n"],
            f"{r['commit_sep_in']:.1f}\"",
            f"{r['plate_sep_in']:.1f}\"",
            f"{r['tunnel_ratio']:.2f}×",
        ] for _, r in best.iterrows()]
        styled_table(ax, rows,
                     ["Pitcher", "Pair", "N", "Sep @ commit", "Sep @ plate", "Ratio"],
                     fontsize=9.5)
        ax.set_title("Best-tunneled pairs — close at the commit point, far at the plate",
                     fontweight="bold", pad=10)

    handles = pitch_legend_handles(ctx.pitch_types)
    fig.legend(handles=handles, loc="lower center", ncol=min(len(handles), 8),
               fontsize=9.5, bbox_to_anchor=(0.5, -0.015), frameon=False)
    fig.text(0.5, -0.035,
             f"Dashed line = commit point at {theme.COMMIT_POINT_FT:.1f} ft, roughly "
             f"where a hitter must decide. Paths are per-pitch-type averages.",
             ha="center", fontsize=9, color=theme.MUTED, style="italic")
    return save(fig, ctx, "10_tunneling.png")


def _plot_view(ax, g, axis):
    for pt, sub in g.groupby("pitch_type"):
        sub = sub.sort_values("y_ft", ascending=False)
        ax.plot(sub["y_ft"], sub[axis], color=theme.pitch_color(pt), linewidth=2.2,
                alpha=0.95)
    ax.axvline(theme.COMMIT_POINT_FT, color="#ffffff", linestyle="--", linewidth=1.2,
               alpha=0.6)
    if axis == "z_ft":
        ax.axhspan(theme.SZ_Z_MIN, theme.SZ_Z_MAX, xmin=0.955, xmax=1.0,
                   color="#ffffff", alpha=0.28)
    else:
        ax.axhspan(-theme.SZ_X_HALF, theme.SZ_X_HALF, xmin=0.955, xmax=1.0,
                   color="#ffffff", alpha=0.28)
    ax.invert_xaxis()
    ax.grid(True)
