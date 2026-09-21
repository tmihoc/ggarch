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
       .label_geometry) vs node rects the stroke itself clears, vs
       other labels, and vs the shared container's padded wall
     - strip crossings (ADR-003): an edge's swept strip vs earlier
       edges' strips — the router's own collision currency
     - residual crossings (ADR-003): the router-reported residuals of
       cheapest-collision paths (edge, obstacle, blocker)
     - turns per edge (ADR-003): bend counts, so the turn constant K
       is tuned on measured data, not guessed

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
from ggarch.geometry import STRIP_PAD, clip_strip, strip_hits_clip
from ggarch.router import ROUTE_STROKE_W

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


def border_rides(points, rmap, eps=0.5):
    """Segments collinear with a node face line and overlapping its
    span — a stroke riding a border instead of meeting the face
    perpendicularly (2026-09-21 hard law: never permitted). Returns
    (segment index, node id, overlap px)."""
    out = []
    for i in range(len(points) - 1):
        p1, p2 = points[i], points[i + 1]
        if math.hypot(p2.x - p1.x, p2.y - p1.y) < eps:
            continue
        if abs(p1.x - p2.x) < eps:      # vertical segment
            lo, hi = sorted((p1.y, p2.y))
            for nid, r in rmap.items():
                for x in (r.x, r.x2):
                    if abs(p1.x - x) < eps:
                        ov = min(hi, r.y2) - max(lo, r.y)
                        if ov > eps:
                            out.append((i, nid, round(ov, 1)))
                        break
        elif abs(p1.y - p2.y) < eps:    # horizontal segment
            lo, hi = sorted((p1.x, p2.x))
            for nid, r in rmap.items():
                for y in (r.y, r.y2):
                    if abs(p1.y - y) < eps:
                        ov = min(hi, r.x2) - max(lo, r.x)
                        if ov > eps:
                            out.append((i, nid, round(ov, 1)))
                        break
    return out


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
        rides = []
        labelled = 0

        labels = []   # (desc, strip) for label-label checks
        for i, e in enumerate(routed.edges):
            desc = f"{e.source_id} -> {e.target_id}" + (
                f" [{e.label}]" if e.label else "")
            src_anc = anc.get(e.source_id, set()) | {e.source_id}
            tgt_anc = anc.get(e.target_id, set()) | {e.target_id}
            exempt = src_anc | tgt_anc

            for _seg, nid, ov in border_rides(e.points, rmap):
                rides.append((desc, nid, ov))

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

        # Strip crossings (ADR-003): edge i's strip vs earlier strips
        # — the router's collision currency, measured independently of
        # the router's own reporting. Earlier strips are clipped against
        # the later edge's endpoint rects (ancestor-or-self, inflated):
        # the hug near a shared endpoint is by design, not a collision.
        strip_crossings = []
        clear = ROUTE_STROKE_W / 2 + STRIP_PAD
        for i, e in enumerate(routed.edges):
            if e.strip is None:
                continue
            ex = (anc.get(e.source_id, set()) | {e.source_id}
                  | anc.get(e.target_id, set()) | {e.target_id})
            boxes = [(rmap[n].x - clear - 5, rmap[n].y - clear - 5,
                      rmap[n].x2 + clear + 5, rmap[n].y2 + clear + 7)
                     for n in ex if n in rmap]
            for j in range(i):
                other = routed.edges[j]
                if other.strip is None:
                    continue
                if strip_hits_clip(e.strip, clip_strip(other.strip, boxes)):
                    strip_crossings.append((e.source_id, e.target_id,
                                            other.strip.owner))

        # Router-reported residuals (cheapest-collision paths) and
        # turns (the K tuning data).
        residuals = []
        turns = 0
        for e in routed.edges:
            turns += e.turns
            for kind, target in (e.residuals or []):
                residuals.append((f"{e.source_id} -> {e.target_id}"
                                  + (f" [{e.label}]" if e.label else ""),
                                  kind, target))

        # Annotation boxes are meta elements — but their rectangles are
        # still geometry: a box whose bounding rect overlaps a node that
        # is not one of its members is a drawing defect (review round 2,
        # the CMR "cross-model machinery" box swallowing endpoint_rec).
        ann_overlaps = []
        for ann in getattr(d, "annotations", []):
            if not hasattr(ann, "nodes") or not hasattr(ann, "padding"):
                continue
            members = [nid for nid in ann.nodes if nid in rmap]
            if not members:
                continue
            # Descendants of members are inside the box by containment,
            # not by accident.
            member_tree = set(members)
            for m in members:
                for nd in rects:
                    if m in ancestors_map(solved).get(nd.id, ()):
                        member_tree.add(nd.id)
            pt = ann.padding_top if ann.padding_top is not None \
                else ann.padding
            pr = ann.padding_right if ann.padding_right is not None \
                else ann.padding
            pb = ann.padding_bottom if ann.padding_bottom is not None \
                else ann.padding
            pl = ann.padding_left if ann.padding_left is not None \
                else ann.padding
            bx0 = min(rmap[m].x for m in members) - pl
            by0 = min(rmap[m].y for m in members) - pt
            bx1 = max(rmap[m].x2 for m in members) + pr
            by1 = max(rmap[m].y2 for m in members) + pb
            for nd in rects:
                if nd.id in member_tree:
                    continue
                r = nd.rect
                if not (r.x2 <= bx0 + WALL_EPS or bx1 <= r.x + WALL_EPS
                        or r.y2 <= by0 + WALL_EPS or by1 <= r.y + WALL_EPS):
                    ann_overlaps.append(
                        (ann.label or "<unlabelled box>", nd.id))

        # Node-node overlaps: two solved rects overlapping is always a
        # defect (authored arrangements with undeclared pairs, or floor
        # packing) — measured so it can never hide either.
        node_overlaps = []
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                ra, rb = rects[i].rect, rects[j].rect
                if not (ra.x2 <= rb.x + WALL_EPS or rb.x2 <= ra.x + WALL_EPS
                        or ra.y2 <= rb.y + WALL_EPS or rb.y2 <= ra.y + WALL_EPS):
                    if ra.x <= rb.x + WALL_EPS and rb.x2 <= ra.x2 + WALL_EPS \
                            and ra.y <= rb.y + WALL_EPS and rb.y2 <= ra.y2 + WALL_EPS:
                        continue  # containment (parent/child) is not overlap
                    if rb.x <= ra.x + WALL_EPS and ra.x2 <= rb.x2 + WALL_EPS \
                            and rb.y <= ra.y + WALL_EPS and ra.y2 <= rb.y2 + WALL_EPS:
                        continue
                    node_overlaps.append((rects[i].id, rects[j].id))

        report[d.name] = dict(
            n_edges=len(routed.edges),
            crossings=crossings,
            diagonals=diagonals,
            rotated=rotated,
            labelled=labelled,
            node_strikes=node_strikes,
            wall_crossings=wall_crossings,
            border_rides=rides,
            label_clashes=label_clashes,
            strip_crossings=strip_crossings,
            residuals=residuals,
            turns=turns,
            # Traceability (0.26.1): per-edge path/direct ratio and bend
            # count — the metric class the 0.26.0 review found hiding
            # behind green crossing metrics.
            ratios=[e.ratio for e in routed.edges],
            turns_list=[e.turns for e in routed.edges],
            ann_overlaps=ann_overlaps,
            node_overlaps=node_overlaps,
        )
    return report


