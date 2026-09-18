"""Geometry audit of ggarch layouts — the measurement gate.

Usage (from a docs dir with ggarch importable, or from the repo):
  python scripts/audit-geometry.py model1.ggarch [model2.ggarch ...]

For every diagram view in the given model files:
  1. solve + route (the exact data the SVG draws)
  2. measure, per routed edge:
     - obstacle crossings: segments passing through the interior of a node
       rect that is not an ancestor-or-self of either endpoint
     - diagonal-ness: mostly-horizontal 2-point paths whose |dy| > 8px
     - label mode: replicate renderer._render_edge's gap-vs-offset test
       (0.25.3 gap-budget wrap)

The label-mode metric tracks the IMPLEMENTED label policy and must be
updated when ADR-002 (along-path labels) lands in 0.25.4: replace it
with rotated-label count (the orientation metric) and label-strike
tests (label extent vs node rects / other labels). Baseline at 0.25.3:
juju4 31 crossing-edges / 27 diagonals / 0 offset labels; juju3
15 / 15 / 0.
"""
import sys
import math
from ggarch import parse, validate, solve, route, render

CHAR_W = 5.5
FONT_SIZE = 9
LH = FONT_SIZE * 1.5
MIN_TAIL = 16
PADDING = 0
EPS = 0.5


def ancestors_map(layout):
    anc = {}
    def walk(n, chain):
        anc[n.id] = set(chain)
        for c in n.children:
            walk(c, chain + [n.id])
    for n in layout.nodes:
        walk(n, [])
    return anc


def all_rects(layout):
    out = []
    def walk(n):
        out.append(n)
        for c in n.children:
            walk(c)
    for n in layout.nodes:
        walk(n)
    return out


def seg_interior_hits(p1, p2, rect):
    """Count interior crossings of segment p1->p2 through rect."""
    length = math.hypot(p2.x - p1.x, p2.y - p1.y)
    if length < 1:
        return 0
    steps = max(2, int(length * 2))
    hits = 0
    prev_in = False
    for i in range(steps + 1):
        t = i / steps
        x = p1.x + (p2.x - p1.x) * t
        y = p1.y + (p2.y - p1.y) * t
        inside = (rect.x + EPS < x < rect.x2 - EPS
                  and rect.y + EPS < y < rect.y2 - EPS)
        if inside and not prev_in:
            hits += 1
        prev_in = inside
    return hits


def wrap_label(label, max_chars):
    wrapped = []
    for raw in label.split("\\n"):
        words = raw.split()
        if not words:
            wrapped.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            if len(cur) + 1 + len(w) <= max_chars:
                cur += " " + w
            else:
                wrapped.append(cur)
                cur = w
        wrapped.append(cur)
    return wrapped


def label_mode(points, label):
    """Replicate renderer._render_edge's use_gap decision (0.25.3 budget)."""
    pts = [(p.x, p.y) for p in points]
    seg_lens = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                for i in range(len(pts) - 1)]
    li = seg_lens.index(max(seg_lens))
    sx0, sy0 = pts[li]
    sx1, sy1 = pts[li + 1]
    seg_len = seg_lens[li]
    ux = abs((sx1 - sx0) / seg_len) if seg_len > 0 else 1.0
    uy = abs((sy1 - sy0) / seg_len) if seg_len > 0 else 0.0
    if ux >= uy:
        budget_px = ux * (seg_len - PADDING * 2 - MIN_TAIL * 2)
    else:
        budget_px = max(seg_len, 132)
    max_chars = max(int(budget_px / CHAR_W), 1)
    wrapped = wrap_label(label, max_chars)
    max_line_w = max(len(l) for l in wrapped) * CHAR_W
    text_h = LH * len(wrapped)
    if ux >= uy:
        gap_needed = max_line_w / ux if ux > 0.1 else max_line_w
    else:
        gap_needed = text_h / uy if uy > 0.1 else text_h
    use_gap = seg_len >= gap_needed + PADDING * 2 + MIN_TAIL * 2
    return use_gap, seg_len, gap_needed, len(wrapped)


def audit_file(path):
    f = parse(open(path).read())
    validate(f)
    report = {}
    for d in f.diagrams:
        m = f.get_model(d.model_name)
        solved = solve(d, m)
        routed = route(solved, m, d.select)
        anc = ancestors_map(solved)
        rects = all_rects(solved)

        crossings = []
        diagonals = []
        labels = []

        for e in routed.edges:
            desc = f"{e.source_id} -> {e.target_id}" + (
                f" [{e.label}]" if e.label else "")
            src_anc = anc.get(e.source_id, set()) | {e.source_id}
            tgt_anc = anc.get(e.target_id, set()) | {e.target_id}
            exempt = src_anc | tgt_anc

            for i in range(len(e.points) - 1):
                p1, p2 = e.points[i], e.points[i + 1]
                for nd in rects:
                    if nd.id in exempt:
                        continue
                    hits = seg_interior_hits(p1, p2, nd.rect)
                    if hits:
                        crossings.append((desc, nd.id, hits))

            if len(e.points) == 2:
                dx = abs(e.points[1].x - e.points[0].x)
                dy = abs(e.points[1].y - e.points[0].y)
                if dx > 40 and dy > 8 and dx >= dy:
                    diagonals.append((desc, round(dx), round(dy)))

            if e.label:
                use_gap, seg_len, gap_needed, nlines = label_mode(e.points, e.label)
                mode = "gap" if use_gap else "OFFSET"
                labels.append((desc, mode, round(seg_len), round(gap_needed), nlines))

        report[d.name] = dict(
            n_edges=len(routed.edges),
            crossings=crossings,
            diagonals=diagonals,
            labels=labels,
        )
    return report


def main():
    for path in sys.argv[1:]:
        report = audit_file(path)
        print(f"\n{'=' * 70}\n{path}\n{'=' * 70}")
        tc = td = to = te = 0
        for view, r in report.items():
            nc = len(set(c[0] for c in r["crossings"]))
            nd = len(r["diagonals"])
            no = sum(1 for l in r["labels"] if l[1] == "OFFSET")
            te += r["n_edges"]
            tc += nc
            td += nd
            to += no
            flag = "  <-- DEFECTS" if (nc or nd or no) else ""
            print(f"{view}: edges={r['n_edges']} "
                  f"crossing-edges={nc} diagonals={nd} "
                  f"offset-labels={no}/{len(r['labels'])}{flag}")
        print(f"\nTOTAL {path}: edges={te} crossing-edges={tc} "
              f"diagonals={td} offset-labels={to}")

        print("\n--- detail ---")
        for view, r in report.items():
            for desc, obst, hits in r["crossings"]:
                print(f"  CROSS  {view}: {desc}  through {obst} (x{hits})")
            for desc, dx, dy in r["diagonals"]:
                print(f"  DIAG   {view}: {desc}  dx={dx} dy={dy}")
            for desc, mode, sl, gn, nl in r["labels"]:
                if mode == "OFFSET":
                    print(f"  LABEL  {view}: {desc}  OFFSET seg={sl} need={gn} lines={nl}")


if __name__ == "__main__":
    main()
