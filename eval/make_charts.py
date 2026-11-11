"""Regenerates the C2/C3 charts from the CSVs next to this script (matplotlib)."""
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
CH = HERE / "charts"
CH.mkdir(exist_ok=True)

ACCENT = "#34449E"
PALETTE = {"rule": "#6B7389", "lateness": "#34449E", "defect_tiebreak": "#A8231B",
           "defect_tiebreak_eta": "#D3D8E1", "reserve": "#146C4F",
           "hybrid": "#8A5A00", "hybrid_alt": "#A8231B", "fair": "#146C4F",
           "robust": "#6B7389", "defects": "#D3D8E1"}


def read(path):
    return list(csv.DictReader(open(path)))


def c2_chart():
    rows = read(HERE / "results_c2.csv")
    by = {}
    for r in rows:
        by.setdefault(r["policy"], {})[r["mode"]] = r
    order = ["rule_earliest", "desk_lateness", "defect_tiebreak",
             "defect_tiebreak_eta", "reserve_fast"]
    labels = ["earliest-finish\nrule", "desk\nlateness", "defect\n(lexicographic)",
              "defect\n(eta ties only)", "reserve fast\nshops"]
    colors = [PALETTE["rule"], PALETTE["lateness"], PALETTE["defect_tiebreak"],
              PALETTE["defect_tiebreak_eta"], PALETTE["reserve"]]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    x = range(len(order))
    w = 0.38
    ax1.bar([i - w / 2 for i in x],
            [float(by[p]["normal"]["% late"]) for p in order], w,
            color=colors, label="normal")
    ax1.bar([i + w / 2 for i in x],
            [float(by[p]["shock"]["% late"]) for p in order], w,
            color="none", edgecolor=colors, hatch="//", label="shock")
    ax1.set_xticks(list(x), labels, fontsize=8)
    ax1.set_ylabel("% of orders late")
    ax1.set_title("Primary metric: % late (10 seeds)")
    ax1.legend(frameon=False, fontsize=8)
    ax1.set_ylim(0, 22)

    ax2.bar([i - w / 2 for i in x],
            [float(by[p]["normal"]["% defect"]) for p in order], w, color=colors)
    ax2.bar([i + w / 2 for i in x],
            [float(by[p]["shock"]["% defect"]) for p in order], w,
            color="none", edgecolor=colors, hatch="//")
    ax2.set_xticks(list(x), labels, fontsize=8)
    ax2.set_ylabel("% of batches defective")
    ax2.set_title("Secondary metric: % defect")
    ax2.set_ylim(0, 8)

    fig.suptitle("C2 · can we beat the earliest-finish rule?", fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(CH / "c2_comparison.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def c3_tradeoff():
    pts = {"lateness": (1.67, 6.83), "fair": (7.58, 6.17), "robust": (3.75, 6.17),
           "hybrid": (19.83, 4.58), "hybrid_40_40_20": (25.42, 4.33),
           "defects": (72.17, 3.17)}
    fig, ax = plt.subplots(figsize=(6.8, 4.6))
    for name, (late, defect) in pts.items():
        color = PALETTE.get(name, ACCENT)
        ax.scatter(late, defect, s=90, color=color, zorder=3)
        dx, dy = (3.0, 0.08) if name not in ("defects", "hybrid_40_40_20") else (3.0, -0.22)
        ha = "left"
        if name == "hybrid":
            dx, dy = -17, 0.12
            ha = "left"
        ax.annotate(name.replace("_", " "), (late, defect),
                    textcoords="offset points", xytext=(dx, dy), fontsize=9, ha=ha)
    ax.set_xlabel("% of orders late (normal, 10 seeds)")
    ax.set_ylabel("% of batches defective")
    ax.set_title("C3 · each objective is a point on the lateness–defect frontier")
    ax.set_xlim(-8, 80)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(CH / "c3_tradeoff.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def c3_allocations():
    rows = read(HERE / "allocations_c3.csv")
    ws = ["W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8"]
    names = ["lateness", "fair", "hybrid", "hybrid_40_40_20"]
    colors = [PALETTE["lateness"], PALETTE["fair"], PALETTE["hybrid"], PALETTE["hybrid_alt"]]
    shares = {}
    for r in rows:
        total = int(r["total"])
        shares[r["policy"]] = [100 * int(r[w]) / total for w in ws]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    x = range(len(ws))
    n = len(names)
    w = 0.8 / n
    for i, name in enumerate(names):
        offs = (i - (n - 1) / 2) * w
        ax.bar([xi + offs for xi in x], shares[name], w, color=colors[i], label=name)
    ax.set_xticks(list(x), ws)
    ax.set_xlabel("workshop")
    ax.set_ylabel("% of pieces allocated (seed 5105)")
    ax.set_title("C3 · where the same 120 orders land under each objective")
    ax.legend(frameon=False, fontsize=9)
    ax.set_ylim(0, 48)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(CH / "c3_allocations.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    c2_chart()
    c3_tradeoff()
    c3_allocations()
    print("charts written to", CH)
