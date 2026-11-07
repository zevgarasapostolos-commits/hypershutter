"""Combine the ablation runs in reports/ablation/ into the thesis tables (Markdown).

    python scripts/ablation_table.py            # matched accuracy and pairwise F1, mean ± sd per event
For each event and condition the newest run wins. Density runs (…-density-*.json) get their own table.
"""

import json
import sys
from pathlib import Path

from hypershutter.core import ablation, config

EVENTS = [("gamos 25-07", "Wedding + baptism (507 clips)"), ("073 Β11-10-2026 Γ", "Baptism 073 (267, tuning)"),
          ("071 Β11-10-2026 Β", "Baptism 071 (249)")]


def load():
    runs = {}
    dens = {}
    for f in sorted(config.reports_dir("ablation").glob("*.json"), key=lambda f: f.stat().st_mtime):
        d = json.loads(f.read_text())
        if "intervals" in d:
            dens[d["event"]] = d
            continue
        for name, c in d["conditions"].items():
            runs[(d["event"].strip(), name)] = c["summary"]
    return runs, dens


def cell(s, key, pct):
    if not s or key not in s:
        return "–"
    m, sd = s[key]["mean"], s[key]["sd"]
    if pct:
        return f"{100 * m:.1f}" + (f" ± {100 * sd:.1f}" if s["n"] > 1 else "")
    return f"{m:.3f}" + (f" ± {sd:.3f}" if s["n"] > 1 else "")


def main() -> None:
    runs, dens = load()
    for key, title, pct in (("matched_accuracy", "Matched accuracy (%)", True), ("pairwise_f1", "Pairwise F1", False),
                            ("ari", "Adjusted Rand Index", False), ("boundary_f1", "Boundary F1", False)):
        print(f"\n**{title}** (mean ± sd over repeats)\n")
        print("| Signals | " + " | ".join(t for _, t in EVENTS) + " |")
        print("|---|" + "---|" * len(EVENTS))
        for name in ablation.CONDITIONS:
            row = [cell(runs.get((e, name)), key, pct) for e, _ in EVENTS]
            if any(x != "–" for x in row):
                print(f"| {name} | " + " | ".join(row) + " |")
    cost = {e: sum(s.get("cost", 0) for (ev, _), s in runs.items() if ev == e) for e, _ in EVENTS}
    print("\nPass-2 cost of all repeats: " + ", ".join(f"{t.split(' (')[0]} ${c:.2f}" for (e, t), c in zip(EVENTS, cost.values())))
    for ev, d in dens.items():
        print(f"\n**Frame density** — {ev}, subset of {d['clips']} clips (time + camera + image)\n")
        print("| One frame every | Frames | Matched accuracy (%) | Pairwise F1 | ARI | Pass-1 cost |")
        print("|---|---|---|---|---|---|")
        for iv, x in sorted(d["intervals"].items(), key=lambda kv: -float(kv[0])):
            s = x["conditions"]["time + camera + image"]["summary"]
            print(f"| {iv} s | {x['frames']} | {cell(s, 'matched_accuracy', True)} | {cell(s, 'pairwise_f1', False)} | "
                  f"{cell(s, 'ari', False)} | {x.get('pass1_cost', '–')} |")


if __name__ == "__main__":
    sys.exit(main())
