"""Geometry audit of ggarch layouts — the measurement gate.

Usage (from a docs dir with ggarch importable, or from the repo):
  python scripts/audit-geometry.py model1.ggarch [model2.ggarch ...]

For every diagram view in the given model files:
  1. solve + route (the exact data the SVG draws)
  2. measure, per routed edge:
     - obstacle crossings: segments passing through the interior of a
       node rect that is not an ancestor-or-self of either endpoint
     - diagonal-ness: mostly-horizontal 2-point paths whose |dy| > 8px
     - rotated labels (ADR-002 orientation metric): labels whose leg
       runs more vertical than horizontal — the trigger metric for the
       staged auto-flip decision
     - label strikes: the label's one-sided strip (renderer
       .label_geometry, pair anchors included) vs node rects the
       stroke itself clears, vs other labels, and vs the shared
       container's padded wall

Label metrics measure the IMPLEMENTED placement (renderer
label_geometry is the single source — the audit imports it, never
replicates it). Baseline at 0.25.4 (ADR-002 along-path labels):
juju3 15 crossing-edges / 11 diagonals / 30 rotated labels /
3 node-strikes / 0 wall-crossings / 6 label-clashes;
juju4 35 / 22 / 22 / 4 / 0 / 10. The 0.25.3 baseline
(juju4 31 / 27 / 0 offset labels; juju3 15 / 15 / 0) applied to the
superseded gap/offset policy; juju4's crossings grew 31 -> 35 because
the abolished gap floors regressed the space 0.25.3 spent widening
gaps (the auto-layout twin tightened; step 2's edge-aware floor sizes
column gaps to the labels routed through them). Wall-crossings 0/0:
the strike-avoidance contract reserves them. Label clashes are the
step-3 router baseline (strips as collision currency).
"""
import sys
import math

from ggarch import parse, validate, solve, route
from ggarch.layout import CONTAINER_PAD, CONTAINER_PAD_TOP
from ggarch.renderer import label_geometry

EPS = 0.5
WALL_EPS = 1.0


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


def rects_by_id(layout):
    out = {}
    def walk(n):
        out[n.id] = n.rect
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


def stroke_interior_hits(points, rect):
    hits = 0
    for i in range(len(points) - 1):
        hits += seg_interior_hits(points[i], points[i + 1], rect)
    return hits


def rects_overlap(a, b, eps=WALL_EPS):
    """Do two (x, y, x2, y2) boxes overlap by more than eps?"""
    return not (a[2] <= b[0] + eps or b[2] <= a[0] + eps
                or a[3] <= b[1] + eps or b[3] <= a[1] + eps)


def strip_rect(lg):
    return lg.strip


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
        rmap = rects_by_id(solved)
        crossings = []
        diagonals = []
        rotated = 0
        node_strikes = []
        wall_crossings = []
        labelled = 0

        labels = []   # (desc, strip) for label-label checks
        for i, e in enumerate(routed.edges):
            desc = f"{e.source_id} -> {e.target_id}" + (
                f" [{e.label}]" if e.label else "")
            src_anc = anc.get(e.source_id, set()) | {e.source_id}
            tgt_anc = anc.get(e.target_id, set()) | {e.target_id}
            exempt = src_anc | tgt_anc

            for j in range(len(e.points) - 1):
                p1, p2 = e.points[j], e.points[j + 1]
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

            if not e.label:
                continue
            labelled += 1
            pts = [(p.x, p.y) for p in e.points]
            lg = label_geometry(pts, e.label, 0.5)
            if lg.rotated:
                rotated += 1
            labels.append((desc, lg.strip))

            # Node strikes: strip vs non-exempt rects whose interior
            # the stroke itself clears (a stroke that crosses the node
            # is a crossing, counted above — router work either way).
            for nd in rects:
                if nd.id in exempt:
                    continue
                nr = (nd.rect.x, nd.rect.y, nd.rect.x2, nd.rect.y2)
                if not rects_overlap(lg.strip, nr):
                    continue
                if stroke_interior_hits(e.points, nd.rect):
                    continue
                node_strikes.append((desc, nd.id))

            # Wall crossings: for internal edges (both endpoints inside
            # the same container), the strip must stay within the
            # container's padded inner rect.
            common = (src_anc & tgt_anc)
            innermost = None
            for cid in common:
                if innermost is None or cid in anc.get(innermost, set()):
                    innermost = cid
            if innermost is not None:
                cr = rmap[innermost]
                inner = (cr.x + CONTAINER_PAD, cr.y + CONTAINER_PAD_TOP,
                         cr.x2 - CONTAINER_PAD, cr.y2 - CONTAINER_PAD)
                if not (lg.strip[0] >= inner[0] - WALL_EPS
                        and lg.strip[1] >= inner[1] - WALL_EPS
                        and lg.strip[2] <= inner[2] + WALL_EPS
                        and lg.strip[3] <= inner[3] + WALL_EPS):
                    wall_crossings.append((desc, innermost))

        label_clashes = []
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                if rects_overlap(labels[i][1], labels[j][1]):
                    label_clashes.append((labels[i][0], labels[j][0]))

        report[d.name] = dict(
            n_edges=len(routed.edges),
            crossings=crossings,
            diagonals=diagonals,
            rotated=rotated,
            labelled=labelled,
            node_strikes=node_strikes,
            wall_crossings=wall_crossings,
            label_clashes=label_clashes,
        )
    return report


def main():
    for path in sys.argv[1:]:
        report = audit_file(path)
        print(f"\n{'=' * 70}\n{path}\n{'=' * 70}")
        tc = td = tr = tns = twc = tl = 0
        te = tlab = 0
        for view, r in report.items():
            nc = len(set(c[0] for c in r["crossings"]))
            nd = len(r["diagonals"])
            nr = r["rotated"]
            nns = len(r["node_strikes"])
            nwc = len(r["wall_crossings"])
            nl = len(r["label_clashes"])
            te += r["n_edges"]
            tlab += r["labelled"]
            tc += nc; td += nd; tr += nr
            tns += nns; twc += nwc; tl += nl
            flag = "  <-- DEFECTS" if (nc or nd or nns or nwc or nl) else ""
            print(f"{view}: edges={r['n_edges']} "
                  f"crossing-edges={nc} diagonals={nd} "
                  f"rotated-labels={nr}/{r['labelled']} "
                  f"node-strikes={nns} wall-crossings={nwc} "
                  f"label-clashes={nl}{flag}")
        print(f"\nTOTAL {path}: edges={te} crossing-edges={tc} "
              f"diagonals={td} rotated-labels={tr}/{tlab} "
              f"node-strikes={tns} wall-crossings={twc} "
              f"label-clashes={tl}")

        print("\n--- detail ---")
        for view, r in report.items():
            for desc, obst, hits in r["crossings"]:
                print(f"  CROSS  {view}: {desc}  through {obst} (x{hits})")
            for desc, dx, dy in r["diagonals"]:
                print(f"  DIAG   {view}: {desc}  dx={dx} dy={dy}")
            for desc, obst in r["node_strikes"]:
                print(f"  NSTRIKE {view}: {desc}  strip strikes {obst}")
            for desc, cont in r["wall_crossings"]:
                print(f"  WALL   {view}: {desc}  strip crosses {cont} wall")
            for a, b in r["label_clashes"]:
                print(f"  LCLASH {view}: {a}  <->  {b}")


if __name__ == "__main__":
    main()