def main(paths=None, gate=False):
    violations: list[str] = []
    for path in (paths if paths is not None else sys.argv[1:]):
        report = audit_file(path)
        print(f"\n{'=' * 70}\n{path}\n{'=' * 70}")
        tc = td = tr = tns = twc = tl = tsc = tres = tt = 0
        te = tlab = 0
        ratios_all = []
        turns_all = []
        for view, r in report.items():
            nc = len(set(c[0] for c in r["crossings"]))
            nd = len(r["diagonals"])
            nr = r["rotated"]
            nns = len(r["node_strikes"])
            nwc = len(r["wall_crossings"])
            nbr = len(r["border_rides"])
            nl = len(r["label_clashes"])
            nsc = len(set(s[0] + s[1] for s in r["strip_crossings"]))
            nres = len(set(x[0] for x in r["residuals"]))
            te += r["n_edges"]
            tlab += r["labelled"]
            tc += nc; td += nd; tr += nr
            tns += nns; twc += nwc; tl += nl
            tsc += nsc; tres += nres; tt += r["turns"]
            ratios_all += r["ratios"]
            turns_all += r["turns_list"]
            ratios = sorted(r["ratios"], reverse=True)
            over15 = sum(1 for x in ratios if x > 1.5)
            over2 = sum(1 for x in ratios if x > 2.0)
            hist: dict[int, int] = {}
            for t in r["turns_list"]:
                hist[t] = hist.get(t, 0) + 1
            if gate and (nc or nns or nwc or nbr):
                violations.append(
                    f"{path}:{view}: crossing-edges={nc} "
                    f"node-strikes={nns} wall-crossings={nwc} "
                    f"border-rides={nbr}")
            flag = "  <-- DEFECTS" if (nc or nsc or nres or nd or nns
                                       or nwc or nl or nbr) else ""
            print(f"{view}: edges={r['n_edges']} "
                  f"crossing-edges={nc} strip-crossings={nsc} "
                  f"residuals={nres} diagonals={nd} "
                  f"rotated-labels={nr}/{r['labelled']} "
                  f"node-strikes={nns} wall-crossings={nwc} "
                  f"border-rides={nbr} "
                  f"label-clashes={nl} turns/edge="
                  f"{r['turns'] / max(r['n_edges'], 1):.2f} "
                  f"max-ratio={max(ratios, default=0):.2f} "
                  f">1.5x={over15} >2x={over2} "
                  f">2-bend={sum(1 for t in r['turns_list'] if t > 2)}"
                  f"{flag}")
        ratios_all.sort(reverse=True)
        turn_hist: dict[int, int] = {}
        for t in turns_all:
            turn_hist[t] = turn_hist.get(t, 0) + 1
        print(f"\nTOTAL {path}: edges={te} crossing-edges={tc} "
              f"strip-crossings={tsc} residuals={tres} "
              f"diagonals={td} rotated-labels={tr}/{tlab} "
              f"node-strikes={tns} wall-crossings={twc} "
              f"label-clashes={tl} turns/edge="
              f"{tt / max(te, 1):.2f}")
        print(f"  traceability: max-ratio="
              f"{max(ratios_all, default=0):.2f} "
              f"p90={ratios_all[max(0, len(ratios_all) // 10)]:.2f} "
              f">1.5x={sum(1 for x in ratios_all if x > 1.5)} "
              f">2x={sum(1 for x in ratios_all if x > 2)} "
              f"turns-hist={dict(sorted(turn_hist.items()))} "
              f">2-bend={sum(1 for t in turns_all if t > 2)}")

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
            for desc, nid, ov in r["border_rides"]:
                print(f"  BRIDE  {view}: {desc}  rides {nid} border ({ov}px)")
            for a, b in r["label_clashes"]:
                print(f"  LCLASH {view}: {a}  <->  {b}")
            for s0, s1, owner in r["strip_crossings"]:
                print(f"  SCROSS {view}: {s0} -> {s1}  overlaps {owner}")
            for a, b in r.get("node_overlaps", []):
                print(f"  NOVER  {view}: {a}  overlaps {b}")
            for label, nid in r.get("ann_overlaps", []):
                print(f"  ANNOVER {view}: box [{label}]  overlaps node {nid}")
            for edge, kind, target in r["residuals"]:
                print(f"  RESID  {view}: {edge}  through {kind} {target}")
            for t in r["turns_list"]:
                if gate and t > 2:
                    violations.append(f"{path}:{view}: >2-bend route "
                                      f"({t} bends)")
        if gate:
            for x in ratios_all:
                if x > 2.0:
                    violations.append(f"{path}: ratio {x:.2f} > 2x")
            if violations:
                print("\nGATE FAILURES:")
                for v in violations:
                    print(f"  {v}")
                sys.exit(1)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    gate = "--gate" in args
    main([a for a in args if a != "--gate"], gate=gate)
