"""Evaluation against an already organized event (read-only).

Category names differ between runs, so the metrics compare groupings, not names:
Hungarian-matched accuracy and per-folder precision/recall, pairwise precision/recall/F1,
Adjusted Rand Index, folder counts and how well part boundaries line up on the timeline.
"""

from __future__ import annotations

import re
from collections import Counter
from math import comb
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

INDEX_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|")


def truth_from_folders(clip_rel: dict[str, str]) -> dict[str, str]:
    """clip id -> the top-level folder it sits in (an organized project)."""
    return {cid: rel.split("/", 1)[0] for cid, rel in clip_rel.items() if "/" in rel}


def truth_from_index(md: Path) -> dict[str, str]:
    """clip stem -> folder, from the user's `00 ΕΥΡΕΤΗΡΙΟ ΠΛΑΝΩΝ.md` (`## <folder>` + table rows)."""
    out, folder = {}, None
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            folder = line[3:].strip()
        elif folder:
            m = INDEX_ROW.match(line)
            if m:
                out[m.group(1).rsplit(".", 1)[0]] = folder
    return out


def _boundaries(labels: list[str]) -> set[int]:
    return {i for i in range(1, len(labels)) if labels[i] != labels[i - 1]}


def boundary_f1(gt: list[str], pred: list[str], tol: int = 1) -> dict:
    """Timeline order: a boundary is where the folder changes between consecutive clips."""
    bg, bp = sorted(_boundaries(gt)), sorted(_boundaries(pred))
    used, hit = set(), 0
    for b in bg:
        cand = [x for x in bp if abs(x - b) <= tol and x not in used]
        if cand:
            used.add(min(cand, key=lambda x: abs(x - b)))
            hit += 1
    prec = hit / len(bp) if bp else 0.0
    rec = hit / len(bg) if bg else 0.0
    return {"gt": len(bg), "pred": len(bp), "precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0}


def metrics(truth: dict[str, str], pred: dict[str, str], order: list[str]) -> dict:
    ids = [c for c in order if c in truth and c in pred]
    g_names = sorted(set(truth[c] for c in ids))
    p_names = sorted(set(pred[c] for c in ids))
    gi = {n: i for i, n in enumerate(g_names)}
    pi = {n: i for i, n in enumerate(p_names)}
    m = np.zeros((len(g_names), len(p_names)), dtype=int)
    for c in ids:
        m[gi[truth[c]], pi[pred[c]]] += 1
    n = len(ids)

    rows, cols = linear_sum_assignment(-m)
    matched = int(m[rows, cols].sum())
    match = {p_names[c]: g_names[r] for r, c in zip(rows, cols)}
    per_folder = []
    for r, c in zip(rows, cols):
        per_folder.append({"truth": g_names[r], "pred": p_names[c], "n_truth": int(m[r].sum()),
                           "n_pred": int(m[:, c].sum()), "correct": int(m[r, c]),
                           "precision": round(m[r, c] / max(1, m[:, c].sum()), 3),
                           "recall": round(m[r, c] / max(1, m[r].sum()), 3)})
    for r, name in enumerate(g_names):
        if r not in rows:
            per_folder.append({"truth": name, "pred": None, "n_truth": int(m[r].sum()), "n_pred": 0,
                               "correct": 0, "precision": 0.0, "recall": 0.0})

    tp = sum(comb(int(x), 2) for x in m.flatten())
    pred_pairs = sum(comb(int(x), 2) for x in m.sum(axis=0))
    true_pairs = sum(comb(int(x), 2) for x in m.sum(axis=1))
    total = comb(n, 2)
    pp = tp / pred_pairs if pred_pairs else 0.0
    pr = tp / true_pairs if true_pairs else 0.0
    expected = pred_pairs * true_pairs / total if total else 0.0
    denom = 0.5 * (pred_pairs + true_pairs) - expected
    ari = (tp - expected) / denom if denom else (1.0 if pred_pairs == true_pairs == tp else 0.0)

    errors = [{"clip": c, "truth": truth[c], "pred": pred[c], "pred_as": match.get(pred[c])}
              for c in ids if match.get(pred[c]) != truth[c]]
    confusions = Counter((e["truth"], e["pred_as"] or e["pred"]) for e in errors).most_common(10)
    return {
        "clips": n, "folders_truth": len(g_names), "folders_pred": len(p_names),
        "matched_accuracy": round(matched / n, 4) if n else 0.0,
        "pairwise": {"precision": round(pp, 4), "recall": round(pr, 4),
                     "f1": round(2 * pp * pr / (pp + pr), 4) if pp + pr else 0.0},
        "ari": round(ari, 4),
        "boundaries": boundary_f1([truth[c] for c in ids], [pred[c] for c in ids]),
        "per_folder": sorted(per_folder, key=lambda x: x["truth"]),
        "errors": errors,
        "top_confusions": [{"truth": t, "pred": p_, "n": k} for (t, p_), k in confusions],
    }


def report_md(name: str, res: dict, run: dict) -> str:
    pw = res["pairwise"]
    b = res["boundaries"]
    lines = [
        f"# Accuracy report — {name}", "",
        f"Run: {run.get('when', '')} · model {run.get('model')} (describe effort {run.get('effort_describe')}, "
        f"structure effort {run.get('effort_structure')}) · frames 1 per {run.get('interval')} s · prompt {run.get('prompt')}", "",
        "| Metric | Value |", "|---|---|",
        f"| Clips evaluated | {res['clips']} |",
        f"| Folders: truth / predicted | {res['folders_truth']} / {res['folders_pred']} |",
        f"| **Matched accuracy** (Hungarian) | **{res['matched_accuracy']:.1%}** |",
        f"| Pairwise precision / recall / **F1** | {pw['precision']:.3f} / {pw['recall']:.3f} / **{pw['f1']:.3f}** |",
        f"| **Adjusted Rand Index** | **{res['ari']:.3f}** |",
        f"| Timeline boundaries F1 (±1 clip) | {b['f1']:.3f} ({b['gt']} true, {b['pred']} predicted) |",
        f"| Clock offsets | {run.get('clocks', '')} |",
        f"| Cost / time | ${run.get('cost', 0):.2f} · describe {run.get('describe_s', 0):.0f} s · structure {run.get('structure_s', 0):.0f} s |",
        f"| Refusals | {run.get('refusals', 0)} |", "",
        "## Per folder (truth → matched prediction)", "",
        "| Truth folder | Predicted folder | n truth | n pred | correct | precision | recall |", "|---|---|---|---|---|---|---|",
    ]
    for f in res["per_folder"]:
        lines.append(f"| {f['truth']} | {f['pred'] or '—'} | {f['n_truth']} | {f['n_pred']} | {f['correct']} | "
                     f"{f['precision']:.2f} | {f['recall']:.2f} |")
    lines += ["", "## Most frequent confusions", "", "| Truth | Predicted as | Clips |", "|---|---|---|"]
    lines += [f"| {c['truth']} | {c['pred']} | {c['n']} |" for c in res["top_confusions"]]
    lines += ["", "## Every misplaced clip", "", "| Clip | Truth | Predicted folder | (counts as) | Description |", "|---|---|---|---|---|"]
    for e in res["errors"]:
        lines.append(f"| {e['clip']} | {e['truth']} | {e['pred']} | {e['pred_as'] or '—'} | {e.get('desc', '')} |")
    return "\n".join(lines) + "\n"
