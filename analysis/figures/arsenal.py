"""Arsenal shape: velocity, movement, per-pitch quality, and run value."""

import numpy as np
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Ellipse

from .. import metrics, theme
from ..render_mpl import diverging_colors, empty_figure, figure_title, note, plt, save


def velocity(ctx):
    """Violin of speed per pitch type, one panel per pitcher."""
    if ctx.empty:
        return empty_figure(ctx, "02_velocity.png", "Velocity by Pitch Type")

    pitchers = ctx.pitchers
    fig, axes = plt.subplots(1, len(pitchers), figsize=(3.8 * len(pitchers), 6),
                             sharey=True, squeeze=False)
    axes = axes[0]
    figure_title(fig, "Velocity Distribution by Pitch Type", ctx, y=1.0)

    for ax, pname in zip(axes, pitchers):
        g = ctx.for_pitcher(pname)
        data, labels, colors = [], [], []
        for pt, sub in sorted(g.groupby("pitch_type"),
                              key=lambda kv: -kv[1]["speed_mph"].mean()):
            s = sub["speed_mph"].dropna()
            if len(s) < 3:
                continue
            data.append(s.to_numpy())
            labels.append(f"{pt}\n{s.mean():.1f}\n({len(s)})")
            colors.append(theme.pitch_color(pt))
        if data:
            vp = ax.violinplot(data, showmeans=True, showmedians=True, widths=0.85)
            for body, color in zip(vp["bodies"], colors):
                body.set_facecolor(color)
                body.set_alpha(0.75)
                body.set_edgecolor(theme.BG)
            vp["cmeans"].set_color("#ffffff")
            vp["cmedians"].set_color("#ffff66")
            for key in ("cbars", "cmins", "cmaxes"):
                vp[key].set_color(theme.MUTED)
            ax.set_xticks(range(1, len(labels) + 1))
            ax.set_xticklabels(labels, fontsize=8)
        ax.set_title(theme.pitcher_display(pname), fontsize=11, fontweight="bold")
        ax.grid(True, axis="y")

    axes[0].set_ylabel("Speed (mph)")
    fig.tight_layout()
    return save(fig, ctx, "02_velocity.png")


def movement(ctx):
    """pfx_x vs pfx_z, all pitchers combined plus a per-pitcher facet row."""
    if ctx.empty:
        return empty_figure(ctx, "03_movement.png", "Pitch Movement Profile")

    pitchers = ctx.pitchers
    ncol = max(len(pitchers), 1)
    fig = plt.figure(figsize=(4.0 * ncol, 11))
    figure_title(fig, "Pitch Movement Profile", ctx, y=0.98)
    gs = GridSpec(2, ncol, figure=fig, height_ratios=[1.35, 1.0], hspace=0.28,
                  wspace=0.22)

    ax_all = fig.add_subplot(gs[0, :])
    _movement_scatter(ax_all, ctx.pitches, label_counts=True, ellipses=True)
    ax_all.set_title("All pitchers — X marks the average break, ellipse = 1σ spread",
                     fontweight="bold", fontsize=11)

    for i, pname in enumerate(pitchers):
        ax = fig.add_subplot(gs[1, i])
        _movement_scatter(ax, ctx.for_pitcher(pname), label_counts=False,
                          ellipses=True, point_alpha=0.28, legend=False)
        ax.set_title(theme.pitcher_short(pname), fontsize=10, fontweight="bold")
        if i:
            ax.set_ylabel("")

    return save(fig, ctx, "03_movement.png")


