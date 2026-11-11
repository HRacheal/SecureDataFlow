"""Static PNG charts (for the report and slides) generated from actual results."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

# Reference palette (dataviz skill): first three categorical slots validate all-pairs.
CONDITION_COLORS = {"Clean ground truth": "#2a78d6", "No controls (A)": "#eb6834", "With controls (B)": "#1baf7a"}
STATUS_COLORS = {"ACCEPTED": "#0ca30c", "FLAGGED": "#fab219", "REJECTED": "#d03b3b"}
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _kes(v, _=None):
    return f"{v / 1e6:.1f}M" if abs(v) >= 1e6 else f"{v / 1e3:.0f}k"


def revenue_by_category(truth: dict, a: dict, b: dict, out: Path) -> Path:
    cats = list(dict.fromkeys(list(truth["by_category"]) + list(a["by_category"]) + list(b["by_category"])))
    series = {"Clean ground truth": truth, "No controls (A)": a, "With controls (B)": b}
    fig, ax = plt.subplots(figsize=(10, 4.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    w = 0.26
    for k, (name, s) in enumerate(series.items()):
        xs = [i + (k - 1) * (w + 0.02) for i in range(len(cats))]
        vals = [s["by_category"].get(c, {}).get("revenue") or 0 for c in cats]
        ax.bar(xs, vals, width=w, color=CONDITION_COLORS[name], label=name, edgecolor=SURFACE, linewidth=1)
    ax.set_xticks(range(len(cats)))
    ax.set_xticklabels(cats, color=INK2)
    ax.yaxis.set_major_formatter(FuncFormatter(_kes))
    ax.set_ylabel("Revenue (KES)", color=INK2, fontsize=9)
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.set_title("Revenue by category: clean truth vs. attacked batch without and with controls",
                 loc="left", color=INK, fontsize=11)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="upper left")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def total_revenue(truth: dict, a: dict, b: dict, out: Path) -> Path:
    names = list(CONDITION_COLORS)
    vals = [truth["total_revenue"], a["total_revenue"], b["total_revenue"]]
    fig, ax = plt.subplots(figsize=(8, 3.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ys = list(range(len(names)))[::-1]
    ax.barh(ys, vals, color=[CONDITION_COLORS[n] for n in names], height=0.55)
    for y, v in zip(ys, vals):
        dev = (v - vals[0]) / vals[0] * 100
        label = f"KES {v:,.0f}" + ("" if y == ys[0] else f"  ({dev:+.1f}% vs truth)")
        ax.text(v, y, "  " + label, va="center", color=INK, fontsize=9)
    ax.set_yticks(ys)
    ax.set_yticklabels(names, color=INK2)
    ax.xaxis.set_major_formatter(FuncFormatter(_kes))
    ax.set_xlim(0, max(vals) * 1.45)
    ax.set_title("Total October revenue reported downstream", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def outcomes_by_scenario(rows: list[dict], out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 4.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    labels = [r["scenario"].replace("_", " ") + f" (n={r['records']})" for r in rows][::-1]
    data = rows[::-1]
    pct = lambda r, k: 100 * r[k] / r["records"]  # noqa: E731
    left = [0.0] * len(data)
    for status, key in (("ACCEPTED", "accepted"), ("FLAGGED", "flagged"), ("REJECTED", "rejected")):
        vals = [pct(r, key) for r in data]
        ax.barh(range(len(data)), vals, left=left, color=STATUS_COLORS[status], label=status.title(),
                height=0.62, edgecolor=SURFACE, linewidth=1.5)
        for i, (v, r) in enumerate(zip(vals, data)):
            if r[key] and v >= 6:
                ax.text(left[i] + v / 2, i, str(r[key]), ha="center", va="center", fontsize=8,
                        color=INK if status == "FLAGGED" else "#ffffff")
        left = [l + v for l, v in zip(left, vals)]
    for i, r in enumerate(data):  # say what the colours mean where colour alone would mislead
        q = r["rejected"] + r["flagged"]
        if r["scenario"] == "LEGITIMATE" and q:
            ax.text(101, i, f"{q} legitimate quarantined", va="center", fontsize=8, color=INK)
        elif r["scenario"] != "LEGITIMATE" and r["accepted"]:
            ax.text(101, i, f"{r['accepted']} MISSED (accepted)", va="center", fontsize=8, color=INK,
                    fontweight="bold")
    ax.set_yticks(range(len(data)))
    ax.set_yticklabels(labels, fontsize=8.5, color=INK2)
    ax.set_xlim(0, 128)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.set_xlabel("% of records in scenario (bar labels = record counts)", color=INK2, fontsize=9)
    ax.set_title("Security decision per scenario (Experiment B)", loc="left", color=INK, fontsize=11)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK2, ncol=3, loc="lower right", bbox_to_anchor=(1, 1.0))
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def failures_by_reason(codes: dict, out: Path) -> Path:
    items = sorted(codes.items(), key=lambda kv: kv[1])
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.barh([k for k, _ in items], [v for _, v in items], color="#2a78d6", height=0.6)
    for i, (_, v) in enumerate(items):
        ax.text(v, i, f" {v}", va="center", fontsize=8.5, color=INK)
    ax.tick_params(axis="y", labelsize=8.5)
    ax.set_xlabel("Validation failures (one record can fail several checks)", color=INK2, fontsize=9)
    ax.set_title("Validation failures by reason code", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out