def _movement_scatter(ax, df, label_counts=True, ellipses=False, point_alpha=0.35,
                      legend=True):
    if df.empty:
        note(ax, "No data")
        return
    for pt, g in df.groupby("pitch_type"):
        xs = g["pfx_x_inches"].dropna()
        zs = g["pfx_z_inches"].dropna()
        if xs.empty:
            continue
        color = theme.pitch_color(pt)
        label = f"{theme.pitch_name(pt)} ({len(g)})" if label_counts else theme.pitch_name(pt)
        ax.scatter(xs, zs, c=color, alpha=point_alpha, s=18, linewidths=0,
                   label=label)
        mx, mz = float(xs.mean()), float(zs.mean())
        if ellipses and len(xs) > 5:
            ax.add_patch(Ellipse((mx, mz), 2 * xs.std(), 2 * zs.std(),
                                 facecolor="none", edgecolor=color,
                                 linewidth=1.4, alpha=0.9, zorder=4))
        ax.scatter([mx], [mz], c=color, s=170, marker="X", edgecolors="white",
                   linewidths=1.4, zorder=5)

    ax.axhline(0, color="#556", linewidth=0.8)
    ax.axvline(0, color="#556", linewidth=0.8)
    ax.set_xlabel("Horizontal break (in)")
    ax.set_ylabel("Induced vertical break (in)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True)
    if legend:
        ax.legend(fontsize=9, loc="upper left", framealpha=0.25)


# ── Scouting card ────────────────────────────────────────────────────────
CARD_METRICS = ["Usage%", "CSW%", "Whiff%", "Chase%", "PutAway%", "xBA"]
CARD_SOURCE = {
    "Usage%": "usage_pct", "CSW%": "csw_pct", "Whiff%": "whiff_pct",
    "Chase%": "chase_pct", "PutAway%": "putaway_pct", "xBA": "xba",
}


def _bench_score(val, key, col_min, col_max):
    """Directional score in [-1, +1] against the MLB benchmark for a metric."""
    poor, avg, elite = theme.SCOUTING_BENCH[key]
    higher_better = elite > avg
    if higher_better:
        if val < avg:
            denom = avg - min(col_min, poor)
            return -min(1.0, (avg - val) / denom) if denom else 0.0
        denom = max(col_max, elite) - avg
        return min(1.0, (val - avg) / denom) if denom else 0.0
    if val > avg:
        denom = max(col_max, poor) - avg
        return -min(1.0, (val - avg) / denom) if denom else 0.0
    denom = avg - min(col_min, elite)
    return min(1.0, (avg - val) / denom) if denom else 0.0


def _cell_color(val, key, col_stats):
    if key == "Usage%":
        mx = col_stats[key][1]
        return theme.to_hex(theme.blend(theme.VOLUME_LO_RGB, theme.VOLUME_HI_RGB,
                                        (val / mx) if mx else 0))
    lo, hi = col_stats[key]
    score = _bench_score(val, key, lo, hi)
    if score >= 0:
        return theme.to_hex(theme.blend(theme.NEUTRAL_RGB, theme.GOOD_RGB, score))
    return theme.to_hex(theme.blend(theme.NEUTRAL_RGB, theme.BAD_RGB, -score))


def _fmt_card(val, key):
    return metrics.fmt_avg(val) if key == "xBA" else f"{val:.0f}%"


def scouting_card(ctx):
    """Which pitch types are working, benchmarked against MLB and the dataset."""
    card = metrics.scouting_card(ctx)
    if card.empty:
        return empty_figure(ctx, "04_scouting_card.png", "Pitch-Type Scouting Card",
                            "No pitch type has enough samples in this slice.")

    rows = card.to_dict("records")
    n_rows, n_cols = len(rows), len(CARD_METRICS)
    col_stats = {
        key: (min(r[CARD_SOURCE[key]] for r in rows),
              max(r[CARD_SOURCE[key]] for r in rows))
        for key in CARD_METRICS
    }

    fig, ax = plt.subplots(figsize=(12, 1.9 + 0.95 * n_rows))
    ax.set_xlim(0, n_cols)
    ax.set_ylim(0, n_rows)
    ax.invert_yaxis()

    for i, row in enumerate(rows):
        for j, key in enumerate(CARD_METRICS):
            val = row[CARD_SOURCE[key]]
            color = _cell_color(val, key, col_stats)
            ax.add_patch(plt.Rectangle((j, i), 1, 1, facecolor=color,
                                       edgecolor=theme.BG, linewidth=1.2))
            txt = theme.text_color_for(color)
            ax.text(j + 0.5, i + 0.42, _fmt_card(val, key), ha="center",
                    va="center", fontsize=13, fontweight="bold", color=txt)
            # Within-slice rank: MLB thresholds saturate on this dataset, so
            # the percentile is what actually separates the pitches.
            pctile_key = f"{CARD_SOURCE[key]}_pctile"
            if pctile_key in row and key != "Usage%":
                ax.text(j + 0.5, i + 0.76, f"p{row[pctile_key]:.0f}", ha="center",
                        va="center", fontsize=7.5, color=txt, alpha=0.8)

    ax.set_yticks([i + 0.5 for i in range(n_rows)])
    ax.set_yticklabels([f"{r['name']}  ({r['n']})" for r in rows],
                       fontsize=11.5, fontweight="bold")
    ax.set_xticks([j + 0.5 for j in range(n_cols)])
    labels = []
    for key in CARD_METRICS:
        if key in theme.SCOUTING_BENCH:
            _, avg, _ = theme.SCOUTING_BENCH[key]
            labels.append(f"{key}\nMLB ≈ {metrics.fmt_avg(avg)}" if key == "xBA"
                          else f"{key}\nMLB ≈ {avg:.0f}%")
        else:
            labels.append(f"{key}\n(volume)")
    ax.set_xticklabels(labels, fontsize=11)
    ax.tick_params(axis="both", length=0, pad=10)
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.set_title(f"Pitch-Type Scouting Card — {ctx.label}", fontsize=14,
                 fontweight="bold", pad=18)
    fig.text(0.5, 0.005,
             "Colour is from the pitcher's POV vs MLB average (green better, red worse) · "
             "small pNN = rank within this slice · Usage% is volume only · xBA inverted",
             ha="center", fontsize=9, color=theme.MUTED, style="italic")
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    return save(fig, ctx, "04_scouting_card.png")


def run_value(ctx):
    """RV/100 by pitch type, the count-value surface, and count-state splits."""
    if ctx.empty:
        return empty_figure(ctx, "05_run_value.png", "Run Value")

    fig = plt.figure(figsize=(16, 10))
    figure_title(fig, "Run Value", ctx, y=0.985)
    gs = GridSpec(2, 2, figure=fig, hspace=0.34, wspace=0.24,
                  height_ratios=[1.0, 1.0])

    # ── RV/100 by pitch type ──────────────────────────────────────────
    ax = fig.add_subplot(gs[0, 0])
    ars = metrics.arsenal(ctx, by_pitcher=False).sort_values("rv_per_100")
    colors = diverging_colors(ars["rv_per_100"])
    ax.barh(ars["name"], ars["rv_per_100"], color=colors, edgecolor=theme.BG)
    ax.axvline(0, color=theme.FG, linewidth=1.0)
    ax.set_xlabel("Runs saved per 100 pitches (pitcher POV)")
    ax.set_title("Run Value by Pitch Type", fontweight="bold")
    ax.grid(True, axis="x")
    for i, (v, n) in enumerate(zip(ars["rv_per_100"], ars["n"])):
        ax.text(v + (0.12 if v >= 0 else -0.12), i, f"{v:+.2f} (n={n})",
                va="center", ha="left" if v >= 0 else "right", fontsize=8)
    pad = max(abs(ars["rv_per_100"]).max(), 0.5) * 0.55
    ax.set_xlim(ars["rv_per_100"].min() - pad, ars["rv_per_100"].max() + pad)

    # ── Count-value surface ───────────────────────────────────────────
    ax = fig.add_subplot(gs[0, 1])
    cv = metrics.count_value_table(ctx.run_value)
    grid = np.full((3, 4), np.nan)
    for _, r in cv.iterrows():
        grid[int(r["strikes"]), int(r["balls"])] = r["value"]
    vmax = float(np.nanmax(np.abs(grid))) or 1.0
    # Values are batter-POV (0-2 is bad for the hitter), but the colour ramp is
    # reversed so green still reads "good for the pitcher" as it does elsewhere.
    im = ax.imshow(grid, cmap=theme.DIVERGING_CMAP_R, vmin=-vmax, vmax=vmax,
                   aspect="auto")
    for s in range(3):
        for b in range(4):
            if np.isnan(grid[s, b]):
                continue
            ax.text(b, s, f"{grid[s, b]:+.3f}", ha="center", va="center",
                    fontsize=10, fontweight="bold",
                    color="#111" if abs(grid[s, b]) < vmax * 0.55 else "#fff")
    ax.set_xticks(range(4))
    ax.set_yticks(range(3))
    ax.set_xlabel("Balls")
    ax.set_ylabel("Strikes")
    ax.set_title("Count Value (runs above average, batter POV; green = pitcher edge)",
                 fontweight="bold", fontsize=10.5)
    fig.colorbar(im, ax=ax, shrink=0.8, label="runs")

    # ── Count-state performance ───────────────────────────────────────
    ax = fig.add_subplot(gs[1, 0])
    st = metrics.performance_by_count_state(ctx)
    if st.empty:
        note(ax, "No data")
    else:
        x = np.arange(len(st))
        width = 0.27
        for i, (col, label, color) in enumerate([
            ("swing_pct", "Swing%", "#3498db"),
            ("whiff_pct", "Whiff%", "#f39c12"),
            ("chase_pct", "Chase%", "#e74c3c"),
        ]):
            ax.bar(x + (i - 1) * width, st[col], width, label=label, color=color,
                   edgecolor=theme.BG)
        ax.set_xticks(x)
        ax.set_xticklabels([s.replace("_", " ") for s in st["state"]], fontsize=9)
        ax.set_ylabel("Percent")
        ax.set_title("Plate Discipline by Count State", fontweight="bold")
        ax.legend(fontsize=8, frameon=False)
        ax.grid(True, axis="y")

    # ── Per-pitcher RV/100 by pitch type ──────────────────────────────
    ax = fig.add_subplot(gs[1, 1])
    per = metrics.arsenal(ctx, by_pitcher=True)
    if per.empty:
        note(ax, "No data")
    else:
        pitchers = ctx.pitchers
        types = [pt for pt in ctx.pitch_types]
        mat = np.full((len(types), len(pitchers)), np.nan)
        lookup = {(r["pitcher_name"], r["pitch_type"]): r["rv_per_100"]
                  for _, r in per.iterrows() if r["n"] >= 20}
        for i, pt in enumerate(types):
            for j, pn in enumerate(pitchers):
                if (pn, pt) in lookup:
                    mat[i, j] = lookup[(pn, pt)]
        vmax = float(np.nanmax(np.abs(mat))) if np.isfinite(mat).any() else 1.0
        im = ax.imshow(mat, cmap=theme.DIVERGING_CMAP, vmin=-vmax, vmax=vmax,
                       aspect="auto")
        for i in range(len(types)):
            for j in range(len(pitchers)):
                if np.isnan(mat[i, j]):
                    continue
                ax.text(j, i, f"{mat[i, j]:+.1f}", ha="center", va="center",
                        fontsize=8, color="#111" if abs(mat[i, j]) < vmax * 0.55 else "#fff")
        ax.set_xticks(range(len(pitchers)))
        ax.set_xticklabels([theme.pitcher_short(p) for p in pitchers], fontsize=9,
                           rotation=20)
        ax.set_yticks(range(len(types)))
        ax.set_yticklabels([theme.pitch_name(t) for t in types], fontsize=9)
        ax.set_title("RV/100 by Pitcher × Pitch Type (min 20)", fontweight="bold")
        fig.colorbar(im, ax=ax, shrink=0.8, label="runs saved /100")

    fig.text(0.5, 0.01,
             "Count values are solved by backward induction over this slice, so "
             "run values sum to zero across it — read them relative to each other.",
             ha="center", fontsize=9, color=theme.MUTED, style="italic")
    return save(fig, ctx, "05_run_value.png")
